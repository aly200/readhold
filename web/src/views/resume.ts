// "Where you left off": shown in the Start a session dialog when you come back to a document.
// The facts (when, which sections, what you said comes next) need no model. With AI switched on there is one
// button that asks the model for a three-line recap; nothing is sent until you press it.
// Everything a model wrote is drawn as text only (h() sets textContent), and is labelled as the model's.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, fmtMinutes, h } from "../util";

interface RecapLine {
  text: string;
  verified: boolean;
  quote?: string;
  sentence?: number;
}
interface Brief {
  id: string;
  recap: RecapLine[];
  point: string;
  next: string;
  status: "verified" | "partly" | "unverified";
  links: string[];
  provider: string;
  model: string;
  warning: string;
}
interface ResumeData {
  session: {
    ended_at: string;
    focused_ms: number;
    question: string;
    next_step: string;
    sections: { id: string; title: string; sentences: number }[];
    highlights: { id: string }[];
  } | null;
  here: { section_title: string; sentence: number } | null;
  ai: { mode: "off" | "local" | "cloud" };
  brief: Brief | null;
}

// A ✓ means the quoted words are in the text you read. It does not mean the line follows from them: that is for you to judge.
const STATUS: Record<Brief["status"], string> = {
  verified: "Each line quotes words that are in the text. Check that the line follows from them.",
  partly: "Some lines quote words that are in the text; the others name no passage.",
  unverified: "No line quotes a passage that is in the text. Treat this as a guess.",
};

function when(iso: string): string {
  const d = new Date(iso);
  const midnight = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((midnight(new Date()) - midnight(d)) / 86_400_000); // by the calendar: last night is yesterday
  const day = days <= 0 ? "Today" : days === 1 ? "Yesterday" : days < 7 ? `${days} days ago` : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return day;
}

function drawBrief(b: Brief): HTMLElement {
  return h("div", { class: "ai-text resume-brief" },
    h("div", { class: "ai-text-label" }, `Written by the AI model (${b.provider === "local" ? "on this computer" : b.provider}). ${STATUS[b.status]}`),
    whyLink(b.id),
    b.recap.length ? null : h("p", null, "The model found too little in what you read to write a recap."),
    h("ul", null, b.recap.map((line) =>
      h("li", null, line.text,
        line.verified && line.quote ? h("div", { class: "resume-quote", title: "These words are in the text you read" }, `✓ “${line.quote}”`) : h("div", { class: "resume-quote unproven" }, "no passage named")))),
    b.point ? h("p", null, h("strong", null, "This section: "), b.point) : null,
    b.next ? h("p", null, h("strong", null, "Next: "), b.next) : null,
    b.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", b.links.join(" · ")) : null,
    b.warning ? h("div", { class: "ai-text-links" }, b.warning) : null);
}

/** A place for the block that fills itself in: the dialog opens at once and never waits for it. */
export function resumeSlot(docId: string): HTMLElement {
  const slot = h("div", { class: "resume-slot" });
  void resumeBlock(docId).then((box) => box && slot.isConnected !== false && slot.append(box));
  return slot;
}

/** The block for the dialog, or null when this document has no finished reading session yet. */
export async function resumeBlock(docId: string): Promise<HTMLElement | null> {
  let data: ResumeData;
  try {
    data = await api.get<ResumeData>(`/api/documents/${docId}/resume`);
  } catch {
    return null; // the dialog works without it
  }
  const s = data.session;
  if (!s) return null;
  const sections = s.sections.map((x) => x.title);
  const read = sections.length ? (sections.length > 3 ? `${sections.slice(0, 3).join(", ")} and ${sections.length - 3} more` : sections.join(", ")) : "";
  const box = h("div", { class: "resume-box" },
    h("div", { class: "kicker" }, "Where you left off"),
    h("p", { class: "resume-facts" },
      `${when(s.ended_at)}${s.focused_ms >= 60_000 ? `, ${fmtMinutes(s.focused_ms)} of reading` : ""}`,
      read ? `. You read: ${read}` : "",
      s.highlights.length ? `. ${s.highlights.length} passage${s.highlights.length === 1 ? "" : "s"} marked` : "",
      data.here ? `. You are in “${data.here.section_title}”.` : "."),
    s.next_step ? h("p", { class: "resume-next" }, h("strong", null, "You said comes next: "), s.next_step) : null);
  if (data.ai.mode === "off") return box;

  const slot = h("div", { class: "resume-ai" });
  box.append(slot);
  const ask = async (fresh: boolean) => {
    clear(slot);
    slot.append(h("p", { class: "muted small", role: "status" }, "Asking the model… You can start reading; this does not block anything."));
    try {
      const r = await api.post<{ brief: Brief }>(`/api/documents/${docId}/resume/brief`, { fresh });
      show(r.brief);
    } catch (e) {
      clear(slot);
      if (shown) slot.append(drawBrief(shown)); // a failed "Ask again" leaves the recap you had
      slot.append(h("p", { class: "muted small" }, `No ${shown ? "new " : ""}recap: ${(e as Error).message}`), button(!!shown, "Try again"));
    }
  };
  const button = (fresh: boolean, label: string): HTMLElement =>
    h("button", { type: "button", class: fresh ? "link small" : "btn small", onclick: () => void ask(fresh) }, label);
  let shown: Brief | null = null;
  const show = (b: Brief) => {
    shown = b;
    clear(slot);
    slot.append(drawBrief(b), button(true, "Ask again"));
  };
  if (data.brief) show(data.brief);
  else {
    slot.append(
      button(false, "Recap with AI"),
      h("span", { class: "muted small" }, data.ai.mode === "cloud"
        ? " Sends the passages you read last time to your cloud model."
        : " Uses the model on this computer."));
  }
  return box;
}
