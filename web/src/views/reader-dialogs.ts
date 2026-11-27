// Reader dialogs: session setup, checkpoints (prediction / recall), guess gate, peeks, explain-it, end session.
import { ambience } from "../ambience";
import { feelRow } from "../feel";
import { displayEquation, mathEl, mathText, plainMath } from "../math";
import { api, save } from "../api";
import { applyComfort, comfortFor, FONTS, saveSettings, state } from "../state";
import type { Energy, Highlight, Note, Quest, Question, QuestStep, Section, Term } from "../types";
import { askText, clear, fmtMinutes, h, type ModalHandle, modal, toast } from "../util";
import { ymd } from "./plan";
import { createQuestion, STARTERS } from "./reader-panels";
import type { Reader } from "./reader";
import { aiIsOn, codeRange, explainSelection } from "./explain";
import { resumeSlot } from "./resume";

// ------------------------------------------------------------------ session start / end
export interface SessionSetup {
  energy: Energy;
  minutes: number;
  question: string;
  questId: string | null;
  parked: boolean;
}

/** Side-quest check: does this reading answer one of the main quest's questions? Link it, time-box it, or park it. */
async function questCheck(r: Reader): Promise<{ el: HTMLElement | null; result: () => { questId: string | null; parked: boolean; minutes?: number } }> {
  let quest: Quest | null = null;
  try {
    quest = await api.get<Quest | null>("/api/quest/active");
  } catch {
    /* no quest info: no check */
  }
  if (!quest || !quest.questions.length) return { el: null, result: () => ({ questId: null, parked: false }) };
  const step = quest.steps.find((s) => s.document_id === r.doc.id && !s.done_at);
  const linked = quest.questions.find((q) => q.id === r.doc.quest_question_id || (step && q.id === step.question_id));
  if (linked || step) {
    return {
      el: h("div", { class: "quest-check ok" }, h("span", { class: "kicker" }, "Main goal"), linked ? ` Reads for: ${linked.text}` : ` Step: ${step!.title}`),
      result: () => ({ questId: quest.id, parked: false }),
    };
  }
  let choice: { questId: string | null; parked: boolean; minutes?: number } = { questId: null, parked: false };
  const note = h("div", { class: "muted small" });
  const row = h("div", { class: "row wrap" });
  const box = h(
    "div",
    { class: "quest-check" },
    h("div", null, h("span", { class: "kicker" }, "Side-goal check"), ` Does this answer a question of “${quest.title}”?`),
    row,
    note,
  );
  const mark = (btn: HTMLElement) => {
    row.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
  };
  quest.questions.forEach((q, i) => {
    const b = h("button", {
      class: "chip",
      onclick: async () => {
        mark(b);
        await save("post", "/api/side-quests", { text: r.doc.title, decision: "linked", question_id: q.id, document_id: r.doc.id });
        r.doc.quest_question_id = q.id;
        choice = { questId: quest.id, parked: false };
        note.textContent = "Linked. This reading now counts for your main goal.";
      },
    }, `Q${i + 1}: ${q.text}`);
    row.append(b);
  });
  const timebox = h("button", {
    class: "chip",
    onclick: () => {
      mark(timebox);
      choice = { questId: null, parked: false, minutes: 15 };
      void save("post", "/api/side-quests", { text: r.doc.title, decision: "timeboxed", minutes: 15, document_id: r.doc.id });
      note.textContent = "Side goal: a 15-minute box, then back to the main goal.";
    },
  }, "No, give it 15 min");
  const park = h("button", {
    class: "chip",
    onclick: () => {
      mark(park);
      choice = { questId: null, parked: true };
      note.textContent = "It'll wait in your parked list. Start takes you back to Today.";
    },
  }, "No, park it for later");
  row.append(timebox, park);
  return {
    el: box,
    result: () => {
      if (choice.parked) void save("post", "/api/side-quests", { text: r.doc.title, decision: "parked", document_id: r.doc.id });
      return choice;
    },
  };
}

export async function sessionSetup(r: Reader): Promise<SessionSetup> {
  let energy: Energy = state.energy;
  let minutes = 15;
  const check = await questCheck(r);
  const qInput = h("input", { type: "text", placeholder: "Optional: the one question this session should answer", "aria-label": "Session question" });
  const pick = (group: HTMLElement, btn: HTMLElement) => {
    group.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
  };
  const energyRow = h("div", { class: "seg", role: "group", "aria-label": "Energy" });
  (["low", "medium", "high"] as Energy[]).forEach((e) => {
    const b = h("button", { class: e === energy ? "on" : "", onclick: () => ((energy = e), pick(energyRow, b)) }, e === "low" ? "Low — slow & gentle" : e === "medium" ? "Medium" : "High — faster");
    energyRow.append(b);
  });
  const boxRow = h("div", { class: "seg", role: "group", "aria-label": "Time box" });
  [10, 15, 25].forEach((m) => {
    const b = h("button", { class: m === minutes ? "on" : "", onclick: () => ((minutes = m), pick(boxRow, b)) }, `${m} min`);
    boxRow.append(b);
  });
  const open = r.ann.questions.filter((q) => !q.answer);
  const leftOff = resumeSlot(r.doc.id); // "where you left off": facts, and a recap from the model if you ask. It fills in by itself
  return new Promise((resolve) => {
    let handle: ModalHandle;
    const start = () => handle.close("go");
    qInput.addEventListener("keydown", (e) => e.key === "Enter" && start());
    modal(
      "Start a session",
      h(
        "div",
        { class: "stack" },
        h("div", { class: "muted" }, r.doc.title),
        leftOff,
        check.el,
        h("label", { class: "field" }, h("span", null, "Energy"), energyRow),
        h("label", { class: "field" }, h("span", null, "Time box"), boxRow),
        h("label", { class: "field" }, h("span", null, "Read to answer"), qInput),
        open.length ? h("div", { class: "row wrap" }, open.slice(0, 4).map((q) => h("button", { class: "chip", onclick: () => (qInput.value = q.text) }, q.text))) : null,
        h("div", { class: "row end" }, h("button", { class: "primary", autofocus: true, onclick: start }, "Start reading (Enter)")),
      ),
      { onOpen: (m) => (handle = m) },
    ).then(async () => {
      const question = qInput.value.trim();
      const quest = check.result();
      if (quest.parked) return resolve({ energy, minutes, question, questId: null, parked: true });
      if (question && !r.ann.questions.some((q) => q.text === question || q.text === `${question}?`)) await createQuestion(r, question, { learn: false });
      resolve({ energy, minutes: quest.minutes ?? minutes, question, questId: quest.questId, parked: false });
    });
  });
}

export async function endSession(r: Reader): Promise<void> {
  r.pacer.pause(false);
  r.flushRead();
  const suggestion = (() => {
    const next = r.next(r.pacer.ord);
    const sec = next !== null ? r.idx[next].sec : null;
    const unanswered = r.ann.questions.find((q) => !q.answer);
    if (unanswered) return `Answer: ${unanswered.text}`;
    return sec ? `Continue with “${sec.title}”` : "Write the explain-it box";
  })();
  const focused = r.session ? fmtMinutes(r.session.focusedMs) : "";
  // A reading step of the main quest can be finished right here.
  let step: QuestStep | null = null;
  try {
    const quest = await api.get<Quest | null>("/api/quest/active");
    step = quest?.steps.find((s) => s.document_id === r.doc.id && !s.done_at) ?? null;
  } catch {
    /* no quest info: plain end */
  }
  const next = h("input", { type: "text", placeholder: suggestion, autofocus: true, "aria-label": "Next step" });
  const finished = h("input", { type: "checkbox" });
  const output = h("input", { type: "text", placeholder: "What did it produce? e.g. notes on multi-head attention", "aria-label": "What it produced", hidden: true });
  const err = h("p", { class: "error small", hidden: true });
  finished.addEventListener("change", () => {
    output.hidden = !finished.checked;
    if (finished.checked) output.focus();
  });
  output.addEventListener("input", () => (err.hidden = true));
  const feel = feelRow();
  let handle: ModalHandle;
  const ok = () => {
    if (finished.checked && !output.value.trim()) {
      err.textContent = "Write one line about what it produced — that's the step's real output.";
      err.hidden = false;
      output.focus();
      return;
    }
    handle.close("ok");
  };
  next.addEventListener("keydown", (e) => e.key === "Enter" && ok());
  output.addEventListener("keydown", (e) => e.key === "Enter" && ok());
  const res = await modal(
    "End session",
    h(
      "div",
      { class: "stack" },
      h("label", { class: "field" }, h("span", null, `${focused ? `${focused} focused. ` : ""}What comes next? One sentence — it becomes your resume point.`), next),
      step
        ? h(
            "div",
            { class: "quest-check ok" },
            h("label", { class: "toggle" }, finished, " This finished the goal step: ", h("strong", null, step.title)),
            output,
            err,
          )
        : null,
      (r.session?.focusedMs ?? 0) >= 3 * 60_000 ? feel.el : null,
      h("div", { class: "row end" }, h("button", { onclick: () => handle.close(null) }, "Cancel"), h("button", { class: "primary", onclick: ok }, "Save & stop")),
    ),
    { onOpen: (m) => (handle = m) },
  );
  if (res !== "ok") return;
  const out = finished.checked ? output.value.trim() : "";
  if (step && out) {
    await api.patch(`/api/quest-steps/${step.id}`, { done: true, output: out });
    ambience.moment();
  }
  await r.session?.end(next.value.trim() || suggestion, out, feel.pick());
  if (out) toast("Step done. That's real output.", "ok");
  location.hash = "#/home";
}

export function timeBoxDone(r: Reader): Promise<boolean> {
  return new Promise((resolve) => {
    let handle: ModalHandle;
    modal(
      "Time box done",
      h(
        "div",
        { class: "stack" },
        h("p", null, `That's ${r.session?.info.time_box_min ?? 15} focused minutes. This counts, whatever happens next.`),
        h("div", { class: "row end" }, h("button", { onclick: () => handle.close("more") }, "5 more minutes"), h("button", { class: "primary", onclick: () => handle.close("end") }, "End session")),
      ),
      { onOpen: (m) => (handle = m) },
    ).then((v) => {
      if (v === "end") endSession(r);
      resolve(v === "more");
    });
  });
}

export function confusionFirst(r: Reader, list: Highlight[]): Promise<unknown> {
  let handle: ModalHandle;
  const rows = list.slice(0, 6).map((hl) => {
    const notes = r.ann.notes.filter((n) => n.sentence >= hl.sentence && n.sentence <= hl.end_sentence);
    const learned = r.ann.terms.filter((t) => !t.is_concept && t.definition && t.created_at > hl.created_at && hl.text.toLowerCase().includes(t.term.toLowerCase()));
    const li = h(
      "li",
      null,
      h("p", null, hl.text),
      notes.map((n) => h("p", { class: "muted small" }, `Your note: ${n.text}`)),
      learned.map((t) => h("p", { class: "muted small" }, `Since then you defined ${t.term}: ${t.definition}`)),
      h(
        "div",
        { class: "row" },
        h("button", { class: "btn small", onclick: () => (handle.close(), r.jumpTo(hl.sentence)) }, "Go there"),
        h(
          "button",
          {
            class: "btn small",
            onclick: async () => {
              await api.patch(`/api/highlights/${hl.id}`, { resolved: true });
              hl.resolved = 1;
              li.classList.add("resolved");
            },
          },
          "Got it now",
        ),
      ),
    );
    return li;
  });
  return modal("Confusion first", h("div", { class: "stack" }, h("p", { class: "muted" }, "Last time, these confused you. Look again with fresh eyes:"), h("ul", { class: "confusions" }, rows), h("div", { class: "row end" }, h("button", { class: "primary", onclick: () => handle.close() }, "Continue"))), {
    wide: true,
    onOpen: (m) => (handle = m),
  });
}

// ------------------------------------------------------------------ section checkpoints
type Step = { type: "predict" | "check"; sec: Section } | { type: "recall"; q: Question };

export function sectionCheckpoints(r: Reader, from: Section, to: Section): Step[] {
  const steps: Step[] = [];
  if (from.prediction && !from.prediction_check) steps.push({ type: "check", sec: from });
  const pids = new Set(from.paragraphs.map((p) => p.id));
  for (const q of r.ann.questions) if (!q.answer && q.paragraphs.some((p) => pids.has(p))) steps.push({ type: "recall", q });
  const pacedInTo = to.paragraphs.reduce((a, p) => a + p.sentences.filter((s) => r.isPaced(s.ord)).length, 0);
  if (state.settings.prediction_prompts && !to.prediction && !["references", "appendix", "abstract"].includes(to.kind) && pacedInTo >= 4) steps.push({ type: "predict", sec: to });
  return steps;
}

export async function runCheckpoints(r: Reader, steps: Step[]): Promise<void> {
  let keepGoing = true;
  for (const st of steps) {
    if (st.type === "predict") keepGoing = (await predict(st.sec)) && keepGoing;
    else if (st.type === "check") await checkPrediction(st.sec);
    else if (st.type === "recall") await recall(r, st.q);
  }
  if (keepGoing) r.pacer.play();
}

async function predict(sec: Section): Promise<boolean> {
  const text = await askText("Prediction", `Before “${sec.title}”: what do you expect it to show? One line.`, "", { okLabel: "Save & read", placeholder: "I expect…" });
  if (text) {
    sec.prediction = text;
    save("patch", `/api/sections/${sec.id}`, { prediction: text });
  }
  return text !== null;
}

function checkPrediction(sec: Section): Promise<unknown> {
  let handle: ModalHandle;
  const note = h("input", { type: "text", placeholder: "Optional: what was different?" });
  const answer = (verdict: string) => {
    sec.prediction_check = note.value.trim() ? `${verdict} — ${note.value.trim()}` : verdict;
    save("patch", `/api/sections/${sec.id}`, { prediction_check: sec.prediction_check });
    handle.close();
  };
  return modal(
    "Compare",
    h(
      "div",
      { class: "stack" },
      h("p", null, `You predicted “${sec.title}” would show:`),
      h("blockquote", null, sec.prediction),
      note,
      h("div", { class: "row end" }, ["Yes", "Partly", "No"].map((v) => h("button", { class: v === "Yes" ? "primary" : "", onclick: () => answer(v) }, v))),
    ),
    { onOpen: (m) => (handle = m) },
  );
}

/** Recall checkpoint: answer from memory in one line, then compare with the text. */
export function recall(r: Reader, q: Question): Promise<unknown> {
  let handle: ModalHandle;
  const box = h("textarea", { rows: 3, placeholder: "From memory, in your own words…", autofocus: true }, q.answer);
  const reveal = h("div", { class: "reveal", hidden: true });
  const saveBtn = h("button", { class: "primary", hidden: true }, "Save answer");
  const compareBtn = h("button", { class: "primary" }, "Compare with the text");
  compareBtn.addEventListener("click", () => {
    if (!box.value.trim()) {
      box.focus();
      toast("Try first — even a rough guess helps memory");
      return;
    }
    clear(reveal);
    const paras = q.paragraphs.map((pid) => r.idx.find((x) => x && x.p.id === pid)?.p).filter(Boolean);
    if (paras.length) for (const p of paras) reveal.append(h("blockquote", null, p!.sentences.map((s) => s.text).join(" ")));
    else if (q.source_sentence !== null) reveal.append(h("blockquote", null, r.idx[q.source_sentence]?.s.text ?? ""));
    else reveal.append(h("p", { class: "muted" }, `No paragraphs tagged for this question yet. While reading, press Q then ${r.ann.questions.indexOf(q) + 1} on a paragraph that answers it.`));
    reveal.hidden = false;
    compareBtn.hidden = true;
    saveBtn.hidden = false;
    saveBtn.focus();
  });
  saveBtn.addEventListener("click", async () => {
    const updated = await api.patch<Question>(`/api/questions/${q.id}`, { answer: box.value.trim() });
    Object.assign(q, { answer: updated.answer, answered_at: updated.answered_at });
    ambience.moment();
    toast("Saved — it's now a review card", "ok");
    r.rampSpeed();
    r.renderSide();
    r.updateProgress();
    handle.close();
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.ctrlKey) (compareBtn.hidden ? saveBtn : compareBtn).click();
  });
  return modal("Recall", h("div", { class: "stack" }, h("p", { class: "q-big" }, q.text), box, reveal, h("div", { class: "row end" }, h("button", { onclick: () => handle.close() }, "Later"), compareBtn, saveBtn)), {
    wide: true,
    onOpen: (m) => (handle = m),
  });
}

// ------------------------------------------------------------------ questions from claims
export function claimBuilder(r: Reader): Promise<unknown> {
  const early = r.doc.sections.filter((s) => ["abstract", "intro"].includes(s.kind));
  const source = (early.length ? early : r.doc.sections.slice(0, 1)).flatMap((s) => s.paragraphs.filter((p) => p.kind === "text").flatMap((p) => p.sentences.map((x) => ({ s: x, sec: s })))).slice(0, 18);
  const rows = source.map(({ s, sec }) => {
    const input = h("input", { type: "text", hidden: true });
    const add = async () => {
      const q = await createQuestion(r, input.value, { sectionId: sec.id, source: s.ord, learn: false });
      if (q) {
        input.hidden = true;
        row.classList.add("done");
        toast("Question added", "ok");
      }
    };
    input.addEventListener("keydown", (e) => e.key === "Enter" && add());
    const claim = s.text.replace(/^(we|in this (paper|work),? we)\s+(show|find|propose|demonstrate|argue|present|introduce)\s+(that\s+)?/i, "").replace(/[.!]+$/, "");
    const lower = claim.charAt(0).toLowerCase() + claim.slice(1);
    const fill = (starter: string) => {
      input.hidden = false;
      input.value = starter === "What proves" ? `What proves that ${lower}?` : starter === "Why does" ? `Why does ${lower}?` : starter === "How does" ? `How does ${lower}?` : `What is ${lower}?`;
      input.focus();
      input.setSelectionRange(starter.length + 1, input.value.length - 1);
    };
    const row = h("li", { class: "claim-row" }, h("p", null, s.text), h("div", { class: "row wrap" }, STARTERS.map((st) => h("button", { class: "btn small", onclick: () => fill(st) }, `${st}…`)), input));
    return row;
  });
  return modal("Turn claims into questions", h("div", { class: "stack" }, h("p", { class: "muted" }, "Pick a starter, edit the wording, press Enter. About a minute — then you read with a job."), h("ol", { class: "claims" }, rows)), { wide: true });
}

// ------------------------------------------------------------------ guess gate
export function guessGate(r: Reader, initial: string): Promise<unknown> {
  r.pacer.pause(false);
  let handle: ModalHandle;
  const term = h("input", { type: "text", value: initial, placeholder: "Term", "aria-label": "Term" });
  const guess = h("textarea", { rows: 2, placeholder: "Your guess first — what do you think it means?", autofocus: !!initial });
  const out = h("div", { class: "reveal", hidden: true });
  const def = h("textarea", { rows: 3, placeholder: "Your corrected definition" });
  const revealBtn = h("button", { class: "primary" }, "Reveal");
  const saveBtn = h("button", { class: "primary", hidden: true }, "Save to glossary");
  let top: { sentence: number; text: string } | null = null;

  const reveal = async (noIdea = false) => {
    if (!term.value.trim()) return term.focus();
    if (!guess.value.trim() && !noIdea) {
      guess.focus();
      toast("Guess first — a wrong guess still helps you remember");
      return;
    }
    if (noIdea && !guess.value.trim()) guess.value = "(no idea)";
    const res = await api.get<{ in_document: { sentence: number; text: string; pattern: string }[]; acronym: string | null; glossary: Term[] }>(`/api/documents/${r.doc.id}/define?term=${encodeURIComponent(term.value.trim())}`);
    clear(out);
    if (res.acronym) out.append(h("p", null, h("strong", null, `${term.value.trim()} = `), res.acronym));
    if (res.in_document.length) {
      top = res.in_document[0];
      out.append(h("p", { class: "muted small" }, "Where this document explains it:"));
      out.append(
        h(
          "ul",
          { class: "defs" },
          res.in_document.map((d) => h("li", null, h("blockquote", null, d.text), h("div", { class: "row" }, h("span", { class: "muted small" }, d.pattern), h("button", { class: "btn small", onclick: () => (handle.close(), r.jumpTo(d.sentence)) }, "Go there")))),
        ),
      );
    } else out.append(h("p", { class: "muted" }, "This document doesn't seem to define it. Write what you can work out from context."));
    if (res.glossary.length) out.append(h("p", { class: "muted small" }, "In your glossary already:"), ...res.glossary.map((g) => h("blockquote", null, g.definition)));
    def.value = res.acronym && guess.value === "(no idea)" ? res.acronym : guess.value === "(no idea)" ? "" : guess.value;
    out.append(h("label", { class: "field" }, h("span", null, "Your definition (corrected)"), def));
    out.hidden = false;
    revealBtn.hidden = true;
    noIdeaBtn.hidden = true;
    saveBtn.hidden = false;
    def.focus();
  };
  const noIdeaBtn = h("button", { onclick: () => reveal(true) }, "No idea — reveal");
  revealBtn.addEventListener("click", () => reveal());
  saveBtn.addEventListener("click", async () => {
    const t = await api.post<Term>("/api/terms", {
      term: term.value.trim(),
      guess: guess.value.trim(),
      definition: def.value.trim(),
      document_id: r.doc.id,
      sentence: top?.sentence ?? r.pacer.ord,
      source_text: top?.text ?? r.idx[r.pacer.ord].s.text,
    });
    r.ann.terms.push(t);
    toast(def.value.trim() ? "Saved to glossary — it's a review card now" : "Guess saved", "ok");
    r.renderSide();
    handle.close();
  });
  guess.addEventListener("keydown", (e) => e.key === "Enter" && e.ctrlKey && reveal());
  return modal("Guess, then reveal", h("div", { class: "stack" }, term, guess, out, h("div", { class: "row end" }, noIdeaBtn, revealBtn, saveBtn)), {
    wide: true,
    onOpen: (m) => {
      handle = m;
      (initial ? guess : term).focus();
    },
  });
}

export function clozePicker(r: Reader, hl: Highlight): Promise<unknown> {
  let handle: ModalHandle;
  const words = hl.text.match(/\S+/g) ?? [];
  return modal(
    "Make a fill-in-the-blank card",
    h(
      "div",
      { class: "stack" },
      h("p", { class: "muted" }, "Click the number or word to hide."),
      h(
        "p",
        { class: "cloze-words" },
        words.map((w) => {
          const bare = w.replace(/^[("'“[]+|[)"'”\],.;:!?]+$/g, "");
          return h(
            "button",
            {
              class: `chip ${/\d/.test(bare) ? "num" : ""}`,
              onclick: async () => {
                Object.assign(hl, await api.patch<Highlight>(`/api/highlights/${hl.id}`, { cloze: bare }));
                toast(`Card made: “${bare}” is hidden`, "ok");
                r.renderSide();
                handle.close();
              },
            },
            w,
          );
        }),
      ),
    ),
    { wide: true, onOpen: (m) => (handle = m) },
  );
}

// ------------------------------------------------------------------ notes, ideas, tagging
export async function addNote(r: Reader): Promise<void> {
  const ord = r.pacer.ord;
  const text = await askText("Margin note", `On: “${r.idx[ord].s.text.slice(0, 120)}”`, "", { multiline: true, okLabel: "Add note (Ctrl+Enter)" });
  if (!text) return;
  const n = await api.post<Note>("/api/notes", { document_id: r.doc.id, sentence: ord, text });
  r.ann.notes.push(n);
  r.decorateSentence(ord);
  r.renderSide();
}

export function showNotes(r: Reader, ord: number): Promise<unknown> {
  let handle: ModalHandle;
  const notes = r.ann.notes.filter((n) => n.sentence === ord);
  return modal(
    "Margin notes",
    h(
      "div",
      { class: "stack" },
      h("blockquote", null, r.idx[ord].s.text),
      notes.map((n) =>
        h(
          "div",
          { class: "note" },
          n.origin === "ai" ? h("div", { class: "ai-text-label" }, "Written by the AI model. Edit it to make it yours.") : null,
          h("p", null, n.text),
          h(
            "div",
            { class: "row" },
            h(
              "button",
              {
                class: "btn small",
                onclick: async () => {
                  const t = await askText("Edit note", "Note", n.text, { multiline: true });
                  if (t === null) return;
                  await api.patch(`/api/notes/${n.id}`, { text: t });
                  if (t !== n.text) n.origin = ""; // you changed it: it is yours now (the server does the same)
                  n.text = t;
                  r.decorateSentence(ord);
                  handle.close();
                },
              },
              "Edit",
            ),
            h(
              "button",
              {
                class: "btn small ghost",
                onclick: async () => {
                  await api.del(`/api/notes/${n.id}`);
                  r.ann.notes = r.ann.notes.filter((x) => x.id !== n.id);
                  r.decorateSentence(ord);
                  r.renderSide();
                  handle.close();
                },
              },
              "Delete",
            ),
          ),
        ),
      ),
      h("div", { class: "row end" }, h("button", { onclick: () => (handle.close(), r.pacer.setPosition(ord), addNote(r)) }, "Add another")),
    ),
    { onOpen: (m) => (handle = m) },
  );
}

export async function quickIdea(r: Reader): Promise<void> {
  const text = await askText("Idea inbox", "What does this spark for your own work?", "", { multiline: true, okLabel: "Save idea (Ctrl+Enter)" });
  if (!text) return;
  await api.post("/api/ideas", { text, document_id: r.doc.id, sentence: r.pacer.ord });
  toast("Saved to your idea inbox", "ok");
}

export async function tagParagraph(r: Reader, qi: number): Promise<void> {
  const q = r.ann.questions[qi];
  if (!q) {
    toast(`There's no question ${qi + 1} yet`);
    return;
  }
  const pid = r.idx[r.pacer.ord].p.id;
  const res = await api.post<{ linked: boolean }>(`/api/questions/${q.id}/link`, { paragraph_id: pid });
  q.paragraphs = res.linked ? [...q.paragraphs, pid] : q.paragraphs.filter((x) => x !== pid);
  toast(res.linked ? `Paragraph tagged as answering Q${qi + 1}` : `Tag removed from Q${qi + 1}`, "ok");
  r.rerenderParagraphOf(r.pacer.ord);
  r.renderMap();
  r.renderSide();
}

// ------------------------------------------------------------------ peeks (figures, tables, equations, citations)
let peekEl: HTMLElement | null = null;
let peekPinned = false;

function closePeek(): void {
  peekEl?.remove();
  peekEl = null;
  peekPinned = false;
}

export function peek(r: Reader, anchor: HTMLElement, pinned: boolean): void {
  if (peekEl && peekPinned && !pinned) return;
  closePeek();
  const key = anchor.dataset.peek ?? "";
  const body = h("div", { class: "peek-body" });
  const keys = key.startsWith("refs:")
    ? key
        .slice(5)
        .split(/\s*,\s*/)
        .flatMap((part) => {
          const m = part.match(/^(\d+)\s*[–-]\s*(\d+)$/);
          if (!m) return [`ref:${part.trim()}`];
          const out: string[] = [];
          for (let i = Number(m[1]); i <= Math.min(Number(m[2]), Number(m[1]) + 6); i++) out.push(`ref:${i}`);
          return out;
        })
    : [key];
  for (const k of keys) {
    const text = r.peeks.get(k);
    if (!text) continue;
    const img = r.peekImages.get(k);
    const eq = k.startsWith("eq:") ? displayEquation(text) : null;
    const item = h(
      "div",
      { class: "peek-item" },
      img
        ? h("img", { class: "peek-eq", src: img, alt: plainMath(text) })
        : eq
          ? h("div", { class: "peek-eq" }, mathEl(eq.tex, true), eq.tag ? h("span", { class: "eq-no" }, eq.tag) : null)
          : h("p", null, mathText(text)),
    );
    if (k.startsWith("ref:")) {
      // a cited paper is kept as a line to follow up; nothing is downloaded
      item.append(
        h("div", { class: "row" },
          h("button", {
            class: "btn small",
            onclick: async () => {
              await api.post("/api/ideas", { text: `To read: ${text}`, document_id: r.doc.id });
              toast("Saved to your reading list (idea inbox)", "ok");
            },
          }, "Save to reading list")),
      );
    }
    body.append(item);
  }
  if (!body.childNodes.length) return;
  peekEl = h("div", { class: "peek-pop", role: "tooltip" }, body, pinned ? h("button", { class: "btn small ghost close", onclick: closePeek }, "Close") : null);
  document.body.append(peekEl);
  positionNear(peekEl, anchor);
  peekPinned = pinned;
  if (!pinned) anchor.addEventListener("mouseleave", () => !peekPinned && closePeek(), { once: true });
  else setTimeout(() => document.addEventListener("mousedown", (e) => !peekEl?.contains(e.target as Node) && closePeek(), { once: true }), 0);
}

export function acronymTip(r: Reader, el: HTMLElement): void {
  if (peekPinned) return;
  closePeek();
  const k = el.dataset.acr ?? "";
  peekEl = h("div", { class: "peek-pop small", role: "tooltip" }, h("strong", null, k), ` = ${r.ann.acronyms[k] ?? ""}`);
  document.body.append(peekEl);
  positionNear(peekEl, el);
  el.addEventListener("mouseleave", () => !peekPinned && closePeek(), { once: true });
}

function positionNear(pop: HTMLElement, anchor: HTMLElement): void {
  const a = anchor.getBoundingClientRect();
  const p = pop.getBoundingClientRect();
  let top = a.bottom + 8;
  if (top + p.height > innerHeight - 70) top = Math.max(8, a.top - p.height - 8);
  const left = Math.min(Math.max(8, a.left), innerWidth - p.width - 8);
  pop.style.top = `${top}px`;
  pop.style.left = `${left}px`;
}

// ------------------------------------------------------------------ selection toolbar
let selBar: HTMLElement | null = null;
export function selectionToolbar(r: Reader): void {
  selBar?.remove();
  selBar = null;
  const sel = window.getSelection();
  const text = sel?.toString().trim() ?? "";
  if (!sel || !text || !sel.rangeCount || !r.paper.contains(sel.anchorNode)) return;
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  const range = r.selectionRange();
  const forAi = aiIsOn() ? (range ?? codeRange(r)) : null; // a selection in a code block can be explained too
  const mk = (label: string, fn: () => void, cls = "") => h("button", { class: `btn small ${cls}`, onmousedown: (e: Event) => e.preventDefault(), onclick: () => (fn(), selBar?.remove()) }, label);
  selBar = h(
    "div",
    { class: "sel-bar", role: "toolbar" },
    text.split(/\s+/).length <= 6 ? mk("Guess (G)", () => guessGate(r, text), "primary") : null,
    range
      ? (["claim", "evidence", "definition", "confusing", "idea"] as const).map((t, i) => mk(`${i + 1} ${t}`, () => r.highlight(t, range[0], range[1]), `hl-${t}`))
      : null,
    range ? mk("→ Note", () => void quoteToNote(r, text, range[0])) : null,
    // offered for a selection inside one paragraph, of at most 12 sentences: the server accepts nothing else
    forAi && forAi[1] - forAi[0] < 12 && r.idx[forAi[0]]?.p.id === r.idx[forAi[1]]?.p.id ? mk("Explain", () => void explainSelection(r, forAi, text)) : null,
  );
  document.body.append(selBar);
  selBar.style.top = `${Math.max(8, rect.top - 44)}px`;
  selBar.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - selBar.offsetWidth - 8))}px`;
  const remove = () => {
    if (!window.getSelection()?.toString().trim()) {
      selBar?.remove();
      selBar = null;
      document.removeEventListener("selectionchange", remove);
    }
  };
  document.addEventListener("selectionchange", remove);
}

/** The passage goes to the end of today's note, with a link back to this sentence. */
async function quoteToNote(r: Reader, text: string, sentence: number): Promise<void> {
  try {
    const note = await api.post<{ id: string }>("/api/pages/quote", { text: text.slice(0, 4000), document_id: r.doc.id, sentence, day: ymd(new Date()) });
    toast("Quoted in today's note, with a link back to here.", "ok", 5000, { label: "Open the note", run: () => void (location.hash = `#/notes/${note.id}`) });
  } catch (e) {
    toast((e as Error).message, "error");
  }
}

// ------------------------------------------------------------------ explain-it, comfort, help
export function explainIt(r: Reader, atEnd: boolean): Promise<unknown> {
  r.pacer.pause(false);
  let handle: ModalHandle;
  const box = h("textarea", { rows: 5, placeholder: "1. It's about…\n2. The key idea is…\n3. It matters because…", autofocus: true }, r.doc.explain_text);
  const finish = h("input", { type: "checkbox", checked: atEnd || r.doc.status === "finished" });
  const saveIt = async () => {
    const text = box.value.trim();
    await api.patch(`/api/documents/${r.doc.id}`, { explain_text: text, ...(finish.checked ? { status: "finished" } : {}) });
    r.doc.explain_text = text;
    if (finish.checked) r.doc.status = "finished";
    r.flushRead();
    handle.close("saved");
  };
  return modal(
    atEnd ? "You reached the end" : "Explain it",
    h(
      "div",
      { class: "stack" },
      h("p", null, "Explain it in three sentences, as if to a younger student. Where it gets vague is what to reread."),
      box,
      h("label", { class: "toggle" }, finish, " Mark this document as finished"),
      h("div", { class: "row end" }, h("button", { onclick: () => handle.close() }, "Later"), h("button", { class: "primary", onclick: saveIt }, "Save")),
    ),
    { wide: true, onOpen: (m) => (handle = m) },
  ).then((v) => {
    if (v === "saved" && finish.checked) location.hash = `#/summary/${r.doc.id}`;
  });
}

export function comfortPopover(r: Reader): Promise<unknown> {
  let handle: ModalHandle;
  const c = comfortFor(r.doc.source_type);
  const font = h("select", null, Object.entries(FONTS).map(([k, f]) => h("option", { value: k }, f.label)));
  font.value = c.font;
  const range = (min: number, max: number, step: number, v: number) => h("input", { type: "range", min, max, step, value: v });
  const size = range(14, 32, 1, c.font_size);
  const width = range(40, 100, 2, c.line_width);
  const lead = range(1.3, 2.4, 0.05, c.line_height);
  const current = () => ({ font: font.value, font_size: Number(size.value), line_width: Number(width.value), line_height: Number(lead.value) });
  [font, size, width, lead].forEach((x) => x.addEventListener("input", () => applyComfort(current())));
  const type = r.doc.source_type;
  return modal(
    "Reading comfort",
    h(
      "div",
      { class: "stack" },
      h("label", { class: "field" }, h("span", null, "Font"), font),
      h("label", { class: "field" }, h("span", null, "Size"), size),
      h("label", { class: "field" }, h("span", null, "Line length"), width),
      h("label", { class: "field" }, h("span", null, "Line spacing"), lead),
      h(
        "div",
        { class: "row end" },
        h(
          "button",
          {
            onclick: async () => {
              await saveSettings({ ...current() });
              toast("Saved as your default", "ok");
              handle.close();
            },
          },
          "Save as default",
        ),
        h(
          "button",
          {
            class: "primary",
            onclick: async () => {
              await saveSettings({ comfort_by_type: { ...state.settings.comfort_by_type, [type]: current() } });
              toast(`Saved for ${type} documents`, "ok");
              handle.close();
            },
          },
          `Save for ${type} documents`,
        ),
      ),
    ),
    { onOpen: (m) => (handle = m) },
  ).then(() => applyComfort(comfortFor(type)));
}

export function keyHelp(): Promise<unknown> {
  const keys: [string, string][] = [
    ["Space", "Play / pause the pacer"],
    ["← →  ↑ ↓", "Move one sentence"],
    ["Click a word", "Restart the pacer from there"],
    ["1 2 3 4 5", "Highlight: claim, evidence, definition, confusing, idea"],
    ["Q then 1–9", "Tag this paragraph as answering question n"],
    ["G", "Guess gate for the selected term"],
    ["N", "Margin note on this sentence"],
    ["I", "Quick idea capture"],
    ["B / Backspace", "Back-jump to where you were"],
    ["W", "Cycle sentence / word / focus-word pacer"],
    ["R", "Read aloud"],
    ["F", "Focus view"],
    ["Ctrl+\\", "Hide or show the side panels"],
    ["+ / −", "Faster / slower"],
    ["E", "End session"],
  ];
  return modal("Keyboard", h("table", { class: "keys" }, keys.map(([k, v]) => h("tr", null, h("th", null, h("kbd", null, k)), h("td", null, v)))));
}
