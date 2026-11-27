"""'Why did it say this?' (milestone 4.2 of docs/ai/PLAN.md, section 6.8): any AI result traced to its prompt and sources.

For a result Readhold kept (`ai_results`), this gathers, without calling a model:
- what the result recorded: the feature, when, the provider and model, the prompt version, its status;
- every model call behind it, from the AI log: task, model, prompt version, time, tokens, retries, outcome and the
  checks the guards ran (fenced, cut, left out, flagged text, links removed, secrets redacted). A brainstorm has its
  samples and the critic; Ask my library has each step; a digest has the call of each part and the final one;
- the sources each call was sent, named: a document's title, section and sentence, your note or idea, "the tags you
  use" and so on. Only where each came from, its trust and how much of it was sent: never its text again;
- the text of each prompt version used, word for word (prompts are plain files: `prompts/<name>_vN.md`);
- how many of the result's quotes were checked, and how many were not.

The AI log keeps 1, 7 or 30 days (Settings → AI); when a call's row is gone, the result says so and shows what it recorded itself.
Reading this never sends anything anywhere, so it also works with AI switched off. A result that was cleared
(Clear AI history) or whose document or note was removed is not found.
"""
from __future__ import annotations

import json
import re

from fastapi import FastAPI, HTTPException

from ..db import DB
from . import prompts

ID = re.compile(r"[0-9a-f]{32}")
DOC = re.compile(r"([0-9a-f]{32}):(\d{1,7})")
KIND = re.compile(r"([a-z]{1,12}):([0-9a-f]{32})(?::(\d{1,7}))?")
MAX_CALLS = 60
# no input_preview: the panel names the sources instead, and never repeats what they said
CALL_COLUMNS = "id, task, provider, model, prompt_version, latency_ms, tokens_in, tokens_out, attempts, checks, outcome, error, output_preview, created_at"
YOURS = {"attempt": "your own attempt, written before the explanation", "session": "what you read and wrote in that session",
         "why": "why you said you read this document"}


def _prompt_text(version: str) -> str | None:
    """The words of one prompt version, from its file; None for a version that is not on this computer (any more)."""
    m = prompts.FILE.fullmatch(f"{version}.md")
    path = prompts.FOLDER / f"{version}.md"
    return path.read_text("utf-8").strip() if m and path.is_file() else None


def _source(db: DB, s: dict) -> dict:
    """One source of a call, named. What it said is not repeated: only where it is."""
    out = {"anchor": s.get("anchor", ""), "trust": s.get("trust", ""), "chars": s.get("chars", 0), "cut": bool(s.get("cut")), "kind": "other", "title": ""}
    a = out["anchor"]
    if m := DOC.fullmatch(a):
        row = db.one("SELECT d.title AS document, c.title AS section FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id AND p.deleted=0"
                     " JOIN sections c ON c.id=p.section_id AND c.deleted=0 JOIN documents d ON d.id=s.document_id"
                     " WHERE s.document_id=? AND s.ord=? AND s.deleted=0 AND d.deleted=0", (m.group(1), int(m.group(2))))
        if row:
            out.update(kind="document", document_id=m.group(1), sentence=int(m.group(2)), document_title=row["document"], section_title=row["section"], title=row["document"])
        else:
            out.update(kind="gone", title="a passage that is no longer in your library")
        return out
    m = KIND.fullmatch(a)
    if not m:
        out.update(kind="gone" if a == "unknown" else "other", title="a source with no place in your library")
        return out
    kind, rid, ord_ = m.groups()
    if kind == "note":
        row = db.one("SELECT title FROM pages WHERE id=? AND deleted=0", (rid,))
        out.update(**({"kind": "note", "note_id": rid, "title": row["title"]} if row else {"kind": "gone", "title": "a note that is no longer in your notes"}))
    elif kind == "idea":
        row = db.one("SELECT substr(text, 1, 80) AS t FROM ideas WHERE id=? AND deleted=0", (rid,))  # filed under a note, or removed
        out.update(**({"kind": "idea", "idea_id": rid, "title": " ".join(row["t"].split())} if row else {"kind": "gone", "title": "an idea that is no longer in the inbox"}))
    elif kind == "hlnote" and ord_ is not None:
        doc = db.scalar("SELECT title FROM documents WHERE id=? AND deleted=0", (rid,))
        out.update(**({"kind": "hlnote", "document_id": rid, "sentence": int(ord_), "title": f"your note on a highlight in {doc}"} if doc
                      else {"kind": "gone", "title": "your note on a highlight in a document you removed"}))
    elif kind in YOURS:
        out.update(kind=kind, title=YOURS[kind])
    elif kind == "tags":
        out.update(kind="tags", title="the tags you use")
    elif kind == "docs":
        out.update(kind="titles", title="document titles (and deadlines)")
    elif kind == "task":
        row = db.one("SELECT text FROM todos WHERE id=?", (rid,))
        out.update(kind="task", title=row["text"] if row else "a task that is no longer on Plan")
    elif kind == "routine":
        row = db.one("SELECT title FROM routines WHERE id=?", (rid,))
        out.update(kind="routine", title=f"your routine “{row['title']}”" if row else "a routine that is no longer there")
    elif kind == "days":
        out.update(kind="days", title="your next days and their free minutes")
    elif kind == "turn":
        out.update(kind="turn", title="an earlier message in the chat")
    elif kind == "ideas":
        out.update(kind="model", title="the ideas the first calls wrote (the model's own text)")
    else:
        out.update(kind=kind, title=kind)
    return out


def _checked(value, counts: dict) -> None:
    """Count the quotes in a result: every part with a "verified" mark, checked or not."""
    if isinstance(value, dict):
        if isinstance(value.get("verified"), bool):
            counts["verified" if value["verified"] else "unchecked"] += 1
        for v in value.values():
            _checked(v, counts)
    elif isinstance(value, list):
        for v in value:
            _checked(v, counts)


def explain(db: DB, result_id: str) -> dict:
    row = db.one("SELECT * FROM ai_results WHERE id=? AND deleted=0", (result_id,)) if ID.fullmatch(result_id or "") else None
    if not row:
        raise HTTPException(404, "not found")
    try:
        payload = json.loads(row["payload"])
    except ValueError:
        payload = {}
    ids = [i for i in (payload.get("log_ids") or []) if isinstance(i, str)] or ([row["log_id"]] if row["log_id"] else [])
    if row["feature"] == "digest" and not payload.get("log_ids"):  # a digest from before 4.2 did not list its part calls
        parts = db.all("SELECT log_id FROM ai_results WHERE feature='digest_map' AND target_id=? AND deleted=0 AND created_at<=? ORDER BY created_at",
                       (row["target_id"], row["created_at"]))
        ids = [p["log_id"] for p in parts if p["log_id"]] + ids
    ids = list(dict.fromkeys(ids))[-MAX_CALLS:]
    found = {r["id"]: r for r in db.all(f"SELECT {CALL_COLUMNS} FROM ai_log WHERE deleted=0 AND id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    calls = []
    for i in ids:
        r = found.get(i)
        if not r:
            continue
        try:
            checks = json.loads(r["checks"] or "{}")
        except ValueError:
            checks = {}
        recorded = isinstance(checks, dict) and isinstance(checks.get("sources"), list)  # calls made before 4.2 did not keep it
        listed = checks.pop("sources") if recorded else []
        calls.append({**{k: r[k] for k in r if k != "checks"}, "checks": checks if isinstance(checks, dict) else {},
                      "sources_recorded": recorded, "sources": [_source(db, s) for s in listed if isinstance(s, dict)]})
    versions = list(dict.fromkeys([row["prompt_version"]] + [c["prompt_version"] for c in calls]))
    counts = {"verified": 0, "unchecked": 0}
    _checked(payload, counts)
    return {"id": row["id"], "feature": row["feature"], "created_at": row["created_at"], "provider": row["provider"], "model": row["model"],
            "prompt_version": row["prompt_version"], "status": payload.get("status", ""), "checked": counts,
            "calls": calls, "log_gone": bool(ids) and len(calls) < len(ids),
            "prompts": {v: t for v in versions if v and (t := _prompt_text(v)) is not None}}


def register(app: FastAPI, db: DB) -> None:
    @app.get("/api/ai/why/{result_id}")
    def api_why(result_id: str):
        """Reads the AI log and the prompt files. Calls no model; works with AI switched off."""
        return explain(db, result_id)
