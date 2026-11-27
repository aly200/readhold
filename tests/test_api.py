import sqlite3

from fastapi.testclient import TestClient

from tests.conftest import TOKEN


def _import(client, sample_md):
    r = client.post("/api/import/text", json={"title": "", "text": sample_md, "why": "exam"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_security_requires_token_and_host(db):
    from readhold.server import create_app

    app = create_app(db, TOKEN, {"testserver"})
    c = TestClient(app)
    assert c.get("/api/home").status_code == 401
    assert c.get("/api/home", headers={"x-readhold-token": "wrong"}).status_code == 401
    assert c.get("/api/home", headers={"x-readhold-token": TOKEN}).status_code == 200
    assert c.get("/api/home", headers={"x-readhold-token": TOKEN, "host": "evil.com"}).status_code == 403
    assert c.get("/auth?token=nope").status_code == 401
    r = c.get("/api/home", headers={"x-readhold-token": TOKEN})
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_import_read_and_structure(client, sample_md):
    doc_id = _import(client, sample_md)
    d = client.get(f"/api/documents/{doc_id}").json()
    assert d["title"] == "Attention Is a Test"
    assert d["status"] == "reading"
    kinds = {s["title"]: (s["kind"], s["background"], s["hidden"]) for s in d["sections"]}
    assert kinds["Related Work"] == ("related", 1, 0)
    assert kinds["References"] == ("references", 0, 1)
    sents = [s for sec in d["sections"] for p in sec["paragraphs"] for s in p["sentences"]]
    assert [s["ord"] for s in sents] == list(range(len(sents)))
    assert all(0 <= s["density"] <= 1 for s in sents)

    client.post(f"/api/documents/{doc_id}/position", json={"position": 5})
    client.post(f"/api/documents/{doc_id}/read", json={"ords": [0, 1, 2]})
    home = client.get("/api/home").json()
    assert home["resume"]["document_id"] == doc_id and home["resume"]["position"] == 5
    assert home["resume"]["progress"]["read"] == 3

    # fix the structure: split, rename, merge
    method = next(s for s in d["sections"] if s["title"] == "Method")
    par = method["paragraphs"][1]
    new = client.post(f"/api/paragraphs/{par['id']}/split", json={"title": "Code"}).json()
    client.patch(f"/api/sections/{new['id']}", json={"title": "Code listing"})
    d2 = client.get(f"/api/documents/{doc_id}").json()
    assert [s["title"] for s in d2["sections"]][3:5] == ["Method", "Code listing"]
    client.post(f"/api/sections/{new['id']}/merge-up")
    d3 = client.get(f"/api/documents/{doc_id}").json()
    assert [s["title"] for s in d3["sections"]] == [s["title"] for s in d["sections"]]


def test_questions_highlights_cards_and_summary(client, sample_md):
    doc_id = _import(client, sample_md)
    tmpl = client.get("/api/templates", params={"kind": "method"}).json()
    assert "How does it work, step by step?" in tmpl

    q = client.post("/api/questions", json={"document_id": doc_id, "text": "How does SMR route tokens?", "section_kind": "method", "source_sentence": 0}).json()
    assert client.get("/api/templates", params={"kind": "method"}).json()[0] == "How does SMR route tokens?"
    client.patch(f"/api/questions/{q['id']}", json={"answer": "A gate scores blocks and keeps top-k."})

    claim = client.post("/api/highlights", json={"document_id": doc_id, "sentence": 0, "type": "claim"}).json()
    ev = client.post("/api/highlights", json={"document_id": doc_id, "sentence": 1, "type": "evidence"}).json()
    client.patch(f"/api/highlights/{ev['id']}", json={"cloze": "41%"})
    client.post("/api/highlights", json={"document_id": doc_id, "sentence": 5, "type": "definition", "note": "router"})
    client.post("/api/highlights", json={"document_id": doc_id, "sentence": 4, "type": "confusing"})
    client.post("/api/highlights", json={"document_id": doc_id, "sentence": 3, "type": "idea", "note": "try on my RAG"})
    client.post("/api/terms", json={"term": "SMR", "guess": "some router", "definition": "Sparse Mixture Router", "document_id": doc_id, "sentence": 0})

    cards = client.get("/api/cards", params={"document_id": doc_id}).json()
    assert {c["source_type"] for c in cards} == {"question", "cloze", "definition", "term"}
    cloze = next(c for c in cards if c["source_type"] == "cloze")
    assert "_____" in cloze["front"] and "41%" not in cloze["front"]

    due = client.get("/api/review/due").json()
    assert due["due_total"] == 4
    r = client.post(f"/api/review/{due['cards'][0]['id']}", json={"rating": 3}).json()
    assert r["due"] > due["cards"][0]["due"]
    assert client.get("/api/review/due").json()["due_total"] == 3

    s = client.get(f"/api/documents/{doc_id}/summary").json()
    assert s["claims"][0]["id"] == claim["id"]
    assert s["claims"][0]["evidence"][0]["id"] == ev["id"]
    assert s["acronyms"]["SMR"] == "Sparse Mixture Router"
    assert len(s["confusions"]) == 1
    assert client.get("/api/ideas").json()[0]["text"] == "try on my RAG"

    exp = client.post(f"/api/documents/{doc_id}/export").json()
    assert "## Main points" in exp["markdown"] and "**Claim:**" in exp["markdown"]

    home = client.get("/api/home").json()
    assert home["confusions"][0]["sentence"] == 4

    client.delete(f"/api/highlights/{ev['id']}")
    assert "cloze" not in {c["source_type"] for c in client.get("/api/cards", params={"document_id": doc_id}).json()}


def test_define_endpoint(client, sample_md):
    doc_id = _import(client, sample_md)
    r = client.get(f"/api/documents/{doc_id}/define", params={"term": "router"}).json()
    assert r["in_document"][0]["text"].startswith("We define a router")
    r = client.get(f"/api/documents/{doc_id}/define", params={"term": "SMR"}).json()
    assert r["acronym"] == "Sparse Mixture Router"


def test_sessions_stats_settings(client, sample_md):
    doc_id = _import(client, sample_md)
    s = client.post("/api/sessions", json={"document_id": doc_id, "energy": "low", "time_box_min": 10}).json()
    client.patch(f"/api/sessions/{s['id']}", json={"focused_ms": 11 * 60_000, "longest_run_ms": 300_000, "sentences_read": 20, "next_step": "Read the Results", "ended": True})
    st = client.get("/api/stats").json()
    assert st["days"][-1]["focused_ms"] == 11 * 60_000
    assert st["streak"] == 1
    assert client.get("/api/home").json()["resume"]["next_step"] == "Read the Results"
    out = client.put("/api/settings", json={"wpm": 300, "not_a_setting": 1}).json()
    assert out["wpm"] == 300 and "not_a_setting" not in out


def test_export_all_and_backup(client, sample_md, home):
    _import(client, sample_md)
    path = client.post("/api/export/all").json()["path"]
    assert path.endswith(".json")
    b = client.post("/api/backup").json()["path"]
    con = sqlite3.connect(b)
    assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_migration_backup_on_upgrade(home, monkeypatch, tmp_path):
    """An extra backup is made before migrating an existing database."""
    from readhold import db as dbmod

    d = dbmod.open_db()
    d.conn.execute("PRAGMA user_version=0")  # pretend it's an old database with data
    d.conn.execute("PRAGMA user_version=0")
    extra = tmp_path / "migs"
    extra.mkdir()
    for f in dbmod.MIGRATIONS_DIR.glob("*.sql"):
        (extra / f.name).write_text("SELECT 1;", "utf-8")
    (extra / "0002_add.sql").write_text("CREATE TABLE extra_thing (id TEXT);", "utf-8")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", extra)
    d.conn.execute("PRAGMA user_version=1")
    d.conn.close()
    latest = max(int(f.name[:4]) for f in extra.glob("*.sql"))
    d2 = dbmod.open_db()
    assert d2.version() == latest
    assert list((home / "data" / "backups").glob(f"readhold-pre-migration-v1-to-v{latest}.db"))


def test_fixes_from_the_code_guidebook(client, sample_md, home):
    from readhold import config, services

    # refusals carry the safety headers too
    from fastapi.testclient import TestClient
    bare = TestClient(client.app)
    r = bare.get("/api/settings")
    assert r.status_code == 401 and "default-src 'self'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/settings").headers["cache-control"] == "no-store"

    doc_id = client.post("/api/import/text", json={"title": "Attention Is a Test", "text": sample_md, "format": "markdown"}).json()["id"]
    kinds = lambda: sorted(c["source_type"] for c in client.get("/api/cards", params={"document_id": doc_id}).json())

    # an answer that is cleared takes its card with it
    q = client.post("/api/questions", json={"document_id": doc_id, "text": "How does SMR route tokens?", "section_kind": "method"}).json()
    client.patch(f"/api/questions/{q['id']}", json={"answer": "A gate keeps the top-k blocks."})
    assert kinds() == ["question"]
    client.patch(f"/api/questions/{q['id']}", json={"answer": ""})
    assert kinds() == []

    # a highlight whose type changes loses the card of its old type
    hl = client.post("/api/highlights", json={"document_id": doc_id, "sentence": 5, "type": "definition", "note": "router"}).json()
    assert kinds() == ["definition"]
    client.patch(f"/api/highlights/{hl['id']}", json={"type": "claim"})
    assert kinds() == []
    ev = client.post("/api/highlights", json={"document_id": doc_id, "sentence": 1, "type": "evidence"}).json()
    client.patch(f"/api/highlights/{ev['id']}", json={"cloze": "41%"})
    assert kinds() == ["cloze"]
    client.patch(f"/api/highlights/{ev['id']}", json={"type": "idea"})
    assert kinds() == []

    # a file type Readhold cannot read is refused, and no copy of it is kept
    before = sorted(f.name for f in config.library_dir().iterdir())
    r = client.post("/api/import/file", files={"file": ("slides.xyz", b"not a document", "application/octet-stream")})
    assert r.status_code >= 400 and "Unsupported" in r.text
    assert sorted(f.name for f in config.library_dir().iterdir()) == before

    # the full export knows every table that holds your work
    assert {"todo_items", "suggestions", "daily_picks"} <= set(services.EXPORT_TABLES)

