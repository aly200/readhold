// Comics: Manga Action — screentone paper, focus lines that turn slowly around the page, and speed lines running
// down the side margins. As you read, pink tone rises from the bottom. A question answered gives a slow pink glow.
// The sound effects and GO GO GO! live in the page (web/src/comics.ts), not here.
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

export default function mangaAction(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  const ink = dark ? "242,242,242" : "17,17,17";
  let tone = null;
  const toneMake = () => (tone ??= dotPattern(ctx, `rgba(${ink},${dark ? 0.1 : 0.09})`, 7, 1.2));
  let pink = null;
  const pinkMake = () => (pink ??= dotPattern(ctx, `rgba(${hexRgb(tokens.sand)},${dark ? 0.4 : 0.35})`, 7, 1.8));
  let angle = 0;
  let run = 0;
  const lines = Array.from({ length: 140 }, (_, i) => ({ a: (i / 140) * Math.PI * 2 + ((i * 7919) % 100) / 2000, wid: 0.004 + ((i * 31) % 10) / 1400 }));

  function fillPattern(p, x, y, left, top, width, height) {
    if (!p) return;
    if (p.setTransform) p.setTransform(new DOMMatrix().translate(x, y));
    ctx.fillStyle = p;
    ctx.fillRect(left, top, width, height);
  }

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
    },
    frame(dt) {
      toneMake();
      pinkMake();
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = tokens.bg;
      ctx.fillRect(0, 0, w, h);
      fillPattern(tone, 0, 0, 0, 0, w, h);

      // focus lines around a clear centre: one turn every few minutes
      angle += dt * 0.025;
      const cx = w / 2;
      const cy = h / 2;
      const inner = Math.min(w, h) * 0.42;
      const R = Math.hypot(w, h);
      ctx.fillStyle = `rgba(${ink},${dark ? 0.2 : 0.18})`;
      ctx.beginPath();
      for (const l of lines) {
        const a = angle + l.a;
        ctx.moveTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
        ctx.lineTo(cx + Math.cos(a - l.wid) * R, cy + Math.sin(a - l.wid) * R);
        ctx.lineTo(cx + Math.cos(a + l.wid) * R, cy + Math.sin(a + l.wid) * R);
        ctx.closePath();
      }
      ctx.fill();

      // speed lines running down both side margins
      run = (run + dt * 40) % 24;
      ctx.fillStyle = `rgba(${ink},${dark ? 0.14 : 0.12})`;
      const side = Math.max(40, w * 0.06);
      for (let y = -24 + run; y < h; y += 24) {
        ctx.fillRect(0, y, side * (0.4 + ((y * 13) % 7) / 10), 2);
        ctx.fillRect(w - side * (0.4 + ((y * 17) % 7) / 10), y + 12, side, 2);
      }

      const p = Math.min(1, state.progress);
      if (p > 0.01) {
        const bh = h * 0.2 * p;
        fillPattern(pink, 0, 0, 0, h - bh, w, bh);
        ctx.fillStyle = `rgba(${ink},0.7)`;
        ctx.fillRect(0, h - bh, w, 3);
      }

      const g = momentGlow(state);
      if (g > 0) {
        const r = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.6);
        r.addColorStop(0, `rgba(${hexRgb(tokens.sand)},${0.18 * g})`);
        r.addColorStop(1, `rgba(${hexRgb(tokens.sand)},0)`);
        ctx.fillStyle = r;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
