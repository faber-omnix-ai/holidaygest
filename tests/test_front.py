"""Lettura del FRONTE dei documenti: testi SINTETICI (nomi e numeri inventati), nessun documento reale."""
import pytest

from app.services import front, ocr

CIE = """REPUBBLICA ITALIANA
CARTA DI IDENTITA / IDENTITY CARD
CA00000AA
COGNOME / SURNAME
PROVATI
NOME / NAME
MARIA ELENA
LUOGO E DATA DI NASCITA / PLACE AND DATE OF BIRTH
ALGHERO (SS) 10.05.1980
SESSO / SEX STATURA / HEIGHT CITTADINANZA / NATIONALITY
F 165 ITA
EMISSIONE / ISSUING SCADENZA / EXPIRY
01.02.2024 10.05.2034
COMUNE DI / MUNICIPALITY
SASSARI"""

CARTACEA = """REPUBBLICA ITALIANA
CARTA D'IDENTITA'
AX 0000000
COMUNE DI ALGHERO
Cognome DI PROVA
Nome GIOVANNI
nato il 03/12/1975
a OLBIA ( SS )
Cittadinanza ITALIANA"""

PATENTE = """PATENTE DI GUIDA
REPUBBLICA ITALIANA
1. PROVETTI
2. LUCA
3. 21/07/88 CAGLIARI (CA)
4a. 15/03/2020 4b. 21/07/2031
4c. MIT-UCO
5. U10000000X
9. AM B1 B"""


def _v(r, k):
    return r["fields"][k]["value"] if k in r["fields"] else None


def test_cie_front(data_dir):
    r = front.parse(CIE)
    assert _v(r, "surname") == "PROVATI" and _v(r, "name") == "MARIA ELENA"
    assert _v(r, "birth_date") == "1980-05-10" and _v(r, "sex") == "F"
    assert _v(r, "birth_comune_code") == "420090003" and _v(r, "birth_state_code") == "100000100"
    assert _v(r, "citizenship_code") == "100000100"
    assert _v(r, "doc.type") == "IDELE" and _v(r, "doc.number") == "CA00000AA"
    assert _v(r, "doc.issue_place") is not None
    assert all(f["status"] == "dubbio" for f in r["fields"].values())  # mai «letto» dal fronte


def test_paper_id_front(data_dir):
    r = front.parse(CARTACEA)
    assert _v(r, "surname") == "DI PROVA" and _v(r, "name") == "GIOVANNI"   # «DI» non è un'etichetta
    assert _v(r, "birth_date") == "1975-12-03"
    assert _v(r, "birth_comune_code") is not None and _v(r, "doc.type") == "IDENT"
    assert _v(r, "doc.number") == "AX0000000" and _v(r, "citizenship_code") == "100000100"


def test_driving_licence_front(data_dir):
    r = front.parse(PATENTE)
    assert _v(r, "surname") == "PROVETTI" and _v(r, "name") == "LUCA"
    assert _v(r, "birth_date") == "1988-07-21" and _v(r, "doc.type") == "PATEN"
    assert _v(r, "doc.number") == "U10000000X" and _v(r, "birth_comune_code") is not None
    assert "doc.issue_place" not in r["fields"] and any("4c" in n for n in r["notes"])


def test_unknown_place_and_garbage(data_dir):
    r = front.parse("COGNOME\nPROVA\nLUOGO E DATA DI NASCITA\nINESISTENTE (ZZ) 01.01.1990")
    assert "birth_comune_code" not in r["fields"] and any("non trovato" in n for n in r["notes"])
    assert front.parse("testo qualsiasi senza dati")["fields"] == {}


def test_mrz_wins_and_disagreement_is_flagged(data_dir):
    mrz = {"surname": {"value": "PROVATI", "status": "letto"}, "birth_date": {"value": "1980-05-11", "status": "letto"}}
    out, notes = front.combine(mrz, front.parse(CIE)["fields"])
    assert out["surname"]["status"] == "letto"                       # concordi: resta la lettura MRZ
    assert out["birth_date"] == {"value": "1980-05-11", "status": "dubbio"} and notes
    assert out["birth_comune_code"]["status"] == "dubbio"           # solo dal fronte


def test_merge_front_and_back(data_dir):
    fr = {"fields": front.parse(CIE)["fields"]}
    back = {"fields": {"surname": {"value": "PROVATI", "status": "letto"},
                       "doc.number": {"value": "CA00000AB", "status": "letto"}}}
    m = ocr.merge([fr, back])
    assert m["fields"]["surname"]["status"] == "letto"
    assert m["fields"]["doc.number"] == {"value": "CA00000AB", "status": "dubbio"} and m["conflicts"]


def test_ocr_on_synthetic_image(data_dir):
    """Catena completa: immagine sintetica -> OCR locale -> proposte. Saltato se mancano motore o font."""
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    if not font_path.exists() or not ocr.status()["available"]:
        pytest.skip("motore OCR o font non disponibili")
    font = ImageFont.truetype(str(font_path), 30)
    img = Image.new("RGB", (900, 760), "white")
    dr = ImageDraw.Draw(img)
    for i, line in enumerate(CIE.splitlines()):
        dr.text((30, 20 + i * 48), line, fill="black", font=font)
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    up = ocr.add_upload(buf.getvalue(), "sintetico.png")
    try:
        r = ocr.read(up["upload_id"])
    finally:
        ocr.discard(up["upload_id"])
    assert r["fields"]["surname"]["value"] == "PROVATI"
    assert r["fields"]["birth_date"]["value"] == "1980-05-10"
    assert r["fields"]["birth_comune_code"]["value"] == "420090003"
    assert r["fields"]["doc.number"]["value"] == "CA00000AA"


def test_mangled_label_line_is_not_taken_as_value(data_dir):
    # OCR reale: etichetta troncata («NATIONALITY» -> «NATIONAL») sulla riga delle etichette
    r = front.parse(CIE.replace("CITTADINANZA / NATIONALITY", "CITTADINANZA / NATIONAL"))
    assert _v(r, "sex") == "F" and _v(r, "citizenship_code") == "100000100"


def test_mrz_filler_read_as_japanese_ku():
    # RapidOCR ha restituito «く» al posto di «<» su un passaporto sintetico: va trattato come riempitivo
    from app.services import mrz
    text = ("P<FRADUBOIS<<LUCAS<<<く<<<<<く<<<く<<<く<く<<<<<く\n"
            "24FD000172FRA9103144M3306024<<<<<<<<<<<<<<04")
    r = mrz.parse(text)
    assert r and r["fields"]["surname"]["value"] == "DUBOIS" and r["fields"]["name"]["value"] == "LUCAS"
