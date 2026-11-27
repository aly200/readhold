"""Bug fixes from the review, plus: energy drain log, paper critique, mixed practice, weekly review, undo removal."""
import json


def _doc(client, sample_md, title="Notes"):
    return client.post("/api/import/text", json={"title": title, "text": sample_md, "format": "markdown"}).json()


# ------------------------------------------------------------------ bug fixes
def test_guess_without_definition_becomes_a_card(client):
    t = client.post("/api/terms", json={"term": "router", "guess": "picks which tokens attend"}).json()
    cards = client.get("/api/cards").json()
    card = next(c for c in cards if c["source_id"] == t["id"])
    assert card["front"] == "router" and "Your guess: picks which tokens attend" in card["back"]
    client.patch(f"/api/terms/{t['id']}", json={"definition": "A module that selects tokens."})
    card = next(c for c in client.get("/api/cards").json() if c["source_id"] == t["id"])
    assert card["back"].startswith("A module that selects tokens.")  # the real definition replaces the guess


def test_predictions_and_critique_in_markdown(client, sample_md):
    doc = _doc(client, sample_md)
    d = client.get(f"/api/documents/{doc['id']}").json()
    sec = d["sections"][0]["id"]
    client.patch(f"/api/sections/{sec}", json={"prediction": "It will route tokens", "prediction_check": "Right"})
    client.patch(f"/api/documents/{doc['id']}", json={"critique": "Strong idea, weak baselines.", "reproduce": "The 41% compute cut"})
    md = client.post(f"/api/documents/{doc['id']}/export").json()["markdown"]
    assert "## Predictions" in md and "I predicted: It will route tokens" in md and "Afterwards: Right" in md
    assert "## My critique" in md and "Strong idea, weak baselines." in md and "The 41% compute cut" in md


def test_export_all_leaves_out_removed_items(client, sample_md, home):
    keep = _doc(client, sample_md, "Keep")
    gone = _doc(client, sample_md, "Gone")
    client.delete(f"/api/documents/{gone['id']}")
    path = client.post("/api/export/all").json()["path"]
    data = json.loads(open(path, encoding="utf-8").read())
    ids = [d["id"] for d in data["documents"]]
    assert keep["id"] in ids and gone["id"] not in ids


def test_removed_document_can_be_restored(client, sample_md):
    doc = _doc(client, sample_md)
    client.delete(f"/api/documents/{doc['id']}")
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert client.post(f"/api/documents/{doc['id']}/restore").status_code == 200
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200


def test_structure_view_does_not_start_reading(client, sample_md):
    doc = _doc(client, sample_md)
    assert client.get(f"/api/documents/{doc['id']}?touch=false").json()["status"] == "queued"
    assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "reading"


def test_concept_search_treats_percent_and_underscore_as_text(client, sample_md):
    _doc(client, sample_md)  # contains "41%"
    assert client.get("/api/concepts", params={"term": "41%"}).json()["mentions"]  # "41%" is found
    assert client.get("/api/concepts", params={"term": "%"}).json()["mentions"]  # a literal % exists ("41%")
    assert client.get("/api/concepts", params={"term": "s_r"}).json()["mentions"] == []  # _ isn't "any character" ("SMR")


def test_time_box_extension_is_saved(client, db):
    s = client.post("/api/sessions", json={"energy": "medium", "time_box_min": 15}).json()
    client.patch(f"/api/sessions/{s['id']}", json={"time_box_min": 20})
    assert db.scalar("SELECT time_box_min FROM sessions WHERE id=?", (s["id"],)) == 20


def test_settings_rows_have_sync_columns(client, db):
    client.put("/api/settings", json={"theme": "paper"})
    row = db.one("SELECT * FROM settings WHERE key='theme'")
    assert row["id"] and row["device_id"] == db.device and row["deleted"] == 0


# ------------------------------------------------------------------ energy drain log
def test_energy_feel_shows_what_drains_and_lifts_you(client):
    q = client.post("/api/quests", json={"title": "Q", "questions": ["A?"]}).json()
    step = client.post(f"/api/quests/{q['id']}/steps", json={"title": "Debug the data loader"}).json()
    for feel in ("drained", "drained", "energized"):
        s = client.post("/api/sessions", json={"energy": "medium", "quest_id": q["id"], "step_id": step["id"]}).json()
        client.patch(f"/api/sessions/{s['id']}", json={"feel": feel, "ended": True})
    other = client.post("/api/sessions", json={"energy": "high", "question": "Sketch the idea"}).json()
    client.patch(f"/api/sessions/{other['id']}", json={"feel": "energized", "ended": True})
    feel = client.get("/api/stats").json()["week"]["feel"]
    assert feel["drains"][0] == {"what": "Debug the data loader", "energized": 1, "neutral": 0, "drained": 2}
    assert {i["what"] for i in feel["lifts"]} == {"Debug the data loader", "Sketch the idea"}
    assert feel["total"] == {"energized": 2, "neutral": 0, "drained": 2}
    assert client.patch(f"/api/sessions/{other['id']}", json={"feel": "angry"}).status_code == 422


# ------------------------------------------------------------------ mixed practice
def test_practice_interleaves_topics_and_puts_misses_first(client, sample_md):
    q = client.post("/api/quests", json={"title": "Transformers", "questions": ["What is attention?", "Why heads?"]}).json()
    for qq in q["questions"]:
        client.patch(f"/api/quest-questions/{qq['id']}", json={"answer": f"Answer to {qq['text']}"})
    doc = _doc(client, sample_md)
    for text in ("What does SMR reduce?", "What matches dense models?"):
        dq = client.post("/api/questions", json={"document_id": doc["id"], "text": text}).json()
        client.patch(f"/api/questions/{dq['id']}", json={"answer": "Compute"})
    items = client.get("/api/practice?n=4").json()
    assert len(items) == 4
    topics = [i["topic_id"] for i in items]
    assert all(a != b for a, b in zip(topics, topics[1:]))  # never the same topic twice in a row
    missed = next(i for i in items if i["source_type"] == "question")
    client.post("/api/practice", json={"source_type": missed["source_type"], "source_id": missed["source_id"], "result": "missed"})
    again = client.get("/api/practice?n=4").json()
    assert again[0]["source_id"] == missed["source_id"] and again[0]["last_result"] == "missed"
    assert client.post("/api/practice", json={"source_type": "question", "source_id": "x", "result": "meh"}).status_code == 422


def test_practice_is_empty_without_answers(client):
    assert client.get("/api/practice").json() == []


# ------------------------------------------------------------------ weekly review
def test_weekly_review_collects_logs_steps_habits_and_practice(client):
    q = client.post("/api/quests", json={"title": "Exam", "questions": ["A?"]}).json()
    step = client.post(f"/api/quests/{q['id']}/steps", json={"title": "Recall A"}).json()
    client.patch(f"/api/quest-steps/{step['id']}", json={"done": True, "output": "wrote A from memory"})
    client.post("/api/logs", json={"did": "Recalled A", "learned": "B matters", "next": "", "next_as_lead": False})
    hb = client.post("/api/habits", json={"title": "Review cards"}).json()
    client.post(f"/api/habits/{hb['id']}/check")
    client.patch(f"/api/quests/{q['id']}", json={"status": "done"})
    week = client.get("/api/stats").json()["week"]
    assert week["logs"][0]["did"] == "Recalled A"
    assert week["steps_done"][0]["title"] == "Recall A" and week["steps_done"][0]["output"] == "wrote A from memory"
    assert week["quests_done"][0]["title"] == "Exam"
    assert week["habits"] == [{"title": "Review cards", "days": 1}]
    assert week["practice"] == {"got": 0, "partly": 0, "missed": 0}


# ------------------------------------------------------------------ code review fixes
def test_step_rejects_empty_required_fields_and_foreign_refs(client):
    a = client.post("/api/quests", json={"title": "A", "questions": ["A1?"]}).json()
    b = client.post("/api/quests", json={"title": "B", "questions": ["B1?"]}).json()  # parks A, both still exist
    step = client.post(f"/api/quests/{b['id']}/steps", json={"title": "Do it"}).json()
    assert client.patch(f"/api/quest-steps/{step['id']}", json={"title": None}).status_code == 422
    assert client.patch(f"/api/quest-steps/{step['id']}", json={"minutes": None}).status_code == 422
    foreign = a["questions"][0]["id"]
    assert client.patch(f"/api/quest-steps/{step['id']}", json={"question_id": foreign}).status_code == 422
    assert client.post(f"/api/quests/{b['id']}/steps", json={"title": "x", "question_id": foreign}).status_code == 422
    assert client.post(f"/api/quests/{b['id']}/steps", json={"title": "x", "document_id": "0" * 32}).status_code == 422
    own = b["questions"][0]["id"]
    assert client.patch(f"/api/quest-steps/{step['id']}", json={"question_id": own}).json()["question_id"] == own


def test_moving_the_lead_updates_sync_columns(client, db):
    q = client.post("/api/quests", json={"title": "Q", "questions": []}).json()
    first = client.post(f"/api/quests/{q['id']}/steps", json={"title": "First", "lead": True}).json()
    db.execute("UPDATE quest_steps SET updated_at='2000-01-01T00:00:00.000+00:00' WHERE id=?", (first["id"],))
    client.post(f"/api/quests/{q['id']}/steps", json={"title": "Second", "lead": True})
    row = db.one("SELECT lead, updated_at FROM quest_steps WHERE id=?", (first["id"],))
    assert row["lead"] == 0 and row["updated_at"] > "2001"  # the change is visible to a future sync


def test_energy_feel_names_unlabelled_sessions(client):
    s = client.post("/api/sessions", json={"energy": "low"}).json()
    client.patch(f"/api/sessions/{s['id']}", json={"feel": "drained", "ended": True})
    assert client.get("/api/stats").json()["week"]["feel"]["drains"][0]["what"] == "Session"


def test_active_quest_endpoint(client):
    assert client.get("/api/quest/active").json() is None
    q = client.post("/api/quests", json={"title": "Q", "questions": ["One?"]}).json()
    active = client.get("/api/quest/active").json()
    assert active["id"] == q["id"] and active["questions"][0]["text"] == "One?"


def test_habits_list_matches_single_habit_state(client):
    a = client.post("/api/habits", json={"title": "A"}).json()
    client.post("/api/habits", json={"title": "B"})
    client.post(f"/api/habits/{a['id']}/check")
    listed = {h["title"]: h for h in client.get("/api/habits").json()}
    assert listed["A"]["done_today"] is True and listed["A"]["streak"] == 1
    assert listed["B"]["done_today"] is False and listed["B"]["streak"] == 0
