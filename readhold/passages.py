"""Passages: find the section of a document that holds some words, and say where a reading session went.

This is plain app data and plain search. No model is involved, and nothing here depends on one.

- The index is `section_fts` (SQLite FTS5): one row per section, with its title and text. `reindex` rebuilds a
  document's rows; it is called after an import and after every change to a document's structure.
- `search_sections` ranks sections with BM25 (a title match counts more) and returns an anchor for each hit:
  the document, the section, and the sentence to open the reader at.
- `last_session` describes the last finished reading session of a document from what was recorded while reading.
"""
from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException

from .db import DB

ID = re.compile(r"[0-9a-f]{32}")
WORD = re.compile(r"[^\W_]+", re.UNICODE)
MAX_WORDS = 12  # words taken from a query
MAX_QUERY = 200
TITLE_WEIGHT, BODY_WEIGHT = 4.0, 1.0


def reindex(db: DB, doc_id: str) -> int:
    """Rebuild the index rows of one document. A removed document has none. Returns the number of rows."""
    with db.lock:
        db.conn.execute("DELETE FROM section_fts WHERE document_id=?", (doc_id,))
        if not db.conn.execute("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)).fetchone():
            return 0
        rows = db.conn.execute(
            "SELECT c.id AS section_id, c.title, MIN(s.ord) AS first_ord, group_concat(s.text, char(10)) AS body"
            " FROM (SELECT s.ord, s.text, p.section_id FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id"
            "       WHERE s.document_id=? AND s.deleted=0 AND p.deleted=0 ORDER BY s.ord) s"
            " JOIN sections c ON c.id=s.section_id WHERE c.deleted=0 GROUP BY c.id ORDER BY c.ord",
            (doc_id,),
        ).fetchall()
        db.conn.executemany(
            "INSERT INTO section_fts (title, body, document_id, section_id, first_ord) VALUES (?,?,?,?,?)",
            [(r["title"], r["body"] or "", doc_id, r["section_id"], r["first_ord"]) for r in rows],
        )
        return len(rows)


def ensure_index(db: DB) -> int:
    """Index the documents that have no rows yet (imported before the index existed). Returns how many were added."""
    missing = db.all("SELECT id FROM documents WHERE deleted=0 AND id NOT IN (SELECT DISTINCT document_id FROM section_fts)")
    return sum(1 for d in missing if reindex(db, d["id"]))


def _words(q: str) -> list[str]:
    return [w.casefold() for w in WORD.findall(q[:MAX_QUERY])][:MAX_WORDS]


def _match(words: list[str], joiner: str) -> str:
    """An FTS5 query from plain words. Each word is quoted, so nothing the user types is read as query syntax;
    the star makes the start of a word enough ("transform" finds "transformers")."""
    return joiner.join(f'"{w}"*' for w in words)


def _best_sentence(db: DB, section_id: str, words: list[str], fallback: int) -> tuple[int, str]:
    """The sentence of the section that holds the most query words: the place to open the reader at."""
    best, best_n, best_text = fallback, 0, ""
    for s in db.all("SELECT s.ord, s.text FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id"
                    " WHERE p.section_id=? AND s.deleted=0 AND p.deleted=0 ORDER BY s.ord", (section_id,)):
        found = {w.casefold() for w in WORD.findall(s["text"])}
        n = sum(1 for w in words if any(f.startswith(w) for f in found))
        if n > best_n:
            best, best_n, best_text = s["ord"], n, s["text"]
        if not best_text:
            best_text = s["text"]
    return best, " ".join(best_text.split())[:240]


def search_sections(db: DB, q: str, limit: int = 8, document_id: str | None = None) -> list[dict]:
    """Sections that match the words, best first. All words must be there; if no section has them all, any of them."""
    words = _words(q)
    if not words:
        return []
    where, params = "", []
    if document_id:
        where, params = " AND f.document_id=?", [document_id]
    sql = ("SELECT f.document_id, f.section_id, f.title AS section_title, f.first_ord, d.title AS document_title,"
           f" bm25(section_fts, {TITLE_WEIGHT}, {BODY_WEIGHT}) AS rank"
           " FROM section_fts f JOIN documents d ON d.id=f.document_id"
           f" WHERE section_fts MATCH ? AND d.deleted=0{where} ORDER BY rank LIMIT ?")
    rows = db.all(sql, (_match(words, " AND "), *params, limit))
    if not rows and len(words) > 1:
        rows = db.all(sql, (_match(words, " OR "), *params, limit))
    out = []
    for r in rows:
        ord_, snippet = _best_sentence(db, r["section_id"], words, r["first_ord"] or 0)
        out.append({"document_id": r["document_id"], "document_title": r["document_title"], "section_id": r["section_id"],
                    "section_title": r["section_title"], "sentence": ord_, "snippet": snippet, "score": round(-r["rank"], 3)})
    return out


def last_session(db: DB, doc_id: str) -> dict | None:
    """The last finished reading session of a document: when, how long, where it went, what you marked, what you
    said comes next. Everything is read from what was saved while you read."""
    s = db.one("SELECT id, started_at, ended_at, focused_ms, sentences_read, question, next_step, start_ord, last_ord FROM sessions"
               " WHERE document_id=? AND deleted=0 AND ended_at IS NOT NULL AND start_ord IS NOT NULL"  # a timer run on the document is not a reading session
               " ORDER BY ended_at DESC LIMIT 1", (doc_id,))
    if not s:
        return None
    read = "s.read_at>=? AND s.read_at<=?"
    args: list = [doc_id, s["started_at"], s["ended_at"]]
    sections = db.all(
        "SELECT c.id, c.title, COUNT(*) AS sentences FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id"
        f" JOIN sections c ON c.id=p.section_id WHERE s.document_id=? AND s.deleted=0 AND c.deleted=0 AND {read}"
        " GROUP BY c.id ORDER BY c.ord", args)
    if not sections and s["start_ord"] is not None and s["last_ord"] is not None:
        lo, hi = sorted((s["start_ord"], s["last_ord"]))  # nothing was marked read: the stretch between start and stop
        sections = db.all(
            "SELECT c.id, c.title, COUNT(*) AS sentences FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id"
            " JOIN sections c ON c.id=p.section_id WHERE s.document_id=? AND s.deleted=0 AND c.deleted=0 AND s.ord BETWEEN ? AND ?"
            " GROUP BY c.id ORDER BY c.ord", (doc_id, lo, hi))
    highlights = db.all("SELECT id, sentence, end_sentence, type, text, note FROM highlights WHERE document_id=? AND deleted=0"
                        " AND created_at>=? AND created_at<=? ORDER BY sentence", (doc_id, s["started_at"], s["ended_at"]))
    return {**s, "sections": sections, "highlights": highlights}


def register(app: FastAPI, db: DB) -> None:
    ensure_index(db)

    def need_doc(doc_id: str) -> None:
        if not ID.fullmatch(doc_id or "") or not db.one("SELECT 1 FROM documents WHERE id=? AND deleted=0", (doc_id,)):
            raise HTTPException(404, "document not found")

    @app.get("/api/passages")
    def api_passages(q: str = "", document_id: str | None = None):
        if document_id is not None:
            need_doc(document_id)
        return {"results": search_sections(db, q, document_id=document_id)}

    @app.get("/api/documents/{doc_id}/last-session")
    def api_last_session(doc_id: str):
        need_doc(doc_id)
        return {"session": last_session(db, doc_id)}
