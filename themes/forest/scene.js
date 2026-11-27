// Forest — drifting leaves and slow light rays. Trees grow along the bottom edge with reading progress.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function momentGlow(state) {
  if (!state.moment || state.still) return 0;
  const s = (performance.now() - state.moment) / 2600;
  return s > 0 && s < 1 ? Math.sin(Math.PI * s) : 0;
}

export default function forest(env) {
  const { ctx, tokens, dark, state } = env;
  const R = rng(23);
  let w = env.w;
  let h = env.h;
  let sky;
  let leaves = [];
  let trees = [];
  const pines = dark ? ["#1f3a24", "#284a2c", "#2f5733"] : ["#3f6b43", "#4c7d4d", "#5b8f58"];
  const leafColors = dark ? ["#5f7d3a", "#7a6a2c", "#3f6a3a"] : ["#8fae5a", "#c9a24a", "#6f9a4e", "#b8763a"];
  const trunk = dark ? "#2a2118" : "#6b4f36";
  const TREES = 16;

  function layout() {
    sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, tokens.bg2);
    sky.addColorStop(1, tokens.bg);
    leaves = Array.from({ length: Math.round((w * h) / 60000) + 10 }, () => newLeaf(true));
    trees = Array.from({ length: TREES }, (_, i) => ({
      x: ((i + 0.5) / TREES) * w + (R() - 0.5) * (w / TREES) * 0.6,
      size: 70 + R() * 70,
      tone: pines[Math.floor(R() * pines.length)],
    }));
  }
  function newLeaf(anywhere) {
    return {
      x: R() * w,
      y: anywhere ? R() * h : -20,
      vx: 8 + R() * 14,
      vy: 14 + R() * 18,
      rot: R() * Math.PI * 2,
      spin: (R() - 0.5) * 1.6,
      sway: R() * Math.PI * 2,
      size: 4 + R() * 4,
      color: leafColors[Math.floor(R() * leafColors.length)],
    };
  }
  layout();
  let t = 0;

  function tree(x, size, grow, tone) {
    const s = size * grow;
    if (s < 2) return;
    const base = h;
    ctx.fillStyle = trunk;
    ctx.fillRect(x - s * 0.04, base - s * 0.22, s * 0.08, s * 0.22);
    ctx.fillStyle = tone;
    for (let k = 0; k < 3; k++) {
      const y = base - s * (0.18 + k * 0.26);
      const half = s * (0.34 - k * 0.08);
      ctx.beginPath();
      ctx.moveTo(x - half, y);
      ctx.lineTo(x + half, y);
      ctx.lineTo(x, y - s * 0.42);
      ctx.closePath();
      ctx.fill();
    }
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
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      // light rays: wide, faint, slowly shifting
      for (let i = 0; i < 4; i++) {
        const sway = Math.sin(t * 0.15 + i * 1.7) * w * 0.03;
        const x = w * (0.12 + i * 0.22) + sway;
        const a = (dark ? 0.035 : 0.07) + 0.025 * Math.sin(t * 0.2 + i);
        ctx.fillStyle = `rgba(255,240,190,${Math.max(0, a)})`;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x + w * 0.06, 0);
        ctx.lineTo(x + w * 0.22, h);
        ctx.lineTo(x + w * 0.1, h);
        ctx.closePath();
        ctx.fill();
      }

      // trees grow along the bottom with progress: one after another
      const p = Math.min(1, state.progress) * TREES;
      for (let i = 0; i < TREES; i++) {
        const grow = Math.max(0, Math.min(1, p - i));
        tree(trees[i].x, trees[i].size, grow > 0 ? 0.25 + 0.75 * grow : 0, trees[i].tone);
        if (grow === 0) {
          ctx.fillStyle = pines[0];
          ctx.fillRect(trees[i].x - 1, h - 6, 2, 6); // a sapling waiting its turn
        }
      }

      // drifting leaves
      for (let i = 0; i < leaves.length; i++) {
        const l = leaves[i];
        l.sway += dt * 1.2;
        l.x += (l.vx + Math.sin(l.sway) * 10) * dt;
        l.y += l.vy * dt;
        l.rot += l.spin * dt;
        if (l.y > h + 20 || l.x > w + 20) leaves[i] = newLeaf(false);
        ctx.save();
        ctx.translate(l.x, l.y);
        ctx.rotate(l.rot);
        ctx.fillStyle = l.color;
        ctx.globalAlpha = dark ? 0.6 : 0.8;
        ctx.beginPath();
        ctx.ellipse(0, 0, l.size, l.size * 0.45, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
      ctx.globalAlpha = 1;

      const g = momentGlow(state);
      if (g > 0) {
        const grad = ctx.createRadialGradient(w * 0.5, h, 0, w * 0.5, h, h * 0.6);
        grad.addColorStop(0, `rgba(255,226,140,${0.25 * g})`);
        grad.addColorStop(1, "rgba(255,226,140,0)");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
