"""Paths and device identity. Everything lives under READHOLD_HOME (default: the project folder).

The app was called Foothold until 2026-11-26: its folder variable (FOOTHOLD_HOME) still works, and its database
file is moved to the new name the first time it is opened (`db_path`)."""
from __future__ import annotations

import json
import logging
import os
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web" / "static"
THEMES_DIR = PROJECT_ROOT / "themes"

MAX_FILE_BYTES = 50 * 1024 * 1024  # the largest file that can be imported


OLD_NAME = "foothold"  # the app's name until 2026-11-26


def home() -> Path:
    return Path(os.environ.get("READHOLD_HOME") or os.environ.get(OLD_NAME.upper() + "_HOME") or PROJECT_ROOT)


def data_dir() -> Path:
    p = home() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def library_dir() -> Path:
    p = home() / "library"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backups_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def exports_dir() -> Path:
    p = data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    """The database. One left from before the rename (with its -wal and -shm files) is moved to the new name, once;
    when both exist the new one is kept and the old one is left alone."""
    new = data_dir() / "readhold.db"
    old = data_dir() / f"{OLD_NAME}.db"
    if old.exists() and not new.exists():
        for suffix in ("", "-wal", "-shm"):
            src = data_dir() / f"{OLD_NAME}.db{suffix}"
            if src.exists():
                src.rename(data_dir() / f"readhold.db{suffix}")
    return new


def device_id() -> str:
    f = data_dir() / "device.json"
    if f.exists():
        try:
            return json.loads(f.read_text("utf-8"))["device_id"]
        except (ValueError, KeyError):
            pass
    did = uuid.uuid4().hex
    f.write_text(json.dumps({"device_id": did}), "utf-8")
    return did


def setup_logging() -> None:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / "readhold.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    from .redact import RedactingFormatter  # key-shaped strings never reach the file

    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore"):  # the HTTP client of the AI adapters logs every request at INFO
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
