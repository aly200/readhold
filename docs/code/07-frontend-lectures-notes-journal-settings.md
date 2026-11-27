# 7. Front end: lectures, notes, journal, Think, and the small pages

This chapter covers six files in `web/src/views/`. Together they hold most of the "write things down" side of the app.

| File | Page in the app | Address |
|---|---|---|
| `lectures.ts` | Study → Lectures (the shelf) | `#/lectures` |
| `lecture.ts` | The lecture desk | `#/lecture/<id>` |
| `notes.ts` | Notes → All notes, plus the table and the big map | `#/notes`, `#/notes/<id>`, `#/notes/today`, `#/notes/<yyyy-mm-dd>`, `#/notes/table`, `#/notes/map` |
| `journal.ts` | Notes → Journal | `#/journal`, `#/journal/<yyyy-mm-dd>` |
| `think.ts` | Notes → Think, and the brainstorm sheet | `#/think`, `#/think/page/<id>`, `#/think/idea/<id>` |
| `misc.ts` | Study → Glossary and concept pages, Notes → Ideas, Stamina, Settings, Fix structure | `#/glossary`, `#/glossary?concept=<term>`, `#/ideas`, `#/stats`, `#/settings`, `#/structure/<docId>` |

Where they sit in the menu (the tab lists are in `views/libtabs.ts`):

- **Study** has the tabs Lectures, Documents, Goals, Review, Glossary. A page shows this header with `libraryHead("<tab id>")`. The tab ids are `study` (Lectures), `documents`, `goals`, `review`, `glossary`.
- **Notes** has the tabs All notes, Journal, Ideas, Think. A page shows this header with `notesHead("<tab id>")`. The ids are `notes`, `journal`, `ideas`, `think`.
- **Stamina** and **Settings** are their own menu entries and have no tab header.

Naming: the code keeps old names. The Lectures tab is `lectures` in code and its tab id is `study`. "Goals" are `quest` in code. The Documents tab is `#/library`. The Study menu entry has the id `library`.

Routing is in `route()` in `main.ts`. Three things there matter for this chapter:

- `#/lecture/<id>` is mounted in its own root, `div.lecture-root`, next to the side menu, not in the usual `div.view`.
- `thinkView(main, id, extra)` gets the second and third parts of the address, so `#/think/page/abc` arrives as `sub = "page"`, `id = "abc"`.
- `lectureView`, `notesView`, `journalView` and `thinkView` return a cleanup function. The views in `misc.ts` and `lecturesView` return nothing.

All six files build their pages with `h(tag, attrs, ...kids)` from `util.ts`. `h()` puts strings in as text nodes. None of these files uses `innerHTML`.

---

## 7.1 `lectures.ts`: the shelf

One exported function:

```ts
export async function lecturesView(root: HTMLElement): Promise<void>
```

The page is `section.lectures.study` with, in order: `libraryHead("study")`, an intro panel, two tiles in `div.study-tiles`, a hidden file input, a `div.busy` spinner, and the list `div.lecture-grid`.

### The two tiles

**Blank notebook** (`div.study-tile.notebook`). It holds four paper buttons built from `PAPERS` (`lined`, `dotted`, `grid`, `plain`; class `paper-pick paper-<v>`). The chosen paper is the local variable `paper`, default `lined`. A paper button calls `stopPropagation()` so it does not also start the notebook. Clicking the tile, or pressing Enter while the tile itself has focus, runs `startNotebook()`:

1. `askText("New notebook", …)` asks for a title. Cancel stops here.
2. `POST /api/lectures/notebook` with `{ title, paper }`. An empty title becomes `"My notes"`.
3. The address changes to `#/lecture/<new id>`.

**Upload** (`div.drop.study-tile.files`). Click or Enter opens the hidden `<input type="file" accept=".pdf,.pptx,.html,.htm" multiple>`. Dragging files over the tile adds the class `over`; dropping them starts the import.

### The upload flow: `importFiles(files)`

Files are sent one at a time, in order. For each file:

1. The spinner is shown with the text `Importing <name>…`.
2. The file goes in a `FormData` under the field `file` to `POST /api/lectures/import` through `api.upload`.
3. On success a toast says `Added "<title>" — N pages`. On failure a toast shows the server's reason for 8 seconds. The loop goes on to the next file.

After the loop, `refresh()` reloads the list. The server checks the content, not the file name (see `readhold/lectures.py`); the `accept` attribute is only a hint to the file picker. The server refuses files over 50 MB with status 413.

### The list: `refresh()`

`GET /api/lectures` returns rows with `id, title, kind, pages, position, notes, updated_at`, newest first. Each row becomes `article.lecture-card.kind-<kind>`:

- A link `a.lecture-open` to `#/lecture/<id>` with a badge (`ICON` and `KIND` give the icon and the word: PDF, Slides, Web page, Notebook), the title, and a line of where you are. For `html` the line is "Web page". For `notebook` it is the page count. For `pdf` and `pptx` it is "Page X of Y" plus a progress bar (`span.meter`). The number of notes is added when it is not zero.
- **Rename**: `askText`, then `PATCH /api/lectures/<id>` with `{ title }`, then `refresh()`.
- **Remove**: `confirmBox`, then `DELETE /api/lectures/<id>` (a soft delete), then `refresh()` and a toast with an **Undo** button for 8 seconds. Undo calls `POST /api/lectures/<id>/restore`.

An empty list shows `p.empty-hint`.

---

## 7.2 `lecture.ts`: the lecture desk

```ts
export function pageView(lec: Lecture, p: LecturePage, opts: { width?: number } = {}): HTMLElement
export async function lectureView(root: HTMLElement, id: string): Promise<() => void>
```

`lectureView` is one long closure. All state is in local variables; nothing is module-level except constants.

### Start-up

Two requests run before anything is drawn: `GET /api/lectures/<id>` (the lecture with its `page_list`) and `GET /api/lectures/<id>/notes` (every note of the notebook). The current page starts at `lec.position`.

State variables worth knowing:

| Variable | Meaning |
|---|---|
| `page` | Index of the page shown (0-based, equal to `LecturePage.ord`) |
| `mode` | `"read"`, `"pen"` or `"snip"` |
| `tab` | Notebook tab: `"page"`, `"all"`, `"cornell"`, `"links"` |
| `recallMode` | Cover each page until you write what you remember |
| `focus` | Side panels hidden |
| `pad`, `padBar` | The `InkPad` over the page and its toolbar (only in pen mode) |
| `previews` | Read-only `InkPad`s of sketch cards, destroyed and rebuilt with the notebook |
| `editingSketch`, `live` | The sketch being drawn in the notebook and its pad, toolbar, caption field |
| `nextColor` | Colour of the next sticky note |
| `isHtml`, `isBook` | `lec.kind === "html"` / `"notebook"` |

### Layout

```
div.lecture-view
  div.lecture-desk.tint-<tint>      (background, prepended)
  header.lec-top                    (renderTop)
  div.lec-body                      (class "single" is added for HTML lectures)
    nav.lec-thumbs                  (renderThumbs)
    div.lec-stage                   (renderStage)
    aside.lec-book                  (renderBook)
```

Four render functions redraw one region each: `renderTop`, `renderThumbs`, `renderStage` (async) and `renderBook`. They are called by hand after each change; there is no reactive layer.

### The top bar: `renderTop()`

Left to right: a link back to `#/lectures`, the title, the page counter `N / total` (not for HTML), then `div.lec-tools`:

| Control | Shown for | What it does |
|---|---|---|
| Pen | all kinds | `setMode("pen")`, or back to `"read"` if already on |
| Snip | PDF and PowerPoint | `setMode("snip")` |
| Recall mode | PDF and PowerPoint | `toggleRecall()` |
| Page tint select | PDF and PowerPoint | `normal`, `dim`, `sepia`, `night`; sets classes on `desk` and `stage`, saves with `PATCH /api/lectures/<id>` `{ page_tint }` |
| Paper select | notebooks | Sets `layout.paper` of the current page, swaps the `paper-*` class on `.page-sheet`, saves with `PATCH /api/lectures/<id>/pages/<ord>` `{ paper }` |
| + Page | notebooks | `addPage()` |
| Timer | all kinds | `timerMenu(button, { label: "Study: <title>", link_type: "lecture", link_id: id })` |
| Focus | all kinds | `toggleFocus()` |
| Export | all kinds | `exportNotes()` |

### How each kind of page is drawn

`pageView(lec, p, opts)` returns a `div.page-sheet` with the page's aspect ratio (`p.width / p.height`, or `4 / 3`). It is used in three places: the stage, the thumbnails and inside snips.

**PDF.** One `<img>` whose source is `/api/lectures/<id>/pages/<ord>/image?w=<width>`. The width is the wanted CSS width times the device pixel ratio (at most 2), capped at 2000. The server renders the page to a PNG through PDFium, never taller than 20,000 pixels (`lectures.MAX_RENDER_PX`, since milestone 4.5): a page drawn very tall comes back narrower than asked.

**PowerPoint.** The server turned the deck into JSON at import. `p.layout` has `bg` and `els`. `pageView` gives the sheet the class `slide` and the background colour, and calls `slideEl()` for each element. Positions and sizes are percentages of the slide. `slideEl()` handles four types:

- `image`: an `img.sl-img` from `/api/lectures/<id>/assets/<name>` (the name is passed through `encodeURIComponent`; the server only serves names matching `img-<16 hex>.<ext>`).
- `box`: a `div.sl-box` with a fill colour.
- `table`: a CSS grid `div.sl-table`; the first row's cells get the class `th`.
- text (the default): `div.sl-text`, with class `title` for a title box. Each paragraph is a `<p>`; each run is a `<span>` from `pptRun()` with bold, italic, colour and size. Paragraphs get the class `bul` (a bullet) when the box is not a title and has more than one non-empty paragraph. Indent is 4% per level.

Font sizes use container query units: `(points / slideWidth) * 100` in `cqw`. So text scales with the slide, in the stage and in a thumbnail alike. This depends on the CSS making `.page-sheet.slide` a size container.

No HTML from the deck is ever used. Every string from the JSON goes through `h()` as a text node. Colours and sizes go in through `style` properties.

**Notebook.** In thumbnails, `pageView` returns `div.page-sheet.nb-paper.paper-<paper>` with the first 700 characters of the page's text as a text node. On the stage the page is drawn by `renderPaperStage()` instead (below).

**HTML.** `pageView` returns an empty sheet for HTML lectures; it is never shown, because thumbnails are skipped for them. The stage is drawn by `renderHtmlStage()`.

### The stage: `renderStage()`

Every call first destroys the old `InkPad`, runs `stageCleanup`, clears the stage and sets its classes (`lec-stage tint-<tint> mode-<mode>`). Then it branches by kind.

**PDF and PowerPoint.** It builds `div.page-frame` holding the `pageView` and `div.ink-host`, calls `fitFrame()`, creates `new InkPad(inkHost, { owner: "lecture_page/<id>:<ord>" })`, enables it only in pen mode, and loads the saved ink. In pen mode it adds the ink toolbar with a "Done" button. In snip mode it calls `armSnip(frame)`. In recall mode, if the page has no `recall` note yet, it calls `coverForRecall(frame)`.

**HTML: `renderHtmlStage()`.** It builds:

```ts
h("iframe", { class: "lec-iframe", src: `/api/lectures/${id}/content.html`,
              sandbox: "allow-scripts", referrerpolicy: "no-referrer", title: lec.title })
```

next to a transparent `div.html-ink-view`, both inside `div.html-frame`. The ink pad sits in the view and has the owner `lecture_page/<id>:0`.

The page and the app talk only through two `postMessage` shapes:

- The page sends `{ readhold: "scroll", x, y, … }` (the script is `SCROLL_REPORTER` in `lectures.py`, added to every HTML lecture by the server). `onMessage` accepts it only if `e.source === iframe.contentWindow`, and only if `x` and `y` are finite and not negative. It then calls `pad.setOffset(x, y)`, so ink stays on the same place of the page while it scrolls. The message also carries `w`, `h`, `vw`, `vh`; the front end does not use them.
- In pen mode the ink layer covers the page, so the mouse wheel is caught by `onWheel` and forwarded as `{ readhold: "scroll-by", dx, dy }`.

The `message` listener is removed by `stageCleanup`.

**Notebook: `renderPaperStage()`.** The sheet holds a `textarea.paper-write` with the page's text, a decorative tape, and the page number. The ink host lies over it. Typing updates `p.text` and calls the debounced `saveText(ord, text)` (600 ms, `PATCH /api/lectures/<id>/pages/<ord>` `{ text }`). The textarea's scroll position is passed to `pad.setOffset(0, scrollTop)`. In pen mode the wheel on the ink layer scrolls the textarea. An empty page takes focus when nothing else is being typed in.

**Sizing: `fitFrame()`.** It sets the frame's width so the whole page fits the stage with 48 px of margin, at least 200 px. A `ResizeObserver` on the stage calls it, at most once per animation frame. It does nothing for HTML.

### Page navigation and position

`go(p)` is the only way to change page. It clamps `p`, returns if nothing changes, then:

1. `pad?.flush()` and `saveText.flush()` write pending ink and text of the page being left.
2. Sets `page` and calls the debounced `savePos(page)` (600 ms, `PATCH /api/lectures/<id>` `{ position }`).
3. Tells the theme scene the progress with `ambience.update({ progress })`.
4. Redraws the top bar, thumbnails and stage, and the notebook if its tab is `"page"`.

`go()` returns at once for HTML lectures: they have one page.

`renderThumbs()` draws one `button.lec-thumb` per page with a small `pageView` (width 240), the page number and a count of the notes on that page. Notebooks get an extra `button.lec-thumb-add`. The current thumbnail is scrolled into view.

`addPage()` (notebooks only) flushes the text, calls `POST /api/lectures/<id>/pages`, pushes the new page into `lec.page_list`, goes back to read mode and calls `go()` on the new page. The server allows up to 500 pages and copies the paper of the last page.

### The notebook panel: `renderBook()`

Every call first runs `closeLive()` and destroys all sketch previews, then clears the panel and rebuilds it:

- `bookGrip`, the resize handle on the left edge.
- `div.book-head` with the tabs and the text-size buttons (`A−`, `A+`).
- `div.book-body` with the content of the tab.

| Tab | Label | Content |
|---|---|---|
| `page` | "Page N" ("Notes" for HTML) | Speaker notes in a `<details>` if the page has any, the composer, then the note cards of this page. For HTML: all notes except the Cornell sheet |
| `all` | "All notes" (not shown for HTML) | Notes grouped by page, each group under a `button.book-page-head` that jumps to the page. Notes with no page and the Cornell sheet are left out |
| `cornell` | "Cornell sheet" | `cornellSheet()` |
| `links` | "Linked" | `connectedCard("lecture", id, lec.title)` from `related.ts`: notes that link to this lecture, mentions, open tasks, and buttons to make a linked note or task |

**Width.** Dragging `bookGrip` sets the CSS variable `--book-w` on `.lec-body`. The width is clamped between 260 px and 62% of the body. On release it is saved with `saveSettings({ notebook_width })`. A double-click saves `0`, which means automatic. `applyBookSize()` applies both settings.

**Text size.** `noteScale(±0.1)` keeps `note_scale` between 0.8 and 1.6, saves it, and sets `--note-scale` on the panel.

### The composer

`composer()` builds `div.composer.sticky.c-<colour>`: a textarea, six colour dots (`STICKY`: `sun`, `mint`, `sky`, `lilac`, `peach`, `rose`), and the buttons Add note, Question card, Snip (PDF and PowerPoint only), Sketch, and "Slide → question" (only when the page has a title and the lecture is not HTML).

### Every kind of note

All notes are rows of `lecture_notes` with `kind`, `page` (or `null`), `body`, `data` (JSON) and `color`. They are created with `POST /api/lectures/<id>/notes`, changed with `PATCH /api/lecture-notes/<nid>`, and deleted with `DELETE /api/lecture-notes/<nid>`. The front end keeps them in the array `notes` and edits that array after each call. `noteCard(n)` draws one note. Every card has a `button.note-del` that asks with `confirmBox` first.

| Kind | `page` | `body` | `data` |
|---|---|---|---|
| `text` | the page (`null` for HTML) | the text | `{}`; colour is in `color` |
| `question` | the page (`null` for HTML) | the front | `{ back }` |
| `snip` | the page | the caption | `{ x, y, w, h }` as fractions of the page |
| `sketch` | the page (`null` for HTML) | the caption | `{ ratio }` (height / width); strokes are in the `ink` table |
| `recall` | the page | what you remembered | `{}` |
| `cornell` | `null` | empty | `{ cues, notes, summary }` |

**`text` (sticky note).**
- Create: the composer's `add()`. It trims the text and rewrites keyboard math: `$$…$$` becomes `\[…\]` and `$…$` becomes `\(…\)`. Then it posts `{ page, kind: "text", body, color: nextColor }`. Ctrl+Enter in the textarea does the same.
- Draw: `div.note-card.text.sticky.c-<colour>`. Each line is a `<p>` whose content comes from `mathText(line)`, so stored math is drawn by KaTeX and the rest is text nodes. `stickyOf()` maps an unknown colour to `sun`.
- Recolour: a dot saves `{ color }` with `save("patch", …)` and swaps the class in place.
- Edit: click the card (or Enter on it). `edit()` swaps the text for a textarea. Ctrl+Enter or leaving the field saves with `PATCH … { body }` when the text is not empty and has changed. Escape gives up. Then `renderBook()` runs.

**`question` (question card).**
- Create: `newQuestion(front?)` opens `questionDialog()`, a modal with Front and Back. Both sides are required. It posts `{ page, kind: "question", body: front, data: { back } }`. "Slide → question" opens the same dialog with the front filled in as `What is <slide title>, and why does it matter?`.
- Joining review: this happens on the server. `sync_question_card()` in `lectures.py` runs after every create and patch. If the note is a question with both sides, it calls `services.upsert_card(db, "lecture_note", note_id, front, back, None)`; otherwise it removes the card. Deleting the note removes the card. The front end only shows the toast "Card added to your reviews."
- Draw: `div.note-card.question` with `div.q-front` and `div.q-back` (both through `mathText`). Click or Enter toggles the class `flipped`.
- Edit: double-click opens `editQuestion(n)`, the same dialog, then `PATCH … { body, data: { back } }`.

**`snip`.**
- Create: `armSnip(frame)` runs when the stage is drawn in snip mode. It adds `div.snip-layer` over the page. Pointer down, move and up draw `div.snip-rect`. Coordinates are fractions of the frame, clamped to 0..1. A rectangle smaller than 3% in either direction is dropped. Then `askText("Snip", …)` asks for a caption; Cancel drops the snip. The note is posted with `data: { x, y, w, h }`, each rounded to four decimals by `round()`. Mode returns to read and the tab to `"page"`.
- Draw: `snipView(lec, page, rect)`. A snip stores no picture. It draws the whole page again with `pageView` (width 900) inside `div.snip-window`, scaled to `100 / w` percent and shifted by `-x / w` and `-y / h`, so only the region shows. The window's aspect ratio is `(w × pageWidth) / (h × pageHeight)`.
- Clicking the card goes to its page. A snip has no edit.

**`sketch`.**
- Create: `newSketch()` posts `{ kind: "sketch", body: "", data: { ratio: 0.75 } }` and calls `startSketch(id)`.
- Draw: `sketchCard(n, del)`. The drawing area is `div.sketch-paper` with `aspect-ratio: 1 / <ratio>`. `sketchRatio()` accepts 0.3 to 3 and falls back to 0.75.
  - Not editing: a read-only `InkPad` (`owner: "note/<id>"`, `readonly: true`, `adaptToDark: isDark`) is created on the next animation frame and kept in `previews`. Clicking the card calls `startSketch`.
  - Editing (`editingSketch === n.id`): a writable `InkPad` with the same owner, a toolbar with "Done" placed before the paper, and a caption `<input>`. These are stored in `live`.
- Resize: dragging `div.sketch-grip` changes the ratio live and saves `{ data: { …, ratio } }` on release.
- Finish: `stopSketch()` calls `closeLive()`, which destroys the pad (this flushes its ink) and saves the caption with `PATCH … { body }` if it changed.
- Strokes are saved by the pad itself to `PUT /api/ink/note/<id>`, not through the note.

**`recall`.**
- Create: with recall mode on, `coverForRecall(frame)` puts `div.recall-cover` over a page that has no recall note yet. "Reveal" (or Ctrl+Enter) posts `{ page, kind: "recall", body }` if you wrote something, removes the cover and calls `ambience.moment()`. "Skip" removes the cover and saves nothing, so the page is covered again next time.
- Draw: `div.note-card.recall` with the text in a `<blockquote>`. No edit.

**`cornell` (the Cornell sheet).** One note per lecture, with `page === null`. `cornellSheet()` finds it or starts with empty fields. It draws three textareas (cues, notes, summary). Any input calls a debounced `persist` (700 ms). The first save creates the note with `POST`; later saves `PATCH` its `data`. A small "Saved" text shows for 1.2 seconds.

### The ink layer (`web/src/ink.ts`)

`InkPad` puts a `canvas.ink-canvas` in a host element and stores strokes as vectors.

- A stroke is `{ tool, color, size, points: [x, y, pressure][] }`. `x` and `y` are both divided by the pad's **width**, so ink keeps its place and shape when the pad is resized.
- `load()` reads `GET /api/ink/<owner>`. Strokes drawn while loading are kept on top of the saved ones. If loading fails, the pad refuses to save, so it never overwrites saved ink with a partial picture.
- Every change sets a 700 ms timer; `flush()` sends `PUT /api/ink/<owner>` with all strokes through `save()` (which retries). `destroy()` flushes first.
- `setOffset(x, y)` scrolls the pad's window over a taller page (HTML lectures and notebook pages).
- Pen pressure sets the line width. After a pen has touched the pad, finger touches are ignored (palm rejection).
- The eraser removes whole strokes near the pointer. Undo and redo keep up to 60 snapshots.
- `adaptToDark` draws dark ink light on dark paper. The desk uses it for sketches, not for ink over slides.

Owners used in this chapter: `lecture_page/<lecture id>:<page>`, `note/<note id>`, `journal/<yyyy-mm-dd>`. The server accepts only these three owner types.

`inkToolbar(pad, extra)` builds `div.ink-bar`: Pen, Marker, Eraser, six colours, three sizes, Undo, Redo, Clear, and any extra buttons. `inkKeys(pad, bar, e)` handles the pad's keys and returns `true` when it used the key.

### Modes, recall, focus

- `setMode(m)` sets `mode` and redraws the top bar and the stage. Snip is refused for HTML and notebooks.
- `toggleRecall()` flips `recallMode` and redraws. Refused for HTML and notebooks.
- `toggleFocus()` toggles the class `focus` on `.lecture-view` and refits the frame.

### The timer menu

The Timer button and the T key call `timerMenu()` from `web/src/timer.ts`. It shows a small menu under the button with "Focus 15 / 25 / 45 min" and a link to `#/timer`. Picking a length starts a focus run labelled `Study: <title>` and linked to this lecture (`link_type: "lecture"`).

### Export: `exportNotes()`

`GET /api/lectures/<id>/export` returns `{ markdown }`. The server builds it: notebook pages first, then the Cornell sheet, questions, snips, recalls, sketches (as a line with the caption) and typed notes, with math turned into Markdown math. The front end copies it to the clipboard. If the clipboard is not available, it shows the Markdown in a read-only textarea in a modal.

### Cleanup

The returned function closes the live sketch, removes the `message` listener, destroys the page pad and all previews, runs `cleanups` (flush `saveText`, disconnect the `ResizeObserver`, remove the key listener), and sets the scene back to idle.

---

## 7.3 `notes.ts`: All notes

```ts
export async function notesView(root: HTMLElement, id?: string): Promise<() => void>
```

`tableView` and `bigMap` are private functions in the same file.

### Module-level state and constants

| Name | Meaning |
|---|---|
| `lastQuery`, `lastTag` | The search text and the chosen tag. They are module-level, so they stay when you open another note or leave and come back |
| `TEMPLATES` | Four note skeletons: Lecture summary, Weekly review, Project, Decision |
| `KIND_ICON` | The icon before a link, by kind |
| `INLINE` | One regular expression for all inline marks |
| `PROP_LINE` | `key:: value` lines |
| `ANCHOR` | A trailing `#s<number>` in a link target (a sentence of a document) |
| `CALLOUT_ICON` | Icons for the five callout kinds |
| `SLASH` | The entries of the slash menu |

The read/write mode is **not** module-level. It is the local variable `mode` and is worked out again each time `notesView` runs.

Small helpers: `splitTarget(raw)` splits `Title#s12` into `{ title, sentence }`. `keyOf(title)` trims, collapses spaces and lower-cases. `isDay(s)` tests `yyyy-mm-dd`. `todayYmd()` gives today in local time. `niceDaily(day)` formats a day for display. `add(el, ...kids)` appends and skips `null`.

### Routing by id

| `id` | What opens |
|---|---|
| `"table"` | `tableView(root)` |
| `"map"` | `bigMap(root)` |
| `"today"` | `GET /api/pages/daily/<today>`; the server makes the daily note if it is not there |
| a date `yyyy-mm-dd` | `GET /api/pages/daily/<date>` |
| anything else | `GET /api/pages/<id>` |
| none | The first note of the list, but only when no search text and no tag are set. Otherwise no note is open and the welcome panel shows |

The list is loaded first with `GET /api/pages?q=<lastQuery>&tag=<lastTag>`. After a daily note is opened the list is loaded again, because the note may have just been made. Any error while opening shows the toast "That note is not here anymore." and leaves `cur` as `null`.

The starting mode is `"read"` when the note has text. It is `"write"` when the note is empty, or when it is a daily note whose body still contains the empty check box of the daily template (`"- [ ] \n"`).

### Layout

```
section.notes
  header (notesHead("notes"))
  nav.notes-list        side    renderList()
  div.note-main         main    renderMain() → renderBody()
  aside.note-around     around  renderAround()
```

### The list and search: `renderList()`

- Buttons: "+ New note" (`openNew()`) and "Today" (`#/notes/today`).
- Links to `#/notes/table` and `#/notes/map`.
- A search field. Typing is debounced 250 ms, then sets `lastQuery`, reloads the list and puts focus back in the new search field (the list is rebuilt, so the old field is gone).
- Tag buttons (`button.md-tag`) from `listing.tags`. Clicking one sets or clears `lastTag`.
- The notes as `a.notes-item`, with a star for pinned ones, the nice date for daily notes, and a snippet.
- A footer with the totals of notes and links.

Search and tag filtering happen on the server. The server returns at most 500 notes and 40 tags.

`openNew()` asks for a title and calls `POST /api/pages/open`. That route returns the note with this title and makes it if needed. So "New note" with an existing title opens the existing note.

### Saving

```ts
const put = (body: Record<string, unknown>): Promise<void>
const saveBody = debounce((text: string) => void put({ body: text }).then(() => void refreshList()), 600);
```

- `put()` chains every request on the promise `saving`, so patches reach the server in order. It sends `PATCH /api/pages/<id>`.
- When the answer arrives and the same note is still open, `cur` is replaced by the server's version, the status shows "Saved", and `renderAround()` runs. In read mode `renderBody()` runs too. In write mode the textarea is left alone.
- On failure the status shows "Not saved" and a toast shows the reason.
- `saveBody` runs 600 ms after the last keystroke, then reloads the list (the snippet and tags may have changed).
- `saveBody.flush()` is called when the mode changes, before a delete, and in the cleanup. `flushPending()` in `main.ts` also runs it on every route change and when the window closes.

The status element is `span.note-status`: "…" while there are unsaved keystrokes, then "Saving…", then "Saved".

### Read mode and write mode

`setMode(next)` flushes the body, sets `mode` and calls `renderMain()`. The two-button switch is `div.note-seg`. Ctrl+E switches too.

**Read mode.** `renderBody()` puts `renderMd(cur.body)` in `div.note-read`. A double-click on anything that is not a link, button or input switches to write mode.

**Write mode.** A plain `textarea.note-area` holding the raw text, with `div.note-suggest` above it. `fit()` grows the textarea to its content. Every input calls `changed()`, which copies the text to `cur.body`, calls `saveBody`, and refits.

Keys in the textarea, when no suggestion is open:

- **Enter** on a list line continues the list: the same indent and marker, the next number for a numbered list, and an unchecked box for a task. Enter on an empty list item removes the marker and ends the list.
- **Tab** inserts two spaces.

### The Markdown renderer: `renderMd(body)`

It walks the lines once and returns DOM nodes. Lines that match nothing gather in `para` and become one `<p>` with `<br>` between lines (`flush()`). The checks run in this order; the first match wins.

| Order | Line looks like | Output |
|---|---|---|
| 1 | ```` ``` ```` | A code block. Lines up to the next ```` ``` ```` go, as plain text, into `pre.md-code > code`. No inline marks are read inside. A fence that is never closed takes the rest of the note |
| 2 | `| a | b |` followed by a `| --- | --- |` line | A table: `div.md-table-wrap > table.md-table`. Following lines that start with `|` are rows. Each row is padded or cut to the number of header cells. Cells go through `inline()` |
| 3 | `key:: value` (`PROP_LINE`) | Properties. Consecutive property lines become one `dl.md-props` with `dt` (the key) and `dd` (the value through `inline()`) |
| 4 | `#` to `####` and a space | A heading `h2` to `h5` with class `md-h` and `data-line="<line index>"` (used by the outline) |
| 5 | `---` or `***` (three or more) | `<hr>` |
| 6 | `- [ ] text` or `- [x] text` | A task: `div.md-task` (plus `is-done`) with a real check box. See below |
| 7 | `- text`, `* text`, `1. text`, `1) text` | A list item: `div.md-li` with `span.md-bullet` ("•" or the number as written) |
| 8 | `>` | A quote. Consecutive `>` lines are joined. If the first line is `[!note]`, `[!tip]`, `[!warning]`, `[!question]` or `[!important]` it is a callout: `div.md-callout.kind-<kind>` with a title (the text after the tag, or the kind's name). Otherwise a `<blockquote>` |
| 9 | empty | Ends the paragraph |
| 10 | anything else | Added to the paragraph |

Lists are not nested elements. Tasks and list items are flat `div`s with left padding of 1.4em for every two spaces of indent.

A property key must start with a letter, be at most 31 characters of letters, digits, `_`, space or `-`, and be followed by `::` and a value.

**Check boxes and "→ Plan".** A task line may end with ` (in Plan)`. That suffix is cut from the shown text.

- Ticking the box calls `setLine(index, …)`, which rewrites that one line of `cur.body` (`[ ]` to `[x]` or back), redraws the body and saves with `put`.
- A task that is not done, has text and is not yet in Plan gets a `button.md-to-plan` ("→ Plan"). It posts to `/api/todos` with the text (link syntax reduced to its label, `*`, `` ` `` and `=` removed, at most 500 characters), `minutes: 25`, and `link_type: "page"`, `link_id: <this note>`. Then `setLine` appends ` (in Plan)` to the line.
- A task already in Plan shows the chip `span.tchip.quiet` "in Plan" instead.

`setLine` works by line number, so it relies on the drawn body being the same text as `cur.body`.

### Inline marks: `inline(text)`

`inline()` runs `INLINE` over the text with `matchAll`. Text between matches goes through `mathText()`, so `\( … \)` math is drawn by KaTeX and everything else is a text node. Each alternative of the expression has its own capture group:

| Group | Syntax | Output |
|---|---|---|
| 1, 2 | `[[Target]]` or `[[Target|label]]` | A link, see below |
| 3 | `` `code` `` | `<code>` |
| 4 | `**bold**` | `<strong>` |
| 5 | `==highlight==` | `<mark>` |
| 6 | `*italic*` | `<em>` |
| 7, 8 | `[text](url)` | A **button** `button.md-ext` showing the text and "↗". Clicking copies the address to the clipboard. The address is never opened or fetched |
| 9 | `#tag` | `button.md-tag`. Clicking sets `lastTag` and reloads the list |

A tag must start with a letter and may hold letters, digits, `_` and `-`, up to 40 characters. The `#` must not follow a letter, digit, `_`, `&`, `#` or `/`. So `C#`, `&#39;` and `page/#top` are not tags. The expression uses the `u` flag, so letters of any script count.

Marks do not nest: the inside of bold, code or a highlight is used as plain text.

**Links.** For `[[Target|label]]`:

1. `splitTarget()` takes a trailing `#s<n>` off the target.
2. The link is looked up in `cur.outgoing` by `keyOf(title)`. The server filled `outgoing` when it saved the note; each entry has `kind`, `id`, `title` and `key`.
3. The kind is `page`, `document`, `lecture`, `quest`, `term`, or `missing` when nothing has that title.
4. The output is `a.wikilink.kind-<kind>` with `href="#"`, the kind's icon and the label (or the title). A click calls `follow(target)`.

`follow(target)` goes to the address from `hrefFor()` when the link resolves. For a document with a sentence number it adds `?s=<n>`. For a missing link it calls `POST /api/pages/open` with the title, which makes the note, and opens it.

```ts
function hrefFor(kind: string, id: string, title = ""): string
```

| Kind | Address |
|---|---|
| `term` | `#/glossary?concept=<title, encoded>` |
| `document` | `#/read/<id>` |
| `lecture` | `#/lecture/<id>` |
| `quest` | `#/quest/<id>` |
| anything else | `#/notes/<id>` |

Because the link kinds come from `cur.outgoing`, a link typed a moment ago shows as "missing" until the save comes back and the body is drawn again.

### Suggestions while writing: links and the slash menu

`checkSuggest()` runs on every input and click in the textarea. It fills `picks` and shows `div.note-suggest` with one `button.chip` per pick.

**The slash menu.** `slashQuery()` matches a `/` at the start of a line (after optional spaces) followed by up to 16 letters, spaces or apostrophes. The typed letters filter `SLASH` by title.

| Title | Inserts | Caret |
|---|---|---|
| Heading | `## ` | end |
| Small heading | `### ` | end |
| To-do | `- [ ] ` | end |
| List | `- ` | end |
| Numbered list | `1. ` | end |
| Quote | `> ` | end |
| Callout | `> [!note] ` | end |
| Table | a header row, a `---` row and one empty row | 8 characters before the end, which is the start of the empty row |
| Code | an opening fence, an empty line, a closing fence | 5 characters before the end, which is the empty line |
| Divider | `---` and a new line | end |
| Link | `[[` | end; the title suggestions open at once |
| Property | `status:: ` | end |
| Today's date | today as `yyyy-mm-dd` (worked out when the menu opens) | end |

`choose(i)` replaces the `/…` text with the entry's `insert` and moves the caret back by `back` characters.

**Link suggestions.** `linkQuery()` finds an open `[[` before the caret. The first time, `GET /api/pages/titles` is fetched and kept in `titles` (it is cleared after a rename). It lists notes, then documents, lectures, goals and glossary terms. The picks are the titles containing the typed text, without the current note, at most 7. `choose(i)` inserts the title and `]]` (or steps over a `]]` that is already there).

Keys while suggestions show: Tab or Enter picks, Up and Down move, Escape closes. A pick uses `mousedown` with `preventDefault()` so the textarea keeps focus. The box hides 150 ms after the textarea loses focus.

### Templates

In write mode the bar has `select.note-template`. Choosing an entry of `TEMPLATES` appends its text to the note (or sets it, if the note is empty), then saves through `saveBody`.

### The bar, title, pin and delete: `renderMain()`

With no note open, `renderMain()` draws `div.note-welcome` with two buttons and three tips.

With a note open it draws `div.note-bar` (the read/write switch, the template select, the status, a pin button, since 5.2 a ✨ Tidy button, since 5.4 a 💬 note chat button, and a delete button), a kicker line for daily notes, the title input and the body.

- **Rename.** The title is `input.note-title`. On `change`, `rename()` waits for `saving`, then sends `PATCH /api/pages/<id>` `{ title }`. The server rewrites `[[old title]]` links in other notes to the new title and answers 409 if the title is taken. On an error the old title is put back and the reason is shown. Enter in the field blurs it.
- **Pin.** `put({ pinned: !page.pinned })`, then the bar and list are redrawn. Pinned notes sort first (on the server).
- **Tidy** (milestone 5.2). The ✨ (`button.note-tool`, "Tidy this note: spacing and lists, or a model's rewrite if you ask") opens `tidyNoteDialog(page.id, before, after)` from `web/src/views/tidy.ts` (chapter 6, section 6.2c). `before` flushes the body and waits for `saving`, so the dialog sees what was typed. Code's fix (spacing and list marks) and, with AI on, a model's rewrite are shown; **Apply** or **Use this** sends `PATCH /api/pages/<id> {body}` only while the note is still the text that was proposed, with Undo. `after` redraws the page with a synthetic `hashchange`. A model's rewrite has no label line (since 2026-11-26, on the owner's request) and keeps the note's own links, tags and properties; the model's own markup is plain text.
- **Note chat** (milestone 5.4). The 💬 (`button.note-tool`, "Ask a model: format this note, enhance it, or write something new", label "Ask a model about this note") opens `noteChatDialog(page.id, before, after)` from `web/src/views/notechat.ts`, with the same `before` and `after` as Tidy. With AI off (`aiIsOn()` from `explain.ts`) the dialog says to use ✨ Tidy (no model) and write the rest yourself. With AI on: the conversation (`div.chat-log`, `p.chat-turn.you` / `.model`), a textarea (2,000 characters; Enter sends, Shift+Enter is a new line), **Send**, **Start over** and **Close**. `run()` keeps the last 12 turns (never starting with the model's), calls `before()`, then `POST /api/notes/<id>/chat {messages}`; the reply joins the conversation, which `memo` keeps per note while the app is open (never saved), so reopening 💬 shows it. `drawAnswer` shows the proposal in `div.ai-text` with its label and **Why did it say this?** (`whyLink`): for a rewrite (`replace`) the text, "Words you did not write" (`mark`s), what was put back, "Much shorter than your note" with the missing words, and **Use this**; for new text (`add`) the text and **Add to the note**, which writes your note, a blank line and the new text. `none` shows only the reply. `write(from, to, done)` re-reads `GET /api/pages/<id>` and sends `PATCH /api/pages/<id> {body}` only while the body is still `from` (else a toast: "The note changed since the model read it."), calls `after()` and shows a toast with **Undo**, which writes `from` back only while the body is still `to`. `after()` redraws the page, which closes the dialog. No label line goes into the note. Text only: `h()` sets `textContent`.
- **Delete.** Flushes the body, waits for `saving`, calls `DELETE /api/pages/<id>` (a soft delete), shows a toast with **Undo** for 7 seconds, and goes to `#/notes`. Undo calls `POST /api/pages/<id>/restore` and opens the note again. The server answers 409 if another note now has that title.

### The "around" panel: `renderAround()`

Blocks appear in this order. Each is `div.around-block`; most are left out when empty.

1. **This day** (daily notes only). From `GET /api/day/<date>`: minutes focused, tasks done (the first six by name), routine steps, a link to that day's journal page, and a link to Plan when the day is today.
2. **Tasks from this note.** The `tasks` of `GET /api/related?kind=page&id=<id>`: open tasks linked to this note.
3. **Similar** (not for daily notes). From `GET /api/think/similar?kind=page&id=<id>`: notes and ideas that share words, with the shared words. A note that is not linked yet is marked "not linked yet". A link leads to the brainstorm sheet `#/think/page/<id>`.
4. **Outline.** Shown when the note has two or more headings. The headings are read from the raw text (code blocks are skipped). Clicking one calls `jump(line)`: in read mode it scrolls to the element with that `data-line`; in write mode it puts the caret at the start of that line.
5. **Links here.** `page.backlinks`: notes that link to this one, each with the line that holds the link.
6. **Mentioned, not linked.** `page.mentions`: notes that contain the title as plain text. "Link it" calls `POST /api/pages/<id>/link-mention` `{ from_id }`. The server turns the first mention in that note into a real link.
7. **Goes to.** `page.outgoing` as chips. A click calls `follow(o.key)` for a link that resolves, and `follow(o.title)` for a missing one. For a missing link the server sets `title` to the text as you typed it (`detail` in `pages.py`), so the note made from the chip keeps that casing, as it does from the link in the body. The chip's label is `o.title` in both cases, so a missing link shows the name its note will get.
8. **Map.** `drawMap()`, or a hint when the note has no linked neighbours.

The three extra requests (1 to 3) are sent once per note. Their results are kept in `extra`, tagged with the note's id. When one arrives it redraws the panel only if the same note is still open.

**The small map: `drawMap()`.** A 280 × 200 canvas (`canvas.note-map`). The current note is in the middle. Up to 12 neighbours from `cur.graph.nodes` sit on an ellipse (radius 100 by 66). Edges are lines; dots are filled with the theme's `--accent`; labels are cut at 18 characters. A click within 20 px of a neighbour opens it. Colours are read from the CSS variables once, when the canvas is drawn. Titles are drawn with `fillText`, so they are never treated as markup.

### Keys and cleanup

The view listens on `document` for Ctrl+E (switch mode) and N (new note, when not typing). The cleanup removes the listener and flushes `saveBody`.

### `tableView`: every note as a table (`#/notes/table`)

It loads all notes once with `GET /api/pages?q=&tag=`. Each note comes with `props`, the `key:: value` pairs the server read from its body.

- **Columns.** Note, Tags, then up to six property keys, then Changed. The property columns are the keys used by the most notes (ties in alphabetical order).
- **Filter.** A text field matches the title, tags and property values. Tag buttons filter by tag; this sets the module-level `lastTag` too, so the choice carries over to the list page.
- **Sort.** Clicking a header button (`button.th-btn`) sorts by that column; clicking again reverses it. Empty cells always go last. Values are compared with `localeCompare` and the `numeric` option, so "10" sorts after "9". The start is Changed, newest first. Headers carry `aria-sort`.
- Filtering and sorting are done in the browser; there are no more requests.

The page is `section.notes-wide`. It has no tab header, only links back to Notes and to the map.

### `bigMap`: the map of all notes (`#/notes/map`)

It loads `GET /api/pages/graph`: nodes `{ id, title, tags, daily }` and edges as pairs of ids. The server sends the 400 most recently changed notes and the true total.

**Layout: `layout()`.** The positions are worked out once per draw and are not animated.

1. Daily notes are left out unless the "Show daily notes too" box is ticked.
2. Start positions are a sunflower spiral: node `i` sits at angle `i × 2.399963` and radius `0.06 + 0.9 × sqrt((i + 0.5) / n)`. This is the same every time, so the map does not jump between visits.
3. A force step runs 180 times (90 times for more than 250 notes). With `k = 1.1 / sqrt(n)`:
   - every pair of notes pushes apart with force `k² / d²`;
   - every link pulls its two notes together with force `d / k`, half applied to each end;
   - every note is pulled a little to the middle (`0.9 × k × position`), which keeps unlinked notes in sight;
   - a note moves at most `heat` per step, and `heat` falls from 0.084 towards 0.004.
4. The result is centred and scaled into −1..1 with one scale for both directions, then multiplied by `min(1, 0.45 + n / 18)` so a few notes stay a small group.

The pair loop is quadratic in the number of notes. With the server's cap of 400 nodes this is at most about 80,000 pairs per step.

**Drawing: `paint()`.** The canvas is as wide as its box and between 300 and 700 px high (56% of the window height). A dot's radius is `4 + min(7, links × 1.2)`. Linked notes use `--accent`, unlinked ones `--muted`. All labels are drawn when there are 50 notes or fewer; otherwise only notes with three or more links, plus the hovered note and its neighbours. Labels are cut at 24 characters.

**Interaction.**
- Moving the mouse finds the nearest dot within 18 px (`hit()`). That note and its neighbours stay bright, the rest fade, its links turn to the accent colour, and the line under the map (`p.notes-map-info`) shows its title and link count.
- A click opens the note.
- Resizing the window repaints (debounced 150 ms). The layout is not worked out again.
- There is no pan and no zoom. The only "zoom" is the fit factor in step 4.

Below the canvas a `<details>` holds the same notes as a list of links, sorted by link count. The canvas has `role="img"` and a label that points to this list.

The cleanup removes the resize listener.

---

## 7.4 `journal.ts`: the journal

```ts
export async function journalView(root: HTMLElement, dayParam?: string): Promise<() => void>
```

### Loading a day

`dayParam` is used only if it is a valid `yyyy-mm-dd` that is not after today; otherwise the page shows today. One request, `GET /api/journal/<day>`, returns everything (`Page`):

| Field | Meaning |
|---|---|
| `entry` | The saved page, or `null` |
| `story` | What you did in the app that day: time, kind, text, and how it felt |
| `memories` | Entries from a week, a month and a year before |
| `recent` | The last 42 days: weather and whether you wrote |
| `letters_due`, `letters_sealed` | Letters ready to open, and the number still sealed |
| `prompts` | The prompt deck, by category |

The entry in memory is `{ id, day, weather, body, prompts }`. With no saved page it starts empty.

### Layout

`notesHead("journal")` and `section.journal` are added to the root side by side. The section holds the header and `div.journal-grid` with `div.journal-page` (left, `renderLeft()`) and `aside.journal-side` (right, `renderRight()`).

### Autosave and status

```ts
const persist = debounce(async () => { await api.put(`/api/journal/${day}`, { weather, body, prompts }); … }, 700);
```

Every change calls `persist()`. It sends the whole entry with `PUT /api/journal/<day>`. The status element `span.journal-status` shows "Saved" for 1.2 seconds, or "Not saved: <reason>". The cleanup calls `persist.flush()`.

### The header: `header()`

It is built once, when the page opens.

- Previous-day link, the title ("Today" or the weekday), next-day link (only for past days), and "Back to today".
- "Day's note": a link to `#/notes/<day>`, the daily note of the same day.
- A line with tasks done, minutes focused and routine steps, filled in later from `GET /api/day/<day>`.
- The **Privacy blur** check box.
- The **weather ribbon** `div.weather-ribbon`: 42 small links `a.wr-day`, one per day, ending at the shown day. A day has the class `w-<weather>` if a weather was picked, or `w-wrote` if there is text only. Each links to that day's page.

### The page (left): `renderLeft()`

It destroys the ink pad if there is one, clears the column and rebuilds, in order:

1. **Inner weather**, `weatherPicker()`. Five buttons from `WEATHER` (`sunny`, `bright`, `cloudy`, `rainy`, `stormy`). Clicking the chosen one again clears it. It saves and redraws the column.
2. **The page**, `textarea.journal-body`. Typing sets `entry.body` and saves.
3. **Prompt answers**, `ol.prompt-answers`, when there are any. Each has its question, a textarea for the answer, and a remove button.
4. **The prompt deck**, `promptDeck()`.
5. **Handwriting**, a `<details class="journal-hand">`. The first time it opens, it makes `new InkPad(host, { owner: "journal/<day>", adaptToDark: isDark })`, loads the ink and adds the toolbar.
6. The status text and, since 5.1, **Delete this page** (`button.journal-delete`, hidden until the page exists), on one row (`div.journal-foot`).

**Delete this page** (milestone 5.1). `deletePage()` asks first ("Delete this day's page?": its words, prompts and drawing leave the journal; it can be undone right after, and the day can still be written again). Then `settle()` sends the last keystrokes, so they cannot bring the page back after the delete, and the ink pad is destroyed, which saves a stroke on its way. `removeItem("journal", entry.id, "Deleted this day's page.", …)` (`web/src/trash.ts`): in `gone` the entry is emptied in memory, the day leaves the ribbon (`pg.recent`) and both are redrawn; in `back` (Undo) the page comes back from the restore's `entry` (words, weather, prompts) and its drawing from the server. The server reuses the same row when the day is written again, and a late Undo then changes nothing.

### Prompts

`promptDeck()` starts on a random category and question. `CATEGORY` maps the server's category ids (`gratitude`, `learning`, `win`, `worry`, `kindness`) to labels. "Another prompt" moves to a different category at random and picks a random question in it. "Answer it" pushes `{ q, a: "" }` to `entry.prompts`, saves, redraws and puts focus in the new answer field.

Prompts are stored with the entry as question and answer pairs, so an old answer keeps its question even if the deck changes later.

### The side (right): `renderRight()`

- **Your day so far** (or "That day in Readhold"): `pg.story` as `ol.story`, each line with its time and a small mark for how the session felt.
- **Free-write sprint** (today only): the "Start 5 minutes" button.
- **On this day**: `pg.memories` as links to those days, with the weather icon and the start of the text.
- **Letters to future you**: `lettersCard()`.

### Sprint mode: `sprint()`

It adds the class `sprint` to the section, puts `div.sprint-clock` at the top of the page column and puts focus in the body. An interval ticks every 500 ms and shows the time left with `fmtClock`. After five minutes, or on "Stop", the class and clock are removed; at the natural end a toast says so.

The hiding is done in CSS: `.journal.sprint` hides the side column, the prompt deck, the handwriting block, the weather picker and the prompt answers, and makes the body at least 60% of the window height. The text is saved as usual while the sprint runs. The cleanup clears the interval.

### Letters

- **Write** (`writeLetter()`): a modal with a textarea and a select for when to open it (7, 30, 90, 182 or 365 days; default 30). An empty letter is refused in the dialog. It posts `{ body, open_on }` to `POST /api/letters`, raises the sealed count and shows a toast with the date. The server refuses a date that is not in the future.
- **Open** (`openLetter(id)`): a due letter shows as `button.envelope`. Clicking it calls `POST /api/letters/<id>/open`, takes it off the list and shows the text in a modal, one `<p>` per line. The server refuses to open a letter before its day (403), so the text of a sealed letter never reaches the page.
- **Your letters** (since 5.1, `allLetters()`): a `details.letters-all` under the letters part of the side column. When it opens it reads `GET /api/letters` and lists the sealed letters ("Sealed until <day>" or "Ready to open", with when it was written; only dates, never the text) and the opened ones (a link that shows the letter again), each with ✕. A sealed letter asks first ("Delete this sealed letter?": you have not read it yet). `deleteLetter` calls `removeItem("letter", …)`; `gone` and `back` read the day again for the letter counts (`refreshLetters`) and redraw the column, and the list stays open. A letter you are reading has **Delete this letter** in its dialog (the focus is on **Close**, never on Delete).

### Privacy blur

The setting is `journal_blur`. The check box saves it with `saveSettings({ journal_blur })` and toggles the class `privacy` on `section.journal`. The blur itself is CSS: textareas in the page column that do not have focus, memory texts and the day story get `filter: blur(5px)`; pointing at the column removes it.

---

## 7.5 `think.ts`: Think

```ts
export async function thinkView(root: HTMLElement, sub?: string, id?: string): Promise<() => void>
```

With `sub` equal to `"page"` or `"idea"` and an `id`, it hands over to `sheetView`. Otherwise it draws the list page.

No model is used on the list page. Every reason shown is worked out by `readhold/think.py` from word counts, and the front end only displays it. The brainstorm sheet has one box that can ask a model, only with AI on and only on a button press ("Ideas from a model", below).

### The list page

`GET /api/think?day=<today>` returns `picks`, `suggestions` and `decided` (totals of accepted and rejected). The server answers 422 when `day` is not a date or is more than one day away from its own today (`day_ok` in `think.py`). `render()` clears and rebuilds `section.think`:

1. `notesHead("think", …)` with a "+ Capture" button that calls `openCapture()` (the same box as Ctrl+J).
2. An intro line.
3. **Today's ideas**: `pickCard` for each pick, in `div.think-grid`.
4. **For you to approve**: `suggestionCard` for each suggestion.
5. A footer with the totals.

`reload()` fetches again and calls `render()`.

**Pick card (`pickCard`).** `div.isle.think-card` (plus `is-opened` once opened). It shows whether it is a note or an idea, the signal in words (`SIGNAL`: `quest`, `question`, `orphan`, `resting`), the title, a snippet, and "Why today:" with the server's reason. Actions:

| Button | Effect |
|---|---|
| Think about it | A link to `#/think/<kind>/<item_id>`. On click it also sends `POST /api/think/picks/<id>` `{ status: "opened" }` and does not wait for it |
| Open the note / Open the inbox | A link to `#/notes/<id>` or `#/ideas` |
| Not today | `POST /api/think/picks/<id>` `{ status: "dismissed" }`, then `reload()` |

**Suggestion card (`suggestionCard`).** It shows the kind in words (`KIND_LABEL`: `link`, `mention`, `file_idea`, `tag`), the title, an optional quote, "Why:" with the reason, and "If you accept:" with the exact change. Then one link per note involved.

**Accept, reject, undo.**

- **Accept** calls `POST /api/think/suggestions/<id>/accept`. The server applies the change.
  - If it fails (for example the note changed and the suggestion no longer fits), the server's message is shown as a toast and the page reloads.
  - If it works, a toast "Done." stays for 8 seconds with an **Undo** button, and the page reloads.
- **Undo** calls `POST /api/think/suggestions/<id>/undo` and reloads. A failure shows the server's message. Undo is only offered in that toast; once the toast is gone the page has no undo button.
- **Not this** calls `POST /api/think/suggestions/<id>/reject` and reloads. The server does not offer a rejected suggestion again.

The list itself is made by `suggestions()` in `think.py` on each `GET /api/think`. A suggestion whose change no longer applies is marked `stale` there and leaves the list. If the same change applies again later, that row is set back to `new` and offered again. The daily limit on new suggestions (`PER_DAY`) is counted on the server's own day, not on the `day` the page sends; a suggestion that comes back counts towards it.

The front end never applies a suggestion itself. It never edits a note for a suggestion; all four kinds are applied by `think.py`.

### The brainstorm sheet: `sheetView(root, kind, id)`

`GET /api/think/brainstorm?kind=<kind>&id=<id>` returns:

| Field | Meaning |
|---|---|
| `item` | The note or idea: `title`, `text`, and for an idea its source document and sentence |
| `near` | Notes and ideas that share words with it |
| `reading` | Highlighted passages that share words with it |
| `sheet_title` | The title the sheet's note must have |
| `sheet` | The sheet's note `{ id, body }` if it exists |

**The questions.** `PROMPTS` holds six questions, each with a hint:

1. In one sentence, what is the idea?
2. Why does it matter to you?
3. What would make it wrong?
4. What does it connect to?
5. What is the smallest way to test or use it?
6. What question does it leave open?

The wording is load-bearing. Each question is saved as a `## ` heading in the note and matched by exact text when the sheet is opened again. If you change a question's wording, old answers to it stop being recognised (they are kept, as extra sections).

**Reading the saved sheet: `readExtra(body, withAnswers)`.** The body is split on lines that start with `## `. A section whose heading is one of the six questions fills `answers` (only when `withAnswers`). Any other section, one the reader added by hand or one of the model's ideas (since 2026-11-26 each idea is its own `## <label>` section), is kept in `extra` and written back unchanged at the end. It runs once on open (with the answers) and again after ideas go in or Undo runs (without them, so what the reader typed meanwhile is not replaced).

**Building the body: `body()`.**

- First line: `About [[<title>]].` for a note whose title can be linked (no `[`, `]`, `|`, `#` or new line, at most 190 characters). Otherwise a quote line with the first 600 characters of the item's text.
- Then one `## <question>` section per answered question, in the order of `PROMPTS`.
- Then the `extra` sections.

**Saving.** `save` is debounced 600 ms and chained on `saving`. While ideas from a model are being kept (`holding`), a save that falls due does not run; it sets `pending` and the typing goes on. A save in between would write the sheet without the ideas the server is adding:

- If the sheet's note exists: `PATCH /api/pages/<sheetId>` `{ body }`.
- If not: `POST /api/pages` `{ title: sheet_title, body }`. If that fails because a note with the title appeared meanwhile, it calls `POST /api/pages/open` to get that note and patches it.
- After the first save the link "Open the sheet as a note" appears. The status reads "Saved as a note".

The cleanup calls `save.flush()`.

**Ideas from a model.** The side column ends with an island "Ideas from a model" that holds `aiIdeasBox({kind, id}, hooks)` from `aibrainstorm.ts` (chapter 5, section 5.6). It is part of the hidden neighbours, so it shows only once the reader has written (attempt before reveal). With AI off it is one line. With AI on it has a topic box and **Ideas from the model**, which posts `POST /api/brainstorm`. Since 2026-11-26 there is no Keep button: as soon as the ideas come back, the box posts every checked one to `POST /api/brainstorm/{id}/keep`, which writes them into this sheet's note on the server, each as its own section, and **Undo** (`POST /api/brainstorm/{id}/undo`) takes them out again while the sheet is as they left it. The hooks keep the two writers apart, around both:

| Hook | What it does |
|---|---|
| `before` | `save.flush()`, waits for `saving` (what the reader typed is on the server), then sets `holding` |
| `after` | Runs after every keep and every Undo, also a failed one. `GET /api/think/brainstorm` again; when the sheet exists, `extra = readExtra(sheet.body, false)` (the ideas now in the sheet are in `extra`), `sheetId` is set and "Open the sheet as a note" shows. Then, in `finally`, `holding` is cleared and, when a save was held (`pending`), one `save()` runs, carrying what was typed meanwhile together with the ideas |

**Hidden neighbours.** The side column `aside.think-around` starts hidden when nothing is written yet and there is something to show. In that state it shows only the counts and a "Show them now" button. It is revealed when:

- the answer to the **first** question reaches 12 characters, or
- "Show them now" is pressed, or
- the sheet already had an answer, or there are no neighbours at all.

This is the "attempt before reveal" principle. Once revealed it lists `near` (links to the note or to the idea's own sheet, with the shared words), `reading` (links to `#/read/<doc>?s=<sentence>`, the text through `mathText`) and the "Ideas from a model" box (below).

The placeholder of the fourth question names the first neighbour ("how does it connect to …") when there is one.

**"Smallest test → task".** The button takes the first line of the answer to question five. With no answer it shows a hint and stops. Otherwise it flushes the save, waits for it, and posts to `/api/todos` with the text (at most 500 characters), `minutes: 10`, `due: <today>`, and a link to the sheet's note when it exists. A toast offers "Open Plan".

---

## 7.6 `misc.ts`: the small pages

Five exported views. None returns a cleanup.

### `glossaryView(root, params)` and the concept page

With `?concept=<term>` it calls `conceptView`. Otherwise it loads `GET /api/terms` and draws `section.glossary-view`: `libraryHead("glossary")`, a filter field and `dl.glossary.big`.

Each term is `div.term-card`: the term as a link to its concept page, the document it came from, the definition (or "guess: …" in italics when there is no definition yet), up to 160 characters of the source sentence, and two buttons:

- **Edit**: `askText` (multi-line), then `PATCH /api/terms/<id>` `{ definition }`.
- **Delete**: `confirmBox`, then `DELETE /api/terms/<id>`. The dialog says the review card goes too.

The filter matches the term or the definition and works in the browser.

`conceptView(root, term)` loads `GET /api/concepts?term=<term>` and shows, for that term: the glossary definitions, your highlights that contain it, your notes on it, and the sentences where it appears. Each is a link to `#/read/<doc>?s=<sentence>` with the text through `mathText`. At the end is `connectedCard("term", "", term)`; for a term the card asks the server by title, not by id.

### `ideasView(root)`

`section.ideas-view` with `notesHead("ideas")`, a capture textarea with a Save button, and `ul.ideas`.

- **Capture**: Save or Ctrl+Enter posts `{ text }` to `POST /api/ideas` and redraws.
- The list is loaded with `GET /api/ideas` on every redraw.

Each idea shows its text, its date, a link to its source sentence if it came from a document, and four actions:

| Action | Effect |
|---|---|
| Think | A link to `#/think/idea/<id>` |
| → Task | `POST /api/todos` with the text (spaces collapsed, 500 characters), `minutes: 25`, linked to the source document if there is one. It lands under "Anytime" in Plan |
| → Note | Asks for a title (default: the first 60 characters), then `POST /api/pages` with the idea's text. If the idea came from a document whose title can be linked, the body ends with `— [[Title#s<sentence>|Title]]` |
| Archive | `DELETE /api/ideas/<id>`, then redraw |

### `statsView(root)`: Stamina and the weekly review

Two requests: `GET /api/stats` and `GET /api/week/plan`. The second may fail without breaking the page; its card is left out.

The page is `section.stats`:

1. **Tiles** (`div.tiles`, each from `tile(label, value, sub)`): Streak; Focused this week (the last 7 days, and how many days counted); Longest unbroken run; Key sentences this week (and cards reviewed).
2. **Focused minutes, last 4 weeks**: a bar chart built from `div.col` elements, one per day of `s.days`. The bar height is the day's minutes against the largest day (at least 10 minutes). Days that count for the streak get the class `counts`. The tooltip has the day's full numbers.
3. **Weekly review**: a `div.week-grid` of cards (`div.isle.week-card`):

| Card | Data |
|---|---|
| Goals and steps done | `week.quests_done`, `week.steps_done` |
| Your daily log | `week.logs`, drawn by `logList()` from `views/logs.ts` |
| Energy: what drains you, what lifts you (wide) | `week.feel.drains`, `week.feel.lifts` |
| Tasks and routines | The answer of `/api/week/plan`: tasks done, open tasks, areas, routines. Left out if that request failed |
| Habits and practice | `week.habits`, `week.practice` |
| Finished reading | `week.finished`, links to `#/summary/<id>` |
| What you can now explain | `week.explained` |
| Still-open confusions | `week.open_confusions`, links into the reader |

The page only reads. It changes nothing.

### `settingsView(root, params?)`

Settings live in `state.settings` (`web/src/state.ts`). Every control calls the local `set(patch)`:

```ts
const set = async (patch) => { await saveSettings(patch); applyTheme(); applyComfort(comfortFor("")); };
```

`saveSettings` merges the patch into `state.settings` at once and sends `PUT /api/settings`. So a change is applied and saved the moment it is made; there is no Save button.

Three small builders make the controls: `select(value, options, onchange)`, `num(value, min, max, step, onchange)` and `check(value, label, onchange)`. `field(label, control)` wraps one in a labelled row. `num` passes the typed number on as it is; `min` and `max` are only attributes of the input.

At the top, `div.set-jump` has one chip per group; a chip scrolls to the group's element by id. The groups, in order:

**Theme** (`#set-theme`)

| Control | Setting key | Values |
|---|---|---|
| Theme cards (one `button.theme-card` per entry of `state.themes`) | `theme` | the theme's id; the page is redrawn after a pick |
| Light / dark | `dark` | `auto`, `light`, `dark` |
| Panels | `glass` | `solid`, `balanced`, `clear` |
| Motion | `intensity` | `off`, `still`, `gentle`, `lively` |
| Ambient sound | `sound` | on / off |
| Sound volume (a range input) | `sound_volume` | 0 to 1 in steps of 0.05 |

**Reading comfort (default)** (`#set-comfort`)

| Control | Setting key | Range |
|---|---|---|
| Font | `font` | the keys of `FONTS` in `state.ts` |
| Size (px) | `font_size` | 14 to 32 |
| Line length (characters) | `line_width` | 40 to 100 |
| Line spacing | `line_height` | 1.3 to 2.4 |
| "Clear them" (shown only when overrides exist) | `comfort_by_type` | set to `{}` |

**Pacer** (`#set-pacer`)

| Control | Setting key | Range or values |
|---|---|---|
| Current pace (wpm) | `wpm` | 80 to 900 |
| Comfort speed | `comfort_wpm` | 80 to 900 |
| Default pacer | `pacer_mode` | `sentence`, `word`, `focus` |
| Default energy | `energy` | `low`, `medium`, `high` |
| Speed ramp | `speed_ramp` | on / off |
| Prediction prompt | `prediction_prompts` | on / off |
| Skip background sections | `skip_background` | on / off |
| Clean view | `clean_view` | on / off |

**Simple mode** (`#set-simple`)

| Control | Setting key | Notes |
|---|---|---|
| Simple mode | `simple_mode` | After saving it fires a `hashchange` event so the menu is redrawn |

**Voice** (`#set-voice`)

| Control | Setting key | Notes |
|---|---|---|
| Read-aloud voice | `tts_voice` | Filled by `fillVoices()` from `tts.voices()`, which returns offline voices only. Empty means automatic |
| Rate | `tts_rate` | 0.5 to 2 |
| Test voice | none | Speaks one sentence with the current voice and rate |

**Review** (`#set-review`)

| Control | Setting key | Range |
|---|---|---|
| Daily review cap (cards) | `review_cap` | 5 to 200 |

**AI** (`#set-ai`, built by `aiSettingsBlock()` in `views/ai-settings.ts`)

The block draws itself after `GET /api/ai/status` and redraws after every change. Its controls do not use `set()`: they call the block's own `change(patch)`, which sends `PUT /api/settings` and takes the answer as the new `state.settings`. The server checks every `ai_…` value; a refused one shows the server's sentence as a toast and the old value comes back. Changing the mode re-runs the route (a `hashchange` event), so the chip in the menu shows the new mode.

| Control | Setting key or request | Range |
|---|---|---|
| AI | `ai_mode` | Off, Local model, Cloud model |
| Stop a call after (seconds) | `ai_timeout_s` | 5 to 600 |
| Server type, Endpoint, Model, Small model | `ai_local_api`, `ai_local_endpoint`, `ai_local_model`, `ai_local_small_model` | |
| Provider, Model, Small model | `ai_cloud_provider`, `ai_cloud_model`, `ai_cloud_small_model` | Anthropic or OpenAI; the placeholders name the default models |
| Daily token budget (two fields) | `ai_budget_local`, `ai_budget_cloud` | 0 = no limit |
| API key field, Save key | `PUT /api/ai/key` | A password field. It is emptied after saving; the key never comes back from the server, only `key_set` |
| Clear key (shown when a key is saved) | `DELETE /api/ai/key?provider=` | After a confirm box |
| Test connection, Cancel | `POST /api/ai/test` with a `call_id` made in the page, `POST /api/ai/cancel` | The result line says "Connected: <model> answered in N s." or the server's sentence. It is kept in `lastTest` across the redraw that follows |
| Show what will be sent before each cloud request (a checkbox, milestone 4.4) | `ai_preview` | On or off. With it on, a call that leaves this computer stops with 428 and `previewDialog` (`web/src/aipreview.ts`, chapter 4) shows its text first |
| Send to the cloud model only documents and notes I tagged #cloud (a checkbox, 4.4) | `ai_cloud_only_tagged` | On or off |
| Keep the AI log (4.4) | `ai_log_days` | 30 days, 7 days, 1 day (the select's value is turned into a number) |
| Clear AI history | `DELETE /api/ai/log` | After a confirm box that says what is deleted: "The AI log is emptied, every recap, explanation, digest, answer, brainstorm and suggestion Readhold kept is deleted, the AI export files in the exports folder are deleted, and every AI call that is running stops. What you kept from a model is yours and stays: review cards, notes on a passage, Study notes and the ideas in your brainstorm sheets (delete them like any note or card). This cannot be undone (your daily backups still hold the data for up to 14 days, and full exports you made keep what they held)." Then a toast "AI history cleared." and a redraw. The route stops running library questions and brainstorms and every other AI call that is running (`port.cancel_all()`), empties the log, stops a digest that is running (`digest.stop()`), deletes any old `readhold-ai-export-*.json` files and every row of `ai_results` (chapter 3, section 7b). The **Export AI data** row that stood above it (4.4, `POST /api/ai/export`) was removed on 2026-11-26: **Export everything** under *Your data* holds the kept AI results, and the AI log is in no export |

The block also shows: `status.problem` (no model, no key) and `status.warning` (an endpoint that is not on this computer) in a warning box, a fixed paragraph that says what cloud mode sends off this computer, a line on private items under the two checkboxes ("Private items: a document or note tagged #private is never sent to a cloud model, and neither are your own notes that copy its sentences or name it (a local model still reads them). Tag a document in Organize, or write #private in a note. Secrets in the text … are replaced by [redacted] before any cloud call."), today's token use, and under the heading **AI history** the number of lines in the AI log with what one line holds. The two checkboxes and the line sit under **Cloud model**, but `ai_preview` and the private rules also apply to a "local" endpoint on another computer (chapter 3). The page builds no prompt and calls no model.

`aiChip()` in the same file is the chip in the menu (chapter 4).

**Your data** (`#set-data`)

| Button | Request | Result |
|---|---|---|
| Export everything (JSON + Markdown) | `POST /api/export/all` | A toast with the path of the export. Since 2026-11-26 the one export of AI data too: it holds the kept AI results (`ai_results`), never the AI log |
| Back up now | `POST /api/backup` | A toast with the path of the backup |

Settings that exist but are **not** on this page: `journal_blur` (the Journal header), `notebook_width` and `note_scale` (the lecture desk), `timer_sound` and `timer_rhythm` (the Timer page, `views/timer.ts`).

### `structureView(root, docId)`: Fix structure

Reached from the reader for a document whose import came out messy. It loads `GET /api/documents/<docId>?touch=false` (so opening this page does not count as reading) and draws `section.structure`: a back link to the reader, the title, the import warning if there is one, and one `div.struct-sec` per section.

| Control | Request |
|---|---|
| Section title (text input, on `change`) | `PATCH /api/sections/<id>` `{ title }`, toast "Renamed" |
| Section type (select over `KIND_LABELS`) | `PATCH /api/sections/<id>` `{ kind }`, toast "Type changed" |
| "skippable" check box | `PATCH /api/sections/<id>` `{ background }` |
| "hidden in clean view" check box | `PATCH /api/sections/<id>` `{ hidden }` |
| "Merge into previous" (not on the first section) | `POST /api/sections/<id>/merge-up`, then the page is rebuilt |
| "Start section here" (on every paragraph but the first of a section) | Asks for a title, then `POST /api/paragraphs/<id>/split` `{ title }`, then the page is rebuilt |

Under each section is `ol.struct-pars`: every paragraph with its kind and its first 160 characters. `reload()` clears the root and runs the view again.

---

## 7.7 API endpoints called by these files

Calls made by shared helpers are listed with the helper.

### Lectures

| Method and path | Called from |
|---|---|
| `GET /api/lectures` | `lectures.ts` `refresh` |
| `POST /api/lectures/import` | `lectures.ts` `importFiles` |
| `POST /api/lectures/notebook` | `lectures.ts` `startNotebook` |
| `PATCH /api/lectures/<id>` (title) | `lectures.ts` Rename button |
| `DELETE /api/lectures/<id>` | `lectures.ts` Remove button |
| `POST /api/lectures/<id>/restore` | `lectures.ts` Undo in the toast |
| `GET /api/lectures/<id>` | `lecture.ts` `lectureView` |
| `GET /api/lectures/<id>/notes` | `lecture.ts` `lectureView` |
| `PATCH /api/lectures/<id>` (position) | `lecture.ts` `savePos` |
| `PATCH /api/lectures/<id>` (page_tint) | `lecture.ts` `renderTop` |
| `PATCH /api/lectures/<id>/pages/<ord>` (text) | `lecture.ts` `saveText` |
| `PATCH /api/lectures/<id>/pages/<ord>` (paper) | `lecture.ts` `renderTop` |
| `POST /api/lectures/<id>/pages` | `lecture.ts` `addPage` |
| `GET /api/lectures/<id>/pages/<ord>/image?w=` | `lecture.ts` `pageView` (as an image source) |
| `GET /api/lectures/<id>/assets/<name>` | `lecture.ts` `slideEl` (as an image source) |
| `GET /api/lectures/<id>/content.html` | `lecture.ts` `renderHtmlStage` (as the iframe source) |
| `POST /api/lectures/<id>/notes` | `lecture.ts` `composer` (`add`), `newQuestion`, `armSnip`, `newSketch`, `coverForRecall`, `cornellSheet` |
| `PATCH /api/lecture-notes/<nid>` | `lecture.ts` `noteCard` (colour, text), `editQuestion`, `sketchCard` (ratio), `closeLive` (caption), `cornellSheet` |
| `DELETE /api/lecture-notes/<nid>` | `lecture.ts` `noteCard` |
| `GET /api/lectures/<id>/export` | `lecture.ts` `exportNotes` |
| `GET /api/ink/<owner>` | `ink.ts` `InkPad.load` |
| `PUT /api/ink/<owner>` | `ink.ts` `InkPad.flush` |

### Notes, Think, journal

| Method and path | Called from |
|---|---|
| `GET /api/pages?q=&tag=` | `notes.ts` `notesView`, `refreshList`, `tableView` |
| `GET /api/pages/<id>` | `notes.ts` `notesView` |
| `GET /api/pages/daily/<day>` | `notes.ts` `notesView` |
| `POST /api/pages/open` | `notes.ts` `openNew`, `follow`; `think.ts` `sheetView` (`save`, fallback); `related.ts` `connectedCard` (fallback) |
| `PATCH /api/pages/<id>` | `notes.ts` `put`, `rename`; `think.ts` `sheetView` (`save`) |
| `DELETE /api/pages/<id>` | `notes.ts` `renderMain` |
| `POST /api/pages/<id>/restore` | `notes.ts` `renderMain` (Undo) |
| `POST /api/pages/<id>/link-mention` | `notes.ts` `renderAround` |
| `GET /api/pages/titles` | `notes.ts` `checkSuggest` |
| `GET /api/pages/graph` | `notes.ts` `bigMap` |
| `POST /api/pages` | `think.ts` `sheetView` (`save`); `misc.ts` `ideasView` (→ Note); `related.ts` `connectedCard` |
| `GET /api/day/<day>` | `notes.ts` `renderAround`; `journal.ts` `header` |
| `GET /api/related?kind=&id=` or `&title=` | `notes.ts` `renderAround`; `related.ts` `connectedCard` |
| `GET /api/think/similar?kind=page&id=` | `notes.ts` `renderAround` |
| `GET /api/think?day=` | `think.ts` `thinkView`, `reload` |
| `POST /api/think/picks/<id>` | `think.ts` `pickCard` |
| `POST /api/think/suggestions/<id>/accept` | `think.ts` `suggestionCard` |
| `POST /api/think/suggestions/<id>/reject` | `think.ts` `suggestionCard` |
| `POST /api/think/suggestions/<id>/undo` | `think.ts` `suggestionCard` (Undo in the toast) |
| `GET /api/think/brainstorm?kind=&id=` | `think.ts` `sheetView` (on open, and in the `after` hook of a keep or an Undo) |
| `POST /api/brainstorm`, `POST /api/brainstorm/cancel`, `POST /api/brainstorm/{id}/keep`, `POST /api/brainstorm/{id}/undo` | `aibrainstorm.ts` `aiIdeasBox`, in `sheetView` (and in the reader's Brainstorm dialog, chapter 5) |
| `GET /api/journal/<day>` | `journal.ts` `journalView` |
| `PUT /api/journal/<day>` | `journal.ts` `persist` |
| `POST /api/letters` | `journal.ts` `writeLetter` |
| `POST /api/letters/<id>/open` | `journal.ts` `openLetter` |
| `GET /api/letters` | `journal.ts` `allLetters` (since 5.1) |
| `DELETE /api/items/journal/<id>`, `DELETE /api/items/letter/<id>` and their `/restore` | `journal.ts` `deletePage`, `deleteLetter`, through `removeItem` (`web/src/trash.ts`; milestone 5.1) |
| `GET /api/tidy/note/<id>`, `POST /api/tidy/suggest` (`kind: "note"`) | `tidy.ts` `tidyNoteDialog`, opened by the ✨ in `notes.ts` (milestone 5.2) |
| `POST /api/notes/<id>/chat`, and `GET` / `PATCH /api/pages/<id>` for Use, Add and Undo | `notechat.ts` `noteChatDialog`, opened by the 💬 in `notes.ts` (milestone 5.4) |
| `GET /api/notes/counts` | `libtabs.ts` `notesHead` |
| `GET /api/library/counts` | `libtabs.ts` `libraryHead` |

### Tasks, glossary, ideas, stats, settings, structure

| Method and path | Called from |
|---|---|
| `POST /api/todos` | `notes.ts` `renderMd` (→ Plan); `think.ts` `sheetView` (Smallest test → task); `misc.ts` `ideasView` (→ Task); `related.ts` `connectedCard` |
| `GET /api/terms` | `misc.ts` `glossaryView` |
| `PATCH /api/terms/<id>` | `misc.ts` `glossaryView` |
| `DELETE /api/terms/<id>` | `misc.ts` `glossaryView` |
| `GET /api/concepts?term=` | `misc.ts` `conceptView` |
| `GET /api/ideas` | `misc.ts` `ideasView` |
| `POST /api/ideas` | `misc.ts` `ideasView` |
| `DELETE /api/ideas/<id>` | `misc.ts` `ideasView` |
| `GET /api/stats` | `misc.ts` `statsView` |
| `GET /api/week/plan` | `misc.ts` `statsView` |
| `PUT /api/settings` | `state.ts` `saveSettings`, called by `misc.ts` `settingsView`, `journal.ts` `header`, `lecture.ts` (`bookGrip`, `noteScale`) |
| `GET /api/ai/status`, `PUT /api/ai/key`, `DELETE /api/ai/key`, `POST /api/ai/test`, `POST /api/ai/cancel`, `DELETE /api/ai/log` (`POST /api/ai/export` was removed on 2026-11-26) | `ai-settings.ts` `aiSettingsBlock` |
| `POST /api/export/all` | `misc.ts` `settingsView` |
| `POST /api/backup` | `misc.ts` `settingsView` |
| `GET /api/documents/<id>?touch=false` | `misc.ts` `structureView` |
| `PATCH /api/sections/<id>` | `misc.ts` `structureView` |
| `POST /api/sections/<id>/merge-up` | `misc.ts` `structureView` |
| `POST /api/paragraphs/<id>/split` | `misc.ts` `structureView` |

---

## 7.8 Keyboard shortcuts

App-wide keys (Ctrl+K search, Ctrl+J capture) are set in `main.ts` and other modules and are not listed here.

### Lecture desk (`onKey` in `lectureView`)

These work when you are not typing in a field and no modal is open, and no Ctrl, Cmd or Alt is held.

| Key | Action |
|---|---|
| Right, Page Down, `j` | Next page |
| Left, Page Up, `k` | Previous page |
| Home / End | First / last page |
| `P` | Pen on or off |
| `S` | Snip on or off (PDF and PowerPoint only) |
| `R` | Recall mode on or off (PDF and PowerPoint only) |
| `F` | Focus: hide the side panels |
| `N` | New page (notebooks only) |
| `T` | Open the timer menu |
| Escape | Leave pen or snip mode; or finish the sketch being drawn |

With the pen on, or while a sketch is being drawn (`inkKeys` in `ink.ts`):

| Key | Action |
|---|---|
| `B` | Pen |
| `M` | Marker (highlighter) |
| `E` | Eraser |
| Ctrl+Z | Undo |
| Ctrl+Y, Ctrl+Shift+Z | Redo |

Because the ink keys are tried first, `E`, `B` and `M` belong to the pen while it is on.

In fields on the desk:

| Where | Key | Action |
|---|---|---|
| Composer textarea | Ctrl+Enter | Add the sticky note |
| Sticky note being edited | Ctrl+Enter / Escape | Save / give up |
| Recall cover | Ctrl+Enter | Reveal |
| Question card | Enter | Flip (double-click edits) |
| Sticky note card | Enter | Edit |

### Notes

| Where | Key | Action |
|---|---|---|
| Anywhere on the page, a note open, no modal | Ctrl+E | Switch between Read and Write |
| Not typing | `N` | New note |
| Title field | Enter | Leave the field (which renames) |
| Textarea, suggestions open | Tab or Enter | Take the highlighted suggestion |
| Textarea, suggestions open | Up / Down | Move in the suggestions |
| Textarea, suggestions open | Escape | Close the suggestions |
| Textarea, on a list line | Enter | Continue the list, or end it on an empty item |
| Textarea | Tab | Insert two spaces |
| Textarea | `/` at the start of a line | Open the slash menu |
| Textarea | `[[` | Open the link suggestions |

### Other pages

| Page | Key | Action |
|---|---|---|
| Ideas | Ctrl+Enter in the capture field | Save the idea |
| Shelf | Enter on a focused tile | Start a notebook / open the file picker |
| Any `askText` dialog | Enter (Ctrl+Enter when multi-line) | OK |
| Any modal | Escape | Close |

The journal, Think, Stamina, Settings and Fix structure define no keys of their own.

---

## 7.9 Rules and gotchas

### Untrusted text

- Note bodies, lecture notes, slide text, speaker notes, journal text, letters, idea text, term definitions and document sentences are all untrusted. They reach the DOM only as text nodes (through `h()` or `textContent`), as `value` of a form field, or as `fillText` on a canvas.
- `renderMd` and `inline` in `notes.ts` are the largest example. They build elements by tag name and put matched text in as children. Adding a feature there must keep that shape. Never build a string of HTML.
- Math goes through `mathText()` (`web/src/math.ts`). KaTeX builds the nodes itself with `trust` off; a formula that fails is shown as plain text.
- Web links in a note are buttons that copy the address. Do not turn them into `<a href>`: the rule is that a note never opens or fetches a web address.
- `[[links]]` use `href="#"` and a click handler. The real address comes from `hrefFor()`, which only makes in-app `#/…` addresses from ids the server returned.
- Slide colours, fills and sizes from PowerPoint JSON are set as `style` properties, not as a style string. The image name is passed through `encodeURIComponent` and checked again by the server.

### The sandbox for HTML lectures

- The iframe has `sandbox="allow-scripts"` and no `allow-same-origin`. Do not add it: with it the page could read the app's cookie and call the API.
- The server sends `lectures.SANDBOX_CSP` for `…/content.html` (set in the `guard` in `server.py`), so the page is an opaque origin with no network even when opened directly.
- The only channel is `postMessage`. Incoming messages are checked for their source window and for finite, non-negative numbers. Keep any new message as narrow as these two. The outgoing message uses the target `"*"` because a sandboxed page has no origin to name; it carries only two numbers.

### Autosave

- Text fields save through `debounce()` from `util.ts`. Every debounced function registers itself in a module-level set while it has a pending call, and `flushPending()` runs them all. `main.ts` calls `flushPending()` at the start of every route change and on `pagehide` and `beforeunload`.
- Some views also flush by hand at the right moment: `saveText.flush()` and `pad.flush()` in `go()` before the page changes, `saveBody.flush()` in `setMode()` and before a delete, `save.flush()` before "Smallest test → task".
- `savePos` and the Cornell sheet's `persist` in `lecture.ts` have no explicit flush in the cleanup. They rely on `flushPending()`.
- Three kinds of write call are in use. `save()` from `api.ts` retries up to three more times and is used for fire-and-forget writes (ink, position, colour, sketch ratio). `api.patch` / `api.put` do not retry; `notes.ts` and `journal.ts` use them and show "Not saved" on failure. Choose `save()` when nothing on screen waits for the answer.
- `InkPad` has its own 700 ms timer and is not in the `flushPending()` set. Its ink is written by `destroy()`, so every view that makes a pad must destroy it in its cleanup. All three do.

### Things that are easy to break

- **`lecture.ts` redraws regions by hand.** After changing `notes`, call `renderBook()` and usually `renderThumbs()` (the note counts). After changing `page` or `mode`, go through `go()` or `setMode()`.
- **`renderBook()` closes the live sketch.** Any redraw of the notebook destroys and rebuilds the sketch pad. The ink is flushed first and `editingSketch` stays set, so the sketch reopens in drawing state, but undo history is lost.
- **The PowerPoint text size uses `cqw`.** It only works while the slide sheet is a size container in the CSS.
- **Snips store a rectangle, not a picture.** If a page's layout or size changes, old snips show a different region.
- **The brainstorm questions are headings in a saved note.** Changing the wording in `PROMPTS` orphans old answers. Also, on every save `body()` writes the first line again, so text typed by hand above the first `## ` heading of a sheet note is lost the next time the sheet is saved from Think. An answer that contains a line starting with `## ` is split into a separate section when the sheet is next opened.
- **Two writers share a brainstorm sheet.** The sheet page writes the whole body from `body()`, and the ideas from a model are appended to the same note on the server (and taken out again by Undo). The page holds its saves while a keep or an Undo runs (`holding`, `pending`) and reads the sheet back in the `after` hook. A new way to write into a sheet from the server needs the same hooks, or the next save from the page drops what the server wrote. Every save also reads the sheet back first and takes its other sections from the server (`readExtra`), so ideas kept from another place (the sheet open in a second window) are not dropped; the six answers are always this page's.
- **`setLine` in `notes.ts` edits by line number.** It assumes the drawn task list matches `cur.body`.
- **Link kinds come from the last save.** `inline()` reads `cur.outgoing`, which the server fills. Do not try to resolve links in the browser.
- **`lastQuery` and `lastTag` outlive the page.** With either set, `#/notes` opens no note and shows the welcome panel beside the filtered list.
- **The journal header is built once.** Picking a weather does not recolour today's square in the ribbon until the page is opened again.
- **`renderLeft()` in the journal rebuilds the whole column.** Picking a weather, answering a prompt or removing one closes the handwriting block (its ink is saved first).
- **`settingsView` redraws by calling itself.** `rerender()` clears the root and runs the view again; it makes a new `Tts` each time. The view sets `speechSynthesis.onvoiceschanged` and never clears it (it replaces the previous handler, so they do not pile up).
- **The sound volume slider saves on every `input` event,** so dragging it sends many `PUT /api/settings` requests.
- **Adding a setting** needs three places: `DEFAULT_SETTINGS` in `server.py` (the server ignores unknown keys), `Settings` in `types.ts`, and a control here.

### Known rough edges

These were seen while reading the code. They are listed so nobody is surprised; the ones still listed are not fixed.

- In `notes.ts`, `rename()` waits for `saving` but does not flush `saveBody`. If the title changes within 600 ms of the last keystroke in the body, `cur` is briefly replaced by a server copy without those keystrokes. The pending save still sends them.
- In `notes.ts`, `put()` takes the body from the server's answer when the patch contained a body. Text typed after the request was sent is in the textarea and in the next pending save, but `cur.body` is stale until the next keystroke. The comment above that line describes the other case (a patch without a body).
- In `notes.ts` `tableView`, `value()` handles a `"created"` column, but no header offers it.
- The slash menu's Table entry leaves the caret at the start of the empty row, before its first `|`, not inside the first cell.
- In `lecture.ts`, the composer turns `$…$` into `\(…\)` when a sticky note is added. Editing a sticky note in place does not, so `$…$` typed during an edit stays as typed and is not drawn as math.
- In `lecture.ts`, emptying a sticky note while editing does not save (an empty body is ignored) and the old text comes back. The only way to remove a note is its delete button.
- In `lecture.ts` `newSketch`, the line `if (tab === "cornell") tab = "page"` cannot run: the Sketch button is in the composer, which is only drawn on the `"page"` tab.
- In `bigMap`, with more than 250 notes the loop runs 90 steps but the cooling is still worked out over 180, so the layout stops while the step size is still about half of its start value.
- The ink toolbar's Clear button uses the browser's `confirm()`; the rest of the app uses `confirmBox()`.
- In `lectures.ts`, the plural test is `pages > 1`, so a count of 0 would read "0 page".
- The menu text for Settings in `main.ts` mentions the timer, but the timer's two options are on the Timer page, not in Settings.
- In `ai-settings.ts`, the Clear AI history confirm text says "AI calls that are running stop"; the route stops only library questions, brainstorms and a digest (chapter 3, section 7b).
- The two privacy checkboxes are drawn under **Cloud model**, and their labels say "cloud", although they also act on a "local" endpoint on another computer.
