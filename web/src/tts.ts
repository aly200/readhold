// Read aloud with the system's built-in voices, and only the offline ones: on Windows these are
// Microsoft David / Zira / Mark. A voice that streams from the internet (Edge "Natural" / "Online" voices) would send
// the text you read to a speech service, so such voices are never listed and never used.

export interface SpeakOpts {
  rate: number;
  voice: string;
  onWord: (charIndex: number) => void;
  onEnd: () => void;
}

export class Tts {
  private token = 0;

  constructor() {
    if (this.available()) speechSynthesis.getVoices(); // the list loads in the background; asking early has it ready when you press R
  }

  available(): boolean {
    return "speechSynthesis" in window;
  }

  voices(): SpeechSynthesisVoice[] {
    if (!this.available()) return [];
    return speechSynthesis.getVoices().filter(isOfflineVoice);
  }

  /** The saved voice when it is an offline one; else the first offline English voice; else any offline voice. */
  pickVoice(name: string): SpeechSynthesisVoice | undefined {
    const all = this.voices();
    return all.find((v) => v.name === name) ?? all.find((v) => v.lang.startsWith("en")) ?? all[0];
  }

  speak(text: string, opts: SpeakOpts): void {
    if (!this.available()) {
      opts.onEnd();
      return;
    }
    const my = ++this.token;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = this.pickVoice(opts.voice);
    if (!v) return; // no offline voice: say nothing, so the browser's default (which may be an online one) is never used
    u.voice = v;
    u.rate = Math.max(0.5, Math.min(2.5, opts.rate));
    u.onboundary = (e) => {
      if (my === this.token && e.name === "word") opts.onWord(e.charIndex);
    };
    const finish = () => {
      if (my === this.token) opts.onEnd();
    };
    u.onend = finish;
    u.onerror = (e) => {
      if (e.error !== "interrupted" && e.error !== "canceled") finish();
    };
    speechSynthesis.speak(u);
  }

  stop(): void {
    this.token++;
    if (this.available()) speechSynthesis.cancel();
  }
}

export function isOfflineVoice(v: SpeechSynthesisVoice): boolean {
  return v.localService && !/natural|online/i.test(v.name);
}
