"""Explain selection (milestone 1.4 of docs/ai/PLAN.md): a plain explanation of a passage you selected.

You choose the level (simple, student, expert), so you decide the depth, not the model. You can write your own
take first; the answer then says what it got right. The model reads three things and nothing else: the passage,
the text around it in the same paragraph, and the title of its section.

Only text of the document is ever sent as the passage. The page tells the server which sentences were selected
and, optionally, the selected words: the words are used only when they are, as written, part of those sentences.
Otherwise the whole sentences are sent. A selection must stay inside one paragraph.

The answer goes through `guard.ask`. Its quote and its terms are checked against exactly the text that was
sent. It is kept in `ai_results`. Nothing is written into your notes unless you press "Save as a note"; a note
saved that way is marked as the model's until you change its text.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..db import DB
from . import guard, prompts, results
from .port import AIError, AIOff, Port
from .resume import status_error

ID = re.compile(r"[0-9a-f]{32}")
FEATURE = "explain"
MAX_STRETCH = 12  # sentences in one selection
MAX_SELECTED = 1800  # characters of the passage itself (a code block is one "sentence" and can be long)
MAX_AROUND = 1800  # characters of the paragraph around it
MAX_ORD = 10_000_000
MAX_TERMS = 5
MIN_QUOTE_WORDS = 3  # a selection can be one short line of code
CAPS = {"explanation": 1500, "meaning": 300, "feedback": 500, "quote": 400}
LEVELS = {
    "simple": "Level: simple. Write for someone new to the subject: 2 to 4 short sentences, everyday words, no jargon. If a technical word is needed, say what it means in the same sentence.",
    "student": "Level: student. Write for a student of the subject: 3 to 6 sentences, the correct terms with a short reason for each step.",
    "expert": "Level: expert. Write for someone who knows the field: 2 to 5 dense sentences, precise terms, what the passage assumes and what it implies.",
}


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


class Term(BaseModel):
    term: str = Field(max_length=200)
    meaning: str = Field(max_length=2000)


class Explained(BaseModel):
    explanation: str = Field(min_length=1, max_length=8000)
    terms: list[Term] = Field(default_factory=list, max_length=12)
    feedback: str = Field("", max_length=4000)
    quote: str = Field("", max_length=2000)


def _one_spacing(text: str) -> str:
    return " ".join(guard.sanitize(text).split())


def passage(db: DB, doc_id: str, first: int, last: int, text: str = "") -> tuple[list[guard.Source], str]:
    """The sources for a selection, and all the document text in them (what a quote or a term may come from)."""
    if last < first or last - first + 1 > MAX_STRETCH:
        raise Invalid(f"Select at most {MAX_STRETCH} sentences.")
    rows = db.all("SELECT s.ord, s.text, s.paragraph_id, p.section_id FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                  " JOIN documents d ON d.id=s.document_id WHERE s.document_id=? AND s.deleted=0 AND d.deleted=0 AND s.ord BETWEEN ? AND ? ORDER BY s.ord", (doc_id, first, last))
    if not rows or rows[0]["ord"] != first:
        raise NotFound()
    if len({r["paragraph_id"] for r in rows}) > 1:
        raise Invalid("Select text inside one paragraph.")
    whole = "\n".join(r["text"] for r in rows)
    selected = whole
    if text.strip():
        # the selected words are used only when they are, as written, in those sentences; then they are the
        # document's own characters. Words that match only loosely (a formula drawn differently on the page)
        # fall back to the whole sentences. Anything else is refused: this route sends document text only.
        typed, plain = _one_spacing(text), guard._plain(text)
        if typed and typed in _one_spacing(whole):
            selected = typed
        elif not plain or plain not in guard._plain(whole):
            raise Invalid("That text is not in this passage.")
    if len(selected) > MAX_SELECTED:
        selected = selected[:MAX_SELECTED].rsplit(" ", 1)[0] + " […]"
    name = db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or ""
    title = db.scalar("SELECT title FROM sections WHERE id=?", (rows[0]["section_id"],)) or ""
    para = db.all("SELECT ord, text FROM sentences WHERE paragraph_id=? AND deleted=0 ORDER BY ord", (rows[0]["paragraph_id"],))
    # the paragraph, or when it is long the part of it nearest the selection: sentences are added outwards until the cap
    lo = next(i for i, r in enumerate(para) if r["ord"] >= first)
    hi = max(i for i, r in enumerate(para) if r["ord"] <= last)
    size = sum(len(r["text"]) for r in para[lo:hi + 1])
    while (lo > 0 or hi < len(para) - 1) and size < MAX_AROUND:
        if lo > 0:
            lo -= 1
            size += len(para[lo]["text"])
        if hi < len(para) - 1 and size < MAX_AROUND:
            hi += 1
            size += len(para[hi]["text"])
    around = "\n".join(r["text"] for r in para[lo:hi + 1])
    cut = len(around) > MAX_AROUND
    if cut:
        around = around[:MAX_AROUND].rsplit(" ", 1)[0] + " […]"
    sources = [
        guard.Source(f"{doc_id}:{first}", "(The selected passage)\n" + selected, "imported", name, cut=selected.endswith(" […]")),
        guard.Source(f"{doc_id}:{para[lo]['ord']}", f"(The text around it, from the section “{title}”)\n" + around, "imported", name, cut=cut or lo > 0 or hi < len(para) - 1),
    ]
    return sources, selected + "\n" + around


def _saved(db: DB, shaped: dict) -> dict:
    """`saved` is true only while the note made from this result still exists."""
    note_id = shaped.get("note_id")
    shaped["saved"] = bool(note_id and db.one("SELECT 1 FROM notes WHERE id=? AND deleted=0", (note_id,)))
    return shaped


def explain(port: Port, db: DB, doc_id: str, first: int, last: int, level: str, text: str = "", attempt: str = "", fresh: bool = False) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()  # with AI off nothing is shown either, not even a kept answer
    sources, sent = passage(db, doc_id, first, last, text)
    attempt = guard.user_text(attempt, "ask") if attempt.strip() else ""
    if attempt:
        sources.append(guard.Source(f"attempt:{doc_id}", "My first attempt at saying what the passage means: " + attempt, "yours"))
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, LEVELS[level], *(f"{x.anchor}\n{x.trust}\n{x.text}" for x in sources))
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, doc_id, key)
        if kept and not fresh:
            return _saved(db, kept)
        result = guard.ask(port, db, FEATURE, f"{prompt.text}\n\n{LEVELS[level]}", sources, budget=FEATURE, schema=Explained, prompt_version=prompt.version)
        data = result.data
        within = guard._plain(sent)  # exactly the document text that was sent
        terms = [{"term": guard.safe_output(t["term"], 120).text, "meaning": guard.safe_output(t["meaning"], CAPS["meaning"]).text}
                 for t in data.get("terms") or [] if guard.word_in(guard._plain(t["term"]), within)][:MAX_TERMS]
        payload = {
            "explanation": guard.safe_output(data["explanation"], CAPS["explanation"]).text,
            "terms": terms,
            "feedback": guard.safe_output(data.get("feedback") or "", CAPS["feedback"]).text if attempt else "",
            "quote": "",
            "status": "unverified",
            "links": list(dict.fromkeys(result.links)),
            "level": level, "document_id": doc_id, "sentence": first, "end_sentence": last, "warning": result.warning,
        }
        quote = data.get("quote") or ""
        if guard.quote_in(quote, sent, MIN_QUOTE_WORDS) and guard.verify_citations(db, [{"anchor": f"{doc_id}:{first}", "quote": quote}]).kept:
            payload.update(quote=guard.safe_output(quote, CAPS["quote"]).text, status="verified")
        return _saved(db, results.keep(db, FEATURE, doc_id, key, payload, prompt.version, result.log_id, replaces=kept["id"] if kept else None))


def save_as_note(db: DB, result_id: str) -> dict:
    """Keep an explanation as a margin note on its sentence. The note says a model wrote it, until you change it.
    Pressing twice, or twice at once, makes one note."""
    if not ID.fullmatch(result_id or ""):
        raise NotFound()
    with results.once("note", result_id):
        row = db.one("SELECT * FROM ai_results WHERE id=? AND feature=? AND deleted=0", (result_id, FEATURE))
        if not row:
            raise NotFound()
        payload = json.loads(row["payload"])
        note = db.one("SELECT * FROM notes WHERE id=? AND deleted=0", (payload.get("note_id", ""),)) if payload.get("note_id") else None
        if not note:
            if not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (payload["document_id"],)):
                raise NotFound()
            note = db.insert("notes", {"document_id": payload["document_id"], "sentence": payload["sentence"], "origin": "ai",
                                       "text": f"AI explanation ({payload['level']}): {payload['explanation']}"[:5000]})
            payload["note_id"] = note["id"]
            db.update("ai_results", result_id, {"payload": json.dumps(payload, ensure_ascii=False), "status": "accepted"})
        return note


class ExplainIn(BaseModel):
    sentence: int = Field(ge=0, le=MAX_ORD)
    end_sentence: int = Field(ge=0, le=MAX_ORD)
    level: Literal["simple", "student", "expert"] = "student"
    text: str = Field("", max_length=1200)
    attempt: str = Field("", max_length=600)
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/documents/{doc_id}/explain")
    def api_explain(doc_id: str, body: ExplainIn):
        """A plain `def`: the call runs on a worker thread, so the reader never waits on it."""
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
            raise HTTPException(404, "document not found")
        try:
            return {"result": explain(port, db, doc_id, body.sentence, body.end_sentence, body.level, body.text, body.attempt, body.fresh)}
        except NotFound:
            raise HTTPException(404, "That passage is not in the document.") from None
        except Invalid as e:
            raise HTTPException(422, str(e)) from None
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None

    @app.post("/api/ai/results/{result_id}/note")
    def api_result_note(result_id: str):
        try:
            return {"note": save_as_note(db, result_id)}
        except NotFound:
            raise HTTPException(404, "not found") from None
