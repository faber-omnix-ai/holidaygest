"""Prenotazioni, blocchi, disponibilità e ciclo prenotazione -> arrivo -> partenza.

Occupazione dell'appartamento: intervallo [arrival, departure) della prenotazione
(pianificato, poi aggiornato da check-in/proroga/partenza anticipata).
Stati che occupano: opzione, confermata, in_corso, conclusa. I blocchi occupano sempre.
Tutte le scritture avvengono in transazioni IMMEDIATE: il controllo sovrapposizioni è
eseguito dentro la stessa transazione della scrittura (vale anche con due finestre aperte).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..config import TZ
from ..db import AppError, ConflictError, audit, get_setting, now_iso, row, rows
from ..util import add_days, d, eur, hhmm, it, minutes, nights, overlaps, parse_cents

OCCUPYING = ("opzione", "confermata", "in_corso", "conclusa")
STATUS_LABEL = {
    "bozza": "Bozza", "opzione": "In opzione", "opzione_scaduta": "Opzione scaduta", "confermata": "Prenotata",
    "in_corso": "Soggiorno in corso", "conclusa": "Conclusa", "annullata": "Annullata", "no_show": "No-show",
}


def _settings(conn) -> dict:
    st = get_setting(conn, "structure", {}) or {}
    return {"checkin": st.get("checkin_time", "15:00"), "checkout": st.get("checkout_time", "10:00"),
            "cleaning": int(st.get("cleaning_minutes", 0) or 0), "capacity": st.get("capacity")}


def new_ref(conn: sqlite3.Connection, arrival: str) -> str:
    y = arrival[:4]
    n = conn.execute("SELECT COUNT(*) FROM bookings WHERE ref LIKE ?", (f"P{y}-%",)).fetchone()[0] + 1
    while conn.execute("SELECT 1 FROM bookings WHERE ref=?", (f"P{y}-{n:04d}",)).fetchone():
        n += 1
    return f"P{y}-{n:04d}"


# ---------------- disponibilità ----------------
def check_availability(conn: sqlite3.Connection, start: str, end: str, checkin_time: str | None = None,
                       checkout_time: str | None = None, exclude_booking: int | None = None,
                       exclude_block: int | None = None) -> dict:
    """Sovrapposizioni e cambi nello stesso giorno per l'intervallo [start, end)."""
    s = _settings(conn)
    cin, cout = checkin_time or s["checkin"], checkout_time or s["checkout"]
    conflicts, turnovers = [], []
    for b in rows(conn.execute(
            f"SELECT id, ref, status, booker_name, arrival, departure, checkin_time, checkout_time FROM bookings "
            f"WHERE status IN ({','.join('?' * len(OCCUPYING))}) AND arrival <= ? AND departure >= ?",
            (*OCCUPYING, end, start))):
        if b["id"] == exclude_booking:
            continue
        if overlaps(start, end, b["arrival"], b["departure"]):
            conflicts.append({"type": "prenotazione", "id": b["id"], "ref": b["ref"], "status": b["status"],
                              "from": b["arrival"], "to": b["departure"],
                              "message": f"Sovrapposizione con {b['ref']} ({STATUS_LABEL[b['status']]}) "
                                         f"dal {it(b['arrival'])} al {it(b['departure'])}"})
        elif b["departure"] == start:  # loro partono, noi arriviamo
            turnovers.append(_turnover(b["checkout_time"] or s["checkout"], cin, s["cleaning"], b, "partenza_prima"))
        elif b["arrival"] == end:      # noi partiamo, loro arrivano
            turnovers.append(_turnover(cout, b["checkin_time"] or s["checkin"], s["cleaning"], b, "arrivo_dopo"))
    for bl in rows(conn.execute("SELECT * FROM blocks WHERE start < ? AND end_excl > ?", (end, start))):
        if bl["id"] != exclude_block:
            conflicts.append({"type": "blocco", "id": bl["id"], "from": bl["start"], "to": bl["end_excl"],
                              "message": f"Periodo bloccato ({bl['kind'].replace('_', ' ')}): {bl['reason']}"})
    return {"conflicts": conflicts, "turnovers": turnovers,
            "turnover_problem": any(not t["compatible"] for t in turnovers)}


def _turnover(out_time: str, in_time: str, cleaning: int, other: dict, kind: str) -> dict:
    gap = minutes(in_time) - minutes(out_time)
    ok = gap >= cleaning
    return {"other_ref": other["ref"], "other_id": other["id"], "kind": kind, "checkout": out_time,
            "checkin": in_time, "gap_minutes": gap, "cleaning_minutes": cleaning, "compatible": ok,
            "message": (f"Cambio ospiti nello stesso giorno con {other['ref']}: uscita {out_time}, entrata {in_time}, "
                        f"{gap} minuti disponibili (preparazione richiesta {cleaning}).")}


def _ensure_free(conn, start, end, cin, cout, exclude_booking=None, exclude_block=None, turnover_ack=False):
    av = check_availability(conn, start, end, cin, cout, exclude_booking, exclude_block)
    if av["conflicts"]:
        raise ConflictError("; ".join(c["message"] for c in av["conflicts"]), extra=av)
    if av["turnover_problem"] and not turnover_ack:
        raise ConflictError("Cambio ospiti nello stesso giorno con orari o tempo di preparazione incompatibili: "
                            "serve una decisione esplicita.", extra={**av, "needs_turnover_ack": True})
    return av


# ---------------- creazione e modifica ----------------
FIELDS = ("booker_name", "booker_phone", "booker_email", "source_text", "arrival", "departure", "checkin_time",
          "checkout_time", "guests_expected", "pricing_mode", "nightly_cents", "base_cents", "deposit_cents",
          "option_expires_at", "linked_booking_id", "tourism_type", "transport", "booking_channel", "notes")
FIELD_LABEL = {"booker_name": "referente", "booker_phone": "telefono", "booker_email": "e-mail",
               "source_text": "provenienza", "arrival": "arrivo", "departure": "partenza",
               "checkin_time": "ora di arrivo", "checkout_time": "ora di partenza", "guests_expected": "persone previste",
               "pricing_mode": "modalità prezzo", "nightly_cents": "prezzo per notte", "base_cents": "totale concordato",
               "deposit_cents": "cauzione", "option_expires_at": "scadenza opzione",
               "linked_booking_id": "prenotazione collegata", "tourism_type": "tipo di turismo",
               "transport": "mezzo di trasporto", "booking_channel": "canale di prenotazione", "notes": "note"}


def _clean(data: dict, current: dict | None = None) -> dict:
    out = dict(current or {})
    for k in FIELDS:
        if k in data:
            out[k] = data[k]
    if not (out.get("booker_name") or "").strip():
        raise AppError("Indicare il nome del referente della prenotazione.", field="booker_name")
    out["booker_name"] = out["booker_name"].strip()
    out["arrival"] = d(out.get("arrival"), "arrivo").isoformat()
    out["departure"] = d(out.get("departure"), "partenza").isoformat()
    if out["departure"] <= out["arrival"]:
        raise AppError("La partenza deve essere successiva all'arrivo (almeno una notte).", field="departure")
    out["checkin_time"] = hhmm(out.get("checkin_time") or None, "orario arrivo")
    out["checkout_time"] = hhmm(out.get("checkout_time") or None, "orario partenza")
    try:
        out["guests_expected"] = int(out.get("guests_expected") or 0)
    except (TypeError, ValueError):
        raise AppError("Numero ospiti non valido.", field="guests_expected")
    if out["guests_expected"] < 1:
        raise AppError("Indicare almeno un ospite previsto.", field="guests_expected")
    if out.get("pricing_mode", "totale") not in ("totale", "per_notte"):
        raise AppError("Modalità prezzo non valida.")
    out["pricing_mode"] = out.get("pricing_mode") or "totale"
    for k in ("nightly_cents", "base_cents", "deposit_cents"):
        out[k] = parse_cents(out.get(k, 0), k)
    if out.get("option_expires_at"):
        try:
            dt = datetime.fromisoformat(out["option_expires_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            out["option_expires_at"] = dt.isoformat(timespec="minutes")
        except ValueError:
            raise AppError("Scadenza opzione non valida.", field="option_expires_at")
    if out.get("booker_email") and "@" not in out["booker_email"]:
        raise AppError("Indirizzo e-mail non valido.", field="booker_email")
    return out


def capacity_warning(conn, guests: int) -> str | None:
    cap = _settings(conn)["capacity"]
    if cap and guests > int(cap):
        return f"Attenzione: {guests} persone superano la capienza confermata ({cap})."
    return None


def create(conn: sqlite3.Connection, data: dict) -> dict:
    status = data.get("status") or "bozza"
    if status not in ("bozza", "opzione", "confermata"):
        raise AppError("Una nuova prenotazione può essere bozza, opzione o confermata.")
    b = _clean(data)
    if status == "opzione" and not b.get("option_expires_at"):
        raise AppError("Per un'opzione indicare la scadenza.", field="option_expires_at")
    if status in OCCUPYING:
        _ensure_free(conn, b["arrival"], b["departure"], b["checkin_time"], b["checkout_time"],
                     turnover_ack=bool(data.get("turnover_ack")))
    ts = now_iso()
    ref = new_ref(conn, b["arrival"])
    cur = conn.execute(
        f"INSERT INTO bookings(ref,status,{','.join(FIELDS)},turnover_ack,created_at,updated_at) "
        f"VALUES (?,?,{','.join('?' * len(FIELDS))},?,?,?)",
        (ref, status, *[b.get(k) for k in FIELDS], int(bool(data.get("turnover_ack"))), ts, ts))
    audit(conn, "prenotazione_creata", "booking", cur.lastrowid, status)
    return get(conn, cur.lastrowid)


def get(conn: sqlite3.Connection, booking_id: int) -> dict:
    b = row(conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)))
    if not b:
        raise AppError("Prenotazione inesistente.", 404)
    return b


def _check_version(b: dict, version) -> None:
    if version is None or int(version) != b["version"]:
        raise ConflictError("La prenotazione è stata modificata nel frattempo (forse in un'altra finestra). "
                            "Ricarica la scheda e ripeti l'operazione.")


def _bump(conn, booking_id: int, sets: dict) -> None:
    sets = {**sets, "updated_at": now_iso()}
    cols = ", ".join(f"{k}=?" for k in sets)
    conn.execute(f"UPDATE bookings SET {cols}, version=version+1 WHERE id=?", (*sets.values(), booking_id))


def preview_update(conn: sqlite3.Connection, booking_id: int, data: dict) -> dict:
    """Conseguenze di una modifica, SENZA salvarla."""
    from . import money, tax, consistency
    old = get(conn, booking_id)
    new = _clean(data, old)
    out: dict = {"changes": {k: {"da": old.get(k), "a": new.get(k), "label": FIELD_LABEL.get(k, k)} for k in FIELDS
                             if (old.get(k) if old.get(k) != "" else None) != (new.get(k) if new.get(k) != "" else None)}}
    av = None
    moved = (new["arrival"], new["departure"], new["checkin_time"], new["checkout_time"]) != \
        (old["arrival"], old["departure"], old["checkin_time"], old["checkout_time"])
    if old["status"] in OCCUPYING and moved:
        av = check_availability(conn, new["arrival"], new["departure"], new["checkin_time"],
                                new["checkout_time"], exclude_booking=booking_id)
    out["availability"] = av
    out["nights"] = {"da": len(nights(old["arrival"], old["departure"])),
                     "a": len(nights(new["arrival"], new["departure"]))}
    # Simulazione in un savepoint annullato: nulla viene salvato.
    conn.execute("SAVEPOINT anteprima")
    try:
        bal_old = money.balances(conn, booking_id)
        sets = {k: new.get(k) for k in FIELDS}
        conn.execute(f"UPDATE bookings SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                     (*sets.values(), booking_id))
        bal_new = money.balances(conn, booking_id)
        effects = consistency.effects_of_booking(conn, booking_id)
    finally:
        conn.execute("ROLLBACK TO anteprima")
        conn.execute("RELEASE anteprima")
    out["price"] = {"da": bal_old["price"]["total_cents"], "a": bal_new["price"]["total_cents"]}
    out["stay_balance"] = {"da": bal_old["stay"]["balance_cents"], "a": bal_new["stay"]["balance_cents"]}
    out["tax"] = {"da": bal_old["tax"]["due_cents"], "a": bal_new["tax"]["due_cents"],
                  "source": bal_new["tax"]["due_source"]}
    out["payments_received"] = bal_old["stay"]["net_cents"]
    out["effects"] = effects
    out["capacity_warning"] = capacity_warning(conn, new["guests_expected"])
    out["summary"] = _summary_lines(out)
    return out


def _summary_lines(p: dict) -> list[str]:
    s = []
    if p["availability"] and p["availability"]["conflicts"]:
        s += [c["message"] for c in p["availability"]["conflicts"]]
    if p["availability"] and p["availability"]["turnovers"]:
        s += [t["message"] for t in p["availability"]["turnovers"]]
    if p["nights"]["da"] != p["nights"]["a"]:
        s.append(f"Notti: {p['nights']['da']} → {p['nights']['a']}")
    if p["price"]["da"] != p["price"]["a"]:
        s.append(f"Prezzo soggiorno: {eur(p['price']['da'])} → {eur(p['price']['a'])}")
    if p["tax"]["da"] != p["tax"]["a"]:
        s.append(f"Imposta: {eur(p['tax']['da'])} → {eur(p['tax']['a'])} ({p['tax']['source']})")
    if p["stay_balance"]["da"] != p["stay_balance"]["a"]:
        s.append(f"Pagamenti soggiorno già registrati {eur(p['payments_received'])}; residuo "
                 f"{eur(p['stay_balance']['da'])} → {eur(p['stay_balance']['a'])}")
    s += p["effects"]
    if p.get("capacity_warning"):
        s.append(p["capacity_warning"])
    return s or ["Nessuna conseguenza oltre ai dati modificati."]


def update(conn: sqlite3.Connection, booking_id: int, data: dict) -> dict:
    old = get(conn, booking_id)
    _check_version(old, data.get("version"))
    new = _clean(data, old)
    changed = [k for k in FIELDS if old.get(k) != new.get(k)]
    if old["status"] in ("annullata", "no_show", "conclusa"):
        allowed = {"notes", "booker_phone", "booker_email", "tourism_type", "transport", "booking_channel",
                   "base_cents", "pricing_mode", "nightly_cents"}
        if set(changed) - allowed:
            raise AppError("Prenotazione chiusa: si possono modificare solo note, contatti e corrispettivo.")
    if old["status"] in OCCUPYING:
        same_dates = (new["arrival"], new["departure"]) == (old["arrival"], old["departure"])
        ack = bool(data.get("turnover_ack")) or (bool(old["turnover_ack"]) and same_dates)
        _ensure_free(conn, new["arrival"], new["departure"], new["checkin_time"], new["checkout_time"],
                     exclude_booking=booking_id, turnover_ack=ack)
    sets = {k: new.get(k) for k in FIELDS}
    if data.get("turnover_ack"):
        sets["turnover_ack"] = 1
    _bump(conn, booking_id, sets)
    audit(conn, "prenotazione_modificata", "booking", booking_id,
          ",".join(changed) + (f" date {old['arrival']}/{old['departure']}→{new['arrival']}/{new['departure']}"
                               if "arrival" in changed or "departure" in changed else ""))
    return get(conn, booking_id)


def set_price_items(conn, booking_id: int, items: list[dict]) -> None:
    conn.execute("DELETE FROM price_items WHERE booking_id=?", (booking_id,))
    for item in items or []:
        if item.get("kind") not in ("extra", "sconto") or not (item.get("description") or "").strip():
            raise AppError("Extra/sconto: indicare tipo e descrizione.")
        conn.execute("INSERT INTO price_items(booking_id,kind,description,amount_cents) VALUES (?,?,?,?)",
                     (booking_id, item["kind"], item["description"].strip(), parse_cents(item.get("amount_cents",
                                                                                            item.get("amount")))))
    _bump(conn, booking_id, {})


# ---------------- transizioni di stato ----------------
def change_status(conn: sqlite3.Connection, booking_id: int, action: str, data: dict) -> dict:
    b = get(conn, booking_id)
    _check_version(b, data.get("version"))
    st = b["status"]
    today = now_iso()[:10]
    if action == "opzione":
        if st not in ("bozza", "opzione_scaduta"):
            raise AppError("Solo una bozza o un'opzione scaduta può diventare opzione.")
        exp = _clean({"option_expires_at": data.get("option_expires_at")}, b).get("option_expires_at")
        if not exp or exp <= now_iso():
            raise AppError("Indicare una scadenza futura per l'opzione.", field="option_expires_at")
        _ensure_free(conn, b["arrival"], b["departure"], b["checkin_time"], b["checkout_time"], booking_id,
                     turnover_ack=bool(data.get("turnover_ack") or b["turnover_ack"]))
        _bump(conn, booking_id, {"status": "opzione", "option_expires_at": exp})
    elif action == "conferma":
        if st not in ("bozza", "opzione", "opzione_scaduta"):
            raise AppError("Questa prenotazione non può essere confermata nello stato attuale.")
        _ensure_free(conn, b["arrival"], b["departure"], b["checkin_time"], b["checkout_time"], booking_id,
                     turnover_ack=bool(data.get("turnover_ack") or b["turnover_ack"]))
        _bump(conn, booking_id, {"status": "confermata", "option_expires_at": None,
                                 "turnover_ack": int(bool(data.get("turnover_ack") or b["turnover_ack"]))})
    elif action == "annulla":
        if st not in ("bozza", "opzione", "opzione_scaduta", "confermata"):
            raise AppError("Una prenotazione con soggiorno in corso o concluso non può essere annullata: "
                           "registrare la partenza anticipata.")
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise AppError("Indicare il motivo dell'annullamento.", field="reason")
        sets = {"status": "annullata", "cancelled_at": now_iso(), "cancel_reason": reason}
        if "retained_cents" in data:  # corrispettivo trattenuto dichiarato dall'operatrice
            sets.update({"pricing_mode": "totale", "base_cents": parse_cents(data["retained_cents"])})
            conn.execute("DELETE FROM price_items WHERE booking_id=?", (booking_id,))
        _bump(conn, booking_id, sets)  # incassi e quietanze restano invariati
    elif action == "no_show":
        if st != "confermata":
            raise AppError("Il no-show si registra solo su una prenotazione confermata.")
        if today < b["arrival"]:
            raise AppError("Il no-show può essere registrato solo dal giorno di arrivo previsto.")
        if conn.execute("SELECT 1 FROM guests WHERE booking_id=? AND presence IN ('presente','partita')",
                        (booking_id,)).fetchone():
            raise AppError("Risultano ospiti arrivati: non è un no-show.")
        if not data.get("confirm"):
            raise AppError("Confermare esplicitamente il no-show.")
        _bump(conn, booking_id, {"status": "no_show", "no_show_at": now_iso()})
    else:
        raise AppError("Operazione non riconosciuta.")
    audit(conn, f"prenotazione_{action}", "booking", booking_id, st)
    return get(conn, booking_id)


def expire_options(conn: sqlite3.Connection) -> int:
    """Opzioni scadute -> 'opzione_scaduta' (ricalcolato all'avvio e a ogni lettura del calendario).
    Le prenotazioni confermate NON vengono mai liberate automaticamente."""
    now = now_iso()
    exp = rows(conn.execute("SELECT id FROM bookings WHERE status='opzione' AND option_expires_at IS NOT NULL "
                            "AND option_expires_at <= ?", (now,)))
    for r in exp:
        conn.execute("UPDATE bookings SET status='opzione_scaduta', version=version+1, updated_at=? WHERE id=?",
                     (now, r["id"]))
        audit(conn, "opzione_scaduta", "booking", r["id"])
    return len(exp)


# ---------------- arrivo e partenza ----------------
def check_in(conn: sqlite3.Connection, booking_id: int, data: dict) -> dict:
    """Registra chi è realmente arrivato e quando. Gli altri restano 'previsti'."""
    b = get(conn, booking_id)
    _check_version(b, data.get("version"))
    if b["status"] not in ("confermata", "in_corso"):
        raise AppError("Il check-in si registra su una prenotazione confermata o in corso.")
    arrivals = data.get("arrivals") or []
    if not arrivals:
        raise AppError("Selezionare almeno un ospite arrivato.")
    first = None
    for a in arrivals:
        g = row(conn.execute("SELECT * FROM guests WHERE id=? AND booking_id=?", (a.get("guest_id"), booking_id)))
        if not g:
            raise AppError("Ospite non appartenente alla prenotazione.")
        if g["presence"] in ("presente", "partita"):
            raise AppError(f"{g['surname']} {g['name']}: arrivo già registrato.")
        day = d(a.get("date"), "data arrivo").isoformat()
        if day > now_iso()[:10]:
            raise AppError("Non è possibile registrare un arrivo futuro.")
        t = hhmm(a.get("time") or None, "ora arrivo")
        dep = g["planned_departure"] or b["departure"]
        if dep <= day:
            raise AppError(f"{g['surname']} {g['name']}: la partenza prevista precede l'arrivo.")
        conn.execute("UPDATE guests SET presence='presente', stay_arrival=?, stay_arrival_time=?, "
                     "version=version+1, updated_at=? WHERE id=?", (day, t, now_iso(), g["id"]))
        first = min(first or day, day)
    sets = {"status": "in_corso"}
    if first and first < b["arrival"]:
        _ensure_free(conn, first, b["departure"], None, None, exclude_booking=booking_id,
                     turnover_ack=bool(data.get("turnover_ack")))
        sets["arrival"] = first
    _bump(conn, booking_id, sets)
    audit(conn, "check_in", "booking", booking_id, f"{len(arrivals)} ospiti")
    return get(conn, booking_id)


def _not_future(day: str, what: str) -> None:
    """Arrivi e partenze EFFETTIVI non possono essere nel futuro (sono fatti già avvenuti)."""
    if day > now_iso()[:10]:
        raise AppError(f"Non è possibile registrare una {what} effettiva futura ({it(day)}): registrarla quando "
                       f"avviene. Per cambiare le date previste modificare la prenotazione o la scheda ospite.")


def mark_not_arrived(conn, booking_id: int, guest_id: int) -> None:
    g = row(conn.execute("SELECT * FROM guests WHERE id=? AND booking_id=?", (guest_id, booking_id)))
    if not g or g["presence"] != "prevista":
        raise AppError("Solo un ospite previsto può essere segnato come non arrivato.")
    conn.execute("UPDATE guests SET presence='non_arrivata', version=version+1, updated_at=? WHERE id=?",
                 (now_iso(), guest_id))
    audit(conn, "ospite_non_arrivato", "guest", guest_id)


def guest_departure(conn, booking_id: int, guest_id: int, day: str) -> None:
    g = row(conn.execute("SELECT * FROM guests WHERE id=? AND booking_id=?", (guest_id, booking_id)))
    if not g or g["presence"] != "presente":
        raise AppError("Solo un ospite presente può partire.")
    day = d(day, "data partenza").isoformat()
    if day <= g["stay_arrival"]:
        raise AppError("La partenza deve essere successiva all'arrivo.")
    _not_future(day, "partenza")
    b = get(conn, booking_id)
    if day > b["departure"]:
        raise AppError(f"La partenza indicata ({it(day)}) è dopo la fine della prenotazione ({it(b['departure'])}): "
                       f"per un soggiorno prolungato registrare la partenza dell'intera prenotazione (proroga).")
    conn.execute("UPDATE guests SET presence='partita', stay_departure=?, version=version+1, updated_at=? "
                 "WHERE id=?", (day, now_iso(), guest_id))
    audit(conn, "ospite_partito", "guest", guest_id)


def checkout_summary(conn, booking_id: int) -> dict:
    from . import money, consistency
    b = get(conn, booking_id)
    gs = rows(conn.execute("SELECT id, surname, name, presence, stay_arrival, stay_departure, planned_departure, "
                           "alloggiati_status, verified_at FROM guests WHERE booking_id=? AND anonymized_at IS NULL",
                           (booking_id,)))
    bal = money.balances(conn, booking_id)
    return {"booking": b, "guests": gs, "balances": bal, "open_items": consistency.open_items_for_booking(conn, b)}


def check_out(conn: sqlite3.Connection, booking_id: int, data: dict) -> dict:
    """Partenza: registra le partenze individuali, aggiorna l'occupazione, il debito resta visibile."""
    b = get(conn, booking_id)
    _check_version(b, data.get("version"))
    if b["status"] != "in_corso":
        raise AppError("Il check-out si registra su un soggiorno in corso.")
    day = d(data.get("date") or now_iso()[:10], "data partenza").isoformat()
    _not_future(day, "partenza")
    if day > b["departure"] and not data.get("extend_ack"):
        extra = len(nights(b["departure"], day))
        raise AppError(f"La partenza indicata ({it(day)}) è {extra} notti dopo la fine della prenotazione "
                       f"({it(b['departure'])}): confermare esplicitamente la proroga. Il prezzo concordato non viene "
                       f"aggiornato automaticamente.", 409, extra={"needs_extend_ack": True, "extra_nights": extra})
    for g in rows(conn.execute("SELECT * FROM guests WHERE booking_id=? AND presence='presente'", (booking_id,))):
        dep = day if day > g["stay_arrival"] else None
        if not dep:
            raise AppError(f"{g['surname']} {g['name']}: la data di partenza precede l'arrivo.")
        conn.execute("UPDATE guests SET presence='partita', stay_departure=?, version=version+1, updated_at=? "
                     "WHERE id=?", (dep, now_iso(), g["id"]))
    last = conn.execute("SELECT MAX(stay_departure) FROM guests WHERE booking_id=? AND presence='partita'",
                        (booking_id,)).fetchone()[0] or day
    sets = {"status": "conclusa", "checked_out_at": now_iso(), "departure": last}
    if last > b["departure"]:
        _ensure_free(conn, b["arrival"], last, None, None, exclude_booking=booking_id)
    _bump(conn, booking_id, sets)
    nxt = conn.execute("SELECT id FROM bookings WHERE status IN ('confermata','opzione') AND arrival >= ? "
                       "ORDER BY arrival LIMIT 1", (last,)).fetchone()
    if nxt:  # dopo una partenza l'appartamento va preparato per l'arrivo successivo
        conn.execute("UPDATE bookings SET prep_status='da_preparare' WHERE id=?", (nxt[0],))
    audit(conn, "check_out", "booking", booking_id, f"partenza {last}")
    return get(conn, booking_id)


def set_prep_status(conn, booking_id: int, status: str) -> None:
    if status not in ("da_preparare", "in_preparazione", "pronto"):
        raise AppError("Stato preparazione non valido.")
    conn.execute("UPDATE bookings SET prep_status=?, updated_at=? WHERE id=?", (status, now_iso(), booking_id))
    audit(conn, "preparazione", "booking", booking_id, status)


# ---------------- blocchi e chiusure ----------------
def create_block(conn, data: dict) -> int:
    start = d(data.get("start"), "primo giorno").isoformat()
    last = d(data.get("last"), "ultimo giorno").isoformat()
    if last < start:
        raise AppError("L'ultimo giorno precede il primo.")
    if data.get("kind") not in ("manutenzione", "uso_personale", "altro"):
        raise AppError("Tipo di blocco non valido.")
    if not (data.get("reason") or "").strip():
        raise AppError("Indicare il motivo del blocco.", field="reason")
    end = add_days(last, 1)
    _ensure_free(conn, start, end, "00:00", "23:59", exclude_block=-1, turnover_ack=True)
    cur = conn.execute("INSERT INTO blocks(start,end_excl,kind,reason,created_at) VALUES (?,?,?,?,?)",
                       (start, end, data["kind"], data["reason"].strip(), now_iso()))
    audit(conn, "blocco_creato", "block", cur.lastrowid)
    return cur.lastrowid


def delete_block(conn, block_id: int) -> None:
    conn.execute("DELETE FROM blocks WHERE id=?", (block_id,))
    audit(conn, "blocco_rimosso", "block", block_id)


def create_closure(conn, data: dict) -> int:
    start = d(data.get("start"), "primo giorno").isoformat()
    last = d(data.get("last"), "ultimo giorno").isoformat()
    if last < start:
        raise AppError("L'ultimo giorno precede il primo.")
    cur = conn.execute("INSERT INTO closures(start,end_excl,note,created_at) VALUES (?,?,?,?)",
                       (start, add_days(last, 1), (data.get("note") or "").strip() or None, now_iso()))
    audit(conn, "chiusura_ross_creata", "closure", cur.lastrowid)
    return cur.lastrowid


# ---------------- calendario e occupazione ----------------
def calendar(conn: sqlite3.Connection, start: str, end: str) -> dict:
    from . import money
    today = now_iso()[:10]
    days = {n.isoformat(): {"date": n.isoformat(), "state": "disponibile", "label": "Disponibile", "items": []}
            for n in nights(start, end)}
    bks = rows(conn.execute(
        "SELECT id, ref, status, booker_name, arrival, departure, guests_expected, prep_status, "
        "checkin_time, checkout_time, option_expires_at FROM bookings WHERE arrival < ? AND departure > ? "
        "AND status NOT IN ('annullata','no_show','opzione_scaduta','bozza') ORDER BY arrival", (end, start)))
    drafts = rows(conn.execute(
        "SELECT id, ref, status, booker_name, arrival, departure FROM bookings WHERE status='bozza' "
        "AND arrival < ? AND departure > ?", (end, start)))
    out_b = []
    for b in bks:
        bal = money.balances(conn, b["id"])
        pay = ("saldato" if bal["stay"]["balance_cents"] <= 0 else
               "parziale" if bal["stay"]["net_cents"] > 0 else "da incassare")
        present = conn.execute("SELECT COUNT(*) FROM guests WHERE booking_id=? AND presence='presente'",
                               (b["id"],)).fetchone()[0]
        state = {"opzione": "opzione", "confermata": "prenotato", "in_corso": "in_corso",
                 "conclusa": "concluso"}[b["status"]]
        card = {"id": b["id"], "ref": b["ref"], "referente": b["booker_name"], "from": b["arrival"],
                "to": b["departure"], "ospiti": b["guests_expected"], "presenti": present,
                "stato": STATUS_LABEL[b["status"]], "status": b["status"], "pagamenti": pay,
                "saldo_cents": bal["stay"]["balance_cents"], "prep_status": b["prep_status"],
                "option_expires_at": b["option_expires_at"]}
        out_b.append(card)
        for n in nights(max(b["arrival"], start), min(b["departure"], end)):
            day = days[n.isoformat()]
            day["state"], day["label"] = state, card["stato"]
            day["items"].append({"type": "booking", "id": b["id"]})
    blks = rows(conn.execute("SELECT * FROM blocks WHERE start < ? AND end_excl > ?", (end, start)))
    for bl in blks:
        for n in nights(max(bl["start"], start), min(bl["end_excl"], end)):
            day = days[n.isoformat()]
            day["state"] = "bloccato"
            day["label"] = "Bloccato: " + ("manutenzione" if bl["kind"] == "manutenzione" else
                                           "uso personale" if bl["kind"] == "uso_personale" else "altro")
            day["items"].append({"type": "block", "id": bl["id"]})
    turnovers = turnover_list(conn, start, end)
    return {"from": start, "to": end, "today": today, "days": list(days.values()), "bookings": out_b,
            "blocks": blks, "drafts": drafts, "turnovers": turnovers}


def turnover_list(conn, start: str, end: str) -> list[dict]:
    """Cambi ospiti: partenza, arrivo successivo, tempo disponibile, stato preparazione."""
    s = _settings(conn)
    bks = rows(conn.execute(
        f"SELECT id, ref, arrival, departure, checkin_time, checkout_time, prep_status, status FROM bookings "
        f"WHERE status IN ({','.join('?' * len(OCCUPYING))}) AND departure >= ? AND arrival <= ? ORDER BY arrival",
        (*OCCUPYING, start, end)))
    out = []
    for prev, nxt in zip(bks, bks[1:]):
        if not (start <= prev["departure"] <= end):
            continue
        out_dt = datetime.fromisoformat(f"{prev['departure']}T{prev['checkout_time'] or s['checkout']}")
        in_dt = datetime.fromisoformat(f"{nxt['arrival']}T{nxt['checkin_time'] or s['checkin']}")
        gap = int((in_dt - out_dt).total_seconds() // 60)
        out.append({"departure_ref": prev["ref"], "departure_id": prev["id"], "departure": prev["departure"],
                    "checkout": prev["checkout_time"] or s["checkout"], "arrival_ref": nxt["ref"],
                    "arrival_id": nxt["id"], "arrival": nxt["arrival"], "checkin": nxt["checkin_time"] or s["checkin"],
                    "gap_minutes": gap, "same_day": prev["departure"] == nxt["arrival"],
                    "compatible": gap >= s["cleaning"], "cleaning_minutes": s["cleaning"],
                    "prep_status": nxt["prep_status"]})
    return out


def occupancy(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Notti nel periodo, separando previsione e consuntivo. Denominatore sempre esplicito."""
    today = now_iso()[:10]
    period = [n.isoformat() for n in nights(start, end)]
    blocked = set()
    for bl in rows(conn.execute("SELECT * FROM blocks WHERE start < ? AND end_excl > ?", (end, start))):
        blocked |= {n.isoformat() for n in nights(max(bl["start"], start), min(bl["end_excl"], end))}
    booked = set()
    for b in rows(conn.execute(
            "SELECT arrival, departure FROM bookings WHERE status IN ('confermata','in_corso','conclusa') "
            "AND arrival < ? AND departure > ?", (end, start))):
        booked |= {n.isoformat() for n in nights(max(b["arrival"], start), min(b["departure"], end))}
    occupied = set()
    for g in rows(conn.execute(
            "SELECT stay_arrival, COALESCE(stay_departure, ?) dep FROM guests WHERE stay_arrival IS NOT NULL "
            "AND stay_arrival < ? AND COALESCE(stay_departure, ?) > ?", (today, end, today, start))):
        occupied |= {n.isoformat() for n in nights(max(g["stay_arrival"], start), min(g["dep"], end, today))}
    sellable = [n for n in period if n not in blocked]
    past_sellable = [n for n in sellable if n < today]
    return {
        "period_nights": len(period), "blocked_nights": len(blocked), "sellable_nights": len(sellable),
        "booked_nights": len(booked), "occupied_nights": len(occupied),
        "forecast_rate": round(100 * len(booked) / len(sellable), 1) if sellable else None,
        "forecast_denominator": f"{len(sellable)} notti vendibili (periodo {len(period)} − bloccate {len(blocked)})",
        "actual_rate": round(100 * len(occupied) / len(past_sellable), 1) if past_sellable else None,
        "actual_denominator": f"{len(past_sellable)} notti vendibili già trascorse",
    }
