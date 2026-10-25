# CLAUDE.md

Gestionale locale per una casa vacanze in Italia (versione pubblica e neutra). Python 3.14 stdlib HTTP + SQLite, interfaccia JS senza build, PyInstaller.

- Vincoli fissi: un appartamento, calendario interno, **nessuna integrazione Booking/iCal/portali**, file
  Alloggiati/ROSS solo da caricare a mano, nessun esito simulato, regole fiscali solo da fonti (`docs/FONTI_NORMATIVE.md`).
- Solo dati sintetici; `GESTIONALE_DATA_DIR` punta sempre a una cartella di prova. Mai dati di ospiti in log, test o repository.
- Nessun dato di una struttura reale nel codice: i dati della struttura si inseriscono in configurazione.
- Denaro in centesimi interi; date ISO, fuso Europe/Rome; notti = arrivo incluso, partenza esclusa.
- Ogni scrittura API passa da `server._call` in una transazione `BEGIN IMMEDIATE` seguita da `consistency.reassess_all`.
  Operazioni che copiano il database (backup/ripristino) usano `use_db=False` e una connessione propria.
- Non usare `innerHTML` con dati: costruire il DOM con `h()` (CSP senza inline).
- Test: `python -m pytest tests -q` (venv in percorso breve, es. `C:\gcb\venv`, per il limite di 260 caratteri).
- Build: `pwsh -File build\build.ps1`. Aggiornare `docs/MATRICE_REQUISITI.md` e `docs/COLLAUDO.md` a ogni incremento.
