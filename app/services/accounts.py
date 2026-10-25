"""Primo avvio, accesso, cambio password e recupero con codice."""
from __future__ import annotations

import json
import secrets
import sqlite3

from .. import config
from ..db import AppError, audit, get_setting, now_iso, set_setting
from ..security import (check_password_policy, hash_password, new_dek, new_recovery_code, normalize_recovery,
                        unwrap_key, verify_password, wrap_key)
from ..state import STATE

# Dati della struttura: vuoti in un archivio nuovo, si inseriscono al primo avvio (Impostazioni → Struttura).
PROPOSED = {"name": "", "address": "", "cin": "", "iun": ""}


def is_setup(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def default_structure() -> dict:
    # Nessun dato precompilato: tipologia, categoria dell'imposta, Comune, capienza, profilo Alloggiati, codice e
    # posti ROSS 1000 restano da indicare e compaiono in «Configurazione da completare» finché mancano.
    return {**PROPOSED, "proposed_unverified": False, "activity_type": None, "tax_comune": "",
            "tax_category": None, "category_confirmed": False, "owner_name": "", "owner_tax_code": "",
            "owner_vat": "", "capacity": None, "checkin_time": "15:00", "checkout_time": "10:00",
            "cleaning_minutes": 120, "alloggiati": {"format": None, "apartment_id": ""},
            "ross": {"code": "", "units": None, "beds": None, "include_names": False, "include_bookings": False},
            "ross_sends_alloggiati": None, "id_prefix": "GC" + secrets.token_hex(2).upper()}


def setup(conn: sqlite3.Connection, username: str, password: str) -> str:
    if is_setup(conn):
        raise AppError("Configurazione iniziale già completata.", 409)
    username = (username or "").strip() or "proprietaria"
    err = check_password_policy(password or "")
    if err:
        raise AppError(err, field="password")
    dek, code = new_dek(), new_recovery_code()
    conn.execute("INSERT INTO users(username,pw_hash,created_at) VALUES (?,?,?)",
                 (username, hash_password(password), now_iso()))
    conn.execute("INSERT INTO keyring(id,wrapped_pw,wrapped_recovery,created_at) VALUES (1,?,?,?)",
                 (wrap_key(dek, password), wrap_key(dek, code), now_iso()))
    if get_setting(conn, "structure") is None:
        set_setting(conn, "structure", default_structure())
    set_setting(conn, "retention", {"anagrafica_years": 5, "confirmed": False})
    from . import tax
    seed = json.loads((config.bundled_data_dir() / "regole_imposta.json").read_text(encoding="utf-8"))
    tax.seed_rules(conn, seed)
    audit(conn, "configurazione_iniziale")
    STATE.dek = dek
    return code


def login(conn: sqlite3.Connection, username: str, password: str) -> int:
    u = conn.execute("SELECT * FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
    if not u or not verify_password(password or "", u["pw_hash"]):
        STATE.sessions.add_failed()
        raise AppError("Nome utente o password non corretti.", 401)
    kr = conn.execute("SELECT wrapped_pw FROM keyring WHERE id=1").fetchone()
    dek = unwrap_key(kr["wrapped_pw"], password)
    if dek is None:
        raise AppError("Password corretta ma chiave dati non apribile: usare il codice di recupero.", 401)
    STATE.dek = dek
    STATE.sessions.reset_failed()
    audit(conn, "accesso")
    return u["id"]


def change_password(conn: sqlite3.Connection, old: str, new: str) -> None:
    u = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    if not verify_password(old or "", u["pw_hash"]):
        raise AppError("Password attuale non corretta.", 403)
    _set_password(conn, u["id"], new, unwrap_key(conn.execute("SELECT wrapped_pw FROM keyring").fetchone()[0], old))


def recover(conn: sqlite3.Connection, code: str, new: str) -> str:
    """Accesso con codice di recupero: imposta una nuova password e genera un NUOVO codice."""
    kr = conn.execute("SELECT * FROM keyring WHERE id=1").fetchone()
    dek = unwrap_key(kr["wrapped_recovery"], normalize_recovery(code or ""))
    if dek is None:
        STATE.sessions.add_failed()
        raise AppError("Codice di recupero non valido.", 403)
    u = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    _set_password(conn, u["id"], new, dek)
    code2 = new_recovery_code()
    conn.execute("UPDATE keyring SET wrapped_recovery=? WHERE id=1", (wrap_key(dek, code2),))
    audit(conn, "recupero_con_codice")
    STATE.dek = dek
    return code2


def _set_password(conn, uid: int, new: str, dek: bytes | None) -> None:
    err = check_password_policy(new or "")
    if err:
        raise AppError(err, field="password")
    if dek is None:
        raise AppError("Chiave dati non disponibile.", 500)
    conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), uid))
    conn.execute("UPDATE keyring SET wrapped_pw=? WHERE id=1", (wrap_key(dek, new),))
    audit(conn, "password_cambiata")


def new_recovery(conn: sqlite3.Connection, password: str) -> str:
    u = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    if not verify_password(password or "", u["pw_hash"]):
        raise AppError("Password non corretta.", 403)
    code = new_recovery_code()
    conn.execute("UPDATE keyring SET wrapped_recovery=? WHERE id=1", (wrap_key(STATE.require_dek(), code),))
    audit(conn, "nuovo_codice_recupero")
    return code
