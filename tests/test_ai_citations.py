"""Quote and anchor verification (AI plan, milestone 2.1): fake citations are always caught, in every feature.

One set of fake citations is run against the checker itself and against every feature that shows a quote.
A feature that calls the model and is not in FEATURES below fails `test_every_feature_that_calls_a_model_is_checked_here`,
so a new feature cannot skip this file. No test reaches a real server (see conftest)."""
import json
import re
from pathlib import Path

import httpx
import pytest

from readhold.ai import guard
from tests.conftest import SAMPLE_MD
from tests.test_ai import LOCAL
from tests.test_ai_digest import _wait as wait_digest

ROOT = Path(__file__).resolve().parents[1]
REAL = "The SMR is a gating network over token blocks."
OTHER_DOC = "# Bread\n\n## Method\n\nFold the dough every thirty minutes and keep the starter warm all week.\n"
FAKES = {
    "invented": "SMR was peer-reviewed at a top venue in 2019",
    "one_word_changed": "The SMR is a gating network over token pieces",
    "letter_swapped": "The SMR is a gating netwrok over token blocks",
    "lookalike_letter": "The SMR is a gating netwоrk over token blocks",  # a Cyrillic o
    "other_document": "Fold the dough every thirty minutes and keep the starter warm",
    "not_sent": "On the LongBench suite, SMR scores 71.2 versus 70.8",
    "across_sections": "top-k routing is cheap. On the LongBench suite",
    "hidden_section": "A. Author. Memory tokens. 2020",
    "too_short": "gating network",
    "empty": "",
    "only_punctuation": "... --- !!! ??? ;;; ,,,",
}


# ------------------------------------------------------------------ the checker itself
def _doc(client, text=SAMPLE_MD):
    r = client.post("/api/import/text", json={"title": "", "text": text, "format": "markdown"})
    assert r.status_code == 200, r.text
    return r.json()


def _sentences(client, doc_id):
    full = client.get(f"/api/documents/{doc_id}").json()
    return {s["text"]: (s["ord"], sec["title"]) for sec in full["sections"] for p in sec["paragraphs"] for s in p["sentences"]}


def test_the_checker_keeps_a_real_quote_and_catches_every_fake(client, db):
    doc = _doc(client)
    other = _doc(client, OTHER_DOC)
    by = _sentences(client, doc["id"])
    at = f"{doc['id']}:{by[REAL][0]}"
    assert guard.verify_citations(db, [{"anchor": at, "quote": REAL}]).status == "verified"
    for name, quote in FAKES.items():
        if name in ("not_sent", "hidden_section"):
            continue  # real text of the document: "not sent" is a matter for each feature, below
        got = guard.verify_citations(db, [{"anchor": at, "quote": quote}])
        assert got.kept == [] and got.status == "unverified", name
    # the text of another document, cited with its own anchor, is real; cited as this document, it is caught
    o = _sentences(client, other["id"])
    other_at = f"{other['id']}:{next(iter(o.values()))[0]}"
    assert guard.verify_citations(db, [{"anchor": other_at, "quote": FAKES["other_document"]}]).kept
    assert not guard.verify_citations(db, [{"anchor": at, "quote": FAKES["other_document"]}]).kept


@pytest.mark.parametrize("anchor", [
    "", "nonsense", "f" * 32, "f" * 32 + ":0", "{doc}", "{doc}:", "{doc}:-1", "{doc}:99999", "{doc}:1.5", "{doc}:1 ", " {doc}:1",
    "{doc}:1;DROP TABLE sentences", "../../{doc}:1", "{DOC}:1", "note:{doc}", "session:{doc}", "{doc}:0:1", "{doc}:00000000001",
])
def test_a_malformed_or_missing_anchor_is_caught(client, db, anchor):
    doc = _doc(client)
    a = anchor.replace("{doc}", doc["id"]).replace("{DOC}", doc["id"].upper())
    got = guard.verify_citations(db, [{"anchor": a, "quote": REAL}])
    assert got.kept == [] and got.removed == 1
    assert db.scalar("SELECT COUNT(*) FROM sentences") > 0


def test_a_quote_from_a_removed_document_section_or_paragraph_is_caught(client, db):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    o = by[REAL][0]
    at = f"{doc['id']}:{o}"
    section = db.scalar("SELECT p.section_id FROM sentences s JOIN paragraphs p ON p.id=s.paragraph_id WHERE s.document_id=? AND s.ord=?", (doc["id"], o))
    paragraph = db.scalar("SELECT paragraph_id FROM sentences WHERE document_id=? AND ord=?", (doc["id"], o))
    assert guard.verify_citations(db, [{"anchor": at, "quote": REAL}]).kept
    db.execute("UPDATE sections SET deleted=1 WHERE id=?", (section,))
    assert not guard.verify_citations(db, [{"anchor": at, "quote": REAL}]).kept
    db.execute("UPDATE sections SET deleted=0 WHERE id=?", (section,))
    db.execute("UPDATE paragraphs SET deleted=1 WHERE id=?", (paragraph,))
    assert not guard.verify_citations(db, [{"anchor": at, "quote": REAL}]).kept
    db.execute("UPDATE paragraphs SET deleted=0 WHERE id=?", (paragraph,))
    client.delete(f"/api/documents/{doc['id']}")
    assert not guard.verify_citations(db, [{"anchor": at, "quote": REAL}]).kept


def test_numbers_keep_their_sign_their_percent_and_their_decimals(client, db):
    doc = _doc(client, "# Numbers\n\n## Results\n\nThe temperature fell by -3 degrees overnight. Compute dropped by 41% on long inputs. The score was 71.2 on the suite.\n")
    by = _sentences(client, doc["id"])
    at = lambda text: f"{doc['id']}:{by[text][0]}"  # noqa: E731
    fell, dropped, score = (k for k in by)
    assert guard.verify_citations(db, [{"anchor": at(fell), "quote": "temperature fell by -3 degrees"}]).kept
    assert not guard.verify_citations(db, [{"anchor": at(fell), "quote": "temperature fell by 3 degrees"}]).kept
    assert guard.verify_citations(db, [{"anchor": at(dropped), "quote": "Compute dropped by 41% on long inputs"}]).kept
    assert not guard.verify_citations(db, [{"anchor": at(dropped), "quote": "Compute dropped by 41 on long inputs"}]).kept
    assert guard.verify_citations(db, [{"anchor": at(score), "quote": "The score was 71.2 on the suite"}]).kept
    assert not guard.verify_citations(db, [{"anchor": at(score), "quote": "The score was 712 on the suite"}]).kept
    assert not guard.verify_citations(db, [{"anchor": at(score), "quote": "The score was 71 2 on the suite"}]).kept
    # what does not change a meaning still matches: case, spacing, quotation marks, a comma before a word
    assert guard.verify_citations(db, [{"anchor": at(score), "quote": "the  SCORE was “71.2” on the suite"}]).kept


def test_a_flood_of_citations_is_cut_off(client, db):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    at = f"{doc['id']}:{by[REAL][0]}"
    many = [{"anchor": at, "quote": REAL}] * 500
    got = guard.verify_citations(db, many)
    assert len(got.kept) == guard.MAX_CITATIONS and got.removed == 500 - guard.MAX_CITATIONS and got.status == "partly"


# ------------------------------------------------------------------ every feature
def _server(client, quote_for):
    """A fake model: every feature gets an answer whose quote is `quote_for(feature)`."""
    def handle(request):
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        if "summarise one part" in system:
            out = {"summary": "A part.", "points": [{"text": "A point.", "quote": quote_for("digest")}], "keywords": []}
        elif "combine the summaries" in system:
            out = {"summary": "The paper.", "key_ideas": [{"text": "An idea.", "anchor": "", "quote": quote_for("digest")}], "keywords": [], "difficulty": "intermediate"}
        elif "organize their library" in system:
            out = {"tags": [{"tag": "routing", "quote": quote_for("organize")}], "related": []}
        elif "judge a list of ideas" in system:
            out = {"groups": [{"label": "One", "ideas": [0], "best": 0}]}
        elif "help a reader brainstorm" in system:
            out = {"ideas": [{"text": "An idea.", "sources": [{"anchor": "", "quote": quote_for("brainstorm")}]}]}
        elif "order in which to read" in system:
            out = {"order": [{"document": 1, "difficulty": "medium", "reason": "Start here.", "quote": quote_for("plan")}]}
        elif "help a reader study" in system:
            out = {"items": [{"text": "A note.", "answer": "An answer.", "anchor": "", "quote": quote_for("notes")}]}
        elif "from their own library" in system:
            out = {"action": "answer", "found": True, "answer": "It is this.", "citations": [{"anchor": "", "quote": quote_for("library")}]}
        elif "<question>" in user:
            out = {"found": True, "answer": "It is this.", "citations": [{"anchor": "", "quote": quote_for("ask")}]}
        elif "(The selected passage)" in user:
            out = {"explanation": "It means this.", "terms": [], "feedback": "", "quote": quote_for("explain")}
        else:
            anchor = re.search(r'<source anchor="([0-9a-f]{32}:\d+)" trust="imported">', user)
            out = {"recap": [{"text": "You read this.", "anchor": anchor.group(1) if anchor else "", "quote": quote_for("resume")}], "point": "", "next": ""}
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(out)}, "prompt_eval_count": 10, "eval_count": 10})

    client.app.state.ai.transport = httpx.MockTransport(handle)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=LOCAL)


def _resume(client, doc_id, by):
    """Read the Method section only, then ask for the recap. Returns the quotes shown as verified, and the status."""
    first = by[REAL][0]
    client.post(f"/api/documents/{doc_id}/position", json={"position": first})
    s = client.post("/api/sessions", json={"document_id": doc_id}).json()
    client.post(f"/api/documents/{doc_id}/read", json={"ords": [first, first + 1]})
    client.post(f"/api/documents/{doc_id}/position", json={"position": first + 1})
    client.patch(f"/api/sessions/{s['id']}", json={"focused_ms": 60_000, "ended": True})
    r = client.post(f"/api/documents/{doc_id}/resume/brief", json={"fresh": True})
    assert r.status_code == 200, r.text
    b = r.json()["brief"]
    return [x.get("quote", "") for x in b["recap"] if x["verified"]], b["status"]


def _explain(client, doc_id, by):
    r = client.post(f"/api/documents/{doc_id}/explain", json={"sentence": by[REAL][0], "end_sentence": by[REAL][0], "level": "student", "fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return ([x["quote"]] if x["status"] == "verified" else []), x["status"]


def _digest(client, doc_id, by):
    client.post(f"/api/documents/{doc_id}/digest", json={"fresh": True})
    d = wait_digest(client, doc_id)["digest"]
    assert d is not None
    return [x.get("quote", "") for x in d["key_ideas"] if x["verified"]], d["status"]


def _ask(client, doc_id, by):
    """A question only the Method section answers: the other sections are not sent."""
    r = client.post(f"/api/documents/{doc_id}/ask", json={"question": "What is the SMR gating network over token blocks?", "fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return [c.get("quote", "") for c in x["citations"] if c["verified"]], x["status"]


def _library(client, doc_id, by):
    """The same question across the whole library: only the Method section of this document matches all its words."""
    r = client.post("/api/library/ask", json={"question": "What is the SMR gating network over token blocks?", "fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return [c.get("quote", "") for c in x["citations"] if c["verified"]], x["status"]


def _notes(client, doc_id, by):
    """Study notes from one highlighted sentence: only that highlight is sent."""
    client.post("/api/highlights", json={"document_id": doc_id, "sentence": by[REAL][0], "end_sentence": by[REAL][0], "type": "claim"})
    r = client.post(f"/api/documents/{doc_id}/study-notes", json={"source": "highlights", "kind": "notes", "fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return [i.get("quote", "") for i in x["items"] if i["verified"]], x["status"]


def _plan(client, doc_id, by):
    """A reading plan for this document and another: the model sees each one's opening and where you go on from.
    You are at the Method section, so its opening is sent; the Results section is not."""
    client.post(f"/api/documents/{doc_id}/position", json={"position": by[REAL][0]})
    other = _doc(client, "# Soil\n\n## One\n\nRain soaks into the soil of the hills slowly every spring.\n")
    r = client.post("/api/reading-plan/suggest", json={"document_ids": [doc_id, other["id"]], "fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return [o.get("quote", "") for o in x["order"] if o["verified"]], x["status"]


def _brainstorm(client, doc_id, by):
    """Ideas for this document, from its one highlighted sentence: the rest of it is not sent."""
    client.post("/api/highlights", json={"document_id": doc_id, "sentence": by[REAL][0], "end_sentence": by[REAL][0], "type": "claim"})
    r = client.post("/api/brainstorm", json={"kind": "document", "id": doc_id, "fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return [c["quote"] for i in x["ideas"] if i["verified"] for c in i["sources"]], x["status"]


def _organize(client, doc_id, by):
    """Tags for this document: the model reads its opening (which holds the Method sentence), never the Results."""
    r = client.post(f"/api/documents/{doc_id}/organize/suggest", json={"fresh": True})
    assert r.status_code == 200, r.text
    x = r.json()["result"]
    return [t["quote"] for t in x["tags"] if t["verified"]], x["status"]


FEATURES = {"resume": _resume, "explain": _explain, "digest": _digest, "ask": _ask, "library": _library, "notes": _notes, "plan": _plan,
            "brainstorm": _brainstorm, "organize": _organize}


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_each_feature_shows_a_real_quote(client, feature):
    doc = _doc(client)
    by = _sentences(client, doc["id"])
    _server(client, lambda f: REAL)
    shown, status = FEATURES[feature](client, doc["id"], by)
    assert shown and guard._plain(shown[0]) == guard._plain(REAL) and status == "verified"  # the check is not vacuous


@pytest.mark.parametrize("fake", sorted(FAKES))
@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_each_feature_catches_every_fake_citation(client, feature, fake):
    if feature == "digest" and fake == "not_sent":
        pytest.skip("the digest reads every visible section, so this sentence was sent; the hidden section is its not-sent case")
    doc = _doc(client)
    _doc(client, OTHER_DOC)
    by = _sentences(client, doc["id"])
    _server(client, lambda f: FAKES[fake])
    shown, status = FEATURES[feature](client, doc["id"], by)
    assert shown == [] and status == "unverified", (feature, fake, shown)


# modules that may call the port directly, and why: guard.ask itself, and Test connection (a fixed text, nothing of yours)
DIRECT_CALLERS = {"guard", "api", "port"}


def _model_callers(extra: dict[str, str] | None = None) -> set[str]:
    """Every module under readhold/ that calls a model: through guard.ask (by any name) or port.complete."""
    import ast

    sources = {p.relative_to(ROOT / "readhold").with_suffix("").as_posix().replace("/", "."): p.read_text("utf-8")
               for p in (ROOT / "readhold").rglob("*.py")}
    sources.update(extra or {})
    found = set()
    for name, text in sources.items():
        short = name.rsplit(".", 1)[-1]
        if short in DIRECT_CALLERS:
            continue
        tree = ast.parse(text)
        ask_names = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("guard")
                     for a in n.names if a.name == "ask"}
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr in ("ask", "complete")) or (isinstance(f, ast.Name) and f.id in ask_names):
                if isinstance(f, ast.Attribute) and f.attr == "ask" and not (isinstance(f.value, ast.Name) and f.value.id not in ("self",)):
                    continue
                found.add(short)
    return found


# features that show no quote at all, and why; each is called once below to show its result holds none
NO_QUOTES = {
    "tidy": "rewrites your own text (5.2); what it adds is marked as new words, not quoted",
    "chat": "drafts tasks from your own words and plan (5.3); a task is not a claim about a document",
    "notechat": "rewrites your own note or writes what you ask for (5.4); it cites nothing, and a rewrite lists its new words",
}


def test_every_feature_that_calls_a_model_is_checked_here():
    callers = _model_callers()
    known = set(FEATURES) | set(NO_QUOTES)
    assert callers == known, f"add the new feature to FEATURES (or NO_QUOTES, with a reason) in this file: {sorted(callers - known)}"


def test_the_features_without_quotes_show_none(client):
    def handle(request):
        system = json.loads(request.content)["messages"][0]["content"]
        out = {"tasks": [{"task": 1, "text": "Go to the gym", "minutes": 30, "day": "", "quote": REAL}]} if "tidy what they wrote" in system \
            else {"reply": "Done.", "action": "add", "text": "An idea.", "quote": REAL} if "one of their notes" in system             else {"reply": "A plan.", "tasks": [{"text": "Read the paper", "day": "", "minutes": 30, "quote": REAL}]}
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(out)}, "prompt_eval_count": 1, "eval_count": 1})

    client.app.state.ai.transport = httpx.MockTransport(handle)
    client.app.state.ai.retry_wait = 0
    client.put("/api/settings", json=LOCAL)
    client.post("/api/todos", json={"text": "gym", "minutes": 25})
    tidy = client.post("/api/tidy/suggest", json={"kind": "tasks"}).json()["result"]
    chat = client.post("/api/plan/chat", json={"messages": [{"who": "you", "text": "Plan my week"}]}).json()["result"]
    page = client.post("/api/pages", json={"title": "Trip", "body": "go to the hill"}).json()
    notechat = client.post(f"/api/notes/{page['id']}/chat", json={"messages": [{"who": "you", "text": "write an idea"}]}).json()["result"]
    for shown in (tidy, chat, notechat):
        assert "quote" not in json.dumps(shown) and "verified" not in json.dumps(shown)  # nothing that could look checked


# ------------------------------------------------------------------ found by a review of 2.1
EDGES = "# Edges\n\n## Results\n\nThe effect was unimportant for every model we tried. The method isn't stable on long inputs. Accuracy improved on all tasks by 15 points. The temperature fell by -30 degrees. The result was non-significant across all of the runs. We tested 1,000 items in the large set. The rate was 10\u207b\u00b3 per hour, e.g.-3 at night.\n"


@pytest.mark.parametrize("fake", [
    "important for every model we tried",  # a word cut out of "unimportant"
    "The method is",  # "isn't" cut short
    "Accuracy improved on all tasks by 1",  # 15 cut short
    "The temperature fell by -3",  # -30 cut short
    "5 points. The temperature fell by",  # starts inside "15"
    "significant across all of the runs",  # "non-significant" cut short
    "We tested 1.000 items in the large set",  # one thousand is not one point zero
    "The rate was 10^3 per hour",  # the sign of the exponent dropped
    "e.g. 3 at night",  # a minus dropped
])
def test_a_quote_must_start_and_end_on_whole_words_and_keep_its_numbers(client, db, fake):
    doc = _doc(client, EDGES)
    first = min(o for o, _ in _sentences(client, doc["id"]).values())
    assert not guard.verify_citations(db, [{"anchor": f"{doc['id']}:{first}", "quote": fake}]).kept, fake
    assert not guard.quote_in(fake, EDGES, 3), fake


@pytest.mark.parametrize("real", [
    "The effect was unimportant for every model",
    "The method isn't stable on long inputs",
    "improved on all tasks by 15 points",
    "The temperature fell by -30 degrees",
    "The temperature fell by \u221230 degrees",  # a typographic minus is the same minus
    "result was non-significant across all of the runs",
    "We tested 1,000 items in the large set",
    "We tested 1000 items in the large set",  # the thousands comma may be left out
    "The rate was 10^-3 per hour",  # a superscript minus is a minus
    "e.g. -3 at night",
])
def test_real_quotes_with_words_and_numbers_still_pass(client, db, real):
    doc = _doc(client, EDGES)
    first = min(o for o, _ in _sentences(client, doc["id"]).values())
    assert guard.verify_citations(db, [{"anchor": f"{doc['id']}:{first}", "quote": real}]).kept, real


def test_keywords_and_terms_are_whole_words_and_never_bare_number_words():
    from readhold.ai.digest import _clean_keywords

    within = guard._plain("Compute fell by 41% and the error by -3 points on 1,000 runs.")
    assert _clean_keywords(["%", "percent", "minus", "1.000", "points", "compute"], within, []) == ["points", "compute"]
    assert not guard.word_in("port", guard._plain("The points are fine."))
    assert guard.word_in("points", guard._plain("The points are fine."))


def test_the_registry_finds_every_way_of_calling_a_model():
    from tests.test_ai_citations import _model_callers

    assert _model_callers() == set(FEATURES) | set(NO_QUOTES)
    fake = "from .guard import ask as a\nfrom . import guard as g\n\ndef run(port):\n    a(port)\n    g.ask(port)\n    port.complete('x', '', '')\n"
    assert _model_callers({"newfeature": fake}) == set(FEATURES) | set(NO_QUOTES) | {"newfeature"}
