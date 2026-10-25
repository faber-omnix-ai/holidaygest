"""Collaudo end-to-end via HTTP dell'applicazione AVVIATA (sorgenti o eseguibile impacchettato).

Uso:  python tests/e2e_pacchetto.py http://127.0.0.1:47720 [--riavvio] [--salva CARTELLA]
Solo dati sintetici. Non contatta servizi esterni. Termina il programma alla fine (/api/shutdown).
Con --riavvio verifica soltanto che i dati creati da un'esecuzione precedente siano ancora presenti.
I file Alloggiati e ROSS prodotti dal programma sono controllati con il verificatore indipendente
build/verifica_tracciati.py; con --salva vengono anche salvati nella cartella indicata.
"""
from __future__ import annotations

import base64
import http.cookiejar
import importlib.util
import io
import json
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verifica_tracciati", Path(__file__).resolve().parent.parent / "build" / "verifica_tracciati.py")
VT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VT)
SALVA = Path(sys.argv[sys.argv.index("--salva") + 1]) if "--salva" in sys.argv else None

# Date relative a oggi: il portale Alloggiati accetta nel file solo arrivi di oggi o di ieri, e il programma
# rifiuta partenze future. Soggiorno: arrivo ieri, partenza fra 2 giorni (3 notti), ancora in corso.
_T = date.today()
ARR, DEP, PREV = (_T - timedelta(1)).isoformat(), (_T + timedelta(2)).isoformat(), (_T - timedelta(2)).isoformat()
TODAY = _T.isoformat()

BASE = sys.argv[1].rstrip("/")
PW = "collaudo-pacchetto-2026"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
CSRF = None
RESULTS = []


def call(method, path, body=None, raw=None, headers=None, expect=200):
    h = {"Origin": BASE, **(headers or {})}
    data = None
    if raw is not None:
        data = raw
        h.setdefault("Content-Type", "application/octet-stream")
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if CSRF:
        h["X-CSRF-Token"] = CSRF
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        r = opener.open(req, timeout=120)
        status, payload, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status, payload, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
    if status != expect:
        raise AssertionError(f"{method} {path}: atteso {expect}, ottenuto {status}: {payload[:300]!r}")
    return json.loads(payload) if "json" in ctype else payload


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("OK   " if cond else "FAIL ") + name + (f" — {detail}" if detail else ""))


def main():
    global CSRF
    if "--riavvio" in sys.argv:
        r = call("POST", "/api/login", {"username": "proprietaria", "password": PW})
        CSRF = r["csrf"]
        bl = call("GET", "/api/bookings")["bookings"]
        check("Persistenza dopo riavvio: prenotazione presente", any(b["booker_name"] == "Referente Collaudo" for b in bl))
        call("POST", "/api/shutdown", {})
        return finish()
    st = call("GET", "/api/status")
    check("Avvio e stato iniziale (archivio vuoto)", st["setup_done"] is False)
    # protezioni di rete
    call("POST", "/api/setup", {"username": "x", "password": "y" * 12}, headers={"Origin": "http://evil.example"}, expect=403)
    check("Richiesta da origine esterna rifiutata", True)
    r = call("POST", "/api/setup", {"username": "proprietaria", "password": PW})
    CSRF = r["csrf"]
    check("Configurazione iniziale con codice di recupero", len(r["recovery_code"]) == 29)
    s = call("GET", "/api/settings")["structure"]
    todo = call("GET", "/api/today")["setup_todo"]
    check("Archivio nuovo senza dati precompilati (struttura, Comune, ROSS da configurare)",
          not s["cin"] and not s["capacity"] and not s["ross"]["code"] and not s["category_confirmed"]
          and len(todo) >= 7, f"{len(todo)} voci da completare")
    s.update({"name": "Casa di Collaudo", "address": "Via di Prova 1", "cin": "CIN-PROVA", "tax_comune": "Alghero",
              "activity_type": "locazione_turistica", "tax_category": "extra_alberghiera", "category_confirmed": True, "capacity": 4,
              "alloggiati": {"format": "168", "apartment_id": ""}, "ross_sends_alloggiati": False,
              "ross": {"code": "PROVA01", "units": 1, "beds": 4, "include_names": False, "include_bookings": False}})
    call("PUT", "/api/settings", {"structure": s})
    rules = call("GET", "/api/tax/rules")["rules"]
    call("POST", f"/api/tax/rules/{rules[0]['id']}/approve", {})
    check("Configurazione completata: nessuna voce da completare", call("GET", "/api/today")["setup_todo"] == [])
    b = call("POST", "/api/bookings", {"booker_name": "Referente Collaudo", "arrival": ARR,
                                       "departure": DEP, "guests_expected": 2, "status": "confermata",
                                       "base_cents": "450,00", "deposit_cents": "100", "tourism_type": "Balneare",
                                       "transport": "Aereo"})["booking"]
    check("Prenotazione senza documenti", b["ref"].startswith(f"P{_T.year}-") or b["ref"].startswith(f"P{_T.year - 1}-"))
    call("POST", "/api/bookings", {"booker_name": "Sovrapposta", "arrival": TODAY, "departure": (_T + timedelta(4)).isoformat(),
                                   "guests_expected": 1, "status": "confermata"}, expect=409)
    check("Sovrapposizione rifiutata dal server", True)
    gids = []
    for sn, nm in (("COLLAUDO", "UNO"), ("COLLAUDO", "DUE")):
        g = call("POST", f"/api/bookings/{b['id']}/guests", {
            "guest_type": "16", "surname": sn, "name": nm, "sex": "F", "birth_date": "1990-01-01",
            "birth_state_code": "100000100", "birth_comune_code": "420090003", "citizenship_code": "100000100",
            "res_state_code": "100000100", "res_comune_code": "420090064",
            "doc": {"type": "IDELE", "number": "CA00000" + nm[0] + "A", "issue_place": "420090003"}})["guest"]
        call("POST", f"/api/guests/{g['id']}/verify", {})
        gids.append(g["id"])
    bk = call("GET", f"/api/bookings/{b['id']}")["booking"]
    call("POST", f"/api/bookings/{b['id']}/checkin", {"version": bk["version"], "arrivals": [
        {"guest_id": x, "date": ARR, "time": "15:30"} for x in gids]})
    bk = call("GET", f"/api/bookings/{b['id']}")["booking"]
    call("POST", f"/api/bookings/{b['id']}/checkout", {"version": bk["version"], "date": DEP}, expect=400)
    check("Partenza in data futura rifiutata", True)
    det = call("GET", f"/api/bookings/{b['id']}")
    check("Imposta 2 adulti × 3 notti = 12 euro (soggiorno in corso)", det["tax"]["total_cents"] == 1200,
          det["tax"]["kind"])
    mv = {"uid": "e2e-op-0001", "booking_id": b["id"], "direction": "entrata", "amount": "562,00", "op_date": TODAY,
          "method": "bonifico", "causale": "Saldo", "allocations": [{"category": "soggiorno", "amount": "450"},
                                                                     {"category": "imposta", "amount": "12"},
                                                                     {"category": "cauzione", "amount": "100"}]}
    call("POST", "/api/movements", mv)
    dup = call("POST", "/api/movements", mv)["movement"]
    bal = call("GET", f"/api/bookings/{b['id']}")["balances"]
    check("Incasso ripartito e ripetizione senza duplicati", dup.get("duplicate_request") and bal["stay"]["balance_cents"] == 0
          and bal["tax"]["residual_cents"] == 0 and bal["deposit"]["held_cents"] == 10000)
    rc = call("POST", f"/api/bookings/{b['id']}/receipt", {"date": TODAY})["receipt"]
    pdf = call("GET", f"/api/receipts/{rc['id']}/pdf")
    check("Quietanza PDF generata", pdf[:5] == b"%PDF-")
    p = call("POST", "/api/exports/alloggiati", {"from": ARR, "to": ARR})
    txt = base64.b64decode(p["content_b64"])
    lines = txt.split(b"\r\n")
    check("File Alloggiati: 2 righe da 168, senza CRLF finale", len(lines) == 2 and all(len(x) == 168 for x in lines)
          and not txt.endswith(b"\r\n"))
    r = call("POST", "/api/exports/ross", {"from": PREV, "to": TODAY})
    xml = base64.b64decode(r["content_b64"])
    check("File ROSS 1000 XML generato e validato localmente", xml.startswith(b"<movimenti><codice>") and xml.count(b"<movimento>") == 3)
    err_a, _ = VT.verifica_alloggiati(txt, _T)
    check("File Alloggiati conforme al verificatore indipendente", not err_a, "; ".join(err_a[:3]))
    err_r, info = VT.verifica_ross(xml)
    check("File ROSS 1000 conforme al verificatore indipendente", not err_r and info["arrivi"] == 2,
          "; ".join(err_r[:3]) or json.dumps(info))
    if SALVA:
        SALVA.mkdir(parents=True, exist_ok=True)
        (SALVA / p["file_name"]).write_bytes(txt)
        (SALVA / r["file_name"]).write_bytes(xml)
    ex = call("GET", "/api/exports")
    check("Lotti in stato «Generato» (nessun esito automatico)", all(x["status"] == "generato" for x in ex["batches"]))
    ocr = call("GET", "/api/ocr/status")
    check("Motore OCR locale disponibile nel pacchetto", ocr["available"], json.dumps(ocr))
    if ocr["available"]:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1400, 300), "white")
        dr = ImageDraw.Draw(img)
        try:
            f = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 40)
        except OSError:
            f = ImageFont.load_default()
        dr.text((30, 60), "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", fill="black", font=f)
        dr.text((30, 140), "L898902C36UTO7408122F1204159ZE184226B<<<<<10", fill="black", font=f)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        up = call("POST", "/api/ocr/upload", raw=buf.getvalue(), headers={"X-Filename": "sintetico.png"})
        t0 = time.time()
        rd = call("POST", f"/api/ocr/{up['upload_id']}/read", {"rotation": 0})
        check("Lettura MRZ sintetica offline", rd["mrz_found"] and rd["fields"]["surname"]["value"] == "ERIKSSON",
              f"{time.time() - t0:.1f} s")
        call("POST", f"/api/ocr/{up['upload_id']}/discard", {})
    job = call("POST", "/api/maintenance", {"title": "Prova collaudo: rubinetto", "priority": "urgente"})["job"]
    job = call("POST", f"/api/maintenance/{job['id']}/status", {"status": "risolto", "cost": "45,00",
                                                                "version": job["version"]})["job"]
    mnt = call("GET", "/api/maintenance?stato=chiusi")
    check("Manutenzione: lavoro aperto e risolto con costo", job["status"] == "risolto" and job["cost_cents"] == 4500
          and mnt["spent_year_cents"] == 4500 and len(job["notes"]) == 2)
    bk = call("POST", "/api/backup/local", {})
    check("Backup cifrato creato e verificato", bk["name"].endswith(".gcbak"))
    q = lambda x: f"{x.year}-T{(x.month - 1) // 3 + 1}"  # noqa: E731
    per = q(_T - timedelta(1))
    exp = 400 * sum(1 for k in range(3) if q(_T - timedelta(1) + timedelta(k)) == per)  # notti nel trimestre
    chk = call("GET", f"/api/periods/check?kind=trimestre&period={per}")
    check(f"Controllo periodo {per}: imposta calcolata {exp // 100} euro", chk["tax_computed_cents"] == exp)
    call("POST", "/api/shutdown", {})
    return finish()


def finish():
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} controlli superati")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
