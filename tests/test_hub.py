"""Overview: every feature's state in one call, and the quick line into today's note."""
import datetime as dt


def _today():
    return dt.date.today().isoformat()


def test_the_overview_gathers_every_feature(client, sample_md):
    empty = client.get("/api/hub").json()
    assert empty["tasks"] == [] and empty["quest"] is None and empty["routines"] == [] and empty["notes"] == [] and empty["journal"] is None
    assert empty["today"] == _today() and empty["review_due"] == 0 and empty["focus_min"] == 0
    assert [d["min"] for d in empty["focus_week"]] == [0] * 7 and empty["focus_week"][-1]["day"] == _today()

    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    client.post("/api/todos", json={"text": "Later thing", "due": (dt.date.today() + dt.timedelta(days=3)).isoformat()})
    client.post("/api/todos", json={"text": "No day"})
    client.post("/api/todos", json={"text": "Plain today", "due": _today()})
    client.post("/api/todos", json={"text": "Matters today", "due": _today(), "priority": 1})
    done = client.post("/api/todos", json={"text": "Done today", "due": _today()}).json()
    client.patch(f"/api/todos/{done['id']}", json={"done": True})
    quest = client.post("/api/quests", json={"title": "Pass the exam", "why": "", "done_looks_like": "", "questions": ["How?"]}).json()
    client.post(f"/api/quests/{quest['id']}/steps", json={"title": "Solve five problems", "minutes": 30})
    r = client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "Water"}, {"text": "Stretch"}]}).json()
    client.post(f"/api/routines/{r['id']}/steps/{r['steps'][0]['id']}/check", json={"done": True})
    client.post("/api/pages", json={"title": "A note", "body": "text"})
    client.post("/api/ideas", json={"text": "An   idea\nover two lines"})

    hub = client.get("/api/hub").json()
    assert [t["text"] for t in hub["tasks"]] == ["Matters today", "Plain today"]  # only what is for now, the starred one first
    assert hub["tasks_now"] == 2 and hub["tasks_open"] == 4 and hub["tasks_done_today"] == 1
    assert hub["quest"] == {"id": quest["id"], "title": "Pass the exam", "steps": 1, "steps_done": 0} and hub["quest_step"]["title"] == "Solve five problems"
    assert hub["routines"] == [{"id": r["id"], "title": "Morning", "slot": "morning", "done": 1, "total": 2, "next": {"id": r["steps"][1]["id"], "text": "Stretch"}}]
    assert [n["title"] for n in hub["notes"]] == ["A note"] and hub["notes_total"] == 1
    assert hub["ideas"][0]["text"] == "An idea over two lines" and hub["ideas_total"] == 1
    assert [d["id"] for d in hub["documents"]] == [doc["id"]] and hub["documents_total"] == 1 and hub["terms_total"] >= 0


def test_library_tabs_get_their_numbers(client, sample_md):
    assert client.get("/api/library/counts").json() == {"documents": 0, "lectures": 0, "goals": 0, "review_due": 0, "terms": 0}
    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    client.post("/api/terms", json={"term": "Attention", "definition": "Weights over the input", "document_id": doc["id"]})
    counts = client.get("/api/library/counts").json()
    client.post("/api/quests", json={"title": "Pass the exam", "why": "", "done_looks_like": "", "questions": []})
    counts = client.get("/api/library/counts").json()
    assert counts["documents"] == 1 and counts["terms"] == 1 and counts["goals"] == 1 and counts["lectures"] == 0
    assert counts["review_due"] == len(client.get("/api/review/due").json()["cards"])  # what the Review tab will show


def test_plan_tab_counts_what_is_for_now(client):
    assert client.get("/api/plan/counts").json() == {"tasks_now": 0}
    client.post("/api/todos", json={"text": "Today", "due": _today()})
    client.post("/api/todos", json={"text": "Carried", "due": (dt.date.today() - dt.timedelta(days=2)).isoformat()})
    client.post("/api/todos", json={"text": "Later", "due": (dt.date.today() + dt.timedelta(days=2)).isoformat()})
    client.post("/api/todos", json={"text": "No day"})
    done = client.post("/api/todos", json={"text": "Done", "due": _today()}).json()
    client.patch(f"/api/todos/{done['id']}", json={"done": True})
    assert client.get("/api/plan/counts").json() == {"tasks_now": 2}
    assert client.get("/api/hub").json()["tasks_now"] == 2  # the same number as the Overview


def test_notes_tabs_get_their_numbers(client):
    assert client.get("/api/notes/counts").json() == {"notes": 0, "ideas": 0, "think": 0}
    client.post("/api/pages", json={"title": "Eigenvalues", "body": "An eigenvalue scales its eigenvector. Is the determinant their product?"})
    client.post("/api/ideas", json={"text": "Draw the eigenvectors"})
    counts = client.get("/api/notes/counts").json()
    assert counts["notes"] == 1 and counts["ideas"] == 1 and counts["think"] == 0  # the tab itself makes no picks
    think = client.get(f"/api/think?day={_today()}").json()
    waiting = len([p for p in think["picks"] if p["status"] == "new"]) + len(think["suggestions"])
    assert client.get("/api/notes/counts").json()["think"] == waiting


def test_a_quick_line_goes_under_notes_in_the_days_note(client):
    r = client.post("/api/pages/capture", json={"text": "  Ask about   the exam room ", "day": "2026-11-22"})
    assert r.status_code == 200, r.text
    body = client.get(f"/api/pages/{r.json()['id']}").json()["body"]
    assert body == "## Today\n- [ ] \n\n## Notes\n- Ask about the exam room\n\n## One good thing\n"
    client.post("/api/pages/capture", json={"text": "Second line", "day": "2026-11-22"})
    body = client.get(f"/api/pages/{r.json()['id']}").json()["body"]
    assert body == "## Today\n- [ ] \n\n## Notes\n- Ask about the exam room\n- Second line\n\n## One good thing\n"
    # a note without that heading gets the line at its end
    client.patch(f"/api/pages/{r.json()['id']}", json={"body": "Just text"})
    client.post("/api/pages/capture", json={"text": "Third", "day": "2026-11-22"})
    assert client.get(f"/api/pages/{r.json()['id']}").json()["body"] == "Just text\n- Third\n"
    assert client.post("/api/pages/capture", json={"text": "x", "day": "2026-13-45"}).status_code == 422
    assert client.post("/api/pages/capture", json={"text": "", "day": "2026-11-22"}).status_code == 422
