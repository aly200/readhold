// Reading plan (milestone 3.1 of docs/ai/PLAN.md): choose what to read, in which order, how hard each one is and by
// when; Readhold spreads what is left over your days (readhold/readplan.py), never past your minutes a day or the
// deadline. With AI on, on a button press, a model suggests the order and levels; nothing changes until you press
// "Use this order" (with Undo), and the schedule is still made by code. Adding the plan to Plan makes tasks you can
// take back in one step. Text only: h() sets textContent.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, debounce, h, type ModalHandle, modal, toast } from "../util";
import { aiIsOn } from "./explain";

type Level = "easy" | "medium" | "hard";
interface Candidate { id: string; title: string; why: string; deadline: string | null; words_left: number; minutes_left: number; sections_left: number }
interface Item { document_id: string; title: string; minutes: number; from: string; to: string; continued: boolean }
interface Day { day: string; items: Item[]; minutes: number; busy: number; room: number }
interface Plan {
  days: Day[]; unplaced: { document_id: string; title: string; minutes: number }[]; fits: boolean; total: number; need_per_day: number | null;
  deadline: string; per_day: number; nothing_left: string[]; key: string;
}
interface Pick { document_id: string; title: string; level: Level; level_from_model: boolean; reason: string; placed: boolean; verified: boolean; quote?: string; nothing_left?: boolean }
interface Suggestion { id: string; order: Pick[]; status: "verified" | "partly" | "unverified"; provider: string; links: string[]; warning: string; cut?: boolean; left_out?: number }
interface Start { documents: Candidate[]; wpm: number; today: string; last_batch: { id: string; open: number } | null; levels: Record<Level, number> }

const LEVEL_LABEL: Record<Level, string> = { easy: "Easy", medium: "Medium", hard: "Hard" };
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // 0 = Monday, as the server counts
const MAX_DOCS = 20; // readhold/readplan.py
const STATUS: Record<Suggestion["status"], string> = {
  verified: "Each reason rests on a passage of that document. The levels are the model's estimate.",
  partly: "Some reasons rest on a passage of the document; the others are the model's guess. The levels are its estimate.",
  unverified: "No reason rests on a passage of the documents. Treat the order as a guess. The levels are its estimate.",
};

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (s: string, n: number): string => {
  const [y, m, d] = s.split("-").map(Number);
  return ymd(new Date(y, m - 1, d + n));
};
const dayLabel = (s: string): string => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
};
const fmt = (min: number): string => (min < 60 ? `${min} min` : `${Math.floor(min / 60)} h${min % 60 ? ` ${min % 60} min` : ""}`);

export async function readingPlanDialog(onAdded: () => void): Promise<unknown> {
  const start = await api.get<Start>("/api/reading-plan");
  let handle: ModalHandle;
  const close = () => handle.close(null);
  if (!start.documents.length) {
    return modal("Plan my reading", h("div", { class: "stack" },
      h("p", null, "There is nothing left to read: every document is finished, or the library is empty."),
      h("div", { class: "row end" }, h("a", { class: "btn", href: "#/library", onclick: () => close() }, "Open Documents"), h("button", { type: "button", onclick: () => close() }, "Close"))),
    { onOpen: (m) => (handle = m) });
  }

  // the form: the order of the list is the reading order; ticked rows are in the plan
  let rows = start.documents.map((d, i) => ({ doc: d, on: i < 3, level: "medium" as Level }));
  let fromAi = ""; // the suggestion the order came from, while you use it
  const soonest = start.documents.map((d) => d.deadline).filter((d): d is string => !!d && d >= start.today).sort()[0];
  const deadline = h("input", { type: "date", min: start.today, max: addDays(start.today, 365), value: soonest ?? addDays(start.today, 13), "aria-label": "Finish by" });
  const perDay = h("input", { type: "number", min: 5, max: 600, step: 5, value: "30", "aria-label": "Minutes a day" });
  const off = new Set<number>();
  const goal = h("input", { type: "text", maxlength: 200, placeholder: "Optional, e.g. Understand routing for Friday's seminar", "aria-label": "What the reading is for" });
  const list = h("ol", { class: "rp-docs" });
  const preview = h("div", { class: "rp-preview", "aria-live": "polite" });
  const aiOut = h("div", { class: "study-out", "aria-live": "polite" });
  let plan: Plan | null = null;
  let seq = 0;

  const chosen = () => rows.filter((r) => r.on);
  const body = () => ({
    documents: chosen().map((r) => ({ id: r.doc.id, level: r.level })),
    deadline: deadline.value, minutes_per_day: Math.round(Number(perDay.value)) || 0,
    days_off: [...off].sort().join(""), goal: goal.value.trim(), ...(fromAi ? { from_ai: fromAi } : {}),
  });

  const drawList = () => {
    clear(list);
    rows.forEach((r, i) => {
      const box = h("input", { type: "checkbox", checked: r.on, "data-k": `on-${r.doc.id}`, "aria-label": `Plan ${r.doc.title}`, onchange: () => {
        if (!r.on && chosen().length >= MAX_DOCS) {
          box.checked = false;
          return toast(`At most ${MAX_DOCS} documents in one plan.`, "info");
        }
        r.on = box.checked;
        changed(true, `on-${r.doc.id}`);
      } });
      const level = h("select", { "aria-label": `How hard ${r.doc.title} is`, "data-k": `lvl-${r.doc.id}`, disabled: !r.on, onchange: () => ((r.level = level.value as Level), changed(true, `lvl-${r.doc.id}`)) },
        (Object.keys(LEVEL_LABEL) as Level[]).map((k) => h("option", { value: k }, `${LEVEL_LABEL[k]}${start.levels[k] !== 1 ? ` (×${start.levels[k]})` : ""}`)));
      level.value = r.level;
      const move = (by: number) => () => {
        const j = i + by;
        if (j < 0 || j >= rows.length) return;
        [rows[i], rows[j]] = [rows[j], rows[i]];
        changed(true);
        list.querySelectorAll<HTMLButtonElement>(by < 0 ? ".rp-up" : ".rp-down")[j]?.focus();
      };
      list.append(h("li", { class: r.on ? "" : "is-off" },
        h("label", { class: "rp-doc" }, box, h("span", { class: "rp-title" }, r.doc.title),
          h("span", { class: "muted small" }, ` · about ${fmt(r.doc.minutes_left)} left${r.doc.deadline ? ` · due ${r.doc.deadline}` : ""}`)),
        level,
        h("button", { type: "button", class: "task-btn ghost rp-up", "aria-label": `Read ${r.doc.title} earlier`, title: "Earlier", disabled: i === 0, onclick: move(-1) }, "↑"),
        h("button", { type: "button", class: "task-btn ghost rp-down", "aria-label": `Read ${r.doc.title} later`, title: "Later", disabled: i === rows.length - 1, onclick: move(1) }, "↓")));
    });
  };

  const drawPlan = (p: Plan) => {
    clear(preview);
    const days = p.days.filter((d) => d.items.length);
    const tasks = days.reduce((n, d) => n + d.items.length, 0);
    preview.append(h("p", { class: p.fits ? "" : "rp-warn" }, p.fits
      ? `${fmt(p.total)} of reading over ${days.length} day${days.length === 1 ? "" : "s"}, finished by ${dayLabel(p.deadline)}. No day holds more than ${p.per_day} minutes.`
      : `This does not fit: ${fmt(p.unplaced.reduce((n, u) => n + u.minutes, 0))} is left over. ${p.need_per_day ? `It would take ${p.need_per_day} minutes a day, or a later deadline, or fewer documents.` : "Choose a later deadline or fewer documents."} Only what fits is added.`));
    if (p.nothing_left.length) preview.append(h("p", { class: "muted small" }, `Nothing left to read in: ${p.nothing_left.join(", ")}.`));
    if (p.unplaced.length) preview.append(h("ul", { class: "rp-unplaced" }, p.unplaced.map((u) => h("li", null, `Does not fit: “${u.title}”, ${fmt(u.minutes)}`))));
    preview.append(h("ol", { class: "rp-days" }, p.days.map((d) => h("li", { class: d.items.length ? "" : "is-empty" },
      h("div", { class: "rp-day-head" }, h("strong", null, dayLabel(d.day)),
        h("span", { class: "muted small" }, d.items.length ? ` ${d.minutes} of ${d.room} min` : d.busy ? " already planned" : " free"),
        d.busy ? h("span", { class: "tchip quiet", title: "Reading-plan tasks already on this day" }, `${d.busy} min planned before`) : null),
      d.items.length ? h("ul", null, d.items.map((it) => h("li", null,
        `“${it.title}”: ${it.from}${it.to !== it.from ? ` → ${it.to}` : ""}${it.continued ? " (continued)" : ""}`, h("span", { class: "muted small" }, ` · ${it.minutes} min`)))) : null))));
    addBtn.disabled = !tasks;
    addBtn.textContent = tasks ? `Add ${tasks} task${tasks === 1 ? "" : "s"} to Plan` : "Nothing to add";
  };

  const refresh = async () => {
    const mine = ++seq;
    plan = null;
    addBtn.disabled = true;
    if (!chosen().length) {
      clear(preview);
      preview.append(h("p", { class: "muted small" }, "Tick at least one document."));
      return;
    }
    try {
      const p = await api.post<Plan>("/api/reading-plan/preview", body());
      if (mine !== seq) return;
      plan = p;
      drawPlan(p);
    } catch (e) {
      if (mine !== seq) return;
      clear(preview);
      preview.append(h("p", { class: "rp-warn" }, (e as Error).message));
    }
  };
  const debounced = debounce(() => void refresh(), 250);
  /** Something in the form changed: the plan on screen is no longer the one Add would add, until the new preview. */
  const later = () => {
    plan = null;
    addBtn.disabled = true;
    debounced();
  };
  /** The list changed. `mine`: you changed it yourself, so the order is no longer only the model's (no AI label).
   *  `focusKey`: the control to give the focus back to after the list is drawn again. */
  const changed = (mine: boolean, focusKey?: string) => {
    if (mine && fromAi) {
      fromAi = "";
      clear(used);
      used.append("You changed the order or the levels, so the tasks will not say that the model suggested them.");
    }
    drawList();
    if (focusKey) list.querySelector<HTMLElement>(`[data-k="${focusKey}"]`)?.focus();
    later();
  };

  const addBtn: HTMLButtonElement = h("button", { type: "button", class: "btn primary", disabled: true, onclick: async () => {
    if (!plan) return;
    addBtn.disabled = true; // one press, one plan
    try {
      const res = await api.post<{ batch: string; added: number }>("/api/reading-plan/apply", { ...body(), expect: plan.key });
      onAdded();
      close();
      toast(`Added ${res.added} reading task${res.added === 1 ? "" : "s"} to Plan, each on its day.`, "ok", 8000, { label: "Undo", run: () => void takeBack(res.batch) });
    } catch (e) {
      toast((e as Error).message, "error");
      void refresh(); // show the plan as it is now (it may have changed since it was drawn)
    }
  } }, "Add to Plan");

  const takeBack = async (batch: string) => {
    try {
      const u = await api.post<{ removed: number; kept: number }>(`/api/reading-plan/${batch}/undo`);
      onAdded();
      toast(`Took back ${u.removed} task${u.removed === 1 ? "" : "s"}.${u.kept ? ` ${u.kept} you already worked on stay${u.kept === 1 ? "s" : ""}.` : ""}`, "ok", 5000);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  // ---------------------------------------------------------------- the model's suggestion
  const useSuggestion = (s: Suggestion) => {
    const before = { rows: rows.map((r) => ({ ...r })), fromAi };
    const byId = new Map(rows.map((r) => [r.doc.id, r]));
    const picked = s.order.map((p) => byId.get(p.document_id)).filter((r): r is (typeof rows)[number] => !!r);
    for (const p of s.order) {
      const r = byId.get(p.document_id);
      if (r) {
        r.on = !p.nothing_left;
        if (p.placed) r.level = p.level;
      }
    }
    rows = [...picked, ...rows.filter((r) => !picked.includes(r))];
    fromAi = s.id;
    changed(false);
    // the Undo stays in the dialog (a toast would cover the Add button)
    clear(used);
    used.append("The order and levels are filled in from the suggestion. Change anything you like. ",
      h("button", { type: "button", class: "link small", onclick: () => {
        rows = before.rows;
        fromAi = before.fromAi;
        clear(used);
        used.append("Back to your own order.");
        changed(false);
      } }, "Undo"));
  };
  const used = h("p", { class: "muted small", "aria-live": "polite" });

  const drawSuggestion = (s: Suggestion) => {
    clear(aiOut);
    const parts: string[] = [];
    if (s.left_out) parts.push(`${s.left_out} part${s.left_out === 1 ? " was" : "s were"} not sent: too much to fit.`);
    if (s.cut) parts.push("Some openings were shortened to fit.");
    aiOut.append(h("div", { class: "ai-text" },
      h("div", { class: "ai-text-label" }, `Suggested by the AI model (${s.provider === "local" ? "on this computer" : s.provider}). ${STATUS[s.status]}`),
      whyLink(s.id),
      parts.length ? h("p", { class: "muted small" }, parts.join(" ")) : null,
      h("ol", { class: "study-items" }, s.order.map((p) => h("li", { class: p.placed ? "" : "unchecked" },
        h("p", null, h("strong", null, p.title), p.placed ? h("span", { class: "tchip quiet", title: "The model's estimate of how slow it reads" }, p.level_from_model ? `${LEVEL_LABEL[p.level]} (its estimate)` : "level not given") : null),
        p.nothing_left ? h("p", { class: "muted small" }, "Nothing left to read.") : !p.placed ? h("p", { class: "muted small" }, "Not placed by the model: it follows in your order.") : null,
        p.reason ? h("p", null, p.reason) : null,
        p.reason ? (p.verified && p.quote ? h("div", { class: "resume-quote" }, `✓ “${p.quote}”`) : h("div", { class: "resume-quote unproven" }, "The model's guess: no passage of the document behind it.")) : null))),
      s.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", s.links.join(" · ")) : null,
      s.warning ? h("div", { class: "ai-text-links" }, s.warning) : null,
      h("div", { class: "row end" },
        h("button", { type: "button", class: "link small", onclick: (e: Event) => ((e.currentTarget as HTMLButtonElement).disabled = true, void suggest(true)) }, "Ask again"),
        h("button", { type: "button", class: "btn", onclick: () => useSuggestion(s) }, "Use this order"))));
  };

  let askSeq = 0;
  const suggest = async (fresh = false) => {
    const ids = chosen().map((r) => r.doc.id);
    if (ids.length < 2) return toast("Tick at least two documents: one has no order to suggest.", "info");
    const mine = ++askSeq; // an older, slower answer never replaces a newer one
    suggestBtn.disabled = true;
    clear(aiOut);
    aiOut.append(h("p", { class: "muted small", role: "status" }, "Asking the model…"));
    try {
      const res = await api.post<{ result: Suggestion }>("/api/reading-plan/suggest", { document_ids: ids, goal: goal.value.trim(), fresh });
      if (mine === askSeq) drawSuggestion(res.result);
    } catch (e) {
      if (mine !== askSeq) return;
      clear(aiOut);
      aiOut.append(h("p", { class: "muted small" }, `No suggestion: ${(e as Error).message}`));
    } finally {
      if (mine === askSeq) suggestBtn.disabled = false;
    }
  };
  const suggestBtn: HTMLButtonElement = h("button", { type: "button", class: "btn", onclick: () => void suggest() }, "Suggest an order with AI");

  const daysOff = h("div", { class: "seg", role: "group", "aria-label": "Days without reading" }, DAY_NAMES.map((name, i) => {
    const b = h("button", { type: "button", "aria-pressed": "false", title: `No reading on ${name}`, onclick: () => {
      if (off.has(i)) off.delete(i);
      else if (off.size < 6) off.add(i);
      else return toast("Leave at least one day of the week for reading.", "info");
      b.classList.toggle("on", off.has(i));
      b.setAttribute("aria-pressed", String(off.has(i)));
      later();
    } }, name);
    return b;
  }));
  for (const el of [deadline, perDay]) el.addEventListener("input", later);

  const last = start.last_batch;
  const lastBox = last
    ? h("p", { class: "muted small" }, `Your last reading plan still has ${last.open} open task${last.open === 1 ? "" : "s"} in Plan; they count against your days. `,
        h("button", { type: "button", class: "link small", onclick: async (e: Event) => {
          (e.currentTarget as HTMLButtonElement).disabled = true;
          await takeBack(last.id);
          void refresh();
        } }, "Take that plan back"))
    : null;

  const aiBox = aiIsOn()
    ? h("div", { class: "stack" },
        h("div", { class: "row" }, suggestBtn,
          h("span", { class: "muted small" }, "The model reads each ticked document's size, section titles and opening, never the whole text. It only suggests; code makes the schedule.")),
        aiOut, used)
    : h("p", { class: "muted small" }, "With AI switched on in Settings, a model can also suggest the order and how hard each document is.");

  drawList();
  void refresh();
  // a suggestion is for the documents that were ticked when it was asked for: ticking others hides it
  list.addEventListener("change", (e) => {
    if ((e.target as HTMLInputElement).type === "checkbox") clear(aiOut);
  });
  return modal("Plan my reading", h("div", { class: "stack" },
    h("p", { class: "muted small" }, `Tick what to read and put it in order. Readhold sizes what is left at your pace (${start.wpm} words a minute, from Settings) and spreads it over your days.`),
    list,
    h("div", { class: "grid2" },
      h("label", { class: "field" }, h("span", null, "Finish by (that day included)"), deadline),
      h("label", { class: "field" }, h("span", null, "Minutes a day for reading"), perDay)),
    h("div", { class: "field" }, h("span", null, "Days without reading"), daysOff),
    h("label", { class: "field" }, h("span", null, "What it is for"), goal),
    aiBox,
    lastBox,
    h("h3", null, "Your plan"),
    preview,
    h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close"), addBtn)), { wide: true, onOpen: (m) => (handle = m) });
}
