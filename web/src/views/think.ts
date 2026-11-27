// Think: step 1 of the agent. No AI model is used: every reason on this page is counted from your own words.
// - Today's ideas: a few notes or ideas worth another look, each with the reason it was picked.
// - For you to approve: small changes the app proposes (a link, a tag, filing an idea). Nothing changes until
//   you accept, accepting can be undone, and one you turn down is not offered again.
// - The brainstorm sheet (#/think/page/<id>, #/think/idea/<id>): the idea, six questions you answer first, then
//   what is near it in your notes and reading. What you write is saved as a note as you type.
// All text is drawn with text nodes. Changes go through POST /api/think/... on this machine.
import { notesHead } from "./libtabs";
import { api } from "../api";
import { openCapture } from "../capture";
import { mathText } from "../math";
import type { BrainstormData, NotePage, ThinkData, Todo } from "../types";
import { clear, debounce, h, toast } from "../util";
import { aiIdeasBox } from "./aibrainstorm";
import { ymd } from "./plan";

const SIGNAL: Record<string, string> = { quest: "Close to what you work on", question: "An open question", orphan: "Not connected yet", resting: "Waiting for a while" };
const KIND_LABEL: Record<string, string> = { link: "Link two notes", mention: "Make a mention a link", file_idea: "File an idea", tag: "Add a tag" };
/** the questions of a brainstorm sheet; each is a heading in the saved note, so the wording must stay as it is */
const PROMPTS: { q: string; hint: string }[] = [
  { q: "In one sentence, what is the idea?", hint: "Say it plainly, as if to a friend." },
  { q: "Why does it matter to you?", hint: "What would change if it were true?" },
  { q: "What would make it wrong?", hint: "The strongest objection you can think of." },
  { q: "What does it connect to?", hint: "Another note, something you read, a goal." },
  { q: "What is the smallest way to test or use it?", hint: "Something you could do in ten minutes." },
  { q: "What question does it leave open?", hint: "The next thing you would want to know." },
];

export async function thinkView(root: HTMLElement, sub?: string, id?: string): Promise<() => void> {
  if ((sub === "page" || sub === "idea") && id) return sheetView(root, sub, id);
  let data = await api.get<ThinkData>(`/api/think?day=${ymd(new Date())}`);
  const page = h("section", { class: "think" });
  root.append(page);
  const reload = async () => {
    data = await api.get<ThinkData>(`/api/think?day=${ymd(new Date())}`);
    render();
  };

  const pickCard = (p: ThinkData["picks"][number]): HTMLElement =>
    h("div", { class: `isle think-card ${p.status === "opened" ? "is-opened" : ""}` },
      h("div", { class: "kicker" }, `${p.kind === "idea" ? "Idea" : "Note"} · ${SIGNAL[p.signal] ?? "Picked for today"}`),
      h("h3", null, p.title),
      p.snippet && p.snippet !== p.title ? h("p", { class: "think-snippet" }, p.snippet) : null,
      h("p", { class: "think-why" }, h("strong", null, "Why today: "), p.reason),
      h("div", { class: "row wrap think-actions" },
        h("a", { class: "btn primary", href: `#/think/${p.kind}/${p.item_id}`, onclick: () => void api.post(`/api/think/picks/${p.id}`, { status: "opened" }).catch(() => undefined) }, "Think about it"),
        h("a", { class: "btn", href: p.kind === "page" ? `#/notes/${p.item_id}` : "#/ideas" }, p.kind === "page" ? "Open the note" : "Open the inbox"),
        h("button", { class: "btn ghost", type: "button", onclick: async () => {
          await api.post(`/api/think/picks/${p.id}`, { status: "dismissed" });
          await reload();
        } }, "Not today")));

  const suggestionCard = (s: ThinkData["suggestions"][number]): HTMLElement =>
    h("div", { class: "isle think-card" },
      h("div", { class: "kicker" }, KIND_LABEL[s.kind] ?? "Suggestion"),
      h("h3", null, s.title),
      s.quote ? h("blockquote", { class: "think-quote" }, s.quote) : null,
      h("p", { class: "think-why" }, h("strong", null, "Why: "), s.reason),
      h("p", { class: "muted small think-change" }, h("strong", null, "If you accept: "), s.change),
      h("div", { class: "row wrap think-actions" },
        h("button", { class: "btn primary", type: "button", onclick: async () => {
          try {
            await api.post(`/api/think/suggestions/${s.id}/accept`, {});
          } catch (e) {
            toast((e as Error).message, "info");
            return void reload();
          }
          toast("Done.", "ok", 8000, { label: "Undo", run: async () => {
            try {
              await api.post(`/api/think/suggestions/${s.id}/undo`, {});
              await reload();
            } catch (e) {
              toast((e as Error).message, "info");
            }
          } });
          await reload();
        } }, "Accept"),
        h("button", { class: "btn", type: "button", title: "It will not be offered again", onclick: async () => {
          await api.post(`/api/think/suggestions/${s.id}/reject`, {});
          await reload();
        } }, "Not this"),
        s.notes.map((n) => h("a", { class: "btn ghost", href: `#/notes/${n.id}`, title: "Open this note" }, `↗ ${n.title}`))));

  const render = () => {
    clear(page);
    page.append(
      notesHead("think", h("button", { class: "btn primary", type: "button", title: "Capture a thought (Ctrl+J)", onclick: () => void openCapture() }, "+ Capture")),
      h("p", { class: "isle think-intro muted" }, "A few ideas to come back to today, and small changes for you to approve. No AI model is used yet: every reason here is counted from your own words, so you can check it."),
      h("h2", { class: "hub-section" }, h("span", null, "Today's ideas"), h("small", null, "with the reason for each")),
      data.picks.length
        ? h("div", { class: "think-grid" }, data.picks.map(pickCard))
        : h("p", { class: "isle think-empty" }, "Nothing to bring back today. Notes and ideas show up here once they have rested a few days, hold an open question, or touch what you are working on."),
      h("h2", { class: "hub-section" }, h("span", null, "For you to approve"), h("small", null, "nothing changes until you accept")),
      data.suggestions.length
        ? h("div", { class: "think-grid" }, data.suggestions.map(suggestionCard))
        : h("p", { class: "isle think-empty" }, "No suggestions right now. They appear when two notes are about the same thing, a note names another one, or an idea fits a note. At most five new ones a day."),
      h("p", { class: "isle think-foot muted small" }, `${data.decided.accepted} accepted · ${data.decided.rejected} turned down so far. A suggestion you turn down is not offered again.`));
  };
  render();
  return () => undefined;
}

// ------------------------------------------------------------------ the brainstorm sheet
async function sheetView(root: HTMLElement, kind: "page" | "idea", id: string): Promise<() => void> {
  const data = await api.get<BrainstormData>(`/api/think/brainstorm?kind=${kind}&id=${id}`);
  const item = data.item;
  // what is already written, read back from the sheet's note: "## question" then the answer
  const answers = new Map<string, string>();
  let extra = "";
  const known = new Set(PROMPTS.map((p) => p.q));
  /** the sections that are not one of the questions: ones you added by hand, and ideas kept from the model */
  const readExtra = (sheetBody: string, withAnswers: boolean): string => {
    let more = "";
    for (const part of sheetBody.split(/^## /m).slice(1)) {
      const nl = part.indexOf("\n");
      const head = (nl < 0 ? part : part.slice(0, nl)).trim();
      const text = nl < 0 ? "" : part.slice(nl + 1).trim();
      if (known.has(head)) {
        if (withAnswers) answers.set(head, text);
      } else more += `## ${head}\n${text}\n\n`; // kept as it is
    }
    return more;
  };
  if (data.sheet) extra = readExtra(data.sheet.body, true);
  let sheetId = data.sheet?.id ?? "";
  let revealed = [...answers.values()].some((a) => a.trim()) || (!data.near.length && !data.reading.length);
  const status = h("span", { class: "muted small", "aria-live": "polite" });
  const linkable = !/[\[\]|#\n]/.test(item.title) && item.title.length <= 190;
  const body = (): string => {
    const top = kind === "page" && linkable ? `About [[${item.title}]].` : `> ${item.text.replace(/\s*\n\s*/g, " ").slice(0, 600)}`;
    const parts = PROMPTS.filter((p) => (answers.get(p.q) ?? "").trim()).map((p) => `## ${p.q}\n${answers.get(p.q)!.trim()}\n`);
    return `${top}\n\n${parts.join("\n")}${extra ? `\n${extra.trim()}\n` : ""}`;
  };
  let saving: Promise<unknown> = Promise.resolve();
  // while ideas from the model are being kept, saves wait (typing goes on): a save in between would write the sheet
  // without them. Once the sheet is read back, one save carries what you typed meanwhile.
  let holding = false;
  let pending = false;
  const save = debounce(() => {
    if (holding) {
      pending = true;
      return;
    }
    status.textContent = "Saving…";
    saving = saving.then(async () => {
      if (sheetId) {
        // the other sections (yours, and ideas kept from the model, maybe in another window) are read back first,
        // so this save never writes over what was added to the sheet since this page opened
        extra = readExtra((await api.get<NotePage>(`/api/pages/${sheetId}`)).body, false);
        await api.patch<NotePage>(`/api/pages/${sheetId}`, { body: body() });
      }
      else {
        try {
          sheetId = (await api.post<NotePage>("/api/pages", { title: data.sheet_title, body: body() })).id;
        } catch {
          // a note with that title appeared meanwhile: write into it
          sheetId = (await api.post<NotePage>("/api/pages/open", { title: data.sheet_title })).id;
          await api.patch<NotePage>(`/api/pages/${sheetId}`, { body: body() });
        }
        open.hidden = false;
        open.setAttribute("href", `#/notes/${sheetId}`);
      }
      status.textContent = "Saved as a note";
    }).catch((e: Error) => {
      status.textContent = "Not saved";
      toast(`Couldn't save: ${e.message}`, "error");
    });
  }, 600);

  // ideas from a model: like what is near, shown once you have written first (attempt before reveal). Before a keep,
  // what you typed is saved; after it, the sheet is read back, so the next save keeps the ideas the model added.
  const ideas = aiIdeasBox({ kind, id }, {
    before: async () => {
      save.flush();
      await saving;
      holding = true;
    },
    after: async () => {
      try {
        const again = await api.get<BrainstormData>(`/api/think/brainstorm?kind=${kind}&id=${id}`);
        if (again.sheet) {
          extra = readExtra(again.sheet.body, false);
          sheetId = again.sheet.id;
          open.hidden = false;
          open.setAttribute("href", `#/notes/${sheetId}`);
        }
      } finally {
        holding = false;
        if (pending) {
          pending = false;
          save();
        }
      }
    },
  });
  const around = h("aside", { class: "think-around", "aria-label": "What is near this idea" });
  const drawAround = () => {
    clear(around);
    if (!revealed) {
      around.append(h("div", { class: "isle think-hidden" },
        h("h2", null, "Near it"),
        h("p", { class: "muted" }, `${data.near.length} of your notes and ${data.reading.length} passage${data.reading.length === 1 ? "" : "s"} you highlighted are close to this. They show once you have written your own first sentence, so your thinking comes first.`),
        h("button", { class: "btn small", type: "button", onclick: () => ((revealed = true), drawAround()) }, "Show them now")));
      return;
    }
    around.append(
      h("div", { class: "isle" }, h("h2", null, "Near it in your notes"),
        data.near.length
          ? h("ul", { class: "around-list" }, data.near.map((n) => h("li", null,
              h("a", { href: n.kind === "page" ? `#/notes/${n.id}` : `#/think/idea/${n.id}` }, n.kind === "idea" ? "💡 " : "📝 ", n.title),
              h("span", { class: "around-context" }, `shares ${n.shared.join(", ")}`))))
          : h("p", { class: "muted small" }, "No other note or idea shares its words yet.")),
      h("div", { class: "isle" }, h("h2", null, "From your reading"),
        data.reading.length
          ? h("ul", { class: "around-list" }, data.reading.map((r) => h("li", null,
              h("a", { href: `#/read/${r.document_id}?s=${r.sentence}`, title: "Open the document at this sentence" }, mathText(r.text)),
              h("span", { class: "around-context" }, `${r.type} · ${r.title} · shares ${r.shared.join(", ")}`))))
          : h("p", { class: "muted small" }, "None of your highlights share its words yet.")),
      h("div", { class: "isle" }, h("h2", null, "Ideas from a model"), ideas));
  };

  const open = h("a", { class: "btn small", href: `#/notes/${sheetId}`, hidden: !sheetId }, "Open the sheet as a note");
  const fields = PROMPTS.map((p, i) => {
    const ta = h("textarea", { rows: 2, placeholder: i === 3 && data.near[0] ? `For example: how does it connect to “${data.near[0].title}”?` : p.hint, "aria-label": p.q }, answers.get(p.q) ?? "");
    const fit = () => {
      ta.style.height = "auto";
      ta.style.height = `${ta.scrollHeight + 2}px`;
    };
    ta.addEventListener("input", () => {
      answers.set(p.q, ta.value);
      fit();
      save();
      if (!revealed && i === 0 && ta.value.trim().length >= 12) ((revealed = true), drawAround());
    });
    requestAnimationFrame(fit);
    return h("label", { class: "think-q" }, h("span", null, p.q), ta);
  });
  const toTask = h("button", { class: "btn small", type: "button", title: "Make the smallest test a task for today", onclick: async () => {
    const text = (answers.get(PROMPTS[4].q) ?? "").trim().split("\n")[0];
    if (!text) return toast("Write the smallest way to test it first.", "info");
    save.flush();
    await saving;
    await api.post<Todo>("/api/todos", { text: text.slice(0, 500), minutes: 10, due: ymd(new Date()), ...(sheetId ? { link_type: "page", link_id: sheetId } : {}) });
    toast("Added to today's plan.", "ok", 4000, { label: "Open Plan", run: () => void (location.hash = "#/plan") });
  } }, "Smallest test → task");

  root.append(h("section", { class: "think sheet" },
    h("header", { class: "isle page-head" },
      h("div", { class: "row between wrap" }, h("a", { class: "btn ghost", href: "#/think" }, "← Think"),
        kind === "page" ? h("a", { class: "btn ghost", href: `#/notes/${item.id}` }, "Open the note") : item.document_id ? h("a", { class: "btn ghost", href: `#/read/${item.document_id}${item.sentence !== null && item.sentence !== undefined ? `?s=${item.sentence}` : ""}` }, `From “${item.document_title ?? "a document"}”`) : null),
      h("div", { class: "kicker" }, kind === "idea" ? "Brainstorm · an idea" : "Brainstorm · a note"),
      h("h1", null, item.title),
      item.text.trim() && item.text.trim() !== item.title ? h("p", { class: "think-source" }, mathText(item.text.length > 700 ? `${item.text.slice(0, 700)}…` : item.text)) : null),
    h("div", { class: "think-cols" },
      h("div", { class: "isle think-sheet" },
        h("p", { class: "muted small" }, "Answer what you can, in any order. What you write is saved as a note as you type."),
        fields,
        h("div", { class: "row wrap think-actions" }, status, h("span", { class: "steady-write-gap" }), toTask, open)),
      around)));
  drawAround();
  return () => save.flush();
}
