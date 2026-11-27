// Overview: every feature on one page, and the page the app opens on.
// - The header says what is next (one thing) and shows how today is going.
// - Below it, one card per feature in the same three groups as the menu (Do, Learn, Reflect). A card shows
//   where that feature stands and lets you do its most common thing right here (tick a task, start a timer,
//   add a line to today's note, save an idea, tick a routine step), with a link to the full page for the rest.
// One call (GET /api/hub) fills it; everything is local. All text is drawn with text nodes.
import { api } from "../api";
import { openCapture } from "../capture";
import { openPalette } from "../palette";
import { saveSettings, state } from "../state";
import { timer } from "../timer";
import type { HubData, ThinkData, Todo } from "../types";
import { clear, fmtClock, h, isTyping, keepTyped, toast } from "../util";
import { parseQuick, ymd } from "./plan";

type Group = "do" | "learn" | "reflect";
const SLOT_ICON: Record<string, string> = { morning: "🌤️", day: "☀️", evening: "🌙" };
const WEATHER: Record<string, string> = { sunny: "☀️", bright: "🌤️", cloudy: "☁️", rainy: "🌧️", stormy: "⛈️" };
const KIND_WORD: Record<string, string> = { focus: "Focus", break: "Break", stopwatch: "Stopwatch" };

const fromYmd = (day: string): Date => {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;
function greeting(): string {
  const hour = new Date().getHours();
  return hour < 5 ? "Still up" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}
/** a thin bar that shows a part of a whole */
const bar = (part: number, label: string): HTMLElement =>
  h("div", { class: "hub-bar", role: "img", "aria-label": label }, h("span", { style: { width: `${Math.round(Math.max(0, Math.min(1, part)) * 100)}%` } }));

export async function hubView(root: HTMLElement): Promise<() => void> {
  let data = await api.get<HubData>("/api/hub");
  const page = h("section", { class: "hub" });
  root.append(page);
  let clocks: HTMLElement[] = [];
  const simple = (): boolean => !!state.settings.simple_mode;

  /** after a quick action: fresh numbers, and the box you were typing in keeps the caret */
  const reload = async (focus?: string) => {
    data = await api.get<HubData>("/api/hub");
    render();
    if (focus) page.querySelector<HTMLInputElement>(focus)?.focus();
  };
  const card = (group: Group, icon: string, title: string, href: string | null, cls: string, ...kids: (HTMLElement | null)[]): HTMLElement =>
    h("div", { class: `isle hub-card g-${group} ${cls}` },
      h("div", { class: "hub-card-head" },
        h("span", { class: "hub-ico", "aria-hidden": "true" }, icon),
        h("h3", null, title),
        href ? h("a", { class: "hub-open", href, title: `Open ${title}`, "aria-label": `Open ${title}` }, "→") : null),
      kids);
  const quickBox = (cls: string, placeholder: string, label: string, run: (text: string) => Promise<void>): HTMLElement => {
    const input = h("input", { type: "text", class: `hub-input ${cls}`, maxlength: 500, placeholder, "aria-label": label });
    input.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !input.value.trim()) return;
      const text = input.value.trim();
      input.value = "";
      try {
        await run(text);
      } catch (err) {
        input.value = text; // nothing is lost when it could not be saved
        toast((err as Error).message, "error");
      }
    });
    return input;
  };
  const links = (...items: [string, string][]): HTMLElement => h("div", { class: "hub-links" }, items.map(([label, href]) => h("a", { href }, label)));
  const empty = (text: string): HTMLElement => h("p", { class: "hub-empty" }, text);
  const clock = (): HTMLElement => {
    const el = h("span", { class: "hub-clock", "aria-live": "off" }, `${timer.over && timer.run?.planned_ms ? "+" : ""}${fmtClock(Math.abs(timer.shown()))}`);
    clocks.push(el);
    return el;
  };
  const focusOn = async (t: HubData["tasks"][number]) => {
    if (timer.run?.todo_id === t.id) return;
    await timer.start({ kind: "focus", minutes: t.minutes, todo_id: t.id });
    render();
  };

  // ---------------------------------------------------------------- the header: one next thing, and how today is going
  const nextUp = (): HTMLElement => {
    const run = timer.run;
    const s = data.quest_step;
    const t = data.tasks[0];
    let kicker = "Nothing is waiting";
    let text: (string | HTMLElement)[] = ["Rest counts too. Or pick one small thing."];
    let action: HTMLElement = h("a", { class: "btn", href: "#/plan" }, "Open Plan");
    if (run) {
      kicker = run.running ? "Running now" : "Paused";
      text = [run.label || KIND_WORD[run.kind] || "Timer", " · ", clock()];
      action = h("a", { class: "btn primary", href: "#/timer" }, "Open the timer");
    } else if (s && !s.in_plan) {
      kicker = "Next step of your goal";
      text = [s.title];
      action = h("a", { class: "btn primary", href: `#/focus/${s.id}` }, `Start · ${s.minutes} min`);
    } else if (t) {
      kicker = t.priority ? "The one that matters today" : "First task for today";
      text = [t.text];
      action = h("button", { class: "btn primary", type: "button", onclick: () => void focusOn(t) }, `Focus · ${t.minutes} min`);
    } else if (data.review_due) {
      kicker = "Due for review";
      text = [`${plural(data.review_due, "card")} — a few minutes keeps what you learned`];
      action = h("a", { class: "btn primary", href: "#/review" }, "Review now");
    }
    return h("div", { class: "hub-next" }, h("div", { class: "hub-next-text" }, h("div", { class: "kicker" }, kicker), h("div", { class: "hub-next-title" }, text)), action);
  };

  const head = (): HTMLElement => {
    const total = data.tasks_done_today + data.tasks_now;
    const ring = h("div", { class: "hub-ring", role: "img", "aria-label": total ? `${data.tasks_done_today} of ${total} tasks done today` : "No tasks for today" },
      h("span", null, total ? `${data.tasks_done_today}/${total}` : "–"));
    ring.style.setProperty("--p", String(total ? Math.round((data.tasks_done_today / total) * 100) : 0));
    const pill = (value: string, label: string, href: string) => h("a", { class: "hub-pill", href }, h("strong", null, value), h("span", null, label));
    return h("header", { class: "isle hub-head" },
      h("div", { class: "hub-head-top" },
        h("div", { class: "hub-hello" },
          h("div", { class: "kicker" }, fromYmd(data.today).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })),
          h("h1", null, `${greeting()}.`)),
        h("div", { class: "hub-head-tools" },
          h("button", { class: "nav-find hub-find", type: "button", title: "Find anything (Ctrl+K)", onclick: () => void openPalette() }, h("span", null, "Find anything…"), h("kbd", null, "Ctrl K")),
          h("button", { class: "hub-settings", type: "button", "aria-pressed": String(simple()), title: simple() ? "Show every card and the whole menu" : "Show only what is next: tasks and the timer", onclick: async () => {
            await saveSettings({ simple_mode: !simple() });
            window.dispatchEvent(new HashChangeEvent("hashchange")); // the menu is drawn again too
          } }, h("span", { "aria-hidden": "true" }, simple() ? "▦" : "◻"), h("span", null, simple() ? "Show everything" : "Simple mode")),
          h("a", { class: "hub-settings", href: "#/settings", title: "Settings" }, h("span", { "aria-hidden": "true" }, "⚙"), h("span", null, "Settings")))),
      h("div", { class: "hub-head-main" },
        ring,
        nextUp()),
      h("div", { class: "hub-pills" },
        pill(String(data.tasks_now), data.tasks_now === 1 ? "task for today" : "tasks for today", "#/plan"),
        pill(String(data.focus_min), "min focused", "#/stats"),
        pill(String(data.review_due), data.review_due === 1 ? "card due" : "cards due", "#/review"),
        pill(`${data.routines.filter((r) => r.total && r.done >= r.total).length}/${data.routines.length}`, "routines done", "#/plan")));
  };

  // ---------------------------------------------------------------- Do
  const tasksPart = (): (HTMLElement | null)[] => {
    const add = quickBox("hub-task", "Add a task for today…   14:30  @tomorrow  #area  ~15  !", "New task", async (text) => {
      const q = parseQuick(text, data.today);
      if (!q.text) return;
      await api.post<Todo>("/api/todos", { text: q.text, minutes: q.minutes ?? 25, due: q.due ?? data.today, ...(q.repeat_rule ? { repeat_rule: q.repeat_rule } : {}), ...(q.priority ? { priority: 1 } : {}), ...(q.at ? { at: q.at } : {}), area: q.area ?? "" });
      await reload(".hub-task");
    });
    const more = data.tasks_now - data.tasks.length;
    return [
      add,
      data.tasks.length
        ? h("ul", { class: "hub-list" }, data.tasks.map((t) => h("li", { class: timer.run?.todo_id === t.id ? "is-active" : "" },
            h("button", { class: "task-check small", type: "button", "aria-label": `Mark “${t.text}” as done`, onclick: async () => {
              await api.patch<Todo>(`/api/todos/${t.id}`, { done: true });
              await reload();
            } }),
            h("span", { class: "grow", title: t.text }, t.priority ? h("span", { class: "task-star" }, "★ ") : null, t.text),
            t.at ? h("span", { class: "tchip due" }, t.at) : null,
            t.due && t.due < data.today ? h("span", { class: "tchip due carried" }, "carried") : null,
            h("span", { class: "tchip quiet" }, `${t.minutes} min`),
            h("button", { class: `task-btn ${timer.run?.todo_id === t.id ? "is-on" : ""}`, type: "button", title: `Focus on this for ${t.minutes} minutes`, "aria-label": `Start a focus timer on ${t.text}`, onclick: () => void focusOn(t) }, timer.run?.todo_id === t.id ? "●" : "▶"))))
        : empty(data.tasks_done_today ? "Today is clear. Rest counts too." : "Nothing for today yet. A task typed above lands on today."),
      h("p", { class: "hub-foot" }, [more > 0 ? `${more} more for today` : "", `${data.tasks_open} open in all`, data.tasks_done_today ? `${data.tasks_done_today} done today` : ""].filter(Boolean).join(" · ")),
      links(["All tasks", "#/plan"], ["This week as a board", "#/plan?view=week"])];
  };

  const goalPart = (): (HTMLElement | null)[] => {
    const q = data.quest;
    const s = data.quest_step;
    return [
      q
        ? h("div", { class: "hub-stack" },
            h("a", { href: `#/quest/${q.id}`, class: "hub-strong" }, q.title),
            q.steps ? bar(q.steps_done / q.steps, `${q.steps_done} of ${q.steps} steps done`) : null,
            h("span", { class: "hub-foot" }, q.steps ? `${q.steps_done} of ${q.steps} steps done` : "No steps written yet"))
        : empty("No goal yet. A goal gives your reading a job."),
      s ? h("div", { class: "hub-sub" }, h("div", { class: "grow" }, h("div", { class: "kicker" }, "Next step"), h("div", null, s.title)), h("a", { class: "btn small", href: `#/focus/${s.id}` }, "Start")) : null,
      links(["Today", "#/home"], q ? ["The goal", `#/quest/${q.id}`] : ["New goal", "#/quest"], ["All goals", "#/quest"])];
  };

  // Plan is one page with two tabs; the card shows both. In simple mode it is the tasks alone.
  const planCard = (alone = false): HTMLElement =>
    alone
      ? card("do", "☑️", "Plan", "#/plan", "wide tall", ...tasksPart())
      : card("do", "☑️", "Plan", "#/plan", "merged",
          h("div", { class: "hub-parts two plan" }, part("Tasks", "#/plan", ...tasksPart()), part("Today", "#/home", ...goalPart())));

  const timerCard = (): HTMLElement => {
    const run = timer.run;
    const start = (kind: "focus" | "break" | "stopwatch", minutes: number, label: string) => h("button", { class: "hub-preset", type: "button", onclick: async () => {
      await timer.start(kind === "stopwatch" ? { kind } : { kind, minutes });
      render();
    } }, label);
    return card("do", "⏱️", "Timer", "#/timer", "",
      run
        ? h("div", { class: "hub-stack" },
            h("div", { class: "kicker" }, `${KIND_WORD[run.kind] ?? "Timer"}${run.label && run.label !== KIND_WORD[run.kind] ? ` · ${run.label}` : ""}${run.running ? "" : " · paused"}`),
            h("div", { class: "hub-big" }, clock()),
            h("div", { class: "hub-row" },
              h("button", { class: "btn small", type: "button", onclick: async () => {
                await timer.toggle();
                render();
              } }, run.running ? "Pause" : "Resume"),
              h("a", { class: "btn small ghost", href: "#/timer" }, "Stop or change it")))
        : h("div", { class: "hub-presets" }, start("focus", 25, "25 min"), start("focus", 50, "50 min"), start("break", 5, "Break 5"), start("stopwatch", 0, "Stopwatch")),
      h("p", { class: "hub-foot" }, `${data.focus_min} min focused today`));
  };

  const routineCard = (): HTMLElement =>
    card("do", "🌤️", "Routines", "#/plan", "",
      data.routines.length
        ? h("ul", { class: "hub-list tall" }, data.routines.map((r) => h("li", null,
            h("span", { class: "hub-slot", "aria-hidden": "true" }, SLOT_ICON[r.slot] ?? "•"),
            h("div", { class: "grow hub-stack" },
              h("span", null, r.title, h("span", { class: "hub-foot" }, ` · ${r.done} of ${r.total}`)),
              r.total ? bar(r.done / r.total, `${r.done} of ${r.total} steps done`) : null,
              h("span", { class: "hub-foot" }, r.next ? `Next: ${r.next.text}` : "Done for today")),
            r.next ? h("button", { class: "task-check small", type: "button", title: `Tick “${r.next.text}”`, "aria-label": `Mark “${r.next.text}” as done`, onclick: async () => {
              await api.post(`/api/routines/${r.id}/steps/${r.next!.id}/check`, { done: true });
              await reload();
            } }) : h("span", { class: "task-check small is-done", "aria-hidden": "true" }, "✓"))))
        : empty("No routine for today. A routine is a short list you do in the same order every day."),
      links(["Run or edit a routine", "#/plan"]));

  // ---------------------------------------------------------------- Learn
  /** one tab of a merged card: its name (a link to the tab) and what is in it right now */
  const part = (title: string, href: string, ...kids: (HTMLElement | null)[]): HTMLElement =>
    h("div", { class: "hub-part" }, h("a", { class: "hub-part-title", href, title: `Open ${title}` }, h("span", null, title), h("span", { "aria-hidden": "true" }, "→")), kids);

  // Study is one page with five tabs (Lectures, Documents, Goals, Review, Glossary); the card shows each of them
  const libraryCard = (): HTMLElement => {
    const q = data.quest;
    return card("learn", "📚", "Study", "#/lectures", "merged",
      h("div", { class: "hub-parts two" },
        part("Lectures", "#/lectures",
          data.lectures.length
            ? h("ul", { class: "hub-list" }, data.lectures.map((l) => h("li", null,
                h("a", { class: "grow hub-title", href: `#/lecture/${l.id}` }, l.title),
                h("span", { class: "tchip quiet" }, l.pages > 1 ? `page ${l.position + 1} of ${l.pages}` : l.kind))))
            : empty("No slides or notebooks yet."),
          links(["Open the shelf", "#/lectures"])),
        part("Documents", "#/library",
          data.documents.length
            ? h("ul", { class: "hub-list tall" }, data.documents.map((d) => {
                const read = d.total_sentences ? Math.min(1, d.position / d.total_sentences) : 0;
                return h("li", null, h("div", { class: "grow hub-stack" },
                  h("a", { class: "hub-title", href: `#/read/${d.id}`, title: "Continue where you stopped" }, d.title),
                  bar(read, `${Math.round(read * 100)}% read`)),
                  h("span", { class: "tchip quiet" }, `${Math.round(read * 100)}%`));
              }))
            : empty(data.documents_total ? "Everything is finished. Import something new." : "Nothing imported yet."),
          links(["Import or browse", "#/library"]))),
      h("div", { class: "hub-parts three" },
        part("Goals", "#/quest",
          q ? h("a", { class: "hub-title", href: `#/quest/${q.id}`, title: "Your main goal" }, q.title) : h("span", { class: "hub-foot" }, "No main goal yet."),
          h("span", { class: "hub-foot" }, q ? (q.steps ? `${q.steps_done} of ${q.steps} steps done` : "No steps written yet") : "A goal gives your reading a job.")),
        part("Review", "#/review",
          h("div", { class: "hub-row" },
            h("span", { class: "grow" }, data.review_due ? `${plural(data.review_due, "card")} due` : "Nothing due"),
            data.review_due ? h("a", { class: "btn small primary", href: "#/review" }, "Review now") : h("a", { class: "btn small", href: "#/practice", title: "A short set mixing your topics, any time" }, "Practice"))),
        part("Glossary", "#/glossary",
          h("div", { class: "hub-row" },
            h("span", { class: "grow" }, `${plural(data.terms_total, "term")} saved`),
            h("a", { class: "btn small", href: "#/glossary" }, "Browse")))));
  };

  // ---------------------------------------------------------------- Reflect
  // Think asks for its own data, so the page never waits for it
  let think: ThinkData | null = null;
  void api.get<ThinkData>(`/api/think?day=${ymd(new Date())}`).then((t) => {
    think = t;
    render();
  }, () => undefined);

  // Notes is one page with four tabs; the card shows each of them
  const notesCard = (): HTMLElement => {
    const j = data.journal;
    const first = think?.picks.find((x) => x.status !== "opened") ?? think?.picks[0];
    return card("reflect", "📝", "Notes", "#/notes", "merged",
      h("div", { class: "hub-parts four" },
        part("All notes", "#/notes",
          quickBox("hub-note", "A line for today's note…", "Add a line to today's note", async (text) => {
            await api.post("/api/pages/capture", { text, day: ymd(new Date()) });
            toast("Added to today's note.", "ok", 2500);
            await reload(".hub-note");
          }),
          data.notes.length
            ? h("ul", { class: "hub-list" }, data.notes.slice(0, 4).map((n) => h("li", null, h("a", { class: "grow hub-title", href: `#/notes/${n.id}` },
                n.daily ? (n.daily === data.today ? "Today's note" : fromYmd(n.daily).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })) : n.title),
                n.daily ? h("span", { class: "tchip quiet" }, "daily") : null)))
            : empty("No notes yet."),
          links(["Today's note", "#/notes/today"], ["Table", "#/notes/table"], ["Map", "#/notes/map"])),
        part("Journal", "#/journal",
          h("div", { class: "hub-number" },
            h("span", { class: "hub-big", "aria-hidden": "true" }, (j && WEATHER[j.weather]) || "🖊️"),
            h("span", null, j ? (j.written ? "Today's page is started." : "Weather chosen. The page is still empty.") : "Today's page is not written yet.")),
          h("div", { class: "hub-row" }, h("a", { class: "btn small", href: "#/journal" }, j?.written ? "Continue writing" : "Write today's page"))),
        part("Ideas", "#/ideas",
          quickBox("hub-idea", "Catch an idea…", "Save an idea", async (text) => {
            await api.post("/api/ideas", { text });
            await reload(".hub-idea");
          }),
          data.ideas.length ? h("ul", { class: "hub-list" }, data.ideas.map((i) => h("li", null, h("span", { class: "grow", title: i.text }, i.text)))) : empty("Nothing caught yet."),
          h("p", { class: "hub-foot" }, `${data.ideas_total} in the inbox`)),
        part("Think", "#/think",
          first
            ? h("div", { class: "hub-stack" },
                h("div", { class: "kicker" }, "An idea for today"),
                h("a", { class: "hub-strong", href: `#/think/${first.kind}/${first.item_id}` }, first.title),
                h("span", { class: "hub-foot" }, first.reason))
            : empty(think ? "Nothing to bring back today." : "Looking through your notes…"),
          h("p", { class: "hub-foot" }, think ? `${plural(think.picks.length, "idea")} for today · ${plural(think.suggestions.length, "suggestion")} to approve` : ""),
          h("div", { class: "hub-row" },
            h("button", { class: "btn small", type: "button", title: "Capture a thought (Ctrl+J)", onclick: () => void openCapture() }, "+ Capture"),
            think?.suggestions.length ? h("a", { class: "btn small", href: "#/think" }, "Review suggestions") : null))));
  };

  const staminaCard = (): HTMLElement => {
    const top = Math.max(10, ...data.focus_week.map((d) => d.min));
    return card("reflect", "📈", "Stamina", "#/stats", "",
      h("div", { class: "hub-spark", role: "img", "aria-label": `Minutes focused on each of the last seven days: ${data.focus_week.map((d) => d.min).join(", ")}` },
        data.focus_week.map((d) => h("div", { class: `hub-spark-day ${d.day === data.today ? "is-today" : ""}`, title: `${fromYmd(d.day).toLocaleDateString(undefined, { weekday: "long" })}: ${d.min} min` },
          h("span", { style: { height: `${Math.max(4, Math.round((d.min / top) * 100))}%` } }),
          h("small", null, fromYmd(d.day).toLocaleDateString(undefined, { weekday: "narrow" }))))),
      h("p", { class: "hub-foot" }, `${data.focus_min} min focused today · ${plural(data.tasks_done_today, "task")} done today · ${data.done_week} this week`),
      links(["Weekly review", "#/stats"]));
  };

  // ---------------------------------------------------------------- assemble
  const section = (label: string, hint: string, cls: string, ...cards: HTMLElement[]): HTMLElement =>
    h("section", { class: "hub-group", "aria-label": label },
      h("h2", { class: "hub-section" }, h("span", null, label), h("small", null, hint)),
      h("div", { class: `hub-grid ${cls}` }, cards));
  const render = () => keepTyped(page, () => { // a redraw (a timer started, a quick action finished) keeps the text in the other boxes
    clocks = [];
    clear(page);
    if (simple()) {
      // simple mode: the one next thing, today's tasks and the timer. Everything else is one click away.
      page.append(head(), h("div", { class: "hub-grid simple" }, planCard(true), timerCard()),
        h("p", { class: "isle hub-simple-note" }, "Simple mode shows only what is next. Every other page is in the menu."));
      return;
    }
    page.append(
      head(),
      section("Do", "what is for now", "do", planCard(), timerCard(), routineCard()),
      section("Learn", "what you study", "learn", libraryCard()),
      section("Reflect", "what you keep", "reflect", notesCard(), staminaCard()));
  });

  // the clocks move once a second; the page is not drawn again for that
  const tick = window.setInterval(() => {
    if (!timer.run) return;
    const text = `${timer.over && timer.run.planned_ms ? "+" : ""}${fmtClock(Math.abs(timer.shown()))}`;
    for (const c of clocks) c.textContent = text;
  }, 1000);
  let lastRun = timer.run?.id ?? "";
  const off = timer.on(() => {
    const now = timer.run?.id ?? "";
    if (now === lastRun) return;
    lastRun = now; // a timer started or ended: the cards that show it follow
    if (!document.querySelector(".modal-back")) void reload();
  });
  const onKey = (e: KeyboardEvent) => {
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key.toLowerCase() === "n") (e.preventDefault(), page.querySelector<HTMLInputElement>(".hub-task")?.focus());
  };
  document.addEventListener("keydown", onKey);
  render();
  return () => {
    clearInterval(tick);
    off();
    document.removeEventListener("keydown", onKey);
  };
}
