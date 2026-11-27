// "Ask your library" on the Documents tab (milestone 2.3 of docs/ai/PLAN.md): a question across every document
// and every note. Without AI it lists the passages and notes that match. With AI on, the model starts from them and
// may search again or read one section, at most 3 steps, then answers with checked quotes or says "not found".
// Everything a model wrote is drawn as text only (h() sets textContent), and is labelled as the model's.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, h } from "../util";
import { aiIsOn } from "./explain";

interface Match {
  kind: "document" | "note";
  document_id?: string;
  document_title?: string;
  section_title?: string;
  sentence?: number;
  note_id?: string;
  title?: string;
  snippet: string;
}
interface Cite {
  verified: boolean;
  kind?: "document" | "note";
  quote?: string;
  document_id?: string;
  document_title?: string;
  section_title?: string;
  sentence?: number;
  note_id?: string;
  note_title?: string;
}
interface Step { step: number; action: "answer" | "search" | "read"; keywords?: string; added?: number; ran?: boolean }
interface Answer {
  id?: string;
  question: string;
  found: boolean;
  answer: string;
  citations: Cite[];
  status: "verified" | "partly" | "unverified" | "not_found";
  steps: Step[];
  links: string[];
  provider?: string;
  warning?: string;
  searched?: number;
  left_out?: number;
  private_left_out?: number; // items tagged #private (or copies of them), left out in cloud mode (4.4)
}

const STATUS: Record<Exclude<Answer["status"], "not_found">, string> = {
  verified: "Each cited passage is in your library. Check that the answer follows from them.",
  partly: "Some cited passages are in your library; the others could not be found in it.",
  unverified: "No cited passage could be found in your library. Treat this answer as a guess.",
};

const where = (m: { kind?: string; document_id?: string; sentence?: number; note_id?: string }): string =>
  m.kind === "note" ? `#/notes/${m.note_id}` : `#/read/${m.document_id}?s=${m.sentence ?? 0}`;

function stepLine(steps: Step[]): string {
  const said = steps.map((s) =>
    s.ran === false ? `still asked to ${s.action} on the last step, where no tool runs`
    : s.action === "search" ? `searched for “${s.keywords ?? ""}” (${s.added ?? 0} new)` : s.action === "read" ? `read ${s.added ? "a section" : "nothing new"}` : "answered");
  return said.length ? `The model ${said.join(", then ")}.` : "";
}

// lives as long as the page: the Documents tab can be left and drawn again while the model works, and
// `redraw` always points at the box on screen now, so the answer lands there (not in a box that is gone)
const memo = { q: "", asked: "", matches: null as Match[] | null, answer: null as Answer | null, note: "", busy: false, seq: 0, redraw: () => {} };

export function libraryAskBox(): HTMLElement {
  const input = h("textarea", { rows: 2, maxlength: 1000, placeholder: "Ask a question across all your documents and notes…", "aria-label": "Question for your library" }, memo.q);
  input.addEventListener("input", () => (memo.q = input.value));
  const out = h("div", { class: "ask-out", "aria-live": "polite" });
  const button = h("button", { type: "button", class: "btn primary", onclick: () => void run(input.value) }, aiIsOn() ? "Ask" : "Find passages");

  const draw = () => {
    clear(out);
    button.toggleAttribute("disabled", memo.busy);
    if (memo.busy) out.append(h("div", { class: "row" }, h("p", { class: "muted small", role: "status" }, aiIsOn() ? "Asking the model (it may search your library up to 3 times)…" : "Looking…"),
      aiIsOn() ? h("button", { type: "button", class: "btn small", onclick: () => void api.post("/api/library/ask/cancel", {}) }, "Stop") : null));
    if (memo.asked && (memo.answer || memo.matches)) out.append(h("p", { class: "muted small" }, h("strong", null, "Your question: "), memo.asked));
    const a = memo.answer;
    if (a) {
      const steps = stepLine(a.steps);
      if (!a.found) {
        out.append(h("div", { class: "ai-text" },
          h("div", { class: "ai-text-label" }, a.searched ? `Checked by the AI model. ${steps}` : "Nothing matched, so no model was asked."),
          h("p", null, h("strong", null, "Not found in your library."), memo.matches?.length ? " The passages below are the closest matches." : ""),
          a.left_out ? h("div", { class: "ai-text-links" }, `${a.left_out} file${a.left_out === 1 ? "" : "s"} of secrets left out: they are never sent to a cloud model.`) : null,
          a.private_left_out ? h("div", { class: "ai-text-links" }, `${a.private_left_out} item${a.private_left_out === 1 ? "" : "s"} left out because ${a.private_left_out === 1 ? "it stays" : "they stay"} on this computer (#private, or not tagged #cloud when only #cloud items may go).`) : null));
      } else {
        out.append(h("div", { class: "ai-text" },
          h("div", { class: "ai-text-label" }, `Written by the AI model (${a.provider === "local" ? "on this computer" : a.provider ?? "AI"}). ${STATUS[a.status as Exclude<Answer["status"], "not_found">]} ${steps}`),
          whyLink(a.id),
          h("p", null, a.answer),
          a.citations.length ? h("ul", { class: "ask-cites" }, a.citations.map((c) =>
            c.verified && c.quote
              ? h("li", null, h("a", { class: "resume-quote", href: where(c), title: "Open this passage" }, `✓ “${c.quote}”`),
                  h("div", { class: "muted small" }, c.kind === "note" ? `Your note “${c.note_title ?? ""}”` : `${c.document_title ?? ""} · ${c.section_title ?? ""}`))
              : h("li", { class: "resume-quote unproven" }, "a passage that could not be found in your library"))) : null,
          a.left_out ? h("div", { class: "ai-text-links" }, `${a.left_out} file${a.left_out === 1 ? "" : "s"} of secrets left out: they are never sent to a cloud model.`) : null,
          a.private_left_out ? h("div", { class: "ai-text-links" }, `${a.private_left_out} item${a.private_left_out === 1 ? "" : "s"} left out because ${a.private_left_out === 1 ? "it stays" : "they stay"} on this computer (#private, or not tagged #cloud when only #cloud items may go).`) : null,
          a.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", a.links.join(" · ")) : null,
          a.warning ? h("div", { class: "ai-text-links" }, a.warning) : null));
      }
      if (a.id && !memo.busy) out.append(h("button", { type: "button", class: "link small", onclick: () => void run(a.question, true) }, "Ask again"));
    } else if (memo.note) out.append(h("p", { class: "muted small" }, memo.note));
    if (memo.matches) {
      out.append(h("div", { class: "kicker" }, "Passages and notes that match"));
      out.append(memo.matches.length
        ? h("ol", { class: "ask-passages" }, memo.matches.map((m) =>
            h("li", null, h("a", { href: where(m) }, m.kind === "note" ? `Note: ${m.title ?? ""}` : `${m.document_title ?? ""} · ${m.section_title ?? ""}`),
              h("div", { class: "muted small" }, m.snippet))))
        : h("p", { class: "muted small" }, "Nothing in your library matches those words."));
    }
  };

  const run = async (text: string, fresh = false) => {
    const q = text.trim();
    if (!q || memo.busy) return;
    const mine = ++memo.seq;
    memo.busy = true;
    memo.asked = q;
    memo.answer = null;
    memo.note = "";
    draw();
    try {
      const found = (await api.get<{ passages: Match[] }>(`/api/library/ask?q=${encodeURIComponent(q)}`)).passages;
      if (mine !== memo.seq) return;
      memo.matches = found;
      memo.redraw();
      if (aiIsOn()) {
        try {
          const res = (await api.post<{ result: Answer }>("/api/library/ask", { question: q, fresh })).result;
          if (mine === memo.seq) memo.answer = res;
        } catch (e) {
          if (mine === memo.seq) memo.note = `No answer from the model: ${(e as Error).message}`;
        }
      }
    } catch (e) {
      if (mine === memo.seq) {
        memo.matches = null;
        memo.note = (e as Error).message;
      }
    } finally {
      if (mine === memo.seq) memo.busy = false;
      memo.redraw();
    }
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void run(input.value);
    }
  });
  const box = h("div", { class: "isle stack library-ask" },
    h("h2", null, "Ask your library"),
    input,
    h("div", { class: "row" }, button),
    h("p", { class: "muted small" }, aiIsOn()
      ? "The model starts from the passages and notes that match, may search again or read one section (at most 3 steps), and says so when your library does not answer."
      : "Finds the passages and notes that match your words. With AI switched on in Settings, a model can also answer from them."),
    out);
  memo.redraw = () => {
    if (out.isConnected) draw();
  };
  draw();
  return box;
}
