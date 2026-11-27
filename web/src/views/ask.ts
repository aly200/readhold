// The Ask tab of the reader's side panel (milestone 2.2 of docs/ai/PLAN.md): a question about this document.
// Without AI it finds the passages that match, best first; that works with AI off. With AI on, the same button
// also asks the model, which answers only from those passages, with checked quotes, or says "not found".
// Everything a model wrote is drawn as text only (h() sets textContent), and is labelled as the model's.
//
// The side panel is rebuilt whenever you highlight or add a note, so everything the tab knows lives in `memo`
// (one per document, while the app is open): the question you are typing, a request in flight, the last answer.
// A rebuilt tab picks it all up, and an answer that arrives late is drawn into whichever tab is showing then.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, h } from "../util";
import { aiIsOn } from "./explain";
import type { Reader } from "./reader";

interface Passage { section_title: string; sentence: number; snippet: string }
interface Cite { verified: boolean; quote?: string; sentence?: number; section_title?: string }
interface Answer {
  id?: string;
  question: string;
  found: boolean;
  answer: string;
  citations: Cite[];
  status: "verified" | "partly" | "unverified" | "not_found";
  links: string[];
  provider?: string;
  warning?: string;
  searched?: number;
}
interface Memo {
  q: string; // what is in the box, sent or not
  asked: string; // the question the passages and the answer below belong to
  passages: Passage[] | null;
  answer: Answer | null;
  note: string;
  busy: boolean;
  seq: number; // the newest request; an older one that answers late is ignored
  redraw: (() => void) | null; // draws into the tab that is showing now
}

const STATUS: Record<Exclude<Answer["status"], "not_found">, string> = {
  verified: "Each cited passage is in the document. Check that the answer follows from them.",
  partly: "Some cited passages are in the document; the others could not be found in it.",
  unverified: "No cited passage could be found in the document. Treat this answer as a guess.",
};

const memos = new Map<string, Memo>();

export function askTab(r: Reader, body: HTMLElement): void {
  let memo = memos.get(r.doc.id);
  if (!memo) {
    memo = { q: "", asked: "", passages: null, answer: null, note: "", busy: false, seq: 0, redraw: null };
    memos.set(r.doc.id, memo);
  }
  const m = memo;
  const input = h("textarea", { rows: 2, maxlength: 1000, placeholder: "Ask about this document…", "aria-label": "Your question" }, m.q);
  input.addEventListener("input", () => (m.q = input.value)); // a rebuilt panel keeps what you were typing
  const out = h("div", { class: "ask-out", "aria-live": "polite" });
  const button = h("button", { type: "button", class: "btn small primary", onclick: () => void run(input.value) }, aiIsOn() ? "Ask" : "Find passages");

  const passageList = (items: Passage[]) =>
    items.length
      ? h("ol", { class: "ask-passages" }, items.map((p) =>
          h("li", null, h("button", { type: "button", class: "link", onclick: () => r.jumpTo(p.sentence) }, p.section_title), h("div", { class: "muted small" }, p.snippet))))
      : h("p", { class: "muted small" }, "No passage of this document matches those words.");

  const draw = () => {
    if (!out.isConnected && m.redraw !== draw) return;
    clear(out);
    button.toggleAttribute("disabled", m.busy);
    if (m.busy) out.append(h("p", { class: "muted small", role: "status" }, aiIsOn() ? "Asking the model…" : "Looking…"));
    if (m.asked && (m.answer || m.passages)) out.append(h("p", { class: "muted small" }, h("strong", null, "Your question: "), m.asked));
    const a = m.answer;
    if (a) {
      if (!a.found) {
        out.append(h("div", { class: "ai-text" },
          h("div", { class: "ai-text-label" }, a.searched ? "Checked by the AI model." : "No passage matched, so no model was asked."),
          h("p", null, h("strong", null, "Not found in this document."), m.passages?.length ? " The passages below are the closest matches." : "")));
      } else {
        out.append(h("div", { class: "ai-text" },
          h("div", { class: "ai-text-label" }, `Written by the AI model (${a.provider === "local" ? "on this computer" : a.provider ?? "AI"}). ${STATUS[a.status as Exclude<Answer["status"], "not_found">]}`),
          whyLink(a.id),
          h("p", null, a.answer),
          a.citations.length ? h("ul", { class: "ask-cites" }, a.citations.map((c) =>
            c.verified && c.quote && c.sentence !== undefined
              ? h("li", null, h("button", { type: "button", class: "link resume-quote", title: `Go to this passage (${c.section_title ?? ""})`, onclick: () => r.jumpTo(c.sentence as number) }, `✓ “${c.quote}”`))
              : h("li", { class: "resume-quote unproven" }, "a passage that could not be found in the document"))) : null,
          a.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", a.links.join(" · ")) : null,
          a.warning ? h("div", { class: "ai-text-links" }, a.warning) : null));
      }
      // asks the question this answer belongs to, not whatever is in the box now
      if (a.id && !m.busy) out.append(h("button", { type: "button", class: "link small", onclick: () => void run(a.question, true) }, "Ask again"));
    } else if (m.note) out.append(h("p", { class: "muted small" }, m.note));
    if (m.passages) out.append(h("div", { class: "kicker" }, "Passages that match"), passageList(m.passages));
  };
  m.redraw = draw;

  const run = async (text: string, fresh = false) => {
    const q = text.trim();
    if (!q || m.busy) return;
    const mine = ++m.seq;
    m.busy = true;
    m.asked = q;
    m.answer = null;
    m.note = "";
    m.redraw?.();
    try {
      const found = (await api.get<{ passages: Passage[] }>(`/api/documents/${r.doc.id}/ask?q=${encodeURIComponent(q)}`)).passages;
      if (mine !== m.seq) return;
      m.passages = found;
      m.redraw?.();
      if (aiIsOn()) {
        try {
          const res = (await api.post<{ result: Answer }>(`/api/documents/${r.doc.id}/ask`, { question: q, fresh })).result;
          if (mine === m.seq) m.answer = res;
        } catch (e) {
          if (mine === m.seq) m.note = `No answer from the model: ${(e as Error).message}`;
        }
      }
    } catch (e) {
      if (mine === m.seq) {
        m.passages = null;
        m.note = (e as Error).message;
      }
    } finally {
      if (mine === m.seq) m.busy = false;
      m.redraw?.();
    }
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void run(input.value);
    }
  });
  body.append(
    h("div", { class: "stack ask-tab" },
      input,
      h("div", { class: "row" }, button),
      h("p", { class: "muted small" }, aiIsOn()
        ? "The model reads only the sections that match your question, and says so when the answer is not in them."
        : "Finds the passages that match your words. With AI switched on in Settings, a model can also answer from them."),
      out));
  draw();
}
