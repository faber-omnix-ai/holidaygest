"""Esportazioni di riepilogo (CSV/XLSX/PDF) minimizzate: niente numeri di documento né dati sanitari.
Le celle che iniziano con = + - @ (o tab/CR) vengono neutralizzate per impedire formule nei fogli."""
from __future__ import annotations

import csv
import io
import json

from .. import config
from ..db import get_setting
from ..util import eur, it

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    if isinstance(v, str) and v.startswith(_DANGEROUS):
        return "'" + v
    return v


def to_csv(headers: list[str], data: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(headers)
    for r in data:
        w.writerow([safe_cell(x) for x in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(title: str, headers: list[str], data: list[list]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(headers)
    for r in data:
        ws.append([safe_cell(x) for x in r])
        for c in ws[ws.max_row]:
            if isinstance(c.value, str):
                c.data_type = "s"  # mai formula
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def period_table(snap: dict) -> tuple[list[str], list[list]]:
    rows_ = [
        ["Periodo", f"{snap['kind']} {snap['period']} ({it(snap['from'])} – {it(snap['to'])} escluso)"],
        ["Soggiorni con presenze", snap["stays"]],
        ["Persone arrivate", snap["persons_arrived"]],
        ["Pernottamenti (presenze effettive)", snap["presence_nights"]],
    ]
    for k, v in snap["tax_nights"].items():
        rows_.append([f"Notti {k.replace('_', ' ')}", v])
    for k, v in snap["exempt_reasons"].items():
        rows_.append([f"  di cui: {k}", v])
    rows_ += [
        ["Imposta calcolata", eur(snap["tax_computed_cents"])],
        ["Imposta incassata", eur(snap["tax_collected_cents"])],
        ["Imposta rimborsata", eur(snap["tax_refunded_cents"])],
        ["Imposta gestita da terzi (documentata)", eur(snap["tax_third_party_cents"])],
        ["Imposta versata", eur(snap["tax_remitted_cents"])],
        ["Ricavi maturati soggiorno (per notte)", eur(snap["revenue_accrued_cents"])],
        ["Incassi soggiorno (per data)", eur(snap["stay_received_cents"])],
        ["Rimborsi soggiorno", eur(snap["stay_refunded_cents"])],
        ["Cauzioni ricevute", eur(snap["deposit_received_cents"])],
        ["Cauzioni restituite", eur(snap["deposit_returned_cents"])],
        ["Criterio notti", snap["attribution"]["notti"]],
        ["Criterio incassi", snap["attribution"]["incassi"]],
        ["Anomalie aperte", len(snap["anomalies"])],
    ]
    return ["Voce", "Valore"], rows_


def _pdf(title: str, blocks: list, footer: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=title, author=config.APP_NAME)
    ss = getSampleStyleSheet()
    story = [Paragraph(title, ss["Title"])]
    for b in blocks:
        if isinstance(b, str):
            story.append(Paragraph(b.replace("&", "&amp;").replace("<", "&lt;"), ss["BodyText"]))
        elif isinstance(b, list):
            t = Table([[Paragraph(str(c).replace("&", "&amp;").replace("<", "&lt;"), ss["BodyText"]) for c in r]
                       for r in b], colWidths=[85 * mm, 85 * mm])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(t)
        story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(footer, ss["Italic"]))
    doc.build(story)
    return buf.getvalue()


def structure_lines(conn) -> list[str]:
    st = get_setting(conn, "structure", {}) or {}
    return [f"{st.get('name', '')} — {st.get('address', '')}",
            f"CIN {st.get('cin', '')}" + (f" · Gestore: {st['owner_name']}" if st.get("owner_name") else "")]


def receipt_pdf(conn, r: dict, booking: dict, guests_count: int) -> bytes:
    det = json.loads(r["detail"])
    blocks = structure_lines(conn) + [[
        ["Quietanza n.", f"{r['number']}/{r['year']}"],
        ["Data", it(r["issued_on"])],
        ["Soggiorno", f"{booking['ref']} dal {it(booking['arrival'])} al {it(booking['departure'])}"],
        ["Ospiti", str(guests_count)],
        ["Importo imposta di soggiorno incassato", eur(r["amount_cents"])],
        ["Imposta dovuta per il soggiorno", eur(det.get("due_cents")) + f" ({det.get('due_source')})"],
        ["Stato", "ANNULLATA: " + (r["cancel_reason"] or "") if r["status"] == "annullata" else "Emessa"],
    ], "Quietanza dell'imposta di soggiorno riscossa dal gestore ai sensi del Regolamento comunale (art. 7). "
       "Non è una fattura né una ricevuta del corrispettivo dell'alloggio."]
    return _pdf("Quietanza imposta di soggiorno", blocks, f"Generato da {config.APP_NAME} {config.VERSION}")


def period_pdf(conn, snap: dict) -> bytes:
    _, rows_ = period_table(snap)
    blocks = structure_lines(conn) + [rows_] + snap["explanations"]
    if snap["anomalies"]:
        blocks.append("Anomalie: " + " | ".join(a["text"] for a in snap["anomalies"][:40]))
    return _pdf(f"Controllo periodo {snap['period']}", blocks,
                "Prospetto di riepilogo: non costituisce prova di versamento né comunicazione all'ente.")


def staytour_pdf(conn, sh: dict) -> bytes:
    data = [["Pernottamenti imponibili", sh["pernottamenti_imponibili"]],
            ["Giorni di permanenza (presenze)", sh["giorni_permanenza"]],
            ["Pernottamenti oltre il limite", sh["pernottamenti_oltre_limite"]],
            ["Pernottamenti DA VERIFICARE", sh["da_verificare"]],
            ["Imposta calcolata", eur(sh["imposta_calcolata_cents"])],
            ["Imposta riscossa (netto rimborsi)", eur(sh["imposta_riscossa_cents"])],
            ["Imposta gestita da terzi", eur(sh["imposta_gestita_terzi_cents"])],
            ["Versamenti registrati", eur(sh["versato_cents"])]]
    data += [[f"Esenti/non assoggettati: {k}", v] for k, v in sh["pernottamenti_esenti_per_motivo"].items()]
    blocks = structure_lines(conn) + [sh["avvertenza"], f"Criterio: {sh['criterio']}", data]
    return _pdf(sh["titolo"], blocks, "Da riportare manualmente sul portale comunale (StayTour/SECAL).")


def exemption_draft_pdf(conn, kind: str) -> bytes:
    texts = {
        "disabilita_grave": ("Dichiarazione sostitutiva — esenzione persona con disabilità grave e accompagnatore",
                             "Il/La sottoscritto/a ____________________, nato/a a ____________ il __________, "
                             "consapevole delle sanzioni penali previste dall'art. 76 del D.P.R. 445/2000 per "
                             "dichiarazioni mendaci, dichiara di trovarsi nella condizione di disabilità grave "
                             "certificata ai sensi dell'art. 3, comma 3, della Legge 104/1992 (o analoga disposizione "
                             "del Paese di provenienza) e indica quale accompagnatore ____________________."),
        "assistenza_ricoverati": ("Dichiarazione sostitutiva — esenzione per assistenza a persona ricoverata",
                                  "Il/La sottoscritto/a ____________________, consapevole delle sanzioni previste "
                                  "dall'art. 76 del D.P.R. 445/2000, dichiara di pernottare nel Comune di ____________ dal ________ "
                                  "al ________ per garantire assistenza a persona ricoverata presso un nosocomio "
                                  "cittadino."),
        "forze_servizio": ("Dichiarazione — personale in servizio",
                           "Il/La sottoscritto/a ____________________, appartenente a ____________________, "
                           "dichiara di soggiornare per esigenze di servizio dal ________ al ________."),
    }
    if kind not in texts:
        from ..db import AppError
        raise AppError("Modulo non disponibile.")
    title, body = texts[kind]
    blocks = ["BOZZA DA VERIFICARE — usare il modulo ufficiale del Comune/SECAL se disponibile.",
              *structure_lines(conn), body,
              "Non indicare diagnosi o altre informazioni sanitarie oltre a quanto richiesto.",
              "Luogo e data ____________________        Firma ____________________"]
    return _pdf(title, blocks, "Bozza non ufficiale generata dal gestionale.")
