"""Avvio: istanza singola, migrazione con backup preventivo, server locale, finestra di controllo.

Uso: AvviaGestionale.exe            (normale: finestra di controllo + browser)
     AvviaGestionale.exe --headless --port 0 --no-browser   (collaudo automatico)
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import threading
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler

from . import config, db
from .state import STATE

log = logging.getLogger("gestionale")


def setup_logging() -> None:
    h = RotatingFileHandler(config.data_dir() / "log" / "gestionale.log", maxBytes=1_000_000, backupCount=3,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for noisy in ("RapidOCR", "rapidocr", "onnxruntime", "PIL"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


class SingleInstance:
    def __init__(self) -> None:
        self.path = config.data_dir() / "gestionale.lock"
        self.fh = None

    def acquire(self) -> bool:
        self.fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False

    def release(self) -> None:
        if self.fh:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.fh.close()
            self.fh = None


PRE_MIGRATION_KEEP_DAYS = 30


def migrate_with_backup() -> str | None:
    """Prima di aggiornare lo schema crea una copia di sicurezza verificata; se l'aggiornamento fallisce la ripristina.

    Restituisce il nome della copia creata (None se non serviva). Le copie pre-migrazione non sono cifrate (la chiave
    non è disponibile prima dell'accesso, come per il database): si eliminano dopo PRE_MIGRATION_KEEP_DAYS giorni.
    """
    p = config.db_path()
    _purge_old_premigration()
    from .services import backup as _bk
    _bk.purge_old_safety_copies()
    if not (p.exists() and p.stat().st_size > 0):
        db.init_db()
        return None
    c = sqlite3.connect(str(p))
    ver = c.execute("PRAGMA user_version").fetchone()[0]
    c.close()
    if ver > db.SCHEMA_VERSION:
        raise db.DatabaseTooNew("archivio di una versione più recente")
    if ver >= db.SCHEMA_VERSION or ver < 1:
        db.init_db()
        return None
    stamp = datetime.now(config.TZ).strftime("%Y%m%d_%H%M%S")
    copy = config.data_dir() / "backup" / f"pre_migrazione_v{ver}_{stamp}.sqlite3"
    src, dst = sqlite3.connect(str(p)), sqlite3.connect(str(copy))
    src.backup(dst)
    dst.close()
    src.close()
    c = sqlite3.connect(str(copy))
    ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and \
        c.execute("PRAGMA user_version").fetchone()[0] == ver
    c.close()
    if not ok:
        copy.unlink(missing_ok=True)
        raise RuntimeError("copia pre-migrazione non verificabile: aggiornamento non eseguito")
    try:
        db.init_db()
        c = sqlite3.connect(str(p))
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.close()
        if not ok:
            raise RuntimeError("integrità")
        log.info("Migrazione schema v%s -> v%s riuscita; copia %s", ver, db.SCHEMA_VERSION, copy.name)
        return copy.name
    except Exception:
        log.error("Migrazione non riuscita: ripristino della copia %s", copy.name)
        for extra in ("-wal", "-shm"):  # file del giornale riferiti al database non ripristinato
            p.with_name(p.name + extra).unlink(missing_ok=True)
        shutil.copyfile(copy, p)
        raise


def _purge_old_premigration() -> None:
    import time
    limit = time.time() - PRE_MIGRATION_KEEP_DAYS * 86400
    for f in (config.data_dir() / "backup").glob("pre_migrazione_v*.sqlite3"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def backup_on_exit() -> None:
    if STATE.dek is None:
        return
    try:
        from .services import backup
        c = db.connect()
        try:
            backup.create_local(c, "chiusura")
        finally:
            c.close()
    except Exception as ex:
        log.error("Backup alla chiusura non riuscito: %s", type(ex).__name__)


def control_window(url: str, stop) -> None:
    import tkinter as tk
    from tkinter import ttk
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    root.title(config.APP_NAME)
    root.minsize(460, 220)
    frm = ttk.Frame(root, padding=16)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Il gestionale è attivo su questo computer.", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    ttk.Label(frm, text=f"Indirizzo locale: {url}", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
    ttk.Label(frm, text=f"Cartella dati: {config.data_dir()}", font=("Segoe UI", 9), wraplength=520).pack(
        anchor="w", pady=(2, 0))
    if config.portable_mode():
        ttk.Label(frm, text="MODALITÀ PORTATILE: i dati sono sulla chiavetta. Non rimuoverla mentre il "
                            "programma è aperto.", foreground="#9a3412", wraplength=520).pack(anchor="w", pady=4)
    row = ttk.Frame(frm)
    row.pack(anchor="w", pady=(14, 0))
    ttk.Button(row, text="Apri il gestionale", command=lambda: webbrowser.open(url)).pack(side="left")
    ttk.Button(row, text="Apri cartella dati", command=lambda: os.startfile(str(config.data_dir()))
               if os.name == "nt" else None).pack(side="left", padx=8)

    def close():
        lbl.config(text="Salvataggio e backup in corso…")
        root.update()
        stop()
        root.destroy()
    ttk.Button(row, text="Chiudi il gestionale", command=close).pack(side="left")
    lbl = ttk.Label(frm, text="Chiudendo questa finestra il gestionale si ferma (con backup automatico).",
                    font=("Segoe UI", 9))
    lbl.pack(anchor="w", pady=(12, 0))
    root.protocol("WM_DELETE_WINDOW", close)
    req = threading.Event()  # richiesta di chiusura dall'interfaccia web (altro thread): Tk la legge dal suo thread
    STATE.shutdown_cb = req.set

    def poll():
        if req.is_set():
            close()
        else:
            root.after(300, poll)
    root.after(300, poll)
    root.mainloop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        config.data_dir()
    except OSError as ex:
        _fatal(f"La cartella dati non è scrivibile ({ex.strerror}).\nCopiare il programma in una cartella del "
               f"proprio utente (es. Documenti) e riprovare.")
        return 2
    setup_logging()
    inst = SingleInstance()
    port_file = config.data_dir() / "gestionale.port"
    if not inst.acquire():
        # Istanza già attiva: si riapre la stessa, senza avviare un secondo server sullo stesso archivio.
        log.info("Seconda istanza: già in esecuzione")
        try:
            port = int(port_file.read_text())
            if not args.no_browser:
                webbrowser.open(f"http://127.0.0.1:{port}/")
        except (OSError, ValueError):
            if not args.headless:
                _fatal("Il gestionale risulta già aperto.")
        return 3
    try:
        migrate_with_backup()
        from .server import make_server
        srv = make_server(args.port)
        port_file.write_text(str(STATE.port))
        url = f"http://127.0.0.1:{STATE.port}/"
        log.info("Avvio versione %s su porta %s", config.VERSION, STATE.port)
        if sys.stdout:  # assente nell'eseguibile senza console
            print(f"PRONTO {url}", flush=True)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        stopped = threading.Event()
        stopping = threading.Lock()

        def stop():
            if not stopping.acquire(blocking=False):
                return
            try:
                backup_on_exit()      # prima di fermare il server e di uscire
                srv.shutdown()
                STATE.lock_app()
            finally:
                stopped.set()

        if not args.no_browser:
            webbrowser.open(url)
        if args.headless:
            STATE.shutdown_cb = lambda: threading.Thread(target=stop, daemon=True).start()
            try:
                while not stopped.wait(0.5):
                    pass
            except KeyboardInterrupt:
                stop()
        else:
            control_window(url, stop)
            stop()
        srv.server_close()
        log.info("Chiusura ordinata")
        return 0
    except db.DatabaseTooNew:
        log.error("Archivio creato da una versione più recente del programma")
        _fatal("L'archivio dei dati è stato creato da una versione PIÙ RECENTE del gestionale.\n"
               "Per non danneggiarlo questa versione non lo apre: usare la versione più recente del programma.\n"
               f"Cartella dati: {config.data_dir()}")
        return 1
    except Exception as ex:
        log.exception("Errore all'avvio: %s", type(ex).__name__)
        _fatal(f"Errore all'avvio ({type(ex).__name__}). I dati non sono stati modificati.\n"
               f"Cartella dati: {config.data_dir()}")
        return 1
    finally:
        if inst.fh is not None:  # solo l'istanza che possiede l'archivio rimuove i propri file di stato
            port_file.unlink(missing_ok=True)
            inst.release()


def _fatal(msg: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, config.APP_NAME, 0x10)
    except Exception:
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
