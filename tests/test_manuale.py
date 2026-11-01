"""Il manuale nell'app: nomi di pulsanti reali, immagini presenti, nessun dato di una struttura nel testo comune."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
MAN = (STATIC / "manuale.js").read_text(encoding="utf-8")
ED = (STATIC / "manuale_edizione.js").read_text(encoding="utf-8")
ROUTE = re.compile(r"#/(\w+)")


def _fonti():
    testi = [(STATIC / f).read_text(encoding="utf-8") for f in ("index.html", "core.js", "boot.js", "views_today_calendar.js",
             "views_booking.js", "views_docs_exports.js", "views_tax_settings.js", "views_maintenance.js")]
    testi.append((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    return "\n".join(testi)


def test_nomi_tra_virgolette_esistono_nel_programma():
    fonti = _fonti()
    # solo i testi dei capitoli: fuori ci sono il commento di testa e il codice che riconosce le virgolette
    corpo = MAN.split("function manCapitoli", 1)[1].split("/* Testo con", 1)[0] + ED
    assenti = sorted({n for n in re.findall(r"«([^»]+)»", corpo) if n not in fonti})
    assert assenti == [], assenti


def test_collegamenti_portano_a_schermate_vere():
    fonti = _fonti()
    for route in set(ROUTE.findall(MAN)):
        assert route == "manuale" or f'^\\/{route}' in fonti, route


def test_capitoli_di_aiuto_esistono():
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    mappa = re.search(r"const AIUTO = \{(.+?)\};", core).group(1)
    for cap in re.findall(r': "(\w+)"', mappa):
        assert f'id: "{cap}"' in MAN, cap


def test_immagini_presenti():
    for nome in re.findall(r'MAN_IMG\("([\w-]+)"', MAN):
        assert (STATIC / "assets" / "manuale" / f"{nome}.jpg").is_file(), nome


def test_testo_comune_senza_riferimenti_a_una_struttura():
    assert not re.search(r"Alghero", MAN)
    assert "innerHTML" not in MAN.replace("mai innerHTML", "")
