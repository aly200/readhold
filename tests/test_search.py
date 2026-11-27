"""Ctrl+K: one search over notes, tasks, documents, quests, glossary terms and ideas."""


def _kinds(client, q):
    return [(r["kind"], r["title"]) for r in client.get("/api/search", params={"q": q}).json()["results"]]


def test_search_finds_things_of_every_kind(client, sample_md):
    client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"})
    client.post("/api/pages", json={"title": "Attention notes", "body": "Self-attention weighs every word."})
    client.post("/api/pages", json={"title": "Loose thoughts", "body": "Maybe attention is like a spotlight."})
    client.post("/api/todos", json={"text": "Reread the attention section"})
    done = client.post("/api/todos", json={"text": "Old attention task"}).json()
    client.patch(f"/api/todos/{done['id']}", json={"done": True})
    client.post("/api/quests", json={"title": "Understand attention", "why": "", "done_looks_like": "", "questions": ["How?"]})
    got = _kinds(client, "ATTENTION")
    assert ("note", "Attention notes") in got and ("note", "Loose thoughts") in got
    assert got.index(("note", "Attention notes")) < got.index(("note", "Loose thoughts"))  # a title match comes first
    assert ("task", "Reread the attention section") in got and ("task", "Old attention task") not in got
    assert ("document", "Attention Is a Test") in got and ("quest", "Understand attention") in got
    hint = next(r["hint"] for r in client.get("/api/search", params={"q": "spotlight"}).json()["results"])
    assert "spotlight" in hint


def test_search_treats_wildcards_as_plain_text_and_empty_as_nothing(client):
    client.post("/api/pages", json={"title": "Plain", "body": "nothing special"})
    assert _kinds(client, "") == [] and _kinds(client, "   ") == []
    assert _kinds(client, "%") == [] and _kinds(client, "_") == []
    client.post("/api/pages", json={"title": "100% sure", "body": ""})
    assert _kinds(client, "100%") == [("note", "100% sure")]


def test_search_looks_inside_documents(client, sample_md):
    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    got = client.get("/api/search", params={"q": "reduces compute"}).json()["results"]
    passages = [r for r in got if r["kind"] == "passage"]
    assert passages and passages[0]["document_id"] == doc["id"] and passages[0]["hint"] == "Attention Is a Test"
    assert "reduces compute" in passages[0]["title"] and isinstance(passages[0]["sentence"], int)
    assert len([r for r in client.get("/api/search", params={"q": "the"}).json()["results"] if r["kind"] == "passage"]) <= 2  # two per document
    assert [r for r in client.get("/api/search", params={"q": "re"}).json()["results"] if r["kind"] == "passage"] == []  # too short to look for
