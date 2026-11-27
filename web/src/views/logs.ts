// The daily log list (did, learned, next), shared by the quest page and the weekly review.
import type { DayLog } from "../types";
import { h } from "../util";

export const fmtDay = (day: string, long = false): string =>
  new Date(`${day}T12:00:00`).toLocaleDateString(undefined, long ? { weekday: "short", month: "short", day: "numeric" } : { weekday: "short", day: "numeric" });

export function logList(logs: Pick<DayLog, "day" | "did" | "learned" | "next">[], long = false): HTMLElement {
  const line = (label: string, text: string) => (text ? h("p", null, h("span", { class: "kicker" }, `${label} `), text) : null);
  return h(
    "ul",
    { class: "log-list" },
    logs.map((l) => h("li", null, h("div", { class: "log-day" }, fmtDay(l.day, long)), h("div", { class: "log-lines" }, line("Did", l.did), line("Learned", l.learned), line("Next", l.next)))),
  );
}
