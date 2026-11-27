// Study notes writer (milestone 2.4 of docs/ai/PLAN.md): a short quiz, flashcards or notes from your highlights or
// one section. Nothing is kept until you choose items and press Keep; what you keep says the model wrote it.
// A quiz asks you first and shows the answer after ("attempt before reveal"). Text only: h() sets textContent.
// Keeping is once: a kept item is shown as kept, and the Keep button cannot be pressed twice while it works.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, h, type ModalHandle, modal, toast } from "../util";
import { aiIdeasBox } from "./aibrainstorm";
import { aiIsOn } from "./explain";
import type { Reader } from "./reader";

type Kind = "notes" | "cards" | "quiz";
type Source = "highlights" | "section";
interface Item { text: string; answer: string; verified: boolean; quote?: string; sentence?: number }
interface Written {
  id: string; kind: Kind; source: Source; items: Item[]; status: "verified" | "partly" | "unverified"; links: string[]; provider: string; warning: string;
  kept?: number[]; cut?: boolean; left_out?: number;
}
interface Kept { page_id?: string; title?: string; cards?: number; skipped?: number; kept: number[] }

const MAX_HIGHLIGHTS = 40; // readhold/ai/notes.py
// recall first ("attempt before reveal"): the quiz is the first choice, finished notes the last
const KIND_LABEL: Record<Kind, string> = { quiz: "Quiz me", cards: "Flashcards", notes: "Notes" };
const STATUS: Record<Written["status"], string> = {
  verified: "Each item rests on a passage that is in your reading. Check that it follows from it.",
  partly: "Some items rest on a passage of your reading; the others name none and cannot be kept.",
  unverified: "No item rests on a passage of your reading. Treat them as guesses; they cannot be kept.",
};

export function studyNotesDialog(r: Reader): Promise<unknown> {
  r.pacer.pause(false);
  let kind: Kind = "quiz";
  let source: Source = r.ann.highlights.length ? "highlights" : "section";
  const section = r.idx[r.pacer.ord]?.sec;
  let handle: ModalHandle;
  let kept = new Set<number>();
  const out = h("div", { class: "study-out", "aria-live": "polite" });
  const close = () => handle.close(null);

  const seg = <T extends string>(label: string, options: [T, string][], get: () => T, set: (v: T) => void) => {
    const box = h("div", { class: "seg", role: "group", "aria-label": label });
    for (const [v, text] of options) {
      const b = h("button", { type: "button", class: get() === v ? "on" : "", onclick: () => {
        set(v);
        box.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      } }, text);
      box.append(b);
    }
    return h("label", { class: "field" }, h("span", null, label), box);
  };

  const jump = (ord: number) => () => (close(), r.jumpTo(ord));
  const quoteOf = (it: Item) =>
    it.verified && it.quote && it.sentence !== undefined
      ? h("button", { type: "button", class: "link resume-quote", onclick: jump(it.sentence) }, `✓ “${it.quote}”`)
      : h("div", { class: "resume-quote unproven" }, "no passage named");

  const keep = async (w: Written, chosen: { index: number; text: string; answer: string }[], keepAs?: "cards"): Promise<Kept | null> => {
    try {
      const res = await api.post<Kept>(`/api/ai/results/${w.id}/accept`, { items: chosen, ...(keepAs ? { keep_as: keepAs } : {}) });
      kept = new Set(res.kept);
      if (res.page_id) toast(`Kept in your note “${res.title}”, marked as written by the model.`, "ok", 6000, { label: "Open the note", run: () => void (location.hash = `#/notes/${res.page_id}`) });
      else {
        const n = res.cards ?? 0;
        const skipped = res.skipped ? ` ${res.skipped} already in Review (or deleted by you), not added again.` : "";
        toast(`${n} card${n === 1 ? "" : "s"} added to Review, marked as written by the model.${skipped}`, "ok", 6000);
      }
      return res;
    } catch (e) {
      toast((e as Error).message, "error");
      return null;
    }
  };

  const drawQuiz = (w: Written) =>
    h("ol", { class: "study-items" }, w.items.map((it, i) => {
      const mine = h("textarea", { rows: 2, placeholder: "Your answer first…", "aria-label": `Your answer to question ${i + 1}` });
      const keepBtn: HTMLButtonElement | null = it.verified
        ? h("button", { type: "button", class: "btn small", disabled: kept.has(i), onclick: async () => {
            keepBtn!.disabled = true;
            if (await keep(w, [{ index: i, text: it.text, answer: it.answer }], "cards")) keepBtn!.textContent = "Kept";
            else keepBtn!.disabled = false;
          } }, kept.has(i) ? "Kept" : "Keep as a card")
        : null;
      const reveal = h("div", { class: "study-reveal", hidden: true }, h("p", null, h("strong", null, "Answer: "), it.answer), quoteOf(it), keepBtn);
      return h("li", null, h("p", null, it.text), mine,
        h("button", { type: "button", class: "btn small", onclick: (e: Event) => {
          if (!mine.value.trim() && !confirm("Show the answer without trying first?")) return;
          reveal.hidden = false;
          (e.currentTarget as HTMLButtonElement).remove();
        } }, "Show the answer"), reveal);
    }));

  const drawList = (w: Written) => {
    const rows = w.items.map((it, i) => {
      const pick = h("input", { type: "checkbox", "aria-label": `Keep item ${i + 1}` });
      const tag = h("span", { class: "muted small" });
      const text = h("textarea", { rows: 2, "aria-label": w.kind === "cards" ? "Question" : "Note" }, it.text);
      const answer = w.kind === "cards" ? h("textarea", { rows: 2, "aria-label": "Answer" }, it.answer) : null;
      const li = h("li", { class: it.verified ? "" : "unchecked" }, h("label", { class: "row" }, pick, tag), text, answer, quoteOf(it));
      return { li, pick, tag, text, answer, i, ok: it.verified };
    });
    const mark = () => {
      for (const x of rows) {
        const done = kept.has(x.i);
        x.pick.checked = x.ok && !done;
        x.pick.disabled = !x.ok || done;
        x.tag.textContent = done ? "Kept" : x.ok ? "Keep" : "Cannot be kept: no passage";
      }
      keepBtn.disabled = !rows.some((x) => !x.pick.disabled);
    };
    const keepBtn: HTMLButtonElement = h("button", { type: "button", class: "btn primary", onclick: async () => {
      const chosen = rows.filter((x) => x.pick.checked && !x.pick.disabled).map((x) => ({ index: x.i, text: x.text.value, answer: x.answer?.value ?? "" }));
      if (!chosen.length) return toast("Choose at least one item to keep.", "info");
      keepBtn.disabled = true; // one press, one copy
      await keep(w, chosen);
      mark();
    } }, w.kind === "cards" ? "Add the chosen cards to Review" : "Keep the chosen notes");
    const box = h("div", { class: "stack" }, h("ol", { class: "study-items" }, rows.map((x) => x.li)), h("div", { class: "row end" }, keepBtn));
    mark();
    return box;
  };

  const sentNote = (w: Written) => {
    const parts: string[] = [];
    if (w.left_out) parts.push(`${w.left_out} ${w.left_out === 1 ? "passage was" : "passages were"} not sent (only the first ${MAX_HIGHLIGHTS} highlights fit).`);
    if (w.cut) parts.push(w.source === "section" ? "This section is long: only the part around where you are was sent." : "Long highlights were shortened to fit.");
    return parts.length ? h("p", { class: "muted small" }, parts.join(" ")) : null;
  };

  const draw = (w: Written) => {
    clear(out);
    kept = new Set(w.kept ?? []);
    out.append(h("div", { class: "ai-text" },
      h("div", { class: "ai-text-label" }, `Written by the AI model (${w.provider === "local" ? "on this computer" : w.provider}). ${STATUS[w.status]}`),
      whyLink(w.id),
      sentNote(w),
      w.items.length ? (w.kind === "quiz" ? drawQuiz(w) : drawList(w)) : h("p", null, "The model found nothing it could write from these passages."),
      w.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", w.links.join(" · ")) : null,
      w.warning ? h("div", { class: "ai-text-links" }, w.warning) : null),
      h("button", { type: "button", class: "link small", onclick: () => void run(true) }, "Ask again"));
  };

  const run = async (fresh = false) => {
    clear(out);
    out.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      const res = await api.post<{ result: Written }>(`/api/documents/${r.doc.id}/study-notes`, { source, kind, section_id: source === "section" ? section?.id ?? "" : "", at: r.pacer.ord, fresh });
      draw(res.result);
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "muted small" }, `Nothing written: ${(e as Error).message}`));
    }
  };

  const body = aiIsOn()
    ? h("div", { class: "stack" },
        seg<Source>("From", [["highlights", `My highlights (${r.ann.highlights.length})`], ["section", `This section${section ? `: ${section.title}` : ""}`]], () => source, (v) => (source = v)),
        seg<Kind>("Make", (Object.keys(KIND_LABEL) as Kind[]).map((k) => [k, KIND_LABEL[k]]), () => kind, (v) => (kind = v)),
        h("p", { class: "muted small" }, "The model reads only the passages you choose. Nothing is kept until you pick items and press Keep; what you keep says the model wrote it."),
        h("div", { class: "row end" }, h("button", { type: "button", class: "btn primary", onclick: () => void run() }, "Write")),
        out)
    : h("div", { class: "stack" },
        h("p", null, "Without AI, the Summary sheet gathers your highlights, and highlights and questions become review cards on their own."),
        h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also draft a quiz, flashcards or notes from your highlights or a section."),
        h("div", { class: "row end" }, h("a", { class: "btn", href: `#/summary/${r.doc.id}`, onclick: close }, "Open the summary sheet")));
  return modal("Study notes", h("div", { class: "stack" }, body, h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close"))), { wide: true, onOpen: (m) => (handle = m) });
}

/** Brainstorm for the whole document (milestone 3.2): ideas from your highlights here and the notes nearest them.
 * Without AI, the brainstorm sheet of a note or an idea (Think) is the way to think an idea through. */
export function brainstormDialog(r: Reader): Promise<unknown> {
  r.pacer.pause(false);
  let handle: ModalHandle;
  const close = () => handle.close(null);
  const body = aiIsOn()
    ? aiIdeasBox({ kind: "document", id: r.doc.id })
    : h("div", { class: "stack" },
        h("p", null, "Without AI, turn a highlight into an idea (or open a note) and use its brainstorm sheet in Think: questions to answer first, then what is near it in your notes and reading."),
        h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also suggest ideas from your highlights here, each with the passages it rests on."),
        h("div", { class: "row end" }, h("a", { class: "btn", href: "#/think", onclick: close }, "Open Think")));
  return modal("Brainstorm", h("div", { class: "stack" }, body, h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close"))), { wide: true, onOpen: (m) => (handle = m) });
}
