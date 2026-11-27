"""Overview: the state of every feature in one call, for the page that shows them all side by side.

It only reads (the quick actions on that page use each feature's own endpoints), and stays on this machine.
"""
from __future__ import annotations

import datetime as dt

from fastapi import FastAPI

from . import compass, planner, related
from .db import DB

NOW_TASKS = 6


def hub(db: DB) -> dict:
    plan = planner.plan(db)
    today = plan["today"]
    open_tasks = [t for t in plan["tasks"] if not t["done_at"]]
    now = [t for t in open_tasks if t["due"] and t["due"] <= today]  # today's and the carried-over ones
    now.sort(key=lambda t: (-(t["priority"] or 0), t["at"] or "99"))  # the one that matters first, then by time of day
    day = related.day(db, today)
    quest = compass.active_quest(db)
    quest_out = None
    if quest:
        steps = db.all("SELECT done_at FROM quest_steps WHERE quest_id=? AND deleted=0", (quest["id"],))
        quest_out = {"id": quest["id"], "title": quest["title"], "steps": len(steps), "steps_done": sum(1 for s in steps if s["done_at"])}
    from .services import _local_date

    first = dt.date.fromisoformat(today) - dt.timedelta(days=6)
    per_day: dict[str, int] = {}
    for s in db.all("SELECT started_at, focused_ms FROM sessions WHERE deleted=0 AND started_at>=?", ((dt.datetime.combine(first, dt.time()) - dt.timedelta(days=1)).isoformat(),)):
        d = _local_date(s["started_at"]).isoformat()
        per_day[d] = per_day.get(d, 0) + (s["focused_ms"] or 0)
    focus_week = [{"day": (first + dt.timedelta(days=i)).isoformat(), "min": round(per_day.get((first + dt.timedelta(days=i)).isoformat(), 0) / 60_000)} for i in range(7)]
    return {
        "today": today,
        "tasks": [{"id": t["id"], "text": t["text"], "minutes": t["minutes"], "priority": t["priority"], "due": t["due"], "at": t["at"]} for t in now[:NOW_TASKS]],
        "tasks_now": len(now),
        "tasks_open": len(open_tasks),
        "tasks_done_today": len(day["tasks_done"]),
        "done_week": plan["done_week"],
        "quest": quest_out,
        "quest_step": plan["quest_step"],
        "review_due": plan["review_due"],
        "routines": [{"id": r["id"], "title": r["title"], "slot": r["slot"], "done": r["done"], "total": len(r["steps"]),
                      "next": next(({"id": s["id"], "text": s["text"]} for s in r["steps"] if not s["done"]), None)}
                     for r in plan["routines"] if r["on_today"]],
        "focus_min": day["focus_min"],
        "focus_week": focus_week,
        "journal": day["journal"],
        "notes": db.all("SELECT id, title, daily FROM pages WHERE deleted=0 ORDER BY updated_at DESC LIMIT 5"),
        "notes_total": db.scalar("SELECT COUNT(*) FROM pages WHERE deleted=0") or 0,
        "ideas": [{"id": r["id"], "text": " ".join(r["text"].split())[:140]} for r in db.all("SELECT id, text FROM ideas WHERE deleted=0 ORDER BY created_at DESC LIMIT 2")],
        "ideas_total": db.scalar("SELECT COUNT(*) FROM ideas WHERE deleted=0") or 0,
        "documents": db.all("SELECT id, title, status, position, total_sentences FROM documents WHERE deleted=0 AND status!='finished' ORDER BY updated_at DESC LIMIT 3"),
        "documents_total": db.scalar("SELECT COUNT(*) FROM documents WHERE deleted=0") or 0,
        "lectures": db.all("SELECT id, title, kind, position, pages FROM lectures WHERE deleted=0 ORDER BY updated_at DESC LIMIT 3"),
        "lectures_total": db.scalar("SELECT COUNT(*) FROM lectures WHERE deleted=0") or 0,
        "terms_total": db.scalar("SELECT COUNT(DISTINCT lower(term)) FROM terms WHERE deleted=0") or 0,
        "stamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/hub")
    def api_hub():
        return hub(db)
