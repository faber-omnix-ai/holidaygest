/* Prenotazioni, scheda soggiorno, ospiti, pagamenti, imposta */
"use strict";
let LISTS = null;
async function lists() { if (!LISTS) LISTS = (await api("GET", "/api/settings")).lists; return LISTS; }
const opt = (arr) => [["", "— scegli —"], ...arr.map(x => [x, x])];

addRoute(/^\/prenotazioni$/, async (main, _m, params) => {
  const q = params.q || "", st = params.stato || "";
  const r = await api("GET", `/api/bookings?q=${encodeURIComponent(q)}&status=${st}`);
  page(main, "Prenotazioni e soggiorni", `${r.bookings.length} risultati`,
    [h("button", { type: "button", class: "primary", onclick: () => bookingDialog({}, (b) => location.hash = `#/prenotazione/${b.id}`) }, "Nuova prenotazione")]);
  const search = h("input", { type: "search", value: q, placeholder: "Cerca referente o riferimento", "aria-label": "Cerca" });
  const sel = h("select", { "aria-label": "Stato", style: "width:auto" }, [["", "Tutti gli stati"], ...Object.entries(STATUS_IT)].map(([v, l]) => h("option", { value: v, selected: v === st }, l)));
  const go = () => location.hash = `#/prenotazioni?q=${encodeURIComponent(search.value)}&stato=${sel.value}`;
  search.addEventListener("keydown", e => { if (e.key === "Enter") go(); }); sel.addEventListener("change", go);
  main.append(h("div", { class: "row", style: "margin-bottom:10px" }, h("div", { style: "flex:1;min-width:220px" }, search), sel, h("button", { type: "button", onclick: go }, "Cerca")));
  main.append(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Rif.", "Referente", "Arrivo", "Partenza", "Persone", "Ospiti inseriti", "Stato"].map(x => h("th", {}, x)))),
    h("tbody", {}, r.bookings.map(b => h("tr", {}, h("td", {}, h("a", { href: `#/prenotazione/${b.id}` }, b.ref)), h("td", {}, b.booker_name),
      h("td", {}, itd(b.arrival)), h("td", {}, itd(b.departure)), h("td", { class: "num" }, b.guests_expected), h("td", { class: "num" }, b.n_guests),
      h("td", {}, badge(b.status_label, BOOKING_BADGE[b.status]))))))));
}, "prenotazioni");

/* ---- Nuova prenotazione: bastano referente, contatto, periodo, persone, stato ---- */
async function bookingDialog(init, done) {
  const L = await lists();
  const f = h("div", { class: "form" },
    field("Referente (chi prenota)", "booker_name", { required: true, wide: true, hint: "può non soggiornare" }),
    field("Telefono", "booker_phone", { type: "tel" }), field("E-mail", "booker_email", { type: "email" }),
    field("Arrivo", "arrival", { type: "date", value: init.arrival || "" }), field("Partenza", "departure", { type: "date", value: init.departure || "" }),
    field("Persone previste", "guests_expected", { type: "number", value: 2 }),
    field("Stato", "status", { type: "select", value: "confermata", options: [["confermata", "Confermata"], ["opzione", "Opzione (con scadenza)"], ["bozza", "Bozza (non occupa il calendario)"]] }),
    field("Scadenza opzione", "option_expires_at", { type: "datetime-local", hint: "solo per opzioni" }),
    field("Prezzo", "pricing_mode", { type: "select", options: [["totale", "Totale concordato"], ["per_notte", "Prezzo per notte × notti"]] }),
    field("Importo (totale o per notte)", "price", { inputmode: "decimal", placeholder: "es. 650,00" }),
    field("Cauzione richiesta", "deposit", { inputmode: "decimal", placeholder: "0,00" }),
    field("Provenienza (testo libero)", "source_text", { placeholder: "es. passaparola, telefono" }),
    field("Note operative", "notes", { type: "textarea", wide: true }));
  const avail = h("div", { class: "small", "aria-live": "polite" });
  const ack = h("label", { class: "check", hidden: true }, h("input", { type: "checkbox", name: "turnover_ack" }), "Accetto il cambio ospiti nello stesso giorno con tempi ridotti (decisione esplicita)");
  const check = async () => {
    const d = formData(f); if (!d.arrival || !d.departure || d.departure <= d.arrival) { avail.textContent = ""; return; }
    const r = await api("GET", `/api/availability?from=${d.arrival}&to=${d.departure}`);
    avail.replaceChildren(
      h("div", {}, `${nightsBetween(d.arrival, d.departure)} notti. `),
      ...r.conflicts.map(c => h("div", { class: "notice err" }, c.message)),
      ...r.turnovers.map(t => h("div", { class: "notice " + (t.compatible ? "info" : "") }, t.message)),
      r.conflicts.length ? "" : h("div", { class: "notice ok" }, "Periodo disponibile nel calendario interno."));
    ack.hidden = !r.turnover_problem;
  };
  f.addEventListener("change", check); setTimeout(check, 50);
  openDialog("Nuova prenotazione", h("div", {}, f, avail, ack,
    h("p", { class: "muted small" }, "I documenti degli ospiti non servono per prenotare: verranno richiesti al check-in. Il calendario non aggiorna annunci esterni.")),
    [{ label: "Annulla" }, {
      label: "Salva prenotazione", primary: true, onClick: async (form) => {
        const d = formData(f);
        const body = { ...d, turnover_ack: $("input[name=turnover_ack]", form).checked, guests_expected: +d.guests_expected || 0,
          base_cents: d.pricing_mode === "totale" ? d.price : 0, nightly_cents: d.pricing_mode === "per_notte" ? d.price : 0, deposit_cents: d.deposit };
        const r = await api("POST", "/api/bookings", body);
        if (r.capacity_warning) toast(r.capacity_warning, true);
        toast(`Prenotazione ${r.booking.ref} salvata.`);
        done && done(r.booking);
      }
    }]);
}

/* ---- Scheda prenotazione ---- */
addRoute(/^\/prenotazione\/(\d+)$/, async (main, m, params) => {
  const id = +m[1];
  const D = await api("GET", `/api/bookings/${id}`);
  const b = D.booking;
  const reload = () => render();
  const acts = [];
  const st = b.status;
  if (["bozza", "opzione_scaduta"].includes(st)) acts.push(h("button", { type: "button", onclick: () => statusAction(b, "opzione", reload) }, "Metti in opzione"));
  if (["bozza", "opzione", "opzione_scaduta"].includes(st)) acts.push(h("button", { type: "button", class: "primary", onclick: () => statusAction(b, "conferma", reload) }, "Conferma"));
  if (["confermata", "in_corso"].includes(st) && D.guests.some(g => g.presence === "prevista")) acts.push(h("button", { type: "button", class: "primary", onclick: () => checkinDialog(D, reload) }, "Registra arrivo (check-in)"));
  if (st === "in_corso") acts.push(h("button", { type: "button", onclick: () => checkoutDialog(D, reload) }, "Registra partenza (check-out)"));
  if (st === "confermata" && b.arrival <= todayIso()) acts.push(h("button", { type: "button", class: "danger", onclick: () => statusAction(b, "no_show", reload) }, "Segna no-show"));
  if (["bozza", "opzione", "opzione_scaduta", "confermata"].includes(st)) acts.push(h("button", { type: "button", class: "danger", onclick: () => statusAction(b, "annulla", reload) }, "Annulla prenotazione"));
  page(main, `${b.ref} · ${b.booker_name}`, null, acts);
  main.append(h("div", { class: "row", style: "margin:-6px 0 10px" }, badge(b.status_label, BOOKING_BADGE[st]),
    h("span", {}, `${itd(b.arrival)} → ${itd(b.departure)} · ${nightsBetween(b.arrival, b.departure)} notti · ${b.guests_expected} persone previste`),
    st === "opzione" ? badge(`Opzione fino al ${itdt(b.option_expires_at)}`, "warn") : null,
    ["confermata", "opzione"].includes(st) ? prepSelect(b.id, b.prep_status) : null));
  if (D.capacity_warning) main.append(h("div", { class: "notice" }, D.capacity_warning));
  if (D.corrections.some(c => c.status === "aperta")) main.append(h("div", { class: "notice err" }, h("strong", {}, "Rettifiche aperte: "),
    h("ul", {}, D.corrections.filter(c => c.status === "aperta").map(c => h("li", {}, c.reason)))));
  const tabs = [["dati", "Prenotazione"], ["ospiti", `Ospiti (${D.guests.length})`], ["pagamenti", "Pagamenti"], ["imposta", "Imposta"], ["adempimenti", `Adempimenti (${D.open_items.length})`]];
  const cur = params.tab || (params.ospite ? "ospiti" : "dati");
  main.append(h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, l]) => h("button", { type: "button", role: "tab", "aria-selected": String(k === cur),
    onclick: () => location.hash = `#/prenotazione/${id}?tab=${k}` }, l))));
  const box = h("div", {}); main.append(box);
  ({ dati: tabData, ospiti: tabGuests, pagamenti: tabPay, imposta: tabTax, adempimenti: tabObl })[cur](box, D, reload, params);
}, "prenotazioni");

async function statusAction(b, action, done) {
  const titles = { opzione: "Metti in opzione", conferma: "Conferma prenotazione", annulla: "Annulla prenotazione", no_show: "Registra no-show" };
  const f = h("div", { class: "form" });
  if (action === "opzione") f.append(field("Scadenza dell'opzione", "option_expires_at", { type: "datetime-local" }));
  if (action === "annulla") f.append(field("Motivo dell'annullamento", "reason", { wide: true }),
    field("Corrispettivo trattenuto (penale), se previsto", "retained", { inputmode: "decimal", placeholder: "lasciare vuoto per non modificare" }),
    h("p", { class: "wide muted small" }, "Incassi, rimborsi e quietanze già registrati restano invariati: eventuali restituzioni si registrano come movimenti separati."));
  if (action === "no_show") f.append(field("Confermo che gli ospiti non si sono presentati", "confirm", { type: "checkbox", wide: true }),
    h("p", { class: "wide muted small" }, "Il no-show non viene mai registrato automaticamente."));
  const ack = h("label", { class: "check", hidden: true }, h("input", { type: "checkbox", name: "turnover_ack" }), "Accetto il cambio ospiti con tempi ridotti");
  openDialog(titles[action], h("div", {}, f, ack), [{ label: "Indietro" }, {
    label: titles[action], primary: action !== "annulla", danger: action === "annulla", onClick: async (form) => {
      const d = formData(form);
      const body = { version: b.version, ...d };
      if (action === "annulla" && d.retained) body.retained_cents = d.retained;
      try { await api("POST", `/api/bookings/${b.id}/status/${action}`, body); }
      catch (e) { if (e.body.detail && e.body.detail.needs_turnover_ack) { ack.hidden = false; toast(e.message, true); return false; } throw e; }
      toast("Operazione registrata."); done();
    }
  }]);
}

function tabData(box, D, reload) {
  const b = D.booking;
  const L = D.lists;
  const f = h("div", { class: "form" },
    field("Referente", "booker_name", { value: b.booker_name, wide: true }),
    field("Telefono", "booker_phone", { value: b.booker_phone }), field("E-mail", "booker_email", { value: b.booker_email }),
    field("Arrivo", "arrival", { type: "date", value: b.arrival }), field("Partenza", "departure", { type: "date", value: b.departure }),
    field("Ora arrivo prevista", "checkin_time", { type: "time", value: b.checkin_time }), field("Ora partenza prevista", "checkout_time", { type: "time", value: b.checkout_time }),
    field("Persone previste", "guests_expected", { type: "number", value: b.guests_expected }),
    field("Modalità prezzo", "pricing_mode", { type: "select", value: b.pricing_mode, options: [["totale", "Totale concordato"], ["per_notte", "Prezzo per notte × notti"]] }),
    field("Totale concordato", "base_cents", { value: (b.base_cents / 100).toFixed(2).replace(".", ","), inputmode: "decimal" }),
    field("Prezzo per notte", "nightly_cents", { value: (b.nightly_cents / 100).toFixed(2).replace(".", ","), inputmode: "decimal" }),
    field("Cauzione richiesta", "deposit_cents", { value: (b.deposit_cents / 100).toFixed(2).replace(".", ","), inputmode: "decimal" }),
    field("Provenienza (testo)", "source_text", { value: b.source_text }),
    field("Tipo di turismo (ROSS)", "tourism_type", { type: "select", value: b.tourism_type || "", options: opt(L.tourism) }),
    field("Mezzo di trasporto (ROSS)", "transport", { type: "select", value: b.transport || "", options: opt(L.transport) }),
    field("Canale di prenotazione (ROSS)", "booking_channel", { type: "select", value: b.booking_channel || "", options: opt(L.channel) }),
    field("Note operative", "notes", { type: "textarea", value: b.notes, wide: true }));
  const items = h("div", {});
  const drawItems = (arr) => items.replaceChildren(h("h3", {}, "Extra e sconti (separati dall'imposta)"),
    ...arr.map((it, i) => h("div", { class: "row", style: "margin-bottom:6px" },
      h("select", { style: "width:auto", "aria-label": "Tipo", onchange: e => it.kind = e.target.value }, ["extra", "sconto"].map(k => h("option", { value: k, selected: it.kind === k }, k))),
      h("input", { value: it.description, placeholder: "Descrizione", "aria-label": "Descrizione", oninput: e => it.description = e.target.value, style: "flex:2" }),
      h("input", { value: it.amount, placeholder: "Importo", "aria-label": "Importo", inputmode: "decimal", oninput: e => it.amount = e.target.value, style: "flex:1" }),
      h("button", { type: "button", onclick: () => { arr.splice(i, 1); drawItems(arr); } }, "Rimuovi"))),
    h("button", { type: "button", onclick: () => { arr.push({ kind: "extra", description: "", amount: "" }); drawItems(arr); } }, "Aggiungi extra o sconto"));
  const P = D.balances.price;
  const priceItems = P.items.map(i => ({ kind: i.kind, description: i.description, amount: (i.amount_cents / 100).toFixed(2).replace(".", ",") }));
  drawItems(priceItems);
  box.append(h("section", { class: "panel" }, f, items,
    h("p", { class: "small" }, `Corrispettivo attuale: ${eur(P.total_cents)} (base ${eur(P.base_cents)} + extra ${eur(P.extra_cents)} − sconti ${eur(P.discount_cents)}, ${P.nights} notti)`),
    h("div", { class: "row" }, h("button", { type: "button", class: "primary", onclick: async () => {
      const d = formData(f);
      const body = { ...d, guests_expected: +d.guests_expected };
      let p;
      try { p = await api("POST", `/api/bookings/${b.id}/preview`, body); } catch (e) { showError(e, f); return; }
      const ack = h("input", { type: "checkbox" });
      const blocked = p.availability && p.availability.conflicts.length;
      openDialog("Conseguenze della modifica", h("div", {}, h("ul", {}, p.summary.map(s => h("li", {}, s))),
        Object.keys(p.changes).length ? h("p", { class: "small muted" }, "Dati modificati: " + Object.values(p.changes).map(c => c.label).join(", ")) : null,
        p.availability && p.availability.turnover_problem ? h("label", { class: "check" }, ack, "Accetto il cambio ospiti con tempi ridotti") : null),
        [{ label: "Annulla" }, blocked ? null : { label: "Conferma modifica", primary: true, onClick: async () => {
          await api("PUT", `/api/bookings/${b.id}`, { ...body, version: b.version, turnover_ack: ack.checked, price_items: priceItems });
          toast("Prenotazione aggiornata."); reload();
        } }].filter(Boolean));
    } }, "Verifica e salva modifiche"))));
}

/* ---- Ospiti ---- */
function tabGuests(box, D, reload, params) {
  const b = D.booking;
  box.append(h("div", { class: "row", style: "margin-bottom:10px" },
    h("button", { type: "button", class: "primary", onclick: () => guestDialog(D, null, reload) }, "Aggiungi ospite (inserimento manuale)"),
    h("a", { class: "btn", href: `#/documenti?prenotazione=${b.id}` }, "Aggiungi ospite da documento"),
    h("span", { class: "muted small" }, "Il referente non è automaticamente un ospite.")));
  if (!D.guests.length) { box.append(h("p", { class: "muted" }, "Nessun ospite inserito.")); return; }
  box.append(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Ospite", "Tipo", "Presenza", "Permanenza", "Dati", "Alloggiati", ""].map(x => h("th", {}, x)))),
    h("tbody", {}, D.guests.map(g => h("tr", {},
      h("td", {}, `${g.surname} ${g.name}`, g.duplicates.length ? h("div", {}, badge("Possibile duplicato: " + g.duplicates.map(x => x.ref).join(", "), "warn")) : null),
      h("td", {}, GUEST_TYPES.find(x => x[0] === g.guest_type)[1]),
      h("td", {}, badge(PRESENCE_IT[g.presence], g.presence === "presente" ? "ok" : "grey")),
      h("td", { class: "small" }, g.stay_arrival ? `effettiva ${itd(g.stay_arrival)} → ${g.stay_departure ? itd(g.stay_departure) : "in corso"}` :
        `prevista ${itd(g.planned_arrival || b.arrival)} → ${itd(g.planned_departure || b.departure)}`),
      h("td", {}, g.verified_at ? badge("Verificati", "ok") : badge(g.missing.length ? `${g.missing.length} da completare` : "Da verificare", "warn")),
      h("td", {}, badge(ALLOG_IT[g.alloggiati_status] || g.alloggiati_status, ALLOG_KIND[g.alloggiati_status])),
      h("td", {}, h("div", { class: "row" },
        h("button", { type: "button", onclick: () => guestDialog(D, g.id, reload) }, "Apri"),
        g.presence === "presente" ? h("button", { type: "button", onclick: () => guestDepartureDialog(g, reload, b) }, "Partenza") : null,
        g.presence === "prevista" && b.status !== "bozza" ? h("button", { type: "button", onclick: async () => {
          try {
            if (await confirmEffects("Ospite non arrivato", g.id, "not_arrived", {}, `${g.surname} ${g.name} non è arrivato/a? Non verrà comunicato né conteggiato per l'imposta.`)) {
              await api("POST", `/api/guests/${g.id}/not-arrived`, {}); reload(); }
          } catch (e) { showError(e); }
        } }, "Non arrivato") : null))))))));
  if (params.ospite) guestDialog(D, +params.ospite, reload);
}

async function guestDialog(D, guestId, done, prefill) {
  const b = D.booking;
  let g = { guest_type: "16", tax_status: "ordinario", field_flags: {}, doc: {} };
  if (guestId) g = (await api("GET", `/api/guests/${guestId}`)).guest;
  if (prefill) g = { ...g, ...prefill.values, field_flags: { ...(g.field_flags || {}), ...prefill.flags }, doc: { ...(g.doc || {}), ...(prefill.values.doc || {}) } };
  const fl = g.field_flags || {};
  const leaders = D.guests.filter(x => ["17", "18"].includes(x.guest_type) && x.id !== guestId);
  const disabled = D.guests.filter(x => x.tax_status === "disabilita_grave" && x.id !== guestId);
  const f = h("div", { class: "form" },
    field("Tipologia di alloggiato", "guest_type", { type: "select", value: g.guest_type, options: GUEST_TYPES }),
    field("Capofamiglia / capogruppo", "leader_guest_id", { type: "select", value: g.leader_guest_id || "", options: [["", "—"], ...leaders.map(x => [x.id, `${x.surname} ${x.name}`])] }),
    field("Cognome", "surname", { value: g.surname, flag: fl.surname, maxlength: 60 }), field("Nome", "name", { value: g.name, flag: fl.name, maxlength: 40 }),
    field("Sesso (come richiesto dal tracciato)", "sex", { type: "select", value: g.sex || "", flag: fl.sex, options: [["", "—"], ["M", "M"], ["F", "F"]] }),
    field("Data di nascita", "birth_date", { type: "date", value: g.birth_date, flag: fl.birth_date }),
    codeField("Stato di nascita", "birth_state_code", "stati", g.birth_state_code, { flag: fl.birth_state_code }),
    codeField("Comune di nascita (se in Italia)", "birth_comune_code", "comuni", g.birth_comune_code, { flag: fl.birth_comune_code }),
    codeField("Cittadinanza", "citizenship_code", "stati", g.citizenship_code, { flag: fl.citizenship_code }),
    codeField("Stato di residenza (ROSS)", "res_state_code", "stati", g.res_state_code),
    codeField("Comune di residenza, se in Italia (ROSS)", "res_comune_code", "comuni", g.res_comune_code),
    field("Località di residenza estera (ROSS, max 30)", "res_place_text", { value: g.res_place_text, maxlength: 30 }),
    h("h3", { class: "wide" }, "Documento (solo capofamiglia, capogruppo, ospite singolo)"),
    codeField("Tipo documento", "doc.type", "documenti", (g.doc || {}).type, { flag: fl["doc.type"] }),
    field("Numero documento", "doc.number", { value: (g.doc || {}).number, flag: fl["doc.number"], maxlength: 25 }),
    codeField("Luogo di rilascio: comune italiano…", "doc.issue_place", "comuni", (g.doc || {}).issue_place, { flag: fl["doc.issue_place"] }),
    codeField("…oppure Stato estero di rilascio", "doc.issue_state", "stati", tableLooksState((g.doc || {}).issue_place) ? (g.doc || {}).issue_place : ""),
    h("h3", { class: "wide" }, "Permanenza prevista (se diversa dalla prenotazione)"),
    field("Arrivo previsto", "planned_arrival", { type: "date", value: g.planned_arrival }), field("Partenza prevista", "planned_departure", { type: "date", value: g.planned_departure }),
    h("h3", { class: "wide" }, "Posizione per l'imposta di soggiorno"),
    field("Posizione", "tax_status", { type: "select", value: g.tax_status, options: [["ordinario", "Ordinaria (minori valutati dalla data di nascita)"], ["residente", "Residente iscritto all'anagrafe di Alghero (non assoggettato)"],
      ["assistenza_ricoverati", "Assistenza a ricoverato nei nosocomi cittadini"], ["forze_servizio", "Polizia/Forze armate/Vigili del fuoco in servizio"],
      ["disabilita_grave", "Disabilità grave certificata (L.104 art.3 c.3)"], ["accompagnatore", "Accompagnatore di persona con disabilità grave"]] }),
    (D.prev_guests || []).length ? field("Prosegue il soggiorno di (prenotazione che termina il giorno dell'arrivo)", "continues_guest_id", { type: "select", wide: true,
      value: g.continues_guest_id || (!guestId ? ((D.prev_guests.find(x => g.surname && x.surname.toUpperCase() === g.surname.toUpperCase() && x.name.toUpperCase() === (g.name || "").toUpperCase() && x.birth_date === g.birth_date) || {}).id || "") : ""),
      options: [["", "— nessuno: soggiorno nuovo —"], ...D.prev_guests.map(x => [x.id, `${x.surname} ${x.name} · ${x.ref}`])],
      hint: "Se è la stessa persona che prolunga il soggiorno, le notti si sommano per il limite delle 7 notti consecutive dell'imposta." }) : null,
    field("Accompagna", "exemption_for_guest", { type: "select", value: g.exemption_for_guest || "", options: [["", "—"], ...disabled.map(x => [x.id, `${x.surname} ${x.name}`])] }),
    field("Dichiarazione/documentazione dell'esenzione acquisita", "exemption_doc_ok", { type: "checkbox", value: g.exemption_doc_ok, wide: true }),
    h("p", { class: "wide muted small" }, "Per le esenzioni non indicare diagnosi o dettagli sanitari: basta registrare che la dichiarazione prevista è stata acquisita."),
    field("Ho verificato questi dati confrontandoli con il documento originale", "verified", { type: "checkbox", wide: true, value: !!g.verified_at }));
  if (g.missing && g.missing.length) f.prepend(h("div", { class: "notice wide" }, "Mancano: " + g.missing.map(x => x.message).join(" · ")));
  if (g.doc_purged_at) f.prepend(h("div", { class: "notice info wide" }, `Dati del documento eliminati il ${itd(g.doc_purged_at)} dopo la ricevuta Alloggiati.`));
  let confirmedKey = null;
  const effBox = h("div", { class: "notice wide", role: "status", hidden: true });
  f.append(effBox);
  const IDENTITY = ["guest_type", "surname", "name", "sex", "birth_date", "birth_state_code", "birth_comune_code", "citizenship_code", "doc.type", "doc.number", "doc.issue_place", "doc.issue_state"];
  const markChanged = (e) => {
    // Dati anagrafici o documentali modificati: la conferma di verifica precedente non vale più, va rifatta consapevolmente.
    const vb = f.querySelector('input[name="verified"]');
    if (vb && vb.checked && g.verified_at && IDENTITY.includes(e.target.name)) {
      vb.checked = false;
      if (!f.querySelector(".reverify")) vb.closest("label").after(h("p", { class: "small reverify wide" }, "Hai modificato dati anagrafici o del documento: ricontrolla con il documento originale e spunta di nuovo la verifica."));
    }
  };
  f.addEventListener("input", markChanged); f.addEventListener("change", markChanged);
  f.addEventListener("input", (e) => { if (e.target.name === "verified") return; if (confirmedKey) { confirmedKey = null; effBox.hidden = true; const btn = $("#dlg-form .dlg-foot button.primary"); if (btn) btn.textContent = "Salva"; } });
  const buttons = [{ label: "Chiudi" }];
  if (guestId && !["caricamento_dichiarato", "esito_registrato"].includes(g.alloggiati_status)) buttons.push({ label: "Elimina ospite", danger: true, onClick: async () => {
    const reason = prompt("Motivo dell'eliminazione:"); if (!reason) return false;
    if (!await confirmEffects("Eliminare l'ospite?", guestId, "delete", { reason }, null, "Elimina", true)) return;
    await api("POST", `/api/guests/${guestId}/delete`, { reason }); toast("Ospite eliminato."); done();
  } });
  if (guestId && g.stay_arrival) buttons.push({ label: "Correggi permanenza effettiva", onClick: () => { stayDialog(g, done); return true; } });
  buttons.push({ label: "Salva", primary: true, onClick: async (form) => {
    const d = formData(f);
    const flags = prefill ? { ...prefill.flags } : {};
    if (prefill) for (const k of Object.keys(prefill.flags)) {
      const before = k.startsWith("doc.") ? (prefill.values.doc || {})[k.slice(4)] : prefill.values[k];
      if (String(before ?? "") !== String(d[k] ?? "")) flags[k] = d[k] ? "corretto" : "mancante";
    }
    const issue = d["doc.issue_place"] || d["doc.issue_state"];
    const body = { guest_type: d.guest_type, leader_guest_id: d.leader_guest_id ? +d.leader_guest_id : null, surname: d.surname, name: d.name, sex: d.sex,
      birth_date: d.birth_date, birth_state_code: d.birth_state_code, birth_comune_code: d.birth_comune_code, citizenship_code: d.citizenship_code,
      res_state_code: d.res_state_code, res_comune_code: d.res_comune_code, res_place_text: d.res_place_text,
      planned_arrival: d.planned_arrival || null, planned_departure: d.planned_departure || null, tax_status: d.tax_status,
      exemption_for_guest: d.exemption_for_guest ? +d.exemption_for_guest : null, exemption_doc_ok: d.exemption_doc_ok,
      continues_guest_id: d.continues_guest_id ? +d.continues_guest_id : null,
      field_flags: flags, version: g.version, data_origin: prefill ? "documento" : (g.data_origin || "manuale") };
    if (!["19", "20"].includes(d.guest_type)) body.doc = { type: d["doc.type"], number: d["doc.number"], issue_place: issue };
    const key = JSON.stringify(body);
    if (key !== confirmedKey) {
      const p = guestId ? await api("POST", `/api/guests/${guestId}/preview`, { action: "save", data: body })
        : await api("POST", `/api/bookings/${b.id}/guests/preview`, body);
      if (guestId ? p.has_effects : p.communications_affected) {
        confirmedKey = key;
        effBox.replaceChildren(h("strong", {}, "Prima di salvare, verifica le conseguenze:"), h("ul", {}, p.summary.map(x => h("li", {}, x))),
          h("p", { class: "small" }, "Premi «Conferma e salva» per procedere, oppure modifica i dati."));
        effBox.hidden = false;
        const btn = form.querySelector(".dlg-foot button.primary"); if (btn) btn.textContent = "Conferma e salva";
        effBox.scrollIntoView({ block: "nearest" });
        return false;
      }
    }
    const r = guestId ? await api("PUT", `/api/guests/${guestId}`, body) : await api("POST", `/api/bookings/${b.id}/guests`, body);
    if (d.verified && !r.guest.verified_at) await api("POST", `/api/guests/${r.guest.id}/verify`, {});
    if (r.duplicates && r.duplicates.length) toast(`Attenzione: possibile duplicato in ${r.duplicates.map(x => x.ref).join(", ")} (nessuna unione automatica).`, true);
    toast("Ospite salvato."); done && done(r.guest);
  } });
  openDialog(guestId ? `Ospite: ${g.surname} ${g.name}` : "Nuovo ospite", f, buttons);
}
/* Anteprima delle conseguenze (simulata sul server e annullata) prima di un'azione sull'ospite. */
async function confirmEffects(title, guestId, action, data, intro, okLabel = "Conferma", danger = false) {
  const p = await api("POST", `/api/guests/${guestId}/preview`, { action, data });
  const lines = [intro ? h("p", {}, intro) : null, h("p", {}, h("strong", {}, "Conseguenze:")), h("ul", {}, p.summary.map(x => h("li", {}, x)))].filter(Boolean);
  return confirmDialog(title, lines, okLabel, danger);
}
function tableLooksState(code) { return code && code.startsWith("100"); }

function stayDialog(g, done) {
  const f = h("div", { class: "form" }, field("Arrivo effettivo", "stay_arrival", { type: "date", value: g.stay_arrival }),
    field("Partenza effettiva", "stay_departure", { type: "date", value: g.stay_departure }), field("Motivo", "reason", { wide: true }));
  openDialog("Permanenza effettiva di un solo ospite", h("div", {}, f, h("p", { class: "muted small" }, "Le date degli altri ospiti non cambiano. Se i dati erano già comunicati verrà aperta una rettifica.")),
    [{ label: "Annulla" }, { label: "Salva", primary: true, onClick: async () => {
      const data = formData(f);
      if (!await confirmEffects("Conseguenze della modifica", g.id, "stay", data)) return;
      await api("POST", `/api/guests/${g.id}/stay`, data); toast("Permanenza aggiornata."); done(); } }]);
}
function guestDepartureDialog(g, done, booking) {
  const end = booking && booking.departure < todayIso() ? booking.departure : todayIso();
  const f = h("div", { class: "form" }, field("Data di partenza", "date", { type: "date", value: end, max: todayIso() }));
  openDialog(`Partenza di ${g.surname} ${g.name}`, f, [{ label: "Annulla" }, { label: "Registra partenza", primary: true, onClick: async () => {
    const data = formData(f);
    if (!await confirmEffects("Conseguenze della partenza", g.id, "departure", data)) return;
    await api("POST", `/api/guests/${g.id}/departure`, data); toast("Partenza registrata."); done(); } }]);
}

function checkinDialog(D, done) {
  const waiting = D.guests.filter(g => g.presence === "prevista");
  if (!waiting.length) { toast("Inserire prima gli ospiti (manualmente o da documento).", true); return; }
  const rows_ = waiting.map(g => {
    const cb = h("input", { type: "checkbox", checked: true, "aria-label": `${g.surname} ${g.name} arrivato` });
    const dt = h("input", { type: "date", value: todayIso(), max: todayIso(), "aria-label": "Data arrivo" });
    const tm = h("input", { type: "time", value: new Date().toTimeString().slice(0, 5), "aria-label": "Ora arrivo" });
    return { g, cb, dt, tm, row: h("tr", {}, h("td", {}, cb), h("td", {}, `${g.surname} ${g.name}`, g.verified_at ? "" : h("div", {}, badge("dati da verificare", "warn"))), h("td", {}, dt), h("td", {}, tm)) };
  });
  openDialog("Chi è arrivato?", h("div", {}, h("p", { class: "small" }, "Seleziona solo le persone effettivamente arrivate. Chi arriva più tardi si registra in seguito."),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Ospite"), h("th", {}, "Data"), h("th", {}, "Ora"))), h("tbody", {}, rows_.map(r => r.row))),
    h("p", { class: "muted small" }, "L'ora di arrivo serve a calcolare il termine per Alloggiati Web (promemoria indicativo).")),
    [{ label: "Annulla" }, { label: "Registra arrivi", primary: true, onClick: async () => {
      const arrivals = rows_.filter(r => r.cb.checked).map(r => ({ guest_id: r.g.id, date: r.dt.value, time: r.tm.value }));
      await api("POST", `/api/bookings/${D.booking.id}/checkin`, { version: D.booking.version, arrivals });
      toast("Arrivi registrati."); done(); } }]);
}

async function checkoutDialog(D, done) {
  const s = await api("GET", `/api/bookings/${D.booking.id}/checkout-summary`);
  const bal = s.balances;
  const dep = D.booking.departure < todayIso() ? D.booking.departure : todayIso();
  const dt = h("input", { type: "date", value: dep, max: todayIso(), "aria-label": "Data partenza" });
  openDialog("Riepilogo di partenza", h("div", {},
    h("h3", {}, "Permanenze"), h("ul", {}, s.guests.map(g => h("li", {}, `${g.surname} ${g.name}: ${PRESENCE_IT[g.presence]}${g.stay_arrival ? ` dal ${itd(g.stay_arrival)}` : ""}${g.stay_departure ? ` al ${itd(g.stay_departure)}` : ""}`))),
    h("h3", {}, "Importi"), h("dl", { class: "kv" },
      h("dt", {}, "Saldo soggiorno"), h("dd", { class: "money" }, eur(bal.stay.balance_cents)),
      h("dt", {}, "Imposta dovuta"), h("dd", { class: "money" }, `${eur(bal.tax.due_cents)} (${bal.tax.due_source})`),
      h("dt", {}, "Imposta ancora da incassare"), h("dd", { class: "money" }, eur(bal.tax.residual_cents)),
      h("dt", {}, "Cauzione trattenuta"), h("dd", { class: "money" }, eur(bal.deposit.held_cents))),
    s.open_items.length ? h("div", {}, h("h3", {}, "Ancora aperto"), h("ul", {}, s.open_items.map(i => h("li", {}, i.text)))) : null,
    h("label", {}, "Data di partenza dei presenti"), dt,
    h("p", { class: "muted small" }, "La partenza si può registrare anche con un saldo aperto: il debito resta visibile in Oggi.")),
    [{ label: "Annulla" }, { label: "Registra partenza", primary: true, onClick: async () => {
      let extend_ack = false;
      if (dt.value > D.booking.departure) {
        const n = nightsBetween(D.booking.departure, dt.value);
        extend_ack = await confirmDialog("Proroga del soggiorno?", [`La prenotazione finiva il ${itd(D.booking.departure)}: con partenza il ${itd(dt.value)} il soggiorno si allunga di ${n} notti.`,
          "Il programma controlla che il calendario sia libero ma NON aggiorna il prezzo concordato: va modificato a parte."], "Confermo la proroga");
        if (!extend_ack) return;
      }
      await api("POST", `/api/bookings/${D.booking.id}/checkout`, { version: D.booking.version, date: dt.value, extend_ack }); toast("Partenza registrata."); done(); } }]);
}

/* ---- Pagamenti ---- */
function tabPay(box, D, reload) {
  const bal = D.balances;
  box.append(h("div", { class: "grid" },
    h("section", { class: "panel" }, h("h2", {}, "Soggiorno"), h("dl", { class: "kv" },
      h("dt", {}, "Corrispettivo concordato"), h("dd", { class: "money" }, eur(bal.stay.agreed_cents)),
      h("dt", {}, "Incassato per il soggiorno"), h("dd", { class: "money" }, eur(bal.stay.received_cents)),
      h("dt", {}, "Rimborsato"), h("dd", { class: "money" }, eur(bal.stay.refunded_cents)),
      h("dt", {}, h("strong", {}, "Saldo da incassare")), h("dd", { class: "money" }, h("strong", {}, eur(bal.stay.balance_cents))))),
    h("section", { class: "panel" }, h("h2", {}, "Imposta di soggiorno"), h("dl", { class: "kv" },
      h("dt", {}, "Dovuta"), h("dd", { class: "money" }, `${eur(bal.tax.due_cents)} · ${bal.tax.due_source}`),
      h("dt", {}, "Incassata"), h("dd", { class: "money" }, eur(bal.tax.collected_cents)),
      h("dt", {}, "Rimborsata"), h("dd", { class: "money" }, eur(bal.tax.refunded_cents)),
      h("dt", {}, "Gestita da terzi"), h("dd", { class: "money" }, eur(bal.tax.third_party_cents)),
      h("dt", {}, h("strong", {}, "Da incassare")), h("dd", { class: "money" }, h("strong", {}, eur(bal.tax.residual_cents)))),
      bal.tax.refusal_note ? h("div", { class: "notice" }, "Rifiuto annotato: " + bal.tax.refusal_note + " — l'imposta resta dovuta.") : null),
    h("section", { class: "panel" }, h("h2", {}, "Cauzione"), h("dl", { class: "kv" },
      h("dt", {}, "Richiesta"), h("dd", { class: "money" }, eur(bal.deposit.requested_cents)),
      h("dt", {}, "Ricevuta"), h("dd", { class: "money" }, eur(bal.deposit.received_cents)),
      h("dt", {}, "Restituita"), h("dd", { class: "money" }, eur(bal.deposit.returned_cents)),
      h("dt", {}, "Trattenuta"), h("dd", { class: "money" }, eur(bal.deposit.held_cents))))));
  box.append(h("div", { class: "row", style: "margin:12px 0" },
    h("button", { type: "button", class: "primary", onclick: () => movementDialog(D, "entrata", reload) }, "Registra incasso"),
    h("button", { type: "button", onclick: () => movementDialog(D, "uscita", reload) }, "Registra restituzione o rimborso"),
    h("button", { type: "button", onclick: () => movementDialog(D, "terzi", reload) }, "Imposta gestita da terzi")));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Movimenti"), D.movements.length ? h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Data", "Tipo", "Importo", "Ripartizione", "Modalità", "Causale", ""].map(x => h("th", {}, x)))),
    h("tbody", {}, D.movements.map(m => h("tr", {}, h("td", {}, itd(m.op_date)), h("td", {}, m.reverses_id ? "Storno" : m.direction),
      h("td", { class: "num money" }, (m.reverses_id ? "−" : "") + eur(m.amount_cents)),
      h("td", { class: "small" }, m.allocations.map(a => `${a.category} ${eur(a.amount_cents)}`).join(" · ")),
      h("td", {}, m.method), h("td", {}, m.causale, m.reference ? h("div", { class: "muted small" }, m.reference) : null),
      h("td", {}, !m.reverses_id && !m.reversed_by ? h("button", { type: "button", onclick: async () => {
        const reason = prompt("Motivo dello storno (il movimento resta registrato):"); if (!reason) return;
        try { await api("POST", `/api/movements/${m.id}/reverse`, { reason, uid: newUid() }); toast("Storno registrato."); reload(); } catch (e) { showError(e); }
      } }, "Storna") : (m.reversed_by ? badge("stornato", "grey") : null))))))) : h("p", { class: "muted" }, "Nessun movimento.")));
}

function movementDialog(D, direction, done) {
  const uid = newUid(); // chiave di idempotenza: un doppio clic non duplica l'incasso
  const titles = { entrata: "Registra incasso", uscita: "Restituzione o rimborso", terzi: "Imposta gestita da terzi" };
  const f = h("div", { class: "form" },
    field("Data", "op_date", { type: "date", value: todayIso() }), field("Importo totale", "amount", { inputmode: "decimal", placeholder: "es. 612,00" }),
    direction !== "terzi" ? field("Modalità", "method", { type: "select", options: [["contanti", "Contanti"], ["bonifico", "Bonifico"], ["carta", "Carta"], ["pos", "POS"], ["assegno", "Assegno"], ["altro", "Altro"]] }) : null,
    field("Causale", "causale", { value: direction === "entrata" ? "Acconto" : direction === "uscita" ? "Restituzione cauzione" : "Imposta riscossa da terzi" }),
    field(direction === "terzi" ? "Riferimento del documento che lo attesta (obbligatorio)" : "Riferimento (facoltativo)", "reference", { wide: true }),
    h("h3", { class: "wide" }, "Ripartizione (la somma deve coincidere con l'importo)"),
    direction !== "terzi" ? field("Soggiorno ed extra", "a_soggiorno", { inputmode: "decimal" }) : null,
    field("Imposta di soggiorno", "a_imposta", { inputmode: "decimal" }),
    direction !== "terzi" ? field("Cauzione", "a_cauzione", { inputmode: "decimal" }) : null);
  openDialog(titles[direction], f, [{ label: "Annulla" }, { label: "Registra", primary: true, onClick: async () => {
    const d = formData(f);
    const allocations = ["soggiorno", "imposta", "cauzione"].filter(c => d["a_" + c]).map(c => ({ category: c, amount: d["a_" + c] }));
    const r = await api("POST", "/api/movements", { uid, booking_id: D.booking.id, direction, op_date: d.op_date, amount: d.amount, method: d.method || "altro", causale: d.causale, reference: d.reference, allocations });
    toast(r.movement.duplicate_request ? "Movimento già registrato: nessun duplicato creato." : "Movimento registrato."); done();
  } }]);
}

/* ---- Imposta ---- */
function tabTax(box, D, reload) {
  const t = D.tax;
  box.append(h("section", { class: "panel" }, h("h2", {}, t.kind === "consuntivo" ? "Calcolo su permanenze effettive" : "Stima su permanenze previste (preventivo)"),
    h("p", { class: "money", style: "font-size:18px" }, "Totale: ", h("strong", {}, eur(t.total_cents)), " ",
      t.final ? badge("definitivo", "ok") : badge(t.total_cents === null ? "DA VERIFICARE" : "non definitivo", "warn")),
    t.issues.length ? h("div", { class: "notice" }, h("ul", {}, t.issues.map(i => h("li", {}, i)))) : null,
    ...t.guests.map(g => h("details", { open: t.guests.length <= 3 }, h("summary", {}, `${g.label}: ${g.explanation}`),
      h("div", { class: "tablewrap" }, h("table", { class: "night-table" }, h("thead", {}, h("tr", {}, ["Notte", "N. consecutiva", "Esito", "Motivo", "Regola", "Tariffa", "Importo"].map(x => h("th", {}, x)))),
        h("tbody", {}, g.lines.map(l => h("tr", {}, h("td", {}, itd(l.night)), h("td", { class: "num" }, l.consecutive_index), h("td", {}, l.cls.replace("_", " ")),
          h("td", { class: "small" }, l.reason || ""), h("td", {}, l.rule_id ? `v.${l.rule_id} (${l.rule_status})` : "—"), h("td", { class: "num" }, l.rate_cents ? eur(l.rate_cents) : "—"),
          h("td", { class: "num" }, eur(l.amount_cents)))))))))));
  const c = D.consolidated;
  box.append(h("section", { class: "panel" }, h("h2", {}, "Consolidamento e quietanze"),
    c ? h("p", {}, `Conteggio consolidato il ${itdt(c.created_at)}: ${eur(c.total_cents)}${c.reason ? " — rettifica: " + c.reason : ""}`) : h("p", { class: "muted" }, "Nessun conteggio consolidato. Si consolida a soggiorno concluso, con calcolo definitivo."),
    h("div", { class: "row" },
      h("button", { type: "button", disabled: !t.final, onclick: async () => {
        let reason = null; if (c) { reason = prompt("Esiste già un conteggio consolidato. Motivo della rettifica:"); if (!reason) return; }
        else if (!(await confirmDialog("Consolidare il conteggio?", [`Imposta definitiva: ${eur(t.total_cents)}.`, "Dopo il consolidamento ogni modifica richiede una rettifica motivata e le regole usate non si possono più cambiare."], "Consolida"))) return;
        try { await api("POST", `/api/bookings/${D.booking.id}/tax/consolidate`, { reason }); toast("Conteggio consolidato."); reload(); } catch (e) { showError(e); }
      } }, c ? "Consolida rettifica" : "Consolida conteggio"),
      h("button", { type: "button", onclick: async () => { try { await api("POST", `/api/bookings/${D.booking.id}/receipt`, {}); toast("Quietanza emessa."); reload(); } catch (e) { showError(e); } } }, "Emetti quietanza dell'imposta incassata"),
      h("button", { type: "button", onclick: async () => {
        const note = prompt("Annota il rifiuto di pagamento (l'imposta resta dovuta; lasciare vuoto per rimuovere):", D.booking.tax_refusal_note || "");
        if (note === null) return; await api("POST", `/api/bookings/${D.booking.id}/tax-refusal`, { note }); reload();
      } }, "Annota rifiuto di pagamento")),
    D.receipts.length ? h("ul", { class: "plain" }, D.receipts.map(r => h("li", {}, `Quietanza n. ${r.number}/${r.year} del ${itd(r.issued_on)} · ${eur(r.amount_cents)} `,
      badge(r.status, r.status === "emessa" ? "ok" : "err"), " ", h("button", { type: "button", class: "link", onclick: () => openUrl(`/api/receipts/${r.id}/pdf`) }, "PDF"), " ",
      r.status === "emessa" ? h("button", { type: "button", class: "link", onclick: async () => { const reason = prompt("Motivo dell'annullamento (il numero non verrà riutilizzato):"); if (!reason) return; await api("POST", `/api/receipts/${r.id}/cancel`, { reason }); reload(); } }, "Annulla") : null))) : null));
}

function tabObl(box, D) {
  box.append(h("section", { class: "panel" }, h("h2", {}, "Da completare"), D.open_items.length ? h("ul", { class: "plain" }, D.open_items.map(i => h("li", {}, badge(i.kind, "warn"), " ", h("a", { href: i.link }, i.text)))) : h("p", { class: "muted" }, "Nulla di aperto.")));
  box.append(h("section", { class: "panel" }, h("h2", {}, "Esportazioni che includono questa prenotazione"),
    D.exports.length ? h("ul", { class: "plain" }, D.exports.map(x => h("li", {}, `Lotto ${x.id} · ${x.kind} · ${itdt(x.created_at)} · `, badge(x.status.replace(/_/g, " "), x.status === "esito_registrato" ? "ok" : x.status === "superato" ? "grey" : "info")))) : h("p", { class: "muted" }, "Nessuna."),
    h("h3", {}, "Rettifiche"), D.corrections.length ? h("ul", { class: "plain" }, D.corrections.map(c => h("li", {}, badge(c.status, c.status === "aperta" ? "err" : "ok"), " ", c.reason, c.resolution ? h("div", { class: "muted small" }, "Gestita: " + c.resolution) : null))) : h("p", { class: "muted" }, "Nessuna.")));
}
