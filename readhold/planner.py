"""Plan: tasks for today and later, and the small routines of a day.

- Tasks are the to-dos of the Timer page with a few more fields: a day (`due`), a repeat rule, a life area and
  a note. A task without a day is "anytime". A task whose day has passed is carried over, never marked late.
- Finishing a repeating task makes its next one (see `timer.next_due`).
- A routine is a short ordered checklist for the morning, the day or the evening. Its checks belong to a day,
  so it starts fresh every morning. The last seven days are kept as a gentle picture, not a streak to protect.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .bodies import Body
from .compass import need_row
from .db import DB
from .timer import _check_id, todo_items

Slot = Literal["morning", "day", "evening"]
SLOT_ORDER = {"morning": 0, "day": 1, "evening": 2}
MAX_STEPS = 30
MAX_ROUTINES = 12


class StepIn(Body):
    text: str = Field(..., min_length=1, max_length=200)
    minutes: int = Field(0, ge=0, le=240)


WEEKDAYS = r"^[0-6]{0,7}$"  # empty = every day; else the days it is for (0 = Monday)


class RoutineIn(Body):
    title: str = Field(..., min_length=1, max_length=120)
    slot: Slot = "morning"
    weekdays: str = Field("", pattern=WEEKDAYS)
    steps: list[StepIn] = Field(default_factory=list, max_length=MAX_STEPS)


class RoutinePatch(Body):
    title: str | None = Field(None, min_length=1, max_length=120)
    slot: Slot | None = None
    weekdays: str | None = Field(None, pattern=WEEKDAYS)
    steps: list[StepIn] | None = Field(None, max_length=MAX_STEPS)


class CheckIn(BaseModel):
    done: bool = True


def routine_out(db: DB, routine: dict, today: dt.date | None = None) -> dict:
    """A routine with its steps, what is done today, and how the last seven days went (0..1 per day)."""
    today = today or dt.date.today()
    steps = db.all("SELECT id, text, minutes FROM routine_steps WHERE routine_id=? AND deleted=0 ORDER BY ord, created_at", (routine["id"],))
    ids = {s["id"] for s in steps}
    since = (today - dt.timedelta(days=6)).isoformat()
    per_day: dict[str, set[str]] = {}
    for c in db.all("SELECT step_id, day FROM routine_checks WHERE routine_id=? AND deleted=0 AND day>=?", (routine["id"], since)):
        if c["step_id"] in ids:
            per_day.setdefault(c["day"], set()).add(c["step_id"])
    done_today = per_day.get(today.isoformat(), set())
    on = _weekdays(routine.get("weekdays") or "")
    days = []
    for i in range(6, -1, -1):
        d = today - dt.timedelta(days=i)
        day = d.isoformat()
        days.append({"day": day, "part": round(len(per_day.get(day, ())) / len(steps), 2) if steps else 0, "off": bool(on) and d.weekday() not in on})
    next_on = ""
    if on and today.weekday() not in on:
        next_on = next((today + dt.timedelta(days=n)).isoformat() for n in range(1, 8) if (today + dt.timedelta(days=n)).weekday() in on)
    return {
        "id": routine["id"], "title": routine["title"], "slot": routine["slot"], "ord": routine["ord"],
        "weekdays": "".join(str(d) for d in sorted(on)), "on_today": not on or today.weekday() in on, "next_on": next_on,
        "steps": [{**s, "done": s["id"] in done_today} for s in steps],
        "done": len(done_today), "days": days,
    }


def _weekdays(value: str) -> set[int]:
    days = {int(c) for c in value if c.isdigit() and int(c) <= 6}
    return set() if len(days) == 7 else days


def routines(db: DB) -> list[dict]:
    rows = db.all("SELECT * FROM routines WHERE deleted=0 ORDER BY ord, created_at")
    rows.sort(key=lambda r: SLOT_ORDER.get(r["slot"], 1))
    today = dt.date.today()
    return [routine_out(db, r, today) for r in rows]


def _set_steps(db: DB, routine_id: str, steps: list[StepIn]) -> None:
    """Replace the steps. A step whose words did not change keeps its id, so its history stays."""
    old = db.all("SELECT id, text FROM routine_steps WHERE routine_id=? AND deleted=0 ORDER BY ord, created_at", (routine_id,))
    by_text: dict[str, list[str]] = {}
    for o in old:
        by_text.setdefault(o["text"], []).append(o["id"])
    kept: set[str] = set()
    for i, step in enumerate(steps):
        text = step.text.strip()
        if not text:
            continue
        same = by_text.get(text)
        if same:
            sid = same.pop(0)
            kept.add(sid)
            db.update("routine_steps", sid, {"minutes": step.minutes, "ord": float(i)})
        else:
            db.insert("routine_steps", {"routine_id": routine_id, "text": text, "minutes": step.minutes, "ord": float(i)})
    for o in old:
        if o["id"] not in kept:
            db.soft_delete("routine_steps", o["id"])


def plan(db: DB) -> dict:
    from .services import _local_date

    today = dt.date.today()
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    rows = db.all("SELECT * FROM todos WHERE deleted=0 AND (done_at IS NULL OR done_at>=?) ORDER BY done_at IS NOT NULL, ord, created_at", (recent,))
    tasks = [r for r in rows if r["done_at"] is None or _local_date(r["done_at"]) == today]
    areas = [r["area"] for r in db.all("SELECT area, COUNT(*) AS n FROM todos WHERE deleted=0 AND area!='' GROUP BY area ORDER BY n DESC, area LIMIT 20")]
    items = todo_items(db, [t["id"] for t in tasks])
    tasks = [{**t, "items": items[t["id"]]} for t in tasks]
    week = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    return {
        "today": today.isoformat(),
        "tasks": tasks,
        "quest_step": _quest_step(db),
        "review_due": db.scalar("SELECT COUNT(*) FROM cards WHERE deleted=0 AND suspended=0 AND due<=?", (dt.datetime.now(dt.timezone.utc).isoformat(),)) or 0,
        "areas": areas,
        "routines": routines(db),
        "done_week": db.scalar("SELECT COUNT(*) FROM todos WHERE deleted=0 AND done_at>=?", (week,)),
    }


def _quest_step(db: DB) -> dict | None:
    """The next step of the quest you are on, so Plan shows everything for today in one place."""
    from .compass import active_quest, lead_step

    quest = active_quest(db)
    if not quest:
        return None
    step = lead_step(db.all("SELECT * FROM quest_steps WHERE quest_id=? AND deleted=0 ORDER BY ord, created_at", (quest["id"],)))
    if not step:
        return None
    in_plan = db.scalar("SELECT COUNT(*) FROM todos WHERE deleted=0 AND done_at IS NULL AND link_type='step' AND link_id=?", (step["id"],))
    return {"id": step["id"], "title": step["title"], "minutes": step["minutes"], "quest_id": quest["id"], "quest_title": quest["title"], "in_plan": bool(in_plan)}


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/plan")
    def api_plan():
        return plan(db)

    def routine(rid: str) -> dict:
        return need_row(db, "routines", _check_id(rid))

    @app.post("/api/routines")
    def api_routine_create(body: RoutineIn):
        if db.scalar("SELECT COUNT(*) FROM routines WHERE deleted=0") >= MAX_ROUTINES:
            raise HTTPException(409, f"You have {MAX_ROUTINES} routines. A few that you keep beat many that you skip.")
        top = db.scalar("SELECT MAX(ord) FROM routines WHERE deleted=0") or 0
        row = db.insert("routines", {"title": body.title.strip(), "slot": body.slot, "weekdays": "".join(str(d) for d in sorted(_weekdays(body.weekdays))), "ord": top + 1})
        _set_steps(db, row["id"], body.steps)
        return routine_out(db, routine(row["id"]))

    @app.patch("/api/routines/{rid}")
    def api_routine_patch(rid: str, body: RoutinePatch):
        routine(rid)
        fields = {k: v for k, v in {"title": body.title.strip() if body.title else None, "slot": body.slot}.items() if v is not None}
        if body.weekdays is not None:
            fields["weekdays"] = "".join(str(d) for d in sorted(_weekdays(body.weekdays)))
        if fields:
            db.update("routines", rid, fields)
        if body.steps is not None:
            _set_steps(db, rid, body.steps)
        return routine_out(db, routine(rid))

    @app.delete("/api/routines/{rid}")
    def api_routine_delete(rid: str):
        routine(rid)
        db.soft_delete("routines", rid)
        return {"ok": True}

    @app.post("/api/routines/{rid}/restore")
    def api_routine_restore(rid: str):
        if not db.one("SELECT 1 FROM routines WHERE id=?", (_check_id(rid),)):
            raise HTTPException(404, "not found")
        db.update("routines", rid, {"deleted": 0})
        return routine_out(db, routine(rid))

    @app.post("/api/routines/{rid}/steps/{sid}/check")
    def api_routine_check(rid: str, sid: str, body: CheckIn):
        """Tick (or untick) one step for today."""
        r = routine(rid)
        step = db.one("SELECT id FROM routine_steps WHERE id=? AND routine_id=? AND deleted=0", (_check_id(sid), rid))
        if not step:
            raise HTTPException(404, "not found")
        day = dt.date.today().isoformat()
        have = db.one("SELECT id FROM routine_checks WHERE step_id=? AND day=? AND deleted=0", (sid, day))
        if body.done and not have:
            db.insert("routine_checks", {"routine_id": rid, "step_id": sid, "day": day})
        elif not body.done and have:
            db.soft_delete("routine_checks", have["id"])
        return routine_out(db, r)
