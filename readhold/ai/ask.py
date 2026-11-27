"""Ask this document (milestone 2.2 of docs/ai/PLAN.md): a question about the document you are reading.

Two layers, as everywhere in Readhold:
- without a model: the passages of the document that match the question, best first (`passages_for`, the
  full-text index of sections from Phase 0). That is already an answer you can read;
- with AI switched on, when you press Ask: one model call with the question and the sections that match best
  (never the whole document). The model answers only from them, or says "not found". Each citation's quote must
  be, word for word, in the text that was sent and in the cited section (`guard.quote_in`, `verify_citations`,
  milestone 2.1). An answer with no checkable quote is shown labelled "unverified" (owner's decision, 2026-11-25).

A question no passage matches is "not found" without asking the model at all.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import passages
from ..db import DB
from ..think import STOP
from . import guard, prompts, results
from .port import AIError, AIOff, Port
from .resume import status_error

ID = re.compile(r"[0-9a-f]{32}")
FEATURE = "ask"
MAX_SECTIONS = 5  # the best-matching sections sent with a question
MAX_CONTEXT = guard.BUDGETS[FEATURE] - 2_000  # characters of section text; the rest is for the question and the fences
MAX_CITATIONS = 4
MIN_QUOTE_WORDS = 4
MAX_QUESTION = guard.USER_LIMITS["ask"]
CAPS = {"answer": 1200, "quote": 400}


class Invalid(Exception):
    pass


class Citation(BaseModel):
    anchor: str = Field("", max_length=80)
    quote: str = Field("", max_length=2000)


class AskOut(BaseModel):
    found: bool
    answer: str = Field("", max_length=8000)
    citations: list[Citation] = Field(default_factory=list, max_length=12)


def _question(text: str) -> str:
    q = " ".join(guard.sanitize(text or "").split())
    if not q:
        raise Invalid("Type a question first.")
    if len(q) > MAX_QUESTION:
        raise Invalid(f"Keep the question under {MAX_QUESTION} characters.")
    return q


def _cache_question(q: str) -> str:
    """The question as the kept answer remembers it: case, spacing and a final ?, ! or . do not matter;
    other punctuation does ("C++" is not "C")."""
    return " ".join(q.split()).casefold().rstrip("?!. ")


NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
ACRONYM = re.compile(r"(?<![\w])[A-Z][A-Z0-9+#]{1,7}(?![\w])")  # RL, AI, GPU, C++, C#: short, but they matter
WORD = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)
MAX_TERMS = 8


def _stem(w: str) -> str:
    """A light, English-only cut, so a word finds its relatives by prefix: "gate" and "gating" both search "gat",
    "processes" searches "process". Other scripts are kept as written (the index holds them as written)."""
    if not w.isascii() or len(w) <= 3:
        return w
    for end in ("ing", "ies", "es", "ed", "s", "e"):
        if w.endswith(end) and len(w) - len(end) >= 3 and not (end == "s" and w.endswith(("ss", "us", "is")))                 and not (end == "ed" and w.endswith("eed")):  # "speed" is not "spe" + "ed"
            return w[: -len(end)]
    return w


def _terms(question: str) -> str:
    """The words to search for. Common words are left out, so "what is the" matches nothing on its own (and a
    question of only common words is "not found" without a model). Numbers and acronyms come first and are kept
    however short; then the longest words, at most MAX_TERMS in all."""
    keep: list[str] = [*NUMBER.findall(question), *(a.casefold() for a in ACRONYM.findall(question))]
    plain = []
    for w in WORD.findall(question.casefold()):
        w = w.strip("'’-")
        if len(w) >= 3 and w not in STOP and w.replace("'", "").replace("’", "") not in STOP:
            plain.append(_stem(w))
    plain.sort(key=len, reverse=True)  # the longest words say the most
    return " ".join(list(dict.fromkeys([*keep, *plain]))[:MAX_TERMS])


def passages_for(db: DB, doc_id: str, question: str, limit: int = MAX_SECTIONS) -> list[dict]:
    """The sections of this document that match the question, best first. No model."""
    terms = _terms(question)
    return passages.search_sections(db, terms, limit=limit, document_id=doc_id) if terms else []


def _around(rows: list[dict], at: int, room: int) -> tuple[str, bool]:
    """The sentences of a section around the one that matched, growing outwards until `room` is used."""
    i = next((k for k, r in enumerate(rows) if r["ord"] == at), 0)
    lo = hi = i
    size = len(rows[i]["text"])
    while size < room and (lo > 0 or hi < len(rows) - 1):
        if hi < len(rows) - 1 and size + len(rows[hi + 1]["text"]) + 1 <= room:
            hi += 1
            size += len(rows[hi]["text"]) + 1
        elif lo > 0 and size + len(rows[lo - 1]["text"]) + 1 <= room:
            lo -= 1
            size += len(rows[lo]["text"]) + 1
        else:
            break
        if lo > 0 and size + len(rows[lo - 1]["text"]) + 1 <= room:
            lo -= 1
            size += len(rows[lo]["text"]) + 1
    text = "\n".join(r["text"] for r in rows[lo:hi + 1])
    cut = lo > 0 or hi < len(rows) - 1
    if len(text) > room:  # one sentence longer than the room
        text = text[:room].rsplit(" ", 1)[0]
        cut = True
    return ("[…] " if lo > 0 else "") + text + (" […]" if cut and hi < len(rows) - 1 or len(text) >= room else ""), cut


def sources_for(db: DB, doc_id: str, hits: list[dict]) -> list[guard.Source]:
    """Each matching section, whole when it fits; a long one around the sentence that matched. Room a short
    section does not use goes to the others."""
    name = db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or ""
    sections = []
    for hit in hits:
        rows = db.all("SELECT s.ord, s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                      " WHERE p.section_id=? AND s.deleted=0 ORDER BY s.ord", (hit["section_id"],))
        if rows:
            sections.append((hit, rows, sum(len(r["text"]) + 1 for r in rows)))
    left, out = MAX_CONTEXT, {}
    for n, (hit, rows, size) in enumerate(sorted(sections, key=lambda x: x[2])):  # the short ones first, so they are whole
        room = left // (len(sections) - n)
        head = f"(Section: {hit['section_title']})\n"
        body, cut = ("\n".join(r["text"] for r in rows), False) if size <= room - len(head) else _around(rows, hit["sentence"], room - len(head))
        left -= len(head) + len(body)
        src = guard.Source(f"{doc_id}:{rows[0]['ord']}", head + body, "imported", name)
        src.cut = cut
        out[hit["section_id"]] = src
    return [out[h["section_id"]] for h, _, _ in sections]  # in the order of the search: best first


def _citation(db: DB, doc_id: str, c: dict, sources: list[guard.Source]) -> dict:
    """One citation, checked: shown only when its quote is in a source that was sent and in that section."""
    out: dict[str, Any] = {"verified": False}
    quote = c.get("quote") or ""
    held = [s for s in sources if guard.quote_in(quote, s.text, MIN_QUOTE_WORDS)]
    held.sort(key=lambda s: s.anchor != c.get("anchor"))  # the source the model named first
    for s in held:
        got = guard.verify_citations(db, [{"anchor": s.anchor, "quote": quote}])
        if got.kept:
            title = db.scalar("SELECT title FROM sections WHERE id=?", (got.kept[0]["section_id"],)) or ""
            out.update(verified=True, quote=guard.safe_output(quote, CAPS["quote"]).text, sentence=got.kept[0]["sentence"],
                       section_title=title, document_id=doc_id)
            break
    return out


def ask(port: Port, db: DB, doc_id: str, question: str, fresh: bool = False) -> dict:
    q = _question(question)  # a question that is not one is a 422, with AI on or off
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    hits = passages_for(db, doc_id, q)
    if not hits:  # nothing in the document matches: no model is asked
        return {"question": q, "found": False, "answer": "", "citations": [], "status": "not_found", "searched": 0, "links": []}
    sources = sources_for(db, doc_id, hits)
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, _cache_question(q), *(f"{s.anchor}\n{s.text}" for s in sources))
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, doc_id, key)
        if kept and not fresh:
            return kept
        r = guard.ask(port, db, FEATURE, prompt.text, sources, budget=FEATURE, question=q, schema=AskOut, prompt_version=prompt.version)
        data = r.data
        if data["found"] and guard.safe_output(data.get("answer") or "").text:
            cites, seen = [], set()
            for c in (data.get("citations") or [])[:MAX_CITATIONS * 3]:  # the same passage cited twice counts once
                one = _citation(db, doc_id, c, sources)
                mark = (one.get("sentence"), guard._plain(one.get("quote", ""))) if one["verified"] else ("x", guard._plain(c.get("quote") or ""))
                if mark not in seen:
                    seen.add(mark)
                    cites.append(one)
            cites = cites[:MAX_CITATIONS]
            proven = sum(1 for c in cites if c["verified"])
            payload = {"question": q, "found": True, "answer": guard.safe_output(data["answer"], CAPS["answer"]).text, "citations": cites,
                       "status": "verified" if cites and proven == len(cites) else "partly" if proven else "unverified"}
        else:  # "not found" wins over anything the model wrote beside it
            payload = {"question": q, "found": False, "answer": "", "citations": [], "status": "not_found"}
        payload.update(searched=len(sources), links=list(dict.fromkeys(r.links)), warning=r.warning)
        return results.keep(db, FEATURE, doc_id, key, payload, prompt.version, r.log_id, replaces=kept["id"] if kept else None)


# ------------------------------------------------------------------ routes
class AskIn(BaseModel):
    question: str = Field(max_length=100_000)  # longer than the limit: _question explains it in words
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    def need_doc(doc_id: str) -> None:
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
            raise HTTPException(404, "document not found")

    def mode() -> str:
        m = port.settings().get("ai_mode")
        return m if m in ("local", "cloud") else "off"

    @app.get("/api/documents/{doc_id}/ask")
    def api_ask_passages(doc_id: str, q: str = ""):
        """The passages that match a question. No model: this works with AI off."""
        need_doc(doc_id)
        try:
            question = _question(q)
        except Invalid as e:
            raise HTTPException(422, str(e)) from None
        return {"passages": passages_for(db, doc_id, question), "ai": {"mode": mode()}}

    @app.post("/api/documents/{doc_id}/ask")
    def api_ask(doc_id: str, body: AskIn):
        """Ask the model. A plain `def`: it runs on a worker thread, and the reader is never blocked."""
        need_doc(doc_id)
        try:
            return {"result": ask(port, db, doc_id, body.question, body.fresh)}
        except Invalid as e:
            raise HTTPException(422, str(e)) from None
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None
