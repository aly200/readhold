"""Plan: tasks with a day, a repeat rule and an area, and the routines of a day."""
import datetime as dt

import pytest


def _task(client, text="Buy milk", **kw):
    r = client.post("/api/todos", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _day(offset=0):
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


@pytest.mark.parametrize(
    "due, rule, today, expected",
    [
        ("2026-11-20", "daily", "2026-11-20", "2026-11-21"),
        ("2026-11-10", "daily", "2026-11-20", "2026-11-21"),  # done very late: the next one is still tomorrow
        ("2026-11-20", "weekdays", "2026-11-20", "2026-11-23"),  # Friday -> Monday
        ("2026-11-16", "weekly", "2026-11-18", "2026-11-23"),
        ("2026-11-02", "weekly", "2026-11-18", "2026-11-23"),  # two weeks late: the next Monday after today
        ("2026-01-31", "monthly", "2026-01-31", "2026-02-28"),  # a short month keeps its last day
        ("2026-12-15", "monthly", "2026-12-15", "2027-01-15"),
        (None, "daily", "2026-11-20", "2026-11-21"),
        ("2026-11-20", "", "2026-11-20", None),
    ],
)
def test_next_day_of_a_repeating_task(due, rule, today, expected):
    from readhold.timer import next_due

    assert next_due(due, rule, dt.date.fromisoformat(today)) == expected


def test_a_task_has_a_day_an_area_and_a_note(client):
    t = _task(client, "Call the dentist", due=_day(1), area=" Health ", note="Ask about Friday", minutes=10)
    assert t["due"] == _day(1) and t["area"] == "Health" and t["note"] == "Ask about Friday" and t["repeat_rule"] == ""
    plan = client.get("/api/plan").json()
    assert plan["today"] == _day() and plan["areas"] == ["Health"]
    assert [x["text"] for x in plan["tasks"]] == ["Call the dentist"]
    # a later day waits in Plan: the Timer page's list stays about now
    assert client.get("/api/timer").json()["todos"] == []
    moved = client.patch(f"/api/todos/{t['id']}", json={"due": _day()}).json()
    assert moved["due"] == _day()
    assert [x["id"] for x in client.get("/api/timer").json()["todos"]] == [t["id"]]
    # back to "anytime"
    assert client.patch(f"/api/todos/{t['id']}", json={"clear_due": True}).json()["due"] is None
    assert client.post("/api/todos", json={"text": "x", "due": "tomorrow"}).status_code == 422
    assert client.post("/api/todos", json={"text": "x", "due": "2026-02-31"}).status_code == 422
    assert client.post("/api/todos", json={"text": "x", "repeat_rule": "hourly"}).status_code == 422


def test_a_carried_over_task_stays_on_the_list(client, db):
    t = _task(client, "Water the plants", due=_day(-3))
    assert [x["id"] for x in client.get("/api/timer").json()["todos"]] == [t["id"]]
    assert client.get("/api/plan").json()["tasks"][0]["due"] == _day(-3)


def test_finishing_a_repeating_task_makes_the_next_one(client, db):
    t = _task(client, "Review 5 cards", repeat_rule="daily", area="Study", minutes=10)
    assert t["due"] == _day()  # a repeating task gets a first day
    done = client.patch(f"/api/todos/{t['id']}", json={"done": True}).json()
    assert done["done_at"] and done["next_id"]
    nxt = db.one("SELECT * FROM todos WHERE id=?", (done["next_id"],))
    assert nxt["text"] == "Review 5 cards" and nxt["due"] == _day(1) and nxt["repeat_rule"] == "daily" and nxt["area"] == "Study"
    assert nxt["done_at"] is None and nxt["minutes"] == 10
    tasks = client.get("/api/plan").json()["tasks"]
    assert {x["id"] for x in tasks} == {t["id"], nxt["id"]}
    # not done after all: the next one is taken back
    back = client.patch(f"/api/todos/{t['id']}", json={"done": False}).json()
    assert back["done_at"] is None and back["next_id"] is None
    assert [x["id"] for x in client.get("/api/plan").json()["tasks"]] == [t["id"]]
    # done again, and this time the next one has work on it: it stays even if you undo
    done = client.patch(f"/api/todos/{t['id']}", json={"done": True}).json()
    db.conn.execute("UPDATE todos SET spent_ms=60000 WHERE id=?", (done["next_id"],))
    client.patch(f"/api/todos/{t['id']}", json={"done": False})
    assert len(client.get("/api/plan").json()["tasks"]) == 2


def test_a_routine_starts_fresh_every_day(client, db):
    r = client.post("/api/routines", json={"title": " Morning start ", "slot": "morning",
                                           "steps": [{"text": "Glass of water"}, {"text": "Stretch", "minutes": 2}, {"text": "Look at the plan"}]}).json()
    assert r["title"] == "Morning start" and [s["text"] for s in r["steps"]] == ["Glass of water", "Stretch", "Look at the plan"]
    assert r["done"] == 0 and len(r["days"]) == 7 and r["days"][-1] == {"day": _day(), "part": 0, "off": False}
    first, second = r["steps"][0], r["steps"][1]
    out = client.post(f"/api/routines/{r['id']}/steps/{first['id']}/check", json={"done": True}).json()
    assert out["done"] == 1 and out["steps"][0]["done"] and out["days"][-1]["part"] == 0.33
    client.post(f"/api/routines/{r['id']}/steps/{first['id']}/check", json={"done": True})  # twice is still once
    assert client.get("/api/plan").json()["routines"][0]["done"] == 1
    assert client.post(f"/api/routines/{r['id']}/steps/{first['id']}/check", json={"done": False}).json()["done"] == 0
    # yesterday's checks do not count for today, but they show in the week
    db.insert("routine_checks", {"routine_id": r["id"], "step_id": second["id"], "day": _day(-1)})
    out = client.get("/api/plan").json()["routines"][0]
    assert out["done"] == 0 and out["days"][-2] == {"day": _day(-1), "part": 0.33, "off": False}


def test_editing_a_routine_keeps_the_history_of_unchanged_steps(client, db):
    r = client.post("/api/routines", json={"title": "Wind down", "slot": "evening", "steps": [{"text": "Tidy the desk"}, {"text": "Plan tomorrow"}]}).json()
    keep = r["steps"][1]
    client.post(f"/api/routines/{r['id']}/steps/{keep['id']}/check", json={"done": True})
    out = client.patch(f"/api/routines/{r['id']}", json={"title": "Evening", "steps": [{"text": "Plan tomorrow", "minutes": 5}, {"text": "Read ten pages"}]}).json()
    assert out["title"] == "Evening" and out["slot"] == "evening"
    assert [s["text"] for s in out["steps"]] == ["Plan tomorrow", "Read ten pages"]
    assert out["steps"][0]["id"] == keep["id"] and out["steps"][0]["done"] and out["steps"][0]["minutes"] == 5
    assert out["done"] == 1


def test_routines_are_ordered_by_part_of_day_and_can_be_removed(client):
    evening = client.post("/api/routines", json={"title": "Evening", "slot": "evening", "steps": [{"text": "a"}]}).json()
    morning = client.post("/api/routines", json={"title": "Morning", "slot": "morning", "steps": [{"text": "b"}]}).json()
    assert [r["title"] for r in client.get("/api/plan").json()["routines"]] == ["Morning", "Evening"]
    assert client.delete(f"/api/routines/{evening['id']}").status_code == 200
    assert [r["title"] for r in client.get("/api/plan").json()["routines"]] == ["Morning"]
    assert client.post(f"/api/routines/{evening['id']}/restore").json()["title"] == "Evening"
    assert client.post("/api/routines", json={"title": "", "steps": []}).status_code == 422
    assert client.post("/api/routines", json={"title": "x", "slot": "night"}).status_code == 422
    assert client.post(f"/api/routines/{morning['id']}/steps/{'0' * 32}/check", json={"done": True}).status_code == 404
    assert client.patch("/api/routines/nope", json={"title": "x"}).status_code == 404
    from readhold.services import EXPORT_TABLES

    assert {"routines", "routine_steps", "routine_checks"} <= set(EXPORT_TABLES)


# ---- plan, part two: the one that matters, small steps inside a task, routines on some days, the quest step
def test_a_task_can_matter_and_hold_small_steps(client):
    t = _task(client, "Write the report", priority=1, due=_day())
    assert t["priority"] == 1 and t["items"] == []
    t = client.post(f"/api/todos/{t['id']}/items", json={"text": " Outline "}).json()
    t = client.post(f"/api/todos/{t['id']}/items", json={"text": "First draft"}).json()
    assert [i["text"] for i in t["items"]] == ["Outline", "First draft"]
    first = t["items"][0]["id"]
    t = client.patch(f"/api/todos/{t['id']}/items/{first}", json={"done": True}).json()
    assert [i["done"] for i in t["items"]] == [True, False]
    plan = client.get("/api/plan").json()
    mine = next(x for x in plan["tasks"] if x["id"] == t["id"])
    assert [i["done"] for i in mine["items"]] == [True, False] and mine["priority"] == 1
    t = client.delete(f"/api/todos/{t['id']}/items/{first}").json()
    assert [i["text"] for i in t["items"]] == ["First draft"]
    assert client.patch(f"/api/todos/{t['id']}", json={"priority": 0}).json()["priority"] == 0
    assert client.patch(f"/api/todos/{t['id']}", json={"priority": 3}).status_code == 422
    other = _task(client, "Another")
    assert client.patch(f"/api/todos/{other['id']}/items/{t['items'][0]['id']}", json={"done": True}).status_code == 404


def test_a_repeating_task_brings_its_small_steps_back_unticked(client):
    t = _task(client, "Weekly review", repeat_rule="weekly", due=_day(), priority=1)
    t = client.post(f"/api/todos/{t['id']}/items", json={"text": "Look at last week"}).json()
    client.patch(f"/api/todos/{t['id']}/items/{t['items'][0]['id']}", json={"done": True})
    client.patch(f"/api/todos/{t['id']}", json={"done": True})
    plan = client.get("/api/plan").json()
    nxt = next(x for x in plan["tasks"] if x["text"] == "Weekly review" and not x["done_at"])
    assert nxt["priority"] == 1 and [(i["text"], i["done"]) for i in nxt["items"]] == [("Look at last week", False)]


def test_a_task_holds_a_limited_number_of_small_steps(client):
    from readhold.timer import MAX_ITEMS

    t = _task(client, "Big job")
    for n in range(MAX_ITEMS):
        assert client.post(f"/api/todos/{t['id']}/items", json={"text": f"step {n}"}).status_code == 200
    assert client.post(f"/api/todos/{t['id']}/items", json={"text": "one more"}).status_code == 409


def test_a_routine_can_be_for_some_days_only(client):
    today = dt.date.today().weekday()
    other = (today + 1) % 7
    on = client.post("/api/routines", json={"title": "Gym bag", "slot": "morning", "weekdays": str(today), "steps": [{"text": "Pack"}]}).json()
    assert on["on_today"] is True and on["weekdays"] == str(today) and on["next_on"] == ""
    off = client.post("/api/routines", json={"title": "Laundry", "slot": "evening", "weekdays": str(other), "steps": [{"text": "Wash"}]}).json()
    assert off["on_today"] is False and off["next_on"] == _day(1)
    assert [d["off"] for d in off["days"]][-1] is True
    every = client.patch(f"/api/routines/{off['id']}", json={"weekdays": "0123456"}).json()
    assert every["weekdays"] == "" and every["on_today"] is True
    assert client.post("/api/routines", json={"title": "Bad", "weekdays": "79", "steps": [{"text": "x"}]}).status_code == 422


def test_plan_shows_the_next_step_of_the_quest(client):
    assert client.get("/api/plan").json()["quest_step"] is None
    quest = client.post("/api/quests", json={"title": "Pass the exam", "why": "", "done_looks_like": "", "questions": ["How?"]}).json()
    step = client.post(f"/api/quests/{quest['id']}/steps", json={"title": "Solve five problems", "minutes": 30}).json()
    got = client.get("/api/plan").json()["quest_step"]
    assert got and got["quest_id"] == quest["id"] and got["quest_title"] == "Pass the exam" and got["in_plan"] is False
    step_id = got["id"]
    _task(client, got["title"], link_type="step", link_id=step_id, due=_day())
    assert client.get("/api/plan").json()["quest_step"]["in_plan"] is True
    assert step is not None


# ---- plan, part three: a time of day, and "every N days"
@pytest.mark.parametrize("due, rule, today, expected", [
    ("2026-11-20", "every:2", "2026-11-20", "2026-11-22"),
    ("2026-11-10", "every:3", "2026-11-20", "2026-11-22"),  # done late: it keeps its rhythm and lands after today
    ("2026-11-20", "every:14", "2026-11-20", "2026-12-04"),
])
def test_a_task_can_repeat_every_few_days(due, rule, today, expected):
    from readhold.timer import next_due

    assert next_due(due, rule, dt.date.fromisoformat(today)) == expected


def test_a_task_can_have_a_time_and_a_custom_repeat(client):
    t = _task(client, "Take the medicine", due=_day(), at="08:30", repeat_rule="every:2")
    assert t["at"] == "08:30" and t["repeat_rule"] == "every:2"
    late = _task(client, "Call back", due=_day(), at="16:05")
    _task(client, "No time", due=_day())
    _task(client, "Tomorrow", due=_day(1), at="09:00")
    timed = client.get("/api/todos/timed").json()
    assert timed["today"] == _day() and [(x["text"], x["at"]) for x in timed["tasks"]] == [("Take the medicine", "08:30"), ("Call back", "16:05")]
    client.patch(f"/api/todos/{t['id']}", json={"done": True})
    nxt = next(x for x in client.get("/api/plan").json()["tasks"] if x["text"] == "Take the medicine" and not x["done_at"])
    assert nxt["due"] == _day(2) and nxt["at"] == "08:30"  # the next one keeps its time
    assert client.patch(f"/api/todos/{late['id']}", json={"at": ""}).json()["at"] == ""
    for bad in ({"at": "25:00"}, {"at": "8:30"}, {"repeat_rule": "every:1"}, {"repeat_rule": "every:0"}, {"repeat_rule": "sometimes"}):
        assert client.patch(f"/api/todos/{late['id']}", json=bad).status_code == 422, bad
