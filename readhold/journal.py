"""Journal: one page per day, started for you.

- Inner weather instead of a mood score (sunny, bright, cloudy, rainy, stormy).
- The day's story is already drafted from what you did in the app (sessions, steps, habits, answers),
  so you write about how it went, not what happened.
- A deck of prompts to draw from, handwriting via the shared ink store, and "On this day" memories.
- Letters to your future self, sealed until the date you choose.
Everything stays on this machine like the rest of Readhold.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .bodies import Body
from .compass import need_row
from .db import DB, now

Weather = Literal["", "sunny", "bright", "cloudy", "rainy", "stormy"]

PROMPTS = {
    "gratitude": ["What small thing went right today?", "Who made today a little easier?", "What are you glad you didn't skip?"],
    "learning": ["What do you understand now that you didn't this morning?", "What confused you, and what's one way to un-confuse it?",
                 "If you taught today's topic in two sentences, what would you say?"],
    "win": ["What's one thing you finished, however small?", "Where did you show up even though it was hard?",
            "What would past-you be proud of today?"],
    "worry": ["What's on your mind? Write it down so your head can let go of it.", "What's in your control about it, and what isn't?",
              "What's the smallest next step for the thing you're avoiding?"],
    "kindness": ["How did you treat yourself today? What would you say to a friend in your place?",
                 "What does tomorrow-you need from tonight-you?"],
}


def _day(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(422, "Use a date like 2026-11-12.")
    try:
        dt.date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(422, "That isn't a real date.") from e
    return value


def _utc_bounds(day: dt.date) -> tuple[str, str]:
    start = dt.datetime.combine(day, dt.time()).astimezone().astimezone(dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    return start.isoformat(timespec="milliseconds"), end.isoformat(timespec="milliseconds")


def _clock(iso: str) -> str:
    return dt.datetime.fromisoformat(iso).astimezone().strftime("%H:%M")


def day_story(db: DB, day: dt.date) -> list[dict]:
    """What you did that day, in time order, from the app's own records. Facts only — the feelings are yours."""
    start, end = _utc_bounds(day)
    items: list[dict] = []
    for s in db.all(
        "SELECT s.started_at, s.focused_ms, s.output, s.feel, d.title AS doc, st.title AS step, s.question FROM sessions s"
        " LEFT JOIN documents d ON d.id=s.document_id LEFT JOIN quest_steps st ON st.id=s.step_id"
        " WHERE s.started_at>=? AND s.started_at<? AND s.deleted=0 AND s.focused_ms>=60000 ORDER BY s.started_at",
        (start, end),
    ):
        what = s["step"] or s["doc"] or s["question"] or "a focus session"
        mins = round(s["focused_ms"] / 60000)
        verb = "Read" if s["doc"] else "Worked on"
        items.append({"time": _clock(s["started_at"]), "kind": "session",
                      "text": f"{verb} {what} · {mins} min" + (f" → {s['output']}" if s["output"] and s["output"] != "done" else ""),
                      "feel": s["feel"]})
    # a goal or a habit you deleted leaves the story with its steps, answers and checks
    for st in db.all("SELECT s.title, s.done_at FROM quest_steps s JOIN quests q ON q.id=s.quest_id"
                     " WHERE s.done_at>=? AND s.done_at<? AND s.deleted=0 AND q.deleted=0", (start, end)):
        items.append({"time": _clock(st["done_at"]), "kind": "step", "text": f"Finished: {st['title']}"})
    for q in db.all("SELECT a.text, a.answered_at FROM quest_questions a JOIN quests q ON q.id=a.quest_id"
                    " WHERE a.answered_at>=? AND a.answered_at<? AND a.deleted=0 AND q.deleted=0", (start, end)):
        items.append({"time": _clock(q["answered_at"]), "kind": "answer", "text": f"Answered: {q['text']}"})
    for h in db.all(
        "SELECT h.title, c.created_at FROM habit_checks c JOIN habits h ON h.id=c.habit_id WHERE c.day=? AND c.deleted=0 AND h.deleted=0",
        (day.isoformat(),),
    ):
        items.append({"time": _clock(h["created_at"]), "kind": "habit", "text": f"Kept a habit: {h['title']}"})
    reviews = db.scalar("SELECT COUNT(*) FROM reviews WHERE reviewed_at>=? AND reviewed_at<? AND deleted=0", (start, end)) or 0
    if reviews:
        items.append({"time": "", "kind": "review", "text": f"Reviewed {reviews} card{'s' if reviews != 1 else ''}"})
    notes = db.scalar("SELECT COUNT(*) FROM lecture_notes WHERE created_at>=? AND created_at<? AND deleted=0", (start, end)) or 0
    if notes:
        items.append({"time": "", "kind": "notes", "text": f"Took {notes} lecture note{'s' if notes != 1 else ''}"})
    log = db.one("SELECT * FROM day_logs WHERE day=? AND deleted=0", (day.isoformat(),))
    if log and log["learned"]:
        items.append({"time": "", "kind": "learned", "text": f"Learned: {log['learned']}"})
    items.sort(key=lambda i: (i["time"] == "", i["time"]))
    return items


def _entry(db: DB, day: str) -> dict | None:
    e = db.one("SELECT * FROM journal_entries WHERE day=? AND deleted=0", (day,))
    if e:
        try:
            e["prompts"] = json.loads(e["prompts"] or "[]")
        except ValueError:
            e["prompts"] = []
    return e


class EntryIn(BaseModel):
    weather: Weather = ""
    body: str = Field("", max_length=100_000)
    prompts: list[dict] = Field(default_factory=list, max_length=20)


class LetterIn(Body):
    body: str = Field(min_length=1, max_length=50_000)
    open_on: str


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/journal/{day}")
    def api_journal(day: str):
        d = dt.date.fromisoformat(_day(day))
        ago = {"A week ago": 7, "A month ago": 30, "A year ago": 365}
        memories = []
        for label, n in ago.items():
            e = _entry(db, (d - dt.timedelta(days=n)).isoformat())
            if e and (e["body"].strip() or e["weather"]):
                memories.append({"label": label, "day": e["day"], "weather": e["weather"], "body": e["body"][:400]})
        since = (d - dt.timedelta(days=41)).isoformat()
        recent = db.all(
            "SELECT day, weather, length(body) > 0 AS wrote FROM journal_entries WHERE day>? AND day<=? AND deleted=0 ORDER BY day",
            (since, d.isoformat()),
        )
        today = dt.date.today().isoformat()
        due = db.all(
            "SELECT id, created_at, open_on FROM letters WHERE open_on<=? AND opened_at IS NULL AND deleted=0 ORDER BY open_on", (today,)
        )
        sealed = db.scalar("SELECT COUNT(*) FROM letters WHERE open_on>? AND deleted=0", (today,)) or 0
        return {"day": d.isoformat(), "entry": _entry(db, d.isoformat()), "story": day_story(db, d), "memories": memories,
                "recent": recent, "letters_due": due, "letters_sealed": sealed, "prompts": PROMPTS}

    @app.put("/api/journal/{day}")
    def api_journal_save(day: str, body: EntryIn):
        day = _day(day)
        if dt.date.fromisoformat(day) > dt.date.today():
            raise HTTPException(422, "You can't write tomorrow's page yet.")
        prompts = [{"q": str(p.get("q", ""))[:500], "a": str(p.get("a", ""))[:20000]} for p in body.prompts if isinstance(p, dict)]
        fields = {"weather": body.weather, "body": body.body, "prompts": json.dumps(prompts, ensure_ascii=False)}
        existing = db.one("SELECT id FROM journal_entries WHERE day=?", (day,))
        if existing:
            db.update("journal_entries", existing["id"], {**fields, "deleted": 0})
        else:
            db.insert("journal_entries", {"day": day, **fields})
        return _entry(db, day)

    @app.get("/api/letters")
    def api_letters():
        today = dt.date.today().isoformat()
        opened = db.all("SELECT * FROM letters WHERE opened_at IS NOT NULL AND deleted=0 ORDER BY opened_at DESC LIMIT 50")
        sealed = db.all("SELECT id, open_on, created_at FROM letters WHERE opened_at IS NULL AND deleted=0 ORDER BY open_on")
        return {"opened": opened, "sealed": [{**s, "ready": s["open_on"] <= today} for s in sealed]}

    @app.post("/api/letters")
    def api_letter_create(body: LetterIn):
        open_on = _day(body.open_on)
        if open_on <= dt.date.today().isoformat():
            raise HTTPException(422, "Pick a day in the future: the letter stays sealed until then.")
        row = db.insert("letters", {"body": body.body.strip(), "open_on": open_on})
        return {"id": row["id"], "open_on": open_on}

    @app.post("/api/letters/{letter_id}/open")
    def api_letter_open(letter_id: str):
        letter = need_row(db, "letters", letter_id)
        if letter["open_on"] > dt.date.today().isoformat():
            raise HTTPException(403, f"Sealed until {letter['open_on']}.")
        if not letter["opened_at"]:
            db.update("letters", letter_id, {"opened_at": now()})
        return need_row(db, "letters", letter_id)
