"""Lectures (PDF, PowerPoint, HTML), the notebook, digital ink, the journal and letters — and their safety rules."""
import datetime as dt
import io
import zipfile

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

PNG = b"\x89PNG\r\n\x1a\n"


def _pdf_bytes(pages=2) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(842, 595))  # a landscape slide
    for i in range(pages):
        c.setFont("Helvetica-Bold", 28)
        c.drawString(60, 520, f"Lecture slide {i + 1}")
        c.setFont("Helvetica", 16)
        c.drawString(60, 470, "Gradient descent takes small steps downhill.")
        c.showPage()
    c.save()
    return buf.getvalue()


def _pptx_bytes() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])  # title + content
    s.shapes.title.text = "Backpropagation"
    body = s.placeholders[1].text_frame
    body.text = "Chain rule, applied backwards"
    p = body.add_paragraph()
    p.text = "Gradients flow from the loss"
    p.level = 1
    run = p.runs[0]
    run.font.size = Pt(20)
    run.font.bold = True
    img = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(img, "PNG")
    img.seek(0)
    s.shapes.add_picture(img, Inches(6), Inches(1), Inches(2), Inches(1.5))
    rows = s.shapes.add_table(2, 2, Inches(1), Inches(5), Inches(4), Inches(1)).table
    rows.cell(0, 0).text = "Layer"
    rows.cell(0, 1).text = "Grad"
    s.notes_slide.notes_text_frame.text = "Mention vanishing gradients."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Summary"
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


HTML = b"""<!doctype html><html><head><title>Interactive gradient demo</title>
<script>document.title = 'changed by script';</script></head>
<body><h1>Gradient demo</h1><p>Drag the slider.</p><script>fetch('https://example.com')</script></body></html>"""


def _import(client, name, data):
    return client.post("/api/lectures/import", files={"file": (name, data)})


# ------------------------------------------------------------------ import and viewing
def test_pdf_lecture_pages_and_rendering(client):
    r = _import(client, "week3.pdf", _pdf_bytes())
    assert r.status_code == 200, r.text
    lec = r.json()
    assert lec["kind"] == "pdf" and lec["pages"] == 2
    full = client.get(f"/api/lectures/{lec['id']}").json()
    assert [p["title"] for p in full["page_list"]] == ["Lecture slide 1", "Lecture slide 2"]
    assert full["page_list"][0]["width"] == pytest.approx(842, abs=1)
    img = client.get(f"/api/lectures/{lec['id']}/pages/1/image?w=500")
    assert img.status_code == 200 and img.content.startswith(PNG)
    assert client.get(f"/api/lectures/{lec['id']}/pages/2/image").status_code == 404  # out of range
    again = client.get(f"/api/lectures/{lec['id']}/pages/1/image?w=500")  # cached file
    assert again.content == img.content


def test_pptx_lecture_layout_images_tables_notes(client):
    r = _import(client, "backprop.pptx", _pptx_bytes())
    assert r.status_code == 200, r.text
    lec = client.get(f"/api/lectures/{r.json()['id']}").json()
    first = lec["page_list"][0]
    assert first["title"] == "Backpropagation" and first["speaker_notes"] == "Mention vanishing gradients."
    kinds = [e["type"] for e in first["layout"]["els"]]
    assert {"text", "image", "table"} <= set(kinds)
    text = next(e for e in first["layout"]["els"] if e["type"] == "text" and not e["title"])
    assert text["paras"][1]["level"] == 1 and text["paras"][1]["runs"][0]["b"] is True and text["paras"][1]["runs"][0]["size"] == 20
    table = next(e for e in first["layout"]["els"] if e["type"] == "table")
    assert table["rows"][0] == ["Layer", "Grad"]
    image = next(e for e in first["layout"]["els"] if e["type"] == "image")
    asset = client.get(f"/api/lectures/{lec['id']}/assets/{image['src']}")
    assert asset.status_code == 200 and asset.headers["content-type"] == "image/png"
    assert client.get(f"/api/lectures/{lec['id']}/assets/..%2F..%2Freadhold.db").status_code == 404
    assert 0 <= text["x"] <= 100 and 0 < text["w"] <= 100


def test_html_lecture_runs_sandboxed_without_network(client):
    lec = _import(client, "demo.html", HTML).json()
    assert lec["title"] == "Interactive gradient demo" and lec["kind"] == "html"
    r = client.get(f"/api/lectures/{lec['id']}/content.html")
    assert r.status_code == 200 and b"Gradient demo" in r.content
    csp = r.headers["content-security-policy"]
    assert "connect-src 'none'" in csp and "default-src 'none'" in csp and "frame-ancestors 'self'" in csp
    assert csp.startswith("sandbox allow-scripts;") and "allow-same-origin" not in csp  # opaque origin, even top-level
    assert "https:" not in csp and "http:" not in csp  # nothing remote can load
    app_csp = client.get("/api/lectures").headers["content-security-policy"]
    assert "script-src 'self'" in app_csp and "unsafe-inline" not in app_csp.split("style-src")[0]  # the app stays strict


@pytest.mark.parametrize("name,data,msg", [
    ("fake.pdf", b"<html>not a pdf</html>", "isn't a PDF"),
    ("fake.pptx", b"%PDF-1.4 nope", "isn't a PowerPoint"),
    ("notes.docx", b"PK\x03\x04", "PDF, PowerPoint"),
    ("empty.pdf", b"", "empty"),
])
def test_lecture_import_checks_content(client, name, data, msg):
    r = _import(client, name, data)
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_zip_bomb_and_non_deck_zip_are_refused(client, monkeypatch):
    from readhold import lectures

    monkeypatch.setattr(lectures, "MAX_ZIP_TOTAL", 1000)
    r = _import(client, "big.pptx", _pptx_bytes())
    assert r.status_code == 422 and "too large" in r.json()["detail"]
    monkeypatch.setattr(lectures, "MAX_ZIP_TOTAL", 400 * 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    r = _import(client, "notadeck.pptx", buf.getvalue())
    assert r.status_code == 422 and "isn't a PowerPoint deck" in r.json()["detail"]


def test_lecture_position_clamp_delete_restore(client):
    lec = _import(client, "w.pdf", _pdf_bytes(3)).json()
    assert client.patch(f"/api/lectures/{lec['id']}", json={"position": 99, "page_tint": "night"}).json()["position"] == 2
    client.delete(f"/api/lectures/{lec['id']}")
    assert client.get(f"/api/lectures/{lec['id']}").status_code == 404
    assert client.post(f"/api/lectures/{lec['id']}/restore").status_code == 200
    assert client.get("/api/lectures/not-an-id").status_code == 404


# ------------------------------------------------------------------ notebook
def test_notebook_notes_questions_become_cards(client):
    lec = _import(client, "w.pdf", _pdf_bytes()).json()
    lid = lec["id"]
    client.post(f"/api/lectures/{lid}/notes", json={"page": 0, "kind": "text", "body": "Steps go *against* the gradient"})
    q = client.post(f"/api/lectures/{lid}/notes", json={"page": 1, "kind": "question", "body": "Why small steps?",
                                                       "data": {"back": "Big steps overshoot the minimum."}}).json()
    client.post(f"/api/lectures/{lid}/notes", json={"page": 0, "kind": "snip", "body": "the update rule",
                                                    "data": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.2}})
    client.post(f"/api/lectures/{lid}/notes", json={"kind": "cornell", "data": {"cues": "Why?", "notes": "Because", "summary": "S"}})
    assert client.post(f"/api/lectures/{lid}/notes", json={"page": 9, "kind": "text", "body": "x"}).status_code == 422
    assert client.post(f"/api/lectures/{lid}/notes", json={"kind": "virus", "body": "x"}).status_code == 422
    cards = [c for c in client.get("/api/cards").json() if c["source_type"] == "lecture_note"]
    assert cards[0]["front"] == "Why small steps?" and cards[0]["back"] == "Big steps overshoot the minimum."
    client.patch(f"/api/lecture-notes/{q['id']}", json={"data": {"back": "They'd overshoot."}})
    assert next(c for c in client.get("/api/cards").json() if c["source_id"] == q["id"])["back"] == "They'd overshoot."
    notes = client.get(f"/api/lectures/{lid}/notes").json()
    assert [n["kind"] for n in notes] == ["text", "snip", "question", "cornell"]  # by page, whole-lecture last
    md = client.get(f"/api/lectures/{lid}/export").json()["markdown"]
    assert "## Cornell sheet" in md and "**Q (Page 2):** Why small steps?" in md and "Snip (Page 1): the update rule" in md
    client.delete(f"/api/lecture-notes/{q['id']}")
    assert not [c for c in client.get("/api/cards").json() if c["source_id"] == q["id"]]


# ------------------------------------------------------------------ ink
def test_ink_is_cleaned_and_round_trips(client):
    lec = _import(client, "w.pdf", _pdf_bytes()).json()
    owner = f"{lec['id']}:0"
    strokes = [
        {"tool": "pen", "color": "#1e3a8a", "size": 0.004, "points": [[0.1, 0.1, 0.5], [0.2, 0.15, 0.7]]},
        {"tool": "<script>", "color": "red;background:url(x)", "size": 99, "points": [[0.3, 0.3], ["x", 1], [5, 5]]},
        {"no": "points"},
    ]
    r = client.put(f"/api/ink/lecture_page/{owner}", json={"strokes": strokes})
    assert r.status_code == 200 and r.json()["strokes"] == 2
    back = client.get(f"/api/ink/lecture_page/{owner}").json()["strokes"]
    assert back[0]["color"] == "#1e3a8a"
    assert back[1] == {"tool": "pen", "color": "#222222", "size": 0.004, "points": [[0.3, 0.3, 0.5]]}
    assert client.get("/api/ink/secrets/abc").status_code == 404
    assert client.put("/api/ink/lecture_page/../../x", json={"strokes": []}).status_code == 404


def test_ink_size_limit(client, monkeypatch):
    from readhold import lectures

    monkeypatch.setattr(lectures, "MAX_INK_BYTES", 200)
    many = [{"tool": "pen", "color": "#000000", "size": 0.004, "points": [[0.1, 0.1, 0.5]] * 50}]
    assert client.put("/api/ink/journal/2026-11-12", json={"strokes": many}).status_code == 413


# ------------------------------------------------------------------ journal and letters
def test_journal_page_with_day_story_and_memories(client, db):
    today = dt.date.today()
    q = client.post("/api/quests", json={"title": "Exam", "questions": ["What is a gradient?"]}).json()
    step = client.post(f"/api/quests/{q['id']}/steps", json={"title": "Recall the update rule"}).json()
    client.patch(f"/api/quest-steps/{step['id']}", json={"done": True, "output": "wrote it from memory"})
    s = client.post("/api/sessions", json={"energy": "medium", "quest_id": q["id"], "step_id": step["id"]}).json()
    client.patch(f"/api/sessions/{s['id']}", json={"focused_ms": 25 * 60_000, "output": "notes", "feel": "energized", "ended": True})
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    client.put(f"/api/journal/{week_ago}", json={"weather": "rainy", "body": "Tough week start."})
    page = client.get(f"/api/journal/{today.isoformat()}").json()
    texts = [i["text"] for i in page["story"]]
    assert any("Worked on Recall the update rule · 25 min → notes" in t for t in texts)
    assert "Finished: Recall the update rule" in texts
    assert page["memories"] == [{"label": "A week ago", "day": week_ago, "weather": "rainy", "body": "Tough week start."}]
    assert set(page["prompts"]) == {"gratitude", "learning", "win", "worry", "kindness"}
    saved = client.put(f"/api/journal/{today.isoformat()}", json={"weather": "bright", "body": "Good focus.",
                                                                  "prompts": [{"q": "What went right?", "a": "Recall worked"}]}).json()
    assert saved["weather"] == "bright" and saved["prompts"][0]["a"] == "Recall worked"
    again = client.put(f"/api/journal/{today.isoformat()}", json={"weather": "sunny", "body": "Edited."}).json()
    assert again["id"] == saved["id"]  # one page per day
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    assert client.put(f"/api/journal/{tomorrow}", json={"body": "x"}).status_code == 422
    assert client.get("/api/journal/2026-13-45").status_code == 422
    assert client.put(f"/api/journal/{today.isoformat()}", json={"weather": "tornado"}).status_code == 422


def test_letters_stay_sealed_until_their_day(client, db):
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    r = client.post("/api/letters", json={"body": "Dear future me: you passed.", "open_on": future}).json()
    assert client.post(f"/api/letters/{r['id']}/open").status_code == 403
    listed = client.get("/api/letters").json()
    assert listed["sealed"][0]["ready"] is False and "body" not in listed["sealed"][0]  # the text stays hidden
    assert client.post("/api/letters", json={"body": "x", "open_on": dt.date.today().isoformat()}).status_code == 422
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    db.execute("UPDATE letters SET open_on=? WHERE id=?", (past, r["id"]))
    page = client.get(f"/api/journal/{dt.date.today().isoformat()}").json()
    assert page["letters_due"][0]["id"] == r["id"]
    opened = client.post(f"/api/letters/{r['id']}/open").json()
    assert opened["body"] == "Dear future me: you passed." and opened["opened_at"]


def test_note_cannot_move_to_missing_page_and_export_has_everything(client, home):
    import json as _json

    lec = _import(client, "w.pdf", _pdf_bytes()).json()
    n = client.post(f"/api/lectures/{lec['id']}/notes", json={"page": 0, "kind": "text", "body": "x"}).json()
    assert client.patch(f"/api/lecture-notes/{n['id']}", json={"page": 5}).status_code == 422
    assert client.patch(f"/api/lecture-notes/{n['id']}", json={"page": 1}).json()["page"] == 1
    client.put(f"/api/journal/{dt.date.today().isoformat()}", json={"weather": "sunny", "body": "hi"})
    path = client.post("/api/export/all").json()["path"]
    data = _json.loads(open(path, encoding="utf-8").read())
    for table in ("lectures", "lecture_notes", "ink", "journal_entries", "letters", "quests", "habits", "day_logs"):
        assert table in data
    assert data["lecture_notes"][0]["body"] == "x" and data["journal_entries"][0]["body"] == "hi"


def test_html_lecture_gets_scroll_reporter_for_the_pen(client):
    from readhold.lectures import SCROLL_REPORTER, with_scroll_reporter

    assert with_scroll_reporter(b"<html><body><p>x</p></BODY></html>") == b"<html><body><p>x</p>" + SCROLL_REPORTER + b"</BODY></html>"
    assert with_scroll_reporter(b"<p>no body tag</p>").endswith(SCROLL_REPORTER)
    lec = _import(client, "demo.html", HTML).json()
    body = client.get(f"/api/lectures/{lec['id']}/content.html").content
    assert body.count(b'readhold:"scroll"') == 1 and body.index(SCROLL_REPORTER) < body.lower().rindex(b"</body>")
    # the stored original is untouched
    from readhold import config
    original = (config.library_dir() / f"{client.get(f'/api/lectures/{lec[chr(105) + chr(100)]}').json()['file_hash']}.html").read_bytes()
    assert original == HTML


def test_notebook_size_settings(client):
    s = client.put("/api/settings", json={"notebook_width": 520, "note_scale": 1.2}).json()
    assert s["notebook_width"] == 520 and s["note_scale"] == 1.2


def test_blank_notebook_pages_writing_and_export(client):
    nb = client.post("/api/lectures/notebook", json={"title": "Linear algebra", "paper": "grid"}).json()
    assert nb["kind"] == "notebook" and nb["pages"] == 1
    lid = nb["id"]
    lec = client.get(f"/api/lectures/{lid}").json()
    assert lec["page_list"][0]["layout"] == {"paper": "grid"} and lec["page_list"][0]["text"] == ""
    # writing is saved per page; a new page keeps the paper of the last one
    assert client.patch(f"/api/lectures/{lid}/pages/0", json={"text": "Eigenvectors keep their direction."}).status_code == 200
    page = client.post(f"/api/lectures/{lid}/pages").json()
    assert page["ord"] == 1 and page["layout"] == {"paper": "grid"}
    assert client.patch(f"/api/lectures/{lid}/pages/1", json={"paper": "dotted"}).status_code == 200
    lec = client.get(f"/api/lectures/{lid}").json()
    assert lec["pages"] == 2 and lec["position"] == 1
    assert lec["page_list"][0]["text"].startswith("Eigenvectors") and lec["page_list"][1]["layout"] == {"paper": "dotted"}
    # notes, ink and export work as for any lecture
    assert client.post(f"/api/lectures/{lid}/notes", json={"page": 1, "kind": "text", "body": "Ask about rank", "color": "mint"}).status_code == 200
    md = client.get(f"/api/lectures/{lid}/export").json()["markdown"]
    assert "## Page 1" in md and "Eigenvectors keep their direction." in md and "Ask about rank" in md
    # bad input is refused
    assert client.patch(f"/api/lectures/{lid}/pages/7", json={"text": "x"}).status_code == 404
    assert client.patch(f"/api/lectures/{lid}/pages/0", json={"paper": "papyrus"}).status_code == 422
    assert client.post(f"/api/lectures/{lid}/notes", json={"page": 0, "kind": "text", "body": "x", "color": "red;}"}).status_code == 422
    assert client.get(f"/api/lectures/{lid}/content.html").status_code == 404
    assert client.get(f"/api/lectures/{lid}/pages/0/image").status_code == 404


def test_imported_lectures_cannot_get_notebook_pages(client):
    lid = _import(client, "slides.pdf", _pdf_bytes(1)).json()["id"]
    assert client.post(f"/api/lectures/{lid}/pages").status_code == 404
    assert client.patch(f"/api/lectures/{lid}/pages/0", json={"text": "x"}).status_code == 404
    assert "text" not in client.get(f"/api/lectures/{lid}").json()["page_list"][0]
