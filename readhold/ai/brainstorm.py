"""Brainstorm with a model (milestone 3.2 of docs/ai/PLAN.md): diverge, then converge.

The non-AI version is the brainstorm sheet (`think.brainstorm`): for a note or an idea, its neighbours in your
notes, the passages you highlighted on the same words, and questions you answer yourself. With AI switched on, and
only when you ask, a model also writes ideas, for a note, an idea or a whole document:

- Diverge: `ANGLES` samples, one call each at a high temperature (profile `brainstorm`), each from a different
  angle: connections, questions, uses. Each sample writes at most 5 ideas, each resting on 1 to 3 quotes.
- Converge: one critic call at temperature 0 (profile `brainstorm_critic`) reads the ideas, as data (a source of
  trust "model"), groups the ones that make the same point and ranks the groups. Code checks what it says: a
  number that is not an idea, or one already grouped, is dropped; ideas it left out follow its groups. When the
  critic fails, code groups ideas that share most of their words and keeps the samples' order (`judge` = "code").

What the model reads is what the sheet shows: the note or idea itself, its nearest notes and the passages you
highlighted on its words; for a document, its highlights and the notes nearest to them. Never whole documents.
Every quote must be, on whole words, in the text as it was sent; a document quote must also pass
`verify_citations` and is shown in the document's own words; a quote of your note or idea must be in its text as
it is now. An idea with no checked quote is never put in the sheet. Checked ideas come first.

Since 2026-11-26 (the owner's decision) the page puts every checked idea into the brainstorm sheet ("Brainstorm:
<title>") as soon as the model answers, each as its own section headed by its label, with no label line and no
source lines; markup the model wrote stays plain text. `undo` takes the last ideas out again while the sheet is
exactly as they left it. Nothing is written without your press of Ideas from the model.
"""
from __future__ import annotations

import json
import re
import threading
from itertools import combinations
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, StrictBool, StrictInt

from .. import pages, think
from ..db import DB, new_id
from . import guard, prompts, results
from .library import Run
from .notes import _inert, _note_line, _own_words
from .notes import _highlights as doc_highlights
from .port import AIError, AIOff, Cancelled, CouldNotGenerate, Port
from .resume import status_error

FEATURE = "brainstorm"
CRITIC = "brainstorm_critic"
ID = re.compile(r"[0-9a-f]{32}")
ANGLES = {
    "connect": "Connect: links between the sources that the reader may not have made yet.",
    "question": "Question: open questions, gaps, and what could prove an idea wrong.",
    "apply": "Apply: ways to use the ideas, small things to try, and contrasts or counter-cases.",
}
MAX_PER_SAMPLE = 5
MAX_SHOWN = 8
MAX_CITES = 3
MIN_QUOTE_WORDS = 4
SAME_WORDS = 0.6  # code grouping when the critic fails: ideas sharing this much of their words make the same point
CAPS = {"text": 400, "label": 80, "quote": 400, "source": 2_500, "near": 1_200}
# the questions of the non-AI sheet (web/src/views/think.ts): an idea's heading is never one of them, or the sheet
# would read the idea as your answer
SHEET_QUESTIONS = ("In one sentence, what is the idea?", "Why does it matter to you?", "What would make it wrong?",
                   "What does it connect to?", "What is the smallest way to test or use it?", "What question does it leave open?")
NO_LABEL = "Idea"  # the heading of an idea the critic gave no label (its first words would only repeat it)
NOTE_ANCHOR = re.compile(r"(note|idea):([0-9a-f]{32})")
HLNOTE_ANCHOR = re.compile(r"hlnote:([0-9a-f]{32}):(\d{1,7})")  # your note on a highlight


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


class Unchecked(Exception):
    pass


# loose on purpose: a field the model left null, wrote with the wrong type or too long drops that part, not the answer
class Cite(BaseModel):
    anchor: guard.LooseText = ""
    quote: guard.LooseText = ""


class Idea(BaseModel):
    text: guard.LooseText = ""
    sources: Annotated[list[Cite], guard.loose_list(6)] = []


class SampleOut(BaseModel):
    ideas: Annotated[list[Idea], guard.loose_list(12)] = []


class Group(BaseModel):
    label: guard.LooseText = ""
    # kept as the model wrote them (lax ints would turn `true` into idea 1); `_critic_groups` takes real ints only
    ideas: Annotated[list[StrictInt | StrictBool | float | str | None], guard.loose_list(40)] = []
    best: StrictInt | StrictBool | float | str | None = -1


class CriticOut(BaseModel):
    groups: Annotated[list[Group], guard.loose_list(30)] = []


# ------------------------------------------------------------------ what the model reads
def _yours(anchor: str, label: str, text: str, cap: int) -> guard.Source:
    return guard.Source(anchor, f"({label})\n{text[:cap]}", "yours")


def _target(db: DB, kind: str, item_id: str) -> tuple[dict, list[guard.Source]]:
    """What is brainstormed about, and the sources: the same things the non-AI sheet shows. A document's sheet says
    it is a document's, so it never shares a note's sheet; two documents with one title get an id suffix."""
    if not ID.fullmatch(item_id or ""):
        raise NotFound()
    if kind == "document":
        doc = db.one("SELECT id, title FROM documents WHERE id=? AND deleted=0", (item_id,))
        if not doc:
            raise NotFound()
        sources = doc_highlights(db, item_id)
        for s in sources:
            s.main = True  # what is brainstormed about: if the document is private, a cloud call is refused, not run on its neighbours
        if not sources:
            raise Invalid("There are no highlights in this document yet. Highlight a few passages first: the ideas build on them.")
        items = think.corpus(db)
        me = {"vec": think._vector(" ".join(s.text for s in sources), items)}
        near = sorted(((think._alike(me, it)[0], it) for it in items if it["kind"] == "page"), key=lambda x: -x[0])
        for score, it in near[:3]:
            if score >= think.NEAR_SCORE:
                sources.append(_yours(f"note:{it['id']}", f"Your note: {it['title'][:200]}", it["text"], CAPS["near"]))
        twin = any(pages.key(o["title"]) == pages.key(doc["title"]) for o in db.all("SELECT title FROM documents WHERE deleted=0 AND id!=?", (doc["id"],)))
        sheet = f"{think.SHEET}{' '.join(doc['title'].split())[:160]} (document{', ' + doc['id'][:6] if twin else ''})"
        return {"kind": "document", "id": doc["id"], "title": doc["title"], "sheet_title": sheet}, sources
    try:
        bs = think.brainstorm(db, kind, item_id)
    except HTTPException:
        raise NotFound() from None
    item = bs["item"]
    sources = [_yours(f"{'note' if kind == 'page' else 'idea'}:{item['id']}", f"Your {'note' if kind == 'page' else 'idea'}: {item['title'][:200]}", item["text"], CAPS["source"])]
    sources[0].main = True  # what is brainstormed about: if it is private, a cloud call is refused, not run without it
    for n in bs["near"][:4]:
        row = think._item(db, n["kind"], n["id"])
        if row:
            sources.append(_yours(f"{'note' if n['kind'] == 'page' else 'idea'}:{row['id']}", f"Your {'note' if n['kind'] == 'page' else 'idea'}: {row['title'][:200]}", row["text"], CAPS["near"]))
    name = {}
    for r in bs["reading"]:
        full = db.one("SELECT text FROM highlights WHERE document_id=? AND sentence=? AND deleted=0", (r["document_id"], r["sentence"]))
        if r["document_id"] not in name:
            name[r["document_id"]] = db.scalar("SELECT source FROM documents WHERE id=?", (r["document_id"],)) or ""
        sources.append(guard.Source(f"{r['document_id']}:{r['sentence']}", f"(Highlighted in {r['title'][:200]})\n{full['text'] if full else r['text']}",
                                    "imported", name[r["document_id"]]))
    return {"kind": kind, "id": item["id"], "title": item["title"], "sheet_title": bs["sheet_title"]}, sources


# ------------------------------------------------------------------ checking
def _body(text: str) -> str:
    """A source's text without the line in brackets that names it."""
    return text.split("\n", 1)[1] if text.startswith("(") and "\n" in text else text


def _span(run: str, q: str) -> str:
    """The words of `run` that are the quote (compared plain), as they are written there; `run` if not found."""
    toks = run.split()
    for s in range(len(toks)):
        if not guard._plain(toks[s]):
            continue
        for e in range(s, len(toks)):
            p = guard._plain(" ".join(toks[s:e + 1]))
            if p == q:
                return " ".join(toks[s:e + 1])
            if len(p) > len(q):
                break
    return run


def _note_words(text: str, quote: str) -> str:
    """Your own words for a quote of your note or idea: the shortest run of its lines that holds it, on one line."""
    lines = [x for x in text.splitlines() if x.strip()]
    q = guard._plain(quote)
    for j in range(len(lines)):
        for i in range(j, max(-1, j - 8), -1):
            run = " ".join(" ".join(lines[i:j + 1]).split())
            if guard.word_in(q, guard._plain(run)):
                run = _span(run, q)
                return run if len(run) <= CAPS["quote"] else run[:CAPS["quote"]].rsplit(" ", 1)[0] + " …"
    return " ".join(guard.safe_output(quote, CAPS["quote"]).text.split())


def _cite(db: DB, c: dict, sent: dict[str, str]) -> dict | None:
    """A quote counts only when it is in a text that was sent, and in the library as it is now."""
    quote = c.get("quote") or ""
    held = [a for a, text in sent.items() if guard.quote_in(quote, _body(text), MIN_QUOTE_WORDS)]
    held.sort(key=lambda a: a != c.get("anchor"))
    for a in held:
        if m := NOTE_ANCHOR.fullmatch(a):
            kind, rid = m.groups()
            if kind == "note":
                row = db.one("SELECT id, title, body AS text FROM pages WHERE id=? AND deleted=0", (rid,))
            else:
                row = db.one("SELECT id, substr(text, 1, 80) AS title, text FROM ideas WHERE id=? AND deleted=0", (rid,))
            if row and guard.quote_in(quote, row["text"], MIN_QUOTE_WORDS):
                return {"kind": kind, "id": row["id"], "title": " ".join(row["title"].split()), "quote": _note_words(row["text"], quote)}
        elif m := HLNOTE_ANCHOR.fullmatch(a):
            row = db.one("SELECT h.note, d.title FROM highlights h JOIN documents d ON d.id=h.document_id AND d.deleted=0"
                         " WHERE h.document_id=? AND h.sentence=? AND h.deleted=0 AND h.note!=''", (m.group(1), int(m.group(2))))
            if row and guard.quote_in(quote, row["note"], MIN_QUOTE_WORDS):
                return {"kind": "hlnote", "document_id": m.group(1), "document_title": row["title"], "sentence": int(m.group(2)),
                        "quote": _note_words(row["note"], quote)}
        elif guard.DOC_ANCHOR.fullmatch(a):
            got = guard.verify_citations(db, [{"anchor": a, "quote": quote}])
            if got.kept:
                k = got.kept[0]
                title = db.scalar("SELECT title FROM documents WHERE id=?", (k["document_id"],)) or ""
                own = _own_words(db, k["section_id"], k["sentence"], quote)
                return {"kind": "document", "document_id": k["document_id"], "document_title": title, "sentence": k["sentence"],
                        "quote": own or guard.safe_output(quote, CAPS["quote"]).text}
    return None


def _mark(c: dict) -> tuple:
    return (c.get("document_id") or c.get("id"), c.get("sentence"), guard._plain(c["quote"]))


def _merge(cites: list[list[dict]]) -> list[dict]:
    out, seen = [], set()
    for group in cites:
        for c in group:
            if _mark(c) not in seen and len(out) < MAX_CITES:
                seen.add(_mark(c))
                out.append(c)
    return out


def _words(text: str) -> set[str]:
    return set(think.words(text))


def _overlap(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x | y else 1.0


def _code_groups(ideas: list[dict]) -> list[tuple[str, list[int], int]]:
    """When the critic fails: ideas that share most of their words are one group, in the samples' order."""
    groups: list[list[int]] = []
    for i, it in enumerate(ideas):
        home = next((g for g in groups if _overlap(ideas[g[0]]["text"], it["text"]) >= SAME_WORDS), None)
        if home is None:
            groups.append([i])
        else:
            home.append(i)
    return [("", g, g[0]) for g in groups]


def _critic_groups(data: dict, n: int) -> list[tuple[str, list[int], int]]:
    """What the critic said, checked: real numbers only, each in one group; the rest follow, one by one."""
    used: set[int] = set()
    out = []
    for g in data.get("groups") or []:
        members = []
        for i in g.get("ideas") or []:
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n and i not in used and i not in members:
                members.append(i)
        if not members:
            continue
        used.update(members)
        best = g.get("best")
        real = isinstance(best, int) and not isinstance(best, bool)  # `True in [1]` is true in Python: check the type first
        out.append((guard.safe_output(str(g.get("label") or ""), CAPS["label"]).text, members, best if real and best in members else members[0]))
    return out + [("", [i], i) for i in range(n) if i not in used]


def _variety(texts: list[str]) -> float | None:
    """1 minus the mean share of words two shown ideas have in common: 1 = all different, 0 = all the same."""
    pairs = list(combinations(texts, 2))
    return round(1 - sum(_overlap(a, b) for a, b in pairs) / len(pairs), 3) if pairs else None


# ------------------------------------------------------------------ the two steps
_runs: set[Run] = set()
_runs_lock = threading.Lock()


def cancel(port: Port) -> bool:
    """Stop every brainstorm that is running: the call in flight is cancelled, and no further call starts."""
    with _runs_lock:
        runs = list(_runs)
    for r in runs:
        r.stop.set()
        if r.call_id:
            port.cancel(r.call_id)
    return bool(runs)


def _call(port: Port, db: DB, run: Run, task: str, instruction: str, sources: list[guard.Source], schema, version: str, topic: str | None) -> guard.Result:
    if run.stop.is_set():
        raise Cancelled()
    run.call_id = new_id()
    r = guard.ask(port, db, task, instruction, sources, budget=FEATURE, question=topic, schema=schema, prompt_version=version, call_id=run.call_id)
    if run.stop.is_set():
        raise Cancelled()
    return r


def write(port: Port, db: DB, kind: str, item_id: str, topic: str = "", fresh: bool = False) -> dict:
    if port.settings().get("ai_mode") not in ("local", "cloud"):
        raise AIOff()
    target, sources = _target(db, kind, item_id)
    left_out = 0
    if guard.leaves(port):  # a file of secrets never leaves this computer: left out, not fatal
        out = [x for x in sources if not (x.name and guard.sensitive_name(x.name))]
        left_out = len({x.anchor.split(":")[0] if guard.DOC_ANCHOR.fullmatch(x.anchor) else x.anchor for x in sources if x not in out})
        sources = out
        if not sources:
            raise Invalid("Every passage here comes from a file of secrets. Such files are never sent to a cloud model; use a local model for them.")
    topic_q = guard.user_text(topic, "topic") if topic.strip() else None
    prompt, critic = prompts.load(FEATURE), prompts.load(CRITIC)
    key = results.key(prompt.hash, critic.hash, kind, topic_q or "", *(f"{s.anchor}\n{s.text}" for s in sources))
    run = Run()
    with _runs_lock:
        _runs.add(run)
    try:
        with results.once(FEATURE, key):
            kept = results.find(db, FEATURE, target["id"], key)
            if kept and not fresh:
                return kept
            return _diverge_converge(port, db, run, target, sources, topic_q, prompt, critic, key, kept, left_out)
    finally:
        with _runs_lock:
            _runs.discard(run)


def _diverge_converge(port, db, run, target, sources, topic, prompt, critic, key, kept, left_out=0) -> dict:
    cands: list[dict] = []
    links: list[str] = []
    log_ids: list[str] = []
    warning = ""
    sent: dict[str, str] = {}
    failed: AIError | None = None
    answered = 0
    for angle, how in ANGLES.items():
        try:
            r = _call(port, db, run, FEATURE, f"{prompt.text}\n\nAngle: {angle}. {how}", sources, SampleOut, prompt.version, topic)
        except CouldNotGenerate as e:  # one sample that could not be read does not sink the others
            failed = e
            if e.log_id:
                log_ids.append(e.log_id)  # listed by "Why did it say this?" with its outcome
            continue
        for a, text in r.sent.items():
            sent.setdefault(a, text)
        links += r.links
        log_ids.append(r.log_id)
        answered += 1
        warning = warning or r.warning
        for it in r.data["ideas"][:MAX_PER_SAMPLE]:
            text = guard.safe_output(it.get("text") or "", CAPS["text"]).text
            if text:
                cites = [c for c in (_cite(db, dict(c), r.sent) for c in (it.get("sources") or [])[:MAX_CITES * 2]) if c]
                cands.append({"text": text, "angle": angle, "cites": _merge([cites])})
    if not answered and failed:  # no sample answered
        raise failed
    judge = "model"
    if len(cands) > 1:
        listing = "\n".join(f"{i}. {c['text']}" for i, c in enumerate(cands))
        src = guard.Source(f"ideas:{new_id()}", f"(The ideas, numbered)\n{listing}", "model")
        try:
            r = _call(port, db, run, CRITIC, critic.text, [src], CriticOut, critic.version, None)
            groups = _critic_groups(r.data, len(cands))
            log_ids.append(r.log_id)
        except (Cancelled, AIOff):
            raise
        except AIError as e:  # whatever went wrong with the critic, the samples are kept: code groups them
            groups, judge = _code_groups(cands), "code"
            if e.log_id:
                log_ids.append(e.log_id)
    else:
        groups, judge = [("", [i], i) for i in range(len(cands))], "none"  # one idea or none: nothing to group or rank
    ideas = []
    for label, members, best in groups:
        if not cands[best]["cites"]:  # the group is led by a member that rests on a checked quote of its own, if one does
            best = next((i for i in members if cands[i]["cites"]), best)
        cites = cands[best]["cites"]  # only its own: a quote never vouches for another idea's text
        ideas.append({"text": cands[best]["text"], "label": label, "similar": len(members) - 1, "angles": sorted({cands[i]["angle"] for i in members}),
                      "sources": cites, "verified": bool(cites)})
    ideas.sort(key=lambda x: not x["verified"])  # stable: the critic's order within each
    ideas = ideas[:MAX_SHOWN]
    proven = sum(1 for x in ideas if x["verified"])
    payload = {"target": {k: target[k] for k in ("kind", "id", "title", "sheet_title")}, "topic": topic or "", "ideas": ideas, "judge": judge,
               "variety": _variety([x["text"] for x in ideas]), "kept": [], "left_out": left_out,
               "status": "verified" if ideas and proven == len(ideas) else "partly" if proven else "unverified",
               "links": list(dict.fromkeys(links)), "warning": warning, "log_ids": log_ids}
    return results.keep(db, FEATURE, target["id"], key, payload, prompt.version, log_ids[-1], replaces=kept["id"] if kept else None,
                        target_type="document" if target["kind"] == "document" else target["kind"])


# ------------------------------------------------------------------ keeping what you choose
def keep(db: DB, result_id: str, chosen: list[dict]) -> dict:
    row = db.one("SELECT * FROM ai_results WHERE id=? AND feature=? AND deleted=0", (result_id, FEATURE)) if ID.fullmatch(result_id or "") else None
    if not row:
        raise NotFound()
    payload = json.loads(row["payload"])
    if not chosen:
        raise Invalid("Choose at least one idea to keep.")
    kept, picked, seen = set(payload.get("kept") or []), [], set()
    for c in chosen:
        i = c.get("index")
        if not isinstance(i, int) or not 0 <= i < len(payload["ideas"]):
            raise Invalid("That idea is not in this result.")
        it = payload["ideas"][i]
        text = " ".join(str(c.get("text") or "").split())[:600]
        if not text:
            raise Invalid("An idea to keep needs its text.")
        if not it["verified"]:
            raise Unchecked()
        if i not in seen and i not in kept:
            seen.add(i)
            picked.append((i, it, text))
    with db.transaction():  # two keeps at once: each reads the sheet the other wrote
        return _write_sheet(db, result_id, payload, kept, picked)


def _write_sheet(db: DB, result_id: str, payload: dict, kept: set, picked: list) -> dict:
    kept = kept | set(json.loads(db.scalar("SELECT payload FROM ai_results WHERE id=?", (result_id,)) or "{}").get("kept") or [])
    picked = [x for x in picked if x[0] not in kept]  # kept by a request that finished while this one waited
    title = payload["target"]["sheet_title"]
    page = pages.find(db, title)
    before = page["body"] if page else ""
    body = before.rstrip()
    new, added = [], []
    for i, it, text in picked:  # each idea its own section, headed by its label: yours to edit or delete in the note
        sentence = _sentence(_note_line(text, it))
        if sentence in body or any(sentence in x for x in new):
            continue
        new.append(f"## {_heading(it.get('label') or '', sentence)}\n{sentence}")
        added.append(i)
    if not new:  # every idea is in the sheet already: nothing to write
        return {"page_id": page["id"] if page else "", "title": title, "added": 0, "kept": sorted(kept | {i for i, *_ in picked})}
    page = page or pages.create(db, title, "")
    body = "\n\n".join(([body] if body else []) + new) + "\n"
    if len(body) > pages.MAX_BODY:
        raise Invalid("That sheet is full. Start a new note.")
    db.update("pages", page["id"], {"body": body, "tags": pages.tags_in(body)})
    pages.relink(db, page["id"], body)
    payload["kept"] = sorted(kept | {i for i, *_ in picked})
    if new:  # what Undo needs: the sheet before and after, and which ideas this put in (always true here)
        payload["last"] = {"page_id": page["id"], "before": before, "after": body, "ideas": added}
    db.update("ai_results", result_id, {"payload": json.dumps(payload, ensure_ascii=False), "status": "accepted"})
    return {"page_id": page["id"], "title": title, "added": len(new), "kept": payload["kept"]}


class Changed(Exception):
    pass


def undo(db: DB, result_id: str, page_id: str) -> dict:
    """Take the last ideas put into the sheet back out, only while the sheet is exactly as they left it (a later
    edit of yours is never undone). The ideas taken out can be kept again."""
    row = db.one("SELECT * FROM ai_results WHERE id=? AND feature=? AND deleted=0", (result_id, FEATURE)) if ID.fullmatch(result_id or "") else None
    if not row:
        raise NotFound()
    with db.transaction():
        payload = json.loads(db.scalar("SELECT payload FROM ai_results WHERE id=?", (result_id,)))
        last = payload.get("last")
        if not last or last.get("page_id") != page_id:
            raise NotFound()
        page = db.one("SELECT id, body FROM pages WHERE id=? AND deleted=0", (page_id,))
        if not page or page["body"] != last["after"]:
            raise Changed()
        db.update("pages", page_id, {"body": last["before"], "tags": pages.tags_in(last["before"])})
        pages.relink(db, page_id, last["before"])
        payload["kept"] = sorted(set(payload.get("kept") or []) - set(last["ideas"]))
        payload.pop("last")
        db.update("ai_results", result_id, {"payload": json.dumps(payload, ensure_ascii=False)})
    return {"kept": payload["kept"]}


def _heading(label: str, sentence: str = "") -> str:
    """An idea's section heading: its label from the critic, else "Idea"; on one line, its markup plain, and never
    the name of one of the sheet's questions."""
    head = " ".join(_inert(label).split())[:80].strip(" #") or NO_LABEL
    return f"{head} (idea)" if head in SHEET_QUESTIONS else head


def _sentence(text: str) -> str:
    """An idea as the sentence of its section: on one line, ending with a full stop unless it has its own end mark."""
    text = " ".join(text.split())
    return text if text[-1:] in ".!?…" else f"{text}."


# ------------------------------------------------------------------ routes
class BrainIn(BaseModel):
    kind: Literal["page", "idea", "document"]
    id: str = Field(max_length=40)
    topic: str = Field("", max_length=200)
    fresh: bool = False


class Chosen(BaseModel):
    index: int
    text: str = Field("", max_length=2000)


class UndoIn(BaseModel):
    page_id: str = Field(max_length=40)


class KeepIn(BaseModel):
    items: list[Chosen] = Field(default_factory=list, max_length=MAX_SHOWN * 2)


def register(app: FastAPI, db: DB, port: Port) -> None:
    @app.post("/api/brainstorm")
    def api_brainstorm(body: BrainIn):
        """A plain `def`: the calls run on a worker thread, and the app is never blocked."""
        try:
            return {"result": write(port, db, body.kind, body.id, body.topic, body.fresh)}
        except NotFound:
            raise HTTPException(404, "not found") from None
        except (Invalid, guard.Blocked) as e:
            raise HTTPException(409, str(e)) from None
        except AIError as e:
            raise HTTPException(status_error(e), e.message) from None

    @app.post("/api/brainstorm/cancel")
    def api_brainstorm_cancel():
        return {"cancelled": cancel(port)}

    @app.post("/api/brainstorm/{result_id}/keep")
    def api_brainstorm_keep(result_id: str, body: KeepIn):
        try:
            return keep(db, result_id, [c.model_dump() for c in body.items])
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Unchecked:
            raise HTTPException(409, "Only ideas that rest on a checked passage can be kept.") from None
        except Invalid as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/brainstorm/{result_id}/undo")
    def api_brainstorm_undo(result_id: str, body: UndoIn):
        try:
            return undo(db, result_id, body.page_id)
        except NotFound:
            raise HTTPException(404, "not found") from None
        except Changed:
            raise HTTPException(409, "The sheet changed since the ideas went in. Delete them in the note by hand.") from None
