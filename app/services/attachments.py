"""Allegati (ricevute ufficiali e di versamento): file cifrati nella cartella dati/allegati."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3

from .. import config
from ..db import AppError, audit, now_iso, row
from ..security import decrypt_bytes, encrypt_bytes
from ..state import STATE
from .ocr import sniff

MAX = 15 * 1024 * 1024


def save(conn: sqlite3.Connection, kind: str, ref_table: str, ref_id: int, filename: str, data: bytes,
         delete_after: str | None) -> int:
    if len(data) > MAX:
        raise AppError("File troppo grande (massimo 15 MB).", 413)
    mime = sniff(data)
    if mime not in ("application/pdf", "image/jpeg", "image/png"):
        raise AppError("Allegare un PDF, JPG o PNG.")
    stored = secrets.token_hex(16) + ".bin"
    (config.data_dir() / "allegati" / stored).write_bytes(
        encrypt_bytes(STATE.require_dek(), data, aad=stored.encode()))
    cur = conn.execute("INSERT INTO attachments(kind,ref_table,ref_id,filename,mime,stored_name,size,sha256,"
                       "delete_after,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (kind, ref_table, ref_id, (filename or "allegato")[:120], mime, stored, len(data),
                        hashlib.sha256(data).hexdigest(), delete_after, now_iso()))
    audit(conn, "allegato_salvato", "attachment", cur.lastrowid, kind)
    return cur.lastrowid


def load(conn: sqlite3.Connection, att_id: int) -> tuple[dict, bytes]:
    a = row(conn.execute("SELECT * FROM attachments WHERE id=?", (att_id,)))
    if not a:
        raise AppError("Allegato inesistente.", 404)
    p = config.data_dir() / "allegati" / a["stored_name"]
    if not p.exists():
        raise AppError("File dell'allegato non trovato nella cartella dati.", 404)
    return a, decrypt_bytes(STATE.require_dek(), p.read_bytes(), aad=a["stored_name"].encode())
