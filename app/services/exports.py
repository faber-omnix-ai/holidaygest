"""Centro esportazioni: Alloggiati Web (TXT) e ROSS 1000 Sardegna (XML).

Tre livelli distinti e mai confusi:
  1. file formalmente valido (tracciato/schema locale);
  2. dati coerenti secondo i controlli locali;
  3. file accettato dal portale -> SOLO quando l'operatrice registra l'esito.
Stati lotto: generato -> caricamento_dichiarato -> esito_registrato | da_correggere; superato.
I file non vengono conservati: si registrano metadati e impronte (HMAC), non il contenuto.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import date
from xml.sax.saxutils import escape

from .. import config
from ..db import AppError, audit, get_setting, now_iso, row, rows, today_iso
from ..state import STATE
from ..util import add_days, d, nights
from ..util import it as it_date
from . import guests as G
from . import tables

ALLOGGIATI_PROFILE = "Alloggiati Web tracciato {fmt} caratteri (Manuale Alloggiati Web, par. 12/12.1)"
ALLOGGIATI_MAX_LINES = 1000   # manuale: «massimo di 1000 righe» per file
ALLOGGIATI_MAX_DAYS = 30      # manuale: permanenza «massimo 30 gg»
ROSS_PROFILE = "ROSS 1000 XML v3 18/03/2026 (GIES)"
BATCH_LABEL = {"da_preparare": "Da preparare", "bloccato": "Bloccato per dati mancanti", "generato": "Generato",
               "caricamento_dichiarato": "Caricamento dichiarato", "esito_registrato": "Esito registrato",
               "da_correggere": "Da correggere", "superato": "Superato (rigenerare)"}
TOURISM = ["Culturale", "Balneare", "Congressuale/Affari", "Fieristico", "Sportivo/Fitness", "Scolastico",
           "Religioso", "Sociale", "Parchi Tematici", "Termale/Trattamenti salute", "Enogastronomico",
           "Cicloturismo", "Escursionistico/Naturalistico", "Altro motivo", "Non specificato"]
TRANSPORT = ["Auto", "Aereo", "Aereo+Pullman", "Aereo+Navetta/Taxi/Auto", "Aereo+Treno", "Treno", "Pullman",
             "Caravan/Autocaravan", "Barca/Nave/Traghetto", "Moto", "Bicicletta", "A piedi", "Altro mezzo",
             "Non Specificato"]
CHANNEL = ["Diretta tradizionale", "Diretta web", "Indiretta tradizionale", "Indiretta web", "Altro canale",
           "Non specificato"]


def _fp(text: str) -> str:
    key = hashlib.sha256(STATE.require_dek() + b"impronta-export").digest()
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _dmy(iso: str) -> str:
    x = d(iso)
    return f"{x.day:02d}/{x.month:02d}/{x.year}"


# ======================= ALLOGGIATI WEB =======================
def _profile(conn) -> dict:
    st = get_setting(conn, "structure", {}) or {}
    p = st.get("alloggiati") or {}
    return {"format": p.get("format", "168"), "apartment_id": (p.get("apartment_id") or "").strip(),
            "ross_sends": st.get("ross_sends_alloggiati")}


def _guest_departure(g: dict, b: dict) -> str:
    return g["stay_departure"] or g["planned_departure"] or b["departure"]


_FOLD = {"ß": "SS", "Ø": "O", "Æ": "AE", "Œ": "OE", "Ł": "L", "Đ": "D", "Þ": "TH", "’": "'"}


def _ascii_name(s: str) -> str:
    """Maiuscolo senza segni diacritici (MÜLLER -> MULLER), come nelle schedine accettate esaminate."""
    import unicodedata
    s = "".join(_FOLD.get(c, c) for c in (s or "").upper())
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def alloggiati_record(g: dict, b: dict, doc: dict, prof: dict) -> tuple[str, str, list[str]]:
    """Restituisce (riga, parte_senza_documento, avvisi). Presuppone dati già controllati."""
    warn = []
    days = len(nights(g["stay_arrival"], _guest_departure(g, b)))
    if days > ALLOGGIATI_MAX_DAYS:  # ammesso solo con conferma esplicita (alloggiati_generate)
        warn.append(f"Permanenza prevista di {days} giorni: nel file è indicato {ALLOGGIATI_MAX_DAYS}, il massimo "
                    "ammesso dal tracciato.")
        days = ALLOGGIATI_MAX_DAYS
    italy = g["birth_state_code"] == tables.ITALIA
    sur, nam = _ascii_name(g["surname"]), _ascii_name(g["name"])
    if (sur, nam) != (g["surname"].upper(), g["name"].upper()):
        warn.append(f"Nel file il nome è scritto senza accenti: «{sur} {nam}» (scheda invariata).")
    head = (g["guest_type"].ljust(2) + _dmy(g["stay_arrival"]) + str(days).ljust(2) + sur.ljust(50)
            + nam.ljust(30) + ("1" if g["sex"] == "M" else "2") + _dmy(g["birth_date"])
            + ((g["birth_comune_code"] or "").ljust(9) if italy else " " * 9)
            + ((g["birth_province"] or "").ljust(2) if italy else " " * 2)
            + g["birth_state_code"].ljust(9) + g["citizenship_code"].ljust(9))
    if g["guest_type"] in ("16", "17", "18"):
        docpart = doc["type"].ljust(5) + doc["number"].ljust(20) + doc["issue_place"].ljust(9)
    else:
        docpart = " " * 34
    line = head + docpart
    if prof["format"] == "174":
        line += prof["apartment_id"].rjust(6, "0")
    if any(ord(ch) > 127 for ch in line):  # già escluso in anteprima: qui solo per sicurezza
        raise AppError("Errore interno: carattere non ASCII nella riga Alloggiati.")
    return line, head, warn


def alloggiati_preview(conn: sqlite3.Connection, start: str, end: str, include_sent: bool = False) -> dict:
    """Chi è incluso e chi è escluso (con motivo) per gli arrivi effettivi in [start, end]."""
    prof = _profile(conn)
    errors_profile = []
    if prof["format"] not in ("168", "174"):
        errors_profile.append("Formato tracciato non configurato.")
    if prof["format"] == "174" and not (prof["apartment_id"].isdigit() and len(prof["apartment_id"]) <= 6):
        errors_profile.append("Formato con ID appartamento: indicare l'ID numerico (max 6 cifre) presente "
                              "nell'elenco appartamenti del portale.")
    end_x = add_days(end, 1)
    yesterday = add_days(today_iso(), -1)
    cand = rows(conn.execute(
        "SELECT g.*, b.ref, b.arrival b_arrival, b.departure, b.status b_status FROM guests g "
        "JOIN bookings b ON b.id=g.booking_id WHERE g.anonymized_at IS NULL AND "
        "((g.stay_arrival >= ? AND g.stay_arrival < ?) OR "
        " (g.presence='prevista' AND COALESCE(g.planned_arrival, b.arrival) >= ? AND "
        "  COALESCE(g.planned_arrival, b.arrival) < ? AND b.status IN ('confermata','in_corso'))) "
        "ORDER BY g.stay_arrival, g.booking_id, g.position, g.id", (start, end_x, start, end_x)))
    included, excluded = [], []
    by_id = {}
    for g in cand:
        b = {"departure": g["departure"], "arrival": g["b_arrival"]}
        info = {"guest_id": g["id"], "booking_id": g["booking_id"], "ref": g["ref"],
                "nome": f"{g['surname']} {g['name']}", "tipo": G.GUEST_TYPES[g["guest_type"]],
                "arrivo": g["stay_arrival"], "stato": g["alloggiati_status"]}
        reasons = []
        if g["presence"] == "prevista":
            reasons.append("Arrivo non ancora registrato (check-in): una prenotazione non è una presenza.")
        elif g["presence"] == "non_arrivata":
            reasons.append("Ospite segnato come non arrivato.")
        if not include_sent and g["alloggiati_status"] in ("caricamento_dichiarato", "esito_registrato"):
            reasons.append("Già comunicato (caricamento dichiarato/esito registrato): per reinviarlo serve "
                           "una scelta esplicita.")
        if not g["verified_at"]:
            reasons.append("Dati anagrafici non ancora verificati.")
        if g["stay_arrival"] and g["presence"] != "prevista" and g["stay_arrival"] < yesterday:
            reasons.append(f"Arrivo del {it_date(g['stay_arrival'])}: il portale accetta nel file solo arrivi di "
                           "oggi o di ieri (Manuale Alloggiati Web). Per una comunicazione tardiva rivolgersi "
                           "alla Questura.")
        bad_chars = sorted({c for c in _ascii_name(g["surname"]) + _ascii_name(g["name"]) if ord(c) > 127})
        if bad_chars:
            reasons.append(f"Cognome o nome con caratteri non latini ({' '.join(bad_chars)}): scrivere la "
                           "traslitterazione in lettere latine riportata sul documento.")
        doc = {}
        if not reasons:
            doc = G.doc_of(g)
            errs = G.check(g, doc, "alloggiati")
            reasons += [f"{e['field']}: {e['message']}" for e in errs]
            if any(ord(c) > 127 for c in "".join(str(v or "") for v in doc.values())):
                reasons.append("Dati del documento con caratteri non ASCII: correggere il numero del documento.")
        info["reasons"] = reasons
        info["_g"], info["_b"], info["_doc"] = g, b, doc
        by_id[g["id"]] = info
        (excluded if reasons else included).append(info)
    # vincolo gruppi/famiglie: componenti subito dopo il proprio capo, nello stesso file
    for info in list(included):
        g = info["_g"]
        if g["guest_type"] in ("19", "20"):
            leader = by_id.get(g["leader_guest_id"])
            if not leader or leader not in included:
                info["reasons"].append("Il capofamiglia/capogruppo non è incluso in questo file: i componenti "
                                       "vanno trasmessi subito dopo il proprio capo.")
                included.remove(info)
                excluded.append(info)
    for info in list(included):
        g = info["_g"]
        if g["guest_type"] in ("17", "18"):
            members = [x for x in cand if x["leader_guest_id"] == g["id"]]
            bad = [m for m in members if by_id[m["id"]] in excluded and m["presence"] == "presente"]
            if bad:
                info["warnings"] = [f"{len(bad)} componenti esclusi: l'esportazione del gruppo sarà parziale."]
    ordered = []
    for info in included:
        g = info["_g"]
        if g["guest_type"] in ("19", "20"):
            continue
        ordered.append(info)
        if g["guest_type"] in ("17", "18"):
            ordered += [x for x in included if x["_g"]["leader_guest_id"] == g["id"]]
    lines, warnings, long_stays = [], [], []
    for info in ordered:
        n_days = len(nights(info["_g"]["stay_arrival"], _guest_departure(info["_g"], info["_b"])))
        if n_days > ALLOGGIATI_MAX_DAYS:
            long_stays.append(f"{info['nome']} ({n_days} giorni)")
        line, head, w = alloggiati_record(info["_g"], info["_b"], info["_doc"], prof)
        expected = 174 if prof["format"] == "174" else 168
        if len(line) != expected:
            raise AppError(f"Errore interno: riga di {len(line)} caratteri invece di {expected}.")
        info["_line"], info["_head"] = line, head
        warnings += [f"{info['nome']}: {x}" for x in w + info.get("warnings", [])]
    if len(ordered) > ALLOGGIATI_MAX_LINES:
        errors_profile.append(f"Il file avrebbe {len(ordered)} righe: il portale ne accetta al massimo "
                              f"{ALLOGGIATI_MAX_LINES}. Ridurre il periodo.")
    if prof["ross_sends"]:
        warnings.insert(0, "Impostazioni: la struttura usa la funzione ROSS 1000 di trasmissione ad Alloggiati. "
                           "Caricare anche questo file creerebbe un DOPPIO INVIO.")
    clean = lambda lst: [{k: v for k, v in x.items() if not k.startswith("_")} for x in lst]  # noqa: E731
    return {"included": clean(ordered), "excluded": clean(excluded), "warnings": warnings,
            "profile_errors": errors_profile, "profile": ALLOGGIATI_PROFILE.format(fmt=prof["format"]),
            "tables": tables.version_label(), "_ordered": ordered, "partial": bool(excluded),
            "long_stays": long_stays}


def alloggiati_generate(conn: sqlite3.Connection, start: str, end: str, confirm_partial: bool,
                        include_sent: bool = False, confirm_double: bool = False,
                        confirm_long_stay: bool = False) -> tuple[dict, bytes]:
    p = alloggiati_preview(conn, start, end, include_sent)
    if p["profile_errors"]:
        raise AppError("; ".join(p["profile_errors"]))
    if not p["_ordered"]:
        raise AppError("Nessun ospite esportabile nel periodo.", extra={k: v for k, v in p.items() if k[0] != "_"})
    if p["excluded"] and not confirm_partial:
        raise AppError("Alcuni ospiti sono esclusi: confermare esplicitamente l'esportazione parziale.",
                       extra={k: v for k, v in p.items() if k[0] != "_"})
    if p["long_stays"] and not confirm_long_stay:
        raise AppError(f"Permanenza oltre {ALLOGGIATI_MAX_DAYS} giorni ({', '.join(p['long_stays'])}): il tracciato "
                       f"ammette al massimo {ALLOGGIATI_MAX_DAYS}. Confermare esplicitamente per indicare "
                       f"{ALLOGGIATI_MAX_DAYS} nel file.", extra={"needs_long_stay_ack": True})
    if _profile(conn)["ross_sends"] and not confirm_double:
        raise AppError("Rischio di doppio invio (ROSS trasmette già ad Alloggiati): confermare esplicitamente.")
    content = "\r\n".join(i["_line"] for i in p["_ordered"])  # nessun CR+LF dopo l'ultima riga
    data = content.encode("utf-8")  # manuale: «codifica UTF-8»; il contenuto è comunque solo ASCII
    prof = _profile(conn)
    checks = {"righe": len(p["_ordered"]), "lunghezza": 174 if prof["format"] == "174" else 168,
              "terminatore": "CR+LF tranne l'ultima riga", "codifica": "UTF-8 (solo caratteri ASCII)",
              "esclusi": len(p["excluded"]), "avvisi": len(p["warnings"]), "tabelle": p["tables"]}
    ts = now_iso()
    fname = f"alloggiati_{start.replace('-', '')}_{end.replace('-', '')}.txt"
    cur = conn.execute(
        "INSERT INTO export_batches(kind,created_at,period_from,period_to,file_name,sha256,item_count,profile,"
        "checks,status) VALUES ('alloggiati',?,?,?,?,?,?,?,?,'generato')",
        (ts, start, end, fname, hashlib.sha256(data).hexdigest(), len(p["_ordered"]), p["profile"],
         json.dumps(checks, ensure_ascii=False)))
    bid = cur.lastrowid
    fname = fname.replace(".txt", f"_lotto{bid}.txt")
    conn.execute("UPDATE export_batches SET file_name=? WHERE id=?", (fname, bid))
    for info in p["_ordered"]:
        g = info["_g"]
        fp = _fp(info["_head"]) + ":" + _fp(info["_line"][len(info["_head"]):])
        conn.execute("INSERT INTO export_items(batch_id,guest_id,fingerprint) VALUES (?,?,?)", (bid, g["id"], fp))
        # lotti precedenti non usati che contenevano lo stesso ospite diventano superati
        for old in rows(conn.execute(
                "SELECT DISTINCT b.id FROM export_batches b JOIN export_items i ON i.batch_id=b.id "
                "WHERE b.kind='alloggiati' AND b.status='generato' AND b.id != ? AND i.guest_id=?", (bid, g["id"]))):
            conn.execute("UPDATE export_batches SET status='superato', superseded_reason=? WHERE id=?",
                         (f"Rigenerato nel lotto {bid}", old["id"]))
        if g["alloggiati_status"] not in ("caricamento_dichiarato", "esito_registrato"):
            conn.execute("UPDATE guests SET alloggiati_status='generato' WHERE id=?", (g["id"],))
    audit(conn, "export_generato", "export_batch", bid, f"alloggiati {len(p['_ordered'])} righe")
    return row(conn.execute("SELECT * FROM export_batches WHERE id=?", (bid,))), data


# ======================= ROSS 1000 =======================
def _ross_cfg(conn) -> dict:
    st = get_setting(conn, "structure", {}) or {}
    r = st.get("ross") or {}
    return {"code": (r.get("code") or "").strip(), "units": r.get("units"), "beds": r.get("beds"),
            "include_names": r.get("include_names", False), "include_bookings": r.get("include_bookings", False),
            "prefix": st.get("id_prefix") or "GC"}


def ross_id(prefix: str, kind: str, n: int) -> str:
    return f"{prefix}{kind}{n}"[:20]


def _x(tag: str, val) -> str:
    return f"<{tag}>{escape('' if val is None else str(val))}</{tag}>"


def _xo(tag: str, val) -> str:
    """Elemento facoltativo: omesso se vuoto (come nei file ROSS 1000 prodotti da altri gestionali e accettati)."""
    return _x(tag, val) if val not in (None, "") else ""


def _ross_open_deletions(conn) -> list[dict]:
    """Eliminazioni non ancora trasmesse: mai incluse in un file, oppure incluse solo in file generati e non
    dichiarati caricati (scartati o rigenerati): devono ricomparire nel file successivo."""
    return rows(conn.execute(
        "SELECT p.* FROM ross_pending_deletions p LEFT JOIN export_batches b ON b.id=p.sent_batch "
        "WHERE p.sent_batch IS NULL OR b.status IN ('generato','superato') ORDER BY p.id"))


def ross_build(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Costruisce i movimenti giornalieri [start, end] (incluso). Nessun valore inventato."""
    cfg = _ross_cfg(conn)
    errs_cfg = []
    if not cfg["code"]:
        errs_cfg.append("Codice struttura ROSS 1000 non configurato (assegnato dall'ente: non coincide con CIN/IUN).")
    for k, lbl in (("units", "unità ricettive disponibili"), ("beds", "letti disponibili")):
        try:
            if cfg[k] is None or int(cfg[k]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            errs_cfg.append(f"Valore ROSS «{lbl}» non configurato.")
    today = now_iso()[:10]
    ross_warn = []
    if end > today:
        errs_cfg.append("Il periodo non può includere giornate future: i movimenti riguardano giornate già iniziate.")
    elif end == today:
        ross_warn.append("È inclusa la giornata di oggi: se in seguito arriva o parte qualcuno, il movimento di oggi "
                         "andrà ritrasmesso (il programma lo segnalerà).")
    days = [n.isoformat() for n in nights(start, add_days(end, 1))]
    closures = rows(conn.execute("SELECT * FROM closures WHERE start <= ? AND end_excl > ?", (end, start)))
    gs = rows(conn.execute(
        "SELECT g.*, b.tourism_type, b.transport, b.booking_channel, b.ref FROM guests g "
        "JOIN bookings b ON b.id=g.booking_id WHERE g.stay_arrival IS NOT NULL AND g.anonymized_at IS NULL "
        "AND g.stay_arrival <= ? AND COALESCE(g.stay_departure, '9999-12-31') >= ?", (end, start)))
    gmap = {g["id"]: g for g in gs}
    excluded, day_xml, day_core, day_info = [], {}, {}, []
    bad = set()
    for g in gs:
        e = G.check(g, None, "ross")
        if g["guest_type"] in ("19", "20") and g["leader_guest_id"] not in gmap:
            e.append({"field": "idcapo", "message": "Capofamiglia/capogruppo non presente nel periodo."})
        if e:
            bad.add(g["id"])
            excluded.append({"guest_id": g["id"], "booking_id": g["booking_id"], "ref": g["ref"],
                             "nome": f"{g['surname']} {g['name']}",
                             "reasons": [f"{x['field']}: {x['message']}" for x in e]})
    pend = _ross_open_deletions(conn)
    for i, day in enumerate(days):
        closed = any(c["start"] <= day < c["end_excl"] for c in closures)
        present = [g for g in gs if g["stay_arrival"] <= day and (g["stay_departure"] or "9999") > day]
        units, beds = int(cfg["units"] or 0), int(cfg["beds"] or 0)
        occ = units if [g for g in present if g["id"] not in bad] else 0  # coerente con gli arrivi inclusi
        if closed and present:
            excluded.append({"guest_id": None, "ref": day, "nome": "",
                             "reasons": [f"{day}: chiusura ROSS registrata ma risultano ospiti presenti."]})
        parts = [f"<movimento>{_x('data', day.replace('-', ''))}<struttura>"
                 f"{_x('apertura', 'NO' if closed else 'SI')}{_x('camereoccupate', 0 if closed else occ)}"
                 f"{_x('cameredisponibili', 0 if closed else units)}{_x('lettidisponibili', 0 if closed else beds)}"
                 f"</struttura>"]
        arr = [g for g in gs if g["stay_arrival"] == day and g["id"] not in bad]
        arr.sort(key=lambda g: (g["guest_type"] in ("19", "20"), g["id"]))
        if arr:
            parts.append("<arrivi>")
            for g in arr:
                italy_birth = g["birth_state_code"] == tables.ITALIA
                luogo = g["res_comune_code"] if g["res_state_code"] == tables.ITALIA else ""  # estero: vuoto
                parts.append(
                    "<arrivo>" + _x("idswh", ross_id(cfg["prefix"], "G", g["id"])) + _x("tipoalloggiato", g["guest_type"])
                    + _x("idcapo", ross_id(cfg["prefix"], "G", g["leader_guest_id"]) if g["leader_guest_id"] else "")
                    + ((_x("cognome", g["surname"]) + _x("nome", g["name"])) if cfg["include_names"] else "")
                    + _x("sesso", g["sex"]) + _x("cittadinanza", g["citizenship_code"])
                    + _x("statoresidenza", g["res_state_code"]) + _x("luogoresidenza", luogo)
                    + _x("datanascita", g["birth_date"].replace("-", "")) + _x("statonascita", g["birth_state_code"])
                    + _x("comunenascita", g["birth_comune_code"] if italy_birth else "")
                    + _xo("tipoturismo", (g["tourism_type"] or "").upper())
                    + _xo("mezzotrasporto", (g["transport"] or "").upper())
                    + _xo("canaleprenotazione", (g["booking_channel"] or "").upper()) + "</arrivo>")
            parts.append("</arrivi>")
        dep = [g for g in gs if g["stay_departure"] == day and g["id"] not in bad]
        if dep:
            parts.append("<partenze>" + "".join(
                "<partenza>" + _x("idswh", ross_id(cfg["prefix"], "G", g["id"])) + _x("tipoalloggiato", g["guest_type"])
                + _x("arrivo", g["stay_arrival"].replace("-", "")) + "</partenza>" for g in dep) + "</partenze>")
        if cfg["include_bookings"]:
            bks = rows(conn.execute("SELECT * FROM bookings WHERE substr(created_at,1,10)=? AND status IN "
                                    "('confermata','in_corso','conclusa')", (day,)))
            if bks:
                parts.append("<prenotazioni>" + "".join(
                    "<prenotazione>" + _x("idswh", ross_id(cfg["prefix"], "P", b["id"]))
                    + _x("arrivo", b["arrival"].replace("-", "")) + _x("partenza", b["departure"].replace("-", ""))
                    + _x("ospiti", b["guests_expected"]) + _x("camere", units) + _x("prezzo", "")
                    + _x("canaleprenotazione", (b["booking_channel"] or "").upper()) + _x("statoprovenienza", "")
                    + _x("comuneprovenienza", "") + "</prenotazione>" for b in bks) + "</prenotazioni>")
        day_core[day] = "".join(parts)  # impronta: senza rettifiche, che cambiano dopo l'invio
        if i == 0 and pend:
            parts.append("<rettifiche>" + "".join(
                "<eliminazione>" + _x("idswh", p["idswh"]) + _x("tipoalloggiato", p["tipo"])
                + _x("arrivo", p["arrivo"].replace("-", "")) + "</eliminazione>" for p in pend) + "</rettifiche>")
        parts.append("</movimento>")
        day_xml[day] = "".join(parts)
        day_info.append({"day": day, "closed": closed, "present": len(present), "arrivals": len(arr),
                         "departures": len(dep)})
    # Senza dichiarazione XML (UTF-8 implicito): come i file ROSS 1000 di altri gestionali già accettati.
    body = (f'<movimenti>{_x("codice", cfg["code"])}'
            f'{_x("prodotto", f"{config.APP_NAME} {config.VERSION}")}' + "".join(day_xml[x] for x in days)
            + "</movimenti>")
    return {"xml": body, "days": day_info, "day_xml": day_xml, "day_core": day_core, "excluded": excluded, "config_errors": errs_cfg,
            "warnings": ross_warn,
            "pending_deletions": len(pend), "profile": ROSS_PROFILE}


def ross_validate(xml: str) -> list[str]:
    from lxml import etree
    xsd = etree.XMLSchema(etree.parse(str(config.bundled_data_dir() / "ross1000_interno.xsd")))
    doc = etree.fromstring(xml.encode("utf-8"))
    if xsd.validate(doc):
        return []
    return [f"riga {e.line}: {e.message}" for e in xsd.error_log][:30]


def ross_preview(conn, start: str, end: str) -> dict:
    r = ross_build(conn, start, end)
    r["schema_errors"] = ross_validate(r["xml"]) if not r["config_errors"] else []
    sent = {x["ross_day"]: x for x in rows(conn.execute(
        "SELECT i.ross_day, i.fingerprint, b.status, b.id batch_id FROM export_items i JOIN export_batches b "
        "ON b.id=i.batch_id WHERE b.kind='ross' AND b.status IN ('caricamento_dichiarato','esito_registrato') "
        "AND i.ross_day BETWEEN ? AND ? ORDER BY b.id", (start, end)))}
    for di in r["days"]:
        prev = sent.get(di["day"])
        di["previously_declared"] = bool(prev)
        di["changed_since_declared"] = bool(prev and prev["fingerprint"] != _fp(r["day_core"][di["day"]]))
    out = {k: v for k, v in r.items() if k not in ("xml", "day_xml", "day_core")}
    return out


def ross_generate(conn, start: str, end: str, confirm_partial: bool) -> tuple[dict, bytes]:
    r = ross_build(conn, start, end)
    if r["config_errors"]:
        raise AppError("; ".join(r["config_errors"]))
    schema_errors = ross_validate(r["xml"])
    if schema_errors:
        raise AppError("Il file non supera il controllo strutturale locale.", extra={"errors": schema_errors})
    if r["excluded"] and not confirm_partial:
        raise AppError("Alcuni ospiti sono esclusi per dati mancanti: correggere o confermare l'esportazione "
                       "parziale (i conteggi del giorno potrebbero non essere coerenti).",
                       extra={"excluded": r["excluded"]})
    data = r["xml"].encode("utf-8")
    checks = {"giorni": len(r["days"]), "schema_locale": "superato (schema interno non ufficiale)",
              "esclusi": len(r["excluded"]), "eliminazioni": r["pending_deletions"]}
    cur = conn.execute(
        "INSERT INTO export_batches(kind,created_at,period_from,period_to,file_name,sha256,item_count,profile,checks,"
        "status) VALUES ('ross',?,?,?,?,?,?,?,?,'generato')",
        (now_iso(), start, end, "tmp", hashlib.sha256(data).hexdigest(), len(r["days"]), r["profile"],
         json.dumps(checks, ensure_ascii=False)))
    bid = cur.lastrowid
    fname = f"ross1000_{start.replace('-', '')}_{end.replace('-', '')}_lotto{bid}.xml"
    conn.execute("UPDATE export_batches SET file_name=? WHERE id=?", (fname, bid))
    for day, x in r["day_core"].items():
        conn.execute("INSERT INTO export_items(batch_id,ross_day,fingerprint) VALUES (?,?,?)", (bid, day, _fp(x)))
    for old in rows(conn.execute(
            "SELECT DISTINCT b.id FROM export_batches b JOIN export_items i ON i.batch_id=b.id WHERE b.kind='ross' "
            "AND b.status='generato' AND b.id != ? AND i.ross_day BETWEEN ? AND ?", (bid, start, end))):
        conn.execute("UPDATE export_batches SET status='superato', superseded_reason=? WHERE id=?",
                     (f"Rigenerato nel lotto {bid}", old["id"]))
    for pd in _ross_open_deletions(conn):  # inclusa in questo file; «trasmessa» solo quando il lotto è caricato
        conn.execute("UPDATE ross_pending_deletions SET sent_batch=? WHERE id=?", (bid, pd["id"]))
    audit(conn, "export_generato", "export_batch", bid, f"ross {len(r['days'])} giorni")
    return row(conn.execute("SELECT * FROM export_batches WHERE id=?", (bid,))), data


# ======================= stati dei lotti =======================
def declare_upload(conn, batch_id: int, when: str | None = None) -> None:
    b = row(conn.execute("SELECT * FROM export_batches WHERE id=?", (batch_id,)))
    if not b or b["status"] != "generato":
        raise AppError("Si può dichiarare il caricamento solo di un lotto «Generato» non superato.")
    conn.execute("UPDATE export_batches SET status='caricamento_dichiarato', declared_at=? WHERE id=?",
                 (when or now_iso(), batch_id))
    if b["kind"] == "alloggiati":
        conn.execute("UPDATE guests SET alloggiati_status='caricamento_dichiarato' WHERE id IN "
                     "(SELECT guest_id FROM export_items WHERE batch_id=?)", (batch_id,))
    audit(conn, "caricamento_dichiarato", "export_batch", batch_id)


def register_outcome(conn, batch_id: int, data: dict) -> dict:
    """Esito dichiarato dall'operatrice in base a quanto mostrato dal portale.
    data: {all: 'accettato'|'scartato'|None, items: {guest_id|day: {'outcome':..., 'note':...}}, official_ref, note}"""
    b = row(conn.execute("SELECT * FROM export_batches WHERE id=?", (batch_id,)))
    if not b or b["status"] not in ("caricamento_dichiarato", "da_correggere", "esito_registrato"):
        raise AppError("Registrare prima il caricamento sul portale.")
    items = rows(conn.execute("SELECT * FROM export_items WHERE batch_id=?", (batch_id,)))
    per = data.get("items") or {}
    rejected = 0
    for it in items:
        key = str(it["guest_id"] if b["kind"] == "alloggiati" else it["ross_day"])
        o = (per.get(key) or {}).get("outcome") or data.get("all")
        if o not in ("accettato", "scartato"):
            raise AppError("Indicare l'esito per ogni elemento (o un esito unico per tutto il lotto).")
        note = ((per.get(key) or {}).get("note") or "").strip() or None
        conn.execute("UPDATE export_items SET outcome=?, outcome_note=? WHERE id=?", (o, note, it["id"]))
        if o == "scartato":
            rejected += 1
        if b["kind"] == "alloggiati":
            conn.execute("UPDATE guests SET alloggiati_status=?, alloggiati_note=? WHERE id=?",
                         ("esito_registrato" if o == "accettato" else "da_correggere", note, it["guest_id"]))
    status = "da_correggere" if rejected else "esito_registrato"
    conn.execute("UPDATE export_batches SET status=?, outcome_at=?, outcome_note=?, official_ref=? WHERE id=?",
                 (status, now_iso(), (data.get("note") or "").strip() or None,
                  (data.get("official_ref") or "").strip() or None, batch_id))
    audit(conn, "esito_registrato", "export_batch", batch_id, f"scartati={rejected}")
    return {"status": status, "rejected": rejected}


def receipt_acquired(conn, batch_id: int) -> int:
    """Ricevuta ufficiale Alloggiati acquisita: elimina i dati documentali conservati solo per l'invio."""
    from . import guests as GG
    b = row(conn.execute("SELECT * FROM export_batches WHERE id=?", (batch_id,)))
    if not b or b["kind"] != "alloggiati":
        raise AppError("Lotto non valido.")
    n = 0
    for it in rows(conn.execute("SELECT guest_id FROM export_items WHERE batch_id=? AND outcome='accettato'",
                                (batch_id,))):
        n += GG.purge_document(conn, it["guest_id"], f"ricevuta Alloggiati lotto {batch_id}")
    return n


def on_guest_deleted(conn, g: dict) -> None:
    """Ospite eliminato: lotti non usati diventano superati; se già nei dati ROSS dichiarati -> eliminazione."""
    for bt in rows(conn.execute("SELECT DISTINCT b.id FROM export_batches b JOIN export_items i ON i.batch_id=b.id "
                                "WHERE b.status='generato' AND i.guest_id=?", (g["id"],))):
        conn.execute("UPDATE export_batches SET status='superato', superseded_reason='Ospite eliminato' WHERE id=?",
                     (bt["id"],))
    if g.get("stay_arrival") and conn.execute(
            "SELECT 1 FROM export_batches WHERE kind='ross' AND status IN ('caricamento_dichiarato',"
            "'esito_registrato','da_correggere') AND period_from <= ? AND period_to >= ?",
            (g["stay_arrival"], g["stay_arrival"])).fetchone():
        cfg = _ross_cfg(conn)
        conn.execute("INSERT INTO ross_pending_deletions(idswh,tipo,arrivo,created_at) VALUES (?,?,?,?)",
                     (ross_id(cfg["prefix"], "G", g["id"]), g["guest_type"], g["stay_arrival"], now_iso()))


def _current_fps(g: dict, prof: dict) -> tuple[str, str | None] | None:
    """Impronte attuali (anagrafica+permanenza, documento). Documento None se già eliminato dopo la ricevuta."""
    if not (g["sex"] and g["birth_date"] and g["birth_state_code"] and g["citizenship_code"]):
        return None
    doc = G.doc_of(g) if g["guest_type"] in ("16", "17", "18") else {}
    complete = g["guest_type"] in ("19", "20") or all((doc or {}).get(k) for k in ("type", "number", "issue_place"))
    use = doc if complete and doc else {"type": "", "number": "", "issue_place": ""}
    line, head, _ = alloggiati_record(g, {"departure": g["departure"]}, use, prof)
    return _fp(head), (_fp(line[len(head):]) if complete else None)


def reassess(conn) -> dict:
    """Confronta i lotti con i dati attuali: lotti non usati -> superati; dati già comunicati -> rettifica."""
    if STATE.dek is None:
        return {"superseded": 0, "corrections": 0}
    sup, corr = 0, 0
    prof = _profile(conn)
    for it in rows(conn.execute(
            "SELECT i.*, b.status bstatus, b.id bid FROM export_items i JOIN export_batches b ON b.id=i.batch_id "
            "WHERE b.kind='alloggiati' AND b.status NOT IN ('superato')")):
        g = row(conn.execute("SELECT g.*, b.departure, b.arrival b_arrival FROM guests g JOIN bookings b "
                             "ON b.id=g.booking_id WHERE g.id=?", (it["guest_id"],)))
        changed, why = False, ""
        if not g or not g["stay_arrival"]:
            changed, why = True, "ospite eliminato o arrivo annullato"
        else:
            fp_head, fp_doc = it["fingerprint"].split(":")
            cur = _current_fps(g, prof)
            if cur is None:
                changed, why = True, "dati anagrafici incompleti dopo la generazione"
            elif cur[0] != fp_head:
                changed, why = True, "anagrafica o date di permanenza modificate dopo la generazione"
            elif cur[1] is not None and cur[1] != fp_doc:
                changed, why = True, "dati del documento modificati dopo la generazione"
        if not changed:
            continue
        if it["bstatus"] == "generato":
            conn.execute("UPDATE export_batches SET status='superato', superseded_reason=? WHERE id=?",
                         (why, it["bid"]))
            if g:
                conn.execute("UPDATE guests SET alloggiati_status='da_preparare' WHERE id=? AND "
                             "alloggiati_status='generato'", (g["id"],))
            sup += 1
        elif g:
            corr += open_correction(conn, "alloggiati", "guest", g["id"], g["booking_id"],
                                    f"{g['surname']} {g['name']}: dati già comunicati (lotto {it['bid']}) — {why}. "
                                    f"Gestire la rettifica secondo le procedure di Alloggiati Web.")
    if conn.execute("SELECT 1 FROM export_batches WHERE kind='ross' AND status != 'superato' LIMIT 1").fetchone():
        for b in rows(conn.execute("SELECT * FROM export_batches WHERE kind='ross' AND status != 'superato'")):
            try:
                r = ross_build(conn, b["period_from"], b["period_to"])
            except AppError:
                continue
            for it in rows(conn.execute("SELECT * FROM export_items WHERE batch_id=?", (b["id"],))):
                x = r["day_core"].get(it["ross_day"])
                if x is None or _fp(x) == it["fingerprint"]:
                    continue
                if b["status"] == "generato":
                    conn.execute("UPDATE export_batches SET status='superato', superseded_reason=? WHERE id=?",
                                 (f"Movimento del {it_date(it['ross_day'])} cambiato dopo la generazione", b["id"]))
                    sup += 1
                    break
                corr += open_correction(conn, "ross", "giorno", int(it["ross_day"].replace("-", "")), None,
                                        f"Movimento ROSS del {it_date(it['ross_day'])} già dichiarato (lotto {b['id']}) e "
                                        f"poi cambiato: ritrasmettere il movimento di quel giorno.")
    # Ospiti il cui unico file generato è stato superato (anche se i LORO dati non sono cambiati) tornano da preparare.
    conn.execute("UPDATE guests SET alloggiati_status='da_preparare' WHERE alloggiati_status='generato' AND NOT EXISTS "
                 "(SELECT 1 FROM export_items i JOIN export_batches b ON b.id=i.batch_id WHERE i.guest_id=guests.id "
                 "AND b.kind='alloggiati' AND b.status='generato')")
    return {"superseded": sup, "corrections": corr}


def open_correction(conn, target: str, entity: str, entity_id: int, booking_id: int | None, reason: str) -> int:
    if conn.execute("SELECT 1 FROM corrections WHERE target=? AND entity=? AND entity_id=? AND status='aperta'",
                    (target, entity, entity_id)).fetchone():
        return 0
    conn.execute("INSERT INTO corrections(target,entity,entity_id,booking_id,reason,created_at) VALUES (?,?,?,?,?,?)",
                 (target, entity, entity_id, booking_id, reason, now_iso()))
    audit(conn, "rettifica_aperta", entity, entity_id, target)
    return 1


def resolve_correction(conn, cid: int, resolution: str) -> None:
    if not (resolution or "").strip():
        raise AppError("Descrivere come è stata gestita la rettifica.")
    c = row(conn.execute("SELECT * FROM corrections WHERE id=? AND status='aperta'", (cid,)))
    conn.execute("UPDATE corrections SET status='gestita', resolution=?, resolved_at=? WHERE id=? AND status='aperta'",
                 (resolution.strip(), now_iso(), cid))
    if c:
        _rebaseline(conn, c)
    audit(conn, "rettifica_gestita", "correction", cid)


def _rebaseline(conn, c: dict) -> None:
    """Rettifica gestita: i dati attuali diventano quelli comunicati, altrimenti la rettifica si riaprirebbe subito.
    Un cambiamento successivo apre una nuova rettifica."""
    declared = "('caricamento_dichiarato','esito_registrato','da_correggere')"
    if c["target"] == "alloggiati" and c["entity"] == "guest":
        g = row(conn.execute("SELECT g.*, b.departure FROM guests g JOIN bookings b ON b.id=g.booking_id "
                             "WHERE g.id=?", (c["entity_id"],)))
        cur = _current_fps(g, _profile(conn)) if g and g["stay_arrival"] else None
        if not cur:
            return
        for it in rows(conn.execute(
                f"SELECT i.id, i.fingerprint FROM export_items i JOIN export_batches b ON b.id=i.batch_id "
                f"WHERE b.kind='alloggiati' AND b.status IN {declared} AND i.guest_id=?", (g["id"],))):
            old_doc = it["fingerprint"].split(":")[1]
            conn.execute("UPDATE export_items SET fingerprint=? WHERE id=?",
                         (f"{cur[0]}:{cur[1] if cur[1] is not None else old_doc}", it["id"]))
    elif c["target"] == "ross" and c["entity"] == "giorno":
        e = str(c["entity_id"])
        day = f"{e[:4]}-{e[4:6]}-{e[6:]}"
        x = ross_build(conn, day, day)["day_core"][day]
        conn.execute(f"UPDATE export_items SET fingerprint=? WHERE ross_day=? AND batch_id IN (SELECT id FROM "
                     f"export_batches WHERE kind='ross' AND status IN {declared})", (_fp(x), day))
