"""Organize the library with a model (milestone 3.3 of docs/ai/PLAN.md): tags that reuse yours, and related documents.

The non-AI version is `readhold/organize.py`: your own document tags (also your collections), related documents
found by shared words, and tags suggested by code. With AI switched on, and only when you ask, a model reads for one
document: its title, its section titles, its opening (`OPENING` characters, by whole sentences) and your highlights
in it; the tags you already use (as your own text); and the titles of the documents code found closest to it,
numbered. Never the whole document, never other documents' text.

What comes back is checked before you see it:
- a tag must be one word as a tag is written (`organize.clean_tag`); one already on the document, a repeat, or a
  bad one is dropped. Your existing tags come first, and at most `MAX_NEW` new ones are kept (the rest are dropped
  and counted). `reuse` is the share of suggested tags you already use: the plan's measure for this milestone.
- a tag's quote counts only when it is, on whole words, in the text sent and passes `verify_citations`; it is then
  shown in the document's own words. A tag without one is shown as the model's guess.
- a related document must be a number of the list code made, once; its reason is labelled as the model's.

Nothing changes when the suggestion arrives. You add a tag (the page sends the tags it expects to replace, so Undo
never overwrites a later change) or open a related document.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import organize as plain
from ..db import DB
from . import guard, privacy, prompts, results
from .notes import _own_words
from .port import AIError, AIOff, Port
from .resume import status_error

FEATURE = "organize"
ID = re.compile(r"[0-9a-f]{32}")
OPENING = 500  # characters of the document's opening, by whole sentences
MAX_HIGHLIGHTS = 8
MAX_TAGS = 6
MAX_NEW = 2
MAX_CANDIDATES = 8
CANDIDATE_SCORE = 0.05  # looser than "related" on the plain page: the model chooses among these
MAX_RELATED = 5
MIN_QUOTE_WORDS = 4
CAPS = {"reason": 200, "quote": 400, "titles": 1_200, "tags": 1_500}


# loose on purpose: a field left null, of the wrong type or too long drops that part, not the whole answer
class TagOut(BaseModel):
    tag: guard.LooseText = ""
    quote: guard.LooseText = ""


class RelatedOut(BaseModel):
    document: Any = 0  # as the model wrote it (lax ints would turn `true`, 1.0 and "1" into 1); code takes real ints only
    reason: guard.LooseText = ""


class OrganizeOut(BaseModel):
    tags: Annotated[list[TagOut], guard.loose_list(20)] = []
    related: Annotated[list[RelatedOut], guard.loose_list(20)] = []


# ------------------------------------------------------------------ what the model reads
def _sources(db: DB, doc: dict, cloud: bool = False) -> tuple[list[guard.Source], list[dict]]:
    name = db.scalar("SELECT source FROM documents WHERE id=?", (doc["id"],)) or ""
    titles = [r["title"] for r in db.all("SELECT title FROM sections WHERE document_id=? AND deleted=0 AND hidden=0 ORDER BY ord", (doc["id"],))]
    rows = db.all("SELECT s.ord, s.text, p.section_id FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                  " JOIN sections c ON c.id=p.section_id AND c.deleted=0 AND c.hidden=0 WHERE s.document_id=? AND s.deleted=0 ORDER BY s.ord LIMIT 200", (doc["id"],))
    head = f"(Document: {doc['title'][:200]}. Sections: {'; '.join(titles)[:CAPS['titles']]})"
    out: list[guard.Source] = []
    size, part, first, sec = 0, [], None, None
    for r in rows:  # the opening, one source per section it reaches, so a quote is checked against its own section
        if size + len(r["text"]) > OPENING and size:
            break
        if r["section_id"] != sec and part:
            out.append(guard.Source(f"{doc['id']}:{first}", "\n".join(part), "imported", name))
            part = []
        if not part:
            first, sec = r["ord"], r["section_id"]
        part.append(r["text"])
        size += len(r["text"]) + 1
    if part:
        out.append(guard.Source(f"{doc['id']}:{first}", "\n".join(part), "imported", name))
    if out:
        out[0].text = f"{head}\n{out[0].text}"
    else:
        out.append(guard.Source(f"{doc['id']}:0", head, "imported", name))
    for h in db.all("SELECT h.sentence, h.text FROM highlights h JOIN sentences s ON s.document_id=h.document_id AND s.ord=h.sentence AND s.deleted=0"
                    " JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0 JOIN sections c ON c.id=p.section_id AND c.hidden=0 AND c.deleted=0"
                    " WHERE h.document_id=? AND h.deleted=0 ORDER BY h.sentence LIMIT ?", (doc["id"], MAX_HIGHLIGHTS)):  # not from hidden sections
        out.append(guard.Source(f"{doc['id']}:{h['sentence']}", f"(Highlighted)\n{h['text']}", "imported", name))
    strict = privacy.only_tagged(db)
    keep_here = (lambda tags: privacy._keeps_here(tags, strict)) if cloud else None  # noqa: E731
    known = [t for t, _ in plain.known_tags(db, keep_here).most_common(80)]
    mine = plain.tags_of(db, doc["id"])
    listed = ""
    for t in known:  # whole tags only, within the cap
        if len(listed) + len(t) + 2 > CAPS["tags"]:
            break
        listed = f"{listed}, {t}" if listed else t
    out.append(guard.Source(f"tags:{doc['id']}", f"(The tags you already use)\n{listed or 'none yet'}\n"
                                                  f"(Already on this document)\n{', '.join(mine) or 'none'}", "yours"))
    cands = plain.related(db, doc["id"], n=MAX_CANDIDATES * 2, floor=CANDIDATE_SCORE)
    if cloud:  # a file of secrets, or a private document, is not even named to a cloud model
        cands = [c for c in cands if not guard.sensitive_name(db.scalar("SELECT source FROM documents WHERE id=?", (c["id"],)) or "")
                 and not privacy.document_private(db, c["id"])]
    cands = cands[:MAX_CANDIDATES]
    if cands:
        out.append(guard.Source(f"docs:{doc['id']}", "(Other documents in your library, numbered)\n" + "\n".join(f"{i}. {c['title'][:200]}" for i, c in enumerate(cands, 1)), "imported"))
    return out, cands


def _body(text: str) -> str:
    return text.split("\n", 1)[1] if text.startswith("(") and "\n" in text else text


def _quote(db: DB, doc_id: str, quote: str, sent: dict[str, str]) -> str | None:
    """The document's own words for a quote that is in a text sent about this document and in the library now."""
    for a, text in sent.items():
        m = guard.DOC_ANCHOR.fullmatch(a)
        if not m or m.group(1) != doc_id or not guard.quote_in(quote, _body(text), MIN_QUOTE_WORDS):
            continue
        got = guard.verify_citations(db, [{"anchor": a, "quote": quote}])
        if got.kept:
            k = got.kept[0]
            return _own_words(db, k["section_id"], k["sentence"], quote) or guard.safe_output(quote, CAPS["quote"]).text
    return None


# ------------------------------------------------------------------ the call
def suggest(port: Port, db: DB, doc_id: str, fresh: bool = False) -> dict:
    doc = db.one("SELECT id, title FROM documents WHERE id=? AND deleted=0", (doc_id,)) if ID.fullmatch(doc_id or "") else None
    if not doc:
        raise HTTPException(404, "not found")
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    sources, cands = _sources(db, doc, cloud=guard.leaves(port))
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, *(f"{s.anchor}\n{s.text}" for s in sources))
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, doc_id, key)
        if kept and not fresh:
            return kept
        r = guard.ask(port, db, FEATURE, prompt.text, sources, budget=FEATURE, schema=OrganizeOut, prompt_version=prompt.version)
        known = set(plain.known_tags(db))
        have = set(plain.tags_of(db, doc_id))
        tags, seen, dropped, raw = [], set(), 0, []
        for t in r.data["tags"]:
            tag = plain.clean_tag(str(t.get("tag") or ""))
            if tag is None:
                dropped += 1
                continue
            if tag not in raw:
                raw.append(tag)
            if tag in have or tag in seen:
                continue
            seen.add(tag)
            one = {"tag": tag, "existing": tag in known, "verified": False}
            q = _quote(db, doc_id, t.get("quote") or "", r.sent)
            if q:
                one.update(verified=True, quote=q)
            tags.append(one)
        ordered = [t for t in tags if t["existing"]] + [t for t in tags if not t["existing"]]
        new = [t for t in ordered if not t["existing"]]
        dropped += max(0, len(new) - MAX_NEW)
        ordered = [t for t in ordered if t["existing"]] + new[:MAX_NEW]
        dropped += max(0, len(ordered) - MAX_TAGS)
        ordered = ordered[:MAX_TAGS]
        related, used = [], set()
        for x in r.data["related"]:
            n = x.get("document")
            if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= len(cands) or n in used or len(related) >= MAX_RELATED:
                continue
            used.add(n)
            c = cands[n - 1]
            related.append({"id": c["id"], "title": c["title"], "shared": c["shared"], "reason": guard.safe_output(x.get("reason") or "", CAPS["reason"]).text})
        proven = sum(1 for t in ordered if t["verified"])
        payload = {"document_id": doc_id, "tags": ordered, "related": related, "dropped": dropped,
                   "reuse": round(sum(1 for t in ordered if t["existing"]) / len(ordered), 3) if ordered else None,
                   # the plan's measure, on what the model wrote (valid tags, before code's filters): yours, or new
                   "model_tags": len(raw), "model_reuse": round(sum(1 for t in raw if t in known) / len(raw), 3) if raw else None,
                   "status": "verified" if ordered and proven == len(ordered) else "partly" if proven else "unverified",
                   "links": list(dict.fromkeys(r.links)), "warning": r.warning}
        return results.keep(db, FEATURE, doc_id, key, payload, prompt.version, r.log_id, replaces=kept["id"] if kept else None)


# ------------------------------------------------------------------ routes
class SuggestIn(BaseModel):
    fresh: bool = False


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/documents/{doc_id}/organize/suggest")
    def api_organize_suggest(doc_id: str, body: SuggestIn):
        """A plain `def`: the call runs on a worker thread, and the app is never blocked."""
        try:
            return {"result": suggest(port, db, doc_id, body.fresh)}
        except guard.Blocked as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None
