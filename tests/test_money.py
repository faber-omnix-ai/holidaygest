import pytest

from app.db import AppError
from app.services import bookings, money
from conftest import checkin_all, mk_booking, mk_guest, uid


def _paid_stay(conn):
    b = mk_booking(conn, "2026-06-01", "2026-06-04", base_cents=50000, deposit_cents=10000)
    mk_guest(conn, b["id"])
    mk_guest(conn, b["id"], surname="BIANCHI")
    checkin_all(conn, b["id"], "2026-06-01")
    return b


def test_split_payment_612(conn):
    # H: 612 = 500 soggiorno + 12 imposta + 100 cauzione
    b = _paid_stay(conn)
    money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "612,00",
                        "op_date": "2026-06-01", "method": "bonifico", "causale": "Saldo e imposta",
                        "allocations": [{"category": "soggiorno", "amount": "500"},
                                        {"category": "imposta", "amount": "12"},
                                        {"category": "cauzione", "amount": "100"}]})
    bal = money.balances(conn, b["id"])
    assert bal["stay"]["balance_cents"] == 0
    assert bal["tax"]["due_cents"] == 1200 and bal["tax"]["residual_cents"] == 0
    assert bal["deposit"]["held_cents"] == 10000


def test_split_must_match_total(conn):
    b = _paid_stay(conn)
    with pytest.raises(AppError):
        money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "612",
                            "op_date": "2026-06-01", "method": "contanti", "causale": "x",
                            "allocations": [{"category": "soggiorno", "amount": "500"}]})


def test_repeated_command_is_idempotent(conn):
    # G: stesso comando ripetuto -> nessun duplicato
    b = _paid_stay(conn)
    op = {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "200", "op_date": "2026-05-01",
          "method": "bonifico", "causale": "Acconto", "allocations": [{"category": "soggiorno", "amount": "200"}]}
    m1 = money.record(conn, dict(op))
    m2 = money.record(conn, dict(op))
    assert m1["id"] == m2["id"] and m2.get("duplicate_request")
    assert conn.execute("SELECT COUNT(*) FROM movements").fetchone()[0] == 1


def test_cancel_keeps_payment_refund_distinct(conn):
    # I: annullo con acconto: l'incasso resta, il rimborso è un movimento distinto
    b = mk_booking(conn, "2027-01-10", "2027-01-15", base_cents=60000)
    money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "150",
                        "op_date": "2026-10-01", "method": "bonifico", "causale": "Acconto",
                        "allocations": [{"category": "soggiorno", "amount": "150"}]})
    b = bookings.get(conn, b["id"])
    bookings.change_status(conn, b["id"], "annulla", {"version": b["version"], "reason": "Richiesta ospite",
                                                      "retained_cents": "50"})
    money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "uscita", "amount": "100",
                        "op_date": "2026-10-05", "method": "bonifico", "causale": "Rimborso acconto",
                        "allocations": [{"category": "soggiorno", "amount": "100"}]})
    bal = money.balances(conn, b["id"])
    assert bal["stay"]["received_cents"] == 15000 and bal["stay"]["refunded_cents"] == 10000
    assert bal["stay"]["balance_cents"] == 0
    assert conn.execute("SELECT COUNT(*) FROM movements WHERE booking_id=?", (b["id"],)).fetchone()[0] == 2


def test_reversal_is_tracked_not_deleted(conn):
    b = _paid_stay(conn)
    m = money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "100",
                            "op_date": "2026-06-01", "method": "contanti", "causale": "errore",
                            "allocations": [{"category": "soggiorno", "amount": "100"}]})
    money.reverse(conn, m["id"], "Importo registrato per errore", uid())
    assert money.balances(conn, b["id"])["stay"]["net_cents"] == 0
    assert conn.execute("SELECT COUNT(*) FROM movements").fetchone()[0] == 2
    with pytest.raises(AppError):
        money.reverse(conn, m["id"], "di nuovo", uid())


def test_refusal_does_not_cancel_tax_due(conn):
    b = _paid_stay(conn)
    conn.execute("UPDATE bookings SET tax_refusal_note='Ospite rifiuta il pagamento' WHERE id=?", (b["id"],))
    bal = money.balances(conn, b["id"])
    assert bal["tax"]["due_cents"] == 1200 and bal["tax"]["residual_cents"] == 1200


def test_third_party_tax_needs_reference(conn):
    b = _paid_stay(conn)
    with pytest.raises(AppError):
        money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "terzi", "amount": "12",
                            "op_date": "2026-06-01", "causale": "Imposta incassata da intermediario",
                            "allocations": [{"category": "imposta", "amount": "12"}]})


def test_receipts_numbering_never_reused(conn):
    b = _paid_stay(conn)
    money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "12",
                        "op_date": "2026-06-03", "method": "contanti", "causale": "Imposta",
                        "allocations": [{"category": "imposta", "amount": "12"}]})
    r1 = money.issue_receipt(conn, b["id"], "2026-06-03")
    assert r1["amount_cents"] == 1200 and r1["number"] == 1
    with pytest.raises(AppError):
        money.issue_receipt(conn, b["id"])  # niente da quietanzare
    money.cancel_receipt(conn, r1["id"], "Dati errati")
    r2 = money.issue_receipt(conn, b["id"], "2026-06-03")
    assert r2["number"] == 2


def test_price_per_night_with_extras(conn):
    b = mk_booking(conn, "2027-08-01", "2027-08-05", pricing_mode="per_notte", nightly_cents="90,00", base_cents=0)
    bookings.set_price_items(conn, b["id"], [{"kind": "extra", "description": "Pulizia finale", "amount": "40"},
                                              {"kind": "sconto", "description": "Fedeltà", "amount": "20"}])
    p = money.price_total(conn, bookings.get(conn, b["id"]))
    assert p["total_cents"] == 36000 + 4000 - 2000
