"""Growth: understand in the right order, notice your gaps, close the day, keep tiny habits.

- Topic map: the concepts a quest needs, what each one depends on, and whether you can explain it
  (new → shaky → solid). "Learn next" is the first concept whose prerequisites you can already explain.
- Teach-back: explain a quest question from memory; every gap you name becomes a step.
- Day log: three lines a day (did, learned, next). "Next" becomes tomorrow's lead step.
- Tiny habits: tied to something you already do, with a 2-minute version, and "never miss twice":
  one missed day doesn't break the streak, two in a row do.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .bodies import Body
from .db import DB, now

Status = Literal["new", "shaky", "solid"]


def _today() -> dt.date:
    return dt.date.today()


# ------------------------------------------------------------------ topic map
def topic_map(db: DB, quest_id: str) -> dict:
    nodes = db.all("SELECT * FROM map_nodes WHERE quest_id=? AND deleted=0 ORDER BY created_at", (quest_id,))
    ids = {n["id"] for n in nodes}
    edges = [
        e for e in db.all("SELECT * FROM map_edges WHERE quest_id=? AND deleted=0", (quest_id,))
        if e["from_id"] in ids and e["to_id"] in ids
    ]
    needs: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        needs[e["to_id"]].append(e["from_id"])
    depth: dict[str, int] = {}

    def depth_of(nid: str, seen: frozenset = frozenset()) -> int:
        if nid in depth:
            return depth[nid]
        if nid in seen:
            return 0
        d = 1 + max((depth_of(p, seen | {nid}) for p in needs[nid]), default=-1)
        depth[nid] = d
        return d

    status = {n["id"]: n["status"] for n in nodes}
    for n in nodes:
        n["depth"] = depth_of(n["id"])
        n["needs"] = needs[n["id"]]
        n["ready"] = all(status[p] == "solid" for p in needs[n["id"]])
    candidates = [n for n in nodes if n["status"] != "solid" and n["ready"]]
    # shaky before new (you've started it), shallow before deep (foundations first)
    candidates.sort(key=lambda n: (n["status"] != "shaky", n["depth"], n["created_at"]))
    solid = sum(1 for n in nodes if n["status"] == "solid")
    return {"nodes": nodes, "edges": edges, "next": candidates[0] if candidates else None,
            "progress": {"solid": solid, "total": len(nodes)}}


def _creates_cycle(db: DB, quest_id: str, from_id: str, to_id: str) -> bool:
    """Would "to needs from" make a loop? True when `from` already (indirectly) needs `to`."""
    needs: dict[str, list[str]] = {}
    for e in db.all("SELECT from_id, to_id FROM map_edges WHERE quest_id=? AND deleted=0", (quest_id,)):
        needs.setdefault(e["to_id"], []).append(e["from_id"])
    stack, seen = [from_id], set()
    while stack:
        cur = stack.pop()
        if cur == to_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(needs.get(cur, []))
    return False


# ------------------------------------------------------------------ habits
def habit_state(db: DB, habit: dict, today: dt.date | None = None, days: set[str] | None = None) -> dict:
    today = today or _today()
    if days is None:
        days = {r["day"] for r in db.all("SELECT day FROM habit_checks WHERE habit_id=? AND deleted=0", (habit["id"],))}
    done_today = today.isoformat() in days
    # never miss twice: walk back from today (or yesterday, if today isn't done yet)
    streak, misses, d = 0, 0, today if done_today else today - dt.timedelta(days=1)
    created = dt.datetime.fromisoformat(habit["created_at"]).astimezone().date()
    while d >= created:
        if d.isoformat() in days:
            streak += 1
            misses = 0
        else:
            misses += 1
            if misses >= 2:
                break
        d -= dt.timedelta(days=1)
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    last14 = [(today - dt.timedelta(days=i)).isoformat() in days for i in range(13, -1, -1)]
    return {
        **habit,
        "done_today": done_today,
        "streak": streak,
        "missed_yesterday": yesterday not in days and created < today,
        "last14": last14,
    }


def habits(db: DB) -> list[dict]:
    rows = db.all("SELECT * FROM habits WHERE deleted=0 AND archived=0 ORDER BY created_at")
    by_habit: dict[str, set[str]] = {h["id"]: set() for h in rows}
    for r in db.all(
        "SELECT c.habit_id, c.day FROM habit_checks c JOIN habits h ON h.id=c.habit_id"
        " WHERE c.deleted=0 AND h.deleted=0 AND h.archived=0"
    ):
        by_habit.setdefault(r["habit_id"], set()).add(r["day"])
    return [habit_state(db, h, days=by_habit[h["id"]]) for h in rows]


def log_today(db: DB) -> dict | None:
    return db.one("SELECT * FROM day_logs WHERE day=? AND deleted=0 ORDER BY updated_at DESC LIMIT 1", (_today().isoformat(),))


# ------------------------------------------------------------------ mixed practice
def practice_items(db: DB, n: int = 10) -> list[dict]:
    """A short, mixed set: answered quest questions, answered paper questions and defined terms,
    interleaved across topics (switching topics is what makes practice stick). Items you missed
    last time come first in their topic; then the ones practised longest ago."""
    pool: list[dict] = []
    for r in db.all(
        "SELECT qq.id, qq.text, qq.answer, q.id AS topic_id, q.title AS topic FROM quest_questions qq"
        " JOIN quests q ON q.id=qq.quest_id WHERE qq.deleted=0 AND q.deleted=0 AND qq.answer!=''"
    ):
        pool.append({"source_type": "quest_question", "source_id": r["id"], "prompt": r["text"], "answer": r["answer"],
                     "topic": r["topic"], "topic_id": f"quest:{r['topic_id']}"})
    for r in db.all(
        "SELECT q.id, q.text, q.answer, d.id AS topic_id, d.title AS topic FROM questions q"
        " JOIN documents d ON d.id=q.document_id WHERE q.deleted=0 AND d.deleted=0 AND q.answer!=''"
    ):
        pool.append({"source_type": "question", "source_id": r["id"], "prompt": r["text"], "answer": r["answer"],
                     "topic": r["topic"], "topic_id": f"doc:{r['topic_id']}"})
    for r in db.all(
        "SELECT t.id, t.term, t.definition, t.document_id, d.title FROM terms t LEFT JOIN documents d ON d.id=t.document_id"
        " WHERE t.deleted=0 AND t.definition!=''"
    ):
        pool.append({"source_type": "term", "source_id": r["id"], "prompt": f"What does “{r['term']}” mean?",
                     "answer": r["definition"], "topic": r["title"] or "Glossary",
                     "topic_id": f"doc:{r['document_id']}" if r["document_id"] else "glossary"})
    if not pool:
        return []
    last: dict[str, dict] = {}
    for a in db.all("SELECT source_id, result, created_at FROM practice_attempts WHERE deleted=0 ORDER BY created_at"):
        last[a["source_id"]] = a  # latest attempt wins
    for it in pool:
        a = last.get(it["source_id"])
        it["last_result"] = a["result"] if a else None
        it["_key"] = (0 if a and a["result"] == "missed" else 1 if a and a["result"] == "partly" else 2 if not a else 3,
                      a["created_at"] if a else "")
    groups: dict[str, list[dict]] = {}
    for it in sorted(pool, key=lambda i: i["_key"]):
        groups.setdefault(it["topic_id"], []).append(it)
    order = sorted(groups, key=lambda g: groups[g][0]["_key"])  # the topic with the weakest item starts
    out: list[dict] = []
    while len(out) < n and any(groups[g] for g in order):
        for g in order:  # round-robin: never two in a row from the same topic while others remain
            if groups[g] and len(out) < n:
                out.append(groups[g].pop(0))
    for it in out:
        it.pop("_key", None)
    return out


class AttemptIn(Body):
    source_type: Literal["quest_question", "question", "term"]
    source_id: str = Field(min_length=1, max_length=64)
    result: Literal["got", "partly", "missed"]


# ------------------------------------------------------------------ request bodies
class NodeIn(Body):
    name: str = Field(min_length=1, max_length=200)
    needs: list[str] = Field(default_factory=list, max_length=20)  # ids of prerequisites


class NodePatch(Body):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Status | None = None
    note: str | None = Field(None, max_length=2000)


class EdgeIn(BaseModel):
    from_id: str
    to_id: str


class TeachIn(Body):
    explanation: str = Field(min_length=1, max_length=20000)
    gaps: list[str] = Field(default_factory=list, max_length=20)
    replace: bool = False  # keep this explanation as the answer, in place of the saved one


class LogIn(BaseModel):
    did: str = Field("", max_length=1000)
    learned: str = Field("", max_length=1000)
    next: str = Field("", max_length=300)
    next_as_lead: bool = True


class HabitIn(Body):
    title: str = Field(min_length=1, max_length=200)
    anchor: str = Field("", max_length=200)
    tiny: str = Field("", max_length=200)


class HabitPatch(Body):
    title: str | None = Field(None, min_length=1, max_length=200)
    anchor: str | None = Field(None, max_length=200)
    tiny: str | None = Field(None, max_length=200)
    archived: bool | None = None


# ------------------------------------------------------------------ routes
def register(app: FastAPI, db: DB) -> None:
    from .compass import active_quest, clear_lead, need_row

    def need(table: str, row_id: str) -> dict:
        return need_row(db, table, row_id)

    # ---- topic map
    @app.get("/api/quests/{quest_id}/map")
    def api_map(quest_id: str):
        need("quests", quest_id)
        return topic_map(db, quest_id)

    @app.post("/api/quests/{quest_id}/map/nodes")
    def api_node_create(quest_id: str, body: NodeIn):
        need("quests", quest_id)
        node = db.insert("map_nodes", {"quest_id": quest_id, "name": body.name.strip()})
        for pre in body.needs:
            if db.one("SELECT 1 FROM map_nodes WHERE id=? AND quest_id=? AND deleted=0", (pre, quest_id)):
                db.insert("map_edges", {"quest_id": quest_id, "from_id": pre, "to_id": node["id"]})
        return topic_map(db, quest_id)

    @app.post("/api/quests/{quest_id}/map/seed")
    def api_map_seed(quest_id: str):
        """Start the map from the concepts in the documents this quest reads."""
        need("quests", quest_id)
        docs = [r["id"] for r in db.all(
            "SELECT DISTINCT d.id FROM documents d WHERE d.deleted=0 AND (d.quest_question_id IN"
            " (SELECT id FROM quest_questions WHERE quest_id=? AND deleted=0)"
            " OR d.id IN (SELECT document_id FROM quest_steps WHERE quest_id=? AND deleted=0))",
            (quest_id, quest_id),
        )]
        have = {n["name"].lower() for n in db.all("SELECT name FROM map_nodes WHERE quest_id=? AND deleted=0", (quest_id,))}
        added = 0
        if docs:
            marks = ",".join("?" for _ in docs)
            for t in db.all(
                f"SELECT term FROM terms WHERE deleted=0 AND document_id IN ({marks})"
                " GROUP BY lower(term) ORDER BY MAX(is_concept) DESC, COUNT(*) DESC LIMIT 12",
                docs,
            ):
                if t["term"].lower() not in have:
                    db.insert("map_nodes", {"quest_id": quest_id, "name": t["term"]})
                    have.add(t["term"].lower())
                    added += 1
        return {**topic_map(db, quest_id), "added": added}

    @app.patch("/api/map-nodes/{node_id}")
    def api_node_patch(node_id: str, body: NodePatch):
        node = need("map_nodes", node_id)
        db.update("map_nodes", node_id, body.model_dump(exclude_none=True))
        return topic_map(db, node["quest_id"])

    @app.delete("/api/map-nodes/{node_id}")
    def api_node_delete(node_id: str):
        node = need("map_nodes", node_id)
        db.soft_delete("map_nodes", node_id)
        for e in db.all("SELECT id FROM map_edges WHERE (from_id=? OR to_id=?) AND deleted=0", (node_id, node_id)):
            db.soft_delete("map_edges", e["id"])
        return topic_map(db, node["quest_id"])

    @app.post("/api/quests/{quest_id}/map/edges")
    def api_edge_create(quest_id: str, body: EdgeIn):
        need("quests", quest_id)
        for nid in (body.from_id, body.to_id):
            if not db.one("SELECT 1 FROM map_nodes WHERE id=? AND quest_id=? AND deleted=0", (nid, quest_id)):
                raise HTTPException(404, "concept not found")
        if body.from_id == body.to_id or _creates_cycle(db, quest_id, body.from_id, body.to_id):
            raise HTTPException(409, "That would make a loop: one of them already needs the other.")
        if not db.one("SELECT 1 FROM map_edges WHERE from_id=? AND to_id=? AND deleted=0", (body.from_id, body.to_id)):
            db.insert("map_edges", {"quest_id": quest_id, "from_id": body.from_id, "to_id": body.to_id})
        return topic_map(db, quest_id)

    @app.delete("/api/map-edges/{edge_id}")
    def api_edge_delete(edge_id: str):
        edge = need("map_edges", edge_id)
        db.soft_delete("map_edges", edge_id)
        return topic_map(db, edge["quest_id"])

    # ---- teach-back
    @app.post("/api/quest-questions/{qq_id}/teachback")
    def api_teachback(qq_id: str, body: TeachIn):
        """Your explanation from memory; each gap you name becomes a step that moves this question."""
        q = need("quest_questions", qq_id)
        fields: dict = {}
        if not q["answer"].strip() or body.replace:  # a saved answer is only replaced when you ask for it
            fields = {"answer": body.explanation.strip(), "answered_at": q["answered_at"] or now()}  # the day it was first answered stays
        if fields:
            db.update("quest_questions", qq_id, fields)
        n = db.scalar("SELECT COUNT(*) FROM quest_steps WHERE quest_id=? AND deleted=0", (q["quest_id"],)) or 0
        steps = []
        for i, gap in enumerate(g.strip() for g in body.gaps):
            if not gap:
                continue
            steps.append(db.insert("quest_steps", {
                "quest_id": q["quest_id"], "question_id": qq_id, "ord": n + i, "minutes": 15,
                "title": f"Fill the gap: {gap}",
                "low": f"Find one sentence that explains {gap}",
                "high": f"Explain {gap} aloud, then add it to your answer",
            }))
        return {"question": need("quest_questions", qq_id), "steps": steps}

    # ---- day log
    @app.get("/api/logs")
    def api_logs(quest_id: str | None = None, days: int = 14):
        since = (_today() - dt.timedelta(days=max(1, min(days, 365)))).isoformat()
        if quest_id:
            return db.all("SELECT * FROM day_logs WHERE quest_id=? AND day>=? AND deleted=0 ORDER BY day DESC", (quest_id, since))
        return db.all("SELECT * FROM day_logs WHERE day>=? AND deleted=0 ORDER BY day DESC", (since,))

    @app.post("/api/logs")
    def api_log_save(body: LogIn):
        """Close the day: one log per day (saving again updates it). "Next" becomes tomorrow's lead step."""
        q = active_quest(db)
        row = {"did": body.did.strip(), "learned": body.learned.strip(), "next": body.next.strip(),
               "quest_id": q["id"] if q else None}
        existing = log_today(db)
        if existing:
            db.update("day_logs", existing["id"], row)
            log = need("day_logs", existing["id"])
        else:
            log = db.insert("day_logs", {**row, "day": _today().isoformat()})
        step = None
        if q and row["next"] and body.next_as_lead:
            same = db.one("SELECT id FROM quest_steps WHERE quest_id=? AND title=? AND done_at IS NULL AND deleted=0",
                          (q["id"], row["next"]))
            clear_lead(db, q["id"])
            if same:
                db.update("quest_steps", same["id"], {"lead": 1})
                step = need("quest_steps", same["id"])
            else:
                n = db.scalar("SELECT COUNT(*) FROM quest_steps WHERE quest_id=? AND deleted=0", (q["id"],)) or 0
                step = db.insert("quest_steps", {"quest_id": q["id"], "title": row["next"], "ord": n, "lead": 1, "minutes": 20})
        return {"log": log, "step": step}

    # ---- habits
    @app.get("/api/habits")
    def api_habits():
        return habits(db)

    @app.post("/api/habits")
    def api_habit_create(body: HabitIn):
        return habit_state(db, db.insert("habits", {k: v.strip() for k, v in body.model_dump().items()}))

    @app.patch("/api/habits/{habit_id}")
    def api_habit_patch(habit_id: str, body: HabitPatch):
        need("habits", habit_id)
        fields = body.model_dump(exclude_none=True)
        if "archived" in fields:
            fields["archived"] = int(fields["archived"])
        db.update("habits", habit_id, fields)
        return habit_state(db, need("habits", habit_id))

    @app.delete("/api/habits/{habit_id}")
    def api_habit_delete(habit_id: str):
        need("habits", habit_id)
        db.soft_delete("habits", habit_id)
        return {"ok": True}

    @app.post("/api/habits/{habit_id}/check")
    def api_habit_check(habit_id: str):
        """Toggle today's check."""
        habit = need("habits", habit_id)
        day = _today().isoformat()
        row = db.one("SELECT id FROM habit_checks WHERE habit_id=? AND day=? AND deleted=0", (habit_id, day))
        if row:
            db.soft_delete("habit_checks", row["id"])
        else:
            db.insert("habit_checks", {"habit_id": habit_id, "day": day})
        return habit_state(db, habit)

    # ---- mixed practice
    @app.get("/api/practice")
    def api_practice(n: int = 10):
        return practice_items(db, max(1, min(n, 30)))

    @app.post("/api/practice")
    def api_practice_attempt(body: AttemptIn):
        return db.insert("practice_attempts", body.model_dump())
