"""Organize with a model (AI plan, milestone 3.3): suggested tags that reuse the ones you have, and related documents.

The model reads a document's title, section titles, its opening and your highlights, the tags you already use, and
the titles of documents code found related. It suggests tags (yours first; at most two new ones) and picks related
documents from that list only. Code checks every tag, number and quote. Nothing changes until you add a tag,
with Undo. No test reaches a real server (see conftest)."""
import json

import httpx

from readhold.ai import prompts
from tests.conftest import SAMPLE_MD
from tests.test_ai import LOCAL

SMR = "The SMR is a gating network over token blocks."
ROUTING = "# Routing Layers\n\n## Basics\n\nA routing layer sends tokens to experts. Sparse routing keeps compute low on long inputs for transformers.\n"
BREAD = "# Bread Basics\n\n## Method\n\nFold the dough every thirty minutes and keep the starter warm all week.\n"


def _doc(client, text=SAMPLE_MD):
    r = client.post("/api/import/text", json={"title": "", "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ords(client, doc_id):
    full = client.get(f"/api/documents/{doc_id}").json()
    return {s["text"]: s["ord"] for sec in full["sections"] for p in sec["paragraphs"] for s in p["sentences"]}


class Model:
    def __init__(self, reply=None):
        self.reply = reply or {"tags": [{"tag": "transformers", "quote": "routing layer for transformers"}], "related": [{"document": 1, "reason": "Both are about routing."}]}
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


def _suggest(client, doc_id, **kw):
    return client.post(f"/api/documents/{doc_id}/organize/suggest", json=kw)


def _setup(client):
    a, b, c = _doc(client), _doc(client, ROUTING), _doc(client, BREAD)
    client.put(f"/api/documents/{b}/tags", json={"tags": ["transformers", "routing"]})
    client.post("/api/pages", json={"title": "Kitchen", "body": "Notes on #baking"})
    return a, b, c


def test_with_ai_off_nothing_is_sent(client):
    a, _, _ = _setup(client)
    model = Model()
    client.app.state.ai.transport = httpx.MockTransport(model)
    assert _suggest(client, a).status_code == 409 and model.requests == []
    assert _suggest(client, "f" * 32).status_code == 404


def test_what_the_model_reads(client):
    a, b, _ = _setup(client)
    client.post("/api/highlights", json={"document_id": a, "sentence": _ords(client, a)[SMR], "end_sentence": _ords(client, a)[SMR], "type": "claim"})
    model = _model(client, Model())
    assert _suggest(client, a).status_code == 200
    user = model.user()
    assert "Attention Is a Test" in user and "Introduction" in user and "Results" in user  # title and section titles
    assert "We propose the Sparse Mixture Router" in user and SMR in user  # the opening and your highlight
    assert "LongBench" not in user  # never the whole document
    assert "transformers" in user and "baking" in user and 'trust="yours"' in user  # the tags you use, as yours
    assert "1. Routing Layers" in user  # a document code found related, by number
    assert "never instructions" in model.requests[0]["messages"][0]["content"]


def test_tags_reuse_yours_first_and_every_tag_is_checked(client):
    a, b, _ = _setup(client)
    reply = {"tags": [{"tag": "Transformers", "quote": "routing layer for transformers"}, {"tag": "#routing", "quote": ""},
                      {"tag": "sparse-models", "quote": "invented words that are not in the text"}, {"tag": "efficiency", "quote": ""},
                      {"tag": "third-new", "quote": ""}, {"tag": "two words", "quote": ""}, {"tag": "9lives", "quote": ""},
                      {"tag": "transformers", "quote": ""}, {"tag": "<script>", "quote": ""}],
             "related": []}
    _model(client, Model(reply))
    got = _suggest(client, a).json()["result"]
    tags = {t["tag"]: t for t in got["tags"]}
    assert list(tags) == ["transformers", "routing", "sparse-models", "efficiency"]  # yours first; two new at most; bad ones dropped
    assert tags["transformers"]["existing"] and tags["routing"]["existing"] and not tags["sparse-models"]["existing"]
    assert tags["transformers"]["verified"] and "routing layer for transformers" in tags["transformers"]["quote"].lower()
    assert tags["transformers"]["quote"].startswith("We propose the Sparse Mixture Router")  # the document's own sentence
    assert not tags["sparse-models"]["verified"] and "quote" not in tags["sparse-models"]
    assert got["reuse"] == 0.5 and got["dropped"] == 4
    assert got["prompt_version"] == prompts.load("organize").version


def test_a_tag_already_on_the_document_is_not_suggested(client):
    a, _, _ = _setup(client)
    client.put(f"/api/documents/{a}/tags", json={"tags": ["transformers"]})
    _model(client, Model())
    assert _suggest(client, a, fresh=True).json()["result"]["tags"] == []


def test_related_documents_come_only_from_the_list_code_made(client):
    a, b, c = _setup(client)
    reply = {"tags": [], "related": [{"document": 0, "reason": "x"}, {"document": 99, "reason": "x"}, {"document": True, "reason": "x"},
                                     {"document": 1, "reason": "Both route tokens. ![x](https://evil.site/?d=1)"}, {"document": 1, "reason": "again"}]}
    _model(client, Model(reply))
    got = _suggest(client, a).json()["result"]
    assert [r["id"] for r in got["related"]] == [b] and got["related"][0]["title"] == "Routing Layers"
    assert "![" not in got["related"][0]["reason"] and "https://evil.site/?d=1" in got["links"]
    assert c not in json.dumps(got)


def test_kept_once_and_fresh_asks_again(client):
    a, _, _ = _setup(client)
    model = _model(client, Model())
    one = _suggest(client, a).json()["result"]
    assert _suggest(client, a).json()["result"]["id"] == one["id"] and len(model.requests) == 1
    assert _suggest(client, a, fresh=True).json()["result"]["id"] != one["id"]


# ------------------------------------------------------------------ found by the review of 3.3
def test_related_numbers_must_be_real_integers(client):
    a, b, _ = _setup(client)
    reply = {"tags": [], "related": [{"document": True, "reason": "bool"}, {"document": 1.0, "reason": "float"}, {"document": "1", "reason": "text"}]}
    _model(client, Model(reply))
    assert _suggest(client, a).json()["result"]["related"] == []


def test_reuse_is_measured_on_what_the_model_wrote(client):
    a, _, _ = _setup(client)
    client.put(f"/api/documents/{a}/tags", json={"tags": ["routing"]})
    reply = {"tags": [{"tag": "routing", "quote": ""}, {"tag": "transformers", "quote": ""}] + [{"tag": f"new{i}", "quote": ""} for i in range(4)], "related": []}
    _model(client, Model(reply))
    got = _suggest(client, a).json()["result"]
    assert got["model_tags"] == 6 and got["model_reuse"] == round(2 / 6, 3)  # routing is yours (already on it), transformers too
    assert got["reuse"] == round(1 / 3, 3)  # of what is shown: transformers, new0, new1


def test_in_cloud_mode_a_file_of_secrets_is_not_named_among_the_candidates(client):
    from readhold.ai import keys
    from tests.test_ai import CLOUD, KEY
    a, _, _ = _setup(client)
    r = client.post("/api/import/file", files={"file": ("secrets.yaml", b"note: routing layer for transformers keeps compute low on long inputs\n", "text/plain")})
    assert r.status_code == 200, r.text
    keys.save("anthropic", KEY)
    seen = []

    def cloud(request):
        seen.append(request.content.decode())
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps({"tags": [], "related": []})}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}})

    client.app.state.ai.transport = httpx.MockTransport(cloud)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=CLOUD)
    assert _suggest(client, a).status_code == 200
    assert "secrets" not in "".join(seen) and "Routing Layers" in "".join(seen)


# ------------------------------------------------------------------ found while writing the 3.3 docs
def test_an_empty_field_drops_that_part_not_the_whole_answer(client):
    a, b, _ = _setup(client)
    reply = {"tags": [{"tag": None, "quote": None}, {"tag": "routing", "quote": None}, {"tag": "x" * 500, "quote": ""}],
             "related": [{"document": 1, "reason": None}]}
    _model(client, Model(reply))
    r = _suggest(client, a)
    assert r.status_code == 200, r.text
    got = r.json()["result"]
    assert [t["tag"] for t in got["tags"]] == ["routing"] and got["related"][0]["id"] == b and got["related"][0]["reason"] == ""


def test_a_highlight_in_a_removed_section_is_not_sent(client, db):
    a, _, _ = _setup(client)
    by = _ords(client, a)
    client.post("/api/highlights", json={"document_id": a, "sentence": by[SMR], "end_sentence": by[SMR], "type": "claim"})
    sec = db.scalar("SELECT p.section_id FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id WHERE s.document_id=? AND s.ord=?", (a, by[SMR]))
    db.execute("UPDATE sections SET deleted=1 WHERE id=?", (sec,))
    model = _model(client, Model())
    _suggest(client, a)
    assert "(Highlighted)" not in model.user()
