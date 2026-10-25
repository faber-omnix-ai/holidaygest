from app.db import AppError
from app.services import bookings, tax
from conftest import checkin_all, mk_booking, mk_guest
import pytest


def _stay(conn, arr, dep, people, start_checkin=True):
    b = mk_booking(conn, arr, dep, guests=len(people))
    for i, p in enumerate(people):
        mk_guest(conn, b["id"], surname=f"PROVA{i}", **p)
    if start_checkin:
        checkin_all(conn, b["id"], arr)
    return b


def test_two_adults_three_nights_12_euro(conn):
    b = _stay(conn, "2026-06-01", "2026-06-04", [{}, {}])
    r = tax.compute_booking(conn, b["id"])
    assert r["total_cents"] == 1200 and r["kind"] == "consuntivo" and r["final"]


def test_two_adults_ten_nights_limit_seven_28_euro(conn):
    b = _stay(conn, "2026-06-01", "2026-06-11", [{}, {}])
    r = tax.compute_booking(conn, b["id"])
    assert r["total_cents"] == 2800
    g = r["guests"][0]
    assert g["counts"] == {"imponibile": 7, "oltre_limite": 3}
    assert "7 notti imponibili" in g["explanation"] and "3 notti oltre il limite" in g["explanation"]


def test_resident_plus_adult_6_euro(conn):
    b = _stay(conn, "2026-06-01", "2026-06-04", [{"tax_status": "residente"}, {}])
    r = tax.compute_booking(conn, b["id"])
    assert r["total_cents"] == 600
    assert r["guests"][0]["counts"] == {"non_assoggettata": 3}


def test_minor_under_12_exempt_and_12_years_pays(conn):
    # Regola 2026 (FAQ Comune di Alghero): esenti fino a 11 anni e 364 giorni; dal 12° compleanno imponibili
    b = _stay(conn, "2026-06-01", "2026-06-04", [{"birth": "2015-01-01"}, {"birth": "2014-03-01"}])
    r = tax.compute_booking(conn, b["id"])
    assert r["guests"][0]["counts"] == {"esente": 3}
    assert r["guests"][1]["counts"] == {"imponibile": 3}
    assert r["total_cents"] == 600


def test_birthday_during_stay(conn):
    # compie 12 anni la seconda notte: prima notte esente (11 anni), poi imponibile
    b = _stay(conn, "2026-06-01", "2026-06-04", [{"birth": "2014-06-02"}])
    lines = tax.compute_booking(conn, b["id"])["guests"][0]["lines"]
    assert [l["cls"] for l in lines] == ["esente", "imponibile", "imponibile"]


def test_unclear_threshold_option_keeps_12_years_da_verificare(conn):
    # Opzione «da chiarire» ancora disponibile: le notti a 12 anni compiuti restano DA VERIFICARE, mai zero
    rid = conn.execute("SELECT id FROM tax_rules").fetchone()[0]
    conn.execute("UPDATE tax_rules SET minor_rule='da_chiarire' WHERE id=?", (rid,))
    b = _stay(conn, "2026-06-01", "2026-06-04", [{"birth": "2014-03-01"}])
    r = tax.compute_booking(conn, b["id"])
    assert r["guests"][0]["counts"] == {"da_chiarire": 3} and r["total_cents"] is None


def test_interpretation_recorded_in_rule_is_applied(conn):
    rid = conn.execute("SELECT id FROM tax_rules").fetchone()[0]
    conn.execute("UPDATE tax_rules SET minor_rule='fino_a_12_compresi' WHERE id=?", (rid,))
    b = _stay(conn, "2026-06-01", "2026-06-03", [{"birth": "2014-03-01"}])
    assert tax.compute_booking(conn, b["id"])["total_cents"] == 0


def test_missing_rule_is_da_verificare_not_zero(conn):
    # J: nessuna regola per il 2027 -> DA VERIFICARE, non zero né tariffa 2026
    b = mk_booking(conn, "2026-12-30", "2027-01-02", guests=1)
    mk_guest(conn, b["id"])
    r = tax.compute_booking(conn, b["id"])
    cls = [l["cls"] for l in r["guests"][0]["lines"]]
    assert cls == ["imponibile", "imponibile", "senza_regola"]
    assert r["total_cents"] is None and r["kind"] == "preventivo"
    with pytest.raises(AppError):
        tax.consolidate(conn, b["id"])


def test_rule_da_verificare_is_provisional(conn):
    conn.execute("UPDATE tax_rules SET status='da_verificare'")
    b = _stay(conn, "2026-06-01", "2026-06-03", [{}])
    r = tax.compute_booking(conn, b["id"])
    assert r["total_cents"] == 400 and not r["final"]


def test_individual_periods(conn):
    # D: due persone con durate diverse nella stessa prenotazione
    b = mk_booking(conn, "2026-07-01", "2026-07-06", guests=2)
    g1 = mk_guest(conn, b["id"], surname="UNO")
    g2 = mk_guest(conn, b["id"], surname="DUE", planned_arrival="2026-07-03")
    bk = bookings.get(conn, b["id"])
    bookings.check_in(conn, b["id"], {"version": bk["version"], "arrivals": [{"guest_id": g1["id"], "date": "2026-07-01"}]})
    bk = bookings.get(conn, b["id"])
    bookings.check_in(conn, b["id"], {"version": bk["version"], "arrivals": [{"guest_id": g2["id"], "date": "2026-07-03"}]})
    bookings.guest_departure(conn, b["id"], g2["id"], "2026-07-05")
    r = tax.compute_booking(conn, b["id"])
    per = {g["guest_id"]: g["counts"].get("imponibile") for g in r["guests"]}
    assert per == {g1["id"]: 5, g2["id"]: 2}
    assert r["total_cents"] == 1400


def test_linked_stay_does_not_reset_count(conn):
    b1 = _stay(conn, "2026-08-01", "2026-08-06", [{}])
    g1 = conn.execute("SELECT id FROM guests WHERE booking_id=?", (b1["id"],)).fetchone()[0]
    bookings.check_out(conn, b1["id"], {"version": bookings.get(conn, b1["id"])["version"], "date": "2026-08-06"})
    b2 = mk_booking(conn, "2026-08-06", "2026-08-10", guests=1, linked_booking_id=b1["id"], turnover_ack=True)
    mk_guest(conn, b2["id"], continues_guest_id=g1)
    checkin_all(conn, b2["id"], "2026-08-06")
    r = tax.compute_booking(conn, b2["id"])
    # 5 notti già fatte: nel secondo soggiorno 2 imponibili e 2 oltre il limite
    assert r["guests"][0]["counts"] == {"imponibile": 2, "oltre_limite": 2}


def test_exemption_requires_documentation(conn):
    b = _stay(conn, "2026-06-01", "2026-06-03", [{"tax_status": "forze_servizio"}])
    r = tax.compute_booking(conn, b["id"])
    assert r["total_cents"] == 0 and not r["final"]
    assert any("documentazione" in i for i in r["issues"])


def test_no_night_stay_and_year_change(conn):
    rid = tax.add_rule(conn, {"comune": "Alghero", "category": "extra_alberghiera", "valid_from": "2027-01-01",
                              "valid_to": "2027-12-31", "rate": "3,00", "max_nights": 7, "minor_rule": "meno_di_12",
                              "exemptions": ["residente", "minore"], "source": "PROVA sintetica",
                              "verified_on": "2026-10-13"})
    tax.approve_rule(conn, rid)
    b = mk_booking(conn, "2026-12-30", "2027-01-02", guests=1)
    mk_guest(conn, b["id"])
    r = tax.compute_booking(conn, b["id"])
    assert r["total_cents"] == 200 + 200 + 300  # cambio tariffa per data della notte, conteggio continuo


def test_consolidation_freezes_and_correction_needs_reason(conn):
    b = _stay(conn, "2026-06-01", "2026-06-04", [{}, {}])
    for g in conn.execute("SELECT id FROM guests WHERE booking_id=?", (b["id"],)).fetchall():
        bookings.guest_departure(conn, b["id"], g[0], "2026-06-04")
    a = tax.consolidate(conn, b["id"])
    assert a["total_cents"] == 1200
    rid = conn.execute("SELECT id FROM tax_rules").fetchone()[0]
    with pytest.raises(AppError):
        tax.approve_rule(conn, rid)  # bloccata: usata in conteggi consolidati
    g = conn.execute("SELECT id FROM guests WHERE booking_id=?", (b["id"],)).fetchone()[0]
    conn.execute("UPDATE guests SET tax_status='residente' WHERE id=?", (g,))
    with pytest.raises(AppError):
        tax.consolidate(conn, b["id"])
    a2 = tax.consolidate(conn, b["id"], reason="Residenza documentata dopo la partenza")
    assert a2["total_cents"] == 600 and a2["supersedes_id"] == a["id"]
