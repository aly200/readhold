"""Study notes writer (milestone 2.4 of docs/ai/PLAN.md): notes, flashcards or a short quiz from what you read.

The non-AI versions already exist: the Summary sheet gathers your highlights, and highlights and questions become
review cards on their own. With AI switched on, and only when you ask, a model drafts study material from one of
two sources: your highlights in a document (with the notes you wrote on them), or one section of it. Three kinds:
- notes:  study notes, one idea each;
- cards:  flashcards, a question and its answer;
- quiz:   a short self-quiz, answered by you first ("attempt before reveal"), then checked against the answer.

Every item must rest on a quote that is, on whole words, in the text as it was sent (after any cut to fit the
budget) and passes `verify_citations`. An item without one is shown labelled and cannot be kept. The quote shown
and kept is the document's own sentence, never the model's wording of it. Nothing is saved until you accept items:
notes go to a note "Study notes: <document>" under a line that says the model wrote them, with a link back to each
passage; cards (and quiz questions you keep) go to the review deck as source "ai", with the passage on the back.
Keeping is once: an item already kept, a card with the same question, or a card you deleted is not added again.
Markup the model wrote ([[links]], #tags) is kept as plain characters; what you type yourself works as usual.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import pages, services
from ..db import DB
from . import guard, prompts, results
from .ask import _around
from .port import AIError, AIOff, Port
from .resume import status_error

ID = re.compile(r"[0-9a-f]{32}")
FEATURE = "notes"
KINDS = {
    "notes": "Kind: notes. Each item is one study note: \"text\" is one plain sentence (under 30 words) stating an idea from the sources; \"answer\" is an empty string.",
    "cards": "Kind: flashcards. Each item is one card: \"text\" is a short question (under 20 words) whose answer is in the sources; \"answer\" is the answer (under 30 words). Prefer questions that make the reader recall, not recognise.",
    "quiz": "Kind: a short quiz. Each item is one question: \"text\" is a question (under 25 words) that checks understanding, not wording; \"answer\" is the answer (under 40 words). Mix easy and harder questions.",
}
MAX_HIGHLIGHTS = 40
MAX_ITEMS = 10
MIN_QUOTE_WORDS = 4
MAX_CONTEXT = guard.BUDGETS[FEATURE] - 2_000
CAPS = {"text": 300, "answer": 400, "quote": 400}
MAX_RUN = 8  # sentences: the longest stretch a quote's own words are looked for in
LABEL = "*Written by the AI model from your reading. Each line links to the passage it rests on: check it, and change it into your own words.*"
OURS = re.compile(r"- [^\n]+\n  > [^\n]+")  # one kept item, as accept writes it


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


class Item(BaseModel):
    text: str = Field(max_length=2000)
    answer: str = Field("", max_length=3000)
    anchor: str = Field("", max_length=80)
    quote: str = Field("", max_length=2000)


class NotesOut(BaseModel):
    items: list[Item] = Field(default_factory=list, max_length=20)


# ------------------------------------------------------------------ what the model reads
def _highlights(db: DB, doc_id: str) -> list[guard.Source]:
    rows = db.all("SELECT sentence, end_sentence, type, text, note FROM highlights WHERE document_id=? AND deleted=0 ORDER BY sentence LIMIT ?",
                  (doc_id, MAX_HIGHLIGHTS))
    name = db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or ""
    out = []
    for h in rows:
        out.append(guard.Source(f"{doc_id}:{h['sentence']}", f"(Highlighted as {h['type']})\n{h['text']}", "imported", name))
        if h["note"].strip():
            out.append(guard.Source(f"hlnote:{doc_id}:{h['sentence']}", f"My note on that passage: {h['note']}", "yours"))
    return out


def _section(db: DB, doc_id: str, section_id: str, at: int | None = None) -> list[guard.Source]:
    """One section. A long one is sent around the sentence you are at (or from its start), and says it was cut."""
    sec = db.one("SELECT id, title FROM sections WHERE id=? AND document_id=? AND deleted=0", (section_id, doc_id)) if ID.fullmatch(section_id or "") else None
    if not sec:
        raise NotFound()
    rows = db.all("SELECT s.ord, s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                  " WHERE p.section_id=? AND s.deleted=0 ORDER BY s.ord", (section_id,))
    if not rows:
        raise Invalid("That section has no text.")
    head = f"(Section: {sec['title']})\n"
    pivot = at if at is not None and any(r["ord"] == at for r in rows) else rows[0]["ord"]
    body, cut = _around(rows, pivot, MAX_CONTEXT - len(head))
    src = guard.Source(f"{doc_id}:{rows[0]['ord']}", head + body, "imported", db.scalar("SELECT source FROM documents WHERE id=?", (doc_id,)) or "")
    src.cut = cut
    return [src]


def _own_words(db: DB, section_id: str, sentence: int, quote: str) -> str:
    """The document's own text for a verified quote: the shortest run of its sentences, from the one the check
    pointed at, that holds the quote. The model's copy may differ in punctuation or symbols that the check ignores."""
    rows = db.all("SELECT s.ord, s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                  " WHERE p.section_id=? AND s.deleted=0 ORDER BY s.ord", (section_id,))
    i = next((k for k, r in enumerate(rows) if r["ord"] == sentence), None)
    if i is None:
        return ""
    q, run = guard._plain(quote), ""
    for r in rows[i:i + MAX_RUN]:
        run = f"{run} {r['text']}".strip()
        if guard.word_in(q, guard._plain(run)):
            return run if len(run) <= CAPS["quote"] else run[:CAPS["quote"]].rsplit(" ", 1)[0] + " …"
    return ""


def _checked(db: DB, doc_id: str, item: dict, sources: list[guard.Source], sent: dict) -> dict:
    out = {"text": guard.safe_output(item["text"], CAPS["text"]).text, "answer": guard.safe_output(item.get("answer") or "", CAPS["answer"]).text, "verified": False}
    quote = item.get("quote") or ""
    # checked against the text as it went out: a source cut to fit the budget did not send its end
    held = [s for s in sources if s.trust == "imported" and guard.quote_in(quote, sent.get(s.anchor, ""), MIN_QUOTE_WORDS)]
    held.sort(key=lambda s: s.anchor != item.get("anchor"))
    for s in held:
        got = guard.verify_citations(db, [{"anchor": s.anchor, "quote": quote}])
        if got.kept:
            k = got.kept[0]
            own = _own_words(db, k["section_id"], k["sentence"], quote)
            out.update(verified=True, quote=own or guard.safe_output(quote, CAPS["quote"]).text, sentence=k["sentence"])
            break
    return out


def write(port: Port, db: DB, doc_id: str, source: str, kind: str, section_id: str = "", fresh: bool = False, at: int | None = None) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    sources = _highlights(db, doc_id) if source == "highlights" else _section(db, doc_id, section_id, at)
    if not sources:
        raise Invalid("There are no highlights in this document yet. Highlight a few passages first, or use a section.")
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, KINDS[kind], source, section_id, *(f"{s.anchor}\n{s.text}" for s in sources))
    unsent = 0
    if source == "highlights":
        unsent = max(0, (db.scalar("SELECT COUNT(*) FROM highlights WHERE document_id=? AND deleted=0", (doc_id,)) or 0) - MAX_HIGHLIGHTS)
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, doc_id, key)
        if kept and not fresh:
            return kept
        r = guard.ask(port, db, FEATURE, f"{prompt.text}\n\n{KINDS[kind]}", sources, budget=FEATURE, schema=NotesOut, prompt_version=prompt.version)
        made = []
        for item in r.data["items"][:MAX_ITEMS * 2]:
            one = _checked(db, doc_id, item, sources, r.sent)
            if not one["text"] or (kind != "notes" and not one["answer"]):
                continue  # a card or a question without an answer is not one
            if kind == "notes":
                one["answer"] = ""
            made.append(one)
        made = made[:MAX_ITEMS]
        proven = sum(1 for x in made if x["verified"])
        payload = {"kind": kind, "source": source, "section_id": section_id, "document_id": doc_id, "items": made,
                   "status": "verified" if made and proven == len(made) else "partly" if proven else "unverified",
                   "links": list(dict.fromkeys(r.links)), "warning": r.warning, "kept": [],
                   # what the model did not see in full: highlights past the first MAX_HIGHLIGHTS, sources cut or left out
                   "cut": bool(r.checks.get("trimmed")), "left_out": unsent + int(r.checks.get("left_out", 0))}
        return results.keep(db, FEATURE, doc_id, key, payload, prompt.version, r.log_id, replaces=kept["id"] if kept else None)


# ------------------------------------------------------------------ keeping what you accept
def _inert(text: str) -> str:
    """Model-written text as plain characters in a note: no [[link]] and no #tag that you did not write yourself."""
    while "[[" in text or "]]" in text:
        text = text.replace("[[", "[").replace("]]", "]")
    return text.replace("#", "＃")


def _same_title(db: DB, doc: dict) -> bool:
    """Another live document answers to this title: a note or a link by title could reach the wrong one."""
    k = pages.key(doc["title"])  # compared in Python: SQLite's lower() folds only ASCII and keeps double spaces
    return any(pages.key(o["title"]) == k for o in db.all("SELECT title FROM documents WHERE deleted=0 AND id!=?", (doc["id"],)))


def _link(db: DB, doc: dict, sentence: int, shared: bool) -> str:
    """A link back to the passage, only when the title can reach nothing else (a note with that title wins a link)."""
    t = " ".join(doc["title"].split())
    note_named = db.one("SELECT 1 FROM pages WHERE title_key=? AND deleted=0", (pages.key(t),))
    if t and t == doc["title"] and not shared and not note_named and not re.search(r"[\[\]|#]", t) and len(t) <= 190:
        return f"[[{t}#s{sentence}|{t}]]"
    return f"{_inert(t)}, sentence {sentence + 1}"


def _note_line(chosen: str, item: dict) -> str:
    """What you keep, with every [[link]] and #tag the model wrote made inert, also after you edited the line;
    a link or tag that is not in the model's text is yours and works as usual."""
    model = item["text"]
    chosen = pages.LINK.sub(lambda m: _inert(m.group(0)) if m.group(0) in model else m.group(0), chosen)
    return pages.TAG.sub(lambda m: _inert(m.group(0)) if re.search(r"(?<![\w&#/])" + re.escape(m.group(0)) + r"(?![\w-])", model) else m.group(0), chosen)


def accept(db: DB, result_id: str, chosen: list[dict], as_kind: str | None) -> dict:
    row = db.one("SELECT * FROM ai_results WHERE id=? AND feature=? AND deleted=0", (result_id, FEATURE)) if ID.fullmatch(result_id or "") else None
    if not row:
        raise NotFound()
    payload = json.loads(row["payload"])
    doc = db.one("SELECT id, title FROM documents WHERE id=? AND deleted=0", (payload["document_id"],))
    if not doc:
        raise NotFound()
    if not chosen:
        raise Invalid("Choose at least one item to keep.")
    kept = set(payload.get("kept") or [])
    picked, seen = [], set()
    for c in chosen:
        i = c.get("index")
        if not isinstance(i, int) or not 0 <= i < len(payload["items"]):
            raise Invalid("That item is not in this result.")
        item = payload["items"][i]
        text, answer = " ".join(str(c.get("text") or "").split()), " ".join(str(c.get("answer") or "").split())
        if not text:
            raise Invalid("An item to keep needs its text.")
        if not item["verified"]:
            raise Unchecked()
        if i in seen or i in kept:  # the same item twice, or kept before: once is enough
            continue
        seen.add(i)
        picked.append((i, item, text[:500], answer[:800]))
    kind = as_kind or payload["kind"]
    if kind in ("cards", "quiz"):
        if any(not a for *_, a in picked):
            raise Invalid("A card needs an answer.")
    with db.transaction():  # two keeps at once: each reads the note (and the kept list) the other wrote
        fresh = json.loads(db.scalar("SELECT payload FROM ai_results WHERE id=?", (result_id,)) or "{}")
        done = set(fresh.get("kept") or [])
        picked = [x for x in picked if x[0] not in done]
        out = _keep_cards(db, result_id, doc, picked) if kind in ("cards", "quiz") else _keep_notes(db, doc, picked)
        payload["kept"] = sorted(kept | done | {i for i, *_ in picked})
        db.update("ai_results", result_id, {"payload": json.dumps(payload, ensure_ascii=False), "status": "accepted"})
    return {**out, "kept": payload["kept"]}


def _keep_cards(db: DB, result_id: str, doc: dict, picked: list) -> dict:
    """Insert only: a card with the same question (live, or deleted by you) is not added again, nothing is overwritten.
    The back carries the passage, so Review shows what to check the card against."""
    known = {pages.key(r["front"]) for r in db.all("SELECT front FROM cards WHERE source_type='ai' AND document_id=?", (doc["id"],))}
    added = skipped = 0
    for i, item, text, answer in picked:
        source_id = f"{result_id}:{i}"
        if pages.key(text) in known or db.one("SELECT 1 FROM cards WHERE source_type='ai' AND source_id=?", (source_id,)):
            skipped += 1
            continue
        known.add(pages.key(text))
        services.upsert_card(db, "ai", source_id, text, f"{answer}\n\nFrom the passage: “{item['quote']}”", doc["id"])
        added += 1
    return {"cards": added, "skipped": skipped}


def _keep_notes(db: DB, doc: dict, picked: list) -> dict:
    shared = _same_title(db, doc)
    title = f"Study notes: {' '.join(doc['title'].split())}"[:180] + (f" ({doc['id'][:6]})" if shared else "")
    page = pages.find(db, title) or pages.create(db, title, "")
    body = page["body"].rstrip()
    new = []
    for _, item, text, _a in picked:
        line = _note_line(text, item)
        if f"\n- {line}\n" in f"\n{body}\n" or any(x.startswith(f"- {line}\n") for x in new):  # already there ("Ask again" can write it again)
            continue
        new.append(f"- {line}\n  > {_inert(item['quote'])} — {_link(db, doc, item['sentence'], shared)}")
    if new:  # a label above each batch, unless the page still ends with the last batch as it was written
        at = body.rfind(LABEL)
        if at < 0 or not all(OURS.fullmatch(b) for b in body[at + len(LABEL):].strip().split("\n\n") if b):
            body = f"{body}\n\n{LABEL}" if body else LABEL
        body += "".join(f"\n\n{x}" for x in new)
    added = len(new)
    body += "\n"
    if len(body) > pages.MAX_BODY:
        raise Invalid("That note is full. Start a new one.")
    db.update("pages", page["id"], {"body": body, "tags": pages.tags_in(body)})
    pages.relink(db, page["id"], body)
    return {"page_id": page["id"], "title": title, "added": added}


class Unchecked(Exception):
    pass


# ------------------------------------------------------------------ routes
class WriteIn(BaseModel):
    source: Literal["highlights", "section"]
    kind: Literal["notes", "cards", "quiz"]
    section_id: str = Field("", max_length=40)
    at: int | None = Field(None, ge=0)  # the sentence you are at: a long section is sent around it
    fresh: bool = False


class Chosen(BaseModel):
    index: int
    text: str = Field("", max_length=2000)
    answer: str = Field("", max_length=3000)


class AcceptIn(BaseModel):
    items: list[Chosen] = Field(default_factory=list, max_length=20)
    keep_as: Literal["notes", "cards"] | None = None  # a quiz question can be kept as a card


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/documents/{doc_id}/study-notes")
    def api_study_notes(doc_id: str, body: WriteIn):
        """A plain `def`: the call runs on a worker thread, so the reader never waits on it."""
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
            raise HTTPException(404, "document not found")
        try:
            return {"result": write(port, db, doc_id, body.source, body.kind, body.section_id, body.fresh, body.at)}
        except NotFound:
            raise HTTPException(404, "That section is not in this document.") from None
        except Invalid as e:
            raise HTTPException(409, str(e)) from None
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None

    @app.post("/api/ai/results/{result_id}/accept")
    def api_accept(result_id: str, body: AcceptIn):
        try:
            return accept(db, result_id, [c.model_dump() for c in body.items], body.keep_as)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Unchecked:
            raise HTTPException(409, "Only items whose passage was checked can be kept.") from None
        except Invalid as e:
            raise HTTPException(409, str(e)) from None
