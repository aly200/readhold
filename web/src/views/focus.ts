// Focus: one step on the screen, a gentle time box, and three honest exits —
// Done (what did it produce?), Stuck (a small protocol, not more willpower), and Park a thought.
import { ambience } from "../ambience";
import { api, save } from "../api";
import { type Feel, feelRow } from "../feel";
import { mathText } from "../math";
import { state } from "../state";
import type { Quest, QuestStep, SessionInfo, Today } from "../types";
import { askText, fmtClock, fmtMinutes, h, isTyping, type ModalHandle, modal, toast } from "../util";
import { stepFor } from "./today";

export async function focusView(root: HTMLElement, id: string, params: URLSearchParams): Promise<() => void> {
  const side = id === "side";
  let step: QuestStep | null = null;
  let quest: Quest | null = null;
  if (!side) {
    const t = await api.get<Today>("/api/today");
    quest = t.quest;
    step = quest?.steps.find((s) => s.id === id) ?? null;
    if (!step) {
      root.append(h("section", { class: "focus" }, h("p", null, "That step isn't in your active goal anymore."), h("a", { class: "btn", href: "#/home" }, "Back to Today")));
      return () => undefined;
    }
  }
  const energy = state.energy;
  const title = side ? params.get("text") || "Side goal" : stepFor(step!, energy);
  const minutes = side ? Number(params.get("min")) || 15 : energy === "low" ? Math.max(5, Math.round(step!.minutes / 3)) : step!.minutes;
  const qIdx = quest && step ? quest.questions.findIndex((q) => q.id === step!.question_id) : -1;

  const info = await api.post<SessionInfo>("/api/sessions", { energy, time_box_min: minutes, quest_id: side ? null : quest?.id, step_id: side ? null : step?.id, question: title });
  let focusedMs = 0;
  let running = true;
  let last = performance.now();
  let output = "";
  let ended = false;
  let boxNoticed = false;
  ambience.update({ mode: "reading", session: 0 });

  const clock = h("div", { class: "focus-clock", "aria-live": "off" }, fmtClock(minutes * 60_000));
  const ring = h("div", { class: "focus-ring" }, clock);
  const pauseBtn = h("button", { class: "btn", onclick: () => togglePause() }, "Pause");
  const tick = window.setInterval(() => {
    const t = performance.now();
    const dt = Math.min(t - last, 5000);
    last = t;
    if (running && document.visibilityState === "visible") {
      focusedMs += dt;
      ambience.state.session = focusedMs / 1000;
    }
    const left = minutes * 60_000 - focusedMs;
    clock.textContent = left >= 0 ? fmtClock(left) : `+${fmtClock(-left)}`;
    ring.style.setProperty("--p", String(Math.min(1, focusedMs / (minutes * 60_000))));
    if (left <= 0 && !boxNoticed) {
      boxNoticed = true;
      ring.classList.add("over");
      toast("Time box done. Finish the thought, then Done — or keep going if it flows.", "ok", 7000);
    }
  }, 500);
  const beat = window.setInterval(() => save("patch", `/api/sessions/${info.id}`, { focused_ms: Math.round(focusedMs) }), 15_000);

  const togglePause = () => {
    running = !running;
    pauseBtn.textContent = running ? "Pause" : "Resume";
    ambience.update({ mode: running ? "reading" : "break" });
  };

  const finish = async (how: "done" | "stop") => {
    if (ended) return;
    const feel = feelRow();
    let feelValue: Feel | "" = "";
    if (how === "done") {
      const out = h("input", { type: "text", autofocus: true, placeholder: "Wrote the 3-line explanation of attention", "aria-label": "What it produced" });
      let hm: ModalHandle;
      const go = () => hm.close("ok");
      out.addEventListener("keydown", (e) => e.key === "Enter" && go());
      const res = await modal(
        "Done",
        h(
          "div",
          { class: "stack" },
          h("label", { class: "field" }, h("span", null, "What did it produce? One line: an answer, a decision, a file, a fact."), out),
          feel.el,
          h("div", { class: "row end" }, h("button", { onclick: () => hm.close(null) }, "Cancel"), h("button", { class: "primary", onclick: go }, "Save")),
        ),
        { onOpen: (m) => (hm = m) },
      );
      if (res !== "ok") return;
      output = out.value.trim() || "done";
      feelValue = feel.pick();
      if (step) await api.patch(`/api/quest-steps/${step.id}`, { done: true, output });
      ambience.moment();
    } else if (focusedMs >= 3 * 60_000) {
      // a real stretch of work, even unfinished: one optional tap for the energy log
      let hm: ModalHandle;
      const res = await modal(
        "Stop here",
        h("div", { class: "stack" }, feel.el, h("div", { class: "row end" }, h("button", { onclick: () => hm.close(null) }, "Keep going"), h("button", { class: "primary", onclick: () => hm.close("ok") }, "Stop"))),
        { onOpen: (m) => (hm = m) },
      );
      if (res !== "ok") return;
      feelValue = feel.pick();
    }
    ended = true;
    await api.patch(`/api/sessions/${info.id}`, { focused_ms: Math.round(focusedMs), output, ended: true, ...(feelValue ? { feel: feelValue } : {}) });
    const took = focusedMs >= 60_000 ? ` in ${fmtMinutes(focusedMs)}` : "";
    toast(how === "done" ? `Done${took}. That's real output.` : took ? `Stopped after ${fmtMinutes(focusedMs)}.` : "Stopped.", "ok");
    location.hash = "#/home";
  };

  const stuck = async () => {
    let handle: ModalHandle;
    const choice = await modal(
      "Stuck? Change the method, not the effort",
      h(
        "div",
        { class: "stack" },
        h(
          "ol",
          { class: "stuck-list" },
          h("li", null, h("strong", null, "Write the problem as one question. "), "Often the question itself shows the next move."),
          h("li", null, h("strong", null, "Try two other ways. "), "A smaller version, a worked example, drawing it, explaining it aloud."),
          h("li", null, h("strong", null, "Still stuck after 10 minutes? "), "Ask someone, or park it as a question and move to the next step."),
        ),
        h("div", { class: "row end" }, h("button", { onclick: () => handle.close("park") }, "Park as a question"), h("button", { class: "primary", onclick: () => handle.close("back") }, "Back to it")),
      ),
      { onOpen: (m) => (handle = m) },
    );
    if (choice !== "park") return;
    const q = await askText("Park as a question", "What exactly is blocking you?", "", { placeholder: "Why does scaling by √d_k help?" });
    if (q) {
      await save("post", "/api/ideas", { text: `Stuck: ${q}` });
      toast("Parked in Ideas.", "ok");
    }
  };

  const parkThought = async () => {
    const text = await askText("Park a thought", "Out of your head, into the inbox. Back to the step.", "", { placeholder: "Look up layer norm later" });
    if (text) {
      await save("post", "/api/ideas", { text });
      toast("Parked.", "ok", 1800);
    }
  };

  const onKey = (e: KeyboardEvent) => {
    if (isTyping(e)) return;
    if (e.key === " ") (e.preventDefault(), togglePause());
    else if (e.key.toLowerCase() === "p") (e.preventDefault(), void parkThought());
    else if (e.key.toLowerCase() === "d") (e.preventDefault(), void finish("done"));
  };
  document.addEventListener("keydown", onKey);

  root.append(
    h(
      "section",
      { class: "focus" },
      h("div", { class: "isle focus-head" },
      h("div", { class: "kicker" }, side ? `Side goal · ${minutes}-minute box` : `${quest!.title}${qIdx >= 0 ? ` · Q${qIdx + 1}` : ""}`),
      h("h1", { class: "focus-title" }, mathText(title)),
      !side && step && energy !== "medium" && step.title !== title ? h("p", { class: "muted small" }, `${energy === "low" ? "Low" : "High"}-energy version of: ${step.title}`) : null),
      ring,
      h(
        "div",
        { class: "focus-actions" },
        side ? null : h("button", { class: "btn primary", onclick: () => finish("done") }, "Done (D)"),
        pauseBtn,
        h("button", { class: "btn", onclick: stuck }, "Stuck?"),
        h("button", { class: "btn", onclick: parkThought }, "Park a thought (P)"),
        h("button", { class: "btn ghost", onclick: () => finish("stop") }, side ? "Back to the main goal" : "Stop"),
      ),
    ),
  );

  return () => {
    clearInterval(tick);
    clearInterval(beat);
    document.removeEventListener("keydown", onKey);
    if (!ended) void save("patch", `/api/sessions/${info.id}`, { focused_ms: Math.round(focusedMs), ended: true });
    ambience.update({ mode: "idle" });
  };
}
