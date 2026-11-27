"""Tidy without a model (milestone 5.2, the non-AI layer): what a good task lacks, and fixes code can make.

A good task starts with what you will do (a verb), has one outcome, a day, and stays short. Code shows each of these
as a hint, and fixes what it can be sure of: spacing, a capital first letter, a time ("30 min") or a day ("tomorrow")
written into the text, moved into the task's own minutes and day. Notes and routines get spacing and list fixes.
Nothing is changed here: the page applies a fix through the usual routes, with Undo."""
import datetime as dt

from readhold import tidy

TODAY = dt.date(2026, 11, 26)  # a Thursday


def test_a_good_task_has_no_hints():
    got = tidy.task("Read chapter 3 of the networks book", 30, "2026-11-27", TODAY)
    assert got["hints"] == [] and got["fix"] is None


def test_hints_say_what_a_task_lacks():
    kinds = {h["kind"] for h in tidy.task("networks book chapter 3", 25, None, TODAY)["hints"]}
    assert kinds == {"verb", "day"}
    several = tidy.task("Email Sara and book the room and print the slides", 25, "2026-11-27", TODAY)["hints"]
    assert [h["kind"] for h in several] == ["several"]
    long = tidy.task("Read " + "the very long description of everything " * 4, 25, "2026-11-27", TODAY)["hints"]
    assert [h["kind"] for h in long] == ["long"]
    assert tidy.task("Write the report", 25, None, TODAY, repeats=True)["hints"] == []  # a repeating task needs no day


def test_a_time_or_a_day_in_the_text_moves_into_the_task():
    got = tidy.task("  call   the bank (30 min) tomorrow ", 25, None, TODAY)
    assert got["fix"] == {"text": "Call the bank", "minutes": 30, "due": "2026-11-27"}
    assert tidy.task("Revise for 1.5h on friday", 25, None, TODAY)["fix"] == {"text": "Revise", "minutes": 90, "due": "2026-11-27"}
    assert tidy.task("Plan next week monday", 25, None, TODAY)["fix"]["due"] == "2026-11-30"
    kept = tidy.task("Read for 20m", 25, "2026-12-01", TODAY)["fix"]
    assert kept == {"text": "Read", "minutes": 20, "due": "2026-12-01"}  # a day already set is kept
    assert tidy.task("Read 900 min", 25, None, TODAY)["fix"] is None  # past the most a task may take: left alone


def test_text_in_another_script_gets_no_verb_hint():
    assert all(h["kind"] != "verb" for h in tidy.task("قراءة الفصل الثالث", 25, "2026-11-27", TODAY)["hints"])


def test_notes_and_routines_get_spacing_and_list_fixes():
    body = "# Title  \n\n\n\n* one\n•  two\n\nText   with  spaces.   \n"
    assert tidy.note(body) == "# Title\n\n- one\n- two\n\nText with spaces.\n"
    assert tidy.note("Already tidy.\n") is None
    steps = tidy.routine([{"text": "  drink water ", "minutes": 0}, {"text": "stretch 10 min", "minutes": 0}])
    assert steps == [{"text": "Drink water", "minutes": 0}, {"text": "Stretch", "minutes": 10}]
    assert tidy.routine([{"text": "Walk", "minutes": 5}]) is None


def test_the_tasks_route_lists_open_tasks_with_their_hints(client):
    a = client.post("/api/todos", json={"text": "networks book chapter 3", "minutes": 25}).json()
    b = client.post("/api/todos", json={"text": "Read the paper", "minutes": 25, "due": dt.date.today().isoformat()}).json()
    client.patch(f"/api/todos/{b['id']}", json={"done": True})
    got = client.get("/api/tidy/tasks").json()["items"]
    assert [i["id"] for i in got] == [a["id"]]  # open tasks only
    assert {h["kind"] for h in got[0]["hints"]} == {"verb", "day"}


def test_the_note_and_routine_routes_propose_without_changing(client, db):
    page = client.post("/api/pages", json={"title": "Messy", "body": "* one\n\n\n\n* two   \n"}).json()
    got = client.get(f"/api/tidy/note/{page['id']}").json()
    assert got["body"] == "- one\n\n- two\n" and client.get(f"/api/pages/{page['id']}").json()["body"] == "* one\n\n\n\n* two   \n"
    r = client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "drink water", "minutes": 0}]}).json()
    assert client.get(f"/api/tidy/routine/{r['id']}").json()["steps"] == [{"text": "Drink water", "minutes": 0}]
    assert client.get("/api/tidy/note/" + "f" * 32).status_code == 404


# ------------------------------------------------------------------ found by the review of 5.2
def test_a_note_keeps_its_tags_code_and_rules():
    assert tidy.note("#private\n#idea about labs\n") is None  # a tag is not made a heading
    code = "Text\n\n```\nline one\n\n\n\nline   two\n```\n\n* * *\n\n    indented   code\n"
    assert tidy.note(code) is None  # code blocks, a rule and indented code are left as they are
    assert tidy.note("No final newline") is None


def test_day_and_time_words_inside_other_phrases_are_left_alone():
    for text in ("Prepare Friday's slides", "Call dentist (not today)", "Water plants every monday", "Review notes before sunday",
                 "Read 'Monday Begins on Saturday'", "Watch 60 Minutes episode", "Buy 2 m of cable"):
        fix = tidy.task(text, 25, "2026-11-30", TODAY)["fix"]
        assert fix is None, (text, fix)
    assert tidy.task("Email Bob (friday)", 25, None, TODAY)["fix"]["text"] == "Email Bob"  # no empty brackets left
    assert tidy.task("Today: review notes", 25, None, TODAY)["fix"]["text"] == "Review notes"
    assert tidy.task("Call Bob friday", 25, "2026-12-01", TODAY)["fix"] is None  # another day already set: the word stays
    for text in ("iPhone repair", "https://example.org read", "eBay order"):
        assert tidy.task(text, 25, "2026-11-30", TODAY)["fix"] is None, text  # not capitalised


def test_a_time_inside_quotes_in_a_routine_step_is_left_alone():
    assert tidy.routine([{"text": "Watch 'The 5 min drill'", "minutes": 0}]) is None
