// Glossary + concept pages, idea inbox, stats + weekly review, settings, fix-the-structure.
import { api } from "../api";
import { saveSettings, state, FONTS, applyComfort, comfortFor } from "../state";
import { mathText } from "../math";
import { logList } from "./logs";
import { applyTheme } from "../themes";
import { Tts } from "../tts";
import type { Doc, NotePage, Term, WeekPlan } from "../types";
import { connectedCard } from "../related";
import { libraryHead, notesHead } from "./libtabs";
import { aiSettingsBlock } from "./ai-settings";
import { askText, clear, confirmBox, fmtMinutes, h, KIND_LABELS, prefersReducedMotion, toast } from "../util";

// ------------------------------------------------------------------ glossary
export async function glossaryView(root: HTMLElement, params: URLSearchParams): Promise<void> {
  const concept = params.get("concept");
  if (concept) return conceptView(root, concept);
  const terms = await api.get<Term[]>("/api/terms");
  const search = h("input", { type: "search", placeholder: "Filter terms…", "aria-label": "Filter terms" });
  const list = h("dl", { class: "glossary big" });
  const draw = () => {
    clear(list);
    const q = search.value.trim().toLowerCase();
    for (const t of terms.filter((x) => !q || x.term.toLowerCase().includes(q) || x.definition.toLowerCase().includes(q))) {
      list.append(h("div", { class: "term-card" },
        h("dt", null, h("a", { href: `#/glossary?concept=${encodeURIComponent(t.term)}` }, t.term), t.document_title ? h("span", { class: "muted small" }, ` · ${t.document_title}`) : null),
        h(
          "dd",
          null,
          t.definition || h("em", null, `guess: ${t.guess || "—"}`),
          t.source_text ? h("div", { class: "muted small" }, `“${t.source_text.slice(0, 160)}”`) : null,
          h(
            "div",
            { class: "row" },
            h(
              "button",
              {
                class: "btn small ghost",
                onclick: async () => {
                  const v = await askText(`Define ${t.term}`, "Your definition", t.definition, { multiline: true });
                  if (v === null) return;
                  Object.assign(t, await api.patch<Term>(`/api/terms/${t.id}`, { definition: v }));
                  draw();
                },
              },
              "Edit",
            ),
            h(
              "button",
              {
                class: "btn small ghost",
                onclick: async () => {
                  if (!(await confirmBox("Delete term?", `Remove “${t.term}” and its review card?`, "Delete"))) return;
                  await api.del(`/api/terms/${t.id}`);
                  terms.splice(terms.indexOf(t), 1);
                  draw();
                },
              },
              "Delete",
            ),
          ),
        ),
      ));
    }
    if (!list.childNodes.length) list.append(h("p", { class: "empty" }, "Terms you look up with the guess gate (G) collect here."));
  };
  search.addEventListener("input", draw);
  root.append(h("section", { class: "glossary-view" }, libraryHead("glossary"), search, list));
  draw();
}

async function conceptView(root: HTMLElement, term: string): Promise<void> {
  const c = await api.get<{ glossary: Term[]; highlights: { document_id: string; sentence: number; text: string; type: string; title: string; note: string }[]; notes: { document_id: string; sentence: number; text: string; title: string }[]; mentions: { document_id: string; ord: number; text: string; title: string }[] }>(`/api/concepts?term=${encodeURIComponent(term)}`);
  const link = (doc: string, ord: number, text: string) => h("a", { href: `#/read/${doc}?s=${ord}` }, mathText(text));
  root.append(
    h(
      "section",
      { class: "concept" },
      h("a", { class: "btn ghost", href: "#/glossary" }, "← Glossary"),
      h("h1", null, term),
      c.glossary.map((g) => h("p", { class: "explain" }, g.definition || `guess: ${g.guess}`)),
      c.highlights.length ? [h("h2", null, "Your highlights"), c.highlights.map((x) => h("p", null, h("span", { class: `tag hl-${x.type}` }, x.type), " ", link(x.document_id, x.sentence, x.text), h("span", { class: "muted small" }, ` — ${x.title}`)))] : null,
      c.notes.length ? [h("h2", null, "Your notes"), c.notes.map((n) => h("p", null, link(n.document_id, n.sentence, n.text), h("span", { class: "muted small" }, ` — ${n.title}`)))] : null,
      h("h2", null, "Where it appears"),
      c.mentions.length ? c.mentions.map((m) => h("p", null, link(m.document_id, m.ord, m.text), h("span", { class: "muted small" }, ` — ${m.title}`))) : h("p", { class: "muted" }, "No mentions found."),
      connectedCard("term", "", term),
    ),
  );
}

// ------------------------------------------------------------------ ideas
export async function ideasView(root: HTMLElement): Promise<void> {
  const list = h("ul", { class: "ideas" });
  const input = h("textarea", { rows: 2, placeholder: "Quick capture — Ctrl+Enter to save" });
  const add = async () => {
    if (!input.value.trim()) return;
    await api.post("/api/ideas", { text: input.value.trim() });
    input.value = "";
    draw();
  };
  input.addEventListener("keydown", (e) => e.key === "Enter" && e.ctrlKey && add());
  const draw = async () => {
    const ideas = await api.get<{ id: string; text: string; document_id: string | null; sentence: number | null; document_title: string | null; created_at: string }[]>("/api/ideas");
    clear(list);
    for (const i of ideas)
      list.append(
        h(
          "li",
          null,
          h("p", null, i.text),
          h(
            "div",
            { class: "muted small row" },
            i.created_at.slice(0, 10),
            i.document_id ? h("a", { href: `#/read/${i.document_id}${i.sentence !== null ? `?s=${i.sentence}` : ""}` }, i.document_title ?? "source") : null,
            h("a", { class: "btn small ghost", href: `#/think/idea/${i.id}`, title: "Brainstorm this idea with your related notes and reading" }, "Think"),
            h("button", { class: "btn small ghost", title: "Make it a task on the Plan page", onclick: async () => {
              await api.post("/api/todos", { text: i.text.replace(/\s+/g, " ").trim().slice(0, 500), minutes: 25, ...(i.document_id ? { link_type: "document", link_id: i.document_id } : {}) });
              toast("Added to Plan, under Anytime.", "ok", 4000, { label: "Open Plan", run: () => void (location.hash = "#/plan") });
            } }, "→ Task"),
            h("button", { class: "btn small ghost", title: "Start a note from this idea", onclick: async () => {
              const title = await askText("New note from this idea", "Title", i.text.replace(/\s+/g, " ").trim().slice(0, 60), { okLabel: "Create" });
              if (!title) return;
              const from = i.document_title && !/[\[\]|#\n]/.test(i.document_title) ? `\n\n— [[${i.document_title}${i.sentence !== null ? `#s${i.sentence}` : ""}|${i.document_title}]]` : "";
              try {
                const p = await api.post<NotePage>("/api/pages", { title, body: `${i.text}${from}\n` });
                toast("Note created.", "ok", 5000, { label: "Open the note", run: () => void (location.hash = `#/notes/${p.id}`) });
              } catch (e) {
                toast((e as Error).message, "error");
              }
            } }, "→ Note"),
            h(
              "button",
              {
                class: "btn small ghost",
                onclick: async () => {
                  await api.del(`/api/ideas/${i.id}`);
                  draw();
                },
              },
              "Archive",
            ),
          ),
        ),
      );
    if (!ideas.length) list.append(h("p", { class: "empty" }, "Idea highlights (key 5) and quick captures (key I) land here."));
  };
  root.append(h("section", { class: "ideas-view" }, notesHead("ideas"), h("div", { class: "row" }, input, h("button", { class: "btn primary", onclick: add }, "Save")), list));
  await draw();
}

// ------------------------------------------------------------------ stats + weekly review
interface Day {
  date: string;
  focused_ms: number;
  longest_run_ms: number;
  sentences: number;
  reviews: number;
  distractions: number;
  counts: boolean;
}

interface FeelItem {
  what: string;
  energized: number;
  neutral: number;
  drained: number;
}

interface Week {
  finished: { id: string; title: string }[];
  explained: { text: string; answer: string; title: string }[];
  open_confusions: { text: string; document_id: string; sentence: number; title: string }[];
  logs: { day: string; did: string; learned: string; next: string }[];
  steps_done: { title: string; output: string; quest: string }[];
  quests_done: { id: string; title: string }[];
  feel: { drains: FeelItem[]; lifts: FeelItem[]; total: { energized: number; neutral: number; drained: number } };
  practice: { got: number; partly: number; missed: number };
  habits: { title: string; days: number }[];
}

export async function statsView(root: HTMLElement): Promise<void> {
  const s = await api.get<{ days: Day[]; streak: number; week: Week }>("/api/stats");
  const w = s.week;
  const wp = await api.get<WeekPlan>("/api/week/plan").catch(() => null);
  const practised = w.practice.got + w.practice.partly + w.practice.missed;
  const last7 = s.days.slice(-7);
  const sum = (k: keyof Day) => last7.reduce((a, d) => a + Number(d[k]), 0);
  const maxMin = Math.max(10, ...s.days.map((d) => d.focused_ms / 60000));
  const maxRun = Math.max(...s.days.map((d) => d.longest_run_ms));
  root.append(
    h(
      "section",
      { class: "stats" },
      h("h1", null, "Stamina"),
      h(
        "div",
        { class: "tiles" },
        tile("Streak", `${s.streak} day${s.streak === 1 ? "" : "s"}`, "10 min or a review counts"),
        tile("Focused this week", fmtMinutes(sum("focused_ms")), `${last7.filter((d) => d.counts).length} of 7 days counted`),
        tile("Longest unbroken run", fmtMinutes(maxRun), "the number that shows stamina growing"),
        tile("Key sentences this week", String(sum("sentences")), `${sum("reviews")} cards reviewed`),
      ),
      h("div", { class: "isle stats-block" },
      h("h2", null, "Focused minutes, last 4 weeks"),
      h(
        "div",
        { class: "chart", role: "img", "aria-label": "Focused minutes per day" },
        s.days.map((d) =>
          h(
            "div",
            { class: `col ${d.counts ? "counts" : ""}`, title: `${d.date}: ${fmtMinutes(d.focused_ms)}, longest run ${fmtMinutes(d.longest_run_ms)}, ${d.sentences} sentences, ${d.reviews} reviews, ${d.distractions} switches away` },
            h("span", { class: "fill", style: { height: `${Math.round(((d.focused_ms / 60000) / maxMin) * 100)}%` } }),
            h("span", { class: "lbl" }, d.date.slice(8)),
          ),
        ),
      )),
      h("div", { class: "isle stats-label" },
        h("h2", null, "Weekly review"),
        h("p", { class: "muted small" }, "The last 7 days: what moved, what you wrote down, and what drained or lifted you.")),
      // each part of the week is its own island
      h("div", { class: "week-grid" },
      h("div", { class: "isle week-card" },
      h("h3", null, "Goals and steps done"),
      w.quests_done.length || w.steps_done.length
        ? h(
            "ul",
            null,
            w.quests_done.map((q) => h("li", null, h("strong", null, "Goal finished: "), h("a", { href: `#/quest/${q.id}` }, q.title))),
            w.steps_done.map((st) => h("li", null, st.title, st.output && st.output !== "done" ? h("span", { class: "muted" }, ` → ${st.output}`) : null, h("span", { class: "muted small" }, ` (${st.quest})`))),
          )
        : h("p", { class: "muted" }, "No goal steps finished this week."),
      ),
      h("div", { class: "isle week-card" },
      h("h3", null, "Your daily log"),
      w.logs.length
        ? logList(w.logs)
        : h("p", { class: "muted" }, "Close your day on Today (three lines) and this week's story writes itself here."),
      ),
      h("div", { class: "isle week-card wide" },
      h("h3", null, "Energy: what drains you, what lifts you"),
      w.feel.drains.length || w.feel.lifts.length
        ? h(
            "div",
            { class: "grid2" },
            h("div", null, h("div", { class: "kicker" }, "Drained you"), w.feel.drains.length ? h("ul", null, w.feel.drains.map((x) => h("li", null, x.what, h("span", { class: "muted small" }, ` · ${x.drained}×`)))) : h("p", { class: "muted small" }, "Nothing yet.")),
            h("div", null, h("div", { class: "kicker" }, "Lifted you"), w.feel.lifts.length ? h("ul", null, w.feel.lifts.map((x) => h("li", null, x.what, h("span", { class: "muted small" }, ` · ${x.energized}×`)))) : h("p", { class: "muted small" }, "Nothing yet.")),
          )
        : h("p", { class: "muted" }, "Tap how a session felt when you finish it (one tap, optional). After a few weeks this shows which work drains you, so you can change the method, not just push harder."),
      w.feel.drains.length ? h("p", { class: "muted small" }, "Tip: put draining work in your peak hours, make its low-energy version smaller, or pair it with something that lifts you.") : null,
      ),
      wp ? h("div", { class: "isle week-card" },
        h("h3", null, "Tasks and routines"),
        h("p", null, wp.tasks_done ? `${wp.tasks_done} task${wp.tasks_done === 1 ? "" : "s"} done` : "No task finished yet this week", ` · ${wp.open} open. `, h("a", { href: "#/plan" }, "Open Plan")),
        wp.areas.length ? h("p", { class: "muted small" }, wp.areas.map((a) => `${a.area} ${a.n}`).join(" · ")) : null,
        wp.routines.length ? h("ul", null, wp.routines.map((r) => h("li", null, r.title, h("span", { class: "muted small" }, ` · ${r.days} of ${r.of} days`)))) : null) : null,
      h("div", { class: "isle week-card" },
      h("h3", null, "Habits and practice"),
      h(
        "ul",
        null,
        w.habits.map((hb) => h("li", null, hb.title, h("span", { class: "muted small" }, ` · ${hb.days} of 7 days`))),
        h("li", null, practised ? `Mixed practice: ${w.practice.got} got it, ${w.practice.partly} partly, ${w.practice.missed} missed` : h("a", { href: "#/practice" }, "Try a mixed practice set")),
      ),
      ),
      h("div", { class: "isle week-card" },
      h("h3", null, "Finished reading"),
      s.week.finished.length ? h("ul", null, s.week.finished.map((f) => h("li", null, h("a", { href: `#/summary/${f.id}` }, f.title)))) : h("p", { class: "muted" }, "Nothing finished this week — that's fine, progress counts too."),
      ),
      h("div", { class: "isle week-card" },
      h("h3", null, "What you can now explain"),
      s.week.explained.length ? h("ul", null, s.week.explained.map((q) => h("li", null, h("strong", null, q.text), ` — ${q.answer}`, h("span", { class: "muted small" }, ` (${q.title})`)))) : h("p", { class: "muted" }, "Answer questions with Recall to see them here."),
      ),
      h("div", { class: "isle week-card" },
      h("h3", null, "Still-open confusions"),
      s.week.open_confusions.length ? h("ul", null, s.week.open_confusions.map((c) => h("li", null, h("a", { href: `#/read/${c.document_id}?s=${c.sentence}` }, c.text), h("span", { class: "muted small" }, ` (${c.title})`)))) : h("p", { class: "muted" }, "None open."),
      )),
    ),
  );
}

function tile(label: string, value: string, sub: string): HTMLElement {
  return h("div", { class: "tile" }, h("div", { class: "muted small" }, label), h("div", { class: "tile-val" }, value), h("div", { class: "muted small" }, sub));
}

// ------------------------------------------------------------------ settings
export async function settingsView(root: HTMLElement, params?: URLSearchParams): Promise<void> {
  const s = state.settings;
  const tts = new Tts();
  const set = async (patch: Partial<typeof s>) => {
    await saveSettings(patch);
    applyTheme();
    applyComfort(comfortFor(""));
  };
  const themeCards = h(
    "div",
    { class: "theme-cards" },
    state.themes.map((t) => {
      const tok = t.tokens.light;
      return h(
        "button",
        { class: `theme-card ${s.theme === t.id ? "on" : ""}`, onclick: async () => (await set({ theme: t.id }), rerender()) },
        h("span", { class: "swatch", style: { background: tok.bg } }, h("span", { style: { background: tok.panel, color: tok.text } }, "Aa"), h("span", { class: "dot", style: { background: tok.accent } })),
        h("strong", null, t.name),
        h("span", { class: "muted small" }, t.description),
      );
    }),
  );
  const select = (value: string, options: [string, string][], onchange: (v: string) => void) => {
    const el = h("select", { onchange: (e: Event) => onchange((e.target as HTMLSelectElement).value) }, options.map(([v, l]) => h("option", { value: v }, l)));
    el.value = value;
    return el;
  };
  const num = (value: number, min: number, max: number, step: number, onchange: (v: number) => void) => h("input", { type: "number", value, min, max, step, onchange: (e: Event) => onchange(Number((e.target as HTMLInputElement).value)) });
  const check = (value: boolean, label: string, onchange: (v: boolean) => void) => h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: value, onchange: (e: Event) => onchange((e.target as HTMLInputElement).checked) }), ` ${label}`);

  const voiceSel = h("select", { onchange: (e: Event) => set({ tts_voice: (e.target as HTMLSelectElement).value }) });
  const fillVoices = () => {
    clear(voiceSel);
    voiceSel.append(h("option", { value: "" }, "Automatic (first offline English voice)"));
    for (const v of tts.voices()) voiceSel.append(h("option", { value: v.name }, `${v.name} (${v.lang})`)); // offline voices only
    voiceSel.value = s.tts_voice;
  };
  fillVoices();
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = fillVoices; // replaces, never piles up

  const rerender = () => {
    clear(root);
    settingsView(root);
  };
  const GROUPS: [string, string][] = [["set-theme", "Theme"], ["set-comfort", "Reading comfort"], ["set-pacer", "Pacer"], ["set-simple", "Simple mode"], ["set-voice", "Voice"], ["set-review", "Review"], ["set-ai", "AI"], ["set-data", "Your data"]];

  root.append(
    h(
      "section",
      { class: "settings" },
      h("div", { class: "isle page-head" },
        h("h1", null, "Settings"),
        h("div", { class: "set-jump", role: "navigation", "aria-label": "Jump to a group" }, GROUPS.map(([id, label]) =>
          h("button", { type: "button", class: "chip", onclick: () => document.getElementById(id)?.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" }) }, label)))),
      h("div", { class: "isle set-block", id: "set-theme" },
      h("h2", null, "Theme"),
      themeCards,
      h(
        "div",
        { class: "grid2" },
        field("Light / dark", select(s.dark, [["auto", "Follow system"], ["light", "Light"], ["dark", "Dark"]], (v) => set({ dark: v as typeof s.dark }))),
        field("Panels", select(s.glass ?? "balanced", [["solid", "Solid (easiest to read)"], ["balanced", "Almost solid"], ["clear", "See-through, blurred (more of the theme)"]], (v) => set({ glass: v as typeof s.glass }))),
        field("Motion", select(s.intensity, [["off", "Off"], ["still", "Still"], ["gentle", "Gentle"], ["lively", "Lively"]], (v) => set({ intensity: v }))),
        field("Ambient sound", check(Boolean(s.sound), "Play the theme's sound", (v) => set({ sound: v }))),
        field("Sound volume", h("input", { type: "range", min: 0, max: 1, step: 0.05, value: s.sound_volume ?? 0.35, "aria-label": "Sound volume", oninput: (e: Event) => set({ sound_volume: Number((e.target as HTMLInputElement).value) }) })),
      ),
      h("p", { class: "muted small" }, "Motion stays in the background and margins; the text panel never moves. It calms down while the pacer runs, pauses when the window is hidden, and your system's reduce-motion setting always switches it to Still. Sounds are generated on this computer and are off until you turn them on."),
      ),
      h("div", { class: "isle set-block", id: "set-comfort" },
      h("h2", null, "Reading comfort (default)"),
      h(
        "div",
        { class: "grid2" },
        field("Font", select(s.font, Object.entries(FONTS).map(([k, f]) => [k, f.label]), (v) => set({ font: v }))),
        field("Size (px)", num(s.font_size, 14, 32, 1, (v) => set({ font_size: v }))),
        field("Line length (characters)", num(s.line_width, 40, 100, 2, (v) => set({ line_width: v }))),
        field("Line spacing", num(s.line_height, 1.3, 2.4, 0.05, (v) => set({ line_height: v }))),
      ),
      Object.keys(s.comfort_by_type ?? {}).length ? h("p", { class: "muted small" }, `Per-type overrides saved for: ${Object.keys(s.comfort_by_type).join(", ")}. `, h("button", { class: "link", onclick: async () => (await set({ comfort_by_type: {} }), rerender()) }, "Clear them")) : null,
      ),
      h("div", { class: "isle set-block", id: "set-pacer" },
      h("h2", null, "Pacer"),
      h(
        "div",
        { class: "grid2" },
        field("Current pace (wpm)", num(s.wpm, 80, 900, 10, (v) => set({ wpm: v }))),
        field("Comfort speed — the ramp never goes below it", num(s.comfort_wpm, 80, 900, 10, (v) => set({ comfort_wpm: v }))),
        field("Default pacer", select(s.pacer_mode, [["sentence", "Sentence"], ["word", "Word"], ["focus", "Focus word"]], (v) => set({ pacer_mode: v as typeof s.pacer_mode }))),
        field("Default energy", select(s.energy, [["low", "Low"], ["medium", "Medium"], ["high", "High"]], (v) => set({ energy: v as typeof s.energy }))),
      ),
      h(
        "div",
        { class: "stack" },
        check(s.speed_ramp, "Speed ramp: +5% after a question finished without many pauses", (v) => set({ speed_ramp: v })),
        check(s.prediction_prompts, "Prediction prompt at the start of each section", (v) => set({ prediction_prompts: v })),
        check(s.skip_background, "Skip background sections (like related work) when reading straight through", (v) => set({ skip_background: v })),
        check(s.clean_view, "Clean view: hide references and boilerplate by default", (v) => set({ clean_view: v })),
      ),
      ),
      h("div", { class: "isle set-block", id: "set-simple" },
      h("h2", null, "Simple mode"),
      h(
        "div",
        { class: "stack" },
        check(Boolean(s.simple_mode), "Simple mode: only today's tasks and the timer on the Overview, and a menu without group names", async (v) => (await set({ simple_mode: v }), window.dispatchEvent(new HashChangeEvent("hashchange")))),
      ),
      ),
      h("div", { class: "isle set-block", id: "set-voice" },
      h("h2", null, "Voice"),
      h(
        "div",
        { class: "grid2" },
        field("Read-aloud voice", voiceSel),
        field("Rate", num(s.tts_rate, 0.5, 2, 0.05, (v) => set({ tts_rate: v }))),
      ),
      h(
        "p",
        { class: "muted small" },
        "Only voices that work offline are listed (on Windows: Microsoft David, Zira, Mark). Voices that stream from the internet are left out, so the text you read never leaves this computer. ",
        h(
          "button",
          {
            class: "btn small",
            onclick: () => tts.speak("This is how reading aloud will sound in Readhold.", { rate: s.tts_rate, voice: s.tts_voice, onWord: () => undefined, onEnd: () => undefined }),
          },
          "Test voice",
        ),
      ),
      ),
      h("div", { class: "isle set-block", id: "set-review" },
      h("h2", null, "Review"),
      field("Daily review cap (cards)", num(s.review_cap, 5, 200, 5, (v) => set({ review_cap: v }))),
      ),
      aiSettingsBlock(),
      h("div", { class: "isle set-block", id: "set-data" },
      h("h2", null, "Your data"),
      h("p", { class: "muted small" }, "Everything is saved the moment you make it, in data/readhold.db. A backup is made every day (last 14 kept) and before every update to the database. Readhold sends nothing anywhere by itself; the only connection it can make is to the AI model you chose, and only while AI is switched on."),
      h(
        "div",
        { class: "row" },
        h(
          "button",
          {
            class: "btn",
            onclick: async () => {
              const r = await api.post<{ path: string }>("/api/export/all");
              toast(`Exported to ${r.path} (plus a Markdown note per document)`, "ok", 8000);
            },
          },
          "Export everything (JSON + Markdown)",
        ),
        h(
          "button",
          {
            class: "btn",
            onclick: async () => {
              const r = await api.post<{ path: string }>("/api/backup");
              toast(`Backup saved: ${r.path}`, "ok", 8000);
            },
          },
          "Back up now",
        ),
      ),
      ),
    ),
  );
  const jump = params?.get("g"); // a link straight to one group, like the AI chip in the menu
  if (jump) document.getElementById(jump)?.scrollIntoView({ block: "start" });
}

function field(label: string, control: HTMLElement): HTMLElement {
  return h("label", { class: "field" }, h("span", null, label), control);
}

// ------------------------------------------------------------------ fix the structure
export async function structureView(root: HTMLElement, docId: string): Promise<void> {
  const doc = await api.get<Doc>(`/api/documents/${docId}?touch=false`);
  const kinds = Object.keys(KIND_LABELS);
  const reload = async () => {
    clear(root);
    await structureView(root, docId);
  };
  root.append(
    h(
      "section",
      { class: "structure" },
      h("div", { class: "isle page-head" },
        h("div", { class: "row between" }, h("a", { class: "btn ghost", href: `#/read/${docId}` }, "← Back to reading"), h("span", { class: "muted small" }, "Merge, split or rename sections when an import comes out messy.")),
        h("h1", null, "Fix structure: ", doc.title),
        doc.import_warning ? h("p", { class: "import-warning" }, doc.import_warning) : null),
      doc.sections.map((sec, i) => {
        const title = h("input", { type: "text", value: sec.title, "aria-label": "Section title" });
        title.addEventListener("change", () => api.patch(`/api/sections/${sec.id}`, { title: title.value }).then(() => toast("Renamed", "ok")));
        const kind = h("select", { "aria-label": "Section type", onchange: (e: Event) => api.patch(`/api/sections/${sec.id}`, { kind: (e.target as HTMLSelectElement).value }).then(() => toast("Type changed", "ok")) }, kinds.map((k) => h("option", { value: k }, KIND_LABELS[k])));
        kind.value = sec.kind;
        return h(
          "div",
          { class: "struct-sec" },
          h(
            "div",
            { class: "row wrap" },
            title,
            kind,
            h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!sec.background, onchange: (e: Event) => api.patch(`/api/sections/${sec.id}`, { background: (e.target as HTMLInputElement).checked }) }), " skippable"),
            h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!sec.hidden, onchange: (e: Event) => api.patch(`/api/sections/${sec.id}`, { hidden: (e.target as HTMLInputElement).checked }) }), " hidden in clean view"),
            i > 0 ? h("button", { class: "btn small", onclick: () => api.post(`/api/sections/${sec.id}/merge-up`).then(reload) }, "Merge into previous") : null,
          ),
          h(
            "ol",
            { class: "struct-pars" },
            sec.paragraphs.map((p, j) =>
              h(
                "li",
                null,
                h("span", { class: `muted small kind` }, p.kind),
                " ",
                p.sentences.map((s) => s.text).join(" ").slice(0, 160),
                j > 0
                  ? h(
                      "button",
                      {
                        class: "btn small ghost",
                        onclick: async () => {
                          const t = await askText("New section", "Title for the section that starts here", "");
                          if (t === null) return;
                          await api.post(`/api/paragraphs/${p.id}/split`, { title: t || "New section" });
                          reload();
                        },
                      },
                      "Start section here",
                    )
                  : null,
              ),
            ),
          ),
        );
      }),
    ),
  );
}
