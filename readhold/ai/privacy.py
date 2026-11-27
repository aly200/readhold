"""Privacy controls (milestone 4.4 of docs/ai/PLAN.md, section 6.4): what never leaves this computer, and the preview.

Private items. A document or a note tagged #private is never sent to a cloud model (on a document the tag is also its
collection, so tagging a collection's documents makes them private); an idea is private when it says #private or
comes from a private document. With the setting `ai_cloud_only_tagged`, it is the other way round: only documents and
notes tagged #cloud may go (per-scope consent), and everything else stays here.

Privacy follows the text, not only the tag: one of your own sources (a note, an idea, your attempt...) that copies
a private document's sentences word for word, or names its title, is withheld too: a quote put into today's note, a
"Study notes" page, a brainstorm sheet. `withheld` is asked about every source of a cloud call, in `guard.pack` and
in the library's search, which leaves such sources out and counts them; a call about a private item (`Source.main`),
or one with nothing left, is refused with a sentence that says why. A local model still reads everything: nothing
leaves the computer.

The send preview ("Show what will be sent", `ai_preview`, cloud mode only). The first cloud call of a request stops
with `PreviewNeeded`; the page shows the exact text and a one-time token. The same request, sent again with
`X-AI-Approve: <token>`, runs that call (same text, by its hash), and the calls after it while they send only the
items you have seen (documents, notes, ideas). A later call that would send another item stops again and shows its
text; its token approves all the items seen so far. A token is used once and lasts `GRANT_SECONDS`. The approval
lives in a context variable of that one request (set by the server's middleware).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import secrets
import threading
import time

from .. import pages
from ..db import DB

PRIVATE_TAG = "private"
CLOUD_TAG = "cloud"
MESSAGE = ("This is marked private (#private), so it is never sent off this computer (to a cloud model, or to a model "
           "server on another computer). Use a model on this computer for it, or remove the tag.")
MESSAGE_TAGGED = ("Only documents and notes tagged #cloud are sent to a cloud model (Settings → AI), and this is not. "
                  "Tag it #cloud, or use a local model.")
GRANT_SECONDS = 600
MAX_GRANTS = 100
SHINGLE = 8  # words: a run of this many words of a private document, found in your own text, counts as a copy
SHORT = 4  # words: a whole private sentence shorter than SHINGLE, but this long, found in your text, counts too
MIN_TITLE = 8  # characters: a private document's title this long, named in your own text, counts as a copy
DOC = re.compile(r"([0-9a-f]{32}):\d{1,7}")
KIND = re.compile(r"([a-z]{1,12}):([0-9a-f]{32})(?::\d{1,7})?")
ABOUT_DOCUMENT = {"attempt", "why", "tags", "docs", "hlnote"}  # sources named by the document they are about


def _setting(db: DB, key: str, default):
    try:
        value = json.loads(db.scalar("SELECT value FROM settings WHERE key=?", (key,)) or "null")
    except ValueError:
        value = None
    return default if value is None else value


def only_tagged(db: DB) -> bool:
    return _setting(db, "ai_cloud_only_tagged", False) is True


def _keeps_here(tags: str | None, strict: bool) -> bool:
    """Do these tags keep an item on this computer? #private always; with the opt-in setting, anything but #cloud."""
    words = (tags or "").split()
    return PRIVATE_TAG in words or (strict and CLOUD_TAG not in words)


def document_private(db: DB, doc_id: str, strict: bool | None = None) -> bool:
    strict = only_tagged(db) if strict is None else strict
    return _keeps_here(db.scalar("SELECT tags FROM documents WHERE id=?", (doc_id,)), strict)


def owner(db: DB, anchor: str) -> tuple[str, str] | None:
    """The item a source belongs to: ("document", id), ("note", id), ("idea", id), ("session", id); None for text that
    is nobody's item (a model's own words)."""
    if m := DOC.fullmatch(anchor):
        return "document", m.group(1)
    m = KIND.fullmatch(anchor)
    if not m:
        return None
    kind, rid = m.groups()
    if kind in ABOUT_DOCUMENT:
        return "document", rid
    if kind in ("note", "idea", "session"):
        return kind, rid
    if kind == "task":  # a task that opens a document belongs to that document (its title may name it)
        row = db.one("SELECT link_type, link_id FROM todos WHERE id=?", (rid,))
        if row and row["link_type"] == "document" and row["link_id"]:
            return "document", row["link_id"]
    return None


def is_private(db: DB, anchor: str, strict: bool | None = None) -> bool:
    """Is the item behind this anchor kept on this computer by its tags (or its document's)?"""
    strict = only_tagged(db) if strict is None else strict
    item = owner(db, anchor)
    if item is None:
        return False
    kind, rid = item
    if kind == "document":
        return document_private(db, rid, strict)
    if kind == "note":
        return _keeps_here(db.scalar("SELECT tags FROM pages WHERE id=?", (rid,)), strict)
    if kind == "idea":
        row = db.one("SELECT text, document_id FROM ideas WHERE id=?", (rid,))
        if not row:
            return False
        own = " ".join(sorted({m.group(1).lower() for m in pages.TAG.finditer(row["text"])}))
        if PRIVATE_TAG in own.split() or (row["document_id"] and document_private(db, row["document_id"], strict)):
            return True
        return strict and CLOUD_TAG not in own.split()
    if kind == "session":
        doc = db.scalar("SELECT document_id FROM sessions WHERE id=?", (rid,))
        return bool(doc) and document_private(db, doc, strict)
    return False


# ------------------------------------------------------------------ copies of private text in your own writing
_copies: dict[str, tuple[tuple, frozenset, str]] = {}  # doc id -> (stamp, its word runs, its title, plain)
_copies_lock = threading.Lock()


def _plain_words(text: str) -> list[str]:
    from .guard import _plain  # one way of comparing text everywhere (guard imports this module, so lazily)

    return _plain(text).split()


def _private_docs(db: DB, strict: bool) -> list[dict]:
    rows = db.all("SELECT id, title, tags, updated_at FROM documents WHERE deleted=0")
    return [r for r in rows if _keeps_here(r["tags"], strict)]


def _runs_of(db: DB, doc: dict) -> tuple[frozenset, str]:
    stamp = (doc["updated_at"], db.scalar("SELECT COUNT(*) FROM sentences WHERE document_id=? AND deleted=0", (doc["id"],)))
    with _copies_lock:
        hit = _copies.get(doc["id"])
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    runs = set()
    for r in db.all("SELECT text FROM sentences WHERE document_id=? AND deleted=0", (doc["id"],)):
        words = _plain_words(r["text"])
        if SHORT <= len(words) < SHINGLE:
            runs.add(" ".join(words))  # a short sentence: looked for whole
        runs.update(" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))
    title = " ".join(_plain_words(doc["title"]))
    with _copies_lock:
        _copies[doc["id"]] = (stamp, frozenset(runs), title)
    return frozenset(runs), title


def copies_private(db: DB, text: str, strict: bool | None = None) -> bool:
    """Does this text (your note, idea, attempt...) copy a private document's words, or name its title?"""
    strict = only_tagged(db) if strict is None else strict
    docs = _private_docs(db, strict)
    if not docs:
        return False
    words = _plain_words(text)
    mine = {" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}
    flat = f" {' '.join(words)} "
    for d in docs:
        runs, title = _runs_of(db, d)
        short = (r for r in runs if r.count(" ") < SHINGLE - 1)
        if mine & runs or (len(title) >= MIN_TITLE and f" {title} " in flat) or any(f" {r} " in flat for r in short):
            return True
    return False


def withheld(db: DB, anchor: str, text: str, trust: str, strict: bool | None = None) -> bool:
    """Must this source stay on this computer in cloud mode? By its tags, or as a copy of private text."""
    strict = only_tagged(db) if strict is None else strict
    if trust == "model":
        return False  # a model's own words, written from sources that were already filtered
    if is_private(db, anchor, strict):
        return True
    return trust == "yours" and copies_private(db, text, strict)


def refusal(db: DB) -> str:
    return MESSAGE_TAGGED if only_tagged(db) else MESSAGE


# ------------------------------------------------------------------ the send preview
class PreviewNeeded(Exception):
    """Not an AIError on purpose: the routes let it through, and the server answers 428 with the text to show."""

    def __init__(self, token: str, task: str, provider: str, system: str, user: str):
        super().__init__("Approve what will be sent.")
        self.token, self.task, self.provider, self.system, self.user = token, task, provider, system, user

    def view(self) -> dict:
        return {"token": self.token, "task": self.task, "provider": self.provider, "system": self.system, "user": self.user,
                "note": "This is exactly what the next call sends. If the feature makes more calls with the same documents "
                        "and notes (more samples, more parts of this document), your approval covers them; if a later call "
                        "would send another one, you are asked again. Every call is listed afterwards under "
                        "\"Why did it say this?\"."}


_grants: dict[str, dict] = {}
_lock = threading.Lock()
_approved: contextvars.ContextVar[dict | None] = contextvars.ContextVar("readhold_ai_approved", default=None)


def _digest(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\x00{user}".encode("utf-8", "replace")).hexdigest()


def approve(token: str | None) -> None:
    """Called for every request: a valid token (used once) becomes this request's approval."""
    if not token:
        return
    now = time.monotonic()
    with _lock:
        grant = _grants.pop(token, None)
    if grant and grant["expires"] > now:
        _approved.set({"hash": grant["hash"], "items": set(grant["items"]), "open": grant["open"]})


def gate(task: str, provider: str, system: str, user: str, items: set[str]) -> None:
    """Let a cloud call through when this request was approved for it; else stop it and show its text.

    Approved: the call whose exact text was shown (by its hash), and after it, calls that send only items already
    seen. A call that would send another item stops, and its token approves everything seen so far plus it."""
    h = _digest(system, user)
    grant = _approved.get()
    if grant and (grant["hash"] == h or (grant["open"] and items <= grant["items"])):
        grant["open"] = True
        grant["items"] |= items
        return
    token = secrets.token_hex(16)
    now = time.monotonic()
    seen = (grant["items"] if grant and grant["open"] else set()) | items
    with _lock:
        for t in [t for t, g in _grants.items() if g["expires"] <= now]:
            del _grants[t]
        while len(_grants) >= MAX_GRANTS:
            _grants.pop(next(iter(_grants)))
        # asked in the middle of an approved request: the new token covers what was approved before, and this call
        _grants[token] = {"hash": h, "items": seen, "open": bool(grant and grant["open"]), "expires": now + GRANT_SECONDS}
    raise PreviewNeeded(token, task, provider, system, user)
