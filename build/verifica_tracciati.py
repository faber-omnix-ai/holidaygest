"""Verificatore INDIPENDENTE dei file Alloggiati Web (TXT) e ROSS 1000 (XML).

Scritto a parte dal generatore: NON importa il codice del programma (app/), legge solo le tabelle ufficiali
(app/data/tabelle/*.csv) e applica le regole del Manuale Alloggiati Web e del tracciato ROSS 1000 così come
documentate in docs/TRACCIATI.md. Serve a evitare che un errore del generatore venga «confermato» dallo stesso codice.

Uso:
  python build/verifica_tracciati.py alloggiati FILE.txt --oggi AAAA-MM-GG [--formato 168|174]
  python build/verifica_tracciati.py ross FILE.xml [--riferimento CAMPIONE.xml]
Con --riferimento confronta SOLO la forma (nomi ed ordine dei tag) con un file accettato: nessun valore viene letto
o stampato da quel file.
Uscita 0 = nessun errore. Non dimostra l'accettazione dei portali: solo la conformità alle regole scritte.
"""
from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

TAB = Path(__file__).resolve().parent.parent / "app" / "data" / "tabelle"
ITALIA = "100000100"


def _table(name: str) -> dict[str, dict]:
    with open(TAB / f"{name}.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    head = rows[0]
    return {r[0].strip(): dict(zip(head, r)) for r in rows[1:] if r and r[0].strip()}


COMUNI, STATI, DOCUMENTI, TIPI = _table("comuni"), _table("stati"), _table("documenti"), _table("tipo_alloggiato")


def _fine(rec: dict) -> date | None:
    v = (rec.get("DataFineVal") or "").strip()
    return datetime.strptime(v[:10], "%d/%m/%Y").date() if v else None


def _dmy(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


# ============================ ALLOGGIATI WEB ============================
CAMPI = [("tipo", 0, 2), ("arrivo", 2, 12), ("giorni", 12, 14), ("cognome", 14, 64), ("nome", 64, 94),
         ("sesso", 94, 95), ("nascita", 95, 105), ("comune_nascita", 105, 114), ("prov_nascita", 114, 116),
         ("stato_nascita", 116, 125), ("cittadinanza", 125, 134), ("doc_tipo", 134, 139), ("doc_numero", 139, 159),
         ("doc_luogo", 159, 168)]


def verifica_alloggiati(data: bytes, oggi: date, formato: str = "168") -> tuple[list[str], dict]:
    err: list[str] = []
    L = 174 if formato == "174" else 168
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["File non in UTF-8 (il manuale chiede la codifica UTF-8)."], {}
    if not text.isascii():
        err.append("Il file contiene caratteri non ASCII.")
    if text.endswith("\r\n") or text.endswith("\n"):
        err.append("C'è un fine riga dopo l'ultima riga (non ammesso).")
    lines = text.split("\r\n")
    if any("\n" in x or "\r" in x for x in lines):
        err.append("Fine riga non CR+LF.")
    if len(lines) > 1000:
        err.append(f"{len(lines)} righe: oltre il massimo di 1000.")
    capo_aperto = None  # tipo del capo (17/18) a cui possono seguire componenti
    for n, line in enumerate(lines, 1):
        p = f"riga {n}"
        if len(line) != L:
            err.append(f"{p}: lunghezza {len(line)} invece di {L}.")
            continue
        f = {k: line[a:b] for k, a, b in CAMPI}
        tipo = f["tipo"]
        if tipo not in TIPI:
            err.append(f"{p}: tipo alloggiato «{tipo}» non presente nella tabella ufficiale.")
        arr = _dmy(f["arrivo"])
        if not arr:
            err.append(f"{p}: data di arrivo non valida (gg/mm/aaaa).")
        elif arr not in (oggi, oggi - timedelta(1)):
            err.append(f"{p}: arrivo {f['arrivo']}: il portale accetta solo oggi o ieri.")
        g = f["giorni"]
        if not (g.rstrip().isdigit() and g == g.rstrip().ljust(2) and 1 <= int(g) <= 30):
            err.append(f"{p}: giorni di permanenza «{g}» non validi (1–30, cifre allineate a sinistra).")
        for k in ("cognome", "nome"):
            v = f[k].rstrip()
            if not v:
                err.append(f"{p}: {k} vuoto.")
            elif not all(c.isalpha() or c in " '-." for c in v) or f[k] != v.ljust(len(f[k])):
                # le minuscole sono ammesse (presenti in file reali ricevuti dal portale); il programma usa il maiuscolo
                err.append(f"{p}: {k} con caratteri diversi da lettere, spazio, apostrofo, trattino o punto.")
        if f["sesso"] not in ("1", "2"):
            err.append(f"{p}: sesso «{f['sesso']}» (atteso 1 o 2).")
        nasc = _dmy(f["nascita"])
        if not nasc:
            err.append(f"{p}: data di nascita non valida.")
        elif arr and nasc > arr:
            err.append(f"{p}: nato dopo la data di arrivo.")
        stato = f["stato_nascita"].strip()
        if stato not in STATI:
            err.append(f"{p}: stato di nascita {stato} non in tabella.")
        if stato == ITALIA:
            c = COMUNI.get(f["comune_nascita"].strip())
            if not c:
                err.append(f"{p}: nato in Italia ma comune di nascita assente o non in tabella.")
            else:
                if f["prov_nascita"] != (c.get("Provincia") or "").strip():
                    err.append(f"{p}: provincia di nascita non corrispondente al comune.")
                fine = _fine(c)
                if fine and nasc and nasc > fine:
                    err.append(f"{p}: comune di nascita cessato prima della data di nascita.")
        elif f["comune_nascita"].strip() or f["prov_nascita"].strip():
            err.append(f"{p}: nato all'estero ma comune/provincia compilati.")
        if f["cittadinanza"].strip() not in STATI:
            err.append(f"{p}: cittadinanza non in tabella.")
        doc = line[134:168]
        if tipo in ("19", "20"):
            if doc.strip():
                err.append(f"{p}: familiare/componente con dati del documento (vanno lasciati vuoti).")
            atteso = {"19": "17", "20": "18"}[tipo]
            if capo_aperto != atteso:
                err.append(f"{p}: componente {tipo} non preceduto dal proprio capo {atteso}.")
        else:
            capo_aperto = tipo if tipo in ("17", "18") else None
            if f["doc_tipo"].strip() not in DOCUMENTI:
                err.append(f"{p}: tipo di documento non in tabella.")
            if not f["doc_numero"].strip():
                err.append(f"{p}: numero documento vuoto.")
            luogo = f["doc_luogo"].strip()
            if luogo not in COMUNI and luogo not in STATI:
                err.append(f"{p}: luogo di rilascio non è un comune né uno Stato della tabella.")
        if formato == "174":
            ida = line[168:174]
            if not ida.isdigit():
                err.append(f"{p}: ID appartamento non numerico.")
    return err, {"righe": len(lines), "lunghezza": L}


# ============================ ROSS 1000 ============================
ORDINE_ARRIVO = ["idswh", "tipoalloggiato", "idcapo", "cognome", "nome", "sesso", "cittadinanza", "statoresidenza",
                 "luogoresidenza", "datanascita", "statonascita", "comunenascita", "tipoturismo", "mezzotrasporto",
                 "canaleprenotazione", "titolostudio", "professione", "esenzioneimposta"]
OBBLIGATORI_ARRIVO = ["idswh", "tipoalloggiato", "idcapo", "sesso", "cittadinanza", "statoresidenza", "luogoresidenza",
                      "datanascita", "statonascita", "comunenascita"]


def _ymd(s: str | None) -> date | None:
    try:
        return datetime.strptime(s or "", "%Y%m%d").date()
    except ValueError:
        return None


def _ordinato(tags: list[str], ordine: list[str]) -> bool:
    idx = [ordine.index(t) for t in tags if t in ordine]
    return idx == sorted(idx) and all(t in ordine for t in tags)


def verifica_ross(data: bytes) -> tuple[list[str], dict]:
    err: list[str] = []
    try:
        text = data.decode("utf-8")
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError) as ex:
        return [f"XML non leggibile o non UTF-8: {ex}"], {}
    if root.tag != "movimenti":
        err.append("Elemento radice diverso da <movimenti>.")
    kids = [c.tag for c in root]
    if kids[:2] != ["codice", "prodotto"] or not (root.findtext("codice") or "").strip():
        err.append("<codice> (non vuoto) e <prodotto> devono precedere i movimenti.")
    movs = root.findall("movimento")
    if not movs:
        err.append("Nessun <movimento>.")
    ids_arrivati: dict[str, dict] = {}
    presenti: set[str] = set()
    prev = None
    n_arr = n_par = n_del = 0
    for m in movs:
        d = _ymd(m.findtext("data"))
        p = f"giornata {m.findtext('data')}"
        if not d:
            err.append(f"{p}: data non valida (AAAAMMGG).")
            continue
        if prev and d != prev + timedelta(1):
            err.append(f"{p}: giornate non consecutive (dopo {prev:%Y%m%d}).")
        prev = d
        s = m.find("struttura")
        if s is None:
            err.append(f"{p}: manca <struttura>.")
            continue
        try:
            occ, disp, letti = (int(s.findtext(k)) for k in ("camereoccupate", "cameredisponibili", "lettidisponibili"))
        except (TypeError, ValueError):
            err.append(f"{p}: valori di struttura non numerici.")
            continue
        ap = s.findtext("apertura")
        if ap not in ("SI", "NO"):
            err.append(f"{p}: apertura «{ap}» (atteso SI/NO).")
        if occ > disp or min(occ, disp, letti) < 0:
            err.append(f"{p}: camere occupate oltre le disponibili o valori negativi.")
        if ap == "NO" and (occ or disp or letti):
            err.append(f"{p}: giornata di chiusura con valori diversi da zero.")
        for a in m.findall("arrivi/arrivo"):
            n_arr += 1
            tags = [c.tag for c in a]
            mancanti = [t for t in OBBLIGATORI_ARRIVO if t not in tags]
            if mancanti:
                err.append(f"{p}: arrivo senza {', '.join(mancanti)}.")
            if not _ordinato(tags, ORDINE_ARRIVO):
                err.append(f"{p}: elementi dell'arrivo fuori ordine o sconosciuti: {tags}.")
            v = {t: (a.findtext(t) or "") for t in ORDINE_ARRIVO}
            i = v["idswh"]
            if not (1 <= len(i) <= 20):
                err.append(f"{p}: idswh vuoto o oltre 20 caratteri.")
            if i in ids_arrivati:
                err.append(f"{p}: idswh {i} già usato per un altro arrivo.")
            t = v["tipoalloggiato"]
            if t not in TIPI:
                err.append(f"{p}: tipoalloggiato {t} non valido.")
            if t in ("16", "17", "18") and v["idcapo"]:
                err.append(f"{p}: idcapo compilato per un ospite singolo o capo.")
            if t in ("19", "20"):
                capo = ids_arrivati.get(v["idcapo"])
                if not capo or capo["tipo"] != {"19": "17", "20": "18"}[t]:
                    err.append(f"{p}: idcapo {v['idcapo']} non corrisponde a un capo arrivato prima nel file.")
            if v["sesso"] not in ("M", "F"):
                err.append(f"{p}: sesso «{v['sesso']}» (atteso M/F).")
            for k in ("cittadinanza", "statoresidenza", "statonascita"):
                if v[k] not in STATI:
                    err.append(f"{p}: {k} {v[k]} non in tabella Stati.")
            if v["statoresidenza"] == ITALIA and v["luogoresidenza"] not in COMUNI:
                err.append(f"{p}: residente in Italia senza comune di residenza valido.")
            if v["statoresidenza"] != ITALIA and v["luogoresidenza"]:
                err.append(f"{p}: residente all'estero con luogoresidenza compilato (atteso vuoto).")
            dn = _ymd(v["datanascita"])
            if not dn or dn > d:
                err.append(f"{p}: data di nascita non valida o successiva all'arrivo.")
            if v["statonascita"] == ITALIA:
                c = COMUNI.get(v["comunenascita"])
                if not c:
                    err.append(f"{p}: nato in Italia senza comune di nascita valido.")
                elif _fine(c) and dn and dn > _fine(c):
                    err.append(f"{p}: comune di nascita cessato prima della nascita.")
            elif v["comunenascita"]:
                err.append(f"{p}: nato all'estero con comunenascita compilato.")
            ids_arrivati[i] = {"tipo": t, "arrivo": d}
            presenti.add(i)
        for q in m.findall("partenze/partenza"):
            n_par += 1
            i, arr = q.findtext("idswh") or "", _ymd(q.findtext("arrivo"))
            if not arr or arr > d:
                err.append(f"{p}: partenza con data di arrivo non valida o futura.")
            if i in ids_arrivati and ids_arrivati[i]["arrivo"] != arr:
                err.append(f"{p}: partenza di {i} con data di arrivo diversa da quella dichiarata.")
            presenti.discard(i)
        for e in m.findall("rettifiche/eliminazione"):
            n_del += 1
            if not (e.findtext("idswh") and _ymd(e.findtext("arrivo")) and e.findtext("tipoalloggiato") in TIPI):
                err.append(f"{p}: eliminazione incompleta.")
        # coerenza presenze note dal file (chi è arrivato nel file e non ancora partito)
        if presenti and occ == 0 and ap == "SI":
            err.append(f"{p}: ospiti presenti ({len(presenti)}) ma camere occupate 0.")
    return err, {"giornate": len(movs), "arrivi": n_arr, "partenze": n_par, "eliminazioni": n_del}


def forma_xml(data: bytes) -> dict[str, list[str]]:
    """Per ogni elemento, la sequenza dei tag figli (senza ripetizioni consecutive). Nessun valore."""
    root = ET.fromstring(data.decode("utf-8", errors="replace").lstrip("﻿"))
    out: dict[str, list[str]] = {}

    def walk(el):
        seq = []
        for c in el:
            if not seq or seq[-1] != c.tag:
                seq.append(c.tag)
            walk(c)
        if seq:
            cur = out.setdefault(el.tag, [])
            for t in seq:  # unione ordinata delle sequenze viste
                if t not in cur:
                    cur.append(t)

    walk(root)
    return out


def confronta_forma(nostro: bytes, riferimento: bytes) -> list[str]:
    a, b = forma_xml(nostro), forma_xml(riferimento)
    diff = []
    for tag in sorted(set(a) | set(b)):
        x, y = a.get(tag, []), b.get(tag, [])
        solo_nostro = [t for t in x if t not in y]
        solo_rif = [t for t in y if t not in x]
        comuni = [t for t in x if t in y]
        if [t for t in y if t in x] != comuni:
            diff.append(f"<{tag}>: ordine dei figli diverso dal file di riferimento.")
        if solo_nostro:
            diff.append(f"<{tag}>: elementi presenti solo nel nostro file: {solo_nostro}.")
        if solo_rif:
            diff.append(f"<{tag}>: elementi presenti solo nel file di riferimento (facoltativi o non usati): {solo_rif}.")
    return diff


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tipo", choices=["alloggiati", "ross"])
    ap.add_argument("file")
    ap.add_argument("--oggi")
    ap.add_argument("--formato", default="168")
    ap.add_argument("--riferimento")
    ap.add_argument("--anonimo", action="store_true",
                    help="per file REALI: stampa solo categorie e conteggi degli errori, mai valori; niente finestra oggi/ieri")
    a = ap.parse_args(argv)
    data = Path(a.file).read_bytes()
    if a.tipo == "alloggiati":
        err, info = verifica_alloggiati(data, date.fromisoformat(a.oggi or date.today().isoformat()), a.formato)
        if a.anonimo:
            err = [e for e in err if "solo oggi o ieri" not in e]
    else:
        err, info = verifica_ross(data)
        if a.riferimento:
            for x in confronta_forma(data, Path(a.riferimento).read_bytes()):
                print("FORMA  " + x)
    print(f"{a.tipo}: {info}" if a.anonimo else f"{a.tipo} {Path(a.file).name}: {info}")
    if a.anonimo:
        import re
        from collections import Counter
        cat = Counter(re.sub(r"«[^»]*»|\w*\d\w*|\[[^\]]*\]", "#", e) for e in err)
        for k, n in cat.most_common():
            print(f"ERRORE x{n}: {k}")
    else:
        for e in err:
            print("ERRORE " + e)
    print("ESITO: " + ("CONFORME alle regole verificate" if not err else f"{len(err)} ERRORI"))
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
