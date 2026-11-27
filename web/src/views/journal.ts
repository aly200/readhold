// Journal: one page a day, already started for you.
// - Inner weather instead of a mood score; the last six weeks show as a weather ribbon.
// - "Your day so far": what you did in Readhold today, drafted from your sessions, steps and habits,
//   so you write about how it felt rather than listing what happened.
// - A deck of prompts to draw from, a 5-minute free-write sprint, handwriting with the pen,
//   "On this day" memories, and letters to your future self, sealed until the day you pick.
import { notesHead } from "./libtabs";
import { api } from "../api";
import { InkPad, inkToolbar } from "../ink";
import { saveSettings, state } from "../state";
import { isDark } from "../themes";
import type { DaySummary } from "../types";
import { removeItem } from "../trash";
import { append, clear, confirmBox, debounce, fmtClock, h, type ModalHandle, modal, toast } from "../util";

type Weather = "" | "sunny" | "bright" | "cloudy" | "rainy" | "stormy";
interface Entry {
  id: string;
  day: string;
  weather: Weather;
  body: string;
  prompts: { q: string; a: string }[];
}
interface Page {
  day: string;
  entry: Entry | null;
  story: { time: string; kind: string; text: string; feel?: string }[];
  memories: { label: string; day: string; weather: Weather; body: string }[];
  recent: { day: string; weather: Weather; wrote: number }[];
  letters_due: { id: string; created_at: string; open_on: string }[];
  letters_sealed: number;
  prompts: Record<string, string[]>;
}

const WEATHER: { id: Exclude<Weather, "">; icon: string; label: string }[] = [
  { id: "sunny", icon: "☀", label: "Sunny" },
  { id: "bright", icon: "⛅", label: "Bright spells" },
  { id: "cloudy", icon: "☁", label: "Cloudy" },
  { id: "rainy", icon: "☂", label: "Rainy" },
  { id: "stormy", icon: "⚡", label: "Stormy" },
];
const CATEGORY: Record<string, string> = { gratitude: "Gratitude", learning: "Learning", win: "A win", worry: "Park a worry", kindness: "Kindness" };

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s: string) => new Date(`${s}T12:00:00`);

export async function journalView(root: HTMLElement, dayParam?: string): Promise<() => void> {
  const today = iso(new Date());
  const day = dayParam && /^\d{4}-\d{2}-\d{2}$/.test(dayParam) && dayParam <= today ? dayParam : today;
  const pg = await api.get<Page>(`/api/journal/${day}`);
  const entry: Entry = pg.entry ?? { id: "", day, weather: "", body: "", prompts: [] };
  let ink: InkPad | null = null;
  let sprintTimer = 0;
  const page = h("section", { class: `journal ${state.settings.journal_blur ? "privacy" : ""}` });
  root.append(notesHead("journal"), page);
  const status = h("span", { class: "muted small journal-status", "aria-live": "polite" });

  let saving: Promise<void> = Promise.resolve(); // the save on its way, so a delete waits for it (and is not undone by it)
  const persist = debounce(() => {
    saving = (async () => {
      try {
        const saved = await api.put<Entry>(`/api/journal/${day}`, { weather: entry.weather, body: entry.body, prompts: entry.prompts });
        if (!entry.id && saved?.id) entry.id = saved.id;
        delPage.hidden = !entry.id; // the page exists now: it can be deleted
        status.textContent = "Saved";
        setTimeout(() => (status.textContent = ""), 1200);
      } catch (e) {
        status.textContent = `Not saved: ${(e as Error).message}`;
      }
    })();
  }, 700);
  const settle = async () => {
    persist.flush();
    await saving;
  };

  // ---------------------------------------------------------------- header: days and the weather ribbon
  const header = () => {
    const prev = new Date(parse(day).getTime() - 86_400_000);
    const next = new Date(parse(day).getTime() + 86_400_000);
    const nice = parse(day).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    const byDay = new Map(pg.recent.map((r) => [r.day, r]));
    const ribbon = h("div", { class: "weather-ribbon", "aria-label": "Your inner weather, last six weeks" });
    for (let i = 41; i >= 0; i--) {
      const d = iso(new Date(parse(day).getTime() - i * 86_400_000));
      const r = byDay.get(d);
      ribbon.append(h("a", { class: `wr-day ${r?.weather ? `w-${r.weather}` : r?.wrote ? "w-wrote" : ""} ${d === day ? "on" : ""}`, href: `#/journal/${d}`, title: `${d}${r?.weather ? ` · ${r.weather}` : ""}` }));
    }
    // what the day held in the rest of Readhold: tasks, focus, routines
    const dayLine = h("span", { class: "muted small journal-dayline" });
    void api.get<DaySummary>(`/api/day/${day}`).then((d) => {
      const bits = [d.tasks_done.length ? `${d.tasks_done.length} task${d.tasks_done.length === 1 ? "" : "s"} done` : "", d.focus_min ? `${d.focus_min} min focused` : "", d.routine_steps ? `${d.routine_steps} routine step${d.routine_steps === 1 ? "" : "s"}` : ""].filter(Boolean);
      dayLine.textContent = bits.join(" · ");
      if (d.tasks_done.length) dayLine.title = d.tasks_done.join("\n");
    }, () => undefined);
    return h(
      "header",
      { class: "journal-head" },
      h("div", { class: "journal-nav" },
        h("a", { class: "btn small ghost", href: `#/journal/${iso(prev)}`, "aria-label": "Previous day" }, "‹"),
        h("h1", null, day === today ? "Today" : nice.split(",")[0], h("span", { class: "muted journal-date" }, ` ${nice}`)),
        day < today ? h("a", { class: "btn small ghost", href: `#/journal/${iso(next)}`, "aria-label": "Next day" }, "›") : null,
        day !== today ? h("a", { class: "btn small", href: "#/journal" }, "Back to today") : null,
        h("a", { class: "btn small ghost", href: `#/notes/${day}`, title: "The note of this day, on the Notes page" }, "📝 Day's note"),
        dayLine,
        h("label", { class: "toggle journal-blur", title: "Blurs your writing until you point at it" },
          h("input", { type: "checkbox", checked: Boolean(state.settings.journal_blur), onchange: async (e: Event) => {
            const on = (e.target as HTMLInputElement).checked;
            await saveSettings({ journal_blur: on });
            page.classList.toggle("privacy", on);
          } }), " Privacy blur")),
      ribbon,
    );
  };

  // ---------------------------------------------------------------- the page
  const weatherPicker = () =>
    h("div", { class: "weather-pick", role: "radiogroup", "aria-label": "Inner weather" },
      h("span", { class: "kicker" }, "Inner weather"),
      WEATHER.map((w) => h("button", {
        class: `weather w-${w.id} ${entry.weather === w.id ? "on" : ""}`, role: "radio", "aria-checked": String(entry.weather === w.id), title: w.label,
        onclick: () => {
          entry.weather = entry.weather === w.id ? "" : w.id;
          persist();
          renderLeft();
        },
      }, h("span", { class: "wi", "aria-hidden": "true" }, w.icon), h("span", null, w.label))));

  const promptDeck = () => {
    const cats = Object.keys(pg.prompts);
    let ci = Math.floor(Math.random() * cats.length);
    let qi = Math.floor(Math.random() * pg.prompts[cats[ci]].length);
    const cat = h("span", { class: "badge" });
    const q = h("p", { class: "prompt-q" });
    const show = () => {
      cat.textContent = CATEGORY[cats[ci]] ?? cats[ci];
      q.textContent = pg.prompts[cats[ci]][qi];
    };
    show();
    return h("div", { class: "prompt-card" },
      h("div", { class: "row" }, cat, h("span", { class: "muted small" }, "Draw a prompt when the page feels blank")),
      q,
      h("div", { class: "row" },
        h("button", { class: "btn small", onclick: () => {
          ci = (ci + 1 + Math.floor(Math.random() * (cats.length - 1))) % cats.length;
          qi = Math.floor(Math.random() * pg.prompts[cats[ci]].length);
          show();
        } }, "Another prompt"),
        h("button", { class: "btn small primary", onclick: () => {
          entry.prompts.push({ q: q.textContent ?? "", a: "" });
          persist();
          renderLeft();
          page.querySelector<HTMLTextAreaElement>(".prompt-answers li:last-child textarea")?.focus();
        } }, "Answer it")));
  };

  const left = h("div", { class: "journal-page" });
  // delete this day's page (its words, prompts and drawing); Undo brings them back, and the day can still be written again
  const delPage = h("button", { class: "btn small ghost journal-delete", hidden: !entry.id, onclick: () => void deletePage() }, "Delete this page");
  const deletePage = async () => {
    if (!(await confirmBox("Delete this day's page?", "Its words, prompts and drawing leave the journal. You can undo it right after, and you can still write this day again.", "Delete"))) return;
    await settle(); // the last keystrokes are saved first, so they cannot bring the page back after it is deleted
    if (!entry.id) return;
    ink?.destroy(); // a stroke on its way is saved before the page goes
    ink = null;
    await removeItem("journal", entry.id, "Deleted this day's page.", {
      gone: () => {
        Object.assign(entry, { id: "", weather: "", body: "", prompts: [] });
        pg.recent = pg.recent.filter((r) => r.day !== day);
        redrawHead();
        renderLeft();
      },
      back: async (r) => {
        await settle();
        if (!r.entry || !page.isConnected) return;
        Object.assign(entry, { id: r.entry.id, weather: r.entry.weather as Weather, body: r.entry.body, prompts: r.entry.prompts });
        pg.recent = [...pg.recent.filter((x) => x.day !== day), { day, weather: entry.weather, wrote: entry.body ? 1 : 0 }];
        redrawHead();
        renderLeft();
      },
    });
  };
  const renderLeft = () => {
    ink?.destroy();
    ink = null;
    clear(left);
    const body = h("textarea", { class: "journal-body", placeholder: day === today ? "How was today, really? Start anywhere." : "Write about this day…", "aria-label": "Journal page" }, entry.body);
    body.addEventListener("input", () => {
      entry.body = body.value;
      persist();
    });
    const answers = h("ol", { class: "prompt-answers" }, entry.prompts.map((p, i) => {
      const a = h("textarea", { rows: 2, placeholder: "…", "aria-label": p.q }, p.a);
      a.addEventListener("input", () => {
        entry.prompts[i].a = a.value;
        persist();
      });
      return h("li", null, h("div", { class: "prompt-q small" }, p.q, h("button", { class: "link small", "aria-label": "Remove prompt", onclick: () => {
        entry.prompts.splice(i, 1);
        persist();
        renderLeft();
      } }, " ✕")), a);
    }));
    const handHost = h("div", { class: "journal-ink" });
    const handWrap = h("details", { class: "journal-hand" }, h("summary", null, "Write or draw by hand"), handHost);
    handWrap.addEventListener("toggle", () => {
      if (handWrap.open && !ink) {
        ink = new InkPad(handHost, { owner: `journal/${day}`, adaptToDark: isDark });
        void ink.load();
        handWrap.insertBefore(inkToolbar(ink), handHost);
      }
    });
    delPage.hidden = !entry.id;
    append(left, [weatherPicker(), body, entry.prompts.length ? answers : null, promptDeck(), handWrap, h("div", { class: "row journal-foot" }, status, delPage)]);
  };

  // ---------------------------------------------------------------- the side: day story, memories, letters
  const right = h("aside", { class: "journal-side" });
  const renderRight = () => {
    clear(right);
    const feelMark: Record<string, string> = { energized: "↑", drained: "↓", neutral: "·" };
    append(right, [
      h("div", { class: "j-card" },
        h("div", { class: "kicker" }, day === today ? "Your day so far" : "That day in Readhold"),
        pg.story.length
          ? h("ol", { class: "story" }, pg.story.map((s) => h("li", { class: `story-${s.kind}` }, h("span", { class: "story-time" }, s.time), h("span", null, s.text, s.feel ? h("span", { class: "muted", title: s.feel }, ` ${feelMark[s.feel] ?? ""}`) : null))))
          : h("p", { class: "muted small" }, "Nothing recorded yet. That's fine — the page is yours either way.")),
      day === today ? h("div", { class: "j-card" }, h("div", { class: "kicker" }, "Free-write sprint"), h("p", { class: "muted small" }, "Five minutes, no stopping, no editing. The side panel hides; just keep the pen moving."), h("button", { class: "btn small", onclick: sprint }, "Start 5 minutes")) : null,
      pg.memories.length
        ? h("div", { class: "j-card" }, h("div", { class: "kicker" }, "On this day"), pg.memories.map((m) => h("a", { class: "memory", href: `#/journal/${m.day}` }, h("strong", null, m.label), m.weather ? h("span", { class: `wi-inline w-${m.weather}` }, ` ${WEATHER.find((w) => w.id === m.weather)?.icon ?? ""}`) : null, h("p", null, m.body || "(no words that day)"))))
        : null,
      lettersCard(),
    ]);
  };

  const lettersCard = () =>
    h("div", { class: "j-card letters" },
      h("div", { class: "kicker" }, "Letters to future you"),
      pg.letters_due.map((l) => h("button", { class: "envelope", onclick: () => openLetter(l.id) }, h("span", { class: "seal", "aria-hidden": "true" }, "✉"), h("span", null, h("strong", null, "A letter from past you"), h("span", { class: "muted small" }, ` · written ${new Date(l.created_at).toLocaleDateString()}`)))),
      pg.letters_sealed ? h("p", { class: "muted small" }, `${pg.letters_sealed} sealed letter${pg.letters_sealed > 1 ? "s" : ""} waiting for their day.`) : null,
      h("button", { class: "btn small", onclick: writeLetter }, "Write one"),
      allLetters());

  // every letter you wrote: read an opened one again, or delete one (a sealed one stays sealed: only its dates show)
  let lettersOpen = false;
  const allLetters = () => {
    const list = h("div", { class: "letters-all-list" }, h("p", { class: "muted small" }, "Loading…"));
    const box = h("details", { class: "letters-all", open: lettersOpen }, h("summary", null, "Your letters"), list);
    const load = async () => {
      const ls = await api.get<{ opened: { id: string; body: string; created_at: string; opened_at: string }[]; sealed: { id: string; open_on: string; created_at: string; ready: boolean }[] }>("/api/letters");
      clear(list);
      const date = (s: string) => new Date(s.length === 10 ? `${s}T12:00:00` : s).toLocaleDateString(undefined, { dateStyle: "medium" });
      if (!ls.opened.length && !ls.sealed.length) list.append(h("p", { class: "muted small" }, "No letters yet."));
      list.append(h("ul", { class: "letters-rows" },
        ls.sealed.map((l) => h("li", null, h("span", null, l.ready ? "Ready to open" : `Sealed until ${date(l.open_on)}`, h("span", { class: "muted small" }, ` · written ${date(l.created_at)}`)),
          h("button", { class: "btn small ghost", "aria-label": "Delete this sealed letter", onclick: () => void deleteLetter(l.id, true) }, "✕"))),
        ls.opened.map((l) => h("li", null, h("button", { class: "link", onclick: () => void showLetter(l.id, l.body, l.created_at) }, `Opened ${date(l.opened_at)}`), h("span", { class: "muted small" }, ` · written ${date(l.created_at)}`),
          h("button", { class: "btn small ghost", "aria-label": "Delete this letter", onclick: () => void deleteLetter(l.id, false) }, "✕")))));
    };
    const show = () => void load().catch((e: Error) => (clear(list), list.append(h("p", { class: "muted small" }, `Not available: ${e.message}`))));
    box.addEventListener("toggle", () => {
      if (box.open && !lettersOpen) show();
      lettersOpen = box.open;
    });
    if (lettersOpen) show(); // drawn again after a delete: the list stays open and fresh
    return box;
  };
  const refreshLetters = async () => {
    const fresh = await api.get<Page>(`/api/journal/${day}`);
    pg.letters_due = fresh.letters_due;
    pg.letters_sealed = fresh.letters_sealed;
    if (page.isConnected) renderRight();
  };
  const deleteLetter = async (lid: string, sealed: boolean, close?: () => void): Promise<void> => {
    if (sealed && !(await confirmBox("Delete this sealed letter?", "You have not read it yet. It leaves the journal without being opened. You can undo it right after.", "Delete"))) return;
    if (await removeItem("letter", lid, "Deleted the letter.", { gone: () => void refreshLetters(), back: () => void refreshLetters() })) close?.();
  };

  const showLetter = async (lid: string, body: string, createdAt: string) => {
    let hm: ModalHandle;
    await modal("A letter from past you", h("div", { class: "stack" }, h("p", { class: "muted small" }, `Written ${new Date(createdAt).toLocaleDateString(undefined, { dateStyle: "long" })}`), h("div", { class: "letter-body" }, body.split("\n").map((p) => h("p", null, p))),
      h("div", { class: "row end" }, h("button", { class: "ghost", onclick: () => void deleteLetter(lid, false, () => hm.close(null)) }, "Delete this letter"), h("button", { class: "primary", autofocus: true, onclick: () => hm.close(null) }, "Close"))), { wide: true, onOpen: (m) => (hm = m) }); // the focus is on Close, never on Delete
  };

  const openLetter = async (lid: string) => {
    const l = await api.post<{ body: string; created_at: string }>(`/api/letters/${lid}/open`);
    pg.letters_due = pg.letters_due.filter((x) => x.id !== lid);
    renderRight();
    await showLetter(lid, l.body, l.created_at);
  };

  const writeLetter = async () => {
    const body = h("textarea", { rows: 9, autofocus: true, placeholder: "Dear future me, …" });
    const when = h("select", { "aria-label": "Open on" }, [["7", "In a week"], ["30", "In a month"], ["90", "In three months"], ["182", "In six months"], ["365", "In a year"]].map(([v, l]) => h("option", { value: v }, l)));
    when.value = "30";
    const err = h("p", { class: "error small", hidden: true });
    let hm: ModalHandle;
    const ok = await modal("A letter to future you", h("div", { class: "stack" },
      h("p", { class: "muted small" }, "It stays sealed until the day you pick, then waits for you here and on Today. What do you hope will be true? What do you want to remember about now?"),
      body, err, h("label", { class: "field" }, h("span", null, "Open"), when),
      h("div", { class: "row end" }, h("button", { onclick: () => hm.close(null) }, "Cancel"), h("button", { class: "primary", onclick: () => {
        if (!body.value.trim()) {
          err.textContent = "Write a few lines first.";
          err.hidden = false;
          return;
        }
        hm.close("ok");
      } }, "Seal it"))), { wide: true, onOpen: (m) => (hm = m) });
    if (ok !== "ok") return;
    const openOn = iso(new Date(Date.now() + Number(when.value) * 86_400_000));
    await api.post("/api/letters", { body: body.value.trim(), open_on: openOn });
    pg.letters_sealed++;
    renderRight();
    toast(`Sealed until ${parse(openOn).toLocaleDateString(undefined, { dateStyle: "medium" })}.`, "ok");
  };

  const sprint = () => {
    const end = Date.now() + 5 * 60_000;
    page.classList.add("sprint");
    const clock = h("div", { class: "sprint-clock", "aria-live": "off" });
    left.prepend(clock);
    left.querySelector<HTMLTextAreaElement>(".journal-body")?.focus();
    const stop = (msg?: string) => {
      clearInterval(sprintTimer);
      sprintTimer = 0;
      page.classList.remove("sprint");
      clock.remove();
      if (msg) toast(msg, "ok", 4000);
    };
    clock.append(h("span", null), h("button", { class: "btn small ghost", onclick: () => stop() }, "Stop"));
    const tick = () => {
      const left = end - Date.now();
      if (left <= 0) return stop("Five minutes of honest writing. That counts.");
      clock.firstElementChild!.textContent = fmtClock(left);
    };
    tick();
    sprintTimer = window.setInterval(tick, 500);
  };

  let head = header();
  const redrawHead = () => {
    const next = header();
    head.replaceWith(next);
    head = next;
  };
  page.append(head, h("div", { class: "journal-grid" }, left, right));
  renderLeft();
  renderRight();
  return () => {
    clearInterval(sprintTimer);
    ink?.destroy();
    persist.flush();
  };
}
