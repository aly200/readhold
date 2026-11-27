"""Note chat (milestone 5.4 of docs/ai/PLAN.md): tell a model what to do with the note you are in.

Asked for on 2026-11-26: a chat box in a note, for "make this note more formatted", "enhance it" or "write an idea
about a story". The same rules as Plan chat (5.3): you type, the model answers with a short reply and one proposal,
and nothing changes until you press a button on the page, with Undo. The proposal is one of:

- `replace`: the whole note rewritten. Checked like Tidy's note (`tidy._note`): your [[links]], #tags and properties
  are kept (put back at the end if the model dropped them), links, tags, images and web links the model added are
  plain text, every word you did not write is listed, and a much shorter rewrite names what went missing;
- `add`: new text to put at the end of the note (a story idea, a summary, a list). Its markup is plain text too;
- `none`: only a reply (a question back, or an answer that was not usable: an unknown action, an empty rewrite).

The note is your own text (trust "yours", the main item: a private note is never sent off this computer), the earlier
turns go as sources (the model's own replies marked as its text), and your newest message is the fenced question,
checked for copies of private text when the call leaves this computer. No label line is put into your note.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..db import DB
from . import guard, privacy, prompts, results
from .port import AIError, AIOff, Port
from .resume import status_error
from .tidy import MAX_NOTE, LongText, _note

FEATURE = "notechat"
ID = re.compile(r"[0-9a-f]{32}")
MAX_TURNS = 12
ACTIONS = ("replace", "add", "none")


class NoteChatOut(BaseModel):
    reply: guard.LooseText = ""
    action: guard.LooseText = ""
    text: LongText = ""


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


def _anchor(i: int) -> str:
    return f"turn:{hashlib.md5(str(i).encode()).hexdigest()}"  # noqa: S324  (a name for a fence, not a secret)


def _sources(db: DB, row: dict, turns: list[dict], away: bool) -> list[guard.Source]:
    note = guard.Source(f"note:{row['id']}", f"(The note you are in: {row['title'][:200]})\n{row['body'] or '(empty so far)'}", "yours")
    note.main = True  # if it is private, a call that leaves this computer is refused
    out = [note]
    for i, t in enumerate(turns[:-1]):  # the conversation so far; the newest message goes as the question
        mine = t["who"] == "you"
        if not mine and away and privacy.copies_private(db, t["text"]):
            continue  # an earlier reply (from a model on this computer) that copies private text never leaves it
        out.append(guard.Source(_anchor(i), f"({'You said' if mine else 'The model said'})\n{t['text']}", "yours" if mine else "model"))
    return out


def _proposal(raw: dict, data: dict, row: dict) -> dict:
    """The model's proposal, checked. Read from the uncleaned answer, so your own links can be told from the model's."""
    action = str(data.get("action") or "").strip().lower()
    text = raw.get("text") if isinstance(raw.get("text"), str) else data.get("text") or ""
    empty = {"action": "none", "text": "", "new_words": [], "restored": [], "missing_words": [], "shorter": False}
    if action not in ("replace", "add") or not text.strip():
        return empty
    if action == "replace":
        checked = _note({"body": text}, {"title": row["title"], "body": row["body"]})
        return {**empty, "action": "replace", "text": checked["body"], "new_words": checked["new_words"], "restored": checked["restored"],
                "missing_words": checked["missing_words"], "shorter": checked["shorter"]} if checked["body"].strip() else empty
    added = _note({"body": text}, {"title": "", "body": ""})  # nothing of yours to keep: all its markup is plain text
    return {**empty, "action": "add", "text": added["body"]} if added["body"].strip() else empty


def answer(port: Port, db: DB, page_id: str, turns: list[dict]) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    row = db.one("SELECT id, title, body FROM pages WHERE id=? AND deleted=0", (page_id,)) if ID.fullmatch(page_id or "") else None
    if not row:
        raise NotFound()
    if len(row["body"]) > MAX_NOTE:
        raise Invalid(f"This note is too long to send at once (over {MAX_NOTE:,} characters). Split it into two notes.")
    question = guard.user_text(turns[-1]["text"], "ask")
    away = guard.leaves(port)
    if away and privacy.copies_private(db, question):
        raise guard.Blocked("Your message copies text from a private document (#private), so it is not sent off this computer. "
                            "Say it in your own words, or use a model on this computer.")
    sources = _sources(db, row, turns, away)
    prompt = prompts.load(FEATURE)
    key = results.key(prompt.hash, dt.date.today().isoformat(), question, *(f"{s.anchor}\n{s.text}" for s in sources))
    with results.once(FEATURE, key):
        kept = results.find(db, FEATURE, row["id"], key)
        if kept:
            return kept
        r = guard.ask(port, db, FEATURE, prompt.text, sources, budget=FEATURE, question=question, schema=NoteChatOut, prompt_version=prompt.version)
        raw = r.raw if isinstance(r.raw, dict) else {}
        payload = {"page_id": row["id"], "question": question, "original": row["body"], "reply": guard.safe_output(r.data.get("reply") or "", 800).text,
                   **_proposal(raw, r.data, row), "links": list(dict.fromkeys(r.links)), "warning": r.warning}
        return results.keep(db, FEATURE, row["id"], key, payload, prompt.version, r.log_id, target_type="page")


# ------------------------------------------------------------------ routes
class Turn(BaseModel):
    who: Literal["you", "model"]
    text: str = Field(max_length=4000)


class NoteChatIn(BaseModel):
    messages: list[Turn] = Field(min_length=1, max_length=MAX_TURNS)


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/notes/{page_id}/chat")
    def api_note_chat(page_id: str, body: NoteChatIn):
        """A plain `def`: the call runs on a worker thread. Nothing is changed: the page applies what you choose."""
        if body.messages[-1].who != "you":
            raise HTTPException(422, "The last message must be yours.")
        try:
            return {"result": answer(port, db, page_id, [m.model_dump() for m in body.messages])}
        except NotFound:
            raise HTTPException(404, "not found") from None
        except (Invalid, guard.Blocked) as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None
