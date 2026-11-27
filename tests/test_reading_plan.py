"""Reading plan without a model (AI plan, milestone 3.1, the code half): you choose the documents, their order and
how hard each one is; code sizes what is left to read at your pace and schedules it day by day. A plan never goes
past your minutes a day or past the day you must finish by; what does not fit is named, never squeezed in.
Adding a plan to Plan makes tasks you can take back in one step."""
import datetime as dt
import random

from readhold import readplan
from tests.conftest import SAMPLE_MD

D0 = dt.date(2026, 12, 1)  # a Tuesday
SMALL = "# Small paper\n\n## One\n\nA short text about rain on the hills and the soil below them.\n"


def _doc(client, text=SAMPLE_MD, title=""):
    r = client.post("/api/import/text", json={"title": title, "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()


def _long(words: int, sections: int = 4, name="Long") -> str:
    per = words // sections
    body = "\n\n".join(f"## Part {i + 1}\n\n" + " ".join(f"word{i}x{k}" for k in range(per)) + "." for i in range(sections))
    return f"# {name}\n\n{body}\n"


def piece(doc="d1", minutes=30, title="A", sentence=0):
    return {"title": title, "sentence": sentence, "minutes": minutes}


def docs(*sizes):
    return [{"id": f"d{i}", "title": f"Doc {i}", "parts": [piece(f"d{i}", m, f"S{j}", j) for j, m in enumerate(parts)]} for i, parts in enumerate(sizes)]


def _check(plan, per_day, start, deadline, days_off=frozenset(), busy=None):
    busy = busy or {}
    for day in plan["days"]:
        d = dt.date.fromisoformat(day["day"])
        assert start <= d <= deadline, day
        assert d.weekday() not in days_off, day
        assert day["minutes"] == sum(i["minutes"] for i in day["items"])
        assert not day["items"] or day["minutes"] + busy.get(day["day"], 0) <= per_day, day  # what you planned before is yours
        assert all(i["minutes"] > 0 for i in day["items"])


# ------------------------------------------------------------------ the scheduler
def test_everything_fits_in_order_and_within_the_day():
    plan = readplan.schedule(docs([30, 30], [45]), D0, D0 + dt.timedelta(days=6), 40)
    _check(plan, 40, D0, D0 + dt.timedelta(days=6))
    assert plan["fits"] and plan["unplaced"] == [] and plan["total"] == 105
    assert sum(d["minutes"] for d in plan["days"]) == 105
    order = [i["document_id"] for d in plan["days"] for i in d["items"]]
    assert order == sorted(order, key=lambda x: int(x[1:]))  # the second document never starts before the first ends


def test_what_does_not_fit_is_named_never_put_past_the_deadline():
    plan = readplan.schedule(docs([60, 60], [90]), D0, D0 + dt.timedelta(days=1), 45)
    _check(plan, 45, D0, D0 + dt.timedelta(days=1))
    assert not plan["fits"]
    assert sum(d["minutes"] for d in plan["days"]) + sum(u["minutes"] for u in plan["unplaced"]) == plan["total"] == 210
    assert plan["unplaced"][-1]["document_id"] == "d1"
    # how many minutes a day it would take, found by the same scheduler
    need = plan["need_per_day"]
    assert need > 45 and readplan.schedule(docs([60, 60], [90]), D0, D0 + dt.timedelta(days=1), need)["fits"]
    assert not readplan.schedule(docs([60, 60], [90]), D0, D0 + dt.timedelta(days=1), need - 1)["fits"]


def test_days_off_and_time_already_planned_are_left_free():
    deadline = D0 + dt.timedelta(days=6)
    busy = {D0.isoformat(): 30, (D0 + dt.timedelta(days=1)).isoformat(): 40}
    plan = readplan.schedule(docs([50], [50]), D0, deadline, 40, days_off={5, 6}, busy=busy)
    _check(plan, 40, D0, deadline, {5, 6}, busy)
    assert plan["fits"]
    assert (D0 + dt.timedelta(days=1)).isoformat() not in {d["day"] for d in plan["days"] if d["items"]}


def test_a_tiny_gap_is_not_filled_with_a_two_minute_task():
    plan = readplan.schedule(docs([38], [30]), D0, D0 + dt.timedelta(days=3), 40)
    first = plan["days"][0]
    assert first["minutes"] == 38  # 2 minutes left that day: the next document starts tomorrow
    assert plan["days"][1]["items"][0]["document_id"] == "d1"
    # but a document that only has 2 minutes left does use them
    plan = readplan.schedule(docs([38], [2]), D0, D0, 40)
    assert plan["fits"] and plan["days"][0]["minutes"] == 40


def test_a_few_minutes_a_day_still_get_through_a_long_section():
    plan = readplan.schedule(docs([30]), D0, D0 + dt.timedelta(days=5), 5)
    assert plan["fits"] and [d["minutes"] for d in plan["days"]] == [5] * 6
    assert [i["continued"] for d in plan["days"] for i in d["items"]] == [False] + [True] * 5


def test_a_deadline_already_past_or_no_reading_day_left_is_refused():
    try:
        readplan.schedule(docs([10]), D0, D0 - dt.timedelta(days=1), 30)
        raise AssertionError("expected a refusal")
    except readplan.Invalid as e:
        assert "deadline" in str(e).lower()
    try:
        readplan.schedule(docs([10]), D0, D0, 30, days_off={D0.weekday()})
        raise AssertionError("expected a refusal")
    except readplan.Invalid as e:
        assert "day" in str(e).lower()


def test_random_plans_never_break_the_two_promises():
    rnd = random.Random(31)
    for _ in range(400):
        sizes = [[rnd.randint(1, 120) for _ in range(rnd.randint(1, 5))] for _ in range(rnd.randint(1, 6))]
        span = rnd.randint(0, 20)
        per_day = rnd.randint(5, 180)
        off = {d for d in range(7) if rnd.random() < 0.2}
        if len(off) == 7:
            off = set()
        days = [D0 + dt.timedelta(days=i) for i in range(span + 1)]
        if all(d.weekday() in off for d in days):
            continue
        busy = {d.isoformat(): rnd.randint(0, per_day + 10) for d in days if rnd.random() < 0.3}
        plan = readplan.schedule(docs(*sizes), D0, days[-1], per_day, days_off=off, busy=busy)
        _check(plan, per_day, D0, days[-1], off, busy)
        placed = sum(d["minutes"] for d in plan["days"])
        assert placed + sum(u["minutes"] for u in plan["unplaced"]) == plan["total"] == sum(map(sum, sizes))
        assert plan["fits"] == (not plan["unplaced"])


def test_minutes_come_from_words_your_pace_and_the_level():
    assert readplan.minutes(500, 250, "medium") == 2
    assert readplan.minutes(500, 250, "hard") == 3  # 2.8, rounded up
    assert readplan.minutes(500, 250, "easy") == 2  # 1.6, rounded up
    assert readplan.minutes(1, 250, "easy") == 1
    assert readplan.LEVELS["hard"] > readplan.LEVELS["medium"] > readplan.LEVELS["easy"]


# ------------------------------------------------------------------ the routes
def _preview(client, ids, **kw):
    body = {"documents": [{"id": i} if isinstance(i, str) else i for i in ids], "deadline": (dt.date.today() + dt.timedelta(days=6)).isoformat(),
            "minutes_per_day": 30, **kw}
    return client.post("/api/reading-plan/preview", json=body)


def test_candidates_are_unfinished_documents_with_what_is_left(client):
    a = _doc(client, _long(3000), "Long one")
    b = _doc(client)
    client.patch(f"/api/documents/{b['id']}", json={"status": "finished"})
    got = client.get("/api/reading-plan").json()
    ids = [d["id"] for d in got["documents"]]
    assert a["id"] in ids and b["id"] not in ids
    one = next(d for d in got["documents"] if d["id"] == a["id"])
    assert one["words_left"] >= 2990 and one["minutes_left"] == readplan.minutes(one["words_left"], got["wpm"], "medium")
    assert got["today"] == dt.date.today().isoformat()


def test_reading_already_done_is_not_planned_again(client):
    a = _doc(client, _long(4000))
    full = client.get(f"/api/documents/{a['id']}").json()
    third = full["sections"][2]["paragraphs"][0]["sentences"][0]["ord"]
    before = _preview(client, [a["id"]]).json()["total"]
    client.post(f"/api/documents/{a['id']}/position", json={"position": third})
    after = _preview(client, [a["id"]]).json()
    assert after["total"] < before
    first = after["days"][0]["items"][0]
    assert first["from"] == "Part 3" and first["sentence"] == third


def test_preview_checks_its_input(client):
    a = _doc(client)
    assert _preview(client, ["f" * 32]).status_code == 404
    assert _preview(client, ["nope"]).status_code in (404, 422)
    assert _preview(client, [a["id"]], deadline="2020-01-01").status_code == 422
    assert _preview(client, [a["id"]], deadline="2026-02-31").status_code == 422
    assert _preview(client, [a["id"]], minutes_per_day=0).status_code == 422
    assert _preview(client, [], ).status_code == 422
    assert _preview(client, [{"id": a["id"], "level": "impossible"}]).status_code == 422
    assert _preview(client, [a["id"]] * 2).json()["total"] == _preview(client, [a["id"]]).json()["total"]  # twice is once


def test_apply_makes_tasks_on_their_days_and_undo_takes_them_back(client):
    a = _doc(client, _long(6000, name="Big paper"))
    b = _doc(client, SMALL)
    body = {"documents": [{"id": a["id"], "level": "hard"}, {"id": b["id"]}], "deadline": (dt.date.today() + dt.timedelta(days=9)).isoformat(),
            "minutes_per_day": 20, "goal": "Exam on Friday"}
    plan = client.post("/api/reading-plan/preview", json=body).json()
    r = client.post("/api/reading-plan/apply", json=body)
    assert r.status_code == 200, r.text
    got = r.json()
    n = sum(len(d["items"]) for d in plan["days"])
    assert got["added"] == n and got["batch"]
    tasks = [t for t in client.get("/api/plan").json()["tasks"]] + []
    rows = client.app.state.db.all("SELECT * FROM todos WHERE plan_batch=? AND deleted=0 ORDER BY due", (got["batch"],))
    assert len(rows) == n
    per_day: dict = {}
    for t in rows:
        per_day[t["due"]] = per_day.get(t["due"], 0) + t["minutes"]
        assert t["link_type"] == "document" and t["link_id"] in (a["id"], b["id"])
        assert "Big paper" in t["text"] or "Small paper" in t["text"]
        assert "reading plan" in t["note"].lower() and "Exam on Friday" in t["note"]
    assert max(per_day.values()) <= 20
    assert tasks is not None
    # a task you already started stays when you undo; the rest go
    first = rows[0]
    client.patch(f"/api/todos/{first['id']}", json={"done": True})
    u = client.post(f"/api/reading-plan/{got['batch']}/undo").json()
    assert u["removed"] == n - 1 and u["kept"] == 1
    assert client.app.state.db.scalar("SELECT COUNT(*) FROM todos WHERE plan_batch=? AND deleted=0", (got["batch"],)) == 1
    assert client.post(f"/api/reading-plan/{got['batch']}/undo").json()["removed"] == 0  # twice is harmless
    assert client.post("/api/reading-plan/nope/undo").status_code == 404


def test_a_second_plan_counts_the_first_one_against_your_day(client):
    a = _doc(client, _long(6000))
    b = _doc(client, _long(6000, name="Other"))
    day = {"deadline": (dt.date.today() + dt.timedelta(days=3)).isoformat(), "minutes_per_day": 30}
    client.post("/api/reading-plan/apply", json={"documents": [{"id": a["id"]}], **day})
    second = client.post("/api/reading-plan/preview", json={"documents": [{"id": b["id"]}], **day}).json()
    assert all(d["minutes"] + d["busy"] <= 30 for d in second["days"])
    assert any(d["busy"] for d in second["days"]) or not second["days"]
    r = client.post("/api/reading-plan/apply", json={"documents": [{"id": b["id"]}], **day}).json()
    db = client.app.state.db
    for due in {t["due"] for t in db.all("SELECT due FROM todos WHERE deleted=0")}:
        assert db.scalar("SELECT SUM(minutes) FROM todos WHERE deleted=0 AND due=?", (due,)) <= 30
    assert r["added"] >= 0


def test_the_last_plan_can_still_be_undone_after_a_reload(client):
    a = _doc(client, _long(2000))
    body = {"documents": [{"id": a["id"]}], "deadline": (dt.date.today() + dt.timedelta(days=4)).isoformat(), "minutes_per_day": 30}
    got = client.post("/api/reading-plan/apply", json=body).json()
    last = client.get("/api/reading-plan").json()["last_batch"]
    assert last["id"] == got["batch"] and last["open"] == got["added"]
    client.post(f"/api/reading-plan/{got['batch']}/undo")
    assert client.get("/api/reading-plan").json()["last_batch"] is None


def test_a_plan_that_does_not_fit_adds_only_what_fits(client):
    a = _doc(client, _long(20000))
    body = {"documents": [{"id": a["id"]}], "deadline": dt.date.today().isoformat(), "minutes_per_day": 15}
    plan = client.post("/api/reading-plan/preview", json=body).json()
    assert not plan["fits"] and plan["unplaced"] and plan["need_per_day"] > 15
    got = client.post("/api/reading-plan/apply", json=body).json()
    assert client.app.state.db.scalar("SELECT SUM(minutes) FROM todos WHERE plan_batch=?", (got["batch"],)) <= 15


# ------------------------------------------------------------------ found by a review of 3.1
def _day_body(ids, days=3, per_day=30, **kw):
    return {"documents": [{"id": i} for i in ids], "deadline": (dt.date.today() + dt.timedelta(days=days)).isoformat(), "minutes_per_day": per_day, **kw}


def _today_minutes(db):
    today = dt.date.today().isoformat()
    return db.scalar("SELECT COALESCE(SUM(minutes), 0) FROM todos WHERE deleted=0 AND plan_batch!='' AND due=?", (today,))


def test_reading_done_or_timed_today_still_counts_against_today(client):
    a = _doc(client, _long(3000))
    b = _doc(client, _long(6000, name="Other"))
    db = client.app.state.db
    client.post("/api/reading-plan/apply", json=_day_body([a["id"]]))
    first = db.one("SELECT * FROM todos WHERE plan_batch!='' AND due=?", (dt.date.today().isoformat(),))
    client.patch(f"/api/todos/{first['id']}", json={"done": True})
    second = client.post("/api/reading-plan/preview", json=_day_body([b["id"]])).json()
    today = second["days"][0]
    assert today["busy"] >= first["minutes"] and today["minutes"] + today["busy"] <= 30
    # time spent with the timer counts too, at least the task's minutes
    db.execute("UPDATE todos SET done_at=NULL, spent_ms=? WHERE id=?", (50 * 60_000, first["id"]))
    third = client.post("/api/reading-plan/preview", json=_day_body([b["id"]])).json()
    assert third["days"][0]["busy"] >= 50 and not third["days"][0]["items"]


def test_an_open_plan_task_from_an_earlier_day_counts_on_today(client):
    a = _doc(client, _long(3000))
    b = _doc(client, _long(6000, name="Other"))
    db = client.app.state.db
    client.post("/api/reading-plan/apply", json=_day_body([a["id"]]))
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    db.execute("UPDATE todos SET due=? WHERE plan_batch!=''", (yesterday,))
    left = db.scalar("SELECT SUM(minutes) FROM todos WHERE plan_batch!=''")
    plan = client.post("/api/reading-plan/preview", json=_day_body([b["id"]])).json()
    assert plan["days"][0]["busy"] == left and plan["days"][0]["minutes"] + left <= 30


def test_undo_keeps_a_task_you_changed(client):
    a = _doc(client, _long(20000))
    db = client.app.state.db
    got = client.post("/api/reading-plan/apply", json=_day_body([a["id"]], days=5)).json()
    rows = db.all("SELECT id FROM todos WHERE plan_batch=? ORDER BY due", (got["batch"],))
    assert len(rows) >= 3
    client.patch(f"/api/todos/{rows[0]['id']}", json={"text": "My own words for this"})
    client.post(f"/api/todos/{rows[1]['id']}/items", json={"text": "a small step"})
    assert client.get("/api/reading-plan").json()["last_batch"]["open"] == len(rows) - 2
    u = client.post(f"/api/reading-plan/{got['batch']}/undo").json()
    assert u == {"removed": len(rows) - 2, "kept": 2}
    kept = {r["id"] for r in db.all("SELECT id FROM todos WHERE plan_batch=? AND deleted=0", (got["batch"],))}
    assert kept == {rows[0]["id"], rows[1]["id"]}


def test_apply_refuses_a_plan_other_than_the_one_shown(client):
    a = _doc(client, _long(20000))
    shown = client.post("/api/reading-plan/preview", json=_day_body([a["id"]])).json()
    r = client.post("/api/reading-plan/apply", json=_day_body([a["id"]], per_day=300, expect=shown["key"]))
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    assert client.app.state.db.scalar("SELECT COUNT(*) FROM todos") == 0
    assert client.post("/api/reading-plan/apply", json=_day_body([a["id"]], expect=shown["key"])).status_code == 200


def test_two_applies_at_once_never_book_a_day_twice(client):
    from concurrent.futures import ThreadPoolExecutor

    a = _doc(client, _long(6000))
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: client.post("/api/reading-plan/apply", json=_day_body([a["id"]])), range(4)))
    db = client.app.state.db
    for row in db.all("SELECT due, SUM(minutes) AS m FROM todos WHERE deleted=0 GROUP BY due"):
        assert row["m"] <= 30, row


def test_a_plan_with_nothing_to_add_is_refused(client):
    a = _doc(client)
    client.patch(f"/api/documents/{a['id']}", json={"status": "finished"})
    r = client.post("/api/reading-plan/apply", json=_day_body([a["id"]]))
    assert r.status_code == 422 and "nothing to add" in r.json()["detail"].lower()


def test_all_seven_days_off_says_why(client):
    a = _doc(client)
    r = client.post("/api/reading-plan/preview", json=_day_body([a["id"]], days_off="0123456"))
    assert r.status_code == 422 and "at least one day" in r.json()["detail"]
