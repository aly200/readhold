"""Delete on everything (milestone 5.1 of docs/ai/PLAN.md, Phase 5): every kind of record you make, and every single
AI result, can be removed from the app, with Undo.

- `DELETE /api/items/{kind}/{id}` is a soft delete (`deleted=1`); `POST /api/items/{kind}/{id}/restore` is its Undo.
- `kind` comes from the fixed list below, which names the table. A table name never comes from the request.
- The id must be a record id (32 hex characters). An unknown id, or a record that is already deleted, is a 404.
  Restoring a record that is not deleted changes nothing (a second Undo click is harmless).
- What hangs on a record goes and comes back with it:
  - card: also marked `suspended`, which means "you took it out of review". Editing what the card came from (a term,
    a question) updates its text but does not bring it back (`services.upsert_card`); only Undo does. A card that was
    removed with its source (not by you) is not restored here.
  - journal: the drawing on that day's page goes and comes back with it. Writing that day's page again later reuses
    the same row (one page per day); a late Undo then changes nothing, so it never overwrites what you wrote since.
  - focus: the run's session row (Stamina, the streak, the journal's day story) and the minutes it added to its
    to-do go and come back with it. A run that is still active cannot be deleted: stop it first.
  - quest: its questions, steps and map stay as they are and come back with it. A restored goal that was the main
    one is parked if another goal became the main one meanwhile (one main goal at a time).
  - map_edge: restored only while both concepts are there and the link makes no loop.
  - ai_result: restored only while what it was about (a document, a note page, an idea) is still there.
    "Clear AI history" deletes results for good: those cannot be restored.
Exports and stats read `deleted=0` rows only, so a deleted record leaves them too.
"""
from __future__ import annotations

import json
import re

from fastapi import FastAPI, HTTPException

from .db import DB, now

ID = re.compile(r"[0-9a-f]{32}")

KINDS: dict[str, str] = {  # kind -> table; nothing else is ever a table name here
    "card": "cards",
    "habit": "habits",
    "quest": "quests",
    "map_edge": "map_edges",
    "journal": "journal_entries",
    "letter": "letters",
    "side_quest": "side_quests",
    "checkin": "checkins",
    "focus": "timer_runs",
    "ai_result": "ai_results",
}
AI_TARGETS = {"document": "documents", "page": "pages", "idea": "ideas"}  # what an AI result can be about, and must still be there


def _row(db: DB, kind: str, rid: str) -> tuple[str, dict]:
    """The table of this kind and the record, deleted or not; 404 for an unknown kind or id."""
    table = KINDS.get(kind)
    if not table or not ID.fullmatch(rid or ""):
        raise HTTPException(404, "not found")
    row = db.one(f"SELECT * FROM {table} WHERE id=?", (rid,))
    if not row:
        raise HTTPException(404, "not found")
    return table, row


def delete(db: DB, kind: str, rid: str) -> dict:
    table, row = _row(db, kind, rid)
    if row["deleted"]:
        raise HTTPException(404, "not found")
    if kind == "focus" and row["status"] == "active":
        raise HTTPException(409, "This timer is still running. Stop it first, then delete it.")
    t = now()
    with db.transaction():
        c = db.conn
        c.execute(f"UPDATE {table} SET deleted=1, updated_at=?, device_id=? WHERE id=?", (t, db.device, rid))
        if kind == "card":
            c.execute("UPDATE cards SET suspended=1 WHERE id=?", (rid,))
        elif kind == "journal":
            c.execute("UPDATE ink SET deleted=1, updated_at=?, device_id=? WHERE owner_type='journal' AND owner_id=? AND deleted=0", (t, db.device, row["day"]))
        elif kind == "focus":
            if row["session_id"]:
                c.execute("UPDATE sessions SET deleted=1, updated_at=?, device_id=? WHERE id=?", (t, db.device, row["session_id"]))
            if row["todo_id"] and row["kind"] != "break":  # the minutes it added to its to-do
                c.execute("UPDATE todos SET spent_ms=MAX(0, spent_ms-?), updated_at=?, device_id=? WHERE id=?", (row["elapsed_ms"], t, db.device, row["todo_id"]))
    return {"ok": True, "kind": kind, "id": rid}


def restore(db: DB, kind: str, rid: str) -> dict:
    table, row = _row(db, kind, rid)
    out: dict = {"ok": True, "kind": kind, "id": rid}
    if row["deleted"]:
        _check_restore(db, kind, row)
        t = now()
        with db.transaction():
            c = db.conn
            c.execute(f"UPDATE {table} SET deleted=0, updated_at=?, device_id=? WHERE id=?", (t, db.device, rid))
            if kind == "card":
                c.execute("UPDATE cards SET suspended=0 WHERE id=?", (rid,))
            elif kind == "journal":
                c.execute("UPDATE ink SET deleted=0, updated_at=?, device_id=? WHERE owner_type='journal' AND owner_id=? AND deleted=1", (t, db.device, row["day"]))
            elif kind == "focus":
                if row["session_id"]:
                    c.execute("UPDATE sessions SET deleted=0, updated_at=?, device_id=? WHERE id=?", (t, db.device, row["session_id"]))
                if row["todo_id"] and row["kind"] != "break":
                    c.execute("UPDATE todos SET spent_ms=spent_ms+?, updated_at=?, device_id=? WHERE id=?", (row["elapsed_ms"], t, db.device, row["todo_id"]))
            elif kind == "quest" and row["status"] == "active":
                other = c.execute("SELECT 1 FROM quests WHERE status='active' AND deleted=0 AND id!=?", (rid,)).fetchone()
                if other:
                    c.execute("UPDATE quests SET status='parked' WHERE id=?", (rid,))
    if kind == "journal":
        entry = db.one("SELECT * FROM journal_entries WHERE id=?", (rid,))
        try:
            entry["prompts"] = json.loads(entry["prompts"] or "[]")
        except ValueError:
            entry["prompts"] = []
        out["entry"] = entry
    return out


def _check_restore(db: DB, kind: str, row: dict) -> None:
    """What a restored record needs to make sense again; a 404 or 409 when it is gone."""
    if kind == "card" and not row["suspended"]:
        raise HTTPException(404, "This card went with what it came from. Restore that instead.")
    if kind == "map_edge":
        from .growth import _creates_cycle

        live = db.scalar("SELECT COUNT(*) FROM map_nodes WHERE id IN (?, ?) AND quest_id=? AND deleted=0", (row["from_id"], row["to_id"], row["quest_id"]))
        if live != 2 or not db.one("SELECT 1 FROM quests WHERE id=? AND deleted=0", (row["quest_id"],)):
            raise HTTPException(404, "One of its concepts is gone.")
        if db.one("SELECT 1 FROM map_edges WHERE from_id=? AND to_id=? AND deleted=0", (row["from_id"], row["to_id"])):
            raise HTTPException(409, "That link is already there.")
        if _creates_cycle(db, row["quest_id"], row["from_id"], row["to_id"]):
            raise HTTPException(409, "That would make a loop: one of them already needs the other.")
    if kind == "ai_result":
        target = AI_TARGETS.get(row["target_type"])
        if target and not db.one(f"SELECT 1 FROM {target} WHERE id=? AND deleted=0", (row["target_id"],)):
            raise HTTPException(404, "What it was about is no longer here.")


def register(app: FastAPI, db: DB) -> None:
    @app.delete("/api/items/{kind}/{rid}")
    def api_item_delete(kind: str, rid: str):
        return delete(db, kind, rid)

    @app.post("/api/items/{kind}/{rid}/restore")
    def api_item_restore(kind: str, rid: str):
        return restore(db, kind, rid)
