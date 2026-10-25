"""Backup cifrato, verifica e ripristino (anche su un altro PC / altro utente Windows).

Formato .gcbak:
  riga 1  b"GCBAK1\\n"
  riga 2  intestazione JSON (versione, schema, data, chiave dati cifrata con password e con
          codice di recupero, conteggi) + "\\n"
  resto   AES-256-GCM(DEK, zip{database coerente, allegati cifrati}) con intestazione come AAD.
Il database è copiato con l'API di backup di SQLite (copia coerente anche a programma aperto).
Entra anche il registro delle eliminazioni (solo identificativi interni), unito a quello locale al ripristino.
NON entrano nel backup: immagini dei documenti e testo OCR (esistono solo in memoria), log.
Il ripristino richiede la password o il codice di recupero: senza entrambi i dati non sono
recuperabili (nessuna chiave universale).
"""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import shutil
import sqlite3
import secrets
import string
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from .. import config
from ..db import SCHEMA_VERSION, AppError, connect, get_setting, now_iso, set_setting
from ..security import decrypt_bytes, encrypt_bytes, normalize_recovery, unwrap_key
from ..state import STATE

MAGIC = b"GCBAK1\n"
KEEP_LOCAL = 15
SAFETY_KEEP_DAYS = 30          # copie «prima_del_ripristino_*» (non cifrate): eliminate dopo 30 giorni
ZIP_MAX_ENTRIES = 100_000      # limiti alla decompressione di un backup (anche se autenticato)
ZIP_MAX_BYTES = 4 * 1024 ** 3
LEDGER_IN_ZIP = "registro_eliminazioni.json"
# backup e ripristino non passano dal lock delle scritture API: si serializzano tra loro
_LOCK = threading.RLock()


def _tmp_name(prefix: str) -> Path:
    return config.data_dir() / f"{prefix}_{os.getpid()}_{secrets.token_hex(4)}.sqlite3"


def _move(src: Path, dst: Path) -> None:
    """Rinomina con brevi tentativi ripetuti: su Windows antivirus e indicizzazione tengono aperti per un attimo
    i file appena scritti e lo spostamento di una cartella può fallire con «Accesso negato»."""
    import time
    for i in range(40):
        try:
            if dst.is_dir() and not any(dst.iterdir()):
                dst.rmdir()  # config.data_dir() ricrea «allegati» vuota se un'altra richiesta la cerca nel frattempo
            os.replace(src, dst)
            return
        except PermissionError:
            if i == 39:
                raise
            time.sleep(0.05 * (1 + i // 10))


def _check_zip(z: zipfile.ZipFile) -> None:
    infos = z.infolist()
    if len(infos) > ZIP_MAX_ENTRIES or sum(i.file_size for i in infos) > ZIP_MAX_BYTES:
        raise AppError("Backup non valido (contenuto eccessivo).")


def _counts(conn) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {"prenotazioni": q("SELECT COUNT(*) FROM bookings"), "ospiti": q("SELECT COUNT(*) FROM guests"),
            "movimenti": q("SELECT COUNT(*) FROM movements"), "allegati": q("SELECT COUNT(*) FROM attachments"),
            "lotti": q("SELECT COUNT(*) FROM export_batches"),
            "ultima_prenotazione": conn.execute("SELECT MAX(arrival) FROM bookings").fetchone()[0]}


def create_bytes(conn: sqlite3.Connection) -> tuple[bytes, dict]:
    dek = STATE.require_dek()
    kr = conn.execute("SELECT * FROM keyring WHERE id=1").fetchone()
    tmp = _tmp_name("tmp_backup")
    try:
        dst = sqlite3.connect(str(tmp))
        conn.backup(dst)
        dst.close()
        db_bytes = tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("gestionale.sqlite3", db_bytes)
        att = config.data_dir() / "allegati"
        for f in sorted(att.glob("*.bin")):
            z.write(f, f"allegati/{f.name}")
        from . import retention
        z.writestr(LEDGER_IN_ZIP, json.dumps(retention.ledger()))
    header = {"app": config.APP_ID, "app_version": config.VERSION, "schema": SCHEMA_VERSION,
              "created_at": now_iso(), "wrapped_pw": kr["wrapped_pw"], "wrapped_recovery": kr["wrapped_recovery"],
              "db_sha256": hashlib.sha256(db_bytes).hexdigest(), "counts": _counts(conn)}
    hb = json.dumps(header).encode("utf-8")
    payload = encrypt_bytes(dek, buf.getvalue(), aad=hb)
    return MAGIC + hb + b"\n" + payload, header


def _record(conn, ok: bool, where: str, err: str | None = None, external: bool = False) -> None:
    b = get_setting(conn, "backup", {}) or {}
    key = "external" if external else "local"
    if ok:
        b[f"{key}_last_ok_at"] = now_iso()
        b[f"{key}_last_ok_path"] = where
        b[f"{key}_last_error"] = None
    else:
        b[f"{key}_last_error"] = f"{now_iso()}: {err}"
    set_setting(conn, "backup", b)


def create_local(conn: sqlite3.Connection, label: str = "") -> Path:
    with _LOCK:
        return _create_local(conn, label)


def _create_local(conn: sqlite3.Connection, label: str) -> Path:
    try:
        data, header = create_bytes(conn)
        base = f"backup_{datetime.now(config.TZ):%Y%m%d_%H%M%S}{('_' + label) if label else ''}"
        path = config.data_dir() / "backup" / f"{base}.gcbak"
        n = 1
        while path.exists():  # due backup nello stesso secondo: nome progressivo
            n += 1
            path = config.data_dir() / "backup" / f"{base}_{n}.gcbak"
        tmp = path.with_suffix(".parziale")
        tmp.write_bytes(data)
        verify_bytes(tmp.read_bytes(), dek=STATE.require_dek())  # rilettura e verifica prima di confermare
        os.replace(tmp, path)
        olds = sorted((config.data_dir() / "backup").glob("backup_*.gcbak"))
        for o in olds[:-KEEP_LOCAL]:
            o.unlink(missing_ok=True)
        _record(conn, True, str(path))
        return path
    except AppError as ex:
        _record(conn, False, "", ex.message)
        raise
    except Exception as ex:
        _record(conn, False, "", f"{type(ex).__name__}")
        raise AppError(f"Backup non riuscito ({type(ex).__name__}). Riprovare; i dati attuali non sono stati "
                       f"modificati.")


def copy_external(conn: sqlite3.Connection, target_dir: str) -> Path:
    """Copia l'ultimo backup verificato sul supporto scelto (chiavetta, disco esterno, cartella)."""
    raw = (target_dir or "").strip().strip('"')
    if not raw:
        raise AppError("Indicare la chiavetta o la cartella di destinazione.", field="dir")
    tdir = Path(raw)
    if not tdir.is_absolute():
        # un percorso relativo finirebbe nella cartella del programma, non sulla chiavetta
        raise AppError("Indicare il percorso completo della destinazione (es. E:\\ oppure E:\\Backup).", field="dir")
    if not tdir.exists() or not tdir.is_dir():
        _record(conn, False, "", "cartella di destinazione non trovata", external=True)
        raise AppError("Cartella di destinazione non trovata. Se è una chiavetta, controllare che sia inserita "
                       "e la lettera dell'unità.")
    src = create_local(conn, "copia")
    dst_dir = tdir / "Backup HolidayGest"
    try:
        dst_dir.mkdir(exist_ok=True)
        dst = dst_dir / src.name
        tmp = dst.with_suffix(".parziale")
        shutil.copyfile(src, tmp)
        if hashlib.sha256(tmp.read_bytes()).digest() != hashlib.sha256(src.read_bytes()).digest():
            raise OSError("copia non identica")
        os.replace(tmp, dst)
    except OSError as ex:
        _record(conn, False, "", f"scrittura non riuscita: {ex.strerror or ex}", external=True)
        raise AppError("Impossibile scrivere sul supporto scelto (protetto da scrittura, pieno o rimosso).")
    b = get_setting(conn, "backup", {}) or {}
    b["external_dir"] = str(tdir)
    set_setting(conn, "backup", b)
    _record(conn, True, str(dst), external=True)
    return dst


def removable_drives() -> list[dict]:
    out = []
    if os.name != "nt":
        return out
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            t = ctypes.windll.kernel32.GetDriveTypeW(root)
            if t == 2:  # DRIVE_REMOVABLE
                out.append({"path": root, "label": f"Unità rimovibile {letter}:"})
    return out


def read_header(data: bytes) -> tuple[dict, bytes, bytes]:
    if not data.startswith(MAGIC):
        raise AppError("Il file scelto non è un backup del gestionale.")
    rest = data[len(MAGIC):]
    nl = rest.find(b"\n")
    if nl < 0:
        raise AppError("Backup danneggiato (intestazione incompleta).")
    hb = rest[:nl]
    try:
        header = json.loads(hb.decode("utf-8"))
    except ValueError:
        raise AppError("Backup danneggiato (intestazione illeggibile).")
    if header.get("app") != config.APP_ID:
        raise AppError("Il backup appartiene a un altro programma.")
    if int(header.get("schema", 0)) > SCHEMA_VERSION:
        raise AppError("Il backup è stato creato da una versione più recente del programma: aggiornare prima "
                       "il programma.")
    return header, hb, rest[nl + 1:]


def unlock_dek(header: dict, secret: str) -> bytes:
    dek = unwrap_key(header["wrapped_pw"], secret)
    if dek is None:
        dek = unwrap_key(header["wrapped_recovery"], normalize_recovery(secret))
    if dek is None:
        raise AppError("Password o codice di recupero non corretti per questo backup.", 403)
    return dek


def verify_bytes(data: bytes, dek: bytes | None = None, secret: str | None = None) -> dict:
    header, hb, payload = read_header(data)
    if dek is None:
        dek = unlock_dek(header, secret or "")
    try:
        plain = decrypt_bytes(dek, payload, aad=hb)
    except Exception:
        raise AppError("Backup danneggiato o chiave non corrispondente (verifica di integrità fallita).")
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        _check_zip(z)
        db_bytes = z.read("gestionale.sqlite3")
        n_att = len([n for n in z.namelist() if n.startswith("allegati/")])
    if hashlib.sha256(db_bytes).hexdigest() != header["db_sha256"]:
        raise AppError("Backup danneggiato (impronta del database non corrispondente).")
    tmp = _tmp_name("tmp_verifica")
    try:
        tmp.write_bytes(db_bytes)
        c = sqlite3.connect(str(tmp))
        try:
            res = c.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                raise AppError("Il database contenuto nel backup non supera il controllo di integrità.")
            counts = {"prenotazioni": c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
                      "ospiti": c.execute("SELECT COUNT(*) FROM guests").fetchone()[0],
                      "movimenti": c.execute("SELECT COUNT(*) FROM movements").fetchone()[0]}
        finally:
            c.close()
    finally:
        tmp.unlink(missing_ok=True)
    return {"header": {k: v for k, v in header.items() if not k.startswith("wrapped")}, "counts": counts,
            "attachments": n_att, "ok": True}


def _archive_in_use(dbp) -> bool:
    """True se sul PC c'è un archivio già configurato (utente creato). Il database vuoto creato all'avvio di un
    PC nuovo non conta: lì il ripristino dalla prima schermata non deve chiedere di «sostituire» nulla."""
    if not (dbp.exists() and dbp.stat().st_size > 0):
        return False
    c = sqlite3.connect(str(dbp))
    try:
        return bool(c.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    except sqlite3.Error:
        return True  # file non leggibile: prudenza, chiedere conferma e farne copia
    finally:
        c.close()


def purge_old_safety_copies() -> int:
    """Le copie «prima_del_ripristino_*» contengono il database non cifrato: eliminate dopo SAFETY_KEEP_DAYS."""
    import time
    limit, n = time.time() - SAFETY_KEEP_DAYS * 86400, 0
    for d in (config.data_dir() / "backup").glob("prima_del_ripristino_*"):
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d)
                n += 1
        except OSError:
            pass
    return n


def restore(data: bytes, secret: str, confirm_replace: bool) -> dict:
    with _LOCK:
        return _restore(data, secret, confirm_replace)


def _restore(data: bytes, secret: str, confirm_replace: bool) -> dict:
    """Ripristino sicuro: verifica completa -> copia di sicurezza dell'archivio attuale -> preparazione dei nuovi
    file accanto ai vecchi -> scambio (allegati, poi database come ultimo passo atomico) con ritorno indietro."""
    header, hb, payload = read_header(data)
    dek = unlock_dek(header, secret)
    report = verify_bytes(data, dek=dek)
    dbp = config.db_path()
    exists = _archive_in_use(dbp)
    if exists and not confirm_replace:
        raise AppError("Esiste già un archivio su questo PC: confermare la sostituzione (verrà prima salvata "
                       "una copia di sicurezza).", extra=report)
    plain = decrypt_bytes(dek, payload, aad=hb)
    ddir = config.data_dir()
    stamp = datetime.now(config.TZ).strftime("%Y%m%d_%H%M%S")
    safety = ddir / "backup" / f"prima_del_ripristino_{stamp}"
    if exists:
        safety.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(dbp))
        dst = sqlite3.connect(str(safety / "gestionale.sqlite3"))
        src.backup(dst)
        dst.close()
        src.close()
        if (ddir / "allegati").exists():
            shutil.copytree(ddir / "allegati", safety / "allegati", dirs_exist_ok=True)
    new_db = ddir / f"ripristino_{stamp}.sqlite3"
    staging = ddir / f"allegati_ripristino_{stamp}"
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        _check_zip(z)
        new_db.write_bytes(z.read("gestionale.sqlite3"))
        staging.mkdir()
        for n in z.namelist():
            if n.startswith("allegati/") and n.endswith(".bin") and "/" not in n[9:] and ".." not in n:
                (staging / Path(n).name).write_bytes(z.read(n))
        backup_ledger = json.loads(z.read(LEDGER_IN_ZIP)) if LEDGER_IN_ZIP in z.namelist() else []
    att = ddir / "allegati"
    parked = ddir / f"allegati_precedenti_{stamp}"
    try:
        if att.exists():
            _move(att, parked)               # 1. allegati attuali messi da parte (reversibile)
        _move(staging, att)                  # 2. nuovi allegati al loro posto
        for suffix in ("-wal", "-shm"):
            Path(str(dbp) + suffix).unlink(missing_ok=True)
        os.replace(new_db, dbp)              # 3. database: ultimo passo, atomico
    except OSError:
        # ritorno allo stato precedente: database invariato, allegati originali rimessi a posto
        if parked.exists():
            if att.exists() and any(att.iterdir()):
                _move(att, ddir / f"allegati_scartati_{stamp}")
            _move(parked, att)
            shutil.rmtree(ddir / f"allegati_scartati_{stamp}", ignore_errors=True)
        new_db.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        raise AppError("Ripristino non riuscito (file in uso o disco non scrivibile): l'archivio attuale è "
                       "rimasto invariato. Chiudere altri programmi e riprovare.")
    shutil.rmtree(parked, ignore_errors=True)
    from . import retention
    retention.ledger_merge(backup_ledger)
    from ..db import init_db
    init_db()
    STATE.dek = dek
    conn = connect()
    try:
        applied = retention.after_restore(conn)
    finally:
        conn.close()
    report["safety_copy"] = str(safety) if exists else None
    report["retention_reapplied"] = applied
    return report
