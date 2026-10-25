"""Collaudo simulato di un mese (settembre 2026) con «viaggio nel tempo», SOLO DATI SINTETICI.

Ogni giorno virtuale si esegue la routine dell'operatrice: eventi del giorno (arrivi, partenze, correzioni),
file Alloggiati degli arrivi di oggi/ieri, file ROSS 1000 della giornata precedente. Ogni file prodotto passa dal
verificatore INDIPENDENTE `build/verifica_tracciati.py` (non importa app/), che controlla anche l'ordine degli
elementi secondo il tracciato. L'imposta del 3° trimestre è ricalcolata a parte dalle regole
(2 € × notti imponibili, minori sotto i 12 anni esenti, massimo 7 notti consecutive).
Nessun file va ai portali: caricamento ed esito sono registrati come li registrerebbe l'operatrice.
Con la variabile GCB_EVIDENZE=<cartella> i file generati e il diario vengono salvati in quella cartella.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

from app.services import bookings, consistency, exports, guests, periods
from app.util import add_days, age_on, nights
from conftest import checkin_all, mk_booking, mk_guest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verifica_tracciati", ROOT / "build" / "verifica_tracciati.py")
VT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VT)

INIZIO, FINE = "2026-09-01", "2026-09-30"
GERMANIA, FRANCIA, USA, REGNO_UNITO = "100000216", "100000215", "100000536", "100000219"
ABBASANTA_CESSATO = "420092512"   # codice valido fino al 15/07/1974 (provincia CA): nascita del 1970 ammessa
ESTERO = lambda stato, citta: {"birth_state_code": stato, "birth_comune_code": None,  # noqa: E731
                               "citizenship_code": stato, "res_state_code": stato, "res_comune_code": None,
                               "res_place_text": citta}


# ------------------------------------------------------------------ orologio virtuale
@pytest.fixture()
def orologio(conn, monkeypatch):
    """Sostituisce «oggi» e «adesso» in tutti i moduli del programma che li hanno importati da app.db."""
    from app import db
    stato = {"giorno": "2026-08-20"}
    now = lambda: f"{stato['giorno']}T12:00:00+02:00"  # noqa: E731
    today = lambda: stato["giorno"]  # noqa: E731
    orig = {"now_iso": db.now_iso, "today_iso": db.today_iso}
    for name, mod in list(sys.modules.items()):
        if name == "app" or name.startswith("app."):
            for attr, fn in (("now_iso", now), ("today_iso", today)):
                if getattr(mod, attr, None) is orig[attr]:
                    monkeypatch.setattr(mod, attr, fn)
    monkeypatch.setattr(exports, "today_iso", today)  # già sostituito da conftest con una data fissa
    return stato


# ------------------------------------------------------------------ calcolo indipendente dell'imposta
def imposta_indipendente(soggiorni: list[dict], dal: str, al_escluso: str) -> dict:
    """2 € per notte imponibile; esente sotto i 12 anni (FAQ del Comune); oltre la 7ª notte consecutiva non dovuta."""
    imponibili = esenti = oltre = 0
    for s in soggiorni:
        for i, n in enumerate(nights(s["arrivo"], s["partenza"]), 1):
            if not (dal <= n.isoformat() < al_escluso):
                continue
            if age_on(date.fromisoformat(s["nascita"]), n) < 12:
                esenti += 1
            elif i > 7:
                oltre += 1
            else:
                imponibili += 1
    return {"imponibili": imponibili, "esenti": esenti, "oltre_limite": oltre, "cents": imponibili * 200}


# ------------------------------------------------------------------ scenario
class Mese:
    def __init__(self, conn, orologio, out: Path):
        self.conn, self.clock, self.out = conn, orologio, out
        self.diario: list[str] = []
        self.file_alloggiati: list[str] = []
        self.file_ross: list[str] = []
        self.soggiorni: list[dict] = []   # per il ricalcolo indipendente dell'imposta
        self.duplicato = None

    @property
    def oggi(self) -> str:
        return self.clock["giorno"]

    def log(self, testo: str) -> None:
        self.diario.append(f"{self.oggi}  {testo}")

    def reassess(self) -> None:
        consistency.reassess_all(self.conn)

    def ospite(self, b, nascita, gtype="16", soggiorno=True, arrivo=None, partenza=None, **kw):
        g = mk_guest(self.conn, b["id"], birth=nascita, gtype=gtype, **kw)
        guests.verify(self.conn, g["id"])
        if soggiorno:
            self.soggiorni.append({"id": g["id"], "nascita": nascita, "arrivo": arrivo or b["arrival"],
                                   "partenza": partenza or b["departure"]})
        return g

    # ---------- prenotazioni create in anticipo (20/08/2026)
    def prenota(self):
        c = self.conn
        self.b1 = mk_booking(c, "2026-09-01", "2026-09-05", guests=4)                   # famiglia 17+19
        self.b2 = mk_booking(c, "2026-09-05", "2026-09-14", guests=3, transport="Auto")  # cambio in giornata, gruppo
        self.b3 = mk_booking(c, "2026-09-15", "2026-09-20", guests=1)                   # ospite inserito due volte
        self.b4 = mk_booking(c, "2026-09-22", "2026-09-24", guests=2)                   # check-in registrato il giorno dopo
        self.b5 = mk_booking(c, "2026-09-28", "2026-11-05", guests=1)                   # soggiorno oltre 30 giorni
        assert bookings.check_availability(c, "2026-09-05", "2026-09-14", exclude_booking=self.b2["id"])["turnovers"]
        self.log("5 prenotazioni confermate per settembre")

    # ---------- eventi dei singoli giorni
    def eventi(self):
        c, g = self.conn, self.oggi
        if g == "2026-09-01":
            capo = self.ospite(self.b1, "1970-02-14", "17", surname="SANNA", name="GIOVANNI",
                               birth_comune_code=ABBASANTA_CESSATO)
            for nome, sesso, nascita in (("MARIA", "F", "1975-06-20"), ("ELENA", "F", "2018-03-10"),
                                         ("PAOLO", "M", "2014-09-03")):   # Paolo compie 12 anni il 03/09
                self.ospite(self.b1, nascita, "19", surname="SANNA", name=nome, sex=sesso, leader_guest_id=capo["id"])
            checkin_all(c, self.b1["id"], g)
            self.log("arrivo famiglia SANNA (capo nato ad Abbasanta, codice comune cessato; minore esente; "
                     "minore che compie 12 anni durante il soggiorno)")
        elif g == "2026-09-05":
            b = bookings.get(c, self.b1["id"])
            bookings.check_out(c, b["id"], {"version": b["version"], "date": g})
            capo = self.ospite(self.b2, "1982-11-02", "18", surname="SCHMIDT", name="JÜRGEN",
                               **ESTERO(GERMANIA, "MUENCHEN"),
                               doc={"type": "PASOR", "number": "C4X9T2L7M", "issue_place": GERMANIA})
            self.membro_fr = self.ospite(self.b2, "1985-04-18", "20", surname="DUBOIS", name="CLAIRE", sex="F",
                                         leader_guest_id=capo["id"], **ESTERO(FRANCIA, "LYON"))
            self.ospite(self.b2, "1990-12-30", "20", surname="O'BRIEN", name="KEVIN", leader_guest_id=capo["id"],
                        **ESTERO(USA, "BOSTON"))
            checkin_all(c, self.b2["id"], g)
            self.log("partenza SANNA e arrivo gruppo SCHMIDT nello stesso giorno (stranieri: DE, FR, US; 9 notti)")
        elif g == "2026-09-06":
            # rettifica dopo l'invio: il nome della componente era sbagliato (CLAIRE -> CLAIRE MARIE)
            m = guests.get(c, self.membro_fr["id"])
            guests.save(c, self.b2["id"], {"name": "CLAIRE MARIE", "version": m["version"]}, m["id"])
            guests.verify(c, m["id"])
            self.reassess()
            corr = c.execute("SELECT * FROM corrections WHERE status='aperta' AND target='alloggiati'").fetchall()
            assert len(corr) == 1 and "DUBOIS CLAIRE MARIE" in corr[0]["reason"]
            exports.resolve_correction(c, corr[0]["id"], "Schedina rettificata sul portale (prova simulata).")
            self.log("rettifica dopo l'invio: nome della componente DUBOIS corretto, rettifica aperta e gestita")
        elif g == "2026-09-14":
            b = bookings.get(c, self.b2["id"])
            bookings.check_out(c, b["id"], {"version": b["version"], "date": g})
            self.log("partenza gruppo SCHMIDT")
        elif g == "2026-09-15":
            self.ospite(self.b3, "1988-01-25", surname="BIANCHI", name="LUCA")
            # stesso ospite inserito per errore una seconda volta (non verificato)
            self.duplicato = mk_guest(c, self.b3["id"], surname="BIANCHI", name="LUCA", birth="1988-01-25")
            checkin_all(c, self.b3["id"], g)
            self.log("arrivo BIANCHI, inserito per errore due volte (il doppione non è verificato)")
        elif g == "2026-09-17":
            # il ROSS del 15 (dichiarato ieri) contiene il doppione: va eliminato
            guests.delete(c, self.duplicato["id"], "Ospite inserito due volte per errore")
            pend = c.execute("SELECT COUNT(*) FROM ross_pending_deletions WHERE sent_batch IS NULL").fetchone()[0]
            assert pend == 1
            self.reassess()
            corr = c.execute("SELECT * FROM corrections WHERE status='aperta' AND target='ross'").fetchall()
            assert len(corr) == 1 and "15/09/2026" in corr[0]["reason"]
            exports.resolve_correction(c, corr[0]["id"], "Arrivo eliminato con <eliminazione> nel file successivo.")
            self.log("doppione eliminato dopo il ROSS dichiarato: eliminazione in attesa per il prossimo file")
        elif g == "2026-09-20":
            b = bookings.get(c, self.b3["id"])
            bookings.check_out(c, b["id"], {"version": b["version"], "date": g})
            self.log("partenza BIANCHI")
        elif g == "2026-09-23":
            capo = self.ospite(self.b4, "1979-07-07", "17", surname="DEIANA", name="ANTONIO")
            self.ospite(self.b4, "1981-08-08", "19", surname="PIRAS", name="CHIARA", sex="F",
                        leader_guest_id=capo["id"])
            checkin_all(c, self.b4["id"], "2026-09-22")
            self.log("arrivo DEIANA/PIRAS del 22/09 registrato il 23/09 (finestra «ieri» di Alloggiati)")
        elif g == "2026-09-24":
            b = bookings.get(c, self.b4["id"])
            bookings.check_out(c, b["id"], {"version": b["version"], "date": g})
            self.log("partenza DEIANA/PIRAS")
        elif g == "2026-09-25":
            bookings.create_closure(c, {"start": "2026-09-25", "last": "2026-09-27", "note": "chiusura"})
            self.log("chiusura ROSS dal 25 al 27/09")
        elif g == "2026-09-28":
            self.ospite(self.b5, "1965-05-05", surname="TAYLOR", name="MARGARET", sex="F",
                        **ESTERO(REGNO_UNITO, "LONDON"),
                        doc={"type": "PASOR", "number": "533380006", "issue_place": REGNO_UNITO})
            checkin_all(c, self.b5["id"], g)
            self.log("arrivo TAYLOR (UK), permanenza prevista 38 giorni")
        self.reassess()

    # ---------- routine giornaliera
    def alloggiati(self):
        c, ieri = self.conn, add_days(self.oggi, -1)
        p = exports.alloggiati_preview(c, ieri, self.oggi)
        if not p["included"]:
            return
        dup = self.duplicato["id"] if self.duplicato else None
        for x in p["excluded"]:
            assert x["guest_id"] == dup or any("Già comunicato" in r for r in x["reasons"]), x
        batch, data = exports.alloggiati_generate(c, ieri, self.oggi, confirm_partial=bool(p["excluded"]),
                                                  confirm_long_stay=bool(p["long_stays"]))
        err, info = VT.verifica_alloggiati(data, date.fromisoformat(self.oggi))
        assert err == [], (batch["file_name"], err)
        self._salva(batch["file_name"], data)
        self.file_alloggiati.append(batch["file_name"])
        exports.declare_upload(c, batch["id"])
        exports.register_outcome(c, batch["id"], {"all": "accettato"})
        exports.receipt_acquired(c, batch["id"])
        self.log(f"Alloggiati {batch['file_name']}: {info['righe']} righe, verificatore CONFORME"
                 + (f", esclusi {len(p['excluded'])}" if p["excluded"] else "")
                 + (", permanenza oltre 30 giorni confermata (30 nel file)" if p["long_stays"] else ""))
        self.reassess()

    def ross(self):
        c, ieri = self.conn, add_days(self.oggi, -1)
        if not (INIZIO <= ieri <= FINE):
            return
        batch, data = exports.ross_generate(c, ieri, ieri, confirm_partial=False)
        err, info = VT.verifica_ross(data)
        assert err == [], (batch["file_name"], err)
        self._salva(batch["file_name"], data)
        self.file_ross.append(batch["file_name"])
        exports.declare_upload(c, batch["id"])
        exports.register_outcome(c, batch["id"], {"all": "accettato"})
        self.log(f"ROSS {batch['file_name']}: {info}, verificatore CONFORME")
        self.reassess()

    def _salva(self, nome: str, data: bytes) -> None:
        (self.out / nome).write_bytes(data)


def test_mese_simulato_settembre_2026(conn, orologio, tmp_path):
    out = Path(os.environ.get("GCB_EVIDENZE") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    m = Mese(conn, orologio, out)
    m.prenota()
    giorno = INIZIO
    while giorno <= add_days(FINE, 1):          # il 01/10 si dichiara il ROSS del 30/09
        orologio["giorno"] = giorno
        m.eventi()                              # arrivi, partenze, correzioni del giorno
        m.alloggiati()                          # arrivi di oggi (o di ieri registrati tardi)
        m.ross()                                # movimento della giornata precedente
        giorno = add_days(giorno, 1)

    # --- file prodotti
    assert len(m.file_alloggiati) == 5          # 01, 05, 15, 23 (arrivo del 22), 28 settembre
    assert len(m.file_ross) == 30               # una giornata per file, dal 01 al 30 settembre
    assert not conn.execute("SELECT 1 FROM export_batches WHERE status='generato'").fetchone()
    assert not conn.execute("SELECT 1 FROM corrections WHERE status='aperta'").fetchone()
    stati = {r[0] for r in conn.execute("SELECT alloggiati_status FROM guests").fetchall()}
    assert stati == {"esito_registrato"}

    # --- controlli puntuali sui file
    txt = {f: (out / f).read_bytes().decode("ascii").split("\r\n") for f in m.file_alloggiati}
    sanna = txt[m.file_alloggiati[0]]
    assert [r[:2] for r in sanna] == ["17", "19", "19", "19"] and sanna[0][105:116] == ABBASANTA_CESSATO + "CA"
    schmidt = txt[m.file_alloggiati[1]]
    assert [r[:2] for r in schmidt] == ["18", "20", "20"] and schmidt[0][64:94].rstrip() == "JURGEN"
    assert len(txt[m.file_alloggiati[2]]) == 1                       # il doppione non è mai stato comunicato
    assert txt[m.file_alloggiati[3]][0][2:12] == "22/09/2026"        # arrivo di ieri
    assert txt[m.file_alloggiati[4]][0][12:14] == "30"               # 38 giorni previsti -> 30 nel file
    ross = {f[9:17]: (out / f).read_bytes().decode() for f in m.file_ross}
    assert "<eliminazione>" in ross["20260916"]                      # generato il 17, dopo l'eliminazione
    assert all("<apertura>NO</apertura>" in ross[f"202609{x}"] for x in ("25", "26", "27"))
    assert "<partenze>" in ross["20260905"] and "<arrivi>" in ross["20260905"]   # cambio in giornata

    # --- il mese intero in un solo file: giornate consecutive, arrivi e partenze coerenti
    mese = exports.ross_build(conn, INIZIO, FINE)
    err, info = VT.verifica_ross(mese["xml"].encode())
    assert err == [] and info["giornate"] == 30 and info["eliminazioni"] == 0
    assert info["arrivi"] == 4 + 3 + 1 + 2 + 1 and info["partenze"] == 4 + 3 + 1 + 2
    # il 15/09 è cambiato dopo l'invio (doppione eliminato) ma la rettifica è stata gestita: nessuna differenza aperta
    assert not [d["day"] for d in exports.ross_preview(conn, INIZIO, FINE)["days"] if d["changed_since_declared"]]

    # --- imposta del 3° trimestre: programma contro ricalcolo indipendente e contro il conto a mano
    atteso = imposta_indipendente(m.soggiorni, "2026-07-01", "2026-10-01")
    # a mano: SANNA 4+4+0+2, SCHMIDT 3×7 (+2 oltre limite ciascuno), BIANCHI 5, DEIANA/PIRAS 2+2, TAYLOR 3 (28-30/09)
    assert atteso == {"imponibili": 43, "esenti": 6, "oltre_limite": 6, "cents": 8600}
    sheet = periods.staytour_sheet(conn, 2026, 3)
    assert sheet["pernottamenti_imponibili"] == atteso["imponibili"]
    assert sheet["pernottamenti_oltre_limite"] == atteso["oltre_limite"]
    assert sum(sheet["pernottamenti_esenti_per_motivo"].values()) == atteso["esenti"]
    assert sheet["imposta_calcolata_cents"] == atteso["cents"]
    assert sheet["da_verificare"] == 0
    assert sheet["giorni_permanenza"] == 16 + 27 + 5 + 4 + 3

    m.log(f"imposta 3° trimestre: {atteso['imponibili']} notti imponibili, € {atteso['cents'] / 100:.2f} "
          f"(programma = ricalcolo indipendente = conto a mano)")
    (out / "diario_simulazione.txt").write_text("\n".join(m.diario) + "\n", encoding="utf-8")
