"""Connections between the pages: what links to what, one day from every side, and the week in Plan."""
import datetime as dt


def _today():
    return dt.date.today().isoformat()


def test_a_document_shows_the_notes_and_tasks_that_point_at_it(client, sample_md):
    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    note = client.post("/api/pages", json={"title": "Reading log", "body": "Started [[Attention Is a Test#s3|the paper]] today."}).json()
    client.post("/api/pages", json={"title": "Unrelated", "body": "Nothing here."})
    task = client.post("/api/todos", json={"text": "Finish section 2", "link_type": "document", "link_id": doc["id"]}).json()
    done = client.post("/api/todos", json={"text": "Skim it", "link_type": "document", "link_id": doc["id"]}).json()
    client.patch(f"/api/todos/{done['id']}", json={"done": True})
    got = client.get("/api/related", params={"kind": "document", "id": doc["id"]}).json()
    assert got["title"] == "Attention Is a Test"
    assert [(n["id"], n["context"]) for n in got["notes"]] == [(note["id"], "Started [[Attention Is a Test#s3|the paper]] today.")]
    assert [t["id"] for t in got["tasks"]] == [task["id"]]  # finished tasks are not listed
    assert client.get("/api/related", params={"kind": "document", "id": "0" * 32}).status_code == 404
    assert client.get("/api/related", params={"kind": "nonsense", "id": doc["id"]}).status_code == 422


def test_a_task_can_point_at_a_note_and_the_note_shows_it(client):
    note = client.post("/api/pages", json={"title": "Exam plan", "body": "- [ ] Book the room"}).json()
    task = client.post("/api/todos", json={"text": "Book the room", "link_type": "page", "link_id": note["id"]}).json()
    assert task["link_type"] == "page"
    assert [t["text"] for t in client.get("/api/related", params={"kind": "page", "id": note["id"]}).json()["tasks"]] == ["Book the room"]
    assert client.post("/api/todos", json={"text": "x", "link_type": "page", "link_id": "0" * 32}).status_code == 422


def test_a_quest_shows_the_tasks_made_from_its_steps(client):
    quest = client.post("/api/quests", json={"title": "Pass the exam", "why": "", "done_looks_like": "", "questions": ["How?"]}).json()
    client.post(f"/api/quests/{quest['id']}/steps", json={"title": "Solve five problems", "minutes": 30})
    step = client.get("/api/plan").json()["quest_step"]
    client.post("/api/todos", json={"text": step["title"], "link_type": "step", "link_id": step["id"], "due": _today()})
    client.post("/api/pages", json={"title": "Why this exam", "body": "It unlocks the next course. [[pass the exam]]"})
    got = client.get("/api/related", params={"kind": "quest", "id": quest["id"]}).json()
    assert [t["text"] for t in got["tasks"]] == ["Solve five problems"] and [n["title"] for n in got["notes"]] == ["Why this exam"]


def test_a_note_can_link_to_a_glossary_term_and_the_term_shows_its_notes(client, sample_md):
    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    r = client.post("/api/terms", json={"term": "Self-attention", "definition": "Each word looks at every other word.", "document_id": doc["id"]})
    assert r.status_code == 200, r.text
    linked = client.post("/api/pages", json={"title": "Linked", "body": "See [[self-attention]]."}).json()
    plain = client.post("/api/pages", json={"title": "Plain", "body": "I think self-attention is the key idea."}).json()
    assert [(o["kind"], o["title"]) for o in linked["outgoing"]] == [("term", "Self-attention")]
    assert ("term", "Self-attention") in {(o["kind"], o["title"]) for o in client.get("/api/pages/titles").json()["others"]}
    got = client.get("/api/related", params={"kind": "term", "title": "self-attention"}).json()
    assert [n["id"] for n in got["notes"]] == [linked["id"]] and [m["id"] for m in got["mentions"]] == [plain["id"]] and got["tasks"] == []
    assert client.get("/api/related", params={"kind": "term", "title": "no such word"}).status_code == 404


def test_one_day_from_every_side(client):
    empty = client.get(f"/api/day/{_today()}").json()
    assert empty == {"day": _today(), "tasks_done": [], "focus_min": 0, "routine_steps": 0, "journal": None, "note_id": None}
    t = client.post("/api/todos", json={"text": "Water the plants"}).json()
    client.patch(f"/api/todos/{t['id']}", json={"done": True})
    r = client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "Water"}]}).json()
    client.post(f"/api/routines/{r['id']}/steps/{r['steps'][0]['id']}/check", json={"done": True})
    note = client.get(f"/api/pages/daily/{_today()}").json()
    got = client.get(f"/api/day/{_today()}").json()
    assert got["tasks_done"] == ["Water the plants"] and got["routine_steps"] == 1 and got["note_id"] == note["id"]
    assert client.get("/api/day/2026-13-45").status_code == 404 and client.get("/api/day/yesterday").status_code == 404


def test_the_week_in_plan_and_the_cards_due(client):
    for text, area in (("A", "Study"), ("B", "Study"), ("C", "Home"), ("D", "")):
        t = client.post("/api/todos", json={"text": text, "area": area}).json()
        client.patch(f"/api/todos/{t['id']}", json={"done": True})
    client.post("/api/todos", json={"text": "Still open"})
    r = client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "Water"}]}).json()
    client.post(f"/api/routines/{r['id']}/steps/{r['steps'][0]['id']}/check", json={"done": True})
    w = client.get("/api/week/plan").json()
    assert w["tasks_done"] == 4 and w["open"] == 1 and w["areas"] == [{"area": "Study", "n": 2}, {"area": "Home", "n": 1}]
    assert w["routines"] == [{"title": "Morning", "days": 1, "of": 7}]
    assert client.get("/api/plan").json()["review_due"] == 0
