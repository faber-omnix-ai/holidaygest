"""Apre il gestionale (sorgenti) su un archivio di PROVA con la data del programma spostata.

Uso:  pythonw strumenti/simulazione/avvia_simulato.py --dati C:\\gcb\\simulazione_novembre\\dati --giorno 2026-12-01
Rifiuta cartelle che non sono simulazioni (manca il file marcatore nella cartella superiore). In alto nelle pagine
compare la fascia «SIMULAZIONE». L'archivio vero (%LOCALAPPDATA%) e il programma del Desktop non vengono toccati.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI.parents[1]))
sys.path.insert(0, str(QUI))
MARCATORE = "SIMULAZIONE_DI_PROVA.txt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dati", required=True)
    ap.add_argument("--giorno", required=True)
    a, resto = ap.parse_known_args()
    dati = Path(a.dati).resolve()
    if not (dati.parent / MARCATORE).exists():
        sys.exit(f"{dati} non è un archivio di simulazione (manca {MARCATORE}).")
    os.environ["GESTIONALE_DATA_DIR"] = str(dati)
    import orologio
    orologio.installa(a.giorno)
    from app import config
    config.SIMULAZIONE = "Archivio di prova separato, solo dati inventati: nulla va ai portali."
    from app.main import main as avvia
    return avvia(resto)


if __name__ == "__main__":
    sys.exit(main())
