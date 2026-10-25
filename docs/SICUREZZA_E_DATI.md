# Protezione dei dati, chiavi e recupero

## Cosa è cifrato e cosa no
| Dato | Dove | Protezione |
|---|---|---|
| Password di accesso | tabella `users` | solo impronta **scrypt** (N=2^15, r=8, p=1, sale casuale) |
| Chiave dati (DEK, 256 bit casuali) | tabella `keyring` | cifrata due volte con **AES-256-GCM**: con chiave derivata (scrypt) dalla password e con chiave derivata dal **codice di recupero** |
| Tipo, numero e luogo di rilascio del documento | `guests.doc_enc` | AES-256-GCM con la DEK, legato all'ospite (dati autenticati = tabella e id: non spostabile su un altro record); eliminati alla ricevuta Alloggiati |
| Ricevute allegate (Alloggiati, versamenti) | cartella `allegati/*.bin` | AES-256-GCM con la DEK |
| Backup `.gcbak` | cartella `backup/` e supporti esterni | interamente AES-256-GCM con la DEK; l'intestazione contiene la DEK cifrata con password e codice di recupero |
| Prenotazioni, nomi, date, importi, regole | database SQLite | **NON cifrati** sul disco: protetti dall'account Windows. Con dati reali **requisito operativo**: account Windows con password e cifratura del disco (BitLocker o equivalente) |
| Immagini dei documenti, miniature, testo OCR | solo memoria del processo | mai scritti su disco, esclusi da backup e log; eliminati alla chiusura della verifica o dopo 30 minuti |
| Copie in cascata (copia di sicurezza pre-ripristino, copia pre-migrazione) | `backup/` | la copia pre-migrazione è una copia SQLite non cifrata (stessi dati del database in uso, la chiave non è disponibile prima dell'accesso); viene creata e verificata solo quando cambia lo schema ed è eliminata automaticamente dopo 30 giorni; anche la copia `prima_del_ripristino_*` è non cifrata ed è eliminata automaticamente dopo 30 giorni |

La password dell'interfaccia **non è** la cifratura del database: protegge l'accesso e sblocca la DEK.
Librerie: `hashlib.scrypt` (Python), `cryptography` (AESGCM). Nessun algoritmo proprietario.

## Recupero autorizzato su un nuovo PC
1. Sul vecchio PC: *Impostazioni → Backup e ripristino → Crea backup* e *Copia su chiavetta*.
2. Sul nuovo PC (anche altro utente Windows): avviare il programma, scegliere *Ripristina da un backup*, indicare il file e la **password** dell'archivio di origine **oppure il codice di recupero**.
3. Il programma verifica integrità (GCM + SHA-256 del database + `PRAGMA integrity_check`) e compatibilità di versione **prima** di sostituire qualsiasi cosa; un archivio esistente viene prima copiato in `backup/prima_del_ripristino_<data>`.
4. I nuovi file vengono preparati accanto a quelli attuali; poi si scambiano gli allegati e, come ultimo passo atomico, il database. Se uno scambio fallisce, gli allegati originali tornano al loro posto e il database resta quello di prima.
5. Dopo il ripristino vengono riapplicate le cancellazioni registrate (`registro_eliminazioni.json`, solo identificativi) e le scadenze degli allegati. Il registro è **incluso nei backup** e al ripristino viene unito a quello del PC. Limite: ripristinando su un PC nuovo un backup **più vecchio** di altri, le cancellazioni fatte dopo quel backup sul vecchio PC non sono note; i documenti di ospiti con ricevuta acquisita vengono comunque eliminati di nuovo.

Se password **e** codice di recupero sono persi, i dati cifrati e i backup non sono recuperabili da nessuno. Non esistono password universali o accessi nascosti.

## Rete e interfaccia
Tentativi di accesso falliti: ritardo crescente, azzerato dopo un accesso riuscito. Server solo su `127.0.0.1`; controllo `Host` (anti DNS-rebinding), `Origin` e token CSRF sulle scritture, cookie `HttpOnly; SameSite=Strict`, CSP `default-src 'self'` senza script o stili inline, nessuna risorsa remota, nessuna telemetria, nessuna verifica di aggiornamenti in rete.

## Log
`log/gestionale.log`: avvio/chiusura, errori con tipo e posizione nel codice. Mai URL con parametri, payload, testo OCR, nomi o numeri di documento. Il registro `audit` nel database contiene solo azioni e identificativi interni (verificato da test).

## Conservazione
- Documenti: cancellati all'acquisizione della ricevuta Alloggiati (Garante, 29/04/2026). Documenti di ospiti partiti senza esito vengono **segnalati**, non cancellati in silenzio.
- Ricevute Alloggiati: 5 anni, poi eliminazione automatica.
- Anagrafiche/prenotazioni: anonimizzazione proposta dopo N anni (predefinito 5, modificabile: conformità da verificare per la propria attività, non verificata da un professionista), solo su conferma.
- Il programma non cancella mai file fuori dalla propria cartella dati (telefono, Download, chiavette).
