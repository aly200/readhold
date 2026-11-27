// Quests: set the main quest (title, why, what done looks like, the questions it must answer),
// then shape its steps — each in three energy sizes, one marked as the lead.
import { ambience } from "../ambience";
import { api } from "../api";
import { mathText } from "../math";
import type { DayLog, Quest, QueueDoc, QuestQuestion, TopicMap } from "../types";
import { append, askText, clear, confirmBox, h, type ModalHandle, modal, toast } from "../util";
import { logList as renderLogs } from "./logs";
import { startStep } from "./today";
import { connectedCard } from "../related";
import type { Related } from "../types";
import { ymd } from "./plan";
import { libraryHead } from "./libtabs";
import { removeItem } from "../trash";

interface QuestRow {
  id: string;
  title: string;
  status: "active" | "done" | "parked";
  deadline: string | null;
  finished_at: string | null;
}

export async function questView(root: HTMLElement, id: string | undefined): Promise<void> {
  if (!id) return questList(root);
  if (id === "new") return questNew(root);
  const [q, docs, map, logs] = await Promise.all([
    api.get<Quest>(`/api/quests/${id}`),
    api.get<QueueDoc[]>("/api/documents"),
    api.get<TopicMap>(`/api/quests/${id}/map`),
    api.get<DayLog[]>(`/api/logs?quest_id=${encodeURIComponent(id)}&days=30`),
  ]);
  questEdit(root, q, docs, map, logs);
}

// ------------------------------------------------------------------ all quests
async function questList(root: HTMLElement): Promise<void> {
  const [quests, sides] = await Promise.all([api.get<QuestRow[]>("/api/quests"), api.get<{ id: string; text: string; created_at: string }[]>("/api/side-quests")]);
  const status = { active: "Active", parked: "Parked", done: "Done" };
  const again = () => {
    if (!location.hash.startsWith("#/quest") || location.hash.startsWith("#/quest/")) return; // you went elsewhere meanwhile
    clear(root);
    void questList(root);
  };
  root.append(
    h(
      "section",
      { class: "quests" },
      libraryHead("goals", h("a", { class: "btn primary", href: "#/quest/new" }, "New main goal")),
      quests.length
        ? h(
            "ul",
            { class: "quest-list" },
            quests.map((x) =>
              h(
                "li",
                { class: x.status },
                h("a", { href: `#/quest/${x.id}` }, x.title),
                h("span", { class: `badge ${x.status === "active" ? "accent" : ""}` }, status[x.status]),
                x.status === "parked" ? h("button", { class: "btn small", onclick: async () => (await api.patch(`/api/quests/${x.id}`, { status: "active" }), (location.hash = "#/home")) }, "Make it the main goal") : null,
                h("button", { class: "btn small ghost", "aria-label": `Delete the goal ${x.title}`, title: "Delete this goal", onclick: async () => (await deleteGoal(x.id, x.title, again)) && again() }, "✕"),
              ),
            ),
          )
        : h("p", { class: "muted" }, "No goals yet. A goal is the one thing that matters this week, and the questions it must answer."),
      h("h2", null, "Parked side goals"),
      sides.length
        ? h("ul", { class: "parked-list" }, sides.map((s) => h("li", null, h("span", null, s.text), h("button", { class: "btn small ghost", onclick: async (e: Event) => (await api.patch(`/api/side-quests/${s.id}`, {}), (e.target as HTMLElement).closest("li")?.remove()) }, "Clear"), deleteSideButton(s, again))))
        : h("p", { class: "muted" }, "Nothing parked. Things that pull you away land here, safe, until it's their turn."),
    ),
  );
}

// ------------------------------------------------------------------ delete, with Undo (milestone 5.1)
/** Delete a goal after asking: its questions, steps and map go out of sight with it, and come back with Undo. */
async function deleteGoal(id: string, title: string, back?: () => void): Promise<boolean> {
  if (!(await confirmBox("Delete this goal?", `“${title}”, with its questions, steps and topic map, leaves Readhold. You can undo it right after.`, "Delete"))) return false;
  return removeItem("quest", id, `Deleted the goal “${title}”.`, { back });
}

/** A parked side goal: "Clear" sets it aside as dealt with; ✕ deletes it (with Undo). */
function deleteSideButton(s: { id: string; text: string }, redraw: () => void): HTMLElement {
  return h("button", { class: "btn small ghost", "aria-label": `Delete the side goal ${s.text}`, title: "Delete", onclick: () => void removeItem("side_quest", s.id, `Deleted “${s.text}”.`, { gone: redraw, back: redraw }) }, "✕");
}

// ------------------------------------------------------------------ new quest
function questNew(root: HTMLElement): void {
  const title = h("input", { type: "text", placeholder: "Pass Thursday's transformers exam", autofocus: true, "aria-label": "Main goal" });
  const why = h("input", { type: "text", placeholder: "It's 30% of the course grade", "aria-label": "Why it matters" });
  const done = h("input", { type: "text", placeholder: "I can answer all 3 questions from memory", "aria-label": "What done looks like" });
  const deadline = h("input", { type: "date", "aria-label": "Deadline" });
  const qs = h("div", { class: "stack" });
  const addQ = (placeholder = "Another question it must answer") => qs.append(h("input", { type: "text", placeholder, class: "q-in" }));
  addQ("How does attention work?");
  addQ("Why use several heads?");
  addQ("What are its limits?");
  const err = h("p", { class: "error small", hidden: true });
  const create = async () => {
    if (!title.value.trim()) {
      err.textContent = "Name the main goal first.";
      err.hidden = false;
      title.focus();
      return;
    }
    const questions = [...qs.querySelectorAll<HTMLInputElement>(".q-in")].map((i) => i.value.trim()).filter(Boolean);
    const q = await api.post<Quest>("/api/quests", { title: title.value, why: why.value, done_looks_like: done.value, deadline: deadline.value || null, questions });
    toast("Main goal set. Now add the lead step.", "ok");
    location.hash = `#/quest/${q.id}`;
  };
  title.addEventListener("input", () => (err.hidden = true));
  root.append(
    h(
      "section",
      { class: "quest-new" },
      h("span", { class: "badge accent" }, "New main goal"),
      h("h1", null, "What's the one thing that matters this week?"),
      h("p", { class: "muted" }, "One goal at a time. Its questions decide what's useful: anything that doesn't move one of them is a side goal."),
      h("label", { class: "field" }, h("span", null, "Main goal"), title),
      err,
      h("label", { class: "field" }, h("span", null, "Why it matters"), why),
      h("label", { class: "field" }, h("span", null, "Done looks like"), done),
      h("label", { class: "field" }, h("span", null, "Deadline (optional)"), deadline),
      h("div", { class: "field" }, h("span", null, "The questions it must answer"), qs, h("button", { class: "link", onclick: () => addQ() }, "+ Add a question")),
      h("div", { class: "row end" }, h("a", { class: "btn ghost", href: "#/home" }, "Cancel"), h("button", { class: "btn primary", onclick: create }, "Set main goal")),
    ),
  );
  title.focus();
}

// ------------------------------------------------------------------ edit quest
function questEdit(root: HTMLElement, q: Quest, docs: QueueDoc[], map: TopicMap, logs: DayLog[]): void {
  const page = h("section", { class: "quest-page" });
  root.append(page);
  const reload = async () => {
    const fresh = await api.get<Quest>(`/api/quests/${q.id}`);
    Object.assign(q, fresh);
    render();
  };
  const field = (label: string, value: string, key: "title" | "why" | "done_looks_like", placeholder: string) => {
    const input = h("input", { type: "text", value, placeholder, "aria-label": label });
    let saved = value; // the last value the server has
    input.addEventListener("change", async () => {
      const next = input.value.trim();
      if (next === saved || (key === "title" && !next)) return;
      await api.patch(`/api/quests/${q.id}`, { [key]: next });
      saved = next;
      toast("Saved", "ok", 1200);
    });
    return h("label", { class: "field" }, h("span", null, label), input);
  };

  const render = () => {
    clear(page);
    const pct = q.progress.total ? Math.round((q.progress.answered / q.progress.total) * 100) : 0;
    append(page, [
      h("div", { class: "isle page-head" },
      h(
        "div",
        { class: "quest-top" },
        h("span", { class: `badge ${q.status === "active" ? "accent" : ""}` }, q.status === "active" ? "Main goal" : q.status === "done" ? "Done" : "Parked"),
        h("a", { class: "quest-edit", href: "#/quest" }, "All goals"),
      ),
      h("h1", { class: "quest-title" }, q.title),
      h("div", { class: "meter", "aria-hidden": "true" }, h("span", { style: { width: `${pct}%` } })),
      h("p", { class: "muted small" }, `${q.progress.answered} of ${q.progress.total} questions answered`),
      h(
        "details",
        { class: "quest-details" },
        h("summary", null, "Goal details"),
        field("Main goal", q.title, "title", ""),
        field("Why it matters", q.why, "why", "It's 30% of the course grade"),
        field("Done looks like", q.done_looks_like, "done_looks_like", "I can answer all questions from memory"),
      )),
      mapCard(),
      h("div", { class: "isle quest-block" },
      h("h2", null, "Questions it must answer"),
      h("p", { class: "muted small" }, "Teach it back: explain a question from memory, then name where you hesitated. Each gap becomes a step."),
      questionList()),
      h("div", { class: "isle quest-block" },
      h("h2", null, "Steps"),
      h("p", { class: "muted small" }, "Each step comes in three sizes, so a low day still moves the goal. ★ marks the lead step: the one that makes the others easier."),
      stepList(),
      addStepForm()),
      h("div", { class: "isle quest-block" }, logList()),
      h("div", { class: "isle quest-block" }, connectedCard("quest", q.id, q.title)),
      q.side_quests.length ? h("div", { class: "isle quest-block" }, h("h2", null, "Parked side goals"), h("ul", { class: "parked-list" }, q.side_quests.map((s) => h("li", null, h("span", null, s.text), h("button", { class: "btn small", onclick: () => addStepFrom(s.text, s.id) }, "Make it a step"), h("button", { class: "btn small ghost", onclick: async () => (await api.patch(`/api/side-quests/${s.id}`, {}), reload()) }, "Clear"), deleteSideButton(s, () => void reload()))))) : null,
      h(
        "div",
        { class: "isle row end quest-finish" },
        h("button", { class: "btn ghost quest-delete", onclick: async () => {
          if (await deleteGoal(q.id, q.title, () => void (location.hash = `#/quest/${q.id}`))) location.hash = "#/quest";
        } }, "Delete goal"),
        q.status !== "active" ? h("button", { class: "btn", onclick: async () => (await api.patch(`/api/quests/${q.id}`, { status: "active" }), reload()) }, "Make it the main goal") : h("button", { class: "btn ghost", onclick: async () => (await api.patch(`/api/quests/${q.id}`, { status: "parked" }), (location.hash = "#/home")) }, "Park this goal"),
        q.status !== "done"
          ? h("button", {
              class: "btn primary",
              onclick: async () => {
                if (q.progress.answered < q.progress.total && !(await confirmBox("Finish the goal?", `${q.progress.total - q.progress.answered} question(s) still have no answer. Finish anyway?`, "Finish"))) return;
                await api.patch(`/api/quests/${q.id}`, { status: "done" });
                ambience.moment();
                toast("Goal done. That's a real result.", "ok", 5000);
                location.hash = "#/home";
              },
            }, "Finish goal")
          : null,
      ),
    ]);
  };

  const mapCard = () => {
    const pct = map.progress.total ? Math.round((map.progress.solid / map.progress.total) * 100) : 0;
    return h(
      "a",
      { class: "map-card", href: `#/map/${q.id}` },
      h("div", null, h("div", { class: "kicker" }, "Topic map"), h("strong", null, map.progress.total ? `${map.progress.solid} of ${map.progress.total} concepts you can explain` : "Map what this goal needs you to understand"), map.next ? h("div", { class: "muted small" }, `Learn next: ${map.next.name}`) : null),
      map.progress.total ? h("div", { class: "map-card-meter", "aria-hidden": "true" }, h("span", { style: { width: `${pct}%` } })) : null,
      h("span", { class: "map-card-go", "aria-hidden": "true" }, "→"),
    );
  };

  const teachBack = async (x: QuestQuestion) => {
    // Step 1: explain from memory (the saved answer stays hidden so it can't prompt you).
    const explain = h("textarea", { rows: 7, autofocus: true, placeholder: "Explain it as if to a friend who missed the lecture. No notes." });
    const err = h("p", { class: "error small", hidden: true });
    explain.addEventListener("input", () => (err.hidden = true));
    let h1: ModalHandle;
    const first = await modal(
      `Teach it back: ${x.text}`,
      h("div", { class: "stack" }, h("p", { class: "muted small" }, "Write it from memory first. Struggling here is the learning."), explain, err,
        h("div", { class: "row end" }, h("button", { onclick: () => h1.close(null) }, "Cancel"), h("button", { class: "primary", onclick: () => (explain.value.trim() ? h1.close("next") : ((err.textContent = "Write your explanation first, even a rough one."), (err.hidden = false))) }, "Next: find the gaps"))),
      { wide: true, onOpen: (m) => (h1 = m) },
    );
    if (first !== "next") return;
    // Step 2: compare, and name the gaps.
    const gaps = h("textarea", { rows: 4, autofocus: true, placeholder: "One per line: where you hesitated, skipped a step, or hand-waved" });
    const replace = h("input", { type: "checkbox" }); // only offered when an answer is saved: without it the new explanation is practice and is not kept
    let h2: ModalHandle;
    const second = await modal(
      "Where were the gaps?",
      h("div", { class: "stack" },
        h("div", { class: "teach-compare" },
          h("div", null, h("div", { class: "kicker" }, "Your explanation now"), h("p", null, explain.value.trim())),
          x.answer ? h("div", null, h("div", { class: "kicker" }, "Your saved answer"), h("p", null, mathText(x.answer))) : h("div", null, h("div", { class: "kicker" }, "Check against"), h("p", { class: "muted" }, "Your notes or the paper. Open them now, then come back."))),
        h("label", { class: "field" }, h("span", null, "Gaps (each becomes a 15-minute step)"), gaps),
        x.answer ? h("label", { class: "teach-replace" }, replace, h("span", null, "Keep this explanation as my answer. It replaces the saved one; without this, the saved answer stays and this one is not kept.")) : null,
        h("div", { class: "row end" }, h("button", { onclick: () => h2.close(null) }, "Cancel"), h("button", { class: "primary", onclick: () => h2.close("save") }, "Save"))),
      { wide: true, onOpen: (m) => (h2 = m) },
    );
    if (second !== "save") return;
    const list = gaps.value.split(/\r?\n/).map((g) => g.trim()).filter(Boolean);
    const r = await api.post<{ steps: unknown[] }>(`/api/quest-questions/${x.id}/teachback`, { explanation: explain.value.trim(), gaps: list, replace: replace.checked });
    if (!x.answer) ambience.moment();
    toast(r.steps.length ? `${r.steps.length} gap${r.steps.length > 1 ? "s" : ""} became step${r.steps.length > 1 ? "s" : ""}.${replace.checked ? " Your answer is replaced." : ""}` : replace.checked ? "Saved as your new answer." : x.answer ? "No gaps named. Nice." : "Saved as your answer.", "ok");
    reload();
  };

  const logList = () => [
    h("h2", null, "Daily log"),
    logs.length ? renderLogs(logs, true) : h("p", { class: "muted" }, "Close each day on the Today screen with three lines: what you did, what you learned, and tomorrow's first step."),
  ];

  const questionList = () =>
    h(
      "ol",
      { class: "quest-questions big" },
      q.questions.map((x, i) => {
        const area = h("textarea", { rows: x.answer ? 3 : 2, placeholder: "Your answer, in your own words — from memory first" }, x.answer);
        area.addEventListener("change", async () => {
          const was = x.answer;
          await api.patch(`/api/quest-questions/${x.id}`, { answer: area.value });
          if (area.value.trim() && !was) ambience.moment();
          reload();
        });
        const linked = q.documents.filter((d) => d.quest_question_id === x.id);
        return h(
          "li",
          { class: x.answer ? "done" : "" },
          h("div", { class: "q-head" }, h("span", { class: "q-mark", "aria-hidden": "true" }, x.answer ? "✓" : `${i + 1}`), h("span", { class: "q-text" }, x.text), h("button", { class: "btn small", onclick: () => teachBack(x) }, "Teach it back"), h("button", { class: "link small", onclick: async () => (await confirmBox("Remove this question?", x.text, "Remove")) && (await api.del(`/api/quest-questions/${x.id}`), reload()) }, "Remove")),
          linked.length ? h("div", { class: "muted small" }, "Reading for it: ", linked.map((d, k) => [k ? ", " : "", h("a", { href: `#/read/${d.id}` }, d.title)])) : null,
          area,
        );
      }),
      h("li", { class: "add" }, h("button", { class: "link", onclick: async () => { const t = await askText("Add a question", "What else must this goal answer?"); if (t) (await api.post(`/api/quests/${q.id}/questions`, { text: t }), reload()); } }, "+ Add a question")),
    );

  const qLabel = (id: string | null) => {
    const i = q.questions.findIndex((x) => x.id === id);
    return i >= 0 ? `Q${i + 1}` : "";
  };

  const stepList = () =>
    q.steps.length
      ? h(
          "ul",
          { class: "steps" },
          q.steps.map((s) =>
            h(
              "li",
              { class: `${s.done_at ? "done" : ""} ${q.lead?.id === s.id ? "is-lead" : ""}` },
              h("input", { type: "checkbox", checked: !!s.done_at, "aria-label": "Done", onchange: async (e: Event) => (await api.patch(`/api/quest-steps/${s.id}`, { done: (e.target as HTMLInputElement).checked }), reload()) }),
              h("button", { class: `star ${s.lead ? "on" : ""}`, title: "Make this the lead step", "aria-label": "Lead step", "aria-pressed": String(!!s.lead), onclick: async () => (await api.patch(`/api/quest-steps/${s.id}`, { lead: !s.lead }), reload()) }, s.lead ? "★" : "☆"),
              h(
                "div",
                { class: "step-body" },
                h("div", { class: "step-title" }, mathText(s.title)),
                h(
                  "div",
                  { class: "muted small" },
                  [qLabel(s.question_id), `${s.minutes} min`, s.low ? `low: ${s.low}` : "", s.high ? `high: ${s.high}` : "", s.document_title ? `reads: ${s.document_title}` : "", s.output ? `→ ${s.output}` : ""].filter(Boolean).join(" · "),
                ),
              ),
              !s.done_at ? h("button", { class: "btn small ghost", title: "Make it one of today's tasks on the Plan page", onclick: async () => {
                const have = await api.get<Related>(`/api/related?kind=quest&id=${q.id}`);
                if (have.tasks.some((t) => t.text === s.title)) return toast("That step is already in Plan.", "info");
                await api.post("/api/todos", { text: s.title.slice(0, 500), minutes: Math.max(1, Math.min(600, s.minutes)), link_type: "step", link_id: s.id, due: ymd(new Date()) });
                toast("Added to today's plan. Finishing the task finishes the step.", "ok", 4500, { label: "Open Plan", run: () => void (location.hash = "#/plan") });
                render();
              } }, "→ Plan") : null,
              !s.done_at && q.status === "active" ? h("button", { class: "btn small", onclick: () => startStep(s) }, "Start") : null,
              h("button", { class: "btn small ghost", "aria-label": "Delete step", onclick: async () => (await confirmBox("Delete this step?", s.title, "Delete")) && (await api.del(`/api/quest-steps/${s.id}`), reload()) }, "✕"),
            ),
          ),
        )
      : h("p", { class: "muted" }, "No steps yet. Start with the lead step: the one that makes the others easier or unnecessary.");

  const addStepFrom = async (text: string, sideId?: string) => {
    await api.post(`/api/quests/${q.id}/steps`, { title: text, minutes: 20, lead: false });
    if (sideId) await api.patch(`/api/side-quests/${sideId}`, {});
    reload();
  };

  const addStepForm = () => {
    const title = h("input", { type: "text", placeholder: "Medium: recall Q2 without notes, then check", "aria-label": "Step" });
    const low = h("input", { type: "text", placeholder: "Low: write one line about Q2", "aria-label": "Low-energy version" });
    const high = h("input", { type: "text", placeholder: "High: explain Q2 aloud, then teach it in writing", "aria-label": "High-energy version" });
    const minutes = h("input", { type: "number", value: 20, min: 2, max: 240, step: 5, "aria-label": "Minutes" });
    const short = (t: string, n = 70) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t);
    const qSel = h("select", { "aria-label": "Moves question" }, h("option", { value: "" }, "Moves no specific question"), q.questions.map((x, i) => h("option", { value: x.id, title: x.text }, `Moves Q${i + 1}: ${short(x.text)}`)));
    const dSel = h("select", { "aria-label": "Reading" }, h("option", { value: "" }, "Not a reading step"), docs.map((d) => h("option", { value: d.id, title: d.title }, `Read: ${short(d.title)}`)));
    const lead = h("input", { type: "checkbox", checked: !q.steps.some((s) => !s.done_at) });
    const err = h("p", { class: "error small", hidden: true });
    const add = async () => {
      if (!title.value.trim()) {
        err.textContent = "Write the step first (the medium version).";
        err.hidden = false;
        title.focus();
        return;
      }
      await api.post(`/api/quests/${q.id}/steps`, {
        title: title.value.trim(), low: low.value.trim(), high: high.value.trim(), minutes: Number(minutes.value) || 20,
        question_id: qSel.value || null, document_id: dSel.value || null, lead: lead.checked,
      });
      reload();
    };
    title.addEventListener("input", () => (err.hidden = true));
    title.addEventListener("keydown", (e) => e.key === "Enter" && add());
    return h(
      "div",
      { class: "add-step" },
      h("div", { class: "kicker" }, "Add a step"),
      title,
      err,
      h("div", { class: "add-step-grid" }, low, high, qSel, dSel),
      h(
        "div",
        { class: "add-step-foot" },
        h("label", { class: "inline" }, minutes, h("span", null, "min")),
        h("label", { class: "toggle" }, lead, " Lead step"),
        h("button", { class: "btn primary", onclick: add }, "Add step"),
      ),
    );
  };

  render();
}
