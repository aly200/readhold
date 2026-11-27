// Optional ambient sound, generated with WebAudio — no audio files, nothing downloaded.
// Always off until you turn it on in Settings. Paused while the window is hidden.

type Stop = () => void;
type Recipe = (ctx: AudioContext, out: AudioNode) => Stop;

let noiseCache: Partial<Record<"pink" | "brown", AudioBuffer>> = {};

function noise(ctx: AudioContext, kind: "pink" | "brown"): AudioBuffer {
  const cached = noiseCache[kind];
  if (cached && cached.sampleRate === ctx.sampleRate) return cached;
  const len = ctx.sampleRate * 6;
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  let b0 = 0, b1 = 0, b2 = 0, last = 0;
  for (let i = 0; i < len; i++) {
    const white = Math.random() * 2 - 1;
    if (kind === "pink") {
      b0 = 0.99765 * b0 + white * 0.099046;
      b1 = 0.963 * b1 + white * 0.2965164;
      b2 = 0.57 * b2 + white * 1.0526913;
      d[i] = (b0 + b1 + b2 + white * 0.1848) * 0.18;
    } else {
      last = (last + 0.02 * white) / 1.02;
      d[i] = last * 3.2;
    }
  }
  // fade the loop seam
  for (let i = 0; i < 2000; i++) {
    const k = i / 2000;
    d[i] *= k;
    d[len - 1 - i] *= k;
  }
  noiseCache = { ...noiseCache, [kind]: buf };
  return buf;
}

function loopNoise(ctx: AudioContext, kind: "pink" | "brown"): AudioBufferSourceNode {
  const src = ctx.createBufferSource();
  src.buffer = noise(ctx, kind);
  src.loop = true;
  src.start();
  return src;
}

function lfo(ctx: AudioContext, freq: number, depth: number, target: AudioParam): OscillatorNode {
  const osc = ctx.createOscillator();
  osc.frequency.value = freq;
  const g = ctx.createGain();
  g.gain.value = depth;
  osc.connect(g).connect(target);
  osc.start();
  return osc;
}

function every(minS: number, maxS: number, fn: () => void): Stop {
  let timer = 0;
  const next = () => {
    timer = window.setTimeout(() => {
      fn();
      next();
    }, (minS + Math.random() * (maxS - minS)) * 1000);
  };
  next();
  return () => clearTimeout(timer);
}

const rain: Recipe = (ctx, out) => {
  const src = loopNoise(ctx, "pink");
  const hp = ctx.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 500;
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 5200;
  const g = ctx.createGain();
  g.gain.value = 0.5;
  const swell = lfo(ctx, 0.05, 0.12, g.gain);
  src.connect(hp).connect(lp).connect(g).connect(out);
  return () => (src.stop(), swell.stop());
};

function windAt(center: number, level: number): Recipe {
  return (ctx, out) => {
    const src = loopNoise(ctx, "brown");
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = center;
    bp.Q.value = 0.7;
    const g = ctx.createGain();
    g.gain.value = level;
    const sweep = lfo(ctx, 0.06, center * 0.45, bp.frequency);
    const gust = lfo(ctx, 0.035, level * 0.45, g.gain);
    src.connect(bp).connect(g).connect(out);
    return () => (src.stop(), sweep.stop(), gust.stop());
  };
}

const birds: Recipe = (ctx, out) =>
  every(4, 11, () => {
    const notes = 2 + Math.floor(Math.random() * 3);
    const base = 2300 + Math.random() * 1400;
    let t = ctx.currentTime + 0.05;
    for (let n = 0; n < notes; n++) {
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(base, t);
      osc.frequency.exponentialRampToValueAtTime(base * (1.25 + Math.random() * 0.3), t + 0.07);
      osc.frequency.exponentialRampToValueAtTime(base * 0.9, t + 0.14);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.05, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.15);
      osc.connect(g).connect(out);
      osc.start(t);
      osc.stop(t + 0.17);
      t += 0.19 + Math.random() * 0.12;
    }
  });

const crickets: Recipe = (ctx, out) => {
  const night = windAt(300, 0.08)(ctx, out);
  const stop = every(0.9, 2.2, () => {
    const t0 = ctx.currentTime + 0.02;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.frequency.value = 4300 + Math.random() * 300;
    g.gain.value = 0;
    for (let p = 0; p < 3; p++) {
      const t = t0 + p * 0.06;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.022, t + 0.012);
      g.gain.linearRampToValueAtTime(0, t + 0.04);
    }
    osc.connect(g).connect(out);
    osc.start(t0);
    osc.stop(t0 + 0.25);
  });
  return () => (night(), stop());
};

const hum: Recipe = (ctx, out) => {
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 400;
  const g = ctx.createGain();
  g.gain.value = 0.12;
  const oscs = [55, 82.4, 110.6].map((f) => {
    const o = ctx.createOscillator();
    o.type = "sine";
    o.frequency.value = f;
    o.connect(lp);
    o.start();
    return o;
  });
  const breathe = lfo(ctx, 0.04, 0.05, g.gain);
  lp.connect(g).connect(out);
  return () => (oscs.forEach((o) => o.stop()), breathe.stop());
};

// Ocean waves: brown noise whose lowpass cutoff and level swell together (~every 11 s, a wave rolling in),
// a faint foam hiss on the crest, a slower swell that varies wave height, and a very soft low rumble.
const waves: Recipe = (ctx, out) => {
  const surf = loopNoise(ctx, "brown");
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 600;
  lp.Q.value = 0.5;
  const g = ctx.createGain();
  g.gain.value = 0.2;
  const roll = lfo(ctx, 0.09, 380, lp.frequency);
  const swell = lfo(ctx, 0.09, 0.12, g.gain);
  const sets = lfo(ctx, 0.037, 0.05, g.gain);
  surf.connect(lp).connect(g).connect(out);

  const foam = loopNoise(ctx, "pink");
  const hp = ctx.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 1800;
  const flp = ctx.createBiquadFilter();
  flp.type = "lowpass";
  flp.frequency.value = 6000;
  const fg = ctx.createGain();
  fg.gain.value = 0.025;
  const fizz = lfo(ctx, 0.09, 0.025, fg.gain);
  foam.connect(hp).connect(flp).connect(fg).connect(out);

  const rumble = ctx.createOscillator();
  rumble.type = "sine";
  rumble.frequency.value = 46;
  const rg = ctx.createGain();
  rg.gain.value = 0.025;
  rumble.connect(rg).connect(out);
  rumble.start();

  return () => (surf.stop(), foam.stop(), rumble.stop(), roll.stop(), swell.stop(), sets.stop(), fizz.stop());
};

// A calm shore: small waves lapping (pink noise whose level and brightness rise and fall about every 7 s),
// the soft hiss of water running back down the sand, and now and then a distant gull.
const shore: Recipe = (ctx, out) => {
  const lap = loopNoise(ctx, "pink");
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 1100;
  const g = ctx.createGain();
  g.gain.value = 0.16;
  const roll = lfo(ctx, 0.14, 600, lp.frequency);
  const swell = lfo(ctx, 0.14, 0.1, g.gain);
  lap.connect(lp).connect(g).connect(out);

  const hiss = loopNoise(ctx, "pink");
  const hp = ctx.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 2600;
  const hg = ctx.createGain();
  hg.gain.value = 0.018;
  const back = lfo(ctx, 0.14, 0.014, hg.gain);
  hiss.connect(hp).connect(hg).connect(out);

  const gulls = every(14, 34, () => {
    const calls = 1 + Math.floor(Math.random() * 3);
    let t = ctx.currentTime + 0.05;
    const base = 1250 + Math.random() * 350;
    for (let n = 0; n < calls; n++) {
      const osc = ctx.createOscillator();
      const vg = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(base * 1.15, t);
      osc.frequency.exponentialRampToValueAtTime(base * 0.78, t + 0.32);
      vg.gain.setValueAtTime(0.0001, t);
      vg.gain.exponentialRampToValueAtTime(0.022, t + 0.05);
      vg.gain.exponentialRampToValueAtTime(0.0001, t + 0.34);
      const bp = ctx.createBiquadFilter();
      bp.type = "bandpass";
      bp.frequency.value = base;
      bp.Q.value = 1.2;
      osc.connect(bp).connect(vg).connect(out);
      osc.start(t);
      osc.stop(t + 0.4);
      t += 0.42 + Math.random() * 0.2;
    }
  });

  return () => (lap.stop(), hiss.stop(), roll.stop(), swell.stop(), back.stop(), gulls());
};

const lofi: Recipe = (ctx, out) => {
  const chords = [
    [261.6, 329.6, 392.0, 493.9],
    [220.0, 261.6, 329.6, 392.0],
    [174.6, 220.0, 261.6, 329.6],
    [196.0, 246.9, 293.7, 329.6],
  ];
  const lp = ctx.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 1100;
  lp.connect(out);
  const crackle = loopNoise(ctx, "brown");
  const cg = ctx.createGain();
  cg.gain.value = 0.03;
  crackle.connect(cg).connect(out);
  let i = 0;
  const play = () => {
    const t = ctx.currentTime + 0.05;
    for (const f of chords[i++ % chords.length]) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "triangle";
      o.frequency.value = f / 2;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.035, t + 0.8);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 4.2);
      o.connect(g).connect(lp);
      o.start(t);
      o.stop(t + 4.3);
    }
  };
  play();
  const timer = window.setInterval(play, 4000);
  return () => (clearInterval(timer), crackle.stop());
};

export const RECIPES: Record<string, Recipe[]> = {
  rain: [rain],
  "wind-birds": [windAt(500, 0.25), birds],
  breeze: [windAt(900, 0.14)],
  wind: [windAt(450, 0.22)],
  hum: [hum],
  crickets: [crickets],
  lofi: [lofi],
  waves: [waves],
  shore: [shore, windAt(900, 0.06)],
};

export const sound = {
  ctx: null as AudioContext | null,
  master: null as GainNode | null,
  stops: [] as Stop[],
  key: "",

  apply(recipe: string | null | undefined, enabled: boolean, volume: number): void {
    const key = enabled && recipe && RECIPES[recipe] ? recipe : "";
    if (this.master) this.master.gain.value = Math.max(0, Math.min(1, volume)) * 0.6;
    if (key === this.key) return;
    this.stopAll();
    this.key = key;
    if (!key) return;
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
      document.addEventListener("visibilitychange", () => (document.hidden ? this.ctx?.suspend() : this.key && this.ctx?.resume()));
      const unlock = () => this.key && this.ctx?.resume();
      window.addEventListener("pointerdown", unlock);
      window.addEventListener("keydown", unlock);
    }
    this.master!.gain.value = Math.max(0, Math.min(1, volume)) * 0.6;
    for (const r of RECIPES[key]) this.stops.push(r(this.ctx, this.master!));
    if (!document.hidden) void this.ctx.resume();
  },

  stopAll(): void {
    for (const s of this.stops) {
      try {
        s();
      } catch {
        /* already stopped */
      }
    }
    this.stops = [];
    void this.ctx?.suspend();
  },
};
