# 4. Front-end core, styles and themes

This chapter covers everything in `web/src/` that is not a page: boot and routing, the DOM helpers, the API wrapper (with `trash.ts`, the delete and Undo of milestone 5.1), themes and the animated background, math, the pacer, the timer, the two global dialogs (Ctrl+K and Ctrl+J), the corner dock, ink, the shared tab header, the stylesheet and the `themes/` folder. Pages (`web/src/views/*`) are covered in other chapters; they are mentioned here only where they call into the core.

Names follow the code. In the app, `hub` is "Overview", menu id `library` is "Study", `quest` is "Goals", `home` is the "Today" tab of Plan, `stats` is "Stamina".

## 4.1 How the front end is put together

There is no framework. Every page is a function that builds DOM nodes with one helper, `h()` (`util.ts`), and appends them to `<div id="app">`. State lives in three places: the server (the truth), a small `state` object (`state.ts`), and module-level variables in the files that need them (for example the `timer` object).

`web/static/index.html` is the whole shell:

- three stylesheets, all local: `/static/fonts.css`, `/static/katex/katex.min.css`, `/static/styles.css`;
- `<div id="app">`, where the router draws;
- `<div id="toasts" aria-live="polite">`, where `toast()` appends;
- one script: `<script type="module" src="/static/app.js">`.

There are no inline scripts and no remote URLs. The server's CSP (`CSP` in `readhold/server.py`) is `script-src 'self'`, `style-src 'self' 'unsafe-inline'`, `connect-src 'self'`, `img-src 'self' data:`, `font-src 'self'`, `object-src 'none'`. Inline styles are allowed (the `style` object in `h()` and KaTeX need them). Inline scripts and any other origin are not.

### Build

`web/package.json` has three scripts:

| Script | What it runs |
|---|---|
| `build` | `node scripts/copy-fonts.mjs`, then `tsc --noEmit`, then `esbuild src/main.ts --bundle --format=esm --target=es2022 --minify --sourcemap --outfile=static/app.js` |
| `watch` | the same esbuild call with `--watch`, no minify, no type check, no font copy |
| `typecheck` | `tsc --noEmit` |

- esbuild makes one file, `web/static/app.js` (plus `app.js.map`). TypeScript only checks types; it emits nothing.
- `web/tsconfig.json`: `strict`, `noUnusedLocals`, `noImplicitReturns`, `isolatedModules`, `moduleResolution: "Bundler"`, target and lib ES2022 plus DOM. `noUnusedLocals` is why a few files contain `void state;` (an import kept alive).
- `web/scripts/copy-fonts.mjs` copies the `@fontsource` woff2 files (Atkinson Hyperlegible, Literata, OpenDyslexic, and since 2026-11-26 Bangers and Dela Gothic One, 400 normal only, for the comics themes' headings; latin subsets) into `static/fonts/`, generates `static/fonts.css` with the `@font-face` rules, and copies `katex.min.css` and KaTeX's woff2 fonts into `static/katex/`. It uses paths relative to `web/`, so run it from there.
- All dependencies are `devDependencies` with exact versions: `esbuild` 0.25.12, `typescript` 5.7.3, `katex` 0.18.9, and five `@fontsource/*` packages (`atkinson-hyperlegible` 5.1.1, `literata` 5.1.1, `opendyslexic` 5.1.0, `bangers` 5.3.0, `dela-gothic-one` 5.3.0; all OFL-1.1), locked in `package-lock.json`. KaTeX is the only library bundled into `app.js`. CI (`.github/workflows/ci.yml`) runs `npm ci` and `npm run build` on Node 24, on Windows and Linux; Dependabot proposes npm updates weekly.
- The only code not in the bundle is a theme's `scene.js`, loaded at run time with `import()` from `/themes/<id>/scene.js` (same origin, so the CSP allows it). See 4.6.

## 4.2 Boot and the router (`main.ts`)

### `boot()`

Runs once, at the bottom of `main.ts`.

1. `await loadState()` fetches settings, themes and today's energy. If it throws, a single warning paragraph is appended to `#app` ("Could not reach the Readhold server…") and boot stops.
2. `applyTheme()` sets CSS variables and `data-*` attributes and starts the scene (4.6).
3. `watchSystemTheme()` re-applies the theme when the OS dark-mode or reduce-motion setting changes.
4. `mountMiniTimer()`, `mountPeek()`, `mountReminders()` create the always-present pieces. The first two share one fixed container, `#corner-dock` (each creates it if it is missing).
5. Unless the hash starts with `#/timer`, `timer.load()` fetches a timer left running. (On `#/timer` the timer page loads it itself.)
6. `GET /api/ambience` → `ambience.update({ reviewed })`, so scenes know how many cards were reviewed today.
7. `hashchange` → `route`.
8. One `keydown` listener on `document`: Ctrl/Cmd+K → `openPalette()`, Ctrl/Cmd+J → `openCapture()` (no Shift, no Alt; `preventDefault()` on both).
9. `dragover` and `drop` on `window`: when the drag holds files (`dataTransfer.types` includes `"Files"`), `preventDefault()`. Without this a file dropped anywhere but a drop zone would make the window open it, a page with no CSP and no sandbox (milestone 4.5, finding L4). Drop zones (the Documents tab, the lecture shelf) handle their own drops first; this only stops the window's default. A drag of text or a link is left alone.
10. `pagehide` and `beforeunload` → `flushPending()`.
11. `error` → `toast("Error: …", "error")`, except messages matching `ResizeObserver loop`. `unhandledrejection` → an error toast as well.
12. `visibilitychange` sets `data-hidden="1"` (or `""`) on `<html>`. The stylesheet pauses CSS animations while it is `"1"`.
13. `await route()` draws the first page.

### `route()`

Called on boot and on every `hashchange`.

1. `flushPending()`: debounced saves run now.
2. The previous page's cleanup function runs, if there is one, and is forgotten. Then the call takes a number: `const mine = ++routeSeq`. `routeSeq` is a module-level counter of page changes, so `mine === routeSeq` is true only while this call is the newest one.
3. `clear(app)`, then every `.peek-pop`, `.sel-bar` and `.modal-back` left on the page is removed. Open dialogs do not survive navigation.
4. The hash is parsed:

```ts
const [path, query] = (location.hash.slice(1) || "/hub").split("?");
const params = new URLSearchParams(query ?? "");
const [, view, id, extra] = path.split("/");
```

   So `#/read/abc?s=12` gives `view = "read"`, `id = "abc"`, `params.get("s") = "12"`. An empty hash is Overview.
5. `applyComfort(comfortFor(""))` resets the reading font variables to the global settings (the reader overrides them per source type).
6. `ambience.update({ mode, session: 0 })`, with `mode = "review"` for `review` and `practice`, otherwise `"idle"`.
7. The view is chosen (table below). Everything is inside one `try`; a thrown error is logged and a `.view` with "Something went wrong: …" and a link to Overview is appended. If the call is no longer the newest one (`mine !== routeSeq`), the error is only logged: the message of a page you already left is not added to the page on screen.

Three views get their own layout and return early:

| Hash | Container | Call | Menu |
|---|---|---|---|
| `#/read/<id>` | none (the reader builds its own) | `new Reader().mount(app, id, params, () => mine === routeSeq)` | no menu |
| `#/lecture/<id>` | `div.lecture-root` | `lectureView(main, id)` | `nav("library")` |
| `#/focus/<id>` | `div.view.focus-view` | `focusView(main, id, params)` | no menu |

All others get `nav(PART_OF[view] ?? (view || "hub"))` plus `div.view`:

| Hash | View function | File | Returns cleanup |
|---|---|---|---|
| `#/hub` (and empty, and unknown) | `hubView(main)` | `views/hub.ts` | yes |
| `#/plan` | `planView(main, params)` | `views/plan.ts` | yes |
| `#/home` | `todayView(main)` | `views/today.ts` | no |
| `#/timer` | `timerView(main)` | `views/timer.ts` | yes |
| `#/lectures` | `lecturesView(main)` | `views/lectures.ts` | no |
| `#/library` | `libraryView(main)` | `views/library.ts` | no |
| `#/quest`, `#/quest/<id>` | `questView(main, id)` | `views/quest.ts` | no |
| `#/map/<id>` | `mapView(main, id)` | `views/map.ts` | yes |
| `#/review` | `reviewView(main)` | `views/review.ts` | yes |
| `#/practice` | `practiceView(main)` | `views/practice.ts` | yes |
| `#/glossary` | `glossaryView(main, params)` | `views/misc.ts` | no |
| `#/summary/<id>` | `summaryView(main, id)` | `views/summary.ts` | no |
| `#/structure/<id>` | `structureView(main, id)` | `views/misc.ts` | no |
| `#/notes`, `#/notes/<id>` | `notesView(main, id)` | `views/notes.ts` | yes |
| `#/journal`, `#/journal/<id>` | `journalView(main, id)` | `views/journal.ts` | yes |
| `#/ideas` | `ideasView(main)` | `views/misc.ts` | no |
| `#/think`, `#/think/<id>/<extra>` | `thinkView(main, id, extra)` | `views/think.ts` | yes |
| `#/stats` | `statsView(main)` | `views/misc.ts` | no |
| `#/settings` | `settingsView(main, params)` (`?g=<group id>` scrolls to one group, for example `set-ai`) | `views/misc.ts` | no |

"Returns cleanup" means `route()` passes the result to `keep()` (the three views in the first table do the same). `keep(made)` is a small function inside `route()`: if this call is still the newest (`mine === routeSeq`) it stores `made` in the module variable `cleanup`; if the hash changed while the view was loading, it calls `made()` at once, so the listeners and timers of a page that is no longer on screen are released and not kept. For the "no" rows the result is not passed to `keep()`, so a cleanup returned by those functions would be ignored. `summary`, `structure` and `map` without an id fall through to `hubView`.

The reader also gets the test itself, as the fourth argument of `mount`: a reader whose document arrives after you moved on draws nothing (chapter 5).

For `notes`, `id` can also be a word, not a record id: the palette links to `#/notes/today`, `#/notes/map` and `#/notes/table`.

### `PART_OF`, `HINT`, `nav()`

- `PART_OF` maps a view name to the menu entry that should be lit: `home → plan`; `quest`, `map`, `lectures`, `review`, `glossary`, `practice`, `summary`, `structure → library`; `journal`, `ideas`, `think → notes`. A view not listed lights the entry with its own name.
- `HINT` maps a menu id to the tooltip (`title`) of its link. It has one key for each id that `nav()` passes to `link()`: `hub`, `plan`, `timer`, `library`, `notes`, `stats`, `settings`.
- `nav(active)` builds `<nav class="topnav" aria-label="Main">`:
  - top: the brand link (`#/hub`, `/static/logo.svg`), the "Find…" button (`openPalette`), the "+ Capture" button (`openCapture`), the Overview link;
  - normal mode: three `div.nav-group` blocks with a `span.nav-label`: **Do** (Plan `#/plan`, Timer `#/timer`), **Learn** (Study `#/lectures`, id `library`), **Reflect** (Notes `#/notes`, Stamina `#/stats`);
  - simple mode (`state.settings.simple_mode`): the same five links without groups, and the class `topnav is-simple`;
  - hiding (added on 2026-11-26): `nav()` returns the menu and a `button.nav-show` (☰ Menu); the brand sits in `div.nav-top` beside `button.nav-hide` («). `setNavHidden()` sets `state.settings.nav_hidden`, saves it with `PUT /api/settings`, moves the focus to the other button, and `applyNavHidden()` sets or removes `data-nav="hidden"` on `<html>` (also at start-up). Ctrl+\\ toggles it on pages that have the menu. styles.css Part twenty-nine hides `.topnav`, drops `#app`'s left padding, puts the corner dock back in the corner and shows `.nav-show` top left;
  - foot: a `span.nav-gap` spacer, the AI chip (`aiChip()` from `views/ai-settings.ts`: "AI: Off", "AI: Local" or "AI: Cloud" from `state.settings.ai_mode`, a link to `#/settings?g=set-ai`) and Settings. The chip is in the menu, so the reader and the Focus page, which have no menu, do not show it yet.
  - The active link gets class `on` and `aria-current="page"`. After insertion, `scrollIntoView` keeps it visible (the menu scrolls sideways on a narrow window).

The menu is rebuilt on every route. It holds no state.

### Global keys

| Key | Where it is bound | Does |
|---|---|---|
| Ctrl/Cmd+K | `boot()` in `main.ts` | `openPalette()` |
| Ctrl/Cmd+J | `boot()` in `main.ts` | `openCapture()` |
| V | `mountPeek()` (capture phase) | hides the page to show the scene; only when `<html>` has `data-scene` |
| Esc | `modal()`, `timerMenu()` | closes that surface; with dialogs stacked, only the topmost |

"While typing" is `isTyping(e)` in `util.ts`: the target is content-editable, an `INPUT`, `TEXTAREA` or `SELECT`, **or any `.modal-back` is open**. Page-level keys (the reader, the lecture desk) are bound by those pages.

## 4.3 `util.ts`

### `h()`

```ts
function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...kids: Kid[]): HTMLElementTagNameMap[K]
type Kid = Node | string | number | null | undefined | false | Kid[];
```

Attribute rules, in the order the code checks them:

| Key / value | Effect |
|---|---|
| value is `undefined`, `null` or `false` | skipped (this is how `hidden: false` or a conditional `"aria-current"` works) |
| `class` | `el.className = String(v)` |
| `style` with an object value | `Object.assign(el.style, v)` (camelCase keys) |
| key starts with `on` and value is a function | `addEventListener(key.slice(2), v)`; `onclick` → `"click"`, so the name after `on` must be the lower-case event name |
| `value`, and the element has a `value` property | sets the property |
| `checked` on an `<input>` | sets the property |
| anything else | `setAttribute(k, v === true ? "" : String(v))` |

So `hidden: true`, `disabled: true` and `autofocus: true` become empty attributes; numbers are stringified; `data-*` and `aria-*` go through `setAttribute`. A `style` given as a string also goes through `setAttribute`.

Children go through `append(el, kids)`: arrays are flattened, `null`/`undefined`/`false` are skipped, nodes are appended, and **strings and numbers become text nodes**. There is no way to pass HTML through `h()`.

### Other DOM helpers

```ts
function append(el: Node, kids: Kid[]): void
function clear(el: Element): void                  // removes every child
function isTyping(e: Event): boolean
const prefersReducedMotion: () => boolean
```

### `keepTyped`

```ts
function keepTyped(root: HTMLElement, draw: () => void): void
```

For a page that redraws itself by emptying `root` and building it again (a late answer from the server or a timer event can ask for that at any moment). It keeps what is half-typed:

- Before the redraw it looks at every `input[type="text"]` and `textarea` inside `root`. A box is remembered if it has the focus or if its value differs from the value it was drawn with. That drawn value is kept in the module-level `drawnValue` (a `WeakMap` from element to string; a box not in it counts as drawn empty).
- It calls `draw()`, then records the drawn value of every box now in `root`.
- Each remembered box is matched to a new one by a key: tag name, `class`, `data-id`, `data-day` and `aria-label`, plus a running number for boxes that share all of these. A changed text is put back and an `input` event is dispatched on the box (so a preview under it follows). A box that had the focus gets the focus and the same caret or selection again.
- If no new box has the key (its task was done, its day passed), the text is dropped.

The selector needs the attribute, so an `<input>` without an explicit `type="text"` is not covered. Overview (`views/hub.ts`), Plan (`views/plan.ts`) and Today (`views/today.ts`) wrap their `render` in it.

### `toast`

```ts
function toast(msg: string, kind: "info" | "error" | "ok" = "info", ms = 3500,
               action?: { label: string; run: () => void }): void
```

Appends `div.toast.<kind>` with `role="status"` to `#toasts`. After `ms` it gets class `out` (fade), and 400 ms later it is removed. With `action`, a `button.toast-action` is added; a click removes the toast and calls `run`. This is how Undo and "Open" links are offered.

### `modal` and `ModalHandle`

```ts
interface ModalHandle { close: (value?: unknown) => void; el: HTMLElement }
function modal(title: string, body: Kid,
               opts?: { wide?: boolean; onOpen?: (m: ModalHandle) => void; dismissable?: boolean }): Promise<unknown>
```

- Builds `div.modal-back > div.modal[role=dialog][aria-modal=true]` with an `<h2>` title and the body, appended to `document.body`.
- The promise resolves with whatever `close(value)` is given. Esc and a mouse-down on the backdrop call `close(undefined)`, unless `dismissable === false`.
- The Esc listener is on `document` in the capture phase and stops propagation, so page keys do not also fire.
- **One Esc closes one dialog** (since 4.2). Each open modal has its own listener; on Esc it looks at every `.modal-back` and acts only when its own backdrop is the last one, the topmost. A dialog opened over another (the "Why did it say this?" panel over the Explain dialog, say) closes first; the next Esc closes the one under it. Before, every open dialog closed on one press.
- `close` is idempotent, removes the backdrop and the key listener, and returns focus to the element that had it.
- The body's buttons need the handle to close the dialog. The pattern used everywhere is `let handle: ModalHandle; modal(..., { onOpen: (m) => (handle = m) })`.
- First focus goes to `[autofocus]`, else the first `textarea, input, select, button.primary, button`.
- There is no focus trap in `modal()`.
- `route()` removes every `.modal-back` without calling `close`, so a modal's promise never resolves if the user navigates away while it is open.

### `askText`, `confirmBox`

```ts
function askText(title: string, label: string, initial = "",
                 opts?: { multiline?: boolean; okLabel?: string; placeholder?: string }): Promise<string | null>
function confirmBox(title: string, text: string, okLabel = "OK"): Promise<boolean>
```

`askText` resolves with the trimmed text, or `null` on Cancel, Esc or backdrop. Enter saves in a single-line field; Ctrl+Enter saves in a multiline one. Note that an empty string is a valid result (callers test `if (!name) return`). `confirmBox` resolves `true` only for the OK button.

### `debounce` and `flushPending`

```ts
function debounce<T extends unknown[]>(fn: (...a: T) => void, ms: number): ((...a: T) => void) & { flush: () => void }
function flushPending(): void
```

- A module-level `pending = new Set<() => void>()` holds the `run` function of every debounced call that has been scheduled but has not fired.
- Calling the debounced function stores the latest arguments, restarts the timeout and adds `run` to `pending`.
- `run` clears the timeout, removes itself from `pending` and, if arguments are waiting, calls `fn` with them once. `.flush` is `run`.
- `flushPending()` runs everything in the set. It is called by `route()` first thing, on `pagehide` and `beforeunload` (`boot()`), and by `whereAmI()` in `capture.ts` before it reads the reading position back.

This is the mechanism behind the "no keystroke is lost" rule. It only works for saves made through `debounce()`. A hand-rolled `setTimeout` save is not flushed (`InkPad` has its own `flush()`, called from `destroy()`). Writes started by a flush during unload still need to reach the server; `api.ts` sets `keepalive` on small writes for that reason.

### Formatting helpers and label maps

| Name | Result |
|---|---|
| `fmtMinutes(ms)` | `"12 min"` or `"1 h 5 min"` (rounded to minutes) |
| `fmtClock(ms)` | `"m:ss"`, never negative (minutes are not capped at 59) |
| `HL_LABELS` | highlight type → label (`claim`, `evidence`, `definition`, `confusing`, `idea`) |
| `HL_KEYS` | keys `"1"`–`"5"` → highlight type (the reader's shortcuts) |
| `KIND_LABELS` | section kind → label (`abstract`, `intro`, `related`, `method`, `results`, `discussion`, `conclusion`, `references`, `appendix`, `other` → "Section") |

## 4.4 `api.ts`, `trash.ts` and `state.ts`

### `api`

```ts
async function call<T>(method: string, path: string, body?: unknown, isForm = false, approve?: string, round = 0): Promise<T>  // not exported
export const api = { get, post, patch, put, del, upload };
```

- `fetch(path, { method, credentials: "same-origin" })`. The session cookie carries the token. Every call goes to a path on the page's own origin, so the server's rule for writes (only from the app's own `Origin`, chapter 1) always holds for it.
- **428, the send preview** (milestone 4.4). The server answers 428 when "Show what will be sent" is on and a call would leave this computer; nothing was sent. `call` reads `preview` from the answer and awaits `previewDialog(preview)` (`aipreview.ts`, below). On **Send** it calls itself again with the same method, path and body, `approve` = `preview.token` (sent as the header `X-AI-Approve`) and `round + 1`. A later call of the same request may need a new approval, so this can repeat, at most 8 rounds. On **Cancel**, after 8 rounds, for a form upload, or when the answer has no `preview`, it throws `Error("Not sent: you did not approve it.")`. The retried request is a whole new request: the server runs the feature from its start.
- A JSON body sets `Content-Type: application/json`. For non-GET requests with a body under 60,000 characters, `keepalive: true` is set, so the write finishes even if the window is closing.
- `upload(path, form)` posts a `FormData` and sets no content type.
- `post` defaults its body to `{}`.
- On a non-OK status it throws `new Error(detail)`, where `detail` is the response's `detail` field (a string as is, anything else JSON-stringified), or the status code when the body is not JSON. Callers show `e.message` in a toast.
- A successful response is always parsed as JSON.

### `previewDialog(p)` (`aipreview.ts`)

```ts
export interface Preview { token: string; task: string; provider: string; system: string; user: string; note: string }
export function previewDialog(p: Preview): Promise<boolean>  // true only for Send
```

A wide modal titled "Send this to the cloud model?" (`div.stack.ai-preview`):

1. "This is what will be sent to <provider>, word for word (<N> characters). Nothing has been sent yet." The provider is shown as "Anthropic (Claude)" or "OpenAI" (`PROVIDER`), else as its id. N counts `system` and `user` together.
2. The server's `note` (muted): that the approval covers more calls with the same documents and notes, and that a call that would send another one asks again.
3. A `details` "The instructions for the model" with `system` in a `pre`.
4. "Your text and question" and `user` in a `pre`.
5. "Secrets found in the text are already replaced by [redacted]. Items tagged #private are left out. You can switch this check off in Settings → AI."
6. **Cancel** and **Send** (`btn primary`).

Every string goes in through `h()`, so the text is shown as text. Escape or the backdrop count as Cancel. Styles: "Part twenty-five" (`.ai-preview pre`: wrapped, scrolling past 22em, on `--panel2`). For a "local" server on another computer the server sends the cloud provider's name as `provider`, so the first line names that provider although the text goes to the endpoint (chapter 3).

### `save()`

```ts
function save(method: "post" | "patch" | "put" | "del", path: string, body?: unknown): Promise<unknown>
```

For writes that must not be lost and whose result nobody waits on. It tries once, then retries up to three more times after 400, 800 and 1200 ms. After the fourth failure it logs `save failed` and rejects. Most callers add `.catch(() => undefined)`; `InkPad.flush()` does not, so a final failure there reaches the global `unhandledrejection` toast.

It retries on any error, including a 4xx. Do not use it for requests that are not safe to repeat.

### `removeItem(kind, id, message, after)` (`trash.ts`)

Milestone 5.1 ("Delete on everything"). The one front-end call for the server's delete and Undo pair (`readhold/trash.py`, chapter 1, section 7b).

```ts
type ItemKind = "card" | "habit" | "quest" | "map_edge" | "journal" | "letter" | "side_quest" | "checkin" | "focus" | "ai_result";
function removeItem(kind: ItemKind, id: string, message: string, after?: { gone?: () => void; back?: (r: Restored) => void }): Promise<boolean>
```

1. `api.del("/api/items/<kind>/<id>")`. On an error it shows the toast "Not deleted: <reason>" (an error toast, 6 seconds) and resolves `false`; `gone` does not run.
2. `gone()` runs, then a toast with `message` and an **Undo** action (8 seconds).
3. Undo sends `POST /api/items/<kind>/<id>/restore` and passes the answer to `back(r)`; a refusal (the card went with its source, a loop, a removed document) shows "Could not undo: <reason>".

`Restored` is `{ok, kind, id, entry?}`; `entry` is the journal page that came back (`id`, `day`, `weather`, `body`, `prompts`). The server knows each kind and what hangs on it; the page names only the kind and the id. Callers: `review.ts` (card), `today.ts` (checkin, habit), `quest.ts` (quest, side_quest), `map.ts` (map_edge), `journal.ts` (journal, letter), `timer.ts` (focus), `why.ts` (ai_result). Each caller redraws itself in `gone` and `back`; `removeItem` changes no page.

### `state`

```ts
export const state = { settings: Settings, themes: Theme[], energy: Energy };
```

- `loadState()` fetches `/api/settings`, `/api/themes` and `/api/ambience` together. `state.energy` is today's check-in (`energy_today`) if there is one, else `settings.energy`. A failure of `/api/ambience` is tolerated; a failure of the other two rejects.
- `saveSettings(patch)` merges the patch into `state.settings` at once, then `PUT /api/settings` and replaces `state.settings` with the server's answer. It does not re-apply the theme; callers call `applyTheme()` when a visual setting changed.
- `state.energy` is also written by the reader (`views/reader.ts`) and Today (`views/today.ts`), each followed by `applyTheme()`.

### Fonts and comfort

- `FONTS` maps a font id (`atkinson`, `literata`, `opendyslexic`, `system`, `serif`) to a label and a CSS `font-family` stack.
- `comfortFor(sourceType)` returns `{ font, font_size, line_width, line_height }` from the settings, overridden by `settings.comfort_by_type[sourceType]` if present.
- `applyComfort(c)` sets `--read-font`, `--read-size` (px), `--read-width` (ch) and `--read-leading` on `<html>`. An unknown font id falls back to Atkinson.

## 4.5 `types.ts`

One file with every shape the server returns. No runtime code. The groups, in file order:

| Group | Main types |
|---|---|
| Reader | `Sentence` (with `words`, `density`, `personal`, `read`), `Paragraph`, `Section`, `Doc`, `Progress`, `QueueDoc` (with `flags`: `hidden_text`, `instructions`), `Question`, `HlType`, `Highlight`, `Note` (with the optional `origin`: `"ai"` for a note saved from something an AI model wrote, emptied when the note is edited), `Term`, `Annotations` |
| Settings and themes | `Settings`, `Energy`, `Comfort`, `Theme`, `Card`, `SessionInfo` |
| Compass | `QuestQuestion`, `QuestStep`, `SideQuest`, `Quest`, `Today` |
| Growth | `MapNode`, `TopicMap`, `Habit`, `DayLog` |
| Lectures | `SlideRun`, `SlideEl`, `LecturePage`, `Paper`, `Lecture`, `LectureNote` |
| Timer and tasks | `TimerKind`, `LinkType`, `TimerRun`, `Todo`, `TodoItem`, `RoutineStep`, `Routine`, `PlanData`, `TimerToday`, `TimerLinks` |
| Notes, search, links | `NoteLink`, `NoteRef`, `NotePage`, `NoteList`, `NoteTitles`, `NoteGraph`, `SearchHit`, `Related`, `DaySummary`, `WeekPlan` |
| Overview and Think | `HubData`, `Near`, `ThinkData`, `BrainstormData` |

Things to know:

- `Settings.intensity` is typed `string`; the values in use are `off`, `still`, `gentle`, `lively`. `Settings.glass` is `"solid" | "balanced" | "clear"`. Since milestone 4.4 `Settings` also has `ai_preview: boolean`, `ai_log_days: 1 | 7 | 30` and `ai_cloud_only_tagged: boolean`.
- `Preview` (the 428 answer's `preview`) is declared in `aipreview.ts`, not here.
- Booleans that come straight from SQLite are typed `number` (`Section.hidden`, `Highlight.resolved`, `NotePage.pinned`).
- `LinkType` is `"" | "step" | "document" | "lecture" | "page"`. `linkHref()` in `timer.ts` turns it into a hash.
- A new setting needs a default in `DEFAULT_SETTINGS` (`server.py`) as well; the server drops unknown keys on save.

## 4.6 Themes and ambience

### `themes.ts`

```ts
function currentTheme(): Theme     // settings.theme, else the first theme
function isDark(): boolean         // settings.dark: "dark" | "light" | "auto" (auto follows the OS)
function applyTheme(): void
function applyTimeOfDay(): void
function watchSystemTheme(): void
```

`applyTheme()` does all of this, every time:

| Sets | Value | Read by |
|---|---|---|
| one CSS variable per token | `--<key with _ → ->`, e.g. `accent_text` → `--accent-text` | the whole stylesheet |
| `data-mode` | `dark` or `light` | `color-scheme`, `--shadow`, equation pictures, `.error` |
| `data-energy` | `state.energy` | `low` desaturates the body and blurs text after the current sentence in the reader |
| `data-progress` | `theme.progress` (`sand-jar` or `bar`) | which progress widget the reader shows |
| `data-glass` | `settings.glass ?? "balanced"` | `--isle-a`, `--isle-filter` (4.13) |
| `ambience.state.energy` | `state.energy` | `ambience.pace()` |
| scene | `ambience.apply(theme.id, theme.has_scene, tokens, isDark(), settings.intensity)` | |
| sound | `sound.apply(theme.ambient_sound, settings.sound, settings.sound_volume ?? 0.35)` | |
| `--tod` | via `applyTimeOfDay()`, then again every 5 minutes | the body's background image |

Tokens are set as inline custom properties on `<html>`, so they win over the defaults in the `:root` rule of `styles.css`. A token missing from a theme keeps the value from the previous theme until reload; the tests require every theme to define the full set.

`data-*` attributes on `<html>` that other files set: `data-scene` (`ambience.apply`), `data-hidden` (`boot()`), `data-peek` (`peek.ts`).

**Time of day.** `applyTimeOfDay()` sets `--tod` from the local clock: 05–08 `rgba(255,190,120,0.1)`, 08–17 `rgba(255,255,255,0)`, 17–20 `rgba(255,150,80,0.1)`, otherwise `rgba(20,30,70,α)` with α 0.12 in dark mode and 0.08 in light. The body paints it as a flat layer over `--bg`. It never touches panels.

### `ambience.ts`: the scene host

One object, `ambience`, owns one `<canvas id="ambience" aria-hidden="true">` prepended to `<body>` (`position: fixed`, `z-index: 0`, `pointer-events: none`; `#app` is `z-index: 1`).

**The scene contract**

```ts
type SceneFactory = (env: SceneEnv) => Scene;          // default export of themes/<id>/scene.js
interface Scene {
  frame(dt: number, t: number): void;                   // dt, t in scene seconds (already scaled)
  resize?(w: number, h: number): void;
  destroy?(): void;
}
interface SceneEnv {
  ctx: CanvasRenderingContext2D;                        // already scaled by devicePixelRatio
  w: number; h: number;                                 // CSS pixels (window.innerWidth/innerHeight)
  dark: boolean;
  tokens: Record<string, string>;                       // the theme's tokens for the current mode (keys with underscores)
  state: AmbienceState;                                 // the live object; read it every frame
}
```

**`AmbienceState`: every field and who writes it**

| Field | Meaning | Written by |
|---|---|---|
| `progress` | 0..1 | reader (ratio of key sentences read), lecture desk (`(page + 1) / pages`; 0 for web lectures), Today (the main goal's answered ratio) |
| `answered` | a count | reader (questions answered in the document), Today (today's answers + finished steps + habits done) |
| `reviewed` | cards rated today | `boot()` from `/api/ambience`; `views/review.ts` adds 1 per rating |
| `mode` | `idle`, `reading`, `break`, `review` | `route()` (`review` on review/practice, else `idle`); `timer.set()`; the reader (playing → `reading`); focus, lecture and practice views |
| `energy` | `low`, `medium`, `high` | `applyTheme()` |
| `moment` | `performance.now()` of the last quiet moment, or 0 | `ambience.moment()`, called when a question is answered, a habit is done, a practice card is "got", and similar |
| `session` | seconds of the current session | reader and focus view (direct assignment each tick); `route()` resets it to 0 |
| `still` | no motion: draw finished states | `ambience.restart()` |

Writers should use `ambience.update(patch)` rather than assigning, because `update` also redraws a still scene. (The reader and focus view assign `session` directly on each tick; in Still mode that change shows only at the next redraw.)

**Methods**

| Method | What it does |
|---|---|
| `apply(themeId, hasScene, tokens, dark, intensity)` | Resolves the intensity (reduce-motion turns anything but `off` into `still`). Toggles `data-scene` on `<html>` (present when the theme has a scene and intensity is not `off`). No scene or `off` → `teardown()`. Otherwise, if the key `themeId|dark|JSON(tokens)` changed or no scene is alive, imports `/themes/<id>/scene.js`, tears the old scene down, sizes the canvas, calls the factory. Then `restart()`. |
| `ensureCanvas()` | Creates the canvas once and binds `resize`, `visibilitychange` and reduce-motion listeners. |
| `size(canvas, ctx)` | Backing store = window size × `min(devicePixelRatio, 1.5)`; `ctx.setTransform(dpr, …)`. Scenes draw in CSS pixels. |
| `onResize()` | Resizes, calls `scene.resize?.(w, h)`, then `drawOnce()`. |
| `teardown()` | Cancels the frame, calls `destroy?.()` inside `try`, drops the scene and key, clears the canvas. |
| `pace()` | `PACE[intensity] × MOOD[mode] × energy factor`. |
| `restart()` | Cancels the loop. Sets `state.still`. If still or hidden: draws one frame (only when visible) and stops. Otherwise starts the `requestAnimationFrame` loop. |
| `drawOnce()` | Draws a single frame with `dt = 0` when the scene is still or no loop is running. |
| `safeFrame(dt)` | Calls `scene.frame(dt, t)` in `try`; an exception logs a warning and tears the scene down. |
| `update(patch)` | Merges into `state`; on a mode change resets the frame clock; `drawOnce()`. |
| `moment()` | Stamps `state.moment`; `drawOnce()`. |

**Frame rate and pace**

| Intensity | Frames per second (`FPS`) | Speed (`PACE`) |
|---|---|---|
| `off` | no scene at all | 0 |
| `still` | one frame on demand | 0 |
| `gentle` | 20 | 0.6 |
| `lively` | 30 | 1 |

The loop runs on every animation frame but returns early until `1000 / fps - 2` ms have passed. `dt` is the real elapsed time, capped at 0.1 s, times `pace()`.

- `MOOD`: `idle` 1, `reading` 0.45, `break` 1.25, `review` 1.1. The scene slows down while you read.
- Energy factor: `low` 0.6, `medium` 1, `high` 1.1.

So "gentle, reading, low energy" runs at 0.6 × 0.45 × 0.6 ≈ 0.16 of real time. Scenes should drive all motion from `dt`, not from wall-clock time, or these factors do nothing.

**Hidden window.** `visibilitychange` calls `restart()`, which stops the loop while `document.hidden` and starts it again after.

**Loading races.** `apply` is async. A `loading` ticket makes sure only the newest request installs its scene.

**Errors.** A scene that fails to import, throws in its factory, or throws in `frame` is torn down with a console warning. The app keeps working with the plain background. `data-scene` stays set in that case (it is toggled before loading), so panels keep their scene styling.

### Writing a scene: `themes/lantern/scene.js` as the example

The file is a plain ES module with one default export. It is served as a static file from `/themes/`; it is not type-checked or bundled.

1. **Top-level helpers are pure.** `rng(seed)` is a small seeded generator, so the layout is the same on every load. `SKY` is a table of `[hour, [top, middle, horizon]]` colours for light and dark, blended by `skyAt()`. `glowSprite()` pre-renders a radial gradient into an `OffscreenCanvas` (and returns `null` when that class is missing; `sprite()` then draws a plain circle).
2. **The factory** `lanterns(env)` reads `ctx`, `dark`, `state`, `w`, `h` once and keeps its own variables. It does not use `env.tokens` (its palette is hard-coded per mode). The Garden scene does: its sky gradient is `tokens.bg` → `tokens.bg2`.
3. **`layout()`** computes everything that depends on the size: horizon, two mountain ridges, stars, ripples, fireflies and 36 lantern positions (`MAX`). It is called once at start and again from `resize(nw, nh)`.
4. **`frame(dt)`**:
   - `t += dt` (its own clock; the second argument of `frame` is not used);
   - `paintSky()` rebuilds the gradients only when the wall-clock minute changes;
   - `ctx.clearRect(0, 0, w, h)` first. The canvas is transparent and is not cleared for you;
   - draws sky, stars (when `night > 0.05`), the moon or sun at a position driven by `state.progress`, mountains, water, reflections, fireflies;
   - lantern count: `min(36, 6 + state.reviewed + state.answered + floor(state.session / 300))`. A `born` map records when each new lantern appeared so it can fade in over 2.4 scene seconds;
   - **Still branch:** when `state.still`, lanterns are drawn at full alpha, four fixed lanterns are drawn in the air from a seeded generator, and the function returns before any animation code;
   - otherwise a lantern lifts off when `state.moment` changes, and at random intervals of 9–20 scene seconds, at most 6 (`RISERS`) at a time.
5. **No `destroy`.** It holds nothing that needs releasing. Add one if a scene keeps timers or listeners (it should not need any).

Rules a scene must follow (most are tested, see below):

- Draw only on `env.ctx`. Do not touch the DOM, the network or storage.
- Handle `state.still`: draw a finished picture with no transitions, since `frame(0)` is all you get.
- Nothing may flash more than 3 times a second. Lantern uses slow sine "breathing" (about 5 s per cycle). Garden's butterfly beats about 1.6 times a second and is skipped in Still mode.
- Keep per-frame work small: pre-compute in `layout()`, cache gradients and sprites.
- The reacting-to-a-moment pattern: compare `state.moment` to a remembered value (Lantern), or compute a 2.6 s sine glow from `performance.now() - state.moment` (`momentGlow()` in Garden).

### The `themes/` folder

Eighteen folders. Each has `theme.json`; sixteen also have `scene.js`.

| Folder | Name | `progress` | `motion` | `ambient_sound` | Scene |
|---|---|---|---|---|---|
| `beach` | Beach | bar | gentle | shore | yes |
| `clean` | Clean | bar | gentle | none | yes |
| `cloud` | Cloud | bar | gentle | wind | yes |
| `comics-action` | Comics: Classic Action | bar | lively | none | yes |
| `comics-classic` | Comics: Classic | bar | gentle | none | yes |
| `forest` | Forest | bar | gentle | wind-birds | yes |
| `galaxy` | Galaxy | bar | gentle | hum | yes |
| `garden` | Garden | bar | gentle | breeze | yes |
| `lantern` | Lanterns | bar | gentle | crickets | yes |
| `manga-action` | Comics: Manga Action | bar | lively | none | yes |
| `meadow` | Meadow | bar | gentle | breeze | yes |
| `night` | Night sky | bar | gentle | crickets | yes |
| `ocean` | Ocean | bar | gentle | waves | yes |
| `orbit` | Orbit | bar | gentle | hum | yes |
| `paper` | Paper | bar | none | none | no |
| `pixel` | Pixel art | bar | gentle | lofi | yes |
| `rain` | Rain | bar | gentle | rain | yes |
| `sand` | Sand | sand-jar | still | none | no |

`theme.json` keys: `name`, `description`, `progress`, `motion`, `sound` (always `null` today), `ambient_sound`, the optional `look` (`"comics"`) and `look_variant` (`classic`, `action`, `manga`), and `tokens.light` / `tokens.dark`. `GET /api/themes` (`api_themes` in `server.py`) adds `id` (the folder name) and `has_scene` (whether `scene.js` exists). The front end decides whether to load a scene from `has_scene`, not from `motion`; `motion` is only checked by the tests. `clean` is the default theme (`DEFAULT_SETTINGS`; it was `sand` until 2026-11-27), and `currentTheme()` in `themes.ts` falls back to it when the saved theme's folder is gone, then to the first theme.

The eighteen tokens: `bg`, `bg2`, `panel`, `panel2`, `border`, `text`, `muted`, `accent`, `accent_text`, `pacer`, `word`, `sand`, `sand_dark`, and the five highlight colours `claim`, `evidence`, `definition`, `confusing`, `idea`.

### What `tests/test_themes.py` enforces

| Test | Rule |
|---|---|
| `test_theme_contrast` (each theme × light, dark) | All eighteen tokens exist. These pairs reach 4.5:1: `text`/`panel`, `muted`/`panel`, `text`/`panel2`, `muted`/`panel2`, `accent`/`panel`, `accent_text`/`accent`, `text`/`pacer`, `text`/`word`, `text`/`bg`, and `text` on each highlight colour. |
| `test_theme_manifest` | `name` is set; `progress` is `sand-jar` or `bar`; `sound`, if set, is a file in the folder; `ambient_sound` is `None` or one of the nine recipe names; a `motion` other than `still`, `none` or missing requires `scene.js`. |
| `test_scene_rules` (each `scene.js`) | Contains `export default`. Contains none of: `fetch(`, `XMLHttpRequest`, `WebSocket`, `eval(`, `new Function`, `import(`, `innerHTML`, `localStorage`, `document.`, `http://`, `https://`. |
| `test_sound_recipes_match_front_end` | Every name in the test's `AMBIENT_SOUNDS` appears in `web/src/sound.ts`. |
| `test_see_through_islands_stay_readable` | Reads `--isle-a` from the `:root[data-glass="clear"]` rule in `styles.css`. Mixes `panel` at that alpha over `bg`, `bg2`, `sand`, `sand_dark`; `text`, `muted` and `accent` must reach 4.5:1 on each. `text` must also pass over pure white and pure black. |

The scene check is a plain substring search. A comment containing `document.` or a URL fails it. If you add a sound recipe, add its name to `AMBIENT_SOUNDS` in the test. If you lower `--isle-a` for see-through panels, every theme is re-checked against the new value.

### `sound.ts`

Ambient sound is generated with WebAudio. There are no audio files.

```ts
type Recipe = (ctx: AudioContext, out: AudioNode) => Stop;   // Stop = () => void
export const RECIPES: Record<string, Recipe[]>;
export const sound = { ctx, master, stops, key, apply(recipe, enabled, volume), stopAll() };
```

Building blocks: `noise(ctx, "pink" | "brown")` makes a cached 6-second buffer with a faded loop seam; `loopNoise` plays it in a loop; `lfo(ctx, freq, depth, target)` slowly modulates a parameter; `every(minS, maxS, fn)` calls `fn` at random intervals.

| Name | Made of |
|---|---|
| `rain` | pink noise, band 500–5200 Hz, slow swell |
| `wind-birds` | `windAt(500, 0.25)` + `birds` (2–4 sine chirps every 4–11 s) |
| `breeze` | `windAt(900, 0.14)` |
| `wind` | `windAt(450, 0.22)` |
| `hum` | three low sines (55, 82.4, 110.6 Hz) through a low-pass, slow breathing |
| `crickets` | quiet wind + three short pulses near 4.3 kHz every 0.9–2.2 s |
| `lofi` | four triangle-wave chords, one every 4 s, plus soft brown-noise crackle |
| `waves` | brown-noise surf with a rolling low-pass, pink foam, a 46 Hz rumble |
| `shore` | pink-noise lapping, backwash hiss, a gull call every 14–34 s, plus `windAt(900, 0.06)` |

`sound.apply(recipe, enabled, volume)`:

- The key is the recipe name when sound is enabled and the recipe exists, else `""`.
- Master gain is `clamp(volume, 0, 1) × 0.6`. It is updated on every call, so the volume slider works without restarting the sound.
- Same key → nothing else happens. A new key → `stopAll()` (every `Stop` runs, the context is suspended), then each recipe in the list is started.
- The `AudioContext` is created on first use. It is suspended while the window is hidden. A `pointerdown` or `keydown` resumes it (browsers block audio before a user gesture).

To add a sound: write a `Recipe` that connects to `out` and returns a function stopping every node and timer it made, add it to `RECIPES`, add the name to the test, and set `ambient_sound` in a `theme.json`.

## 4.7 `math.ts` and `tts.ts`

### Math

Math is stored as LaTeX inside `\( … \)` (inline) and `\[ … \]` (display). The Markdown importer writes it; a paper imported from arXiv by an earlier version holds it too. `math.ts` turns that into DOM.

```ts
const hasMath: (text: string) => boolean
function mathEl(tex: string, display: boolean): HTMLElement
function mathText(text: string): Node[]
function displayEquation(text: string): { tex: string; tag: string } | null
function wordsWithIndex(text: string): { word: string; index: number }[]
const words: (text: string) => string[]
const plainMath: (text: string) => string
const spoken: (word: string) => string
```

- **Finding.** `MATH` is one global regex matching either delimiter pair. `mathText()` walks the matches: plain stretches become text nodes, each formula becomes `mathEl(...)`. Text without `\(` or `\[` returns a single text node without running the regex.
- **Drawing.** `mathEl()` calls `katex.render(tex, el, options)` into a `span.math` or `div.math.math-display`. KaTeX builds the nodes itself. Options:

| Option | Value | Why |
|---|---|---|
| `displayMode` | from the delimiter | |
| `throwOnError` | `true` | so the `catch` can fall back |
| `trust` | `false` | `\href`, `\url`, `\htmlData` and similar are refused |
| `strict` | `"ignore"` | non-standard LaTeX is accepted silently |
| `output` | `"htmlAndMathml"` | the MathML is what screen readers read |
| `macros` | a fresh copy of `MACROS` | `\mathbbm`, `\argmax`, `\argmin`; a copy, because KaTeX may write `\gdef` macros into the object |
| `maxExpand` | 500 | stops runaway macro expansion |
| `maxSize` | 20 | caps sizes a formula can ask for |

- **Fallback.** If KaTeX throws, the element's `textContent` is the raw LaTeX, with class `math-raw` and an explanatory `title`. Reading never breaks on a formula.
- **Cache.** A `Map` keyed by `"D"|"I" + tex` stores a clone; each call returns a fresh clone. It is emptied when it passes 3000 entries. Failed formulas are cached too.
- **Do not redefine KaTeX's own macros** in `MACROS` (the comment names `\R`, `\E`, `\bm`, `\coloneqq`): expansion loops.
- `displayEquation(text)` recognises a paragraph that is only `\[ … \]` plus an optional number like `(3)` of at most 12 characters.
- `wordsWithIndex(text)` splits on whitespace like `/\S+/g`, but keeps a formula as one word even if its LaTeX contains spaces. The pacer and the reader rely on this for word positions.
- `plainMath(text)` strips delimiters and keeps the LaTeX (for titles, tooltips, search).
- `spoken(word)` is for read-aloud: `speakTex()` rewrites fractions ("a over b"), roots, powers, subscripts, Greek letters and common operators into rough English. Unknown commands are dropped. An empty result is spoken as "formula".

### `tts.ts`

```ts
interface SpeakOpts { rate: number; voice: string; onWord: (charIndex: number) => void; onEnd: () => void }
class Tts { available(); voices(); pickVoice(name); speak(text, opts); stop() }
function isOfflineVoice(v: SpeechSynthesisVoice): boolean
```

- Uses the browser's `speechSynthesis`. If it is missing, `speak` calls `onEnd` at once.
- `voices()` returns only offline voices (`isOfflineVoice`). The constructor calls `speechSynthesis.getVoices()` once so the list is loaded early.
- `pickVoice(name)`: the named voice if it is an offline one, else the first offline English voice, else the first offline voice.
- `speak` says nothing when there is no offline voice, so the browser's default voice (which may be an online one) is never used. `onEnd` is not called in that case; the reader refuses to switch read-aloud on without an offline voice (`Reader.setReadAloud`).
- `speak` cancels anything in progress, clamps `rate` to 0.5–2.5, and forwards `boundary` events of type `word` to `onWord(charIndex)`.
- A private `token` counter is bumped by every `speak` and `stop`. Callbacks from an older utterance are ignored. `interrupted` and `canceled` errors do not call `onEnd`.
- `isOfflineVoice(v)`: `localService` and the name does not contain "natural" or "online". A voice that streams from the internet would send the text you read to a speech service, so `voices()` leaves it out: it is never listed and never used.

## 4.8 `pacer.ts` and `session.ts`

### The pacer

`Pacer` knows nothing about the DOM. It talks to a `PacerHost` (the reader implements it):

```ts
interface PacerHost {
  sentence(ord: number): Sentence;
  words(ord: number): string[];
  next(ord: number): number | null;
  prev(ord: number): number | null;
  show(ord: number, wordIdx: number | null): void;   // move the cursor
  done(ord: number): void;                            // a sentence was read to its end
  boundary(from: number, to: number): boolean;        // true = pause here (section change)
  end(): void;
  playState(playing: boolean): void;
}
type PacerMode = "sentence" | "word" | "focus";
const ENERGY_SPEED = { low: 0.85, medium: 1, high: 1.15 };
```

Public fields: `playing`, `ord`, `wordIdx`, `mode`, `wpm`, `energy`, `readAloud`, `voice`, `ttsRate`, `pauses`. Methods: `play()`, `pause(countAsPause = true)`, `toggle()`, `step(1 | -1)`, `setPosition(ord, wordIdx = 0)`, `setReadAloud(on)`, `invalidate()`, `expectedMs(ord?)`, `voices()`, `destroy()`.

**What it toggles.** Nothing directly. It calls `host.show(ord, wordIdx)`, and the reader moves CSS classes on existing elements. `wordIdx` is `null` in sentence mode without read-aloud, and a number otherwise. The page is never re-rendered by the pacer.

**The clock.** `startClock()` runs one `requestAnimationFrame` loop. Each frame adds the elapsed time (capped at 250 ms, so a background tab cannot skip ahead) to `acc` and calls `advanceByClock()`:

- sentence mode: when `acc` reaches `sentenceMs(current)`, subtract it and `finishSentence()`;
- other modes (`word` and `focus` are the same to the pacer; the reader draws them differently): advance word by word while `acc` covers the next word's time, calling `host.show` for each, then `finishSentence()` after the last word. Per-sentence word timings are cached in `wordCache`; call `invalidate()` after changing `wpm` or anything else that affects them.

**How density changes speed.**

```
sentenceMs = max(900, (words × 60000 / wpm) × (0.7 + 0.9 × density) × (1 + personal) / speed) + 200
wordMs     = max(90,  (60000 / wpm) × (0.55 + 0.09 × min(letters, 14)) × (0.8 + 0.6 × density) × (1 + personal) / speed)
             + half a base word after , ; :   + one base word after . ! ?   (added before the division by speed)
```

`density` (0..1) comes from the server (`density.py`); `personal` is the learned slow-down for that sentence; `speed` is `ENERGY_SPEED[energy]`. A sentence with density 1 stays lit about 2.3 times as long as one with density 0.

**`finishSentence()`**: `host.done(ord)`; if there is no next sentence, pause and `host.end()`; otherwise ask `host.boundary(from, to)`, move to the next sentence, `host.show`, and pause (without counting a pause) if the host asked for it.

**Read aloud.** With `readAloud` on, the rAF clock is not used. `speak()` joins the words from the current word onward (each passed through `spoken()` from `math.ts`), records each word's character offset, and calls `Tts.speak` with `rate = ttsRate × (1 - 0.18 × density) × speed`. `onWord(charIndex)` maps the offset back to a word index and calls `host.show`; `onEnd` calls `finishSentence()`, which speaks the next sentence.

**Pauses.** `pause()` increments `pauses` unless called with `false`. The reader uses the count for its speed ramp.

### `SessionTracker`

```ts
static async start(documentId, energy, timeBoxMin, question, isPlaying, onTick, questId = null)
```

`start` posts to `/api/sessions` and returns a tracker. It tracks:

| Field | Meaning |
|---|---|
| `focusedMs` | time counted as focused |
| `runMs`, `longestRunMs` | the current and the longest unbroken run |
| `distractions` | incremented by `distracted()`, which also resets `runMs` |
| `sentencesRead` | set by the reader |

- A 1-second interval (`tick`) adds the elapsed time (capped at 5 s) when the user is **present** (`document.visibilityState === "visible"` and `document.hasFocus()`) and **engaged** (the pacer is playing, or `activity()` was called in the last 60 s). When not present, `runMs` resets. Then `onTick(this)`.
- A 15-second interval (`flush`) sends `PATCH /api/sessions/<id>` through `save()`.
- `flushOnUnload()` sends the same payload with a raw `fetch` and `keepalive: true`.
- `end(nextStep, output, feel)` stops both intervals and sends a final patch with `next_step`, `output`, `ended: true` and the optional `feel`.
- `leave()` is for leaving the reader without the end dialog (`Reader.destroy()` calls it). It stops both intervals, marks the tracker as ended and sends one patch with the counters and `ended: true` through `save()`, without waiting for it. It does nothing if the session has already ended.
- `stopTimers()` only stops the intervals. `end()` and `leave()` call it.
- Once the tracker is ended, `flush()`, `flushOnUnload()`, `end()` and `leave()` do nothing.

## 4.9 `timer.ts` and `reminders.ts`

### The `timer` object

One timer for the whole app. The server keeps the run (`/api/timer…`); the client keeps a local clock so the display does not need the server every tick.

**State**

| Field | Meaning |
|---|---|
| `run` | the current `TimerRun`, or `null` |
| `baseMs`, `baseAt` | elapsed time, and the `performance.now()` at which it was true |
| `over` | a countdown has reached zero (and chimed) |
| `listeners` | callbacks registered with `on()` |
| `tickId`, `beatId` | interval ids |
| `loaded` | the server state has arrived at least once |

**Read**

| Method | Returns |
|---|---|
| `elapsed()` | `baseMs` plus time since `baseAt` if running |
| `shown()` | countdown: `planned_ms - elapsed()` (negative when over); stopwatch (`planned_ms === 0`): elapsed |
| `progress()` | 0..1 for a countdown, else 0 |

**Events**: `on(fn)` returns an unsubscribe function. `emit()` calls every listener inside `try`. Listeners are called on every state change and every tick. A page must call the unsubscribe function in its cleanup.

**Change**

| Method | Request | Notes |
|---|---|---|
| `set(run)` | none | Central setter: stores the run, rebases the clock on `elapsed_now_ms`, computes `over`, calls `schedule()`, updates `ambience` mode (`break` for a break, `reading` while a focus or stopwatch run is running, else `idle`), emits. |
| `load()` | `GET /api/timer` | Returns `{ run, todos, today }`. Shows a toast if `run.was_quiet` (the app was closed while it ran, so it came back paused). |
| `start(opts)` | `POST /api/timer/start` | Body is `{ minutes: 25, ...opts }`. See `StartOpts`: `kind`, `minutes`, `label`, `todo_id`, `link_type`, `link_id`. |
| `pause()` | `POST /api/timer/<id>/pause` | Sends `elapsed_ms`. |
| `resume()` | `POST /api/timer/<id>/resume` | |
| `toggle()` | | pause or resume |
| `extend(minutes = 5)` | `POST /api/timer/<id>/extend?minutes=N` | Countdowns only. Keeps the local elapsed time instead of the server's. |
| `finish(status, extra)` | `POST /api/timer/<id>/finish` | `status` is `done` or `stopped`; `extra` may carry `feel` and `output`. Returns `{ today, todos }` and sets the run to `null`. |

**Ticks.** `schedule()` starts two intervals while a run is running and stops them otherwise: a 500 ms tick that detects the end of a countdown (sets `over`, then `chime()` and a toast) and emits; and a 15 s `beat()` that posts `elapsed_ms` to `/api/timer/<id>/beat`. The countdown does not stop at zero; it runs on and the display shows `+m:ss`.

**`chime()`** plays two soft sine notes (659 Hz, then 988 Hz) with a quiet overtone, only when `settings.timer_sound` is on. It has its own `AudioContext`, separate from `sound.ts`.

**`linkHref(type, id)`** maps a `LinkType` to a hash: `lecture → #/lecture/<id>`, `document → #/read/<id>`, `step → #/home`, `page → #/notes/<id>`.

### The mini timer

`mountMiniTimer()` adds `div.mini-timer` (role `timer`) to `#corner-dock`: a dot, a link to `#/timer` with the time and label, and a pause/resume button. Its `render` runs on every timer event and on `hashchange`:

- hidden when there is no run or the hash starts with `#/timer`;
- classes `kind-<kind>`, `paused`, `over`;
- **it also sets `document.title`**: `"12:34 · Focus — Readhold"` while a run exists, `"Readhold"` otherwise.

It also sends `timer.beat(true)` (keepalive) on `pagehide`.

### `timerMenu(anchor, opts)`

A small popup under a button (used by the lecture desk): the current run if any, "Focus 15/25/45 min" buttons that start a focus run linked to `opts.link_type` / `opts.link_id`, and a link to the timer page. Closes on outside pointer-down, Esc or a choice.

### `reminders.ts`

`mountReminders()` is the only export.

- `refresh()` loads `GET /api/todos/timed` → `{ today, tasks: [{ id, text, at: "HH:MM", minutes }] }`. It runs at mount, every 60 s, and on every `hashchange`.
- `check()` runs after the first refresh and every 20 s. For each task whose time has come and whose key `<day>:<id>:<at>` is not in the `fired` set: mark it fired; if it is more than 10 minutes late, stay silent; otherwise `chime()` and a 30-second toast `"14:30 · text"` with a "Focus N min" action that starts a focus timer with `todo_id`.
- `fired` lives in memory only. A reload within the 10-minute window rings again. Nothing runs while the app is closed.

## 4.10 `palette.ts`, `capture.ts`, `related.ts`

### Find anything: `openPalette()` (Ctrl+K)

Does nothing if any `.modal-back` is already open. Opens a `modal("Find anything", …)` with an input (`.find-input`) and a list (`ul.switch-list`).

**Where rows come from** (`draw()`):

| Query | Rows, in order |
|---|---|
| empty | the first 7 commands, then up to 5 recent notes from `GET /api/pages/titles` |
| not empty | search hits; up to 5 commands whose label contains the query; "Add task …"; "Create note …" (unless a note hit has exactly that title) |

- **Search hits** come from `GET /api/search?q=…`, debounced by 140 ms. A counter (`asked`) drops answers that arrive after a newer query. The `KIND` table maps each `SearchHit["kind"]` to an icon, a hint and a target: `note → #/notes/<id>`, `task → #/plan`, `document → #/read/<id>`, `passage → #/read/<document_id>?s=<sentence>`, `lecture → #/lecture/<id>`, `quest → #/quest/<id>`, `term → #/glossary?concept=<title>`, `idea → #/ideas`.
- **Commands** come from `commands()`: Overview, Capture a thought, Think, Today's note, start a 25-minute focus timer, take a 5-minute break, Plan's week board (`#/plan?view=week`), the notes map and table, switch light/dark (`saveSettings` + `applyTheme`), and a "Go to …" row for each page. To add a command, add a `Row` (`{ icon, label, hint, go }`) to that array.
- **Quick add** reuses Plan's parser: `parseQuick(raw, ymd(new Date()))` from `views/plan.ts`. Its result fields used here are `text`, `minutes`, `due`, `repeat_rule`, `at`, `area`. The row posts to `/api/todos`. If Plan is the open page, a synthetic `hashchange` is dispatched so it redraws.
- **Create note** posts to `/api/pages/open` with the title and opens the note.

Keys: ↑/↓ move the selection, Enter flushes the pending search and runs the selected row. Running a row closes the modal first, then calls `row.go()`; a rejected promise becomes an error toast.

### Capture: `openCapture()` (Ctrl+J)

Does nothing if a modal is open.

**`whereAmI()`** builds a stamp `{ kind, id, title, sentence }` from the hash. It returns `null` unless the second path part is a 32-character hex id.

| View | Stamp kind | Extra |
|---|---|---|
| `read`, `summary`, `structure` | `document` | calls `flushPending()` first, then `GET /api/documents/<id>?touch=false`; `sentence` is the saved position (only for `read`) |
| `lecture` | `lecture` | |
| `quest`, `map` | `quest` | |
| `notes` | `page` | |

A failed request means no stamp.

**The three destinations.** The choice is remembered for the session in `lastKind` (starts as `idea`).

| Kind | Request | With a stamp |
|---|---|---|
| `idea` | `POST /api/ideas` | a document stamp sends `document_id` (and `sentence`); any other stamp appends `— from “title”` to the text |
| `note` | `POST /api/pages/capture` with `day` = today | appends ` — [[title]]`, or `[[title#s<n>|title]]` for a document with a sentence; a title that is not linkable (empty, over 190 characters, or containing `[ ] | #` or a newline) is appended as plain text. Newlines are collapsed; the text is cut to 1000 characters |
| `task` | `POST /api/todos` | first line is the task text (500), the rest is the note (2000); `link_type`/`link_id` from the stamp, except for a quest |

Enter saves, Shift+Enter makes a new line. On failure the box stays open with an error toast. After a save, if the open page lists what was saved (`#/hub`, `#/ideas`, `#/plan`, `#/think`, an empty hash, or `#/notes/today`), a synthetic `hashchange` redraws it.

### `connectedCard(kind, id, title)` (`related.ts`)

Returns a `div.connected` at once and fills it when `GET /api/related?kind=…&id=…` answers (for `kind === "term"` the query uses `title=` instead of `id=`). If the request fails the card hides itself.

It shows up to three lists, "Notes that link here", "Mentioned in your notes" and "Open tasks", or a hint that nothing points here yet. Actions:

- **+ Note about this**: asks for a title, posts to `/api/pages` with the body `About [[title]].` (only when the title is linkable). If that fails (a note with that title exists), it opens the existing one through `/api/pages/open`.
- **+ Task for today**: only for the kinds in `TASK_START` (`document`, `lecture`, `page`). Posts to `/api/todos` with `link_type`, `link_id`, `due` = today, then reloads the card.
- For a quest, a hint replaces the task button.

Called from the summary sheet (`views/summary.ts`), the lecture desk's notebook (`views/lecture.ts`), the glossary's concept page (`views/misc.ts`) and a goal's page (`views/quest.ts`). The kind `page` is supported and the file's header comment mentions notes, but `views/notes.ts` does not call it.

## 4.11 The corner dock, small pieces and ink

`mountMiniTimer()` and `mountPeek()` both put their piece into `#corner-dock` (class `corner-dock`). On a wide window the dock sits at the foot of the side menu; on a narrow one it is a bar at the bottom (see 4.13).

The calm tools that used to live here (`unstick.ts`, `steadynote.ts`, `guess.ts`) were removed on 2026-11-25; see chapter 2, section 5.

### `feel.ts`

`feelRow()` returns `{ el, pick() }`: three chips (Energized, Neutral, Drained). One tap picks, the same tap clears, `pick()` returns `""` when skipped. Used by end-of-session dialogs.

### `peek.ts`

`mountPeek()` adds `button.peek-btn` to the dock. A click, or the V key, toggles `data-peek` on `<html>`; the stylesheet fades `#app`, `#toasts`, the rest of the dock and any modal to opacity 0. While it is on, any key or any pointer-down outside the button turns it off, and that event is swallowed (`preventDefault` + `stopPropagation`, capture phase). `hashchange` turns it off too. The V key only works when `<html>` has `data-scene`; the stylesheet hides the button when there is no scene, and in the reader and the lecture desk.

### `ink.ts`

Pen strokes on a canvas, stored as vectors.

```ts
type Tool = "pen" | "highlighter" | "eraser";
interface Stroke {
  tool: "pen" | "highlighter";
  color: string;
  size: number;                          // relative to pad width
  points: [number, number, number][];    // x, y (both relative to pad WIDTH), pressure 0..1
}
interface InkOptions { owner?: string; adaptToDark?: () => boolean; readonly?: boolean; onChange?: (strokes: Stroke[]) => void }
class InkPad { constructor(host: HTMLElement, opts?: InkOptions) }
function inkToolbar(pad: InkPad, extra?: (HTMLElement | null)[]): HTMLElement
function inkKeys(pad: InkPad, bar: HTMLElement, e: KeyboardEvent): boolean
const INK_COLORS: string[]   // six colours
```

- **Coordinates.** `x` is 0..1 across the pad; `y` is also divided by the width, so it runs 0..height/width. Ink keeps its place and proportions when the pad is resized or zoomed.
- **Tools.** Pen: width follows pressure (`0.35 + p × 1.1` of the base; mouse and touch use 0.5), drawn as quadratic curves through midpoints. Highlighter: 3.2 times the chosen size, alpha 0.32, drawn as one path so overlaps do not darken. Eraser: removes whole strokes that pass within a small radius; it is not stored as a stroke. Sizes: `fine` 0.0025, `medium` 0.0045, `bold` 0.008.
- **Input.** Pointer events with capture and coalesced events. Points closer than 0.6 px are skipped. A single tap becomes a two-point dot. Palm rejection: once a pen has been seen, touch pointers do not draw.
- **History.** `undo()`, `redo()`, `clear()`. Snapshots are JSON strings of the whole stroke list, at most 60.
- **Saving.** `owner` is the path under `/api/ink/` (in use: `lecture_page/<id>:<ord>`, `note/<id>`, `journal/<day>`). `load()` fetches and puts saved strokes under any drawn meanwhile. Every change schedules `flush()` after 700 ms: `PUT /api/ink/<owner>` with `{ strokes }` through `save()`. If loading failed, nothing is saved, so a partial picture never overwrites the stored one. No `owner` means a preview that is never saved.
- **Resize.** A `ResizeObserver` on the host defers `resize()` to the next animation frame (resizing inside the callback causes the "ResizeObserver loop" notice that `boot()` filters). `resize()` sets the backing store to host size × `min(devicePixelRatio, 2)` and redraws everything.
- **Offset.** `setOffset(x, y)` shifts the drawing transform, for a pad that is a window onto a taller scrolling page (web lectures).
- **Dark paper.** With `adaptToDark` returning true, strokes darker than luminance 0.3 are drawn in a light colour. The stored colour does not change.
- **`destroy()`** flushes, disconnects the observer and removes the canvas. Pages must call it in their cleanup.
- `setEnabled(on)` toggles drawing and the `drawing` class.
- `inkToolbar` builds the tool, colour, size, Undo, Redo and Clear buttons and stores a `pick` function on the bar element. `inkKeys` handles B, M, E, Ctrl+Z, Ctrl+Shift+Z and Ctrl+Y; the page decides when to call it. Clear asks with the browser's `confirm()`, not `confirmBox()`.

## 4.12 `views/libtabs.ts`: the shared tab header

Three menu entries are pages with tabs. The tabs are plain links, so every old address still works.

```ts
function tabHead<T extends string>(title: string, about: string, tabs: Tab<T>[], active: T,
                                   load: () => Promise<Counts<T>>, tools: (HTMLElement | null)[]): HTMLElement   // not exported
export function planHead(active: PlanTab, ...tools): HTMLElement
export function libraryHead(active: LibTab, ...tools): HTMLElement
export function notesHead(active: NotesTab, ...tools): HTMLElement
```

`tabHead` returns `<header class="isle lib-head">` with an `<h1>`, a `<nav class="lib-tabs">` of links (`class="on"` and `aria-current="page"` on the active one) and, if any tools were passed, a `div.lib-tools`. Each tab has a hidden `span.lib-count`. When `load()` resolves, tabs with a non-zero count show the number, with a tooltip `"<n> <what>"` and the class `is-due` when `due` is set. A failed count request is ignored.

| Header | Title | Tab ids → label → hash | Counts from |
|---|---|---|---|
| `planHead` | Plan | `tasks` → Tasks → `#/plan`; `today` → Today → `#/home` | `GET /api/plan/counts` → `tasks_now` (on `tasks`) |
| `libraryHead` | Study | `study` → Lectures → `#/lectures`; `documents` → Documents → `#/library`; `goals` → Goals → `#/quest`; `review` → Review → `#/review`; `glossary` → Glossary → `#/glossary` | `GET /api/library/counts` → `documents`, `lectures`, `goals`, `review_due` (due), `terms` |
| `notesHead` | Notes | `notes` → All notes → `#/notes`; `journal` → Journal → `#/journal`; `ideas` → Ideas → `#/ideas`; `think` → Think → `#/think` | `GET /api/notes/counts` → `notes`, `ideas`, `think` (due) |

Note the ids: the Lectures tab's id is `study`, and the Study page's header function is `libraryHead`.

**To add a tab**

1. Add its id to the union type (`PlanTab`, `LibTab` or `NotesTab`) and a `{ id, label, href, hint }` entry to the array (`PLAN`, `LIBRARY`, `NOTES`). Order in the array is order on screen.
2. If it should show a number, add a field to the matching counts route in `server.py` and map it in the `load` callback.
3. Put `…Head("<id>", ...tools)` at the top of the page's view function.
4. In `main.ts`: add the route, and add the view name to `PART_OF` so the right menu entry lights up.
5. Optionally add a "Go to …" row in `commands()` in `palette.ts`.

## 4.13 The stylesheet (`web/static/styles.css`)

One file, about 2,000 lines (2,028 on 2026-11-26, after milestone 4.5), mostly one rule per line. No preprocessor, no `@layer`, no `@import`. It grew by appending: later blocks restyle earlier ones.

### Structure, in file order

| Block (its header comment) | Holds |
|---|---|
| top of file | `:root` defaults, base elements |
| `controls` | buttons, `.btn` variants (`primary`, `ghost`, `small`, `big`, `icon`, `on`), `.chip`, inputs, layout helpers (`.row`, `.row.wrap`, `.row.end`, `.stack`, `.field`) |
| `top nav + views` | `.topnav`, `.view`, `.view > section`, the Documents list |
| `reader` | the reader: paper, sentences, the pacer cursor, equations, the map and side panels, progress, popups (`.peek-pop`, `.sel-bar`), `.modal-back`, `.modal`, `#toasts`, `.toast` |
| `motion` | `data-hidden` pause, the global reduce-motion rule |
| `ambience (animated themes)` | `#ambience`, `#app` stacking, first `data-scene` washes |
| `Compass: Today, quests, focus` | Today, goals, the focus view |
| `Growth: topic map, teach-back, log, habits` | |
| `Lectures shelf`, `Lecture desk`, `Notebook`, `Journal`, notebook sizing, `Study: bright, creative notebook` | lecture and journal pages, paper styles, sticky notes |
| `Timer: calm, soft, slow` | the timer page, `.mini-timer`, `.timer-menu`; then, without a block header of their own, `.corner-dock`, `.starter-chips` (the routine starters in Plan) and the full-screen routine runner (`.modal-back.steady`, `.steady-*`) |
| `Calm pass: one soft look on every page` | a restyle of everything above: softer corners, entry animations, per-page touch-ups, `data-peek` |
| `Plan: tasks and routines`, `Notes: linked pages` | |
| `Floating islands: the scene is the room` | the island system, part one |
| `Floating islands, part two` | the `.isle` class; Stamina, Study shelf, Practice, Summary, the reader as islands |
| `Part three` | `--side-w`, the side menu, the Ctrl+K dialog, Plan's week board, note blocks, table and map, Settings; ends with a short `fixes found while looking at the pages` block |
| `Part four` | the Connected card |
| `Part five` | Overview (`hub-*`), with container queries; the dock at the foot of the menu |
| `Part six` | a narrow window: the dock becomes a bottom bar |
| `Part seven` | Think and Capture |
| `Part eight` | simple mode, right-to-left text (`unicode-bidi: plaintext`) |
| `Part nine` to `Part thirteen` | the tab header (`.lib-head`, `.lib-tabs`, `.lib-count`, `.lib-tools`) and the Overview cards merged to match the menu |
| `Part fourteen` | `.teach-replace`: the "keep this explanation as my answer" tick box of teach-back |
| `Part fifteen` | what an AI model wrote (`.ai-text`, `.ai-text-label`, `.ai-text p`, `ul` and `code`, `.ai-text-links`), and `.doc-flag`: the "flagged text" mark of a document |
| `Part sixteen` | "Where you left off" in the Start a session dialog (`views/resume.ts`): `.resume-box` (the panel), `.resume-facts` (the muted facts line), `.resume-ai` (the slot for the button or the recap), `.resume-brief` and its `li`, `.resume-quote` (a verified quote, italic) and `.resume-quote.unproven` ("no passage named", upright). The Explain and Digest dialogs and the Ask tab use `.resume-quote` too |
| `Part seventeen` | Explain a selected passage (`views/explain.ts`): `.explain-out` (the column that holds "Asking the model…", the answer and its buttons); `.explain-out:empty` and `.resume-slot:empty` are not displayed, so an Explain dialog with no answer yet and a Start a session dialog whose "Where you left off" has not arrived show no gap |
| `Part eighteen` | The Digest dialog of a document (`views/digest.ts`): `.digest-facts` (the words and minutes line), `.digest-outline` (the outline, no bullets, at most 14em high and scrolling; `li.lvl-2` and `li.lvl-3` indented 1em and 2em; `li.skipped .link`, a section left out of the digest, at 0.6 opacity), `.digest-ai` (the column for the button, the progress or the digest; its `progress` full width), `.digest` and its `li` (the digest itself, stretched to the dialog's width), `.digest-keys` (the keywords, wrapping anywhere), `.digest-parts` (the "Part by part" `details`: its `summary` in the UI font, its `ol` indented). Last, `button.resume-quote`: a verified quote that is a button (in the digest, and in the Ask tab) is a block, left-aligned, with no padding |
| `Part nineteen` | The Ask tab of the reader's side panel (`views/ask.ts`): `.ask-tab textarea` (full width, `box-sizing: border-box`, resizable up and down only), `.ask-out` (the column for "Asking the model…", the answer and the passages, a gap of 0.5em; `.ask-out:empty` is not displayed), `.ask-passages` and `.ask-cites` (the passage list and the ✓ quotes, no margin, indented 1.2em) and their `li` (0.3em apart). The answer box uses `.ai-text…` (Part fifteen) and the quotes `.resume-quote` (Parts sixteen and eighteen) |
| `Part twenty` | *Ask your library* on the Documents tab (`views/libraryask.ts`): `.library-ask` (the island, 1rem above and below), `.library-ask h2` (no margin), `.library-ask textarea` (full width, `box-sizing: border-box`, resizable up and down only), and `.library-ask .ask-cites a`, `.library-ask .ask-passages a` (the ✓ quotes and the match links, not underlined). The rest it borrows: `.ask-out`, `.ask-passages`, `.ask-cites` (Part nineteen), `.ai-text…` (Part fifteen), `.resume-quote` (Part sixteen) |
| `Part twenty-one` | The Study notes dialog (`views/studynotes.ts`): `.study-out` (the column for "Asking the model…" and the items, a gap of 0.5em; `.study-out:empty` is not displayed), `.study-items` (the list of items, indented 1.2em) and its `li` (a column, 0.6em apart; `li.unchecked`, an item with no checked passage, at 0.75 opacity), `.study-items textarea` (full width, `box-sizing: border-box`, resizable up and down only), `.study-reveal` (a quiz answer once shown, a column). The rest it borrows: `.seg` and `.field` for the two choices, `.ai-text…` (Part fifteen), `.resume-quote` (Parts sixteen and eighteen). Between `.study-items textarea` and `.study-reveal` sit the rules of the Plan my reading dialog (milestone 3.1, `views/readplan.ts`), under a plain comment: `.rp-docs` (the document list, at most 16em high and scrolling; `li.is-off` at 0.6 opacity), `.rp-doc` and `.rp-title` (one line, cut with an ellipsis), `.rp-days` (the plan's days; `li.is-empty` at 0.6 opacity), `.rp-day-head`, `.rp-warn` (a line with an accent bar on its left) and `.rp-unplaced` |
| `Part twenty-two` | Brainstorm with a model (milestone 3.2; `views/aibrainstorm.ts`, in the brainstorm sheet and the reader's Brainstorm dialog): `.ai-ideas input[type="text"]` (the topic box takes the rest of its row, at least 12em) and `.ai-ideas .ask-cites` (no top margin above an idea's passages). The rest it borrows: `.study-out` and `.study-items` with `li.unchecked` (Part twenty-one), `.ask-cites` (Part nineteen), `.ai-text…` (Part fifteen), `.resume-quote` and `.resume-quote.unproven` (Part sixteen) |
| `Part twenty-three` | Organize (milestone 3.3; `views/organize.ts` and the Documents tab): `.shelves` (the collection chips above the reading queue: a gap of 0.35em, 0.6em below; `.shelves:empty` is not displayed), `.doc-tags` (a document's tags in its meta line, muted), `.org-tags` (the tag chips in the dialog, wrapping, 0.35em apart) and `.org-list` (the suggested tags and related documents: no bullets, a column 0.4em apart). The chips use the earlier `.chip` rule (`controls`) and `.chip.on` (the chosen collection) |
| `Part twenty-four` | "Why did it say this?" (milestone 4.2; `views/why.ts`): `.why-link` (the link beside an AI label, 0.4em on its left), `.why-call` (one box per model call: a border and 8px corners) with its `summary` (a pointer, bold), `.why-facts` (a two-column grid of `dt` and `dd`: the label muted, `dd` with no margin), `.why-checks` and `.why-sources` (the lists of checks and sources, indented 1.2em), `.why-preview` (the start of what came back, smaller and muted), `.why-prompt pre` (the prompt word for word: wrapped, smaller, at most 20em high and scrolling) |
| `Part twenty-five` | The send preview (milestone 4.4; `aipreview.ts`): `.ai-preview pre` (the text that would be sent: wrapped, 0.85em, at most 22em high and scrolling, on `--panel2` with 0.6em padding and 6px corners). One rule; the rest of the dialog uses `.stack`, `.row.end`, `.btn.primary` and `.muted.small` |
| `Part twenty-seven` | Tidy and Plan chat (milestones 5.2 and 5.3; `views/tidy.ts`, `views/planchat.ts`, `plan.ts`). It comes **before** Part twenty-six in the file. `.tidy-list` (the tasks: a numbered column, 0.7em apart), `.tidy-item` (one task: a column), `.tidy-hints` (the hints, also Plan chat's flags: muted, 0.9em), `.tidy-fix` and `.tidy-model` (0.92em), `.tidy-split` (the parts and the routine steps), `.tidy-new mark` (the new words, a little apart), `.tidy-pre` (a proposed note: wrapped, 0.88em, at most 20em high and scrolling, on `--panel2`), `.chat-log` (the conversation: a column, at most 16em high and scrolling; not shown while empty), `.chat-turn` and `.chat-turn.model` (the model's turns muted), `.plan-tools` (the three buttons of the Plan header, 0.35em apart) |
| `Part thirty-one` | Fold the reader's side panels (2026-11-27): `.reader.panels-hidden .reader-body` (one column, so the page sits in the middle), `.reader.panels-hidden .map` and `.side` (not displayed), `.panels-toggle` (no wrapping; not displayed under 960 px, where the panels are already folded) |
| `Part twenty-six` | Delete on everything (milestone 5.1): `.review-tools` (the **Delete card** row), `.checkin-remove` (the ✕ beside the energy, muted), `.map-needs`, `.map-need` and `.map-need-x` (a "needs" link as a pill with its ✕), `.quest-delete` (pushed to the left of a goal's last row), `.journal-foot` (the status and **Delete this page** on one row), `.letters-all` and `.letters-rows` (the **Your letters** list), `.recent-focus`, `.recent-runs`, `.recent-main`, `.recent-what` (the Timer page's recent sessions; the ✕ at 60% until hovered or focused), `.why-deleted` (the line after **Delete this result**, with an accent bar) |

Some "Part" headers describe an earlier layout (for example "Part ten: Study and Tasks are tabs of Library too"; Tasks is now a tab of Plan). Trust the rules, not the headers.

### Variables on `:root`

| Variable | Default | Set by |
|---|---|---|
| `--bg`, `--bg2`, `--panel`, `--panel2`, `--border`, `--text`, `--muted`, `--accent`, `--accent-text`, `--pacer`, `--word`, `--sand`, `--sand-dark`, `--claim`, `--evidence`, `--definition`, `--confusing`, `--idea` | a sand-like palette | `applyTheme()` from the theme's tokens |
| `--tod` | `transparent` | `applyTimeOfDay()` |
| `--read-font`, `--read-size`, `--read-width`, `--read-leading` | Atkinson, 20px, 66ch, 1.7 | `applyComfort()` |
| `--ui-font`, `--radius` | Atkinson stack, 10px | CSS only |
| `--shadow` | a light shadow | CSS; heavier under `data-mode="dark"` |
| `--isle-a` | `94%` | CSS: `82%` under `data-glass="clear"`, `100%` under `data-glass="solid"` |
| `--isle-filter` | `none` | CSS: `blur(18px) saturate(1.15)` under `data-glass="clear"` |
| `--isle-radius` | `26px` | CSS only |
| `--isle-shadow` | `0 18px 44px -22px rgb(0 0 0 / 42%)` | CSS only |
| `--side-w` | `13.5rem` | CSS only; the width of the side menu |

### `data-*` attributes on `<html>` the stylesheet reacts to

| Attribute | Effect in CSS |
|---|---|
| `data-mode="dark"` | `color-scheme: dark`, a heavier `--shadow`, inverted equation pictures, a lighter `.error` colour |
| `data-energy="low"` | `saturate(0.85)` on the body; in the reader, sentences, paragraphs and sections after the current one are blurred and dimmed |
| `data-progress="bar"` | the reader shows the bar and hides the sand jar |
| `data-glass` | `--isle-a` and `--isle-filter` (above) |
| `data-scene` (presence) | early washes on the reader's panels and Today; the Look-at-the-view button is shown only with it; on a narrow window an otherwise empty dock is hidden without it |
| `data-hidden="1"` | every CSS animation is paused |
| `data-peek` (presence) | the page fades out, leaving the scene |

There is no attribute for the motion setting. Reduce-motion is handled by `@media (prefers-reduced-motion: reduce)` blocks, so choosing "Still" or "Off" in Settings stops the scene but not CSS transitions.

### The island system

The idea (from the block's own comment): there is no big page panel. Each piece of a page is its own nearly solid card with air between, and the theme's scene shows around the pieces.

Three layers of rules make it:

1. **The old default.** `.view > section, .view > article` are one solid panel (`background: var(--panel)`, border, 22px radius, `--shadow`).
2. **Pages split into islands.** `.view > section:where(.plan, .notes, .timer-page, .glossary-view, .ideas-view, .review, .quests, .library, .stats, .lectures, .quest-page, .topic-map, .practice, .structure)` makes the section itself transparent with no border, shadow or padding. Its children are then styled as islands.
3. **The island look**, one declaration block shared by a long selector list:

```css
background: color-mix(in srgb, var(--panel) var(--isle-a), transparent);
backdrop-filter: var(--isle-filter);
border: 1px solid color-mix(in srgb, var(--border) 45%, transparent);
border-radius: var(--isle-radius);
box-shadow: var(--isle-shadow);
```

   The first list ("Floating islands") names specific pieces (`.today-head`, `.timer-card`, `.plan-group`, `.notes-list`, `.term-card`, `.doc-row`, the menu, and so on), plus any `.view > section` that is **not** in a second `:where(:not(...))` list. That second list is the list from step 2 plus `.today, .focus, .home, .journal`. The second block ("part two") adds the generic class **`.isle`** and more named pieces, including the reader's top bar, pacer bar, map and side panel.

`.isle` also gets `padding: 1.2rem 1.5rem`, `box-sizing: border-box`, `min-width: 0`, and its first and last child lose their outer margin.

**How see-through panels work.** Settings → Panels writes `settings.glass`; `applyTheme()` copies it to `data-glass`; the three `:root` rules change `--isle-a` and `--isle-filter`; every island picks that up through the shared block. Solid is 100% panel colour, the default is 94%, see-through is 82% with an 18px backdrop blur. `test_see_through_islands_stay_readable` parses the 82% out of the stylesheet with a regular expression that expects the form `:root[data-glass="clear"] { … --isle-a: <number>% … }`; keep that rule in that shape.

The reader's paper, lecture pages and dialogs (`.modal`) are not islands and stay solid.

### Specificity tricks in use

- `:where(...)` in the `.view > section` rules adds no specificity, so a page class can still override.
- `:root:root .reader-top` (and similar) doubles the root pseudo-class to beat the earlier `:root[data-scene] .reader-top` wash.
- Selector lists like `.topnav, :root[data-scene] .topnav` repeat a rule at the higher specificity for the same reason.
- `!important` is rare: `[hidden] { display: none !important; }` (so `hidden` always wins over a `display` rule), the reduce-motion reset, and a handful of input restyles (`.find-input`, `.plan-add-input`, `.note-title`, `.hub-input`, `.task-items-add`, `.wk-add`).

### Layout with `:has()`

The stylesheet uses `:has()` to react to what is on the page, with no class toggling in TypeScript:

- `#app:has(> .topnav)` gets `padding-left: calc(var(--side-w) + 24px)` on a wide window, making room for the fixed side menu. The reader and the focus view have no `.topnav`, so they use the full width.
- `body:has(#app > .topnav) .corner-dock` places the dock at the foot of the side menu (wide) or as a bottom bar (narrow). `body:has(.reader) .corner-dock` moves it to the bottom right instead.
- `#app:has(> .lecture-root)` makes the lecture desk fill the window height.
- `.view:has(> section.plan)` and `.view:has(> section.think)` widen the page.

### Breakpoints and container queries

| Query | What changes |
|---|---|
| `min-width: 821px` | the menu is a fixed column on the left (`--side-w`), with group labels; the dock sits at its foot |
| `max-width: 820px` | the menu is a pill at the top that scrolls sideways; the dock is a bar at the bottom; `.view` gets bottom padding for it |
| `min-width: 821px` with `max-height: 980px` / `760px` | the side menu tightens its padding so it fits without scrolling |
| `max-width: 1180px`, `960px` | the reader narrows its side columns, then hides the map and side panel |
| `max-width: 1100px`, `700px` | Notes goes from three columns to two, then one |
| `max-width: 1000px` | the lecture desk hides the thumbnails and the notebook |
| `max-width: 900px` | Timer, Plan, Journal and Think go to one column |
| `max-width: 560px` – `720px` | small fixes per component (tab header, tasks, Overview head) |
| `prefers-reduced-motion: reduce` | one global rule cuts every animation and transition to 0.01 ms; several blocks also set `animation: none` or `transition: none` |

Container queries:

- `.view > section.hub { container-type: inline-size; }`. The Overview grid (`.hub-grid`, `.hub-parts`) changes at container widths 1000px, 600–999px and 760px. Because the side menu takes space, these follow the page's width, not the window's.
- `.page-sheet.slide` and `.page-sheet.nb-paper` are containers so that slide text and notebook paper can be sized in `cqw` units and scale with the page.

### Stacking order

| z-index | What |
|---|---|
| 0 | `#ambience` |
| 1 | `#app` |
| 5 | the side menu (inside `#app`) |
| 55, 60 | the reader's selection bar and peek popup |
| 100 | `.modal-back` |
| 150 | `.corner-dock` |
| 160 | `.timer-menu` |
| 170 | `.modal-back.steady` (the routine runner in Plan) |
| 200 | `#toasts` |

The dock (150) is above an ordinary modal (100), so the mini timer stays clickable over a dialog.

### Practical advice

- **Where to add CSS.** For a new page or feature, append a block at the end with a header comment in the same style. For a change to an existing component, edit its rules in place and then search the file for the same selector further down: later "Calm pass", "Floating islands" and "Part" blocks often restyle it, and the later rule wins at equal specificity.
- **A new island.** Give the element the class `isle`. Do not add to the long selector lists unless you cannot change the markup.
- **A new page made of islands.** Either wrap pieces in `.isle` inside a section whose class you add to *both* `:where(...)` lists (the "section disappears" list and the `:not(...)` list), or leave the section alone and it will be one island by default. Adding the class to only one list gives either a double panel or no panel.
- **Colours.** Use the theme variables and `color-mix(in srgb, …)`. A literal colour is only right for things that must not follow the theme (paper and sticky notes, slide text, the error toast). Any text colour on a panel must keep 4.5:1; the tests check the tokens, not your new rule.
- **Motion.** Keep transitions short and subtle; the global reduce-motion rule will cut them. Do not add a CSS animation that blinks faster than 3 times a second.
- **Hiding.** Use the `hidden` attribute (`h(..., { hidden: true })` or `el.hidden = …`). The `[hidden]` rule makes it reliable.
- **No inline `<style>` blocks or scripts in `index.html`.** Inline `style` attributes are fine.

## 4.14 Invariants and gotchas

**Safety**

- Never use `innerHTML` (or `insertAdjacentHTML`, `outerHTML`) with document, note or any server text. Nothing in `web/src/` does. Build with `h()`; strings become text nodes. Math goes through `mathEl()`, where KaTeX builds nodes with `trust: false`.
- The CSP blocks inline scripts, `eval`, remote scripts, remote fetches and remote fonts. A library must be bundled by esbuild or copied into `web/static/` by the build script. Adding a CDN link will silently fail.
- Scenes are the only run-time-loaded code. They come from `/themes/` on the same origin and are checked by `test_scene_rules`.
- No browser storage, with one exception: since 5.3 `views/planchat.ts` keeps the minutes a day you last said you have in `localStorage` (`readhold.planchat.minutes`, read and written inside `try`). Nothing else in `web/src/` uses `localStorage`, `sessionStorage` or IndexedDB. Settings go through `saveSettings()`; everything else is a route. Per-session memory (`lastKind` in `capture.ts`, `fired` in `reminders.ts`) is module state and is lost on reload by design.
- Links found in user text are shown, not fetched. `fetch` is only ever called with a path on the same origin.
- Keep the window's `dragover` and `drop` guard in `boot()`: without it a file dropped outside a drop zone opens as the window, with no CSP. A new drop zone handles its own `drop` and calls `preventDefault()` itself.
- A 428 is not an error to show: it is the send preview, and only `call()` in `api.ts` handles it. A feature that calls the server some other way (a raw `fetch`, as `InkPad.load()` does for ink) would get a 428 it cannot answer; AI routes must go through `api.*`.
- The send preview's text is shown with `h()` like every other server text. Never draw it as markup: it is document text.

**Never lose work**

- Save on the event, not on a button. For typing, wrap the save in `debounce()` so `flushPending()` covers it. A raw `setTimeout` save is invisible to `flushPending()`.
- A page that redraws itself while it has text boxes wraps the redraw in `keepTyped(root, draw)` (4.3), so text typed and not yet sent survives the redraw.
- `route()` flushes before it runs the old page's cleanup. A cleanup must not cancel a save that has just been flushed.
- Use `save()` for fire-and-forget writes; it retries. Use `api.*` when you need the result or want to show the error.
- Writes during unload rely on `keepalive`, which browsers cap at about 64 KB in total. `call()` only sets it for bodies under 60,000 characters. Large bodies (a long note, many ink strokes) may not finish if the window closes inside the debounce window.

**Routing**

- A view that adds listeners on `window` or `document`, timers, observers, a `timer.on()` subscription or an `InkPad` must return a cleanup, **and** its line in `route()` must pass it on (`keep(await …)`). Several lines do not.
- `route()` is async, and two calls can overlap: if the hash changes while a view is still loading, both calls finish. `routeSeq` sorts this out. Only the newest call may store its cleanup; `keep()` runs the cleanup of an older call as soon as its view function returns, and an error from an older call shows no message. The older view still draws into its own detached element (harmless). This covers only what the returned cleanup releases, and only views whose line uses `keep()`. The reader mounts straight into `#app`, which is not detached, so it also checks `current()` after loading and draws nothing when it is stale.
- Several modules redraw a page by dispatching a synthetic `hashchange` (`palette.ts`, `capture.ts`). That runs the full `route()`, including flush and cleanup.
- `route()` removes open modals from the DOM without resolving their promises. Code after `await modal(...)` may never run.
- Global key handlers must check `isTyping(e)` and modifier keys. `isTyping` is also true while any modal is open.
- Esc closes only the topmost `.modal-back`. Code that wants every dialog gone sends Esc once per open dialog (`whyDialog`'s link handler does, at most 5 times), or removes the backdrops itself as `route()` does.

**Performance**

- The pacer has one `requestAnimationFrame` clock and only calls `host.show()`. Do not add a second timer to it, and do not rebuild DOM from `show()`.
- The ambience has its own single rAF loop with a frame cap of 20 or 30 a second, pauses when hidden, and draws one frame in Still mode. Do not start animation loops elsewhere.
- `timer` listeners run twice a second while a run is active. Keep them to text and class updates.
- `mathEl()` caches by LaTeX source; always go through it rather than calling KaTeX directly.

**Theme work**

- After changing any `theme.json`, `scene.js`, the `--isle-a` rule or `sound.ts` recipe names, run `uv run pytest tests/test_themes.py`.
- A scene must draw a sensible finished picture when `state.still` is true and `dt` is 0.
- `applyTheme()` is safe to call at any time and is the only place that should set the theme's `data-*` attributes.

**Things in the code that may surprise you**

- Simple mode only drops the group labels of the menu. The class `is-simple` that `nav()` adds has no rule in the stylesheet.
- `Theme.motion` and the `sound` key of `theme.json` are not used by the front end.
- The fallback volume differs: `applyTheme()` passes `sound_volume ?? 0.35` to the ambient sound, while `chime()` uses `sound_volume ?? 0.6`. The server default is 0.35, so the fallbacks rarely apply.
- `InkPad.load()` uses `fetch` directly, not `api.get`.
- After 8 rounds of 428, `call()` throws "Not sent: you did not approve it.", the same sentence as for Cancel, although the reader approved every round.
- The preview dialog's title says "cloud model", and its first line names the cloud provider the server sent, also for a "local" model server on another computer.

### The comics look (`look`, `web/src/comics.ts`, styles.css Part twenty-eight)

Added on 2026-11-26, on the owner's request (chosen from a design canvas): three themes, **Comics: Classic** (`comics-classic`), **Comics: Classic Action** (`comics-action`) and **Comics: Manga Action** (`manga-action`). Each is one theme with two covers: light mode is the white cover, dark mode the black cover (the tokens; `tests/test_comics_themes.py` checks the light `bg` and `panel` are near white and the dark ones near black, and that `border`, drawn as ink, reaches 3:1 on both).

| Part | What it does |
|---|---|
| `theme.json` `look`, `look_variant` | `applyTheme()` (`themes.ts`) sets `data-look` and `data-look-variant` on `<html>`, or removes them for a theme without a look. `Theme` in `types.ts` has both as optional |
| styles.css Part twenty-eight | Under `:root[data-look="comics"]`: `--comic-head` (Bangers, bundled; Impact or Arial Black only if the font file is missing; Dela Gothic One for manga), `--comic-shadow` (`--border` on the white cover, `--accent` on the black), `--comic-line`, a small `--radius`, and islands with a hard shadow (`--isle-radius`, `--isle-shadow`). Ink borders and hard shadows on `.paper`, `.modal`, the cards and buttons (pressed buttons sink); comic headings (`h1`, `h2`, `.doc-title`, the brand); the current tab tilted (skewed for manga); manga buttons are pills; Classic titles get a yellow offset shadow. The reading text's font is never changed. `.s` fades its background in 0.9 s (the calm highlight). Reduce-motion turns off the effects and transitions |
| `comics.ts` | `comics.step(page)`, called from the reader's `show()` when the sentence changes while the pacer plays: in Classic Action and Manga Action, a sound effect (`SFX`) set by `textContent` in one fixed element, placed on the page's top-right corner (`getBoundingClientRect`, over the padding), and the page's ink shadow grows for 0.35 s (`comics-hit-a/b`; the page does not move). At most one every `MIN_GAP_MS` (2.5 s). `comics.burst()`, called from `boundary()` when a section ends: one big word (`BIG`: KA-POW!, or GO GO GO! as a band in manga) for 1.6 s, in every comics theme. Both do nothing unless the Motion setting is Gentle or Lively and reduce-motion is off; both elements ignore the pointer and are `aria-hidden`. `retrigger` swaps each element's own `-a`/`-b` class so a one-shot animation runs again |
| `scene.js` (three) | Classic: halftone dots drifting, a dot band rising with progress, the moment glow. Classic Action: the same plus rays turning about once in two minutes and speed streaks. Manga Action: screentone, 140 focus lines turning slowly around a clear centre, speed lines in the side margins, pink tone rising with progress. Dot patterns are made lazily on a frame with an `OffscreenCanvas` tile, in a `try`: a scene started while the window has no size (found in the app: it threw, and the scene stopped) skips the dots until it can make them |

### The calm themes: Clean, Meadow and Orbit

Added on 2026-11-27, on the owner's request (chosen from a design canvas: modern minimalist, nature and universe), each made to be easy on the eyes in light and dark mode. `tests/test_calm_themes.py` (12 tests) checks what "comfortable" means here: no pure white or pure black `bg` or `panel`, text on the panel between 7:1 and 16:1 (enough contrast without glare), a light `bg` that is light and a dark one that is dark, motion `gentle`, and a scene that uses `state.progress` and `state.still`. They need nothing new outside `themes/`: only `theme.json` and `scene.js`, like the other scene themes.

| Theme | `scene.js` |
|---|---|
| `clean` | The `bg` colour, a faint 24 px dot grid (an `OffscreenCanvas` pattern made lazily, in a `try`, like the comics dots) breathing over about 14 s, a 2 px accent line along the top at `w × progress`, and the moment glow. Nothing else moves |
| `meadow` | A sky gradient (pale blue to cream; navy to teal at dusk), a sun or moon in the right margin (at 93% of the width, so it shows beside the reading page) whose halo breathes over 9 s, two hill ridges (sums of sines) drifting at 4 and 7 px a second with a mist band between them, falling petals by day or dim fireflies at dusk, and 14 flowers standing in the near hill's grass at 90% of the height (above the reader's bottom bar): `round(progress × 14)` of them open, the rest are buds. The moment glow comes from the sun in the `word` colour. Positions come from a seeded random (`rng`), so a resize keeps the same meadow |
| `orbit` | A radial gradient from `bg2` to `bg`, dim stars (one per 9,000 px²; about a third twinkle over 12 s), two nebulae drifting over a minute, a sun low in the left margin (6% across, 84% down, above the reader's bottom bar) with three rings and three planets (one turn in 80, 160 and 280 s, the last one backwards), and a constellation of 7 stars in the right margin (at most 170 px or 9% of the width, 16 px from the edge, so it clears the page at 1280 px): `round(progress × 6)` links are drawn. The moment glow is violet, from the centre |

In Still mode every scene draws one resting frame that still shows your progress. The parts that show progress sit in the margins beside the reading page, because that is what stays visible in the reader with its panels folded (found in the app: the sun was half behind the page and the flowers behind the bottom bar). Found while building: Meadow's light `accent` (#3f7a4c) missed 4.5:1 on a see-through island over `sand` by a hair (4.4994); it is #3b7448.

The comic fonts are bundled since 2026-11-26: `copy-fonts.mjs` copies `bangers-latin-400-normal.woff2` and `dela-gothic-one-latin-400-normal.woff2` into `web/static/fonts/` and writes their `@font-face` rules into `static/fonts.css`. They are used only for headings, never for the reading text. Checked in the running app with a 1280×720 window: all three themes on both covers, the sound effect at the page's corner, the section burst; the front end has no automated tests.
