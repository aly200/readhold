// Study shelf: start a blank notebook (no file needed), or add PDF slides, PowerPoint decks and HTML
// lecture pages; open any of them to study with the notebook beside it.
import { api } from "../api";
import type { Paper } from "../types";
import { askText, clear, confirmBox, h, toast } from "../util";
import { libraryHead } from "./libtabs";

interface Row {
  id: string;
  title: string;
  kind: "pdf" | "pptx" | "html" | "notebook";
  pages: number;
  position: number;
  notes: number;
  updated_at: string;
}

const KIND = { pdf: "PDF", pptx: "Slides", html: "Web page", notebook: "Notebook" };
const ICON = { pdf: "📄", pptx: "🖼️", html: "🌐", notebook: "📒" };
const PAPERS: [Paper, string][] = [["lined", "Lined"], ["dotted", "Dotted"], ["grid", "Grid"], ["plain", "Plain"]];

export async function lecturesView(root: HTMLElement): Promise<void> {
  const list = h("div", { class: "lecture-grid" });
  const busy = h("div", { class: "busy", hidden: true }, h("span", { class: "spinner" }), h("span", { class: "busy-text" }, "Importing…"));
  const input = h("input", { type: "file", accept: ".pdf,.pptx,.html,.htm", multiple: true, hidden: true });
  const importFiles = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      busy.hidden = false;
      busy.querySelector(".busy-text")!.textContent = `Importing ${f.name}…`;
      const form = new FormData();
      form.append("file", f);
      try {
        const r = await api.upload<{ id: string; title: string; pages: number }>("/api/lectures/import", form);
        toast(`Added “${r.title}” — ${r.pages} page${r.pages > 1 ? "s" : ""}`, "ok");
      } catch (e) {
        toast(`Couldn't import ${f.name}: ${(e as Error).message}`, "error", 8000);
      } finally {
        busy.hidden = true;
      }
    }
    await refresh();
  };
  input.addEventListener("change", () => input.files && importFiles(input.files));
  const drop = h(
    "div",
    { class: "drop study-tile files", tabindex: 0, role: "button", onclick: () => input.click(), onkeydown: (e: KeyboardEvent) => e.key === "Enter" && input.click() },
    h("span", { class: "tile-icon", "aria-hidden": "true" }, "📚"),
    h("strong", null, "Study a lecture"),
    h("span", { class: "muted" }, "Drop PDF slides, a PowerPoint (.pptx) or an HTML page here · or click to choose"),
  );
  drop.addEventListener("dragover", (e) => (e.preventDefault(), drop.classList.add("over")));
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer?.files.length) void importFiles(e.dataTransfer.files);
  });

  // A blank notebook: no file to drop, just pages to write and draw on.
  let paper: Paper = "lined";
  const paperBtns = PAPERS.map(([v, label]) =>
    h("button", { class: `paper-pick paper-${v} ${v === paper ? "on" : ""}`, type: "button", "aria-pressed": String(v === paper), title: `${label} paper`, onclick: (e: Event) => {
      e.stopPropagation();
      paper = v;
      paperBtns.forEach((b) => {
        const on = b.classList.contains(`paper-${v}`);
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", String(on));
      });
    } }, h("span", { class: "paper-swatch" }), label));
  const startNotebook = async () => {
    const title = await askText("New notebook", "What is it for?", "", { placeholder: "Linear algebra · week 3", okLabel: "Start writing" });
    if (title === null) return;
    const nb = await api.post<{ id: string }>("/api/lectures/notebook", { title: title.trim() || "My notes", paper });
    location.hash = `#/lecture/${nb.id}`;
  };
  const blank = h("div", { class: "study-tile notebook", tabindex: 0, role: "button", onclick: () => void startNotebook(), onkeydown: (e: KeyboardEvent) => e.key === "Enter" && e.target === blank && void startNotebook() },
    h("span", { class: "tile-icon", "aria-hidden": "true" }, "✏️"),
    h("strong", null, "Start a blank notebook"),
    h("span", { class: "muted" }, "No lecture needed: type or write by hand on pages, with sticky notes, question cards and sketches beside them."),
    h("div", { class: "paper-picks", role: "group", "aria-label": "Paper" }, paperBtns));

  root.append(
    h(
      "section",
      { class: "lectures study" },
      libraryHead("study"),
      h("div", { class: "isle page-head" },
        h("p", { class: "muted" }, "Slides stay slides, and blank pages are yours to fill. Every page has a notebook beside it: sticky notes, question cards, snips, sketches and a pen."),
        h("p", { class: "muted small" }, "Web pages open in a sealed frame: their scripts run, but they can't reach the internet or the rest of Readhold.")),
      h("div", { class: "study-tiles" }, blank, drop),
      input,
      busy,
      list,
    ),
  );

  async function refresh(): Promise<void> {
    const rows = await api.get<Row[]>("/api/lectures");
    clear(list);
    if (!rows.length) {
      list.append(h("p", { class: "empty-hint" }, "Nothing here yet. Start a notebook, or add this week's slides."));
      return;
    }
    for (const r of rows) {
      const pct = r.pages ? Math.round(((r.position + 1) / r.pages) * 100) : 0;
      const where = r.kind === "html" ? "Web page" : r.kind === "notebook" ? `${r.pages} page${r.pages > 1 ? "s" : ""}` : `Page ${r.position + 1} of ${r.pages}`;
      list.append(
        h(
          "article",
          { class: `lecture-card kind-${r.kind}` },
          h("a", { class: "lecture-open", href: `#/lecture/${r.id}` },
            h("span", { class: "badge" }, h("span", { "aria-hidden": "true" }, `${ICON[r.kind]} `), KIND[r.kind]),
            h("strong", { class: "lecture-title" }, r.title),
            h("span", { class: "muted small" }, where, r.notes ? ` · ${r.notes} note${r.notes > 1 ? "s" : ""}` : ""),
            r.kind === "html" || r.kind === "notebook" ? null : h("span", { class: "meter" }, h("span", { style: { width: `${pct}%` } }))),
          h(
            "div",
            { class: "row" },
            h("button", { class: "btn small ghost", onclick: async () => {
              const t = await askText("Rename", "Title", r.title);
              if (t) (await api.patch(`/api/lectures/${r.id}`, { title: t }), refresh());
            } }, "Rename"),
            h("button", { class: "btn small ghost", onclick: async () => {
              if (!(await confirmBox(`Remove this ${r.kind === "notebook" ? "notebook" : "lecture"}?`, `“${r.title}” and its notes are hidden. You can undo right after.`, "Remove"))) return;
              await api.del(`/api/lectures/${r.id}`);
              await refresh();
              toast(`Removed “${r.title}”.`, "info", 8000, { label: "Undo", run: async () => (await api.post(`/api/lectures/${r.id}/restore`), refresh()) });
            } }, "Remove"),
          ),
        ),
      );
    }
  }
  await refresh();
}
