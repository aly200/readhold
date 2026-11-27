# 5. Front end: the reader, documents, review, practice and focus

This chapter covers sixteen files in `web/src/views/`:

| File | What it is | Address |
|---|---|---|
| `reader.ts` | The reading screen, class `Reader` | `#/read/<docId>` (optional `?s=<ord>`) |
| `reader-panels.ts` | The reader's side panel: Questions, Notes, Terms, Ask | part of the reader |
| `reader-dialogs.ts` | Every dialog and popover the reader opens | part of the reader |
| `resume.ts` | "Where you left off": the block at the top of the Start a session dialog (`resumeSlot`, `resumeBlock`) | part of the reader |
| `explain.ts` | The Explain dialog for a selected passage (`explainSelection`), with `aiIsOn` and `codeRange` | part of the reader |
| `digest.ts` | The Digest dialog of a document (`digestDialog`): the outline and reading time, and with AI on the digest, its progress and Stop | part of the reader |
| `ask.ts` | The Ask tab of the side panel (`askTab`): the passages that match a question, and with AI on an answer with checked quotes | part of the reader |
| `studynotes.ts` | The Study notes dialog (`studyNotesDialog`): with AI off a pointer to the summary sheet; with AI on a quiz, flashcards or notes drafted from your highlights or one section, each item resting on a checked passage, kept only when you choose it. Also the Brainstorm dialog of a document (`brainstormDialog`) | part of the reader |
| `aibrainstorm.ts` | `aiIdeasBox`: ideas from a model for a note, an idea or a document; since 2026-11-26 the ones that rest on a checked passage go straight into the brainstorm sheet, each as its own section, with Undo. Used by `brainstormDialog` here and by the brainstorm sheet (`think.ts`, chapter 7) | part of the reader, and of Think |
| `organize.ts` | The Organize dialog (`organizeDialog`): a document's tags (also its collections), tags suggested by code, related documents, and with AI on a model's suggestion | part of the reader and of the Documents tab |
| `why.ts` | The "Why did it say this?" panel (`whyDialog`) and the link that opens it (`whyLink`), beside the AI label of every AI feature; since 5.1 its **Delete this result** button | part of every AI feature |
| `summary.ts` | The summary sheet of one document | `#/summary/<docId>` |
| `library.ts` | Import and the reading queue (the "Documents" tab of "Study") | `#/library` |
| `libraryask.ts` | The *Ask your library* box on the Documents tab (`libraryAskBox`): the passages and notes that match a question across the library, and with AI on an answer with checked quotes, the model's steps and Stop | part of the Documents tab |
| `review.ts` | Daily card review (the "Review" tab of "Study"); since 5.1 **Delete card** | `#/review` |
| `practice.ts` | Mixed practice | `#/practice` |
| `focus.ts` | A focus session on one goal step, or a side goal | `#/focus/<stepId>`, `#/focus/side?text=…&min=…` |

How they fit together. `library.ts` imports a document and lists it. Opening a row goes to the reader. The reader loads the document and its annotations, runs a start dialog, and then drives the pacer (`web/src/pacer.ts`) and a session tracker (`web/src/session.ts`). While reading you make questions, highlights, notes and glossary terms; several of these become review cards on the server. `summary.ts` shows what you collected. `review.ts` shows the due cards. `practice.ts` asks a mixed set that the server builds from answered questions and defined terms. `focus.ts` is the non-reading sibling of the reader: a goal step with no document gets a time box instead of a text.

Naming: the app says "Goals", "main goal" and "side goal". The code says quest, main quest and side quest. This chapter uses the code names.

The router (`route()` in `web/src/main.ts`) treats two of these pages specially. For `read` it creates `new Reader()` and mounts it straight into `#app` with no side menu; it also hands `mount` a function that says whether this page change is still the newest one. For `focus` it appends `div.view.focus-view` with no side menu. The others get `nav(...)` plus `div.view`.

---

## 5.1 `Reader` (`reader.ts`)

```ts
export class Reader implements PacerHost {
  async mount(root: HTMLElement, docId: string, params: URLSearchParams, current: () => boolean = () => true): Promise<() => void>
  destroy(): void
}
```

`Reader` is the only class in these files. It implements `PacerHost` (from `pacer.ts`), so the pacer calls back into it. `reader-panels.ts` and `reader-dialogs.ts` are plain functions that take the `Reader` as their first argument `r` and read or change its public fields.

### Fields

| Field | Meaning |
|---|---|
| `doc: Doc` | The document with its sections, paragraphs and sentences (`GET /api/documents/{id}`) |
| `ann: Annotations` | `questions`, `highlights`, `notes`, `terms`, `acronyms` (`GET /api/documents/{id}/annotations`) |
| `idx: Idx[]` | One entry per sentence `ord`: `{ s, p, sec, secIdx }`. Built by `buildIndex()`. The main lookup table |
| `pacer: Pacer` | Made in the constructor with `this` as host |
| `session: SessionTracker \| null` | `null` until the start dialog is answered |
| `pass` | `0` = read everything (straight through), `1..3` = the three-pass plan |
| `isPaper` | True for `source_type` `pdf` or `arxiv`, or when any section has kind `abstract` |
| `focusView`, `panelsHidden`, `showHidden` | The Focus view toggle; whether the map and the side panel are folded away (from the `reader_panels_hidden` setting); whether hidden sections are shown |
| `root`, `topEl`, `mapEl`, `scroller`, `paper`, `sideEl`, `barEl`, `focusWordEl` | The shell elements (see layout) |
| `sideTab` | `"questions" \| "notes" \| "terms" \| "ask"` |
| `secEls[]`, `rendered[]` | One `<section>` per section, and whether its body has been filled |
| `sentEls: Map<ord, HTMLElement>` | The `span.s` of each rendered sentence |
| `parEls: Map<paragraphId, HTMLElement>` | The element of each rendered paragraph |
| `hlByOrd: Map<ord, Highlight[]>` | Highlights that cover a sentence. Built by `indexHighlights()` |
| `peeks`, `peekImages` | Text (and, for PDF equations, an image URL) for `figure:N`, `table:N`, `eq:N`, `ref:N`. Built by `buildPeeks()` |
| `backStack: number[]` | Sentences to return to with B / Backspace |
| private `curSentEl`, `curWordEl`, `curParEl`, `curSecEl` | The elements that carry the `cur` class now |
| private `readBuffer: Set<number>` | Sentences marked read but not yet sent to the server |
| private `observer` | The `IntersectionObserver` that fills sections |
| private `cleanup[]` | Functions run by `destroy()` |
| private `qPending` | Timer id while waiting for the digit after Q |
| private `enteredAt` | When the current sentence was entered (`performance.now()`) |
| private `gone` | Set by `destroy()`: you left this reader. `startFlow` then opens and starts nothing more |
| private `timeBoxShown` | The "Time box done" dialog was shown |
| private `savePosition` | `debounce(…, 1200)` around `POST /api/documents/{id}/position` |

### Lifecycle

`mount()` does this, in order:

1. Loads the document and the annotations in parallel. Then it calls `current()` (given by the router; true while this is still the newest page change). If it is false, you moved to another page while the document loaded: `mount` returns an empty cleanup and draws nothing.
2. Sets `isPaper` and `pass`. A paper starts in `doc.current_pass` (the column defaults to 1). If the paper is on pass 1 but has a saved position or a `?s=` parameter, `pass` is set to 0 for this visit so the resume point is not skipped. This override is not saved.
3. `buildIndex()`, `buildPeeks()`, `indexHighlights()`.
4. Copies settings into the pacer: `wpm`, `pacer_mode`, `state.energy`, `tts_voice`, `tts_rate`.
5. `applyComfort(comfortFor(doc.source_type))`.
6. `renderShell()`, `renderSections()`, `renderMap()`, `renderSide()`.
7. Picks the start sentence (see "Position").
8. `bindKeys()`, `bindAway()`.
9. Starts a 4-second interval that calls `flushRead()`.
10. Adds a `beforeunload` handler: `flushRead(true)` and `session.flushOnUnload()`.
11. Shows `doc.import_warning` as a toast, if any.
12. After 50 ms, runs `startFlow(params)`.
13. Returns `() => this.destroy()` to the router.

`startFlow()` stops at its start, and again after each dialog, when `gone` is set:

1. If there are unresolved `confusing` highlights and there is no `?s=` parameter, awaits `dlg.confusionFirst()`.
2. Awaits `dlg.sessionSetup()`. Sets `state.energy` and `pacer.energy` from the answer and calls `applyTheme()`.
3. If the answer is `parked`, goes to `#/home` and stops. No session is created.
4. Otherwise `SessionTracker.start(...)` (which does `POST /api/sessions`). If `gone` was set while the session was being created, it is closed at once with `session.leave()`. Otherwise `updateTop()`.

`destroy()`: sets `gone`, then `pacer.destroy()`, `flushRead(true)`, `session.leave()`, disconnects the observer and runs every `cleanup` function. `SessionTracker.leave()` (in `session.ts`) stops the tracker's timers and sends the counters with `ended: true`; it does nothing if the session was already ended by the end dialog. So leaving the reader in any way ends the session.

### Layout

`renderShell()` builds this tree inside `root`:

```
div.reader
  header.reader-top          topEl    back link, title + why, .timer, progress widget, End session
  div.reader-body
    nav.map                  mapEl    section map
    main.page                scroller the scrolling column
      article.paper          paper    the text
    aside.side               sideEl   Questions | Notes | Terms | Ask
  footer.pacer-bar           barEl    pacer controls
  div.focus-word             focusWordEl (hidden unless playing in focus mode)
```

The three columns are `mapEl`, `scroller` and `sideEl`. `renderShell()` also attaches four listeners to `scroller`: `click` → `onPaperClick`, `mouseover` → `onPaperHover`, `mouseup` → `dlg.selectionToolbar` (on the next tick), and `scroll` → `session.activity()`.

**Top bar** (`renderTop`). "← Home" links to `#/hub`. Before **End session** sits `button.panels-toggle`: "Hide panels" or "Show panels" (`aria-pressed`, the label and title say Ctrl+\\), which calls `setPanelsHidden`. `updateTop()` writes `"<m:ss> left"` into `.timer` from `session.timeBoxMs - session.focusedMs`.

**Map** (`renderMap`). The head line shows section count, estimated minutes (`words of text/list sentences ÷ settings.wpm`) and question count. For papers it shows four pass buttons. Each section is `li.map-sec` with `data-i`, a `button.map-link` (title, kind label, question numbers as `.q-dot`), a `.map-bar` showing percent read, and a `button.map-skip` that calls `toggleBackground(i)`. The bottom `.map-actions` hold "Digest" (`digestDialog(this)`, section 5.6; shown with AI on and off, tooltip "The outline, the reading time and, with AI on, a summary"), "Summary sheet", "Study notes" (`studyNotesDialog(this)`, section 5.6; shown with AI on and off, tooltip "Notes, flashcards or a quiz from your highlights or a section"), "Brainstorm" (`brainstormDialog(this)`, section 5.6; tooltip "Ideas that connect your highlights here with your notes"), "Organize" (`organizeDialog(this.doc.id, this.doc.title)`, section 5.6; tooltip "Tags (your collections) and related documents"), "Fix structure", the clean-view toggle and "Explain it". `renderMapBars()` updates only the bar widths; `flushRead()` calls it.

**Pacer bar** (`renderBar`). Previous, play/pause (`button.play`), next, a mode `<select>`, the `.wpm` group with `.wpm-val`, an energy `<select>`, two `label.toggle` checkboxes ("Read aloud (R)", "Focus view (F)"), "Aa" (comfort) and "Keys (?)". The bar is rendered once. Later updates find controls by position (see Gotchas).

### Rendering sections and sentences

`renderSections()` clears `paper` and builds, for every section, a `section.sec` with:

- classes `kind-<kind>`, `background` (skippable), `collapsed` (hidden in clean view), `out-of-pass`;
- `data-i` and `id="sec-<i>"`;
- a `header.sec-head` with the title (`h2`, or `h3` when `level > 1`), a `.kind-badge`, a `.bg-badge` for background sections and a "Show" button for collapsed ones;
- an empty `div.sec-body`.

It ends with `div.doc-end` and an "Explain it in three sentences" button.

**Only sections near the viewport are filled.** The mechanism:

- Each `sec-body` starts empty with an estimated `min-height`: `max(40, chars / line_width * font_size * line_height)` pixels, so the scroll bar has roughly the right length before the text exists.
- One `IntersectionObserver` (root `scroller`, `rootMargin: "1800px 0px"`) watches every non-collapsed section.
- When a section comes within 1800 px of the visible area, the callback calls `ensureRendered(i)`.
- `ensureRendered(i)` returns at once if `rendered[i]` is set. Otherwise it removes the `min-height`, renders every paragraph into a `DocumentFragment`, appends it, and stops observing that section.
- Code that needs a sentence element calls `ensureRendered` first: `show()`, `jumpTo()`, `scrollTo()`.

Sections are filled once and never emptied again. A collapsed section is not observed; it is filled only if something jumps into it.

`renderParagraph(p)` picks the element by `p.kind`:

| Kind | Element |
|---|---|
| `code` | `pre.p.code`, sentences joined by newlines, as one text node. There are no `span.s` elements inside, so nothing in it is in `sentEls`. The style keeps the text as written (`white-space: pre`, fixed-width font, sideways scroll for long lines). A paragraph of a code file (`source_type` `code`) is one stored sentence that keeps its indent |
| `equation` | `renderEquation()` (below) |
| `reference` | `div.p.ref-item` with `mathText(text)` |
| `list` | `div.p.li` of sentences |
| anything else | `div.p.<kind>` of sentences |

It sets `data-pid`, stores the element in `parEls`, and prepends `span.q-badges` (`Q1`, `Q2`, …) for each question whose `paragraphs` include this paragraph.

`renderEquation()` has three cases. With `p.asset` it returns `figure.p.eq.eq-img` holding an `<img>` served from `/api/documents/{id}/assets/{name}` (`assetUrl()`); the `onload` handler scales it to the reading font size. Otherwise, if `displayEquation(text)` matches, it draws KaTeX with `mathEl(tex, true)` plus an `.eq-no` tag. Otherwise it falls back to `mathText(text)`.

`renderSentence(s)` returns `span.s` with `data-o="<ord>"` (and class `read` if already read). Inside:

- Every word is a `span.w`. Words come from `wordsWithIndex()` in `math.ts`, which keeps a whole formula as one word. A formula word gets class `has-math` and is drawn with `mathText`.
- A word that matches a key in `ann.acronyms` (also tried without a trailing "s", and not if the word contains "(") gets class `acr` and `data-acr`.
- `REF_RE` finds "Fig. 3", "Table 2", "Eq. (4)" and citation groups like `[3, 5–7]`. If the target is in `peeks`, the words of that match are wrapped in `span.peek` with `data-peek` (`figure:3`, `table:2`, `eq:4`, or `refs:3, 5–7`) and `tabindex="0"`.
- Spaces between words are separate text nodes.

It stores the element in `sentEls` and calls `decorateSentence()` for highlights and note marks.

`rerenderParagraphOf(ord)` rebuilds one paragraph in place (used after tagging or deleting a question so the `Q` badges change) and then calls `show()` again to restore the `cur` classes.

### Which sentences the pacer visits

`isPaced(ord)` decides. In order:

1. No index entry → false.
2. Section is `hidden`, `settings.clean_view` is on and `showHidden` is off → false.
3. Pass 1: text or list paragraphs in `abstract`/`conclusion` sections, plus every `caption` paragraph.
4. Otherwise only `text` and `list` paragraphs are paced.
5. Pass 2: sections of kind abstract, intro, method, results, discussion, conclusion or `other`.
6. Pass 3: everything textual, background included.
7. Pass 0: everything textual, except `background` sections when `settings.skip_background` is on.

`next(ord)` and `prev(ord)` walk to the nearest paced sentence. `isPacedOrNext(ord)` returns `ord` itself or the next paced one. When `mount` is asked for a sentence that is not paced (a code block, a caption, an equation), it also calls `scrollToBlock(ord)`, which scrolls the page to that paragraph and marks it for a moment; the pacer still starts at the next paced sentence.

### Position: save and restore

- **Save.** `show()` calls `savePosition(ord)` each time the current sentence changes. It is debounced 1200 ms and sends `POST /api/documents/{id}/position {position}` through `save()` (which retries). Because it uses `util.debounce`, `flushPending()` in the router and on page close sends a waiting value at once. The server writes `documents.position`.
- **Restore.** `mount()` takes `?s=<ord>` if present, otherwise `doc.position`, clamps it to `0 … idx.length-1`, passes it through `isPacedOrNext`, then calls `pacer.setPosition(start)` and `scrollTo(start, false)`.
- **`?s=`** is produced by the links on the summary sheet (`go()` in `summary.ts`). It also skips the "Confusion first" dialog.
- `scrollTo()` puts the sentence one third down the scroller. `keepInView()` scrolls only when the sentence leaves the band between 15 % and 70 % of the height. Both use `behavior: "auto"` when the system asks for reduced motion.
- `jumpTo(ord, remember = true)` pushes the old position on `backStack`, sets the pacer to the nearest paced sentence, scrolls to the exact target, and adds class `flash` for 1.2 s. `backJump()` pops the stack. `jumpToSection(i)` jumps to the first paced sentence of the section if it is inside that section, else to the section's first sentence.

### Read marks

`done(ord)` (called by the pacer at the end of a sentence, and by `manualStep(1)` for the sentence you step away from) sets `s.read = 1`, adds the ord to `readBuffer`, increments `session.sentencesRead`, adds class `read`, and calls `updateProgress()`.

`flushRead(unload = false)` sends the buffer with `POST /api/documents/{id}/read {ords}`. In normal use it goes through `save()` and puts the ords back in the buffer if every retry fails. On unload it uses a raw `fetch` with `keepalive: true`. It runs every 4 s, at the end of the document, in `endSession`, in `explainIt` and in `destroy()`.

### Passes

`setPass(n)`:

- sets `this.pass`;
- for `n > 0` saves `PATCH /api/documents/{id} {current_pass: n}` (the server accepts 1–3 only, so "All" is never saved);
- toggles `out-of-pass` on each section and re-renders the map;
- moves the pacer to the first paced sentence (from the start for passes 1–3, from the current sentence for "All");
- shows a toast.

`inPass(sec)` is the per-section test used for the `out-of-pass` class in both the paper and the map.

### Energy modes

Energy is `low`, `medium` or `high`. It is chosen in the start dialog and can be changed in the pacer bar (`setEnergy`). `setEnergy` sets `pacer.energy` and `state.energy`, calls `pacer.invalidate()` and `applyTheme()`. It does not write to the server.

- The pacer multiplies speed by `ENERGY_SPEED` (`low: 0.85`, `medium: 1`, `high: 1.15`).
- `applyTheme()` (in `themes.ts`) sets `data-energy` on the root element. The stylesheet uses `:root[data-energy="low"]` to blur and fade the text after the current sentence, paragraph and section.

### Comfort settings

`applyComfort(c)` (in `state.ts`) sets four CSS variables on the root element: `--read-font`, `--read-size`, `--read-width`, `--read-leading`. `comfortFor(sourceType)` merges the global settings with `settings.comfort_by_type[sourceType]`. The reader applies it in `mount()`. The router resets it to the global values (`applyComfort(comfortFor(""))`) on every route change. The "Aa" button opens `dlg.comfortPopover` (section 5.5).

### Progress widget

`progressWidget()` and `setProgress(scope, ratio, label)` are exported functions at the bottom of `reader.ts`. The widget is `div.progress` (`role="progressbar"`) with an SVG jar (`svg.jar`, a `rect.sand` clipped by `#jar-clip`), a `div.bar > span`, and `span.pct`. `setProgress` moves the sand (`y = 37 - 28 * pct / 100`), sets the bar width, the percent text, `aria-valuenow` and the tooltip.

`updateProgress()` computes the ratio:

```
ratio = (read + answered * 5) / (total + questions * 5)
```

`total` and `read` count sentences in `text`/`list` paragraphs whose section is neither `background` nor `hidden`. Each question weighs as five sentences. The same call sends `ambience.update({ progress: ratio, answered })`.

### Skip-background and clean view

- **Skip background.** A section with `background = 1` gets class `background` and a "skippable" badge. In pass 0 the pacer skips it when `settings.skip_background` is on. `toggleBackground(i)` flips the flag, saves `PATCH /api/sections/{id} {background}`, toggles the class and re-renders the map.
- **Clean view.** A section with `hidden = 1` (set at import, for example references) is collapsed when `settings.clean_view` is on and `showHidden` is off. `toggleHidden()` flips `showHidden` (or, if `clean_view` was off, turns it on in memory only), then calls `renderSections()`, `renderMap()` and `pacer.setPosition(pacer.ord, 0)`. This is a full re-render of the paper, done only on this user action.

### Other reader behaviour

- **Focus view** (`setFocusView`, key F, the checkbox in the pacer bar). Toggles class `focus-view` on `div.reader`. The stylesheet rule `.reader.focus-view .paper …` fades every paragraph except the current one, the section heads and the document title to opacity 0.22.
- **Hide panels** (`setPanelsHidden`, Ctrl+\\, the button in the top bar; added on 2026-11-27). Toggles class `panels-hidden` on `div.reader`, saves `reader_panels_hidden` with `saveSettings`, redraws the top bar (`renderTop`, then `updateTop` so the timer keeps its text) and puts the keyboard back on the button. `renderShell` reads the setting, so the choice holds after a restart. Ctrl+\\ is checked at the top of the key handler, before the rule that ignores keys with Ctrl, and it works while typing; the reader has no side menu, so the app's own Ctrl+\\ (which needs `#app > .topnav`) never fires here. Styles: Part thirty-one of `styles.css` (chapter 4).
- **Distraction guard** (`bindAway`). Window `blur` or a hidden tab pauses the pacer (not counted as a pause) and calls `session.distracted()`. Coming back shows a toast with the first 90 characters of the current sentence and flashes it. It does not resume by itself.
- **Time box** (`onSessionTick`). Called every second by the session tracker. When `focusedMs >= timeBoxMs` it sets ambience mode `break`, pauses, and opens `dlg.timeBoxDone`. "5 more minutes" adds 5 to `session.info.time_box_min` and saves `PATCH /api/sessions/{id} {time_box_min}`.
- **Personal slow-down** (`sendSlow`, `learnFrom`). `sendSlow(ord, signal)` updates `s.personal` locally (`personal * 0.6 + signal * 0.4`, clamped to −0.3 … 0.6), invalidates the pacer cache, and posts `/api/documents/{id}/slow {ord, signal}`. Signals sent: `−0.3` when the pacer was playing and you left a sentence in under 40 % of its expected time (`learnFrom`); `0.5` for the sentence you land on after a manual step back; `0` for the sentence you step back from.
- **Speed ramp** (`rampSpeed`). Called after a recall answer is saved. If `settings.speed_ramp` is on and `pacer.pauses <= 2`, wpm rises by 5 % (never below `settings.comfort_wpm`, never above 900, the same ceiling as `changeWpm`) and is saved with `PUT /api/settings {wpm}`. The pause counter is reset either way.

---

## 5.2 Keyboard shortcuts

### Reader (`bindKeys` in `reader.ts`, on `document`)

All of these are ignored when `isTyping(e)` is true (focus in an input, textarea, select or contenteditable, or any modal open) or when Ctrl, Meta or Alt is held.

| Key | What it does | Handler |
|---|---|---|
| Space | Play / pause the pacer | `pacer.toggle()` |
| → or ↓ | Next paced sentence; marks the one you leave as read | `manualStep(1)` |
| ← or ↑ | Previous paced sentence; records a rewind signal | `manualStep(-1)` |
| Q, then 1–9 within 2 s | Tag (or untag) the current paragraph as answering question n | `qPending` timer, then `dlg.tagParagraph(r, n-1)` |
| 1 2 3 4 5 | Highlight the selection, or the current sentence: claim, evidence, definition, confusing, idea. Same key again removes it | `HL_KEYS` → `selectionRange()` → `highlight()` |
| B or Backspace | Go back to where you were before the last jump | `backJump()` |
| N | Margin note on the current sentence | `dlg.addNote` |
| G | Guess gate for the selected text | `dlg.guessGate` |
| I | Quick idea | `dlg.quickIdea` |
| F | Toggle Focus view | `setFocusView` |
| Ctrl+\\ | Hide or show the map and the side panel | `setPanelsHidden` |
| R | Toggle read aloud | `setReadAloud` |
| W | Cycle sentence → word → focus-word pacer | `setMode` |
| + or = | 10 wpm faster | `changeWpm(10)` |
| - | 10 wpm slower | `changeWpm(-10)` |
| E | End session dialog | `dlg.endSession` |
| ? | Keyboard help | `dlg.keyHelp` |

While `qPending` is set, a digit is consumed by the tagging branch before the highlight keys are checked.

### Inside reader dialogs (`reader-dialogs.ts`, `util.ts`)

| Key | Where | What it does | Handler |
|---|---|---|---|
| Esc | Any modal | Closes it with `undefined`; with one dialog over another, only the top one (since 4.2) | `modal()` in `util.ts` |
| Enter | Start a session, in the question input | Starts | `sessionSetup` |
| Enter | End session, in the next-step and output inputs | Save & stop | `endSession` (`ok`) |
| Ctrl+Enter | Recall textarea | "Compare with the text", then "Save answer" | `recall` |
| Ctrl+Enter | Guess gate, guess textarea | Reveal | `guessGate` |
| Enter | Guess box in the Terms tab | Opens the guess gate | `termsTab` |
| Enter | Claim builder, the question input | Adds the question | `claimBuilder` (`add`) |
| Enter | New question input in the Questions tab | Adds the question | `questionsTab` (`add`) |
| Enter / Ctrl+Enter | `askText` dialogs (single line / multiline) | OK | `askText` in `util.ts` |

### Other pages

| Key | Page | What it does | Handler |
|---|---|---|---|
| Enter | Documents: the drop zone when focused | Opens the file picker | `libraryView` (`drop`) |
| Space | Review, before reveal | Shows the answer | `onKey` → `reveal` in `reviewView` |
| 1 2 3 4 | Review, after reveal | Again, Hard, Good, Easy | `onKey` → `rate` in `reviewView` |
| Enter (no Shift) | Practice, before reveal | Reveals. Shift+Enter is a new line in the attempt | `onKey` → `reveal` in `practiceView` |
| 1 2 3 | Practice, after reveal | Missed, Partly, Got it | `onKey` → `rate` in `practiceView` |
| Space | Focus | Pause / resume the clock | `onKey` → `togglePause` in `focusView` |
| P | Focus | Park a thought | `onKey` → `parkThought` |
| D | Focus | Done dialog | `onKey` → `finish("done")` |
| Enter | Focus: Done dialog, the output input | Save | `finish` |

Review ignores keys while a `.modal-back` exists, and ignores 1–4 when Ctrl, Meta or Alt is held. Practice and Focus use `isTyping`.

---

## 5.3 Highlights, notes and the selection bar

### Highlights

Five kinds (`HlType`): `claim`, `evidence`, `definition`, `confusing`, `idea`. Keys 1–5 map to them through `HL_KEYS` in `util.ts`.

```ts
async highlight(type: HlType, from = this.pacer.ord, to = from): Promise<void>
```

`highlight()` is a toggle:

- If a highlight of the same type with exactly the same `sentence` and `end_sentence` exists, it calls `DELETE /api/highlights/{id}` and removes it from `ann.highlights`.
- Otherwise it calls `POST /api/highlights {document_id, sentence, end_sentence, type}` and pushes the returned row. The server fills `text` from the sentences. For `idea` the server also inserts a row in `ideas`. The server syncs review cards for highlights (`services.sync_highlight_card`).
- Then `indexHighlights()`, `decorateSentence(o)` for each covered sentence, and `renderSide()`.

A highlight covers whole sentences. With a text selection, `selectionRange()` turns it into `[firstOrd, lastOrd]` by finding the `.s` ancestor of each end of the selection.

**Drawing.** `decorateSentence(ord)` removes `hl` and every `hl-<type>` class, then adds `hl` and `hl-<type>` for the last highlight in `hlByOrd.get(ord)`. Only one type colours a sentence, even if several highlights overlap.

More actions live in the Notes tab (`hlItem` in `reader-panels.ts`):

| Action | Call |
|---|---|
| "Note" / "Name the term" | `PATCH /api/highlights/{id} {note}` |
| "Make blank card" (evidence only) | `dlg.clozePicker` → `PATCH /api/highlights/{id} {cloze}` |
| "Got it now" / "Reopen" (confusing only) | `PATCH /api/highlights/{id} {resolved}` |
| "Remove" | `r.highlight(type, sentence, end_sentence)` (the toggle) |

### Notes on sentences

- **Add.** `dlg.addNote(r)` (key N) asks for text with `askText` (multiline) and calls `POST /api/notes {document_id, sentence, text}` for `pacer.ord`.
- **Draw.** `decorateSentence` appends `button.note-mark` ("✎") inside the sentence span, with `data-note="<ord>"` and the note texts as tooltip.
- **Open.** A click on `.note-mark` is caught in `onPaperClick` and opens `dlg.showNotes(r, ord)`: each note with "Edit" (`PATCH /api/notes/{id} {text}`) and "Delete" (`DELETE /api/notes/{id}`), and "Add another" (moves the pacer to that sentence, then `addNote`).
- **A note a model wrote.** A note with `origin === "ai"` (saved from an explanation, section 5.6) gets `div.ai-text-label` above its text in `showNotes`: "Written by the AI model. Edit it to make it yours." After a successful "Edit" the page sets `n.origin = ""`, as the server did (`PATCH /api/notes/{id}` empties the column when the text changed), so the label is gone the next time the dialog opens. Pressing OK in the edit box without changing the text also sets `n.origin = ""` in the page, but the server keeps `ai` then (it clears `origin` only when the text really changes): the label is gone until the document is loaded again, and then it is back. The Notes tab shows the label too (section 5.5); the summary sheet does not.

### Clicks and hovers in the paper

`onPaperClick` checks, in order: `.note-mark` → notes dialog; `.peek` → pinned peek; a non-empty selection → nothing; a `.s` → `pacer.setPosition(ord, wordIndex)` and push the old position on `backStack`. So a click on a word restarts the pacer from that word.

`onPaperHover` opens an unpinned peek for `.peek` and an acronym tooltip for `.acr`.

### The selection bar

`dlg.selectionToolbar(r)` runs after every `mouseup` in the scroller. If there is a non-empty selection inside `r.paper`, it appends `div.sel-bar` (`role="toolbar"`) to `document.body`, 44 px above the selection:

| Button | Shown when | Does |
|---|---|---|
| "Guess (G)" | the selection has six words or fewer | `guessGate(r, text)` |
| "1 claim" … "5 idea" | the selection maps to sentences | `r.highlight(type, from, to)` |
| "→ Note" | the selection maps to sentences | `quoteToNote(r, text, from)` |
| "Explain" | AI is on (`aiIsOn()`: `state.settings.ai_mode` is `local` or `cloud`) and there is a range of fewer than 12 sentences apart (`forAi[1] - forAi[0] < 12`, the server's `MAX_STRETCH`). The page does not check that the range is inside one paragraph; the server does (422 "Select text inside one paragraph.") | `explainSelection(r, forAi, text)` (section 5.6) |

The range for Explain is `forAi = range ?? codeRange(r)`: `r.selectionRange()` when the selection starts and ends inside sentence spans (`.s`), else `codeRange`. A code block is one `pre.p.code` with no sentence spans, so `selectionRange()` is `null` there; `codeRange(r)` (`explain.ts`) finds the `pre.p.code[data-pid]` around the selection's anchor node and returns `[ord, ord]` of that paragraph's sentence (a code paragraph is one sentence). That is why a selection inside code shows "Explain" but no highlight buttons. With AI off `forAi` is `null` and the bar is as before.

Each button calls `preventDefault` on `mousedown` so the selection survives the click. A `selectionchange` listener removes the bar when the selection becomes empty. The router also removes any `.sel-bar` on route change.

---

## 5.4 The pacer integration

`pacer.ts` owns the clock. The reader owns the DOM. The contract is `PacerHost`:

| Host method (in `Reader`) | Called by the pacer when | What the reader does |
|---|---|---|
| `sentence(ord)`, `words(ord)` | It needs timing data | Returns from `idx`; `words` uses `tokens()` (math-aware) |
| `next(ord)`, `prev(ord)` | It advances or steps | Applies `isPaced` |
| `show(ord, wordIdx)` | The cursor moves | Moves the `cur` classes (below) |
| `done(ord)` | A sentence was read to its end | Marks it read |
| `boundary(from, to)` | The next sentence is in another section | Returns true to pause for checkpoints |
| `end()` | There is no next sentence | `flushRead()`, then `dlg.explainIt(r, true)` |
| `playState(playing)` | Play or pause | Updates the button, ambience and focus word |

**`show()` only toggles classes.** When the sentence changes it moves `cur` from the old `span.s` to the new one, and the same for the paragraph (`.p.cur`), the section (`.sec.cur`) and the map entry (`.map-sec.cur`). It then calls `keepInView` and `savePosition`. When the word changes it moves `cur` between `span.w` elements. Nothing in the paper is rebuilt. Two side effects go beyond class toggles: a section change re-renders the side panel if the Questions tab is open (the suggested questions depend on the section), and in focus mode `showFocusWord()` rewrites the three spans of `focusWordEl`.

**Play and pause.** `pacer.toggle()` is bound to Space and the play button. `playState()` toggles class `playing` on `root`, sets ambience mode to `reading` or `idle`, swaps the button glyph and label, shows or hides `focusWordEl`, and calls `session.activity()`. The reader pauses with `pacer.pause(false)` when the pause is not the user's choice (dialogs, window blur, time box), so it does not count against the speed ramp.

**Modes** (`setMode`, key W, the mode select). Saved with `PUT /api/settings {pacer_mode}`.

| Mode | Clock | What is lit |
|---|---|---|
| `sentence` | `sentenceMs()`: words at your wpm, scaled by density and `personal`, at least 900 ms, plus 200 ms | The sentence only (`wordIdx` is `null`) |
| `word` | `wordMs()` per word: length, density, `personal`, extra time after punctuation | The sentence and the current word |
| `focus` | Same as word mode | Same, plus the word shown large in `div.focus-word` with a `.pivot` letter at 35 % of its length |

The pacer runs one `requestAnimationFrame` loop (`startClock`). A frame is capped at 250 ms so a background tab does not skip ahead.

**Read aloud** (`setReadAloud`, key R). `pacer.setReadAloud(on)` hands the clock to the speech engine (`Tts` in `tts.ts`): the sentence is spoken from the current word, each word boundary calls `host.show(ord, wordIdx)`, and the end of speech calls `finishSentence()`. Formulas are spoken in words through `spoken()` in `math.ts`. In read-aloud the word is lit even in sentence mode. If no voices are found the reader shows a toast pointing to Settings.

**Section boundaries.** `boundary(from, to)` asks `dlg.sectionCheckpoints()` for steps. If there are any, it schedules `dlg.runCheckpoints()` and returns true; the pacer moves to the next sentence and pauses. Manual steps (arrow keys) do not call `boundary`, so they never open checkpoints.

**Speed.** `changeWpm(delta)` clamps to 80–900, invalidates the pacer cache, updates `.wpm-val`, and saves `PUT /api/settings {wpm}`.

**Session tracking.** `SessionTracker` ticks every second. Time counts as focused when the window is visible and focused and either the pacer is playing or there was activity in the last 60 s. The reader calls `session.activity()` on keys, clicks, scrolls, manual steps and play-state changes. The tracker saves `PATCH /api/sessions/{id}` every 15 s (`flush`), on unload (`flushOnUnload`), and once more with `ended: true` from `end()` (the End session dialog) or from `leave()` (`Reader.destroy()`, when you leave any other way).

---

## 5.5 Side panel (`reader-panels.ts`)

`renderSidePanel(r)` clears `r.sideEl` and draws a `div.tabs` row and a `div.tab-body`. Four tabs: Questions, Notes, Terms and Ask. Tab counts: questions; highlights + notes; non-concept terms + acronyms; Ask has none. The whole panel is rebuilt on every change (`r.renderSide()`), whichever tab is open, so the Ask tab is drawn again too; it keeps its state in `memo` (below).

### Questions tab (`questionsTab`)

- **Session question.** If the session has one, a `div.job` box shows it.
- **Suggested questions.** For the current section it fetches `GET /api/templates?kind=<section kind>`. Templates already used as a question text, or dismissed, are dropped. The rest are shown in `div.templates`, each with "+" (adds it) and "×" (dismisses it). Dismissals are kept in the module-level set `dismissedTemplates`, keyed `kind:text`. They last until the page is reloaded and are not saved.
- **The template bank.** On the server, `services.question_templates` returns up to three learned templates for the kind (most used first) followed by the defaults. A question is learned when `POST /api/questions` carries `section_kind`. `createQuestion` sends `section_kind` only when `opts.learn !== false`. In practice only the free-text "Add" box teaches the bank; accepted templates, claim questions and the session question pass `learn: false`.
- **Question list** (`ol.q-list`). Each item shows its number, text, how many paragraphs are tagged, the answer if any, and three buttons: "Recall" / "Recall again" (`dlg.recall`), "Go to answer" (jumps to the first tagged paragraph, `jumpToParagraph`) and "Delete" (`deleteQuestion`: `DELETE /api/questions/{id}`, then re-renders the affected paragraphs).
- **Add a question.** Four starter buttons (`STARTERS`: "How does", "What proves", "Why does", "What is") prefill the input. Enter or "Add" calls `createQuestion`.
- **"Turn claims into questions"** opens `dlg.claimBuilder` (section 5.6).

```ts
export async function createQuestion(r: Reader, text: string,
  opts: { sectionId?: string | null; sectionKind?: string | null; source?: number | null; learn?: boolean } = {}): Promise<Question | null>
```

`createQuestion` trims the text, adds a "?" if missing, posts `/api/questions`, pushes the result on `r.ann.questions`, and calls `renderSide()`, `renderMap()` and `updateProgress()`.

**Question tagging.** Press Q, then a digit 1–9 within two seconds. `dlg.tagParagraph(r, n-1)` calls `POST /api/questions/{id}/link {paragraph_id}` for the paragraph of the current sentence. The route is a toggle and answers `{linked}`. The function updates `q.paragraphs`, re-renders that paragraph (for the `Q` badge), the map (for the `.q-dot`) and the side panel.

**Recall flow.** See `recall` in section 5.6.

### Notes tab (`notesTab`)

A hint line about keys 1–5 and N. Then one group per highlight type that has items (`h3.hl-head.hl-<type>` and `ul.hl-list`), each item drawn by `hlItem` (text as a jump link, note, cloze, and the actions listed in section 5.3). Then "Margin notes": each note is a link that jumps to its sentence, with the first 80 characters of the sentence under it; for a note with `origin === "ai"` that line starts with "Written by the AI model · ". An empty state is shown when there is nothing.

### Terms tab (`termsTab`)

- An input and "Guess, then reveal" open `dlg.guessGate` with the typed term.
- "Your glossary for this document": terms with `is_concept = 0`, as a `dl.glossary`. The term jumps to its sentence. The definition is shown, or `guess: …` if there is none yet.
- "Acronyms found": every entry of `ann.acronyms`.
- "Concepts": terms with `is_concept = 1`, as chips that open the guess gate.

### Ask tab (`askTab` in `ask.ts`)

Milestone 2.2 of the AI plan (Ask this document); the server side is `readhold/ai/ask.py` (chapter 3, section 7b). The tab is there with AI on or off.

| Name | What it is |
|---|---|
| `Passage` | A passage from `GET …/ask`: `section_title`, `sentence`, `snippet` |
| `Cite` | A citation of an answer: `verified`, and when verified `quote`, `sentence`, `section_title` |
| `Answer` | The `result` of `POST …/ask`: `id` (only for an answer that was kept), `question`, `found`, `answer`, `citations`, `status` (`verified`, `partly`, `unverified`, `not_found`), `links`, `provider`, `warning`, `searched` (the number of sections sent; 0 when no model was asked) |
| `STATUS` | The sentence under the label for each status but `not_found`: "Each cited passage is in the document. Check that the answer follows from them." / "Some cited passages are in the document; the others could not be found in it." / "No cited passage could be found in the document. Treat this answer as a guess." |
| `Memo` | What the tab knows about one document: `q` (the text in the box, sent or not; set on every keystroke), `asked` (the question the passages and the answer belong to), `passages`, `answer`, `note` (the error line), `busy` (a request is running), `seq` (the number of the newest request) and `redraw` (the `draw` of the tab that is showing now) |
| `memos` | A module-level `Map` from document id to its `Memo`. It lives while the app is open (not saved), so a side-panel rebuild, switching tabs, or leaving the reader and coming back shows it all again, a half-typed question included |

What `askTab(r, body)` draws, top to bottom: a `textarea` (2 rows, `maxlength` 1000, placeholder "Ask about this document…", `aria-label` "Your question", filled with `memo.q`); one button, **Ask** when `aiIsOn()` and **Find passages** when not; a line that says what it does ("The model reads only the sections that match your question, and says so when the answer is not in them." with AI on; "Finds the passages that match your words. With AI switched on in Settings, a model can also answer from them." with AI off); and `div.ask-out` (`aria-live="polite"`), drawn by `draw()` from `memo`. The label and the line are chosen when the tab is drawn. Each new tab sets `memo.redraw` to its own `draw`, so a request that ends later draws into the tab that is showing then; a detached tab that is no longer `memo.redraw` draws nothing.

`run(text, fresh)`, from the button or Enter in the box (Shift+Enter is a new line) with the box's text, or from **Ask again** with the question of the answer:

1. The trimmed text, or nothing when it is empty or a run is going (`memo.busy`, shared by every tab of the document).
2. `seq` goes up by one and is this run's number; `busy` is set, `asked` is the question, the old answer and error line are cleared, and the tab is drawn (the button disabled).
3. `GET /api/documents/{id}/ask?q=<question>`; the passages are kept and drawn at once.
4. Only when `aiIsOn()` at that moment: `POST /api/documents/{id}/ask {question, fresh}`. A failure gives "No answer from the model: <the server's sentence>" and keeps the passages.
5. A failed GET: no passages, and its reason as the line.
6. `busy` is cleared and `memo.redraw()` runs. At each step a run whose number is no longer `seq` writes nothing into `memo`.

`draw()`, top to bottom:

| State | What it shows |
|---|---|
| `busy` | "Asking the model…" (AI on) or "Looking…" (`role="status"`), and the button disabled |
| A question with passages or an answer | "**Your question:** <asked>" |
| An answer with `found` | `div.ai-text`: `div.ai-text-label` "Written by the AI model (on this computer)." or "(<provider>)" and the `STATUS` sentence; the answer as a `p`; `ul.ask-cites`, one `li` per citation: a verified one is a link-style button `✓ “<quote>”` (`.resume-quote`, tooltip "Go to this passage (<section>)") that calls `r.jumpTo(sentence)`; one that was not verified is "a passage that could not be found in the document" (`.unproven`); the addresses the model wrote, as words ("The model wrote addresses. Readhold does not open them: …"); the budget `warning` |
| An answer that is not found | `div.ai-text` with the label "Checked by the AI model." when the answer's `searched` is above 0, else "No passage matched, so no model was asked.", and "**Not found in this document.**", with " The passages below are the closest matches." when there are passages |
| An answer with an `id`, no run going | A link-style **Ask again** (`run(answer.question, true)`): it asks the question the answer belongs to, not what is in the box now. A "not found" that asked no model has no `id`, so no **Ask again** |
| No answer, an error line | The line |
| Passages | A `kicker` "Passages that match" and `ol.ask-passages`: per passage a link-style button with its section title (`r.jumpTo(sentence)`) and the snippet under it; or "No passage of this document matches those words." |

Everything is built with `h()`; the model's words are text nodes and never go through `mathText`. Styles: "Part nineteen" of `styles.css` (chapter 4), with `.ai-text…` (Part fifteen) and `.resume-quote` (Part sixteen).

A review of 2.2 found that a side-panel rebuild (after a highlight or a note) lost a half-typed question and the "Asking the model…" line, that a late answer went into the old, detached panel, that two runs could overlap and an older answer could be shown under a newer question, that **Ask again** sent what was in the box rather than the question answered. All of these were fixed right after with `memo`, `seq`, `redraw` and "Your question:". Checked in the running app: a highlight made while a question was half typed kept the text.

Limits, read from the code (the page has no automated test; it was tried in the running app with a stand-in server, not with a model):

- The button label and the line follow AI on or off as it was when the tab was drawn; `run` checks `aiIsOn()` itself, so what it does is always right.
- While a new question is looked up, the passages of the one before stay under "Your question:" until the new ones arrive.
- A ✓ that points into a section hidden by clean view cannot show it: `jumpTo` moves the pacer to the next paced sentence.

---

## 5.6 Dialogs (`reader-dialogs.ts`)

All dialogs use `modal()`, `askText()` or `confirmBox()` from `util.ts`. While a modal is open, `isTyping()` is true, so the reader's keys are off.

### `confusionFirst(r, list)`

- **When.** At the start of `startFlow`, if there are unresolved `confusing` highlights and no `?s=`.
- **Shows.** Up to six of them. Under each: your margin notes on those sentences, and any term you defined after the highlight was made whose name appears in the highlighted text.
- **Saves.** "Got it now" → `PATCH /api/highlights/{id} {resolved: true}`. "Go there" closes and jumps.

### `sessionSetup(r)` and the side-quest check

- **When.** Every time the reader opens, after `confusionFirst`.
- **Shows first.** The document's title, then "Where you left off" (`resumeSlot`, below; an empty `div` that fills itself in when the document has a finished reading session), then the block of `questCheck`.
- **Asks.** Energy (low / medium / high), a time box (10, 15 or 25 minutes, default 15), and an optional question to read for. Up to four unanswered questions are offered as chips.
- **Returns** `SessionSetup { energy, minutes, question, questId, parked }`.
- **Saves.** A typed question that does not already exist is created with `createQuestion(…, { learn: false })`. The session itself is created afterwards by `startFlow`.

`questCheck(r)` builds the top block of this dialog. It fetches `GET /api/quest/active`.

- No active quest, or the quest has no questions: no block.
- The document is already linked (`doc.quest_question_id`), or an open step of the quest points at this document: a green line "Reads for: …" or "Step: …". The session gets the quest id.
- Otherwise the "Side-goal check" asks whether the document answers one of the main quest's questions:

| Choice | Effect |
|---|---|
| A question chip | At once: `POST /api/side-quests {text, decision: "linked", question_id, document_id}`; sets `r.doc.quest_question_id`; the session gets the quest id |
| "No, give it 15 min" | At once: `POST /api/side-quests {decision: "timeboxed", minutes: 15, …}`; the time box becomes 15 minutes |
| "No, park it for later" | When the dialog closes: `POST /api/side-quests {decision: "parked", …}`; `startFlow` goes to `#/home` and no session starts |

### `resumeSlot(docId)` and `resumeBlock(docId)` (`resume.ts`): "Where you left off"

The block at the top of the Start a session dialog, under the document's title. It is milestone 1.3 of the AI plan (the Resume briefing); the server side is `readhold/ai/resume.py` (chapter 3, section 7b).

- **When.** `sessionSetup` calls `resumeSlot(r.doc.id)` and puts the `div.resume-slot` it returns into the dialog. **The dialog does not wait**: `resumeSlot` starts `resumeBlock` and appends the box to the slot when it arrives. An empty slot takes no room (`.resume-slot:empty` in "Part seventeen" of `styles.css`).
- `resumeBlock` calls `GET /api/documents/{id}/resume`. It **returns** `null` (no block) when the request fails or the document has no finished reading session, so the dialog works without it.
- **The facts, always** (no model): one line built from the last session, `p.resume-facts`: when it ended (`when()`: "Today", "Yesterday", "N days ago" up to 6, then a short date; counted in **calendar days** from local midnight to local midnight, so a session that ended last night reads "Yesterday"), the reading time when it was a minute or more, "You read: …" with up to three section titles and "and N more", "N passage(s) marked", and "You are in “<section>”." when the position is known. Under it "You said comes next: …" when the session has a `next_step`.
- **AI off** (`ai.mode` is `off`): that is the whole block. No button, no request.
- **AI on, no kept recap:** a **Recap with AI** button and one sentence beside it: " Uses the model on this computer." in local mode, " Sends the passages you read last time to your cloud model." in cloud mode. **Nothing is sent until the button is pressed.**
- **AI on, a kept recap** (`brief` in the answer): it is drawn at once, with no call.
- **The button** runs `ask(false)`: the slot shows "Asking the model… You can start reading; this does not block anything." (`role="status"`), then `POST /api/documents/{id}/resume/brief {fresh: false}`. The dialog stays usable; starting the session closes it while the request runs, and the server still keeps the result for next time.
- **A failure** with no recap on screen shows "No recap: <the server's sentence>" and a **Try again** button (`fresh: false`).
- **Ask again**, a link under a drawn recap, runs `ask(true)`: `{fresh: true}`, a new call that replaces the kept recap. `show` remembers the recap in `shown`; when "Ask again" fails, **the recap that was shown is drawn again**, with "No new recap: <the server's sentence>" and **Try again** (`fresh: true`) under it.

`drawBrief(b)` draws a recap as `div.ai-text.resume-brief`:

| Part | What it shows |
|---|---|
| `div.ai-text-label` | "Written by the AI model (on this computer)." or "(<provider>)." for a cloud model, then the status sentence |
| `p` | "The model found too little in what you read to write a recap.", only when `recap` is empty |
| `ul` | One `li` per recap line: the line's text, then `div.resume-quote`: `✓ “<quote>”` (tooltip "These words are in the text you read") when the line is verified and has a quote, else "no passage named" (`.unproven`) |
| `p` | "**This section:** " and `point`, when there is one |
| `p` | "**Next:** " and `next`, when there is one |
| `div.ai-text-links` | "The model wrote addresses. Readhold does not open them: " and the addresses joined by " · ", when there are any; and a second one with the budget `warning`, when there is one |

The three status sentences (`STATUS`). A ✓ means the quoted words are in the text that was read; it does not mean the line follows from them, and the wording says so:

| `status` | Sentence |
|---|---|
| `verified` | "Each line quotes words that are in the text. Check that the line follows from them." |
| `partly` | "Some lines quote words that are in the text; the others name no passage." |
| `unverified` | "No line quotes a passage that is in the text. Treat this as a guess." |

Everything is built with `h()`, so every string from the server, the model's words included, is a text node. The file has no `innerHTML`, no `a` and no `img`. The quote is not a link: `sentence` and `document_id` come back from the server but the page does not use them. Styles: "Part sixteen" of `styles.css` (`.resume-box`, `.resume-facts`, `.resume-ai`, `.resume-brief`, `.resume-quote`), with `.ai-text`, `.ai-text-label` and `.ai-text-links` from "Part fifteen".

### `explainSelection(r, range, text)` (`explain.ts`): the Explain dialog

Milestone 1.4 of the AI plan (Explain selection); the server side is `readhold/ai/explain.py` (chapter 3, section 7b). Opened only by the "Explain" button of the selection bar (section 5.3), so only with AI on. `range` is `[first ord, last ord]`, `text` the selected text as the browser gives it.

| Name | What it is |
|---|---|
| `aiIsOn()` | `state.settings.ai_mode` is `local` or `cloud` |
| `codeRange(r)` | The `[ord, ord]` of the code paragraph that holds the selection, or `null` (section 5.3) |
| `LEVELS` | The three buttons: `simple` "Simple", `student` "Student", `expert` "Expert", each with a tooltip |
| `lastLevel` | A module variable: the level picked last, kept while the app is open. Starts as `student` |
| `Explained` | What the route returns: `id`, `explanation`, `terms`, `feedback`, `quote`, `status` (`verified` or `unverified`), `links`, `level`, `provider`, `warning`, `saved` |

What the dialog does, in order:

1. `r.pacer.pause(false)`: the pacer stops (not counted as a pause by the reader).
2. A wide modal "Explain this passage": the passage in a `blockquote` (the first 400 characters, then `…`), the level buttons (`div.seg`, `role="group"`), a `textarea` "Your take first: what do you think it means? A rough line is enough." (`maxlength` 600, focused), the buttons **No idea, explain** and **Explain**, one line that says where the text goes, the output `div.explain-out` (`aria-live="polite"`), and **Close**.
3. The line: "Uses the model on this computer. Only this passage and its paragraph are read." in local mode; "Sends this passage, its paragraph and your take to your cloud model. Secrets are removed first." in cloud mode.
4. **Nothing is sent when the dialog opens.** **No idea, explain** runs `run("")`. **Explain** runs `run(take)` when the box holds text; with an empty box it only focuses the box.
5. `run(attempt, fresh=false)`: does nothing while a request is running (`busy`); shows "Asking the model…" (`role="status"`); posts `POST /api/documents/{id}/explain {sentence: range[0], end_sentence: range[1], level, text: text.slice(0, 1200), attempt, fresh}`; then `show`. A failure shows "No explanation: <the server's sentence>".
6. `show(x, attempt)` draws `drawResult(x)` and a row with **Save as a note** and **Ask again** (`run(attempt, true)`, at the level selected at that moment).
7. **Save as a note** posts `POST /api/ai/results/{id}/note`, adds the note to `r.ann.notes` unless it is there, calls `r.decorateSentence(note.sentence)` and `r.renderSide()`, disables itself, reads "Saved as a note" and shows a toast. For a result that comes back with `saved: true` the button is disabled from the start. The server sends `saved: true` only while that note still exists, so after the note was deleted the button is live again.

`drawResult(x)` draws an answer as `div.ai-text`:

| Part | What it shows |
|---|---|
| `div.ai-text-label` | "Written by the AI model (on this computer). Check it against the passage." or "(<provider>)" for a cloud model |
| `p` | The explanation |
| `ul` | One `li` per term: the term in `strong`, then ": " and its meaning; only when there are terms |
| `p` | "**About your take:** " and `feedback`, when there is one |
| `div.resume-quote` | `✓ It rests on: “<quote>”` when `status` is `verified` (tooltip "These words are in the passage. Whether the explanation follows from them is for you to judge."); else, with `.unproven`, "The model named no passage that is in the text. Treat this as a guess." |
| `div.ai-text-links` | The addresses the model wrote, as words; and the budget `warning` |

Everything is built with `h()`: the model's words are text nodes, never markup, and never go through `mathText`. Styles: "Part seventeen" of `styles.css` (`.explain-out`), with the classes of parts fifteen and sixteen.

Limits, read from the code (the page has no test and was not tried in the running app): the `text` is the browser's selection, so a selection that takes in a section heading, a `Q1` badge or a rendered formula holds characters that are not sentence text, and the server answers 422 "That text is not in this passage." or, when the letters and digits still match, explains the whole sentences instead of the selected words; a selection that runs over two paragraphs is not offered **Explain** (the bar compares the paragraphs of its first and last sentence, and the server refuses it too); of a long paragraph only the part nearest the selection is sent (at most 1,800 characters), which the line under the buttons calls "the text around it in its paragraph"; a selection over 1,200 characters is cut for the request while the range still covers all of it; "Ask again" always asks with `fresh: true`, also after the level was changed to one that has a kept answer.

### `digestDialog(r)` (`digest.ts`): the Digest dialog

Milestone 1.5 of the AI plan (Document digest); the server side is `readhold/ai/digest.py` (chapter 3, section 7b). Opened by the **Digest** button of the map (section 5.1), with AI on or off.

| Name | What it is |
|---|---|
| `OutlineItem`, `Facts` | The facts from the server: the outline (`id`, `title`, `level`, `words`, `sentence`, `skipped`), `words`, `wpm`, `minutes` |
| `Part`, `Idea`, `Digest` | A kept digest: `summary`, `key_ideas` (`text`, `verified`, and `quote` and `sentence` when verified), `keywords`, `difficulty`, `parts` (`sentence`, `titles`, `summary`, `failed`), `skipped_parts`, `status`, `links`, `provider`, `warning` |
| `Job` | `id`, `state` (`running`, `done`, `failed`, `cancelled`), `step` (`parts`, `combining`), `done`, `total`, `message` |
| `DigestData` | What `GET /api/documents/{id}/digest` returns: `{facts, ai: {mode}, digest, job}` |
| `STATUS` | The sentence for each status: `verified` "Each key idea quotes words that are in the document. Check that the idea follows from them.", `partly` "Some key ideas quote words that are in the document; the others name no passage.", `unverified` "No key idea quotes a passage that is in the document. Treat them as a guess." |

What the dialog does, in order:

1. `r.pacer.pause(false)`, then `GET /api/documents/{id}/digest`. A failure opens a small modal "The digest could not be loaded: <reason>".
2. A wide modal "Digest": the document's title, `drawFacts`, the AI part `div.digest-ai` (`aria-live="polite"`), and **Close**.
3. `drawFacts`: "<words> words · about <minutes> min at <wpm> words a minute", then `ol.digest-outline`, one `li.lvl-<1…3>` per section with a link-style button (its title; it closes the dialog and calls `r.jumpTo(sentence)`) and " · <n> words", or " · left out of the digest" (class `skipped`, dimmed) for a hidden section. The facts are drawn once and do not change while the dialog is open.
4. `draw(data)` fills the AI part:
   - AI off: "With AI switched on in Settings, a model can write a summary and the key ideas here." Nothing else.
   - A running job: "Reading part <done + 1> of <total>…" (or "Combining the parts…"), a `progress` (`max` = total + 1, half a step for the combining), "You can close this and keep reading; it goes on in the background.", and **Stop** (posts `…/digest/cancel`, then polls). The next poll is set for 800 ms.
   - A kept digest: `drawDigest` and a link-style **Ask again** (`ask(true)`).
   - Otherwise: "No digest: <message>" for a failed job, or "Stopped after <done> of <total> parts. The parts already read are kept; the next digest goes on from there." for a stopped one; then the button **Digest with AI**, or **Go on with the digest** when the last job did not end `done`, and one line that says where the text goes: "Sends the document to your cloud model one part at a time (references left out). Secrets are removed first." in cloud mode, "Uses the model on this computer, one part at a time." in local mode.
5. **Nothing is sent when the dialog opens.** `ask(fresh)` posts `POST /api/documents/{id}/digest {fresh}`. A kept digest in the answer is drawn at once; otherwise the dialog polls. A refusal (409 for AI off, a document that is too long, or one with no text to digest) shows "No digest: <the server's sentence>".
6. `poll()` clears the pending timer, stops when the AI part is no longer in the page (`isConnected`), gets the digest and draws it; a failed GET tries again after 2 s. Closing the dialog clears the timer (`done.then(stopPolling)`), so polling ends with the dialog; the job goes on on the server.

`drawDigest(r, d, close)` draws `div.ai-text.digest`:

| Part | What it shows |
|---|---|
| `div.ai-text-label` | "Written by the AI model (on this computer)." or "(<provider>)", then the `STATUS` sentence |
| `p` | The summary |
| `ul` | One `li` per key idea: its text, then either a link-style button `✓ “<quote>”` (tooltip "Go to this passage"; closes the dialog and jumps to `sentence`) or "no passage named" (`.unproven`) |
| `p.digest-keys` | "**Keywords:** " and the keywords joined by " · " |
| `p` | "The model's guess at the level: <difficulty>." |
| `details.digest-parts` | Only with more than one part: "Part by part (<n>)", with ", <k> without a summary" when parts were skipped; an `ol` with each part's section titles (a button that jumps to its first sentence) and its summary, or "The model could not summarise this part." |
| `div.ai-text-links` | The addresses the model wrote, as words; and the budget `warning` |

Everything is built with `h()`: the model's words are text nodes, never markup, and never go through `mathText`. Styles: "Part eighteen" of `styles.css` (chapter 4), with `.ai-text`, `.ai-text-label`, `.ai-text-links` (Part fifteen) and `.resume-quote` (Part sixteen).

Limits, read from the code (the page has no test; it was tried in the running app with a stand-in server, not with a model): the facts are not reloaded while the dialog is open; after a server restart the last job is gone, so the dialog shows **Digest with AI** and no "Stopped after …" line, although pressing it goes on from the kept parts; a digest that was made before a structure edit is not shown at all (the server's key changed), not shown as out of date; when **Stop** and the 800 ms timer fire together two polls can run at once (each clears the latest timer, so it settles at one chain); while a job runs the server returns no digest (it does not look for one), so the dialog shows the progress, also while a fresh digest replaces a kept one; the cloud line says "references left out", while every hidden section is left out.

### `studyNotesDialog(r)` (`studynotes.ts`): the Study notes dialog

Milestone 2.4 of the AI plan (Study notes writer and flashcards); the server side is `readhold/ai/notes.py` (chapter 3, section 7b). Opened by the **Study notes** button of the map (section 5.1), with AI on or off.

| Name | What it is |
|---|---|
| `Kind`, `Source` | `notes`, `cards` or `quiz`; `highlights` or `section` |
| `Item` | One drafted item: `text`, `answer`, `verified`, and `quote` and `sentence` when verified |
| `Written` | A kept result: `id`, `kind`, `source`, `items`, `status`, `links`, `provider`, `warning`, `kept` (the indices already kept), `cut`, `left_out` |
| `Kept` | What the accept route returns: `page_id` and `title` (notes), or `cards` and `skipped` (cards); and `kept` |
| `MAX_HIGHLIGHTS` | 40, the same number as in `notes.py`, for the "not sent" line |
| `KIND_LABEL` | `quiz` "Quiz me", `cards` "Flashcards", `notes` "Notes", in that order: recall first ("attempt before reveal"), finished notes last |
| `STATUS` | `verified` "Each item rests on a passage that is in your reading. Check that it follows from it.", `partly` "Some items rest on a passage of your reading; the others name none and cannot be kept.", `unverified` "No item rests on a passage of your reading. Treat them as guesses; they cannot be kept." |

What the dialog does, in order:

1. `r.pacer.pause(false)`. The kind starts at **Quiz me**; the source at **My highlights (n)** when the document has highlights, else **This section: <title>** (the section of the pacer's sentence).
2. AI off: "Without AI, the Summary sheet gathers your highlights, and highlights and questions become review cards on their own.", a line that a model can draft these with AI on, and **Open the summary sheet** (`#/summary/<id>`). Nothing else; nothing is sent.
3. AI on: two segmented choices, **From** and **Make** (`seg`: buttons in `div.seg`, the chosen one with class `on`), the line "The model reads only the passages you choose. Nothing is kept until you pick items and press Keep; what you keep says the model wrote it.", **Write**, and the output column `div.study-out` (`aria-live="polite"`).
4. **Nothing is sent when the dialog opens.** `run(fresh)` shows "Asking the model…" and posts `POST /api/documents/{id}/study-notes {source, kind, section_id, at, fresh}` (`section_id` only for a section; `at` is the pacer's sentence, so a long section is sent around it). A failure shows "Nothing written: <the server's sentence>".
5. `draw(w)`: `div.ai-text` with the label "Written by the AI model (on this computer)." or "(<provider>)" and the `STATUS` sentence; `sentNote` (below); the items, or "The model found nothing it could write from these passages."; the addresses the model wrote, as words; the budget `warning`; then a link-style **Ask again** (`run(true)`).
6. `sentNote(w)`: "N passages were not sent (only the first 40 highlights fit)." when `left_out`; "This section is long: only the part around where you are was sent." (a section) or "Long highlights were shortened to fit." (highlights) when `cut`.

**A quiz** (`drawQuiz`): one `li` per question with its text, a textarea "Your answer first…", and **Show the answer**. Pressed with an empty textarea it asks `confirm("Show the answer without trying first?")`. Then the button goes and `div.study-reveal` shows "Answer: …", the quote (`quoteOf`), and for a verified item **Keep as a card** (`keep_as: "cards"`). The answer typed is not sent or saved.

**Notes and flashcards** (`drawList`): one `li` per item with a tick box, a tag, a textarea with the text (and for cards one with the answer), and the quote. `mark()` sets each row: a kept item is ticked off, disabled and tagged "Kept"; a verified one is ticked and tagged "Keep"; one with no checked passage is disabled, tagged "Cannot be kept: no passage" and dimmed (`li.unchecked`). The button ("Keep the chosen notes" or "Add the chosen cards to Review") is disabled when nothing is left to keep.

`quoteOf(it)`: a verified item gets a link-style button `✓ “<quote>”` that closes the dialog and jumps to `sentence`; the quote is the document's own sentence(s), as the server returns it. Otherwise "no passage named" (`.unproven`).

`keep(w, chosen, keepAs?)` posts `POST /api/ai/results/{id}/accept {items: [{index, text, answer}], keep_as?}`. The text sent is what is in the textarea, so the reader's own rewording is kept. On success `kept` becomes the server's list and a toast says where it went: "Kept in your note “<title>”, marked as written by the model." with **Open the note**, or "N cards added to Review, marked as written by the model." with " N already in Review (or deleted by you), not added again." when some were skipped. A failure shows the server's sentence. Each Keep button is disabled the moment it is pressed ("one press, one copy") and enabled again only when the request failed; a quiz button then reads "Kept".

Everything is built with `h()`: the model's words are text nodes, never markup, and never go through `mathText`. Styles: "Part twenty-one" of `styles.css` (chapter 4), with `.seg`, `.ai-text…` (Part fifteen) and `.resume-quote` (Parts sixteen and eighteen).

Limits, read from the code (the page has no automated test; it was tried in the running app with a stand-in server, not with a model): there is no way to pick which highlights are sent; nothing checks that every highlight gets an item; the reader's quiz answer is not compared with the model's or saved; a line the reader rewrote in the dialog is still kept under the AI label; the "not sent" line names the 40-highlight limit even when the server's count also holds sources the budget left out; the dialog keeps nothing in memory, so closing it during "Asking the model…" loses the answer from view (the server keeps it, and the next **Write** with the same choices returns it without a call); the quiz's "Show the answer" uses the browser's own `confirm`, not `confirmBox`.

### `brainstormDialog(r)` (`studynotes.ts`) and `aiIdeasBox(target, hooks)` (`aibrainstorm.ts`): Brainstorm

Milestone 3.2 of the AI plan (Brainstorm, diverge then converge); the server side is `readhold/ai/brainstorm.py` (chapter 3, section 7b). `brainstormDialog(r)` is opened by the **Brainstorm** button of the map. It calls `r.pacer.pause(false)`, then shows, in a wide modal titled "Brainstorm": with AI off, a line that the brainstorm sheet of an idea or a note (Think) is the way to think an idea through without AI, a line that a model can suggest ideas with AI on, and **Open Think** (`#/think`); with AI on, `aiIdeasBox({kind: "document", id})`. The same box sits in the side column of a brainstorm sheet (chapter 7, section 7.5), with hooks.

| Name | What it is |
|---|---|
| `Source` | One checked passage: `kind` (`document`, `note`, `idea`, `hlnote`), `quote`, and `document_id`, `document_title`, `sentence` or `id`, `title` |
| `Idea` | `text`, `label`, `similar`, `angles`, `sources`, `verified` |
| `Result` | The kept result: `id`, `target` (with `sheet_title`), `topic`, `ideas`, `judge` (`model` or `code`), `status`, `links`, `warning`, `provider`, `kept`, `left_out` |
| `Target`, `Hooks` | `{kind: "page" \| "idea" \| "document", id}`; `{before?, after?}`, both async, run around putting ideas in and around Undo |

What `aiIdeasBox` does, in order:

1. AI off (`aiIsOn()` false): one line, "With AI switched on in Settings, a model can also suggest ideas here, each with the passages it rests on." Nothing else.
2. AI on: a topic input (200 characters, optional), **Ideas from the model**, a line on what the model reads ("only your highlights in this document and the notes nearest to them, never the whole document" for a document; "only what this sheet shows: the text, the notes near it and the passages you highlighted on its words" otherwise), and the output column `div.study-out` (`aria-live="polite"`).
3. **For a document, attempt first.** Above them a textarea "First, your own thought: what do your highlights here make you think of?" (500 characters). **Ideas from the model** stays disabled until it holds 12 characters. What is typed there is never sent or saved: it is the "attempt before reveal" step. (A sheet needs no such box: it shows this box only once the reader has written, see chapter 7.)
4. **Nothing is sent when the box is drawn.** `run(fresh)` (one at a time, `busy`) shows "The model is writing ideas from three angles, then ranking them…" with **Stop** (`POST /api/brainstorm/cancel`, which stops every running brainstorm), then posts `POST /api/brainstorm {kind, id, topic, fresh}`. A failure shows "No ideas: <the server's sentence>".
5. `putIn(r)` (since 2026-11-26, on the owner's request; it replaced the list of ideas with tick boxes and **Keep the chosen ideas**): it picks every idea that is `verified` and not in `r.kept`, and counts the ones that are not verified. With none to put in it says "No new idea that rests on your passages." (or "The model wrote no ideas from these passages."), with the Why link and **Ask again**, and writes nothing.
6. Otherwise `await hooks.before?.()`, then `POST /api/brainstorm/{id}/keep {items: [{index, text}]}` with the model's text; `await hooks.after?.()` runs in `finally`, also after a failure, because the sheet holds its saves until it runs. A failure shows "The ideas were not added: <the server's sentence>". On success `kept` becomes the server's list, and the box says "Added N ideas to “<title>”, each as its own part. Edit them there, or delete what you don't want." (or "Those ideas are already in the sheet."), with **Open the note** (`#/notes/<page_id>`), **Undo** (only when ideas went in), the Why link (`whyLink`), and under it "N ideas that named no passage of yours were left out.", "N files of secrets left out: they are never sent to a cloud model." when `left_out`, the addresses the model wrote, as words, and the budget `warning`; then a link-style **Ask again** (`run(true)`). A toast "Added N ideas to “<title>”." offers **Undo** too.
7. `undo()`: `hooks.before`, `POST /api/brainstorm/{id}/undo {page_id}`, `hooks.after`. On success `kept` becomes the server's list and the box says "The ideas were taken out of the sheet.", with **Ask again**; the ideas taken out go in again the next time the box puts ideas in. A 409 (the sheet changed since) shows the server's sentence, "The sheet changed since the ideas went in. Delete them in the note by hand.", as a toast.

Everything is built with `h()`: the model's words are text nodes, never markup, and never go through `mathText`. Styles: "Part twenty-two" of `styles.css` (chapter 4), with `.study-out`, `.ai-text…` (Part fifteen).

Limits, read from the code (no automated test of the page; tried in the running app with a stand-in server, not with a model): **Stop** stops every brainstorm that is running, and closing the dialog does not stop one (the server keeps the result, and the same request later returns it without a call); the box no longer shows the ideas, their checked passages or who grouped them, only what went into the sheet (the kept result still holds them; "Why did it say this?" names the sources each call was sent); the box shows no "Written by the AI model" label, and the sheet has none either; the Undo in the box and the one in the toast are the same, so a second press answers 404 ("not found"); `variety` is not shown.

### `organizeDialog(docId, title, onChange?)` (`organize.ts`): Organize

Milestone 3.3 of the AI plan (Organize library and related documents); the server side is `readhold/organize.py` and `readhold/ai/organize.py` (chapter 3, sections 7c and 7b). Opened by **Organize** on a queue row (with `onChange` = the queue's `refresh`) and by **Organize** in the reader's map (without). A wide modal titled "Organize “<title>”". Like Study notes and Brainstorm, the reader's button pauses the pacer first.

| Name | What it is |
|---|---|
| `Related`, `Suggested`, `Overview`, `AIResult` | The shapes of `GET /api/organize/{id}` and of the suggestion |
| `TAG` | `^\p{L}[\p{L}\p{N}_-]{0,39}$` (Unicode), the page's copy of `organize.clean_tag`'s rule, for an early message |
| `tags` | The tags as the server last returned them |
| `queue` | One promise chain: every save waits for the one before |
| `buttons` | Per tag, the **+ #tag** buttons drawn for it, so all of them are disabled while the tag is on (`syncButtons`) |

What the dialog does:

1. A line "Tags are your collections: the Documents tab can show every document with a tag. Only you add them."; **Your tags** (`div.org-tags`: a `span.chip` per tag with **×**, or "No tags yet."); an input "Add a tag" (41 characters, with a `datalist` of the tags you use); the **Private** checkbox (below); then `load()`'s part; then the AI part; **Close**.
2. **Private** (milestone 4.4). `label.row` with a checkbox and "Private: never send this document to a cloud model (it adds the tag #private; a local model still reads it)". Ticking it calls `save((now) => now.includes("private") ? now : [...now, "private"])`, unticking `save((now) => now.filter((t) => t !== "private"))`: the same chain as any tag change, with `expect`, the toast and **Undo**. After every save and every redraw of the chips the box is set from the tags (`privateBox.checked = tags.includes("private")`), so a `#private` added or removed by hand, or undone, shows. The server's privacy rules read this tag (chapter 3, section 7b, *Privacy controls*); the page does nothing else with it.
3. `load()`: `GET /api/organize/{id}`, then **Suggested from your library** (each **+ #tag** with its reason, or a line on when tags are suggested) and **Related documents** (each a link to `#/read/<id>` that closes the dialog, with "shares …"; or "No other document shares enough of its words yet.").
4. **Saving.** `add(t)` trims, drops `#`, makes NFC lower case and checks `TAG` (else "A tag is one word that starts with a letter (use - to join words)."). `save(next)` chains on `queue`: it takes the tags now (`before`), sends `PUT /api/documents/{id}/tags {tags: next(before), expect: before}`, and on success shows "Tags saved." with **Undo**. Undo, also on the chain, sends `{tags: before, expect: after}`, where `after` is exactly what that change produced: so an Undo after a later change (or after a change in another window) is refused with 409 and overwrites nothing. A failure shows the server's sentence and reloads the box. After each try the chips are redrawn, the buttons synced, and `onChange` runs (the queue redraws, with its chips).
5. AI off: a line that a model can also suggest tags and related documents. AI on: **From a model**, a line on what the model reads, **Suggest tags and related documents**, and `div.study-out`. `runAI(fresh)` shows "Asking the model…" and posts `POST /api/documents/{id}/organize/suggest {fresh}`; a failure shows "No suggestions: …".
6. `drawAI(r)`: `div.ai-text` with "Suggested by the AI model (on this computer)." or "(<provider>)", the reuse sentence ("N% of its tags are ones you already use.") and "A tag with ✓ rests on a passage of this document; the others are its guess."; each tag as **+ #tag** with "one of your tags" or "a new tag" and, when verified, `✓ “<quote>”` (`.resume-quote`); "N more suggestions were left out (not a tag, or more than two new ones)."; **Related, by the model** with links and "The model's reason: …"; the addresses as words; the warning; **Ask again**.

Everything is built with `h()`. Styles: "Part twenty-three" (`.org-tags`, `.org-list`), with `.chip`, `.study-out`, `.ai-text…` and `.resume-quote`.

Limits, read from the code (no automated test; tried in the running app with a stand-in server): the reader's Organize button does not refresh anything else on the page (the reader shows no tags); `TAG` and `clean_tag` must be kept alike by hand.

### `whyDialog(resultId)` and `whyLink(resultId)` (`why.ts`): "Why did it say this?"

Milestone 4.2 of the AI plan; the server side is `readhold/ai/why.py` (chapter 3, section 7b). It reads the AI log through the server and calls no model.

**The link.** `whyLink(id)` returns `button.link.small.why-link` "Why did it say this?", or `null` when there is no result id (nothing was asked of a model). Each feature places it right after its `div.ai-text-label`: `drawBrief` in `resume.ts`, `drawResult` in `explain.ts`, the digest in `digest.ts`, the answer in `ask.ts` and `libraryask.ts`, the draft in `studynotes.ts`, the ideas in `aibrainstorm.ts`, the suggestion in `organize.ts`, and the order suggestion in `readplan.ts` (chapter 6). A click calls `whyDialog(id)`.

**The panel.** A wide modal titled "Why did it say this?". It shows "Reading the AI log…" (`role=status`) and sends `GET /api/ai/why/{id}`. Then, top to bottom:

| Part | What it shows |
|---|---|
| The result | "<feature>, <time>. Model: <model> (on this computer, or the provider). Prompt: <version>." (`FEATURE` names the twelve features, Tidy and Plan chat among them since Phase 5 and Note chat since 5.4) |
| Status | The sentence of `STATUS` for `verified`, `partly`, `unverified` or `not_found`; nothing for another status |
| Count | "Of the parts it shows with a mark, N of M parts rest on a quote found word for word in the passage it names; K do not, so they are shown as unchecked." Only when something was counted |
| Gone | When `log_gone`: "The log of some of its calls is gone: Readhold keeps it as long as Settings → AI says (30 days at most)." or, with no call left, "The log of its calls is gone: … What the result itself recorded is above." (since 4.4, when the retention became a setting) |
| Each call | `callBox`: a `details.why-call` (open when there is one call). The summary: "Call i of n: " (with several), the task in words (`TASK`, else the feature name) and the outcome in words (`OUTCOME`: answered, failed and why, stopped, not sent and why). Then `dl.why-facts`: Model, Prompt, When (time, seconds, tries when more than one), Tokens, and Error when there is one. Then the guards' checks in words (`CHECKS`: fenced, trimmed, left out, flagged, links removed, and since 4.4 `private_left_out`, "N private items (#private) left out: never sent to a cloud model", then secrets removed). Then "What it was sent (N)" with the sources, or "Not recorded for this call: it was made before Readhold kept the list of sources. Ask again to see it.", or "Only the instruction and your question." Past 60: "The first 60 are named here; M more were sent too." Then "The start of what came back" (`output_preview`, or "(nothing kept)") |
| A source | `sourceRow`: the name (a document as "<title> · <section>", "Your note “…”", "Your idea “…”", else the server's title), then its trust in words (`TRUST`), "N characters sent" and "(cut)". A link only for a document passage or a note on a highlight (`#/read/<doc>?s=<ord>`), a note (`#/notes/<id>`) or an idea (`#/think/idea/<id>`); a `gone` source is a plain `span` |
| Prompts | One `details.why-prompt` per version: "The prompt <version>, word for word" and a `pre` with its text |
| Foot | "This comes from the AI log on this computer. Opening it sends nothing anywhere.", then **Delete this result** and **Close** (Close has the focus, never Delete) |

A failed request shows "Not available: <the error>".

**Closing.** `close` closes the panel and then sends Esc on `document` while a `.modal-back` is left, at most 5 times. Since `modal()` closes only the topmost dialog on Esc (chapter 4), each Esc closes one: the dialog the panel was opened from goes too. A source link and **Close** both call it. Esc on the panel itself closes only the panel.

Everything is built with `h()`; the server sends names and sizes, never a source's text. Styles: "Part twenty-four" (`.why-link`, `.why-call`, `.why-facts`, `.why-checks`, `.why-sources`, `.why-preview`, `.why-prompt`).

**Delete this result** (milestone 5.1). A `ghost` button, titled "Remove this one result. Asking again makes a new one.", that calls `removeItem("ai_result", resultId, "Deleted this AI result.", …)` (`trash.ts`, chapter 4). In `gone` the button is disabled and `p.why-deleted` (`role=status`) says "Deleted. Close this panel and reload the page (or open it again): the box it came from will no longer show it. Asking again makes a new one."; in `back` the button is enabled again and the line says "It is back." The box the result came from is not redrawn: it keeps showing the result until it is drawn again. A restore is refused while the result's document, note or idea is gone. Style: `.why-deleted` in "Part twenty-six". Checked in the running app with a stand-in model.

Since Phase 5, `whyLink` also sits beside the AI label of Tidy (`views/tidy.ts`) and Plan chat (`views/planchat.ts`), chapter 6. Their sources are named by the server's bare word (`task`, `routine`, `days`, `turn`), and Plan chat's deadlines (`docs:`) as "the titles of related documents".

Limits: nothing tests the front end (tried in the running app with a stand-in server). **Close** closes only the panel; a source link closes every open dialog. When every log row is gone the panel says so, and points to what the result itself recorded.

### Section checkpoints: `sectionCheckpoints`, `runCheckpoints`

`sectionCheckpoints(r, from, to)` returns a list of steps, in this order:

1. `check` — the section just finished has a `prediction` but no `prediction_check`.
2. `recall` — one per unanswered question that has a tagged paragraph in the section just finished.
3. `predict` — `settings.prediction_prompts` is on, the next section has no prediction, its kind is not references, appendix or abstract, and it has at least four paced sentences.

`runCheckpoints` runs them one after another, then calls `r.pacer.play()` unless a prediction prompt was cancelled.

| Step | Dialog | Saves |
|---|---|---|
| `predict` | `askText("Prediction", …)`, one line | `PATCH /api/sections/{id} {prediction}` (only if not empty) |
| `check` | "Compare": your prediction, an optional note, Yes / Partly / No | `PATCH /api/sections/{id} {prediction_check}` (`"Yes — note"` or just the verdict) |
| `recall` | `recall(r, q)` | see below |

### `recall(r, q)`

- **When.** As a checkpoint, or from the "Recall" button on a question.
- **Flow.** You type an answer from memory. "Compare with the text" refuses an empty box. It then reveals the tagged paragraphs, or the question's source sentence, or a hint to tag a paragraph. Then "Save answer" appears.
- **Saves.** `PATCH /api/questions/{id} {answer}`. The server creates or updates the review card for the question. Afterwards: `ambience.moment()`, a toast, `r.rampSpeed()`, `renderSide()`, `updateProgress()`.
- "Later" closes without saving.

### `claimBuilder(r)`

- **When.** "Turn claims into questions" in the Questions tab.
- **Shows.** Up to 18 sentences from `text` paragraphs of the abstract and intro sections (or of the first section if there are none). Each row has the four starter buttons.
- **Flow.** A starter fills an input with a question made from the sentence. Openers like "We show that" are stripped, the final full stop is removed, and the first letter is lowered. Enter adds it.
- **Saves.** `createQuestion(…, { sectionId, source: s.ord, learn: false })`, so the question remembers its source sentence.

### `guessGate(r, initial)`

- **When.** Key G (with the selected text, possibly empty), the "Guess (G)" button of the selection bar, the Terms tab, or a concept chip. It pauses the pacer.
- **Flow.** Term and guess. "Reveal" refuses an empty guess; "No idea — reveal" fills in "(no idea)". It then calls `GET /api/documents/{id}/define?term=…` and shows the acronym expansion, the sentences where the document defines the term (each with "Go there"), and any definitions already in your glossary. A "Your definition (corrected)" box is prefilled with your guess, or with the acronym expansion if you had no idea.
- **Saves.** "Save to glossary" → `POST /api/terms {term, guess, definition, document_id, sentence, source_text}`. The sentence is the first defining sentence found, or the current sentence. The term is pushed on `r.ann.terms`. The toast says it became a review card when a definition was given.

### `clozePicker(r, hl)`

- **When.** "Make blank card" / "Change blank" on an evidence highlight.
- **Flow.** The highlight text is split into words, each a chip (numbers get class `num`). Clicking one saves it.
- **Saves.** `PATCH /api/highlights/{id} {cloze}` with the word stripped of surrounding punctuation.

### `addNote`, `showNotes`, `quickIdea`, `tagParagraph`

`addNote` and `showNotes` are in section 5.3. `tagParagraph` is in section 5.5. `quickIdea` (key I) asks one multiline text and saves `POST /api/ideas {text, document_id, sentence}`.

### Peeks: `peek(r, anchor, pinned)` and `acronymTip(r, el)`

- **When.** Hovering a `span.peek` opens an unpinned popover; clicking it opens a pinned one with a "Close" button. Hovering a `.acr` word opens a small tooltip with the expansion.
- **Shows.** For `figure:N` / `table:N` the caption text. For `eq:N` the cropped picture, or KaTeX, or text. For `refs:…` each cited reference; a range such as `5–9` is expanded, at most seven items per range.
- **Reference action.** Every reference has one button, "Save to reading list" → `POST /api/ideas {text: "To read: …", document_id}`, then a toast. The cited paper is kept as a line in the idea inbox; nothing is downloaded.
- There is one popover at a time (`peekEl`, `peekPinned` are module variables). An unpinned one closes on `mouseleave`. A pinned one closes on the next `mousedown` outside it. `positionNear` places it under the anchor, or above when there is no room.

### `selectionToolbar` and the "→ Note" quote

The bar is described in section 5.3, with its "Explain" button and `codeRange`; the dialog that button opens is `explainSelection`, above. `quoteToNote(r, text, sentence)` posts `POST /api/pages/quote {text (first 4000 characters), document_id, sentence, day}` where `day` is today from `ymd()` in `views/plan.ts`. The server appends the passage to that day's note with a link back to the sentence. The toast has an "Open the note" action that goes to `#/notes/<id>`.

### `explainIt(r, atEnd)`

- **When.** The pacer reaches the end (`Reader.end()`, `atEnd = true`), the button at the end of the paper, or "Explain it" in the map. It pauses the pacer.
- **Asks.** Three sentences in a textarea prefilled with `doc.explain_text`, and a checkbox "Mark this document as finished" (ticked when `atEnd` or already finished).
- **Saves.** `PATCH /api/documents/{id} {explain_text, status?: "finished"}`, then `flushRead()`.
- **After.** If saved and marked finished, goes to `#/summary/<id>`.

### `timeBoxDone(r)`

- **When.** Focused time reaches the time box (`onSessionTick`).
- **Buttons.** "5 more minutes" resolves true (the reader extends the box). "End session" calls `endSession(r)`.

### `endSession(r)`

- **When.** The top-bar button, key E, or from `timeBoxDone`. It pauses the pacer and calls `flushRead()`.
- **Asks.** "What comes next?" One line. The placeholder is a suggestion: the first unanswered question, else the next section's title, else "Write the explain-it box". An empty input saves the suggestion.
- **Goal step.** It fetches `GET /api/quest/active`. If an open step points at this document, a checkbox "This finished the goal step" appears. Ticking it reveals a required "What did it produce?" line.
- **Extras.** After at least three focused minutes, `feelRow()` (energized / neutral / drained).
- **Saves, on "Save & stop".** `PATCH /api/quest-steps/{id} {done: true, output}` if the step was finished; then `session.end(nextStep, output, feel)`, which is `PATCH /api/sessions/{id}` with the counters, `next_step`, `output`, `ended: true`, and `feel` when given.
- **After.** Goes to `#/home`. "Cancel" returns to the reader with the pacer paused.

### `comfortPopover(r)`

- **When.** The "Aa" button.
- **Asks.** Font (from `FONTS`), size 14–32, line length 40–100, line spacing 1.3–2.4. Every input event previews through `applyComfort(current())`.
- **Saves.** "Save as default" → `saveSettings({font, font_size, line_width, line_height})`. "Save for <type> documents" → `saveSettings({comfort_by_type: {…, [type]: current()}})`. Both are `PUT /api/settings`.
- **After.** On any close it reapplies `comfortFor(type)`, so an unsaved preview is dropped.

### `keyHelp()`

A table of the reader's keys. The list is typed by hand in this function; keep it in step with `bindKeys`.

---

## 5.7 `summary.ts`

```ts
export async function summaryView(root: HTMLElement, docId: string): Promise<void>
```

It loads `GET /api/documents/{id}/summary` once and builds `article.summary`. The helper `section(title, kids)` returns nothing when `kids` is empty, so empty parts disappear. The helper `go(ord, text)` makes a link to `#/read/<id>?s=<ord>`, or plain text when there is no sentence.

| Part | Content |
|---|---|
| Header (`header.isle.page-head`) | "← Back to reading", "Export Markdown", title, progress line, source, "Why I read this" |
| In my words | `explain_text`, or a hint that the explain-it box fills it. Always shown |
| Main points | Each claim with its evidence under it, then evidence without a claim |
| Questions | Each question and its answer, or "not answered yet" |
| Glossary | Terms (definition or guess), `definition` highlights, acronyms |
| Predictions | Section title, prediction, and the check result |
| Still confusing | Confusing highlights |
| Ideas | Idea highlights (the note if there is one, else the text) |
| Margin notes | Each note, linked to its sentence |
| Connected | `connectedCard("document", id, title)` from `related.ts` |
| My critique | `critiqueBox()` |

**Critique** (`critiqueBox`). A textarea and a "result I'd reproduce" input. Each saves on its `change` event with `PATCH /api/documents/{id} {critique}` or `{reproduce}` and shows "Saved" for 1.5 s.

**"Make it a goal step".** Requires the reproduce line. It saves the line, then fetches `GET /api/quest/active`.

- With an active quest: `POST /api/quests/{id}/steps {title: "Reproduce: …", document_id, minutes: 60, low, high}`.
- Without one: `POST /api/ideas {text: "Reproduce: …", document_id}`.

**Export** (`exportMd`). `POST /api/documents/{id}/export` writes a Markdown file on the server and returns `{path, markdown}`. The page copies the Markdown to the clipboard and shows the path. If the clipboard is refused it still shows the path.

The view returns no cleanup function and has no keys.

---

## 5.8 `library.ts` (and `libraryask.ts`)

```ts
export async function libraryView(root: HTMLElement): Promise<void>
```

The page is `section.library`: the shared tab header `libraryHead("documents")`, an import block, the *Ask your library* box (`libraryAskBox()`, below), the heading "Reading queue", the collection chips (`div.row.wrap.shelves`, below) and the reading queue (`div.queue`).

### Two import paths

Both go through `run(label, fn)`, which shows the `.busy` spinner, awaits `fn`, and on error shows "Import failed: …" for 8 s.

| Path | UI | Call |
|---|---|---|
| File | The drop zone `div.drop` (click, Enter, or drag and drop) and a hidden file input accepting `.pdf`, the text types `.md,.markdown,.txt,.text,.rst` and the code types `.py,.pyi,.js,.mjs,.cjs,.jsx,.ts,.tsx,.go,.rs,.java,.c,.h,.cpp,.cc,.hpp,.cs,.kt,.swift,.php,.rb,.sh,.ps1,.sql,.css,.json,.toml,.yaml,.yml` (the same list as `CODE_EXT` in `readhold/importers/code_import.py`; it is written out by hand here), multiple. The drop zone reads "Drop a PDF, Markdown, text or code file or click to choose" | `api.upload("/api/import/file", FormData{file})`, one file after another (`importFiles`) |
| Paste | Inside `<details>`: title, textarea, a Markdown / Plain text select | `POST /api/import/text {title, text, format}` (`importPaste`) |

There is no link import. A note under the two paths says: "Files stay on this computer. Readhold downloads nothing: to read a web article or an arXiv paper, save it as a PDF first, or paste its text."

### The why and deadline prompts

`afterImport(res)` runs after each successful import:

1. A toast with the section and sentence counts; a second toast for `res.warning`.
2. `askText("Why am I reading this?")`.
3. If that was not cancelled, `askText("Deadline (optional)")`.
4. `PATCH /api/documents/{id}` with `why` if not empty and `deadline` if it matches `YYYY-MM-DD`. A deadline in another format is dropped without a message here.
5. `refresh()`.

With several files, each file finishes its prompts before the next import starts.

### Queue rows

`refresh()` loads `GET /api/documents`, draws the collection chips, and draws one `article.doc-row.<status>` per document of the chosen collection:

**Collections (`shelves`).** Milestone 3.3: a tag is also a collection. `refresh()` counts every tag over `QueueDoc.tags` (`web/src/types.ts`, optional; the list `GET /api/documents` returns). With at least one tag it draws `div.row.wrap.shelves` (`role="group"`, label "Collections: show the documents with a tag"): a `button.chip` **All**, then one per tag, "#<tag> (<count>)", the most used first, then by name. The chosen one has class `on` and `aria-pressed="true"`; pressing a chip sets `shelf` and calls `refresh()`. With a chip chosen only the documents with that tag are listed; when its tag is gone, `shelf` goes back to all. `.shelves:empty` is not displayed, so a library without tags shows no gap. The chosen chip lives in the page function, so it is forgotten when you leave the tab.

Each row:

- `a.doc-name` → `#/read/<id>`;
- a meta line: source type, "due …" (class `overdue` when the deadline is before today and the document is not finished), status, "import note" with the warning as tooltip, "⚠ flagged text" when `d.flags` is not empty (below), and the tags as " · #a #b" (`span.doc-tags`, muted);
- `button.why` showing the reason, or an invitation to add one → `editWhy`;
- a progress `div.bar`.

**The "flagged text" mark.** `QueueDoc.flags` (`web/src/types.ts`, optional) is the list `GET /api/documents` returns: none, one or both of `hidden_text` and `instructions` (chapter 1, section 6, `documents.flags`). With at least one, the meta line ends in `span.warn.doc-flag` reading " · ⚠ flagged text". Its tooltip comes from `flagHint(flags)`:

| Flag | Sentence |
|---|---|
| `hidden_text` | "This file holds text a reader cannot see (white, too small, or off the page)." |
| `instructions` | "Some of its text reads like orders to an AI model ("ignore previous instructions")." |
| always, at the end | "You can read it as usual. An AI model is always told that document text is material to read, never instructions." |

The mark is a `title` tooltip only: it is not a button, it does not say where the text is, and it cannot be dismissed. `.doc-flag` (a help cursor) is the last rule of "Part fifteen" in `styles.css`. `afterImport` does not use the `flags` field of the import answer (`ImportResult` has no such field); the mark appears because `refresh()` reloads the queue. The reader itself shows no mark.

Actions (`div.doc-actions`):

| Action | Does |
|---|---|
| "Resume" / "Read" (Resume when `position > 0`) | `#/read/<id>` |
| "Summary" | `#/summary/<id>` |
| "Structure" | `#/structure/<id>` |
| "Organize" | `organizeDialog(d.id, d.title, refresh)` (section 5.6): tags and related documents; each tag change redraws the queue and its chips |
| "Deadline" | `setDeadline`: `askText`, format check with an error toast, `PATCH /api/documents/{id} {deadline}` (empty clears) |
| "Remove" | `remove` (below) |

### Removal and undo

`remove(d)` asks with `confirmBox`, calls `DELETE /api/documents/{id}` (a soft delete on the server), refreshes, and shows an 8-second toast with an "Undo" action. Undo calls `POST /api/documents/{id}/restore` and refreshes. After the toast is gone there is no undo on this page.

### Ask your library (`libraryAskBox` in `libraryask.ts`)

```ts
export function libraryAskBox(): HTMLElement
```

Milestone 2.3 of the AI plan (Ask my library); the server side is `readhold/ai/library.py` (chapter 3, section 7b). `libraryView` places the box between the import block and the "Reading queue" heading. It is there with AI on or off. The loop (which tool, which anchor, how many steps) runs on the server; the page only sends the question.

| Name | What it is |
|---|---|
| `Match` | A passage or note from `GET /api/library/ask`: `kind` (`document` or `note`), for a document `document_id`, `document_title`, `section_title`, `sentence`; for a note `note_id`, `title`; and `snippet` |
| `Cite` | A citation of an answer: `verified`, and when verified `kind`, `quote`, and `document_id`, `document_title`, `section_title`, `sentence` or `note_id`, `note_title` |
| `Step` | One step of the loop: `step`, `action` (`answer`, `search`, `read`), `keywords`, `added`, `ran` (`false` for a tool asked for on the last step, where no tool runs) |
| `Answer` | The `result` of `POST /api/library/ask`: `id` (only for an answer that was kept), `question`, `found`, `answer`, `citations`, `status`, `steps`, `links`, `provider`, `warning`, `searched`, `left_out`, and since 4.4 `private_left_out` (optional: items tagged `#private`, or copies of them, left out in cloud mode) |
| `STATUS` | The sentence under the label for each status but `not_found`: "Each cited passage is in your library. Check that the answer follows from them." / "Some cited passages are in your library; the others could not be found in it." / "No cited passage could be found in your library. Treat this answer as a guess." |
| `where(m)` | The address of a match or a citation: `#/notes/<note_id>` for a note, `#/read/<document_id>?s=<sentence>` (0 when there is none) for a document |
| `stepLine(steps)` | "The model " and, joined by ", then ", per step: `searched for “<keywords>” (<added> new)`, `read a section` (when it added one) or `read nothing new`, `answered`, or, for a step with `ran: false`, `still asked to search on the last step, where no tool runs` (or `to read`); then ".". Empty for no steps |
| `memo` | One module-level object, for the whole app: `q` (the text in the box, set on every keystroke), `asked` (the question the matches and the answer belong to), `matches`, `answer`, `note` (the error line), `busy`, `seq` (the number of the newest request), `redraw` (draws the box on screen: each `libraryAskBox()` points it at its own `out`, so it always reaches the box drawn last). It lives while the app is open (not saved), so leaving the Documents tab and coming back shows the last question, its matches and its answer again |

What `libraryAskBox()` draws, top to bottom, inside `div.isle.stack.library-ask`: the heading "Ask your library"; a `textarea` (2 rows, `maxlength` 1000, placeholder "Ask a question across all your documents and notes…", `aria-label` "Question for your library", filled with `memo.q`); one button (`btn primary`), **Ask** when `aiIsOn()` and **Find passages** when not; a line that says what it does ("The model starts from the passages and notes that match, may search again or read one section (at most 3 steps), and says so when your library does not answer." with AI on; "Finds the passages and notes that match your words. With AI switched on in Settings, a model can also answer from them." with AI off); and `div.ask-out` (`aria-live="polite"`), drawn by `draw()` from `memo`. The label and the line are chosen when the box is drawn.

`run(text, fresh)`, from the button or Enter in the box (Shift+Enter is a new line) with the box's text, or from **Ask again** with the question of the answer:

1. The trimmed text, or nothing when it is empty or a run is going (`memo.busy`).
2. `seq` goes up by one; `busy` is set, `asked` is the question, the old answer and error line are cleared, and the box is drawn (the button disabled).
3. `GET /api/library/ask?q=<question>`; the matches are kept and drawn at once.
4. Only when `aiIsOn()` at that moment: `POST /api/library/ask {question, fresh}`. A failure gives "No answer from the model: <the server's sentence>" ("… Stopped." after **Stop**) and keeps the matches.
5. A failed GET: no matches, and its reason as the line.
6. `busy` is cleared (when the run is still the newest), and `memo.redraw()` draws the box that is on the page now, which may be a newer one than the box that started the run.

`draw()`, top to bottom:

| State | What it shows |
|---|---|
| `busy` | "Asking the model (it may search your library up to 3 times)…" with a small **Stop** button (AI on; it sends `POST /api/library/ask/cancel`), or "Looking…" (AI off), `role="status"`; the button disabled |
| A question with matches or an answer | "**Your question:** <asked>" |
| An answer with `found` | `div.ai-text`: `div.ai-text-label` "Written by the AI model (on this computer)." or "(<provider>)", the `STATUS` sentence and `stepLine`; the answer as a `p`; `ul.ask-cites`, one `li` per citation: a verified one is a link `✓ “<quote>”` (`a.resume-quote`, `href` from `where`, tooltip "Open this passage") with "Your note “<title>”" or "<document> · <section>" under it (`muted small`); one that was not verified is "a passage that could not be found in your library" (`.resume-quote.unproven`); "N file(s) of secrets left out: they are never sent to a cloud model." when `left_out`; "N private item(s) (#private) left out: never sent to a cloud model." when `private_left_out` (since 4.4); the addresses the model wrote, as words ("The model wrote addresses. Readhold does not open them: …"); the budget `warning` |
| An answer that is not found | `div.ai-text` with the label "Checked by the AI model." and `stepLine` when `searched` is above 0, else "Nothing matched, so no model was asked."; "**Not found in your library.**", with " The passages below are the closest matches." when there are matches; the files of secrets line when `left_out`; the private line when `private_left_out` (a question whose only matches were private asks no model and shows it here) |
| An answer with an `id`, no run going | A link-style **Ask again** (`run(answer.question, true)`): it asks the question the answer belongs to. A "not found" that asked no model has no `id`, so no **Ask again** |
| No answer, an error line | The line |
| Matches | A `kicker` "Passages and notes that match" and `ol.ask-passages`: per match a link (`where`) with "<document> · <section>" or "Note: <title>" and the snippet under it; or "Nothing in your library matches those words." |

The links are plain `href`s: a passage opens the reader at its sentence through the router (`#/read/<id>?s=<ord>`), a note opens the Notes page. Everything is built with `h()`; the model's words are text nodes and never go through `mathText`. Styles: "Part twenty" of `styles.css` (chapter 4), with `.ask-out`, `.ask-passages` and `.ask-cites` (Part nineteen), `.ai-text…` (Part fifteen) and `.resume-quote` (Part sixteen).

Found while the 2.3 docs were written, and fixed since:

- **A box drawn while a question runs no longer stays busy.** `run` used to redraw only the box that started it. Now it calls `memo.redraw`, which always points at the box on screen, so an answer that arrives after you left the Documents tab and came back lands there. Read from the code; not checked by hand in the app.
- **A tool asked for on the last step reads plainly.** `Step` has `ran`, and such a step reads "still asked to search (or read) on the last step, where no tool runs" instead of `searched for “” (0 new)`.

Still true:

- `memo.seq` guards nothing that `memo.busy` does not already block: a second run cannot start while one is going.
- The private line uses the server's count as it is. A kept answer comes back without `private_left_out`, so the line shows only for an answer the model gave just now; and with "only #cloud" on, an item left out for having no `#cloud` tag is still called "private item (#private)".
- With "Show what will be sent" on, the POST may answer 428: `api.ts` shows the preview and sends the question again on **Send** (chapter 4). **Cancel** ends in "No answer from the model: Not sent: you did not approve it.", and the matches stay.
- There is no automated test of this file.

---

## 5.9 `review.ts`

```ts
export async function reviewView(root: HTMLElement): Promise<() => void>
```

It loads `GET /api/review/due` once: `{ cards, due_total, cap_left }`. The server already limits `cards` to what is left of today's cap (`settings.review_cap` minus today's reviews).

**State.** `i` (index), `shown` (answer visible), `done` (rated this visit). `draw()` rebuilds `div.review-card` each time.

**Card flow.**

1. The source label (`SOURCE` maps `term`, `definition`, `question`, `cloze`, `quest_question`, `lecture_note`, and `ai`: "Written by the AI model: check it against the passage on the back", for a card kept from the Study notes dialog, section 5.6) and `p.front`. Review cannot edit a card, so that label stays on an `ai` card for good.
2. "Answer in your head (or out loud) first." and "Show answer (Space)".
3. `reveal()` sets `shown` and redraws: `div.back` (the back split on blank lines into paragraphs) and four rating buttons, Again (1), Hard (2), Good (3), Easy (4).
4. `rate(n)` calls `POST /api/review/{cardId} {rating: n}`. A `saving` flag is set while the request runs; a second call in that time returns at once, so one card is not rated twice. On failure it shows an error and stays on the card. On success it advances and calls `ambience.update({ reviewed: ambience.state.reviewed + 1 })`.
5. After the last card: "Done for today" with the count, or "Nothing due", plus links to the documents and to mixed practice.

**Cap message.** The status line reads `"<i+1> of <n>"`. When `due_total > cards.length` it adds `"(cap reached — N wait for tomorrow)"`.

**Delete card** (milestone 5.1). Under every card, in `div.review-tools`, a `ghost` button titled "It will not come back in review. Undo puts it back." `removeCard(c)` calls `removeItem("card", c.id, "Card deleted. It will not come back in review.", …)` (`trash.ts`). In `gone` the card leaves `cards`, `due_total` goes down by one, `i` moves back when the card was before it, and the answer is hidden when it was the card on screen; then `draw()`. In `back` (Undo) the card goes back next in line (after the current one when its answer is showing, else at once) and `due_total` goes up again. On the server the card is also `suspended`, so editing its term or question does not bring it back (chapter 1, section 7b). Style: `.review-tools` in "Part twenty-six".

**Keys.** Space and 1–4, see section 5.2. The cleanup function removes the listener.

The header is `libraryHead("review", <Mixed practice link>)`.

---

## 5.10 `practice.ts`

```ts
export async function practiceView(root: HTMLElement): Promise<() => void>
```

**Set building.** The client does not build the set. It asks `GET /api/practice?n=10` and uses the list in the order returned. The mixing is done on the server by `practice_items` in `readhold/growth.py` (answered quest questions, answered document questions and defined terms, interleaved by topic, missed items first). Each `Item` has `source_type`, `source_id`, `prompt`, `answer`, `topic`, `topic_id` and `last_result`. "Another set" (`anotherSet`) fetches again and resets `i`, `shown` and `results`.

**Reveal and rating flow.** `draw()` rebuilds the whole `section.practice`.

1. `article.practice-card`: the topic badge, "missed last time" when `last_result === "missed"`, the counter, the prompt (`h2.practice-prompt`), and a textarea for your attempt.
2. `reveal()` (button or Enter) keeps the attempt in `attemptText` and redraws with `div.practice-reveal`: "Your try" (only if you wrote something) and "Answer".
3. Three buttons: Missed (1), Partly (2), Got it (3). `rate(r)` records the result locally and sends `POST /api/practice {source_type, source_id, result}` through `save()` without waiting. "Got it" also calls `ambience.moment()`.
4. After the last item: "Set done" with the three counts and a line that depends on whether anything was missed.

The attempt text is never sent to the server. Only the self-rating is stored (`practice_attempts`).

An empty list shows a "Nothing to practise yet" panel with a link back to Review.

`practiceView` sets `ambience.update({ mode: "review" })` (the router does the same for this route). The cleanup function removes the key listener.

---

## 5.11 `focus.ts`

```ts
export async function focusView(root: HTMLElement, id: string, params: URLSearchParams): Promise<() => void>
```

Two kinds of session:

- **A goal step.** `id` is a quest step id. The page loads `GET /api/today`, takes `t.quest` and finds the step. If it is missing it shows "That step isn't in your active goal anymore." and stops.
- **A side goal.** `id` is the literal `side`. The title comes from `?text=` and the minutes from `?min=` (default 15).

**The time box.**

- The title is `stepFor(step, energy)` from `views/today.ts`: the step's `low` or `high` wording for that energy, else its title.
- Minutes: the step's minutes, or at low energy `max(5, round(minutes / 3))`.
- On mount, before any button is pressed, it creates the session: `POST /api/sessions {energy, time_box_min, quest_id, step_id, question: title}`.
- A 500 ms interval adds elapsed time to `focusedMs` while `running` and the tab is visible. It updates `div.focus-clock` (counting down, then `+m:ss` past the box), sets the CSS variable `--p` on `div.focus-ring`, and sets `ambience.state.session`.
- When the box runs out it adds class `over` to the ring and shows one toast. Nothing is forced; the clock keeps counting.
- A 15 s interval saves `PATCH /api/sessions/{id} {focused_ms}`.
- "Pause" (`togglePause`) flips `running` and sets ambience mode `reading` or `break`.

**The three exits** (as the file header names them) plus Stop:

| Exit | Function | What it asks | What it saves |
|---|---|---|---|
| Done (D) | `finish("done")` | "What did it produce?" (one line; empty becomes `"done"`) and `feelRow()` | `PATCH /api/quest-steps/{id} {done: true, output}` when there is a step, then the session patch below |
| Stuck? | `stuck()` | A three-point protocol; "Park as a question" asks what is blocking you | `POST /api/ideas {text: "Stuck: …"}`. The session continues |
| Park a thought (P) | `parkThought()` | One line | `POST /api/ideas {text}`. The session continues |
| Stop / "Back to the main goal" | `finish("stop")` | After ≥ 3 focused minutes: `feelRow()`, with "Keep going" to cancel. Under 3 minutes: nothing | The session patch below |

The session patch in `finish` is `PATCH /api/sessions/{id} {focused_ms, output, ended: true, feel?}`. It then shows a "Done …" or "Stopped …" toast and goes to `#/home`.

**Cleanup.** Clears both intervals, removes the key listener, and, if the session was not ended through `finish`, saves `PATCH /api/sessions/{id} {focused_ms, ended: true}`. Then sets ambience mode `idle`.

The "Done (D)" button is not drawn for a side goal.

---

## 5.12 API endpoints called by these files

| Method and path | Called from |
|---|---|
| `GET /api/documents/{id}` | `Reader.mount` |
| `GET /api/documents/{id}/annotations` | `Reader.mount` |
| `GET /api/documents/{id}/assets/{name}` | `Reader.assetUrl` (as an `<img src>` in `renderEquation` and in `dlg.peek`) |
| `POST /api/documents/{id}/position` | `Reader.savePosition` (debounced) |
| `POST /api/documents/{id}/read` | `Reader.flushRead` |
| `GET /api/documents/{id}/resume` | `resumeBlock` (`resume.ts`), started by `resumeSlot` from `dlg.sessionSetup` |
| `POST /api/documents/{id}/resume/brief` | `resumeBlock`: the **Recap with AI**, **Try again** and **Ask again** buttons, and nothing else |
| `POST /api/documents/{id}/explain` | `explainSelection` (`explain.ts`): the **Explain**, **No idea, explain** and **Ask again** buttons, and nothing else |
| `POST /api/ai/results/{id}/note` | `explainSelection`: **Save as a note** |
| `GET /api/documents/{id}/digest` | `digestDialog` (`digest.ts`): on open, and every 800 ms while a job runs and the dialog is open |
| `POST /api/documents/{id}/digest` | `digestDialog`: the **Digest with AI**, **Go on with the digest** and **Ask again** buttons, and nothing else |
| `POST /api/documents/{id}/digest/cancel` | `digestDialog`: **Stop** |
| `GET /api/documents/{id}/ask?q=` | `askTab` (`ask.ts`): **Find passages** / **Ask**, Enter in the box, **Ask again** |
| `POST /api/documents/{id}/ask` | `askTab`: the same, only with AI on, and nothing else |
| `POST /api/documents/{id}/study-notes` | `studyNotesDialog` (`studynotes.ts`): the **Write** and **Ask again** buttons, only with AI on, and nothing else |
| `POST /api/ai/results/{id}/accept` | `studyNotesDialog`: **Keep the chosen notes**, **Add the chosen cards to Review**, **Keep as a card** |
| `POST /api/brainstorm` | `aiIdeasBox` (`aibrainstorm.ts`, from `brainstormDialog` and the brainstorm sheet): **Ideas from the model** and **Ask again**, only with AI on, and nothing else |
| `POST /api/brainstorm/cancel` | `aiIdeasBox`: **Stop** |
| `POST /api/brainstorm/{id}/keep` | `aiIdeasBox`: right after the model answers (`putIn`), with no button of its own |
| `POST /api/brainstorm/{id}/undo` | `aiIdeasBox`: **Undo** in the box and in the toast |
| `GET /api/organize/{id}` | `organizeDialog` (`organize.ts`): on open, and after a failed save |
| `PUT /api/documents/{id}/tags` | `organizeDialog`: Enter in the tag box, **×**, **+ #tag**, **Undo** |
| `POST /api/documents/{id}/organize/suggest` | `organizeDialog`: **Suggest tags and related documents** and **Ask again**, only with AI on |
| `GET /api/ai/why/{result_id}` | `whyDialog` (`why.ts`), from the **Why did it say this?** link beside an AI label. Calls no model |
| `POST /api/documents/{id}/slow` | `Reader.sendSlow` |
| `GET /api/library/ask?q=` | `libraryAskBox` (`libraryask.ts`): **Find passages** / **Ask**, Enter in the box, **Ask again** |
| `POST /api/library/ask` | `libraryAskBox`: the same, only with AI on, and nothing else |
| `POST /api/library/ask/cancel` | `libraryAskBox`: **Stop** |
| `PATCH /api/documents/{id}` | `Reader.setPass` (`current_pass`); `dlg.explainIt` (`explain_text`, `status`); `summary.ts` `critiqueBox` (`critique`, `reproduce`); `library.ts` `afterImport`, `editWhy`, `setDeadline` (`why`, `deadline`) |
| `DELETE /api/documents/{id}` | `library.ts` `remove` |
| `POST /api/documents/{id}/restore` | `library.ts` `remove` (Undo) |
| `GET /api/documents` | `library.ts` `refresh` (the queue, with `flags` and `tags`) |
| `GET /api/documents/{id}/define?term=` | `dlg.guessGate` |
| `GET /api/documents/{id}/summary` | `summaryView` |
| `POST /api/documents/{id}/export` | `summary.ts` `exportMd` |
| `POST /api/import/file` | `library.ts` `importFiles` |
| `POST /api/import/text` | `library.ts` `importPaste` |
| `PATCH /api/sections/{id}` | `Reader.toggleBackground` (`background`); `dlg.predict` (`prediction`); `dlg.checkPrediction` (`prediction_check`) |
| `GET /api/templates?kind=` | `reader-panels.ts` `questionsTab` |
| `POST /api/questions` | `reader-panels.ts` `createQuestion` |
| `PATCH /api/questions/{id}` | `dlg.recall` (`answer`) |
| `DELETE /api/questions/{id}` | `reader-panels.ts` `deleteQuestion` |
| `POST /api/questions/{id}/link` | `dlg.tagParagraph` |
| `POST /api/highlights` | `Reader.highlight` |
| `PATCH /api/highlights/{id}` | `reader-panels.ts` `hlItem` (`note`, `resolved`); `dlg.clozePicker` (`cloze`); `dlg.confusionFirst` (`resolved`) |
| `DELETE /api/highlights/{id}` | `Reader.highlight` |
| `POST /api/notes` | `dlg.addNote` |
| `PATCH /api/notes/{id}` | `dlg.showNotes` (the server also empties `origin` when the text changed) |
| `DELETE /api/notes/{id}` | `dlg.showNotes` |
| `POST /api/terms` | `dlg.guessGate` |
| `POST /api/ideas` | `dlg.quickIdea`; `dlg.peek` ("Save to reading list"); `summary.ts` `critiqueBox`; `focus.ts` `stuck`, `parkThought` |
| `POST /api/pages/quote` | `dlg.quoteToNote` |
| `POST /api/sessions` | `SessionTracker.start` (from `Reader.startFlow`); `focusView` |
| `PATCH /api/sessions/{id}` | `SessionTracker.flush`, `flushOnUnload`, `end`, `leave` (`session.ts`); `Reader.onSessionTick` (`time_box_min`); `focusView` (heartbeat, `finish`, cleanup) |
| `PUT /api/settings` | `Reader.setMode`, `changeWpm`, `rampSpeed`; `dlg.comfortPopover` through `saveSettings` |
| `GET /api/quest/active` | `dlg.questCheck`; `dlg.endSession`; `summary.ts` `critiqueBox` |
| `POST /api/side-quests` | `dlg.questCheck` |
| `PATCH /api/quest-steps/{id}` | `dlg.endSession`; `focus.ts` `finish` |
| `POST /api/quests/{id}/steps` | `summary.ts` `critiqueBox` |
| `GET /api/today` | `focusView` |
| `GET /api/review/due` | `reviewView` |
| `POST /api/review/{cardId}` | `review.ts` `rate` |
| `DELETE /api/items/card/{id}`, `POST /api/items/card/{id}/restore` | `review.ts` `removeCard`, through `removeItem` (`trash.ts`; milestone 5.1) |
| `DELETE /api/items/ai_result/{id}`, `POST /api/items/ai_result/{id}/restore` | `whyDialog` (`why.ts`), **Delete this result**, through `removeItem` (milestone 5.1) |
| `GET /api/practice?n=10` | `practiceView`, `anotherSet` |
| `POST /api/practice` | `practice.ts` `rate` |

Not in this table because other modules make the call: the Connected card's requests (`related.ts`) and the tab counts (`libtabs.ts`).

Two call styles are used. `api.*` throws on failure. `save()` (in `api.ts`) retries three more times with a growing delay and is used for writes fired without waiting.

---

## 5.13 Rules these files must keep

**Text only through text nodes or `mathText`.**

- No file in this chapter uses `innerHTML`. Everything is built with `h()`, which turns string children into text nodes.
- Document text that may hold math goes through `mathText()` (`renderParagraph`, `renderSentence`, `renderEquation`, `hlItem`, `dlg.peek`, `go()` in `summary.ts`, card fronts and backs in `review.ts`, prompts and answers in `practice.ts`, the title in `focus.ts`). `mathText` returns text nodes and KaTeX-built elements; KaTeX runs with `trust: false`, and a failing formula falls back to plain text (`mathEl` in `math.ts`).
- Equation pictures are `<img>` elements whose `src` is built by `Reader.assetUrl` with `encodeURIComponent`; the `alt` is `plainMath(text)`.
- The side-goal title in `focus.ts` comes from the URL (`?text=`) and is also rendered through `mathText`.
- The progress jar is SVG built with `createElementNS`, with no document text in it.
- Every AI label has the **Why did it say this?** link next to it (`whyLink`). A new AI feature adds it too. The panel (`why.ts`) draws names, sizes and the start of what came back with `h()` only, and never shows a source's text.
- What a model wrote (`resume.ts`, `explain.ts`, `digest.ts`, `ask.ts`, `libraryask.ts`, `studynotes.ts`, `aibrainstorm.ts`, `organize.ts`, and its start in `why.ts`) is drawn with `h()` only and sits inside `div.ai-text` under a label that says a model wrote it. It never goes through `mathText`, and an address in it is shown as words.
- A margin note with `origin === "ai"` is shown with its label wherever the reader lists notes with their text (`showNotes`, `notesTab`). The label is removed only by an edit that changes the text.
- The "Explain" button exists only while AI is on, and the Explain dialog sends nothing until a button in it is pressed.
- The Digest dialog shows the outline and the reading time with AI on or off, and starts a digest only from its buttons. It polls only while a job runs and the dialog is open.
- The Ask tab finds passages with AI on or off and asks the model only from its button (or Enter, or **Ask again**) while AI is on. A question is sent to the server, never to a model by the page.
- The *Ask your library* box does the same across the library; the page sends the question and `fresh` and nothing else, and **Stop** sends an empty body. It never builds a prompt, chooses a tool or sends an anchor: the loop runs on the server.
- The Study notes dialog sends nothing on open and asks the model only from **Write** or **Ask again** while AI is on. It keeps only what the reader ticks and presses Keep for, and only items with a checked passage can be ticked. A Keep button is disabled while its request runs, so one press makes one copy.
- The Brainstorm box sends nothing when drawn and asks the model only from **Ideas from the model** or **Ask again** while AI is on; for a document only after the reader wrote a line of their own, which is never sent. It keeps only ideas with a checked passage that the reader ticks, and runs `hooks.after` after every keep, also a failed one.
- The Organize dialog changes tags only on the reader's press, and every change sends `expect`; an Undo expects exactly the tags its own change produced. Its AI part asks the model only from its button while AI is on, and adds nothing by itself.

**No re-render on pacer ticks.**

- `Reader.show()` moves the `cur` class and nothing else in the paper. `Reader.done()` adds `read`. `playState()` toggles `playing`.
- Rebuilds happen only on user actions: `renderSections()` in `toggleHidden`, `rerenderParagraphOf()` after tagging or deleting a question, `renderMap()` after structural changes, `renderSide()` after annotation changes.
- If you add something to `show()`, keep it to class toggles and cheap lookups in `sentEls` / `parEls`. In word mode it runs for every word.

**Autosave with `debounce` and `flushPending`.**

- The only debounced save in these files is `Reader.savePosition`. It uses `util.debounce`, so `flushPending()` (router and page close, in `main.ts`) covers it.
- Read marks are buffered instead: `readBuffer` → `flushRead()` on a 4 s interval, in `destroy()`, and with `keepalive` on `beforeunload`.
- Session counters: `SessionTracker.flush()` every 15 s, `flushOnUnload()` on `beforeunload`, and `leave()` in `Reader.destroy()`, which sends them one last time with `ended: true`.
- Everything else (highlights, notes, questions, terms, ideas, ratings) is sent in the click or key handler that made it. There is no Save button for annotations.

**Ambience updates.**

| Where | Call |
|---|---|
| `Reader.playState` | `ambience.update({ mode: "reading" \| "idle" })` |
| `Reader.updateProgress` | `ambience.update({ progress, answered })` |
| `Reader.onSessionTick` | `ambience.state.session = seconds`; `ambience.update({ mode: "break" })` at the end of the time box |
| `dlg.recall`, `dlg.endSession` (step finished) | `ambience.moment()` |
| `review.ts` `rate` | `ambience.update({ reviewed: +1 })` |
| `practiceView`, `rate` | `ambience.update({ mode: "review" })`; `ambience.moment()` on "Got it" |
| `focusView` | `mode: "reading"` at start, `"break"` on pause, `"idle"` in cleanup; `ambience.state.session`; `ambience.moment()` on Done |
| `route()` in `main.ts` | Resets `mode` (`review` for review and practice, else `idle`) and `session: 0` on every route change |

**Other rules visible here.**

- Network use: none. Every call in these files goes to the app's own server. `library.ts` imports only a file you pick or drop, or text you paste, and the reference peek only saves a line to the idea inbox. `tests/test_no_network.py` checks that no file in `web/src/` has a `fetch` to an `http` address, a `WebSocket`, an `EventSource` or `sendBeacon`.
- Scrolling respects reduced motion (`prefersReducedMotion()` in `scrollTo` and `keepInView`).
- Every listener added on `document` or `window` has a matching removal in the page's cleanup function (`Reader.cleanup`, and the functions returned by `reviewView`, `practiceView`, `focusView`).

---

## 5.14 Gotchas and fragile spots

These were found by reading the code.

**Reader**

- **The focus view class goes on `div.reader`, not on `root`.** `this.root` is `#app`, and `div.reader` is its child. The stylesheet's rule is `.reader.focus-view .paper …`, so `setFocusView` toggles the class on `this.root.querySelector(".reader")`. The Focus page uses the same class name on its own container; its width rules are written `.view.focus-view`, so they do not match the reader.
- **`playing` class has no CSS.** `playState` toggles `playing` on `root`, but the string "playing" does not occur in `styles.css`.
- **`learnFrom` does less than its comment says.** The comment mentions long dwells raising the slow-down. The code only sends `−0.3` for racing ahead. The raise comes from `manualStep(-1)` only.
- **Controls are found by position.** The R key ticks the first `.toggle input` in the bar; `setFocusView` ticks the second; the W key sets the first `<select>`. Reordering `renderBar` breaks these without a type error.
- **Leaving without "End session" still ends the session, but with less.** `destroy()` calls `session.leave()`, which sends the counters and `ended: true`. Finishing through the explain-it dialog (which navigates to the summary) and the "← Home" link both take this path. Only `SessionTracker.end()`, called from `endSession`, also saves `next_step`, `output` and `feel`. `leave()` does not wait for its request and marks the tracker ended before it is sent.
- **A reader that loads late must stay off the screen.** The reader draws straight into `#app`. `mount` checks `current()` after its only `await` and before it touches `root`; `startFlow` checks `gone` after each `await`. New code in either that comes after an `await` needs the same check.
- **The Start a session dialog waits for no request.** `sessionSetup` puts `resumeSlot(...)` into the dialog and opens it; `GET /api/documents/{id}/resume` fills the slot in later, or leaves it empty. The route still calls no model; keep it that way.
- **A recap is asked for only by a click.** `resumeBlock` must never call the brief route by itself (decision on open question 2 of the AI plan, 2026-11-25).
- **"Today" in the facts line is the calendar day.** `when()` counts days between local midnights, so a session that ended last night reads "Yesterday" the next morning.
- **A code block has no sentence spans.** `selectionRange()` is `null` inside `pre.p.code`, so highlights and "→ Note" are not offered there; "Explain" works through `codeRange`, which relies on `data-pid` on the `pre` and on a code paragraph being one sentence.
- **A failed "Ask again" leaves the recap you had.** `ask` draws `shown` again under the error line, with a "Try again" button.
- **A running recap has no Cancel.** The request goes on after the dialog closes; the page passes no `call_id`. Switching AI off stops it.
- **Esc in "Start a session" starts the session.** The modal is dismissable and its `.then` does not look at the result, so Esc or a backdrop click behaves like "Start reading" with the current choices.
- **Side-quest check saves on click.** A question chip or the 15-minute chip posts to `/api/side-quests` at once, and every further click posts again. Choosing a question and then "park it" leaves the "linked" row saved and `doc.quest_question_id` set in memory, while the session is parked.
- **"All" is not remembered.** `setPass(0)` saves nothing, so a paper reopens in its last saved pass, except for the pass-1-with-a-position override in `mount`.
- **Clean view is switched in memory only.** `toggleHidden` may set `state.settings.clean_view = true` without saving it.
- **Section height is an estimate.** The `min-height` formula uses the global `font_size`, `line_width` and `line_height`, not the per-type comfort values or the real column width. The scroll bar length shifts as sections fill in. `scrollTo` and `jumpTo` call `ensureRendered` on the target section first, but sections above it may still be estimates.
- **Only nine questions can be tagged by key**, and while waiting for the digit after Q the keys 1–5 do not highlight.
- **`manualStep(1)` marks the current sentence read even if there is no next sentence.**
- **Overlapping highlights show one colour** (the last in `hlByOrd`). Removal needs the exact same range and type, which the Notes tab "Remove" button supplies.
- **Template requests.** `questionsTab` fetches `/api/templates` on every side-panel render while the Questions tab is open, which includes every section change during pacing. A late answer is written into a detached body, so it is harmless, but it is a request per render.
- **Peeks are mouse-only.** `span.peek` has `tabindex="0"`, but there is no key handler for it; only click and hover open it.
- **Module-level state in `reader-dialogs.ts` and `reader-panels.ts`.** `peekEl`, `peekPinned`, `selBar` and `dismissedTemplates` outlive a `Reader`. The router removes `.peek-pop` and `.sel-bar` elements on route change, but the variables keep pointing at the removed nodes until the next use.
- **Errors in `highlight`, `addNote`, `tagParagraph` and similar handlers are not caught locally.** They surface through the global `unhandledrejection` toast in `main.ts`. Local state is updated only after the request succeeds, so the page stays consistent.
- **`keyHelp` is a hand-written list** and does not include "?" itself.

**Summary, Documents**

- **Critique saves on `change`,** which fires when the field loses focus. It is not debounced, so `flushPending()` does not cover it. Clicking a link blurs the field first; a navigation that does not blur it could lose the last edit.
- **A badly formatted deadline right after import is dropped silently** (`afterImport`), while the "Deadline" button shows an error for the same input.
- **`overdue` compares with the UTC date** (`new Date().toISOString().slice(0, 10)`), which can differ from the local date near midnight.
- **Undo of a removal lives only in the toast** (8 s).

**Review, Practice**

- **One rating per card.** `rate` in `review.ts` awaits the POST before advancing `i`. The `saving` flag makes a second key press or click during that wait do nothing; keep it if you change `rate`.
- **Review keys do not check focus.** The handler checks for an open modal, and for Ctrl, Meta or Alt on the digits 1–4. It does not use `isTyping`, and Space is not checked for modifiers.
- **Practice results are fire-and-forget.** A failed `POST /api/practice` (after retries) is only logged to the console.
- **"Set building on the client" does not exist.** Do not look for it in `practice.ts`; change `practice_items` in `readhold/growth.py`.

**Focus**

- **The session row is created on page load.** Opening and leaving at once still leaves a session (ended by the cleanup with whatever time was counted).
- **D works for a side goal** even though the Done button is hidden there. It opens the Done dialog and saves the output on the session; no step is patched.
- **`ended` is set before the final PATCH.** If that request fails, the cleanup will not retry it, because it only saves when `ended` is false. This call uses `api.patch`, not `save()`.
- **Time counts only while the tab is visible,** in steps of at most 5 s per tick. Unlike the reader, window focus and recent activity are not required.
