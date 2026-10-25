"""Movimenti economici con ripartizione (soggiorno / imposta / cauzione).

- Ogni incasso o uscita è un movimento con data, importo, modalità, causale, prenotazione.
- La somma delle ripartizioni deve coincidere con l'importo.
- Idempotenza: ogni richiesta porta un `uid` generato dall'interfaccia; ripetere lo stesso
  comando non crea un secondo movimento.
- Correzioni: storno tracciato (movimento con `reverses_id`), mai cancellazioni.
- Imposta e cauzione non sono ricavi dell'appartamento.
"""
from __future__ import annotations

import json
import sqlite3

from ..db import AppError, audit, now_iso, row, rows
from ..util import d, nights, parse_cents

CATEGORIES = ("soggiorno", "imposta", "cauzione")
DIRECTIONS = ("entrata", "uscita", "terzi")
METHODS = ("contanti", "bonifico", "carta", "pos", "assegno", "altro")


def price_total(conn: sqlite3.Connection, b: dict) -> dict:
    items = rows(conn.execute("SELECT * FROM price_items WHERE booking_id=? ORDER BY id", (b["id"],)))
    n = len(nights(b["arrival"], b["departure"]))
    base = b["nightly_cents"] * n if b["pricing_mode"] == "per_notte" else b["base_cents"]
    extra = sum(i["amount_cents"] for i in items if i["kind"] == "extra")
    disc = sum(i["amount_cents"] for i in items if i["kind"] == "sconto")
    return {"nights": n, "base_cents": base, "extra_cents": extra, "discount_cents": disc,
            "total_cents": base + extra - disc, "items": items, "mode": b["pricing_mode"],
            "nightly_cents": b["nightly_cents"]}


def _validate_allocs(amount: int, allocs: list[dict], direction: str) -> list[tuple[str, int]]:
    out = []
    for a in allocs or []:
        cat = a.get("category")
        if cat not in CATEGORIES:
            raise AppError(f"Ripartizione non valida: {cat}")
        c = parse_cents(a.get("amount_cents", a.get("amount")), f"ripartizione {cat}")
        if c < 0:
            raise AppError("Le ripartizioni devono essere positive.")
        if c:
            out.append((cat, c))
    if not out:
        raise AppError("Indicare almeno una ripartizione (soggiorno, imposta o cauzione).")
    s = sum(c for _, c in out)
    if s != amount:
        from ..util import eur
        raise AppError(f"La somma delle ripartizioni ({eur(s)}) non coincide con l'importo ({eur(amount)}).")
    if direction == "terzi" and any(cat != "imposta" for cat, _ in out):
        raise AppError("Le somme gestite da terzi possono riguardare solo l'imposta di soggiorno.")
    return out


def record(conn: sqlite3.Connection, data: dict) -> dict:
    uid = (data.get("uid") or "").strip()
    if len(uid) < 8:
        raise AppError("Identificativo dell'operazione mancante: ricarica la pagina e riprova.")
    existing = row(conn.execute("SELECT * FROM movements WHERE uid=?", (uid,)))
    if existing:
        existing["duplicate_request"] = True
        return existing  # stesso comando ripetuto: nessun duplicato
    b = conn.execute("SELECT id, status FROM bookings WHERE id=?", (data.get("booking_id"),)).fetchone()
    if not b:
        raise AppError("Prenotazione inesistente", 404)
    direction = data.get("direction")
    if direction not in DIRECTIONS:
        raise AppError("Tipo di movimento non valido.")
    amount = parse_cents(data.get("amount_cents", data.get("amount")))
    if amount <= 0:
        raise AppError("L'importo deve essere maggiore di zero.", field="amount")
    method = data.get("method") or ("altro" if direction == "terzi" else None)
    if method not in METHODS:
        raise AppError("Indicare la modalità di pagamento.", field="method")
    causale = (data.get("causale") or "").strip()
    if not causale:
        raise AppError("Indicare la causale.", field="causale")
    if direction == "terzi" and not (data.get("reference") or "").strip():
        raise AppError("Per l'imposta gestita da terzi indicare il riferimento del documento che lo attesta.",
                       field="reference")
    op_date = d(data.get("op_date"), "data operazione").isoformat()
    allocs = _validate_allocs(amount, data.get("allocations"), direction)
    cur = conn.execute(
        "INSERT INTO movements(uid,booking_id,direction,amount_cents,op_date,method,causale,reference,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (uid, b["id"], direction, amount, op_date, method, causale, (data.get("reference") or "").strip() or None,
         now_iso()))
    mid = cur.lastrowid
    for cat, c in allocs:
        conn.execute("INSERT INTO allocations(movement_id,category,amount_cents) VALUES (?,?,?)", (mid, cat, c))
    audit(conn, "movimento_registrato", "movement", mid, f"{direction} {amount}")
    return row(conn.execute("SELECT * FROM movements WHERE id=?", (mid,)))


def reverse(conn: sqlite3.Connection, movement_id: int, reason: str, uid: str) -> dict:
    """Storno tracciato di un movimento: non lo cancella, lo neutralizza."""
    if not reason or not reason.strip():
        raise AppError("Indicare la motivazione dello storno.")
    if row(conn.execute("SELECT id FROM movements WHERE uid=?", (uid,))):
        return row(conn.execute("SELECT * FROM movements WHERE uid=?", (uid,)))
    m = row(conn.execute("SELECT * FROM movements WHERE id=?", (movement_id,)))
    if not m:
        raise AppError("Movimento inesistente", 404)
    if m["reverses_id"]:
        raise AppError("Non è possibile stornare uno storno; registra un nuovo movimento.")
    if m["reversed_by"]:
        raise AppError("Movimento già stornato.")
    cur = conn.execute(
        "INSERT INTO movements(uid,booking_id,direction,amount_cents,op_date,method,causale,reference,reverses_id,"
        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (uid, m["booking_id"], m["direction"], m["amount_cents"], now_iso()[:10], m["method"],
         f"STORNO: {reason.strip()}",
         m["reference"], m["id"], now_iso()))
    for a in rows(conn.execute("SELECT * FROM allocations WHERE movement_id=?", (m["id"],))):
        conn.execute("INSERT INTO allocations(movement_id,category,amount_cents) VALUES (?,?,?)",
                     (cur.lastrowid, a["category"], a["amount_cents"]))
    conn.execute("UPDATE movements SET reversed_by=? WHERE id=?", (cur.lastrowid, m["id"]))
    audit(conn, "movimento_stornato", "movement", m["id"], f"storno={cur.lastrowid}")
    return row(conn.execute("SELECT * FROM movements WHERE id=?", (cur.lastrowid,)))


def _signed(conn: sqlite3.Connection, where: str, params: tuple) -> list[dict]:
    """Ripartizioni con segno: storni negativi."""
    return rows(conn.execute(
        "SELECT m.id movement_id, m.booking_id, m.direction, m.op_date, a.category, "
        "CASE WHEN m.reverses_id IS NULL THEN a.amount_cents ELSE -a.amount_cents END amount "
        f"FROM movements m JOIN allocations a ON a.movement_id=m.id WHERE {where}", params))


def balances(conn: sqlite3.Connection, booking_id: int) -> dict:
    from . import tax
    b = dict(conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone())
    s = {(dr, c): 0 for dr in DIRECTIONS for c in CATEGORIES}
    for r in _signed(conn, "m.booking_id=?", (booking_id,)):
        s[(r["direction"], r["category"])] += r["amount"]
    price = price_total(conn, b)
    stay_in = s[("entrata", "soggiorno")] - s[("uscita", "soggiorno")]
    due_tax = tax.due_for_booking(conn, booking_id)
    tax_coll = s[("entrata", "imposta")] - s[("uscita", "imposta")]
    tax_third = s[("terzi", "imposta")]
    dep_in, dep_out = s[("entrata", "cauzione")], s[("uscita", "cauzione")]
    tax_due = due_tax["due_cents"]
    return {
        "price": price,
        "stay": {"agreed_cents": price["total_cents"], "received_cents": s[("entrata", "soggiorno")],
                 "refunded_cents": s[("uscita", "soggiorno")], "net_cents": stay_in,
                 "balance_cents": price["total_cents"] - stay_in},
        "tax": {"due_cents": tax_due, "due_source": due_tax["source"], "final": due_tax["calc"]["final"],
                "collected_cents": s[("entrata", "imposta")], "refunded_cents": s[("uscita", "imposta")],
                "third_party_cents": tax_third,
                "residual_cents": None if tax_due is None else tax_due - tax_coll - tax_third,
                "issues": due_tax["calc"]["issues"], "refusal_note": b["tax_refusal_note"]},
        "deposit": {"requested_cents": b["deposit_cents"], "received_cents": dep_in, "returned_cents": dep_out,
                    "held_cents": dep_in - dep_out},
    }


def movements_for(conn: sqlite3.Connection, booking_id: int) -> list[dict]:
    ms = rows(conn.execute("SELECT * FROM movements WHERE booking_id=? ORDER BY op_date, id", (booking_id,)))
    for m in ms:
        m["allocations"] = rows(conn.execute("SELECT category, amount_cents FROM allocations WHERE movement_id=?",
                                             (m["id"],)))
    return ms


# ---------- quietanze imposta ----------
def issue_receipt(conn: sqlite3.Connection, booking_id: int, issued_on: str | None = None) -> dict:
    """Quietanza per l'imposta REALMENTE incassata e non ancora quietanzata."""
    bal = balances(conn, booking_id)
    collected = bal["tax"]["collected_cents"] - bal["tax"]["refunded_cents"]
    already = conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM tax_receipts WHERE booking_id=? "
                           "AND status='emessa'", (booking_id,)).fetchone()[0]
    amount = collected - already
    if amount <= 0:
        raise AppError("Nessun importo di imposta incassato da quietanzare.")
    day = d(issued_on or now_iso()[:10]).isoformat()
    year = int(day[:4])
    num = conn.execute("SELECT COALESCE(MAX(number),0)+1 FROM tax_receipts WHERE year=?", (year,)).fetchone()[0]
    calc = bal["tax"]
    detail = {"due_cents": calc["due_cents"], "due_source": calc["due_source"], "collected_total_cents": collected,
              "previous_receipts_cents": already}
    cur = conn.execute("INSERT INTO tax_receipts(year,number,issued_on,booking_id,amount_cents,detail,created_at) "
                       "VALUES (?,?,?,?,?,?,?)", (year, num, day, booking_id, amount, json.dumps(detail), now_iso()))
    audit(conn, "quietanza_emessa", "tax_receipt", cur.lastrowid, f"{year}/{num}")
    return row(conn.execute("SELECT * FROM tax_receipts WHERE id=?", (cur.lastrowid,)))


def cancel_receipt(conn: sqlite3.Connection, receipt_id: int, reason: str) -> None:
    if not reason or not reason.strip():
        raise AppError("Indicare la motivazione dell'annullamento.")
    r = row(conn.execute("SELECT * FROM tax_receipts WHERE id=?", (receipt_id,)))
    if not r or r["status"] != "emessa":
        raise AppError("Quietanza non annullabile.")
    conn.execute("UPDATE tax_receipts SET status='annullata', cancel_reason=?, cancelled_at=? WHERE id=?",
                 (reason.strip(), now_iso(), receipt_id))
    audit(conn, "quietanza_annullata", "tax_receipt", receipt_id)  # il numero resta assegnato
