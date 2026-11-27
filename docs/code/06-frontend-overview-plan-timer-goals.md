# 6. Front end: Overview, Plan, Timer and Goals

This chapter covers the pages you use to decide what to do and to do it. All of them live in `web/src/views/`.

| File | Page in the app | Address |
|---|---|---|
| `hub.ts` | Overview | `#/hub` (also the default page) |
| `plan.ts` | Plan → Tasks | `#/plan`, `#/plan?view=week` |
| `readplan.ts` | The **Plan my reading** dialog, from the Plan tab header (a dialog, not a page) | – |
| `tidy.ts` | The three Tidy dialogs (milestone 5.2): **✨ Tidy tasks** from the Plan header, the ✨ on a routine, the ✨ in a note's bar | – |
| `planchat.ts` | The **Plan with a model** dialog (Plan chat, milestone 5.3), from the Plan header | – |
| `today.ts` | Plan → Today | `#/home` |
| `timer.ts` | Timer | `#/timer` |
| `quest.ts` | Study → Goals | `#/quest`, `#/quest/new`, `#/quest/<id>` |
| `map.ts` | A goal's topic map | `#/map/<questId>` |
| `logs.ts` | The daily log list (a helper, not a page) | – |
| `libtabs.ts` | The shared tab header (a helper, not a page) | – |

How they fit together:

- The menu has merged entries. **Plan** is one menu entry with two tabs: Tasks (`plan.ts`) and Today (`today.ts`). **Study** (menu id `library`) has five tabs; Goals (`quest.ts`) is one of them. The tab strip is drawn by `libtabs.ts`. `PART_OF` in `main.ts` tells the menu which entry to highlight (`home → plan`, `quest → library`, `map → library`).
- **Tasks** are rows of the `todos` table. The Plan page, the Timer page's to-do list and the Overview all read and write the same rows through `/api/todos`.
- **Goals** are called *quests* in the code. The active quest is the "main goal". Its next open step (the "lead step") shows on Today, on Plan as a special row, and on the Overview.
- **The timer** is one object for the whole app (`web/src/timer.ts`). Every page here either starts it or shows it.
- **Overview** reads all of this in one call and offers the most common action of each feature.

Every page function has the same shape: it takes the root element, loads its data, builds DOM with `h()` and appends it. Some return a cleanup function, which `route()` in `main.ts` calls before the next page. If a page finishes loading after a newer page change, `route()` calls its cleanup at once and does not keep it (`routeSeq`, `keep`).

| Function | Returns a cleanup? |
|---|---|
| `hubView(root)` | yes |
| `planView(root, params)` | yes |
| `todayView(root)` | no |
| `timerView(root)` | yes |
| `questView(root, id)` | no |
| `mapView(root, questId)` | yes |

---

## 6.1 `hub.ts` — Overview

```ts
export async function hubView(root: HTMLElement): Promise<() => void>
```

### Data

- `GET /api/hub` fills the page (`HubData`). The server side is `hub()` in `readhold/hub.py`. It only reads.
- `GET /api/think?day=<today>` is asked separately and not awaited. When it arrives, `think` is set and `render()` runs again. If it fails, the error is ignored and the Think part keeps its "Looking through your notes…" text.
- The timer state comes from the `timer` object, not from `/api/hub`.

What `/api/hub` holds (checked in `hub.py`): `tasks` is at most 6 open tasks due today or earlier, starred first and then by time of day; `tasks_now` is the full count of those; `routines` holds only routines that are on today; `documents` is 3 unfinished documents; `lectures` is 3; `notes` is 5 (the page shows 4); `ideas` is 2, each cut to 140 characters. The server also returns `notes_total`, `lectures_total` and `stamp`, which `hub.ts` does not read.

### `render` and `reload`

- `render()` clears `page` (`section.hub`), resets the `clocks` list and builds everything again from `data`, `think` and `timer`. The rebuild runs inside `keepTyped(page, …)` from `util.ts`, so text half-typed in a quick box, its caret and the focus are put back afterwards (see 6.11).
- `reload(focus?)` fetches `/api/hub` again, calls `render()`, and if `focus` (a CSS selector) is given, focuses that element. Quick boxes pass their own class (`.hub-task`, `.hub-note`, `.hub-idea`) so the caret stays in the box after Enter.

### Helpers (all local to `hubView` unless noted)

| Helper | What it builds |
|---|---|
| `bar(part, label)` (module level) | `div.hub-bar` with an inner `span` whose width is `part` (0–1) as a percent. `role="img"` with the label. |
| `card(group, icon, title, href, cls, ...kids)` | `div.isle.hub-card.g-<group>` with a `hub-card-head` (icon in `hub-ico`, `h3`, and an arrow link `a.hub-open` when `href` is not null). |
| `part(title, href, ...kids)` | One tab of a merged card: `div.hub-part` with a title link `a.hub-part-title`. |
| `quickBox(cls, placeholder, label, run)` | A text input `input.hub-input.<cls>`. On Enter with text it empties the box and calls `run(text)`. If `run` throws, the text is put back and the error is shown as a toast. |
| `links(...[label, href])` | `div.hub-links` with plain links. |
| `empty(text)` | `p.hub-empty`. |
| `clock()` | `span.hub-clock` with the timer's current time. It also pushes the element into `clocks`, so the one-second tick can update it. |
| `focusOn(task)` | Starts a focus timer on a task (`timer.start({ kind: "focus", minutes: t.minutes, todo_id: t.id })`), unless that task is already being timed. |
| `plural`, `fromYmd`, `greeting` (module level) | Small text helpers. |

### The header: `head()` and `nextUp()`

`head()` builds `header.isle.hub-head`:

- **Top row** (`hub-head-top`): the date and greeting (`hub-hello`), and tools (`hub-head-tools`): a "Find anything…" button (`openPalette()`), the Simple mode toggle, and a Settings link.
- **Main row** (`hub-head-main`): the ring and the next thing.
  - The ring is `div.hub-ring`. It shows `tasks_done_today / (tasks_done_today + tasks_now)` and sets the CSS variable `--p` to the percent. With no tasks it shows "–".
- **Pills** (`hub-pills`, each an `a.hub-pill`): tasks for today → `#/plan`; minutes focused → `#/stats`; cards due → `#/review`; routines done (routines with `total > 0` and `done >= total`, out of all of today's routines) → `#/plan`.

`nextUp()` picks **one** thing. The order is fixed:

| # | Condition | Kicker | Action |
|---|---|---|---|
| 1 | `timer.run` exists | "Running now" or "Paused" | link "Open the timer" → `#/timer`; the text holds a live `clock()` |
| 2 | `data.quest_step` exists and `in_plan` is false | "Next step of your goal" | link "Start · N min" → `#/focus/<stepId>` |
| 3 | `data.tasks[0]` exists | "The one that matters today" (starred) or "First task for today" | button "Focus · N min" → `focusOn(t)` |
| 4 | `data.review_due > 0` | "Due for review" | link "Review now" → `#/review` |
| 5 | none of these | "Nothing is waiting" | link "Open Plan" |

A goal step that already has an open task in Plan (`in_plan`) is skipped in rule 2, because its task then shows through rule 3.

### Sections, grid classes and cards

`section(label, hint, cls, ...cards)` builds `section.hub-group` with an `h2.hub-section` and a `div.hub-grid.<cls>`.

| Section | Grid class | Cards |
|---|---|---|
| Do | `hub-grid do` | `planCard()`, `timerCard()`, `routineCard()` |
| Learn | `hub-grid learn` | `libraryCard()` |
| Reflect | `hub-grid reflect` | `notesCard()`, `staminaCard()` |

A card built with the class `merged` spans the full grid row (`.hub-grid .hub-card.merged { grid-column: 1 / -1 }` in `styles.css`). Inside it, `div.hub-parts` lays out the parts; the modifier sets the column count on wide screens: `two`, `three`, `four`, and `two plan` (Tasks wider than Today).

**Plan card** — `planCard(alone = false)`

- Normal: `card("do", …, "merged", div.hub-parts.two.plan)` with two parts, Tasks and Today.
- Simple mode (`alone = true`): a plain card with classes `wide tall` that holds the Tasks content only.

*Tasks part* — `tasksPart()`:

- A quick box (`.hub-task`). The text goes through `parseQuick()` from `plan.ts`. Then `POST /api/todos` with `due: q.due ?? data.today`. So a task typed here lands on **today** unless a day is written. (On the Plan page the same line without a day lands in Anytime.)
- A list `ul.hub-list`. Each row: a tick button (`PATCH /api/todos/<id> { done: true }`, then `reload()`), the text (with `★` when starred), chips for the time (`tchip due`), "carried" when `due < today`, the minutes, and a ▶ button that calls `focusOn`. The row has `is-active` and the button shows `●` while that task is being timed.
- A foot line: "N more for today" (when more than 6), open in all, done today.
- Links to `#/plan` and `#/plan?view=week`.

*Today part* — `goalPart()`: the main goal's title (link to `#/quest/<id>`), a `bar()` of steps done, the next step with a "Start" link to `#/focus/<stepId>`, and links to Today, the goal, and all goals. No API calls.

**Timer card** — `timerCard()`

- No run: four `button.hub-preset`: 25 min, 50 min, Break 5, Stopwatch. Each calls `timer.start(...)` and then `render()`.
- A run: kind and label, a big `clock()`, a Pause/Resume button (`timer.toggle()`), and a link to `#/timer` to stop or change it. The Overview cannot stop a timer.
- Foot: minutes focused today.

**Routines card** — `routineCard()`: one row per routine that is on today, with a `bar()`, "Next: …" and a tick button for the next open step (`POST /api/routines/<id>/steps/<stepId>/check { done: true }`, then `reload()`). A finished routine shows a static ✓.

**Study card** — `libraryCard()`: a merged card with two rows of parts.

- `hub-parts two`: **Lectures** (title links to `#/lecture/<id>`, chip "page X of Y" or the kind) and **Documents** (title links to `#/read/<id>`, a `bar()` of `position / total_sentences`).
- `hub-parts three`: **Goals** (main goal title and steps done), **Review** ("Review now" when cards are due, else "Practice" → `#/practice`), **Glossary** (count and "Browse").
- No API calls; every item is a link.

**Notes card** — `notesCard()`: a merged card with `hub-parts four`.

| Part | Shows | Quick action |
|---|---|---|
| All notes | up to 4 recent notes; a daily note shows as "Today's note" or its date | quick box `.hub-note` → `POST /api/pages/capture { text, day }` |
| Journal | the weather icon chosen today, and whether the page is started | link to `#/journal` |
| Ideas | the 2 latest ideas and the inbox count | quick box `.hub-idea` → `POST /api/ideas { text }` |
| Think | the first pick that is not yet `opened` (or the first pick), its reason, counts of picks and suggestions | "+ Capture" (`openCapture()`), "Review suggestions" → `#/think` |

**Stamina card** — `staminaCard()`: seven bars (`div.hub-spark`, one `hub-spark-day` per day, `is-today` on today) scaled to the largest day, with a floor of 10 minutes for the scale.

### Simple mode

`simple()` reads `state.settings.simple_mode`. In simple mode `render()` draws only `head()`, a `div.hub-grid.simple` with `planCard(true)` and `timerCard()`, and a note (`p.hub-simple-note`).

The toggle calls `saveSettings({ simple_mode })` and then dispatches a `hashchange` event. That runs `route()` again, so the menu (`nav()` in `main.ts`) is redrawn too, without its group names.

### Live updates and keys

- **Clock tick.** A one-second `setInterval` writes the time into every element in `clocks`. The page is not rendered again for this.
- **Timer subscription.** `timer.on(...)` compares `timer.run?.id` with `lastRun`. When a run starts or ends, it calls `reload()`, unless a modal is open (`.modal-back` exists). Pause and resume do not change the id, so they do not reload; the buttons that pause call `render()` themselves.
- **N key.** Focuses the task quick box, unless you are typing or a modifier key is held.
- The cleanup clears the interval, the subscription and the key listener.

---

## 6.2 `plan.ts` — Plan → Tasks

### Exports

| Export | Purpose |
|---|---|
| `repeatLabel(rule)` | `"weekly"` → "every week", `"every:3"` → "every 3 days", `"every:14"` → "every 2 weeks". Unknown rules are returned as they are. |
| `ymd(date)` | A local date as `YYYY-MM-DD`. Also used by `hub.ts` and `quest.ts`. |
| `Quick` (interface) | The result of `parseQuick`. |
| `parseQuick(raw, today)` | One typed line into a task. |
| `planView(root, params)` | The page. Its tab header carries three tools in `span.plan-tools` (`readingBtn()`, passed to `planHead` as a tool, also on every re-render): **📚 Plan my reading**, which opens `readingPlanDialog(() => reload())`; since 5.2 **✨ Tidy tasks** (`tidyTasksDialog(() => reload())`, section 6.2c); since 5.3 **💬 Plan with a model** (`planChatDialog(() => reload())`, section 6.2d). |

### `parseQuick`

```ts
export function parseQuick(raw: string, today: string): Quick
// Quick = { text, priority?, at?, due?, repeat_rule?, area?, minutes? }
```

The line is split on spaces. Each word is tested in this order; the first match wins. A word that matches nothing is part of the task text.

| # | Mark | Rule | Example → result |
|---|---|---|---|
| 1 | `#area` | Starts with `#` and is longer than one character. `_` and `-` become spaces, the first letter is made upper case. | `#health` → area "Health"; `#deep_work` → "Deep work" |
| 2 | `~N` | `~` and 1–3 digits. Clamped to 1–600. | `~15` → 15 minutes; `~0` → 1 |
| 3 | `!` or `!!` | Exactly that word. | `!` → `priority: 1` |
| 4 | `*word` | `day`, `daily`, `weekday`, `weekdays`, `week`, `weekly`, `month`, `monthly` (`REPEAT_WORDS`). | `*daily` → `"daily"`; `*week` → `"weekly"` |
| 5 | `*Nd`, `*Nw` | N days or N weeks, where the total is 2–999 days. | `*3d` → `"every:3"`; `*2w` → `"every:14"`; `*1d` is not accepted and stays as text |
| 6 | a time | `H:MM` or `HH:MM`, with or without `@`. Stored as `HH:MM`. | `9:05` → `"09:05"`; `@14:30` → `"14:30"` |
| 7 | `@day` | Whatever `parseDay` accepts (below). | `@tomorrow`, `@fri`, `@+3`, `@2026-12-01` |

`parseDay(word, today)` accepts: `today`/`tod`; `tomorrow`/`tmr`/`tom`; `+N` (1–3 digits); a full `YYYY-MM-DD`; or the start of an English weekday name, at least three letters. A weekday always means the **next** one, never today (`@fri` typed on a Friday is next week's Friday).

Things to know:

- If a mark appears twice, the last one wins.
- `parseQuick` does not shorten the area. The server allows 40 characters (`TodoIn.area`), so a longer `#tag` is refused by the server.
- The server gives a repeating task with no day today's date (`api_todo_create` in `timer.py`).

### View state

| Variable | Scope | Meaning |
|---|---|---|
| `lastView` | module | `"list"` or `"week"`. Kept while the app is open, so coming back to Plan shows the same view. `?view=week` in the address sets it. |
| `view` | page | The view shown now. |
| `area` | page | The life area filter (`""` = all). Reset on every visit. |
| `openItems` | page | A `Set` of task ids whose small steps are showing. |
| `data` | page | The last `PlanData` from `GET /api/plan`. |
| `tabs` | page | The current tab header element. |
| `lastTimed` | page | The task id the timer was on at the last check. |

### How it re-renders

Three small functions change data:

- `reload()` — `GET /api/plan` again, then `render()`.
- `patch(task, body)` — `PATCH /api/todos/<id>`, then `reload()`.
- `setTask(fresh)` / `setRoutine(fresh)` — replace one task or routine in `data` from a response. The caller then calls `render()` with no second request. The small-steps box and routine ticks use this.

`render()` rebuilds the whole page, inside `keepTyped(page, …)` from `util.ts`. `keepTyped` notes every text box on the page that holds unsent text or has the focus, runs the rebuild, then writes the text back into the same box, fires an `input` event so the quick-add preview is repainted, and gives back the focus and the caret. This covers the main quick-add box (`.plan-add-input`), a small-steps box (`.task-items-add`, matched by its `data-id`) and a week column's add box (`.wk-add`, matched by its `data-day`). These boxes also set the focus by hand after their own add (see 6.11).

**Tab header refresh.** Every `render()` calls `planHead("tasks")` again and swaps it in with `tabs.replaceWith(fresh)`. This is how the number on the Tasks tab follows what you tick and add. It costs one `GET /api/plan/counts` per render.

**Timer subscription.** `timer.on(...)` watches `timer.run?.todo_id`. When it changes, the page reloads so the "being timed" mark follows, unless a modal is open.

### Page layout

`render()` appends to `section.plan`:

- `header.plan-head`: the date, the title "Tasks", a summary line (`p.plan-summary`), and the List/Week switch (`div.note-seg` with two `button.note-seg-btn`).
- List view: `div.plan-grid` holding `renderTasks()` and `renderRoutines()`.
- Week view: `div.plan-week` holding `quickAdd()`, `areaChips()` and `renderWeek()`. Routines are not shown in the week view.

### Quick add — `quickAdd()`

- An input (`.plan-add-input`), an "Add" button and a preview line (`div.plan-add-preview`, `aria-live="polite"`).
- `paint()` runs on every `input` event. It calls `parseQuick` and shows a chip (`span.tchip`) for each thing it understood: `★ matters`, the day (through `dueLabel`), `⏰ time`, `↻ repeat`, the area, the minutes. With an empty box it shows the list of marks. With text but no marks it says the task will go to Anytime.
- `add()` runs on Enter or the button. It sends `POST /api/todos` with `text`, `minutes` (default 25) and only the fields that were given. `area` falls back to the current area filter. Then it empties the box, reloads and refocuses the box.

### Task groups — `renderTasks()`

Tasks are first filtered by `shown()` (the area filter). Then:

| Group | Holds | Order | Notes |
|---|---|---|---|
| Carried over | open, `due < today` | `byStar` | class `carried`; text "Not late. Just waiting." |
| Today | open, `due === today` | `byStar` | class `is-today`; a progress bar `div.plan-meter`; `questRow()` and `reviewRow()` come first |
| Next 7 days | open, `today < due <= today + 7` | by day | |
| Later | open, `due > today + 7` | by day | |
| Anytime | open, no day | `byStar` | |
| Done today | `done_at` set | as loaded | class `done` |

`byStar` sorts starred tasks first, then by time of day; tasks with no time go last. `group()` returns `null` for an empty group with no hint, so only Today always shows.

**The nudge.** When Today holds more than 5 tasks, a `div.plan-nudge` offers "Keep 3, move the rest to tomorrow". It patches every task after the third (in `byStar` order) to tomorrow, all at once with `Promise.all`, then reloads.

**Area chips** — `areaChips()`: an "All" chip and one chip per area in `data.areas` (the server sends the 20 most used). Clicking the active one clears the filter. Returns `null` when there are no areas.

### The goal-step row and the review row

- `questRow()` — shown at the top of Today when `data.quest_step` exists, it is not already in the plan (`in_plan`), and no area filter is on. It is a `li.task.quest-step` with a link to the goal, a "▶ Start" link to `#/focus/<stepId>`, and "+ Today". "+ Today" sends `POST /api/todos` with `link_type: "step"`, `link_id` and `due: today`. After that the server reports `in_plan: true` and the row goes away; the step is now a normal task.
- `reviewRow()` — shown when `data.review_due > 0` and no area filter is on. It only links to `#/review`.

### Task row — `taskRow(t)`

`li.task` with the classes `is-done`, `is-active` (being timed) and `is-star` as they apply. It has three parts.

**1. The tick** (`button.task-check`). `PATCH /api/todos/<id> { done: !done }`, then reload. On the server, finishing a repeating task creates the next one, and finishing a task linked to a goal step finishes the step (`api_todo_patch` in `timer.py`). Toasts: "It comes back …" for a repeating task; "Today is clear" when it was the last open task for today.

**2. The main part** (`div.task-main`): the title, the chips, and the small-steps box when open.

- The title is a button; clicking it opens `editTask(t)`.
- Chips (`div.task-chips`):

| Chip | When | Clickable |
|---|---|---|
| day (`tchip due`, plus `carried`) | has a day and is not done | no |
| `⏰ time` | has a time and is not done | no |
| `↻ repeat` | repeats | no |
| area (`tchip area`) | has an area | yes: filters by that area |
| minutes (`tchip quiet`) | always; shows "spent / planned" after one minute spent | no |
| `↗ open` (`tchip link`) | linked to something (`linkHref`) | yes: a link |
| `✎ note` | has a note (the note is the tooltip) | no |
| `☰ steps` or `☰ done/total` (`tchip steps`) | not done | yes: opens or closes the small steps |

**3. The actions** (`div.task-actions`), for an open task:

| Button | Does |
|---|---|
| ☆ / ★ | `patch(t, { priority: 0 or 1 })` |
| ▶ / ● | `timer.start({ kind: "focus", minutes: <minutes left>, todo_id })`. Minutes left is planned minus spent, at least 1. Does nothing while this task is being timed. |
| Today | on a carried-over task, or a task for a later day: `patch(t, { due: today })` |
| Tomorrow | on a task with no day, for today or carried over: `patch(t, { due: today + 1 })` |
| ✕ | `DELETE /api/todos/<id>`, reload, and a 6-second toast with "Undo" → `POST /api/todos/<id>/restore` |

A done task has only ✕.

**Edit dialog** — `editTask(t)`. A `modal()` with these fields:

| Field | Control | Sent as |
|---|---|---|
| Task | text | `text` (empty text cancels the save, silently) |
| Day | date | `due`, or `clear_due: true` when empty |
| Time | time | `at` (empty string clears it) |
| Repeat | select of `REPEAT_CHOICES`, plus the task's own rule if it is not in the list | `repeat_rule` |
| Area | text with a `datalist` of known areas | `area` |
| Minutes | number 1–600 | `minutes` (left out if not in range) |
| Note | textarea | `note` |
| ★ This one matters | checkbox | `priority` |

Enter in the Task field saves. Everything goes in one `PATCH`.

**Small steps** — `itemsBox(t)`. Shown when the task id is in `openItems`. Each step has a tick (`PATCH /api/todos/<id>/items/<itemId> { done }`) and a remove button (`DELETE` on the same address). An input (`.task-items-add`, with `data-id`) adds a step on Enter (`POST /api/todos/<id>/items`). All three responses are the full task, applied with `setTask`. The server allows 20 steps per task; a refused add shows the server's message as a toast. Ticking the last open step shows a toast but does not finish the task.

### The week board — `renderWeek()`

Layout: `div.wk` holds a tray (`section.wk-tray`, "No day yet") and `div.wk-board` with seven columns (`section.wk-col`), today first.

- **Tray**: open tasks with no day **or with a past day** (carried-over tasks sit here). It also says how many tasks lie after the seven days.
- **Column** — `column(day, i)`: a head with the name, date and load ("3 · 1 h 20"), a list of cards, a note "A full day. Something can move." when the planned minutes pass 300, and an add box (`.wk-add`, with `data-day`). The add box uses `parseQuick` but always sets `due` to the column's day, whatever `@day` says. Today's column starts with `questRowSmall()`, a goal-step card that links to the focus page.
- **Card** — `card(t, day)`: `li.wk-card` with a tick, the title (opens `editTask`), small chips, and move buttons.

**Drag and drop.** It uses the browser's own drag events; there is no library.

- A card has `draggable="true"`. On `dragstart` it stores the task id with `dataTransfer.setData("text/plain", id)` and gets the class `is-drag`.
- `zone(el, due)` makes a column or the tray a drop target. `dragover` calls `preventDefault()` (this is what allows a drop) and adds `is-over`. `dragleave` removes it only when the pointer has really left the element. `drop` reads the id and calls `move(id, due)`.
- `move(id, due)` does nothing if the day is unchanged. Otherwise it patches `{ due }`, or `{ clear_due: true }` for the tray, and reloads.
- You can move a task between days. You cannot reorder cards inside a day.

**Keyboard alternative.** Each card has `‹` and `›` buttons (`div.wk-move`): a day earlier (only for days after today), a day later, and from the tray `›` puts the task on today.

### Routines

Shown in the list view by `renderRoutines()` (`aside.plan-routines`). With no routines it shows three starter chips (`STARTERS`); one click creates that routine with `POST /api/routines`.

**Card** — `routineCard(r)`:

- A routine that is not on today (`r.on_today` false) is a one-line card (`div.routine.is-off`): "Rests today · back <day>".
- Otherwise: the head with the count, the weekdays (`daysLabel`), and seven dots for the last seven days (`div.routine-days`; opacity grows with the share done, `off` marks a rest day). Then the steps, each with a tick. Then "Run it, one step at a time".
- `missedYesterday` shows one kind line when yesterday was an "on" day with nothing done, some earlier day had something done, and nothing is done today.

**Tidy** — since 5.2 each routine card has a ✨ (`task-btn ghost`, "Tidy its steps") that opens `tidyRoutineDialog(r, () => reload())` (section 6.2c). A tidy changes the steps in place, so their ticks and history stay.

**Ticking a step** — `checkStep(r, stepId, done)`: `POST /api/routines/<id>/steps/<stepId>/check { done }`. The response is the fresh routine, stored with `setRoutine`.

**Run** — `runRoutine(r)`. A full-screen overlay (`div.modal-back.steady`) that shows one step at a time.

- "Done, next" calls `checkStep` and shows the next open step.
- "Skip" marks the step done **only in the overlay's own copy**. Nothing is saved, so the step is still open on the page.
- A step with minutes shows a countdown (a local `setInterval`, not the app timer) and plays `chime()` once at zero.
- Esc, ✕ or leaving the page (`hashchange`) closes it. Closing re-renders the page.
- Because the overlay has the class `modal-back`, the timer subscription and the N key hold back while it is open.

**Edit dialog** — `editRoutine(r | null)`:

- Name; part of the day (three `button.pick` used as radio buttons: morning, day, evening); weekdays; steps.
- **Weekday picker**: seven toggle buttons (`data-day` 0–6, 0 = Monday), plus two shortcuts, "weekdays" and "every day". No day picked means every day. It is sent as a string of digits, for example `"01234"`.
- **Steps** are one per line in a textarea. `parseSteps` reads `~N` at the end of a line as minutes (at most 240) and drops a leading `-` or `*`.
- For a new routine the three starters can fill the form.
- Save: `PATCH /api/routines/<id>` or `POST /api/routines` with `{ title, slot, weekdays, steps }`. On the server a step whose words did not change keeps its id and history (`_set_steps` in `planner.py`).
- "Delete routine": `DELETE /api/routines/<id>`, then a toast with "Undo" → `POST /api/routines/<id>/restore`.

---

## 6.2b `readplan.ts` — Plan my reading

Milestone 3.1 of `docs/ai/PLAN.md` (Reading plan). The server side is `readhold/readplan.py` (the schedule, no model; chapter 3, section 2b) and `readhold/ai/plan.py` (the model's suggestion; chapter 3, section 7b). One export: `readingPlanDialog(onAdded)`, a wide `modal`. `onAdded` is called after tasks are added or taken back (Plan passes its `reload`).

**Opening.** `GET /api/reading-plan` gives the candidates (unfinished documents with something left), `wpm`, `today`, `last_batch` and `levels`. With no candidate the dialog only says there is nothing left to read, with **Open Documents**.

**The form.**

| Part | What it is |
|---|---|
| `ol.rp-docs` | One row per candidate: a tick box (the first three are ticked; at most `MAX_DOCS` = 20), the title, "about N left" and the document's own deadline, a level `select` (Easy ×0.8, Medium, Hard ×1.4; disabled while unticked), **↑** and **↓**. The order of the list is the reading order |
| Finish by | `input[type=date]`, from today to a year ahead; starts on the soonest document deadline from today on, else in 13 days. The day itself is a reading day |
| Minutes a day for reading | `input[type=number]`, 5 to 600, step 5, starts at 30 |
| Days without reading | Seven toggle buttons (Mon … Sun, 0 = Monday as the server counts); a seventh is refused with a toast |
| What it is for | The goal, up to 200 characters; it goes into the tasks' note and, with AI, to the model |

Every change at once forgets the plan on screen and disables Add (`later()`), then, after 250 ms (`util.debounce`), asks `POST /api/reading-plan/preview` with the form (`body()`). A counter (`seq`) drops an answer that arrives after a newer request. With nothing ticked no request is made. A change to the list (`changed(mine, focusKey)`) draws the list again and gives the focus back to the tick box or level it came from (`data-k`); a change you made yourself (`mine`) also drops `fromAi`, with a line saying the tasks will not say the model suggested them. Ticking another document hides a suggestion made for the old set.

**The preview** (`drawPlan`): one line, either "<time> of reading over N days, finished by <day>. No day holds more than M minutes." or "This does not fit: <time> is left over. It would take N minutes a day, or a later deadline, or fewer documents. Only what fits is added."; the documents with nothing left; one "Does not fit: …" line per unplaced document; then every reading day up to the last one used, with "x of y min", "already planned" or "free", a chip for reading-plan minutes planned before, and its items ("“<title>”: <from> → <to> (continued) · N min").

**Adding.** **Add N tasks to Plan** (disabled while there is no preview or nothing to add; disabled again while it works, so one press is one plan) posts the same form, with `expect` set to the shown plan's `key`, to `/api/reading-plan/apply` (when the plan changed in between the server answers 409, the toast says so and the preview is drawn again), calls `onAdded`, closes the dialog and shows a toast "Added N reading tasks to Plan, each on its day." with **Undo** (`takeBack(batch)`: `POST /api/reading-plan/<batch>/undo`, then a toast "Took back N tasks." and, when some were worked on, that they stay). When the last plan still has open tasks the dialog says so, with **Take that plan back**.

**With AI on** (`aiIsOn()`) the dialog has **Suggest an order with AI** and the line "The model reads each ticked document's size, section titles and opening, never the whole text. It only suggests; code makes the schedule." With fewer than two ticked documents it only shows a toast. Otherwise `POST /api/reading-plan/suggest` with the ticked ids in order, the goal and `fresh`. The button is disabled while it works, and a counter (`askSeq`) drops an older answer that arrives after a newer one. With AI off a line says what AI would add.

`drawSuggestion(s)` draws, in `div.ai-text`: the label "Suggested by the AI model (on this computer)" or the provider's name, and one sentence by `status` (`STATUS`: every reason rests on a passage; some do; none does, "Treat the order as a guess"; each adds "The levels are its estimate"); what was not sent; then per document its title, a chip "<Level> (its estimate)" or "level not given", "Not placed by the model: it follows in your order." or "Nothing left to read.", the reason, and under it either "✓ “<quote>”" or "The model's guess: no passage of the document behind it."; addresses the model wrote, as words; **Ask again** and **Use this order**.

`useSuggestion(s)` changes only the form: the documents in the model's order first (the rest after, as they were), ticked unless nothing is left, with the model's level where it placed the document; `fromAi` is set to the result id, so `apply` labels the tasks. A line under the suggestion says the form was filled in, with **Undo**, which puts back the rows and `fromAi` as they were (an inline line, not a toast, so it never covers the Add button).

Everything a model wrote is drawn with `h()`, which sets text; nothing is HTML. Styles: `.rp-docs`, `.rp-doc`, `.rp-title`, `.rp-days`, `.rp-day-head`, `.rp-warn`, `.rp-unplaced` (in `styles.css`, after the Study notes block), and the shared `.ai-text`, `.study-items`, `.resume-quote`.

---

## 6.2c `tidy.ts` — Tidy (tasks, a routine, a note)

```ts
export function tidyTasksDialog(onChange: () => void): Promise<unknown>
export function tidyNoteDialog(pageId: string, before: () => Promise<void>, after: () => void): Promise<unknown>
export function tidyRoutineDialog(r: Routine, onChange: () => void): Promise<unknown>
```

Milestone 5.2 of the AI plan. The server side is `readhold/tidy.py` (chapter 3, section 7d) and `readhold/ai/tidy.py` (chapter 3, section 7b). Each dialog shows code's hints and fixes first; with AI on (`aiIsOn()` from `explain.ts`) it also has one button that asks a model. Nothing changes until the reader presses **Apply** or **Use**, and each change has Undo. Everything is drawn with `h()`, so a model's words are text.

**Tasks** — `tidyTasksDialog`, from **✨ Tidy tasks** in the Plan header. `load()` reads `GET /api/tidy/tasks` and `draw()` lists each task (`ol.tidy-list`, `li.tidy-item`): its text, minutes and day (`dayLabel`), its hints (`ul.tidy-hints`) or "Clear as it is.", and, when code has a fix, "Fix: “…” · N min · <day>" with **Apply**. With AI on, **Suggestions from the model** sends `POST /api/tidy/suggest {kind: "tasks", fresh}`; the answer's items are kept in a `Map` by task id, a label line says "Suggested by the AI model for N tasks. Nothing changes until you press Use." with `whyLink` and **Ask again**, and each task with a proposal gets `div.ai-text.tidy-model`: "The model: “…”" with its minutes and day, the split as `ol.tidy-split`, `newWords` ("Words you did not write: " and each word in a `mark`, then "(check them: the model may not add facts)"), **Use** and, with a split, **Split into N**.

**`applyTask(id, was, now, extra, onChange)`.** One change at a time: a module-level `busy` flag makes a second press do nothing while one runs. It sends `PATCH /api/todos/<id> {text, minutes, due?}`, then, for a split, one `POST /api/todos` per extra part (its minutes or 25, on the same day as the task). Then a toast, "Task tidied." or "Split into N tasks.", with **Undo**. Undo reads `GET /api/plan` first: when the task is gone or no longer has the text, minutes and day this change gave it, it says "The task changed since. Change it back by hand." and leaves the task; otherwise it sends the old text, minutes and day back (`clear_due` when it had none). In both cases it then deletes the parts the split added. When a step fails half way, the toast says "Done only in part: …" with **Undo what was done**. After each change the dialog reloads the list and drops that task's proposal.

**A note** — `tidyNoteDialog`, from the ✨ in a note's bar (`notes.ts`, chapter 7). `before()` saves what was typed first (the note page flushes its debounced save). It reads the body, then `GET /api/tidy/note/<id>`: when `changed`, "Spacing and list marks, fixed by code:", the new body in `pre.tidy-pre`, and **Apply**; else "Spacing and list marks are tidy already." With AI on, **A rewrite from the model** sends `{kind: "note", id, fresh}` and shows the proposal in `pre.tidy-pre` with `newWords`, "Put back at the end because the model left them out: …" (`restored`), "Much shorter than your note. Words that went missing: …" (`shorter`, `missing_words`), **Use this** and **Ask again**. `use(from, to)` reads the note again and changes it only while it is still `from` ("The note changed since this was proposed. Ask again." otherwise), then closes the dialog, calls `after()` (the page redraws through a `hashchange`) and shows "Note tidied." with Undo, which puts `from` back only while the note is still `to`.

**A routine** — `tidyRoutineDialog`, from the ✨ on a routine's card. It shows "Now:" and the steps, then `GET /api/tidy/routine/<id>`: "Fixed by code:" with the new steps and **Apply**, or "Its steps are tidy already." With AI on, **Steps from the model** sends `{kind: "routine", id, fresh}` and shows the steps with `newWords`, **Use these** and **Ask again**. `use(steps)` sends `POST /api/tidy/routine/<id>/apply {steps, expect: <the steps as the dialog opened>}`: the steps change in place, so their ticks and history stay. A 409 (the routine changed, or the number of steps differs) is shown as a toast. Undo sends the same route with the old steps and `expect` set to the new ones.

Styles: "Part twenty-seven" (`.tidy-list`, `.tidy-item`, `.tidy-hints`, `.tidy-fix`, `.tidy-model`, `.tidy-split`, `.tidy-new mark`, `.tidy-pre`).

Limits: the split's Undo deletes the parts it added even when the task itself changed since, or the parts were edited; a model's proposal cannot be edited in the dialog (use it, then edit the task); nothing tests the front end (checked in the running app with a stand-in model: the hints, fixes, proposals and the new-words line; a routine with another number of steps refused, its ticks kept).

## 6.2d `planchat.ts` — Plan with a model (Plan chat)

```ts
export function planChatDialog(onChange: () => void): Promise<unknown>
```

Milestone 5.3 of the AI plan; the server side is `readhold/ai/chat.py` (chapter 3, section 7b). Opened by **💬 Plan with a model** in the Plan header. With AI off it is a short dialog: add tasks yourself or use *Plan my reading*, and that with AI on a model can draft tasks.

**State.** A module-level `memo` holds the conversation (`turns`) and the last answer while the app is open, so closing and opening the dialog keeps both. `MAX_TURNS` is 12. The minutes a day are kept per viewer in `localStorage` under `readhold.planchat.minutes` (read and written inside `try`; 120 when missing or out of 15 to 720). This is the one use of browser storage in `web/src/` (chapter 4, section 4.14).

**Sending.** A textarea (1,000 characters; Enter sends, Shift+Enter is a new line) and **Send**. `run()` takes the turns so far plus the new message, keeps the last 12 and drops a first turn that is the model's, and sends `POST /api/plan/chat {messages, minutes_a_day}`. Send is disabled while it runs. On success the model's reply (or "(no reply)") joins the turns, the box is emptied and the log (`div.chat-log`, "You: " / "Model: ") and the drafts are drawn again. A failure is the toast "Not sent: …".

**The drafts** — `drawDrafts()`. A box `div.ai-text` with the label "Drafted by the AI model. Each was checked: its day, its minutes and your free time that day. Nothing is added until you press Add." and `whyLink`. One row per draft: a tick box (ticked unless already added), a text box (500 characters), a date box, a minutes box (1 to 600), "Added" for one already added, and its flags as `ul.tidy-hints`; a draft over the day's free time has the class `unchecked`. Then "N drafts were already in your plan, so they are left out." (`already`), "N more were left out: at most 12 at a time." (`dropped`), the answer's `warning`, and **Add the ticked tasks to Plan**.

**Adding.** The button collects the ticked rows that are not added (index, text, day or `null`, minutes) and sends `POST /api/plan/chat/<id>/add {items}`; with nothing ticked it says "Tick the drafts you want to add." The button is disabled while it runs (one click, one batch). The answer's `kept` marks the added drafts; `onChange()` reloads the Plan page; the toast says "Added N tasks to Plan, each noting a model drafted it." with **Undo**, which sends `POST /api/plan/chat/<id>/undo {batch}` for that click's batch, takes the new `kept` (so the drafts can be added again) and says "Took back N." or "Took back N; M you already changed or started stay."

**Start over** clears `memo` and the dialog. Styles: "Part twenty-seven" (`.chat-log`, `.chat-turn`, `.chat-turn.model`) and the list classes of Study notes (`.study-items`) and Tidy (`.tidy-hints`).

Limits: there is no **Ask again** (the same message in the same state asks nothing new); nothing tests the front end (checked in the running app with a stand-in model: the drafts, their flags, Add, Undo, and adding again after Undo).

---

## 6.3 `today.ts` — Plan → Today

```ts
export function stepFor(step: QuestStep, energy: Energy): string
export function startStep(step: QuestStep): void
export async function todayView(root: HTMLElement): Promise<void>
```

### Data

| Call | When | Used for |
|---|---|---|
| `GET /api/today` | at start (and again after closing the day) | the main goal, check-in, energy curve, output, habits, today's log |
| `GET /api/home` | at start | the resume point, due cards, streak, open confusions |
| `GET /api/plan` | at start, not awaited | the plan-peek line |

The page is `planHead("today")` followed by `section.today`. `render()` clears the section and appends the blocks in this order: `header()`, `methodHint()` (only when `t.empty_streak >= 3`), `questCard()` or `noQuest()`, `planPeek()`, `sideCheck()`, `habitsCard()`, `tiles()`, `closeDay()`, `readingRow()`. Then it focuses the element marked `autofocus`, so Enter starts the lead step. All of this runs inside `keepTyped(page, …)` from `util.ts`: if you were typing in a text box on the page (the side-goal box), its text, caret and focus are put back after the redraw, and the focus does not move to Start.

### Energy check-in — `header()`

Three buttons (`div.seg.energy-seg`): Low, Medium, High. Since 5.1, when there is a check-in today, a ✕ (`button.link.small.checkin-remove`, "Remove this check-in (an earlier one from today counts again)") follows them: `removeCheckin()` calls `removeItem("checkin", id, …)` (`trash.ts`), and in `gone` and `back` reads `GET /api/today` again, sets `energy` and `state.energy` from the check-in that counts now, applies the theme and renders. A click on an energy sets the local `energy`, sets `state.energy`, calls `applyTheme()`, sends `POST /api/checkins { energy }` through `save()` (which retries), and renders again. The starting value is today's check-in, or `state.energy` if there is none. If there is no check-in yet, a toast asks for one.

### How energy sizes a step

- `stepFor(step, energy)` picks the text: `step.low` on a low day, `step.high` on a high day, `step.title` otherwise. If the low or high text is empty it falls back to the title. `focus.ts` uses it too.
- The minutes shown: on low energy `max(5, round(minutes / 3))`; otherwise the step's minutes.
- `startStep(step)` decides where Start goes: a step with a `document_id` opens the reader (`#/read/<docId>`); any other step opens the focus page (`#/focus/<stepId>`). `quest.ts` uses it too.
- Habits also follow energy: on a low day a habit shows its `tiny` text.

### Main goal card — `questCard(q)`

- A badge "Main goal", the days left (`daysLeft`), a link "Open goal".
- The questions (`ol.quest-questions`). Clicking one opens `askText` with the saved answer. Saving sends `PATCH /api/quest-questions/<id> { answer }`, updates the local objects and renders. A first answer triggers `ambience.moment()`.
- The lead step (`div.lead-step`): the text from `stepFor` (drawn with `mathText`), the minutes, which question it moves, the document it reads, and the Start button. With no open step it shows a link "Add a step".
- A progress bar of questions answered.

With no main goal, `noQuest()` shows a "Continue reading" card (when `home.resume` exists) and a card that links to `#/quest/new`.

### Plan peek — `planPeek()`

One line that links to `#/plan`: how many tasks are for today (carried-over ones count), how many are done, and the first unfinished routine. It returns `null` until `/api/plan` has arrived. When it arrives, the page renders again, but only if the page is still in the document and no modal is open.

### Side-goal check — `sideCheck()`

For "something is pulling at you". The flow:

1. Type the thing and press Enter or "Check".
2. `decide(text)` asks whether it answers one of the main goal's questions and shows chips.
3. Each chip sends `POST /api/side-quests`:

| Chip | Body | After |
|---|---|---|
| "Moves Q*n*" (one per question) | `{ text, decision: "linked", question_id }` | a line of advice |
| "Park it" | `{ text, decision: "parked" }` | `t.parked++`, a line of reassurance |
| "Give it 15 min" | `{ text, decision: "timeboxed", minutes: 15 }` | goes to `#/focus/side?text=…&min=15` |

On the server only a parked one stays open (`resolved = 0`); it then shows in the Goals list under "Parked side goals".

### Habits — `habitsCard()`

- Tick: `POST /api/habits/<id>/check` with no body. The server toggles today's check and returns the habit; the page copies it over the old object.
- Each row shows the anchor, the streak, "missed yesterday: don't miss twice" when it applies, and 14 dots (`div.habit-dots`).
- ✕ opens `stopOrDelete(hb)`, a dialog "Stop tracking or delete?" with **Cancel**, **Delete** and **Stop tracking** (the default). Stop tracking: `PATCH /api/habits/<id> { archived: true }`, with Undo (`{ archived: false }`, back in its place). Delete (since 5.1): `removeItem("habit", id, …)`; its streak and checks leave Today, the journal and the weekly review, and Undo reads `GET /api/habits` and puts it back where it was.
- "+ Add a habit" opens a dialog with three fields (the habit, "after I…", the tiny version) and sends `POST /api/habits`. "After " is put in front of the anchor if you did not type it.

### Rhythm and output tiles — `tiles()`

Three `div.tile`:

1. **Your rhythm**: nine bars for two-hour slots from 6:00 to 24:00, from `t.energy.hours`. The peak slot has the class `peak`, the current one `now`. While `t.energy.learning` is true the heights are a fixed placeholder pattern, not data. The line below comes from `hardNow(t)`.
2. **Real output today**: answers plus steps done; empty sessions are named.
3. **On the main goal**: the share of focused time spent on the goal; "—" under one minute.

### Close the day — `closeDay()`

A bar with a button (primary after 17:00). The dialog has three fields: did, learned, tomorrow's first step. With a main goal there is a checkbox "Make it tomorrow's lead step" (ticked at first). Saving sends `POST /api/logs { did, learned, next, next_as_lead }`, then fetches `/api/today` again and renders. On the server there is one log per day (saving again updates it), and "next" becomes or marks the lead step (`api_log_save` in `growth.py`). Once closed, the bar shows "Day closed" and an Edit button.

### Bottom row and ambience — `readingRow()`

A row of quiet links (`div.home-quiet`): continue reading, cards due, a letter that is ready, open confusions, parked side goals, the streak.

This function also calls `ambience.update({ progress, answered })` each time the page renders. `progress` is the share of the main goal's questions answered, or the reading progress when there is no goal. `answered` is today's answers plus steps done plus habits ticked. The themed background grows from these numbers.

---

## 6.4 The Timer page — `views/timer.ts` and `web/src/timer.ts`

### The app-wide `timer` object

`web/src/timer.ts` holds the one clock. The server keeps the run, so it survives a reload.

| Member | Purpose |
|---|---|
| `run` | The current `TimerRun`, or `null` |
| `elapsed()`, `shown()`, `progress()` | Time so far; time left (negative when over) or time so far for a stopwatch; 0–1 |
| `over` | A countdown has passed zero |
| `on(fn)` | Subscribe; returns the unsubscribe function |
| `load()` | `GET /api/timer`, then `set(run)` |
| `start(opts)` | `POST /api/timer/start`. The server stops any earlier run first and keeps its time. |
| `pause()`, `resume()`, `toggle()` | `POST /api/timer/<id>/pause` and `/resume` |
| `extend(min)` | `POST /api/timer/<id>/extend?minutes=N` |
| `finish(status)` | `POST /api/timer/<id>/finish`; returns today's numbers and the to-dos |
| `beat()` | `POST /api/timer/<id>/beat` every 15 seconds while running, and on `pagehide` |

While a run is running, one interval fires `emit()` twice a second. All listeners redraw from it. `linkHref(type, id)` says where a linked thing opens; a linked **step** opens `#/home`, not the goal page. `chime()` plays the end sound if `settings.timer_sound` is on. `mountMiniTimer()` builds the small floating timer.

### Layout

`timerView` appends `section.timer-page` with two children:

- `stage` (`div.timer-card`) — the clock. Drawn by `renderStage()`.
- `side` (`aside.todo-panel`) — the to-do list. Drawn by `renderTodos()`.

It loads `timer.load()` (run, to-dos, today's numbers) and `GET /api/timer/links`. If the links call fails, the page works without links.

The ring is an SVG built once with `createElementNS`. `paint()` updates the time text, the ring's `stroke-dashoffset` and the line under the time. A stopwatch's ring goes round once an hour.

### Idle stage (no run)

- A kind switch (`div.seg`): Focus, Break, Stopwatch.
- Presets (`div.presets`): Focus 10, 15, 25, 45, 60; Break 3, 5, 10, 15; none for the stopwatch. Plus a custom number box (1–600). A preset click or a valid custom number sets `minutes` and calls `renderStage()`, so the clock and the Start button ("Start N min") both show it.
- "What will you work on?" (`input.timer-what`), and for focus and stopwatch a link select.
- The Start button, and two checkboxes saved at once with `saveSettings`: `timer_sound` and `timer_rhythm`.

`start()` calls `timer.start({ kind, minutes, label, link_type, link_id })`.

### Linking

- `linkSelect(value, onChange)` builds a `<select>` with three groups from `/api/timer/links`: open steps of the main goal, lectures, documents. The value is `"type:id"`; `splitLink` splits it.
- `linkChip(type, id)` builds the link shown on a run or a to-do (`a.link-chip`). Its title comes from `titleOf`, which looks in the loaded links and falls back to "A goal step", "A lecture" or "A document".
- The timer itself can be linked (the select on the stage), and each new to-do can be linked (the select in the add row).
- When a run is started from a to-do with no link of its own, the server copies the to-do's link (`api_timer_start`).

### Running stage

Kind, label, the link chip, the ring, and the buttons: Pause/Resume, "+5 min" (countdowns only), Done (or "End break"), and Stop (not for a break). A break shows one idea from `BREAK_IDEAS`.

### What happens at the end

There are two separate moments.

**1. The countdown reaches zero.** This is handled in `timer.schedule()`, not on the page. `timer.over` becomes true, `chime()` plays and a toast appears. **The run does not end.** The clock keeps counting with a `+` in front, and the ring gets the class `over`.

**2. You press Done or Stop** — `finish(status)` on the page:

1. `timer.finish(status)` sends the elapsed time. The server ends the run, writes the time on the session, and adds it to the to-do's `spent_ms` (not for a break).
2. The page takes the fresh numbers and to-dos from the response and redraws the list.
3. A toast names the minutes.
4. **Rhythm.** After a focus run ended with Done, if `settings.timer_rhythm` is on, the stage switches to a 5-minute break and a toast offers to start it.

Finishing a timer does **not** tick the to-do. You tick it yourself. Ticking a to-do linked to a goal step finishes the step on the server; the page shows "The goal step is done too."

### To-do list — `renderTodos()` and `todoRow()`

The list is what `/api/timer` sends: open tasks with no day, for today or carried over, then the ones done today. Tasks for later days are only on the Plan page.

| Action | How | API |
|---|---|---|
| Add | text, minutes select (5–90), optional link | `POST /api/todos` (no day, so it is an Anytime task) |
| Tick | the round button | `PATCH /api/todos/<id> { done }` |
| Edit the text | click the text, or Enter on it; Enter or leaving the box saves, Esc cancels | `PATCH /api/todos/<id> { text }` through `save()` |
| Time it | ▶ starts a focus run for the minutes left | `timer.start({ …, todo_id })` |
| Delete | ✕; asks first if it is being timed; toast with Undo | `DELETE /api/todos/<id>`, `POST /api/todos/<id>/restore` |
| Reorder | drag an open task onto another | `PATCH /api/todos/<id> { ord }` |

Reordering drops the dragged task **before** the task it is dropped on. The new `ord` is halfway between the target and the task above it, or the target's `ord - 1`. The list is sorted locally first and saved after.

This list has no small steps, star, day or repeat. Those are on the Plan page ("Plan →" in the head).

**Recent focus sessions** (since 5.1). Under the list, the same `details.recent-focus` element on every redraw (so it stays open or closed). When it opens, `loadRecent()` reads `GET /api/timer/recent` and lists each run (`ul.recent-runs`): its label (or the kind), when, how long, "stopped early" for a stopped run, and ✕ ("Delete: it stops counting in Stamina, the streak and the journal"). ✕ calls `removeItem("focus", id, "Deleted “…”. It no longer counts in Stamina.", …)`; `gone` and `back` reload today's numbers and the to-do list (`freshToday`) and the list. A running timer is refused by the server (409, shown as "Not deleted: …"). With none: "No focus sessions in the last two weeks."

### Shared state with the mini timer

The page and the mini timer hold no state of their own about the run. Both read `timer.run` and subscribe with `timer.on`.

- The page's listener builds a key from the run's id, running flag and planned time. When the key changes it redraws the stage and the list. When it does not, it only calls `paint()`.
- When the run ends anywhere (the key becomes empty), the page fetches `/api/timer` again for fresh numbers.
- `mountMiniTimer()` hides its pill on `#/timer` and shows it on every other page. It also writes the time into the window title.
- `main.ts` calls `timer.load()` at boot unless the app opens on `#/timer`, where `timerView` does it.

---

## 6.5 `quest.ts` — Study → Goals

```ts
export async function questView(root: HTMLElement, id: string | undefined): Promise<void>
```

`questView` picks one of three screens: no id → `questList`; `"new"` → `questNew`; otherwise it loads four things at once and calls `questEdit`.

### List — `questList(root)`

- Loads `GET /api/quests` and `GET /api/side-quests`.
- Head: `libraryHead("goals", <"New main goal" button>)`. This is the only screen in the file with the tab header.
- Each goal: a link, a badge (Active, Parked, Done), and for a parked one "Make it the main goal" → `PATCH /api/quests/<id> { status: "active" }`, then `#/home`. The server parks the goal that was active.
- "Parked side goals": each with "Clear" → `PATCH /api/side-quests/<id> {}`. The server marks it resolved. The row is removed from the page directly. Since 5.1 each also has ✕ (`deleteSideButton`): `removeItem("side_quest", …)`, and the list is drawn again on delete and on Undo.
- Since 5.1 each goal has ✕: `deleteGoal(id, title, again)` asks first ("Delete this goal?": its questions, steps and topic map leave Readhold; you can undo it right after), then `removeItem("quest", …)`; the list is drawn again, and again on Undo. A goal restored while another became the main one comes back parked (the server's rule).

### New goal — `questNew(root)`

Fields: the goal, why it matters, what done looks like, an optional deadline, and question inputs (three to start; "+ Add a question" adds more). An empty title shows an inline error. "Set main goal" sends `POST /api/quests { title, why, done_looks_like, deadline, questions }` and goes to `#/quest/<newId>`. Cancel goes to `#/home`.

### Goal page — `questEdit(root, q, docs, map, logs)`

Loaded once: `GET /api/quests/<id>`, `GET /api/documents`, `GET /api/quests/<id>/map`, `GET /api/logs?quest_id=<id>&days=30`.

`reload()` fetches only the goal again, copies it over `q` and renders. The map summary, the logs and the document list stay as first loaded.

The blocks, top to bottom:

**Head.** Badge, "All goals" link, title, a bar of questions answered, and a `<details>` "Goal details" with three inputs made by `field()`: title, why, done looks like. Each saves on `change` with `PATCH /api/quests/<id> { <key>: value }` and a short "Saved" toast. An empty title is not saved.

**Topic map card** — `mapCard()`: a link to `#/map/<id>` with the count of concepts you can explain and "Learn next".

**Questions** — `questionList()`. For each question:

- An answer textarea. On `change` it sends `PATCH /api/quest-questions/<id> { answer }` and reloads. A first answer triggers `ambience.moment()`.
- "Teach it back" → `teachBack(x)`.
- "Remove" → confirm, then `DELETE /api/quest-questions/<id>`.
- "Reading for it": documents whose `quest_question_id` is this question, as links to the reader.
- The last row, "+ Add a question", uses `askText` and `POST /api/quests/<id>/questions { text }`.

**Teach-back dialog** — `teachBack(x)`, two modals in a row:

1. Explain from memory. The saved answer is hidden. An empty explanation is refused.
2. Compare: your explanation beside the saved answer (or a hint to check your notes), and a box for gaps, one per line. When the question already has an answer, there is also a checkbox "Keep this explanation as my answer" (not ticked at first).

Saving sends `POST /api/quest-questions/<id>/teachback { explanation, gaps, replace }`, where `replace` is the checkbox. On the server (`api_teachback` in `growth.py`) each gap becomes a 15-minute step "Fill the gap: …" tied to this question. The explanation is stored as the answer when the question had no answer, or when `replace` is true (it then takes the place of the saved answer). Otherwise the saved answer stays and the explanation is not kept.

The toast afterwards says what happened: with gaps, "N gaps became steps." (plus "Your answer is replaced." when the box was ticked); with no gaps, "Saved as your new answer." (ticked), "No gaps named. Nice." (an answer was saved and the box was not ticked) or "Saved as your answer." (the question had no answer).

**Steps** — `stepList()` and `addStepForm()`.

A step has three sizes: `title` (medium), `low` and `high`. Each row has:

| Control | Does |
|---|---|
| checkbox | `PATCH /api/quest-steps/<id> { done }` |
| ☆ / ★ | `PATCH /api/quest-steps/<id> { lead: !lead }`. The server clears the mark on the other steps. |
| "→ Plan" (open steps) | see below |
| "Start" (open steps of the active goal) | `startStep(s)` from `today.ts` |
| ✕ | confirm, then `DELETE /api/quest-steps/<id>` |

The row has the class `is-lead` when it is `q.lead`. That is the starred step if it is open, else the first open step (`lead_step` in `compass.py`). So a row can be the lead without showing a filled star.

**"→ Plan".** It first asks `GET /api/related?kind=quest&id=<questId>` and stops with a toast if a task with the same text is already there. Otherwise `POST /api/todos { text, minutes, link_type: "step", link_id, due: <today> }`. From then on, ticking the task finishes the step.

**Add a step** form: the medium text, the low and high versions, minutes (default 20), "Moves Q*n*" select, "Read: <document>" select, and a "Lead step" checkbox (ticked when the goal has no open step). `POST /api/quests/<id>/steps`. A step with a document opens the reader when started.

**Daily log** — `logList()`: the last 30 days of logs for this goal, drawn by `logList` from `logs.ts`.

**Connected** — `connectedCard("quest", q.id, q.title)` from `related.ts`. It loads `/api/related` by itself.

**Parked side goals** (when the goal has any): "Make it a step" → `addStepFrom` (`POST /api/quests/<id>/steps { title, minutes: 20, lead: false }`, then `PATCH /api/side-quests/<id> {}`), and "Clear".

**Park and finish.**

- An active goal: "Park this goal" → `PATCH /api/quests/<id> { status: "parked" }`, then `#/home`.
- A goal that is not active: "Make it the main goal" → `{ status: "active" }`.
- "Finish goal": asks first if some questions have no answer, then `{ status: "done" }`, `ambience.moment()`, a toast, and `#/home`.
- "Delete goal" (since 5.1, `button.quest-delete`, at the left of the row): `deleteGoal` asks first, deletes with `removeItem("quest", …)` and goes to `#/quest`; Undo goes back to `#/quest/<id>`.

The parked side goals of a goal page have the same ✕ as the list (`deleteSideButton`).

## 6.6 `map.ts` — a goal's topic map

```ts
export async function mapView(root: HTMLElement, questId: string): Promise<() => void>
```

Loads `GET /api/quests/<id>` (for the title) and `GET /api/quests/<id>/map`. Every write route returns the whole map again, so the page uses one pattern: `call(promise)` awaits it, stores the result with `set(map)` and renders; an error becomes a toast.

**The data** (`topic_map` in `growth.py`):

- A **node** is a concept: `name`, `status`, `needs` (ids), `depth`, `ready`.
- An **edge** `from_id → to_id` means "to needs from".
- `depth` is 0 for a concept that needs nothing, else one more than its deepest need.
- `ready` is true when everything it needs is `solid`.
- `next` ("learn next") is the first concept that is not solid and is ready; shaky ones before new ones, shallow before deep.

**Rating.** Each node has a `button.status-chip`. A click moves the status round: `new` → `shaky` → `solid` → `new` (`PATCH /api/map-nodes/<id> { status }`).

**Node card** — `nodeCard(n)`: `div.map-node` with the status as a class, `next` when it is the one to learn next, and `blocked` when not ready. It has the name, ✕ (confirm, then `DELETE /api/map-nodes/<id>`; the server removes its edges too), the status chip, a "Needs: …" line and "+ Needs…".

**Removing a need** (since 5.1). Each "needs" link is a chip (`span.map-need`, from `needChip`) with the name of the concept it needs and a ✕ (`button.map-need-x`, "Remove this link"): `removeItem("map_edge", edge.id, "Removed the link: “…” no longer needs “…”.", …)`; the map is fetched again on delete and on Undo. The two concepts stay. Undo is refused when a concept is gone or the link would now make a loop.

**Adding needs** — `pickNeeds(title, exclude)` is a modal with one toggle chip per other concept. "+ Needs…" then sends one `POST /api/quests/<id>/map/edges { from_id, to_id }` per chosen concept. The server refuses a loop with a 409, which shows as a toast.

**Learn next** — `nextCard()`: the name, a reason, and two buttons. "Make it a step" sends `POST /api/quests/<id>/steps` with a title "Learn: <name>" and ready-made low and high versions. "I can explain it" sets the node to `solid`.

**Add form** — `addForm()`: a name box (Enter adds), "Needs…" (picks prerequisites before adding), "Add concept" (`POST /api/quests/<id>/map/nodes { name, needs }`), and "Fill from my reading".

**Seeding from documents.** "Fill from my reading" sends `POST /api/quests/<id>/map/seed`. The server takes up to 12 saved terms from the documents this goal reads (documents tied to one of its questions or to one of its steps), skips names already on the map, and returns the map with `added`.

**The board.**

- `render()` fills `div.map-board` with one `div.map-col` per depth. The column heads come from `COLUMN`: "Foundations", "Builds on those", then "Then".
- The lines are an SVG (`svg.map-lines`) laid over the board. `drawLines()` runs in `requestAnimationFrame` after each render, so the cards have their final place. For each edge it finds the two cards by `data-id`, measures them with `getBoundingClientRect`, and draws a curved `path` from the right edge of one to the left edge of the other. A line from a solid concept gets the class `solid`.
- Lines are drawn again on window resize and when the board scrolls.

## 6.7 `logs.ts`

Two exports. `fmtDay(day, long)` formats a `YYYY-MM-DD` day. `logList(logs, long)` builds `ul.log-list`, one item per day with "Did", "Learned" and "Next" lines; an empty line is left out. It is used by the goal page here and by the weekly review in `misc.ts`.

## 6.8 `libtabs.ts` — the shared tab header

```ts
export function planHead(active: PlanTab, ...tools): HTMLElement      // "tasks" | "today"
export function libraryHead(active: LibTab, ...tools): HTMLElement    // "documents" | "study" | "goals" | "review" | "glossary"
export function notesHead(active: NotesTab, ...tools): HTMLElement    // "notes" | "journal" | "ideas" | "think"
```

All three call the private `tabHead(title, about, tabs, active, load, tools)`. It builds `header.isle.lib-head` with:

- an `h1` (Plan, Study or Notes);
- `nav.lib-tabs`, one plain link per tab; the active one has the class `on` and `aria-current="page"`;
- `div.lib-tools` holding any extra elements the caller passed.

The tabs are ordinary links to the old addresses. There is no tab state: clicking one is a normal route change.

**Counts.** Each tab has a hidden `span.lib-count`. After the header is built, `load()` fetches the numbers. A tab with a number above zero shows it, with a tooltip. `is-due` is added when the count wants attention (Review, Think). If the request fails, the tabs simply have no numbers.

| Head | Counts from | Numbers shown |
|---|---|---|
| `planHead` | `GET /api/plan/counts` | Tasks: `tasks_now` |
| `libraryHead` | `GET /api/library/counts` | all five tabs |
| `notesHead` | `GET /api/notes/counts` | All notes, Ideas, Think |

In `LibTab`, the id `study` is the tab labelled **Lectures**, and `documents` is the tab labelled Documents.

How the pages in this chapter use it:

| Page | Call |
|---|---|
| `plan.ts` | `planHead("tasks")`, appended before the page and replaced on every render |
| `today.ts` | `planHead("today")`, built once |
| `quest.ts`, list only | `libraryHead("goals", <button>)` |
| goal page, new-goal page, `map.ts`, `timer.ts`, `hub.ts` | no tab header |

---

## 6.9 API endpoints these files call

| Method and path | Called from |
|---|---|
| `GET /api/hub` | `hub.ts`: `hubView`, `reload` |
| `GET /api/think?day=` | `hub.ts`: `hubView` |
| `POST /api/pages/capture` | `hub.ts`: `notesCard` |
| `POST /api/ideas` | `hub.ts`: `notesCard` |
| `PUT /api/settings` (through `saveSettings`) | `hub.ts`: `head`; `timer.ts`: `renderStage` |
| `GET /api/plan` | `plan.ts`: `planView`, `reload`; `today.ts`: `todayView` |
| `GET /api/plan/counts` | `libtabs.ts`: `planHead` |
| `GET /api/library/counts` | `libtabs.ts`: `libraryHead` |
| `GET /api/notes/counts` | `libtabs.ts`: `notesHead` |
| `POST /api/todos` | `hub.ts`: `tasksPart`; `plan.ts`: `quickAdd`, `questRow`, `renderWeek` (column add); `timer.ts`: `renderTodos`; `quest.ts`: `stepList` |
| `PATCH /api/todos/<id>` | `hub.ts`: `tasksPart`; `plan.ts`: `patch`, `taskRow`, `renderTasks` (nudge), `renderWeek`; `timer.ts`: `todoRow` |
| `DELETE /api/todos/<id>` | `plan.ts`: `taskRow`; `timer.ts`: `todoRow` |
| `POST /api/todos/<id>/restore` | `plan.ts`: `taskRow`; `timer.ts`: `todoRow` |
| `POST /api/todos/<id>/items` | `plan.ts`: `itemsBox` |
| `PATCH /api/todos/<id>/items/<itemId>` | `plan.ts`: `itemsBox` |
| `DELETE /api/todos/<id>/items/<itemId>` | `plan.ts`: `itemsBox` |
| `POST /api/routines` | `plan.ts`: `editRoutine`, `renderRoutines` (starters) |
| `PATCH /api/routines/<id>` | `plan.ts`: `editRoutine` |
| `DELETE /api/routines/<id>` | `plan.ts`: `editRoutine` |
| `POST /api/routines/<id>/restore` | `plan.ts`: `editRoutine` |
| `POST /api/routines/<id>/steps/<stepId>/check` | `plan.ts`: `checkStep`; `hub.ts`: `routineCard` |
| `GET /api/timer` | `web/src/timer.ts`: `timer.load`; `timer.ts`: timer listener |
| `GET /api/timer/links` | `timer.ts`: `timerView` |
| `POST /api/timer/start` | `timer.start`, used by `hub.ts`, `plan.ts`, `timer.ts` |
| `POST /api/timer/<id>/pause`, `/resume` | `timer.toggle`, used by `hub.ts`, `timer.ts`, the mini timer |
| `POST /api/timer/<id>/extend?minutes=` | `timer.extend`, used by `timer.ts` |
| `POST /api/timer/<id>/finish` | `timer.finish`, used by `timer.ts` |
| `POST /api/timer/<id>/beat` | `timer.beat` |
| `GET /api/today` | `today.ts`: `todayView`, `closeDay` |
| `GET /api/home` | `today.ts`: `todayView` |
| `POST /api/checkins` | `today.ts`: `header` |
| `POST /api/side-quests` | `today.ts`: `sideCheck` |
| `GET /api/side-quests` | `quest.ts`: `questList` |
| `PATCH /api/side-quests/<id>` | `quest.ts`: `questList`, `questEdit`, `addStepFrom` |
| `POST /api/habits` | `today.ts`: `habitsCard` |
| `PATCH /api/habits/<id>` | `today.ts`: `habitsCard` |
| `POST /api/habits/<id>/check` | `today.ts`: `habitsCard` |
| `POST /api/logs` | `today.ts`: `closeDay` |
| `GET /api/logs?quest_id=&days=30` | `quest.ts`: `questView` |
| `GET /api/quests` | `quest.ts`: `questList` |
| `POST /api/quests` | `quest.ts`: `questNew` |
| `GET /api/quests/<id>` | `quest.ts`: `questView`, `reload`; `map.ts`: `mapView` |
| `PATCH /api/quests/<id>` | `quest.ts`: `questList`, `field`, park/finish buttons |
| `POST /api/quests/<id>/questions` | `quest.ts`: `questionList` |
| `PATCH /api/quest-questions/<id>` | `quest.ts`: `questionList`; `today.ts`: `questCard` |
| `DELETE /api/quest-questions/<id>` | `quest.ts`: `questionList` |
| `POST /api/quest-questions/<id>/teachback` | `quest.ts`: `teachBack` |
| `POST /api/quests/<id>/steps` | `quest.ts`: `addStepForm`, `addStepFrom`; `map.ts`: `nextCard` |
| `PATCH /api/quest-steps/<id>` | `quest.ts`: `stepList` |
| `DELETE /api/quest-steps/<id>` | `quest.ts`: `stepList` |
| `GET /api/documents` | `quest.ts`: `questView` |
| `GET /api/related?kind=quest&id=` | `quest.ts`: `stepList` ("→ Plan"); `connectedCard` |
| `GET /api/quests/<id>/map` | `quest.ts`: `questView`; `map.ts`: `mapView` |
| `POST /api/quests/<id>/map/nodes` | `map.ts`: `addForm` |
| `POST /api/quests/<id>/map/edges` | `map.ts`: `nodeCard` |
| `POST /api/quests/<id>/map/seed` | `map.ts`: `addForm` |
| `PATCH /api/map-nodes/<id>` | `map.ts`: `nodeCard`, `nextCard` |
| `DELETE /api/map-nodes/<id>` | `map.ts`: `nodeCard` |
| `DELETE /api/items/<kind>/<id>`, `POST /api/items/<kind>/<id>/restore` | `removeItem` (`web/src/trash.ts`, milestone 5.1), used by `today.ts` (`removeCheckin`: `checkin`; `stopOrDelete`: `habit`), `quest.ts` (`deleteGoal`: `quest`; `deleteSideButton`: `side_quest`), `map.ts` (`needChip`: `map_edge`), `timer.ts` (`loadRecent`: `focus`) |
| `GET /api/timer/recent` | `timer.ts`: `loadRecent` (since 5.1) |
| `GET /api/habits` | `today.ts`: the Undo of a deleted habit (since 5.1) |
| `GET /api/tidy/tasks` | `tidy.ts`: `tidyTasksDialog` (`load`) |
| `GET /api/tidy/routine/<id>`, `POST /api/tidy/routine/<id>/apply` | `tidy.ts`: `tidyRoutineDialog` (and its Undo) |
| `GET /api/tidy/note/<id>` | `tidy.ts`: `tidyNoteDialog` (called from `notes.ts`, chapter 7) |
| `POST /api/tidy/suggest` | `tidy.ts`: the model's button and **Ask again** in each of the three dialogs |
| `PATCH /api/todos/<id>`, `POST /api/todos`, `DELETE /api/todos/<id>` (Tidy) | `tidy.ts`: `applyTask` and its Undo |
| `POST /api/plan/chat`, `POST /api/plan/chat/<id>/add`, `POST /api/plan/chat/<id>/undo` | `planchat.ts`: `run`, the Add button, the Undo toast |

Server routes that exist but that none of these files call: `DELETE /api/map-edges/<id>`, `DELETE /api/quests/<id>`, `DELETE /api/habits/<id>` (since 5.1 the pages delete through `/api/items/…`, whose restore also undoes these), `GET /api/quest/active`.

## 6.10 Keyboard shortcuts

Page shortcuts are ignored while you type in a field, while a modal is open, and when Ctrl, Alt or the Meta key is held (`isTyping` in `util.ts`).

| Key | Where | Does |
|---|---|---|
| N | Overview | Focus the task quick box (`.hub-task`) |
| Enter | Overview quick boxes | Add the task, note line or idea |
| N | Plan → Tasks | Focus the quick-add box (`.plan-add-input`) |
| Enter | Plan quick add, a week column's add box, a small-steps box | Add |
| Enter | Edit task dialog, Task field | Save |
| Esc | Routine run | Close |
| Enter | Routine run | Presses the focused "Done, next" button |
| Enter | Today, on load | Presses the focused Start (or Resume, or "Set your main goal") |
| Enter | Today side-goal box | Run the check |
| Ctrl+Enter | Today answer dialog (`askText`, multi-line) | Save |
| Space | Timer page | Pause or resume, when a timer exists |
| Enter | Timer "what will you work on" box | Start |
| Enter | Timer to-do add box | Add |
| Enter on a to-do's text | Timer to-do list | Edit it; Enter saves, Esc cancels |
| Enter | Goal page, step form's first field | Add the step |
| Enter | Topic map name box | Add the concept |
| Esc | Any `modal()` | Close without saving |
| Ctrl+K, Ctrl+J | Everywhere (`main.ts`) | Find; capture a thought |

## 6.11 Rules and gotchas

**Text is always a text node.** Every string from the database goes through `h()` as a child, which makes a text node. None of these files uses `innerHTML`. Step titles and saved answers that may hold LaTeX go through `mathText()` (`today.ts`, `quest.ts`), which builds nodes too. The two SVGs (the timer ring, the map lines) are built with `createElementNS` and hold no user text.

**Saving happens at the action.** There is no Save button on a page and no debounce in these files. A tick, a drop, Enter in a quick box or a `change` on a field sends its request at once. Dialogs save when you press their button. `save()` from `api.ts` (which retries three times) is used for the energy check-in, side-goal choices, the to-do text edit and the reorder; the rest use `api.*` directly, and a failure surfaces as the global error toast from `main.ts`.

**Quest means goal.** The code, the tables, the routes and the addresses say *quest*; the app says *goal*. `side_quests` are "side goals". The file `today.ts` is the Today tab, served by `compass.py`, at the address `#/home`. The menu id for Study is `library`, and the tab id `study` is the Lectures tab. Keep the code names when you add code, and the app names in anything the user reads.

**A re-render replaces every element.** All these pages rebuild their DOM from data. On the Overview, Plan and Today, `render()` runs inside `keepTyped(root, draw)` from `util.ts`, which keeps what is half-typed. Before the redraw it notes every `input[type="text"]` and `textarea` under the root whose text differs from what the page drew into it, or that has the focus. After the redraw it writes the text back (and fires an `input` event), and gives the focus and the caret back. A box is found again by its tag, its class, its `data-id` / `data-day` and its `aria-label`; boxes that share all of these are told apart by their order. If the box is not on the new page (its task was ticked, for example), its text is dropped. Number, date and select controls are not covered. The other pages here do not use `keepTyped`. Places to watch:

- *Plan.* The quick-add box, a small-steps box and a week column's add box keep their text, caret and focus when a render comes from elsewhere, for example when the timer starts or ends and the listener reloads. A new text box on this page needs a class (and a `data-id` or `data-day` when there is one per task or day) so it can be found again.
- *Overview.* The quick boxes keep their text when the Think data arrives (a second render shortly after load) or when a timer starts or ends. `reload(focus)` still sets the focus after a box's own action.
- *Today.* Every `render()` focuses the `autofocus` element, so after a habit tick or an energy change (a button had the focus) the focus jumps to Start. If the focus was in the side-goal box, `keepTyped` gives it back, and the late `/api/plan` render keeps the text typed there.
- *Goal page.* An answer textarea saves on `change`, which fires when you leave it, and then reloads the page. If you click from one answer straight into another field, that field is rebuilt under you and loses the focus. Text in the "Add a step" form is lost on any reload.
- Renders from timer events are held back while a `.modal-back` element exists, so dialogs are safe.

**Tasks typed in different places land in different groups.** Overview: today. Plan quick add: Anytime, unless a day is written. A week column: that column's day, whatever is written. Timer page: Anytime.

**The focus link for a goal step differs by page.** `startStep()` (Today, goal page) opens the reader for a step with a document. The Overview and the Plan step row link straight to `#/focus/<stepId>`; the data they get has no `document_id`.

**The check-in label does not update.** In `today.ts` the header reads `t.checkin` to choose between "Energy" and "How's your energy?". Tapping a level does not set `t.checkin`, so the question stays until the page is opened again. Each tap also inserts a new check-in row.

**The custom minutes box on the Timer page redraws the stage.** Its `change` handler calls `renderStage()`, not only `paint()`, because the Start button's text names the minutes. A number outside 1–600 is ignored.

**The timer link select is not cleared after Start.** `start()` in `timer.ts` resets `label`, but `link` keeps its value for the next run.

**Minutes for a focus run on a task.** In `plan.ts` (`taskRow`) and `timer.ts` (`todoRow`) they are `Math.max(1, Math.round(minutes - spent_ms / 60_000))`: the minutes left, never less than 1, also when more time was spent than planned.

**`questRowSmall()` is built twice** per render in the week view (once for the test, once for the list). It is harmless.

**Routine "Skip" saves nothing.** By design; the step stays open on the page.

**Timer reorder limits.** A to-do can be dropped before another, never after the last one. When a task is dropped on the one just below it, its new `ord` is the target's minus 1, which is only right while the neighbours' `ord` values are at least 1 apart.

**"Make it a step" on the topic map does not check for a copy.** Pressing it twice adds two "Learn: …" steps. The map page also does not reload after it.

**There is no way to remove one "needs" line** in the map page; the route exists but the page does not call it. Removing the concept removes its lines.

**A teach-back explanation replaces a saved answer only when asked.** For an unanswered question it becomes the answer. For an answered one it is kept only when "Keep this explanation as my answer" is ticked (`replace`); otherwise only the gaps are saved (as steps).

**`todayView` and `questView` return no cleanup.** They add no global listeners, so nothing leaks. The late `/api/plan` promise in `today.ts` checks `page.isConnected` before it renders.

**`mapView`'s cleanup removes the window `resize` listener only.** The scroll listener is on the board element and goes away with it.

**Declaration order in `plan.ts`.** `REPEAT_WORDS` is declared below `parseQuick`, and `lastTimed` below the `timer.on` callback that reads it. Both work because the code runs later than the declaration. Do not call either earlier during module or page set-up.

**Deletes go through `removeItem`** (milestone 5.1). A page never calls `/api/items/…` itself: `removeItem` (`web/src/trash.ts`) deletes, shows the Undo toast and calls the page's `gone` and `back`. A page redraws in both, from the server when what it shows depends on what is left (the check-in, the Timer's recent list and today's numbers, the map); it never assumes the restore worked.

**The check-in ✕ follows `t.checkin`.** Like the label above, it uses `t.checkin` as it was when the page loaded (or after a delete or Undo), and a tap on an energy does not update it. So the first tap of the day shows no ✕ until the next load, and after a later tap the ✕ removes the check-in that was current at load, not the tap just made (its toast names that older energy).

**Tidy and Plan chat change nothing on their own.** Every change goes through the page's own call (a task patch, a note patch, the routine apply, the chat add), after the reader's press, and each has Undo. A model's text is drawn with `h()`; nothing it wrote is used as markup, a link or an address.

**Plan chat keeps one setting in `localStorage`** (the minutes a day). It is the only use of browser storage in `web/src/`; every read and write is inside `try`, and the dialog works without it.
