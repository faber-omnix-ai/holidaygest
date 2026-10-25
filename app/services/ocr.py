"""Lettura locale dei documenti: tutto in memoria, nessun file scritto su disco.

Motore: RapidOCR (modelli PP-OCR in ONNX, Apache-2.0) su CPU tramite onnxruntime, inclusi
nel pacchetto; nessun servizio esterno. PDF: prima estrazione del testo (pypdfium2), poi OCR
delle pagine rasterizzate se il testo manca. HEIC: non supportato (convertire in JPG).
Il testo estratto è trattato come DATO NON ATTENDIBILE: non viene mai interpretato come comando,
non viene registrato nei log, non viene salvato.
"""
from __future__ import annotations

import io
import logging
import secrets
import threading
import time

from ..db import AppError
from ..state import STATE
from . import mrz

MAX_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PDF_PAGES = 4
log = logging.getLogger("gestionale.ocr")
_engine = None
_engine_lock = threading.Lock()
_engine_error: str | None = None


def sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heim", b"heis"):
        return "image/heic"
    return None


def engine():
    """Carica il motore una sola volta. In caso di errore il percorso manuale resta disponibile."""
    global _engine, _engine_error
    with _engine_lock:
        if _engine is None and _engine_error is None:
            try:
                from rapidocr import RapidOCR
                _engine = RapidOCR(params={"Global.log_level": "error"})
            except Exception as ex:  # motore assente o danneggiato
                _engine_error = f"{type(ex).__name__}"
                log.warning("Motore OCR non disponibile: %s", _engine_error)
        if _engine is None:
            raise AppError("Il motore di lettura documenti non è disponibile su questo PC. "
                           "Prosegui con l'inserimento manuale: i dati già inseriti restano.", 503)
        return _engine


def status() -> dict:
    try:
        engine()
        return {"available": True}
    except AppError as ex:
        return {"available": False, "message": ex.message}


def _open_image(data: bytes, rotation: int):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise AppError("Immagine non leggibile o danneggiata.")
    img = ImageOps.exif_transpose(img).convert("RGB")
    if rotation % 360:
        img = img.rotate(-rotation, expand=True)
    return img


def _pdf_pages(data: bytes) -> list[tuple[str, object]]:
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise AppError("PDF non leggibile o protetto.")
    out = []
    try:
        if len(pdf) > MAX_PDF_PAGES:
            raise AppError(f"PDF con troppe pagine (massimo {MAX_PDF_PAGES}): caricare solo fronte e retro.")
        for i in range(len(pdf)):
            page = pdf[i]
            text = page.get_textpage().get_text_range() or ""
            img = page.render(scale=2.0).to_pil().convert("RGB")
            out.append((text, img))
    finally:
        pdf.close()
    return out


def _thumb(img) -> bytes:
    from PIL import Image
    t = img.copy()
    t.thumbnail((1400, 1400), Image.LANCZOS)
    buf = io.BytesIO()
    t.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def _ocr_image(img) -> str:
    import numpy as np
    eng = engine()
    res = eng(np.asarray(img))
    txts = getattr(res, "txts", None) or ()
    return "\n".join(t for t in txts if t)


def add_upload(data: bytes, filename: str) -> dict:
    if len(data) > MAX_BYTES:
        raise AppError("File troppo grande (massimo 15 MB).", 413)
    kind = sniff(data)
    if kind is None:
        raise AppError("Formato non riconosciuto: usare JPG, PNG o PDF.")
    if kind == "image/heic":
        raise AppError("Le foto HEIC non sono supportate localmente: sul telefono scegliere «Più compatibile» "
                       "(JPG) oppure convertire la foto in JPG.")
    uid = secrets.token_urlsafe(12)
    entry = {"created": time.time(), "kind": kind, "data": data, "name": filename[:80], "rotation": 0}
    with STATE.lock:
        STATE.purge_uploads()
        if len(STATE.uploads) >= 12:
            raise AppError("Troppi documenti in verifica: completare o scartare quelli aperti.")
        STATE.uploads[uid] = entry
    return {"upload_id": uid, "kind": kind}


def _get(uid: str) -> dict:
    with STATE.lock:
        e = STATE.uploads.get(uid)
    if not e:
        raise AppError("Documento non più disponibile (scaduto o già eliminato): ricaricarlo.", 404)
    return e


def preview(uid: str, rotation: int = 0) -> bytes:
    e = _get(uid)
    if e["kind"] == "application/pdf":
        pages = _pdf_pages(e["data"])
        img = pages[0][1]
        if rotation % 360:
            img = img.rotate(-rotation, expand=True)
    else:
        img = _open_image(e["data"], rotation)
    return _thumb(img)


def read(uid: str, rotation: int = 0) -> dict:
    """Estrae testo e campi proposti. Restituisce SOLO proposte con stato (letto/dubbio/mancante)."""
    e = _get(uid)
    texts, used_ocr = [], False
    if e["kind"] == "application/pdf":
        for text, img in _pdf_pages(e["data"]):
            if len(text.strip()) >= 20:
                texts.append(text)
            else:
                if rotation % 360:
                    img = img.rotate(-rotation, expand=True)
                texts.append(_ocr_image(img))
                used_ocr = True
    else:
        texts.append(_ocr_image(_open_image(e["data"], rotation)))
        used_ocr = True
    full = "\n".join(texts)
    parsed = mrz.parse(full)
    result = {"engine": "RapidOCR (locale, CPU)" if used_ocr else "Testo del PDF",
              "mrz_found": bool(parsed), "fields": {}, "notes": []}
    if parsed:
        result["fields"] = parsed["fields"]
        result["document_code"] = parsed["document_code"]
        result["issuing_country_iso3"] = parsed["issuing_country_iso3"]
        if not parsed["format_ok"]:
            result["notes"].append("Cifra di controllo complessiva MRZ non corrispondente: lettura dubbia, "
                                   "verificare ogni campo.")
        result["notes"].append(parsed["note"])
    else:
        result["notes"].append("Zona MRZ non trovata o illeggibile: si propongono solo i campi riconosciuti nel "
                               "testo del fronte; gli altri vanno compilati guardando il documento, oppure "
                               "riprovare ruotando l'immagine.")
    from . import front
    fr = front.parse(full)
    result["fields"], diff_notes = front.combine(result["fields"], fr["fields"])
    result["notes"] += fr["notes"] + diff_notes
    from . import tables
    for k, kind in (("birth_comune_code", "comuni"), ("birth_state_code", "stati"), ("citizenship_code", "stati"),
                    ("doc.type", "documenti"), ("doc.issue_place", "comuni")):
        it = tables.get(kind, (result["fields"].get(k) or {}).get("value"))
        if it:
            result["fields"][k]["label"] = it["name"] + (f" ({it['prov']})" if kind == "comuni" and it.get("prov") else "")
    # Testo grezzo mostrato SOLO a video per facilitare la trascrizione; mai salvato o registrato.
    result["raw_text"] = full[:4000]
    with STATE.lock:
        if uid in STATE.uploads:
            STATE.uploads[uid]["rotation"] = rotation
    return result


def discard(uid: str) -> None:
    with STATE.lock:
        e = STATE.uploads.pop(uid, None)
        if e:
            e.clear()


def merge(readings: list[dict]) -> dict:
    """Unisce letture fronte/retro: valori discordanti diventano 'dubbio' con conflitto segnalato."""
    out: dict = {}
    conflicts = []
    for r in readings:
        for k, f in (r.get("fields") or {}).items():
            if f.get("value") in (None, ""):
                continue
            if k in out and out[k]["value"] != f["value"]:
                conflicts.append(f"{k}: «{out[k]['value']}» / «{f['value']}»")
                keep = f if f.get("status") == "letto" and out[k].get("status") != "letto" else out[k]
                out[k] = {"value": keep["value"], "status": "dubbio"}  # preferito il valore letto dalla MRZ
            elif k not in out:
                out[k] = dict(f)
            elif f.get("status") == "letto" and not any(c.split(":")[0] == k for c in conflicts):
                out[k] = dict(f)  # stesso valore confermato dalla MRZ (fronte e retro concordi)
    return {"fields": out, "conflicts": conflicts}
