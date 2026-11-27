"""Resume briefing (milestone 1.3 of docs/ai/PLAN.md): "where you left off" when you come back to a document.

Two layers, as everywhere in Readhold:
- the facts need no model: when the last session was, which sections you read, what you marked, what you said
  comes next, and where you are now (`facts`). They never depend on a prompt file or on AI being set up;
- with AI switched on, and only when you ask, a model writes a three-line recap from exactly those passages
  (`brief`). It goes through `guard.ask`. Each line may carry a quote; a quote is shown only when it is, word
  for word, in the text that was sent. That proves the passage is real, not that the line follows from it,
  and the page says so. The result is kept in `ai_results` so the same recap is not asked for twice.

The model sees: the sentences you read in that session (by section, latest first when there are many), the
passages you marked, your own notes for the session, and the start of the section you are in. Never the whole
document.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import passages
from ..db import DB
from . import guard, prompts, results
from .port import AIError, AIOff, Port

log = logging.getLogger(__name__)
ID = re.compile(r"[0-9a-f]{32}")
FEATURE = "resume"
MAX_CONTEXT = guard.BUDGETS["resume"]  # characters of source text
MAX_SOURCES = 12
MAX_SECTIONS = 5  # the sections read last in the session
MAX_HIGHLIGHTS = 5
AHEAD = 12  # sentences of the current section, from where you are
MAX_LINES = 3
MIN_QUOTE_WORDS = 5
CAPS = {"text": 300, "point": 400, "next": 300, "quote": 400}


class NoSession(Exception):
    """There is no finished reading session to brief on."""


class Line(BaseModel):
    text: str = Field(max_length=2000)
    anchor: str = Field("", max_length=80)
    quote: str = Field("", max_length=2000)


class Brief(BaseModel):
    recap: list[Line] = Field(default_factory=list, max_length=8)  # empty is allowed: "the sources are too thin"
    point: str = Field("", max_length=2000)
    next: str = Field("", max_length=2000)


def status_error(e: AIError) -> int:
    """The HTTP status for a failed AI call: 409 = something to set up or switch on, 504 = too slow, 502 = the model."""
    return 409 if e.code in ("off", "setup", "no_key", "budget", "cancelled", "changed") else 504 if e.code == "timeout" else 502


# ------------------------------------------------------------------ the facts (no model)
def here(db: DB, doc_id: str) -> dict | None:
    """Where the reader stands in the document: the section and the sentence."""
    return db.one(
        "SELECT c.id AS section_id, c.title AS section_title, d.position AS sentence FROM documents d"
        " JOIN sentences s ON s.document_id=d.id AND s.ord=d.position AND s.deleted=0"
        " JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0 JOIN sections c ON c.id=p.section_id AND c.deleted=0"
        " WHERE d.id=? AND d.deleted=0", (doc_id,))


def facts(db: DB, doc_id: str, mode: str) -> dict:
    session = passages.last_session(db, doc_id)
    if not session:
        return {"session": None, "here": None, "ai": {"mode": mode}, "brief": None}
    kept = None
    if mode != "off":
        try:  # the facts never fail because of the AI layer (a missing prompt file, a damaged kept result)
            prompt = prompts.load(FEATURE)
            kept = results.find(db, FEATURE, doc_id, _key(prompt, context(db, doc_id, session)))
        except Exception:  # noqa: BLE001
            log.exception("Could not look up the kept recap for %s", doc_id)
    return {"session": session, "here": here(db, doc_id), "ai": {"mode": mode}, "brief": kept}


# ------------------------------------------------------------------ what the model may read
def context(db: DB, doc_id: str, session: dict | None = None) -> list[guard.Source]:
    session = session or passages.last_session(db, doc_id)
    if not session:
        raise NoSession()
    name = db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or ""
    live = " JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0 JOIN sections c ON c.id=p.section_id AND c.deleted=0"
    sources: list[guard.Source] = []
    # 1. what was read in that session, section by section
    rows = db.all(f"SELECT s.ord, s.text, s.read_at, p.section_id FROM sentences s{live}"
                  " WHERE s.document_id=? AND s.deleted=0 AND s.read_at>=? AND s.read_at<=? ORDER BY s.ord", (doc_id, session["started_at"], session["ended_at"]))
    if not rows and session["start_ord"] is not None and session["last_ord"] is not None:
        lo, hi = sorted((session["start_ord"], session["last_ord"]))  # only re-read text: the stretch between start and stop
        rows = db.all(f"SELECT s.ord, s.text, s.read_at, p.section_id FROM sentences s{live}"
                      " WHERE s.document_id=? AND s.deleted=0 AND s.ord BETWEEN ? AND ? ORDER BY s.ord", (doc_id, lo, hi))
    by_section: dict[str, list[dict]] = {}
    for r in rows:
        by_section.setdefault(r["section_id"], []).append(r)
    # when there were many, the sections read last (by the clock), shown in the order of the document
    latest = sorted(by_section.values(), key=lambda part: max(r["read_at"] or "" for r in part))[-MAX_SECTIONS:]
    for part in sorted(latest, key=lambda part: part[0]["ord"]):
        sources.append(guard.Source(f"{doc_id}:{part[0]['ord']}", "\n".join(r["text"] for r in part), "imported", name))
    # 2. the passages marked in that session
    marked = session["highlights"][:MAX_HIGHLIGHTS]
    for h in marked:
        sources.append(guard.Source(f"{doc_id}:{h['sentence']}", h["text"], "imported", name))
    # 3. the reader's own words: their question, their next-step line, their notes on what they marked
    own = []
    if session["question"]:
        own.append(f"The question I was reading for: {session['question']}")
    if session["next_step"]:
        own.append(f"What I said comes next: {session['next_step']}")
    own += [f"My note on a marked passage: {h['note']}" for h in marked if h["note"]]
    if own:
        sources.append(guard.Source(f"session:{session['id']}", "\n".join(own), "yours"))
    # 4. where the reader is now: the rest of that section, a few sentences
    at = here(db, doc_id)
    if at:
        ahead = db.all("SELECT s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0 WHERE p.section_id=? AND s.deleted=0 AND s.ord>=? ORDER BY s.ord LIMIT ?",
                       (at["section_id"], at["sentence"], AHEAD))
        if ahead:
            sources.append(guard.Source(f"{doc_id}:{at['sentence']}", f"(The section the reader is in now: {at['section_title']})\n" + "\n".join(r["text"] for r in ahead), "imported", name))
    sources = sources[-MAX_SOURCES:]
    share = MAX_CONTEXT // max(1, len(sources))
    for s in sources:
        if len(s.text) > share:
            s.text, s.cut = s.text[:share].rsplit(" ", 1)[0] + " […]", True  # said in the AI log as "trimmed"
    return sources


def _key(prompt: prompts.Prompt, sources: list[guard.Source]) -> str:
    """Everything the recap is made from: the prompt and every source as it would be sent. A changed note, a
    removed highlight or a new position gives a new key, so an old recap is never shown for new inputs."""
    return results.key(prompt.hash, *(f"{s.anchor}\n{s.trust}\n{s.text}" for s in sources))


# ------------------------------------------------------------------ the recap
def _line(db: DB, doc_id: str, line: dict, sources: list[guard.Source]) -> dict:
    """One recap line. Its quote is shown only when it is, word for word, in an imported source that was sent."""
    out: dict[str, Any] = {"text": guard.safe_output(line["text"], CAPS["text"]).text, "verified": False}
    quote = line.get("quote") or ""
    held = [s for s in sources if s.trust == "imported" and s.anchor.startswith(doc_id + ":") and guard.quote_in(quote, s.text, MIN_QUOTE_WORDS)]
    if held:
        given = next((s for s in held if s.anchor == line.get("anchor")), held[0])
        got = guard.verify_citations(db, [{"anchor": given.anchor, "quote": quote}])
        if got.kept:
            out.update(verified=True, quote=guard.safe_output(quote, CAPS["quote"]).text, sentence=got.kept[0]["sentence"], document_id=doc_id)
    return out


def brief(port: Port, db: DB, doc_id: str, fresh: bool = False) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()  # with AI off nothing is shown either, not even a kept recap
    session = passages.last_session(db, doc_id)
    if not session:
        raise NoSession()
    prompt = prompts.load(FEATURE)
    sources = context(db, doc_id, session)
    key = _key(prompt, sources)
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, doc_id, key)
        if kept and not fresh:
            return kept
        result = guard.ask(port, db, FEATURE, prompt.text, sources, budget=FEATURE, schema=Brief, prompt_version=prompt.version)
        data = result.data
        lines = [_line(db, doc_id, x, sources) for x in data["recap"] if x["text"].strip()][:MAX_LINES]
        proven = sum(1 for x in lines if x["verified"])
        payload = {
            "recap": lines,
            "point": guard.safe_output(data.get("point") or "", CAPS["point"]).text,
            "next": guard.safe_output(data.get("next") or "", CAPS["next"]).text,
            "status": "verified" if lines and proven == len(lines) else "partly" if proven else "unverified",
            "links": list(dict.fromkeys(result.links)),
            "session_id": session["id"],
            "warning": result.warning,
        }
        return results.keep(db, FEATURE, doc_id, key, payload, prompt.version, result.log_id, replaces=kept["id"] if kept else None)


# ------------------------------------------------------------------ routes
class BriefIn(BaseModel):
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    def need_doc(doc_id: str) -> None:
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
            raise HTTPException(404, "document not found")

    def mode() -> str:
        m = port.settings().get("ai_mode")
        return m if m in ("local", "cloud") else "off"

    @app.get("/api/documents/{doc_id}/resume")
    def api_resume(doc_id: str):
        need_doc(doc_id)
        return facts(db, doc_id, mode())

    @app.post("/api/documents/{doc_id}/resume/brief")
    def api_resume_brief(doc_id: str, body: BriefIn):
        """Ask the model for the recap. A plain `def`: it runs on a worker thread, and the reader is never blocked."""
        need_doc(doc_id)
        try:
            return {"brief": brief(port, db, doc_id, body.fresh)}
        except NoSession:
            raise HTTPException(409, "There is no finished reading session of this document yet.") from None
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None
