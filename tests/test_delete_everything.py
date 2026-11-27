"""Milestone 5.1 (docs/ai/PLAN.md, Phase 5): every kind of record you make, and every single AI result, can be removed,
with Undo. `DELETE /api/items/{kind}/{id}` is a soft delete; `POST /api/items/{kind}/{id}/restore` is the Undo.
The kind comes from a fixed list, never a table name; linked rows go and come back with their record."""
import datetime as dt
import json

import pytest

from readhold import services
from readhold.ai import results


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def _delete(client, kind, rid):
    return client.delete(f"/api/items/{kind}/{rid}")


def _restore(client, kind, rid):
    return client.post(f"/api/items/{kind}/{rid}/restore")


def _today():
    return dt.date.today().isoformat()


def _doc(client, sample_md):
    return _ok(client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}))


def _quest(client, title="Pass the exam"):
    return _ok(client.post("/api/quests", json={"title": title, "questions": ["How does attention work?"]}))


def _term_card(client, doc_id):
    term = _ok(client.post("/api/terms", json={"term": "SMR", "definition": "Sparse Mixture Router", "document_id": doc_id, "sentence": 0}))
    card = next(c for c in _ok(client.get("/api/cards")) if c["source_type"] == "term" and c["source_id"] == term["id"])
    return term, card


def _due_ids(client):
    return {c["id"] for c in _ok(client.get("/api/review/due"))["cards"]}


def _focus_run(client, minutes_done=30, todo_id=None):
    body = {"kind": "focus", "minutes": 25, **({"todo_id": todo_id} if todo_id else {})}
    run = _ok(client.post("/api/timer/start", json=body))
    _ok(client.post(f"/api/timer/{run['id']}/finish", json={"elapsed_ms": minutes_done * 60_000, "status": "done"}))
    return run


# ------------------------------------------------------------------ every kind, with how to make one and see it
def _make_card(client, db, sample_md):
    _, card = _term_card(client, _doc(client, sample_md)["id"])
    return card["id"], lambda: card["id"] in _due_ids(client)


def _make_habit(client, db, sample_md):
    hb = _ok(client.post("/api/habits", json={"title": "Review 5 cards", "anchor": "After coffee", "tiny": "Review 1 card"}))
    return hb["id"], lambda: hb["id"] in {x["id"] for x in _ok(client.get("/api/habits"))}


def _make_quest(client, db, sample_md):
    q = _quest(client)
    return q["id"], lambda: q["id"] in {x["id"] for x in _ok(client.get("/api/quests"))}


def _make_map_edge(client, db, sample_md):
    q = _quest(client)
    a = _ok(client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "softmax"}))["nodes"][0]
    m = _ok(client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "attention", "needs": [a["id"]]}))
    (edge,) = m["edges"]
    return edge["id"], lambda: edge["id"] in {e["id"] for e in _ok(client.get(f"/api/quests/{q['id']}/map"))["edges"]}


def _make_journal(client, db, sample_md):
    e = _ok(client.put(f"/api/journal/{_today()}", json={"weather": "sunny", "body": "A good day.", "prompts": []}))
    return e["id"], lambda: (_ok(client.get(f"/api/journal/{_today()}"))["entry"] or {}).get("id") == e["id"]


def _make_letter(client, db, sample_md):
    later = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    lt = _ok(client.post("/api/letters", json={"body": "Dear future me", "open_on": later}))
    return lt["id"], lambda: lt["id"] in {x["id"] for x in _ok(client.get("/api/letters"))["sealed"]}


def _make_side_quest(client, db, sample_md):
    s = _ok(client.post("/api/side-quests", json={"text": "Look up the GPU prices", "decision": "parked"}))
    return s["id"], lambda: s["id"] in {x["id"] for x in _ok(client.get("/api/side-quests"))}


def _make_checkin(client, db, sample_md):
    c = _ok(client.post("/api/checkins", json={"energy": "low"}))
    return c["id"], lambda: (_ok(client.get("/api/today"))["checkin"] or {}).get("id") == c["id"]


def _make_focus(client, db, sample_md):
    run = _focus_run(client)
    return run["id"], lambda: run["id"] in {x["id"] for x in _ok(client.get("/api/timer/recent"))}


def _make_ai_result(client, db, sample_md):
    doc = _doc(client, sample_md)
    res = results.keep(db, "explain", doc["id"], "some-key", {"status": "verified", "text": "An explanation"}, "explain_v1", "")
    return res["id"], lambda: client.get(f"/api/ai/why/{res['id']}").status_code == 200


MAKERS = {
    "card": _make_card, "habit": _make_habit, "quest": _make_quest, "map_edge": _make_map_edge, "journal": _make_journal,
    "letter": _make_letter, "side_quest": _make_side_quest, "checkin": _make_checkin, "focus": _make_focus, "ai_result": _make_ai_result,
}


@pytest.mark.parametrize("kind", sorted(MAKERS))
def test_each_kind_deletes_and_restores(client, db, sample_md, kind):
    rid, visible = MAKERS[kind](client, db, sample_md)
    assert visible()
    _ok(_delete(client, kind, rid))
    assert not visible()
    assert _delete(client, kind, rid).status_code == 404  # already deleted
    _ok(_restore(client, kind, rid))
    assert visible()
    _ok(_restore(client, kind, rid))  # a second Undo changes nothing
    assert visible()


@pytest.mark.parametrize("kind", sorted(MAKERS))
def test_an_unknown_id_or_a_bad_id_is_404(client, kind):
    for rid in ("0" * 32, "not-an-id", "A" * 32, "0" * 31, "0" * 33):
        assert _delete(client, kind, rid).status_code == 404
        assert _restore(client, kind, rid).status_code == 404


def test_an_unknown_kind_is_refused(client, db):
    hb = _ok(client.post("/api/habits", json={"title": "Stretch"}))
    for kind in ("habits", "documents", "users", "settings", "HABIT", "habit;", "sqlite_master", "x" * 200):
        assert _delete(client, kind, hb["id"]).status_code in (404, 422)
        assert _restore(client, kind, hb["id"]).status_code in (404, 422)
    assert db.one("SELECT deleted FROM habits WHERE id=?", (hb["id"],))["deleted"] == 0


def test_a_kind_only_restores_its_own_records(client, db):
    hb = _ok(client.post("/api/habits", json={"title": "Stretch"}))
    q = _quest(client)
    _ok(_delete(client, "habit", hb["id"]))
    assert _restore(client, "quest", hb["id"]).status_code == 404
    assert _delete(client, "quest", hb["id"]).status_code == 404
    assert db.one("SELECT deleted FROM habits WHERE id=?", (hb["id"],))["deleted"] == 1
    assert db.one("SELECT deleted FROM quests WHERE id=?", (q["id"],))["deleted"] == 0


def test_the_old_delete_routes_still_work_and_undo_through_the_new_one(client):
    hb = _ok(client.post("/api/habits", json={"title": "Stretch"}))
    _ok(client.delete(f"/api/habits/{hb['id']}"))
    assert hb["id"] not in {x["id"] for x in _ok(client.get("/api/habits"))}
    _ok(_restore(client, "habit", hb["id"]))
    assert hb["id"] in {x["id"] for x in _ok(client.get("/api/habits"))}
    q = _quest(client)
    _ok(client.delete(f"/api/quests/{q['id']}"))
    assert client.get(f"/api/quests/{q['id']}").status_code == 404
    _ok(_restore(client, "quest", q["id"]))
    assert _ok(client.get(f"/api/quests/{q['id']}"))["questions"][0]["text"] == "How does attention work?"  # its questions came back with it


# ------------------------------------------------------------------ review cards
def test_a_deleted_card_is_skipped_by_review_and_stays_deleted(client, db, sample_md):
    doc = _doc(client, sample_md)
    term, card = _term_card(client, doc["id"])
    assert card["id"] in _due_ids(client)
    _ok(_delete(client, "card", card["id"]))
    assert card["id"] not in _due_ids(client)
    assert client.post(f"/api/review/{card['id']}", json={"rating": 3}).status_code == 404  # a deleted card is not rated
    # editing what the card came from does not bring it back
    _ok(client.patch(f"/api/terms/{term['id']}", json={"definition": "The Sparse Mixture Router, a routing layer"}))
    assert card["id"] not in _due_ids(client)
    assert card["id"] not in {c["id"] for c in _ok(client.get("/api/cards"))}
    assert _ok(client.get("/api/library/counts"))["review_due"] == 0
    # Undo puts it back, with the new text
    _ok(_restore(client, "card", card["id"]))
    back = next(c for c in _ok(client.get("/api/review/due"))["cards"] if c["id"] == card["id"])
    assert "routing layer" in back["back"]


def test_a_card_removed_with_its_source_is_not_restored_by_hand(client, sample_md):
    doc = _doc(client, sample_md)
    term, card = _term_card(client, doc["id"])
    _ok(client.delete(f"/api/terms/{term['id']}"))  # the card went with its term, not by you
    assert _restore(client, "card", card["id"]).status_code == 404
    assert card["id"] not in _due_ids(client)


def test_an_ai_card_you_deleted_is_never_added_again(client, db, sample_md):
    doc = _doc(client, sample_md)
    card = services.upsert_card(db, "ai", "r1:0", "What is SMR?", "A router", doc["id"])
    _ok(_delete(client, "card", card["id"]))
    services.upsert_card(db, "ai", "r1:0", "What is SMR?", "A router", doc["id"])
    assert card["id"] not in _due_ids(client)


# ------------------------------------------------------------------ journal
def test_journal_delete_then_writing_that_day_again_works(client, db):
    day = _today()
    e = _ok(client.put(f"/api/journal/{day}", json={"weather": "rainy", "body": "First version", "prompts": [{"q": "Why?", "a": "Because"}]}))
    _ok(client.put(f"/api/ink/journal/{day}", json={"strokes": [{"tool": "pen", "points": [[0.1, 0.1], [0.2, 0.2]]}]}))
    _ok(_delete(client, "journal", e["id"]))
    page = _ok(client.get(f"/api/journal/{day}"))
    assert page["entry"] is None and all(r["day"] != day for r in page["recent"])
    assert _ok(client.get(f"/api/ink/journal/{day}"))["strokes"] == []  # the drawing on the page went with it
    # Undo brings back the words and the drawing
    back = _ok(_restore(client, "journal", e["id"]))
    assert back["entry"]["body"] == "First version" and back["entry"]["prompts"] == [{"q": "Why?", "a": "Because"}]
    assert len(_ok(client.get(f"/api/ink/journal/{day}"))["strokes"]) == 1
    # delete again, then write a new page for the same day: the UNIQUE day is no obstacle
    _ok(_delete(client, "journal", e["id"]))
    again = _ok(client.put(f"/api/journal/{day}", json={"weather": "sunny", "body": "Second version", "prompts": []}))
    assert again["body"] == "Second version" and again["weather"] == "sunny" and again["prompts"] == []
    assert _ok(client.get(f"/api/journal/{day}"))["entry"]["body"] == "Second version"
    assert db.scalar("SELECT COUNT(*) FROM journal_entries WHERE day=?", (day,)) == 1
    _ok(_restore(client, "journal", e["id"]))  # a late Undo does not overwrite what you wrote since
    assert _ok(client.get(f"/api/journal/{day}"))["entry"]["body"] == "Second version"


def test_a_deleted_habit_leaves_the_day_story(client):
    hb = _ok(client.post("/api/habits", json={"title": "Stretch"}))
    _ok(client.post(f"/api/habits/{hb['id']}/check"))
    assert any("Stretch" in s["text"] for s in _ok(client.get(f"/api/journal/{_today()}"))["story"])
    _ok(_delete(client, "habit", hb["id"]))
    assert not any("Stretch" in s["text"] for s in _ok(client.get(f"/api/journal/{_today()}"))["story"])


def test_letters_opened_or_sealed_can_go(client, db):
    later = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    lt = _ok(client.post("/api/letters", json={"body": "Dear future me", "open_on": later}))
    assert _ok(client.get(f"/api/journal/{_today()}"))["letters_sealed"] == 1
    _ok(_delete(client, "letter", lt["id"]))
    assert _ok(client.get(f"/api/journal/{_today()}"))["letters_sealed"] == 0
    assert client.post(f"/api/letters/{lt['id']}/open").status_code == 404
    _ok(_restore(client, "letter", lt["id"]))
    assert _ok(client.get(f"/api/journal/{_today()}"))["letters_sealed"] == 1


# ------------------------------------------------------------------ focus sessions
def test_deleting_a_focus_run_takes_its_session_out_of_the_stats_and_undo_brings_both_back(client, db):
    todo = _ok(client.post("/api/todos", json={"text": "Read chapter 3", "minutes": 25}))
    run = _focus_run(client, 30, todo["id"])
    session_id = run["session_id"]
    stats = lambda: _ok(client.get("/api/stats"))["days"][-1]["focused_ms"]
    spent = lambda: db.one("SELECT spent_ms FROM todos WHERE id=?", (todo["id"],))["spent_ms"]
    assert stats() == 30 * 60_000 and spent() == 30 * 60_000
    assert _ok(client.get("/api/timer"))["today"]["focus_ms"] == 30 * 60_000
    assert any(s["kind"] == "session" for s in _ok(client.get(f"/api/journal/{_today()}"))["story"])
    _ok(_delete(client, "focus", run["id"]))
    assert db.one("SELECT deleted FROM sessions WHERE id=?", (session_id,))["deleted"] == 1
    assert stats() == 0 and spent() == 0
    assert _ok(client.get("/api/timer"))["today"] == {"focus_ms": 0, "runs": 0, "todos_done": 0}
    assert _ok(client.get("/api/today"))["output"]["focused_ms"] == 0
    assert not any(s["kind"] == "session" for s in _ok(client.get(f"/api/journal/{_today()}"))["story"])
    _ok(_restore(client, "focus", run["id"]))
    assert db.one("SELECT deleted FROM sessions WHERE id=?", (session_id,))["deleted"] == 0
    assert stats() == 30 * 60_000 and spent() == 30 * 60_000
    _ok(_restore(client, "focus", run["id"]))  # Undo twice: the time is not counted twice
    assert spent() == 30 * 60_000


def test_a_running_timer_cannot_be_deleted(client, db):
    run = _ok(client.post("/api/timer/start", json={"kind": "focus", "minutes": 25}))
    r = _delete(client, "focus", run["id"])
    assert r.status_code == 409 and "Stop it first" in r.json()["detail"]
    assert db.one("SELECT deleted FROM timer_runs WHERE id=?", (run["id"],))["deleted"] == 0
    assert db.one("SELECT deleted FROM sessions WHERE id=?", (run["session_id"],))["deleted"] == 0
    assert _ok(client.get("/api/timer"))["run"]["id"] == run["id"]


def test_recent_focus_sessions_lists_finished_runs_only(client):
    brk = _ok(client.post("/api/timer/start", json={"kind": "break", "minutes": 5}))
    _ok(client.post(f"/api/timer/{brk['id']}/finish", json={"elapsed_ms": 60_000}))
    done = _focus_run(client, 10)
    running = _ok(client.post("/api/timer/start", json={"kind": "stopwatch"}))
    recent = _ok(client.get("/api/timer/recent"))
    assert [x["id"] for x in recent] == [done["id"]]  # no break, not the one still running
    assert recent[0]["elapsed_ms"] == 10 * 60_000 and recent[0]["kind"] == "focus"
    assert running["id"] not in {x["id"] for x in recent}


# ------------------------------------------------------------------ AI results
def test_a_deleted_ai_result_is_not_found_and_undo_brings_it_back(client, db, sample_md):
    doc = _doc(client, sample_md)
    res = results.keep(db, "explain", doc["id"], "key-1", {"status": "verified"}, "explain_v1", "")
    assert client.get(f"/api/ai/why/{res['id']}").status_code == 200
    _ok(_delete(client, "ai_result", res["id"]))
    assert client.get(f"/api/ai/why/{res['id']}").status_code == 404
    assert results.find(db, "explain", doc["id"], "key-1") is None  # the feature's box shows nothing now
    _ok(_restore(client, "ai_result", res["id"]))
    assert results.find(db, "explain", doc["id"], "key-1")["id"] == res["id"]


def test_an_ai_result_about_a_removed_document_is_not_restored(client, db, sample_md):
    doc = _doc(client, sample_md)
    res = results.keep(db, "explain", doc["id"], "key-1", {"status": "verified"}, "explain_v1", "")
    _ok(_delete(client, "ai_result", res["id"]))
    _ok(client.delete(f"/api/documents/{doc['id']}"))
    assert _restore(client, "ai_result", res["id"]).status_code == 404
    results.clear_all(db)  # Clear AI history deletes for good: nothing to restore
    assert _restore(client, "ai_result", res["id"]).status_code == 404


# ------------------------------------------------------------------ links, quests, check-ins
def test_restoring_a_map_link_that_would_make_a_loop_is_refused(client):
    q = _quest(client)
    a = _ok(client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "softmax"}))["nodes"][0]
    m = _ok(client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "attention", "needs": [a["id"]]}))
    b = next(n for n in m["nodes"] if n["name"] == "attention")
    (edge,) = m["edges"]
    _ok(_delete(client, "map_edge", edge["id"]))
    _ok(client.post(f"/api/quests/{q['id']}/map/edges", json={"from_id": b["id"], "to_id": a["id"]}))  # the other way round now
    assert _restore(client, "map_edge", edge["id"]).status_code == 409
    # a link whose concept is gone is not restored either
    _ok(client.delete(f"/api/map-nodes/{a['id']}"))
    assert _restore(client, "map_edge", edge["id"]).status_code in (404, 409)


def test_a_restored_goal_does_not_push_out_the_main_goal(client):
    old = _quest(client, "Old goal")
    _ok(_delete(client, "quest", old["id"]))
    new = _quest(client, "New goal")
    _ok(_restore(client, "quest", old["id"]))
    assert _ok(client.get("/api/quest/active"))["id"] == new["id"]
    assert _ok(client.get(f"/api/quests/{old['id']}"))["status"] == "parked"


def test_removing_a_checkin_brings_back_the_earlier_one_of_today(client):
    first = _ok(client.post("/api/checkins", json={"energy": "low"}))
    second = _ok(client.post("/api/checkins", json={"energy": "high"}))
    assert _ok(client.get("/api/today"))["checkin"]["id"] == second["id"]
    _ok(_delete(client, "checkin", second["id"]))
    assert _ok(client.get("/api/today"))["checkin"]["id"] == first["id"]
    assert _ok(client.get("/api/ambience"))["energy_today"] == "low"


def test_a_deleted_side_quest_is_not_counted_as_parked(client):
    s = _ok(client.post("/api/side-quests", json={"text": "Read about GPUs", "decision": "parked"}))
    assert _ok(client.get("/api/today"))["parked"] == 1
    _ok(_delete(client, "side_quest", s["id"]))
    assert _ok(client.get("/api/today"))["parked"] == 0


# ------------------------------------------------------------------ exports keep ignoring deleted rows
def test_the_export_leaves_out_what_you_deleted(client, db, home):
    hb = _ok(client.post("/api/habits", json={"title": "Stretch"}))
    run = _focus_run(client, 5)
    lt = _ok(client.post("/api/letters", json={"body": "Dear me", "open_on": (dt.date.today() + dt.timedelta(days=9)).isoformat()}))
    for kind, rid in (("habit", hb["id"]), ("focus", run["id"]), ("letter", lt["id"])):
        _ok(_delete(client, kind, rid))
    path = _ok(client.post("/api/export/all"))["path"]
    data = json.loads(open(path, encoding="utf-8").read())
    assert hb["id"] not in {r["id"] for r in data["habits"]}
    assert run["id"] not in {r["id"] for r in data["timer_runs"]}
    assert run["session_id"] not in {r["id"] for r in data["sessions"]}
    assert lt["id"] not in {r["id"] for r in data["letters"]}
