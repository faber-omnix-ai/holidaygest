/* Imposta e rendiconti; Impostazioni e backup */
"use strict";

addRoute(/^\/imposta$/, async (main, _m, params) => {
  page(main, "Imposta e rendiconti");
  const tab = params.tab || "periodo";
  main.append(h("div", { class: "tabs", role: "tablist" }, [["periodo", "Controlla periodo"], ["staytour", "Prospetto trimestrale"], ["versamenti", "Versamenti e adempimenti"], ["regole", "Regole imposta"], ["moduli", "Moduli esenzione"]]
    .map(([k, l]) => h("button", { type: "button", role: "tab", "aria-selected": String(k === tab), onclick: () => location.hash = `#/imposta?tab=${k}` }, l))));
  const box = h("div", {}); main.append(box);
  await ({ periodo: taxPeriod, staytour: taxStaytour, versamenti: taxRemit, regole: taxRules, moduli: taxForms })[tab](box, params);
}, "imposta");

function periodPicker(kind, value) {
  const t = todayIso();
  const y = +t.slice(0, 4);
  const defaults = { mese: t.slice(0, 7), trimestre: `${y}-T${Math.floor((+t.slice(5, 7) - 1) / 3) + 1}`, anno: String(y) };
  return field("Periodo (mese AAAA-MM, trimestre AAAA-Tn, anno AAAA)", "period", { value: value || defaults[kind] });
}

async function taxPeriod(box, params) {
  const kind = params.kind || "trimestre";
  const f = h("div", { class: "form" }, field("Tipo", "kind", { type: "select", value: kind, options: [["mese", "Mese"], ["trimestre", "Trimestre"], ["anno", "Anno"]] }), periodPicker(kind, params.period));
  $("select", f).addEventListener("change", e => location.hash = `#/imposta?tab=periodo&kind=${e.target.value}`);
  const out = h("div", {});
  box.append(h("section", { class: "panel" }, f, h("div", { class: "row", style: "margin-top:8px" }, h("button", { type: "button", class: "primary", onclick: () => run() }, "Controlla periodo")), out));
  const closures = (await api("GET", "/api/periods/closures")).closures;
  box.append(h("section", { class: "panel" }, h("h2", {}, "Chiusure registrate"), closures.length ? h("ul", { class: "plain" }, closures.map(c => h("li", {},
    `n. ${c.id} · ${c.kind} ${c.period} · ${itdt(c.created_at)} · `, badge(c.status, c.status === "chiuso" ? "ok" : "grey"), c.supersedes_id ? ` (rettifica della n. ${c.supersedes_id}: ${c.reason})` : "",
    h("div", { class: "muted small" }, "Impronta " + c.snapshot_hash.slice(0, 16))))) : h("p", { class: "muted" }, "Nessuna.")));
  const run = async () => {
    const d = formData(f);
    let s; try { s = await api("GET", `/api/periods/check?kind=${d.kind}&period=${encodeURIComponent(d.period)}`); } catch (e) { showError(e); return; }
    const n = s.tax_nights;
    out.replaceChildren(h("h2", { style: "margin-top:14px" }, `${d.kind} ${s.period}: ${itd(s.from)} – ${itd(addDays(s.to, -1))}`),
      h("div", { class: "grid" },
        h("div", {}, h("h3", {}, "Presenze e pernottamenti"), h("dl", { class: "kv" },
          h("dt", {}, "Soggiorni con presenze"), h("dd", {}, s.stays), h("dt", {}, "Persone arrivate"), h("dd", {}, s.persons_arrived),
          h("dt", {}, "Pernottamenti effettivi"), h("dd", {}, s.presence_nights),
          h("dt", {}, "Imponibili"), h("dd", {}, n.imponibile || 0), h("dt", {}, "Esenti"), h("dd", {}, n.esente || 0),
          h("dt", {}, "Non assoggettati"), h("dd", {}, n.non_assoggettata || 0), h("dt", {}, "Oltre il limite"), h("dd", {}, n.oltre_limite || 0),
          h("dt", {}, "DA VERIFICARE"), h("dd", {}, (n.da_chiarire || 0) + (n.senza_regola || 0))),
          Object.keys(s.exempt_reasons).length ? h("ul", { class: "small" }, Object.entries(s.exempt_reasons).map(([k, v]) => h("li", {}, `${k}: ${v}`))) : null),
        h("div", {}, h("h3", {}, "Imposta"), h("dl", { class: "kv" },
          h("dt", {}, "Calcolata"), h("dd", { class: "money" }, eur(s.tax_computed_cents)), h("dt", {}, "Incassata"), h("dd", { class: "money" }, eur(s.tax_collected_cents)),
          h("dt", {}, "Rimborsata"), h("dd", { class: "money" }, eur(s.tax_refunded_cents)), h("dt", {}, "Gestita da terzi"), h("dd", { class: "money" }, eur(s.tax_third_party_cents)),
          h("dt", {}, "Versata"), h("dd", { class: "money" }, eur(s.tax_remitted_cents)))),
        h("div", {}, h("h3", {}, "Soggiorno (non include imposta e cauzioni)"), h("dl", { class: "kv" },
          h("dt", {}, "Ricavi maturati"), h("dd", { class: "money" }, eur(s.revenue_accrued_cents)), h("dt", {}, "Incassi ricevuti"), h("dd", { class: "money" }, eur(s.stay_received_cents)),
          h("dt", {}, "Rimborsi"), h("dd", { class: "money" }, eur(s.stay_refunded_cents)), h("dt", {}, "Cauzioni ricevute / restituite"), h("dd", { class: "money" }, `${eur(s.deposit_received_cents)} / ${eur(s.deposit_returned_cents)}`)))),
      h("p", { class: "small muted" }, `Criteri: notti ${s.attribution.notti}; incassi ${s.attribution.incassi}; versamenti ${s.attribution.versamenti}.`),
      h("ul", { class: "small muted" }, s.explanations.map(x => h("li", {}, x))),
      h("h3", {}, `Anomalie (${s.anomalies.length})`),
      s.anomalies.length ? h("ul", { class: "plain" }, s.anomalies.map(a => h("li", {}, h("a", { href: a.link }, a.text)))) : h("p", { class: "muted" }, "Nessuna anomalia."),
      h("div", { class: "row" },
        h("button", { type: "button", onclick: () => openUrl(`/api/periods/export?kind=${d.kind}&period=${encodeURIComponent(d.period)}&fmt=pdf`) }, "PDF"),
        h("button", { type: "button", onclick: async () => { const r = await api("GET", `/api/periods/export?kind=${d.kind}&period=${encodeURIComponent(d.period)}&fmt=csv`, undefined, { blob: true }); download(r.blob, r.name); } }, "CSV"),
        h("button", { type: "button", onclick: async () => { const r = await api("GET", `/api/periods/export?kind=${d.kind}&period=${encodeURIComponent(d.period)}&fmt=xlsx`, undefined, { blob: true }); download(r.blob, r.name); } }, "XLSX"),
        h("button", { type: "button", class: "primary", onclick: async () => {
          let confirm_anomalies = false, reason = null;
          if (s.anomalies.length) { confirm_anomalies = await confirmDialog("Chiudere con anomalie?", `Ci sono ${s.anomalies.length} anomalie aperte. La chiusura le registrerà come note.`, "Chiudi comunque"); if (!confirm_anomalies) return; }
          if (closures.some(c => c.kind === d.kind && c.period === d.period && c.status === "chiuso")) { reason = prompt("Il periodo è già chiuso: motivo della rettifica?"); if (!reason) return; }
          try { const r = await api("POST", "/api/periods/close", { kind: d.kind, period: d.period, confirm_anomalies, reason }); toast(`Periodo chiuso: riepilogo n. ${r.closure.id}.`); render(); } catch (e) { showError(e); }
        } }, "Chiudi periodo")));
  };
  if (params.period) run();
}

async function taxStaytour(box) {
  const y = +todayIso().slice(0, 4), q = Math.floor((+todayIso().slice(5, 7) - 1) / 3) + 1;
  const pq = q > 1 ? q - 1 : 4, py = q > 1 ? y : y - 1;
  const f = h("div", { class: "form" }, field("Anno", "year", { type: "number", value: py }), field("Trimestre", "quarter", { type: "select", value: pq, options: [1, 2, 3, 4].map(x => [x, `${x}° trimestre`]) }));
  const out = h("div", {});
  box.append(h("section", { class: "panel" }, h("p", { class: "small" }, "Prospetto per compilare a mano la comunicazione trimestrale sul portale comunale (StayTour/SECAL). Non è un file importabile e non prova il versamento."),
    f, h("div", { class: "row", style: "margin-top:8px" }, h("button", { type: "button", class: "primary", onclick: async () => {
      const d = formData(f); const s = await api("GET", `/api/staytour?year=${d.year}&quarter=${d.quarter}`);
      out.replaceChildren(h("h2", { style: "margin-top:12px" }, s.titolo), h("p", { class: "small muted" }, s.avvertenza + " Criterio: " + s.criterio),
        h("dl", { class: "kv" }, h("dt", {}, "Pernottamenti imponibili"), h("dd", {}, s.pernottamenti_imponibili), h("dt", {}, "Giorni di permanenza"), h("dd", {}, s.giorni_permanenza),
          h("dt", {}, "Oltre il limite"), h("dd", {}, s.pernottamenti_oltre_limite), h("dt", {}, "DA VERIFICARE"), h("dd", {}, s.da_verificare),
          ...Object.entries(s.pernottamenti_esenti_per_motivo).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]),
          h("dt", {}, "Imposta calcolata"), h("dd", {}, eur(s.imposta_calcolata_cents)), h("dt", {}, "Imposta riscossa"), h("dd", {}, eur(s.imposta_riscossa_cents)),
          h("dt", {}, "Gestita da terzi"), h("dd", {}, eur(s.imposta_gestita_terzi_cents)), h("dt", {}, "Versamenti registrati"), h("dd", {}, eur(s.versato_cents))),
        s.anomalie.length ? h("div", { class: "notice" }, `${s.anomalie.length} anomalie: vedi «Controlla periodo».`) : null,
        h("button", { type: "button", onclick: () => openUrl(`/api/staytour?year=${d.year}&quarter=${d.quarter}&fmt=pdf`) }, "Prospetto PDF"));
    } }, "Prepara prospetto")), out));
}

async function taxRemit(box) {
  const R = await api("GET", "/api/remittances");
  const uid = newUid();
  const y = +todayIso().slice(0, 4);
  const f = h("div", { class: "form" }, field("Anno", "year", { type: "number", value: y }), field("Trimestre", "quarter", { type: "select", options: [1, 2, 3, 4].map(x => [x, `${x}°`]) }),
    field("Data versamento", "paid_on", { type: "date", value: todayIso() }), field("Importo", "amount", { inputmode: "decimal" }),
    field("Modalità", "method", { type: "select", options: [["pagopa", "PagoPA"], ["bonifico", "Bonifico"], ["altro", "Altro"]] }),
    field("Riferimento (CRO, IUV, n. operazione)", "reference"), field("Note", "note", { wide: true }));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Registra un versamento al Comune"), f, h("button", { type: "button", class: "primary", style: "margin-top:8px", onclick: async () => {
    try { await api("POST", "/api/remittances", { ...formData(f), uid }); toast("Versamento registrato (questo prospetto non è una prova di pagamento: conservare la ricevuta)."); render(); } catch (e) { showError(e, f); }
  } }, "Registra versamento"),
    R.remittances.length ? h("table", { style: "margin-top:10px" }, h("thead", {}, h("tr", {}, ["Periodo", "Data", "Importo", "Riferimento"].map(x => h("th", {}, x)))),
      h("tbody", {}, R.remittances.map(r => h("tr", {}, h("td", {}, `${r.quarter}° trim. ${r.year}`), h("td", {}, itd(r.paid_on)), h("td", { class: "num" }, eur(r.amount_cents)), h("td", {}, r.reference))))) : null));
  const of = h("div", { class: "form" }, field("Adempimento", "kind", { type: "select", options: [["comunicazione_trimestrale", "Comunicazione trimestrale (portale comunale)"], ["dichiarazione_annuale", "Dichiarazione annuale (entro 30 giugno)"]] }),
    field("Periodo (es. 2026-T3 oppure 2026)", "period"), field("Stato", "status", { type: "select", options: [["da_fare", "Da fare"], ["dichiarata", "Dichiarata dall'operatrice"]] }),
    field("Data", "declared_on", { type: "date", value: todayIso() }), field("Riferimento/protocollo", "reference"), field("Note", "note", { wide: true }));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Stato degli adempimenti (indipendente da Alloggiati e ROSS)"), of,
    h("button", { type: "button", style: "margin-top:8px", onclick: async () => { try { await api("POST", "/api/obligations", formData(of)); toast("Stato aggiornato."); render(); } catch (e) { showError(e); } } }, "Salva stato"),
    R.obligations.length ? h("ul", { class: "plain" }, R.obligations.map(o => h("li", {}, `${o.kind.replace("_", " ")} ${o.period}: `, badge(o.status, o.status === "dichiarata" ? "ok" : "warn"), o.reference ? ` · ${o.reference}` : ""))) : null));
}

async function taxRules(box) {
  const R = await api("GET", "/api/tax/rules");
  box.append(h("div", { class: "notice" }, "Le regole sono dati verificabili, non interpretazioni automatiche. Approvarle solo dopo averne controllato fonte, decorrenza e categoria. Per un periodo senza regola il calcolo resta DA VERIFICARE. Una regola usata in conteggi consolidati non si modifica: si crea una nuova versione."));
  for (const r of R.rules) {
    box.append(h("section", { class: "panel" }, h("h2", {}, `Versione ${r.id} · ${r.comune} · ${r.category.replace("_", "-")} `, badge({ da_verificare: "da verificare", approvata: "approvata", revocata: "revocata" }[r.status] || r.status, r.status === "approvata" ? "ok" : r.status === "revocata" ? "grey" : "warn"), r.locked ? badge("usata in conteggi consolidati", "info") : null),
      h("dl", { class: "kv" }, h("dt", {}, "Validità"), h("dd", {}, `${itd(r.valid_from)} – ${itd(r.valid_to)}`), h("dt", {}, "Tariffa"), h("dd", {}, `${eur(r.rate_cents)} per persona e notte`),
        h("dt", {}, "Limite notti consecutive"), h("dd", {}, r.max_nights || "nessuno"),
        h("dt", {}, "Soglia minori"), h("dd", {}, { da_chiarire: "DA CHIARIRE con SECAL (a 12 anni compiuti: DA VERIFICARE)", meno_di_12: "esenti fino al 12° compleanno (escluso)", fino_a_12_compresi: "esenti fino al 13° compleanno (escluso)" }[r.minor_rule]),
        h("dt", {}, "Esenzioni"), h("dd", {}, h("ul", { class: "small" }, r.exemptions.map(e => h("li", {}, R.exemption_labels[e] || e)))),
        h("dt", {}, "Fonte"), h("dd", { class: "small" }, r.source), h("dt", {}, "Verificata il"), h("dd", {}, itd(r.verified_on)), r.notes ? [h("dt", {}, "Note"), h("dd", { class: "small" }, r.notes)] : null),
      h("div", { class: "row" },
        r.status === "da_verificare" && !r.locked ? h("button", { type: "button", class: "primary", onclick: () => approveRule(r) }, "Approva dopo verifica") : null,
        r.status !== "revocata" ? h("button", { type: "button", class: "danger", onclick: async () => { const reason = prompt("Motivo della revoca:"); if (!reason) return; await api("POST", `/api/tax/rules/${r.id}/revoke`, { reason }); render(); } }, "Revoca") : null)));
  }
  const f = h("div", { class: "form" }, field("Comune", "comune", { placeholder: "es. Alghero", hint: "come in Impostazioni → Struttura" }), field("Categoria", "category", { type: "select", options: [["extra_alberghiera", "Extra-alberghiera"]] }),
    field("Valida dal", "valid_from", { type: "date" }), field("Valida al", "valid_to", { type: "date" }), field("Tariffa per persona e notte", "rate", { inputmode: "decimal" }),
    field("Limite notti consecutive", "max_nights", { type: "number", value: 7 }),
    field("Soglia minori", "minor_rule", { type: "select", options: [["da_chiarire", "Da chiarire"], ["meno_di_12", "Esenti sotto i 12 anni"], ["fino_a_12_compresi", "Esenti fino a 12 anni compresi"]] }),
    field("Fonte (atto, articolo, URL)", "source", { wide: true }), field("Data di verifica", "verified_on", { type: "date", value: todayIso() }), field("Note", "notes", { wide: true }),
    ...Object.entries(R.exemption_labels).map(([k, l]) => field(l, "ex_" + k, { type: "checkbox", wide: true })));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Nuova versione di regola"), f, h("button", { type: "button", style: "margin-top:8px", onclick: async () => {
    const d = formData(f); const exemptions = Object.keys(R.exemption_labels).filter(k => d["ex_" + k]);
    try { await api("POST", "/api/tax/rules", { ...d, exemptions, max_nights: +d.max_nights || null }); toast("Versione creata (da verificare)."); render(); } catch (e) { showError(e, f); }
  } }, "Crea versione (stato: da verificare)")));
}
function approveRule(r) {
  const f = h("div", { class: "form" }, field("Interpretazione della soglia d'età", "minor_rule", { type: "select", value: r.minor_rule, wide: true,
    options: [["da_chiarire", "Ancora da chiarire (le notti a 12 anni compiuti restano DA VERIFICARE)"], ["meno_di_12", "Chiarita: esenti fino al compimento dei 12 anni"], ["fino_a_12_compresi", "Chiarita: esenti fino al compimento dei 13 anni"]] }),
    field("Ho verificato fonte, decorrenza e categoria della struttura", "ok", { type: "checkbox", wide: true }));
  openDialog("Approva regola", h("div", {}, f, h("p", { class: "small muted" }, "Scegliere l'interpretazione indicata dal regolamento o dalle FAQ del proprio Comune (es. Alghero: esenti fino a 11 anni e 364 giorni) e annotarla nelle note.")),
    [{ label: "Annulla" }, { label: "Approva", primary: true, onClick: async () => { const d = formData(f); if (!d.ok) { toast("Confermare la verifica.", true); return false; }
      await api("POST", `/api/tax/rules/${r.id}/approve`, { minor_rule: d.minor_rule }); toast("Regola approvata."); render(); } }]);
}
async function taxForms(box) {
  box.append(h("section", { class: "panel" }, h("h2", {}, "Bozze di dichiarazione per le esenzioni"),
    h("p", { class: "small" }, "Bozze da verificare: usare i moduli ufficiali del Comune/SECAL se disponibili. Non raccogliere diagnosi."),
    h("ul", {}, [["disabilita_grave", "Persona con disabilità grave e accompagnatore"], ["assistenza_ricoverati", "Assistenza a persona ricoverata"], ["forze_servizio", "Personale in servizio"]]
      .map(([k, l]) => h("li", {}, h("button", { type: "button", class: "link", onclick: () => openUrl(`/api/exemption-draft/${k}`) }, l))))));
}

/* ---------------- Impostazioni e backup ---------------- */
addRoute(/^\/impostazioni$/, async (main, _m, params) => {
  page(main, "Impostazioni e backup");
  const tab = params.tab || "struttura";
  main.append(h("div", { class: "tabs", role: "tablist" }, [["struttura", "Struttura"], ["backup", "Backup e ripristino"], ["trasferimento", "Trasferisci su un altro PC"], ["sicurezza", "Accesso e protezione"], ["conservazione", "Conservazione dati"], ["altro", "Tabelle, chiusure ROSS, informazioni"]]
    .map(([k, l]) => h("button", { type: "button", role: "tab", "aria-selected": String(k === tab), onclick: () => location.hash = `#/impostazioni?tab=${k}` }, l))));
  const box = h("div", {}); main.append(box);
  const S_ = await api("GET", "/api/settings");
  await ({ struttura: setStructure, backup: setBackup, trasferimento: setTransfer, sicurezza: setSecurity, conservazione: setRetention, altro: setOther })[tab](box, S_);
}, "impostazioni");

function structureForm(st) {
  const a = st.alloggiati || {}, r = st.ross || {};
  return h("div", { class: "form" },
    st.proposed_unverified ? h("div", { class: "notice wide" }, "Dati proposti e non ancora verificati: controllarli con i documenti della struttura e togliere la spunta qui sotto.") : null,
    field("Nome struttura", "name", { value: st.name }), field("Indirizzo", "address", { value: st.address, wide: true }),
    field("CIN", "cin", { value: st.cin }), field("IUN", "iun", { value: st.iun }),
    field("Dati proposti non ancora verificati", "proposed_unverified", { type: "checkbox", value: st.proposed_unverified, wide: true }),
    field("Tipologia dell'attività (da confermare)", "activity_type", { type: "select", value: st.activity_type || "", wide: true, options: [["", "— da indicare —"],
      ["CAV", "Casa e appartamento per vacanze (CAV)"], ["locazione_turistica", "Locazione turistica / unità in locazione occasionale a fini ricettivi"], ["altro", "Altro (da verificare)"]],
      hint: "Il programma non decide. Le FAQ di Sardegna Turismo indicano che una CAV richiede almeno tre unità abitative gestite in forma unitaria e imprenditoriale; confermare con il titolo abilitativo (SUAPE/IUN)." }),
    field("Comune dell'imposta di soggiorno", "tax_comune", { value: st.tax_comune, hint: "come scritto nelle regole dell'imposta (Imposta → Regole)" }),
    field("Categoria per l'imposta di soggiorno", "tax_category", { type: "select", value: st.tax_category || "", options: [["", "— da indicare —"], ["extra_alberghiera", "Struttura extra-alberghiera"]] }),
    field("Confermo la categoria per l'imposta (Regolamento art. 1)", "category_confirmed", { type: "checkbox", value: st.category_confirmed, wide: true }),
    field("Gestore / intestazione quietanze", "owner_name", { value: st.owner_name }), field("Codice fiscale gestore", "owner_tax_code", { value: st.owner_tax_code }),
    field("Partita IVA (se presente)", "owner_vat", { value: st.owner_vat }),
    field("Capienza confermata (persone)", "capacity", { type: "number", value: st.capacity }),
    field("Orario check-in predefinito", "checkin_time", { type: "time", value: st.checkin_time }), field("Orario check-out predefinito", "checkout_time", { type: "time", value: st.checkout_time }),
    field("Tempo di preparazione tra ospiti (minuti)", "cleaning_minutes", { type: "number", value: st.cleaning_minutes }),
    h("h3", { class: "wide" }, "Alloggiati Web"),
    field("Tracciato del profilo", "a_format", { type: "select", value: a.format || "", options: [["", "— da indicare —"], ["168", "Standard 168 caratteri"], ["174", "File unico con ID appartamento (174)"]] }),
    field("ID appartamento (solo tracciato 174)", "a_apartment_id", { value: a.apartment_id, inputmode: "numeric" }),
    field("Gli ospiti vengono già comunicati ad Alloggiati tramite ROSS 1000?", "ross_sends", { hint: "Secondo le FAQ regionali il passaggio non è automatico: da ROSS 1000 si scarica un file da caricare su Alloggiati, oppure si configura il web service. Rispondere «Sì» solo se si usa uno dei due.", type: "select", value: st.ross_sends_alloggiati === null || st.ross_sends_alloggiati === undefined ? "" : String(st.ross_sends_alloggiati), options: [["", "Non so (da verificare)"], ["false", "No"], ["true", "Sì (non caricare il TXT: doppio invio)"]] }),
    h("h3", { class: "wide" }, "ROSS 1000 Sardegna"),
    field("Codice struttura ROSS (assegnato dall'ente, non è CIN/IUN)", "r_code", { value: r.code }),
    field("Unità ricettive disponibili (dato ROSS)", "r_units", { type: "number", value: r.units, hint: "verificare con l'ente: appartamento ≠ camere" }),
    field("Letti disponibili (dato ROSS)", "r_beds", { type: "number", value: r.beds }),
    field("Includi cognome e nome negli arrivi ROSS", "r_names", { type: "checkbox", value: r.include_names === true, wide: true }),
    field("Includi l'elemento facoltativo «prenotazioni»", "r_bookings", { type: "checkbox", value: !!r.include_bookings, wide: true }));
}
function structurePayload(d) {
  return { name: d.name, address: d.address, cin: d.cin, iun: d.iun, proposed_unverified: d.proposed_unverified, activity_type: d.activity_type || null,
    tax_comune: (d.tax_comune || "").trim(), tax_category: d.tax_category || null, category_confirmed: d.category_confirmed, owner_name: d.owner_name, owner_tax_code: d.owner_tax_code, owner_vat: d.owner_vat,
    capacity: d.capacity ? +d.capacity : null, checkin_time: d.checkin_time, checkout_time: d.checkout_time, cleaning_minutes: +d.cleaning_minutes || 0,
    alloggiati: { format: d.a_format || null, apartment_id: d.a_apartment_id }, ross_sends_alloggiati: d.ross_sends === "" ? null : d.ross_sends === "true",
    ross: { code: d.r_code, units: d.r_units ? +d.r_units : null, beds: d.r_beds ? +d.r_beds : null, include_names: d.r_names, include_bookings: d.r_bookings } };
}
async function setStructure(box, S_) {
  const f = structureForm(S_.structure);
  box.append(h("section", { class: "panel" }, f, h("button", { type: "button", class: "primary", style: "margin-top:10px", onclick: async () => {
    try { await api("PUT", "/api/settings", { structure: structurePayload(formData(f)) }); LISTS = null; toast("Impostazioni salvate."); render(); } catch (e) { showError(e, f); }
  } }, "Salva")));
}

async function setBackup(box) {
  const B = await api("GET", "/api/backup/status");
  const b = B.backup;
  box.append(h("section", { class: "panel" }, h("h2", {}, "Archivio in uso"), h("dl", { class: "kv" },
    h("dt", {}, "Database"), h("dd", { class: "small" }, B.db_path), h("dt", {}, "Cartella dati"), h("dd", { class: "small" }, B.data_dir),
    h("dt", {}, "Ultimo backup riuscito"), h("dd", {}, b.local_last_ok_at ? itdt(b.local_last_ok_at) : "mai"),
    h("dt", {}, "Ultima copia esterna"), h("dd", {}, b.external_last_ok_at ? `${itdt(b.external_last_ok_at)} · ${b.external_last_ok_path}` : "mai")),
    b.local_last_error ? h("div", { class: "notice err" }, "Ultimo errore: " + b.local_last_error) : null,
    b.external_last_error ? h("div", { class: "notice" }, "Ultimo errore copia esterna: " + b.external_last_error) : null,
    h("p", { class: "small muted" }, "Il backup è cifrato: contiene database, ricevute allegate e foto/PDF della manutenzione, NON contiene immagini dei documenti degli ospiti né testo OCR. Per aprirlo servono la password o il codice di recupero. Viene fatto anche automaticamente alla chiusura del programma."),
    h("button", { type: "button", class: "primary", onclick: async () => { try { const r = await api("POST", "/api/backup/local", {}); toast("Backup creato e verificato: " + r.name); render(); } catch (e) { showError(e); } } }, "Crea backup ora")));
  const dir = h("input", { value: b.external_dir || (B.drives[0] || {}).path || "", placeholder: "es. E:\\ oppure una cartella" });
  box.append(h("section", { class: "panel" }, h("h2", {}, "Copia su chiavetta o disco esterno"),
    B.drives.length ? h("p", { class: "small" }, "Unità rimovibili trovate: ", B.drives.map(d => h("button", { type: "button", class: "link", style: "margin-right:8px", onclick: () => dir.value = d.path }, d.path))) : h("p", { class: "small muted" }, "Nessuna chiavetta rilevata. Si può indicare qualsiasi cartella."),
    h("label", {}, "Destinazione"), dir,
    h("button", { type: "button", style: "margin-top:8px", onclick: async () => { try { const r = await api("POST", "/api/backup/external", { dir: dir.value }); toast("Copia completata e verificata: " + r.path); render(); } catch (e) { showError(e); render(); } } }, "Copia ora"),
    h("p", { class: "small muted" }, "Se la chiavetta non è inserita il programma continua a funzionare normalmente: l'insuccesso viene segnalato qui e in Oggi.")));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Backup locali"), B.local_files.length ? h("ul", { class: "plain" }, B.local_files.map(f => h("li", {}, `${f.name} · ${(f.size / 1024).toFixed(0)} KB `,
    h("button", { type: "button", class: "link", onclick: async () => { const r = await api("GET", `/api/backup/file?name=${encodeURIComponent(f.name)}`, undefined, { blob: true }); download(r.blob, f.name); } }, "Scarica")))) : h("p", { class: "muted" }, "Nessuno.")));
  box.append(restorePanel(false));
}

function restorePanel(firstRun) {
  const fi = h("input", { type: "file", accept: ".gcbak" });
  const secret = h("input", { type: "password", autocomplete: "off", placeholder: "Password oppure codice di recupero" });
  const out = h("div", {});
  const readFile = () => new Promise((res, rej) => { const f = fi.files[0]; if (!f) { rej(new ApiError("Scegliere il file di backup (.gcbak).")); return; } f.arrayBuffer().then(res, rej); });
  const hdr = () => ({ "X-Backup-Secret": btoa(unescape(encodeURIComponent(secret.value))), "Content-Type": "application/octet-stream" });
  return h("section", { class: "panel" }, h("h2", {}, firstRun ? "Ripristina da un backup (trasferimento da un altro PC)" : "Verifica o ripristina un backup"),
    h("label", {}, "File di backup"), fi, h("label", { style: "margin-top:8px" }, "Password o codice di recupero dell'archivio di origine"), secret,
    h("div", { class: "row", style: "margin-top:8px" },
      h("button", { type: "button", onclick: async () => { try { const r = await api("POST", "/api/backup/verify", await readFile(), { raw: true, headers: hdr() });
        out.replaceChildren(h("div", { class: "notice ok" }, `Backup integro del ${itdt(r.header.created_at)} (versione ${r.header.app_version}): ${r.counts.prenotazioni} prenotazioni, ${r.counts.ospiti} ospiti, ${r.counts.movimenti} movimenti, ${r.attachments} allegati.`)); } catch (e) { showError(e); } } }, "Verifica senza ripristinare"),
      h("button", { type: "button", class: "danger", onclick: async () => {
        if (!firstRun && !(await confirmDialog("Sostituire l'archivio attuale?", ["L'archivio attuale verrà prima copiato in una cartella di sicurezza.", "Dopo il ripristino occorre accedere con la password dell'archivio ripristinato."], "Ripristina", true))) return;
        try { const r = await api("POST", "/api/backup/restore", await readFile(), { raw: true, headers: { ...hdr(), "X-Confirm-Replace": firstRun ? "0" : "1" } });
          out.replaceChildren(h("div", { class: "notice ok" }, h("p", {}, `Ripristino completato: ${r.counts.prenotazioni} prenotazioni, ${r.counts.ospiti} ospiti, ${r.counts.movimenti} movimenti, ${r.attachments} allegati.`),
            r.safety_copy ? h("p", { class: "small" }, "Copia di sicurezza dell'archivio precedente: " + r.safety_copy) : null,
            h("p", { class: "small" }, "Eliminazioni già fatte riapplicate (i dati cancellati non tornano con il backup): "
              + Object.entries(r.retention_reapplied || {}).map(([k, v]) => `${k} ${v}`).join(", ") + "."),
            h("p", {}, "Ora accedi con la password dell'archivio ripristinato e verifica prenotazioni, movimenti e ricevute."),
            h("button", { type: "button", class: "primary", onclick: () => location.reload() }, "Vai all'accesso")));
        } catch (e) { showError(e); } } }, "Ripristina")), out);
}

async function setTransfer(box) {
  box.append(h("section", { class: "panel" }, h("h2", {}, "Trasferire il gestionale su un altro PC"),
    h("div", { class: "notice" }, "Non esiste sincronizzazione tra due PC: se si usano due copie separatamente si ottengono archivi diversi, che il programma non unisce. Dopo il trasferimento usare un solo PC."),
    h("ol", { class: "steps" },
      h("li", {}, h("strong", {}, "Crea un backup coerente e protetto. "), h("button", { type: "button", onclick: async () => { try { const r = await api("POST", "/api/backup/local", {}); toast("Backup creato e verificato: " + r.name); } catch (e) { showError(e); } } }, "Crea backup ora")),
      h("li", {}, h("strong", {}, "Copia il backup sul supporto scelto "), "(chiavetta o disco): ", h("a", { href: "#/impostazioni?tab=backup" }, "Copia su chiavetta"), ". Copia anche la cartella del programma (o lo ZIP di consegna)."),
      h("li", {}, h("strong", {}, "Sul secondo PC "), "copia la cartella del programma (es. in Documenti), poi fai doppio clic su AvviaGestionale.exe. Non serve installare nulla."),
      h("li", {}, h("strong", {}, "Al primo avvio scegli «Ripristina da backup» "), "e indica il file .gcbak e la password (o il codice di recupero) dell'archivio di origine."),
      h("li", {}, h("strong", {}, "Verifica "), "che prenotazioni, movimenti, regole dell'imposta e ricevute siano presenti (il ripristino mostra i conteggi); poi smetti di usare il vecchio PC.")),
    h("p", { class: "small muted" }, "Senza password e senza codice di recupero il backup non può essere aperto da nessuno, nemmeno dall'assistenza.")));
}

async function setSecurity(box) {
  const f = h("div", { class: "form" }, field("Password attuale", "old", { type: "password" }), field("Nuova password (min. 10 caratteri)", "new", { type: "password" }));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Cosa è protetto e come"), h("ul", { class: "small" },
    h("li", {}, "La password serve per accedere all'interfaccia ed è conservata solo come impronta (scrypt)."),
    h("li", {}, "I dati dei documenti d'identità (tipo, numero, luogo di rilascio), le ricevute allegate e i backup sono cifrati con AES-256-GCM con una chiave dati casuale."),
    h("li", {}, "La chiave dati è conservata solo cifrata, due volte: con la password e con il codice di recupero. Non esiste una chiave universale."),
    h("li", {}, "Le altre informazioni del database (prenotazioni, nomi, importi) NON sono cifrate sul disco: proteggere l'accesso a Windows con una password e, se possibile, attivare BitLocker."),
    h("li", {}, "Le immagini dei documenti restano solo in memoria durante la verifica e non entrano in backup, log o rapporti.")),
    h("h3", {}, "Cambia password"), f, h("button", { type: "button", style: "margin-top:8px", onclick: async () => { try { await api("POST", "/api/password", formData(f)); toast("Password cambiata."); } catch (e) { showError(e, f); } } }, "Cambia password"),
    h("h3", {}, "Nuovo codice di recupero"), h("p", { class: "small" }, "Il codice precedente smetterà di funzionare per l'archivio (resta valido per i backup già creati)."),
    h("button", { type: "button", onclick: async () => { const pw = prompt("Password attuale:"); if (!pw) return; try { const r = await api("POST", "/api/recovery-code", { password: pw });
      openDialog("Nuovo codice di recupero", h("div", {}, h("p", {}, "Trascrivilo e conservalo lontano dal PC:"), h("div", { class: "code" }, r.recovery_code)), [{ label: "L'ho conservato" }]); } catch (e) { showError(e); } } }, "Genera nuovo codice")));
}

async function setRetention(box, S_) {
  const R = await api("GET", "/api/retention");
  const f = h("div", { class: "form" }, field("Conservazione anagrafiche e prenotazioni (anni dopo l'anno del soggiorno)", "anagrafica_years", { type: "number", value: R.policy.anagrafica_years }),
    field("Periodo confermato con il consulente", "confirmed", { type: "checkbox", value: R.policy.confirmed, wide: true }));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Regole di conservazione"), h("ul", { class: "small" },
    h("li", {}, "Dati dei documenti: eliminati quando si allega la ricevuta Alloggiati (nota del Garante del 29/04/2026)."),
    h("li", {}, "Ricevute Alloggiati: conservate 5 anni, poi eliminate automaticamente."),
    h("li", {}, "Immagini e testo letto dai documenti: mai salvati su disco."),
    h("li", {}, "Il programma non cancella mai file fuori dalla propria cartella dati (foto sul telefono, download, chiavette): eliminarli manualmente.")),
    f, h("button", { type: "button", onclick: async () => { await api("PUT", "/api/settings", { structure: {}, retention: formData(f) }); toast("Salvato."); render(); } }, "Salva")));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Prenotazioni oltre il periodo di conservazione"), R.candidates.length ? h("div", {},
    h("ul", {}, R.candidates.map(c => h("li", {}, `${c.ref} · ${itd(c.arrival)} – ${itd(c.departure)}`))),
    h("button", { type: "button", class: "danger", onclick: async () => { if (!(await confirmDialog("Anonimizzare?", `${R.candidates.length} prenotazioni: nomi, contatti e dati anagrafici verranno rimossi definitivamente; restano importi e conteggi.`, "Anonimizza", true))) return;
      await api("POST", "/api/retention/anonymize", { booking_ids: R.candidates.map(c => c.id) }); toast("Anonimizzazione eseguita."); render(); } }, "Anonimizza"))
    : h("p", { class: "muted" }, "Nessuna."),
    R.stale_documents.length ? h("div", { class: "notice" }, `Documenti ancora conservati per ospiti partiti senza esito Alloggiati: ${R.stale_documents.map(x => x.ref).join(", ")}. Completare la comunicazione e allegare la ricevuta.`) : null));
}

async function setOther(box, S_) {
  const C = await api("GET", "/api/closures");
  const cf = h("div", { class: "form" }, field("Primo giorno", "start", { type: "date" }), field("Ultimo giorno", "last", { type: "date" }), field("Nota", "note", { wide: true }));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Chiusure ROSS 1000 (apertura = NO)"),
    h("p", { class: "small muted" }, "Distinte dai blocchi del calendario: un blocco per manutenzione non diventa automaticamente una chiusura statistica. Verificare le regole regionali."),
    cf, h("button", { type: "button", style: "margin-top:8px", onclick: async () => { try { await api("POST", "/api/closures", formData(cf)); render(); } catch (e) { showError(e, cf); } } }, "Registra chiusura"),
    C.closures.length ? h("ul", { class: "plain" }, C.closures.map(c => h("li", {}, `${itd(c.start)} – ${itd(addDays(c.end_excl, -1))} ${c.note || ""} `,
      h("button", { type: "button", class: "link", onclick: async () => { await api("POST", `/api/closures/${c.id}/delete`, {}); render(); } }, "Rimuovi")))) : null));
  const t = S_.tables;
  const files = {};
  const inputs = ["comuni", "stati", "documenti", "tipo_alloggiato"].map(k => { const i = h("input", { type: "file", accept: ".csv" }); i.addEventListener("change", async () => { const f = i.files[0]; if (f) files[k] = bufToB64(await f.arrayBuffer()); }); return h("div", { class: "field" }, h("label", {}, k + ".csv"), i); });
  box.append(h("section", { class: "panel" }, h("h2", {}, "Tabelle ufficiali Alloggiati"), h("p", { class: "small" }, `In uso: ${t.fonte} · scaricate il ${itd(t.scaricato_il)}`),
    h("p", { class: "small muted" }, "Per aggiornarle: scaricare i 4 file dalla pagina «Tabelle» del portale Alloggiati Web e importarli qui. Il programma non si collega a Internet."),
    h("div", { class: "form" }, inputs), h("button", { type: "button", style: "margin-top:8px", onclick: async () => { try { await api("POST", "/api/tables/import", { files }); toast("Tabelle aggiornate."); render(); } catch (e) { showError(e); } } }, "Importa tabelle")));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Informazioni"), h("dl", { class: "kv" },
    h("dt", {}, "Versione"), h("dd", {}, S.status.version), h("dt", {}, "Cartella programma"), h("dd", { class: "small" }, S_.program_dir),
    h("dt", {}, "Cartella dati"), h("dd", { class: "small" }, S_.data_dir), h("dt", {}, "Modalità portatile"), h("dd", {}, S_.portable ? "Sì: dati sulla chiavetta" : "No")),
    h("p", { class: "small muted" }, "Aggiornare il programma: chiudere il gestionale, sostituire la cartella del programma con la nuova versione, riavviare. I dati restano nella cartella dati; prima di aggiornare lo schema il programma crea una copia di sicurezza."),
    h("button", { type: "button", class: "danger", onclick: async () => { if (await confirmDialog("Chiudere il gestionale?", "Verrà eseguito un backup automatico e il programma si fermerà.", "Chiudi")) { await api("POST", "/api/shutdown", {}); document.body.replaceChildren(h("p", { class: "center-box" }, "Gestionale chiuso. Puoi chiudere questa scheda.")); } } }, "Chiudi il gestionale")));
}
