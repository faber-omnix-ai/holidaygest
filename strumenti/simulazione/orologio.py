"""Orologio spostato per le simulazioni di prova (SOLO archivi di prova, mai la consegna).

Sostituisce «oggi» e «adesso» in tutti i moduli app.* che li hanno importati da app.db / app.util, come la fixture
`orologio` di tests/test_simulazione_mese.py. L'ora del giorno resta quella reale: cambia solo la data.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATO = {"giorno": None}   # data simulata (ISO); None = data reale


def _adesso() -> datetime:
    from app import config
    reale = datetime.now(config.TZ)
    if not STATO["giorno"]:
        return reale
    g = date.fromisoformat(STATO["giorno"])
    return reale + timedelta(days=(g - reale.date()).days)


def installa(giorno: str) -> None:
    """Carica tutti i moduli del programma e ne sostituisce le funzioni dell'orologio."""
    import app
    from app import db, util
    for m in pkgutil.walk_packages(app.__path__, "app."):
        importlib.import_module(m.name)
    STATO["giorno"] = giorno
    nuovi = {db.now_iso: lambda: _adesso().isoformat(timespec="seconds"),
             db.today_iso: lambda: _adesso().date().isoformat(),
             util.now_local: _adesso}
    for name, mod in list(sys.modules.items()):
        if name != "app" and not name.startswith("app."):
            continue
        for attr, val in list(vars(mod).items()):
            for orig, nuovo in nuovi.items():
                if val is orig:
                    setattr(mod, attr, nuovo)


def imposta(giorno: str) -> None:
    STATO["giorno"] = giorno
