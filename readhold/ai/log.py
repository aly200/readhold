"""The AI log: what was asked of a model, by which task, and how it went (table `ai_log`).

It stores a hash and a short preview of the input and the output, with secrets removed, and in `checks` the list of
sources a call was sent: their anchors (ids and positions), trust and size, never their text ("Why did it say
this?", milestone 4.2). It never stores a key and never the whole text. Rows are deleted after 30 days, or 7 or 1 if you choose
(`ai_log_days`, milestone 4.4); "Clear AI history" empties it at once.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time

from .. import redact
from ..db import DB

RETENTION_DAYS = 30  # the longest; the setting `ai_log_days` can make it 7 or 1 (milestone 4.4)
PREVIEW = 200  # characters kept of the input and of the output
SHOWN = ("id", "task", "provider", "model", "prompt_version", "input_hash", "input_preview", "output_preview",
         "latency_ms", "tokens_in", "tokens_out", "attempts", "checks", "outcome", "error", "created_at")


def digest(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def preview(text: str) -> str:
    """The first characters of a text on one line, with secrets removed."""
    return " ".join(redact.clean(text[: PREVIEW * 4]).split())[:PREVIEW]


_purged_at = 0.0


def write(db: DB, **row) -> str:
    global _purged_at
    if time.monotonic() - _purged_at > 3600:  # the 30-day rule also holds while the app stays open for days
        _purged_at = time.monotonic()
        purge(db)
    return db.insert("ai_log", row)["id"]


def recent(db: DB, limit: int = 50) -> list[dict]:
    cols = ", ".join(SHOWN)
    return db.all(f"SELECT {cols} FROM ai_log WHERE deleted=0 ORDER BY created_at DESC, rowid DESC LIMIT ?", (max(1, min(limit, 200)),))


def count(db: DB) -> int:
    return db.scalar("SELECT COUNT(*) FROM ai_log WHERE deleted=0") or 0


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds")


def _today_start() -> str:
    """Local midnight, as the UTC text the rows are stamped with."""
    return _iso(dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0))


def tokens_today(db: DB, provider: str) -> int:
    """Tokens used with this provider since local midnight. Cleared rows still count: clearing the history
    does not hand the day's budget back."""
    return db.scalar(
        "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) FROM ai_log WHERE provider=? AND created_at>=?",
        (provider, _today_start()),
    ) or 0


def days(db: DB) -> int:
    """How long lines are kept: the setting `ai_log_days` (1, 7 or 30), at most RETENTION_DAYS."""
    try:
        value = json.loads(db.scalar("SELECT value FROM settings WHERE key='ai_log_days'") or "null")
    except ValueError:
        value = None
    return value if value in (1, 7, 30) else RETENTION_DAYS


def purge(db: DB) -> int:
    """Delete rows older than the retention period, and cleared rows from before today (they were kept only
    for that day's budget). Returns how many went."""
    cutoff = _iso(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days(db)))
    return db.execute("DELETE FROM ai_log WHERE created_at<? OR (deleted=1 AND created_at<?)", (cutoff, _today_start()))


def clear(db: DB) -> None:
    """Clear AI history. Everything before today is deleted. Today's rows lose all their content and are marked
    deleted; only their token counts stay until tomorrow, so the daily budget still holds."""
    start = _today_start()
    with db.transaction():
        db.conn.execute("DELETE FROM ai_log WHERE created_at<?", (start,))
        db.conn.execute(
            "UPDATE ai_log SET input_hash='', input_preview='', output_preview='', error='', checks='{}', deleted=1,"
            " updated_at=?, device_id=? WHERE deleted=0",
            (_iso(dt.datetime.now(dt.timezone.utc)), db.device),
        )
