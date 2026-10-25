/* Manutenzione: lavori da fare nell'appartamento (anche periodici), apparecchi della casa, rubrica delle ditte */
"use strict";
const MNT_STATUS_KIND = { da_fare: "warn", in_corso: "info", risolto: "ok", annullato: "grey" };
const MNT_PRIO_KIND = { urgente: "err", normale: "info", bassa: "grey" };
const MNT_PRIO = [["urgente", "Urgente"], ["normale", "Normale"], ["bassa", "Bassa"]];
const MNT_NOTE_IT = { nota: "Nota", stato: "Stato", modifica: "Modifica", allegato: "Allegato" };
const MNT_FILES = ".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf";
const MNT_WARRANTY = { valida: ["Garanzia valida", "ok"], in_scadenza: ["Garanzia in scadenza", "warn"], scaduta: ["Garanzia scaduta", "grey"] };
async function uploadMntFiles(jobId, files, base = "/api/maintenance") {
  for (const file of files) {
    try { await api("POST", `${base}/${jobId}/attachments`, file, { raw: true, headers: { "X-Filename": encodeURIComponent(file.name).slice(0, 80), "Content-Type": "application/octet-stream" } }); }
    catch (e) { showError(e); return false; }
  }
  if (files.length) toast(files.length === 1 ? "Allegato salvato (cifrato)." : `${files.length} allegati salvati (cifrati).`);
  return true;
}
function centsInput(c) { return c === null || c === undefined ? "" : (c / 100).toFixed(2).replace(".", ","); }
function mntDue(j) {
  if (!j.due_date) return h("span", { class: "muted" }, "—");
  return h("span", {}, itd(j.due_date), " ", j.overdue ? badge("Scaduto", "err") : j.due_soon ? badge("In scadenza", "warn") : null);
}
function mntTabs(active) {
  return h("div", { class: "tabs", role: "tablist" }, [["lavori", "Lavori", "#/manutenzione"], ["apparecchi", "Apparecchi della casa", "#/manutenzione/apparecchi"],
    ["ditte", "Ditte e tecnici", "#/manutenzione/ditte"]].map(([k, l, href]) =>
    h("button", { type: "button", role: "tab", "aria-selected": String(k === active), onclick: () => location.hash = href }, l)));
}
function nJobs(x) { return `${x.n_jobs}` + (x.open_jobs ? ` (${x.open_jobs} ${x.open_jobs === 1 ? "aperto" : "aperti"})` : ""); }
function warrantyBadge(a) { const w = MNT_WARRANTY[a.warranty_status]; return w ? badge(w[0], w[1]) : null; }
function searchBox(main, placeholder) {
  const s = h("input", { type: "search", placeholder, "aria-label": placeholder, style: "width:auto;min-width:240px" });
  s.addEventListener("input", () => { const q = s.value.trim().toLowerCase(); $$("tbody tr", main).forEach(tr => { tr.hidden = !!q && !tr.dataset.text.includes(q); }); });
  return s;
}
function jobsTable(jobs, opts = {}) {
  return h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Lavoro", "Priorità", "Scadenza", "Stato", opts.noAsset ? null : "Apparecchio", opts.noContractor ? null : "Ditta / tecnico", "Preventivo", "Costo", "Foto"].filter(Boolean).map(x => h("th", {}, x)))),
    h("tbody", {}, jobs.map(j => h("tr", { dataset: { text: [j.title, j.contractor, j.description, j.asset_name].join(" ").toLowerCase() } },
      h("td", {}, h("a", { href: `#/manutenzione/${j.id}` }, j.title), j.recur_label ? h("div", { class: "muted small" }, "↻ " + j.recur_label) : null),
      h("td", {}, badge(j.priority_label, MNT_PRIO_KIND[j.priority])),
      h("td", {}, mntDue(j)),
      h("td", {}, badge(j.status_label, MNT_STATUS_KIND[j.status]), j.resolved_at ? h("div", { class: "muted small" }, itd(j.resolved_at)) : null),
      opts.noAsset ? null : h("td", {}, j.asset_id ? h("a", { href: `#/manutenzione/apparecchi/${j.asset_id}` }, j.asset_name) : ""),
      opts.noContractor ? null : h("td", {}, j.contractor_id ? h("a", { href: `#/manutenzione/ditte/${j.contractor_id}` }, j.contractor) : (j.contractor || "")),
      h("td", { class: "num" }, j.quote_cents === null ? "" : eur(j.quote_cents)),
      h("td", { class: "num" }, j.cost_cents === null ? "" : eur(j.cost_cents)),
      h("td", { class: "num" }, j.n_attachments || ""))))));
}
function attachmentsPanel(title, hint, list, uploadBase, ownerId, reload) {
  const fi = h("input", { type: "file", accept: MNT_FILES, hidden: true, multiple: true });
  fi.addEventListener("change", async () => { if (await uploadMntFiles(ownerId, fi.files, uploadBase)) reload(); });
  return h("section", { class: "panel" }, h("h2", {}, title, h("span", { class: "count" }, String(list.length))),
    h("div", { class: "row" }, fi, h("button", { type: "button", onclick: () => fi.click() }, "Aggiungi foto o PDF")),
    h("p", { class: "muted small" }, hint),
    list.length ? h("div", { class: "thumbs" }, list.map(a => h("div", { class: "att" },
      h("button", { type: "button", class: "thumb", title: a.filename, onclick: () => openUrl(`/api/attachments/${a.id}`) },
        a.mime.startsWith("image/") ? h("img", { src: `/api/attachments/${a.id}`, alt: a.filename, loading: "lazy" }) : h("span", { class: "pdf" }, "PDF"),
        h("span", { class: "small" }, a.filename)),
      h("button", { type: "button", class: "link small", "aria-label": `Rimuovi ${a.filename}`, onclick: async () => {
        if (!await confirmDialog("Rimuovere l'allegato?", [`«${a.filename}» verrà eliminato definitivamente.`], "Rimuovi", true)) return;
        try { await api("POST", `${uploadBase}/${ownerId}/attachments/${a.id}/delete`, {}); toast("Allegato rimosso."); reload(); } catch (e) { showError(e); }
      } }, "Rimuovi")))) : null);
}

/* ---------------- Lavori ---------------- */
addRoute(/^\/manutenzione$/, async (main, _m, params) => {
  const which = params.stato || "aperti";
  const r = await api("GET", `/api/maintenance?stato=${which}`);
  const c = r.counts;
  page(main, "Manutenzione", `${c.da_fare} da fare · ${c.in_corso} in corso · ${c.risolto} risolti`,
    [h("button", { type: "button", class: "primary", onclick: () => jobDialog(null, (j) => location.hash = `#/manutenzione/${j.id}`) }, "Nuovo lavoro")]);
  main.append(mntTabs("lavori"));
  const sel = h("select", { "aria-label": "Quali lavori", style: "width:auto" },
    [["aperti", "Lavori aperti"], ["periodici", "Lavori periodici (prossimi)"], ["chiusi", "Risolti e annullati"], ["tutti", "Tutti"]].map(([v, l]) => h("option", { value: v, selected: v === which }, l)));
  sel.addEventListener("change", () => location.hash = `#/manutenzione?stato=${sel.value}`);
  main.append(h("div", { class: "row", style: "margin-bottom:10px" }, sel, searchBox(main, "Cerca lavoro, ditta, apparecchio"), h("span", { class: "spacer" }),
    h("span", { class: "small muted" }, `Spesi nel ${r.year} per lavori risolti: `, h("strong", {}, eur(r.spent_year_cents)))));
  if (!r.jobs.length) {
    main.append(h("p", { class: "muted" }, which === "aperti" ? "Nessun lavoro aperto: la casa è in ordine." : which === "periodici" ? "Nessun lavoro periodico: si crea scegliendo «Si ripete» nel lavoro." : "Nessun lavoro."));
    return;
  }
  main.append(jobsTable(r.jobs));
}, "manutenzione");

addRoute(/^\/manutenzione\/(\d+)$/, async (main, m) => {
  const { job: j } = await api("GET", `/api/maintenance/${m[1]}`);
  const reload = () => render();
  page(main, j.title, j.status_label, [
    h("a", { class: "btn", href: "#/manutenzione" }, "‹ Tutti i lavori"),
    h("button", { type: "button", onclick: () => jobDialog(j, reload) }, "Modifica"),
    ...j.next_statuses.map(s => h("button", { type: "button", class: s.status === "risolto" ? "primary" : "",
      onclick: () => statusDialog(j, s, reload) }, s.label))]);
  const g = h("div", { class: "grid" });
  main.append(g);
  const ci = j.contractor_info;
  g.append(h("section", { class: "panel" }, h("h2", {}, "Dettagli"),
    h("dl", { class: "kv" },
      h("dt", {}, "Stato"), h("dd", {}, badge(j.status_label, MNT_STATUS_KIND[j.status])),
      h("dt", {}, "Priorità"), h("dd", {}, badge(j.priority_label, MNT_PRIO_KIND[j.priority])),
      h("dt", {}, "Scadenza"), h("dd", {}, mntDue(j)),
      h("dt", {}, "Si ripete"), h("dd", {}, !j.recur_label ? "No" : j.next_job || j.status === "annullato" ? `↻ ${j.recur_label}` : `↻ ${j.recur_label} (il prossimo si crea alla risoluzione)`),
      h("dt", {}, "Apparecchio"), h("dd", {}, j.asset ? h("a", { href: `#/manutenzione/apparecchi/${j.asset.id}` }, j.asset.name) : "—"),
      h("dt", {}, "Ditta / tecnico"), h("dd", {}, ci ? [h("a", { href: `#/manutenzione/ditte/${ci.id}` }, ci.name), ci.phone ? h("div", { class: "small" }, "☎ ", h("a", { href: `tel:${ci.phone}` }, ci.phone)) : null] : (j.contractor || "—")),
      h("dt", {}, "Preventivo"), h("dd", { class: "money" }, j.quote_cents === null ? "—" : eur(j.quote_cents)),
      h("dt", {}, "Costo finale"), h("dd", { class: "money" }, j.cost_cents === null ? "—" : eur(j.cost_cents)),
      h("dt", {}, "Aperto il"), h("dd", {}, itdt(j.created_at)),
      j.resolved_at ? [h("dt", {}, "Risolto il"), h("dd", {}, itdt(j.resolved_at))] : null,
      j.prev_job ? [h("dt", {}, "Intervento precedente"), h("dd", {}, h("a", { href: `#/manutenzione/${j.prev_job.id}` }, j.prev_job.resolved_at ? `risolto il ${itd(j.prev_job.resolved_at)}` : j.prev_job.status_label))] : null,
      j.next_job ? [h("dt", {}, "Prossimo intervento"), h("dd", {}, h("a", { href: `#/manutenzione/${j.next_job.id}` }, j.next_job.due_date ? `entro il ${itd(j.next_job.due_date)}` : j.next_job.status_label), " ", badge(j.next_job.status_label, MNT_STATUS_KIND[j.next_job.status]))] : null),
    j.description ? h("p", { class: "pre" }, j.description) : h("p", { class: "muted" }, "Nessuna descrizione."),
    h("p", { class: "muted small" }, "Il registro non blocca il calendario e i costi non entrano nei conti dei soggiorni.")));

  const noteBox = h("textarea", { "aria-label": "Nuova nota", placeholder: "es. chiamato l'idraulico, viene martedì" });
  g.append(h("section", { class: "panel" }, h("h2", {}, "Diario dell'avanzamento"),
    noteBox, h("div", { class: "row", style: "margin:6px 0 10px" }, h("button", { type: "button", onclick: async () => {
      try { await api("POST", `/api/maintenance/${j.id}/notes`, { text: noteBox.value }); toast("Nota aggiunta."); reload(); } catch (e) { showError(e); }
    } }, "Aggiungi nota")),
    h("ul", { class: "plain" }, j.notes.map(n => h("li", {}, h("div", { class: "muted small" }, itdt(n.at), " · ", MNT_NOTE_IT[n.kind] || n.kind),
      h("div", { class: "pre" }, n.text))))));
  g.append(attachmentsPanel("Foto e allegati", "JPG, PNG o PDF fino a 15 MB: foto del guasto, preventivo, fattura.", j.attachments, "/api/maintenance", j.id, reload));
}, "manutenzione");

async function jobDialog(j, done) {
  j = j || {};
  let O;
  try { O = await api("GET", "/api/maintenance/options"); } catch (e) { showError(e); return; }
  const none = [["", "— nessuno —"]];
  const f = h("div", { class: "form" },
    field("Che cosa c'è da fare", "title", { value: j.title, required: true, wide: true, maxlength: 120, placeholder: "es. Rubinetto della doccia che gocciola" }),
    field("Descrizione", "description", { type: "textarea", value: j.description, wide: true }),
    field("Priorità", "priority", { type: "select", value: j.priority || "normale", options: MNT_PRIO }),
    field("Da fare entro", "due_date", { type: "date", value: j.due_date || "", hint: "obbligatoria se si ripete" }),
    field("Si ripete", "recur_months", { type: "select", value: j.recur_months || "", options: [["", "No, una volta sola"], ...O.recur], hint: "es. pulizia filtri ogni 6 mesi" }),
    field("Apparecchio", "asset_id", { type: "select", value: j.asset_id || "", options: [...none, ...O.assets.map(a => [a.id, a.name])], hint: O.assets.length ? "facoltativo" : "aggiungili in «Apparecchi della casa»" }),
    field("Ditta / tecnico dalla rubrica", "contractor_id", { type: "select", value: j.contractor_id || "", options: [...none, ...O.contractors.map(c => [c.id, c.name + (c.specialty ? ` (${c.specialty})` : "")])] }),
    field("…oppure nuova ditta", "contractor_new", { maxlength: 120, placeholder: "nome: viene aggiunta alla rubrica" }),
    field("Preventivo", "quote_cents", { value: centsInput(j.quote_cents), inputmode: "decimal", placeholder: "es. 120,00" }),
    j.id ? field("Costo finale", "cost_cents", { value: centsInput(j.cost_cents), inputmode: "decimal", placeholder: "0,00" }) : null);
  const fi = h("input", { type: "file", accept: MNT_FILES, hidden: true, multiple: true });
  const chosen = h("span", { class: "small muted" }, "Nessun file scelto");
  fi.addEventListener("change", () => { chosen.textContent = fi.files.length ? [...fi.files].map(x => x.name).join(", ") : "Nessun file scelto"; });
  const photos = h("div", { class: "field wide" }, h("label", {}, "Foto o PDF", h("span", { class: "muted" }, " · facoltativo: guasto, preventivo, fattura")),
    h("div", { class: "row" }, fi, h("button", { type: "button", onclick: () => fi.click() }, "Aggiungi foto o PDF"), chosen));
  openDialog(j.id ? "Modifica lavoro" : "Nuovo lavoro di manutenzione", h("div", {}, f, photos), [{ label: "Annulla" }, {
    label: "Salva", primary: true, onClick: async () => {
      const d = formData(f);
      if (d.contractor_new) { d.contractor = d.contractor_new; delete d.contractor_id; }
      delete d.contractor_new;
      const r = j.id ? await api("PUT", `/api/maintenance/${j.id}`, { ...d, version: j.version })
        : await api("POST", "/api/maintenance", d);
      toast("Lavoro salvato.");
      await uploadMntFiles(r.job.id, fi.files);  // il lavoro resta salvato anche se un file viene rifiutato
      done(r.job);
    } }]);
}

function statusDialog(j, s, done) {
  const needs = s.status === "annullato" || s.status === "da_fare";
  const f = h("div", { class: "form" },
    field(needs ? (s.status === "annullato" ? "Perché non serve più" : "Perché si riapre") : "Nota (facoltativa)", "note",
      { type: "textarea", wide: true, placeholder: s.status === "risolto" ? "es. sostituita la guarnizione" : "" }),
    s.status === "risolto" ? field("Costo finale", "cost", { value: centsInput(j.cost_cents), inputmode: "decimal", placeholder: "0,00", hint: "facoltativo" }) : null);
  const info = s.status === "risolto" && j.recur_months && !j.next_job_id
    ? h("p", { class: "notice info" }, `Lavoro periodico (${j.recur_label.toLowerCase()}): risolvendolo si apre da solo il prossimo intervento.`) : null;
  openDialog(`${s.label}: ${j.title}`, h("div", {}, info, f), [{ label: "Annulla" }, {
    label: s.label, primary: true, onClick: async () => {
      const r = await api("POST", `/api/maintenance/${j.id}/status`, { ...formData(f), status: s.status, version: j.version });
      toast(r.job.next_job && !j.next_job_id ? `Lavoro risolto. Prossimo intervento entro il ${itd(r.job.next_job.due_date)}.` : `Lavoro: ${s.label.toLowerCase()}.`);
      done();
    } }]);
}

/* ---------------- Apparecchi della casa ---------------- */
addRoute(/^\/manutenzione\/apparecchi$/, async (main) => {
  const r = await api("GET", "/api/maintenance/assets");
  page(main, "Manutenzione", "Apparecchi della casa: garanzie, manuali, storia dei lavori",
    [h("button", { type: "button", class: "primary", onclick: () => assetDialog(null, r.categories, (a) => location.hash = `#/manutenzione/apparecchi/${a.id}`) }, "Nuovo apparecchio")]);
  main.append(mntTabs("apparecchi"));
  if (!r.assets.length) {
    main.append(h("p", { class: "muted" }, "Nessun apparecchio. Aggiungi condizionatore, caldaia, lavatrice… con garanzia e manuale: i lavori si potranno collegare."));
    return;
  }
  main.append(h("div", { class: "row", style: "margin-bottom:10px" }, searchBox(main, "Cerca apparecchio, marca, modello")));
  main.append(h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Apparecchio", "Tipo", "Marca e modello", "Garanzia", "Lavori", "Prossima scadenza", "Spesa totale", "Documenti"].map(x => h("th", {}, x)))),
    h("tbody", {}, r.assets.map(a => h("tr", { dataset: { text: [a.name, a.category, a.brand, a.model, a.location].join(" ").toLowerCase() } },
      h("td", {}, h("a", { href: `#/manutenzione/apparecchi/${a.id}` }, a.name), a.active ? null : h("div", {}, badge("Dismesso", "grey")), a.location ? h("div", { class: "muted small" }, a.location) : null),
      h("td", {}, a.category || ""),
      h("td", {}, [a.brand, a.model].filter(Boolean).join(" ")),
      h("td", {}, a.warranty_until ? [itd(a.warranty_until), " ", warrantyBadge(a)] : h("span", { class: "muted" }, "—")),
      h("td", { class: "num" }, a.n_jobs ? nJobs(a) : ""),
      h("td", {}, a.next_due ? itd(a.next_due) : ""),
      h("td", { class: "num" }, a.spent_cents ? eur(a.spent_cents) : ""),
      h("td", { class: "num" }, a.n_attachments || "")))))));
}, "manutenzione");

addRoute(/^\/manutenzione\/apparecchi\/(\d+)$/, async (main, m) => {
  const [{ asset: a }, opts] = await Promise.all([api("GET", `/api/maintenance/assets/${m[1]}`), api("GET", "/api/maintenance/options")]);
  const reload = () => render();
  page(main, a.name, a.category || "Apparecchio", [
    h("a", { class: "btn", href: "#/manutenzione/apparecchi" }, "‹ Tutti gli apparecchi"),
    h("button", { type: "button", onclick: () => assetDialog(a, opts.categories, reload) }, "Modifica"),
    h("button", { type: "button", class: "primary", onclick: () => jobDialog({ asset_id: a.id, title: "" }, (j) => location.hash = `#/manutenzione/${j.id}`) }, "Nuovo lavoro su questo apparecchio")]);
  const g = h("div", { class: "grid" });
  main.append(g);
  g.append(h("section", { class: "panel" }, h("h2", {}, "Scheda"),
    h("dl", { class: "kv" },
      h("dt", {}, "Tipo"), h("dd", {}, a.category || "—"),
      h("dt", {}, "Marca e modello"), h("dd", {}, [a.brand, a.model].filter(Boolean).join(" ") || "—"),
      h("dt", {}, "Dove si trova"), h("dd", {}, a.location || "—"),
      h("dt", {}, "Acquistato il"), h("dd", {}, a.purchased_on ? itd(a.purchased_on) : "—"),
      h("dt", {}, "Garanzia fino al"), h("dd", {}, a.warranty_until ? [itd(a.warranty_until), " ", warrantyBadge(a)] : "—"),
      h("dt", {}, "In uso"), h("dd", {}, a.active ? "Sì" : "No, dismesso"),
      h("dt", {}, "Lavori"), h("dd", {}, nJobs(a)),
      h("dt", {}, "Spesa per lavori risolti"), h("dd", { class: "money" }, eur(a.spent_cents))),
    a.notes ? h("p", { class: "pre" }, a.notes) : null));
  g.append(attachmentsPanel("Manuale, scontrino, garanzia", "JPG, PNG o PDF fino a 15 MB: manuale d'uso, scontrino, certificato di garanzia, libretto.", a.attachments, "/api/maintenance/assets", a.id, reload));
  main.append(h("section", { class: "panel" }, h("h2", {}, "Storia dei lavori", h("span", { class: "count" }, String(a.jobs.length))),
    a.jobs.length ? jobsTable(a.jobs, { noAsset: true }) : h("p", { class: "muted" }, "Nessun lavoro collegato.")));
}, "manutenzione");

function assetDialog(a, categories, done) {
  a = a || {};
  const f = h("div", { class: "form" },
    field("Nome", "name", { value: a.name, required: true, maxlength: 120, placeholder: "es. Condizionatore camera" }),
    field("Tipo", "category", { value: a.category, list: "mnt-categories", maxlength: 120 }),
    h("datalist", { id: "mnt-categories" }, categories.map(c => h("option", { value: c }))),
    field("Marca", "brand", { value: a.brand, maxlength: 120 }),
    field("Modello", "model", { value: a.model, maxlength: 120 }),
    field("Dove si trova", "location", { value: a.location, maxlength: 120, placeholder: "es. camera da letto" }),
    field("Data di acquisto", "purchased_on", { type: "date", value: a.purchased_on || "" }),
    field("Garanzia fino al", "warranty_until", { type: "date", value: a.warranty_until || "", hint: "avviso in «Oggi» 60 giorni prima" }),
    field("Note", "notes", { type: "textarea", value: a.notes, wide: true }),
    a.id ? field("In uso (togli la spunta se l'apparecchio è stato sostituito)", "active", { type: "checkbox", value: a.active, wide: true }) : null);
  openDialog(a.id ? "Modifica apparecchio" : "Nuovo apparecchio", f, [{ label: "Annulla" }, {
    label: "Salva", primary: true, onClick: async () => {
      const d = formData(f);
      const r = a.id ? await api("PUT", `/api/maintenance/assets/${a.id}`, { ...d, version: a.version }) : await api("POST", "/api/maintenance/assets", d);
      toast("Apparecchio salvato."); done(r.asset);
    } }]);
}

/* ---------------- Ditte e tecnici ---------------- */
addRoute(/^\/manutenzione\/ditte$/, async (main) => {
  const r = await api("GET", "/api/maintenance/contractors");
  page(main, "Manutenzione", "Ditte e tecnici: contatti e lavori fatti",
    [h("button", { type: "button", class: "primary", onclick: () => contractorDialog(null, r.specialties, (c) => location.hash = `#/manutenzione/ditte/${c.id}`) }, "Nuova ditta")]);
  main.append(mntTabs("ditte"));
  if (!r.contractors.length) {
    main.append(h("p", { class: "muted" }, "Rubrica vuota. Aggiungi idraulico, elettricista, tecnico del condizionatore…: nei lavori li sceglierai dall'elenco."));
    return;
  }
  main.append(h("div", { class: "row", style: "margin-bottom:10px" }, searchBox(main, "Cerca ditta o specialità")));
  main.append(h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Ditta / tecnico", "Specialità", "Telefono", "Lavori", "Ultimo lavoro risolto", "Spesa totale"].map(x => h("th", {}, x)))),
    h("tbody", {}, r.contractors.map(c => h("tr", { dataset: { text: [c.name, c.specialty, c.phone, c.email].join(" ").toLowerCase() } },
      h("td", {}, h("a", { href: `#/manutenzione/ditte/${c.id}` }, c.name), c.active ? null : h("div", {}, badge("Non più usata", "grey"))),
      h("td", {}, c.specialty || ""),
      h("td", {}, c.phone ? h("a", { href: `tel:${c.phone}` }, c.phone) : ""),
      h("td", { class: "num" }, c.n_jobs ? nJobs(c) : ""),
      h("td", {}, c.last_resolved_at ? itd(c.last_resolved_at) : ""),
      h("td", { class: "num" }, c.spent_cents ? eur(c.spent_cents) : "")))))));
}, "manutenzione");

addRoute(/^\/manutenzione\/ditte\/(\d+)$/, async (main, m) => {
  const [{ contractor: c }, opts] = await Promise.all([api("GET", `/api/maintenance/contractors/${m[1]}`), api("GET", "/api/maintenance/options")]);
  const reload = () => render();
  page(main, c.name, c.specialty || "Ditta / tecnico", [
    h("a", { class: "btn", href: "#/manutenzione/ditte" }, "‹ Tutte le ditte"),
    h("button", { type: "button", onclick: () => contractorDialog(c, opts.specialties, reload) }, "Modifica")]);
  main.append(h("section", { class: "panel" }, h("h2", {}, "Contatti"),
    h("dl", { class: "kv" },
      h("dt", {}, "Telefono"), h("dd", {}, c.phone ? h("a", { href: `tel:${c.phone}` }, c.phone) : "—"),
      h("dt", {}, "E-mail"), h("dd", {}, c.email ? h("a", { href: `mailto:${c.email}` }, c.email) : "—"),
      h("dt", {}, "Lavori"), h("dd", {}, nJobs(c)),
      h("dt", {}, "Spesa per lavori risolti"), h("dd", { class: "money" }, eur(c.spent_cents))),
    c.notes ? h("p", { class: "pre" }, c.notes) : null));
  main.append(h("section", { class: "panel" }, h("h2", {}, "Lavori", h("span", { class: "count" }, String(c.jobs.length))),
    c.jobs.length ? jobsTable(c.jobs, { noContractor: true }) : h("p", { class: "muted" }, "Nessun lavoro collegato.")));
}, "manutenzione");

function contractorDialog(c, specialties, done) {
  c = c || {};
  const f = h("div", { class: "form" },
    field("Nome", "name", { value: c.name, required: true, maxlength: 120, placeholder: "es. Idraulica Rossi" }),
    field("Specialità", "specialty", { value: c.specialty, list: "mnt-specialties", maxlength: 120 }),
    h("datalist", { id: "mnt-specialties" }, specialties.map(s => h("option", { value: s }))),
    field("Telefono", "phone", { value: c.phone, type: "tel", maxlength: 120 }),
    field("E-mail", "email", { value: c.email, type: "email", maxlength: 120 }),
    field("Note", "notes", { type: "textarea", value: c.notes, wide: true, }),
    c.id ? field("Ancora usata (togli la spunta per nasconderla dagli elenchi dei lavori)", "active", { type: "checkbox", value: c.active, wide: true }) : null);
  openDialog(c.id ? "Modifica ditta" : "Nuova ditta o tecnico", f, [{ label: "Annulla" }, {
    label: "Salva", primary: true, onClick: async () => {
      const d = formData(f);
      const r = c.id ? await api("PUT", `/api/maintenance/contractors/${c.id}`, { ...d, version: c.version }) : await api("POST", "/api/maintenance/contractors", d);
      toast("Ditta salvata."); done(r.contractor);
    } }]);
}
