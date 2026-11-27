"""The calm timer and the to-do timer: runs survive reloads, count as sessions, add time to to-dos, and link to steps."""
import datetime as dt


def _todo(client, text="Read chapter 3", minutes=25, **kw):
    r = client.post("/api/todos", json={"text": text, "minutes": minutes, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_focus_run_on_a_todo_counts_everywhere(client, db):
    todo = _todo(client)
    run = client.post("/api/timer/start", json={"kind": "focus", "minutes": 25, "todo_id": todo["id"]}).json()
    assert run["label"] == "Read chapter 3" and run["running"] and run["planned_ms"] == 25 * 60_000
    assert run["session_id"]
    # a reload sees the same run, still counting
    again = client.get("/api/timer").json()["run"]
    assert again["id"] == run["id"] and again["running"] and again["elapsed_now_ms"] >= 0
    # pause, resume, heartbeat, finish
    paused = client.post(f"/api/timer/{run['id']}/pause", json={"elapsed_ms": 600_000}).json()
    assert not paused["running"] and paused["elapsed_now_ms"] == 600_000
    assert client.post(f"/api/timer/{run['id']}/resume").json()["running"]
    assert client.post(f"/api/timer/{run['id']}/beat", json={"elapsed_ms": 900_000}).status_code == 200
    assert db.one("SELECT focused_ms FROM sessions WHERE id=?", (run["session_id"],))["focused_ms"] == 900_000
    out = client.post(f"/api/timer/{run['id']}/finish", json={"elapsed_ms": 1_500_000, "status": "done", "feel": "energized"}).json()
    assert out["today"]["focus_ms"] == 1_500_000 and out["today"]["runs"] == 1
    assert out["todos"][0]["spent_ms"] == 1_500_000
    s = db.one("SELECT * FROM sessions WHERE id=?", (run["session_id"],))
    assert s["focused_ms"] == 1_500_000 and s["ended_at"] and s["feel"] == "energized"
    assert client.get("/api/timer").json()["run"] is None
    # an ended run can't be paused again
    assert client.post(f"/api/timer/{run['id']}/pause", json={"elapsed_ms": 1}).status_code == 409
    # and it shows in Stamina
    today = client.get("/api/stats").json()["days"][-1]
    assert today["focused_ms"] >= 1_500_000


def test_one_timer_at_a_time_and_breaks_stay_out_of_the_stats(client, db):
    todo = _todo(client)
    first = client.post("/api/timer/start", json={"kind": "stopwatch", "todo_id": todo["id"]}).json()
    client.post(f"/api/timer/{first['id']}/pause", json={"elapsed_ms": 120_000})
    brk = client.post("/api/timer/start", json={"kind": "break", "minutes": 5, "todo_id": todo["id"]}).json()
    assert db.one("SELECT status FROM timer_runs WHERE id=?", (first["id"],))["status"] == "stopped"
    assert brk["session_id"] is None and brk["label"] == "Read chapter 3"
    client.post(f"/api/timer/{brk['id']}/finish", json={"elapsed_ms": 300_000})
    t = client.get("/api/timer").json()
    assert t["todos"][0]["spent_ms"] == 120_000  # the break didn't add to the to-do
    assert t["today"]["focus_ms"] == 120_000


def test_extend_and_validation(client):
    run = client.post("/api/timer/start", json={"kind": "focus", "minutes": 10}).json()
    assert client.post(f"/api/timer/{run['id']}/extend?minutes=5").json()["planned_ms"] == 15 * 60_000
    assert client.post(f"/api/timer/{run['id']}/extend?minutes=500").status_code == 422
    assert client.post("/api/timer/start", json={"kind": "nap", "minutes": 10}).status_code == 422
    assert client.post("/api/timer/start", json={"kind": "focus", "minutes": 0}).status_code == 422
    assert client.post("/api/timer/start", json={"kind": "focus", "link_type": "lecture", "link_id": "0" * 32}).status_code == 422
    assert client.post("/api/timer/not-an-id/pause", json={"elapsed_ms": 1}).status_code == 404
    assert client.post("/api/todos", json={"text": "", "minutes": 5}).status_code == 422
    assert client.post("/api/todos", json={"text": "x", "link_type": "step", "link_id": "f" * 32}).status_code == 422


def test_todo_linked_to_a_step_finishes_the_step(client):
    q = client.post("/api/quests", json={"title": "Exam", "why": "", "done_looks_like": "", "questions": ["How?"]}).json()
    step = client.post(f"/api/quests/{q['id']}/steps", json={"title": "Recall section 2"}).json()
    links = client.get("/api/timer/links").json()
    assert any(s["id"] == step["id"] for s in links["steps"])
    todo = _todo(client, "Recall section 2", 15, link_type="step", link_id=step["id"])
    done = client.patch(f"/api/todos/{todo['id']}", json={"done": True}).json()
    assert done["done_at"]
    s = next(s for s in client.get(f"/api/quests/{q['id']}").json()["steps"] if s["id"] == step["id"])
    assert s["done_at"] and s["output"].startswith("Done:")
    # today's finished to-dos stay on the list; undo works
    t = client.get("/api/timer").json()
    assert t["today"]["todos_done"] == 1 and t["todos"][-1]["id"] == todo["id"]
    assert client.patch(f"/api/todos/{todo['id']}", json={"done": False}).json()["done_at"] is None


def test_todo_order_edit_delete_restore_and_export(client, home):
    a = _todo(client, "A")
    b = _todo(client, "B")
    assert [t["text"] for t in client.get("/api/timer").json()["todos"]] == ["A", "B"]
    client.patch(f"/api/todos/{b['id']}", json={"ord": a["ord"] - 1, "minutes": 40, "text": "B first"})
    todos = client.get("/api/timer").json()["todos"]
    assert [t["text"] for t in todos] == ["B first", "A"] and todos[0]["minutes"] == 40
    client.delete(f"/api/todos/{a['id']}")
    assert len(client.get("/api/timer").json()["todos"]) == 1
    client.post(f"/api/todos/{a['id']}/restore")
    assert len(client.get("/api/timer").json()["todos"]) == 2
    from readhold.services import EXPORT_TABLES

    assert {"todos", "timer_runs"} <= set(EXPORT_TABLES)


def test_timer_settings_exist(client):
    s = client.get("/api/settings").json()
    assert s["timer_sound"] is True and s["timer_rhythm"] is False
    assert client.put("/api/settings", json={"timer_rhythm": True}).json()["timer_rhythm"] is True


def test_a_quick_reload_keeps_counting_but_a_closed_app_pauses(client, db):
    run = client.post("/api/timer/start", json={"kind": "focus", "minutes": 25}).json()
    # a reload a moment after the last heartbeat: the time since then counts
    earlier = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=40)).isoformat(timespec="milliseconds")
    db.conn.execute("UPDATE timer_runs SET running_since=?, elapsed_ms=60000, updated_at=? WHERE id=?", (earlier, earlier, run["id"]))
    r = client.get("/api/timer").json()["run"]
    assert r["running"] and 100_000 <= r["elapsed_now_ms"] < 110_000
    # the app was closed for an hour: the timer comes back paused at the last heartbeat
    long_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat(timespec="milliseconds")
    db.conn.execute("UPDATE timer_runs SET running_since=?, elapsed_ms=60000, updated_at=? WHERE id=?", (long_ago, long_ago, run["id"]))
    r = client.get("/api/timer").json()["run"]
    assert not r["running"] and r["elapsed_now_ms"] == 60_000 and r["was_quiet"]
    # a heartbeat rebases the saved time
    client.post(f"/api/timer/{run['id']}/resume")
    client.post(f"/api/timer/{run['id']}/beat", json={"elapsed_ms": 70_000})
    r = client.get("/api/timer").json()["run"]
    assert r["running"] and 70_000 <= r["elapsed_now_ms"] < 75_000
