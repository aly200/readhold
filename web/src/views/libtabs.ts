// Three menu entries are one page with tabs:
//   Plan    — the tasks of your days (with routines) and Today (your main goal, your energy, the next step);
//   Study   — lectures and notebooks, the documents you read, the goals (each with questions and steps), the cards to review, the glossary;
//   Notes   — your notes, the journal, the idea inbox and Think.
// This is the header they share. The tabs are plain links, so every old address (#/review, #/journal, …) still works.
import { api } from "../api";
import { h } from "../util";

interface Tab<T extends string> {
  id: T;
  label: string;
  href: string;
  hint: string;
}
/** the small number on a tab: how many, what it counts (for the tooltip), and whether it wants attention */
type Counts<T extends string> = Partial<Record<T, { n: number; what: string; due?: boolean }>>;

function tabHead<T extends string>(title: string, about: string, tabs: Tab<T>[], active: T, load: () => Promise<Counts<T>>, tools: (HTMLElement | null)[]): HTMLElement {
  const count = {} as Record<T, HTMLElement>;
  const bar = h("nav", { class: "lib-tabs", "aria-label": about }, tabs.map((t) => {
    count[t.id] = h("span", { class: "lib-count", hidden: true });
    return h("a", { href: t.href, class: t.id === active ? "on" : "", "aria-current": t.id === active ? "page" : undefined, title: t.hint }, h("span", null, t.label), count[t.id]);
  }));
  // the numbers arrive a moment later; the tabs work without them
  load().then((c) => {
    for (const t of tabs) {
      const got = c[t.id];
      if (!got || !got.n) continue;
      const what = `${got.n} ${got.what}`;
      count[t.id].textContent = String(got.n);
      count[t.id].title = what;
      count[t.id].setAttribute("aria-label", what);
      count[t.id].classList.toggle("is-due", Boolean(got.due));
      count[t.id].hidden = false;
    }
  }, () => undefined);
  const extra = tools.filter(Boolean);
  return h("header", { class: "isle lib-head" }, h("h1", null, title), bar, extra.length ? h("div", { class: "lib-tools" }, extra) : null);
}

// ------------------------------------------------------------------ Plan
export type PlanTab = "tasks" | "today";

const PLAN: Tab<PlanTab>[] = [
  { id: "tasks", label: "Tasks", href: "#/plan", hint: "Tasks for your days, and routines" },
  { id: "today", label: "Today", href: "#/home", hint: "Your main goal, your energy and the next step" },
];

export function planHead(active: PlanTab, ...tools: (HTMLElement | null)[]): HTMLElement {
  return tabHead("Plan", "Parts of Plan", PLAN, active, async () => {
    const c = await api.get<{ tasks_now: number }>("/api/plan/counts");
    return { tasks: { n: c.tasks_now, what: "for today (carried-over ones too)" } };
  }, tools);
}

// ------------------------------------------------------------------ Study
export type LibTab = "documents" | "study" | "goals" | "review" | "glossary";

const LIBRARY: Tab<LibTab>[] = [
  { id: "study", label: "Lectures", href: "#/lectures", hint: "Slides, web pages and notebooks to study from" },
  { id: "documents", label: "Documents", href: "#/library", hint: "The papers and articles you read" },
  { id: "goals", label: "Goals", href: "#/quest", hint: "What you are working towards: the questions each goal must answer and the steps to get there" },
  { id: "review", label: "Review", href: "#/review", hint: "Cards that come back just before you would forget them" },
  { id: "glossary", label: "Glossary", href: "#/glossary", hint: "The terms you saved while reading" },
];

export function libraryHead(active: LibTab, ...tools: (HTMLElement | null)[]): HTMLElement {
  return tabHead("Study", "Parts of Study", LIBRARY, active, async () => {
    const c = await api.get<{ documents: number; lectures: number; goals: number; review_due: number; terms: number }>("/api/library/counts");
    return {
      documents: { n: c.documents, what: c.documents === 1 ? "document" : "documents" },
      study: { n: c.lectures, what: "to study from" },
      goals: { n: c.goals, what: "not finished" },
      review: { n: c.review_due, what: "to review now", due: true },
      glossary: { n: c.terms, what: "saved" },
    };
  }, tools);
}

// ------------------------------------------------------------------ Notes
export type NotesTab = "notes" | "journal" | "ideas" | "think";

const NOTES: Tab<NotesTab>[] = [
  { id: "notes", label: "All notes", href: "#/notes", hint: "Your own linked notes" },
  { id: "journal", label: "Journal", href: "#/journal", hint: "One page a day about how it went" },
  { id: "ideas", label: "Ideas", href: "#/ideas", hint: "A quick inbox for ideas" },
  { id: "think", label: "Think", href: "#/think", hint: "Ideas to come back to, and small changes for you to approve" },
];

export function notesHead(active: NotesTab, ...tools: (HTMLElement | null)[]): HTMLElement {
  return tabHead("Notes", "Parts of Notes", NOTES, active, async () => {
    const c = await api.get<{ notes: number; ideas: number; think: number }>("/api/notes/counts");
    return {
      notes: { n: c.notes, what: c.notes === 1 ? "note" : "notes" },
      ideas: { n: c.ideas, what: "in the inbox" },
      think: { n: c.think, what: "waiting for you (ideas for today and suggestions)", due: true },
    };
  }, tools);
}
