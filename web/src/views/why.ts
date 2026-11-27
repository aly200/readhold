// "Why did it say this?" (milestone 4.2 of docs/ai/PLAN.md, section 6.8). A link beside every AI label opens what
// is behind a result: each model call (model, prompt version, time, tokens, retries, the checks the guards ran),
// the sources each call was sent (named, with how much of each; never their text again), the prompt itself, word
// for word, and how many quotes were checked. It reads the AI log on this computer and calls no model.
// Text only: h() sets textContent.
import { api } from "../api";
import { removeItem } from "../trash";
import { clear, h, type ModalHandle, modal } from "../util";

interface Source {
  anchor: string; trust: string; chars: number; cut: boolean; kind: string; title: string;
  document_id?: string; document_title?: string; section_title?: string; sentence?: number; note_id?: string; idea_id?: string;
}
interface Call {
  id: string; task: string; provider: string; model: string; prompt_version: string; latency_ms: number; tokens_in: number; tokens_out: number;
  attempts: number; outcome: string; error: string; created_at: string; output_preview: string;
  checks: Record<string, unknown>; sources: Source[]; sources_recorded: boolean;
}
interface Why {
  id: string; feature: string; created_at: string; provider: string; model: string; prompt_version: string; status: string;
  checked: { verified: number; unchecked: number }; calls: Call[]; log_gone: boolean; prompts: Record<string, string>;
}

const FEATURE: Record<string, string> = {
  resume: "Where you left off", explain: "Explain", digest: "Digest", ask: "Ask this document", library: "Ask your library",
  notes: "Study notes", plan: "Reading plan", brainstorm: "Brainstorm", organize: "Organize", tidy: "Tidy", chat: "Plan chat", notechat: "Note chat",
};
const TASK: Record<string, string> = { digest_map: "summarise one part", digest: "combine the parts", brainstorm: "write ideas", brainstorm_critic: "group and rank the ideas" };
const TRUST: Record<string, string> = { imported: "from a document", yours: "your own writing", model: "the model's own text" };
const CHECKS: [string, (v: unknown) => string | null][] = [
  ["fenced", (v) => `${v} source${v === 1 ? "" : "s"} fenced as material to read, never as orders`],
  ["trimmed", (v) => (v ? "some text was cut to fit the size limit" : null)],
  ["left_out", (v) => (v ? `${v} source${v === 1 ? "" : "s"} left out: over the size limit` : null)],
  ["flagged", (v) => (Array.isArray(v) && v.length ? `text that reads like orders to a model was found (${v.join(", ")}); it stayed fenced` : null)],
  ["links_removed", (v) => (v ? `${v} address${v === 1 ? "" : "es"} the model wrote shown as words, never opened` : null)],
  ["private_left_out", (v) => (v ? `${v} item${v === 1 ? "" : "s"} left out because ${v === 1 ? "it stays" : "they stay"} on this computer (#private, or not tagged #cloud)` : null)],
  ["secrets_redacted", (v) => (typeof v === "number" ? `${v} secret${v === 1 ? "" : "s"} removed before sending` : null)],
];

const OUTCOME: Record<string, string> = {
  ok: "answered", invalid: "failed: the answer did not have the expected shape", timeout: "failed: took too long", cancelled: "stopped",
  error: "failed: the model server gave an error", budget: "not sent: today's budget was used up", no_key: "not sent: no API key", setup: "not sent: AI not set up",
};
const STATUS: Record<string, string> = {
  verified: "Every quote it shows was found word for word in the passage it names.",
  partly: "Some quotes were found word for word in their passage; the others were not, and are marked or left out.",
  unverified: "None of its quotes was found in the passage it names: treat it as a guess.",
  not_found: "It said your sources do not hold the answer.",
};
const when = (iso: string) => new Date(iso).toLocaleString();
const where = (s: Source): string | null =>
  s.kind === "document" || s.kind === "hlnote" ? `#/read/${s.document_id}?s=${s.sentence ?? 0}` : s.kind === "note" ? `#/notes/${s.note_id}` : s.kind === "idea" ? `#/think/idea/${s.idea_id}` : null;

function sourceRow(s: Source, close: () => void): HTMLElement {
  const name = s.kind === "document" ? `${s.document_title} · ${s.section_title}` : s.kind === "note" ? `Your note “${s.title}”` : s.kind === "idea" ? `Your idea “${s.title}”` : s.title || s.anchor;
  const href = where(s);
  return h("li", null, href ? h("a", { href, onclick: close }, name) : h("span", null, name),
    h("span", { class: "muted small" }, ` · ${TRUST[s.trust] ?? s.trust} · ${s.chars.toLocaleString()} characters sent${s.cut ? " (cut)" : ""}`));
}

function callBox(c: Call, i: number, n: number, close: () => void): HTMLElement {
  const notes = CHECKS.map(([k, say]) => (k in c.checks ? say(c.checks[k]) : null)).filter((x): x is string => !!x);
  const more = typeof c.checks.sources_more === "number" ? c.checks.sources_more : 0;
  return h("details", { class: "why-call", open: n === 1 },
    h("summary", null, `${n > 1 ? `Call ${i + 1} of ${n}: ` : ""}${TASK[c.task] ?? FEATURE[c.task] ?? c.task} · ${OUTCOME[c.outcome] ?? c.outcome}`),
    h("dl", { class: "why-facts" },
      h("dt", null, "Model"), h("dd", null, `${c.model || "?"} (${c.provider === "local" ? "on this computer" : c.provider})`),
      h("dt", null, "Prompt"), h("dd", null, c.prompt_version || "none"),
      h("dt", null, "When"), h("dd", null, `${when(c.created_at)}, ${(c.latency_ms / 1000).toFixed(1)} s${c.attempts > 1 ? `, ${c.attempts} tries` : ""}`),
      h("dt", null, "Tokens"), h("dd", null, `${c.tokens_in.toLocaleString()} in, ${c.tokens_out.toLocaleString()} out`),
      c.error ? h("dt", null, "Error") : null, c.error ? h("dd", null, c.error) : null),
    notes.length ? h("ul", { class: "why-checks" }, notes.map((x) => h("li", null, x))) : null,
    h("h4", null, c.sources_recorded ? `What it was sent (${c.sources.length + more})` : "What it was sent"),
    more ? h("p", { class: "muted small" }, `The first ${c.sources.length} are named here; ${more} more ${more === 1 ? "was" : "were"} sent too.`) : null,
    !c.sources_recorded ? h("p", { class: "muted small" }, "Not recorded for this call: it was made before Readhold kept the list of sources. Ask again to see it.")
      : c.sources.length ? h("ul", { class: "why-sources" }, c.sources.map((s) => sourceRow(s, close))) : h("p", { class: "muted small" }, "Only the instruction and your question."),
    h("h4", null, "The start of what came back"),
    h("p", { class: "why-preview" }, c.output_preview || "(nothing kept)"));
}

/** The panel for one result. */
export function whyDialog(resultId: string): Promise<unknown> {
  let handle: ModalHandle;
  // a link to a passage leaves this page: every open dialog goes (the one this panel was opened from, too)
  const close = () => {
    handle.close(null);
    for (let i = 0; i < 5 && document.querySelector(".modal-back"); i++) document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  };
  const body = h("div", { class: "stack why" }, h("p", { class: "muted small", role: "status" }, "Reading the AI log…"));
  void api.get<Why>(`/api/ai/why/${resultId}`).then((w) => {
    clear(body);
    const checked = w.checked.verified + w.checked.unchecked;
    body.append(h("div", { class: "stack" },
      h("p", null, `${FEATURE[w.feature] ?? w.feature}, ${when(w.created_at)}. Model: ${w.model || "?"} (${w.provider === "local" ? "on this computer" : w.provider}). Prompt: ${w.prompt_version}.`),
      STATUS[w.status] ? h("p", null, STATUS[w.status]) : null,
      checked ? h("p", { class: "muted small" }, `Of the parts it shows with a mark, ${w.checked.verified} of ${checked} ${checked === 1 ? "part rests" : "parts rest"} on a quote found word for word in the passage it names${w.checked.unchecked ? `; ${w.checked.unchecked} ${w.checked.unchecked === 1 ? "does" : "do"} not, so ${w.checked.unchecked === 1 ? "it is" : "they are"} shown as unchecked` : ""}.`) : null,
      w.log_gone ? h("p", { class: "muted small" }, w.calls.length ? "The log of some of its calls is gone: Readhold keeps it as long as Settings → AI says (30 days at most)." : "The log of its calls is gone: Readhold keeps it as long as Settings → AI says (30 days at most). What the result itself recorded is above.") : null,
      ...w.calls.map((c, i) => callBox(c, i, w.calls.length, close)),
      ...Object.entries(w.prompts).map(([v, text]) => h("details", { class: "why-prompt" }, h("summary", null, `The prompt ${v}, word for word`), h("pre", null, text))),
      h("p", { class: "muted small" }, "This comes from the AI log on this computer. Opening it sends nothing anywhere.")));
  }, (e: Error) => {
    clear(body);
    body.append(h("p", { class: "muted small" }, `Not available: ${e.message}`));
  });
  // milestone 5.1: this one result can be deleted (with Undo). Its box keeps showing it until the page is drawn again.
  const said = h("p", { class: "why-deleted", role: "status", hidden: true });
  const del: HTMLButtonElement = h("button", { type: "button", class: "ghost", title: "Remove this one result. Asking again makes a new one.", onclick: () => void removeItem("ai_result", resultId, "Deleted this AI result.", {
    gone: () => {
      del.disabled = true;
      said.hidden = false;
      said.textContent = "Deleted. Close this panel and reload the page (or open it again): the box it came from will no longer show it. Asking again makes a new one.";
    },
    back: () => {
      del.disabled = false;
      said.textContent = "It is back.";
    },
  }) }, "Delete this result");
  return modal("Why did it say this?", h("div", { class: "stack" }, body, said, h("div", { class: "row end" }, del, h("button", { type: "button", autofocus: true, onclick: () => handle.close(null) }, "Close"))), { wide: true, onOpen: (m) => (handle = m) }); // Close has the focus, never Delete
}

/** The link beside an AI label. Nothing when the result has no id (nothing was asked of a model). */
export function whyLink(resultId: string | undefined | null): HTMLElement | null {
  return resultId ? h("button", { type: "button", class: "link small why-link", onclick: () => void whyDialog(resultId) }, "Why did it say this?") : null;
}
