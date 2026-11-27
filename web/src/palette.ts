// Find anything (Ctrl+K, from anywhere): notes, tasks, documents, study files, quests, glossary terms and ideas,
// plus a few commands (go to a page, start a timer, add a task). Everything is local; nothing is fetched from outside.
// Results are drawn with text nodes only.
import { api } from "./api";
import { saveSettings, state } from "./state";
import { applyTheme, isDark } from "./themes";
import { timer } from "./timer";
import type { NotePage, NoteTitles, SearchHit } from "./types";
import { clear, debounce, h, type ModalHandle, modal, toast } from "./util";
import { parseQuick, ymd } from "./views/plan";

interface Row {
  icon: string;
  label: string;
  hint: string;
  go: () => Promise<void> | void;
}

const KIND: Record<SearchHit["kind"], { icon: string; hint: string; href: (hit: SearchHit) => string }> = {
  note: { icon: "📝", hint: "note", href: (x) => `#/notes/${x.id}` },
  task: { icon: "☑️", hint: "task", href: () => "#/plan" },
  document: { icon: "📄", hint: "document", href: (x) => `#/read/${x.id}` },
  passage: { icon: "🔎", hint: "inside", href: (x) => `#/read/${x.document_id}?s=${x.sentence}` },
  lecture: { icon: "📒", hint: "lecture", href: (x) => `#/lecture/${x.id}` },
  quest: { icon: "🧭", hint: "goal", href: (x) => `#/quest/${x.id}` },
  term: { icon: "🔤", hint: "glossary", href: (x) => `#/glossary?concept=${encodeURIComponent(x.title)}` },
  idea: { icon: "💡", hint: "idea", href: () => "#/ideas" },
};

const go = (hash: string) => () => void (location.hash = hash);

function commands(): Row[] {
  const page = (label: string, hash: string): Row => ({ icon: "→", label: `Go to ${label}`, hint: "page", go: go(hash) });
  return [
    { icon: "🗂️", label: "Overview: every feature on one page", hint: "page", go: go("#/hub") },
    { icon: "✍️", label: "Capture a thought", hint: "Ctrl+J", go: () => void import("./capture").then((m) => m.openCapture()) },
    { icon: "🌱", label: "Think: today's ideas and suggestions", hint: "page", go: go("#/think") },
    { icon: "📝", label: "Today's note", hint: "daily note", go: go("#/notes/today") },
    { icon: "⏱️", label: "Start a 25-minute focus timer", hint: "command", go: async () => {
      await timer.start({ kind: "focus", minutes: 25 });
      toast("Timer started. It is in the corner.", "ok", 2500);
    } },
    { icon: "☕", label: "Take a 5-minute break", hint: "command", go: async () => {
      await timer.start({ kind: "break", minutes: 5 });
      toast("Break started.", "ok", 2500);
    } },
    { icon: "🗓️", label: "Plan: this week as a board", hint: "view", go: go("#/plan?view=week") },
    { icon: "🕸️", label: "Notes: the big map", hint: "view", go: go("#/notes/map") },
    { icon: "▦", label: "Notes: as a table", hint: "view", go: go("#/notes/table") },
    { icon: "🌗", label: isDark() ? "Switch to light" : "Switch to dark", hint: "command", go: async () => {
      await saveSettings({ dark: isDark() ? "light" : "dark" });
      applyTheme();
    } },
    page("Overview", "#/hub"), page("Today (in Plan)", "#/home"), page("Plan", "#/plan"), page("Timer", "#/timer"), page("Study", "#/lectures"), page("Lectures (in Study)", "#/lectures"), page("Goals (in Study)", "#/quest"),
    page("Documents (in Study)", "#/library"), page("Review (in Study)", "#/review"), page("Glossary (in Study)", "#/glossary"), page("Notes", "#/notes"),
    page("Journal (in Notes)", "#/journal"), page("Ideas (in Notes)", "#/ideas"), page("Think (in Notes)", "#/think"), page("Stamina", "#/stats"), page("Settings", "#/settings"),
  ];
}

export async function openPalette(): Promise<void> {
  if (document.querySelector(".modal-back")) return;
  let handle: ModalHandle;
  let sel = 0;
  let rows: Row[] = [];
  let hits: SearchHit[] = [];
  let asked = 0;
  let recent: NoteTitles["pages"] = [];
  const cmds = commands();
  const input = h("input", { type: "text", class: "find-input", placeholder: "Find a note, a task, words inside a document… or type what you want to do", "aria-label": "Find anything", autofocus: true });
  const list = h("ul", { class: "switch-list", role: "listbox" });

  const draw = () => {
    const raw = input.value.trim();
    const q = raw.toLowerCase();
    rows = [];
    if (!q) {
      rows.push(...cmds.slice(0, 7), ...recent.slice(0, 5).map((p) => ({ icon: "📝", label: p.title, hint: "recent note", go: go(`#/notes/${p.id}`) })));
    } else {
      rows.push(...hits.map((x) => ({ icon: KIND[x.kind].icon, label: x.title, hint: x.hint ? `${KIND[x.kind].hint} · ${x.hint}` : KIND[x.kind].hint, go: go(KIND[x.kind].href(x)) })));
      rows.push(...cmds.filter((c) => c.label.toLowerCase().includes(q)).slice(0, 5));
      const quick = parseQuick(raw, ymd(new Date()));
      if (quick.text) {
        rows.push({ icon: "＋", label: `Add task “${quick.text}”`, hint: quick.due ? `task · ${quick.due}` : "task · @tomorrow #area ~15 work here", go: async () => {
          await api.post("/api/todos", { text: quick.text, minutes: quick.minutes ?? 25, ...(quick.due ? { due: quick.due } : {}), ...(quick.repeat_rule ? { repeat_rule: quick.repeat_rule } : {}), ...(quick.at ? { at: quick.at } : {}), area: quick.area ?? "" });
          toast("Added to Plan.", "ok", 3000, { label: "Open Plan", run: go("#/plan") });
          if (location.hash.startsWith("#/plan")) window.dispatchEvent(new HashChangeEvent("hashchange"));
        } });
      }
      if (!hits.some((x) => x.kind === "note" && x.title.toLowerCase() === q)) {
        rows.push({ icon: "＋", label: `Create note “${raw}”`, hint: "new note", go: async () => {
          const p = await api.post<NotePage>("/api/pages/open", { title: raw });
          location.hash = `#/notes/${p.id}`;
        } });
      }
    }
    sel = Math.min(sel, Math.max(0, rows.length - 1));
    clear(list);
    rows.forEach((r, i) => list.append(h("li", { role: "option", "aria-selected": String(i === sel) },
      h("button", { type: "button", class: `switch-row ${i === sel ? "is-on" : ""}`, onclick: () => pick(i) },
        h("span", { class: "find-main" }, h("span", { class: "find-icon", "aria-hidden": "true" }, r.icon), h("span", { class: "find-label" }, r.label)),
        h("span", { class: "find-hint muted small" }, r.hint)))));
    list.querySelector(".switch-row.is-on")?.scrollIntoView({ block: "nearest" });
  };
  const pick = (i: number) => {
    const row = rows[i];
    if (!row) return;
    handle.close(null);
    void Promise.resolve(row.go()).catch((e: Error) => toast(e.message, "error"));
  };
  const ask = debounce(async () => {
    const q = input.value.trim();
    const mine = ++asked;
    if (!q) return;
    try {
      const got = await api.get<{ results: SearchHit[] }>(`/api/search?q=${encodeURIComponent(q)}`);
      if (mine !== asked) return; // a newer search is on its way
      hits = got.results;
      draw();
    } catch {
      /* the commands still work without the search */
    }
  }, 140);
  input.addEventListener("input", () => {
    sel = 0;
    if (!input.value.trim()) hits = [];
    draw();
    ask();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") (e.preventDefault(), (sel = Math.min(rows.length - 1, sel + 1)), draw());
    else if (e.key === "ArrowUp") (e.preventDefault(), (sel = Math.max(0, sel - 1)), draw());
    else if (e.key === "Enter") (e.preventDefault(), ask.flush(), pick(sel));
  });
  draw();
  api.get<NoteTitles>("/api/pages/titles").then((t) => {
    recent = t.pages;
    if (!input.value.trim()) draw();
  }, () => undefined);
  void state;
  await modal("Find anything", h("div", { class: "stack find" }, input, list, h("p", { class: "muted small find-tip" }, "↑ ↓ to move · Enter to open · Esc to close")), { onOpen: (m) => (handle = m) });
}
