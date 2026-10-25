# Collaudo

Tutte le prove usano **solo dati inventati** e nessun file viene inviato ai portali: «caricamento» ed «esito» sono
registrati come li registrerebbe l'utente. Accettazione reale dei file: si vede solo al primo invio sul portale
(per Alloggiati Web usare prima la funzione «Elabora»).

## Livelli di prova
| Prova | Comando | Cosa controlla |
|---|---|---|
| Test automatici | `python -m pytest tests -q` | 132 test: calendario e conflitti, ospiti, denaro, imposta, file Alloggiati e ROSS, rettifiche, periodi, backup e ripristino, privacy, manutenzione, migrazioni dello schema |
| Mese simulato (settembre) | `tests/test_simulazione_mese.py` | routine giorno per giorno con «viaggio nel tempo»; 35 file verificati dal verificatore indipendente; imposta del trimestre = ricalcolo indipendente |
| Verificatore indipendente | `build/verifica_tracciati.py` | non importa il codice del programma: tracciato Alloggiati (posizioni, tabelle, date, finestra oggi/ieri, ordine capo/componenti) e ROSS 1000 (giornate consecutive, ordine degli elementi, arrivi/partenze, idcapo, residenza, nascita, eliminazioni, camere occupate). Con `--anonimo` analizza file reali mostrando solo la forma |
| Prova completa sull'applicazione avviata | `python tests/e2e_pacchetto.py http://127.0.0.1:<porta> [--salva DIR]` | configurazione, prenotazione, ospiti, check-in, incassi, quietanza PDF, file verificati, OCR MRZ sintetica, manutenzione, backup |
| Collaudo del pacchetto Windows | `pwsh -File build\collaudo_pacchetto.ps1 -Zip <zip> -Lavoro <cartella> -Python <python>` | 14 prove: estrazione con spazi e accenti, avvio senza Python nel PATH, DLL solo dal pacchetto, prova completa, chiusura con backup, riavvio, aggiornamento senza perdita dati, porta occupata, seconda istanza, solo 127.0.0.1, modalità portatile, pacchetto e log senza dati |
| Simulazione di un mese nel programma avviato | `python strumenti/simulazione/simula_novembre.py <cartella>` poi `avvia_simulato.py` | archivio di prova separato con data spostata: 8 soggiorni (ospiti italiani e stranieri), 8 file Alloggiati e 30 ROSS verificati, rettifiche, eliminazione ROSS, partenza anticipata, incassi e quietanze, manutenzione completa; 17 controlli |

## Riscontri con fonti esterne
- ROSS 1000: struttura confrontata con il tracciato pubblicato dalla Regione Piemonte (ver. 1.3 del 24/09/2018) e,
  solo nella forma, con un file accettato prodotto da un altro gestionale; confronto con il generatore indipendente
  open-ross (MIT): le differenze trovate erano errori di quel generatore (vedi `docs/TRACCIATI.md`).
- Alloggiati Web: forma a 168 caratteri confrontata (solo nella forma) con file reali accettati.

## Non dimostrato
- Accettazione dei file da parte dei portali (si vede al primo invio reale).
- Funzionamento su un PC senza Python installato (il collaudo toglie Python dal PATH, ma il PC di prova lo ha).
- Regole ROSS 1000 di regioni diverse dalla Sardegna; regolamenti dell'imposta diversi da quello di Alghero.
