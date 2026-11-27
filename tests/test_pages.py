"""Notes: pages linked with [[double brackets]], backlinks, mentions, renames and the daily note."""
import datetime as dt


def _page(client, title, body=""):
    r = client.post("/api/pages", json={"title": title, "body": body})
    assert r.status_code == 200, r.text
    return r.json()


def test_links_backlinks_and_a_link_to_a_page_that_does_not_exist_yet(client):
    eig = _page(client, "Eigenvectors", "A vector that keeps its direction. See [[Linear maps]] and [[SVD|the SVD]].")
    assert [o["key"] for o in eig["outgoing"]] == ["linear maps", "svd"]
    assert all(o["kind"] == "missing" for o in eig["outgoing"]) and eig["backlinks"] == []
    # following a link makes the page, and it already knows what links to it
    svd = client.post("/api/pages/open", json={"title": "svd"}).json()
    assert svd["title"] == "svd" and [b["title"] for b in svd["backlinks"]] == ["Eigenvectors"]
    assert "[[SVD|the SVD]]" in svd["backlinks"][0]["context"]
    # opening it again does not make a second one
    assert client.post("/api/pages/open", json={"title": "  SVD "}).json()["id"] == svd["id"]
    eig = client.get(f"/api/pages/{eig['id']}").json()
    assert [(o["key"], o["kind"]) for o in eig["outgoing"]] == [("linear maps", "missing"), ("svd", "page")]
    assert {n["title"] for n in eig["graph"]["nodes"]} == {"Eigenvectors", "svd"} and eig["graph"]["edges"] == [[eig["id"], svd["id"]]]
    # a second note with the same title is refused, whatever the capitals
    assert client.post("/api/pages", json={"title": "eigenvectors"}).status_code == 409


def test_editing_a_body_keeps_links_and_tags_in_step(client, db):
    a = _page(client, "Reading list", "#books and #Study\n- [[Deep Work]]\n```\n[[not a link]] #nottag\n```")
    assert a["tags"] == "books study" and [o["key"] for o in a["outgoing"]] == ["deep work"]
    out = client.patch(f"/api/pages/{a['id']}", json={"body": "Now about [[Focus]] only. #study"}).json()
    assert out["tags"] == "study" and [o["key"] for o in out["outgoing"]] == ["focus"]
    live = db.all("SELECT target FROM page_links WHERE from_id=? AND deleted=0", (a["id"],))
    assert [r["target"] for r in live] == ["focus"]
    # saving the same body again writes no new link rows
    client.patch(f"/api/pages/{a['id']}", json={"body": "Now about [[Focus]] only. #study"})
    assert db.scalar("SELECT COUNT(*) FROM page_links WHERE from_id=?", (a["id"],)) == 2
    listing = client.get("/api/pages").json()
    assert listing["total"] == 1 and listing["links"] == 1 and listing["tags"] == [{"tag": "study", "n": 1}]
    assert listing["pages"][0]["snippet"] == "Now about Focus only. #study"


def test_renaming_a_page_rewrites_the_links_to_it(client):
    target = _page(client, "Linear maps", "Functions that keep sums and scaling.")
    a = _page(client, "Eigenvectors", "See [[linear maps]] and again [[Linear  Maps|maps]].")
    out = client.patch(f"/api/pages/{target['id']}", json={"title": "Linear transformations"}).json()
    assert out["title"] == "Linear transformations" and [b["id"] for b in out["backlinks"]] == [a["id"]]
    body = client.get(f"/api/pages/{a['id']}").json()["body"]
    assert body == "See [[Linear transformations]] and again [[Linear transformations|maps]]."
    # a rename onto an existing title is refused
    assert client.patch(f"/api/pages/{a['id']}", json={"title": "linear transformations"}).status_code == 409
    # changing only the capitals is fine
    assert client.patch(f"/api/pages/{a['id']}", json={"title": "EIGENVECTORS"}).json()["title"] == "EIGENVECTORS"


def test_unlinked_mentions_can_become_links(client):
    rank = _page(client, "Rank", "The number of independent columns.")
    other = _page(client, "Problem set 4", "Question 2 asks for the rank of a matrix. Cranky, but fine. See [[Rank|this]]? No, later.")
    plain = _page(client, "Lecture 3", "We computed the rank twice, then the Rank again.")
    got = client.get(f"/api/pages/{rank['id']}").json()
    assert [b["id"] for b in got["backlinks"]] == [other["id"]]
    assert [m["id"] for m in got["mentions"]] == [plain["id"]]  # linked notes are not listed as mentions
    out = client.post(f"/api/pages/{rank['id']}/link-mention", json={"from_id": plain["id"]}).json()
    assert {b["id"] for b in out["backlinks"]} == {other["id"], plain["id"]} and out["mentions"] == []
    assert client.get(f"/api/pages/{plain['id']}").json()["body"] == "We computed the [[Rank]] twice, then the Rank again."
    assert client.post(f"/api/pages/{rank['id']}/link-mention", json={"from_id": rank["id"]}).status_code == 409


def test_a_link_can_open_a_document_or_a_quest(client, sample_md):
    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    quest = client.post("/api/quests", json={"title": "Pass the exam", "why": "", "done_looks_like": "", "questions": ["How?"]}).json()
    p = _page(client, "Week plan", "Read [[attention is a test]] for [[Pass the exam]]. Then [[Nowhere]].")
    kinds = {o["key"]: (o["kind"], o["id"]) for o in p["outgoing"]}
    assert kinds == {"attention is a test": ("document", doc["id"]), "pass the exam": ("quest", quest["id"]), "nowhere": ("missing", None)}
    titles = client.get("/api/pages/titles").json()
    assert [x["title"] for x in titles["pages"]] == ["Week plan"]
    assert {(o["kind"], o["title"]) for o in titles["others"] if o["kind"] != "term"} == {("document", "Attention Is a Test"), ("quest", "Pass the exam")}


def test_one_daily_note_per_day(client):
    day = dt.date.today().isoformat()
    first = client.get(f"/api/pages/daily/{day}").json()
    assert first["title"] == day and first["daily"] == day and "## Today" in first["body"]
    client.patch(f"/api/pages/{first['id']}", json={"body": "Wrote the proof. #win"})
    again = client.get(f"/api/pages/daily/{day}").json()
    assert again["id"] == first["id"] and again["body"] == "Wrote the proof. #win"
    assert client.get("/api/pages/daily/2026-02-31").status_code == 404
    assert client.get("/api/pages/daily/today").status_code == 404


def test_search_tags_pin_delete_restore_and_export(client):
    a = _page(client, "Alpha", "about matrices #math")
    b = _page(client, "Beta", "about gardens #home")
    assert [p["title"] for p in client.get("/api/pages", params={"q": "matri"}).json()["pages"]] == ["Alpha"]
    assert [p["title"] for p in client.get("/api/pages", params={"tag": "#home"}).json()["pages"]] == ["Beta"]
    assert [p["title"] for p in client.get("/api/pages", params={"q": "100%"}).json()["pages"]] == []
    client.patch(f"/api/pages/{a['id']}", json={"pinned": True})
    client.patch(f"/api/pages/{b['id']}", json={"body": "newer"})
    assert [p["title"] for p in client.get("/api/pages").json()["pages"]] == ["Alpha", "Beta"]  # pinned stays on top
    assert client.delete(f"/api/pages/{a['id']}").status_code == 200
    assert client.get(f"/api/pages/{a['id']}").status_code == 404
    assert client.post(f"/api/pages/{a['id']}/restore").json()["title"] == "Alpha"
    assert client.post("/api/pages", json={"title": "   "}).status_code == 422
    assert client.get("/api/pages/not-an-id").status_code == 404
    from readhold.services import EXPORT_TABLES

    assert {"pages", "page_links"} <= set(EXPORT_TABLES)


# ---- notes, part two: properties, the big map, quotes from a document
def test_properties_are_read_from_key_value_lines(client):
    from readhold.pages import props_in

    body = "status:: reading\nCourse:: Linear algebra\n\nNot a prop: just text\n```\nhidden:: yes\n```\nstatus:: again"
    assert props_in(body) == {"status": "reading", "course": "Linear algebra"}
    _page(client, "Eigenvalues", body + "\n#math")
    row = next(p for p in client.get("/api/pages").json()["pages"] if p["title"] == "Eigenvalues")
    assert row["props"] == {"status": "reading", "course": "Linear algebra"} and row["created_at"]


def test_the_big_map_has_every_note_and_the_links_between_notes(client):
    a = _page(client, "Alpha", "See [[Beta]] and [[Nowhere yet]].")
    b = _page(client, "Beta", "Back to [[alpha]]. And to itself: [[Beta]].")
    c = _page(client, "Gamma", "Alone.")
    g = client.get("/api/pages/graph").json()
    assert {n["id"] for n in g["nodes"]} == {a["id"], b["id"], c["id"]} and g["total"] == 3
    assert sorted(g["edges"]) == sorted([[a["id"], b["id"]], [b["id"], a["id"]]])


def test_a_quote_from_a_document_lands_in_the_days_note_with_a_link_back(client, sample_md):
    doc = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()
    r = client.post("/api/pages/quote", json={"text": "  Attention is\nall you need. ", "document_id": doc["id"], "sentence": 7, "day": "2026-11-22"})
    assert r.status_code == 200, r.text
    note = client.get(f"/api/pages/{r.json()['id']}").json()
    assert note["daily"] == "2026-11-22"
    assert note["body"].endswith("> Attention is all you need.\n> — [[Attention Is a Test#s7|Attention Is a Test]]\n")
    assert [(o["kind"], o["id"]) for o in note["outgoing"]] == [("document", doc["id"])]  # the sentence mark is not part of the title
    again = client.post("/api/pages/quote", json={"text": "Second", "document_id": doc["id"], "sentence": 9, "day": "2026-11-22"}).json()
    assert again["id"] == note["id"]
    assert client.post("/api/pages/quote", json={"text": "x", "document_id": "0" * 32, "sentence": 1, "day": "2026-11-22"}).status_code == 404
    assert client.post("/api/pages/quote", json={"text": "x", "document_id": doc["id"], "sentence": 1, "day": "2026-13-45"}).status_code == 422


def test_a_missing_link_keeps_its_casing(client):
    p = client.post("/api/pages", json={"title": "Reading list", "body": "Next: [[Singular Value Decomposition]] and [[singular value decomposition|SVD]]."}).json()
    out = client.get(f"/api/pages/{p['id']}").json()["outgoing"]
    assert [(o["kind"], o["title"], o["key"]) for o in out] == [("missing", "Singular Value Decomposition", "singular value decomposition")]

