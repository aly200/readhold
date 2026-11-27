"""Security review before open-sourcing (AI plan, milestone 4.5): what the review found, kept fixed.

The threat model is docs/ai/PLAN.md section 6.1 (re-checked in 6.1a).
No test reaches a real server (see conftest)."""
import json
import time

import httpx

from readhold.ai import adapters
from tests.test_ai_citations import REAL, _doc, _server
from tests.test_ai_guard import FAKE_KEY
from tests.test_ai_privacy import _private

QUESTION = "What is the SMR gating network over token blocks?"


# ------------------------------------------------------------------ M1: a "local" server on another computer
def _remote_local(client, endpoint="http://203.0.113.7:11434"):
    seen = []
    _server(client, lambda f: REAL)
    inner = client.app.state.ai.transport.handler
    client.app.state.ai.transport = httpx.MockTransport(lambda req: seen.append(req) or inner(req))
    assert client.put("/api/settings", json={"ai_mode": "local", "ai_local_endpoint": endpoint}).status_code == 200
    return seen


def test_a_model_server_on_another_computer_gets_every_rule_text_leaving_the_computer_gets(client):
    secret = _doc(client)
    _private(client, secret["id"])
    keyed = _doc(client, f"# Keys\n\n## Setup\n\nThe SMR gating network over token blocks uses the key {FAKE_KEY} for its router.\n")
    seen = _remote_local(client)
    r = client.post(f"/api/documents/{secret['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 409 and "private" in r.json()["detail"].lower() and seen == []  # private stays here
    r = client.post(f"/api/documents/{keyed['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 200, r.text
    sent = b"".join(q.content for q in seen).decode()
    assert FAKE_KEY not in sent and "[redacted]" in sent  # secrets are removed before it goes
    client.put("/api/settings", json={"ai_preview": True})
    assert client.post(f"/api/documents/{keyed['id']}/ask", json={"question": QUESTION, "fresh": True}).status_code == 428  # and it is previewed


def test_a_model_server_on_this_computer_is_still_trusted(client):
    secret = _doc(client)
    _private(client, secret["id"])
    _remote_local(client, "http://localhost:11434")
    assert client.post(f"/api/documents/{secret['id']}/ask", json={"question": QUESTION}).status_code == 200


def test_on_this_computer_means_exactly_that():  # L1
    for url in ("http://localhost:11434", "http://127.0.0.1:8080", "http://127.5.5.5", "http://[::1]:11434"):
        assert adapters.is_local(url), url
    for url in ("http://127.evil.example", "http://127.0.0.1.nip.io", "https://127.attacker.test", "http://localhost.evil.example", "http://10.0.0.2"):
        assert not adapters.is_local(url), url
        assert adapters.endpoint_warning(url)


# ------------------------------------------------------------------ L2: another web page on this computer
def test_a_write_from_another_origin_is_refused(client):
    for headers in ({"Origin": "http://127.0.0.1:8888"}, {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
        r = client.post("/api/backup", headers=headers)
        assert r.status_code == 403, headers
    assert client.post("/api/backup", headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/api/backup").status_code == 200  # no Origin at all: not a browser page of another site
    assert client.get("/api/documents", headers={"Origin": "http://127.0.0.1:8888"}).status_code == 200  # reads are not writes


# ------------------------------------------------------------------ L6, L7: imports that would hang
def test_a_very_long_line_of_code_does_not_hang_the_import(client):
    line = "impl " + "a<" * 100_000 + "\n"
    start = time.monotonic()
    r = client.post("/api/import/file", files={"file": ("slow.rs", line.encode(), "text/plain")})
    assert r.status_code == 200 and time.monotonic() - start < 5


def test_a_pdf_with_too_many_pages_opens_as_plain_text_of_its_first_pages(client, tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas

    from readhold.importers import pdf_import
    monkeypatch.setattr(pdf_import, "MAX_PAGES", 3)
    f = tmp_path / "long.pdf"
    c = canvas.Canvas(str(f))
    for i in range(5):
        c.drawString(72, 720, f"Page {i} of a long report about gears and widgets.")
        c.showPage()
    c.save()
    r = client.post("/api/import/file", files={"file": ("long.pdf", f.read_bytes(), "application/pdf")})
    assert r.status_code == 200 and "5 pages" in r.json()["warning"]  # a failed import never blocks reading: plain text, with the reason
    text = json.dumps(client.get(f"/api/documents/{r.json()['id']}").json())
    assert "Page 2 of" in text and "Page 3 of" not in text  # only the first MAX_PAGES pages were read


# ------------------------------------------------------------------ I1, I2: keys never stored or echoed
def test_a_key_shaped_value_is_refused_in_any_setting(client, db):
    r = client.put("/api/settings", json={"tts_voice": FAKE_KEY})
    assert r.status_code == 422 and FAKE_KEY not in r.text
    assert FAKE_KEY not in json.dumps(db.all("SELECT value FROM settings"))


def test_a_rejected_request_does_not_echo_what_was_sent(client):
    doc = _doc(client)
    long = "x" * 100_001 + FAKE_KEY
    r = client.post(f"/api/documents/{doc['id']}/ask", json={"question": long})
    assert r.status_code == 422 and FAKE_KEY not in r.text and "xxxxxxxxxx" not in r.text


# ------------------------------------------------------------------ I3, I6: exports and headers
def test_exported_notes_never_overwrite_each_other_or_use_a_reserved_name(client):
    from pathlib import Path
    for _ in range(2):
        client.post("/api/import/text", json={"title": "CON", "text": "# CON\n\n## One\n\nSome text here about gears.\n", "format": "markdown"})
    path = Path(client.post("/api/export/all").json()["path"])
    md = sorted(p.name for p in path.parent.glob(f"notes-{path.stem.split('-', 2)[2]}/*.md"))
    assert len(md) >= 2 and len(set(md)) == len(md) and "CON.md" not in md


def test_every_response_says_it_is_for_this_page_only(client):
    r = client.get("/")
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert r.headers["cross-origin-resource-policy"] == "same-origin"
    assert "camera=()" in r.headers["permissions-policy"]


# ------------------------------------------------------------------ found while writing the 4.3 to 4.5 docs
def test_switching_the_endpoint_while_a_call_is_prepared_sends_nothing(client, db, monkeypatch):
    from readhold.ai import guard
    doc = _doc(client)
    seen = _remote_local(client, "http://localhost:11434")
    real_pack = guard.pack

    def pack_then_move(*a, **kw):
        out = real_pack(*a, **kw)
        db.execute("UPDATE settings SET value=? WHERE key='ai_local_endpoint'", (json.dumps("http://203.0.113.7:11434"),))
        return out

    monkeypatch.setattr(guard, "pack", pack_then_move)
    r = client.post(f"/api/documents/{doc['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 409 and "changed" in r.json()["detail"].lower() and seen == []


def test_the_preview_names_where_the_text_goes(client):
    doc = _doc(client)
    _remote_local(client)
    client.put("/api/settings", json={"ai_preview": True})
    r = client.post(f"/api/documents/{doc['id']}/ask", json={"question": QUESTION})
    assert r.status_code == 428 and r.json()["preview"]["provider"] == "remote:203.0.113.7"
    assert "cloud" not in r.json()["detail"].lower()


def test_clear_ai_history_stops_every_running_call(client, monkeypatch):
    stopped = []
    monkeypatch.setattr(client.app.state.ai, "cancel_all", lambda: stopped.append(1) or 0)
    assert client.delete("/api/ai/log").status_code == 200 and stopped


def test_a_kept_library_answer_still_says_what_was_left_out(client):
    secret = _doc(client)
    _private(client, secret["id"])
    _doc(client, "# Gating notes\n\n## One\n\nThe SMR gating network over token blocks is a router that keeps the best blocks.\n")
    _remote_local(client)
    one = client.post("/api/library/ask", json={"question": QUESTION}).json()["result"]
    two = client.post("/api/library/ask", json={"question": QUESTION}).json()["result"]
    assert one["id"] == two["id"] and one["private_left_out"] == two["private_left_out"] == 1


def test_a_pdf_over_the_page_cap_is_not_flagged_as_hiding_text(client, tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas

    from readhold.importers import pdf_import
    monkeypatch.setattr(pdf_import, "MAX_PAGES", 2)
    f = tmp_path / "long.pdf"
    c = canvas.Canvas(str(f))
    for i in range(4):
        c.drawString(72, 720, f"Page {i} of a long report about gears and widgets.")
        c.showPage()
    c.save()
    r = client.post("/api/import/file", files={"file": ("long.pdf", f.read_bytes(), "application/pdf")})
    listed = next(d for d in client.get("/api/documents").json() if d["id"] == r.json()["id"])
    assert "hidden_text" not in listed["flags"]


def test_one_documents_summary_export_never_overwrites_another(client):
    ids = [client.post("/api/import/text", json={"title": "CON", "text": "# CON\n\n## One\n\nSome text about gears.\n", "format": "markdown"}).json()["id"] for _ in range(2)]
    paths = [client.post(f"/api/documents/{i}/export").json()["path"] for i in ids]
    assert paths[0] != paths[1] and not any(p.endswith("\\CON.md") or p.endswith("/CON.md") for p in paths)


def test_a_key_inside_an_object_setting_is_refused(client):
    r = client.put("/api/settings", json={"comfort_by_type": {"pdf": {"note": FAKE_KEY}}})
    assert r.status_code == 422 and FAKE_KEY not in r.text


def test_a_refused_tag_is_not_echoed(client):
    doc = _doc(client)
    r = client.put(f"/api/documents/{doc['id']}/tags", json={"tags": ["two words here"]})
    assert r.status_code == 422 and "two words here" not in r.text
