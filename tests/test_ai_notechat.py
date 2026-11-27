"""Note chat (milestone 5.4): tell a model what to do with the note you are in ("make it more formatted", "enhance
it", "write an idea for a story"). It answers with a short reply and a proposal: the whole note rewritten (replace),
new text to add at the end (add), or nothing. Nothing changes until you press Use or Add on the page, with Undo.
A rewrite is checked like Tidy's: your links, tags and properties are kept, markup the model adds stays plain text,
and every word you did not write is listed. No label line goes into your note. No test reaches a real server."""
import httpx

from tests.test_ai_tidy import Model, _model


def _note(client, body="meeting notes. sara said lab moved to thursday. see [[Lab]] #work", title="Messy"):
    return client.post("/api/pages", json={"title": title, "body": body}).json()


def _ask(client, page_id, text="make it more formatted", earlier=()):
    msgs = [*earlier, {"who": "you", "text": text}]
    return client.post(f"/api/notes/{page_id}/chat", json={"messages": msgs})


REWRITE = {"reply": "I gave it a heading and a list.", "action": "replace",
           "text": "# Meeting\n\n- Sara said the lab moved to Thursday.\n- See [[Lab]].\n- Ask [[Secret plan]] about #urgent funding."}
STORY = {"reply": "Here is an idea you could build on.", "action": "add",
         "text": "## Story idea\n\nA lighthouse keeper finds a map drawn in salt."}


def test_with_ai_off_nothing_is_sent(client):
    page = _note(client)
    model = Model(REWRITE)
    client.app.state.ai.transport = httpx.MockTransport(model)
    assert _ask(client, page["id"]).status_code == 409 and model.requests == []


def test_a_rewrite_is_proposed_checked_and_not_applied(client):
    page = _note(client)
    _model(client, Model(REWRITE))
    got = _ask(client, page["id"]).json()["result"]
    assert got["action"] == "replace" and got["reply"].startswith("I gave it")
    assert "[[Lab]]" in got["text"] and "#work" in got["text"]  # your own link stays; your tag is put back
    assert "[[Secret plan]]" not in got["text"] and "#urgent" not in got["text"]  # the model's markup is plain text
    assert {"funding", "secret", "plan", "urgent"} <= set(got["new_words"]) and "#work" in got["restored"]
    assert got["original"] == page["body"] and "AI model" not in got["text"]  # no label line in your note
    assert client.get(f"/api/pages/{page['id']}").json()["body"] == page["body"]  # nothing applied


def test_new_writing_is_proposed_as_text_to_add(client):
    page = _note(client, body="Ideas for the weekend.")
    _model(client, Model(STORY))
    got = _ask(client, page["id"], "write an idea about a story").json()["result"]
    assert got["action"] == "add" and got["text"].startswith("## Story idea") and got["new_words"] == []
    assert client.get(f"/api/pages/{page['id']}").json()["body"] == "Ideas for the weekend."


def test_an_empty_note_can_be_written_into(client):
    page = _note(client, body="", title="Story")
    _model(client, Model(STORY))
    got = _ask(client, page["id"], "write an idea about a story")
    assert got.status_code == 200 and got.json()["result"]["action"] == "add"


def test_what_the_model_is_given(client):
    page = _note(client)
    model = _model(client, Model(REWRITE))
    _ask(client, page["id"], "enhance it", earlier=[{"who": "you", "text": "hi"}, {"who": "model", "text": "Hello, what should I do?"}])
    sent = model.user()
    assert 'trust="yours"' in sent and "sara said lab moved" in sent and 'trust="model"' in sent
    assert "<question>\nenhance it\n</question>" in sent
    system = model.system().lower()
    assert "never translate" in system and "you cannot change the note yourself" in system


def test_a_reply_without_a_usable_proposal_is_just_a_reply(client):
    page = _note(client)
    _model(client, Model({"reply": "What kind of story?", "action": "delete everything", "text": "x"}))
    got = _ask(client, page["id"], "write something").json()["result"]
    assert got["action"] == "none" and got["text"] == "" and got["reply"] == "What kind of story?"
    _model(client, Model({"reply": "Done.", "action": "replace", "text": "   "}))
    got = _ask(client, page["id"], "tidy it please").json()["result"]
    assert got["action"] == "none"  # an empty rewrite would wipe the note: it is no proposal


def test_the_same_question_on_the_same_note_is_asked_once(client):
    page = _note(client)
    model = _model(client, Model(REWRITE))
    one = _ask(client, page["id"]).json()["result"]
    two = _ask(client, page["id"]).json()["result"]
    assert one["id"] == two["id"] and len(model.requests) == 1
    assert client.get(f"/api/ai/why/{one['id']}").json()["feature"] == "notechat"


def test_bad_requests(client):
    page = _note(client)
    _model(client, Model(REWRITE))
    assert _ask(client, "f" * 32).status_code == 404
    assert client.post(f"/api/notes/{page['id']}/chat", json={"messages": [{"who": "model", "text": "hi"}]}).status_code == 422
    too_many = [{"who": "you" if i % 2 == 0 else "model", "text": "hi"} for i in range(13)]
    assert client.post(f"/api/notes/{page['id']}/chat", json={"messages": too_many}).status_code == 422  # at most 12 messages
    long = _note(client, body="word " * 3000, title="Long")  # a second note needs its own title
    r = _ask(client, long["id"])
    assert r.status_code == 409 and "too long" in r.json()["detail"]


def test_a_private_note_never_leaves_this_computer(client):
    from readhold.ai import keys
    from tests.test_ai import CLOUD, KEY

    page = _note(client, body="my diary #private")
    seen = []
    client.app.state.ai.transport = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(500))
    keys.save("anthropic", KEY)
    client.put("/api/settings", json=CLOUD)
    r = _ask(client, page["id"])
    assert r.status_code == 409 and "private" in r.json()["detail"].lower() and seen == []


def test_your_message_is_checked_for_private_text_too(client):
    from readhold.ai import keys
    from tests.test_ai import CLOUD, KEY

    r = client.post("/api/import/text", json={"title": "", "text": "# Diary\n\n## One\n\nToday I wrote about many very private things at home.\n", "format": "markdown"}).json()
    client.put(f"/api/documents/{r['id']}/tags", json={"tags": ["private"]})
    page = _note(client, body="a plain note")
    seen = []
    client.app.state.ai.transport = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(500))
    keys.save("anthropic", KEY)
    client.put("/api/settings", json=CLOUD)
    got = _ask(client, page["id"], "Add this: Today I wrote about many very private things at home.")
    assert got.status_code == 409 and "private" in got.json()["detail"].lower() and seen == []
