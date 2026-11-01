"""Fotografa le schermate del manuale da un archivio di PROVA (solo dati inventati) già avviato.

Uso: python scatta.py <url> <cartella_uscita> <foto_documento_di_fantasia>
Richiede Playwright ed Edge. Non usare mai sull'archivio vero: il password è quella di prova.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL, OUT, DOC = sys.argv[1].rstrip("/") + "/", Path(sys.argv[2]), sys.argv[3]
PASSWORD = "password-di-prova-123"
OUT.mkdir(parents=True, exist_ok=True)


def foto(pg, nome):
    pg.wait_for_timeout(900)
    pg.screenshot(path=OUT / f"{nome}.jpg", type="jpeg", quality=78)
    print(nome)


def vai(pg, h):
    pg.goto(URL + h)
    pg.wait_for_timeout(1400)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1160, "height": 860})
    pg.goto(URL)
    pg.get_by_label("Nome utente").fill("proprietaria")
    pg.get_by_label("Password", exact=True).fill(PASSWORD)
    pg.keyboard.press("Enter")
    pg.wait_for_selector("nav:visible")
    vai(pg, "#/oggi"); foto(pg, "oggi")
    vai(pg, "#/calendario?mese=2026-11"); foto(pg, "calendario")
    vai(pg, "#/prenotazioni")
    pg.get_by_role("button", name="Nuova prenotazione").click()
    d = pg.locator("dialog")
    d.locator("[name=booker_name]").fill("Erika Mustermann")
    d.locator("[name=arrival]").fill("2026-12-19"); d.locator("[name=departure]").fill("2026-12-23")
    d.locator("[name=departure]").dispatch_event("change")
    d.locator("[name=price]").fill("520,00"); d.locator("[name=deposit]").fill("150,00")
    foto(pg, "prenotazione")
    pg.get_by_role("button", name="Salva prenotazione").click()
    pg.wait_for_url("**/prenotazione/**")
    nuova = pg.url.split("/prenotazione/")[1].split("?")[0]
    vai(pg, f"#/documenti?prenotazione={nuova}")
    pg.locator("input[type=file]").set_input_files(DOC)
    pg.wait_for_timeout(900)
    pg.get_by_role("button", name="Leggi i dati dal documento").click()
    pg.get_by_text("Zona MRZ").wait_for(timeout=90000)
    pg.get_by_role("button", name="Usa questi dati e completa la scheda").scroll_into_view_if_needed()
    foto(pg, "documento")
    bks = pg.evaluate("fetch('/api/bookings?status=').then(r => r.json())")["bookings"]
    conclusa = next(x for x in bks if x["arrival"].startswith("2026-11") and x["status"] == "conclusa")
    vai(pg, f"#/prenotazione/{conclusa['id']}?tab=pagamenti"); foto(pg, "pagamenti")
    vai(pg, f"#/prenotazione/{conclusa['id']}?tab=imposta"); foto(pg, "imposta")
    vai(pg, "#/esportazioni"); foto(pg, "esportazioni")
    vai(pg, "#/imposta?tab=staytour")
    pg.locator("[name=quarter]").select_option("4")
    pg.get_by_role("button", name="Prepara prospetto").click()
    foto(pg, "trimestre")
    vai(pg, "#/manutenzione"); foto(pg, "manutenzione")
    vai(pg, "#/impostazioni?tab=backup"); foto(pg, "backup")
    b.close()
