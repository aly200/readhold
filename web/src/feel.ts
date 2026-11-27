// Energy drain log: one optional tap after a session — energized, neutral or drained.
// Over a few weeks it shows which kinds of work drain you, so you can change the method, not just push harder.
import { h } from "./util";

export type Feel = "energized" | "neutral" | "drained";

const LABEL: Record<Feel, string> = { energized: "Energized", neutral: "Neutral", drained: "Drained" };

/** Three chips; `pick()` reads the choice ("" when skipped). */
export function feelRow(): { el: HTMLElement; pick: () => Feel | "" } {
  let chosen: Feel | "" = "";
  const row = h("div", { class: "row wrap feel-row", role: "group", "aria-label": "How did it feel?" });
  (Object.keys(LABEL) as Feel[]).forEach((f) => {
    const b = h("button", {
      class: `chip feel-${f}`,
      "aria-pressed": "false",
      onclick: () => {
        chosen = chosen === f ? "" : f;
        row.querySelectorAll("button").forEach((x) => {
          const on = x === b && chosen === f;
          x.classList.toggle("on", on);
          x.setAttribute("aria-pressed", String(on));
        });
      },
    }, LABEL[f]);
    row.append(b);
  });
  return { el: h("div", { class: "field" }, h("span", null, "How did it feel? (optional, one tap)"), row), pick: () => chosen };
}
