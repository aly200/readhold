"""Plan chat (milestone 5.3): tasks drafted from what you type, added only when you click, with Undo.

You write ("plan my week around the exam on Friday"); the model answers with a short reply and at most 12 draft
tasks (text, day, minutes). Code gives it your free minutes per day and your open tasks and deadlines, and checks
every draft: a real day from today to 60 days ahead, minutes 5 to 240, the day's free time, not a task you already
have. Nothing is added by asking: one click adds the drafts you keep, as one batch, and Undo takes it back.
No test reaches a real server (see conftest)."""
import datetime as dt
import json

import httpx

from tests.test_ai import LOCAL

TODAY = dt.date.today()
TOMORROW = (TODAY + dt.timedelta(days=1)).isoformat()


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


def _model(client, model):
    client.app.state.ai.transport = httpx.MockTransport(model)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=LOCAL)
    return model


def _chat(client, text="Plan my study for the exam this week", earlier=(), per_day=120):
    msgs = [*earlier, {"who": "you", "text": text}]
    return client.post("/api/plan/chat", json={"messages": msgs, "minutes_a_day": per_day})


DRAFTS = {"reply": "Here is a plan for the next days.", "tasks": [
    {"text": "Read chapter 3 of the networks book", "day": "tomorrow", "minutes": 60},
    {"text": "Do the practice exam", "day": TOMORROW, "minutes": 90},
    {"text": "Rest", "day": (TODAY - dt.timedelta(days=3)).isoformat(), "minutes": 30},
    {"text": "Revise everything", "day": (TODAY + dt.timedelta(days=200)).isoformat(), "minutes": 9999},
    {"text": "email the professor", "day": "", "minutes": 10},
]}


def test_with_ai_off_nothing_is_sent(client):
    model = Model(DRAFTS)
    client.app.state.ai.transport = httpx.MockTransport(model)
    assert _chat(client).status_code == 409 and model.requests == []


def test_the_model_reads_your_days_tasks_and_deadlines_and_what_you_wrote(client):
    client.post("/api/todos", json={"text": "Email the professor", "minutes": 15, "due": TOMORROW})
    client.post("/api/import/text", json={"title": "", "text": "# Networks Book\n\n## One\n\nRouters forward packets.\n", "format": "markdown"})
    doc = client.get("/api/documents").json()[0]
    client.patch(f"/api/documents/{doc['id']}", json={"deadline": (TODAY + dt.timedelta(days=5)).isoformat()})
    model = _model(client, Model(DRAFTS))
    earlier = [{"who": "you", "text": "I have an exam on Friday"}, {"who": "model", "text": "Good luck, let us plan it."}]
    r = _chat(client, "Spread the reading over the week", earlier)
    assert r.status_code == 200, r.text
    user = model.user()
    assert "<question>\nSpread the reading over the week\n</question>" in user
    assert "Email the professor" in user and "Networks Book" in user
    assert f"{TOMORROW}" in user and "free" in user  # the days and their free minutes, worked out by code
    assert 'trust="model"' in user and "I have an exam on Friday" in user  # the conversation so far, the model's part marked as its own


def test_every_draft_is_checked_and_nothing_is_added_by_asking(client, db):
    client.post("/api/todos", json={"text": "Email the professor", "minutes": 15, "due": TOMORROW})
    _model(client, Model(DRAFTS))
    before = db.scalar("SELECT COUNT(*) FROM todos")
    got = _chat(client, per_day=120).json()["result"]
    assert db.scalar("SELECT COUNT(*) FROM todos") == before  # nothing is added until you click
    d = {x["text"]: x for x in got["drafts"]}
    assert "Email the professor" not in d and got["already"] == 1  # a task you already have is not drafted again
    assert d["Read chapter 3 of the networks book"]["due"] == TOMORROW
    assert d["Rest"]["due"] is None and "day" in " ".join(d["Rest"]["flags"])  # a past day is not used
    assert d["Revise everything"]["due"] is None and d["Revise everything"]["minutes"] == 25 and d["Revise everything"]["flags"]
    over = d["Do the practice exam"]  # 15 already planned + 60 + 90 > 120 free minutes tomorrow
    assert over["fits"] is False and any("free" in f for f in over["flags"])
    assert got["reply"] == "Here is a plan for the next days."


def test_at_most_twelve_drafts(client):
    _model(client, Model({"reply": "Many.", "tasks": [{"text": f"Read part {i}", "day": "", "minutes": 20} for i in range(30)]}))
    got = _chat(client).json()["result"]
    assert len(got["drafts"]) == 12 and got["dropped"] == 18


def test_one_click_adds_the_drafts_you_keep_and_undo_takes_them_back(client, db):
    _model(client, Model(DRAFTS))
    got = _chat(client).json()["result"]
    url = f"/api/plan/chat/{got['id']}/add"
    pick = [{"index": 0, "text": got["drafts"][0]["text"], "due": got["drafts"][0]["due"], "minutes": 45},
            {"index": 1, "text": "Do the practice exam (my words)", "due": TOMORROW, "minutes": 90}]
    r = client.post(url, json={"items": pick})
    assert r.status_code == 200, r.text
    batch = r.json()["batch"]
    rows = db.all("SELECT * FROM todos WHERE plan_batch=? AND deleted=0 ORDER BY ord", (batch,))
    assert [x["text"] for x in rows] == ["Read chapter 3 of the networks book", "Do the practice exam (my words)"]
    assert rows[0]["minutes"] == 45 and all("drafted by the ai model" in x["note"].lower() for x in rows)
    assert client.post(url, json={"items": pick}).json()["added"] == 0  # once only
    assert client.post(url, json={"items": [{"index": 99, "text": "x", "due": None, "minutes": 10}]}).status_code == 409
    undo = client.post(f"/api/plan/chat/{got['id']}/undo", json={"batch": batch}).json()
    assert undo["removed"] == 2 and db.scalar("SELECT COUNT(*) FROM todos WHERE plan_batch=? AND deleted=0", (batch,)) == 0


def test_what_you_write_is_checked(client):
    _model(client, Model(DRAFTS))
    assert _chat(client, "x" * 1001).status_code in (409, 422)
    assert client.post("/api/plan/chat", json={"messages": [{"who": "you", "text": "hi"}] * 13, "minutes_a_day": 60}).status_code == 422
    assert client.post("/api/plan/chat", json={"messages": [{"who": "model", "text": "hi"}], "minutes_a_day": 60}).status_code == 422  # you speak last
    assert _chat(client, per_day=5).status_code == 422


# ------------------------------------------------------------------ found by the review of 5.2 and 5.3
def test_each_add_is_its_own_batch_and_undo_lets_you_add_again(client, db):
    _model(client, Model(DRAFTS))
    got = _chat(client).json()["result"]
    url = f"/api/plan/chat/{got['id']}"
    one = client.post(f"{url}/add", json={"items": [{"index": 0, "text": got["drafts"][0]["text"], "due": None, "minutes": 30}]}).json()
    two = client.post(f"{url}/add", json={"items": [{"index": 1, "text": got["drafts"][1]["text"], "due": None, "minutes": 30}]}).json()
    assert one["batch"] != two["batch"]
    undo = client.post(f"{url}/undo", json={"batch": two["batch"]}).json()
    assert undo["removed"] == 1 and 1 not in undo["kept"] and 0 in undo["kept"]  # only the second click is taken back
    again = client.post(f"{url}/add", json={"items": [{"index": 1, "text": got["drafts"][1]["text"], "due": None, "minutes": 30}]}).json()
    assert again["added"] == 1  # and it can be added again


def test_a_day_that_does_not_exist_is_refused_and_chat_batches_are_not_a_reading_plan(client):
    _model(client, Model(DRAFTS))
    got = _chat(client).json()["result"]
    url = f"/api/plan/chat/{got['id']}/add"
    bad = client.post(url, json={"items": [{"index": 0, "text": "x", "due": f"{TODAY.year + 1}-11-31", "minutes": 30}]})
    assert bad.status_code == 409
    client.post(url, json={"items": [{"index": 0, "text": "Read", "due": TOMORROW, "minutes": 30}]})
    assert client.get("/api/reading-plan").json()["last_batch"] is None  # the reading plan does not offer to take it back


def test_a_private_document_is_not_named_through_a_task_or_an_earlier_reply(client):
    from readhold.ai import keys
    from tests.test_ai import CLOUD, KEY
    r = client.post("/api/import/text", json={"title": "", "text": "# Diary\n\n## One\n\nToday I wrote about many private things.\n", "format": "markdown"}).json()
    client.put(f"/api/documents/{r['id']}/tags", json={"tags": ["private"]})
    client.post("/api/todos", json={"text": "Read the next part", "minutes": 25, "link_type": "document", "link_id": r["id"]})
    seen = []

    def cloud(request):
        seen.append(request.content.decode())
        out = {"reply": "Fine.", "tasks": []}
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(out)}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}})

    client.app.state.ai.transport = httpx.MockTransport(cloud)
    client.app.state.ai.retry_wait = 0
    keys.save("anthropic", KEY)
    client.put("/api/settings", json=CLOUD)
    earlier = [{"who": "you", "text": "What should I read?"}, {"who": "model", "text": "Read Diary: Today I wrote about many private things."}]
    assert _chat(client, "Plan my week", earlier).status_code == 200
    sent = "".join(seen)
    assert "Read the next part" not in sent and "many private things" not in sent


# ------------------------------------------------------------------ found while writing the Phase 5 docs
def test_the_why_panel_names_the_chats_sources(client):
    client.post("/api/todos", json={"text": "Email the professor", "minutes": 15})
    _model(client, Model(DRAFTS))
    earlier = [{"who": "you", "text": "I have an exam"}, {"who": "model", "text": "Let us plan it."}]
    got = _chat(client, "Plan the week", earlier).json()["result"]
    src = client.get(f"/api/ai/why/{got['id']}").json()["calls"][0]["sources"]
    names = {s["kind"]: s["title"] for s in src}
    assert names["days"] == "your next days and their free minutes" and names["task"] == "Email the professor"
    assert "earlier message" in names["turn"]


def test_your_newest_message_is_checked_for_private_text_too(client):
    from readhold.ai import keys
    from tests.test_ai import CLOUD, KEY
    r = client.post("/api/import/text", json={"title": "", "text": "# Diary\n\n## One\n\nToday I wrote about many very private things at home.\n", "format": "markdown"}).json()
    client.put(f"/api/documents/{r['id']}/tags", json={"tags": ["private"]})
    seen = []
    client.app.state.ai.transport = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(500))
    keys.save("anthropic", KEY)
    client.put("/api/settings", json=CLOUD)
    got = _chat(client, "Plan around this: Today I wrote about many very private things at home.")
    assert got.status_code == 409 and "private" in got.json()["detail"].lower() and seen == []


def test_a_task_you_have_is_known_however_many_open_tasks_there_are(client, db):
    from readhold.db import new_id, now
    t = now()
    db.conn.executemany("INSERT INTO todos (id, text, minutes, ord, device_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        [(new_id(), f"Filler task {i}", 10, i, db.device, t, t) for i in range(60)])
    client.post("/api/todos", json={"text": "Email the professor", "minutes": 15})
    _model(client, Model(DRAFTS))
    got = _chat(client).json()["result"]
    assert got["already"] == 1 and "email the professor" not in [d["text"].lower() for d in got["drafts"]]


def test_the_minutes_a_day_are_kept_as_a_setting(client):
    assert client.get("/api/settings").json()["plan_minutes_a_day"] == 120
    assert client.put("/api/settings", json={"plan_minutes_a_day": 90}).json()["plan_minutes_a_day"] == 90
