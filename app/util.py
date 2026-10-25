"""Utilità comuni: date, importi, testo."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .db import AppError


def d(s: str | date | None, field: str = "data") -> date:
    if isinstance(s, date):
        return s
    if not s:
        raise AppError(f"Data mancante ({field}).", field=field)
    try:
        if "/" in s:  # formato italiano gg/mm/aaaa
            g, m, a = s.split("/")
            return date(int(a), int(m), int(g))
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        raise AppError(f"Data non valida: «{s}» ({field}). Usa il formato gg/mm/aaaa.", field=field)


def iso(x: date | None) -> str | None:
    return x.isoformat() if x else None


def it(x: str | date | None) -> str:
    if not x:
        return ""
    x = d(x)
    return f"{x.day:02d}/{x.month:02d}/{x.year}"


def nights(start: str | date, end: str | date) -> list[date]:
    a, b = d(start), d(end)
    return [a + timedelta(days=i) for i in range((b - a).days)]


def add_days(x: str | date, n: int) -> str:
    return (d(x) + timedelta(days=n)).isoformat()


def overlaps(a1: str, a2: str, b1: str, b2: str) -> bool:
    """Intervalli [a1,a2) e [b1,b2) su date ISO."""
    return a1 < b2 and b1 < a2


def eur(cents: int | None) -> str:
    if cents is None:
        return "DA VERIFICARE"
    sign = "-" if cents < 0 else ""
    c = abs(int(cents))
    whole = f"{c // 100:,}".replace(",", ".")
    return f"{sign}€ {whole},{c % 100:02d}"


def parse_cents(v, field: str = "importo") -> int:
    """Accetta centesimi interi o stringhe in formato italiano ("1.234,50")."""
    if v is None or v == "":
        return 0
    if isinstance(v, int):
        return v
    s = str(v).strip().replace("€", "").replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d{1,2})?|\d+([.,]\d{1,2})?", s):
        raise AppError(f"Importo non valido: «{v}» ({field}).", field=field)
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    whole, _, frac = s.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def hhmm(s: str | None, field: str = "orario") -> str | None:
    if not s:
        return None
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s):
        raise AppError(f"Orario non valido: «{s}» ({field}). Usa hh:mm.", field=field)
    return s


def minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def quarter_of(x: date) -> int:
    return (x.month - 1) // 3 + 1


def period_bounds(kind: str, period: str) -> tuple[str, str]:
    """Restituisce [inizio, fine) per 'mese' (2026-03), 'trimestre' (2026-T1), 'anno' (2026)."""
    try:
        if kind == "mese":
            y, m = map(int, period.split("-"))
            s = date(y, m, 1)
            e = date(y + (m == 12), (m % 12) + 1, 1)
        elif kind == "trimestre":
            y, q = period.split("-T")
            y, q = int(y), int(q)
            s = date(y, 3 * (q - 1) + 1, 1)
            e = date(y + (q == 4), (3 * q % 12) + 1, 1)
        elif kind == "anno":
            y = int(period)
            s, e = date(y, 1, 1), date(y + 1, 1, 1)
        else:
            raise ValueError
    except ValueError:
        raise AppError(f"Periodo non valido: {kind} {period}")
    return s.isoformat(), e.isoformat()


def age_on(birth: date, when: date) -> int:
    return when.year - birth.year - ((when.month, when.day) < (birth.month, birth.day))


def now_local() -> datetime:
    from .config import TZ
    return datetime.now(TZ)
