// The comics themes' action moves, in the page (the background scene is the theme's scene.js).
//  - step(): when the pacer moves on, Classic Action and Manga Action pop a small sound effect beside the page
//    (ZIP!, WHAM!…) and the page's ink shadow takes a hit. The page itself never moves: the text stays still.
//  - burst(): finishing a section pops one big KA-POW! (GO GO GO! in Manga Action), in every comics theme.
// Rules: nothing at all when motion is off, Still, or reduce-motion; at most one move every MIN_GAP_MS (never
// more than once a second, so nothing flashes); words are set with textContent; the elements ignore the pointer
// and are hidden from screen readers (they repeat nothing the page says).
import { ambience } from "./ambience";
import { prefersReducedMotion } from "./util";

/** The least time between two sound effects. Sentences are shown for at least 0.9 s, so most get none. */
export const MIN_GAP_MS = 2_500;
const BURST_MS = 1_600;

const SFX: Record<string, string[]> = {
  action: ["ZIP!", "WHAM!", "ZOOM!", "BAM!", "SWOOSH!", "POW!"],
  manga: ["SHAA!", "DOOM!", "ZAP!", "WHAM!", "BOOM!", "GO!"],
};
const BIG: Record<string, string> = { classic: "KA-POW!", action: "KA-POW!", manga: "GO GO GO!" };

let lastStep = 0;
let turn = 0;
let sfxEl: HTMLElement | null = null;
let burstEl: HTMLElement | null = null;
let burstTimer: number | undefined;

function variant(): string | undefined {
  const root = document.documentElement;
  return root.dataset.look === "comics" ? root.dataset.lookVariant : undefined;
}

/** Motion is allowed: not reduce-motion, and the motion setting is Gentle or Lively (not Still, not off).
 *  It reads the setting, not the scene, so the moves follow it even while the background is still starting. */
function moving(): boolean {
  return !prefersReducedMotion() && (ambience.intensity === "gentle" || ambience.intensity === "lively");
}

/** A star-shaped burst: an ink outline around a coloured star, with the word inside. */
function makeBurst(cls: string): HTMLElement {
  const outer = document.createElement("div");
  outer.className = cls;
  outer.setAttribute("aria-hidden", "true");
  const inner = document.createElement("span");
  outer.append(inner);
  document.body.append(outer);
  return outer;
}

/** Restart a one-shot CSS animation by swapping between two class names that run the same keyframes.
 *  Each element swaps on its own (a shared counter moved by two elements would always land on the same name). */
function retrigger(el: Element, base: string): void {
  const next = el.classList.contains(`${base}-a`) ? "b" : "a";
  el.classList.remove(`${base}-a`, `${base}-b`);
  el.classList.add(`${base}-${next}`);
}

export const comics = {
  /** The pacer moved on to another sentence. `page` is the reading panel (its shadow takes the hit). */
  step(page: HTMLElement | null): void {
    const v = variant();
    if (!v || !SFX[v] || !moving()) return;
    const now = performance.now();
    if (now - lastStep < MIN_GAP_MS) return;
    lastStep = now;
    sfxEl ??= makeBurst("comics-sfx");
    (sfxEl.firstElementChild as HTMLElement).textContent = SFX[v][turn++ % SFX[v].length];
    if (page) {
      // on the page's top-right corner, half over the margin: over the padding, not the text
      const r = page.getBoundingClientRect();
      const top = Math.max(r.top, page.parentElement?.getBoundingClientRect().top ?? 0);
      sfxEl.style.left = `${Math.round(r.right - 52)}px`;
      sfxEl.style.top = `${Math.round(top - 18)}px`;
    }
    retrigger(sfxEl, "pop");
    if (page) retrigger(page, "comics-hit");
  },

  /** A section was finished. */
  burst(): void {
    const v = variant();
    if (!v || !moving()) return;
    burstEl ??= makeBurst("comics-burst");
    (burstEl.firstElementChild as HTMLElement).textContent = BIG[v] ?? BIG.classic;
    burstEl.classList.add("on");
    retrigger(burstEl, "pop");
    clearTimeout(burstTimer);
    burstTimer = window.setTimeout(() => burstEl?.classList.remove("on"), BURST_MS);
  },
};
