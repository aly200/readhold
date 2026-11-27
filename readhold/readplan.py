"""Reading plan: what is left to read, spread over the days before you must finish (milestone 3.1 of docs/ai/PLAN.md).

This is the plan without a model, and the half of it that code always does, also with AI on (ADR 008: code
handles scheduling and dates). You choose the documents, their order and how hard each one is; code works out
the rest:
- `remaining`  what is left of a document from where you are: its visible sections and their words;
- `minutes`    reading time at your pace (`wpm`), times the level (easy, medium, hard), rounded up;
- `schedule`   fills each reading day, in your order, up to your minutes a day and never past the day you must
               finish by (that day included). Days off are skipped; reading-plan tasks already on a day count
               against it. A section that does not fit is continued the next day; less than MIN_PIECE minutes
               left in a day is left free rather than filled with a two-minute task (with fewer minutes a day
               than MIN_PIECE, a whole day's time is the smallest piece). What does not fit is named,
               never squeezed in, with the minutes a day it would take.
- `apply`      adds the plan to Plan as tasks on their days (each opens its document), under one batch id;
- `undo`       takes the batch back: every task of it you have not finished or timed.

With AI on, a model may suggest the order and the levels (`ai/plan.py`); you see it, use it or not, and this
module schedules it the same way. A task made from the model's order says so in its note.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import threading
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .db import DB, new_id

ID = re.compile(r"[0-9a-f]{32}")
LEVELS = {"easy": 0.8, "medium": 1.0, "hard": 1.4}
Level = Literal["easy", "medium", "hard"]
MIN_PIECE = 10  # minutes: less room than this left in a day (with more to read) starts the next piece tomorrow
MAX_DOCS = 20
MAX_DAYS = 366
MAX_PER_DAY = 600  # a task's longest time (timer.MAX_MINUTES)
UNDO_DAYS = 14  # how long "Undo the last plan" is offered after a reload


class Invalid(Exception):
    pass


class Changed(Exception):
    """The plan to add is not the one the page showed (something changed in between): 409, look again."""


_apply_lock = threading.Lock()  # two applies at once would each see the other's days as free


def minutes(words: int, wpm: int, level: str = "medium") -> int:
    wpm = max(60, min(1200, int(wpm or 250)))
    return max(1, math.ceil(words / wpm * LEVELS.get(level, 1.0) - 1e-9)) if words > 0 else 0


# ------------------------------------------------------------------ what is left
def remaining(db: DB, doc_id: str) -> dict | None:
    """A live document and what is left of it from where you are: its visible sections (skipped ones aside), with
    the words of the sentences from your position on. None for a document that is not there."""
    doc = db.one("SELECT id, title, why, deadline, status, position, source FROM documents WHERE id=? AND deleted=0", (doc_id,)) if ID.fullmatch(doc_id or "") else None
    if not doc:
        return None
    at = doc["position"] or 0
    rows = [] if doc["status"] == "finished" else db.all(
        "SELECT c.id, c.title, MIN(s.ord) AS sentence, COALESCE(SUM(s.words), 0) AS words FROM sections c"
        " JOIN paragraphs p ON p.section_id=c.id AND p.deleted=0 JOIN sentences s ON s.paragraph_id=p.id AND s.deleted=0"
        " WHERE c.document_id=? AND c.deleted=0 AND c.hidden=0 AND s.ord>=? GROUP BY c.id ORDER BY c.ord", (doc_id, at))
    sections = [{"id": r["id"], "title": " ".join((r["title"] or "").split()) or "Start", "sentence": r["sentence"], "words": r["words"]} for r in rows if r["words"] > 0]
    return {**doc, "sections": sections, "words_left": sum(s["words"] for s in sections)}


def parts(left: dict, wpm: int, level: str) -> list[dict]:
    """The sections as pieces of reading time. The document's minutes are shared out over its sections by their words,
    so thirty short sections do not each round up to a minute; a section too short to get a minute joins the next."""
    total = minutes(left["words_left"], wpm, level)
    if not total:
        return []
    out: list[dict] = []
    done_words, given, pending = 0, 0, None
    for s in left["sections"]:
        done_words += s["words"]
        end = round(done_words / left["words_left"] * total)
        m = end - given
        if pending is None:
            pending = {"title": s["title"], "last": s["title"], "sentence": s["sentence"], "minutes": 0}
        pending["last"] = s["title"]
        pending["minutes"] += m
        given = end
        if pending["minutes"] > 0:
            out.append(pending)
            pending = None
    if pending is not None:  # short sections at the end: they belong with the last piece
        if out:
            out[-1]["last"] = pending["last"]
            out[-1]["minutes"] += pending["minutes"]
        else:
            out.append({**pending, "minutes": max(1, pending["minutes"])})
    return out


# ------------------------------------------------------------------ the schedule
def reading_days(start: dt.date, deadline: dt.date, days_off: set[int] | frozenset = frozenset()) -> list[dt.date]:
    if deadline < start:
        raise Invalid("That deadline has passed. Choose a day from today on.")
    if (deadline - start).days >= MAX_DAYS:
        raise Invalid("Choose a deadline within a year.")
    days = [start + dt.timedelta(days=i) for i in range((deadline - start).days + 1)]
    days = [d for d in days if d.weekday() not in days_off]
    if not days:
        raise Invalid("There is no reading day before the deadline: every day left is a day off.")
    return days


def _fill(docs: list[dict], days: list[dt.date], room: list[int], smallest: int = MIN_PIECE) -> tuple[list[list[dict]], list[dict]]:
    """`smallest`: the shortest piece worth starting (less with fewer minutes a day than MIN_PIECE)."""
    plan: list[list[dict]] = [[] for _ in days]
    used = [0] * len(days)
    unplaced: dict[str, dict] = {}
    i = 0
    for doc in docs:
        for p in doc["parts"]:
            left, first = p["minutes"], True
            while left > 0:
                while i < len(days):
                    free = room[i] - used[i]
                    if free > 0 and (free >= smallest or free >= left):
                        break
                    i += 1
                if i >= len(days):
                    u = unplaced.setdefault(doc["id"], {"document_id": doc["id"], "title": doc["title"], "minutes": 0, "from": p["title"]})
                    u["minutes"] += left
                    break
                take = min(left, room[i] - used[i])
                items = plan[i]
                last = items[-1] if items else None
                if last and last["document_id"] == doc["id"]:  # the same document on the same day is one task
                    last["minutes"] += take
                    last["to"] = p.get("last", p["title"])
                else:
                    items.append({"document_id": doc["id"], "title": doc["title"], "minutes": take, "from": p["title"], "to": p.get("last", p["title"]),
                                  "sentence": p["sentence"], "continued": not first})
                used[i] += take
                left -= take
                first = False
    return plan, list(unplaced.values())


def schedule(docs: list[dict], start: dt.date, deadline: dt.date, per_day: int, days_off: set[int] | frozenset = frozenset(),
             busy: dict[str, int] | None = None) -> dict:
    """The day-by-day plan. `docs` in reading order, each {"id", "title", "parts": [{"title", "sentence", "minutes"}]}.
    `busy`: minutes already planned per day ("YYYY-MM-DD"). Two promises, checked by tests: no day holds more than
    `per_day` with what is already planned, and no reading lies outside start..deadline or on a day off."""
    busy = busy or {}
    days = reading_days(start, deadline, days_off)

    def run(limit: int):
        return _fill(docs, days, [max(0, limit - busy.get(d.isoformat(), 0)) for d in days], min(MIN_PIECE, limit))

    plan, unplaced = run(per_day)
    total = sum(p["minutes"] for d in docs for p in d["parts"])
    need = None
    if unplaced:  # the fewest minutes a day that would fit, found by the same scheduler
        lo, hi = per_day + 1, MAX_PER_DAY
        if not run(hi)[1]:
            while lo < hi:
                mid = (lo + hi) // 2
                if run(mid)[1]:
                    lo = mid + 1
                else:
                    hi = mid
            need = lo
    last = max((k for k, items in enumerate(plan) if items), default=-1)
    out_days = [{"day": d.isoformat(), "items": plan[k], "minutes": sum(x["minutes"] for x in plan[k]), "busy": busy.get(d.isoformat(), 0),
                 "room": max(0, per_day - busy.get(d.isoformat(), 0))} for k, d in enumerate(days[:last + 1])]
    return {"days": out_days, "unplaced": unplaced, "fits": not unplaced, "total": total, "need_per_day": need,
            "start": start.isoformat(), "deadline": deadline.isoformat(), "per_day": per_day, "reading_days": len(days)}


# ------------------------------------------------------------------ from the request to a plan
class DocIn(BaseModel):
    id: str = Field(..., max_length=40)
    level: Level = "medium"


class PlanIn(BaseModel):
    documents: list[DocIn] = Field(..., min_length=1, max_length=MAX_DOCS)
    deadline: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")  # the last day to read on (it is included)
    minutes_per_day: int = Field(..., ge=5, le=MAX_PER_DAY)
    days_off: str = Field("", pattern=r"^[0-6]{0,7}$")  # weekdays without reading (0 = Monday); not all seven (`_days_off`)
    goal: str = Field("", max_length=200)
    from_ai: str = Field("", max_length=40)  # the AI suggestion this order came from, if any
    expect: str = Field("", max_length=64)  # apply: the `key` of the preview the page showed; another plan is refused


def _days_off(value: str) -> set[int]:
    off = {int(c) for c in value}
    if len(off) == 7:
        raise Invalid("Leave at least one day of the week for reading.")
    return off


def busy_minutes(db: DB, start: dt.date, deadline: dt.date) -> dict[str, int]:
    """Minutes of reading-plan tasks on each day, so a second plan does not book the same time twice. Counted on the
    safe side: every live plan task on its day, done or not, at its minutes or the time spent on it if more; an open
    one whose day has passed counts on today (it is on today's list), and so does one finished today."""
    from .services import _local_date

    out: dict[str, int] = {}
    first = start.isoformat()
    for t in db.all("SELECT due, minutes, spent_ms, done_at FROM todos WHERE deleted=0 AND plan_batch!='' AND plan_batch NOT LIKE 'chat:%' AND due IS NOT NULL AND due<=?",
                    (deadline.isoformat(),)):
        day = t["due"]
        if day < first:
            if t["done_at"] is None or _local_date(t["done_at"]) == start:
                day = first
            else:
                continue
        out[day] = out.get(day, 0) + max(t["minutes"], t["spent_ms"] // 60_000)
    return out


def plan_key(plan: dict) -> str:
    """What the page showed, as one hash: the days and what is on them, and what does not fit."""
    shown = {"days": [[d["day"], [[i["document_id"], i["minutes"], i["from"], i["to"]] for i in d["items"]]] for d in plan["days"]],
             "unplaced": [[u["document_id"], u["minutes"]] for u in plan["unplaced"]]}
    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode()).hexdigest()


def build(db: DB, body: PlanIn, wpm: int, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    try:
        deadline = dt.date.fromisoformat(body.deadline)
    except ValueError:
        raise Invalid("That day does not exist.") from None
    off = _days_off(body.days_off)
    reading_days(today, deadline, off)  # refuse a past deadline before reading anything
    docs, seen, done = [], set(), []
    for d in body.documents:
        if d.id in seen:
            continue
        seen.add(d.id)
        left = remaining(db, d.id)
        if left is None:
            raise LookupError(d.id)
        ps = parts(left, wpm, d.level)
        if not ps:
            done.append(left["title"])
            continue
        docs.append({"id": d.id, "title": " ".join(left["title"].split()) or "Untitled", "level": d.level, "parts": ps})
    plan = schedule(docs, today, deadline, body.minutes_per_day, off, busy_minutes(db, today, deadline))
    out = {**plan, "nothing_left": done, "wpm": wpm, "levels": {d["id"]: d["level"] for d in docs}}
    out["key"] = plan_key(out)
    return out


def _task_text(item: dict) -> str:
    span = item["from"] if item["to"] == item["from"] else f"{item['from']} → {item['to']}"
    text = f"Read “{item['title']}”: {span}" + (" (continued)" if item["continued"] else "")
    return text if len(text) <= 500 else text[:499] + "…"


def _ai_order(db: DB, body: PlanIn) -> dict:
    """The suggestion the order came from. It must still be the model's order: the documents in its order (those it
    found nothing left in aside) and its levels where it gave one. Otherwise the tasks would wrongly say so."""
    row = db.one("SELECT id, payload FROM ai_results WHERE id=? AND feature='plan' AND deleted=0", (body.from_ai,)) if ID.fullmatch(body.from_ai) else None
    if not row:
        raise LookupError(body.from_ai)
    try:
        order = [o for o in json.loads(row["payload"])["order"] if not o.get("nothing_left")]
    except (ValueError, KeyError, TypeError):
        raise LookupError(body.from_ai) from None
    want = list(dict.fromkeys(d.id for d in body.documents))
    levels = {d.id: d.level for d in body.documents}
    if want != [o["document_id"] for o in order] or any(o.get("level_from_model") and levels.get(o["document_id"]) != o["level"] for o in order):
        raise Changed("This is no longer the order the model suggested. Add it without the label, or use the suggestion again.")
    return row


def apply(db: DB, body: PlanIn, wpm: int) -> dict:
    with _apply_lock:  # build and insert as one step: a second apply sees the first one's tasks as busy time
        return _apply(db, body, wpm)


def _apply(db: DB, body: PlanIn, wpm: int) -> dict:
    ai_row = _ai_order(db, body) if body.from_ai else None
    plan = build(db, body, wpm)
    if body.expect and body.expect != plan["key"]:
        raise Changed("The plan changed since it was shown (your tasks or documents moved on). Look at it again, then add it.")
    if not any(d["items"] for d in plan["days"]):
        raise Invalid("There is nothing to add: no reading fits in this plan.")
    batch = new_id()
    goal = " ".join(body.goal.split())
    note = f"From your reading plan{f' for “{goal}”' if goal else ''}: finish by {plan['deadline']}."
    if ai_row:
        note += " The order and levels were suggested by the AI model; check that they suit you."
    added = 0
    with db.transaction():
        top = db.scalar("SELECT MAX(ord) FROM todos WHERE deleted=0") or 0
        for day in plan["days"]:
            for item in day["items"]:
                added += 1
                db.insert("todos", {"text": _task_text(item), "minutes": max(1, min(MAX_PER_DAY, item["minutes"])), "ord": top + added,
                                    "link_type": "document", "link_id": item["document_id"], "due": day["day"], "note": note, "plan_batch": batch})
        if ai_row:
            db.update("ai_results", ai_row["id"], {"status": "accepted"})
    return {"batch": batch, "added": added, "plan": plan}


_UNTOUCHED = ("done_at IS NULL AND spent_ms=0 AND updated_at=created_at"
              " AND NOT EXISTS (SELECT 1 FROM todo_items i WHERE i.todo_id=todos.id AND i.deleted=0)")


def undo(db: DB, batch: str) -> dict:
    """Take a plan back: its tasks as the plan made them go. A task you finished, timed, edited, moved or gave small
    steps is yours now and stays."""
    if not ID.fullmatch(batch or "") or not db.one("SELECT 1 FROM todos WHERE plan_batch=? LIMIT 1", (batch,)):
        raise LookupError(batch)
    with db.transaction():
        live = db.scalar("SELECT COUNT(*) FROM todos WHERE plan_batch=? AND deleted=0", (batch,)) or 0
        ids = [r["id"] for r in db.all(f"SELECT id FROM todos WHERE plan_batch=? AND deleted=0 AND {_UNTOUCHED}", (batch,))]
        for i in ids:
            db.soft_delete("todos", i)
    return {"removed": len(ids), "kept": live - len(ids)}


def last_batch(db: DB) -> dict | None:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=UNDO_DAYS)).isoformat()
    row = db.one(f"SELECT plan_batch, COUNT(*) AS n, MAX(created_at) AS at FROM todos WHERE plan_batch!='' AND plan_batch NOT LIKE 'chat:%' AND deleted=0 AND {_UNTOUCHED}"
                 " AND created_at>=? GROUP BY plan_batch ORDER BY at DESC LIMIT 1", (since,))
    return {"id": row["plan_batch"], "open": row["n"], "created_at": row["at"]} if row else None


def candidates(db: DB, wpm: int) -> list[dict]:
    out = []
    for d in db.all("SELECT id FROM documents WHERE deleted=0 AND status!='finished' ORDER BY deadline IS NULL, deadline, updated_at DESC LIMIT 200"):
        left = remaining(db, d["id"])
        if not left or not left["words_left"]:
            continue
        out.append({"id": left["id"], "title": left["title"], "why": left["why"] or "", "deadline": left["deadline"], "status": left["status"],
                    "words_left": left["words_left"], "minutes_left": minutes(left["words_left"], wpm), "sections_left": len(left["sections"])})
    return out


# ------------------------------------------------------------------ routes
def register(app: FastAPI, db: DB, settings: Callable[[], dict]) -> None:
    def wpm() -> int:
        return int(settings().get("wpm") or 250)

    def run(fn):
        try:
            return fn()
        except LookupError:
            raise HTTPException(404, "That document or suggestion is not in your library.") from None
        except Invalid as e:
            raise HTTPException(422, str(e)) from None
        except Changed as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/api/reading-plan")
    def api_reading_plan():
        w = wpm()
        return {"documents": candidates(db, w), "wpm": w, "today": dt.date.today().isoformat(), "last_batch": last_batch(db), "levels": LEVELS,
                "min_piece": MIN_PIECE}

    @app.post("/api/reading-plan/preview")
    def api_reading_plan_preview(body: PlanIn):
        return run(lambda: build(db, body, wpm()))

    @app.post("/api/reading-plan/apply")
    def api_reading_plan_apply(body: PlanIn):
        return run(lambda: apply(db, body, wpm()))

    @app.post("/api/reading-plan/{batch}/undo")
    def api_reading_plan_undo(batch: str):
        return run(lambda: undo(db, batch))

