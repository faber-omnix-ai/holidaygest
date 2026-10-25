"""Password, chiavi e cifratura.

Algoritmi standard, nessuna crittografia inventata:
- password: scrypt (hashlib, stdlib) con sale casuale;
- chiave dati (DEK) casuale 256 bit, cifrata ("wrapped") con AES-256-GCM sotto due
  chiavi derivate con scrypt: dalla password e dal codice di recupero;
- campi documentali e allegati: AES-256-GCM (libreria `cryptography`).
La DEK esiste in chiaro solo in memoria dopo l'accesso.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
_MAXMEM = 128 * 1024 * 1024
_B32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # senza 0/O/1/I


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _scrypt(secret: str, salt: bytes, n: int = SCRYPT_N) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=n, r=SCRYPT_R, p=SCRYPT_P,
                          maxmem=_MAXMEM, dklen=32)


# ---------- password ----------
def check_password_policy(pw: str) -> str | None:
    if len(pw) < 10:
        return "La password deve avere almeno 10 caratteri."
    if pw.strip() != pw:
        return "La password non può iniziare o finire con spazi."
    return None


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${SCRYPT_N}${_b64(salt)}${_b64(_scrypt(pw, salt))}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        return hmac.compare_digest(_scrypt(pw, _unb64(salt), int(n)), _unb64(h))
    except (ValueError, TypeError):
        return False


# ---------- chiavi ----------
def new_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def new_recovery_code() -> str:
    raw = "".join(secrets.choice(_B32) for _ in range(24))
    return "-".join(raw[i:i + 4] for i in range(0, 24, 4))


def normalize_recovery(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def wrap_key(dek: bytes, secret: str) -> str:
    salt, nonce = os.urandom(16), os.urandom(12)
    kek = _scrypt(secret, salt)
    ct = AESGCM(kek).encrypt(nonce, dek, b"gestionale-dek-v1")
    return json.dumps({"v": 1, "n": SCRYPT_N, "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct)})


def unwrap_key(wrapped: str, secret: str) -> bytes | None:
    try:
        w = json.loads(wrapped)
        kek = _scrypt(secret, _unb64(w["salt"]), int(w["n"]))
        return AESGCM(kek).decrypt(_unb64(w["nonce"]), _unb64(w["ct"]), b"gestionale-dek-v1")
    except Exception:
        return None


# ---------- cifratura dati ----------
def encrypt_bytes(dek: bytes, data: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return b"GCB1" + nonce + AESGCM(dek).encrypt(nonce, data, aad)


def decrypt_bytes(dek: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    if blob[:4] != b"GCB1":
        raise ValueError("Formato cifrato non riconosciuto")
    return AESGCM(dek).decrypt(blob[4:16], blob[16:], aad)


def encrypt_json(dek: bytes, obj, context: str) -> str:
    """v2: il dato cifrato è legato al proprio record (AAD = contesto), così non può essere spostato su un altro."""
    return "v2:" + _b64(encrypt_bytes(dek, json.dumps(obj, ensure_ascii=False).encode("utf-8"), context.encode()))


def decrypt_json(dek: bytes, s: str | None, context: str):
    if not s:
        return None
    aad = b"field" if s.startswith("v1:") else context.encode()  # v1: formato precedente, AAD fissa
    return json.loads(decrypt_bytes(dek, _unb64(s[3:]), aad).decode("utf-8"))


# ---------- sessioni ----------
class Sessions:
    """Sessioni in memoria (un solo utente locale). Scadenza per inattività."""

    IDLE_SECONDS = 2 * 3600

    def __init__(self) -> None:
        self._s: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.failed: list[float] = []

    def create(self, user_id: int) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._lock:
            self._s[token] = {"user_id": user_id, "csrf": csrf, "last": time.time()}
        return token, csrf

    def get(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._lock:
            s = self._s.get(token)
            if not s:
                return None
            if time.time() - s["last"] > self.IDLE_SECONDS:
                del self._s[token]
                return None
            s["last"] = time.time()
            return s

    def drop(self, token: str | None) -> None:
        with self._lock:
            self._s.pop(token or "", None)

    def count(self) -> int:
        with self._lock:
            return len(self._s)

    def clear(self) -> None:
        with self._lock:
            self._s.clear()

    def add_failed(self) -> None:
        with self._lock:
            self.failed.append(time.time())

    def reset_failed(self) -> None:
        with self._lock:
            self.failed.clear()

    def throttle_seconds(self) -> float:
        """Ritardo crescente dopo tentativi falliti recenti (anti forza bruta locale)."""
        now = time.time()
        with self._lock:
            self.failed = [t for t in self.failed if now - t < 900]
            n = len(self.failed)
        return min(30.0, 0.5 * (2 ** max(0, n - 3))) if n > 3 else 0.0
