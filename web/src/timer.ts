// The calm timer: one clock for the whole app. It keeps running while you move between pages (a small
// floating timer shows it), survives a reload (the server keeps its state), and ends with a soft chime,
// never an alarm. Focus runs count as sessions on the server, so they show in Stamina.
import { ambience } from "./ambience";
import { api } from "./api";
import { state } from "./state";
import type { LinkType, TimerKind, TimerRun, TimerToday, Todo } from "./types";
import { fmtClock, h, toast } from "./util";

export interface TimerData {
  run: TimerRun | null;
  todos: Todo[];
  today: TimerToday;
}
export interface StartOpts {
  kind: TimerKind;
  minutes?: number;
  label?: string;
  todo_id?: string | null;
  link_type?: LinkType;
  link_id?: string;
}

type Listener = () => void;
const KIND_WORD: Record<TimerKind, string> = { focus: "Focus", break: "Break", stopwatch: "Stopwatch" };

/** Where a linked item opens. */
export function linkHref(type: LinkType, id: string): string | null {
  if (type === "lecture") return `#/lecture/${id}`;
  if (type === "document") return `#/read/${id}`;
  if (type === "step") return "#/home";
  if (type === "page") return `#/notes/${id}`;
  return null;
}

export const timer = {
  run: null as TimerRun | null,
  baseMs: 0, // elapsed time at baseAt
  baseAt: 0, // performance.now() when baseMs was true
  over: false, // a countdown has reached zero (and chimed)
  listeners: new Set<Listener>(),
  tickId: 0,
  beatId: 0,
  loaded: false, // the server's timer state has arrived at least once

  elapsed(): number {
    if (!this.run) return 0;
    return this.baseMs + (this.run.running ? performance.now() - this.baseAt : 0);
  },
  /** Milliseconds left on a countdown (negative once over); for the stopwatch, the time so far. */
  shown(): number {
    if (!this.run) return 0;
    return this.run.planned_ms ? this.run.planned_ms - this.elapsed() : this.elapsed();
  },
  progress(): number {
    if (!this.run || !this.run.planned_ms) return 0;
    return Math.min(1, this.elapsed() / this.run.planned_ms);
  },

  on(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  },
  emit(): void {
    this.listeners.forEach((fn) => {
      try {
        fn();
      } catch (e) {
        console.warn("timer listener", e);
      }
    });
  },

  set(run: TimerRun | null): void {
    this.run = run;
    this.loaded = true;
    this.baseMs = run?.elapsed_now_ms ?? 0;
    this.baseAt = performance.now();
    this.over = !!run && run.planned_ms > 0 && this.baseMs >= run.planned_ms;
    this.schedule();
    ambience.update({ mode: !run ? "idle" : run.kind === "break" ? "break" : run.running ? "reading" : "idle" });
    this.emit();
  },

  async load(): Promise<TimerData> {
    const t = await api.get<TimerData>("/api/timer");
    this.set(t.run);
    if (t.run?.was_quiet) toast("Your timer paused while Readhold was closed. Resume when you're ready.", "info", 6000);
    return t;
  },

  async start(opts: StartOpts): Promise<void> {
    const run = await api.post<TimerRun>("/api/timer/start", { minutes: 25, ...opts });
    this.set(run);
  },
  async pause(): Promise<void> {
    if (!this.run?.running) return;
    this.set(await api.post<TimerRun>(`/api/timer/${this.run.id}/pause`, { elapsed_ms: Math.round(this.elapsed()) }));
  },
  async resume(): Promise<void> {
    if (!this.run || this.run.running) return;
    this.set(await api.post<TimerRun>(`/api/timer/${this.run.id}/resume`, {}));
  },
  async toggle(): Promise<void> {
    return this.run?.running ? this.pause() : this.resume();
  },
  async extend(minutes = 5): Promise<void> {
    if (!this.run || !this.run.planned_ms) return;
    const elapsed = this.elapsed();
    const run = await api.post<TimerRun>(`/api/timer/${this.run.id}/extend?minutes=${minutes}`, {});
    this.set({ ...run, elapsed_now_ms: Math.round(elapsed) });
  },
  async finish(status: "done" | "stopped", extra: { feel?: string; output?: string } = {}): Promise<{ today: TimerToday; todos: Todo[] } | null> {
    if (!this.run) return null;
    const res = await api.post<{ today: TimerToday; todos: Todo[] }>(`/api/timer/${this.run.id}/finish`, { elapsed_ms: Math.round(this.elapsed()), status, ...extra });
    this.set(null);
    return res;
  },

  /** One tick for the whole app while a timer runs (2 per second), and a heartbeat every 15 seconds. */
  schedule(): void {
    const running = !!this.run?.running;
    if (running && !this.tickId) {
      this.tickId = window.setInterval(() => {
        if (this.run?.planned_ms && !this.over && this.elapsed() >= this.run.planned_ms) {
          this.over = true;
          chime();
          toast(this.run.kind === "break" ? "Break's over. Come back gently when you're ready." : "Time's up. Finish your thought, then press Done.", "ok", 8000);
        }
        this.emit();
      }, 500);
      this.beatId = window.setInterval(() => this.beat(), 15_000);
    } else if (!running && this.tickId) {
      clearInterval(this.tickId);
      clearInterval(this.beatId);
      this.tickId = 0;
      this.beatId = 0;
    }
  },
  beat(keepalive = false): void {
    if (!this.run?.running) return;
    const body = JSON.stringify({ elapsed_ms: Math.round(this.elapsed()) });
    fetch(`/api/timer/${this.run.id}/beat`, { method: "POST", keepalive, credentials: "same-origin", headers: { "Content-Type": "application/json" }, body }).catch(() => undefined);
  },
};

// ------------------------------------------------------------------ a soft chime (generated, no audio file)
let chimeCtx: AudioContext | null = null;
export function chime(): void {
  if (!state.settings.timer_sound) return;
  try {
    chimeCtx ??= new AudioContext();
    const ctx = chimeCtx;
    void ctx.resume();
    const vol = 0.07 * Math.max(0.3, Math.min(1, Number(state.settings.sound_volume ?? 0.6) || 0.6));
    [[659.25, 0], [987.77, 0.9]].forEach(([f, at]) => {
      const t0 = ctx.currentTime + at;
      for (const [mult, level] of [[1, 1], [2.76, 0.25]]) {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = "sine";
        o.frequency.value = f * mult;
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(vol * level, t0 + 0.03);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 2.6);
        o.connect(g).connect(ctx.destination);
        o.start(t0);
        o.stop(t0 + 2.7);
      }
    });
  } catch {
    /* no audio: the toast and the ring still say it */
  }
}

// ------------------------------------------------------------------ the small floating timer on other pages
export function mountMiniTimer(): void {
  const time = h("span", { class: "mini-time" });
  const label = h("span", { class: "mini-label" });
  const toggle = h("button", { class: "mini-btn", type: "button", onclick: () => void timer.toggle() });
  const pill = h("div", { class: "mini-timer", role: "timer", "aria-live": "off", hidden: true },
    h("span", { class: "mini-dot", "aria-hidden": "true" }),
    h("a", { class: "mini-open", href: "#/timer", title: "Open the timer" }, time, label),
    toggle);
  // the corner dock: this small timer and a pinned peek share the bottom-left corner
  const dock = document.getElementById("corner-dock") ?? document.body.appendChild(h("div", { id: "corner-dock", class: "corner-dock" }));
  dock.append(pill);
  let lastTitle = "";
  const render = () => {
    const run = timer.run;
    const onTimerPage = location.hash.startsWith("#/timer");
    pill.hidden = !run || onTimerPage;
    const title = run ? `${timer.over && run.planned_ms ? "+" : ""}${fmtClock(Math.abs(timer.shown()))} · ${KIND_WORD[run.kind]} — Readhold` : "Readhold";
    if (title !== lastTitle) document.title = lastTitle = title;
    if (!run) return;
    pill.className = `mini-timer kind-${run.kind} ${run.running ? "" : "paused"} ${timer.over ? "over" : ""}`;
    time.textContent = `${timer.over && run.planned_ms ? "+" : ""}${fmtClock(Math.abs(timer.shown()))}`;
    label.textContent = run.label || KIND_WORD[run.kind];
    toggle.textContent = run.running ? "❚❚" : "▶";
    toggle.setAttribute("aria-label", run.running ? "Pause the timer" : "Resume the timer");
    toggle.title = run.running ? "Pause" : "Resume";
  };
  timer.on(render);
  window.addEventListener("hashchange", render);
  window.addEventListener("pagehide", () => timer.beat(true));
  render();
}

// ------------------------------------------------------------------ quick start from anywhere (e.g. a lecture)
/** A small menu under a button: start a focus timer tied to what you're working on, or open the timer. */
export function timerMenu(anchor: HTMLElement, opts: { label: string; link_type: LinkType; link_id: string }): void {
  document.querySelector(".timer-menu")?.remove();
  const close = () => {
    menu.remove();
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", esc, true);
  };
  const outside = (e: Event) => !menu.contains(e.target as Node) && e.target !== anchor && close();
  const esc = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), close());
  const go = (minutes: number) => async () => {
    close();
    await timer.start({ kind: "focus", minutes, label: opts.label, link_type: opts.link_type, link_id: opts.link_id });
    toast(`${minutes}-minute focus started. The timer is in the corner.`, "ok", 2500);
  };
  const run = timer.run;
  const menu = h("div", { class: "timer-menu", role: "menu" },
    run ? h("div", { class: "timer-menu-now" }, `${run.label || KIND_WORD[run.kind]} · ${fmtClock(Math.abs(timer.shown()))}`) : null,
    h("div", { class: "timer-menu-row" }, [15, 25, 45].map((m) => h("button", { class: "btn small", role: "menuitem", onclick: go(m) }, `Focus ${m} min`))),
    h("a", { class: "timer-menu-open", href: "#/timer", role: "menuitem", onclick: close }, "Open the timer and to-do list →"));
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.top = `${Math.round(r.bottom + 6)}px`;
  menu.style.left = `${Math.round(Math.max(8, Math.min(window.innerWidth - menu.offsetWidth - 8, r.right - menu.offsetWidth)))}px`;
  setTimeout(() => {
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", esc, true);
  });
}
