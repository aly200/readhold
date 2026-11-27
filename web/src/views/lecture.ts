// The lecture desk: the page as it was shown (PDF page, rebuilt slide, or a sealed web page), the
// theme's world around it, and a notebook beside it.
// Ways to take notes: typed notes (with math), question cards (they join your reviews), snips of a
// region of the slide, sketches, ink written straight onto the page, recall-before-reveal, and a
// Cornell sheet for the whole lecture.
// A notebook (no file) uses the same desk: its pages are paper you type on and write over with the pen.
import { ambience } from "../ambience";
import { api, save } from "../api";
import { inkKeys, InkPad, inkToolbar } from "../ink";
import { mathText } from "../math";
import { connectedCard } from "../related";
import { saveSettings, state } from "../state";
import { isDark } from "../themes";
import { timerMenu } from "../timer";
import type { Lecture, LectureNote, LecturePage, Paper, SlideEl } from "../types";
import { append, askText, clear, confirmBox, debounce, h, isTyping, type ModalHandle, modal, toast } from "../util";

type Mode = "read" | "pen" | "snip";
type Tab = "page" | "all" | "cornell" | "links"; // links = the notes and tasks that point at this study file

// Sticky-note colours for typed notes (stored by name; the colours live in styles.css)
const STICKY = ["sun", "mint", "sky", "lilac", "peach", "rose"] as const;
type Sticky = (typeof STICKY)[number];
const STICKY_NAME: Record<Sticky, string> = { sun: "Sunny yellow", mint: "Mint", sky: "Sky blue", lilac: "Lilac", peach: "Peach", rose: "Rose" };
const stickyOf = (c: string): Sticky => ((STICKY as readonly string[]).includes(c) ? (c as Sticky) : "sun");
const PAPERS: [Paper, string][] = [["lined", "Paper: lined"], ["dotted", "Paper: dotted"], ["grid", "Paper: grid"], ["plain", "Paper: plain"]];
const paperOf = (p: LecturePage): Paper => p.layout?.paper ?? "lined";

// ------------------------------------------------------------------ page rendering (shared by stage, thumbnails, snips)
function pptRun(text: string, r: { b: boolean; i: boolean; size: number | null; color: string | null }, fallback: number, slideW: number): HTMLElement {
  const pt = r.size ?? fallback;
  return h("span", { style: { fontWeight: r.b ? "700" : "", fontStyle: r.i ? "italic" : "", color: r.color ?? "", fontSize: `${(pt / slideW) * 100}cqw` } }, text);
}

function slideEl(lec: Lecture, el: SlideEl, slideW: number): HTMLElement {
  const box = { left: `${el.x}%`, top: `${el.y}%`, width: `${el.w}%`, height: `${el.h}%` };
  if (el.type === "image" && el.src) {
    return h("img", { class: "sl-img", src: `/api/lectures/${lec.id}/assets/${encodeURIComponent(el.src)}`, alt: "", loading: "lazy", style: box });
  }
  if (el.type === "box") return h("div", { class: "sl-box", style: { ...box, background: el.fill ?? "" } });
  if (el.type === "table" && el.rows) {
    const cols = Math.max(1, ...el.rows.map((r) => r.length));
    return h("div", { class: "sl-table", style: { ...box, gridTemplateColumns: `repeat(${cols}, 1fr)`, fontSize: `${(14 / slideW) * 100}cqw` } },
      el.rows.flatMap((r, ri) => r.map((c) => h("div", { class: ri === 0 ? "th" : "" }, c))));
  }
  const paras = el.paras ?? [];
  const bullets = !el.title && paras.filter((p) => p.runs.length).length > 1;
  return h(
    "div",
    { class: `sl-text ${el.title ? "title" : ""}`, style: { ...box, background: el.fill ?? "" } },
    paras.map((p) => h("p", { class: bullets ? "bul" : "", style: { paddingLeft: bullets ? `calc(${p.level * 4}% + 1em)` : `${p.level * 4}%`, textAlign: p.align || "" } },
      p.runs.map((r) => pptRun(r.t, r, p.default, slideW)))),
  );
}

export function pageView(lec: Lecture, p: LecturePage, opts: { width?: number } = {}): HTMLElement {
  const ratio = p.width && p.height ? `${p.width} / ${p.height}` : "4 / 3";
  if (lec.kind === "pdf") {
    const w = Math.min(2000, Math.round((opts.width ?? 1200) * Math.min(window.devicePixelRatio || 1, 2)));
    return h("div", { class: "page-sheet", style: { aspectRatio: ratio } },
      h("img", { src: `/api/lectures/${lec.id}/pages/${p.ord}/image?w=${w}`, alt: p.title || `Page ${p.ord + 1}`, loading: "lazy", decoding: "async", draggable: "false" }));
  }
  if (lec.kind === "pptx" && p.layout) {
    return h("div", { class: "page-sheet slide", style: { aspectRatio: ratio, background: p.layout.bg ?? "#ffffff" } },
      (p.layout.els ?? []).map((el) => slideEl(lec, el, p.width || 720)));
  }
  if (lec.kind === "notebook") {
    // a thumbnail of your page: its paper and the start of what you wrote (as text, never HTML)
    return h("div", { class: `page-sheet nb-paper paper-${paperOf(p)}`, style: { aspectRatio: ratio } },
      h("div", { class: "paper-preview" }, (p.text ?? "").slice(0, 700)));
  }
  return h("div", { class: "page-sheet", style: { aspectRatio: ratio } });
}

/** A snipped region of a page, shown at its own size: the full page, scaled and shifted inside a window. */
function snipView(lec: Lecture, p: LecturePage, r: { x: number; y: number; w: number; h: number }): HTMLElement {
  const pw = p.width || 4;
  const ph = p.height || 3;
  const inner = h("div", { class: "snip-inner", style: { width: `${100 / r.w}%`, left: `${(-r.x / r.w) * 100}%`, top: `${(-r.y / r.h) * 100}%` } }, pageView(lec, p, { width: 900 }));
  return h("div", { class: "snip-window", style: { aspectRatio: `${r.w * pw} / ${r.h * ph}` } }, inner);
}

// ------------------------------------------------------------------ the view
export async function lectureView(root: HTMLElement, id: string): Promise<() => void> {
  const lec = await api.get<Lecture>(`/api/lectures/${id}`);
  let notes = await api.get<LectureNote[]>(`/api/lectures/${id}/notes`);
  let page = Math.min(lec.position, lec.pages - 1);
  let mode: Mode = "read";
  let tab: Tab = "page";
  let recallMode = false;
  let focus = false;
  let pad: InkPad | null = null;
  let padBar: HTMLElement | null = null;
  const cleanups: (() => void)[] = [];
  let previews: InkPad[] = []; // read-only sketch previews in the notebook, rebuilt with it
  let editingSketch: string | null = null; // the sketch being drawn in place, in the notebook
  let live: { pad: InkPad; bar: HTMLElement; caption: HTMLInputElement; note: LectureNote } | null = null;
  let stageCleanup: (() => void) | null = null;
  const isHtml = lec.kind === "html";
  const isBook = lec.kind === "notebook"; // blank pages you write on (no imported file)
  let nextColor: Sticky = "sun"; // colour of the next sticky note
  const saveText = debounce((ord: number, text: string) => void save("patch", `/api/lectures/${id}/pages/${ord}`, { text }), 600);
  cleanups.push(() => saveText.flush());

  const desk = h("div", { class: `lecture-desk tint-${lec.page_tint}` });
  const thumbs = h("nav", { class: "lec-thumbs", "aria-label": "Pages" });
  const stage = h("div", { class: "lec-stage" });
  const book = h("aside", { class: "lec-book", "aria-label": "Notebook" });
  const top = h("header", { class: "lec-top" });
  root.append(h("div", { class: "lecture-view" }, top, h("div", { class: isHtml ? "lec-body single" : "lec-body" }, thumbs, stage, book)));
  root.querySelector(".lecture-view")!.prepend(desk);
  ambience.update({ mode: "reading" });
  const body = root.querySelector<HTMLElement>(".lec-body")!;

  // The notebook's width (drag its left edge; double-click for automatic) and its text size are yours to set.
  const applyBookSize = () => {
    const w = Number(state.settings.notebook_width) || 0;
    if (w > 0) body.style.setProperty("--book-w", `${w}px`);
    else body.style.removeProperty("--book-w");
    book.style.setProperty("--note-scale", String(Number(state.settings.note_scale) || 1));
  };
  applyBookSize();
  const bookGrip = h("div", { class: "book-grip", role: "separator", "aria-orientation": "vertical", "aria-label": "Notebook width", title: "Drag to resize the notebook · double-click for automatic" });
  bookGrip.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try {
      bookGrip.setPointerCapture(e.pointerId);
    } catch {
      /* released already */
    }
    const box = body.getBoundingClientRect();
    let width = 0;
    const move = (ev: PointerEvent) => {
      width = Math.round(Math.min(Math.max(box.right - ev.clientX, 260), box.width * 0.62));
      body.style.setProperty("--book-w", `${width}px`);
      fitFrame();
    };
    const up = () => {
      bookGrip.removeEventListener("pointermove", move);
      bookGrip.removeEventListener("pointerup", up);
      bookGrip.removeEventListener("pointercancel", up);
      if (width) void saveSettings({ notebook_width: width });
    };
    bookGrip.addEventListener("pointermove", move);
    bookGrip.addEventListener("pointerup", up);
    bookGrip.addEventListener("pointercancel", up);
  });
  bookGrip.addEventListener("dblclick", () => {
    void saveSettings({ notebook_width: 0 });
    applyBookSize();
    fitFrame();
  });
  const noteScale = (delta: number) => {
    const next = Math.round(Math.min(1.6, Math.max(0.8, (Number(state.settings.note_scale) || 1) + delta)) * 10) / 10;
    void saveSettings({ note_scale: next });
    applyBookSize();
  };

  const savePos = debounce((p: number) => save("patch", `/api/lectures/${id}`, { position: p }), 600);
  const notesOn = (p: number | null) => notes.filter((n) => n.page === p);
  const cur = () => lec.page_list[page];

  // ---------------------------------------------------------------- top bar
  const renderTop = () => {
    clear(top);
    const tint = h("select", { "aria-label": "Page tint", onchange: (e: Event) => {
      const v = (e.target as HTMLSelectElement).value as Lecture["page_tint"];
      lec.page_tint = v;
      desk.className = `lecture-desk tint-${v}`;
      stage.classList.remove("tint-normal", "tint-dim", "tint-sepia", "tint-night");
      stage.classList.add(`tint-${v}`);
      void save("patch", `/api/lectures/${id}`, { page_tint: v });
    } }, [["normal", "Pages: as is"], ["dim", "Pages: dimmed"], ["sepia", "Pages: warm"], ["night", "Pages: night"]].map(([v, l]) => h("option", { value: v }, l)));
    tint.value = lec.page_tint;
    const modeBtn = (m: Mode, label: string, key: string) =>
      h("button", { class: `btn small ${mode === m ? "on" : ""}`, title: `${label} (${key})`, disabled: isHtml && m === "snip" ? true : undefined, onclick: () => setMode(mode === m ? "read" : m) }, label);
    const paperSel = h("select", { "aria-label": "Paper for this page", onchange: (e: Event) => {
      const v = (e.target as HTMLSelectElement).value as Paper;
      const p = cur();
      p.layout = { ...(p.layout ?? {}), paper: v };
      frame?.querySelector(".page-sheet")?.classList.remove("paper-lined", "paper-dotted", "paper-grid", "paper-plain");
      frame?.querySelector(".page-sheet")?.classList.add(`paper-${v}`);
      void save("patch", `/api/lectures/${id}/pages/${p.ord}`, { paper: v });
      renderThumbs();
    } }, PAPERS.map(([v, l]) => h("option", { value: v }, l)));
    if (isBook) paperSel.value = paperOf(cur());
    const slides = !isHtml && !isBook; // tools that only make sense on imported slides
    append(top, [
      h("a", { class: "btn ghost small", href: "#/lectures" }, "← Lectures"),
      h("strong", { class: "lec-name", title: lec.title }, isBook ? h("span", { "aria-hidden": "true" }, "📒 ") : null, lec.title),
      isHtml ? null : h("span", { class: "lec-pageno" }, `${page + 1} / ${lec.pages}`),
      h("div", { class: "lec-tools" },
        modeBtn("pen", "Pen", "P"),
        slides ? modeBtn("snip", "Snip", "S") : null,
        slides ? h("button", { class: `btn small ${recallMode ? "on" : ""}`, title: "Recall before you look (R)", onclick: () => toggleRecall() }, "Recall mode") : null,
        slides ? tint : null,
        isBook ? paperSel : null,
        isBook ? h("button", { class: "btn small", title: "Add a page at the end (N)", onclick: () => void addPage() }, "+ Page") : null,
        h("button", { class: "btn small", title: "Start a focus timer for this (T)", "aria-haspopup": "menu", onclick: (e: Event) => timerMenu(e.currentTarget as HTMLElement, { label: `Study: ${lec.title}`, link_type: "lecture", link_id: id }) }, "⏱ Timer"),
        h("button", { class: `btn small ${focus ? "on" : ""}`, title: "Hide the side panels (F)", onclick: () => toggleFocus() }, "Focus"),
        h("button", { class: "btn small", title: "Copy the notebook as Markdown", onclick: exportNotes }, "Export")),
    ]);
  };

  // ---------------------------------------------------------------- thumbnails
  const renderThumbs = () => {
    clear(thumbs);
    if (isHtml) return;
    lec.page_list.forEach((p) => {
      const count = notes.filter((n) => n.page === p.ord).length;
      const t = h("button", { class: `lec-thumb ${p.ord === page ? "on" : ""}`, "aria-label": `Page ${p.ord + 1}${p.title ? `: ${p.title}` : ""}`, onclick: () => go(p.ord) },
        pageView(lec, p, { width: 240 }),
        h("span", { class: "lec-thumb-no" }, String(p.ord + 1)),
        count ? h("span", { class: "lec-thumb-notes", title: `${count} note${count > 1 ? "s" : ""}` }, String(count)) : null);
      thumbs.append(t);
    });
    if (isBook) thumbs.append(h("button", { class: "lec-thumb-add", title: "Add a page (N)", onclick: () => void addPage() }, h("span", { "aria-hidden": "true" }, "+"), " New page"));
    thumbs.querySelector<HTMLElement>(".lec-thumb.on")?.scrollIntoView({ block: "nearest" });
  };

  // ---------------------------------------------------------------- stage
  let frame: HTMLElement | null = null;
  const fitFrame = () => {
    if (!frame || isHtml) return;
    const p = cur();
    const ratio = (p.width || 4) / (p.height || 3);
    const box = stage.getBoundingClientRect();
    const availW = box.width - 48;
    const availH = box.height - 48;
    const w = Math.max(200, Math.min(availW, availH * ratio));
    frame.style.width = `${w}px`;
  };
  let fitQueued = 0;
  const ro = new ResizeObserver(() => {
    if (!fitQueued) fitQueued = requestAnimationFrame(() => { fitQueued = 0; fitFrame(); });
  });
  ro.observe(stage);
  cleanups.push(() => ro.disconnect());

  const renderStage = async () => {
    pad?.destroy();
    pad = null;
    padBar = null;
    stageCleanup?.();
    stageCleanup = null;
    clear(stage);
    stage.className = `lec-stage tint-${lec.page_tint} mode-${mode}`;
    if (isHtml) {
      await renderHtmlStage();
      return;
    }
    if (isBook) {
      await renderPaperStage();
      return;
    }
    const p = cur();
    const inkHost = h("div", { class: "ink-host" });
    frame = h("div", { class: "page-frame" }, pageView(lec, p, { width: Math.max(stage.clientWidth, 800) }), inkHost);
    stage.append(frame);
    fitFrame();
    pad = new InkPad(inkHost, { owner: `lecture_page/${id}:${p.ord}` });
    pad.setEnabled(mode === "pen");
    await pad.load();
    if (mode === "pen") {
      padBar = inkToolbar(pad, [h("button", { class: "ink-tool", onclick: () => setMode("read") }, "Done")]);
      stage.append(padBar);
    }
    if (mode === "snip") armSnip(frame);
    if (recallMode && !notes.some((n) => n.page === p.ord && n.kind === "recall")) coverForRecall(frame);
  };

  /** Web lecture: the sealed page, with a transparent ink layer on top that scrolls with it.
   * The page reports its scroll position (see lectures.SCROLL_REPORTER); in pen mode the mouse wheel is
   * forwarded to it, so you can scroll and write without leaving the pen. */
  const renderHtmlStage = async () => {
    const iframe = h("iframe", { class: "lec-iframe", src: `/api/lectures/${id}/content.html`, sandbox: "allow-scripts", referrerpolicy: "no-referrer", title: lec.title });
    const view = h("div", { class: "html-ink-view" });
    stage.append(h("div", { class: "html-frame" }, iframe, view));
    pad = new InkPad(view, { owner: `lecture_page/${id}:0` });
    pad.setEnabled(mode === "pen");
    const onMessage = (e: MessageEvent) => {
      if (e.source !== iframe.contentWindow || !e.data || e.data.readhold !== "scroll") return;
      const x = Number(e.data.x);
      const y = Number(e.data.y);
      if (Number.isFinite(x) && Number.isFinite(y) && x >= 0 && y >= 0) pad?.setOffset(x, y);
    };
    const onWheel = (e: WheelEvent) => {
      if (mode !== "pen") return;
      e.preventDefault();
      iframe.contentWindow?.postMessage({ readhold: "scroll-by", dx: e.deltaX, dy: e.deltaY }, "*");
    };
    window.addEventListener("message", onMessage);
    view.addEventListener("wheel", onWheel, { passive: false });
    stageCleanup = () => window.removeEventListener("message", onMessage);
    await pad.load();
    if (mode === "pen") {
      padBar = inkToolbar(pad, [h("button", { class: "ink-tool", onclick: () => setMode("read") }, "Done")]);
      stage.append(padBar);
    }
  };

  /** Notebook page: paper you type on (saved as you type), with the pen's ink layer over it. The ink
   * scrolls with your writing, and in pen mode the mouse wheel still scrolls the page. */
  const renderPaperStage = async () => {
    const p = cur();
    const write = h("textarea", { class: "paper-write", spellcheck: "true", "aria-label": `Page ${page + 1}: your writing`,
      placeholder: p.text ? "" : "Start writing here…  Press P (or Pen) to write and draw by hand." });
    write.value = p.text ?? "";
    const inkHost = h("div", { class: "ink-host" });
    const sheet = h("div", { class: `page-sheet nb-paper paper-${paperOf(p)}`, style: { aspectRatio: `${p.width || 850} / ${p.height || 1100}` } },
      h("span", { class: "paper-tape", "aria-hidden": "true" }), write, h("span", { class: "paper-no", "aria-hidden": "true" }, String(page + 1)));
    frame = h("div", { class: "page-frame paper-frame" }, sheet, inkHost);
    stage.append(frame);
    fitFrame();
    pad = new InkPad(inkHost, { owner: `lecture_page/${id}:${p.ord}` });
    pad.setEnabled(mode === "pen");
    write.addEventListener("input", () => {
      p.text = write.value;
      saveText(p.ord, write.value);
    });
    write.addEventListener("scroll", () => pad?.setOffset(0, write.scrollTop));
    inkHost.addEventListener("wheel", (e) => {
      if (mode !== "pen") return;
      e.preventDefault();
      write.scrollTop += e.deltaY;
    }, { passive: false });
    await pad.load();
    pad?.setOffset(0, write.scrollTop);
    if (mode === "pen") {
      padBar = inkToolbar(pad!, [h("button", { class: "ink-tool", onclick: () => setMode("read") }, "Done")]);
      stage.append(padBar);
    } else if (!write.value && !(document.activeElement instanceof HTMLTextAreaElement || document.activeElement instanceof HTMLInputElement)) {
      write.focus({ preventScroll: true }); // an empty page is ready to type on
    }
  };

  const addPage = async () => {
    if (!isBook) return;
    saveText.flush();
    const np = await api.post<LecturePage>(`/api/lectures/${id}/pages`);
    lec.page_list.push(np);
    lec.pages = lec.page_list.length;
    if (mode !== "read") mode = "read";
    go(np.ord);
  };

  const armSnip = (f: HTMLElement) => {
    const layer = h("div", { class: "snip-layer", title: "Drag over the part of the page to snip" });
    const rect = h("div", { class: "snip-rect", hidden: true });
    layer.append(rect);
    f.append(layer);
    let start: [number, number] | null = null;
    const rel = (e: PointerEvent): [number, number] => {
      const r = f.getBoundingClientRect();
      return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
    };
    const box = (a: [number, number], b: [number, number]) => ({ x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(a[0] - b[0]), h: Math.abs(a[1] - b[1]) });
    layer.addEventListener("pointerdown", (e) => {
      try {
        layer.setPointerCapture(e.pointerId);
      } catch {
        /* released already */
      }
      start = rel(e);
      rect.hidden = false;
    });
    layer.addEventListener("pointermove", (e) => {
      if (!start) return;
      const b = box(start, rel(e));
      Object.assign(rect.style, { left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` });
    });
    layer.addEventListener("pointerup", async (e) => {
      if (!start) return;
      const b = box(start, rel(e));
      start = null;
      if (b.w < 0.03 || b.h < 0.03) {
        rect.hidden = true;
        return;
      }
      const caption = await askText("Snip", "What is this? A few words help future-you.", "", { placeholder: "The update rule", okLabel: "Save snip" });
      if (caption === null) {
        rect.hidden = true;
        return;
      }
      const n = await api.post<LectureNote>(`/api/lectures/${id}/notes`, { page, kind: "snip", body: caption, data: { x: round(b.x), y: round(b.y), w: round(b.w), h: round(b.h) } });
      notes.push(n);
      setMode("read");
      tab = "page";
      renderBook();
      renderThumbs();
      toast("Snipped into your notebook.", "ok", 1800);
    });
  };
  const round = (v: number) => Math.round(v * 10000) / 10000;

  const coverForRecall = (f: HTMLElement) => {
    const area = h("textarea", { rows: 4, placeholder: "Before you look: what do you remember from this page?", "aria-label": "Recall" });
    const reveal = async () => {
      const text = area.value.trim();
      if (text) {
        const n = await api.post<LectureNote>(`/api/lectures/${id}/notes`, { page, kind: "recall", body: text });
        notes.push(n);
        renderBook();
        renderThumbs();
      }
      cover.remove();
      ambience.moment();
    };
    area.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.preventDefault(), reveal());
    });
    const cover = h("div", { class: "recall-cover" },
      h("div", { class: "recall-card" },
        h("div", { class: "kicker" }, `Page ${page + 1}${cur().title ? ` · ${cur().title}` : ""}`),
        h("p", null, "Recall first. Writing what you remember before you look is what makes it stick."),
        area,
        h("div", { class: "row end" }, h("button", { class: "btn ghost", onclick: () => cover.remove() }, "Skip"), h("button", { class: "btn primary", onclick: reveal }, "Reveal (Ctrl+Enter)"))));
    f.append(cover);
    setTimeout(() => area.focus(), 30);
  };

  // ---------------------------------------------------------------- notebook
  const noteCard = (n: LectureNote): HTMLElement => {
    const del = h("button", { class: "note-del", "aria-label": "Delete note", title: "Delete", onclick: async (e: Event) => {
      e.stopPropagation();
      if (!(await confirmBox("Delete this note?", n.body.slice(0, 120) || "This note", "Delete"))) return;
      await api.del(`/api/lecture-notes/${n.id}`);
      notes = notes.filter((x) => x.id !== n.id);
      renderBook();
      renderThumbs();
    } }, "✕");
    if (n.kind === "question") {
      const back = String(n.data.back ?? "");
      const card = h("div", { class: "note-card question", tabindex: 0, title: "Click to flip" },
        h("div", { class: "note-kind" }, "❓ Question card · in your reviews"), del,
        h("div", { class: "q-front" }, mathText(n.body)),
        h("div", { class: "q-back" }, mathText(back)));
      card.addEventListener("click", () => card.classList.toggle("flipped"));
      card.addEventListener("keydown", (e) => e.key === "Enter" && card.classList.toggle("flipped"));
      card.addEventListener("dblclick", () => void editQuestion(n));
      return card;
    }
    if (n.kind === "snip") {
      const p = lec.page_list[n.page ?? 0];
      const r = n.data as { x: number; y: number; w: number; h: number };
      return h("div", { class: "note-card snip", title: "Go to this page", onclick: () => go(n.page ?? 0) },
        h("div", { class: "note-kind" }, `✂️ Snip · page ${(n.page ?? 0) + 1}`), del, snipView(lec, p, r), n.body ? h("p", null, n.body) : null);
    }
    if (n.kind === "sketch") return sketchCard(n, del);
    if (n.kind === "recall") {
      return h("div", { class: "note-card recall" }, h("div", { class: "note-kind" }, "🧠 Recalled before looking"), del, h("blockquote", null, n.body));
    }
    // typed note: a sticky note; click to edit in place, pick its colour from the dots
    const view = h("div", { class: "note-text" }, n.body.split("\n").map((line) => h("p", null, mathText(line))));
    const card = h("div", { class: `note-card text sticky c-${stickyOf(n.color)}`, tabindex: 0, title: "Click to edit" }, del, view);
    const dots = STICKY.map((c) => h("button", { class: `sticky-dot c-${c} ${c === stickyOf(n.color) ? "on" : ""}`, title: STICKY_NAME[c], "aria-label": `Colour: ${STICKY_NAME[c]}`, onclick: (e: Event) => {
      e.stopPropagation();
      n.color = c;
      card.classList.remove(...STICKY.map((s) => `c-${s}`));
      card.classList.add(`c-${c}`);
      dots.forEach((d) => d.classList.toggle("on", d.classList.contains(`c-${c}`) && d.classList.contains("sticky-dot")));
      void save("patch", `/api/lecture-notes/${n.id}`, { color: c });
    } }));
    card.append(h("div", { class: "sticky-colors", role: "group", "aria-label": "Note colour" }, dots));
    const edit = () => {
      if (card.querySelector("textarea")) return;
      const area = h("textarea", { rows: Math.min(14, Math.max(3, n.body.split("\n").length + 1)) }, n.body);
      const done = async (keep: boolean) => {
        const text = area.value.trim();
        if (keep && text && text !== n.body) {
          await api.patch(`/api/lecture-notes/${n.id}`, { body: text });
          n.body = text;
        }
        renderBook();
      };
      area.addEventListener("keydown", (e) => {
        if (e.key === "Escape") (e.stopPropagation(), done(false));
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.preventDefault(), done(true));
      });
      area.addEventListener("blur", () => done(true));
      view.replaceWith(area);
      area.focus();
    };
    card.addEventListener("click", edit);
    card.addEventListener("keydown", (e) => e.key === "Enter" && e.target === card && edit());
    return card;
  };

  const composer = () => {
    const area = h("textarea", { rows: 3, placeholder: `Sticky note for page ${page + 1}… (Ctrl+Enter to add · $x^2$ works for math)`, "aria-label": "New note" });
    const box = h("div", { class: `composer sticky c-${nextColor}` });
    const dots = STICKY.map((c) => h("button", { class: `sticky-dot c-${c} ${c === nextColor ? "on" : ""}`, type: "button", title: STICKY_NAME[c], "aria-label": `Colour: ${STICKY_NAME[c]}`, onclick: () => {
      nextColor = c;
      box.classList.remove(...STICKY.map((s) => `c-${s}`));
      box.classList.add(`c-${c}`);
      dots.forEach((d) => d.classList.toggle("on", d.classList.contains(`c-${c}`)));
      area.focus();
    } }));
    const add = async () => {
      const text = area.value.trim();
      if (!text) return area.focus();
      // $…$ from the keyboard becomes the stored \( … \) form the renderer understands
      const body = text.replace(/\$\$([^$]+)\$\$/g, "\\[$1\\]").replace(/\$(?![\s\d])([^$\n]+?)(?<!\s)\$/g, "\\($1\\)");
      const n = await api.post<LectureNote>(`/api/lectures/${id}/notes`, { page: isHtml ? null : page, kind: "text", body, color: nextColor });
      notes.push(n);
      area.value = "";
      renderBook();
      renderThumbs();
      book.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus();
    };
    area.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.preventDefault(), add());
    });
    const title = cur()?.title ?? "";
    append(box, [
      area,
      h("div", { class: "sticky-colors always", role: "group", "aria-label": "Colour of the next note" }, dots),
      h("div", { class: "composer-actions" },
        h("button", { class: "btn small primary", onclick: add }, "Add note"),
        h("button", { class: "btn small", title: "A question card for your reviews", onclick: () => void newQuestion() }, "❓ Question card"),
        isHtml || isBook ? null : h("button", { class: "btn small", title: "Drag over part of the page (S)", onclick: () => setMode("snip") }, "✂️ Snip"),
        h("button", { class: "btn small", title: "Draw or write by hand", onclick: () => void newSketch() }, "✏️ Sketch"),
        title && !isHtml ? h("button", { class: "btn small ghost", title: "Turn this slide's title into a question", onclick: () => void newQuestion(`What is ${title.replace(/[.:]$/, "")}, and why does it matter?`) }, "Slide → question") : null),
    ]);
    return box;
  };

  const questionDialog = async (front = "", back = ""): Promise<{ front: string; back: string } | null> => {
    const f = h("textarea", { rows: 2, placeholder: "Question", autofocus: true }, front);
    const b = h("textarea", { rows: 4, placeholder: "Answer (what you'd want to recall)" }, back);
    const err = h("p", { class: "error small", hidden: true });
    let hm: ModalHandle;
    const ok = await modal("Question card", h("div", { class: "stack" },
      h("p", { class: "muted small" }, "It joins your daily review, so this lecture comes back before the exam."),
      h("label", { class: "field" }, h("span", null, "Front"), f), h("label", { class: "field" }, h("span", null, "Back"), b), err,
      h("div", { class: "row end" }, h("button", { onclick: () => hm.close(null) }, "Cancel"), h("button", { class: "primary", onclick: () => {
        if (!f.value.trim() || !b.value.trim()) {
          err.textContent = "Write both sides: a question and its answer.";
          err.hidden = false;
          return;
        }
        hm.close("ok");
      } }, "Save card"))), { onOpen: (m) => (hm = m) });
    return ok === "ok" ? { front: f.value.trim(), back: b.value.trim() } : null;
  };

  const newQuestion = async (front = "") => {
    const q = await questionDialog(front);
    if (!q) return;
    const n = await api.post<LectureNote>(`/api/lectures/${id}/notes`, { page: isHtml ? null : page, kind: "question", body: q.front, data: { back: q.back } });
    notes.push(n);
    renderBook();
    renderThumbs();
    toast("Card added to your reviews.", "ok", 1800);
  };

  const editQuestion = async (n: LectureNote) => {
    const q = await questionDialog(n.body, String(n.data.back ?? ""));
    if (!q) return;
    await api.patch(`/api/lecture-notes/${n.id}`, { body: q.front, data: { back: q.back } });
    n.body = q.front;
    n.data = { back: q.back };
    renderBook();
  };

  const sketchRatio = (n: LectureNote): number => {
    const r = Number(n.data.ratio);
    return Number.isFinite(r) && r >= 0.3 && r <= 3 ? r : 0.75;
  };

  /** A sketch right in the notebook: click to draw in place (the page stays in full view), drag the
   * bottom edge to make it taller or shorter. */
  const sketchCard = (n: LectureNote, del: HTMLElement): HTMLElement => {
    const editing = editingSketch === n.id;
    const paper = h("div", { class: `sketch-paper ${editing ? "live" : ""}`, style: { aspectRatio: `1 / ${sketchRatio(n)}` } });
    const grip = h("div", { class: "sketch-grip", role: "separator", "aria-orientation": "horizontal", "aria-label": "Sketch height", title: "Drag to make the sketch taller or shorter" });
    const card = h("div", { class: `note-card sketch ${editing ? "editing" : ""}` }, h("div", { class: "note-kind" }, editing ? "✏️ Sketch · drawing (Done to finish)" : "✏️ Sketch · click to draw"), del, paper, grip);
    grip.addEventListener("click", (e) => e.stopPropagation());
    grip.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        grip.setPointerCapture(e.pointerId);
      } catch {
        /* released already */
      }
      const r0 = paper.getBoundingClientRect();
      let ratio = sketchRatio(n);
      const move = (ev: PointerEvent) => {
        ratio = Math.min(3, Math.max(0.3, (r0.height + ev.clientY - e.clientY) / Math.max(r0.width, 1)));
        paper.style.aspectRatio = `1 / ${ratio}`;
      };
      const up = () => {
        grip.removeEventListener("pointermove", move);
        grip.removeEventListener("pointerup", up);
        grip.removeEventListener("pointercancel", up);
        n.data = { ...n.data, ratio: Math.round(ratio * 100) / 100 };
        void save("patch", `/api/lecture-notes/${n.id}`, { data: n.data });
      };
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", up);
      grip.addEventListener("pointercancel", up);
    });
    if (editing) {
      const caption = h("input", { type: "text", value: n.body, placeholder: "Caption (optional)", "aria-label": "Caption" });
      card.append(caption);
      requestAnimationFrame(() => {
        if (!paper.isConnected) return;
        const sketchPad = new InkPad(paper, { owner: `note/${n.id}`, adaptToDark: isDark });
        void sketchPad.load();
        const bar = inkToolbar(sketchPad, [h("button", { class: "ink-tool primary", onclick: () => stopSketch() }, "Done")]);
        paper.before(bar);
        live = { pad: sketchPad, bar, caption, note: n };
      });
    } else {
      if (n.body) card.append(h("p", null, n.body));
      card.title = "Click to draw";
      card.addEventListener("click", () => startSketch(n.id));
      requestAnimationFrame(() => {
        if (!paper.isConnected) return;
        const preview = new InkPad(paper, { owner: `note/${n.id}`, readonly: true, adaptToDark: isDark });
        void preview.load();
        previews.push(preview);
      });
    }
    return card;
  };

  /** Close the sketch being drawn: its ink is saved by the pad; the caption is saved here. */
  const closeLive = () => {
    if (!live) return;
    const { pad: sketchPad, caption, note } = live;
    live = null;
    sketchPad.destroy();
    const text = caption.value.trim();
    if (text !== note.body) {
      note.body = text;
      void save("patch", `/api/lecture-notes/${note.id}`, { body: text });
    }
  };

  const startSketch = (nid: string) => {
    closeLive();
    editingSketch = nid;
    renderBook();
    requestAnimationFrame(() => book.querySelector(".note-card.sketch.editing")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  };

  const stopSketch = () => {
    closeLive();
    editingSketch = null;
    renderBook();
  };

  const newSketch = async () => {
    const n = await api.post<LectureNote>(`/api/lectures/${id}/notes`, { page: isHtml ? null : page, kind: "sketch", body: "", data: { ratio: 0.75 } });
    notes.push(n);
    if (tab === "cornell") tab = "page";
    startSketch(n.id);
    renderThumbs();
  };

  const cornellSheet = () => {
    let note = notes.find((n) => n.kind === "cornell" && n.page === null) ?? null;
    const d = (note?.data ?? {}) as { cues?: string; notes?: string; summary?: string };
    const cues = h("textarea", { placeholder: "Cues: questions and keywords", "aria-label": "Cues" }, d.cues ?? "");
    const main = h("textarea", { placeholder: "Notes: what the lecture said, in your words", "aria-label": "Notes" }, d.notes ?? "");
    const summary = h("textarea", { placeholder: "Summary: the whole lecture in 3–5 sentences, written last", "aria-label": "Summary" }, d.summary ?? "");
    const status = h("span", { class: "muted small" });
    const persist = debounce(async () => {
      const data = { cues: cues.value, notes: main.value, summary: summary.value };
      if (note) {
        await api.patch(`/api/lecture-notes/${note.id}`, { data });
        note.data = data;
      } else {
        note = await api.post<LectureNote>(`/api/lectures/${id}/notes`, { page: null, kind: "cornell", data });
        notes.push(note);
      }
      status.textContent = "Saved";
      setTimeout(() => (status.textContent = ""), 1200);
    }, 700);
    [cues, main, summary].forEach((t) => t.addEventListener("input", persist));
    return h("div", { class: "cornell" },
      h("p", { class: "muted small" }, "The Cornell method: notes on the right while you study, cue questions on the left afterwards, a summary at the bottom. Cover the right side and answer the cues to review."),
      h("div", { class: "cornell-grid" }, cues, main), summary, status);
  };

  const renderBook = () => {
    closeLive();
    previews.forEach((p) => p.destroy());
    previews = [];
    clear(book);
    book.append(bookGrip);
    const tabBtn = (t: Tab, label: string) => h("button", { class: `tab ${tab === t ? "on" : ""}`, role: "tab", "aria-selected": String(tab === t), onclick: () => ((tab = t), renderBook()) }, label);
    book.append(h("div", { class: "book-head" },
      h("div", { class: "tabs", role: "tablist" }, tabBtn("page", isHtml ? "Notes" : `Page ${page + 1}`), isHtml ? null : tabBtn("all", "All notes"), tabBtn("cornell", "Cornell sheet"), tabBtn("links", "Linked")),
      h("div", { class: "note-size", role: "group", "aria-label": "Note text size" },
        h("button", { class: "btn small ghost", title: "Smaller notes", "aria-label": "Smaller notes", onclick: () => noteScale(-0.1) }, "A−"),
        h("button", { class: "btn small ghost", title: "Larger notes", "aria-label": "Larger notes", onclick: () => noteScale(0.1) }, "A+"))));
    const body = h("div", { class: "book-body" });
    book.append(body);
    if (tab === "cornell") {
      body.append(cornellSheet());
      return;
    }
    if (tab === "links") {
      body.append(h("div", { class: "book-connected" }, connectedCard("lecture", id, lec.title)));
      return;
    }
    if (tab === "page") {
      const p = cur();
      if (p?.speaker_notes) body.append(h("details", { class: "speaker-notes" }, h("summary", null, "Speaker notes"), h("p", null, p.speaker_notes)));
      body.append(composer());
      const list = isHtml ? notes.filter((n) => n.kind !== "cornell") : notesOn(page).filter((n) => n.kind !== "cornell");
      if (!list.length) body.append(h("p", { class: "empty-hint" }, isHtml ? "Notes for this page appear here." : isBook ? "Sticky notes, question cards and sketches for this page gather here." : "Nothing on this page yet. Type a note, snip part of the slide, or switch on the pen and write on it."));
      list.forEach((n) => body.append(noteCard(n)));
      return;
    }
    const groups = new Map<number, LectureNote[]>();
    notes.filter((n) => n.kind !== "cornell" && n.page !== null).forEach((n) => groups.set(n.page!, [...(groups.get(n.page!) ?? []), n]));
    if (!groups.size) body.append(h("p", { class: "empty-hint" }, "Your notes for every page will gather here."));
    [...groups.keys()].sort((a, b) => a - b).forEach((pg) => {
      body.append(h("button", { class: "book-page-head", onclick: () => go(pg) }, `Page ${pg + 1}`, lec.page_list[pg]?.title ? h("span", { class: "muted" }, ` · ${lec.page_list[pg].title}`) : null));
      groups.get(pg)!.forEach((n) => body.append(noteCard(n)));
    });
  };

  // ---------------------------------------------------------------- actions
  const go = (p: number) => {
    if (isHtml) return;
    const next = Math.max(0, Math.min(lec.pages - 1, p));
    if (next === page) return;
    pad?.flush();
    saveText.flush();
    page = next;
    savePos(page);
    ambience.update({ progress: (page + 1) / lec.pages });
    renderTop();
    renderThumbs();
    void renderStage();
    if (tab === "page") renderBook();
  };

  const setMode = (m: Mode) => {
    if ((isHtml || isBook) && m === "snip") return;
    mode = m;
    renderTop();
    void renderStage();
  };

  const toggleRecall = () => {
    if (isHtml || isBook) return;
    recallMode = !recallMode;
    renderTop();
    void renderStage();
    if (recallMode) toast("Recall mode: each page stays covered until you write what you remember.", "info", 4000);
  };

  const toggleFocus = () => {
    focus = !focus;
    root.querySelector(".lecture-view")?.classList.toggle("focus", focus);
    renderTop();
    requestAnimationFrame(fitFrame);
  };

  async function exportNotes() {
    const r = await api.get<{ markdown: string }>(`/api/lectures/${id}/export`);
    try {
      await navigator.clipboard.writeText(r.markdown);
      toast("Notebook copied as Markdown.", "ok");
    } catch {
      await modal("Your notebook (Markdown)", h("textarea", { rows: 16, readonly: true }, r.markdown), { wide: true });
    }
  }

  const onKey = (e: KeyboardEvent) => {
    if (live && !isTyping(e)) {
      if (inkKeys(live.pad, live.bar, e)) return;
      if (e.key === "Escape") return stopSketch();
    }
    if (mode === "pen" && pad && padBar && !isTyping(e) && inkKeys(pad, padBar, e)) return;
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowRight" || k === "PageDown" || k === "j") (e.preventDefault(), go(page + 1));
    else if (k === "ArrowLeft" || k === "PageUp" || k === "k") (e.preventDefault(), go(page - 1));
    else if (k === "Home") go(0);
    else if (k === "End") go(lec.pages - 1);
    else if (k.toLowerCase() === "p") setMode(mode === "pen" ? "read" : "pen");
    else if (k.toLowerCase() === "s") setMode(mode === "snip" ? "read" : "snip");
    else if (k.toLowerCase() === "r") toggleRecall();
    else if (k.toLowerCase() === "f") toggleFocus();
    else if (k.toLowerCase() === "n" && isBook) void addPage();
    else if (k.toLowerCase() === "t") {
      const btn = top.querySelector<HTMLElement>("[aria-haspopup=menu]");
      if (btn) timerMenu(btn, { label: `Study: ${lec.title}`, link_type: "lecture", link_id: id });
    }
    else if (k === "Escape" && mode !== "read") setMode("read");
  };
  document.addEventListener("keydown", onKey);
  cleanups.push(() => document.removeEventListener("keydown", onKey));

  renderTop();
  renderThumbs();
  renderBook();
  ambience.update({ progress: isHtml ? 0 : (page + 1) / lec.pages });
  await renderStage();

  return () => {
    closeLive();
    stageCleanup?.();
    pad?.destroy();
    previews.forEach((p) => p.destroy());
    cleanups.forEach((f) => f());
    ambience.update({ mode: "idle" });
  };
}
