"""Accesso SQLite: connessioni, migrazioni, impostazioni, transazioni serializzate."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA_VERSION = 3


class AppError(Exception):
    """Errore mostrabile all'utente (in italiano)."""

    def __init__(self, message: str, status: int = 400, field: str | None = None, extra: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field
        self.extra = extra


class ConflictError(AppError):
    def __init__(self, message: str, extra: Any = None):
        super().__init__(message, 409, extra=extra)


def now_iso() -> str:
    return datetime.now(config.TZ).isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now(config.TZ).date().isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.db_path()), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


class DatabaseTooNew(RuntimeError):
    """Archivio creato da una versione più recente: non si apre per non danneggiarlo."""


# Migrazioni dello schema: versione -> funzione(conn) oppure script SQL. Ognuna è eseguita in una transazione
# propria insieme all'aggiornamento di user_version (tutto o niente). I database nuovi nascono da schema.sql
# già alla versione corrente. Esempio per la versione 2:  MIGRATIONS[2] = "ALTER TABLE bookings ADD COLUMN x TEXT;"
# Versione 2 (0.2.6): registro dei lavori di manutenzione. Stesso testo in fondo a schema.sql.
MAINTENANCE_SQL = """
CREATE TABLE IF NOT EXISTS maintenance_jobs (
  id          INTEGER PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  priority    TEXT NOT NULL DEFAULT 'normale' CHECK (priority IN ('urgente','normale','bassa')),
  due_date    TEXT,
  status      TEXT NOT NULL DEFAULT 'da_fare' CHECK (status IN ('da_fare','in_corso','risolto','annullato')),
  contractor  TEXT,
  quote_cents INTEGER,
  cost_cents  INTEGER,
  resolved_at TEXT,
  version     INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_notes (
  id      INTEGER PRIMARY KEY,
  job_id  INTEGER NOT NULL REFERENCES maintenance_jobs(id),
  at      TEXT NOT NULL,
  kind    TEXT NOT NULL CHECK (kind IN ('nota','stato','modifica','allegato')),
  text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_maintenance_notes_job ON maintenance_notes(job_id)
"""
# Versione 3 (0.2.7): apparecchi della casa, rubrica delle ditte, lavori periodici. Stesso testo in fondo a schema.sql.
# Le ditte già scritte nei lavori diventano voci della rubrica (una per nome) e i lavori vi vengono collegati.
ASSETS_SQL = """
CREATE TABLE IF NOT EXISTS maintenance_contractors (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  specialty  TEXT,
  phone      TEXT,
  email      TEXT,
  notes      TEXT,
  active     INTEGER NOT NULL DEFAULT 1,
  version    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_assets (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  category       TEXT,
  brand          TEXT,
  model          TEXT,
  location       TEXT,
  purchased_on   TEXT,
  warranty_until TEXT,
  notes          TEXT,
  active         INTEGER NOT NULL DEFAULT 1,
  version        INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
ALTER TABLE maintenance_jobs ADD COLUMN asset_id INTEGER REFERENCES maintenance_assets(id);
ALTER TABLE maintenance_jobs ADD COLUMN contractor_id INTEGER REFERENCES maintenance_contractors(id);
ALTER TABLE maintenance_jobs ADD COLUMN recur_months INTEGER CHECK (recur_months IS NULL OR recur_months BETWEEN 1 AND 120);
ALTER TABLE maintenance_jobs ADD COLUMN prev_job_id INTEGER REFERENCES maintenance_jobs(id);
ALTER TABLE maintenance_jobs ADD COLUMN next_job_id INTEGER REFERENCES maintenance_jobs(id);
CREATE INDEX IF NOT EXISTS ix_maintenance_jobs_asset ON maintenance_jobs(asset_id);
CREATE INDEX IF NOT EXISTS ix_maintenance_jobs_contractor ON maintenance_jobs(contractor_id);
INSERT INTO maintenance_contractors(name, created_at, updated_at)
  SELECT TRIM(contractor), MIN(created_at), MIN(created_at) FROM maintenance_jobs
  WHERE TRIM(COALESCE(contractor, '')) <> '' GROUP BY TRIM(contractor);
UPDATE maintenance_jobs SET contractor_id = (SELECT c.id FROM maintenance_contractors c
  WHERE c.name = TRIM(maintenance_jobs.contractor)) WHERE TRIM(COALESCE(contractor, '')) <> ''
"""
MIGRATIONS: dict[int, Any] = {2: MAINTENANCE_SQL, 3: ASSETS_SQL}


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        if ver > SCHEMA_VERSION:
            raise DatabaseTooNew("Il database proviene da una versione più recente del programma.")
        if ver < 1:
            sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        for v in range(ver + 1, SCHEMA_VERSION + 1):
            step = MIGRATIONS.get(v)
            if step is None:
                raise RuntimeError(f"Migrazione dello schema alla versione {v} mancante.")
            conn.execute("BEGIN IMMEDIATE")
            try:
                if callable(step):
                    step(conn)
                else:
                    for stmt in [x.strip() for x in step.split(";") if x.strip()]:
                        conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {v}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transazione IMMEDIATE: serializza le scritture anche tra più finestre."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def audit(conn: sqlite3.Connection, action: str, entity: str | None = None,
          entity_id: int | None = None, detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit(at, action, entity, entity_id, detail) VALUES (?,?,?,?,?)",
        (now_iso(), action, entity, entity_id, detail),
    )


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def row(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None
