// Readhold front end entry: hash router + nav. No remote code, no eval.
import { ambience } from "./ambience";
import { api } from "./api";
import { loadState, state } from "./state";
import { applyTheme, watchSystemTheme } from "./themes";
import { applyComfort, comfortFor } from "./state";
import { clear, flushPending, h, toast } from "./util";
import { focusView } from "./views/focus";
import { hubView } from "./views/hub";
import { journalView } from "./views/journal";
import { lectureView } from "./views/lecture";
import { lecturesView } from "./views/lectures";
import { mapView } from "./views/map";
import { notesView } from "./views/notes";
import { openPalette } from "./palette";
import { openCapture } from "./capture";
import { thinkView } from "./views/think";
import { planView } from "./views/plan";
import { practiceView } from "./views/practice";
import { questView } from "./views/quest";
import { todayView } from "./views/today";
import { libraryView } from "./views/library";
import { Reader } from "./views/reader";
import { reviewView } from "./views/review";
import { summaryView } from "./views/summary";
import { timerView } from "./views/timer";
import { mountMiniTimer, timer } from "./timer";
import { mountPeek } from "./peek";
import { mountReminders } from "./reminders";
import { glossaryView, ideasView, settingsView, statsView, structureView } from "./views/misc";
import { aiChip } from "./views/ai-settings";

let cleanup: (() => void) | void;
const app = document.getElementById("app")!;

/** what each page is for, in plain words (shown when you point at its name) */
const HINT: Record<string, string> = {
  hub: "Every feature on one page, and what is next",
  plan: "The tasks of your days, your routines, and Today: your main goal and the next step",
  timer: "A focus timer beside a to-do list",
  library: "Everything you learn from: lectures and notebooks, documents, goals, review cards and the glossary",
  notes: "Your notes, the journal, the idea inbox and Think",
  stats: "Stamina: how long you focused, and the weekly review",
  settings: "Themes, reading comfort, the timer, AI and your data",
};
/** pages that live inside another menu entry */
const PART_OF: Record<string, string> = { home: "plan", quest: "library", map: "library", lectures: "library", review: "library", glossary: "library", journal: "notes", ideas: "notes", think: "notes", practice: "library", summary: "library", structure: "library" };

/** Hide or show the side menu: the page takes its room. Saved as a setting, so it holds after a restart. */
function setNavHidden(hidden: boolean): void {
  state.settings.nav_hidden = hidden;
  applyNavHidden();
  void api.put("/api/settings", { nav_hidden: hidden }).catch(() => undefined);
  const back = document.querySelector<HTMLElement>(hidden ? ".nav-show" : ".nav-hide");
  back?.focus(); // the keyboard stays where the button that moved it is
}

function applyNavHidden(): void {
  if (state.settings.nav_hidden) document.documentElement.dataset.nav = "hidden";
  else delete document.documentElement.dataset.nav;
}

/** The side menu, and the small Menu button that shows it again when it is hidden. */
function nav(active: string): HTMLElement[] {
  const link = (href: string, label: string, id: string) => h("a", { href, class: active === id ? "on" : "", "aria-current": active === id ? "page" : undefined, title: HINT[id] }, label);
  const group = (label: string, ...links: HTMLElement[]) => h("div", { class: "nav-group", role: "group", "aria-label": label }, h("span", { class: "nav-label", "aria-hidden": "true" }, label), links);
  const top = [
    h("div", { class: "nav-top" },
      h("a", { class: "brand", href: "#/hub", title: "Overview" }, h("img", { src: "/static/logo.svg", alt: "", width: 22, height: 22 }), "Readhold"),
      h("button", { class: "nav-hide", type: "button", title: "Hide the menu, to give the page the whole window (Ctrl+\\)", "aria-label": "Hide the menu (Ctrl+\\)", onclick: () => setNavHidden(true) }, "«")),
    h("button", { class: "nav-find", type: "button", title: "Find anything (Ctrl+K)", onclick: () => void openPalette() }, h("span", null, "Find…"), h("kbd", null, "Ctrl K")),
    h("button", { class: "nav-find nav-capture", type: "button", title: "Capture a thought (Ctrl+J)", onclick: () => void openCapture() }, h("span", null, "+ Capture"), h("kbd", null, "Ctrl J")),
    link("#/hub", "Overview", "hub"),
  ];
  const foot = [h("span", { class: "nav-gap", "aria-hidden": "true" }), aiChip(), link("#/settings", "Settings", "settings")];
  let bar: HTMLElement;
  if (state.settings.simple_mode) {
    // simple mode: the same pages, without the group names
    bar = h("nav", { class: "topnav is-simple", "aria-label": "Main" }, top,
      link("#/plan", "Plan", "plan"), link("#/timer", "Timer", "timer"), link("#/lectures", "Study", "library"), link("#/notes", "Notes", "notes"), link("#/stats", "Stamina", "stats"),
      foot);
  } else {
    bar = h("nav", { class: "topnav", "aria-label": "Main" }, top,
      group("Do", link("#/plan", "Plan", "plan"), link("#/timer", "Timer", "timer")),
      group("Learn", link("#/lectures", "Study", "library")),
      group("Reflect", link("#/notes", "Notes", "notes"), link("#/stats", "Stamina", "stats")),
      foot);
  }
  // the menu scrolls when the window is small: keep the current page in sight
  setTimeout(() => bar.querySelector("a.on")?.scrollIntoView({ inline: "center", block: "nearest" }), 0);
  const show = h("button", { class: "nav-show", type: "button", title: "Show the menu (Ctrl+\\)", "aria-label": "Show the menu (Ctrl+\\)", onclick: () => setNavHidden(false) }, "☰ Menu");
  return [bar, show];
}

let routeSeq = 0; // counts page changes, so a slow page knows it is no longer the current one
async function route(): Promise<void> {
  flushPending(); // unsaved debounced edits are written before the screen changes
  if (typeof cleanup === "function") cleanup();
  cleanup = undefined;
  const mine = ++routeSeq;
  /** a page that finished loading after a newer page change: its listeners and timers are released, not kept */
  const keep = (made: (() => void) | void): void => {
    if (mine === routeSeq) cleanup = made;
    else if (typeof made === "function") made();
  };
  clear(app);
  document.querySelectorAll(".peek-pop, .sel-bar, .modal-back").forEach((e) => e.remove());
  const [path, query] = (location.hash.slice(1) || "/hub").split("?"); // the app opens on Overview
  const params = new URLSearchParams(query ?? "");
  const [, view, id, extra] = path.split("/");
  applyComfort(comfortFor(""));
  ambience.update({ mode: view === "review" || view === "practice" ? "review" : "idle", session: 0 });
  try {
    if (view === "read" && id) {
      const reader = new Reader();
      keep(await reader.mount(app, id, params, () => mine === routeSeq));
      return;
    }
    if (view === "lecture" && id) {
      const main = h("div", { class: "lecture-root" });
      app.append(...nav("library"), main);
      keep(await lectureView(main, id));
      return;
    }
    if (view === "focus" && id) {
      const main = h("div", { class: "view focus-view" });
      app.append(main);
      keep(await focusView(main, id, params));
      return;
    }
    const main = h("div", { class: "view" });
    app.append(...nav(PART_OF[view] ?? (view || "hub")), main);
    if (view === "library") await libraryView(main);
    else if (view === "review") keep(await reviewView(main));
    else if (view === "summary" && id) await summaryView(main, id);
    else if (view === "structure" && id) await structureView(main, id);
    else if (view === "glossary") await glossaryView(main, params);
    else if (view === "ideas") await ideasView(main);
    else if (view === "stats") await statsView(main);
    else if (view === "settings") await settingsView(main, params);
    else if (view === "quest") await questView(main, id);
    else if (view === "map" && id) keep(await mapView(main, id));
    else if (view === "practice") keep(await practiceView(main));
    else if (view === "lectures") await lecturesView(main);
    else if (view === "timer") keep(await timerView(main));
    else if (view === "plan") keep(await planView(main, params));
    else if (view === "hub") keep(await hubView(main));
    else if (view === "think") keep(await thinkView(main, id, extra));
    else if (view === "notes") keep(await notesView(main, id));
    else if (view === "journal") keep(await journalView(main, id));
    else if (view === "home") await todayView(main);
    else keep(await hubView(main));
  } catch (e) {
    console.error(e);
    if (mine !== routeSeq) return; // the page that failed is no longer the one on screen
    app.append(h("div", { class: "view" }, h("p", { class: "import-warning" }, `Something went wrong: ${(e as Error).message}`), h("a", { href: "#/hub" }, "Go to Overview")));
  }
}

async function boot(): Promise<void> {
  try {
    await loadState();
  } catch (e) {
    app.append(h("p", { class: "import-warning" }, `Could not reach the Readhold server: ${(e as Error).message}. Start it with: uv run python -m readhold`));
    return;
  }
  applyTheme();
  applyNavHidden();
  watchSystemTheme();
  mountMiniTimer();
  mountPeek();
  mountReminders();
  if (!location.hash.startsWith("#/timer")) timer.load().catch(() => undefined); // a timer left running comes back
  api.get<{ reviews_today: number }>("/api/ambience").then((a) => ambience.update({ reviewed: a.reviews_today }), () => undefined);
  window.addEventListener("hashchange", route);
  // Ctrl+K: find anything, from anywhere
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      void openPalette();
    }
    // Ctrl+\: hide or show the side menu (pages that have it)
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key === "\\" && document.querySelector("#app > .topnav")) {
      e.preventDefault();
      setNavHidden(!state.settings.nav_hidden);
    }
    // Ctrl+J: capture a thought, from anywhere
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "j") {
      e.preventDefault();
      void openCapture();
    }
  });
  // a file dropped anywhere but a drop zone would make the window open it (a page with no CSP and no sandbox);
  // drop zones handle their own drops first, so this only stops the window's default
  const isFile = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  window.addEventListener("dragover", (e) => isFile(e) && e.preventDefault());
  window.addEventListener("drop", (e) => isFile(e) && e.preventDefault());
  window.addEventListener("pagehide", flushPending);
  window.addEventListener("beforeunload", flushPending);
  window.addEventListener("error", (e) => {
    // A harmless browser notice (layout settled one frame later), not a failure.
    if (/ResizeObserver loop/.test(e.message ?? "")) return;
    toast(`Error: ${e.message}`, "error");
  });
  window.addEventListener("unhandledrejection", (e) => toast(`Error: ${(e.reason as Error)?.message ?? e.reason}`, "error"));
  // Battery saver: theme motion pauses when hidden.
  document.addEventListener("visibilitychange", () => (document.documentElement.dataset.hidden = document.hidden ? "1" : ""));
  void state;
  await route();
}

boot();
