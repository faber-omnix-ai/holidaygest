/* Verifica documenti (OCR locale) ed Esportazioni */
"use strict";

addRoute(/^\/documenti$/, async (main, _m, params) => {
  page(main, "Verifica documenti", "Lettura locale sul PC · nessun invio a servizi esterni");
  if (!params.prenotazione) {
    const r = await api("GET", "/api/bookings?status=");
    const active = r.bookings.filter(b => ["confermata", "in_corso", "opzione"].includes(b.status));
    main.append(h("section", { class: "panel" }, h("h2", {}, "Per quale prenotazione?"),
      active.length ? h("ul", { class: "plain" }, active.map(b => h("li", {}, h("a", { href: `#/documenti?prenotazione=${b.id}` }, `${b.ref} · ${b.booker_name} · ${itd(b.arrival)} → ${itd(b.departure)}`)))) : h("p", { class: "muted" }, "Nessuna prenotazione attiva."),
      h("p", { class: "muted small" }, "In alternativa gli ospiti si inseriscono sempre a mano dalla scheda della prenotazione.")));
    return;
  }
  const D = await api("GET", `/api/bookings/${params.prenotazione}`);
  const st = await api("GET", "/api/ocr/status");
  main.append(h("p", {}, h("a", { href: `#/prenotazione/${D.booking.id}?tab=ospiti` }, `← ${D.booking.ref} · ${D.booking.booker_name}`)));
  main.append(h("div", { class: "notice info" }, "Le immagini restano solo in memoria e vengono eliminate alla chiusura di questa verifica (al più tardi dopo 30 minuti). ",
    "La lettura automatica non prova l'autenticità del documento e non sostituisce l'identificazione dell'ospite: ogni campo va controllato."));
  if (!st.available) main.append(h("div", { class: "notice err" }, st.message));
  const uploads = []; // {id, name, readings}
  let current = null, rot = 0, zoom = 1;
  const img = h("img", { alt: "Anteprima del documento caricato" });
  const viewer = h("div", { class: "viewer" }, img);
  const thumbs = h("div", { class: "thumbs" });
  const textBox = h("div", {});
  const fileIn = h("input", { type: "file", accept: ".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf", multiple: true, "aria-label": "Scegli foto o PDF del documento" });
  const show = async () => {
    if (!current) { img.removeAttribute("src"); return; }
    const r = await api("GET", `/api/ocr/${current.id}/preview?rot=${rot}`, undefined, { blob: true });
    if (img.src) URL.revokeObjectURL(img.src);
    img.src = URL.createObjectURL(r.blob); img.style.transform = `scale(${zoom})`;
  };
  const drawThumbs = () => thumbs.replaceChildren(...uploads.map(u => h("button", { type: "button", "aria-pressed": String(u === current), onclick: () => { current = u; rot = 0; show(); } },
    u.name, u.readings ? " ✓" : "")));
  fileIn.addEventListener("change", async () => {
    for (const file of fileIn.files) {
      try {
        const r = await api("POST", "/api/ocr/upload", file, { raw: true, headers: { "X-Filename": encodeURIComponent(file.name).slice(0, 80), "Content-Type": "application/octet-stream" } });
        const u = { id: r.upload_id, name: uploads.length ? `Pagina ${uploads.length + 1}` : "Fronte", readings: null };
        uploads.push(u); current = u;
      } catch (e) { showError(e); }
    }
    fileIn.value = ""; drawThumbs(); show();
  });
  const fieldsBox = h("div", {});
  const readBtn = h("button", { type: "button", class: "primary", disabled: !st.available }, "Leggi i dati dal documento");
  readBtn.addEventListener("click", async () => {
    if (!current) { toast("Caricare prima una foto o un PDF.", true); return; }
    readBtn.disabled = true; readBtn.textContent = "Lettura in corso…";
    try { current.readings = await api("POST", `/api/ocr/${current.id}/read`, { rotation: rot }); drawThumbs(); await drawFields(); }
    catch (e) { showError(e); toast("Puoi proseguire con l'inserimento manuale: nulla di quanto inserito va perso.", false); await drawFields(); }
    finally { readBtn.disabled = !st.available; readBtn.textContent = "Leggi i dati dal documento"; }
  });
  const drawFields = async () => {
    const readings = uploads.filter(u => u.readings).map(u => u.readings);
    const merged = readings.length ? await api("POST", "/api/ocr/merge", { readings }) : { fields: {}, conflicts: [] };
    const F = merged.fields;
    const values = { surname: F.surname?.value, name: F.name?.value, sex: F.sex?.value, birth_date: F.birth_date?.value,
      birth_state_code: F.birth_state_code?.value, birth_comune_code: F.birth_comune_code?.value, citizenship_code: F.citizenship_code?.value,
      doc: { number: F["doc.number"]?.value, type: F["doc.type"]?.value, issue_place: F["doc.issue_place"]?.value } };
    for (const k of Object.keys(values)) if (values[k] === undefined) delete values[k];
    for (const k of Object.keys(values.doc)) if (values.doc[k] === undefined) delete values.doc[k];
    const flags = {};
    for (const k of OCR_FIELDS.map(x => x[0])) flags[k] = F[k] ? F[k].status : "mancante";
    const last = readings[readings.length - 1] || {};
    fieldsBox.replaceChildren(
      readings.length ? h("dl", { class: "kv" },
        h("dt", {}, "Motore"), h("dd", {}, last.engine || ""),
        h("dt", {}, "Zona MRZ"), h("dd", {}, last.mrz_found ? "trovata" : "non trovata"),
        F.nationality_iso3 ? [h("dt", {}, "Nazionalità (codice MRZ)"), h("dd", {}, `${F.nationality_iso3.value} — non è un codice Alloggiati: scegliere la cittadinanza dall'elenco ufficiale`)] : null,
        last.document_code ? [h("dt", {}, "Tipo (codice MRZ)"), h("dd", {}, `${last.document_code} — scegliere il tipo dall'elenco ufficiale`)] : null,
        F["doc.expiry"] ? [h("dt", {}, "Scadenza documento"), h("dd", {}, itd(F["doc.expiry"].value) + (F["doc.expiry"].value < todayIso() ? " — SCADUTO" : ""))] : null) : null,
      ...(merged.conflicts.length ? [h("div", { class: "notice" }, "Valori diversi tra fronte e retro: " + merged.conflicts.join("; "))] : []),
      ...((last.notes || []).map(n => h("p", { class: "small muted" }, n))),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Campo"), h("th", {}, "Valore proposto"), h("th", {}, "Stato"))),
        h("tbody", {}, OCR_FIELDS.map(([k, l]) => {
          const v = F[k] ? (F[k].label || F[k].value) : null;
          return h("tr", {}, h("td", {}, l), h("td", {}, k === "birth_date" && v ? itd(v) : (v || "—")), h("td", {}, flagBadge(flags[k])));
        }))),
      h("p", { class: "small muted" }, "«Dubbio» = proposta da controllare sul documento. Solo la zona MRZ con cifre di controllo corrette dà «letto»."),
      last.raw_text ? h("details", {}, h("summary", {}, "Testo letto (solo a video, non viene salvato)"), h("div", { class: "ocrtext" }, last.raw_text)) : null,
      h("div", { class: "row", style: "margin-top:10px" },
        h("button", { type: "button", class: "primary", onclick: () => openGuest({ values, flags }) }, readings.length ? "Usa questi dati e completa la scheda" : "Compila la scheda manualmente"),
        h("button", { type: "button", onclick: () => openGuest(null) }, "Inserimento manuale")));
  };
  const openGuest = (prefill) => guestDialog(D, null, async () => { await discardAll(); location.hash = `#/prenotazione/${D.booking.id}?tab=ospiti`; }, prefill || undefined);
  const discardAll = async () => { for (const u of uploads.splice(0)) { try { await api("POST", `/api/ocr/${u.id}/discard`, {}); } catch (e) { /* già scaduto */ } } current = null; drawThumbs(); show(); };
  main.append(h("div", { class: "docsplit" },
    h("div", {}, h("div", { class: "row" }, fileIn),
      thumbs,
      h("div", { class: "row", style: "margin-bottom:8px" },
        h("button", { type: "button", onclick: () => { rot = (rot + 270) % 360; show(); } }, "↺ Ruota"),
        h("button", { type: "button", onclick: () => { rot = (rot + 90) % 360; show(); } }, "↻ Ruota"),
        h("button", { type: "button", onclick: () => { zoom = Math.min(3, zoom + 0.25); img.style.transform = `scale(${zoom})`; } }, "＋ Ingrandisci"),
        h("button", { type: "button", onclick: () => { zoom = Math.max(0.5, zoom - 0.25); img.style.transform = `scale(${zoom})`; } }, "－ Riduci"),
        h("button", { type: "button", class: "danger", onclick: discardAll }, "Elimina immagini")),
      viewer, h("p", { class: "muted small" }, "Formati: JPG, PNG, PDF (fronte e retro anche in file separati). HEIC: scegliere «Più compatibile» sul telefono.")),
    h("div", {}, h("section", { class: "panel" }, h("h2", {}, "Campi estratti"), h("div", { class: "row", style: "margin-bottom:8px" }, readBtn), fieldsBox, textBox))));
  window.addEventListener("hashchange", discardAll, { once: true });
  drawFields();
}, "documenti");

const OCR_FIELDS = [["surname", "Cognome"], ["name", "Nome"], ["sex", "Sesso"], ["birth_date", "Data di nascita"],
  ["birth_state_code", "Stato di nascita"], ["birth_comune_code", "Comune di nascita"], ["citizenship_code", "Cittadinanza"],
  ["doc.type", "Tipo documento"], ["doc.number", "Numero documento"], ["doc.issue_place", "Luogo di rilascio"]];

/* ---------------- Esportazioni ---------------- */
addRoute(/^\/esportazioni$/, async (main) => {
  const X = await api("GET", "/api/exports");
  page(main, "Esportazioni ed esiti", "File da caricare manualmente sui portali");
  main.append(h("div", { class: "notice info" }, "Tre livelli distinti: ", h("strong", {}, "file valido"), " (tracciato rispettato) · ", h("strong", {}, "dati coerenti"),
    " (controlli locali) · ", h("strong", {}, "accettato dal portale"), " (solo quando registri l'esito). Scaricare un file non è una comunicazione effettuata."));
  if (X.ross_sends_alloggiati) main.append(h("div", { class: "notice err" }, "Impostazioni: ROSS 1000 trasmette già ad Alloggiati Web. Caricare anche il file Alloggiati produrrebbe un doppio invio."));
  const today = todayIso();
  const g = h("div", { class: "grid" }); main.append(g);
  // Alloggiati
  const af = h("div", { class: "form" }, field("Arrivi dal", "from", { type: "date", value: addDays(today, -1) }), field("al", "to", { type: "date", value: today }),
    field("Includi ospiti già comunicati (reinvio esplicito)", "include_sent", { type: "checkbox", wide: true }));
  const aout = h("div", {});
  g.append(h("section", { class: "panel" }, h("h2", {}, "Alloggiati Web (TXT)"),
    h("p", { class: "small muted" }, `Profilo: ${X.alloggiati_profile && X.alloggiati_profile.format ? X.alloggiati_profile.format + " caratteri" : "NON CONFIGURATO"} · ${X.tables}`), af,
    h("div", { class: "row", style: "margin-top:8px" }, h("button", { type: "button", onclick: async () => {
      const d = formData(af);
      try { const p = await api("GET", `/api/exports/alloggiati/preview?from=${d.from}&to=${d.to}&include_sent=${d.include_sent ? 1 : 0}`); drawPreview(aout, p, d, "alloggiati"); } catch (e) { showError(e); }
    } }, "Anteprima: chi è incluso e chi no")), aout));
  // ROSS
  const rf = h("div", { class: "form" }, field("Giornate dal", "from", { type: "date", value: addDays(today, -1) }), field("al", "to", { type: "date", value: addDays(today, -1) }));
  const rout = h("div", {});
  g.append(h("section", { class: "panel" }, h("h2", {}, "ROSS 1000 Sardegna (XML)"),
    h("p", { class: "small muted" }, "Tracciato XML GIES versione 3 del 18/03/2026. Controllo con schema interno non ufficiale."), rf,
    h("div", { class: "row", style: "margin-top:8px" }, h("button", { type: "button", onclick: async () => {
      const d = formData(rf);
      try { const p = await api("GET", `/api/exports/ross/preview?from=${d.from}&to=${d.to}`); drawRoss(rout, p, d); } catch (e) { showError(e); }
    } }, "Anteprima movimenti")), rout,
    X.pending_deletions.length ? h("p", { class: "small" }, `Eliminazioni ROSS registrate: ${X.pending_deletions.length} (incluse nel prossimo file se non ancora inviate).`) : null));
  // Da comunicare
  main.append(h("section", { class: "panel", style: "margin-top:14px" }, h("h2", {}, "Ospiti arrivati non ancora comunicati ad Alloggiati", h("span", { class: "count" }, String(X.pending.length))),
    X.pending.length ? h("ul", { class: "plain" }, X.pending.map(p => h("li", {}, h("a", { href: `#/prenotazione/${p.booking_id}?ospite=${p.guest_id}` }, `${p.ref} · ${p.surname} ${p.name}`),
      ` · arrivo ${itd(p.stay_arrival)} · `, badge(ALLOG_IT[p.alloggiati_status] || p.alloggiati_status, ALLOG_KIND[p.alloggiati_status]), p.verified_at ? null : badge("dati da verificare", "warn")))) : h("p", { class: "muted" }, "Nessuno.")));
  // Lotti
  main.append(h("section", { class: "panel" }, h("h2", {}, "Lotti generati"), X.batches.length ? h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Lotto", "Destinazione", "Generato", "Periodo", "Elementi", "Controlli", "Stato", "Azioni"].map(x => h("th", {}, x)))),
    h("tbody", {}, X.batches.map(b => h("tr", {}, h("td", {}, b.id), h("td", {}, b.kind === "alloggiati" ? "Alloggiati Web" : "ROSS 1000"), h("td", {}, itdt(b.created_at)),
      h("td", {}, `${itd(b.period_from)} – ${itd(b.period_to)}`), h("td", { class: "num" }, b.item_count),
      h("td", { class: "small" }, Object.entries(b.checks).map(([k, v]) => `${k}: ${v}`).join(" · "), h("div", { class: "muted" }, b.profile)),
      h("td", {}, badge(b.status_label, { esito_registrato: "ok", superato: "grey", da_correggere: "err", generato: "info", caricamento_dichiarato: "info" }[b.status]),
        b.superseded_reason ? h("div", { class: "small muted" }, b.superseded_reason) : null, b.official_ref ? h("div", { class: "small" }, "Rif.: " + b.official_ref) : null),
      h("td", {}, batchActions(b))))))) : h("p", { class: "muted" }, "Nessun lotto.")));
  // Rettifiche
  main.append(h("section", { class: "panel" }, h("h2", {}, "Segnalazioni di rettifica"),
    h("p", { class: "small muted" }, "Si aprono quando cambiano dati già comunicati o consolidati. Il programma non aggiorna i portali: gestire la rettifica con le procedure del portale e registrare qui come è stata risolta."),
    X.corrections.length ? h("ul", { class: "plain" }, X.corrections.map(c => h("li", {}, badge(c.status, c.status === "aperta" ? "err" : "ok"), ` ${c.target} · ${itdt(c.created_at)} · ${c.reason}`,
      c.booking_id ? [" ", h("a", { href: `#/prenotazione/${c.booking_id}` }, "apri pratica")] : null,
      c.status === "aperta" ? [" ", h("button", { type: "button", class: "link", onclick: async () => { const r = prompt("Come è stata gestita la rettifica?"); if (!r) return; await api("POST", `/api/corrections/${c.id}/resolve`, { resolution: r }); render(); } }, "Segna come gestita")] :
        h("div", { class: "small muted" }, "Gestita: " + c.resolution)))) : h("p", { class: "muted" }, "Nessuna.")));
}, "esportazioni");

function drawPreview(out, p, d, kind) {
  out.replaceChildren(
    ...p.profile_errors.map(e => h("div", { class: "notice err" }, e)),
    ...p.warnings.map(w => h("div", { class: "notice" }, w)),
    h("h3", {}, `Inclusi (${p.included.length})`),
    p.included.length ? h("ul", {}, p.included.map(x => h("li", {}, `${x.nome} · ${x.tipo} · arrivo ${itd(x.arrivo)}`))) : h("p", { class: "muted" }, "Nessuno."),
    h("h3", {}, `Esclusi (${p.excluded.length})`),
    p.excluded.length ? h("ul", {}, p.excluded.map(x => h("li", {}, h("a", { href: `#/prenotazione/${x.booking_id}?ospite=${x.guest_id}` }, x.nome), h("ul", { class: "small" }, x.reasons.map(r => h("li", {}, r)))))) : h("p", { class: "muted" }, "Nessuno."),
    p.included.length && !p.profile_errors.length ? h("button", { type: "button", class: "primary", onclick: async () => {
      let confirm_partial = false, confirm_double = false, confirm_long_stay = false;
      if ((p.long_stays || []).length) { confirm_long_stay = await confirmDialog("Permanenza oltre 30 giorni", `${p.long_stays.join(", ")}: il tracciato Alloggiati ammette al massimo 30 giorni. Nel file verrà indicato 30. Procedere?`, "Indica 30 e procedi", true); if (!confirm_long_stay) return; }
      if (p.excluded.length) { confirm_partial = await confirmDialog("Esportazione parziale", `${p.excluded.length} ospiti restano esclusi (motivi indicati). Generare comunque il file per gli altri?`, "Genera file parziale"); if (!confirm_partial) return; }
      if (p.warnings.some(w => w.includes("DOPPIO INVIO"))) { confirm_double = await confirmDialog("Rischio di doppio invio", "ROSS 1000 risulta già configurato per trasmettere ad Alloggiati. Generare comunque?", "Genera comunque", true); if (!confirm_double) return; }
      try {
        const r = await api("POST", "/api/exports/alloggiati", { from: d.from, to: d.to, include_sent: d.include_sent, confirm_partial, confirm_double, confirm_long_stay });
        download(b64ToBlob(r.content_b64, "text/plain"), r.file_name);
        toast(`File ${r.file_name} generato. Dopo averlo caricato sul portale, registra il caricamento e l'esito.`); render();
      } catch (e) { showError(e); }
    } }, "Genera file TXT") : null);
}

function drawRoss(out, p, d) {
  const changed = p.days.filter(x => x.changed_since_declared);
  out.replaceChildren(...p.config_errors.map(e => h("div", { class: "notice err" }, e)),
    ...p.schema_errors.map(e => h("div", { class: "notice err" }, "Schema: " + e)),
    ...(p.warnings || []).map(w => h("div", { class: "notice" }, w)),
    h("p", { class: "small" }, `${p.days.length} giornate · arrivi ${p.days.reduce((a, x) => a + x.arrivals, 0)} · partenze ${p.days.reduce((a, x) => a + x.departures, 0)} · giornate chiuse ${p.days.filter(x => x.closed).length}`),
    changed.length ? h("div", { class: "notice" }, `Giornate già dichiarate e poi cambiate: ${changed.map(x => itd(x.day)).join(", ")} — ritrasmettere questi movimenti.`) : null,
    p.excluded.length ? h("div", {}, h("h3", {}, `Esclusi (${p.excluded.length})`), h("ul", {}, p.excluded.map(x => h("li", {}, x.booking_id ? h("a", { href: `#/prenotazione/${x.booking_id}?ospite=${x.guest_id}` }, x.nome || x.ref) : x.ref, h("ul", { class: "small" }, x.reasons.map(r => h("li", {}, r))))))) : null,
    !p.config_errors.length ? h("button", { type: "button", class: "primary", onclick: async () => {
      let confirm_partial = false;
      if (p.excluded.length) { confirm_partial = await confirmDialog("Esportazione parziale", "Alcuni ospiti sono esclusi: i conteggi delle giornate interessate potrebbero non essere coerenti. Generare comunque?", "Genera file parziale"); if (!confirm_partial) return; }
      try { const r = await api("POST", "/api/exports/ross", { from: d.from, to: d.to, confirm_partial }); download(b64ToBlob(r.content_b64, "application/xml"), r.file_name); toast(`File ${r.file_name} generato.`); render(); }
      catch (e) { showError(e); }
    } }, "Genera file XML") : null);
}

function batchActions(b) {
  const acts = [];
  if (b.status === "generato") acts.push(h("button", { type: "button", onclick: async () => {
    if (await confirmDialog("Caricamento sul portale", `Confermi di aver caricato il file ${b.file_name} sul portale ${b.kind === "alloggiati" ? "Alloggiati Web" : "ROSS 1000"}? Questo NON registra un esito positivo.`, "Sì, l'ho caricato")) {
      await api("POST", `/api/exports/${b.id}/declare`, {}); render(); }
  } }, "Dichiara caricato"));
  if (["caricamento_dichiarato", "da_correggere", "esito_registrato"].includes(b.status)) acts.push(h("button", { type: "button", onclick: () => outcomeDialog(b) }, "Registra esito"));
  if (["esito_registrato", "da_correggere"].includes(b.status)) {
    const fi = h("input", { type: "file", accept: ".pdf,.jpg,.jpeg,.png", hidden: true });
    fi.addEventListener("change", async () => {
      const file = fi.files[0]; if (!file) return;
      try { const r = await api("POST", `/api/exports/${b.id}/receipt`, file, { raw: true, headers: { "X-Filename": encodeURIComponent(file.name).slice(0, 80), "Content-Type": "application/octet-stream" } });
        toast(`Ricevuta acquisita (conservata fino al ${itd(r.keep_until)}). Dati documentali eliminati: ${r.documents_purged}.`); render(); } catch (e) { showError(e); }
    });
    acts.push(fi, h("button", { type: "button", onclick: () => fi.click() }, "Allega ricevuta ufficiale"));
  }
  for (const r of b.receipts || []) acts.push(h("button", { type: "button", class: "link", onclick: () => openUrl(`/api/attachments/${r.id}`) }, "Ricevuta"));
  return h("div", { class: "row" }, acts);
}

function outcomeDialog(b) {
  const sel = {};
  const rows_ = b.items.map(it => {
    const key = String(b.kind === "alloggiati" ? it.guest_id : it.ross_day);
    const s = h("select", { style: "width:auto", "aria-label": "Esito" }, [["", "—"], ["accettato", "Accettato"], ["scartato", "Scartato"]].map(([v, l]) => h("option", { value: v, selected: it.outcome === v }, l)));
    const n = h("input", { value: it.outcome_note || "", placeholder: "Motivo indicato dal portale (se presente)" });
    sel[key] = { s, n };
    return h("tr", {}, h("td", {}, b.kind === "alloggiati" ? `${it.surname || "?"} ${it.name || ""}` : itd(it.ross_day)), h("td", {}, s), h("td", {}, n));
  });
  const all = h("select", { style: "width:auto" }, [["", "Esito per singolo elemento"], ["accettato", "Tutto accettato"], ["scartato", "Tutto scartato"]].map(([v, l]) => h("option", { value: v }, l)));
  const ref = h("input", { placeholder: "Riferimento/protocollo indicato dal portale (se presente)" });
  openDialog(`Esito del lotto ${b.id}`, h("div", {}, h("p", { class: "small" }, "Registra solo quanto mostrato dal portale. Se il portale non fornisce dettagli per singolo ospite, usa l'esito unico."),
    h("label", {}, "Esito"), all, h("table", {}, h("tbody", {}, rows_)), h("label", {}, "Riferimento ufficiale"), ref),
    [{ label: "Annulla" }, { label: "Registra esito", primary: true, onClick: async () => {
      const items = {}; for (const [k, v] of Object.entries(sel)) if (v.s.value) items[k] = { outcome: v.s.value, note: v.n.value };
      const r = await api("POST", `/api/exports/${b.id}/outcome`, { all: all.value || null, items, official_ref: ref.value });
      toast(r.rejected ? `${r.rejected} elementi scartati: correggere e rigenerare.` : "Esito registrato."); render();
    } }]);
}
