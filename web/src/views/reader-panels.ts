// Side panel of the reader: Questions | Notes | Terms.
import { askTab } from "./ask";
import { api } from "../api";
import { mathText } from "../math";
import type { Highlight, HlType, Question } from "../types";
import { askText, clear, h, HL_LABELS, KIND_LABELS, toast } from "../util";
import * as dlg from "./reader-dialogs";
import type { Reader } from "./reader";

const dismissedTemplates = new Set<string>();
export const STARTERS = ["How does", "What proves", "Why does", "What is"];

export async function createQuestion(r: Reader, text: string, opts: { sectionId?: string | null; sectionKind?: string | null; source?: number | null; learn?: boolean } = {}): Promise<Question | null> {
  const t = text.trim();
  if (!t) return null;
  const q = await api.post<Question>("/api/questions", {
    document_id: r.doc.id,
    text: /[?]$/.test(t) ? t : `${t}?`,
    section_id: opts.sectionId ?? null,
    section_kind: opts.learn === false ? null : (opts.sectionKind ?? null),
    source_sentence: opts.source ?? null,
  });
  r.ann.questions.push(q);
  r.renderSide();
  r.renderMap();
  r.updateProgress();
  return q;
}

export function renderSidePanel(r: Reader): void {
  const el = r.sideEl;
  clear(el);
  const tab = (id: typeof r.sideTab, label: string, count: number) =>
    h("button", { class: `tab ${r.sideTab === id ? "on" : ""}`, role: "tab", "aria-selected": r.sideTab === id, onclick: () => ((r.sideTab = id), renderSidePanel(r)) }, label, count ? h("span", { class: "count" }, String(count)) : null);
  el.append(
    h(
      "div",
      { class: "tabs", role: "tablist" },
      tab("questions", "Questions", r.ann.questions.length),
      tab("notes", "Notes", r.ann.highlights.length + r.ann.notes.length),
      tab("terms", "Terms", r.ann.terms.filter((t) => !t.is_concept).length + Object.keys(r.ann.acronyms).length),
      tab("ask", "Ask", 0),
    ),
  );
  const body = h("div", { class: "tab-body" });
  el.append(body);
  if (r.sideTab === "questions") questionsTab(r, body);
  else if (r.sideTab === "notes") notesTab(r, body);
  else if (r.sideTab === "ask") askTab(r, body);
  else termsTab(r, body);
}

function questionsTab(r: Reader, body: HTMLElement): void {
  const cur = r.idx[r.pacer.ord];
  const sec = cur?.sec;
  if (r.session?.info.question) body.append(h("div", { class: "job" }, h("span", { class: "muted small" }, "This session's question"), h("strong", null, r.session.info.question)));

  // Templates for the current section type (accept or dismiss).
  if (sec) {
    api.get<string[]>(`/api/templates?kind=${encodeURIComponent(sec.kind)}`).then((list) => {
      const have = new Set(r.ann.questions.map((q) => q.text));
      const fresh = list.filter((t) => !have.has(t) && !dismissedTemplates.has(`${sec.kind}:${t}`));
      if (!fresh.length || r.sideTab !== "questions") return;
      const box = h(
        "div",
        { class: "templates" },
        h("div", { class: "muted small" }, `Suggested for ${KIND_LABELS[sec.kind] ?? "this section"}`),
        fresh.map((t) =>
          h(
            "div",
            { class: "template" },
            h("span", null, t),
            h("button", { class: "btn small", title: "Add this question", onclick: () => createQuestion(r, t, { sectionId: sec.id, sectionKind: sec.kind, learn: false }) }, "+"),
            h("button", { class: "btn small ghost", title: "Not useful", onclick: () => (dismissedTemplates.add(`${sec.kind}:${t}`), renderSidePanel(r)) }, "×"),
          ),
        ),
      );
      body.querySelector(".templates")?.remove();
      body.insertBefore(box, body.querySelector(".q-list"));
    });
  }

  const list = h("ol", { class: "q-list" });
  r.ann.questions.forEach((q, i) => {
    list.append(
      h(
        "li",
        { class: `q ${q.answer ? "answered" : ""}` },
        h("span", { class: "q-num", title: `Press Q then ${i + 1} to tag the current paragraph` }, String(i + 1)),
        h(
          "div",
          { class: "q-main" },
          h("div", { class: "q-text" }, q.text),
          h("div", { class: "muted small" }, q.paragraphs.length ? `${q.paragraphs.length} paragraph${q.paragraphs.length > 1 ? "s" : ""} tagged` : "Not tagged yet — Q then " + (i + 1), q.answer ? " · answered" : ""),
          q.answer ? h("div", { class: "q-answer" }, q.answer) : null,
          h(
            "div",
            { class: "row" },
            h("button", { class: "btn small primary", onclick: () => dlg.recall(r, q) }, q.answer ? "Recall again" : "Recall"),
            q.paragraphs.length ? h("button", { class: "btn small", onclick: () => jumpToParagraph(r, q.paragraphs[0]) }, "Go to answer") : null,
            h("button", { class: "btn small ghost", "aria-label": "Delete question", onclick: () => deleteQuestion(r, q) }, "Delete"),
          ),
        ),
      ),
    );
  });
  body.append(list);

  const input = h("input", { type: "text", placeholder: "Write a question to read for…", "aria-label": "New question" });
  const add = () => createQuestion(r, input.value, { sectionId: sec?.id, sectionKind: sec?.kind }).then(() => (input.value = ""));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") add();
  });
  body.append(
    h(
      "div",
      { class: "add-q" },
      h("div", { class: "row wrap" }, STARTERS.map((s) => h("button", { class: "btn small", onclick: () => ((input.value = s + " "), input.focus()) }, `${s}…`))),
      h("div", { class: "row" }, input, h("button", { class: "btn", onclick: add }, "Add")),
      h("button", { class: "btn small", onclick: () => dlg.claimBuilder(r) }, "Turn claims into questions"),
    ),
  );
}

function jumpToParagraph(r: Reader, pid: string): void {
  for (const x of r.idx) if (x && x.p.id === pid) return r.jumpTo(x.s.ord);
}

async function deleteQuestion(r: Reader, q: Question): Promise<void> {
  await api.del(`/api/questions/${q.id}`);
  r.ann.questions = r.ann.questions.filter((x) => x.id !== q.id);
  r.renderSide();
  r.renderMap();
  for (const pid of q.paragraphs) {
    const x = r.idx.find((y) => y && y.p.id === pid);
    if (x) r.rerenderParagraphOf(x.s.ord);
  }
}

function notesTab(r: Reader, body: HTMLElement): void {
  const types: HlType[] = ["claim", "evidence", "definition", "confusing", "idea"];
  body.append(h("p", { class: "muted small" }, "Keys 1–5 highlight the current sentence (or your selection): 1 Claim · 2 Evidence · 3 Definition · 4 Confusing · 5 Idea. N adds a margin note."));
  for (const t of types) {
    const items = r.ann.highlights.filter((x) => x.type === t);
    if (!items.length) continue;
    body.append(h("h3", { class: `hl-head hl-${t}` }, HL_LABELS[t], h("span", { class: "count" }, String(items.length))));
    body.append(h("ul", { class: "hl-list" }, items.map((x) => hlItem(r, x))));
  }
  if (r.ann.notes.length) {
    body.append(h("h3", null, "Margin notes"));
    body.append(
      h(
        "ul",
        { class: "hl-list" },
        r.ann.notes.map((n) => h("li", null, h("button", { class: "link", onclick: () => r.jumpTo(n.sentence) }, n.text), h("div", { class: "muted small" }, n.origin === "ai" ? "Written by the AI model · " : "", r.idx[n.sentence]?.s.text.slice(0, 80) ?? ""))),
      ),
    );
  }
  if (!r.ann.highlights.length && !r.ann.notes.length) body.append(h("p", { class: "empty" }, "No highlights yet. They will build your summary sheet when you finish."));
}

function hlItem(r: Reader, x: Highlight): HTMLElement {
  return h(
    "li",
    { class: x.resolved ? "resolved" : "" },
    h("button", { class: "link", onclick: () => r.jumpTo(x.sentence) }, x.text.length > 160 && !x.text.includes("\\") ? x.text.slice(0, 160) + "…" : mathText(x.text)),
    x.note ? h("div", { class: "hl-note" }, x.note) : null,
    x.cloze ? h("div", { class: "muted small" }, `Blank card: “${x.cloze}”`) : null,
    h(
      "div",
      { class: "row" },
      h(
        "button",
        {
          class: "btn small ghost",
          onclick: async () => {
            const note = await askText("Note", x.type === "definition" ? "Which term does this define?" : "Your note", x.note);
            if (note === null) return;
            Object.assign(x, await api.patch<Highlight>(`/api/highlights/${x.id}`, { note }));
            renderSidePanel(r);
          },
        },
        x.type === "definition" ? "Name the term" : "Note",
      ),
      x.type === "evidence" ? h("button", { class: "btn small ghost", onclick: () => dlg.clozePicker(r, x) }, x.cloze ? "Change blank" : "Make blank card") : null,
      x.type === "confusing"
        ? h(
            "button",
            {
              class: "btn small ghost",
              onclick: async () => {
                Object.assign(x, await api.patch<Highlight>(`/api/highlights/${x.id}`, { resolved: !x.resolved }));
                toast(x.resolved ? "Resolved — nice" : "Back on the confusing list");
                renderSidePanel(r);
              },
            },
            x.resolved ? "Reopen" : "Got it now",
          )
        : null,
      h("button", { class: "btn small ghost", onclick: () => r.highlight(x.type, x.sentence, x.end_sentence) }, "Remove"),
    ),
  );
}

function termsTab(r: Reader, body: HTMLElement): void {
  const input = h("input", { type: "text", placeholder: "A word or phrase…", "aria-label": "Term to look up" });
  const go = () => input.value.trim() && dlg.guessGate(r, input.value.trim());
  input.addEventListener("keydown", (e) => e.key === "Enter" && go());
  body.append(h("div", { class: "row" }, input, h("button", { class: "btn primary", onclick: go }, "Guess, then reveal")), h("p", { class: "muted small" }, "Or select text in the page and press G. You guess first; then the app shows where the document defines it."));
  const terms = r.ann.terms.filter((t) => !t.is_concept);
  if (terms.length) {
    body.append(h("h3", null, "Your glossary for this document"));
    body.append(
      h(
        "dl",
        { class: "glossary" },
        terms.map((t) => [h("dt", null, h("button", { class: "link", onclick: () => (t.sentence !== null ? r.jumpTo(t.sentence) : undefined) }, t.term)), h("dd", null, t.definition || h("em", null, `guess: ${t.guess}`))]),
      ),
    );
  }
  const acr = Object.entries(r.ann.acronyms);
  if (acr.length) {
    body.append(h("h3", null, "Acronyms found"));
    body.append(h("dl", { class: "glossary" }, acr.map(([k, v]) => [h("dt", null, k), h("dd", null, v)])));
  }
  const concepts = r.ann.terms.filter((t) => t.is_concept);
  if (concepts.length) {
    body.append(h("h3", null, "Concepts (from `code` terms)"));
    body.append(h("div", { class: "row wrap" }, concepts.map((c) => h("button", { class: "chip", onclick: () => dlg.guessGate(r, c.term) }, c.term))));
  }
}
