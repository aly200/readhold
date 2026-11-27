"""Reading plan with a model (milestone 3.1 of docs/ai/PLAN.md): the model sizes and orders, code schedules.

The non-AI version is the whole plan already (`readhold/readplan.py`): you choose the order and how hard each
document is, and code spreads what is left over your days, never past your minutes a day or your deadline. With
AI on, and only when you ask, a model reads for each chosen document its title, what is left of it (words and
minutes, worked out by code), the titles of the sections left, its opening and the opening of the part where you
go on, plus why you read it and your goal if you wrote them. It never sees whole documents. It answers with an order
and a level (easy, medium, hard) per document, and one reason each.

What comes back is checked before you see it:
- a document is placed once; a number that is not one of yours, or a second mention, is dropped; documents the
  model left out follow in your order, marked as not placed by it;
- a level that is not one of the three is not used ("medium");
- a reason rests on a quote that is, on whole words, in the text sent for that document and passes
  `verify_citations`; it is then shown in the document's own words. A reason without one is shown labelled as the
  model's guess. The levels are always labelled as its estimate; code turns them into time (x0.8, x1, x1.4).

Nothing changes when the suggestion arrives. You use it (it fills in the order and levels, with Undo) or not; the
schedule is then made by code, and tasks you add from it say in their note that a model ordered them.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import readplan
from ..db import DB
from . import guard, prompts, results
from .notes import _own_words
from .port import AIError, AIOff, Port
from .resume import status_error

ID = re.compile(r"[0-9a-f]{32}")
FEATURE = "plan"
MAX_DOCS = readplan.MAX_DOCS
OPENING = 420  # characters of a document's opening, and of the part where you go on
MAX_TITLES = 12
MIN_QUOTE_WORDS = 4
CAPS = {"reason": 240, "quote": 400}


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


class Pick(BaseModel):
    """Loose on purpose: a field the model left null or wrote with the wrong type drops that part of the entry, not
    the whole answer. Each field is checked by hand below (`_number`, `_text`)."""
    document: Any = None  # kept as sent, so `true` stays a bool and is not document 1 (`_number`)
    difficulty: Any = None
    reason: Any = None
    quote: Any = None


class PlanOut(BaseModel):
    order: list[Pick] = Field(default_factory=list, max_length=60)


# ------------------------------------------------------------------ what the model reads
def _opening(db: DB, section_id: str, first: int) -> str:
    """The sentences of a section from `first` on, up to OPENING characters."""
    out, size = [], 0
    for r in db.all("SELECT s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                    " WHERE p.section_id=? AND s.deleted=0 AND s.ord>=? ORDER BY s.ord LIMIT 12", (section_id, first)):
        if out and size + len(r["text"]) > OPENING:
            break
        out.append(r["text"])
        size += len(r["text"]) + 1
    return " ".join(out)


def _sources(db: DB, k: int, left: dict, wpm: int) -> list[guard.Source]:
    doc_id, title = left["id"], " ".join(left["title"].split()) or "Untitled"
    start = db.one("SELECT c.id, MIN(s.ord) AS sentence FROM sections c JOIN paragraphs p ON p.section_id=c.id AND p.deleted=0"
                   " JOIN sentences s ON s.paragraph_id=p.id AND s.deleted=0 WHERE c.document_id=? AND c.deleted=0 AND c.hidden=0"
                   " GROUP BY c.id ORDER BY c.ord LIMIT 1", (doc_id,))
    titles = [s["title"][:60] for s in left["sections"][:MAX_TITLES]]
    more = len(left["sections"]) - len(titles)
    head = (f"(Document {k}: {title})\n"
            f"(Left to read: {left['words_left']} words, about {readplan.minutes(left['words_left'], wpm)} minutes at {wpm} words a minute;"
            f" {len(left['sections'])} section{'s' if len(left['sections']) != 1 else ''} left)\n"
            f"(Sections left: {'; '.join(titles)}{f'; and {more} more' if more > 0 else ''})\n(Opening)\n")
    out = [guard.Source(f"{doc_id}:{start['sentence']}", head + _opening(db, start["id"], start["sentence"]), "imported", left["source"] or "")]
    on = left["sections"][0]
    if on["id"] != start["id"]:  # you are further on: the model also reads where you go on from
        out.append(guard.Source(f"{doc_id}:{on['sentence']}", f"(Document {k}, where the reader goes on: {on['title'][:60]})\n" + _opening(db, on["id"], on["sentence"]),
                                "imported", left["source"] or ""))
    why = " ".join((left["why"] or "").split())
    if why:
        out.append(guard.Source(f"why:{doc_id}", f"(Document {k}) Why I read it: {why[:300]}", "yours"))
    return out


def _text(value) -> str:
    """A text field of the answer: a string (cut at 2,000 characters), or nothing."""
    return value[:2000] if isinstance(value, str) else ""


def _number(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"\s*(?:document\s*)?(\d{1,3})\s*", str(value), re.I)
    return int(m.group(1)) if m else None


def _checked(db: DB, quote: str, sources: list[guard.Source], sent: dict) -> dict:
    """A quote counts only when it is in the text sent for this document and in the document itself."""
    for s in sources:
        if s.trust != "imported" or not guard.quote_in(quote, sent.get(s.anchor, ""), MIN_QUOTE_WORDS):
            continue
        got = guard.verify_citations(db, [{"anchor": s.anchor, "quote": quote}])
        if got.kept:
            k = got.kept[0]
            own = _own_words(db, k["section_id"], k["sentence"], quote)
            return {"verified": True, "quote": own or guard.safe_output(quote, CAPS["quote"]).text, "sentence": k["sentence"]}
    return {"verified": False}


def suggest(port: Port, db: DB, doc_ids: list[str], goal: str = "", fresh: bool = False) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    if len(set(doc_ids)) != len(doc_ids):
        raise Invalid("Each document once, please.")
    wpm = int(port.settings().get("wpm") or 250)
    lefts = []
    for d in doc_ids:
        left = readplan.remaining(db, d)
        if left is None:
            raise NotFound()
        lefts.append(left)
    todo = [x for x in lefts if x["words_left"]]
    if len(todo) < 2:
        raise Invalid("Choose at least two documents with something left to read: one has no order to suggest.")
    goal = guard.user_text(goal, "topic") if goal.strip() else ""
    per_doc = [_sources(db, k + 1, x, wpm) for k, x in enumerate(todo)]
    sources = [s for group in per_doc for s in group]
    prompt = prompts.load(FEATURE)
    target = results.key(*sorted(doc_ids))[:32]
    key = results.key(prompt.hash, goal, str(wpm), *(f"{s.anchor}\n{s.text}" for s in sources))
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, target, key)
        if kept and not fresh:
            return kept
        r = guard.ask(port, db, FEATURE, prompt.text, sources, budget=FEATURE, question=goal or None, schema=PlanOut, prompt_version=prompt.version)
        order, seen = [], set()
        for e in r.data["order"][:MAX_DOCS * 3]:
            n = _number(e.get("document"))
            if n is None or not 1 <= n <= len(todo) or todo[n - 1]["id"] in seen:
                continue
            left = todo[n - 1]
            seen.add(left["id"])
            level = e["difficulty"].strip().lower() if isinstance(e.get("difficulty"), str) else ""
            reason = guard.safe_output(_text(e.get("reason")), CAPS["reason"]).text
            quote = _text(e.get("quote"))
            one = {"document_id": left["id"], "title": left["title"], "level": level if level in readplan.LEVELS else "medium",
                   "level_from_model": level in readplan.LEVELS, "reason": reason, "placed": True, "verified": False}
            if reason and quote.strip():
                one.update(_checked(db, quote, per_doc[n - 1], r.sent))
            order.append(one)
        for x in lefts:  # what the model left out (or that has nothing left) follows in your order
            if x["id"] not in seen:
                order.append({"document_id": x["id"], "title": x["title"], "level": "medium", "level_from_model": False, "reason": "",
                              "placed": False, "verified": False, "nothing_left": not x["words_left"]})
        reasons = [x for x in order if x["placed"] and x["reason"]]
        proven = sum(1 for x in reasons if x["verified"])
        payload = {"order": order, "goal": goal, "document_ids": doc_ids,
                   "status": "verified" if reasons and proven == len(reasons) else "partly" if proven else "unverified",
                   "links": list(dict.fromkeys(r.links)), "warning": r.warning,
                   "cut": bool(r.checks.get("trimmed")), "left_out": int(r.checks.get("left_out", 0))}
        return results.keep(db, FEATURE, target, key, payload, prompt.version, r.log_id, replaces=kept["id"] if kept else None, target_type="plan")


# ------------------------------------------------------------------ routes
class SuggestIn(BaseModel):
    document_ids: list[str] = Field(..., min_length=2, max_length=MAX_DOCS)
    goal: str = Field("", max_length=200)
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/reading-plan/suggest")
    def api_plan_suggest(body: SuggestIn):
        """A plain `def`: the call runs on a worker thread, so the page never waits on it."""
        try:
            return {"result": suggest(port, db, body.document_ids, body.goal, body.fresh)}
        except NotFound:
            raise HTTPException(404, "That document is not in your library.") from None
        except Invalid as e:
            raise HTTPException(409, str(e)) from None
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None
