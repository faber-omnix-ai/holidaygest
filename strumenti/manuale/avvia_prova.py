"""Avvia il programma (sorgenti) su un archivio di simulazione, senza fascia, per le schermate del manuale.

Uso: python avvia_prova.py <cartella_simulazione> <giorno> <porta>
Rifiuta cartelle senza il marcatore della simulazione: l'archivio vero non si tocca.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strumenti" / "simulazione"))
base, giorno, porta = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
if not (base / "SIMULAZIONE_DI_PROVA.txt").exists():
    sys.exit("Non è un archivio di simulazione.")
os.environ["GESTIONALE_DATA_DIR"] = str(base / "dati")
import orologio  # noqa: E402
orologio.installa(giorno)
from app.main import main  # noqa: E402
sys.exit(main(["--headless", "--no-browser", "--port", porta]))
