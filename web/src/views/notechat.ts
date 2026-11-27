// Note chat (milestone 5.4 of docs/ai/PLAN.md): tell a model what to do with the note you are in ("make it more
// formatted", "enhance it", "write an idea about a story"). It replies and proposes either the whole note rewritten
// (Use this, with Undo) or new text for the end of the note (Add to the note, with Undo). Nothing changes until you
// press one, and only while the note is still as the model saw it. Text only: h() sets textContent.
import { api } from "../api";
import { clear, h, type ModalHandle, modal, toast } from "../util";
import { aiIsOn } from "./explain";
import { whyLink } from "./why";

interface Turn { who: "you" | "model"; text: string }
interface Answer {
  id: string; reply: string; action: "replace" | "add" | "none"; text: string; original: string;
  new_words: string[]; restored: string[]; shorter: boolean; missing_words: string[]; warning: string;
}

const MAX_TURNS = 12;
const memo = new Map<string, Turn[]>(); // each note's conversation, kept while the app is open (never saved)
const marks = (words: string[]) => words.flatMap((w, i) => (i ? [", ", h("mark", null, w)] : [h("mark", null, w)]));

/** `before` saves what you typed; `after` shows the note again once it changed. */
export function noteChatDialog(pageId: string, before: () => Promise<void>, after: () => void): Promise<unknown> {
  let handle: ModalHandle;
  const close = () => handle.close(null);
  if (!aiIsOn()) {
    return modal("Ask a model about this note", h("div", { class: "stack" },
      h("p", null, "Without AI, ✨ Tidy fixes the spacing and lists of this note, and you write the rest yourself."),
      h("p", { class: "muted small" }, "With AI switched on in Settings, you can tell a model what to do with this note: format it, enhance it, or write something new. You choose whether to use what it proposes."),
      h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close"))), { onOpen: (m) => (handle = m) });
  }
  const turns = memo.get(pageId) ?? [];
  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  const out = h("div", { class: "stack" });
  const input = h("textarea", { rows: 2, maxlength: 2000, placeholder: "For example: make this note more formatted · enhance it · write an idea for a story", "aria-label": "What should the model do with this note?" });
  const send = h("button", { type: "button", class: "btn primary" }, "Send");

  const drawLog = () => {
    clear(log);
    log.append(...turns.map((t) => h("p", { class: `chat-turn ${t.who}` }, h("strong", null, t.who === "you" ? "You: " : "Model: "), t.text)));
  };
  /** Write `to` into the note, only while it still reads `from`; Undo puts `from` back while nothing changed since. */
  const write = async (from: string, to: string, done: string) => {
    const now = (await api.get<{ body: string }>(`/api/pages/${pageId}`)).body;
    if (now !== from) return toast("The note changed since the model read it. Send your message again.", "error");
    await api.patch(`/api/pages/${pageId}`, { body: to });
    after();
    toast(done, "ok", 9000, { label: "Undo", run: async () => {
      const cur = (await api.get<{ body: string }>(`/api/pages/${pageId}`)).body;
      if (cur !== to) return toast("The note changed since. Edit it by hand to take the change out.", "error");
      await api.patch(`/api/pages/${pageId}`, { body: from });
      after();
    } });
  };
  const drawAnswer = (a: Answer) => {
    clear(out);
    if (a.action === "none") {
      if (a.warning) out.append(h("div", { class: "ai-text-links" }, a.warning));
      return;
    }
    const replace = a.action === "replace";
    const joined = a.original.trim() ? `${a.original.replace(/\s+$/, "")}\n\n${a.text}` : a.text;
    out.append(h("div", { class: "ai-text" },
      h("div", { class: "ai-text-label" }, replace ? "The note rewritten by the AI model. Nothing changes until you press Use." : "Text written by the AI model, for the end of your note. Nothing changes until you press Add.", whyLink(a.id)),
      h("pre", { class: "tidy-pre" }, a.text),
      replace && a.new_words.length ? h("div", { class: "tidy-new" }, "Words you did not write: ", ...marks(a.new_words)) : null,
      replace && a.restored.length ? h("div", { class: "muted small" }, "Put back at the end because the model left them out: ", a.restored.join("  ")) : null,
      replace && a.shorter ? h("div", { class: "tidy-new" }, "Much shorter than your note. Words that went missing: ", ...marks(a.missing_words)) : null,
      a.warning ? h("div", { class: "ai-text-links" }, a.warning) : null,
      h("div", { class: "row wrap" },
        replace
          ? h("button", { type: "button", class: "btn small primary", onclick: () => void write(a.original, a.text, "Note rewritten.") }, "Use this")
          : h("button", { type: "button", class: "btn small primary", onclick: () => void write(a.original, joined, "Added to the note.") }, "Add to the note"))));
  };
  const run = async () => {
    const text = input.value.trim();
    if (!text) return;
    const next: Turn[] = [...turns, { who: "you" as const, text }].slice(-MAX_TURNS);
    if (next[0]?.who === "model") next.shift();
    send.disabled = true;
    clear(out);
    out.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      await before();
      const a = (await api.post<{ result: Answer }>(`/api/notes/${pageId}/chat`, { messages: next })).result;
      turns.splice(0, turns.length, ...next, { who: "model" as const, text: a.reply || "(no reply)" });
      memo.set(pageId, turns);
      input.value = "";
      drawLog();
      drawAnswer(a);
    } catch (e) {
      clear(out);
      toast(`Not sent: ${(e as Error).message}`, "error");
    } finally {
      send.disabled = false;
    }
  };
  send.addEventListener("click", () => void run());
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void run();
    }
  });
  drawLog();
  const body = h("div", { class: "stack" },
    h("p", { class: "muted small" }, "The model reads this note and what you write here. It can rewrite the note or write something new for its end; you choose whether to use it."),
    log,
    h("div", { class: "row" }, input, send),
    out,
    h("div", { class: "row between" },
      h("button", { type: "button", class: "link small", onclick: () => (turns.splice(0), memo.delete(pageId), drawLog(), clear(out)) }, "Start over"),
      h("button", { type: "button", onclick: close }, "Close")));
  return modal("Ask a model about this note", body, { wide: true, onOpen: (m) => (handle = m) });
}
