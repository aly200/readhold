"""Growth: topic map order, teach-back gaps → steps, day log → tomorrow's lead step, never-miss-twice habits."""
import datetime as dt


def _quest(client):
    return client.post("/api/quests", json={"title": "Understand transformers", "questions": ["How does attention work?"]}).json()


def test_topic_map_learn_next_follows_prerequisites(client):
    q = _quest(client)
    m = client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "Dot product"}).json()
    dot = m["nodes"][0]["id"]
    m = client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "Softmax"}).json()
    soft = next(n["id"] for n in m["nodes"] if n["name"] == "Softmax")
    m = client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "Attention", "needs": [dot, soft]}).json()
    att = next(n for n in m["nodes"] if n["name"] == "Attention")
    assert att["depth"] == 1 and set(att["needs"]) == {dot, soft} and att["ready"] is False
    assert m["next"]["name"] == "Dot product"  # foundations first
    client.patch(f"/api/map-nodes/{soft}", json={"status": "shaky"})
    assert client.get(f"/api/quests/{q['id']}/map").json()["next"]["name"] == "Softmax"  # started beats new
    client.patch(f"/api/map-nodes/{dot}", json={"status": "solid"})
    m = client.patch(f"/api/map-nodes/{soft}", json={"status": "solid"}).json()
    assert m["next"]["name"] == "Attention"  # ready once its prerequisites are solid
    assert m["progress"] == {"solid": 2, "total": 3}


def test_topic_map_refuses_loops(client):
    q = _quest(client)
    a = client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "A"}).json()["nodes"][0]["id"]
    m = client.post(f"/api/quests/{q['id']}/map/nodes", json={"name": "B", "needs": [a]}).json()
    b = next(n["id"] for n in m["nodes"] if n["name"] == "B")
    r = client.post(f"/api/quests/{q['id']}/map/edges", json={"from_id": b, "to_id": a})
    assert r.status_code == 409 and "loop" in r.json()["detail"]
    assert client.post(f"/api/quests/{q['id']}/map/edges", json={"from_id": a, "to_id": a}).status_code == 409
    # deleting a concept removes its links
    m = client.delete(f"/api/map-nodes/{a}").json()
    assert [n["name"] for n in m["nodes"]] == ["B"] and m["edges"] == []


def test_map_seed_from_quest_reading(client, sample_md):
    q = _quest(client)
    doc = client.post("/api/import/text", json={"title": "Notes", "text": sample_md, "format": "markdown"}).json()
    client.post(f"/api/quests/{q['id']}/steps", json={"title": "Read the notes", "document_id": doc["id"]})
    m = client.post(f"/api/quests/{q['id']}/map/seed").json()
    assert m["added"] >= 1 and "top-k" in [n["name"] for n in m["nodes"]]
    again = client.post(f"/api/quests/{q['id']}/map/seed").json()
    assert again["added"] == 0  # no duplicates


def test_teachback_saves_answer_and_turns_gaps_into_steps(client):
    q = _quest(client)
    qq = q["questions"][0]["id"]
    r = client.post(f"/api/quest-questions/{qq}/teachback",
                    json={"explanation": "Queries match keys; values are mixed by those weights.", "gaps": ["why scale by √d_k", " ", "masking"]}).json()
    assert r["question"]["answer"].startswith("Queries match keys")
    assert [s["title"] for s in r["steps"]] == ["Fill the gap: why scale by √d_k", "Fill the gap: masking"]
    assert all(s["question_id"] == qq for s in r["steps"])
    # a second teach-back keeps the first answer
    r2 = client.post(f"/api/quest-questions/{qq}/teachback", json={"explanation": "Different words."}).json()
    assert r2["question"]["answer"].startswith("Queries match keys") and r2["steps"] == []


def test_day_log_once_per_day_and_next_becomes_lead(client):
    q = _quest(client)
    r = client.post("/api/logs", json={"did": "Read 3.2", "learned": "Heads attend to different things", "next": "Recall Q1 cold"}).json()
    assert r["step"]["title"] == "Recall Q1 cold" and r["step"]["lead"] == 1
    r2 = client.post("/api/logs", json={"did": "Read 3.2 and 3.3", "learned": "", "next": "Recall Q1 cold"}).json()
    assert r2["log"]["id"] == r["log"]["id"] and r2["log"]["did"] == "Read 3.2 and 3.3"  # updated, not duplicated
    t = client.get("/api/today").json()
    assert t["quest"]["lead"]["title"] == "Recall Q1 cold"
    assert len([s for s in t["quest"]["steps"] if s["title"] == "Recall Q1 cold"]) == 1
    assert t["log_today"]["did"] == "Read 3.2 and 3.3"
    assert len(client.get(f"/api/logs?quest_id={q['id']}").json()) == 1


def test_habit_check_toggles_today(client):
    h = client.post("/api/habits", json={"title": "Review 5 cards", "anchor": "After morning coffee", "tiny": "Review 1 card"}).json()
    assert h["done_today"] is False and h["streak"] == 0
    h = client.post(f"/api/habits/{h['id']}/check").json()
    assert h["done_today"] is True and h["streak"] == 1
    h = client.post(f"/api/habits/{h['id']}/check").json()  # tap again to undo
    assert h["done_today"] is False
    assert client.get("/api/today").json()["habits"][0]["title"] == "Review 5 cards"


def test_never_miss_twice(db):
    from readhold.growth import habit_state

    today = dt.date(2026, 11, 20)
    habit = db.insert("habits", {"title": "Read", "created_at": "2026-11-01T08:00:00.000+00:00"})
    for d in (19, 17, 16, 13):  # missed 18 (once: fine), missed 15 and 14 (twice: streak stops there)
        db.insert("habit_checks", {"habit_id": habit["id"], "day": f"2026-11-{d:02d}"})
    s = habit_state(db, habit, today)
    assert s["done_today"] is False and s["missed_yesterday"] is False
    assert s["streak"] == 3  # 19, 17, 16
    db.insert("habit_checks", {"habit_id": habit["id"], "day": "2026-11-20"})
    assert habit_state(db, habit, today)["streak"] == 4
    assert habit_state(db, habit, dt.date(2026, 11, 22))["missed_yesterday"] is True
