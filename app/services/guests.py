"""Ospiti: anagrafica operativa, dati documentali cifrati, permanenze individuali, verifica.

Il referente della prenotazione NON è automaticamente un ospite: gli ospiti sono solo
quelli inseriti qui. Ogni ospite ha la propria permanenza (prevista ed effettiva).
I dati documentali (tipo, numero, luogo di rilascio) servono solo ad Alloggiati Web:
sono cifrati e vengono eliminati dopo l'acquisizione della ricevuta.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from ..db import AppError, audit, now_iso, row, rows
from ..security import decrypt_json, encrypt_json
from ..state import STATE
from ..util import age_on, d
from . import tables

GUEST_TYPES = {"16": "Ospite singolo", "17": "Capofamiglia", "18": "Capogruppo", "19": "Familiare",
               "20": "Componente gruppo"}
LEADER_FOR = {"19": "17", "20": "18"}
BASE_FIELDS = ("guest_type", "leader_guest_id", "surname", "name", "sex", "birth_date", "birth_state_code",
               "birth_comune_code", "citizenship_code", "res_state_code", "res_comune_code", "res_place_text",
               "planned_arrival", "planned_departure", "continues_guest_id", "tax_status", "exemption_doc_ok",
               "exemption_for_guest", "position")
FLAG_VALUES = ("letto", "corretto", "mancante", "dubbio", "manuale")
_NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'’\- .]+$")


def _norm(s) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


def _doc_ctx(guest_id: int) -> str:
    return f"guests.doc_enc:{guest_id}"


def doc_of(g: dict) -> dict:
    if not g.get("doc_enc"):
        return {}
    return decrypt_json(STATE.require_dek(), g["doc_enc"], _doc_ctx(g["id"])) or {}


def public(g: dict, with_doc: bool = False) -> dict:
    """Vista per l'interfaccia. I dati documentali solo quando servono (scheda ospite/verifica)."""
    out = {k: v for k, v in g.items() if k != "doc_enc"}
    out["has_doc"] = bool(g.get("doc_enc"))
    out["field_flags"] = json.loads(g.get("field_flags") or "{}")
    if with_doc and g.get("doc_enc"):
        out["doc"] = doc_of(g)
    return out


def _apply(conn, booking: dict, data: dict, current: dict | None) -> tuple[dict, dict | None]:
    g = dict(current or {})
    for k in BASE_FIELDS:
        if k in data:
            g[k] = data[k]
    for k in ("surname", "name", "res_place_text"):
        g[k] = _norm(g.get(k))
    if not g.get("surname") or not g.get("name"):
        raise AppError("Cognome e nome sono obbligatori anche in bozza.", field="surname")
    if g.get("guest_type") not in GUEST_TYPES:
        raise AppError("Indicare la tipologia di alloggiato.", field="guest_type")
    if g.get("sex") not in (None, "", "M", "F"):
        raise AppError("Sesso non valido: indicare M o F come richiesto dal tracciato.", field="sex")
    g["sex"] = g.get("sex") or None
    for k in ("birth_date", "planned_arrival", "planned_departure"):
        g[k] = d(g[k], k).isoformat() if g.get(k) else None
    for k in ("birth_state_code", "birth_comune_code", "citizenship_code", "res_state_code", "res_comune_code"):
        g[k] = _norm(g.get(k))
    if g.get("birth_state_code") and g["birth_state_code"] != tables.ITALIA:
        g["birth_comune_code"] = None
    if g.get("birth_comune_code"):
        c = tables.get("comuni", g["birth_comune_code"])
        g["birth_province"] = c["prov"] if c else None
    else:
        g["birth_province"] = None
    pa = g.get("planned_arrival") or booking["arrival"]
    pd = g.get("planned_departure") or booking["departure"]
    if pd <= pa:
        raise AppError("La partenza prevista dell'ospite deve seguire l'arrivo previsto.", field="planned_departure")
    if pa < booking["arrival"] or pd > booking["departure"]:
        raise AppError("Il periodo previsto dell'ospite deve rientrare nel periodo della prenotazione: "
                       "modificare prima le date della prenotazione.", field="planned_arrival")
    if g.get("guest_type") in LEADER_FOR:
        lid = g.get("leader_guest_id")
        leader = row(conn.execute("SELECT id, guest_type FROM guests WHERE id=? AND booking_id=?",
                                  (lid, booking["id"]))) if lid else None
        if not leader or leader["guest_type"] != LEADER_FOR[g["guest_type"]]:
            need = GUEST_TYPES[LEADER_FOR[g["guest_type"]]]
            raise AppError(f"{GUEST_TYPES[g['guest_type']]}: indicare il {need.lower()} della stessa prenotazione.",
                           field="leader_guest_id")
    else:
        g["leader_guest_id"] = None
    from .tax import TAX_STATUSES
    if (g.get("tax_status") or "ordinario") not in TAX_STATUSES:
        raise AppError("Posizione fiscale non valida.", field="tax_status")
    g["tax_status"] = g.get("tax_status") or "ordinario"
    g["exemption_doc_ok"] = 1 if g.get("exemption_doc_ok") in (1, True, "1", "true", "on") else 0
    if g["tax_status"] != "accompagnatore":
        g["exemption_for_guest"] = None
    doc = None
    if "doc" in data:
        dd = data.get("doc") or {}
        doc = {"type": _norm(dd.get("type")), "number": _norm(dd.get("number")),
               "issue_place": _norm(dd.get("issue_place"))}
        if doc["number"]:
            doc["number"] = doc["number"].upper().replace(" ", "")
    return g, doc


def save(conn: sqlite3.Connection, booking_id: int, data: dict, guest_id: int | None = None) -> dict:
    b = row(conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)))
    if not b:
        raise AppError("Prenotazione inesistente.", 404)
    cur = None
    if guest_id:
        cur = row(conn.execute("SELECT * FROM guests WHERE id=? AND booking_id=?", (guest_id, booking_id)))
        if not cur:
            raise AppError("Ospite inesistente.", 404)
        if cur.get("anonymized_at"):
            raise AppError("Ospite anonimizzato: non modificabile.")
        if data.get("version") is not None and int(data["version"]) != cur["version"]:
            raise AppError("Scheda ospite modificata in un'altra finestra: ricaricare.", 409)
    g, doc = _apply(conn, b, data, cur)
    flags = json.loads((cur or {}).get("field_flags") or "{}")
    for k, v in (data.get("field_flags") or {}).items():
        if v in FLAG_VALUES:
            flags[k] = v
    ts = now_iso()
    enc = None
    if doc is not None and cur:
        enc = encrypt_json(STATE.require_dek(), doc, _doc_ctx(guest_id)) if any(doc.values()) else None
    vals = {k: g.get(k) for k in BASE_FIELDS}
    vals["birth_province"] = g.get("birth_province")
    vals["field_flags"] = json.dumps(flags)
    if data.get("data_origin") in ("manuale", "documento"):
        vals["data_origin"] = data["data_origin"]
    if cur:
        changed_identity = any(cur.get(k) != vals.get(k) for k in BASE_FIELDS[:12]) or doc is not None and \
            (doc_of(cur) or {}) != doc
        if doc is not None:
            vals["doc_enc"] = enc
        if changed_identity:
            vals["verified_at"] = None  # dati cambiati: nuova verifica necessaria
        sets = ", ".join(f"{k}=?" for k in vals)
        conn.execute(f"UPDATE guests SET {sets}, version=version+1, updated_at=? WHERE id=?",
                     (*vals.values(), ts, guest_id))
        audit(conn, "ospite_modificato", "guest", guest_id)
        gid = guest_id
    else:
        if vals.get("position") in (None, ""):
            vals["position"] = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM guests WHERE booking_id=?",
                                            (booking_id,)).fetchone()[0]
        vals["doc_enc"] = None  # cifrato dopo l'inserimento, legato all'id del nuovo ospite
        cols = ", ".join(vals)
        c = conn.execute(f"INSERT INTO guests(booking_id, {cols}, created_at, updated_at) "
                         f"VALUES (?, {','.join('?' * len(vals))}, ?, ?)", (booking_id, *vals.values(), ts, ts))
        gid = c.lastrowid
        if doc is not None and any(doc.values()):
            conn.execute("UPDATE guests SET doc_enc=? WHERE id=?",
                         (encrypt_json(STATE.require_dek(), doc, _doc_ctx(gid)), gid))
        audit(conn, "ospite_creato", "guest", gid)
    if "verified" in data and data["verified"]:
        verify(conn, gid)
    return get(conn, gid)


def get(conn, guest_id: int) -> dict:
    g = row(conn.execute("SELECT * FROM guests WHERE id=?", (guest_id,)))
    if not g:
        raise AppError("Ospite inesistente.", 404)
    return g


def check(g: dict, doc: dict | None, purpose: str) -> list[dict]:
    """Controlli bloccanti per destinazione: 'verifica' | 'alloggiati' | 'ross'. Errori per campo."""
    errs: list[dict] = []
    who = f"{g.get('surname') or '?'} {g.get('name') or '?'}"

    def e(field, msg):
        errs.append({"guest_id": g.get("id"), "guest": who, "field": field, "message": msg})

    if purpose in ("verifica", "alloggiati"):
        if len(g.get("surname") or "") > 50:
            e("surname", "Cognome oltre 50 caratteri: il tracciato non lo consente; verificare la grafia sul "
                         "documento (nessun troncamento automatico).")
        if len(g.get("name") or "") > 30:
            e("name", "Nome oltre 30 caratteri: verificare la grafia sul documento (nessun troncamento automatico).")
        for k in ("surname", "name"):
            if g.get(k) and not _NAME_RE.match(g[k]):
                e(k, "Contiene caratteri non ammessi (numeri o simboli).")
    if not g.get("sex"):
        e("sex", "Sesso mancante (richiesto dal tracciato: M o F).")
    if not g.get("birth_date"):
        e("birth_date", "Data di nascita mancante.")
    else:
        bd = d(g["birth_date"])
        if bd > date.today():
            e("birth_date", "Data di nascita nel futuro.")
        elif age_on(bd, date.today()) > 120:
            e("birth_date", "Data di nascita non plausibile (oltre 120 anni).")
    if not g.get("birth_state_code"):
        e("birth_state_code", "Stato di nascita mancante.")
    else:
        ok, msg = tables.valid_on("stati", g["birth_state_code"], g.get("birth_date"))
        if not ok:
            e("birth_state_code", f"Stato di nascita: {msg}.")
        if g["birth_state_code"] == tables.ITALIA:
            if not g.get("birth_comune_code"):
                e("birth_comune_code", "Nato in Italia: comune di nascita obbligatorio.")
            else:
                ok, msg = tables.valid_on("comuni", g["birth_comune_code"], g.get("birth_date"))
                if not ok:
                    e("birth_comune_code", f"Comune di nascita: {msg}.")
    if not g.get("citizenship_code"):
        e("citizenship_code", "Cittadinanza mancante.")
    elif not tables.get("stati", g["citizenship_code"]):
        e("citizenship_code", "Cittadinanza: codice non presente nella tabella ufficiale Stati.")
    if purpose in ("verifica", "alloggiati") and g.get("guest_type") in ("16", "17", "18"):
        doc = doc or {}
        if g.get("doc_purged_at"):
            e("doc", "Dati del documento già eliminati dopo la ricevuta: per una nuova comunicazione "
                     "occorre riacquisirli dal documento.")
        else:
            if not doc.get("type"):
                e("doc.type", "Tipo di documento mancante.")
            elif not tables.get("documenti", doc["type"]):
                e("doc.type", "Tipo di documento non presente nella tabella ufficiale.")
            if not doc.get("number"):
                e("doc.number", "Numero del documento mancante.")
            elif len(doc["number"]) > 20:
                e("doc.number", "Numero documento oltre 20 caratteri.")
            if not doc.get("issue_place"):
                e("doc.issue_place", "Luogo di rilascio mancante (comune italiano o Stato estero).")
            elif not (tables.get("comuni", doc["issue_place"]) or tables.get("stati", doc["issue_place"])):
                e("doc.issue_place", "Luogo di rilascio: codice non presente nelle tabelle Comuni/Stati.")
    if purpose == "ross":
        if not g.get("res_state_code"):
            e("res_state_code", "Stato di residenza mancante (richiesto da ROSS 1000).")
        elif g["res_state_code"] == tables.ITALIA and not g.get("res_comune_code"):
            e("res_comune_code", "Residente in Italia: comune di residenza obbligatorio per ROSS 1000.")
        if g.get("res_place_text") and len(g["res_place_text"]) > 30:
            e("res_place_text", "Località di residenza estera oltre 30 caratteri.")
    return errs


def verify(conn, guest_id: int) -> dict:
    g = get(conn, guest_id)
    errs = check(g, doc_of(g), "verifica")
    if errs:
        raise AppError("Verifica non possibile: correggere i campi indicati.", extra={"errors": errs})
    conn.execute("UPDATE guests SET verified_at=?, version=version+1 WHERE id=?", (now_iso(), guest_id))
    audit(conn, "ospite_verificato", "guest", guest_id)
    return get(conn, guest_id)


def duplicates(conn, g: dict) -> list[dict]:
    """Possibili duplicati: stessa persona (cognome, nome, nascita) in altre schede. Mai unione automatica."""
    if not g.get("birth_date"):
        return []
    return rows(conn.execute(
        "SELECT g.id, g.booking_id, b.ref FROM guests g JOIN bookings b ON b.id=g.booking_id "
        "WHERE g.id != ? AND UPPER(g.surname)=UPPER(?) AND UPPER(g.name)=UPPER(?) AND g.birth_date=? "
        "AND g.anonymized_at IS NULL", (g["id"], g["surname"], g["name"], g["birth_date"])))


def set_stay(conn, guest_id: int, data: dict) -> dict:
    """Modifica la permanenza EFFETTIVA di un solo ospite (non tocca gli altri)."""
    g = get(conn, guest_id)
    b = row(conn.execute("SELECT * FROM bookings WHERE id=?", (g["booking_id"],)))
    if g["presence"] not in ("presente", "partita"):
        raise AppError("La permanenza effettiva si modifica solo per ospiti arrivati.")
    arr = d(data.get("stay_arrival") or g["stay_arrival"], "arrivo effettivo").isoformat()
    dep = data.get("stay_departure") or g["stay_departure"]
    dep = d(dep).isoformat() if dep else None
    if dep and dep <= arr:
        raise AppError("La partenza deve seguire l'arrivo.")
    if arr < b["arrival"] or (dep and dep > b["departure"]):
        raise AppError("La permanenza esce dal periodo della prenotazione: estendere prima la prenotazione "
                       "(proroga) con il controllo disponibilità.")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise AppError("Indicare il motivo della modifica della permanenza.")
    conn.execute("UPDATE guests SET stay_arrival=?, stay_departure=?, presence=?, version=version+1, updated_at=? "
                 "WHERE id=?", (arr, dep, "partita" if dep and g["presence"] == "partita" else g["presence"],
                                now_iso(), guest_id))
    audit(conn, "permanenza_modificata", "guest", guest_id, reason[:200])
    return get(conn, guest_id)


def delete(conn, guest_id: int, reason: str) -> None:
    g = get(conn, guest_id)
    if g["alloggiati_status"] in ("caricamento_dichiarato", "esito_registrato"):
        raise AppError("Ospite già comunicato ad Alloggiati Web: non si elimina. Aprire una rettifica secondo "
                       "le procedure del portale.")
    if not (reason or "").strip():
        raise AppError("Indicare il motivo dell'eliminazione.")
    if conn.execute("SELECT 1 FROM guests WHERE leader_guest_id=?", (guest_id,)).fetchone():
        raise AppError("Ospite capofamiglia/capogruppo di altri: modificare prima i componenti.")
    from . import exports
    exports.on_guest_deleted(conn, g)
    conn.execute("DELETE FROM guests WHERE id=?", (guest_id,))
    audit(conn, "ospite_eliminato", "guest", guest_id, reason[:200])


def purge_document(conn, guest_id: int, why: str) -> bool:
    """Elimina i dati documentali conservati solo per la trasmissione. True se c'era qualcosa da eliminare."""
    from .retention import ledger_add
    c = conn.execute("UPDATE guests SET doc_enc=NULL, doc_purged_at=?, version=version+1 WHERE id=? "
                     "AND doc_enc IS NOT NULL", (now_iso(), guest_id))
    if c.rowcount:
        audit(conn, "documento_eliminato", "guest", guest_id, why)
        ledger_add("doc", guest_id)
    return bool(c.rowcount)
