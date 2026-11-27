// Meadow — a soft sky with a gentle sun in the right margin, beside the reading page (or, in dark mode, a moon at dusk), two layers of rolling hills drifting
// slowly at different speeds, mist between them, a few petals by day and dim fireflies at dusk. In the near hill's
// grass, one more flower opens for each part of the document you read (state.progress). A question answered gives a warm
// glow. In Still mode everything is drawn at rest, the flowers showing your progress.
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

export default function meadow(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  const sky = dark ? ["#1a2133", "#2c3a3f"] : ["#e3eef0", "#f2efe2"];
  const hills = dark ? ["#22362c", "#1a2b22"] : ["#c3d8b2", "#a3c691"];
  const stem = dark ? "#46705a" : "#5a8a52";
  const petals = ["#f2a7b9", "#ffffff", "#f6c97a"];
  const FLOWERS = 14;
  let t = 0;
  let bits = [];
  let flowers = [];

  function layout() {
    const R = rng(11);
    bits = Array.from({ length: dark ? 14 : 10 }, () => ({ x: R() * w, y: R() * h, v: 6 + R() * 8, phase: R() * 6.28, c: petals[Math.floor(R() * 3)] }));
    flowers = Array.from({ length: FLOWERS }, (_, i) => ({ x: (w / FLOWERS) * (i + 0.5) + (R() - 0.5) * 30, hgt: 26 + R() * 22, c: petals[i % 3] }));
  }
  layout();

  function ridge(baseY, amp, len, offset, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(0, h);
    for (let x = 0; x <= w + 20; x += 20) {
      const u = (x + offset) / len;
      ctx.lineTo(x, baseY - amp * (0.55 * Math.sin(u) + 0.3 * Math.sin(u * 2.3 + 1.1) + 0.15 * Math.sin(u * 5.1)));
    }
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.fill();
  }

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
      layout();
    },
    frame(dt) {
      t += dt;
      ctx.clearRect(0, 0, w, h);
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, sky[0]);
      g.addColorStop(1, sky[1]);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);

      // the sun, or the moon at dusk, breathing very slowly
      const sx = w * 0.93; // in the right margin, so it shows beside the reading page
      const sy = h * 0.17;
      const breathe = state.still ? 0.5 : 0.5 + 0.5 * Math.sin((t * 2 * Math.PI) / 9);
      const halo = ctx.createRadialGradient(sx, sy, 0, sx, sy, 150);
      halo.addColorStop(0, dark ? `rgba(233,228,204,${0.16 + 0.06 * breathe})` : `rgba(250,214,130,${0.3 + 0.1 * breathe})`);
      halo.addColorStop(1, "rgba(250,214,130,0)");
      ctx.fillStyle = halo;
      ctx.fillRect(sx - 150, sy - 150, 300, 300);
      ctx.fillStyle = dark ? "#e9e4cc" : "#fbe6ae";
      ctx.beginPath();
      ctx.arc(sx, sy, 38, 0, Math.PI * 2);
      ctx.fill();

      ridge(h * 0.74, h * 0.06, 260, t * 4, hills[0]);
      const mist = ctx.createLinearGradient(0, h * 0.7, 0, h * 0.86);
      mist.addColorStop(0, "rgba(255,255,255,0)");
      mist.addColorStop(0.5, dark ? "rgba(160,190,200,0.10)" : "rgba(255,255,255,0.45)");
      mist.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = mist;
      ctx.fillRect(0, h * 0.7, w, h * 0.16);
      ridge(h * 0.86, h * 0.05, 200, t * 7, hills[1]);

      // petals by day, fireflies at dusk
      for (const b of bits) {
        if (dark) {
          b.x += Math.sin(t * 0.3 + b.phase) * dt * 4;
          b.y += Math.cos(t * 0.25 + b.phase) * dt * 3;
          const a = state.still ? 0.4 : 0.25 + 0.45 * (0.5 + 0.5 * Math.sin(t * 0.45 + b.phase));
          const fg = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, 7);
          fg.addColorStop(0, `rgba(255,229,138,${a})`);
          fg.addColorStop(1, "rgba(255,229,138,0)");
          ctx.fillStyle = fg;
          ctx.fillRect(b.x - 7, b.y - 7, 14, 14);
        } else {
          b.y += b.v * dt;
          b.x += Math.sin(t * 0.4 + b.phase) * dt * 6;
          if (b.y > h + 10) {
            b.y = -10;
            b.x = Math.random() * w;
          }
          ctx.save();
          ctx.globalAlpha = 0.55;
          ctx.fillStyle = b.c;
          ctx.translate(b.x, b.y);
          ctx.rotate(t * 0.5 + b.phase);
          ctx.beginPath();
          ctx.ellipse(0, 0, 4.5, 3, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
      }

      // flowers: one more opens for each part you read
      const open = Math.round(Math.min(1, state.progress) * FLOWERS);
      flowers.forEach((f, i) => {
        const bloom = i < open;
        const base = h * 0.9; // in the near hill's grass, above the reader's bottom bar
        const top = base - f.hgt * (bloom ? 1 : 0.55);
        ctx.strokeStyle = stem;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(f.x, base);
        ctx.lineTo(f.x, top);
        ctx.stroke();
        if (bloom) {
          ctx.fillStyle = f.c;
          for (let k = 0; k < 5; k++) {
            const a = (k / 5) * Math.PI * 2;
            ctx.beginPath();
            ctx.arc(f.x + Math.cos(a) * 6, top + Math.sin(a) * 6, 5, 0, Math.PI * 2);
            ctx.fill();
          }
          ctx.fillStyle = "#ffd25e";
          ctx.beginPath();
          ctx.arc(f.x, top, 3.5, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.fillStyle = stem;
          ctx.beginPath();
          ctx.ellipse(f.x, top, 3, 5, 0, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      const gl = momentGlow(state);
      if (gl > 0) {
        const r = ctx.createRadialGradient(sx, sy, 0, sx, sy, Math.max(w, h) * 0.6);
        r.addColorStop(0, `rgba(${hexRgb(tokens.word)},${0.22 * gl})`);
        r.addColorStop(1, `rgba(${hexRgb(tokens.word)},0)`);
        ctx.fillStyle = r;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
