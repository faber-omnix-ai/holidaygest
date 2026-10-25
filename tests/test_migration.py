"""Aggiornamento dello schema: copia di sicurezza prima, ripristino se fallisce. Archivio sintetico."""
import os
import sqlite3
import time

import pytest

from app import config, db, main
from conftest import mk_booking


def _count(path, table="bookings"):
    c = sqlite3.connect(str(path))
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


@pytest.fixture()
def v1_archive(conn):
    mk_booking(conn, "2026-08-01", "2026-08-05")
    conn.close()
    return config.db_path()


V = db.SCHEMA_VERSION  # archivio di prova alla versione corrente; le migrazioni simulate sono V+1, V+2


def test_migration_creates_verified_copy_and_applies(v1_archive, monkeypatch):
    monkeypatch.setattr(db, "SCHEMA_VERSION", V + 1)
    monkeypatch.setitem(db.MIGRATIONS, V + 1, "ALTER TABLE bookings ADD COLUMN nota_prova TEXT; "
                                              "UPDATE bookings SET nota_prova='migrata'")
    name = main.migrate_with_backup()
    assert name and name.startswith(f"pre_migrazione_v{V}_")
    copy = config.data_dir() / "backup" / name
    assert _count(copy) == (1, V)                    # copia integra alla versione precedente
    assert _count(v1_archive) == (1, V + 1)          # archivio aggiornato, dati conservati
    c = sqlite3.connect(str(v1_archive))
    assert c.execute("SELECT nota_prova FROM bookings").fetchone()[0] == "migrata"
    c.close()
    assert main.migrate_with_backup() is None        # seconda volta: niente da fare, nessuna nuova copia


def test_failed_migration_restores_archive(v1_archive, monkeypatch):
    def broken(c):
        c.execute("ALTER TABLE bookings ADD COLUMN mezza TEXT")
        raise RuntimeError("errore simulato a metà migrazione")
    monkeypatch.setattr(db, "SCHEMA_VERSION", V + 2)
    monkeypatch.setitem(db.MIGRATIONS, V + 1, "ALTER TABLE bookings ADD COLUMN passo2 TEXT")
    monkeypatch.setitem(db.MIGRATIONS, V + 2, broken)
    with pytest.raises(RuntimeError):
        main.migrate_with_backup()
    assert _count(v1_archive) == (1, V)              # tornato esattamente alla versione di partenza
    c = sqlite3.connect(str(v1_archive))
    cols = [r[1] for r in c.execute("PRAGMA table_info(bookings)")]
    assert "passo2" not in cols and "mezza" not in cols and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    c.close()
    monkeypatch.setitem(db.MIGRATIONS, V + 2, "ALTER TABLE bookings ADD COLUMN passo3 TEXT")
    assert main.migrate_with_backup()                # corretto il programma, l'aggiornamento riesce
    assert _count(v1_archive) == (1, V + 2)


def test_newer_archive_is_refused_untouched(v1_archive):
    c = sqlite3.connect(str(v1_archive))
    c.execute("PRAGMA user_version = 99")
    c.close()
    before = v1_archive.read_bytes()
    with pytest.raises(db.DatabaseTooNew):
        main.migrate_with_backup()
    assert v1_archive.read_bytes() == before


def test_old_premigration_copies_are_purged(data_dir):
    config.data_dir()
    old = config.data_dir() / "backup" / "pre_migrazione_v1_20250101_000000.sqlite3"
    new = config.data_dir() / "backup" / "pre_migrazione_v1_20260101_000000.sqlite3"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    t = time.time() - (main.PRE_MIGRATION_KEEP_DAYS + 1) * 86400
    os.utime(old, (t, t))
    main.migrate_with_backup()
    assert not old.exists() and new.exists()
