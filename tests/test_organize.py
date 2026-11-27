"""Organize the library without a model (AI plan, milestone 3.3, the non-AI layer): document tags you set yourself
(they are your collections on the Documents tab), related documents found by the words they share (retrieval
without embeddings), and tags suggested by code from related documents and the tags you already use."""

GEARS = "# Gear Trains\n\n## Basics\n\nA gear train passes torque from one gear to the next. The ratio of teeth sets the speed of each gear.\n\n## Wear\n\nGear teeth wear down when the torque is too high for the gear train.\n"
GEARS2 = "# Clock Gears\n\n## Escapement\n\nA clock uses a gear train to turn the hands. The ratio of teeth on each gear keeps the speed steady.\n"
BREAD = "# Bread Basics\n\n## Method\n\nFold the dough every thirty minutes and keep the starter warm all week.\n"


def _doc(client, text):
    r = client.post("/api/import/text", json={"title": "", "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _tags(client, doc_id, tags, **kw):
    return client.put(f"/api/documents/{doc_id}/tags", json={"tags": tags, **kw})


def test_tags_are_set_cleaned_and_shown_in_the_queue(client):
    a = _doc(client, GEARS)
    r = _tags(client, a, ["Mechanics", "#gears", "mechanics", "  clocks  "])
    assert r.status_code == 200 and r.json()["tags"] == ["mechanics", "gears", "clocks"]
    queue = {d["id"]: d for d in client.get("/api/documents").json()}
    assert queue[a]["tags"] == ["mechanics", "gears", "clocks"]
    for bad in (["two words"], ["9lives"], ["a" * 41], ["<b>"], ["x"] * 0 + [f"t{i}" for i in range(13)]):
        assert _tags(client, a, bad).status_code == 422, bad
    assert _tags(client, "f" * 32, ["x"]).status_code == 404


def test_a_change_can_say_what_it_expects_so_undo_never_overwrites(client):
    a = _doc(client, GEARS)
    _tags(client, a, ["gears"])
    assert _tags(client, a, ["gears", "mechanics"], expect=["gears"]).status_code == 200
    r = _tags(client, a, ["gears"], expect=["gears"])  # the tags changed since: not overwritten
    assert r.status_code == 409 and client.get(f"/api/organize/{a}").json()["tags"] == ["gears", "mechanics"]


def test_related_documents_share_words_and_say_which(client):
    a, b, c = _doc(client, GEARS), _doc(client, GEARS2), _doc(client, BREAD)
    got = client.get(f"/api/organize/{a}").json()
    ids = [r["id"] for r in got["related"]]
    assert ids == [b] and c not in ids
    assert {"gear", "train"} <= set(got["related"][0]["shared"]) and got["related"][0]["title"] == "Clock Gears"
    client.delete(f"/api/documents/{b}")
    assert client.get(f"/api/organize/{a}").json()["related"] == []


def test_tags_are_suggested_from_related_documents_and_from_tags_you_use(client):
    a, b, _ = _doc(client, GEARS), _doc(client, GEARS2), _doc(client, BREAD)
    _tags(client, b, ["mechanics", "clocks"])
    client.post("/api/pages", json={"title": "Torque", "body": "Notes on #torque and #baking"})
    got = client.get(f"/api/organize/{a}").json()
    sug = {s["tag"]: s for s in got["suggested"]}
    assert "mechanics" in sug and "Clock Gears" in sug["mechanics"]["reason"]
    assert "torque" in sug and "baking" not in sug  # a tag you use whose word is in this document; not one that is not
    assert all(s["existing"] for s in got["suggested"])
    assert {"mechanics", "clocks", "torque", "baking"} <= set(got["known"])
    _tags(client, a, ["mechanics"])
    assert "mechanics" not in {s["tag"] for s in client.get(f"/api/organize/{a}").json()["suggested"]}


# ------------------------------------------------------------------ found by the review of 3.3
def test_an_older_document_still_gets_related_documents(client, db, monkeypatch):
    from readhold import organize
    a, b = _doc(client, GEARS), _doc(client, GEARS2)
    for i in range(3):
        _doc(client, BREAD.replace("Bread", f"Bread {i}"))
    db.execute("UPDATE documents SET updated_at='2000-01-01' WHERE id=?", (a,))
    monkeypatch.setattr(organize, "MAX_DOCS", 3)
    db.execute("UPDATE documents SET updated_at='2999-01-01' WHERE id=?", (b,))
    assert [r["id"] for r in client.get(f"/api/organize/{a}").json()["related"]] == [b]


def test_tags_are_normalized_and_expect_must_be_valid(client):
    a = _doc(client, GEARS)
    cafe = "café"  # "café" written with a combining accent
    r = _tags(client, a, [cafe])
    assert r.status_code == 200 and r.json()["tags"] == ["café"]
    assert _tags(client, a, ["²abc"]).status_code == 422  # a tag starts with a letter, not a superscript two
    assert _tags(client, a, [], expect=["!!!"]).status_code == 422
