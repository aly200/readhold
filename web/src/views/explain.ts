// Explain a passage you selected (milestone 1.4 of docs/ai/PLAN.md).
// You pick the level, and you may write your own take first: an attempt before the answer is how memory is made.
// Nothing is sent until you press a button. The answer is the model's and says so; it is drawn as text only
// (h() sets textContent), and it becomes a note of yours only if you press "Save as a note".
import { whyLink } from "./why";
import { api } from "../api";
import { state } from "../state";
import type { Note } from "../types";
import { clear, h, type ModalHandle, modal, toast } from "../util";
import type { Reader } from "./reader";

type Level = "simple" | "student" | "expert";
interface Explained {
  id: string;
  explanation: string;
  terms: { term: string; meaning: string }[];
  feedback: string;
  quote: string;
  status: "verified" | "unverified";
  links: string[];
  level: Level;
  provider: string;
  warning: string;
  saved: boolean;
}

const LEVELS: [Level, string, string][] = [
  ["simple", "Simple", "Everyday words, as for someone new to the subject"],
  ["student", "Student", "The right terms, with a reason for each step"],
  ["expert", "Expert", "Dense and precise, for someone who knows the field"],
];
let lastLevel: Level = "student"; // remembered while the app is open

export function aiIsOn(): boolean {
  return state.settings.ai_mode === "local" || state.settings.ai_mode === "cloud";
}

/** The sentence range of a selection inside a code block (code has no sentence elements of its own). */
export function codeRange(r: Reader): [number, number] | null {
  const node = window.getSelection()?.anchorNode;
  const pre = (node instanceof Element ? node : node?.parentElement)?.closest<HTMLElement>("pre.p.code[data-pid]");
  if (!pre) return null;
  const at = r.idx.find((x) => x.p.id === pre.dataset.pid);
  return at ? [at.s.ord, at.s.ord] : null;
}

function drawResult(x: Explained): HTMLElement {
  return h("div", { class: "ai-text" },
    h("div", { class: "ai-text-label" }, `Written by the AI model (${x.provider === "local" ? "on this computer" : x.provider}). Check it against the passage.`),
    whyLink(x.id),
    h("p", null, x.explanation),
    x.terms.length ? h("ul", null, x.terms.map((t) => h("li", null, h("strong", null, t.term), `: ${t.meaning}`))) : null,
    x.feedback ? h("p", null, h("strong", null, "About your take: "), x.feedback) : null,
    x.status === "verified"
      ? h("div", { class: "resume-quote", title: "These words are in the passage. Whether the explanation follows from them is for you to judge." }, `✓ It rests on: “${x.quote}”`)
      : h("div", { class: "resume-quote unproven" }, "The model named no passage that is in the text. Treat this as a guess."),
    x.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", x.links.join(" · ")) : null,
    x.warning ? h("div", { class: "ai-text-links" }, x.warning) : null);
}

export function explainSelection(r: Reader, range: [number, number], text: string): Promise<unknown> {
  r.pacer.pause(false);
  let level = lastLevel;
  const shown = text.length > 400 ? `${text.slice(0, 400)}…` : text;
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Level" });
  LEVELS.forEach(([id, label, hint]) => {
    const b = h("button", { type: "button", class: id === level ? "on" : "", title: hint, onclick: () => {
      level = lastLevel = id;
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    } }, label);
    seg.append(b);
  });
  const take = h("textarea", { rows: 2, maxlength: 600, autofocus: true, placeholder: "Your take first: what do you think it means? A rough line is enough.", "aria-label": "Your take" });
  const out = h("div", { class: "explain-out", "aria-live": "polite" });
  let handle: ModalHandle;
  let busy = false;
  const run = async (attempt: string, fresh = false) => {
    if (busy) return;
    busy = true;
    clear(out);
    out.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      const res = await api.post<{ result: Explained }>(`/api/documents/${r.doc.id}/explain`,
        { sentence: range[0], end_sentence: range[1], level, text: text.slice(0, 1200), attempt, fresh });
      show(res.result, attempt);
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "muted small" }, `No explanation: ${(e as Error).message}`));
    } finally {
      busy = false;
    }
  };
  const show = (x: Explained, attempt: string) => {
    clear(out);
    const save = h("button", { type: "button", class: "btn small", disabled: x.saved, onclick: async () => {
      try {
        const res = await api.post<{ note: Note }>(`/api/ai/results/${x.id}/note`);
        if (!r.ann.notes.some((n) => n.id === res.note.id)) r.ann.notes.push(res.note);
        r.decorateSentence(res.note.sentence);
        r.renderSide();
        save.setAttribute("disabled", "");
        save.textContent = "Saved as a note";
        toast("Saved as a margin note, marked as written by the model.", "ok");
      } catch (e) {
        toast((e as Error).message, "error");
      }
    } }, x.saved ? "Saved as a note" : "Save as a note");
    out.append(drawResult(x), h("div", { class: "row" }, save, h("button", { type: "button", class: "link small", onclick: () => void run(attempt, true) }, "Ask again")));
  };
  const cloud = state.settings.ai_mode === "cloud";
  return modal(
    "Explain this passage",
    h("div", { class: "stack" },
      h("blockquote", null, shown),
      h("label", { class: "field" }, h("span", null, "Level"), seg),
      take,
      h("div", { class: "row end" },
        h("button", { type: "button", onclick: () => void run("") }, "No idea, explain"),
        h("button", { type: "button", class: "primary", onclick: () => (take.value.trim() ? void run(take.value.trim()) : take.focus()) }, "Explain")),
      h("p", { class: "muted small" }, cloud
        ? "Sends this passage, the text around it in its paragraph and your take to your cloud model. Secrets are removed first."
        : "Uses the model on this computer. It reads only this passage and the text around it in its paragraph."),
      out,
      h("div", { class: "row end" }, h("button", { type: "button", onclick: () => handle.close(null) }, "Close"))),
    { wide: true, onOpen: (m) => (handle = m) },
  );
}
