// Garden — a lawn with sprouts. One flower blooms for each question you answer; now and then a butterfly passes.
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

const MAX = 48;

export default function garden(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  let sky;
  let spots = [];
  let blades = [];
  const petals = dark ? ["#c77fa3", "#d9a35a", "#8f86d6", "#d7d7d7", "#e08a7a"] : ["#e58bb3", "#f2b84b", "#9a8ee8", "#ffffff", "#f08f7a"];
  const leaf = dark ? "#4d6b35" : "#6f9a4a";
  const grass = dark ? "#2f4224" : "#9fbf72";
  let seen = 0;
  let bornAt = new Map();
  let t = 0;
  let fly = null;
  let nextFly = 8;

  function layout() {
    const R = rng(5);
    sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, tokens.bg);
    sky.addColorStop(1, tokens.bg2);
    spots = Array.from({ length: MAX }, () => ({
      x: 20 + R() * (w - 40),
      stem: 26 + R() * 44,
      r: 5 + R() * 5,
      color: petals[Math.floor(R() * petals.length)],
      lean: (R() - 0.5) * 8,
    }));
    blades = Array.from({ length: Math.round(w / 6) }, (_, i) => ({ x: i * 6 + R() * 4, hgt: 8 + R() * 14, ph: R() * 6 }));
  }
  layout();

  function flower(s, bloom) {
    const base = h;
    const top = base - s.stem;
    ctx.strokeStyle = leaf;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(s.x, base);
    ctx.quadraticCurveTo(s.x + s.lean, base - s.stem * 0.5, s.x + s.lean * 0.6, top);
    ctx.stroke();
    const cx = s.x + s.lean * 0.6;
    if (bloom <= 0) {
      ctx.fillStyle = leaf;
      ctx.beginPath();
      ctx.ellipse(cx, top, 2.5, 4, 0, 0, Math.PI * 2);
      ctx.fill(); // a bud
      return;
    }
    const r = s.r * bloom;
    ctx.fillStyle = s.color;
    for (let k = 0; k < 5; k++) {
      const a = (k / 5) * Math.PI * 2;
      ctx.beginPath();
      ctx.ellipse(cx + Math.cos(a) * r, top + Math.sin(a) * r, r * 0.75, r * 0.5, a, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = dark ? "#e2c25a" : "#f5c542";
    ctx.beginPath();
    ctx.arc(cx, top, Math.max(1.5, r * 0.45), 0, Math.PI * 2);
    ctx.fill();
  }

  function butterfly(dt) {
    nextFly -= dt;
    if (!fly && nextFly <= 0) {
      const ltr = Math.random() < 0.5;
      fly = { x: ltr ? -20 : w + 20, dir: ltr ? 1 : -1, y0: h * (0.25 + Math.random() * 0.4), age: 0 };
      nextFly = 18 + Math.random() * 20;
    }
    if (!fly) return;
    fly.age += dt;
    fly.x += fly.dir * 45 * dt;
    const y = fly.y0 + Math.sin(fly.age * 0.9) * 30;
    const flap = 0.35 + 0.65 * Math.abs(Math.sin(fly.age * 5)); // about 1.6 wingbeats a second
    ctx.save();
    ctx.translate(fly.x, y);
    ctx.fillStyle = dark ? "#c99be0" : "#b07cd8";
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(side * 5 * flap, -2, 6 * flap, 4.5, side * 0.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(side * 4 * flap, 3, 4 * flap, 3, -side * 0.4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = dark ? "#e8e1d0" : "#3b2f2a";
    ctx.fillRect(-0.8, -5, 1.6, 10);
    ctx.restore();
    if (fly.x < -40 || fly.x > w + 40) fly = null;
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

      // lawn
      ctx.strokeStyle = grass;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (const b of blades) {
        const sway = Math.sin(t * 0.8 + b.ph) * 2;
        ctx.moveTo(b.x, h);
        ctx.lineTo(b.x + sway, h - b.hgt);
      }
      ctx.stroke();

      // flowers: one per answered question; the rest wait as buds
      const n = Math.min(MAX, state.answered);
      if (n > seen) for (let i = seen; i < n; i++) bornAt.set(i, t);
      if (n < seen) bornAt = new Map([...bornAt].filter(([i]) => i < n));
      seen = n;
      const buds = Math.max(n + 6, 12);
      for (let i = 0; i < Math.min(MAX, buds); i++) {
        let bloom = 0;
        if (i < n) bloom = state.still ? 1 : Math.min(1, (t - (bornAt.get(i) ?? -10)) / 1.6);
        flower(spots[i], bloom);
      }

      if (!state.still) butterfly(dt);

      const g = momentGlow(state);
      if (g > 0) {
        const grad = ctx.createRadialGradient(w * 0.5, h, 0, w * 0.5, h, h * 0.5);
        grad.addColorStop(0, `rgba(255,236,170,${0.25 * g})`);
        grad.addColorStop(1, "rgba(255,236,170,0)");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
