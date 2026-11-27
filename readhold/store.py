"""Turn a ParsedDoc into rows, and read a document back for the reader."""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import config, density, passages
from .db import DB, new_id, now
from .text import BACKGROUND_KINDS, HIDDEN_KINDS, count_words, section_kind, split_sentences

if TYPE_CHECKING:
    from .importers.model import ParsedDoc

PACED_KINDS = {"text", "list"}  # code, equations, captions and references are set aside, not paced


def save_parsed(db: DB, doc: "ParsedDoc", source: str, file_hash: str | None, why: str = "") -> dict:
    t = now()
    common = {"device_id": db.device, "created_at": t, "updated_at": t, "deleted": 0}
    doc_id = new_id()
    p_ord = 0
    s_ord = 0
    sec_rows, par_rows, sen_rows = [], [], []
    for i, sec in enumerate(doc.sections):
        kind = sec.kind or section_kind(sec.title)
        sec_id = new_id()
        sec_rows.append(
            (sec_id, doc_id, i, sec.title[:300], kind, sec.level, int(kind in BACKGROUND_KINDS), int(kind in HIDDEN_KINDS))
        )
        for para in sec.paras:
            par_id = new_id()
            asset = ""
            if para.image:
                asset = f"{par_id}.png"
                folder = assets_dir(doc_id)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / asset).write_bytes(para.image)
            par_rows.append((par_id, doc_id, sec_id, p_ord, para.kind, asset))
            p_ord += 1
            if para.kind in PACED_KINDS:
                sentences = split_sentences(para.text)
            else:
                # kept whole; not paced. Code keeps the indent of its first line
                sentences = [para.text.strip("\n").rstrip() if para.kind == "code" else para.text.strip()]
            for s in sentences:
                d = density.score(s) if para.kind in PACED_KINDS else 0.0
                sen_rows.append((new_id(), doc_id, par_id, s_ord, s, count_words(s), d))
                s_ord += 1

    with db.transaction():
        db.conn.execute(
            "INSERT INTO documents (id, title, source, source_type, file_hash, why, import_warning, total_sentences,"
            " status, import_flags, device_id, created_at, updated_at, deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, doc.title[:300], source, doc.source_type, file_hash, why, doc.warning, s_ord, "queued",
             " ".join(doc.flags), db.device, t, t, 0),
        )
        db.conn.executemany(
            "INSERT INTO sections (id, document_id, ord, title, kind, level, background, hidden, device_id, created_at,"
            " updated_at, deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [r + (common["device_id"], t, t, 0) for r in sec_rows],
        )
        db.conn.executemany(
            "INSERT INTO paragraphs (id, document_id, section_id, ord, kind, asset, device_id, created_at, updated_at,"
            " deleted) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [r + (common["device_id"], t, t, 0) for r in par_rows],
        )
        db.conn.executemany(
            "INSERT INTO sentences (id, document_id, paragraph_id, ord, text, words, density, device_id, created_at,"
            " updated_at, deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [r + (common["device_id"], t, t, 0) for r in sen_rows],
        )
    for c in doc.concepts[:200]:
        db.insert("terms", {"term": c, "document_id": doc_id, "is_concept": 1})
    passages.reindex(db, doc_id)  # the full-text index of its sections
    return {"id": doc_id, "title": doc.title, "warning": doc.warning, "sentences": s_ord, "sections": len(sec_rows)}


def assets_dir(doc_id: str):
    """Pictures cut from a document (PDF display equations): library/assets/<document id>/."""
    return config.library_dir() / "assets" / doc_id


def load_document(db: DB, doc_id: str) -> dict | None:
    d = db.one("SELECT * FROM documents WHERE id=? AND deleted=0", (doc_id,))
    if not d:
        return None
    sections = db.all("SELECT * FROM sections WHERE document_id=? AND deleted=0 ORDER BY ord", (doc_id,))
    paragraphs = db.all(
        "SELECT id, section_id, ord, kind, asset FROM paragraphs WHERE document_id=? AND deleted=0 ORDER BY ord",
        (doc_id,),
    )
    sentences = db.all(
        "SELECT ord, paragraph_id, text, words, density, personal, read_at IS NOT NULL AS read FROM sentences"
        " WHERE document_id=? AND deleted=0 ORDER BY ord",
        (doc_id,),
    )
    by_par: dict[str, list] = {}
    for s in sentences:
        by_par.setdefault(s.pop("paragraph_id"), []).append(s)
    by_sec: dict[str, list] = {}
    for p in paragraphs:
        p["sentences"] = by_par.get(p["id"], [])
        if not p["asset"]:
            p.pop("asset")
        by_sec.setdefault(p.pop("section_id"), []).append(p)
    for sec in sections:
        sec["paragraphs"] = by_sec.get(sec["id"], [])
        for k in ("device_id", "created_at", "updated_at", "deleted", "document_id"):
            sec.pop(k, None)
    d["sections"] = [s for s in sections if s["paragraphs"]]
    return d


def doc_sentences(db: DB, doc_id: str) -> list[tuple[int, str]]:
    return [
        (r["ord"], r["text"])
        for r in db.all(
            "SELECT s.ord, s.text FROM sentences s JOIN paragraphs p ON p.id = s.paragraph_id"
            " WHERE s.document_id=? AND s.deleted=0 AND p.kind IN ('text','list','caption') ORDER BY s.ord",
            (doc_id,),
        )
    ]


def key_sentence_stats(db: DB, doc_id: str) -> dict:
    """Key sentences = paced text outside background/hidden sections."""
    row = db.one(
        "SELECT COUNT(*) AS total, SUM(s.read_at IS NOT NULL) AS read FROM sentences s"
        " JOIN paragraphs p ON p.id=s.paragraph_id JOIN sections c ON c.id=p.section_id"
        " WHERE s.document_id=? AND s.deleted=0 AND p.deleted=0 AND c.deleted=0 AND p.kind IN ('text','list')"
        " AND c.background=0 AND c.hidden=0",
        (doc_id,),
    )
    total = row["total"] or 0
    read = row["read"] or 0
    return {"total": total, "read": read, "ratio": (read / total) if total else 0.0}
