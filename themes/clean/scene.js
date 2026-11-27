// Clean — modern and minimal. A faint dot grid breathes very slowly (about 14 s a breath) and a thin accent line
// along the top fills as you read. A question answered gives a soft glow. Nothing else moves. In Still mode
// (state.still) the grid is drawn at rest and the line shows your progress.
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

export default function clean(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  const ink = dark ? "255,255,255" : "0,0,0";
  let dots = null;
  const dotsMake = () => (dots ??= dotPattern(ctx, `rgba(${ink},${dark ? 0.05 : 0.055})`, 24, 1.1));
  let t = 0;

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
    },
    frame(dt) {
      dotsMake();
      t += dt;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = tokens.bg;
      ctx.fillRect(0, 0, w, h);
      if (dots) {
        ctx.save();
        ctx.globalAlpha = state.still ? 0.8 : 0.6 + 0.4 * (0.5 + 0.5 * Math.sin((t * 2 * Math.PI) / 14));
        ctx.fillStyle = dots;
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      }
      const p = Math.min(1, state.progress);
      ctx.fillStyle = `rgba(${hexRgb(tokens.accent)},${dark ? 0.55 : 0.5})`;
      ctx.fillRect(0, 0, w * p, 2);
      const g = momentGlow(state);
      if (g > 0) {
        const r = ctx.createRadialGradient(w / 2, h * 0.4, 0, w / 2, h * 0.4, Math.max(w, h) * 0.6);
        r.addColorStop(0, `rgba(${hexRgb(tokens.accent)},${0.1 * g})`);
        r.addColorStop(1, `rgba(${hexRgb(tokens.accent)},0)`);
        ctx.fillStyle = r;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
