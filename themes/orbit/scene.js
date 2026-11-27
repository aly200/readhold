// Orbit — space, kept calm. Deep navy (or pale lavender at Dawn, in light mode), dim stars that twinkle very
// slowly, two soft nebulae drifting, and a small solar system low on the left whose three planets orbit slowly
// (the slowest takes minutes). In the right margin, a constellation: each step of your reading joins one more star
// (state.progress). A question answered gives a soft violet glow. In Still mode everything is drawn at rest.
function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}
function momentGlow(state) {
  if (!state.moment || state.still) return 0;
  const s = (performance.now() - state.moment) / 2600;
  return s > 0 && s < 1 ? Math.sin(Math.PI * s) : 0;
}
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export default function orbit(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  const star = dark ? "255,255,255" : "90,70,190";
  const ring = dark ? "160,170,255" : "88,69,201";
  const planets = [
    { r: 150, size: 9, speed: (2 * Math.PI) / 80, a: 0.4, c: dark ? "#6f9bff" : "#7a9cff" },
    { r: 250, size: 15, speed: (2 * Math.PI) / 160, a: 2.2, c: dark ? "#a774ff" : "#b08cff" },
    { r: 360, size: 11, speed: -(2 * Math.PI) / 280, a: 4.1, c: dark ? "#3cc6a3" : "#4fcfae" },
  ];
  const SHAPE = [[0, 0.7], [0.18, 0.35], [0.4, 0.55], [0.58, 0.15], [0.76, 0.45], [0.92, 0.2], [1, 0.62]];
  let t = 0;
  let stars = [];

  function layout() {
    const R = rng(7);
    stars = Array.from({ length: Math.round((w * h) / 9000) }, () => ({ x: R() * w, y: R() * h, s: R() < 0.12 ? 1.5 : 0.9, tw: R() < 0.3, ph: R() * 6.28 }));
  }
  layout();

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
      layout();
    },
    frame(dt) {
      t += dt;
      ctx.clearRect(0, 0, w, h);
      const bg = ctx.createRadialGradient(w * 0.2, 0, 0, w * 0.2, 0, Math.max(w, h));
      bg.addColorStop(0, tokens.bg2);
      bg.addColorStop(0.6, tokens.bg);
      bg.addColorStop(1, tokens.bg);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);

      // nebulae, drifting very slowly
      const drift = state.still ? 0 : Math.sin(t / 30) * 30;
      for (const [nx, ny, nr, col] of [[0.18, 0.72, 0.28, dark ? "120,60,200" : "255,175,200"], [0.7, 0.15, 0.24, dark ? "40,120,220" : "150,170,255"]]) {
        const cx = w * nx + drift;
        const cy = h * ny - drift / 2;
        const rr = Math.max(w, h) * nr;
        const n = ctx.createRadialGradient(cx, cy, 0, cx, cy, rr);
        n.addColorStop(0, `rgba(${col},${dark ? 0.18 : 0.24})`);
        n.addColorStop(1, `rgba(${col},0)`);
        ctx.fillStyle = n;
        ctx.fillRect(cx - rr, cy - rr, rr * 2, rr * 2);
      }

      // stars; some twinkle, slowly (about 12 s), never flash
      for (const s of stars) {
        const a = s.tw && !state.still ? 0.3 + 0.4 * (0.5 + 0.5 * Math.sin((t * 2 * Math.PI) / 12 + s.ph)) : 0.5;
        ctx.fillStyle = `rgba(${star},${a * (dark ? 0.9 : 0.5)})`;
        ctx.fillRect(s.x, s.y, s.s, s.s);
      }

      // the solar system, low in the left margin (beside the reading page, above the reader's bottom bar)
      const cx = w * 0.06;
      const cy = h * 0.84;
      ctx.lineWidth = 1;
      for (const p of planets) {
        ctx.strokeStyle = `rgba(${ring},${dark ? 0.12 : 0.16})`;
        ctx.beginPath();
        ctx.arc(cx, cy, p.r, 0, Math.PI * 2);
        ctx.stroke();
      }
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, 110);
      glow.addColorStop(0, "rgba(255,190,110,0.35)");
      glow.addColorStop(1, "rgba(255,190,110,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(cx - 110, cy - 110, 220, 220);
      const sun = ctx.createRadialGradient(cx - 12, cy - 12, 4, cx, cy, 44);
      sun.addColorStop(0, "#fff1c2");
      sun.addColorStop(0.6, "#f5b25a");
      sun.addColorStop(1, "#e9844a");
      ctx.fillStyle = sun;
      ctx.beginPath();
      ctx.arc(cx, cy, 44, 0, Math.PI * 2);
      ctx.fill();
      for (const p of planets) {
        const ang = p.a + p.speed * t;
        const px = cx + Math.cos(ang) * p.r;
        const py = cy + Math.sin(ang) * p.r;
        ctx.fillStyle = p.c;
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fill();
      }

      // the constellation: one more star joined for each step you read
      const bw = Math.min(170, w * 0.09); // narrow enough for the right margin beside the reading page, even at 1280 px
      const bx = w - bw - 16;
      const by = h * 0.13;
      const bh = 90;
      const lit = Math.round(Math.min(1, state.progress) * (SHAPE.length - 1));
      ctx.strokeStyle = `rgba(${hexRgb(tokens.accent)},${dark ? 0.7 : 0.6})`;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      for (let i = 1; i <= lit; i++) {
        ctx.moveTo(bx + SHAPE[i - 1][0] * bw, by + SHAPE[i - 1][1] * bh);
        ctx.lineTo(bx + SHAPE[i][0] * bw, by + SHAPE[i][1] * bh);
      }
      ctx.stroke();
      SHAPE.forEach(([sx, sy], i) => {
        ctx.fillStyle = i <= lit ? (dark ? "#ffffff" : tokens.accent) : `rgba(${star},${dark ? 0.35 : 0.3})`;
        ctx.beginPath();
        ctx.arc(bx + sx * bw, by + sy * bh, i <= lit ? 3 : 2, 0, Math.PI * 2);
        ctx.fill();
      });

      const gl = momentGlow(state);
      if (gl > 0) {
        const r = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.6);
        r.addColorStop(0, `rgba(${hexRgb(tokens.accent)},${0.14 * gl})`);
        r.addColorStop(1, `rgba(${hexRgb(tokens.accent)},0)`);
        ctx.fillStyle = r;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
