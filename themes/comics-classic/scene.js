// Comics: Classic — halftone paper whose dots drift slowly. As you read, a band of coloured dots rises from the
// bottom edge. A question answered gives a slow warm glow (never a flash). White cover by day, black cover by night.
function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}
function momentGlow(state) {
  if (!state.moment || state.still) return 0;
  const s = (performance.now() - state.moment) / 2600;
  return s > 0 && s < 1 ? Math.sin(Math.PI * s) : 0;
}
/** One tile of halftone dots, as a repeating pattern (null where OffscreenCanvas is missing: no dots then). */
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

export default function comicsClassic(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  const ink = dark ? "245,240,230" : "17,17,17";
  let dots = null;
  const dotsMake = () => (dots ??= dotPattern(ctx, `rgba(${ink},${dark ? 0.09 : 0.08})`, 12, 1.4));
  let band = null;
  const bandMake = () => (band ??= dotPattern(ctx, `rgba(${hexRgb(tokens.sand)},${dark ? 0.35 : 0.3})`, 10, 2.2));
  let ox = 0;
  let oy = 0;

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
      const glow = ctx.createRadialGradient(w * 0.2, 0, 0, w * 0.2, 0, Math.max(w, h) * 0.8);
      glow.addColorStop(0, tokens.bg2);
      glow.addColorStop(1, tokens.bg);
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      ox = (ox + dt * 5) % 12; // one tile every few seconds: the paper drifts, it never jumps
      oy = (oy + dt * 2.5) % 12;
      fillPattern(dots, ox, oy, 0, h);

      const p = Math.min(1, state.progress);
      if (p > 0.01) {
        const bh = h * 0.22 * p;
        fillPattern(band, 0, 0, h - bh, bh);
        ctx.fillStyle = `rgba(${ink},${dark ? 0.5 : 0.6})`;
        ctx.fillRect(0, h - bh, w, 2);
      }

      const g = momentGlow(state);
      if (g > 0) {
        const r = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.6);
        r.addColorStop(0, `rgba(255,210,63,${0.18 * g})`);
        r.addColorStop(1, "rgba(255,210,63,0)");
        ctx.fillStyle = r;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
