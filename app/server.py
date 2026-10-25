"""Server HTTP locale (solo 127.0.0.1). Nessuna dipendenza esterna, nessuna risorsa remota.

Protezioni: controllo Host (anti DNS-rebinding), controllo Origin e token CSRF su ogni richiesta
che modifica dati, cookie di sessione HttpOnly SameSite=Strict, CSP restrittiva, limiti di dimensione.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import socket
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import config, db
from .db import AppError
from .state import STATE

log = logging.getLogger("gestionale.http")
MAX_BODY = 20 * 1024 * 1024
ROUTES: list[tuple[str, re.Pattern, callable, dict]] = []


def route(method: str, pattern: str, auth: bool = True, write: bool | None = None, raw: bool = False,
          reassess: bool = True, use_db: bool = True):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn,
                       {"auth": auth, "write": method != "GET" if write is None else write, "raw": raw,
                        "reassess": reassess, "db": use_db}))
        return fn
    return deco


class Request:
    def __init__(self, method, path, query, headers, body, session):
        self.method, self.path, self.query, self.headers, self.body, self.session = \
            method, path, query, headers, body, session
        self._json = None

    @property
    def json(self) -> dict:
        if self._json is None:
            try:
                self._json = json.loads(self.body.decode("utf-8")) if self.body else {}
            except ValueError:
                raise AppError("Richiesta non valida.")
            if not isinstance(self._json, dict):
                raise AppError("Richiesta non valida.")
        return self._json

    def q(self, key, default=None):
        v = self.query.get(key)
        return v[0] if v else default


class FileResponse:
    def __init__(self, data: bytes, ctype: str, filename: str | None = None, inline: bool = False):
        self.data, self.ctype, self.filename, self.inline = data, ctype, filename, inline


class Handler(BaseHTTPRequestHandler):
    server_version = "Gestionale"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # nessun URL con parametri nei log
        pass

    # ----- sicurezza -----
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{STATE.port}", f"localhost:{STATE.port}")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            ref = self.headers.get("Referer") or ""
            return ref.startswith((f"http://127.0.0.1:{STATE.port}/", f"http://localhost:{STATE.port}/"))
        return origin in (f"http://127.0.0.1:{STATE.port}", f"http://localhost:{STATE.port}")

    def _cookie(self, name: str) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
                         "object-src 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj, extra=None):
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", {"Cache-Control": "no-store", **(extra or {})})

    # ----- metodi -----
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _static(self, path: str):
        root = config.static_dir().resolve()
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (root / rel).resolve()
        if root not in target.parents and target != root / "index.html" or not target.is_file():
            target = root / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    def _dispatch(self, method: str):
        t0 = time.time()
        try:
            if not self._host_ok():
                return self._send(421, b"Host non consentito", "text/plain; charset=utf-8")
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                if method != "GET":
                    return self._send(405, b"", "text/plain")
                return self._static(u.path)
            for m, rx, fn, opt in ROUTES:
                if m != method:
                    continue
                mt = rx.match(u.path)
                if mt:
                    return self._call(fn, opt, mt, u, method)
            return self._json(404, {"error": "Risorsa non trovata."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            dt = time.time() - t0
            if dt > 5:
                log.info("richiesta lenta %s %.1fs", method, dt)

    def _call(self, fn, opt, mt, u, method):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "File o richiesta troppo grande (massimo 20 MB)."})
        body = self.rfile.read(length) if length else b""
        token = self._cookie("gsid")
        session = STATE.sessions.get(token)
        if opt["write"]:
            if not self._origin_ok():
                return self._json(403, {"error": "Richiesta non consentita (origine)."})
            if opt["auth"] and (not session or self.headers.get("X-CSRF-Token") != session["csrf"]):
                return self._json(403, {"error": "Sessione scaduta: ricarica la pagina e accedi di nuovo."})
        if opt["auth"] and (not session or STATE.dek is None):
            return self._json(401, {"error": "Accesso richiesto.", "login": True})
        req = Request(method, u.path, parse_qs(u.query), self.headers, body, session)
        conn = db.connect() if opt["db"] else None
        try:
            if conn is None:
                res = fn(req, conn, *mt.groups())
            elif opt["write"]:
                with db.tx(conn):
                    res = fn(req, conn, *mt.groups())
                    if opt["reassess"] and STATE.dek is not None:
                        from .services import consistency
                        consistency.reassess_all(conn)
            else:
                res = fn(req, conn, *mt.groups())
        except AppError as ex:
            payload = {"error": ex.message}
            if ex.field:
                payload["field"] = ex.field
            if ex.extra is not None:
                payload["detail"] = ex.extra
            return self._json(ex.status, payload)
        except Exception as ex:
            tb = traceback.extract_tb(ex.__traceback__)
            where = f"{tb[-1].filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{tb[-1].lineno}" if tb else "?"
            log.error("Errore interno %s in %s (%s)", type(ex).__name__, where, u.path.split("/")[2])
            return self._json(500, {"error": f"Errore imprevisto ({type(ex).__name__}). Nessuna modifica parziale "
                                             f"è stata salvata. Se si ripete, annotare l'ora e contattare "
                                             f"l'assistenza."})
        finally:
            if conn is not None:
                conn.close()
        if isinstance(res, FileResponse):
            disp = "inline" if res.inline else "attachment"
            extra = {"Cache-Control": "no-store"}
            if res.filename:
                extra["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(res.filename)}"
            return self._send(200, res.data, res.ctype, extra)
        if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict) and "_cookie" in res[1]:
            obj, meta = res
            return self._json(200, obj, {"Set-Cookie": meta["_cookie"]})
        return self._json(200, res if res is not None else {"ok": True})


def session_cookie(token: str | None) -> str:
    if token is None:
        return "gsid=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
    return f"gsid={token}; Path=/; HttpOnly; SameSite=Strict"


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def make_server(port: int | None = None) -> Server:
    """Prova la porta preferita; se occupata ne usa una libera. Sempre e solo 127.0.0.1."""
    from . import api  # noqa: F401  registra le rotte
    candidates = [port] if port else [config.PREFERRED_PORT, config.PREFERRED_PORT + 1, 0]
    last = None
    for p in candidates:
        try:
            srv = Server(("127.0.0.1", p), Handler)
            STATE.port = srv.server_address[1]
            return srv
        except OSError as ex:
            last = ex
    raise RuntimeError(f"Nessuna porta locale disponibile: {last}")


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0
