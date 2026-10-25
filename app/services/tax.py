"""Imposta di soggiorno: regole versionate e calcolo per ospite e per notte.

Principi (vedi docs/FONTI_NORMATIVE.md):
- la regola si sceglie per la DATA DELLA NOTTE, comune e categoria configurati;
- notte senza regola -> "da_verificare" (mai zero, mai una tariffa vecchia);
- regola con stato 'da_verificare' -> importo calcolato ma provvisorio, non consolidabile;
- limite notti consecutive: conteggio di TUTTI i pernottamenti consecutivi dell'ospite
  (es. Reg. di Alghero art. 3 c. 3 "eccedenti i primi sette pernottamenti consecutivi"),
  inclusa la continuazione in un soggiorno collegato; nessun azzeramento a cambio mese/anno;
- soglia "entro il dodicesimo anno di età": sotto i 12 anni esente in ogni lettura,
  dai 13 imponibile in ogni lettura; a 12 anni compiuti l'esito dipende dall'interpretazione
  registrata nella regola: se 'da_chiarire' la notte resta DA VERIFICARE.
- un solo motivo per notte, con priorità: non assoggettato > esente > oltre limite > da chiarire > imponibile.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..db import AppError, audit, now_iso, rows, get_setting
from ..util import age_on, d, eur, nights

# Esenzioni personali: modello del Regolamento di Alghero (art. 3 c. 1), comune a molti regolamenti.
# Ogni regola indica quali applicare; i riferimenti agli articoli vanno letti nel regolamento del proprio Comune.
EXEMPTIONS = {
    "residente": "Non assoggettato: iscritto all'anagrafe del Comune",
    "minore": "Esente: minore (soglia d'età indicata nella regola)",
    "assistenza_ricoverati": "Esente: assistenza a persona ricoverata nelle strutture sanitarie del Comune",
    "forze_servizio": "Esente: Polizia di Stato, Polizia Locale, Forze armate, Vigili del fuoco in servizio",
    "disabilita_grave": "Esente: persona con disabilità grave certificata",
    "accompagnatore": "Esente: accompagnatore di persona con disabilità grave",
}
# Esenzioni che richiedono documentazione/dichiarazione acquisita (art. 3 c. 4).
NEEDS_DOC = {"assistenza_ricoverati", "forze_servizio", "disabilita_grave", "accompagnatore"}
TAX_STATUSES = {"ordinario", "residente", "assistenza_ricoverati", "forze_servizio",
                "disabilita_grave", "accompagnatore"}

CLASS_LABEL = {
    "imponibile": "imponibile",
    "non_assoggettata": "non assoggettata",
    "esente": "esente",
    "oltre_limite": "oltre il limite di notti consecutive",
    "da_chiarire": "DA VERIFICARE (soglia d'età)",
    "senza_regola": "DA VERIFICARE (nessuna regola per la data)",
}


@dataclass
class NightLine:
    night: str
    cls: str
    reason: str | None
    rule_id: int | None
    rule_status: str | None
    rate_cents: int | None
    amount_cents: int | None
    consecutive_index: int


@dataclass
class GuestTax:
    guest_id: int
    label: str
    basis: str                   # 'effettiva' | 'prevista' | 'nessuna'
    start: str | None
    end: str | None
    lines: list[NightLine] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        c: dict[str, int] = {}
        for ln in self.lines:
            c[ln.cls] = c.get(ln.cls, 0) + 1
        return c

    @property
    def amount_cents(self) -> int | None:
        if any(ln.amount_cents is None for ln in self.lines):
            return None
        return sum(ln.amount_cents or 0 for ln in self.lines)


def load_rules(conn: sqlite3.Connection, comune: str, category: str) -> list[dict]:
    return rows(conn.execute(
        "SELECT * FROM tax_rules WHERE comune=? AND category=? AND status!='revocata' ORDER BY valid_from",
        (comune, category)))


def rule_for(rules: list[dict], night: date) -> dict | None:
    s = night.isoformat()
    match = [r for r in rules if r["valid_from"] <= s <= r["valid_to"]]
    if len(match) > 1:
        # versioni sovrapposte: vince la più recente approvata, altrimenti nessuna scelta automatica
        appr = [r for r in match if r["status"] == "approvata"]
        if len(appr) == 1:
            return appr[0]
        return None
    return match[0] if match else None


def _guest_interval(g: dict, booking: dict) -> tuple[str, str | None, str | None]:
    """Permanenza su cui calcolare: effettiva se registrata, altrimenti prevista."""
    if g["presence"] == "non_arrivata":
        return "nessuna", None, None
    if g["stay_arrival"]:
        end = g["stay_departure"] or g["planned_departure"] or booking["departure"]
        return "effettiva", g["stay_arrival"], end
    return "prevista", g["planned_arrival"] or booking["arrival"], g["planned_departure"] or booking["departure"]


def _prior_consecutive(conn: sqlite3.Connection, g: dict, start: str, depth: int = 0) -> int:
    """Notti consecutive già trascorse dallo stesso ospite nel soggiorno collegato precedente."""
    if not g.get("continues_guest_id") or depth > 20:
        return 0
    p = conn.execute("SELECT g.*, b.arrival, b.departure FROM guests g JOIN bookings b ON b.id=g.booking_id "
                     "WHERE g.id=?", (g["continues_guest_id"],)).fetchone()
    if not p:
        return 0
    p = dict(p)
    basis, ps, pe = _guest_interval(p, p)
    if not ps or pe != start:
        return 0  # non contiguo: nessuna continuità
    return len(nights(ps, pe)) + _prior_consecutive(conn, p, ps, depth + 1)


def compute_guest(conn: sqlite3.Connection, g: dict, booking: dict, rules: list[dict],
                  all_guests: dict[int, dict]) -> GuestTax:
    basis, start, end = _guest_interval(g, booking)
    gt = GuestTax(g["id"], f"{g['surname']} {g['name']}".strip(), basis, start, end)
    if basis == "nessuna" or not start or not end:
        return gt
    status = g["tax_status"] or "ordinario"
    if status not in TAX_STATUSES:
        gt.issues.append(f"Stato fiscale sconosciuto: {status}")
    if status in NEEDS_DOC and not g["exemption_doc_ok"]:
        gt.issues.append("Esenzione indicata ma documentazione/dichiarazione non ancora acquisita.")
    if status == "accompagnatore":
        tgt = all_guests.get(g.get("exemption_for_guest") or -1)
        if not tgt or tgt["tax_status"] != "disabilita_grave":
            gt.issues.append("Accompagnatore: indicare la persona con disabilità grave accompagnata.")
        else:
            others = [x for x in all_guests.values() if x["id"] != g["id"]
                      and x["tax_status"] == "accompagnatore" and x.get("exemption_for_guest") == tgt["id"]]
            if others:
                gt.issues.append("Il regolamento prevede un solo accompagnatore per persona con disabilità.")
    birth = d(g["birth_date"]) if g["birth_date"] else None
    prior = _prior_consecutive(conn, g, start)
    for i, n in enumerate(nights(start, end)):
        idx = prior + i + 1
        rule = rule_for(rules, n)
        ln = NightLine(n.isoformat(), "imponibile", None, rule["id"] if rule else None,
                       rule["status"] if rule else None, rule["rate_cents"] if rule else None, None, idx)
        allowed = set(json.loads(rule["exemptions"])) if rule else set()
        if status == "residente":
            ln.cls, ln.reason, ln.amount_cents = "non_assoggettata", EXEMPTIONS["residente"], 0
        elif status in EXEMPTIONS and status != "residente" and status in allowed:
            ln.cls, ln.reason, ln.amount_cents = "esente", EXEMPTIONS[status], 0
        elif rule is None:
            ln.cls, ln.reason = "senza_regola", "Nessuna regola verificata per questa data"
        else:
            minor_cls = None
            if birth is None:
                minor_cls = "da_chiarire_nascita"
            elif "minore" in allowed:
                age = age_on(birth, n)
                if age < 12:
                    minor_cls = "esente"
                elif age == 12:
                    mr = rule["minor_rule"]
                    minor_cls = "esente" if mr == "fino_a_12_compresi" else (
                        None if mr == "meno_di_12" else "da_chiarire")
            if minor_cls == "esente":
                ln.cls, ln.reason, ln.amount_cents = "esente", EXEMPTIONS["minore"], 0
            elif rule["max_nights"] and idx > rule["max_nights"]:
                ln.cls, ln.reason, ln.amount_cents = "oltre_limite", \
                    f"Oltre i primi {rule['max_nights']} pernottamenti consecutivi (art. 3 c. 3)", 0
            elif minor_cls == "da_chiarire":
                ln.cls, ln.reason = "da_chiarire", ("Ospite con 12 anni compiuti: soglia «entro il dodicesimo "
                                                    "anno di età» da chiarire con SECAL")
            elif minor_cls == "da_chiarire_nascita":
                ln.cls, ln.reason = "da_chiarire", "Data di nascita mancante: impossibile valutare l'esenzione minori"
            else:
                ln.cls, ln.amount_cents = "imponibile", rule["rate_cents"]
        gt.lines.append(ln)
    return gt


def compute_booking(conn: sqlite3.Connection, booking_id: int) -> dict:
    b = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not b:
        raise AppError("Prenotazione inesistente", 404)
    b = dict(b)
    st = get_setting(conn, "structure", {}) or {}
    comune, category = st.get("tax_comune") or "", st.get("tax_category")
    guests = rows(conn.execute("SELECT * FROM guests WHERE booking_id=? AND anonymized_at IS NULL "
                               "ORDER BY position, id", (booking_id,)))
    gmap = {g["id"]: g for g in guests}
    result = {"booking_id": booking_id, "category": category, "guests": [], "issues": [],
              "kind": "preventivo", "total_cents": None, "final": False}
    if b["status"] in ("annullata", "no_show", "opzione_scaduta"):
        result["issues"].append("Prenotazione non soggiornata: nessuna imposta dovuta da questo calcolo.")
        result["total_cents"] = 0
        return result
    if not st.get("category_confirmed") or not category:
        result["issues"].append("Categoria della struttura non confermata nelle Impostazioni: calcolo non disponibile.")
        return result
    if not guests:
        result["issues"].append("Nessun ospite inserito: impossibile calcolare l'imposta.")
        return result
    rules = load_rules(conn, comune, category)
    totals: dict[str, int] = {}
    total, unknown, provisional, effective = 0, False, False, True
    for g in guests:
        gt = compute_guest(conn, g, b, rules, gmap)
        if gt.basis == "prevista":
            effective = False
        amt = gt.amount_cents
        if amt is None:
            unknown = True
        else:
            total += amt
        if any(ln.rule_status == "da_verificare" for ln in gt.lines):
            provisional = True
        for k, v in gt.counts().items():
            totals[k] = totals.get(k, 0) + v
        result["guests"].append({
            "guest_id": gt.guest_id, "label": gt.label, "basis": gt.basis, "start": gt.start, "end": gt.end,
            "counts": gt.counts(), "amount_cents": amt, "issues": gt.issues,
            "explanation": explain(gt), "lines": [ln.__dict__ for ln in gt.lines]})
        result["issues"] += [f"{gt.label}: {i}" for i in gt.issues]
    if provisional:
        result["issues"].append("Una o più notti usano una regola con stato «da verificare»: importo provvisorio.")
    result["counts"] = totals
    result["kind"] = "consuntivo" if effective and all(
        g["presence"] in ("presente", "partita", "non_arrivata") for g in guests) else "preventivo"
    result["total_cents"] = None if unknown else total
    result["final"] = (not unknown and not provisional and not result["issues"]
                       and result["kind"] == "consuntivo")
    result["rule_ids"] = sorted({ln["rule_id"] for g in result["guests"] for ln in g["lines"] if ln["rule_id"]})
    return result


def explain(gt: GuestTax) -> str:
    if gt.basis == "nessuna":
        return "Ospite non arrivato: nessuna notte."
    c = gt.counts()
    parts = []
    rates = sorted({ln.rate_cents for ln in gt.lines if ln.cls == "imponibile" and ln.rate_cents})
    if c.get("imponibile"):
        parts.append(f"{c['imponibile']} notti imponibili × " + " / ".join(eur(r) for r in rates))
    for k in ("non_assoggettata", "esente", "oltre_limite", "da_chiarire", "senza_regola"):
        if c.get(k):
            parts.append(f"{c[k]} notti {CLASS_LABEL[k]}")
    base = "permanenza effettiva" if gt.basis == "effettiva" else "permanenza PREVISTA (stima)"
    tot = eur(gt.amount_cents)
    return f"{'; '.join(parts) or 'nessuna notte'} — {base}; totale {tot}"


def consolidated(conn: sqlite3.Connection, booking_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM tax_assessments WHERE booking_id=? AND status='consolidato' "
                     "ORDER BY id DESC LIMIT 1", (booking_id,)).fetchone()
    return dict(r) if r else None


def consolidate(conn: sqlite3.Connection, booking_id: int, reason: str | None = None) -> dict:
    """Congela il conteggio (regole bloccate). Una nuova consolidazione è una rettifica tracciata."""
    calc = compute_booking(conn, booking_id)
    if not calc["final"]:
        raise AppError("Il calcolo non è definitivo: " + ("; ".join(calc["issues"]) or
                       "servono permanenze effettive per tutti gli ospiti."), extra=calc)
    prev = consolidated(conn, booking_id)
    detail = json.dumps(calc, ensure_ascii=False)
    if prev:
        if prev["detail"] == detail:
            return prev
        if not reason:
            raise AppError("Esiste già un conteggio consolidato: indicare la motivazione della rettifica.")
        conn.execute("UPDATE tax_assessments SET status='superato' WHERE id=?", (prev["id"],))
    cur = conn.execute(
        "INSERT INTO tax_assessments(booking_id,status,total_cents,detail,rule_ids,reason,supersedes_id,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (booking_id, "consolidato", calc["total_cents"], detail, json.dumps(calc["rule_ids"]),
         reason, prev["id"] if prev else None, now_iso()))
    if calc["rule_ids"]:
        conn.execute(f"UPDATE tax_rules SET locked=1 WHERE id IN ({','.join('?' * len(calc['rule_ids']))})",
                     calc["rule_ids"])
    audit(conn, "imposta_consolidata" if not prev else "imposta_rettificata", "booking", booking_id,
          f"totale={calc['total_cents']}")
    return dict(conn.execute("SELECT * FROM tax_assessments WHERE id=?", (cur.lastrowid,)).fetchone())


def due_for_booking(conn: sqlite3.Connection, booking_id: int) -> dict:
    """Imposta dovuta: consolidata se presente, altrimenti calcolo corrente (con il suo stato)."""
    cons = consolidated(conn, booking_id)
    calc = compute_booking(conn, booking_id)
    out = {"calc": calc, "consolidated": None, "due_cents": calc["total_cents"], "source": calc["kind"],
           "differs": False}
    if cons:
        out["consolidated"] = {"id": cons["id"], "total_cents": cons["total_cents"], "created_at": cons["created_at"]}
        out["due_cents"], out["source"] = cons["total_cents"], "consolidato"
        out["differs"] = calc["total_cents"] != cons["total_cents"]
    return out


# ---------- gestione regole ----------
def seed_rules(conn: sqlite3.Connection, seed: list[dict]) -> None:
    if conn.execute("SELECT COUNT(*) FROM tax_rules").fetchone()[0]:
        return
    for r in seed:
        status = r.get("status", "da_verificare")  # «approvata» solo se confermata dal gestore sulle fonti
        conn.execute(
            "INSERT INTO tax_rules(comune,category,valid_from,valid_to,rate_cents,max_nights,minor_rule,exemptions,"
            "seasonality,source,verified_on,status,notes,created_at,approved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["comune"], r["category"], r["valid_from"], r["valid_to"], r["rate_cents"], r.get("max_nights"),
             r["minor_rule"], json.dumps(r["exemptions"]), json.dumps(r.get("seasonality", [])), r["source"],
             r["verified_on"], status, r.get("notes"), now_iso(), now_iso() if status == "approvata" else None))


def approve_rule(conn: sqlite3.Connection, rule_id: int, minor_rule: str | None = None) -> None:
    r = conn.execute("SELECT * FROM tax_rules WHERE id=?", (rule_id,)).fetchone()
    if not r:
        raise AppError("Regola inesistente", 404)
    if r["locked"]:
        raise AppError("Regola già usata in conteggi consolidati: crea una nuova versione invece di modificarla.")
    if minor_rule:
        if minor_rule not in ("da_chiarire", "meno_di_12", "fino_a_12_compresi"):
            raise AppError("Interpretazione soglia d'età non valida")
        conn.execute("UPDATE tax_rules SET minor_rule=? WHERE id=?", (minor_rule, rule_id))
    conn.execute("UPDATE tax_rules SET status='approvata', approved_at=? WHERE id=?", (now_iso(), rule_id))
    audit(conn, "regola_approvata", "tax_rule", rule_id, minor_rule)


def add_rule(conn: sqlite3.Connection, data: dict) -> int:
    from ..util import parse_cents
    req = ("comune", "category", "valid_from", "valid_to", "source", "verified_on")
    for k in req:
        if not data.get(k):
            raise AppError(f"Campo obbligatorio mancante: {k}", field=k)
    vf, vt = d(data["valid_from"]).isoformat(), d(data["valid_to"]).isoformat()
    if vt < vf:
        raise AppError("La data di fine validità precede l'inizio.")
    ex = data.get("exemptions") or []
    if any(e not in EXEMPTIONS for e in ex):
        raise AppError("Esenzione non prevista dall'elenco del regolamento.")
    overl = conn.execute("SELECT id FROM tax_rules WHERE comune=? AND category=? AND status!='revocata' "
                         "AND valid_from<=? AND valid_to>=?", (data["comune"], data["category"], vt, vf)).fetchall()
    if overl:
        raise AppError("Esiste già una versione valida nello stesso periodo: revocala prima di inserirne un'altra.")
    cur = conn.execute(
        "INSERT INTO tax_rules(comune,category,valid_from,valid_to,rate_cents,max_nights,minor_rule,exemptions,"
        "seasonality,source,verified_on,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["comune"], data["category"], vf, vt, parse_cents(data.get("rate")), data.get("max_nights") or None,
         data.get("minor_rule") or "da_chiarire", json.dumps(ex), "[]", data["source"],
         d(data["verified_on"]).isoformat(), "da_verificare", data.get("notes"), now_iso()))
    audit(conn, "regola_creata", "tax_rule", cur.lastrowid)
    return cur.lastrowid


def revoke_rule(conn: sqlite3.Connection, rule_id: int, reason: str) -> None:
    if not reason:
        raise AppError("Indicare la motivazione della revoca.")
    conn.execute("UPDATE tax_rules SET status='revocata', notes=COALESCE(notes,'')||? WHERE id=?",
                 (f"\nRevocata il {now_iso()[:10]}: {reason}", rule_id))
    audit(conn, "regola_revocata", "tax_rule", rule_id)
