"""Coerenza tra moduli: conseguenze delle modifiche, pratiche aperte, rettifiche."""
from __future__ import annotations

import json
import sqlite3

from ..db import rows
from ..util import eur, it


def effects_of_booking(conn: sqlite3.Connection, booking_id: int) -> list[str]:
    """Esportazioni, conteggi e rendiconti interessati dallo stato ATTUALE (anche simulato) della prenotazione."""
    from . import tax
    out = []
    gids = [r["id"] for r in rows(conn.execute("SELECT id FROM guests WHERE booking_id=?", (booking_id,)))]
    if gids:
        q = ",".join("?" * len(gids))
        for b in rows(conn.execute(
                f"SELECT DISTINCT b.id, b.status, b.kind FROM export_batches b JOIN export_items i ON i.batch_id=b.id "
                f"WHERE b.kind='alloggiati' AND i.guest_id IN ({q}) AND b.status != 'superato'", gids)):
            if b["status"] == "generato":
                out.append(f"Il file Alloggiati del lotto {b['id']} (generato, non ancora caricato) potrebbe "
                           f"diventare superato: andrà rigenerato.")
            else:
                out.append(f"Dati già comunicati ad Alloggiati (lotto {b['id']}): una modifica aprirà una "
                           f"segnalazione di rettifica; il portale NON viene aggiornato automaticamente.")
    bk = conn.execute("SELECT arrival, departure FROM bookings WHERE id=?", (booking_id,)).fetchone()
    for b in rows(conn.execute("SELECT id, status FROM export_batches WHERE kind='ross' AND status!='superato' "
                               "AND period_from < ? AND period_to >= ?", (bk["departure"], bk["arrival"]))):
        out.append(f"Il periodo rientra nel lotto ROSS {b['id']} ({b['status'].replace('_', ' ')}): "
                   f"i movimenti modificati andranno ritrasmessi.")
    cons = tax.consolidated(conn, booking_id)
    if cons:
        now = tax.compute_booking(conn, booking_id)
        if now["total_cents"] != cons["total_cents"]:
            out.append(f"Imposta già consolidata {eur(cons['total_cents'])}: il nuovo calcolo "
                       f"({eur(now['total_cents'])}) richiederà una rettifica motivata.")
    for pc in rows(conn.execute("SELECT id, kind, period FROM period_closures WHERE status='chiuso'")):
        from ..util import period_bounds
        s, e = period_bounds(pc["kind"], pc["period"])
        if bk["arrival"] < e and bk["departure"] > s:
            out.append(f"Il periodo {pc['period']} è già chiuso (riepilogo n. {pc['id']}): servirà una rettifica.")
    return out


def open_items_for_booking(conn: sqlite3.Connection, b: dict) -> list[dict]:
    """Adempimenti e dati ancora aperti per una prenotazione, ciascuno con il collegamento alla pratica."""
    from . import money
    items = []
    link = f"#/prenotazione/{b['id']}"
    gs = rows(conn.execute("SELECT * FROM guests WHERE booking_id=? AND anonymized_at IS NULL", (b["id"],)))
    if b["status"] in ("confermata", "in_corso", "conclusa") and not gs:
        items.append({"kind": "ospiti", "text": f"{b['ref']}: nessun ospite inserito", "link": link})
    for g in gs:
        who = f"{g['surname']} {g['name']}"
        if not g["verified_at"]:
            items.append({"kind": "verifica", "text": f"{b['ref']} · {who}: dati da verificare",
                          "link": f"{link}?ospite={g['id']}"})
        if g["presence"] in ("presente", "partita") and g["alloggiati_status"] not in (
                "caricamento_dichiarato", "esito_registrato"):
            items.append({"kind": "alloggiati", "text": f"{b['ref']} · {who}: comunicazione Alloggiati "
                                                        f"({g['alloggiati_status'].replace('_', ' ')})",
                          "link": "#/esportazioni"})
    bal = money.balances(conn, b["id"])
    if bal["stay"]["balance_cents"] > 0 and b["status"] not in ("annullata", "no_show", "opzione_scaduta"):
        items.append({"kind": "incasso", "text": f"{b['ref']}: saldo soggiorno da incassare "
                                                 f"{eur(bal['stay']['balance_cents'])}", "link": link})
    if bal["stay"]["balance_cents"] < 0:
        items.append({"kind": "incasso", "text": f"{b['ref']}: incassato più del corrispettivo "
                                                 f"({eur(-bal['stay']['balance_cents'])})", "link": link})
    t = bal["tax"]
    if t["due_cents"] is None and b["status"] in ("confermata", "in_corso", "conclusa"):
        items.append({"kind": "imposta", "text": f"{b['ref']}: imposta DA VERIFICARE", "link": link})
    elif t["residual_cents"] and t["residual_cents"] > 0:
        items.append({"kind": "imposta", "text": f"{b['ref']}: imposta da incassare {eur(t['residual_cents'])}",
                      "link": link})
    if bal["deposit"]["held_cents"] > 0 and b["status"] in ("conclusa", "annullata", "no_show"):
        items.append({"kind": "cauzione", "text": f"{b['ref']}: cauzione ancora trattenuta "
                                                  f"{eur(bal['deposit']['held_cents'])}", "link": link})
    for c in rows(conn.execute("SELECT * FROM corrections WHERE booking_id=? AND status='aperta'", (b["id"],))):
        items.append({"kind": "rettifica", "text": f"{b['ref']}: rettifica {c['target']} da gestire",
                      "link": link})
    return items


def reassess_all(conn: sqlite3.Connection, booking_id: int | None = None) -> dict:
    """Da chiamare dopo ogni modifica: lotti superati, rettifiche, conteggi consolidati divergenti."""
    from . import exports, tax, periods
    res = exports.reassess(conn)
    ids = [booking_id] if booking_id else [r["booking_id"] for r in rows(conn.execute(
        "SELECT DISTINCT booking_id FROM tax_assessments WHERE status='consolidato'"))]
    for bid in ids:
        cons = tax.consolidated(conn, bid)
        if not cons:
            continue
        calc = tax.compute_booking(conn, bid)
        if json.dumps(calc, ensure_ascii=False) != cons["detail"]:
            res["corrections"] += exports.open_correction(
                conn, "imposta", "booking", bid, bid,
                f"Il conteggio consolidato ({eur(cons['total_cents'])}) non corrisponde più ai dati attuali "
                f"({eur(calc['total_cents'])}): consolidare una rettifica motivata.")
    res["corrections"] += periods.reassess_closures(conn)
    return res


# ---------- anteprima generica: simulazione in un savepoint annullato ----------
_PRESENCE = {"prevista": "prevista", "presente": "presente", "partita": "partita", "non_arrivata": "non arrivata"}
_BATCH = {"generato": "generato", "caricamento_dichiarato": "caricamento dichiarato",
          "esito_registrato": "esito registrato", "da_correggere": "da correggere", "superato": "superato"}


def _snapshot(conn: sqlite3.Connection, booking_id: int) -> dict:
    from . import money, tax
    calc = tax.compute_booking(conn, booking_id)
    bal = money.balances(conn, booking_id)
    gs = rows(conn.execute("SELECT id, surname, name, presence, verified_at, alloggiati_status, stay_arrival, "
                           "stay_departure, planned_arrival, planned_departure, tax_status FROM guests "
                           "WHERE booking_id=?", (booking_id,)))
    return {
        "tax_total": calc["total_cents"], "tax_kind": calc["kind"],
        "tax_guests": {g["guest_id"]: (g["label"], g["amount_cents"], json.dumps(g["counts"], sort_keys=True))
                       for g in calc["guests"]},
        "stay_balance": bal["stay"]["balance_cents"], "tax_residual": bal["tax"]["residual_cents"],
        "guests": {g["id"]: g for g in gs},
        "batches": {b["id"]: b for b in rows(conn.execute("SELECT id, kind, status FROM export_batches"))},
        "corrections": {c["id"]: c for c in rows(conn.execute(
            "SELECT id, target, reason FROM corrections WHERE status='aperta'"))},
        "closures": {c["id"]: c for c in rows(conn.execute("SELECT id, period, status FROM period_closures"))},
        "ross_deletions": conn.execute("SELECT COUNT(*) FROM ross_pending_deletions WHERE sent_batch IS NULL"
                                       ).fetchone()[0],
    }


def _counts_text(js: str) -> str:
    from .tax import CLASS_LABEL
    c = json.loads(js)
    return ", ".join(f"{v} {CLASS_LABEL.get(k, k)}" for k, v in c.items()) or "nessuna notte"


def _diff(a: dict, b: dict) -> list[str]:
    out: list[str] = []
    for gid, ga in a["guests"].items():
        gb = b["guests"].get(gid)
        who = f"{ga['surname']} {ga['name']}"
        if gb is None:
            out.append(f"{who}: la scheda verrà eliminata.")
            continue
        if ga["presence"] != gb["presence"]:
            out.append(f"{who}: presenza {_PRESENCE[ga['presence']]} → {_PRESENCE[gb['presence']]}.")
        for k, lbl in (("stay_arrival", "arrivo effettivo"), ("stay_departure", "partenza effettiva"),
                       ("planned_arrival", "arrivo previsto"), ("planned_departure", "partenza prevista")):
            if ga[k] != gb[k]:
                out.append(f"{who}: {lbl} {it(ga[k]) or '—'} → {it(gb[k]) or '—'}.")
        if ga["verified_at"] and not gb["verified_at"]:
            out.append(f"{who}: dati modificati, la verifica andrà ripetuta prima delle comunicazioni.")
        if ga["alloggiati_status"] != gb["alloggiati_status"]:
            out.append(f"{who}: stato Alloggiati {ga['alloggiati_status'].replace('_', ' ')} → "
                       f"{gb['alloggiati_status'].replace('_', ' ')}.")
    for gid, ta in a["tax_guests"].items():
        tb = b["tax_guests"].get(gid)
        if tb and (ta[1] != tb[1] or ta[2] != tb[2]):
            out.append(f"Imposta di {ta[0]}: {eur(ta[1]) if ta[1] is not None else 'DA VERIFICARE'} "
                       f"({_counts_text(ta[2])}) → {eur(tb[1]) if tb[1] is not None else 'DA VERIFICARE'} "
                       f"({_counts_text(tb[2])}).")
    if a["tax_total"] != b["tax_total"]:
        fa = eur(a["tax_total"]) if a["tax_total"] is not None else "DA VERIFICARE"
        fb = eur(b["tax_total"]) if b["tax_total"] is not None else "DA VERIFICARE"
        out.append(f"Imposta totale della prenotazione: {fa} → {fb}.")
    if a["tax_residual"] != b["tax_residual"] and b["tax_residual"] is not None:
        out.append(f"Imposta ancora da incassare: {eur(b['tax_residual'])}"
                   + (" (già incassato più del dovuto: valutare un rimborso)" if b["tax_residual"] < 0 else "") + ".")
    if a["stay_balance"] != b["stay_balance"]:
        out.append(f"Saldo soggiorno: {eur(a['stay_balance'])} → {eur(b['stay_balance'])}.")
    for bid, ba in a["batches"].items():
        bb = b["batches"].get(bid)
        if bb and ba["status"] != bb["status"]:
            kind = "Alloggiati" if ba["kind"] == "alloggiati" else "ROSS 1000"
            msg = f"Lotto {kind} n. {bid}: {_BATCH.get(ba['status'], ba['status'])} → " \
                  f"{_BATCH.get(bb['status'], bb['status'])}"
            if bb["status"] == "superato":
                msg += " (il file andrà rigenerato; quello vecchio non va caricato)"
            out.append(msg + ".")
    for cid, c in b["corrections"].items():
        if cid not in a["corrections"]:
            out.append(f"Si aprirà una rettifica ({c['target']}): {c['reason']}")
    for pid, pa in a["closures"].items():
        pb = b["closures"].get(pid)
        if pb and pa["status"] != pb["status"]:
            out.append(f"Chiusura del periodo {pa['period']}: {pa['status']} → {pb['status']}.")
    if b["ross_deletions"] > a["ross_deletions"]:
        out.append("Il prossimo file ROSS 1000 conterrà l'eliminazione di movimenti già dichiarati.")
    return out


def simulate(conn: sqlite3.Connection, booking_id: int, action) -> dict:
    """Esegue `action(conn)` e la rivalutazione completa, raccoglie le conseguenze e ANNULLA tutto.

    Usa lo stesso codice del salvataggio reale: l'anteprima non può divergere da ciò che accadrà.
    """
    before = _snapshot(conn, booking_id)
    conn.execute("SAVEPOINT anteprima_generica")
    try:
        action(conn)
        reassess_all(conn)
        after = _snapshot(conn, booking_id) if conn.execute(
            "SELECT 1 FROM bookings WHERE id=?", (booking_id,)).fetchone() else before
    finally:
        conn.execute("ROLLBACK TO anteprima_generica")
        conn.execute("RELEASE anteprima_generica")
    lines = _diff(before, after)
    serious = (any(after["batches"].get(k, v)["status"] != v["status"] for k, v in before["batches"].items())
               or set(after["corrections"]) - set(before["corrections"])
               or any(after["closures"].get(k, v)["status"] != v["status"] for k, v in before["closures"].items())
               or after["ross_deletions"] > before["ross_deletions"])
    return {"summary": lines or ["Nessuna conseguenza oltre ai dati modificati."], "has_effects": bool(lines),
            "communications_affected": bool(serious)}
