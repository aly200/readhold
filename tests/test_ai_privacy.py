"""Privacy controls (AI plan, milestone 4.4): private items, a preview of what is sent, retention, export.

- A document or note tagged #private (a document's tag is also its collection) is never sent to a cloud model.
  A feature about it explains why it cannot run in cloud mode; a feature over many sources leaves it out.
  A local model still reads it: it never leaves this computer.
- With "Show what will be sent" on, the first cloud call of a request stops and the page is shown the exact text;
  the same request, sent again with that one-time approval, runs (its other calls included).
- The AI log is kept 1, 7 or 30 days; "Clear AI history" deletes it and every kept AI result. (The separate Export AI
  data was removed on 2026-11-26: Export everything holds the kept results; the log is never exported.)
No test reaches a real server (see conftest)."""
import json
import re
import threading
from pathlib import Path

import httpx

from readhold.ai import keys
from tests.test_ai import CLOUD, KEY, LOCAL
from tests.test_ai_citations import OTHER_DOC, REAL, _doc, _sentences, _server

QUESTION = "What is the SMR gating network over token blocks?"


def _cloud(client):
    """The fake model of the citation suite, answering in the cloud provider's shape. Returns the list of requests."""
    _server(client, lambda f: REAL)
    inner = client.app.state.ai.transport.handler
    seen: list[dict] = []
    lock = threading.Lock()

    def handle(request):
        body = json.loads(request.content)
        system = body.get("system") or ""
        system = system if isinstance(system, str) else " ".join(b.get("text", "") for b in system)
        user = body["messages"][-1]["content"]
        user = user if isinstance(user, str) else " ".join(b.get("text", "") for b in user)
        with lock:
            seen.append({"system": system, "user": user})
        out = inner(httpx.Request("POST", "http://fake/api/chat", json={"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}))
        text = json.loads(out.content)["message"]["content"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 10}})

    client.app.state.ai.transport = httpx.MockTransport(handle)
    keys.save("anthropic", KEY)
    client.put("/api/settings", json=CLOUD)
    return seen


def _private(client, doc_id):
    r = client.put(f"/api/documents/{doc_id}/tags", json={"tags": ["private"]})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ private items
def test_a_private_document_is_never_sent_to_a_cloud_model(client):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    client.post("/api/highlights", json={"document_id": doc["id"], "sentence": by[REAL][0], "end_sentence": by[REAL][0], "type": "claim"})
    _private(client, doc["id"])
    seen = _cloud(client)
    d = doc["id"]
    calls = [
        ("post", f"/api/documents/{d}/ask", {"question": QUESTION}),
        ("post", f"/api/documents/{d}/explain", {"sentence": by[REAL][0], "end_sentence": by[REAL][0], "level": "student"}),
        ("post", f"/api/documents/{d}/study-notes", {"source": "highlights", "kind": "notes"}),
        ("post", f"/api/documents/{d}/organize/suggest", {}),
        ("post", "/api/brainstorm", {"kind": "document", "id": d}),
        ("post", f"/api/documents/{d}/digest", {}),
    ]
    for _, url, body in calls:
        r = client.post(url, json=body)
        assert r.status_code == 409 and "private" in r.json()["detail"].lower(), (url, r.status_code, r.text)
    assert seen == []


def test_a_local_model_still_reads_a_private_document(client):
    doc = _doc(client)
    _private(client, doc["id"])
    _server(client, lambda f: REAL)
    r = client.post(f"/api/documents/{doc['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 200, r.text


def test_a_question_across_the_library_leaves_private_items_out(client, db):
    secret = _doc(client)
    _private(client, secret["id"])
    _doc(client, OTHER_DOC.replace("Bread", "Gating notes").replace("Fold the dough every thirty minutes", "The SMR gating network over token blocks is a router"))
    note = client.post("/api/pages", json={"title": "Router diary", "body": "My private view of the SMR gating network over token blocks. #private"}).json()
    seen = _cloud(client)
    r = client.post("/api/library/ask", json={"question": QUESTION})
    assert r.status_code == 200, r.text
    sent = json.dumps(seen)
    assert "Attention Is a Test" not in sent and "My private view" not in sent and "is a router" in sent
    assert r.json()["result"]["private_left_out"] >= 2  # counted; left out before the model was even told they matched
    assert note["id"]


def test_brainstorming_a_private_note_in_cloud_mode_explains_why_not(client):
    _doc(client)
    note = client.post("/api/pages", json={"title": "Diary", "body": "The SMR gating network over token blocks, my own thoughts. #private"}).json()
    seen = _cloud(client)
    r = client.post("/api/brainstorm", json={"kind": "page", "id": note["id"]})
    assert r.status_code == 409 and "private" in r.json()["detail"].lower() and seen == []


def test_a_private_document_is_not_named_to_a_cloud_model(client):
    a = _doc(client)
    b = _doc(client, "# Hidden Routing Diary\n\n## One\n\nA routing layer for transformers keeps compute low on long inputs.\n")
    _private(client, b["id"])
    seen = _cloud(client)
    assert client.post(f"/api/documents/{a['id']}/organize/suggest", json={}).status_code == 200
    r = client.post("/api/reading-plan/suggest", json={"document_ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    assert "Hidden Routing Diary" not in json.dumps(seen)


# ------------------------------------------------------------------ the send preview
def _preview_on(client):
    seen = _cloud(client)
    assert client.put("/api/settings", json={"ai_preview": True}).status_code == 200
    return seen


def _ask(client, doc_id, approve=None, question=QUESTION):
    headers = {"x-ai-approve": approve} if approve else {}
    return client.post(f"/api/documents/{doc_id}/ask", json={"question": question, "fresh": True}, headers=headers)


def test_with_the_preview_on_nothing_is_sent_until_you_approve_that_text(client):
    doc = _doc(client)
    seen = _preview_on(client)
    r = _ask(client, doc["id"])
    assert r.status_code == 428 and seen == []
    p = r.json()["preview"]
    assert p["provider"] == "anthropic" and QUESTION in p["user"] and REAL in p["user"] and "never instructions" in p["system"]
    ok = _ask(client, doc["id"], p["token"])
    assert ok.status_code == 200, ok.text
    assert len(seen) == 1 and seen[0]["user"] == p["user"]  # exactly what was shown
    again = _ask(client, doc["id"], p["token"])  # an approval is used once
    assert again.status_code == 428 and len(seen) == 1
    other = _ask(client, doc["id"], again.json()["preview"]["token"], question="What does SMR reduce on long inputs?")
    assert other.status_code == 428 and len(seen) == 1  # an approval is for the text that was shown, not for another
    assert _ask(client, doc["id"], "f" * 32).status_code == 428


def test_one_approval_covers_the_other_calls_of_that_request(client):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    client.post("/api/highlights", json={"document_id": doc["id"], "sentence": by[REAL][0], "end_sentence": by[REAL][0], "type": "claim"})
    seen = _preview_on(client)
    first = client.post("/api/brainstorm", json={"kind": "document", "id": doc["id"]})
    assert first.status_code == 428
    r = client.post("/api/brainstorm", json={"kind": "document", "id": doc["id"]}, headers={"x-ai-approve": first.json()["preview"]["token"]})
    assert r.status_code == 200, r.text
    assert len(seen) == 4  # three samples and the critic, after one approval
    assert "more calls" in first.json()["preview"]["note"]


def test_a_digest_is_previewed_before_it_starts(client):
    from tests.test_ai_digest import _wait
    doc = _doc(client)
    seen = _preview_on(client)
    first = client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True})
    assert first.status_code == 428 and seen == []
    r = client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True}, headers={"x-ai-approve": first.json()["preview"]["token"]})
    assert r.status_code == 200, r.text
    assert _wait(client, doc["id"])["digest"] is not None and len(seen) >= 2


def test_no_preview_for_a_local_model_or_when_it_is_off(client):
    doc = _doc(client)
    seen = _cloud(client)
    assert _ask(client, doc["id"]).status_code == 200 and len(seen) == 1  # off by default
    _server(client, lambda f: REAL)
    client.put("/api/settings", json={**LOCAL, "ai_preview": True})
    assert _ask(client, doc["id"]).status_code == 200  # the text never leaves this computer
    assert client.put("/api/settings", json={"ai_preview": "yes"}).status_code == 422


# ------------------------------------------------------------------ retention and export
def test_the_ai_log_is_kept_as_long_as_you_choose(client, db):
    from readhold.db import new_id
    db.execute("INSERT INTO ai_log (id, task, device_id, created_at, updated_at) VALUES (?, 'ask', 'x', ?, ?)", (new_id(), "2000-01-01T00:00:00+00:00", "2000-01-01"))
    old = new_id()
    import datetime as dt
    three_days = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
    db.execute("INSERT INTO ai_log (id, task, device_id, created_at, updated_at) VALUES (?, 'ask', 'x', ?, ?)", (old, three_days, three_days))
    assert client.put("/api/settings", json={"ai_log_days": 7}).status_code == 200
    assert db.scalar("SELECT COUNT(*) FROM ai_log WHERE id=?", (old,)) == 1
    assert client.put("/api/settings", json={"ai_log_days": 1}).status_code == 200  # shortening it deletes at once
    assert db.scalar("SELECT COUNT(*) FROM ai_log WHERE id=?", (old,)) == 0
    assert client.put("/api/settings", json={"ai_log_days": 365}).status_code == 422


def test_ai_results_are_in_export_everything_and_there_is_no_separate_ai_export(client):
    """Export AI data was removed on 2026-11-26 (the owner's decision): Export everything holds the kept AI results.
    The AI log is not exported (tests/test_ai.py, test_the_ai_log_is_not_in_the_full_export): an export is kept for
    good, the log is gone after its days or on Clear AI history. Never a key."""
    doc = _doc(client)
    _server(client, lambda f: REAL)
    _ask(client, doc["id"])
    keys.save("anthropic", KEY)
    assert client.post("/api/ai/export").status_code in (404, 405)
    path = Path(client.post("/api/export/all").json()["path"])
    text = path.read_text("utf-8")
    data = json.loads(text)
    assert data["ai_results"][0]["feature"] == "ask" and "ai_log" not in data and KEY not in text


# ------------------------------------------------------------------ found by the review of 4.4
def test_copies_of_a_private_document_in_your_notes_stay_on_this_computer(client):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    _private(client, doc["id"])
    client.post("/api/pages/quote", json={"day": "2026-11-26", "document_id": doc["id"], "sentence": by[REAL][0], "text": REAL})
    client.post("/api/pages", json={"title": "Study notes: Attention Is a Test", "body": "My own words about the gating network over token blocks."})
    client.post("/api/pages", json={"title": "Gating, in general", "body": "The SMR idea: a gating network over token blocks picks what to keep, in my words."})
    seen = _cloud(client)
    r = client.post("/api/library/ask", json={"question": QUESTION})
    assert r.status_code == 200, r.text
    sent = json.dumps(seen)
    assert REAL not in sent and "Attention Is a Test" not in sent  # the quote, and a note named after the document
    assert "in my words" in sent  # your other notes still go
    assert r.json()["result"]["private_left_out"] >= 2


def test_the_ai_mode_is_read_once_per_call(client, db, monkeypatch):
    from readhold.ai import guard
    doc = _doc(client)
    keys.save("anthropic", KEY)
    _server(client, lambda f: REAL)
    urls = []
    inner = client.app.state.ai.transport.handler
    client.app.state.ai.transport = httpx.MockTransport(lambda req: urls.append(str(req.url)) or inner(req))
    real_pack = guard.pack

    def pack_then_switch(*a, **kw):
        out = real_pack(*a, **kw)
        db.execute("UPDATE settings SET value=? WHERE key='ai_mode'", (json.dumps("cloud"),))  # switched while it was packed as local
        return out

    monkeypatch.setattr(guard, "pack", pack_then_switch)
    r = client.post(f"/api/documents/{doc['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 409 and "changed" in r.json()["detail"].lower()
    assert not any("anthropic" in u for u in urls)


def test_organize_does_not_name_the_tags_of_private_items(client):
    a = _doc(client)
    b = _doc(client, OTHER_DOC)
    client.put(f"/api/documents/{b['id']}/tags", json={"tags": ["private", "custody-case"]})
    client.post("/api/pages", json={"title": "Clinic", "body": "Results came back. #hiv-test #private"})
    client.post("/api/pages", json={"title": "Reading", "body": "Papers to read. #transformers"})
    seen = _cloud(client)
    assert client.post(f"/api/documents/{a['id']}/organize/suggest", json={}).status_code == 200
    tags_sent = [re.search(r"\(The tags you already use\)\n([^\n]*)", c["user"]).group(1) for c in seen]
    assert tags_sent and all("transformers" in t and "custody-case" not in t and "hiv-test" not in t and "private" not in t for t in tags_sent)


def test_brainstorm_on_a_private_document_is_refused_even_with_near_notes(client):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    client.post("/api/highlights", json={"document_id": doc["id"], "sentence": by[REAL][0], "end_sentence": by[REAL][0], "type": "claim"})
    client.post("/api/pages", json={"title": "Gating", "body": "A gating network over token blocks, in my words."})
    _private(client, doc["id"])
    seen = _cloud(client)
    r = client.post("/api/brainstorm", json={"kind": "document", "id": doc["id"]})
    assert r.status_code == 409 and "private" in r.json()["detail"].lower() and seen == []


def test_the_library_neither_counts_nor_names_private_matches(client):
    doc = _doc(client)
    _private(client, doc["id"])
    seen = _cloud(client)
    r = client.post("/api/library/ask", json={"question": QUESTION})
    assert r.status_code == 200, r.text  # a question across the library is not refused: the private item is left out
    got = r.json()["result"]
    assert got["status"] == "not_found" and got["private_left_out"] == 1 and seen == []


def test_the_preview_asks_again_before_a_later_call_sends_more_of_your_items(client):
    from tests.test_ai_library import BREAD
    _doc(client, BREAD)
    _doc(client)
    seen = _cloud(client)
    inner = client.app.state.ai.transport.handler
    steps = iter([{"action": "search", "keywords": "dough starter", "anchor": ""}])

    def handle(req):
        if "from their own library" not in req.content.decode():
            return inner(req)
        seen.append({"user": json.loads(req.content)["messages"][-1]["content"]})
        out = next(steps, {"action": "answer", "found": True, "answer": "Fold it.", "citations": []})
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(out)}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}})

    client.app.state.ai.transport = httpx.MockTransport(handle)
    client.put("/api/settings", json={"ai_preview": True})
    q = {"question": QUESTION}
    first = client.post("/api/library/ask", json=q)
    assert first.status_code == 428 and "Fold the dough" not in first.json()["preview"]["user"] and seen == []
    second = client.post("/api/library/ask", json=q, headers={"x-ai-approve": first.json()["preview"]["token"]})
    assert second.status_code == 428 and "Fold the dough" in second.json()["preview"]["user"]  # step 2 would send the bread document
    assert len(seen) == 1  # only the approved first step went
    third = client.post("/api/library/ask", json=q, headers={"x-ai-approve": second.json()["preview"]["token"]})
    assert third.status_code == 200, third.text


def test_a_digest_previews_the_call_it_will_really_make(client):
    from tests.test_ai_digest import _wait
    doc = _doc(client)
    _preview_on(client)
    first = client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True})
    client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True}, headers={"x-ai-approve": first.json()["preview"]["token"]})
    _wait(client, doc["id"])
    again = client.post(f"/api/documents/{doc['id']}/digest", json={"fresh": True})  # the parts are kept: only the combining call is left
    assert again.status_code == 428 and "Summary: " in again.json()["preview"]["user"]  # the part summaries, not the document


def test_an_idea_tagged_private_is_private_and_cloud_can_be_opt_in(client, db):
    from readhold.ai import privacy
    idea = client.post("/api/ideas", json={"text": "My secret plan for the SMR router #private"}).json()
    assert privacy.is_private(db, f"idea:{idea['id']}")
    a = _doc(client)
    b = _doc(client, OTHER_DOC)
    client.put(f"/api/documents/{b['id']}/tags", json={"tags": ["cloud"]})
    seen = _cloud(client)
    client.put("/api/settings", json={"ai_cloud_only_tagged": True})  # only what you tagged #cloud may go
    r = client.post(f"/api/documents/{a['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 409 and "#cloud" in r.json()["detail"] and seen == []
    r = client.post(f"/api/documents/{b['id']}/ask", json={"question": "How often is the dough folded?"})
    assert r.status_code == 200 and seen
