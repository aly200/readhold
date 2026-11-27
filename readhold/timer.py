"""Timer: a calm focus/break timer and a stopwatch, plus a to-do list whose tasks you can time.

- One timer at a time. Its state lives in the database (elapsed time + when it was last resumed), so a
  reload picks it up exactly where it was. The open app sends a heartbeat every 15 s; if Readhold was closed
  (no heartbeat for QUIET_MS), the timer comes back paused at its last saved time, so hours away never count
  as focus.
- A focus run is also a session row, so it counts in Stamina, the streak and the journal's day story.
- A to-do can link to a quest step, a library document or a lecture/notebook. Finishing a to-do that
  links to a step also finishes the step. Time spent with the timer adds up on the to-do.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .bodies import Body
from .compass import checkin_today, need_row
from .db import DB, now

ID = re.compile(r"[0-9a-f]{32}")
LinkType = Literal["", "step", "document", "lecture", "page"]  # page = one of your notes
MAX_MINUTES = 600
QUIET_MS = 150_000  # no heartbeat for this long: the app was closed or asleep
DAY = r"\d{4}-\d{2}-\d{2}"
REPEAT = r"^(|daily|weekdays|weekly|monthly|every:([2-9]|[1-9]\d{1,2}))$"  # every:N = every N days
AT = r"^(|([01]\d|2[0-3]):[0-5]\d)$"  # a time of day, or none


def _day(value: str | None) -> str | None:
    """A real calendar day (YYYY-MM-DD), or 422."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(422, "That day does not exist.") from None


def next_due(due: str | None, rule: str, today: dt.date | None = None) -> str | None:
    """The next day of a repeating task: always after today, however late the last one was done."""
    if not rule:
        return None
    today = today or dt.date.today()
    day = dt.date.fromisoformat(due) if due else today
    anchor = day.day
    while True:
        if rule == "daily":
            day += dt.timedelta(days=1)
        elif rule.startswith("every:"):
            day += dt.timedelta(days=int(rule[6:]))
        elif rule == "weekdays":
            day += dt.timedelta(days=1)
            while day.weekday() >= 5:
                day += dt.timedelta(days=1)
        elif rule == "weekly":
            day += dt.timedelta(days=7)
        else:  # monthly: the same day number, or the month's last day
            year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
            last = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)).day
            day = dt.date(year, month, min(anchor, last))
        if day > today:
            return day.isoformat()


def _check_id(value: str) -> str:
    if not ID.fullmatch(value or ""):
        raise HTTPException(404, "not found")
    return value


def _ms_since(iso: str | None) -> int:
    if not iso:
        return 0
    delta = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)
    return max(0, int(delta.total_seconds() * 1000))


def run_out(run: dict | None) -> dict | None:
    """The run as the front end needs it: elapsed time counted up to this moment."""
    if not run:
        return None
    return {**run, "elapsed_now_ms": run["elapsed_ms"] + _ms_since(run["running_since"]), "running": bool(run["running_since"])}


def run_view(db: DB, run: dict | None) -> dict | None:
    """What the page gets for a run (the same as run_out; kept as the one name the routes use)."""
    return run_out(run)


def _link_ok(db: DB, link_type: str, link_id: str) -> None:
    if not link_type:
        return
    table = {"step": "quest_steps", "document": "documents", "lecture": "lectures", "page": "pages"}[link_type]
    if not ID.fullmatch(link_id or "") or not db.one(f"SELECT 1 FROM {table} WHERE id=? AND deleted=0", (link_id,)):
        raise HTTPException(422, "That link points to something that no longer exists.")


class TodoIn(Body):
    text: str = Field(..., min_length=1, max_length=500)
    minutes: int = Field(25, ge=1, le=MAX_MINUTES)
    link_type: LinkType = ""
    link_id: str = Field("", max_length=32)
    due: str | None = Field(None, pattern=DAY)  # the day it is for (none = anytime)
    repeat_rule: str = Field("", pattern=REPEAT)
    at: str = Field("", pattern=AT)  # a time of day ("14:30"), or none
    area: str = Field("", max_length=40)  # a life area: Study, Home, Health...
    note: str = Field("", max_length=2000)
    priority: int = Field(0, ge=0, le=1)  # 1 = this one matters


class TodoPatch(Body):
    text: str | None = Field(None, min_length=1, max_length=500)
    minutes: int | None = Field(None, ge=1, le=MAX_MINUTES)
    done: bool | None = None
    ord: float | None = None
    link_type: LinkType | None = None
    link_id: str | None = Field(None, max_length=32)
    due: str | None = Field(None, pattern=DAY)
    clear_due: bool = False  # back to "anytime"
    repeat_rule: str | None = Field(None, pattern=REPEAT)
    at: str | None = Field(None, pattern=AT)
    area: str | None = Field(None, max_length=40)
    note: str | None = Field(None, max_length=2000)
    priority: int | None = Field(None, ge=0, le=1)


class ItemIn(Body):
    text: str = Field(..., min_length=1, max_length=200)


class ItemPatch(Body):
    text: str | None = Field(None, min_length=1, max_length=200)
    done: bool | None = None


MAX_ITEMS = 20


def todo_items(db: DB, todo_ids: list[str]) -> dict[str, list[dict]]:
    """The small checklists of these tasks, by task id."""
    out: dict[str, list[dict]] = {t: [] for t in todo_ids}
    for i in range(0, len(todo_ids), 400):
        chunk = todo_ids[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in db.all(f"SELECT id, todo_id, text, done FROM todo_items WHERE deleted=0 AND todo_id IN ({marks}) ORDER BY ord, created_at", chunk):
            out[r["todo_id"]].append({"id": r["id"], "text": r["text"], "done": bool(r["done"])})
    return out


def todo_out(db: DB, todo: dict) -> dict:
    return {**todo, "items": todo_items(db, [todo["id"]])[todo["id"]]}


class StartIn(BaseModel):
    kind: Literal["focus", "break", "stopwatch"]
    minutes: int = Field(25, ge=1, le=MAX_MINUTES)
    label: str = Field("", max_length=300)
    todo_id: str | None = None
    link_type: LinkType = ""
    link_id: str = Field("", max_length=32)


class ElapsedIn(BaseModel):
    elapsed_ms: int = Field(..., ge=0, le=24 * 3600 * 1000)


class FinishIn(ElapsedIn):
    status: Literal["done", "stopped"] = "done"
    feel: Literal["", "energized", "neutral", "drained"] = ""
    output: str = Field("", max_length=500)


def current_run(db: DB) -> dict | None:
    run = db.one("SELECT * FROM timer_runs WHERE status='active' AND deleted=0 ORDER BY started_at DESC LIMIT 1")
    if run and run["running_since"] and _ms_since(run["updated_at"]) > QUIET_MS:
        # Readhold was closed (or the computer slept) while it ran: keep the time up to the last heartbeat, paused
        db.update("timer_runs", run["id"], {"running_since": None})
        run = db.one("SELECT * FROM timer_runs WHERE id=?", (run["id"],))
        run["was_quiet"] = True
    return run


def _sync_session(db: DB, run: dict, elapsed: int, end: bool = False, feel: str = "", output: str = "") -> None:
    if not run.get("session_id"):
        return
    fields: dict = {"focused_ms": elapsed, "longest_run_ms": elapsed}
    if end:
        fields["ended_at"] = now()
        if feel:
            fields["feel"] = feel
        if output:
            fields["output"] = output
    db.update("sessions", run["session_id"], fields)


def finish_run(db: DB, run: dict, elapsed: int, status: str = "stopped", feel: str = "", output: str = "") -> dict:
    """End a run: record its time on the session and on its to-do."""
    elapsed = max(elapsed, run["elapsed_ms"])
    db.update("timer_runs", run["id"], {"elapsed_ms": elapsed, "running_since": None, "status": status, "ended_at": now()})
    _sync_session(db, run, elapsed, end=True, feel=feel, output=output)
    if run.get("todo_id") and run["kind"] != "break":
        db.execute("UPDATE todos SET spent_ms=spent_ms+?, updated_at=?, device_id=? WHERE id=?", (elapsed, now(), db.device, run["todo_id"]))
    return {**run, "elapsed_ms": elapsed, "status": status}


def _today_summary(db: DB) -> dict:
    from .services import _local_date

    today = dt.date.today()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    focus = 0
    runs = 0
    for r in db.all("SELECT kind, elapsed_ms, started_at FROM timer_runs WHERE status!='active' AND started_at>=? AND deleted=0", (since,)):
        if r["kind"] != "break" and _local_date(r["started_at"]) == today:
            focus += r["elapsed_ms"]
            runs += 1
    done = sum(1 for t in db.all("SELECT done_at FROM todos WHERE done_at IS NOT NULL AND deleted=0 AND done_at>=?", (since,))
               if _local_date(t["done_at"]) == today)
    return {"focus_ms": focus, "runs": runs, "todos_done": done}


def list_todos(db: DB) -> list[dict]:
    """Open to-dos for now (anytime, today or carried over), then the ones finished today. Later days wait in Plan."""
    from .services import _local_date

    today = dt.date.today()
    rows = db.all("SELECT * FROM todos WHERE deleted=0 AND (done_at IS NULL OR done_at>=?) ORDER BY done_at IS NOT NULL, ord, created_at",
                  ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat(),))
    day = today.isoformat()
    return [r for r in rows if (r["done_at"] is None and (not r["due"] or r["due"] <= day)) or (r["done_at"] and _local_date(r["done_at"]) == today)]


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/timer")
    def api_timer():
        return {"run": run_view(db, current_run(db)), "todos": list_todos(db), "today": _today_summary(db)}

    @app.get("/api/timer/recent")
    def api_timer_recent():
        """Your finished focus runs and stopwatches of the last two weeks (breaks are not listed), so you can remove one."""
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).isoformat()
        return db.all(
            "SELECT id, kind, label, elapsed_ms, status, started_at, ended_at, link_type, link_id FROM timer_runs"
            " WHERE deleted=0 AND status!='active' AND kind!='break' AND started_at>=? ORDER BY started_at DESC, rowid DESC LIMIT 20",
            (since,),
        )

    @app.get("/api/timer/links")
    def api_timer_links():
        """Things a to-do or a timer can be linked to: open steps of the active quest, lectures and notebooks, documents."""
        steps = db.all(
            "SELECT s.id, s.title FROM quest_steps s JOIN quests q ON q.id=s.quest_id"
            " WHERE q.status='active' AND q.deleted=0 AND s.deleted=0 AND s.done_at IS NULL ORDER BY s.ord LIMIT 50"
        )
        lectures = db.all("SELECT id, title, kind FROM lectures WHERE deleted=0 ORDER BY updated_at DESC LIMIT 50")
        documents = db.all("SELECT id, title FROM documents WHERE deleted=0 ORDER BY updated_at DESC LIMIT 50")
        return {"steps": steps, "lectures": lectures, "documents": documents}

    @app.post("/api/timer/start")
    def api_timer_start(body: StartIn):
        old = current_run(db)
        if old:  # one timer at a time: the old one is stopped and its time kept
            finish_run(db, old, old["elapsed_ms"] + _ms_since(old["running_since"]))
        link_type, link_id = body.link_type, body.link_id
        todo = None
        if body.todo_id:
            todo = need_row(db, "todos", _check_id(body.todo_id))
            if not link_type and todo["link_type"]:
                link_type, link_id = todo["link_type"], todo["link_id"]
        _link_ok(db, link_type, link_id)
        label = body.label.strip() or (todo["text"] if todo else {"focus": "Focus", "break": "Break", "stopwatch": "Stopwatch"}[body.kind])
        session_id = None
        if body.kind != "break":
            checkin = checkin_today(db)
            step_quest = db.scalar("SELECT quest_id FROM quest_steps WHERE id=?", (link_id,)) if link_type == "step" else None
            session = db.insert("sessions", {
                "document_id": link_id if link_type == "document" else None,
                "started_at": now(), "energy": checkin["energy"] if checkin else "medium",
                "time_box_min": body.minutes if body.kind == "focus" else 0,
                "question": label[:300], "step_id": link_id if link_type == "step" else None, "quest_id": step_quest,
            })
            session_id = session["id"]
        run = db.insert("timer_runs", {
            "kind": body.kind, "label": label[:300], "planned_ms": body.minutes * 60_000 if body.kind != "stopwatch" else 0,
            "elapsed_ms": 0, "running_since": now(), "status": "active", "todo_id": todo["id"] if todo else None,
            "session_id": session_id, "link_type": link_type, "link_id": link_id, "started_at": now(),
        })
        return run_view(db, run)

    def active(rid: str) -> dict:
        run = need_row(db, "timer_runs", _check_id(rid))
        if run["status"] != "active":
            raise HTTPException(409, "This timer has already ended.")
        return run

    @app.post("/api/timer/{rid}/pause")
    def api_timer_pause(rid: str, body: ElapsedIn):
        run = active(rid)
        elapsed = max(body.elapsed_ms, run["elapsed_ms"])
        db.update("timer_runs", rid, {"elapsed_ms": elapsed, "running_since": None})
        _sync_session(db, run, elapsed)
        return run_view(db, need_row(db, "timer_runs", rid))

    @app.post("/api/timer/{rid}/resume")
    def api_timer_resume(rid: str):
        run = active(rid)
        if not run["running_since"]:
            db.update("timer_runs", rid, {"running_since": now()})
        return run_view(db, need_row(db, "timer_runs", rid))

    @app.post("/api/timer/{rid}/beat")
    def api_timer_beat(rid: str, body: ElapsedIn):
        """Heartbeat while running: keeps the session's focused time current (and survives a crash)."""
        run = active(rid)
        elapsed = max(body.elapsed_ms, run["elapsed_ms"])
        if run["running_since"]:  # rebase: the saved time is now this heartbeat's
            db.update("timer_runs", rid, {"elapsed_ms": elapsed, "running_since": now()})
        _sync_session(db, run, elapsed)
        return {"ok": True}

    @app.post("/api/timer/{rid}/extend")
    def api_timer_extend(rid: str, minutes: int = 5):
        run = active(rid)
        if not 1 <= minutes <= 120 or run["kind"] == "stopwatch":
            raise HTTPException(422, "Add between 1 and 120 minutes to a countdown.")
        db.update("timer_runs", rid, {"planned_ms": run["planned_ms"] + minutes * 60_000})
        return run_view(db, need_row(db, "timer_runs", rid))

    @app.post("/api/timer/{rid}/finish")
    def api_timer_finish(rid: str, body: FinishIn):
        run = active(rid)
        finish_run(db, run, body.elapsed_ms, body.status, body.feel, body.output.strip())
        return {"ok": True, "today": _today_summary(db), "todos": list_todos(db)}

    # ---- to-dos
    @app.get("/api/todos/timed")
    def api_todos_timed():
        """Today's open tasks that have a time, for the reminders while the app is open."""
        return {"today": dt.date.today().isoformat(),
                "tasks": db.all("SELECT id, text, at, minutes FROM todos WHERE deleted=0 AND done_at IS NULL AND at!='' AND due=? ORDER BY at", (dt.date.today().isoformat(),))}

    @app.post("/api/todos")
    def api_todo_create(body: TodoIn):
        _link_ok(db, body.link_type, body.link_id)
        top = db.scalar("SELECT MAX(ord) FROM todos WHERE deleted=0 AND done_at IS NULL") or 0
        due = _day(body.due) or (dt.date.today().isoformat() if body.repeat_rule else None)  # a repeating task needs a first day
        row = db.insert("todos", {**body.model_dump(), "text": body.text.strip(), "area": body.area.strip(), "due": due, "ord": top + 1})
        return todo_out(db, need_row(db, "todos", row["id"]))

    @app.patch("/api/todos/{tid}")
    def api_todo_patch(tid: str, body: TodoPatch):
        todo = need_row(db, "todos", _check_id(tid))
        fields = body.model_dump(exclude_none=True)
        done = fields.pop("done", None)
        if "due" in fields:
            fields["due"] = _day(fields["due"])
        if fields.pop("clear_due", False):
            fields["due"] = None
        if "area" in fields:
            fields["area"] = fields["area"].strip()
        if "link_type" in fields or "link_id" in fields:
            lt = fields.get("link_type", todo["link_type"])
            li = fields.get("link_id", todo["link_id"]) if lt else ""
            _link_ok(db, lt, li)
            fields["link_type"], fields["link_id"] = lt, li
        if done is True and not todo["done_at"]:
            fields["done_at"] = now()
            if todo["link_type"] == "step":  # finishing the to-do finishes the quest step it stands for
                db.execute("UPDATE quest_steps SET done_at=?, output=CASE WHEN output='' THEN ? ELSE output END, updated_at=?, device_id=?"
                           " WHERE id=? AND done_at IS NULL", (now(), f"Done: {todo['text'][:200]}", now(), db.device, todo["link_id"]))
            rule = fields.get("repeat_rule", todo["repeat_rule"])
            if rule:  # a repeating task: the next one is ready as soon as this one is done
                top = db.scalar("SELECT MAX(ord) FROM todos WHERE deleted=0 AND done_at IS NULL") or 0
                nxt = db.insert("todos", {"text": todo["text"], "minutes": todo["minutes"], "link_type": todo["link_type"] if todo["link_type"] != "step" else "",
                                         "link_id": todo["link_id"] if todo["link_type"] != "step" else "", "area": fields.get("area", todo["area"]),
                                         "note": fields.get("note", todo["note"]), "repeat_rule": rule, "priority": fields.get("priority", todo["priority"]), "at": fields.get("at", todo["at"]),
                                         "due": next_due(fields.get("due", todo["due"]), rule), "ord": top + 1})
                fields["next_id"] = nxt["id"]
                for n, it in enumerate(todo_items(db, [tid])[tid]):  # its checklist starts again, unticked
                    db.insert("todo_items", {"todo_id": nxt["id"], "text": it["text"], "ord": float(n)})
        elif done is False:
            fields["done_at"] = None
            if todo["next_id"]:  # not done after all: take back the next one, unless you already worked on it
                db.execute("UPDATE todos SET deleted=1, updated_at=?, device_id=? WHERE id=? AND done_at IS NULL AND spent_ms=0", (now(), db.device, todo["next_id"]))
                fields["next_id"] = None
        if fields:
            db.update("todos", tid, fields)
        return todo_out(db, need_row(db, "todos", tid))

    # ---- the small checklist inside a task
    def item(tid: str, iid: str) -> dict:
        row = db.one("SELECT * FROM todo_items WHERE id=? AND todo_id=? AND deleted=0", (_check_id(iid), _check_id(tid)))
        if not row:
            raise HTTPException(404, "not found")
        return row

    @app.post("/api/todos/{tid}/items")
    def api_item_create(tid: str, body: ItemIn):
        todo = need_row(db, "todos", _check_id(tid))
        if db.scalar("SELECT COUNT(*) FROM todo_items WHERE todo_id=? AND deleted=0", (tid,)) >= MAX_ITEMS:
            raise HTTPException(409, f"A task holds up to {MAX_ITEMS} small steps. A bigger job is better as two tasks.")
        top = db.scalar("SELECT MAX(ord) FROM todo_items WHERE todo_id=? AND deleted=0", (tid,)) or 0
        db.insert("todo_items", {"todo_id": tid, "text": body.text.strip(), "ord": top + 1})
        return todo_out(db, todo)

    @app.patch("/api/todos/{tid}/items/{iid}")
    def api_item_patch(tid: str, iid: str, body: ItemPatch):
        item(tid, iid)
        fields: dict = {}
        if body.text is not None:
            fields["text"] = body.text.strip()
        if body.done is not None:
            fields["done"] = int(body.done)
        if fields:
            db.update("todo_items", iid, fields)
        return todo_out(db, need_row(db, "todos", tid))

    @app.delete("/api/todos/{tid}/items/{iid}")
    def api_item_delete(tid: str, iid: str):
        item(tid, iid)
        db.soft_delete("todo_items", iid)
        return todo_out(db, need_row(db, "todos", tid))

    @app.delete("/api/todos/{tid}")
    def api_todo_delete(tid: str):
        need_row(db, "todos", _check_id(tid))
        db.soft_delete("todos", tid)
        return {"ok": True}

    @app.post("/api/todos/{tid}/restore")
    def api_todo_restore(tid: str):
        if not db.one("SELECT 1 FROM todos WHERE id=?", (_check_id(tid),)):
            raise HTTPException(404, "not found")
        db.update("todos", tid, {"deleted": 0})
        return need_row(db, "todos", tid)
