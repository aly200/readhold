"""Think: step 1 of the agent. No AI model is used here: everything is counted from your own words.

- `similar`: the notes and ideas closest to one of them, by the words they share (TF-IDF). Each result says
  which words it shares, so the reason can be checked.
- Suggestions: small changes the app proposes (link two notes, turn a mention into a link, file an idea under
  a note, add a tag). A suggestion never changes anything by itself: you accept it, and accepting can be undone.
  One you turn down is not offered again. At most `PER_DAY` new ones a day.
- Daily picks: a few notes or ideas to think about today, each with the signal that picked it.
- Brainstorm: for one note or idea, its neighbours and the passages you highlighted on the same words.

Safety: the text of notes and documents is only ever counted and compared here. It is never followed as an
instruction, and the only changes that exist are the four kinds in `KINDS`, each on records that are checked
to exist. A later model (steps 2 and 3) plugs in behind `similar` and can only produce the same suggestions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import pages
from .db import DB, now

KINDS = ("link", "mention", "file_idea", "tag")
PER_DAY = 5           # new suggestions a day
PICKS = 3             # ideas to think about a day
MAX_PAGES = 600       # the most recently changed notes are looked at
MAX_IDEAS = 300
LINK_SCORE = 0.18     # how alike two notes must be before a link is proposed (two short notes on one topic score about 0.2)
IDEA_SCORE = 0.15
NEAR_SCORE = 0.12     # the least that counts as "similar"
SHEET = "Brainstorm: "  # the title of a brainstorm sheet starts with this
ID = re.compile(r"[0-9a-f]{32}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
WORD = re.compile(r"[^\W\d_][^\W\d_'\-]{2,}")  # three letters or more, in any alphabet
APOSTROPHE = re.compile(r"(?<=[^\W\d_])['’](?=[^\W\d_])")  # don't is one word (dont), matrix's folds to matrix
MARKS = re.compile(r"[\u064B-\u0652\u0640]")  # Arabic vowel marks and the stretching line: not part of the word
MARK = re.compile(r"\[\[([^\[\]\n|]{1,200})(?:\|([^\[\]\n]{0,200}))?\]\]")
STOP = frozenset("""the and for that this with from have has had not but are was were you your its they them their
there then than what when where which who whom why how can could should would will just into about over under also
more most some any all each very much many such only other out our ours his her she him one two use used using may
might must been being does did doing because while these those here onto per via etc too get got make made like
still yet ever even own same new old see say said way thing things lot bit let lets dont isnt itll ive
doesnt didnt wont cant youre theyre thats whats
today notes note good idea ideas related todo
في من على إلى الى عن هذا هذه ذلك تلك التي الذي الذين كان كانت يكون مع أن ان إن لا ما هو هي هم ثم أو او قد كل بعد قبل بين حتى عند لم لن هناك هنا أي كما لكن غير أيضا ايضا""".split())


def words(text: str) -> list[str]:
    """The words that carry meaning: lower-cased, markup and common words dropped, plurals folded."""
    text = MARK.sub(lambda m: m.group(2) or pages.ANCHOR.sub("", m.group(1)), text)
    out = []
    for w in WORD.findall(APOSTROPHE.sub("", MARKS.sub("", text.lower()))):
        if w in STOP:
            continue  # checked before folding, or "does" would pass as "doe"
        if w.isascii():
            if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
                w = w[:-1]  # maps and map are one word
        elif w.startswith("ال") and len(w) >= 5:
            w = w[2:]  # the Arabic "the" is written onto the word
        if len(w) >= 3 and w not in STOP:
            out.append(w)
    return out


def _one_line(text: str, n: int = 160) -> str:
    return " ".join(MARK.sub(lambda m: m.group(2) or pages.ANCHOR.sub("", m.group(1)), text).split())[:n]


class Corpus(list):
    """The items, plus how many of them use each word (so a new piece of text can be weighed the same way)."""

    df: Counter


def corpus(db: DB) -> Corpus:
    """Your notes (not the daily ones: they are a log, not a topic) and the ideas in the inbox, with their word weights."""
    items = Corpus()
    for r in db.all("SELECT id, title, body, tags, created_at, updated_at FROM pages WHERE deleted=0 AND daily IS NULL ORDER BY updated_at DESC LIMIT ?", (MAX_PAGES,)):
        if r["title"].startswith(SHEET):
            continue  # a brainstorm sheet is your thinking about a note, not a topic of its own
        tf = Counter(words(r["body"]))
        for w in words(r["title"]):
            tf[w] += 3  # the title says what the note is about
        items.append({"kind": "page", "id": r["id"], "title": r["title"], "text": r["body"], "tags": r["tags"].split(), "updated_at": r["updated_at"], "tf": tf})
    for r in db.all("SELECT id, text, created_at FROM ideas WHERE deleted=0 ORDER BY created_at DESC LIMIT ?", (MAX_IDEAS,)):
        items.append({"kind": "idea", "id": r["id"], "title": _one_line(r["text"], 80), "text": r["text"], "tags": [], "updated_at": r["created_at"], "tf": Counter(words(r["text"]))})
    n = len(items)
    df: Counter = Counter()
    for it in items:
        df.update(it["tf"].keys())
    for it in items:
        vec = {w: (1 + math.log(c)) * (math.log((n + 1) / (df[w] + 1)) + 1) for w, c in it["tf"].items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        it["vec"] = {w: v / norm for w, v in vec.items()}
    items.df = df
    return items


def _alike(a: dict, b: dict) -> tuple[float, list[str]]:
    """How alike two items are (0..1), and the words that make them alike, strongest first."""
    small, big = (a["vec"], b["vec"]) if len(a["vec"]) <= len(b["vec"]) else (b["vec"], a["vec"])
    parts = [(v * big[w], w) for w, v in small.items() if w in big]
    if not parts:
        return 0.0, []
    parts.sort(reverse=True)
    return sum(p for p, _ in parts), [w for _, w in parts[:3]]


def _vector(text: str, items: Corpus) -> dict:
    """Word weights for a piece of text that is not in the corpus (your quest, a highlight)."""
    n = len(items)
    df = items.df
    tf = Counter(words(text))
    vec = {w: (1 + math.log(c)) * (math.log((n + 1) / (df[w] + 1)) + 1) for w, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {w: v / norm for w, v in vec.items()}


def similar(db: DB, kind: str, item_id: str, n: int = 5, items: Corpus | None = None) -> list[dict]:
    items = items if items is not None else corpus(db)
    me = next((it for it in items if it["kind"] == kind and it["id"] == item_id), None)
    if not me:
        return []
    out = []
    for it in items:
        if it is me:
            continue
        score, shared = _alike(me, it)
        if score >= NEAR_SCORE and (len(shared) >= 2 or score >= 0.25):  # one common word is not enough, unless it carries the whole note
            out.append({"kind": it["kind"], "id": it["id"], "title": it["title"], "score": round(score, 3), "shared": shared})
    out.sort(key=lambda x: (-x["score"], x["title"]))
    return out[:n]


def _quoted(ws: list[str]) -> str:
    return ", ".join(ws)


# ------------------------------------------------------------------ suggestions
def _linked(db: DB) -> set[tuple[str, str]]:
    """Every (from note, to note) pair that already has a link."""
    by_key = {r["title_key"]: r["id"] for r in db.all("SELECT id, title_key FROM pages WHERE deleted=0")}
    return {(r["from_id"], by_key[r["target"]]) for r in db.all("SELECT from_id, target FROM page_links WHERE deleted=0") if r["target"] in by_key}


def candidates(db: DB, items: Corpus) -> list[dict]:
    """Every change worth proposing right now, best first. Nothing is written here."""
    notes = [it for it in items if it["kind"] == "page"]
    ideas = [it for it in items if it["kind"] == "idea"]
    linked = _linked(db)
    out: list[dict] = []
    recent = notes[:200]
    # a note names another note in plain words: the surest suggestion there is
    for target in recent:
        title = " ".join(target["title"].split())
        if len(title) < 4 or not pages.linkable(title):
            continue
        pattern = re.compile(r"(?<![\w\[])" + r"\s+".join(re.escape(w) for w in title.split()) + r"(?![\w\]])", re.I)
        low = title.casefold()
        for src in notes:
            if src is target or (src["id"], target["id"]) in linked or low not in src["text"].casefold():
                continue
            if pattern.search(MARK.sub("", src["text"])):
                out.append({"kind": "mention", "key": f"mention:{src['id']}:{target['id']}", "score": 1.0,
                            "payload": {"from_id": src["id"], "to_id": target["id"]},
                            "reason": f"“{src['title']}” mentions “{title}” in plain words, without a link."})
    # two notes about the same thing that do not link to each other
    for i, a in enumerate(recent):
        if len(a["text"]) < 40:
            continue
        for b in notes[i + 1:]:
            if len(b["text"]) < 40 or (a["id"], b["id"]) in linked or (b["id"], a["id"]) in linked or not pages.linkable(b["title"]):
                continue
            score, shared = _alike(a, b)
            if score >= LINK_SCORE and len(shared) >= 2:
                lo, hi = sorted((a["id"], b["id"]))
                out.append({"kind": "link", "key": f"link:{lo}:{hi}", "score": round(score, 3),
                            "payload": {"from_id": a["id"], "to_id": b["id"]},  # the note you touched last gets the link
                            "reason": f"Both are about {_quoted(shared)}, and neither links to the other."})
    # an idea in the inbox that belongs with a note
    for idea in ideas:
        best = max(((*_alike(idea, n), n) for n in notes), key=lambda x: x[0], default=None)
        if best and best[0] >= IDEA_SCORE and best[1]:
            out.append({"kind": "file_idea", "key": f"file_idea:{idea['id']}:{best[2]['id']}", "score": round(best[0], 3),
                        "payload": {"idea_id": idea["id"], "to_id": best[2]["id"]},
                        "reason": f"This idea shares {_quoted(best[1])} with the note “{best[2]['title']}”."})
    # a tag most of a note's neighbours carry
    for a in recent[:120]:
        near = [b for b in notes if b is not a and _alike(a, b)[0] >= 0.15][:6]
        count = Counter(t for b in near for t in b["tags"] if t not in a["tags"])
        for tag, k in count.items():
            if k >= 2 and re.fullmatch(r"[^\W\d_][\w-]{0,39}", tag):
                out.append({"kind": "tag", "key": f"tag:{a['id']}:{tag}", "score": round(0.3 + 0.05 * k, 3),
                            "payload": {"page_id": a["id"], "tag": tag},
                            "reason": f"{k} notes close to this one are tagged #{tag}."})
    out.sort(key=lambda c: (-c["score"], c["key"]))
    return out


def _page(db: DB, pid: str) -> dict | None:
    return db.one("SELECT id, title, body, daily FROM pages WHERE id=? AND deleted=0", (pid,)) if ID.fullmatch(pid or "") else None


def _describe(db: DB, s: dict) -> dict | None:
    """A suggestion with the titles it is about, or None when what it is about is gone or already done."""
    p = json.loads(s["payload"])
    out = {"id": s["id"], "kind": s["kind"], "reason": s["reason"], "status": s["status"], "created_at": s["created_at"]}
    if s["kind"] in ("link", "mention"):
        src, dst = _page(db, p.get("from_id", "")), _page(db, p.get("to_id", ""))
        if not src or not dst or pages.key(dst["title"]) in pages.links_in(src["body"]):
            return None
        verb = "Link" if s["kind"] == "link" else "Turn the mention into a link:"
        return {**out, "title": f"{verb} “{src['title']}” → “{dst['title']}”", "notes": [{"id": src["id"], "title": src["title"]}, {"id": dst["id"], "title": dst["title"]}],
                "change": f"Adds “Related: [[{dst['title']}]]” at the end of “{src['title']}”." if s["kind"] == "link" else f"The words “{dst['title']}” in “{src['title']}” become a link."}
    if s["kind"] == "file_idea":
        idea = db.one("SELECT id, text FROM ideas WHERE id=? AND deleted=0", (p.get("idea_id", ""),))
        dst = _page(db, p.get("to_id", ""))
        if not idea or not dst:
            return None
        return {**out, "title": f"File the idea under “{dst['title']}”", "notes": [{"id": dst["id"], "title": dst["title"]}], "quote": _one_line(idea["text"], 240),
                "change": f"Adds the idea as a line at the end of “{dst['title']}” and takes it out of the inbox."}
    if s["kind"] == "tag":
        page = _page(db, p.get("page_id", ""))
        tag = str(p.get("tag", ""))
        if not page or not re.fullmatch(r"[^\W\d_][\w-]{0,39}", tag) or tag in pages.tags_in(page["body"]).split():
            return None
        return {**out, "title": f"Tag “{page['title']}” with #{tag}", "notes": [{"id": page["id"], "title": page["title"]}], "change": f"Adds “#{tag}” at the end of the note."}
    return None


def suggestions(db: DB) -> list[dict]:
    """The open suggestions. New ones are made first, up to PER_DAY a day; ones that no longer apply are retired."""
    day = dt.date.today().isoformat()  # the limit is counted on this machine's day, whatever day the page sends
    made_today = db.scalar("SELECT COUNT(*) FROM suggestions WHERE created_at>=?", (_day_start(day),)) or 0
    if made_today < PER_DAY:
        known = {r["key"]: r for r in db.all("SELECT * FROM suggestions")}
        for c in candidates(db, corpus(db)):
            if made_today >= PER_DAY:
                break
            old = known.get(c["key"])
            if old and old["status"] == "stale" and not old["deleted"]:
                # it stopped applying once (a note was renamed, a link was added and removed) and applies again: offer it again
                fresh = {"payload": json.dumps(c["payload"]), "reason": c["reason"], "score": c["score"]}
                if _describe(db, {**old, **fresh, "status": "new"}):
                    db.update("suggestions", old["id"], {**fresh, "status": "new", "decided_at": None, "created_at": now()})
                    made_today += 1
                continue
            if c["key"] not in known:
                db.insert("suggestions", {"kind": c["kind"], "key": c["key"], "payload": json.dumps(c["payload"]), "reason": c["reason"], "score": c["score"]})
                known[c["key"]] = {"status": "new", "deleted": 0}
                made_today += 1
    out = []
    for s in db.all("SELECT * FROM suggestions WHERE status='new' AND deleted=0 ORDER BY score DESC, created_at"):
        shown = _describe(db, s)
        if shown:
            out.append(shown)
        else:
            db.update("suggestions", s["id"], {"status": "stale", "decided_at": now()})
    return out


def _day_start(day: str) -> str:
    """The UTC moment a local day began (close enough: the server and you share a clock)."""
    local = dt.datetime.combine(dt.date.fromisoformat(day), dt.time()).astimezone()
    return local.astimezone(dt.timezone.utc).isoformat()


def _set_body(db: DB, page_id: str, body: str) -> None:
    if len(body) > pages.MAX_BODY:
        raise HTTPException(409, "That note is full.")
    db.update("pages", page_id, {"body": body, "tags": pages.tags_in(body)})
    pages.relink(db, page_id, body)


def accept(db: DB, s: dict) -> dict:
    """Make the one change a suggestion stands for. What changed is kept, so it can be taken back."""
    if s["status"] != "new" or s["kind"] not in KINDS or not _describe(db, s):
        raise HTTPException(409, "That suggestion no longer applies.")
    p = json.loads(s["payload"])
    undo: dict = {}
    if s["kind"] == "link":
        src, dst = _page(db, p["from_id"]), _page(db, p["to_id"])
        after = f"{src['body'].rstrip()}\n\nRelated: [[{dst['title']}]]\n"
        undo = {"page_id": src["id"], "before": src["body"], "after": after}
        _set_body(db, src["id"], after)
    elif s["kind"] == "mention":
        src, dst = _page(db, p["from_id"]), _page(db, p["to_id"])
        after = pages.link_first_mention(src["body"], dst["title"])
        if after is None:
            raise HTTPException(409, "That note no longer mentions this title.")
        undo = {"page_id": src["id"], "before": src["body"], "after": after}
        _set_body(db, src["id"], after)
    elif s["kind"] == "file_idea":
        idea = db.one("SELECT id, text FROM ideas WHERE id=? AND deleted=0", (p["idea_id"],))
        dst = _page(db, p["to_id"])
        after = f"{dst['body'].rstrip()}\n- {_one_line(idea['text'], 1000)}\n"
        undo = {"page_id": dst["id"], "before": dst["body"], "after": after, "idea_id": idea["id"]}
        _set_body(db, dst["id"], after)
        db.soft_delete("ideas", idea["id"])
    elif s["kind"] == "tag":
        page = _page(db, p["page_id"])
        after = f"{page['body'].rstrip()}\n\n#{p['tag']}\n"
        undo = {"page_id": page["id"], "before": page["body"], "after": after}
        _set_body(db, page["id"], after)
    db.update("suggestions", s["id"], {"status": "accepted", "decided_at": now(), "undo": json.dumps(undo)})
    return {"ok": True, "id": s["id"], "page_id": undo.get("page_id")}


def undo(db: DB, s: dict) -> dict:
    if s["status"] != "accepted" or not s["undo"]:
        raise HTTPException(409, "There is nothing to take back.")
    u = json.loads(s["undo"])
    page = _page(db, u.get("page_id", ""))
    if not page or page["body"] != u["after"]:
        raise HTTPException(409, "The note has changed since. Edit it by hand to take the change out.")
    _set_body(db, page["id"], u["before"])
    if u.get("idea_id"):
        db.update("ideas", u["idea_id"], {"deleted": 0})
    db.update("suggestions", s["id"], {"status": "new", "decided_at": None, "undo": ""})
    return {"ok": True}


# ------------------------------------------------------------------ a few ideas to think about today
def _context(db: DB) -> tuple[str, str]:
    """What you are working on now (the words, and what to call it in a reason)."""
    from .compass import active_quest

    quest = active_quest(db)
    if quest:
        qs = " ".join(r["text"] for r in db.all("SELECT text FROM quest_questions WHERE quest_id=? AND deleted=0", (quest["id"],)))
        steps = " ".join(r["title"] for r in db.all("SELECT title FROM quest_steps WHERE quest_id=? AND deleted=0 AND done_at IS NULL", (quest["id"],)))
        return f"{quest['title']} {quest['title']} {qs} {steps}", f"your goal “{quest['title']}”"
    doc = db.one("SELECT title FROM documents WHERE deleted=0 AND status='reading' ORDER BY updated_at DESC LIMIT 1")
    return (f"{doc['title']} {doc['title']}", f"what you are reading, “{doc['title']}”") if doc else ("", "")


def _age(iso: str, today: dt.date) -> int:
    try:
        return (today - dt.datetime.fromisoformat(iso).astimezone().date()).days
    except ValueError:
        return 0


def _weeks(days: int) -> str:
    return f"{days} days" if days < 14 else f"{days // 7} weeks"


def make_picks(db: DB, day: str) -> None:
    """Choose today's few. One per kind of reason where possible, never one shown in the last week."""
    items = corpus(db)
    today = dt.date.fromisoformat(day)
    since = (today - dt.timedelta(days=7)).isoformat()
    seen = {(r["item_kind"], r["item_id"]) for r in db.all("SELECT item_kind, item_id FROM daily_picks WHERE day>=? AND deleted=0", (since,))}
    pool = [it for it in items if (it["kind"], it["id"]) not in seen and len(words(it["text"])) + len(words(it["title"])) >= 2]
    linked = _linked(db)
    has_link = {a for a, _ in linked} | {b for _, b in linked}
    text, name = _context(db)
    ctx = {"vec": _vector(text, items)} if text else None
    mix = lambda it: hashlib.sha256(f"{day}:{it['id']}".encode()).hexdigest()  # a different order each day, the same all day
    by_signal: dict[str, list[tuple[float, dict, str]]] = {"quest": [], "question": [], "orphan": [], "resting": []}
    for it in pool:
        age = _age(it["updated_at"], today)
        if ctx:
            score, shared = _alike(it, ctx)
            if score >= 0.1 and shared:
                by_signal["quest"].append((score, it, f"It shares {_quoted(shared)} with {name}."))
        open_q = next((l.strip() for l in it["text"].splitlines()
                       if (re.match(r"\s*[-*]\s+\[ \]\s+\S", l) and not l.rstrip().endswith("(in Plan)"))  # one already sent to Plan is taken care of
                       or (l.strip().endswith("?") and len(l.strip()) > 8)), "")
        if open_q:
            q = re.sub(r"^[-*]\s+\[ \]\s+", "", open_q)
            by_signal["question"].append((min(age, 60) / 60, it, f"It still holds an open question: “{_one_line(q, 90)}”"))
        if it["kind"] == "page" and it["id"] not in has_link and age >= 2:
            by_signal["orphan"].append((min(age, 60) / 60, it, "No note links to it and it links to none. Does it connect to anything?"))
        if age >= (7 if it["kind"] == "idea" else 14):
            what = "This idea has waited in the inbox for" if it["kind"] == "idea" else "You have not touched this note for"
            by_signal["resting"].append((min(age, 90) / 90, it, f"{what} {_weeks(age)}."))
    chosen: list[tuple[dict, str, str]] = []
    taken: set[str] = set()
    for _round in range(PICKS):
        for signal in ("quest", "question", "orphan", "resting"):
            rows = sorted((r for r in by_signal[signal] if r[1]["id"] not in taken), key=lambda r: (-round(r[0], 2), mix(r[1])))
            if rows and len(chosen) < PICKS:
                chosen.append((rows[0][1], signal, rows[0][2]))
                taken.add(rows[0][1]["id"])
    for it, signal, reason in chosen:
        db.insert("daily_picks", {"day": day, "item_kind": it["kind"], "item_id": it["id"], "signal": signal, "reason": reason})


def picks(db: DB, day: str) -> list[dict]:
    if not db.scalar("SELECT COUNT(*) FROM daily_picks WHERE day=? AND deleted=0", (day,)):
        make_picks(db, day)
    out = []
    for r in db.all("SELECT * FROM daily_picks WHERE day=? AND deleted=0 AND status!='dismissed' ORDER BY created_at, id", (day,)):
        item = _item(db, r["item_kind"], r["item_id"])
        if item:
            out.append({"id": r["id"], "kind": r["item_kind"], "item_id": r["item_id"], "title": item["title"], "snippet": pages._snippet(item["text"], 200) if r["item_kind"] == "page" else _one_line(item["text"], 200),
                        "signal": r["signal"], "reason": r["reason"], "status": r["status"]})
    return out


def _item(db: DB, kind: str, item_id: str) -> dict | None:
    if not ID.fullmatch(item_id or ""):
        return None
    if kind == "page":
        r = db.one("SELECT id, title, body FROM pages WHERE id=? AND deleted=0", (item_id,))
        return {"kind": "page", "id": r["id"], "title": r["title"], "text": r["body"]} if r else None
    if kind == "idea":
        r = db.one("SELECT i.id, i.text, i.document_id, i.sentence, d.title AS document_title FROM ideas i LEFT JOIN documents d ON d.id=i.document_id WHERE i.id=? AND i.deleted=0", (item_id,))
        return {"kind": "idea", "id": r["id"], "title": _one_line(r["text"], 80), "text": r["text"], "document_id": r["document_id"], "sentence": r["sentence"], "document_title": r["document_title"]} if r else None
    return None


# ------------------------------------------------------------------ brainstorm: one idea with everything near it
def brainstorm(db: DB, kind: str, item_id: str) -> dict:
    item = _item(db, kind, item_id)
    if not item:
        raise HTTPException(404, "not found")
    items = corpus(db)
    near = similar(db, kind, item_id, 6, items)
    me = {"vec": _vector(f"{item['title']} {item['text']}", items)}
    reading = []
    for h in db.all("SELECT h.document_id, h.sentence, h.type, h.text, h.note, d.title FROM highlights h JOIN documents d ON d.id=h.document_id"
                    " WHERE h.deleted=0 AND d.deleted=0 ORDER BY h.created_at DESC LIMIT 800"):
        score, shared = _alike(me, {"vec": _vector(f"{h['text']} {h['note']}", items)})
        if score >= NEAR_SCORE and shared:
            reading.append({"document_id": h["document_id"], "sentence": h["sentence"], "type": h["type"], "text": _one_line(h["text"], 300), "title": h["title"], "score": round(score, 3), "shared": shared})
    reading.sort(key=lambda x: -x["score"])
    sheet_title = f"{SHEET}{item['title']}"[:190]
    sheet = pages.find(db, sheet_title)
    return {"item": item, "near": near, "reading": reading[:6], "sheet_title": sheet_title,
            "sheet": {"id": sheet["id"], "body": sheet["body"]} if sheet else None}


# ------------------------------------------------------------------ API
class PickPatch(BaseModel):
    status: str = Field(..., pattern=r"^(new|opened|dismissed)$")


def register(app: FastAPI, db: DB) -> None:
    def day_ok(day: str) -> str:
        if not DAY.fullmatch(day or ""):
            raise HTTPException(422, "not a day")
        try:
            asked = dt.date.fromisoformat(day)
        except ValueError:
            raise HTTPException(422, "not a day") from None
        if abs((asked - dt.date.today()).days) > 1:  # the page and the server share a clock; a day apart only around midnight
            raise HTTPException(422, "not today")
        return day

    def suggestion(sid: str) -> dict:
        row = db.one("SELECT * FROM suggestions WHERE id=? AND deleted=0", (sid,)) if ID.fullmatch(sid or "") else None
        if not row:
            raise HTTPException(404, "not found")
        return row

    @app.get("/api/think")
    def api_think(day: str):
        day_ok(day)
        return {"day": day, "picks": picks(db, day), "suggestions": suggestions(db),
                "decided": {"accepted": db.scalar("SELECT COUNT(*) FROM suggestions WHERE status='accepted'") or 0,
                            "rejected": db.scalar("SELECT COUNT(*) FROM suggestions WHERE status='rejected'") or 0}}

    @app.get("/api/think/similar")
    def api_similar(kind: str, id: str):
        if kind not in ("page", "idea") or not ID.fullmatch(id or ""):
            raise HTTPException(404, "not found")
        return {"similar": similar(db, kind, id)}

    @app.get("/api/think/brainstorm")
    def api_brainstorm(kind: str, id: str):
        if kind not in ("page", "idea"):
            raise HTTPException(404, "not found")
        return brainstorm(db, kind, id)

    @app.post("/api/think/picks/{pid}")
    def api_pick(pid: str, body: PickPatch):
        if not ID.fullmatch(pid or "") or not db.one("SELECT 1 FROM daily_picks WHERE id=? AND deleted=0", (pid,)):
            raise HTTPException(404, "not found")
        db.update("daily_picks", pid, {"status": body.status})
        return {"ok": True}

    @app.post("/api/think/suggestions/{sid}/accept")
    def api_accept(sid: str):
        return accept(db, suggestion(sid))

    @app.post("/api/think/suggestions/{sid}/reject")
    def api_reject(sid: str):
        s = suggestion(sid)
        if s["status"] != "new":
            raise HTTPException(409, "That suggestion is already decided.")
        db.update("suggestions", sid, {"status": "rejected", "decided_at": now()})
        return {"ok": True}

    @app.post("/api/think/suggestions/{sid}/undo")
    def api_undo(sid: str):
        return undo(db, suggestion(sid))
