"""The findings that were still open after the code guidebook: each one has a check here."""
import datetime as dt

def test_a_text_of_spaces_is_empty(client):
    assert client.post("/api/todos", json={"text": "   "}).status_code == 422
    assert client.post("/api/routines", json={"title": " \t ", "steps": [{"text": "Water"}]}).status_code == 422
    assert client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "  "}]}).status_code == 422
    assert client.post("/api/pages", json={"title": "  "}).status_code == 422
    made = client.post("/api/todos", json={"text": "  Call the dentist "})
    assert made.status_code == 200 and made.json()["text"] == "Call the dentist"
    assert client.patch(f"/api/todos/{made.json()['id']}", json={"text": "  "}).status_code == 422
    assert client.patch(f"/api/todos/{made.json()['id']}", json={"minutes": 5}).status_code == 200  # a field left out is not "empty"


def test_teachback_replaces_the_answer_only_when_asked(client):
    q = client.post("/api/quests", json={"title": "Understand attention", "questions": ["What does a head attend to?"]}).json()
    qq = q["questions"][0]["id"]
    url = f"/api/quest-questions/{qq}/teachback"
    assert client.post(url, json={"explanation": "First words."}).json()["question"]["answer"] == "First words."
    assert client.post(url, json={"explanation": "Second words."}).json()["question"]["answer"] == "First words."
    first = client.post(url, json={"explanation": "Second words."}).json()["question"]["answered_at"]
    third = client.post(url, json={"explanation": "Third words.", "replace": True}).json()["question"]
    assert third["answer"] == "Third words." and third["answered_at"] == first  # the day it was first answered stays


def test_a_suggestion_that_applies_again_is_offered_again(client, db):
    eigen = "An eigenvector keeps its direction under a linear transformation. The eigenvalue says how much it stretches."
    diag = "Diagonalization writes a matrix with its eigenvector basis, so the eigenvalue of each direction sits on the diagonal."
    for title, body in (("Eigenvectors", eigen), ("Diagonalization", diag)):
        assert client.post("/api/pages", json={"title": title, "body": body}).status_code == 200
    today = dt.date.today().isoformat()
    think = lambda: client.get("/api/think", params={"day": today}).json()["suggestions"]
    s = think()[0]
    src, dst = s["notes"]
    before = client.get(f"/api/pages/{src['id']}").json()["body"]
    # you add the link by hand: the suggestion no longer applies
    assert client.patch(f"/api/pages/{src['id']}", json={"body": f"{before} See [[{dst['title']}]]."}).status_code == 200
    assert think() == []
    assert db.scalar("SELECT status FROM suggestions WHERE id=?", (s["id"],)) == "stale"
    # you take the link out again: the same suggestion comes back (before, it was gone for good)
    assert client.patch(f"/api/pages/{src['id']}", json={"body": before}).status_code == 200
    assert [x["id"] for x in think()] == [s["id"]]
    # one you said no to stays away
    assert client.post(f"/api/think/suggestions/{s['id']}/reject").status_code == 200
    assert think() == []


def test_think_refuses_a_day_far_from_today(client):
    far = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    assert client.get("/api/think", params={"day": far}).status_code == 422
    near = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    assert client.get("/api/think", params={"day": near}).status_code == 200


def test_raw_updates_name_the_device(client, db):
    made = client.post("/api/todos", json={"text": "Read chapter 2", "minutes": 10}).json()
    db.execute("UPDATE todos SET device_id='other' WHERE id=?", (made["id"],))
    run = client.post("/api/timer/start", json={"kind": "focus", "minutes": 10, "todo_id": made["id"]})
    assert run.status_code == 200, run.text
    assert client.post(f"/api/timer/{run.json()['id']}/finish", json={"elapsed_ms": 60_000}).status_code == 200
    assert db.scalar("SELECT device_id FROM todos WHERE id=?", (made["id"],)) == db.device  # the time it took was written here
