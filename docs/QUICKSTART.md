# Readhold in 15 minutes

A friendly tour for your first day. Every detail lives in the full guide, [`GUIDE.md`](GUIDE.md); this page is just
enough to get going.

**What Readhold is for.** You read a paper, an article or your own notes, and you want to *understand* it and *keep*
it, not just reach the last page. Readhold shows the shape of a text first, gives you a question to read for, paces
you one sentence at a time, and turns what you mark into notes and review cards. Everything stays on your computer.

---

## 1. Install and open it (once)

You need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/). Then, in a terminal, in the Readhold folder:

```bash
uv sync
cd web && npm ci && npm run build && cd ..
uv run python -m readhold
```

A window opens. Next time only the last line is needed (on Windows you can also double-click `Readhold.pyw`).

**Make a desktop shortcut (Windows).** In the same folder, run this once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
```

A **Readhold** shortcut with the logo appears on your desktop and in Start, and opens the app with no console window.
To pin it to the taskbar: press Start, type `Readhold`, right-click it and choose **Pin to taskbar**.

## 2. Find your way around

The menu on the left has everything:

| Menu | What it is for |
|---|---|
| **Overview** | Today at a glance: your next step, today's tasks, the timer, routines, cards due |
| **Plan** | Tasks and routines, and **Today**: one main goal and the next step |
| **Timer** | A focus timer beside a to-do list |
| **Study** | Your documents (the reading list), lectures and notebooks, goals, review cards and the glossary |
| **Notes** | Linked notes, the journal, the idea inbox and Think |
| **Stamina** | How long you focused, your streak and the weekly review |
| **Settings** | Themes, reading comfort, the timer, AI and your data |

Two shortcuts work everywhere: **Ctrl+K** finds anything, and **Ctrl+J** captures a thought before it slips away.
**«** at the top of the menu (or **Ctrl+\\**) hides it when you want the whole window.

## 3. Read your first document

1. **Add it.** Go to **Study → Documents** and drop a PDF, Markdown, text or code file on the box, or use
   **Paste text**. Readhold asks *why* you are reading it: one line is enough.
2. **Open it** with **Read**. A small box asks how much energy you have (low, medium, high), how long you have
   (10, 15 or 25 minutes) and, if you like, one question to read for. Press **Enter**.
3. **Look at the map first.** The left column shows every section and how long it is. You see the whole shape
   before the detail.
4. **Press Space.** The pacer lights one sentence at a time and moves on by itself: slower on dense sentences, faster
   on easy ones. **← →** step by hand, **−** and **+** change the speed.
5. **Mark as you go:** **1** claim, **2** evidence, **3** definition, **4** confusing, **5** idea. **N** writes a
   margin note, **I** saves a quick idea. Press **?** to see every key.
6. **End the session** with **E**. Write one sentence about what comes next: that is what Readhold shows you
   tomorrow, and the reader reopens at the exact sentence you stopped on.

Low on energy? Pick **Low** and **10 minutes**. A short, tired session still counts.

## 4. Remember what you read

- **Review.** Your highlights and answers become cards. **Study → Review** asks a few each day (about five minutes).
  Rate how well you knew each one; Readhold brings it back just before you would forget it.
- **Summary sheet.** At the end of a document Readhold asks you to explain it in three sentences, then builds a
  summary sheet from your marks. You can export it to Markdown.
- **Notes.** In **Notes**, write freely. `[[Another note]]` links two notes, `#tag` groups them, and the side shows
  what links here and a small map.

## 5. Plan your days

- **Plan → Tasks**: type a task like `read chapter 2 @tomorrow ~25`, where `@` sets the day and `~` the minutes.
  **📚 Plan my reading** spreads what is left to read over your days, never past your minutes or your deadline.
- **Timer**: press **25 min** for a focus session; the minutes show up in **Stamina**.
- **Routines**: short lists you do in the same order every day, ticked off on the Overview.

## 6. Make it yours

- **Settings → Theme**: eighteen themes. You start on **Clean**, a calm minimal look; the rest go from plain paper to calm scenes
  (**Meadow**, **Orbit**) and three comics themes. Each has a
  light and a dark look (**Light / dark** in Settings). The reading text always stays on a calm, solid page.
- **Settings → Reading comfort**: font (including OpenDyslexic), text size, line spacing and width.
- **Motion**: Gentle, Lively or Still. Still stops every animation.
- **See more of your theme while reading**: **Hide panels** in the reader's top bar (or **Ctrl+\\**) folds the side
  panels away, so the page sits alone over the theme.

## 7. Optional: switch on the AI assistant

Readhold works fully without AI. If you want help (explanations, answers with quotes, study cards, a note chat…),
you can connect a model **that runs on your own computer**, so nothing leaves it.

**Get started with AI in 5 minutes**

1. **Install Ollama**, a free app that runs models on your computer: [ollama.com](https://ollama.com).
2. **Download a model.** In a terminal: `ollama pull llama3.2` (about 2 GB; a bigger model such as `qwen2.5:7b`
   gives better answers if your computer has 16 GB of memory or more).
3. **Connect Readhold.** Open **Settings → AI**, choose **Local model**, leave the server as **Ollama**, type
   `llama3.2` as the model, and press **Test connection**. It should say the model answered.
4. **Try it.** Open a document, select a passage and press **Explain**; or open a note and press **💬** to ask the
   model to format it, enhance it or write an idea.

Every AI feature asks the model only when you press its button, shows where its answer came from (**Why did it say
this?**), and changes nothing until you press **Use** or **Add**, with **Undo**. Tag a document or note `#private`
and it never goes to a cloud model.

**A cloud model instead?** Choose **Cloud model** in Settings → AI, pick Anthropic or OpenAI, and paste your own API
key. The key is kept in your computer's credential store, never in a file. Turn on **Show what will be sent** to see
the exact text before each request.

## 8. Your data is safe

- Everything you do is saved the moment you do it. There is no Save button.
- A backup of your database is made every day, and the last 14 are kept.
- **Settings → Your data → Export everything** writes all of it to JSON and Markdown.
- Readhold connects to nothing by itself: no account, no telemetry. The only connection it can make is to the AI
  model you chose, and only while AI is on.

---

**Next:** the full guide, [`GUIDE.md`](GUIDE.md), explains every screen, setting and key.
