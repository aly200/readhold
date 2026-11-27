"""Scores, computed in code from what each feature stored (`ai_results`) and from the AI log (`ai_log`).

Nothing here calls a model or judges wording: it counts. What a person has to judge (is an explanation clear, does
an outline match the paper) is left to the person, and those features show no goal.
"""
from __future__ import annotations

import json
import statistics

FEATURES = ("resume", "explain", "digest", "ask", "library", "notes", "plan", "brainstorm", "organize", "tidy", "chat", "notechat")
NO_QUOTES = ("tidy", "chat", "notechat")  # they rework your own words and show no quote (tests/test_ai_citations.py, NO_QUOTES)
MAX_STEPS = 3  # the Ask my library loop's cap (library.MAX_STEPS); a run past it fails its goal
VARIETY_GOAL = 0.5  # brainstorm: ideas share less than half their words, on average
REUSE_GOAL = 0.5  # organize: more than half of the model's tags are ones you already use ("most of the time")
NEW_WORDS_GOAL = 0.5  # tidy: more than half of its proposals add no word you did not write ("most")
LISTS = {"resume": "recap", "digest": "key_ideas", "ask": "citations", "library": "citations", "notes": "items", "brainstorm": "ideas", "organize": "tags"}


# ------------------------------------------------------------------ one result
def quotes(feature: str, payload: dict | None) -> tuple[int, int]:
    """(verified, shown): the quotes a result showed, and how many of them were checked against the source.
    Brainstorm and organize count ideas and tags, each verified when it rests on a checked quote. Tidy, Plan
    chat and the note chat show none: (0, 0), and the table says "-"."""
    if not payload or feature in NO_QUOTES:
        return 0, 0
    if feature == "explain":
        return int(payload.get("status") == "verified"), 1
    if feature == "plan":
        reasons = [o for o in payload.get("order") or [] if o.get("placed") and o.get("reason")]
        return sum(1 for o in reasons if o.get("verified")), len(reasons)
    items = payload.get(LISTS[feature]) or []
    if feature in ("ask", "library") and not payload.get("found"):
        items = []
    return sum(1 for x in items if x.get("verified")), len(items)


def right(payload: dict | None, expect: str) -> bool:
    """Did Ask say "found" when the texts answer the question, and "not found" when they do not?
    An answer labelled unverified still counts as an answer. For Ask my library, "not found" counts only when the
    model said so in an answer step: a loop that ran out of steps without answering is stored as not found too,
    but the model never said it."""
    if not payload:
        return False
    missing = payload.get("status") == "not_found" or not payload.get("found")
    if expect != "not_found":
        return not missing
    taken = payload.get("steps")
    if taken and taken[-1].get("action") != "answer":
        return False
    return missing


def documents_cited(payload: dict | None) -> int:
    """How many different documents an answer's verified quotes come from."""
    return len({c.get("document_id") for c in (payload or {}).get("citations") or [] if c.get("verified") and c.get("document_id")})


def bare(payload: dict | None) -> bool:
    """An answer shown with no verified quote at all (labelled unverified): it fails "every quote verifies"."""
    return bool(payload) and bool(payload.get("found")) and payload.get("status") != "verified"


def steps(payload: dict | None) -> int:
    return len((payload or {}).get("steps") or [])


def plan_check(preview: dict | None) -> dict:
    """The reading plan's promise, checked on the day-by-day plan code made from the model's order and levels:
    no day holds more than the minutes a day (with what was already planned), no reading lies past the deadline,
    and every minute is either on a day or shown as not fitting."""
    if not preview:
        return {"within": False, "over_days": 0, "late_days": 0, "lost_minutes": 0, "fits": False}
    per_day, deadline = preview["per_day"], preview["deadline"]
    days = preview.get("days") or []
    over = sum(1 for d in days if sum(i["minutes"] for i in d["items"]) + d.get("busy", 0) > per_day)
    late = sum(1 for d in days if d["items"] and d["day"] > deadline)
    placed = sum(i["minutes"] for d in days for i in d["items"])
    lost = max(0, preview.get("total", 0) - placed - sum(u["minutes"] for u in preview.get("unplaced") or []))
    return {"within": not over and not late and not lost, "over_days": over, "late_days": late, "lost_minutes": lost, "fits": bool(preview.get("fits"))}


def tidy_check(payload: dict | None) -> dict:
    """Tidy's "no invented facts", from the words code found in a rewrite that are not in what you wrote
    (`new_words`). Each proposal counts once: every task it rewrites, the note, the routine; an empty rewrite
    proposes nothing. `clean`: proposals that add no word. For the note also how many words it added, and how many
    of your own links, tags and properties it dropped (`restored`: code put them back)."""
    out = {"proposals": 0, "clean": 0, "note_new_words": None, "restored": 0}
    if not payload:
        return out
    kind = payload.get("kind")
    if kind == "tasks":
        items = payload.get("items") or []
        return {**out, "proposals": len(items), "clean": sum(1 for i in items if not i.get("new_words"))}
    proposed = bool(payload.get("body") if kind == "note" else payload.get("steps"))
    new = len(payload.get("new_words") or [])
    out.update(proposals=int(proposed), clean=int(proposed and not new))
    if kind == "note" and proposed:
        out.update(note_new_words=new, restored=len(payload.get("restored") or []))
    return out


def notechat_check(payload: dict | None) -> dict:
    """The note chat's "a usable proposal": a rewrite of the note or text to add (`action` "replace" or "add"), not
    only a reply. For a rewrite also the words it added (`new_words`) and the links or tags of yours it dropped that
    code put back (`restored`); new writing (add) is expected to have new words, so they are not counted."""
    p = payload or {}
    action = p.get("action")
    rewrite = action == "replace"
    return {"proposal": int(action in ("replace", "add")), "rewrite": int(rewrite),
            "new_words": len(p.get("new_words") or []) if rewrite else 0, "restored": len(p.get("restored") or []) if rewrite else 0}


def chat_check(payload: dict | None) -> dict:
    """Plan chat's "drafts fit", from the checks code put on each draft: `fit` counts the drafts that fit their
    day's free time (`fits`) with nothing flagged (`flags`: no usable day or minutes, or over the free time). A
    draft for any day (no `due`, nothing flagged) fits too: the chat may leave the day open, and it loads no day. Also the drafts code left out: past the most a reply may hold (`dropped`), or tasks you already
    have (`already`)."""
    p = payload or {}
    drafts = p.get("drafts") or []
    return {"drafts": len(drafts), "fit": sum(1 for d in drafts if d.get("fits") and not d.get("flags")),
            "dropped": int(p.get("dropped") or 0), "already": int(p.get("already") or 0)}


# ------------------------------------------------------------------ the calls, from ai_log
def _checks(row: dict) -> dict:
    try:
        got = json.loads(row.get("checks") or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def calls(rows: list[dict]) -> dict:
    """Calls, schema failures (answers that did not fit the schema, retried or not), retries, failed calls,
    latency and tokens, from the AI log rows of a feature's runs."""
    lat = [r["latency_ms"] for r in rows]
    return {
        "calls": len(rows),
        "schema_failures": sum(int(_checks(r).get("schema_failures") or 0) for r in rows),
        "retries": sum(max(0, (r.get("attempts") or 1) - 1) for r in rows),
        "failed": sum(1 for r in rows if r.get("outcome") != "ok"),
        "latency_median": round(statistics.median(lat)) if lat else None,
        "latency_max": max(lat) if lat else None,
        "tokens_in": sum(r.get("tokens_in") or 0 for r in rows),
        "tokens_out": sum(r.get("tokens_out") or 0 for r in rows),
    }


# ------------------------------------------------------------------ one feature, all its cases
def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def feature_row(feature: str, cases: list[dict]) -> dict:
    """One line of the table. `cases`: what the harness recorded for each run of this feature."""
    done = [c for c in cases if c["ok"]]
    verified = shown = 0
    for c in done:
        v, n = quotes(feature, c["payload"])
        verified, shown = verified + v, shown + n
    row = {"feature": feature, "cases": len(cases), "ran": f"{len(done)}/{len(cases)}", "verified": verified, "quotes": shown,
           "rate": round(verified / shown, 3) if shown else None, "check": "", "goal": "-",
           **calls([r for c in cases for r in c["log"]])}
    if not cases:
        row["goal"] = "n/a"
        return row
    every = len(done) == len(cases)
    all_quotes = verified == shown
    if feature in ("ask", "library"):
        found = [c for c in cases if c.get("expect") == "found"]
        missing = [c for c in cases if c.get("expect") == "not_found"]
        f_ok = sum(1 for c in found if c["ok"] and right(c["payload"], "found"))
        m_ok = sum(1 for c in missing if c["ok"] and right(c["payload"], "not_found"))
        unquoted = sum(1 for c in done if bare(c["payload"]))  # an answer without a checked quote for every citation
        few = sum(1 for c in found if c["ok"] and c.get("min_docs") and documents_cited(c["payload"]) < c["min_docs"])
        row.update(found_right=f"{f_ok}/{len(found)}", not_found_right=f"{m_ok}/{len(missing)}", unquoted=unquoted, too_few_documents=few)
        row["check"] = f"found {f_ok}/{len(found)}, not found {m_ok}/{len(missing)}"
        if unquoted:
            row["check"] += f", {unquoted} not all verified"
        if few:
            row["check"] += f", {few} cite too few texts"
        good = every and f_ok == len(found) and m_ok == len(missing) and all_quotes and not unquoted and not few
        if feature == "library":
            most = max((steps(c["payload"]) for c in done), default=0)
            row["max_steps"] = most
            row["check"] += f", {most} step{'s' if most != 1 else ''}"
            good = good and most <= MAX_STEPS
        row["goal"] = "pass" if good else "FAIL"
    elif feature == "plan":
        checks = [c.get("plan") or plan_check(None) for c in cases]
        ok = sum(1 for p in checks if p["within"])
        row.update(within=f"{ok}/{len(cases)}", fits=f"{sum(1 for p in checks if p['fits'])}/{len(cases)}")
        row["check"] = f"within time and deadline {ok}/{len(cases)}"
        row["goal"] = "pass" if every and ok == len(cases) else "FAIL"
    elif feature == "brainstorm":
        v = _mean([c["payload"]["variety"] for c in done if c["payload"].get("variety") is not None])
        row["variety"] = v
        row["check"] = f"variety {v:.2f}" if v is not None else "variety -"
        row["goal"] = "pass" if every and v is not None and v >= VARIETY_GOAL and shown and all_quotes else "FAIL"
    elif feature == "organize":
        v = _mean([c["payload"]["model_reuse"] for c in done if c["payload"].get("model_reuse") is not None])
        row["model_reuse"] = v
        row["check"] = f"model_reuse {v:.2f}" if v is not None else "model_reuse -"
        row["goal"] = "pass" if every and v is not None and v > REUSE_GOAL else "FAIL"
    elif feature == "tidy":
        checks = [tidy_check(c["payload"]) for c in done]
        n, clean = sum(p["proposals"] for p in checks), sum(p["clean"] for p in checks)
        notes = [p["note_new_words"] for p in checks if p["note_new_words"] is not None]
        restored = sum(p["restored"] for p in checks)
        row.update(proposals=n, no_new_words=clean, no_new_words_share=round(clean / n, 2) if n else None,
                   note_new_words=sum(notes) if notes else None, restored=restored)
        row["check"] = f"no new words {clean}/{n}" + (f", note +{sum(notes)}" if notes else "") + (f", {restored} restored" if restored else "")
        row["goal"] = "pass" if every and n and clean / n > NEW_WORDS_GOAL else "FAIL"  # nothing proposed: nothing to judge
    elif feature == "chat":
        checks = [chat_check(c["payload"]) for c in done]
        n, fit = sum(p["drafts"] for p in checks), sum(p["fit"] for p in checks)
        dropped, already = sum(p["dropped"] for p in checks), sum(p["already"] for p in checks)
        row.update(drafts=n, fit=fit, dropped=dropped, already=already)
        row["check"] = f"fits {fit}/{n}, {dropped} dropped, {already} already planned"
        row["goal"] = "pass" if every and n and fit == n else "FAIL"  # no draft at all: nothing was checked
    elif feature == "notechat":
        checks = [notechat_check(c["payload"]) for c in done]
        n, rewrites = sum(p["proposal"] for p in checks), sum(p["rewrite"] for p in checks)
        added, restored = sum(p["new_words"] for p in checks), sum(p["restored"] for p in checks)
        row.update(proposals=n, rewrites=rewrites, rewrite_new_words=added, restored=restored)
        row["check"] = f"proposals {n}/{len(cases)}" + (f", rewrite +{added}" if rewrites else "") + (f", {restored} restored" if restored else "")
        row["goal"] = "pass" if every and n == len(cases) else "FAIL"  # each request should get a rewrite or text to add
    return row


# ------------------------------------------------------------------ the table
COLUMNS = [  # (title, width, right-aligned)
    ("feature", 10, False), ("ran", 5, True), ("quotes verified", 15, True), ("check (plan's \"done when\")", 40, False), ("goal", 4, False),
    ("calls", 5, True), ("schema fails", 12, True), ("retries", 7, True), ("median ms", 9, True), ("tokens in/out", 15, True),
]


def _n(x: int | None) -> str:
    return "-" if x is None else f"{x:,}"


def _cells(r: dict) -> list[str]:
    q = f"{r['verified']}/{r['quotes']} {round(100 * r['rate']):>3}%" if r["quotes"] else "-"
    return [r["feature"], r["ran"], q, r["check"] or "-", r["goal"], _n(r["calls"]), _n(r["schema_failures"]), _n(r["retries"]),
            _n(r["latency_median"]), f"{_n(r['tokens_in'])}/{_n(r['tokens_out'])}" if r["calls"] else "-"]


def render(rows: list[dict], header: str) -> str:
    """The table, ASCII only so any console can print it."""
    def line(cells: list[str]) -> str:
        out = []
        for (title, width, right_), cell in zip(COLUMNS, cells, strict=True):
            cell = cell if len(cell) <= width else cell[: width - 1] + "~"
            out.append(cell.rjust(width) if right_ else cell.ljust(width))
        return "  ".join(out)

    head = line([t if len(t) <= w else t[:w] for t, w, _ in COLUMNS])
    rule = "-" * len(head)
    body = [line(_cells(r)) for r in rows]
    return "\n".join([header, rule, head, rule, *body, rule]).encode("ascii", "replace").decode("ascii")


LEGEND = """\
ran              cases that finished, of the cases run (a case that failed is listed under Problems)
quotes verified  quotes shown that were found word for word in the cited passage (brainstorm: ideas; organize: tags);
                 tidy, chat and notechat show no quotes: -
check            ask, library: said "found" / "not found" right, and every answer fully verified; library: its most
                 steps (code caps it at 3), and a question over two texts cites both
                 plan: day-by-day plans with no day over the minutes and nothing past the deadline
                 brainstorm: variety, 1 = ideas share no words, 0 = all the same (goal 0.50 or more)
                 organize: model_reuse, the share of the model's tags you already use (goal more than 0.50)
                 tidy: no invented facts, the proposals (each task, the note, the routine) that add no word you did
                 not write (goal more than half); note +N: words the note's rewrite added; restored: your own links
                 or tags it dropped, which code put back
                 chat: Plan chat's drafts that fit their day's free time (or are for any day), nothing flagged
                 (goal: every draft); dropped: past the 12 a reply may hold; already planned: tasks you have, left
                 out by code
                 notechat: requests that got a usable proposal (a rewrite or text to add, not only a reply);
                 rewrite +N: words a rewrite added; restored: your own links or tags it dropped, put back
goal             pass / FAIL against the plan's "done when"; - means a person judges it (read the results)
calls ...        from the AI log: model calls, answers that broke the schema, retries, median latency, tokens"""
