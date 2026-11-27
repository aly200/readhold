"""Ask my library (milestone 2.3 of docs/ai/PLAN.md): a question across all your documents and your notes.

Two layers, as everywhere in Readhold:
- without a model: the passages of every document and the notes that match the question (`matches`);
- with AI switched on, when you press Ask: the plan's one bounded agent loop. The model starts with the best
  matches and works in at most MAX_STEPS steps (each step is one call; like every call it may be retried once).
  At each step it answers, or uses one of two tools:
    search(keywords)  more passages and notes for other words (the words are cleaned like a question's);
    read(anchor)      more of the section around one sentence of a live document ("<doc id>:<ord>"), or a whole
                      note ("note:<id>"); when that source was already sent, the longer copy replaces it.
  Both only read. They take words and anchors, never paths or links. What the model asked for is never written
  back into its instructions: it is only told how many sources were added. On the last step no tool runs; if
  the model still asks for more, the answer is "not found in your library". A question can be stopped.

Every quote is checked against the text that was sent: a document quote must also pass `verify_citations`
(2.1); a note quote must be, on whole words, in the note's text (not its title) as it is now. A kept answer is
given again only while every quote it shows is still true of the library. Files of secrets are left out of a
cloud call (not refused: the rest of the library is still asked), counted once per file.
"""
from __future__ import annotations

import bisect
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import passages
from ..db import DB, new_id
from . import guard, privacy, prompts, results
from .ask import Citation, Invalid, _around, _cache_question, _question, _terms
from .port import AIError, AIOff, Cancelled, Port
from .resume import status_error

FEATURE = "library"
MAX_STEPS = 3
MAX_SECTIONS = 5  # document sections a search brings in
MAX_NOTES = 3  # notes a search brings in
MAX_SOURCES = 10  # sources in one call; the oldest are dropped first (they stay checkable)
MAX_CONTEXT = guard.BUDGETS[FEATURE] - 2_000
ROOM = MAX_CONTEXT // MAX_SOURCES  # characters one source may hold when it is first added
MAX_CITATIONS = 5
MIN_QUOTE_WORDS = 4
NOTE_SCAN = 5_000  # the most recent notes a search looks at
DOC_ANCHOR = re.compile(r"([0-9a-f]{32}):(\d{1,7})")
NOTE_ANCHOR = re.compile(r"note:([0-9a-f]{32})")
CAPS = {"answer": 1400, "quote": 400, "snippet": 200}


class Step(BaseModel):
    action: Literal["answer", "search", "read"]
    keywords: str = Field("", max_length=300)
    anchor: str = Field("", max_length=120)
    found: bool = False
    answer: str = Field("", max_length=8000)
    citations: list[Citation] = Field(default_factory=list, max_length=15)


# ------------------------------------------------------------------ notes, searched by word prefixes
_note_words: dict[str, tuple[str, list[str]]] = {}  # note id -> (updated_at, its plain words, sorted): made once per change
_note_lock = threading.Lock()


def _words_of(note: dict) -> list[str]:
    with _note_lock:
        hit = _note_words.get(note["id"])
        if hit and hit[0] == note["updated_at"]:
            return hit[1]
    words = sorted(set(guard._plain(f"{note['title']} {note['body']}").split()))
    with _note_lock:
        _note_words[note["id"]] = (note["updated_at"], words)
    return words


def _has_prefix(words: list[str], prefix: str) -> bool:
    i = bisect.bisect_left(words, prefix)
    return i < len(words) and words[i].startswith(prefix)


def _note_hits(db: DB, terms: str) -> list[dict]:
    """Notes that hold the search words (a word may be the start of a longer one), most words first."""
    wanted = [w for w in (guard._plain(t) for t in terms.split()) if w]
    if not wanted:
        return []
    scored = []
    for n in db.all("SELECT id, title, body, updated_at FROM pages WHERE deleted=0 ORDER BY updated_at DESC LIMIT ?", (NOTE_SCAN,)):
        have = _words_of(n)
        score = sum(1 for w in wanted if _has_prefix(have, w))
        if score:
            scored.append((score, n))
    best = max((s for s, _ in scored), default=0)
    need = len(wanted) if best == len(wanted) else 1  # all the words when some note has them all, else any
    return [n for s, n in sorted(scored, key=lambda x: -x[0]) if s >= need][:MAX_NOTES]


def _snippet(text: str, terms: str) -> str:
    hits = [m.start() for w in terms.split() if (m := re.search(re.escape(w), text, re.I))]
    start = max(0, min(hits, default=0) - 60)
    return ("…" if start else "") + " ".join(text[start:start + CAPS["snippet"]].split())


def matches(db: DB, question: str) -> list[dict]:
    """The passages and notes that match a question, documents first. No model."""
    terms = _terms(question)
    if not terms:
        return []
    out = [{"kind": "document", **h} for h in passages.search_sections(db, terms, limit=MAX_SECTIONS)]
    out += [{"kind": "note", "note_id": n["id"], "title": n["title"], "snippet": _snippet(n["body"], terms)} for n in _note_hits(db, terms)]
    return out


# ------------------------------------------------------------------ the two tools
NOTE_HEAD = "(Your note: {title})\n"


def _section_source(db: DB, doc_id: str, ord_: int, room: int = ROOM) -> guard.Source | None:
    """The section around one sentence of a live document, as a source. None for anything else."""
    at = db.one("SELECT p.section_id, c.title AS section, d.title AS document, d.source FROM sentences s"
                " JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0 JOIN sections c ON c.id=p.section_id AND c.deleted=0"
                " JOIN documents d ON d.id=s.document_id AND d.deleted=0 WHERE s.document_id=? AND s.ord=? AND s.deleted=0", (doc_id, ord_))
    if not at:
        return None
    rows = db.all("SELECT s.ord, s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                  " WHERE p.section_id=? AND s.deleted=0 ORDER BY s.ord", (at["section_id"],))
    head = f"(Document: {at['document']}. Section: {at['section']})\n"
    body, cut = _around(rows, ord_, max(200, room - len(head)))
    src = guard.Source(f"{doc_id}:{rows[0]['ord']}", head + body, "imported", at["source"] or "")
    src.cut = cut
    src.center = ord_  # type: ignore[attr-defined]  # the sentence this copy is built around: a later read grows around it too
    return src


def _note_source(db: DB, note_id: str, room: int = ROOM) -> guard.Source | None:
    n = db.one("SELECT id, title, body FROM pages WHERE id=? AND deleted=0", (note_id,))
    if not n:
        return None
    head = NOTE_HEAD.format(title=" ".join(n["title"].split())[:200])
    src = guard.Source(f"note:{n['id']}", head + n["body"][: max(200, room - len(head))], "yours")
    src.cut = len(head) + len(n["body"]) > room
    return src


def search(db: DB, words: str) -> list[guard.Source]:
    """Tool 1: the passages and notes for some words."""
    terms = _terms(words)
    if not terms:
        return []
    out = [s for h in passages.search_sections(db, terms, limit=MAX_SECTIONS) if (s := _section_source(db, h["document_id"], h["sentence"]))]
    return out + [s for n in _note_hits(db, terms) if (s := _note_source(db, n["id"]))]


def read(db: DB, anchor: str, around: int | None = None) -> guard.Source | None:
    """Tool 2: more of one section of a live document, or one note. Anything that is not such an anchor is nothing.
    `around`: for a section already sent, the sentence its copy was built around (the anchor the model sees is the
    section's first sentence; reading from there would lose the passage the search matched)."""
    anchor = (anchor or "").strip()
    if m := DOC_ANCHOR.fullmatch(anchor):
        ord_ = int(m.group(2))
        if around is not None:
            same = db.one("SELECT 1 FROM sentences a JOIN sentences b ON b.document_id=a.document_id AND b.ord=? AND b.deleted=0"
                          " JOIN paragraphs pa ON pa.id=a.paragraph_id JOIN paragraphs pb ON pb.id=b.paragraph_id"
                          " WHERE a.document_id=? AND a.ord=? AND a.deleted=0 AND pa.section_id=pb.section_id", (around, m.group(1), ord_))
            ord_ = around if same else ord_
        return _section_source(db, m.group(1), ord_, room=ROOM * 2)
    if m := NOTE_ANCHOR.fullmatch(anchor):
        return _note_source(db, m.group(1), room=ROOM * 2)
    return None


# ------------------------------------------------------------------ checking
def _body(anchor: str, text: str) -> str:
    """What may be quoted from a source: for a note, its text without the header that names it."""
    return text.split("\n", 1)[1] if NOTE_ANCHOR.fullmatch(anchor) and "\n" in text else text


def _citation(db: DB, c: dict, sent: dict[str, str]) -> dict:
    """A quote is shown only when it is in a text that was sent and in the library as it is now."""
    quote = c.get("quote") or ""
    held = [a for a, text in sent.items() if guard.quote_in(quote, _body(a, text), MIN_QUOTE_WORDS)]
    held.sort(key=lambda a: a != c.get("anchor"))
    for a in held:
        if m := NOTE_ANCHOR.fullmatch(a):
            n = db.one("SELECT id, title, body FROM pages WHERE id=? AND deleted=0", (m.group(1),))
            if n and guard.quote_in(quote, n["body"], MIN_QUOTE_WORDS):
                return {"verified": True, "kind": "note", "note_id": n["id"], "note_title": n["title"], "quote": guard.safe_output(quote, CAPS["quote"]).text}
        elif DOC_ANCHOR.fullmatch(a):
            got = guard.verify_citations(db, [{"anchor": a, "quote": quote}])
            if got.kept:
                k = got.kept[0]
                titles = db.one("SELECT d.title AS document, c.title AS section FROM documents d, sections c WHERE d.id=? AND c.id=?", (k["document_id"], k["section_id"])) or {}
                return {"verified": True, "kind": "document", "document_id": k["document_id"], "document_title": titles.get("document", ""),
                        "section_title": titles.get("section", ""), "sentence": k["sentence"], "quote": guard.safe_output(quote, CAPS["quote"]).text}
    return {"verified": False}


def still_true(db: DB, kept: dict) -> bool:
    """Is every quote a kept answer shows still in the library, as it is now? (a document or note it cites may have
    been removed or changed since, also one that only a later step of the loop brought in)."""
    for c in kept.get("citations") or []:
        if not c.get("verified"):
            continue
        if c.get("kind") == "note":
            n = db.one("SELECT body FROM pages WHERE id=? AND deleted=0", (c.get("note_id", ""),))
            if not n or not guard.quote_in(c.get("quote", ""), n["body"], MIN_QUOTE_WORDS):
                return False
        elif not guard.verify_citations(db, [{"anchor": f"{c.get('document_id')}:{c.get('sentence')}", "quote": c.get("quote", "")}]).kept:
            return False
    return True


# ------------------------------------------------------------------ the loop
@dataclass(eq=False)  # each run is itself, so it can sit in a set
class Run:
    stop: threading.Event = field(default_factory=threading.Event)
    call_id: str = ""


_runs: set[Run] = set()
_runs_lock = threading.Lock()


def cancel(port: Port) -> bool:
    """Stop every question that is running: the call in flight is cancelled, and no further step starts."""
    with _runs_lock:
        runs = list(_runs)
    for r in runs:
        r.stop.set()
        if r.call_id:
            port.cancel(r.call_id)
    return bool(runs)


def _doc_of(src: guard.Source) -> str:
    m = DOC_ANCHOR.fullmatch(src.anchor)
    return m.group(1) if m else src.anchor


def ask(port: Port, db: DB, question: str, fresh: bool = False) -> dict:
    q = _question(question)
    mode = port.settings().get("ai_mode")
    if mode not in ("local", "cloud"):
        raise AIOff()
    cloud = guard.leaves(port)  # the cloud, or a model server on another computer
    secret_files: set[str] = set()
    private: set[str] = set()
    strict = privacy.only_tagged(db)

    def allowed(new: list[guard.Source]) -> list[guard.Source]:
        """What may be sent. In cloud mode, files of secrets and private items (and copies of them) are left out before
        they take a place, are counted as "added", or are told to the model: each is only counted, once."""
        out = []
        for s in new:
            if cloud and s.name and guard.sensitive_name(s.name):
                secret_files.add(_doc_of(s))  # a file of secrets never goes to a cloud model; counted once per file
            elif cloud and privacy.withheld(db, s.anchor, s.text, s.trust, strict):
                private.add(_doc_of(s))
            else:
                out.append(s)
        return out

    first = allowed(search(db, q))
    if not first:  # nothing in the library matches (or only files of secrets or private items did): no model is asked
        return {"question": q, "found": False, "answer": "", "citations": [], "status": "not_found", "searched": 0, "steps": [], "links": [],
                "left_out": len(secret_files), "private_left_out": len(private)}
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, mode, _cache_question(q), *(f"{s.anchor}\n{s.text}" for s in first))
    run = Run()
    with _runs_lock:
        _runs.add(run)
    try:
        with results.once(FEATURE, key):
            kept = results.find(db, FEATURE, FEATURE, key)
            if kept and not fresh and still_true(db, kept):
                return {**kept, "private_left_out": len(private)}
            out = _loop(port, db, q, prompt, key, first, allowed, secret_files, run, kept)
            return {**out, "private_left_out": len(private)}
    finally:
        with _runs_lock:
            _runs.discard(run)


def _loop(port: Port, db: DB, q: str, prompt: prompts.Prompt, key: str, first: list[guard.Source], allowed, secret_files: set[str], run: Run, kept: dict | None) -> dict:
    sources: list[guard.Source] = []
    sent: dict[str, str] = {}  # every text the model was given, by anchor: what a quote may come from
    centers: dict[str, int] = {}  # anchor -> the sentence its first copy was built around

    def add(new: list[guard.Source]) -> int:
        n = 0
        for s in allowed(new):
            if (c := getattr(s, "center", None)) is not None:
                centers.setdefault(s.anchor, c)
            old = next((i for i, x in enumerate(sources) if x.anchor == s.anchor), None)
            if old is None:
                sources.append(s)
                n += 1
            elif len(s.text) > len(sources[old].text):  # read brought in more of a source already sent
                sources[old] = s
                n += 1
        del sources[:-MAX_SOURCES]  # the oldest go first; what was sent stays checkable in `sent`
        return n

    add(first)
    steps: list[dict[str, Any]] = []
    links: list[str] = []
    log_ids: list[str] = []
    note, data, warning = "", None, ""
    for k in range(1, MAX_STEPS + 1):
        if run.stop.is_set():
            raise Cancelled()
        last = k == MAX_STEPS
        instruction = (f"{prompt.text}\n\nStep {k} of {MAX_STEPS}."
                       + (" This is the last step: answer now, with \"found\": false if the sources do not say." if last else "")
                       + (f" {note}" if note else ""))
        for s in sources:  # a longer copy is added beside the shorter one: both were sent
            sent[s.anchor] = s.text if s.anchor not in sent or sent[s.anchor] in s.text else f"{sent[s.anchor]}\n{s.text}"
        run.call_id = new_id()
        r = guard.ask(port, db, FEATURE, instruction, sources, budget=FEATURE, question=q, schema=Step, prompt_version=prompt.version, call_id=run.call_id)
        if run.stop.is_set():
            raise Cancelled()
        links += r.links
        log_ids.append(r.log_id)
        warning, data = r.warning, r.data
        action = data["action"]
        if action == "answer":
            steps.append({"step": k, "action": "answer"})
            break
        if last:  # no tool runs on the last step: there would be no step left to use what it found
            steps.append({"step": k, "action": action, "added": 0, "ran": False})
            data = None
            break
        if action == "search":
            raw = data.get("keywords") or ""
            words = _terms(raw)  # for the step line only: search cleans the words itself, once
            added = add(search(db, raw)) if words else 0
            steps.append({"step": k, "action": "search", "keywords": guard.safe_output(words, 200).text, "added": added})
            note = f"Your search added {added} new source{'s' if added != 1 else ''}."  # the words are not repeated here
        else:
            anchor = (data.get("anchor") or "").strip()
            src = read(db, anchor, centers.get(anchor))
            added = add([src]) if src else 0
            steps.append({"step": k, "action": "read", "added": added})
            note = "More of the source you asked for was added." if added else "Nothing was added: that anchor is not a section or a note of the library, or nothing more of it fits."
        data = None
    if data and data["action"] == "answer" and data["found"] and guard.safe_output(data.get("answer") or "").text:
        cites, seen = [], set()
        for c in (data.get("citations") or [])[:MAX_CITATIONS * 3]:
            one = _citation(db, c, sent)
            mark = (one.get("note_id") or one.get("document_id"), one.get("sentence"), guard._plain(one.get("quote", ""))) if one["verified"] else ("x", guard._plain(c.get("quote") or ""))
            if mark not in seen:
                seen.add(mark)
                cites.append(one)
        cites = cites[:MAX_CITATIONS]
        proven = sum(1 for c in cites if c["verified"])
        payload = {"question": q, "found": True, "answer": guard.safe_output(data["answer"], CAPS["answer"]).text, "citations": cites,
                   "status": "verified" if cites and proven == len(cites) else "partly" if proven else "unverified"}
    else:  # "not found", or the model was still asking for more at the last step
        payload = {"question": q, "found": False, "answer": "", "citations": [], "status": "not_found"}
    payload.update(steps=steps, searched=len(sent), links=list(dict.fromkeys(links)), warning=warning, left_out=len(secret_files), log_ids=log_ids)
    return results.keep(db, FEATURE, FEATURE, key, payload, prompt.version, log_ids[-1], replaces=kept["id"] if kept else None, target_type="library")


# ------------------------------------------------------------------ routes
class AskIn(BaseModel):
    question: str = Field(max_length=100_000)  # longer than the limit: _question explains it in words
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    def mode() -> str:
        m = port.settings().get("ai_mode")
        return m if m in ("local", "cloud") else "off"

    @app.get("/api/library/ask")
    def api_library_matches(q: str = ""):
        """The passages and notes that match a question. No model: this works with AI off."""
        try:
            question = _question(q)
        except Invalid as e:
            raise HTTPException(422, str(e)) from None
        return {"passages": matches(db, question), "ai": {"mode": mode()}}

    @app.post("/api/library/ask")
    def api_library_ask(body: AskIn):
        """Ask the model. A plain `def`: it runs on a worker thread, and the app is never blocked."""
        try:
            return {"result": ask(port, db, body.question, body.fresh)}
        except Invalid as e:
            raise HTTPException(422, str(e)) from None
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None

    @app.post("/api/library/ask/cancel")
    def api_library_cancel():
        return {"cancelled": cancel(port)}
