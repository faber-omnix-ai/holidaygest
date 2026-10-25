"""Simulazione completa di NOVEMBRE 2026 in un archivio di prova SEPARATO. SOLO DATI SINTETICI.

Uso:  python strumenti/simulazione/simula_novembre.py C:\\gcb\\simulazione_novembre [--ricrea]

Avvia il programma (sorgenti) dentro questo processo con l'orologio spostato e lo usa via HTTP come farebbe
l'interfaccia, giorno per giorno dal 05/10 al 01/12/2026: prenotazioni con caparra, ospiti italiani e stranieri,
check-in e check-out, incassi, cauzioni, imposta e quietanze, file Alloggiati (PS) e ROSS 1000 di ogni giorno
con caricamento ed esito registrati come li registrerebbe l'operatrice (nessun file va ai portali), rettifica di
un nome dopo l'invio, ospite inserito due volte ed eliminato (eliminazione ROSS), partenza anticipata di un
ospite, arrivo registrato il giorno dopo, lavori di manutenzione da fare / in corso / risolti / annullati con foto
e PDF, prenotazioni di dicembre (confermata, opzione, annullata), blocco del calendario, chiusura del mese.
Ogni file prodotto passa dal verificatore indipendente build/verifica_tracciati.py e viene salvato in
<cartella>/file_generati. L'imposta di novembre è ricalcolata a parte dalle regole.
Poi si apre con strumenti/simulazione/avvia_simulato.py (data del programma 01/12/2026).
"""
from __future__ import annotations

import base64
import http.cookiejar
import importlib.util
import io
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
import uuid
from datetime import date
from pathlib import Path

QUI = Path(__file__).resolve().parent
ROOT = QUI.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(QUI))

MARCATORE = "SIMULAZIONE_DI_PROVA.txt"
PASSWORD = "password-di-prova-123"   # la stessa di tests/conftest.py: solo archivi di prova
_spec = importlib.util.spec_from_file_location("verifica_tracciati", ROOT / "build" / "verifica_tracciati.py")
VT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VT)

IT = "100000100"
GERMANIA, FRANCIA, SPAGNA, REGNO_UNITO, SVIZZERA = "100000216", "100000215", "100000239", "100000219", "100000241"
ALGHERO, SASSARI, CAGLIARI, NUORO, ORISTANO = "420090003", "420090064", "420092009", "420091051", "420095038"
MILANO, ROMA, NAPOLI, TORINO, BOLOGNA = "403015146", "412058091", "415063049", "401001272", "408037006"


# ------------------------------------------------------------------ cartella e avvio del programma
def prepara_cartella(base: Path, ricrea: bool) -> Path:
    dati = base / "dati"
    if base.exists() and any(base.iterdir()):
        if not ricrea:
            sys.exit(f"La cartella {base} non è vuota: usare --ricrea per rifare la simulazione.")
        if not (base / MARCATORE).exists():
            sys.exit(f"{base} non contiene {MARCATORE}: non la cancello (non sembra una simulazione).")
        shutil.rmtree(base)
    (base / "file_generati").mkdir(parents=True)
    (base / MARCATORE).write_text("Archivio di prova creato da strumenti/simulazione/simula_novembre.py. "
                                  "Solo dati sintetici.\n", encoding="utf-8")
    os.environ["GESTIONALE_DATA_DIR"] = str(dati)
    return dati


class Programma:
    """Il server del gestionale avviato in questo processo, con l'orologio spostato."""

    def __init__(self):
        import orologio
        self.clock = orologio
        orologio.installa("2026-10-05")
        from app import db
        from app.server import make_server
        from app.state import STATE
        db.init_db()
        self.state = STATE
        self.srv = make_server(0)
        self.base = f"http://127.0.0.1:{STATE.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def giorno(self, g: str) -> None:
        self.clock.imposta(g)

    def call(self, method, path, body=None, raw=None, headers=None, expect=200):
        h = {"Origin": self.base, **(headers or {})}
        data = None
        if raw is not None:
            data = raw
            h.setdefault("Content-Type", "application/octet-stream")
        elif body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            r = self.opener.open(req, timeout=120)
            status, payload, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status, payload, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        if status != expect:
            raise AssertionError(f"{method} {path}: atteso {expect}, ottenuto {status}: {payload[:400]!r}")
        return json.loads(payload) if "json" in ctype else payload

    def chiudi(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.state.lock_app()


# ------------------------------------------------------------------ dati sintetici
def italiano(cognome, nome, sesso, nascita, nato_a, residente_a, tipo="16", capo=None, doc=None):
    g = {"guest_type": tipo, "surname": cognome, "name": nome, "sex": sesso, "birth_date": nascita,
         "birth_state_code": IT, "birth_comune_code": nato_a, "citizenship_code": IT,
         "res_state_code": IT, "res_comune_code": residente_a}
    if tipo in ("16", "17", "18"):
        g["doc"] = {"type": "IDELE", "number": doc, "issue_place": residente_a}
    if capo:
        g["leader_guest_id"] = capo
    return g


def straniero(cognome, nome, sesso, nascita, stato, citta, tipo="16", capo=None, doc=None):
    g = {"guest_type": tipo, "surname": cognome, "name": nome, "sex": sesso, "birth_date": nascita,
         "birth_state_code": stato, "birth_comune_code": None, "citizenship_code": stato,
         "res_state_code": stato, "res_comune_code": None, "res_place_text": citta}
    if tipo in ("16", "17", "18"):
        g["doc"] = {"type": "PASOR", "number": doc, "issue_place": stato}
    if capo:
        g["leader_guest_id"] = capo
    return g


def png(testo: str, colore: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 600), colore)
    dr = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 44)
    except OSError:
        f = ImageFont.load_default()
    dr.rectangle((30, 30, 870, 570), outline="white", width=6)
    dr.multiline_text((70, 220), "FOTO DI PROVA\n" + testo, fill="white", font=f, spacing=14)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def pdf(righe: list[str]) -> bytes:
    """PDF minimale di una pagina (documento di prova, nessun dato reale)."""
    testo = "BT /F1 14 Tf 60 780 Td 18 TL " + " ".join(
        "(" + r.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for r in righe) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(testo)} >>\nstream\n{testo}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def add_days(iso: str, n: int) -> str:
    from datetime import timedelta
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def it(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


# ------------------------------------------------------------------ scenario
PRENOTAZIONI = {
    # chiave: (creata il, arrivo, partenza, persone, totale, cauzione, referente, telefono, turismo, mezzo, canale)
    "B1": ("2026-10-06", "2026-11-01", "2026-11-04", 2, "360,00", "0", "Giovanni Murgia", "Culturale", "Auto",
           "Diretta tradizionale"),
    "B2": ("2026-10-08", "2026-11-04", "2026-11-09", 4, "650,00", "150,00", "Klaus Weber", "Balneare", "Aereo",
           "Indiretta web"),
    "B3": ("2026-10-12", "2026-11-09", "2026-11-12", 1, "300,00", "0", "Andrea Ferrari", "Congressuale/Affari",
           "Aereo+Navetta/Taxi/Auto", "Diretta web"),
    "B4": ("2026-10-15", "2026-11-12", "2026-11-16", 3, "480,00", "100,00", "Camille Dupont", "Escursionistico/Naturalistico",
           "Aereo", "Indiretta web"),
    "B5": ("2026-10-18", "2026-11-16", "2026-11-20", 3, "520,00", "0", "Paolo Conti", "Culturale", "Barca/Nave/Traghetto",
           "Diretta web"),
    "B6": ("2026-10-22", "2026-11-20", "2026-11-21", 1, "110,00", "0", "Elena Garcia Lopez", "Enogastronomico", "Aereo",
           "Indiretta web"),
    "B7": ("2026-10-26", "2026-11-21", "2026-11-25", 2, "470,00", "100,00", "John Smith", "Culturale", "Aereo",
           "Indiretta web"),
    "B8": ("2026-10-29", "2026-11-25", "2026-12-01", 4, "690,00", "200,00", "Luca Sechi", "Sportivo/Fitness", "Auto",
           "Diretta tradizionale"),
}
CAPARRE = {"B1": ("100,00", "bonifico"), "B2": ("200,00", "carta"), "B3": ("300,00", "carta"),
           "B4": ("150,00", "bonifico"), "B5": ("150,00", "bonifico"), "B6": ("110,00", "carta"),
           "B7": ("150,00", "bonifico"), "B8": ("200,00", "bonifico")}


class Novembre:
    def __init__(self, p: Programma, out: Path):
        self.p, self.out = p, out
        self.b: dict[str, dict] = {}
        self.g: dict[str, int] = {}              # ospiti per etichetta
        self.soggiorni: list[dict] = []          # per il ricalcolo indipendente dell'imposta
        self.diario: list[str] = []
        self.file_alloggiati: list[str] = []
        self.file_ross: list[str] = []
        self.oggi = "2026-10-05"
        self.mnt: dict[str, dict] = {}

    # ---------- utilità
    def log(self, t: str) -> None:
        riga = f"{it(self.oggi)}  {t}"
        self.diario.append(riga)
        print(riga, flush=True)

    def vai(self, g: str) -> None:
        self.oggi = g
        self.p.giorno(g)

    def booking(self, k: str) -> dict:
        return self.p.call("GET", f"/api/bookings/{self.b[k]['id']}")

    def incasso(self, k, importo, metodo, causale, ripartizione, giorno=None, direzione="entrata"):
        self.p.call("POST", "/api/movements", {
            "uid": uuid.uuid4().hex, "booking_id": self.b[k]["id"], "direction": direzione, "amount": importo,
            "op_date": giorno or self.oggi, "method": metodo, "causale": causale,
            "allocations": [{"category": c, "amount": a} for c, a in ripartizione]})

    def ospite(self, k, etichetta, dati, soggiorno=True, verifica=True, partenza=None):
        g = self.p.call("POST", f"/api/bookings/{self.b[k]['id']}/guests", dati)["guest"]
        if verifica:
            self.p.call("POST", f"/api/guests/{g['id']}/verify", {})
        self.g[etichetta] = g["id"]
        if soggiorno:
            arr = PRENOTAZIONI[k][1]
            self.soggiorni.append({"nascita": dati["birth_date"], "arrivo": arr,
                                   "partenza": partenza or PRENOTAZIONI[k][2]})
        return g["id"]

    def check_in(self, k, giorno=None, ora="16:00"):
        self.p.call("POST", f"/api/bookings/{self.b[k]['id']}/prep", {"status": "pronto"})
        d = self.booking(k)
        ids = [x["id"] for x in d["guests"] if x["presence"] == "prevista"]
        self.p.call("POST", f"/api/bookings/{self.b[k]['id']}/checkin", {
            "version": d["booking"]["version"],
            "arrivals": [{"guest_id": i, "date": giorno or self.oggi, "time": ora} for i in ids]})
        # saldo del soggiorno e cauzione all'arrivo
        d = self.booking(k)
        saldo = d["balances"]["stay"]["balance_cents"]
        cauz = d["balances"]["deposit"]["requested_cents"]
        rip = [("soggiorno", f"{saldo / 100:.2f}".replace(".", ","))]
        if cauz:
            rip.append(("cauzione", f"{cauz / 100:.2f}".replace(".", ",")))
        tot = saldo + cauz
        if tot:
            self.incasso(k, f"{tot / 100:.2f}".replace(".", ","), "contanti" if k in ("B1", "B5", "B8") else "pos",
                         "Saldo soggiorno" + (" e cauzione" if cauz else ""), rip)

    def check_out(self, k, metodo_imposta="contanti"):
        d = self.booking(k)
        self.p.call("POST", f"/api/bookings/{self.b[k]['id']}/checkout",
                    {"version": d["booking"]["version"], "date": self.oggi})
        d = self.booking(k)
        imp = d["balances"]["tax"]["residual_cents"]
        assert imp is not None and imp > 0, (k, d["balances"]["tax"])
        self.incasso(k, f"{imp / 100:.2f}".replace(".", ","), metodo_imposta, "Imposta di soggiorno",
                     [("imposta", f"{imp / 100:.2f}".replace(".", ","))])
        held = d["balances"]["deposit"]["held_cents"]
        if held:
            self.incasso(k, f"{held / 100:.2f}".replace(".", ","), "contanti", "Restituzione cauzione",
                         [("cauzione", f"{held / 100:.2f}".replace(".", ","))], direzione="uscita")
        rc = self.p.call("POST", f"/api/bookings/{self.b[k]['id']}/receipt", {"date": self.oggi})["receipt"]
        pdfq = self.p.call("GET", f"/api/receipts/{rc['id']}/pdf")
        assert pdfq[:5] == b"%PDF-"
        d = self.booking(k)
        assert d["balances"]["stay"]["balance_cents"] == 0 and d["balances"]["tax"]["residual_cents"] == 0
        return imp, rc

    def rettifiche_aperte(self) -> list[dict]:
        return [c for c in self.p.call("GET", "/api/exports")["corrections"] if c["status"] == "aperta"]

    # ---------- configurazione e prenotazioni (ottobre)
    def configura(self):
        r = self.p.call("POST", "/api/setup", {"username": "proprietaria", "password": PASSWORD})
        self.p.csrf = r["csrf"]
        s = self.p.call("GET", "/api/settings")["structure"]
        assert not s["ross"]["code"] and not s["capacity"] and not s["category_confirmed"]   # archivio nuovo: vuoto
        s.update({"name": "Casa Vacanze Prova", "address": "Via di Prova 1, 07041 Alghero (SS)", "cin": "CIN-PROVA",
                  "iun": "PROVA", "activity_type": "locazione_turistica", "tax_comune": "Alghero",
                  "tax_category": "extra_alberghiera", "category_confirmed": True, "capacity": 4,
                  "alloggiati": {"format": "168", "apartment_id": ""}, "ross_sends_alloggiati": False,
                  "ross": {"code": "", "units": 1, "beds": 4, "include_names": False, "include_bookings": False}})
        self.p.call("PUT", "/api/settings", {"structure": s})
        rule = self.p.call("GET", "/api/tax/rules")["rules"][0]
        self.p.call("POST", f"/api/tax/rules/{rule['id']}/approve", {"minor_rule": "meno_di_12"})
        self.p.call("POST", "/api/obligations", {"kind": "comunicazione_trimestrale", "period": "2026-T3",
                                                 "status": "da_fare", "note": "simulazione"})
        self.log("archivio di prova creato e configurato (struttura inventata, regola di esempio di Alghero approvata)")
        # rubrica delle ditte e apparecchi della casa (tutti inventati)
        self.ditte = {}
        for k, nome, spec, tel in (("clima", "Clima Service Alghero (prova)", "Climatizzazione", "000 100 0001"),
                                   ("idraulico", "Idraulico Sanna (prova)", "Idraulico", "000 100 0002"),
                                   ("pittore", "Pitture Alghero (prova)", "Imbianchino", "000 100 0003")):
            self.ditte[k] = self.p.call("POST", "/api/maintenance/contractors", {
                "name": nome, "specialty": spec, "phone": tel})["contractor"]["id"]
        self.app = {}
        for k, dati in (("clima", {"name": "Condizionatore camera", "category": "Climatizzatore", "brand": "Marca Prova",
                                   "model": "CP-12", "location": "camera da letto", "purchased_on": "2024-01-15",
                                   "warranty_until": "2027-01-15"}),
                        ("scaldabagno", {"name": "Scaldabagno", "category": "Caldaia / scaldabagno",
                                         "brand": "Marca Prova", "location": "bagno", "purchased_on": "2019-06-01",
                                         "warranty_until": "2021-06-01"}),
                        ("lavatrice", {"name": "Lavatrice", "category": "Lavatrice", "brand": "Marca Prova",
                                       "location": "veranda", "purchased_on": "2025-05-10",
                                       "warranty_until": "2028-05-10"})):
            self.app[k] = self.p.call("POST", "/api/maintenance/assets", dati)["asset"]["id"]
        self.p.call("POST", f"/api/maintenance/assets/{self.app['clima']}/attachments",
                    raw=pdf(["MANUALE DI PROVA - Condizionatore CP-12", "Pulire i filtri ogni 6 mesi"]),
                    headers={"X-Filename": "manuale_condizionatore.pdf"})
        self.lavoro("filtri", {"title": "Pulizia filtri del condizionatore", "priority": "normale",
                               "due_date": "2026-11-10", "recur_months": 6, "asset_id": self.app["clima"]})
        self.lavoro("caldaia", {"title": "Controllo annuale dello scaldabagno", "priority": "normale",
                                "due_date": "2026-12-05", "recur_months": 12, "asset_id": self.app["scaldabagno"],
                                "contractor_id": self.ditte["idraulico"], "quote_cents": "70,00"})
        self.log("rubrica: 3 ditte; apparecchi: condizionatore (garanzia fino al 15/01/2027, manuale), scaldabagno, "
                 "lavatrice; lavori periodici: filtri ogni 6 mesi, scaldabagno ogni anno")

    def prenota(self, k):
        c, arr, dep, n, tot, cauz, ref, turismo, mezzo, canale = PRENOTAZIONI[k]
        self.vai(c)
        b = self.p.call("POST", "/api/bookings", {
            "booker_name": ref, "booker_phone": "000 000 0000", "booker_email": "prova@example.invalid",
            "source_text": "Simulazione", "arrival": arr, "departure": dep, "guests_expected": n,
            "status": "confermata", "base_cents": tot, "deposit_cents": cauz, "tourism_type": turismo,
            "transport": mezzo, "booking_channel": canale, "turnover_ack": True,
            "checkin_time": "15:00", "checkout_time": "10:00"})["booking"]
        self.b[k] = b
        cap, met = CAPARRE[k]
        self.incasso(k, cap, met, "Caparra", [("soggiorno", cap)])
        self.log(f"prenotazione {b['ref']} {ref}: {it(arr)}–{it(dep)}, {n} persone, € {tot}, caparra € {cap}")

    def ottobre(self):
        self.configura()
        self.vai("2026-10-14")
        self.p.call("POST", "/api/obligations", {"kind": "comunicazione_trimestrale", "period": "2026-T3",
                                                 "status": "dichiarata", "declared_on": "2026-10-14",
                                                 "reference": "PROVA-T3", "note": "Simulazione: zero pernottamenti"})
        self.log("comunicazione imposta 3° trimestre 2026 segnata come dichiarata (zero pernottamenti, prova)")
        for k in PRENOTAZIONI:
            self.prenota(k)
        # dicembre: una confermata, un'opzione, una annullata
        self.vai("2026-10-30")
        b9 = self.p.call("POST", "/api/bookings", {
            "booker_name": "Marta Pinna", "booker_phone": "000 000 0001", "arrival": "2026-12-05",
            "departure": "2026-12-08", "guests_expected": 2, "status": "confermata", "base_cents": "330,00",
            "tourism_type": "Culturale", "transport": "Auto", "booking_channel": "Diretta tradizionale"})["booking"]
        self.b["B9"] = b9
        self.incasso("B9", "100,00", "bonifico", "Caparra", [("soggiorno", "100,00")])
        self.b["B11"] = self.p.call("POST", "/api/bookings", {
            "booker_name": "Hans Becker", "arrival": "2026-12-18", "departure": "2026-12-22", "guests_expected": 2,
            "status": "confermata", "base_cents": "420,00", "tourism_type": "Culturale",
            "transport": "Aereo", "booking_channel": "Indiretta web"})["booking"]
        self.log("dicembre: confermata Pinna 05–08/12 (caparra € 100), confermata Becker 18–22/12")
        # dal 31/10 si comincia a usare il programma per ROSS 1000 (promemoria dal 01/11)
        self.vai("2026-10-31")
        s = self.p.call("GET", "/api/settings")["structure"]
        s["ross"]["code"] = "PROVA01"
        self.p.call("PUT", "/api/settings", {"structure": s})
        assert self.p.call("GET", "/api/settings")["structure"]["ross"]["configured_on"] == "2026-10-31"
        self.log("ROSS 1000 gestito dal programma da questa data: promemoria delle giornate dal 01/11")

    # ---------- manutenzione
    def lavoro(self, chiave, dati, foto=None):
        j = self.p.call("POST", "/api/maintenance", dati)["job"]
        self.mnt[chiave] = j
        for nome, contenuto in foto or []:
            self.allegato(chiave, nome, contenuto)
        self.log(f"manutenzione aperta: {dati['title']}")
        return j

    def allegato(self, chiave, nome, contenuto):
        jid = self.mnt[chiave]["id"]
        self.p.call("POST", f"/api/maintenance/{jid}/attachments", raw=contenuto,
                    headers={"X-Filename": nome, "Content-Type": "application/octet-stream"})

    def stato_lavoro(self, chiave, stato, nota=None, costo=None):
        jid = self.mnt[chiave]["id"]
        j = self.p.call("GET", f"/api/maintenance/{jid}")["job"]
        body = {"status": stato, "version": j["version"], "note": nota or ""}
        if costo is not None:
            body["cost"] = costo
        self.mnt[chiave] = self.p.call("POST", f"/api/maintenance/{jid}/status", body)["job"]

    def nota_lavoro(self, chiave, testo):
        self.p.call("POST", f"/api/maintenance/{self.mnt[chiave]['id']}/notes", {"text": testo})

    # ---------- eventi dei giorni di novembre
    def eventi(self):
        g, call = self.oggi, self.p.call
        if g == "2026-11-01":
            capo = self.ospite("B1", "murgia", italiano("MURGIA", "GIOVANNI", "M", "1975-03-12", NUORO, CAGLIARI,
                                                         "17", doc="CA12345AB"))
            self.ospite("B1", "porcu", italiano("PORCU", "ANNA", "F", "1978-07-22", ORISTANO, CAGLIARI, "19",
                                                capo=capo))
            self.check_in("B1", ora="15:40")
            self.log("arrivo MURGIA/PORCU (italiani, capofamiglia + familiare)")
        elif g == "2026-11-03":
            self.lavoro("clima", {"title": "Condizionatore camera: non raffredda", "priority": "urgente",
                                  "description": "Si accende ma esce aria tiepida. Segnalato dagli ospiti.",
                                  "due_date": "2026-12-03", "contractor_id": self.ditte["clima"],
                                  "asset_id": self.app["clima"], "quote_cents": "180,00"},
                        [("condizionatore.png", png("condizionatore camera", "#5b6b8c"))])
        elif g == "2026-11-04":
            self.check_out("B1")
            capo = self.ospite("B2", "weber", straniero("WEBER", "KLAUS", "M", "1980-01-15", GERMANIA, "BERLIN",
                                                        "17", doc="C01X00T47"))
            self.ospite("B2", "weber_s", straniero("WEBER", "SABINE", "F", "1982-05-30", GERMANIA, "BERLIN", "19",
                                                   capo=capo))
            self.ospite("B2", "weber_l", straniero("WEBER", "LENA", "F", "2016-08-10", GERMANIA, "BERLIN", "19",
                                                   capo=capo))
            self.ospite("B2", "weber_j", straniero("WEBER", "JONAS", "M", "2012-02-01", GERMANIA, "BERLIN", "19",
                                                   capo=capo))
            self.check_in("B2", ora="17:10")
            self.log("partenza MURGIA e arrivo famiglia WEBER (Germania, 4 persone, una bambina di 10 anni esente)")
        elif g == "2026-11-05":
            self.stato_lavoro("clima", "in_corso", "Il tecnico ha ordinato il pezzo (condensatore).")
            self.log("manutenzione: condizionatore in corso")
        elif g == "2026-11-06":
            self.lavoro("doccia", {"title": "Rubinetto della doccia che gocciola", "priority": "normale",
                                   "contractor_id": self.ditte["idraulico"], "quote_cents": "80,00",
                                   "due_date": "2026-11-12"},
                        [("doccia_prima.png", png("rubinetto doccia - prima", "#4f7c82"))])
            self.stato_lavoro("doccia", "in_corso", "L'idraulico passa sabato mattina.")
        elif g == "2026-11-08":
            self.stato_lavoro("doccia", "risolto", "Sostituita la cartuccia del miscelatore.", "65,00")
            self.allegato("doccia", "fattura_idraulico.pdf", pdf(["FATTURA DI PROVA - nessun valore fiscale",
                                                                  "Idraulico Sanna (prova)",
                                                                  "Sostituzione cartuccia miscelatore: 65,00 EUR"]))
            self.allegato("doccia", "doccia_dopo.png", png("rubinetto doccia - dopo", "#3d7a4f"))
            self.log("manutenzione: rubinetto della doccia risolto (€ 65,00, fattura e foto)")
        elif g == "2026-11-09":
            self.check_out("B2", "carta")
            self.ospite("B3", "ferrari", italiano("FERRARI", "ANDREA", "M", "1988-11-03", MILANO, MILANO,
                                                  doc="CA67890CD"))
            self.check_in("B3", ora="21:15")
            self.log("partenza WEBER e arrivo FERRARI (Milano, ospite singolo, lavoro)")
        elif g == "2026-11-10":
            self.stato_lavoro("filtri", "risolto", "Filtri lavati e asciugati.", "0")
            nxt = self.mnt["filtri"]["next_job"]
            assert nxt and nxt["due_date"] == "2027-05-10", nxt
            self.log("lavoro periodico: filtri del condizionatore puliti, il prossimo si è aperto da solo per il "
                     "10/05/2027")
            self.lavoro("lampadina", {"title": "Lampadina dell'ingresso fulminata", "priority": "bassa"})
            self.stato_lavoro("lampadina", "risolto", "Cambiata dal gestore.", "4,50")
            self.lavoro("divano", {"title": "Sostituzione divano letto", "priority": "bassa",
                                   "quote_cents": "890,00", "contractor": "Arredamenti (prova)"})
            self.stato_lavoro("divano", "annullato", "Deciso di rimandare all'anno prossimo.")
        elif g == "2026-11-12":
            self.check_out("B3", "carta")
            capo = self.ospite("B4", "dupont", straniero("DUPONT", "CAMILLE", "F", "1995-04-04", FRANCIA, "LYON",
                                                         "18", doc="19AB12345"))
            self.ospite("B4", "martin", straniero("MARTIN", "LUCAS", "M", "1994-09-19", FRANCIA, "MARSEILLE",
                                                  "20", capo=capo))
            self.ospite("B4", "bernard", straniero("BERNARD", "JULIE", "F", "1996-12-01", FRANCIA, "PARIS",
                                                   "20", capo=capo))
            self.check_in("B4", ora="16:30")
            self.log("partenza FERRARI e arrivo gruppo DUPONT (Francia, capogruppo + 2)")
        elif g == "2026-11-13":
            gid = self.g["martin"]
            x = call("GET", f"/api/guests/{gid}")["guest"]
            call("PUT", f"/api/guests/{gid}", {"name": "LUCAS ANTOINE", "version": x["version"]})
            call("POST", f"/api/guests/{gid}/verify", {})
            aperte = self.rettifiche_aperte()
            assert len(aperte) == 1 and aperte[0]["target"] == "alloggiati", aperte
            call("POST", f"/api/corrections/{aperte[0]['id']}/resolve",
                 {"resolution": "Schedina rettificata sul portale Alloggiati (prova simulata)."})
            self.log("rettifica dopo l'invio: nome di MARTIN corretto in LUCAS ANTOINE, rettifica aperta e gestita")
        elif g == "2026-11-16":
            self.check_out("B4", "carta")
            capo = self.ospite("B5", "conti", italiano("CONTI", "PAOLO", "M", "1979-10-02", ROMA, ROMA, "17",
                                                       doc="CA11223EF"))
            self.ospite("B5", "deluca", italiano("DE LUCA", "FRANCESCA", "F", "1981-04-14", NAPOLI, ROMA, "19",
                                                 capo=capo))
            self.ospite("B5", "sofia", italiano("CONTI", "SOFIA", "F", "2018-06-06", ROMA, ROMA, "19", capo=capo))
            self.ospite("B5", "doppione", italiano("CONTI", "SOFIA", "F", "2018-06-06", ROMA, ROMA, "19", capo=capo),
                        soggiorno=False, verifica=False)
            self.check_in("B5", ora="18:00")
            self.log("partenza DUPONT e arrivo famiglia CONTI (Roma); la bambina inserita per errore due volte "
                     "(il doppione non è verificato)")
        elif g == "2026-11-18":
            call("POST", f"/api/guests/{self.g['doppione']}/delete", {"reason": "Ospite inserito due volte per errore"})
            aperte = self.rettifiche_aperte()
            assert len(aperte) == 1 and aperte[0]["target"] == "ross" and "16/11/2026" in aperte[0]["reason"], aperte
            call("POST", f"/api/corrections/{aperte[0]['id']}/resolve",
                 {"resolution": "Arrivo eliminato con <eliminazione> nel file successivo."})
            self.lavoro("tapparella", {"title": "Tapparella della cucina bloccata a metà", "priority": "normale",
                                       "due_date": "2026-11-28", "description": "La cinghia sembra consumata."},
                        [("tapparella.png", png("tapparella cucina", "#8c6b5b"))])
            self.log("doppione CONTI eliminato dopo il ROSS dichiarato del 16/11: eliminazione per il prossimo file")
        elif g == "2026-11-20":
            self.check_out("B5")
            self.ospite("B6", "garcia", straniero("GARCIA LOPEZ", "ELENA", "F", "1990-02-20", SPAGNA, "MADRID",
                                                  doc="PAB123456"))
            self.check_in("B6", ora="19:45")
            self.log("partenza CONTI e arrivo GARCIA LOPEZ (Spagna, una sola notte: termine Alloggiati 6 ore)")
        elif g == "2026-11-21":
            self.check_out("B6", "carta")
            self.log("partenza GARCIA LOPEZ; SMITH arriva tardi la sera, registrato domani")
        elif g == "2026-11-22":
            capo = self.ospite("B7", "smith", straniero("SMITH", "JOHN", "M", "1972-08-08", REGNO_UNITO, "LONDON",
                                                        "17", doc="533380006"))
            self.ospite("B7", "smith_e", straniero("SMITH", "EMMA", "F", "1974-03-03", REGNO_UNITO, "LONDON", "19",
                                                   capo=capo))
            self.check_in("B7", giorno="2026-11-21", ora="23:30")
            self.nota_lavoro("clima", "Pezzo arrivato in ritardo dal fornitore: intervento rimandato.")
            self.log("arrivo SMITH (Regno Unito) del 21/11 registrato il 22/11 (finestra «ieri» di Alloggiati)")
        elif g == "2026-11-25":
            self.check_out("B7", "carta")
            capo = self.ospite("B8", "sechi", italiano("SECHI", "LUCA", "M", "1985-01-30", SASSARI, ALGHERO, "18",
                                                       doc="CA44556GH"))
            self.ospite("B8", "piras", italiano("PIRAS", "MARTA", "F", "1987-05-17", TORINO, TORINO, "20", capo=capo))
            self.ospite("B8", "keller", straniero("KELLER", "STEFAN", "M", "1986-10-10", SVIZZERA, "ZURICH", "20",
                                                  capo=capo), partenza="2026-11-28")
            self.ospite("B8", "demontis", italiano("DEMONTIS", "GIULIA", "F", "1989-12-12", BOLOGNA, BOLOGNA, "20",
                                                   capo=capo))
            self.check_in("B8", ora="15:20")
            self.lavoro("pittura", {"title": "Tinteggiatura della camera da letto", "priority": "bassa",
                                    "due_date": "2026-12-10", "contractor_id": self.ditte["pittore"],
                                    "quote_cents": "350,00"})
            call("POST", "/api/blocks", {"start": "2026-12-09", "last": "2026-12-10", "kind": "manutenzione",
                                         "reason": "Tinteggiatura camera (prova)"})
            self.log("partenza SMITH e arrivo gruppo SECHI (3 italiani + 1 svizzero); blocco 09–10/12 per "
                     "tinteggiatura")
        elif g == "2026-11-28":
            call("POST", f"/api/guests/{self.g['keller']}/departure", {"date": g})
            # la permanenza comunicata ad Alloggiati (6 giorni) cambia: il programma apre una rettifica
            aperte = self.rettifiche_aperte()
            assert len(aperte) == 1 and aperte[0]["target"] == "alloggiati" and "KELLER" in aperte[0]["reason"], aperte
            call("POST", f"/api/corrections/{aperte[0]['id']}/resolve",
                 {"resolution": "Permanenza rettificata sul portale Alloggiati (prova simulata)."})
            b11 = self.booking("B11")["booking"]
            call("POST", f"/api/bookings/{b11['id']}/status/annulla",
                 {"version": b11["version"], "reason": "Cambio di programma del cliente (prova)"})
            self.log("partenza anticipata di KELLER (gruppo SECHI): rettifica Alloggiati della permanenza aperta e "
                     "gestita; annullata la prenotazione Becker di dicembre")
        elif g == "2026-11-30":
            call("POST", "/api/bookings", {
                "booker_name": "Giorgia Fadda", "arrival": "2026-12-12", "departure": "2026-12-15",
                "guests_expected": 3, "status": "opzione", "option_expires_at": "2026-12-03T12:00",
                "base_cents": "360,00", "tourism_type": "Culturale", "transport": "Auto"})
            self.log("opzione Fadda 12–15/12 in scadenza il 03/12 alle 12:00")
        elif g == "2026-12-01":
            self.check_out("B8")
            self.log("partenza gruppo SECHI: novembre completo")

    # ---------- routine giornaliera
    def alloggiati(self):
        ieri = add_days(self.oggi, -1)
        p = self.p.call("GET", f"/api/exports/alloggiati/preview?from={ieri}&to={self.oggi}")
        if not p["included"]:
            return
        dup = self.g.get("doppione")
        for x in p["excluded"]:
            assert x["guest_id"] == dup or any("Già comunicato" in r for r in x["reasons"]), x
        r = self.p.call("POST", "/api/exports/alloggiati", {
            "from": ieri, "to": self.oggi, "confirm_partial": bool(p["excluded"]),
            "confirm_long_stay": bool(p.get("long_stays"))})
        data = base64.b64decode(r["content_b64"])
        err, info = VT.verifica_alloggiati(data, date.fromisoformat(self.oggi))
        assert err == [], (r["file_name"], err)
        (self.out / r["file_name"]).write_bytes(data)
        self.file_alloggiati.append(r["file_name"])
        bid = r["batch"]["id"]
        self.p.call("POST", f"/api/exports/{bid}/declare", {})
        self.p.call("POST", f"/api/exports/{bid}/outcome", {"all": "accettato"})
        self.p.call("POST", f"/api/exports/{bid}/receipt", raw=pdf(["RICEVUTA DI PROVA - simulazione",
                                                                     f"File {r['file_name']}",
                                                                     "Nessun invio al portale"]),
                    headers={"X-Filename": f"ricevuta_prova_{self.oggi}.pdf"})
        self.log(f"Alloggiati {r['file_name']}: {info['righe']} righe, verificatore CONFORME, caricamento ed esito "
                 f"registrati, ricevuta di prova allegata")

    def ross(self):
        ieri = add_days(self.oggi, -1)
        if not ("2026-11-01" <= ieri <= "2026-11-30"):
            return
        r = self.p.call("POST", "/api/exports/ross", {"from": ieri, "to": ieri})
        data = base64.b64decode(r["content_b64"])
        err, info = VT.verifica_ross(data)
        assert err == [], (r["file_name"], err)
        (self.out / r["file_name"]).write_bytes(data)
        self.file_ross.append(r["file_name"])
        bid = r["batch"]["id"]
        self.p.call("POST", f"/api/exports/{bid}/declare", {})
        self.p.call("POST", f"/api/exports/{bid}/outcome", {"all": "accettato"})
        self.log(f"ROSS {r['file_name']}: arrivi {info['arrivi']}, partenze {info['partenze']}, "
                 f"eliminazioni {info['eliminazioni']}, verificatore CONFORME")

    # ---------- chiusura del mese
    def fine_mese(self):
        chk = self.p.call("GET", "/api/periods/check?kind=mese&period=2026-11")
        if chk["anomalies"]:
            self.log(f"chiusura di novembre NON eseguita: {len(chk['anomalies'])} anomalie "
                     + "; ".join(a.get("text", str(a)) for a in chk["anomalies"][:5]))
        else:
            self.p.call("POST", "/api/periods/close", {"kind": "mese", "period": "2026-11"})
            self.log("mese di novembre chiuso (riepilogo congelato)")
        bk = self.p.call("POST", "/api/backup/local", {})
        self.log(f"backup cifrato {bk['name']}")


def imposta_indipendente(soggiorni, dal, al_escluso) -> dict:
    from datetime import timedelta
    imponibili = esenti = oltre = 0
    for s in soggiorni:
        a, z, nato = date.fromisoformat(s["arrivo"]), date.fromisoformat(s["partenza"]), date.fromisoformat(s["nascita"])
        for i in range((z - a).days):
            n = a + timedelta(days=i)
            if not (dal <= n.isoformat() < al_escluso):
                continue
            eta = n.year - nato.year - ((n.month, n.day) < (nato.month, nato.day))
            if eta < 12:
                esenti += 1
            elif i + 1 > 7:
                oltre += 1
            else:
                imponibili += 1
    return {"imponibili": imponibili, "esenti": esenti, "oltre_limite": oltre, "cents": imponibili * 200}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = Path(sys.argv[1]).resolve()
    prepara_cartella(base, "--ricrea" in sys.argv)
    p = Programma()
    m = Novembre(p, base / "file_generati")
    controlli = []
    try:
        m.ottobre()
        g = "2026-11-01"
        while g <= "2026-12-01":
            m.vai(g)
            m.eventi()
            m.alloggiati()
            m.ross()
            g = add_days(g, 1)
        m.fine_mese()

        # ---------- controlli finali
        ok = lambda nome, cond, det="": controlli.append((nome, bool(cond), det))  # noqa: E731
        ok("File Alloggiati generati (uno per ogni giorno di arrivi)", len(m.file_alloggiati) == 8,
           str(len(m.file_alloggiati)))
        ok("File ROSS 1000 generati (una giornata ciascuno, 01–30/11)", len(m.file_ross) == 30, str(len(m.file_ross)))
        ex = p.call("GET", "/api/exports")
        ok("Nessun lotto rimasto «Generato»", all(b["status"] != "generato" for b in ex["batches"]))
        ok("Nessuna rettifica aperta", not [c for c in ex["corrections"] if c["status"] == "aperta"])
        ok("Nessun ospite in attesa di Alloggiati", not ex["pending"])
        ross17 = (m.out / next(f for f in m.file_ross if "20261117" in f)).read_bytes()
        ok("ROSS del 17/11 contiene l'eliminazione del doppione", b"<eliminazione>" in ross17)
        ross28 = (m.out / next(f for f in m.file_ross if "20261128" in f)).read_bytes()
        ok("ROSS del 28/11 contiene la partenza anticipata di KELLER", b"<partenze>" in ross28)
        from app import db
        from app.services import exports
        c = db.connect()
        try:
            mese = exports.ross_build(c, "2026-11-01", "2026-11-30")
        finally:
            c.close()
        err, info = VT.verifica_ross(mese["xml"].encode())
        (m.out / "ROSS_novembre_intero_solo_controllo.xml").write_text(mese["xml"], encoding="utf-8")
        ok("Novembre intero in un solo XML: conforme, 30 giornate", not err and info["giornate"] == 30,
           json.dumps(info) + "; ".join(err[:3]))
        ok("Arrivi e partenze del mese coerenti (20 arrivi, 17 partenze entro il 30/11)",
           info["arrivi"] == 2 + 4 + 1 + 3 + 3 + 1 + 2 + 4 and info["partenze"] == 2 + 4 + 1 + 3 + 3 + 1 + 2 + 1,
           f"arrivi {info['arrivi']}, partenze {info['partenze']}")
        atteso = imposta_indipendente(m.soggiorni, "2026-11-01", "2026-12-01")
        ok("Ricalcolo indipendente = conto a mano (74 notti imponibili, 9 esenti, € 148,00)",
           atteso == {"imponibili": 74, "esenti": 9, "oltre_limite": 0, "cents": 14800}, json.dumps(atteso))
        sh = p.call("GET", "/api/staytour?year=2026&quarter=4")
        ok("Imposta 4° trimestre del programma = ricalcolo indipendente",
           sh["pernottamenti_imponibili"] == atteso["imponibili"] and sh["imposta_calcolata_cents"] == atteso["cents"]
           and sum(sh["pernottamenti_esenti_per_motivo"].values()) == atteso["esenti"] and sh["da_verificare"] == 0,
           f"programma: {sh['pernottamenti_imponibili']} notti, {sh['imposta_calcolata_cents'] / 100:.2f} €")
        mn = p.call("GET", "/api/maintenance?stato=tutti")
        st = sorted(j["status"] for j in mn["jobs"])
        ok("Manutenzione: da fare, in corso, risolti e annullato presenti",
           st == sorted(["da_fare"] * 4 + ["in_corso", "risolto", "risolto", "risolto", "annullato"]), ", ".join(st))
        ok("Manutenzione: spesa dell'anno € 69,50", mn["spent_year_cents"] == 6950, str(mn["spent_year_cents"]))
        per = p.call("GET", "/api/maintenance?stato=periodici")["jobs"]
        ok("Lavori periodici: filtri il 10/05/2027, scaldabagno il 05/12/2026",
           sorted((j["title"], j["due_date"]) for j in per) == [("Controllo annuale dello scaldabagno", "2026-12-05"),
                                                                ("Pulizia filtri del condizionatore", "2027-05-10")])
        ditte = {c["name"]: c for c in p.call("GET", "/api/maintenance/contractors")["contractors"]}
        ok("Rubrica: spesa per ditta (idraulico € 65,00)", ditte["Idraulico Sanna (prova)"]["spent_cents"] == 6500)
        app = {a["name"]: a for a in p.call("GET", "/api/maintenance/assets")["assets"]}
        ok("Apparecchi: garanzia del condizionatore in scadenza, 3 lavori collegati, manuale allegato",
           app["Condizionatore camera"]["warranty_status"] == "in_scadenza"
           and app["Condizionatore camera"]["n_jobs"] == 3 and app["Condizionatore camera"]["n_attachments"] == 1,
           json.dumps({k: app["Condizionatore camera"][k] for k in ("warranty_status", "n_jobs", "n_attachments")}))
        oggi = p.call("GET", "/api/today")
        ok("Pagina Oggi del 01/12: da incassare solo il saldo Pinna di dicembre (€ 230), imposta tutta incassata",
           oggi["to_collect_cents"] == 23000 and oggi["tax_to_collect_cents"] == 0,
           f"{oggi['to_collect_cents']} / {oggi['tax_to_collect_cents']}")
    finally:
        p.chiudi()
    (base / "diario_simulazione.txt").write_text("\n".join(m.diario) + "\n", encoding="utf-8")
    righe = [("OK   " if c[1] else "FAIL ") + c[0] + (f" — {c[2]}" if c[2] else "") for c in controlli]
    (base / "controlli.txt").write_text("\n".join(righe) + "\n", encoding="utf-8")
    print("\n" + "\n".join(righe))
    bad = [c for c in controlli if not c[1]]
    print(f"\n{len(controlli) - len(bad)}/{len(controlli)} controlli superati")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
