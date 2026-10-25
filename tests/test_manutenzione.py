"""Manutenzione: lavori, stati, diario, costi, foto, promemoria in «Oggi», migrazione dello schema. Dati sintetici."""
import re
import sqlite3
import struct
import zlib

import pytest

from app import config, db, main
from app.db import AppError, now_iso
from app.services import maintenance as M
from app.util import add_days

TODAY = now_iso()[:10]


def _png() -> bytes:
    raw = b"\x00\xff\x00\x00"  # 1 pixel rosso
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_create_validate_and_order(conn):
    with pytest.raises(AppError) as ex:
        M.create(conn, {"title": "  "})
    assert ex.value.field == "title"
    with pytest.raises(AppError):
        M.create(conn, {"title": "Prova", "priority": "altissima"})
    with pytest.raises(AppError):
        M.create(conn, {"title": "Prova", "quote_cents": "-5"})
    a = M.create(conn, {"title": "Imbiancare la camera", "priority": "bassa"})
    b = M.create(conn, {"title": "Perdita sotto il lavello", "priority": "urgente", "quote_cents": "120,50",
                        "contractor": "Idraulica Prova", "due_date": add_days(TODAY, 2)})
    assert b["quote_cents"] == 12050 and b["status"] == "da_fare" and b["due_soon"]
    assert [n["text"] for n in b["notes"]] == ["Lavoro aperto: Da fare"]
    assert [j["id"] for j in M.list_jobs(conn)["jobs"]] == [b["id"], a["id"]]   # urgente prima


def test_progress_until_resolved_with_diary_and_cost(conn):
    j = M.create(conn, {"title": "Condizionatore non raffredda"})
    j = M.set_status(conn, j["id"], {"status": "in_corso", "note": "Chiamato il tecnico", "version": j["version"]})
    j = M.add_note(conn, j["id"], "Il tecnico viene martedì")
    with pytest.raises(AppError):
        M.add_note(conn, j["id"], " ")
    j = M.update(conn, j["id"], {"contractor": "Clima Prova", "version": j["version"]})
    with pytest.raises(AppError) as ex:                                     # versione superata: altra finestra
        M.update(conn, j["id"], {"contractor": "Altro", "version": j["version"] - 1})
    assert ex.value.status == 409
    j = M.set_status(conn, j["id"], {"status": "risolto", "note": "Ricaricato il gas", "cost": "180,00",
                                     "version": j["version"]})
    assert j["status"] == "risolto" and j["cost_cents"] == 18000 and j["resolved_at"]
    assert [n["kind"] for n in j["notes"]] == ["stato", "modifica", "nota", "stato", "stato"]
    assert j["notes"][0]["text"] == "In corso → Risolto: Ricaricato il gas"
    assert [s["status"] for s in j["next_statuses"]] == ["da_fare"]              # solo riapertura
    assert M.list_jobs(conn, "chiusi")["spent_year_cents"] == 18000
    assert not M.list_jobs(conn, "aperti")["jobs"]


def test_transitions_and_mandatory_reasons(conn):
    j = M.create(conn, {"title": "Tapparella bloccata"})
    with pytest.raises(AppError):
        M.set_status(conn, j["id"], {"status": "annullato"})              # motivo obbligatorio
    j = M.set_status(conn, j["id"], {"status": "annullato", "note": "Sistemata da sola"})
    with pytest.raises(AppError):
        M.set_status(conn, j["id"], {"status": "in_corso"})               # da annullato solo riapertura
    with pytest.raises(AppError):
        M.set_status(conn, j["id"], {"status": "da_fare"})                # riapertura senza motivo
    j = M.set_status(conn, j["id"], {"status": "da_fare", "note": "Si è bloccata di nuovo"})
    assert j["status"] == "da_fare" and j["resolved_at"] is None
    assert j["notes"][0]["text"].startswith("Annullato → Riaperto")


def test_cancelled_costs_not_counted(conn):
    j = M.create(conn, {"title": "Sostituire il box doccia", "quote_cents": "900"})
    M.update(conn, j["id"], {"cost_cents": "50", "version": j["version"]})
    M.set_status(conn, j["id"], {"status": "annullato", "note": "Rinviato all'anno prossimo"})
    assert M.list_jobs(conn, "tutti")["spent_year_cents"] == 0


def test_photo_attachment_encrypted(conn):
    j = M.create(conn, {"title": "Crepa nel muro del terrazzo"})
    r = M.add_attachment(conn, j["id"], "crepa.png", _png())
    j = r["job"]
    assert [a["filename"] for a in j["attachments"]] == ["crepa.png"] and j["notes"][0]["kind"] == "allegato"
    stored = conn.execute("SELECT stored_name, delete_after FROM attachments WHERE id=?",
                          (r["attachment_id"],)).fetchone()
    assert stored["delete_after"] is None                                   # nessuna eliminazione automatica
    assert b"IHDR" not in (config.data_dir() / "allegati" / stored["stored_name"]).read_bytes()  # cifrato
    with pytest.raises(AppError):
        M.add_attachment(conn, j["id"], "nota.txt", b"testo semplice")


def test_remove_wrong_attachment(conn):
    from app.services import retention
    j = M.create(conn, {"title": "Macchia sul soffitto"})
    other = M.create(conn, {"title": "Altro lavoro"})
    aid = M.add_attachment(conn, j["id"], "sbagliata.png", _png())["attachment_id"]
    stored = conn.execute("SELECT stored_name FROM attachments WHERE id=?", (aid,)).fetchone()[0]
    with pytest.raises(AppError) as ex:                                     # allegato di un altro lavoro
        M.remove_attachment(conn, other["id"], aid)
    assert ex.value.status == 404
    j = M.remove_attachment(conn, j["id"], aid)
    assert j["attachments"] == [] and j["notes"][0]["text"] == "Allegato rimosso: sbagliata.png"
    assert not (config.data_dir() / "allegati" / stored).exists()
    assert {"kind": "attachment", "id": stored} in [{k: x[k] for k in ("kind", "id")} for x in retention.ledger()]


def test_today_shows_urgent_overdue_and_soon_only(conn):
    from app import api
    urg = M.create(conn, {"title": "Urgente", "priority": "urgente"})
    late = M.create(conn, {"title": "Scaduto", "due_date": add_days(TODAY, -1)})
    soon = M.create(conn, {"title": "Tra tre giorni", "due_date": add_days(TODAY, 3)})
    M.create(conn, {"title": "Fra un mese", "due_date": add_days(TODAY, 30)})
    M.create(conn, {"title": "Senza scadenza"})
    done = M.create(conn, {"title": "Urgente ma risolto", "priority": "urgente"})
    M.set_status(conn, done["id"], {"status": "risolto"})
    items = api.today(None, conn)["maintenance"]
    assert [x["id"] for x in items] == [late["id"], urg["id"], soon["id"]]
    assert items[0]["overdue"] and items[0]["link"] == f"#/manutenzione/{late['id']}"


def _maintenance_sql(path) -> list[str]:
    c = sqlite3.connect(str(path))
    try:
        return [re.sub(r"\s+", " ", r[0]).strip() for r in c.execute(
            "SELECT sql FROM sqlite_master WHERE name LIKE '%maintenance%' ORDER BY name")]
    finally:
        c.close()


def test_periodic_job_spawns_next_once(conn):
    first_due = add_days(TODAY, 3)
    with pytest.raises(AppError) as ex:                                     # periodico senza prima scadenza
        M.create(conn, {"title": "Pulizia filtri condizionatore", "recur_months": "6"})
    assert ex.value.field == "due_date"
    with pytest.raises(AppError):
        M.create(conn, {"title": "Pulizia filtri", "recur_months": "200", "due_date": first_due})
    j = M.create(conn, {"title": "Pulizia filtri condizionatore", "recur_months": "6", "due_date": first_due,
                        "contractor": "Clima Prova", "quote_cents": "60"})
    assert j["recur_label"] == "Ogni 6 mesi"
    j = M.set_status(conn, j["id"], {"status": "risolto", "cost": "55,00", "version": j["version"]})
    nxt = j["next_job"]
    assert nxt and nxt["due_date"] == M.add_months(TODAY, 6) and nxt["status"] == "da_fare"
    n = M.get(conn, nxt["id"])
    assert n["prev_job_id"] == j["id"] and n["recur_months"] == 6 and n["cost_cents"] is None
    assert n["contractor_id"] == j["contractor_id"] and n["quote_cents"] == 6000
    assert j["notes"][0]["text"].startswith("Prossimo intervento programmato")
    # riaperto e risolto di nuovo: nessun secondo «prossimo»
    j = M.set_status(conn, j["id"], {"status": "da_fare", "note": "Filtro ancora sporco"})
    j = M.set_status(conn, j["id"], {"status": "risolto"})
    assert conn.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE prev_job_id=?", (j["id"],)).fetchone()[0] == 1
    assert [x["id"] for x in M.list_jobs(conn, "periodici")["jobs"]] == [nxt["id"]]
    # annullato: la serie si ferma
    n = M.set_status(conn, nxt["id"], {"status": "annullato", "note": "Condizionatore sostituito"})
    assert n["next_job"] is None


def test_add_months_end_of_month():
    assert M.add_months("2026-01-31", 1) == "2026-02-28"
    assert M.add_months("2026-08-31", 6) == "2027-02-28"
    assert M.add_months("2026-11-15", 12) == "2027-11-15"


def test_assets_warranty_jobs_and_documents(conn):
    from app import api
    with pytest.raises(AppError):
        M.asset_save(conn, {"name": " "})
    with pytest.raises(AppError):
        M.asset_save(conn, {"name": "Lavatrice", "purchased_on": TODAY, "warranty_until": add_days(TODAY, -1)})
    a = M.asset_save(conn, {"name": "Condizionatore camera", "category": "Climatizzatore", "brand": "Marca Prova",
                            "warranty_until": add_days(TODAY, 20)})
    old = M.asset_save(conn, {"name": "Frigorifero vecchio", "warranty_until": add_days(TODAY, -400)})
    assert a["warranty_status"] == "in_scadenza" and old["warranty_status"] == "scaduta"
    j = M.create(conn, {"title": "Non raffredda", "asset_id": a["id"]})
    M.set_status(conn, j["id"], {"status": "risolto", "cost": "120"})
    with pytest.raises(AppError):
        M.create(conn, {"title": "Apparecchio inesistente", "asset_id": 999})
    a = M.asset_get(conn, a["id"])
    assert a["n_jobs"] == 1 and a["spent_cents"] == 12000 and [x["id"] for x in a["jobs"]] == [j["id"]]
    assert M.get(conn, j["id"])["asset"]["name"] == "Condizionatore camera"
    a = M.asset_add_attachment(conn, a["id"], "manuale.png", _png())
    assert [x["filename"] for x in a["attachments"]] == ["manuale.png"]
    with pytest.raises(AppError) as ex:                                      # allegato di un altro apparecchio
        M.asset_remove_attachment(conn, old["id"], a["attachments"][0]["id"])
    assert ex.value.status == 404
    assert M.asset_remove_attachment(conn, a["id"], a["attachments"][0]["id"])["attachments"] == []
    with pytest.raises(AppError) as ex:                                      # versione superata
        M.asset_save(conn, {"name": "X", "version": a["version"] - 1}, a["id"])
    assert ex.value.status == 409
    items = api.today(None, conn)["maintenance"]
    assert [x["title"] for x in items if x.get("kind") == "garanzia"] == ["Garanzia: Condizionatore camera"]
    M.asset_save(conn, {"active": False, "version": a["version"]}, a["id"])  # dismesso: niente avviso
    assert not [x for x in api.today(None, conn)["maintenance"] if x.get("kind") == "garanzia"]
    assert [x["name"] for x in M.options(conn)["assets"]] == ["Frigorifero vecchio"]


def test_contractors_rubric(conn):
    j = M.create(conn, {"title": "Perdita", "contractor": "Idraulica Prova"})
    k = M.create(conn, {"title": "Scarico lento", "contractor": "  idraulica prova "})   # stesso nome: stessa ditta
    assert j["contractor_id"] == k["contractor_id"] and k["contractor"] == "Idraulica Prova"
    cid = j["contractor_id"]
    with pytest.raises(AppError):
        M.contractor_save(conn, {"name": "IDRAULICA PROVA"})                 # doppione nella rubrica
    with pytest.raises(AppError):
        M.contractor_save(conn, {"name": "Elettricista", "email": "senza-chiocciola"})
    e = M.contractor_save(conn, {"name": "Elettricista Prova", "specialty": "Elettricista", "phone": "000 111"})
    j = M.update(conn, j["id"], {"contractor_id": e["id"], "version": j["version"]})
    assert j["contractor"] == "Elettricista Prova" and j["contractor_info"]["phone"] == "000 111"
    c = M.contractor_get(conn, cid)
    c = M.contractor_save(conn, {"name": "Idraulica Prova srl", "version": c["version"]}, cid)
    assert M.get(conn, k["id"])["contractor"] == "Idraulica Prova srl"      # il nome nei lavori segue la rubrica
    M.set_status(conn, k["id"], {"status": "risolto", "cost": "80"})
    lst = {x["name"]: x for x in M.contractor_list(conn)["contractors"]}
    assert lst["Idraulica Prova srl"]["spent_cents"] == 8000 and lst["Elettricista Prova"]["open_jobs"] == 1
    M.contractor_save(conn, {"active": False, "version": c["version"]}, cid)
    assert [x["name"] for x in M.options(conn)["contractors"]] == ["Elettricista Prova"]
    j = M.update(conn, j["id"], {"contractor_id": "", "version": j["version"]})
    assert j["contractor"] is None and j["contractor_id"] is None


def test_v1_archive_migrated_to_maintenance_schema(conn, tmp_path):
    fresh = _maintenance_sql(config.db_path())
    assert len(fresh) == 7
    for t in ("maintenance_notes", "maintenance_jobs", "maintenance_assets", "maintenance_contractors"):
        conn.execute(f"DROP TABLE {t}")
    conn.execute("PRAGMA user_version = 1")
    conn.close()
    name = main.migrate_with_backup()
    assert name and name.startswith("pre_migrazione_v1_")
    assert _maintenance_sql(config.db_path()) == fresh                      # migrato = archivio nuovo
    c = sqlite3.connect(str(config.db_path()))
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 3
    c.close()


def test_v2_archive_contractors_moved_to_rubric(conn):
    fresh = _maintenance_sql(config.db_path())
    for t in ("maintenance_notes", "maintenance_jobs", "maintenance_assets", "maintenance_contractors"):
        conn.execute(f"DROP TABLE {t}")
    for stmt in [x for x in db.MAINTENANCE_SQL.split(";") if x.strip()]:
        conn.execute(stmt)
    ts = now_iso()
    for title, ditta in (("A", "Idraulica Prova "), ("B", "Idraulica Prova"), ("C", ""), ("D", None),
                         ("E", "Clima Prova")):
        conn.execute("INSERT INTO maintenance_jobs(title, contractor, created_at, updated_at) VALUES (?,?,?,?)",
                     (title, ditta, ts, ts))
    conn.execute("PRAGMA user_version = 2")
    conn.close()
    assert main.migrate_with_backup().startswith("pre_migrazione_v2_")
    assert _maintenance_sql(config.db_path()) == fresh
    c = db.connect()
    try:
        names = [r[0] for r in c.execute("SELECT name FROM maintenance_contractors ORDER BY name")]
        assert names == ["Clima Prova", "Idraulica Prova"]
        linked = dict(c.execute("SELECT j.title, k.name FROM maintenance_jobs j LEFT JOIN maintenance_contractors k "
                                "ON k.id=j.contractor_id").fetchall())
        assert linked == {"A": "Idraulica Prova", "B": "Idraulica Prova", "C": None, "D": None, "E": "Clima Prova"}
    finally:
        c.close()
