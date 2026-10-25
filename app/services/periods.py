"""Controllo e chiusura dei periodi (mese, trimestre, anno), riconciliazione e prospetti.

Criteri di attribuzione (dichiarati in ogni prospetto):
- pernottamenti, imposta calcolata e ricavi maturati: per DATA DELLA NOTTE;
- incassi, rimborsi e versamenti: per DATA DELL'OPERAZIONE;
- versamenti: per trimestre di riferimento indicato nel movimento.
Il criterio di attribuzione per la comunicazione comunale va confermato nelle istruzioni
StayTour/SECAL (vedi docs/FONTI_NORMATIVE.md).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from ..db import AppError, audit, now_iso, row, rows
from ..util import eur, it, nights, period_bounds
from . import money, tax

ATTRIBUTION = {"notti": "per data della notte (arrivo incluso, partenza esclusa)",
               "incassi": "per data dell'operazione", "versamenti": "per trimestre indicato nel versamento"}


def _tax_lines(conn, b: dict) -> tuple[list[dict], str, bool]:
    """Righe per notte dal conteggio consolidato se esiste, altrimenti dal calcolo corrente."""
    cons = tax.consolidated(conn, b["id"])
    calc = json.loads(cons["detail"]) if cons else tax.compute_booking(conn, b["id"])
    lines = [ln | {"guest_id": g["guest_id"], "basis": g["basis"]} for g in calc["guests"] for ln in g["lines"]]
    return lines, ("consolidato" if cons else calc["kind"]), bool(cons)


def _revenue_by_night(conn, b: dict) -> dict[str, int]:
    p = money.price_total(conn, b)
    ns = [n.isoformat() for n in nights(b["arrival"], b["departure"])]
    if not ns:
        return {}
    per, rem = divmod(p["total_cents"], len(ns))
    out = {n: per for n in ns}
    out[ns[-1]] += rem
    return out


def check(conn: sqlite3.Connection, kind: str, period: str) -> dict:
    s, e = period_bounds(kind, period)
    today = now_iso()[:10]
    anomalies: list[dict] = []
    bks = rows(conn.execute("SELECT * FROM bookings WHERE arrival < ? AND departure > ? ORDER BY arrival", (e, s)))
    counts = {"imponibile": 0, "esente": 0, "non_assoggettata": 0, "oltre_limite": 0, "da_chiarire": 0,
              "senza_regola": 0}
    exempt_reasons: dict[str, int] = {}
    tax_amount, tax_unknown, presence_days, persons_arrived = 0, False, 0, 0
    revenue = 0
    for b in bks:
        link = f"#/prenotazione/{b['id']}"
        if b["status"] in ("confermata", "in_corso", "conclusa"):
            for n, c in _revenue_by_night(conn, b).items():
                if s <= n < e:
                    revenue += c
        if b["status"] not in ("in_corso", "conclusa"):
            if b["status"] == "confermata" and b["arrival"] < today:
                anomalies.append({"text": f"{b['ref']}: arrivo previsto il {it(b['arrival'])} ma nessun check-in "
                                          f"registrato (non viene chiuso automaticamente)", "link": link})
            continue
        if b["status"] == "in_corso" and b["departure"] < today:
            anomalies.append({"text": f"{b['ref']}: partenza prevista superata, check-out non registrato",
                              "link": link})
        lines, source, _ = _tax_lines(conn, b)
        for ln in lines:
            if not (s <= ln["night"] < e) or ln["basis"] != "effettiva":
                continue
            presence_days += 1
            counts[ln["cls"]] = counts.get(ln["cls"], 0) + 1
            if ln["cls"] in ("esente", "non_assoggettata"):
                exempt_reasons[ln["reason"]] = exempt_reasons.get(ln["reason"], 0) + 1
            if ln["amount_cents"] is None:
                tax_unknown = True
            else:
                tax_amount += ln["amount_cents"]
        if any(ln["amount_cents"] is None and s <= ln["night"] < e for ln in lines):
            anomalies.append({"text": f"{b['ref']}: imposta DA VERIFICARE per notti del periodo", "link": link})
        if any(ln["basis"] == "prevista" and s <= ln["night"] < e and ln["night"] < today for ln in lines):
            anomalies.append({"text": f"{b['ref']}: ospiti senza permanenza effettiva registrata", "link": link})
        for g in rows(conn.execute("SELECT * FROM guests WHERE booking_id=? AND anonymized_at IS NULL", (b["id"],))):
            if g["stay_arrival"] and s <= g["stay_arrival"] < e:
                persons_arrived += 1
                if g["alloggiati_status"] not in ("caricamento_dichiarato", "esito_registrato"):
                    anomalies.append({"text": f"{b['ref']} · {g['surname']} {g['name']}: comunicazione Alloggiati "
                                              f"non registrata ({g['alloggiati_status'].replace('_', ' ')})",
                                      "link": "#/esportazioni"})
            if not g["verified_at"] and g["presence"] in ("presente", "partita"):
                anomalies.append({"text": f"{b['ref']} · {g['surname']} {g['name']}: dati non verificati",
                                  "link": f"{link}?ospite={g['id']}"})
        bal = money.balances(conn, b["id"])
        if b["status"] == "conclusa" and (bal["tax"]["residual_cents"] or 0) > 0:
            anomalies.append({"text": f"{b['ref']}: imposta non riscossa {eur(bal['tax']['residual_cents'])}"
                                      + (" (rifiuto annotato: resta dovuta dal gestore)" if b["tax_refusal_note"]
                                         else ""), "link": link})
        if b["status"] == "conclusa" and bal["stay"]["balance_cents"] > 0:
            anomalies.append({"text": f"{b['ref']}: saldo soggiorno aperto {eur(bal['stay']['balance_cents'])}",
                              "link": link})
    mov = {(r["direction"], r["category"]): r["amt"] for r in rows(conn.execute(
        "SELECT m.direction, a.category, SUM(CASE WHEN m.reverses_id IS NULL THEN a.amount_cents ELSE "
        "-a.amount_cents END) amt FROM movements m JOIN allocations a ON a.movement_id=m.id "
        "WHERE m.op_date >= ? AND m.op_date < ? GROUP BY m.direction, a.category", (s, e)))}
    g = lambda dr, c: mov.get((dr, c), 0) or 0  # noqa: E731
    y0, y1 = int(s[:4]), int(e[:4])
    rem = rows(conn.execute("SELECT * FROM remittances WHERE (year*10+quarter) >= ? AND (year*10+quarter) < ?",
                            (y0 * 10 + (int(s[5:7]) - 1) // 3 + 1, y1 * 10 + (int(e[5:7]) - 1) // 3 + 1)))
    remitted = sum(r["amount_cents"] for r in rem)
    for c in rows(conn.execute("SELECT * FROM corrections WHERE status='aperta'")):
        anomalies.append({"text": f"Rettifica aperta ({c['target']}): {c['reason']}",
                          "link": f"#/prenotazione/{c['booking_id']}" if c["booking_id"] else "#/esportazioni"})
    for b in rows(conn.execute("SELECT id, kind, period_from, period_to FROM export_batches WHERE status='generato' "
                               "AND period_from < ? AND period_to >= ?", (e, s))):
        anomalies.append({"text": f"Lotto {b['kind']} n. {b['id']} generato ma caricamento non dichiarato",
                          "link": "#/esportazioni"})
    ross_days = {r["ross_day"] for r in rows(conn.execute(
        "SELECT i.ross_day FROM export_items i JOIN export_batches b ON b.id=i.batch_id WHERE b.kind='ross' "
        "AND b.status IN ('caricamento_dichiarato','esito_registrato') AND i.ross_day >= ? AND i.ross_day < ?",
        (s, e)))}
    missing_ross = [n.isoformat() for n in nights(s, min(e, today)) if n.isoformat() not in ross_days]
    if missing_ross:
        anomalies.append({"text": f"ROSS 1000: {len(missing_ross)} giornate trascorse senza movimento dichiarato "
                                  f"(dal {it(missing_ross[0])})", "link": "#/esportazioni"})
    return {
        "kind": kind, "period": period, "from": s, "to": e, "attribution": ATTRIBUTION,
        "stays": len([b for b in bks if b["status"] in ("in_corso", "conclusa")]),
        "persons_arrived": persons_arrived, "presence_nights": presence_days,
        "tax_nights": counts, "exempt_reasons": exempt_reasons,
        "tax_computed_cents": None if tax_unknown else tax_amount,
        "tax_collected_cents": g("entrata", "imposta"), "tax_refunded_cents": g("uscita", "imposta"),
        "tax_third_party_cents": g("terzi", "imposta"), "tax_remitted_cents": remitted,
        "revenue_accrued_cents": revenue, "stay_received_cents": g("entrata", "soggiorno"),
        "stay_refunded_cents": g("uscita", "soggiorno"), "deposit_received_cents": g("entrata", "cauzione"),
        "deposit_returned_cents": g("uscita", "cauzione"),
        "explanations": [
            "Alloggiati conta le PERSONE arrivate nel periodo; ROSS conta arrivi, partenze e presenze GIORNALIERE; "
            "l'imposta conta i PERNOTTAMENTI imponibili (esenzioni e limite di 7 notti esclusi): i totali non "
            "coincidono per costruzione.",
            "Ricavi maturati (corrispettivo ripartito sulle notti del periodo) e incassi ricevuti (per data "
            "dell'operazione) sono grandezze distinte: un acconto per un soggiorno futuro è un incasso, non un ricavo "
            "del periodo.",
            "Imposta e cauzione non sono ricavi dell'appartamento."],
        "anomalies": anomalies,
    }


def _figures(snap: dict) -> dict:
    keys = ("presence_nights", "tax_nights", "tax_computed_cents", "tax_collected_cents", "tax_refunded_cents",
            "tax_third_party_cents", "tax_remitted_cents", "revenue_accrued_cents", "stay_received_cents",
            "persons_arrived")
    return {k: snap[k] for k in keys}


def close(conn: sqlite3.Connection, kind: str, period: str, confirm_anomalies: bool, reason: str | None) -> dict:
    snap = check(conn, kind, period)
    if snap["anomalies"] and not confirm_anomalies:
        raise AppError(f"Ci sono {len(snap['anomalies'])} anomalie: correggerle o confermare la chiusura con "
                       f"anomalie note.", extra=snap)
    prev = row(conn.execute("SELECT * FROM period_closures WHERE kind=? AND period=? AND status='chiuso'",
                            (kind, period)))
    if prev and not (reason or "").strip():
        raise AppError("Periodo già chiuso: la nuova chiusura è una rettifica e richiede la motivazione.")
    body = json.dumps(snap, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(json.dumps(_figures(snap), sort_keys=True).encode()).hexdigest()
    if prev:
        conn.execute("UPDATE period_closures SET status='superato' WHERE id=?", (prev["id"],))
    cur = conn.execute("INSERT INTO period_closures(kind,period,snapshot,snapshot_hash,status,supersedes_id,reason,"
                       "created_at) VALUES (?,?,?,?,'chiuso',?,?,?)",
                       (kind, period, body, h, prev["id"] if prev else None, (reason or "").strip() or None, now_iso()))
    if prev:
        conn.execute("UPDATE corrections SET status='gestita', resolution=?, resolved_at=? WHERE target='periodo' "
                     "AND entity_id=? AND status='aperta'", (f"Rettifica: chiusura n. {cur.lastrowid}", now_iso(),
                                                              prev["id"]))
    audit(conn, "periodo_chiuso", "period_closure", cur.lastrowid, f"{kind} {period}")
    return row(conn.execute("SELECT id, kind, period, snapshot_hash, status, created_at FROM period_closures "
                            "WHERE id=?", (cur.lastrowid,)))


def reassess_closures(conn: sqlite3.Connection) -> int:
    from .exports import open_correction
    n = 0
    for pc in rows(conn.execute("SELECT * FROM period_closures WHERE status='chiuso'")):
        snap = check(conn, pc["kind"], pc["period"])
        h = hashlib.sha256(json.dumps(_figures(snap), sort_keys=True).encode()).hexdigest()
        if h != pc["snapshot_hash"]:
            n += open_correction(conn, "periodo", "period_closure", pc["id"], None,
                                 f"Il periodo {pc['period']} (chiusura n. {pc['id']}) è cambiato dopo la chiusura: "
                                 f"verificare e registrare una chiusura di rettifica.")
    return n


def staytour_sheet(conn: sqlite3.Connection, year: int, quarter: int) -> dict:
    """Prospetto per la compilazione MANUALE della comunicazione trimestrale (non importabile)."""
    period = f"{year}-T{quarter}"
    c = check(conn, "trimestre", period)
    return {
        "titolo": f"Prospetto imposta di soggiorno — {quarter}° trimestre {year}",
        "avvertenza": "Prospetto di supporto per la compilazione manuale sul portale comunale. Non è un file "
                      "importabile, non sostituisce la comunicazione e non prova il versamento.",
        "criterio": ATTRIBUTION["notti"],
        "pernottamenti_imponibili": c["tax_nights"].get("imponibile", 0),
        "giorni_permanenza": c["presence_nights"],
        "pernottamenti_esenti_per_motivo": c["exempt_reasons"],
        "pernottamenti_oltre_limite": c["tax_nights"].get("oltre_limite", 0),
        "da_verificare": c["tax_nights"].get("da_chiarire", 0) + c["tax_nights"].get("senza_regola", 0),
        "imposta_calcolata_cents": c["tax_computed_cents"],
        "imposta_riscossa_cents": c["tax_collected_cents"] - c["tax_refunded_cents"],
        "imposta_gestita_terzi_cents": c["tax_third_party_cents"],
        "versato_cents": c["tax_remitted_cents"],
        "anomalie": c["anomalies"],
    }
