# Build riproducibile del pacchetto Windows

Requisiti **solo sul PC dello sviluppatore**: Windows 10/11 x64, Python 3.14 (launcher `py`), PowerShell 7.
Il PC di chi usa il programma non richiede nulla.

```
pwsh -File build\build.ps1 -Lavoro C:\gcb
```
Passi eseguiti dallo script:
1. ambiente virtuale isolato `C:\gcb\venv-build` con le versioni esatte di `requirements-lock.txt`;
2. test automatici (`pytest`, dati sintetici) — la build si interrompe se falliscono;
3. PyInstaller con `build/gestionale.spec` (cartella autosufficiente `AvviaGestionale\`, eseguibile senza console,
   icona e informazioni di versione; inclusi interfaccia, tabelle ufficiali, regole, schema XSD interno, modelli
   OCR ONNX, `tzdata`);
4. composizione di `C:\gcb\consegna\Gestionale Casa Vacanze\` con `Guida rapida.html`, `LEGGIMI.txt` e `licenze\`;
5. controlli di pulizia: nessun database, backup, log, lock o registro nel pacchetto; modelli OCR presenti;
6. ZIP `GestionaleCasaVacanze_<versione>.zip` e `SHA256.txt`.

Usare un percorso di lavoro breve: alcune librerie superano il limite di 260 caratteri dei percorsi Windows.

## Aggiornare una versione
1. Incrementare `VERSION` in `app/config.py` (e `build/versione.txt`).
2. Se cambia lo schema: aumentare `SCHEMA_VERSION` in `app/db.py` e aggiungere la migrazione in `init_db`;
   all'avvio `main.migrate_with_backup` crea `backup/pre_migrazione_v<N>_<data>.sqlite3`, migra e verifica l'integrità,
   ripristinando la copia in caso di errore.
3. Rieseguire la build e il collaudo (`docs/COLLAUDO.md`).

## Note
- L'eseguibile non è firmato digitalmente: Windows SmartScreen può chiedere conferma («Esegui comunque»).
  Per evitarlo serve un certificato di firma del codice (non incluso).
- Licenze delle librerie redistribuite: cartella `licenze\` del pacchetto (raccolte da `build/raccogli_licenze.py`).
