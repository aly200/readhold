"""The evaluation harness (AI plan, milestone 4.1): one command prints scores for every feature.

What is checked here is the harness itself, not a model: its scoring, its sample set, that it runs in a throwaway
folder and leaves the real one alone, that it says so and stops when there is no model, and that the stand-in run
goes through the normal port and guards for all eleven features. No test reaches a real server (see conftest).
"""
import json
import os

import httpx
import pytest

from readhold.eval import harness, samples, score, standin

FEATURES = ("resume", "explain", "digest", "ask", "library", "notes", "plan", "brainstorm", "organize", "tidy", "chat", "notechat")


# ------------------------------------------------------------------ scoring, on results made by hand
@pytest.mark.parametrize("feature, payload, want", [
    ("resume", {"recap": [{"verified": True}, {"verified": False}, {"verified": True}]}, (2, 3)),
    ("explain", {"status": "verified", "quote": "a b c"}, (1, 1)),
    ("explain", {"status": "unverified", "quote": ""}, (0, 1)),
    ("digest", {"key_ideas": [{"verified": True}, {"verified": True}]}, (2, 2)),
    ("ask", {"found": True, "citations": [{"verified": True}, {"verified": False}]}, (1, 2)),
    ("ask", {"found": False, "status": "not_found", "citations": []}, (0, 0)),
    ("library", {"found": True, "citations": [{"verified": True}]}, (1, 1)),
    ("notes", {"items": [{"verified": False}]}, (0, 1)),
    ("plan", {"order": [{"placed": True, "reason": "x", "verified": True}, {"placed": True, "reason": "", "verified": False},
                        {"placed": False, "reason": "", "verified": False}]}, (1, 1)),
    ("brainstorm", {"ideas": [{"verified": True}, {"verified": False}]}, (1, 2)),
    ("organize", {"tags": [{"verified": True}, {"verified": True}, {"verified": False}]}, (2, 3)),
    ("ask", None, (0, 0)),
    ("tidy", {"kind": "tasks", "items": [{"new_words": [], "verified": True}]}, (0, 0)),  # shows no quotes: the column says "-"
    ("chat", {"drafts": [{"due": "2026-11-27", "fits": True, "flags": [], "verified": True}]}, (0, 0)),
    ("notechat", {"action": "replace", "text": "x", "verified": True}, (0, 0)),
])
def test_quotes_are_counted_from_the_stored_result(feature, payload, want):
    assert score.quotes(feature, payload) == want


def test_found_and_not_found_are_judged_against_what_was_expected():
    found = {"found": True, "status": "verified", "answer": "x"}
    unverified = {"found": True, "status": "unverified", "answer": "x"}
    missing = {"found": False, "status": "not_found"}
    assert score.right(found, "found") and score.right(unverified, "found")  # shown, labelled: still an answer
    assert not score.right(missing, "found")
    assert score.right(missing, "not_found") and not score.right(found, "not_found")
    assert not score.right(None, "found") and not score.right(None, "not_found")  # a case that failed is never right


def test_steps_are_the_library_loop_s_steps():
    assert score.steps({"steps": [{"step": 1}, {"step": 2}]}) == 2
    assert score.steps({"steps": []}) == 0 and score.steps(None) == 0


def _preview(days, unplaced=(), total=None, per_day=15, deadline="2026-12-03"):
    placed = sum(i["minutes"] for d in days for i in d["items"])
    return {"days": days, "unplaced": list(unplaced), "fits": not unplaced, "per_day": per_day, "deadline": deadline,
            "total": placed + sum(u["minutes"] for u in unplaced) if total is None else total}


def _day(day, *minutes, busy=0):
    return {"day": day, "items": [{"minutes": m} for m in minutes], "minutes": sum(minutes), "busy": busy}


def test_a_plan_is_within_limits_only_if_no_day_is_over_none_is_late_and_nothing_is_lost():
    ok = score.plan_check(_preview([_day("2026-11-26", 10, 5), _day("2026-11-27", 15)]))
    assert ok == {"within": True, "over_days": 0, "late_days": 0, "lost_minutes": 0, "fits": True}
    assert not score.plan_check(_preview([_day("2026-11-26", 10, 6)]))["within"]  # 16 > 15 minutes
    assert score.plan_check(_preview([_day("2026-11-26", 10, busy=6)]))["over_days"] == 1  # with what was already planned
    assert score.plan_check(_preview([_day("2026-12-04", 5)]))["late_days"] == 1  # past the deadline
    assert score.plan_check(_preview([_day("2026-11-26", 5)], total=9))["lost_minutes"] == 4  # minutes dropped silently
    told = score.plan_check(_preview([_day("2026-11-26", 15)], unplaced=[{"minutes": 30}]))
    assert told["within"] and not told["fits"]  # what does not fit is shown as not fitting: that keeps the promise
    assert not score.plan_check(None)["within"]


def _row(task="ask", **kw):
    base = {"task": task, "latency_ms": 100, "tokens_in": 50, "tokens_out": 10, "attempts": 1, "checks": json.dumps({"schema": True, "fenced": 2}),
            "outcome": "ok"}
    return {**base, **kw}


def test_call_stats_come_from_the_ai_log_rows():
    rows = [_row(), _row(latency_ms=300, attempts=2, checks=json.dumps({"schema": True, "schema_failures": 1, "fenced": 1})),
            _row(latency_ms=200, attempts=2, outcome="invalid", tokens_out=0, checks=json.dumps({"schema": False, "schema_failures": 2, "fenced": 1})),
            _row(latency_ms=50, outcome="timeout", checks="{}", tokens_in=0, tokens_out=0)]
    s = score.calls(rows)
    assert s["calls"] == 4 and s["schema_failures"] == 3 and s["retries"] == 2 and s["failed"] == 2
    assert s["latency_median"] == 150 and s["latency_max"] == 300
    assert s["tokens_in"] == 150 and s["tokens_out"] == 20
    assert score.calls([])["calls"] == 0 and score.calls([])["latency_median"] is None
    assert score.calls([_row(checks="not json")])["schema_failures"] == 0  # a damaged checks cell is not a crash


def _case(feature, payload, ok=True, expect="", plan=None, log=None):
    return {"feature": feature, "ok": ok, "error": "" if ok else "The model server did not answer.", "payload": payload, "expect": expect,
            "plan": plan, "log": log if log is not None else [_row(feature)]}


def test_the_goals_follow_the_plan_s_done_when_rows():
    good_ask = [_case("ask", {"found": True, "status": "verified", "citations": [{"verified": True}]}, expect="found"),
                _case("ask", {"found": False, "status": "not_found", "citations": []}, expect="not_found")]
    assert score.feature_row("ask", good_ask)["goal"] == "pass"
    wrong = good_ask[:1] + [_case("ask", {"found": True, "status": "verified", "citations": [{"verified": True}]}, expect="not_found")]
    assert score.feature_row("ask", wrong)["goal"] == "FAIL"  # it answered what the text does not say
    guessed = [_case("ask", {"found": True, "status": "partly", "citations": [{"verified": True}, {"verified": False}]}, expect="found")]
    assert score.feature_row("ask", guessed)["goal"] == "FAIL"  # every quote must verify
    lib = [_case("library", {"found": True, "status": "verified", "citations": [{"verified": True}], "steps": [{}, {}]}, expect="found")]
    row = score.feature_row("library", lib)
    assert row["goal"] == "pass" and row["max_steps"] == 2 and "2 steps" in row["check"]
    lib[0]["payload"]["steps"] = [{}, {}, {}, {}]
    assert score.feature_row("library", lib)["goal"] == "FAIL"
    within = {"within": True, "fits": True, "over_days": 0, "late_days": 0, "lost_minutes": 0}
    assert score.feature_row("plan", [_case("plan", {"order": []}, plan=within)])["goal"] == "pass"
    assert score.feature_row("plan", [_case("plan", {"order": []}, plan={**within, "within": False, "over_days": 1})])["goal"] == "FAIL"
    ideas = {"ideas": [{"verified": True}, {"verified": True}], "variety": 0.8}
    assert score.feature_row("brainstorm", [_case("brainstorm", ideas)])["goal"] == "pass"
    assert score.feature_row("brainstorm", [_case("brainstorm", {**ideas, "variety": 0.3})])["goal"] == "FAIL"
    assert score.feature_row("organize", [_case("organize", {"tags": [{"verified": True}], "model_reuse": 0.67})])["goal"] == "pass"
    assert score.feature_row("organize", [_case("organize", {"tags": [{"verified": True}], "model_reuse": 0.5})])["goal"] == "FAIL"  # half is not most
    assert score.feature_row("resume", [_case("resume", {"recap": [{"verified": True}]})])["goal"] == "-"  # judged by a person
    failed = [_case("ask", None, ok=False, expect="found")]
    row = score.feature_row("ask", failed)
    assert row["goal"] == "FAIL" and row["ran"] == "0/1"
    assert score.feature_row("ask", [])["goal"] == "n/a"


def test_tidy_counts_the_proposals_that_add_no_word_you_did_not_write():
    tasks = {"kind": "tasks", "items": [{"new_words": []}, {"new_words": ["plan"]}, {"new_words": []}]}
    assert score.tidy_check(tasks) == {"proposals": 3, "clean": 2, "note_new_words": None, "restored": 0}
    note = {"kind": "note", "body": "*Tidied*\n\nA note.", "new_words": ["3", "monday"], "restored": ["#private"]}
    assert score.tidy_check(note) == {"proposals": 1, "clean": 0, "note_new_words": 2, "restored": 1}
    routine = {"kind": "routine", "steps": [{"text": "Drink water", "minutes": 0}], "new_words": []}
    assert score.tidy_check(routine) == {"proposals": 1, "clean": 1, "note_new_words": None, "restored": 0}
    assert score.tidy_check({"kind": "note", "body": "", "new_words": [], "restored": []})["proposals"] == 0  # an empty rewrite proposes nothing
    assert score.tidy_check({"kind": "routine", "steps": [], "new_words": []})["proposals"] == 0
    assert score.tidy_check(None)["proposals"] == 0

    row = score.feature_row("tidy", [_case("tidy", tasks), _case("tidy", routine)])
    assert row["proposals"] == 4 and row["no_new_words"] == 3 and row["no_new_words_share"] == 0.75 and row["goal"] == "pass"
    assert row["check"] == "no new words 3/4" and row["quotes"] == 0 and score._cells(row)[2] == "-"
    row = score.feature_row("tidy", [_case("tidy", tasks), _case("tidy", note)])
    assert row["no_new_words"] == 2 and row["proposals"] == 4 and row["goal"] == "FAIL"  # half is not most
    assert row["check"] == "no new words 2/4, note +2, 1 restored" and row["note_new_words"] == 2 and row["restored"] == 1
    assert score.feature_row("tidy", [_case("tidy", {"kind": "tasks", "items": []})])["goal"] == "FAIL"  # nothing proposed: nothing shown to judge
    assert score.feature_row("tidy", [_case("tidy", tasks), _case("tidy", None, ok=False)])["goal"] == "FAIL"  # every case must run


def test_plan_chat_counts_the_drafts_that_fit_their_days_free_time():
    ok = {"drafts": [{"due": "2026-11-27", "fits": True, "flags": []}, {"due": "2026-11-28", "fits": True, "flags": []},
                     {"due": None, "fits": True, "flags": []}],  # any day: the chat may leave it open, and it loads no day
          "already": 1, "dropped": 0}
    assert score.chat_check(ok) == {"drafts": 3, "fit": 3, "dropped": 0, "already": 1}
    bad = {"drafts": [{"due": "2026-11-27", "fits": False, "flags": ["Over your free time that day: 70 of 60 minutes planned."]},
                      {"due": None, "fits": True, "flags": ["The model gave no real day: it has none."]},
                      {"due": "2026-11-28", "fits": True, "flags": ["The model's minutes were not usable: set to 25."]}],
           "already": 0, "dropped": 2}
    assert score.chat_check(bad) == {"drafts": 3, "fit": 0, "dropped": 2, "already": 0}
    assert score.chat_check(None) == {"drafts": 0, "fit": 0, "dropped": 0, "already": 0}

    row = score.feature_row("chat", [_case("chat", ok)])
    assert row["goal"] == "pass" and row["check"] == "fits 3/3, 0 dropped, 1 already planned"
    assert row["drafts"] == 3 and row["fit"] == 3 and row["already"] == 1 and row["dropped"] == 0
    assert row["quotes"] == 0 and score._cells(row)[2] == "-"
    row = score.feature_row("chat", [_case("chat", ok), _case("chat", bad)])
    assert row["goal"] == "FAIL" and row["check"] == "fits 3/6, 2 dropped, 1 already planned"  # every draft must fit
    assert score.feature_row("chat", [_case("chat", {"drafts": [], "already": 0, "dropped": 0})])["goal"] == "FAIL"  # no draft: nothing checked
    assert score.feature_row("chat", [_case("chat", ok), _case("chat", None, ok=False)])["goal"] == "FAIL"


def test_the_table_has_one_row_per_feature_and_prints_anywhere():
    rows = [score.feature_row(f, []) for f in FEATURES]
    text = score.render(rows, "Readhold evaluation")
    lines = text.splitlines()
    assert text.isascii()  # a Windows console in any code page can print it
    for f in FEATURES:
        assert sum(1 for ln in lines if ln.startswith(f + " ")) == 1, f
    assert lines[0] == "Readhold evaluation"
    widths = {len(ln) for ln in lines[1:len(FEATURES) + 4] if ln.strip()}
    assert len(widths) == 1, "the table's lines line up"


# ------------------------------------------------------------------ the sample set
def test_every_feature_has_cases_and_ask_and_library_have_both_kinds():
    by = {f: [c for c in samples.CASES if c["feature"] == f] for f in FEATURES}
    assert {c["feature"] for c in samples.CASES} == set(FEATURES) and all(by.values())
    for f in ("ask", "library"):
        assert {c["expect"] for c in by[f]} == {"found", "not_found"}, f
    for c in samples.CASES:
        for d in [c.get("doc"), *c.get("docs", [])]:
            assert d is None or d in samples.DOCS, c
    for doc, sentence in samples.HIGHLIGHTS:
        assert sentence in samples.DOCS[doc]
    for c in samples.CASES:
        if c.get("sentence"):
            assert c["sentence"] in samples.DOCS[c["doc"]]
        if c.get("read") or c.get("section"):
            assert f"## {c.get('read') or c.get('section')}\n" in samples.DOCS[c["doc"]]


def test_tidy_and_plan_chat_have_your_own_writing_to_work_on():
    assert {c["kind"] for c in samples.CASES if c["feature"] == "tidy"} == {"tasks", "note", "routine"}
    for c in samples.CASES:
        if c["feature"] == "chat":
            assert c["messages"][-1]["who"] == "you" and {m["who"] for m in c["messages"]} <= {"you", "model"}, c["name"]
            assert 15 <= c["minutes"] <= 720, c["name"]
    assert samples.TASKS and samples.NOTE["title"] and samples.NOTE["body"] and samples.ROUTINE["steps"]
    # your own writing is made when the first of these cases runs: after every reading feature, so the note is never
    # among what Ask my library searches (and the open tasks are never in the reading plan's way)
    order = [c["feature"] for c in samples.CASES]
    last_reading = max(i for i, f in enumerate(order) if f not in ("tidy", "chat", "notechat"))
    assert all(i > last_reading for i, f in enumerate(order) if f in ("tidy", "chat", "notechat"))


def test_the_harness_runs_every_feature_the_app_calls_a_model_for():
    from tests.test_ai_citations import FEATURES as CHECKED
    from tests.test_ai_citations import NO_QUOTES

    assert set(harness.RUNNERS) == set(CHECKED) | set(NO_QUOTES) == set(FEATURES)  # a new feature must be added here too
    assert set(score.NO_QUOTES) == set(NO_QUOTES)  # the features that show no quote: "-" in the quotes column
    assert set(harness.CALLS) == set(FEATURES)  # the calls a case makes, for the cloud warning's count


# ------------------------------------------------------------------ the stand-in model
def _body(system, user):
    return {"model": "stand-in", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "stream": False}


def test_the_stand_in_answers_test_connection_and_says_not_found_when_the_words_are_missing():
    got = standin.answer({"model": "x", "messages": [{"role": "user", "content": "Reply with the single word: ready"}]})
    assert got["message"]["content"] == "ready" and got["eval_count"] >= 0
    src = '<source anchor="' + "a" * 32 + ':3" trust="imported">\nThe router keeps the four highest-scoring blocks for each query.\n</source>'
    system = "You answer a reader's question about one document they are reading."
    yes = json.loads(standin.answer(_body(system, src + "\n\n<question>\nHow many blocks does the router keep?\n</question>"))["message"]["content"])
    no = json.loads(standin.answer(_body(system, src + "\n\n<question>\nWhat learning rate was the router trained with?\n</question>"))["message"]["content"])
    assert yes["found"] and yes["citations"][0]["quote"].startswith("The router keeps the four")
    assert not no["found"] and no["citations"] == []


def test_the_stand_in_knows_every_feature_s_prompt():
    from readhold.ai import prompts

    for name in ("resume", "explain", "digest_map", "digest", "ask", "library", "notes", "plan", "brainstorm", "brainstorm_critic", "organize",
                 "tidy", "chat", "notechat"):
        assert standin.feature_of(prompts.load(name).text, "") == name, name


# ------------------------------------------------------------------ isolation: the real data folder is left alone
def _snapshot(folder):
    return {p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture()
def real_home(home):
    """The user's real folder, with a database whose settings choose a local model, closed as after quitting the app."""
    from readhold.db import open_db

    db = open_db()
    for k, v in {"ai_mode": "local", "ai_local_model": "my-model", "wpm": 300}.items():
        db.execute("INSERT INTO settings (key, value, updated_at, id, device_id) VALUES (?,?,?,?,?)", (k, json.dumps(v), "2026-11-26", os.urandom(16).hex(), db.device))
    db.conn.close()
    (home / "data" / "ai_profiles.json").write_text(json.dumps({"ask": {"temperature": 0.1}}), "utf-8")
    return home


def test_the_user_s_model_settings_are_read_without_changing_anything(real_home):
    before = _snapshot(real_home)
    got = harness.read_settings(real_home)
    assert got["ai_mode"] == "local" and got["ai_local_model"] == "my-model" and got["wpm"] == 300
    assert "ai_local_endpoint" not in got or got["ai_local_endpoint"].startswith("http")
    assert harness.read_profiles(real_home) == {"ask": {"temperature": 0.1}}
    assert _snapshot(real_home) == before


def test_a_folder_without_readhold_data_is_not_created(tmp_path):
    empty = tmp_path / "never-used"
    assert harness.read_settings(empty) == {} and harness.read_profiles(empty) == {}
    assert not empty.exists()


def test_the_stand_in_run_never_touches_the_real_folder(real_home, monkeypatch):
    before = _snapshot(real_home)
    seen = {}
    real_open = harness._open_app

    def spy(*a, **kw):
        out = real_open(*a, **kw)
        from readhold import config

        seen["home"] = config.home()
        return out

    monkeypatch.setattr(harness, "_open_app", spy)
    report = harness.run(stand_in=True, only={"ask"})
    assert report["status"] == "done"
    assert seen["home"] != real_home and not seen["home"].exists()  # a throwaway folder, removed afterwards
    assert os.environ["READHOLD_HOME"] == str(real_home)  # put back
    assert _snapshot(real_home) == before


def test_keep_leaves_the_throwaway_folder_for_a_look(home):
    report = harness.run(stand_in=True, only={"organize"}, keep=True)
    from pathlib import Path

    kept = Path(report["kept"])
    try:
        assert kept.exists() and (kept / "data" / "readhold.db").exists() and kept != home
    finally:
        import shutil

        shutil.rmtree(kept, ignore_errors=True)


# ------------------------------------------------------------------ no model: say so, stop cleanly
def test_with_ai_off_it_says_so_and_stops(home, capsys):
    assert harness.main([]) == 0
    out = capsys.readouterr().out
    assert "AI is off" in out and "--stand-in" in out and "resume" not in out


def test_a_cloud_model_needs_a_yes_before_anything_is_sent(home, monkeypatch, capsys):
    monkeypatch.setattr(harness, "read_settings", lambda h: {"ai_mode": "cloud", "ai_cloud_provider": "anthropic"})
    opened = []
    monkeypatch.setattr(harness, "_open_app", lambda *a, **k: opened.append(1))
    assert harness.main([]) == 0
    out = capsys.readouterr().out
    assert "--yes" in out and "anthropic" in out and not opened


def test_a_model_that_does_not_answer_is_reported_without_scores(home, monkeypatch, capsys):
    """Settings name a local model, but its server is not running: Test connection fails, and nothing else is tried."""
    monkeypatch.setattr(harness, "read_settings", lambda h: {"ai_mode": "local", "ai_local_model": "my-model"})

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(harness, "_transport_for_tests", httpx.MockTransport(down))
    assert harness.main([]) == 0
    out = capsys.readouterr().out
    assert "did not answer" in out and "verified" not in out.lower()


def test_no_model_named_is_reported(home, monkeypatch, capsys):
    monkeypatch.setattr(harness, "read_settings", lambda h: {"ai_mode": "local", "ai_local_model": ""})
    assert harness.main([]) == 0
    assert "Choose a model" in capsys.readouterr().out


# ------------------------------------------------------------------ the port counts schema failures
def test_a_schema_failure_is_counted_in_the_log_even_when_the_retry_works(client, db):
    from pydantic import BaseModel

    from tests.test_ai import LOCAL

    class Out(BaseModel):
        n: int

    answers = iter(['{"n": "many"}', '{"n": 3}'])

    def server(request):
        return httpx.Response(200, json={"message": {"content": next(answers)}, "prompt_eval_count": 1, "eval_count": 1})

    client.put("/api/settings", json=LOCAL)
    port = client.app.state.ai
    port.transport, port.retry_wait = httpx.MockTransport(server), 0
    assert port.complete("ask", "s", "u", Out).data == {"n": 3}
    row = db.one("SELECT attempts, checks FROM ai_log ORDER BY rowid DESC LIMIT 1")
    assert row["attempts"] == 2 and json.loads(row["checks"])["schema_failures"] == 1


# ------------------------------------------------------------------ the whole run, on the stand-in
@pytest.fixture(scope="module")
def stand_in_run(tmp_path_factory):
    old = os.environ.get("READHOLD_HOME")
    os.environ["READHOLD_HOME"] = str(tmp_path_factory.mktemp("real"))
    try:
        yield harness.run(stand_in=True)
    finally:
        if old is None:
            os.environ.pop("READHOLD_HOME", None)
        else:
            os.environ["READHOLD_HOME"] = old


def test_the_stand_in_run_scores_all_twelve_features(stand_in_run):
    rows = {r["feature"]: r for r in stand_in_run["rows"]}
    assert stand_in_run["status"] == "done" and list(rows) == list(FEATURES)
    for f, r in rows.items():
        n = sum(1 for c in samples.CASES if c["feature"] == f)
        assert r["ran"] == f"{n}/{n}", (f, [c["error"] for c in stand_in_run["cases"] if c["feature"] == f])
        assert r["calls"] >= n and r["failed"] == 0 and r["schema_failures"] == 0, f
        assert max(len(c["log"]) for c in stand_in_run["cases"] if c["feature"] == f) <= harness.CALLS[f], f  # no retries here
        if f in score.NO_QUOTES:  # they show no quote: the column says "-"
            assert r["quotes"] == 0 and score._cells(r)[2] == "-", f
        elif f not in ("ask", "library"):  # those have cases with nothing to quote
            assert r["quotes"] > 0 and r["verified"] == r["quotes"], f
        assert r["goal"] in ("pass", "-"), (f, r)
    assert rows["library"]["max_steps"] == 2  # a search, then the answer
    assert rows["brainstorm"]["variety"] and rows["organize"]["model_reuse"] > 0.5


def test_the_stand_in_run_checks_tidy_for_invented_words(stand_in_run):
    """Tasks, a note and a routine are tidied. The stand-in puts a verb before the task that has none ("dentist
    appointment"): a word you did not write, which is counted. The note keeps your link and tag, so nothing is put back."""
    tidy = {r["feature"]: r for r in stand_in_run["rows"]}["tidy"]
    assert tidy["goal"] == "pass" and tidy["proposals"] >= 3
    assert 0.5 < tidy["no_new_words_share"] < 1 and tidy["no_new_words"] == tidy["proposals"] - 1
    assert tidy["note_new_words"] == 0 and tidy["restored"] == 0
    assert tidy["check"] == f"no new words {tidy['no_new_words']}/{tidy['proposals']}, note +0"
    kinds = {c["payload"]["kind"]: c["payload"] for c in stand_in_run["cases"] if c["feature"] == "tidy"}
    assert set(kinds) == {"tasks", "note", "routine"}
    items = kinds["tasks"]["items"]
    assert [i["new_words"] for i in items if i["new_words"]] == [["plan"]]
    assert any(len(i["split"]) == 2 for i in items) and any(i["due"] for i in items)  # a split, and a day the text implies
    assert len(items) < len(samples.TASKS)  # a task that is already clear is left as it is
    assert "[[Soil sensor log]]" in kinds["note"]["body"] and kinds["routine"]["steps"]


def test_the_stand_in_run_checks_that_plan_chat_drafts_fit(stand_in_run):
    """Two conversations; one asks for a task you already have, which code leaves out and counts."""
    chat = {r["feature"]: r for r in stand_in_run["rows"]}["chat"]
    assert chat["goal"] == "pass" and chat["drafts"] >= 3 and chat["fit"] == chat["drafts"]
    assert chat["dropped"] == 0 and chat["already"] == 1
    assert chat["check"] == f"fits {chat['fit']}/{chat['drafts']}, 0 dropped, 1 already planned"
    for c in stand_in_run["cases"]:
        if c["feature"] == "chat":
            assert c["payload"]["reply"] and all(d["due"] and d["fits"] and not d["flags"] for d in c["payload"]["drafts"]), c["name"]
            assert c["payload"]["minutes_a_day"] == next(s["minutes"] for s in samples.CASES if s["name"] == c["name"])


def test_every_call_of_the_stand_in_run_went_through_the_guards(stand_in_run):
    tasks = set()
    for c in stand_in_run["cases"]:
        for row in c["log"]:
            tasks.add(row["task"])
            assert "fenced" in json.loads(row["checks"]), (c["feature"], row["task"])  # guard.ask wrote its checks
    assert tasks == {"resume", "explain", "digest_map", "digest", "ask", "library", "notes", "plan", "brainstorm", "brainstorm_critic", "organize",
                     "tidy", "chat", "notechat"}


def test_not_found_cases_really_reach_the_model(stand_in_run):
    for c in stand_in_run["cases"]:
        if c.get("expect") == "not_found":
            assert c["log"], f"{c['name']}: no model call, so the case tests the search, not the model"


def test_the_command_prints_one_table_and_can_write_json(home, tmp_path, capsys):
    out_file = tmp_path / "scores.json"
    assert harness.main(["--stand-in", "--json", str(out_file)]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert "stand-in" in lines[0]
    for f in FEATURES:
        assert sum(1 for ln in lines if ln.startswith(f + " ")) == 1, f
    assert "tidy:" in out and "chat:" in out and "notechat:" in out  # the legend says what their checks count
    saved = json.loads(out_file.read_text("utf-8"))
    assert [r["feature"] for r in saved["rows"]] == list(FEATURES) and saved["samples"] == samples.VERSION


def test_only_runs_the_features_named(home, capsys):
    assert harness.main(["--stand-in", "--only", "ask,organize"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(ln.startswith("ask ") for ln in lines) and not any(ln.startswith("resume ") for ln in lines)
    with pytest.raises(SystemExit):
        harness.main(["--stand-in", "--only", "nonsense"])


def test_the_harness_imports_no_network_client_and_not_the_adapters():
    from pathlib import Path

    from tests.test_no_network import _clients, _imports

    folder = Path(harness.__file__).parent
    for path in folder.glob("*.py"):
        assert not _clients(path), path
        assert not {n for n in _imports(path) if "adapters" in n}, path
        assert "httpx" not in path.read_text("utf-8"), path


# ------------------------------------------------------------------ found by the review of 4.1
def test_a_library_loop_that_never_answered_is_not_a_right_not_found():
    ran_out = {"found": False, "status": "not_found", "steps": [{"action": "search"}, {"action": "search"}, {"action": "search", "ran": False}]}
    said = {"found": False, "status": "not_found", "steps": [{"action": "search"}, {"action": "answer"}]}
    assert not score.right(ran_out, "not_found") and score.right(said, "not_found")
    assert score.right({"found": False, "status": "not_found", "steps": []}, "not_found")  # nothing matched: no model was needed
    row = score.feature_row("library", [_case("library", ran_out, expect="not_found")])
    assert row["goal"] == "FAIL" and row["not_found_right"] == "0/1"


def test_an_answer_without_a_verified_quote_fails_every_quote_verifies():
    naked = {"found": True, "status": "unverified", "answer": "x", "citations": []}
    for f in ("ask", "library"):
        row = score.feature_row(f, [_case(f, naked, expect="found")])
        assert row["goal"] == "FAIL" and row["unquoted"] == 1 and "not all verified" in row["check"], f


def test_a_question_over_two_texts_must_cite_both():
    one = {"found": True, "status": "verified", "steps": [{"action": "answer"}], "citations": [{"verified": True, "document_id": "a"}, {"verified": True, "document_id": "a"}]}
    two = {**one, "citations": [{"verified": True, "document_id": "a"}, {"verified": True, "document_id": "b"}]}
    case = _case("library", one, expect="found")
    case["min_docs"] = 2
    assert score.feature_row("library", [case])["goal"] == "FAIL"
    case["payload"] = two
    assert score.feature_row("library", [case])["goal"] == "pass"


def _log_tokens(home, provider, n):
    import sqlite3

    from readhold.ai import log as ai_log

    conn = sqlite3.connect(home / "data" / "readhold.db")
    now = ai_log._iso(__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    conn.execute("INSERT INTO ai_log (id, task, provider, tokens_in, tokens_out, device_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                 (os.urandom(16).hex(), "ask", provider, n, 0, "d", now, now))
    conn.commit()
    conn.close()


def test_the_day_s_budget_goes_on_from_what_the_app_used_today(real_home, monkeypatch):
    _log_tokens(real_home, "anthropic", 150_000)
    assert harness.tokens_today(real_home, "anthropic") == 150_000 and harness.tokens_today(real_home, "local") == 0
    seen = {}
    monkeypatch.setattr(harness, "read_settings", lambda h: {"ai_mode": "cloud", "ai_cloud_provider": "anthropic", "ai_budget_cloud": 200_000})

    def stop(chosen, stand_in):
        seen.update(chosen)
        raise harness.CaseFailed("stop here")

    monkeypatch.setattr(harness, "_open_app", stop)
    harness.run(allow_cloud=True)
    assert seen["ai_budget_cloud"] == 50_000  # what is left of today's, not a second budget
    _log_tokens(real_home, "anthropic", 60_000)
    seen.clear()
    got = harness.run(allow_cloud=True)
    assert got["status"] == "budget" and "used up" in got["message"] and not seen  # nothing was opened or sent


def test_a_crash_while_setting_up_is_a_sentence_not_a_traceback(home, monkeypatch):
    def boom(ctx):
        raise KeyError("router")

    monkeypatch.setattr(harness, "_setup", boom)
    got = harness.run(stand_in=True)
    assert got["status"] == "error" and "could not be set up" in got["message"]
    assert os.environ["READHOLD_HOME"] == str(home)


def test_the_real_settings_path_leaves_the_real_folder_alone(real_home, monkeypatch):
    """With your own settings (a local model, a profile change): the model is answered by the stand-in through a
    mock transport, and the real folder is the same afterwards, byte for byte."""
    before = _snapshot(real_home)
    used = {}

    def server(request):
        body = json.loads(request.content)
        used["model"] = body["model"]
        if body["model"] and "temperature" in body.get("options", {}):
            used.setdefault("temps", set()).add(body["options"]["temperature"])
        return httpx.Response(200, json=standin.answer(body))

    monkeypatch.setattr(harness, "_transport_for_tests", httpx.MockTransport(server))
    got = harness.run(only={"ask"})
    assert got["status"] == "done" and got["rows"][0]["goal"] == "pass"
    assert used["model"] == "my-model" and 0.1 in used["temps"]  # your model, and your profile change for ask
    assert _snapshot(real_home) == before


def test_settings_are_read_while_the_app_is_open(real_home):
    """The app holds the database open (WAL mode): the newest setting is read, and no data file changes."""
    from readhold.db import open_db

    db = open_db()
    try:
        db.execute("UPDATE settings SET value=? WHERE key='ai_local_model'", (json.dumps("newer-model"),))
        data = {k: v for k, v in _snapshot(real_home).items() if not k.endswith("-shm")}
        assert harness.read_settings(real_home)["ai_local_model"] == "newer-model"
        assert {k: v for k, v in _snapshot(real_home).items() if not k.endswith("-shm")} == data
    finally:
        db.conn.close()


def test_the_note_chat_counts_requests_that_got_a_usable_proposal():
    rewrite = {"action": "replace", "text": "# Trip", "new_words": ["trip", "plan"], "restored": ["#field-work"]}
    story = {"action": "add", "text": "## Story idea", "new_words": [], "restored": []}
    only_reply = {"action": "none", "text": "", "new_words": [], "restored": []}
    assert score.notechat_check(rewrite) == {"proposal": 1, "rewrite": 1, "new_words": 2, "restored": 1}
    assert score.notechat_check(story) == {"proposal": 1, "rewrite": 0, "new_words": 0, "restored": 0}
    assert score.notechat_check(only_reply)["proposal"] == 0 and score.notechat_check(None)["proposal"] == 0
    row = score.feature_row("notechat", [_case("notechat", rewrite), _case("notechat", story)])
    assert row["goal"] == "pass" and row["check"] == "proposals 2/2, rewrite +2, 1 restored" and score._cells(row)[2] == "-"
    assert score.feature_row("notechat", [_case("notechat", story), _case("notechat", only_reply)])["goal"] == "FAIL"


def test_the_stand_in_run_checks_the_note_chat(stand_in_run):
    row = {r["feature"]: r for r in stand_in_run["rows"]}["notechat"]
    assert row["goal"] == "pass" and row["proposals"] == 2 and row["rewrites"] == 1 and row["restored"] == 0
    got = {c["name"]: c["payload"] for c in stand_in_run["cases"] if c["feature"] == "notechat"}
    assert got["format the note"]["action"] == "replace" and "[[Soil sensor log]]" in got["format the note"]["text"]
    assert got["a story idea from it"]["action"] == "add"

