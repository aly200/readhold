"""Start Readhold: local server on 127.0.0.1 (random port, session token) + a desktop window.

    python -m readhold              desktop window (pywebview / Edge WebView2)
    python -m readhold --browser    open in the default browser instead
    python -m readhold --serve      server only; prints the sign-in URL (for development)
"""
from __future__ import annotations

import argparse
import logging
import secrets
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from . import config
from .db import open_db
from .server import create_app

log = logging.getLogger("readhold")


def bind(port: int = 0) -> socket.socket:
    """The server's socket on 127.0.0.1, bound here and handed to uvicorn: the port is never free in between, so no
    other program on this computer can take it and receive the address with the session token."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="readhold")
    ap.add_argument("--browser", action="store_true", help="open in the default browser instead of a window")
    ap.add_argument("--serve", action="store_true", help="run the server only and print the URL")
    ap.add_argument("--port", type=int, default=0, help="fixed port (default: random)")
    ap.add_argument("--token", default="", help="fixed session token (development only)")
    args = ap.parse_args(argv)

    config.setup_logging()
    sock = bind(args.port)
    port = sock.getsockname()[1]
    token = args.token or secrets.token_urlsafe(32)
    db = open_db()
    app = create_app(db, token, {f"127.0.0.1:{port}", f"localhost:{port}"})
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False, log_config=None)
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    url = f"http://127.0.0.1:{port}/auth?token={token}"
    log.info("Readhold running on 127.0.0.1:%s", port)

    def backups() -> None:
        # the daily backup also happens when the app stays open past midnight
        while True:
            time.sleep(3600)
            try:
                db.daily_backup()
            except Exception:  # noqa: BLE001
                log.exception("Daily backup failed")

    threading.Thread(target=backups, daemon=True, name="daily-backup").start()

    try:
        if args.serve:
            print(f"Readhold is running: {url}", flush=True)
            thread.join()
        elif args.browser:
            webbrowser.open(url)
            print("Readhold is open in your browser. Press Ctrl+C here to stop.", flush=True)
            thread.join()
        else:
            try:
                import webview
            except ImportError:
                webbrowser.open(url)
                thread.join()
                return 0
            from . import winicon

            window = webview.create_window("Readhold", url, width=1360, height=880, min_size=(900, 600), text_select=True)
            window.events.shown += lambda: winicon.apply(window)  # the logo in the title bar and taskbar
            webview.start(private_mode=False)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
