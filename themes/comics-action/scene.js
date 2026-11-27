// Comics: Classic Action — halftone paper, comic rays turning slowly behind the page and speed streaks sweeping
// through the margins. As you read, a band of dots rises from the bottom. A question answered gives a slow warm glow.
// The sound effects and the KA-POW live in the page (web/src/comics.ts), not here.
function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}
function momentGlow(state) {
  if (!state.moment || state.still) return 0;
  const s = (performance.now() - state.moment) / 2600;
  return s > 0 && s < 1 ? Math.sin(Math.PI * s) : 0;
}
function dotPattern(ctx, color, size, radius) {
  if (typeof OffscreenCanvas === "undefined") return null;
  try {
    const tile = new OffscreenCanvas(size, size);
    const t = tile.getContext("2d");
    t.fillStyle = color;
    t.beginPath();
    t.arc(size / 2, size / 2, radius, 0, Math.PI * 2);
    t.fill();
    return ctx.createPattern(tile, "repeat");
  } catch {
    return null; // no dots this frame; tried again on the next
  }
}

export default function comicsAction(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  const ink = dark ? "245,240,230" : "17,17,17";
  const ray = dark ? "255,210,63" : "229,51,42";
  let dots = null;
  const dotsMake = () => (dots ??= dotPattern(ctx, `rgba(${ink},${dark ? 0.08 : 0.07})`, 11, 1.3));
  let band = null;
  const bandMake = () => (band ??= dotPattern(ctx, `rgba(${hexRgb(tokens.sand)},${dark ? 0.45 : 0.35})`, 10, 2.2));
  let angle = 0;
  let ox = 0;
  const streaks = Array.from({ length: 7 }, (_, i) => ({ x: (i / 7) * 1.6 - 0.3, y: 0.1 + ((i * 37) % 80) / 100, len: 0.12 + (i % 3) * 0.05, v: 0.03 + (i % 4) * 0.012 }));

  function fillPattern(p, x, y, top, height) {
    if (!p) return;
    if (p.setTransform) p.setTransform(new DOMMatrix().translate(x, y));
    ctx.fillStyle = p;
    ctx.fillRect(0, top, w, height);
  }

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
    },
    frame(dt) {
      dotsMake();
      bandMake();
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = tokens.bg;
      ctx.fillRect(0, 0, w, h);
      const glow = ctx.createRadialGradient(w / 2, h * 0.45, 0, w / 2, h * 0.45, Math.max(w, h) * 0.7);
      glow.addColorStop(0, tokens.bg2);
      glow.addColorStop(1, tokens.bg);
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      // rays: one turn every two minutes or so
      angle += dt * 0.05;
      const cx = w / 2;
      const cy = h * 0.45;
      const R = Math.hypot(w, h);
      ctx.fillStyle = `rgba(${ray},${dark ? 0.06 : 0.07})`;
      ctx.beginPath();
      for (let i = 0; i < 24; i++) {
        const a = angle + (i / 24) * Math.PI * 2;
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
        ctx.lineTo(cx + Math.cos(a + 0.09) * R, cy + Math.sin(a + 0.09) * R);
        ctx.closePath();
      }
      ctx.fill();

      ox = (ox + dt * 6) % 11;
      fillPattern(dots, ox, ox / 2, 0, h);

      // speed streaks: long, thin, slanted, sweeping right
      ctx.strokeStyle = `rgba(${ink},${dark ? 0.16 : 0.14})`;
      ctx.lineWidth = 3;
      ctx.beginPath();
      for (const s of streaks) {
        s.x += s.v * dt;
        if (s.x > 1.3) s.x = -0.3;
        const x = s.x * w;
        const y = s.y * h;
        ctx.moveTo(x, y);
        ctx.lineTo(x + s.len * w, y - s.len * w * 0.18);
      }
      ctx.stroke();

      const p = Math.min(1, state.progress);
      if (p > 0.01) {
        const bh = h * 0.22 * p;
        fillPattern(band, 0, 0, h - bh, bh);
        ctx.fillStyle = `rgba(${ink},${dark ? 0.5 : 0.6})`;
        ctx.fillRect(0, h - bh, w, 2);
      }

      const g = momentGlow(state);
      if (g > 0) {
        const r = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.6);
        r.addColorStop(0, `rgba(255,210,63,${0.2 * g})`);
        r.addColorStop(1, "rgba(255,210,63,0)");
        ctx.fillStyle = r;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
