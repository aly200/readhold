// Look at the view: one small button (and the V key) fades the page away for a moment so only the theme's
// scene is left. Any key or click brings the page back. A breath for the eyes between two pieces of work.
import { h, isTyping } from "./util";

let on = false;
let button: HTMLButtonElement | null = null;

function set(next: boolean): void {
  on = next;
  document.documentElement.toggleAttribute("data-peek", on);
  button?.setAttribute("aria-pressed", String(on));
}

export function mountPeek(): void {
  const dock = document.getElementById("corner-dock") ?? document.body.appendChild(h("div", { id: "corner-dock", class: "corner-dock" }));
  button = h("button", { class: "peek-btn", type: "button", title: "Look at the view (V)", "aria-label": "Look at the view", "aria-pressed": "false", onclick: (e: Event) => {
    e.stopPropagation();
    set(!on);
  } }, h("span", { "aria-hidden": "true" }, "🌅"));
  dock.append(button);
  // any click or key brings the page back
  document.addEventListener("pointerdown", (e) => {
    if (on && !button?.contains(e.target as Node)) {
      e.preventDefault();
      e.stopPropagation();
      set(false);
    }
  }, true);
  document.addEventListener("keydown", (e) => {
    if (on) {
      e.preventDefault();
      e.stopPropagation();
      set(false);
      return;
    }
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key.toLowerCase() === "v" && document.documentElement.hasAttribute("data-scene")) {
      e.preventDefault();
      set(true);
    }
  }, true);
  window.addEventListener("hashchange", () => on && set(false));
}
