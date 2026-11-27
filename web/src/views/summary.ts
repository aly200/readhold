// Auto summary sheet: built from your claims, evidence, answers, glossary and open confusions.
import { api } from "../api";
import type { Highlight } from "../types";
import { mathText } from "../math";
import { h, toast } from "../util";
import { connectedCard } from "../related";
import type { Quest } from "../types";

interface Summary {
  document: { id: string; title: string; source: string | null; why: string; explain_text: string; status: string; critique: string; reproduce: string };
  claims: (Highlight & { evidence: Highlight[] })[];
  orphan_evidence: Highlight[];
  questions: { id: string; text: string; answer: string; source_sentence: number | null }[];
  terms: { term: string; guess: string; definition: string; sentence: number | null }[];
  definitions: Highlight[];
  confusions: Highlight[];
  ideas: Highlight[];
  notes: { sentence: number; text: string }[];
  predictions: { title: string; prediction: string; prediction_check: string }[];
  acronyms: Record<string, string>;
  progress: { read: number; total: number; ratio: number };
}

export async function summaryView(root: HTMLElement, docId: string): Promise<void> {
  const s = await api.get<Summary>(`/api/documents/${docId}/summary`);
  const d = s.document;
  const go = (ord: number | null, text: string) => (ord === null ? h("span", null, mathText(text)) : h("a", { href: `#/read/${d.id}?s=${ord}`, title: "Open at this sentence" }, mathText(text)));
  const section = (title: string, kids: unknown[]) => (kids.length ? h("section", null, h("h2", null, title), ...(kids as Node[])) : null);
  root.append(
    h(
      "article",
      { class: "summary" },
      h("header", { class: "isle page-head" },
      h("div", { class: "row between" }, h("a", { class: "btn ghost", href: `#/read/${d.id}` }, "← Back to reading"), h("button", { class: "btn", onclick: exportMd }, "Export Markdown")),
      h("h1", null, d.title),
      h("p", { class: "muted" }, `${s.progress.read} of ${s.progress.total} key sentences read · ${s.questions.filter((q) => q.answer).length}/${s.questions.length} questions answered`, d.source ? ` · ${d.source}` : ""),
      d.why ? h("p", null, h("strong", null, "Why I read this: "), d.why) : null),
      section("In my words", d.explain_text ? [h("p", { class: "explain" }, d.explain_text)] : [h("p", { class: "muted" }, "Not written yet — the explain-it box at the end of the document fills this.")]),
      section("Main points", [
        ...s.claims.map((c) => h("div", { class: "claim" }, h("p", null, h("span", { class: "tag hl-claim" }, "Claim"), " ", go(c.sentence, c.text), c.note ? h("em", null, ` — ${c.note}`) : null), c.evidence.map((e) => h("p", { class: "evidence" }, h("span", { class: "tag hl-evidence" }, "Evidence"), " ", go(e.sentence, e.text))))),
        ...s.orphan_evidence.map((e) => h("p", { class: "evidence" }, h("span", { class: "tag hl-evidence" }, "Evidence"), " ", go(e.sentence, e.text))),
      ]),
      section(
        "Questions",
        s.questions.map((q) => h("div", { class: "qa" }, h("p", null, h("strong", null, q.text)), h("p", null, q.answer || h("em", { class: "muted" }, "not answered yet")))),
      ),
      section("Glossary", [
        ...s.terms.map((t) => h("p", null, h("strong", null, t.term), ": ", t.definition || h("em", null, `guess: ${t.guess}`))),
        ...s.definitions.map((x) => h("p", null, h("span", { class: "tag hl-definition" }, "Definition"), " ", go(x.sentence, x.text))),
        ...Object.entries(s.acronyms).map(([k, v]) => h("p", null, h("strong", null, k), `: ${v}`)),
      ]),
      section("Predictions", s.predictions.map((p) => h("p", null, h("strong", null, `${p.title}: `), p.prediction, p.prediction_check ? h("span", { class: "muted" }, ` → ${p.prediction_check}`) : null))),
      section("Still confusing", s.confusions.map((c) => h("p", null, h("span", { class: "tag hl-confusing" }, "Confusing"), " ", go(c.sentence, c.text)))),
      section("Ideas", s.ideas.map((i) => h("p", null, h("span", { class: "tag hl-idea" }, "Idea"), " ", go(i.sentence, i.note || i.text)))),
      section("Margin notes", s.notes.map((n) => h("p", null, go(n.sentence, n.text)))),
      h("section", null, connectedCard("document", d.id, d.title)),
      critiqueBox(),
    ),
  );

  /** After the three passes: a one-paragraph critique and one result worth reproducing. */
  function critiqueBox(): HTMLElement {
    const critique = h("textarea", { rows: 5, placeholder: "Strengths, weaknesses, and what you'd test next. One honest paragraph.", "aria-label": "Critique" }, d.critique ?? "");
    const reproduce = h("input", { type: "text", value: d.reproduce ?? "", placeholder: "One result you'd reproduce, e.g. the BLEU gain from multi-head attention", "aria-label": "Result to reproduce" });
    const saved = h("span", { class: "muted small" });
    const persist = async (field: "critique" | "reproduce", value: string) => {
      await api.patch(`/api/documents/${d.id}`, { [field]: value });
      d[field] = value;
      saved.textContent = "Saved";
      setTimeout(() => (saved.textContent = ""), 1500);
    };
    critique.addEventListener("change", () => persist("critique", critique.value.trim()));
    reproduce.addEventListener("change", () => persist("reproduce", reproduce.value.trim()));
    const toQuest = h("button", {
      class: "btn",
      onclick: async () => {
        const what = reproduce.value.trim();
        if (!what) {
          toast("Write the result you'd reproduce first.", "info");
          reproduce.focus();
          return;
        }
        await persist("reproduce", what);
        const quest = await api.get<Quest | null>("/api/quest/active");
        if (!quest) {
          await api.post("/api/ideas", { text: `Reproduce: ${what}`, document_id: d.id });
          toast("No main goal right now, so it's parked in Ideas.", "ok");
          return;
        }
        await api.post(`/api/quests/${quest.id}/steps`, {
          title: `Reproduce: ${what}`, document_id: d.id, minutes: 60,
          low: `List what you'd need to reproduce: ${what}`, high: `Run it end to end and compare with the paper`,
        });
        toast(`Added to “${quest.title}” as a step.`, "ok");
      },
    }, "Make it a goal step");
    return h(
      "section",
      { class: "critique" },
      h("h2", null, "My critique"),
      h("p", { class: "muted small" }, "After the three passes: judge the paper, then pick one result to reproduce. Reading turns into understanding when you test it."),
      critique,
      h("label", { class: "field" }, h("span", null, "A result I'd reproduce"), reproduce),
      h("div", { class: "row" }, toQuest, saved),
    );
  }

  async function exportMd() {
    const r = await api.post<{ path: string; markdown: string }>(`/api/documents/${docId}/export`);
    try {
      await navigator.clipboard.writeText(r.markdown);
      toast(`Saved to ${r.path} and copied to the clipboard`, "ok", 6000);
    } catch {
      toast(`Saved to ${r.path}`, "ok", 6000);
    }
  }
}
