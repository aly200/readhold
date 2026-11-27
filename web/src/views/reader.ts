// The reading screen: section map, solid reading panel, side panel, pacer bar.
// Long documents render only the sections near the viewport; the pacer only toggles classes.
import { ambience } from "../ambience";
import { comics } from "../comics";
import { api, save } from "../api";
import { Pacer, type PacerHost } from "../pacer";
import { SessionTracker } from "../session";
import { applyComfort, comfortFor, saveSettings, state } from "../state";
import { displayEquation, hasMath, mathEl, mathText, plainMath, words as mathWords, wordsWithIndex } from "../math";
import { applyTheme } from "../themes";
import type { Annotations, Doc, Highlight, HlType, Paragraph, Section, Sentence } from "../types";
import { clear, debounce, fmtClock, h, HL_KEYS, isTyping, KIND_LABELS, prefersReducedMotion, toast } from "../util";
import * as dlg from "./reader-dialogs";
import { digestDialog } from "./digest";
import { organizeDialog } from "./organize";
import { brainstormDialog, studyNotesDialog } from "./studynotes";
import { renderSidePanel } from "./reader-panels";

/** Words of a sentence; a formula counts as one word even if its LaTeX has spaces. */
export const tokens = (text: string): string[] => mathWords(text);

interface Idx {
  s: Sentence;
  p: Paragraph;
  sec: Section;
  secIdx: number;
}

const PASS1 = new Set(["abstract", "conclusion"]);
const PASS2 = new Set(["abstract", "intro", "method", "results", "discussion", "conclusion"]);
const REF_RE = /\b(Fig(?:ure)?s?\.?|Tab(?:le)?s?\.?|Eq(?:uation)?s?\.?)\s*\(?(\d+)\)?|\[(\d{1,3}(?:\s*[,–-]\s*\d{1,3})*)\]/g;

export class Reader implements PacerHost {
  doc!: Doc;
  ann!: Annotations;
  idx: Idx[] = [];
  pacer: Pacer;
  session: SessionTracker | null = null;
  pass = 0; // 0 = all, 1..3 = three-pass plan
  isPaper = false;
  focusView = false;
  panelsHidden = false; // the map and the side panel folded away (a setting, so it holds after a restart)
  showHidden = false;

  root!: HTMLElement;
  scroller!: HTMLElement;
  paper!: HTMLElement;
  mapEl!: HTMLElement;
  sideEl!: HTMLElement;
  barEl!: HTMLElement;
  topEl!: HTMLElement;
  focusWordEl!: HTMLElement;
  sideTab: "questions" | "notes" | "terms" | "ask" = "questions";

  secEls: HTMLElement[] = [];
  rendered: boolean[] = [];
  sentEls = new Map<number, HTMLElement>();
  parEls = new Map<string, HTMLElement>();
  hlByOrd = new Map<number, Highlight[]>();
  peeks = new Map<string, string>();
  /** Equation numbers whose formula is a picture cropped from the PDF: key → image URL. */
  peekImages = new Map<string, string>();
  backStack: number[] = [];
  private curSentEl: HTMLElement | null = null;
  private curWordEl: HTMLElement | null = null;
  private curParEl: HTMLElement | null = null;
  private curSecEl: HTMLElement | null = null;
  private readBuffer = new Set<number>();
  private observer!: IntersectionObserver;
  private cleanup: (() => void)[] = [];
  private qPending = 0;
  private enteredAt = performance.now();
  private gone = false; // you left this reader: nothing more is drawn, opened or started
  private timeBoxShown = false;
  private savePosition = debounce((ord: number) => save("post", `/api/documents/${this.doc.id}/position`, { position: ord }), 1200);

  constructor() {
    this.pacer = new Pacer(this);
  }

  // ------------------------------------------------------------------ setup
  async mount(root: HTMLElement, docId: string, params: URLSearchParams, current: () => boolean = () => true): Promise<() => void> {
    this.root = root;
    const [doc, ann] = await Promise.all([api.get<Doc>(`/api/documents/${docId}`), api.get<Annotations>(`/api/documents/${docId}/annotations`)]);
    if (!current()) return () => undefined; // you moved to another page while the document loaded: it stays off the screen
    this.doc = doc;
    this.ann = ann;
    this.isPaper = ["pdf", "arxiv"].includes(doc.source_type) || doc.sections.some((s) => s.kind === "abstract");
    this.pass = this.isPaper ? doc.current_pass : 0;
    if (this.isPaper && doc.current_pass === 1 && (doc.position > 0 || params.has("s"))) this.pass = 0;
    this.buildIndex();
    this.buildPeeks();
    this.indexHighlights();

    const s = state.settings;
    this.pacer.wpm = s.wpm;
    this.pacer.mode = s.pacer_mode;
    this.pacer.energy = state.energy;
    this.pacer.voice = s.tts_voice;
    this.pacer.ttsRate = s.tts_rate;
    applyComfort(comfortFor(doc.source_type));

    this.renderShell();
    this.renderSections();
    this.renderMap();
    this.renderSide();

    const startAt = params.has("s") ? Number(params.get("s")) : doc.position;
    const want = Math.min(Math.max(startAt, 0), this.idx.length - 1);
    const start = this.isPacedOrNext(want);
    if (start !== null) {
      this.pacer.setPosition(start);
      this.scrollTo(start, false);
    }
    if (start !== want) this.scrollToBlock(want); // the anchor is a code block, a caption or an equation: the pacer cannot stand there, the page can

    this.bindKeys();
    this.bindAway();
    const flush = window.setInterval(() => this.flushRead(), 4000);
    this.cleanup.push(() => clearInterval(flush));
    const unload = () => {
      this.flushRead(true);
      this.session?.flushOnUnload();
    };
    window.addEventListener("beforeunload", unload);
    this.cleanup.push(() => window.removeEventListener("beforeunload", unload));

    if (doc.import_warning) toast(doc.import_warning, "info", 7000);
    // Confusion first, then a 5-second session setup.
    setTimeout(() => this.startFlow(params), 50);
    return () => this.destroy();
  }

  private async startFlow(params: URLSearchParams): Promise<void> {
    if (this.gone) return;
    const open = this.ann.highlights.filter((x) => x.type === "confusing" && !x.resolved);
    if (open.length && !params.has("s")) await dlg.confusionFirst(this, open);
    if (this.gone) return;
    const setup = await dlg.sessionSetup(this);
    if (this.gone) return;
    state.energy = setup.energy;
    this.pacer.energy = setup.energy;
    applyTheme();
    if (setup.parked) {
      location.hash = "#/home"; // parked as a side quest: back to the main quest
      return;
    }
    this.session = await SessionTracker.start(this.doc.id, setup.energy, setup.minutes, setup.question, () => this.pacer.playing, (t) => this.onSessionTick(t), setup.questId);
    if (this.gone) return void this.session.leave(); // you left while it was being created: it is closed, not left open
    this.updateTop();
  }

  destroy(): void {
    this.gone = true;
    this.pacer.destroy();
    this.flushRead(true);
    this.session?.leave();
    this.observer?.disconnect();
    this.cleanup.forEach((f) => f());
  }

  private buildIndex(): void {
    this.idx = [];
    this.doc.sections.forEach((sec, secIdx) => {
      for (const p of sec.paragraphs) for (const s of p.sentences) this.idx[s.ord] = { s, p, sec, secIdx };
    });
    // Defensive: fill holes (sentences are 0..n-1, but keep the reader safe if not).
    for (let i = 0; i < this.idx.length; i++) if (!this.idx[i]) this.idx[i] = this.idx[i - 1] ?? this.idx.find(Boolean)!;
  }

  private buildPeeks(): void {
    this.peeks.clear();
    this.peekImages.clear();
    for (const sec of this.doc.sections)
      for (const p of sec.paragraphs) {
        const text = p.sentences.map((s) => s.text).join(" ");
        if (p.kind === "caption") {
          const m = text.match(/^(fig(?:ure)?|tab(?:le)?)\.?\s*(\d+)/i);
          if (m) this.peeks.set(`${m[1].toLowerCase().startsWith("f") ? "figure" : "table"}:${m[2]}`, text);
        } else if (p.kind === "equation") {
          const m = text.match(/\((\d+)\)\s*$/);
          if (m) {
            this.peeks.set(`eq:${m[1]}`, text);
            if (p.asset) this.peekImages.set(`eq:${m[1]}`, this.assetUrl(p.asset));
          }
        } else if (p.kind === "reference") {
          const m = text.match(/^\[(\d+)\]/);
          if (m) this.peeks.set(`ref:${m[1]}`, text);
        }
      }
  }

  indexHighlights(): void {
    this.hlByOrd.clear();
    for (const hl of this.ann.highlights)
      for (let o = hl.sentence; o <= hl.end_sentence; o++) {
        const list = this.hlByOrd.get(o) ?? [];
        list.push(hl);
        this.hlByOrd.set(o, list);
      }
  }

  // ------------------------------------------------------------------ pacing rules
  isPaced(ord: number): boolean {
    const x = this.idx[ord];
    if (!x) return false;
    const { p, sec } = x;
    if (sec.hidden && state.settings.clean_view && !this.showHidden) return false;
    const textual = p.kind === "text" || p.kind === "list";
    if (this.pass === 1) return (PASS1.has(sec.kind) && textual) || p.kind === "caption";
    if (!textual) return false;
    if (this.pass === 2) return PASS2.has(sec.kind) || sec.kind === "other";
    if (this.pass === 3) return true;
    return !(sec.background && state.settings.skip_background);
  }

  isPacedOrNext(ord: number): number | null {
    return this.isPaced(ord) ? ord : this.next(ord);
  }

  sentence(ord: number): Sentence {
    return this.idx[ord].s;
  }

  words(ord: number): string[] {
    return tokens(this.idx[ord].s.text);
  }

  next(ord: number): number | null {
    for (let o = ord + 1; o < this.idx.length; o++) if (this.isPaced(o)) return o;
    return null;
  }

  prev(ord: number): number | null {
    for (let o = ord - 1; o >= 0; o--) if (this.isPaced(o)) return o;
    return null;
  }

  // ------------------------------------------------------------------ pacer host
  show(ord: number, wordIdx: number | null): void {
    const x = this.idx[ord];
    this.ensureRendered(x.secIdx);
    const sEl = this.sentEls.get(ord) ?? null;
    if (sEl !== this.curSentEl) {
      if (this.curSentEl && this.pacer.playing) this.learnFrom(Number(this.curSentEl.dataset.o));
      this.curSentEl?.classList.remove("cur");
      sEl?.classList.add("cur");
      if (this.curSentEl && sEl && this.pacer.playing) comics.step(this.paper); // comics themes: a sound effect beside the page
      this.curSentEl = sEl;
      this.enteredAt = performance.now();
      const pEl = this.parEls.get(x.p.id) ?? null;
      if (pEl !== this.curParEl) {
        this.curParEl?.classList.remove("cur");
        pEl?.classList.add("cur");
        this.curParEl = pEl;
      }
      const secEl = this.secEls[x.secIdx];
      if (secEl !== this.curSecEl) {
        this.curSecEl?.classList.remove("cur");
        secEl.classList.add("cur");
        this.curSecEl = secEl;
        this.mapEl.querySelectorAll(".map-sec.cur").forEach((e) => e.classList.remove("cur"));
        this.mapEl.querySelector(`.map-sec[data-i="${x.secIdx}"]`)?.classList.add("cur");
        if (this.sideTab === "questions") this.renderSide();
      }
      this.keepInView(sEl);
      this.savePosition(ord);
    }
    const wEl = wordIdx === null || !sEl ? null : (sEl.querySelectorAll<HTMLElement>(".w")[wordIdx] ?? null);
    if (wEl !== this.curWordEl) {
      this.curWordEl?.classList.remove("cur");
      wEl?.classList.add("cur");
      this.curWordEl = wEl;
    }
    if (this.pacer.mode === "focus" && this.pacer.playing && wordIdx !== null) this.showFocusWord(this.words(ord)[wordIdx] ?? "");
  }

  done(ord: number): void {
    const s = this.idx[ord].s;
    if (!s.read) {
      s.read = 1;
      this.readBuffer.add(ord);
      if (this.session) this.session.sentencesRead++;
      this.sentEls.get(ord)?.classList.add("read");
      this.updateProgress();
    }
  }

  boundary(from: number, to: number): boolean {
    const a = this.idx[from];
    const b = this.idx[to];
    if (a.secIdx === b.secIdx) return false;
    comics.burst(); // comics themes: a section finished
    const steps = dlg.sectionCheckpoints(this, a.sec, b.sec);
    if (!steps.length) return false;
    setTimeout(() => dlg.runCheckpoints(this, steps), 0);
    return true;
  }

  end(): void {
    this.flushRead();
    dlg.explainIt(this, true);
  }

  playState(playing: boolean): void {
    this.root.classList.toggle("playing", playing);
    ambience.update({ mode: playing ? "reading" : "idle" });
    const btn = this.barEl.querySelector<HTMLButtonElement>(".play");
    if (btn) {
      btn.textContent = playing ? "❚❚" : "▶";
      btn.setAttribute("aria-label", playing ? "Pause (Space)" : "Play (Space)");
    }
    this.focusWordEl.hidden = !(playing && this.pacer.mode === "focus");
    this.session?.activity();
  }

  /** Learn where you personally slow down: rewinds and long dwells raise it, racing ahead lowers it. */
  private learnFrom(ord: number): void {
    const dwell = performance.now() - this.enteredAt;
    const expected = this.pacer.expectedMs(ord);
    if (!this.pacer.playing) return;
    if (dwell < expected * 0.4) this.sendSlow(ord, -0.3);
  }

  sendSlow(ord: number, signal: number): void {
    const s = this.idx[ord].s;
    s.personal = Math.max(-0.3, Math.min(0.6, s.personal * 0.6 + signal * 0.4));
    this.pacer.invalidate();
    save("post", `/api/documents/${this.doc.id}/slow`, { ord, signal }).catch(() => undefined);
  }

  // ------------------------------------------------------------------ rendering
  private renderShell(): void {
    clear(this.root);
    this.topEl = h("header", { class: "reader-top" });
    this.mapEl = h("nav", { class: "map", "aria-label": "Document map" });
    this.paper = h("article", { class: "paper", "aria-label": this.doc.title });
    this.scroller = h("main", { class: "page" }, this.paper);
    this.sideEl = h("aside", { class: "side", "aria-label": "Questions, notes and terms" });
    this.barEl = h("footer", { class: "pacer-bar" });
    this.focusWordEl = h("div", { class: "focus-word", hidden: true, "aria-live": "off" });
    this.panelsHidden = !!state.settings.reader_panels_hidden;
    this.root.append(h("div", { class: `reader${this.panelsHidden ? " panels-hidden" : ""}` }, this.topEl, h("div", { class: "reader-body" }, this.mapEl, this.scroller, this.sideEl), this.barEl, this.focusWordEl));
    this.renderTop();
    this.renderBar();
    this.scroller.addEventListener("click", (e) => this.onPaperClick(e));
    this.scroller.addEventListener("mouseover", (e) => this.onPaperHover(e));
    this.scroller.addEventListener("mouseup", () => setTimeout(() => dlg.selectionToolbar(this), 0));
    this.scroller.addEventListener("scroll", () => this.session?.activity(), { passive: true });
  }

  private renderTop(): void {
    clear(this.topEl);
    this.topEl.append(
      h("a", { class: "btn ghost", href: "#/hub", title: "Back to Overview" }, "← Home"),
      h("div", { class: "top-title" }, h("strong", null, this.doc.title), this.doc.why ? h("span", { class: "muted" }, ` — ${this.doc.why}`) : null),
      h("span", { class: "timer", title: "Time left in this session's time box" }),
      progressWidget(),
      h("button", {
        class: "btn ghost panels-toggle", type: "button", "aria-pressed": String(this.panelsHidden),
        title: this.panelsHidden ? "Show the map and the side panel again (Ctrl+\\)" : "Fold the map and the side panel away, so the page sits alone over the theme (Ctrl+\\)",
        "aria-label": this.panelsHidden ? "Show the side panels (Ctrl+\\)" : "Hide the side panels (Ctrl+\\)",
        onclick: () => this.setPanelsHidden(!this.panelsHidden),
      }, this.panelsHidden ? "Show panels" : "Hide panels"),
      h("button", { class: "btn", onclick: () => dlg.endSession(this) }, "End session"),
    );
    this.updateProgress();
  }

  updateTop(): void {
    const t = this.topEl.querySelector(".timer");
    if (t && this.session) t.textContent = `${fmtClock(this.session.timeBoxMs - this.session.focusedMs)} left`;
  }

  private onSessionTick(t: SessionTracker): void {
    this.updateTop();
    ambience.state.session = t.focusedMs / 1000;
    if (!this.timeBoxShown && t.focusedMs >= t.timeBoxMs) {
      this.timeBoxShown = true;
      ambience.update({ mode: "break" });
      this.pacer.pause(false);
      dlg.timeBoxDone(this).then((more) => {
        if (more && this.session) {
          this.session.info.time_box_min += 5;
          void save("patch", `/api/sessions/${this.session.info.id}`, { time_box_min: this.session.info.time_box_min });
          this.timeBoxShown = false;
        }
      });
    }
  }

  updateProgress(): void {
    let total = 0;
    let read = 0;
    for (const x of this.idx) {
      if (!x || (x.p.kind !== "text" && x.p.kind !== "list") || x.sec.background || x.sec.hidden) continue;
      total++;
      if (x.s.read) read++;
    }
    const answered = this.ann.questions.filter((q) => q.answer).length;
    const qs = this.ann.questions.length;
    const ratio = total + qs ? (read + answered * 5) / (total + qs * 5) : 0;
    setProgress(this.topEl, ratio, `${read} of ${total} key sentences read · ${answered}/${qs} questions answered`);
    ambience.update({ progress: ratio, answered });
  }

  renderSections(): void {
    clear(this.paper);
    this.observer?.disconnect();
    this.secEls = [];
    this.rendered = [];
    this.sentEls.clear();
    this.parEls.clear();
    this.curSentEl = this.curParEl = this.curSecEl = this.curWordEl = null;
    this.paper.append(h("h1", { class: "doc-title" }, this.doc.title));
    if (this.doc.import_warning) this.paper.append(h("p", { class: "import-warning" }, "Import note: ", this.doc.import_warning, " ", h("a", { href: `#/structure/${this.doc.id}` }, "Fix structure")));
    this.observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) this.ensureRendered(Number((e.target as HTMLElement).dataset.i));
      },
      { root: this.scroller, rootMargin: "1800px 0px" },
    );
    this.doc.sections.forEach((sec, i) => {
      const chars = sec.paragraphs.reduce((a, p) => a + p.sentences.reduce((b, s) => b + s.text.length + 1, 0), 0);
      const hidden = sec.hidden && state.settings.clean_view && !this.showHidden;
      const el = h(
        "section",
        { class: `sec kind-${sec.kind} ${sec.background ? "background" : ""} ${hidden ? "collapsed" : ""} ${this.inPass(sec) ? "" : "out-of-pass"}`, "data-i": i, id: `sec-${i}` },
        h(
          "header",
          { class: "sec-head" },
          h(sec.level > 1 ? "h3" : "h2", null, sec.title),
          h("span", { class: "kind-badge" }, KIND_LABELS[sec.kind] ?? sec.kind),
          sec.background ? h("span", { class: "bg-badge", title: "Background — safe to skip. The pacer skips it." }, "skippable") : null,
          hidden ? h("button", { class: "btn small", onclick: () => this.toggleHidden() }, "Show") : null,
        ),
        h("div", { class: "sec-body", style: { minHeight: hidden ? "0" : `${Math.max(40, (chars / (state.settings.line_width * 1.0)) * state.settings.font_size * state.settings.line_height)}px` } }),
      );
      this.secEls.push(el);
      this.rendered.push(false);
      this.paper.append(el);
      if (!hidden) this.observer.observe(el);
    });
    this.paper.append(h("div", { class: "doc-end" }, h("p", { class: "muted" }, "End of document."), h("button", { class: "btn primary", onclick: () => dlg.explainIt(this, false) }, "Explain it in three sentences")));
  }

  inPass(sec: Section): boolean {
    if (this.pass === 1) return PASS1.has(sec.kind);
    if (this.pass === 2) return PASS2.has(sec.kind) || sec.kind === "other";
    return true;
  }

  ensureRendered(i: number): void {
    if (this.rendered[i]) return;
    this.rendered[i] = true;
    const sec = this.doc.sections[i];
    const body = this.secEls[i].querySelector<HTMLElement>(".sec-body")!;
    body.style.minHeight = "";
    clear(body);
    const frag = document.createDocumentFragment();
    for (const p of sec.paragraphs) frag.append(this.renderParagraph(p));
    body.append(frag);
    this.observer.unobserve(this.secEls[i]);
  }

  assetUrl(name: string): string {
    return `/api/documents/${encodeURIComponent(this.doc.id)}/assets/${encodeURIComponent(name)}`;
  }

  private renderEquation(p: Paragraph, text: string): HTMLElement {
    if (p.asset) {
      // A display equation from a PDF: the exact picture of it, cropped from the page (its number included).
      // Cropped at 3 px per PDF point; papers set body text near 10 pt, so match it to the reading font size.
      const fit = (e: Event) => {
        const img = e.target as HTMLImageElement;
        const px = parseFloat(getComputedStyle(img).fontSize) || 20;
        img.style.width = `${(img.naturalWidth / 3) * (px / 10)}px`;
      };
      return h("figure", { class: "p eq eq-img" }, h("img", { src: this.assetUrl(p.asset), alt: plainMath(text), loading: "lazy", decoding: "async", onload: fit }));
    }
    const d = displayEquation(text);
    if (d) {
      return h("div", { class: "p eq", role: "math", "aria-label": plainMath(text) }, mathEl(d.tex, true), d.tag ? h("span", { class: "eq-no" }, d.tag) : null);
    }
    return h("div", { class: hasMath(text) ? "p eq" : "p eq eq-text" }, mathText(text));
  }

  private renderParagraph(p: Paragraph): HTMLElement {
    const text = p.sentences.map((s) => s.text).join(" ");
    let el: HTMLElement;
    if (p.kind === "code") el = h("pre", { class: "p code" }, p.sentences.map((s) => s.text).join("\n"));
    else if (p.kind === "equation") el = this.renderEquation(p, text);
    else if (p.kind === "reference") el = h("div", { class: "p ref-item" }, mathText(text));
    else {
      el = h("div", { class: `p ${p.kind === "list" ? "li" : p.kind}` });
      for (const s of p.sentences) {
        el.append(this.renderSentence(s), " ");
      }
    }
    el.dataset.pid = p.id;
    this.parEls.set(p.id, el);
    const qn = this.ann.questions.map((q, i) => (q.paragraphs.includes(p.id) ? i + 1 : 0)).filter(Boolean);
    if (qn.length) el.prepend(h("span", { class: "q-badges", "aria-label": `Answers question ${qn.join(", ")}` }, qn.map((n) => h("span", { class: "q-badge" }, `Q${n}`))));
    return el;
  }

  private renderSentence(s: Sentence): HTMLElement {
    const el = h("span", { class: `s ${s.read ? "read" : ""}`, "data-o": s.ord });
    const text = s.text;
    const ranges: { start: number; end: number; key: string }[] = [];
    for (const m of text.matchAll(REF_RE)) {
      let key = "";
      if (m[3]) {
        const first = m[3].split(/[,–-]/)[0].trim();
        key = `ref:${first}`;
        if (!this.peeks.has(key)) continue;
        key = `refs:${m[3]}`;
      } else {
        const kind = m[1].toLowerCase().startsWith("f") ? "figure" : m[1].toLowerCase().startsWith("t") ? "table" : "eq";
        key = `${kind}:${m[2]}`;
        if (!this.peeks.has(key)) continue;
      }
      ranges.push({ start: m.index!, end: m.index! + m[0].length, key });
    }
    const acr = this.ann.acronyms;
    let ref: { el: HTMLElement; end: number } | null = null;
    for (const { word, index: start } of wordsWithIndex(text)) {
      const isMath = hasMath(word);
      const w = h("span", { class: isMath ? "w has-math" : "w" }, isMath ? mathText(word) : word);
      const bare = isMath ? "" : word.replace(/^[^\w]+|[^\w]+$/g, "");
      const ak = !bare ? "" : acr[bare] ? bare : acr[bare.replace(/s$/, "")] ? bare.replace(/s$/, "") : "";
      if (ak && !word.includes("(")) {
        w.classList.add("acr");
        w.dataset.acr = ak;
      }
      if (ref && start >= ref.end) ref = null;
      const r: { start: number; end: number; key: string } | null | undefined = ref ? null : ranges.find((x) => start >= x.start && start < x.end);
      if (r) {
        if (el.childNodes.length) el.append(" ");
        ref = { el: h("span", { class: "peek", "data-peek": r.key, tabindex: 0 }), end: r.end };
        el.append(ref.el);
      } else {
        const target = ref ? ref.el : el;
        if (target.childNodes.length) target.append(" ");
      }
      (ref ? ref.el : el).append(w);
    }
    this.sentEls.set(s.ord, el);
    this.decorateSentence(s.ord, el);
    return el;
  }

  decorateSentence(ord: number, el = this.sentEls.get(ord)): void {
    if (!el) return;
    el.classList.remove("hl", "hl-claim", "hl-evidence", "hl-definition", "hl-confusing", "hl-idea");
    const hls = this.hlByOrd.get(ord);
    if (hls?.length) el.classList.add("hl", `hl-${hls[hls.length - 1].type}`);
    el.querySelector(":scope > .note-mark")?.remove();
    const notes = this.ann.notes.filter((n) => n.sentence === ord);
    if (notes.length) el.append(h("button", { class: "note-mark", title: notes.map((n) => n.text).join("\n"), "aria-label": "Margin note", "data-note": ord }, "✎"));
  }

  rerenderParagraphOf(ord: number): void {
    const x = this.idx[ord];
    const old = this.parEls.get(x.p.id);
    if (!old) return;
    for (const s of x.p.sentences) this.sentEls.delete(s.ord);
    const fresh = this.renderParagraph(x.p);
    old.replaceWith(fresh);
    if (this.curParEl === old) {
      this.curParEl = fresh;
      fresh.classList.add("cur");
    }
    this.curSentEl = null;
    this.show(this.pacer.ord, this.pacer.mode === "sentence" ? null : this.pacer.wordIdx);
  }

  renderMap(): void {
    clear(this.mapEl);
    const passes = this.isPaper
      ? h(
          "div",
          { class: "passes", role: "group", "aria-label": "Three-pass plan" },
          [
            [1, "Pass 1", "Title, abstract, headings, figures, conclusion (~5 min)"],
            [2, "Pass 2", "Method and results"],
            [3, "Pass 3", "Everything, including details and background"],
            [0, "All", "Read straight through (skips background)"],
          ].map(([n, label, tip]) => h("button", { class: `btn small ${this.pass === n ? "on" : ""}`, title: String(tip), onclick: () => this.setPass(Number(n)) }, String(label))),
        )
      : null;
    const secCounts = this.doc.sections.map((sec) => {
      let total = 0;
      let read = 0;
      for (const p of sec.paragraphs) if (p.kind === "text" || p.kind === "list") for (const s of p.sentences) (total++, s.read && read++);
      return { total, read };
    });
    const qBySec = this.doc.sections.map((sec) => {
      const pids = new Set(sec.paragraphs.map((p) => p.id));
      return this.ann.questions.map((q, i) => (q.paragraphs.some((p) => pids.has(p)) ? i + 1 : 0)).filter(Boolean);
    });
    const totalWords = this.idx.reduce((a, x) => a + (x && (x.p.kind === "text" || x.p.kind === "list") ? x.s.words : 0), 0);
    const minutes = Math.max(1, Math.round(totalWords / state.settings.wpm));
    this.mapEl.append(
      h("div", { class: "map-head" }, h("div", { class: "muted small" }, `${this.doc.sections.length} sections · ~${minutes} min at ${state.settings.wpm} wpm · ${this.ann.questions.length} questions`), passes),
      h(
        "ol",
        { class: "map-list" },
        this.doc.sections.map((sec, i) => {
          const c = secCounts[i];
          const pct = c.total ? Math.round((100 * c.read) / c.total) : 0;
          return h(
            "li",
            { class: `map-sec lvl-${Math.min(sec.level, 3)} ${sec.background ? "background" : ""} ${sec.hidden ? "hidden-sec" : ""} ${this.inPass(sec) ? "" : "out-of-pass"}`, "data-i": i },
            h("button", { class: "map-link", onclick: () => this.jumpToSection(i) }, h("span", { class: "map-title" }, sec.title), h("span", { class: "map-meta" }, KIND_LABELS[sec.kind] ?? "", sec.background ? " · skip" : "", qBySec[i].length ? h("span", { class: "q-dots" }, qBySec[i].map((n) => h("span", { class: "q-dot" }, String(n)))) : null)),
            h("span", { class: "map-bar", "aria-hidden": "true" }, h("span", { style: { width: `${pct}%` } })),
            h("button", { class: "map-skip", title: sec.background ? "Read this section" : "Mark as safe to skip", onclick: () => this.toggleBackground(i) }, sec.background ? "↺" : "⤼"),
          );
        }),
      ),
      h(
        "div",
        { class: "map-actions" },
        h("button", { class: "btn small", title: "The outline, the reading time and, with AI on, a summary", onclick: () => void digestDialog(this) }, "Digest"),
        h("a", { class: "btn small", href: `#/summary/${this.doc.id}` }, "Summary sheet"),
        h("button", { class: "btn small", title: "Notes, flashcards or a quiz from your highlights or a section", onclick: () => void studyNotesDialog(this) }, "Study notes"),
        h("button", { class: "btn small", title: "Ideas that connect your highlights here with your notes", onclick: () => void brainstormDialog(this) }, "Brainstorm"),
        h("button", { class: "btn small", title: "Tags (your collections) and related documents", onclick: () => (this.pacer.pause(false), void organizeDialog(this.doc.id, this.doc.title)) }, "Organize"),
        h("a", { class: "btn small", href: `#/structure/${this.doc.id}` }, "Fix structure"),
        h("button", { class: "btn small", onclick: () => this.toggleHidden() }, this.showHidden || !state.settings.clean_view ? "Clean view" : "Show references"),
        h("button", { class: "btn small", onclick: () => dlg.explainIt(this, false) }, "Explain it"),
      ),
    );
    if (this.curSecEl) this.mapEl.querySelector(`.map-sec[data-i="${this.curSecEl.dataset.i}"]`)?.classList.add("cur");
  }

  renderSide(): void {
    renderSidePanel(this);
  }

  private renderBar(): void {
    const p = this.pacer;
    const modeSel = h(
      "select",
      { "aria-label": "Pacer mode", onchange: (e: Event) => this.setMode((e.target as HTMLSelectElement).value as typeof p.mode) },
      h("option", { value: "sentence" }, "Sentence pacer"),
      h("option", { value: "word" }, "Word pacer"),
      h("option", { value: "focus" }, "Focus word"),
    );
    modeSel.value = p.mode;
    const energySel = h(
      "select",
      { "aria-label": "Energy", onchange: (e: Event) => this.setEnergy((e.target as HTMLSelectElement).value as typeof p.energy) },
      h("option", { value: "low" }, "Low energy"),
      h("option", { value: "medium" }, "Medium energy"),
      h("option", { value: "high" }, "High energy"),
    );
    energySel.value = p.energy;
    clear(this.barEl);
    this.barEl.append(
      h("button", { class: "btn icon", "aria-label": "Previous sentence (←)", onclick: () => this.manualStep(-1) }, "⏮"),
      h("button", { class: "btn icon play primary", "aria-label": "Play (Space)", onclick: () => this.pacer.toggle() }, "▶"),
      h("button", { class: "btn icon", "aria-label": "Next sentence (→)", onclick: () => this.manualStep(1) }, "⏭"),
      modeSel,
      h("span", { class: "wpm" }, h("button", { class: "btn icon small", "aria-label": "Slower (-)", onclick: () => this.changeWpm(-10) }, "−"), h("span", { class: "wpm-val" }, `${p.wpm} wpm`), h("button", { class: "btn icon small", "aria-label": "Faster (+)", onclick: () => this.changeWpm(10) }, "+")),
      energySel,
      h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: p.readAloud, onchange: (e: Event) => (this.setReadAloud((e.target as HTMLInputElement).checked), ((e.target as HTMLInputElement).checked = this.pacer.readAloud)) }), " Read aloud (R)"),
      h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: this.focusView, onchange: (e: Event) => this.setFocusView((e.target as HTMLInputElement).checked) }), " Focus view (F)"),
      h("button", { class: "btn small", onclick: () => dlg.comfortPopover(this) }, "Aa"),
      h("button", { class: "btn small", onclick: () => dlg.keyHelp() }, "Keys (?)"),
    );
  }

  // ------------------------------------------------------------------ actions
  setMode(mode: Pacer["mode"]): void {
    this.pacer.mode = mode;
    this.pacer.invalidate();
    this.focusWordEl.hidden = !(this.pacer.playing && mode === "focus");
    this.show(this.pacer.ord, mode === "sentence" && !this.pacer.readAloud ? null : this.pacer.wordIdx);
    save("put", "/api/settings", { pacer_mode: mode });
    state.settings.pacer_mode = mode;
  }

  setEnergy(e: Pacer["energy"]): void {
    this.pacer.energy = e;
    state.energy = e;
    this.pacer.invalidate();
    applyTheme();
  }

  changeWpm(delta: number): void {
    this.pacer.wpm = Math.max(80, Math.min(900, this.pacer.wpm + delta));
    this.pacer.invalidate();
    this.barEl.querySelector(".wpm-val")!.textContent = `${this.pacer.wpm} wpm`;
    state.settings.wpm = this.pacer.wpm;
    save("put", "/api/settings", { wpm: this.pacer.wpm });
  }

  /** Speed ramp: +5% after a question finished without many pauses, never below comfort speed. */
  rampSpeed(): void {
    if (!state.settings.speed_ramp) return;
    if (this.pacer.pauses <= 2) {
      const next = Math.round(this.pacer.wpm * 1.05);
      this.pacer.wpm = Math.min(900, Math.max(state.settings.comfort_wpm, next)); // the same ceiling as the − / + buttons
      this.pacer.invalidate();
      this.barEl.querySelector(".wpm-val")!.textContent = `${this.pacer.wpm} wpm`;
      state.settings.wpm = this.pacer.wpm;
      save("put", "/api/settings", { wpm: this.pacer.wpm });
      toast(`Nice run — pace up to ${this.pacer.wpm} wpm`, "ok");
    }
    this.pacer.pauses = 0;
  }

  setReadAloud(on: boolean): void {
    if (on && !this.pacer.voices().length) {
      // only offline voices are used (an online voice would send your text out), and this computer offers none yet
      toast("No offline voice found on this computer yet. Try again in a moment, or see Settings → Voice.", "info", 6000);
      on = false;
    }
    this.pacer.setReadAloud(on);
  }

  setFocusView(on: boolean): void {
    this.focusView = on;
    this.root.querySelector(".reader")?.classList.toggle("focus-view", on); // the style rule is .reader.focus-view
    const cb = this.barEl.querySelectorAll<HTMLInputElement>(".toggle input")[1];
    if (cb) cb.checked = on;
  }

  /** Fold the map and the side panel away (or bring them back): the page sits alone in the middle and the theme's
   * scene shows on both sides. Saved as a setting. The reading page itself stays solid either way. */
  setPanelsHidden(on: boolean): void {
    this.panelsHidden = on;
    this.root.querySelector(".reader")?.classList.toggle("panels-hidden", on);
    void saveSettings({ reader_panels_hidden: on }).catch(() => undefined);
    this.renderTop();
    this.updateTop();
    this.topEl.querySelector<HTMLElement>(".panels-toggle")?.focus(); // the keyboard stays on the button that moved
  }

  setPass(n: number): void {
    this.pass = n;
    if (n > 0) save("patch", `/api/documents/${this.doc.id}`, { current_pass: n });
    this.secEls.forEach((el, i) => el.classList.toggle("out-of-pass", !this.inPass(this.doc.sections[i])));
    this.renderMap();
    const first = this.isPacedOrNext(n === 0 ? this.pacer.ord : 0);
    if (first !== null) {
      this.pacer.setPosition(first);
      this.scrollTo(first, true);
    }
    toast(n === 0 ? "Reading straight through" : `Pass ${n}: ${["", "abstract, headings, figures, conclusion", "method and results", "all the details"][n]}`);
  }

  toggleHidden(): void {
    if (!state.settings.clean_view) {
      state.settings.clean_view = true;
      this.showHidden = false;
    } else this.showHidden = !this.showHidden;
    this.renderSections();
    this.renderMap();
    this.pacer.setPosition(this.pacer.ord, 0);
  }

  async toggleBackground(i: number): Promise<void> {
    const sec = this.doc.sections[i];
    sec.background = sec.background ? 0 : 1;
    await save("patch", `/api/sections/${sec.id}`, { background: !!sec.background });
    this.secEls[i].classList.toggle("background", !!sec.background);
    this.renderMap();
  }

  manualStep(dir: 1 | -1): void {
    const from = this.pacer.ord;
    if (dir < 0) this.sendSlow(from, 0); // no-op signal keeps decay moving
    this.pacer.step(dir);
    if (dir < 0 && this.pacer.ord !== from) this.sendSlow(this.pacer.ord, 0.5); // a rewind means it needed rereading
    if (dir > 0) this.done(from);
    this.session?.activity();
  }

  jumpTo(ord: number, remember = true): void {
    if (remember && ord !== this.pacer.ord) this.backStack.push(this.pacer.ord);
    const target = ord;
    const paced = this.isPaced(ord) ? ord : (this.next(ord) ?? ord); // captions/equations aren't paced
    this.ensureRendered(this.idx[target].secIdx);
    this.pacer.setPosition(paced, 0);
    this.scrollTo(target, true);
    this.sentEls.get(target)?.classList.add("flash");
    setTimeout(() => this.sentEls.get(target)?.classList.remove("flash"), 1200);
  }

  backJump(): void {
    const ord = this.backStack.pop();
    if (ord === undefined) {
      toast("Nothing to go back to");
      return;
    }
    this.jumpTo(ord, false);
  }

  jumpToSection(i: number): void {
    const first = this.doc.sections[i].paragraphs.flatMap((p) => p.sentences)[0];
    if (!first) return;
    const target = this.isPacedOrNext(first.ord) ?? first.ord;
    this.jumpTo(this.idx[target].secIdx === i ? target : first.ord);
  }

  private scrollTo(ord: number, smooth: boolean): void {
    this.ensureRendered(this.idx[ord].secIdx);
    const el = this.sentEls.get(ord);
    if (!el) return;
    const top = el.getBoundingClientRect().top - this.scroller.getBoundingClientRect().top + this.scroller.scrollTop - this.scroller.clientHeight * 0.33;
    this.scroller.scrollTo({ top, behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto" });
  }

  /** Bring the paragraph that holds this sentence to the top third. Works for blocks the pacer skips (code, equations). */
  private scrollToBlock(ord: number): void {
    const at = this.idx[ord];
    if (!at) return;
    this.ensureRendered(at.secIdx);
    const el = this.scroller.querySelector<HTMLElement>(`[data-pid="${at.p.id}"]`);
    if (!el) return;
    const top = el.getBoundingClientRect().top - this.scroller.getBoundingClientRect().top + this.scroller.scrollTop - this.scroller.clientHeight * 0.33;
    this.scroller.scrollTo({ top, behavior: "auto" });
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1500);
  }

  private keepInView(el: HTMLElement | null): void {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const c = this.scroller.getBoundingClientRect();
    if (r.top < c.top + c.height * 0.15 || r.bottom > c.top + c.height * 0.7) {
      const top = r.top - c.top + this.scroller.scrollTop - c.height * 0.33;
      this.scroller.scrollTo({ top, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    }
  }

  private showFocusWord(word: string): void {
    const clean = word;
    const pivot = Math.min(Math.max(Math.floor(clean.length * 0.35), 0), clean.length - 1);
    clear(this.focusWordEl);
    this.focusWordEl.append(h("span", null, clean.slice(0, pivot)), h("span", { class: "pivot" }, clean.charAt(pivot)), h("span", null, clean.slice(pivot + 1)));
  }

  flushRead(unload = false): void {
    if (!this.readBuffer.size) return;
    const ords = [...this.readBuffer];
    this.readBuffer.clear();
    const url = `/api/documents/${this.doc.id}/read`;
    if (unload) fetch(url, { method: "POST", keepalive: true, credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ords }) }).catch(() => undefined);
    else
      save("post", url, { ords }).catch(() => ords.forEach((o) => this.readBuffer.add(o)));
    const counts = this.mapEl.querySelectorAll<HTMLElement>(".map-sec");
    if (counts.length) this.renderMapBars();
  }

  private renderMapBars(): void {
    this.doc.sections.forEach((sec, i) => {
      let total = 0;
      let read = 0;
      for (const p of sec.paragraphs) if (p.kind === "text" || p.kind === "list") for (const s of p.sentences) (total++, s.read && read++);
      const bar = this.mapEl.querySelector<HTMLElement>(`.map-sec[data-i="${i}"] .map-bar span`);
      if (bar) bar.style.width = `${total ? Math.round((100 * read) / total) : 0}%`;
    });
  }

  // ------------------------------------------------------------------ highlights, notes
  async highlight(type: HlType, from = this.pacer.ord, to = from): Promise<void> {
    const existing = (this.hlByOrd.get(from) ?? []).find((x) => x.type === type && x.sentence === from && x.end_sentence === to);
    if (existing) {
      await api.del(`/api/highlights/${existing.id}`);
      this.ann.highlights = this.ann.highlights.filter((x) => x.id !== existing.id);
      toast(`${type} highlight removed`);
    } else {
      const hl = await api.post<Highlight>("/api/highlights", { document_id: this.doc.id, sentence: from, end_sentence: to, type });
      this.ann.highlights.push(hl);
      if (type === "confusing") toast("Marked confusing — it will be shown first next session");
      if (type === "idea") toast("Sent to your idea inbox", "ok");
    }
    this.indexHighlights();
    for (let o = from; o <= to; o++) this.decorateSentence(o);
    this.renderSide();
  }

  // ------------------------------------------------------------------ input
  private onPaperClick(e: MouseEvent): void {
    const t = e.target as HTMLElement;
    this.session?.activity();
    const note = t.closest<HTMLElement>(".note-mark");
    if (note) {
      dlg.showNotes(this, Number(note.dataset.note));
      return;
    }
    const peek = t.closest<HTMLElement>(".peek");
    if (peek) {
      dlg.peek(this, peek, true);
      return;
    }
    if (window.getSelection()?.toString().trim()) return;
    const w = t.closest<HTMLElement>(".w");
    const s = t.closest<HTMLElement>(".s");
    if (!s) return;
    const ord = Number(s.dataset.o);
    const wi = w ? [...s.querySelectorAll(".w")].indexOf(w) : 0;
    if (ord !== this.pacer.ord) this.backStack.push(this.pacer.ord);
    this.pacer.setPosition(ord, Math.max(wi, 0));
  }

  private onPaperHover(e: MouseEvent): void {
    const t = e.target as HTMLElement;
    const peek = t.closest<HTMLElement>(".peek");
    if (peek) dlg.peek(this, peek, false);
    const acr = t.closest<HTMLElement>(".acr");
    if (acr) dlg.acronymTip(this, acr);
  }

  private bindKeys(): void {
    const onKey = (e: KeyboardEvent) => {
      // Ctrl+\: fold the side panels away or bring them back (the reader has no side menu, so it is free here)
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key === "\\") {
        e.preventDefault();
        this.setPanelsHidden(!this.panelsHidden);
        return;
      }
      if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      this.session?.activity();
      const k = e.key;
      if (this.qPending && /^[1-9]$/.test(k)) {
        e.preventDefault();
        this.qPending = 0;
        dlg.tagParagraph(this, Number(k) - 1);
        return;
      }
      switch (k) {
        case " ":
          e.preventDefault();
          this.pacer.toggle();
          break;
        case "ArrowRight":
        case "ArrowDown":
          e.preventDefault();
          this.manualStep(1);
          break;
        case "ArrowLeft":
        case "ArrowUp":
          e.preventDefault();
          this.manualStep(-1);
          break;
        case "q":
        case "Q":
          this.qPending = window.setTimeout(() => (this.qPending = 0), 2000);
          toast("Tag this paragraph: press the question number (1–9)");
          break;
        case "b":
        case "B":
        case "Backspace":
          e.preventDefault();
          this.backJump();
          break;
        case "n":
        case "N":
          e.preventDefault();
          dlg.addNote(this);
          break;
        case "g":
        case "G":
          e.preventDefault();
          dlg.guessGate(this, window.getSelection()?.toString().trim() ?? "");
          break;
        case "i":
        case "I":
          e.preventDefault();
          dlg.quickIdea(this);
          break;
        case "f":
        case "F":
          this.setFocusView(!this.focusView);
          break;
        case "r":
        case "R": {
          const on = !this.pacer.readAloud;
          this.setReadAloud(on);
          const cb = this.barEl.querySelector<HTMLInputElement>(".toggle input");
          if (cb) cb.checked = this.pacer.readAloud; // it stays off when there is no offline voice
          break;
        }
        case "w":
        case "W": {
          const order = ["sentence", "word", "focus"] as const;
          const next = order[(order.indexOf(this.pacer.mode) + 1) % 3];
          this.setMode(next);
          this.barEl.querySelector<HTMLSelectElement>("select")!.value = next;
          toast(`${next === "sentence" ? "Sentence" : next === "word" ? "Word" : "Focus word"} pacer`);
          break;
        }
        case "+":
        case "=":
          this.changeWpm(10);
          break;
        case "-":
          this.changeWpm(-10);
          break;
        case "e":
        case "E":
          e.preventDefault();
          dlg.endSession(this);
          break;
        case "?":
          dlg.keyHelp();
          break;
        default:
          if (HL_KEYS[k]) {
            e.preventDefault();
            const [from, to] = this.selectionRange() ?? [this.pacer.ord, this.pacer.ord];
            this.highlight(HL_KEYS[k], from, to);
          }
      }
    };
    document.addEventListener("keydown", onKey);
    this.cleanup.push(() => document.removeEventListener("keydown", onKey));
  }

  selectionRange(): [number, number] | null {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const r = sel.getRangeAt(0);
    const a = (r.startContainer.parentElement ?? null)?.closest<HTMLElement>(".s");
    const b = (r.endContainer.parentElement ?? null)?.closest<HTMLElement>(".s");
    if (!a || !b) return null;
    const x = Number(a.dataset.o);
    const y = Number(b.dataset.o);
    return [Math.min(x, y), Math.max(x, y)];
  }

  /** Distraction guard: switching away pauses and logs it; coming back says where you were. No guilt. */
  private bindAway(): void {
    let away = false;
    const leave = () => {
      if (away) return;
      away = true;
      if (this.pacer.playing) this.pacer.pause(false);
      if (this.session) this.session.distracted();
    };
    const back = () => {
      if (!away) return;
      away = false;
      if (!this.session) return;
      const s = this.idx[this.pacer.ord]?.s.text ?? "";
      toast(`You were here: “${s.slice(0, 90)}${s.length > 90 ? "…" : ""}” — press Space to continue`, "info", 6000);
      this.sentEls.get(this.pacer.ord)?.classList.add("flash");
      setTimeout(() => this.sentEls.get(this.pacer.ord)?.classList.remove("flash"), 1500);
    };
    const vis = () => (document.visibilityState === "hidden" ? leave() : back());
    window.addEventListener("blur", leave);
    window.addEventListener("focus", back);
    document.addEventListener("visibilitychange", vis);
    this.cleanup.push(() => {
      window.removeEventListener("blur", leave);
      window.removeEventListener("focus", back);
      document.removeEventListener("visibilitychange", vis);
    });
  }
}

// ------------------------------------------------------------------ progress widget (sand jar / bar)
export function progressWidget(): HTMLElement {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 30 40");
  svg.setAttribute("class", "jar");
  svg.setAttribute("aria-hidden", "true");
  const clip = document.createElementNS(ns, "clipPath");
  clip.id = "jar-clip";
  const inner = document.createElementNS(ns, "path");
  inner.setAttribute("d", "M8 9 h14 v3 q4 3 4 9 v12 q0 4 -4 4 h-14 q-4 0 -4 -4 v-12 q0 -6 4 -9 z");
  clip.append(inner);
  const sand = document.createElementNS(ns, "rect");
  sand.setAttribute("class", "sand");
  sand.setAttribute("x", "0");
  sand.setAttribute("width", "30");
  sand.setAttribute("y", "37");
  sand.setAttribute("height", "40");
  sand.setAttribute("clip-path", "url(#jar-clip)");
  const outline = document.createElementNS(ns, "path");
  outline.setAttribute("d", inner.getAttribute("d")!);
  outline.setAttribute("class", "jar-outline");
  const lid = document.createElementNS(ns, "rect");
  lid.setAttribute("x", "7");
  lid.setAttribute("y", "4");
  lid.setAttribute("width", "16");
  lid.setAttribute("height", "4");
  lid.setAttribute("rx", "1.5");
  lid.setAttribute("class", "jar-lid");
  svg.append(clip, sand, outline, lid);
  return h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100 }, svg, h("div", { class: "bar" }, h("span")), h("span", { class: "pct" }));
}

export function setProgress(scope: HTMLElement, ratio: number, label: string): void {
  const pct = Math.round(Math.max(0, Math.min(1, ratio)) * 100);
  const box = scope.querySelector<HTMLElement>(".progress");
  if (!box) return;
  box.setAttribute("aria-valuenow", String(pct));
  box.title = label;
  const sand = box.querySelector(".sand");
  if (sand) sand.setAttribute("y", String(37 - (28 * pct) / 100));
  const bar = box.querySelector<HTMLElement>(".bar span");
  if (bar) bar.style.width = `${pct}%`;
  box.querySelector(".pct")!.textContent = `${pct}%`;
}
