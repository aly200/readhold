"""Compass: main quest, its questions and steps, energy check-ins, side quests, and real output."""
import datetime as dt


def _quest(client, title="Pass the transformers exam", questions=("How does attention work?", "Why multi-head?", "What limits it?")):
    r = client.post("/api/quests", json={"title": title, "why": "Thursday exam", "done_looks_like": "3 answers from memory",
                                         "questions": list(questions)})
    assert r.status_code == 200, r.text
    return r.json()


def test_today_without_a_quest(client):
    t = client.get("/api/today").json()
    assert t["quest"] is None
    assert t["energy"]["learning"] is True
    assert t["output"] == {"answers": 0, "steps": 0, "empty_sessions": 0, "focused_ms": 0, "on_quest_ms": 0,
                           "on_quest_ratio": None}


def test_one_main_quest_at_a_time(client):
    first = _quest(client, "First")
    second = _quest(client, "Second")
    t = client.get("/api/today").json()
    assert t["quest"]["id"] == second["id"]
    assert client.get(f"/api/quests/{first['id']}").json()["status"] == "parked"  # parked, never lost
    client.patch(f"/api/quests/{first['id']}", json={"status": "active"})
    assert client.get("/api/today").json()["quest"]["id"] == first["id"]
    assert client.get(f"/api/quests/{second['id']}").json()["status"] == "parked"


def test_questions_steps_lead_and_progress(client):
    q = _quest(client)
    assert [x["text"] for x in q["questions"]] == ["How does attention work?", "Why multi-head?", "What limits it?"]
    q1 = q["questions"][0]["id"]
    a = client.post(f"/api/quests/{q['id']}/steps", json={"title": "Read section 3.2", "question_id": q1}).json()
    b = client.post(f"/api/quests/{q['id']}/steps", json={"title": "Recall Q2 without notes", "low": "Write 1 line",
                                                          "high": "Explain it to a friend", "minutes": 25, "lead": True}).json()
    t = client.get("/api/today").json()
    assert t["quest"]["lead"]["id"] == b["id"]  # the marked lead step comes first
    # marking another step as lead moves the mark
    client.patch(f"/api/quest-steps/{a['id']}", json={"lead": True})
    assert client.get("/api/today").json()["quest"]["lead"]["id"] == a["id"]
    # finishing it: the lead falls to the next open step, output counts today
    client.patch(f"/api/quest-steps/{a['id']}", json={"done": True, "output": "notes on scaled dot-product"})
    t = client.get("/api/today").json()
    assert t["quest"]["lead"]["id"] == b["id"]
    assert t["output"]["steps"] == 1
    # answering a quest question is progress
    client.patch(f"/api/quest-questions/{q1}", json={"answer": "Weighted sum of values by query-key similarity."})
    t = client.get("/api/today").json()
    assert t["quest"]["progress"] == {"answered": 1, "total": 3}
    assert t["output"]["answers"] == 1
    client.patch(f"/api/quest-questions/{q1}", json={"answer": ""})
    assert client.get("/api/today").json()["quest"]["progress"]["answered"] == 0


def test_energy_checkin(client):
    client.post("/api/checkins", json={"energy": "low"})
    client.post("/api/checkins", json={"energy": "high"})
    assert client.get("/api/today").json()["checkin"]["energy"] == "high"
    assert client.post("/api/checkins", json={"energy": "sleepy"}).status_code == 422


def test_side_quests_park_and_link(client, sample_md):
    q = _quest(client)
    doc = client.post("/api/import/text", json={"title": "Notes", "text": sample_md, "format": "markdown"}).json()
    client.post("/api/side-quests", json={"text": "Learn advanced CUDA", "decision": "parked"})
    client.post("/api/side-quests", json={"text": "Notes", "decision": "linked", "document_id": doc["id"],
                                          "question_id": q["questions"][1]["id"]})
    t = client.get("/api/today").json()
    assert t["parked"] == 1
    assert [s["text"] for s in t["quest"]["side_quests"]] == ["Learn advanced CUDA"]
    assert t["quest"]["documents"][0]["id"] == doc["id"]  # the document now reads for question 2
    side = t["quest"]["side_quests"][0]
    client.patch(f"/api/side-quests/{side['id']}")
    assert client.get("/api/today").json()["parked"] == 0


def test_time_on_main_quest_and_empty_sessions(client):
    q = _quest(client)
    on = client.post("/api/sessions", json={"quest_id": q["id"], "energy": "medium"}).json()
    client.patch(f"/api/sessions/{on['id']}", json={"focused_ms": 30 * 60_000, "output": "answer to Q1", "ended": True})
    side = client.post("/api/sessions", json={"energy": "low"}).json()
    client.patch(f"/api/sessions/{side['id']}", json={"focused_ms": 10 * 60_000, "ended": True})  # produced nothing
    out = client.get("/api/today").json()["output"]
    assert out["on_quest_ratio"] == 0.75
    assert out["empty_sessions"] == 1
    assert client.get("/api/today").json()["empty_streak"] == 1


def test_energy_curve_finds_your_peak(client, db):
    from readhold import compass

    base = dt.datetime.now().astimezone().replace(hour=9, minute=30, second=0, microsecond=0)
    for day in range(4):
        start = (base - dt.timedelta(days=day + 1)).astimezone(dt.timezone.utc).isoformat(timespec="milliseconds")
        db.insert("sessions", {"started_at": start, "focused_ms": 40 * 60_000, "energy": "high"})
    curve = compass.energy_curve(db)
    assert curve["learning"] is False
    assert curve["peak"][0] in (8, 9)  # the best 2-hour window covers 9:30
