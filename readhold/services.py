"""Domain logic: questions, cards (FSRS), summary sheet, export, home and stats."""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict

from fsrs import Card, Rating, Scheduler

from . import config
from .db import DB, now
from .store import doc_sentences, key_sentence_stats
from .text import math_to_markdown
from .terms import find_acronyms

# ---------------------------------------------------------------- questions

DEFAULT_TEMPLATES: dict[str, list[str]] = {
    "abstract": ["What problem does this solve?", "What is the main claim, in one line?"],
    "intro": ["Why does this problem matter?", "What is new compared to earlier work?"],
    "related": ["How is this different from what came before?"],
    "method": ["How does it work, step by step?", "What goes in and what comes out?"],
    "results": ["Which numbers back the main claim?", "What was it compared against?"],
    "discussion": ["What are the limits of this result?"],
    "conclusion": ["What should I remember in one sentence?"],
    "appendix": [],
    "references": [],
    "other": ["What is the main point of this section?"],
}


def question_templates(db: DB, kind: str) -> list[str]:
    learned = [
        r["text"]
        for r in db.all(
            "SELECT text FROM template_bank WHERE section_kind=? AND deleted=0 ORDER BY uses DESC LIMIT 3", (kind,)
        )
    ]
    out: list[str] = []
    for t in learned + DEFAULT_TEMPLATES.get(kind, DEFAULT_TEMPLATES["other"]):
        if t not in out:
            out.append(t)
    return out


def learn_template(db: DB, kind: str, text: str) -> None:
    """Questions you keep teach the next paper of the same kind. Specific nouns are left as written."""
    text = text.strip()
    if not text or len(text) > 140:
        return
    row = db.one("SELECT id, uses FROM template_bank WHERE section_kind=? AND text=?", (kind, text))
    if row:
        db.update("template_bank", row["id"], {"uses": row["uses"] + 1, "deleted": 0})
    else:
        db.insert("template_bank", {"section_kind": kind, "text": text})


# ---------------------------------------------------------------- cards (FSRS)

_scheduler = Scheduler()


def _iso(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def upsert_card(db: DB, source_type: str, source_id: str, front: str, back: str, document_id: str | None) -> dict:
    front, back = front.strip(), back.strip()
    existing = db.one("SELECT * FROM cards WHERE source_type=? AND source_id=?", (source_type, source_id))
    if existing:
        # a card you deleted in Review (suspended) stays deleted when its source changes; only its Undo brings it back
        db.update("cards", existing["id"], {"front": front, "back": back, **({} if existing["suspended"] else {"deleted": 0})})
        return {**existing, "front": front, "back": back}
    card = Card()
    return db.insert(
        "cards",
        {
            "document_id": document_id,
            "source_type": source_type,
            "source_id": source_id,
            "front": front,
            "back": back,
            "fsrs": json.dumps(card.to_dict()),
            "due": _iso(card.due),
        },
    )


def remove_card(db: DB, source_type: str, source_id: str) -> None:
    row = db.one("SELECT id FROM cards WHERE source_type=? AND source_id=?", (source_type, source_id))
    if row:
        db.soft_delete("cards", row["id"])


def reviews_today(db: DB) -> int:
    start = dt.datetime.combine(dt.date.today(), dt.time.min).astimezone()
    return db.scalar("SELECT COUNT(*) FROM reviews WHERE reviewed_at >= ? AND deleted=0", (_iso(start),)) or 0


def due_cards(db: DB, cap: int) -> dict:
    remaining = max(cap - reviews_today(db), 0)
    rows = db.all(
        "SELECT id, document_id, source_type, front, back, due FROM cards WHERE deleted=0 AND suspended=0 AND due<=?"
        " ORDER BY due LIMIT ?",
        (_iso(dt.datetime.now(dt.timezone.utc)), remaining),
    )
    total_due = db.scalar(
        "SELECT COUNT(*) FROM cards WHERE deleted=0 AND suspended=0 AND due<=?", (_iso(dt.datetime.now(dt.timezone.utc)),)
    )
    return {"cards": rows, "due_total": total_due, "cap_left": remaining}


def review_card(db: DB, card_id: str, rating: int) -> dict:
    row = db.one("SELECT * FROM cards WHERE id=? AND deleted=0", (card_id,))
    if not row:
        raise KeyError(card_id)
    card = Card.from_dict(json.loads(row["fsrs"]))
    card, _log = _scheduler.review_card(card, Rating(rating))
    db.update("cards", card_id, {"fsrs": json.dumps(card.to_dict()), "due": _iso(card.due)})
    db.insert("reviews", {"card_id": card_id, "rating": rating, "reviewed_at": _iso(dt.datetime.now(dt.timezone.utc))})
    return {"id": card_id, "due": _iso(card.due)}


def definition_card_front(sentence: str, note: str) -> str:
    if note.strip():
        return f"What is {note.strip()}?"
    m = re.match(r"^\s*(?:An?|The)?\s*([\w\- ]{2,40}?)\s+(?:is|are|refers to|denotes|means)\b", sentence)
    if m:
        return f"What is {m.group(1).strip()}?"
    words = sentence.split()
    return "Recall the definition: " + " ".join(words[:6]) + " …"


def cloze_front(sentence: str, hidden: str) -> str:
    return re.sub(re.escape(hidden), "_____", sentence, count=1)


def sync_highlight_card(db: DB, hl: dict) -> None:
    """Definition highlights → definition card; evidence with a cloze word → fill-in-the-blank card."""
    if hl.get("deleted"):
        remove_card(db, "definition", hl["id"])
        remove_card(db, "cloze", hl["id"])
        return
    if hl["type"] == "definition":
        upsert_card(db, "definition", hl["id"], definition_card_front(hl["text"], hl.get("note", "")), hl["text"], hl["document_id"])
    else:
        remove_card(db, "definition", hl["id"])  # its type changed: the old card must not stay in review
    if hl["type"] == "evidence" and hl.get("cloze"):
        upsert_card(db, "cloze", hl["id"], cloze_front(hl["text"], hl["cloze"]), hl["cloze"] + "\n\n" + hl["text"], hl["document_id"])
    else:
        remove_card(db, "cloze", hl["id"])


# ---------------------------------------------------------------- summary sheet and export


def summary(db: DB, doc_id: str) -> dict:
    doc = db.one("SELECT id, title, source, why, explain_text, status, critique, reproduce FROM documents WHERE id=?", (doc_id,))
    hls = db.all("SELECT * FROM highlights WHERE document_id=? AND deleted=0 ORDER BY sentence", (doc_id,))
    claims: list[dict] = []
    orphan_evidence: list[dict] = []
    for h in hls:
        if h["type"] == "claim":
            claims.append({**h, "evidence": []})
        elif h["type"] == "evidence":
            (claims[-1]["evidence"] if claims else orphan_evidence).append(h)
    questions = db.all(
        "SELECT id, text, answer, source_sentence FROM questions WHERE document_id=? AND deleted=0 ORDER BY ord, created_at",
        (doc_id,),
    )
    terms = db.all(
        "SELECT term, guess, definition, sentence FROM terms WHERE document_id=? AND deleted=0 AND is_concept=0 ORDER BY term",
        (doc_id,),
    )
    definitions = [h for h in hls if h["type"] == "definition"]
    confusions = [h for h in hls if h["type"] == "confusing" and not h["resolved"]]
    ideas = [h for h in hls if h["type"] == "idea"]
    notes = db.all("SELECT sentence, text FROM notes WHERE document_id=? AND deleted=0 ORDER BY sentence", (doc_id,))
    sections = db.all(
        "SELECT title, prediction, prediction_check FROM sections WHERE document_id=? AND deleted=0 AND prediction!='' ORDER BY ord",
        (doc_id,),
    )
    acronyms = find_acronyms([t for _, t in doc_sentences(db, doc_id)])
    return {
        "document": doc,
        "claims": claims,
        "orphan_evidence": orphan_evidence,
        "questions": questions,
        "terms": terms,
        "definitions": definitions,
        "confusions": confusions,
        "ideas": ideas,
        "notes": notes,
        "predictions": sections,
        "acronyms": acronyms,
        "progress": key_sentence_stats(db, doc_id),
    }


def summary_markdown(db: DB, doc_id: str) -> str:
    s = summary(db, doc_id)
    d = s["document"]
    src = d["source"] or ""
    link = (lambda o: f" ([s{o}]({src}))") if src.startswith("http") else (lambda o: f" (s{o})")
    out = [f"# {d['title']}", ""]
    if src:
        out += [f"Source: {src}", ""]
    if d["why"]:
        out += [f"**Why I read this:** {d['why']}", ""]
    if d["explain_text"]:
        out += ["## In my words", "", d["explain_text"], ""]
    if s["claims"] or s["orphan_evidence"]:
        out += ["## Main points", ""]
        for c in s["claims"]:
            out.append(f"- **Claim:** {c['text']}{link(c['sentence'])}" + (f" — _{c['note']}_" if c["note"] else ""))
            for e in c["evidence"]:
                out.append(f"  - Evidence: {e['text']}{link(e['sentence'])}")
        for e in s["orphan_evidence"]:
            out.append(f"- Evidence: {e['text']}{link(e['sentence'])}")
        out.append("")
    if (d.get("critique") or "").strip() or (d.get("reproduce") or "").strip():
        out += ["## My critique", ""]
        if d.get("critique", "").strip():
            out += [d["critique"].strip(), ""]
        if d.get("reproduce", "").strip():
            out += [f"**A result I'd reproduce:** {d['reproduce'].strip()}", ""]
    if s.get("predictions"):
        out += ["## Predictions", ""]
        for p in s["predictions"]:
            out.append(f"- **{p['title']}** — I predicted: {p['prediction']}")
            if p.get("prediction_check"):
                out.append(f"  - Afterwards: {p['prediction_check']}")
        out.append("")
    if s["questions"]:
        out += ["## Questions", ""]
        for q in s["questions"]:
            out.append(f"- **{q['text']}**")
            out.append(f"  - {q['answer'] or '_not answered yet_'}")
        out.append("")
    if s["terms"] or s["definitions"] or s["acronyms"]:
        out += ["## Glossary", ""]
        for t in s["terms"]:
            out.append(f"- **{t['term']}**: {t['definition'] or t['guess']}")
        for h in s["definitions"]:
            out.append(f"- {h['text']}{link(h['sentence'])}")
        for k, v in s["acronyms"].items():
            out.append(f"- **{k}**: {v}")
        out.append("")
    if s["confusions"]:
        out += ["## Still confusing", ""] + [f"- {h['text']}{link(h['sentence'])}" for h in s["confusions"]] + [""]
    if s["ideas"]:
        out += ["## Ideas", ""] + [f"- {h['note'] or h['text']}{link(h['sentence'])}" for h in s["ideas"]] + [""]
    if s["notes"]:
        out += ["## Margin notes", ""] + [f"- {n['text']}{link(n['sentence'])}" for n in s["notes"]] + [""]
    return math_to_markdown("\n".join(out))  # formulas as $…$, which Obsidian and most Markdown tools render


def export_markdown_file(db: DB, doc_id: str) -> str:
    md = summary_markdown(db, doc_id)
    title = db.scalar("SELECT title FROM documents WHERE id=?", (doc_id,)) or doc_id
    safe = re.sub(r"[^\w\- ]+", "", title)[:80].strip() or "document"
    path = config.exports_dir() / f"{safe} ({doc_id[:8]}).md"  # the id: one file per document, and never a reserved name
    path.write_text(md, "utf-8")
    return str(path)


EXPORT_TABLES = [
    "documents", "sections", "paragraphs", "sentences", "questions", "question_links", "highlights", "notes", "ai_results",
    "terms", "cards", "reviews", "sessions", "ideas", "template_bank", "settings",
    "quests", "quest_questions", "quest_steps", "side_quests", "checkins", "map_nodes", "map_edges", "day_logs",
    "habits", "habit_checks", "practice_attempts", "lectures", "lecture_pages", "lecture_notes", "ink",
    "journal_entries", "letters", "todos", "todo_items", "timer_runs", "unstick_events", "steady_notes", "routines", "routine_steps", "routine_checks", "pages", "page_links",
    "suggestions", "daily_picks",
]  # never "ai_log": an export is kept for good, the AI log is gone after its days or on Clear AI history


def export_all(db: DB) -> str:
    data = {}
    for t in EXPORT_TABLES:
        cols = {r["name"] for r in db.all(f"PRAGMA table_info({t})")}
        data[t] = db.all(f"SELECT * FROM {t}" + (" WHERE deleted=0" if "deleted" in cols else ""))
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.exports_dir() / f"readhold-export-{stamp}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    md_dir = config.exports_dir() / f"notes-{stamp}"
    md_dir.mkdir(exist_ok=True)
    for d in db.all("SELECT id, title FROM documents WHERE deleted=0"):
        safe = re.sub(r"[^\w\- ]+", "", d["title"])[:80].strip() or "document"
        # the id keeps two documents with one title apart, and "CON" or "NUL" from being a reserved name on Windows
        (md_dir / f"{safe} ({d['id'][:8]}).md").write_text(summary_markdown(db, d["id"]), "utf-8")
    return str(path)


# ---------------------------------------------------------------- home and stats


def _local_date(iso: str) -> dt.date:
    return dt.datetime.fromisoformat(iso).astimezone().date()


def daily_stats(db: DB, days: int = 14) -> list[dict]:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days + 1)
    per: dict[dt.date, dict] = defaultdict(lambda: {"focused_ms": 0, "longest_run_ms": 0, "sentences": 0, "reviews": 0, "distractions": 0})
    for s in db.all("SELECT * FROM sessions WHERE started_at>=? AND deleted=0", (since.isoformat(),)):
        d = per[_local_date(s["started_at"])]
        d["focused_ms"] += s["focused_ms"]
        d["longest_run_ms"] = max(d["longest_run_ms"], s["longest_run_ms"])
        d["sentences"] += s["sentences_read"]
        d["distractions"] += s["distractions"]
    for r in db.all("SELECT reviewed_at FROM reviews WHERE reviewed_at>=? AND deleted=0", (_iso(since),)):
        per[_local_date(r["reviewed_at"])]["reviews"] += 1
    today = dt.date.today()
    out = []
    for i in range(days - 1, -1, -1):
        day = today - dt.timedelta(days=i)
        d = per.get(day, {"focused_ms": 0, "longest_run_ms": 0, "sentences": 0, "reviews": 0, "distractions": 0})
        out.append({"date": day.isoformat(), **d, "counts": d["focused_ms"] >= 10 * 60_000 or d["reviews"] > 0})
    return out


def streak(days: list[dict]) -> int:
    """Low-day streak: a day counts with 10 focused minutes or any review. Today doesn't break it yet."""
    n = 0
    for i, d in enumerate(reversed(days)):
        if d["counts"]:
            n += 1
        elif i == 0:
            continue
        else:
            break
    return n


def home(db: DB, review_cap: int) -> dict:
    last = db.one(
        "SELECT s.*, d.title FROM sessions s JOIN documents d ON d.id=s.document_id"
        " WHERE s.deleted=0 AND d.deleted=0 ORDER BY s.updated_at DESC LIMIT 1"
    )
    resume = None
    doc = None
    if last:
        doc = db.one("SELECT id, title, position FROM documents WHERE id=?", (last["document_id"],))
    if not doc:
        doc = db.one(
            "SELECT id, title, position FROM documents WHERE deleted=0 AND status!='finished' ORDER BY updated_at DESC LIMIT 1"
        )
    if doc:
        sentence = db.scalar(
            "SELECT text FROM sentences WHERE document_id=? AND ord=?", (doc["id"], doc["position"])
        )
        resume = {
            "document_id": doc["id"],
            "title": doc["title"],
            "position": doc["position"],
            "sentence": sentence,
            "next_step": last["next_step"] if last and last["document_id"] == doc["id"] else "",
            "progress": key_sentence_stats(db, doc["id"]),
        }
    confusions = db.all(
        "SELECT h.id, h.document_id, h.sentence, h.text, d.title FROM highlights h JOIN documents d ON d.id=h.document_id"
        " WHERE h.type='confusing' AND h.resolved=0 AND h.deleted=0 AND d.deleted=0 ORDER BY h.created_at DESC LIMIT 5"
    )
    days = daily_stats(db, 14)
    due = due_cards(db, review_cap)
    return {
        "resume": resume,
        "confusions": confusions,
        "due_cards": min(due["due_total"], due["cap_left"]),
        "streak": streak(days),
        "today": days[-1],
    }


def queue(db: DB) -> list[dict]:
    docs = db.all(
        "SELECT id, title, source, source_type, why, deadline, status, position, total_sentences, import_warning, flags, tags,"
        " created_at, updated_at FROM documents WHERE deleted=0"
        " ORDER BY status='finished', deadline IS NULL, deadline, updated_at DESC"
    )
    for d in docs:
        d["progress"] = key_sentence_stats(db, d["id"])
        d["flags"] = (d["flags"] or "").split()  # hidden_text, instructions: the warning badge
        d["tags"] = (d["tags"] or "").split()  # your tags: also the collections of the Documents tab
    return docs


def weekly_review(db: DB) -> dict:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    finished = db.all("SELECT id, title FROM documents WHERE finished_at>=? AND deleted=0", (since,))
    explained = db.all(
        "SELECT q.text, q.answer, d.title FROM questions q JOIN documents d ON d.id=q.document_id"
        " WHERE q.answered_at>=? AND q.deleted=0 AND q.answer!='' ORDER BY q.answered_at DESC LIMIT 20",
        (since,),
    )
    open_conf = db.all(
        "SELECT h.text, h.document_id, h.sentence, d.title FROM highlights h JOIN documents d ON d.id=h.document_id"
        " WHERE h.type='confusing' AND h.resolved=0 AND h.deleted=0 ORDER BY h.created_at DESC LIMIT 20"
    )
    # Compass and growth: what moved, what you wrote down, how it felt
    since_day = (dt.date.today() - dt.timedelta(days=6)).isoformat()
    logs = db.all("SELECT * FROM day_logs WHERE day>=? AND deleted=0 ORDER BY day", (since_day,))
    steps = db.all(
        "SELECT s.title, s.output, q.title AS quest FROM quest_steps s JOIN quests q ON q.id=s.quest_id"
        " WHERE s.done_at>=? AND s.deleted=0 AND q.deleted=0 ORDER BY s.done_at",
        (since,),
    )
    quests_done = db.all("SELECT id, title FROM quests WHERE finished_at>=? AND deleted=0", (since,))
    feel = energy_feel(db, 28)
    attempts = db.all("SELECT result FROM practice_attempts WHERE created_at>=? AND deleted=0", (since,))
    practice = {r: sum(1 for a in attempts if a["result"] == r) for r in ("got", "partly", "missed")}
    habits = []
    for hb in db.all("SELECT id, title FROM habits WHERE deleted=0 AND archived=0 ORDER BY created_at"):
        days = db.scalar("SELECT COUNT(DISTINCT day) FROM habit_checks WHERE habit_id=? AND day>=? AND deleted=0", (hb["id"], since_day)) or 0
        habits.append({"title": hb["title"], "days": days})
    return {"finished": finished, "explained": explained, "open_confusions": open_conf, "logs": logs,
            "steps_done": steps, "quests_done": quests_done, "feel": feel, "practice": practice, "habits": habits}


def energy_feel(db: DB, days: int = 28) -> dict:
    """Energy drain log: which kinds of work leave you drained or energized (from the one-tap feel after sessions)."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    rows = db.all(
        "SELECT s.feel, COALESCE(st.title, d.title, NULLIF(s.question, ''), 'Session') AS what FROM sessions s"
        " LEFT JOIN quest_steps st ON st.id=s.step_id LEFT JOIN documents d ON d.id=s.document_id"
        " WHERE s.started_at>=? AND s.deleted=0 AND s.feel!=''",
        (since,),
    )
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"energized": 0, "neutral": 0, "drained": 0})
    for r in rows:
        counts[r["what"]][r["feel"]] += 1
    items = [{"what": k, **v} for k, v in counts.items()]
    drains = sorted((i for i in items if i["drained"]), key=lambda i: (-i["drained"], i["what"]))[:5]
    lifts = sorted((i for i in items if i["energized"]), key=lambda i: (-i["energized"], i["what"]))[:5]
    total = {f: sum(i[f] for i in items) for f in ("energized", "neutral", "drained")}
    return {"drains": drains, "lifts": lifts, "total": total}
