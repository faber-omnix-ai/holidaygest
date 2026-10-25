"""Fixture con DATI SINTETICI. Nessun dato reale, nessun invio ai portali."""
from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASSWORD = "password-di-prova-123"
ALLOGGIATI_TODAY = "2026-10-13"
RECOVERY = ""
_uid = itertools.count(1)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "dati con spazi è"
    monkeypatch.setenv("GESTIONALE_DATA_DIR", str(d))
    from app.services import exports, tables
    tables.reset_cache()
    # le prove Alloggiati usano arrivi a date fisse (12/10/2026): il «giorno corrente» per la finestra
    # oggi/ieri del portale è fissato al 13/10/2026 (le prove della finestra lo cambiano esplicitamente)
    monkeypatch.setattr(exports, "today_iso", lambda: ALLOGGIATI_TODAY)
    yield d
    from app.state import STATE
    STATE.lock_app()


@pytest.fixture()
def conn(data_dir):
    from app import db
    from app.services import accounts, tax
    db.init_db()
    c = db.connect()
    code = accounts.setup(c, "proprietaria", PASSWORD)
    st = db.get_setting(c, "structure")
    st.update({"name": "Casa di Prova", "address": "Via di Prova 1", "cin": "CIN-PROVA", "tax_comune": "Alghero",
               "activity_type": "locazione_turistica", "tax_category": "extra_alberghiera", "category_confirmed": True,
               "capacity": 4, "cleaning_minutes": 120, "alloggiati": {"format": "168", "apartment_id": ""},
               "ross": {"code": "TEST000", "units": 1, "beds": 4, "include_names": False, "include_bookings": False},
               "ross_sends_alloggiati": False})
    db.set_setting(c, "structure", st)
    rid = c.execute("SELECT id FROM tax_rules").fetchone()[0]
    tax.approve_rule(c, rid)
    import conftest
    conftest.RECOVERY = code
    yield c
    c.close()


def uid() -> str:
    return f"test-op-{next(_uid):06d}"


def mk_booking(conn, arrival, departure, status="confermata", guests=2, **kw):
    from app.services import bookings
    data = {"booker_name": "Referente Prova", "booker_phone": "000", "arrival": arrival, "departure": departure,
            "guests_expected": guests, "status": status, "base_cents": kw.pop("base_cents", 50000),
            "tourism_type": "Balneare", "transport": "Aereo", **kw}
    return bookings.create(conn, data)


def mk_guest(conn, booking_id, surname="ROSSI", name="MARIO", birth="1980-05-10", gtype="16", **kw):
    from app.services import guests
    data = {"guest_type": gtype, "surname": surname, "name": name, "sex": kw.pop("sex", "M"), "birth_date": birth,
            "birth_state_code": "100000100", "birth_comune_code": "420090064", "citizenship_code": "100000100",
            "res_state_code": "100000100", "res_comune_code": "420090064",
            "doc": {"type": "IDENT", "number": "XX0000000", "issue_place": "420090064"}, **kw}
    if gtype in ("19", "20"):
        data.pop("doc")
    return guests.save(conn, booking_id, data)


def checkin_all(conn, booking_id, day):
    from app.services import bookings
    gs = conn.execute("SELECT id FROM guests WHERE booking_id=?", (booking_id,)).fetchall()
    b = bookings.get(conn, booking_id)
    return bookings.check_in(conn, booking_id, {"version": b["version"],
                                                "arrivals": [{"guest_id": g[0], "date": day, "time": "16:00"}
                                                             for g in gs]})
