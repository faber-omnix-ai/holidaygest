import threading

import pytest

from app import db
from app.db import AppError, ConflictError
from app.services import bookings, guests, tax
from conftest import checkin_all, mk_booking, mk_guest


def test_overlap_rejected_and_same_day_turnover_allowed(conn):
    mk_booking(conn, "2026-11-10", "2026-11-15")
    with pytest.raises(ConflictError):
        mk_booking(conn, "2026-11-14", "2026-11-16")
    b = mk_booking(conn, "2026-11-15", "2026-11-18")  # 10:00 -> 15:00 con 120 min di preparazione
    assert b["status"] == "confermata"


def test_incompatible_turnover_needs_explicit_decision(conn):
    st = db.get_setting(conn, "structure")
    st["cleaning_minutes"] = 600
    db.set_setting(conn, "structure", st)
    mk_booking(conn, "2026-11-10", "2026-11-15")
    with pytest.raises(ConflictError) as ex:
        mk_booking(conn, "2026-11-15", "2026-11-18")
    assert ex.value.extra["needs_turnover_ack"]
    assert mk_booking(conn, "2026-11-15", "2026-11-18", turnover_ack=True)["turnover_ack"] == 1


def test_draft_does_not_occupy_but_confirmation_checks(conn):
    d = mk_booking(conn, "2026-11-01", "2026-11-05", status="bozza")
    mk_booking(conn, "2026-11-03", "2026-11-06")
    with pytest.raises(ConflictError):
        bookings.change_status(conn, d["id"], "conferma", {"version": d["version"]})


def test_blocks_occupy_and_generate_nothing(conn):
    bookings.create_block(conn, {"start": "2026-12-01", "last": "2026-12-03", "kind": "manutenzione",
                                 "reason": "Imbiancatura"})
    with pytest.raises(ConflictError):
        mk_booking(conn, "2026-12-03", "2026-12-05")
    assert mk_booking(conn, "2026-12-04", "2026-12-06")  # ultimo giorno bloccato incluso, il 4 è libero
    assert conn.execute("SELECT COUNT(*) FROM guests").fetchone()[0] == 0


def test_two_windows_only_one_wins(conn, data_dir):
    # B: due finestre (due connessioni) confermano periodi incompatibili in parallelo
    a = mk_booking(conn, "2027-02-01", "2027-02-05", status="bozza")
    b = mk_booking(conn, "2027-02-03", "2027-02-07", status="bozza")
    results = []
    barrier = threading.Barrier(2)

    def worker(bid, ver):
        c = db.connect()
        try:
            barrier.wait()
            with db.tx(c):
                bookings.change_status(c, bid, "conferma", {"version": ver})
            results.append("ok")
        except ConflictError:
            results.append("conflitto")
        finally:
            c.close()

    ts = [threading.Thread(target=worker, args=(x["id"], x["version"])) for x in (a, b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == ["conflitto", "ok"]
    n = conn.execute("SELECT COUNT(*) FROM bookings WHERE status='confermata'").fetchone()[0]
    assert n == 1


def test_stale_version_rejected(conn):
    b = mk_booking(conn, "2027-03-01", "2027-03-04")
    bookings.update(conn, b["id"], {"version": b["version"], "notes": "prima finestra"})
    with pytest.raises(ConflictError):
        bookings.update(conn, b["id"], {"version": b["version"], "notes": "seconda finestra"})


def test_option_expiry_and_confirmed_never_released(conn):
    o = mk_booking(conn, "2027-04-01", "2027-04-03", status="opzione", option_expires_at="2026-01-01T10:00")
    c = mk_booking(conn, "2026-09-01", "2026-09-03")  # confermata nel passato senza check-in
    assert bookings.expire_options(conn) == 1
    assert bookings.get(conn, o["id"])["status"] == "opzione_scaduta"
    assert bookings.get(conn, c["id"])["status"] == "confermata"  # mai no-show automatico


def test_no_show_only_explicit(conn):
    b = mk_booking(conn, "2026-09-10", "2026-09-12")
    with pytest.raises(AppError):
        bookings.change_status(conn, b["id"], "no_show", {"version": b["version"]})
    r = bookings.change_status(conn, b["id"], "no_show", {"version": b["version"], "confirm": True})
    assert r["status"] == "no_show"


def test_booking_without_documents_persists_after_reopen(conn, data_dir):
    # A: prenotazione senza documenti, chiudo e riapro
    b = mk_booking(conn, "2027-05-01", "2027-05-04", notes="nessun documento ancora")
    conn.close()
    c2 = db.connect()
    r = c2.execute("SELECT * FROM bookings WHERE id=?", (b["id"],)).fetchone()
    assert r["booker_name"] == "Referente Prova" and r["notes"] == "nessun documento ancora"
    c2.close()


def test_checkin_confirms_only_actual_guests(conn):
    b = mk_booking(conn, "2026-09-20", "2026-09-25")
    g1 = mk_guest(conn, b["id"], surname="ARRIVATO")
    g2 = mk_guest(conn, b["id"], surname="ATTESO")
    bookings.check_in(conn, b["id"], {"version": b["version"], "arrivals": [{"guest_id": g1["id"],
                                                                             "date": "2026-09-20"}]})
    assert guests.get(conn, g1["id"])["presence"] == "presente"
    assert guests.get(conn, g2["id"])["presence"] == "prevista"


def test_capacity_warning(conn):
    assert bookings.capacity_warning(conn, 6)
    assert bookings.capacity_warning(conn, 4) is None


def test_early_departure_frees_nights_and_checkout_with_open_balance(conn):
    b = mk_booking(conn, "2026-10-01", "2026-10-10", base_cents=90000)
    mk_guest(conn, b["id"])
    checkin_all(conn, b["id"], "2026-10-01")
    b = bookings.get(conn, b["id"])
    r = bookings.check_out(conn, b["id"], {"version": b["version"], "date": "2026-10-05"})
    assert r["status"] == "conclusa" and r["departure"] == "2026-10-05"
    assert mk_booking(conn, "2026-10-06", "2026-10-08")  # notti liberate
    s = bookings.checkout_summary(conn, b["id"])
    assert s["balances"]["stay"]["balance_cents"] == 90000  # debito resta aperto e visibile
    assert any(i["kind"] == "incasso" for i in s["open_items"])


def test_preview_shows_consequences_without_saving(conn):
    b = mk_booking(conn, "2027-06-01", "2027-06-05", pricing_mode="per_notte", nightly_cents=10000, base_cents=0)
    mk_booking(conn, "2027-06-07", "2027-06-09")
    p = bookings.preview_update(conn, b["id"], {"departure": "2027-06-08"})
    assert p["nights"] == {"da": 4, "a": 7}
    assert p["price"] == {"da": 40000, "a": 70000}
    assert p["availability"]["conflicts"]
    assert bookings.get(conn, b["id"])["departure"] == "2027-06-05"  # nulla salvato


def test_occupancy_has_explicit_denominator(conn):
    bookings.create_block(conn, {"start": "2027-07-01", "last": "2027-07-02", "kind": "uso_personale",
                                 "reason": "Famiglia"})
    mk_booking(conn, "2027-07-10", "2027-07-15")
    o = bookings.occupancy(conn, "2027-07-01", "2027-08-01")
    assert o["period_nights"] == 31 and o["blocked_nights"] == 2 and o["sellable_nights"] == 29
    assert o["booked_nights"] == 5 and "29 notti vendibili" in o["forecast_denominator"]
    assert o["occupied_nights"] == 0  # previsione e consuntivo separati


def test_referent_not_guest_and_planned_not_exported(conn):
    # C: il referente non soggiorna e non viene esportato
    from app.services import exports
    b = mk_booking(conn, "2026-10-12", "2026-10-14")
    g = mk_guest(conn, b["id"], surname="OSPITE", name="EFFETTIVO")
    guests.verify(conn, g["id"])
    p = exports.alloggiati_preview(conn, "2026-10-12", "2026-10-12")
    assert not p["included"] and p["excluded"][0]["reasons"][0].startswith("Arrivo non ancora registrato")
    checkin_all(conn, b["id"], "2026-10-12")
    p = exports.alloggiati_preview(conn, "2026-10-12", "2026-10-12")
    assert [x["nome"] for x in p["included"]] == ["OSPITE EFFETTIVO"]
    assert all("Referente" not in x["nome"] for x in p["included"] + p["excluded"])
