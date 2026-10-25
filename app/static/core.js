/* Nucleo dell'interfaccia: DOM sicuro (mai innerHTML con dati), API, dialoghi, formati italiani. */
"use strict";
const S = { csrf: null, status: null };
// Nome mostrato nel saluto in «Oggi» (vuoto = solo «Buongiorno»): personalizzabile nella propria copia
const PROPRIETARIA = "";
// Foto facoltative della casa (sfondo): metterle in app/static/assets/casa/ con questi nomi

const CASA_FOTO = ["casa-1.jpg", "casa-2.jpg", "casa-3.jpg", "casa-4.jpg", "casa-5.jpg", "casa-6.jpg"];
const FOTO = { ok: [] };
FOTO.ready = Promise.all(CASA_FOTO.map(n => new Promise(res => {
  const im = new Image(); im.onload = () => res(n); im.onerror = () => res(null); im.src = "assets/casa/" + n;
}))).then(list => { FOTO.ok = list.filter(Boolean); fotoSfondo(); });
function fotoUrl(n) { return `url("assets/casa/${n}")`; }
function fotoSfondo() {
  if (!FOTO.ok.length) return;
  // accesso: sempre il giardino con la bouganville; dentro il programma una foto diversa a ogni schermata
  const n = document.body.classList.contains("login") && FOTO.ok.includes("casa-1.jpg") ? "casa-1.jpg"
    : FOTO.ok[Math.floor(Math.random() * FOTO.ok.length)];
  document.documentElement.style.setProperty("--foto-sfondo", fotoUrl(n));
}
function saluto() {
  const o = new Date().getHours();
  return o < 13 ? "Buongiorno" : o < 18 ? "Buon pomeriggio" : "Buonasera";
}
const V = {}; // viste registrate

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "value") el.value = v;
    else if (k === "style") el.style.cssText = v; // CSSOM: consentito dalla CSP (niente attributi style inline)
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(9)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
// append/replaceChildren ignorano i valori vuoti (null/false), come h(): niente testo "null" a schermo
for (const m of ["append", "replaceChildren"]) {
  const orig = Element.prototype[m];
  Element.prototype[m] = function (...k) { return orig.apply(this, k.flat(9).filter(x => x !== null && x !== undefined && x !== false)); };
}
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];

function eur(c) {
  if (c === null || c === undefined) return "DA VERIFICARE";
  const neg = c < 0; c = Math.abs(c);
  const s = Math.floor(c / 100).toLocaleString("it-IT") + "," + String(c % 100).padStart(2, "0");
  return (neg ? "-" : "") + "€ " + s;
}
function itd(iso) { if (!iso) return ""; const [y, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${y}`; }
function itdt(iso) { if (!iso) return ""; return itd(iso) + (iso.length > 10 ? " " + iso.slice(11, 16) : ""); }
function isoFromIt(s) {
  s = (s || "").trim(); if (!s) return "";
  const m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/); if (m) return `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  return s;
}
function addDays(iso, n) { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function nightsBetween(a, b) { return Math.round((new Date(b + "T12:00:00") - new Date(a + "T12:00:00")) / 864e5); }
function localIso() { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }
// «oggi» è quello del programma (server): coincide col PC, salvo nel lanciatore di prova con l'orologio spostato
function todayIso() { return S.dayShift ? addDays(localIso(), S.dayShift) : localIso(); }
function newUid() { return (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, ""); }
const MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

class ApiError extends Error { constructor(msg, status, body) { super(msg); this.status = status; this.body = body || {}; } }

async function api(method, url, body, opts = {}) {
  const headers = {};
  let payload;
  if (opts.raw) { payload = body; Object.assign(headers, opts.headers || {}); }
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  if (S.csrf) headers["X-CSRF-Token"] = S.csrf;
  let r;
  try { r = await fetch(url, { method, headers, body: payload, credentials: "same-origin" }); }
  catch (e) { throw new ApiError("Il gestionale non risponde: verificare che la finestra del programma sia aperta.", 0); }
  const ct = r.headers.get("Content-Type") || "";
  if (!r.ok) {
    const j = ct.includes("json") ? await r.json() : { error: await r.text() };
    if (r.status === 401 && j.login) { S.csrf = null; showLogin(); }
    throw new ApiError(j.error || "Errore", r.status, j);
  }
  if (opts.blob) return { blob: await r.blob(), name: decodeURIComponent(((r.headers.get("Content-Disposition") || "").split("''")[1] || "file")) };
  return ct.includes("json") ? r.json() : r.text();
}

function toast(msg, err) {
  const t = h("div", { class: "toast" + (err ? " err" : ""), role: err ? "alert" : "status" }, msg);
  $("#toasts").append(t); setTimeout(() => t.remove(), err ? 9000 : 4500);
}
function showError(e, formRoot) {
  const body = e.body || {};
  if (formRoot) markErrors(formRoot, body);
  const det = body.detail;
  if (det && det.errors) {
    openDialog("Correzioni necessarie", h("div", {}, h("p", {}, e.message),
      h("ul", {}, det.errors.map(x => h("li", {}, typeof x === "string" ? x : `${x.guest ? x.guest + " · " : ""}${x.message}`)))), [{ label: "Chiudi" }]);
  } else toast(e.message, true);
}
function markErrors(root, body) {
  $$(".field.err", root).forEach(f => { f.classList.remove("err"); $(".msg", f)?.remove(); });
  const errs = (body.detail && body.detail.errors) || (body.field ? [{ field: body.field, message: body.error }] : []);
  for (const er of errs) {
    const inp = root.querySelector(`[name="${er.field}"]`);
    if (inp) { const f = inp.closest(".field"); f.classList.add("err"); f.append(h("div", { class: "msg" }, er.message)); if (!root._focused) { inp.focus(); root._focused = true; } }
  }
  root._focused = false;
}

/* Dialogo modale. buttons: [{label, primary, danger, value, onClick(form) -> false per non chiudere}] */
function openDialog(title, content, buttons) {
  const dlg = $("#dlg"), form = $("#dlg-form");
  form.replaceChildren(
    h("div", { class: "dlg-head" }, h("h2", {}, title)),
    h("div", { class: "dlg-body" }, content),
    h("div", { class: "dlg-foot" }, (buttons || [{ label: "Chiudi" }]).map(b => {
      const btn = h("button", { type: "button", class: (b.primary ? "primary " : "") + (b.danger ? "danger" : "") }, b.label);
      btn.addEventListener("click", async () => {
        if (b.onClick) {
          btn.disabled = true;
          try { const r = await b.onClick(form); if (r === false) { btn.disabled = false; return; } }
          catch (e) { btn.disabled = false; showError(e, form); return; }
        }
        dlg.close();
      });
      return btn;
    })));
  if (!dlg.open) dlg.showModal();
  const first = form.querySelector(".dlg-body input, .dlg-body select, .dlg-body textarea");
  (first || form.querySelector(".dlg-foot button")).focus();
  return form;
}
function confirmDialog(title, lines, okLabel = "Conferma", danger = false) {
  return new Promise(res => {
    openDialog(title, h("div", {}, (Array.isArray(lines) ? lines : [lines]).map(l => l instanceof Node ? l : h("p", {}, l))),
      [{ label: "Annulla", onClick: () => res(false) }, { label: okLabel, primary: !danger, danger, onClick: () => res(true) }]);
    $("#dlg").addEventListener("cancel", () => res(false), { once: true });
  });
}

/* Campi modulo */
function field(label, name, opts = {}) {
  const id = "f_" + name.replace(/\W/g, "_") + "_" + Math.random().toString(36).slice(2, 6);
  let input;
  if (opts.type === "select") {
    input = h("select", { id, name, required: opts.required }, (opts.options || []).map(o => {
      const [v, l] = Array.isArray(o) ? o : [o, o];
      return h("option", { value: v, selected: String(opts.value ?? "") === String(v) }, l);
    }));
  } else if (opts.type === "textarea") input = h("textarea", { id, name, value: opts.value ?? "" });
  else if (opts.type === "checkbox") {
    return h("div", { class: "field " + (opts.wide ? "wide" : "") }, h("label", { class: "check", for: id },
      h("input", { id, name, type: "checkbox", checked: !!opts.value }), h("span", {}, label)));
  } else input = h("input", { id, name, type: opts.type || "text", value: opts.value ?? "", placeholder: opts.placeholder,
    required: opts.required, autocomplete: "off", inputmode: opts.inputmode, list: opts.list, maxlength: opts.maxlength, max: opts.max });
  return h("div", { class: "field " + (opts.wide ? "wide" : "") },
    h("label", { for: id }, label, opts.flag ? flagBadge(opts.flag) : null, opts.hint ? h("span", { class: "muted" }, " · " + opts.hint) : null), input);
}
function flagBadge(f) {
  const lbl = { letto: "letto", corretto: "corretto", mancante: "mancante", dubbio: "dubbio", manuale: "manuale" }[f] || f;
  return h("span", { class: "badge flag-" + f, style: "margin-left:6px" }, lbl);
}
function formData(root) {
  const o = {};
  $$("input, select, textarea", root).forEach(i => {
    if (!i.name) return;
    if (i.type === "checkbox") o[i.name] = i.checked;
    else o[i.name] = i.value.trim();
  });
  return o;
}

/* Ricerca nelle tabelle ufficiali (comuni, stati, documenti) */
function codeField(label, name, kind, value, opts = {}) {
  const wrap = h("div", { class: "field " + (opts.wide ? "wide" : "") });
  const hidden = h("input", { type: "hidden", name, value: value || "" });
  const listId = "dl_" + name.replace(/\W/g, "_") + Math.random().toString(36).slice(2, 6);
  const shown = h("input", { type: "text", list: listId, autocomplete: "off", placeholder: "Scrivi per cercare…", "aria-label": label });
  const dl = h("datalist", { id: listId });
  const info = h("div", { class: "muted small" });
  const id = "f_" + listId;
  shown.id = id;
  wrap.append(h("label", { for: id }, label, opts.flag ? flagBadge(opts.flag) : null), shown, dl, hidden, info);
  let last = [];
  const setInfo = (it) => { info.textContent = it ? `Codice ${it.code}${it.prov && it.prov !== "ES" ? " · " + it.prov : ""}${it.soppresso ? " · CESSATO" : ""}` : (hidden.value ? "Codice " + hidden.value : ""); };
  if (value) api("GET", `/api/tables/${kind}?q=${encodeURIComponent(value)}`).then(r => { const it = r.items.find(x => x.code === value); if (it) { shown.value = it.name; setInfo(it); } else setInfo(null); });
  shown.addEventListener("input", async () => {
    const q = shown.value.trim();
    const hit = last.find(x => x.name === q.toUpperCase());
    if (hit) { hidden.value = hit.code; setInfo(hit); hidden.dispatchEvent(new Event("change", { bubbles: true })); return; }
    if (hidden.value) { hidden.value = ""; hidden.dispatchEvent(new Event("change", { bubbles: true })); }
    setInfo(null);
    if (q.length < 2) return;
    try {
      const r = await api("GET", `/api/tables/${kind}?q=${encodeURIComponent(q)}`);
      last = r.items; dl.replaceChildren(...r.items.map(x => h("option", { value: x.name }, `${x.code}${x.prov ? " " + x.prov : ""}${x.soppresso ? " (cessato)" : ""}`)));
    } catch (e) { /* ignorato: l'utente può riprovare */ }
  });
  return wrap;
}

function download(blob, name) {
  const a = h("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
}
function b64ToBlob(b64, type) { const bin = atob(b64); const arr = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i); return new Blob([arr], { type }); }
function bufToB64(buf) { const u = new Uint8Array(buf); let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); }
function openUrl(url) { window.open(url, "_blank", "noopener"); }

function badge(text, kind) { return h("span", { class: "badge b-" + (kind || "grey") }, text); }
const BOOKING_BADGE = { bozza: "grey", opzione: "warn", opzione_scaduta: "grey", confermata: "info", in_corso: "ok", conclusa: "grey", annullata: "err", no_show: "err" };
const STATUS_IT = { bozza: "Bozza", opzione: "In opzione", opzione_scaduta: "Opzione scaduta", confermata: "Prenotata", in_corso: "Soggiorno in corso", conclusa: "Conclusa", annullata: "Annullata", no_show: "No-show" };
const PRESENCE_IT = { prevista: "Prevista", presente: "Presente", partita: "Partita", non_arrivata: "Non arrivata" };
const ALLOG_IT = { da_preparare: "Da preparare", generato: "File generato", caricamento_dichiarato: "Caricamento dichiarato", esito_registrato: "Esito registrato", da_correggere: "Da correggere" };
const ALLOG_KIND = { da_preparare: "warn", generato: "info", caricamento_dichiarato: "info", esito_registrato: "ok", da_correggere: "err" };
const PREP_IT = { da_preparare: "Da pulire/preparare", in_preparazione: "In preparazione", pronto: "Pronto" };
const GUEST_TYPES = [["16", "Ospite singolo"], ["17", "Capofamiglia"], ["18", "Capogruppo"], ["19", "Familiare"], ["20", "Componente gruppo"]];

/* Router */
const ROUTES = [];
function addRoute(rx, fn, nav) { ROUTES.push({ rx, fn, nav }); }
async function render() {
  const hash = location.hash || "#/oggi";
  const [path, qs] = hash.slice(1).split("?");
  const params = Object.fromEntries(new URLSearchParams(qs || ""));
  for (const r of ROUTES) {
    const m = path.match(r.rx);
    if (m) {
      $$("nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === r.nav));
      fotoSfondo();
      const main = $("#main");
      main.replaceChildren(h("p", { class: "muted" }, "Caricamento…"));
      try { await r.fn(main, m, params); }
      catch (e) { if (e.status !== 401) main.replaceChildren(h("div", { class: "notice err" }, e.message)); }
      main.focus({ preventScroll: true });
      return;
    }
  }
  location.hash = "#/oggi";
}
function page(main, title, sub, actions) {
  main.replaceChildren(h("div", { class: "pagehead" }, h("h1", {}, title), sub ? h("span", { class: "sub" }, sub) : null,
    actions ? h("div", { class: "actions" }, actions) : null));
  document.title = title + " · Gestionale Casa Vacanze";
  return main;
}
