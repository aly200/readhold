// Session tracking: focused time, longest unbroken run, distractions. Saved every 15 s and on end.
import { api, save } from "./api";
import type { Energy, SessionInfo } from "./types";

export class SessionTracker {
  focusedMs = 0;
  runMs = 0;
  longestRunMs = 0;
  distractions = 0;
  sentencesRead = 0;
  private lastActivity = performance.now();
  private lastTick = performance.now();
  private tickTimer = 0;
  private beatTimer = 0;
  private ended = false;

  constructor(
    public info: SessionInfo,
    private isPlaying: () => boolean,
    private onTick: (s: SessionTracker) => void,
  ) {
    this.tickTimer = window.setInterval(() => this.tick(), 1000);
    this.beatTimer = window.setInterval(() => this.flush(), 15000);
  }

  static async start(documentId: string, energy: Energy, timeBoxMin: number, question: string, isPlaying: () => boolean, onTick: (s: SessionTracker) => void, questId: string | null = null) {
    const info = await api.post<SessionInfo>("/api/sessions", { document_id: documentId, energy, time_box_min: timeBoxMin, question, quest_id: questId });
    return new SessionTracker(info, isPlaying, onTick);
  }

  get timeBoxMs(): number {
    return this.info.time_box_min * 60_000;
  }

  activity(): void {
    this.lastActivity = performance.now();
  }

  distracted(): void {
    this.distractions++;
    this.runMs = 0;
  }

  private tick(): void {
    const t = performance.now();
    const dt = Math.min(t - this.lastTick, 5000);
    this.lastTick = t;
    const present = document.visibilityState === "visible" && document.hasFocus();
    const engaged = this.isPlaying() || t - this.lastActivity < 60_000;
    if (present && engaged) {
      this.focusedMs += dt;
      this.runMs += dt;
      this.longestRunMs = Math.max(this.longestRunMs, this.runMs);
    } else if (!present) {
      this.runMs = 0;
    }
    this.onTick(this);
  }

  private payload(extra: Record<string, unknown> = {}) {
    return {
      focused_ms: Math.round(this.focusedMs),
      longest_run_ms: Math.round(this.longestRunMs),
      distractions: this.distractions,
      sentences_read: this.sentencesRead,
      ...extra,
    };
  }

  flush(): void {
    if (!this.ended) save("patch", `/api/sessions/${this.info.id}`, this.payload()).catch(() => undefined);
  }

  /** Synchronous-ish save for page unload. */
  flushOnUnload(): void {
    if (this.ended) return;
    fetch(`/api/sessions/${this.info.id}`, {
      method: "PATCH",
      keepalive: true,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(this.payload()),
    }).catch(() => undefined);
  }

  async end(nextStep: string, output = "", feel = ""): Promise<void> {
    if (this.ended) return;
    this.stopTimers();
    await save("patch", `/api/sessions/${this.info.id}`, this.payload({ next_step: nextStep, output, ended: true, ...(feel ? { feel } : {}) }));
    this.ended = true;
  }

  /** Leaving the reader without the end dialog: the session is closed with what it has, so it is not left open for ever. */
  leave(): void {
    if (this.ended) return;
    this.stopTimers();
    this.ended = true;
    save("patch", `/api/sessions/${this.info.id}`, this.payload({ ended: true })).catch(() => undefined);
  }

  stopTimers(): void {
    clearInterval(this.tickTimer);
    clearInterval(this.beatTimer);
  }
}
