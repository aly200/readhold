"""Tidy (milestone 5.2 of docs/ai/PLAN.md, the layer without a model): what a good task lacks, and fixes code is sure of.

A good task starts with what you will do (a verb), has one outcome, a day, and stays short. Each missing part is a
*hint*, never a change. A *fix* is only what code can be sure of: spacing, a capital first letter, and a time
("30 min", "1.5h") or a day ("tomorrow", "friday") written into the text, moved into the task's own minutes and day.
Notes get spacing and list marks fixed; routine steps get spacing, a capital and their minutes.

Nothing here writes: the routes return proposals, and the page applies one through the usual routes, with Undo.
With AI on, `readhold/ai/tidy.py` can also propose a rewrite; it goes through the same page.
"""
from __future__ import annotations

import datetime as dt
import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .db import DB

ID = re.compile(r"[0-9a-f]{32}")
MAX_MINUTES = 600  # as a task (timer.MAX_MINUTES)
MAX_STEP_MINUTES = 240  # as a routine step (planner.StepIn)
LONG = 90  # characters: a longer task text gets a hint to move details into its note
MAX_TASKS = 200
# words a task commonly starts with; a first word outside this list (in Latin script) gets a gentle hint
VERBS = frozenset("""
add answer apply arrange ask attend back bake book borrow brainstorm buy call cancel change check choose clean clear
collect compare complete confirm contact cook copy create cut decide define delete deliver design discuss do download
draft draw drink email explain export file fill find finish fix follow get give go handle help hire import install
invite join learn list listen look make mark meet memorize move note open order organise organize outline pack pay
pick plan post practice practise prepare present print read rebook record reflect register remind remove renew repair
reply report reschedule research return review revise rewrite run save schedule send set share shop sign sketch
sleep solve sort start study submit summarise summarize take talk teach test text think tidy train translate try
turn update upload visit walk wash watch water work write fold iron vacuum feed phone jog swim pray meditate mop sweep dust
wrap stretch rest nap
""".split())
JOIN = re.compile(r"\s*(?:,|;|\band\b|\bthen\b)\s+", re.I)
# a time written into a task: lower-case units only ("60 Minutes" is a title), and a bare "m" only straight after the number
# ("30m"; "2 m of cable" is a length)
TIME = re.compile(r"\(?\s*(?:\bfor\s+)?\b(\d{1,3}(?:\.\d)?)(?:\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours)|(m))\b\s*\)?")
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_WORD = re.compile(r"\b(?:on\s+)?(today|tomorrow|" + "|".join(DAYS) + r")\b", re.I)
NOT_A_DAY = frozenset("not every each before by last until after since next".split())  # "every monday" is not a day to set
QUOTED = re.compile(r"[\"“”][^\"“”]*[\"“”]|(?<!\w)['‘][^'‘’]*['’](?!\w)")
URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)", re.I)


def _clean(text: str) -> str:
    """Spacing, no empty brackets or leading punctuation left by a moved word, and a capital first letter when the first
    word is all lower case (so "iPhone", "eBay" and a web address stay as they are)."""
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    text = re.sub(r"^[\s:;,\-–—]+", "", " ".join(text.split()))
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    first = (text.split() or [""])[0]
    if first.isalpha() and first.islower() and not URL.match(text):
        text = text[:1].upper() + text[1:]
    return text


def _day(word: str, today: dt.date) -> str:
    w = word.lower()
    if w == "today":
        return today.isoformat()
    if w == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    ahead = (DAYS.index(w) - today.weekday()) % 7 or 7  # the next one: "friday" said on a Friday is a week away
    return (today + dt.timedelta(days=ahead)).isoformat()


def _quoted(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in QUOTED.finditer(text)]


def _inside(spans: list[tuple[int, int]], at: int) -> bool:
    return any(a <= at < b for a, b in spans)


def _minutes(m: re.Match) -> int | None:
    unit = m.group(2) or m.group(3)
    n = float(m.group(1)) * (60 if unit.startswith("h") else 1)
    return int(n) if n == int(n) else None


def _day_match(text: str) -> re.Match | None:
    """The first day word that sets a day: not "every monday", not "Friday's", not inside quotes."""
    spans = _quoted(text)
    for d in DAY_WORD.finditer(text):
        before = text[:d.start()].split()
        if before and before[-1].lower().strip("(") in NOT_A_DAY:
            continue
        if re.match(r"['’]s\b", text[d.end():]) or _inside(spans, d.start()):
            continue
        return d
    return None


def task(text: str, minutes: int, due: str | None, today: dt.date, repeats: bool = False) -> dict:
    """The hints for one task, and the fix code is sure of (None when there is nothing to fix)."""
    new_text, new_minutes, new_due = text, minutes, due
    m = next((x for x in TIME.finditer(new_text) if not _inside(_quoted(new_text), x.start())), None)
    if m:
        n = _minutes(m)
        if n is not None and 1 <= n <= MAX_MINUTES:
            new_minutes = n
            new_text = new_text[:m.start()] + " " + new_text[m.end():]
    d = _day_match(new_text)
    if d:
        day = _day(d.group(1), today)
        if not due or day == due:  # a day already set to another one: the word stays, nothing is guessed
            new_due = due or day
            new_text = new_text[:d.start()] + " " + new_text[d.end():]
    new_text = _clean(new_text)
    fix = {"text": new_text, "minutes": new_minutes, "due": new_due}
    fix = None if (new_text, new_minutes, new_due) == (text, minutes, due) or not new_text else fix
    shown = fix["text"] if fix else text
    hints = []
    first = (shown.split() or [""])[0].lower().strip(".,:;!?")
    if first and shown.isascii() and first.isalpha() and first not in VERBS:  # English-looking text only
        hints.append({"kind": "verb", "text": "Start with what you will do, a verb: “Read …”, “Email …”, “Finish …”."})
    parts = [p for p in JOIN.split(shown) if p]
    if len(parts) > 1 and sum(1 for p in parts[1:] if p.split()[0].lower() in VERBS) >= 1:
        hints.append({"kind": "several", "text": "This looks like more than one task. Split it, so each can be done and ticked on its own."})
    if not (fix["due"] if fix else due) and not repeats:
        hints.append({"kind": "day", "text": "No day: a task without one can wait forever. Give it the day you will do it."})
    if len(shown) > LONG:
        hints.append({"kind": "long", "text": "Long: keep the task short, and put the details in its note."})
    return {"hints": hints, "fix": fix}


def note(body: str) -> str | None:
    """A note with tidy spacing and list marks, or None when it is tidy already. Left as they are: code blocks
    (fenced or indented), a rule (* * *), tags (#private is never made a heading) and a missing last line break."""
    out: list[str] = []
    fenced, blank = False, 0
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            fenced, blank = not fenced, 0
            out.append(line.rstrip())
            continue
        if fenced:
            out.append(line)
            continue
        if line.startswith(("    ", "\t")) and line.strip():  # indented code
            blank = 0
            out.append(line.rstrip())
            continue
        if not line.strip():
            blank += 1
            if blank == 1:
                out.append("")
            continue
        blank = 0
        lead = line[:len(line) - len(line.lstrip())]
        rest = " ".join(line.split())
        if not re.fullmatch(r"[*\-_](\s*[*\-_]){2,}", rest):  # a rule stays a rule
            rest = re.sub(r"^[*•·]\s+", "- ", rest)
        out.append(lead + rest)
    text = "\n".join(out).strip("\n") + ("\n" if body.endswith("\n") else "")
    return None if text == body else text


def routine(steps: list[dict]) -> list[dict] | None:
    """Routine steps with tidy text and their minutes taken from the text, or None when they are tidy already."""
    out = []
    for s in steps:
        text, minutes = s["text"], s.get("minutes", 0)
        m = next((x for x in TIME.finditer(text) if not _inside(_quoted(text), x.start())), None)
        if m and not minutes:
            n = _minutes(m)
            if n is not None and 1 <= n <= MAX_STEP_MINUTES:
                minutes, text = n, text[:m.start()] + " " + text[m.end():]
        out.append({"text": _clean(text) or s["text"], "minutes": minutes})
    return None if out == [{"text": s["text"], "minutes": s.get("minutes", 0)} for s in steps] else out


class Step(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)
    minutes: int = Field(0, ge=0, le=MAX_STEP_MINUTES)


class ApplySteps(BaseModel):
    steps: list[Step] = Field(..., min_length=1, max_length=30)
    expect: list[Step] = Field(..., max_length=30)  # the steps as they were when the change was proposed


def apply_steps(db: DB, rid: str, steps: list[dict], expect: list[dict]) -> int:
    """Change a routine's step texts and minutes in place, so each step keeps its id, its ticks and its history.
    Only while the steps are still what was expected, and only for the same number of steps."""
    with db.transaction():
        rows = db.all("SELECT id, text, minutes FROM routine_steps WHERE routine_id=? AND deleted=0 ORDER BY ord", (rid,))
        if [{"text": r["text"], "minutes": r["minutes"]} for r in rows] != expect:
            raise HTTPException(409, "The routine changed since. Look at it again.")
        if len(steps) != len(rows):
            raise HTTPException(409, "This changes the number of steps, so it cannot keep their ticks. Edit the routine to do it.")
        for r, s in zip(rows, steps, strict=True):
            if (r["text"], r["minutes"]) != (s["text"], s["minutes"]):
                db.update("routine_steps", r["id"], {"text": s["text"], "minutes": s["minutes"]})
    return len(steps)


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/tidy/tasks")
    def api_tidy_tasks():
        """Every open task with its hints and the fix code is sure of. Nothing is changed."""
        today = dt.date.today()
        rows = db.all("SELECT id, text, minutes, due, repeat_rule FROM todos WHERE deleted=0 AND done_at IS NULL ORDER BY ord LIMIT ?", (MAX_TASKS,))
        return {"items": [{"id": r["id"], "text": r["text"], "minutes": r["minutes"], "due": r["due"],
                           **task(r["text"], r["minutes"], r["due"], today, bool(r["repeat_rule"]))} for r in rows]}

    @app.get("/api/tidy/note/{page_id}")
    def api_tidy_note(page_id: str):
        row = db.one("SELECT body FROM pages WHERE id=? AND deleted=0", (page_id,)) if ID.fullmatch(page_id or "") else None
        if not row:
            raise HTTPException(404, "not found")
        fixed = note(row["body"])
        return {"body": fixed if fixed is not None else row["body"], "changed": fixed is not None}

    @app.post("/api/tidy/routine/{rid}/apply")
    def api_tidy_routine_apply(rid: str, body: ApplySteps):
        if not ID.fullmatch(rid or "") or not db.one("SELECT 1 FROM routines WHERE id=? AND deleted=0", (rid,)):
            raise HTTPException(404, "not found")
        return {"changed": apply_steps(db, rid, [s.model_dump() for s in body.steps], [s.model_dump() for s in body.expect])}

    @app.get("/api/tidy/routine/{rid}")
    def api_tidy_routine(rid: str):
        if not ID.fullmatch(rid or "") or not db.one("SELECT 1 FROM routines WHERE id=? AND deleted=0", (rid,)):
            raise HTTPException(404, "not found")
        steps = [{"text": r["text"], "minutes": r["minutes"]} for r in db.all("SELECT text, minutes FROM routine_steps WHERE routine_id=? AND deleted=0 ORDER BY ord", (rid,))]
        fixed = routine(steps)
        return {"steps": fixed if fixed is not None else steps, "changed": fixed is not None}
