# Readhold: Reading and Learning App Plan

Nov 6, 2026 · @Ali

> **Note (2026-11-25):** this is the original plan, kept as written. Import from a link (web articles and arXiv), described below, was removed on 2026-11-25. Readhold downloads nothing: to read a web article or an arXiv paper, save it as a PDF first, or paste its text. Since 2026-11-25 there is one connection it can make: to the AI model you chose, and only while AI is switched on (`docs/ai/PLAN.md`). See `docs/PHASES.md`.

Readhold is a local-first reader for papers, articles and notes that gives every long text a map before the wall, keeps you active while you read, and turns what you read into notes and memory. Every feature works with no AI; a local model is an optional plug-in that only makes things faster.

## The problem

You start papers and articles, then drop off at a predictable point: right after the abstract or intro, where the long text begins. Code loses you when it gets long and tangled. Today's tools (PDF viewers, browsers) show the whole wall at once and do nothing to keep you engaged, so reading turns passive, boring and tiring.

The cost is real: papers left half-read, shallow understanding before exams, and a story that you're "lazy" when the actual problem is the tool and the method.

**Who it's for:** you first (a student, product manager and AI engineer reading research papers, course material, docs and markdown files). Later, students and engineers with the same drop-off pattern.

## Goals and non-goals

Version 1 succeeds if you finish more of what you open, remember it a week later, and can start a session in seconds, all without AI.

**Goals**

1. **Get past the cliff:** read at least 80% of the key sentences in papers and articles you open, instead of stopping after the abstract.
2. **Remember it:** answer your own questions about a paper from memory one week later.
3. **Start in under 30 seconds:** opening the app puts you back at your exact next step.
4. **Fully offline, no AI:** every feature in this plan works with the AI switch off.
5. **Notes come for free:** finishing a paper leaves you with a summary sheet built from your own highlights and answers.

**Non-goals for version 1**

- **No AI dependency.** AI is a later plug-in; nothing waits for a model.
- **No code mode yet.** It needs its own redesign (missions and live values) and comes in a later phase.
- **No social or sharing features.** This is a personal tool first; sharing adds accounts and servers.
- **No perfect PDF layout handling.** Complex tables and math-heavy layouts get a readable fallback, not a perfect copy.
- **No native mobile app.** Desktop first; a web version (including reading on a phone) comes later from the same front end.

## Design principles

Seven rules decide every feature; if a feature breaks one, it gets cut or redesigned.

1. **Map before the wall.** Every text shows its shape (sections, questions, length) before its detail.
2. **Read with a job.** You read to answer questions, not to reach the last page.
3. **Attempt before reveal.** You guess before an explanation, and recall before moving on.
4. **Effort where it pays.** Pace slows on dense sentences and speeds through easy ones.
5. **Low days still count.** Energy modes make a tired 10-minute session real progress.
6. **AI is a plug-in, never a dependency.** Each feature has a non-AI version; AI only makes it faster.
7. **Offline and local.** Everything works with no internet, and documents, notes and stats live on your machine.

## Import and formats

Every import ends in the same internal shape: a document made of sections, paragraphs and sentences. Structure is found with rules, not AI.

| Source | How you add it | How structure is found | Version |
| --- | --- | --- | --- |
| arXiv paper | Paste the link | Use arXiv's HTML version when it exists, else the LaTeX source; sections, abstract, figures and references come out clean | 1 |
| PDF (course slides, papers) | Drag in the file | Text with positions from pdf.js; headings from font size; "Abstract", "Introduction", "References" detected by keyword; two-column order fixed by x-position | 1 |
| Web article | Paste a URL | Readability-style extraction removes menus and ads; headings become sections | 1 |
| Markdown and text | Paste or open a file | Headings become sections; backtick terms become concepts; code blocks set aside | 1 |
| EPUB books | Open a file | Chapters from the book's own table of contents | Later |

A **fix-the-structure** view lets you merge, split or rename sections when a PDF comes out messy, so a bad import never blocks reading. A **clean view** hides references, footnotes and boilerplate by default, with one tap to bring them back.

## Reading engine

The engine is the part already proven in the simulation: a pacer that moves through the text at a speed that follows its density.

| Feature | What it does | How it works without AI |
| --- | --- | --- |
| Sentence pacer | Highlights one sentence at a time and moves on by itself | Time per sentence = word count, your speed and the sentence's density score |
| Word pacer | A highlight moves word by word, pausing at commas and full stops | Time per word scales with word length, punctuation and density |
| Focus word mode | Shows one word at a time in a fixed spot, for very fast skim passes | Same timing as the word pacer; optional, off by default |
| Density score | Decides where to slow down | Rare-word ratio from a word-frequency list, sentence length, numbers, symbols, math and acronyms; it also learns which sentences you personally slow down on |
| Read aloud | Reads the text with a synced word highlight | The system's built-in voices; dense sentences read slightly slower; offline neural voices later |
| Energy modes | Low, medium or high at the start of a session | Low blurs the text ahead and slows the pace; high speeds it up |
| Focus view | Dims everything except the current paragraph or question | Pure display rules |
| Background skipping | Marks paragraphs safe to skip, like related work | Section-name rules plus your own marks |
| Reading comfort | Font, size, line length, spacing, dark mode, a dyslexia-friendly font | Settings saved per document type |
| Navigation | Section map, keyboard control, jump to any sentence or word | Click any word to restart the pacer from there |

Keyboard first: Space plays or pauses, arrow keys move a sentence, number keys add highlights (see Notes).

## Understanding features

Without AI, the app doesn't explain things for you; it makes you build the understanding, faster, and hands you the right part of the text at the right moment.

**Questions and reading plans**

- **Claim-to-question builder.** After the abstract or intro, each sentence becomes a card you can turn into a question with one tap, using starters like "How does…", "What proves…", "Why does…". You edit the wording; it takes about a minute.
- **Question templates by section type.** Method gets "How does it work, step by step?", Results gets "Which numbers back the main claim?", and so on, ready to accept or delete.
- **Tag as you read.** Press Q then 1, 2 or 3 to mark a paragraph as answering a question. The map fills in as you go, and the next paper of the same kind starts with better templates.
- **Three-pass plan for papers.** Pass 1 covers the title, abstract, headings, figures and conclusion (about 5 minutes). Pass 2 covers method and results. Pass 3 is the details, and is optional.
- **Prediction prompt.** At the start of a section you write one line on what you expect it to show, then compare at the end.

**Understanding terms without AI**

- **Guess gate.** Select any word or phrase, write your guess, then reveal the answer from the sources below. Every guess goes to your review list.
- **Definition finder.** Jumps to where the document itself defines the term, using patterns like "X is", "we define X", "X refers to" and the first bold or italic use. Papers usually explain their own terms; this finds that sentence instantly.
- **Acronym expander.** Detects "Long Form (LF)" once, then shows the expansion every time "LF" appears.
- **Personal glossary.** Every term you look up is saved with your definition and the sentence it came from. Optional offline dictionary and online encyclopedia lookups are included.

**No more scrolling to find things**

- **Figure, table and equation peek.** Hovering "Figure 3", "Table 2" or "Eq. 4" shows it in a popup, so you never lose your place.
- **Citation peek.** Hovering "\[12\]" shows that reference's title and year, with a button to add it to your reading queue.
- **Back-jump.** After any jump, one key takes you back to the exact sentence you left.

**Closing the loop**

- **Explain-it box.** At the end of a document, you write a three-sentence explanation as if for a younger student. Gaps in that explanation show what to reread.
- **Confusion marker.** Any sentence you mark as confusing is shown first next session, with what you've learned since.

## Notes and highlights

Highlights have a meaning, not just a color, so the app can assemble your notes for you when you finish.

| Key | Highlight type | Use it for | Where it goes later |
| --- | --- | --- | --- |
| 1 | Claim | What the authors say is true | Summary sheet, main points |
| 2 | Evidence | Numbers, results, proof | Summary sheet, under its claim |
| 3 | Definition | A term being defined | Glossary and flashcards |
| 4 | Confusing | Anything you didn't get | Shown first next session |
| 5 | Idea | Something it sparks for your own work | Idea inbox |

- **Margin notes** attach to a sentence, so they stay with their context.
- **"In my words" answers.** Each question's recall answer is saved as a note.
- **Auto summary sheet.** When you finish, one page is assembled from the claims, evidence under each claim, your question answers, glossary terms and open confusions. Every line links back to its sentence.
- **Idea inbox.** Idea highlights and quick captures collect in one place, outside any document. This is the raw material for creative thinking from our first conversation, and it can later feed a daily "combine two ideas" prompt.
- **Concept pages.** Tag a concept once, and its page lists every highlight and note on it across all your papers.
- **Export** to Markdown files with links back to the source, so notes also work in Obsidian or any notes app.

## Memory and review

Reading once and forgetting is the main way study time gets wasted. Here review is built from what you already did while reading, so it costs no extra setup.

- **Recall checkpoints.** After each question, you answer it from memory in one line, then compare with the text. This is already working in the simulation.
- **Cards made automatically:**
  - guess-gated terms (term on the front, your corrected definition on the back),
  - Definition highlights,
  - your questions with their answers,
  - fill-in-the-blank cards from any Evidence highlight: click the number or word to hide.
- **Spaced repetition with FSRS**, the modern open-source scheduling algorithm. Cards come back right before you'd forget them. A daily review takes about 5 minutes and has its own cap, so it never piles up.
- **Confusion first.** Next session opens with your open confusions from last time.
- **End-of-document quiz.** Your own questions are asked back in random order, a day after you finish.
- **Exam mode.** Pick a course or tag, and it builds a timed quiz from all its cards and questions. This fits your course study tools.

## Focus, stamina and progress

These features target starting, staying and coming back, which is where the "laziness" actually happens.

- **One-tap start.** Opening the app shows your saved next-step sentence and a Resume button, and nothing else.
- **Session setup in 5 seconds:** energy level, one document, one question, and a time box of 10, 15 or 25 minutes.
- **End-of-session note.** Stopping asks for one sentence about what comes next, which becomes the next resume point.
- **Distraction guard.** If you switch windows, the pacer pauses and logs it. When you return it says where you left off, with no guilt message.
- **Stamina stats:** focused minutes, longest unbroken run and key sentences read, per day and per week. The trend is what matters: a longer unbroken run is reading stamina growing.
- **Speed ramp.** The pace rises 5% after each question you finish without pausing much, and never drops below your comfort speed.
- **Low-day streak.** A day counts if you read 10 minutes or did your review, so a tired day doesn't break the streak.
- **Reading queue with a reason.** Every document you add asks "why am I reading this?" in one line, and the queue is sorted by your deadlines.
- **Weekly review.** Each week shows what you finished, what you can now explain, and which confusions are still open.
- **Sand progress.** The animated sand jar fills from real progress only (sentences read, questions answered, cards reviewed), not time spent.

## Themes and ambience

Themes make the app feel calm and alive, but they never compete with the text. The reading text always sits on a solid, high-contrast panel; motion lives only in the background and margins.

| Theme | Calm look | Ambient motion | Progress you see | Optional sound |
| --- | --- | --- | --- | --- |
| Sand | Warm stone and sand | Still | The sand jar fills | None |
| Rain | Soft blue-grey, like a window on a rainy day | Rain streaks and slow droplets in the margins | The fogged window slowly clears | Rain |
| Forest | Deep greens, warm paper | Leaves drifting, light rays shifting slowly | Trees grow along the bottom edge | Wind and birds |
| Garden | Soft green and cream | An occasional butterfly | A flower blooms for each question answered | Light breeze |
| Cloud | Pale sky and white | Clouds drifting slowly | The sky clears and the sun comes out | Soft wind |
| Galaxy | Deep indigo and violet | Slow nebula drift, faint twinkling stars | Each reviewed card adds a star to a constellation | Low ambient hum |
| Night sky | Navy with warm text | Rare shooting star, the moon moving across the session | The moon phase fills | Crickets |
| Pixel art | A retro palette (the reading text keeps a normal font) | A gentle parallax pixel scene | A small pixel character walks further along a path | Soft lo-fi loop |
| Paper | Plain paper, no motion | None | A simple bar | None |

**What makes a theme dynamic**

- **Time of day:** the palette shifts slowly from dawn to night, following your clock.
- **Session state:** motion calms down while the pacer runs, gets a little livelier during breaks and review, and gives a small, quiet moment when you finish a question.
- **Energy mode:** low energy picks softer colors and slower motion automatically.
- **Intensity slider:** Off, Still, Gentle or Lively, per theme. Sound is always off until you turn it on.

**Theme rules (for the build)**

- Each theme is a folder: a `theme.json` of color and font tokens, one scene module for the animation, and optional assets. Adding a new theme means adding a folder, with no core code changes.
- Every theme's text colors must pass WCAG AA contrast (4.5 to 1 for body text), checked by an automated test.
- No flashing: nothing flashes more than 3 times a second, so the rain theme has no lightning.
- The system's reduce-motion setting is respected, and it switches every theme to Still.
- All art and sound files are bundled with the app and use CC0 or similarly free licenses, so everything works offline and is safe to use.

## Reliability, safety and smoothness

These are requirements, not nice-to-haves: every phase must meet them before its gate counts.

**Reliability: never lose work**

- Every highlight, note, answer and card is saved the moment it's made (SQLite in WAL mode). There is no Save button.
- An automatic daily backup of the database keeps the last 14 days, and an extra backup is made before any database migration.
- After a crash or restart, the app reopens at the exact sentence where you were.
- A failed import never blocks reading: it shows the reason, falls back to a plain-text view, and keeps the original file.
- Database schema changes are versioned migrations, never manual edits.
- Export everything (documents, notes, cards, stats) to Markdown and JSON at any time.
- Tests cover the parsers (on a fixture set of real PDFs, articles and markdown files from your courses), sentence splitting, density scoring, FSRS scheduling and theme contrast, plus end-to-end tests of the pacer and voice.
- Errors go to a local log file. Nothing is ever sent anywhere: no telemetry.

**Safety: a local app that can't be abused**

- The Python server listens only on `127.0.0.1`, on a random port, and every request needs a session token. It also checks the Host header, so websites and other apps can't talk to it.
- Imported web pages are untrusted: scripts, iframes and event handlers are stripped before display, and the window runs with a strict content-security policy.
- The app reads and writes only its own data folder and files you pick.
- Network use happens only during an import, only to the link you gave, with a timeout and a size limit (50 MB).
- No `eval` or remotely loaded code. Dependencies are pinned in a lock file.
- The later AI plug-in may only talk to a model server on your own machine.

**Smoothness: it should feel instant**

| What | Target |
| --- | --- |
| App opens to your resume point | Under 2 seconds |
| Import a 30-page PDF | Under 5 seconds, done in the background |
| Scrolling and the pacer highlight | 60 frames per second |
| Response to a key press or click | Under 50 ms |
| CPU use while reading with an animated theme | Under 5% on your laptop |

- The pacer uses one clock driven by `requestAnimationFrame`, so it never drifts. A highlight moves by toggling classes, not by redrawing the page.
- Long documents render only the visible sections, so a 100-page paper stays as fast as a short article.
- Parsing and density scoring run in Python or a Web Worker, never on the screen's main thread.
- Theme animations run on one canvas, capped at 30 frames per second, using only cheap transforms. They pause when the window is hidden or minimized, and a battery-saver mode switches them to Still.

## Optional AI layer (later)

AI is a switch in settings, off by default. When it's on, it upgrades features that already work; turning it off loses nothing. It talks to any local server with an OpenAI-compatible API (for example Ollama or llama.cpp), so the Qwen models you already run would plug straight in.

| Feature | Without AI (version 1) | With AI switched on |
| --- | --- | --- |
| Density score | Word rarity, length and symbols | The model's perplexity per sentence |
| Questions after the abstract | Tap-to-convert claims and templates | Questions drafted for you to edit |
| Term help | Definition finder, acronyms, glossary | A one-line explanation using the paper's context |
| Recall check | You compare your answer with the text | The model grades your answer and names what's missing |
| Cards | Made from your highlights | Extra cards suggested from the text |
| Summary sheet | Assembled from your notes | A draft paragraph on top of your notes |

One rule stays even with AI: its answer always appears after your own attempt, so the guess gate never goes away.

## Build plan

Four core phases take about 7 to 8 weeks of part-time work. Phase 1 is the first version that's genuinely useful for your courses.

&#91;embedded content: build plan · 5 phases, 4 gates\]

Phase 1 is highlighted as the minimum useful version; the dashed phase is optional. If a gate isn't met, fix that phase before starting the next, and any new idea goes into Phase 4 rather than the current phase.

## Tech stack and data model

A personal, fully offline tool: a small Python server on your own machine does the heavy work, and a web page inside a desktop window does the reading. Nothing is hosted anywhere and no account is needed.

| Layer | Choice | Why |
| --- | --- | --- |
| Engine | Python with FastAPI, run locally | Your strongest language; one command starts it |
| Window | pywebview | Opens the reading page as its own desktop window, away from browser tabs |
| Reading screen | HTML, CSS and TypeScript, built from the simulation | Word highlights, voice sync and animation are what browsers do best |
| Storage | SQLite, one file on your disk | Documents, notes, cards and stats in one place you can back up |
| PDFs | pypdfium2 (PDFium; replaced PyMuPDF to avoid the AGPL) | Text with font sizes and positions, for headings and two-column pages |
| Articles | trafilatura | Clean article text, saved once and readable offline after that |
| Markdown | mistune or Python-Markdown | Headings and code blocks parsed reliably |
| Density | A word-frequency list stored locally, plus simple rules | No model needed |
| Voice | Offline system voices now, Piper later | Works with no internet |
| Spaced repetition | The FSRS Python package | A proven scheduler |
| Fonts and libraries | Bundled inside the app, no CDNs | The app opens and works with Wi-Fi off |

**Offline rule:** the internet is touched only when you import a link (an arXiv paper or an article). The full text is saved locally at that moment, so reading, notes, review and stats never need a connection. Pick a local voice in settings, because some browser voices stream from the internet.

**Desktop now, web later:** the reading screen is a plain web app that talks to the Python server through one small API module and uses no pywebview-only features. A web version later means serving the same front end in a browser, not a rewrite.

**Windows first:** on Windows, pywebview uses the built-in Edge WebView2, so the reading screen gets a modern Chromium engine with nothing extra to install. The offline voices to test are the built-in Microsoft ones (David, Zira, Mark); Edge's "Natural" voices need the internet. Start the app from a desktop shortcut that runs it with `pythonw` (no console window); a PyInstaller `.exe` is optional.

**Core data model**

- **Document**: title, source, type, date added, why you're reading it.
- **Section, Paragraph, Sentence**: order, text, density score, background flag.
- **Question**: document, text, linked paragraphs, your recall answer.
- **Highlight**: sentence range, type (claim, evidence, definition, confusing, idea), note.
- **Term**: the term, your definition, the source sentence, the first time you saw it.
- **Card**: front, back, source, FSRS schedule state.
- **Session**: start, end, energy, focused time, longest run, next-step sentence.

## Sharing between your PC and laptop (later, only if needed)

Data sync between machines is not part of the current build. For now, only the code is shared, through a private GitHub repository cloned on both machines. The design below is parked for later, if you find you need it.

| What | How it moves | Why this way |
| --- | --- | --- |
| App code | Private GitHub repository, cloned on both machines | Normal Git workflow; pull before you start, push when you stop |
| Python environment | `uv` with a lock file in the repo | Both machines get exactly the same package versions |
| Your data (notes, cards, stats, progress) | A change log per device, inside a synced folder | No two machines ever write the same file, so sync can't corrupt it |
| Imported documents (PDFs, saved articles) | A `library` folder in the same synced folder, files named by content hash | Files never change after import, so they never conflict |
| The local database | Rebuilt on each machine from the change logs | Never synced directly |

**Why not sync the database file itself:** cloud folders like OneDrive can corrupt a SQLite file if it's open on one machine while syncing, or changed on both. Instead, every change (a highlight, a note, a card review, your reading position) is written as one line to that device's own log, for example `sync/pc.jsonl` and `sync/laptop.jsonl`. On start, each machine reads the other device's new lines and merges them into its own database. Two edits to the same note keep the newer one, and the older version is saved in history, never lost.

**Which synced folder**

- **OneDrive:** already built into Windows; works anywhere with internet. The simplest start.
- **Syncthing:** free, open source and peer to peer, with no cloud at all. It syncs directly between the PC and laptop on the same Wi-Fi. It's the most private option, but syncing only happens when both machines are on.

**Keep out of GitHub:** the `data` and `library` folders, the `sync` folder and `.venv` all go in `.gitignore`. The repository holds code only, which also keeps any copyrighted papers out of it.

**Build note:** sync itself is not built now. Records still use UUIDs, a device id, an updated-at time and a deleted flag from Phase 0, because it costs nothing today and keeps sync possible later without rewriting the database.

## Success metrics

The app tracks its own success, because you are the first user.

| Metric | Target | Checked |
| --- | --- | --- |
| Documents where you get past the intro cliff | 80% of documents opened | Weekly |
| Key sentences read per document | 70% or more | Per document |
| Recall answers you write instead of skipping | 75% or more | Weekly |
| Days with review done | 5 of 7 | Weekly |
| Time from opening the app to reading | Under 30 seconds | Per session |
| Papers finished per month | Double the count from last month (count it now as a baseline) | Monthly |
| Still using it daily | After 4 weeks | Once |

## Open questions

- [ ] Do arXiv HTML pages and your course PDFs import cleanly? Test on 5 real files before building the rest.
- [ ] Do you read Arabic material too? If yes, right-to-left layout and Arabic voices change the design from day one.
- [ ] After Phase 3: do you need your reading data on both machines? If yes, choose OneDrive or Syncthing and build the parked sync design.
- [ ] How should code mode work once it returns: missions and live values, as proposed?

## Notes for building with Claude Code

- Build one phase at a time, in order, and stop at each gate. Don't start the next phase in the same session.
- Put the design principles and the reliability, safety and smoothness rules into the project's rules file for Claude Code (a working note, not published with the repository), so every session follows them.
- Write the parser tests first, against 5 of your own real files, before building the reader on top.
- Port the reader from the simulation rather than starting over: its pacer, word timing, voice sync, guess gate, recall checkpoint and resume point already work.
- Start the theme system in Phase 0 with two calm themes (Sand and Paper). The animated themes come in Phase 3, once the reader is stable.
- Any new idea during a phase goes into a parking-lot list in the repo, not into the current phase.
