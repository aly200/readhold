"""'Why did it say this?' (AI plan, milestone 4.2): any AI result can be traced to its prompt and its sources.

For a kept result: every model call behind it (from the AI log: model, prompt version, tokens, time, retries, checks),
the text of each prompt version used, the sources each call was sent (anchors resolved to titles, never their
text), and how many of its quotes were checked. No test reaches a real server (see conftest)."""
import json

import httpx

from readhold.ai import prompts
from tests.conftest import SAMPLE_MD
from tests.test_ai import LOCAL
from tests.test_ai_citations import REAL, _doc, _server, _sentences


def _why(client, rid):
    return client.get(f"/api/ai/why/{rid}")


def _ask(client, doc_id):
    r = client.post(f"/api/documents/{doc_id}/ask", json={"question": "What is the SMR gating network over token blocks?", "fresh": True})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_an_answer_traces_to_its_prompt_model_sources_and_checks(client):
    doc = _doc(client)
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    r = _why(client, res["id"])
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["feature"] == "ask" and w["status"] == "verified"
    assert w["checked"] == {"verified": 1, "unchecked": 0}
    (call,) = w["calls"]
    assert call["task"] == "ask" and call["outcome"] == "ok" and call["prompt_version"] == prompts.load("ask").version
    assert call["provider"] == "local" and call["tokens_in"] > 0 and call["attempts"] == 1
    assert call["checks"]["fenced"] >= 1
    assert w["prompts"][call["prompt_version"]] == prompts.load("ask").text  # the instruction itself, word for word
    src = call["sources"]
    by = _sentences(client, doc["id"])
    method = next(s for s in src if s["kind"] == "document" and s["section_title"] == "Method")
    assert method["document_title"] == "Attention Is a Test" and method["trust"] == "imported" and method["chars"] > 0
    assert method["sentence"] <= by[REAL][0]
    assert REAL not in json.dumps(src)  # what a source said is not repeated here, only where it is


def test_a_feature_with_several_calls_lists_them_all(client):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    client.post("/api/highlights", json={"document_id": doc["id"], "sentence": by[REAL][0], "end_sentence": by[REAL][0], "type": "claim"})
    _server(client, lambda f: REAL)
    res = client.post("/api/brainstorm", json={"kind": "document", "id": doc["id"], "fresh": True}).json()["result"]
    w = _why(client, res["id"]).json()
    assert [c["task"] for c in w["calls"]] == ["brainstorm"] * 3 + ["brainstorm_critic"]  # three samples, then the critic
    assert set(w["prompts"]) == {prompts.load("brainstorm").version, prompts.load("brainstorm_critic").version}
    assert w["calls"][3]["sources"][0]["kind"] == "model"  # the critic read the ideas, as the model's text


def test_a_digest_shows_its_part_calls_too(client):
    from tests.test_ai_digest import _wait
    doc = _doc(client)
    _server(client, lambda f: REAL)
    client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True})
    d = _wait(client, doc["id"])["digest"]
    w = _why(client, d["id"]).json()
    tasks = [c["task"] for c in w["calls"]]
    assert tasks[-1] == "digest" and "digest_map" in tasks


def test_your_notes_and_other_sources_are_named(client):
    _doc(client)
    client.post("/api/pages", json={"title": "Starter care", "body": "My starter likes the SMR gating network over token blocks a lot."})
    _server(client, lambda f: REAL)
    res = client.post("/api/library/ask", json={"question": "What is the SMR gating network over token blocks?", "fresh": True}).json()["result"]
    src = _why(client, res["id"]).json()["calls"][0]["sources"]
    note = next(s for s in src if s["kind"] == "note")
    assert note["title"] == "Starter care" and note["trust"] == "yours"


def test_when_the_log_is_gone_the_result_says_so(client, db):
    doc = _doc(client)
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    db.execute("DELETE FROM ai_log")
    w = _why(client, res["id"]).json()
    assert w["calls"] == [] and w["log_gone"] is True and w["model"]  # what the result itself recorded still shows


def test_unknown_cleared_or_removed_results_are_not_found(client):
    doc = _doc(client)
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    assert _why(client, "f" * 32).status_code == 404
    assert _why(client, "nope").status_code == 404
    client.delete(f"/api/documents/{doc['id']}")
    assert _why(client, res["id"]).status_code == 404
    doc2 = _doc(client, SAMPLE_MD)
    res2 = _ask(client, doc2["id"])
    client.delete("/api/ai/log")
    assert _why(client, res2["id"]).status_code == 404


def test_works_with_ai_switched_off_afterwards(client):
    doc = _doc(client)
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    client.put("/api/settings", json={**LOCAL, "ai_mode": "off"})
    assert _why(client, res["id"]).status_code == 200  # reading the log never calls a model


def test_no_model_call_is_made_to_explain(client):
    doc = _doc(client)
    calls = []
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    client.app.state.ai.transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    _why(client, res["id"])
    assert calls == []


def test_a_call_logged_before_sources_were_kept_says_so(client, db):
    doc = _doc(client)
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    db.execute("UPDATE ai_log SET checks=? WHERE id=?", (json.dumps({"fenced": 2}), res["log_id"]))
    (call,) = _why(client, res["id"]).json()["calls"]
    assert call["sources_recorded"] is False and call["sources"] == [] and call["checks"] == {"fenced": 2}


# ------------------------------------------------------------------ found by the review of 4.2
def test_a_digest_lists_its_own_part_calls_not_older_ones(client, db):
    from tests.test_ai_digest import _wait
    doc = _doc(client)
    _server(client, lambda f: REAL)
    client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True})
    d = _wait(client, doc["id"])["digest"]
    before = [c["id"] for c in _why(client, d["id"]).json()["calls"]]
    other = _ask(client, doc["id"])  # a call that has nothing to do with the digest, dressed up as an older part
    db.execute("INSERT INTO ai_results (id, feature, target_type, target_id, input_key, payload, log_id, device_id, created_at, updated_at)"
               " VALUES (?, 'digest_map', 'document', ?, 'old', '{}', ?, 'x', '2000-01-01', '2000-01-01')", ("e" * 32, doc["id"], other["log_id"]))
    assert [c["id"] for c in _why(client, d["id"]).json()["calls"]] == before


def test_a_call_that_failed_is_shown_with_its_outcome(client):
    from tests.test_ai_brainstorm import Model, _model, _setup
    _, _, note = _setup(client)
    _model(client, Model(critic="not json at all"))
    res = client.post("/api/brainstorm", json={"kind": "page", "id": note["id"]}).json()["result"]
    calls = _why(client, res["id"]).json()["calls"]
    assert [c["task"] for c in calls][-1] == "brainstorm_critic" and calls[-1]["outcome"] == "invalid"


def test_every_kind_of_your_own_source_is_named(client):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    _server(client, lambda f: REAL)
    r = client.post(f"/api/documents/{doc['id']}/explain", json={"sentence": by[REAL][0], "end_sentence": by[REAL][0], "level": "student",
                                                                "attempt": "I think it picks which blocks count.", "fresh": True}).json()["result"]
    src = _why(client, r["id"]).json()["calls"][0]["sources"]
    mine = next(s for s in src if s["anchor"].startswith("attempt:"))
    assert mine["kind"] == "attempt" and "attempt" in mine["title"] and mine["title"] != "attempt"


def test_a_removed_source_has_no_link(client, db):
    _doc(client)
    note = client.post("/api/pages", json={"title": "Starter care", "body": "My starter likes the SMR gating network over token blocks a lot."}).json()
    _server(client, lambda f: REAL)
    res = client.post("/api/library/ask", json={"question": "What is the SMR gating network over token blocks?", "fresh": True}).json()["result"]
    db.execute("UPDATE pages SET deleted=1 WHERE id=?", (note["id"],))  # removed without going through the route
    src = _why(client, res["id"]).json()["calls"][0]["sources"]
    gone = next(s for s in src if s["anchor"] == f"note:{note['id']}")
    assert gone["kind"] == "gone" and "note_id" not in gone


def test_a_long_list_of_sources_says_how_many_more(client, db):
    from readhold.ai import guard
    srcs = [guard.Source(f"note:{'a' * 31}{i % 10}", f"text {i}", "yours") for i in range(70)]
    packed = guard.pack(db, srcs, "notes")
    assert len(packed.checks["sources"]) == guard.MAX_LISTED and packed.checks["sources_more"] == 70 - guard.MAX_LISTED


def test_the_preview_of_what_was_sent_is_not_returned(client):
    doc = _doc(client)
    _server(client, lambda f: REAL)
    res = _ask(client, doc["id"])
    (call,) = _why(client, res["id"]).json()["calls"]
    assert "input_preview" not in call


def test_a_failed_call_keeps_its_sources(client):
    from tests.test_ai_brainstorm import Model, _model, _setup
    _, _, note = _setup(client)
    _model(client, Model(critic="not json at all"))
    res = client.post("/api/brainstorm", json={"kind": "page", "id": note["id"]}).json()["result"]
    failed = _why(client, res["id"]).json()["calls"][-1]
    assert failed["outcome"] == "invalid" and failed["sources_recorded"] and failed["sources"][0]["kind"] == "model"
