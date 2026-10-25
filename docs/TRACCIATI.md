# Tracciati implementati

## Alloggiati Web — TXT (`app/services/exports.py`)
Fonte: Manuale Utente Alloggiati Web, par. 12 (168) e 12.1 (174). Posizioni numerate da 0 come nel manuale.

| Campo | Da | A | Lung. | 16/17/18 | 19/20 | Note implementazione |
|---|---|---|---|---|---|---|
| Tipo alloggiato | 0 | 1 | 2 | obbl. | obbl. | 16 singolo, 17 capofamiglia, 18 capogruppo, 19 familiare, 20 componente |
| Data arrivo | 2 | 11 | 10 | obbl. | obbl. | gg/mm/aaaa, arrivo **effettivo** dell'ospite |
| Giorni permanenza | 12 | 13 | 2 | obbl. | obbl. | numero allineato a sinistra e completato con spazio (es. «3 », «12»), come nelle schedine accettate di un altro gestionale (il manuale indica solo «2 caratteri»); oltre 30 (massimo del manuale) → file generato **solo con conferma esplicita**, indicando 30 |
| Cognome | 14 | 63 | 50 | obbl. | obbl. | spazi a destra; oltre 50 → **errore bloccante**, nessun troncamento |
| Nome | 64 | 93 | 30 | obbl. | obbl. | come sopra |
| Sesso | 94 | 94 | 1 | obbl. | obbl. | 1 = M, 2 = F |
| Data nascita | 95 | 104 | 10 | obbl. | obbl. | |
| Comune nascita | 105 | 113 | 9 | se Italia | se Italia | spazi se nato all'estero; validità alla data di nascita (comuni cessati) |
| Provincia nascita | 114 | 115 | 2 | se Italia | se Italia | dalla tabella Comuni |
| Stato nascita | 116 | 124 | 9 | obbl. | obbl. | tabella Stati |
| Cittadinanza | 125 | 133 | 9 | obbl. | obbl. | tabella Stati |
| Tipo documento | 134 | 138 | 5 | obbl. | spazi | tabella Documenti |
| Numero documento | 139 | 158 | 20 | obbl. | spazi | oltre 20 → errore |
| Luogo rilascio | 159 | 167 | 9 | obbl. | spazi | comune italiano o Stato |
| ID appartamento | 168 | 173 | 6 | solo profilo 174 | solo 174 | numerico, zeri a sinistra (non verificato: la struttura usa il formato 168, confermato dal suo file del 21/07/2026) |

- Fine riga CR+LF, **tranne l'ultima** riga. Codifica **UTF-8** (manuale); il contenuto è comunque solo ASCII.
- Al massimo **1000 righe** per file (manuale): oltre, il file non viene generato.
- Solo ospiti con arrivo **di oggi o di ieri** (manuale: il portale accetta solo queste date); gli altri sono esclusi con motivo e indicazione di rivolgersi alla Questura.
- Ordine: capofamiglia/capogruppo seguito subito dai propri componenti; un componente il cui capo è escluso viene escluso con motivo.
- Cognome e nome in MAIUSCOLO e **senza segni diacritici** nel file (MÜLLER → MULLER, NICOLÒ → NICOLO), con avviso nell'anteprima; la scheda dell'ospite conserva la grafia originale. Il file risulta così solo ASCII; un nome che dopo questa conversione contiene ancora caratteri non latini (greco, cirillico…) esclude l'ospite con motivo: va scritta la traslitterazione del documento.
- **Confronto del 14/10/2026** con 333 schedine Alloggiati prodotte da un altro gestionale (archivio «Storico Istat»), esaminate **solo nella forma** con uno script locale che non mostra nomi, numeri o date: righe da 168, CR+LF tranne l'ultima, solo ASCII, sesso 1/2, comune e provincia vuoti per i nati all'estero, documento a spazi per 19/20, componenti subito dopo il capo — tutto coincidente. Adeguati: giorni di permanenza scritti «3 » (non «03») e nomi senza accenti.
- Esclusioni sempre mostrate con motivo: arrivo non registrato, dati non verificati, campi mancanti, già comunicato (reinvio solo con scelta esplicita).
- Avviso di doppio invio se in Impostazioni è indicato che ROSS 1000 trasmette ad Alloggiati.
- Il file non viene conservato: si registrano lotto, data, periodo, profilo e tabelle usati, esito dei controlli, SHA-256 del file e impronte HMAC per ospite (per rilevare modifiche successive).

## ROSS 1000 Sardegna — XML (`app/services/exports.py`, `app/data/ross1000_interno.xsd`)
Fonte: GIES, «Tracciato record di integrazione dati (XML)», versione 3 del 18/03/2026.

- `<movimenti><codice/><prodotto/>` + un `<movimento>` per **ogni giornata** del periodo, in ordine di data, anche senza movimenti.
- `<struttura>`: `apertura` SI/NO (NO solo per le **chiusure ROSS** registrate, mai per i blocchi di calendario), `camereoccupate` (= unità disponibili se c'è almeno un ospite presente quella notte, altrimenti 0), `cameredisponibili` e `lettidisponibili` da configurazione; con apertura NO tutti a zero.
- `<arrivi>`: ospiti con arrivo effettivo nel giorno, nell'ordine `idswh`, `tipoalloggiato`, `idcapo`, `sesso`, `cittadinanza`, `statoresidenza`, `luogoresidenza`, `datanascita`, `statonascita`, `comunenascita` e, solo se indicati, `tipoturismo`, `mezzotrasporto`, `canaleprenotazione`. `idswh` = prefisso installazione + `G` + id interno (stabile, max 20); `idcapo` vuoto per 16/17/18; `luogoresidenza` = codice comune se residente in Italia, **vuoto** se residente all'estero; `comunenascita` vuoto se nato all'estero. `cognome`/`nome` **non inclusi** per impostazione predefinita (attivabili in Impostazioni). `titolostudio`, `professione`, `esenzioneimposta` omessi.
- Nessuna dichiarazione `<?xml ...?>` in testa (UTF-8, fine riga LF).
- **Confronto del 14/10/2026** con un file ROSS 1000 accettato dal portale e prodotto da un altro gestionale, esaminato **solo nella struttura** con uno script locale che non mostra i valori personali: stessi elementi e stesso ordine; adeguati assenza della dichiarazione XML, omissione di cognome/nome e dei campi facoltativi vuoti, `luogoresidenza` vuoto per i residenti all'estero. Il confronto non dimostra l'accettazione dei NOSTRI file: va verificata sul portale.
- **Riscontro del 25/10/2026** con il tracciato ROSS 1000 pubblicato dalla Regione Piemonte (stessa piattaforma;
  «Ver. 1.3 del 24/09/2018», https://www.regione.piemonte.it/web/media/8310/download): `idcapo` obbligatorio solo per
  19/20 e uguale all'`idswh` del capo, vuoto nell'esempio per il tipo 18; `camereoccupate` = camere effettivamente
  occupate; `luogoresidenza` obbligatorio solo per i residenti in Italia («per gli stranieri può essere valorizzato»
  con codice NUTS o località, max 30); `comunenascita` vuoto se nati all'estero; valori di tipo turismo / mezzo /
  canale in MAIUSCOLO negli esempi. Tutto coerente con il nostro file. Il documento indica `tipoturismo` e
  `mezzotrasporto` come obbligatori: in Sardegna risultano facoltativi (vedi sotto); nelle altre regioni verificare.
  Nello stesso giorno confronto con un generatore indipendente (github.com/zumatt/open-ross, MIT) sui file della
  simulazione di novembre: stessa struttura e stessi elementi; le differenze sono tutte errori di quel generatore
  rispetto al tracciato (idcapo vuoto per i componenti, camere occupate 6–7 su 1 disponibile, residenza presa dal
  luogo di nascita, nessuna partenza anticipata), vedi COLLAUDO.md.
- `<partenze>`: ospiti con partenza effettiva nel giorno, con data di arrivo.
- `<prenotazioni>` facoltativo (disattivato di default).
- `<rettifiche><eliminazione>` per ospiti eliminati dopo un invio dichiarato. L'eliminazione risulta trasmessa solo quando il file che la contiene è dichiarato caricato: se il file è scartato o rigenerato, ricompare nel file successivo.
- Esportazione parziale (solo con conferma): `camereoccupate` considera solo gli ospiti inclusi nel file, così non c'è una giornata occupata senza il relativo arrivo; quando l'ospite viene completato la giornata risulta cambiata e va ritrasmessa.
- `tipoturismo` e `mezzotrasporto`: omessi se non indicati, come nel file accettato esaminato. Un tracciato pubblico ROSS 1000 li indica come obbligatori; in Sardegna sono risultati **non obbligatori** (indicazione ricevuta da una struttura sarda il 24/10/2026, coerente con il file accettato esaminato). Nel dubbio compilarli sempre nella prenotazione: se presenti vengono inclusi.
- Controllo strutturale con **schema interno non ufficiale** + controlli semantici; impronta per giornata per segnalare giornate già dichiarate e poi cambiate («ritrasmettere il movimento del giorno»).

## Imposta di soggiorno
Regole in tabella `tax_rules` (comune, categoria, validità, tariffa, limite notti, interpretazione soglia minori, esenzioni, fonte, data verifica, stato). Seme: `app/data/regole_imposta.json`.
