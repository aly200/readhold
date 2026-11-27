"""Organize the library (milestone 3.3 of docs/ai/PLAN.md, the layer without a model).

- Tags on documents: words you give a document, written like note #tags (a letter first, then letters, digits,
  "-" or "_", at most 40). A tag is also a collection: the Documents tab shows the documents that carry it.
  Only you set them. A change can name the tags it expects to replace (`expect`): Undo uses it, so it never
  overwrites a change made since.
- Related documents: found by the words documents share (TF-IDF over the title, the section titles, your
  highlights and the start of the text). No embeddings and no model: each result names the words it shares.
- Suggested tags: tags that related documents carry, and tags you already use (on documents or notes) whose word
  is one of this document's main words. Each says why. They are suggestions: nothing is added until you add it.

It only counts and compares text; it never follows it.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import think
from .db import DB

ID = re.compile(r"[0-9a-f]{32}")
TAG = re.compile(r"[^\W\d_][\w-]{0,39}")
MAX_TAGS = 12  # on one document
MAX_DOCS = 400  # the most recently changed documents are compared
SAMPLE_WORDS = 2_000  # words of a document's text that count, from its start
RELATED_SCORE = 0.12  # how alike two documents must be to be called related
MAX_RELATED = 5
MAIN_WORDS = 30  # a document's strongest words: a tag you use that is one of them is suggested
MAX_SUGGESTED = 6


def clean_tag(raw: str) -> str | None:
    """A tag as it is kept: composed (NFC, so "café" is one way), lower case, a letter first."""
    t = unicodedata.normalize("NFC", unicodedata.normalize("NFC", raw.strip().lstrip("#")).lower())
    return t if TAG.fullmatch(t) and t[0].isalpha() else None


def tags_of(db: DB, doc_id: str) -> list[str]:
    return (db.scalar("SELECT tags FROM documents WHERE id=?", (doc_id,)) or "").split()


def known_tags(db: DB, keep_here=None) -> Counter:
    """Every tag you use, on documents and on notes, with how often. `keep_here(tags)`: items it is true for are not
    counted (a cloud model is not told the tags of private items, nor the word "private" itself)."""
    out: Counter = Counter()
    for table in ("documents", "pages"):
        for r in db.all(f"SELECT tags FROM {table} WHERE deleted=0 AND tags!=''"):  # noqa: S608  (two fixed names)
            if keep_here is None or not keep_here(r["tags"]):
                out.update(r["tags"].split())
    if keep_here is not None:
        out.pop("private", None)
    return out


def set_tags(db: DB, doc_id: str, raw: list[str], expect: list[str] | None = None) -> list[str]:
    if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
        raise HTTPException(404, "not found")
    tags: list[str] = []
    for r in raw:
        t = clean_tag(r)
        if t is None:
            raise HTTPException(422, "One of these cannot be a tag: a tag is one word, starting with a letter, at most 40 characters.")
        if t not in tags:
            tags.append(t)
    if len(tags) > MAX_TAGS:
        raise HTTPException(422, f"At most {MAX_TAGS} tags on one document.")
    if expect is not None:
        want = [clean_tag(e) for e in expect]
        if None in want:
            raise HTTPException(422, "`expect` holds something that is not a tag.")
        if tags_of(db, doc_id) != want:
            raise HTTPException(409, "The tags changed since. Nothing was changed; edit them by hand.")
    db.update("documents", doc_id, {"tags": " ".join(tags)})
    return tags


# ------------------------------------------------------------------ related documents, by shared words
def _profiles(db: DB, include: str = "") -> dict[str, dict]:
    """Per document: its words, weighted (title x3, section titles and highlights x2, the start of the text x1).
    The most recently changed MAX_DOCS documents, plus `include` (the one asked about) however old it is."""
    docs = db.all("SELECT id, title, tags FROM documents WHERE deleted=0 ORDER BY updated_at DESC LIMIT ?", (MAX_DOCS,))
    if include and not any(d["id"] == include for d in docs):
        docs += db.all("SELECT id, title, tags FROM documents WHERE deleted=0 AND id=?", (include,))
    out = {}
    for d in docs:
        tf: Counter = Counter()
        for w in think.words(d["title"]):
            tf[w] += 3
        for r in db.all("SELECT title FROM sections WHERE document_id=? AND deleted=0 AND hidden=0", (d["id"],)):
            for w in think.words(r["title"]):
                tf[w] += 2
        for r in db.all("SELECT text FROM highlights WHERE document_id=? AND deleted=0 LIMIT 200", (d["id"],)):
            for w in think.words(r["text"]):
                tf[w] += 2
        n = 0
        for r in db.all("SELECT text FROM sentences WHERE document_id=? AND deleted=0 ORDER BY ord LIMIT 600", (d["id"],)):
            ws = think.words(r["text"])
            tf.update(ws[: max(0, SAMPLE_WORDS - n)])
            n += len(ws)
            if n >= SAMPLE_WORDS:
                break
        out[d["id"]] = {"id": d["id"], "title": d["title"], "tags": d["tags"].split(), "tf": tf}
    df: Counter = Counter()
    for p in out.values():
        df.update(p["tf"].keys())
    n = len(out)
    for p in out.values():
        vec = {w: (1 + math.log(c)) * (math.log((n + 1) / (df[w] + 1)) + 1) for w, c in p["tf"].items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        p["vec"] = {w: v / norm for w, v in vec.items()}
    return out


def related(db: DB, doc_id: str, profiles: dict | None = None, n: int = MAX_RELATED, floor: float = RELATED_SCORE) -> list[dict]:
    profiles = profiles if profiles is not None else _profiles(db, doc_id)
    me = profiles.get(doc_id)
    if not me:
        return []
    out = []
    for p in profiles.values():
        if p is me:
            continue
        score, shared = think._alike(me, p)
        if score >= floor and len(shared) >= 2:
            out.append({"id": p["id"], "title": p["title"], "score": round(score, 3), "shared": shared, "tags": p["tags"]})
    out.sort(key=lambda x: -x["score"])
    return out[:n]


def suggested(db: DB, doc_id: str, profiles: dict | None = None) -> list[dict]:
    """Tags worth adding, each with its reason. Only tags you already use: a new word is for you (or a model) to propose."""
    profiles = profiles if profiles is not None else _profiles(db, doc_id)
    me = profiles.get(doc_id)
    if not me:
        return []
    have = set(me["tags"])
    known = known_tags(db)
    out: dict[str, dict] = {}
    for r in related(db, doc_id, profiles):
        for t in r["tags"]:
            if t not in have and t not in out:
                out[t] = {"tag": t, "existing": True, "score": r["score"], "reason": f"The related document “{r['title']}” has it."}
    main = {w for w, _ in sorted(me["vec"].items(), key=lambda x: -x[1])[:MAIN_WORDS]}
    for t, count in known.most_common():
        if t in have or t in out:
            continue
        ws = think.words(t.replace("-", " ").replace("_", " "))
        if ws and all(w in main for w in ws):
            out[t] = {"tag": t, "existing": True, "score": 0.1 + 0.01 * min(count, 9), "reason": f"You use #{t}, and “{' '.join(ws)}” is one of this document's main words."}
    return sorted(out.values(), key=lambda s: -s["score"])[:MAX_SUGGESTED]


def overview(db: DB, doc_id: str) -> dict:
    if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
        raise HTTPException(404, "not found")
    profiles = _profiles(db, doc_id)
    return {"tags": tags_of(db, doc_id), "known": [t for t, _ in known_tags(db).most_common(60)],
            "related": [{k: r[k] for k in ("id", "title", "score", "shared")} for r in related(db, doc_id, profiles)],
            "suggested": [{k: s[k] for k in ("tag", "existing", "reason")} for s in suggested(db, doc_id, profiles)]}


# ------------------------------------------------------------------ routes
class TagsIn(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=40)
    expect: list[str] | None = Field(None, max_length=40)


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/organize/{doc_id}")
    def api_organize(doc_id: str):
        return overview(db, doc_id)

    @app.put("/api/documents/{doc_id}/tags")
    def api_tags(doc_id: str, body: TagsIn):
        return {"tags": set_tags(db, doc_id, body.tags, body.expect)}
