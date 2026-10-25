# HolidayGest

**Il gestionale locale per la tua casa vacanze.**

Gestionale **locale** per chi affitta **un appartamento** per vacanze in Italia (locazione turistica / casa vacanze).
Funziona su un solo PC Windows, senza cloud e senza collegamenti a Booking o ad altri portali commerciali.

- Calendario interno e prenotazioni inserite a mano (opzioni, conferme, cambio ospiti nello stesso giorno).
- Ospiti inseriti a mano o letti dalla zona MRZ del documento con **OCR locale** (nessun dato esce dal PC).
- File per **Alloggiati Web** (Polizia di Stato, TXT a 168 o 174 caratteri) e **ROSS 1000** (movimento turistico,
  XML) **da caricare a mano** sui portali, con registrazione del caricamento e dell'esito e gestione delle rettifiche.
- **Imposta di soggiorno** con regole versionate e approvate dall'utente (tariffa, limite di notti, minori,
  esenzioni), quietanze PDF, prospetti trimestrali, chiusura dei periodi.
- Incassi, caparre, cauzioni e storni con ripartizione soggiorno / imposta / cauzione.
- **Manutenzione**: lavori da fare / in corso / risolti, lavori periodici, apparecchi con garanzie e manuali,
  rubrica di ditte e tecnici, foto e PDF.
- Archivio cifrato con password e codice di recupero, backup cifrati, conservazione e anonimizzazione dei dati.

> **Avvertenza.** Il programma prepara file e calcoli, ma **non sostituisce le verifiche dell'utente**: i file vanno
> controllati e caricati sui portali ufficiali, che sono gli unici a stabilire se sono accettati. Le regole
> dell'imposta di soggiorno vanno inserite e approvate dall'utente sulla base del regolamento del proprio Comune.
> Software fornito «così com'è», senza garanzie (vedi `LICENSE`).

## Stato e limiti
- Collaudato su **Windows 10/11**. Tracciato ROSS 1000 provato sulla **Sardegna**: le altre regioni usano la
  stessa piattaforma ma possono avere regole proprie (controllare `docs/TRACCIATI.md` e le istruzioni regionali).
- Imposta di soggiorno: il motore segue lo schema dei regolamenti comunali più comuni (tariffa per persona e
  notte, limite di notti consecutive, soglia d'età dei minori, esenzioni personali). È inclusa come **esempio da
  verificare** la regola 2026 del Comune di Alghero; per un altro Comune se ne crea una nuova in *Imposta → Regole*.
- Un solo appartamento affittato per intero (le camere non sono unità prenotabili).

## Primo avvio (utente)
1. Scaricare lo ZIP della versione (sezione *Releases*), estrarlo in una cartella del proprio utente, avviare
   `AvviaGestionale.exe`. Non serve installare Python.
2. Creare la password e conservare il **codice di recupero**.
3. Completare *Impostazioni → Struttura*: nome, indirizzo, CIN, Comune e categoria per l'imposta, capienza,
   profilo Alloggiati, codice e posti ROSS 1000. La pagina *Oggi* elenca ciò che manca.
4. In *Imposta → Regole* creare o verificare la regola del proprio Comune e approvarla.

Guida: `docs/guida/Guida_rapida.html`. I dati stanno in `%LOCALAPPDATA%\HolidayGest`, separati dal
programma (oppure accanto al programma in modalità portatile, con il file `MODALITA_PORTATILE.txt`).

## Sviluppo
```
py -3.14 -m venv C:\gcb\venv
C:\gcb\venv\Scripts\pip install -r requirements-lock.txt
set GESTIONALE_DATA_DIR=C:\gcb\dati_sviluppo
C:\gcb\venv\Scripts\python AvviaGestionale.py
```
Usare **sempre** una cartella dati di sviluppo separata (`GESTIONALE_DATA_DIR`) e **solo dati inventati**.
Percorsi brevi (es. `C:\gcb`) per il limite di 260 caratteri di Windows.

- Test: `C:\gcb\venv\Scripts\python -m pytest tests -q`
- Prova completa dell'applicazione avviata (anche dell'eseguibile): `python tests/e2e_pacchetto.py http://127.0.0.1:<porta>`
- Verificatore indipendente dei file Alloggiati e ROSS (non usa il codice del programma): `build/verifica_tracciati.py`
- Simulazione di un mese intero in un archivio di prova con data spostata: `strumenti/simulazione/` (vedi i commenti)
- Pacchetto Windows: `pwsh -File build\build.ps1` e collaudo `build\collaudo_pacchetto.ps1` (vedi `docs/BUILD.md`)

## Architettura
- Python 3.14 (solo libreria standard per il server) + SQLite; interfaccia HTML/CSS/JS senza dipendenze esterne;
  pacchetto con PyInstaller.
- `app/main.py` avvio (istanza singola, porta libera su 127.0.0.1, migrazione con copia di sicurezza, finestra di
  controllo, chiusura con backup); `app/server.py` server HTTP con controlli Host/Origin/CSRF e CSP; `app/api.py`.
- `app/services/`: `bookings`, `guests`, `money`, `tax`, `exports` (Alloggiati, ROSS, lotti, rettifiche),
  `periods`, `maintenance`, `backup`, `retention`, `ocr` + `mrz`, `reports`, `tables`, `accounts`.
- Documenti: `PROJECT_SPEC.md`, `docs/FONTI_NORMATIVE.md`, `docs/TRACCIATI.md`, `docs/SICUREZZA_E_DATI.md`,
  `docs/MATRICE_REQUISITI.md`, `docs/COLLAUDO.md`.

## Privacy
Nessun dato di ospiti nel repository, nei test o nei log: i test usano solo dati inventati. Chi contribuisce non
deve mai allegare file reali (schedine, XML, documenti, database): per segnalare un problema sui file usare
`build/verifica_tracciati.py --anonimo`, che riporta solo la forma, mai i valori.

## Licenza
GPL-3.0-or-later (vedi `LICENSE`). Le librerie incluse nel pacchetto mantengono le proprie licenze (cartella
`licenze` del pacchetto).
