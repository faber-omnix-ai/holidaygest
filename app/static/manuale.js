/* Manuale di istruzioni consultabile nell'app, anche prima dell'accesso. Solo testo fisso: nessun dato di ospiti.
   Nei testi: **grassetto**; tra «» solo i nomi scritti davvero sui pulsanti e nelle schermate (li controlla tests/test_manuale.py). */
"use strict";
const MAN_P = x => ({ t: "p", x });
const MAN_PASSI = v => ({ t: "passi", v });
const MAN_LISTA = v => ({ t: "lista", v });
const MAN_NOTA = x => ({ t: "nota", x });
const MAN_ATT = x => ({ t: "att", x });
const MAN_VAI = (href, x) => ({ t: "vai", href, x });
const MAN_IMG = (src, alt) => ({ t: "img", src, alt });
const MAN_FAQ = (q, a) => ({ t: "faq", q, a });
const MAN_VOCE = (q, a) => ({ t: "voce", q, a });

function manCapitoli() {
  return [
    { gruppo: "Per iniziare", id: "inizia", titolo: "Da dove comincio", breve: "Che cosa fa il programma, in due minuti.", blocchi: [
      MAN_P("Questo programma tiene in ordine la casa vacanze: prenotazioni, ospiti, soldi, imposta di soggiorno, comunicazioni obbligatorie e manutenzione. **Non serve conoscere la materia:** il manuale spiega ogni passaggio con parole semplici."),
      MAN_LISTA([
        "**Funziona solo su questo computer.** I dati non vanno su Internet.",
        "**Non è collegato a Booking o Airbnb.** Le prenotazioni si scrivono qui a mano, e il calendario non aggiorna gli annunci.",
        "**Prepara i file, ma non li invia.** Alloggiati Web e ROSS 1000 si caricano a mano sui portali.",
        "**Ti ricorda le cose da fare,** ma solo quando il programma è aperto: a computer spento non arrivano avvisi.",
      ]),
      MAN_P("**Una prenotazione, dall'inizio alla fine:**"),
      MAN_PASSI([
        "Qualcuno prenota: inserisci la prenotazione dal calendario.",
        "Incassi l'acconto: lo registri in «Pagamenti».",
        "Arrivano gli ospiti: inserisci i loro dati e premi «Registra arrivo (check-in)».",
        "Entro i termini: prepari i file per Alloggiati Web e ROSS 1000 e li carichi sui portali.",
        "Gli ospiti pagano e partono: registri incasso, imposta e «Registra partenza (check-out)».",
        "Fine trimestre: controlli i conti e comunichi l'imposta al Comune.",
      ]),
      MAN_NOTA("Nelle pagine del programma trovi il collegamento «Come funziona»: apre il capitolo giusto di questo manuale. La parola che non conosci è spiegata nel glossario."),
    ] },
    { gruppo: "Per iniziare", id: "avvio", titolo: "Aprire e chiudere il programma", breve: "Avvio, accesso e chiusura corretta.", blocchi: [
      MAN_PASSI([
        "**Solo la prima volta:** copia la cartella del programma sul computer, per esempio in Documenti. Non usarla direttamente dalla chiavetta.",
        "Fai doppio clic su **AvviaGestionale.exe**. Si apre una piccola finestra di controllo e il programma nel browser.",
        "Scrivi la password e premi «Entra».",
        "Quando hai finito, chiudi con «Chiudi il gestionale»: il programma fa da solo un backup.",
      ]),
      MAN_NOTA("Se il browser non si apre, premi «Apri il gestionale» nella finestra di controllo. Il programma funziona anche senza Internet: Internet serve solo per usare i portali."),
      MAN_ATT("Alla prima apertura Windows può mostrare un avviso, perché il programma non è firmato: scegli **Ulteriori informazioni** e poi **Esegui comunque**."),
    ] },
    { gruppo: "Per iniziare", id: "struttura", titolo: MAN_ED.struttura.titolo, breve: MAN_ED.struttura.breve, blocchi: MAN_ED.struttura.blocchi },

    { gruppo: "Ogni giorno", id: "oggi", titolo: "La pagina Oggi", breve: "Il riassunto di quello che c'è da fare.", blocchi: [
      MAN_P("È la prima pagina da guardare: risponde alle domande della giornata. Ogni avviso è un collegamento: **fai clic e arrivi alla pratica da sistemare.**"),
      MAN_IMG("oggi", "La pagina Oggi con arrivi, partenze e cose da fare"),
      MAN_LISTA([
        "«Chi arriva» e «Chi parte»: gli ospiti dei prossimi giorni.",
        "«L'appartamento è pronto?»: i cambi tra un ospite e l'altro e il tempo per le pulizie.",
        "«Quali dati mancano»: ospiti incompleti e correzioni da fare.",
        "«Comunicazioni da gestire»: i file da caricare e le scadenze. La scritta «Termine superato» significa che sei in ritardo.",
        "«Manutenzione»: lavori urgenti, scaduti o in scadenza e garanzie che stanno finendo.",
        "«Quanto devo incassare»: i saldi aperti e l'imposta da riscuotere.",
        "«Scadenze e backup»: gli appuntamenti con il Comune e l'ultimo backup riuscito.",
        "«Prossima disponibilità»: i prossimi periodi liberi.",
      ]),
      MAN_VAI("#/oggi", "Apri la pagina Oggi"),
    ] },
    { gruppo: "Ogni giorno", id: "calendario", titolo: "Il calendario", breve: "Vedere il mese, prenotare, bloccare i giorni.", blocchi: [
      MAN_IMG("calendario", "Il calendario del mese con le prenotazioni"),
      MAN_P("**Che cosa significano le scritte:** «Disponibile» è libero; «In opzione» è tenuto da parte fino a una scadenza; «Prenotato» è confermato; «Soggiorno in corso» significa ospiti in casa; «Concluso» è finito; «Bloccato» è chiuso per manutenzione o uso personale. ▶ indica un arrivo, ◀ una partenza."),
      MAN_P("**Prenotare:** fai clic sul giorno di arrivo e poi su quello di partenza. Si apre la finestra della prenotazione."),
      MAN_P("**Spostare una prenotazione:** trascinala su un altro giorno. Prima di salvare vedi che cosa cambia e premi «Conferma spostamento». Con il tasto Esc annulli."),
      MAN_P("**Chiudere dei giorni:** premi «Blocca periodo», scegli le date e il motivo. Per riaprirli, fai clic sul periodo bloccato e premi «Rimuovi blocco»."),
      MAN_NOTA("Un blocco non crea ospiti né comunicazioni, e non vale come chiusura per ROSS 1000: quella si segna a parte."),
      MAN_VAI("#/calendario", "Apri il calendario"),
    ] },
    { gruppo: "Ogni giorno", id: "prenotazione", titolo: "Le prenotazioni", breve: "Inserire, confermare, modificare, annullare.", blocchi: [
      MAN_PASSI([
        "Premi «Nuova prenotazione», oppure fai clic su due giorni nel calendario.",
        "Scrivi chi prenota in «Referente (chi prenota)», un contatto, le date e le «Persone previste».",
        "Scegli lo stato: «Confermata», «Opzione (con scadenza)» se aspetti una risposta, oppure «Bozza (non occupa il calendario)».",
        "Indica il prezzo e l'eventuale «Cauzione richiesta». Controlla la scritta «Periodo disponibile nel calendario interno.».",
        "Premi «Salva prenotazione».",
      ]),
      MAN_IMG("prenotazione", "La finestra della nuova prenotazione"),
      MAN_NOTA("Per prenotare **non servono i documenti**: li chiedi all'arrivo. Chi prenota non è per forza un ospite: gli ospiti si inseriscono a parte."),
      MAN_P("**La scheda della prenotazione** ha cinque parti: «Prenotazione», «Ospiti», «Pagamenti», «Imposta» e «Adempimenti», cioè tutto quello che resta da completare."),
      MAN_LISTA([
        "**Modificare:** cambia i dati in «Prenotazione» e premi «Verifica e salva modifiche». Vedi le conseguenze e premi «Conferma modifica».",
        "**Extra e sconti:** usa «Aggiungi extra o sconto». Sono separati dall'imposta.",
        "**Confermare un'opzione:** premi «Conferma». Alla scadenza l'opzione decade e libera il calendario.",
        "**Annullare:** premi «Annulla prenotazione». Acconti e quietanze restano registrati.",
        "**Non si sono presentati:** premi «Segna no-show». Il programma non lo decide mai da solo.",
      ]),
      MAN_VAI("#/prenotazioni", "Apri le prenotazioni"),
    ] },
    { gruppo: "Ogni giorno", id: "ospiti", titolo: "Gli ospiti e i documenti", breve: "Inserire i dati a mano o da una foto del documento.", blocchi: [
      MAN_P("Apri la prenotazione e vai su «Ospiti». Ci sono due modi per inserire una persona:"),
      MAN_P("**Dalla foto del documento**"),
      MAN_PASSI([
        "Premi «Aggiungi ospite da documento».",
        "Scegli la foto o il PDF del documento. Se serve puoi ruotarla o ingrandirla.",
        "Premi «Leggi i dati dal documento».",
        "Controlla **ogni campo** sul documento vero. «letto» è affidabile, «dubbio» è da controllare, «mancante» va scritto da te.",
        "Premi «Usa questi dati e completa la scheda» e completa ciò che manca.",
      ]),
      MAN_IMG("documento", "La lettura del documento con i campi proposti"),
      MAN_P("**A mano:** premi «Aggiungi ospite (inserimento manuale)». Funziona sempre, anche senza foto."),
      MAN_LISTA([
        "**«Tipologia di alloggiato»:** una persona sola è «Ospite singolo». Una famiglia ha un «Capofamiglia» e i «Familiare»; un gruppo ha un «Capogruppo» e i «Componente gruppo».",
        "**Il documento** serve solo per ospite singolo, capofamiglia e capogruppo. Gli altri vanno collegati al loro capofamiglia o capogruppo.",
        "**Comuni e Stati:** scrivi le prime lettere e scegli dall'elenco ufficiale.",
        "**Alla fine** spunta «Ho verificato questi dati confrontandoli con il documento originale». **Senza questa spunta l'ospite non entra nei file.**",
      ]),
      MAN_ATT("Le immagini restano in memoria solo durante la lettura e poi vengono cancellate. **Le foto sul telefono o nella cartella Download devi cancellarle tu.**"),
      MAN_VAI("#/documenti", "Apri la verifica documenti"),
    ] },
    { gruppo: "Ogni giorno", id: "arrivo", titolo: "Arrivo e partenza", breve: "Registrare chi è arrivato davvero e chi è partito.", blocchi: [
      MAN_P("Una prenotazione futura non è un ospite arrivato: **l'arrivo va registrato**, perché da lì partono i termini delle comunicazioni e il calcolo dell'imposta."),
      MAN_PASSI([
        "Nella prenotazione premi «Registra arrivo (check-in)». Gli ospiti devono essere già inseriti.",
        "In «Chi è arrivato?» spunta solo le persone arrivate davvero, con data e ora.",
        "Premi «Registra arrivi».",
        "Alla fine del soggiorno premi «Registra partenza (check-out)». Vedi il riepilogo di soldi, imposta e comunicazioni aperte.",
        "Conferma con «Registra partenza». Puoi farlo anche con un saldo aperto: resta visibile in «Oggi».",
      ]),
      MAN_LISTA([
        "**Un ospite parte prima degli altri:** nella tabella «Ospiti» premi «Partenza» sulla sua riga.",
        "**Un ospite non è venuto:** premi «Non arrivato». Non verrà comunicato né conteggiato per l'imposta.",
      ]),
    ] },

    { gruppo: "Soldi e obblighi", id: "pagamenti", titolo: "Incassi e cauzioni", breve: "Registrare soldi ricevuti e restituiti.", blocchi: [
      MAN_PASSI([
        "Nella prenotazione apri «Pagamenti» e premi «Registra incasso».",
        "Scrivi data, «Importo totale» e «Modalità».",
        "Dividi l'importo in **«Soggiorno ed extra», «Imposta di soggiorno» e «Cauzione»**. La somma deve dare il totale.",
        "Premi «Registra».",
      ]),
      MAN_NOTA("**Esempio:** incassi 612 €. Scrivi 500 in «Soggiorno ed extra», 12 in «Imposta di soggiorno» e 100 in «Cauzione»."),
      MAN_IMG("pagamenti", "La scheda Pagamenti con saldi e movimenti"),
      MAN_LISTA([
        "**Restituire la cauzione o rimborsare:** «Registra restituzione o rimborso».",
        "**Hai sbagliato un importo:** premi «Storna» sulla riga e registra quello giusto. L'errore resta scritto, per tenere i conti in ordine.",
        "**L'imposta l'ha riscossa un portale o un altro soggetto:** «Imposta gestita da terzi», con il riferimento del documento che lo dimostra.",
      ]),
    ] },
    { gruppo: "Soldi e obblighi", id: "imposta", titolo: "Imposta di soggiorno", breve: "Calcolo, quietanza e regole del Comune.", blocchi: [
      MAN_P("L'imposta è **dei soldi del Comune, non tuoi**: il programma la tiene separata dal resto. Il calcolo è nella scheda «Imposta» della prenotazione, ospite per ospite e notte per notte, con il motivo di ogni esclusione."),
      MAN_IMG("imposta", "Il calcolo dell'imposta per ogni ospite"),
      MAN_LISTA([
        "**Prima dell'arrivo** è una stima. **Dopo l'arrivo** il calcolo usa i giorni effettivi.",
        "**DA VERIFICARE** significa che manca una regola approvata o c'è un dubbio, per esempio una data di nascita. Non viene mai trasformato in zero: va chiarito.",
        "**Esenzioni:** nella scheda dell'ospite scegli la «Posizione per l'imposta di soggiorno» e registra solo che hai ricevuto la dichiarazione, senza diagnosi.",
      ]),
      MAN_P("**A soggiorno finito:**"),
      MAN_PASSI([
        "Premi «Consolida conteggio»: fissa l'importo definitivo.",
        "Premi «Emetti quietanza dell'imposta incassata» e, se serve, apri il «PDF» da stampare.",
        "Se l'ospite rifiuta di pagare, usa «Annota rifiuto di pagamento»: l'imposta resta dovuta.",
      ]),
      MAN_P("**Le regole dell'imposta**"),
      ...MAN_ED.regola_imposta,
      MAN_VAI("#/imposta?tab=regole", "Apri le regole dell'imposta"),
    ] },
    { gruppo: "Soldi e obblighi", id: "comunicazioni", titolo: "Alloggiati Web e ROSS 1000", breve: "Le comunicazioni obbligatorie, passo per passo.", blocchi: [
      MAN_P("**Sono due obblighi diversi:** Alloggiati Web comunica alla Polizia di Stato chi alloggia; ROSS 1000 comunica i dati statistici sul turismo. Uno non sostituisce l'altro."),
      MAN_NOTA("**Alloggiati Web:** entro 24 ore dall'arrivo, ed entro 6 ore se il soggiorno non supera le 24 ore. La pagina «Oggi» mostra il termine di ogni ospite."),
      MAN_NOTA(MAN_ED.ross_regola),
      MAN_IMG("esportazioni", "La pagina Esportazioni ed esiti"),
      MAN_P("**Alloggiati Web**"),
      MAN_PASSI([
        "Apri «Esportazioni ed esiti». In «Alloggiati Web (TXT)» scegli le date.",
        "Premi «Anteprima: chi è incluso e chi no». Se qualcuno è escluso, leggi il motivo e fai clic sul nome per correggerlo.",
        "Premi «Genera file TXT»: il file viene scaricato sul computer.",
        "Accedi al portale Alloggiati Web, carica il file e usa prima **Elabora** e poi **Invia**.",
        "Torna nel programma. In «Lotti generati» premi «Dichiara caricato» e poi «Registra esito», scrivendo quello che dice il portale.",
        "Scarica dal portale la ricevuta e premi «Allega ricevuta ufficiale»: viene conservata 5 anni e i dati dei documenti vengono cancellati.",
      ]),
      MAN_P("**ROSS 1000**"),
      MAN_PASSI([
        "In «ROSS 1000 Sardegna (XML)» scegli le giornate e premi «Anteprima movimenti».",
        "Premi «Genera file XML», caricalo sul portale ROSS 1000.",
        "Torna nel programma e premi «Dichiara caricato» e «Registra esito».",
      ]),
      MAN_ATT("**Scaricare il file non è una comunicazione:** l'obbligo è assolto solo quando il portale lo accetta."),
      MAN_LISTA([
        "**Non comunicare due volte le stesse cose:** per gli stessi giorni usa il file del programma **oppure** il portale, mai entrambi.",
        "**Chiusure lunghe, per esempio l'inverno:** vai in «Impostazioni e backup», scheda «Tabelle, chiusure ROSS, informazioni», e premi «Registra chiusura».",
        "**Rettifiche:** se cambi dati già comunicati, compare una segnalazione. Il programma non aggiorna i portali: correggi sul portale e poi premi «Segna come gestita».",
      ]),
      MAN_VAI("#/esportazioni", "Apri Esportazioni ed esiti"),
    ] },
    { gruppo: "Soldi e obblighi", id: "trimestre", titolo: "A fine trimestre", breve: "Controllare i conti e comunicare al Comune.", blocchi: [
      MAN_P(MAN_ED.scadenza_trimestre),
      MAN_PASSI([
        "Apri «Imposta e rendiconti» e nella scheda «Controlla periodo» premi il pulsante «Controlla periodo».",
        "Leggi le «Anomalie»: ogni voce apre la pratica da sistemare.",
        "Nella scheda «Prospetto trimestrale» scegli anno e trimestre e premi «Prepara prospetto».",
        "Copia i dati **a mano** sul portale del Comune e fai il versamento.",
        "Nella scheda «Versamenti e adempimenti» premi «Registra versamento» e aggiorna lo stato con «Salva stato».",
        "Torna in «Controlla periodo» e premi «Chiudi periodo»: viene salvato un riepilogo numerato.",
      ]),
      MAN_IMG("trimestre", "Il prospetto trimestrale"),
      MAN_NOTA("Il prospetto non è un file da caricare e non prova il pagamento: conserva la ricevuta del versamento."),
      MAN_VAI("#/imposta?tab=staytour", "Apri il prospetto trimestrale"),
    ] },

    { gruppo: "La casa e i dati", id: "manutenzione", titolo: "Manutenzione", breve: "Lavori, apparecchi e ditte.", blocchi: [
      MAN_IMG("manutenzione", "L'elenco dei lavori di manutenzione"),
      MAN_P("**Un lavoro da fare**"),
      MAN_PASSI([
        "Apri «Manutenzione» e premi «Nuovo lavoro».",
        "Scrivi «Che cosa c'è da fare», la «Priorità» e «Da fare entro». Puoi aggiungere la foto del guasto.",
        "Scegli la ditta oppure scrivi il nome in «…oppure nuova ditta»: entra da sola nella rubrica.",
        "Nella scheda del lavoro annota i passi nel «Diario dell'avanzamento», per esempio che hai chiamato il tecnico.",
        "Quando è finito, segna il lavoro come risolto e indica il «Costo finale».",
      ]),
      MAN_LISTA([
        "**Lavori che si ripetono:** in «Si ripete» scegli ogni quanto, per esempio la pulizia dei filtri ogni 6 mesi. Quando lo risolvi, si apre da solo il prossimo.",
        "**«Apparecchi della casa»:** marca, modello, «Garanzia fino al», manuale e scontrino. In «Oggi» compare un avviso 60 giorni prima della fine della garanzia.",
        "**«Ditte e tecnici»:** contatti, lavori fatti e spesa di ogni ditta.",
      ]),
      MAN_NOTA("La manutenzione non blocca il calendario: per non affittare in quei giorni usa «Blocca periodo». I suoi costi non entrano nei conti dei soggiorni."),
      MAN_VAI("#/manutenzione", "Apri la manutenzione"),
    ] },
    { gruppo: "La casa e i dati", id: "backup", titolo: "Backup e sicurezza", breve: "Non perdere i dati e cambiare computer.", blocchi: [
      MAN_P("Il **backup** è una copia protetta di tutti i dati. Il programma lo fa da solo alla chiusura, ma **se il computer si rompe quella copia si perde con lui**: tienine una anche su una chiavetta."),
      MAN_PASSI([
        "Vai in «Impostazioni e backup», scheda «Backup e ripristino».",
        "Premi «Crea backup ora».",
        "Inserisci la chiavetta, scegli la «Destinazione» e premi «Copia ora».",
      ]),
      MAN_IMG("backup", "La scheda Backup e ripristino"),
      MAN_ATT("**Password e codice di recupero:** per aprire un backup serve uno dei due. **Se li perdi entrambi, nessuno può recuperare i dati.** Tieni il codice scritto su carta, lontano dal computer."),
      MAN_LISTA([
        "**Cambiare la password:** scheda «Accesso e protezione», pulsante «Cambia password».",
        "**Controllare un backup:** «Verifica senza ripristinare» non modifica nulla.",
        "**Tornare a un backup:** «Ripristina» sostituisce l'archivio, dopo averne salvato una copia.",
        "**Cambiare computer:** segui i passi in «Trasferisci su un altro PC». Dopo usa un solo computer: due copie non si uniscono.",
        "**Proteggi anche Windows con una password:** nomi e importi non sono cifrati sul disco.",
      ]),
      MAN_VAI("#/impostazioni?tab=backup", "Apri Backup e ripristino"),
    ] },

    { gruppo: "Serve aiuto?", id: "problemi", titolo: "Se qualcosa non va", breve: "Le domande più comuni.", blocchi: [
      MAN_FAQ("Ho dimenticato la password.", "Nella pagina di accesso premi «Ho dimenticato la password», scrivi il codice di recupero e la nuova password. Il programma ti mostra un nuovo codice: conservalo."),
      MAN_FAQ("Il programma dice che non risponde.", "La finestra di controllo potrebbe essere chiusa. Riavvia AvviaGestionale.exe: i dati non si perdono."),
      MAN_FAQ("Un ospite non entra nel file.", "Nell'anteprima leggi il motivo sotto «Esclusi». Di solito mancano dei dati, manca la spunta di verifica o l'arrivo non è registrato. Fai clic sul nome per correggere."),
      MAN_FAQ("L'imposta dice DA VERIFICARE.", "Apri la scheda «Imposta» e leggi il motivo: spesso manca la data di nascita o una regola approvata per quel periodo."),
      MAN_FAQ("Ho sbagliato un incasso.", "Non si cancella: premi «Storna» e registra il movimento giusto."),
      MAN_FAQ("Ho corretto un ospite già comunicato.", "Compare una rettifica in «Segnalazioni di rettifica». Correggi anche sul portale e poi premi «Segna come gestita»."),
      MAN_FAQ("Il portale ha scartato il file.", "Registra l'esito con «Registra esito», correggi i dati e genera un nuovo file. Fa fede solo quello che dice il portale."),
      MAN_FAQ("Non posso prenotare quelle date.", "Il periodo è occupato o bloccato. Se un ospite parte e un altro arriva lo stesso giorno con poco tempo, il programma chiede di spuntare «Accetto il cambio ospiti con tempi ridotti»."),
      MAN_FAQ("Non vedo le prenotazioni di Booking.", "È normale: il programma non è collegato ai portali. Inseriscile a mano."),
      MAN_NOTA("Il programma aiuta, ma **non sostituisce i controlli sui portali ufficiali**. Per dubbi di legge o fiscali chiedi al Comune o al tuo consulente."),
    ] },
    { gruppo: "Serve aiuto?", id: "glossario", titolo: "Glossario", breve: "Le parole difficili spiegate semplici.", blocchi: [
      MAN_VOCE("Alloggiati Web", "Il portale della Polizia di Stato dove si comunicano le persone alloggiate."),
      MAN_VOCE("ROSS 1000", "Il portale per comunicare arrivi e partenze a fini statistici sul turismo."),
      MAN_VOCE("CIN", "Codice Identificativo Nazionale della struttura."),
      MAN_VOCE("IUN", "Codice regionale della struttura in Sardegna."),
      MAN_VOCE("Imposta di soggiorno", "Somma per persona e notte chiesta dal Comune: la incassi e la versi al Comune."),
      MAN_VOCE("Quietanza", "Ricevuta che dimostra che l'ospite ha pagato l'imposta."),
      MAN_VOCE("Referente", "Chi prenota. Può anche non soggiornare."),
      MAN_VOCE("Capofamiglia / Capogruppo", "La persona che presenta il documento per la famiglia o per il gruppo."),
      MAN_VOCE("Opzione", "Date tenute da parte fino a una scadenza, senza conferma definitiva."),
      MAN_VOCE("Bozza", "Prenotazione appuntata che non occupa il calendario."),
      MAN_VOCE("No-show", "Ospite con prenotazione confermata che non si presenta."),
      MAN_VOCE("Check-in / Check-out", "L'arrivo e la partenza degli ospiti."),
      MAN_VOCE("Caparra / Acconto", "Parte del prezzo pagata prima del soggiorno."),
      MAN_VOCE("Cauzione", "Somma a garanzia di eventuali danni, da restituire alla fine."),
      MAN_VOCE("Storno", "Movimento che annulla un altro movimento sbagliato, lasciandone traccia."),
      MAN_VOCE("Lotto", "Un file generato per un portale, con il suo stato."),
      MAN_VOCE("Rettifica", "Correzione di dati già comunicati o definitivi."),
      MAN_VOCE("Consolidare", "Fissare come definitivo il conteggio dell'imposta di un soggiorno."),
      MAN_VOCE("Giornata a zero", "Giorno senza arrivi né partenze, che ROSS 1000 chiede comunque di comunicare."),
      MAN_VOCE("OCR", "La lettura automatica del testo di una foto. Qui avviene sul tuo computer."),
      MAN_VOCE("MRZ", "Le righe con i simboli < in fondo a passaporti e carte d'identità: sono le più affidabili da leggere."),
      MAN_VOCE("Backup", "Copia di sicurezza protetta di tutti i dati."),
      MAN_VOCE("Codice di recupero", "Codice da conservare su carta: sostituisce la password se la dimentichi."),
      MAN_VOCE("Anonimizzare", "Togliere per sempre nomi e dati personali, lasciando importi e conteggi."),
    ] },
  ];
}

/* Testo con **grassetto** e «nomi di pulsanti», costruito nel DOM (mai innerHTML) */
function manTesto(x) {
  const out = [];
  x.split(/(\*\*[^*]+\*\*|«[^»]+»)/).forEach(p => {
    if (!p) return;
    if (p.startsWith("**")) out.push(h("strong", {}, manTesto(p.slice(2, -2))));
    else if (p.startsWith("«")) out.push(h("span", { class: "man-ui" }, p.slice(1, -1)));
    else out.push(p);
  });
  return out;
}
function manBlocco(b) {
  if (b.t === "p") return h("p", {}, manTesto(b.x));
  if (b.t === "passi") return h("ol", { class: "man-passi" }, b.v.map(x => h("li", {}, manTesto(x))));
  if (b.t === "lista") return h("ul", {}, b.v.map(x => h("li", {}, manTesto(x))));
  if (b.t === "nota") return h("div", { class: "notice info" }, manTesto(b.x));
  if (b.t === "att") return h("div", { class: "notice" }, manTesto(b.x));
  if (b.t === "faq") return h("details", { class: "man-faq" }, h("summary", {}, b.q), h("p", {}, manTesto(b.a)));
  if (b.t === "voce") return h("div", { class: "man-voce" }, h("dt", {}, b.q), h("dd", {}, manTesto(b.a)));
  if (b.t === "vai") return S.csrf ? h("p", {}, h("a", { class: "btn primary", href: b.href }, b.x + " →")) : null;
  if (b.t === "img") {
    const im = h("img", { src: `assets/manuale/${b.src}.jpg`, alt: b.alt, loading: "lazy" });
    const fig = h("figure", { class: "man-img" }, im, h("figcaption", {}, "Esempio con dati inventati"));
    im.addEventListener("error", () => fig.remove()); // senza immagine il testo basta da solo
    return fig;
  }
  return null;
}
function manNorm(s) { return s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[*«»]/g, "").toLowerCase(); }
function manTestoCap(c) {
  return manNorm([c.titolo, c.breve, ...c.blocchi.map(b => [b.x, b.q, b.a, b.alt, ...(b.v || [])].filter(Boolean).join(" "))].join(" "));
}

function manuale(main, inizio, indietro) {
  const caps = manCapitoli();
  let cur = caps.some(c => c.id === inizio) ? inizio : "inizia";
  const corpo = h("div", { class: "man-corpo" });
  const indice = h("nav", { class: "man-indice", "aria-label": "Capitoli del manuale" });
  const cerca = h("input", { type: "search", placeholder: "Cerca una parola, per esempio cauzione", "aria-label": "Cerca nel manuale" });
  const apri = (id) => {
    if (S.csrf && !indietro) { const hash = `#/manuale?c=${id}`; if (location.hash !== hash) { location.hash = hash; return; } }
    cur = id; cerca.value = ""; disegna(); window.scrollTo(0, 0);
  };
  const cap = (c) => {
    const i = caps.indexOf(c), prec = caps[i - 1], succ = caps[i + 1];
    const blocchi = c.blocchi.map(manBlocco);
    const ospita = c.id === "glossario" ? [h("dl", { class: "man-glossario" }, blocchi)] : blocchi;
    return h("article", { class: "panel man-cap", id: "cap-" + c.id }, h("h2", {}, c.titolo), h("p", { class: "muted" }, c.breve), ospita,
      h("div", { class: "row man-naviga" },
        prec ? h("button", { type: "button", onclick: () => apri(prec.id) }, "← " + prec.titolo) : null, h("span", { class: "spacer" }),
        succ ? h("button", { type: "button", class: "primary", onclick: () => apri(succ.id) }, succ.titolo + " →") : null));
  };
  const disegna = () => {
    let gruppo = null;
    indice.replaceChildren(caps.flatMap(c => {
      const titolo = c.gruppo !== gruppo ? h("h3", {}, c.gruppo) : null; gruppo = c.gruppo;
      return [titolo, h("button", { type: "button", class: "link" + (c.id === cur ? " attivo" : ""), "aria-current": c.id === cur ? "page" : null, onclick: () => apri(c.id) }, c.titolo)];
    }));
    const q = manNorm(cerca.value.trim());
    if (q.length < 2) { corpo.replaceChildren(cap(caps.find(c => c.id === cur))); return; }
    const trovati = caps.filter(c => manTestoCap(c).includes(q));
    corpo.replaceChildren(h("section", { class: "panel" }, h("h2", {}, `Risultati: ${trovati.length}`),
      trovati.length ? h("ul", { class: "plain" }, trovati.map(c => h("li", {},
        h("button", { type: "button", class: "link", onclick: () => apri(c.id) }, c.titolo), h("div", { class: "muted small" }, c.breve))))
        : h("p", { class: "muted" }, "Nessun capitolo contiene questa parola. Prova con una parola più semplice o guarda il glossario.")));
  };
  cerca.addEventListener("input", disegna);
  const stampa = () => {
    corpo.replaceChildren(...caps.map(c => { const a = cap(c); $(".man-naviga", a).remove(); return a; }));
    $$("details", corpo).forEach(d => { d.open = true; }); // sulla carta le risposte devono essere visibili
    $$("img", corpo).forEach(i => { i.loading = "eager"; });
    window.addEventListener("afterprint", disegna, { once: true });
    window.print();
  };
  const hero = h("section", { class: "hero man-hero" }, h("p", { class: "hello" }, "Manuale di istruzioni"),
    h("p", { class: "hello-sub" }, "Tutto quello che serve, spiegato con parole semplici"));
  FOTO.ready.then(() => { if (FOTO.ok.length) hero.style.setProperty("--foto-hero", fotoUrl(FOTO.ok[new Date().getDate() % FOTO.ok.length])); });
  main.replaceChildren(hero,
    h("div", { class: "row man-strumenti" }, cerca,
      indietro ? h("button", { type: "button", onclick: indietro }, "Torna all'accesso") : null,
      h("button", { type: "button", onclick: stampa }, "Stampa il manuale")),
    h("div", { class: "man-griglia" }, indice, corpo));
  disegna();
}

addRoute(/^\/manuale$/, async (main, _m, params) => {
  document.title = "Manuale · " + document.title.split(" · ").pop();
  manuale(main, params.c);
}, "manuale");
