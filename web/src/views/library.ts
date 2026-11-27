// Library: import (file or paste) and the reading queue — every document says why you're reading it.
import { api } from "../api";
import { libraryAskBox } from "./libraryask";
import type { QueueDoc } from "../types";
import { askText, clear, confirmBox, h, toast } from "../util";
import { libraryHead } from "./libtabs";
import { organizeDialog } from "./organize";

interface ImportResult {
  id: string;
  title: string;
  warning: string | null;
  sentences: number;
  sections: number;
}

/** What the warning on a document means, in words. */
function flagHint(flags: string[]): string {
  const parts: string[] = [];
  if (flags.includes("hidden_text")) parts.push("This file holds text a reader cannot see (white, too small, or off the page).");
  if (flags.includes("instructions")) parts.push("Some of its text reads like orders to an AI model (\"ignore previous instructions\").");
  return `${parts.join(" ")} You can read it as usual. An AI model is always told that document text is material to read, never instructions.`;
}

export async function libraryView(root: HTMLElement): Promise<void> {
  const list = h("div", { class: "queue" });
  const shelves = h("div", { class: "row wrap shelves", role: "group", "aria-label": "Collections: show the documents with a tag" });
  let shelf = "";
  const busy = h("div", { class: "busy", hidden: true }, h("span", { class: "spinner" }), h("span", { class: "busy-text" }, "Importing…"));

  const afterImport = async (res: ImportResult) => {
    toast(`Imported “${res.title}” — ${res.sections} sections, ${res.sentences} sentences`, "ok");
    if (res.warning) toast(res.warning, "info", 7000);
    const why = await askText("Why am I reading this?", "One line. It keeps you reading with a job.", "", { placeholder: "e.g. for Thursday's exam — understand the method", okLabel: "Save" });
    const deadline = why !== null ? await askText("Deadline (optional)", "When do you need it? (YYYY-MM-DD, or leave empty)", "", { placeholder: "2026-11-20" }) : null;
    const patch: Record<string, string> = {};
    if (why) patch.why = why;
    if (deadline && /^\d{4}-\d{2}-\d{2}$/.test(deadline)) patch.deadline = deadline;
    if (Object.keys(patch).length) await api.patch(`/api/documents/${res.id}`, patch);
    await refresh();
  };

  const run = async (label: string, fn: () => Promise<ImportResult>) => {
    busy.hidden = false;
    busy.querySelector(".busy-text")!.textContent = label;
    try {
      const res = await fn();
      busy.hidden = true;
      await afterImport(res);
    } catch (e) {
      busy.hidden = true;
      toast(`Import failed: ${(e as Error).message}`, "error", 8000);
    }
  };

  const fileInput = h("input", { type: "file", accept: ".pdf,.md,.markdown,.txt,.text,.rst,.py,.pyi,.js,.mjs,.cjs,.jsx,.ts,.tsx,.go,.rs,.java,.c,.h,.cpp,.cc,.hpp,.cs,.kt,.swift,.php,.rb,.sh,.ps1,.sql,.css,.json,.toml,.yaml,.yml", multiple: true, hidden: true });
  const importFiles = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      const form = new FormData();
      form.append("file", f);
      await run(`Importing ${f.name}…`, () => api.upload<ImportResult>("/api/import/file", form));
    }
  };
  fileInput.addEventListener("change", () => fileInput.files && importFiles(fileInput.files));
  const drop = h("div", { class: "drop", tabindex: 0, role: "button", onclick: () => fileInput.click(), onkeydown: (e: KeyboardEvent) => e.key === "Enter" && fileInput.click() }, h("strong", null, "Drop a PDF, Markdown, text or code file"), h("span", { class: "muted" }, " or click to choose"));
  drop.addEventListener("dragover", (e) => (e.preventDefault(), drop.classList.add("over")));
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer?.files.length) importFiles(e.dataTransfer.files);
  });

  const pasteTitle = h("input", { type: "text", placeholder: "Title (optional)" });
  const paste = h("textarea", { rows: 6, placeholder: "Paste Markdown or plain text…" });
  const fmt = h("select", null, h("option", { value: "markdown" }, "Markdown"), h("option", { value: "text" }, "Plain text"));
  const importPaste = () => paste.value.trim() && run("Reading the structure…", () => api.post<ImportResult>("/api/import/text", { title: pasteTitle.value, text: paste.value, format: fmt.value })).then(() => ((paste.value = ""), (pasteTitle.value = "")));

  root.append(
    h(
      "section",
      { class: "library" },
      libraryHead("documents"),
      h(
        "div",
        { class: "import" },
        drop,
        fileInput,
        h("details", null, h("summary", null, "Paste text"), h("div", { class: "stack" }, pasteTitle, paste, h("div", { class: "row" }, fmt, h("button", { class: "btn", onclick: importPaste }, "Import text")))),
        h("p", { class: "muted small" }, "Files stay on this computer. Readhold downloads nothing: to read a web article or an arXiv paper, save it as a PDF first, or paste its text."),
        busy,
      ),
      libraryAskBox(),
      h("h2", null, "Reading queue"),
      shelves,
      list,
    ),
  );

  async function refresh(): Promise<void> {
    const all = await api.get<QueueDoc[]>("/api/documents");
    clear(list);
    // collections: every tag, with how many documents carry it; choosing one shows only those
    const counts = new Map<string, number>();
    for (const d of all) for (const t of d.tags ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
    if (shelf && !counts.has(shelf)) shelf = "";
    clear(shelves);
    if (counts.size) {
      const chip = (t: string, label: string) => h("button", { type: "button", class: `chip ${shelf === t ? "on" : ""}`, "aria-pressed": String(shelf === t), onclick: () => ((shelf = t), void refresh()) }, label);
      shelves.append(chip("", "All"), ...[...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([t, n]) => chip(t, `#${t} (${n})`)));
    }
    const docs = shelf ? all.filter((d) => d.tags?.includes(shelf)) : all;
    if (!docs.length) {
      list.append(h("p", { class: "empty" }, "Nothing here yet."));
      return;
    }
    for (const d of docs) {
      const pct = Math.round(d.progress.ratio * 100);
      const overdue = d.deadline && d.status !== "finished" && d.deadline < new Date().toISOString().slice(0, 10);
      list.append(
        h(
          "article",
          { class: `doc-row ${d.status}` },
          h(
            "div",
            { class: "doc-main" },
            h("a", { class: "doc-name", href: `#/read/${d.id}` }, d.title),
            h(
              "div",
              { class: "muted small" },
              d.source_type.toUpperCase(),
              d.deadline ? h("span", { class: overdue ? "overdue" : "" }, ` · due ${d.deadline}`) : null,
              ` · ${d.status}`,
              d.import_warning ? h("span", { class: "warn", title: d.import_warning }, " · import note") : null,
              d.flags?.length ? h("span", { class: "warn doc-flag", title: flagHint(d.flags) }, " · ⚠ flagged text") : null,
              d.tags?.length ? h("span", { class: "doc-tags" }, ` · ${d.tags.map((t) => `#${t}`).join(" ")}`) : null,
            ),
            h("button", { class: "why link", onclick: () => editWhy(d) }, d.why ? `Why: ${d.why}` : "Why am I reading this? (add)"),
            h("div", { class: "bar", title: `${d.progress.read} of ${d.progress.total} key sentences read` }, h("span", { style: { width: `${pct}%` } })),
          ),
          h(
            "div",
            { class: "doc-actions" },
            h("a", { class: "btn primary small", href: `#/read/${d.id}` }, d.position > 0 ? "Resume" : "Read"),
            h("a", { class: "btn small", href: `#/summary/${d.id}` }, "Summary"),
            h("a", { class: "btn small", href: `#/structure/${d.id}` }, "Structure"),
            h("button", { class: "btn small ghost", title: "Tags (your collections) and related documents", onclick: () => void organizeDialog(d.id, d.title, () => void refresh()) }, "Organize"),
            h("button", { class: "btn small ghost", onclick: () => setDeadline(d) }, "Deadline"),
            h("button", { class: "btn small ghost", onclick: () => remove(d) }, "Remove"),
          ),
        ),
      );
    }
  }

  async function editWhy(d: QueueDoc) {
    const why = await askText("Why am I reading this?", "One line", d.why);
    if (why === null) return;
    await api.patch(`/api/documents/${d.id}`, { why });
    refresh();
  }
  async function setDeadline(d: QueueDoc) {
    const v = await askText("Deadline", "YYYY-MM-DD (empty to clear)", d.deadline ?? "");
    if (v === null) return;
    if (v && !/^\d{4}-\d{2}-\d{2}$/.test(v)) return toast("Use the format YYYY-MM-DD", "error");
    await api.patch(`/api/documents/${d.id}`, { deadline: v || "" });
    refresh();
  }
  async function remove(d: QueueDoc) {
    if (!(await confirmBox("Remove this document?", `“${d.title}” will be hidden. Your notes stay in the database and exports, and the original file stays in the library folder.`, "Remove"))) return;
    await api.del(`/api/documents/${d.id}`);
    refresh();
    toast(`Removed “${d.title}”.`, "info", 8000, {
      label: "Undo",
      run: async () => {
        await api.post(`/api/documents/${d.id}/restore`);
        refresh();
      },
    });
  }

  await refresh();
}
