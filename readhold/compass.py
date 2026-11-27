"""Compass: the right thing, at the right energy, in the right way.

One main quest at a time. It names the questions it must answer; steps move those questions forward,
each with a low/medium/high-energy version; one step is the lead (it makes the others easier).
Anything that pulls you elsewhere is a side quest: link it to a question, give it a time box, or park it.
Progress is real output (answers, finished steps), never time spent.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .bodies import Body
from . import growth
from .db import DB, now

Energy = Literal["low", "medium", "high"]
EMPTY_SESSION_MS = 3 * 60_000  # a session this long that produced nothing counts as "empty"


# ------------------------------------------------------------------ time helpers
def _day_start_utc(day: dt.date | None = None) -> str:
    """Local midnight of `day` (default today) as a UTC ISO string, comparable with stored timestamps."""
    day = day or dt.date.today()
    local_midnight = dt.datetime.combine(day, dt.time()).astimezone()
    return local_midnight.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds")


def _local(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso).astimezone()


# ------------------------------------------------------------------ shared helpers
def need_row(db: DB, table: str, row_id: str) -> dict:
    """The live row, or a 404. `table` is always a constant from this codebase, never user input."""
    row = db.one(f"SELECT * FROM {table} WHERE id=? AND deleted=0", (row_id,))
    if not row:
        raise HTTPException(404, "not found")
    return row


def clear_lead(db: DB, quest_id: str, keep: str | None = None) -> None:
    """Unmark the lead step(s) through db.update, so updated_at and device_id change too (sync-safe)."""
    for s in db.all("SELECT id FROM quest_steps WHERE quest_id=? AND lead=1 AND deleted=0", (quest_id,)):
        if s["id"] != keep:
            db.update("quest_steps", s["id"], {"lead": 0})


def check_step_refs(db: DB, quest_id: str, question_id: str | None, document_id: str | None) -> None:
    """A step may only point at a question of its own quest and at a document that exists."""
    if question_id and not db.one(
        "SELECT 1 FROM quest_questions WHERE id=? AND quest_id=? AND deleted=0", (question_id, quest_id)
    ):
        raise HTTPException(422, "That question isn't part of this goal.")
    if document_id and not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (document_id,)):
        raise HTTPException(422, "That document isn't in your library.")


# ------------------------------------------------------------------ reads
def active_quest(db: DB) -> dict | None:
    return db.one("SELECT * FROM quests WHERE status='active' AND deleted=0 ORDER BY updated_at DESC LIMIT 1")


def quest_detail(db: DB, quest_id: str) -> dict | None:
    q = db.one("SELECT * FROM quests WHERE id=? AND deleted=0", (quest_id,))
    if not q:
        return None
    q["questions"] = db.all(
        "SELECT * FROM quest_questions WHERE quest_id=? AND deleted=0 ORDER BY ord, created_at", (quest_id,)
    )
    q["steps"] = db.all(
        "SELECT s.*, d.title AS document_title FROM quest_steps s LEFT JOIN documents d ON d.id=s.document_id"
        " WHERE s.quest_id=? AND s.deleted=0 ORDER BY s.done_at IS NOT NULL, s.ord, s.created_at",
        (quest_id,),
    )
    q["documents"] = db.all(
        "SELECT id, title, quest_question_id FROM documents WHERE deleted=0 AND quest_question_id IN"
        " (SELECT id FROM quest_questions WHERE quest_id=? AND deleted=0)",
        (quest_id,),
    )
    q["side_quests"] = db.all(
        "SELECT * FROM side_quests WHERE quest_id=? AND deleted=0 AND resolved=0 ORDER BY created_at DESC", (quest_id,)
    )
    answered = sum(1 for x in q["questions"] if x["answer"].strip())
    q["progress"] = {"answered": answered, "total": len(q["questions"])}
    q["lead"] = lead_step(q["steps"])
    return q


def lead_step(steps: list[dict]) -> dict | None:
    """The marked lead step if it's still open, else the first open step."""
    open_steps = [s for s in steps if not s["done_at"]]
    return next((s for s in open_steps if s["lead"]), None) or (open_steps[0] if open_steps else None)


def checkin_today(db: DB) -> dict | None:
    return db.one(
        "SELECT * FROM checkins WHERE created_at>=? AND deleted=0 ORDER BY created_at DESC, rowid DESC LIMIT 1", (_day_start_utc(),)
    )


def energy_curve(db: DB, days: int = 30) -> dict:
    """Your rhythm from your own sessions: focused minutes by hour of day, and your best 2-hour window."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="milliseconds")
    hours = [0.0] * 24
    sessions = db.all("SELECT started_at, focused_ms FROM sessions WHERE started_at>=? AND deleted=0", (since,))
    for s in sessions:
        if s["focused_ms"] > 0:
            hours[_local(s["started_at"]).hour] += s["focused_ms"] / 60_000
    total = sum(hours)
    if len([s for s in sessions if s["focused_ms"] > 0]) < 3 or total < 20:
        return {"learning": True, "hours": hours, "peak": None}
    best = max(range(24), key=lambda h: hours[h] + hours[(h + 1) % 24])
    return {"learning": False, "hours": [round(x, 1) for x in hours], "peak": [best, (best + 2) % 24]}


def output_today(db: DB, quest_id: str | None) -> dict:
    """Real output, not time: answers written and steps finished today, and sessions that produced nothing."""
    start = _day_start_utc()
    answers = (db.scalar("SELECT COUNT(*) FROM questions WHERE answered_at>=? AND deleted=0", (start,)) or 0) + (
        db.scalar("SELECT COUNT(*) FROM quest_questions WHERE answered_at>=? AND deleted=0", (start,)) or 0
    )
    steps = db.scalar("SELECT COUNT(*) FROM quest_steps WHERE done_at>=? AND deleted=0", (start,)) or 0
    sessions = db.all("SELECT * FROM sessions WHERE started_at>=? AND deleted=0", (start,))
    empty = sum(
        1
        for s in sessions
        if s["ended_at"] and s["focused_ms"] >= EMPTY_SESSION_MS and not s["output"] and not s["sentences_read"]
    )
    on_quest = sum(s["focused_ms"] for s in sessions if quest_id and s["quest_id"] == quest_id)
    focused = sum(s["focused_ms"] for s in sessions)
    return {
        "answers": answers,
        "steps": steps,
        "empty_sessions": empty,
        "focused_ms": focused,
        "on_quest_ms": on_quest,
        "on_quest_ratio": round(on_quest / focused, 2) if focused else None,
    }


def recent_empty_streak(db: DB) -> int:
    """How many of your last sessions in a row produced nothing (a hint to change method, not to try harder)."""
    n = 0
    for s in db.all("SELECT * FROM sessions WHERE ended_at IS NOT NULL AND deleted=0 ORDER BY started_at DESC LIMIT 6"):
        if s["focused_ms"] >= EMPTY_SESSION_MS and not s["output"] and not s["sentences_read"]:
            n += 1
        else:
            break
    return n


def today(db: DB) -> dict:
    q = active_quest(db)
    detail = quest_detail(db, q["id"]) if q else None
    return {
        "quest": detail,
        "checkin": checkin_today(db),
        "energy": energy_curve(db),
        "output": output_today(db, q["id"] if q else None),
        "empty_streak": recent_empty_streak(db),
        "parked": db.scalar("SELECT COUNT(*) FROM side_quests WHERE decision='parked' AND resolved=0 AND deleted=0") or 0,
        "habits": growth.habits(db),
        "letters_due": db.scalar(
            "SELECT COUNT(*) FROM letters WHERE open_on<=? AND opened_at IS NULL AND deleted=0", (dt.date.today().isoformat(),)
        ) or 0,
        "log_today": growth.log_today(db),
    }


# ------------------------------------------------------------------ request bodies
class QuestIn(Body):
    title: str = Field(min_length=1, max_length=300)
    why: str = Field("", max_length=2000)
    done_looks_like: str = Field("", max_length=2000)
    deadline: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    questions: list[str] = Field(default_factory=list, max_length=8)


class QuestPatch(Body):
    title: str | None = Field(None, min_length=1, max_length=300)
    why: str | None = Field(None, max_length=2000)
    done_looks_like: str | None = Field(None, max_length=2000)
    deadline: str | None = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    status: Literal["active", "done", "parked"] | None = None


class QuestionIn(Body):
    text: str = Field(min_length=1, max_length=500)


class QuestionPatch(Body):
    text: str | None = Field(None, min_length=1, max_length=500)
    answer: str | None = Field(None, max_length=20000)
    ord: int | None = None


class StepIn(Body):
    title: str = Field(min_length=1, max_length=300)
    question_id: str | None = None
    document_id: str | None = None
    low: str = Field("", max_length=300)
    high: str = Field("", max_length=300)
    minutes: int = Field(20, ge=2, le=240)
    lead: bool = False


class StepPatch(Body):
    title: str | None = Field(None, min_length=1, max_length=300)
    question_id: str | None = None
    document_id: str | None = None
    low: str | None = Field(None, max_length=300)
    high: str | None = Field(None, max_length=300)
    minutes: int | None = Field(None, ge=2, le=240)
    lead: bool | None = None
    ord: int | None = None
    done: bool | None = None
    output: str | None = Field(None, max_length=5000)


class CheckinIn(BaseModel):
    energy: Energy
    note: str = Field("", max_length=500)


class SideIn(Body):
    text: str = Field(min_length=1, max_length=500)
    decision: Literal["parked", "timeboxed", "linked"]
    minutes: int = Field(0, ge=0, le=240)
    question_id: str | None = None
    document_id: str | None = None


# ------------------------------------------------------------------ routes
def register(app: FastAPI, db: DB) -> None:
    def need(table: str, row_id: str) -> dict:
        return need_row(db, table, row_id)

    @app.get("/api/today")
    def api_today():
        return today(db)

    @app.get("/api/quest/active")
    def api_quest_active():
        """Just the main quest (questions, steps) — cheaper than /api/today for dialogs that only need that."""
        q = active_quest(db)
        return quest_detail(db, q["id"]) if q else None

    @app.get("/api/quests")
    def api_quests():
        return db.all("SELECT * FROM quests WHERE deleted=0 ORDER BY status='active' DESC, updated_at DESC LIMIT 50")

    @app.post("/api/quests")
    def api_quest_create(body: QuestIn):
        # one main quest at a time: an earlier active quest is parked, never lost
        for old in db.all("SELECT id FROM quests WHERE status='active' AND deleted=0"):
            db.update("quests", old["id"], {"status": "parked"})
        q = db.insert("quests", {"title": body.title.strip(), "why": body.why.strip(),
                                 "done_looks_like": body.done_looks_like.strip(), "deadline": body.deadline,
                                 "status": "active"})
        for i, text in enumerate(t.strip() for t in body.questions):
            if text:
                db.insert("quest_questions", {"quest_id": q["id"], "ord": i, "text": text})
        return quest_detail(db, q["id"])

    @app.get("/api/quests/{quest_id}")
    def api_quest(quest_id: str):
        q = quest_detail(db, quest_id)
        if not q:
            raise HTTPException(404, "goal not found")
        return q

    @app.patch("/api/quests/{quest_id}")
    def api_quest_patch(quest_id: str, body: QuestPatch):
        need("quests", quest_id)
        fields = body.model_dump(exclude_none=True)
        if fields.get("deadline") == "":
            fields["deadline"] = None
        if fields.get("status") == "active":
            for old in db.all("SELECT id FROM quests WHERE status='active' AND id!=? AND deleted=0", (quest_id,)):
                db.update("quests", old["id"], {"status": "parked"})
        if fields.get("status") == "done":
            fields["finished_at"] = now()
        db.update("quests", quest_id, fields)
        return quest_detail(db, quest_id)

    @app.delete("/api/quests/{quest_id}")
    def api_quest_delete(quest_id: str):
        need("quests", quest_id)
        db.soft_delete("quests", quest_id)
        return {"ok": True}

    @app.post("/api/quests/{quest_id}/questions")
    def api_qq_create(quest_id: str, body: QuestionIn):
        need("quests", quest_id)
        n = db.scalar("SELECT COUNT(*) FROM quest_questions WHERE quest_id=? AND deleted=0", (quest_id,)) or 0
        return db.insert("quest_questions", {"quest_id": quest_id, "ord": n, "text": body.text.strip()})

    @app.patch("/api/quest-questions/{qq_id}")
    def api_qq_patch(qq_id: str, body: QuestionPatch):
        row = need("quest_questions", qq_id)
        fields = body.model_dump(exclude_none=True)
        if "answer" in fields:
            fields["answer"] = fields["answer"].strip()
            if fields["answer"] and not row["answer"]:
                fields["answered_at"] = now()
            if not fields["answer"]:
                fields["answered_at"] = None
        db.update("quest_questions", qq_id, fields)
        return need("quest_questions", qq_id)

    @app.delete("/api/quest-questions/{qq_id}")
    def api_qq_delete(qq_id: str):
        need("quest_questions", qq_id)
        db.soft_delete("quest_questions", qq_id)
        return {"ok": True}

    @app.post("/api/quests/{quest_id}/steps")
    def api_step_create(quest_id: str, body: StepIn):
        need("quests", quest_id)
        check_step_refs(db, quest_id, body.question_id, body.document_id)
        n = db.scalar("SELECT COUNT(*) FROM quest_steps WHERE quest_id=? AND deleted=0", (quest_id,)) or 0
        row = {**body.model_dump(), "quest_id": quest_id, "ord": n, "lead": int(body.lead)}
        if body.lead:
            clear_lead(db, quest_id)
        return db.insert("quest_steps", row)

    @app.patch("/api/quest-steps/{step_id}")
    def api_step_patch(step_id: str, body: StepPatch):
        step = need("quest_steps", step_id)
        fields = body.model_dump(exclude_unset=True)
        for key in ("title", "low", "high", "minutes", "lead", "ord", "output"):
            if key in fields and fields[key] is None:  # these columns can't be empty
                raise HTTPException(422, f"{key} can't be empty")
        check_step_refs(db, step["quest_id"], fields.get("question_id"), fields.get("document_id"))
        done = fields.pop("done", None)
        if done is True and not step["done_at"]:
            fields["done_at"] = now()
        elif done is False:
            fields["done_at"] = None
        if fields.get("lead"):
            clear_lead(db, step["quest_id"], keep=step_id)
        if "lead" in fields:
            fields["lead"] = int(bool(fields["lead"]))
        db.update("quest_steps", step_id, fields)
        return need("quest_steps", step_id)

    @app.delete("/api/quest-steps/{step_id}")
    def api_step_delete(step_id: str):
        need("quest_steps", step_id)
        db.soft_delete("quest_steps", step_id)
        return {"ok": True}

    @app.post("/api/checkins")
    def api_checkin(body: CheckinIn):
        return db.insert("checkins", body.model_dump())

    @app.get("/api/side-quests")
    def api_side_list():
        return db.all("SELECT * FROM side_quests WHERE deleted=0 AND resolved=0 ORDER BY created_at DESC LIMIT 100")

    @app.post("/api/side-quests")
    def api_side_create(body: SideIn):
        q = active_quest(db)
        row = db.insert("side_quests", {**body.model_dump(), "quest_id": q["id"] if q else None,
                                        "resolved": int(body.decision != "parked")})
        if body.decision == "linked" and body.document_id and body.question_id:
            db.update("documents", body.document_id, {"quest_question_id": body.question_id})
        return row

    @app.patch("/api/side-quests/{side_id}")
    def api_side_resolve(side_id: str):
        need("side_quests", side_id)
        db.update("side_quests", side_id, {"resolved": 1})
        return {"ok": True}
