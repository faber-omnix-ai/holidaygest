"""Endpoint JSON dell'interfaccia. Ogni scrittura avviene in una transazione unica (vedi server._call)."""
from __future__ import annotations

import base64
import json
from datetime import date, timedelta

from . import config
from .db import AppError, audit, get_setting, now_iso, row, rows, set_setting
from .server import FileResponse, route, session_cookie
from .services import (accounts, attachments, backup, bookings, consistency, exports, guests, maintenance, money,
                       ocr, periods, reports, retention, tables, tax)
from .state import STATE
from .util import add_days, d, eur, nights, parse_cents

TODAY = lambda: now_iso()[:10]  # noqa: E731


def _id(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        raise AppError("Identificativo non valido.")


def _session_payload(req_cookie_token: str, csrf: str, extra: dict | None = None):
    return {"ok": True, "csrf": csrf, **(extra or {})}, {"_cookie": session_cookie(req_cookie_token)}


# ======================= stato, accesso =======================
@route("GET", r"/api/status", auth=False)
def status(req, conn):
    s = req.session
    done = accounts.is_setup(conn)
    st = get_setting(conn, "structure", {}) or {}
    return {"app": config.APP_NAME, "version": config.VERSION, "setup_done": done,
            "logged_in": bool(s and STATE.dek), "csrf": s["csrf"] if s and STATE.dek else None,
            "structure_name": st.get("name"), "data_dir": str(config.data_dir()),
            "portable": config.portable_mode(), "today": TODAY(), "simulation": config.SIMULAZIONE}


@route("POST", r"/api/setup", auth=False, reassess=False)
def setup(req, conn):
    j = req.json
    code = accounts.setup(conn, j.get("username"), j.get("password"))
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    token, csrf = STATE.sessions.create(uid)
    return _session_payload(token, csrf, {"recovery_code": code})


@route("POST", r"/api/login", auth=False, reassess=False)
def login(req, conn):
    import time
    time.sleep(STATE.sessions.throttle_seconds())
    j = req.json
    uid = accounts.login(conn, j.get("username"), j.get("password"))
    token, csrf = STATE.sessions.create(uid)
    bookings.expire_options(conn)
    retention.purge_expired_attachments(conn)
    return _session_payload(token, csrf)


@route("POST", r"/api/recover", auth=False, reassess=False)
def recover(req, conn):
    import time
    time.sleep(STATE.sessions.throttle_seconds())
    j = req.json
    code2 = accounts.recover(conn, j.get("code"), j.get("new_password"))
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    token, csrf = STATE.sessions.create(uid)
    return _session_payload(token, csrf, {"recovery_code": code2})


@route("POST", r"/api/logout", reassess=False)
def logout(req, conn):
    STATE.sessions.drop(None)
    STATE.lock_app()
    return {"ok": True}, {"_cookie": session_cookie(None)}


@route("POST", r"/api/password", reassess=False)
def change_password(req, conn):
    accounts.change_password(conn, req.json.get("old"), req.json.get("new"))
    return {"ok": True}


@route("POST", r"/api/recovery-code", reassess=False)
def new_recovery(req, conn):
    return {"recovery_code": accounts.new_recovery(conn, req.json.get("password"))}


@route("POST", r"/api/shutdown", reassess=False)
def shutdown(req, conn):
    if STATE.shutdown_cb:
        STATE.shutdown_cb()
    return {"ok": True}


# ======================= impostazioni =======================
@route("GET", r"/api/settings")
def get_settings(req, conn):
    return {"structure": get_setting(conn, "structure", {}), "retention": retention.policy(conn),
            "backup": get_setting(conn, "backup", {}) or {}, "data_dir": str(config.data_dir()),
            "program_dir": str(config.program_dir()), "portable": config.portable_mode(),
            "tables": tables.load()["meta"], "lists": {"tourism": exports.TOURISM, "transport": exports.TRANSPORT,
                                                       "channel": exports.CHANNEL}}


@route("PUT", r"/api/settings")
def put_settings(req, conn):
    j = req.json
    st = get_setting(conn, "structure", {}) or {}
    s = j.get("structure") or {}
    allowed = ("name", "address", "cin", "iun", "activity_type", "tax_category", "category_confirmed",
               "owner_name", "owner_tax_code", "owner_vat", "capacity", "checkin_time", "checkout_time",
               "cleaning_minutes", "alloggiati", "ross", "ross_sends_alloggiati", "proposed_unverified", "tax_comune")
    from .util import hhmm
    prev_ross_since = (st.get("ross") or {}).get("configured_on")
    for k in allowed:
        if k in s:
            st[k] = s[k]
    hhmm(st.get("checkin_time")), hhmm(st.get("checkout_time"))
    if st.get("capacity") not in (None, ""):
        st["capacity"] = int(st["capacity"])
    st["cleaning_minutes"] = int(st.get("cleaning_minutes") or 0)
    if st.get("category_confirmed") and st.get("tax_category") not in ("extra_alberghiera",):
        raise AppError("Categoria fiscale non gestita da questa versione: solo strutture extra-alberghiere.")
    a = st.get("alloggiati") or {}
    if a.get("format") not in (None, "", "168", "174"):
        raise AppError("Formato Alloggiati non valido.")
    if isinstance(st.get("ross"), dict):
        # data da cui ricordare le giornate ROSS 1000 non dichiarate: mai retroattiva
        st["ross"]["configured_on"] = prev_ross_since or (TODAY() if st["ross"].get("code") else None)
    set_setting(conn, "structure", st)
    if "retention" in j:
        set_setting(conn, "retention", {"anagrafica_years": int(j["retention"].get("anagrafica_years", 5)),
                                        "confirmed": bool(j["retention"].get("confirmed"))})
    audit(conn, "impostazioni_modificate")
    return {"ok": True}


# ======================= oggi =======================
@route("GET", r"/api/today")
def today(req, conn):
    t = TODAY()
    tomorrow, week = add_days(t, 1), add_days(t, 7)
    bookings.expire_options(conn)
    arr = rows(conn.execute("SELECT * FROM bookings WHERE status IN ('confermata','opzione','in_corso') "
                            "AND arrival BETWEEN ? AND ? ORDER BY arrival", (t, week)))
    dep = rows(conn.execute("SELECT * FROM bookings WHERE status='in_corso' AND departure BETWEEN ? AND ? "
                            "ORDER BY departure", (add_days(t, -30), week)))
    present = rows(conn.execute("SELECT * FROM bookings WHERE status='in_corso' ORDER BY arrival"))
    open_items = []
    active = rows(conn.execute("SELECT * FROM bookings WHERE status IN ('confermata','in_corso','conclusa',"
                               "'annullata','no_show') AND (departure >= ? OR status='in_corso')",
                               (add_days(t, -120),)))
    to_collect = 0
    tax_to_collect = 0
    for b in active:
        items = consistency.open_items_for_booking(conn, b)
        if b["status"] == "confermata" and b["arrival"] > add_days(t, 3):
            items = [i for i in items if i["kind"] in ("rettifica",)]  # futuro lontano: niente allarmi
        open_items += items
        if b["status"] in ("confermata", "in_corso", "conclusa"):
            bal = money.balances(conn, b["id"])
            to_collect += max(0, bal["stay"]["balance_cents"])
            tax_to_collect += max(0, bal["tax"]["residual_cents"] or 0)
    # Alloggiati: scadenza indicativa dall'ora di arrivo registrata
    deadlines = []
    for g in rows(conn.execute(
            "SELECT g.id, g.surname, g.name, g.stay_arrival, g.stay_arrival_time, g.stay_departure, g.booking_id, "
            "b.ref, b.departure FROM guests g JOIN bookings b ON b.id=g.booking_id WHERE g.presence IN "
            "('presente','partita') AND g.alloggiati_status NOT IN ('caricamento_dichiarato','esito_registrato') "
            "AND g.stay_arrival >= ?", (add_days(t, -30),))):
        from datetime import datetime
        arr_dt = datetime.fromisoformat(f"{g['stay_arrival']}T{g['stay_arrival_time'] or '12:00'}").replace(
            tzinfo=config.TZ)
        g_dep = g["stay_departure"] or g["departure"]
        short = (date.fromisoformat(g_dep) - date.fromisoformat(g["stay_arrival"])).days <= 1
        hours = 6 if short else 24
        due = arr_dt + timedelta(hours=hours)
        deadlines.append({"text": f"Alloggiati: {g['ref']} · {g['surname']} {g['name']}", "due": due.isoformat(
            timespec="minutes"), "basis": f"{hours} ore dall'arrivo"
            + ("" if g["stay_arrival_time"] else " (ora di arrivo non registrata: calcolata dalle 12:00)"),
            "overdue": due.isoformat() < now_iso(), "link": "#/esportazioni"})
    deadlines += _ross_pending_days(conn, t)
    y, q = int(t[:4]), (int(t[5:7]) - 1) // 3 + 1
    pq, py = (q - 1, y) if q > 1 else (4, y - 1)
    obl = row(conn.execute("SELECT * FROM obligations WHERE kind='comunicazione_trimestrale' AND period=?",
                           (f"{py}-T{pq}",)))
    due_q = date(y, 3 * (q - 1) + 1, 15).isoformat()
    sched = [{"text": f"Comunicazione e versamento imposta {pq}° trimestre {py}", "due": due_q,
              "status": (obl or {}).get("status", "da_fare"), "link": "#/imposta",
              "note": "Regolamento art. 6: entro il 15 del mese successivo al trimestre, anche con zero pernottamenti "
                      "(informative comunali). Verificare proroghe."}]
    sched += _tax_rule_reminders(conn, t)
    for o in rows(conn.execute("SELECT id, ref, booker_name, option_expires_at FROM bookings WHERE status='opzione' "
                               "AND option_expires_at IS NOT NULL ORDER BY option_expires_at")):
        if o["option_expires_at"][:10] <= week:
            sched.append({"text": f"Opzione {o['ref']} · {o['booker_name']}: confermare o lasciar scadere",
                          "due": o["option_expires_at"], "status": "da_fare", "link": f"#/prenotazione/{o['id']}",
                          "note": "Alla scadenza l'opzione decade e libera il calendario (nessuna conferma automatica)."})
    if int(t[5:7]) <= 6:
        oa = row(conn.execute("SELECT * FROM obligations WHERE kind='dichiarazione_annuale' AND period=?",
                              (str(y - 1),)))
        sched.append({"text": f"Dichiarazione annuale imposta {y - 1}", "due": f"{y}-06-30",
                      "status": (oa or {}).get("status", "da_fare"), "link": "#/imposta",
                      "note": "Entro il 30 giugno, solo in via telematica (modello D.M. MEF 29/04/2022), "
                              "direttamente o tramite intermediario abilitato."})
    bk = get_setting(conn, "backup", {}) or {}
    st = get_setting(conn, "structure", {}) or {}
    setup_todo = []
    if not st.get("category_confirmed"):
        setup_todo.append("Confermare la categoria della struttura (imposta di soggiorno non calcolabile).")
    if not (st.get("alloggiati") or {}).get("format"):
        setup_todo.append("Configurare il profilo Alloggiati Web (168 o 174 caratteri).")
    if not st.get("name") or not st.get("address") or not st.get("cin"):
        setup_todo.append("Inserire nome, indirizzo e CIN della struttura.")
    if not st.get("tax_comune"):
        setup_todo.append("Indicare il Comune dell'imposta di soggiorno (come scritto nelle regole dell'imposta).")
    if not (st.get("ross") or {}).get("code"):
        setup_todo.append("Inserire il codice struttura ROSS 1000 assegnato dall'ente.")
    elif not (st.get("ross") or {}).get("units") or not (st.get("ross") or {}).get("beds"):
        setup_todo.append("Indicare unità ricettive e letti disponibili per ROSS 1000.")
    if st.get("ross_sends_alloggiati") is None:
        setup_todo.append("Indicare se ROSS 1000 trasmette già ad Alloggiati Web (per evitare doppi invii).")
    if conn.execute("SELECT COUNT(*) FROM tax_rules WHERE status='approvata'").fetchone()[0] == 0:
        setup_todo.append("Creare e approvare la regola dell'imposta di soggiorno del proprio Comune (Imposta → "
                          "Regole; quella di Alghero è inclusa come esempio da verificare).")
    if not st.get("capacity"):
        setup_todo.append("Indicare la capienza confermata dell'appartamento.")
    turnovers = bookings.turnover_list(conn, add_days(t, -1), week)
    corrections = rows(conn.execute("SELECT * FROM corrections WHERE status='aperta' ORDER BY id"))
    return {"today": t, "arrivals": arr, "departures": dep, "present": present, "open_items": open_items,
            "to_collect_cents": to_collect, "tax_to_collect_cents": tax_to_collect, "deadlines": deadlines,
            "schedule": sched, "backup": bk, "setup_todo": setup_todo, "turnovers": turnovers,
            "next_free": _next_free(conn, t), "corrections": corrections,
            "stale_documents": retention.stale_documents(conn), "maintenance": maintenance.today_items(conn, t),
            "deadline_note": "Termini Alloggiati: entro 24 ore dall'arrivo; entro 6 ore per soggiorni non superiori "
                             "a 24 ore (D.M. 7/1/2013 come modificato dal D.M. 16/09/2021, art. 1). ROSS 1000: "
                             "movimenti entro 24 ore (Regione Sardegna, D.G.R. 10/20 del 17/03/2015), comprese le "
                             "giornate senza ospiti e le chiusure. I promemoria compaiono solo a programma aperto."}


def _tax_rule_reminders(conn, t: str) -> list[dict]:
    """Promemoria: manca una regola dell'imposta approvata per l'anno successivo (da dicembre) o per notti già
    prenotate. Il programma non proroga da solo le tariffe: va creata e approvata la nuova versione."""
    st = get_setting(conn, "structure", {}) or {}
    comune, cat = st.get("tax_comune") or "", st.get("tax_category")
    if not cat:
        return []  # categoria non ancora indicata: già tra le voci di configurazione

    def covered(day: str) -> bool:
        return bool(conn.execute("SELECT 1 FROM tax_rules WHERE status='approvata' AND comune=? AND category=? "
                                 "AND valid_from <= ? AND valid_to >= ?", (comune, cat, day, day)).fetchone())

    note = ("Il programma non applica proroghe automatiche delle tariffe: verificare la delibera del Comune o la "
            "pagina SECAL e creare in Imposta → Regole la nuova versione (anche con le stesse tariffe), poi approvarla.")
    out, y = [], int(t[:4])
    years: dict[int, list[dict]] = {}
    for b in rows(conn.execute("SELECT id, ref, arrival, departure FROM bookings WHERE status IN "
                               "('opzione','confermata','in_corso') AND departure > ? ORDER BY arrival", (t,))):
        for day in {max(b["arrival"], t), add_days(b["departure"], -1)}:
            if not covered(day):
                years.setdefault(int(day[:4]), []).append(b)
    for yr, bks in sorted(years.items()):
        refs = sorted({b["ref"] for b in bks})
        out.append({"text": f"Imposta di soggiorno {yr}: nessuna regola approvata per {len(refs)} prenotazioni "
                            f"({', '.join(refs[:4])}{'…' if len(refs) > 4 else ''}): il calcolo resta «da verificare»",
                    "due": min(b["arrival"] for b in bks), "status": "da_fare", "link": "#/imposta", "note": note})
    if t[5:] >= "12-01" and not covered(f"{y + 1}-01-01") and (y + 1) not in years:
        out.append({"text": f"Tariffe dell'imposta di soggiorno {y + 1}: inserire e approvare la nuova regola",
                    "due": f"{y}-12-31", "status": "da_fare", "link": "#/imposta", "note": note})
    return out


def _ross_pending_days(conn, today: str) -> list[dict]:
    """Giornate ROSS 1000 trascorse (fino a ieri) non coperte da un file dichiarato caricato.

    Si parte dal giorno successivo alla configurazione del codice ROSS (mai prima) e al massimo da 60 giorni fa:
    chi inserisce i movimenti direttamente sul portale può ignorare il promemoria.
    """
    st = get_setting(conn, "structure", {}) or {}
    since = (st.get("ross") or {}).get("configured_on")
    if not (st.get("ross") or {}).get("code") or not since:
        return []
    start = max(add_days(since, 1), add_days(today, -60))
    end = add_days(today, -1)
    if start > end:
        return []
    covered = set()
    for b in rows(conn.execute("SELECT period_from, period_to FROM export_batches WHERE kind='ross' AND status IN "
                               "('caricamento_dichiarato','esito_registrato') AND period_to >= ? AND period_from <= ?",
                               (start, end))):
        x = max(b["period_from"], start)
        while x <= min(b["period_to"], end):
            covered.add(x)
            x = add_days(x, 1)
    missing = [x.isoformat() for x in nights(start, add_days(end, 1)) if x.isoformat() not in covered]
    if not missing:
        return []
    from datetime import datetime
    first_due = datetime.fromisoformat(f"{add_days(missing[0], 1)}T23:59").replace(tzinfo=config.TZ)
    return [{"text": f"ROSS 1000: {len(missing)} giornate non ancora dichiarate (dal {missing[0][8:]}/{missing[0][5:7]} "
                     f"al {missing[-1][8:]}/{missing[-1][5:7]})", "due": first_due.isoformat(timespec="minutes"),
             "basis": "entro 24 ore; anche giornate a zero e chiusure. Se le hai inserite direttamente sul portale, "
                      "ignora questo promemoria.", "overdue": first_due.isoformat() < now_iso(),
             "link": "#/esportazioni"}]


def _next_free(conn, start: str, horizon: int = 180) -> list[dict]:
    """Primi periodi liberi (notti) entro l'orizzonte, in base al solo calendario interno."""
    end_h = add_days(start, horizon)
    busy = set()
    for b in rows(conn.execute("SELECT arrival, departure FROM bookings WHERE status IN "
                               "('opzione','confermata','in_corso','conclusa') AND departure > ? AND arrival < ?",
                               (start, end_h))):
        busy |= {n.isoformat() for n in nights(b["arrival"], b["departure"])}
    for bl in rows(conn.execute("SELECT start, end_excl FROM blocks WHERE end_excl > ? AND start < ?", (start, end_h))):
        busy |= {n.isoformat() for n in nights(bl["start"], bl["end_excl"])}
    out, run = [], None
    for k in range(horizon):
        day = add_days(start, k)
        if day not in busy:
            run = run or {"from": day}
            run["to"] = add_days(day, 1)
        elif run:
            out.append(run)
            run = None
            if len(out) == 3:
                return out
    if run:
        run["open_end"] = True
        out.append(run)
    return out[:3]


# ======================= calendario e prenotazioni =======================
@route("GET", r"/api/calendar")
def calendar(req, conn):
    bookings.expire_options(conn)
    s, e = d(req.q("from")).isoformat(), d(req.q("to")).isoformat()
    if (date.fromisoformat(e) - date.fromisoformat(s)).days > 400:
        raise AppError("Periodo troppo lungo.")
    out = bookings.calendar(conn, s, e)
    out["occupancy"] = bookings.occupancy(conn, s, e)
    return out


@route("GET", r"/api/availability")
def availability(req, conn):
    ex = req.q("exclude")
    return bookings.check_availability(conn, d(req.q("from")).isoformat(), d(req.q("to")).isoformat(),
                                       req.q("checkin") or None, req.q("checkout") or None,
                                       exclude_booking=_id(ex) if ex else None)


@route("GET", r"/api/bookings")
def list_bookings(req, conn):
    q = (req.q("q") or "").strip()
    st = req.q("status")
    sql, args = "SELECT * FROM bookings WHERE 1=1", []
    if q:
        sql += " AND (booker_name LIKE ? OR ref LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if st:
        sql += " AND status=?"
        args.append(st)
    sql += " ORDER BY arrival DESC LIMIT 300"
    out = rows(conn.execute(sql, args))
    for b in out:
        b["status_label"] = bookings.STATUS_LABEL[b["status"]]
        b["n_guests"] = conn.execute("SELECT COUNT(*) FROM guests WHERE booking_id=?", (b["id"],)).fetchone()[0]
    return {"bookings": out}


@route("POST", r"/api/bookings")
def create_booking(req, conn):
    b = bookings.create(conn, req.json)
    if req.json.get("price_items"):
        bookings.set_price_items(conn, b["id"], req.json["price_items"])
    return {"booking": b, "capacity_warning": bookings.capacity_warning(conn, b["guests_expected"])}


@route("GET", r"/api/bookings/(\d+)")
def booking_detail(req, conn, bid):
    bid = _id(bid)
    b = bookings.get(conn, bid)
    b["status_label"] = bookings.STATUS_LABEL[b["status"]]
    gs = [guests.public(g) for g in rows(conn.execute(
        "SELECT * FROM guests WHERE booking_id=? ORDER BY position, id", (bid,)))]
    for g in gs:
        g["duplicates"] = guests.duplicates(conn, g)
        g["missing"] = [e["message"] for e in guests.check(guests.get(conn, g["id"]),
                                                           guests.doc_of(guests.get(conn, g["id"])), "verifica")]
    # ospiti di un soggiorno che termina il giorno di arrivo di questo: per collegare una proroga (limite 7 notti)
    prev = rows(conn.execute(
        "SELECT g.id, g.surname, g.name, g.birth_date, p.ref FROM guests g JOIN bookings p ON p.id=g.booking_id "
        "WHERE p.id != ? AND p.departure = ? AND p.status NOT IN ('annullata','no_show','opzione_scaduta','bozza') "
        "AND g.anonymized_at IS NULL AND g.presence != 'non_arrivata' ORDER BY p.id, g.position, g.id",
        (bid, b["arrival"])))
    return {"booking": b, "guests": gs, "prev_guests": prev, "balances": money.balances(conn, bid),
            "movements": money.movements_for(conn, bid), "tax": tax.compute_booking(conn, bid),
            "consolidated": tax.consolidated(conn, bid),
            "receipts": rows(conn.execute("SELECT id, year, number, issued_on, amount_cents, status, cancel_reason "
                                          "FROM tax_receipts WHERE booking_id=? ORDER BY id", (bid,))),
            "open_items": consistency.open_items_for_booking(conn, b),
            "corrections": rows(conn.execute("SELECT * FROM corrections WHERE booking_id=? ORDER BY id DESC",
                                             (bid,))),
            "exports": rows(conn.execute(
                "SELECT DISTINCT b.id, b.kind, b.status, b.created_at, b.file_name FROM export_batches b JOIN "
                "export_items i ON i.batch_id=b.id WHERE i.guest_id IN (SELECT id FROM guests WHERE booking_id=?) "
                "ORDER BY b.id DESC", (bid,))),
            "capacity_warning": bookings.capacity_warning(conn, max(b["guests_expected"], len(gs))),
            "lists": {"tourism": exports.TOURISM, "transport": exports.TRANSPORT, "channel": exports.CHANNEL},
            "linked": rows(conn.execute("SELECT id, ref, arrival, departure FROM bookings WHERE id=? OR "
                                        "linked_booking_id=?", (b["linked_booking_id"] or -1, bid)))}


@route("POST", r"/api/bookings/(\d+)/preview", write=False)
def booking_preview(req, conn, bid):
    return bookings.preview_update(conn, _id(bid), req.json)


@route("PUT", r"/api/bookings/(\d+)")
def booking_update(req, conn, bid):
    b = bookings.update(conn, _id(bid), req.json)
    if "price_items" in req.json:
        bookings.set_price_items(conn, b["id"], req.json["price_items"])
    return {"booking": bookings.get(conn, b["id"])}


@route("POST", r"/api/bookings/(\d+)/status/(\w+)")
def booking_status(req, conn, bid, action):
    return {"booking": bookings.change_status(conn, _id(bid), action, req.json)}


@route("POST", r"/api/bookings/(\d+)/checkin")
def booking_checkin(req, conn, bid):
    return {"booking": bookings.check_in(conn, _id(bid), req.json)}


@route("GET", r"/api/bookings/(\d+)/checkout-summary")
def booking_checkout_summary(req, conn, bid):
    return bookings.checkout_summary(conn, _id(bid))


@route("POST", r"/api/bookings/(\d+)/checkout")
def booking_checkout(req, conn, bid):
    return {"booking": bookings.check_out(conn, _id(bid), req.json)}


@route("POST", r"/api/bookings/(\d+)/prep")
def booking_prep(req, conn, bid):
    bookings.set_prep_status(conn, _id(bid), req.json.get("status"))
    return {"ok": True}


@route("POST", r"/api/bookings/(\d+)/tax-refusal")
def tax_refusal(req, conn, bid):
    note = (req.json.get("note") or "").strip() or None
    conn.execute("UPDATE bookings SET tax_refusal_note=?, updated_at=?, version=version+1 WHERE id=?",
                 (note, now_iso(), _id(bid)))
    audit(conn, "rifiuto_imposta_annotato", "booking", _id(bid))
    return {"ok": True}


@route("POST", r"/api/bookings/(\d+)/tax/consolidate")
def tax_consolidate(req, conn, bid):
    return {"assessment": tax.consolidate(conn, _id(bid), req.json.get("reason"))}


# ======================= ospiti =======================
@route("POST", r"/api/bookings/(\d+)/guests")
def guest_create(req, conn, bid):
    g = guests.save(conn, _id(bid), req.json)
    return {"guest": guests.public(g), "duplicates": guests.duplicates(conn, g)}


@route("GET", r"/api/guests/(\d+)")
def guest_get(req, conn, gid):
    g = guests.get(conn, _id(gid))
    out = guests.public(g, with_doc=True)
    out["duplicates"] = guests.duplicates(conn, g)
    out["missing"] = guests.check(g, guests.doc_of(g), "verifica")
    return {"guest": out}


@route("PUT", r"/api/guests/(\d+)")
def guest_update(req, conn, gid):
    g = guests.get(conn, _id(gid))
    g = guests.save(conn, g["booking_id"], req.json, g["id"])
    return {"guest": guests.public(g), "duplicates": guests.duplicates(conn, g)}


@route("POST", r"/api/guests/(\d+)/verify")
def guest_verify(req, conn, gid):
    return {"guest": guests.public(guests.verify(conn, _id(gid)))}


@route("POST", r"/api/guests/(\d+)/stay")
def guest_stay(req, conn, gid):
    return {"guest": guests.public(guests.set_stay(conn, _id(gid), req.json))}


@route("POST", r"/api/guests/(\d+)/not-arrived")
def guest_not_arrived(req, conn, gid):
    g = guests.get(conn, _id(gid))
    bookings.mark_not_arrived(conn, g["booking_id"], g["id"])
    return {"ok": True}


@route("POST", r"/api/guests/(\d+)/departure")
def guest_departure(req, conn, gid):
    g = guests.get(conn, _id(gid))
    bookings.guest_departure(conn, g["booking_id"], g["id"], req.json.get("date"))
    return {"ok": True}


@route("POST", r"/api/guests/(\d+)/delete")
def guest_delete(req, conn, gid):
    guests.delete(conn, _id(gid), req.json.get("reason"))
    return {"ok": True}


_GUEST_ACTIONS = {
    "save": lambda c, g, data: guests.save(c, g["booking_id"], data, g["id"]),
    "stay": lambda c, g, data: guests.set_stay(c, g["id"], data),
    "not_arrived": lambda c, g, data: bookings.mark_not_arrived(c, g["booking_id"], g["id"]),
    "departure": lambda c, g, data: bookings.guest_departure(c, g["booking_id"], g["id"], data.get("date")),
    "delete": lambda c, g, data: guests.delete(c, g["id"], data.get("reason") or "anteprima"),
}


@route("POST", r"/api/guests/(\d+)/preview", write=False)
def guest_preview(req, conn, gid):
    """Conseguenze di una modifica all'ospite, simulata con lo stesso codice del salvataggio e poi annullata."""
    g = guests.get(conn, _id(gid))
    act = _GUEST_ACTIONS.get(req.json.get("action"))
    if not act:
        raise AppError("Azione non prevista.")
    data = req.json.get("data") or {}
    return consistency.simulate(conn, g["booking_id"], lambda c: act(c, g, data))


@route("POST", r"/api/bookings/(\d+)/guests/preview", write=False)
def guest_create_preview(req, conn, bid):
    b = bookings.get(conn, _id(bid))
    return consistency.simulate(conn, b["id"], lambda c: guests.save(c, b["id"], req.json))


@route("GET", r"/api/tables/(\w+)")
def table_search(req, conn, kind):
    return {"items": tables.search(kind, req.q("q", ""), 25, req.q("on"))}


# ======================= denaro =======================
@route("POST", r"/api/movements")
def movement_create(req, conn):
    return {"movement": money.record(conn, req.json)}


@route("POST", r"/api/movements/(\d+)/reverse")
def movement_reverse(req, conn, mid):
    return {"movement": money.reverse(conn, _id(mid), req.json.get("reason"), req.json.get("uid"))}


@route("POST", r"/api/bookings/(\d+)/receipt")
def receipt_issue(req, conn, bid):
    return {"receipt": money.issue_receipt(conn, _id(bid), req.json.get("date"))}


@route("POST", r"/api/receipts/(\d+)/cancel")
def receipt_cancel(req, conn, rid):
    money.cancel_receipt(conn, _id(rid), req.json.get("reason"))
    return {"ok": True}


@route("GET", r"/api/receipts/(\d+)/pdf")
def receipt_pdf(req, conn, rid):
    r = row(conn.execute("SELECT * FROM tax_receipts WHERE id=?", (_id(rid),)))
    if not r:
        raise AppError("Quietanza inesistente.", 404)
    b = bookings.get(conn, r["booking_id"])
    n = conn.execute("SELECT COUNT(*) FROM guests WHERE booking_id=? AND presence IN ('presente','partita')",
                     (b["id"],)).fetchone()[0]
    return FileResponse(reports.receipt_pdf(conn, r, b, n), "application/pdf",
                        f"quietanza_{r['year']}_{r['number']}.pdf", inline=True)


# ======================= imposta: regole, versamenti, periodi =======================
@route("GET", r"/api/tax/rules")
def tax_rules(req, conn):
    out = rows(conn.execute("SELECT * FROM tax_rules ORDER BY valid_from DESC, id DESC"))
    for r in out:
        r["exemptions"] = json.loads(r["exemptions"])
    return {"rules": out, "exemption_labels": tax.EXEMPTIONS}


@route("POST", r"/api/tax/rules")
def tax_rule_add(req, conn):
    return {"id": tax.add_rule(conn, req.json)}


@route("POST", r"/api/tax/rules/(\d+)/approve")
def tax_rule_approve(req, conn, rid):
    tax.approve_rule(conn, _id(rid), req.json.get("minor_rule"))
    return {"ok": True}


@route("POST", r"/api/tax/rules/(\d+)/revoke")
def tax_rule_revoke(req, conn, rid):
    tax.revoke_rule(conn, _id(rid), req.json.get("reason"))
    return {"ok": True}


@route("GET", r"/api/remittances")
def remittances(req, conn):
    return {"remittances": rows(conn.execute("SELECT * FROM remittances ORDER BY year DESC, quarter DESC, id")),
            "obligations": rows(conn.execute("SELECT * FROM obligations ORDER BY period DESC"))}


@route("POST", r"/api/remittances")
def remittance_add(req, conn):
    j = req.json
    if row(conn.execute("SELECT id FROM remittances WHERE uid=?", (j.get("uid") or "",))):
        return {"ok": True, "duplicate_request": True}
    if not j.get("uid"):
        raise AppError("Identificativo operazione mancante.")
    q = int(j.get("quarter") or 0)
    if q not in (1, 2, 3, 4):
        raise AppError("Trimestre non valido.")
    amt = parse_cents(j.get("amount"))
    if amt <= 0:
        raise AppError("Importo non valido.")
    if not (j.get("reference") or "").strip():
        raise AppError("Indicare il riferimento del versamento (CRO/IUV/numero operazione).")
    cur = conn.execute("INSERT INTO remittances(uid,year,quarter,amount_cents,paid_on,method,reference,note,"
                       "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (j["uid"], int(j.get("year")), q, amt, d(j.get("paid_on")).isoformat(), j.get("method"),
                        j["reference"].strip(), j.get("note"), now_iso()))
    audit(conn, "versamento_registrato", "remittance", cur.lastrowid)
    return {"id": cur.lastrowid}


@route("POST", r"/api/obligations")
def obligation_set(req, conn):
    j = req.json
    if j.get("kind") not in ("comunicazione_trimestrale", "dichiarazione_annuale"):
        raise AppError("Adempimento non valido.")
    if j.get("status") not in ("da_fare", "dichiarata"):
        raise AppError("Stato non valido.")
    conn.execute("INSERT INTO obligations(kind,period,status,declared_on,reference,note,updated_at) "
                 "VALUES (?,?,?,?,?,?,?) ON CONFLICT(kind,period) DO UPDATE SET status=excluded.status, "
                 "declared_on=excluded.declared_on, reference=excluded.reference, note=excluded.note, "
                 "updated_at=excluded.updated_at",
                 (j["kind"], j.get("period"), j["status"], j.get("declared_on"), j.get("reference"), j.get("note"),
                  now_iso()))
    audit(conn, "adempimento_aggiornato", "obligation", None, f"{j['kind']} {j.get('period')} {j['status']}")
    return {"ok": True}


@route("GET", r"/api/periods/check")
def period_check(req, conn):
    return periods.check(conn, req.q("kind"), req.q("period"))


@route("POST", r"/api/periods/close")
def period_close(req, conn):
    j = req.json
    return {"closure": periods.close(conn, j.get("kind"), j.get("period"), bool(j.get("confirm_anomalies")),
                                     j.get("reason"))}


@route("GET", r"/api/periods/closures")
def period_closures(req, conn):
    return {"closures": rows(conn.execute("SELECT id, kind, period, snapshot_hash, status, supersedes_id, reason, "
                                          "created_at FROM period_closures ORDER BY id DESC"))}


@route("GET", r"/api/periods/export")
def period_export(req, conn):
    snap = periods.check(conn, req.q("kind"), req.q("period"))
    fmt = req.q("fmt", "csv")
    name = f"riepilogo_{snap['period']}"
    if fmt == "pdf":
        return FileResponse(reports.period_pdf(conn, snap), "application/pdf", name + ".pdf", inline=True)
    h, data = reports.period_table(snap)
    if fmt == "xlsx":
        return FileResponse(reports.to_xlsx("Riepilogo", h, data),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", name + ".xlsx")
    return FileResponse(reports.to_csv(h, data), "text/csv; charset=utf-8", name + ".csv")


@route("GET", r"/api/staytour")
def staytour(req, conn):
    sh = periods.staytour_sheet(conn, int(req.q("year")), int(req.q("quarter")))
    if req.q("fmt") == "pdf":
        return FileResponse(reports.staytour_pdf(conn, sh), "application/pdf",
                            f"prospetto_imposta_{req.q('year')}_T{req.q('quarter')}.pdf", inline=True)
    return sh


@route("GET", r"/api/exemption-draft/(\w+)")
def exemption_draft(req, conn, kind):
    return FileResponse(reports.exemption_draft_pdf(conn, kind), "application/pdf", f"bozza_{kind}.pdf", inline=True)


# ======================= esportazioni =======================
def _strip(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


@route("GET", r"/api/exports")
def exports_list(req, conn):
    bs = rows(conn.execute("SELECT * FROM export_batches ORDER BY id DESC LIMIT 200"))
    for b in bs:
        b["status_label"] = exports.BATCH_LABEL.get(b["status"], b["status"])
        b["checks"] = json.loads(b["checks"])
        b["items"] = rows(conn.execute(
            "SELECT i.guest_id, i.ross_day, i.outcome, i.outcome_note, g.surname, g.name FROM export_items i "
            "LEFT JOIN guests g ON g.id=i.guest_id WHERE i.batch_id=?", (b["id"],)))
        b["receipts"] = rows(conn.execute("SELECT id, filename, delete_after FROM attachments WHERE "
                                          "ref_table='export_batches' AND ref_id=?", (b["id"],)))
    pending = rows(conn.execute(
        "SELECT g.id guest_id, g.booking_id, b.ref, g.surname, g.name, g.stay_arrival, g.alloggiati_status, "
        "g.verified_at FROM guests g JOIN bookings b ON b.id=g.booking_id WHERE g.presence IN ('presente','partita') "
        "AND g.alloggiati_status NOT IN ('caricamento_dichiarato','esito_registrato') ORDER BY g.stay_arrival"))
    st = get_setting(conn, "structure", {}) or {}
    return {"batches": bs, "pending": pending,
            "corrections": rows(conn.execute("SELECT * FROM corrections ORDER BY status, id DESC LIMIT 200")),
            "ross_sends_alloggiati": st.get("ross_sends_alloggiati"),
            "alloggiati_profile": st.get("alloggiati"), "tables": tables.version_label(),
            "pending_deletions": rows(conn.execute("SELECT * FROM ross_pending_deletions ORDER BY id DESC"))}


@route("GET", r"/api/exports/alloggiati/preview")
def alloggiati_preview(req, conn):
    return _strip(exports.alloggiati_preview(conn, d(req.q("from")).isoformat(), d(req.q("to")).isoformat(),
                                             req.q("include_sent") == "1"))


@route("POST", r"/api/exports/alloggiati")
def alloggiati_generate(req, conn):
    j = req.json
    batch, data = exports.alloggiati_generate(conn, d(j.get("from")).isoformat(), d(j.get("to")).isoformat(),
                                              bool(j.get("confirm_partial")), bool(j.get("include_sent")),
                                              bool(j.get("confirm_double")), bool(j.get("confirm_long_stay")))
    return {"batch": batch, "file_name": batch["file_name"], "content_b64": base64.b64encode(data).decode()}


@route("GET", r"/api/exports/ross/preview")
def ross_preview(req, conn):
    return exports.ross_preview(conn, d(req.q("from")).isoformat(), d(req.q("to")).isoformat())


@route("POST", r"/api/exports/ross")
def ross_generate(req, conn):
    j = req.json
    batch, data = exports.ross_generate(conn, d(j.get("from")).isoformat(), d(j.get("to")).isoformat(),
                                        bool(j.get("confirm_partial")))
    return {"batch": batch, "file_name": batch["file_name"], "content_b64": base64.b64encode(data).decode()}


@route("POST", r"/api/exports/(\d+)/declare")
def export_declare(req, conn, bid):
    exports.declare_upload(conn, _id(bid), req.json.get("when"))
    return {"ok": True}


@route("POST", r"/api/exports/(\d+)/outcome")
def export_outcome(req, conn, bid):
    return exports.register_outcome(conn, _id(bid), req.json)


@route("POST", r"/api/exports/(\d+)/receipt", raw=True)
def export_receipt(req, conn, bid):
    bid = _id(bid)
    b = row(conn.execute("SELECT * FROM export_batches WHERE id=?", (bid,)))
    if not b or b["status"] not in ("esito_registrato", "da_correggere"):
        raise AppError("Registrare prima l'esito del caricamento.")
    keep = (date.today().replace(year=date.today().year + 5)).isoformat()
    aid = attachments.save(conn, "ricevuta_alloggiati" if b["kind"] == "alloggiati" else "esito_ross",
                           "export_batches", bid, req.headers.get("X-Filename") or "ricevuta.pdf", req.body,
                           keep)
    purged = exports.receipt_acquired(conn, bid) if b["kind"] == "alloggiati" else 0
    return {"attachment_id": aid, "documents_purged": purged, "keep_until": keep}


@route("GET", r"/api/attachments/(\d+)")
def attachment_get(req, conn, aid):
    a, data = attachments.load(conn, _id(aid))
    return FileResponse(data, a["mime"], a["filename"], inline=True)


@route("POST", r"/api/corrections/(\d+)/resolve")
def correction_resolve(req, conn, cid):
    exports.resolve_correction(conn, _id(cid), req.json.get("resolution"))
    return {"ok": True}


# ======================= blocchi e chiusure =======================
@route("POST", r"/api/blocks")
def block_create(req, conn):
    return {"id": bookings.create_block(conn, req.json)}


@route("POST", r"/api/blocks/(\d+)/delete")
def block_delete(req, conn, bid):
    bookings.delete_block(conn, _id(bid))
    return {"ok": True}


@route("GET", r"/api/closures")
def closures(req, conn):
    return {"closures": rows(conn.execute("SELECT * FROM closures ORDER BY start DESC"))}


@route("POST", r"/api/closures")
def closure_create(req, conn):
    return {"id": bookings.create_closure(conn, req.json)}


@route("POST", r"/api/closures/(\d+)/delete")
def closure_delete(req, conn, cid):
    conn.execute("DELETE FROM closures WHERE id=?", (_id(cid),))
    audit(conn, "chiusura_ross_rimossa", "closure", _id(cid))
    return {"ok": True}


# ======================= manutenzione =======================
@route("GET", r"/api/maintenance")
def maintenance_list(req, conn):
    return maintenance.list_jobs(conn, req.q("stato", "aperti"))


@route("POST", r"/api/maintenance")
def maintenance_create(req, conn):
    return {"job": maintenance.create(conn, req.json)}


@route("GET", r"/api/maintenance/(\d+)")
def maintenance_get(req, conn, jid):
    return {"job": maintenance.get(conn, _id(jid))}


@route("PUT", r"/api/maintenance/(\d+)")
def maintenance_update(req, conn, jid):
    return {"job": maintenance.update(conn, _id(jid), req.json)}


@route("POST", r"/api/maintenance/(\d+)/status")
def maintenance_status(req, conn, jid):
    return {"job": maintenance.set_status(conn, _id(jid), req.json)}


@route("POST", r"/api/maintenance/(\d+)/notes")
def maintenance_note(req, conn, jid):
    return {"job": maintenance.add_note(conn, _id(jid), req.json.get("text"))}


@route("POST", r"/api/maintenance/(\d+)/attachments", raw=True)
def maintenance_attachment(req, conn, jid):
    from urllib.parse import unquote
    return maintenance.add_attachment(conn, _id(jid), unquote(req.headers.get("X-Filename") or "foto"), req.body)


@route("POST", r"/api/maintenance/(\d+)/attachments/(\d+)/delete")
def maintenance_attachment_delete(req, conn, jid, aid):
    return {"job": maintenance.remove_attachment(conn, _id(jid), _id(aid))}


@route("GET", r"/api/maintenance/options")
def maintenance_options(req, conn):
    return maintenance.options(conn)


@route("GET", r"/api/maintenance/assets")
def maintenance_assets(req, conn):
    return maintenance.asset_list(conn)


@route("POST", r"/api/maintenance/assets")
def maintenance_asset_create(req, conn):
    return {"asset": maintenance.asset_save(conn, req.json)}


@route("GET", r"/api/maintenance/assets/(\d+)")
def maintenance_asset_get(req, conn, aid):
    return {"asset": maintenance.asset_get(conn, _id(aid))}


@route("PUT", r"/api/maintenance/assets/(\d+)")
def maintenance_asset_update(req, conn, aid):
    return {"asset": maintenance.asset_save(conn, req.json, _id(aid))}


@route("POST", r"/api/maintenance/assets/(\d+)/attachments", raw=True)
def maintenance_asset_attachment(req, conn, aid):
    from urllib.parse import unquote
    return {"asset": maintenance.asset_add_attachment(conn, _id(aid), unquote(req.headers.get("X-Filename") or
                                                                              "documento"), req.body)}


@route("POST", r"/api/maintenance/assets/(\d+)/attachments/(\d+)/delete")
def maintenance_asset_attachment_delete(req, conn, aid, att):
    return {"asset": maintenance.asset_remove_attachment(conn, _id(aid), _id(att))}


@route("GET", r"/api/maintenance/contractors")
def maintenance_contractors(req, conn):
    return maintenance.contractor_list(conn)


@route("POST", r"/api/maintenance/contractors")
def maintenance_contractor_create(req, conn):
    return {"contractor": maintenance.contractor_save(conn, req.json)}


@route("GET", r"/api/maintenance/contractors/(\d+)")
def maintenance_contractor_get(req, conn, cid):
    return {"contractor": maintenance.contractor_get(conn, _id(cid))}


@route("PUT", r"/api/maintenance/contractors/(\d+)")
def maintenance_contractor_update(req, conn, cid):
    return {"contractor": maintenance.contractor_save(conn, req.json, _id(cid))}


# ======================= documenti (OCR) =======================
@route("GET", r"/api/ocr/status", use_db=False)
def ocr_status(req, conn):
    return ocr.status()


@route("POST", r"/api/ocr/upload", raw=True, reassess=False, use_db=False)
def ocr_upload(req, conn):
    return ocr.add_upload(req.body, req.headers.get("X-Filename") or "documento")


@route("GET", r"/api/ocr/([\w-]+)/preview", use_db=False)
def ocr_preview(req, conn, uid):
    return FileResponse(ocr.preview(uid, int(req.q("rot", "0") or 0)), "image/jpeg", None, inline=True)


@route("POST", r"/api/ocr/([\w-]+)/read", reassess=False, use_db=False)
def ocr_read(req, conn, uid):
    return ocr.read(uid, int(req.json.get("rotation") or 0))


@route("POST", r"/api/ocr/merge", reassess=False, use_db=False)
def ocr_merge(req, conn):
    return ocr.merge(req.json.get("readings") or [])


@route("POST", r"/api/ocr/([\w-]+)/discard", reassess=False, use_db=False)
def ocr_discard(req, conn, uid):
    ocr.discard(uid)
    return {"ok": True}


# ======================= backup, ripristino, conservazione =======================
@route("GET", r"/api/backup/status")
def backup_status(req, conn):
    files = sorted((config.data_dir() / "backup").glob("*.gcbak"), reverse=True)
    return {"backup": get_setting(conn, "backup", {}) or {}, "data_dir": str(config.data_dir()),
            "db_path": str(config.db_path()), "drives": backup.removable_drives(),
            "local_files": [{"name": f.name, "size": f.stat().st_size} for f in files[:20]]}


def _own_conn(fn):
    """Il backup copia il database: va eseguito su una connessione propria, fuori da transazioni aperte."""
    from .db import connect
    c = connect()
    try:
        return fn(c)
    finally:
        c.close()


@route("POST", r"/api/backup/local", reassess=False, use_db=False)
def backup_local(req, conn):
    p = _own_conn(backup.create_local)
    return {"path": str(p), "name": p.name}


@route("POST", r"/api/backup/external", reassess=False, use_db=False)
def backup_external(req, conn):
    target = req.json.get("dir") or ""
    p = _own_conn(lambda c: backup.copy_external(c, target))
    return {"path": str(p)}


@route("GET", r"/api/backup/file")
def backup_file(req, conn):
    name = req.q("name") or ""
    p = (config.data_dir() / "backup" / name)
    if "/" in name or "\\" in name or not name.endswith(".gcbak") or not p.is_file():
        raise AppError("File di backup non trovato.", 404)
    return FileResponse(p.read_bytes(), "application/octet-stream", name)


@route("POST", r"/api/backup/verify", auth=False, raw=True, reassess=False, use_db=False)
def backup_verify(req, conn):
    secret = base64.b64decode(req.headers.get("X-Backup-Secret") or "").decode("utf-8", "ignore")
    return backup.verify_bytes(req.body, secret=secret)


@route("POST", r"/api/backup/restore", auth=False, raw=True, reassess=False, use_db=False)
def backup_restore(req, conn):
    from .db import connect
    c = connect()
    try:
        configured = accounts.is_setup(c)
    finally:
        c.close()
    if configured and not (req.session and STATE.dek):
        raise AppError("Per sostituire un archivio esistente occorre prima accedere.", 401)
    secret = base64.b64decode(req.headers.get("X-Backup-Secret") or "").decode("utf-8", "ignore")
    with STATE.lock:  # il ripristino gestisce file e connessioni da sé
        rep = backup.restore(req.body, secret, req.headers.get("X-Confirm-Replace") == "1")
    STATE.sessions.clear()
    STATE.dek = None
    return rep


@route("GET", r"/api/retention")
def retention_info(req, conn):
    return {"policy": retention.policy(conn), "candidates": retention.anonymize_candidates(conn),
            "stale_documents": retention.stale_documents(conn)}


@route("POST", r"/api/retention/anonymize")
def retention_anonymize(req, conn):
    ids = [int(x) for x in req.json.get("booking_ids") or []]
    allowed = {b["id"] for b in retention.anonymize_candidates(conn)}
    if not ids or set(ids) - allowed:
        raise AppError("Selezionare solo prenotazioni oltre il periodo di conservazione.")
    for i in ids:
        retention.anonymize_booking(conn, i)
    return {"anonymized": len(ids)}


@route("POST", r"/api/tables/import")
def tables_import(req, conn):
    files = {k: base64.b64decode(v) for k, v in (req.json.get("files") or {}).items()}
    meta = tables.import_update(files)
    audit(conn, "tabelle_aggiornate")
    return {"meta": meta}
