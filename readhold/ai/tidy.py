"""Tidy with a model (milestone 5.2 of docs/ai/PLAN.md): a rewrite of your tasks, a note or a routine, proposed only.

The non-AI version is `readhold/tidy.py` (hints, and fixes code is sure of). With AI on, and only when you ask, a
model reads what you wrote (your open tasks, one note, or one routine, as your own text) and proposes a rewrite:
- tasks: a clearer text starting with a verb, minutes, a day the text implies, and a split into at most 4 parts;
- a note: a tidier body (headings, lists), the same content;
- a routine: clearer step texts and minutes.

What comes back is checked before you see it: a task number must be one of yours, once; minutes must be possible
(1 to 600 for a task, 0 to 240 for a step) or are not used; a day must be today to 60 days ahead or is not used;
texts are capped. Every word of the rewrite that is not in what you wrote is listed (`new_words`), so an invented
fact is visible: the model is told to add none. In a note, a [[link]] or #tag the model added stays plain text;
your own stay as they are. Nothing is applied here: the page applies what you accept, through the usual routes,
with Undo. A note too long to send whole is refused rather than cut (the rewrite would lose its end).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, BeforeValidator, Field

from .. import pages, think
from .. import tidy as plain
from ..db import DB
from . import guard, prompts, results
from .notes import _inert
from .port import AIError, AIOff, Port
from .resume import status_error

FEATURE = "tidy"
ID = re.compile(r"[0-9a-f]{32}")
MAX_TASKS = 30
MAX_SPLIT = 4
MAX_NOTE = 10_000  # characters: a longer note is refused, not cut (guard.BUDGETS["tidy"] holds it whole)
MAX_STEPS = 30
DAYS_AHEAD = 60
CAP = 200
KINDS = {
    "tasks": ('Kind: tasks. Answer {"tasks": [...]}: one entry per task you improve, with "task" (its number), "text" (one clear task '
              'starting with a verb, under 15 words), "minutes" (your estimate, a whole number, or 0 if unsure), "day" ("today", '
              '"tomorrow", a weekday or YYYY-MM-DD, only if the text says when; else "") and "split" (when the task holds several '
              'things to do: at most 4 parts, each {"text", "minutes"}; else []).'),
    "note": 'Kind: a note. Answer {"body": "..."}: the whole note, tidied: a short heading if it helps, lists for lists, full sentences. The same content; keep its [[links]].',
    "routine": 'Kind: a routine. Answer {"steps": [{"text", "minutes"}, ...]}: its steps, each a short clear action; minutes only if the step is timed, else 0.',
}


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


class Part(BaseModel):
    text: guard.LooseText = ""
    minutes: Any = None


class TaskOut(BaseModel):
    task: Any = None
    text: guard.LooseText = ""
    minutes: Any = None
    day: guard.LooseText = ""
    split: Annotated[list[Part], guard.loose_list(8)] = []


# a note's body may be as long as a note (guard.LooseText would cut it at 2,000 characters)
LongText = Annotated[str, BeforeValidator(lambda v: v[:pages.MAX_BODY] if isinstance(v, str) else "")]
FILLER = frozenset("the a an of to in on at for and or with by is are be it its this that your you my i as from".split())
SHORTER = 0.6  # a rewrite under this share of the note's length is marked, with the words that went missing


class TidyOut(BaseModel):
    tasks: Annotated[list[TaskOut], guard.loose_list(60)] = []
    body: LongText = ""
    steps: Annotated[list[Part], guard.loose_list(60)] = []


def _whole(v: Any, low: int, high: int) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and low <= v <= high else None


def _day(v: str, today: dt.date) -> str | None:
    v = (v or "").strip().lower()
    if not v:
        return None
    if v in ("today", "tomorrow", *plain.DAYS):
        return plain._day(v, today)
    try:
        d = dt.date.fromisoformat(v)
    except ValueError:
        return None
    return d.isoformat() if today <= d <= today + dt.timedelta(days=DAYS_AHEAD) else None


def _text(v: str) -> str:
    return " ".join(guard.safe_output(v, CAP - 1).text.split())  # CAP - 1: the "…" of a cut text still fits in CAP


def _tokens(text: str) -> set[str]:
    """Every word and number, short ones and negations included ("not", "dont", "al", "3"), but the few filler words."""
    return {w.replace("'", "").replace("’", "") for w in re.findall(r"[\w'’]+", text.casefold())} - FILLER - {""}


def _new_words(proposed: str, original: str) -> list[str]:
    return sorted(_tokens(proposed) - _tokens(original))


# ------------------------------------------------------------------ what the model reads
def _target(db: DB, kind: str, item_id: str) -> tuple[str, str, list[guard.Source], dict]:
    """(target_type, target_id, sources, what they say) for what is tidied."""
    if kind == "tasks":
        rows = db.all("SELECT id, text, minutes, due FROM todos WHERE deleted=0 AND done_at IS NULL ORDER BY ord LIMIT ?", (MAX_TASKS,))
        if not rows:
            raise Invalid("There is no open task to tidy.")
        sources = [guard.Source(f"task:{r['id']}", f"(Task {i}) {r['text']} | {r['minutes']} min | day: {r['due'] or 'none'}", "yours")
                   for i, r in enumerate(rows, 1)]
        return "plan", "tasks", sources, {"tasks": rows}
    if not ID.fullmatch(item_id or ""):
        raise NotFound()
    if kind == "note":
        row = db.one("SELECT id, title, body FROM pages WHERE id=? AND deleted=0", (item_id,))
        if not row:
            raise NotFound()
        if len(row["body"]) > MAX_NOTE:
            raise Invalid(f"This note is too long to tidy at once (over {MAX_NOTE:,} characters). Tidy it in parts, or use the tidy that needs no model.")
        src = guard.Source(f"note:{row['id']}", f"(Your note: {row['title'][:200]})\n{row['body']}", "yours")
        src.main = True  # if it is private, a call that leaves this computer is refused
        return "page", row["id"], [src], {"title": row["title"], "body": row["body"]}
    row = db.one("SELECT id, title FROM routines WHERE id=? AND deleted=0", (item_id,))
    if not row:
        raise NotFound()
    steps = db.all("SELECT text, minutes FROM routine_steps WHERE routine_id=? AND deleted=0 ORDER BY ord", (item_id,))
    text = f"(Routine: {row['title'][:120]})\n" + "\n".join(f"{i}. {s['text']} ({s['minutes']} min)" for i, s in enumerate(steps, 1))
    return "routine", row["id"], [guard.Source(f"routine:{row['id']}", text, "yours")], {"title": row["title"], "steps": steps}


# ------------------------------------------------------------------ checking what comes back
def _tasks(data: dict, rows: list[dict], today: dt.date, sent: dict) -> list[dict]:
    out, seen = [], set()
    for t in data.get("tasks") or []:
        n = _whole(t.get("task"), 1, len(rows))
        if n is None or n in seen or f"task:{rows[n - 1]['id']}" not in sent:  # only a task the model was shown
            continue
        seen.add(n)
        row = rows[n - 1]
        text = _text(t.get("text") or "")
        split = [{"text": p, "minutes": _whole(s.get("minutes"), 1, plain.MAX_MINUTES)}
                 for s in (t.get("split") or [])[:MAX_SPLIT] if (p := _text(s.get("text") or ""))]
        if not text and not split:
            continue
        everything = " ".join([text] + [s["text"] for s in split])
        out.append({"id": row["id"], "number": n, "original": {"text": row["text"], "minutes": row["minutes"], "due": row["due"]},
                    "text": text or row["text"], "minutes": _whole(t.get("minutes"), 1, plain.MAX_MINUTES), "due": _day(t.get("day") or "", today),
                    "split": split if len(split) > 1 else [], "new_words": _new_words(everything, row["text"])})
    return out


def _link_key(m: re.Match) -> str:
    return pages.key(pages.ANCHOR.sub("", m.group(1)))


def _note(data: dict, original: dict) -> dict:
    """The rewrite, checked: your own links, tags and properties are kept (put back at the end if the model dropped
    them); links, tags, images and web links it added are plain text; a much shorter rewrite says what went missing."""
    was = original["body"]
    body = guard.sanitize(data.get("body") or "").strip()
    if not body:
        return {"body": "", "new_words": [], "restored": [], "missing_words": [], "shorter": False}
    plain_was = pages.FENCE.sub("", was)  # what is inside a code block is not a live link or tag
    own_links = {_link_key(m): m.group(0) for m in pages.LINK.finditer(plain_was)}
    own_tags = {m.group(1).lower(): m.group(0) for m in pages.TAG.finditer(plain_was)}
    own_props = {m.group(1).strip().lower(): m.group(0).strip() for m in pages.PROP.finditer(was)}
    body = pages.LINK.sub(lambda m: m.group(0) if _link_key(m) in own_links else _inert(m.group(0)), body)
    body = pages.TAG.sub(lambda m: m.group(0) if m.group(1).lower() in own_tags else _inert(m.group(0)), body)
    # image and web-link syntax: yours stays as you wrote it; what the model added becomes words, never loaded
    body = guard._IMAGE.sub(lambda m: m.group(0) if m.group(0) in was else f"{m.group(1) or 'image'} (image not loaded: {m.group(2)})", body)
    body = guard._LINK.sub(lambda m: m.group(0) if m.group(0) in was else (f"{m.group(1)} ({m.group(2)})" if m.group(1) else m.group(2)), body)
    body = "\n".join(line for line in body.split("\n") if not guard._REF.fullmatch(line) or line in was)
    plain_new = pages.FENCE.sub("", body)
    have_links = {_link_key(m) for m in pages.LINK.finditer(plain_new)}
    have_tags = {m.group(1).lower() for m in pages.TAG.finditer(plain_new)}
    have_props = {m.group(1).strip().lower() for m in pages.PROP.finditer(body)}
    back_props = [v for k, v in own_props.items() if k not in have_props]
    back_marks = [v for k, v in own_links.items() if k not in have_links] + [v for k, v in own_tags.items() if k not in have_tags]
    if back_props or back_marks:  # never lose #private, #cloud, a link or a property you wrote
        body = body.rstrip() + "\n\n" + "\n".join(back_props + ([" ".join(back_marks)] if back_marks else []))
    shorter = len(body) < SHORTER * len(was)
    # no label line in the note: what you choose to Use is yours (the proposal itself stays in the AI log and results)
    return {"body": f"{body}\n"[: pages.MAX_BODY], "new_words": _new_words(body, original["title"] + " " + was),
            "restored": back_props + back_marks, "shorter": shorter,
            "missing_words": sorted(_tokens(was) - _tokens(body), key=lambda w: (any(c.isdigit() for c in w), w))[:40] if shorter else []}


def _steps(data: dict, original: dict) -> dict:
    steps = [{"text": t, "minutes": _whole(s.get("minutes"), 0, plain.MAX_STEP_MINUTES) or 0}
             for s in (data.get("steps") or [])[:MAX_STEPS] if (t := _text(s.get("text") or ""))]
    was = original["title"] + " " + " ".join(s["text"] for s in original["steps"])
    return {"steps": steps, "new_words": _new_words(" ".join(s["text"] for s in steps), was)}


def suggest(port: Port, db: DB, kind: str, item_id: str = "", fresh: bool = False) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    target_type, target_id, sources, original = _target(db, kind, item_id)
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, kind, dt.date.today().isoformat(), *(f"{s.anchor}\n{s.text}" for s in sources))  # days are worked out from today
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, target_id, key)
        if kept and not fresh:
            return kept
        r = guard.ask(port, db, FEATURE, f"{prompt.text}\n\n{KINDS[kind]}", sources, budget=FEATURE, schema=TidyOut, prompt_version=prompt.version)
        today = dt.date.today()
        if kind == "tasks":
            payload: dict = {"kind": kind, "items": _tasks(r.data, original["tasks"], today, r.sent)}
        elif kind == "note":
            raw = r.raw if isinstance(r.raw, dict) else {}  # uncleaned, so your own links can be told from the model's
            payload = {"kind": kind, "page_id": target_id, "original": original["body"], **_note({"body": raw.get("body") if isinstance(raw.get("body"), str) else r.data.get("body")}, original)}
        else:
            payload = {"kind": kind, "routine_id": target_id, **_steps(r.data, original)}
        payload.update(links=list(dict.fromkeys(r.links)), warning=r.warning)
        return results.keep(db, FEATURE, target_id, key, payload, prompt.version, r.log_id, replaces=kept["id"] if kept else None, target_type=target_type)


# ------------------------------------------------------------------ routes
class SuggestIn(BaseModel):
    kind: Literal["tasks", "note", "routine"]
    id: str = Field("", max_length=40)
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/tidy/suggest")
    def api_tidy_suggest(body: SuggestIn):
        """A plain `def`: the call runs on a worker thread. Nothing is changed: the page applies what you accept."""
        try:
            return {"result": suggest(port, db, body.kind, body.id, body.fresh)}
        except NotFound:
            raise HTTPException(404, "not found") from None
        except (Invalid, guard.Blocked) as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None
