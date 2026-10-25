"""Voci prima solo «implementate», ora coperte da test (check pre-consegna del 15/10/2026)."""
import pytest

from app import api
from app.db import AppError
from app.services import bookings, guests, tables
from conftest import checkin_all, mk_booking, mk_guest


# ---------------- preparazione dell'appartamento e cambio ospiti ----------------
def test_same_day_turnover_listed_with_time_and_prep_status(conn):
    a = mk_booking(conn, "2026-11-10", "2026-11-13", guests=1)
    b = mk_booking(conn, "2026-11-13", "2026-11-16", guests=1)
    tl = bookings.turnover_list(conn, "2026-11-01", "2026-11-30")
    assert len(tl) == 1
    x = tl[0]
    assert (x["departure_id"], x["arrival_id"]) == (a["id"], b["id"]) and x["same_day"]
    assert (x["checkout"], x["checkin"], x["gap_minutes"]) == ("10:00", "15:00", 300) and x["compatible"]


def test_checkout_marks_next_arrival_to_prepare_and_prep_states(conn):
    a = mk_booking(conn, "2026-10-08", "2026-10-11", guests=1)
    b = mk_booking(conn, "2026-10-11", "2026-10-14", guests=1)
    bookings.set_prep_status(conn, b["id"], "pronto")
    mk_guest(conn, a["id"])
    checkin_all(conn, a["id"], "2026-10-08")
    bookings.check_out(conn, a["id"], {"version": bookings.get(conn, a["id"])["version"], "date": "2026-10-11"})
    assert bookings.get(conn, b["id"])["prep_status"] == "da_preparare"  # dopo una partenza va ripreparato
    for s in ("in_preparazione", "pronto"):
        bookings.set_prep_status(conn, b["id"], s)
        assert bookings.get(conn, b["id"])["prep_status"] == s
    with pytest.raises(AppError):
        bookings.set_prep_status(conn, b["id"], "pulito")


# ---------------- comuni cessati nelle tabelle ufficiali ----------------
GIUNCUGNANO = "409046016"  # comune cessato il 31/12/2014 (tabella Alloggiati Web)


def test_ceased_comune_valid_only_before_its_end_date():
    assert tables.valid_on("comuni", GIUNCUGNANO, "1980-05-10") == (True, None)
    ok, msg = tables.valid_on("comuni", GIUNCUGNANO, "2016-03-01")
    assert not ok and "cessato il 31/12/2014" in msg
    hit = [x for x in tables.search("comuni", "GIUNCUGNANO", on_date="2016-03-01") if x["code"] == GIUNCUGNANO][0]
    assert hit["soppresso"]
    hit = [x for x in tables.search("comuni", "GIUNCUGNANO", on_date="1980-05-10") if x["code"] == GIUNCUGNANO][0]
    assert not hit["soppresso"]


def test_guest_born_in_ceased_comune_checked_at_birth_date(conn):
    b = mk_booking(conn, "2026-10-12", "2026-10-14", guests=2)
    old = mk_guest(conn, b["id"], birth="1980-05-10", birth_comune_code=GIUNCUGNANO)
    young = mk_guest(conn, b["id"], name="LUCA", birth="2016-03-01", birth_comune_code=GIUNCUGNANO)
    assert not [e for e in guests.check(old, guests.doc_of(old), "verifica") if e["field"] == "birth_comune_code"]
    errs = [e for e in guests.check(young, guests.doc_of(young), "verifica") if e["field"] == "birth_comune_code"]
    assert errs and "cessato" in errs[0]["message"]


# ---------------- archivio nuovo: nessun dato precompilato, tutto in «Configurazione da completare» ----------------
def test_new_archive_is_empty_and_lists_what_to_configure(data_dir):
    from app import db
    from app.services import accounts
    db.init_db()
    c = db.connect()
    try:
        accounts.setup(c, "proprietaria", "password-di-prova-123")
        st = db.get_setting(c, "structure")
        assert (st["name"], st["address"], st["cin"], st["iun"], st["tax_comune"]) == ("", "", "", "", "")
        assert not st["category_confirmed"] and st["capacity"] is None and st["alloggiati"]["format"] is None
        assert (st["ross"]["code"], st["ross"]["units"], st["ross"]["beds"]) == ("", None, None)
        assert st["ross_sends_alloggiati"] is None
        assert not st["ross"].get("configured_on") and api._ross_pending_days(c, "2026-12-01") == []
        rule = c.execute("SELECT comune, status, approved_at FROM tax_rules").fetchone()
        assert tuple(rule) == ("Alghero", "da_verificare", None)          # solo esempio, mai approvato da solo
        todo = " | ".join(api.today(None, c)["setup_todo"])
        for voce in ("CIN", "Comune dell'imposta", "categoria", "168 o 174", "codice struttura ROSS",
                     "trasmette già ad Alloggiati", "regola dell'imposta", "capienza"):
            assert voce in todo, voce
        # configurata la struttura e approvata una regola: lista vuota
        st.update({"name": "Casa", "address": "Via 1", "cin": "CIN", "tax_comune": "Alghero", "category_confirmed": True,
                   "tax_category": "extra_alberghiera", "capacity": 4, "alloggiati": {"format": "168"},
                   "ross_sends_alloggiati": False, "ross": {"code": "X1", "units": 1, "beds": None}})
        db.set_setting(c, "structure", st)
        from app.services import tax
        tax.approve_rule(c, c.execute("SELECT id FROM tax_rules").fetchone()[0])
        assert api.today(None, c)["setup_todo"] == ["Indicare unità ricettive e letti disponibili per ROSS 1000."]
    finally:
        c.close()


# ---------------- promemoria regola dell'imposta per l'anno successivo ----------------
def test_reminder_for_bookings_in_year_without_approved_rule(conn):
    mk_booking(conn, "2027-06-10", "2027-06-14", guests=2)
    r = api._tax_rule_reminders(conn, "2026-10-15")
    assert len(r) == 1 and r[0]["text"].startswith("Imposta di soggiorno 2027") and r[0]["due"] == "2027-06-10"


def test_reminder_in_december_for_next_year_rule(conn):
    assert api._tax_rule_reminders(conn, "2026-11-30") == []
    r = api._tax_rule_reminders(conn, "2026-12-01")
    assert len(r) == 1 and "2027" in r[0]["text"] and r[0]["due"] == "2026-12-31"
    assert not any("2026" in x["text"] for x in api._tax_rule_reminders(conn, "2026-06-01"))
