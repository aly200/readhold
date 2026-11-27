# Chapter 3. Back end: Plan, Notes, Search, Connections, Overview, Think

This chapter covers eleven modules, the AI package `readhold/ai/` (section 7b) and the eleven migrations behind them.

| Module | Name in the app | Writes? |
|---|---|---|
| `readhold/timer.py` | Timer, and the task list shown in Plan → Tasks | yes |
| `readhold/planner.py` | Plan → Tasks (`#/plan`): tasks by day, routines | yes (routines only) |
| `readhold/readplan.py` | **Plan my reading** on Plan → Tasks: what is left to read, spread over the days before a deadline (the reading plan without a model) | yes: tasks (`todos`) with a `plan_batch`, only when the reader adds a plan, and their removal on Undo |
| `readhold/pages.py` | Notes → All notes (`#/notes`), daily notes, the map | yes |
| `readhold/search.py` | Ctrl+K search | no |
| `readhold/passages.py` | No page of its own: the full-text index of sections (used by Ctrl+K) and "where a reading session went" | only the index `section_fts`, which is derived data |
| `readhold/related.py` | The "Connected" card, a day's summary, the week review | no |
| `readhold/hub.py` | Overview (`#/hub`) | no |
| `readhold/think.py` | Notes → Think (`#/think`) | yes, but only through accepted suggestions |
| `readhold/tidy.py` | **✨ Tidy tasks** on Plan → Tasks, the ✨ on a routine and in a note's bar: hints for what a task lacks, and the fixes code is sure of (milestone 5.2 without a model; section 7d) | only `routine_steps`, in place, when the reader applies a routine fix; everything else is applied by the page through the usual routes |
| `readhold/organize.py` | The **Organize** dialog and the collection chips of the Documents tab: document tags, related documents, suggested tags (the layer of milestone 3.3 without a model; section 7c) | yes: `documents.tags`, only when the reader sets tags |
| `readhold/ai/` (a package) and `readhold/redact.py` | Settings → AI, the "flagged text" mark on a document, and the twelve features: "Where you left off" in the Start a session dialog (the Resume briefing), **Explain** on a selected passage in the reader, the **Digest** dialog from the reader's map (the Document digest), the **Ask** tab of the reader's side panel (Ask this document), the *Ask your library* box on the Documents tab (Ask my library), the **Study notes** dialog from the reader's map (Study notes writer and flashcards), **Suggest an order with AI** in the Plan my reading dialog (the Reading plan), "Ideas from a model" on a brainstorm sheet and in the reader's **Brainstorm** dialog (Brainstorm), **Suggest tags and related documents** in the **Organize** dialog (Organize), the model's buttons in the three Tidy boxes (Tidy, milestone 5.2), **💬 Plan with a model** on Plan → Tasks (Plan chat, milestone 5.3), and **💬 Ask a model about this note** in a note's bar (Note chat, milestone 5.4). The LLM port, its adapters, key storage, the AI log, the guardrails every feature goes through, the prompt registry, the kept results | the log `ai_log`, the table `ai_results`, the file `data/ai_profiles.json`, the column `documents.flags`, a margin note (`notes`, with `origin='ai'`) when the reader saves an explanation, and, when the reader keeps study items, a note `Study notes: <document>` (`pages`) or review cards (`cards`, `source_type` `ai`), and, when the reader keeps ideas, the brainstorm sheet `Brainstorm: <title>` (`pages`), and, when the reader clicks Add in Plan chat, tasks (`todos` with `plan_batch` `chat:<id>`) and their removal on Undo (the note chat's Use and Add write the note through the usual `PATCH /api/pages/{id}`, from the page) |

All modules follow the same shape: pydantic models and plain functions at module level, then `register(app, db)` which defines the routes as closures. `server.py` calls the `register` functions in this order: `timer`, `planner`, `readplan` (with the settings function, for the reading pace), `pages`, `search`, `related`, `organize`, `tidy`, `hub`, `think`, `passages`, `trash` (chapter 1, section 7b), and last `ai.register(app, db, settings_dict)`, which also takes the settings function and itself calls `resume.register`, `explain.register`, `digest.register`, `ask.register`, `library.register`, `notes.register`, `plan.register`, `brainstorm.register`, `organize.register`, `tidy.register` and `chat.register` (each with `(app, db, port)`), then `why.register(app, db)`.

Shared helpers used below:

- `db.now()` returns a UTC ISO timestamp with milliseconds. `DB.insert` fills `id`, `device_id`, `created_at`, `updated_at`. `DB.update` also sets `updated_at` and `device_id`. `DB.soft_delete` sets `deleted=1`.
- `db.device` is this machine's device id. A raw `UPDATE` that writes `updated_at` by hand also sets `device_id=db.device`.
- `compass.need_row(db, table, id)` returns the live row or raises 404.
- `bodies.Body` (`readhold/bodies.py`) is the base class of request models with a required text. It refuses (422, `"<field> is empty"`) any string field that carries a `min_length` and holds only whitespace. A field left out of a patch is not checked. The text is not trimmed there; routes strip what they store. Here it is the base of `TodoIn`, `TodoPatch`, `ItemIn`, `ItemPatch` (`timer.py`), `StepIn`, `RoutineIn`, `RoutinePatch` (`planner.py`) and `PageIn`, `OpenIn`, `PagePatch`, `CaptureIn`, `QuoteIn` (`pages.py`). So "1–500" for those models means "1–500 and not only spaces".
- `services._local_date(iso)` turns a stored UTC timestamp into the local calendar date. Every "today" test on a timestamp goes through it.
- Each module has its own `ID = re.compile(r"[0-9a-f]{32}")`. Ids are checked with `fullmatch` before they reach SQL. A bad id is a 404, not a 422.

Naming: code says `todos`, `quests`, `pages`, `hub`. The app says tasks, Goals (the active quest is the "main goal"), notes, Overview.

---

## 1. `timer.py`: timer runs and tasks

One timer runs at a time. Its state is in the database, so a reload continues it. The same module owns the task list (`todos`), the small steps inside a task (`todo_items`), repeats, and the data for reminders.

### 1.1 Constants

| Name | Value | Meaning |
|---|---|---|
| `ID` | `[0-9a-f]{32}` | Shape of every id |
| `LinkType` | `Literal["", "step", "document", "lecture", "page"]` | What a task or run can point at. `page` is a note |
| `MAX_MINUTES` | `600` | Upper limit for a task estimate and a countdown |
| `QUIET_MS` | `150_000` | No heartbeat for this long means the app was closed or asleep |
| `DAY` | `\d{4}-\d{2}-\d{2}` | Pattern for `due` |
| `REPEAT` | `^(|daily|weekdays|weekly|monthly|every:([2-9]|[1-9]\d{1,2}))$` | Repeat rule. Empty means no repeat. `every:N` is every N days, N from 2 to 999 |
| `AT` | `^(|([01]\d|2[0-3]):[0-5]\d)$` | A 24-hour time `HH:MM`, or empty for no time |
| `MAX_ITEMS` | `20` | Small steps per task |

### 1.2 Models

`TodoIn` (create a task)

| Field | Type and limit | Default |
|---|---|---|
| `text` | str, 1–500 | required |
| `minutes` | int, 1–`MAX_MINUTES` | 25 |
| `link_type` | `LinkType` | `""` |
| `link_id` | str, max 32 | `""` |
| `due` | str or null, pattern `DAY` | null (anytime) |
| `repeat_rule` | str, pattern `REPEAT` | `""` |
| `at` | str, pattern `AT` | `""` |
| `area` | str, max 40 | `""` |
| `note` | str, max 2000 | `""` |
| `priority` | int, 0–1 | 0 |

`TodoPatch` has the same fields, all optional, plus `done: bool`, `ord: float` and `clear_due: bool = False`. `due: null` means "not sent", so `clear_due` is the only way back to anytime.

`ItemIn`: `text` 1–200. `ItemPatch`: optional `text` 1–200, optional `done`.

`StartIn` (start a run)

| Field | Type and limit | Default |
|---|---|---|
| `kind` | `"focus" | "break" | "stopwatch"` | required |
| `minutes` | int, 1–600 | 25 |
| `label` | str, max 300 | `""` |
| `todo_id` | str or null | null |
| `link_type`, `link_id` | as above | `""` |

`ElapsedIn`: `elapsed_ms` 0 to 24 hours. `FinishIn` adds `status` (`"done" | "stopped"`, default `"done"`), `feel` (`"" | "energized" | "neutral" | "drained"`) and `output` (max 500).

### 1.3 Functions

| Function | Behaviour |
|---|---|
| `_day(value)` | Returns a real ISO day or raises 422 "That day does not exist." (the regex accepts `2026-02-31`; this rejects it) |
| `next_due(due, rule, today=None)` | The next day of a repeating task. See 1.6 |
| `_check_id(value)` | 404 unless the id matches `ID`. `planner.py` imports it |
| `_ms_since(iso)` | Milliseconds from a timestamp to now, never negative |
| `run_out(run)` | The run plus `elapsed_now_ms` (`elapsed_ms` + time since `running_since`) and `running` (bool) |
| `run_view(db, run)` | Returns `run_out(run)`. It is the one name the routes use |
| `_link_ok(db, link_type, link_id)` | 422 unless the target exists and is not deleted. Table per type: `quest_steps`, `documents`, `lectures`, `pages` |
| `todo_items(db, todo_ids)` | `{todo_id: [{id, text, done}]}`, read in chunks of 400 ids, ordered by `ord, created_at`. `planner.py` uses it |
| `todo_out(db, todo)` | The task row plus `items` |
| `current_run(db)` | The newest `active` run. Applies the quiet rule (1.5) |
| `_sync_session(db, run, elapsed, end, feel, output)` | Copies elapsed time to the run's session |
| `finish_run(db, run, elapsed, status, feel, output)` | Ends a run. See 1.5 |
| `_today_summary(db)` | `{focus_ms, runs, todos_done}` for the local day. Counts ended, non-break runs started today |
| `list_todos(db)` | Open tasks that are for now (`due` empty or `due <= today`), then tasks finished today |

### 1.4 Routes

| Method and path | Body | Returns | Side effects |
|---|---|---|---|
| `GET /api/timer` | – | `{run, todos, today}` | May pause a quiet run (1.5) |
| `GET /api/timer/links` | – | `{steps, lectures, documents}`, 50 each. Steps are the open steps of the active quest | none |
| `GET /api/timer/recent` | – | Since 5.1: the live finished runs (`status != 'active'`) that are not breaks, started in the last 14 days, newest first (`started_at`, then `rowid`), at most 20: `id, kind, label, elapsed_ms, status, started_at, ended_at, link_type, link_id`. The Timer page's **Recent focus sessions**, each deletable through `DELETE /api/items/focus/{id}` (chapter 1, section 7b) | none |
| `POST /api/timer/start` | `StartIn` | the run (`run_view`) | Ends any active run, inserts a session (not for a break), inserts a run |
| `POST /api/timer/{rid}/pause` | `ElapsedIn` | the run | Saves elapsed, clears `running_since`, syncs session |
| `POST /api/timer/{rid}/resume` | – | the run | Sets `running_since` if paused |
| `POST /api/timer/{rid}/beat` | `ElapsedIn` | `{ok: true}` | Rebases elapsed time, syncs session |
| `POST /api/timer/{rid}/extend?minutes=5` | – (query `minutes`, 1–120) | the run | Adds to `planned_ms`. 422 for a stopwatch |
| `POST /api/timer/{rid}/finish` | `FinishIn` | `{ok, today, todos}` | Ends the run and its session, adds time to the task |
| `GET /api/todos/timed` | – | `{today, tasks: [{id, text, at, minutes}]}` | none |
| `POST /api/todos` | `TodoIn` | task with `items` | Inserts |
| `PATCH /api/todos/{tid}` | `TodoPatch` | task with `items` | See 1.6 |
| `DELETE /api/todos/{tid}` | – | `{ok: true}` | Soft delete |
| `POST /api/todos/{tid}/restore` | – | the task row (without `items`) | `deleted=0` |
| `POST /api/todos/{tid}/items` | `ItemIn` | task with `items` | 409 at `MAX_ITEMS` |
| `PATCH /api/todos/{tid}/items/{iid}` | `ItemPatch` | task with `items` | Updates one small step |
| `DELETE /api/todos/{tid}/items/{iid}` | – | task with `items` | Soft delete |

The pause, resume, beat, extend and finish routes go through the local helper `active(rid)`: 404 for a bad or missing id, 409 "This timer has already ended." when the status is not `active`.

`GET /api/todos/timed` returns today's open tasks that have a time (`at != ''` and `due = today`), ordered by `at`. The front end (`web/src/reminders.ts`) uses it for reminders while the app is open.

`GET /api/timer/links` does not list notes, although `page` is a valid `link_type`.

### 1.5 The timer run lifecycle

Stored state is two values: `elapsed_ms` (time counted so far) and `running_since` (when it was last started or resumed, `NULL` while paused). The time now is `elapsed_ms + (now - running_since)`.

**Start** (`api_timer_start`)
1. If a run is active, `finish_run` ends it with status `stopped` and its time up to now. One timer at a time.
2. If `todo_id` is given, the task is loaded. If the request has no link and the task has one, the run inherits the task's link.
3. `_link_ok` checks the link.
4. The label is the given label, else the task text, else `Focus`, `Break` or `Stopwatch`.
5. A `sessions` row is inserted whenever `kind != "break"`. It gets `document_id` (document link), `step_id` and `quest_id` (step link), `energy` from today's check-in (`compass.checkin_today`, default `medium`), `time_box_min` (the minutes for focus, 0 for a stopwatch) and `question` (the label).
6. A `timer_runs` row is inserted with `status='active'`, `elapsed_ms=0`, `running_since=now`, and `planned_ms` (0 for a stopwatch).

**Pause** stores `max(body.elapsed_ms, stored elapsed_ms)`, clears `running_since`, and syncs the session.

**Resume** sets `running_since=now` if the run was paused. It does nothing if it was already running.

**Beat** (the heartbeat; the module docstring says the open app sends one every 15 s). If the run is running it stores the client's elapsed time (never less than stored) and sets `running_since=now`. This "rebase" means a crash loses at most the time since the last beat. It also refreshes `updated_at`, which the quiet rule reads.

**The quiet rule** lives in `current_run`. If the active run is running and its `updated_at` is older than `QUIET_MS`, the run is paused at its stored `elapsed_ms` and returned with `was_quiet: True`. Hours with the app closed never count. `was_quiet` is not stored; it is only on that one response.

**Finish** (`finish_run`)
1. `elapsed = max(given, stored)`.
2. The run gets `elapsed_ms`, `running_since=NULL`, `status` (`done` or `stopped`) and `ended_at`.
3. `_sync_session(..., end=True)` sets the session's `focused_ms`, `longest_run_ms`, `ended_at`, and `feel` and `output` when given.
4. If the run has a task and is not a break, `todos.spent_ms` grows by `elapsed` (a raw `UPDATE` that also sets `updated_at` and `device_id`).

**How focused time is counted.** `_sync_session` writes `focused_ms = longest_run_ms = elapsed` on every pause, beat and finish. It overwrites; it does not add. The server trusts the client's `elapsed_ms` but never lets it go below the stored value.

**When a run counts in Stamina.** Stamina reads `sessions` (`services.daily_stats`), not `timer_runs`.

| Run | Session row | In Stamina | In the Timer page's `today.focus_ms` | Adds to `todos.spent_ms` |
|---|---|---|---|---|
| focus or stopwatch | yes | yes | yes | yes, if it has a task |
| break | no | no | no | no |

`services.daily_stats` marks a day as counting when its sessions total at least 10 focused minutes or it has a review.

Run status values: `active` → `done` or `stopped`. There is no way back to `active`.

### 1.6 Tasks

**Create** (`api_todo_create`). The link is checked. `ord` is the highest open `ord` plus 1, so a new task goes to the end. A repeating task with no day gets today as its first day.

**Patch** (`api_todo_patch`), in order:
1. `due` is checked with `_day`. `clear_due` sets `due` to null.
2. If `link_type` or `link_id` is sent, the pair is rebuilt and checked. An empty `link_type` clears `link_id`.
3. `done: true` on an open task sets `done_at`. Then:
   - If the task links to a quest step, the step gets `done_at` too, and `output = "Done: <task text>"` when its output was empty.
   - If the task has a repeat rule (the patched one, or the stored one), the next task is inserted and its id stored in `next_id` of the finished task.
4. `done: false` clears `done_at`. If the task has a `next_id`, that next task is soft-deleted only when it is still open and has `spent_ms = 0`. `next_id` is cleared either way.

Un-finishing a task does not reopen the quest step.

**What the next task copies:** `text`, `minutes`, `area`, `note`, `repeat_rule`, `priority`, `at`, and the link unless it is a `step` link (a step is done once). Values patched in the same request win over stored ones. `due` is `next_due(due, rule)`. `ord` puts it at the end. `spent_ms` starts at 0. The small steps are copied by text, unticked, in order.

**`next_due(due, rule, today)`** starts from `due` (or today when there is none) and steps forward until the day is after today. So a task finished a week late does not produce a pile of overdue copies.

| Rule | Step |
|---|---|
| `daily` | +1 day |
| `every:N` | +N days |
| `weekdays` | +1 day, then skip Saturday and Sunday |
| `weekly` | +7 days |
| `monthly` | Same day number next month, or the month's last day when the month is shorter. The day number is taken from the original `due` (`anchor`), so 31 Jan → 28 Feb → 31 Mar |

**Small steps** (`todo_items`). At most `MAX_ITEMS` live items per task (409 beyond). The local helper `item(tid, iid)` checks that the item belongs to the task.

### 1.7 Tables

`todos` (0007, extended by 0010, 0012, 0014)

| Column | Meaning |
|---|---|
| `text` | The task |
| `minutes` | Your estimate (default 25) |
| `spent_ms` | Time spent with the timer |
| `ord` | Order (REAL) |
| `link_type`, `link_id` | `''`, `step`, `document`, `lecture` or `page`, and the target id. The comment in 0007 does not list `page`; the code accepts it |
| `done_at` | Timestamp when finished, NULL when open |
| `due` (0010) | The local day it is for, NULL = anytime |
| `repeat_rule` (0010) | See `REPEAT`. `every:N` came with 0014 and needed no column |
| `area` (0010) | A life area such as Study or Home |
| `note` (0010) | Free text |
| `next_id` (0010) | On a finished repeating task: the id of the task made from it |
| `priority` (0012) | 1 = "this one matters" |
| `at` (0014) | `HH:MM` or `''` |

`todo_items` (0012): `todo_id`, `text`, `done` (0/1), `ord`.

`timer_runs` (0007)

| Column | Meaning |
|---|---|
| `kind` | `focus`, `break`, `stopwatch` |
| `label` | What the run is called |
| `planned_ms` | Countdown length, 0 for a stopwatch |
| `elapsed_ms` | Time counted up to `running_since`, or the total once paused or ended |
| `running_since` | When it was last started or resumed, NULL while paused |
| `status` | `active`, `done`, `stopped` |
| `todo_id` | The task being timed, if any |
| `session_id` | The `sessions` row; NULL for a break |
| `link_type`, `link_id` | As on a task |
| `started_at`, `ended_at` | Timestamps |

All tables also have `id`, `device_id`, `created_at`, `updated_at`, `deleted`.

---

## 2. `planner.py`: the Plan page and routines

`GET /api/plan` returns everything the Tasks tab needs in one call. Tasks are the `todos` rows from `timer.py`; this module only reads them. It owns routines: short ordered checklists for the morning, the day or the evening whose ticks belong to one day.

### 2.1 Constants and models

| Name | Value | Meaning |
|---|---|---|
| `Slot` | `"morning" | "day" | "evening"` | Part of the day |
| `SLOT_ORDER` | `{"morning": 0, "day": 1, "evening": 2}` | Sort order of routines |
| `MAX_STEPS` | `30` | Steps per routine (a pydantic list limit, so 422) |
| `MAX_ROUTINES` | `12` | Live routines (409 beyond) |
| `WEEKDAYS` | `^[0-6]{0,7}$` | Days a routine is for, as digits, 0 = Monday. Empty = every day |

`StepIn`: `text` 1–200, `minutes` 0–240 (0 = no timer for this step).
`RoutineIn`: `title` 1–120, `slot` (default `morning`), `weekdays`, `steps` (max `MAX_STEPS`).
`RoutinePatch`: the same, all optional.
`CheckIn`: `done: bool = True`.

### 2.2 Functions

**`_weekdays(value) -> set[int]`** turns the string into a set of digits. All seven days collapse to the empty set, which means every day. Stored values are always sorted and deduplicated.

**`routine_out(db, routine, today=None) -> dict`**

```json
{"id": "", "title": "", "slot": "morning", "ord": 1.0,
 "weekdays": "01234", "on_today": true, "next_on": "",
 "steps": [{"id": "", "text": "", "minutes": 0, "done": false}],
 "done": 0,
 "days": [{"day": "2026-11-17", "part": 0.5, "off": false}]}
```

- `steps`: live steps in order, each with `done` for today.
- `done`: how many steps are ticked today.
- `days`: the last seven days, oldest first, ending today. `part` is ticked steps divided by the current number of steps, rounded to 2 places (0 when there are no steps). Ticks of steps that were since removed are ignored. `off` is true when the routine has weekdays and that day is not one of them.
- `on_today`: true when the routine has no weekdays or today is one.
- `next_on`: empty when on today; otherwise the next date within 7 days that is one of its weekdays.

**`routines(db)`** returns all live routines, sorted by slot, then `ord`, then `created_at`.

**`_set_steps(db, routine_id, steps)`** replaces the steps but keeps history. A new step whose stripped text equals an old step's text reuses that row (its `minutes` and `ord` are updated). Other new steps are inserted. Old steps that were not reused are soft-deleted. Duplicated texts are matched one to one in order. Because ticks point at step ids, an unchanged step keeps its past ticks; a reworded step starts fresh.

**`plan(db) -> dict`**

| Field | Source |
|---|---|
| `today` | The server's local date |
| `tasks` | All open tasks (any day, including future ones) and tasks finished today, each with `items`. Ordered open first, then `ord, created_at` |
| `quest_step` | `_quest_step(db)` |
| `review_due` | Count of `cards` with `deleted=0`, `suspended=0` and `due <= now`. Not limited by the daily review cap |
| `areas` | Up to 20 area names, most used first |
| `routines` | `routines(db)` |
| `done_week` | Tasks with `done_at` in the last 7×24 hours |

**`_quest_step(db)`** takes `compass.active_quest`, then `compass.lead_step` over its steps (the marked lead step if still open, else the first open step). Returns `{id, title, minutes, quest_id, quest_title, in_plan}` or `None`. `in_plan` is true when an open task links to that step.

### 2.3 How Plan groups tasks

The server sends one flat list. The grouping is done in `renderTasks` in `web/src/views/plan.ts` from `due` and `data.today`:

| Group | Rule |
|---|---|
| Carried over | open, `due < today` |
| Today | open, `due == today`. The quest step and the review row are shown first in this group |
| Next 7 days | open, `today < due <= today + 7` |
| Later | open, `due > today + 7` |
| Anytime | open, no `due` |
| Done today | `done_at` set (the server only sends those finished today) |

A task whose day has passed is never marked late in data. Nothing rewrites `due`.

`timer.list_todos` (the Timer page) and `hub.hub` use their own filters. If you change what "for now" means, check all three plus `/api/plan/counts`.

### 2.4 Routes

| Method and path | Body | Returns | Side effects |
|---|---|---|---|
| `GET /api/plan` | – | `plan(db)` | none |
| `POST /api/routines` | `RoutineIn` | `routine_out` | Inserts routine and steps. 409 at `MAX_ROUTINES` |
| `PATCH /api/routines/{rid}` | `RoutinePatch` | `routine_out` | Updates fields; `steps` replaces the list through `_set_steps` |
| `DELETE /api/routines/{rid}` | – | `{ok: true}` | Soft-deletes the routine (its steps and checks stay) |
| `POST /api/routines/{rid}/restore` | – | `routine_out` | `deleted=0`. Does not check `MAX_ROUTINES` |
| `POST /api/routines/{rid}/steps/{sid}/check` | `CheckIn` | `routine_out` | Ticks or unticks one step for today |

**Routine checks.** A tick is one `routine_checks` row for `(step_id, day)` with the server's local date. `done: true` inserts a row if there is none. `done: false` soft-deletes it. Ticking again after unticking inserts a new row. The route does not check `on_today`, so a step can be ticked on an off day. There is no route to tick a past day.

### 2.5 Tables (0010, 0012)

| Table | Columns |
|---|---|
| `routines` | `title`, `slot`, `ord`, `weekdays` (0012; `''` = every day) |
| `routine_steps` | `routine_id`, `text`, `minutes`, `ord` |
| `routine_checks` | `routine_id`, `step_id`, `day` (local `YYYY-MM-DD`) |

---

## 2b. `readplan.py`: the reading plan (no model)

Milestone 3.1 of `docs/ai/PLAN.md` ("Reading plan: LLM sizing plus code scheduler"; done when "plans never exceed daily time or miss the deadline"). This module is the plan without a model, and the half that code always does, also with AI on (ADR 008: code handles scheduling and dates). The reader chooses the documents, their order and a level per document; code works out the time and the days. A model may only suggest the order and the levels (`ai/plan.py`, section 7b); the schedule is made here either way.

### 2b.1 Names

| Name | What it is |
|---|---|
| `LEVELS` | `{"easy": 0.8, "medium": 1.0, "hard": 1.4}`: the factor on reading time |
| `MIN_PIECE` | 10 minutes: with less room than this left in a day and more to read, the next piece starts the next day. With fewer minutes a day than 10, the smallest piece is a whole day (`min(MIN_PIECE, per_day)`) |
| `MAX_DOCS` | 20 documents in one plan |
| `MAX_DAYS` | 366: a deadline more than a year away is refused |
| `MAX_PER_DAY` | 600 minutes (a task's longest time, `timer.MAX_MINUTES`); also the top of the `need_per_day` search |
| `UNDO_DAYS` | 14: how long "Take that plan back" is offered after a reload |
| `Invalid` | 422 with the reason |
| `Changed` | 409: the plan to add is not the one the page showed, or a `from_ai` order is no longer the model's |
| `_apply_lock` | One apply at a time, so two applies at once cannot each see the other's days as free |
| `_UNTOUCHED` | The SQL test for a task as the plan made it: not done, no time spent, `updated_at = created_at` (never edited, moved or starred) and no live small steps |
| `DocIn`, `PlanIn` | `{documents: [{id, level}] (1 to 20), deadline: "YYYY-MM-DD", minutes_per_day: 5..600, days_off: weekday digits (0 = Monday; all seven is `Invalid`, "Leave at least one day of the week for reading."), goal (up to 200), from_ai (a result id, or ""), expect (the preview's `key`, or "")}` |

### 2b.2 Functions

| Function | What it does |
|---|---|
| `minutes(words, wpm, level)` | `ceil(words / wpm × LEVELS[level])`, at least 1 for any words, 0 for none. `wpm` is clamped to 60..1200 (default 250), as in `digest.facts` |
| `remaining(db, doc_id)` | The live document (else `None`) and what is left of it: its live, visible sections (`hidden=0`) with the words of their sentences from `documents.position` on, in order; a finished document has none. `{…document, sections: [{id, title, sentence, words}], words_left}` |
| `parts(left, wpm, level)` | The sections as pieces of reading time. The document's minutes (`minutes(words_left)`) are shared out by cumulative words, so thirty short sections do not each round up to a minute; a section that gets 0 minutes joins the next piece (`title` … `last`), and trailing ones join the last piece. The sum is exactly the document's minutes |
| `reading_days(start, deadline, days_off)` | Every day from `start` to `deadline` (both included) that is not a day off. `Invalid` for a deadline before today ("That deadline has passed…"), more than `MAX_DAYS` ahead, or no reading day left |
| `_fill(docs, days, room, smallest)` | The greedy fill: pieces in order, each day up to its `room`; a piece that does not fit is continued the next day (`continued: true`); a day with less than `smallest` free (and more to read) is skipped. The same document twice on one day is one item (`from` … `to`). What is left past the last day goes to `unplaced`, per document |
| `schedule(docs, start, deadline, per_day, days_off, busy)` | `room` per day is `per_day − busy[day]` (at least 0). Returns `{days: [{day, items: [{document_id, title, minutes, from, to, sentence, continued}], minutes, busy, room}] (every reading day up to the last one used, empty ones included), unplaced, fits, total, need_per_day, start, deadline, per_day, reading_days}`. When something is unplaced, `need_per_day` is the fewest minutes a day that fits, found by a binary search with the same scheduler (`None` when even `MAX_PER_DAY` does not) |
| `busy_minutes(db, start, deadline)` | Minutes of reading-plan tasks (`plan_batch != ''`, and since 5.3 not `chat:%`: Plan chat's batches are not reading) per day, counted on the safe side: every live one on its day, done or not, at its minutes or the time spent on it if more; an open one whose day has passed counts on today (it is on today's list), and so does one from an earlier day finished today. A second plan does not book the same time twice. Tasks you added yourself do not count |
| `plan_key(plan)` | A SHA-256 of what the page shows: each day's items (document, minutes, from, to) and what does not fit. `build` returns it as `key` |
| `build(db, body, wpm, today)` | Checks the deadline (a real day, `reading_days`) before reading anything; each document once; `LookupError` (404) for one that is not there; documents with nothing left go to `nothing_left`; then `schedule`. Adds `nothing_left`, `wpm`, `levels` and `key` |
| `apply(db, body, wpm)` | Under `_apply_lock`. `from_ai`, when given, must be a live `ai_results` row of feature `plan` (else 404) whose order is still the request's (`_ai_order`: the same documents in the same order, those with nothing left aside, and the model's level wherever it gave one; else `Changed`). Builds the plan again on the server (the page's preview is never trusted); with `expect`, a plan whose `key` differs is `Changed` (409, nothing added); a plan with no item is `Invalid` ("There is nothing to add…"). Then in one transaction inserts one task per item: `text` "Read “<title>”: <from> → <to>" (and " (continued)"), `minutes`, `due`, `link_type` `document`, `link_id`, the note "From your reading plan (for “<goal>”): finish by <deadline>." plus, from a suggestion, "The order and levels were suggested by the AI model; check that they suit you.", and one new `plan_batch` id. Marks the suggestion `accepted`. `{batch, added, plan}` |
| `undo(db, batch)` | In one transaction, soft-deletes every live task of the batch that is `_UNTOUCHED`; a task you finished, timed, edited, moved or gave small steps stays. `{removed, kept}`; twice is harmless; 404 for a batch that never existed |
| `last_batch(db)` | The newest batch (of the last `UNDO_DAYS` days, never a `chat:` one) that still has `_UNTOUCHED` tasks: `{id, open, created_at}` (`open` = how many Undo would remove) or `None` |
| `candidates(db, wpm)` | Unfinished live documents with something left (at most 200 looked at), by deadline then last use: `{id, title, why, deadline, status, words_left, minutes_left, sections_left}` |

The two promises, checked by `tests/test_reading_plan.py` (also on 400 random plans): no day holds more than `per_day` together with the reading-plan minutes already on it, and no reading lies outside today..deadline or on a day off. What does not fit is named in `unplaced`, never squeezed in; **Add to Plan** then adds only what fits.

### 2b.3 Routes

| Method and path | Body | Returns | Side effects |
|---|---|---|---|
| `GET /api/reading-plan` | – | `{documents: candidates, wpm, today, last_batch, levels, min_piece}` | none |
| `POST /api/reading-plan/preview` | `PlanIn` | `build(…)` | none |
| `POST /api/reading-plan/apply` | `PlanIn` | `{batch, added, plan}` | Inserts the tasks; marks the AI suggestion `accepted` (only when tasks are added) |
| `POST /api/reading-plan/{batch}/undo` | – | `{removed, kept}` | Soft-deletes the batch's open, untimed tasks |

Codes: 404 for a document or suggestion that is not there (`LookupError`) or an unknown batch; 409 for `Changed`; 422 for `Invalid` (a past deadline, all seven days off, nothing to add) and for a body that fails `PlanIn` (an unknown level, minutes out of range, a malformed date).

Found by an independent review after building, and fixed (each with a test in `tests/test_reading_plan.py` or `tests/test_ai_plan.py`): reading done or timed today, and open plan tasks from earlier days, were not counted against today, so a second plan could go past the minutes a day (`busy_minutes` now counts them); Undo removed tasks the reader had edited or given small steps (`_UNTOUCHED`); two applies at once could book the same days twice (`_apply_lock`); the page could add a plan it had not shown yet, within the 250 ms before the new preview (`expect` and `plan_key`, and the page disables Add at once); a plan with nothing in it was "added" and its Undo then answered 404 (now 422); the AI label stayed on tasks after the reader changed the model's order (`_ai_order`, and the page drops `from_ai` on any change of order, level or tick); `true` as a document number placed document 1, and one null field failed the whole answer (`Pick` takes any value; `_number` and `_text` check each by hand); all seven days off gave a generic 422. `wpm` comes from the `wpm` setting (`register(app, db, settings)`).

### 2b.4 Table (0020)

`0020_plan_batch.sql` adds `todos.plan_batch TEXT NOT NULL DEFAULT ''` (`''` = a task you added yourself) and a partial index on it. Since 5.3 Plan chat writes `chat:<id>` there (one per click, `ai/chat.py`), and `_UNTOUCHED` is what its Undo uses too. Nothing else in the app reads it: a reading-plan task is an ordinary task you can edit, move, time or delete.

---

## 3. `pages.py`: notes

A note ("page" in code) is a title and a plain-text body in a small Markdown. `[[Title]]` links to anything with that title. The module keeps a link table in step with the bodies, reads tags and properties from the text, makes daily notes, and serves the data for the map.

### 3.1 Constants and patterns

| Name | Value | Meaning |
|---|---|---|
| `LINK` | `\[\[([^\[\]\n|]{1,200})(?:\|([^\[\]\n]{0,200}))?\]\]` | `[[Title]]` or `[[Title|shown text]]`. Group 1 is the target, group 2 the alias |
| `TAG` | `(?<![\w&#/])#([^\W\d_][\w-]{0,39})` | `#tag`. Must not follow a word character, `&`, `#` or `/` (so `a#b`, `&#39;`, `##` and URL fragments are not tags). Starts with a letter of any alphabet, then up to 39 word characters or hyphens |
| `FENCE` | ```` ```.*?``` ```` with `re.S` | A fenced code block. Removed before links, tags and properties are read |
| `ANCHOR` | `\s*#s\d{1,6}\s*$` | A sentence anchor at the end of a link target: `[[Title#s12]]` is sentence 12 of a document |
| `PROP` | `^([A-Za-z][\w \-]{0,30})::[ \t]*(\S.*)$` with `re.M` | A property line `key:: value`. The key starts with an ASCII letter and is at most 31 characters. The value must not be empty |
| `MAX_PROPS` | `12` | Properties read per note |
| `MAX_BODY` | `200_000` | Characters in a body |
| `COLS` | `id, title, body, tags, pinned, daily, created_at, updated_at` | Columns returned for a page |
| `DAILY_BODY` | `"## Today\n- [ ] \n\n## Notes\n\n\n## One good thing\n"` | Template of a new daily note |

### 3.2 Models

| Model | Fields |
|---|---|
| `PageIn` | `title` 1–200, `body` max `MAX_BODY` (default `""`) |
| `OpenIn` | `title` 1–200 |
| `PagePatch` | optional `title` 1–200, optional `body`, optional `pinned: bool` |
| `MentionIn` | `from_id` |
| `CaptureIn` | `text` 1–1000, `day` (`YYYY-MM-DD`) |
| `QuoteIn` | `text` 1–4000, `document_id`, `sentence` 0–999999 (default 0), `day` |

`day` in `CaptureIn` and `QuoteIn` is the client's local day. The client chooses which daily note gets the line.

### 3.3 Functions

| Function | Behaviour |
|---|---|
| `key(title) -> str` | Collapses whitespace and applies `casefold()`. This is how titles are compared everywhere |
| `links_in(body) -> list[str]` | The keys a body links to, each once, in order. Code fences are skipped and a sentence anchor is removed first |
| `props_in(body) -> dict` | The first `MAX_PROPS` properties. Keys are lower-cased with whitespace collapsed; the first line for a key wins; values are cut to 200 characters |
| `tags_in(body) -> str` | Lower-cased tags, sorted, space separated |
| `_snippet(body, n=140)` | A one-line preview: links become their text, property lines and Markdown marks are removed |
| `_line_with(body, target)` | The first line that contains `target` (case-folded), cut to 200 characters |
| `linkable(title) -> bool` | True when a title can stand inside `[[ ]]`: not empty, at most 190 characters, none of `[ ] | #` or a newline |
| `link_first_mention(body, title)` | See 3.6 |
| `relink(db, page_id, body)` | Brings `page_links` in step with the body. Only differences are written |
| `find(db, title)` | The oldest live page with that `title_key`, or `None` |
| `create(db, title, body="", daily=None)` | 422 for an empty title, 409 if the title exists. Sets `title_key`, `tags`, runs `relink` |
| `resolve(db, target)` | What a link key points to. See 3.4 |
| `detail(db, page)` | The page plus `outgoing`, `backlinks`, `mentions`, `graph`. See 3.5 |

### 3.4 Links: parsing, storing, resolving

**Parsing.** `links_in` strips code fences, finds every `LINK`, removes a trailing `#s12` anchor, and turns the target into a key. So `[[Linear  Algebra]]`, `[[linear algebra|LA]]` and `[[Linear algebra#s40]]` all give the key `linear algebra`.

**Storing.** `page_links` has one live row per `(from_id, target)`, where `target` is the key, not an id. A link can therefore point at a page that does not exist yet, or at something that is not a page. `relink` soft-deletes rows whose target left the body and inserts rows for new targets. Every code path that changes a body must call `relink` and recompute `tags`: `create`, `api_page_patch`, `api_page_quote`, `api_page_capture`, `api_link_mention`, the rename rewrite, and `think._set_body`.

**Resolving.** `resolve` tries, in order:

1. a note with that `title_key` → `{"kind": "page", id, title}`
2. a document, then a lecture, then a quest whose `lower(title)` equals the key → `kind` `document`, `lecture`, `quest`
3. a glossary term whose `lower(term)` equals the key → `kind: "term"` (the link opens its concept page)
4. otherwise `{"kind": "missing", "id": None, "title": target}`. `target` is the key, so this title is case-folded; `detail` puts the typed casing back (3.5)

A note always wins over other things with the same title. The function's docstring does not mention terms; the code handles them.

The sentence anchor is not used on the server beyond being stripped. The front end reads it from the body to open the reader at that sentence.

### 3.5 `detail`: what surrounds a page

```json
{"id": "", "title": "", "body": "", "tags": "", "pinned": 0, "daily": null,
 "created_at": "", "updated_at": "",
 "outgoing":  [{"kind": "page", "id": "", "title": "", "key": ""}],
 "backlinks": [{"id": "", "title": "", "context": ""}],
 "mentions":  [{"id": "", "title": "", "context": ""}],
 "graph": {"nodes": [{"id": "", "title": ""}], "edges": [["from", "to"]]}}
```

- `outgoing`: `resolve` for every key in `links_in(body)`. For a `missing` link, `title` is replaced by the target as it was typed in the body (anchor removed, whitespace collapsed; the first spelling wins when the same key is linked twice), so a note created from that link gets the casing the user wrote. `key` stays case-folded.
- `backlinks`: up to 100 other live pages with a `page_links` row whose target is this page's key, newest first. `context` is the line containing `[[<key>`.
- `mentions`: only when the key has 3 or more characters. Up to 30 other pages whose body contains the key are scanned; a page is kept when it is not already a backlink and the key still appears after links are removed. At most 10 are returned.
- `graph`: this page, the notes it links to, and the notes that link here. Edges are `[from, to]`. Non-note targets are not in the graph.

### 3.6 Turning a mention into a link

`link_first_mention(body, title)` builds a pattern from the title's words joined by `\s+`, case-insensitive, with `(?<![\w\[])` before and `(?![\w\]])` after, so it matches whole words and not text already inside brackets. It walks the body between existing `LINK` matches and replaces the first match with `[[title]]`. It returns the new body, or `None` when there is no plain mention. The inserted text is the canonical title, so the casing the user typed is replaced.

Both `POST /api/pages/{pid}/link-mention` and Think's `mention` suggestion use it.

### 3.7 Tags and properties

- Tags are recomputed from the body on every body change and stored in `pages.tags` as a sorted, space-separated string. `GET /api/pages?tag=x` filters on whole tags after the SQL query.
- Properties are not stored. `props_in` is run on each row when `GET /api/pages` builds the list, and `_snippet` hides the property lines.

### 3.8 Daily notes

`GET /api/pages/daily/{day}` validates the day (404 if it is not a real date) and returns the first that exists:

1. the page with `daily = day`,
2. a page whose title is the day (it is returned as it is; its `daily` column is not set),
3. a new page titled with the day, body `DAILY_BODY`, `daily = day`.

This GET writes on first open. The quote and capture routes use the same three-step lookup.

### 3.9 Quote and capture

**`POST /api/pages/quote`** puts a passage from a document at the end of the day's note:

```
<existing body, right-trimmed>

> <text, whitespace collapsed>
> — [[<Title>#s<sentence>|<Title>]]
```

The source is a link only when the document title has none of `[ ] | #` and is at most 190 characters; otherwise it is the plain title. 404 if the document is gone, 409 if the body would pass `MAX_BODY`. Returns `{id, title}` of the note. `sentence` is not checked against the document.

**`POST /api/pages/capture`** adds one line `- <text>` to the day's note:

- If no line equals `## notes` (case-insensitive, trimmed): the line is appended at the end.
- Otherwise: the section runs from that heading to the next line starting with `## ` (or the end). The line goes after the last non-empty line of the section. Then the empty lines after it are reduced to exactly one before whatever follows.

409 if the body would pass `MAX_BODY`. Returns `{id, title}`.

### 3.10 Rename

In `api_page_patch`, when the new title's key differs from the old one:

1. 409 if another page has the new title.
2. Every page with a link row to the old key is loaded. A pattern matches `[[ old title ]]` and `[[ old title |alias]]` (case-insensitive, flexible whitespace) and replaces the title, keeping the alias.
3. Other pages are updated and relinked at once. For the page itself, the rewrite is applied only when the request did not also send a `body`; a sent body is stored as given.

When only case or spacing changes, the key is the same and no bodies are rewritten.

### 3.11 Routes

| Method and path | Body or query | Returns | Side effects |
|---|---|---|---|
| `GET /api/pages` | `q`, `tag` | `{pages, tags, total, links}` | none |
| `GET /api/pages/titles` | – | `{pages: [{id, title}], others: [{kind, id, title}]}` | none |
| `POST /api/pages` | `PageIn` | `detail` | Inserts. 409 on a duplicate title |
| `POST /api/pages/open` | `OpenIn` | `detail` | Creates the note if no note has that title |
| `GET /api/pages/daily/{day}` | – | `detail` | May create the daily note |
| `GET /api/pages/graph` | – | `{nodes, edges, total}` | none |
| `POST /api/pages/quote` | `QuoteIn` | `{id, title}` | Appends to the day's note |
| `POST /api/pages/capture` | `CaptureIn` | `{id, title}` | Inserts a line in the day's note |
| `GET /api/pages/{pid}` | – | `detail` | none |
| `PATCH /api/pages/{pid}` | `PagePatch` | `detail` | Updates; a rename rewrites links in other notes |
| `DELETE /api/pages/{pid}` | – | `{ok: true}` | Soft delete |
| `POST /api/pages/{pid}/restore` | – | `detail` | 409 if a live note now has that title |
| `POST /api/pages/{pid}/link-mention` | `MentionIn` | `detail` of the target | Edits the body of the note `from_id` |

Details:

- `GET /api/pages`: `q` matches `title_key` or `lower(body)` with `LIKE` (wildcards escaped). Order is pinned first, then newest; limit 500. Each row is `{id, title, tags, pinned, daily, updated_at, created_at, snippet, props}`. `tags` is the 40 most used tags as `[{tag, n}]`. `total` counts live pages; `links` counts live `page_links` rows.
- `GET /api/pages/titles`: up to 1000 notes; `others` has up to 100 documents, 100 lectures, 100 quests, and up to 300 terms deduplicated by lower-cased word.
- `GET /api/pages/graph`: the 400 most recently changed notes as `{id, title, tags, daily}`. An edge is added for each link row whose source and target are both in that set and are different notes. `total` is the number of live notes, so the front end can tell when the map is partial.

### 3.12 Tables (0011)

`pages`

| Column | Meaning |
|---|---|
| `title` | As typed, whitespace collapsed |
| `title_key` | `key(title)`. How links find a page. Indexed, not unique; the code enforces one live page per key |
| `body` | Plain text |
| `tags` | Tags found in the body, space separated |
| `pinned` | 0/1 |
| `daily` | `YYYY-MM-DD` for a daily note, else NULL |

`page_links`: `from_id` (a page id), `target` (a title key, of a page or of something else).

---

## 4. `search.py`: Ctrl+K

One function, one route, read-only. It imports `passages` for step 5b.

`PER_KIND = 6`.

`_like(q)` case-folds the query and escapes `\`, `%` and `_`, so wildcards typed by the user are plain text. `_around(text, q, n=90)` returns about `n` characters around the first match, starting a third of `n` before it, with a leading `…` when cut.

**`search(db, q) -> list[dict]`** collapses whitespace, cuts the query to 100 characters, and returns `[]` for an empty query. There is no score. The order of the result list is the order of these steps, and each step has its own limit:

| Step | Kind | Match | Limit | `title` / `hint` |
|---|---|---|---|---|
| 1 | `note` | `title_key LIKE` | 6, newest first | title / `""` |
| 2 | `note` | `lower(body) LIKE`, not already found | notes stop at 12 in total | title / text around the match |
| 3 | `task` | open tasks, `lower(text) LIKE` | 6, by `ord` | text / `"<due or anytime> · <area>"` |
| 4 | `document`, `lecture`, `quest` | `lower(title) LIKE` | 6 each, newest first | title / `""` |
| 5 | `passage` | `lower(sentences.text) LIKE`, only when the query has 3+ characters | scans up to 60 rows; keeps at most 2 per document and 6 in total | text around the match (110) / document title |
| 5b | `passage` | `passages.search_sections(db, q, limit=6)`: sections that hold the words anywhere, best first (section 4b). Same 3+ character condition | shares step 5's counters: at most 2 per document and 6 in total, counting step 5's hits. A hit on a sentence step 5 already listed is skipped | the hit's sentence, around the first word of the query (110) / `"<document title> · <section title>"` |
| 6 | `term` | `lower(term) LIKE` | 6 | term / definition (90) |
| 7 | `idea` | `lower(text) LIKE` | 3 | text (120) / `""` |

Every result has `kind`, `id`, `title`, `hint`. A passage has `id = "<document_id>:<ord>"` plus `document_id` and `sentence`, so the front end can open the reader at that sentence. Steps 5 and 5b give the same shape; the front end does not tell them apart.

Step 5 finds the exact phrase. Step 5b finds the words when they are not together, or are only the start of a word. When step 5 already gave 6 passages, step 5b adds nothing.

| Method and path | Query | Returns |
|---|---|---|
| `GET /api/search` | `q` | `{results: [...]}` |

---

## 4b. `passages.py`: the section index, and where a session went

Plain search and plain app data. No model is involved. The module does two things: it keeps and searches a full-text index of sections, and it describes the last reading session of a document. It was built as Phase 0 of the AI assistant plan (`docs/ai/PLAN.md`); nothing in it needs the later phases.

### 4b.1 Constants

| Name | Value | Meaning |
|---|---|---|
| `ID` | `[0-9a-f]{32}` | A row id |
| `WORD` | `[^\W_]+` (Unicode) | A word: letters and digits in any alphabet, no underscore |
| `MAX_QUERY` | 200 | Characters of a query that are read |
| `MAX_WORDS` | 12 | Words taken from a query |
| `TITLE_WEIGHT`, `BODY_WEIGHT` | 4.0, 1.0 | BM25 column weights: a match in the title counts 4 times a match in the text |

### 4b.2 The index

`section_fts` is an FTS5 table made by migration `0015_passages.sql` (columns in chapter 1, section 6). It has one row per section: `title`, `body` (the section's sentences joined by newlines), and the unindexed `document_id`, `section_id` and `first_ord`.

| Function | What it does |
|---|---|
| `reindex(db, doc_id) -> int` | Under `db.lock`: deletes the document's rows, and if the document exists and is not deleted, inserts one row per non-deleted section that has at least one non-deleted sentence in a non-deleted paragraph. `first_ord` is the lowest sentence `ord` of the section. Returns the number of rows written (0 for a removed document) |
| `ensure_index(db) -> int` | Calls `reindex` for every non-deleted document that has no row in `section_fts`. Returns how many of them got rows. This is how documents imported before migration 0015 enter the index |

`reindex` is called by `store.save_parsed` and by four routes in `server.py`: the section rename, merge-up, split and document delete (chapter 1, section 11). `ensure_index` runs once, at the top of `register`.

### 4b.3 `search_sections(db, q, limit=8, document_id=None) -> list[dict]`

1. **Words.** `_words(q)` cuts the query to 200 characters, takes the `WORD` matches, case-folds them and keeps the first 12. No words: `[]`.
2. **The FTS5 query.** `_match(words, joiner)` writes each word as `"word"*` and joins them. The quotes mean nothing the user types is read as FTS5 syntax: `AND`, `NEAR`, `*`, `:`, `^` and quotes are either plain words or dropped by step 1. The star makes the start of a word enough ("transform" finds "transformers").
3. **All words first.** The words are joined with ` AND `. If no row matches and there is more than one word, the query runs again with ` OR `.
4. **Ranking.** `ORDER BY bm25(section_fts, 4.0, 1.0)`, limited to `limit`. The join to `documents` keeps only non-deleted documents. With `document_id`, only that document's rows.
5. **The sentence to open at.** `_best_sentence(db, section_id, words, fallback)` reads the section's sentences in order and picks the one that holds the most query words (a word counts when some word of the sentence starts with it); the first such sentence wins a tie. If none holds a word (the match was in the title), the anchor is `first_ord` and the snippet is the section's first sentence. The snippet is that sentence with whitespace collapsed, cut to 240 characters.

Each result:

| Key | Content |
|---|---|
| `document_id`, `document_title` | The document |
| `section_id`, `section_title` | The section; the title is the one stored in the index |
| `sentence` | The sentence `ord` to open the reader at (`#/read/<document_id>?s=<sentence>`). When this sentence is not paced, as in a code block, the reader scrolls to its block and the pacer waits at the next paced sentence (chapter 5) |
| `snippet` | The text of that sentence |
| `score` | `-bm25`, rounded to 3 places. Higher is better. FTS5 gives a word that is in most rows almost no weight, so in a small library the score can be 0.0; the order still comes from the unrounded value |

### 4b.4 `last_session(db, doc_id) -> dict | None`

The last finished session of a document: the `sessions` row with that `document_id`, `deleted=0` and an `ended_at`, newest `ended_at` first. A session that is still open is never returned. `None` when there is none.

| Key | Content |
|---|---|
| `id`, `started_at`, `ended_at`, `focused_ms`, `sentences_read`, `question`, `next_step`, `start_ord`, `last_ord` | From the `sessions` row |
| `sections` | `{id, title, sentences}` per section, in section order: the sections with sentences whose `read_at` lies between `started_at` and `ended_at`, and how many. If no sentence was marked read in that time and both ords are set, the sections that hold the sentences from `start_ord` to `last_ord` (whichever is lower first) |
| `highlights` | `{id, sentence, end_sentence, type, text, note}` for the document's non-deleted highlights with `created_at` between `started_at` and `ended_at`, by sentence |

Everything is read from what was saved while reading. `start_ord` and `last_ord` are written by `POST` and `PATCH /api/sessions` in `server.py` (chapter 1, section 5.9).

### 4b.5 Routes

| Method and path | Query | Returns |
|---|---|---|
| `GET /api/passages` | `q`, optional `document_id` | `{results: search_sections(...)}` with the default limit of 8. A `document_id` that is not the id of a non-deleted document: 404 "document not found" |
| `GET /api/documents/{doc_id}/last-session` | | `{session: last_session(...)}`; `session` is `null` when the document has no finished session. 404 for a missing or deleted document |

No page calls either route. Ctrl+K reaches `search_sections` through `search.py`. The Resume briefing (section 7b) calls `last_session` directly and serves it through its own route, `GET /api/documents/{doc_id}/resume`.

---

## 5. `related.py`: connections

Three read-only views.

`Kind = Literal["document", "lecture", "quest", "term", "page"]`. `TABLES` maps each kind except `term` to its table and title column.

### 5.1 `related(db, kind, oid="", title="") -> dict`

Used by the "Connected" card.

1. Find the title. For `term`, the word comes from `title` and must exist in `terms` (a term is known by its word, because the same word can be saved from several documents). For the other kinds, the row is loaded by id. 404 when not found.
2. `k = pages.key(title)`.
3. `notes`: up to 30 live notes with a link row to `k`, excluding the object itself, newest first. Each is `{id, title, daily, context}`.
4. `mentions`: only for `term`, and only when `k` has 3+ characters. Notes whose body contains the word outside links and that do not already link to it. Up to 20 scanned, 8 returned.
5. `tasks`: open tasks pointing at the object.

| Kind | `tasks` |
|---|---|
| `document`, `lecture`, `page` | open `todos` with `link_type = kind` and `link_id = id` (limit 30) |
| `quest` | open `todos` with `link_type='step'` whose step belongs to the quest (limit 30) |
| `term` | always `[]` |

Result: `{kind, id, title, notes, mentions, tasks}`. Each task is `{id, text, due, minutes}`.

### 5.2 `day(db, day_iso) -> dict`

One day from every side. Rows are fetched in a three-day window and then filtered with `_local_date`.

| Field | Source |
|---|---|
| `day` | The input |
| `tasks_done` | Texts of tasks finished that local day, oldest first, at most 40 |
| `focus_min` | Sum of `sessions.focused_ms` for sessions started that day, in minutes |
| `routine_steps` | Count of live `routine_checks` for that day |
| `journal` | `{weather, written}` when the journal entry has weather or text, else `None` |
| `note_id` | Id of the daily note, or `None` |

### 5.3 `week(db) -> dict`

For the weekly review on the Stamina page.

| Field | Source |
|---|---|
| `tasks_done` | Count of tasks finished in the last 7×24 hours |
| `areas` | Top 5 areas among those tasks, `[{area, n}]` |
| `open` | Count of all open tasks |
| `routines` | Per routine `{title, days, of}`: `of` is the number of the last 7 days the routine was on, `days` how many of those had at least one tick |

### 5.4 Routes

| Method and path | Query | Returns |
|---|---|---|
| `GET /api/related` | `kind` (required, validated), `id`, `title` | `related(...)` |
| `GET /api/day/{day_iso}` | – | `day(...)`. 404 for a bad date |
| `GET /api/week/plan` | – | `week(...)` |

---

## 6. `hub.py`: Overview

`GET /api/hub` returns the state of every feature in one call. It only reads and reuses `planner.plan`, `related.day` and `compass.active_quest`.

`NOW_TASKS = 6`: how many tasks the page lists.

| Field | Source |
|---|---|
| `today` | `plan["today"]` |
| `tasks` | Open tasks with a day that is today or earlier, sorted by priority (starred first) then time of day (tasks without a time last). First `NOW_TASKS`, each `{id, text, minutes, priority, due, at}` |
| `tasks_now` | How many such tasks there are in total |
| `tasks_open` | All open tasks, including later and anytime ones |
| `tasks_done_today` | `len(day["tasks_done"])` |
| `done_week` | `plan["done_week"]` |
| `quest` | `{id, title, steps, steps_done}` for the active quest, or `None` |
| `quest_step` | `plan["quest_step"]` |
| `review_due` | `plan["review_due"]` (uncapped) |
| `routines` | Routines that are on today: `{id, title, slot, done, total, next}`. `next` is the first unticked step `{id, text}` or `None` |
| `focus_min` | `day["focus_min"]` |
| `focus_week` | Seven entries `{day, min}` for the last seven days ending today, from `sessions.focused_ms` grouped by local start date |
| `journal` | `day["journal"]` |
| `notes`, `notes_total` | The 5 most recently changed notes `{id, title, daily}`; count of live notes |
| `ideas`, `ideas_total` | The 2 newest ideas `{id, text}` (text cut to 140); count |
| `documents`, `documents_total` | The 3 most recently changed documents whose status is not `finished`: `{id, title, status, position, total_sentences}`; count of all documents |
| `lectures`, `lectures_total` | The 3 most recently changed: `{id, title, kind, position, pages}`; count |
| `terms_total` | Distinct lower-cased terms |
| `stamp` | The UTC time the response was built |

Anytime tasks are not in `tasks` or `tasks_now`.

---

## 7. `think.py`: similar notes, suggestions, daily picks, brainstorm

Think uses no model. It counts words in the user's notes and ideas, compares the counts, and from that proposes small changes, picks a few items to think about each day, and gathers material for a brainstorm sheet.

### 7.1 Constants

| Name | Value | Meaning |
|---|---|---|
| `KINDS` | `("link", "mention", "file_idea", "tag")` | The only suggestion kinds |
| `PER_DAY` | `5` | New suggestions made per day |
| `PICKS` | `3` | Daily picks |
| `MAX_PAGES` | `600` | Most recently changed notes in the corpus |
| `MAX_IDEAS` | `300` | Newest ideas in the corpus |
| `LINK_SCORE` | `0.18` | Least similarity for a `link` suggestion |
| `IDEA_SCORE` | `0.15` | Least similarity for a `file_idea` suggestion |
| `NEAR_SCORE` | `0.12` | Least similarity that counts as "similar" |
| `SHEET` | `"Brainstorm: "` | Title prefix of a brainstorm sheet |
| `DAY` | `\d{4}-\d{2}-\d{2}` | Shape of the `day` query value |
| `WORD` | `[^\W\d_][^\W\d_'\-]{2,}` | A word: three or more letters in any alphabet |
| `APOSTROPHE` | `(?<=[^\W\d_])['’](?=[^\W\d_])` | A straight or curly apostrophe between two letters. Removed before words are found, so `don't` is one word (`dont`) and `matrix's` folds to `matrix` |
| `MARKS` | `[ً-ْـ]` | Arabic vowel marks and the tatweel (stretching line). Removed before words are found |
| `MARK` | the same pattern as `pages.LINK` | Used to replace a link with its text |
| `STOP` | a `frozenset` | Common English and Arabic words, contractions without their apostrophe (`dont`, `doesnt`, `cant`, …), plus app words such as `today`, `note`, `idea`, `related`, `todo` |

Two thresholds are literals, not constants: `0.25` in `similar` and `0.15` in the tag rule of `candidates`. In `make_picks`, `0.1` is the least similarity to the current goal.

### 7.2 Tokenisation: `words(text) -> list[str]`

1. Each link is replaced by its alias, or by its target without a sentence anchor.
2. The text is lower-cased and `MARKS` are removed, so an Arabic word with and without vowel marks is the same word. Then every `APOSTROPHE` is removed.
3. `WORD` finds the words.
4. A word in `STOP` is dropped here, before any folding.
5. ASCII words longer than 3 letters that end in `s` lose the `s`, unless they end in `ss`, `us` or `is` (`maps` → `map`; `class`, `status`, `basis` stay).
6. Non-ASCII words that start with `ال` and have 5 or more letters lose that prefix (the Arabic definite article).
7. Words shorter than 3 letters or in `STOP` are dropped.

The stop-word test runs twice: before the folding (step 4), so `does` is dropped and never becomes `doe`, and again after it (step 7), so a plural of a stop word is dropped too.

`_one_line(text, n=160)` is the same link replacement, whitespace collapsed, cut to `n`.

### 7.3 The corpus and similarity

**`corpus(db) -> Corpus`** (`Corpus` is a `list` subclass with a `df` counter):

- Notes: live, not daily (`daily IS NULL`), the `MAX_PAGES` most recently changed, skipping titles that start with `SHEET`. Term counts come from the body; each title word adds 3.
- Ideas: live, the `MAX_IDEAS` newest. For an idea, `title` is its first 80 characters and `updated_at` is its `created_at`.
- Each item: `{kind, id, title, text, tags, updated_at, tf, vec}`.

Weights are TF-IDF, with `n` the number of items and `df[w]` the number of items using a word:

```
weight(w) = (1 + ln(tf[w])) * (ln((n + 1) / (df[w] + 1)) + 1)
```

Each vector is then scaled to length 1.

**`_alike(a, b) -> (score, shared)`** is the dot product of two vectors (the cosine, 0 to 1), with the three words that contribute most.

**`_vector(text, items)`** weighs text that is not in the corpus (the goal, a highlight) with the corpus's `df`.

**`similar(db, kind, item_id, n=5, items=None)`** returns up to `n` items `{kind, id, title, score, shared}`, best first. An item is kept when `score >= NEAR_SCORE` and it either shares two or more words or scores `>= 0.25`. An unknown item gives `[]`.

The corpus is rebuilt on each call that needs it. Nothing is cached.

### 7.4 Suggestions

**`candidates(db, items) -> list[dict]`** computes every change worth proposing now. It writes nothing. `notes` is every note in the corpus; `recent` is the first 200 (most recently changed). `_linked(db)` is the set of `(from note, to note)` pairs that already have a link.

| Kind | When it is proposed | Score | `key` | `payload` |
|---|---|---|---|---|
| `mention` | A target in `recent` with a title of 4+ characters that is `linkable`. A source note that does not link to it and whose text, with links removed, contains the title as whole words | `1.0` | `mention:<src>:<target>` | `{from_id, to_id}` |
| `link` | `a` in `recent`, `b` later in `notes`; both bodies have 40+ characters; no link in either direction; `b`'s title is `linkable`; similarity `>= LINK_SCORE` with 2+ shared words | the similarity | `link:<lo>:<hi>` (ids sorted, so one per pair) | `{from_id: a, to_id: b}`. `a` is the more recently changed note and gets the link |
| `file_idea` | For each idea, its best-matching note; similarity `>= IDEA_SCORE` with at least one shared word | the similarity | `file_idea:<idea>:<note>` | `{idea_id, to_id}` |
| `tag` | For each of the first 120 notes: take up to 6 notes with similarity `>= 0.15` (the first six in corpus order). A tag carried by 2+ of them, missing on this note, and matching `[^\W\d_][\w-]{0,39}` | `0.3 + 0.05 * k` (k = neighbours with the tag) | `tag:<page>:<tag>` | `{page_id, tag}` |

Candidates are sorted by score (highest first), then key. Each has a `reason` in plain words that names the shared words or the count, so the user can check it.

**`suggestions(db) -> list[dict]`** (called by `GET /api/think`):

1. The day is the server's `dt.date.today()`; the `day` the page sends is not passed in. Count suggestions with `created_at` since the local start of that day (`_day_start`). All statuses count.
2. If fewer than `PER_DAY`, go through the candidates, best first, until the count reaches `PER_DAY`:
   - a candidate whose `key` is not in the table is inserted;
   - a candidate whose key belongs to a live row with status `stale` is checked with `_describe` against its fresh payload. If it applies again, the same row is updated: new `payload`, `reason` and `score`, `status='new'`, `decided_at` cleared, `created_at` set to now. It counts towards today's limit;
   - a candidate whose key belongs to any other row (`new`, `accepted`, `rejected`) is skipped.
3. Load suggestions with `status='new'`, by score then age. Each goes through `_describe`. Those that no longer apply are set to `stale` with `decided_at`.

The key of every suggestion ever made stays in the table (and has a unique index). A rejected suggestion is therefore never offered again. A stale one comes back, as the same row, when its change applies again (for example a link added by hand and then taken out). Rejecting all five does not refill the list that day.

**`_describe(db, s)`** returns the suggestion for display, or `None` when it no longer applies:

| Kind | No longer applies when |
|---|---|
| `link`, `mention` | Either note is gone, or the source already links to the target |
| `file_idea` | The idea or the note is gone |
| `tag` | The note is gone, the tag fails the tag pattern, or the note already has the tag |

The display shape is `{id, kind, reason, status, created_at, title, notes, change}`, plus `quote` for `file_idea`. `change` says in words exactly what accepting will do.

**`accept(db, s)`** raises 409 unless the status is `new`, the kind is in `KINDS` and `_describe` still passes. Then it makes one change:

| Kind | Change |
|---|---|
| `link` | Appends `\n\nRelated: [[<target title>]]\n` to the source note |
| `mention` | `pages.link_first_mention` on the source note (409 if the mention is gone) |
| `file_idea` | Appends `\n- <idea in one line, max 1000>\n` to the note and soft-deletes the idea |
| `tag` | Appends `\n\n#<tag>\n` to the note |

Every body change goes through `_set_body`, which refuses bodies over `pages.MAX_BODY` (409), recomputes tags and calls `pages.relink`. The suggestion gets `status='accepted'`, `decided_at`, and `undo` as JSON: `{page_id, before, after}` plus `idea_id` for `file_idea`. Returns `{ok, id, page_id}`.

**`undo(db, s)`** raises 409 unless the status is `accepted` and `undo` is set. It loads the page and compares its body with the stored `after`. If they differ in any way it refuses: "The note has changed since. Edit it by hand to take the change out." Otherwise it restores `before`, restores the idea (`deleted=0`) for `file_idea`, and sets the suggestion back to `new` with an empty `undo`. The suggestion is then open again and can be accepted or rejected.

**Status values**

| From | To | By |
|---|---|---|
| `new` | `accepted` | `accept` |
| `accepted` | `new` | `undo` |
| `new` | `rejected` | `POST .../reject` (final) |
| `new` | `stale` | `suggestions`, when `_describe` returns `None` |
| `stale` | `new` | `suggestions`, when the same key is a candidate again and `_describe` passes |

### 7.5 Daily picks

**`picks(db, day)`** calls `make_picks` when the day has no pick rows, then returns the day's picks that are not dismissed and whose item still exists: `{id, kind, item_id, title, snippet, signal, reason, status}`. Picks are stored, so they stay the same all day.

**`make_picks(db, day)`**:

1. Build the corpus. The pool is every item that was not picked in the last 7 days (dismissed picks count too) and has at least 2 meaningful words in title and text together.
2. Find the context with `_context(db)`: the active quest (its title twice, its questions, its open step titles), else the title of the most recently changed document with status `reading`, else nothing.
3. For each item, compute its age in days from `updated_at` and add it to every signal it fits:

| Signal | Fits when | Rank |
|---|---|---|
| `quest` | There is a context, similarity to it `>= 0.1`, and a shared word | the similarity |
| `question` | A line is an unticked check box (`- [ ] text`) that does not end with `(in Plan)`, or a line ends with `?` and is longer than 8 characters | `min(age, 60) / 60` |
| `orphan` | It is a note, it has no note-to-note link in either direction, and it is 2+ days old | `min(age, 60) / 60` |
| `resting` | An idea 7+ days old, or a note 14+ days old | `min(age, 90) / 90` |

4. Choose up to `PICKS` items. Up to `PICKS` rounds go through the signals in the order `quest`, `question`, `orphan`, `resting`. Each takes its best item not yet taken. Ties (rank rounded to 2 places) are broken by `sha256("<day>:<item id>")`, which gives a different order each day and the same order all day.
5. Insert one `daily_picks` row per chosen item with its `signal` and `reason`.

The signal is named `quest` even when the context is a document being read; the reason text says which it was.

Pick status: `new` → `opened` or `dismissed`, set by the client through `POST /api/think/picks/{pid}`. The route accepts any of the three values at any time.

### 7.6 Brainstorm

**`brainstorm(db, kind, item_id) -> dict`** is read-only. 404 when the item is gone.

| Field | Content |
|---|---|
| `item` | From `_item`: `{kind, id, title, text}`; an idea also has `document_id`, `sentence`, `document_title` |
| `near` | `similar(...)` with `n=6` |
| `reading` | Among the 800 newest highlights, those whose text plus note is similar to the item (`>= NEAR_SCORE` with a shared word). Top 6: `{document_id, sentence, type, text, title, score, shared}` |
| `sheet_title` | `SHEET` (`"Brainstorm: "`) + item title, cut to 190 |
| `sheet` | `{id, body}` of the note with that title, or `None` |

This function never creates the sheet. The sheet is an ordinary note, made and saved through the `pages` routes (and, for ideas a model wrote, by `ai.brainstorm.keep` and `undo`, section 7b). Sheets are left out of the corpus by their title prefix. `ai/brainstorm.py` builds its sources from this function's answer, so the model reads what the sheet shows.

### 7.7 Routes

| Method and path | Body or query | Returns | Side effects |
|---|---|---|---|
| `GET /api/think` | `day` (required) | `{day, picks, suggestions, decided: {accepted, rejected}}` | May insert picks and suggestions; may mark suggestions `stale` or bring a stale one back |
| `GET /api/think/similar` | `kind` (`page` or `idea`), `id` | `{similar: [...]}` | none |
| `GET /api/think/brainstorm` | `kind`, `id` | `brainstorm(...)` | none |
| `POST /api/think/picks/{pid}` | `PickPatch` (`status`: `new`, `opened` or `dismissed`) | `{ok: true}` | Updates the pick |
| `POST /api/think/suggestions/{sid}/accept` | – | `{ok, id, page_id}` | Makes the one change |
| `POST /api/think/suggestions/{sid}/reject` | – | `{ok: true}` | 409 unless `new` |
| `POST /api/think/suggestions/{sid}/undo` | – | `{ok: true}` | Takes the change back |

`day` is the client's local day. The local helper `day_ok` answers 422 for a value that is not a real date ("not a day") and for a day more than one day away from the server's today ("not today"); a difference of one day is allowed for the minutes around midnight. The picks are made and read for the `day` sent. The suggestions' daily limit ignores it and uses the server's day (7.4).

### 7.8 Tables (0013)

`suggestions`

| Column | Meaning |
|---|---|
| `kind` | `link`, `mention`, `file_idea`, `tag` |
| `key` | What it is about. Unique index `idx_suggestions_key` |
| `payload` | JSON with the ids (and the tag) |
| `reason` | Why, in words |
| `score` | Used for ordering |
| `status` | `new`, `accepted`, `rejected`, `stale` |
| `undo` | JSON of what accepting changed, `''` otherwise |
| `decided_at` | When it was accepted, rejected or retired |

`daily_picks`: `day` (local date), `item_kind` (`page` or `idea`), `item_id`, `signal` (`quest`, `question`, `orphan`, `resting`), `reason`, `status` (`new`, `opened`, `dismissed`).

### 7.9 The safety design, and where each guarantee lives

The project's safety rules say (and the docstring of `think.py` repeats it): Think only counts and compares text; it never follows it. The only changes are the four suggestion kinds, each applied only when the user accepts, with undo. A model added later must go through the same suggestions.

| Guarantee | Where in the code |
|---|---|
| Note and document text is only counted and compared | `words`, `corpus`, `_alike`, `_vector`. Text is reduced to word counts. No code path reads a command, an id or a kind out of a body |
| Only four kinds of change exist | `KINDS`. `candidates` builds each kind with a literal `kind` string. `accept` rejects any other kind and has one branch per kind |
| A payload holds ids chosen by the code, never text from a note | `candidates` fills `payload` from corpus item ids. The one free value, the tag, must match `[^\W\d_][\w-]{0,39}` in both `candidates` and `_describe` |
| Records are checked before anything is changed | `_page` (id shape, live row) and the idea lookup in `_describe`; `accept` calls `_describe` first |
| Nothing changes without the user | `candidates` writes nothing. `suggestions` only inserts rows in `suggestions`. The only writers of note bodies are `accept` and `undo`, reached only from `POST .../accept` and `POST .../undo` |
| Accepting can be undone | `accept` stores `before` and `after` in `suggestions.undo` |
| Undo never overwrites later edits | `undo` requires `page["body"] == u["after"]` exactly, else 409 |
| A refused suggestion does not come back | The unique `key`, and the `known` rows in `suggestions`: only a row with status `stale` is offered again, never a `rejected` one |
| At most `PER_DAY` new ones a day | The `made_today` count in `suggestions`, taken on the server's day. A stale suggestion offered again counts. `day_ok` keeps the `day` of `GET /api/think` within one day of today |
| Looking at a tab makes nothing | `/api/notes/counts` in `server.py` only counts existing rows |
| Body size and link table stay correct | `_set_body` |
| Nothing leaves the machine | The module imports no network code |

`test_a_hostile_note_can_only_ever_be_counted` creates a note full of instruction-like text and checks that no body changes, no note is removed, and every suggestion is one of the four kinds with status `new`.

---

## 7c. `organize.py`: document tags, related documents, suggested tags (no model)

Milestone 3.3 of `docs/ai/PLAN.md` ("Organize library and related documents"), the layer without a model. The model's half is `ai/organize.py` (section 7b). Like `think.py`, this module only counts and compares text; it never follows it. The page side is `web/src/views/organize.ts` and the chips in `library.ts` (chapter 5, section 5.8).

### 7c.1 Names

| Name | What it is |
|---|---|
| `ID` | 32 hex characters |
| `TAG` | `[^\W\d_][\w-]{0,39}`: a letter first, then letters, digits, `_` or `-`, at most 40 characters. The same shape as a note `#tag` and a Think `tag` suggestion |
| `MAX_TAGS` | 12 tags on one document |
| `MAX_DOCS` | 400: the most recently changed documents that are compared |
| `SAMPLE_WORDS` | 2,000: the words of a document's text that count, from its start |
| `RELATED_SCORE` | 0.12: how alike two documents must be to be called related (the same as `think.NEAR_SCORE`) |
| `MAX_RELATED` | 5 |
| `MAIN_WORDS` | 30: a document's strongest words; a tag you use that is one of them is suggested |
| `MAX_SUGGESTED` | 6 |
| `TagsIn` | `{tags: [str] (at most 40), expect: [str] \| null (at most 40)}` |

### 7c.2 Functions

| Function | What it does |
|---|---|
| `clean_tag(raw) -> str \| None` | Strips spaces and a leading `#`, puts the text in NFC, lower-cases it, NFC again (so `café` typed with a combining accent is one tag), and keeps it only when it matches `TAG` and its first character `isalpha()` (so `²abc` is not a tag). A tag with a combining mark inside (Devanagari vowel signs, for example) fails `\w` and is refused, as note tags are |
| `tags_of(db, doc_id)` | `documents.tags` split at spaces |
| `known_tags(db, keep_here=None) -> Counter` | Every tag on live documents and on live notes (`pages.tags`), with how often. With `keep_here(tags)` (since 4.4, from `ai/organize.py` for a cloud call), an item for which it is true is not counted, and the tag `private` is dropped: a cloud model is not told the tags of private items, nor the word "private" |
| `set_tags(db, doc_id, raw, expect=None)` | 404 for a missing document. Each tag through `clean_tag` (422 with "“…” cannot be a tag: one word, starting with a letter, at most 40 characters."), repeats dropped in order, more than `MAX_TAGS` is 422. With `expect`: each through `clean_tag` (422 "`expect` holds something that is not a tag." when one fails), then 409 "The tags changed since. Nothing was changed; edit them by hand." unless the stored tags are exactly `expect`, in order. Then `db.update`. Returns the tags |
| `_profiles(db, include="")` | Per document: a weighted word count `tf` (`think.words`; the title ×3, the titles of live, visible sections ×2, the text of up to 200 live highlights ×2, the first `SAMPLE_WORDS` words of the live sentences in order ×1), then TF-IDF over the documents compared: `(1 + log c) × (log((n + 1) / (df + 1)) + 1)`, normalised. The documents are the `MAX_DOCS` most recently changed, plus `include` (the one asked about) when it is older. Not cached: about 0.3 s at 400 documents |
| `related(db, doc_id, profiles=None, n=MAX_RELATED, floor=RELATED_SCORE)` | `think._alike` of this document with every other profile; kept when the score is at least `floor` and they share at least two words. Best first, at most `n`: `{id, title, score, shared, tags}`. `ai/organize.py` calls it with a looser floor for its candidates |
| `suggested(db, doc_id, profiles=None)` | Tags worth adding, each with a reason. First the tags of the related documents that this one lacks ("The related document “<title>” has it.", scored by that document's score). Then, from `known_tags` (most used first), each tag whose words (`-` and `_` read as spaces) are all among this document's `MAIN_WORDS` strongest words ("You use #<tag>, and “<words>” is one of this document's main words.", scored 0.1 plus 0.01 per use, up to 9). Only tags you already use: a new word is for the reader, or a model, to propose. At most `MAX_SUGGESTED`, `existing: true` |
| `overview(db, doc_id)` | 404 for a missing document. One `_profiles` call, then `{tags, known (the 60 most used), related (id, title, score, shared), suggested (tag, existing, reason)}` |

### 7c.3 Routes

| Method and path | Body | Returns | Side effects |
|---|---|---|---|
| `GET /api/organize/{doc_id}` | – | `overview(...)` | none |
| `PUT /api/documents/{doc_id}/tags` | `TagsIn` | `{tags}` | Sets `documents.tags` |

Codes: 404 for a missing or removed document (or a malformed id); 409 when `expect` does not match; 422 for a tag that fails `clean_tag`, more than 12 tags, an `expect` that holds a non-tag, or a body that fails `TagsIn`.

`GET /api/documents` (`services.queue`, chapter 1) returns each document's `tags` as a list: the Documents tab draws its collection chips from it, so a tag is a collection with no table of its own.

### 7c.4 Table (0021)

`0021_document_tags.sql` adds `documents.tags TEXT NOT NULL DEFAULT ''`: the reader's tags, space separated, lower case. Only `set_tags` writes it. It is in the export with the rest of `documents`.

Found by an independent review after building, and fixed (tests in `tests/test_organize.py`): the document asked about was not profiled when it was not among the 400 most recent, so it had no related documents (`include`); tags were not NFC, so `café` could be two tags, and a superscript digit passed as a first letter (`clean_tag`); an `expect` that held a non-tag was compared instead of refused (now 422). **Still true:** the check-then-update of `set_tags` is not atomic (two changes at the same moment can both pass the `expect` check); `_profiles` is computed afresh for every request.

---

## 7d. `tidy.py`: hints and fixes for tasks, notes and routines (no model)

Milestone 5.2 of `docs/ai/PLAN.md` ("Tidy: messy notes, tasks and routines made clear"), the layer without a model. The model's half is `ai/tidy.py` (section 7b). A good task starts with what you will do (a verb), has one outcome and a day, and stays short. A missing part is a *hint*, never a change; a *fix* is only what code can be sure of. Only `apply_steps` writes; the page applies everything else through the usual routes, with Undo. The page side is `web/src/views/tidy.ts` (chapter 6).

### 7d.1 Names

| Name | What it is |
|---|---|
| `ID` | 32 hex characters |
| `MAX_MINUTES`, `MAX_STEP_MINUTES` | 600 (as `timer.MAX_MINUTES`) and 240 (as `planner.StepIn`) |
| `LONG` | 90 characters: a longer task gets the `long` hint |
| `MAX_TASKS` | 200 open tasks listed |
| `VERBS` | About 200 common first words of a task ("read", "email", "finish", …) |
| `JOIN` | A comma, a semicolon, "and" or "then", with the spaces around them: where a task may hold several |
| `TIME` | A time in the text: an optional "(" and "for ", a number (up to three digits, one decimal), then `min`, `mins`, `minute`, `minutes`, `h`, `hr`, `hrs`, `hour` or `hours` (lower case only, so "60 Minutes" is a title), or `m` straight after the number ("30m"; "2 m of cable" is a length) |
| `DAYS`, `DAY_WORD` | The seven weekdays; "today", "tomorrow" or a weekday, with an optional "on " before it, any case |
| `NOT_A_DAY` | `not`, `every`, `each`, `before`, `by`, `last`, `until`, `after`, `since`, `next`: a day word right after one of them sets no day ("every monday") |
| `QUOTED` | Text in straight or curly double quotes, or in single quotes that are not part of a word |
| `URL` | A text that starts with a scheme (`https://`) or `www.` |
| `Step`, `ApplySteps` | `{text (1 to 200), minutes (0 to 240)}`; `{steps (1 to 30), expect (up to 30)}` |

### 7d.2 Functions

| Function | What it does |
|---|---|
| `_clean(text)` | Empty `()` and `[]` left by a moved word go; spaces are one; a leading `:`, `;`, `,` or dash goes; no space before punctuation; the first letter is made a capital when the first word is all lower-case letters and the text is not a web address (so "iPhone" and "eBay" stay) |
| `_day(word, today)` | The ISO day: today, tomorrow, or the next such weekday ("friday" said on a Friday is a week away) |
| `_quoted`, `_inside` | The spans of quoted text; is a position inside one |
| `_minutes(m)` | Minutes from a `TIME` match (hours × 60); `None` when it is not a whole number |
| `_day_match(text)` | The first day word that sets a day: not after a `NOT_A_DAY` word, not followed by `'s` ("Friday's"), not inside quotes |
| `task(text, minutes, due, today, repeats=False)` | The first `TIME` outside quotes becomes the minutes when 1 to 600, and leaves the text. Then a day word: when the task has no day, or the same day, it becomes the day and leaves the text; a different day already set wins and the word stays. Then `_clean`. `fix` is `{text, minutes, due}`, or `None` when nothing changed or the text would be empty. Hints on the fixed text: `verb` (ASCII text whose first word is letters only and not in `VERBS`), `several` (`JOIN` splits it and a later part starts with a verb), `day` (no day, and it does not repeat), `long` (over `LONG`). There is no minutes hint: every task has minutes |
| `note(body)` | Line by line: a fenced code block (from a line starting with three backticks to the next) and indented code are kept as they are (only trailing spaces go); runs of empty lines become one; other lines keep their indent, get single spaces, and a leading `*`, `•` or `·` becomes `- ` unless the line is a rule (`* * *`, `---`). A tag line such as `#private` is untouched (`#` is not a list mark). The text keeps a final newline only when it had one. `None` when nothing changed |
| `routine(steps)` | Per step: when it has no minutes, a `TIME` in its text becomes them (1 to 240) and leaves the text; then `_clean` (the old text when nothing is left). `None` when nothing changed. Quoted text is not looked at here |
| `apply_steps(db, rid, steps, expect)` | In one transaction: the live steps in order must be exactly `expect` (409 "The routine changed since. Look at it again."); the count must be the same (409 "This changes the number of steps, so it cannot keep their ticks. Edit the routine to do it."); each changed step gets `db.update` of its text and minutes. Each step keeps its id, so `routine_checks` and the 7-day picture stay (`planner._set_steps` matches by text and would lose them) |

### 7d.3 Routes

| Method and path | Body | Returns | Side effects |
|---|---|---|---|
| `GET /api/tidy/tasks` | – | `{items}`: each open task (`done_at IS NULL`, by `ord`, at most 200) with `id`, `text`, `minutes`, `due`, `hints`, `fix` | none |
| `GET /api/tidy/note/{page_id}` | – | `{body, changed}`: the fixed body, or the body as it is | none; 404 for a bad id or a missing note |
| `GET /api/tidy/routine/{rid}` | – | `{steps, changed}` | none; 404 |
| `POST /api/tidy/routine/{rid}/apply` | `ApplySteps` | `{changed}` (the number of steps) | Changes the steps in place; 404, 409, 422 |

The page applies a task fix with `PATCH /api/todos/{id}` and a note fix with `PATCH /api/pages/{id}`, each with its own Undo.

Found by the review of 5.2, and now so (tests in `tests/test_tidy.py`): a note keeps its tags (`#private` is never made a heading), code blocks, rules and a missing final newline; day and time words inside other phrases stay ("Friday's", "not today", "every monday", quotes, "60 Minutes", "2 m"); no empty brackets are left behind; "iPhone", "eBay" and web addresses are not capitalised. **Still true:** `routine` does not skip quoted text; the verb list is English only, so other languages get no verb hint at all; `several` counts any later part that starts with a listed verb, so "Read and write" (one task to some) gets the hint.

---

## 7b. `ai/`: the LLM port, its adapters, keys, the AI log, the guardrails, prompts, kept results, the Resume briefing, Explain selection, the Document digest, Ask this document, Ask my library, Study notes, the Reading plan, Brainstorm, Organize, Tidy and Plan chat

Milestones 1.1 ("LLM port, local and cloud adapters, profiles, timeout, ai_log"), 1.2 ("Guardrails v1"), 1.2b ("Secret storage and log redaction"), 1.3 ("Resume briefing"), 1.4 ("Explain selection") and 1.5 ("Document digest with map-reduce") of `docs/ai/PLAN.md`: all of Phase 1; and of Phase 2 milestones 2.1 ("Quote and anchor verification", in `guard.py` and `tests/test_ai_citations.py`), 2.2 ("Ask this document", `ask.py`), 2.3 ("Ask my library with a bounded loop", `library.py`) and 2.4 ("Study notes writer and flashcards", `notes.py`); and all of Phase 3: milestones 3.1 ("Reading plan", `plan.py`, with the scheduler in `readhold/readplan.py`, section 2b), 3.2 ("Brainstorm (diverge then converge)", `brainstorm.py`) and 3.3 ("Organize library and related documents", `organize.py`, with the layer without a model in `readhold/organize.py`, section 7c). There are **nine AI features**: the Resume briefing (`resume.py`), Explain selection (`explain.py`), Ask this document (`ask.py`), Ask my library (`library.py`, a bounded loop of at most 3 calls), Study notes (`notes.py`), the Reading plan (`plan.py`) and Organize (`organize.py`), each with one prompt; the Document digest (`digest.py`), with two (`digest_map` and `digest`); and Brainstorm (`brainstorm.py`), with two (`brainstorm` for three sample calls and `brainstorm_critic` for one critic call). A feature calls `guard.ask`, which goes through the port, and keeps its result through `results.py`. Of Phase 4: 4.1, the evaluation harness (`readhold/eval/`); 4.2, "Why did it say this?" (`why.py`), which reads the AI log and calls no model; 4.3, the red-team suite (`tests/test_redteam.py`) and CI (`.github/workflows/ci.yml`); 4.4, the privacy controls (`privacy.py`, and changes to `guard.py`, `port.py`, `digest.py`, `library.py`, `organize.py`, `brainstorm.py` and `api.py`); 4.5, the security review (changes to `adapters.py`, `guard.py` and `port.py` here, and to the server and the importers in chapter 1). Phase 4 is done. See *The red-team suite*, *Privacy controls* and *The security review* below. Of Phase 5 ("Everyday control", added on 2026-11-26): 5.1, Delete on everything, has no model (`readhold/trash.py`, chapter 1, section 7b; an AI result is one of its kinds); 5.2, Tidy (`tidy.py`, with `readhold/tidy.py`, section 7d), and 5.3, Plan chat (`chat.py`), are the tenth and eleventh features, each with one prompt; they add `guard.Result.raw` and a `task:` branch in `privacy.owner`. Phase 5 is done. 5.4, Note chat (`notechat.py`), added on request on 2026-11-26, is the twelfth feature, with one prompt; it reuses Tidy's note check (`tidy._note`). See *Tidy*, *Plan chat* and *Note chat* below.

| File | Job |
|---|---|
| `readhold/ai/__init__.py` | Exports `Port`, `Reply`, the errors (not `ModeChanged`), `register`, `endpoint_warning`, `MAX_REPLY_BYTES` and the modules `keys`, `log`, `privacy` (since 4.4: the server calls `ai.privacy.approve` and catches `ai.privacy.PreviewNeeded`), `profiles`, `settings`. It imports `ask`, `brainstorm`, `chat`, `digest`, `explain`, `guard`, `library`, `notechat`, `notes`, `organize`, `plan`, `prompts`, `results`, `resume` and `tidy` too, so `ai.guard` and `ai.results` work, but they are not in `__all__`. Its docstring says "Twelve features exist", names each with its module (`notechat.py` last) and says the log keeps 1, 7 or 30 days; its file list has `resume.py` but none of the later feature modules, nor `results.py` or `privacy.py` |
| `readhold/ai/port.py` | The port and its limits |
| `readhold/ai/adapters.py` | One class per kind of server, `send()`, `open_client()`. **The only file in `readhold/` that imports a network client** |
| `readhold/ai/profiles.py`, `profiles.json` | Per-task profiles |
| `readhold/ai/keys.py` | API keys in the OS credential store |
| `readhold/ai/settings.py` | The `ai_…` settings and their checks |
| `readhold/ai/log.py` | The table `ai_log` |
| `readhold/ai/api.py` | The `/api/ai/…` routes |
| `readhold/ai/guard.py` | The guardrails (milestone 1.2): what reaches a model and what comes back from one; the citation check of milestone 2.1; since 4.4 and 4.5 the private step, the send preview's hook and `leaves` |
| `readhold/ai/privacy.py` | Milestone 4.4: which items never leave this computer (`#private`, or with `ai_cloud_only_tagged` anything not `#cloud`), copies of them in the reader's own text, and the send preview (`PreviewNeeded`, `approve`, `gate`). No route of its own. See *Privacy controls* below |
| `readhold/ai/prompts.py`, `prompts/resume_v1.md`, `prompts/explain_v1.md`, `prompts/digest_map_v1.md`, `prompts/digest_v1.md`, `prompts/ask_v1.md`, `prompts/library_v1.md`, `prompts/notes_v1.md`, `prompts/plan_v1.md`, and the later `brainstorm_v1.md`, `brainstorm_critic_v1.md`, `organize_v1.md`, `tidy_v1.md`, `tidy_v2.md` (in use since 2026-11-26), `chat_v1.md` and `notechat_v1.md` | The prompt registry: one file per version, the highest version in use |
| `readhold/ai/results.py` | The table `ai_results`, shared by every feature: the `input_key`, find, keep, one call (or one saved note) for two simultaneous requests, hiding a deleted document's results, clearing everything |
| `readhold/ai/resume.py` | Milestone 1.3, the first feature: the facts of the last reading session, and a recap from a model on request. Its two routes, and `status_error` (the HTTP status of a failed AI call) |
| `readhold/ai/explain.py` | Milestone 1.4: a plain explanation of a passage the reader selected, at a level they choose, and "Save as a note". Its two routes |
| `readhold/ai/digest.py` | Milestone 1.5: the facts of a document (outline, words, reading time) without a model, and on request a digest by map-reduce in a background job (parts at section boundaries, one call per part, then one combining call), with progress and Stop. Its three routes |
| `readhold/ai/ask.py` | Milestone 2.2: a question about the document being read. The passages that match, without a model; on request an answer from the best-matching sections only, with checked quotes, or "not found". Its two routes |
| `readhold/ai/library.py` | Milestone 2.3: a question across every document and note. The passages and notes that match, without a model; on request a bounded loop of at most 3 calls with two read-only tools (`search`, `read`), checked quotes from documents and notes, or "not found in your library"; Stop. Its three routes |
| `readhold/ai/notes.py` | Milestone 2.4: study notes, flashcards or a short quiz drafted from the reader's highlights or one section, each item resting on a quote checked against the text as sent; nothing is saved until the reader keeps items, which go to a labelled note or to Review as `ai` cards, once. Its two routes |
| `readhold/ai/plan.py` | Milestone 3.1: on request, a model suggests the order of the documents of a reading plan and a level for each, with one reason each resting on a checked quote or labelled a guess. It never schedules and changes nothing: the reader uses the suggestion or not, and `readhold/readplan.py` (section 2b) makes the schedule. Its one route |
| `readhold/ai/brainstorm.py` | Milestone 3.2: on request, ideas for a note, an idea or a document. Three sample calls from three angles (diverge), then one critic call that groups and ranks them (converge), its numbers checked by code; each idea rests on its own checked quotes; since 2026-11-26 the checked ideas go straight into the brainstorm sheet when the reader asks, each as its own section, with Undo. Its four routes |
| `readhold/ai/organize.py` | Milestone 3.3: on request, a model suggests tags for a document (the reader's own first, at most two new) and related documents from the list `readhold/organize.py` (section 7c) found, each checked; nothing changes until the reader adds a tag. Its one route |
| `readhold/ai/tidy.py` | Milestone 5.2: on request, a model proposes a rewrite of the reader's open tasks (with splits, minutes and days), one note or one routine; every number, day and length is checked, every new word listed, and in a note the reader's own links, tags and properties are kept and the model's made plain. Nothing is applied here. Its one route |
| `readhold/ai/chat.py` | Milestone 5.3: Plan chat. On request, a model drafts at most 12 tasks from what the reader types, given the next 14 days with their free minutes, the open tasks and the reading deadlines; every draft is checked; only the reader's click adds them (`add`, a batch per click), and `undo` takes a click back. Its three routes |
| `readhold/ai/notechat.py` | Milestone 5.4: Note chat. On request, a model reads the note you are in and what you type, replies, and proposes the whole note rewritten (`replace`, checked by `tidy._note`) or text for its end (`add`), or nothing (`none`). It changes nothing: the page writes the note on Use or Add. Its one route |
| `readhold/ai/why.py` | Milestone 4.2: "Why did it say this?". For a kept result, every model call behind it from `ai_log`, the sources each was sent (named, never their text), the checks the guards ran, and each prompt word for word. It calls no model. Its one route. See *"Why did it say this?"* below |
| `readhold/redact.py` | Removes secrets from text that is written to a log, and from text that is sent to a cloud model |
| `readhold/eval/` | Milestone 4.1, outside the AI package: the evaluation harness, `uv run python -m readhold.eval`. It runs the twelve features (Tidy, Plan chat and Note chat since 2026-11-26) over a fixed sample set in a throwaway Readhold folder, through their own routes, and prints one table of scores. See *The evaluation harness* below |

Call direction: `api -> resume, explain, digest, ask, library, notes, plan, brainstorm, organize -> guard, results -> port -> adapters, keys, profiles, log -> redact, db, config`. `brainstorm` imports `pages`, `think` (the non-AI sheet's data, `corpus`, `_vector`, `_alike`, `words`), `guard`, `prompts`, `results`, `Run` from `library`, `OURS`, `_inert`, `_link`, `_note_line`, `_own_words`, `_same_title` and `_highlights` from `notes`, the port's error types and `status_error` from `resume`. `organize` (the AI one) imports `readhold/organize.py` (as `plain`), `guard`, `prompts`, `results`, `_own_words` from `notes`, the port's error types and `status_error` from `resume`; `readhold/organize.py` imports only `think` and `db`, nothing from `ai`. `ask` imports `passages`, `think.STOP`, `guard`, `prompts`, `results`, the port's error types and `status_error` from `resume`. `library` imports `passages`, `db`, `guard`, `prompts`, `results`, `_question`, `_terms`, `_cache_question`, `_around`, `Citation` and `Invalid` from `ask`, the port's error types and `status_error` from `resume`. `notes` imports `pages` and `services` (to keep what the reader accepts), `guard`, `prompts`, `results`, `_around` from `ask`, the port's error types and `status_error` from `resume`. `plan` imports `readplan` (what is left of a document, minutes, levels), `guard`, `prompts`, `results`, `_own_words` from `notes`, the port's error types and `status_error` from `resume`; `readplan` imports nothing from `ai`. `resume` imports `passages`, `guard`, `prompts`, `results` and the port's error types; `explain` imports `guard`, `prompts`, `results`, the port's error types and `status_error` from `resume`; `digest` imports `guard`, `prompts`, `results`, `db` and the port's error types (and starts its own threads); `results` imports only `db`; `guard` imports `port`, `adapters` (only `leaves_computer`), `privacy`, `redact` and `db`; `privacy` imports `pages` (its `TAG` pattern) and `db`, and `guard._plain` inside a function (the two import each other). `digest`, `library` and `organize` import `privacy` too. `why` imports only `db` and `prompts` (no port, no `guard`): it reads, and calls no model. `tidy` (the AI one) imports `pages`, `think`, `readhold/tidy.py` (as `plain`), `guard`, `prompts`, `results`, `_inert` from `notes`, the port's error types and `status_error` from `resume`; `readhold/tidy.py` imports only `db`. `chat` imports `readhold/tidy.py` (as `plain`, for `_day`, `DAYS` and `MAX_MINUTES`), `db`, `guard`, `privacy`, `prompts`, `results`, the port's error types, `status_error` from `resume`, and `readplan` inside `undo`. `server.py` calls `ai.guard.flag_document` after an import and `ai.results.forget_document` when a document is deleted. Nothing outside the package imports `adapters`. The document store (`store.py`, `passages.py`) imports nothing from `ai`.

### The port: `Port` (`port.py`)

`server.create_app` calls `ai.register(app, db, settings_dict)`, which makes one `Port(db, settings)` and keeps it at `app.state.ai`. `settings` is the function `settings_dict`: the port calls it on every call, so **switching between off, local and cloud is only a settings change**.

```python
reply = port.complete("explain", system, user)             # reply.text
reply = port.complete("digest", system, user, schema=M)    # reply.data: checked against the pydantic model M
```

`complete(task, system, user, schema=None, *, call_id=None, prompt_version="", expect_mode=None) -> Reply` blocks until the answer, an `AIError`, the timeout or a cancel. `expect_mode` (milestone 4.4) is the mode the text was prepared for; `guard.ask` passes it. Call it from a worker thread (a plain `def` route), never from the server's event loop. `Reply` holds `text`, `data` (the checked JSON as a dict, or `None`), `log_id`, `provider`, `model`, `latency_ms`, `tokens_in`, `tokens_out` and `warning` (set when the day's budget is 80% used). `prompt_version` (at most 80 characters) is written to `ai_log.prompt_version` and changes nothing else.

What happens in a call, in order:

1. **Off means off.** If `ai_mode` is not `local` or `cloud`, `AIOff` is raised at once: before the worker thread, an HTTP client or a socket exists, and without a log row. **Same mode as packed** (4.4): with `expect_mode` given and `ai_mode` now another value, `ModeChanged` is raised, also without a log row: text packed for a local model (no private rules, no redaction) never goes to a cloud one. Only the mode is compared, not the endpoint (see *Privacy controls*, limits).
2. **Profile.** `profiles.load()[task]`; an unknown task is a `ValueError` (a programming error).
3. The rest runs as a coroutine on the port's own event loop (one daemon thread named `readhold-ai`, started on the first call). The call is registered under its `call_id` so it can be cancelled.
4. **Text that leaves this computer: secrets out.** When `adapters.leaves_computer(settings)` is true (cloud mode, or since 4.5 a "local" endpoint that is not on this computer), `_call` first runs `redact.scrub_all` on the system text and on the user text and notes the number of replacements as `secrets_redacted` in the row's checks. Everything after this step (the hash and the preview in the log, the input cap, the request) sees only the cleaned text. This is the last gate: a feature that skips `guard.pack` still sends no key-shaped text, e-mail address or phone number off this computer. With a model server on this computer the text is sent as it is.
5. **Budget.** `log.tokens_today(db, provider)` against `ai_budget_local` or `ai_budget_cloud`. At or over the budget: `BudgetReached`, no request.
6. **Model.** The profile says `small` or `strong`. Local: `ai_local_small_model` (for `small`) or else `ai_local_model`. Cloud: `ai_cloud_small_model` or `ai_cloud_model`, or else `adapters.CLOUD_DEFAULTS[provider][size]` (Anthropic: `claude-opus-5-5` and `claude-haiku-5-5`; OpenAI: none). No model: `NotSetUp`.
7. **Input cap.** More than `MAX_INPUT_CHARS` (400,000) characters: `TooLong`. A feature's own budget is far below this (`guard.BUDGETS`).
8. **Adapter.** Local: `adapters.local(ai_local_api, ai_local_endpoint)`. Cloud: the key from `keys.get(provider)`; without one `NoKey` is raised and the cloud adapter is never built.
9. **At most 2 at once.** An `asyncio.Semaphore(MAX_AT_ONCE)`; a third call waits its turn.
10. **The request**, inside `asyncio.timeout(ai_timeout_s)` (the HTTP client has the same timeout). A new `httpx.AsyncClient` per call: `follow_redirects=False`, `trust_env=False` (no proxy, certificate file or credential from the environment).
11. **At most one retry**, after `retry_wait` (0.5 s): when the server answers 429 or 5xx, the connection breaks, the reply is not JSON, the answer is empty, or the answer fails its schema. Never after a timeout, a refused key (401/403), an unknown model (404), another 4xx, or a server that is not running.
12. **Output cap.** The profile's `max_output_tokens` is sent to the provider. The port then cuts the text at `max_output_tokens * CHARS_PER_TOKEN` (8) characters and notes `truncated` in the row's checks. A reply body over `MAX_REPLY_BYTES` (2 MB) is dropped while it is being read.
13. **The key cannot come back in.** `redact.strip_known` removes the app's own keys from the answer, in case a server repeats one.
14. **Schema.** With `schema` (a pydantic model class), the JSON object in the answer (a code fence or words around it are dropped) is validated with `model_validate_json`. Ollama also gets the JSON schema as `format`. A failure after the retry is `CouldNotGenerate`.
15. **Log.** One row in `ai_log`, whatever the outcome (except `AIOff` and an unknown task).

`cancel(call_id)` cancels the call's task from any thread; the request is closed and the caller gets `Cancelled`. `cancel_all()` does it for every running call. `settings_changed()` is called by `PUT /api/settings` (after a request that held an `ai_…` key) and calls `cancel_all()` when the mode is now off, or, since 4.4, when it switched between local and cloud (it remembers the last mode in `_mode`): **the kill switch stops running calls too**, and so does a mode switch, since what runs was prepared for the other mode. A change of the endpoint alone cancels nothing.

`status()` is what Settings shows: `mode`, `provider`, `model`, `cloud_provider`, `key_set`, `ready`, `problem` (a sentence), `warning` (from `endpoint_warning`), `usage` (`{used, budget, state: ok | warn | stop}`) and `logged` (rows in the log). It never contains a key.

Errors are subclasses of `AIError`, each with a `code` and a `message` a page can show:

| Class | `code` | When |
|---|---|---|
| `AIOff` | `off` | `ai_mode` is `off` |
| `NotSetUp` | `setup` | No model is chosen |
| `NoKey` | `no_key` | Cloud mode without a stored key (also when the credential store cannot be read) |
| `BudgetReached` | `budget` | The provider's daily budget is used up |
| `TooLong` | `too_long` | The input is over the hard cap |
| `TimedOut` | `timeout` | The call took longer than `ai_timeout_s` |
| `Cancelled` | `cancelled` | `cancel`, or AI was switched off or to the other mode |
| `ModeChanged` | `changed` | Since 4.4: the mode changed between packing and sending (`expect_mode`). "The AI mode changed while this was being prepared. Nothing was sent; try again." `status_error` answers 409 |
| `CouldNotGenerate` | `invalid` | Empty or schema-failing answer, also after the retry |
| `ProviderError` | `offline`, `auth`, `model`, `busy`, `refused`, `bad_reply`, `error` | The server did not answer, refused the key, does not know the model, is failing, declined the request, sent something unreadable, or returned another error |

The messages are fixed sentences. What a server said in an error goes only to the log (cleaned), never to the page.

**`AIError.log_id`** (milestone 4.2) is the id of the `ai_log` row of the failed call, or `""` when no row was written. `fail(outcome, error, detail)` inside `_call` writes the row and sets it for every refusal and failure after the settings are read (`budget`, `setup`, `too_long`, `no_key`, `timeout`, the provider errors, `invalid`). The cancel path sets it on the `Cancelled` it raises (outcome `cancelled`). `AIOff` raised before the call has none. A feature can then list a failed call with its outcome ("Why did it say this?").

### The adapters (`adapters.py`)

An adapter has `provider`, `request(ask) -> (url, headers, body)` and `read(data) -> Answer`. `Ask` is the provider-free request: `model`, `system`, `user`, `params` (the profile's values) and `schema`. `_pick` keeps only the parameters a provider takes and renames them: **a parameter a provider does not support is dropped**.

| Class | Server | Request | Parameters sent |
|---|---|---|---|
| `Ollama` | A local Ollama server | `POST <endpoint>/api/chat`, `stream: false` | `options`: `temperature`, `top_p`, `min_p`, `num_predict`; `format` = the JSON schema when one is given |
| `OpenAICompatible` | llama.cpp, LM Studio, vLLM, Ollama under `/v1` | `POST <endpoint>/chat/completions` (`/v1` is added when the endpoint has no path), `stream: false` | `temperature`, `top_p`, `max_tokens` |
| `Anthropic` | `https://api.anthropic.com/v1/messages`, headers `x-api-key` and `anthropic-version: 2023-06-01` | `system` at the top level | `max_tokens` only, never below 1024. No `temperature`, `top_p` or `top_k`: current Claude models answer 400 to them. These models think before they answer and the thinking counts as output, which is why `max_tokens` has a floor; the port's character cap still holds the answer to the profile's length. `stop_reason: "refusal"` becomes `ProviderError("refused")` |
| `OpenAI` | `https://api.openai.com/v1/chat/completions`, header `authorization: Bearer …` | | `max_completion_tokens`; `temperature` and `top_p` unless the model name starts with `o1`, `o3`, `o4` or `gpt-5` (reasoning models take none) |

No adapter sends `tools`. The cloud addresses are constants in the code; only the local endpoint is a setting.

`send(client, adapter, ask)` posts the request as a stream and reads at most `MAX_REPLY_BYTES`. Status 200 is parsed; 401/403 is `auth`, 404 `model`, 429 and 5xx `busy` (retried once), any other status (a redirect too) `error`. Token counts are read from the reply (`prompt_eval_count`/`eval_count`, `usage.prompt_tokens`/`completion_tokens`, `usage.input_tokens` plus the cache counts / `output_tokens`); when a server gives none, the port estimates a quarter of the characters and notes `tokens_estimated`.

`is_local(url) -> bool` (exact since 4.5, finding L1): the URL's host, in lower case, is `localhost`, `127.0.0.1` or `::1` (`LOCAL_HOSTS`), or an IP address written as a number that `ipaddress` calls loopback (any `127.…`, `[::1]`). A name is never parsed as a number: `127.evil.example`, `127.0.0.1.nip.io` and `localhost.evil.example` are other computers, and so is `10.0.0.2`. A URL that cannot be split is not local.

`leaves_computer(settings) -> bool` (4.5, finding M1): true in cloud mode, and in local mode when `ai_local_endpoint` is not `is_local`. The port (its scrub, step 4 above) and `guard.leaves` use it, so a "local" server on another computer gets every rule of text that leaves this computer.

`endpoint_warning(url)`: empty when `is_local(url)`. Otherwise "This model server is not on this computer: text you send to it leaves this computer.", with a second sentence when the address is not HTTPS. It is a warning, not a block (plan 6.4); `status()` carries it and Settings shows it. Since 4.5 the rules of a cloud call apply to such a server as well.

The cloud adapter is written with plain `httpx` requests, not a provider's SDK, on purpose: there is one network client in the app and one place to cap, time and mock it, and an SDK would read keys and proxies from the environment.

### Profiles (`profiles.py`)

`profiles.json` holds the defaults of section 7 of the plan:

| Task | Model | Temperature | Top-p | Max output tokens |
|---|---|---|---|---|
| `test` | small | 0 | 1.0 | 32 |
| `resume` | small | 0.2 | 0.9 | 700 |
| `explain` | strong | 0.4 | 0.95 | 900 |
| `digest` | strong | 0.2 | 0.9 | 900 |
| `digest_map` | small | 0.2 | 0.9 | 500 |
| `ask` | strong | 0 | 1.0 | 800 |
| `notes` | strong | 0.5 | 0.95 | 1200 |
| `plan` | strong | 0.3 | 0.95 | 1000 |
| `brainstorm` | strong | 1.0 | 1.0 | 500 (and `min_p` 0.05, which only Ollama takes) |
| `brainstorm_critic` | strong | 0 | 1.0 | 800 |
| `organize` | small | 0.2 | 0.9 | 300 |

The token caps are this milestone's own choice; the plan gives none. `load()` returns the defaults with the user's changes on top. `save(changes)` checks them (`check`: known tasks and fields only, `temperature` 0 to 2, `top_p` and `min_p` 0 to 1, `max_output_tokens` 16 to 8192, `model` `small` or `strong`), keeps only what differs from the defaults, and writes `data/ai_profiles.json` through a temporary file; an empty object deletes the file. A damaged file falls back to the defaults. Profiles can be changed through `PUT /api/ai/profiles` or the file; the Settings page has no table for them yet.

### Keys (`keys.py`) and redaction (`redact.py`)

A key is stored with `keyring.set_password("Readhold", "ai-key:<provider>", key)`: on Windows, the Credential Manager. `PROVIDERS` is `("anthropic", "openai")`. `tidy` trims a pasted key and refuses anything that is not 12 to 500 printable ASCII characters without spaces. `get` returns the key or `None`; a credential store that cannot be read counts as no key. `save` and `get` also call `redact.remember(key)`.

A key is never written to the database, a settings row, a config file, a log or an API response. Three things keep that true:

- `ai.settings.check` refuses any `ai_…` string that `redact.looks_like_key`, so a key pasted into the model or endpoint box answers 422 and is not stored. An endpoint may not hold a user name, a password or a `?query` either. Since 4.5 `PUT /api/settings` refuses a key-shaped string in any setting, not only the `ai_…` ones, before anything is stored, and a 422 of a failed body never echoes the input (chapter 1, sections 4.2b and 4.4).
- `redact.clean(text)` replaces with `[redacted]`: every key the app has handled in this run (kept in memory only), key-shaped strings (`sk-…`, `ghp_…`, `xox…`, `AIza…`, `AKIA…`, `hf_…`, `Bearer …`, `Basic …`, private-key blocks), and the value (8 characters or more, up to a space, a quote, a comma, `;` or `&`) after one of the names `api_key`, `x-api-key`, `authorization`, `access_token`, `auth_token`, `secret`, `password` or `passwd` followed by `:` or `=`. The name stays. A bare `token = …` is not such a name; its value goes only when it has a key shape. The log file's formatter and the previews and errors of `ai_log` go through it.
- `redact.strip_known(text)` removes only the app's own keys. It is used on a model's answer, where text that merely looks like a key (in a code file, say) must stay.

Two more functions (milestone 1.2) are for text that is about to be sent, not logged. Both return `(text, count)`:

- `redact.scrub(text)` does what `clean` does and counts the replacements.
- `redact.scrub_all(text)` runs `scrub` and then also replaces JWTs (`eyJ….….…`), e-mail addresses and phone numbers. A phone number is one of three shapes: `+` and a digit, 7 to 15 more digits, spaces or dashes, and a last digit (`+20 100 123 4567`); an area code of 2 to 4 digits in brackets and two groups of 3 to 4 digits (`(555) 123-4567`); or `555-123-4567` (3, 3 and 4 digits with dashes). It must not touch a letter, a digit or a full stop on either side, or a dash behind it. Plain groups of digits are numbers and stay. `Port._call` (cloud mode) and `guard.redact_secrets` call it. Nothing else does: the log file and the AI log keep e-mail addresses and phone numbers, and a local model gets the text unchanged.

Limits of the patterns, measured on 2026-11-25. They are rules, not a scanner: a secret with no known shape and no known name in front of it passes. A phone number without a `+`, brackets or the `555-123-4567` shape passes: `555 123 4567`, `555.123.4567`, `0100 123 4567`. `the secret: understanding` loses the word after the colon. `basic` or `bearer` followed by a run of 16 or more letters, digits and dashes is taken for a credential, in prose too. `git@github.com:user/repo.git` loses its first part as an e-mail address. No longer limits: `(555) 123-4567` is matched, `Authorization: Basic <base64>` is redacted, and groups of digits that are not a phone number stay (`10 000 000`, `512 1024 2048`, `pages 100-200-300`, `2019-2020`).

### The AI log (`log.py`, migration `0016_ai_log.sql`)

| Column | Holds |
|---|---|
| `id`, `device_id`, `created_at`, `updated_at`, `deleted` | The project's record columns |
| `task` | The task or feature name |
| `provider`, `model` | `local`, `anthropic` or `openai`, and the model's name |
| `prompt_version` | The version of the prompt a feature used, such as `resume_v1` (`prompts.py`). Empty for Test connection and for a caller that names none |
| `input_hash` | SHA-256 of the system and user text |
| `input_preview`, `output_preview` | The first 200 characters on one line, through `redact.clean` |
| `latency_ms`, `tokens_in`, `tokens_out`, `attempts` | Measured; `attempts` is 1, or 2 after the retry |
| `checks` | JSON. From the port: `schema` (true/false), `truncated`, `tokens_estimated`, and in cloud mode `secrets_redacted` (a count). `guard.ask` adds its own after the call: `fenced` (number of sources), `trimmed`, `left_out` (only when sources were left out of the budget), `flagged` (the kinds of order-like text in what was sent), `links_removed`, and in cloud mode its own `secrets_redacted`, which replaces the port's, and (since 4.4, only when some were) `private_left_out`. "Cloud mode" here means any call that leaves this computer (since 4.5). Since 4.2 also `sources` (a list of `{anchor, trust, chars, cut}`, one per source sent, at most 60) and `sources_more` (how many more were sent). Never a source's text. The guard's checks are merged after the call; a failed call whose error names its row (`AIError.log_id`) gets the packing checks too, all but `links_removed` |
| `outcome` | `ok`, `invalid`, `timeout`, `cancelled`, `error`, `budget`, `no_key`, `setup` |
| `error` | A short reason, cleaned, at most 300 characters |

- **Retention.** `purge` deletes rows older than `days(db)`: the setting `ai_log_days` (1, 7 or 30, milestone 4.4), else `RETENTION_DAYS` (30). It runs when the app starts, at most once an hour when a row is written, and after every `PUT /api/settings` that held an `ai_…` key, so a shorter time deletes at once. It also deletes cleared rows from before today.
- **Clear AI history** (`clear`, `DELETE /api/ai/log`): every row from before today is deleted. Today's rows lose their hash, previews, error and checks (the list of sources with them) and get `deleted=1`; only their token counts stay, so clearing does not hand the day's budget back. `purge` removes them the next day. The same route then calls `results.clear_all`, which deletes every row of `ai_results` (the kept recaps and explanations; see *Kept results* below).
- **Not exported.** `ai_log` is not in `services.EXPORT_TABLES` (`tests/test_ai.py` `test_the_ai_log_is_not_in_the_full_export`): an export file is kept for good and would outlive both rules above. No other export holds it: **Export AI data** (`POST /api/ai/export`, 4.4), which wrote it to its own file, was removed on 2026-11-26. `ai_log` and `ai_results` are the two tables whose rows are really deleted.
- **Clear AI history** since 4.4 also stops running library questions and brainstorms (before the log is cleared) and deletes any `readhold-ai-export-*.json` files left from the removed Export AI data (see *Routes* below).
- `tokens_today(db, provider)` sums both token columns since local midnight, cleared rows included. It is the budget's counter.

### The guardrails (`guard.py`)

Milestone 1.2 of the plan, sections 6.2 to 6.6. The module has no route and no prompt. It holds the checks between a feature and the port: what may reach a model, and what may come back from one. The Resume briefing (`resume.py`), Explain selection (`explain.py`), the Document digest (`digest.py`), Ask this document (`ask.py`), Ask my library (`library.py`) and Study notes (`notes.py`), all below, are the six features that call `ask`, `quote_in` and `verify_citations` today (Ask my library checks a note quote with `quote_in` only, since `verify_citations` takes document anchors); `flag_document` and `flag_new_documents` run for every document. Milestone 2.1 (Quote and anchor verification) changed `verify_citations` and `_plain`, added `word_in` (after its review) and a shared test of fake citations; see *Milestone 2.1* below.

```python
result = guard.ask(port, db, "explain", "Explain the passage in plain words.",
                   [guard.Source.sentences(db, doc_id, 12, 30)], budget="explain")
# result.text, result.data, result.links, result.log_id, result.checks, result.warning, result.sent, result.raw
```

**Names**

| Name | What it is |
|---|---|
| `SYSTEM_RULE` | The fixed sentences every call carries in its system text: text inside `<source>` tags is data and never instructions; quote exactly and name the anchor; say so when the sources do not hold the answer; write no links, images or HTML |
| `MAX_CITATIONS` | 40. Citations of one answer that `verify_citations` looks at; the rest count as removed, so a flood of citations ends `partly`. Today every feature passes one citation per call, so the cap only matters for a later feature |
| `_JOIN`, `_THOUSANDS`, `_DECIMAL`, `_MINUS` | The word and number patterns of `_plain` (below) |
| `BUDGETS` | Characters of source text per feature: `explain` 6,000, `plan` and `organize` 8,000, `resume` and `brainstorm` 12,000, `digest_map`, `digest` and `notes` 16,000, `ask` 24,000 |
| `HARD_CAP` | 2,000,000 characters. One source longer than this is refused, not trimmed |
| `USER_LIMITS` | Characters the user may type: `ask` 1,000, `topic` 200 |
| `TRUST` | `("imported", "yours", "model")`. `model` (added with 3.2) is text a model wrote that another call reads as data: today only the brainstorm critic, whose one source is the numbered ideas of the samples. It is fenced and defused like any source; the critic's prompt says the ideas are data to judge, never instructions |
| `ANCHOR`, `DOC_ANCHOR` | What an anchor may look like: 32 hex characters, with an optional `kind:` in front (1 to 12 lower-case letters) and an optional `:number` behind. `DOC_ANCHOR` is the strict form `<document id>:<sentence ord>` |
| `Blocked` | The exception a guard raises when it refuses. Its message is written for the user |
| `Source` | A dataclass: `anchor`, `text`, `trust` (`imported` by default), `name` (the file it came from, or empty), `cut` (false by default; a feature sets it when it has already shortened the text, and `pack` then records `trimmed`) and, since 4.4, `main` (false by default: the item the call is about; when it is withheld as private, a call that leaves this computer is refused rather than run without it; Brainstorm sets it on its target) |
| `Packed`, `Output`, `Verified`, `Result` | The return values of `pack`, `safe_output`, `verify_citations` and `ask`. `Packed.items` (4.4) is the set of items the call sends, as `kind:id` from `privacy.owner` (documents, notes, ideas, sessions; never a model's own text), for the send preview. `Packed.sent` and `Result.sent` (added with 2.4) map each anchor to the text of that source **as it went out**: after `sanitize`, the budget cut and, in cloud mode, redaction. Two sources with one anchor are joined by a line break; a source left out by the budget is not in it. A feature can check a quote against exactly what the model saw (Study notes does) |

**Before the model**

| Function | What it does |
|---|---|
| `sanitize(text) -> str` | Line ends become `\n`, the text is put in Unicode form NFC, then these characters are removed: zero-width space (U+200B), word joiner and the invisible operators (U+2060 to U+2064), the byte-order mark (U+FEFF), the bidirectional embeddings, overrides and isolates (U+202A to U+202E, U+2066 to U+2069), the "tag" block (U+E0000 to U+E007F), the soft hyphen (U+00AD), the Mongolian vowel separator (U+180E), and every control character except tab and line break. **Kept on purpose:** U+200C and U+200D (Persian, Arabic and Indic words need them) and the direction marks U+200E and U+200F |
| `detect(text) -> list[str]` | The names of the `_ORDERS` patterns found in the sanitised text. The joiners and direction marks that `sanitize` keeps (U+200C to U+200F, `_JOINERS`) are taken out of the copy that is checked, so `ig` + U+200C + `nore` is still "ignore". It removes nothing from the text itself |
| `flag_document(db, doc_id) -> set[str]` | Starts from `documents.import_flags`, adds `instructions` when `detect` finds anything in any paragraph (the paragraph's sentences joined by spaces), and stores the result in `documents.flags` as words in alphabetical order with a space between them. `updated_at` is not touched: the flags are a mark about the file, not an edit by the user. Returns the set; an unknown id returns an empty set |
| `flag_new_documents(db) -> int` | Runs `flag_document` on every live document whose `flags` is NULL and returns how many there were |
| `Source.sentences(db, doc_id, first, last) -> Source` | Sentences `first` to `last` of a document, joined by line breaks, with the anchor `<doc_id>:<first>`, trust `imported` and `name` = `documents.source`. `Blocked("That passage is not in your library.")` when the document is deleted or the range is empty |
| `sensitive_name(name) -> bool` | True for a file name that holds secrets by its nature: `.env`, `.env.*`, `*.env`; `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519` (alone or with anything after a dot: `.pub`, `.bak`); `*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.kdbx`, `*.keystore`, `*.jks`, `*.tfvars`; `.npmrc`, `.pypirc`, `.netrc`, `.htpasswd`; `authorized_keys`. Also any name that holds a secret word (`_SECRET_WORD`: `secret`, `credential`, `passwd`, `password`, `private_key`, `api_key`, `token`, with or without a final `s`, with `_`, `-` or nothing inside `private_key` and `api_key`) that does not touch another letter: `my-secrets.yaml`, `aws_credentials`, `api_keys.json`, but not `tokenizer.py`. A secret word does not count when the file is prose (`_PROSE`: `.md`, `.markdown`, `.txt`, `.text`, `.rst`, `.pdf`): `secrets.md` is writing about secrets. Only the last part of a path is looked at, without regard to case |
| `redact_secrets(text) -> (text, count)` | `redact.scrub_all` |
| `user_text(text, kind="ask") -> str` | Sanitises what the user typed, turns every run of whitespace into one space, and raises `Blocked` when it is longer than `USER_LIMITS[kind]` |
| `pack(db, sources, budget, question=None, cloud=False) -> Packed` | See below. `cloud=True` means "the text leaves this computer" (`leaves`) |
| `leaves(port) -> bool` | Since 4.5: `adapters.leaves_computer(port.settings())`. A cloud model, or a "local" server on another computer. Every rule of a cloud call follows it, decided by where the text goes, not by the mode's name |
| `preview(port, db, task, instruction, sources, budget) -> None` | Since 4.4: for a feature that calls the model in the background (the digest). When `leaves(port)` and `ai_preview` are true, it packs the sources as for a cloud call and asks `privacy.gate`, which raises `PreviewNeeded` unless this request was approved for that text |

The `_ORDERS` patterns, all case-blind:

| Name | Matches |
|---|---|
| `ignore` | *ignore*, *disregard*, *forget* or *override*, then within 40 characters *previous*, *prior*, *above*, *earlier* or *all*, then within 30 characters *instruction(s)*, *prompt(s)*, *direction(s)* or *guideline(s)*; no full stop or line break in between |
| `ignore_yours` | *ignore*, *disregard*, *forget* or *override*, optionally *all* (*of*), then *your*, optionally *previous*, *prior* or *earlier*, then *instruction(s)*, *rule(s)*, *prompt(s)*, *guideline(s)* or *training* |
| `ignore_above` | *ignore* or *disregard*, optionally *everything* or *all*, optionally *the*, then *above*, *previous* or *prior*, followed by *instruction(s)*, *text*, *message(s)*, *and*, one of `. , : ; !` or the end of the line |
| `forget_told` | *forget* *everything* or *all*, then "you were told", "you have been told", *above* or *before* |
| `you_are_now` | "you are now" followed by *a*, *an*, *the*, "in (one word) mode", *dan*, *free*, "no longer", *my*, *unrestricted* or *jailbroken* |
| `system_prompt` | *your* or *my*, then *system*, *developer*, *hidden* or *initial*, then *prompt*, *message* or *instructions*; or "system prompt:" |
| `new_instructions` | "new instruction(s):" |
| `hide_from_user` | "do not tell / inform / mention (this) to / reveal (this) to the user" |
| `act_as` | *act*, *behave* or *respond* "as" (the, a, an) *system*, *developer* or *dan* |
| `reveal` | *reveal*, *print*, *repeat* or *show* (me), then *your* or "the system / hidden / initial", then *prompt*, *instructions* or *rules* |
| `fake_tag` | A whole tag, opening or closing, named `system`, `assistant` or `instruction(s)`: `<system>`, `</assistant>`, `< /instructions >`. A tag with attributes, and `<source …>`, are not matched |

`pack` step by step:

1. `limit = BUDGETS[budget]`. An unknown budget name is a `KeyError` (a programming error). Then, only with `cloud=True`, **private items** (4.4): `privacy.withheld(db, anchor, text, trust, strict)` is asked about every source (`strict` = `only_tagged`, read once). When every source is withheld, or one with `main` is, `Blocked(privacy.refusal(db))` ends the call. Otherwise the withheld ones are dropped before anything else, and their number goes into `checks["private_left_out"]` (only when above 0). `fenced` then counts what is left.
2. Every source is checked first: longer than `HARD_CAP` raises `Blocked("That text is too long to send to a model.")`. With `cloud=True`, a source whose `name` is a `sensitive_name` raises `Blocked`: the file "is never sent to a cloud model; use a local model for it". A local call may read such a file.
3. Every source is `sanitize`d, and `_shares(sizes, limit)` decides how many characters each may keep. The budget is a total. When all of them together fit, nothing is cut. Otherwise the sources are taken shortest first, each given `left // <sources still to place>` (where `left` starts at `limit` and loses what each placed source keeps), so the shorter ones stay whole and the longer ones share what is left equally (water-filling). With more sources than the budget can hold at `MIN_SHARE` (40) characters each, the first `limit // 40` get 40 and the rest get 0.
4. Per source: with a room of 0 the source is left out (`checks["trimmed"] = True`, and `checks["left_out"]` counts such sources). Otherwise, when the text is longer than its room it is cut there, at its end: the last cut word is dropped and ` […]` is added (`checks["trimmed"] = True`). `detect` runs on what is left; with `cloud=True`, `redact_secrets` runs on it. So a short source is never cut because a long one is beside it, and a feature that already fitted its sources to the budget (Ask's `sources_for`, section 7b) gets them sent as it built them.
5. `_fence` writes the source as

   ```
   <source anchor="<anchor>" trust="imported|yours|model">
   …text…
   </source>
   ```

   An anchor that does not match `ANCHOR` is written as `unknown`, and a trust that is not in `TRUST` as `imported`. **A source cannot close its own fence** (`_defuse`): in the text, a `<` is written as `&lt;` when the letters among the 39 characters after it, read without regard to case and without anything that is not a letter (spaces, slashes, the kept invisible joiners), start with `source`, `question`, `system` or `assistant`. So `</source>`, `</ SOURCE >` and `<` + U+200C + `/source>` all lose their `<`. The words stay readable; they are no longer a tag. Any other `<` stays, so `a < b` and code read as written.
6. The fenced sources are joined by blank lines. With a `question`, it goes through `user_text(question, "ask")`, in cloud mode through `redact_secrets`, gets the same `<` rule, and is added last as `<question>…</question>`, outside every source.
7. Returns `Packed(system=SYSTEM_RULE, user=…, checks, sent, items)` (`items`: the `kind:id` of the owner of every source that was sent and is not trust `model`), where `sent` maps each anchor to its text as written into the fence in step 4 (cut and redacted; before `_defuse`). `checks` holds `fenced` (the number of sources given, those left out included), `trimmed`, `left_out` (only when at least one source was left out), `flagged` (the sorted `detect` names) and, in cloud mode, `secrets_redacted`. Since 4.2 it also holds `sources`: for each source that was sent (not those left out), in order, `{anchor, trust, chars, cut}`: the anchor as written into the fence (`unknown` when it does not match `ANCHOR`), the trust (`imported` when not in `TRUST`), the characters sent after the cut, and `cut` (the feature's own `Source.cut`, or cut here). At most `MAX_LISTED` = 60 are listed; each one past that adds 1 to `sources_more`. **It never holds a source's text**: only where it is and how much of it went.

**After the model**

| Function | What it does |
|---|---|
| `safe_output(text, cap=None) -> Output` | Sanitises the answer. Markdown image syntax `![alt](address)` becomes `alt (image not loaded: address)`, link syntax `[words](address)` becomes `words (address)`, reference-style link definitions (`[name]: address` on a line of its own) are removed, and any `![` or `](` that is left is broken up (`[`, `] (`). The addresses of the image and link syntax are collected in `Output.links`: a page may show them as words, and nothing opens or loads them. Raw HTML stays as the characters it is, because the page draws an answer with text nodes only (`web/src/aitext.ts`, below). With a `cap`, a longer text is cut there, gets `…` and `Output.cut` is true |
| `quote_in(quote, text, min_words=5) -> bool` | Is the quote, word for word, in this text? Both go through `_plain` first (case, spacing and punctuation aside), then `word_in` compares them on whole words. False for a quote of fewer than `min_words` words or under 12 characters. Resume and Explain use it to hold a quote against the text that went to the model, before `verify_citations` |
| `_plain(text) -> str` | The form a quote and its source are compared in (also used by `quote_in`, by Explain's selection and term checks and by the digest's keyword check). In order: `sanitize`, NFKC, `casefold`; a hyphen (`-`, U+2010, U+2011) or an apostrophe (`'`, U+2019) between two letters is removed (`_JOIN`), so `non-significant` is the one word `nonsignificant` and `isn't` is `isnt` (a quote must keep such a word as written: `top k` does not match `top-k`); a comma after a digit and before exactly three digits is a thousands comma and is removed (`_THOUSANDS`), so `1,000` is `1000`; a `.` or `,` between two digits then becomes `_` (`_DECIMAL`), so `71.2` and `71,2` are the one token `71_2`, never `71 2` or `712`, and `1.000` is `1_000`, another number than `1,000`; U+2212 (minus) always becomes ` minus ` (NFKC turns a superscript minus, `10⁻³`, into it, so its sign is kept); a `-` or U+2013 (en dash) before a digit, with at most one space between, becomes ` minus ` (`_MINUS`) unless it comes right after a letter, digit or `_`, or after a digit and a space, so `-3`, `(-3)`, `e.g.-3` and `- 3` are "minus 3", while `x-1`, `3-4`, `3 - 4` and `COVID-19` stay two tokens; `%` becomes ` percent `; then every run of characters that are not letters, digits or `_` becomes one space, and the ends are trimmed. Milestone 2.1 added the number rules, and its review the joined words, the thousands comma, the superscript minus and the minus after a full stop or before a space; before, `71.2` was `71 2` and `-3` was `3` |
| `word_in(quote_plain, text_plain) -> bool` | Is one plain text inside another on whole words (both padded with a space)? So `important` is not in `unimportant` and `by 1` is not in `by 15`. Used by `quote_in`, `verify_citations`, Explain's term check and the digest's keyword check. False for an empty quote |
| `verify_citations(db, citations) -> Verified` | `citations` is a list of dicts with `anchor` and `quote`. Only the first `MAX_CITATIONS` (40) are looked at; the rest count as removed. A citation is kept only when: its anchor matches `DOC_ANCHOR`; that sentence is live, in a live paragraph, a live section and a live document (all four `deleted = 0`; the paragraph and section rules are from 2.1); the quote, after `_plain`, is at least 12 characters and 3 words long; and the quote is found, on whole words (`word_in`), in the text of **the section that holds the cited sentence** (its live sentences in live paragraphs, joined by spaces, after `_plain`). A hidden section (References) counts: it is real text of the document, and whether it was sent is each feature's check. A kept citation gets `document_id`, `section_id` and `sentence`: the first sentence of the section that holds the whole quote, or else the first that holds the quote's first six words, or else the cited one. `Verified` holds `kept`, `removed` (a count) and `status`: `verified` (all kept), `partly` (some removed), `unverified` (none kept; an empty list too) |

**The one way in for a feature: `ask`**

`ask(port, db, task, instruction, sources, budget, question=None, schema=None, prompt_version="", call_id=None) -> Result` (`call_id` is passed on to the port, so the caller can cancel that call with `port.cancel(call_id)`; the digest uses it for Stop):

1. Reads `ai_mode` from the port's settings. Not `local` or `cloud`: `AIOff`, before anything is packed.
2. `pack(db, sources, budget, question, cloud=leaves(port))` (before 4.5: `cloud=(mode == "cloud")`). A `Blocked` here ends the call; nothing is sent and no row is written to `ai_log`. Then **the send preview** (4.4): when the text leaves this computer and `ai_preview` is on, `privacy.gate(task, ai_cloud_provider, system, packed.user, packed.items)`. It returns when this request was approved for this text, or for these items; otherwise it raises `PreviewNeeded`, nothing is sent, no log row is written, and the server answers 428.
3. `port.complete(task, instruction + blank line + SYSTEM_RULE, packed.user, schema, prompt_version=prompt_version, call_id=call_id, expect_mode=mode)`. The port's own limits and its scrub apply as for any call; the port refuses with `ModeChanged` when the mode is no longer `mode`. When the port raises an `AIError` that names a log row (`log_id`), the packing checks are merged into that row before the error goes on, so a failed call also lists its sources.
4. `safe_output(reply.text)`, without a cap: the port has already cut the answer at the profile's length.
5. The guard's checks (`fenced`, `trimmed`, `left_out` when there is one, `flagged`, `links_removed`, `sources` and `sources_more`, and `secrets_redacted` and `private_left_out` for text that leaves this computer) are merged into the `checks` of the call's `ai_log` row. When `port.complete` raised instead, the packing checks (all but `links_removed`) are merged into the failed call's row when the error names one (step 3); a refusal before any row (`AIOff`, `ModeChanged`, `PreviewNeeded`, a `Blocked` from `pack`) leaves no row. `links_removed` counts the addresses in the text answer only.
6. Returns `Result(text, data, links, log_id, checks, warning, sent)` (`sent` is `Packed.sent`, unchanged). `data` is the port's checked JSON (`reply.data`) after `_clean_data`: every string in it, inside lists and as a value of an object at any depth, goes through `safe_output` too, and the addresses found there are added to `links`. Keys of an object, numbers and the rest stay as they are.

`ask` does not call `verify_citations`. A feature whose answer carries citations calls it on its own.

**The page side: `web/src/aitext.ts`**

The front-end half of "safe rendering". No page imports it yet, so it is not in the built `app.js`; its styles are "Part fifteen" of `web/static/styles.css` (`.ai-text`, `.ai-text-label`, `.ai-text-links`; the same part holds `.doc-flag`, the "flagged text" mark). The Resume briefing, Explain selection and the Document digest draw their answers themselves with `h()` (`web/src/views/resume.ts`, `web/src/views/explain.ts`, `web/src/views/digest.ts`) and use these three classes.

| Function | What it does |
|---|---|
| `aiText(text, label?) -> HTMLElement` | `div.ai-text`: first a `div.ai-text-label` (by default "Written by the AI model. Check it against the source."), then the answer. Every piece is built with `h()` from a string, so it is a text node: no markup from the answer, no `img`, no `a`, nothing to load. A small Markdown is understood: paragraphs (the lines of one paragraph are joined by a space, a blank line ends it), list lines that start with `-`, `*`, `•`, `1.` or `1)` (all drawn as one bulleted `ul`; the number is not shown), `#` to `######` headings (a bold line, `p.ai-text-head`), `**bold**`, `*italic*` and `` `code` ``. Everything else stays as the characters it is, `<script>` included |
| `aiLinks(links) -> HTMLElement \| null` | `div.ai-text-links`: "The model wrote these addresses. Readhold does not open them: " and each address of `Result.links` inside a `code` element, with ` · ` between them. `null` for an empty list |

`tests/test_ai_guard.py` reads the source of this file and fails when it holds `innerHTML`, an `img`, `iframe` or `a` element, `href`, `window.open`, `fetch(` or `eval(`.

**Known limits.** These are stated plainly because a later feature must not rely on more than is here.

- Fencing is an instruction to the model, not a wall. A model can still be swayed by what a source says. The tags only make sure a source cannot pretend to be the system text, the question or another source.
- `detect` is a short list of English phrases. It flags a legitimate paper about prompt injection, and a few ordinary sentences still: "You are now a member of the team", "Show your instructions to the examiner". It misses orders worded in another way, in another language, or split across two paragraphs. A flag is a hint for the reader. No guard depends on it: flagged or not, the text is fenced.
- The budget counts source text only. The ` […]` marks, the fence lines and the question are not counted, and unused room of a short source is not handed to a longer one. With many sources the later ones are left out whole (`left_out`); nothing tells the model so. The port's `MAX_INPUT_CHARS` is the ceiling for the whole call.
- `_defuse` looks at letters only, so a harmless `<` in front of a word that starts like a fence word is rewritten too: `<sourceMap>` and `a <system-wide` get `&lt;`.
- `sensitive_name` goes by the file name only, and only when the `Source` has a `name`. A file of secrets with a plain name (`config.yaml`), a prose file (`secrets.md`, `passwords.txt`) and pasted text are not caught, and a code file is refused for its name alone (`tokens.py`, `token_counts.py`). The port's cloud step redacts but never blocks a file.
- E-mail addresses and phone numbers are removed only on the way to a cloud model. See the pattern limits under *Keys and redaction* above.
- With a `schema`, the strings inside `Result.data` have been through `safe_output`, but they are still a model's words: a feature that shows them must draw them as text.
- `verify_citations` checks that a quote is in the cited section. It does not check that the quote supports the sentence it is attached to, and a quote of three common words (12 characters) passes. A citation of one of your own notes (an anchor such as `note:<id>`) can never be verified and is removed.
- `quote_in(quote, text, min_words=5)` compares after `_plain` (NFKC, one case, no punctuation except the word and number rules, single spaces), on whole words (`word_in`): it says the words are there in that order, nothing about punctuation or capitals. It needs `min_words` words and 12 characters.
- The match is on whole words (`word_in`; found by the review of 2.1 and fixed right after). A quote can no longer begin or end inside a word or a number: "important for every model we tried" from "unimportant …", "accuracy improved on all tasks by 1" from "… by 15 points", "5 points" from "15 points", "the temperature fell by -3" from "… by -30 degrees" are all caught. A hyphen or an apostrophe between two letters is part of the word (`_JOIN`), so "significant across all of the runs" is not in "non-significant across …" and "the method is" is not in "the method isn't". The price: a quote must keep such a word as written, and "top k" does not match "top-k". In the middle of a quote nothing can be left out or added: dropping "not" inside a quote is caught.
- A quote may run across sentences and paragraphs of one section, because the sentences are joined and the full stop is punctuation: "the drug did not work patients improved anyway" from "The drug did not work. Patients improved anyway …" is kept. This is on purpose: the words are real and in this order, and quoting two sentences is legitimate.
- What `_plain` treats as the same, and so cannot tell apart: `items 1,5` and `1.5`; `x-1` and `x 1` (a hyphen after a letter is not a minus); `3-4`, `3–4`, `3 - 4` and `3 4` (a digit, then a dash, is a range). What it tells apart although the meaning may be the same (a real quote is then not verified): `x-1` and `x − 1` (a typographic minus is always a minus); `1 000` with a space and `1,000` or `1000`. Fixed after the review of 2.1: a thousands comma is left out (`1,000` = `1000`, and `1.000` is another number); a superscript minus keeps its sign (`10^-3` matches `10⁻³`, `10^3` does not); a minus after a full stop (`e.g.-3`) and `- 3` with a space count as minus. Footnote marks become letters of the word (`accuracy¹` is `accuracy1`), so a quote without them is not verified.
- Explain's term check and the digest's keyword check use `word_in`, so the term `port` is not accepted when the passage says "points". The digest drops a keyword that is only a sign word (`%`, `percent`, `minus`) or has no letter (`1.000`); a kept keyword is shown as the model wrote it.
- A refused call (`Blocked`) leaves no trace in `ai_log`.
- Text hidden in a PDF: see chapter 1, section 9.3, for what the importer drops, what it only counts and what it cannot see.

### Milestone 2.1: quote and anchor verification

Plan sections 6.3 ("Quote verification", "Anchor verification"), 6.6, 6.9 rows 4 and 5 and section 8. Its check: "Fake citations in test outputs are always caught". The owner chose to build it in the same session as Phase 1, although `CLAUDE.md` says a new phase starts in a new session.

**Already there before 2.1.** `quote_in` and `verify_citations`; each feature checks a quote against exactly the text it sent (`resume._line`: an imported source of that document that was sent; `explain.explain`: `sent`; `digest._summarise_part` and `_find_quote`: `Chunk.body`), and only then through `verify_citations`; the three statuses; an invented quote and a missing anchor tested for each feature and in `test_ai_guard.py`.

**What 2.1 added.**

- `verify_citations` needs a live paragraph and section as well as a live sentence and document, and looks at no more than `MAX_CITATIONS`.
- `_plain` keeps a number's meaning (decimals, a minus sign, `%`; the table above). The same function serves `quote_in`, Explain's selection and term checks and the digest's keywords, so all of them changed with it.
- `tests/test_ai_citations.py`, below.

**Fixed after the review of 2.1.** The review reproduced its findings with a script and a temporary `READHOLD_HOME`; all but the ones under *Known limits* were fixed right after:

- `word_in`: a quote, a term or a keyword is matched on whole words, in `quote_in`, `verify_citations` (the section and the sentence it points at), Explain's term check and the digest's keyword check.
- `_plain`: `_JOIN` keeps a hyphenated or apostrophe word as one word; `_THOUSANDS` leaves out a thousands comma; U+2212 (and so a superscript minus after NFKC) is always a minus; `_MINUS` also takes a minus after a full stop and `- 3` with a space, and leaves `3 - 4` a range.
- `_clean_keywords` drops a keyword that is only a sign word or has no letter.
- The registry test reads the code with `ast` (below).
- 21 more tests in `tests/test_ai_citations.py` (section "found by a review of 2.1").

**The shared fake citations (`tests/test_ai_citations.py`).** `REAL` is a sentence of `SAMPLE_MD`'s Method section. `FAKES` holds eleven fakes: `invented`; `one_word_changed`; `letter_swapped`; `lookalike_letter` (a Cyrillic `о`, which NFKC does not fold); `other_document` (a sentence of a second, imported document); `not_sent` (a real sentence of another section); `across_sections` (the end of one section and the start of the next); `hidden_section` (a line of References); `too_short`; `empty`; `only_punctuation`.

- The checker: `REAL` under its anchor is `verified`; every fake under that anchor is caught (`not_sent` and `hidden_section` are real text of the document, so they are each feature's matter); the other document's sentence is kept under its own anchor and caught under this one.
- Every feature: `FEATURES` maps `resume`, `explain`, `digest`, `ask` (added with milestone 2.2: the registry test failed until it was) and `library` (added with 2.3, the same way) to a helper that drives the feature through its routes against a fake model server (`_server`, which answers each feature's schema with the quote it is given, telling the features apart by their prompts; Ask by the `<question>` tag in the user text, Ask my library by "from their own library" in its prompt, answering at once with `action` `answer`). Ask's helper asks "What is the SMR gating network over token blocks?", which only the Method section answers, so `not_sent` (a real sentence of another section) and `hidden_section` are really not sent to it and returns the quotes shown as verified and the status. Ask my library's helper asks the same question across the library: only the Method section of this document matches all its words, so the second document of the fake tests (`OTHER_DOC`) and the other sections are not sent. A control test per feature shows `REAL` verified, so the fake tests cannot pass by showing nothing. Then each feature with each fake: nothing shown, status `unverified`. One case is skipped on purpose: the digest with `not_sent`, because the digest reads every visible section; `hidden_section` is its not-sent case.
- Anchors: 18 malformed or missing ones (empty, not hex, an unknown document, no `:ord`, a negative, huge, decimal or padded number, spaces, SQL, a path, upper case, `note:` and `session:` kinds, an extra `:1`, leading zeros) are removed and the database is untouched.
- A removed section, a removed paragraph and a removed document each make the citation fail.
- Numbers: `-3` against `3`, `41%` against `41`, `71.2` against `712` and `71 2` are caught; case, spacing and curly quotation marks still match.
- A flood of 500 citations keeps `MAX_CITATIONS` and ends `partly`.
- **The registry test** (`test_every_feature_that_calls_a_model_is_checked_here`, with `_model_callers`): it parses every module under `readhold/` (sub-folders included) with Python's `ast` and finds each one that calls a model: `guard.ask` under any import name (`from .guard import ask as a`, `g.ask(…)` on any module name) or `port.complete(` directly. Those modules must be exactly the keys of `FEATURES`, so a new feature fails the suite until it is added to this file. `DIRECT_CALLERS` (`guard`, `api` for Test connection, which sends a fixed text, and `port`) are the modules allowed to call the port directly. `test_the_registry_finds_every_way_of_calling_a_model` feeds it a fake module that calls a model in all three ways.
- **Found by the review** (`EDGES`, one section with the hard cases): nine fakes that start or end inside a word, a number or a hyphenated word, or change a number (`1.000` for `1,000`, `10^3` for `10⁻³`, `e.g. 3` for `e.g.-3`) are caught by `verify_citations` and by `quote_in`; ten real quotes with the same words and numbers still pass (a typographic minus, `1000` for `1,000`, `10^-3`, `e.g. -3`); `_clean_keywords` keeps `points` and `compute` and drops `%`, `percent`, `minus` and `1.000`, and `word_in` does not find `port` in "points".

**Decisions, not built.**

- The plan's section 8 says an answer with nothing verified is "hidden". Readhold shows it labelled `unverified` ("Treat this as a guess") instead. **Decided by the owner on 2026-11-25: keep it labelled**; a guess can still help the reader think, the label says not to rely on it, and hiding would make the features look broken with small local models that often fail to quote exactly. A setting to hide such answers may come later, off by default.
- A `note:<id>` anchor (a citation of the reader's own note) is not verifiable by `verify_citations` and is removed there. Milestone 2.3, Ask my library, the one feature that cites notes, checks a note quote itself (`library._citation`: on whole words in the note's text as sent, without its header, and in the live note's text), and a kept answer's note quotes again in `still_true`.
- The plan's anchor has a page and character offsets. Readhold's is a document id and a sentence `ord`: `ord` is given once at import (`store.save_parsed`) and nothing renumbers it (a merge-up or a split moves paragraphs between sections and keeps every `ord`; there is no re-parse). **A PDF sentence has no page number**: the parser knows each block's page (`Block.page` in `importers/pdf_import.py`), but `PPara` and the `sentences` table do not keep it, so a citation can open its sentence in the reader but cannot say "page 7". Where in the sentence the quote starts is not stored either; it is found again by searching the section. The section a sentence is checked against is the one it is in at check time.

**Known limits.** The `_plain` limits listed above: a quote may run across sentences and paragraphs of one section (on purpose); `x-1` and `x − 1` do not match; `1 000` with a space does not match `1,000`. The registry test sees a call written as `name.ask(…)` or `ask(…)` under its imported name, and any `.complete(…)`; it does not see a call through a longer path (`readhold.ai.guard.ask(…)`) or through `getattr`. The fake server tells features apart by words of their prompts, so a new feature's calls get the Resume answer until `_server` learns it. Explain's check of a selection against a formula drawn in the browser was not tried. Nothing in 2.1 was tried against a real model.

### Prompts, kept results, the Resume briefing, Explain selection, the Document digest, Ask this document, Ask my library, Study notes, the Reading plan, Brainstorm and Organize (`prompts.py`, `results.py`, `resume.py`, `explain.py`, `digest.py`, `ask.py`, `library.py`, `notes.py`, `plan.py`, `brainstorm.py`, `organize.py`, migrations `0018_ai_results.sql` and `0019_note_origin.sql`)

Milestones 1.3, 1.4, 1.5, 2.2, 2.3, 2.4, 3.1, 3.2 and 3.3 of the plan: the nine features. All follow the same path: build the sources, compute an `input_key`, return the kept result when there is one, otherwise call `guard.ask`, check what came back, and keep it in `ai_results`. The digest does this twice over: once per part (`digest_map`), then once for the whole (`digest`), in a background job. Ask my library calls `guard.ask` up to three times for one kept result (a bounded loop); Brainstorm calls it four times (three samples and a critic).

**The prompt registry (`prompts.py`)**

A prompt is a plain file, `readhold/ai/prompts/<name>_v<N>.md`, one file per version. It holds the instruction of one feature and nothing else: no document text and no placeholders (a test refuses a `{` in `resume_v1.md`). What a model reads from the library always goes into fenced sources.

| Name | What it is |
|---|---|
| `FOLDER` | `readhold/ai/prompts/` |
| `FILE` | The file-name pattern `<name>_v<number>.md` |
| `NAME` | What a prompt name may look like: a lower-case letter, then up to 40 lower-case letters, digits or `_`. A name with a slash or a dot never reaches the file system |
| `Prompt` | A frozen dataclass: `name` (`resume`), `version` (`resume_v1`), `text` (the file, stripped) and `hash` (SHA-256 of the text) |
| `versions(name) -> list[int]` | The version numbers that have a file, ascending |
| `load(name) -> Prompt` | The prompt in use: **the highest version**. `KeyError` for a name that fails `NAME` or has no file. The file is read on every call |

`prompts/resume_v1.md` asks for a JSON object with `recap` (at most 3 items, each with `text`, `anchor` and `quote`: a passage of 5 to 25 words copied word for word from a source marked `trust="imported"`), `point` (one sentence about the section the reader is in now) and `next` (one sentence about what to read next, built on the reader's own next step when there is one). Its rules: only what the sources say, empty `quote` and `anchor` when nothing can be quoted, say less when the sources are thin, plain sentences, the JSON object and nothing else.

`prompts/explain_v1.md` asks for a JSON object with `explanation` (what the selected passage means, the passage itself and not the topic), `terms` (at most 5 items with `term`, written exactly as in the passage, and `meaning`), `feedback` (one or two kind sentences about the reader's first attempt, or an empty string) and `quote` (5 to 25 words of the passage, copied word for word, that the explanation rests on). Its rules: only what the sources say, say what is missing instead of guessing, no added facts or made-up numbers, code explained step by step in words, plain sentences, the JSON object and nothing else. The level is **not** in the file: `explain.LEVELS[level]` is appended to the prompt text for each call.

`prompts/digest_map_v1.md` (one part of a document, with its section titles) asks for a JSON object with `summary` (two or three plain sentences, under 60 words), `points` (at most 3, each with `text`, under 25 words, and `quote`, 5 to 20 words copied word for word from the part) and `keywords` (at most 5 that appear in the part). `prompts/digest_v1.md` (the part summaries, in order, with their points and quotes; it says the model does not see the document) asks for `summary` (at most 5 sentences, under 120 words), `key_ideas` (at most 6, each with `text`, `anchor` of the part and `quote`, one of the quotes given, copied exactly), `keywords` (at most 10, from the parts) and `difficulty` (`introductory`, `intermediate` or `advanced`). Both: only what the sources say, no Markdown or links, the JSON object and nothing else.

`prompts/ask_v1.md` (the sections that match a reader's question best, and the question) asks for a JSON object with `found` (true only when the sources answer the question), `answer` (at most 6 plain sentences, under 120 words; empty when not found) and `citations` (at most 4, each with `anchor` and `quote`, 5 to 25 words copied word for word from a `trust="imported"` source; empty when not found). Its rules: only from the sources, else `found` false; no guessing and no outside knowledge; a partial answer says what the sources do not cover; plain sentences, no Markdown or links, the JSON object and nothing else.

`prompts/library_v1.md` (the passages and notes that match a reader's question best, and the question; at most 3 steps) asks for a JSON object with `action` (`answer`, `search` or `read`), `keywords` (a few plain search words, for `search`), `anchor` (the anchor of the source to read, for `read`), `found`, `answer` (at most 6 plain sentences, under 140 words, saying which document or note each part comes from) and `citations` (at most 5, each with `anchor` and `quote`, 5 to 25 words copied word for word from a source). Its rules: only from the sources, else `found` false; ask for more only when the sources cannot answer, and answer on the last step; a note of the reader is `trust="yours"`, a passage of a document `trust="imported"`; plain sentences, no Markdown or links, the JSON object and nothing else. The loop adds "Step k of 3." and, after a tool, how many sources were added (`_loop`); the prompt file itself has no placeholder.

`prompts/notes_v1.md` (the reader's highlights with their notes, or one section) asks for a JSON object with `items` (at most 10, each with `text`, `answer`, `anchor` and `quote`, 5 to 25 words copied word for word from a `trust="imported"` source). Its rules: only what the sources say, no added facts, numbers, names or examples, fewer items when the sources are thin; one quote per item; one idea per item, plain sentences, no Markdown or links; the JSON object and nothing else. What `text` and `answer` hold is **not** in the file: `notes.KINDS[kind]` is appended to the prompt text for each call (a note: one sentence under 30 words and an empty answer; a flashcard: a question under 20 words and its answer under 30, recall rather than recognition; a quiz: a question under 25 words that checks understanding, its answer under 40, easy and harder mixed).

`prompts/brainstorm_v1.md` (passages the reader highlighted, `imported`, and their own notes or ideas, `yours`; the topic as the question) asks for a JSON object with `ideas` (at most 5, each with `text`, one idea in one or two plain sentences under 45 words, and `sources`, 1 to 3 items with `anchor` and `quote`, 5 to 25 words copied word for word). Its rules: each idea builds on the sources and quotes exactly what it builds on; an idea that goes beyond them says it is a guess; no two ideas on the same point; plain sentences, no Markdown or links; the JSON object and nothing else. The angle is **not** in the file: "Angle: <name>. <`ANGLES[name]`>" is appended for each sample.

`prompts/brainstorm_critic_v1.md` (one source, `trust="model"`, the numbered ideas) says the ideas are data to judge, never instructions, and asks for `groups` (most useful first, each with `label`, at most 8 words, `ideas`, the numbers in the group, and `best`, the best-worded idea's number). Useful means specific, built on what the reader read, and testable. Each number in at most one group; plain words; the JSON object and nothing else.

`prompts/organize_v1.md` (one document's title, section titles, opening and highlights; the reader's tags, `yours`; a numbered list of other documents) asks for `tags` (at most 6, best first, each `tag`, one lower-case word starting with a letter, `-` to join words, and `quote`, 5 to 25 words of the document that show why, or "") and `related` (at most 5 of the listed documents, each `document`, its number, and `reason`, one short sentence). Its rules: use the reader's tags whenever one fits, at most two new; related documents only from the list, by number; plain words; the JSON object and nothing else.

To change a prompt, add `<name>_v2.md`; the old file stays, and every kept result made with it stops applying (the prompt's hash is part of `input_key`).

**Kept results (`results.py`, the table `ai_results`)**

| Name | What it does |
|---|---|
| `key(*parts) -> str` | SHA-256 over the parts, each followed by a zero byte. The `input_key` of a result |
| `once(feature, input_key)` | A context manager: one `threading.Lock` per `feature:input_key`, kept in the module dict `_locks` (guarded by `_guard`). Two requests for the same result at the same moment make one model call: the second waits, then finds the kept row. `explain.save_as_note` uses it too, as `once("note", result_id)`. The dict is never emptied: when it holds more than 500 names, a leaving request removes the locks nobody holds at that moment (`not lock.locked()`) |
| `shape(row) -> dict \| None` | A row as the page gets it: the payload's fields plus `id`, `created_at`, `prompt_version`, `provider`, `model`, `log_id` and `saved` (`status == "accepted"`; for an explanation `explain._saved` then sets it from the note itself). `None` when the payload is not a JSON object, so a damaged row counts as not there |
| `find(db, feature, target_id, input_key)` | The newest live row for that feature, target and key, through `shape` |
| `keep(db, feature, target_id, input_key, payload, prompt_version, log_id, replaces=None, target_type="document")` | Inserts the new row with `target_type` (`document`, or `library` for Ask my library; the argument was added with 2.3) and the `provider` and `model` of the call's `ai_log` row, **then** soft-deletes the row named by `replaces`, so a reader polling at that moment sees the old or the new result, never neither (changed for 1.5; before, the old row went first). When `target_type` is `document` and the document is no longer live (it was removed while the model answered), the new row is stored with `deleted=1`, so no later request finds it. Returns it through `shape` |
| `forget_document(db, doc_id)` | `UPDATE ai_results SET deleted=1` for that `target_id`. `server.api_doc_delete` calls it after the soft delete and the reindex. `updated_at` and `device_id` are not touched. Restoring the document does not bring the rows back |
| `clear_all(db) -> int` | `DELETE FROM ai_results`: every row, live or soft-deleted, of every feature. Called by `DELETE /api/ai/log` ("Clear AI history"). A margin note saved from an explanation is a row of `notes` and stays, still with `origin='ai'` |

The table (migration `0018_ai_results.sql`), one row per result:

| Column | Holds |
|---|---|
| `id`, `device_id`, `created_at`, `updated_at`, `deleted` | The project's record columns |
| `feature` | `resume`, `explain`, `digest` (a whole digest), `digest_map` (the summary of one part of a document, kept so that a stopped digest goes on), `ask` (an answer to a question about the document), `library` (an answer to a question across the library), `notes` (drafted study items), `plan` (a reading-plan suggestion), `brainstorm` (ideas) or `organize` (suggested tags and related documents) |
| `target_type`, `target_id` | `document` and the document's id; for `library`, `library` and `library` (one target for the whole library); for `plan`, `plan` and a hash of the chosen documents; for a brainstorm of a note or an idea, `page` or `idea` and its id |
| `input_key` | The hash of everything the result was made from |
| `payload` | JSON, already cleaned and checked. Resume: `recap`, `point`, `next`, `status`, `links`, `session_id`, `warning`. Explain: `explanation`, `terms`, `feedback`, `quote`, `status`, `links`, `level`, `document_id`, `sentence`, `end_sentence`, `warning`, and `note_id` once it was saved as a note. Digest: `summary`, `key_ideas`, `keywords`, `difficulty`, `parts`, `skipped_parts`, `status`, `links`, `warning`. Digest part (`digest_map`): `summary`, `points`, `keywords`, `sentence`, `titles`, `links`, `warning`. Ask: `question` (as first asked, cleaned), `found`, `answer`, `citations` (each `verified`, and when verified `quote`, `sentence`, `section_title`, `document_id`), `status`, `searched`, `links`, `warning`. Ask my library: `question`, `found`, `answer`, `citations` (each `verified`, and when verified `kind` and `quote`, with `document_id`, `document_title`, `section_title` and `sentence` for a document or `note_id` and `note_title` for a note), `status`, `steps`, `searched`, `links`, `warning`, `left_out`, `log_ids`. Study notes: `kind`, `source`, `section_id`, `document_id`, `items` (each `text`, `answer`, `verified`, and when verified `quote`, the document's own words, and `sentence`), `status`, `links`, `warning`, `kept` (the indices kept so far), `cut`, `left_out`. Reading plan: section *Reading plan* below. Brainstorm: `target` (`kind`, `id`, `title`, `sheet_title`), `topic`, `ideas` (each `text`, `label`, `similar`, `angles`, `sources`, `verified`), `judge`, `variety`, `kept`, `left_out`, `status`, `links`, `warning`, `log_ids`, and after ideas went into the sheet `last` (`page_id`, `before`, `after`, `ideas`; for Undo). Organize: `document_id`, `tags` (each `tag`, `existing`, `verified`, and `quote` when verified), `related` (each `id`, `title`, `shared`, `reason`), `dropped`, `reuse`, `model_tags`, `model_reuse`, `status`, `links`, `warning` |
| `status` | `shown` by default. `explain.save_as_note` sets `accepted`, and it stays `accepted` when that note is deleted later (the `saved` the page gets is checked against the note). `notes.accept` and `brainstorm.keep` set `accepted` the first time items are kept from a result (the indices are in `payload.kept`); `readplan.apply` sets it on a reading-plan suggestion a plan was made from. `edited` and `dismissed` are named in the migration; nothing sets them |
| `prompt_version`, `provider`, `model` | Which prompt and which model wrote it |
| `log_id` | The `ai_log` row of the call. That row is gone after 30 days; the result stays until it is replaced, its document is deleted or the AI history is cleared |

Index `idx_ai_results_target` on `(feature, target_id, input_key)`. The table **is** in `services.EXPORT_TABLES`: unlike `ai_log` it is something the user was shown. Nothing in it is written into the reader's notes or cards unless they press "Save as a note" (Explain) or a Keep button (Study notes, Brainstorm), or add a tag (Organize).

#### The Resume briefing (`resume.py`)

"Where you left off" when you come back to a document. It has two layers. The facts need no model (`facts`). With AI on, and only when the reader presses the button, a model writes a short recap from the passages of the last reading session (`brief`). The page side is `web/src/views/resume.ts` (chapter 5, section 5.6).

The plan's open question 2 ("Should the Resume briefing run automatically on open, or only when asked?") is decided: **only when asked**. The facts show by themselves; a model is asked only by `POST …/resume/brief`, and the page sends that only from a button.

**Names in `resume.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"resume"`: the task name for the port and the profile, the budget name, the prompt name and `ai_results.feature` |
| `MAX_CONTEXT` | `guard.BUDGETS["resume"]`, 12,000 characters of source text |
| `MAX_SOURCES` | 12. `context` cannot build more: 5 + 5 + 1 + 1 |
| `MAX_SECTIONS` | 5 sections of the session: the five read last, by the clock |
| `MAX_HIGHLIGHTS` | 5 marked passages, the first five by sentence |
| `AHEAD` | 12 sentences of the current section, from the reader's position on |
| `MAX_LINES` | 3 recap lines are kept |
| `MIN_QUOTE_WORDS` | 5: a quote of fewer words proves nothing and is not shown |
| `CAPS` | Characters kept of what the model wrote: `text` 300, `point` 400, `next` 300, `quote` 400. A longer string is cut and gets `…` |
| `NoSession` | The exception for "this document has no finished reading session" |
| `Line`, `Brief` | The pydantic schema of the answer. `Brief`: `recap` (0 to 8 `Line`s; **an empty list is a valid answer**, "the sources are too thin"), `point`, `next`. `Line`: `text`, `anchor`, `quote`. Strings up to 2,000 characters (an anchor 80) |
| `BriefIn` | The body of the brief route: `{fresh: bool = false}` |
| `status_error(e) -> int` | The HTTP status for a failed AI call, used by both features: 409 for the codes `off`, `setup`, `no_key`, `budget` and `cancelled` (the off switch during a call), 504 for `timeout`, 502 for every other code |

**The facts (no model)**

- `here(db, doc_id) -> dict | None`: `{section_id, section_title, sentence}` for the sentence at `documents.position`. `None` when no live sentence in a live paragraph of a live section has that `ord`.
- `facts(db, doc_id, mode) -> dict`: `{session, here, ai: {mode}, brief}`. `session` is `passages.last_session` (section 4b.4). With no finished session everything but `ai` is `null`. `brief` is the kept recap for the current `input_key`, or `null`. With `mode` `off` the kept recap is not looked up at all, so no prompt file is read. With AI on, the lookup (`prompts.load`, `context`, `_key`, `results.find`) sits inside a `try`: any failure is logged and `brief` is `null`. **The facts never fail because of the AI layer.** No model, no network, no write.

**`context(db, doc_id, session=None) -> list[guard.Source]`: what the model may read**

Raises `NoSession` without a finished session. `name` of every document source is `documents.source`, so a file of secrets is refused for a cloud call by `guard.pack`. Every query joins live paragraphs and live sections, so a section removed by a merge-up contributes nothing under its old id.

1. **What was read in that session.** The sentences whose `read_at` lies between the session's `started_at` and `ended_at`, in order. If there are none and both ords are set, the sentences from `start_ord` to `last_ord` (whichever is lower first). They are grouped by section. When there are more than `MAX_SECTIONS` groups, the ones whose latest `read_at` is newest are kept (**the sections read last**), and they are sent in the order of the document. Each becomes one source: anchor `<doc_id>:<ord of the group's first sentence>`, the sentences joined by line breaks, trust `imported`.
2. **What was marked.** The first `MAX_HIGHLIGHTS` highlights of the session (by sentence): anchor `<doc_id>:<sentence>`, the highlight's text, trust `imported`.
3. **The reader's own words**, as one source with the anchor `session:<session id>` and trust `yours`: "The question I was reading for: …", "What I said comes next: …", and "My note on a marked passage: …" for each of those highlights that has a note. Left out when all are empty.
4. **Where the reader is now.** With a `here`: up to `AHEAD` sentences of that section from the position on, under the line "(The section the reader is in now: <title>)", anchor `<doc_id>:<position>`, trust `imported`.
5. At most `MAX_SOURCES` sources (the last ones). Each gets an equal share, `MAX_CONTEXT // number of sources`. A longer text is cut there, its last cut word is dropped, ` […]` is added and `Source.cut` is set. `guard.pack` reads `cut`, so the `ai_log` row of the call says `trimmed: true`.

Never the whole document: a session that read all of a long document sends the start of the five sections it read last.

**`_key(prompt, sources) -> str`**: `results.key` over the prompt's hash and, for every source, its anchor, trust and text **as it would be sent**. So the key changes with a new session, a new position (the last source starts there), an edited note on a marked passage, a removed or added highlight, a changed question or next step, an edited section, and a new prompt version. Any of these makes the kept recap stale: `facts` returns `brief: null` and the button is back.

**`brief(port, db, doc_id, fresh=False) -> dict`**

1. `ai_mode` is not `local` or `cloud`: `AIOff`, before anything else. **With AI off a kept recap is not returned either.**
2. `last_session`; none: `NoSession`.
3. `prompts.load("resume")`, `context`, `_key`.
4. Inside `results.once("resume", key)`: a live `ai_results` row with this feature, document and key, and `fresh` false, is returned. **No model is called.**
5. `guard.ask(port, db, "resume", prompt.text, sources, budget="resume", schema=Brief, prompt_version=prompt.version)`. Every guard of 1.2 applies: the off switch (`AIOff` before anything is packed), fencing, the budget, the cloud rules, the port's limits (the `resume` profile: the small model, temperature 0.2, 700 output tokens), `safe_output` on every string.
6. The first `MAX_LINES` lines with a non-empty `text` go through `_line`. An empty `recap` gives no lines.
7. `status`: `verified` when there is at least one line and every line is verified, `partly` when some are, else `unverified` (also for an empty recap).
8. The payload is `recap`, `point` and `next` (capped), `status`, `links` (the addresses the model wrote, each once), `session_id` and `warning` (the port's budget warning).
9. `results.keep`: with `fresh` and an old row, the old row is soft-deleted, then the new row is inserted (as deleted when the document was removed meanwhile). This happens only after a good answer, so a failed "Ask again" keeps the old recap in the table (and the page keeps showing it).

`_line(db, doc_id, line, sources) -> dict`: `{text, verified}`, and for a verified line also `quote`, `sentence` and `document_id`. The quote must pass `guard.quote_in(quote, source.text, MIN_QUOTE_WORDS)` for at least one source that was sent, has trust `imported` and an anchor of this document: **word for word (case, spacing and punctuation aside), at least 5 words, in text that went to the model.** The line's own anchor is used when it names one of those sources, else the first source that holds the quote ("the anchor is repaired"). Then `guard.verify_citations` must keep the quote under that anchor; it also gives the sentence. **A quote that fails is not returned at all**, so the page cannot show it as a quote. A ✓ therefore proves the quoted words are in the text; it does not prove the line follows from them.

**Routes** (registered by `resume.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body | Result |
|---|---|---|
| `GET /api/documents/{doc_id}/resume` | | `facts(...)` with `ai.mode` = `off`, `local` or `cloud`. Read-only. 404 "document not found" for a bad id or a missing or deleted document |
| `POST /api/documents/{doc_id}/resume/brief` | `{fresh?}` | `{brief}`. A plain `def`, so it runs on a worker thread and blocks no other request |

Status codes of the brief route:

| Code | When | `detail` |
|---|---|---|
| 200 | A kept recap (AI on), or a new one (an empty recap included) | |
| 404 | Bad id, missing or deleted document | "document not found" |
| 409 | `NoSession` | "There is no finished reading session of this document yet." |
| 409 | `guard.Blocked`: in cloud mode, a document whose file name marks it as a file of secrets (`.env`, `id_rsa`, …) | The guard's sentence |
| 409 | `AIError` with the code `off` (also when a recap is kept), `setup`, `no_key` or `budget`: something the user can change in Settings. And `cancelled`: AI was switched off during the call | The error's sentence |
| 504 | `AIError` with the code `timeout` | "The model took too long, so the call was stopped." |
| 502 | Every other `AIError`: `invalid`, `too_long`, and the provider codes (`offline`, `auth`, `model`, `busy`, `refused`, `bad_reply`, `error`) | The error's sentence |
| 422 | No body, or a body that is not `{fresh?: bool}` | FastAPI's own |

**Invariants**

- `GET …/resume` never calls a model and never writes, and it answers whatever state the AI layer is in. Only `POST …/resume/brief` can call a model, and the page sends it only from a button.
- `resume.py` calls `guard.ask`, never the port. The prompt text holds no document text.
- Every string of the model that is stored went through `safe_output` (in `ask`) and a cap (in `brief`). The model's `anchor` is not stored or returned.
- A line is `verified` only when its quote is in an imported source that was sent and `verify_citations` kept it; an unverified line has no `quote` key.
- A kept recap is returned only for the same prompt text and the same sources, character for character, and only while AI is on.
- A result row is replaced by soft delete, never changed in place.

**Known limits** (each was tried on 2026-11-25 unless it says otherwise)

- **Nothing was tried against a real model.** The plan's check "recaps match what was actually read, on 10 test sessions" is open.
- `verified` means the quote is in text that was sent. It does not mean the sentence beside it is true or follows from the quote. `point` and `next` carry no quote and are never checked, whatever the status says.
- The `input_key` does not include the AI mode, the model or the profile. Changing the model leaves the kept recap in place; "Ask again" (`fresh`) is the way to a new one.
- Only the start of each section is kept when a session was long.
- `read_at` is written once per sentence. A session that only re-reads text gets no sentence in its time window and falls back to the `start_ord` to `last_ord` stretch; a session that jumps far gets every section in between. (Not tried again after the review.)
- The current section's source starts at the reader's position, so it can repeat sentences of a "read" source, and two sources can share an anchor.
- `context` cuts a source at `share` characters and then adds ` […]`. When the word it dropped was shorter than three characters the text is a little over `share` (up to 4 characters). `guard.pack` cuts only when the sources together are over the 12,000-character budget (`MAX_CONTEXT` is the whole budget), so this matters only when so many sources run over that the room the shorter ones leave is used up; then `pack` cuts the longest sources once more, and the model gets a word less of them than `_line` compares against. Read from the code, not reproduced.
- `once` holds a worker thread for as long as the first request's model call runs. Two "Ask again" presses at the same moment are still two calls, one after the other (`fresh` skips the kept row).
- The brief route passes no `call_id`, so a running recap can be stopped only by switching AI off, and that answers 409 ("Stopped."; the status is read from `status_error`, not tried).
- `clear_all` deletes rows for good, but the daily backups in `data/backups/` (14 kept) still hold what was in the table when they were made.
- An `ai_mode` that is on but has no profile for `resume` is a `ValueError`, so a 500. (Not tried again after the review.)

#### Explain selection (`explain.py`)

Milestone 1.4. The reader selects text, presses **Explain**, picks a level, may write their own take first, and a model explains the passage. The model reads three things and nothing else: the selection, the text around it in the same paragraph, and the title of its section (plus the reader's take, as their own words). A selection must stay inside one paragraph. The page side is `web/src/views/explain.ts` and `selectionToolbar` (chapter 5, sections 5.3 and 5.6).

**Names in `explain.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"explain"`: the task name for the port and the profile (the strong model, temperature 0.4, 900 output tokens), the budget name (`guard.BUDGETS["explain"]`, 6,000 characters), the prompt name and `ai_results.feature` |
| `MAX_STRETCH` | 12: the most sentences one selection may span |
| `MAX_SELECTED` | 1,800: the most characters of the selection that are sent (a code block is one "sentence" and can be long) |
| `MAX_AROUND` | 1,800: the most characters of the paragraph around it that are sent |
| `MAX_ORD` | 10,000,000: the largest `sentence` or `end_sentence` the route takes |
| `MAX_TERMS` | 5 terms are kept |
| `MIN_QUOTE_WORDS` | 3 (not 5 as in resume): a selection can be one short line of code |
| `CAPS` | Characters kept of what the model wrote: `explanation` 1,500, `meaning` 300, `feedback` 500, `quote` 400; a `term` is cut at 120 |
| `LEVELS` | The three level instructions, appended to the prompt text and hashed into the `input_key`: `simple` (2 to 4 short sentences, everyday words, a technical word explained in the same sentence), `student` (3 to 6 sentences, the correct terms with a short reason for each step), `expert` (2 to 5 dense sentences, precise terms, what the passage assumes and implies) |
| `NotFound`, `Invalid` | The exceptions for "that passage is not in the document" (404) and "that request is not allowed" (422) |
| `Term`, `Explained` | The pydantic schema of the answer. `Explained`: `explanation` (1 to 8,000 characters), `terms` (at most 12 `Term`s: `term` up to 200, `meaning` up to 2,000), `feedback` (up to 4,000), `quote` (up to 2,000) |
| `ExplainIn` | The body of the route: `sentence` and `end_sentence` (0 to `MAX_ORD`), `level` (`simple`, `student` or `expert`; default `student`), `text` (up to 1,200 characters, default empty), `attempt` (up to 600, default empty), `fresh` (default false) |

**`passage(db, doc_id, first, last, text="") -> (sources, sent)`: what the model may read**

`sent` is all the document text in the two sources: the selection and the text around it, as they go to the model. A quote or a term may come from there and from nowhere else.

1. `last < first`, or more than `MAX_STRETCH` sentences: `Invalid("Select at most 12 sentences.")`.
2. The live sentences (in live paragraphs) of the document (itself not deleted) with `ord` from `first` to `last`. None, or the first one is not `first`: `NotFound`.
3. The sentences are in more than one paragraph: `Invalid("Select text inside one paragraph.")`.
4. `whole` is those sentences joined by line breaks. Without a `text` (or with one of spaces only), the selection is `whole`.
5. With a `text` (what the reader actually selected, which can be part of a sentence), three cases. `_one_spacing` is `guard.sanitize` with every run of spaces and line breaks made one space.
   - `_one_spacing(text)` is not empty and is inside `_one_spacing(whole)`: the words are in those sentences **as written**, spacing aside. The selection is that text.
   - Otherwise, `guard._plain(text)` is not empty and is inside `guard._plain(whole)`: a loose match (other case, other punctuation, a formula drawn differently on the page). The selection is `whole`, **the document's own sentences, not what was typed**.
   - Otherwise (no letter or digit in the text, or words that are not there): `Invalid("That text is not in this passage.")`.

   **So only text of the document is ever sent as the passage.**
6. A selection over `MAX_SELECTED` characters is cut there, its last cut word is dropped and ` […]` is added.
7. `around`: the selected sentences, then sentences of the same paragraph are added outwards, one before and one after in turn, while the total is under `MAX_AROUND` characters and there are sentences left. They are joined by line breaks. A result over `MAX_AROUND` characters is cut the same way. So a short paragraph is sent whole, and of a long one **the part nearest the selection**.
8. Two sources, both trust `imported` and named after `documents.source` (so a file of secrets is refused for a cloud call): anchor `<doc_id>:<first>` with "(The selected passage)" and the selection; anchor `<doc_id>:<ord of the first sentence of around>` with "(The text around it, from the section “<title>”)" and `around`. The title is that of the selection's section. `Source.cut` is set on the first when the selection was cut, and on the second when `around` was cut or does not hold the whole paragraph; `guard.pack` reads it, so the `ai_log` row says `trimmed: true`.
9. Returns the sources and `sent` = the selection, a line break, `around`.

**`explain(port, db, doc_id, first, last, level, text="", attempt="", fresh=False) -> dict`**

1. `ai_mode` is not `local` or `cloud`: `AIOff`, before anything else. **With AI off a kept explanation is not returned either.** Then `passage`.
2. A non-blank `attempt` goes through `guard.user_text` (cleaned, spaces collapsed) and becomes a third source: anchor `attempt:<doc_id>`, "My first attempt at saying what the passage means: …", trust `yours`. It is fenced like any source, so `</source>` or order-like text in it stays data (`_defuse`), and `detect` records it in the log row's `flagged`.
3. `prompts.load("explain")`, and the `input_key`: `results.key` over the prompt's hash, the full level instruction (`LEVELS[level]`), and each source's anchor, trust and text. The same passage, level and take give the same key; a reworded level instruction gives a new one.
4. Inside `results.once("explain", key)`: a live kept row and `fresh` false: it is returned, through `_saved`. **No model is called.**
5. `guard.ask(port, db, "explain", prompt.text + "\n\n" + LEVELS[level], sources, budget="explain", schema=Explained, prompt_version=prompt.version)`. Every guard and every port limit applies. The budget is 6,000 characters in all. `passage` already cut both document sources to about 1,800, and a take is at most 1,000 (`user_text`), so together they fit and `guard.pack` has nothing more to cut.
6. `terms`: an item is kept only when its `term` is not blank and `_plain(term)` is inside `_plain(sent)` on whole words (`guard.word_in`); the first `MAX_TERMS`; `term` and `meaning` capped. **A term that is not in the text that was sent is dropped.**
7. The payload: `explanation` (capped), `terms`, `feedback` (capped; empty when no take was given, whatever the model wrote), `quote` empty, `status` `unverified`, `links`, `level`, `document_id`, `sentence` (`first`), `end_sentence` (`last`), `warning`.
8. The quote: when `guard.quote_in(quote, sent, MIN_QUOTE_WORDS)` holds and `guard.verify_citations` keeps it under the anchor `<doc_id>:<first>`, the payload gets the quote (capped) and `status` `verified`. **The quote is checked against exactly the text that was sent**, so words from a part of the paragraph the model never received cannot come back `verified`.
9. `results.keep`, replacing the old row when `fresh` found one (the new row is stored as deleted when the document was removed while the model answered). The result goes through `_saved`.

`_saved(db, shaped) -> dict` sets `saved` to true only when the result has a `note_id` and that note is still live. So after the note was deleted the page offers **Save as a note** again.

**`save_as_note(db, result_id) -> dict`**

1. An id that is not 32 hex characters: `NotFound`. Everything else runs inside `results.once("note", result_id)`, so several presses at the same moment make **one** note.
2. The live `explain` row with that id, else `NotFound`.
3. When the payload has a `note_id` and that note is live, it is returned: one result makes one note.
4. Otherwise, when the result's document is not live: `NotFound`. Else a row of `notes` is inserted: the result's `document_id` and `sentence` (the first selected sentence), `origin` `"ai"`, and the text "AI explanation (<level>): <explanation>", cut at 5,000 characters. The payload gets `note_id` and the row's `status` becomes `accepted`.

`notes.origin` (migration `0019_note_origin.sql`, `TEXT NOT NULL DEFAULT ''`) says who wrote a margin note: empty is the reader, `ai` is "saved from something a model wrote". `PATCH /api/notes/{n_id}` (`server.api_note_patch`) sets it back to empty when the text really changes; saving the same text again keeps it. Once the reader edits the note, it is theirs. The page shows the label while it is `ai` (chapter 5, section 5.3).

**Routes** (registered by `explain.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body | Result |
|---|---|---|
| `POST /api/documents/{doc_id}/explain` | `ExplainIn` | `{result}`: the payload through `results.shape` and `_saved`. A plain `def`, so it runs on a worker thread |
| `POST /api/ai/results/{result_id}/note` | | `{note}`: the margin note, new or the one saved before |

Status codes of the explain route:

| Code | When | `detail` |
|---|---|---|
| 200 | A kept explanation (AI on), or a new one | |
| 404 | Bad id, missing or deleted document | "document not found" |
| 404 | `NotFound`: the first sentence does not exist | "That passage is not in the document." |
| 422 | `Invalid`: more than 12 sentences, `end_sentence` before `sentence`, a selection over more than one paragraph ("Select text inside one paragraph."), or a `text` that is not in those sentences or has no letter or digit | The exception's sentence |
| 422 | A body that fails `ExplainIn`: an unknown level, a `sentence` or `end_sentence` below 0 or over `MAX_ORD`, a `text` over 1,200 or an `attempt` over 600 characters | FastAPI's own |
| 409 | `guard.Blocked`: in cloud mode, a file of secrets by its name | The guard's sentence |
| 409 | `AIError` with the code `off` (also when an explanation is kept), `setup`, `no_key`, `budget` or `cancelled` (AI was switched off during the call) | The error's sentence |
| 504 | `AIError` with the code `timeout` | The error's sentence |
| 502 | Every other `AIError` (`status_error`) | The error's sentence |

The note route answers 200 or 404 "not found" (an id that is not 32 hex characters, a result of another feature, a result that was replaced, cleared or whose document was deleted).

**Invariants**

- The page sends positions, a level, the selected text and the reader's take. It never sends a prompt, and the selected text is refused unless its words are in those sentences of that document. What is sent as the passage is always characters of the document: the selected words as written, or the whole sentences.
- A selection stays inside one paragraph, and at most `MAX_SELECTED` + `MAX_AROUND` characters of the document are sent.
- With AI off the route answers 409 before it looks for a kept result.
- `explain.py` calls `guard.ask`, never the port. The level instruction is a fixed string of the code, not something the page can write.
- Every string of the model that is stored went through `safe_output` and a cap. A term is stored only when it is in the text that was sent; a quote only when it is in that text and `verify_citations` kept it.
- Nothing is written into `notes` unless `POST /api/ai/results/{id}/note` is called, and such a note carries `origin='ai'` until `PATCH /api/notes/{id}` changes its text. One result makes one note, also for simultaneous requests.
- A note is a row of its own: replacing, clearing or hiding the result never changes it.

**Known limits** (each was tried on 2026-11-25 with the fake model server unless it says otherwise)

- **Nothing was tried against a real model.** The plan's check "judged clear on 20 sample passages" is open.
- `verified` means the quoted words are in the text that was sent. It does not mean the explanation follows from them. `explanation`, `feedback` and the `meaning` of a term are never checked.
- A `text` that matches only loosely (other case or punctuation, full-width forms of the same letters) is not refused: the whole sentences are explained instead, and nothing in the result says the selection was widened. A single letter that is in the sentence passes as the selection.
- A selection over two paragraphs or two sections is refused (422 "Select text inside one paragraph."), also when it is short. What a browser selection holds beside a sentence (a heading, a `Q1` badge, a rendered formula) is not sentence text: such a `text` answers 422 "That text is not in this passage." or, when its letters and digits still match, falls back to the whole sentences. The 422 was tried with a heading in `text`; what the browser really puts into the selection was not.
- A code paragraph is one sentence however many lines it has, so `MAX_STRETCH` does not bound code; `MAX_SELECTED` and `MAX_AROUND` do. A long block is sent twice (as the selection when no `text` is given, and as its paragraph), each cut at 1,800 characters from its start.
- `around` is cut from its end. A selection of many long sentences (over 1,800 characters together) is itself cut in both sources. Read from the code, not tried.
- A take that holds order-like text or a closing tag is fenced and recorded in the log row's `flagged`, but the reader is not told.
- Two "Ask again" presses at the same moment are two calls, one after the other, as for the recap.
- After Clear AI history the same passage is asked for again, and saving that new result makes a second note beside the first.
- The label is shown in the notes dialog and in the reader's Notes tab only. The summary sheet, the concept page ("Your notes") and the Markdown export show the note without it; the text still begins "AI explanation (<level>):".
- The `input_key` does not include the model or the profile. Changing the model leaves kept explanations in place; "Ask again" is the way to a new one.

#### Document digest (`digest.py`)

Milestone 1.5 ("Document digest with map-reduce"). The shape of a document before its detail, in two layers. The facts need no model: the outline, the word count and the reading time at the reader's speed (`facts`). With AI on, and only when the reader presses **Digest with AI**, a model writes a summary, up to six key ideas, keywords and a guess at the difficulty. A long document is never sent at once: it is cut into parts at section boundaries (`chunks`), each part is summarised on its own (the **map** step, one call per part, task `digest_map`), and the part summaries are combined (the **reduce** step, one call, task `digest`). The reduce step never sees the document, only the part summaries and the checked quotes they rest on. It runs in a background thread (`Job`) with progress and can be stopped; each part's summary is kept the moment it is made, so a stopped or failed digest goes on where it stopped. The page side is `web/src/views/digest.ts` (chapter 5, section 5.6).

Decisions: the plan's trigger column says "Import, or the Digest button"; **only the button is built**. A digest on import would send every imported document to a cloud model without a press. The reading time and the outline are code, as the plan says; the outline comes from the parser, not from the model. "Ask again" redoes the combining step only.

**Names in `digest.py`**

| Name | What it is |
|---|---|
| `FEATURE`, `MAP` | `"digest"` and `"digest_map"`: the task names for the port and the profiles (`digest`: the strong model, temperature 0.2, 900 output tokens; `digest_map`: the small model, temperature 0.2, 500 output tokens), the budget names (`guard.BUDGETS`, 16,000 characters each), the prompt names and the `ai_results.feature` of the digest and of each part summary |
| `CHUNK` | 6,000: the characters a part aims at |
| `MAX_CHUNK` | 14,000: the most a part may grow to so that a long document stays within `MAX_CHUNKS` |
| `MAX_CHUNKS` | 40 parts. A document that needs more at `MAX_CHUNK` is refused (`TooLong`; about 560,000 characters, some 250 pages) |
| `GROW` | 1.25: the factor the target grows by, so the targets are 6,000, 7,500, 9,375, 11,718 and 14,000 |
| `MIN_QUOTE_WORDS` | 5: a shorter quote proves nothing and is not kept |
| `MAX_POINTS`, `MAX_IDEAS`, `MAX_KEYWORDS` | 3 points per part, 6 key ideas, 12 keywords are kept |
| `HEADER_ROOM` | 800: the characters kept free in each part for its header line (at most an eighth of the part) |
| `HEADER_TITLES` | 6: the section titles a part's header names; more are "and <n> more" |
| `CAPS` | Characters kept of what the model wrote: `summary` 1,200, a part's summary (`part`) 400, a `point` 220, an `idea` 260, a `quote` 300, a `keyword` 40. A longer string is cut and gets `…` |
| `ID` | 32 lower-case hex characters: what a document id must look like before the database is asked |
| `TooLong` | The exception for "more than `MAX_CHUNKS` parts" (the module's own, not `port.TooLong`) |
| `Nothing` | The exception for a document with no text the digest may read (empty, or every section hidden); the start route answers 409 |
| `Stopped` | Raised by `_check`: Stop was pressed, AI was switched off, or the document was removed. The job ends `cancelled` |
| `Chunk` | A dataclass for one part: `text` (what the model reads: a header line, then `## <title>` and the sentences of each section), `body` (the same without the header; what the kept part summary depends on and what quotes are checked against), `first` (the part's first sentence), `titles`, `anchors` (the first sentence of each section in the part) |
| `Point`, `MapOut` | The schema of a map answer. `MapOut`: `summary` (1 to 4,000 characters), `points` (at most 8 `Point`s: `text`, `quote`), `keywords` (at most 20) |
| `Idea`, `DigestOut` | The schema of the reduce answer. `DigestOut`: `summary` (1 to 6,000), `key_ideas` (at most 12 `Idea`s: `text`, `anchor` up to 80, `quote`), `keywords` (at most 30), `difficulty`: exactly one of `introductory`, `intermediate`, `advanced` (a `Literal`, so anything else fails the schema) |
| `Job` | One digest run: `doc_id`, `total`, `id`, `state` (`running`, `done`, `failed`, `cancelled`), `step` (`parts`, `combining`), `done` (parts finished), `message` (the reason of a failure, for the page), `call_id` (the model call in flight, or empty), `stop` (a `threading.Event`). `view()` is what the page gets (no `call_id`, no event) |
| `_jobs`, `_jobs_lock` | The module dict `doc_id → Job` (the last job of each document, finished ones included) and the lock that makes "is one running? then start one" a single step |
| `stop(doc_id=None)` | Sets `stop` on the running job of one document (called by `server.api_doc_delete`) or of every document (called by Clear AI history); returns how many. It does not cancel the call in flight, but its answer is not kept (`_check`) |
| `_stamp`, `_key_cache` | `_stamp(db, doc_id)`: the latest `updated_at` and the row count of the document's sections and of its paragraphs, so it changes when the structure changes. `_key_cache`: `doc_id → (stamp and both prompt hashes, digest key)`, so `kept_digest` computes the parts only when one of them changed |
| `DigestIn` | The body of the start route: `{fresh: bool = false}` |

**`facts(db, doc_id, wpm) -> dict`: no model**

One query: the live sections of the document, each joined with its live paragraphs and their live sentences, grouped by section in section order. A section with no live sentence (a heading with nothing under it) is therefore not in the outline. Each outline item is `{id, title, level, kind, words, sentence, skipped}`: `words` is the sum of `sentences.words`, `sentence` the section's first sentence (for the jump), `skipped` is `sections.hidden` (references, and any section hidden in Fix structure). `words` of the document is the sum over the sections that are not skipped; sections marked *safe to skip* (`background`) are counted and are digested. `wpm` is the `wpm` setting, 250 when unset, clamped to 60 to 1,200. `minutes` is `max(1, ceil(words / wpm))`, so an empty document reads "about 1 min". Returns `{outline, words, wpm, minutes}`.

**`chunks(db, doc_id) -> list[Chunk]`: the parts, step by step**

1. The live sentences of the document in live paragraphs of live sections whose `hidden` is 0, in `ord` order. Hidden sections are left out entirely: they are never sent.
2. Consecutive sentences of the same section form one `(title, sentences)` pair.
3. Room is kept for the header: the sections are packed to `room = target - min(HEADER_ROOM, target // 8)`, starting with `target = CHUNK`. `_split_long(sentences, room // 2)` first cuts a sentence longer than half a part into pieces at the last space in its second half (or at the limit when there is none), so a code file on one line or a PDF without full stops becomes several pieces.
4. `_pack(sections, room)`:
   - the size of a section is its sentences' lengths plus one each, plus the title plus 4 (`## ` and a line break);
   - when the current part is not empty and the section would take it over the target, the part is closed;
   - a section that fits the target joins the current part whole;
   - a longer section is cut **between sentences**: pieces are closed when the next sentence would take them over the target, and every piece after the first has the title `<title> (continued)`. The last piece stays open, so the next small sections can join it. After `_split_long` no sentence is longer than half the room;
5. More than `MAX_CHUNKS` parts: the target grows by `GROW`, up to `MAX_CHUNK`, and the packing is done again. Still too many at `MAX_CHUNK`: `TooLong`.
6. Each part becomes a `Chunk`: `body` is, per section, `## <title>` and its sentences, one per line; `text` is the header `(Part <i> of <n>. Sections: <titles>)`, a line break and `body`. The header names at most `HEADER_TITLES` titles, each cut at 80 characters, then "and <n> more", so it fits the room kept for it.

A document with no text outside hidden sections has no parts: `chunks` returns `[]`, and `start` raises `Nothing`.

**The keys (`_keys`)**: the key of a part summary is `results.key(map prompt hash, part.body)`; the key of the digest is `results.key(reduce prompt hash, *every part key)`. So a new prompt version of either file, an edited sentence, a renamed section, a hidden or shown section, a merge-up or a split gives new keys, and the old digest is not shown. The header (the part number) is not in the key, so a part whose text did not change keeps its summary even when the number of parts changes, as long as its boundaries are the same. The keys leave out the AI mode, the model and the profile, and the digest key does not say which parts had no summary. `kept_digest(db, doc_id)` returns `results.find(FEATURE, …)` for the digest key, or `None` when a prompt is missing or the document is too long. The key is remembered per document in `_key_cache` with `_stamp` and both prompt hashes; the parts are computed again only when one of them changed.

**The map step: `_summarise_part(port, db, job, doc_id, name, chunk, key, prompt, failed=None) -> dict | None`**

1. A live kept part summary under `key`: it is returned. No call.
2. `_check`: Stop pressed, AI off, or the document removed raises `Stopped`. A new `call_id` is stored on the job, so Stop can cancel the call.
3. `guard.ask(port, db, "digest_map", prompt.text, [one Source], budget="digest_map", schema=MapOut, prompt_version=…, call_id=…)`. **One source per call: this part's `text`**, anchor `<doc_id>:<first>`, trust `imported`, named after `documents.source` (so a file of secrets is refused for a cloud call). Every guard of 1.2 applies; the budget of 16,000 characters is more than `MAX_CHUNK`, so a normal part is sent whole.
4. `CouldNotGenerate` (two answers that fail `MapOut`): returns `None`. The part is skipped, nothing is kept, and a later run asks for it again. Since 4.2 the failed call's `log_id` is appended to the `failed` list when one is given, so the digest can list it. Every other error goes up to `run`. Then `_check` again: an answer that arrives after Stop, the off switch or the removal of the document is not kept.
5. The first `MAX_POINTS` points: `text` capped, and a point whose text is empty after cleaning is skipped; the quote kept (capped) only when `guard.quote_in(quote, chunk.body, 5)` holds, else empty, with `verified` true or false.
6. The payload `{summary, points, keywords, sentence, titles, links, warning}`: the summary capped at 400; the keywords through `_clean_keywords` against this part's text. Kept at once with `results.keep(db, "digest_map", doc_id, key, …)`.

`_clean_keywords(words, within, links)`: each keyword through `safe_output` (capped at 40; addresses go to `links`), kept only when its `guard._plain` form is at least 3 characters, the keyword has a letter, its plain form is not only `percent` or `minus` (a sign word, as `%` becomes), and it is a whole word or phrase of `within` (`guard.word_in` against the `_plain` text of the part, or of every part for the digest: it must be found with a space, or the start or end of the text, on each side), each once, at most `MAX_KEYWORDS`.

**The reduce step and the job: `run(port, db, job, fresh)`**

1. `prompts.load` of both prompts, `chunks`, `job.total`, the keys, the document's `source` name.
2. For each part in order (**one call at a time**: a local model is never asked twice at once by one digest): `_check(port, db, job)`, which raises `Stopped` when `job.stop` is set, `ai_mode` is no longer `local` or `cloud`, or the document was removed; the job then ends `cancelled`. Otherwise `_summarise_part` with a fresh `failed` list, then `job.done += 1`. `part_logs` collects the call behind each part, in order: the kept summary's `log_id`, or the failed call's.
3. `_check` after the last part.
4. No part has a summary: `failed` with "Couldn't generate a usable answer.".
5. `job.step = "combining"`. One source per part that has a summary: anchor `<doc_id>:<first>`, trust `imported`, the text `(Part <i> of <n>. Sections: …)` (at most `HEADER_TITLES` titles, each cut at 60 characters, then "and more"), `Summary: …` and `Points:` with `- <point> — quote: “<quote>”` (a quote only when it was verified). Each source gets an equal share, `guard.BUDGETS["digest"] // <parts with a summary> - 20` characters: the header and summary are cut to it, then whole points are added while they fit. A point that does not fit is left out whole, so a quote is never cut in half and `guard.pack` cuts nothing (the log row says `trimmed: false`). **The document's own sentences are not in it**; what it holds of the document is section titles and the verified quotes.
6. Inside `results.once("digest", key)`: a live kept digest and `fresh` false: `done`, no call. Otherwise `_check`, a new `call_id` and `guard.ask(port, db, "digest", prompt.text, sources, budget="digest", schema=DigestOut, …)`, then `_check` again: an answer that arrives after Stop is not kept.
7. Key ideas: the first `MAX_IDEAS` with a non-empty text (capped). `_find_quote(db, doc_id, parts, quote, anchor)`: the parts whose `body` holds the quote (`quote_in`, at least 5 words), the one the model named first; for each, each section start in it is tried with `guard.verify_citations` (the quote must be in that sentence's section); the first one kept gives the sentence. A verified idea gets `quote` (capped) and `sentence`; an unverified one has neither key. **A quote counts only when it is, word for word, in the text of the document that was read**, whatever the model saw.
8. The payload: `summary` (capped at 1,200), `key_ideas`, `keywords` (the reduce answer's, checked against the text of every part), `difficulty`, `parts` (`{sentence, titles, summary, failed}` for every part, in order), `skipped_parts`, `status` (`verified` when there are ideas and all are verified, `partly` when some are, else `unverified`), `links` (the reduce answer's and every part's, each once), `warning` and `log_ids` (since 4.2: `part_logs` and then the reduce call's id; this digest's own calls only, failed part calls included). `results.keep`, replacing the old digest when `fresh` found one (the new row goes in first; see `results.keep`).
9. `job.state = "done"`.

Since 4.4 `run` also catches `privacy.PreviewNeeded` (the preview was switched on while the job ran, so a call it was not approved for came up): `failed`, "Stopped before sending more: start the digest again to see what will be sent." Nothing more is sent. Errors: `Cancelled`, `AIOff` and `Stopped` give `cancelled`; any other `AIError` (no model, no key, budget, offline, timeout, `changed`, …), `guard.Blocked` (a file of secrets, or a private document, for text that leaves this computer) and `TooLong` give `failed` with the error's sentence in `message`; anything else is logged and gives `failed` with "Something went wrong while writing the digest. It is in the log file." `call_id` is emptied at the end in every case.

**`start(port, db, doc_id, fresh, preview=None) -> (job, kept)`**: under `_jobs_lock`: a running job of that document is returned as it is (one job per document; a second press joins it). Then `chunks` (a `TooLong` goes to the caller; no parts raises `Nothing`). Without `fresh`, a kept digest is returned with the last job, if any, and nothing starts. Otherwise, since 4.4, `preview(parts)` runs first when the route gave one: `preview_first_call(port, db, doc_id, parts)` finds the first call the job will really make (the map call of the first part that has no kept summary, or, when every part has one, the combining call with `_reduce_sources` over the kept summaries) and hands it to `guard.preview`, which raises `PreviewNeeded` (the route then answers 428, and no job exists) unless this request is approved. Then a new `Job` replaces the old one in `_jobs`, and a daemon thread `digest-<id prefix>` runs `run` inside `contextvars.copy_context()`: the copy carries this request's approval, so the job's calls are covered by it (the later map calls send the same document; the combining call too, as its sources are anchored in it). `_reduce_sources(doc_id, name, read)` is the reduce step's source builder, shared by `run` and the preview. `fresh` reuses every kept part summary, so "Ask again" asks for the combining step and for the parts that had no summary, nothing else.

**Stop**: `POST …/digest/cancel` sets `job.stop` and, when a call is in flight, `port.cancel(job.call_id)`. `_check` looks at the event, the AI mode and the document before every part, right before and right after each model call, and before and after the combining call, so even when `port.cancel` finds nothing yet (the call is still being packed or queued), the answer is not kept. Switching AI off cancels every call (`port.cancel_all`). Removing the document (`server.api_doc_delete`) calls `digest.stop(doc_id)`, and Clear AI history calls `digest.stop()`.

**Routes** (registered by `digest.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body | Result |
|---|---|---|
| `GET /api/documents/{doc_id}/digest` | | `{facts, ai: {mode}, digest, job}`: `facts(...)`, the AI mode, the kept digest for the current keys (only with AI on and no job running; a failure there is logged and gives `null`), and `job.view()` of the document's last job or `null`. The job is read before the digest, so a job seen as `done` has already kept its digest. While a job runs no kept digest is looked for, so a poll does no heavy work. No model is called and nothing is written (apart from `_key_cache` in memory). The page polls it every 800 ms while a job runs |
| `POST /api/documents/{doc_id}/digest` | `{fresh?}` | `{job, digest}`: a kept digest (with `fresh` false) and no new job, or the job that runs now (new, or the one already running). The work happens in the background, so the answer comes at once |
| `POST /api/documents/{doc_id}/digest/cancel` | | `{cancelled: true}` when a job was running, else `{cancelled: false}`. 404 for an id that is not 32 hex characters or not a document (a removed document is still found) |

Status codes:

| Route | Code | When |
|---|---|---|
| GET | 200 | Always for a live document, whatever state the AI layer is in |
| GET, POST | 404 | Not 32 hex characters, missing or deleted document ("document not found") |
| cancel | 404 | Not 32 hex characters, or no such document ("document not found") |
| POST | 428 | Since 4.4: "Show what will be sent" is on, the text leaves this computer, and this request carries no approval for the first call; `{detail, preview}`, nothing sent, no job |
| POST | 409 | AI is off ("AI is off. You can switch it on in Settings."), also when a digest is kept; since 4.4, for text that leaves this computer, the document is private (`privacy.refusal`, said up front: the job would only fail in the background); a file of secrets refused by the preview's packing (`guard.Blocked`); or the document needs more than `MAX_CHUNKS` parts ("This document is too long for a digest (it would need more than 40 parts). Digest a part of it, or use the outline."); or the document has no text to digest ("This document has no text to digest (it is empty, or every section is hidden).") |
| POST | 422 | A body that is not `{fresh?: bool}` (FastAPI's own) |
| POST | 200 | Everything else. A failure of the run itself (no model, no key, budget, the server not running, a timeout, a file of secrets in cloud mode, no part summarised) is not an HTTP status: the job ends `failed` and its `message` says why |
| cancel | 200 | Any known document |

**Invariants**

- A map call holds exactly one source: one part, never more, at most `MAX_CHUNK` characters with its header. Hidden sections are never sent.
- The reduce call's sources are the part summaries, their points, the verified quotes and the section titles; never the document's sentences.
- `GET …/digest` never calls a model and never writes. A model is called only by a job, and a job starts only from `POST …/digest`, which the page sends only from a button. Nothing happens on import.
- `digest.py` calls `guard.ask`, never `port.complete`. The prompts hold no document text.
- Every string of a model that is stored went through `safe_output` (in `ask`, and again here) and a cap. A part's quote is kept only when it is in that part's text; a key idea's quote only when it is in a part's text and `verify_citations` keeps it; a keyword only when it is a whole word or phrase of the document's text, at least 3 characters, with a letter and not only a sign word. The difficulty is one of three fixed words.
- A part summary is kept as soon as it is made, so Stop, a failure, the off switch or a restart lose at most the call in flight.
- After Stop, the off switch, the removal of the document or Clear AI history, no new call goes out and no answer is kept (`_check`).
- At most one job runs per document; the parts of one job are asked one after the other.

**Known limits** (found in a review on 2026-11-25; "tried" means reproduced with a stand-in model server). The review also found that a removed document kept being sent, that Stop could miss the call it was meant to stop, that the combining call was trimmed from about eleven parts on, that one very long sentence was one very long part, that the header was not counted, that a document with nothing to digest failed with the wrong words, that a keyword was checked as a substring, that the GET computed the parts on every poll, that the `digest_map` profile allowed only 300 output tokens, that an empty point was kept, that Clear AI history did not stop a run and that its question did not name digests; all of these were fixed right after (the tests under "found by a review" in `tests/test_ai_digest.py`). What is still true:

- **Nothing was tried against a real model.** The plan's check "a 40-page paper yields an accurate outline" is about the parser's outline, which needs no model; the quality of summaries, key ideas and the difficulty guess from a real model is open.
- **A structure edit during a run is not seen by that run.** The parts are computed when the job starts; a section hidden, renamed or edited during a run is sent as it was read at the start. (Removing the document stops the run.)
- **A failed part is not retried by "Digest with AI".** The digest key does not depend on which parts had a summary, so once a digest with a skipped part is kept, the plain button returns it; "Ask again" (`fresh`) asks for the missing parts again. When no digest was kept (a stopped or failed run), the next run asks for them.
- **After a structure edit the digest is gone, not marked old.** Any edit gives new keys; the old rows stay in `ai_results` (live) but are never shown again. A rename or a split can move part boundaries, so more parts than the edited one are asked again.
- **A server restart forgets the job.** `_jobs` is in memory: after a restart `job` is `null`, the dialog shows **Digest with AI** (not **Go on with the digest**) and no "Stopped after …" line, but pressing it reuses the kept parts.
- `_jobs` keeps the last job of every document digested since the start, and `_key_cache` one key per document looked at; each is a few fields, so they grow with the number of documents, not with time.
- `stop` (removing the document, Clear AI history) sets the event but does not cancel the call in flight, so that one call runs to its end; its answer is not kept.
- The keys leave out the AI mode, the model and the profile, as for the other features.

#### Ask this document (`ask.py`)

Milestone 2.2 ("Ask this document"). The plan: "Ask box in the side panel … a cited answer; each citation jumps to the exact passage"; context "Top FTS5 sections, up to a token budget"; check "Says 'not found' when the answer isn't there; every quote verifies". Two layers. Without a model, and with AI off, the passages of the document that match the question, best first (`passages_for`, the full-text index of Phase 0): that is already an answer the reader can open. With AI on, and only when the reader presses **Ask**, one model call with the question and the best-matching sections, never the whole document; the model answers only from them or says "not found". The page side is `web/src/views/ask.ts` (chapter 5).

Decisions: the search is by words (FTS5 with BM25), not by meaning; no embeddings (that is the plan's Phase 3). An answer with no checkable quote is shown labelled "unverified" (the owner's decision of 2026-11-25, see *Milestone 2.1*). A question no section matches is "not found" without a model call.

**Names in `ask.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"ask"`: the task name for the port and the profile (`profiles.json`: the strong model, temperature 0, top-p 1.0, 800 output tokens), the budget name (`guard.BUDGETS["ask"]`, 24,000 characters), the prompt name and the `ai_results.feature` |
| `MAX_SECTIONS` | 5: the best-matching sections sent with a question (and the passages listed) |
| `MAX_CONTEXT` | `BUDGETS["ask"] - 2_000` = 22,000 characters of section text; the rest is room for the question and the fences |
| `MAX_CITATIONS` | 4: the citations of an answer that are kept; up to 12 (`MAX_CITATIONS * 3`) are looked at, so a repeated one does not push another out; the rest are dropped |
| `MIN_QUOTE_WORDS` | 4: a shorter quote proves nothing and is not shown (the prompt asks for 5 to 25) |
| `MAX_QUESTION` | `guard.USER_LIMITS["ask"]`, 1,000 characters |
| `CAPS` | Characters kept of what the model wrote: `answer` 1,200, `quote` 400 |
| `ID` | 32 lower-case hex characters: what a document id must look like before the database is asked |
| `NUMBER` | A number standing on its own (`3`, `71.2`, `1,5`), not part of a word or of a longer number |
| `ACRONYM` | A word in capitals of 2 to 8 characters, digits, `+` and `#` allowed after the first letter (`RL`, `AI`, `GPU`, `C++`, `C#`): short, but it matters |
| `WORD` | A word: a letter, then letters, digits, `_`, apostrophes and hyphens, in any script |
| `MAX_TERMS` | 8: the search words kept of a question |
| `Invalid` | A question that is empty or too long; the routes answer 422 with its sentence |
| `Citation`, `AskOut` | The schema of an answer: `found` (required), `answer` (up to 8,000), `citations` (at most 12 `Citation`s: `anchor` up to 80, `quote` up to 2,000). An answer outside it fails the schema: one retry, then 502 |
| `AskIn` | The body of the POST route: `{question (up to 100,000 characters), fresh: bool = false}`. The bound is far above `MAX_QUESTION`, so a question that is too long reaches `_question` and is refused in words |
| `_question(text)` | `guard.sanitize`, then every run of white space made one space. Empty: `Invalid("Type a question first.")`. Over `MAX_QUESTION`: `Invalid("Keep the question under 1000 characters.")` |
| `_cache_question(q)` | The question as the kept answer remembers it: lower case (`casefold`), every run of white space one space, a final `?`, `!` or `.` taken off. Other punctuation stays, so "Is C++ faster than C#?" and "Is C faster than C?" are two keys |
| `_stem(w)` | A light cut, for words in ASCII letters of more than three characters only: the first of the endings `ing`, `ies`, `es`, `ed`, `s`, `e` that leaves at least three letters is taken off (`s` not after `ss`, `us` or `is`; `ed` not after `ee`, so "speed" stays `speed`, a change made with 2.3: before, "speed" was cut to `spe`, which the prefix search widens to any word starting "spe"). "gate" and "gating" both become `gat`, "processes" `process`. Ask my library uses the same cut for the question and for the model's search words. A word in another script is kept as written, as the index holds it |
| `_terms(question)` | The search words, in this order: the numbers (`NUMBER`) and the acronyms (`ACRONYM`, lower-cased), kept however short; then the other words (`WORD`, lower-cased, apostrophes and hyphens at the ends taken off) of three characters or more that are not common words (`think.STOP`, also with the apostrophe removed), each through `_stem`, the longest first. Each once, at most `MAX_TERMS`. A question of only common words gives an empty string |
| `passages_for(db, doc_id, question, limit=MAX_SECTIONS)` | `passages.search_sections(db, _terms(question), limit, document_id=doc_id)`; no search words: no passages. No model, no write |
| `_around(rows, at, room)` | The sentences of a long section around the one that matched (`at`), below |
| `sources_for(db, doc_id, hits)` | One `guard.Source` per hit, below |
| `_citation(db, doc_id, c, sources)` | One citation, checked, below |
| `ask(port, db, doc_id, question, fresh=False)` | The feature, below |
| `register(app, db, port)` | The two routes |

**`search_sections` as Ask uses it** (chapter 3, section 4b.3): of the search words (at most 8 from `_terms`), the first 200 characters and at most 12 words are taken (`passages.MAX_QUERY`, `MAX_WORDS`), each quoted and given a `*`, so any word typed is read as a plain word (FTS5 syntax such as `OR`, `NEAR(`, `*` or quotation marks is just text) and the start of a word is enough (`router` finds `routers`). First every word must be in the section (`AND`); when no section has them all, any of them (`OR`). Sections are ranked by BM25 with the title weighted 4 to 1. Hidden sections (the references) are in the index and can match. Each hit has the sentence that holds the most search words (the jump target) and its first 240 characters as the snippet.

**`sources_for(db, doc_id, hits) -> list[Source]`**

1. For each hit, the live sentences of the live paragraphs of that section, in `ord` order, and their size (each sentence plus a line break). A section with none is skipped.
2. The sections are placed shortest first. Each gets `room = left // <sections still to place>`, where `left` starts at `MAX_CONTEXT` and loses what each placed section used, so room a short section does not use goes to the longer ones (with five hits the even share is 4,400 characters; with one, 22,000). Together they stay under the 24,000-character budget, so `guard.pack` cuts nothing more (it cuts only when the sources together are over it).
3. The text is `(Section: <title>)`, a line break, and then the whole section, one sentence per line, when it fits in `room` less the title line. A longer section is cut by `_around` to the sentences around the one the search found (`hit["sentence"]`, the jump target), and marked `Source.cut` (the log row then says `trimmed`).
4. Anchor `<doc_id>:<the section's first ord>`, trust `imported`, named after `documents.source` (so a file of secrets is refused for a cloud call).
5. The sources come back in the order of the search, best first.

**`_around(rows, at, room) -> (text, cut)`**: starts at the sentence whose `ord` is `at` (the first sentence when it is not there) and grows outwards, one sentence after it and one before it in turn, while the next one still fits in `room`; it stops when neither side fits. `[…] ` goes in front when the start of the section is left out, ` […]` at the end when its end is. A single sentence longer than `room` is cut at the last space before `room` (and gets no ` […]` when it is the last sentence of the section, though it is marked `cut`).

**`_citation(db, doc_id, c, sources) -> dict`**

1. The sources whose text holds the quote (`guard.quote_in(quote, source.text, MIN_QUOTE_WORDS)`: at least 4 words and 12 characters of `_plain` text, on whole words), the one whose anchor the model named first.
2. For each, `guard.verify_citations(db, [{anchor: source.anchor, quote}])`: the quote must be in that section of the live document. The first one kept gives `{verified: true, quote (safe_output, capped at 400), sentence (the sentence that holds the quote), section_title, document_id}`.
3. None: `{verified: false}`, with no quote.

So a quote counts only when it is in the text `sources_for` built (a part of a section it cut off does not count) and in the document as it is now. That text is also what the model got: `guard.pack` cuts nothing of sources that fit the budget.

**`ask(port, db, doc_id, question, fresh=False)`, step by step**

1. `_question` (422 for an empty or too long question). This comes first, so a question that is not one is a 422 with AI on or off.
2. `ai_mode` is not `local` or `cloud`: `AIOff` (409). This comes before a kept answer is looked for, so with AI off nothing a model wrote is served.
3. `passages_for`. **No hit: `{question, found: false, answer: "", citations: [], status: "not_found", searched: 0, links: []}`**, at once. No model call, no `ai_log` row, nothing kept (so it has no `id`).
4. `sources_for`, then `prompts.load("ask")`.
5. The key: `results.key(prompt.hash, _cache_question(question), *("<anchor>\n<text>" for each source as cut))`. The same question typed in another case or spacing, or with or without a final `?`, `!` or `.`, is the same key; other punctuation makes another key.
6. Inside `results.once("ask", key)`: a live kept answer and `fresh` false: it is returned. No call.
7. `guard.ask(port, db, "ask", prompt.text, sources, budget="ask", question=question, schema=AskOut, prompt_version=…)`. `pack` puts each source in its fence and the question after them in `<question>` … `</question>`: cleaned and capped again (`user_text`), redacted in cloud mode, and passed through `_defuse`, so `</question>`, `<system>` or `<source …>` typed in the question lose their `<` and cannot close or open a fence. The question is never in the instruction.
8. The model says `found` and the answer is not empty after `safe_output`: the first `MAX_CITATIONS * 3` citations through `_citation`, where the same passage cited again counts once (a verified one by its sentence and `_plain` quote, an unverified one by its `_plain` quote), and the first `MAX_CITATIONS` of what is left are kept; the answer capped at 1,200. Status `verified` when there are citations and every one is verified, `partly` when some are, `unverified` when none is (also when the model gave none).
9. Otherwise (`found` false, or an empty answer): **"not found" wins over anything the model wrote beside it**: `{found: false, answer: "", citations: [], status: "not_found"}`.
10. Both: `searched` (the number of sections sent), `links` (the addresses the model wrote, each once; never opened), `warning`. `results.keep(db, "ask", doc_id, key, payload, …, replaces=<the kept row when fresh>)`: the new row goes in first.

**Routes** (registered by `ask.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body / query | Result |
|---|---|---|
| `GET /api/documents/{doc_id}/ask` | `?q=` | `{passages, ai: {mode}}`: `passages_for` (each passage: `document_id`, `document_title`, `section_id`, `section_title`, `sentence`, `snippet`, `score`) and the AI mode (`off`, `local` or `cloud`). Works with AI off. No model, no write |
| `POST /api/documents/{doc_id}/ask` | `{question, fresh?}` | `{result}`: the kept answer, or a new one. A plain `def`, so it runs on a worker thread |

| Route | Code | When |
|---|---|---|
| GET, POST | 200 | A live document and a question of 1 to 1,000 characters (POST: and AI on; a "not found" is a 200) |
| GET, POST | 404 | Not 32 hex characters, missing or deleted document ("document not found") |
| GET | 422 | An empty or too long question (`Invalid`) |
| POST | 422 | An empty or too long question (`Invalid`), with AI on or off, its `detail` a sentence; a body that fails `AskIn` (no `question`, over 100,000 characters; FastAPI's own, its `detail` a list) |
| POST | 409 | AI off (also when an answer is kept), no model, no key, budget used up, a call cancelled by the off switch, a file of secrets in cloud mode (`guard.Blocked`) |
| POST | 504 | The model took too long |
| POST | 502 | Two answers that fail `AskOut`, a provider error |

**Invariants**

- What is sent: at most `MAX_SECTIONS` sections that match the question's words, at most `MAX_CONTEXT` characters of their text in all, each under its title, and the question. Never a section that does not match. A document of one section (pasted text without headings) is that one section: whole when it fits, else the sentences around the one that matched, up to 22,000 characters with its title.
- A question that matches no section reaches no model.
- The question is the reader's own text, but it is still fenced (`<question>`), cleaned, capped and defused, and redacted in cloud mode. It is never part of the instruction.
- A quote is shown with ✓ only when it is in the text `sources_for` built (`quote_in`) and `verify_citations` keeps it; `guard.pack` sends that text uncut, since it fits the budget. A ✓ proves the words are in the document, not that the answer follows from them; the page says so.
- "Not found" wins: an answer or citations written beside `found: false` are dropped.
- `ask` checks the off switch before it looks for a kept answer. `GET …/ask` never calls a model and never writes.
- Anything the answer depends on is in the key: the prompt, the question in `_cache_question` form, and every source as sent (anchor and cut text). An edit of a sentence in a matched section, a change in which sections match, or a sentence that moves the section's first `ord` gives a new key, so a stale answer is not shown. A kept answer's citations need no new check: the text they were checked against is part of the key.
- `ask.py` calls `guard.ask`, never `port.complete`, and is in `FEATURES` of `tests/test_ai_citations.py`.

**Known limits** (found in a review on 2026-11-25 and reproduced with a script against a temporary `READHOLD_HOME` and a stand-in model server). The review also found that a long section was sent from its start (so the sentence that matched could be left out), that a question of only common words fell back to the raw question and sent sections that merely contain "is", that words under three letters (`RL`, `AI`) were dropped, that an Arabic word lost its "ال" in the search but not in the index, that the numbers of a long question came last and were dropped, that plural folding missed ("processes" did not find "process") and "gate" did not find "gating", that the same passage cited four times was four ✓, that `C++` and `C#` were one key with `C`, that an empty question was a 409 with AI off and a very long body a 422 with a list, and that the confirm text of Clear AI history did not name answers; all of these were fixed right after (the tests under "found by a review of 2.2" in `tests/test_ai_ask.py`; the page side is in chapter 5). Found later, while these docs were brought up to date, and fixed: `guard.pack` gave every source an equal share of the budget (4,800 characters with five) and cut a longer one from its start, so a long section beside short ones lost the end of its window around the matched sentence, and a quote from the part cut off still came back `verified` (`_citation` checks `sources_for`'s text). Now `pack` cuts only when the sources together are over the budget, and then the long ones first (the guardrails above, `pack` step 3), so Ask's sources go out as `sources_for` built them (`test_a_long_section_beside_short_ones_still_sends_the_matching_sentence`: a 700-sentence section whose last sentence answers, with four short matching sections). What is still true:

- **Hidden sections are searched and sent**, on purpose: "who wrote …" is a fair question. Unlike the digest, `passages_for` does not leave out sections with `hidden = 1`, so a question about a reference ("Who wrote Memory tokens in 2020?") sends the References. In clean view a jump to such a passage cannot show the collapsed section (the pacer moves on to the next paced sentence).
- **Words, not meaning**: a synonym, or a form of the word beyond the light cut of `_stem`, is not found. A fair question in other words than the document's may well find nothing, and is then "not found" without a model call.
- **The cut can widen a search**: `_stem` and the prefix search together make "time" (`tim*`) also find "timing" and "timid".
- **When no section holds all the search words**, any one of them is enough (`search_sections` falls back to `OR`), so up to five weakly related sections can be sent for a long question.
- In the search, `C++` and `C#` are the word `c` (`passages.WORD` keeps letters and digits only), so they match any word that starts with c.
- The key leaves out the AI mode, the model and the profile, as for the other features: after switching models the kept answer comes back until **Ask again**.
- Two **Ask again** presses at the same moment are two calls.
- Nothing was tried against a real model; the quality of answers, and how often a real model says "not found" when it should, are open.

#### Ask my library (`library.py`)

Milestone 2.3 ("Ask my library with a bounded loop"). The plan (section 3, "The one place an agent loop is justified"): "Tools: `search_library(keywords)` and `read_section(anchor)`. Both are read-only. At most 3 steps, then it must answer or reply 'not found in your library'. Every other feature is a single call." Its check: "Answers multi-document questions within 3 steps". Two layers. Without a model, and with AI off, the passages of every document and the notes that match the question (`matches`). With AI on, and only when the reader presses **Ask**, the loop: the model starts with the best matches and works in at most `MAX_STEPS` steps, each one call; at each step it answers or uses one of two tools, which only read. The page side is `web/src/views/libraryask.ts` (chapter 5, section 5.8).

Decisions: the tools are named `search` and `read` (the plan's `search_library` and `read_section`), and `read` brings in more of a section around one sentence (twice the room of a first copy), or a whole note, not always the whole section, so one long section cannot fill the budget. Files of secrets are left out of a cloud call, not refused, because one such file among many matches should not stop a question across the library. The search is by words, as for Ask this document.

**Names in `library.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"library"`: the task name for the port and the profile (`profiles.json`: the strong model, temperature 0, top-p 1.0, 900 output tokens), the budget name (`guard.BUDGETS["library"]`, 24,000 characters), the prompt name, the `ai_results.feature` and its `target_id` |
| `MAX_STEPS` | 3: calls in one question, the last of which must answer |
| `MAX_SECTIONS`, `MAX_NOTES` | 5 document sections and 3 notes that one search brings in (and that `matches` lists) |
| `MAX_SOURCES` | 10: sources sent with one call; when there are more, the oldest are dropped (they stay checkable) |
| `MAX_CONTEXT` | `BUDGETS["library"] - 2_000` = 22,000 characters |
| `ROOM` | `MAX_CONTEXT // MAX_SOURCES` = 2,200: the characters one source may hold when it is first added; `read` gives twice that |
| `MAX_CITATIONS` | 5: the citations kept; up to 15 (`MAX_CITATIONS * 3`, also the schema's bound) are looked at, a repeat counting once |
| `MIN_QUOTE_WORDS` | 4: a shorter quote proves nothing |
| `NOTE_SCAN` | 5,000: the most recently changed notes a search looks at |
| `DOC_ANCHOR`, `NOTE_ANCHOR` | `<32 hex>:<1 to 7 digits>` and `note:<32 hex>`, matched in full: the only anchors `read` and the checks accept |
| `CAPS` | `answer` 1,400, `quote` 400, `snippet` 200 characters |
| `Step` | The schema of one step: `action` (`Literal["answer", "search", "read"]`), `keywords` (up to 300), `anchor` (up to 120), `found`, `answer` (up to 8,000), `citations` (at most 15 `ask.Citation`s). An answer outside it fails the schema: one retry, then 502 |
| `_note_words`, `_note_lock` | The per-note cache: note id → (`updated_at`, its `_plain` words, sorted and each once), made once per change of the note, under a lock |
| `_words_of(note)` | A note's words from the cache, or made from `"<title> <body>"` through `guard._plain` and stored |
| `_has_prefix(words, prefix)` | `bisect_left` in the sorted words: is there a word that starts with `prefix`? |
| `_note_hits(db, terms)` | The notes for some search words, below |
| `_snippet(text, terms)` | 200 characters of a note's text from 60 before the first search word found (`re.search` with `re.I` on the text itself, so case folding cannot shift it), white space made single, "…" in front when it does not start at 0 |
| `matches(db, question)` | No model: `_terms(question)`; none: `[]`. Else the sections (`passages.search_sections(…, limit=MAX_SECTIONS)`, each with `kind: "document"`), then the notes (`kind: "note"`, `note_id`, `title`, `snippet`) |
| `NOTE_HEAD` | `"(Your note: {title})\n"`, the first line of a note source |
| `_section_source(db, doc_id, ord_, room=ROOM)` | A `guard.Source` for the section around one sentence of a live document, below, with `center` set to that sentence; `None` otherwise |
| `_note_source(db, note_id, room=ROOM)` | A `guard.Source` for a live note, below; `None` otherwise |
| `search(db, words)` | Tool 1 |
| `read(db, anchor, around=None)` | Tool 2 |
| `_body(anchor, text)` | What may be quoted from a sent text: for a note anchor, the text after its first line (the `NOTE_HEAD`); else the text |
| `_citation(db, c, sent)` | One citation, checked, below |
| `still_true(db, kept)` | Does a kept answer still hold, below |
| `Run` | One running question: `stop` (a `threading.Event`) and `call_id` (the call in flight). `eq=False`, so each run is itself in a set |
| `_runs`, `_runs_lock` | The running questions |
| `cancel(port)` | Stop every running question: set each `stop`, and `port.cancel(call_id)` for the call in flight. `True` when one was running |
| `_doc_of(src)` | The document id of a source's anchor (to count files of secrets per file) |
| `ask(port, db, question, fresh=False)` | The feature, below |
| `_loop(…)` | The steps, below |
| `AskIn` | The body of the POST route: `{question (up to 100,000 characters), fresh: bool = false}`, as in `ask.py` |
| `register(app, db, port)` | The three routes |

From `ask.py` it uses `_question` (cleaned, 1 to 1,000 characters, else `Invalid`), `_terms` (the search words), `_cache_question`, `_around` and `Citation`.

**The notes search (`_note_hits`)**

1. The search words, each through `guard._plain`; none: `[]`.
2. The `NOTE_SCAN` most recently changed live notes (`pages`, `deleted=0`, `ORDER BY updated_at DESC`).
3. For each, its sorted words (`_words_of`, cached), and a score: how many search words are the start of one of its words (`_has_prefix`). A word in the title counts as much as one in the text.
4. When some note has every word, only notes with every word are kept; else any note with one. Highest score first (among equal scores, the most recent first), at most `MAX_NOTES`.

The cache makes a second search over 2,000 notes take well under a second (the first one builds it); a note's entry is made again when its `updated_at` changes. Entries of deleted notes are not removed.

**The sources**

- `_section_source`: the sentence must be live, in a live paragraph, section and document. The rows are the live sentences of the live paragraphs of its section, in `ord` order. The text is `(Document: <title>. Section: <title>)`, a line break, and `_around(rows, ord_, max(200, room - <header>))`: the sentences around that one, growing outwards, ` […]` where cut. Anchor `<doc_id>:<the section's first ord>` (so every copy of one section has one anchor), trust `imported`, named after `documents.source` (for the cloud rule), `cut` set when it is shortened, and `center` set to the sentence the copy is built around (so a later read can grow around it).
- `_note_source`: a live note. `NOTE_HEAD` with the title (white space made single, at most 200 characters), then the text, at most `max(200, room - <header>)` characters. Anchor `note:<id>`, trust `yours`, no file name, `cut` when it is shortened.

**The tools**

- `search(db, words)`: `_terms(words)`; none: `[]`. A `_section_source` for each hit of `passages.search_sections(…, limit=MAX_SECTIONS)` (at the sentence that holds the most search words), then a `_note_source` for each of `_note_hits`. The words reach SQLite only as an FTS5 query built by `passages` (each word quoted) and as plain `?` parameters.
- `read(db, anchor, around=None)`: the stripped anchor must match `DOC_ANCHOR` (a `_section_source`, `room = ROOM * 2`, around the sentence `around` when it is given and in the same section as the anchor's sentence, else around the anchor's sentence; `_loop` passes as `around` the sentence the first copy of that source was built around, so reading the anchor the model was given, the section's first sentence, keeps the passage the search matched) or `NOTE_ANCHOR` (a `_note_source`, `room = ROOM * 2`) in full. Anything else (a path, a link, a removed document, an unknown note or sentence, an empty string) is `None`, which adds nothing.

Both only read; neither takes a path, a file name or an address.

**`ask(port, db, question, fresh=False)`, step by step**

1. `_question` (422). Then `ai_mode` not `local` or `cloud`: `AIOff` (409), before anything kept is looked at.
2. `allowed(sources)`: for text that leaves this computer (`cloud = guard.leaves(port)`, since 4.5), a source whose file name is a file of secrets (`guard.sensitive_name`) is left out and its document id added to `secret_files` (a set, so each file counts once however often it matches, over every step); since 4.4 a source that `privacy.withheld` says must stay here (a private document or note, or a copy of one in your note) is left out the same way and its document id (or, for a note, its anchor) added to `private`. Both happen before the source takes a place, is counted as "added", or is told to the model. The rest pass. With a model on this computer all pass.
3. `first = allowed(search(db, question))`. **Empty: `{question, found: false, answer: "", citations: [], status: "not_found", searched: 0, steps: [], links: [], left_out, private_left_out}`**, at once: no prompt, no model call, no `ai_log` row, nothing kept.
4. `prompts.load("library")`; the key: `results.key(prompt.hash, mode, _cache_question(question), *("<anchor>\n<text>" for each first source))`.
5. A `Run` goes into `_runs` (and out again in `finally`).
6. Inside `results.once("library", key)`: a kept row (`results.find(db, "library", "library", key)`) is returned when `fresh` is false **and** `still_true` holds. Otherwise `_loop`, which replaces the kept row (if any) when it keeps its result.

**`_loop`, step by step**

1. `sources` starts as `first` (through `add`). `add(new)` passes `new` through `allowed`; a source with a new anchor is appended, one whose anchor is there already replaces it only when its text is longer (a `read` of more); each counts as added. Then `del sources[:-MAX_SOURCES]`: the oldest go first. `add` also keeps `centers` (anchor → the `center` of the first copy of that source). `sent` maps every anchor ever sent to its text: what a quote may come from. When a longer copy does not contain the shorter one, both are kept, joined by a line break, since both were sent.
2. For each step `k` of 1 to 3: `run.stop` set: `Cancelled`. The instruction is the prompt, `"Step k of 3."`, on the last step `" This is the last step: answer now, with \"found\": false if the sources do not say."`, and after a tool the `note` of the step before. Each source goes into `sent`. A new `run.call_id`, then `guard.ask(port, db, "library", instruction, sources, budget="library", question=q, schema=Step, prompt_version=…, call_id=…)`. `run.stop` set when it returns: `Cancelled`, so a late answer is not kept. Its links and `log_id` are collected.
3. `action == "answer"`: the step is `{step, action: "answer"}` and the loop ends.
4. On the last step any other action: `{step, action, added: 0, ran: false}`, no tool runs, and the result is "not found".
5. `search`: `add(search(db, keywords))` with the model's raw keywords (`search` runs `_terms` itself, so the words are cleaned once; nothing runs when `_terms(keywords)` is empty); the step is `{step, action: "search", keywords: <_terms(keywords), safe_output, 200 characters>, added}`. The note for the next instruction is only `"Your search added N new source(s)."`: **the words the model chose never go into its instructions.**
6. `read`: `add([read(db, anchor, centers.get(anchor))])` (nothing when `read` gives `None`); the step is `{step, action: "read", added}` and the note says that more was added, or that nothing was ("that anchor is not a section or a note of the library, or nothing more of it fits").
7. After the loop: when the last data is an answer with `found` and a non-empty answer, the first 15 citations through `_citation(db, c, sent)`, a repeat (the same note or document and sentence and `_plain` quote, or the same unverified `_plain` quote) counting once, then the first `MAX_CITATIONS`. Status `verified` (citations, all verified), `partly` (some), `unverified` (none, or no citation). The answer through `safe_output`, capped at 1,400. Otherwise `{found: false, answer: "", citations: [], status: "not_found"}`.
8. Both: `steps`, `searched` (`len(sent)`: every source sent over the steps), `links` (each once), `warning` (of the last call), `left_out` (`len(secret_files)`), `log_ids` (one per call). `results.keep(db, "library", "library", key, payload, prompt.version, <the last log_id>, replaces=<the kept row>, target_type="library")`. `ask` returns the kept row with `private_left_out` (`len(private)`) added; that count is not in the payload, so a kept answer returned later has none.

**Checking**

`_citation(db, c, sent)`:

1. The anchors of `sent` whose quotable text (`_body`: a note without its header line) holds the quote (`guard.quote_in`, at least 4 words and 12 characters of `_plain` text, on whole words); the one the model named first.
2. For a note anchor: the live note's text must hold the quote too (`quote_in(quote, body)`): `{verified: true, kind: "note", note_id, note_title, quote}`. Because the header is cut off first, a quote that runs from the title into the text is not found.
3. For a document anchor: `verify_citations(db, [{anchor, quote}])` (the quote in that section of the live document; it gives the sentence that holds it): `{verified: true, kind: "document", document_id, document_title, section_title, sentence, quote}`.
4. None: `{verified: false}`.

`still_true(db, kept)`: for every verified citation of a kept answer, a note quote must still be in the live note's text, and a document quote must still pass `verify_citations` at `<document_id>:<sentence>`. One that fails makes the kept answer stale, and `ask` runs the loop again. This also covers sources that only a later step brought in, which are not part of the key.

**Stop**

`POST /api/library/ask/cancel` calls `cancel(port)`: every `Run` in `_runs` gets `stop` set, and its call in flight is cancelled through `port.cancel(call_id)` (`Cancelled` from the port, 409 "Stopped."). The loop also checks `stop` before each call and after each answer, so a step that finished just as Stop was pressed is not followed by another, and nothing is kept. Stop applies to every library question that is running, not one.

**Routes** (registered by `library.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body / query | Result |
|---|---|---|
| `GET /api/library/ask` | `?q=` | `{passages, ai: {mode}}`: `matches` (documents: `kind`, `document_id`, `document_title`, `section_id`, `section_title`, `sentence`, `snippet`, `score`; notes: `kind`, `note_id`, `title`, `snippet`) and the AI mode (`off`, `local` or `cloud`). Works with AI off. No model, no write |
| `POST /api/library/ask` | `{question, fresh?}` | `{result}`: the kept answer, or a new one. A plain `def`, so it runs on a worker thread |
| `POST /api/library/ask/cancel` | | `{cancelled: bool}` |

| Route | Code | When |
|---|---|---|
| GET, POST | 200 | A question of 1 to 1,000 characters (POST: and AI on; a "not found" is a 200) |
| GET | 422 | An empty or too long question (`Invalid`) |
| POST | 422 | An empty or too long question (`Invalid`), with AI on or off, its `detail` a sentence; a body that fails `AskIn` |
| POST | 409 | AI off (also when an answer is kept), no model, no key, budget used up, a call cancelled by **Stop** or the off switch, `guard.Blocked` |
| POST | 504 | The model took too long |
| POST | 502 | Two answers that fail `Step`, a provider error |
| cancel | 200 | Always |

**Invariants**

- At most `MAX_STEPS` calls per question; no tool runs on the last one. A new action or a longer loop needs a decision, not a constant change: it is the plan's only agent loop.
- The tools only read, and take only words (cleaned by `_terms`, passed as parameters) and anchors that match `DOC_ANCHOR` or `NOTE_ANCHOR` in full; never a path, a file name or a link.
- The model's words never go back into its instructions: after a tool it is told only how many sources were added. Its search words are shown to the reader as text, cleaned.
- Every text that was sent stays in `sent`, so a quote from a source dropped by `MAX_SOURCES` still checks; a quote must also be in the library as it is now (`verify_citations` for a document, the live note's text for a note).
- In cloud mode no source of a file of secrets, and no private item or copy of one, reaches `guard.ask` (`allowed`, before `pack`, so `pack`'s `Blocked` is not reached for them). A question is never refused for a private match: it is left out, counted, and the rest is asked.
- `ask` checks the question, then the off switch, before it looks for a kept answer; a kept answer is returned only while `still_true`. `GET /api/library/ask` never calls a model and never writes.
- The key holds the prompt, the mode, the question in `_cache_question` form and every first source as sent; what later steps brought in is covered by `still_true`, not by the key.
- `library.py` calls `guard.ask`, never `port.complete`, and is in `FEATURES` of `tests/test_ai_citations.py`.

**Known limits** (a review after building, on 2026-11-25, reproduced its findings with a stand-in model server). The review found that `read` almost never added anything (a source already sent was not replaced by its longer copy), that a kept answer could still cite documents or notes removed or changed later, that the note search took about 12 s with 2,000 notes (it is now cached per note and searched by sorted prefixes), that there was no Stop, that the model's search words went into its system instructions, that a file of secrets was counted once per match, that a search asked for on the last step still ran, that a note quote could join the title and the text, and that the snippet could be shifted by case folding; all were fixed right after (the tests under "found by a review of 2.3" in `tests/test_ai_library.py`). What is still true:

- **Up to six requests.** Each of the 3 steps may be retried once by the port (a server error, or an answer that fails `Step`), so a question can make up to 6 requests and take about 6 × `ai_timeout_s`.
- **Tool names and reach.** The plan's `search_library` and `read_section` are `search` and `read`, and `read` returns more of a section around a sentence (`ROOM * 2`), not always the whole section.
- **The key leaves out the provider and the model** (it includes the mode): after switching models within a mode, a kept answer comes back until **Ask again**.
- **A quote from a part that `guard.pack` cut** still counts: `sent` holds the sources as built, and when one call is over the budget (a read copy of 4,400 characters beside nine of 2,200 is just over 24,000) `pack` cuts the longest at their end. Such a quote is real library text, but the model may not have seen it.
- **Files of secrets take places**: in cloud mode they are left out after the search, so they still take places among the 5 section hits, and fewer sections may be sent.
- **Notes beyond the `NOTE_SCAN` most recent are not searched**, and `_note_words` keeps an entry for a deleted note until the app restarts.
- **Per-scope consent and private documents** (plan 6.4) came with milestone 4.4: in cloud mode `#private` items and copies of them are left out, and with `ai_cloud_only_tagged` only `#cloud` items go (*Privacy controls* below). A private match still takes one of the five places of the search, so fewer sections may be sent.
- Two **Ask again** presses at the same moment are two runs of the loop; Stop stops every running question.
- Nothing was tried against a real model; the plan's check "answers multi-document questions within 3 steps" was tried only with a stand-in.

Found while the 2.3 docs were written, and fixed since:

- **`read` keeps the passage the search matched.** A section source's anchor is `<doc>:<the section's first ord>`, and the model is asked to read "that source's anchor", so `read` used to re-centre a long section on its first sentence and the window around the sentence that matched was lost. Now `_section_source` sets `center` (the sentence the copy is built around), `_loop` keeps `centers` (anchor → that sentence), and `read(db, anchor, around)` grows the longer copy around it, but only when that sentence is in the same section as the anchor. `sent` keeps both copies when the longer one does not contain the shorter (joined by a line break). Test: `test_reading_the_anchor_it_was_given_keeps_the_sentence_that_matched`.
- **The model's search words are cleaned once.** `_loop` used to pass `_terms(keywords)` to `search`, which applies `_terms` again, so `_stem` ran twice ("phases releases" was searched as `pha relea`). Now `_loop` passes the raw keywords and `search` runs `_terms` itself; the step line shows `_terms(raw)`. Test: `test_the_models_search_words_are_cleaned_once`.

#### Study notes (`notes.py`)

Milestone 2.4 ("Study notes writer and flashcards"). The non-AI versions already exist: the summary sheet gathers your highlights, and highlights and questions become review cards on their own. With AI on, and only when the reader presses **Write**, a model drafts study material from one of two sources, the reader's highlights in this document (with the notes on them) or one section, in one of three kinds: `notes` (study notes, one idea each), `cards` (flashcards, a question and its answer) and `quiz` (a short self-quiz, answered by the reader first). Every item must rest on a quote that is in the text as it was sent; an item without one is shown labelled and cannot be kept. Nothing is saved until the reader keeps items. The page side is `web/src/views/studynotes.ts` (chapter 5, section 5.6).

Decisions (most from an independent review after building): a quote is checked against the text as sent (`Result.sent`), so a quote from the cut-off end of a long highlight is not verified; the quote shown and kept is the document's own sentence(s) (`_own_words`), not the model's copy; `[[links]]` and `#tags` the model wrote become plain characters in the note (`_inert`), while what the reader typed stays live; keeping is once (the indices go into the result's `kept`, a line already in the note is not appended, cards are insert-only and a card with the same question, live or deleted by the reader, is skipped and counted as `skipped`); a label line above each kept batch, unless the note still ends with the last batch as written; a card carries its passage on the back; documents with the same title get their own note and no link by title; a long section is sent around the sentence the reader is at (`at`); errors of the accept route are 409, like the write route, and a malformed body stays 422.

**Names in `notes.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"notes"`: the task name for the port and the profile (`profiles.json`: the strong model, temperature 0.5, top-p 0.95, 2,400 output tokens), the budget name (`guard.BUDGETS["notes"]`, 16,000 characters), the prompt name and `ai_results.feature` |
| `KINDS` | The instruction appended to the prompt for each kind (`notes`, `cards`, `quiz`); see `prompts/notes_v1.md` above |
| `MAX_HIGHLIGHTS` | 40: the highlights sent, the first 40 by sentence; the rest are counted in `left_out` |
| `MAX_ITEMS` | 10 items kept of an answer (20 looked at) |
| `MIN_QUOTE_WORDS` | 4: a shorter quote proves nothing |
| `MAX_CONTEXT` | `BUDGETS["notes"] - 2_000` = 14,000: the room for one section |
| `CAPS` | `text` 300, `answer` 400, `quote` 400 characters |
| `MAX_RUN` | 8: the longest run of sentences `_own_words` looks through |
| `LABEL` | The label line above a kept batch: "*Written by the AI model from your reading. Each line links to the passage it rests on: check it, and change it into your own words.*" |
| `OURS` | The pattern of one kept item as `accept` writes it (`- <line>` and `  > <quote> — <link>`) |
| `Invalid`, `NotFound`, `Unchecked` | 409, 404, and 409 "Only items whose passage was checked can be kept." |
| `Item`, `NotesOut` | The schema: `items` (at most 20), each `text`, `answer`, `anchor`, `quote` |
| `WriteIn` | `{source: "highlights" \| "section", kind: "notes" \| "cards" \| "quiz", section_id (up to 40), at (≥ 0, optional), fresh}` |
| `Chosen`, `AcceptIn` | `{items: [{index, text, answer}] (at most 20), keep_as: "notes" \| "cards" \| null}`; `keep_as: "cards"` keeps a quiz question as a card |

**What the model reads**

- `_highlights(db, doc_id)`: the first `MAX_HIGHLIGHTS` live highlights by sentence. Each is a source `<doc>:<sentence>`, trust `imported`, text "(Highlighted as <type>)" and the highlight's text, named after `documents.source` (for the cloud rule). A highlight with a note adds a second source `hlnote:<doc>:<sentence>`, trust `yours`: "My note on that passage: …". With no highlights, `write` raises `Invalid` ("There are no highlights in this document yet. …") before any call.
- `_section(db, doc_id, section_id, at)`: one live section of this document (else `NotFound`, 404), as one source `<doc>:<its first ord>` with "(Section: <title>)" and its live sentences. A long one is cut with `ask._around` to `MAX_CONTEXT`, around the sentence `at` when it is in the section, else from its start, and has `Source.cut`. A section with no sentences is `Invalid`.

**`write(port, db, doc_id, source, kind, section_id="", fresh=False, at=None)`, step by step**

1. `ai_mode` not `local` or `cloud`: `AIOff` (409), before anything kept is looked at.
2. The sources (above). The key: `results.key(prompt.hash, KINDS[kind], source, section_id, *("<anchor>\n<text>" for each source))`. For highlights, `unsent` = live highlights past the first 40.
3. Inside `results.once("notes", key)`: a kept row is returned unless `fresh`.
4. One `guard.ask(port, db, "notes", prompt + KINDS[kind], sources, budget="notes", schema=NotesOut, prompt_version=…)`. Many long highlights can be over the budget, and `pack` then cuts them at their end (`trimmed`) or leaves the last ones out (`left_out`).
5. The first 20 items through `_checked`. A card or a quiz question without an answer is dropped; for notes the answer is emptied. At most `MAX_ITEMS`.
6. Status `verified` (items, all verified), `partly` (some), `unverified` (none, or no items). `cut` is the log's `trimmed`; `left_out` is `unsent` plus the sources `pack` left out.
7. `results.keep(…, replaces=<the kept row>)` with `kept: []`.

**Checking: `_checked(db, doc_id, item, sources, sent)`**

1. `text` and `answer` through `safe_output` and their caps.
2. The imported sources whose text **as sent** (`Result.sent`) holds the quote (`guard.quote_in`, at least 4 words and 12 characters, whole words); the one the model named first. A `yours` source (the reader's note) never verifies an item.
3. For each: `verify_citations` at that anchor. The first that keeps it gives `verified: true`, the `sentence` that holds the quote, and the `quote`: `_own_words(db, section_id, sentence, quote)`, the shortest run of the section's live sentences, from that sentence on and at most `MAX_RUN`, whose `_plain` text holds the quote, capped at 400 characters at a space with " …". When no such run is found, the model's quote through `safe_output` is kept instead.
4. None: `verified: false` and no quote.

**Keeping: `accept(db, result_id, chosen, as_kind)`**

1. The result (feature `notes`, live) and its live document, else `NotFound` (404). No items: `Invalid`.
2. For each chosen item: an `index` inside the result (else `Invalid`), a text that is not empty after spacing is made single (else `Invalid`), a verified item (else `Unchecked`). An index chosen twice in one request, or already in `kept`, is skipped. The text is cut at 500 characters and the answer at 800.
3. The kind is `keep_as` or the result's kind. Cards and quiz: every picked item needs an answer (`Invalid`), then `_keep_cards`. Notes: `_keep_notes`.
4. `kept` becomes the union of the old and the new indices, written back into the payload, and the row's `status` is set to `accepted`. Returns what the keeper returned plus `kept`.

`_keep_cards(db, result_id, doc, picked)`: **insert only**. The questions already known are the `pages.key` forms of the fronts of every `ai` card of this document, live or deleted. An item whose question is known, or whose `source_id` (`<result id>:<index>`) has a card, is counted in `skipped`; otherwise `services.upsert_card(db, "ai", source_id, question, "<answer>\n\nFrom the passage: “<quote>”", doc_id)`, which inserts since no card has that `source_id`. So a card the reader deleted is never brought back, and nothing is overwritten. Returns `{cards, skipped}`.

`_keep_notes(db, doc, picked)`:

1. `_same_title`: does another live document have the same title (by `pages.key`)? Then the note's title is "Study notes: <title> (<first 6 characters of the document id>)", else "Study notes: <title>" (the title part cut at 180 characters). `pages.find` or `pages.create`.
2. `LABEL` is added above the batch unless the body still ends with the last batch as written: after the last `LABEL`, every block separated by a blank line matches `OURS`.
3. Per item: the line is `_note_line(text, item)`: the kept text with each `[[link]]` and `#tag` that is also in the model's text made inert by `_inert` (also after the reader edited the line); a link or tag the reader added stays live. The label is added only when at least one new line is written. A line already in the body as `- <line>` is skipped ("Ask again" can draft the same line). Otherwise `- <line>` and `  > <the quote, inert> — <link>` are appended.
4. `_link(db, doc, sentence, shared)`: `[[<title>#s<sentence>|<title>]]` only when the title is plain (no `[`, `]`, `|` or `#`, at most 190 characters, no extra spaces), no other document has the same title, and no note is called that title (a note would win the link). Otherwise "<title, inert>, sentence <n + 1>", which is not a link.
5. A body over `pages.MAX_BODY` is `Invalid` ("That note is full. Start a new one."). Then `tags` from `pages.tags_in` and `pages.relink`, as for any note edit. Returns `{page_id, title, added}`.

`_inert(text)`: `[[` becomes `[` and `]]` becomes `]` until none is left, and `#` becomes the full-width `＃`, so neither `pages.links_in` nor `pages.tags_in` sees a link or a tag.

**Routes** (registered by `notes.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body | Result |
|---|---|---|
| `POST /api/documents/{doc_id}/study-notes` | `WriteIn` | `{result}`: the kept result, or a new one. A plain `def`, so it runs on a worker thread |
| `POST /api/ai/results/{result_id}/accept` | `AcceptIn` | `{page_id, title, added, kept}` (notes) or `{cards, skipped, kept}` (cards) |

| Route | Code | When |
|---|---|---|
| write | 200 | A result, also one with no items |
| write | 404 | An unknown or removed document; a section that is not in it |
| write | 409 | AI off (also when a result is kept), no highlights, a section with no text, `guard.Blocked`, no model, no key, budget, a cancelled call |
| write | 422 | A body that fails `WriteIn` (an unknown source or kind) |
| write | 504, 502 | `status_error`: a timeout; an answer that fails `NotesOut` twice, a provider error |
| accept | 200 | Something kept, or nothing new (all already kept or skipped) |
| accept | 404 | An unknown result or one of another feature; a removed document |
| accept | 409 | No items, an index outside the result, an empty text, a card without an answer, an unchecked item, a full note |
| accept | 422 | A body that fails `AcceptIn` (an index that is not a number) |

**Invariants**

- Only `POST …/study-notes` calls a model, and only after the off check; the page sends it only from **Write** or **Ask again**.
- A quote is checked against `Result.sent`, the text as it went out, then by `verify_citations`; a `yours` source never verifies an item. If what `_highlights` or `_section` sends changes, the check follows by itself, and the key with it.
- Only verified items can be kept; the quote kept is the document's own words when they can be found.
- Model text in a note is inert; only the reader's own typing can make a link or a tag.
- Keeping is once per index, a line is not appended twice, and cards are only inserted, never updated or restored.
- A link by title is made only when the title can reach nothing else.
- `notes.py` calls `guard.ask`, never `port.complete`, and is in `FEATURES` of `tests/test_ai_citations.py`.

**Known limits.** No way to pick which highlights are sent (the first 40 by sentence); no check that every highlight gets an item; the reader's quiz answer is not compared or saved; Review cannot edit a card, so the `ai` label on a card never goes; lines the reader rewrote in the dialog still sit under the AI label; the cache key leaves out the model and the provider, as in the other features; a suffixed note title changes if a same-titled document appears later (the next keep then starts a second note). Checked in the running app with a stand-in model (flashcards: the own-words quote shown, a double press sends once, a card kept earlier is recognised). Nothing was tried against a real model.

Found while these docs were written, and fixed since (each with a test in `tests/test_ai_notes.py`):

- **No bare label line.** `_keep_notes` first builds the new lines (skipping lines already in the note, or twice in one request) and adds `LABEL` only when there is at least one (`test_no_empty_label_when_nothing_new_is_kept`).
- **`_same_title` compares in Python** with `pages.key` over all live documents, so "Über X" and "über x", or "A  B" and "A B", are the same title (`test_same_title_is_seen_beyond_ascii_and_spacing`).
- **The model's markup stays inert after an edit.** `_note_line` makes inert each `[[link]]` and `#tag` of the kept line that is also in the model's text; a link or tag the reader added works as usual (`test_model_markup_stays_inert_after_a_small_edit`).

#### Reading plan (`plan.py`)

Milestone 3.1 ("Reading plan: LLM sizing plus code scheduler"). The non-AI version is the whole plan already (`readhold/readplan.py`, section 2b): the reader picks the documents, their order and a level each, and code spreads what is left over the days. With AI on, and only when the reader presses **Suggest an order with AI**, a model suggests the order and a level (easy, medium, hard) per document, with one reason each. It never schedules and never changes anything: the dialog shows the suggestion, **Use this order** fills in the form (with Undo), and the schedule is made by code as always. Tasks added from it say in their note that a model ordered them.

**Names in `plan.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"plan"`: the task name for the port and the profile (`profiles.json`: the strong model, temperature 0.3, top-p 0.95, 1,000 output tokens), the budget (`guard.BUDGETS["plan"]`, 8,000 characters), the prompt name and `ai_results.feature` |
| `MAX_DOCS` | `readplan.MAX_DOCS` (20) |
| `OPENING` | 420 characters of a document's opening, and of the part where the reader goes on |
| `MAX_TITLES` | 12 section titles per document (each cut at 60 characters), then "and N more" |
| `MIN_QUOTE_WORDS` | 4 |
| `CAPS` | `reason` 240, `quote` 400 characters |
| `Invalid`, `NotFound` | 409 and 404 |
| `Pick`, `PlanOut` | The schema: `order` (at most 60 entries), each `document` (a number, or a text such as "2" or "Document 2"), `difficulty`, `reason`, `quote`; every field takes any value and is checked by hand |
| `SuggestIn` | `{document_ids (2 to 20), goal (up to 200), fresh}` |

**What the model reads** (`_sources(db, k, left, wpm)`, per chosen document with something left, numbered from 1 in the reader's order)

1. One `imported` source at the document's first visible sentence, named after `documents.source` (for the cloud rule): "(Document k: <title>)", "(Left to read: N words, about M minutes at W words a minute; S sections left)" (computed by `readplan`), "(Sections left: …)", "(Opening)" and the first sentences of the first visible section, up to `OPENING` characters (`_opening`).
2. When the reader is past that section, a second `imported` source at the sentence they go on from: "(Document k, where the reader goes on: <section>)" and the opening of that section from there.
3. When the document has a "why", a `yours` source `why:<doc id>`: "(Document k) Why I read it: …" (300 characters at most).

The reader's goal, when written, goes in as the `<question>` (`guard.user_text(goal, "topic")`, 200 characters). Never a whole document, never a section past its opening.

**`suggest(port, db, doc_ids, goal="", fresh=False)`, step by step**

0. The schema `Pick` takes any value in its four fields, so a null or a number where a text belongs drops only that part of the entry, not the whole answer; `_text` keeps strings only (2,000 characters), and `_number` refuses a `bool` (`true` is not document 1).
1. `ai_mode` not `local` or `cloud`: `AIOff` (409). A document twice: `Invalid`. A document that is not there: `NotFound` (404). Fewer than two documents with something left to read: `Invalid` ("one has no order to suggest").
2. The sources (above); the key `results.key(prompt.hash, goal, wpm, every source as anchor and text)`; the target id is the first 32 characters of `results.key(*sorted(doc_ids))`, with `target_type="plan"`.
3. Inside `results.once("plan", key)`: a kept row is returned unless `fresh`.
4. One `guard.ask(port, db, "plan", prompt.text, sources, budget="plan", question=goal or None, schema=PlanOut, prompt_version=…)`.
5. The checks: an entry whose `document` is not a number from 1 to the count (a `bool` is not a number), or names a document already placed, is dropped; a `difficulty` other than the three is not used (`level` `medium`, `level_from_model: false`); the reason goes through `safe_output` and its cap; a reason with a quote goes through `_checked`. Documents the model left out (and those with nothing left) follow in the reader's order with `placed: false`.
6. `_checked(db, quote, sources, sent)`: the quote must be, on whole words and at least 4 words, in an `imported` source of **that** document as it was sent (`Result.sent`), then pass `verify_citations` at that source's anchor; the quote shown is then the document's own words (`notes._own_words`). The header lines are in the sent text but are not sentences of the document, so a quote of a title or of the size line never verifies. A `yours` source never verifies.
7. Status over the placed entries that have a reason: `verified` (all have a ✓), `partly` (some), `unverified` (none, or no reason at all).
8. `results.keep(…, target_type="plan", replaces=<the kept row>)`. Payload: `{order: [{document_id, title, level, level_from_model, reason, placed, verified, quote?, sentence?, nothing_left?}], goal, document_ids, status, links, warning, cut, left_out}`.

**Route** (registered by `plan.register(app, db, port)`, which `ai.api.register` calls)

| Route | Code | When |
|---|---|---|
| `POST /api/reading-plan/suggest` | 200 | `{result}`: the kept suggestion, or a new one. A plain `def`, so it runs on a worker thread |
| | 404 | A document that is not in the library |
| | 409 | AI off, a document twice, fewer than two with something left, `guard.Blocked` (a file of secrets in cloud mode; since 4.4 also every source private: a private document among others is only left out by `guard.pack`, so the model never sees its title), no model, no key, budget, a cancelled call |
| | 422 | A body that fails `SuggestIn` (one document, more than 20, a goal over 200 characters) |
| | 504, 502 | `status_error`: a timeout; an answer that fails `PlanOut` twice, a provider error |

Using the suggestion is the page's job (it fills the form; nothing is sent). Adding a plan made from it goes through `POST /api/reading-plan/apply` with `from_ai: <result id>` (section 2b): the result must exist and the request must still be its order and levels, its status becomes `accepted`, and each task's note says the AI model suggested the order and levels.

**Invariants**

- Only `POST /api/reading-plan/suggest` calls a model, and only after the off check; the page sends it only from **Suggest an order with AI** or **Ask again**.
- The model sees sizes, section titles and openings, never a whole document; sizes and minutes are computed by code.
- The model's answer changes no data. The schedule, and both of its promises, come from `readplan.schedule` whatever the model said.
- Every reason with a ✓ rests on a quote checked against the text sent and the document; the others are labelled "the model's guess"; levels are always labelled as its estimate.
- `plan.py` calls `guard.ask`, never `port.complete`, and is in `FEATURES` of `tests/test_ai_citations.py`.

**Known limits.** The model does not see what the reader already knows, so its levels are rough; the cache key leaves out the model and the provider, as in the other features; nothing checks the order against the documents' own deadlines (a plan has one deadline).

#### Brainstorm (`brainstorm.py`)

Milestone 3.2 ("Brainstorm (diverge then converge)"). The non-AI version is the brainstorm sheet (`think.brainstorm`, section 7.6, and `sheetView` in `web/src/views/think.ts`): six questions the reader answers first, then the notes and highlights near the idea. With AI on, and only when the reader presses **Ideas from the model**, a model writes ideas for a note, an idea or a whole document. Diverge: three samples at a high temperature, each from another angle. Converge: one critic call at temperature 0 groups the ideas that make the same point and ranks the groups; code checks what it says. Every idea must rest on its own quote, checked against the text as sent and the library as it is now; an idea without one is left out. Since 2026-11-26 (the owner's decision) the checked ideas go straight into the reader's brainstorm sheet when the model answers, each as its own section, with Undo; nothing is written without the reader's press of **Ideas from the model**. The page side is `web/src/views/aibrainstorm.ts` (chapter 7, section 7.5, and chapter 5, section 5.6).

Decisions (most from an independent review after building): a group shows only its leading idea's own checked quotes, and when the critic's pick has none a member with checked quotes leads, so a quote never vouches for another idea's text; a quote of the reader's note, idea or note on a highlight is shown in their own words on one line (`_span`, `_note_words`), and an `hlnote:` quote is checked against the highlight's note; any failure of the critic except Stop or AI off falls back to code grouping (`judge` "code"); a field the model left null, wrote with the wrong type or too long drops that part, not the whole answer (`guard.LooseText`, `guard.loose_list`, also used by Organize; 3.1 does the same with `Pick`); the samples' output cap was raised to 1,500 tokens; the document Brainstorm asks for one line of the reader's own first (attempt before reveal), which is neither sent nor saved (the page's job); a keep runs in one transaction and re-reads the kept list (the same was done for `notes.accept`); in cloud mode files of secrets are left out and counted (`left_out`), not fatal; the critic's numbers are taken only as real ints (a boolean is not idea 1); the sheet's autosave waits while a keep runs (the page's job); a document's sheet is "Brainstorm: <title> (document)", with an id suffix when two documents share a title.

**Names in `brainstorm.py`**

| Name | What it is |
|---|---|
| `FEATURE`, `CRITIC` | `"brainstorm"` and `"brainstorm_critic"`: the task names for the port and the profiles (`profiles.json`: both the strong model; `brainstorm` temperature 1.0, top-p 1.0, `min_p` 0.05, 1,500 output tokens; `brainstorm_critic` temperature 0, top-p 1.0, 800 tokens), the prompt names. Both calls use the budget `guard.BUDGETS["brainstorm"]`, 12,000 characters. `ai_results.feature` is `brainstorm` |
| `ANGLES` | `connect` ("links between the sources that the reader may not have made yet"), `question` ("open questions, gaps, and what could prove an idea wrong"), `apply` ("ways to use the ideas, small things to try, and contrasts or counter-cases"): one sample each, in that order |
| `MAX_PER_SAMPLE` | 5 ideas read from one sample |
| `MAX_SHOWN` | 8 ideas shown |
| `MAX_CITES` | 3 quotes kept per idea (6 looked at) |
| `MIN_QUOTE_WORDS` | 4 |
| `SAME_WORDS` | 0.6: code grouping puts an idea in a group when it shares this much of its words (Jaccard over `think.words`) with the group's first idea |
| `CAPS` | `text` 400, `label` 80, `quote` 400, `source` 2,500 (the note or idea itself), `near` 1,200 (a nearby note or idea) characters |
| `SHEET_QUESTIONS` | The six questions of the non-AI sheet, as written in `web/src/views/think.ts` (`test_sheet_questions_match_the_page` checks they match): an idea's heading is never one of them |
| `NO_LABEL` | "Idea": the heading of an idea the critic gave no label |
| `NOTE_ANCHOR`, `HLNOTE_ANCHOR` | `note:<id>` or `idea:<id>`; `hlnote:<doc id>:<sentence>` (the reader's note on a highlight, from `notes._highlights`) |
| `Invalid`, `NotFound`, `Unchecked`, `Changed` | 409, 404, 409 "Only ideas that rest on a checked passage can be kept.", and 409 "The sheet changed since the ideas went in. Delete them in the note by hand." (Undo) |
| `Cite`, `Idea`, `SampleOut` | A sample's schema: `ideas` (at most 12), each `text` and `sources` (at most 6), each `anchor` and `quote` |
| `Group`, `CriticOut` | The critic's schema: `groups` (at most 30), each `label`, `ideas` (at most 40) and `best`. The numbers are kept as the model wrote them (`StrictInt`, `StrictBool`, float, str or null), so lax parsing cannot turn `true` into 1; `_critic_groups` takes real ints only |
| `BrainIn` | `{kind: "page" \| "idea" \| "document", id (up to 40), topic (up to 200), fresh}` |
| `Chosen`, `KeepIn` | `{items: [{index, text}] (at most 16)}` |

**What the model reads: `_target(db, kind, item_id)`**

- An id that is not 32 hex characters: `NotFound`.
- A note or an idea: `think.brainstorm(db, kind, id)` (its `HTTPException` becomes `NotFound`). Sources, all `yours` but the highlights: the item itself as `note:<id>` or `idea:<id>`, "(Your note: <title>)" or "(Your idea: …)" and its text up to 2,500 characters; up to 4 of `near`, each re-read with `think._item`, up to 1,200; each passage of `reading` as `<doc>:<sentence>`, `imported`, "(Highlighted in <title>)" and the highlight's full text, named after `documents.source` (for the cloud rule). The sheet title is the one `think.brainstorm` gives.
- A document: the live document (else `NotFound`); its sources are `notes._highlights` (the first 40 highlights, `imported`, and the reader's note on each as an `hlnote:` source, `yours`); with none, `Invalid` ("There are no highlights in this document yet. Highlight a few passages first: the ideas build on them."). Then up to 3 notes (`kind` `page` of `think.corpus`) nearest to the highlights' text (`think._vector`, `_alike`, at least `think.NEAR_SCORE`), as `note:<id>` sources. The sheet title is `think.SHEET` + the title with spacing made single, cut at 160, + " (document)", or " (document, <first 6 characters of the id>)" when another live document has the same title (`pages.key`), so a document's sheet never shares a note's sheet.
- Never a whole document, never a section past what is listed here.

**`write(port, db, kind, item_id, topic="", fresh=False)`, step by step**

1. `ai_mode` not `local` or `cloud`: `AIOff` (409), before anything else.
2. `_target`. Since 4.4 the target's own sources have `main = True`: for a document, every highlight source; for a note or an idea, its own text. In cloud mode (`guard.leaves`) a source whose `name` is a `guard.sensitive_name` is removed before packing, and `left_out` counts the files left out (a document's sources count once, by document id); when nothing is left, `Invalid` ("Every passage here comes from a file of secrets. …"). `guard.pack` then withholds private sources: a private target (a `main` source) refuses the whole brainstorm with `privacy.refusal` (409), also when notes near it are not private; a private neighbour is only left out and counted in the log's `private_left_out`.
3. The topic, when given, through `guard.user_text(topic, "topic")` (whitespace made single, at most 200 characters).
4. The key: `results.key(prompt.hash, critic.hash, kind, topic, *("<anchor>\n<text>" for each source))`.
5. A `Run` (from `library.py`: a stop event and the `call_id` in flight) is added to `_runs` under `_runs_lock`, and removed in `finally`.
6. Inside `results.once("brainstorm", key)`: the kept row for the target and key is returned unless `fresh`; otherwise `_diverge_converge`.

**`_diverge_converge`**

1. Per angle, `_call`: the stop event is checked, a new `call_id` is set, then `guard.ask(port, db, "brainstorm", prompt + "\n\nAngle: <angle>. <how>", sources, budget="brainstorm", question=topic, schema=SampleOut, prompt_version=…, call_id=…)`, and the stop event is checked again (`Cancelled`). A sample the model could not answer in shape (`CouldNotGenerate`, after the port's one retry) is skipped, and its `log_id` (when there is one) still goes into `log_ids`; `answered` counts the samples that worked, and when it is 0 the last error is raised. Any other error (timeout, Stop, AI off) ends the request.
2. Each sample's first `MAX_PER_SAMPLE` ideas: the text through `safe_output` and its cap (an empty one is dropped), up to 6 quotes through `_cite` against **that sample's** `Result.sent`, then `_merge` (repeats out, at most 3). The candidates keep their angle.
3. With more than one candidate, the critic: one source `ideas:<new id>`, trust `model`, "(The ideas, numbered)" and "0. …", "1. …"; `_call(port, db, run, "brainstorm_critic", critic.text, [src], CriticOut, …, None)`. `_critic_groups(data, n)`: per group, the members that are real ints (`isinstance(i, int)` and not a `bool`), in range, not already in a group and not twice; a group with no member is dropped; `best` is used only when it is a real int and a member, else the first member; the label through `safe_output`, 80 characters. Candidates in no group follow, one group each, in order. `Cancelled` and `AIOff` are raised; any other `AIError` of the critic (no answer, a 5xx, a timeout, an answer that fails `CriticOut` twice) gives `_code_groups` and `judge` "code", and the failed critic's `log_id` goes into `log_ids` too (4.2). With one idea or none there is no critic call and `judge` is "none" (the page then says nothing about ranking).
4. Per group: the leader is `best`, unless it has no checked quote and another member has, then the first such member. The idea shown is the leader's text with **the leader's own quotes only**; `similar` is the number of other members, `angles` those of all members. `verified` is whether the leader has a quote.
5. Checked ideas first (a stable sort, so the critic's order holds within each), at most `MAX_SHOWN`. `variety` (`_variety`): 1 minus the mean word overlap of every pair of shown ideas (1 all different, 0 all the same; `None` for fewer than two). Status `verified` (all shown ideas checked), `partly` (some), `unverified` (none).
6. `results.keep(…, log_ids[-1], replaces=<kept row>, target_type="document" or the kind)`. Payload: `{target: {kind, id, title, sheet_title}, topic, ideas, judge, variety, kept: [], left_out, status, links, warning, log_ids}`. `log_ids` lists every call in order, the samples and the critic, failed ones included; the row's own `log_id` is the last of them.

**Checking: `_cite(db, c, sent)`**

1. The anchors whose text as sent (without its first line in brackets, `_body`) holds the quote (`guard.quote_in`, whole words, at least 4 words), the one the model named first.
2. `note:` or `idea:`: the live note (`pages.body`) or idea (`ideas.text`) must hold the quote **now**; the quote shown is `_note_words(text, quote)`: the shortest run of up to 8 non-empty lines that holds it, joined on one line, cut by `_span` to exactly the words of the quote as the reader wrote them, capped at 400 characters at a space with " …". `{kind, id, title, quote}`.
3. `hlnote:`: the live highlight with a non-empty note, in a live document, must hold the quote in its **note**; the quote is `_note_words(note, quote)`. `{kind: "hlnote", document_id, document_title, sentence, quote}`.
4. A document anchor: `verify_citations`; the quote is `notes._own_words` (the document's own sentences), else the model's quote through `safe_output`. `{kind: "document", document_id, document_title, sentence, quote}`.
5. None of these: no quote.

**Into the sheet: `keep(db, result_id, chosen)`** (since 2026-11-26, on the owner's request, this replaces 3.2's "nothing is kept until you choose": the page calls it as soon as the model answers, with every verified idea not yet kept; there are no tick boxes and no Keep button)

1. The result (feature `brainstorm`, live), else `NotFound`. No items: `Invalid` ("Choose at least one idea to keep."). Each item: an `index` inside the result (else `Invalid`), a text that is not empty once its spacing is made single (else `Invalid`; cut at 600 characters), a verified idea (else `Unchecked`). An index twice in the request, or already in `kept`, is skipped.
2. In `db.transaction()`, `_write_sheet`: `kept` is read again from the row (a keep that finished while this one waited), and the picked ideas already kept are dropped. The sheet is `pages.find(sheet_title)` or `pages.create`. Per idea: one sentence, `_sentence(notes._note_line(text, idea))` (the model's `[[links]]` and `#tags` inert, also after an edit; the reader's own stay live; on one line, with a full stop unless it has its own end mark). A sentence already in the body (or in this batch) is skipped.
3. Each new idea is its own section at the end of the sheet: `## <_heading(label)>`, then the sentence, sections apart by a blank line. `_heading`: the critic's label through `notes._inert`, on one line, cut at 80 and stripped of spaces and `#`; `NO_LABEL` ("Idea") when that leaves nothing; " (idea)" added when it is one of `SHEET_QUESTIONS`, so the non-AI sheet never reads it as the reader's answer. No heading of its own, no label line and no source lines (`HEADING` and `LABEL` were removed; the passages stay in the result's payload).
4. A body over `pages.MAX_BODY` is `Invalid` ("That sheet is full. Start a new note."). Then `tags` and `pages.relink`, as for any note edit; `kept` and status `accepted` in the result. When ideas went in, the payload also keeps `last: {page_id, before, after, ideas}` (the sheet before and after, and the indexes put in) for Undo. Returns `{page_id, title, added, kept}`.

The non-AI sheet reads each idea's section back as one the reader added (`readExtra` in `think.ts` keeps every section that is not one of its six questions), so later typing in the sheet keeps them.

**Undo: `undo(db, result_id, page_id)`** takes the last ideas back out. The result must be live, and in one transaction its payload must have a `last` for that `page_id` (else `NotFound`, 404). The sheet must be live and its body exactly `last.after` (else `Changed`, 409 "The sheet changed since the ideas went in. Delete them in the note by hand."): a later edit of the reader's is never undone. Then the body is `last.before` again (with `tags` and `pages.relink`), `last.ideas` leave `kept`, so they can go in again, and `last` is removed. Returns `{kept}`.

**Stop: `cancel(port)`** sets the stop event of every run in `_runs` and cancels each call in flight (`port.cancel`). It cannot tell one brainstorm from another. `{cancelled: bool}`.

**Routes** (registered by `brainstorm.register(app, db, port)`, which `ai.api.register` calls)

| Route | Body | Result |
|---|---|---|
| `POST /api/brainstorm` | `BrainIn` | `{result}`: the kept ideas, or new ones. A plain `def`, so the four calls run on a worker thread |
| `POST /api/brainstorm/cancel` | – | `{cancelled}` |
| `POST /api/brainstorm/{result_id}/keep` | `KeepIn` | `{page_id, title, added, kept}` |
| `POST /api/brainstorm/{result_id}/undo` | `UndoIn` (`{page_id}`) | `{kept}`; 404 when there is nothing to undo for that sheet, 409 when the sheet changed |

| Route | Code | When |
|---|---|---|
| brainstorm | 404 | An id that is not a live note, idea or document |
| brainstorm | 409 | AI off (also when a result is kept), a document with no highlights, every source a file of secrets in cloud mode, `guard.Blocked`, no model, no key, budget, a call stopped by **Stop** or the off switch |
| brainstorm | 422 | A body that fails `BrainIn` (an unknown kind, a topic over 200 characters) |
| brainstorm | 504, 502 | `status_error`: a timeout; every sample failing its schema twice, a provider error |
| keep | 404 | An unknown result, or one of another feature |
| keep | 409 | No items, an index outside the result, an empty text, an unchecked idea, a full sheet |
| keep | 422 | A body that fails `KeepIn` |

**Invariants**

- Only `POST /api/brainstorm` calls a model, and only after the off check; the page sends it only from **Ideas from the model** or **Ask again**.
- What the model reads comes from `_target`: what the non-AI sheet shows, or a document's highlights and the notes near them; never a whole document.
- The critic's one source is model text with `trust="model"`; what it says is used only through `_critic_groups`, which takes real ints that name candidates.
- An idea shows only its own quotes. A quote is checked against the `Result.sent` of the sample that wrote it, then against the live library or the live note.
- Keeping is once per index, inside a transaction; a line is not appended twice; model markup is inert.
- `brainstorm.py` calls `guard.ask`, never `port.complete`, and is in `FEATURES` of `tests/test_ai_citations.py`.

**Known limits.** Stop cancels every running brainstorm, and closing the dialog does not stop one; there is no trigger from a highlight or a collection, and no section summaries as context; `variety` is stored but not shown; the critic does not see the quotes, so it may rank an idea whose quote failed above one whose quote held (code then moves checked ideas first); the cache key leaves out the model and the provider, as in the other features. Removing a note or an idea takes its brainstorm results out of sight (the note's delete route and the idea's set `ai_results.deleted` for that target). Checked in the running app with a stand-in model; never with a real model.

#### Organize (`organize.py`)

Milestone 3.3 ("Organize library and related documents"). The non-AI version is `readhold/organize.py` (section 7c): the reader's tags, which are also collections, related documents by shared words, and tags suggested by code. With AI on, and only when the reader presses **Suggest tags and related documents**, a model reads a little of one document and suggests tags (the reader's own first, at most two new) and which of the documents code found closest are related. Nothing changes until the reader adds a tag. The page side is `web/src/views/organize.ts` (chapter 5, section 5.6).

Decisions (most from an independent review after building): in cloud mode candidates from files of secrets are not named, and since 4.4 neither are private candidates (`privacy.document_private`), and the list of the reader's tags leaves out the tags of private documents and notes and the word `private` itself (`plain.known_tags(db, keep_here)`, with `keep_here = privacy._keeps_here` under the current `only_tagged`); related numbers are real ints only; `model_tags` and `model_reuse` measure reuse on what the model wrote, while `reuse` is measured on what is shown; highlights from hidden sections are not sent; the known-tags list is cut on whole tags. On the page: an Undo sends `expect` equal to the tags its own change produced, and saves run one after another.

**Names in `organize.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"organize"`: the task (`profiles.json`: the small model, temperature 0.2, top-p 0.9, 600 output tokens), the budget (`guard.BUDGETS["organize"]`, 8,000 characters), the prompt name and `ai_results.feature` |
| `OPENING` | 500 characters of the document's opening, by whole sentences |
| `MAX_HIGHLIGHTS` | 8 |
| `MAX_TAGS`, `MAX_NEW` | 6 tags shown, at most 2 of them new |
| `MAX_CANDIDATES`, `CANDIDATE_SCORE` | 8 candidates, found by `plain.related` with the floor 0.05 (looser than the 0.12 of the plain page: the model chooses among them) |
| `MAX_RELATED` | 5 |
| `MIN_QUOTE_WORDS` | 4 |
| `CAPS` | `reason` 200, `quote` 400, `titles` 1,200 (the section titles), `tags` 1,500 (the tags the reader uses) characters |
| `TagOut`, `RelatedOut`, `OrganizeOut` | The schema: `tags` (at most 20), each `tag` and `quote`; `related` (at most 20), each `document` (any value: code takes real ints only) and `reason` |
| `SuggestIn` | `{fresh}` |

**What the model reads: `_sources(db, doc, cloud)`**

1. The opening: the live sentences of live, visible sections in order (at most 200 looked at) until `OPENING` characters, with at least one sentence; one `imported` source per section it reaches, anchored at its first sentence (so a quote is checked against its own section), named after `documents.source`. The first source starts with "(Document: <title>. Sections: <the visible section titles, up to 1,200 characters>)". A document with no such sentence gets that header alone.
2. Up to `MAX_HIGHLIGHTS` live highlights whose sentence is in a visible section, each "(Highlighted)" and its text, `imported`.
3. One `yours` source `tags:<doc id>`: "(The tags you already use)" and the 80 most used, joined with commas and cut on whole tags within 1,500 characters (or "none yet"), then "(Already on this document)" and its tags (or "none").
4. Candidates: `plain.related(db, doc_id, n=16, floor=0.05)`; in cloud mode those whose file is a `sensitive_name` are dropped before they are named; the first 8, as one `imported` source `docs:<doc id>`: "(Other documents in your library, numbered)" and "1. <title>", … Only titles, never their text.

**`suggest(port, db, doc_id, fresh=False)`, step by step**

1. A missing document: 404. `ai_mode` not `local` or `cloud`: `AIOff` (409).
2. The sources (above), built with `cloud = guard.leaves(port)`. The key: `results.key(prompt.hash, every source as anchor and text)`. In cloud mode `guard.pack` refuses the document itself when it is a file of secrets (`Blocked`, 409), and since 4.4 when it is private: every source is about it (its sentences, `tags:<id>`, `docs:<id>`), so all are withheld and the call is refused with `privacy.refusal`.
3. Inside `results.once("organize", key)`: a kept row is returned unless `fresh`.
4. One `guard.ask(port, db, "organize", prompt.text, sources, budget="organize", schema=OrganizeOut, prompt_version=…)`.
5. Tags: each through `plain.clean_tag` (a failure counts in `dropped`); each valid one goes into `raw` once (what the model wrote); one already on the document or seen before is skipped; `existing` is whether the reader uses it already (`known_tags`); `_quote` checks its quote. Then the reader's own tags first, then the new ones; new ones past `MAX_NEW`, and anything past `MAX_TAGS`, are dropped and counted.
6. `_quote(db, doc_id, quote, sent)`: only a source of **this** document (a `DOC_ANCHOR` with its id) whose text as sent holds the quote (whole words, at least 4 words), then `verify_citations`; the quote shown is `notes._own_words`, else the model's through `safe_output`. A quote of the header line or of a candidate title never verifies.
7. Related: each `document` that is a real int (not a `bool`, not `1.0`, not `"1"`) from 1 to the number of candidates, not used before, at most 5; `{id, title, shared}` from the candidate and the reason through `safe_output`, 200 characters.
8. `reuse`: the share of shown tags that are the reader's own (`None` with none shown). `model_tags`: the valid tags the model wrote (before code's filters); `model_reuse`: the share of those the reader already uses (the plan's measure for this milestone). Status `verified` (every shown tag has a quote), `partly`, `unverified`.
9. `results.keep(…, replaces=<kept row>)`. Payload: `{document_id, tags, related, dropped, reuse, model_tags, model_reuse, status, links, warning}`.

**Route** (registered by `organize.register(app, db, port)`, which `ai.api.register` calls)

| Route | Code | When |
|---|---|---|
| `POST /api/documents/{doc_id}/organize/suggest` | 200 | `{result}`: the kept suggestion, or a new one. A plain `def`, so it runs on a worker thread |
| | 404 | A document that is not there (also with AI off) |
| | 409 | AI off, `guard.Blocked` (the document is a file of secrets in cloud mode), no model, no key, budget, a cancelled call |
| | 422 | A body that fails `SuggestIn` |
| | 504, 502 | `status_error`: a timeout; an answer that fails `OrganizeOut` twice, a provider error |

Adding a suggested tag is the page's job: `PUT /api/documents/{doc_id}/tags` with `expect` (section 7c). Nothing in this module writes a tag.

**Invariants**

- Only `POST …/organize/suggest` calls a model, and only after the off check; the page sends it only from its button or **Ask again**.
- The model reads the title, visible section titles, the opening, up to 8 visible highlights, the reader's tags and the candidates' titles; never a whole document, never another document's text.
- A tag is kept only as `clean_tag` writes it; a related document only as a number of the list code made.
- The answer changes no data. Tags are added only by the reader.
- `organize.py` calls `guard.ask`, never `port.complete`, and is in `FEATURES` of `tests/test_ai_citations.py`.

**Known limits.** No trigger on import; reuse is not added up across calls (milestone 4.1 will); `_profiles` (used for the candidates) is not cached, about 0.3 s at 400 documents; tags with combining marks (Devanagari, for example) are refused, as note tags are; the check-then-update of `set_tags` is not atomic; the cache key leaves out the model and the provider. Checked in the running app with a stand-in model; never with a real model.

#### Tidy (`tidy.py`)

Milestone 5.2 ("Tidy: messy notes, tasks and routines made clear"). The non-AI version is `readhold/tidy.py` (section 7d): hints for what a task lacks and the fixes code is sure of. With AI on, and only when the reader presses the model's button in one of the three Tidy boxes, a model reads the reader's own text and proposes a rewrite. It may reword, reorder, shorten and split, never add facts. Code checks what comes back; nothing is applied here. The page side is `web/src/views/tidy.ts` (chapter 6).

**Names in `tidy.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"tidy"`: the task (`profiles.json`: the strong model, temperature 0.2, top-p 0.9, 6,000 output tokens), the budget (`guard.BUDGETS["tidy"]`, 12,000 characters), the prompt name and `ai_results.feature` |
| `MAX_TASKS`, `MAX_SPLIT`, `MAX_NOTE`, `MAX_STEPS`, `DAYS_AHEAD`, `CAP` | 30 tasks sent, 4 parts in a split, 10,000 characters of note, 30 steps, 60 days ahead, 200 characters of text |
| `KINDS` | The instruction added after the prompt, per kind: `tasks` (answer `{"tasks": [...]}` with `task`, `text`, `minutes`, `day`, `split`), `note` (`{"body"}`, the same content, keep its `[[links]]`), `routine` (`{"steps"}`) |
| `Part`, `TaskOut`, `TidyOut` | The schema, loose on purpose (`guard.LooseText`, `guard.loose_list`): numbers and days are `Any` and checked by code. `TidyOut.body` is `LongText` |
| `LongText` | A string cut at `pages.MAX_BODY` (200,000) instead of `LooseText`'s 2,000, so a note's rewrite is never cut short |
| `FILLER`, `SHORTER` | The few filler words `_tokens` drops (`the`, `a`, `of`, `to`, …); 0.6: a rewrite under 60% of the note's length is marked `shorter` |
| `Invalid`, `NotFound`, `SuggestIn` | 409, 404; `{kind: tasks \| note \| routine, id (40 characters at most), fresh}` |

**What the model reads: `_target(db, kind, item_id)`**

- `tasks`: the open tasks by `ord`, at most 30, one `yours` source each, `task:<id>`, "(Task N) <text> \| <minutes> min \| day: <due or none>". None open: `Invalid` "There is no open task to tidy." Target `plan` / `tasks`.
- `note`: one `yours` source `note:<id>`, "(Your note: <title, 200 characters>)" and the body, with `main = True` (a private note refuses a call that leaves this computer). A body over `MAX_NOTE` is `Invalid` (refused, not cut: the rewrite would lose its end). Target `page` / its id.
- `routine`: one `yours` source `routine:<id>`, "(Routine: <title>)" and its numbered steps with their minutes. Target `routine` / its id.

A bad id is `NotFound` before any lookup.

**`suggest(port, db, kind, item_id="", fresh=False)`, step by step**

1. `ai_mode` not `local` or `cloud`: `AIOff` (409).
2. `_target` (404 or 409 as above).
3. The key: `results.key(prompt.hash, kind, today's date, every source as anchor and text)`. The date is in it because a day the model names ("tomorrow", "friday") is worked out from today.
4. Inside `results.once("tidy", key)`: a kept row is returned unless `fresh`.
5. One `guard.ask(port, db, "tidy", prompt.text + "\n\n" + KINDS[kind], sources, budget="tidy", schema=TidyOut, prompt_version=…)`. The prompt in use is `tidy_v2` (since 2026-11-26): write in the same language and never translate, not even a word (the owner saw a note come back translated); really tidy (spelling, grammar, structure, every point kept); never add facts.
6. The check, by kind (below), then `links` and `warning`, then `results.keep(…, replaces=<kept row>, target_type=…)`.

**Checking tasks: `_tasks(data, rows, today, sent)`.** `task` must be a real int (not a `bool`) from 1 to the number of rows, not seen before, and its `task:<id>` must be in `r.sent` (a task the guard left out, a private one in cloud mode for example, gets no answer). `text` and each split part through `_text` (`safe_output`, spaces joined, at most `CAP` with room for the "…"). Minutes through `_whole` (an int, not a `bool`, 1 to 600, else `None`). `day` through `_day` (today, tomorrow, a weekday through `plain._day`, or an ISO date from today to 60 days ahead, else `None`). A split keeps at most 4 parts with text, and only when there are at least two. An entry with neither text nor split is dropped. Each item: `{id, number, original: {text, minutes, due}, text (or the old text), minutes, due, split, new_words}`, `new_words` over the text and every part against the task's own text.

**Checking a note: `_note(data, original)`.** It works on the uncleaned answer, `r.raw` (new in `guard.Result`), because `guard._clean_data` would already have turned every link into words, the reader's own too. The body goes through `guard.sanitize` and is stripped. Then:

1. The reader's own marks, read outside code blocks (`pages.FENCE`): links by `pages.key` of their target (`_link_key`), tags in lower case, properties by key (`pages.PROP`).
2. In the rewrite, a `[[link]]` or `#tag` the reader did not have goes through `notes._inert` (plain characters); a picture (`guard._IMAGE`) or a web link (`guard._LINK`) that is not, as written, in the reader's note becomes words ("… (image not loaded: <address>)", "words (address)"); a reference-style link line (`guard._REF`) that is not in the note is dropped.
3. Own properties, links and tags missing from the rewrite are put back at the end (properties one per line, then the marks on one line) and listed in `restored`, so `#private`, `#cloud`, a link or a property is never lost.
4. `shorter` when the body is under `SHORTER` of the old one; then `missing_words` are up to 40 of the reader's words that are gone (words with digits last).
5. The body is cut at `pages.MAX_BODY`; no label line goes on top (it did until 2026-11-26, when the owner asked for none). `new_words` against the title and the old body.

Payload: `{kind, page_id, original, body, new_words, restored, shorter, missing_words, links, warning}`. An empty body gives empty lists and no `Use`.

**Checking a routine: `_steps(data, original)`.** At most 30 steps with text (`_text`), minutes 0 to 240 (`_whole`, else 0); `new_words` against the title and the old steps. Payload: `{kind, routine_id, steps, new_words, links, warning}`.

**`_tokens` and `_new_words`.** Every run of letters, digits, `'` and `’` in `casefold()`, apostrophes dropped ("don't" is `dont`), minus `FILLER`. So numbers, short words and negations count: "1200", "al", "3", "not" are listed when the reader did not write them. `new_words` is the sorted difference.

**Route** (registered by `tidy.register(app, db, port)`, which `ai.api.register` calls)

| Route | Code | When |
|---|---|---|
| `POST /api/tidy/suggest` | 200 | `{result}`: the kept proposal, or a new one. A plain `def`, so it runs on a worker thread. Nothing changes |
| | 404 | A note or routine that is not there, or a bad id |
| | 409 | AI off, `Invalid` (no open task, a note too long), `guard.Blocked` (a private note in cloud mode, a file of secrets), no model, no key, budget, a cancelled call |
| | 422 | A body that fails `SuggestIn` (an unknown kind) |
| | 504, 502 | `status_error`: a timeout; an answer that fails `TidyOut` twice, a provider error |

Applying is the page's job (section 7d and chapter 6): a task through `PATCH /api/todos/{id}` (and `POST /api/todos` for split parts), a note through `PATCH /api/pages/{id}`, a routine through `POST /api/tidy/routine/{id}/apply`.

**Invariants**

- Only `POST /api/tidy/suggest` calls a model, and only after the off check; the page sends it only from the model's button or **Ask again**.
- The model reads only the reader's own text (tasks, one note, one routine), as `yours`; a note is `main`.
- A number, a day or a length from the model is used only after code checked it; a task number only for a task that was sent.
- Every word the reader did not write is in `new_words`. In a note the model's links, tags, pictures and web links never become live; the reader's own links, tags and properties are never lost.
- The answer changes no data. `tidy.py` calls `guard.ask`, never `port.complete`, and is in `NO_QUOTES` of `tests/test_ai_citations.py`: it shows no quote, and the test checks it shows none even when the model writes one.

**Known limits.** A rewrite carries no mark that a model wrote it, a task's or a note's (decided; the note's label line was removed on 2026-11-26, on the owner's request); `new_words` is a word list, so a changed meaning with the same words ("not" moved) is not caught; the cache key leaves out the model and the provider; "Why did it say this?" names the `task:` and `routine:` sources by the bare word. Checked in the running app with a stand-in model; never with a real model.

#### Plan chat (`chat.py`)

Milestone 5.3 ("Plan chat: tasks drafted from what you type"), the plan's first free-text feature (design note in section 10 of `docs/ai/PLAN.md`). The reader writes ("plan my week around the exam on Friday"); the model answers with a short reply and at most 12 draft tasks. Code gives it what it needs, checks every draft, and adds nothing until the reader clicks. The page side is `web/src/views/planchat.ts` (chapter 6).

**Names in `chat.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"chat"`: the task (`profiles.json`: the strong model, temperature 0.3, top-p 0.95, 1,500 output tokens), the budget (12,000 characters), the prompt name and `ai_results.feature` (target `plan` / `chat`) |
| `MAX_DRAFTS`, `MAX_TURNS`, `MAX_TASKS`, `DAYS`, `DAYS_AHEAD`, `DEFAULT_MINUTES` | 12 drafts, 12 messages, 40 open tasks sent, 14 days shown, 60 days ahead, 25 minutes |
| `NOTE` | "Drafted by the AI model from your Plan chat on {day}; check that it suits you.": every added task's note |
| `_anchor(kind, name)` | `<kind>:<md5 of name>`: a well-formed anchor for a source that is no row (`days:…`, `turn:…`) |
| `Draft`, `ChatOut` | The schema: `reply` and `tasks` (at most 60 read), each `text`, `day`, `minutes` (any value) |
| `Turn`, `ChatIn` | `{who: you \| model, text (4,000 characters at most)}`; `{messages (1 to 12), minutes_a_day (15 to 720, default 120)}` |
| `Chosen`, `AddIn`, `UndoIn` | `{index, text (2,000), due (10 characters or null), minutes (default 25)}`; `{items (at most 12)}`; `{batch (60 characters)}` |

**What the model reads: `_sources(db, turns, per_day, today, away)`**

1. One `yours` source `days:…`: "(Your next days, worked out by the app)" and, for each of the next 14 days, "<date> <weekday>: N free of M minutes", where N is `per_day` minus the minutes of the open tasks with that day (`_planned`, never below 0).
2. Each open task, ordered by day (none last) and `ord`, at most 40: `task:<id>`, `yours`, "(Open task) <text> \| day: <due or any> \| <minutes> min".
3. Each unfinished document with a deadline from today, at most 20: `docs:<id>`, `imported`, "(Deadline) Read “<title>” by <day>", with "; why: …" when there is one.
4. The conversation before the last message: `turn:…`, "(You said)" as `yours` or "(The model said)" as `model`. When the text leaves this computer (`guard.leaves`), a model turn that `privacy.copies_private` is skipped: an earlier reply from a model on this computer may have named private text.

The last message is the question, through `guard.user_text(…, "ask")` (1,000 characters; longer is `Blocked`, 409). In cloud mode `guard.pack` withholds the rest by the usual rule: a private document's deadline (`docs:` is `ABOUT_DOCUMENT`), a task that opens a private document (`privacy.owner` maps a `task:<id>` with `link_type` `document` to that document, new in 5.3), and a `yours` turn or task whose text copies private text.

**`draft(port, db, turns, per_day)`.** `AIOff` first; the sources; the key over the prompt, `per_day`, today, the question and every source; inside `results.once("chat", key)` a kept row is returned (there is no `fresh`); one `guard.ask(port, db, "chat", prompt.text, sources, budget="chat", question=question, schema=ChatOut, prompt_version=…)`. Payload: `{question, minutes_a_day, reply (safe_output, 800), drafts, already, dropped, kept: [], batch: "", links, warning}`.

**Checking: `_check(data, tasks, planned, per_day, today)`.** For each draft: the text through `safe_output` (200) with its spaces joined, empty ones skipped; the same words as an open task (spaces and case ignored) counts in `already`; a repeat in the answer is skipped; past 12 counts in `dropped`. Then `_day` (empty is no day; today, tomorrow and weekdays through `plain._day`; an ISO date from today to 60 days ahead; anything else is no day, with a flag that says why), minutes (a real int 5 to 240, else 25 with a flag), and the day's load: `planned` plus the drafts already placed on that day; over `per_day`, `fits` is false and a flag says "Over your free time that day: N of M minutes planned." Each draft: `{text, due, minutes, fits, flags}`.

**`add(db, result_id, chosen)`: the one click.** 404 for a bad id or a result that is not a live `chat` one. In one transaction, with the payload read again: each chosen `index` must be a real int in range (else `Invalid` 409 "That draft is not in this answer."); an index already in `kept` is skipped; the text (spaces joined, 500 characters) must not be empty; `due` must be an ISO date that exists, from today to 365 days ahead, or null; minutes 1 to 600. Each becomes a task at the end of the open list (`ord`), with `NOTE` and `plan_batch` `chat:<new id>`, one batch per click. The payload gets the new `kept` and `batches[batch] = [[task id, index], …]`; the result's status becomes `accepted`. Returns `{batch, added, kept}`.

**`undo(db, result_id, batch)`.** 404 for an unknown result, or a batch that is not in its `batches` (or is empty). In one transaction: the batch's live tasks that are still `readplan._UNTOUCHED` (not done, not timed, not edited since it was added, no small steps) are soft-deleted; their indices leave `kept`, so the drafts can be added again; the batch keeps the tasks that stayed. Returns `{removed, stayed, kept}`.

**Routes** (registered by `chat.register(app, db, port)`)

| Route | Code | When |
|---|---|---|
| `POST /api/plan/chat` | 200 | `{result}`: the kept answer or a new one. Nothing is added. A plain `def` |
| | 409 | AI off, `guard.Blocked` (a message over 1,000 characters, a refused file), no model, no key, budget, a cancelled call |
| | 422 | The last message is not yours, or a body that fails `ChatIn` |
| | 504, 502 | `status_error` |
| `POST /api/plan/chat/{result_id}/add` | 200, 404, 409, 422 | `{batch, added, kept}`; 409 for `Invalid` |
| `POST /api/plan/chat/{result_id}/undo` | 200, 404, 422 | `{removed, stayed, kept}` |

`readplan` ignores `chat:` batches: `busy_minutes` does not count them as reading time and `last_batch` never offers one; `readplan.undo` takes only a 32-hex batch id, so it cannot take a chat batch back either.

**Invariants**

- Only `POST /api/plan/chat` calls a model, and nothing it returns is added. A task is added only by `add`, which the page sends only from **Add the ticked tasks to Plan**.
- Every draft is checked by code before it is shown, and every added task by code again (the reader may have edited it).
- Each click is its own batch, and Undo takes back only that batch's untouched tasks.
- Every added task's note says a model drafted it.
- The model gets no tools and cannot add, move or delete anything; what the reader typed reaches it only inside the `<question>` fence or as a fenced `yours` turn.
- `chat.py` calls `guard.ask`, never `port.complete`, and is in `NO_QUOTES` of `tests/test_ai_citations.py`.

**Decisions.** "Only #cloud" (`ai_cloud_only_tagged`) governs documents, notes and ideas (the library), not plan items or what the reader types: a task has no tags; a task that opens a document follows that document; a turn or task that copies a document that stays here stays here too. Nothing is added without the click (the owner's decision of 2026-11-26).

**Known limits.** The free minutes count every open task with a day, a reading-plan task included, but not time already spent; there is no **Ask again**: the same message in the same state on the same day gives the kept answer. Fixed after the Phase 5 docs (2026-11-26, with tests): the newest message, sent as the question, is checked for copies of private text too, and refused off this computer (`Blocked`, 409); a draft that repeats any open task is caught, not only one of the 40 shown (`_check` reads every open task); **Export AI data** listed the tasks it added ("drafted by the AI model"; that export was removed later the same day); "Why did it say this?" names `days:`, `task:` and `turn:` in words and the `docs:` deadlines as "document titles (and deadlines)"; the evaluation harness runs it. Checked in the running app with a stand-in model (drafts, flags, Add, Undo, adding again); never with a real model.

#### Note chat (`notechat.py`, milestone 5.4)

Milestone 5.4 ("Note chat"), added on request on 2026-11-26 (design note in section 10 of `docs/ai/PLAN.md`). In a note, the reader tells a model what to do with it ("make this note more formatted", "enhance it", "write an idea for a story"). The model answers with a short reply and one proposal: the whole note rewritten, new text for the end of the note, or nothing. The same rules as Plan chat: code checks the proposal, and nothing changes until the reader presses a button on the page, with Undo. The page side is `web/src/views/notechat.ts` (chapter 7).

**Names in `notechat.py`**

| Name | What it is |
|---|---|
| `FEATURE` | `"notechat"`: the task (`profiles.json`: the strong model, temperature 0.6, top-p 0.95, 6,000 output tokens), the budget (`guard.BUDGETS["notechat"]`, 12,000 characters), the prompt name (`notechat_v1`) and `ai_results.feature` (target `page` / the note's id). "Why did it say this?" names it "Note chat" |
| `MAX_TURNS`, `ACTIONS` | 12 messages; `replace`, `add`, `none` |
| `NoteChatOut` | The schema: `reply` and `action` (`guard.LooseText`), `text` (`tidy.LongText`, so a rewrite of a long note is not cut) |
| `_anchor(i)` | `turn:<md5 of i>`: a well-formed anchor for an earlier turn |
| `Turn`, `NoteChatIn` | `{who: you \| model, text (4,000 characters at most)}`; `{messages (1 to 12)}` |
| `Invalid`, `NotFound` | 409, 404 |

**What the model reads: `_sources(db, row, turns, away)`**

1. The note: `note:<id>`, `yours`, "(The note you are in: <title, 200 characters>)" and the body, or "(empty so far)". It is `main`, so a #private note refuses a call that leaves this computer.
2. The conversation before the last message: `turn:…`, "(You said)" as `yours` or "(The model said)" as `model`. When the call leaves this computer (`guard.leaves`), a model turn that `privacy.copies_private` is skipped.

The last message is the question, through `guard.user_text(…, "ask")` (1,000 characters; longer is `Blocked`, 409). When the call leaves this computer and the message copies private text (`privacy.copies_private`), it is `Blocked` too: "Say it in your own words, or use a model on this computer."

**`answer(port, db, page_id, turns)`.** `AIOff` first; a bad or unknown id is `NotFound`; a body over `tidy.MAX_NOTE` (10,000 characters) is `Invalid` ("Split it into two notes."). Then the question, the private check and the sources; the key over the prompt, today, the question and every source; inside `results.once("notechat", key)` a kept row is returned (there is no `fresh`); one `guard.ask(port, db, "notechat", prompt.text, sources, budget="notechat", question=question, schema=NoteChatOut, prompt_version=…)`. Payload: `{page_id, question, original (the note as sent), reply (safe_output, 800), action, text, new_words, restored, missing_words, shorter, links, warning}`.

**Checking: `_proposal(raw, data, row)`.** It reads the `text` from the uncleaned answer (`r.raw`), as Tidy does, so the reader's own links can be told from the model's.

- `action` (lower case) not `replace` or `add`, or an empty text: `none`, with an empty text and empty lists. An empty rewrite would wipe the note, so it is no proposal.
- `replace`: the text goes through `tidy._note` against the note (section *Tidy*, "Checking a note"): the reader's links, tags and properties kept or put back (`restored`); the model's links, tags, pictures and web links plain; `new_words`; `shorter` and `missing_words`. No label line. A body that comes back empty is `none`.
- `add`: the text goes through `tidy._note` against an empty note, so all its markup is plain. `new_words` stays empty: new writing is expected to have new words.

**Route** (registered by `notechat.register(app, db, port)`)

| Route | Code | When |
|---|---|---|
| `POST /api/notes/{page_id}/chat` | 200 | `{result}`: the kept answer or a new one. Nothing is changed. A plain `def` |
| | 404 | A note that is not there, or a bad id |
| | 409 | AI off, `Invalid` (a note too long), `guard.Blocked` (a private note, or a message that copies private text, off this computer; a message over 1,000 characters), no model, no key, budget, a cancelled call |
| | 422 | The last message is not yours, or a body that fails `NoteChatIn` |
| | 504, 502 | `status_error` |

Applying is the page's job: `notechat.ts` re-reads the note and writes it through `PATCH /api/pages/{id}` only on **Use this** (the rewrite) or **Add to the note** (your text, a blank line, the new text), and only while the body is still `original`. Its Undo toast puts `original` back only while the body is still what was written.

**Invariants**

- Only `POST /api/notes/{page_id}/chat` calls a model, and the server applies nothing it returns.
- The model reads only the note and the conversation; the note is `yours` and `main`, the model's own turns are `model`.
- A rewrite never loses the reader's links, tags or properties, and the model's markup never becomes live, in a rewrite or in added text. Every word of a rewrite the reader did not write is in `new_words`.
- No label line goes into the note (the owner's decision of 2026-11-26).
- `notechat.py` calls `guard.ask`, never `port.complete`, and is in `NO_QUOTES` of `tests/test_ai_citations.py` and of `eval/score.py`: it shows no quote.

**Known limits.** There is no **Ask again**: the same message on the same note on the same day gives the kept answer. The conversation is kept in memory per note (`memo` in `notechat.ts`) while the app is open, never saved. The dialog closes after Use or Add, because the note page is drawn again; 💬 opens it again with the conversation. Checked in the running app with a stand-in model (a rewrite used, a story idea added, Undo restored the note exactly); never with a real model.

### The evaluation harness (`readhold/eval/`, milestone 4.1)

**4.1 Evaluation harness per feature** ("One command prints scores for every feature"). It is a package beside `ai/`, not inside it, and it calls no model itself: it drives the app.

```bash
uv run python -m readhold.eval                 # the model in your Settings (local; cloud needs --yes)
uv run python -m readhold.eval --stand-in      # a fake model in-process: checks the harness (CI)
uv run python -m readhold.eval --model qwen2.5:14b --only ask,library --json scores.json --keep
```

| File | Job |
|---|---|
| `harness.py` | The command (`main`) and `run(stand_in, model, allow_cloud, only, keep, progress) -> report`. `read_settings(home)` and `read_profiles(home)`: the `ai_…` settings and `wpm` (`COPIED`), each through `settings.check`, and your profile changes through `profiles.check`, read from your folder; `tokens_today(home, provider)`: what the app used today. `_query` reads your database read-only: `immutable=1` when there is no `-wal` file (nothing is created beside it), plain `mode=ro` when there is one (the app is open; the newest values may be only in the WAL, and SQLite may touch its own `-shm` index file, which holds no data). `_open_app` opens a new database in a `tempfile.mkdtemp` folder (`READHOLD_HOME` is set to it and put back afterwards), `create_app`, and FastAPI's `TestClient` (`raise_server_exceptions=False`; in-process ASGI, no socket, no port), applies the settings with `PUT /api/settings`, and with `--stand-in` calls `Port.use_stand_in(standin.answer)`. Then `POST /api/ai/test`; `_setup` imports the sample texts and puts their tags and highlights on; each case runs through `RUNNERS` (one function per feature, the routes of `tests/test_ai_citations.py`, always `fresh: true`), and `Ctx.stored` reads the result back from `ai_results` by its id: the score is of what was stored. `_run_case` takes the `ai_log` rows after the case's `MAX(rowid)` mark: the calls of that case only (cases run one after another; `_settle` waits for a digest that was cancelled, so its last row is not counted to the next case). At the end: `digest.stop()`, `_settle`, the database closed, the folder removed (`--keep` leaves it). `_yours` makes the sample tasks, note and routine through the app's routes the first time a Tidy or Plan chat case needs them; those cases run last, so Ask my library never sees the note. `_tidy` asks `POST /api/tidy/suggest`, `_chat` `POST /api/plan/chat` and `_notechat` `POST /api/notes/{id}/chat` on the sample note: nothing is applied or added |
| `samples.py` | `VERSION`, `DOCS` (four short texts written for the harness: block routing, rain in hill soil, sourdough, rye), `TAGS`, `HIGHLIGHTS`, `CASES` (26: resume 2, explain 2, digest 2, ask 4, library 3, notes 2, plan 2, brainstorm 1, organize 1, tidy 3, chat 2, notechat 2). Since `VERSION` 2, `TASKS`, `NOTE` and `ROUTINE` stand for your own writing, for Tidy and Plan chat: four open tasks (one to split, one whose day is only in its text, one with no verb, one already clear), a loose note with a link and a tag, and a three-step routine. A Tidy case names a `kind`; a chat case its `messages` and `minutes` a day. Since `VERSION` 3, two note chat cases ask about the sample note: "format the note" and "a story idea from it", each with its `messages`. `expect` is `found` or `not_found` (ask, library); a not-found question shares words with the texts, so the model is asked and has to say so. `min_docs` (library): the answer must cite at least that many documents |
| `score.py` | Pure functions. `quotes(feature, payload) -> (verified, shown)` (resume `recap`, explain its one quote, digest `key_ideas`, ask and library `citations` of a found answer, notes `items`, plan the placed orders with a reason, brainstorm `ideas`, organize `tags`); `right(payload, expect)` (an unverified answer is still an answer; Ask my library's "not found" counts only when its last step was an answer: a loop that ran out of steps is stored as not found, but the model never said so); `bare` (a found answer that is not `verified`); `documents_cited`; `steps`; `plan_check(preview) -> {within, over_days, late_days, lost_minutes, fits}` on the day-by-day plan `readplan.build` made from the model's order and levels (`POST /api/reading-plan/preview`); `calls(rows)` (calls, `schema_failures`, retries = attempts − 1, failed = outcome not `ok`, median and largest latency, tokens); since Phase 5 `tidy_check(payload)` (`proposals`: every task a rewrite proposes, the note, the routine; `clean`: those that add no word you did not write, from `new_words`; the note's new words and `restored`) and `chat_check(payload)` (`drafts`; `fit`: those that fit their day's free time, or are for any day, with nothing flagged; `dropped`, `already`); since 5.4 `notechat_check(payload)` (`proposal`: a rewrite or text to add, not only a reply; `rewrite`; for a rewrite its `new_words` and `restored`; added text is expected to have new words, so they are not counted); `feature_row`; `render` (ASCII only, fixed widths); `LEGEND` |
| `standin.py` | The stand-in model. `feature_of(system, user)` knows a feature by words of its prompt (`KNOWN`); `answer(body)` takes an Ollama `/api/chat` body and returns the reply: it quotes only sentences it was sent, says not found when a question's words (stems of 4+ letters, acronyms) are not all in the sources, searches once in the library loop and answers in step 2, quotes both documents when it can, reuses fitting tags and adds one new one. In Tidy it rewords with your own words but puts a verb before a task that has none (a word you did not write, which the score counts); in Plan chat it drafts each thing the message lists on the first day with room, even one you already have (code leaves it out: `already`); in the note chat it gives text to add (a story idea) when the message says write, idea or story, and otherwise the note rewritten as a heading and a list that keeps every line, so your links and tags stay. Its token counts are characters / 4 |

**Goals** (`feature_row`, from the plan's "done when"): ask, *every not-found right, every answer found, every answer verified*; library, the same, plus *at most 3 steps* (code caps the loop at 3, so this cannot fail today) and *a two-text question cites both*; plan, *every plan within the minutes a day and the deadline, nothing lost*; brainstorm, *variety ≥ `VARIETY_GOAL` (0.5) and every idea verified*; organize, *mean `model_reuse` > `REUSE_GOAL` (0.5)*; tidy, *more than half the proposals add no word you did not write* (`NEW_WORDS_GOAL` 0.5; nothing proposed fails); chat, *every draft fits* (no draft at all fails); notechat, *every request gets a usable proposal (a rewrite or text to add)*. Tidy, chat and notechat show no quotes: `-`. Resume, explain, digest and notes show `-`: their checks ("recaps match what was read", "judged clear", "an accurate outline", "no invented facts") need a person; the table gives their verified-quote rate. A case that failed fails its feature's goal. Plan's goal mostly tests the scheduler with the model's levels (the order and levels cannot make code break its promises), so read it as "the hybrid holds", not as a judgement of the model.

**What is never touched.** Your database is only read (`_query`), `data/ai_profiles.json` only read, the key only read from the credential store, by the port, as in the app. Everything written (database, backups, `device.json`, the kept results and the AI log of the run) is in the throwaway folder. The budget: the run starts from today's tokens in your AI log, so it spends only what is left of the day's budget (`status: "budget"` when nothing is left). Nothing to score: AI off (`status: "off"`), a cloud model without `--yes` (`"cloud"`: it says how many calls, at most), Test connection failing (`"no_model"`, with its message), and anything that goes wrong while starting or setting up (`"error"`) each print one sentence and exit 0; a case that fails is listed under *Problems* and the others still run. Output: the table on stdout, one progress line per case on stderr, every case and stored result with `--json FILE`.

**Changes in the AI package for it.** `adapters.stand_in(answer)` (an `httpx.MockTransport` that hands each request body to `answer`, never a connection; it lives in `adapters.py` because that file alone may import `httpx`), `Port.use_stand_in(answer)` (sets the port's transport to it and `retry_wait` to 0; every guard still runs), and `checks["schema_failures"]` in `Port._call`: each answer that did not fit the schema adds one, and the count stays when the retry worked (`checks["schema"]` then says `true`).

### "Why did it say this?" (`why.py`, milestone 4.2)

**4.2 "'Why did it say this?' panel from ai_log"** ("Any answer can be traced to its prompt and sources"; plan sections 6.4 and 6.8). One route, `GET /api/ai/why/{result_id}`, registered by `api.py` with `why.register(app, db)`. It reads `ai_results`, `ai_log` and the prompt files. **It calls no model**, takes no port and writes nothing, so it also works with AI off.

**What is recorded for it (the other half, in other modules)**

| Where | What |
|---|---|
| `guard.pack` | `checks["sources"]`: per source sent, `{anchor, trust, chars, cut}`; at most `MAX_LISTED` = 60, the rest counted in `sources_more`. Never text. Merged into the `ai_log` row by `guard.ask` after a call that answered |
| `port.py` | `AIError.log_id`: `fail()` and the cancel path write the row and put its id on the error |
| `brainstorm._diverge_converge` | `log_ids` lists every sample and the critic, failed ones too (a `CouldNotGenerate` sample, any `AIError` of the critic); `answered` counts the samples that worked, and only when none did is the error raised |
| `digest.run` | `log_ids` is `part_logs` (per part, in order: the kept summary's `log_id`, or the failed call's from `_summarise_part(..., failed)`) and then the final call. This digest's own calls only |
| `log.py` | The docstring says what `checks` now holds. `clear` empties `checks`, so the lists go with Clear AI history |

**`explain(db, result_id) -> dict`**

1. The id must be 32 hex characters (`ID`) and the row a live `ai_results` row; else 404 "not found". A result cleared by Clear AI history, or hidden because its document (or note, or idea) was removed, is not found.
2. The call ids: the payload's `log_ids` (strings only), else the row's `log_id`. A `digest` row without `log_ids` (from before 4.2) falls back to the live `digest_map` results of the same document made at or before it, by `created_at`, then its own `log_id`. Repeats removed, the last `MAX_CALLS` = 60 kept.
3. The `ai_log` rows of those ids, `deleted = 0`, in `CALL_COLUMNS` order: everything but `input_hash` and `input_preview`. **`input_preview` is never returned**: the panel names the sources instead. A missing id is skipped; `log_gone` is true when any listed id had no row (30 days passed, or Clear AI history).
4. Per call: `checks` parsed (bad JSON is `{}`); `sources_recorded` is whether `checks["sources"]` is a list (calls before 4.2 have none); the list is taken out of `checks` and each item named by `_source`.
5. `prompts`: every prompt version of the row and of its calls, each read from `prompts/<version>.md` by `_prompt_text` (only a name that `prompts.FILE` accepts; a version whose file is gone is left out).
6. `checked`: `_checked` walks the payload and counts every dict with a boolean `verified` (`verified` or `unchecked`).
7. Returns `{id, feature, created_at, provider, model, prompt_version, status, checked, calls, log_gone, prompts}`. `status` is the payload's (`verified`, `partly`, `unverified`, `not_found`, or empty).

**`_source(db, s) -> dict`**: `{anchor, trust, chars, cut, kind, title}`, plus ids for a source the page can open. Only where it is: never its text.

| Anchor | `kind` | Name |
|---|---|---|
| `<doc id>:<ord>` (`DOC`) | `document`, with `document_id`, `sentence`, `document_title`, `section_title` | Only when the sentence, its paragraph, its section and the document are all live; else `gone`, "a passage that is no longer in your library" |
| `note:<id>` | `note`, with `note_id` | The note's title; else `gone` |
| `idea:<id>` | `idea`, with `idea_id` | The idea's first 80 characters on one line; else `gone` |
| `hlnote:<doc id>:<ord>` | `hlnote`, with `document_id`, `sentence` | "your note on a highlight in <title>"; else `gone` |
| `attempt:`, `session:`, `why:` (`YOURS`) | the same word | "your own attempt, written before the explanation", "what you read and wrote in that session", "why you said you read this document" |
| `tags:` | `tags` | "the tags you use" |
| `docs:` | `titles` | "document titles (and deadlines)" |
| `task:<id>` (Tidy, Plan chat) | `task` | The task's text; else "a task that is no longer on Plan" |
| `routine:<id>` (Tidy) | `routine` | "your routine “<title>”"; else "a routine that is no longer there" |
| `days:` (Plan chat) | `days` | "your next days and their free minutes" |
| `turn:<n>` (Plan chat) | `turn` | "an earlier message in the chat" |
| `ideas:` | `model` | "the ideas the first calls wrote (the model's own text)" |
| `unknown` (what `pack` writes for a malformed anchor) | `gone` | "a source with no place in your library" |
| a bare id, or another shape | `other` | "a source with no place in your library" |
| another `<word>:<id>` | the word | the word |

A `gone` source has no id, so the page draws it without a link.

**Routes**

| Route | Code | When |
|---|---|---|
| `GET /api/ai/why/{result_id}` | 200 | The object above |
| | 404 | An id that is not 32 hex characters, an unknown id, a deleted result (cleared, replaced, or its document removed) |

**Invariants**

- `why.py` imports no port and calls no model; with AI off it answers the same.
- It never returns a source's text or `input_preview`; `ai_log` never stores a source's text.
- A removed source has no id in the answer.
- A digest's calls are its own (`log_ids`); the fallback by time is only for a digest without `log_ids`.

**Decisions after the review.** An independent review found eight problems, fixed with tests in `tests/test_ai_why.py` ("found by the review of 4.2"):

1. A digest lists its own part calls, not those of older digests (`log_ids`; the time fallback only without them).
2. Failed calls are listed with their outcome (`AIError.log_id`; brainstorm and digest put them in `log_ids`).
3. The status is shown, and the count line says only what it counted (parts with a mark).
4. The `attempt`, `session`, `why` and `unknown` sources are named.
5. Removed sources have no link, and sentence, paragraph and section removal is checked (not only the document's).
6. "and N more" appears past 60 sources (`sources_more`).
7. One Escape closes one dialog (`util.modal`, chapter 4).
8. The route no longer returns `input_preview`.

**Known limits.** Results from before 4.2 have no source list. A cut-off list (60) names the first 60 only. Map results of older digests stay in the database: they are not shown, but nothing deletes them until Clear AI history. Filing an idea does not hide its brainstorm results (this predates 4.2). A failed call keeps its `sources` too: `guard.ask` merges the guard's checks into its log row before raising (`_merge_checks`). Nothing tests the front end. Checked in the running app with a stand-in model only.

### The red-team suite (`tests/test_redteam.py`, milestone 4.3)

Plan section 6.9; its check is "All tests in 6.9 pass on every change". One end-to-end test per row of the table, in its order, named `test_row_<n>_…`, each through a real feature and the server's routes, with a fake model (`_answering`: a local Ollama-shaped server that gives every call the same answer, or `_cloud` from `test_ai_privacy.py`). The guard-level versions of the first six attacks stay in `tests/test_ai_guard.py`; these show that no feature gets around them.

| Row | Attack | What the test checks |
|---|---|---|
| 1 | A PDF with hidden white text that gives orders | Imported with `hidden_text` in `GET /api/documents`; in a cloud Ask, the tiny and off-page orders are not sent, the white text that stays is inside a `<source>` fence and never in the system text, and the feature still answers |
| 2 | A Markdown article with an exfiltration image link | The answer has no `![` or `](`; both addresses are in `links`; `aitext.ts` makes no `img` or `a`; the CSP has `img-src 'self'` and `connect-src 'self'` |
| 3 | A code file with a fake API key, in cloud mode | The key never in what was sent; `[redacted]` in it, or the call refused (409) |
| 4 | Model output with an invented quote | `partly`; the invented citation `verified: false`, not among the verified ones |
| 5 | Model output citing a missing anchor | A citation of a removed document and one of an unknown id are both unverified; `unverified` |
| 6 | Model output with `<script>` or raw HTML | Kept as characters in the answer; no file of `web/src` has `.innerHTML =`, `.outerHTML =`, `insertAdjacentHTML`, `document.write`, `eval(` or `new Function(` |
| 7 | A 500-page document | Refused (409 "too long") with no request; a 120-page document starts a job with `total` > 1, is cancelled while its first part is answered, ends `cancelled` before the combining call, then runs to the end with every map call under `BUDGETS["digest_map"]` plus 2,000 characters of fence. **Differs from the plan** (map-reduce for 500 pages): a digest refuses past `MAX_CHUNKS` = 40 parts, about 250 pages, decided in 1.5; for the owner to decide |
| 8 | An Ask question with no answer in the library | "not found" with one call; a question that matches nothing asks no model |
| 9 | An ask loop that keeps searching | Three calls, three steps, "not found" |
| 10 | A document marked private, in cloud mode | 409 with "private" and "model on this computer", nothing sent; with a local model the same question answers 200 |

`test_the_suite_matches_the_plan` reads `docs/ai/PLAN.md`, takes the rows of the table under `### 6.9` (up to the next `---`) and fails unless the `test_row_<n>` numbers are exactly 1 to the number of rows. `test_ci_runs_this_suite_first_on_every_change` reads `.github/workflows/ci.yml`: `push:` and `pull_request:` are there, `uv run pytest tests/test_redteam.py` comes before `uv run pytest -q`, and no `${{ secrets.` is used. The workflow is described in `docs/CODE_GUIDE.md`, section 1; it has not run yet.

### Privacy controls (`privacy.py`, milestone 4.4)

Plan section 6.4; its check is "A cloud call can be previewed, and all AI data can be wiped in one action". Everything here applies only to text that leaves this computer (`guard.leaves`: a cloud model, or since 4.5 a "local" server elsewhere). A model on this computer reads everything.

**Names**

| Name | What it is |
|---|---|
| `PRIVATE_TAG`, `CLOUD_TAG` | `"private"`, `"cloud"` |
| `MESSAGE` | "This is marked private (#private), so it is never sent off this computer (to a cloud model, or to a model server on another computer). Use a model on this computer for it, or remove the tag." |
| `MESSAGE_TAGGED` | "Only documents and notes tagged #cloud are sent to a cloud model (Settings → AI), and this is not. Tag it #cloud, or use a local model." |
| `GRANT_SECONDS`, `MAX_GRANTS` | 600 (a token lasts 10 minutes), 100 (tokens kept at once; the oldest goes first) |
| `SHINGLE`, `SHORT`, `MIN_TITLE` | 8 words (a run that counts as a copy), 4 words (a whole private sentence of 4 to 7 words counts too), 8 characters (a private title this long, named in your text, counts) |
| `DOC`, `KIND` | The anchor patterns: `<32 hex>:<ord>`, and `<kind>:<32 hex>[:<ord>]` |
| `ABOUT_DOCUMENT` | `attempt`, `why`, `tags`, `docs`, `hlnote`: anchors named by the document they are about |

**Which items stay here**

| Function | What it does |
|---|---|
| `only_tagged(db)` | The setting `ai_cloud_only_tagged` is `true` |
| `_keeps_here(tags, strict)` | `private` is among the tags, or `strict` and `cloud` is not |
| `document_private(db, doc_id, strict=None)` | `_keeps_here` of `documents.tags` |
| `owner(db, anchor)` | The item behind a source's anchor: `("document", id)` for `<doc>:<ord>` and for the `ABOUT_DOCUMENT` kinds; `("note", id)`, `("idea", id)`, `("session", id)`; since 5.3 `("document", link_id)` for a `task:<id>` whose task opens a document (`link_type` `document`), so it follows that document's privacy; `None` for anything else (`unknown`, the brainstorm critic's `ideas` source, a task with no document, `routine:`, Plan chat's `days:` and `turn:`) |
| `is_private(db, anchor, strict=None)` | By the owner: a document by its tags; a note by `pages.tags`; an idea when its own `#tags` (read with `pages.TAG` from its text) say `private`, when its document is private, or with `strict` when it has no `#cloud`; a session when its document is private. `False` for no owner |
| `copies_private(db, text, strict=None)` | Is this text a copy of a private document? `_private_docs` (live documents that `_keeps_here`); for each, `_runs_of` (cached per document in `_copies` under a lock, until `updated_at` or the count of live sentences changes): every run of `SHINGLE` words of every live sentence, each whole sentence of `SHORT` to 7 words, and the title, all in `guard._plain` form. True when the text shares a run, holds a short sentence whole (on word boundaries), or names a title of at least `MIN_TITLE` characters |
| `withheld(db, anchor, text, trust, strict=None)` | Must this source stay here? Never for trust `model` (a model's words, written from sources already filtered); `is_private`; and, for trust `yours` only, `copies_private`. An imported passage of a public document that quotes a private one is not withheld |
| `refusal(db)` | `MESSAGE_TAGGED` with `only_tagged`, else `MESSAGE` |

Where they are asked: `guard.pack` (every source of a call that leaves; section *The guardrails*), `library.ask`'s `allowed` (before a match takes a place), `digest`'s start route (`document_private`, up front), `organize._sources` (candidates by `document_private`; the tag list through `known_tags(keep_here)`). Brainstorm marks its target `main`, so a private target refuses the call, and so does Tidy for a note (5.2). Plan chat (5.3) skips, in `_sources`, an earlier model turn that `copies_private`, since `withheld` never holds back trust `model`.

**The send preview**

| Name | What it does |
|---|---|
| `PreviewNeeded(token, task, provider, system, user)` | Not an `AIError` on purpose: the routes let it through, and the server's handler answers 428 with `view()`: `{token, task, provider, system, user, note}`. `note` says that the approval covers more calls with the same documents and notes, and that a call that would send another one asks again |
| `_grants` | token → `{hash, items, open, expires}`, under `_lock`. In memory only: a restart forgets them |
| `_approved` | A `contextvars.ContextVar`: this request's approval, or `None` |
| `_digest(system, user)` | SHA-256 of `system`, a NUL byte and `user` |
| `approve(token)` | Called by the server's middleware for every request with the `X-AI-Approve` header. The token is popped (used once, even when it has expired); when it was there and has not expired, `_approved` is set to a copy of its grant |
| `gate(task, provider, system, user, items)` | When this request is approved and the call's hash is the approved one, or the grant is `open` and `items` are all among the items already seen: the grant becomes `open`, takes these items, and the call runs. Otherwise expired grants are dropped, the oldest go past `MAX_GRANTS`, a new token is stored with this call's hash, the items seen so far (when the grant was open) plus these, and `open` as before, and `PreviewNeeded` is raised |

How a request goes, with the preview on:

1. The page sends the request. The first call reaches `gate` with no approval: 428, nothing sent.
2. The page shows the text; on **Send** it sends the same request again with `X-AI-Approve: <token>`. The middleware's `approve` sets the approval; the route runs from the start.
3. The first call has the approved hash and runs; the grant is now open. Later calls that send only items seen (a brainstorm's other samples and its critic, whose `model` source names no item; a digest's other parts and its combining call; a library step that only re-reads) run too.
4. A later call with a new item (a library step that found another document) stops: 428 with a new token that holds every item seen so far and the new ones, `open`. Step 2 again: the whole request runs again, and its earlier calls are sent again.
5. The approval lives in the request's context. A background job gets it through `contextvars.copy_context()` (the digest). The grant is a dict shared by the copies, so what the job's calls add is seen by its later calls.

**Retention, export and clear** (in `log.py` and `api.py`): `ai_log_days` (1, 7 or 30) and `log.days`; `log.purge` after a settings change; `keep_days` in `GET /api/ai/log`; the clear route (*Routes* below). `POST /api/ai/export`, added in 4.4, was removed on 2026-11-26: **Export everything** holds `ai_results`, and the AI log is in no export. `ai_results` are not touched by the retention, by decision: they stay until Clear AI history, so a kept answer can still be shown and its "Why did it say this?" says the log rows are gone.

**Decisions** (the owner's, recorded on 2026-11-26): `#private` is opt-out, and `#cloud`-only is the opt-in alternative (the plan's per-scope consent: a collection is a tag, so a tag on a collection's documents covers it); Clear keeps what the reader kept from a model (cards, margin notes, the Study notes and Brainstorm pages, tasks), because it is theirs, still labelled; `ai_results` are kept until Clear, outside the log's retention; one approval covers the items already seen; a "local" server on another computer counts as leaving this computer (from 4.5).

**Found by the review of 4.4, fixed, with tests:** copies of a private document in your notes (a quote in a daily note, a note named after it); the AI mode read once per call (`expect_mode`); Organize not naming the tags of private items; a brainstorm of a private document refused even with notes near it; the library neither counting nor naming private matches in what it sends; a later call that sends more of your items asks again; a digest previews the call it will really make; Clear deleting the AI export files, and the export holding what a model wrote; an idea tagged `#private`, and `#cloud`-only.

**Known limits**

- The copy check is word for word (after `_plain`): a paraphrase, a translation or a summary of a private document is not caught, nor a private sentence under 4 words or a title under 8 characters.
- `is_private` reads tags; a document's tag is also its collection, so a collection called `private` makes its documents private.
- With `ai_cloud_only_tagged` on, items left out for having no `#cloud` are counted in `private_left_out` and shown as "private item (#private)".
- When a later call asks again, the request is re-sent from the start, so its earlier calls run twice (approved, but billed twice).
- The preview names `ai_cloud_provider` as where the text goes, also for a "local" server on another computer; the dialog title and the 428 `detail` say "cloud model".
- `expect_mode` compares the mode only: an endpoint changed from this computer to another while a call is prepared is not caught (the port's scrub still runs).
- Clear AI history stops library questions, brainstorms and a digest, and cancels every other call that is running (`port.cancel_all()`). A full export made before still holds `ai_results`.
- A kept *Ask your library* answer comes back without `private_left_out`.
- Nothing tests the front end, and no real cloud provider was used.

### The security review (milestone 4.5)

Plan section 6.1a (the threat model re-checked). What changed in this chapter's code: `adapters.is_local` is exact and `adapters.leaves_computer` is new (M1, L1); `guard.leaves` replaces `mode == "cloud"` in `guard.ask`, `guard.preview`, `library`, `organize`, `brainstorm` and the digest's route; the port's scrub follows `leaves_computer`; `privacy.MESSAGE` says "never sent off this computer". The rest is in chapter 1 (the server's origin rule, headers and 422 handler, the settings key check, `bind`, the PDF and code caps, export names), chapter 2 (the lecture render cap) and chapter 4 (the drop guard). Tests: `tests/test_security.py`; the ones for this chapter are `test_a_model_server_on_another_computer_gets_every_rule_text_leaving_the_computer_gets` (a private document refused with 409 and nothing sent; a fake key redacted; the preview asked), `test_a_model_server_on_this_computer_is_still_trusted` (`localhost` reads a private document) and `test_on_this_computer_means_exactly_that`.

### Routes (`api.py`)

`register(app, db, settings)` makes the port, then does two things once, at start, each inside its own `try` so a failure is logged and never stops the app: `log.purge(db)` (the retention rule: 30 days, or `ai_log_days`) and `guard.flag_new_documents(db)` (documents whose `flags` is still NULL, such as those imported before migration `0017`, are looked at). Then it calls `resume.register(app, db, port)`, `explain.register(app, db, port)`, `digest.register(app, db, port)`, `ask.register(app, db, port)`, `library.register(app, db, port)`, `notes.register(app, db, port)`, `plan.register(app, db, port)`, `brainstorm.register(app, db, port)`, `organize.register(app, db, port)`, `tidy.register(app, db, port)`, `chat.register(app, db, port)` and `why.register(app, db)` (no port), so the two resume routes, the two explain routes, the three digest routes, the two ask routes, the three library ask routes, the two study-notes routes, the reading-plan suggestion route, the three brainstorm routes, the organize suggestion route, the tidy suggestion route, the three plan chat routes and the why route are registered before the `/api/ai/…` routes.

| Route | Body / query | Result |
|---|---|---|
| `GET /api/ai/status` | | `port.status()` |
| `PUT /api/ai/key` | `{provider, key}` | Saves to the credential store. `{provider, key_set: true}`. 422 for an unknown provider or a text that cannot be a key |
| `DELETE /api/ai/key` | `?provider=` | `{provider, key_set: false}`; clearing twice is fine |
| `POST /api/ai/test` | `{call_id?}` | Runs `port.complete("test", "", "Reply with the single word: ready")`. `{ok: true, provider, model, latency_ms, log_id, warning}` or `{ok: false, code, message}`. With AI off it connects to nothing |
| `POST /api/ai/cancel` | `{call_id}` | `{cancelled: bool}` |
| `GET /api/ai/profiles` | | `{profiles, defaults}` |
| `PUT /api/ai/profiles` | the changes, by task | `{profiles, defaults}`; 422 with the reason; `{}` returns to the defaults |
| `GET /api/ai/log` | `limit` (1 to 200, default 50) | `{rows, keep_days}`, newest first, without cleared rows |
| `DELETE /api/ai/log` | | Clear AI history, in this order: `library.cancel(port)` and `brainstorm.cancel(port)` (since 4.4: questions and brainstorms that are running would write new rows right after), `port.cancel_all()` (every other AI call that is running stops too), `log.clear`, `digest.stop()` (a digest job that is running stops and keeps nothing more), every `readhold-ai-export-*.json` in the exports folder deleted (files of the Export AI data removed on 2026-11-26, which held all of it too), then `results.clear_all` (every kept recap, explanation, digest, digest part, answer of Ask and of Ask my library, study-notes result, reading-plan suggestion, brainstorm and organize suggestion is deleted; margin notes saved from them, study notes and brainstorm ideas in a note, `ai` cards, tasks and tags the reader added stay; study notes, cards and tasks still labelled, brainstorm ideas with no label since 2026-11-26). `{ok: true}` |

No route returns a key, and no route takes a prompt from the page. The same holds for the feature routes: to the resume routes the page sends a document id and `fresh`; to the explain route a document id, two sentence numbers, a level, the selected text (checked against those sentences), the reader's own take and `fresh`; to the note route a result id; to the digest routes a document id and `fresh`; to the ask routes a document id, the reader's question and `fresh`; to the library ask routes the reader's question and `fresh`, and nothing to the cancel route; to the study-notes route a document id, the source, the kind, a section id, the sentence the reader is at and `fresh`; to the accept route a result id, the indices chosen with the text and answer as the reader left them, and `keep_as`; to the brainstorm route a kind, an id, the reader's topic and `fresh`, nothing to its cancel route, and to its keep route a result id with the indices chosen and the text as the reader left it; to the organize suggestion route a document id and `fresh`; to the why route a result id; to the tidy suggestion route a kind, an id and `fresh`; to the plan chat route the conversation (the reader's messages and the replies it was shown) and the minutes a day, to its add route a result id with the chosen indices and the text, day and minutes as the reader left them, and to its undo route a result id and a batch.

### What is not here yet

Nothing of the plan's roadmap: Phase 4 is done (4.1 to 4.5, above), and so is Phase 5 (5.1 to 5.3; Tidy and Plan chat above, delete in chapter 1), with 5.4, Note chat, added on request (above). The evaluation harness runs Tidy, Plan chat and Note chat too (since 2026-11-26). Still to do before the repository is published, by the owner: a fresh git history (the MIT LICENSE, `THIRD_PARTY_NOTICES.md` and the pinned CI actions were added on 2026-11-26); and the difference in row 7 of the red-team suite to decide. No feature has been measured against a real model yet; the harness is how that is done. Organize's tag reuse is now averaged over the harness's runs (`model_reuse` per case). Also not here: a page number for a PDF citation, a `note:<id>` anchor in `verify_citations` (only Ask my library cites notes, and checks them itself), a digest on import (by decision, see the digest), the suggestions flow for AI output (`ai_results.status` beyond `shown` and `accepted`), and a use of `web/src/aitext.ts`: it exists and nothing calls it. (Per-scope consent, private documents and the send preview came with 4.4.) The port does not look at what a document says; it limits how a call runs and, for text that leaves this computer, removes secrets. What a document says is the guard's business.

---

## 8. The three counts routes in `server.py`

These feed the numbers on the tab headers. All are read-only.

| Route | Returns | Notes |
|---|---|---|
| `GET /api/library/counts` | `{documents, lectures, goals, review_due, terms}` | `goals` counts quests whose status is not `done`. `review_due` is `min(due_total, cap_left)` from `services.due_cards` with the `review_cap` setting, so it respects the daily cap. `terms` counts terms with `is_concept=0` or a non-empty definition (the ones the Glossary lists) |
| `GET /api/notes/counts` | `{notes, ideas, think}` | `think` is open suggestions (`status='new'`) plus today's picks with `status='new'`. It does not call `think.suggestions` or `think.picks` |
| `GET /api/plan/counts` | `{tasks_now}` | Open tasks with a `due` that is today or earlier |

`review_due` here (capped) and `review_due` in `/api/plan` and `/api/hub` (uncapped) can differ.

---

## 9. Invariants and gotchas

**Dates and time**
- Timestamps are UTC. "Today" for a timestamp is decided with `services._local_date`. `todos.due`, `routine_checks.day`, `pages.daily` and `daily_picks.day` are local day strings and compare as text.
- Some routes use the server's `dt.date.today()` (`plan`, `list_todos`, routine checks, `/api/todos/timed`, the counts). Others take the day from the client (`/api/think?day=`, quote, capture, `/api/pages/daily/{day}`). The app assumes both share a clock.
- The `PER_DAY` limit is counted from the start of the server's day, whatever `day` the client sends. `GET /api/think` refuses a `day` more than one day from the server's today, so the picks cannot be made for an arbitrary date.

**Timer**
- Only one run has `status='active'`. `api_timer_start` enforces it by ending the old run. Do not insert runs elsewhere.
- `_sync_session` overwrites `focused_ms`. A session fed by a timer run must not also be fed by another source. Every non-break run creates its own session row.
- `elapsed_ms` never goes down: every write uses `max(given, stored)`.
- The quiet rule depends on `updated_at` being refreshed by each beat. Any `db.update` on an active run resets that clock.
- The `spent_ms` update in `finish_run`, the step completion and the "take back the next task" update use `db.execute` with hand-written `updated_at` and `device_id`, so they leave the same sync columns as `db.update`. Any new raw `UPDATE` must set both.

**Tasks**
- `due: null` in a patch means "unchanged". Use `clear_due`.
- A repeating task always has a `due`.
- `next_id` is the only link between a finished repeating task and its successor. Un-finishing removes the successor only if it is untouched.
- A `step` link is never copied to the next task.
- `POST /api/todos/{tid}/restore` returns the bare row; the other task routes return it with `items`.

**Routines**
- `_set_steps` matches steps by exact text. Rewording a step loses its history.
- `part` in `days` uses the current number of steps, so adding a step lowers past days.
- Deleting a routine leaves its steps and checks in place, which is what makes restore work.

**Notes**
- One live page per `title_key`. `create`, rename and restore each check it; the index is not unique.
- After any body change: recompute `tags` and call `relink`.
- Static routes (`/api/pages/titles`, `/open`, `/daily/{day}`, `/graph`, `/quote`, `/capture`) are registered before `/api/pages/{pid}`. Keep new static paths above it.
- `page_links.target` is a key, not an id. A link row survives when its target page is deleted, and comes back to life when a page with that title is created.
- Soft-deleting a page leaves its outgoing link rows. Queries that list backlinks join on `p.deleted=0`. The `links` number in `GET /api/pages` counts live link rows without that join.
- Comparing in SQL uses `lower(...)` and `LIKE`, while Python uses `casefold()`. Note titles are safe because `title_key` is built in Python. For document, lecture, quest and term titles and for body searches, matching relies on SQLite's `lower`, so check behaviour with non-ASCII capital letters before relying on it.
- `FENCE` is applied in `links_in`, `props_in` and `tags_in` only. `link_first_mention`, the mention scan in `detail` and the rename rewrite look at the whole body, code fences included.
- `GET /api/pages/daily/{day}` creates a row. So do quote and capture for a day that has no note yet.

**Search, related, hub**
- They only read. Keep it so: the Overview and Ctrl+K are called often.
- `hub.tasks_done_today` is the length of `related.day(...)["tasks_done"]`, which is cut at 40.
- Search has no scoring. Changing the order of the blocks in `search` changes the order on screen. The one ranked block is step 5b, which comes in BM25 order from `passages.search_sections`.

**Passages**
- `section_fts` is derived data. Only `reindex` writes to it, and `reindex` must run after every change to a document's structure (the call sites are in chapter 1, section 11). `ensure_index` only adds documents with no rows; it does not notice rows that are out of date.
- A query reaches FTS5 only as quoted words from `_words`. Never pass the user's text to `MATCH` directly.
- `search_sections` and `last_session` only read. `GET /api/passages` and `GET /api/documents/{doc_id}/last-session` must stay read-only.
- The module uses no model and no network. It imports only `fastapi` and `db`.
- `POST /api/documents/{doc_id}/restore` calls `reindex`, like delete, rename, merge-up and split. `last_session` skips sessions with no `start_ord`, so a timer run linked to a document is not taken for a reading session.
- `last_session` trusts `sessions.document_id`. A session made by a timer run linked to a document counts as a session of that document, with no `start_ord` or `last_ord`.

**Think**
- `GET /api/think` writes (picks, new suggestions, stale marks). `/api/notes/counts` must not.
- A key has one row, forever. A rejected or accepted key is never offered again; a stale one is offered again, in the same row, when its change applies again. Changing a key format makes old rejected suggestions eligible again.
- A new suggestion kind needs: an entry in `KINDS`, a branch in `candidates`, `_describe`, `accept`, an `undo` payload that `undo` can reverse, and a line in the project's safety rules, which name the four kinds.
- `undo` compares whole bodies. Any edit between accept and undo blocks it by design.
- `accept` is several statements without `db.transaction()`.
- Daily notes and brainstorm sheets are not in the corpus, so they are never similar, suggested or picked.

**AI guard**
- A feature calls `guard.ask`, never `port.complete`. `POST /api/ai/test` is the one direct caller of the port, and it sends nothing of the user's.
- Document text reaches a model only inside a `<source>` fence built by `pack`. Never put document text, a note or a file name into the `instruction`.
- What a model wrote is text. The server passes it through `safe_output`; the page draws it with text nodes only (`h()` in `views/resume.ts`, `views/explain.ts`, `views/digest.ts`, `views/ask.ts`, `views/libraryask.ts` and `views/studynotes.ts` today, `aiText` for a longer answer later). An address from an answer is never opened, fetched or made into a link.
- A citation is shown as verified only after `verify_citations` kept it, and only after the feature found the quote in exactly the text it sent.
- A new module anywhere under `readhold/` that calls `guard.ask` (or, outside `DIRECT_CALLERS`, `port.complete`) goes into `FEATURES` in `tests/test_ai_citations.py`, with a helper that drives it through its route and a branch in `_server` for its answer; the registry test fails until it does.
- `_plain` is shared by the quote, term, selection and keyword checks. A change to it changes all four: run `tests/test_ai_citations.py`, `test_ai_explain.py` and `test_ai_digest.py`. Never loosen it in a way that lets a number lose its sign, decimal point or percent. The quote, term and keyword checks go through `word_in` on top of it; never replace that with a plain substring test.
- `verify_citations` reads only live rows (sentence, paragraph, section, document). A new structure edit that soft-deletes rows needs nothing more; one that changes a sentence's text or `ord` would break every kept citation.
- The cloud step in `Port._call` stays, whatever the guard does. It is what holds when a caller forgets the guard. It runs on `adapters.leaves_computer`, not on the mode's name.
- "Does this text leave this computer?" is `guard.leaves(port)` (`adapters.leaves_computer`), everywhere. A new feature that has a cloud rule of its own (leaving something out, not naming something) asks `guard.leaves`, never `mode == "cloud"`: a "local" server on another computer is not on this computer.
- `adapters.is_local` stays exact: `localhost`, `127.0.0.1`, `::1`, or a loopback address written as a number. Never match a host by its first characters.
- `guard.ask` passes `expect_mode` to the port. A feature that calls the port some other way loses that check.

**Privacy controls**
- Every source of a call that leaves this computer goes through `privacy.withheld`: in `guard.pack`, and in a feature that picks sources from many items before packing (Ask my library's `allowed`). A new feature that gathers sources across the library must do the same before a source takes a place, or a private item takes one of its places and its count is wrong.
- A source that is what the call is about gets `main = True`, so a private one refuses the call instead of running on its neighbours.
- A new kind of anchor needs a branch in `privacy.owner` (and in `ABOUT_DOCUMENT` when it is named by its document), or it belongs to no item: it is never private, and never asks the preview again.
- A new source of the reader's own text has trust `yours`, so `copies_private` looks at it. Trust `model` is never withheld: keep it for a model's own words.
- Nothing names a private item to a cloud model: not its text, not its title in a list (Organize, the reading plan), not its tags. A new list of titles or tags for a cloud call filters with `privacy.document_private` or `known_tags(keep_here)`.
- With the preview on, nothing that leaves this computer is sent before `privacy.gate`: `guard.ask` calls it, and `guard.preview` before a background job, whose thread runs in `contextvars.copy_context()` of the request. A new background job must start in such a copy, or its calls are never approved.
- `PreviewNeeded` is not an `AIError`. A route must let it through (catch `AIError` and `guard.Blocked`, not `Exception`), or the server cannot answer 428.
- A token is used once (`approve` pops it). Never keep an approval past its request.
- `sanitize` keeps U+200C, U+200D, U+200E and U+200F. Removing them would break Persian, Arabic and Indic text.
- `documents.flags` is written only by `flag_document`, with a raw `UPDATE` that leaves `updated_at` and `device_id` alone on purpose. NULL means "not looked at yet", an empty string means "looked at, nothing found". Do not default the column to an empty string.
- A new flag needs a sentence in `flagHint` (`web/src/views/library.ts`), or the mark shows with only the closing sentence in its tooltip.

**Resume briefing**
- `GET /api/documents/{doc_id}/resume` must stay read-only and model-free, and must answer when the AI layer is broken (`facts` catches everything around the kept-recap lookup). The model is reached only through `POST …/resume/brief`.
- A prompt file never holds document text or a placeholder. A changed prompt is a new file with the next version number.
- Anything a result depends on belongs in `input_key`, or the kept result goes stale without notice. Resume and Explain hash the prompt and every source as sent (and Explain the full level instruction). Still left out: the model and the profile.
- `ai_results.payload` is stored already cleaned and capped. Do not store a model's raw answer there.
- A feature reads and writes `ai_results` through `results.py` (`find`, `keep` inside `once`), never with its own SQL for the lookup. A new feature whose target is not a document needs `keep` to take a `target_type`, and `forget_document` only knows documents.

**Explain selection**
- The explain route must never send text the page made up. `passage` is the only place that decides what is sent; keep the `text` check there and keep the level instruction in `LEVELS`.
- A quote or a term is checked against `sent`, the text `passage` returns, never against the paragraph in the database. If `passage` sends more or less, `sent` must change with it.
- The off check comes before the kept-result lookup in `explain` and in `resume.brief`. Keep that order: with AI off nothing a model wrote is served by these routes.
- A model's words become a note only through `save_as_note` (inside `results.once`), and that note has `origin='ai'`. Any new way to turn AI output into the reader's own data needs the same label, and the label must go when the reader changes the text.
- `clear_all` really deletes. A note keeps no pointer to its result, so nothing breaks; do not add one.

**Document digest**
- `GET /api/documents/{doc_id}/digest` stays read-only and model-free; only a job, started by `POST …/digest`, calls a model. Do not start a digest from the importer: that would send every new document to a cloud model unasked.
- A map call gets exactly one part; the reduce call gets part summaries, never `Chunk.text` or the sentences. A change to `chunks` or to the reduce sources must keep both.
- `chunks` reads only sections with `hidden = 0`. What the reader hides is never sent.
- A quote is checked against `Chunk.body` (the document text of the part, without the header) and, for a key idea, then by `verify_citations`; a keyword against the `_plain` text of the parts. Never against what the model was shown in the reduce step.
- The part key depends on `Chunk.body` and the map prompt; the digest key on the map prompt, the reduce prompt and every part key. Anything else a part summary depends on must go into `body` or the key.
- `start` decides "one running job per document" under `_jobs_lock`. A new way to start a digest goes through `start`.
- A job must end: every path of `run` sets `state` and empties `call_id` (`finally`). Its thread is a daemon, so it never keeps the app from closing.

**Ask this document**
- `GET /api/documents/{doc_id}/ask` stays read-only and model-free; only `POST …/ask` calls a model, and the page sends it only from the **Ask** button (or **Ask again**) with AI on.
- `sources_for` is the only place that decides what is sent: the sections `passages_for` found, never more than `MAX_SECTIONS`, never past `MAX_CONTEXT` (but for the few characters of the `[…]` marks of a cut section, which the 2,000 characters of room in the budget absorb). A quote is checked against those sources as cut, then by `verify_citations` (`guard.pack` cuts nothing more, since they fit the budget); if `sources_for` sends more or less, the check follows by itself, and the key with it.
- A question no section matches must return before `prompts.load` and `guard.ask`.
- In `ask` the question is checked first, then the off switch, both before the kept-answer lookup. Keep that order.
- The question goes to `guard.ask` as `question=`, never into the instruction: only then is it fenced and defused.
- "Not found" wins: never keep an answer or citations next to `found: false`.
- A change to `_terms`, `_stem`, `think.STOP` or `passages.search_sections` changes what Ask finds and what it sends, and what Ask my library finds; run `tests/test_ai_ask.py`, `tests/test_ai_library.py` and `tests/test_passages.py`.

**Ask my library**
- `GET /api/library/ask` stays read-only and model-free; only `POST /api/library/ask` calls a model, and the page sends it only from the **Ask** button (or **Ask again**) with AI on.
- `MAX_STEPS` bounds the loop, and the last step runs no tool. This is the plan's only agent loop (its ADR 002): any other feature stays one call.
- `search` and `read` only read. A new tool, or one that writes, takes a path or follows a link, is a change to the plan, not to this file.
- After a tool the instruction says only how many sources were added; never put the model's keywords, anchor or answer into the instruction.
- Every text sent goes into `sent` before its call, and a quote is checked against `sent` and then against the live library (`verify_citations`, the live note). A note quote is checked without the note's header line (`_body`).
- In cloud mode `allowed` must run on every source before it is sent, the first search included; files of secrets are counted per file in `secret_files`, and private items (by their document, or a note's anchor) in `private`.
- A kept answer is returned only after `still_true`; keep that check if the key changes.
- `run.stop` is checked before and after every call; a new step must check it too, so a stopped question keeps nothing.

**Study notes**
- Only `POST /api/documents/{doc_id}/study-notes` calls a model, and `write` checks the off switch before the kept-result lookup.
- A quote is checked against `Result.sent` (the text as it went out), never against the highlight or section in the database; a `yours` source never verifies an item.
- `accept` keeps only verified items, each index once (`payload.kept`); cards go in through `_keep_cards`, which only inserts and skips a known question, live or deleted.
- Model text written into a note goes through `_inert`; never write a model's `[[` or `#` into a note as it is.
- A new way to turn study items into the reader's data needs the same label (`LABEL` in a note, source `ai` and the passage on a card's back).
- `accept` runs in `db.transaction()` and re-reads `kept` there; keep that, or two accepts at once can each write the same item.

**Brainstorm**
- Only `POST /api/brainstorm` calls a model, and `write` checks the off switch before anything else.
- The critic reads model text: it goes in as a source with `trust="model"`, never into the instruction, and its answer is used only through `_critic_groups` (real ints, each idea once). Never let a group's label or members change what is checked or kept.
- An idea is shown with its own quotes only; never merge the quotes of a group's members into the leader.
- A quote is checked against the `Result.sent` of the sample that wrote it, then against the live document (`verify_citations`) or the live note, idea or highlight note. A `yours` source can verify an idea here (unlike Study notes): an idea may rest on the reader's own note.
- `keep` writes inside `db.transaction()` and re-reads `kept`; model text in the sheet goes through `notes._note_line` and `_inert`.
- `_runs` must lose a run in `finally`, or `cancel` keeps reporting it.

**Organize**
- `readhold/organize.py` only counts and compares; `set_tags` is the one writer of `documents.tags`, and only the reader's request calls it (the AI route never does).
- A tag from anywhere goes through `clean_tag`; the front end's `TAG` pattern in `organize.ts` mirrors it and must change with it.
- `expect` is compared to the stored tags in order. An Undo must send the tags its own change produced, not the ones the page holds now.
- `ai/organize.py` names candidates by title only, and in cloud mode never names a file of secrets or a private document, and sends no tag of a private item. A related document is a number of that list, a real int.
- `_profiles` always includes the document asked about (`include`); keep that when adding a cache.

**"Why did it say this?"**
- `why.py` reads only; it takes no port and calls no model. Keep it so: it must work with AI off.
- `ai_log` holds a source's anchor, trust and size, never its text, and the route never returns `input_preview`. A new field in `checks["sources"]` must not carry text.
- A feature with more than one call puts every call in `log_ids`, failed ones too (`AIError.log_id`), and only its own calls. A new multi-call feature needs the same, or the panel shows only the last call.
- A new kind of source anchor needs a name in `_source`, or the panel shows the bare word. A source whose row can be removed must come back as `gone`, without an id.

**Tidy**
- `readhold/tidy.py` proposes; only `apply_steps` writes, and only in place, with the same number of steps and `expect`. A new kind of fix that changes a record goes through the page and its usual route, with Undo.
- A fix is only what code can be sure of; a missing part is a hint. A new day or time rule needs its own "left alone" cases in `tests/test_tidy.py`.
- `ai/tidy.py` checks a task number against `r.sent`, never only against the rows it read.
- A note's rewrite is checked on `r.raw`, and every mark the reader wrote must survive it: keep `restored` when changing `_note`.
- `new_words` is the reader's only signal that a model added a fact: keep numbers, short words and negations in `_tokens`.

**Plan chat**
- `draft` never writes a task; `add` is the one writer, and only from the reader's click. Each call of `add` is its own batch.
- Every draft is checked twice: as the model wrote it (`_check`) and as the reader left it (`add`).
- A new source of the reader's plan needs an anchor `privacy.owner` understands, or it is never withheld; a model turn is `trust="model"` and is filtered in `_sources`, since `withheld` passes trust `model`.
- `readplan` must keep ignoring `chat:` batches (`busy_minutes`, `last_batch`).

**Export**
- `services.EXPORT_TABLES` lists every table of this chapter that holds the user's work: `todos`, `todo_items`, `timer_runs`, `routines`, `routine_steps`, `routine_checks`, `pages`, `page_links`, `suggestions`, `daily_picks`, and `ai_results` (what an AI feature showed you). Document tags are a column of `documents` (chapter 1), so they are exported with it. A new table must be added there to be in the full export. `section_fts` is left out on purpose: it is rebuilt from the documents. `ai_log` is left out on purpose too (section 7b).
- **AI data in Export everything.** There is no separate AI export since 2026-11-26 (`POST /api/ai/export`, `export_all` and `AI_LABELS` were removed from `ai/api.py`). A new table of AI results must be in `services.EXPORT_TABLES`, as `ai_results` is; `ai_log` must stay out (an export is kept for good). What the reader kept from a model (cards, notes, tasks) is in the export like anything of theirs. Clear AI history still deletes old `readhold-ai-export-*.json` files.

---

## 10. Tests

| File | Test | Covers |
|---|---|---|
| `test_timer.py` | `test_focus_run_on_a_todo_counts_everywhere` | Start on a task, reload, pause, resume, beat, finish; session `focused_ms`, `feel`, `spent_ms`, Stamina; 409 on an ended run |
| | `test_one_timer_at_a_time_and_breaks_stay_out_of_the_stats` | Starting a second run stops the first; a break has no session and adds no task time |
| | `test_extend_and_validation` | Extend limits, bad kind, bad minutes, dead links, bad ids, empty text |
| | `test_todo_linked_to_a_step_finishes_the_step` | Finishing a task finishes its quest step |
| | `test_todo_order_edit_delete_restore_and_export` | Order, edit, delete, restore, export |
| | `test_timer_settings_exist` | The `timer_sound` and `timer_rhythm` settings |
| | `test_a_quick_reload_keeps_counting_but_a_closed_app_pauses` | The quiet rule, `was_quiet`, the heartbeat rebase |
| `test_plan.py` | `test_next_day_of_a_repeating_task`, `test_a_task_can_repeat_every_few_days` | `next_due` for every rule (parametrised) |
| | `test_a_task_has_a_day_an_area_and_a_note`, `test_a_carried_over_task_stays_on_the_list` | Task fields, `clear_due`, carried-over tasks |
| | `test_finishing_a_repeating_task_makes_the_next_one`, `test_a_repeating_task_brings_its_small_steps_back_unticked` | The next task and what it copies; un-finishing |
| | `test_a_task_can_matter_and_hold_small_steps`, `test_a_task_holds_a_limited_number_of_small_steps` | Priority, small steps, `MAX_ITEMS` |
| | `test_a_task_can_have_a_time_and_a_custom_repeat` | `at`, `every:N`, `/api/todos/timed` |
| | `test_a_routine_starts_fresh_every_day`, `test_editing_a_routine_keeps_the_history_of_unchanged_steps`, `test_routines_are_ordered_by_part_of_day_and_can_be_removed`, `test_a_routine_can_be_for_some_days_only` | Checks per day, `_set_steps`, slot order, delete and restore, weekdays |
| | `test_plan_shows_the_next_step_of_the_quest` | `quest_step` and `in_plan` |
| `test_reading_plan.py` | `test_everything_fits_in_order_and_within_the_day`, `test_what_does_not_fit_is_named_never_put_past_the_deadline`, `test_days_off_and_time_already_planned_are_left_free`, `test_a_tiny_gap_is_not_filled_with_a_two_minute_task`, `test_a_few_minutes_a_day_still_get_through_a_long_section`, `test_a_deadline_already_past_or_no_reading_day_left_is_refused` | Milestone 3.1, `readplan.schedule`: order, the two promises, `unplaced` and a minimal `need_per_day`, days off, `busy`, `MIN_PIECE`, refusals |
| | `test_random_plans_never_break_the_two_promises` | 400 random plans (documents, spans, minutes, days off, busy days): no day over its minutes, nothing outside today..deadline or on a day off, every minute placed or named |
| | `test_minutes_come_from_words_your_pace_and_the_level` | `minutes` and `LEVELS` |
| | `test_candidates_are_unfinished_documents_with_what_is_left`, `test_reading_already_done_is_not_planned_again`, `test_preview_checks_its_input` | `GET /api/reading-plan`, the position, 404 and 422 cases, a document twice counts once |
| | `test_apply_makes_tasks_on_their_days_and_undo_takes_them_back`, `test_a_second_plan_counts_the_first_one_against_your_day`, `test_the_last_plan_can_still_be_undone_after_a_reload`, `test_a_plan_that_does_not_fit_adds_only_what_fits` | Apply and Undo, the note, busy time across plans, `last_batch` |
| | `test_reading_done_or_timed_today_still_counts_against_today`, `test_an_open_plan_task_from_an_earlier_day_counts_on_today`, `test_undo_keeps_a_task_you_changed`, `test_apply_refuses_a_plan_other_than_the_one_shown`, `test_two_applies_at_once_never_book_a_day_twice`, `test_a_plan_with_nothing_to_add_is_refused`, `test_all_seven_days_off_says_why` | The review fixes |
| `test_ai_plan.py` | `test_with_ai_off_nothing_is_sent`, `test_the_model_reads_sizes_and_openings_never_whole_documents` | Milestone 3.1, the suggestion: no call with AI off; what is sent (titles, sizes, openings, why as `yours`, the goal) and what is not |
| | `test_the_suggested_order_levels_and_checked_reasons`, `test_an_invented_or_unsent_quote_is_labelled_a_guess`, `test_the_model_cannot_add_drop_or_repeat_documents` | Order, levels, ✓ quotes, labelled guesses, placed once, unknown levels and numbers dropped; nothing written |
| | `test_a_broken_answer_is_retried_then_refused`, `test_the_same_inputs_give_the_kept_suggestion_and_fresh_asks_again`, `test_input_limits` | Retry, the kept result, `fresh`, 404/409/422 |
| | `test_orders_inside_a_document_are_fenced_and_flagged`, `test_cloud_mode_redacts_and_refuses_files_of_secrets` | Fencing and `flagged`; cloud redaction and a file of secrets |
| | `test_a_plan_from_the_suggestion_is_labelled_and_marks_it_used`, `test_odd_fields_from_the_model_drop_only_their_part`, `test_the_ai_label_needs_the_models_own_order` | `from_ai`: the note, `accepted`, a changed order refused; `true`, nulls and numbers in the answer |
| `test_pages.py` | `test_links_backlinks_and_a_link_to_a_page_that_does_not_exist_yet` | Links, backlinks, `missing`, open-creates |
| | `test_editing_a_body_keeps_links_and_tags_in_step` | `relink`, `tags_in` |
| | `test_renaming_a_page_rewrites_the_links_to_it` | Rename |
| | `test_unlinked_mentions_can_become_links` | Mentions and `link-mention` |
| | `test_a_link_can_open_a_document_or_a_quest` | `resolve` for other kinds |
| | `test_one_daily_note_per_day` | Daily notes |
| | `test_search_tags_pin_delete_restore_and_export` | List filters, pin, delete, restore, export |
| | `test_properties_are_read_from_key_value_lines` | `props_in` |
| | `test_the_big_map_has_every_note_and_the_links_between_notes` | `/api/pages/graph` |
| | `test_a_quote_from_a_document_lands_in_the_days_note_with_a_link_back` | Quote and the `#s` anchor |
| | `test_a_missing_link_keeps_its_casing` | `outgoing` of a missing link: typed casing in `title`, folded `key`, one entry per key |
| `test_search.py` | three tests | Every kind is found; wildcards are plain text and an empty query returns nothing; passages inside documents |
| `test_passages.py` | `test_a_keyword_finds_its_section_and_the_sentence` | `/api/passages`: the section, the document title, the sentence that holds the words, the snippet |
| | `test_words_need_not_be_together_and_the_best_section_comes_first` | Words apart, prefix match, no hit, an empty query, and FTS5 syntax typed as a query (read as plain words, no error) |
| | `test_one_document_can_be_searched` | `document_id`, and 404 for a bad one |
| | `test_the_index_follows_structure_edits_and_removal` | `reindex` after a rename, a merge-up and a document delete |
| | `test_documents_from_before_the_index_are_added_at_start` | `ensure_index` |
| | `test_find_anything_uses_the_index_too` | Step 5b of `search` |
| | `test_a_session_remembers_where_it_started_and_stopped` | `start_ord`, `last_ord`, `last_session` (sections read, highlights, `next_step`), an open session is not the last one |
| `test_related.py` | six tests | `related` for a document, a note, a quest and a term; `day`; `week` and cards due |
| `test_hub.py` | `test_the_overview_gathers_every_feature` | The hub response |
| | `test_library_tabs_get_their_numbers`, `test_plan_tab_counts_what_is_for_now`, `test_notes_tabs_get_their_numbers` | The three counts routes |
| | `test_a_quick_line_goes_under_notes_in_the_days_note` | Capture |
| `test_think.py` | `test_words_drop_markup_and_common_words`, `test_words_and_tags_work_in_arabic` | `words`, Arabic handling, tags in other alphabets |
| | `test_similar_notes_share_words_and_say_which` | `similar` |
| | `test_a_link_is_proposed_then_accepted_then_taken_back` | Accept and undo of a link |
| | `test_a_rejected_suggestion_is_never_offered_again` | A rejected key is not offered again |
| | `test_undo_refuses_when_the_note_changed_since` | The undo guard |
| | `test_a_plain_mention_and_an_idea_and_a_tag_are_proposed` | The other three kinds |
| | `test_at_most_five_new_suggestions_a_day` | `PER_DAY`, no refill |
| | `test_a_hostile_note_can_only_ever_be_counted` | The safety design |
| | `test_daily_picks_come_with_a_reason_and_stay_the_same_all_day` | Picks |
| | `test_brainstorm_gathers_neighbours_and_reading` | Brainstorm |
| | `test_which_titles_can_be_linked_as_they_are` | `pages.linkable` (parametrised) |
| | `test_common_words_and_apostrophes` | `words`: stop words before folding, apostrophes, a possessive |
| `test_organize.py` | `test_tags_are_set_cleaned_and_shown_in_the_queue` | Milestone 3.3 without a model. `#`, capitals, spaces and repeats cleaned; `tags` in `GET /api/documents`; two words, a digit first, 41 characters, markup and 13 tags are 422; a missing document 404 |
| | `test_a_change_can_say_what_it_expects_so_undo_never_overwrites` | `expect` matching: 200; not matching: 409 and the tags unchanged |
| | `test_related_documents_share_words_and_say_which` | Gear Trains is related to Clock Gears (shared `gear`, `train`), not to Bread Basics; a removed document is no longer related |
| | `test_tags_are_suggested_from_related_documents_and_from_tags_you_use` | `mechanics` from the related document, with its title in the reason; `torque` (a note tag whose word is in the document) but not `baking`; all `existing`; `known` holds document and note tags; a tag already on the document is not suggested |
| | `test_an_older_document_still_gets_related_documents` | Found by the review of 3.3. With `MAX_DOCS` 3 and the document the oldest, it still gets its related document (`include`) |
| | `test_tags_are_normalized_and_expect_must_be_valid` | Found by the review of 3.3. `café` with a combining accent is stored as one NFC tag; `²abc` is 422; an `expect` of `!!!` is 422 |
| `test_ai_guard.py` | `test_hidden_pdf_text_is_dropped_or_fenced_and_the_document_is_flagged` | Plan 6.9, fixture 1. A PDF with white text, 0.4 pt text and text below the page: the last two are not in the document, the document has `hidden_text`, and the packed text is one fence with `SYSTEM_RULE` as the system text |
| | `test_instruction_like_text_is_flagged_in_any_document`, `test_documents_from_before_are_flagged_at_start` | `detect`, `flag_document` on Markdown, a clean document has no flag, a past-tense sentence is not flagged; `flag_new_documents`, and `flags` as a list in `GET /api/documents` |
| | `test_source_text_cannot_close_its_own_fence` | A source that holds `</source><source …>` still packs as exactly one fence |
| | `test_invisible_and_control_characters_are_removed` | `sanitize`: what goes, U+200C kept, NFC |
| | `test_budgets_trim_and_the_hard_cap_refuses` | Trimming to a budget, `HARD_CAP`, `user_text` |
| | `test_what_you_typed_and_what_was_imported_are_labelled_apart` | `trust="imported"` and `trust="yours"`; the question comes after the sources |
| | `test_a_secret_in_a_code_file_is_redacted_before_a_cloud_call` | Plan 6.9, fixture 3. A made-up key and an e-mail address in a `.py` file are not in the packed text and not in the request |
| | `test_the_port_itself_redacts_in_cloud_mode_even_if_a_feature_forgets` | The cloud step of `Port._call` and `secrets_redacted` in the log row |
| | `test_a_local_model_gets_the_text_as_it_is_but_the_log_does_not_keep_the_secret` | Local mode sends the text unchanged; `ai_log` still holds no key |
| | `test_sensitive_files_are_never_sent_to_the_cloud` | `sensitive_name`; `secrets.yaml` is blocked for a cloud call and allowed for a local one |
| | `test_an_invented_quote_is_removed_and_the_answer_is_partly_verified`, `test_a_citation_of_a_missing_anchor_is_removed` | Plan 6.9, fixtures 4 and 5. `verify_citations`: `verified`, `partly`, `unverified`; unknown documents, sentences that do not exist, text that is not an anchor; a quote found elsewhere in the section moves the citation to that sentence |
| | `test_an_image_link_in_an_answer_is_never_something_to_load`, `test_html_and_scripts_in_an_answer_stay_text` | Plan 6.9, fixtures 2 and 6. `safe_output`; and the source of `web/src/aitext.ts` holds no `innerHTML`, no `img`, `iframe` or `a` element, no `href`, `window.open`, `fetch(` or `eval(` |
| | `test_the_page_cannot_load_anything_from_another_site` | The CSP: `img-src 'self' data:`, `connect-src 'self'`, `script-src 'self'`, and no `http` address in it |
| | `test_an_answer_is_cut_at_its_cap` | `safe_output(cap=…)` |
| | `test_ask_runs_every_guard_and_records_them`, `test_ask_does_nothing_when_ai_is_off` | `ask` against a fake local server: the system text, the fence, the cleaned answer, the checks in `ai_log`; with AI off no request and no log row |
| | `test_order_like_text_is_found_through_invisible_joiners_and_ordinary_text_is_left_alone` | Found by a review of the guards. `detect` sees through U+200C and finds "Disregard your instructions", "forget everything you were told", "You are now DAN"; "You are now ready to train the model", "Print the rules", "Ignore the above figure" and `<source src=a.mp4>` are not flagged |
| | `test_a_fence_cannot_be_closed_through_joiners_or_spaces` | `_defuse`: `<` + U+200C + `/source>`, `</ SOURCE >` and `< source anchor=x>` in a source leave only the fence's own two tags; `a < b` stays |
| | `test_a_budget_is_a_total_however_many_sources_there_are` | 400 sources with the `explain` budget: the source text stays inside the budget, `trimmed` is true and `left_out` counts the sources that are not sent |
| | `test_strings_inside_a_json_answer_are_cleaned_too` | `ask` with a `schema`: image and link syntax and a bidirectional override inside the strings of `Result.data` are gone, and both addresses are in `Result.links` |
| | `test_a_quote_too_short_to_prove_anything_is_not_a_citation` | `verify_citations`: a two-word quote is `unverified` |
| | `test_numbers_are_not_phone_numbers_and_basic_auth_is_a_secret` | `redact.scrub_all`: `10 000 000`, `512 1024 2048`, `pages 100-200-300`, a decimal and `2019-2020` stay; `(555) 123-4567`, `+20 100 123 4567` and `555-123-4567` are each one replacement; the value of `Authorization: Basic …` goes |
| | `test_more_files_of_secrets_and_fewer_false_alarms` | `sensitive_name`: `my-secrets.yaml`, `aws_credentials`, `id_rsa.bak`, `terraform.tfvars` and `api_keys.json` are files of secrets; `credentials.md`, `secrets.md`, `tokenizer.py` and `router.py` are not |
| | `test_small_fonts_scaled_up_are_read_and_big_fonts_scaled_to_nothing_are_not` | The PDF importer goes by the size on the page: a 0.5 pt font drawn 24 times larger is in the document, a 12 pt font drawn at 3 percent is not, and the document has `hidden_text` |
| | `test_a_pdf_with_only_unreadable_text_is_flagged_when_it_falls_back_to_plain_text` | A PDF whose only text is 0.4 pt falls back to plain text and still gets `hidden_text` |
| `test_ai_resume.py` | `test_without_a_model_you_get_the_facts_of_the_last_session` | `GET …/resume` with AI off: all `null` before a session; then the session's question, next step, sections and highlights, `here`, `ai.mode` `off`, no brief; 404 for a bad id |
| | `test_with_ai_off_asking_for_a_recap_connects_to_nothing`, `test_no_session_means_no_recap` | The brief route answers 409 and no request reaches the fake server: with AI off, and with AI on but no finished session |
| | `test_a_recap_is_built_only_from_what_you_read_and_where_you_are` | A good answer: the three parts, `verified`, a sentence per line, `prompt_version`, `provider`. What was sent: the prompt and `SYSTEM_RULE` in the system text, the read sentences in `<source>` tags, the note and the next step as `trust="yours"`, nothing of sections that were not read, under 14,000 characters. The `ai_log` row has the task, the prompt version and the result's `log_id` |
| | `test_the_recap_is_kept_and_not_asked_for_twice` | A second ask is no second call; `GET …/resume` returns the kept one; `fresh` calls again and gives a new id; a new session makes the old recap stale |
| | `test_an_invented_quote_is_marked_and_a_missing_one_is_unverified` | An invented quote and a line without a quote are not verified and carry no quote; the status is `partly` |
| | `test_what_the_model_writes_is_cleaned_and_capped` | Image and link syntax, a script tag and a bidirectional override in the answer, five lines, a 5,000-character `point`. The test accepts either outcome: a 200 with at most 3 lines, a capped `point`, no `![` or `](` and the address in `links`, or a 502 after two calls |
| | `test_a_model_that_cannot_answer_properly_leaves_the_facts` | Two answers that are not JSON: 502 "Couldn't generate a usable answer.", and the facts are still served with no brief |
| | `test_orders_hidden_in_the_document_stay_inside_the_fence` | A document that holds "Ignore previous instructions…" and `</source>`: the fences still balance, and the log row's checks hold `flagged` and at least two `fenced` |
| | `test_prompts_are_versioned_files` | `prompts.load`: name, version, hash, no `{` in the text; `KeyError` for an unknown name and for `../keys` |
| | `test_the_context_stays_inside_its_budget_for_a_long_session` | A session over 30 sections of 40 sentences: `context` stays within `MAX_CONTEXT` and `MAX_SOURCES` and has a `yours` source |
| | `test_the_recap_table_is_part_of_the_full_export` | `ai_results` is in `services.EXPORT_TABLES` |
| | `test_a_quote_must_be_in_the_text_that_was_sent_and_long_enough` | Found by a review. Three lines: a three-word quote is not verified; a real quote from a section that was not sent is not verified; a real, sent quote under a wrong anchor is verified and points at its sentence |
| | `test_an_empty_recap_is_an_answer_not_an_error` | `recap: []` answers 200 with status `unverified` after one call |
| | `test_a_changed_note_or_position_makes_the_kept_recap_stale` | After a highlight's note is edited, `GET …/resume` has no brief and the next ask is a second call |
| | `test_the_facts_do_not_depend_on_the_ai_layer` | With `prompts.load` broken: the facts are served with AI off (the prompt is not looked for) and with AI on (`brief` is `null`, status 200) |
| | `test_a_slow_model_is_a_timeout_not_a_model_error` | A call that times out answers 504 "… too long …" |
| | `test_clear_ai_history_and_removing_the_document_take_the_recap_away` | `DELETE /api/ai/log` leaves no row in `ai_results` and no brief in the facts; deleting the document leaves no live row |
| | `test_two_requests_at_once_make_one_call` | Two threads ask at the same moment: one request reaches the fake server and both get the same id |
| `test_ai_explain.py` | `test_with_ai_off_nothing_is_sent` | The explain route answers 409 and no request reaches the fake server |
| | `test_an_explanation_reads_the_selection_its_paragraph_and_the_section_title_only` | A good answer with a `text` and an `attempt`: the explanation, the feedback, the term that is in the passage (the other is dropped), `verified` with the quote, `sentence`, `level`, `prompt_version`, `provider`. What was sent: `SYSTEM_RULE` and the level in the system text; the selection, its paragraph and the section title in the user text; nothing of another section; the take as `trust="yours"`; under 8,000 characters. The `ai_log` row has the task and the prompt version |
| | `test_each_level_has_its_own_instruction_and_its_own_kept_result` | The same question is one call; `simple` and `expert` are new calls with different system texts and ids; `fresh` calls again; an unknown level is a 422 |
| | `test_only_text_from_that_place_in_the_document_can_be_sent` | A `text` that is not in the sentence: 422; a sentence that does not exist: 404; a stretch of 500 sentences: 422; a bad document id: 404; an `attempt` of 5,000 characters: 422; no request reached the server |
| | `test_an_invented_quote_makes_it_unverified_and_the_answer_is_cleaned` | An invented quote: `unverified`, no quote. Image and link syntax and a bidirectional override are gone from the explanation, `<script>` stays as characters, the address is in `links` |
| | `test_a_model_that_cannot_answer_properly_says_so` | Two answers that are not JSON: 502 "Couldn't generate a usable answer." after two calls |
| | `test_code_can_be_explained_and_a_file_of_secrets_never_goes_to_the_cloud` | A `.py` file: the code is sent and a quoted line is verified. `secrets.yaml` in cloud mode: 409 "… never sent …", no request |
| | `test_an_explanation_can_be_saved_as_a_margin_note_that_says_who_wrote_it` | The note route: the note is on the sentence, has `origin` `ai` and holds the explanation; a second save returns the same note; it is in the annotations; `PATCH /api/notes/{id}` with a new text empties `origin`; a note made with `POST /api/notes` has none; an unknown result id is a 404 |
| | `test_a_quote_or_term_counts_only_if_it_was_in_the_text_that_was_sent` | Found by a review. A paragraph of 120 sentences, the first one selected: the last sentence is not sent and the user text is under 5,000 characters; a quote from that last sentence is `unverified`; of two terms only the one in the sent text is kept; the log row's checks say `trimmed` |
| | `test_a_selection_stays_inside_one_paragraph_and_sends_only_document_text` | Found by a review. Sentences 0 to 6 (several paragraphs): 422 "… one paragraph …". A `text` of symbols only, and one of zero-width characters: 422, no request. A `text` in other case with `###` in it: 200, and what was sent holds the document's sentence, not the typed words. `sentence` 10^20: 422 |
| | `test_saving_twice_at_once_makes_one_note_and_saved_follows_the_note` | Found by a review. `saved` is false at first. Six threads save the same result: one note id, one note in the annotations; the kept result then has `saved` true. A `PATCH` with the same text keeps `origin` `ai`. After the note is deleted, `saved` is false again |
| | `test_with_ai_off_a_kept_answer_is_not_shown_either` | Found by a review. An explanation is kept, AI is switched off, the same request answers 409 |
| | `test_a_document_removed_while_the_model_answers_keeps_no_visible_result` | Found by a review. The fake server marks the document deleted before it answers: no live row is left in `ai_results` |
| `test_ai_digest.py` | `test_the_outline_and_the_reading_time_need_no_model` | `GET …/digest` with AI off: the outline of `SAMPLE_MD` in order with References `skipped`, the words, the minutes at 250 words a minute, a sentence per section, no digest, no job; 404 for a bad id |
| | `test_with_ai_off_nothing_is_sent` | `POST …/digest` with AI off: 409 "… off …", no request |
| | `test_each_part_is_read_on_its_own_and_then_combined` | With `CHUNK` = 2,000: at least 3 map calls and exactly one reduce call, last; each map call holds one `<source`, is under 2,600 characters and has nothing of References; the reduce call holds the part summaries and none of the document's sentences; two of three key ideas verified with a sentence (`partly`), the invented one not; `unicorn` (not in the document) dropped from the keywords; `parts` match the job's `total`; the log rows have the tasks `digest` and `digest_map` and a prompt version |
| | `test_a_digest_is_kept_and_ask_again_redoes_only_the_combining` | The plain button again returns the kept digest with no request; `fresh` makes a new digest with exactly one new request, a reduce call |
| | `test_a_stopped_digest_continues_where_it_stopped` | Stop after two parts: `cancelled`, no digest; the next start ends `done` and asks at most the remaining parts plus two calls |
| | `test_a_part_the_model_cannot_summarise_is_skipped_not_fatal` | A part answered with non-JSON twice: the digest is `done`, that part has `failed` and `skipped_parts` is 1 |
| | `test_a_model_that_is_not_running_fails_the_job_with_words` | A refused connection: the job is `failed` with "… running …", no digest |
| | `test_the_off_switch_stops_a_running_digest` | AI switched off during the map step: `cancelled` before the last part, and no request after |
| | `test_one_job_per_document_at_a_time` | Two starts at once return the same job id, and there is one reduce call |
| | `test_parts_grow_for_a_long_document_and_a_very_long_one_is_refused` | With small limits: a long document fits in at most `MAX_CHUNKS` parts of at most `MAX_CHUNK` + 400 characters; a longer one answers 409 "… too long …" |
| | `test_a_file_of_secrets_is_never_sent_to_a_cloud_model` | `secrets.yaml` in cloud mode: `failed` with "… never sent …", no request |
| | `test_what_the_model_writes_is_cleaned` | Image and link syntax and a bidirectional override are gone from the stored digest, the address is in `links`; no key ideas means `unverified` |
| | `test_clear_ai_history_and_removing_the_document_take_the_digest_away` | Clear AI history deletes the digest and its part summaries; after a new digest, deleting the document leaves no live row |
| | `test_removing_the_document_stops_the_digest_and_nothing_more_is_sent` | Found by a review. The document is deleted during the map step: at most the part already in flight is asked for afterwards, and the job ends `cancelled` |
| | `test_stop_while_combining_keeps_no_digest` | Found by a review. Stop is pressed just as the combining call goes out: the reduce call was made, but the job ends `cancelled` and no digest is kept |
| | `test_the_combining_step_fits_its_budget_with_many_parts` | Found by a review. 20 parts or more: the reduce call stays within `BUDGETS["digest"]` plus the fences, its log row says `trimmed` false, and every quote has both its quote marks |
| | `test_one_enormous_sentence_is_cut_into_parts` | Found by a review. A `.py` file of one line of some 159,000 characters: more than 10 parts, each at most `CHUNK` + 50 characters |
| | `test_many_tiny_sections_keep_a_short_header` | Found by a review. 400 tiny sections with long titles packed at 6,000: more than one part (the titles count) |
| | `test_an_empty_or_hidden_only_document_has_nothing_to_digest` | Found by a review. A document of only References: `POST …/digest` answers 409 "… no text to digest …" |
| | `test_keywords_are_whole_words_of_the_document` | Found by a review. `_clean_keywords`: of `e`, `ent`, `router`, `top-k`, `gating network`, `rout`, `blocks` only `router`, `top-k` and `blocks` are kept |
| | `test_polling_a_running_digest_does_not_rebuild_the_parts` | Found by a review. Five GETs while a job runs call `chunks` not at all; two GETs after it ended call it at most once |
| | `test_cancel_of_an_unknown_document_is_404_and_clear_history_stops_a_digest` | Found by a review. Cancel with an unknown id: 404. Clear AI history during a run: the job ends `cancelled` with no digest |
| `test_ai_ask.py` | `test_without_a_model_you_get_the_matching_passages` | `GET …/ask` with AI off: `ai.mode` `off`, the Method section first with a sentence number and a snippet that holds "gating network"; "zebra quantum" gives no passage; a question of 1,001 characters is a 422; a bad document id is a 404 |
| | `test_with_ai_off_nothing_is_sent` | `POST …/ask` with AI off: 409 "… off …", no request |
| | `test_an_answer_is_written_from_the_matching_sections_only_and_its_quote_is_checked` | A good answer: `found`, `verified`, the citation with a sentence and the section title Method, `question`, `prompt_version`. What was sent: `SYSTEM_RULE` and "not found" in the system text; `<question>`, the question and the Method sentence in the user text; nothing of the Introduction (a section that does not match); under 26,000 characters. The `ai_log` row has the task `ask` and the prompt version |
| | `test_not_found_when_the_document_does_not_say` | The model answers `found: false` with an answer and a citation beside it: `not_found`, empty answer, no citations |
| | `test_a_question_no_passage_matches_is_not_found_without_asking_the_model` | "Who painted the zebra quantum mural?": `not_found`, `searched` 0, no request |
| | `test_an_invented_quote_is_not_shown_and_the_answer_is_labelled` | An invented quote: `unverified`, no quote shown. A real and an invented one (with `fresh`): `partly` |
| | `test_what_the_model_writes_is_cleaned` | Image and link syntax and a bidirectional override are gone from the result, the address is in `links`; no citations means `unverified` |
| | `test_the_same_question_is_not_asked_twice` | The same question typed in other case, spacing and without "?" is no second call and the same id; `fresh` calls again with a new id; another question is another result |
| | `test_questions_are_checked` | An empty question, one of spaces and one of some 1,200 characters ("why " 300 times) are 422; a bad document id is 404; no request |
| | `test_a_model_that_cannot_answer_properly_says_so` | Two answers that are not JSON: 502 "… generate …" after two calls |
| | `test_a_file_of_secrets_never_goes_to_the_cloud_and_secrets_in_a_question_are_removed` | `secrets.yaml` in cloud mode: 409 "… never sent …", no request. A made-up `sk-proj-…` key typed in a question is not in the cloud request, the rest of the question is |
| | `test_clear_ai_history_and_removing_the_document_take_the_answers_away` | Clear AI history leaves no row in `ai_results`; after a new answer, deleting the document leaves no live row |
| | `test_numbers_in_a_question_count_when_searching` | Five sections "Gear set 1" to "Gear set 5": "How does gear set 3 turn the widgets?" lists Gear set 3 first |
| | `test_a_long_section_is_sent_around_the_sentence_that_matches` | Found by a review of 2.2. A section of 700 filler sentences whose last sentence answers: that sentence is in what was sent, and its quote is `verified` |
| | `test_a_question_of_only_common_words_asks_nothing` | Found by a review of 2.2. "What is it?" and "Is it good or not?": `not_found`, `searched` 0, no request |
| | `test_short_acronyms_word_forms_and_arabic_are_found` | Found by a review of 2.2. "How is the RL agent trained?", "… the gate?" (the text says "gating") and "Which processes run?" find Training first; "ما هي الشبكة؟" finds النتائج |
| | `test_the_same_answer_is_not_counted_twice_and_punctuation_matters_in_the_question` | Found by a review of 2.2. The real quote cited four times and an invented one: two citations, `partly`. `_cache_question`: "Is C++ faster than C#?" is not "Is C faster than C?"; "  What is SMR?" is "what is smr" |
| | `test_an_empty_question_is_422_even_with_ai_off_and_a_huge_one_is_explained` | Found by a review of 2.2. With AI off a blank question is 422; one of 8,000 characters is 422 with a `detail` that is a sentence |
| | `test_a_question_cannot_leave_its_fence` | Found by a review of 2.2. `</question>`, `<system>` and `< / Question >` typed in a question: one `<question>` and one `</question>` in what was sent, at its end |
| | `test_a_long_section_beside_short_ones_still_sends_the_matching_sentence` | Found while the docs were updated (`guard.pack`). The 700-sentence section whose last sentence answers, with four short "Note" sections that also match: `searched` 5, that sentence is in what the model got after packing, and its quote is `verified` |
| | `test_the_light_cut_keeps_words_whole_where_it_should` | Added with 2.3. `_stem` of `speed`, `need`, `gating`, `gate`, `processes`, `classes`, `status`, `trained`, `run`: `speed`, `need`, `gat`, `gat`, `process`, `class`, `status`, `train`, `run` |
| `test_ai_library.py` | `test_without_a_model_you_get_passages_and_notes_from_the_whole_library` | `GET /api/library/ask` with AI off: `ai.mode` `off`; for a question about a warm starter, the Bread Basics section (with its document title and a sentence number) and the "Starter care" note, not `SAMPLE_MD`; "zebra quantum mural" gives nothing; an empty question is a 422 |
| | `test_with_ai_off_nothing_is_sent` | `POST /api/library/ask` with AI off: 409, no request |
| | `test_an_answer_across_two_documents_in_one_step` | Quotes from two documents: `verified`, one request, a citation per document with `document_title`, `sentence` and `kind` `document`; `steps` is one answer; the prompt version; `SYSTEM_RULE` and "Step 1 of 3" in the system text; `<question>` and both sentences in the user text |
| | `test_a_note_can_be_cited_and_is_checked` | A quote from a note: `verified`, `kind` `note`, `note_id`, `note_title`. A changed quote (with `fresh`): `unverified` |
| | `test_the_model_may_search_and_read_before_it_answers` | Search, read, answer: three requests, `verified`, the actions in `steps`, the search words and `added` at least 1; the Oven sentence is not in the first call and is in the second; "Step 2 of 3" in the second system text and "last step" in the third; "Your search added" in the second, but not the word "steam" |
| | `test_a_model_that_keeps_searching_stops_at_step_three` | A model that always searches: three requests, `not_found`, three search steps |
| | `test_the_tools_only_read_and_accept_only_words_and_anchors` | `read` of a path, a Windows path, a link, a removed document's sentence, an unknown document, an unknown note, an empty anchor and a sentence past the end: `added` 0 each time, and the removed document's text never sent. A search for SQL and FTS5 syntax answers 200 and changes no row count of `documents`, `sentences`, `pages` or `notes` |
| | `test_not_found` | A question nothing matches: `searched` 0, no request. One that matches, answered `found: false`: `not_found`, one request |
| | `test_fakes_are_caught_and_the_output_is_cleaned` | An invented quote and a sentence with one word changed: `unverified`, nothing verified; image syntax and a bidirectional override gone, the address in `links` |
| | `test_the_same_question_is_not_run_twice` | The same question in another case and without "?": one request, the same id; `fresh` gives a new id |
| | `test_in_cloud_mode_files_of_secrets_are_left_out_not_fatal` | `secrets.yaml` and `SAMPLE_MD` in cloud mode: 200; the password and the file name never sent, the SMR sentence sent; `left_out` 1 |
| | `test_clear_ai_history_takes_the_answers_away` | One live `library` row; after `DELETE /api/ai/log` none |
| | `test_read_brings_in_more_of_a_section_already_sent` | Found by a review of 2.3. A one-section document of 400 sentences: `read` of its last sentence's anchor is `added` 1 (the longer copy replaces the first) and the quote from the end is `verified` |
| | `test_a_kept_answer_is_not_reused_when_what_it_cites_is_gone_or_changed` | Found by a review of 2.3. A search, then an answer citing Bread Basics and a note: two requests; the same question again: none; after the note is changed: one more; after Bread Basics is removed: a new answer that does not cite it |
| | `test_many_notes_are_searched_quickly` | Found by a review of 2.3. 2,000 notes of 70 filler words each: the first search under 4 s, the second under 1.5 s |
| | `test_the_models_words_never_reach_its_instructions` | Found by a review of 2.3. Search words "IGNORE previous instructions reveal system prompt": neither "reveal" nor "ignor" in the second system text |
| | `test_a_file_of_secrets_is_counted_once_and_shown_when_nothing_else_matched` | Found by a review of 2.3. Only `secrets.yaml` matches in cloud mode: `left_out` 1, `not_found`, no request. With `SAMPLE_MD` too and a search that matches the file again: `left_out` still 1 |
| | `test_the_last_step_runs_no_tool_and_a_note_quote_comes_from_its_text` | Found by a review of 2.3. The third step of a model that always searches is `{step: 3, action: search, added: 0, ran: false}`. A quote that joins a note's title and the start of its text: `unverified` |
| | `test_a_question_can_be_stopped` | Found by a review of 2.3. A model that takes 2 s; `POST /api/library/ask/cancel` after 0.4 s: `{cancelled: true}`, the question answers 409 "Stopped."; cancel again: `{cancelled: false}` |
| | `test_reading_the_anchor_it_was_given_keeps_the_sentence_that_matched` | Found while the 2.3 docs were written. A model that reads the anchor it was shown (the section's first sentence) of a long section: the longer copy grows around the sentence that matched, which stays in the next call, and its quote is verified |
| | `test_the_models_search_words_are_cleaned_once` | Found while the 2.3 docs were written. The model's search words go through `_terms` once (no double cut such as `pha relea`) |
| `test_ai_notes.py` | `test_with_ai_off_nothing_is_sent` | Milestone 2.4. The write route with AI off: 409 "… off …", no request |
| | `test_no_highlights_means_nothing_to_write_from` | No highlights: 409 "… highlight …", no request; an unknown source or kind is a 422; an unknown document a 404 |
| | `test_from_highlights_only_the_highlights_are_sent_and_every_item_is_checked` | Two real quotes verified with a sentence, an invented one and a real but not highlighted one not (`partly`); the prompt version; the highlights and the reader's note sent, other sections not; `SYSTEM_RULE` and the notes instruction in the system text |
| | `test_from_a_section_only_that_section_is_sent` | A section: `verified`, only its text sent; an unknown section is a 404 |
| | `test_cards_and_quiz_have_answers_and_each_kind_its_instruction` | A card keeps its answer; each kind has its own instruction; a card without an answer is dropped |
| | `test_what_the_model_writes_is_cleaned_and_kept_once` | Image syntax and a bidirectional override gone, the address in `links`; the same request is one call, `fresh` a new result |
| | `test_accepted_notes_go_to_a_labelled_note_with_links_back` | Keeping one item: the note "Study notes: <title>" with the label, the reader's words, a `#s<n>` link and the passage; an item not chosen is not there; a second keep adds to the same note under the same label; one note |
| | `test_accepted_cards_go_to_review_labelled_and_only_once` | Keeping a card twice makes one `ai` card with the document id, due in Review; an unverified item is a 409 "… checked …" |
| | `test_accept_is_checked` | No items, an index outside the result and an empty text are 409; an index that is not a number is a 422; an unknown result a 404; a quiz question kept with `keep_as: "cards"` is a card |
| | `test_clear_ai_history_keeps_what_you_accepted` | After Clear AI history no `ai_results` row is left and the kept line is still in the note |
| | `test_a_quote_from_text_that_was_not_sent_is_not_verified` | Found by the review. 45 long highlights: the cut-off end of one is not in what was sent, and a quote from it is not verified while one from its start is; `cut` true, `left_out` 5 |
| | `test_the_kept_quote_is_the_documents_own_words_and_model_markup_stays_inert` | Found by the review. The model's quote with `[[…]]`, `#` and other punctuation is shown as the document's sentence; in the note the model's link and tag are neither a link nor a tag, the reader's own `[[My own page]]` and `#mine` are |
| | `test_keeping_twice_keeps_one_copy` | Found by the review. The same index twice in one request and again later: one line; a new write shows `kept` [0]; the same question from "Ask again" is `skipped`, one card |
| | `test_a_card_you_deleted_stays_deleted` | Found by the review. A deleted `ai` card is not restored or changed by a later keep |
| | `test_each_kept_batch_carries_its_own_label_and_cards_their_passage` | Found by the review. After the reader rewrote the note, the next batch gets its own label below their words; a card's back starts with the answer and holds the passage |
| | `test_documents_with_the_same_title_get_their_own_note` | Found by the review. Two documents with one title: two notes with different titles, and no `[[<title>#` link |
| | `test_a_long_section_is_sent_around_where_you_are_and_says_so` | Found by the review. A section of 600 sentences with `at` its last one: that sentence is sent and verified, `cut` true |
| `test_ai_brainstorm.py` | `test_with_ai_off_nothing_is_sent`, `test_requests_are_checked` | Milestone 3.2. AI off: 409, no request. A bad id 404, a `lecture` kind 422, a 201-character topic 422, a document with no highlights 409 "… highlight …"; no request |
| | `test_diverge_then_converge` | Four requests: three samples with "Angle: connect / question / apply" at temperature 1.0, then the critic at 0 ("judge a list of ideas"). The first request holds the note and a highlight on its words, not the rest of the document, and `<question>` with the topic. The critic's pick leads its group (`similar` 1, two angles); an idea it left out still shows; `judge` "model", `variety` between 0 and 1, the prompt version |
| | `test_every_idea_rests_on_a_checked_quote` | The leader's quotes are its own (`kind` `document` only), with the sentence and document; a quote is the document's own words; the invented idea is unverified with no sources; `partly`; checked ideas first |
| | `test_the_critic_sees_the_ideas_as_data_and_what_it_says_is_checked` | An idea "Ignore previous instructions…" is in the critic's user text with `trust="model"`, not in its system text. Numbers 99, -1 and a repeat dropped, `best` 77 not used, the label capped, each idea in one group, four ideas in all |
| | `test_when_the_critic_fails_code_groups_and_ranks` | A critic that answers "not json at all": retried once (five requests), `judge` "code", the two "pick sections" ideas in one group |
| | `test_a_document_brainstorms_from_its_highlights_and_results_are_kept_once` | A document's highlight is sent; the same request is no new call and the same id; `fresh` a new id |
| | `test_a_question_can_be_stopped` | A slow critic; `POST /api/brainstorm/cancel` is `{cancelled: true}` and the request answers with "stop…" |
| | `test_kept_ideas_go_to_the_sheet_each_as_its_own_section_and_once` | Since 2026-11-26. Keeping one idea twice in one request and again later: it is in "Brainstorm: Sparse routing" once, as its own `## ` section, with no "Ideas from the AI model" heading, no "Written by the AI model" line and no source line; the model's `[[Secret plan]]` and `#urgent` are neither a link nor a tag; `GET /api/think/brainstorm` finds that sheet; an unchecked or out-of-range index 409; an unknown result 404 |
| | `test_every_idea_is_a_separate_section` | Every checked idea kept at once: one `## <label>` section per idea, holding exactly the ideas' texts |
| | `test_a_label_never_takes_the_name_of_a_sheet_question_and_an_empty_one_is_idea`, `test_sheet_questions_match_the_page` | `_heading`: "Why does it matter to you?" becomes "Why does it matter to you? (idea)", an empty label "Idea", `[[Secret]] #now` plain. `SHEET_QUESTIONS` are the questions written in `web/src/views/think.ts` |
| | `test_undo_takes_the_ideas_out_while_the_sheet_is_as_they_left_it` | Two keeps; Undo of the second gives the sheet as it was after the first, and `kept` holds only the first; the undone idea can be kept again; after the reader edits the sheet, Undo is 409 and the edit stays |
| | `test_a_group_never_lends_its_quotes_to_an_unchecked_idea` | Found by the review of 3.2. The critic's pick is the invented idea: it stays unverified with no sources, and the member with its own checked quote leads |
| | `test_a_quote_of_your_note_is_kept_in_your_own_words_on_one_line` | Found by the review. A quote across two lines of a note, in other case: shown as the note's words on one line, and kept so in the sheet |
| | `test_a_critic_that_fails_in_any_way_falls_back_to_code` | Found by the review. A critic that answers 503: 200, `judge` "code", ideas shown |
| | `test_a_boolean_is_not_an_idea_number` | Found by the review. `ideas: [true, 0]`, `best: true`: one member, `similar` 0 |
| | `test_two_keeps_at_once_both_land` | Found by the review. Two keeps of different ideas at the same moment (one slowed down): both ideas are in the sheet |
| | `test_in_cloud_mode_a_file_of_secrets_is_left_out_not_fatal` | Found by the review. A highlight in `secrets.yaml` and a note in cloud mode: 200, `left_out` 1, the file name never sent |
| | `test_a_document_brainstorm_has_its_own_sheet` | Found by the review. With a note named like the document: the sheet title is "Brainstorm: Attention Is a Test (document)" |
| | `test_variety_is_lower_when_ideas_repeat` | `_variety`: 0 for two equal ideas, 1 for two with no word in common |
| `test_ai_organize.py` | `test_with_ai_off_nothing_is_sent` | Milestone 3.3, the suggestion. AI off: 409, no request; a missing document 404 |
| | `test_what_the_model_reads` | The title and section titles, the opening and a highlight, not a later sentence (`LongBench`); the tags the reader uses (`transformers`, `baking`) as `trust="yours"`; "1. Routing Layers"; `SYSTEM_RULE` |
| | `test_tags_reuse_yours_first_and_every_tag_is_checked` | Nine tags from the model: the reader's two first, two new kept, the rest dropped (`dropped` 4); the checked quote is the document's sentence; an invented one unverified and without `quote`; `reuse` 0.5; the prompt version |
| | `test_a_tag_already_on_the_document_is_not_suggested` | With `transformers` on the document, no tag is suggested |
| | `test_related_documents_come_only_from_the_list_code_made` | 0, 99, `true` and a repeat dropped; Routing Layers kept, with image syntax gone from its reason and the address in `links`; Bread Basics never named |
| | `test_kept_once_and_fresh_asks_again` | One request for two asks; `fresh` a new id |
| | `test_related_numbers_must_be_real_integers` | Found by the review of 3.3. `true`, `1.0` and `"1"`: no related document |
| | `test_reuse_is_measured_on_what_the_model_wrote` | Found by the review. Six tags written, two the reader uses (one already on the document): `model_tags` 6, `model_reuse` 0.333, `reuse` 0.333 of the three shown |
| | `test_in_cloud_mode_a_file_of_secrets_is_not_named_among_the_candidates` | Found by the review. `secrets.yaml` would be a candidate: its name is never sent, Routing Layers is |
| `test_eval.py` | `test_quotes_are_counted_from_the_stored_result`, `test_found_and_not_found_are_judged_against_what_was_expected`, `test_steps_are_the_library_loop_s_steps`, `test_a_plan_is_within_limits_only_if_no_day_is_over_none_is_late_and_nothing_is_lost`, `test_call_stats_come_from_the_ai_log_rows` | Milestone 4.1, the scoring functions on results made by hand |
| | `test_the_goals_follow_the_plan_s_done_when_rows`, `test_the_table_has_one_row_per_feature_and_prints_anywhere` | Pass / FAIL / `-` / `n/a`; the table is ASCII and its lines line up |
| | `test_tidy_counts_the_proposals_that_add_no_word_you_did_not_write`, `test_plan_chat_counts_the_drafts_that_fit_their_days_free_time` | Phase 5: `tidy_check` and `chat_check` on results made by hand (a draft for any day, nothing flagged, fits) |
| | `test_the_note_chat_counts_requests_that_got_a_usable_proposal` | Milestone 5.4: `notechat_check` on a rewrite (2 new words, 1 restored), a story to add and a reply only; two usable proposals pass ("proposals 2/2, rewrite +2, 1 restored", quotes `-`), a reply only fails |
| | `test_every_feature_has_cases_and_ask_and_library_have_both_kinds`, `test_tidy_and_plan_chat_have_your_own_writing_to_work_on`, `test_the_harness_runs_every_feature_the_app_calls_a_model_for` | The sample set; `RUNNERS` equals `FEATURES` of `test_ai_citations.py` |
| | `test_the_stand_in_answers_test_connection_and_says_not_found_when_the_words_are_missing`, `test_the_stand_in_knows_every_feature_s_prompt` | The stand-in model |
| | `test_the_user_s_model_settings_are_read_without_changing_anything`, `test_a_folder_without_readhold_data_is_not_created`, `test_the_stand_in_run_never_touches_the_real_folder`, `test_the_real_settings_path_leaves_the_real_folder_alone`, `test_settings_are_read_while_the_app_is_open`, `test_keep_leaves_the_throwaway_folder_for_a_look` | The real folder is the same byte for byte (with the app closed; with it open, all but `-shm`); your model and your profile change are used; `READHOLD_HOME` is put back |
| | `test_with_ai_off_it_says_so_and_stops`, `test_a_cloud_model_needs_a_yes_before_anything_is_sent`, `test_a_model_that_does_not_answer_is_reported_without_scores`, `test_no_model_named_is_reported`, `test_a_crash_while_setting_up_is_a_sentence_not_a_traceback`, `test_the_day_s_budget_goes_on_from_what_the_app_used_today` | Stopping cleanly, and the budget |
| | `test_a_schema_failure_is_counted_in_the_log_even_when_the_retry_works` | `checks["schema_failures"]` |
| | `test_the_stand_in_run_scores_all_twelve_features`, `test_the_stand_in_run_checks_tidy_for_invented_words`, `test_the_stand_in_run_checks_that_plan_chat_drafts_fit`, `test_every_call_of_the_stand_in_run_went_through_the_guards`, `test_not_found_cases_really_reach_the_model`, `test_the_command_prints_one_table_and_can_write_json`, `test_only_runs_the_features_named` | The whole run on the stand-in: twelve rows, every call carries `guard.ask`'s `fenced` check, all fourteen tasks are called (with `notechat` since 5.4); Tidy marks the one word it adds and leaves the clear task alone, the chat's drafts fit and the task you have is counted as `already`. The first test's name still says eleven; it checks every row of `FEATURES`, twelve now |
| | `test_the_stand_in_run_checks_the_note_chat` | The note chat on the stand-in: goal pass, 2 proposals, 1 rewrite, nothing restored; "format the note" is a `replace` that keeps `[[Soil sensor log]]`, "a story idea from it" an `add` |
| | `test_a_library_loop_that_never_answered_is_not_a_right_not_found`, `test_an_answer_without_a_verified_quote_fails_every_quote_verifies`, `test_a_question_over_two_texts_must_cite_both` | Found by the review of 4.1 |
| | `test_the_harness_imports_no_network_client_and_not_the_adapters` | `readhold/eval/` imports neither (and `test_no_network.py` scans it with the rest of `readhold/`) |
| `test_ai_why.py` | `test_an_answer_traces_to_its_prompt_model_sources_and_checks` | Milestone 4.2. An Ask answer: feature, status `verified`, `checked` 1 of 1, one call (task, outcome, prompt version, provider, tokens, attempts, `fenced`), the prompt word for word, the Method section named with document title and trust, and the passage's text nowhere in the sources |
| | `test_a_feature_with_several_calls_lists_them_all`, `test_a_digest_shows_its_part_calls_too` | A brainstorm: three `brainstorm` calls then `brainstorm_critic`, both prompts, the critic's source of kind `model`. A digest: `digest_map` calls, `digest` last |
| | `test_your_notes_and_other_sources_are_named` | Ask my library: a note named by its title, trust `yours` |
| | `test_when_the_log_is_gone_the_result_says_so`, `test_unknown_cleared_or_removed_results_are_not_found` | No log rows: `calls` empty, `log_gone`, the result's own model still shown. 404 for an unknown id, a malformed id, a removed document's result and a cleared one |
| | `test_works_with_ai_switched_off_afterwards`, `test_no_model_call_is_made_to_explain` | 200 with AI off; no request reaches the transport |
| | `test_a_call_logged_before_sources_were_kept_says_so` | A row without `sources`: `sources_recorded` false, `sources` empty, the other checks kept |
| | `test_a_digest_lists_its_own_part_calls_not_older_ones`, `test_a_call_that_failed_is_shown_with_its_outcome`, `test_every_kind_of_your_own_source_is_named`, `test_a_removed_source_has_no_link`, `test_a_long_list_of_sources_says_how_many_more`, `test_the_preview_of_what_was_sent_is_not_returned` | Found by the review of 4.2: a planted older `digest_map` row changes nothing; a critic that answers badly is the last call, outcome `invalid`; the `attempt:` source of Explain is named; a note removed behind the route's back is `gone` with no `note_id`; `pack` with 70 sources lists 60 and `sources_more` 10; no `input_preview` |
| `test_ai_citations.py` | `test_the_checker_keeps_a_real_quote_and_catches_every_fake` | Milestone 2.1. `verify_citations`: `REAL` is `verified`; every fake of `FAKES` but `not_sent` and `hidden_section` is caught under `REAL`'s anchor; the other document's sentence is kept under its own anchor and caught under this one |
| | `test_a_malformed_or_missing_anchor_is_caught` | 18 cases (parametrised): each anchor is removed (`removed` 1) and the sentences are still there |
| | `test_a_quote_from_a_removed_document_section_or_paragraph_is_caught` | A soft-deleted section, then a soft-deleted paragraph, then the document deleted through its route: the citation is kept before and fails each time (each removal is undone before the next) |
| | `test_numbers_keep_their_sign_their_percent_and_their_decimals` | `-3` vs `3`, `41%` vs `41`, `71.2` vs `712` and `71 2` caught; other case, double spaces and curly quotation marks still match |
| | `test_a_flood_of_citations_is_cut_off` | 500 citations: `MAX_CITATIONS` kept, the rest `removed`, status `partly` |
| | `test_each_feature_shows_a_real_quote` | Per feature (resume, explain, digest, ask, library, notes, plan, brainstorm, organize), through its routes and the fake server: `REAL` is shown verified and the status is `verified`. The control that the next test is not vacuous. The notes helper highlights `REAL`'s sentence and asks for notes from the highlights, so only that sentence is sent |
| | `test_each_feature_catches_every_fake_citation` | Every feature with every fake (99 cases, one skipped: the digest with `not_sent`): no quote shown, status `unverified` |
| | `test_every_feature_that_calls_a_model_is_checked_here` | The modules under `readhold/` that call a model (`guard.ask` under any name, or `port.complete(` directly, found with `ast`; `DIRECT_CALLERS` left out) are exactly the keys of `FEATURES` |
| | `test_a_quote_must_start_and_end_on_whole_words_and_keep_its_numbers` | Found by a review of 2.1. 9 fakes against `EDGES` (cut out of `unimportant`, `isn't`, `15`, `-30`, `non-significant`; `1.000` for `1,000`; `10^3` for `10⁻³`; `e.g. 3` for `e.g.-3`): `verify_citations` keeps none and `quote_in` finds none |
| | `test_real_quotes_with_words_and_numbers_still_pass` | Found by a review of 2.1. 10 real quotes of `EDGES` are kept, among them a typographic minus, `1000` for `1,000`, `10^-3` for `10⁻³` and `e.g. -3` |
| | `test_keywords_and_terms_are_whole_words_and_never_bare_number_words` | Found by a review of 2.1. `_clean_keywords` keeps `points` and `compute` and drops `%`, `percent`, `minus` and `1.000`; `word_in` finds `points` but not `port` in "The points are fine." |
| | `test_the_registry_finds_every_way_of_calling_a_model` | Found by a review of 2.1. `_model_callers` on the real code gives the keys of `FEATURES`; a fake module that calls `ask` under an alias, `g.ask` and `port.complete` is found |
| | `test_the_features_without_quotes_show_none` | Since Phase 5. `NO_QUOTES` holds `tidy`, `chat` and (since 5.4) `notechat`, each with its reason; `test_every_feature_that_calls_a_model_is_checked_here` accepts `FEATURES` plus `NO_QUOTES`. A model that writes a `quote` of `REAL` in a Tidy task, a Plan chat draft and a note chat answer: no result holds `quote` or `verified` |
| `test_tidy.py` | `test_a_good_task_has_no_hints`, `test_hints_say_what_a_task_lacks` | Milestone 5.2 without a model (9 tests; the day is fixed, Thursday 2026-11-26). "Read chapter 3 of the networks book" with a day: no hint, no fix. "networks book chapter 3": `verb` and `day`; three joined tasks: `several`; a long one: `long`; a repeating task needs no day |
| | `test_a_time_or_a_day_in_the_text_moves_into_the_task` | "call the bank (30 min) tomorrow" → "Call the bank", 30, Friday; "1.5h on friday" → 90; "next week monday"; a set day kept; 900 minutes left alone |
| | `test_text_in_another_script_gets_no_verb_hint`, `test_notes_and_routines_get_spacing_and_list_fixes` | Arabic: no `verb` hint. A note's heading spaces, empty lines and `*`/`•` marks; a tidy note is `None`; routine steps get a capital and "10 min" |
| | `test_the_tasks_route_lists_open_tasks_with_their_hints`, `test_the_note_and_routine_routes_propose_without_changing` | `GET /api/tidy/tasks` leaves out a done task; the note and routine routes return the fix and the note is unchanged; a missing note is 404 |
| | `test_a_note_keeps_its_tags_code_and_rules`, `test_day_and_time_words_inside_other_phrases_are_left_alone` | Found by the review of 5.2: `#private` and `#idea` lines, a fenced block with empty lines, `* * *`, indented code and a missing final newline give `None`; seven phrases give no fix; "(friday)" leaves no brackets; "Today: review notes"; another day set keeps the word; `iPhone`, a web address and `eBay` are not capitalised |
| `test_ai_tidy.py` | `test_with_ai_off_nothing_is_sent`, `test_tasks_are_rewritten_split_and_checked` | Milestone 5.2 with the fake model server (14 tests). AI off: 409, no request. Two tasks, five answers: one proposal per real task (`True`, 7 and a second answer for task 2 ignored), the split cut to 4, 9999 minutes and a day 400 days ahead not used, `new_words` holds `chapter`, `read` and `car`; the user text holds both tasks and `trust="yours"`; the system text says "never add" |
| | `test_a_note_rewrite_marks_new_words_and_keeps_model_markup_plain`, `test_a_routine_rewrite_is_checked` | `[[Lab]]` stays a link, `[[Secret plan]]` and `#urgent` are plain, their words are in `new_words`, the note is unchanged; a routine's 999 minutes become 0 |
| | `test_requests_are_checked_and_a_long_note_is_refused`, `test_kept_once_and_traceable` | 404, 422 for `essay`, a 20,000-character note 409 "too long", no open task 409; the same request twice is one call, and `GET /api/ai/why/{id}` names `tidy` |
| | `test_a_long_note_rewrite_is_not_cut_and_a_short_one_says_what_went_missing`, `test_a_rewrite_keeps_your_tags_links_and_properties`, `test_your_own_markdown_links_stay_as_you_wrote_them` | Found by the review of 5.2 and 5.3: a 6,500-character rewrite stays over 6,000; a one-line rewrite has `shorter` and `switches` missing; `#private`, `#idea`, `[[Lab]]` and two properties are put back and listed in `restored`; your `[the docs](…)` and `[1]: …` stay, the model's `![x](…)` goes |
| | `test_new_words_shows_numbers_names_and_negations`, `test_a_long_model_step_still_fits_and_a_routine_keeps_its_ticks`, `test_an_old_tidy_is_not_offered_with_its_old_days_and_withheld_tasks_get_no_answer` | `dont`, `1200`, `al`, `two`, `not`, `3`, `may` listed; a 500-character step capped at 200; the apply keeps the ticked step's id and tick, a stale `expect` is 409, the Undo works; five days later the same tasks ask the model again |
| | `test_a_tidied_note_has_no_label_line`, `test_the_model_is_told_never_to_translate` | Asked for on 2026-11-26: a note's rewrite starts with the model's own heading, with no "Tidied by" line; for an Arabic note the system text says "never translate" and "same language" (`tidy_v2`) |
| `test_ai_chat.py` | `test_with_ai_off_nothing_is_sent`, `test_the_model_reads_your_days_tasks_and_deadlines_and_what_you_wrote` | Milestone 5.3 with the fake model server (9 tests). AI off: 409, no request. The user text: the question in `<question>`, the open task, the document's title (with a deadline), tomorrow's date and "free", `trust="model"` and the earlier message |
| | `test_every_draft_is_checked_and_nothing_is_added_by_asking`, `test_at_most_twelve_drafts` | No task added; the task you have is left out (`already` 1); "tomorrow" is tomorrow; a past day and a day 200 days ahead are dropped with a flag, 9999 minutes become 25; 15 + 60 + 90 over 120 minutes tomorrow: `fits` false and a "free" flag; 30 drafts: 12 and `dropped` 18 |
| | `test_one_click_adds_the_drafts_you_keep_and_undo_takes_them_back`, `test_what_you_write_is_checked` | Two drafts added with edited minutes and text, both noting a model drafted them; a second Add adds 0; index 99 is 409; Undo removes 2. 1,001 characters, 13 messages, the model last and 5 minutes a day are refused |
| | `test_each_add_is_its_own_batch_and_undo_lets_you_add_again`, `test_a_day_that_does_not_exist_is_refused_and_chat_batches_are_not_a_reading_plan`, `test_a_private_document_is_not_named_through_a_task_or_an_earlier_reply` | Found by the review of 5.2 and 5.3: two clicks, two batches; Undo of the second leaves the first, and the draft can be added again; November 31 is 409; `GET /api/reading-plan` has no `last_batch` after a chat add; in cloud mode a task linked to a `#private` document and an earlier model reply that quotes it are not in what is sent |
| `test_ai_notechat.py` | `test_with_ai_off_nothing_is_sent`, `test_a_rewrite_is_proposed_checked_and_not_applied` | Milestone 5.4 with the fake model server (10 tests; `Model` and `_model` from `test_ai_tidy.py`). AI off: 409, no request. A rewrite: `replace`, `[[Lab]]` kept and `#work` put back (`restored`), the model's `[[Secret plan]]` and `#urgent` plain, `funding`, `secret`, `plan`, `urgent` in `new_words`, `original` is the note, no "AI model" line, and the note is unchanged |
| | `test_new_writing_is_proposed_as_text_to_add`, `test_an_empty_note_can_be_written_into` | A story idea is `add`, with no `new_words`, and the note is unchanged; an empty note can be asked about (200, `add`) |
| | `test_what_the_model_is_given` | The note as `trust="yours"`, an earlier model turn as `trust="model"`, the message in `<question>`; the system text says "never translate" and "you cannot change the note yourself" |
| | `test_a_reply_without_a_usable_proposal_is_just_a_reply`, `test_the_same_question_on_the_same_note_is_asked_once` | An unknown action ("delete everything") and a blank rewrite are `none`; the same question twice is one call, and `GET /api/ai/why/{id}` names `notechat` |
| | `test_bad_requests` | An unknown note 404; the model speaking last 422; a 15,000-character note 409 "too long" |
| | `test_a_private_note_never_leaves_this_computer`, `test_your_message_is_checked_for_private_text_too` | In cloud mode a `#private` note, and a message that copies a sentence of a `private` document, are 409 "private" with no request |
| `test_ai_privacy.py` | `test_a_private_document_is_never_sent_to_a_cloud_model` | Milestone 4.4 (20 tests; a fake Anthropic-shaped server, `_cloud`). A document tagged `private` with a highlight: Ask, Explain, Study notes, Organize, Brainstorm and the digest all answer 409 with "private", and no request is made |
| | `test_a_local_model_still_reads_a_private_document` | The same document with a local model: Ask answers 200 |
| | `test_a_question_across_the_library_leaves_private_items_out`, `test_the_library_neither_counts_nor_names_private_matches` | Ask my library in cloud mode: a private document and a note with `#private` are not in what was sent, a public match is, and `private_left_out` is at least 2. Only a private match: 200, `not_found`, `private_left_out` 1, no request |
| | `test_brainstorming_a_private_note_in_cloud_mode_explains_why_not`, `test_brainstorm_on_a_private_document_is_refused_even_with_near_notes` | 409 with "private", nothing sent, also when a public note is near the private document |
| | `test_a_private_document_is_not_named_to_a_cloud_model`, `test_organize_does_not_name_the_tags_of_private_items` | Organize of a public document and a reading plan with a private one: 200, the private title never sent. Organize's tag list holds `transformers` but not `custody-case`, `hiv-test` or `private` |
| | `test_copies_of_a_private_document_in_your_notes_stay_on_this_computer` | A quote of a private document in the day's note and a note titled after it are not sent; a note in your own words is; `private_left_out` at least 2 |
| | `test_an_idea_tagged_private_is_private_and_cloud_can_be_opt_in` | `is_private` of an idea with `#private`. With `ai_cloud_only_tagged`: an untagged document is refused with "#cloud", nothing sent; one tagged `cloud` is asked |
| | `test_with_the_preview_on_nothing_is_sent_until_you_approve_that_text` | With `ai_preview`: 428 and no request; the preview's provider, question, source and `SYSTEM_RULE`; the same request with the token: 200, one request whose user text is the preview's; the token again: 428; a token for one question does not approve another; a made-up token: 428 |
| | `test_one_approval_covers_the_other_calls_of_that_request` | A brainstorm: one 428, then after approval four requests (three samples and the critic); the note says "more calls" |
| | `test_the_preview_asks_again_before_a_later_call_sends_more_of_your_items` | Ask my library whose model searches once: the first preview holds no bread text; after approval, step 2 would send the bread document, so a second 428 shows it, and only step 1 was sent; the second token gives 200 |
| | `test_a_digest_is_previewed_before_it_starts`, `test_a_digest_previews_the_call_it_will_really_make` | 428 before a job exists; after approval the digest is kept and at least two requests went. With every part kept, the next preview is the combining call (`Summary: `), not the document |
| | `test_no_preview_for_a_local_model_or_when_it_is_off` | Cloud with the preview off: one request, 200. A local model with the preview on: 200. `ai_preview: "yes"`: 422 |
| | `test_the_ai_mode_is_read_once_per_call` | `pack` is wrapped to switch `ai_mode` to cloud right after packing for local: 409 "changed", no request to the cloud |
| | `test_the_ai_log_is_kept_as_long_as_you_choose` | Rows of 2000 and of three days ago: `ai_log_days` 7 keeps the second, 1 deletes it at once; 365 is a 422 |
| | `test_ai_results_are_in_export_everything_and_there_is_no_separate_ai_export` | Since 2026-11-26. `POST /api/ai/export` answers 404 or 405; `POST /api/export/all` holds the Ask result in `ai_results`, no `ai_log`, and not the saved key |
| | `test_the_ai_log_is_kept_for_the_days_you_choose` | `keep_days` in `GET /api/ai/log` is 30, then 7 after the setting |
| `test_redteam.py` | `test_row_1_…` to `test_row_10_…`, `test_the_suite_matches_the_plan`, `test_ci_runs_this_suite_first_on_every_change` | Milestone 4.3 (12 tests). See *The red-team suite* in section 7b |
| `test_security.py` | `test_a_model_server_on_another_computer_gets_every_rule_text_leaving_the_computer_gets` | Milestone 4.5. A "local" endpoint `http://203.0.113.7:11434`: a private document 409 with nothing sent; a document with a fake key answers 200, with the key not sent and `[redacted]` in its place; with `ai_preview` on, 428 |
| | `test_a_model_server_on_this_computer_is_still_trusted`, `test_on_this_computer_means_exactly_that` | `http://localhost:11434` reads a private document (200). `is_local` is true for `localhost`, `127.0.0.1:8080`, `127.5.5.5`, `[::1]`, and false (with an endpoint warning) for `127.evil.example`, `127.0.0.1.nip.io`, `127.attacker.test`, `localhost.evil.example`, `10.0.0.2` |
| | the seven others | The server, the importers and the export of chapter 1 |
| `test_open_findings.py` | `test_a_text_of_spaces_is_empty` | `bodies.Body` on tasks, routines, routine steps and notes; a field left out of a patch passes |
| | `test_a_suggestion_that_applies_again_is_offered_again` | Stale, then the same row offered again; a rejected one stays away |
| | `test_think_refuses_a_day_far_from_today` | `day_ok`: 30 days away is a 422, one day away passes |
| | `test_raw_updates_name_the_device` | `finish_run` sets `device_id` on the task |

`tests/test_ai.py` (the port, the adapters, keys, the log, profiles) is summarised in `docs/CODE_GUIDE.md`, section 9.

Not covered by a test in `test_ai_privacy.py`: the Recap and the reading plan's suggestion on a private document alone; a token that expired (10 minutes) or the `MAX_GRANTS` limit; an endpoint changed from local to remote while a call is prepared; `copies_private` on a whole short sentence (4 to 7 words) and on a title under 8 characters; the Settings page, the preview dialog and the Organize checkbox (nothing tests the front end).

Not covered by a test in `test_ai_resume.py`: cloud mode (redaction and a refused file of secrets through the brief route), the 409 for `setup`, `no_key`, `budget` and `cancelled`, a kept recap with AI off (the explain test covers the same order of checks for explanations only), a document whose position matches no sentence, a code file, the ord-range fallback of `context`, the caps `MAX_SECTIONS` (and "the sections read last"), `MAX_HIGHLIGHTS` and `AHEAD`, `Source.cut` and `trimmed` in the log row, a section removed by a merge-up, a damaged `payload`, a failed "Ask again" keeping the old row, and anything in `web/src/views/resume.ts` (the calendar days of `when()`, `resumeSlot`).

Not covered by a test in `test_ai_explain.py`: an accepted selection of more than one sentence, a selection or a code block over `MAX_SELECTED` characters, a selection in the middle of a long paragraph (text added on both sides), `end_sentence` before `sentence`, a take that holds order-like text or a closing tag, the 504 and the 409 for a cancelled call, `once` on the explain route and its tidy-up past 500 names, Clear AI history for explain results and for a saved note, a document deleted through its route (explain results, a saved note, and saving a note afterwards), the 5,000-character cut of a note, and anything in `web/src/views/explain.ts`, `selectionToolbar` or the two note labels.

Not covered by a test in `test_ai_digest.py`: a section hidden or renamed while a job runs; Stop during a map call before the port has registered it; an empty document (the 409 test uses one of only References); a section exactly at the target; a structure edit or a new prompt version making the kept digest stale (and `_key_cache` seeing it); `TooLong` from the default limits; the 404 of the start route; a server restart (`_jobs` empty); and anything in `web/src/views/digest.ts` (polling, Stop, Go on, closing the dialog).

Not covered by a test in `test_ai_citations.py`: a quote across two sentences of one section (passes, on purpose); LaTeX math (`\(0.5\)`), ranges such as `3-4` and `3 - 4`, `x-1` against `x − 1`, `1 000` with a space, and `top k` against `top-k`; a section merged up or split after a result was kept; cloud mode; and a model call through a longer path (`readhold.ai.guard.ask(…)`) or `getattr`, which the registry does not see.

Not covered by a test in `test_ai_library.py`: a `read` of a note (`note:<id>` of a live note); a `read` whose `around` sentence was moved to another section by a merge-up or split; more than `MAX_SOURCES` sources, and a quote from a source dropped by it; a call over the budget that `guard.pack` cuts; notes beyond `NOTE_SCAN`; the snippet itself; a key in a note in cloud mode; the 502, the 504 and the off switch during a question; two questions at the same moment (`results.once`); a kept answer made in local mode asked again in cloud mode; and anything in `web/src/views/libraryask.ts`.

Not covered by a test in `test_ai_brainstorm.py`: a quote of an idea; a sheet over `pages.MAX_BODY`; two documents with one title (the id suffix); the 504 and the 502; a critic answer of `{"groups": []}` with one candidate (no critic call); `fresh` after a keep (the new result starts with no `kept`); and anything in `web/src/views/aibrainstorm.ts` or the hooks in `think.ts`.

Not covered by a test in `test_organize.py` or `test_ai_organize.py`: two `PUT …/tags` at the same moment (the check-then-update is not atomic); a tag with a combining mark (refused); highlights in a hidden section (not sent, by the SQL); the known-tags cut at 1,500 characters; the 504 and the 502; and anything in `web/src/views/organize.ts` (the save chain, Undo) or the chips in `library.ts`.

Not covered by a test in `test_ai_why.py`: the `session`, `why`, `tags`, `docs` and `hlnote` names (only `attempt` and the critic's `ideas` are checked); a removed sentence, paragraph or section (only a removed note is tested; the SQL checks all four); the time fallback of an older digest without `log_ids`; more than `MAX_CALLS` calls; a prompt version whose file is gone; and anything in `web/src/views/why.ts`.

Not covered by a test in `test_ai_notes.py`: cloud mode (redaction, a file of secrets); a highlight that spans two sections; a quote longer than `MAX_RUN` sentences (the model's copy is then kept); a note named like the document (no link); a note over `pages.MAX_BODY`; the 504 and the 502; `keep_as: "notes"`; the three findings listed under *Study notes* above; and anything in `web/src/views/studynotes.ts`.

Not covered by a test that I could find by name: the JWT pattern of `redact.scrub_all`, `safe_output` on reference-style links, a `Blocked` source in `ask`, `ask` in cloud mode, `reindex` after a split, the ord-range fallback of `last_session`, the monthly anchor across several months in one chain, capture into a note without a `## Notes` heading, and undo of `file_idea` restoring the idea. Check the test bodies before relying on this list.

Not covered by a test in `test_tidy.py`, `test_ai_tidy.py`, `test_ai_chat.py` or `test_ai_notechat.py`: a private note in cloud mode (Tidy marks it `main`; the refusal is the guard's, tested elsewhere); a split whose second `POST /api/todos` fails (the page's "Undo what was done"); the routine fix on quoted text (it is not skipped); a Tidy or Plan chat answer that is not JSON (the port's retry, tested in `test_ai.py`); a Plan chat draft day edited to more than 60 days ahead (allowed up to a year by `add`); a duplicate of an open task past the first 40; for the note chat, 13 messages (refused by `NoteChatIn`, not tested), an earlier model reply that copies private text in cloud mode (the same code as Plan chat's, tested there), and **Use this** or **Add to the note** on a note that changed since (the page's check); the front end of these features.
