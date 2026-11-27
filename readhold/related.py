"""Connections: what belongs together across the pages.

- `related`: for a document, a study file, a quest, a glossary term or a note, the notes that link to it and
  the open tasks that point at it. Every page that shows one of these can show the same "Connected" card.
- `day`: one day seen from every side (tasks done, focused minutes, routines, the journal page, the day's note),
  shown beside a daily note and on the journal page.
- `week`: the tasks and routines of the last seven days, for the weekly review on the Stamina page.

It only reads. Nothing here writes or leaves this machine.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from fastapi import FastAPI, HTTPException

from . import pages, planner
from .db import DB

Kind = Literal["document", "lecture", "quest", "term", "page"]
TABLES = {"document": ("documents", "title"), "lecture": ("lectures", "title"), "quest": ("quests", "title"), "page": ("pages", "title")}
ID = re.compile(r"[0-9a-f]{32}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def related(db: DB, kind: str, oid: str = "", title: str = "") -> dict:
    if kind == "term":  # a term is known by its word: the same word can be saved from several documents
        title = " ".join(title.split())
        if not title or not db.one("SELECT 1 FROM terms WHERE deleted=0 AND lower(term)=? LIMIT 1", (title.lower(),)):
            raise HTTPException(404, "not found")
    else:
        table, col = TABLES[kind]
        row = db.one(f"SELECT {col} AS title FROM {table} WHERE id=? AND deleted=0", (oid,)) if ID.fullmatch(oid or "") else None
        if not row:
            raise HTTPException(404, "not found")
        title = row["title"]
    k = pages.key(title)
    rows = db.all(
        "SELECT p.id, p.title, p.body, p.daily FROM page_links l JOIN pages p ON p.id=l.from_id"
        " WHERE l.target=? AND l.deleted=0 AND p.deleted=0 AND p.id!=? ORDER BY p.updated_at DESC LIMIT 30", (k, oid))
    notes = [{"id": r["id"], "title": r["title"], "daily": r["daily"], "context": pages._line_with(r["body"], f"[[{k}")} for r in rows]
    mentions: list[dict] = []
    if kind == "term" and len(k) >= 3:  # terms are often written without brackets
        linked = {r["id"] for r in rows}
        for r in db.all("SELECT id, title, body, daily FROM pages WHERE deleted=0 AND lower(body) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT 20", (_like(k),)):
            plain = pages.LINK.sub("", r["body"])
            if r["id"] not in linked and k in plain.casefold():
                mentions.append({"id": r["id"], "title": r["title"], "daily": r["daily"], "context": pages._line_with(plain, k)})
    if kind == "quest":
        tasks = db.all(
            "SELECT t.id, t.text, t.due, t.minutes FROM todos t JOIN quest_steps s ON s.id=t.link_id"
            " WHERE t.link_type='step' AND s.quest_id=? AND s.deleted=0 AND t.deleted=0 AND t.done_at IS NULL ORDER BY t.ord LIMIT 30", (oid,))
    elif kind == "term":
        tasks = []
    else:
        tasks = db.all("SELECT id, text, due, minutes FROM todos WHERE link_type=? AND link_id=? AND deleted=0 AND done_at IS NULL ORDER BY ord LIMIT 30", (kind, oid))
    return {"kind": kind, "id": oid, "title": title, "notes": notes, "mentions": mentions[:8], "tasks": tasks}


def day(db: DB, day_iso: str) -> dict:
    from .services import _local_date

    d = dt.date.fromisoformat(day_iso)
    lo = (dt.datetime.combine(d, dt.time()) - dt.timedelta(days=1)).isoformat()
    hi = (dt.datetime.combine(d, dt.time()) + dt.timedelta(days=2)).isoformat()
    done = [r["text"] for r in db.all("SELECT text, done_at FROM todos WHERE deleted=0 AND done_at>=? AND done_at<? ORDER BY done_at", (lo, hi)) if _local_date(r["done_at"]) == d]
    focused = sum(r["focused_ms"] or 0 for r in db.all("SELECT started_at, focused_ms FROM sessions WHERE deleted=0 AND started_at>=? AND started_at<?", (lo, hi))
                  if _local_date(r["started_at"]) == d)
    journal = db.one("SELECT weather, body FROM journal_entries WHERE day=? AND deleted=0", (day_iso,))
    note = db.one("SELECT id FROM pages WHERE daily=? AND deleted=0 ORDER BY created_at LIMIT 1", (day_iso,))
    return {
        "day": day_iso,
        "tasks_done": done[:40],
        "focus_min": round(focused / 60_000),
        "routine_steps": db.scalar("SELECT COUNT(*) FROM routine_checks WHERE day=? AND deleted=0", (day_iso,)) or 0,
        "journal": {"weather": journal["weather"], "written": bool(journal["body"].strip())} if journal and (journal["weather"] or journal["body"].strip()) else None,
        "note_id": note["id"] if note else None,
    }


def week(db: DB) -> dict:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    rows = db.all("SELECT area FROM todos WHERE deleted=0 AND done_at>=?", (since,))
    areas: dict[str, int] = {}
    for r in rows:
        if r["area"]:
            areas[r["area"]] = areas.get(r["area"], 0) + 1
    routines = []
    for r in planner.routines(db):
        on = [x for x in r["days"] if not x["off"]]
        routines.append({"title": r["title"], "days": sum(1 for x in on if x["part"] > 0), "of": len(on)})
    return {
        "tasks_done": len(rows),
        "areas": [{"area": a, "n": n} for a, n in sorted(areas.items(), key=lambda x: (-x[1], x[0]))[:5]],
        "open": db.scalar("SELECT COUNT(*) FROM todos WHERE deleted=0 AND done_at IS NULL") or 0,
        "routines": routines,
    }


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/related")
    def api_related(kind: Kind, id: str = "", title: str = ""):
        return related(db, kind, id, title)

    @app.get("/api/day/{day_iso}")
    def api_day(day_iso: str):
        if not DAY.fullmatch(day_iso):
            raise HTTPException(404, "not found")
        try:
            return day(db, day_iso)
        except ValueError:
            raise HTTPException(404, "not found") from None

    @app.get("/api/week/plan")
    def api_week_plan():
        return week(db)
