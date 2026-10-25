"""Tabelle ufficiali Alloggiati Web (Comuni, Stati, Documenti, Tipo alloggiato).

Versione inclusa nel pacchetto in app/data/tabelle, con provenienza in meta.json.
Un aggiornamento importato dall'utente (file CSV scaricati dal portale) viene salvato
nella cartella dati/tabelle e ha precedenza; la versione in uso è sempre dichiarata.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
from datetime import date
from pathlib import Path

from .. import config
from ..db import AppError

FILES = {"comuni": "comuni.csv", "stati": "stati.csv", "documenti": "documenti.csv",
         "tipo_alloggiato": "tipo_alloggiato.csv"}
ITALIA = "100000100"
_lock = threading.Lock()
_cache: dict | None = None


def _dirs() -> list[Path]:
    return [config.data_dir() / "tabelle", config.bundled_data_dir() / "tabelle"]


def _source_dir() -> Path:
    user = config.data_dir() / "tabelle"
    if all((user / f).exists() for f in FILES.values()) and (user / "meta.json").exists():
        return user
    return config.bundled_data_dir() / "tabelle"


def _parse_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    g, m, a = s[:10].split("/")
    return date(int(a), int(m), int(g)).isoformat()


def load() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        src = _source_dir()
        t: dict = {"meta": json.loads((src / "meta.json").read_text(encoding="utf-8")), "dir": str(src)}
        for key, fn in FILES.items():
            text = (src / fn).read_text(encoding="utf-8-sig", errors="strict")
            rdr = csv.DictReader(io.StringIO(text))
            items = {}
            for r in rdr:
                code = (r.get("Codice") or "").strip()
                if not code:
                    continue
                items[code] = {"code": code, "name": (r.get("Descrizione") or "").strip(),
                               "prov": (r.get("Provincia") or "").strip(),
                               "end": _parse_date(r.get("DataFineVal") or "")}
            t[key] = items
        _cache = t
        return t


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def version_label() -> str:
    m = load()["meta"]
    sc = m.get('scaricato_il') or ''
    sc = f"{sc[8:10]}/{sc[5:7]}/{sc[:4]}" if len(sc) == 10 else sc
    return f"Tabelle Alloggiati scaricate il {sc} ({m.get('fonte')})"


def search(kind: str, q: str, limit: int = 20, on_date: str | None = None) -> list[dict]:
    t = load().get(kind)
    if t is None:
        raise AppError("Tabella sconosciuta")
    q = (q or "").strip().upper()
    out = []
    for it in t.values():
        if not q or it["name"].startswith(q) or it["code"] == q:
            item = dict(it)
            item["soppresso"] = bool(it["end"] and (on_date or date.today().isoformat()) > it["end"])
            out.append(item)
    out.sort(key=lambda x: (x["soppresso"], x["name"] != q, x["name"]))
    return out[:limit]


def get(kind: str, code: str | None) -> dict | None:
    if not code:
        return None
    return load()[kind].get(code)


def valid_on(kind: str, code: str, when: str | None) -> tuple[bool, str | None]:
    """Codice esistente e valido alla data (es. comune di nascita alla data di nascita)."""
    it = get(kind, code)
    if not it:
        return False, f"codice {code} non presente nella tabella ufficiale {kind}"
    if it["end"] and when and when > it["end"]:
        return False, f"{it['name']} ({code}) cessato il {it['end'][8:10]}/{it['end'][5:7]}/{it['end'][:4]}: verificare il codice valido alla data"
    return True, None


def import_update(files: dict[str, bytes]) -> dict:
    """Importa CSV ufficiali scaricati dall'utente; controlla intestazioni e codici prima di attivarli."""
    dst = config.data_dir() / "tabelle"
    dst.mkdir(exist_ok=True)
    meta = {"fonte": "Importazione manuale da file scaricati dal portale Alloggiati Web",
            "scaricato_il": date.today().isoformat(), "file": {}}
    staged = {}
    for key, fn in FILES.items():
        data = files.get(key)
        if data is None:
            raise AppError(f"Manca il file {fn}.")
        text = data.decode("utf-8-sig")
        rdr = csv.DictReader(io.StringIO(text))
        if not rdr.fieldnames or "Codice" not in rdr.fieldnames or "Descrizione" not in rdr.fieldnames:
            raise AppError(f"{fn}: intestazione non riconosciuta (attese colonne Codice, Descrizione).")
        n = sum(1 for r in rdr if (r.get("Codice") or "").strip())
        if n == 0:
            raise AppError(f"{fn}: nessun codice trovato.")
        staged[fn] = data
        meta["file"][fn] = {"sha256": hashlib.sha256(data).hexdigest(), "righe": n}
    for fn, data in staged.items():
        (dst / fn).write_bytes(data)
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    reset_cache()
    return meta
