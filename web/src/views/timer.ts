// Timer page: a calm focus/break timer or stopwatch beside a to-do list whose tasks you can time.
// Everything here is optional to the rest of Readhold: link a task (or the timer) to a quest step, a
// lecture or notebook, or a library document; start it, open the linked thing, and the small floating timer
// keeps time while you work there.
import { api, save } from "../api";
import { saveSettings, state } from "../state";
import { linkHref, timer, type TimerData } from "../timer";
import { removeItem } from "../trash";
import type { LinkType, TimerKind, TimerLinks, TimerToday, Todo } from "../types";
import { clear, confirmBox, fmtClock, fmtMinutes, h, isTyping, toast } from "../util";

interface RecentRun { id: string; kind: TimerKind; label: string; elapsed_ms: number; status: string; started_at: string }

const PRESETS: Record<TimerKind, number[]> = { focus: [10, 15, 25, 45, 60], break: [3, 5, 10, 15], stopwatch: [] };
const KIND_LABEL: Record<TimerKind, string> = { focus: "Focus", break: "Break", stopwatch: "Stopwatch" };
const BREAK_IDEAS = [
  "Look at something far away for a while.",
  "Roll your shoulders and stretch your back.",
  "Drink a glass of water.",
  "Stand up and walk around the room.",
  "Close your eyes and listen for the furthest sound.",
  "Open a window for some fresh air.",
];
const R = 120; // ring radius in the SVG
const CIRC = 2 * Math.PI * R;

export async function timerView(root: HTMLElement): Promise<() => void> {
  let data: TimerData = await timer.load();
  let links: TimerLinks = { steps: [], lectures: [], documents: [] };
  try {
    links = await api.get<TimerLinks>("/api/timer/links");
  } catch {
    /* links are optional */
  }
  let kind: TimerKind = data.run?.kind ?? "focus";
  let minutes = kind === "break" ? 5 : 25;
  let label = "";
  let link = ""; // "type:id"
  const cleanups: (() => void)[] = [];

  const stage = h("div", { class: "timer-card" });
  const side = h("aside", { class: "todo-panel", "aria-label": "To-do" });
  root.append(h("section", { class: "timer-page" }, stage, side));

  // ---------------------------------------------------------------- linking (optional)
  const titleOf = (type: LinkType, id: string): string => {
    if (type === "step") return links.steps.find((s) => s.id === id)?.title ?? "A goal step";
    if (type === "lecture") return links.lectures.find((l) => l.id === id)?.title ?? "A lecture";
    if (type === "document") return links.documents.find((d) => d.id === id)?.title ?? "A document";
    return "";
  };
  const linkSelect = (value: string, onChange: (v: string) => void): HTMLSelectElement => {
    const sel = h("select", { class: "link-select", "aria-label": "Link to (optional)", onchange: (e: Event) => onChange((e.target as HTMLSelectElement).value) },
      h("option", { value: "" }, "No link"),
      links.steps.length ? h("optgroup", { label: "Goal steps" }, links.steps.map((s) => h("option", { value: `step:${s.id}` }, s.title))) : null,
      links.lectures.length ? h("optgroup", { label: "Lectures" }, links.lectures.map((l) => h("option", { value: `lecture:${l.id}` }, `${l.kind === "notebook" ? "📒" : "📄"} ${l.title}`))) : null,
      links.documents.length ? h("optgroup", { label: "Documents" }, links.documents.map((d) => h("option", { value: `document:${d.id}` }, d.title))) : null);
    sel.value = value;
    return sel;
  };
  const splitLink = (v: string): { link_type: LinkType; link_id: string } => {
    const [t, id] = v.split(":");
    return t && id ? { link_type: t as LinkType, link_id: id } : { link_type: "", link_id: "" };
  };
  const linkChip = (type: LinkType, id: string) => {
    const href = type ? linkHref(type, id) : null;
    if (!href) return null;
    const icon = type === "step" ? "🧭" : type === "lecture" ? "📒" : "📄";
    return h("a", { class: "link-chip", href, title: "Open it; the timer keeps running" }, h("span", { "aria-hidden": "true" }, `${icon} `), titleOf(type, id));
  };

  // ---------------------------------------------------------------- the timer
  const ringFg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  const ring = (() => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 280 280");
    svg.setAttribute("class", "timer-ring-svg");
    svg.setAttribute("aria-hidden", "true");
    const track = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    for (const c of [track, ringFg]) {
      c.setAttribute("cx", "140");
      c.setAttribute("cy", "140");
      c.setAttribute("r", String(R));
    }
    track.setAttribute("class", "ring-track");
    ringFg.setAttribute("class", "ring-fg");
    ringFg.setAttribute("stroke-dasharray", String(CIRC));
    ringFg.setAttribute("transform", "rotate(-90 140 140)");
    svg.append(track, ringFg);
    return svg;
  })();
  const timeEl = h("div", { class: "timer-time", role: "timer", "aria-live": "off" });
  const subEl = h("div", { class: "timer-sub" });
  const ringBox = h("div", { class: "timer-ring" }, ring, h("div", { class: "timer-center" }, timeEl, subEl));

  const paint = () => {
    const run = timer.run;
    if (run) {
      const shown = timer.shown();
      timeEl.textContent = `${timer.over && run.planned_ms ? "+" : ""}${fmtClock(Math.abs(shown))}`;
      const p = run.planned_ms ? timer.progress() : (timer.elapsed() % 3_600_000) / 3_600_000; // the stopwatch ring goes round once an hour
      ringFg.setAttribute("stroke-dashoffset", String(CIRC * (1 - p)));
      ringBox.classList.toggle("running", run.running);
      ringBox.classList.toggle("over", timer.over);
      subEl.textContent = !run.running ? "Paused" : timer.over ? (run.kind === "break" ? "Break's over" : "Time's up") : KIND_LABEL[run.kind];
    } else {
      timeEl.textContent = kind === "stopwatch" ? "0:00" : fmtClock(minutes * 60_000);
      ringFg.setAttribute("stroke-dashoffset", String(CIRC));
      ringBox.classList.remove("running", "over");
      subEl.textContent = kind === "stopwatch" ? "Counts up from zero" : `${minutes} minutes`;
    }
  };

  const finish = async (status: "done" | "stopped") => {
    const run = timer.run;
    if (!run) return;
    const took = timer.elapsed();
    const res = await timer.finish(status);
    if (res) {
      data = { ...data, run: null, today: res.today, todos: res.todos };
      renderTodos();
    }
    if (run.kind === "break") toast("Welcome back.", "ok", 2500);
    else if (status === "done") toast(took >= 60_000 ? `Nice. ${fmtMinutes(took)} of focus.` : "Done.", "ok");
    else toast(took >= 60_000 ? `Stopped after ${fmtMinutes(took)}. It still counts.` : "Stopped.", "info");
    if (run.kind === "focus" && status === "done" && state.settings.timer_rhythm) {
      kind = "break";
      minutes = 5;
      renderStage();
      toast("Time for a short break?", "info", 8000, { label: "Start 5-minute break", run: () => void timer.start({ kind: "break", minutes: 5 }) });
      return;
    }
    renderStage();
  };

  const renderStage = () => {
    clear(stage);
    const run = timer.run;
    if (run) {
      stage.className = `timer-card kind-${run.kind}`;
      const buttons = h("div", { class: "timer-actions" },
        h("button", { class: "btn primary", onclick: () => void timer.toggle() }, run.running ? "Pause" : "Resume"),
        run.planned_ms ? h("button", { class: "btn", title: "Five more minutes", onclick: () => void timer.extend(5) }, "+5 min") : null,
        h("button", { class: "btn", onclick: () => void finish("done") }, run.kind === "break" ? "End break" : "Done"),
        run.kind === "break" ? null : h("button", { class: "btn ghost", onclick: () => void finish("stopped") }, "Stop"));
      stage.append(
        h("div", { class: "timer-kicker" }, KIND_LABEL[run.kind]),
        h("h2", { class: "timer-label" }, run.label || KIND_LABEL[run.kind]),
        linkChip(run.link_type, run.link_id) ?? h("span", null),
        ringBox,
        buttons,
      );
      if (run.kind === "break") stage.append(h("p", { class: "break-idea" }, BREAK_IDEAS[Math.floor(Math.random() * BREAK_IDEAS.length)])); // one small idea for the break
      paint();
      return;
    }
    stage.className = `timer-card idle kind-${kind}`;
    const seg = h("div", { class: "seg", role: "tablist", "aria-label": "Timer kind" },
      (Object.keys(KIND_LABEL) as TimerKind[]).map((k) => h("button", { class: `seg-btn ${k === kind ? "on" : ""}`, role: "tab", "aria-selected": String(k === kind), onclick: () => {
        kind = k;
        minutes = k === "break" ? 5 : k === "focus" ? 25 : minutes;
        renderStage();
      } }, KIND_LABEL[k])));
    const presets = h("div", { class: "presets", role: "group", "aria-label": "Minutes" },
      PRESETS[kind].map((m) => h("button", { class: `preset ${m === minutes ? "on" : ""}`, onclick: () => ((minutes = m), renderStage()) }, `${m}`)),
      kind === "stopwatch" ? null : h("label", { class: "preset custom" }, h("input", { type: "number", min: 1, max: 600, value: String(minutes), "aria-label": "Custom minutes", onchange: (e: Event) => {
        const v = Math.round(Number((e.target as HTMLInputElement).value));
        if (v >= 1 && v <= 600) (minutes = v), renderStage(); // the Start button names the minutes
      } }), " min"));
    const what = h("input", { type: "text", class: "timer-what", placeholder: kind === "break" ? "Rest" : "What will you work on? (optional)", value: label, "aria-label": "What it's for",
      oninput: (e: Event) => (label = (e.target as HTMLInputElement).value) });
    const start = async () => {
      await timer.start({ kind, minutes, label: label.trim(), ...splitLink(link) });
      label = "";
      renderStage();
    };
    what.addEventListener("keydown", (e) => e.key === "Enter" && void start());
    const opt = (key: "timer_sound" | "timer_rhythm", text: string, title: string) =>
      h("label", { class: "timer-opt", title }, h("input", { type: "checkbox", checked: !!state.settings[key], onchange: (e: Event) => void saveSettings({ [key]: (e.target as HTMLInputElement).checked }) }), text);
    stage.append(
      seg,
      ringBox,
      presets,
      h("div", { class: "timer-form" }, what, kind === "break" ? null : linkSelect(link, (v) => (link = v))),
      h("div", { class: "timer-actions" }, h("button", { class: "btn primary big", onclick: () => void start() }, kind === "stopwatch" ? "Start the stopwatch" : `Start ${minutes} min`)),
      h("div", { class: "timer-opts" },
        opt("timer_sound", "Soft chime at the end", "A quiet two-note chime, never an alarm"),
        opt("timer_rhythm", "Offer a break after focus", "After Done, suggest a 5-minute break")),
    );
    paint();
  };

  // ---------------------------------------------------------------- to-do list
  let newLink = "";
  const renderTodos = () => {
    clear(side);
    const t: TimerToday = data.today;
    side.append(h("div", { class: "todo-head" },
      h("h2", null, "To-do", h("a", { class: "todo-plan-link", href: "#/plan", title: "Days, repeats, areas and routines" }, "Plan →")),
      h("span", { class: "todo-today", title: "Today, with the timer" }, `${fmtMinutes(t.focus_ms)} focused · ${t.todos_done} done`)));
    const text = h("input", { type: "text", placeholder: "Add a task…", "aria-label": "New task", maxlength: 500 });
    const mins = h("select", { "aria-label": "Estimated minutes" }, [5, 10, 15, 25, 45, 60, 90].map((m) => h("option", { value: String(m) }, `${m} min`)));
    mins.value = "25";
    const add = async () => {
      const v = text.value.trim();
      if (!v) return text.focus();
      const todo = await api.post<Todo>("/api/todos", { text: v, minutes: Number(mins.value), ...splitLink(newLink) });
      data.todos = [...data.todos.filter((x) => !x.done_at), todo, ...data.todos.filter((x) => x.done_at)];
      newLink = "";
      renderTodos();
      side.querySelector<HTMLInputElement>(".todo-add input[type=text]")?.focus();
    };
    text.addEventListener("keydown", (e) => e.key === "Enter" && void add());
    side.append(h("div", { class: "todo-add" }, text, h("div", { class: "row" }, mins, linkSelect(newLink, (v) => (newLink = v)), h("button", { class: "btn small primary", onclick: () => void add() }, "Add"))));

    const open = data.todos.filter((x) => !x.done_at);
    const done = data.todos.filter((x) => x.done_at);
    const list = h("ul", { class: "todo-list" });
    if (!open.length) list.append(h("li", { class: "todo-empty" }, done.length ? "All clear. Nicely done." : "Write down what you want to do, then press ▶ on a task to time it."));
    open.forEach((todo, i) => list.append(todoRow(todo, open, i)));
    side.append(list);
    if (done.length) {
      side.append(h("div", { class: "todo-done-head" }, "Done today"));
      const dl = h("ul", { class: "todo-list done" });
      done.forEach((todo) => dl.append(todoRow(todo, done, -1)));
      side.append(dl);
    }
    side.append(recent); // the same element each time, so it stays open or closed as you left it
  };

  // ---------------------------------------------------------------- recent focus sessions: each can be deleted, with Undo
  // A deleted run leaves Stamina, the streak, the journal's day story and its task's minutes; Undo brings it all back.
  const recentList = h("ul", { class: "recent-runs" });
  const recent = h("details", { class: "recent-focus" }, h("summary", null, "Recent focus sessions"), recentList);
  const freshToday = () => void api.get<TimerData>("/api/timer").then((d) => ((data = { ...data, today: d.today, todos: d.todos }), renderTodos()), () => undefined);
  const loadRecent = async () => {
    let runs: RecentRun[];
    try {
      runs = await api.get<RecentRun[]>("/api/timer/recent");
    } catch (e) {
      clear(recentList);
      recentList.append(h("li", { class: "muted small" }, `Not available: ${(e as Error).message}`));
      return;
    }
    clear(recentList);
    if (!runs.length) recentList.append(h("li", { class: "muted small" }, "No focus sessions in the last two weeks."));
    for (const r of runs) {
      const name = r.label || KIND_LABEL[r.kind];
      const when = new Date(r.started_at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      recentList.append(h("li", null,
        h("div", { class: "recent-main" }, h("span", { class: "recent-what" }, name), h("span", { class: "muted small" }, `${when} · ${fmtMinutes(r.elapsed_ms)}${r.status === "stopped" ? " · stopped early" : ""}`)),
        h("button", { class: "todo-del", "aria-label": `Delete the session ${name}`, title: "Delete: it stops counting in Stamina, the streak and the journal", onclick: () => void removeItem("focus", r.id, `Deleted “${name}”. It no longer counts in Stamina.`, {
          gone: () => (freshToday(), void loadRecent()),
          back: () => (freshToday(), void loadRecent()),
        }) }, "✕")));
    }
  };
  recent.addEventListener("toggle", () => {
    if (recent.open) void loadRecent();
  });

  const todoRow = (todo: Todo, siblings: Todo[], index: number): HTMLElement => {
    const active = timer.run?.todo_id === todo.id;
    const pct = Math.min(1, todo.spent_ms / (todo.minutes * 60_000));
    const check = h("button", { class: `todo-check ${todo.done_at ? "on" : ""}`, "aria-label": todo.done_at ? "Mark as not done" : "Mark as done", title: todo.done_at ? "Not done after all" : "Done", onclick: async () => {
      const fresh = await api.patch<Todo>(`/api/todos/${todo.id}`, { done: !todo.done_at });
      data.todos = data.todos.map((x) => (x.id === todo.id ? fresh : x));
      if (fresh.done_at) data.today = { ...data.today, todos_done: data.today.todos_done + 1 };
      else data.today = { ...data.today, todos_done: Math.max(0, data.today.todos_done - 1) };
      if (fresh.done_at && todo.link_type === "step") toast("The goal step is done too.", "ok", 2500);
      renderTodos();
    } }, todo.done_at ? "✓" : "");
    const textEl = h("span", { class: "todo-text", tabindex: 0, title: "Click to edit" }, todo.text);
    const edit = () => {
      if (todo.done_at) return;
      const input = h("input", { type: "text", value: todo.text, maxlength: 500, "aria-label": "Task" });
      const commit = async (keep: boolean) => {
        const v = input.value.trim();
        if (keep && v && v !== todo.text) {
          todo.text = v;
          await save("patch", `/api/todos/${todo.id}`, { text: v });
        }
        renderTodos();
      };
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") void commit(true);
        if (e.key === "Escape") void commit(false);
      });
      input.addEventListener("blur", () => void commit(true));
      textEl.replaceWith(input);
      input.focus();
      input.select();
    };
    textEl.addEventListener("click", edit);
    textEl.addEventListener("keydown", (e) => e.key === "Enter" && edit());
    const play = todo.done_at ? null : h("button", { class: `todo-play ${active ? "on" : ""}`, title: active ? "Being timed now" : `Focus on this for ${todo.minutes} minutes`, "aria-label": `Start a ${todo.minutes}-minute focus on ${todo.text}`, onclick: async () => {
      if (active) return;
      await timer.start({ kind: "focus", minutes: Math.max(1, Math.round(todo.minutes - todo.spent_ms / 60_000)), todo_id: todo.id });
      renderStage();
      renderTodos();
    } }, active ? "●" : "▶");
    const del = h("button", { class: "todo-del", "aria-label": "Delete task", title: "Delete", onclick: async () => {
      if (active && !(await confirmBox("Delete this task?", "It's being timed right now. The time you spent still counts.", "Delete"))) return;
      await api.del(`/api/todos/${todo.id}`);
      data.todos = data.todos.filter((x) => x.id !== todo.id);
      renderTodos();
      toast(`Deleted “${todo.text}”.`, "info", 6000, { label: "Undo", run: async () => {
        const back = await api.post<Todo>(`/api/todos/${todo.id}/restore`, {});
        data.todos = [...data.todos, back].sort((a, b) => Number(!!a.done_at) - Number(!!b.done_at) || a.ord - b.ord);
        renderTodos();
      } });
    } }, "✕");
    const li = h("li", { class: `todo ${todo.done_at ? "is-done" : ""} ${active ? "is-active" : ""}`, draggable: index >= 0 ? "true" : undefined },
      check,
      h("div", { class: "todo-main" },
        textEl,
        h("div", { class: "todo-meta" },
          h("span", { class: "todo-bar", "aria-hidden": "true" }, h("span", { style: { width: `${Math.round(pct * 100)}%` } })),
          h("span", null, `${Math.round(todo.spent_ms / 60_000)} / ${todo.minutes} min`),
          linkChip(todo.link_type, todo.link_id))),
      play,
      del);
    // drag to reorder (open tasks only)
    if (index >= 0) {
      li.addEventListener("dragstart", (e) => {
        e.dataTransfer?.setData("text/plain", todo.id);
        li.classList.add("dragging");
      });
      li.addEventListener("dragend", () => li.classList.remove("dragging"));
      li.addEventListener("dragover", (e) => (e.preventDefault(), li.classList.add("drop-here")));
      li.addEventListener("dragleave", () => li.classList.remove("drop-here"));
      li.addEventListener("drop", async (e) => {
        e.preventDefault();
        li.classList.remove("drop-here");
        const moved = e.dataTransfer?.getData("text/plain");
        const from = siblings.find((x) => x.id === moved);
        if (!from || from.id === todo.id) return;
        const before = siblings[index - 1];
        const ord = before && before.id !== from.id ? (before.ord + todo.ord) / 2 : todo.ord - 1;
        from.ord = ord;
        data.todos.sort((a, b) => Number(!!a.done_at) - Number(!!b.done_at) || a.ord - b.ord);
        renderTodos();
        await save("patch", `/api/todos/${from.id}`, { ord });
      });
    }
    return li;
  };

  // ---------------------------------------------------------------- live updates and keys
  let lastRunKey = "";
  cleanups.push(timer.on(() => {
    const key = timer.run ? `${timer.run.id}:${timer.run.running}:${timer.run.planned_ms}` : "";
    if (key !== lastRunKey) {
      lastRunKey = key;
      renderStage();
      renderTodos();
      // the timer ended (here or from another page): today's numbers and the tasks' time are fresh again
      if (!key) void api.get<TimerData>("/api/timer").then((d) => ((data = { ...d, run: null }), renderTodos()), () => undefined);
      if (!key && recent.open) void loadRecent(); // the run that just ended is listed now
    } else paint();
  }));
  const onKey = (e: KeyboardEvent) => {
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === " " && timer.run) (e.preventDefault(), void timer.toggle());
  };
  document.addEventListener("keydown", onKey);
  cleanups.push(() => document.removeEventListener("keydown", onKey));

  lastRunKey = timer.run ? `${timer.run.id}:${timer.run.running}:${timer.run.planned_ms}` : "";
  renderStage();
  renderTodos();
  return () => cleanups.forEach((f) => f());
}
