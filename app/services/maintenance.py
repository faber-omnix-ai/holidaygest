"""Manutenzione: registro dei lavori da fare nell'appartamento e del loro avanzamento fino alla risoluzione.

Registro separato dal calendario (non blocca date) e dai conti dei soggiorni (preventivo e costo sono solo annotati).
Ogni passo resta nel diario del lavoro: cambi di stato, note, modifiche, foto. Nessun lavoro si cancella: si annulla.
Dalla versione 3 dello schema: apparecchi della casa (con garanzia e manuali), rubrica delle ditte e lavori periodici
(alla risoluzione si crea da solo il lavoro successivo, con scadenza spostata di N mesi dalla data di risoluzione).
"""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date

from ..db import AppError, audit, now_iso, row, rows
from ..util import add_days, d, it, parse_cents
from . import attachments

PRIORITIES = {"urgente": "Urgente", "normale": "Normale", "bassa": "Bassa"}
STATUSES = {"da_fare": "Da fare", "in_corso": "In corso", "risolto": "Risolto", "annullato": "Annullato"}
OPEN = ("da_fare", "in_corso")
# Passaggi ammessi. Da «risolto» o «annullato» si torna solo a «da fare» (riapertura motivata).
TRANSITIONS = {"da_fare": {"in_corso", "risolto", "annullato"}, "in_corso": {"risolto", "annullato"},
               "risolto": {"da_fare"}, "annullato": {"da_fare"}}
FIELD_LABEL = {"title": "titolo", "description": "descrizione", "priority": "priorità", "due_date": "scadenza",
               "contractor": "ditta/tecnico", "quote_cents": "preventivo", "cost_cents": "costo finale",
               "asset_id": "apparecchio", "contractor_id": "ditta/tecnico", "recur_months": "ripetizione"}
SOON_DAYS = 7
WARRANTY_SOON_DAYS = 60
RECUR_CHOICES = [(1, "Ogni mese"), (3, "Ogni 3 mesi"), (6, "Ogni 6 mesi"), (12, "Ogni anno"), (24, "Ogni 2 anni")]
# Suggerimenti per i moduli (testo libero: si può scrivere altro)
CATEGORIES = ["Climatizzatore", "Caldaia / scaldabagno", "Lavatrice", "Lavastoviglie", "Frigorifero",
              "Forno / piano cottura", "Televisore", "Impianto elettrico", "Impianto idraulico",
              "Rilevatore gas / fumo", "Estintore", "Infissi / tapparelle", "Arredo", "Altro"]
SPECIALTIES = ["Idraulico", "Elettricista", "Climatizzazione", "Caldaie", "Elettrodomestici", "Fabbro", "Imbianchino",
               "Falegname", "Muratore", "Giardiniere", "Pulizie", "Disinfestazione", "Tuttofare", "Altro"]
ASSET_FIELDS = {"name": "nome", "category": "tipo", "brand": "marca", "model": "modello", "location": "dove si trova",
                "purchased_on": "data di acquisto", "warranty_until": "garanzia fino al", "notes": "note",
                "active": "in uso"}
CONTRACTOR_FIELDS = {"name": "nome", "specialty": "specialità", "phone": "telefono", "email": "e-mail",
                     "notes": "note", "active": "attiva"}


def _text(v, field: str, maxlen: int) -> str | None:
    s = (v or "").strip() if isinstance(v, str) or v is None else str(v).strip()
    if len(s) > maxlen:
        raise AppError(f"Testo troppo lungo (massimo {maxlen} caratteri).", field=field)
    return s or None


def _cents(v, field: str) -> int | None:
    if v is None or v == "":
        return None
    c = parse_cents(v, FIELD_LABEL[field])
    if c < 0:
        raise AppError("L'importo non può essere negativo.", field=field)
    return c


def _ref(conn, table: str, v, field: str, what: str) -> int | None:
    if v in (None, "", 0, "0"):
        return None
    try:
        i = int(v)
    except (TypeError, ValueError):
        raise AppError(f"{what} non valido.", field=field)
    if not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (i,)).fetchone():
        raise AppError(f"{what} inesistente.", field=field)
    return i


def _months(v) -> int | None:
    if v in (None, "", 0, "0"):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise AppError("Ripetizione non valida.", field="recur_months")
    if not 1 <= n <= 120:
        raise AppError("Ripetizione: da 1 a 120 mesi.", field="recur_months")
    return n


def add_months(day: str, n: int) -> str:
    x = date.fromisoformat(day)
    m = x.month - 1 + n
    y, m = x.year + m // 12, m % 12 + 1
    return date(y, m, min(x.day, calendar.monthrange(y, m)[1])).isoformat()


def recur_label(n: int | None) -> str | None:
    if not n:
        return None
    return dict(RECUR_CHOICES).get(n) or f"Ogni {n} mesi"


def _clean(conn, data: dict, current: dict | None = None) -> dict:
    out = {k: (current or {}).get(k) for k in FIELD_LABEL}
    out["priority"] = out["priority"] or "normale"
    for k in FIELD_LABEL:
        if k not in data:
            continue
        v = data[k]
        if k == "title":
            out[k] = _text(v, k, 120)
        elif k == "description":
            out[k] = _text(v, k, 4000)
        elif k == "contractor":
            out[k] = _text(v, k, 120)
        elif k == "priority":
            out[k] = v or "normale"
        elif k == "due_date":
            out[k] = d(v, "scadenza").isoformat() if v else None
        elif k == "asset_id":
            out[k] = _ref(conn, "maintenance_assets", v, k, "Apparecchio")
        elif k == "contractor_id":
            out[k] = _ref(conn, "maintenance_contractors", v, k, "Ditta")
        elif k == "recur_months":
            out[k] = _months(v)
        else:
            out[k] = _cents(v, k)
    # Ditta: dalla rubrica (contractor_id) oppure per nome (testo libero: si cerca o si aggiunge alla rubrica)
    if "contractor_id" in data:
        out["contractor"] = _contractor_name(conn, out["contractor_id"])
    elif "contractor" in data:
        out["contractor_id"] = _contractor_by_name(conn, out["contractor"]) if out["contractor"] else None
        out["contractor"] = _contractor_name(conn, out["contractor_id"])
    if not out["title"]:
        raise AppError("Indicare che cosa c'è da fare (titolo).", field="title")
    if out["priority"] not in PRIORITIES:
        raise AppError("Priorità non valida.", field="priority")
    if out["recur_months"] and not out["due_date"] and not current:
        raise AppError("Per un lavoro periodico indicare la prima scadenza.", field="due_date")
    return out


def _note(conn, job_id: int, kind: str, text: str) -> None:
    conn.execute("INSERT INTO maintenance_notes(job_id, at, kind, text) VALUES (?,?,?,?)",
                 (job_id, now_iso(), kind, text))


def _job(conn, job_id: int) -> dict:
    j = row(conn.execute("SELECT * FROM maintenance_jobs WHERE id=?", (job_id,)))
    if not j:
        raise AppError("Lavoro di manutenzione inesistente.", 404)
    return j


def _check_version(j: dict, version, what: str = "Lavoro modificato") -> None:
    if version is not None and int(version) != j["version"]:
        raise AppError(f"{what} in un'altra finestra: ricaricare.", 409)


def _decorate(j: dict, today: str) -> dict:
    j = dict(j)
    j["status_label"], j["priority_label"] = STATUSES[j["status"]], PRIORITIES[j["priority"]]
    is_open = j["status"] in OPEN
    j["overdue"] = bool(is_open and j["due_date"] and j["due_date"] < today)
    j["due_soon"] = bool(is_open and j["due_date"] and today <= j["due_date"] <= add_days(today, SOON_DAYS))
    j["recur_label"] = recur_label(j.get("recur_months"))
    return j


def _insert(conn, v: dict, opened_note: str) -> int:
    ts = now_iso()
    cur = conn.execute(
        f"INSERT INTO maintenance_jobs({','.join(v)}, status, created_at, updated_at) "
        f"VALUES ({','.join('?' * len(v))}, 'da_fare', ?, ?)", (*v.values(), ts, ts))
    jid = cur.lastrowid
    _note(conn, jid, "stato", opened_note)
    audit(conn, "manutenzione_aperta", "maintenance_job", jid)
    return jid


def create(conn: sqlite3.Connection, data: dict) -> dict:
    v = _clean(conn, data)
    return get(conn, _insert(conn, v, "Lavoro aperto: Da fare"))


def update(conn: sqlite3.Connection, job_id: int, data: dict) -> dict:
    j = _job(conn, job_id)
    _check_version(j, data.get("version"))
    v = _clean(conn, data, j)
    changed = [k for k in FIELD_LABEL if v[k] != j[k]]
    if not changed:
        return get(conn, job_id)
    sets = ", ".join(f"{k}=?" for k in changed)
    conn.execute(f"UPDATE maintenance_jobs SET {sets}, version=version+1, updated_at=? WHERE id=?",
                 (*[v[k] for k in changed], now_iso(), job_id))
    _note(conn, job_id, "modifica", "Modificati: " + ", ".join(dict.fromkeys(FIELD_LABEL[k] for k in changed)))
    audit(conn, "manutenzione_modificata", "maintenance_job", job_id)
    return get(conn, job_id)


def _spawn_next(conn, j: dict, resolved_day: str) -> int:
    """Lavoro periodico risolto: crea il successivo, scadenza = risoluzione + N mesi. Una volta sola per lavoro."""
    due = add_months(resolved_day, j["recur_months"])
    v = {k: j[k] for k in ("title", "description", "priority", "contractor", "quote_cents", "asset_id",
                           "contractor_id", "recur_months")}
    v.update({"due_date": due, "cost_cents": None, "prev_job_id": j["id"]})
    nid = _insert(conn, v, f"Lavoro periodico ({recur_label(j['recur_months']).lower()}): aperto alla "
                           f"risoluzione del precedente, scadenza {it(due)}")
    conn.execute("UPDATE maintenance_jobs SET next_job_id=? WHERE id=?", (nid, j["id"]))
    _note(conn, j["id"], "stato", f"Prossimo intervento programmato per il {it(due)}")
    return nid


def set_status(conn: sqlite3.Connection, job_id: int, data: dict) -> dict:
    j = _job(conn, job_id)
    _check_version(j, data.get("version"))
    new = data.get("status")
    if new not in STATUSES:
        raise AppError("Stato non valido.")
    if new not in TRANSITIONS[j["status"]]:
        raise AppError(f"Da «{STATUSES[j['status']]}» non si può passare a «{STATUSES[new]}».")
    note = _text(data.get("note"), "note", 2000)
    if new == "annullato" and not note:
        raise AppError("Indicare perché il lavoro non serve più.", field="note")
    if new == "da_fare" and not note:
        raise AppError("Indicare perché il lavoro viene riaperto.", field="note")
    if "cost" in data:  # costo finale indicabile alla chiusura
        cost = _cents(data.get("cost"), "cost_cents")
        if cost is not None:
            conn.execute("UPDATE maintenance_jobs SET cost_cents=? WHERE id=?", (cost, job_id))
    resolved = now_iso() if new == "risolto" else None
    conn.execute("UPDATE maintenance_jobs SET status=?, resolved_at=?, version=version+1, updated_at=? WHERE id=?",
                 (new, resolved, now_iso(), job_id))
    verb = "Riaperto" if new == "da_fare" else STATUSES[new]
    _note(conn, job_id, "stato", f"{STATUSES[j['status']]} → {verb}" + (f": {note}" if note else ""))
    audit(conn, "manutenzione_stato", "maintenance_job", job_id, new)
    if new == "risolto" and j["recur_months"] and not j["next_job_id"]:
        _spawn_next(conn, j, resolved[:10])
    return get(conn, job_id)


def add_note(conn: sqlite3.Connection, job_id: int, text: str) -> dict:
    _job(conn, job_id)
    t = _text(text, "text", 2000)
    if not t:
        raise AppError("Scrivere la nota.", field="text")
    _note(conn, job_id, "nota", t)
    conn.execute("UPDATE maintenance_jobs SET updated_at=? WHERE id=?", (now_iso(), job_id))
    audit(conn, "manutenzione_nota", "maintenance_job", job_id)
    return get(conn, job_id)


def _attachments_of(conn, table: str, ref_id: int) -> list[dict]:
    return rows(conn.execute("SELECT id, filename, mime, size, created_at FROM attachments WHERE ref_table=? AND "
                             "ref_id=? ORDER BY id", (table, ref_id)))


def _remove_file(conn, table: str, ref_id: int, att_id: int) -> dict:
    """Eliminato dal disco e dall'archivio. Il registro delle eliminazioni impedisce che un ripristino da un backup
    precedente lo faccia ricomparire."""
    from .. import config
    from .retention import ledger_add
    a = row(conn.execute("SELECT * FROM attachments WHERE id=? AND ref_table=? AND ref_id=?", (att_id, table, ref_id)))
    if not a:
        raise AppError("Allegato inesistente per questa scheda.", 404)
    conn.execute("DELETE FROM attachments WHERE id=?", (att_id,))
    audit(conn, "allegato_rimosso", "attachment", att_id, "manutenzione")
    ledger_add("attachment", a["stored_name"])
    (config.data_dir() / "allegati" / a["stored_name"]).unlink(missing_ok=True)
    return a


def add_attachment(conn: sqlite3.Connection, job_id: int, filename: str, data: bytes) -> dict:
    _job(conn, job_id)
    aid = attachments.save(conn, "manutenzione", "maintenance_jobs", job_id, filename, data, None)
    _note(conn, job_id, "allegato", f"Allegato: {(filename or 'allegato')[:120]}")
    conn.execute("UPDATE maintenance_jobs SET updated_at=? WHERE id=?", (now_iso(), job_id))
    return {"attachment_id": aid, "job": get(conn, job_id)}


def remove_attachment(conn: sqlite3.Connection, job_id: int, att_id: int) -> dict:
    """Foto o PDF caricato per errore, con traccia nel diario."""
    _job(conn, job_id)
    a = _remove_file(conn, "maintenance_jobs", job_id, att_id)
    _note(conn, job_id, "allegato", f"Allegato rimosso: {a['filename']}")
    conn.execute("UPDATE maintenance_jobs SET updated_at=? WHERE id=?", (now_iso(), job_id))
    return get(conn, job_id)


def _brief(conn, job_id: int | None) -> dict | None:
    if not job_id:
        return None
    return row(conn.execute("SELECT id, title, status, due_date, resolved_at FROM maintenance_jobs WHERE id=?",
                            (job_id,)))


def get(conn: sqlite3.Connection, job_id: int) -> dict:
    j = _decorate(_job(conn, job_id), now_iso()[:10])
    j["notes"] = rows(conn.execute("SELECT * FROM maintenance_notes WHERE job_id=? ORDER BY id DESC", (job_id,)))
    j["attachments"] = _attachments_of(conn, "maintenance_jobs", job_id)
    j["next_statuses"] = [{"status": s, "label": "Riapri" if s == "da_fare" else STATUSES[s]}
                          for s in ("in_corso", "risolto", "annullato", "da_fare") if s in TRANSITIONS[j["status"]]]
    j["asset"] = row(conn.execute("SELECT id, name, category FROM maintenance_assets WHERE id=?", (j["asset_id"],))) \
        if j["asset_id"] else None
    j["contractor_info"] = row(conn.execute("SELECT id, name, specialty, phone, email FROM maintenance_contractors "
                                            "WHERE id=?", (j["contractor_id"],))) if j["contractor_id"] else None
    j["prev_job"], j["next_job"] = _brief(conn, j["prev_job_id"]), _brief(conn, j["next_job_id"])
    for x in (j["prev_job"], j["next_job"]):
        if x:
            x["status_label"] = STATUSES[x["status"]]
    return j


_LIST_SQL = ("SELECT j.*, a.name asset_name, (SELECT COUNT(*) FROM attachments t WHERE t.ref_table='maintenance_jobs' "
             "AND t.ref_id=j.id) n_attachments FROM maintenance_jobs j LEFT JOIN maintenance_assets a ON a.id=j.asset_id")
_ORDER = ("CASE WHEN j.status IN ('da_fare','in_corso') THEN 0 ELSE 1 END, "
          "CASE j.priority WHEN 'urgente' THEN 0 WHEN 'normale' THEN 1 ELSE 2 END, "
          "COALESCE(j.due_date, '9999-12-31'), COALESCE(j.resolved_at, ''), j.id")


def list_jobs(conn: sqlite3.Connection, which: str = "aperti") -> dict:
    today = now_iso()[:10]
    where = {"aperti": "j.status IN ('da_fare','in_corso')", "chiusi": "j.status IN ('risolto','annullato')",
             "periodici": "j.recur_months IS NOT NULL AND j.status IN ('da_fare','in_corso')", "tutti": "1=1"}.get(which)
    if where is None:
        raise AppError("Filtro non valido.")
    jobs = [_decorate(j, today) for j in rows(conn.execute(f"{_LIST_SQL} WHERE {where} ORDER BY {_ORDER}"))]
    counts = {s: 0 for s in STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) FROM maintenance_jobs GROUP BY status"):
        counts[r[0]] = r[1]
    year = today[:4]
    spent = conn.execute("SELECT COALESCE(SUM(cost_cents),0) FROM maintenance_jobs WHERE status='risolto' "
                         "AND substr(resolved_at,1,4)=?", (year,)).fetchone()[0]
    return {"jobs": jobs, "counts": counts, "year": year, "spent_year_cents": spent,
            "priorities": PRIORITIES, "statuses": STATUSES}


def _jobs_where(conn, where: str, args: tuple) -> list[dict]:
    today = now_iso()[:10]
    return [_decorate(j, today) for j in rows(conn.execute(f"{_LIST_SQL} WHERE {where} ORDER BY {_ORDER}", args))]


def _job_stats(conn, col: str, ref_id: int) -> dict:
    r = conn.execute(f"SELECT COUNT(*), SUM(status IN ('da_fare','in_corso')), "
                     f"COALESCE(SUM(CASE WHEN status='risolto' THEN cost_cents END),0), MAX(resolved_at) "
                     f"FROM maintenance_jobs WHERE {col}=?", (ref_id,)).fetchone()
    nxt = conn.execute(f"SELECT MIN(due_date) FROM maintenance_jobs WHERE {col}=? AND status IN ('da_fare','in_corso')",
                       (ref_id,)).fetchone()[0]
    return {"n_jobs": r[0], "open_jobs": r[1] or 0, "spent_cents": r[2], "last_resolved_at": r[3], "next_due": nxt}


# ------------------------------------------------------------------ rubrica delle ditte
def _contractor(conn, cid: int) -> dict:
    c = row(conn.execute("SELECT * FROM maintenance_contractors WHERE id=?", (cid,)))
    if not c:
        raise AppError("Ditta inesistente.", 404)
    return c


def _contractor_name(conn, cid: int | None) -> str | None:
    return _contractor(conn, cid)["name"] if cid else None


def _contractor_by_name(conn, name: str) -> int:
    r = conn.execute("SELECT id FROM maintenance_contractors WHERE lower(name)=lower(?) ORDER BY active DESC, id",
                     (name.strip(),)).fetchone()
    if r:
        return r[0]
    ts = now_iso()
    cid = conn.execute("INSERT INTO maintenance_contractors(name, created_at, updated_at) VALUES (?,?,?)",
                       (name.strip(), ts, ts)).lastrowid
    audit(conn, "ditta_aggiunta", "maintenance_contractor", cid)
    return cid


def contractor_save(conn: sqlite3.Connection, data: dict, cid: int | None = None) -> dict:
    cur = _contractor(conn, cid) if cid else {}
    if cid:
        _check_version(cur, data.get("version"), "Ditta modificata")
    v = {k: cur.get(k) for k in CONTRACTOR_FIELDS}
    for k in CONTRACTOR_FIELDS:
        if k in data:
            v[k] = (1 if data[k] in (True, 1, "1", "true", "on") else 0) if k == "active" else \
                _text(data[k], k, 2000 if k == "notes" else 120)
    if v["active"] is None:
        v["active"] = 1
    if not v["name"]:
        raise AppError("Indicare il nome della ditta o del tecnico.", field="name")
    if v["email"] and "@" not in v["email"]:
        raise AppError("Indirizzo e-mail non valido.", field="email")
    dup = conn.execute("SELECT id FROM maintenance_contractors WHERE lower(name)=lower(?) AND id IS NOT ?",
                       (v["name"], cid)).fetchone()
    if dup:
        raise AppError("Questa ditta è già nella rubrica.", field="name")
    ts = now_iso()
    if cid:
        changed = [k for k in CONTRACTOR_FIELDS if v[k] != cur[k]]
        if changed:
            conn.execute(f"UPDATE maintenance_contractors SET {', '.join(f'{k}=?' for k in changed)}, "
                         f"version=version+1, updated_at=? WHERE id=?", (*[v[k] for k in changed], ts, cid))
            if "name" in changed:  # il nome mostrato nei lavori segue la rubrica
                conn.execute("UPDATE maintenance_jobs SET contractor=? WHERE contractor_id=?", (v["name"], cid))
            audit(conn, "ditta_modificata", "maintenance_contractor", cid, ",".join(changed))
    else:
        cid = conn.execute(f"INSERT INTO maintenance_contractors({','.join(v)}, created_at, updated_at) "
                           f"VALUES ({','.join('?' * len(v))}, ?, ?)", (*v.values(), ts, ts)).lastrowid
        audit(conn, "ditta_aggiunta", "maintenance_contractor", cid)
    return contractor_get(conn, cid)


def contractor_get(conn: sqlite3.Connection, cid: int) -> dict:
    c = _contractor(conn, cid)
    c.update(_job_stats(conn, "contractor_id", cid))
    c["jobs"] = _jobs_where(conn, "j.contractor_id=?", (cid,))
    return c


def contractor_list(conn: sqlite3.Connection) -> dict:
    out = []
    for c in rows(conn.execute("SELECT * FROM maintenance_contractors ORDER BY active DESC, lower(name)")):
        c.update(_job_stats(conn, "contractor_id", c["id"]))
        out.append(c)
    return {"contractors": out, "specialties": SPECIALTIES}


# ------------------------------------------------------------------ apparecchi della casa
def _asset(conn, aid: int) -> dict:
    a = row(conn.execute("SELECT * FROM maintenance_assets WHERE id=?", (aid,)))
    if not a:
        raise AppError("Apparecchio inesistente.", 404)
    return a


def _warranty(a: dict, today: str) -> dict:
    a = dict(a)
    w = a["warranty_until"]
    a["warranty_status"] = None if not w else "scaduta" if w < today else \
        "in_scadenza" if w <= add_days(today, WARRANTY_SOON_DAYS) else "valida"
    return a


def asset_save(conn: sqlite3.Connection, data: dict, aid: int | None = None) -> dict:
    cur = _asset(conn, aid) if aid else {}
    if aid:
        _check_version(cur, data.get("version"), "Apparecchio modificato")
    v = {k: cur.get(k) for k in ASSET_FIELDS}
    for k in ASSET_FIELDS:
        if k not in data:
            continue
        x = data[k]
        if k == "active":
            v[k] = 1 if x in (True, 1, "1", "true", "on") else 0
        elif k in ("purchased_on", "warranty_until"):
            v[k] = d(x, ASSET_FIELDS[k]).isoformat() if x else None
        else:
            v[k] = _text(x, k, 2000 if k == "notes" else 120)
    if v["active"] is None:
        v["active"] = 1
    if not v["name"]:
        raise AppError("Indicare il nome dell'apparecchio (es. Condizionatore camera).", field="name")
    if v["purchased_on"] and v["warranty_until"] and v["warranty_until"] < v["purchased_on"]:
        raise AppError("La garanzia non può finire prima dell'acquisto.", field="warranty_until")
    ts = now_iso()
    if aid:
        changed = [k for k in ASSET_FIELDS if v[k] != cur[k]]
        if changed:
            conn.execute(f"UPDATE maintenance_assets SET {', '.join(f'{k}=?' for k in changed)}, "
                         f"version=version+1, updated_at=? WHERE id=?", (*[v[k] for k in changed], ts, aid))
            audit(conn, "apparecchio_modificato", "maintenance_asset", aid, ",".join(changed))
    else:
        aid = conn.execute(f"INSERT INTO maintenance_assets({','.join(v)}, created_at, updated_at) "
                           f"VALUES ({','.join('?' * len(v))}, ?, ?)", (*v.values(), ts, ts)).lastrowid
        audit(conn, "apparecchio_aggiunto", "maintenance_asset", aid)
    return asset_get(conn, aid)


def asset_get(conn: sqlite3.Connection, aid: int) -> dict:
    a = _warranty(_asset(conn, aid), now_iso()[:10])
    a.update(_job_stats(conn, "asset_id", aid))
    a["jobs"] = _jobs_where(conn, "j.asset_id=?", (aid,))
    a["attachments"] = _attachments_of(conn, "maintenance_assets", aid)
    return a


def asset_list(conn: sqlite3.Connection) -> dict:
    today = now_iso()[:10]
    out = []
    for a in rows(conn.execute("SELECT * FROM maintenance_assets ORDER BY active DESC, lower(name)")):
        a = _warranty(a, today)
        a.update(_job_stats(conn, "asset_id", a["id"]))
        a["n_attachments"] = conn.execute("SELECT COUNT(*) FROM attachments WHERE ref_table='maintenance_assets' "
                                          "AND ref_id=?", (a["id"],)).fetchone()[0]
        out.append(a)
    return {"assets": out, "categories": CATEGORIES}


def asset_add_attachment(conn: sqlite3.Connection, aid: int, filename: str, data: bytes) -> dict:
    _asset(conn, aid)
    attachments.save(conn, "manutenzione", "maintenance_assets", aid, filename, data, None)
    conn.execute("UPDATE maintenance_assets SET updated_at=? WHERE id=?", (now_iso(), aid))
    return asset_get(conn, aid)


def asset_remove_attachment(conn: sqlite3.Connection, aid: int, att_id: int) -> dict:
    _asset(conn, aid)
    _remove_file(conn, "maintenance_assets", aid, att_id)
    return asset_get(conn, aid)


def options(conn: sqlite3.Connection) -> dict:
    """Elenchi per i moduli dei lavori: apparecchi e ditte in uso, ripetizioni."""
    return {"assets": rows(conn.execute("SELECT id, name, category FROM maintenance_assets WHERE active=1 "
                                        "ORDER BY lower(name)")),
            "contractors": rows(conn.execute("SELECT id, name, specialty, phone FROM maintenance_contractors "
                                             "WHERE active=1 ORDER BY lower(name)")),
            "recur": RECUR_CHOICES, "categories": CATEGORIES, "specialties": SPECIALTIES}


# ------------------------------------------------------------------ promemoria in «Oggi»
def today_items(conn: sqlite3.Connection, today: str) -> list[dict]:
    """Per «Oggi»: lavori aperti urgenti, scaduti o in scadenza entro SOON_DAYS giorni; garanzie in scadenza."""
    out = []
    for j in rows(conn.execute("SELECT * FROM maintenance_jobs WHERE status IN ('da_fare','in_corso')")):
        j = _decorate(j, today)
        if j["priority"] == "urgente" or j["overdue"] or j["due_soon"]:
            out.append({"id": j["id"], "title": j["title"], "status_label": j["status_label"],
                        "priority": j["priority"], "due_date": j["due_date"], "overdue": j["overdue"],
                        "link": f"#/manutenzione/{j['id']}"})
    out.sort(key=lambda x: (not x["overdue"], x["priority"] != "urgente", x["due_date"] or "9999"))
    for a in rows(conn.execute("SELECT id, name, warranty_until FROM maintenance_assets WHERE active=1 AND "
                               "warranty_until BETWEEN ? AND ? ORDER BY warranty_until",
                               (today, add_days(today, WARRANTY_SOON_DAYS)))):
        out.append({"id": a["id"], "kind": "garanzia", "title": f"Garanzia: {a['name']}",
                    "status_label": "Garanzia in scadenza", "priority": "normale", "due_date": a["warranty_until"],
                    "overdue": False, "link": f"#/manutenzione/apparecchi/{a['id']}"})
    return out
