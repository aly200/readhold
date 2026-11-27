"""One search over everything you keep in Readhold (Ctrl+K): notes, tasks, documents and the passages inside
them, study files, quests, glossary terms and ideas. It only reads, and only on this machine."""
from __future__ import annotations

from fastapi import FastAPI

from . import passages
from .db import DB

PER_KIND = 6


def _like(q: str) -> str:
    return "%" + q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _around(text: str, q: str, n: int = 90) -> str:
    """A short piece of the text around the first place the words appear."""
    flat = " ".join(text.split())
    at = flat.casefold().find(q.casefold())
    if at < 0:
        return flat[:n]
    start = max(0, at - n // 3)
    return ("…" if start else "") + flat[start:start + n]


def search(db: DB, q: str) -> list[dict]:
    q = " ".join(q.split())[:100]
    if not q:
        return []
    like = _like(q)
    out: list[dict] = []
    seen: set[str] = set()
    for r in db.all("SELECT id, title, body FROM pages WHERE deleted=0 AND title_key LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?", (like, PER_KIND)):
        seen.add(r["id"])
        out.append({"kind": "note", "id": r["id"], "title": r["title"], "hint": ""})
    for r in db.all("SELECT id, title, body FROM pages WHERE deleted=0 AND lower(body) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?", (like, PER_KIND * 2)):
        if r["id"] not in seen and len(seen) < PER_KIND * 2:
            seen.add(r["id"])
            out.append({"kind": "note", "id": r["id"], "title": r["title"], "hint": _around(r["body"], q)})
    for r in db.all("SELECT id, text, due, area FROM todos WHERE deleted=0 AND done_at IS NULL AND lower(text) LIKE ? ESCAPE '\\' ORDER BY ord LIMIT ?", (like, PER_KIND)):
        out.append({"kind": "task", "id": r["id"], "title": r["text"], "hint": " · ".join(x for x in (r["due"] or "anytime", r["area"]) if x)})
    for kind, table in (("document", "documents"), ("lecture", "lectures"), ("quest", "quests")):
        for r in db.all(f"SELECT id, title FROM {table} WHERE deleted=0 AND lower(title) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?", (like, PER_KIND)):
            out.append({"kind": kind, "id": r["id"], "title": r["title"], "hint": ""})
    if len(q) >= 3:  # the text of your documents: a passage opens the reader at that sentence
        per_doc: dict[str, int] = {}
        for r in db.all("SELECT s.document_id, s.ord, s.text, d.title FROM sentences s JOIN documents d ON d.id=s.document_id"
                        " WHERE s.deleted=0 AND d.deleted=0 AND lower(s.text) LIKE ? ESCAPE '\\' ORDER BY d.updated_at DESC, s.ord LIMIT 60", (like,)):
            if per_doc.get(r["document_id"], 0) >= 2 or sum(per_doc.values()) >= PER_KIND:
                continue  # a couple of passages per document, so one long paper does not fill the list
            per_doc[r["document_id"]] = per_doc.get(r["document_id"], 0) + 1
            out.append({"kind": "passage", "id": f"{r['document_id']}:{r['ord']}", "title": _around(r["text"], q, 110), "hint": r["title"],
                        "document_id": r["document_id"], "sentence": r["ord"]})
        # then the sections that hold the words anywhere, best first (the full-text index): the words need not be together
        for hit in passages.search_sections(db, q, limit=PER_KIND):
            if per_doc.get(hit["document_id"], 0) >= 2 or sum(per_doc.values()) >= PER_KIND:
                continue
            if any(o["kind"] == "passage" and o["document_id"] == hit["document_id"] and o["sentence"] == hit["sentence"] for o in out):
                continue
            per_doc[hit["document_id"]] = per_doc.get(hit["document_id"], 0) + 1
            out.append({"kind": "passage", "id": f"{hit['document_id']}:{hit['sentence']}", "title": _around(hit["snippet"], q.split()[0], 110),
                        "hint": f"{hit['document_title']} · {hit['section_title']}", "document_id": hit["document_id"], "sentence": hit["sentence"]})
    for r in db.all("SELECT id, term, definition FROM terms WHERE deleted=0 AND lower(term) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?", (like, PER_KIND)):
        out.append({"kind": "term", "id": r["id"], "title": r["term"], "hint": " ".join(r["definition"].split())[:90]})
    for r in db.all("SELECT id, text FROM ideas WHERE deleted=0 AND lower(text) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?", (like, 3)):
        out.append({"kind": "idea", "id": r["id"], "title": " ".join(r["text"].split())[:120], "hint": ""})
    return out


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/search")
    def api_search(q: str = ""):
        return {"results": search(db, q)}
