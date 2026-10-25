"""Correzioni dalla revisione esterna del 14/10/2026 (verificate sul codice e sul Manuale Alloggiati Web)."""
import json
import os
import time
from pathlib import Path

import pytest
from lxml import etree

from app import config, db
from app.db import AppError
from app.security import _b64, encrypt_bytes
from app.services import accounts, backup, exports, guests, retention
from app.state import STATE
from conftest import PASSWORD, checkin_all, mk_booking, mk_guest
from test_exports import DAY, _family


# ---------------- Alloggiati: manuale (UTF-8, max 1000 righe, arrivo oggi/ieri, max 30 giorni) ----------------
def test_alloggiati_file_is_utf8_ascii(conn):
    _family(conn)
    batch, data = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    assert data.decode("utf-8").isascii() and "MULLER" in data.decode("utf-8")
    assert json.loads(batch["checks"])["codifica"].startswith("UTF-8")


def test_alloggiati_arrival_older_than_yesterday_excluded(conn, monkeypatch):
    _family(conn)
    monkeypatch.setattr(exports, "today_iso", lambda: "2026-10-14")  # arrivo 12/10 = due giorni fa
    p = exports.alloggiati_preview(conn, DAY, DAY)
    assert not p["included"] and all(any("oggi o di ieri" in r for r in x["reasons"]) for x in p["excluded"])


def test_alloggiati_non_latin_name_excluded(conn):
    b = mk_booking(conn, DAY, "2026-10-14", guests=1)
    g = mk_guest(conn, b["id"], surname="ΠΑΠΑΔΟΠΟΥΛΟΣ", name="NIKOS")
    with pytest.raises(AppError):  # primo blocco: la verifica non accetta lettere non latine
        guests.verify(conn, g["id"])
    checkin_all(conn, b["id"], DAY)
    conn.execute("UPDATE guests SET verified_at='2026-10-12T10:00' WHERE id=?", (g["id"],))  # secondo blocco
    p = exports.alloggiati_preview(conn, DAY, DAY)
    assert not p["included"] and any("non latini" in r for r in p["excluded"][0]["reasons"])


def test_alloggiati_long_stay_needs_explicit_ack(conn):
    b = mk_booking(conn, DAY, "2026-11-20", guests=1)  # 39 notti
    g = mk_guest(conn, b["id"])
    guests.verify(conn, g["id"])
    checkin_all(conn, b["id"], DAY)
    with pytest.raises(AppError) as ex:
        exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    assert ex.value.extra["needs_long_stay_ack"]
    _, data = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False, confirm_long_stay=True)
    assert data.decode()[12:14] == "30"


def test_alloggiati_max_lines(conn, monkeypatch):
    _family(conn)
    monkeypatch.setattr(exports, "ALLOGGIATI_MAX_LINES", 2)
    with pytest.raises(AppError) as ex:
        exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    assert "al massimo 2" in ex.value.message


# ---------------- ROSS 1000 ----------------
def _ross_two_guests(conn):
    b = mk_booking(conn, "2026-09-02", "2026-09-04", guests=2)
    g1 = mk_guest(conn, b["id"])
    g2 = mk_guest(conn, b["id"], name="LUIGI", birth="1985-01-01")
    checkin_all(conn, b["id"], "2026-09-02")
    batch, _ = exports.ross_generate(conn, "2026-09-01", "2026-09-03", confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    return b, g1, g2


def test_ross_deletion_survives_discarded_file(conn):
    _, _, g2 = _ross_two_guests(conn)
    guests.delete(conn, g2["id"], "inserito per errore")
    _, a = exports.ross_generate(conn, "2026-09-06", "2026-09-06", confirm_partial=False)
    assert b"<eliminazione>" in a
    bb, b = exports.ross_generate(conn, "2026-09-06", "2026-09-06", confirm_partial=False)  # file A scartato
    assert b"<eliminazione>" in b
    exports.declare_upload(conn, bb["id"])
    _, c = exports.ross_generate(conn, "2026-09-07", "2026-09-07", confirm_partial=False)
    assert b"<eliminazione>" not in c  # trasmessa con il lotto caricato


def test_ross_occupied_rooms_consistent_with_included_guests(conn):
    b = mk_booking(conn, "2026-09-10", "2026-09-12", guests=1)
    mk_guest(conn, b["id"], res_state_code=None, res_comune_code=None)  # dato ROSS mancante
    checkin_all(conn, b["id"], "2026-09-10")
    _, data = exports.ross_generate(conn, "2026-09-10", "2026-09-10", confirm_partial=True)
    mv = etree.fromstring(data).find("movimento")
    assert mv.findtext("struttura/camereoccupate") == "0" and mv.find("arrivi") is None


# ---------------- backup e ripristino ----------------
def test_backup_carries_deletion_ledger(conn, data_dir):
    retention.ledger_add("doc", 999)
    path = backup.create_local(conn)
    (config.data_dir() / retention.LEDGER).unlink()  # come su un PC nuovo, senza registro
    conn.close()
    backup.restore(path.read_bytes(), PASSWORD, confirm_replace=True)
    assert any(x["kind"] == "doc" and x["id"] == 999 for x in retention.ledger())


def test_restore_failure_leaves_archive_unchanged(conn, data_dir, monkeypatch):
    path = backup.create_local(conn)
    mk_booking(conn, "2026-09-20", "2026-09-22")
    att = config.data_dir() / "allegati"
    att.mkdir(exist_ok=True)
    (att / "dopo_il_backup.bin").write_bytes(b"x")
    conn.close()
    real, dbp = os.replace, config.db_path()

    def failing(src, dst):
        if Path(dst) == dbp:
            raise OSError("file in uso")
        return real(src, dst)

    monkeypatch.setattr(backup.os, "replace", failing)
    with pytest.raises(AppError) as ex:
        backup.restore(path.read_bytes(), PASSWORD, confirm_replace=True)
    assert "invariato" in ex.value.message
    assert (att / "dopo_il_backup.bin").exists()
    c = db.connect()
    assert c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
    c.close()


def test_backups_in_same_second_get_distinct_names(conn, data_dir):
    a, b = backup.create_local(conn), backup.create_local(conn)
    assert a != b and a.exists() and b.exists()


def test_old_safety_copies_purged(conn, data_dir):
    old = config.data_dir() / "backup" / "prima_del_ripristino_20200101_000000"
    old.mkdir(parents=True)
    (old / "gestionale.sqlite3").write_bytes(b"x")
    t = time.time() - 40 * 86400
    os.utime(old, (t, t))
    recent = config.data_dir() / "backup" / "prima_del_ripristino_20990101_000000"
    recent.mkdir()
    assert backup.purge_old_safety_copies() == 1
    assert not old.exists() and recent.exists()


# ---------------- sicurezza ----------------
def test_document_ciphertext_bound_to_its_guest(conn):
    b = mk_booking(conn, DAY, "2026-10-14", guests=2)
    g1 = mk_guest(conn, b["id"])
    g2 = mk_guest(conn, b["id"], name="LUIGI", doc={"type": "IDENT", "number": "YY1111111", "issue_place": "420090064"})
    enc1 = guests.get(conn, g1["id"])["doc_enc"]
    assert enc1.startswith("v2:")
    conn.execute("UPDATE guests SET doc_enc=? WHERE id=?", (enc1, g2["id"]))  # scambio diretto nel database
    with pytest.raises(Exception):
        guests.doc_of(guests.get(conn, g2["id"]))
    # i dati cifrati con il formato precedente (v1) restano leggibili
    v1 = "v1:" + _b64(encrypt_bytes(STATE.require_dek(), json.dumps({"number": "ZZ2"}).encode(), b"field"))
    conn.execute("UPDATE guests SET doc_enc=? WHERE id=?", (v1, g2["id"]))
    assert guests.doc_of(guests.get(conn, g2["id"]))["number"] == "ZZ2"


def test_failed_logins_reset_after_success(conn):
    for _ in range(5):
        with pytest.raises(AppError):
            accounts.login(conn, "proprietaria", "sbagliata")
    assert STATE.sessions.throttle_seconds() > 0
    accounts.login(conn, "proprietaria", PASSWORD)
    assert STATE.sessions.throttle_seconds() == 0
