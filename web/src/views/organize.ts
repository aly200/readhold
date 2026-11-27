// Organize a document (milestone 3.3 of docs/ai/PLAN.md). Without a model: your tags (also your collections on the
// Documents tab), tags suggested by code from related documents and the tags you use, and related documents found by
// the words they share. With AI on, and only when you ask: a model's tag suggestions (yours first, at most two new)
// and its pick of related documents, each checked. Nothing changes until you add a tag, and each add has Undo.
// Text only: h() sets textContent.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, h, type ModalHandle, modal, toast } from "../util";
import { aiIsOn } from "./explain";

interface Related { id: string; title: string; score?: number; shared: string[]; reason?: string }
interface Suggested { tag: string; existing: boolean; reason?: string; verified?: boolean; quote?: string }
interface Overview { tags: string[]; known: string[]; related: Related[]; suggested: Suggested[] }
interface AIResult { id: string; tags: Suggested[]; related: Related[]; reuse: number | null; dropped: number; status: string; links: string[]; warning: string; provider: string }

// as the server's `organize.clean_tag`: a letter first, then letters, digits, "-" or "_"; at most 40
const TAG = /^\p{L}[\p{L}\p{N}_-]{0,39}$/u;

export function organizeDialog(docId: string, title: string, onChange?: () => void): Promise<unknown> {
  let handle: ModalHandle;
  let tags: string[] = [];
  const close = () => handle.close(null);
  const mine = h("div", { class: "org-tags", "aria-live": "polite" });
  const plain = h("div", { class: "stack" });
  const ai = h("div", { class: "study-out", "aria-live": "polite" });

  // every change sends the tags it expects to replace, and an Undo expects exactly the tags its change produced:
  // so neither a stale page nor an Undo after a later change can overwrite anything (the server answers 409)
  let queue: Promise<unknown> = Promise.resolve();
  const buttons = new Map<string, HTMLButtonElement[]>();
  const syncButtons = () => buttons.forEach((bs, t) => bs.forEach((b) => (b.disabled = tags.includes(t))));
  const put = async (next: string[], expect: string[]): Promise<string[] | null> => {
    try {
      tags = (await api.put<{ tags: string[] }>(`/api/documents/${docId}/tags`, { tags: next, expect })).tags;
      return tags;
    } catch (e) {
      toast((e as Error).message, "error");
      await load().catch(() => undefined);
      return null;
    } finally {
      drawMine();
      syncButtons();
      onChange?.();
    }
  };
  const save = (next: (now: string[]) => string[]) => {
    queue = queue.then(async () => {
      const before = tags;
      const after = await put(next(before), before);
      if (after) toast("Tags saved.", "ok", 6000, { label: "Undo", run: () => void (queue = queue.then(() => put(before, after))) });
    });
  };

  const add = (t: string) => {
    const tag = t.trim().replace(/^#/, "").normalize("NFC").toLowerCase().normalize("NFC");
    if (!TAG.test(tag)) return toast("A tag is one word that starts with a letter (use - to join words).", "error");
    save((now) => (now.includes(tag) ? now : [...now, tag]));
  };

  const input = h("input", { type: "text", maxlength: 41, placeholder: "Add a tag", "aria-label": "Add a tag", list: "org-known" });
  const known = h("datalist", { id: "org-known" });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      add(input.value);
      input.value = "";
    }
  });

  // #private (milestone 4.4): never sent to a cloud model; a local model still reads it
  const privateBox = h("input", { type: "checkbox", onchange: () => {
    const on = privateBox.checked;
    save((now) => (on ? (now.includes("private") ? now : [...now, "private"]) : now.filter((t) => t !== "private")));
  } });
  const drawMine = () => {
    privateBox.checked = tags.includes("private");
    clear(mine);
    mine.append(...tags.map((t) => h("span", { class: "chip" }, `#${t} `,
      h("button", { type: "button", class: "link", "aria-label": `Remove #${t}`, onclick: () => save((now) => now.filter((x) => x !== t)) }, "×"))));
    if (!tags.length) mine.append(h("span", { class: "muted small" }, "No tags yet."));
  };

  const addBtn = (s: Suggested) => {
    const b: HTMLButtonElement = h("button", { type: "button", class: "btn small", disabled: tags.includes(s.tag), onclick: () => {
      b.disabled = true;
      add(s.tag);
    } }, `+ #${s.tag}`);
    buttons.set(s.tag, [...(buttons.get(s.tag) ?? []).filter((x) => x.isConnected), b]);
    return b;
  };

  const load = async () => {
    const o = await api.get<Overview>(`/api/organize/${docId}`);
    tags = o.tags;
    clear(known);
    known.append(...o.known.map((t) => h("option", { value: t })));
    drawMine();
    clear(plain);
    plain.append(
      h("h3", null, "Suggested from your library"),
      o.suggested.length
        ? h("ul", { class: "org-list" }, o.suggested.map((s) => h("li", null, addBtn(s), h("span", { class: "muted small" }, ` ${s.reason ?? ""}`))))
        : h("p", { class: "muted small" }, "Nothing yet: tags are suggested when related documents carry them, or when a tag you use names one of this document's main words."),
      h("h3", null, "Related documents"),
      o.related.length
        ? h("ul", { class: "org-list" }, o.related.map((r) => h("li", null, h("a", { href: `#/read/${r.id}`, onclick: close }, r.title), h("span", { class: "muted small" }, ` shares ${r.shared.join(", ")}`))))
        : h("p", { class: "muted small" }, "No other document shares enough of its words yet."));
  };

  const drawAI = (r: AIResult) => {
    clear(ai);
    const reuse = r.reuse === null ? "" : ` ${Math.round(r.reuse * 100)}% of its tags are ones you already use.`;
    ai.append(h("div", { class: "ai-text" },
      h("div", { class: "ai-text-label" }, `Suggested by the AI model (${r.provider === "local" ? "on this computer" : r.provider}).${reuse} A tag with ✓ rests on a passage of this document; the others are its guess.`),
      whyLink(r.id),
      r.tags.length
        ? h("ul", { class: "org-list" }, r.tags.map((s) => h("li", null, addBtn(s),
            h("span", { class: "muted small" }, s.existing ? " one of your tags" : " a new tag"),
            s.verified && s.quote ? h("div", { class: "resume-quote" }, `✓ “${s.quote}”`) : null)))
        : h("p", { class: "muted small" }, "No new tag to suggest."),
      r.dropped ? h("p", { class: "muted small" }, `${r.dropped} more suggestion${r.dropped === 1 ? " was" : "s were"} left out (not a tag, or more than two new ones).`) : null,
      r.related.length
        ? h("div", null, h("h3", null, "Related, by the model"), h("ul", { class: "org-list" }, r.related.map((x) => h("li", null,
            h("a", { href: `#/read/${x.id}`, onclick: close }, x.title), h("div", { class: "muted small" }, `The model's reason: ${x.reason ?? ""}`)))))
        : null,
      r.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", r.links.join(" · ")) : null,
      r.warning ? h("div", { class: "ai-text-links" }, r.warning) : null),
      h("button", { type: "button", class: "link small", onclick: () => void runAI(true) }, "Ask again"));
  };

  const runAI = async (fresh = false) => {
    clear(ai);
    ai.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      drawAI((await api.post<{ result: AIResult }>(`/api/documents/${docId}/organize/suggest`, { fresh })).result);
    } catch (e) {
      clear(ai);
      ai.append(h("p", { class: "muted small" }, `No suggestions: ${(e as Error).message}`));
    }
  };

  void load();
  const body = h("div", { class: "stack" },
    h("p", { class: "muted small" }, `Tags are your collections: the Documents tab can show every document with a tag. Only you add them.`),
    h("h3", null, "Your tags"), mine, h("div", { class: "row" }, input, known),
    h("label", { class: "row" }, privateBox, h("span", null, "Private: never send this document to a cloud model (it adds the tag #private; a local model still reads it)")),
    plain,
    aiIsOn()
      ? h("div", { class: "stack" }, h("h3", null, "From a model"),
          h("p", { class: "muted small" }, "The model reads this document's title, section titles, opening and your highlights, your tags, and the titles of the documents above. Never the whole document."),
          h("div", { class: "row" }, h("button", { type: "button", class: "btn", onclick: () => void runAI() }, "Suggest tags and related documents")), ai)
      : h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also suggest tags (yours first) and related documents."),
    h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close")));
  return modal(`Organize “${title}”`, body, { wide: true, onOpen: (m) => (handle = m) });
}
