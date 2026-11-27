// Cloud — clouds drift slowly. As you read, the sky clears and the sun comes out.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function mix(a, b, k) {
  const pa = parseInt(a.slice(1), 16);
  const pb = parseInt(b.slice(1), 16);
  const ch = (s) => Math.round(((pa >> s) & 255) * (1 - k) + ((pb >> s) & 255) * k);
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}
function momentGlow(state) {
  if (!state.moment || state.still) return 0;
  const s = (performance.now() - state.moment) / 2600;
  return s > 0 && s < 1 ? Math.sin(Math.PI * s) : 0;
}

export default function cloud(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  let clouds = [];
  const overcastTop = dark ? "#1d2533" : "#bcd5ec"; // soft blue even before the sky clears
  const clearTop = dark ? "#16294a" : "#9cc8f0";
  const puff = dark ? "200,210,225" : "255,255,255";

  function layout() {
    const R = rng(3);
    clouds = Array.from({ length: 10 }, (_, i) => {
      const scale = 0.6 + R() * 0.9;
      return {
        x: R() * (w + 300) - 150,
        y: h * (0.06 + R() * 0.6),
        v: 5 + R() * 9,
        scale,
        order: i / 10,
        puffs: Array.from({ length: 6 }, () => ({ dx: (R() - 0.5) * 140, dy: (R() - 0.5) * 30, r: 26 + R() * 30 })),
      };
    });
  }
  layout();

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
      layout();
    },
    frame(dt) {
      const p = Math.min(1, state.progress);
      ctx.clearRect(0, 0, w, h);
      const sky = ctx.createLinearGradient(0, 0, 0, h);
      sky.addColorStop(0, mix(overcastTop, clearTop, p));
      sky.addColorStop(1, tokens.bg);
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      // the sun rises and brightens with progress
      const sunA = Math.pow(p, 1.3);
      if (sunA > 0.02) {
        const sx = w * 0.82;
        const sy = h * (0.34 - 0.2 * p);
        const halo = ctx.createRadialGradient(sx, sy, 0, sx, sy, 160);
        halo.addColorStop(0, `rgba(255,226,140,${0.55 * sunA})`);
        halo.addColorStop(1, "rgba(255,226,140,0)");
        ctx.fillStyle = halo;
        ctx.fillRect(sx - 160, sy - 160, 320, 320);
        ctx.fillStyle = `rgba(255,${dark ? 214 : 222},${dark ? 130 : 120},${sunA})`;
        ctx.beginPath();
        ctx.arc(sx, sy, 34, 0, Math.PI * 2);
        ctx.fill();
      }

      // clouds thin out as the sky clears
      for (const c of clouds) {
        c.x += c.v * dt;
        if (c.x - 200 > w) c.x = -220;
        const fade = Math.max(0, Math.min(1, (c.order + 0.35 - p * 0.9) * 3));
        const a = (0.35 + 0.5 * (1 - p)) * fade;
        if (a < 0.02) continue;
        ctx.fillStyle = `rgba(${puff},${a * (dark ? 0.35 : 0.85)})`;
        ctx.beginPath();
        for (const pf of c.puffs) {
          ctx.moveTo(c.x + pf.dx * c.scale + pf.r * c.scale, c.y + pf.dy * c.scale);
          ctx.arc(c.x + pf.dx * c.scale, c.y + pf.dy * c.scale, pf.r * c.scale, 0, Math.PI * 2);
        }
        ctx.fill();
      }

      const g = momentGlow(state);
      if (g > 0) {
        const grad = ctx.createRadialGradient(w * 0.82, h * 0.2, 0, w * 0.82, h * 0.2, Math.max(w, h) * 0.5);
        grad.addColorStop(0, `rgba(255,232,160,${0.25 * g})`);
        grad.addColorStop(1, "rgba(255,232,160,0)");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
