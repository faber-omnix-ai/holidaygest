"""Proposte dal FRONTE dei documenti italiani (testo OCR locale), senza MRZ.

Copre i modelli più comuni: carta d'identità elettronica (CIE), carta d'identità cartacea, patente di guida
(campi numerati 1-5 del modello europeo). È un'euristica sul testo: ogni valore è restituito con stato
«dubbio» e va confrontato con il documento. Nessun valore viene mai marcato «letto»: quello vale solo per la
MRZ con cifre di controllo corrette. Il testo non viene salvato né registrato.
"""
from __future__ import annotations

import re
import unicodedata

from . import tables

DUBBIO = "dubbio"
_LABELS = ("COGNOME", "SURNAME", "NOME", "NAME", "LUOGO", "PLACE", "DATA", "DATE", "SESSO", "SEX", "STATURA",
           "HEIGHT", "CITTADINANZA", "NATIONALITY", "EMISSIONE", "ISSUING", "SCADENZA", "EXPIRY", "FIRMA",
           "SIGNATURE", "COMUNE", "MUNICIPALITY", "REPUBBLICA", "CARTA", "IDENTITA", "IDENTITY", "PATENTE",
           "MINISTERO", "ESTREMI", "INDIRIZZO", "RESIDENZA", "STATO", "CIVILE", "PROFESSIONE", "CONNOTATI",
           "NASCITA", "BIRTH")
_STOP = {"E", "DI", "OF", "AND", "IL", "A", "DEL", "DELLA"}  # solo per riconoscere le righe-etichetta
_DATE = re.compile(r"\b(\d{1,2})[./\- ](\d{1,2})[./\- ](\d{4}|\d{2})\b")
_COMUNE_PROV = re.compile(r"([A-Z][A-Z' \-]{1,40}?)\s*\(\s*([A-Z]{2})\s*\)")
_CIE_NUM = re.compile(r"\b([A-Z]{2}\s?\d{5}\s?[A-Z]{2})\b")
_PAPER_ID_NUM = re.compile(r"\b([A-Z]{2}\s?\d{7})\b")
_PATENTE_NUM = re.compile(r"\b([A-Z]{1,2}\d[A-Z0-9]{6,7}[A-Z])\b")


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.upper()).strip()


def _is_label(line: str) -> bool:
    words = [w for w in re.findall(r"[A-Z]+", line) if w not in _STOP]
    return bool(words) and sum(w in _LABELS for w in words) >= max(1, (len(words) + 1) // 2)


def _strip_labels(line: str) -> str:
    out = line
    for lab in sorted(_LABELS, key=len, reverse=True):
        out = re.sub(rf"\b{lab}\b", " ", out)
    return re.sub(r"^[\s/:.\-|]+|[\s/:.\-|]+$", "", re.sub(r"\s+", " ", out)).strip()


def _after(lines: list[str], *keys: str, max_ahead: int = 2) -> str | None:
    """Valore che segue un'etichetta: sulla stessa riga (dopo l'etichetta) o nelle righe successive."""
    for i, ln in enumerate(lines):
        if not any(re.search(rf"\b{k}\b", ln) for k in keys):
            continue
        same = _strip_labels(ln)
        words = [w for w in re.findall(r"[A-Z]+", ln) if w not in _STOP]
        labels = sum(w in _LABELS for w in words)
        if labels >= 2 and labels * 2 >= len(words):
            same = ""  # riga di sole etichette (eventualmente storpiate dall'OCR): il valore è sotto
        if same and not set(re.findall(r"[A-Z]+", same)) <= _STOP and not _is_label(same):
            return same
        for nxt in lines[i + 1:i + 1 + max_ahead]:
            if nxt and not _is_label(nxt):
                return _strip_labels(nxt) or None
    return None


def _date_iso(m: re.Match, birth: bool = True) -> str | None:
    dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
    if len(yy) == 2:
        y = int(yy)
        y += 1900 if birth and y > 30 else 2000  # anno a due cifre (patente): ipotesi da verificare
    else:
        y = int(yy)
    if not (1 <= dd <= 31 and 1 <= mm <= 12 and 1900 <= y <= 2100):
        return None
    return f"{y:04d}-{mm:02d}-{dd:02d}"


def _comune(name: str, prov: str | None, on: str | None) -> dict | None:
    name = _plain(name).strip(" -'")
    hits = [c for c in tables.load()["comuni"].values() if c["name"] == name and (not prov or c["prov"] == prov)]
    if not hits:
        return None
    valid = [c for c in hits if not c["end"] or not on or on <= c["end"]]
    return (valid or hits)[0]


def _f(value) -> dict:
    return {"value": value, "status": DUBBIO, "source": "fronte"}


def parse(text: str) -> dict:
    lines = [_plain(x) for x in (text or "").splitlines() if x.strip()]
    joined = "\n".join(lines)
    out: dict = {}
    notes: list[str] = []
    patente = "PATENTE" in joined or sum(bool(re.match(r"^[1-5][ABC]?\s*[.)]", ln)) for ln in lines) >= 3
    if patente:
        num = {}
        for ln in lines:
            m = re.match(r"^([1-5][ABC]?)\s*[.)]\s*(.+)$", ln)
            if m and m.group(1) not in num:
                num[m.group(1)] = m.group(2).strip()
        if num.get("1"):
            out["surname"] = _f(num["1"])
        if num.get("2"):
            out["name"] = _f(num["2"])
        if num.get("3"):
            m = _DATE.search(num["3"])
            if m and _date_iso(m):
                out["birth_date"] = _f(_date_iso(m))
            place = _COMUNE_PROV.search(num["3"][m.end():] if m else num["3"])
            if place:
                out["_birth_place"] = (place.group(1), place.group(2))
        if num.get("5"):
            pm = _PATENTE_NUM.search(num["5"].replace(" ", ""))
            if pm:
                out["doc.number"] = _f(pm.group(1))
        out["doc.type"] = _f("PATEN")
        notes.append("Patente di guida riconosciuta dai campi numerati: il luogo di rilascio (campo 4c) va "
                     "indicato a mano secondo le istruzioni di Alloggiati Web.")
    else:
        sur = _after(lines, "COGNOME", "SURNAME")
        if sur:
            out["surname"] = _f(sur)
        nm = _after(lines, "NOME", "NAME")
        if nm and nm != sur:
            out["name"] = _f(nm)
        sx = _after(lines, "SESSO", "SEX", max_ahead=1)
        if sx and sx[:1] in ("M", "F") and len(sx.split()[0]) == 1:
            out["sex"] = _f(sx[:1])
        birth_line = _after(lines, "LUOGO E DATA DI NASCITA", "NASCITA", "BIRTH", "NATO", "NATA", max_ahead=2) or ""
        m = _DATE.search(birth_line)
        if not m:  # carta cartacea: «nato il 10/05/1980»
            for ln in lines:
                if re.search(r"\bNAT[OA]\b", ln) and _DATE.search(ln):
                    m = _DATE.search(ln)
                    birth_line = ln
                    break
        if m and _date_iso(m):
            out["birth_date"] = _f(_date_iso(m))
        place = _COMUNE_PROV.search(birth_line)
        if not place:
            for ln in lines:  # «a ALGHERO (SS)» sulla riga successiva
                if re.match(r"^A\s+[A-Z]", ln) and _COMUNE_PROV.search(ln):
                    place = _COMUNE_PROV.search(ln[2:])
                    break
        if place:
            out["_birth_place"] = (place.group(1), place.group(2))
        cit = _after(lines, "CITTADINANZA", "NATIONALITY", max_ahead=1)
        if cit and re.search(r"\bITA(LIANA)?\b", cit):
            out["citizenship_code"] = _f(tables.ITALIA)
        cie = _CIE_NUM.search(joined)
        paper = _PAPER_ID_NUM.search(joined)
        if cie and ("ELETTRONICA" in joined or "IDENTITY CARD" in joined or "CARTA DI IDENTITA" in joined):
            out["doc.number"] = _f(cie.group(1).replace(" ", ""))
            out["doc.type"] = _f("IDELE")
        elif paper and "CARTA" in joined and "IDENTITA" in joined:
            out["doc.number"] = _f(paper.group(1).replace(" ", ""))
            out["doc.type"] = _f("IDENT")
        issuer = re.search(r"\bCOMUNE DI\s+([A-Z][A-Z' \-]{1,40})", joined)
        name = issuer.group(1).split("\n")[0] if issuer else _after(lines, "MUNICIPALITY", max_ahead=1)
        if name:
            c = _comune(name, None, None)
            if c:
                out["doc.issue_place"] = _f(c["code"])
    bp = out.pop("_birth_place", None)
    if bp:
        c = _comune(bp[0], bp[1], (out.get("birth_date") or {}).get("value"))
        if c:
            out["birth_comune_code"] = _f(c["code"])
            out["birth_state_code"] = _f(tables.ITALIA)
        else:
            notes.append(f"Luogo di nascita letto «{bp[0].strip()} ({bp[1]})» non trovato nella tabella dei comuni: "
                         f"sceglierlo dall'elenco.")
    if out:
        notes.append("Campi proposti dal fronte del documento con lettura del testo: tutti DA VERIFICARE.")
    return {"fields": out, "notes": notes}


def combine(mrz_fields: dict, front_fields: dict) -> tuple[dict, list[str]]:
    """MRZ prevale; se il fronte dice altro il campo diventa «dubbio» con nota."""
    out = {k: dict(v) for k, v in mrz_fields.items()}
    notes = []
    for k, v in front_fields.items():
        if k not in out or out[k].get("value") in (None, ""):
            out[k] = v
        elif _plain(str(out[k]["value"])) != _plain(str(v["value"])):
            out[k]["status"] = DUBBIO
            notes.append(f"{k}: MRZ «{out[k]['value']}», fronte «{v['value']}» — verificare sul documento.")
    return out, notes
