// Brainstorm with a model (milestone 3.2 of docs/ai/PLAN.md), on the brainstorm sheet of a note or an idea, and
// for a whole document from the reader. The model writes ideas from three angles, a second call groups and ranks
// them. Since 2026-11-26 (the owner's request) the ideas that rest on a checked passage go straight into the
// brainstorm sheet, each as its own section headed by its label, for you to edit or delete there; Undo takes them out
// while the sheet is as they left it. Ideas with no passage of yours are left out. Text only: h() sets textContent.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, h, toast } from "../util";
import { aiIsOn } from "./explain";

interface Source { kind: "document" | "note" | "idea" | "hlnote"; quote: string; document_id?: string; document_title?: string; sentence?: number; id?: string; title?: string }
interface Idea { text: string; label: string; similar: number; angles: string[]; sources: Source[]; verified: boolean }
interface Result {
  id: string; target: { kind: string; id: string; title: string; sheet_title: string }; topic: string; ideas: Idea[]; judge: "model" | "code" | "none";
  status: "verified" | "partly" | "unverified"; links: string[]; warning: string; provider: string; kept?: number[]; left_out?: number;
}
export interface Target { kind: "page" | "idea" | "document"; id: string }
export interface Hooks { before?: () => Promise<void>; after?: () => Promise<void> | void }

export function aiIdeasBox(target: Target, hooks: Hooks = {}): HTMLElement {
  if (!aiIsOn()) return h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also suggest ideas here, each with the passages it rests on.");
  const topic = h("input", { type: "text", maxlength: 200, placeholder: "A topic for the ideas (optional)", "aria-label": "Topic for the ideas" });
  const out = h("div", { class: "study-out", "aria-live": "polite" });
  let busy = false;
  /** Put every checked idea into the sheet; a toast offers Undo, and the box says what went in. */
  const putIn = async (r: Result) => {
    clear(out);
    const chosen = r.ideas.map((it, i) => ({ it, i })).filter(({ it, i }) => it.verified && !(r.kept ?? []).includes(i)).map(({ it, i }) => ({ index: i, text: it.text }));
    const without = r.ideas.filter((it) => !it.verified).length;
    const foot = [
      without ? h("div", { class: "muted small" }, `${without} idea${without === 1 ? "" : "s"} that named no passage of yours ${without === 1 ? "was" : "were"} left out.`) : null,
      r.left_out ? h("div", { class: "ai-text-links" }, `${r.left_out} file${r.left_out === 1 ? "" : "s"} of secrets left out: they are never sent to a cloud model.`) : null,
      r.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", r.links.join(" · ")) : null,
      r.warning ? h("div", { class: "ai-text-links" }, r.warning) : null,
    ];
    const again = h("button", { type: "button", class: "link small", onclick: () => void run(true) }, "Ask again");
    if (!chosen.length) {
      out.append(h("div", { class: "ai-text" }, h("p", null, r.ideas.length ? "No new idea that rests on your passages." : "The model wrote no ideas from these passages."), whyLink(r.id), ...foot), again);
      return;
    }
    let res: { page_id: string; title: string; kept: number[]; added: number };
    try {
      await hooks.before?.();
      res = await api.post<{ page_id: string; title: string; kept: number[]; added: number }>(`/api/brainstorm/${r.id}/keep`, { items: chosen });
    } catch (e) {
      out.append(h("p", { class: "muted small" }, `The ideas were not added: ${(e as Error).message}`), again);
      return;
    } finally {
      await hooks.after?.(); // also after a failure: the sheet holds its saves until this runs
    }
    r.kept = res.kept;
    const open = () => void (location.hash = `#/notes/${res.page_id}`);
    let undone = false;
    const undo = async () => {
      if (undone) return; // the box and the toast offer the same Undo: one press takes the ideas out
      undone = true;
      try {
        await hooks.before?.();
        const u = await api.post<{ kept: number[] }>(`/api/brainstorm/${r.id}/undo`, { page_id: res.page_id });
        r.kept = u.kept;
        clear(out);
        out.append(h("p", { class: "muted small" }, "The ideas were taken out of the sheet."), again);
      } catch (e) {
        undone = false;
        toast((e as Error).message, "error");
      } finally {
        await hooks.after?.();
      }
    };
    out.append(h("div", { class: "ai-text" },
      h("p", null, res.added ? `Added ${res.added} idea${res.added === 1 ? "" : "s"} to “${res.title}”, each as its own part. Edit them there, or delete what you don't want.` : "Those ideas are already in the sheet."),
      h("div", { class: "row wrap" },
        h("button", { type: "button", class: "btn small primary", onclick: open }, "Open the note"),
        res.added ? h("button", { type: "button", class: "btn small", onclick: () => void undo() }, "Undo") : null,
        whyLink(r.id)),
      ...foot), again);
    if (res.added) toast(`Added ${res.added} idea${res.added === 1 ? "" : "s"} to “${res.title}”.`, "ok", 8000, { label: "Undo", run: () => void undo() });
  };

  const run = async (fresh = false) => {
    if (busy) return;
    busy = true;
    go.disabled = true;
    clear(out);
    out.append(h("div", { class: "row" }, h("p", { class: "muted small", role: "status" }, "The model is writing ideas from three angles, then ranking them…"),
      h("button", { type: "button", class: "btn small", onclick: () => void api.post("/api/brainstorm/cancel", {}) }, "Stop")));
    try {
      const res = await api.post<{ result: Result }>("/api/brainstorm", { ...target, topic: topic.value.trim(), fresh });
      await putIn(res.result);
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "muted small" }, `No ideas: ${(e as Error).message}`));
    } finally {
      busy = false;
      go.disabled = false; // run only starts once the attempt is written, so it stays allowed
    }
  };
  const go: HTMLButtonElement = h("button", { type: "button", class: "btn", onclick: () => void run() }, "Ideas from the model");
  // attempt before reveal: the sheet shows this box only once you have written; for a document, write one line first here
  let first: HTMLElement | null = null;
  if (target.kind === "document") {
    const own = h("textarea", { rows: 2, maxlength: 500, placeholder: "First, your own thought: what do your highlights here make you think of?", "aria-label": "Your own thought first" });
    go.disabled = true;
    own.addEventListener("input", () => (go.disabled = busy || own.value.trim().length < 12));
    first = own;
  }
  return h("div", { class: "stack ai-ideas" },
    first,
    h("p", { class: "muted small" }, target.kind === "document"
      ? "The model reads only your highlights in this document and the notes nearest to them, never the whole document."
      : "The model reads only what this sheet shows: the text, the notes near it and the passages you highlighted on its words."),
    h("div", { class: "row wrap" }, topic, go),
    out);
}
