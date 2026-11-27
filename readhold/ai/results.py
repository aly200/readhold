"""What AI features produced and showed you: the `ai_results` table, shared by every feature.

A result is kept under an `input_key`, a hash of everything it was made from. The same inputs give the kept
result back without a new call; any change to the inputs makes a new key, so a stale result is never shown.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import threading

from ..db import DB

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


@contextlib.contextmanager
def once(feature: str, input_key: str):
    """Two requests for the same result at the same moment make one model call: the second waits, then finds it kept."""
    name = f"{feature}:{input_key}"
    with _guard:
        lock = _locks.setdefault(name, threading.Lock())
    with lock:
        yield
    with _guard:  # tidy up, but never drop a lock somebody holds or waits for
        if len(_locks) > 500:
            for other in [k for k, v in _locks.items() if not v.locked()]:
                del _locks[other]


def shape(row: dict) -> dict | None:
    """A row as the page gets it. A row whose JSON cannot be read counts as not there."""
    try:
        payload = json.loads(row["payload"])
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return {**payload, "id": row["id"], "created_at": row["created_at"], "prompt_version": row["prompt_version"], "provider": row["provider"],
            "model": row["model"], "log_id": row["log_id"], "saved": row.get("status") == "accepted"}


def find(db: DB, feature: str, target_id: str, input_key: str) -> dict | None:
    row = db.one("SELECT * FROM ai_results WHERE feature=? AND target_id=? AND input_key=? AND deleted=0 ORDER BY created_at DESC, rowid DESC LIMIT 1", (feature, target_id, input_key))
    return shape(row) if row else None


def keep(db: DB, feature: str, target_id: str, input_key: str, payload: dict, prompt_version: str, log_id: str, replaces: str | None = None,
         target_type: str = "document") -> dict:
    reply = db.one("SELECT provider, model FROM ai_log WHERE id=?", (log_id,)) or {"provider": "", "model": ""}
    # the document may have been removed while the model was answering: then the result is kept out of sight too
    gone = target_type == "document" and not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (target_id,))
    row = db.insert("ai_results", {"feature": feature, "target_type": target_type, "target_id": target_id, "input_key": input_key, "deleted": int(gone),
                                   "payload": json.dumps(payload, ensure_ascii=False), "prompt_version": prompt_version,
                                   "provider": reply["provider"], "model": reply["model"], "log_id": log_id})
    if replaces:  # the new one is in first, so there is never a moment with neither
        db.soft_delete("ai_results", replaces)
    return shape(row)


def forget_document(db: DB, doc_id: str) -> None:
    """A removed document takes what was written about it out of sight."""
    db.execute("UPDATE ai_results SET deleted=1 WHERE target_id=? AND deleted=0", (doc_id,))


def clear_all(db: DB) -> int:
    """"Clear AI history": everything a model wrote that Readhold kept is deleted for good. Notes you saved from an
    answer are yours and stay."""
    return db.execute("DELETE FROM ai_results")
