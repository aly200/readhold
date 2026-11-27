// Digital ink: pen, highlighter and eraser on a canvas, saved as small vector strokes (not pixels).
// - Pressure from a pen (PointerEvent.pressure); mouse and finger use a steady width.
// - Palm rejection: once a pen has touched the pad, finger touches are ignored for drawing.
// - Coordinates are stored relative to the pad's width (x 0..1, y 0..height/width), so ink stays put
//   when the window or zoom changes. Undo/redo keep snapshots; every change is saved shortly after.
import { save } from "./api";
import { h } from "./util";

export type Tool = "pen" | "highlighter" | "eraser";
export interface Stroke {
  tool: "pen" | "highlighter";
  color: string;
  size: number; // relative to pad width
  points: [number, number, number][]; // x, y (relative to width), pressure 0..1
}

export const INK_COLORS = ["#1f2937", "#1d4ed8", "#c2410c", "#15803d", "#7c3aed", "#be123c"];
const SIZES = { fine: 0.0025, medium: 0.0045, bold: 0.008 };

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
}

export interface InkOptions {
  /** Where strokes are saved: /api/ink/<owner>. Empty = not saved (preview). */
  owner?: string;
  /** Draw dark ink light on dark paper (sketch pages); off for ink over white slides. */
  adaptToDark?: () => boolean;
  readonly?: boolean;
  onChange?: (strokes: Stroke[]) => void;
}

export class InkPad {
  readonly canvas: HTMLCanvasElement;
  strokes: Stroke[] = [];
  tool: Tool = "pen";
  color = INK_COLORS[0];
  size: number = SIZES.medium;
  enabled = true;
  private ctx: CanvasRenderingContext2D;
  private undoStack: string[] = [];
  private redoStack: string[] = [];
  private current: Stroke | null = null;
  private activePointer: number | null = null;
  private penSeen = false;
  private saveTimer = 0;
  private loading = false;
  private loadFailed = false;
  private dirtyWhileLoading = false;
  private ro: ResizeObserver;
  private w = 1;
  private hgt = 1;
  private ox = 0; // scroll offset in px: the pad is a window onto a taller page (web lectures)
  private oy = 0;
  private dpr = 1;

  constructor(private host: HTMLElement, private opts: InkOptions = {}) {
    this.canvas = h("canvas", { class: "ink-canvas", "aria-label": "Drawing area" });
    host.append(this.canvas);
    this.ctx = this.canvas.getContext("2d")!;
    // Resize on the next frame: resizing the canvas inside the observer callback can trigger
    // another observation in the same frame (a "ResizeObserver loop" warning).
    let queued = 0;
    this.ro = new ResizeObserver(() => {
      if (queued) return;
      queued = requestAnimationFrame(() => { queued = 0; if (this.canvas.isConnected) this.resize(); });
    });
    this.ro.observe(host);
    if (!opts.readonly) {
      this.canvas.addEventListener("pointerdown", this.down);
      this.canvas.addEventListener("pointermove", this.move);
      this.canvas.addEventListener("pointerup", this.up);
      this.canvas.addEventListener("pointercancel", this.up);
    }
    this.resize();
  }

  async load(): Promise<void> {
    if (!this.opts.owner) return;
    this.loading = true;
    try {
      const r = await fetch(`/api/ink/${this.opts.owner}`, { credentials: "same-origin" });
      if (!r.ok) throw new Error(String(r.status));
      const saved = ((await r.json()) as { strokes: Stroke[] }).strokes ?? [];
      // strokes drawn while loading are kept on top of the saved ones, never dropped
      this.strokes = [...saved, ...this.strokes];
      this.loadFailed = false;
    } catch {
      // Couldn't read the saved ink: don't save over it with a partial picture.
      this.loadFailed = true;
    } finally {
      this.loading = false;
    }
    this.redraw();
    if (this.dirtyWhileLoading && !this.loadFailed) this.changed();
    this.dirtyWhileLoading = false;
  }

  setEnabled(on: boolean): void {
    this.enabled = on;
    this.canvas.classList.toggle("drawing", on);
  }

  // ------------------------------------------------------------------ pointer input
  private point(e: PointerEvent): [number, number, number] {
    const r = this.canvas.getBoundingClientRect();
    const x = (e.clientX - r.left + this.ox) / r.width;
    const y = (e.clientY - r.top + this.oy) / r.width; // y relative to width keeps proportions
    const p = e.pointerType === "pen" ? (e.pressure || 0.5) : 0.5;
    return [x, y, p];
  }

  private down = (e: PointerEvent): void => {
    if (!this.enabled || this.activePointer !== null) return;
    if (e.pointerType === "pen") this.penSeen = true;
    else if (e.pointerType === "touch" && this.penSeen) return; // palm rejection
    if (e.button !== 0 && e.pointerType === "mouse") return;
    e.preventDefault();
    try {
      this.canvas.setPointerCapture(e.pointerId);
    } catch {
      /* the pointer was already released: drawing still works without capture */
    }
    this.activePointer = e.pointerId;
    if (this.tool === "eraser") {
      this.snapshot();
      this.eraseAt(this.point(e));
      return;
    }
    this.current = { tool: this.tool, color: this.color, size: this.tool === "highlighter" ? this.size * 3.2 : this.size, points: [this.point(e)] };
  };

  private move = (e: PointerEvent): void => {
    if (e.pointerId !== this.activePointer) return;
    const events = typeof e.getCoalescedEvents === "function" ? e.getCoalescedEvents() : [e];
    for (const ev of events.length ? events : [e]) {
      const pt = this.point(ev);
      if (this.tool === "eraser") this.eraseAt(pt);
      else if (this.current) {
        const prev = this.current.points[this.current.points.length - 1];
        if (Math.hypot(pt[0] - prev[0], pt[1] - prev[1]) * this.w < 0.6) continue; // skip sub-pixel jitter
        this.current.points.push(pt);
        this.drawSegment(this.current, this.current.points.length - 1);
      }
    }
  };

  private up = (e: PointerEvent): void => {
    if (e.pointerId !== this.activePointer) return;
    this.activePointer = null;
    if (this.current) {
      if (this.current.points.length === 1) this.current.points.push([this.current.points[0][0] + 0.0005, this.current.points[0][1], this.current.points[0][2]]);
      this.snapshot();
      this.strokes.push(this.current);
      this.current = null;
      this.redraw();
      this.changed();
    } else if (this.tool === "eraser") this.changed();
  };

  private eraseAt([x, y]: [number, number, number]): void {
    const r = 0.012;
    const before = this.strokes.length;
    this.strokes = this.strokes.filter((s) => !s.points.some(([px, py]) => Math.hypot(px - x, py - y) < r + s.size / 2));
    if (this.strokes.length !== before) this.redraw();
  }

  // ------------------------------------------------------------------ history
  private snapshot(): void {
    this.undoStack.push(JSON.stringify(this.strokes));
    if (this.undoStack.length > 60) this.undoStack.shift();
    this.redoStack = [];
  }

  undo(): void {
    const prev = this.undoStack.pop();
    if (prev === undefined) return;
    this.redoStack.push(JSON.stringify(this.strokes));
    this.strokes = JSON.parse(prev);
    this.redraw();
    this.changed();
  }

  redo(): void {
    const next = this.redoStack.pop();
    if (next === undefined) return;
    this.undoStack.push(JSON.stringify(this.strokes));
    this.strokes = JSON.parse(next);
    this.redraw();
    this.changed();
  }

  clear(): void {
    if (!this.strokes.length) return;
    this.snapshot();
    this.strokes = [];
    this.redraw();
    this.changed();
  }

  private changed(): void {
    this.opts.onChange?.(this.strokes);
    if (!this.opts.owner) return;
    if (this.loading) {
      this.dirtyWhileLoading = true; // saved once the existing ink has arrived and been merged
      return;
    }
    if (this.loadFailed) {
      console.warn("Ink not saved: the existing ink for this page couldn't be loaded.");
      return;
    }
    clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => this.flush(), 700);
  }

  /** Save now (also called when leaving the page). */
  flush(): void {
    if (!this.opts.owner || !this.saveTimer) return;
    clearTimeout(this.saveTimer);
    this.saveTimer = 0;
    void save("put", `/api/ink/${this.opts.owner}`, { strokes: this.strokes });
  }

  // ------------------------------------------------------------------ drawing
  /** Scroll the pad's window over the page (px). Strokes keep their place on the page. */
  setOffset(x: number, y: number): void {
    if (x === this.ox && y === this.oy) return;
    this.ox = x;
    this.oy = y;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, -x * this.dpr, -y * this.dpr);
    this.redraw();
  }

  resize(): void {
    const r = this.host.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = Math.max(1, r.width);
    this.hgt = Math.max(1, r.height);
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.hgt * dpr);
    this.canvas.style.width = `${this.w}px`;
    this.canvas.style.height = `${this.hgt}px`;
    this.dpr = dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, -this.ox * dpr, -this.oy * dpr);
    this.redraw();
  }

  private colorFor(s: Stroke): string {
    if (this.opts.adaptToDark?.() && luminance(s.color) < 0.3) return "#e8e6e1";
    return s.color;
  }

  private style(s: Stroke): void {
    const c = this.ctx;
    c.strokeStyle = this.colorFor(s);
    c.lineCap = s.tool === "highlighter" ? "butt" : "round";
    c.lineJoin = "round";
    c.globalAlpha = s.tool === "highlighter" ? 0.32 : 1;
  }

  private width(s: Stroke, p: number): number {
    const base = s.size * this.w;
    return s.tool === "highlighter" ? base : Math.max(0.6, base * (0.35 + p * 1.1));
  }

  private drawSegment(s: Stroke, i: number): void {
    const c = this.ctx;
    const a = s.points[i - 1];
    const b = s.points[i];
    this.style(s);
    c.lineWidth = this.width(s, b[2]);
    c.beginPath();
    c.moveTo(a[0] * this.w, a[1] * this.w);
    c.lineTo(b[0] * this.w, b[1] * this.w);
    c.stroke();
    c.globalAlpha = 1;
  }

  private drawStroke(s: Stroke): void {
    const c = this.ctx;
    const pts = s.points;
    if (pts.length < 2) return;
    this.style(s);
    if (s.tool === "highlighter") {
      // one path, one width: overlapping segments of a translucent stroke must not stack up
      c.lineWidth = this.width(s, 0.5);
      c.beginPath();
      c.moveTo(pts[0][0] * this.w, pts[0][1] * this.w);
      for (let i = 1; i < pts.length; i++) c.lineTo(pts[i][0] * this.w, pts[i][1] * this.w);
      c.stroke();
    } else {
      // smooth: quadratic curves through midpoints, width following pressure
      for (let i = 1; i < pts.length; i++) {
        const p0 = pts[i - 1];
        const p1 = pts[i];
        const m0 = i > 1 ? [(pts[i - 2][0] + p0[0]) / 2, (pts[i - 2][1] + p0[1]) / 2] : [p0[0], p0[1]];
        const m1 = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2];
        c.lineWidth = this.width(s, (p0[2] + p1[2]) / 2);
        c.beginPath();
        c.moveTo(m0[0] * this.w, m0[1] * this.w);
        c.quadraticCurveTo(p0[0] * this.w, p0[1] * this.w, m1[0] * this.w, m1[1] * this.w);
        if (i === pts.length - 1) c.lineTo(p1[0] * this.w, p1[1] * this.w);
        c.stroke();
      }
    }
    c.globalAlpha = 1;
  }

  redraw(): void {
    this.ctx.clearRect(this.ox, this.oy, this.w, this.hgt);
    for (const s of this.strokes) this.drawStroke(s);
  }

  destroy(): void {
    this.flush();
    this.ro.disconnect();
    this.canvas.remove();
  }
}

/** Pen / highlighter / eraser, colours, sizes, undo, redo, clear. */
export function inkToolbar(pad: InkPad, extra: (HTMLElement | null)[] = []): HTMLElement {
  const bar = h("div", { class: "ink-bar", role: "toolbar", "aria-label": "Pen tools" });
  const toolBtn = (t: Tool, label: string, key: string) =>
    h("button", { class: `ink-tool ${pad.tool === t ? "on" : ""}`, title: `${label} (${key})`, "aria-pressed": String(pad.tool === t), "data-tool": t, onclick: () => pick(t) }, label);
  const pick = (t: Tool) => {
    pad.tool = t;
    bar.querySelectorAll<HTMLElement>("[data-tool]").forEach((b) => {
      b.classList.toggle("on", b.dataset.tool === t);
      b.setAttribute("aria-pressed", String(b.dataset.tool === t));
    });
  };
  const swatches = h("div", { class: "ink-colors", role: "group", "aria-label": "Ink colour" }, INK_COLORS.map((c, i) => {
    const b = h("button", { class: `ink-swatch ${pad.color === c ? "on" : ""}`, style: { background: c }, "aria-label": `Colour ${i + 1}`, onclick: () => {
      pad.color = c;
      if (pad.tool === "eraser") pick("pen");
      swatches.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    } });
    return b;
  }));
  const sizes = h("div", { class: "ink-sizes", role: "group", "aria-label": "Pen size" }, (Object.keys(SIZES) as (keyof typeof SIZES)[]).map((k) => {
    const b = h("button", { class: `ink-size ${pad.size === SIZES[k] ? "on" : ""}`, title: k, "aria-label": `${k} pen`, onclick: () => {
      pad.size = SIZES[k];
      sizes.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    } }, h("span", { style: { width: `${k === "fine" ? 4 : k === "medium" ? 7 : 11}px`, height: `${k === "fine" ? 4 : k === "medium" ? 7 : 11}px` } }));
    return b;
  }));
  bar.append(
    toolBtn("pen", "Pen", "B"),
    toolBtn("highlighter", "Marker", "M"),
    toolBtn("eraser", "Eraser", "E"),
    swatches,
    sizes,
    h("button", { class: "ink-tool", title: "Undo (Ctrl+Z)", onclick: () => pad.undo() }, "Undo"),
    h("button", { class: "ink-tool", title: "Redo (Ctrl+Y)", onclick: () => pad.redo() }, "Redo"),
    h("button", { class: "ink-tool", title: "Clear this page's ink", onclick: () => pad.strokes.length && confirm("Clear all ink here? (Undo can bring it back.)") && pad.clear() }, "Clear"),
    ...extra.filter((x): x is HTMLElement => x !== null),
  );
  (bar as HTMLElement & { pick?: (t: Tool) => void }).pick = pick;
  return bar;
}

/** Keyboard for an active pad: B pen, M marker, E eraser, Ctrl+Z undo, Ctrl+Y / Ctrl+Shift+Z redo. */
export function inkKeys(pad: InkPad, bar: HTMLElement, e: KeyboardEvent): boolean {
  const pick = (bar as HTMLElement & { pick?: (t: Tool) => void }).pick;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    if (e.shiftKey) pad.redo();
    else pad.undo();
    return true;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
    e.preventDefault();
    pad.redo();
    return true;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  const t = ({ b: "pen", m: "highlighter", e: "eraser" } as Record<string, Tool>)[e.key.toLowerCase()];
  if (t && pick) {
    pick(t);
    return true;
  }
  return false;
}
