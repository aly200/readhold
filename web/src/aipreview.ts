// "Show what will be sent" (milestone 4.4 of docs/ai/PLAN.md, section 6.4). With the setting on, in cloud mode, the
// server stops the first call of a request and answers 428 with the exact text; this dialog shows it. Send repeats
// the same request with a one-time approval for that text; Cancel sends nothing. Text only: h() sets textContent.
import { h, type ModalHandle, modal } from "./util";

export interface Preview { token: string; task: string; provider: string; system: string; user: string; note: string }

const PROVIDER: Record<string, string> = { anthropic: "Anthropic (Claude)", openai: "OpenAI" };
/** Where the text goes: a cloud provider, or a model server on another computer ("remote:<host>"). */
const where = (p: string) => (p.startsWith("remote:") ? `the model server at ${p.slice(7)} (another computer)` : PROVIDER[p] ?? p);

/** True when you choose to send it. */
export function previewDialog(p: Preview): Promise<boolean> {
  let handle: ModalHandle;
  const done = (v: boolean) => () => handle.close(v);
  const size = p.system.length + p.user.length;
  const body = h("div", { class: "stack ai-preview" },
    h("p", null, `This is what will be sent to ${where(p.provider)}, word for word (${size.toLocaleString()} characters). Nothing has been sent yet.`),
    h("p", { class: "muted small" }, p.note),
    h("details", null, h("summary", null, "The instructions for the model"), h("pre", null, p.system)),
    h("h3", null, "Your text and question"),
    h("pre", null, p.user),
    h("p", { class: "muted small" }, "Secrets found in the text are already replaced by [redacted]. Items tagged #private are left out. You can switch this check off in Settings → AI."),
    h("div", { class: "row end" }, h("button", { type: "button", onclick: done(false) }, "Cancel"), h("button", { type: "button", class: "btn primary", onclick: done(true) }, "Send")));
  return modal("Send this off this computer?", body, { wide: true, onOpen: (m) => (handle = m) }).then((v) => v === true);
}
