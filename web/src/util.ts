// DOM helpers. Document text is always inserted as text nodes — never as HTML.

type Kid = Node | string | number | null | undefined | false | Kid[];
type Attrs = Record<string, unknown>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...kids: Kid[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = String(v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v as EventListener);
      else if (k === "value" && "value" in el) (el as unknown as HTMLInputElement).value = String(v);
      else if (k === "checked" && el instanceof HTMLInputElement) el.checked = Boolean(v);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  append(el, kids);
  return el;
}

export function append(el: Node, kids: Kid[]): void {
  for (const k of kids) {
    if (k === null || k === undefined || k === false) continue;
    if (Array.isArray(k)) append(el, k);
    else el.appendChild(typeof k === "object" ? k : document.createTextNode(String(k)));
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

type TextBox = HTMLInputElement | HTMLTextAreaElement;
const drawnValue = new WeakMap<Element, string>(); // what each text box held when its page drew it

/** Redraw a page without losing what is half-typed on it.
 *  `draw` empties `root` and builds it again (a late answer from the server or a timer event can ask for that
 *  at any moment). Text you typed and did not send yet is put back into the same box, with the caret and the focus.
 *  A box is "the same" when its class, its `data-id` / `data-day` and its label match. */
export function keepTyped(root: HTMLElement, draw: () => void): void {
  const boxes = (): Map<string, TextBox> => {
    const out = new Map<string, TextBox>();
    const seen = new Map<string, number>();
    for (const el of root.querySelectorAll<TextBox>('input[type="text"], textarea')) {
      const name = [el.tagName, el.className, el.dataset.id ?? "", el.dataset.day ?? "", el.getAttribute("aria-label") ?? ""].join("|");
      const n = seen.get(name) ?? 0;
      seen.set(name, n + 1);
      out.set(`${name}|${n}`, el);
    }
    return out;
  };
  const typed: { key: string; value: string; changed: boolean; focus: boolean; from: number | null; to: number | null }[] = [];
  for (const [key, el] of boxes()) {
    const focus = document.activeElement === el;
    const changed = el.value !== (drawnValue.get(el) ?? "");
    if (changed || focus) typed.push({ key, value: el.value, changed, focus, from: el.selectionStart, to: el.selectionEnd });
  }
  draw();
  const now = boxes();
  for (const el of now.values()) drawnValue.set(el, el.value);
  for (const t of typed) {
    const el = now.get(t.key);
    if (!el) continue; // the box is gone (its task was done, its day passed): there is nowhere to put the text back
    if (t.changed && el.value !== t.value) {
      el.value = t.value;
      el.dispatchEvent(new Event("input")); // a preview under the box follows the text
    }
    if (t.focus) {
      el.focus();
      if (t.from !== null && t.to !== null) el.setSelectionRange(t.from, t.to);
    }
  }
}

export function toast(msg: string, kind: "info" | "error" | "ok" = "info", ms = 3500, action?: { label: string; run: () => void }): void {
  const box = document.getElementById("toasts")!;
  const t = h("div", { class: `toast ${kind}`, role: "status" }, msg);
  if (action) {
    t.append(
      " ",
      h("button", {
        class: "toast-action",
        onclick: () => {
          t.remove();
          action.run();
        },
      }, action.label),
    );
  }
  box.appendChild(t);
  setTimeout(() => t.classList.add("out"), ms);
  setTimeout(() => t.remove(), ms + 400);
}

export interface ModalHandle {
  close: (value?: unknown) => void;
  el: HTMLElement;
}

/** A small modal. Resolves with whatever close() is given (undefined on Esc / backdrop). */
export function modal(title: string, body: Kid, opts: { wide?: boolean; onOpen?: (m: ModalHandle) => void; dismissable?: boolean } = {}): Promise<unknown> {
  return new Promise((resolve) => {
    const prevFocus = document.activeElement as HTMLElement | null;
    const panel = h("div", { class: `modal ${opts.wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title }, h("h2", null, title), body);
    const back = h("div", { class: "modal-back" }, panel);
    let done = false;
    const close = (v?: unknown) => {
      if (done) return;
      done = true;
      back.remove();
      document.removeEventListener("keydown", onKey, true);
      prevFocus?.focus?.();
      resolve(v);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || opts.dismissable === false) return;
      const open = document.querySelectorAll(".modal-back");
      if (open[open.length - 1] !== back) return; // a dialog opened over this one closes first: one Escape, one dialog
      e.stopPropagation();
      close(undefined);
    };
    back.addEventListener("mousedown", (e) => {
      if (e.target === back && opts.dismissable !== false) close(undefined);
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(back);
    const handle = { close, el: panel };
    opts.onOpen?.(handle);
    const first = panel.querySelector<HTMLElement>("[autofocus]") ?? panel.querySelector<HTMLElement>("textarea, input, select, button.primary, button");
    first?.focus();
  });
}

export function askText(title: string, label: string, initial = "", opts: { multiline?: boolean; okLabel?: string; placeholder?: string } = {}): Promise<string | null> {
  let field: HTMLInputElement | HTMLTextAreaElement;
  if (opts.multiline) field = h("textarea", { rows: 4, placeholder: opts.placeholder ?? "", autofocus: true }, initial);
  else field = h("input", { type: "text", value: initial, placeholder: opts.placeholder ?? "", autofocus: true });
  return new Promise((resolve) => {
    let handle: ModalHandle;
    const ok = () => handle.close(field.value.trim());
    field.addEventListener("keydown", (e) => {
      const ke = e as KeyboardEvent;
      if (ke.key === "Enter" && (!opts.multiline || ke.ctrlKey)) {
        e.preventDefault();
        ok();
      }
    });
    modal(title, h("div", { class: "stack" }, h("label", { class: "field" }, h("span", null, label), field), h("div", { class: "row end" }, h("button", { onclick: () => handle.close(null) }, "Cancel"), h("button", { class: "primary", onclick: ok }, opts.okLabel ?? "Save"))), {
      onOpen: (m) => (handle = m),
    }).then((v) => resolve(typeof v === "string" ? v : null));
  });
}

export function confirmBox(title: string, text: string, okLabel = "OK"): Promise<boolean> {
  return new Promise((resolve) => {
    let handle: ModalHandle;
    modal(title, h("div", { class: "stack" }, h("p", null, text), h("div", { class: "row end" }, h("button", { onclick: () => handle.close(false) }, "Cancel"), h("button", { class: "primary", onclick: () => handle.close(true) }, okLabel))), {
      onOpen: (m) => (handle = m),
    }).then((v) => resolve(v === true));
  });
}

export function isTyping(e: Event): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  return t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || !!document.querySelector(".modal-back");
}

export function fmtMinutes(ms: number): string {
  const m = Math.round(ms / 60000);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function fmtClock(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// Debounced calls that haven't run yet. Leaving a screen or closing the window runs them right away,
// so a debounced autosave never drops your last keystrokes ("never lose work").
const pending = new Set<() => void>();

export function flushPending(): void {
  for (const run of [...pending]) run();
}

export function debounce<T extends unknown[]>(fn: (...a: T) => void, ms: number): ((...a: T) => void) & { flush: () => void } {
  let t: number | undefined;
  let args: T | null = null;
  const run = () => {
    clearTimeout(t);
    pending.delete(run);
    if (args) {
      const a = args;
      args = null;
      fn(...a);
    }
  };
  const call = (...a: T) => {
    args = a;
    clearTimeout(t);
    pending.add(run);
    t = window.setTimeout(run, ms);
  };
  return Object.assign(call, { flush: run });
}

export const prefersReducedMotion = (): boolean => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const HL_LABELS: Record<string, string> = {
  claim: "Claim",
  evidence: "Evidence",
  definition: "Definition",
  confusing: "Confusing",
  idea: "Idea",
};
export const HL_KEYS: Record<string, "claim" | "evidence" | "definition" | "confusing" | "idea"> = {
  "1": "claim",
  "2": "evidence",
  "3": "definition",
  "4": "confusing",
  "5": "idea",
};

export const KIND_LABELS: Record<string, string> = {
  abstract: "Abstract",
  intro: "Intro",
  related: "Related",
  method: "Method",
  results: "Results",
  discussion: "Discussion",
  conclusion: "Conclusion",
  references: "References",
  appendix: "Appendix",
  other: "Section",
};
