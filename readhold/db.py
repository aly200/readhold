"""SQLite storage: WAL mode, versioned migrations, daily + pre-migration backups."""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from . import config

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
KEEP_DAILY_BACKUPS = 14


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex


class DB:
    """One connection guarded by a lock. Single user, so this is simple and safe."""

    def __init__(self, path: Path, device: str):
        self.path = path
        self.device = device
        self.lock = threading.RLock()
        fresh = not path.exists()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate(fresh)

    # ---------- migrations and backups ----------
    def migrations(self) -> list[tuple[int, Path]]:
        out = []
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            out.append((int(f.name.split("_", 1)[0]), f))
        return out

    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self, fresh: bool) -> None:
        with self.lock:
            current = self.version()
            pending = [(v, f) for v, f in self.migrations() if v > current]
            if not pending:
                return
            if current > 0 and not fresh:
                self.backup(f"pre-migration-v{current}-to-v{pending[-1][0]}")
            for v, f in pending:
                log.info("Applying migration %s", f.name)
                self.conn.execute("BEGIN")
                try:
                    for stmt in _split_sql(f.read_text("utf-8")):
                        self.conn.execute(stmt)
                    self.conn.execute(f"PRAGMA user_version={v}")
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise

    def backup(self, label: str) -> Path:
        target = config.backups_dir() / f"readhold-{label}.db"
        with self.lock:
            dest = sqlite3.connect(str(target))
            try:
                self.conn.backup(dest)
            finally:
                dest.close()
        return target

    def daily_backup(self) -> Path | None:
        today = dt.date.today().isoformat()
        target = config.backups_dir() / f"readhold-daily-{today}.db"
        made = None
        if not target.exists():
            made = self.backup(f"daily-{today}")
        # daily backups from before the rename count too; the oldest go first, by their date
        found = [*config.backups_dir().glob("readhold-daily-*.db"), *config.backups_dir().glob(f"{config.OLD_NAME}-daily-*.db")]
        dailies = sorted(found, key=lambda p: p.stem.rsplit("daily-", 1)[-1])
        for old in dailies[:-KEEP_DAILY_BACKUPS]:
            old.unlink(missing_ok=True)
        return made

    # ---------- query helpers ----------
    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(r) if r else None

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self.lock:
            r = self.conn.execute(sql, tuple(params)).fetchone()
            return r[0] if r else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).rowcount

    def insert(self, table: str, row: dict) -> dict:
        """Insert with sync columns filled in. Returns the full row."""
        t = now()
        row = {"id": new_id(), **row}
        row.setdefault("device_id", self.device)
        row.setdefault("created_at", t)
        row.setdefault("updated_at", t)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.lock:
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
        return row

    def update(self, table: str, row_id: str, fields: dict) -> int:
        if not fields:
            return 0
        fields = {**fields, "updated_at": now(), "device_id": self.device}
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            return self.conn.execute(
                f"UPDATE {table} SET {sets} WHERE id=?", (*fields.values(), row_id)
            ).rowcount

    def soft_delete(self, table: str, row_id: str) -> int:
        return self.update(table, row_id, {"deleted": 1})

    def transaction(self):
        return _Tx(self)


class _Tx:
    def __init__(self, db: DB):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db.lock.release()
        return False


def _split_sql(script: str) -> list[str]:
    """Split a migration file into statements (no triggers/procedures in our migrations)."""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def open_db(path: Path | None = None) -> DB:
    db = DB(path or config.db_path(), config.device_id())
    try:
        db.daily_backup()
    except Exception:  # a backup failure must never block reading
        log.exception("Daily backup failed")
    return db
