// Plan: the tasks of your days and the small routines that hold them together.
// - Tasks are the Timer page's to-dos with a day, a repeat rule and a life area. Type one line to add:
//   "Call the dentist @tomorrow #health ~10". A task whose day has passed is carried over, never "late".
// - Routines are short checklists for the morning, the day or the evening. They start fresh every day, and
//   "Run" walks you through one step at a time.
// - A task can be starred as "the one that matters" (! in the quick line) and can hold a few small steps.
// - "Week" shows the next seven days as a board: drag a task to another day, or use its ‹ › buttons.
// - A routine can be for some days of the week only; on its other days it rests.
// The tone is on purpose: small wins are shown, nothing is red, and moving a task to tomorrow is one tap.
import { planHead } from "./libtabs";
import { planChatDialog } from "./planchat";
import { readingPlanDialog } from "./readplan";
import { tidyRoutineDialog, tidyTasksDialog } from "./tidy";
import { api } from "../api";
import { chime, linkHref, timer } from "../timer";
import type { PlanData, Routine, Todo } from "../types";
import { clear, fmtClock, h, isTyping, keepTyped, type ModalHandle, modal, toast } from "../util";

type Repeat = Todo["repeat_rule"];
const REPEAT_BASE: Record<string, string> = { daily: "every day", weekdays: "on weekdays", weekly: "every week", monthly: "every month" };
const REPEAT_CHOICES = ["daily", "weekdays", "weekly", "monthly", "every:2", "every:3", "every:14"];
/** "weekly" → "every week", "every:3" → "every 3 days", "every:14" → "every 2 weeks" */
export function repeatLabel(rule: string): string {
  const n = Number(rule.match(/^every:(\d+)$/)?.[1] ?? 0);
  if (n) return n % 7 === 0 ? `every ${n / 7} weeks` : `every ${n} days`;
  return REPEAT_BASE[rule] ?? rule;
}
const SLOT_LABEL: Record<Routine["slot"], string> = { morning: "Morning", day: "During the day", evening: "Evening" };
const SLOT_ICON: Record<Routine["slot"], string> = { morning: "🌤️", day: "☀️", evening: "🌙" };
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // a routine's days: 0 = Monday
const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const STARTERS: { title: string; slot: Routine["slot"]; steps: string }[] = [
  { title: "Morning start", slot: "morning", steps: "A glass of water\nOpen the window ~1\nLook at today's plan ~2\nPick the one thing that matters" },
  { title: "Study warm-up", slot: "day", steps: "Clear the desk ~2\nPhone out of reach\nWrite the question I want answered\nStart a 2-minute timer" },
  { title: "Wind down", slot: "evening", steps: "Close the day in Readhold ~2\nSet out tomorrow's first task\nScreens off ~1\nRead a few pages" },
];

// ------------------------------------------------------------------ days (local, as YYYY-MM-DD)
const pad = (n: number) => String(n).padStart(2, "0");
export const ymd = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromYmd = (s: string): Date => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const addDays = (s: string, n: number): string => {
  const d = fromYmd(s);
  d.setDate(d.getDate() + n);
  return ymd(d);
};
const dayDiff = (a: string, b: string): number => Math.round((fromYmd(a).getTime() - fromYmd(b).getTime()) / 86_400_000);

function dueLabel(due: string, today: string): string {
  const n = dayDiff(due, today);
  if (n === 0) return "Today";
  if (n === 1) return "Tomorrow";
  if (n === -1) return "from yesterday";
  if (n < 0) return `from ${-n} days ago`;
  return fromYmd(due).toLocaleDateString(undefined, n < 7 ? { weekday: "long" } : { weekday: "short", day: "numeric", month: "short" });
}

/** "@tomorrow", "@fri", "@+3", "@2026-12-01" → a day. */
function parseDay(word: string, today: string): string | null {
  if (/^(today|tod)$/.test(word)) return today;
  if (/^(tomorrow|tmr|tom)$/.test(word)) return addDays(today, 1);
  if (/^\+\d{1,3}$/.test(word)) return addDays(today, Number(word.slice(1)));
  if (/^\d{4}-\d{2}-\d{2}$/.test(word) && !Number.isNaN(fromYmd(word).getTime())) return word;
  if (word.length >= 3) {
    const i = WEEKDAYS.findIndex((w) => w.startsWith(word));
    if (i >= 0) {
      const ahead = (i - fromYmd(today).getDay() + 7) % 7 || 7; // the next one, never today
      return addDays(today, ahead);
    }
  }
  return null;
}

/** "01234" → "Weekdays" */
function daysLabel(weekdays: string): string {
  if (!weekdays) return "";
  if (weekdays === "01234") return "Weekdays";
  if (weekdays === "56") return "Weekends";
  return weekdays.split("").map((d) => DAY_NAMES[Number(d)]).join(" ");
}
const fmtLoad = (min: number): string => (min < 60 ? `${min} min` : `${Math.floor(min / 60)} h${min % 60 ? ` ${min % 60}` : ""}`);

// the view you chose stays while the app is open
let lastView: "list" | "week" = "list";

export interface Quick {
  text: string;
  priority?: number;
  at?: string; // a time of day, "14:30"
  due?: string;
  repeat_rule?: Repeat;
  area?: string;
  minutes?: number;
}

/** One line into a task: words are the task; @day, a time (14:30), #area, *repeat, ~minutes and ! (it matters) are picked out. */
export function parseQuick(raw: string, today: string): Quick {
  const out: Quick = { text: "" };
  const words: string[] = [];
  for (const tok of raw.trim().split(/\s+/)) {
    const low = tok.toLowerCase();
    if (low.length > 1 && low.startsWith("#")) {
      const a = tok.slice(1).replace(/[_-]+/g, " ");
      out.area = a.charAt(0).toUpperCase() + a.slice(1);
    } else if (/^~\d{1,3}$/.test(low)) out.minutes = Math.max(1, Math.min(600, Number(low.slice(1))));
    else if (low === "!" || low === "!!") out.priority = 1;
    else if (low.startsWith("*") && REPEAT_WORDS[low.slice(1)]) out.repeat_rule = REPEAT_WORDS[low.slice(1)];
    else if (/^\*\d{1,3}[dw]$/.test(low) && Number(low.slice(1, -1)) * (low.endsWith("w") ? 7 : 1) >= 2 && Number(low.slice(1, -1)) * (low.endsWith("w") ? 7 : 1) <= 999) out.repeat_rule = `every:${Number(low.slice(1, -1)) * (low.endsWith("w") ? 7 : 1)}`; // *3d, *2w
    else if (/^@?([01]?\d|2[0-3]):[0-5]\d$/.test(low)) {
      const [hh, mm] = low.replace("@", "").split(":");
      out.at = `${hh.padStart(2, "0")}:${mm}`; // 9:05 or @14:30
    }
    else if (low.startsWith("@") && parseDay(low.slice(1), today)) out.due = parseDay(low.slice(1), today)!;
    else words.push(tok);
  }
  out.text = words.join(" ");
  return out;
}
const REPEAT_WORDS: Record<string, string> = { day: "daily", daily: "daily", weekdays: "weekdays", weekday: "weekdays", week: "weekly", weekly: "weekly", month: "monthly", monthly: "monthly" };

// ------------------------------------------------------------------ the page
export async function planView(root: HTMLElement, params?: URLSearchParams): Promise<() => void> {
  let data = await api.get<PlanData>("/api/plan");
  let area = ""; // the life area shown ("" = all)
  if (params?.get("view") === "week") lastView = "week";
  let view = lastView;
  const openItems = new Set<string>(); // the tasks whose small steps are showing
  const page = h("section", { class: "plan" });
  // milestone 3.1: spread the reading that is left over your days (code schedules; a model may suggest the order)
  // milestones 5.2 and 5.3: tidy messy tasks (code first, a model's rewrite on request); draft tasks by chatting with a model
  const readingBtn = () => h("span", { class: "row wrap plan-tools" },
    h("button", { type: "button", class: "btn small", title: "Spread what is left to read over your days, before a deadline", onclick: () => void readingPlanDialog(() => void reload()) }, "📚 Plan my reading"),
    h("button", { type: "button", class: "btn small", title: "What your tasks lack, fixes, and a model's rewrite if you ask", onclick: () => void tidyTasksDialog(() => void reload()) }, "✨ Tidy tasks"),
    h("button", { type: "button", class: "btn small", title: "Tell a model what you need; it drafts tasks, you choose what to add", onclick: () => void planChatDialog(() => void reload()) }, "💬 Plan with a model"));
  let tabs = planHead("tasks", readingBtn());
  root.append(tabs, page);

  const reload = async () => {
    data = await api.get<PlanData>("/api/plan");
    render();
  };
  const patch = async (t: Todo, body: Record<string, unknown>) => {
    await api.patch<Todo>(`/api/todos/${t.id}`, body);
    await reload();
  };
  const setTask = (fresh: Todo) => {
    data.tasks = data.tasks.map((x) => (x.id === fresh.id ? { ...x, ...fresh } : x));
  };
  const byStar = (list: Todo[]): Todo[] => [...list].sort((a, b) => (b.priority || 0) - (a.priority || 0) || (a.at || "99").localeCompare(b.at || "99")); // the one that matters, then by time; the rest keeps its order

  // ---------------------------------------------------------------- tasks
  const quickAdd = (): HTMLElement => {
    const input = h("input", { type: "text", class: "plan-add-input", maxlength: 500, placeholder: "Add a task…  e.g. Call the dentist @tomorrow #health ~10", "aria-label": "New task" });
    const preview = h("div", { class: "plan-add-preview", "aria-live": "polite" });
    const paint = () => {
      const q = parseQuick(input.value, data.today);
      clear(preview);
      if (!input.value.trim()) {
        preview.append(h("span", { class: "plan-tip" }, "@tomorrow or @fri for a day · 14:30 for a time · #home for an area · *daily or *3d to repeat · ~15 for minutes · ! if it matters"));
        return;
      }
      if (q.priority) preview.append(h("span", { class: "tchip star" }, "★ matters"));
      if (q.due) preview.append(h("span", { class: "tchip due" }, dueLabel(q.due, data.today)));
      if (q.at) preview.append(h("span", { class: "tchip due" }, `⏰ ${q.at}`));
      if (q.repeat_rule) preview.append(h("span", { class: "tchip" }, `↻ ${repeatLabel(q.repeat_rule)}`));
      if (q.area) preview.append(h("span", { class: "tchip area" }, q.area));
      if (q.minutes) preview.append(h("span", { class: "tchip" }, `${q.minutes} min`));
      if (!preview.childNodes.length) preview.append(h("span", { class: "plan-tip" }, "Enter adds it to Anytime. Add @today to put it on today."));
    };
    const add = async () => {
      const q = parseQuick(input.value, data.today);
      if (!q.text) return input.focus();
      await api.post<Todo>("/api/todos", { text: q.text, minutes: q.minutes ?? 25, ...(q.due ? { due: q.due } : {}), ...(q.repeat_rule ? { repeat_rule: q.repeat_rule } : {}), ...(q.priority ? { priority: 1 } : {}), ...(q.at ? { at: q.at } : {}), area: q.area ?? (area || "") });
      input.value = "";
      await reload();
      page.querySelector<HTMLInputElement>(".plan-add-input")?.focus();
    };
    input.addEventListener("input", paint);
    input.addEventListener("keydown", (e) => e.key === "Enter" && void add());
    paint();
    return h("div", { class: "plan-add" }, h("div", { class: "plan-add-row" }, input, h("button", { class: "btn primary", type: "button", onclick: () => void add() }, "Add")), preview);
  };

  const editTask = async (t: Todo) => {
    let handle: ModalHandle;
    const text = h("input", { type: "text", value: t.text, maxlength: 500, "aria-label": "Task", autofocus: true });
    const due = h("input", { type: "date", value: t.due ?? "", "aria-label": "Day" });
    const repeat = h("select", { "aria-label": "Repeat" }, h("option", { value: "" }, "Does not repeat"), [...new Set([...REPEAT_CHOICES, ...(t.repeat_rule ? [t.repeat_rule] : [])])].map((k) => h("option", { value: k }, `Repeats ${repeatLabel(k)}`)));
    const at = h("input", { type: "time", value: t.at ?? "", "aria-label": "Time of day" });
    repeat.value = t.repeat_rule;
    const areaIn = h("input", { type: "text", value: t.area, maxlength: 40, list: "plan-areas", placeholder: "Study, Home, Health…", "aria-label": "Area" });
    const mins = h("input", { type: "number", min: 1, max: 600, value: String(t.minutes), "aria-label": "Minutes" });
    const note = h("textarea", { rows: 3, maxlength: 2000, placeholder: "Anything you need to remember for it", "aria-label": "Note" }, t.note);
    const star = h("input", { type: "checkbox", checked: !!t.priority });
    const ok = () => handle.close("ok");
    text.addEventListener("keydown", (e) => e.key === "Enter" && ok());
    const res = await modal("Edit task", h("div", { class: "stack" },
      h("label", { class: "field" }, h("span", null, "Task"), text),
      h("div", { class: "grid2" },
        h("label", { class: "field" }, h("span", null, "Day (empty = anytime)"), due),
        h("label", { class: "field" }, h("span", null, "Time (optional; it reminds you)"), at),
        h("label", { class: "field" }, h("span", null, "Repeat"), repeat),
        h("label", { class: "field" }, h("span", null, "Area"), areaIn),
        h("label", { class: "field" }, h("span", null, "Minutes"), mins)),
      h("label", { class: "field" }, h("span", null, "Note"), note),
      h("label", { class: "toggle" }, star, " ★ This one matters (it is shown first)"),
      h("datalist", { id: "plan-areas" }, data.areas.map((a) => h("option", { value: a }))),
      h("div", { class: "row end" }, h("button", { type: "button", onclick: () => handle.close(null) }, "Cancel"), h("button", { class: "primary", type: "button", onclick: ok }, "Save"))), { onOpen: (m) => (handle = m) });
    if (res !== "ok" || !text.value.trim()) return;
    const m = Math.round(Number(mins.value));
    await patch(t, { text: text.value.trim(), priority: star.checked ? 1 : 0, at: at.value, repeat_rule: repeat.value, area: areaIn.value.trim(), note: note.value, ...(m >= 1 && m <= 600 ? { minutes: m } : {}), ...(due.value ? { due: due.value } : { clear_due: true }) });
  };

  /** the small steps inside a task */
  const itemsBox = (t: Todo): HTMLElement => {
    const items = t.items ?? [];
    const input = h("input", { type: "text", class: "task-items-add", "data-id": t.id, maxlength: 200, placeholder: items.length ? "Another small step…" : "The first small step… (Enter adds it)", "aria-label": `Add a small step to ${t.text}` });
    input.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !input.value.trim()) return;
      try {
        setTask(await api.post<Todo>(`/api/todos/${t.id}/items`, { text: input.value.trim() }));
      } catch (err) {
        return toast((err as Error).message, "info");
      }
      render();
      page.querySelector<HTMLInputElement>(`.task-items-add[data-id="${t.id}"]`)?.focus();
    });
    return h("div", { class: "task-items" },
      items.length ? h("ul", null, items.map((it) => h("li", { class: it.done ? "is-done" : "" },
        h("button", { class: `task-check small ${it.done ? "is-done" : ""}`, type: "button", "aria-label": it.done ? `Mark “${it.text}” as not done` : `Mark “${it.text}” as done`, onclick: async () => {
          setTask(await api.patch<Todo>(`/api/todos/${t.id}/items/${it.id}`, { done: !it.done }));
          const left = (data.tasks.find((x) => x.id === t.id)?.items ?? []).filter((i) => !i.done).length;
          if (!it.done && !left) toast("Every small step is done. Tick the task when you're ready.", "ok", 4000);
          render();
        } }, it.done ? "✓" : ""),
        h("span", { class: "task-item-text" }, it.text),
        h("button", { class: "task-btn ghost", type: "button", "aria-label": `Remove ${it.text}`, title: "Remove", onclick: async () => {
          setTask(await api.del<Todo>(`/api/todos/${t.id}/items/${it.id}`));
          render();
        } }, "✕")))) : null,
      input);
  };

  const taskRow = (t: Todo): HTMLElement => {
    const done = !!t.done_at;
    const items = t.items ?? [];
    const itemsDone = items.filter((i) => i.done).length;
    const expanded = openItems.has(t.id) && !done;
    const active = timer.run?.todo_id === t.id;
    const late = !done && !!t.due && t.due < data.today;
    const check = h("button", { class: `task-check ${done ? "is-done" : ""}`, type: "button", "aria-label": done ? `Mark “${t.text}” as not done` : `Mark “${t.text}” as done`, onclick: async () => {
      await api.patch<Todo>(`/api/todos/${t.id}`, { done: !done });
      const before = openToday().length;
      await reload();
      if (!done) {
        if (t.repeat_rule) toast(`Done. It comes back ${repeatLabel(t.repeat_rule)}.`, "ok", 3000);
        else if (before === 1 && !openToday().length) toast("Today is clear. Rest counts too.", "ok", 5000);
      }
    } }, done ? "✓" : "");
    const chips = h("div", { class: "task-chips" },
      t.due && !done ? h("span", { class: `tchip due ${late ? "carried" : ""}` }, dueLabel(t.due, data.today)) : null,
      t.at && !done ? h("span", { class: "tchip due", title: "It reminds you at this time while Readhold is open" }, `⏰ ${t.at}`) : null,
      t.repeat_rule ? h("span", { class: "tchip", title: `Repeats ${repeatLabel(t.repeat_rule)}` }, `↻ ${repeatLabel(t.repeat_rule)}`) : null,
      t.area ? h("button", { class: "tchip area", type: "button", title: `Show only ${t.area}`, onclick: () => ((area = area === t.area ? "" : t.area), render()) }, t.area) : null,
      h("span", { class: "tchip quiet" }, t.spent_ms >= 60_000 ? `${Math.round(t.spent_ms / 60_000)} / ${t.minutes} min` : `${t.minutes} min`),
      t.link_type && linkHref(t.link_type, t.link_id) ? h("a", { class: "tchip link", href: linkHref(t.link_type, t.link_id)! }, "↗ open") : null,
      t.note ? h("span", { class: "tchip quiet", title: t.note }, "✎ note") : null,
      done
        ? items.length ? h("span", { class: "tchip quiet" }, `☰ ${itemsDone}/${items.length}`) : null
        : h("button", { class: `tchip steps ${expanded ? "is-on" : ""}`, type: "button", "aria-expanded": String(expanded), title: items.length ? "Show or hide its small steps" : "Break it into small steps", onclick: () => {
            if (expanded) openItems.delete(t.id);
            else openItems.add(t.id);
            render();
            if (!expanded) page.querySelector<HTMLInputElement>(`.task-items-add[data-id="${t.id}"]`)?.focus();
          } }, items.length ? `☰ ${itemsDone}/${items.length}` : "☰ steps"));
    const title = h("button", { class: "task-text link", type: "button", title: "Edit", onclick: () => void editTask(t) }, t.priority ? h("span", { class: "task-star", title: "The one that matters" }, "★ ") : null, t.text);
    const actions = h("div", { class: "task-actions" });
    if (!done) {
      actions.append(h("button", { class: `task-btn ghost ${t.priority ? "is-star" : ""}`, type: "button", "aria-pressed": String(!!t.priority), title: t.priority ? "No longer the one that matters" : "Mark as the one that matters", "aria-label": `${t.priority ? "Unstar" : "Star"} ${t.text}`, onclick: () => void patch(t, { priority: t.priority ? 0 : 1 }) }, t.priority ? "★" : "☆"));
      actions.append(h("button", { class: `task-btn ${active ? "is-on" : ""}`, type: "button", title: active ? "Being timed now" : `Focus on this for ${t.minutes} minutes`, "aria-label": `Start a focus timer on ${t.text}`, onclick: async () => {
        if (active) return;
        await timer.start({ kind: "focus", minutes: Math.max(1, Math.round(t.minutes - t.spent_ms / 60_000)), todo_id: t.id });
        toast("Timer started. It is in the corner.", "ok", 2500);
        render();
      } }, active ? "●" : "▶"));
      if (late) actions.append(h("button", { class: "task-btn wide", type: "button", title: "Do it today", onclick: () => void patch(t, { due: data.today }) }, "Today"));
      if (!t.due || t.due <= data.today) actions.append(h("button", { class: "task-btn wide", type: "button", title: "Move to tomorrow, no guilt", onclick: () => void patch(t, { due: addDays(data.today, 1) }) }, "Tomorrow"));
      else actions.append(h("button", { class: "task-btn wide", type: "button", title: "Pull into today", onclick: () => void patch(t, { due: data.today }) }, "Today"));
    }
    actions.append(h("button", { class: "task-btn ghost", type: "button", "aria-label": `Delete ${t.text}`, title: "Delete", onclick: async () => {
      await api.del(`/api/todos/${t.id}`);
      await reload();
      toast(`Deleted “${t.text}”.`, "info", 6000, { label: "Undo", run: async () => {
        await api.post(`/api/todos/${t.id}/restore`, {});
        await reload();
      } });
    } }, "✕"));
    return h("li", { class: `task ${done ? "is-done" : ""} ${active ? "is-active" : ""} ${t.priority && !done ? "is-star" : ""}` }, check, h("div", { class: "task-main" }, title, chips, expanded ? itemsBox(t) : null), actions);
  };

  /** the next step of your quest, shown with today's tasks so there is one place to look */
  const questRow = (): HTMLElement | null => {
    const q = data.quest_step;
    if (!q || q.in_plan || area) return null;
    return h("li", { class: "task quest-step" },
      h("span", { class: "quest-step-ico", "aria-hidden": "true" }, "🧭"),
      h("div", { class: "task-main" },
        h("a", { class: "task-text", href: `#/quest/${q.quest_id}`, title: "Open the goal" }, q.title),
        h("div", { class: "task-chips" }, h("span", { class: "tchip quiet" }, `Goal: ${q.quest_title}`), h("span", { class: "tchip quiet" }, `${q.minutes} min`))),
      h("div", { class: "task-actions" },
        h("a", { class: "task-btn wide", href: `#/focus/${q.id}`, title: "Start a focus session on this step" }, "▶ Start"),
        h("button", { class: "task-btn wide", type: "button", title: "Make it one of today's tasks", onclick: async () => {
          await api.post<Todo>("/api/todos", { text: q.title, minutes: Math.max(1, Math.min(600, q.minutes)), link_type: "step", link_id: q.id, due: data.today });
          await reload();
        } }, "+ Today")));
  };

  const shown = () => data.tasks.filter((t) => !area || t.area === area);
  const openToday = () => data.tasks.filter((t) => !t.done_at && t.due === data.today);

  /** cards that are due, shown with today's tasks */
  const reviewRow = (): HTMLElement | null => {
    if (!data.review_due || area) return null;
    return h("li", { class: "task quest-step" },
      h("span", { class: "quest-step-ico", "aria-hidden": "true" }, "🔁"),
      h("div", { class: "task-main" },
        h("a", { class: "task-text", href: "#/review" }, `${data.review_due} card${data.review_due === 1 ? "" : "s"} to review`),
        h("div", { class: "task-chips" }, h("span", { class: "tchip quiet" }, "Review · a few minutes keeps what you learned"))),
      h("div", { class: "task-actions" }, h("a", { class: "task-btn wide", href: "#/review" }, "▶ Review")));
  };

  const group = (title: string, tasks: Todo[], opts: { hint?: string; cls?: string; extra?: HTMLElement | null; first?: (HTMLElement | null)[] } = {}): HTMLElement | null => {
    const first = (opts.first ?? []).filter((x): x is HTMLElement => !!x);
    if (!tasks.length && !opts.hint && !first.length) return null;
    return h("div", { class: `plan-group ${opts.cls ?? ""}` },
      h("div", { class: "plan-group-head" }, h("h2", null, title), tasks.length ? h("span", { class: "plan-count" }, String(tasks.length)) : null, opts.extra ?? null),
      tasks.length || first.length ? h("ul", { class: "task-list" }, first, tasks.map(taskRow)) : h("p", { class: "plan-empty" }, opts.hint));
  };

  const areaChips = (): HTMLElement | null => data.areas.length
    ? h("div", { class: "plan-areas", role: "group", "aria-label": "Show an area" },
        h("button", { class: `tchip area ${area ? "" : "is-on"}`, type: "button", onclick: () => ((area = ""), render()) }, "All"),
        data.areas.map((a) => h("button", { class: `tchip area ${area === a ? "is-on" : ""}`, type: "button", onclick: () => ((area = area === a ? "" : a), render()) }, a)))
    : null;

  const renderTasks = (): HTMLElement => {
    const all = shown();
    const open = all.filter((t) => !t.done_at);
    const done = all.filter((t) => t.done_at);
    const carried = byStar(open.filter((t) => t.due && t.due < data.today));
    const today = byStar(open.filter((t) => t.due === data.today));
    const week = addDays(data.today, 7);
    const upcoming = open.filter((t) => t.due && t.due > data.today && t.due <= week).sort((a, b) => a.due!.localeCompare(b.due!));
    const later = open.filter((t) => t.due && t.due > week).sort((a, b) => a.due!.localeCompare(b.due!));
    const anytime = byStar(open.filter((t) => !t.due));
    const total = today.length + done.length;
    const meter = total ? h("div", { class: "plan-meter", role: "img", "aria-label": `${done.length} of ${total} done today` }, h("span", { style: { width: `${Math.round((done.length / total) * 100)}%` } })) : null;
    const lighten = today.length > 5
      ? h("div", { class: "plan-nudge" }, h("span", null, `${today.length} tasks today is a lot. Three done beats eight planned.`),
          h("button", { class: "btn small", type: "button", onclick: async () => {
            await Promise.all(today.slice(3).map((t) => api.patch(`/api/todos/${t.id}`, { due: addDays(data.today, 1) })));
            await reload();
            toast("Kept the top three. The rest wait for tomorrow.", "ok", 4000);
          } }, "Keep 3, move the rest to tomorrow"))
      : null;
    const box = h("div", { class: "plan-tasks" }, quickAdd());
    const chips = areaChips();
    if (chips) box.append(chips);
    const todayHint = done.length ? "Today is clear. Rest counts too." : anytime.length || carried.length ? "Nothing chosen for today yet. Press “Today” on a task below to bring it here." : "Add your first task above. One line is enough.";
    for (const el of [
      group("Carried over", carried, { cls: "carried", extra: h("span", { class: "plan-sub" }, "Not late. Just waiting. Pick today or tomorrow.") }),
      group("Today", today, { hint: todayHint, cls: "is-today", extra: meter, first: [questRow(), reviewRow()] }),
      lighten,
      group("Next 7 days", upcoming),
      group("Later", later),
      group("Anytime", anytime),
      group("Done today", done, { cls: "done" }),
    ]) if (el) box.append(el);
    return box;
  };

  // ---------------------------------------------------------------- the week as a board
  const renderWeek = (): HTMLElement => {
    const open = shown().filter((t) => !t.done_at);
    const days = Array.from({ length: 7 }, (_, i) => addDays(data.today, i));
    const move = async (id: string, due: string | null) => {
      const t = data.tasks.find((x) => x.id === id);
      if (!t || (t.due ?? null) === due) return;
      await patch(t, due ? { due } : { clear_due: true });
    };
    const zone = (el: HTMLElement, due: string | null) => {
      el.addEventListener("dragover", (e) => {
        e.preventDefault();
        el.classList.add("is-over");
      });
      el.addEventListener("dragleave", (e) => {
        if (!el.contains(e.relatedTarget as Node | null)) el.classList.remove("is-over");
      });
      el.addEventListener("drop", (e) => {
        e.preventDefault();
        el.classList.remove("is-over");
        const id = e.dataTransfer?.getData("text/plain");
        if (id) void move(id, due);
      });
    };
    const card = (t: Todo, day: string | null): HTMLElement => {
      const items = t.items ?? [];
      const el = h("li", { class: `wk-card ${t.priority ? "is-star" : ""} ${timer.run?.todo_id === t.id ? "is-active" : ""}`, draggable: "true", "data-id": t.id },
        h("button", { class: "task-check small", type: "button", "aria-label": `Mark “${t.text}” as done`, onclick: async () => {
          await api.patch<Todo>(`/api/todos/${t.id}`, { done: true });
          await reload();
          toast(t.repeat_rule ? `Done. It comes back ${repeatLabel(t.repeat_rule)}.` : "Done.", "ok", 2500);
        } }),
        h("div", { class: "wk-body" },
          h("button", { class: "wk-text link", type: "button", title: "Edit", onclick: () => void editTask(t) }, t.priority ? h("span", { class: "task-star" }, "★ ") : null, t.text),
          h("div", { class: "wk-meta" },
            t.at ? h("span", { class: "tchip due" }, t.at) : null,
            h("span", { class: "tchip quiet" }, `${t.minutes} min`),
            t.due && t.due < data.today ? h("span", { class: "tchip due carried" }, dueLabel(t.due, data.today)) : null,
            t.repeat_rule ? h("span", { class: "tchip quiet", title: `Repeats ${repeatLabel(t.repeat_rule)}` }, "↻") : null,
            items.length ? h("span", { class: "tchip quiet" }, `☰ ${items.filter((i) => i.done).length}/${items.length}`) : null,
            t.area ? h("span", { class: "tchip area" }, t.area) : null)),
        h("div", { class: "wk-move" },
          day && day > data.today ? h("button", { class: "task-btn ghost", type: "button", title: "A day earlier", "aria-label": `Move ${t.text} a day earlier`, onclick: () => void move(t.id, addDays(day, -1)) }, "‹") : null,
          h("button", { class: "task-btn ghost", type: "button", title: day ? "A day later" : "Put it on today", "aria-label": day ? `Move ${t.text} a day later` : `Put ${t.text} on today`, onclick: () => void move(t.id, day ? addDays(day, 1) : data.today) }, "›")));
      el.addEventListener("dragstart", (e) => {
        e.dataTransfer?.setData("text/plain", t.id);
        if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
        el.classList.add("is-drag");
      });
      el.addEventListener("dragend", () => el.classList.remove("is-drag"));
      return el;
    };
    const column = (day: string, i: number): HTMLElement => {
      const tasks = byStar(open.filter((t) => t.due === day));
      const mins = tasks.reduce((n, t) => n + t.minutes, 0);
      const d = fromYmd(day);
      const name = i === 0 ? "Today" : i === 1 ? "Tomorrow" : d.toLocaleDateString(undefined, { weekday: "long" });
      const add = h("input", { type: "text", class: "wk-add", "data-day": day, maxlength: 500, placeholder: "+ Add", "aria-label": `Add a task for ${name}` });
      add.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        const q = parseQuick(add.value, data.today);
        if (!q.text) return;
        await api.post<Todo>("/api/todos", { text: q.text, minutes: q.minutes ?? 25, due: day, ...(q.repeat_rule ? { repeat_rule: q.repeat_rule } : {}), ...(q.priority ? { priority: 1 } : {}), ...(q.at ? { at: q.at } : {}), area: q.area ?? (area || "") });
        await reload();
        page.querySelector<HTMLInputElement>(`.wk-add[data-day="${day}"]`)?.focus();
      });
      const full = mins > 300;
      const el = h("section", { class: `wk-col ${i === 0 ? "is-today" : ""}`, "aria-label": name },
        h("header", { class: "wk-head" },
          h("strong", null, name),
          h("span", { class: "muted small" }, d.toLocaleDateString(undefined, { day: "numeric", month: "short" })),
          tasks.length ? h("span", { class: "wk-load muted small" }, `${tasks.length} · ${fmtLoad(mins)}`) : null),
        h("ul", { class: "wk-list" }, i === 0 && questRowSmall() ? questRowSmall() : null, tasks.map((t) => card(t, day))),
        full ? h("p", { class: "wk-note" }, "A full day. Something can move.") : null,
        add);
      zone(el, day);
      return el;
    };
    const questRowSmall = (): HTMLElement | null => {
      const q = data.quest_step;
      if (!q || q.in_plan || area) return null;
      return h("li", { class: "wk-card quest-step" }, h("span", { "aria-hidden": "true" }, "🧭"),
        h("div", { class: "wk-body" }, h("a", { class: "wk-text", href: `#/focus/${q.id}`, title: "Start a focus session on this goal step" }, q.title), h("div", { class: "wk-meta" }, h("span", { class: "tchip quiet" }, `goal step · ${q.minutes} min`))));
    };
    const loose = byStar(open.filter((t) => !t.due || t.due < data.today));
    const later = open.filter((t) => t.due && t.due > days[6]).length;
    const tray = h("section", { class: "wk-tray", "aria-label": "No day yet" },
      h("header", { class: "wk-head" }, h("strong", null, "No day yet"), loose.length ? h("span", { class: "wk-load muted small" }, String(loose.length)) : null,
        h("span", { class: "muted small wk-tip" }, "Drag a task onto a day, or press › to put it on today.")),
      loose.length ? h("ul", { class: "wk-list tray" }, loose.map((t) => card(t, null))) : h("p", { class: "muted small wk-none" }, "Nothing is waiting. Drop a task here to take its day away."),
      later ? h("p", { class: "muted small wk-none" }, `${later} more after this week. They are in the List view.`) : null);
    zone(tray, null);
    return h("div", { class: "wk" }, tray, h("div", { class: "wk-board" }, days.map(column)));
  };

  // ---------------------------------------------------------------- routines
  const setRoutine = (r: Routine) => {
    data.routines = data.routines.map((x) => (x.id === r.id ? r : x));
  };
  const checkStep = async (r: Routine, stepId: string, done: boolean): Promise<Routine> => {
    const fresh = await api.post<Routine>(`/api/routines/${r.id}/steps/${stepId}/check`, { done });
    setRoutine(fresh);
    return fresh;
  };

  const parseSteps = (raw: string) => raw.split("\n").map((line) => {
    const m = line.trim().match(/^(.*?)(?:\s+~(\d{1,3}))?$/);
    return { text: (m?.[1] ?? "").replace(/^[-*]\s*/, "").trim().slice(0, 200), minutes: Math.min(240, Number(m?.[2] ?? 0)) };
  }).filter((s) => s.text);

  const editRoutine = async (r: Routine | null) => {
    let handle: ModalHandle;
    let slot: Routine["slot"] = r?.slot ?? "morning";
    const title = h("input", { type: "text", value: r?.title ?? "", maxlength: 120, placeholder: "Morning start", "aria-label": "Routine name", autofocus: true });
    const steps = h("textarea", { rows: 7, placeholder: "One small step per line.\nAdd ~2 at the end for a 2-minute timer.", "aria-label": "Steps" }, r ? r.steps.map((s) => (s.minutes ? `${s.text} ~${s.minutes}` : s.text)).join("\n") : "");
    const days = new Set<number>((r?.weekdays ?? "").split("").map(Number));
    const dayRow = h("div", { class: "pick-row days", role: "group", "aria-label": "Days of the week" });
    const paintDays = () => dayRow.querySelectorAll<HTMLButtonElement>("button[data-day]").forEach((b) => {
      const on = days.has(Number(b.dataset.day));
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    DAY_NAMES.forEach((n, i) => dayRow.append(h("button", { type: "button", class: "pick", "data-day": String(i), onclick: () => {
      if (days.has(i)) days.delete(i);
      else days.add(i);
      paintDays();
    } }, n)));
    dayRow.append(h("button", { type: "button", class: "link small", onclick: () => {
      days.clear();
      [0, 1, 2, 3, 4].forEach((d) => days.add(d));
      paintDays();
    } }, "weekdays"), h("button", { type: "button", class: "link small", onclick: () => (days.clear(), paintDays()) }, "every day"));
    paintDays();
    const slots = h("div", { class: "pick-row", role: "radiogroup", "aria-label": "Part of the day" });
    const paintSlots = () => slots.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.slot === slot);
      b.setAttribute("aria-checked", String(b.dataset.slot === slot));
    });
    (Object.keys(SLOT_LABEL) as Routine["slot"][]).forEach((s) => slots.append(h("button", { type: "button", class: "pick", role: "radio", "data-slot": s, onclick: () => ((slot = s), paintSlots()) }, `${SLOT_ICON[s]} ${SLOT_LABEL[s]}`)));
    paintSlots();
    const starters = r ? null : h("div", { class: "starter-chips" }, STARTERS.map((st) => h("button", { class: "chip", type: "button", onclick: () => {
      title.value = st.title;
      steps.value = st.steps;
      slot = st.slot;
      paintSlots();
    } }, st.title)));
    const res = await modal(r ? "Edit routine" : "New routine", h("div", { class: "stack" },
      r ? null : h("p", { class: "muted" }, "Keep it short. Four small steps you really do beat ten you skip."),
      starters,
      h("label", { class: "field" }, h("span", null, "Name"), title),
      h("div", { class: "field" }, h("span", null, "Part of the day"), slots),
      h("div", { class: "field" }, h("span", null, "Days (none picked = every day)"), dayRow),
      h("label", { class: "field" }, h("span", null, "Steps"), steps),
      h("div", { class: "row" },
        r ? h("button", { class: "ghost", type: "button", onclick: () => handle.close("delete") }, "Delete routine") : null,
        h("span", { class: "steady-write-gap" }),
        h("button", { type: "button", onclick: () => handle.close(null) }, "Cancel"),
        h("button", { class: "primary", type: "button", onclick: () => handle.close("ok") }, "Save"))), { onOpen: (m) => (handle = m) });
    if (res === "delete" && r) {
      await api.del(`/api/routines/${r.id}`);
      await reload();
      toast(`Deleted “${r.title}”.`, "info", 6000, { label: "Undo", run: async () => {
        await api.post(`/api/routines/${r.id}/restore`, {});
        await reload();
      } });
      return;
    }
    if (res !== "ok") return;
    const list = parseSteps(steps.value);
    if (!title.value.trim() || !list.length) return toast("A routine needs a name and at least one step.", "info");
    const weekdays = [...days].sort().join("");
    try {
      if (r) await api.patch(`/api/routines/${r.id}`, { title: title.value.trim(), slot, weekdays, steps: list });
      else await api.post("/api/routines", { title: title.value.trim(), slot, weekdays, steps: list });
    } catch (e) {
      return toast((e as Error).message, "error");
    }
    await reload();
  };

  /** One step at a time, full screen, with nothing else to look at. */
  const runRoutine = (start: Routine) => {
    let r = start;
    let tick = 0;
    let closed = false;
    const prevFocus = document.activeElement as HTMLElement | null;
    const stage = h("div", { class: "steady-stage routine-run" });
    const overlay = h("div", { class: "modal-back steady", role: "dialog", "aria-modal": "true", "aria-label": r.title },
      h("button", { class: "steady-x", type: "button", "aria-label": "Close", title: "Close (Esc)", onclick: () => close() }, "✕"), stage);
    const close = () => {
      if (closed) return;
      closed = true;
      clearInterval(tick);
      overlay.remove();
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("hashchange", close);
      prevFocus?.focus?.();
      render();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") (e.stopPropagation(), close());
    };
    const show = () => {
      clearInterval(tick);
      clear(stage);
      const i = r.steps.findIndex((s) => !s.done);
      const dots = h("div", { class: "steady-dots", role: "img", "aria-label": `${r.done} of ${r.steps.length} steps done` }, r.steps.map((s) => h("span", { class: s.done ? "done" : "" })));
      if (i < 0) {
        const back = h("button", { class: "btn primary big", type: "button", onclick: close }, "Close");
        stage.append(h("div", { class: "steady-orb rest", "aria-hidden": "true" }), h("h2", { class: "steady-title" }, `${r.title} is done.`), h("p", { class: "steady-sub" }, "Small things, done in order. That is how days hold together."), dots, back);
        back.focus();
        return;
      }
      const step = r.steps[i];
      const clock = h("div", { class: "steady-count" });
      if (step.minutes) {
        const ends = performance.now() + step.minutes * 60_000;
        let rang = false;
        const paint = () => {
          const left = ends - performance.now();
          clock.textContent = left > 0 ? fmtClock(left) : "Time's up, whenever you're ready.";
          if (left <= 0 && !rang) {
            rang = true;
            chime();
          }
        };
        paint();
        tick = window.setInterval(paint, 500);
      }
      const next = h("button", { class: "btn primary big", type: "button", onclick: async () => {
        r = await checkStep(r, step.id, true);
        show();
      } }, i === r.steps.length - 1 ? "Done" : "Done, next");
      stage.append(
        h("div", { class: "timer-kicker" }, `${r.title} · step ${i + 1} of ${r.steps.length}`),
        h("h2", { class: "steady-cue routine-step" }, step.text),
        clock,
        dots,
        h("div", { class: "steady-actions" }, next, h("button", { class: "btn ghost", type: "button", title: "Leave this one for today", onclick: () => {
          // skipped only on this screen: nothing is saved, so it is still open on the page
          r = { ...r, steps: r.steps.map((s) => (s.id === step.id ? { ...s, done: true } : s)) };
          show();
        } }, "Skip")));
      next.focus();
    };
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("hashchange", close);
    document.body.append(overlay);
    show();
  };

  const routineCard = (r: Routine): HTMLElement => {
    const all = r.steps.length > 0 && r.done >= r.steps.length;
    const missedYesterday = r.days.length >= 2 && r.days[r.days.length - 2].part === 0 && !r.days[r.days.length - 2].off && r.days.slice(0, -2).some((d) => d.part > 0) && r.done === 0;
    const edit = h("span", { class: "row" },
      h("button", { class: "task-btn ghost", type: "button", "aria-label": `Tidy ${r.title}`, title: "Tidy its steps", onclick: () => void tidyRoutineDialog(r, () => void reload()) }, "✨"),
      h("button", { class: "task-btn ghost", type: "button", "aria-label": `Edit ${r.title}`, title: "Edit", onclick: () => void editRoutine(r) }, "✎"));
    if (!r.on_today) {
      // not one of its days: it rests, and takes no room
      const back = r.next_on ? dueLabel(r.next_on, data.today).toLowerCase() : "";
      return h("div", { class: "routine is-off" },
        h("div", { class: "routine-head" },
          h("span", { class: "routine-ico", "aria-hidden": "true" }, SLOT_ICON[r.slot]),
          h("div", { class: "routine-title" }, h("strong", null, r.title), h("span", { class: "muted small" }, `Rests today${back ? ` · back ${back}` : ""}`)),
          edit));
    }
    const card = h("div", { class: `routine ${all ? "is-done" : ""}` },
      h("div", { class: "routine-head" },
        h("span", { class: "routine-ico", "aria-hidden": "true" }, SLOT_ICON[r.slot]),
        h("div", { class: "routine-title" }, h("strong", null, r.title), h("span", { class: "muted small" }, all ? "Done for today" : `${r.done} of ${r.steps.length}`, r.weekdays ? ` · ${daysLabel(r.weekdays)}` : "")),
        h("div", { class: "routine-days", role: "img", "aria-label": "The last seven days" }, r.days.map((d) => d.off
          ? h("span", { class: "off", title: `${d.day}: a rest day` })
          : h("span", { title: `${d.day}: ${Math.round(d.part * 100)}%`, style: { opacity: String(0.18 + d.part * 0.82) } }))),
        edit),
      h("ul", { class: "routine-steps" }, r.steps.map((s) => h("li", { class: s.done ? "is-done" : "" },
        h("button", { class: `task-check small ${s.done ? "is-done" : ""}`, type: "button", "aria-label": s.done ? `Mark “${s.text}” as not done` : `Mark “${s.text}” as done`, onclick: async () => {
          const fresh = await checkStep(r, s.id, !s.done);
          if (!s.done && fresh.done >= fresh.steps.length) toast(`${fresh.title} is done. Nicely held.`, "ok", 4000);
          render();
        } }, s.done ? "✓" : ""),
        h("span", { class: "routine-step-text" }, s.text),
        s.minutes ? h("span", { class: "tchip quiet" }, `${s.minutes} min`) : null))),
      missedYesterday ? h("p", { class: "routine-note" }, "Yesterday slipped by. That happens. Today brings it back.") : null,
      all ? null : h("button", { class: "btn small routine-run-btn", type: "button", onclick: () => runRoutine(r) }, r.done ? "Continue, one step at a time" : "Run it, one step at a time"));
    return card;
  };

  const renderRoutines = (): HTMLElement => {
    const box = h("aside", { class: "plan-routines", "aria-label": "Routines" },
      h("div", { class: "plan-group-head" }, h("h2", null, "Routines"), h("button", { class: "btn small", type: "button", onclick: () => void editRoutine(null) }, "+ New")));
    if (!data.routines.length) {
      box.append(h("div", { class: "plan-empty routines-empty" },
        h("p", null, "A routine is a short list you do in the same order every day, so you don't have to decide again each morning."),
        h("div", { class: "starter-chips" }, STARTERS.map((st) => h("button", { class: "chip", type: "button", onclick: async () => {
          await api.post("/api/routines", { title: st.title, slot: st.slot, steps: parseSteps(st.steps) });
          await reload();
          toast(`Added “${st.title}”. Change the steps to fit you.`, "ok", 4000);
        } }, `+ ${st.title}`)))));
      return box;
    }
    for (const r of data.routines) box.append(routineCard(r));
    return box;
  };

  // ---------------------------------------------------------------- assemble
  const render = () => keepTyped(page, () => { // the new-task box, a small-step box and the week's "+ Add" boxes keep their text
    clear(page);
    const fresh = planHead("tasks", readingBtn()); // the number on the tab follows what you tick and add
    tabs.replaceWith(fresh);
    tabs = fresh;
    const open = data.tasks.filter((t) => !t.done_at);
    const doneToday = data.tasks.filter((t) => t.done_at).length;
    const date = fromYmd(data.today).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    page.append(
      h("header", { class: "plan-head" },
        h("div", null, h("div", { class: "kicker" }, date), h("h1", null, "Tasks")),
        h("div", { class: "plan-head-side" },
          h("p", { class: "plan-summary" }, doneToday ? `${doneToday} done today` : "A fresh day", ` · ${open.length} open`, data.done_week ? ` · ${data.done_week} done this week` : ""),
          h("div", { class: "note-seg", role: "tablist", "aria-label": "How to show the plan" }, (["list", "week"] as const).map((v) =>
            h("button", { type: "button", role: "tab", class: `note-seg-btn ${view === v ? "is-on" : ""}`, "aria-selected": String(view === v), title: v === "list" ? "Tasks in groups, with your routines" : "The next seven days as a board", onclick: () => {
              view = lastView = v;
              render();
            } }, v === "list" ? "List" : "Week"))))),
      view === "week"
        ? h("div", { class: "plan-week" }, quickAdd(), areaChips(), renderWeek())
        : h("div", { class: "plan-grid" }, renderTasks(), renderRoutines()));
  });

  const onKey = (e: KeyboardEvent) => {
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key.toLowerCase() === "n") {
      e.preventDefault();
      page.querySelector<HTMLInputElement>(".plan-add-input")?.focus();
    }
  };
  document.addEventListener("keydown", onKey);
  const off = timer.on(() => {
    // a timer started or ended elsewhere: the "being timed" mark follows it
    const now = timer.run?.todo_id ?? "";
    if (now !== lastTimed) {
      lastTimed = now;
      if (!document.querySelector(".modal-back")) void reload();
    }
  });
  let lastTimed = timer.run?.todo_id ?? "";
  render();
  return () => {
    document.removeEventListener("keydown", onKey);
    off();
  };
}
