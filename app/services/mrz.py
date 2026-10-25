"""Lettura MRZ (ICAO 9303) TD1, TD2, TD3 con cifre di controllo.

La MRZ aiuta la trascrizione ma NON prova l'autenticità del documento. I codici MRZ
(es. nazionalità ISO 3166 alpha-3) NON sono codici Alloggiati: la scelta del codice
ufficiale resta all'operatrice.
"""
from __future__ import annotations

import re
from datetime import date

_W = (7, 3, 1)
_LINE = re.compile(r"[A-Z0-9<]{28,46}")
# Correzioni OCR tipiche, applicate solo in base alla posizione (cifre vs lettere)
_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"})
# segni che l'OCR multilingue può restituire al posto del riempitivo «<» (prova del 15/10/2026: «く» giapponese)
_FILLER = str.maketrans({"«": "<", "‹": "<", "く": "<", "〈": "<", "＜": "<", "﹤": "<", "⟨": "<", "ㄑ": "<"})


def _val(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c == "<":
        return 0
    return ord(c) - 55


def check_digit(s: str) -> str:
    return str(sum(_val(c) * _W[i % 3] for i, c in enumerate(s)) % 10)


def _digits(s: str) -> str:
    return s.translate(_TO_DIGIT)


def _alpha(s: str) -> str:
    return s.translate(_TO_ALPHA)


def _date(yymmdd: str, birth: bool) -> str | None:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    cur = date.today().year % 100
    century = (1900 if yy > cur else 2000) if birth else 2000
    try:
        return date(century + yy, mm, dd).isoformat()
    except ValueError:
        return None


def _names(field: str) -> tuple[str, str]:
    sur, _, giv = field.partition("<<")
    return sur.replace("<", " ").strip(), giv.replace("<", " ").strip()


def find_lines(text: str) -> list[str]:
    out = []
    for raw in text.upper().splitlines():
        s = raw.replace(" ", "").translate(_FILLER)
        m = _LINE.search(s)
        if m and m.group(0).count("<") >= 2:
            out.append(m.group(0))
    return out


def parse(text: str) -> dict | None:
    lines = find_lines(text)
    for size, n in ((30, 3), (44, 2), (36, 2)):
        cand = [l for l in lines if abs(len(l) - size) <= 1]
        for i in range(len(cand) - n + 1):
            block = [l[:size].ljust(size, "<") for l in cand[i:i + n]]
            res = _parse_td1(block) if size == 30 else _parse_td3(block) if size == 44 else _parse_td2(block)
            if res:
                return res
    return None


def _field(value, ok: bool | None) -> dict:
    return {"value": value, "status": "letto" if ok else "dubbio"}


def _common(doc_code, country, number, n_ok, birth, b_ok, sex, expiry, e_ok, nat, surname, given, composite_ok):
    sx = {"M": "M", "F": "F"}.get(sex)
    return {
        "format_ok": composite_ok,
        "document_code": doc_code.replace("<", ""),
        "issuing_country_iso3": _alpha(country).replace("<", ""),
        "fields": {
            "surname": _field(surname, composite_ok), "name": _field(given, composite_ok),
            "doc.number": _field(number.replace("<", ""), n_ok),
            "birth_date": _field(_date(birth, True), b_ok and _date(birth, True) is not None),
            "sex": {"value": sx, "status": "letto" if sx else "mancante"},
            "nationality_iso3": _field(_alpha(nat).replace("<", ""), composite_ok),
            "doc.expiry": _field(_date(expiry, False), e_ok),
        },
        "note": "Dati letti dalla MRZ: verificarli sul documento. La MRZ non garantisce l'autenticità.",
    }


def _parse_td3(l: list[str]) -> dict | None:
    a, b = l
    if a[0] not in "PV":
        return None
    number, n_cd = b[0:9], _digits(b[9])
    nat = b[10:13]
    birth, b_cd = _digits(b[13:19]), _digits(b[19])
    sex = b[20]
    expiry, e_cd = _digits(b[21:27]), _digits(b[27])
    opt, o_cd = b[28:42], b[42]
    comp_cd = _digits(b[43])
    composite = number + n_cd + birth + b_cd + expiry + e_cd + opt + o_cd
    sur, giv = _names(_alpha(a[5:44]))
    return _common(a[0:2], a[2:5], number, check_digit(number) == n_cd, birth, check_digit(birth) == b_cd, sex,
                   expiry, check_digit(expiry) == e_cd, nat, sur, giv, check_digit(composite) == comp_cd)


def _parse_td2(l: list[str]) -> dict | None:
    a, b = l
    if a[0] not in "ACI":
        return None
    number, n_cd = b[0:9], _digits(b[9])
    nat = b[10:13]
    birth, b_cd = _digits(b[13:19]), _digits(b[19])
    sex = b[20]
    expiry, e_cd = _digits(b[21:27]), _digits(b[27])
    composite = number + n_cd + birth + b_cd + expiry + e_cd + b[28:35]
    sur, giv = _names(_alpha(a[5:36]))
    return _common(a[0:2], a[2:5], number, check_digit(number) == n_cd, birth, check_digit(birth) == b_cd, sex,
                   expiry, check_digit(expiry) == e_cd, nat, sur, giv, check_digit(composite) == _digits(b[35]))


def _parse_td1(l: list[str]) -> dict | None:
    a, b, c = l
    if a[0] not in "ACI":
        return None
    number, n_cd = a[5:14], _digits(a[14])
    if n_cd == "<":  # numero lungo: prosegue nel campo opzionale
        ext = a[15:30].split("<")[0]
        number, n_cd = number + ext[:-1], ext[-1:]
    birth, b_cd = _digits(b[0:6]), _digits(b[6])
    sex = b[7]
    expiry, e_cd = _digits(b[8:14]), _digits(b[14])
    nat = b[15:18]
    composite = a[5:30] + b[0:7] + b[8:15] + b[18:29]
    sur, giv = _names(_alpha(c))
    return _common(a[0:2], a[2:5], number, check_digit(number) == n_cd, birth, check_digit(birth) == b_cd, sex,
                   expiry, check_digit(expiry) == e_cd, nat, sur, giv, check_digit(composite) == _digits(b[29]))
