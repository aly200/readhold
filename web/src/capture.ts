// Capture (Ctrl+J, from anywhere): one box for a thought, saved as an idea, a line in today's note or a task.
// It is stamped with where you were: the document and sentence you were reading, or the study file, quest or
// note that was open. Nothing is typed twice, and the stamp becomes a link back.
// No AI is involved; everything is saved through the features' own endpoints on this machine.
import { api } from "./api";
import type { Doc } from "./types";
import { flushPending, h, type ModalHandle, modal, toast } from "./util";

type Kind = "idea" | "note" | "task";
interface Stamp {
  kind: "document" | "lecture" | "quest" | "page";
  id: string;
  title: string;
  sentence: number | null;
}

let lastKind: Kind = "idea"; // what you chose last time stays chosen
const pad = (n: number) => String(n).padStart(2, "0");
const today = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const linkable = (title: string): boolean => !!title.trim() && title.length <= 190 && !/[\[\]|#\n]/.test(title);

/** where you are right now, read from the address and asked from the server */
async function whereAmI(): Promise<Stamp | null> {
  const [, view, id] = (location.hash.slice(1).split("?")[0] || "").split("/");
  if (!id || !/^[0-9a-f]{32}$/.test(id)) return null;
  try {
    if (view === "read" || view === "summary" || view === "structure") {
      flushPending(); // the place you reached is written before it is read back
      const d = await api.get<Doc>(`/api/documents/${id}?touch=false`);
      return { kind: "document", id, title: d.title, sentence: view === "read" ? d.position : null };
    }
    if (view === "lecture") return { kind: "lecture", id, title: (await api.get<{ title: string }>(`/api/lectures/${id}`)).title, sentence: null };
    if (view === "quest" || view === "map") return { kind: "quest", id, title: (await api.get<{ title: string }>(`/api/quests/${id}`)).title, sentence: null };
    if (view === "notes") return { kind: "page", id, title: (await api.get<{ title: string }>(`/api/pages/${id}`)).title, sentence: null };
  } catch {
    /* no stamp is fine */
  }
  return null;
}

export async function openCapture(): Promise<void> {
  if (document.querySelector(".modal-back")) return;
  const stamp = await whereAmI();
  let handle: ModalHandle;
  let kind = lastKind;
  const text = h("textarea", { rows: 4, maxlength: 5000, placeholder: "What is on your mind?", "aria-label": "Your thought", autofocus: true });
  const useStamp = h("input", { type: "checkbox", checked: true });
  const kinds = h("div", { class: "pick-row", role: "radiogroup", "aria-label": "Save it as" });
  const hint = h("p", { class: "muted small capture-hint" });
  const HINT: Record<Kind, string> = {
    idea: "Goes to the idea inbox. Think can bring it back later.",
    note: "Becomes a line under “Notes” in today's note.",
    task: "Becomes a task under Anytime in Plan. The first line is the task.",
  };
  const paint = () => {
    kinds.querySelectorAll<HTMLButtonElement>("button").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.kind === kind);
      b.setAttribute("aria-checked", String(b.dataset.kind === kind));
    });
    hint.textContent = HINT[kind];
  };
  ([["idea", "💡 Idea"], ["note", "📝 Today's note"], ["task", "☑️ Task"]] as [Kind, string][]).forEach(([k, label]) =>
    kinds.append(h("button", { type: "button", class: "pick", role: "radio", "data-kind": k, onclick: () => ((kind = k), paint(), text.focus()) }, label)));
  paint();

  const save = async () => {
    const value = text.value.trim();
    if (!value) return text.focus();
    const st = stamp && useStamp.checked ? stamp : null;
    lastKind = kind;
    try {
      if (kind === "idea") {
        const from = st && st.kind !== "document" ? `\n— from “${st.title}”` : "";
        await api.post("/api/ideas", { text: `${value}${from}`, ...(st?.kind === "document" ? { document_id: st.id, ...(st.sentence !== null ? { sentence: st.sentence } : {}) } : {}) });
        toast("Saved to the idea inbox.", "ok", 3500, { label: "Open", run: () => void (location.hash = "#/ideas") });
      } else if (kind === "note") {
        const link = !st ? "" : !linkable(st.title) ? ` — ${st.title}` : st.kind === "document" && st.sentence !== null ? ` — [[${st.title}#s${st.sentence}|${st.title}]]` : ` — [[${st.title}]]`;
        await api.post("/api/pages/capture", { text: `${value.replace(/\s*\n\s*/g, " ")}${link}`.slice(0, 1000), day: today() });
        toast("Added to today's note.", "ok", 3500, { label: "Open", run: () => void (location.hash = "#/notes/today") });
      } else {
        const first = value.split("\n")[0].trim().slice(0, 500);
        const rest = value.split("\n").slice(1).join("\n").trim().slice(0, 2000);
        await api.post("/api/todos", { text: first, minutes: 25, note: rest, ...(st && st.kind !== "quest" ? { link_type: st.kind, link_id: st.id } : {}) });
        toast("Added to Plan, under Anytime.", "ok", 3500, { label: "Open", run: () => void (location.hash = "#/plan") });
      }
    } catch (e) {
      return toast(`Not saved: ${(e as Error).message}`, "error"); // the box stays open, so nothing typed is lost
    }
    handle.close("saved");
    // a page that lists what was just saved draws itself again
    if (/^#\/(hub|ideas|plan|think)?(\?|$)/.test(location.hash) || location.hash === "" || location.hash.startsWith("#/notes/today")) window.dispatchEvent(new HashChangeEvent("hashchange"));
  };
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) (e.preventDefault(), void save());
  });
  await modal("Capture", h("div", { class: "stack capture" },
    text,
    kinds,
    hint,
    stamp ? h("label", { class: "toggle capture-stamp" }, useStamp, ` Stamp it: from “${stamp.title}”${stamp.sentence !== null ? `, sentence ${stamp.sentence + 1}` : ""}`) : null,
    h("div", { class: "row end" },
      h("span", { class: "muted small capture-keys" }, "Enter saves · Shift+Enter for a new line"),
      h("button", { type: "button", onclick: () => handle.close(null) }, "Cancel"),
      h("button", { class: "primary", type: "button", onclick: () => void save() }, "Save"))), { onOpen: (m) => (handle = m) });
}
