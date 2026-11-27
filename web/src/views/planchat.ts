// Plan chat (milestone 5.3 of docs/ai/PLAN.md): tell the model what you need ("plan my week around the exam on
// Friday"); it drafts tasks. Code checks each draft (a real day, possible minutes, your free time that day). Nothing is
// added until you press Add; one Undo takes the whole batch back. Text only: h() sets textContent.
import { api } from "../api";
import { state } from "../state";
import { clear, h, type ModalHandle, modal, toast } from "../util";
import { aiIsOn } from "./explain";
import { whyLink } from "./why";

interface Draft { text: string; due: string | null; minutes: number; fits: boolean; flags: string[] }
interface Answer { id: string; reply: string; drafts: Draft[]; already: number; dropped: number; kept: number[]; links: string[]; warning: string }
interface Turn { who: "you" | "model"; text: string }

const MAX_TURNS = 12;
const memo: { turns: Turn[]; answer: Answer | null } = { turns: [], answer: null }; // kept while the app is open

/** The minutes a day you last said you have: a setting (saved in Readhold's database, like any other). */
function storedMinutes(): number {
  const n = Number((state.settings as unknown as Record<string, unknown>).plan_minutes_a_day);
  return n >= 15 && n <= 720 ? n : 120;
}

export function planChatDialog(onChange: () => void): Promise<unknown> {
  let handle: ModalHandle;
  const close = () => handle.close(null);
  if (!aiIsOn()) {
    return modal("Plan with a model", h("div", { class: "stack" },
      h("p", null, "Without AI, add tasks yourself, or let “Plan my reading” spread what is left to read over your days."),
      h("p", { class: "muted small" }, "With AI switched on in Settings, you can tell a model what you need and it drafts the tasks; you choose what to add."),
      h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close"))), { onOpen: (m) => (handle = m) });
  }
  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  const drafts = h("div", { class: "stack" });
  const input = h("textarea", { rows: 2, maxlength: 1000, placeholder: "For example: plan my week around the exam on Friday", "aria-label": "Your message" });
  const perDay = h("input", { type: "number", min: 15, max: 720, step: 15, value: storedMinutes(), "aria-label": "Minutes you have each day" });
  const send = h("button", { type: "button", class: "btn primary" }, "Send");

  const drawLog = () => {
    clear(log);
    log.append(...memo.turns.map((t) => h("p", { class: `chat-turn ${t.who}` }, h("strong", null, t.who === "you" ? "You: " : "Model: "), t.text)));
  };
  const drawDrafts = () => {
    clear(drafts);
    const a = memo.answer;
    if (!a) return;
    const rows = a.drafts.map((d, i) => {
      const done = a.kept.includes(i);
      const pick = h("input", { type: "checkbox", checked: !done, disabled: done, "aria-label": `Add draft ${i + 1}` });
      const text = h("input", { type: "text", value: d.text, maxlength: 500, "aria-label": `Task ${i + 1}` });
      const due = h("input", { type: "date", value: d.due ?? "", "aria-label": `Day of task ${i + 1}` });
      const minutes = h("input", { type: "number", min: 1, max: 600, value: d.minutes, "aria-label": `Minutes of task ${i + 1}` });
      const li = h("li", { class: d.fits ? "" : "unchecked" }, h("div", { class: "row wrap" }, pick, text, due, minutes, done ? h("span", { class: "muted small" }, "Added") : null),
        d.flags.length ? h("ul", { class: "tidy-hints" }, d.flags.map((f) => h("li", null, f))) : null);
      return { li, pick, text, due, minutes, i };
    });
    const add = h("button", { type: "button", class: "btn primary", onclick: async () => {
      const items = rows.filter((x) => x.pick.checked && !x.pick.disabled).map((x) => ({ index: x.i, text: x.text.value, due: x.due.value || null, minutes: Number(x.minutes.value) }));
      if (!items.length) return toast("Tick the drafts you want to add.", "info");
      add.disabled = true; // one click, one batch
      try {
        const r = await api.post<{ batch: string; added: number; kept: number[] }>(`/api/plan/chat/${a.id}/add`, { items });
        a.kept = r.kept;
        onChange();
        drawDrafts();
        toast(`Added ${r.added} task${r.added === 1 ? "" : "s"} to Plan, each noting a model drafted it.`, "ok", 9000, { label: "Undo", run: async () => {
          try {
            const u = await api.post<{ removed: number; stayed: number; kept: number[] }>(`/api/plan/chat/${a.id}/undo`, { batch: r.batch });
            a.kept = u.kept; // what was taken back can be added again
            onChange();
            drawDrafts();
            toast(u.stayed ? `Took back ${u.removed}; ${u.stayed} you already changed or started stay.` : `Took back ${u.removed}.`, "info");
          } catch (e) {
            toast((e as Error).message, "error");
          }
        } });
      } catch (e) {
        add.disabled = false;
        toast((e as Error).message, "error");
      }
    } }, "Add the ticked tasks to Plan");
    drafts.append(h("div", { class: "ai-text" },
      h("div", { class: "ai-text-label" }, "Drafted by the AI model. Each was checked: its day, its minutes and your free time that day. Nothing is added until you press Add.", whyLink(a.id)),
      rows.length ? h("ol", { class: "study-items" }, rows.map((x) => x.li)) : h("p", { class: "muted small" }, "No tasks this time."),
      a.already ? h("p", { class: "muted small" }, `${a.already} draft${a.already === 1 ? " was" : "s were"} already in your plan, so ${a.already === 1 ? "it is" : "they are"} left out.`) : null,
      a.dropped ? h("p", { class: "muted small" }, `${a.dropped} more ${a.dropped === 1 ? "was" : "were"} left out: at most 12 at a time.`) : null,
      a.warning ? h("div", { class: "ai-text-links" }, a.warning) : null,
      rows.length ? h("div", { class: "row end" }, add) : null));
  };
  const run = async () => {
    const text = input.value.trim();
    if (!text) return;
    const minutes = Number(perDay.value);
    if (minutes !== storedMinutes()) void api.put("/api/settings", { plan_minutes_a_day: minutes }).then((s) => ((state.settings as unknown) = s), () => undefined);
    const turns: Turn[] = [...memo.turns, { who: "you" as const, text }].slice(-MAX_TURNS);
    if (turns[0]?.who === "model") turns.shift();
    send.disabled = true;
    try {
      const a = (await api.post<{ result: Answer }>("/api/plan/chat", { messages: turns, minutes_a_day: minutes })).result;
      memo.turns = [...turns, { who: "model" as const, text: a.reply || "(no reply)" }];
      memo.answer = a;
      input.value = "";
      drawLog();
      drawDrafts();
    } catch (e) {
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
  drawDrafts();
  const body = h("div", { class: "stack" },
    h("p", { class: "muted small" }, "The model reads your next days with their free time, your open tasks and your reading deadlines. It only drafts: you choose what is added."),
    log,
    h("label", { class: "row" }, h("span", { class: "muted small" }, "Minutes you have each day"), perDay),
    h("div", { class: "row" }, input, send),
    drafts,
    h("div", { class: "row between" },
      h("button", { type: "button", class: "link small", onclick: () => ((memo.turns = []), (memo.answer = null), drawLog(), drawDrafts()) }, "Start over"),
      h("button", { type: "button", onclick: close }, "Close")));
  return modal("Plan with a model", body, { wide: true, onOpen: (m) => (handle = m) });
}
