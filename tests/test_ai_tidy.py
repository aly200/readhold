"""Tidy with a model (milestone 5.2): a rewrite of tasks, a note or a routine, proposed, never applied by itself.

The model may reword, split a task (at most 4 parts), estimate minutes and name a day the text already implies.
Code checks every number, day and length, and marks every word of the rewrite that is not in what you wrote (the
model may not add facts). Markup it adds ([[links]], #tags) stays plain text. The page applies what you accept,
through the usual routes, with Undo. No test reaches a real server (see conftest)."""
import datetime as dt
import json

import httpx

from tests.test_ai import LOCAL


class Model:
    def __init__(self, reply):
        self.reply = reply
        self.requests: list[dict] = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        out = self.reply(body) if callable(self.reply) else self.reply
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(out)}, "prompt_eval_count": 10, "eval_count": 10})

    def user(self, i=-1):
        return self.requests[i]["messages"][-1]["content"]

    def system(self, i=-1):
        return self.requests[i]["messages"][0]["content"]


def _model(client, model):
    client.app.state.ai.transport = httpx.MockTransport(model)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=LOCAL)
    return model


def _task(client, text, **kw):
    r = client.post("/api/todos", json={"text": text, "minutes": 25, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_with_ai_off_nothing_is_sent(client):
    _task(client, "networks book")
    model = Model({"tasks": []})
    client.app.state.ai.transport = httpx.MockTransport(model)
    assert client.post("/api/tidy/suggest", json={"kind": "tasks"}).status_code == 409 and model.requests == []


def test_tasks_are_rewritten_split_and_checked(client):
    a = _task(client, "networks book ch 3 and email sara about the lab")
    b = _task(client, "gym")
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    far = (dt.date.today() + dt.timedelta(days=400)).isoformat()
    model = _model(client, Model({"tasks": [
        {"task": 1, "text": "Read chapter 3 of the networks book", "minutes": 45, "day": "tomorrow",
         "split": [{"text": "Read chapter 3 of the networks book", "minutes": 45}, {"text": "Email Sara about the lab", "minutes": 10},
                   {"text": "x", "minutes": 5}, {"text": "y", "minutes": 5}, {"text": "z", "minutes": 5}]},
        {"task": 2, "text": "Go to the gym and buy a car", "minutes": 9999, "day": far},
        {"task": 2, "text": "A second answer for the same task", "minutes": 10, "day": ""},
        {"task": 7, "text": "No such task", "minutes": 10, "day": ""},
        {"task": True, "text": "Not a number", "minutes": 10, "day": ""},
    ]}))
    r = client.post("/api/tidy/suggest", json={"kind": "tasks"})
    assert r.status_code == 200, r.text
    got = r.json()["result"]
    by = {i["id"]: i for i in got["items"]}
    assert set(by) == {a["id"], b["id"]}  # one proposal per task, only real ones
    one = by[a["id"]]
    assert one["text"] == "Read chapter 3 of the networks book" and one["minutes"] == 45 and one["due"] == tomorrow
    assert len(one["split"]) == 4  # at most 4 parts
    assert "chapter" in one["new_words"] and "read" in one["new_words"]  # words you did not write are marked
    two = by[b["id"]]
    assert two["minutes"] is None and two["due"] is None  # an impossible number or a far day is not used
    assert "car" in two["new_words"]
    sent = model.user()
    assert "networks book ch 3" in sent and "gym" in sent and 'trust="yours"' in sent
    assert "never add" in model.system().lower()


def test_a_note_rewrite_marks_new_words_and_keeps_model_markup_plain(client):
    page = client.post("/api/pages", json={"title": "Messy", "body": "meeting notes. sara said lab moved to thursday. see [[Lab]]"}).json()
    _model(client, Model({"body": "# Meeting\n\n- Sara said the lab moved to Thursday.\n- See [[Lab]].\n- Ask [[Secret plan]] about #urgent funding."}))
    got = client.post("/api/tidy/suggest", json={"kind": "note", "id": page["id"]}).json()["result"]
    assert "[[Lab]]" in got["body"]  # your own link stays a link
    assert "[[Secret plan]]" not in got["body"] and "#urgent" not in got["body"]  # the model's markup is plain text
    assert {"funding", "secret", "plan", "urgent"} <= set(got["new_words"])
    assert client.get(f"/api/pages/{page['id']}").json()["body"].startswith("meeting notes")  # nothing applied


def test_a_routine_rewrite_is_checked(client):
    r = client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "water", "minutes": 0}, {"text": "stretch", "minutes": 0}]}).json()
    _model(client, Model({"steps": [{"text": "Drink a glass of water", "minutes": 2}, {"text": "Stretch", "minutes": 999}]}))
    got = client.post("/api/tidy/suggest", json={"kind": "routine", "id": r["id"]}).json()["result"]
    assert got["steps"] == [{"text": "Drink a glass of water", "minutes": 2}, {"text": "Stretch", "minutes": 0}]
    assert {"drink", "glass"} <= set(got["new_words"])


def test_requests_are_checked_and_a_long_note_is_refused(client):
    _model(client, Model({"body": "x"}))
    assert client.post("/api/tidy/suggest", json={"kind": "note", "id": "f" * 32}).status_code == 404
    assert client.post("/api/tidy/suggest", json={"kind": "essay"}).status_code == 422
    long = client.post("/api/pages", json={"title": "Long", "body": "word " * 4000}).json()
    r = client.post("/api/tidy/suggest", json={"kind": "note", "id": long["id"]})
    assert r.status_code == 409 and "too long" in r.json()["detail"].lower()
    assert client.post("/api/tidy/suggest", json={"kind": "tasks"}).status_code == 409  # no open task


def test_kept_once_and_traceable(client):
    _task(client, "gym")
    model = _model(client, Model({"tasks": [{"task": 1, "text": "Go to the gym", "minutes": 60, "day": ""}]}))
    one = client.post("/api/tidy/suggest", json={"kind": "tasks"}).json()["result"]
    two = client.post("/api/tidy/suggest", json={"kind": "tasks"}).json()["result"]
    assert one["id"] == two["id"] and len(model.requests) == 1
    assert client.get(f"/api/ai/why/{one['id']}").json()["feature"] == "tidy"


# ------------------------------------------------------------------ found by the review of 5.2 and 5.3
def test_a_long_note_rewrite_is_not_cut_and_a_short_one_says_what_went_missing(client):
    long_body = "\n".join(f"Line {i} about the routers and the switches in the lab." for i in range(120))  # about 6,500 characters
    page = client.post("/api/pages", json={"title": "Long", "body": long_body}).json()
    _model(client, Model({"body": long_body.replace("Line", "Point")}))
    got = client.post("/api/tidy/suggest", json={"kind": "note", "id": page["id"]}).json()["result"]
    assert len(got["body"]) > 6_000
    page2 = client.post("/api/pages", json={"title": "Short", "body": long_body}).json()
    _model(client, Model({"body": "Line 1 about the routers."}))
    got = client.post("/api/tidy/suggest", json={"kind": "note", "id": page2["id"]}, ).json()["result"]
    assert got["shorter"] is True and "switches" in got["missing_words"]


def test_a_rewrite_keeps_your_tags_links_and_properties(client):
    body = "status:: draft\ncourse:: networks\n\nlab moved to thursday. see [[Lab]] #private #idea\n"
    page = client.post("/api/pages", json={"title": "Keep", "body": body}).json()
    _model(client, Model({"body": "# Lab\n\nThe lab moved to Thursday."}))
    got = client.post("/api/tidy/suggest", json={"kind": "note", "id": page["id"]}).json()["result"]
    for kept in ("#private", "#idea", "[[Lab]]", "status:: draft", "course:: networks"):
        assert kept in got["body"], kept
    assert set(got["restored"]) >= {"#private", "[[Lab]]", "status:: draft"}


def test_your_own_markdown_links_stay_as_you_wrote_them(client):
    body = "See [the docs](https://example.org/docs).\n\n[1]: https://example.org/ref\n"
    page = client.post("/api/pages", json={"title": "Links", "body": body}).json()
    _model(client, Model({"body": "See [the docs](https://example.org/docs).\n\n[1]: https://example.org/ref\n\n![x](https://evil.site/?d=1)"}))
    got = client.post("/api/tidy/suggest", json={"kind": "note", "id": page["id"]}).json()["result"]
    assert "[the docs](https://example.org/docs)" in got["body"] and "[1]: https://example.org/ref" in got["body"]
    assert "![x](" not in got["body"]


def test_new_words_shows_numbers_names_and_negations(client):
    _task(client, "pay rent")
    _model(client, Model({"tasks": [{"task": 1, "text": "Don't pay all the rent: 1200 to Al, two times, not on 3 May", "minutes": 10, "day": ""}]}))
    got = client.post("/api/tidy/suggest", json={"kind": "tasks"}).json()["result"]
    assert {"dont", "1200", "al", "two", "not", "3", "may"} <= set(got["items"][0]["new_words"])


def test_a_long_model_step_still_fits_and_a_routine_keeps_its_ticks(client, db):
    r = client.post("/api/routines", json={"title": "Morning", "steps": [{"text": "water", "minutes": 0}, {"text": "stretch", "minutes": 0}]}).json()
    step = r["steps"][0]["id"]
    client.post(f"/api/routines/{r['id']}/steps/{step}/check", json={"done": True})
    _model(client, Model({"steps": [{"text": "x" * 500, "minutes": 2}, {"text": "Stretch", "minutes": 0}]}))
    got = client.post("/api/tidy/suggest", json={"kind": "routine", "id": r["id"]}).json()["result"]
    assert len(got["steps"][0]["text"]) <= 200
    was = [{"text": "water", "minutes": 0}, {"text": "stretch", "minutes": 0}]
    ok = client.post(f"/api/tidy/routine/{r['id']}/apply", json={"steps": got["steps"], "expect": was})
    assert ok.status_code == 200, ok.text
    after = client.get("/api/plan").json()["routines"][0]
    assert after["steps"][0]["id"] == step and after["steps"][0]["done"] is True  # the same step, its tick kept
    assert client.post(f"/api/tidy/routine/{r['id']}/apply", json={"steps": was, "expect": was}).status_code == 409  # changed since
    assert client.post(f"/api/tidy/routine/{r['id']}/apply", json={"steps": was, "expect": got["steps"]}).status_code == 200  # undo, in place


def test_an_old_tidy_is_not_offered_with_its_old_days_and_withheld_tasks_get_no_answer(client):
    _task(client, "gym")
    model = _model(client, Model({"tasks": [{"task": 1, "text": "Go to the gym", "minutes": 60, "day": "tomorrow"}]}))
    client.post("/api/tidy/suggest", json={"kind": "tasks"})
    import datetime as _dt
    from unittest import mock
    later = _dt.date.today() + _dt.timedelta(days=5)
    with mock.patch("readhold.ai.tidy.dt") as fake:
        fake.date.today.return_value = later
        fake.date.fromisoformat = _dt.date.fromisoformat
        fake.timedelta = _dt.timedelta
        client.post("/api/tidy/suggest", json={"kind": "tasks"})
    assert len(model.requests) == 2  # a new day is a new question: "tomorrow" is worked out again


# ------------------------------------------------------------------ asked for on 2026-11-26
def test_a_tidied_note_has_no_label_line(client):
    """The owner asked: no "Tidied by the AI model" line in the note. What you Use is yours."""
    page = client.post("/api/pages", json={"title": "Messy", "body": "meeting notes. sara said lab moved to thursday."}).json()
    _model(client, Model({"body": "# Meeting\n\n- Sara said the lab moved to Thursday."}))
    got = client.post("/api/tidy/suggest", json={"kind": "note", "id": page["id"]}).json()["result"]
    assert got["body"].startswith("# Meeting") and "Tidied by" not in got["body"] and "AI model" not in got["body"]


def test_the_model_is_told_never_to_translate(client):
    """The owner saw a note come back translated. The prompt now says, in so many words, never to translate."""
    page = client.post("/api/pages", json={"title": "ملاحظات", "body": "اجتماع غدا مع سارة"}).json()
    model = _model(client, Model({"body": "اجتماع غدًا مع سارة"}))
    client.post("/api/tidy/suggest", json={"kind": "note", "id": page["id"]})
    assert "never translate" in model.system().lower() and "same language" in model.system().lower()

