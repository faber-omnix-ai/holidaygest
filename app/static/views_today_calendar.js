/* Oggi e Calendario */
"use strict";

addRoute(/^\/oggi$/, async (main) => {
  const t = await api("GET", "/api/today");
  const hero = h("section", { class: "hero" }, h("p", { class: "hello" }, saluto() + (PROPRIETARIA ? `, ${PROPRIETARIA} ` : " "), h("span", { class: "heart", "aria-hidden": "true" }, "✿")),
    h("p", { class: "hello-sub" }, `${itd(t.today)} · ecco come va la casa oggi`));
  FOTO.ready.then(() => { if (FOTO.ok.length) hero.style.setProperty("--foto-hero", fotoUrl(FOTO.ok[new Date().getDate() % FOTO.ok.length])); });
  page(main, "Oggi", itd(t.today), [h("a", { class: "btn primary", href: "#/calendario" }, "Nuova prenotazione dal calendario")]);
  main.prepend(hero);
  if (t.setup_todo.length) main.append(h("div", { class: "notice" }, h("strong", {}, "Configurazione da completare: "),
    h("ul", {}, t.setup_todo.map(x => h("li", {}, x))), h("a", { href: "#/impostazioni" }, "Vai alle Impostazioni")));
  const g = h("div", { class: "grid" });
  main.append(g);
  const bk = (b, extra) => h("li", {}, h("a", { href: `#/prenotazione/${b.id}` }, `${b.ref} · ${b.booker_name}`), " ",
    badge(STATUS_IT[b.status], BOOKING_BADGE[b.status]), h("div", { class: "muted small" }, extra));

  g.append(h("section", { class: "panel" }, h("h2", {}, "Chi arriva", h("span", { class: "count" }, "prossimi 7 giorni")),
    t.arrivals.length ? h("ul", { class: "plain" }, t.arrivals.map(b => bk(b,
      `Arrivo ${itd(b.arrival)}${b.checkin_time ? " ore " + b.checkin_time : ""} · ${b.guests_expected} persone · `
      + (b.status === "in_corso" ? "arrivati" : `appartamento: ${PREP_IT[b.prep_status]}`)
      + (b.status === "opzione" && b.option_expires_at ? ` · opzione in scadenza il ${itdt(b.option_expires_at)}` : ""))))
      : h("p", { class: "muted" }, "Nessun arrivo previsto.")));
  g.append(h("section", { class: "panel" }, h("h2", {}, "Chi parte"),
    t.departures.length ? h("ul", { class: "plain" }, t.departures.map(b => bk(b,
      `Partenza ${itd(b.departure)}${b.departure < t.today ? " — SUPERATA: registrare il check-out" : ""}`)))
      : h("p", { class: "muted" }, "Nessuna partenza nei prossimi giorni."),
    t.present.length ? h("p", { class: "small" }, `In casa ora: ${t.present.map(b => b.ref).join(", ")}`) : null));

  g.append(h("section", { class: "panel" }, h("h2", {}, "L'appartamento è pronto?"),
    t.turnovers.length ? h("ul", { class: "plain" }, t.turnovers.map(x => h("li", {},
      h("div", {}, `${itd(x.departure)} ore ${x.checkout} parte ${x.departure_ref} → ${itd(x.arrival)} ore ${x.checkin} arriva `,
        h("a", { href: `#/prenotazione/${x.arrival_id}` }, x.arrival_ref)),
      h("div", { class: "row small" }, x.same_day ? badge("Cambio in giornata", "warn") : null,
        `Tempo disponibile: ${Math.floor(x.gap_minutes / 60)} h ${x.gap_minutes % 60} min (preparazione prevista ${x.cleaning_minutes} min)`,
        x.compatible ? null : badge("Tempo insufficiente", "err")),
      prepSelect(x.arrival_id, x.prep_status))))
      : h("p", { class: "muted" }, "Nessun cambio ospiti nei prossimi 7 giorni.")));

  g.append(h("section", { class: "panel" }, h("h2", {}, "Quali dati mancano", h("span", { class: "count" }, String(t.open_items.length))),
    t.open_items.length ? h("ul", { class: "plain" }, t.open_items.slice(0, 40).map(i => h("li", {}, badge(i.kind, i.kind === "rettifica" ? "err" : "warn"), " ",
      h("a", { href: i.link }, i.text)))) : h("p", { class: "muted" }, "Nessuna pratica aperta.")));

  g.append(h("section", { class: "panel" }, h("h2", {}, "Comunicazioni da gestire"),
    t.deadlines.length ? h("ul", { class: "plain" }, t.deadlines.map(x => h("li", {}, h("a", { href: x.link }, x.text),
      h("div", { class: "small " + (x.overdue ? "" : "muted") }, x.overdue ? badge("Termine superato", "err") : null, x.overdue ? ` era entro il ${itdt(x.due)} (${x.basis})` : ` entro il ${itdt(x.due)} (${x.basis})`))))
      : h("p", { class: "muted" }, "Nessuna comunicazione Alloggiati in sospeso."),
    t.corrections.length ? h("p", {}, badge(`${t.corrections.length} rettifiche aperte`, "err"), " ", h("a", { href: "#/esportazioni" }, "Gestisci")) : null,
    h("p", { class: "muted small" }, t.deadline_note)));

  const mnt = t.maintenance || [];
  g.append(h("section", { class: "panel" }, h("h2", {}, "Manutenzione", h("span", { class: "count" }, String(mnt.length))),
    mnt.length ? h("ul", { class: "plain" }, mnt.map(x => h("li", {}, h("a", { href: x.link }, x.title), " ",
      x.overdue ? badge("Scaduto", "err") : x.priority === "urgente" ? badge("Urgente", "err") : badge("In scadenza", "warn"),
      h("div", { class: "muted small" }, x.kind === "garanzia" ? `Garanzia: scade il ${itd(x.due_date)}` : [x.status_label, x.due_date ? ` · entro il ${itd(x.due_date)}` : ""]))))
      : h("p", { class: "muted" }, "Nessun lavoro urgente o in scadenza."),
    h("a", { href: "#/manutenzione" }, "Tutti i lavori")));

  g.append(h("section", { class: "panel" }, h("h2", {}, "Quanto devo incassare"),
    h("dl", { class: "kv" }, h("dt", {}, "Saldi soggiorno aperti"), h("dd", { class: "money" }, eur(t.to_collect_cents)),
      h("dt", {}, "Imposta da incassare"), h("dd", { class: "money" }, eur(t.tax_to_collect_cents))),
    h("p", { class: "muted small" }, "Importi distinti: l'imposta di soggiorno non è un ricavo dell'appartamento.")));

  const b = t.backup || {};
  g.append(h("section", { class: "panel" }, h("h2", {}, "Scadenze e backup"),
    h("ul", { class: "plain" }, t.schedule.map(s => h("li", {}, h("a", { href: s.link }, s.text), " ",
      badge(s.status === "dichiarata" ? "Dichiarata" : "Da fare", s.status === "dichiarata" ? "ok" : "warn"),
      h("div", { class: "muted small" }, `Entro ${s.due.length > 10 ? itdt(s.due) : itd(s.due)} · ${s.note}`)))),
    h("h3", {}, "Backup"),
    h("p", {}, b.local_last_ok_at ? `Ultimo backup riuscito: ${itdt(b.local_last_ok_at)}` : badge("Nessun backup ancora eseguito", "err")),
    b.external_last_ok_at ? h("p", { class: "small" }, `Ultima copia su supporto esterno: ${itdt(b.external_last_ok_at)}`) : h("p", { class: "small muted" }, "Nessuna copia su chiavetta o disco esterno."),
    b.local_last_error ? h("div", { class: "notice err" }, "Ultimo tentativo non riuscito: " + b.local_last_error) : null,
    b.external_last_error ? h("div", { class: "notice" }, "Copia esterna non riuscita: " + b.external_last_error) : null,
    h("a", { href: "#/impostazioni?tab=backup" }, "Backup e ripristino")));

  g.append(h("section", { class: "panel" }, h("h2", {}, "Prossima disponibilità"),
    t.next_free.length ? h("ul", { class: "plain" }, t.next_free.map(f => h("li", {}, `Arrivo possibile dal ${itd(f.from)} `,
      f.open_end ? "(libero oltre i prossimi 6 mesi)" : `con partenza entro il ${itd(f.to)} (${nightsBetween(f.from, f.to)} notti)`))) : h("p", { class: "muted" }, "Nessun periodo libero nei prossimi 6 mesi."),
    h("p", { class: "muted small" }, "Secondo il solo calendario interno: non riflette annunci esterni."),
    t.stale_documents.length ? h("div", { class: "notice" }, `${t.stale_documents.length} ospiti partiti hanno ancora dati documentali senza esito Alloggiati registrato.`) : null));
}, "oggi");

function prepSelect(bookingId, current) {
  const sel = h("select", { "aria-label": "Stato preparazione appartamento", style: "width:auto" },
    Object.entries(PREP_IT).map(([v, l]) => h("option", { value: v, selected: v === current }, l)));
  sel.addEventListener("change", async () => {
    try { await api("POST", `/api/bookings/${bookingId}/prep`, { status: sel.value }); toast("Stato preparazione aggiornato (non modifica la disponibilità)."); }
    catch (e) { showError(e); }
  });
  return h("div", { class: "row small" }, h("span", { class: "muted" }, "Stato appartamento:"), sel);
}

/* ---------------- Calendario ---------------- */
const CAL = { y: null, m: null, sel: null };
addRoute(/^\/calendario$/, async (main, _m, params) => {
  if (CAL.y === null || params.mese) {
    const base = params.mese || todayIso().slice(0, 7);
    CAL.y = +base.slice(0, 4); CAL.m = +base.slice(5, 7) - 1;
  }
  await drawCalendar(main);
}, "calendario");

async function drawCalendar(main) {
  const first = new Date(CAL.y, CAL.m, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const gridStart = addDays(`${CAL.y}-${String(CAL.m + 1).padStart(2, "0")}-01`, -startOffset);
  const gridEnd = addDays(gridStart, 42);
  const monthStart = `${CAL.y}-${String(CAL.m + 1).padStart(2, "0")}-01`;
  const monthEnd = addDays(new Date(CAL.y, CAL.m + 1, 1, 12).toISOString().slice(0, 10), 0);
  const data = await api("GET", `/api/calendar?from=${gridStart}&to=${gridEnd}`);
  const occ = await api("GET", `/api/calendar?from=${monthStart}&to=${monthEnd}`).then(r => r.occupancy);
  const byDay = Object.fromEntries(data.days.map(d => [d.date, d]));
  const bmap = Object.fromEntries(data.bookings.map(b => [b.id, b]));
  document.title = "Calendario · Gestionale Casa Vacanze";
  const go = (dm) => { CAL.m += dm; if (CAL.m < 0) { CAL.m = 11; CAL.y--; } if (CAL.m > 11) { CAL.m = 0; CAL.y++; } CAL.sel = null; drawCalendar(main); };
  main.replaceChildren(
    h("div", { class: "cal-head" },
      h("button", { type: "button", onclick: () => go(-1), "aria-label": "Mese precedente" }, "‹"),
      h("h1", {}, `${MONTHS[CAL.m]} ${CAL.y}`),
      h("button", { type: "button", onclick: () => go(1), "aria-label": "Mese successivo" }, "›"),
      h("button", { type: "button", onclick: () => { const t = todayIso(); CAL.y = +t.slice(0, 4); CAL.m = +t.slice(5, 7) - 1; drawCalendar(main); } }, "Oggi"),
      h("input", { type: "month", value: monthStart.slice(0, 7), style: "width:auto", "aria-label": "Vai al mese",
        onchange: (e) => { if (e.target.value) { CAL.y = +e.target.value.slice(0, 4); CAL.m = +e.target.value.slice(5, 7) - 1; drawCalendar(main); } } }),
      h("span", { class: "spacer" }),
      h("button", { type: "button", onclick: () => blockDialog(() => drawCalendar(main)) }, "Blocca periodo"),
      h("button", { type: "button", class: "primary", onclick: () => bookingDialog({}, () => drawCalendar(main)) }, "Nuova prenotazione")),
    h("div", { class: "legend", "aria-label": "Legenda" },
      [["disponibile", "Disponibile"], ["opzione", "In opzione"], ["prenotato", "Prenotato"], ["in_corso", "Soggiorno in corso"], ["concluso", "Concluso"], ["bloccato", "Bloccato (manutenzione/uso personale)"]]
        .map(([k, l]) => h("span", {}, h("i", { class: "lg-" + k }), l)),
      h("span", { class: "muted" }, "▶ arrivo · ◀ partenza · Clic su due giorni liberi (arrivo e partenza) per prenotare; trascina una prenotazione per spostarla.")),
    CAL.sel ? h("div", { class: "notice info" }, `Arrivo selezionato: ${itd(CAL.sel)}. Ora fai clic sul giorno di partenza (o premi Esc).`) : null);
  const cal = h("div", { class: "cal", role: "grid", "aria-label": "Calendario disponibilità" },
    ["lun", "mar", "mer", "gio", "ven", "sab", "dom"].map(d => h("div", { class: "dow", role: "columnheader" }, d)));
  for (let i = 0; i < 42; i++) {
    const iso = addDays(gridStart, i);
    const d = byDay[iso] || { state: "disponibile", label: "Disponibile", items: [] };
    const arrivals = data.bookings.filter(b => b.from === iso), departures = data.bookings.filter(b => b.to === iso);
    const bItem = d.items.find(x => x.type === "booking");
    const b = bItem ? bmap[bItem.id] : null;
    const cell = h("button", {
      type: "button", role: "gridcell",
      class: `day s-${d.state}${iso.slice(0, 7) !== monthStart.slice(0, 7) ? " out" : ""}${iso === data.today ? " today" : ""}${CAL.sel === iso ? " sel" : ""}`,
      "aria-label": `${itd(iso)}: ${d.label}${b ? ", " + b.ref + " " + b.referente : ""}${arrivals.length ? ", arrivo" : ""}${departures.length ? ", partenza" : ""}`,
    }, h("span", { class: "n" }, h("span", {}, String(+iso.slice(8))), h("span", { class: "mk" }, departures.length ? "◀" : "", arrivals.length ? "▶" : "")),
      h("span", { class: "st" }, d.label),
      b ? h("span", { class: "chip", title: `${b.ref} · ${b.referente} · ${b.ospiti} persone · pagamenti: ${b.pagamenti}. Trascina per spostare.`,
        onpointerdown: (e) => calDragStart(e, b, iso, bmap, main) },
        `${b.ref} · ${b.referente}`) : null,
      b ? h("span", { class: "small muted" }, `${b.ospiti} pers. · ${b.pagamenti}`) : null);
    cell.dataset.iso = iso;
    cell.addEventListener("click", () => {
      if (CAL.justDragged) { CAL.justDragged = false; return; }
      if (b) { location.hash = `#/prenotazione/${b.id}`; return; }
      if (d.state === "bloccato") { const bl = data.blocks.find(x => x.id === d.items[0].id); blockInfo(bl, () => drawCalendar(main)); return; }
      if (!CAL.sel) { CAL.sel = iso; drawCalendar(main); return; }
      if (iso <= CAL.sel) { CAL.sel = iso; drawCalendar(main); return; }
      const arr = CAL.sel; CAL.sel = null;
      bookingDialog({ arrival: arr, departure: iso }, () => drawCalendar(main));
    });
    cal.append(cell);
  }
  main.append(cal);
  document.onkeydown = (e) => { if (e.key === "Escape" && CAL.sel) { CAL.sel = null; drawCalendar(main); } };
  // occupazione con denominatore esplicito, previsione e consuntivo separati
  main.append(h("div", { class: "grid", style: "margin-top:14px" },
    h("section", { class: "panel" }, h("h2", {}, `Riepilogo di ${MONTHS[CAL.m]}`),
      h("dl", { class: "kv" },
        h("dt", {}, "Notti nel mese"), h("dd", {}, occ.period_nights),
        h("dt", {}, "Notti bloccate"), h("dd", {}, occ.blocked_nights),
        h("dt", {}, "Notti vendibili"), h("dd", {}, occ.sellable_nights),
        h("dt", {}, "Notti prenotate (previsione)"), h("dd", {}, `${occ.booked_nights}${occ.forecast_rate !== null ? ` — ${occ.forecast_rate}% su ${occ.forecast_denominator}` : ""}`),
        h("dt", {}, "Notti occupate (consuntivo)"), h("dd", {}, `${occ.occupied_nights}${occ.actual_rate !== null ? ` — ${occ.actual_rate}% su ${occ.actual_denominator}` : " — nessuna notte trascorsa"}`))),
    h("section", { class: "panel" }, h("h2", {}, "Arrivi e partenze del periodo"),
      data.bookings.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Prenotazione"), h("th", {}, "Arrivo"), h("th", {}, "Partenza"), h("th", {}, "Stato"), h("th", {}, "Pagamenti"))),
        h("tbody", {}, data.bookings.map(b => h("tr", {}, h("td", {}, h("a", { href: `#/prenotazione/${b.id}` }, `${b.ref} · ${b.referente}`)),
          h("td", {}, itd(b.from)), h("td", {}, itd(b.to)), h("td", {}, b.stato), h("td", {}, b.pagamenti))))))
        : h("p", { class: "muted" }, "Nessuna prenotazione."),
      data.drafts.length ? h("p", { class: "small muted" }, `Bozze (non occupano il calendario): ${data.drafts.map(x => x.ref).join(", ")}`) : null),
    h("section", { class: "panel" }, h("h2", {}, "Cambi ospiti"),
      data.turnovers.length ? h("ul", { class: "plain" }, data.turnovers.map(x => h("li", {},
        `${itd(x.departure)} ${x.checkout} → ${itd(x.arrival)} ${x.checkin}: ${Math.floor(x.gap_minutes / 60)} h ${x.gap_minutes % 60} min `,
        x.compatible ? badge(PREP_IT[x.prep_status], x.prep_status === "pronto" ? "ok" : "warn") : badge("Tempo di preparazione insufficiente", "err"))))
        : h("p", { class: "muted" }, "Nessun cambio nel periodo."))));
}

/* Trascinamento con gli eventi del puntatore (mouse, penna, tocco): funziona in tutti i browser, anche dentro
   le celle-pulsante dove il drag-and-drop HTML5 non è affidabile. Esc annulla. Nulla si salva senza conferma. */
function calDragStart(e, b, iso, bmap, main) {
  if (e.button !== 0) return;
  const chip = e.currentTarget, x0 = e.clientX, y0 = e.clientY, offset = nightsBetween(b.from, iso);
  let active = false, cancelled = false, target = null;
  const cellAt = (ev) => { const el = document.elementFromPoint(ev.clientX, ev.clientY); return el && el.closest(".cal .day"); };
  const mark = (c) => { if (target === c) return; if (target) target.classList.remove("drop"); target = c; if (c) c.classList.add("drop"); };
  const finish = () => {
    document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up);
    document.removeEventListener("keydown", esc, true);
    chip.classList.remove("dragging"); document.body.classList.remove("cal-dragging"); mark(null);
  };
  const move = (ev) => {
    if (!active && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 6) return;
    if (!active) { active = true; chip.classList.add("dragging"); document.body.classList.add("cal-dragging"); }
    ev.preventDefault(); mark(cellAt(ev));
  };
  const up = async (ev) => {
    const c = active ? cellAt(ev) : null; const was = active || cancelled; finish();
    if (!was) return;
    CAL.justDragged = true; setTimeout(() => { CAL.justDragged = false; }, 0);
    if (!c || !c.dataset.iso) return;
    const bb = bmap[b.id], len = nightsBetween(bb.from, bb.to), newFrom = addDays(c.dataset.iso, -offset);
    if (newFrom === bb.from) return;
    await moveBooking(bb.id, newFrom, addDays(newFrom, len), () => drawCalendar(main));
  };
  const esc = (ev) => {
    if (ev.key !== "Escape" || !active) return;
    ev.stopPropagation(); active = false; cancelled = true;
    chip.classList.remove("dragging"); document.body.classList.remove("cal-dragging"); mark(null);
  };
  document.addEventListener("pointermove", move); document.addEventListener("pointerup", up);
  document.addEventListener("keydown", esc, true);
}

async function moveBooking(id, from, to, done) {
  const det = await api("GET", `/api/bookings/${id}`);
  let p;
  try { p = await api("POST", `/api/bookings/${id}/preview`, { arrival: from, departure: to }); }
  catch (e) { showError(e); return; }
  const blocked = p.availability && p.availability.conflicts.length;
  const needAck = p.availability && p.availability.turnover_problem;
  const ack = h("input", { type: "checkbox", id: "ack-mv" });
  openDialog(`Spostare ${det.booking.ref}?`, h("div", {},
    h("p", {}, `Nuovo periodo: dal ${itd(from)} al ${itd(to)}.`),
    h("ul", {}, p.summary.map(s => h("li", {}, s))),
    blocked ? h("div", { class: "notice err" }, "Spostamento non possibile: periodo occupato.") : null,
    needAck ? h("label", { class: "check" }, ack, "Accetto il cambio ospiti con tempi ridotti (decisione esplicita)") : null),
    [{ label: "Annulla" }, blocked ? null : {
      label: "Conferma spostamento", primary: true, onClick: async () => {
        await api("PUT", `/api/bookings/${id}`, { version: det.booking.version, arrival: from, departure: to, turnover_ack: needAck ? ack.checked : undefined });
        toast("Prenotazione spostata."); done && done();
      }
    }].filter(Boolean));
}

function blockDialog(done) {
  const f = h("div", { class: "form" },
    field("Primo giorno bloccato", "start", { type: "date" }), field("Ultimo giorno bloccato", "last", { type: "date" }),
    field("Tipo", "kind", { type: "select", options: [["manutenzione", "Manutenzione"], ["uso_personale", "Uso personale della proprietaria"], ["altro", "Altro"]] }),
    field("Motivo", "reason", { wide: true }));
  openDialog("Blocca un periodo", h("div", {}, f, h("p", { class: "muted small" }, "Il blocco occupa il calendario ma non genera ospiti, imposta, né comunicazioni. Non diventa una chiusura ROSS: quella si registra a parte nelle Impostazioni.")),
    [{ label: "Annulla" }, { label: "Blocca", primary: true, onClick: async () => { await api("POST", "/api/blocks", formData(f)); toast("Periodo bloccato."); done(); } }]);
}
function blockInfo(bl, done) {
  openDialog("Periodo bloccato", h("dl", { class: "kv" }, h("dt", {}, "Dal"), h("dd", {}, itd(bl.start)), h("dt", {}, "Al (incluso)"), h("dd", {}, itd(addDays(bl.end_excl, -1))),
    h("dt", {}, "Tipo"), h("dd", {}, bl.kind.replace("_", " ")), h("dt", {}, "Motivo"), h("dd", {}, bl.reason)),
    [{ label: "Chiudi" }, { label: "Rimuovi blocco", danger: true, onClick: async () => { await api("POST", `/api/blocks/${bl.id}/delete`, {}); toast("Blocco rimosso."); done(); } }]);
}
