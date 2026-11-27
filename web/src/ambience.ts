// Ambience: one background canvas driven by the current theme's scene.js.
// Rules: one canvas, ≤ 30 fps, paused when hidden, reduce-motion → Still, nothing flashes.
// The reading text always sits on a solid panel above this canvas; motion lives in the background and margins.
import { prefersReducedMotion } from "./util";

/** What a scene module (themes/<id>/scene.js) default-exports. */
export type SceneFactory = (env: SceneEnv) => Scene;

export interface Scene {
  /** Draw one frame. `dt` is seconds of scene time since the last frame (already scaled by mood and intensity). */
  frame(dt: number, t: number): void;
  resize?(w: number, h: number): void;
  destroy?(): void;
}

export interface SceneEnv {
  ctx: CanvasRenderingContext2D;
  w: number;
  h: number;
  dark: boolean;
  tokens: Record<string, string>;
  /** Live state the scene reads every frame. */
  state: AmbienceState;
}

export interface AmbienceState {
  progress: number; // 0..1, reading progress of the open document (key sentences read)
  answered: number; // questions answered in the open document
  reviewed: number; // review cards rated today
  mode: "idle" | "reading" | "break" | "review";
  energy: "low" | "medium" | "high";
  /** performance.now() of the last "quiet moment" (a question answered), or 0. */
  moment: number;
  /** Seconds since the reading session started (0 when no session). */
  session: number;
  /** True when motion is off (Still intensity or reduce-motion): draw finished states, no transitions. */
  still: boolean;
}

type Intensity = "off" | "still" | "gentle" | "lively";

const FPS: Record<Intensity, number> = { off: 0, still: 0, gentle: 20, lively: 30 };
const PACE: Record<Intensity, number> = { off: 0, still: 0, gentle: 0.6, lively: 1 };
const MOOD: Record<AmbienceState["mode"], number> = { idle: 1, reading: 0.45, break: 1.25, review: 1.1 };

export const ambience = {
  state: { progress: 0, answered: 0, reviewed: 0, mode: "idle", energy: "medium", moment: 0, session: 0, still: true } as AmbienceState,
  canvas: null as HTMLCanvasElement | null,
  scene: null as Scene | null,
  sceneKey: "",
  intensity: "still" as Intensity,
  raf: 0,
  last: 0,
  t: 0,
  loading: 0,

  /** Called by applyTheme(): load (or keep) the theme's scene and restart the clock. */
  async apply(themeId: string, hasScene: boolean, tokens: Record<string, string>, dark: boolean, intensity: string): Promise<void> {
    this.intensity = (prefersReducedMotion() && intensity !== "off" ? "still" : intensity) as Intensity;
    const key = `${themeId}|${dark}|${JSON.stringify(tokens)}`;
    document.documentElement.toggleAttribute("data-scene", hasScene && this.intensity !== "off");
    if (!hasScene || this.intensity === "off") {
      this.teardown();
      return;
    }
    if (key !== this.sceneKey || !this.scene) {
      const ticket = ++this.loading;
      let factory: SceneFactory;
      try {
        const url = `/themes/${encodeURIComponent(themeId)}/scene.js`;
        factory = (await import(url)).default as SceneFactory;
      } catch (e) {
        console.warn("Theme scene failed to load", e);
        this.teardown();
        return;
      }
      if (ticket !== this.loading) return; // a newer theme was chosen meanwhile
      this.teardown();
      const canvas = this.ensureCanvas();
      const ctx = canvas.getContext("2d", { alpha: true })!;
      const { w, h } = this.size(canvas, ctx);
      try {
        this.scene = factory({ ctx, w, h, dark, tokens, state: this.state });
      } catch (e) {
        console.warn("Theme scene failed to start", e);
        this.teardown();
        return;
      }
      this.sceneKey = key;
    }
    this.restart();
  },

  ensureCanvas(): HTMLCanvasElement {
    if (this.canvas) return this.canvas;
    const c = document.createElement("canvas");
    c.id = "ambience";
    c.setAttribute("aria-hidden", "true");
    document.body.prepend(c);
    this.canvas = c;
    window.addEventListener("resize", () => this.onResize());
    document.addEventListener("visibilitychange", () => this.restart());
    window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", () => this.restart());
    return c;
  },

  size(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D): { w: number; h: number } {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5); // cheap on big screens
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w, h };
  },

  onResize(): void {
    if (!this.canvas || !this.scene) return;
    const ctx = this.canvas.getContext("2d")!;
    const { w, h } = this.size(this.canvas, ctx);
    this.scene.resize?.(w, h);
    this.drawOnce();
  },

  teardown(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    try {
      this.scene?.destroy?.();
    } catch {
      /* ignore */
    }
    this.scene = null;
    this.sceneKey = "";
    if (this.canvas) this.canvas.getContext("2d")!.clearRect(0, 0, this.canvas.width, this.canvas.height);
  },

  pace(): number {
    const energy = this.state.energy === "low" ? 0.6 : this.state.energy === "high" ? 1.1 : 1;
    return PACE[this.intensity] * MOOD[this.state.mode] * energy;
  },

  restart(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (!this.scene) return;
    const still = this.intensity === "still" || prefersReducedMotion();
    this.state.still = still;
    if (still || document.hidden) {
      if (!document.hidden) this.drawOnce();
      return;
    }
    this.last = performance.now();
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      const fps = FPS[this.intensity];
      const elapsed = now - this.last;
      if (elapsed < 1000 / fps - 2) return; // frame cap
      this.last = now;
      const dt = Math.min(elapsed / 1000, 0.1) * this.pace();
      this.t += dt;
      this.safeFrame(dt);
    };
    this.raf = requestAnimationFrame(loop);
  },

  /** Still mode, or a progress change while still: draw a single frame. */
  drawOnce(): void {
    if (this.scene && (this.intensity === "still" || prefersReducedMotion() || !this.raf)) this.safeFrame(0);
  },

  safeFrame(dt: number): void {
    try {
      this.scene!.frame(dt, this.t);
    } catch (e) {
      console.warn("Theme scene error; motion stopped", e);
      this.teardown();
    }
  },

  update(patch: Partial<AmbienceState>): void {
    const moodChanged = patch.mode !== undefined && patch.mode !== this.state.mode;
    Object.assign(this.state, patch);
    if (moodChanged) this.last = performance.now();
    this.drawOnce();
  },

  /** A small, quiet moment (a question answered). Scenes show a slow glow — never a flash. */
  moment(): void {
    this.state.moment = performance.now();
    this.drawOnce();
  },
};
