import pytest
from lxml import etree

from app import db
from app.db import AppError
from app.services import bookings, consistency, exports, guests
from conftest import checkin_all, mk_booking, mk_guest

DAY = "2026-10-12"


def _family(conn, day=DAY):
    b = mk_booking(conn, day, "2026-10-16", guests=3)
    capo = mk_guest(conn, b["id"], surname="ROSSI", name="MARIO", gtype="17")
    fam = mk_guest(conn, b["id"], surname="ROSSI", name="LUCIA", gtype="19", sex="F", birth="2010-02-03",
                   leader_guest_id=capo["id"])
    est = mk_guest(conn, b["id"], surname="MÜLLER", name="ANNA", gtype="16", sex="F", birth="1990-01-01",
                   birth_state_code="100000216", birth_comune_code=None, citizenship_code="100000216",
                   res_state_code="100000216", res_comune_code=None, res_place_text="BERLIN",
                   doc={"type": "PASOR", "number": "C01X00T47", "issue_place": "100000216"})
    for g in (capo, fam, est):
        guests.verify(conn, g["id"])
    checkin_all(conn, b["id"], day)
    return b, capo, fam, est


def test_txt_layout_168(conn):
    b, capo, fam, est = _family(conn)
    batch, data = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    assert not data.endswith(b"\r\n")  # nessun CR+LF dopo l'ultima riga
    lines = data.decode("cp1252").split("\r\n")
    assert [len(l) for l in lines] == [168, 168, 168]
    l0, l1, l2 = lines
    # ordine: capofamiglia seguito dal familiare
    assert l0[0:2] == "17" and l1[0:2] == "19"
    assert l0[2:12] == "12/10/2026" and l0[12:14] == "4 "
    assert l0[14:64].rstrip() == "ROSSI" and l0[64:94].rstrip() == "MARIO" and l0[94] == "1"
    # posizioni dal manuale Alloggiati (tabella numerata da 0): nascita 95-104, comune 105-113, ...
    assert l0[95:105] == "10/05/1980"
    assert l0[105:114] == "420090064" and l0[114:116] == "SS" and l0[116:125] == "100000100"
    assert l0[125:134] == "100000100"
    assert l0[134:139] == "IDENT" and l0[139:159].rstrip() == "XX0000000" and l0[159:168] == "420090064"
    assert l1[134:168] == " " * 34  # familiare: documento in bianco
    assert l2[105:116] == " " * 11 and l2[116:125] == "100000216"  # nato all'estero
    assert batch["status"] == "generato"


def test_txt_layout_174_with_apartment_id(conn):
    st = db.get_setting(conn, "structure")
    st["alloggiati"] = {"format": "174", "apartment_id": "123"}
    db.set_setting(conn, "structure", st)
    _family(conn)
    _, data = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    lines = data.decode("cp1252").split("\r\n")
    assert all(len(l) == 174 and l[168:174] == "000123" for l in lines)


def test_long_name_blocks_without_truncation(conn):
    b = mk_booking(conn, DAY, "2026-10-14", guests=1)
    g = mk_guest(conn, b["id"], surname="A" * 51)
    checkin_all(conn, b["id"], DAY)
    with pytest.raises(AppError):
        guests.verify(conn, g["id"])
    p = exports.alloggiati_preview(conn, DAY, DAY)
    assert not p["included"] and p["excluded"]


def test_member_without_leader_is_excluded_explicitly(conn):
    b, capo, fam, est = _family(conn)
    conn.execute("UPDATE guests SET verified_at=NULL WHERE id=?", (capo["id"],))
    p = exports.alloggiati_preview(conn, DAY, DAY)
    excl = {x["guest_id"]: x["reasons"] for x in p["excluded"]}
    assert capo["id"] in excl and fam["id"] in excl
    assert any("capofamiglia" in r for r in excl[fam["id"]])
    with pytest.raises(AppError):
        exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    batch, data = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=True)
    assert batch["item_count"] == 1


def test_superseded_after_change(conn):
    # E: modifica dopo la generazione -> lotto superato
    b, capo, fam, est = _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    guests.save(conn, b["id"], {"name": "MARIO GIUSEPPE", "version": guests.get(conn, capo["id"])["version"]},
                capo["id"])
    exports.reassess(conn)
    assert conn.execute("SELECT status FROM export_batches WHERE id=?", (batch["id"],)).fetchone()[0] == "superato"
    # anche gli altri ospiti dello stesso file superato tornano «da preparare»
    for g in (capo, fam, est):
        assert guests.get(conn, g["id"])["alloggiati_status"] == "da_preparare"


def test_change_after_declared_opens_correction(conn):
    # F: dati già comunicati -> rettifica, nessun aggiornamento simulato del portale
    b, capo, fam, est = _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    guests.save(conn, b["id"], {"surname": "ROSSI BIS", "version": guests.get(conn, capo["id"])["version"]},
                capo["id"])
    r = exports.reassess(conn)
    assert r["corrections"] == 1
    row = conn.execute("SELECT * FROM export_batches WHERE id=?", (batch["id"],)).fetchone()
    assert row["status"] == "caricamento_dichiarato"  # lo stato non diventa "aggiornato"
    c = conn.execute("SELECT * FROM corrections WHERE status='aperta'").fetchone()
    assert c["target"] == "alloggiati" and "rettifica" in c["reason"].lower()


def test_handled_correction_is_not_reopened(conn):
    # Collaudo simulato 24/10/2026: una rettifica gestita si riapriva identica alla scrittura successiva.
    b, capo, fam, est = _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    guests.save(conn, b["id"], {"name": "LUCIA ANNA", "version": guests.get(conn, fam["id"])["version"]}, fam["id"])
    consistency.reassess_all(conn)
    cid = conn.execute("SELECT id FROM corrections WHERE status='aperta'").fetchone()[0]
    exports.resolve_correction(conn, cid, "Rettificata sul portale")
    consistency.reassess_all(conn)
    assert not conn.execute("SELECT 1 FROM corrections WHERE status='aperta'").fetchone()
    guests.save(conn, b["id"], {"name": "LUCIA", "version": guests.get(conn, fam["id"])["version"]}, fam["id"])
    assert consistency.reassess_all(conn)["corrections"] == 1      # un cambiamento successivo riapre


def test_handled_ross_correction_is_not_reopened(conn):
    b, capo, fam, est = _family(conn, day="2026-09-02")
    batch, _ = exports.ross_generate(conn, "2026-09-02", "2026-09-02", confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    guests.save(conn, b["id"], {"birth_date": "1991-01-01", "version": guests.get(conn, est["id"])["version"]},
                est["id"])
    consistency.reassess_all(conn)
    cid = conn.execute("SELECT id FROM corrections WHERE status='aperta' AND target='ross'").fetchone()[0]
    exports.resolve_correction(conn, cid, "Movimento ritrasmesso")
    consistency.reassess_all(conn)
    assert not conn.execute("SELECT 1 FROM corrections WHERE status='aperta' AND target='ross'").fetchone()
    assert not exports.ross_preview(conn, "2026-09-02", "2026-09-02")["days"][0]["changed_since_declared"]


def test_no_double_send_and_partial_outcome(conn):
    b, capo, fam, est = _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    exports.declare_upload(conn, batch["id"])
    p = exports.alloggiati_preview(conn, DAY, DAY)
    assert not p["included"]  # già comunicati: esclusi salvo scelta esplicita
    res = exports.register_outcome(conn, batch["id"], {"items": {
        str(capo["id"]): {"outcome": "accettato"}, str(fam["id"]): {"outcome": "accettato"},
        str(est["id"]): {"outcome": "scartato", "note": "Documento non valido"}}})
    assert res == {"status": "da_correggere", "rejected": 1}
    assert guests.get(conn, est["id"])["alloggiati_status"] == "da_correggere"
    n = exports.receipt_acquired(conn, batch["id"])
    assert n == 1  # documenti realmente eliminati: il familiare accettato non aveva documento
    assert guests.get(conn, capo["id"])["doc_enc"] is None  # dati documentali eliminati dopo la ricevuta
    assert guests.get(conn, est["id"])["doc_enc"] is not None  # scartato: serve per la correzione


def test_download_is_not_success(conn):
    _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    assert batch["status"] == "generato"
    assert conn.execute("SELECT COUNT(*) FROM export_items WHERE outcome IS NOT NULL").fetchone()[0] == 0


def test_ross_xml_structure_and_zero_days(conn):
    b, capo, fam, est = _family(conn, day="2026-09-02")
    bk = bookings.get(conn, b["id"])
    bookings.check_out(conn, b["id"], {"version": bk["version"], "date": "2026-09-04"})
    bookings.create_closure(conn, {"start": "2026-09-05", "last": "2026-09-05", "note": "chiusura"})
    batch, data = exports.ross_generate(conn, "2026-09-01", "2026-09-05", confirm_partial=False)
    doc = etree.fromstring(data)
    mv = doc.findall("movimento")
    assert [m.findtext("data") for m in mv] == ["20260901", "20260902", "20260903", "20260904", "20260905"]
    assert mv[0].findtext("struttura/camereoccupate") == "0" and mv[0].findtext("struttura/apertura") == "SI"
    assert mv[1].findtext("struttura/camereoccupate") == "1"
    arr = mv[1].findall("arrivi/arrivo")
    assert len(arr) == 3
    fam_x = [a for a in arr if a.findtext("tipoalloggiato") == "19"][0]
    capo_x = [a for a in arr if a.findtext("tipoalloggiato") == "17"][0]
    assert fam_x.findtext("idcapo") == capo_x.findtext("idswh")
    est_x = [a for a in arr if a.findtext("cittadinanza") == "100000216"][0]
    assert est_x.findtext("comunenascita") == "" and est_x.findtext("luogoresidenza") == ""
    assert len(mv[3].findall("partenze/partenza")) == 3
    assert mv[4].findtext("struttura/apertura") == "NO" and mv[4].findtext("struttura/lettidisponibili") == "0"
    assert exports.ross_validate(data.decode()) == []


def test_ross_ids_stable_on_regeneration(conn):
    _family(conn, day="2026-09-02")
    _, d1 = exports.ross_generate(conn, "2026-09-01", "2026-09-03", confirm_partial=False)
    _, d2 = exports.ross_generate(conn, "2026-09-01", "2026-09-03", confirm_partial=False)
    ids = lambda d: [e.text for e in etree.fromstring(d).iter("idswh")]  # noqa: E731
    assert ids(d1) == ids(d2)
    assert conn.execute("SELECT status FROM export_batches ORDER BY id").fetchall()[0][0] == "superato"


def test_ross_requires_configuration(conn):
    st = db.get_setting(conn, "structure")
    st["ross"]["code"] = ""
    db.set_setting(conn, "structure", st)
    with pytest.raises(AppError) as ex:
        exports.ross_generate(conn, "2026-09-01", "2026-09-02", confirm_partial=False)
    assert "Codice struttura" in ex.value.message


def test_reservation_alone_generates_no_communication(conn):
    mk_booking(conn, "2026-09-10", "2026-09-12")
    r = exports.ross_build(conn, "2026-09-10", "2026-09-11")
    assert "<arrivo>" not in r["xml"]
    assert not exports.alloggiati_preview(conn, "2026-09-10", "2026-09-11")["included"]


def test_open_items_link_to_booking(conn):
    b = mk_booking(conn, "2026-09-10", "2026-09-12")
    items = consistency.open_items_for_booking(conn, bookings.get(conn, b["id"]))
    assert items and all(i["link"].startswith("#/") for i in items)


def test_ross_layout_matches_accepted_sample(conn):
    # Struttura confrontata (solo tag, senza leggere dati personali) con un file ROSS 1000 di altro gestionale.
    b, capo, fam, est = _family(conn, day="2026-09-02")
    _, data = exports.ross_generate(conn, "2026-09-02", "2026-09-02", confirm_partial=False)
    assert data.startswith(b"<movimenti><codice>")                       # nessuna dichiarazione XML
    doc = etree.fromstring(data)
    arr = doc.findall("movimento/arrivi/arrivo")
    assert [c.tag for c in arr[0]] == ["idswh", "tipoalloggiato", "idcapo", "sesso", "cittadinanza",
                                       "statoresidenza", "luogoresidenza", "datanascita", "statonascita",
                                       "comunenascita", "tipoturismo", "mezzotrasporto"]
    assert not doc.findall(".//cognome") and not doc.findall(".//titolostudio")   # nomi non inclusi di default


def test_alloggiati_layout_matches_accepted_schedine(conn):
    # Confronto di forma con schedine Alloggiati accettate (altro gestionale): giorni «3 », solo ASCII, maiuscolo.
    b, capo, fam, est = _family(conn)
    batch, data = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    data.decode("ascii")                                                   # nessun carattere accentato
    lines = data.decode("ascii").split("\r\n")
    est_line = [l for l in lines if l[14:64].strip() == "MULLER"][0]       # MÜLLER -> MULLER nel file
    assert est_line[12:14] == "4 " and est_line[64:94].rstrip() == "ANNA"
    assert guests.get(conn, est["id"])["surname"] == "MÜLLER"            # la scheda resta invariata
