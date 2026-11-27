"""A full-text index over the sections of your documents, and where each reading session went (AI plan, phase 0.2 and 0.3)."""
from tests.conftest import SAMPLE_MD


def _doc(client, text=SAMPLE_MD, title=""):
    r = client.post("/api/import/text", json={"title": title, "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()


def _find(client, q, **kw):
    r = client.get("/api/passages", params={"q": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def test_a_keyword_finds_its_section_and_the_sentence(client):
    doc = _doc(client)
    got = _find(client, "gating network")
    assert got and got[0]["document_id"] == doc["id"] and got[0]["section_title"] == "Method"
    assert got[0]["document_title"] == "Attention Is a Test"
    # the anchor is the sentence that holds the words: the reader opens there
    full = client.get(f"/api/documents/{doc['id']}").json()
    sentence = next(s for sec in full["sections"] for p in sec["paragraphs"] for s in p["sentences"] if s["ord"] == got[0]["sentence"])
    assert "gating network" in sentence["text"]
    assert "gating" in got[0]["snippet"]


def test_words_need_not_be_together_and_the_best_section_comes_first(client):
    _doc(client)
    got = _find(client, "blocks score kept")  # three words from one sentence, not next to each other
    assert got[0]["section_title"] == "Method"
    assert _find(client, "transform")[0]["section_title"] in ("Abstract", "Introduction")  # the start of a word is enough
    assert _find(client, "zebra quantum") == []
    assert _find(client, "") == [] and _find(client, '"') == [] and _find(client, "* ( ) : ^ -") == []
    for odd in ('AND OR NOT *', 'NEAR(a b)', 'title: "x', "a' OR 1=1 --", "col:^x*"):  # query syntax is read as plain words, never as syntax
        _find(client, odd)


def test_one_document_can_be_searched(client):
    a = _doc(client)
    b = _doc(client, "# Bread\n\n## Method\n\nFold the dough every thirty minutes. The starter needs flour and water to stay alive for the whole week.\n")
    both = _find(client, "method")
    assert {r["document_id"] for r in both} == {a["id"], b["id"]}
    only = _find(client, "method", document_id=b["id"])
    assert [r["document_id"] for r in only] == [b["id"]]
    assert client.get("/api/passages", params={"q": "method", "document_id": "nope"}).status_code == 404


def test_the_index_follows_structure_edits_and_removal(client):
    doc = _doc(client)
    full = client.get(f"/api/documents/{doc['id']}").json()
    method = next(s for s in full["sections"] if s["title"] == "Method")
    assert client.patch(f"/api/sections/{method['id']}", json={"title": "Routing recipe"}).status_code == 200
    assert _find(client, "recipe")[0]["section_title"] == "Routing recipe"
    # merged into the section above: its text is found there now
    assert client.post(f"/api/sections/{method['id']}/merge-up").status_code == 200
    assert _find(client, "gating network")[0]["section_title"] == "Related Work"
    assert _find(client, "recipe") == []
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert _find(client, "gating network") == []


def test_documents_from_before_the_index_are_added_at_start(client, db):
    from readhold import passages

    doc = _doc(client)
    db.execute("DELETE FROM section_fts")
    assert _find(client, "gating network") == []
    assert passages.ensure_index(db) == 1
    assert _find(client, "gating network")[0]["document_id"] == doc["id"]
    assert passages.ensure_index(db) == 0


def test_find_anything_uses_the_index_too(client):
    _doc(client)
    got = [r for r in client.get("/api/search", params={"q": "blocks score kept"}).json()["results"] if r["kind"] == "passage"]
    assert got and got[0]["hint"].startswith("Attention Is a Test") and isinstance(got[0]["sentence"], int)


def test_a_session_remembers_where_it_started_and_stopped(client):
    doc = _doc(client)
    assert client.get(f"/api/documents/{doc['id']}/last-session").json() == {"session": None}
    client.post(f"/api/documents/{doc['id']}/position", json={"position": 3})
    s = client.post("/api/sessions", json={"document_id": doc["id"], "question": "What is SMR?"}).json()
    assert s["start_ord"] == 3
    client.post(f"/api/documents/{doc['id']}/read", json={"ords": [3, 4, 5, 6]})
    client.post(f"/api/documents/{doc['id']}/position", json={"position": 6})
    full = client.get(f"/api/documents/{doc['id']}").json()
    hl = client.post("/api/highlights", json={"document_id": doc["id"], "sentence": 4, "end_sentence": 4, "type": "claim"})
    assert hl.status_code == 200, hl.text
    assert client.patch(f"/api/sessions/{s['id']}", json={"focused_ms": 90_000, "sentences_read": 4, "next_step": "Read Method", "ended": True}).status_code == 200
    last = client.get(f"/api/documents/{doc['id']}/last-session").json()["session"]
    assert (last["start_ord"], last["last_ord"]) == (3, 6) and last["next_step"] == "Read Method" and last["question"] == "What is SMR?"
    by_ord = {s2["ord"]: sec["title"] for sec in full["sections"] for p in sec["paragraphs"] for s2 in p["sentences"]}
    assert [x["title"] for x in last["sections"]] == list(dict.fromkeys(by_ord[o] for o in (3, 4, 5, 6)))
    assert [h["sentence"] for h in last["highlights"]] == [4]
    # a session that is still open is not "the last session"
    client.post("/api/sessions", json={"document_id": doc["id"]})
    assert client.get(f"/api/documents/{doc['id']}/last-session").json()["session"]["id"] == s["id"]
    assert client.get("/api/documents/nope/last-session").status_code == 404


def test_a_restored_document_is_found_again_and_a_split_is_followed(client):
    doc = _doc(client)
    client.delete(f"/api/documents/{doc['id']}")
    assert client.post(f"/api/documents/{doc['id']}/restore").status_code == 200
    assert _find(client, "gating network")[0]["section_title"] == "Method"
    full = client.get(f"/api/documents/{doc['id']}").json()
    method = next(s for s in full["sections"] if s["title"] == "Method")
    assert client.post(f"/api/paragraphs/{method['paragraphs'][-1]['id']}/split", json={"title": "Code sample"}).status_code == 200
    assert _find(client, "route")[0]["section_title"] == "Code sample"


def test_a_timer_run_on_a_document_is_not_its_last_reading_session(client):
    doc = _doc(client)
    run = client.post("/api/timer/start", json={"kind": "focus", "minutes": 5, "link_type": "document", "link_id": doc["id"]}).json()
    assert client.post(f"/api/timer/{run['id']}/finish", json={"elapsed_ms": 60_000}).status_code == 200
    assert client.get(f"/api/documents/{doc['id']}/last-session").json() == {"session": None}
