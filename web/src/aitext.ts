// Drawing what a model wrote. Milestone 1.2 of docs/ai/PLAN.md, "safe rendering".
//
// A model's answer is untrusted text: a document it read may have told it what to write. So an answer is drawn
// with text nodes only. There is no markup from the answer, no picture, no link element and nothing to load:
// an address in an answer is shown as words. The server has already turned image and link syntax into words
// (`guard.safe_output`); this file would be safe without that, because it never builds anything but text.
//
// The small Markdown understood here: paragraphs, "- " and "1. " lists, "#" headings (drawn as bold lines),
// **bold**, *italic* and `code`. Everything else stays as the characters it is, "<script>" included.
import { h } from "./util";

/** Split a line into plain, bold, italic and code runs. Every run becomes a text node inside a span. */
function runs(line: string): HTMLElement[] {
  const out: HTMLElement[] = [];
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)/g;
  let at = 0;
  for (const m of line.matchAll(re)) {
    const i = m.index ?? 0;
    if (i > at) out.push(h("span", null, line.slice(at, i)));
    const t = m[0];
    if (t.startsWith("**")) out.push(h("strong", null, t.slice(2, -2)));
    else if (t.startsWith("`")) out.push(h("code", null, t.slice(1, -1)));
    else out.push(h("em", null, t.slice(1, -1)));
    at = i + t.length;
  }
  if (at < line.length) out.push(h("span", null, line.slice(at)));
  return out;
}

/** The answer as elements. `label` says who wrote it, so it is never mistaken for your own words. */
export function aiText(text: string, label = "Written by the AI model. Check it against the source."): HTMLElement {
  const box = h("div", { class: "ai-text" }, h("div", { class: "ai-text-label" }, label));
  let list: HTMLElement | null = null;
  let para: string[] = [];
  const flush = () => {
    if (para.length) box.append(h("p", null, runs(para.join(" "))));
    para = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = line.match(/^\s*(?:[-*•]|\d{1,3}[.)])\s+(.*)$/);
    const head = line.match(/^#{1,6}\s+(.*)$/);
    if (item) {
      flush();
      if (!list) {
        list = h("ul", null);
        box.append(list);
      }
      list.append(h("li", null, runs(item[1])));
      continue;
    }
    list = null;
    if (!line.trim()) flush();
    else if (head) {
      flush();
      box.append(h("p", { class: "ai-text-head" }, h("strong", null, head[1])));
    } else para.push(line.trim());
  }
  flush();
  return box;
}

/** The addresses a model wrote, as words under the answer. They are never opened from here. */
export function aiLinks(links: string[]): HTMLElement | null {
  if (!links.length) return null;
  return h("div", { class: "ai-text-links" },
    h("span", null, "The model wrote these addresses. Readhold does not open them: "),
    links.map((address, i) => h("code", null, (i ? " · " : "") + address)));
}
