"""Anteprima delle conseguenze delle modifiche agli ospiti: simulata, mai salvata, uguale all'effetto reale."""
from app.services import bookings, consistency, exports, guests, tax
from conftest import mk_booking, mk_guest
from test_exports import DAY, _family


def _state(conn):
    return (conn.execute("SELECT group_concat(id||status) FROM export_batches").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0],
            conn.execute("SELECT group_concat(id||tax_status||COALESCE(stay_departure,'')||presence) FROM guests"
                         ).fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0])


def test_preview_exemption_change_shows_tax_and_correction_without_saving(conn):
    b = mk_booking(conn, "2026-06-01", "2026-06-04", guests=1)
    g = mk_guest(conn, b["id"])
    from conftest import checkin_all
    checkin_all(conn, b["id"], "2026-06-01")
    bookings.guest_departure(conn, b["id"], g["id"], "2026-06-04")
    tax.consolidate(conn, b["id"])
    before = _state(conn)
    g = guests.get(conn, g["id"])
    p = consistency.simulate(conn, b["id"], lambda c: guests.save(
        c, b["id"], {"tax_status": "residente", "version": g["version"]}, g["id"]))
    text = " ".join(p["summary"])
    assert "6,00" in text and "0,00" in text            # imposta 6 € -> 0 €
    assert "rettifica" in text.lower() and p["communications_affected"]
    assert _state(conn) == before                        # niente salvato, nemmeno l'audit


def test_preview_stay_change_marks_batch_superseded_only_in_preview(conn):
    b, capo, fam, est = _family(conn)
    batch, _ = exports.alloggiati_generate(conn, DAY, DAY, confirm_partial=False)
    before = _state(conn)
    p = consistency.simulate(conn, b["id"], lambda c: guests.set_stay(
        c, est["id"], {"stay_arrival": "2026-10-13", "reason": "arrivata un giorno dopo"}))
    text = " ".join(p["summary"])
    assert f"n. {batch['id']}" in text and "superato" in text and "MÜLLER ANNA: arrivo effettivo 12/10/2026 → 13/10/2026" in text
    assert _state(conn) == before
    # l'effetto reale coincide con l'anteprima
    guests.set_stay(conn, est["id"], {"stay_arrival": "2026-10-13", "reason": "arrivata un giorno dopo"})
    consistency.reassess_all(conn)
    assert conn.execute("SELECT status FROM export_batches WHERE id=?", (batch["id"],)).fetchone()[0] == "superato"


def test_preview_delete_and_not_arrived(conn):
    b = mk_booking(conn, "2026-07-01", "2026-07-05", guests=2)
    g1 = mk_guest(conn, b["id"])
    g2 = mk_guest(conn, b["id"], name="LUIGI", birth="1985-01-01")
    before = _state(conn)
    p = consistency.simulate(conn, b["id"], lambda c: guests.delete(c, g2["id"], "errore"))
    assert any("verrà eliminata" in s for s in p["summary"]) and any("Imposta" in s for s in p["summary"])
    p = consistency.simulate(conn, b["id"], lambda c: bookings.mark_not_arrived(c, b["id"], g1["id"]))
    assert any("prevista → non arrivata" in s for s in p["summary"])
    assert _state(conn) == before and guests.get(conn, g2["id"])


def test_preview_validation_error_propagates_and_rolls_back(conn):
    import pytest
    from app.db import AppError
    b = mk_booking(conn, "2026-07-01", "2026-07-05", guests=1)
    g = mk_guest(conn, b["id"])
    before = _state(conn)
    with pytest.raises(AppError):
        consistency.simulate(conn, b["id"], lambda c: guests.save(
            c, b["id"], {"planned_departure": "2026-07-09", "version": g["version"]}, g["id"]))
    assert _state(conn) == before
    assert not conn.in_transaction
