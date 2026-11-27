"""Notes: your own pages, linked with [[double brackets]].

- A page is a title and a plain-text body (a small Markdown: headings, lists, check boxes, bold, code).
- `[[Another page]]` links to a page by its title. The page does not have to exist yet: following the link
  makes it. A link whose title matches a library document, a lecture or notebook, a quest or a glossary term
  opens that.
- Every page shows what links to it (backlinks) and where its title is mentioned without a link.
- Renaming a page rewrites the links that point to it, so nothing breaks.
- One daily note per day, made on first open.

Bodies are stored as plain text and drawn with text nodes only (see `web/src/views/notes.ts`).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .bodies import Body
from .db import DB

ID = re.compile(r"[0-9a-f]{32}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
LINK = re.compile(r"\[\[([^\[\]\n|]{1,200})(?:\|([^\[\]\n]{0,200}))?\]\]")
TAG = re.compile(r"(?<![\w&#/])#([^\W\d_][\w-]{0,39})")  # a tag starts with a letter of any alphabet
FENCE = re.compile(r"```.*?```", re.S)
ANCHOR = re.compile(r"\s*#s\d{1,6}\s*$")
PROP = re.compile(r"^([A-Za-z][\w \-]{0,30})::[ \t]*(\S.*)$", re.M)
MAX_PROPS = 12
MAX_BODY = 200_000
COLS = "id, title, body, tags, pinned, daily, created_at, updated_at"
DAILY_BODY = "## Today\n- [ ] \n\n## Notes\n\n\n## One good thing\n"


def key(title: str) -> str:
    return " ".join(title.split()).casefold()


def _check_id(value: str) -> str:
    if not ID.fullmatch(value or ""):
        raise HTTPException(404, "not found")
    return value


def links_in(body: str) -> list[str]:
    """The titles a body links to (as keys), each once, in order. `[[Title#s12]]` points at sentence 12 of a document."""
    out: list[str] = []
    for m in LINK.finditer(FENCE.sub("", body)):
        k = key(ANCHOR.sub("", m.group(1)))
        if k and k not in out:
            out.append(k)
    return out


def props_in(body: str) -> dict[str, str]:
    """`key:: value` lines are the properties of a note (status:: reading, course:: Linear algebra)."""
    out: dict[str, str] = {}
    for m in PROP.finditer(FENCE.sub("", body)):
        k = " ".join(m.group(1).split()).lower()
        if k not in out and len(out) < MAX_PROPS:
            out[k] = m.group(2).strip()[:200]
    return out


def tags_in(body: str) -> str:
    return " ".join(sorted({m.group(1).lower() for m in TAG.finditer(FENCE.sub("", body))}))


def _snippet(body: str, n: int = 140) -> str:
    text = re.sub(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]", lambda m: m.group(2) or m.group(1), body)
    text = PROP.sub("", text)  # properties are shown as columns, not as the first words of a note
    text = re.sub(r"^[#>\-*\s\[\]x]+", "", text, flags=re.M)
    text = re.sub(r"\*\*|==|`", "", text)
    return " ".join(text.split())[:n]


def _line_with(body: str, target: str) -> str:
    """The line of a body that links to (or mentions) a title, for showing context."""
    for line in body.splitlines():
        low = line.casefold()
        if target in low:
            return line.strip()[:200]
    return ""


class PageIn(Body):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field("", max_length=MAX_BODY)


class OpenIn(Body):
    title: str = Field(..., min_length=1, max_length=200)


class PagePatch(Body):
    title: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = Field(None, max_length=MAX_BODY)
    pinned: bool | None = None


class MentionIn(BaseModel):
    from_id: str


class CaptureIn(Body):
    text: str = Field(..., min_length=1, max_length=1000)
    day: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")  # the local day whose note gets the line


class QuoteIn(Body):
    text: str = Field(..., min_length=1, max_length=4000)
    document_id: str
    sentence: int = Field(0, ge=0, le=999_999)
    day: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")  # the local day whose note gets the quote


def linkable(title: str) -> bool:
    """A title that can stand inside [[ ]] as it is."""
    title = " ".join(title.split())
    return bool(title) and len(title) <= 190 and not re.search(r"[\[\]|#\n]", title)


def link_first_mention(body: str, title: str) -> str | None:
    """The body with the first plain mention of a title turned into a link, or None when there is none."""
    words = r"\s+".join(re.escape(w) for w in title.split())
    pattern = re.compile(r"(?<![\w\[])" + words + r"(?![\w\]])", re.I)
    out: list[str] = []
    last = 0
    done = False
    for m in LINK.finditer(body):  # look only outside the links that are already there
        chunk = body[last:m.start()]
        if not done:
            chunk, n = pattern.subn(lambda _: f"[[{title}]]", chunk, count=1)
            done = n > 0
        out += [chunk, m.group(0)]
        last = m.end()
    tail = body[last:]
    if not done:
        tail, n = pattern.subn(lambda _: f"[[{title}]]", tail, count=1)
        done = n > 0
    return "".join(out) + tail if done else None


def relink(db: DB, page_id: str, body: str) -> None:
    """Keep page_links in step with the body: only what changed is written."""
    want = links_in(body)
    have = {r["target"]: r["id"] for r in db.all("SELECT id, target FROM page_links WHERE from_id=? AND deleted=0", (page_id,))}
    for target, link_id in have.items():
        if target not in want:
            db.soft_delete("page_links", link_id)
    for target in want:
        if target not in have:
            db.insert("page_links", {"from_id": page_id, "target": target})


def find(db: DB, title: str) -> dict | None:
    return db.one(f"SELECT {COLS} FROM pages WHERE title_key=? AND deleted=0 ORDER BY created_at LIMIT 1", (key(title),))


def create(db: DB, title: str, body: str = "", daily: str | None = None) -> dict:
    title = " ".join(title.split())
    if not title:
        raise HTTPException(422, "A note needs a title.")
    if find(db, title):
        raise HTTPException(409, "A note with that title already exists.")
    row = db.insert("pages", {"title": title, "title_key": key(title), "body": body, "tags": tags_in(body), "daily": daily})
    relink(db, row["id"], body)
    return db.one(f"SELECT {COLS} FROM pages WHERE id=?", (row["id"],))


def resolve(db: DB, target: str) -> dict:
    """What a link's title points to: a note first, then a document, a lecture or notebook, a quest."""
    page = db.one("SELECT id, title FROM pages WHERE title_key=? AND deleted=0 ORDER BY created_at LIMIT 1", (target,))
    if page:
        return {"kind": "page", **page}
    for kind, table in (("document", "documents"), ("lecture", "lectures"), ("quest", "quests")):
        row = db.one(f"SELECT id, title FROM {table} WHERE deleted=0 AND lower(title)=? LIMIT 1", (target,))
        if row:
            return {"kind": kind, **row}
    term = db.one("SELECT id, term AS title FROM terms WHERE deleted=0 AND lower(term)=? LIMIT 1", (target,))
    if term:  # a word from your glossary: the link opens its concept page
        return {"kind": "term", **term}
    return {"kind": "missing", "id": None, "title": target}


def detail(db: DB, page: dict) -> dict:
    """A page with everything around it: where its links go, what links here, and unlinked mentions."""
    me = key(page["title"])
    outgoing = [{**resolve(db, t), "key": t} for t in links_in(page["body"])]
    written: dict[str, str] = {}  # the title as you typed it, for links that point at nothing yet
    for m in LINK.finditer(FENCE.sub("", page["body"])):
        raw = " ".join(ANCHOR.sub("", m.group(1)).split())
        written.setdefault(key(raw), raw)
    for o in outgoing:
        if o["kind"] == "missing":
            o["title"] = written.get(o["key"], o["title"])
    back_rows = db.all(
        f"SELECT p.id, p.title, p.body FROM page_links l JOIN pages p ON p.id=l.from_id"
        " WHERE l.target=? AND l.deleted=0 AND p.deleted=0 AND p.id!=? ORDER BY p.updated_at DESC LIMIT 100", (me, page["id"]))
    backlinks = [{"id": r["id"], "title": r["title"], "context": _line_with(r["body"], f"[[{me}")} for r in back_rows]
    linked = {r["id"] for r in back_rows}
    mentions = []
    if len(me) >= 3:
        like = "%" + me.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for r in db.all("SELECT id, title, body FROM pages WHERE deleted=0 AND id!=? AND lower(body) LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT 30", (page["id"], like)):
            if r["id"] not in linked and me in LINK.sub("", r["body"]).casefold():
                mentions.append({"id": r["id"], "title": r["title"], "context": _line_with(LINK.sub("", r["body"]), me)})
    # the small map: this page, the notes it links to, and the notes that link here
    nodes = {page["id"]: page["title"]}
    edges: list[list[str]] = []
    for o in outgoing:
        if o["kind"] == "page" and o["id"] != page["id"]:
            nodes[o["id"]] = o["title"]
            edges.append([page["id"], o["id"]])
    for b in backlinks:
        nodes[b["id"]] = b["title"]
        edges.append([b["id"], page["id"]])
    return {**page, "outgoing": outgoing, "backlinks": backlinks, "mentions": mentions[:10],
            "graph": {"nodes": [{"id": i, "title": t} for i, t in nodes.items()], "edges": edges}}


def register(app: FastAPI, db: DB) -> None:
    def page(pid: str) -> dict:
        row = db.one(f"SELECT {COLS} FROM pages WHERE id=? AND deleted=0", (_check_id(pid),))
        if not row:
            raise HTTPException(404, "not found")
        return row

    @app.get("/api/pages")
    def api_pages(q: str = "", tag: str = ""):
        """The list for the sidebar: pinned first, then the most recently changed."""
        sql = f"SELECT {COLS} FROM pages WHERE deleted=0"
        params: list = []
        if q.strip():
            like = "%" + q.strip().casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += " AND (title_key LIKE ? ESCAPE '\\' OR lower(body) LIKE ? ESCAPE '\\')"
            params += [like, like]
        rows = db.all(sql + " ORDER BY pinned DESC, updated_at DESC LIMIT 500", params)
        if tag.strip():
            want = tag.strip().lower().lstrip("#")
            rows = [r for r in rows if want in r["tags"].split()]
        tags: dict[str, int] = {}
        for r in db.all("SELECT tags FROM pages WHERE deleted=0 AND tags!=''"):
            for t in r["tags"].split():
                tags[t] = tags.get(t, 0) + 1
        return {
            "pages": [{"id": r["id"], "title": r["title"], "tags": r["tags"], "pinned": r["pinned"], "daily": r["daily"],
                       "updated_at": r["updated_at"], "created_at": r["created_at"], "snippet": _snippet(r["body"]), "props": props_in(r["body"])} for r in rows],
            "tags": [{"tag": t, "n": n} for t, n in sorted(tags.items(), key=lambda x: (-x[1], x[0]))[:40]],
            "total": db.scalar("SELECT COUNT(*) FROM pages WHERE deleted=0"),
            "links": db.scalar("SELECT COUNT(*) FROM page_links WHERE deleted=0"),
        }

    @app.get("/api/pages/titles")
    def api_page_titles():
        """Everything a [[link]] can point to: your notes, then documents, lectures and notebooks, quests."""
        others = []
        for kind, table in (("document", "documents"), ("lecture", "lectures"), ("quest", "quests")):
            others += [{"kind": kind, **r} for r in db.all(f"SELECT id, title FROM {table} WHERE deleted=0 ORDER BY updated_at DESC LIMIT 100")]
        seen: set[str] = set()
        for r in db.all("SELECT id, term AS title FROM terms WHERE deleted=0 ORDER BY updated_at DESC LIMIT 300"):
            if r["title"].lower() not in seen:
                seen.add(r["title"].lower())
                others.append({"kind": "term", **r})
        return {"pages": db.all("SELECT id, title FROM pages WHERE deleted=0 ORDER BY updated_at DESC LIMIT 1000"), "others": others}

    @app.post("/api/pages")
    def api_page_create(body: PageIn):
        return detail(db, create(db, body.title, body.body))

    @app.post("/api/pages/open")
    def api_page_open(body: OpenIn):
        """Follow a link: the note with this title, made now if it does not exist."""
        return detail(db, find(db, body.title) or create(db, body.title))

    @app.get("/api/pages/daily/{day}")
    def api_page_daily(day: str):
        if not DAY.fullmatch(day):
            raise HTTPException(404, "not found")
        try:
            dt.date.fromisoformat(day)
        except ValueError:
            raise HTTPException(404, "not found") from None
        row = db.one(f"SELECT {COLS} FROM pages WHERE daily=? AND deleted=0 ORDER BY created_at LIMIT 1", (day,))
        return detail(db, row or find(db, day) or create(db, day, DAILY_BODY, daily=day))

    @app.get("/api/pages/graph")
    def api_page_graph():
        """Every note and the links between notes, for the big map."""
        rows = db.all("SELECT id, title, title_key, tags, daily FROM pages WHERE deleted=0 ORDER BY updated_at DESC LIMIT 400")
        by_key = {r["title_key"]: r["id"] for r in reversed(rows)}
        ids = {r["id"] for r in rows}
        edges: list[list[str]] = []
        for link in db.all("SELECT from_id, target FROM page_links WHERE deleted=0"):
            to = by_key.get(link["target"])
            if to and link["from_id"] in ids and to != link["from_id"]:
                edges.append([link["from_id"], to])
        return {"nodes": [{"id": r["id"], "title": r["title"], "tags": r["tags"], "daily": r["daily"]} for r in rows], "edges": edges,
                "total": db.scalar("SELECT COUNT(*) FROM pages WHERE deleted=0")}

    @app.post("/api/pages/quote")
    def api_page_quote(body: QuoteIn):
        """Put a passage from a document at the end of a day's note, with a link back to the sentence."""
        try:
            dt.date.fromisoformat(body.day)
        except ValueError:
            raise HTTPException(422, "not a day") from None
        doc = db.one("SELECT id, title FROM documents WHERE id=? AND deleted=0", (_check_id(body.document_id),))
        if not doc:
            raise HTTPException(404, "not found")
        note = db.one(f"SELECT {COLS} FROM pages WHERE daily=? AND deleted=0 ORDER BY created_at LIMIT 1", (body.day,)) or find(db, body.day) \
            or create(db, body.day, DAILY_BODY, daily=body.day)
        text = " ".join(body.text.split())
        title = " ".join(doc["title"].split())
        source = f"[[{title}#s{body.sentence}|{title}]]" if title and not re.search(r"[\[\]|#]", title) and len(title) <= 190 else title
        new_body = f"{note['body'].rstrip()}\n\n> {text}\n> — {source}\n"
        if len(new_body) > MAX_BODY:
            raise HTTPException(409, "Today's note is full. Start a new note for more quotes.")
        db.update("pages", note["id"], {"body": new_body, "tags": tags_in(new_body)})
        relink(db, note["id"], new_body)
        return {"id": note["id"], "title": note["title"]}

    @app.post("/api/pages/capture")
    def api_page_capture(body: CaptureIn):
        """One quick line into a day's note, under its "## Notes" heading when it has one."""
        try:
            dt.date.fromisoformat(body.day)
        except ValueError:
            raise HTTPException(422, "not a day") from None
        note = db.one(f"SELECT {COLS} FROM pages WHERE daily=? AND deleted=0 ORDER BY created_at LIMIT 1", (body.day,)) or find(db, body.day) \
            or create(db, body.day, DAILY_BODY, daily=body.day)
        line = "- " + " ".join(body.text.split())
        lines = note["body"].split("\n")
        at = next((i for i, l in enumerate(lines) if l.strip().lower() == "## notes"), None)
        if at is None:
            new_body = f"{note['body'].rstrip()}\n{line}\n" if note["body"].strip() else f"{line}\n"
        else:
            end = next((j for j in range(at + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
            while end > at + 1 and not lines[end - 1].strip():
                end -= 1  # after the last line already under the heading
            lines[end:end] = [line]
            rest = end + 1
            while rest < len(lines) and not lines[rest].strip():
                del lines[rest]  # exactly one empty line before what comes next
            if rest < len(lines):
                lines[rest:rest] = [""]
            new_body = "\n".join(lines)
        if len(new_body) > MAX_BODY:
            raise HTTPException(409, "Today's note is full. Start a new note.")
        db.update("pages", note["id"], {"body": new_body, "tags": tags_in(new_body)})
        relink(db, note["id"], new_body)
        return {"id": note["id"], "title": note["title"]}

    @app.get("/api/pages/{pid}")
    def api_page(pid: str):
        return detail(db, page(pid))

    @app.patch("/api/pages/{pid}")
    def api_page_patch(pid: str, body: PagePatch):
        old = page(pid)
        fields: dict = {}
        if body.title is not None:
            title = " ".join(body.title.split())
            if not title:
                raise HTTPException(422, "A note needs a title.")
            if key(title) != key(old["title"]):
                if find(db, title):
                    raise HTTPException(409, "A note with that title already exists.")
                # the links that pointed to the old title now point to the new one
                old_key = key(old["title"])
                pattern = re.compile(r"\[\[\s*" + r"\s+".join(re.escape(w) for w in old["title"].split()) + r"\s*(\|[^\[\]\n]*)?\]\]", re.I)
                for src in db.all("SELECT p.id, p.body FROM page_links l JOIN pages p ON p.id=l.from_id WHERE l.target=? AND l.deleted=0 AND p.deleted=0", (old_key,)):
                    new_body = pattern.sub(lambda m: f"[[{title}{m.group(1) or ''}]]", src["body"])
                    if new_body != src["body"]:
                        if src["id"] == pid and body.body is None:
                            fields["body"] = new_body
                        elif src["id"] != pid:
                            db.update("pages", src["id"], {"body": new_body})
                            relink(db, src["id"], new_body)
            if title != old["title"]:
                fields.update({"title": title, "title_key": key(title)})
        if body.body is not None:
            fields["body"] = body.body
        if "body" in fields:
            fields["tags"] = tags_in(fields["body"])
        if body.pinned is not None:
            fields["pinned"] = int(body.pinned)
        if fields:
            db.update("pages", pid, fields)
            if "body" in fields:
                relink(db, pid, fields["body"])
        return detail(db, page(pid))

    @app.delete("/api/pages/{pid}")
    def api_page_delete(pid: str):
        page(pid)
        db.soft_delete("pages", pid)
        # what a model wrote about this note (a brainstorm) goes out of sight with it; nothing of yours is touched
        db.execute("UPDATE ai_results SET deleted=1 WHERE target_id=? AND deleted=0", (pid,))
        return {"ok": True}

    @app.post("/api/pages/{pid}/restore")
    def api_page_restore(pid: str):
        row = db.one("SELECT title FROM pages WHERE id=?", (_check_id(pid),))
        if not row:
            raise HTTPException(404, "not found")
        if find(db, row["title"]):
            raise HTTPException(409, "A note with that title exists now. Rename it first.")
        db.update("pages", pid, {"deleted": 0})
        return detail(db, page(pid))

    @app.post("/api/pages/{pid}/link-mention")
    def api_link_mention(pid: str, body: MentionIn):
        """Turn the first plain mention of this page's title in another note into a real link."""
        target = page(pid)
        src = page(body.from_id)
        new_body = link_first_mention(src["body"], target["title"])
        if new_body is None:
            raise HTTPException(409, "That note no longer mentions this title.")
        db.update("pages", src["id"], {"body": new_body, "tags": tags_in(new_body)})
        relink(db, src["id"], new_body)
        return detail(db, page(pid))
