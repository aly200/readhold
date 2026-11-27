// Mixed practice: a short set that switches between topics (interleaving), attempt before reveal,
// then an honest self-rating. Unlike review cards it isn't scheduled: use it before an exam,
// or when you want to know what you really know across everything.
import { ambience } from "../ambience";
import { api, save } from "../api";
import { mathText } from "../math";
import { clear, h, isTyping } from "../util";

interface Item {
  source_type: "quest_question" | "question" | "term";
  source_id: string;
  prompt: string;
  answer: string;
  topic: string;
  topic_id: string;
  last_result: "got" | "partly" | "missed" | null;
}

type Result = "got" | "partly" | "missed";

export async function practiceView(root: HTMLElement): Promise<() => void> {
  let items = await api.get<Item[]>("/api/practice?n=10");
  const page = h("section", { class: "practice" });
  root.append(page);
  ambience.update({ mode: "review" });
  let i = 0;
  let shown = false;
  const results: Result[] = [];
  let attempt: HTMLTextAreaElement | null = null;

  const rate = (r: Result) => {
    const it = items[i];
    results.push(r);
    void save("post", "/api/practice", { source_type: it.source_type, source_id: it.source_id, result: r });
    if (r === "got") ambience.moment();
    i++;
    shown = false;
    draw();
  };

  const draw = () => {
    clear(page);
    if (!items.length) {
      page.append(h("div", { class: "isle practice-end" },
        h("h1", null, "Mixed practice"),
        h("p", { class: "muted" }, "Nothing to practise yet. Practice uses what you've already answered: goal questions, questions in your papers, and terms with a definition."),
        h("a", { class: "btn", href: "#/review" }, "Back to Review"),
      ));
      return;
    }
    if (i >= items.length) {
      const got = results.filter((r) => r === "got").length;
      const partly = results.filter((r) => r === "partly").length;
      const missed = results.filter((r) => r === "missed").length;
      page.append(h("div", { class: "isle practice-end" },
        h("h1", null, "Set done"),
        h("p", { class: "practice-score" }, `${got} got it · ${partly} partly · ${missed} missed`),
        h("p", { class: "muted" }, missed ? "The ones you missed come first next time. Missing them now is what makes them stick." : "Solid. Mixed practice like this is the closest thing to the exam."),
        h("div", { class: "row" }, h("button", { class: "btn primary", autofocus: true, onclick: anotherSet }, "Another set"), h("a", { class: "btn", href: "#/review" }, "Back to Review")),
      ));
      return;
    }
    const it = items[i];
    attempt = h("textarea", { rows: 4, autofocus: true, placeholder: "Answer from memory first — a rough try counts", "aria-label": "Your attempt" });
    const card = h(
      "article",
      { class: "practice-card" },
      h("div", { class: "practice-meta" }, h("span", { class: "badge" }, it.topic), it.last_result === "missed" ? h("span", { class: "muted small" }, "missed last time") : null, h("span", { class: "muted small practice-count" }, `${i + 1} of ${items.length}`)),
      h("h2", { class: "practice-prompt" }, mathText(it.prompt)),
      shown
        ? h("div", { class: "practice-reveal" }, attemptText ? h("div", null, h("div", { class: "kicker" }, "Your try"), h("p", null, attemptText)) : null, h("div", null, h("div", { class: "kicker" }, "Answer"), h("p", null, mathText(it.answer))))
        : attempt,
      shown
        ? h(
            "div",
            { class: "row wrap practice-rate" },
            h("button", { class: "btn", onclick: () => rate("missed") }, "Missed (1)"),
            h("button", { class: "btn", onclick: () => rate("partly") }, "Partly (2)"),
            h("button", { class: "btn primary", onclick: () => rate("got") }, "Got it (3)"),
          )
        : h("div", { class: "row end" }, h("button", { class: "btn primary", onclick: reveal }, "Reveal (Enter)")),
    );
    page.append(h("div", { class: "isle practice-head" }, h("h1", null, "Mixed practice"), h("p", { class: "muted small" }, "Topics are mixed on purpose: switching is harder, and that's why it sticks.")), card);
    page.querySelector<HTMLElement>("[autofocus]")?.focus();
  };

  let attemptText = "";
  async function anotherSet(): Promise<void> {
    items = await api.get<Item[]>("/api/practice?n=10");
    i = 0;
    shown = false;
    results.length = 0;
    draw();
  }
  const reveal = () => {
    attemptText = attempt?.value.trim() ?? "";
    shown = true;
    draw();
  };

  const onKey = (e: KeyboardEvent) => {
    if (i >= items.length) return;
    if (!shown && e.key === "Enter" && !e.shiftKey && (e.target === attempt || !isTyping(e))) {
      e.preventDefault(); // Enter reveals; Shift+Enter makes a new line in your answer
      reveal();
      return;
    }
    if (shown && !isTyping(e) && ["1", "2", "3"].includes(e.key)) rate(e.key === "1" ? "missed" : e.key === "2" ? "partly" : "got");
  };
  document.addEventListener("keydown", onKey);
  draw();
  return () => document.removeEventListener("keydown", onKey);
}
