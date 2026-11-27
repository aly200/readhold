// Tidy (milestone 5.2 of docs/ai/PLAN.md): messy tasks, a note or a routine, made clear. Code first: hints for what a
// good task lacks, and fixes it is sure of. With AI on, and only when you ask, a model proposes a rewrite; words in it
// that you did not write are shown marked. Nothing changes until you press Apply or Use, and each change has Undo
// (while nothing changed since). Text only: h() sets textContent.
import { api } from "../api";
import type { PlanData, Routine } from "../types";
import { clear, h, type ModalHandle, modal, toast } from "../util";
import { aiIsOn } from "./explain";
import { whyLink } from "./why";

interface Hint { kind: string; text: string }
interface Fix { text: string; minutes: number; due: string | null }
interface TaskTidy { id: string; text: string; minutes: number; due: string | null; hints: Hint[]; fix: Fix | null }
interface Part { text: string; minutes: number | null }
interface ModelTask { id: string; number: number; original: { text: string; minutes: number; due: string | null }; text: string; minutes: number | null; due: string | null; split: Part[]; new_words: string[] }
interface Step { text: string; minutes: number }

const dayLabel = (d: string | null) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) : "no day");
const marks = (words: string[]) => words.flatMap((w, i) => (i ? [", ", h("mark", null, w)] : [h("mark", null, w)]));
const newWords = (words: string[]) => (words.length
  ? h("div", { class: "tidy-new" }, "Words you did not write: ", ...marks(words), " (check them: the model may not add facts)")
  : null);

/** Change one task, and offer Undo that puts it back as it was (and removes parts the split added). */
let busy = false; // one change at a time: a second press while one runs does nothing

async function applyTask(id: string, was: Fix, now: Fix, extra: Part[], onChange: () => void): Promise<void> {
  if (busy) return;
  busy = true;
  const body: Record<string, unknown> = { text: now.text, minutes: now.minutes };
  if (now.due) body.due = now.due;
  const made: string[] = [];
  let changed = false;
  const undo = async () => {
    // only what is still as this change left it: a later edit of yours (to the task or to a part) is never undone
    const tasks = (await api.get<PlanData>("/api/plan")).tasks;
    const cur = tasks.find((t) => t.id === id);
    let left = 0;
    if (changed && (!cur || cur.text !== now.text || cur.minutes !== now.minutes || (now.due && cur.due !== now.due))) {
      left++;
    } else if (changed) {
      await api.patch(`/api/todos/${id}`, { text: was.text, minutes: was.minutes, ...(was.due ? { due: was.due } : { clear_due: true }) });
    }
    for (const [k, m] of made.entries()) {
      const part = tasks.find((t) => t.id === m);
      if (part && !part.done_at && part.text === extra[k].text) await api.del(`/api/todos/${m}`).catch(() => undefined);
      else if (part) left++;
    }
    onChange();
    if (left) toast(`${left} changed since ${left === 1 ? "was" : "were"} left as you made ${left === 1 ? "it" : "them"}.`, "info");
  };
  try {
    await api.patch(`/api/todos/${id}`, body);
    changed = true;
    for (const p of extra) made.push((await api.post<{ id: string }>("/api/todos", { text: p.text, minutes: p.minutes ?? 25, ...(now.due ? { due: now.due } : {}) })).id);
    onChange();
    toast(made.length ? `Split into ${made.length + 1} tasks.` : "Task tidied.", "ok", 7000, { label: "Undo", run: () => void undo().catch((e: Error) => toast(e.message, "error")) });
  } catch (e) {
    onChange();
    toast(changed ? `Done only in part: ${(e as Error).message}` : (e as Error).message, "error", 9000, changed ? { label: "Undo what was done", run: () => void undo() } : undefined);
  } finally {
    busy = false;
  }
}

export function tidyTasksDialog(onChange: () => void): Promise<unknown> {
  let handle: ModalHandle;
  const list = h("ol", { class: "tidy-list" }, h("li", { class: "muted small" }, "Looking…"));
  const out = h("div", { class: "stack" });
  const model = new Map<string, ModelTask>();
  let items: TaskTidy[] = [];

  const row = (t: TaskTidy): HTMLElement => {
    const was: Fix = { text: t.text, minutes: t.minutes, due: t.due };
    const m = model.get(t.id);
    return h("li", { class: "tidy-item" },
      h("strong", null, t.text), h("span", { class: "muted small" }, ` · ${t.minutes} min · ${dayLabel(t.due)}`),
      t.hints.length ? h("ul", { class: "tidy-hints" }, t.hints.map((x) => h("li", null, x.text))) : h("div", { class: "muted small" }, "Clear as it is."),
      t.fix ? h("div", { class: "row wrap tidy-fix" }, h("span", null, `Fix: “${t.fix.text}” · ${t.fix.minutes} min · ${dayLabel(t.fix.due)}`),
        h("button", { type: "button", class: "btn small", onclick: () => void applyTask(t.id, was, t.fix!, [], () => (model.delete(t.id), onChange(), void load())) }, "Apply")) : null,
      m ? h("div", { class: "ai-text tidy-model" },
        h("div", null, `The model: “${m.text}”`, m.minutes ? ` · ${m.minutes} min` : "", m.due ? ` · ${dayLabel(m.due)}` : ""),
        m.split.length ? h("ol", { class: "tidy-split" }, m.split.map((p) => h("li", null, p.text, p.minutes ? ` · ${p.minutes} min` : ""))) : null,
        newWords(m.new_words),
        h("div", { class: "row wrap" },
          h("button", { type: "button", class: "btn small", onclick: () => void applyTask(t.id, was, { text: m.text, minutes: m.minutes ?? t.minutes, due: m.due ?? t.due }, [], () => (model.delete(t.id), onChange(), void load())) }, "Use"),
          m.split.length ? h("button", { type: "button", class: "btn small", onclick: () => void applyTask(t.id, was, { text: m.split[0].text, minutes: m.split[0].minutes ?? t.minutes, due: m.due ?? t.due }, m.split.slice(1), () => (model.delete(t.id), onChange(), void load())) }, `Split into ${m.split.length}`) : null)) : null);
  };
  const draw = () => {
    clear(list);
    list.append(...(items.length ? items.map(row) : [h("li", { class: "muted small" }, "No open task.")]));
  };
  const load = async () => {
    items = (await api.get<{ items: TaskTidy[] }>("/api/tidy/tasks")).items;
    draw();
  };
  const ask = async (fresh = false) => {
    clear(out);
    out.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      const r = (await api.post<{ result: { id: string; items: ModelTask[]; warning: string } }>("/api/tidy/suggest", { kind: "tasks", fresh })).result;
      model.clear();
      for (const m of r.items) model.set(m.id, m);
      clear(out);
      out.append(h("div", { class: "ai-text-label" }, `Suggested by the AI model for ${r.items.length} task${r.items.length === 1 ? "" : "s"}. Nothing changes until you press Use.`, whyLink(r.id)),
        h("button", { type: "button", class: "link small", onclick: () => void ask(true) }, "Ask again"));
      draw();
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "muted small" }, `No suggestions: ${(e as Error).message}`));
    }
  };
  void load();
  const body = h("div", { class: "stack" },
    h("p", { class: "muted small" }, "A clear task starts with what you will do (a verb), has one outcome, a day, and stays short. Fixes move a time or a day written in the text into the task itself."),
    aiIsOn() ? h("div", { class: "row" }, h("button", { type: "button", class: "btn", onclick: () => void ask() }, "Suggestions from the model")) : h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also propose rewrites and splits."),
    out, list,
    h("div", { class: "row end" }, h("button", { type: "button", onclick: () => handle.close(null) }, "Close")));
  return modal("Tidy your tasks", body, { wide: true, onOpen: (m) => (handle = m) });
}

/** One note. `before` saves what you typed; `after` shows the note again once it changed. */
export function tidyNoteDialog(pageId: string, before: () => Promise<void>, after: () => void): Promise<unknown> {
  let handle: ModalHandle;
  const code = h("div", { class: "stack" }, h("p", { class: "muted small" }, "Looking…"));
  const out = h("div", { class: "stack" });
  const use = async (from: string, to: string) => {
    const now = (await api.get<{ body: string }>(`/api/pages/${pageId}`)).body;
    if (now !== from) return toast("The note changed since this was proposed. Ask again.", "error");
    await api.patch(`/api/pages/${pageId}`, { body: to });
    handle.close(null);
    after();
    toast("Note tidied.", "ok", 8000, { label: "Undo", run: async () => {
      const cur = (await api.get<{ body: string }>(`/api/pages/${pageId}`)).body;
      if (cur !== to) return toast("The note changed since. Edit it by hand to take the change out.", "error");
      await api.patch(`/api/pages/${pageId}`, { body: from });
      after();
    } });
  };
  void (async () => {
    await before();
    const from = (await api.get<{ body: string }>(`/api/pages/${pageId}`)).body;
    const r = await api.get<{ body: string; changed: boolean }>(`/api/tidy/note/${pageId}`);
    clear(code);
    code.append(r.changed
      ? h("div", { class: "stack" }, h("p", { class: "muted small" }, "Spacing and list marks, fixed by code:"), h("pre", { class: "tidy-pre" }, r.body),
          h("div", { class: "row" }, h("button", { type: "button", class: "btn small", onclick: () => void use(from, r.body) }, "Apply")))
      : h("p", { class: "muted small" }, "Spacing and list marks are tidy already."));
  })();
  const ask = async (fresh = false) => {
    clear(out);
    out.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      await before();
      const r = (await api.post<{ result: { id: string; body: string; original: string; new_words: string[]; restored: string[]; shorter: boolean; missing_words: string[] } }>("/api/tidy/suggest", { kind: "note", id: pageId, fresh })).result;
      clear(out);
      out.append(h("div", { class: "ai-text" },
        h("div", { class: "ai-text-label" }, "A rewrite proposed by the AI model. Nothing changes until you press Use.", whyLink(r.id)),
        h("pre", { class: "tidy-pre" }, r.body), newWords(r.new_words),
        r.restored.length ? h("div", { class: "muted small" }, "Put back at the end because the model left them out: ", r.restored.join("  ")) : null,
        r.shorter ? h("div", { class: "tidy-new" }, "Much shorter than your note. Words that went missing: ", ...marks(r.missing_words)) : null,
        h("div", { class: "row wrap" }, r.body ? h("button", { type: "button", class: "btn small", onclick: () => void use(r.original, r.body) }, "Use this") : null,
          h("button", { type: "button", class: "link small", onclick: () => void ask(true) }, "Ask again"))));
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "muted small" }, `No rewrite: ${(e as Error).message}`));
    }
  };
  const body = h("div", { class: "stack" }, code,
    aiIsOn() ? h("div", { class: "row" }, h("button", { type: "button", class: "btn", onclick: () => void ask() }, "A rewrite from the model")) : h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also propose a clearer version of this note."),
    out, h("div", { class: "row end" }, h("button", { type: "button", onclick: () => handle.close(null) }, "Close")));
  return modal("Tidy this note", body, { wide: true, onOpen: (m) => (handle = m) });
}

export function tidyRoutineDialog(r: Routine, onChange: () => void): Promise<unknown> {
  let handle: ModalHandle;
  const was: Step[] = r.steps.map((s) => ({ text: s.text, minutes: s.minutes }));
  const code = h("div", { class: "stack" }, h("p", { class: "muted small" }, "Looking…"));
  const out = h("div", { class: "stack" });
  const show = (steps: Step[]) => h("ol", { class: "tidy-split" }, steps.map((s) => h("li", null, s.text, s.minutes ? ` · ${s.minutes} min` : "")));
  const use = async (steps: Step[]) => {
    try {
      await api.post(`/api/tidy/routine/${r.id}/apply`, { steps, expect: was });
    } catch (e) {
      return toast((e as Error).message, "error", 9000);
    }
    handle.close(null);
    onChange();
    toast(`“${r.title}” tidied. Its ticks are kept.`, "ok", 8000, { label: "Undo", run: async () => {
      try {
        await api.post(`/api/tidy/routine/${r.id}/apply`, { steps: was, expect: steps });
      } catch (e) {
        toast((e as Error).message, "error");
      }
      onChange();
    } });
  };
  void api.get<{ steps: Step[]; changed: boolean }>(`/api/tidy/routine/${r.id}`).then((x) => {
    clear(code);
    code.append(x.changed ? h("div", { class: "stack" }, h("p", { class: "muted small" }, "Fixed by code:"), show(x.steps),
      h("div", { class: "row" }, h("button", { type: "button", class: "btn small", onclick: () => void use(x.steps) }, "Apply"))) : h("p", { class: "muted small" }, "Its steps are tidy already."));
  });
  const ask = async (fresh = false) => {
    clear(out);
    out.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      const x = (await api.post<{ result: { id: string; steps: Step[]; new_words: string[] } }>("/api/tidy/suggest", { kind: "routine", id: r.id, fresh })).result;
      clear(out);
      out.append(h("div", { class: "ai-text" },
        h("div", { class: "ai-text-label" }, "Steps proposed by the AI model. Nothing changes until you press Use.", whyLink(x.id)),
        show(x.steps), newWords(x.new_words),
        h("div", { class: "row wrap" }, x.steps.length ? h("button", { type: "button", class: "btn small", onclick: () => void use(x.steps) }, "Use these") : null,
          h("button", { type: "button", class: "link small", onclick: () => void ask(true) }, "Ask again"))));
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "muted small" }, `No steps: ${(e as Error).message}`));
    }
  };
  const body = h("div", { class: "stack" }, h("p", { class: "muted small" }, "Now:"), show(was), code,
    aiIsOn() ? h("div", { class: "row" }, h("button", { type: "button", class: "btn", onclick: () => void ask() }, "Steps from the model")) : null,
    out, h("div", { class: "row end" }, h("button", { type: "button", onclick: () => handle.close(null) }, "Close")));
  return modal(`Tidy “${r.title}”`, body, { wide: true, onOpen: (m) => (handle = m) });
}
