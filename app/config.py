"""Percorsi, versione e costanti dell'applicazione.

I dati (database, backup, log, allegati) sono SEPARATI dai binari: la cartella
programma può essere sostituita senza perdere nulla.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

APP_NAME = "HolidayGest"
APP_ID = "HolidayGest"
VERSION = "0.2.7"
TZ = ZoneInfo("Europe/Rome")
# Impostata solo dal lanciatore di prova strumenti/simulazione/avvia_simulato.py (orologio spostato): mai nella consegna
SIMULAZIONE: str | None = None

PORTABLE_FLAG = "MODALITA_PORTATILE.txt"
PREFERRED_PORT = 47615


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """Cartella che contiene l'eseguibile (o la radice dei sorgenti)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Risorse in sola lettura (static, tabelle, regole) incluse nel pacchetto."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", program_dir()))
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    return resource_dir() / "app" / "static"


def bundled_data_dir() -> Path:
    return resource_dir() / "app" / "data"


def portable_mode() -> bool:
    return (program_dir() / PORTABLE_FLAG).exists()


def data_dir() -> Path:
    """Cartella dati.

    Ordine: variabile GESTIONALE_DATA_DIR (test/sviluppo) -> modalità portatile
    (file flag accanto all'eseguibile) -> %LOCALAPPDATA%\\HolidayGest.
    %LOCALAPPDATA% non è sincronizzata da OneDrive per impostazione predefinita.
    """
    env = os.environ.get("GESTIONALE_DATA_DIR")
    if env:
        p = Path(env)
    elif portable_mode():
        p = program_dir() / "DatiGestionale"
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(base) / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    for sub in ("backup", "log", "allegati"):
        (p / sub).mkdir(exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "gestionale.sqlite3"
