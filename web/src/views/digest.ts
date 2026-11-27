// The digest of a document (milestone 1.5 of docs/ai/PLAN.md): its shape before its detail.
// The facts need no model: the outline, the words and the reading time at your speed. With AI switched on there is
// one button; nothing is sent until you press it. The digest is written in the background, part by part, and the
// dialog shows how far it got. Close the dialog and it keeps going; Stop ends it, and the next time it continues.
// Everything a model wrote is drawn as text only (h() sets textContent), and is labelled as the model's.
import { whyLink } from "./why";
import { api } from "../api";
import { clear, h, type ModalHandle, modal } from "../util";
import type { Reader } from "./reader";

interface OutlineItem { id: string; title: string; level: number; words: number; sentence: number; skipped: boolean }
interface Facts { outline: OutlineItem[]; words: number; wpm: number; minutes: number }
interface Part { sentence: number; titles: string[]; summary: string; failed: boolean }
interface Idea { text: string; verified: boolean; quote?: string; sentence?: number }
interface Digest {
  id: string;
  summary: string;
  key_ideas: Idea[];
  keywords: string[];
  difficulty: "introductory" | "intermediate" | "advanced";
  parts: Part[];
  skipped_parts: number;
  status: "verified" | "partly" | "unverified";
  links: string[];
  provider: string;
  warning: string;
}
interface Job { id: string; state: "running" | "done" | "failed" | "cancelled"; step: "parts" | "combining"; done: number; total: number; message: string }
interface DigestData { facts: Facts; ai: { mode: "off" | "local" | "cloud" }; digest: Digest | null; job: Job | null }

const STATUS: Record<Digest["status"], string> = {
  verified: "Each key idea quotes words that are in the document. Check that the idea follows from them.",
  partly: "Some key ideas quote words that are in the document; the others name no passage.",
  unverified: "No key idea quotes a passage that is in the document. Treat them as a guess.",
};

function drawDigest(r: Reader, d: Digest, close: () => void): HTMLElement {
  const go = (ord: number) => () => (close(), r.jumpTo(ord));
  return h("div", { class: "ai-text digest" },
    h("div", { class: "ai-text-label" }, `Written by the AI model (${d.provider === "local" ? "on this computer" : d.provider}). ${STATUS[d.status]}`),
    whyLink(d.id),
    h("p", null, d.summary),
    d.key_ideas.length ? h("ul", null, d.key_ideas.map((x) => h("li", null, x.text,
      x.verified && x.quote && x.sentence !== undefined
        ? h("button", { type: "button", class: "link resume-quote", title: "Go to this passage", onclick: go(x.sentence) }, `✓ “${x.quote}”`)
        : h("div", { class: "resume-quote unproven" }, "no passage named")))) : null,
    d.keywords.length ? h("p", { class: "digest-keys" }, h("strong", null, "Keywords: "), d.keywords.join(" · ")) : null,
    h("p", { class: "muted small" }, `The model's guess at the level: ${d.difficulty}.`),
    d.parts.length > 1 ? h("details", { class: "digest-parts" },
      h("summary", null, `Part by part (${d.parts.length})${d.skipped_parts ? `, ${d.skipped_parts} without a summary` : ""}`),
      h("ol", null, d.parts.map((p) => h("li", null,
        h("button", { type: "button", class: "link", onclick: go(p.sentence) }, p.titles.join(", ")),
        h("div", { class: p.failed ? "muted small" : "small" }, p.failed ? "The model could not summarise this part." : p.summary))))) : null,
    d.links.length ? h("div", { class: "ai-text-links" }, "The model wrote addresses. Readhold does not open them: ", d.links.join(" · ")) : null,
    d.warning ? h("div", { class: "ai-text-links" }, d.warning) : null);
}

function drawFacts(r: Reader, f: Facts, close: () => void): HTMLElement {
  return h("div", { class: "digest-facts" },
    h("p", null, `${f.words.toLocaleString()} words · about ${f.minutes} min at ${f.wpm} words a minute`),
    h("ol", { class: "digest-outline" }, f.outline.map((s) =>
      h("li", { class: `lvl-${Math.min(s.level, 3)} ${s.skipped ? "skipped" : ""}` },
        h("button", { type: "button", class: "link", onclick: () => (close(), r.jumpTo(s.sentence)) }, s.title),
        h("span", { class: "muted small" }, s.skipped ? " · left out of the digest" : ` · ${s.words} words`)))));
}

export async function digestDialog(r: Reader): Promise<unknown> {
  r.pacer.pause(false);
  const id = r.doc.id;
  let data: DigestData;
  try {
    data = await api.get<DigestData>(`/api/documents/${id}/digest`);
  } catch (e) {
    return modal("Digest", h("p", { class: "import-warning" }, `The digest could not be loaded: ${(e as Error).message}`));
  }
  let handle: ModalHandle;
  let timer = 0;
  const close = () => handle.close(null);
  const ai = h("div", { class: "digest-ai", "aria-live": "polite" });
  const stopPolling = () => window.clearTimeout(timer);

  const draw = (d: DigestData) => {
    clear(ai);
    if (d.ai.mode === "off") {
      ai.append(h("p", { class: "muted small" }, "With AI switched on in Settings, a model can write a summary and the key ideas here."));
      return;
    }
    const job = d.job;
    if (job && job.state === "running") {
      ai.append(
        h("p", { role: "status" }, job.step === "combining" ? "Combining the parts…" : `Reading part ${Math.min(job.done + 1, job.total)} of ${job.total}…`),
        h("progress", { max: job.total + 1, value: job.done + (job.step === "combining" ? 0.5 : 0) }),
        h("p", { class: "muted small" }, "You can close this and keep reading; it goes on in the background."),
        h("button", { type: "button", class: "btn small", onclick: async () => (await api.post(`/api/documents/${id}/digest/cancel`), void poll()) }, "Stop"));
      timer = window.setTimeout(() => void poll(), 800);
      return;
    }
    if (d.digest) {
      ai.append(drawDigest(r, d.digest, close), h("button", { type: "button", class: "link small", onclick: () => void ask(true) }, "Ask again"));
      return;
    }
    if (job?.state === "failed") ai.append(h("p", { class: "muted small" }, `No digest: ${job.message}`));
    if (job?.state === "cancelled") ai.append(h("p", { class: "muted small" }, `Stopped after ${job.done} of ${job.total} parts. The parts already read are kept; the next digest goes on from there.`));
    ai.append(
      h("button", { type: "button", class: "btn small", onclick: () => void ask(false) }, job && job.state !== "done" ? "Go on with the digest" : "Digest with AI"),
      h("span", { class: "muted small" }, d.ai.mode === "cloud"
        ? " Sends the document to your cloud model one part at a time (references left out). Secrets are removed first."
        : " Uses the model on this computer, one part at a time."));
  };
  const poll = async () => {
    stopPolling();
    if (!ai.isConnected) return;
    try {
      data = await api.get<DigestData>(`/api/documents/${id}/digest`);
      draw(data);
    } catch {
      timer = window.setTimeout(() => void poll(), 2000);
    }
  };
  const ask = async (fresh: boolean) => {
    try {
      const res = await api.post<{ job: Job | null; digest: Digest | null }>(`/api/documents/${id}/digest`, { fresh });
      data = { ...data, job: res.job, digest: res.digest ?? (fresh ? null : data.digest) };
      if (res.digest) draw(data);
      else void poll();
    } catch (e) {
      clear(ai);
      ai.append(h("p", { class: "muted small" }, `No digest: ${(e as Error).message}`));
    }
  };
  draw(data);
  const done = modal("Digest", h("div", { class: "stack" }, h("div", { class: "muted" }, r.doc.title), drawFacts(r, data.facts, close), ai,
    h("div", { class: "row end" }, h("button", { type: "button", onclick: close }, "Close"))), { wide: true, onOpen: (m) => (handle = m) });
  void done.then(stopPolling);
  return done;
}
