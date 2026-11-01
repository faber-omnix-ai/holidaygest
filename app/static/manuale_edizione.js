/* Parti del manuale che dipendono da questa copia del programma (il resto è in manuale.js) */
"use strict";
const MAN_ED = {
  regola_imposta: [
    MAN_P("Ogni Comune ha le sue regole, e **sei tu a inserirle e approvarle**. Nel programma trovi una regola di esempio da verificare: non usarla senza controllarla."),
    MAN_PASSI([
      "Vai in «Imposta e rendiconti», scheda «Regole imposta».",
      "In «Nuova versione di regola» scrivi Comune, date di validità, tariffa, limite di notti e soglia dei minori, copiandoli dal regolamento del tuo Comune.",
      "In «Fonte (atto, articolo, URL)» indica dove hai trovato i dati.",
      "Premi «Crea versione (stato: da verificare)» e poi «Approva dopo verifica».",
    ]),
    MAN_NOTA("Il nome del Comune deve essere scritto come in «Impostazioni e backup», scheda «Struttura», voce «Comune dell'imposta di soggiorno»."),
  ],
  scadenza_trimestre: "Controlla sul sito del tuo Comune **quando** vanno fatti comunicazione e versamento: scadenze e portali cambiano da Comune a Comune.",
  ross_regola: "In Sardegna il movimento va comunicato **ogni giorno, entro 24 ore**: arrivi e partenze, ma anche i giorni con la casa libera (giornata a zero) e i periodi di chiusura. Nelle altre regioni **verifica termini e regole** della tua Regione: il file è stato provato solo sulla Sardegna.",
  struttura: {
    titolo: "Il primo avvio",
    breve: "Password, dati della casa e regole: da fare una volta sola.",
    blocchi: [
      MAN_PASSI([
        "Avvia il programma e premi «Inizia con un archivio vuoto».",
        "Crea la password. Il programma ti mostra il **codice di recupero**: scrivilo su carta e conservalo lontano dal computer.",
        "Completa «Impostazioni e backup», scheda «Struttura»: nome, indirizzo, CIN e IUN, tipo di attività, Comune, capienza e orari.",
        "Nella stessa scheda indica il tracciato di Alloggiati Web e il codice struttura di ROSS 1000 con unità e letti.",
        "Inserisci la regola dell'imposta di soggiorno del tuo Comune (vedi il capitolo sull'imposta).",
      ]),
      MAN_NOTA("Finché manca qualcosa, la pagina «Oggi» lo elenca in «Configurazione da completare». Puoi completare i dati anche in più volte."),
      MAN_ATT("Prima di inviare il primo file vero a un portale, controllalo con la funzione di verifica del portale. Il programma gestisce un solo appartamento: le camere non sono prenotabili una per una."),
    ],
  },
};
