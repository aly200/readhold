# Chapter 2 — Back end: goals, growth, lectures, journal

This chapter covers four feature modules and the four migrations behind them.

| Module | Name in the app | Migration |
|---|---|---|
| `readhold/compass.py` | Plan → Today, and Study → Goals | `0003_compass.sql` |
| `readhold/growth.py` | A goal's topic map, teach-back, the daily log, tiny habits, mixed practice | `0004_growth.sql`, `0005_reflect.sql` |
| `readhold/lectures.py` | Study → Lectures (slides, PowerPoint, sealed web pages, blank notebooks, pen ink) | `0006_lectures_journal.sql` |
| `readhold/journal.py` | Notes → Journal, and letters to future you | `0006_lectures_journal.sql` |

Naming: the interface says "goal" where the code says `quest`, "main goal" for the quest with `status='active'`, and "side goal" for a `side_quests` row. This chapter uses the code names.

## 0. Shared ground

**Wiring.** `create_app()` in `readhold/server.py` calls `compass.register(app, db)`, `growth.register(app, db)`, `lectures.register(app, db)`, `journal.register(app, db)`, then the modules of chapter 3, starting with `timer`. Each `register` defines its routes as closures over `db`. Nothing else is passed in.

**The `DB` helper** (`readhold/db.py`), as used here:

- `db.insert(table, row)` adds `id` (`uuid4().hex`, 32 hex characters), `device_id`, `created_at`, `updated_at` and returns the row as a dict. Columns left out take their SQL defaults, and the returned dict does not contain them. Several routes re-read the row for that reason.
- `db.update(table, id, fields)` also sets `updated_at` and `device_id`. With an empty `fields` it does nothing and returns 0.
- `db.soft_delete(table, id)` is `update(..., {"deleted": 1})`. Rows are never removed.
- `now()` is a UTC ISO string with milliseconds. Timestamps compare correctly as strings.
- `db.device` is this machine's device id. The few raw `UPDATE` statements in these modules (the two lecture updates in the notebook page routes) set `updated_at` and `device_id=db.device` by hand, so they leave the same sync columns as `db.update`.

**`bodies.Body`** (`readhold/bodies.py`) is the base class of every request model that has a required text. `min_length=1` alone accepts `"   "`. `Body` adds one validator: any string field that carries a `min_length` and holds only whitespace is refused with 422 (`"<field> is empty"`). An optional field that was left out is `None` and is not checked. The text is not trimmed there; the routes still strip what they store. In the model tables below, "1–300" on a model that extends `Body` therefore means "1–300 and not only spaces". Models without such a field stay on pydantic's `BaseModel`.

**Standard columns.** Every table below has `id TEXT PRIMARY KEY`, `device_id`, `created_at`, `updated_at`, `deleted`. The column tables in this chapter leave them out.

**`compass.need_row(db, table, row_id)`** returns the live row or raises 404. It builds SQL with the table name, so `table` must be a constant in the code, never user input. `growth`, `lectures` and `journal` all import it.

**Dates.** Two kinds are stored. Timestamps (`created_at`, `done_at`, `answered_at`, …) are UTC. Day keys (`day_logs.day`, `habit_checks.day`, `journal_entries.day`, `letters.open_on`) are local dates `YYYY-MM-DD`. To ask "what happened today" against UTC timestamps, `compass._day_start_utc()` and `journal._utc_bounds()` convert local midnight to UTC first.

**Settings.** `settings_dict()` in `server.py` merges `DEFAULT_SETTINGS` with rows of the `settings` table. Keys that belong to these features: `journal_blur`, `notebook_width`, `note_scale`. None of the four modules reads settings on the server; the front end does.

---

## 1. `compass.py` — Today and Goals

One main quest at a time. A quest names the questions it must answer. Steps move the questions forward. One step is the lead. Anything that pulls elsewhere is recorded as a side quest. Progress is counted in answers and finished steps, not time.

### 1.1 Tables (`0003_compass.sql`)

**`quests`**

| Column | Meaning |
|---|---|
| `title` | Required |
| `why` | Why it matters, default `''` |
| `done_looks_like` | The definition of done, written before starting |
| `deadline` | `YYYY-MM-DD` or NULL |
| `status` | `active`, `parked` or `done`; default `active` |
| `finished_at` | Set when status becomes `done` |

Index `idx_quests_status (status, updated_at)`.

**`quest_questions`**

| Column | Meaning |
|---|---|
| `quest_id` | References `quests(id)` |
| `ord` | Order within the quest |
| `text` | The question |
| `answer` | Default `''`; non-blank means answered |
| `answered_at` | Set when the answer first becomes non-empty; NULL again when emptied |

**`quest_steps`**

| Column | Meaning |
|---|---|
| `quest_id` | References `quests(id)` |
| `question_id` | The quest question this step moves (optional) |
| `document_id` | A reading step opens this document (optional) |
| `ord` | Order |
| `title` | The medium-energy version |
| `low` | The tiny version for low-energy days, default `''` |
| `high` | The full version for high-energy days, default `''` |
| `minutes` | Estimate, default 20 |
| `lead` | 1 on the step that makes the others easier |
| `done_at` | NULL while open |
| `output` | What finishing it produced |

**`side_quests`**

| Column | Meaning |
|---|---|
| `quest_id` | The main quest active when it was recorded; may be NULL |
| `text` | What pulled at you |
| `decision` | `parked`, `timeboxed` or `linked` |
| `minutes` | The time box, 0 when not used |
| `question_id`, `document_id` | Set when it turned out to serve a quest question |
| `resolved` | 0 while it still waits for you |

**`checkins`**: `energy` (`low`, `medium`, `high`) and `note`. Index on `created_at`.

The migration also adds `sessions.quest_id`, `sessions.step_id`, `sessions.output` and `documents.quest_question_id`. The session routes live in `server.py`; compass only reads these columns.

### 1.2 Status values and transitions

**Quest status.** `active` → `parked` → `active` and `active` → `done` are all done through `PATCH /api/quests/{id}`.

- Only one quest is active. `POST /api/quests` parks every active quest before inserting the new one as `active`. `PATCH` with `status: "active"` parks every *other* active quest first.
- Parking keeps everything. Nothing is deleted.
- `status: "done"` sets `finished_at = now()`.
- The rule is enforced in the two routes only. There is no database constraint. `active_quest()` tolerates a broken state by taking the most recently updated active row.

**Step lead.** At most one open lead per quest. `clear_lead(db, quest_id, keep=None)` unmarks the others. It goes through `db.update` row by row so `updated_at` and `device_id` change (covered by `test_moving_the_lead_updates_sync_columns`).

**Side-quest decisions.**

| `decision` | `resolved` on insert | Extra effect |
|---|---|---|
| `parked` | 0 | Stays in the list until `PATCH /api/side-quests/{id}` |
| `timeboxed` | 1 | None on the server |
| `linked` | 1 | If both `document_id` and `question_id` are given, sets `documents.quest_question_id` |

### 1.3 Constants and types

| Name | Value | Controls |
|---|---|---|
| `Energy` | `Literal["low", "medium", "high"]` | Check-in values |
| `EMPTY_SESSION_MS` | `3 * 60_000` | A finished session at least this long with no `output` and no `sentences_read` counts as empty |

### 1.4 Functions

| Signature | Behaviour |
|---|---|
| `_day_start_utc(day: date \| None = None) -> str` | Local midnight of `day` (default today) as a UTC ISO string |
| `_local(iso: str) -> datetime` | A stored timestamp in local time |
| `need_row(db, table, row_id) -> dict` | Live row or 404 |
| `clear_lead(db, quest_id, keep=None) -> None` | Unmark lead steps, except `keep` |
| `check_step_refs(db, quest_id, question_id, document_id) -> None` | 422 unless the question belongs to this quest and the document exists (both live) |
| `active_quest(db) -> dict \| None` | The `active` quest row, newest `updated_at` first |
| `quest_detail(db, quest_id) -> dict \| None` | The quest plus `questions`, `steps`, `documents`, `side_quests`, `progress`, `lead` |
| `lead_step(steps) -> dict \| None` | See 1.6 |
| `checkin_today(db) -> dict \| None` | The latest check-in since local midnight (by `created_at`, then `rowid`, so two taps in one second keep their order; since 5.1) |
| `energy_curve(db, days=30) -> dict` | See 1.6 |
| `output_today(db, quest_id) -> dict` | See 1.6 |
| `recent_empty_streak(db) -> int` | See 1.6 |
| `today(db) -> dict` | Everything the Today page needs, in one call |

`quest_detail` in detail:

- `questions`: ordered by `ord, created_at`.
- `steps`: joined with `documents` for `document_title`; open steps first (`done_at IS NOT NULL`), then `ord, created_at`.
- `documents`: `id, title, quest_question_id` for documents linked to one of this quest's questions.
- `side_quests`: unresolved ones of this quest, newest first.
- `progress`: `{"answered": n, "total": n}`; answered means `answer.strip()` is non-empty.
- `lead`: `lead_step(steps)`.

### 1.5 Request models

| Model | Fields |
|---|---|
| `QuestIn` | `title` 1–300; `why` ≤ 2000; `done_looks_like` ≤ 2000; `deadline` `YYYY-MM-DD` or null; `questions` list of at most 8 strings |
| `QuestPatch` | `title` 1–300; `why` ≤ 2000; `done_looks_like` ≤ 2000; `deadline` `YYYY-MM-DD` or `""` (clears it); `status` `active`/`done`/`parked` |
| `QuestionIn` | `text` 1–500 |
| `QuestionPatch` | `text` 1–500; `answer` ≤ 20000; `ord` int |
| `StepIn` | `title` 1–300; `question_id`; `document_id`; `low` ≤ 300; `high` ≤ 300; `minutes` 2–240 (default 20); `lead` bool |
| `StepPatch` | `title`, `question_id`, `document_id`, `low`, `high`, `minutes` (2–240), `lead`, `ord`, `done` bool, `output` ≤ 5000 |
| `CheckinIn` | `energy` (`Energy`); `note` ≤ 500 |
| `SideIn` | `text` 1–500; `decision` `parked`/`timeboxed`/`linked`; `minutes` 0–240; `question_id`; `document_id` |

All of these extend `Body` (section 0) except `CheckinIn`, so a `title` or `text` made only of spaces is a 422.

`QuestIn.questions` caps the number of items but not the length of each string.

### 1.6 Algorithms

**How Today picks the next step.** `today()` loads the active quest through `quest_detail`. The step to do is `detail["lead"]`, computed by `lead_step(steps)`:

1. Keep the steps with no `done_at`.
2. If one of them has `lead=1`, return it.
3. Otherwise return the first open step in list order (`ord`, then `created_at`).
4. With no open steps, return `None`.

So a finished lead never blocks the page: the next open step takes over without any write.

**How the step is sized by energy.** The server does not size anything. It returns the step with all three texts (`title`, `low`, `high`) and today's check-in. The front end chooses: `stepFor()` in `web/src/views/today.ts` shows `low` on a low day, `high` on a high day, and falls back to `title` when that text is empty. The same file shows the time as `max(5, round(minutes / 3))` on a low day and `minutes` otherwise. A change to sizing rules belongs there, not in `compass.py`.

**The energy check-in.** `POST /api/checkins` inserts a row every time. `checkin_today()` returns the newest one since local midnight, so the last tap of the day wins and earlier taps stay as history. Since milestone 5.1 a check-in can be deleted (`DELETE /api/items/checkin/{id}`, chapter 1, section 7b): the one before it counts again.

**`energy_curve(db, days=30)`.**

1. Take sessions that started in the last `days` days.
2. For each with `focused_ms > 0`, add its focused minutes to the bucket of the local hour it *started* in (24 buckets).
3. If fewer than 3 such sessions exist, or the total is under 20 minutes, return `{"learning": True, "hours": [...], "peak": None}`.
4. Otherwise the peak is the start hour `h` that maximises `hours[h] + hours[(h + 1) % 24]`. Return `{"learning": False, "hours": [rounded to 0.1], "peak": [h, (h + 2) % 24]}`.

**`output_today(db, quest_id)`** returns:

```json
{"answers": 0, "steps": 0, "empty_sessions": 0,
 "focused_ms": 0, "on_quest_ms": 0, "on_quest_ratio": null}
```

- `answers`: rows in `questions` (paper questions) plus `quest_questions` with `answered_at` since local midnight.
- `steps`: `quest_steps` with `done_at` since local midnight (any quest).
- `empty_sessions`: today's sessions that have ended, ran at least `EMPTY_SESSION_MS`, and have neither `output` nor `sentences_read`.
- `on_quest_ratio`: `on_quest_ms / focused_ms` rounded to 2 places, or `None` when nothing was focused.

**`recent_empty_streak(db)`** walks the last 6 ended sessions, newest first, and counts empty ones until the first non-empty one.

**`today(db)`** returns:

```json
{"quest": {...} , "checkin": {...}, "energy": {...}, "output": {...},
 "empty_streak": 0, "parked": 0, "habits": [...], "letters_due": 0, "log_today": {...}}
```

`parked` counts unresolved parked side quests across all quests. `habits` and `log_today` come from `growth`. `letters_due` reads the `letters` table that `journal.py` owns.

### 1.7 Routes

| Method | Path | Body | Returns | Side effects |
|---|---|---|---|---|
| GET | `/api/today` | — | `today(db)` | None |
| GET | `/api/quest/active` | — | `quest_detail` of the active quest, or `null` | None |
| GET | `/api/quests` | — | Up to 50 quest rows, active first, then by `updated_at` | None |
| POST | `/api/quests` | `QuestIn` | `quest_detail` | Parks every active quest; inserts the quest and one `quest_questions` row per non-blank question |
| GET | `/api/quests/{quest_id}` | — | `quest_detail`, 404 if missing | None |
| PATCH | `/api/quests/{quest_id}` | `QuestPatch` | `quest_detail` | See 1.2 |
| DELETE | `/api/quests/{quest_id}` | — | `{"ok": true}` | Soft-deletes the quest row only |
| POST | `/api/quests/{quest_id}/questions` | `QuestionIn` | The new row | `ord` = current count |
| PATCH | `/api/quest-questions/{qq_id}` | `QuestionPatch` | The row | Strips `answer`; sets or clears `answered_at` |
| DELETE | `/api/quest-questions/{qq_id}` | — | `{"ok": true}` | Soft delete |
| POST | `/api/quests/{quest_id}/steps` | `StepIn` | The inserted row | `check_step_refs`; if `lead`, `clear_lead` first |
| PATCH | `/api/quest-steps/{step_id}` | `StepPatch` | The row | See below |
| DELETE | `/api/quest-steps/{step_id}` | — | `{"ok": true}` | Soft delete |
| POST | `/api/checkins` | `CheckinIn` | The new row | Insert |
| GET | `/api/side-quests` | — | Up to 100 unresolved rows, newest first | None |
| POST | `/api/side-quests` | `SideIn` | The new row | Attaches the active quest id; may link a document (1.2) |
| PATCH | `/api/side-quests/{side_id}` | — | `{"ok": true}` | Sets `resolved=1` |

`PATCH /api/quest-steps/{step_id}` details:

- It uses `model_dump(exclude_unset=True)`, so an explicit `null` is different from a missing key. `question_id: null` and `document_id: null` clear the link.
- An explicit `null` for `title`, `low`, `high`, `minutes`, `lead`, `ord` or `output` is refused with 422 (`"<key> can't be empty"`), because those columns are `NOT NULL`.
- `done: true` sets `done_at` only if the step was open, so the first finish time is kept. `done: false` clears it.
- `lead: true` calls `clear_lead(..., keep=step_id)`.

`PATCH /api/quest-questions/{qq_id}`: `answered_at` is set only on the change from empty to non-empty. Editing an existing answer keeps the first time.

### 1.8 Invariants and gotchas

- Deleting a quest does not touch its questions, steps, map or side quests. Readers must join through a live quest, as `growth.practice_items` does.
- `PATCH` with `status: "active"` on a `done` quest does not clear `finished_at`.
- `POST /api/side-quests` does not check that `question_id` or `document_id` exist. With a wrong `document_id` the link update changes no row and no error is raised.
- `QuestPatch` and `QuestionPatch` use `exclude_none`, so they cannot set a field to NULL. The deadline is cleared with `""`.
- `ord` for a new question or step is the count of live rows. After a delete, two rows can share an `ord`; ordering then falls back to `created_at`.

### 1.9 Tests

`tests/test_compass.py`: Today with no quest; one main quest at a time; questions, steps, lead and progress; the energy check-in; parking and linking side quests; time on the main quest and empty sessions; the energy curve's peak. `tests/test_reflect.py` adds: step validation (`test_step_rejects_empty_required_fields_and_foreign_refs`), sync columns when the lead moves, and `/api/quest/active`.

---

## 2. `growth.py` — topic map, teach-back, day log, habits, practice

Five small tools that hang off a quest or off the day. The module imports `active_quest`, `clear_lead` and `need_row` from `compass` *inside* `register()`, because `compass` imports `growth` at module level.

### 2.1 Tables (`0004_growth.sql`, `0005_reflect.sql`)

**`map_nodes`** — a concept a quest needs.

| Column | Meaning |
|---|---|
| `quest_id` | References `quests(id)` |
| `name` | The concept |
| `status` | `new`, `shaky` or `solid` ("can I explain it?"); default `new` |
| `note` | Free text |

**`map_edges`** — "`to_id` needs `from_id`". `from_id` is the prerequisite. Both reference `map_nodes(id)`; `quest_id` is stored too.

**`day_logs`**: `day` (local date), `quest_id` (the active quest when saved, may be NULL), `did`, `learned`, `next`. Index on `day`. There is no unique index; the route keeps one row per day.

**`habits`**: `title`, `anchor` (what it follows, "After my morning coffee"), `tiny` (the 2-minute version), `archived`.

**`habit_checks`**: `habit_id`, `day` (local date). A live row means "done that day". Index `(habit_id, day)`.

**`practice_attempts`** (`0005_reflect.sql`): `source_type` (`quest_question`, `question`, `term`), `source_id`, `result` (`got`, `partly`, `missed`). Index on `created_at`. Rows are only ever inserted.

`0005_reflect.sql` also adds `sessions.feel`, `documents.critique`, `documents.reproduce`, and the sync columns on `settings`. Those are used by `server.py` and `services.py`, not by this module, except that `journal.day_story` reads `sessions.feel`.

Node status has no enforced order. `PATCH /api/map-nodes/{id}` sets any of the three values at any time.

### 2.2 Functions

| Signature | Behaviour |
|---|---|
| `topic_map(db, quest_id) -> dict` | Nodes, edges, the "learn next" node, progress (2.4) |
| `_creates_cycle(db, quest_id, from_id, to_id) -> bool` | True when `from_id` already needs `to_id`, directly or not |
| `habit_state(db, habit, today=None, days=None) -> dict` | The habit row plus `done_today`, `streak`, `missed_yesterday`, `last14` (2.4) |
| `habits(db) -> list[dict]` | `habit_state` for every live, unarchived habit, with one query for all checks |
| `log_today(db) -> dict \| None` | Today's `day_logs` row (newest if several) |
| `practice_items(db, n=10) -> list[dict]` | A mixed practice set (2.4) |

`Status = Literal["new", "shaky", "solid"]`.

### 2.3 Request models

| Model | Fields |
|---|---|
| `NodeIn` | `name` 1–200; `needs` up to 20 prerequisite ids |
| `NodePatch` | `name` 1–200; `status` (`Status`); `note` ≤ 2000 |
| `EdgeIn` | `from_id`; `to_id` |
| `TeachIn` | `explanation` 1–20000; `gaps` up to 20 strings; `replace` bool, default false |
| `LogIn` | `did` ≤ 1000; `learned` ≤ 1000; `next` ≤ 300; `next_as_lead` bool, default true |
| `HabitIn` | `title` 1–200; `anchor` ≤ 200; `tiny` ≤ 200 |
| `HabitPatch` | `title` 1–200; `anchor` ≤ 200; `tiny` ≤ 200; `archived` bool |
| `AttemptIn` | `source_type` `quest_question`/`question`/`term`; `source_id` 1–64; `result` `got`/`partly`/`missed` |

All of these extend `Body` (section 0) except `EdgeIn` and `LogIn`.

### 2.4 Algorithms

**Topic map and "learn next" (`topic_map`).**

1. Load the quest's live nodes in creation order, and its live edges. Drop edges whose ends are not both live nodes.
2. Build `needs[node] = [prerequisite ids]`.
3. Compute `depth` per node: 0 with no prerequisites, otherwise 1 + the deepest prerequisite. The recursion carries a `seen` set and returns 0 on a repeat, so a loop in the data cannot hang it.
4. Mark each node `ready` when every prerequisite has `status == "solid"`. A node with no prerequisites is ready.
5. Candidates are nodes that are not `solid` and are `ready`.
6. Sort candidates by: `shaky` before `new` (you already started it), then smaller `depth` (foundations first), then `created_at`.
7. `next` is the first candidate, or `None`.

Returned shape:

```json
{"nodes": [{"...row": "", "depth": 0, "needs": ["id"], "ready": true}],
 "edges": [...], "next": {...}, "progress": {"solid": 1, "total": 4}}
```

**Loop refusal.** `POST .../map/edges` refuses `from_id == to_id` and any edge for which `_creates_cycle` is true, with 409. `_creates_cycle` walks prerequisites of `from_id` with a stack and reports whether it reaches `to_id`.

**Seeding the map.** `POST .../map/seed` collects the documents this quest reads (linked to one of its questions through `documents.quest_question_id`, or used by one of its steps). It takes up to 12 terms from those documents, grouped by lower-cased term, concepts first (`MAX(is_concept)`), then the most frequent. Each term not already a node name (case-insensitive) becomes a `new` node. No edges are made.

**Teach-back → gap steps.** `POST /api/quest-questions/{qq_id}/teachback`:

1. If the question has no answer yet (blank after stripping), or `replace` is true, the stripped explanation becomes the answer. `answered_at` is set to now only when it was empty: with `replace` the saved answer is overwritten, and the time it was first answered stays.
2. If it already has an answer and `replace` is false (the default), the saved answer stays and the explanation is not stored anywhere.
3. Each non-blank entry in `gaps` becomes a `quest_steps` row on the same quest, linked to this question, with `minutes=15` and:
   - `title`: `Fill the gap: <gap>`
   - `low`: `Find one sentence that explains <gap>`
   - `high`: `Explain <gap> aloud, then add it to your answer`
4. `ord` is the current step count plus the gap's index in the request. Gap steps are never marked lead.
5. Returns `{"question": row, "steps": [new rows]}`.

**Day log and tomorrow's lead.** `POST /api/logs`:

1. Strip the three texts. Attach the active quest's id (or NULL).
2. If today already has a log, update it; otherwise insert one with `day` = today. Saving again on the same day overwrites, including `quest_id`.
3. If there is an active quest, `next` is non-empty and `next_as_lead` is true:
   - call `clear_lead` on the quest;
   - if an open step with exactly that title exists, mark it lead;
   - otherwise insert a new step with that title, `lead=1`, `minutes=20`.
4. Returns `{"log": row, "step": row or null}`.

**Habit streak: "never miss twice" (`habit_state`).**

1. `done_today` is whether today's date is in the set of checked days.
2. Start walking back from today if it is done, otherwise from yesterday. An unchecked today is not a miss yet.
3. For each day back to the habit's creation date (local): a checked day adds 1 to `streak` and resets the miss counter; an unchecked day adds 1 to the miss counter.
4. Stop at the second miss in a row. One missed day inside a streak does not break it and does not count towards it.
5. `missed_yesterday` is true when yesterday is unchecked and the habit was created before today.
6. `last14` is a list of 14 booleans, oldest first, ending today.

`POST /api/habits/{id}/check` toggles today: it soft-deletes today's live check or inserts a new one. Undo then redo leaves one deleted row and one live row.

**Mixed practice (`practice_items`).**

1. Build a pool from three sources, each tagged with a topic:
   - answered quest questions of live quests → topic `quest:<quest id>`;
   - answered paper questions of live documents → topic `doc:<document id>`;
   - terms with a definition → topic `doc:<document id>`, or `glossary` when the term has no document.
2. Find the latest attempt per `source_id` from `practice_attempts`.
3. Give every item a key `(rank, last attempt time)`. Rank: 0 last result `missed`, 1 `partly`, 2 never practised, 3 `got`. Within a rank, the oldest attempt comes first.
4. Sort the pool by key and group it by topic, so each topic's list starts with its weakest item.
5. Order the topics by their first item's key.
6. Take one item per topic in turn (round-robin) until `n` items are taken or the pool is empty.

Each item: `source_type`, `source_id`, `prompt`, `answer`, `topic`, `topic_id`, `last_result`. Term prompts read `What does “<term>” mean?`. The route clamps `n` to 1–30.

### 2.5 Routes

| Method | Path | Body | Returns | Side effects |
|---|---|---|---|---|
| GET | `/api/quests/{quest_id}/map` | — | `topic_map` | None |
| POST | `/api/quests/{quest_id}/map/nodes` | `NodeIn` | `topic_map` | Inserts the node, and one edge per id in `needs` that is a live node of this quest (others are ignored) |
| POST | `/api/quests/{quest_id}/map/seed` | — | `topic_map` plus `"added": n` | Inserts up to 12 nodes |
| PATCH | `/api/map-nodes/{node_id}` | `NodePatch` | `topic_map` of its quest | Update |
| DELETE | `/api/map-nodes/{node_id}` | — | `topic_map` | Soft-deletes the node and every live edge touching it |
| POST | `/api/quests/{quest_id}/map/edges` | `EdgeIn` | `topic_map` | 404 if either node is not in this quest; 409 on a loop; a duplicate edge is not inserted again |
| DELETE | `/api/map-edges/{edge_id}` | — | `topic_map` | Soft delete |
| POST | `/api/quest-questions/{qq_id}/teachback` | `TeachIn` | `{"question", "steps"}` | See 2.4 |
| GET | `/api/logs?quest_id=&days=14` | — | `day_logs` rows, newest day first | `days` clamped to 1–365 |
| POST | `/api/logs` | `LogIn` | `{"log", "step"}` | See 2.4 |
| GET | `/api/habits` | — | `habits(db)` | None |
| POST | `/api/habits` | `HabitIn` | `habit_state` | Insert; all three texts stripped |
| PATCH | `/api/habits/{habit_id}` | `HabitPatch` | `habit_state` | Update |
| DELETE | `/api/habits/{habit_id}` | — | `{"ok": true}` | Soft delete (checks stay) |
| POST | `/api/habits/{habit_id}/check` | — | `habit_state` | Toggles today's check |
| GET | `/api/practice?n=10` | — | `practice_items` | None |
| POST | `/api/practice` | `AttemptIn` | The new row | Insert |

### 2.6 Invariants and gotchas

- The edge direction is easy to reverse by mistake: `from_id` is the prerequisite, `to_id` is the concept that needs it.
- The map stays loop-free only because the edge route checks. `topic_map` survives a loop but the depths it then reports are not meaningful.
- `habits()` and `habit_state()` must agree. `habits()` passes pre-loaded `days`; `test_habits_list_matches_single_habit_state` checks the two paths give the same result.
- `practice_items` matches attempts by `source_id` alone and ignores `source_type`. This works because ids are UUIDs.
- The term query in `practice_items` joins `documents` with `LEFT JOIN` and does not filter `d.deleted`. Terms of a removed document still appear in practice.
- Teach-back replaces a saved answer only when the request sends `replace: true`. Without it, an already answered question keeps its answer and only the gaps are stored (2.4, steps 1–2).

### 2.7 Tests

`tests/test_growth.py`: learn-next follows prerequisites; loops refused; seeding from the quest's reading; teach-back saves the answer and makes steps; one log per day and `next` becomes the lead; the habit toggle; `test_never_miss_twice` (calls `habit_state` directly with a fixed `today`). `tests/test_reflect.py`: `test_practice_interleaves_topics_and_puts_misses_first`, `test_practice_is_empty_without_answers`, and the weekly review that reads logs, steps, habits and practice. `tests/test_open_findings.py`: `test_teachback_replaces_the_answer_only_when_asked` (a second teach-back keeps the first answer; with `replace` it takes the new one).

---

## 3. `lectures.py` — slides, PowerPoint, sealed pages, notebooks, ink

A lecture is shown as pages, not reflowed into text. Beside the pages is a notebook of notes in several forms. A pen layer (ink) can sit over a lecture page, a sketch note or a journal day. A "notebook" lecture has no file: its pages are blank paper.

### 3.1 Tables (`0006_lectures_journal.sql`)

**`lectures`**

| Column | Meaning |
|---|---|
| `title` | Up to 300 characters |
| `kind` | `pdf`, `pptx`, `html`, or `notebook` (the migration comment lists only the first three) |
| `source` | The original file name; `''` for a notebook |
| `file_hash` | SHA-256 of the upload; the original is `library/<hash>.<ext>`; `''` for a notebook |
| `pages` | Page count |
| `position` | The page you were on (0-based) |
| `page_tint` | `normal`, `dim`, `sepia` or `night` |

**`lecture_pages`**

| Column | Meaning |
|---|---|
| `lecture_id`, `ord` | Which lecture, which page (0-based) |
| `title` | First line of a PDF page, slide title, or the HTML title |
| `text` | Imported pages: plain text kept for search. Notebook pages: what the user typed |
| `speaker_notes` | PowerPoint notes |
| `width`, `height` | Points for PDF and PowerPoint; 0 for HTML; 850 × 1100 for a notebook page |
| `layout` | PowerPoint: JSON `{"bg", "els"}`. Notebook: JSON `{"paper": ...}`. Otherwise `''` |

**`lecture_notes`**

| Column | Meaning |
|---|---|
| `lecture_id` | The lecture |
| `page` | Page `ord`, or NULL for the whole lecture |
| `kind` | `text`, `cornell`, `snip`, `question`, `sketch`, `recall` |
| `body` | The main text (for a question note, the question) |
| `data` | JSON object: Cornell fields `cues`/`notes`/`summary`, a snip rectangle, a question's `back` |
| `color` | `''` or one of `sun`, `mint`, `sky`, `lilac`, `peach`, `rose` |

**`ink`**

| Column | Meaning |
|---|---|
| `owner_type` | `lecture_page`, `note` or `journal` |
| `owner_id` | See 3.6 |
| `strokes` | JSON list of cleaned strokes |

`idx_ink_owner` is a unique index on `(owner_type, owner_id)`: one ink row per owner, deleted or not.

### 3.2 Constants

| Name | Value | Controls |
|---|---|---|
| `KINDS` | `.pdf`→`pdf`, `.pptx`→`pptx`, `.html`/`.htm`→`html` | Accepted extensions |
| `MAX_ZIP_ENTRIES` | 5000 | Entry cap for a `.pptx` |
| `MAX_ZIP_TOTAL` | 400 MB | Cap on the declared uncompressed size of a `.pptx` |
| `RASTER` | `png`, `jpg`, `jpeg`, `gif`, `bmp` → MIME subtype | Image types kept from a deck and served |
| `RENDER_WIDTHS` | `(480, 960, 1400, 2000)` | The only widths a PDF page is rendered at |
| `EMU_PER_PT` | 12700 | PowerPoint units per point |
| `SANDBOX_CSP` | See 3.5 | The policy for an HTML lecture |
| `SCROLL_REPORTER` | A `<script>` block as bytes | Added to every served HTML lecture |
| `NoteKind` | The six note kinds | |
| `NOTE_COLOR` | `^(\|sun\|mint\|sky\|lilac\|peach\|rose)$` | Colour names, not CSS |
| `Paper` | `lined`, `dotted`, `grid`, `plain` | Notebook paper |
| `NOTEBOOK_W`, `NOTEBOOK_H` | 850, 1100 | Shape of a notebook page |
| `MAX_NOTEBOOK_PAGES` | 500 | Pages per notebook |
| `MAX_INK_BYTES` | 3 MB | Size of one owner's ink as compact JSON |
| `INK_OWNERS` | `lecture_page`, `note`, `journal` | Accepted `owner_type` values |

The upload size limit is `config.MAX_FILE_BYTES` (50 MB), shared with document import.

### 3.3 Functions

| Signature | Behaviour |
|---|---|
| `with_scroll_reporter(html: bytes) -> bytes` | Inserts `SCROLL_REPORTER` before the last `</body>` (case-insensitive), or appends it |
| `lecture_dir(lecture_id) -> Path` | `library/lectures/<id>/`, created if missing |
| `_check_id(value) -> str` | 404 unless `value` is exactly 32 lower-case hex characters |
| `_parse_pdf(path) -> list[dict]` | One dict per page: `title`, `text`, `width`, `height` |
| `_check_zip(data) -> None` | The PowerPoint zip checks (3.4) |
| `_rgb(color)`, `_fill(shape)`, `_pct(v, total)` | Helpers: `#RRGGBB` or `None`; a solid fill colour or `None`; a percentage rounded to 3 places |
| `_parse_pptx(data, lid) -> list[dict]` | Slides as JSON layouts; writes raster images into `lecture_dir(lid)` |
| `_parse_html(data, stem) -> tuple[str, list[dict]]` | The title and one page of plain text |
| `import_lecture(db, filename, data) -> dict` | Validates, keeps the original, parses, inserts; returns `{"id", "title", "kind", "pages"}` |
| `render_pdf_page(lecture, page, width) -> Path` | A cached PNG of one PDF page, at most `MAX_RENDER_PX` (20,000) pixels tall |
| `create_notebook(db, title, paper) -> dict` | A `notebook` lecture with one blank page |
| `_insert_blank_page(db, lid, ord_, paper, t) -> None` | One notebook page row |
| `_clean_strokes(strokes) -> list` | Keeps only well-formed strokes (3.6) |
| `_note_out(n) -> dict` | Parses `data` from JSON; `{}` if it is not valid |

Inside `register()`: `lecture(lid)` is `need_row(db, "lectures", _check_id(lid))`; `notebook_page(lid, ord_)` returns the lecture and page row or 404; `sync_question_card(note)` keeps a review card in step with a question note.

### 3.4 Import, step by step

`POST /api/lectures/import` reads at most `MAX_FILE_BYTES + 1` bytes and answers 413 if the file is larger. It then runs `import_lecture` in a thread pool (`run_in_threadpool`), so parsing is off the event loop. `ImportFailed` becomes 422 with the reason as `detail`.

`import_lecture(db, filename, data)`:

1. The extension picks the kind through `KINDS`. Anything else: "Lectures can be PDF, PowerPoint (.pptx) or HTML files."
2. Empty data is refused.
3. Content checks by kind:
   - **PDF**: after stripping leading whitespace, the data must start with `%PDF`.
   - **PowerPoint**: the data must start with `PK` (the zip signature). The message tells the user to re-save old `.ppt` files as `.pptx`.
   - **HTML**: no content check. It is only ever shown inside the sandbox.
4. `new_id()` makes the lecture id.
5. `keep_original(data, ext)` writes `library/<sha256><ext>` if it is not there and returns the hash. HTML is always stored as `.html`, also for `.htm`. This happens before parsing, so the original is kept even when parsing fails.
6. Parse by kind (below).
7. In one transaction, insert the `lectures` row and all `lecture_pages` rows with raw SQL (`db.conn.execute` / `executemany`), because the lecture id was chosen earlier.

**PDF (`_parse_pdf`).** Under `PDFIUM_LOCK`, open the stored file and, for each page, read the text, take the first line longer than 2 characters as the title (cut to 120), keep the text (cut to 20,000) and the page size in points. Pages and the document are closed in `finally` blocks. A file PDFium cannot open, or one with no pages, raises `ImportFailed`.

**PowerPoint zip checks (`_check_zip`).** Before `python-pptx` sees the data:

1. It must open as a zip (`BadZipFile` → "isn't a valid PowerPoint file").
2. No more than `MAX_ZIP_ENTRIES` entries, and the sum of the entries' declared `file_size` must not exceed `MAX_ZIP_TOTAL` ("expands to something far too large to open safely").
3. It must contain `ppt/presentation.xml` ("isn't a PowerPoint deck").

**PowerPoint becomes JSON (`_parse_pptx`).** Slide size defaults to 9144000 × 6858000 EMU when the deck does not state it. For each slide, `walk()` visits the shapes:

- A **group** is walked recursively.
- A **picture** is kept only if its extension is in `RASTER`. The bytes are written to `lecture_dir(lid)/img-<first 16 hex of sha256>.<ext>` unless that file exists. EMF, WMF and SVG are skipped and never written.
- A **table** becomes `{"type": "table", ..., "rows": [[cell text ≤ 500]]}`, at most 60 rows.
- A shape with a **text frame** becomes a text element if any run has text; otherwise, if it has a solid fill, a `box`.
- Any other shape with a solid fill becomes a `box`.
- An exception on one shape is logged and that shape is skipped. One odd shape never fails the deck.

Every element carries `x`, `y`, `w`, `h` as percentages of the slide. A text element:

```json
{"type": "text", "x": 5.0, "y": 4.2, "w": 90.0, "h": 15.0, "title": true, "fill": null,
 "paras": [{"level": 0, "align": "center", "default": 36,
            "runs": [{"t": "Backpropagation", "b": false, "i": false, "size": null, "color": null}]}]}
```

- `runs[].t` is cut to 4000 characters. `size` is in points, or `null` when the run inherits it.
- `default` is the fallback size: 36 for a title placeholder, 18 otherwise, minus 2 per indent level, never under 10.
- `align` is `left`, `center`, `right`, `justify` or `''`.
- Colours are `#RRGGBB` only when the deck states an RGB value. Theme colours come out as `null`.

Per slide the page row gets: `title` (the title placeholder, else the first non-blank text line, cut to 120), `text` (all run text, cut to 20,000), `speaker_notes` (cut to 20,000), `width`/`height` in points, and `layout` = `json.dumps({"bg": <solid background or null>, "els": [...]})`. A deck with no slides raises `ImportFailed`.

The layout is data. The front end draws it with DOM nodes and `textContent`. No HTML is produced from a deck at any point.

**HTML (`_parse_html`).** Decode as UTF-8, falling back to cp1252 with replacement. With `lxml`, take `<title>` (cut to 200) as the lecture title, drop `script`, `style` and `noscript`, and keep the remaining text with whitespace collapsed (cut to 50,000) for search. If parsing fails the text is empty and the lecture still imports. The result is one page with `width` and `height` 0.

### 3.5 Serving: page images, deck images, sealed HTML

**PDF page images (`render_pdf_page`).**

1. The route `GET /api/lectures/{lid}/pages/{page}/image?w=1400` answers 404 unless the lecture is a PDF and `0 <= page < pages`. It clamps `w` to 200–4000.
2. The width is rounded up to the next entry of `RENDER_WIDTHS` (2000 at most). This bounds the number of cached files per page to four.
3. The cache file is `library/lectures/<id>/p<page>-w<width>.png`. If it exists it is returned at once, without touching PDFium.
4. Otherwise, under `PDFIUM_LOCK`: open `library/<file_hash>.pdf`, render the page at `scale = width / page width`, but never more than `MAX_RENDER_PX / page height` (`MAX_RENDER_PX` = 20,000 pixels, milestone 4.5, finding L7: a page 1 point wide and 14,400 points tall would otherwise ask for a picture millions of pixels tall), convert to a PIL image, close the bitmap, page and document. A capped page comes out narrower than asked.
5. Outside the lock, save to a temp file with a unique name (`<stem>-<new id>.tmp`) and `replace()` it onto the final name. The swap is atomic, so a half-written PNG is never served, and two renders of the same page cannot share a temp file.

The cache is never cleared. A lecture's file never changes, so the cache cannot go stale.

**PDFium lock.** Both `_parse_pdf` and `render_pdf_page` import `PDFIUM_LOCK` from `importers.pdf_import` and hold it for every PDFium call, from opening the document to closing it. Any new code that touches `pypdfium2` must do the same.

**Deck images.** `GET /api/lectures/{lid}/assets/{name}`:

- `lid` must pass `_check_id` and be a live lecture.
- `name` must fully match `img-[0-9a-f]{16}\.(png|jpe?g|gif|bmp)`.
- The path is `library/lectures/<lid>/<name>`; 404 if it is not a file.
- The media type comes from `RASTER`, not from the file.

Both path parts are restricted to fixed patterns, so the path cannot leave the lecture's folder. `test_pptx_lecture_layout_images_tables_notes` requests `..%2F..%2Freadhold.db` and expects 404.

**Sealed HTML.** `GET /api/lectures/{lid}/content.html` returns the stored original with `SCROLL_REPORTER` inserted, as `text/html; charset=utf-8`. It answers 404 for any other kind, or if the original file is missing. The file on disk is never modified.

The policy is set in `server.py`, not here. The `guard` middleware gives a response `lectures.SANDBOX_CSP` when the path starts with `/api/lectures/` and ends with `/content.html`; every other response gets the app's strict `CSP`. `SANDBOX_CSP` is:

```
sandbox allow-scripts;
default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline';
img-src data: blob:; font-src data:; media-src data: blob:;
connect-src 'none'; form-action 'none'; base-uri 'none';
frame-ancestors 'self'
```

What each part does:

- `sandbox allow-scripts` without `allow-same-origin` makes the page an opaque origin, also when it is opened directly and not in the app's iframe. Its scripts cannot read Readhold's pages, cookies or API. It cannot open windows or submit forms.
- Inline script and style are allowed so interactive lecture pages work. No script, style, image, font or media can be loaded from a URL; only `data:` and `blob:`.
- `connect-src 'none'` blocks `fetch`, XHR and WebSockets.
- `frame-ancestors 'self'` means only the app can frame it.

**`SCROLL_REPORTER`.** The pen layer sits over the iframe and needs to know how far the page has scrolled. The script posts `{readhold: "scroll", x, y, w, h, vw, vh}` (numbers only) to `parent` on scroll, resize, load and body size changes. It accepts one message, `{readhold: "scroll-by", dx, dy}`, only when `e.source === parent`, and calls `window.scrollBy`. It is wrapped in `try/catch`.

### 3.6 Notes, notebooks, ink, export

**Request models.**

| Model | Fields |
|---|---|
| `LecturePatch` | `title` 1–300; `position` ≥ 0; `page_tint` `normal`/`dim`/`sepia`/`night` |
| `NoteIn` | `page` ≥ 0 or null; `kind` (`NoteKind`); `body` ≤ 50000; `data` dict; `color` matching `NOTE_COLOR` |
| `NotePatch` | `body` ≤ 50000; `data` dict; `color`; `page` ≥ 0 |
| `NotebookIn` | `title` 1–300, default `"My notes"`; `paper` (`Paper`), default `lined` |
| `PagePatch` | `text` ≤ 100000; `paper` (`Paper`) |
| `InkIn` | `strokes` list of at most 5000 items |

`LecturePatch` and `NotebookIn` extend `Body` (section 0), so a title of spaces is a 422. The others have no required text.

**Notes.** `data` is stored as JSON text and must serialise to at most 200,000 characters (413 otherwise). A note's `page` must be below the lecture's page count (422 "No such page."). Creating a note also calls `db.update("lectures", lid, {"position": <unchanged>})` only to bump `updated_at`, so recently used lectures sort first.

**Question notes are review cards.** `sync_question_card(note)` runs after every create and patch. If the note's kind is `question` and both `body` and `data["back"]` are non-blank, it calls `services.upsert_card(db, "lecture_note", note id, front, back, None)`. Otherwise it calls `services.remove_card`. Deleting a note removes the card and soft-deletes the note's ink.

**Notebooks.** `create_notebook` inserts a lecture with `kind="notebook"`, empty `source` and `file_hash`, `pages=1`, and one page from `_insert_blank_page` (size 850 × 1100, `layout` `{"paper": ...}`). `POST /api/lectures/{lid}/pages` adds a page at the end on the same paper as the last page, raises `pages`, and moves `position` to the new page; it refuses beyond `MAX_NOTEBOOK_PAGES`. `PATCH /api/lectures/{lid}/pages/{ord_}` saves the typed text or changes the paper. Both page routes answer 404 for an imported lecture. Both change the `lectures` row with a raw `UPDATE` that sets `updated_at` and `device_id`.

`GET /api/lectures/{lid}` returns page `text` only for notebooks. For imported lectures `text` is removed from each page: it exists for search only.

**Ink storage.** One row per owner. The owner id must match `[0-9a-f]{32}(:\d{1,5})?|\d{4}-\d{2}-\d{2}`: a 32-hex id, optionally followed by `:<number>`, or a date. The tests use `<lecture id>:<page ord>` for `lecture_page` and a date for `journal`. The route does not check that the owner exists, and does not tie the id form to the owner type.

`PUT /api/ink/{owner_type}/{owner_id}` replaces the whole stroke list. `_clean_strokes` rebuilds every stroke from scratch:

| Field | Rule |
|---|---|
| stroke | Must be a dict with a `points` list, else dropped |
| `tool` | `pen` or `highlighter`; anything else becomes `pen` |
| `color` | Must match `#RRGGBB`; anything else becomes `#222222` |
| `size` | A number in 0.0005–0.1; anything else becomes 0.004 |
| `points` | At most the first 20,000; each a list `[x, y]` or `[x, y, pressure]` of numbers |
| `x`, `y` | Kept only if `-0.1 <= x <= 1.1` and `-0.1 <= y <= 3.0`; rounded to 5 places |
| `pressure` | Default 0.5; clamped to 0–1; rounded to 3 places |

A stroke with no valid points is dropped. Unknown keys never survive. The stored format is:

```json
[{"tool": "pen", "color": "#1e3a8a", "size": 0.004, "points": [[0.1, 0.1, 0.5], [0.2, 0.15, 0.7]]}]
```

Coordinates are fractions of the owner's size, not pixels (the migration comment says "coordinates 0..1"). The code allows `y` up to 3.0; the reason is not stated in this module. The cleaned list is serialised compactly and refused with 413 above `MAX_INK_BYTES`. The upsert looks up the row without filtering `deleted` and sets `deleted=0`, which the unique index requires. `GET` returns `{"strokes": [...], "updated_at": ...}`, with an empty list and `null` when there is no live row.

**Notebook export.** `GET /api/lectures/{lid}/export` returns `{"markdown": "..."}`:

1. `# <lecture title>`.
2. For a notebook lecture: `## Page N` and the typed text for each page that has text, then `## Notebook` if there are notes.
3. Notes ordered with whole-lecture notes first, then by page and creation time. Each is one of:
   - `cornell`: a `## Cornell sheet` block with **Cues**, **Notes**, **Summary** from `data`;
   - `question`: `- **Q (<where>):** <body>` and an indented line with `data["back"]`;
   - `snip`: `- ✂ Snip (<where>): <body>`;
   - `recall`: `- Recall (<where>): <body>`;
   - `sketch`: `- ✎ Sketch (<where>)` plus `: <body>` if there is one;
   - anything else: `- <where>: <body>`.
4. `<where>` is `Whole lecture` or `Page N` (1-based).
5. The text passes through `text.math_to_markdown`.

Ink is not part of the Markdown export.

### 3.7 Routes

| Method | Path | Body | Returns | Side effects |
|---|---|---|---|---|
| GET | `/api/lectures` | — | List: `id, title, kind, pages, position, updated_at, notes` (live note count), newest `updated_at` first | None |
| POST | `/api/lectures/import` | multipart `file` | `{"id", "title", "kind", "pages"}`; 413 over 50 MB; 422 with the reason | Writes the original, deck images, DB rows |
| POST | `/api/lectures/notebook` | `NotebookIn` | `{"id", "title", "kind": "notebook", "pages": 1}` | Inserts lecture and one page |
| GET | `/api/lectures/{lid}` | — | The lecture row plus `page_list` (`ord, title, speaker_notes, width, height, layout`, and `text` for notebooks) | None |
| PATCH | `/api/lectures/{lid}` | `LecturePatch` | The row | `position` clamped to `pages - 1` |
| DELETE | `/api/lectures/{lid}` | — | `{"ok": true}` | Soft delete; files stay |
| POST | `/api/lectures/{lid}/restore` | — | The row | Sets `deleted=0` |
| POST | `/api/lectures/{lid}/pages` | — | The new page as a `page_list` item | Notebook only; adds a page, moves `position` |
| PATCH | `/api/lectures/{lid}/pages/{ord_}` | `PagePatch` | `{"ok": true}` | Notebook only; bumps the lecture's `updated_at` (and sets its `device_id`) |
| GET | `/api/lectures/{lid}/pages/{page}/image?w=` | — | PNG | PDF only; may render and cache |
| GET | `/api/lectures/{lid}/assets/{name}` | — | The image | None |
| GET | `/api/lectures/{lid}/content.html` | — | The HTML, under `SANDBOX_CSP` | HTML only |
| GET | `/api/lectures/{lid}/notes` | — | Notes with `data` parsed, by page, whole-lecture notes last | None |
| POST | `/api/lectures/{lid}/notes` | `NoteIn` | The note | Card sync; bumps the lecture's `updated_at` |
| PATCH | `/api/lecture-notes/{nid}` | `NotePatch` | The note | Card sync |
| DELETE | `/api/lecture-notes/{nid}` | — | `{"ok": true, "lecture_id": ...}` | Soft-deletes the note, its card and its ink |
| GET | `/api/lectures/{lid}/export` | — | `{"markdown": ...}` | None |
| GET | `/api/ink/{owner_type}/{owner_id}` | — | `{"strokes", "updated_at"}` | None |
| PUT | `/api/ink/{owner_type}/{owner_id}` | `InkIn` | `{"ok": true, "strokes": <count kept>}` | Upsert |

### 3.8 Invariants and gotchas

- **The sandbox depends on a path match in another file.** If the content route is renamed, or a second route serves lecture HTML, the `guard` in `server.py` must change too, or the page gets the app's CSP (and breaks) or, worse, a new route serves untrusted HTML without the sandbox. `test_html_lecture_runs_sandboxed_without_network` pins the header.
- Never add `allow-same-origin` to `SANDBOX_CSP`, and never add a network source. The test asserts both.
- Every id that becomes part of a file path goes through `_check_id` or a full-match regular expression. Keep it that way for any new file route.
- `text` on an imported page is search data. Do not return it from `GET /api/lectures/{lid}`; `test_imported_lectures_cannot_get_notebook_pages` checks it is absent.
- `lectures` and `lecture_pages` rows are inserted with raw SQL in `import_lecture`, `create_notebook` and `_insert_blank_page`. A new column needs a default or a change in each of those statements.
- `NotePatch` uses `exclude_none`, so a note cannot be moved back to "whole lecture" (`page = NULL`) through the API.
- The note list and the export order whole-lecture notes differently (last in the list, first in the export). Both are deliberate in the SQL (`page IS NULL` versus `page IS NULL DESC`).
- Deleting a lecture does not delete its notes, cards or ink. They become unreachable through the lecture routes because `lecture(lid)` answers 404.

### 3.9 Tests (`tests/test_lectures.py`)

| Test | Covers |
|---|---|
| `test_pdf_lecture_pages_and_rendering` | Page titles and size, PNG output, out-of-range page, the cached file |
| `test_pptx_lecture_layout_images_tables_notes` | Text runs, indent level, bold, size, table rows, image asset and its content type, a path-traversal name, percentages |
| `test_html_lecture_runs_sandboxed_without_network` | The title, the sandbox header, and that the app's own CSP stays strict |
| `test_lecture_import_checks_content` | Fake PDF, fake PowerPoint, wrong extension, empty file |
| `test_zip_bomb_and_non_deck_zip_are_refused` | `MAX_ZIP_TOTAL` (lowered by monkeypatch) and a zip with no deck |
| `test_lecture_position_clamp_delete_restore` | Position clamp, delete, restore, a malformed id |
| `test_notebook_notes_questions_become_cards` | Note kinds, bad page and bad kind, card create/update/remove, list order, export |
| `test_ink_is_cleaned_and_round_trips` | Stroke cleaning, unknown owner type, a traversal path |
| `test_ink_size_limit` | `MAX_INK_BYTES` |
| `test_note_cannot_move_to_missing_page_and_export_has_everything` | Page check on patch; the full JSON export includes these tables |
| `test_html_lecture_gets_scroll_reporter_for_the_pen` | Placement of the script; the stored original is unchanged |
| `test_blank_notebook_pages_writing_and_export` | Notebook pages, paper, text, export, refusals |
| `test_imported_lectures_cannot_get_notebook_pages` | Page routes are notebook-only |

Not covered by a test: the 413 for an upload over 50 MB, `MAX_ZIP_ENTRIES`, `MAX_NOTEBOOK_PAGES`, and the 200,000-character cap on note `data`.

---

## 4. `journal.py` — journal and letters

One page per day. The page arrives with the day's facts already listed, so the user writes about how it went. Mood is "inner weather". Letters to a future self stay sealed until a chosen date.

### 4.1 Tables (`0006_lectures_journal.sql`)

**`journal_entries`**

| Column | Meaning |
|---|---|
| `day` | Local date; unique index `idx_journal_day` |
| `weather` | `''`, `sunny`, `bright`, `cloudy`, `rainy` or `stormy` |
| `body` | The free text |
| `prompts` | JSON `[{"q": ..., "a": ...}]` |

**`letters`**

| Column | Meaning |
|---|---|
| `body` | The letter |
| `open_on` | Local date; sealed until then |
| `opened_at` | NULL until opened |

A letter moves one way: sealed (`open_on` in the future) → ready (`open_on <= today`, `opened_at` NULL) → opened (`opened_at` set). There is no route to edit or delete a letter, or to delete a journal entry.

Handwriting on a journal page is stored in the shared `ink` table with `owner_type="journal"` and the date as `owner_id` (see 3.6).

### 4.2 Constants, helpers, models

- `Weather = Literal["", "sunny", "bright", "cloudy", "rainy", "stormy"]`.
- `PROMPTS`: a dict of five decks — `gratitude` (3), `learning` (3), `win` (3), `worry` (3), `kindness` (2). It is returned whole with every journal page; the front end draws from it.

| Signature | Behaviour |
|---|---|
| `_day(value: str) -> str` | 422 unless `value` is `YYYY-MM-DD` and a real date |
| `_utc_bounds(day: date) -> tuple[str, str]` | Local midnight and the next midnight, as UTC strings |
| `_clock(iso: str) -> str` | A stored timestamp as local `HH:MM` |
| `day_story(db, day: date) -> list[dict]` | The day's facts (4.3) |
| `_entry(db, day: str) -> dict \| None` | The live entry with `prompts` parsed (`[]` if invalid) |

| Model | Fields |
|---|---|
| `EntryIn` | `weather` (`Weather`), default `''`; `body` ≤ 100000; `prompts` list of at most 20 dicts |
| `LetterIn` | `body` 1–50000; `open_on` string (validated by `_day` in the route). Extends `Body` (section 0): a body of spaces is a 422 |

### 4.3 How the page is pre-filled: `day_story`

Facts only, read from other features' tables for the local day:

| Source | Condition | Item |
|---|---|---|
| `sessions` (joined to `documents` and `quest_steps`) | Started that day, `focused_ms >= 60000` | `kind: "session"`, text `<Read\|Worked on> <what> · <N> min`, plus ` → <output>` when the output is non-empty and not `"done"`; also `feel` |
| `quest_steps` (joined to `quests`) | `done_at` that day, the goal not deleted (since 5.1) | `kind: "step"`, `Finished: <title>` |
| `quest_questions` (joined to `quests`) | `answered_at` that day, the goal not deleted (since 5.1) | `kind: "answer"`, `Answered: <text>` |
| `habit_checks` (joined to `habits`) | `day` equals the date, check and habit not deleted (the habit since 5.1) | `kind: "habit"`, `Kept a habit: <title>` |
| `reviews` | `reviewed_at` that day, count > 0 | `kind: "review"`, `Reviewed N card(s)`, no time |
| `lecture_notes` | `created_at` that day, count > 0 | `kind: "notes"`, `Took N lecture note(s)`, no time |
| `day_logs` | That day's log has `learned` | `kind: "learned"`, `Learned: <text>`, no time |

For a session, `<what>` is the step title, else the document title, else the session's `question`, else `a focus session`. The verb is `Read` when the session has a document, otherwise `Worked on`.

Items are sorted by time; items without a time come last. Each item is `{"time": "HH:MM" or "", "kind", "text"}`.

Answers to paper questions (`questions` table) are not in the story; only quest questions are.

### 4.4 Routes

| Method | Path | Body | Returns | Side effects |
|---|---|---|---|---|
| GET | `/api/journal/{day}` | — | See below | None |
| PUT | `/api/journal/{day}` | `EntryIn` | The entry with `prompts` parsed | Upsert by day |
| GET | `/api/letters` | — | `{"opened": [...], "sealed": [...]}` | None |
| POST | `/api/letters` | `LetterIn` | `{"id", "open_on"}` | Insert |
| POST | `/api/letters/{letter_id}/open` | — | The full letter row | Sets `opened_at` once |

**`GET /api/journal/{day}`** returns:

```json
{"day": "2026-11-12", "entry": {...} , "story": [...], "memories": [...],
 "recent": [{"day": "...", "weather": "...", "wrote": 1}],
 "letters_due": [{"id": "...", "created_at": "...", "open_on": "..."}],
 "letters_sealed": 0, "prompts": {...}}
```

- `memories` ("On this day"): the entries exactly 7, 30 and 365 days before `day`, labelled `A week ago`, `A month ago`, `A year ago`. One is included only if it has text or a weather. The body is cut to 400 characters.
- `recent`: entries from the 41 days up to and including `day`, with `wrote` = whether the body is non-empty.
- `letters_due`: unopened letters with `open_on <= ` the real today (not `day`), without their bodies.
- `letters_sealed`: the count of letters with `open_on` after today.

**`PUT /api/journal/{day}`.** A future day is refused with 422 ("You can't write tomorrow's page yet."). Each prompt is rebuilt as `{"q": str ≤ 500, "a": str ≤ 20000}`; non-dict items are dropped and other keys are discarded. The existing row is looked up without filtering `deleted` and the update sets `deleted=0`, because the unique index allows only one row per day.

**Letters.**

- Create: `open_on` must be a real date strictly after today (422 otherwise). The body is stripped.
- List: `opened` holds full rows, newest opened first, at most 50. `sealed` holds `id, open_on, created_at` and `ready` (`open_on <= today`) for every unopened letter. A sealed letter's body is never in this response.
- Open: 403 `Sealed until <date>.` while `open_on` is after today. Otherwise `opened_at` is set if it was NULL and the full row, with the body, is returned. Opening again changes nothing.

### 4.5 Invariants and gotchas

- The seal is enforced by which columns the list queries select and by the 403 in the open route. Any new route that returns `letters` rows must keep the body out for unopened letters.
- `journal_entries.day` is unique. Always upsert; never insert a second row for a day.
- `GET` accepts future days (it only reads). Only `PUT` refuses them.
- `compass.today()` counts due letters itself with its own query on `letters`. A change to what "due" means has to be made in both places.
- Day comparisons on `open_on` and `day` are string comparisons on ISO dates. They rely on the `YYYY-MM-DD` form that `_day` enforces.

### 4.6 Tests

In `tests/test_lectures.py`: `test_journal_page_with_day_story_and_memories` (the story lines for a session and a finished step, the week-ago memory, the prompt decks, one page per day, a future day, an invalid date, an invalid weather) and `test_letters_stay_sealed_until_their_day` (403 before the date, the body hidden in the list, a non-future date refused, `letters_due`, opening). `tests/test_reflect.py` has no journal test; its export tests cover the tables only indirectly. Not covered: the month and year memories, `recent`, `letters_sealed`, and prompt cleaning limits.

---

## 5. Removed: the calm tools

The calm tools were removed on 2026-11-25: Unstick with Shrink it (the two-minute tiny start) and Steady me (the breathing reset), the notes from steady you, and guess versus reality.

- `readhold/calm.py` is deleted. `create_app()` no longer calls `calm.register`, and every `/api/calm…` route answers 404.
- The settings keys `unstick_button`, `guess_ask` and `steady_pattern` are gone from `DEFAULT_SETTINGS`.
- The session and timer models no longer take `guess_hard`, `real_hard` or `guess` (chapters 1 and 3).
- The database keeps the old data. Migrations `0008_calm.sql` and `0009_steady_notes.sql` are not edited, so the tables `unstick_events` and `steady_notes` and the columns `sessions.guess_hard` and `sessions.real_hard` still exist. Nothing reads or writes them.
- Both tables are still in `services.EXPORT_TABLES`, so old rows are part of the full JSON export. The two `sessions` columns travel with the `sessions` rows.
- `tests/test_calm.py` and `tests/test_steady_notes.py` are deleted. `tests/test_no_network.py::test_the_calm_tools_are_gone` checks that `/api/calm` and `/api/calm/notes` answer 404, that the three settings keys are gone, and that a timer start that still sends a `guess` is accepted and returns a run without `guess_hard`.

---

## 6. Cross-module links worth knowing

| Reader | Reads from | Why |
|---|---|---|
| `compass.today` | `growth.habits`, `growth.log_today`, `letters` | The Today page shows habits, the day log and due letters |
| `growth.register` | `compass.active_quest`, `clear_lead`, `need_row` | The day log and teach-back write `quest_steps` |
| `growth.practice_items` | `quest_questions`, `questions`, `terms`, `documents` | Practice draws on answers from the reader and from goals |
| `lectures.register` | `services.upsert_card`, `remove_card` | Question notes are review cards |
| `journal.day_story` | `sessions`, `quest_steps`, `quest_questions`, `habit_checks`, `reviews`, `lecture_notes`, `day_logs` | The pre-filled day |
| `server.guard` | `lectures.SANDBOX_CSP` | The sandbox header |

A rename or a change of meaning in any column on the right needs a check of the reader on the left.
