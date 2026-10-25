# Specifica di progetto (sintesi operativa)

Nato come gestionale di un appartamento ad Alghero e reso generico. Stato puntuale di ogni requisito:
`docs/MATRICE_REQUISITI.md`.

## Ambito
- Una struttura, un appartamento affittato interamente (le camere non sono unità prenotabili).
- Nessun dato precompilato: nome, indirizzo, CIN/IUN, categoria (CAV / locazione turistica), Comune dell'imposta,
  dati del gestore, capienza, codice ROSS, profilo Alloggiati si inseriscono in configurazione.
- Esclusi: Booking/iCal/channel manager/API commerciali, pagamenti online, fatturazione elettronica, accessi automatici ai portali.

## Stati indipendenti
| Ambito | Stati | Dove |
|---|---|---|
| Prenotazione/occupazione | bozza, opzione, opzione_scaduta, confermata, in_corso, conclusa, annullata, no_show | `bookings.status` |
| Preparazione appartamento (operativo) | da_preparare, in_preparazione, pronto | `bookings.prep_status` |
| Presenza del singolo ospite | prevista, presente, partita, non_arrivata | `guests.presence` |
| Verifica anagrafica | non verificata / verificata (data) + stato per campo (letto, corretto, mancante, dubbio, manuale) | `guests.verified_at`, `field_flags` |
| Pagamento soggiorno | saldo calcolato dai movimenti | `movements` + `allocations` |
| Imposta | preventivo / consuntivo / consolidato; dovuta, incassata, rimborsata, gestita da terzi, residua | `tax_*`, `allocations` |
| Alloggiati per ospite | da_preparare, generato, caricamento_dichiarato, esito_registrato, da_correggere | `guests.alloggiati_status` |
| Lotti di esportazione | generato, caricamento_dichiarato, esito_registrato, da_correggere, superato (+ «bloccato per dati mancanti» in anteprima) | `export_batches.status` |
| Rendicontazione | comunicazione trimestrale, dichiarazione annuale (da_fare/dichiarata), versamenti, chiusure di periodo | `obligations`, `remittances`, `period_closures` |
| Rettifiche | aperta, gestita | `corrections` |

## Regole chiave
- Notti: arrivo incluso, partenza esclusa; cambio nello stesso giorno ammesso se uscita + preparazione ≤ entrata, altrimenti decisione esplicita.
- Conflitti verificati lato server dentro una transazione `BEGIN IMMEDIATE` (valido con più finestre) + controllo di versione.
- Le opzioni scadute si ricalcolano all'apertura/lettura; le confermate non vengono mai liberate né marcate no-show automaticamente.
- Una prenotazione non genera comunicazioni: solo gli arrivi effettivi registrati.
- Imposta per ospite e per notte, regola scelta per data della notte; mancanza di regola o dubbio → DA VERIFICARE.
- Ogni modifica mostra prima le conseguenze (disponibilità, notti, prezzo, imposta, residui, esportazioni, periodi chiusi).
- File generato ≠ comunicazione; esiti solo dichiarati dall'operatrice; lotti non usati diventano «superati» se i dati cambiano;
  dati già comunicati modificati → segnalazione di rettifica.
- Denaro: movimenti con ripartizione; storni tracciati; idempotenza per chiave di operazione; quietanze numerate senza riuso.

## Incrementi
1. Base locale e pacchettizzazione → fatto, pacchetto provato con ambiente ridotto.
2. Calendario, prenotazioni, inserimento manuale → fatto.
3. Imposta versionata, incassi, rendiconti → fatto.
4. Esportatori Alloggiati/ROSS e stati → fatto (validazione locale; accettazione dei portali da collaudare con dati reali autorizzati).
5. OCR locale e correzione umana → fatto (MRZ; nessuna estrazione strutturata dal fronte della CIE).
6. Collaudo, backup/ripristino, pacchetto finale → vedi `docs/COLLAUDO.md`.
