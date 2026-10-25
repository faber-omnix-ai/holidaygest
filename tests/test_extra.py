import json
import threading
import urllib.error
import urllib.request

import pytest

from app import db
from app.db import AppError
from app.services import bookings, guests, ocr, periods, tax
from app.state import STATE
from conftest import PASSWORD, checkin_all, mk_booking, mk_guest


def test_ocr_unavailable_manual_path_still_works(conn, monkeypatch):
    # M: il motore OCR non funziona -> errore chiaro, l'inserimento manuale resta disponibile
    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setattr(ocr, "_engine_error", "ImportError")
    assert ocr.status()["available"] is False
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "PNG")
    up = ocr.add_upload(buf.getvalue(), "x.png")
    with pytest.raises(AppError) as ex:
        ocr.read(up["upload_id"])
    assert ex.value.status == 503 and "manuale" in ex.value.message
    b = mk_booking(conn, "2026-10-01", "2026-10-03", guests=1)
    g = mk_guest(conn, b["id"])
    assert guests.verify(conn, g["id"])["verified_at"]
    ocr.discard(up["upload_id"])
    assert not STATE.uploads


def test_upload_validation():
    with pytest.raises(AppError):
        ocr.add_upload(b"MZ\x90\x00 eseguibile", "virus.exe")
    with pytest.raises(AppError) as ex:
        ocr.add_upload(b"\x00\x00\x00\x18ftypheic" + b"0" * 20, "foto.heic")
    assert "HEIC" in ex.value.message
    with pytest.raises(AppError):
        ocr.add_upload(b"\xff\xd8\xff" + b"0" * (16 * 1024 * 1024), "grande.jpg")


def test_homonyms_not_merged_duplicates_flagged(conn):
    b1 = mk_booking(conn, "2026-09-01", "2026-09-03", guests=1)
    b2 = mk_booking(conn, "2026-09-05", "2026-09-07", guests=1)
    b3 = mk_booking(conn, "2026-09-08", "2026-09-10", guests=1)
    g1 = mk_guest(conn, b1["id"], surname="ROSSI", name="MARIO", birth="1980-05-10")
    g2 = mk_guest(conn, b2["id"], surname="ROSSI", name="MARIO", birth="1980-05-10")
    g3 = mk_guest(conn, b3["id"], surname="ROSSI", name="MARIO", birth="1975-01-01")  # omonimo
    assert [d["id"] for d in guests.duplicates(conn, g2)] == [g1["id"]]
    assert all(d["id"] != g3["id"] for d in guests.duplicates(conn, g1))
    assert conn.execute("SELECT COUNT(*) FROM guests").fetchone()[0] == 3  # nessuna unione


def test_zero_night_stay_rejected(conn):
    with pytest.raises(AppError):
        mk_booking(conn, "2026-09-01", "2026-09-01")


def test_period_close_and_change_opens_correction(conn):
    from app.services import consistency
    b = mk_booking(conn, "2026-07-01", "2026-07-04", guests=1)
    g = mk_guest(conn, b["id"])
    checkin_all(conn, b["id"], "2026-07-01")
    s = periods.check(conn, "trimestre", "2026-T3")
    assert s["tax_nights"].get("imponibile") == 3 and s["tax_computed_cents"] == 600
    assert s["anomalies"]  # comunicazioni non registrate, ecc.
    with pytest.raises(AppError):
        periods.close(conn, "trimestre", "2026-T3", confirm_anomalies=False, reason=None)
    c1 = periods.close(conn, "trimestre", "2026-T3", confirm_anomalies=True, reason=None)
    conn.execute("UPDATE guests SET tax_status='residente' WHERE id=?", (g["id"],))
    consistency.reassess_all(conn)
    corr = conn.execute("SELECT * FROM corrections WHERE target='periodo'").fetchone()
    assert corr and corr["entity_id"] == c1["id"]
    with pytest.raises(AppError):
        periods.close(conn, "trimestre", "2026-T3", confirm_anomalies=True, reason=None)
    c2 = periods.close(conn, "trimestre", "2026-T3", confirm_anomalies=True, reason="Residenza documentata")
    old = conn.execute("SELECT status FROM period_closures WHERE id=?", (c1["id"],)).fetchone()[0]
    assert old == "superato" and c2["id"] != c1["id"]


def test_revenue_vs_cash_separated(conn):
    from app.services import money
    from conftest import uid
    b = mk_booking(conn, "2027-03-01", "2027-03-05", base_cents=40000)
    money.record(conn, {"uid": uid(), "booking_id": b["id"], "direction": "entrata", "amount": "100",
                        "op_date": "2026-10-10", "method": "bonifico", "causale": "Acconto",
                        "allocations": [{"category": "soggiorno", "amount": "100"}]})
    oct_ = periods.check(conn, "mese", "2026-10")
    mar = periods.check(conn, "mese", "2027-03")
    assert oct_["stay_received_cents"] == 10000 and oct_["revenue_accrued_cents"] == 0
    assert mar["revenue_accrued_cents"] == 40000 and mar["stay_received_cents"] == 0


@pytest.fixture()
def server(conn):
    from app.server import make_server
    srv = make_server(0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{STATE.port}"
    srv.shutdown()
    srv.server_close()


def _req(url, method="GET", body=None, headers=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_http_protections(server):
    st, hdr, _ = _req(server + "/api/status")
    assert st == 200 and "default-src 'self'" in hdr["Content-Security-Policy"]
    assert _req(server + "/api/status", headers={"Host": "evil.example"})[0] == 421       # anti DNS-rebinding
    assert _req(server + "/api/bookings")[0] == 401                                       # serve l'accesso
    st, _, _ = _req(server + "/api/login", "POST", {"username": "proprietaria", "password": PASSWORD},
                    headers={"Origin": "http://evil.example"})
    assert st == 403                                                                      # origine esterna
    st, hdr, body = _req(server + "/api/login", "POST", {"username": "proprietaria", "password": PASSWORD},
                         headers={"Origin": server})
    assert st == 200 and "HttpOnly" in hdr["Set-Cookie"] and "SameSite=Strict" in hdr["Set-Cookie"]
    cookie = hdr["Set-Cookie"].split(";")[0]
    st, _, _ = _req(server + "/api/bookings", "POST", {"booker_name": "x"}, headers={"Origin": server, "Cookie": cookie})
    assert st == 403                                                                      # manca il token CSRF
    st, _, _ = _req(server + "/api/../../app/config.py")
    assert st in (200, 404)  # mai il file sorgente: lo statico serve solo index.html fuori dalla cartella
    _, _, page = _req(server + "/static/../../app/config.py")
    assert b"APP_NAME" not in page


def test_ross_pending_days_reminder(conn):
    # Regione Sardegna (FAQ, D.G.R. 10/20/2015): movimenti entro 24 ore, anche giornate a zero. Mai retroattivo.
    from app import api
    st = db.get_setting(conn, "structure")
    assert api._ross_pending_days(conn, "2026-10-10") == []          # data di configurazione assente
    st["ross"]["configured_on"] = "2026-09-30"
    db.set_setting(conn, "structure", st)
    conn.execute("INSERT INTO export_batches(kind,created_at,period_from,period_to,file_name,sha256,item_count,"
                 "profile,checks,status) VALUES ('ross','x','2026-10-01','2026-10-05','f.xml','0',5,'p','{}',"
                 "'caricamento_dichiarato')")
    r = api._ross_pending_days(conn, "2026-10-10")
    assert len(r) == 1 and r[0]["text"].startswith("ROSS 1000: 4 giornate") and "06/10" in r[0]["text"]
    assert r[0]["overdue"]
    st["ross"]["configured_on"] = "2026-10-09"
    db.set_setting(conn, "structure", st)
    assert api._ross_pending_days(conn, "2026-10-10") == []          # nessuna giornata trascorsa da allora
