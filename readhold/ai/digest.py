"""Document digest (milestone 1.5 of docs/ai/PLAN.md): the shape of a document before its detail.

Two layers, as everywhere in Readhold:
- the facts need no model: the outline (from the parser), the word count and the reading time at your speed
  (`facts`). Code does the exact work;
- with AI switched on, and only when you ask, a model writes a summary, the key ideas, keywords and a guess at
  the difficulty. A long document is never sent at once. It is cut into parts at section boundaries (`chunks`);
  each part is summarised on its own (the map step, one call per part, `digest_map`), then the part summaries are
  combined (the reduce step, one call, `digest`). The reduce step never sees the document, only the summaries
  and the quotes they rest on.

It runs in the background (`Job`), with progress, and can be stopped. Each part's summary is kept as soon as it
is made, so a stopped or failed digest continues where it stopped. A part the model cannot summarise is skipped,
not fatal. Every call goes through `guard.ask`; quotes are checked against the text of the part they came from,
and a keyword that is not in the document is dropped.
"""
from __future__ import annotations

import contextvars
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..db import DB, new_id
from . import guard, privacy, prompts, results
from .port import AIError, AIOff, Cancelled, CouldNotGenerate, Port

log = logging.getLogger(__name__)
ID = re.compile(r"[0-9a-f]{32}")
FEATURE, MAP = "digest", "digest_map"
CHUNK = 6_000  # characters a part aims at
MAX_CHUNK = 14_000  # the most a part may grow to, to keep a long document under MAX_CHUNKS (the map budget is 16,000)
MAX_CHUNKS = 40  # parts; a document that needs more is refused (about 250 pages)
GROW = 1.25
MIN_QUOTE_WORDS = 5
MAX_POINTS, MAX_IDEAS, MAX_KEYWORDS = 3, 6, 12
CAPS = {"summary": 1200, "part": 400, "point": 220, "idea": 260, "quote": 300, "keyword": 40}


HEADER_ROOM = 800  # characters kept free in each part for its header line
HEADER_TITLES = 6  # section titles named in a part's header


class TooLong(Exception):
    pass


class Nothing(Exception):
    """The document has no text the digest may read (it is empty, or every section is hidden)."""


def _split_long(sents: list[dict], most: int) -> list[dict]:
    """A sentence longer than `most` characters (a code file on one line, a PDF without full stops) is cut into
    pieces at spaces, so no part is one enormous sentence that the model would only read the start of."""
    out: list[dict] = []
    for s in sents:
        text = s["text"]
        while len(text) > most:
            cut = text.rfind(" ", most // 2, most)
            cut = cut if cut > 0 else most
            out.append({**s, "text": text[:cut]})
            text = text[cut:].lstrip()
        if text:
            out.append({**s, "text": text})
    return out


# ------------------------------------------------------------------ the facts (no model)
def facts(db: DB, doc_id: str, wpm: int) -> dict:
    rows = db.all(
        "SELECT c.id, c.title, c.level, c.kind, c.hidden, MIN(s.ord) AS sentence, COALESCE(SUM(s.words), 0) AS words FROM sections c"
        " JOIN paragraphs p ON p.section_id=c.id AND p.deleted=0 JOIN sentences s ON s.paragraph_id=p.id AND s.deleted=0"
        " WHERE c.document_id=? AND c.deleted=0 GROUP BY c.id ORDER BY c.ord", (doc_id,))
    outline = [{"id": r["id"], "title": r["title"], "level": r["level"], "kind": r["kind"], "words": r["words"], "sentence": r["sentence"],
                "skipped": bool(r["hidden"])} for r in rows]
    words = sum(o["words"] for o in outline if not o["skipped"])
    wpm = max(60, min(1200, int(wpm or 250)))
    return {"outline": outline, "words": words, "wpm": wpm, "minutes": max(1, math.ceil(words / wpm))}


# ------------------------------------------------------------------ parts
@dataclass
class Chunk:
    text: str  # what the model reads: a header line, then "## Title" and the sentences of each section
    body: str  # the same without the header (what the kept summary depends on)
    first: int  # the first sentence
    titles: list[str]
    anchors: list[int] = field(default_factory=list)  # the first sentence of each section in the part


def _pack(sections: list[tuple[str, list[dict]]], target: int) -> list[list[tuple[str, list[dict]]]]:
    """Fill parts with whole sections; a section longer than the target is cut between sentences."""
    parts: list[list[tuple[str, list[dict]]]] = []
    cur: list[tuple[str, list[dict]]] = []
    size = 0
    for title, sents in sections:
        n = sum(len(s["text"]) + 1 for s in sents) + len(title) + 4
        if cur and size + n > target:
            parts.append(cur)
            cur, size = [], 0
        if n <= target:
            cur.append((title, sents))
            size += n
            continue
        piece, piece_size = [], len(title) + 4
        for s in sents:  # a long section on its own: in pieces
            if piece and piece_size + len(s["text"]) + 1 > target:
                parts.append([(title, piece)])
                piece, piece_size = [], len(title) + 16
                title = title if title.endswith("(continued)") else f"{title} (continued)"
            piece.append(s)
            piece_size += len(s["text"]) + 1
        cur, size = [(title, piece)], piece_size
    if cur:
        parts.append(cur)
    return parts


def chunks(db: DB, doc_id: str) -> list[Chunk]:
    """The parts of a document, at section boundaries. References and other hidden sections are left out."""
    rows = db.all(
        "SELECT s.ord, s.text, c.id AS section_id, c.title FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
        " JOIN sections c ON c.id=p.section_id AND c.deleted=0 WHERE s.document_id=? AND s.deleted=0 AND c.hidden=0 ORDER BY s.ord", (doc_id,))
    sections: list[tuple[str, list[dict]]] = []
    for r in rows:
        if not sections or sections[-1][1][-1]["section_id"] != r["section_id"]:
            sections.append((r["title"], []))
        sections[-1][1].append(r)
    target = CHUNK
    while True:
        room = target - min(HEADER_ROOM, target // 8)
        packed = _pack([(title, _split_long(sents, room // 2)) for title, sents in sections], room)
        if len(packed) <= MAX_CHUNKS:
            break
        if target >= MAX_CHUNK:
            raise TooLong()
        target = min(MAX_CHUNK, int(target * GROW))
    out = []
    for i, part in enumerate(packed, 1):
        body = "\n".join(f"## {title}\n" + "\n".join(s["text"] for s in sents) for title, sents in part)
        titles = [title for title, _ in part]
        named = ", ".join(t[:80] for t in titles[:HEADER_TITLES]) + (f" and {len(titles) - HEADER_TITLES} more" if len(titles) > HEADER_TITLES else "")
        header = f"(Part {i} of {len(packed)}. Sections: {named})"
        out.append(Chunk(f"{header}\n{body}", body, part[0][1][0]["ord"], titles, [sents[0]["ord"] for _, sents in part]))
    return out


# ------------------------------------------------------------------ the answers asked for
class Point(BaseModel):
    text: str = Field(max_length=2000)
    quote: str = Field("", max_length=2000)


class MapOut(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    points: list[Point] = Field(default_factory=list, max_length=8)
    keywords: list[str] = Field(default_factory=list, max_length=20)


class Idea(BaseModel):
    text: str = Field(max_length=2000)
    anchor: str = Field("", max_length=80)
    quote: str = Field("", max_length=2000)


class DigestOut(BaseModel):
    summary: str = Field(min_length=1, max_length=6000)
    key_ideas: list[Idea] = Field(default_factory=list, max_length=12)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    difficulty: Literal["introductory", "intermediate", "advanced"]


def _keys(map_prompt: prompts.Prompt, reduce_prompt: prompts.Prompt, parts: list[Chunk]) -> tuple[list[str], str]:
    map_keys = [results.key(map_prompt.hash, c.body) for c in parts]
    return map_keys, results.key(reduce_prompt.hash, *map_keys)


_key_cache: dict[str, tuple[tuple, str]] = {}


def _stamp(db: DB, doc_id: str) -> tuple:
    """Changes whenever the structure of a document changes (a section renamed, hidden, merged or split)."""
    a = db.one("SELECT MAX(updated_at) AS t, COUNT(*) AS n FROM sections WHERE document_id=?", (doc_id,))
    b = db.one("SELECT MAX(updated_at) AS t, COUNT(*) AS n FROM paragraphs WHERE document_id=?", (doc_id,))
    return (a["t"], a["n"], b["t"], b["n"])


def kept_digest(db: DB, doc_id: str) -> dict | None:
    try:
        map_prompt, reduce_prompt = prompts.load(MAP), prompts.load(FEATURE)
        stamp = (_stamp(db, doc_id), map_prompt.hash, reduce_prompt.hash)
        hit = _key_cache.get(doc_id)
        if hit and hit[0] == stamp:
            key = hit[1]
        else:
            _, key = _keys(map_prompt, reduce_prompt, chunks(db, doc_id))
            _key_cache[doc_id] = (stamp, key)
    except (KeyError, TooLong):
        return None
    return results.find(db, FEATURE, doc_id, key)


def stop(doc_id: str | None = None) -> int:
    """Stop the digest of one document (when it is removed) or of all (Clear AI history)."""
    n = 0
    for d, job in list(_jobs.items()):
        if (doc_id is None or d == doc_id) and job.state == "running":
            job.stop.set()
            n += 1
    return n


# ------------------------------------------------------------------ the job
@dataclass
class Job:
    doc_id: str
    total: int
    id: str = field(default_factory=new_id)
    state: str = "running"  # running | done | failed | cancelled
    step: str = "parts"  # parts | combining
    done: int = 0
    message: str = ""
    call_id: str = ""
    stop: threading.Event = field(default_factory=threading.Event)

    def view(self) -> dict:
        return {"id": self.id, "state": self.state, "step": self.step, "done": self.done, "total": self.total, "message": self.message}


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _clean_keywords(words: list[str], within: str, links: list[str]) -> list[str]:
    out: list[str] = []
    for w in words:
        o = guard.safe_output(str(w), CAPS["keyword"])
        links.extend(o.links)
        plain = guard._plain(o.text)
        if (len(plain) >= 3 and re.search(r"[^\W\d_]", o.text) and plain not in ("percent", "minus")  # a word, not a sign
                and guard.word_in(plain, within) and o.text not in out):  # whole words only
            out.append(o.text)
    return out[:MAX_KEYWORDS]


class Stopped(Exception):
    """Stop was pressed, AI was switched off, or the document was removed: nothing more is sent."""


def _check(port: Port, db: DB, job: Job) -> None:
    if job.stop.is_set() or port.settings().get("ai_mode") not in ("local", "cloud"):
        raise Stopped()
    if not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (job.doc_id,)):
        raise Stopped()


def _summarise_part(port: Port, db: DB, job: Job, doc_id: str, name: str, c: Chunk, key: str, prompt: prompts.Prompt, failed: list | None = None) -> dict | None:
    """The map step for one part. Returns the kept summary, or None when the model could not summarise it (the failed
    call's log row then goes into `failed`, so "Why did it say this?" lists it)."""
    kept = results.find(db, MAP, doc_id, key)
    if kept:
        return kept
    _check(port, db, job)
    job.call_id = new_id()
    try:
        r = guard.ask(port, db, MAP, prompt.text, [guard.Source(f"{doc_id}:{c.first}", c.text, "imported", name)], budget=MAP,
                      schema=MapOut, prompt_version=prompt.version, call_id=job.call_id)
    except CouldNotGenerate as e:
        if failed is not None and e.log_id:
            failed.append(e.log_id)
        return None
    _check(port, db, job)  # pressed Stop while the model was answering: its answer is not kept
    links = list(r.links)
    points = []
    for p in r.data["points"][:MAX_POINTS]:
        text = guard.safe_output(p["text"], CAPS["point"]).text
        if not text:
            continue
        quote = p.get("quote") or ""
        ok = guard.quote_in(quote, c.body, MIN_QUOTE_WORDS)
        points.append({"text": text, "quote": guard.safe_output(quote, CAPS["quote"]).text if ok else "", "verified": ok})
    payload = {"summary": guard.safe_output(r.data["summary"], CAPS["part"]).text, "points": points,
               "keywords": _clean_keywords(r.data.get("keywords") or [], guard._plain(c.body), links),
               "sentence": c.first, "titles": c.titles, "links": list(dict.fromkeys(links)), "warning": r.warning}
    return results.keep(db, MAP, doc_id, key, payload, prompt.version, r.log_id)


def _find_quote(db: DB, doc_id: str, parts: list[Chunk], quote: str, anchor: str) -> int | None:
    """The sentence a key idea's quote is in, or None. The quote must be in the text of a part that was read."""
    holders = [c for c in parts if guard.quote_in(quote, c.body, MIN_QUOTE_WORDS)]
    holders.sort(key=lambda c: f"{doc_id}:{c.first}" != anchor)  # the part the model named first
    for c in holders:
        for a in c.anchors:
            got = guard.verify_citations(db, [{"anchor": f"{doc_id}:{a}", "quote": quote}])
            if got.kept:
                return got.kept[0]["sentence"]
    return None


def _reduce_sources(doc_id: str, name: str, read: list) -> list[guard.Source]:
    """What the combining call reads: the summary and the points of each part that was read, as many whole points
    as fit in its share."""
    sources = []
    share = guard.BUDGETS[FEATURE] // len(read) - 20
    for i, (c, s) in enumerate(read, 1):
        named = ", ".join(t[:60] for t in c.titles[:HEADER_TITLES]) + (" and more" if len(c.titles) > HEADER_TITLES else "")
        lines = [f"(Part {i} of {len(read)}. Sections: {named})", f"Summary: {s['summary']}"]
        text = "\n".join(lines)[:share]
        points = [f"- {p['text']} — quote: “{p['quote']}”" if p["quote"] else f"- {p['text']}" for p in s["points"]]
        for j, line in enumerate(points):  # as many whole points as fit, so a quote is never cut in half
            add = ("\nPoints:\n" if j == 0 else "\n") + line
            if len(text) + len(add) > share:
                break
            text += add
        sources.append(guard.Source(f"{doc_id}:{c.first}", text, "imported", name))
    return sources


def preview_first_call(port: Port, db: DB, doc_id: str, parts: list) -> None:
    """For "Show what will be sent": the first call this digest will really make. The summary of the first part not
    yet summarised; when every part is, the combining call."""
    map_prompt, reduce_prompt = prompts.load(MAP), prompts.load(FEATURE)
    map_keys, _ = _keys(map_prompt, reduce_prompt, parts)
    name = db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or ""
    kept = []
    for c, k in zip(parts, map_keys, strict=True):
        s = results.find(db, MAP, doc_id, k)
        if not s:
            guard.preview(port, db, MAP, map_prompt.text, [guard.Source(f"{doc_id}:{c.first}", c.text, "imported", name)], MAP)
            return
        kept.append((c, s))
    guard.preview(port, db, FEATURE, reduce_prompt.text, _reduce_sources(doc_id, name, kept), FEATURE)


def run(port: Port, db: DB, job: Job, fresh: bool) -> None:
    doc_id = job.doc_id
    try:
        map_prompt, reduce_prompt = prompts.load(MAP), prompts.load(FEATURE)
        parts = chunks(db, doc_id)
        job.total = len(parts)
        map_keys, key = _keys(map_prompt, reduce_prompt, parts)
        name = db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or ""
        summaries: list[dict | None] = []
        part_logs: list[str] = []  # the call behind each part, in order: its kept summary's, or the one that failed
        for c, k in zip(parts, map_keys, strict=True):  # one part after another: a local model is never asked twice at once by a digest
            _check(port, db, job)
            failed: list[str] = []
            s = _summarise_part(port, db, job, doc_id, name, c, k, map_prompt, failed)
            summaries.append(s)
            part_logs += [s["log_id"]] if s and s.get("log_id") else failed
            job.done += 1
        _check(port, db, job)
        read = [(c, s) for c, s in zip(parts, summaries, strict=True) if s]
        if not read:
            job.state, job.message = "failed", CouldNotGenerate.message
            return
        job.step = "combining"
        sources = _reduce_sources(doc_id, name, read)
        with results.once(FEATURE, key):
            kept = results.find(db, FEATURE, doc_id, key)
            if kept and not fresh:
                job.state = "done"
                return
            _check(port, db, job)
            job.call_id = new_id()
            r = guard.ask(port, db, FEATURE, reduce_prompt.text, sources, budget=FEATURE, schema=DigestOut, prompt_version=reduce_prompt.version, call_id=job.call_id)
            _check(port, db, job)  # pressed Stop while the model was combining: the answer is not kept
            links = list(r.links)
            for s in summaries:
                links += (s or {}).get("links", [])
            ideas = []
            for idea in r.data["key_ideas"][:MAX_IDEAS]:
                text = guard.safe_output(idea["text"], CAPS["idea"]).text
                if not text:
                    continue
                at = _find_quote(db, doc_id, parts, idea.get("quote") or "", idea.get("anchor") or "")
                ideas.append({"text": text, "verified": at is not None, **({"quote": guard.safe_output(idea["quote"], CAPS["quote"]).text, "sentence": at} if at is not None else {})})
            proven = sum(1 for x in ideas if x["verified"])
            payload = {
                "summary": guard.safe_output(r.data["summary"], CAPS["summary"]).text,
                "key_ideas": ideas,
                "keywords": _clean_keywords(r.data.get("keywords") or [], guard._plain("\n".join(c.body for c in parts)), links),
                "difficulty": r.data["difficulty"],
                "parts": [{"sentence": c.first, "titles": c.titles, "summary": s["summary"] if s else "", "failed": s is None}
                          for c, s in zip(parts, summaries, strict=True)],
                "skipped_parts": sum(1 for s in summaries if s is None),
                "status": "verified" if ideas and proven == len(ideas) else "partly" if proven else "unverified",
                "links": list(dict.fromkeys(links)),
                "warning": r.warning,
                "log_ids": part_logs + [r.log_id],  # this digest's own calls, for "Why did it say this?"
            }
            results.keep(db, FEATURE, doc_id, key, payload, reduce_prompt.version, r.log_id, replaces=kept["id"] if kept else None)
        job.state = "done"
    except (Cancelled, AIOff, Stopped):
        job.state = "cancelled"
    except AIError as e:
        job.state, job.message = "failed", e.message
    except guard.Blocked as e:
        job.state, job.message = "failed", str(e)
    except privacy.PreviewNeeded:  # "Show what will be sent" was switched on while it ran: nothing more was sent
        job.state, job.message = "failed", "Stopped before sending more: start the digest again to see what will be sent."
    except TooLong:
        job.state, job.message = "failed", too_long_message()
    except Exception:  # noqa: BLE001  (a background job reports, it never takes the app down)
        log.exception("The digest of %s failed", doc_id)
        job.state, job.message = "failed", "Something went wrong while writing the digest. It is in the log file."
    finally:
        job.call_id = ""


def too_long_message() -> str:
    return f"This document is too long for a digest (it would need more than {MAX_CHUNKS} parts). Digest a part of it, or use the outline."


def start(port: Port, db: DB, doc_id: str, fresh: bool, preview=None) -> tuple[Job | None, dict | None]:
    """Start a digest unless one is running or a kept one fits. Returns (job, kept digest)."""
    with _jobs_lock:
        job = _jobs.get(doc_id)
        if job and job.state == "running":
            return job, None
        parts = chunks(db, doc_id)  # TooLong goes to the caller
        if not parts:
            raise Nothing()
        if not fresh:
            kept = kept_digest(db, doc_id)
            if kept:
                return job, kept
        if preview:  # "Show what will be sent": the first call it will make, before anything starts (raises PreviewNeeded)
            preview(parts)
        job = Job(doc_id, total=len(parts))
        _jobs[doc_id] = job
    # the job runs in a copy of this request's context: a send preview approved for this request covers its calls
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(run, port, db, job, fresh), name=f"digest-{doc_id[:8]}", daemon=True).start()
    return job, None


# ------------------------------------------------------------------ routes
class DigestIn(BaseModel):
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    def need_doc(doc_id: str) -> None:
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
            raise HTTPException(404, "document not found")

    def mode() -> str:
        m = port.settings().get("ai_mode")
        return m if m in ("local", "cloud") else "off"

    @app.get("/api/documents/{doc_id}/digest")
    def api_digest(doc_id: str):
        need_doc(doc_id)
        job = _jobs.get(doc_id)
        view = job.view() if job else None  # read first: a job seen as done has already kept its digest
        kept = None
        if mode() != "off" and not (view and view["state"] == "running"):  # while it runs there is nothing new to find
            try:  # the facts never fail because of the AI layer
                kept = kept_digest(db, doc_id)
            except Exception:  # noqa: BLE001
                log.exception("Could not look up the kept digest of %s", doc_id)
        return {"facts": facts(db, doc_id, port.settings().get("wpm", 250)), "ai": {"mode": mode()}, "digest": kept, "job": view}

    @app.post("/api/documents/{doc_id}/digest")
    def api_digest_start(doc_id: str, body: DigestIn):
        need_doc(doc_id)
        if mode() == "off":
            raise HTTPException(409, AIOff.message)
        if guard.leaves(port) and privacy.document_private(db, doc_id):  # said now: the job would only fail in the background
            raise HTTPException(409, privacy.refusal(db))
        try:
            job, kept = start(port, db, doc_id, body.fresh, preview=lambda parts: preview_first_call(port, db, doc_id, parts))
        except TooLong:
            raise HTTPException(409, too_long_message()) from None
        except Nothing:
            raise HTTPException(409, "This document has no text to digest (it is empty, or every section is hidden).") from None
        except guard.Blocked as e:  # the preview's packing refused (a file of secrets in cloud mode)
            raise HTTPException(409, str(e)) from None
        return {"job": job.view() if job else None, "digest": kept}

    @app.post("/api/documents/{doc_id}/digest/cancel")
    def api_digest_cancel(doc_id: str):
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=?", (doc_id,)):
            raise HTTPException(404, "document not found")
        job = _jobs.get(doc_id)
        if not job or job.state != "running":
            return {"cancelled": False}
        job.stop.set()
        if job.call_id:
            port.cancel(job.call_id)
        return {"cancelled": True}
