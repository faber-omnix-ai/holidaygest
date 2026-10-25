/* Avvio: configurazione iniziale, accesso, recupero */
"use strict";

function centerBox(...kids) {
  $("#side").hidden = true;
  $("#main").replaceChildren(h("div", { class: "center-box" }, ...kids));
}

function showSetup() {
  document.title = "Configurazione iniziale · Gestionale Casa Vacanze";
  document.body.classList.add("login"); fotoSfondo();
  centerBox(h("h1", {}, "Benvenuto nel gestionale della casa vacanze"),
    h("p", {}, "Il programma funziona solo su questo computer, senza collegamenti a Booking o ad altri portali."),
    h("div", { class: "panel" }, h("h2", {}, "Prima installazione"),
      h("p", { class: "small" }, "Crea la password di accesso. Verrà mostrato anche un codice di recupero da conservare."),
      h("button", { type: "button", class: "primary", onclick: setupPassword }, "Inizia con un archivio vuoto")),
    restorePanel(true));
}

function setupPassword() {
  const f = h("div", {}, field("Nome utente", "username", { value: "proprietaria" }), field("Password (almeno 10 caratteri)", "password", { type: "password" }),
    field("Ripeti la password", "password2", { type: "password" }));
  centerBox(h("h1", {}, "Password di accesso"), h("div", { class: "panel" }, f,
    h("p", { class: "small muted" }, "Non esistono password predefinite o di servizio: senza password e senza codice di recupero i dati non sono recuperabili."),
    h("div", { class: "row" }, h("button", { type: "button", onclick: showSetup }, "Indietro"), h("button", { type: "button", class: "primary", onclick: async () => {
      const d = formData(f);
      if (d.password !== d.password2) { toast("Le due password non coincidono.", true); return; }
      try {
        const r = await api("POST", "/api/setup", { username: d.username, password: d.password });
        S.csrf = r.csrf; showRecovery(r.recovery_code, setupStructure);
      } catch (e) { showError(e, f); }
    } }, "Crea"))));
}

function showRecovery(code, next) {
  const ok = h("input", { type: "checkbox", id: "rc-ok" });
  const btn = h("button", { type: "button", class: "primary", disabled: true, onclick: next }, "Continua");
  ok.addEventListener("change", () => btn.disabled = !ok.checked);
  centerBox(h("h1", {}, "Codice di recupero"), h("div", { class: "panel" },
    h("p", {}, "Serve se dimentichi la password o per ripristinare un backup su un altro PC. Trascrivilo su carta e conservalo lontano dal computer. Non verrà più mostrato."),
    h("div", { class: "code" }, code),
    h("label", { class: "check", for: "rc-ok", style: "margin-top:12px" }, ok, "L'ho trascritto e conservato in un luogo sicuro"),
    h("div", { class: "row", style: "margin-top:10px" }, btn)));
}

async function setupStructure() {
  const S_ = await api("GET", "/api/settings");
  const f = structureForm(S_.structure);
  centerBox(h("h1", {}, "Dati della struttura"), h("p", { class: "small" }, "Si possono completare anche in seguito da Impostazioni. Le voci mancanti vengono ricordate nella schermata Oggi."),
    h("div", { class: "panel" }, f, h("div", { class: "row", style: "margin-top:10px" },
      h("button", { type: "button", onclick: () => start() }, "Completa più tardi"),
      h("button", { type: "button", class: "primary", onclick: async () => {
        try { await api("PUT", "/api/settings", { structure: structurePayload(formData(f)) }); start(); } catch (e) { showError(e, f); }
      } }, "Salva e inizia"))));
  $(".center-box").style.maxWidth = "900px";
}

function showLogin() {
  document.title = "Accesso · Gestionale Casa Vacanze";
  const f = h("div", {}, field("Nome utente", "username", { value: "proprietaria" }), field("Password", "password", { type: "password" }));
  const go = async () => {
    try { const r = await api("POST", "/api/login", formData(f)); S.csrf = r.csrf; start(); } catch (e) { showError(e, f); }
  };
  f.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  document.body.classList.add("login"); fotoSfondo();
  centerBox(h("div", { class: "login-card" }, h("div", { class: "mark", "aria-hidden": "true" }),
      h("p", { class: "hello" }, saluto() + (PROPRIETARIA ? `, ${PROPRIETARIA}` : "")),
      h("p", {}, S.status && S.status.structure_name || "Gestionale")), h("div", { class: "panel" }, h("h2", {}, "Accesso"), f,
    h("div", { class: "row", style: "margin-top:10px" }, h("button", { type: "button", class: "primary", onclick: go }, "Entra"), h("span", { class: "spacer" }),
      h("button", { type: "button", class: "link", onclick: showRecover }, "Ho dimenticato la password"))),
    h("p", { class: "small muted" }, `Dati in: ${S.status ? S.status.data_dir : ""}`));
  setTimeout(() => $("input[name=password]").focus(), 30);
}

function showRecover() {
  const f = h("div", {}, field("Codice di recupero", "code", { placeholder: "XXXX-XXXX-XXXX-XXXX-XXXX-XXXX" }), field("Nuova password (min. 10 caratteri)", "new_password", { type: "password" }));
  centerBox(h("h1", {}, "Recupero accesso"), h("div", { class: "panel" }, f, h("div", { class: "row", style: "margin-top:10px" },
    h("button", { type: "button", onclick: showLogin }, "Indietro"),
    h("button", { type: "button", class: "primary", onclick: async () => {
      try { const r = await api("POST", "/api/recover", formData(f)); S.csrf = r.csrf; showRecovery(r.recovery_code, start); } catch (e) { showError(e, f); }
    } }, "Imposta nuova password"))));
}

async function start() {
  S.status = await api("GET", "/api/status");
  $("#foot-app").textContent = S.status.app; $("#foot-ver").textContent = S.status.version;
  S.dayShift = S.status.today ? nightsBetween(localIso(), S.status.today) : 0;
  if (S.status.simulation && !$("#sim-banner")) {
    document.body.prepend(h("div", { id: "sim-banner", class: "notice", role: "status" },
      `SIMULAZIONE — data del programma ${itd(S.status.today)}. ${S.status.simulation}`));
  }
  if (!S.status.setup_done) { showSetup(); return; }
  if (!S.status.logged_in) { showLogin(); return; }
  S.csrf = S.status.csrf;
  document.body.classList.remove("login");
  $("#brand-name").textContent = S.status.structure_name || "Casa vacanze";
  $("#side").hidden = false;
  render();
}

window.addEventListener("hashchange", () => { if (S.csrf) render(); });
$("#btn-logout").addEventListener("click", async () => { try { await api("POST", "/api/logout", {}); } catch (e) { /* già uscito */ } S.csrf = null; start(); });
start().catch(e => $("#main").replaceChildren(h("div", { class: "notice err center-box" }, e.message)));
