"""Plan chat (milestone 5.3 of docs/ai/PLAN.md): tasks drafted from what you type, added only when you click.

The plan's first free-text feature, kept to the same rules (design note in section 10, Phase 5). You write ("plan my
week around the exam on Friday"); the model answers with a short reply and at most `MAX_DRAFTS` draft tasks. Code
gives it what it needs and nothing more: your next `DAYS` days with the free minutes on each (minutes a day you set,
minus the open tasks already on that day), your open tasks, the deadlines of what you read, and the conversation so
far (the model's earlier replies marked as its own text). What you write is fenced like any source.

Every draft is checked before you see it: a real day from today to `DAYS_AHEAD` days ahead (else it has no day), minutes
5 to 240 (else 25, said), not a task you already have (left out and counted), and the day's free time (marked when it
would go over). Nothing is added by asking. `add` puts the drafts you keep on Plan as one batch (`plan_batch`), each
saying in its note that a model drafted it; the reading plan's Undo (`readplan.undo`) takes the batch back.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import tidy as plain
from ..db import DB, new_id
from . import guard, privacy, prompts, results
from .port import AIError, AIOff, Port
from .resume import status_error

FEATURE = "chat"
ID = re.compile(r"[0-9a-f]{32}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_DRAFTS = 12
MAX_TURNS = 12
MAX_TASKS = 40
DAYS = 14  # days shown with their free minutes
DAYS_AHEAD = 60
DEFAULT_MINUTES = 25
NOTE = "Drafted by the AI model from your Plan chat on {day}; check that it suits you."


def _anchor(kind: str, name: str) -> str:
    return f"{kind}:{hashlib.md5(name.encode()).hexdigest()}"  # noqa: S324  (a name for a fence, not a secret)


class Draft(BaseModel):
    text: guard.LooseText = ""
    day: guard.LooseText = ""
    minutes: Any = None


class ChatOut(BaseModel):
    reply: guard.LooseText = ""
    tasks: Annotated[list[Draft], guard.loose_list(60)] = []


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


def _planned(db: DB) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in db.all("SELECT due, minutes FROM todos WHERE deleted=0 AND done_at IS NULL AND due IS NOT NULL"):
        out[r["due"]] = out.get(r["due"], 0) + (r["minutes"] or 0)
    return out


def _sources(db: DB, turns: list[dict], per_day: int, today: dt.date, away: bool = False) -> tuple[list[guard.Source], list[dict], dict[str, int]]:
    planned = _planned(db)
    days = [today + dt.timedelta(days=i) for i in range(DAYS)]
    lines = [f"{d.isoformat()} {d.strftime('%A')}: {max(0, per_day - planned.get(d.isoformat(), 0))} free of {per_day} minutes" for d in days]
    out = [guard.Source(_anchor("days", "days"), "(Your next days, worked out by the app)\n" + "\n".join(lines), "yours")]
    tasks = db.all("SELECT id, text, minutes, due FROM todos WHERE deleted=0 AND done_at IS NULL ORDER BY due IS NULL, due, ord LIMIT ?", (MAX_TASKS,))
    out += [guard.Source(f"task:{t['id']}", f"(Open task) {t['text']} | day: {t['due'] or 'any'} | {t['minutes']} min", "yours") for t in tasks]
    for d in db.all("SELECT id, title, why, deadline FROM documents WHERE deleted=0 AND status!='finished' AND deadline>=? ORDER BY deadline LIMIT 20", (today.isoformat(),)):
        out.append(guard.Source(f"docs:{d['id']}", f"(Deadline) Read “{d['title'][:200]}” by {d['deadline']}" + (f"; why: {d['why'][:200]}" if d["why"] else ""), "imported"))
    for i, t in enumerate(turns[:-1]):  # the conversation so far; the latest message goes as the question
        mine = t["who"] == "you"
        if not mine and away and privacy.copies_private(db, t["text"]):
            continue  # an earlier reply (from a model on this computer) that names private text never leaves it
        out.append(guard.Source(_anchor("turn", str(i)), f"({'You said' if mine else 'The model said'})\n{t['text']}", "yours" if mine else "model"))
    return out, tasks, planned


def _day(v: str, today: dt.date) -> tuple[str | None, str]:
    v = (v or "").strip().lower()
    if not v:
        return None, ""
    if v in ("today", "tomorrow", *plain.DAYS):
        return plain._day(v, today), ""
    try:
        d = dt.date.fromisoformat(v)
    except ValueError:
        return None, "The model gave no real day: it has none."
    if not today <= d <= today + dt.timedelta(days=DAYS_AHEAD):
        return None, f"The model's day ({d.isoformat()}) is in the past or more than {DAYS_AHEAD} days ahead: it has none."
    return d.isoformat(), ""


def _check(data: dict, tasks: list[dict], planned: dict[str, int], per_day: int, today: dt.date, db: DB | None = None) -> dict:
    every = db.all("SELECT text FROM todos WHERE deleted=0 AND done_at IS NULL LIMIT 5000") if db is not None else tasks
    have = {" ".join(t["text"].split()).casefold() for t in every}  # every open task, not only those shown to the model
    load = dict(planned)
    drafts, seen, already, dropped = [], set(), 0, 0
    for t in data.get("tasks") or []:
        text = " ".join(guard.safe_output(t.get("text") or "", 200).text.split())
        if not text:
            continue
        key = text.casefold()
        if key in have:
            already += 1
            continue
        if key in seen:
            continue
        if len(drafts) >= MAX_DRAFTS:
            dropped += 1
            continue
        seen.add(key)
        flags = []
        due, why = _day(t.get("day") or "", today)
        if why:
            flags.append(why)
        m = t.get("minutes")
        minutes = m if isinstance(m, int) and not isinstance(m, bool) and 5 <= m <= 240 else None
        if minutes is None:
            minutes = DEFAULT_MINUTES
            flags.append(f"The model's minutes were not usable: set to {DEFAULT_MINUTES}.")
        fits = True
        if due:
            load[due] = load.get(due, 0) + minutes
            if load[due] > per_day:
                fits = False
                flags.append(f"Over your free time that day: {load[due]} of {per_day} minutes planned.")
        drafts.append({"text": text, "due": due, "minutes": minutes, "fits": fits, "flags": flags})
    return {"drafts": drafts, "already": already, "dropped": dropped}


def draft(port: Port, db: DB, turns: list[dict], per_day: int) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    today = dt.date.today()
    question = guard.user_text(turns[-1]["text"], "ask")
    if guard.leaves(port) and privacy.copies_private(db, question):  # as for the earlier messages: private text stays here
        raise guard.Blocked("Your message copies text from a private document (#private), so it is not sent off this computer. "
                            "Say it in your own words, or use a model on this computer.")
    sources, tasks, planned = _sources(db, turns, per_day, today, away=guard.leaves(port))
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, str(per_day), today.isoformat(), question, *(f"{s.anchor}\n{s.text}" for s in sources))
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, FEATURE, key)
        if kept:
            return kept
        r = guard.ask(port, db, FEATURE, prompt.text, sources, budget=FEATURE, question=question, schema=ChatOut, prompt_version=prompt.version)
        payload = {"question": question, "minutes_a_day": per_day, "reply": guard.safe_output(r.data.get("reply") or "", 800).text,
                   **_check(r.data, tasks, planned, per_day, today, db), "kept": [], "batch": "", "links": list(dict.fromkeys(r.links)), "warning": r.warning}
        return results.keep(db, FEATURE, FEATURE, key, payload, prompt.version, r.log_id, target_type="plan")


def add(db: DB, result_id: str, chosen: list[dict]) -> dict:
    """The one click: the drafts you keep go on Plan as one batch. Each draft once; edits you made are what is added."""
    row = db.one("SELECT * FROM ai_results WHERE id=? AND feature=? AND deleted=0", (result_id, FEATURE)) if ID.fullmatch(result_id or "") else None
    if not row:
        raise NotFound()
    today = dt.date.today()
    with db.transaction():
        payload = json.loads(db.scalar("SELECT payload FROM ai_results WHERE id=?", (result_id,)))
        kept, batch, added, ids = set(payload.get("kept") or []), f"chat:{new_id()}", [], []  # each click is its own batch
        top = db.scalar("SELECT MAX(ord) FROM todos WHERE deleted=0 AND done_at IS NULL") or 0
        for c in chosen:
            i = c.get("index")
            if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(payload["drafts"]):
                raise Invalid("That draft is not in this answer.")
            if i in kept:
                continue
            text = " ".join(str(c.get("text") or "").split())[:500]
            due = c.get("due") or None
            if not text:
                raise Invalid("A task needs its text.")
            if due is not None:
                try:
                    real = DAY.fullmatch(str(due)) and dt.date.fromisoformat(str(due))
                except ValueError:
                    real = None
                if not real or not today <= real <= today + dt.timedelta(days=365):
                    raise Invalid("A task's day must be a real day from today on.")
            minutes = c.get("minutes")
            if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= plain.MAX_MINUTES:
                raise Invalid(f"A task's minutes must be from 1 to {plain.MAX_MINUTES}.")
            top += 1
            row = db.insert("todos", {"text": text, "minutes": minutes, "due": due, "ord": top, "note": NOTE.format(day=today.isoformat()), "plan_batch": batch})
            kept.add(i)
            added.append(i)
            ids.append([row["id"], i])
        payload["kept"] = sorted(kept)
        if ids:
            payload.setdefault("batches", {})[batch] = ids
        db.update("ai_results", result_id, {"payload": json.dumps(payload, ensure_ascii=False), "status": "accepted"})
    return {"batch": batch, "added": len(added), "kept": payload["kept"]}


# ------------------------------------------------------------------ routes
class Turn(BaseModel):
    who: Literal["you", "model"]
    text: str = Field(max_length=4000)


class ChatIn(BaseModel):
    messages: list[Turn] = Field(min_length=1, max_length=MAX_TURNS)
    minutes_a_day: int = Field(120, ge=15, le=720)


class Chosen(BaseModel):
    index: int
    text: str = Field("", max_length=2000)
    due: str | None = Field(None, max_length=10)
    minutes: int = 25


class AddIn(BaseModel):
    items: list[Chosen] = Field(default_factory=list, max_length=MAX_DRAFTS)


def undo(db: DB, result_id: str, batch: str) -> dict:
    """Take one click back: its tasks as they were added go (one you finished, timed or changed stays, as in the
    reading plan), and their drafts can be added again."""
    from .. import readplan

    row = db.one("SELECT * FROM ai_results WHERE id=? AND feature=? AND deleted=0", (result_id, FEATURE)) if ID.fullmatch(result_id or "") else None
    if not row:
        raise NotFound()
    with db.transaction():
        payload = json.loads(db.scalar("SELECT payload FROM ai_results WHERE id=?", (result_id,)))
        pairs = (payload.get("batches") or {}).get(batch)
        if not pairs:
            raise NotFound()
        gone = {r["id"] for r in db.all(f"SELECT id FROM todos WHERE plan_batch=? AND deleted=0 AND {readplan._UNTOUCHED}", (batch,))}
        for tid in gone:
            db.soft_delete("todos", tid)
        payload["kept"] = sorted(set(payload.get("kept") or []) - {i for tid, i in pairs if tid in gone})
        payload["batches"][batch] = [[tid, i] for tid, i in pairs if tid not in gone]
        db.update("ai_results", result_id, {"payload": json.dumps(payload, ensure_ascii=False)})
    return {"removed": len(gone), "stayed": len(pairs) - len(gone), "kept": payload["kept"]}


class UndoIn(BaseModel):
    batch: str = Field(max_length=60)


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/plan/chat")
    def api_plan_chat(body: ChatIn):
        """A plain `def`: the call runs on a worker thread. Nothing is added: the drafts wait for your click."""
        if body.messages[-1].who != "you":
            raise HTTPException(422, "The last message must be yours.")
        try:
            return {"result": draft(port, db, [m.model_dump() for m in body.messages], body.minutes_a_day)}
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None

    @app.post("/api/plan/chat/{result_id}/undo")
    def api_plan_chat_undo(result_id: str, body: UndoIn):
        try:
            return undo(db, result_id, body.batch)
        except NotFound:
            raise HTTPException(404, "not found") from None

    @app.post("/api/plan/chat/{result_id}/add")
    def api_plan_chat_add(result_id: str, body: AddIn):
        try:
            return add(db, result_id, [c.model_dump() for c in body.items])
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Invalid as e:
            raise HTTPException(409, str(e)) from None
