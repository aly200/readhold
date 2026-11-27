// The "Connected" card: for a document, a study file, a quest, a glossary term or a note, it shows the notes
// that link to it and the open tasks that point at it, and makes a new note or task that is already linked.
// The same card is used on every page that shows one of these, so the pages hold together.
// Everything is drawn with text nodes; the data comes from GET /api/related on this machine.
import { api } from "./api";
import type { NotePage, Related, Todo } from "./types";
import { askText, clear, h, toast } from "./util";

const pad = (n: number) => String(n).padStart(2, "0");
const today = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const TASK_START: Partial<Record<Related["kind"], string>> = { document: "Read: ", lecture: "Study: ", page: "" };

export function connectedCard(kind: Related["kind"], id: string, title: string): HTMLElement {
  const box = h("div", { class: "connected" }, h("h2", null, "Connected"), h("p", { class: "muted small" }, "Looking…"));
  const load = async (): Promise<void> => {
    let r: Related;
    try {
      r = await api.get<Related>(`/api/related?kind=${kind}&${kind === "term" ? `title=${encodeURIComponent(title)}` : `id=${id}`}`);
    } catch {
      box.hidden = true; // nothing to connect (for example a term that was removed)
      return;
    }
    const linkable = !/[\[\]|#\n]/.test(r.title) && r.title.length <= 190;
    const newNote = async () => {
      const name = await askText("New note", "Title", `Notes on ${r.title}`.slice(0, 190), { okLabel: "Create" });
      if (!name) return;
      try {
        const p = await api.post<NotePage>("/api/pages", { title: name, body: linkable ? `About [[${r.title}]].\n\n` : "" });
        location.hash = `#/notes/${p.id}`;
      } catch {
        // a note with that title is already there: open it
        const p = await api.post<NotePage>("/api/pages/open", { title: name });
        location.hash = `#/notes/${p.id}`;
      }
    };
    const newTask = async () => {
      const text = await askText("New task", "What needs doing?", `${TASK_START[kind] ?? ""}${kind === "page" ? "" : r.title}`.slice(0, 200), { okLabel: "Add to today" });
      if (!text) return;
      try {
        await api.post<Todo>("/api/todos", { text, minutes: 25, link_type: kind, link_id: id, due: today() });
        toast("Added to today's plan.", "ok", 4000, { label: "Open Plan", run: () => void (location.hash = "#/plan") });
        void load();
      } catch (e) {
        toast((e as Error).message, "error");
      }
    };
    const noteRow = (n: Related["notes"][number]) => h("li", null, h("a", { href: `#/notes/${n.id}` }, "📝 ", n.title), n.context ? h("span", { class: "around-context" }, n.context) : null);
    clear(box);
    box.append(h("h2", null, "Connected"));
    if (r.notes.length) box.append(h("h3", null, "Notes that link here"), h("ul", { class: "around-list" }, r.notes.map(noteRow)));
    if (r.mentions.length) box.append(h("h3", null, "Mentioned in your notes"), h("ul", { class: "around-list" }, r.mentions.map(noteRow)));
    if (r.tasks.length) {
      box.append(h("h3", null, "Open tasks"), h("ul", { class: "around-list" }, r.tasks.map((t) =>
        h("li", null, h("a", { href: "#/plan" }, "☑ ", t.text), h("span", { class: "around-context" }, `${t.due ?? "anytime"} · ${t.minutes} min`)))));
    }
    if (!r.notes.length && !r.mentions.length && !r.tasks.length) {
      box.append(h("p", { class: "muted small" }, linkable ? `Nothing points here yet. A note that says [[${r.title}]] shows up in this card.` : "Nothing points here yet."));
    }
    box.append(h("div", { class: "row wrap connected-actions" },
      h("button", { class: "btn small", type: "button", onclick: () => void newNote() }, "+ Note about this"),
      kind in TASK_START ? h("button", { class: "btn small", type: "button", onclick: () => void newTask() }, "+ Task for today") : null,
      kind === "quest" ? h("span", { class: "muted small" }, "Press “→ Plan” on a step to make it a task.") : null));
  };
  void load();
  return box;
}
