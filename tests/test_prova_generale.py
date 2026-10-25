"""Difetti emersi nella prova generale del 14/10/2026 (pacchetto Windows, dati sintetici): non devono ripresentarsi."""
import pytest

from app.db import AppError, now_iso
from app.services import bookings, exports, guests
from app.util import add_days
from conftest import checkin_all, mk_booking, mk_guest

TODAY = now_iso()[:10]


def test_future_actual_departure_refused(conn):
    b = mk_booking(conn, add_days(TODAY, -1), add_days(TODAY, 3), guests=2)
    g1 = mk_guest(conn, b["id"])
    mk_guest(conn, b["id"], name="LUIGI", birth="1985-01-01")
    checkin_all(conn, b["id"], add_days(TODAY, -1))
    with pytest.raises(AppError) as ex:
        bookings.guest_departure(conn, b["id"], g1["id"], add_days(TODAY, 2))
    assert "futura" in ex.value.message
    with pytest.raises(AppError):
        bookings.check_out(conn, b["id"], {"version": bookings.get(conn, b["id"])["version"],
                                           "date": add_days(TODAY, 2)})
    assert guests.get(conn, g1["id"])["presence"] == "presente"


def test_checkout_after_booked_end_needs_explicit_extension(conn):
    b = mk_booking(conn, add_days(TODAY, -6), add_days(TODAY, -3), guests=1)
    mk_guest(conn, b["id"])
    checkin_all(conn, b["id"], add_days(TODAY, -6))
    v = bookings.get(conn, b["id"])["version"]
    with pytest.raises(AppError) as ex:                    # partenza registrata in ritardo = proroga non voluta
        bookings.check_out(conn, b["id"], {"version": v, "date": TODAY})
    assert ex.value.status == 409 and ex.value.extra["needs_extend_ack"] and ex.value.extra["extra_nights"] == 3
    assert bookings.get(conn, b["id"])["departure"] == add_days(TODAY, -3)
    bookings.check_out(conn, b["id"], {"version": v, "date": TODAY, "extend_ack": True})
    assert bookings.get(conn, b["id"])["departure"] == TODAY


def test_single_guest_departure_cannot_exceed_booking(conn):
    b = mk_booking(conn, add_days(TODAY, -6), add_days(TODAY, -3), guests=2)
    g1 = mk_guest(conn, b["id"])
    mk_guest(conn, b["id"], name="LUIGI", birth="1985-01-01")
    checkin_all(conn, b["id"], add_days(TODAY, -6))
    with pytest.raises(AppError) as ex:
        bookings.guest_departure(conn, b["id"], g1["id"], TODAY)
    assert "proroga" in ex.value.message


def test_ross_today_allowed_with_warning_future_refused(conn):
    r = exports.ross_build(conn, add_days(TODAY, -2), TODAY)
    assert not any("futur" in e for e in r["config_errors"]) and r["warnings"]
    r = exports.ross_build(conn, add_days(TODAY, -2), add_days(TODAY, 1))
    assert any("future" in e for e in r["config_errors"])


def test_preview_lists_changed_fields_in_italian_only_when_changed(conn):
    b = mk_booking(conn, "2027-05-01", "2027-05-04", guests=2)
    p = bookings.preview_update(conn, b["id"], {"booking_channel": "", "transport": "Auto"})
    assert [c["label"] for c in p["changes"].values()] == ["mezzo di trasporto"]


def test_correction_message_names_guest_and_what_changed(conn):
    from test_exports import DAY, _family
    b, capo, fam, est = _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    guests.save(conn, b["id"], {"birth_date": "1990-01-02", "version": guests.get(conn, est["id"])["version"]},
                est["id"])
    exports.reassess(conn)
    reason = conn.execute("SELECT reason FROM corrections WHERE status='aperta'").fetchone()[0]
    assert reason.startswith("MÜLLER ANNA:") and "anagrafica" in reason


def test_receipt_counts_only_documents_really_deleted(conn):
    from test_exports import DAY, _family
    _family(conn)  # capofamiglia e ospite singolo hanno un documento; il familiare no
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    exports.register_outcome(conn, batch["id"], {"all": "accettato"})
    assert exports.receipt_acquired(conn, batch["id"]) == 2


def test_today_screen_with_departed_guest_not_yet_communicated(conn):
    # Oggi andava in errore: la variabile delle partenze veniva sovrascritta nel calcolo dei termini Alloggiati
    from app import api
    b = mk_booking(conn, add_days(TODAY, -5), add_days(TODAY, -2), guests=1)
    mk_guest(conn, b["id"])
    checkin_all(conn, b["id"], add_days(TODAY, -5))
    bookings.check_out(conn, b["id"], {"version": bookings.get(conn, b["id"])["version"], "date": add_days(TODAY, -2)})
    b2 = mk_booking(conn, add_days(TODAY, -1), add_days(TODAY, 2), guests=1)
    mk_guest(conn, b2["id"], name="LUIGI", birth="1985-01-01")
    checkin_all(conn, b2["id"], add_days(TODAY, -1))
    t = api.today(None, conn)
    assert isinstance(t["departures"], list) and [x["id"] for x in t["departures"]] == [b2["id"]]
    assert any("Alloggiati" in x["text"] for x in t["deadlines"])
