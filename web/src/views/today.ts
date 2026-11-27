// Today: one screen, one decision. Your energy, the one thing that matters, and a Start button.
// Below it: the side-quest check, your rhythm, and real output (answers and finished steps, not hours).
import { planHead } from "./libtabs";
import { ambience } from "../ambience";
import { api, save } from "../api";
import { mathText } from "../math";
import { state } from "../state";
import { applyTheme } from "../themes";
import type { DayLog, Energy, Habit, PlanData, Quest, QuestStep, Today } from "../types";
import { removeItem } from "../trash";
import { append, askText, clear, fmtMinutes, h, keepTyped, type ModalHandle, modal, toast } from "../util";

interface HomeData {
  resume: { document_id: string; title: string; position: number; sentence: string | null; next_step: string; progress: { ratio: number } } | null;
  confusions: { id: string }[];
  due_cards: number;
  streak: number;
  today: { counts: boolean };
}

const ENERGY_LABEL: Record<Energy, string> = { low: "Low", medium: "Medium", high: "High" };

/** The version of a step that fits today's energy. */
export function stepFor(step: QuestStep, energy: Energy): string {
  if (energy === "low") return step.low || step.title;
  if (energy === "high") return step.high || step.title;
  return step.title;
}

export function startStep(step: QuestStep): void {
  location.hash = step.document_id ? `#/read/${step.document_id}` : `#/focus/${step.id}`;
}

const hourLabel = (h24: number) => `${((h24 + 11) % 12) + 1}${h24 < 12 ? " am" : " pm"}`;

function greeting(): string {
  const hr = new Date().getHours();
  return hr < 5 ? "Working late" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
}

function daysLeft(deadline: string | null): string {
  if (!deadline) return "";
  const days = Math.round((new Date(`${deadline}T23:59:59`).getTime() - Date.now()) / 86_400_000);
  return days < 0 ? "past its deadline" : days === 0 ? "due today" : days === 1 ? "due tomorrow" : `${days} days left`;
}

export async function todayView(root: HTMLElement): Promise<void> {
  const [t, home] = await Promise.all([api.get<Today>("/api/today"), api.get<HomeData>("/api/home")]);
  let energy: Energy = t.checkin?.energy ?? state.energy;
  state.energy = energy; // today's check-in sizes everything: steps, the pacer, the theme's motion
  const page = h("section", { class: "today" });
  root.append(planHead("today"), page);
  // today's tasks and routines in one line (the Plan page has the rest)
  let plan: PlanData | null = null;
  const planPeek = () => {
    if (!plan) return null;
    const due = plan.tasks.filter((x) => !x.done_at && x.due && x.due <= plan!.today);
    const done = plan.tasks.filter((x) => x.done_at).length;
    const routines = plan.routines.filter((r) => r.steps.length);
    if (!due.length && !done && !routines.length) return null;
    const next = routines.find((r) => r.done < r.steps.length);
    return h("a", { class: "plan-peek", href: "#/plan" },
      h("span", { class: "kicker" }, "Plan"),
      h("span", { class: "plan-peek-text" },
        due.length ? `${due.length} task${due.length === 1 ? "" : "s"} for today` : done ? "Today's tasks are done" : "No tasks chosen for today",
        done && due.length ? ` · ${done} done` : "",
        next ? ` · ${next.title}: ${next.done} of ${next.steps.length}` : routines.length ? " · routines done" : ""),
      h("span", { class: "plan-peek-go", "aria-hidden": "true" }, "→"));
  };

  const render = () => keepTyped(page, () => { // the plan's numbers arrive late: what you typed meanwhile stays
    clear(page);
    append(page, [header(), t.empty_streak >= 3 ? methodHint() : null, t.quest ? questCard(t.quest) : noQuest(), planPeek(), sideCheck(), habitsCard(), tiles(), closeDay(), readingRow()]);
    page.querySelector<HTMLElement>("[autofocus]")?.focus(); // Enter starts the lead step
  });
  api.get<PlanData>("/api/plan").then((p) => {
    plan = p;
    if (page.isConnected && !document.querySelector(".modal-back")) render();
  }, () => undefined);

  // ---------------------------------------------------------------- header + energy check-in
  const header = () => {
    const peak = t.energy.peak ? `Your peak focus: ${hourLabel(t.energy.peak[0])}–${hourLabel(t.energy.peak[1])}` : "Learning your rhythm from your sessions";
    const seg = h("div", { class: "seg energy-seg", role: "group", "aria-label": "Energy right now" });
    (["low", "medium", "high"] as Energy[]).forEach((e) => {
      seg.append(
        h("button", {
          class: e === energy ? "on" : "",
          "aria-pressed": String(e === energy),
          onclick: async () => {
            energy = e;
            state.energy = e;
            applyTheme();
            await save("post", "/api/checkins", { energy: e });
            t.checkin = (await api.get<Today>("/api/today")).checkin; // the ✕ then removes this tap, the latest one
            render();
          },
        }, ENERGY_LABEL[e]),
      );
    });
    return h(
      "header",
      { class: "today-head" },
      h("div", null, h("p", { class: "muted small" }, new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }), " · ", peak), h("h1", null, t.quest ? `${greeting()}. One thing matters today.` : `${greeting()}.`)),
      h("div", { class: "energy-check" }, h("span", { class: "muted small" }, t.checkin ? "Energy" : "How's your energy?"), seg,
        t.checkin ? h("button", { class: "link small checkin-remove", title: "Remove this check-in (an earlier one from today counts again)", "aria-label": "Remove today's energy check-in", onclick: () => void removeCheckin() }, "✕") : null),
    );
  };
  // each tap on an energy is a check-in; removing the latest one makes an earlier one of today count again
  const removeCheckin = async () => {
    const id = (t.checkin as { id?: string } | null)?.id;
    if (!id) return;
    const fresh = async () => {
      t.checkin = (await api.get<Today>("/api/today")).checkin;
      if (t.checkin) energy = state.energy = t.checkin.energy;
      applyTheme();
      render();
    };
    await removeItem("checkin", id, `Removed this energy check-in (${ENERGY_LABEL[t.checkin!.energy]}).`, { gone: () => void fresh(), back: () => void fresh() });
  };

  const methodHint = () =>
    h(
      "div",
      { class: "notice warn" },
      h("strong", null, "Your last sessions produced nothing. "),
      "Change the method, not the effort: pick the smallest version of the step, switch format (explain it aloud, draw it, write the question first), or ask someone.",
    );

  // ---------------------------------------------------------------- the main quest
  const questCard = (q: Quest) => {
    const lead = q.lead;
    const qIndex = (id: string | null) => q.questions.findIndex((x) => x.id === id);
    const pct = q.progress.total ? Math.round((q.progress.answered / q.progress.total) * 100) : 0;
    const questions = h(
      "ol",
      { class: "quest-questions" },
      q.questions.map((x, i) =>
        h(
          "li",
          { class: x.answer ? "done" : "" },
          h("button", {
            class: "link",
            title: x.answer ? "Answered — click to revise" : "Answer it in your own words",
            onclick: async () => {
              const a = await askText(`Q${i + 1}`, x.text, x.answer, { multiline: true, okLabel: "Save answer", placeholder: "In your own words, from memory first" });
              if (a === null) return;
              await api.patch(`/api/quest-questions/${x.id}`, { answer: a });
              if (a && !x.answer) ambience.moment();
              x.answer = a;
              q.progress.answered = q.questions.filter((y) => y.answer).length;
              render();
            },
          }, h("span", { class: "q-mark", "aria-hidden": "true" }, x.answer ? "✓" : `${i + 1}`), x.text),
        ),
      ),
    );
    const leadBox = lead
      ? h(
          "div",
          { class: "lead-step" },
          h("div", { class: "lead-arrow", "aria-hidden": "true" }, "→"),
          h(
            "div",
            { class: "lead-text" },
            h("div", { class: "kicker" }, "Lead step"),
            h("p", { class: "lead-title" }, mathText(stepFor(lead, energy))),
            h(
              "p",
              { class: "muted small" },
              `${ENERGY_LABEL[energy]} energy version · about ${energy === "low" ? Math.max(5, Math.round(lead.minutes / 3)) : lead.minutes} min`,
              qIndex(lead.question_id) >= 0 ? ` · moves Q${qIndex(lead.question_id) + 1}` : "",
              lead.document_title ? ` · reading: ${lead.document_title}` : "",
            ),
          ),
          h("button", { class: "btn primary start", autofocus: true, onclick: () => startStep(lead) }, "Start"),
        )
      : h(
          "div",
          { class: "lead-step no-step" },
          h("p", null, q.progress.answered === q.progress.total && q.progress.total ? "Every question is answered. Finish the goal, or add a step." : "No open steps. Add the one that makes the others easier."),
          h("a", { class: "btn", href: `#/quest/${q.id}` }, "Add a step"),
        );
    return h(
      "article",
      { class: "quest-card" },
      h(
        "div",
        { class: "quest-top" },
        h("span", { class: "badge accent" }, "Main goal"),
        q.deadline ? h("span", { class: "muted small" }, daysLeft(q.deadline)) : null,
        h("a", { class: "quest-edit", href: `#/quest/${q.id}` }, "Open goal"),
      ),
      h("h2", { class: "quest-title" }, q.title),
      q.why ? h("p", { class: "muted quest-why" }, q.why) : null,
      questions,
      leadBox,
      h("div", { class: "meter", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": pct, "aria-label": "Questions answered" }, h("span", { style: { width: `${pct}%` } })),
      h("p", { class: "muted small" }, `${q.progress.answered} of ${q.progress.total} questions answered`, q.side_quests.length ? ` · ${q.side_quests.length} parked` : ""),
    );
  };

  const noQuest = () => {
    const r = home.resume;
    // No quest yet but something half-read: resuming stays one key away (Enter), like the old Home.
    const resume = r
      ? h(
          "article",
          { class: "quest-card resume-inline" },
          h("div", { class: "quest-top" }, h("span", { class: "badge" }, "Continue reading"), h("span", { class: "muted small" }, `${Math.round(r.progress.ratio * 100)}% of key sentences`)),
          h("h2", { class: "quest-title" }, r.title),
          h("p", { class: "next-step-inline" }, r.next_step || (r.sentence ? `Pick up at: “${r.sentence}”` : "Pick up where you left off.")),
          h("a", { class: "btn primary start", href: `#/read/${r.document_id}`, autofocus: true }, "Resume"),
        )
      : null;
    return [
      resume,
      h(
        "article",
        { class: `quest-card no-quest ${r ? "compact" : ""}` },
        h("span", { class: "badge accent" }, "Main goal"),
        h("h2", { class: "quest-title" }, "What's the one thing that matters this week?"),
        h("p", { class: "muted" }, "Name it, write the 3 questions it must answer, and Readhold keeps you pointed at it: one lead step at a time, sized to your energy."),
        h("a", { class: r ? "btn" : "btn primary", href: "#/quest/new", autofocus: r ? undefined : true }, "Set your main goal"),
      ),
    ];
  };

  // ---------------------------------------------------------------- side-quest check
  const sideCheck = () => {
    const input = h("input", { type: "text", placeholder: "Something pulling at you? (a tutorial, a tool, a rabbit hole)", "aria-label": "Something pulling at you" });
    const out = h("div", { class: "side-out" });
    const decide = (text: string) => {
      clear(out);
      const q = t.quest;
      const done = (msg: string) => {
        clear(out);
        out.append(h("p", { class: "muted small" }, msg));
        input.value = "";
      };
      const linkBtns = q
        ? q.questions.map((x, i) =>
            h("button", {
              class: "chip",
              onclick: async () => {
                await save("post", "/api/side-quests", { text, decision: "linked", question_id: x.id });
                done(`Good: it moves Q${i + 1}. Add it as a step in the goal if it needs real time.`);
              },
            }, `Moves Q${i + 1}`),
          )
        : [];
      out.append(
        h("p", { class: "small" }, q ? `Does “${text}” answer one of your questions?` : `No main goal yet. Park “${text}”, or give it a time box?`),
        h(
          "div",
          { class: "row wrap" },
          linkBtns,
          h("button", {
            class: "chip",
            onclick: async () => {
              await save("post", "/api/side-quests", { text, decision: "parked" });
              t.parked++;
              done("Parked. It's safe in your list; your main goal is still the thing.");
            },
          }, "Park it"),
          h("button", {
            class: "chip",
            onclick: async () => {
              await save("post", "/api/side-quests", { text, decision: "timeboxed", minutes: 15 });
              location.hash = `#/focus/side?text=${encodeURIComponent(text)}&min=15`;
            },
          }, "Give it 15 min"),
        ),
      );
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && input.value.trim()) decide(input.value.trim());
    });
    return h(
      "div",
      { class: "side-check" },
      h("div", { class: "side-row" }, h("span", { class: "side-icon", "aria-hidden": "true" }, "◎"), input, h("button", { class: "btn", onclick: () => input.value.trim() && decide(input.value.trim()) }, "Check")),
      out,
    );
  };

  // ---------------------------------------------------------------- rhythm and output
  const tiles = () => {
    const hrs = t.energy.hours;
    const slots = [6, 8, 10, 12, 14, 16, 18, 20, 22].map((s) => ({ s, v: hrs[s] + hrs[s + 1] }));
    const max = Math.max(1, ...slots.map((x) => x.v));
    const nowSlot = Math.floor((new Date().getHours() - 6) / 2);
    const curve = h(
      "div",
      { class: "curve", "aria-label": t.energy.learning ? "Not enough sessions yet" : "Focused minutes by time of day" },
      slots.map((x, i) =>
        h("span", {
          class: `${t.energy.peak && (x.s === t.energy.peak[0] || x.s + 1 === t.energy.peak[0]) ? "peak" : ""} ${i === nowSlot ? "now" : ""}`,
          style: { height: `${t.energy.learning ? 12 + ((i * 37) % 40) : Math.max(8, (x.v / max) * 100)}%` },
          title: `${hourLabel(x.s)}–${hourLabel(x.s + 2)}`,
        }),
      ),
    );
    const o = t.output;
    const ratio = o.on_quest_ratio;
    return h(
      "div",
      { class: "tiles" },
      h(
        "div",
        { class: "tile" },
        h("div", { class: "tile-label" }, "Your rhythm"),
        curve,
        h("div", { class: "muted small" }, t.energy.learning ? "A few more sessions and this shows your best hours." : hardNow(t)),
      ),
      h("div", { class: "tile" }, h("div", { class: "tile-label" }, "Real output today"), h("div", { class: "tile-num" }, String(o.answers + o.steps)), h("div", { class: "muted small" }, `${o.answers} answer${o.answers === 1 ? "" : "s"} · ${o.steps} step${o.steps === 1 ? "" : "s"} done`, o.empty_sessions ? ` · ${o.empty_sessions} empty session${o.empty_sessions > 1 ? "s" : ""}` : "")),
      h(
        "div",
        { class: "tile" },
        h("div", { class: "tile-label" }, "On the main goal"),
        h("div", { class: "tile-num" }, ratio === null || o.focused_ms < 60_000 ? "—" : `${Math.round(ratio * 100)}%`),
        h("div", { class: "muted small" }, o.focused_ms ? `${fmtMinutes(o.on_quest_ms)} of ${fmtMinutes(o.focused_ms)} focused` : "No focused time yet today"),
      ),
    );
  };

  // ---------------------------------------------------------------- tiny habits (never miss twice)
  const habitsCard = () => {
    const row = (hb: Habit) => {
      const label = energy === "low" && hb.tiny ? hb.tiny : hb.title;
      return h(
        "li",
        { class: `habit ${hb.done_today ? "done" : ""}` },
        h("button", {
          class: "habit-check",
          "aria-pressed": String(hb.done_today),
          "aria-label": hb.done_today ? `Undo ${hb.title}` : `Done: ${hb.title}`,
          onclick: async () => {
            const fresh = await api.post<Habit>(`/api/habits/${hb.id}/check`);
            Object.assign(hb, fresh);
            if (fresh.done_today) ambience.moment();
            render();
          },
        }, hb.done_today ? "✓" : ""),
        h(
          "div",
          { class: "habit-body" },
          h("div", { class: "habit-title" }, label, energy === "low" && hb.tiny ? h("span", { class: "muted small" }, " (tiny version)") : null),
          h(
            "div",
            { class: "muted small" },
            hb.anchor ? `${hb.anchor} · ` : "",
            hb.streak ? `${hb.streak}-day streak` : "Start today",
            hb.missed_yesterday && !hb.done_today ? h("span", { class: "miss" }, " · missed yesterday: don’t miss twice") : null,
          ),
        ),
        h("div", { class: "habit-dots", "aria-hidden": "true", title: "Last 14 days" }, hb.last14.map((d) => h("span", { class: d ? "on" : "" }))),
        h("button", {
          class: "btn small ghost",
          "aria-label": `Stop tracking or delete ${hb.title}`,
          title: "Stop tracking or delete",
          onclick: () => void stopOrDelete(hb),
        }, "✕"),
      );
    };
    // stop tracking keeps the habit and its history out of the way; delete removes it from the app (with Undo)
    const stopOrDelete = async (hb: Habit) => {
      let hm: ModalHandle;
      const choice = await modal("Stop tracking or delete?", h("div", { class: "stack" },
        h("p", null, `“${hb.title}”. Stop tracking keeps it and its history saved. Delete removes it from Readhold: its streak and checks leave Today, the journal and the weekly review.`),
        h("div", { class: "row end" },
          h("button", { onclick: () => hm.close(null) }, "Cancel"),
          h("button", { onclick: () => hm.close("delete") }, "Delete"),
          h("button", { class: "primary", onclick: () => hm.close("stop") }, "Stop tracking"))), { onOpen: (m) => (hm = m) });
      const at = Math.max(0, t.habits.indexOf(hb));
      const putBack = (back: Habit) => {
        const rest = t.habits.filter((x) => x.id !== back.id);
        rest.splice(Math.min(at, rest.length), 0, back); // where it was
        t.habits = rest;
        render();
      };
      if (choice === "stop") {
        await api.patch(`/api/habits/${hb.id}`, { archived: true });
        t.habits = t.habits.filter((x) => x.id !== hb.id);
        render();
        toast(`Stopped tracking “${hb.title}”.`, "info", 8000, { label: "Undo", run: async () => putBack(await api.patch<Habit>(`/api/habits/${hb.id}`, { archived: false })) });
      } else if (choice === "delete") {
        await removeItem("habit", hb.id, `Deleted the habit “${hb.title}”.`, {
          gone: () => ((t.habits = t.habits.filter((x) => x.id !== hb.id)), render()),
          back: async () => {
            const all = await api.get<Habit[]>("/api/habits");
            const back = all.find((x) => x.id === hb.id);
            if (back) putBack(back);
          },
        });
      }
    };
    const add = async () => {
      const title = h("input", { type: "text", autofocus: true, placeholder: "Review 5 cards", "aria-label": "Habit" });
      const anchor = h("input", { type: "text", placeholder: "After my morning coffee", "aria-label": "After what" });
      const tiny = h("input", { type: "text", placeholder: "Review 1 card", "aria-label": "Tiny version" });
      const err = h("p", { class: "error small", hidden: true });
      title.addEventListener("input", () => (err.hidden = true));
      let hm: ModalHandle;
      const ok = await modal(
        "A tiny habit",
        h(
          "div",
          { class: "stack" },
          h("p", { class: "muted small" }, "Small enough to do on your worst day, tied to something you already do."),
          h("label", { class: "field" }, h("span", null, "The habit"), title),
          err,
          h("label", { class: "field" }, h("span", null, "When: after I…"), anchor),
          h("label", { class: "field" }, h("span", null, "The 2-minute version for low days"), tiny),
          h(
            "div",
            { class: "row end" },
            h("button", { onclick: () => hm.close(null) }, "Cancel"),
            h("button", {
              class: "primary",
              onclick: () => {
                if (title.value.trim()) hm.close("ok");
                else {
                  err.textContent = "Name the habit first.";
                  err.hidden = false;
                  title.focus();
                }
              },
            }, "Add habit"),
          ),
        ),
        { onOpen: (m) => (hm = m) },
      );
      if (ok !== "ok") return;
      const a = anchor.value.trim();
      const hb = await api.post<Habit>("/api/habits", { title: title.value.trim(), anchor: a && !/^after\b/i.test(a) ? `After ${a}` : a, tiny: tiny.value.trim() });
      t.habits.push(hb);
      render();
    };
    const done = t.habits.filter((x) => x.done_today).length;
    return h(
      "div",
      { class: "habits-card" },
      h(
        "div",
        { class: "habits-head" },
        h("div", { class: "tile-label" }, "Tiny habits"),
        t.habits.length ? h("span", { class: "muted small" }, `${done} of ${t.habits.length} today`) : null,
        h("button", { class: "btn small", onclick: add }, "+ Add a habit"),
      ),
      t.habits.length
        ? h("ul", { class: "habit-list" }, t.habits.map(row))
        : h("p", { class: "muted small" }, "One tiny habit tied to something you already do beats a big plan. Missing one day is fine; never miss twice."),
    );
  };

  // ---------------------------------------------------------------- close the day
  const closeDay = () => {
    const log = t.log_today;
    const evening = new Date().getHours() >= 17;
    const open = async () => {
      const field = (label: string, value: string, placeholder: string) => {
        const el = h("input", { type: "text", value, placeholder, "aria-label": label });
        return { el, wrap: h("label", { class: "field" }, h("span", null, label), el) };
      };
      const did = field("What I did", log?.did ?? "", "Read 3.2, answered Q1");
      const learned = field("What I learned", log?.learned ?? "", "Scaling by √d_k keeps the softmax from saturating");
      const next = field("Tomorrow’s first step", log?.next ?? "", "Recall Q2 without notes");
      const lead = h("input", { type: "checkbox", checked: Boolean(t.quest) });
      did.el.setAttribute("autofocus", "");
      let hm: ModalHandle;
      const ok = await modal(
        "Close your day",
        h(
          "div",
          { class: "stack" },
          h("p", { class: "muted small" }, "Two minutes. Writing tomorrow’s first step lets your head stop holding it."),
          did.wrap,
          learned.wrap,
          next.wrap,
          t.quest ? h("label", { class: "toggle" }, lead, " Make it tomorrow’s lead step") : null,
          h("div", { class: "row end" }, h("button", { onclick: () => hm.close(null) }, "Cancel"), h("button", { class: "primary", onclick: () => hm.close("ok") }, "Close the day")),
        ),
        { onOpen: (m) => (hm = m) },
      );
      if (ok !== "ok") return;
      await api.post<{ log: DayLog }>("/api/logs", { did: did.el.value, learned: learned.el.value, next: next.el.value, next_as_lead: lead.checked });
      toast("Day closed. Rest well.", "ok");
      Object.assign(t, await api.get<Today>("/api/today"));
      render();
    };
    if (log) {
      return h(
        "div",
        { class: "close-day closed" },
        h("span", { class: "q-mark done-mark", "aria-hidden": "true" }, "✓"),
        h("div", { class: "close-text" }, h("strong", null, "Day closed"), log.next ? h("span", { class: "muted small" }, ` · tomorrow starts with: ${log.next}`) : null),
        h("button", { class: "btn small ghost", onclick: open }, "Edit"),
      );
    }
    return h(
      "div",
      { class: `close-day ${evening ? "evening" : ""}` },
      h("div", { class: "close-text" }, h("strong", null, "Close your day"), h("span", { class: "muted small" }, " · 2 minutes: did, learned, tomorrow’s first step")),
      h("button", { class: evening ? "btn primary" : "btn", onclick: open }, "Close the day"),
    );
  };

  const readingRow = () => {
    const r = home.resume;
    // The themed world grows from real progress: the main quest's answered questions (trees, sky, moon,
    // the path), and today's answers, finished steps and habits (one flower each in the Garden).
    const q = t.quest;
    const questRatio = q && q.progress.total ? q.progress.answered / q.progress.total : null;
    ambience.update({
      progress: questRatio ?? r?.progress.ratio ?? 0,
      answered: t.output.answers + t.output.steps + t.habits.filter((x) => x.done_today).length,
    });
    return h(
      "div",
      { class: "home-quiet" },
      r ? h("a", { href: `#/read/${r.document_id}` }, `Continue reading: ${r.title}`) : h("a", { href: "#/library" }, "Add something to read"),
      home.due_cards ? h("a", { href: "#/review" }, `${home.due_cards} cards to review (~${Math.max(1, Math.round(home.due_cards / 6))} min)`) : null,
      t.letters_due ? h("a", { class: "letter-due", href: "#/journal" }, `✉ A letter from past you is ready`) : null,
      home.confusions.length ? h("span", null, `${home.confusions.length} open confusion${home.confusions.length > 1 ? "s" : ""}, shown first when you read`) : null,
      t.parked ? h("a", { href: "#/quest" }, `${t.parked} parked`) : null,
      h("span", null, home.streak ? `${home.streak}-day streak` : "A day counts with 10 minutes or a review", home.today.counts ? " · today counts" : ""),
    );
  };

  render();
  if (!t.checkin) toast("Tap your energy: Readhold sizes the next step to it.", "info", 4500);
}

function hardNow(t: Today): string {
  if (!t.energy.peak) return "";
  const hr = new Date().getHours();
  const [a, b] = t.energy.peak;
  const inPeak = a < b ? hr >= a && hr < b : hr >= a || hr < b;
  return inPeak ? "You're in your peak: do the hard thinking now." : `Hard thinking fits best around ${hourLabel(a)}. Now suits lighter steps.`;
}
