// The pacer: one requestAnimationFrame clock, speed follows sentence density. It never re-renders —
// the host only toggles classes. Read-aloud mode hands the clock to the speech engine instead.
import { spoken as spokenWord } from "./math";
import type { Energy, Sentence } from "./types";
import { Tts } from "./tts";

export type PacerMode = "sentence" | "word" | "focus";

export interface PacerHost {
  sentence(ord: number): Sentence;
  words(ord: number): string[];
  next(ord: number): number | null;
  prev(ord: number): number | null;
  /** Called when the cursor moves to a sentence (and word index in word modes). */
  show(ord: number, wordIdx: number | null): void;
  /** A sentence was read to the end by the pacer. */
  done(ord: number): void;
  /** Crossing into another section. Return true to pause there (prediction / recall checkpoint). */
  boundary(from: number, to: number): boolean;
  end(): void;
  playState(playing: boolean): void;
}

export const ENERGY_SPEED: Record<Energy, number> = { low: 0.85, medium: 1, high: 1.15 };

export class Pacer {
  playing = false;
  ord = 0;
  wordIdx = 0;
  mode: PacerMode = "sentence";
  wpm = 250;
  energy: Energy = "medium";
  readAloud = false;
  voice = "";
  ttsRate = 1;
  /** Pauses during the current stretch (used by the speed ramp). */
  pauses = 0;

  private raf = 0;
  private last = 0;
  private acc = 0;
  private wordCache: { ord: number; words: string[]; ms: number[] } | null = null;
  private tts = new Tts();

  constructor(private host: PacerHost) {}

  get speed(): number {
    return ENERGY_SPEED[this.energy];
  }

  /** How long a sentence stays lit: words at your speed, slowed by density and your personal slow-down. */
  sentenceMs(s: Sentence): number {
    const base = (s.words * 60000) / this.wpm;
    const effort = (0.7 + 0.9 * s.density) * (1 + s.personal);
    return Math.max(900, (base * effort) / this.speed) + 200;
  }

  wordMs(word: string, s: Sentence): number {
    const base = 60000 / this.wpm;
    const len = Math.min(word.replace(/[^\p{L}\p{N}]/gu, "").length, 14);
    let ms = base * (0.55 + 0.09 * len) * (0.8 + 0.6 * s.density) * (1 + s.personal);
    if (/[,;:]["')\]]*$/.test(word)) ms += base * 0.5;
    else if (/[.!?]["')\]]*$/.test(word)) ms += base * 1.0;
    return Math.max(90, ms / this.speed);
  }

  /** Expected duration of the current sentence — the host uses it to learn slow-downs. */
  expectedMs(ord = this.ord): number {
    const s = this.host.sentence(ord);
    if (this.mode === "sentence") return this.sentenceMs(s);
    return this.host.words(ord).reduce((a, w) => a + this.wordMs(w, s), 0);
  }

  private wordsFor(ord: number) {
    if (this.wordCache?.ord !== ord) {
      const s = this.host.sentence(ord);
      const words = this.host.words(ord);
      this.wordCache = { ord, words, ms: words.map((w) => this.wordMs(w, s)) };
    }
    return this.wordCache;
  }

  setPosition(ord: number, wordIdx = 0): void {
    this.ord = ord;
    this.wordIdx = wordIdx;
    this.acc = 0;
    this.wordCache = null;
    this.host.show(ord, this.mode === "sentence" && !this.readAloud ? null : wordIdx);
    if (this.playing && this.readAloud) this.speak();
  }

  invalidate(): void {
    this.wordCache = null;
  }

  play(): void {
    if (this.playing) return;
    this.playing = true;
    this.host.playState(true);
    this.host.show(this.ord, this.mode === "sentence" && !this.readAloud ? null : this.wordIdx);
    if (this.readAloud) this.speak();
    else this.startClock();
  }

  pause(countAsPause = true): void {
    if (!this.playing) return;
    this.playing = false;
    if (countAsPause) this.pauses++;
    cancelAnimationFrame(this.raf);
    this.tts.stop();
    this.host.playState(false);
  }

  toggle(): void {
    if (this.playing) this.pause();
    else this.play();
  }

  setReadAloud(on: boolean): void {
    const was = this.playing;
    if (was) this.pause(false);
    this.readAloud = on;
    if (was) this.play();
  }

  /** Manual step by one sentence (arrow keys). */
  step(dir: 1 | -1): void {
    const target = dir > 0 ? this.host.next(this.ord) : this.host.prev(this.ord);
    if (target === null) return;
    const was = this.playing;
    if (was && this.readAloud) this.tts.stop();
    this.setPosition(target, 0);
  }

  private startClock(): void {
    cancelAnimationFrame(this.raf);
    this.last = performance.now();
    const loop = (t: number) => {
      if (!this.playing) return;
      const dt = Math.min(t - this.last, 250); // a background tab must not skip ahead
      this.last = t;
      this.acc += dt;
      this.advanceByClock();
      if (this.playing) this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  private advanceByClock(): void {
    if (this.mode === "sentence") {
      const need = this.sentenceMs(this.host.sentence(this.ord));
      if (this.acc >= need) {
        this.acc -= need;
        this.finishSentence();
      }
      return;
    }
    const wc = this.wordsFor(this.ord);
    while (this.playing && this.acc >= (wc.ms[this.wordIdx] ?? 0)) {
      this.acc -= wc.ms[this.wordIdx] ?? 0;
      if (this.wordIdx + 1 < wc.words.length) {
        this.wordIdx++;
        this.host.show(this.ord, this.wordIdx);
      } else {
        this.finishSentence();
        return;
      }
    }
  }

  private finishSentence(): void {
    this.host.done(this.ord);
    const next = this.host.next(this.ord);
    if (next === null) {
      this.pause(false);
      this.host.end();
      return;
    }
    const stop = this.host.boundary(this.ord, next);
    this.ord = next;
    this.wordIdx = 0;
    this.acc = 0;
    this.wordCache = null;
    this.host.show(next, this.mode === "sentence" && !this.readAloud ? null : 0);
    if (stop) {
      this.pause(false);
      return;
    }
    if (this.readAloud && this.playing) this.speak();
  }

  private speak(): void {
    const s = this.host.sentence(this.ord);
    const words = this.host.words(this.ord);
    // Start from the current word: build char offsets of each word within the spoken text.
    const fromWord = Math.min(this.wordIdx, Math.max(words.length - 1, 0));
    const spoken = words.slice(fromWord).map(spokenWord); // formulas are read in words, not LaTeX
    const offsets: number[] = [];
    let pos = 0;
    for (const w of spoken) {
      offsets.push(pos);
      pos += w.length + 1;
    }
    const rate = this.ttsRate * (1 - 0.18 * s.density) * this.speed;
    this.tts.speak(spoken.join(" "), {
      rate,
      voice: this.voice,
      onWord: (charIndex) => {
        let i = 0;
        while (i + 1 < offsets.length && offsets[i + 1] <= charIndex) i++;
        this.wordIdx = fromWord + i;
        this.host.show(this.ord, this.wordIdx);
      },
      onEnd: () => {
        if (this.playing) this.finishSentence();
      },
    });
  }

  voices(): SpeechSynthesisVoice[] {
    return this.tts.voices();
  }

  destroy(): void {
    this.pause(false);
    this.tts.stop();
  }
}
