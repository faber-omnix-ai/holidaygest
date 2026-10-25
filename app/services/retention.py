"""Conservazione e cancellazione.

- Dati documentali: eliminati all'acquisizione della ricevuta Alloggiati (Garante, nota 29/04/2026).
- Ricevute Alloggiati: conservate 5 anni (scadenza impostata all'acquisizione), poi eliminate.
- Anagrafiche e prenotazioni: anonimizzate dopo il periodo configurato (predefinito: 5 anni dopo
  la fine dell'anno del soggiorno — VALORE DA CONFERMARE con il proprio consulente).
- Registro eliminazioni (solo identificativi interni, nessun dato personale) fuori dal database:
  dopo un ripristino le eliminazioni vengono riapplicate.
Nessun file esterno all'applicazione viene mai cancellato.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from .. import config
from ..db import audit, get_setting, now_iso, rows

LEDGER = "registro_eliminazioni.json"


def _ledger_path():
    return config.data_dir() / LEDGER


def ledger() -> list[dict]:
    p = _ledger_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []


def _ledger_write(items: list[dict]) -> None:
    tmp = _ledger_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(items), encoding="utf-8")
    tmp.replace(_ledger_path())


def ledger_add(kind: str, ident: int | str) -> None:
    items = ledger()
    items.append({"kind": kind, "id": ident, "at": now_iso()})
    _ledger_write(items)


def ledger_merge(other: list[dict]) -> None:
    """Unisce il registro contenuto in un backup a quello del PC (nessuna eliminazione va persa nel trasferimento)."""
    items = ledger()
    seen = {(x["kind"], str(x["id"])) for x in items}
    for x in other or []:
        if isinstance(x, dict) and x.get("kind") in ("doc", "anon_booking", "attachment") and \
                (x["kind"], str(x.get("id"))) not in seen:
            items.append({"kind": x["kind"], "id": x.get("id"), "at": x.get("at") or now_iso()})
            seen.add((x["kind"], str(x.get("id"))))
    _ledger_write(items)


def policy(conn) -> dict:
    p = get_setting(conn, "retention", {}) or {}
    return {"anagrafica_years": int(p.get("anagrafica_years", 5)), "confirmed": bool(p.get("confirmed", False))}


def anonymize_candidates(conn: sqlite3.Connection) -> list[dict]:
    years = policy(conn)["anagrafica_years"]
    limit = f"{date.today().year - years}-01-01"
    return rows(conn.execute(
        "SELECT id, ref, arrival, departure FROM bookings WHERE departure < ? AND status IN "
        "('conclusa','annullata','no_show','opzione_scaduta','bozza') AND booker_name != 'ANONIMIZZATO'",
        (limit,)))


def anonymize_booking(conn: sqlite3.Connection, booking_id: int) -> None:
    ts = now_iso()
    conn.execute("UPDATE bookings SET booker_name='ANONIMIZZATO', booker_phone=NULL, booker_email=NULL, "
                 "notes=NULL, source_text=NULL, tax_refusal_note=NULL, updated_at=? WHERE id=?", (ts, booking_id))
    conn.execute("UPDATE guests SET surname='ANONIMIZZATO', name='', birth_date=NULL, birth_comune_code=NULL, "
                 "birth_province=NULL, res_comune_code=NULL, res_place_text=NULL, doc_enc=NULL, field_flags='{}', "
                 "anonymized_at=? WHERE booking_id=?", (ts, booking_id))
    for a in rows(conn.execute("SELECT id, detail FROM tax_assessments WHERE booking_id=?", (booking_id,))):
        det = json.loads(a["detail"])
        for g in det.get("guests", []):
            g["label"] = f"Ospite {g['guest_id']}"
        conn.execute("UPDATE tax_assessments SET detail=? WHERE id=?", (json.dumps(det, ensure_ascii=False), a["id"]))
    audit(conn, "anonimizzazione", "booking", booking_id)
    ledger_add("anon_booking", booking_id)


def purge_expired_attachments(conn: sqlite3.Connection) -> int:
    today = date.today().isoformat()
    n = 0
    for a in rows(conn.execute("SELECT * FROM attachments WHERE delete_after IS NOT NULL AND delete_after < ?",
                               (today,))):
        (config.data_dir() / "allegati" / a["stored_name"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM attachments WHERE id=?", (a["id"],))
        audit(conn, "allegato_scaduto_eliminato", "attachment", a["id"])
        ledger_add("attachment", a["stored_name"])
        n += 1
    return n


def stale_documents(conn: sqlite3.Connection) -> list[dict]:
    """Dati documentali ancora presenti dopo la partenza, senza ricevuta: da gestire (mai eliminati in silenzio)."""
    return rows(conn.execute(
        "SELECT g.id, g.booking_id, b.ref, g.alloggiati_status FROM guests g JOIN bookings b ON b.id=g.booking_id "
        "WHERE g.doc_enc IS NOT NULL AND g.presence='partita' AND g.alloggiati_status != 'esito_registrato'"))


def after_restore(conn: sqlite3.Connection) -> dict:
    """Riapplica le eliminazioni registrate e le scadenze: il ripristino non riporta in vita dati eliminati."""
    from . import guests
    n = {"documenti": 0, "anonimizzazioni": 0, "allegati": 0}
    for it in ledger():
        if it["kind"] == "doc":
            c = conn.execute("UPDATE guests SET doc_enc=NULL, doc_purged_at=COALESCE(doc_purged_at, ?) "
                             "WHERE id=? AND doc_enc IS NOT NULL", (it["at"], it["id"]))
            n["documenti"] += c.rowcount
        elif it["kind"] == "anon_booking":
            if conn.execute("SELECT 1 FROM bookings WHERE id=? AND booker_name!='ANONIMIZZATO'",
                            (it["id"],)).fetchone():
                anonymize_booking(conn, it["id"])
                n["anonimizzazioni"] += 1
        elif it["kind"] == "attachment":
            (config.data_dir() / "allegati" / str(it["id"])).unlink(missing_ok=True)
            c = conn.execute("DELETE FROM attachments WHERE stored_name=?", (it["id"],))
            n["allegati"] += c.rowcount
    # documenti di ospiti con esito già registrato e ricevuta acquisita
    for g in rows(conn.execute("SELECT g.id FROM guests g WHERE g.doc_enc IS NOT NULL AND EXISTS (SELECT 1 FROM "
                               "attachments a JOIN export_items i ON i.batch_id=a.ref_id WHERE a.kind="
                               "'ricevuta_alloggiati' AND a.ref_table='export_batches' AND i.guest_id=g.id "
                               "AND i.outcome='accettato')")):
        guests.purge_document(conn, g["id"], "riapplicata dopo ripristino")
        n["documenti"] += 1
    n["allegati"] += purge_expired_attachments(conn)
    audit(conn, "ripristino_conservazione_riapplicata", None, None, json.dumps(n))
    return n
