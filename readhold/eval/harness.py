"""The evaluation harness: run every AI feature over the fixed sample set and print one table of scores.

    uv run python -m readhold.eval              the model in your Settings (local, or cloud with --yes)
    uv run python -m readhold.eval --stand-in   a fake model in-process: checks the harness itself (CI)

How it keeps your data out of it: it reads only the AI settings and the profile changes of your data folder
(read-only: nothing of yours is written; see `_query`), and today's token count from its AI log, then opens a fresh, throwaway Readhold folder, imports the sample texts there
and drives the app's own routes in-process (FastAPI's test client: no socket, no port). Every model call goes
through the same `guard.ask` and port as in the app, so the scores are those of the app as it is. The throwaway
folder is deleted at the end (`--keep` leaves it, to look at its `ai_results` and `ai_log`).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from .. import config
from . import samples, score, standin

log = logging.getLogger(__name__)

STAND_IN = {"ai_mode": "local", "ai_local_api": "ollama", "ai_local_endpoint": "http://localhost:11434", "ai_local_model": "stand-in",
            "ai_local_small_model": "", "ai_timeout_s": 60, "ai_budget_local": 0}
COPIED = ("ai_mode", "ai_local_api", "ai_local_endpoint", "ai_local_model", "ai_local_small_model", "ai_cloud_provider", "ai_cloud_model",
          "ai_cloud_small_model", "ai_timeout_s", "ai_budget_local", "ai_budget_cloud", "wpm")
# the most calls one case of each feature makes, without retries: digest a part and the whole, library its steps
# (library.MAX_STEPS), brainstorm three angles and the critic; the others one
CALLS = {"resume": 1, "explain": 1, "digest": 2, "ask": 1, "library": 3, "notes": 1, "plan": 1, "brainstorm": 4, "organize": 1, "tidy": 1, "chat": 1, "notechat": 1}
_transport_for_tests = None  # tests put a mock transport here, to stand for a model server that is down


class CaseFailed(Exception):
    pass


# ------------------------------------------------------------------ what is read from your folder (read-only)
def _query(home: Path, sql: str, params: tuple = ()) -> list | None:
    """Rows of a read-only query on the database of the Readhold folder `home`; None when there is none.

    Nothing of yours is written. With no -wal file (the app is closed) everything is in the main file, and
    "immutable" reads it without creating any file beside it. With a -wal file (the app is open, or it was not
    closed cleanly) the newest values may be only in it, so it is read in plain read-only mode; SQLite may then
    touch its own -shm index file, which holds no data."""
    path = home / "data" / "readhold.db"
    if not path.is_file():
        return None
    live = path.with_name(path.name + "-wal").exists()
    for mode in (("mode=ro",) if live else ()) + ("immutable=1",):
        try:
            conn = sqlite3.connect(f"{path.as_uri()}?{mode}", uri=True)
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    return None


def read_settings(home: Path) -> dict:
    """The AI settings (and reading speed) of the Readhold folder `home`, read-only (`_query`).
    A value that fails its check is left out. A folder without a database gives {} (and is not created)."""
    from ..ai import settings as ai_settings

    rows = _query(home, "SELECT key, value FROM settings")
    out = {}
    for key, value in rows or []:
        if key not in COPIED:
            continue
        try:
            v = json.loads(value)
            out[key] = ai_settings.check(key, v) if key in ai_settings.CHECKS else v
        except (TypeError, ValueError):
            continue
    if "wpm" in out and not (isinstance(out["wpm"], int) and 50 <= out["wpm"] <= 2000):
        del out["wpm"]
    return out


def tokens_today(home: Path, provider: str) -> int:
    """Tokens already used today with this provider in the app (its AI log, read-only), so the evaluation spends
    only what is left of the day's budget, not a second one."""
    from ..ai import log as ai_log

    rows = _query(home, "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) FROM ai_log WHERE provider=? AND created_at>=?", (provider, ai_log._today_start()))
    return int(rows[0][0]) if rows else 0


def read_profiles(home: Path) -> dict:
    """Your changes to the model profiles (`data/ai_profiles.json`), checked; {} when there are none."""
    from ..ai import profiles

    f = home / "data" / "ai_profiles.json"
    if not f.is_file():
        return {}
    try:
        return profiles.check(json.loads(f.read_text("utf-8")))
    except (OSError, ValueError):
        return {}


def describe(s: dict, stand_in: bool) -> str:
    if stand_in:
        return "stand-in model (checks the harness, not a model)"
    if s.get("ai_mode") == "cloud":
        from ..ai.port import Port

        return f"cloud {s.get('ai_cloud_provider', 'anthropic')}: {Port._model(s, 'cloud', 'strong') or '?'} (small: {Port._model(s, 'cloud', 'small') or '?'})"
    small = s.get("ai_local_small_model") or ""
    return f"local {s.get('ai_local_api', 'ollama')} at {s.get('ai_local_endpoint', '')}: {s.get('ai_local_model') or '?'}" + (f" (small: {small})" if small else "")


# ------------------------------------------------------------------ the throwaway app
class Ctx:
    def __init__(self, client, db, wait_s: float):
        self.client, self.db, self.wait_s = client, db, wait_s
        self.ids: dict[str, str] = {}
        self.ords: dict[str, dict[str, int]] = {}  # doc -> sentence text -> ord
        self.sections: dict[str, dict[str, dict]] = {}  # doc -> title -> {"id", "ords"}
        self.own: dict[str, str] = {}  # your own writing (`_yours`): "note" and "routine" -> id
        self.own_made = False

    def post(self, url: str, body: dict) -> dict:
        r = self.client.post(url, json=body)
        if r.status_code != 200:
            raise CaseFailed(_detail(r))
        return r.json()

    def stored(self, payload: dict | None) -> dict | None:
        """The result as the feature stored it in `ai_results`; what the route said when nothing was stored."""
        from ..ai import results

        if payload and payload.get("id"):
            row = self.db.one("SELECT * FROM ai_results WHERE id=?", (payload["id"],))
            if row and (shaped := results.shape(row)):
                return shaped
        return payload


def _detail(r) -> str:
    try:
        d = r.json().get("detail")
    except ValueError:
        d = None
    return f"{d if isinstance(d, str) else r.text[:200]} (HTTP {r.status_code})"


def _open_app(chosen: dict, stand_in: bool):
    """A Readhold app on the throwaway folder (READHOLD_HOME is already set to it), with the model settings applied."""
    from fastapi.testclient import TestClient

    from ..db import open_db
    from ..server import create_app

    db = open_db()
    token = secrets.token_urlsafe(16)
    app = create_app(db, token, {"testserver"})
    client = TestClient(app, raise_server_exceptions=False)  # a server error is a 500 the case reports, not a traceback
    client.get(f"/auth?token={token}", follow_redirects=False)
    if stand_in:
        app.state.ai.use_stand_in(standin.answer)
    elif _transport_for_tests is not None:
        app.state.ai.transport, app.state.ai.retry_wait = _transport_for_tests, 0
    r = client.put("/api/settings", json=chosen)
    if r.status_code != 200:
        db.conn.close()
        raise CaseFailed(f"The settings were refused: {_detail(r)}")
    return db, client


def _setup(ctx: Ctx) -> None:
    """Import the sample texts, and put the sample tags and highlights on them."""
    for name, text in samples.DOCS.items():
        doc = ctx.post("/api/import/text", {"title": "", "text": text, "format": "markdown"})
        ctx.ids[name] = doc["id"]
        full = ctx.client.get(f"/api/documents/{doc['id']}").json()
        ctx.ords[name] = {s["text"]: s["ord"] for sec in full["sections"] for p in sec["paragraphs"] for s in p["sentences"]}
        ctx.sections[name] = {sec["title"]: {"id": sec["id"], "ords": [s["ord"] for p in sec["paragraphs"] for s in p["sentences"]]}
                              for sec in full["sections"]}
    for name, tags in samples.TAGS.items():
        r = ctx.client.put(f"/api/documents/{ctx.ids[name]}/tags", json={"tags": tags})
        if r.status_code != 200:
            raise CaseFailed(f"tags: {_detail(r)}")
    for name, sentence in samples.HIGHLIGHTS:
        o = ctx.ords[name][sentence]
        ctx.post("/api/highlights", {"document_id": ctx.ids[name], "sentence": o, "end_sentence": o, "type": "claim"})


# ------------------------------------------------------------------ one case of each feature
def _resume(ctx: Ctx, case: dict):
    d, ords = ctx.ids[case["doc"]], ctx.sections[case["doc"]][case["read"]]["ords"]
    ctx.post(f"/api/documents/{d}/position", {"position": ords[0]})
    s = ctx.post("/api/sessions", {"document_id": d})
    ctx.post(f"/api/documents/{d}/read", {"ords": ords})
    ctx.post(f"/api/documents/{d}/position", {"position": ords[-1]})
    r = ctx.client.patch(f"/api/sessions/{s['id']}", json={"focused_ms": 120_000, "ended": True})
    if r.status_code != 200:
        raise CaseFailed(_detail(r))
    return ctx.post(f"/api/documents/{d}/resume/brief", {"fresh": True})["brief"], None


def _explain(ctx: Ctx, case: dict):
    o = ctx.ords[case["doc"]][case["sentence"]]
    return ctx.post(f"/api/documents/{ctx.ids[case['doc']]}/explain", {"sentence": o, "end_sentence": o, "level": case["level"], "fresh": True})["result"], None


def _digest(ctx: Ctx, case: dict):
    d = ctx.ids[case["doc"]]
    ctx.post(f"/api/documents/{d}/digest", {"fresh": True})
    end = time.monotonic() + ctx.wait_s
    while time.monotonic() < end:
        got = ctx.client.get(f"/api/documents/{d}/digest").json()
        job = got.get("job") or {}
        if job.get("state") in ("done", "failed", "cancelled"):
            if job["state"] != "done" or not got.get("digest"):
                raise CaseFailed(job.get("message") or f"the digest {job['state']}")
            return got["digest"], None
        time.sleep(0.05)
    ctx.client.post(f"/api/documents/{d}/digest/cancel", json={})
    _settle(30.0)  # its cancelled call is logged before the next case starts counting
    raise CaseFailed(f"the digest did not finish within {round(ctx.wait_s)} s")


def _settle(most: float) -> None:
    """Wait (at most `most` seconds) until no digest job is running."""
    from ..ai import digest

    end = time.monotonic() + most
    while time.monotonic() < end and any(j.state == "running" for j in list(digest._jobs.values())):
        time.sleep(0.05)


def _ask(ctx: Ctx, case: dict):
    return ctx.post(f"/api/documents/{ctx.ids[case['doc']]}/ask", {"question": case["question"], "fresh": True})["result"], None


def _library(ctx: Ctx, case: dict):
    return ctx.post("/api/library/ask", {"question": case["question"], "fresh": True})["result"], None


def _notes(ctx: Ctx, case: dict):
    body = {"source": case["source"], "kind": case["kind"], "fresh": True}
    if case["source"] == "section":
        body["section_id"] = ctx.sections[case["doc"]][case["section"]]["id"]
    return ctx.post(f"/api/documents/{ctx.ids[case['doc']]}/study-notes", body)["result"], None


def _plan(ctx: Ctx, case: dict):
    """The model's order and levels, then the day-by-day plan code makes from them (the preview the page shows)."""
    got = ctx.post("/api/reading-plan/suggest", {"document_ids": [ctx.ids[d] for d in case["docs"]], "fresh": True})["result"]
    deadline = (dt.date.today() + dt.timedelta(days=case["days"])).isoformat()
    preview = ctx.post("/api/reading-plan/preview", {"documents": [{"id": o["document_id"], "level": o["level"]} for o in got["order"]],
                                                    "deadline": deadline, "minutes_per_day": case["minutes"]})
    return got, {"plan": score.plan_check(preview), "preview": preview}


def _brainstorm(ctx: Ctx, case: dict):
    return ctx.post("/api/brainstorm", {"kind": "document", "id": ctx.ids[case["doc"]], "fresh": True})["result"], None


def _organize(ctx: Ctx, case: dict):
    return ctx.post(f"/api/documents/{ctx.ids[case['doc']]}/organize/suggest", {"fresh": True})["result"], None


def _yours(ctx: Ctx) -> dict[str, str]:
    """The writing that stands for your own (samples.TASKS, NOTE, ROUTINE), made through the app's routes the first
    time a Tidy or Plan chat case needs it. Not in `_setup`: those cases come last, so the note is never among what
    Ask my library searches and the scores of the reading features stay those of the sample texts alone. Made once
    even if a step fails (a case that then misses it fails, and says so)."""
    if not ctx.own_made:
        ctx.own_made = True
        today = dt.date.today()
        for t in samples.TASKS:
            due = None if t["in_days"] is None else (today + dt.timedelta(days=t["in_days"])).isoformat()
            ctx.post("/api/todos", {"text": t["text"], "minutes": t["minutes"], "due": due})
        ctx.own["note"] = ctx.post("/api/pages", {"title": samples.NOTE["title"], "body": samples.NOTE["body"]})["id"]
        ctx.own["routine"] = ctx.post("/api/routines", {"title": samples.ROUTINE["title"], "steps": samples.ROUTINE["steps"]})["id"]
    return ctx.own


def _tidy(ctx: Ctx, case: dict):
    """A proposed rewrite of your open tasks, your note or your routine (nothing is applied)."""
    own = _yours(ctx)
    body = {"kind": case["kind"], "fresh": True}
    if case["kind"] != "tasks":
        if case["kind"] not in own:
            raise CaseFailed(f"your sample {case['kind']} could not be made")
        body["id"] = own[case["kind"]]
    return ctx.post("/api/tidy/suggest", body)["result"], None


def _notechat(ctx: Ctx, case: dict):
    """What the model proposes for your sample note, from a conversation (nothing is changed)."""
    own = _yours(ctx)
    if "note" not in own:
        raise CaseFailed("your sample note could not be made")
    return ctx.post(f"/api/notes/{own['note']}/chat", {"messages": case["messages"]})["result"], None


def _chat(ctx: Ctx, case: dict):
    """Drafts from a conversation, around your open tasks and the minutes a day (nothing is added)."""
    _yours(ctx)
    return ctx.post("/api/plan/chat", {"messages": case["messages"], "minutes_a_day": case["minutes"]})["result"], None


RUNNERS: dict[str, Callable] = {"resume": _resume, "explain": _explain, "digest": _digest, "ask": _ask, "library": _library, "notes": _notes,
                                "plan": _plan, "brainstorm": _brainstorm, "organize": _organize, "tidy": _tidy, "chat": _chat,
                                "notechat": _notechat}
LOG_COLUMNS = "task, latency_ms, tokens_in, tokens_out, attempts, checks, outcome, error"


def _run_case(ctx: Ctx, case: dict) -> dict:
    mark = ctx.db.scalar("SELECT COALESCE(MAX(rowid), 0) FROM ai_log")
    started = time.monotonic()
    out = {"feature": case["feature"], "name": case["name"], "expect": case.get("expect", ""), "min_docs": case.get("min_docs", 0), "ok": False, "error": "", "payload": None, "plan": None}
    try:
        payload, extra = RUNNERS[case["feature"]](ctx, case)
        out.update(ok=True, payload=ctx.stored(payload), **(extra or {}))
    except CaseFailed as e:
        out["error"] = str(e)
    except Exception as e:  # noqa: BLE001  (one broken case must not hide the scores of the others)
        log.exception("eval case %s failed", case["name"])
        out["error"] = f"{type(e).__name__}: {e}"[:300]
    out["seconds"] = round(time.monotonic() - started, 2)
    out["log"] = ctx.db.all(f"SELECT {LOG_COLUMNS} FROM ai_log WHERE rowid>? ORDER BY rowid", (mark,))
    return out


# ------------------------------------------------------------------ the run
def run(*, stand_in: bool = False, model: str = "", allow_cloud: bool = False, only: set[str] | None = None, keep: bool = False,
        progress: Callable[[str], None] | None = None) -> dict:
    """Run the cases and score them. Returns {"status", "message", "model", "rows", "cases", ...}; status is
    "done", or "off" / "cloud" / "no_model" / "error" with a message saying why nothing was scored."""
    from ..ai import settings as ai_settings

    say = progress or (lambda _: None)
    real = config.home()
    chosen = dict(STAND_IN) if stand_in else read_settings(real)
    cases = [c for c in samples.CASES if not only or c["feature"] in only]
    report = {"status": "", "message": "", "model": describe(chosen, stand_in), "samples": samples.VERSION, "rows": [], "cases": [],
              "started": dt.datetime.now().isoformat(timespec="seconds")}
    mode = chosen.get("ai_mode", "off")
    if model and not stand_in and mode in ("local", "cloud"):
        try:
            name = ai_settings.check(f"ai_{mode}_model", model)
        except ValueError as e:
            return {**report, "status": "error", "message": f"--model: {e}"}
        chosen.update({f"ai_{mode}_model": name, f"ai_{mode}_small_model": ""})  # every task uses that one model
        report["model"] = describe(chosen, False)
    if mode not in ("local", "cloud"):
        return {**report, "status": "off", "message": (
            "AI is off in your Settings, so there is no model to evaluate. Choose a model and switch AI on in Settings,\n"
            "or check the harness itself on the stand-in model:  uv run python -m readhold.eval --stand-in")}
    from ..ai import where

    if where.leaves_computer(chosen) and not allow_cloud:  # a cloud model, or a model server on another computer
        n = sum(CALLS[c["feature"]] for c in cases)
        return {**report, "status": "cloud", "message": (
            f"Your Settings use a {'cloud model' if mode == 'cloud' else 'model server on another computer'} ({report['model']}).\n"
            f"The evaluation sends its own sample texts (none of yours) to it with your API key: about {n} calls, and tokens on your bill.\n"
            "It counts against today's token budget in your Settings, like any call. Run it again with --yes to go ahead.")}
    if not stand_in:  # the day's budget goes on from what the app already used today, not from zero
        provider = "local" if mode == "local" else chosen.get("ai_cloud_provider", "anthropic")
        key = "ai_budget_local" if mode == "local" else "ai_budget_cloud"
        budget = int(chosen.get(key, ai_settings.DEFAULTS[key]) or 0)
        if budget:
            left = budget - tokens_today(real, provider)
            if left <= 0:
                return {**report, "status": "budget", "message": "Today's token budget for this provider is used up, so nothing was sent. It starts again tomorrow; you can also raise it in Settings."}
            chosen[key] = left
    overrides = {} if stand_in else read_profiles(real)
    throwaway = Path(tempfile.mkdtemp(prefix="readhold-eval-"))
    old = os.environ.get("READHOLD_HOME")
    os.environ["READHOLD_HOME"] = str(throwaway)
    db = None
    try:
        if overrides:
            (config.data_dir() / "ai_profiles.json").write_text(json.dumps(overrides), "utf-8")
        try:
            db, client = _open_app(chosen, stand_in)
            r = client.post("/api/ai/test", json={})
            test = r.json() if r.status_code == 200 else {"ok": False, "message": _detail(r)}
        except CaseFailed as e:
            return {**report, "status": "error", "message": str(e)}
        except Exception as e:  # noqa: BLE001  (said in a sentence, never a traceback)
            log.exception("eval: the throwaway app could not start")
            return {**report, "status": "error", "message": f"The evaluation could not start: {type(e).__name__}: {e}"[:400]}
        if not test.get("ok"):
            return {**report, "status": "no_model", "message": f"The model could not be reached with Test connection: {test.get('message', '')}\n"
                                                               f"Model: {report['model']}. Nothing was scored."}
        timeout = float(chosen.get("ai_timeout_s") or 60)
        ctx = Ctx(client, db, wait_s=max(60.0, 6 * timeout))
        try:
            _setup(ctx)
        except Exception as e:  # noqa: BLE001
            return {**report, "status": "error", "message": f"The sample texts could not be set up: {e}"[:400]}
        for k, case in enumerate(cases, 1):
            say(f"[{k:>2}/{len(cases)}] {case['feature']:<10} {case['name']} ...")
            got = _run_case(ctx, case)
            say(f"        {'ok' if got['ok'] else 'FAILED: ' + got['error']} ({got['seconds']:.1f} s, {len(got['log'])} call{'s' if len(got['log']) != 1 else ''})")
            report["cases"].append(got)
        features = [f for f in score.FEATURES if not only or f in only]
        report["rows"] = [score.feature_row(f, [c for c in report["cases"] if c["feature"] == f]) for f in features]
        report["status"] = "done"
        if keep:
            report["kept"] = str(throwaway)
        return report
    finally:
        from ..ai import digest

        digest.stop()
        _settle(10.0)  # a digest that is still running writes its last rows before the database closes
        if db is not None:
            db.conn.close()
        if old is None:
            os.environ.pop("READHOLD_HOME", None)
        else:
            os.environ["READHOLD_HOME"] = old
        if not keep:
            shutil.rmtree(throwaway, ignore_errors=True)
            if throwaway.exists():  # Windows may still hold a file of it
                say(f"(The throwaway folder could not be removed completely: {throwaway})")


# ------------------------------------------------------------------ the command
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m readhold.eval", description="Run every AI feature over a fixed set of sample texts and print scores.")
    ap.add_argument("--stand-in", action="store_true", help="use a fake model in-process (checks the harness, not a model; nothing connects)")
    ap.add_argument("--model", default="", help="try this model instead of the one in Settings (same server or provider; used for every task)")
    ap.add_argument("--yes", action="store_true", help="allow a cloud model: the sample texts (none of yours) are sent with your API key")
    ap.add_argument("--only", default="", help=f"comma-separated features to run: {', '.join(score.FEATURES)}")
    ap.add_argument("--json", default="", metavar="FILE", help="also write every case, result and score to this file")
    ap.add_argument("--keep", action="store_true", help="keep the throwaway Readhold folder and print where it is")
    args = ap.parse_args(argv)
    only = {f.strip() for f in args.only.split(",") if f.strip()}
    if only - set(score.FEATURES):
        ap.error(f"unknown feature: {', '.join(sorted(only - set(score.FEATURES)))}")

    if not logging.getLogger().handlers:  # the app's warnings go to the screen, short, with secrets removed
        from ..redact import RedactingFormatter

        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(RedactingFormatter("  (%(levelname)s %(name)s: %(message)s)"))
        h.setLevel(logging.ERROR)
        logging.getLogger().addHandler(h)

    def progress(line: str) -> None:
        enc = getattr(sys.stderr, "encoding", None) or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"), file=sys.stderr, flush=True)

    def show(text: str) -> None:  # any console, any code page: what it cannot print becomes "?"
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, "replace").decode(enc, "replace"))

    report = run(stand_in=args.stand_in, model=args.model, allow_cloud=args.yes, only=only or None, keep=args.keep, progress=progress)
    if report["status"] != "done":
        show(report["message"])
        return 0
    n = len(report["cases"])
    header = f"Readhold evaluation | {report['model']} | samples v{report['samples']}, {n} case{'s' if n != 1 else ''} | {report['started'].replace('T', ' ')}"
    show(score.render(report["rows"], header))
    print(score.LEGEND)
    problems = [c for c in report["cases"] if not c["ok"]]
    if problems:
        print("\nProblems:")
        for c in problems:
            show(f"  {c['feature']} - {c['name']}: {c['error']}")
    if report.get("kept"):
        show(f"\nThe throwaway Readhold folder was kept: {report['kept']}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), "utf-8")
        show(f"\nEvery case and result: {args.json}")
    return 0
