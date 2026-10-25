import json
import logging
import os
import shutil

import pytest

from app import config, db
from app.db import AppError
from app.services import backup, exports, guests, mrz, retention
from app.state import STATE
from conftest import PASSWORD, checkin_all, mk_booking, mk_guest
import conftest


def _sample(conn):
    b = mk_booking(conn, "2026-10-12", "2026-10-15")
    g = mk_guest(conn, b["id"], surname="SINTETICO", name="OSPITE")
    guests.verify(conn, g["id"])
    checkin_all(conn, b["id"], "2026-10-12")
    return b, g


def test_backup_restore_other_windows_user(conn, data_dir, tmp_path, monkeypatch):
    # K: ripristino su altro PC/utente: serve solo il file e la password (o il codice di recupero)
    b, g = _sample(conn)
    path = backup.create_local(conn)
    data = path.read_bytes()
    assert b"SINTETICO" not in data and b"XX0000000" not in data  # contenuto cifrato
    conn.close()
    STATE.lock_app()
    other = tmp_path / "AltroUtente" / "AppData Locale"
    monkeypatch.setenv("GESTIONALE_DATA_DIR", str(other))
    db.init_db()  # come all'avvio del programma su un PC nuovo: database vuoto, nessun utente
    with pytest.raises(AppError):
        backup.restore(data, "password-sbagliata", False)
    # dalla PRIMA schermata (nessuna conferma di sostituzione): deve riuscire perché non c'è un archivio in uso
    rep = backup.restore(data, conftest.RECOVERY, False)  # codice di recupero
    assert rep["counts"]["prenotazioni"] == 1
    c = db.connect()
    gg = guests.get(c, g["id"])
    assert guests.doc_of(gg)["number"] == "XX0000000"
    c.close()


def test_restore_reapplies_deletions(conn, data_dir):
    b, g = _sample(conn)
    path = backup.create_local(conn)          # backup PRIMA dell'eliminazione
    batch, _ = exports.alloggiati_generate(conn, "2026-10-12", "2026-10-12", confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    exports.register_outcome(conn, batch["id"], {"all": "accettato"})
    exports.receipt_acquired(conn, batch["id"])
    assert guests.get(conn, g["id"])["doc_enc"] is None
    conn.close()
    rep = backup.restore(path.read_bytes(), PASSWORD, confirm_replace=True)
    assert rep["safety_copy"] and os.path.isdir(rep["safety_copy"])
    assert rep["retention_reapplied"]["documenti"] >= 1
    c = db.connect()
    assert guests.get(c, g["id"])["doc_enc"] is None  # il ripristino non riporta in vita il documento
    c.close()


def test_restore_requires_confirmation_and_rejects_corruption(conn, data_dir):
    _sample(conn)
    data = backup.create_local(conn).read_bytes()
    with pytest.raises(AppError):
        backup.restore(data, PASSWORD, confirm_replace=False)
    broken = data[:-50] + bytes(50)
    with pytest.raises(AppError):
        backup.verify_bytes(broken, secret=PASSWORD)
    with pytest.raises(AppError):
        backup.restore(b"non un backup", PASSWORD, True)
    assert db.connect().execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1  # archivio intatto


def test_external_copy_and_missing_usb(conn, data_dir, tmp_path):
    _sample(conn)
    usb = tmp_path / "E chiavetta"
    usb.mkdir()
    dst = backup.copy_external(conn, str(usb))
    assert dst.exists() and dst.read_bytes().startswith(b"GCBAK1")
    with pytest.raises(AppError):
        backup.copy_external(conn, str(tmp_path / "unità rimossa"))
    # destinazione vuota o relativa: rifiutata, mai una «copia esterna» nella cartella del programma
    for bad in ("", "   ", "Backup", r".\sotto"):
        with pytest.raises(AppError):
            backup.copy_external(conn, bad)
    assert (db.get_setting(conn, "backup") or {}).get("external_dir") == str(usb)
    st = db.get_setting(conn, "backup")
    assert st["local_last_ok_at"] and st["external_last_error"]  # insuccesso segnalato, uso normale invariato


def test_program_update_keeps_data(conn, data_dir):
    # L: sostituire la cartella programma non tocca la cartella dati
    _sample(conn)
    assert config.db_path().parent == data_dir
    assert not str(data_dir).startswith(str(config.program_dir()))
    db.init_db()  # nuovo avvio/migrazione idempotente
    assert db.connect().execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1


def test_no_personal_data_in_logs_and_audit(conn, data_dir, caplog):
    caplog.set_level(logging.DEBUG)
    _sample(conn)
    audit = json.dumps([dict(r) for r in conn.execute("SELECT * FROM audit").fetchall()])
    for secret in ("SINTETICO", "XX0000000", "Referente Prova"):
        assert secret not in audit and secret not in caplog.text


def test_mrz_td3_with_ocr_confusion():
    text = ("P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C36UT07408122F1204159ZE184226B<<<<<10")  # 'UT0' letto al posto di 'UTO'
    r = mrz.parse(text)
    f = r["fields"]
    assert f["surname"]["value"] == "ERIKSSON" and f["name"]["value"] == "ANNA MARIA"
    assert f["birth_date"] == {"value": "1974-08-12", "status": "letto"}
    assert f["doc.number"]["status"] == "letto" and f["sex"]["value"] == "F"
    assert f["nationality_iso3"]["value"] == "UTO"


def test_mrz_td1_and_bad_check_digit():
    td1 = ("I<UTOD231458907<<<<<<<<<<<<<<<\n7408122F1204159UTO<<<<<<<<<<<6\nERIKSSON<<ANNA<MARIA<<<<<<<<<<")
    r = mrz.parse(td1)
    assert r["fields"]["doc.number"]["value"] == "D23145890" and r["format_ok"]
    bad = td1.replace("7408122", "7408129")
    assert mrz.parse(bad)["fields"]["birth_date"]["status"] == "dubbio"


def test_unreadable_text_gives_no_invented_fields():
    assert mrz.parse("testo qualsiasi senza zona leggibile") is None


def test_formula_injection_neutralized():
    from app.services.reports import safe_cell, to_csv
    assert safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert b"'=1+1" in to_csv(["a"], [["=1+1"]])
