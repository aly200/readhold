// Daily review with FSRS: about 5 minutes, capped so it never piles up. Attempt before reveal.
import { ambience } from "../ambience";
import { api } from "../api";
import { mathText } from "../math";
import { removeItem } from "../trash";
import type { Card } from "../types";
import { clear, h, toast } from "../util";
import { libraryHead } from "./libtabs";

const SOURCE: Record<string, string> = { term: "Term", definition: "Definition", question: "Your question", cloze: "Fill the blank", quest_question: "Goal question", lecture_note: "Lecture", ai: "Written by the AI model: check it against the passage on the back" };

export async function reviewView(root: HTMLElement): Promise<() => void> {
  const data = await api.get<{ cards: Card[]; due_total: number; cap_left: number }>("/api/review/due");
  const cards = data.cards;
  let i = 0;
  let shown = false;
  let done = 0;
  const box = h("div", { class: "review-card" });
  const status = h("div", { class: "muted small" });
  root.append(
    h(
      "section",
      { class: "review" },
      libraryHead("review", h("a", { class: "btn", href: "#/practice", title: "A short set mixing your topics, any time" }, "Mixed practice")),
      status,
      box,
    ),
  );

  const draw = () => {
    clear(box);
    status.textContent = cards.length ? `${Math.min(i + 1, cards.length)} of ${cards.length}${data.due_total > cards.length ? ` (cap reached — ${data.due_total - cards.length} wait for tomorrow)` : ""}` : "";
    if (i >= cards.length) {
      box.append(h("h2", null, done ? "Done for today" : "Nothing due"), h("p", null, done ? `${done} cards reviewed. This counts toward your streak.` : "Cards come from your guesses, definitions, questions and evidence blanks."), h("div", { class: "row" }, h("a", { class: "btn primary", href: "#/library" }, "Back to the documents"), h("a", { class: "btn", href: "#/practice" }, "Mixed practice")));
      return;
    }
    const c = cards[i];
    box.append(h("div", { class: "muted small" }, SOURCE[c.source_type] ?? c.source_type), h("p", { class: "front" }, mathText(c.front)));
    if (!shown) {
      box.append(h("p", { class: "muted small" }, "Answer in your head (or out loud) first."), h("button", { class: "btn primary", onclick: reveal }, "Show answer (Space)"));
    } else {
      box.append(
        h("div", { class: "back" }, c.back.split("\n\n").map((part) => h("p", null, mathText(part)))),
        h(
          "div",
          { class: "row ratings" },
          [
            [1, "Again"],
            [2, "Hard"],
            [3, "Good"],
            [4, "Easy"],
          ].map(([n, label]) => h("button", { class: `btn ${n === 3 ? "primary" : ""}`, onclick: () => rate(Number(n)) }, `${label} (${n})`)),
        ),
      );
    }
    box.append(h("div", { class: "row end review-tools" }, h("button", { class: "btn small ghost", title: "It will not come back in review. Undo puts it back.", onclick: () => void removeCard(c) }, "Delete card")));
  };
  // a card you delete is skipped now and stays out of review, even when what it came from changes; Undo puts it back
  const removeCard = async (c: Card) => {
    await removeItem("card", c.id, "Card deleted. It will not come back in review.", {
      gone: () => {
        const at = cards.indexOf(c);
        if (at < 0) return;
        cards.splice(at, 1);
        data.due_total = Math.max(0, data.due_total - 1); // it is not waiting for tomorrow either
        if (at < i) i--;
        if (at === i) shown = false;
        draw();
      },
      back: () => {
        if (cards.includes(c)) return;
        data.due_total++;
        cards.splice(shown ? i + 1 : i, 0, c); // next in line, or now when no answer is showing
        draw();
      },
    });
  };
  const reveal = () => {
    shown = true;
    draw();
  };
  let saving = false;
  const rate = async (n: number) => {
    if (saving) return; // a second key press while the first is being saved must not rate the same card twice
    saving = true;
    const c = cards[i];
    try {
      await api.post(`/api/review/${c.id}`, { rating: n });
    } catch (e) {
      toast(`Could not save: ${(e as Error).message}`, "error");
      return;
    } finally {
      saving = false;
    }
    done++;
    i++;
    ambience.update({ reviewed: ambience.state.reviewed + 1 });
    shown = false;
    draw();
  };
  const onKey = (e: KeyboardEvent) => {
    if (document.querySelector(".modal-back")) return;
    if (e.key === " " && !shown && i < cards.length) {
      e.preventDefault();
      reveal();
    } else if (shown && !e.ctrlKey && !e.metaKey && !e.altKey && /^[1-4]$/.test(e.key)) rate(Number(e.key));
  };
  document.addEventListener("keydown", onKey);
  draw();
  return () => document.removeEventListener("keydown", onKey);
}
