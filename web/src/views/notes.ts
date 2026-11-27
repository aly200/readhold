// Notes: your own pages, linked with [[double brackets]].
// - Write in a small Markdown (headings, lists, check boxes, **bold**, `code`, ==highlight==, #tags, math).
// - [[Another note]] links by title. Typing [[ suggests titles. A link to a note that doesn't exist yet
//   makes it when you follow it. A link can also open a library document, a lecture or notebook, or a quest.
// - Beside every note: what links here, plain mentions you can turn into links, and a small map.
// - Ctrl+K finds anything from anywhere. One daily note per day. A check box can be sent to Plan.
// - Typing / at the start of a line offers blocks (heading, to-do, table, callout…). `key:: value` lines are
//   properties: they show as a small grid in the note and as columns in the table of all notes (#/notes/table).
// - #/notes/map draws every note and the links between them.
// Safety: bodies are plain text. Everything is drawn with DOM nodes and textContent, never innerHTML.
import { tidyNoteDialog } from "./tidy";
import { noteChatDialog } from "./notechat";
import { notesHead } from "./libtabs";
import { api } from "../api";
import { mathText } from "../math";
import type { DaySummary, Near, NoteGraph, NoteLink, NoteList, NotePage, NoteTitles, Related } from "../types";
import { askText, clear, debounce, h, isTyping, prefersReducedMotion, toast } from "../util";

type Mode = "read" | "write";
const TEMPLATES: Record<string, string> = {
  "Lecture summary": "## Main idea\n\n\n## Key points\n- \n\n## Questions I still have\n- [ ] \n\n## In my own words\n",
  "Weekly review": "## What went well\n- \n\n## What was hard\n- \n\n## Next week, the one thing\n- [ ] \n",
  "Project": "## Goal\n\n\n## Done looks like\n\n\n## Next steps\n- [ ] \n",
  "Decision": "## The question\n\n\n## Options\n- \n\n## What I choose, and why\n",
};
const KIND_ICON: Record<NoteLink["kind"], string> = { page: "", document: "📄 ", lecture: "📒 ", quest: "🧭 ", term: "🔤 ", missing: "" };
const INLINE = /\[\[([^\[\]\n|]{1,200})(?:\|([^\[\]\n]{0,200}))?\]\]|`([^`\n]+)`|\*\*([^*\n]+)\*\*|==([^=\n]+)==|\*([^*\s][^*\n]*)\*|\[([^\]\n]+)\]\(([^)\s]+)\)|(?<![\p{L}\p{N}_&#/])#(\p{L}[\p{L}\p{N}_-]{0,39})/gu;

const PROP_LINE = /^([A-Za-z][\w \-]{0,30})::[ \t]*(\S.*)$/;
const ANCHOR = /\s*#s(\d{1,6})\s*$/; // [[A document#s12]] points at its sentence 12
const CALLOUT_ICON: Record<string, string> = { note: "📝", tip: "💡", warning: "⚠️", question: "❓", important: "⭐" };
/** what typing / at the start of a line offers; `back` puts the caret that many characters before the end */
const SLASH: { title: string; insert: string; back?: number }[] = [
  { title: "Heading", insert: "## " },
  { title: "Small heading", insert: "### " },
  { title: "To-do", insert: "- [ ] " },
  { title: "List", insert: "- " },
  { title: "Numbered list", insert: "1. " },
  { title: "Quote", insert: "> " },
  { title: "Callout", insert: "> [!note] " },
  { title: "Table", insert: "| Column | Column |\n| --- | --- |\n|  |  |\n", back: 8 },
  { title: "Code", insert: "```\n\n```\n", back: 5 },
  { title: "Divider", insert: "---\n" },
  { title: "Link", insert: "[[" },
  { title: "Property", insert: "status:: " },
  { title: "Today's date", insert: "" },
];

const splitTarget = (raw: string): { title: string; sentence: number | null } => {
  const m = raw.match(ANCHOR);
  return m ? { title: raw.slice(0, m.index), sentence: Number(m[1]) } : { title: raw, sentence: null };
};

// what you were looking at stays when you move between notes
let lastQuery = "";
let lastTag = "";

/** append, skipping the pieces that are not there */
const add = (el: Element, ...kids: (Node | string | null)[]): void => el.append(...kids.filter((k): k is Node | string => k !== null));

const isDay = (s: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(s);
const keyOf = (title: string): string => title.trim().split(/\s+/).join(" ").toLowerCase();
const pad = (n: number) => String(n).padStart(2, "0");
const todayYmd = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
function hrefFor(kind: string, id: string, title = ""): string {
  if (kind === "term") return `#/glossary?concept=${encodeURIComponent(title)}`;
  if (kind === "document") return `#/read/${id}`;
  if (kind === "lecture") return `#/lecture/${id}`;
  if (kind === "quest") return `#/quest/${id}`;
  return `#/notes/${id}`;
}
function niceDaily(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

// ------------------------------------------------------------------ the page
export async function notesView(root: HTMLElement, id?: string): Promise<() => void> {
  if (id === "table") return tableView(root);
  if (id === "map") return bigMap(root);
  let listing = await api.get<NoteList>(`/api/pages?q=${encodeURIComponent(lastQuery)}&tag=${encodeURIComponent(lastTag)}`);
  let cur: NotePage | null = null;
  try {
    if (id === "today") cur = await api.get<NotePage>(`/api/pages/daily/${todayYmd()}`);
    else if (id && isDay(id)) cur = await api.get<NotePage>(`/api/pages/daily/${id}`); // #/notes/2026-11-22: that day's note
    else if (id) cur = await api.get<NotePage>(`/api/pages/${id}`);
    else if (listing.pages.length && !lastQuery && !lastTag) cur = await api.get<NotePage>(`/api/pages/${listing.pages[0].id}`);
  } catch {
    toast("That note is not here anymore.", "info");
  }
  if ((id === "today" || (id && isDay(id))) && cur) listing = await api.get<NoteList>(`/api/pages?q=${encodeURIComponent(lastQuery)}&tag=${encodeURIComponent(lastTag)}`);
  let mode: Mode = cur && cur.body.trim() && !(cur.daily && cur.body.includes("- [ ] \n")) ? "read" : "write";
  let titles: NoteTitles | null = null;
  let extra: { id: string; day: DaySummary | null; tasks: Related["tasks"]; near: Near[] } | null = null;

  const side = h("nav", { class: "notes-list", "aria-label": "Your notes" });
  const main = h("div", { class: "note-main" });
  const around = h("aside", { class: "note-around", "aria-label": "Around this note" });
  root.append(h("section", { class: "notes" }, notesHead("notes"), side, main, around));

  const refreshList = async () => {
    listing = await api.get<NoteList>(`/api/pages?q=${encodeURIComponent(lastQuery)}&tag=${encodeURIComponent(lastTag)}`);
    renderList();
  };

  // ---------------------------------------------------------------- saving
  let saving: Promise<unknown> = Promise.resolve();
  const status = h("span", { class: "note-status muted small", "aria-live": "polite" });
  const put = (body: Record<string, unknown>): Promise<void> => {
    if (!cur) return Promise.resolve();
    const pid = cur.id;
    status.textContent = "Saving…";
    const job = saving.then(() => api.patch<NotePage>(`/api/pages/${pid}`, body)).then((fresh) => {
      if (!cur || cur.id !== pid) return;
      // keep what is being typed: only what the server knows better is taken over
      cur = { ...fresh, body: "body" in body ? fresh.body : cur.body };
      status.textContent = "Saved";
      renderAround();
      if (mode === "read") renderBody();
    }, (e: Error) => {
      status.textContent = "Not saved";
      toast(`Couldn't save: ${e.message}`, "error");
    });
    saving = job;
    return job;
  };
  const saveBody = debounce((text: string) => void put({ body: text }).then(() => void refreshList()), 600);

  // ---------------------------------------------------------------- the list on the left
  const openNew = async () => {
    const title = await askText("New note", "Title", "", { okLabel: "Create", placeholder: "Eigenvectors" });
    if (!title) return;
    try {
      const p = await api.post<NotePage>("/api/pages/open", { title });
      location.hash = `#/notes/${p.id}`;
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const renderList = () => {
    clear(side);
    const search = h("input", { type: "search", value: lastQuery, placeholder: "Search notes…", "aria-label": "Search notes" });
    const go = debounce(() => {
      lastQuery = search.value.trim();
      void refreshList().then(() => side.querySelector<HTMLInputElement>("input[type=search]")?.focus());
    }, 250);
    search.addEventListener("input", go);
    add(side,
      h("div", { class: "notes-actions" },
        h("button", { class: "btn primary", type: "button", onclick: () => void openNew() }, "+ New note"),
        h("a", { class: "btn", href: "#/notes/today", title: "One note per day, made when you open it" }, "Today")),
      h("div", { class: "notes-views" },
        h("a", { href: "#/notes/table", title: "Every note in a table, with its properties as columns" }, "▦ Table"),
        h("a", { href: "#/notes/map", title: "Every note and the links between them" }, "🕸 Map")),
      search,
      listing.tags.length ? h("div", { class: "notes-tags" }, listing.tags.map((t) => h("button", { type: "button", class: `md-tag ${lastTag === t.tag ? "is-on" : ""}`, onclick: () => {
        lastTag = lastTag === t.tag ? "" : t.tag;
        void refreshList();
      } }, `#${t.tag}`))) : null);
    const ul = h("ul", { class: "notes-items" });
    for (const p of listing.pages) {
      ul.append(h("li", null, h("a", { href: `#/notes/${p.id}`, class: `notes-item ${cur?.id === p.id ? "is-on" : ""}`, "aria-current": cur?.id === p.id ? "page" : undefined },
        h("span", { class: "notes-item-title" }, p.pinned ? "★ " : "", p.daily ? `${niceDaily(p.daily)}` : p.title),
        p.snippet ? h("span", { class: "notes-item-snip" }, p.snippet) : null)));
    }
    if (!listing.pages.length) ul.append(h("li", { class: "muted small notes-none" }, lastQuery || lastTag ? "No note matches. Clear the search to see them all." : "No notes yet."));
    side.append(ul, h("div", { class: "notes-foot muted small" }, `${listing.total} note${listing.total === 1 ? "" : "s"} · ${listing.links} link${listing.links === 1 ? "" : "s"} · Ctrl+K finds anything`));
  };

  // ---------------------------------------------------------------- drawing a body (text nodes only)
  const follow = async (target: string) => {
    const { title, sentence } = splitTarget(target);
    const hit = cur?.outgoing.find((o) => o.key === keyOf(title));
    if (hit && hit.kind !== "missing" && hit.id) return void (location.hash = hrefFor(hit.kind, hit.id, hit.title) + (hit.kind === "document" && sentence !== null ? `?s=${sentence}` : ""));
    const p = await api.post<NotePage>("/api/pages/open", { title: title.trim() });
    location.hash = `#/notes/${p.id}`;
  };
  const inline = (text: string): Node[] => {
    const out: Node[] = [];
    let last = 0;
    for (const m of text.matchAll(INLINE)) {
      if (m.index! > last) out.push(...mathText(text.slice(last, m.index)));
      last = m.index! + m[0].length;
      if (m[1] !== undefined) {
        const to = splitTarget(m[1]);
        const hit = cur?.outgoing.find((o) => o.key === keyOf(to.title));
        const kind = hit?.kind ?? "missing";
        out.push(h("a", { href: "#", class: `wikilink kind-${kind}`, title: kind === "missing" ? "Not written yet. Click to start it." : kind === "page" ? "Open this note" : `Open the ${kind === "lecture" ? "lecture or notebook" : kind === "term" ? "glossary term" : kind}`,
          onclick: (e: Event) => (e.preventDefault(), void follow(m[1])) }, KIND_ICON[kind], (m[2] || to.title).trim()));
      } else if (m[3] !== undefined) out.push(h("code", null, m[3]));
      else if (m[4] !== undefined) out.push(h("strong", null, m[4]));
      else if (m[5] !== undefined) out.push(h("mark", null, m[5]));
      else if (m[6] !== undefined) out.push(h("em", null, m[6]));
      else if (m[7] !== undefined) {
        const url = m[8];
        out.push(h("button", { type: "button", class: "md-ext", title: `${url} (click to copy; Readhold stays offline)`, onclick: () => void navigator.clipboard?.writeText(url).then(() => toast("Link copied.", "ok", 2000), () => undefined) }, m[7], " ↗"));
      } else if (m[9] !== undefined) {
        const tag = m[9].toLowerCase();
        out.push(h("button", { type: "button", class: "md-tag", title: `Show notes tagged #${tag}`, onclick: () => {
          lastTag = tag;
          void refreshList();
        } }, `#${m[9]}`));
      }
    }
    if (last < text.length) out.push(...mathText(text.slice(last)));
    return out;
  };

  const setLine = async (index: number, change: (line: string) => string) => {
    if (!cur) return;
    const lines = cur.body.split("\n");
    if (index >= lines.length) return;
    lines[index] = change(lines[index]);
    cur.body = lines.join("\n");
    renderBody();
    await put({ body: cur.body });
  };

  const renderMd = (body: string): Node[] => {
    const out: Node[] = [];
    const lines = body.split("\n");
    let para: string[] = [];
    const flush = () => {
      if (!para.length) return;
      const p = h("p");
      para.forEach((l, k) => {
        if (k) p.append(h("br"));
        p.append(...inline(l));
      });
      out.push(p);
      para = [];
    };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^```/.test(line)) {
        flush();
        const code: string[] = [];
        for (i++; i < lines.length && !/^```/.test(lines[i]); i++) code.push(lines[i]);
        out.push(h("pre", { class: "md-code" }, h("code", null, code.join("\n"))));
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
        flush();
        const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const top = cells(line);
        const rows: string[][] = [];
        for (i += 2; i < lines.length && /^\s*\|/.test(lines[i]); i++) rows.push(cells(lines[i]));
        i--;
        out.push(h("div", { class: "md-table-wrap" }, h("table", { class: "md-table" },
          h("thead", null, h("tr", null, top.map((c) => h("th", null, inline(c))))),
          h("tbody", null, rows.map((r) => h("tr", null, top.map((_c, k) => h("td", null, inline(r[k] ?? "")))))))));
        continue;
      }
      if (PROP_LINE.test(line)) {
        flush();
        const dl = h("dl", { class: "md-props" });
        for (; i < lines.length && PROP_LINE.test(lines[i]); i++) {
          const m = lines[i].match(PROP_LINE)!;
          dl.append(h("dt", null, m[1].trim()), h("dd", null, inline(m[2])));
        }
        i--;
        out.push(dl);
        continue;
      }
      const head = line.match(/^(#{1,4})\s+(.*)$/);
      if (head) {
        flush();
        out.push(h(`h${head[1].length + 1}` as "h2", { class: "md-h", "data-line": String(i) }, inline(head[2])));
        continue;
      }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
        flush();
        out.push(h("hr"));
        continue;
      }
      const task = line.match(/^(\s*)[-*]\s+\[( |x|X)\]\s?(.*)$/);
      if (task) {
        flush();
        const index = i;
        const done = task[2] !== " ";
        const inPlan = /\(in Plan\)\s*$/.test(task[3]);
        const text = task[3].replace(/\s*\(in Plan\)\s*$/, "");
        out.push(h("div", { class: `md-task ${done ? "is-done" : ""}`, style: { paddingLeft: `${Math.floor(task[1].length / 2) * 1.4}em` } },
          h("input", { type: "checkbox", checked: done, "aria-label": text || "Task", onchange: () => void setLine(index, (l) => (done ? l.replace(/\[(x|X)\]/, "[ ]") : l.replace("[ ]", "[x]"))) }),
          h("span", { class: "md-task-text" }, inline(text)),
          inPlan ? h("span", { class: "tchip quiet" }, "in Plan") : !done && text.trim()
            ? h("button", { type: "button", class: "md-to-plan", title: "Make it a task on the Plan page", onclick: async () => {
                await api.post("/api/todos", { text: text.replace(/\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]/g, (_s, a: string, b?: string) => b || a).replace(/[*`=]/g, "").trim().slice(0, 500), minutes: 25, ...(cur ? { link_type: "page", link_id: cur.id } : {}) });
                await setLine(index, (l) => `${l.trimEnd()} (in Plan)`);
                toast("Added to Plan.", "ok", 2500);
              } }, "→ Plan")
            : null));
        continue;
      }
      const item = line.match(/^(\s*)([-*]|\d+[.)])\s+(.*)$/);
      if (item) {
        flush();
        out.push(h("div", { class: "md-li", style: { paddingLeft: `${Math.floor(item[1].length / 2) * 1.4}em` } }, h("span", { class: "md-bullet", "aria-hidden": "true" }, /\d/.test(item[2]) ? item[2] : "•"), h("span", null, inline(item[3]))));
        continue;
      }
      if (/^>/.test(line)) {
        flush();
        const q: string[] = [];
        for (; i < lines.length && /^>/.test(lines[i]); i++) q.push(lines[i].replace(/^>\s?/, ""));
        i--;
        const body = (ls: string[]): Node[] => ls.flatMap((l, k) => (k ? [h("br"), ...inline(l)] : inline(l)));
        const call = q[0].match(/^\[!(note|tip|warning|question|important)\]\s*(.*)$/i);
        if (call) {
          const kind = call[1].toLowerCase();
          out.push(h("div", { class: `md-callout kind-${kind}` },
            h("strong", { class: "md-callout-title" }, `${CALLOUT_ICON[kind]} `, call[2] ? inline(call[2]) : kind.charAt(0).toUpperCase() + kind.slice(1)),
            q.length > 1 ? h("div", null, body(q.slice(1))) : null));
        } else out.push(h("blockquote", null, body(q)));
        continue;
      }
      if (!line.trim()) {
        flush();
        continue;
      }
      para.push(line);
    }
    flush();
    return out;
  };

  // ---------------------------------------------------------------- the note in the middle
  const bodyBox = h("div", { class: "note-body-box" });
  let area: HTMLTextAreaElement | null = null;
  const fit = () => {
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight + 4}px`;
  };

  const renderBody = () => {
    clear(bodyBox);
    area = null;
    if (!cur) return;
    if (mode === "read") {
      const view = h("div", { class: "note-read", title: "Double-click to write" }, renderMd(cur.body));
      if (!cur.body.trim()) view.append(h("p", { class: "muted" }, "Empty for now. Press Write, or double-click here."));
      view.addEventListener("dblclick", (e) => {
        if ((e.target as HTMLElement).closest("a, button, input")) return;
        setMode("write");
      });
      bodyBox.append(view);
      return;
    }
    // write mode: plain text, with [[ suggestions above it
    const suggest = h("div", { class: "note-suggest", hidden: true });
    let picks: { title: string; kind: string; insert?: string; back?: number }[] = [];
    let pickAt = 0;
    const ta = h("textarea", { class: "note-area", spellcheck: "true", placeholder: "Write here.  Type / for blocks.  # Heading   - list   - [ ] task   [[link to a note]]   #tag   **bold**", "aria-label": "Note text" }, cur.body);
    area = ta;
    const hideSuggest = () => {
      suggest.hidden = true;
      picks = [];
    };
    const drawSuggest = () => {
      clear(suggest);
      suggest.append(h("span", { class: "muted small" }, picks[0]?.kind === "slash" ? "Insert:" : "Link to:"));
      picks.forEach((p, i) => suggest.append(h("button", { type: "button", class: `chip ${i === pickAt ? "is-on" : ""}`, onmousedown: (e: Event) => (e.preventDefault(), choose(i)) }, KIND_ICON[p.kind as NoteLink["kind"]] ?? "", p.title)));
      suggest.append(h("span", { class: "muted small" }, "Tab to pick"));
    };
    const linkQuery = (): string | null => ta.value.slice(0, ta.selectionStart).match(/\[\[([^\[\]\n]*)$/)?.[1] ?? null;
    /** "/" at the start of a line, and what was typed after it */
    const slashQuery = (): { q: string; from: number } | null => {
      const pos = ta.selectionStart;
      const start = ta.value.lastIndexOf("\n", pos - 1) + 1;
      const m = ta.value.slice(start, pos).match(/^(\s*)\/([a-z' ]{0,16})$/i);
      return m ? { q: m[2].toLowerCase(), from: start + m[1].length } : null;
    };
    const checkSuggest = async () => {
      const slash = slashQuery();
      if (slash) {
        picks = SLASH.filter((c) => c.title.toLowerCase().includes(slash.q)).slice(0, 13).map((c) => ({ ...c, kind: "slash", insert: c.title === "Today's date" ? todayYmd() : c.insert }));
        if (!picks.length) return hideSuggest();
        pickAt = Math.min(pickAt, picks.length - 1);
        suggest.hidden = false;
        return drawSuggest();
      }
      const q = linkQuery();
      if (q === null) return hideSuggest();
      titles ??= await api.get<NoteTitles>("/api/pages/titles").catch(() => ({ pages: [], others: [] }));
      const low = q.toLowerCase();
      picks = [...titles.pages.map((p) => ({ title: p.title, kind: "page" })), ...titles.others.map((o) => ({ title: o.title, kind: o.kind }))]
        .filter((p) => p.title.toLowerCase().includes(low) && p.title !== cur?.title).slice(0, 7);
      if (!picks.length) return hideSuggest();
      pickAt = Math.min(pickAt, picks.length - 1);
      suggest.hidden = false;
      drawSuggest();
    };
    const choose = (i: number) => {
      const p = picks[i];
      const slash = slashQuery();
      if (p?.kind === "slash" && slash) {
        ta.setRangeText(p.insert ?? "", slash.from, ta.selectionStart, "end");
        if (p.back) ta.selectionStart = ta.selectionEnd = ta.selectionStart - p.back;
        hideSuggest();
        changed();
        ta.focus();
        void checkSuggest(); // "Link" goes straight on to the titles
        return;
      }
      const q = linkQuery();
      if (q === null || !p) return;
      const end = ta.selectionStart;
      const closes = ta.value.slice(end, end + 2) === "]]";
      ta.setRangeText(`${p.title}${closes ? "" : "]]"}`, end - q.length, end, "end");
      if (closes) ta.selectionStart = ta.selectionEnd = ta.selectionStart + 2;
      hideSuggest();
      changed();
      ta.focus();
    };
    const changed = () => {
      if (!cur) return;
      cur.body = ta.value;
      status.textContent = "…";
      saveBody(ta.value);
      fit();
    };
    ta.addEventListener("input", () => {
      changed();
      void checkSuggest();
    });
    ta.addEventListener("click", () => void checkSuggest());
    ta.addEventListener("blur", () => setTimeout(hideSuggest, 150));
    ta.addEventListener("keydown", (e) => {
      if (!suggest.hidden && picks.length) {
        if (e.key === "Tab" || e.key === "Enter") return void (e.preventDefault(), choose(pickAt));
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          pickAt = (pickAt + (e.key === "ArrowDown" ? 1 : picks.length - 1)) % picks.length;
          return drawSuggest();
        }
        if (e.key === "Escape") return void (e.stopPropagation(), hideSuggest());
      }
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && ta.selectionStart === ta.selectionEnd) {
        // a list goes on by itself; an empty item ends it
        const pos = ta.selectionStart;
        const start = ta.value.lastIndexOf("\n", pos - 1) + 1;
        const line = ta.value.slice(start, pos);
        const m = line.match(/^(\s*)([-*] \[[ xX]\] |[-*] |(\d+)([.)]) )/);
        if (!m) return;
        e.preventDefault();
        if (line.trim() === m[2].trim()) ta.setRangeText("", start, pos, "end");
        else ta.setRangeText(`\n${m[1]}${m[3] ? `${Number(m[3]) + 1}${m[4]} ` : m[2].replace(/\[[xX]\]/, "[ ]")}`, pos, pos, "end");
        changed();
      } else if (e.key === "Tab" && !e.shiftKey) {
        e.preventDefault();
        ta.setRangeText("  ", ta.selectionStart, ta.selectionEnd, "end");
        changed();
      }
    });
    bodyBox.append(suggest, ta);
    requestAnimationFrame(fit);
  };

  const setMode = (next: Mode) => {
    if (mode === next) return;
    saveBody.flush();
    mode = next;
    renderMain();
    if (next === "write") area?.focus();
  };

  const renderMain = () => {
    clear(main);
    if (!cur) {
      main.append(h("div", { class: "note-welcome" },
        h("h1", null, "Notes"),
        h("p", null, "A place for what you learn and think. Link notes with [[double brackets]] and they start to hold each other up."),
        h("div", { class: "row wrap" },
          h("a", { class: "btn primary big", href: "#/notes/today" }, "Start today's note"),
          h("button", { class: "btn", type: "button", onclick: () => void openNew() }, "+ New note")),
        h("ul", { class: "note-tips" },
          h("li", null, h("code", null, "[[Title]]"), " links to another note. If it doesn't exist yet, following the link makes it."),
          h("li", null, h("code", null, "- [ ] task"), " makes a check box. One click sends it to Plan."),
          h("li", null, h("code", null, "#tag"), " groups notes. ", h("kbd", null, "Ctrl"), "+", h("kbd", null, "K"), " jumps to any note."))));
      return;
    }
    const page = cur;
    const title = h("input", { class: "note-title", type: "text", value: page.title, maxlength: 200, "aria-label": "Title" });
    const rename = async () => {
      const next = title.value.trim();
      if (!next || next === page.title) return void (title.value = page.title);
      await saving;
      try {
        cur = await api.patch<NotePage>(`/api/pages/${page.id}`, { title: next });
        titles = null;
        toast(cur.backlinks.length ? `Renamed. ${cur.backlinks.length} link${cur.backlinks.length === 1 ? "" : "s"} to it now use the new title.` : "Renamed.", "ok", 3000);
        renderMain();
        renderAround();
        void refreshList();
      } catch (e) {
        title.value = page.title;
        toast((e as Error).message, "error");
      }
    };
    title.addEventListener("change", () => void rename());
    title.addEventListener("keydown", (e) => e.key === "Enter" && (e.preventDefault(), title.blur()));
    const seg = h("div", { class: "note-seg", role: "tablist", "aria-label": "Read or write" },
      (["read", "write"] as Mode[]).map((m) => h("button", { type: "button", role: "tab", class: `note-seg-btn ${mode === m ? "is-on" : ""}`, "aria-selected": String(mode === m), title: "Ctrl+E switches", onclick: () => setMode(m) }, m === "read" ? "Read" : "Write")));
    const template = mode === "write" ? h("select", { class: "note-template", "aria-label": "Insert a template", onchange: (e: Event) => {
      const sel = e.target as HTMLSelectElement;
      const text = TEMPLATES[sel.value];
      sel.value = "";
      if (!text || !area || !cur) return;
      area.value = area.value.trim() ? `${area.value.trimEnd()}\n\n${text}` : text;
      cur.body = area.value;
      saveBody(area.value);
      fit();
      area.focus();
    } }, h("option", { value: "" }, "Template…"), Object.keys(TEMPLATES).map((k) => h("option", { value: k }, k))) : null;
    add(main,
      h("div", { class: "note-bar" },
        seg,
        template,
        status,
        h("span", { class: "steady-write-gap" }),
        h("button", { type: "button", class: `note-tool ${page.pinned ? "is-on" : ""}`, title: page.pinned ? "Unpin" : "Pin to the top of the list", "aria-pressed": String(!!page.pinned), onclick: async () => {
          await put({ pinned: !page.pinned });
          renderMain();
          void refreshList();
        } }, page.pinned ? "★" : "☆"),
        h("button", { type: "button", class: "note-tool", title: "Tidy this note: spacing and lists, or a model's rewrite if you ask", "aria-label": "Tidy this note", onclick: () => void tidyNoteDialog(page.id, async () => {
          saveBody.flush();
          await saving;
        }, () => window.dispatchEvent(new HashChangeEvent("hashchange"))) }, "✨"),
        h("button", { type: "button", class: "note-tool", title: "Ask a model: format this note, enhance it, or write something new", "aria-label": "Ask a model about this note", onclick: () => void noteChatDialog(page.id, async () => {
          saveBody.flush();
          await saving;
        }, () => window.dispatchEvent(new HashChangeEvent("hashchange"))) }, "💬"),
        h("button", { type: "button", class: "note-tool", title: "Delete this note", "aria-label": "Delete this note", onclick: async () => {
          saveBody.flush();
          await saving;
          await api.del(`/api/pages/${page.id}`);
          toast(`Deleted “${page.title}”.`, "info", 7000, { label: "Undo", run: async () => {
            try {
              await api.post(`/api/pages/${page.id}/restore`, {});
              location.hash = `#/notes/${page.id}`;
            } catch (e) {
              toast((e as Error).message, "error");
            }
          } });
          location.hash = "#/notes";
        } }, "🗑")),
      page.daily ? h("div", { class: "kicker" }, `Daily note · ${niceDaily(page.daily)}`) : null,
      title,
      bodyBox);
    renderBody();
  };

  // ---------------------------------------------------------------- around the note: backlinks, mentions, map
  const drawMap = (): HTMLElement | null => {
    if (!cur || cur.graph.nodes.length < 2) return null;
    const g = cur.graph;
    const W = 280;
    const H = 200;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const canvas = h("canvas", { class: "note-map", width: W * dpr, height: H * dpr, role: "img", "aria-label": `A map of ${g.nodes.length} linked notes` });
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string) => css.getPropertyValue(name).trim() || "#888";
    const others = g.nodes.filter((n) => n.id !== cur!.id).slice(0, 12);
    const pos = new Map<string, [number, number]>([[cur.id, [W / 2, H / 2]]]);
    others.forEach((n, i) => {
      const a = (i / others.length) * Math.PI * 2 - Math.PI / 2;
      pos.set(n.id, [W / 2 + Math.cos(a) * 100, H / 2 + Math.sin(a) * 66]);
    });
    ctx.scale(dpr, dpr);
    ctx.strokeStyle = color("--muted");
    ctx.globalAlpha = 0.45;
    for (const [a, b] of g.edges) {
      const p = pos.get(a);
      const q = pos.get(b);
      if (!p || !q) continue;
      ctx.beginPath();
      ctx.moveTo(p[0], p[1]);
      ctx.lineTo(q[0], q[1]);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.font = `11px ${css.getPropertyValue("--ui-font") || "sans-serif"}`;
    ctx.textAlign = "center";
    for (const n of [...others, { id: cur.id, title: cur.title }]) {
      const p = pos.get(n.id)!;
      const me = n.id === cur.id;
      ctx.fillStyle = color("--accent");
      ctx.globalAlpha = me ? 1 : 0.7;
      ctx.beginPath();
      ctx.arc(p[0], p[1], me ? 7 : 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = color("--text");
      ctx.fillText(n.title.length > 18 ? `${n.title.slice(0, 17)}…` : n.title, p[0], p[1] + (me ? 20 : 17));
    }
    canvas.addEventListener("click", (e) => {
      const r = canvas.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * W;
      const y = ((e.clientY - r.top) / r.height) * H;
      const hit = others.find((n) => Math.hypot(pos.get(n.id)![0] - x, pos.get(n.id)![1] - y) < 20);
      if (hit) location.hash = `#/notes/${hit.id}`;
    });
    return canvas;
  };

  const renderAround = () => {
    clear(around);
    if (!cur) return;
    const page = cur;
    const map = drawMap();
    const heads: { level: number; text: string; line: number }[] = [];
    let fenced = false;
    page.body.split("\n").forEach((l, i) => {
      if (/^```/.test(l)) fenced = !fenced;
      const m = fenced ? null : l.match(/^(#{1,4})\s+(.*\S)\s*$/);
      if (m) heads.push({ level: m[1].length, text: m[2].replace(/\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]/g, (_s, a: string, b?: string) => b || a).replace(/[*`=]/g, ""), line: i });
    });
    const jump = (line: number) => {
      if (mode === "read") return main.querySelector(`.note-read [data-line="${line}"]`)?.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
      if (!area) return;
      const at = page.body.split("\n").slice(0, line).join("\n").length + (line ? 1 : 0);
      area.focus();
      area.setSelectionRange(at, at);
    };
    // what else belongs to this note: the day it is for, and the tasks that came from it. Asked once per note.
    if (extra?.id !== page.id) {
      extra = { id: page.id, day: null, tasks: [], near: [] };
      const mine = extra;
      const again = () => cur?.id === mine.id && extra === mine && renderAround();
      if (page.daily) void api.get<DaySummary>(`/api/day/${page.daily}`).then((d) => ((mine.day = d), again()), () => undefined);
      void api.get<Related>(`/api/related?kind=page&id=${page.id}`).then((r) => ((mine.tasks = r.tasks), r.tasks.length && again()), () => undefined);
      if (!page.daily) void api.get<{ similar: Near[] }>(`/api/think/similar?kind=page&id=${page.id}`).then((r) => ((mine.near = r.similar), r.similar.length && again()), () => undefined);
    }
    const dayInfo = extra.day;
    const dayBlock = page.daily && dayInfo ? h("div", { class: "around-block" }, h("h2", null, "This day"),
      h("p", { class: "around-day" }, [`${dayInfo.focus_min} min focused`, `${dayInfo.tasks_done.length} task${dayInfo.tasks_done.length === 1 ? "" : "s"} done`, dayInfo.routine_steps ? `${dayInfo.routine_steps} routine step${dayInfo.routine_steps === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ")),
      dayInfo.tasks_done.length ? h("ul", { class: "around-done" }, dayInfo.tasks_done.slice(0, 6).map((t) => h("li", null, "✓ ", t)), dayInfo.tasks_done.length > 6 ? h("li", { class: "muted" }, `and ${dayInfo.tasks_done.length - 6} more`) : null) : null,
      h("div", { class: "around-chips" },
        h("a", { href: `#/journal/${page.daily}`, class: "wikilink kind-page" }, dayInfo.journal ? `📔 Journal page${dayInfo.journal.weather ? ` · ${dayInfo.journal.weather}` : ""}` : "📔 Write the journal page"),
        page.daily === todayYmd() ? h("a", { href: "#/plan", class: "wikilink kind-page" }, "☑ Plan") : null)) : null;
    const taskBlock = extra.tasks.length ? h("div", { class: "around-block" }, h("h2", null, "Tasks from this note", h("span", { class: "plan-count" }, String(extra.tasks.length))),
      h("ul", { class: "around-list" }, extra.tasks.map((t) => h("li", null, h("a", { href: "#/plan" }, "☑ ", t.text), h("span", { class: "around-context" }, `${t.due ?? "anytime"} · ${t.minutes} min`))))) : null;
    const linkedIds = new Set([...page.backlinks.map((b) => b.id), ...page.outgoing.map((o) => o.id)]);
    const nearBlock = extra.near.length ? h("div", { class: "around-block" }, h("h2", null, "Similar"),
      h("ul", { class: "around-list" }, extra.near.map((n) => h("li", null,
        h("a", { href: n.kind === "page" ? `#/notes/${n.id}` : `#/think/idea/${n.id}` }, n.kind === "idea" ? "💡 " : "", n.title),
        h("span", { class: "around-context" }, `shares ${n.shared.join(", ")}${n.kind === "page" && !linkedIds.has(n.id) ? " · not linked yet" : ""}`)))),
      h("a", { class: "around-more", href: `#/think/page/${page.id}` }, "Think about this note →")) : null;
    add(around,
      dayBlock,
      taskBlock,
      nearBlock,
      heads.length >= 2 ? h("div", { class: "around-block" }, h("h2", null, "Outline"),
        h("ul", { class: "around-outline" }, heads.map((x) => h("li", { style: { paddingLeft: `${(x.level - 1) * 0.9}em` } }, h("button", { type: "button", class: "link", onclick: () => jump(x.line) }, x.text))))) : null,
      h("div", { class: "around-block" }, h("h2", null, "Links here", page.backlinks.length ? h("span", { class: "plan-count" }, String(page.backlinks.length)) : null),
        page.backlinks.length
          ? h("ul", { class: "around-list" }, page.backlinks.map((b) => h("li", null, h("a", { href: `#/notes/${b.id}` }, b.title), b.context ? h("span", { class: "around-context" }, b.context) : null)))
          : h("p", { class: "muted small" }, "No note links here yet. Write [[", page.title, "]] in another note and it shows up.")),
      page.mentions.length ? h("div", { class: "around-block" }, h("h2", null, "Mentioned, not linked"),
        h("ul", { class: "around-list" }, page.mentions.map((m) => h("li", null,
          h("div", { class: "row between" }, h("a", { href: `#/notes/${m.id}` }, m.title), h("button", { type: "button", class: "btn small", title: `Turn the mention in “${m.title}” into a link`, onclick: async () => {
            try {
              cur = { ...(await api.post<NotePage>(`/api/pages/${page.id}/link-mention`, { from_id: m.id })), body: cur?.body ?? page.body };
              renderAround();
              void refreshList();
              toast("Linked.", "ok", 2000);
            } catch (e) {
              toast((e as Error).message, "error");
            }
          } }, "Link it")),
          m.context ? h("span", { class: "around-context" }, m.context) : null)))) : null,
      page.outgoing.length ? h("div", { class: "around-block" }, h("h2", null, "Goes to"),
        h("div", { class: "around-chips" }, page.outgoing.map((o) => h("a", { href: "#", class: `wikilink kind-${o.kind}`, onclick: (e: Event) => (e.preventDefault(), void follow(o.kind === "missing" ? o.title : o.key)) }, KIND_ICON[o.kind], o.title)))) : null,
      h("div", { class: "around-block" }, h("h2", null, "Map"), map ?? h("p", { class: "muted small" }, "Link this note to another one and a small map of its neighbours appears here.")));
  };

  // ---------------------------------------------------------------- keys
  const onKey = (e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "e" && cur && !document.querySelector(".modal-back")) {
      e.preventDefault();
      setMode(mode === "read" ? "write" : "read");
      return;
    }
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key.toLowerCase() === "n") (e.preventDefault(), void openNew());
  };
  document.addEventListener("keydown", onKey);

  renderList();
  renderMain();
  renderAround();
  if (cur && mode === "write") (area as HTMLTextAreaElement | null)?.focus();
  return () => {
    document.removeEventListener("keydown", onKey);
    saveBody.flush();
  };
}

// ------------------------------------------------------------------ every note as a table (properties are columns)
async function tableView(root: HTMLElement): Promise<() => void> {
  const listing = await api.get<NoteList>("/api/pages?q=&tag=");
  let tag = lastTag;
  let text = "";
  let sortBy = "updated";
  let dir: 1 | -1 = -1;
  // the properties used most become the columns
  const count = new Map<string, number>();
  for (const p of listing.pages) for (const k of Object.keys(p.props)) count.set(k, (count.get(k) ?? 0) + 1);
  const cols = [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 6).map(([k]) => k);
  const body = h("div", { class: "isle notes-table-box" });
  const filter = h("input", { type: "search", placeholder: "Filter…", "aria-label": "Filter the table" });
  const tags = h("div", { class: "notes-tags" });
  const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const value = (p: NoteList["pages"][number], col: string): string =>
    col === "title" ? (p.daily ?? p.title) : col === "tags" ? p.tags : col === "updated" ? p.updated_at : col === "created" ? p.created_at : (p.props[col] ?? "");
  const draw = () => {
    clear(tags);
    listing.tags.forEach((t) => tags.append(h("button", { type: "button", class: `md-tag ${tag === t.tag ? "is-on" : ""}`, "aria-pressed": String(tag === t.tag), onclick: () => {
      tag = lastTag = tag === t.tag ? "" : t.tag;
      draw();
    } }, `#${t.tag}`)));
    const q = text.toLowerCase();
    const rows = listing.pages
      .filter((p) => (!tag || p.tags.split(" ").includes(tag)) && (!q || `${p.title} ${p.tags} ${Object.values(p.props).join(" ")}`.toLowerCase().includes(q)))
      .sort((a, b) => {
        const x = value(a, sortBy);
        const y = value(b, sortBy);
        if (!x !== !y) return x ? -1 : 1; // empty cells go last, whichever way it is sorted
        return x.localeCompare(y, undefined, { numeric: true, sensitivity: "base" }) * dir;
      });
    const th = (label: string, col: string) => h("th", { scope: "col", "aria-sort": sortBy === col ? (dir === 1 ? "ascending" : "descending") : "none" },
      h("button", { type: "button", class: "th-btn", title: "Sort by this column", onclick: () => {
        if (sortBy === col) dir = dir === 1 ? -1 : 1;
        else (sortBy = col), (dir = col === "updated" || col === "created" ? -1 : 1);
        draw();
      } }, label, sortBy === col ? (dir === 1 ? " ↑" : " ↓") : ""));
    clear(body);
    if (!rows.length) {
      body.append(h("p", { class: "muted" }, listing.pages.length ? "No note matches. Clear the filter to see them all." : "No notes yet. Write one and it shows up here."));
      return;
    }
    body.append(h("div", { class: "md-table-wrap" }, h("table", { class: "md-table notes-table" },
      h("thead", null, h("tr", null, th("Note", "title"), th("Tags", "tags"), cols.map((c) => th(c.charAt(0).toUpperCase() + c.slice(1), c)), th("Changed", "updated"))),
      h("tbody", null, rows.map((p) => h("tr", null,
        h("th", { scope: "row" }, h("a", { href: `#/notes/${p.id}` }, p.pinned ? "★ " : "", p.daily ? niceDaily(p.daily) : p.title)),
        h("td", null, p.tags ? p.tags.split(" ").map((t) => h("span", { class: "md-tag" }, `#${t}`)) : null),
        cols.map((c) => h("td", null, p.props[c] ?? "")),
        h("td", { class: "muted small" }, day(p.updated_at))))))),
      h("p", { class: "muted small notes-table-foot" }, `${rows.length} of ${listing.pages.length} note${listing.pages.length === 1 ? "" : "s"}`));
  };
  filter.addEventListener("input", () => {
    text = filter.value.trim();
    draw();
  });
  root.append(h("section", { class: "notes-wide" },
    h("div", { class: "isle page-head" },
      h("div", { class: "row between wrap" }, h("a", { class: "btn ghost", href: "#/notes" }, "← Notes"), h("a", { class: "btn ghost", href: "#/notes/map" }, "🕸 Map")),
      h("h1", null, "Notes as a table"),
      h("p", { class: "muted" }, "A line like ", h("code", null, "status:: reading"), " in a note is a property. The properties you use most are the columns here. Click a column to sort by it."),
      h("div", { class: "notes-table-tools" }, filter, tags)),
    body));
  draw();
  return () => undefined;
}

// ------------------------------------------------------------------ the big map: every note and the links between notes
async function bigMap(root: HTMLElement): Promise<() => void> {
  const g = await api.get<NoteGraph>("/api/pages/graph");
  let showDaily = false;
  let hover = "";
  const box = h("div", { class: "isle notes-map-box" });
  const info = h("p", { class: "muted small notes-map-info", "aria-live": "polite" });
  const canvas = h("canvas", { class: "notes-map", role: "img" });
  type P = { id: string; title: string; x: number; y: number; deg: number };
  let pts: P[] = [];
  let edges: [number, number][] = [];
  let near = new Map<string, Set<string>>();

  /** places the notes: linked notes pull together, all notes push apart. Worked out once, not animated. */
  const layout = () => {
    const nodes = g.nodes.filter((n) => showDaily || !n.daily);
    const at = new Map(nodes.map((n, i) => [n.id, i]));
    edges = g.edges.filter(([a, b]) => at.has(a) && at.has(b)).map(([a, b]) => [at.get(a)!, at.get(b)!]);
    pts = nodes.map((n, i) => {
      const r = 0.06 + 0.9 * Math.sqrt((i + 0.5) / nodes.length); // a sunflower: even, and the same every time
      const a = i * 2.399963;
      return { id: n.id, title: n.daily ? niceDaily(n.daily) : n.title, x: Math.cos(a) * r, y: Math.sin(a) * r, deg: 0 };
    });
    near = new Map(pts.map((p) => [p.id, new Set<string>()]));
    for (const [a, b] of edges) {
      pts[a].deg++;
      pts[b].deg++;
      near.get(pts[a].id)!.add(pts[b].id);
      near.get(pts[b].id)!.add(pts[a].id);
    }
    const n = pts.length;
    const k = 1.1 / Math.sqrt(Math.max(1, n));
    for (let step = 0; step < (n > 250 ? 90 : 180); step++) {
      const heat = 0.08 * (1 - step / 180) + 0.004;
      const dx = new Float64Array(n);
      const dy = new Float64Array(n);
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          let ux = pts[i].x - pts[j].x;
          let uy = pts[i].y - pts[j].y;
          let d2 = ux * ux + uy * uy;
          if (d2 < 1e-6) (ux = 0.001 * (i - j)), (uy = 0.001), (d2 = 1e-6);
          const f = (k * k) / d2;
          dx[i] += ux * f;
          dy[i] += uy * f;
          dx[j] -= ux * f;
          dy[j] -= uy * f;
        }
      }
      for (const [a, b] of edges) {
        const ux = pts[a].x - pts[b].x;
        const uy = pts[a].y - pts[b].y;
        const d = Math.hypot(ux, uy) || 1e-3;
        const f = (d * d) / k / d;
        dx[a] -= ux * f * 0.5;
        dy[a] -= uy * f * 0.5;
        dx[b] += ux * f * 0.5;
        dy[b] += uy * f * 0.5;
      }
      for (let i = 0; i < n; i++) {
        dx[i] -= pts[i].x * 0.9 * k; // a soft pull to the middle keeps lone notes in sight
        dy[i] -= pts[i].y * 0.9 * k;
        const d = Math.hypot(dx[i], dy[i]) || 1e-9;
        const move = Math.min(d, heat);
        pts[i].x += (dx[i] / d) * move;
        pts[i].y += (dy[i] / d) * move;
      }
    }
    // fit into -1..1
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const half = Math.max(x1 - x0, y1 - y0) / 2 || 1; // one scale for both directions keeps the shape
    const zoom = Math.min(1, 0.45 + n / 18); // a handful of notes stays a small group in the middle
    for (const p of pts) {
      p.x = ((p.x - (x0 + x1) / 2) / half) * zoom;
      p.y = ((p.y - (y0 + y1) / 2) / half) * zoom;
    }
  };

  let W = 0;
  let H = 0;
  const px = (p: P): [number, number] => [44 + ((p.x + 1) / 2) * (W - 88), 30 + ((p.y + 1) / 2) * (H - 70)];
  const radius = (p: P) => 4 + Math.min(7, p.deg * 1.2);
  const paint = () => {
    W = Math.max(280, box.clientWidth - 2);
    H = Math.max(300, Math.min(700, Math.round(window.innerHeight * 0.56)));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string) => css.getPropertyValue(name).trim() || "#888";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const lit = hover ? near.get(hover) : null;
    ctx.lineWidth = 1;
    for (const [a, b] of edges) {
      const on = !hover || pts[a].id === hover || pts[b].id === hover;
      ctx.strokeStyle = on && hover ? color("--accent") : color("--muted");
      ctx.globalAlpha = hover ? (on ? 0.9 : 0.08) : 0.4;
      const [x, y] = px(pts[a]);
      const [u, v] = px(pts[b]);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(u, v);
      ctx.stroke();
    }
    ctx.font = `12px ${css.getPropertyValue("--ui-font").trim() || "sans-serif"}`;
    ctx.textAlign = "center";
    const labelAll = pts.length <= 50;
    for (const p of pts) {
      const [x, y] = px(p);
      const on = !hover || p.id === hover || !!lit?.has(p.id);
      ctx.globalAlpha = on ? 1 : 0.2;
      ctx.fillStyle = p.deg ? color("--accent") : color("--muted");
      ctx.beginPath();
      ctx.arc(x, y, radius(p) + (p.id === hover ? 2 : 0), 0, Math.PI * 2);
      ctx.fill();
      if (labelAll || p.deg >= 3 || (hover && on)) {
        ctx.fillStyle = color("--text");
        ctx.fillText(p.title.length > 24 ? `${p.title.slice(0, 23)}…` : p.title, x, y + radius(p) + 14);
      }
    }
    ctx.globalAlpha = 1;
  };
  const hit = (e: MouseEvent): P | null => {
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    let best: P | null = null;
    let bestD = 18;
    for (const p of pts) {
      const [u, v] = px(p);
      const d = Math.hypot(u - x, v - y);
      if (d < bestD) (best = p), (bestD = d);
    }
    return best;
  };
  canvas.addEventListener("mousemove", (e) => {
    const p = hit(e);
    const id = p?.id ?? "";
    canvas.style.cursor = p ? "pointer" : "default";
    if (id === hover) return;
    hover = id;
    info.textContent = p ? `${p.title} · ${p.deg} link${p.deg === 1 ? "" : "s"}` : summary();
    paint();
  });
  canvas.addEventListener("mouseleave", () => {
    if (!hover) return;
    hover = "";
    info.textContent = summary();
    paint();
  });
  canvas.addEventListener("click", (e) => {
    const p = hit(e);
    if (p) location.hash = `#/notes/${p.id}`;
  });
  const summary = () => `${pts.length} note${pts.length === 1 ? "" : "s"} · ${edges.length} link${edges.length === 1 ? "" : "s"}${g.total > g.nodes.length ? ` · the ${g.nodes.length} most recent are shown` : ""}. Point at a note to see its neighbours; click to open it.`;
  const listBox = h("details", { class: "notes-map-list" });
  const draw = () => {
    layout();
    clear(box);
    clear(listBox);
    if (pts.length < 2) {
      box.append(h("p", { class: "muted" }, "The map needs at least two notes. Link them with [[double brackets]] and lines appear between them."));
      return;
    }
    canvas.setAttribute("aria-label", `A map of ${pts.length} notes and ${edges.length} links. The same notes are in the list below the map.`);
    info.textContent = summary();
    listBox.append(h("summary", null, "The same notes as a list"),
      h("ul", null, [...pts].sort((a, b) => b.deg - a.deg || a.title.localeCompare(b.title)).map((p) => h("li", null, h("a", { href: `#/notes/${p.id}` }, p.title), h("span", { class: "muted small" }, ` · ${p.deg} link${p.deg === 1 ? "" : "s"}`)))));
    box.append(canvas, info, listBox);
    paint();
  };
  const daily = h("input", { type: "checkbox", checked: showDaily, onchange: () => {
    showDaily = daily.checked;
    draw();
  } });
  root.append(h("section", { class: "notes-wide" },
    h("div", { class: "isle page-head" },
      h("div", { class: "row between wrap" }, h("a", { class: "btn ghost", href: "#/notes" }, "← Notes"), h("a", { class: "btn ghost", href: "#/notes/table" }, "▦ Table")),
      h("h1", null, "The map of your notes"),
      h("p", { class: "muted" }, "Every dot is a note, every line a [[link]]. Notes with more links are bigger. Grey dots are not linked to anything yet."),
      g.nodes.some((n) => n.daily) ? h("label", { class: "toggle" }, daily, " Show daily notes too") : null),
    box));
  draw();
  const onResize = debounce(() => pts.length >= 2 && paint(), 150);
  window.addEventListener("resize", onResize);
  return () => window.removeEventListener("resize", onResize);
}
