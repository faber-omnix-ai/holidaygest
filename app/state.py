"""Stato di processo: chiave dati in memoria, sessioni, caricamenti OCR temporanei (solo RAM)."""
from __future__ import annotations

import threading
import time

from .db import AppError
from .security import Sessions


class AppState:
    def __init__(self) -> None:
        self.dek: bytes | None = None
        self.sessions = Sessions()
        self.uploads: dict[str, dict] = {}   # documenti caricati: solo in memoria, mai su disco
        self.lock = threading.RLock()
        self.port: int | None = None
        self.shutdown_cb = None

    def require_dek(self) -> bytes:
        if self.dek is None:
            raise AppError("Sessione bloccata: effettua di nuovo l'accesso.", 401)
        return self.dek

    def lock_app(self) -> None:
        with self.lock:
            self.dek = None
            self.sessions.clear()
            self.purge_uploads(all_=True)

    def purge_uploads(self, all_: bool = False, max_age: int = 1800) -> int:
        """Elimina dalla memoria immagini, miniature e testo OCR temporanei."""
        now = time.time()
        with self.lock:
            dead = [k for k, v in self.uploads.items() if all_ or now - v["created"] > max_age]
            for k in dead:
                v = self.uploads.pop(k)
                v.clear()
            return len(dead)


STATE = AppState()
