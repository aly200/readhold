// Night sky — stars, a rare shooting star, and the moon crossing the sky during your session.
// The moon's phase fills with reading progress: new moon at the start, full moon at the end.
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

const SESSION_ARC = 30 * 60; // the moon crosses the sky over 30 focused minutes

export default function night(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  let sky;
  let stars = [];
  let hills = [];
  let shoot = null;
  let nextShoot = 25 + Math.random() * 30;
  let t = 0;
  const starRGB = dark ? "255,244,220" : "60,70,110";
  const moonLit = dark ? "#f6ecd0" : "#fffaf0";
  const hillColor = dark ? "#070c1a" : "#9aa5c2";

  function layout() {
    const R = rng(41);
    sky = ctx.createLinearGradient(0, 0, 0, h);
    if (dark) {
      sky.addColorStop(0, tokens.bg);
      sky.addColorStop(1, tokens.bg2);
    } else {
      sky.addColorStop(0, "#b9c2dd");
      sky.addColorStop(0.7, tokens.bg);
      sky.addColorStop(1, "#ead9cf");
    }
    stars = Array.from({ length: Math.round((w * h) / (dark ? 5000 : 14000)) }, () => ({
      x: R() * w,
      y: R() * h * 0.8,
      r: 0.5 + R() * 1.2,
      base: 0.3 + R() * 0.5,
      speed: 0.4 + R() * 0.8,
      phase: R() * Math.PI * 2,
    }));
    hills = Array.from({ length: 9 }, (_, i) => ({ x: (i / 8) * w, y: h - 25 - R() * 45 }));
  }
  layout();

  function moon(x, y, r, phase) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.clip();
    ctx.fillStyle = dark ? "#2a3150" : "#c9cfe2"; // the unlit disc
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
    ctx.fillStyle = moonLit;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    // the shadow slides off as the phase fills
    ctx.fillStyle = dark ? "#1f2744" : "#bcc3da";
    ctx.beginPath();
    ctx.arc(x - r * 2 * phase, y, r * 1.02, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.strokeStyle = dark ? "rgba(246,236,208,0.35)" : "rgba(80,90,130,0.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
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

      for (const s of stars) {
        const a = s.base + 0.2 * Math.sin(t * s.speed + s.phase);
        ctx.fillStyle = `rgba(${starRGB},${Math.max(0.05, a)})`;
        ctx.fillRect(s.x, s.y, s.r * 1.5, s.r * 1.5);
      }

      // a rare shooting star: one slow streak, then a long wait
      if (!state.still) {
        nextShoot -= dt;
        if (!shoot && nextShoot <= 0) {
          shoot = { x: w * (0.2 + Math.random() * 0.6), y: h * (0.05 + Math.random() * 0.25), age: 0 };
          nextShoot = 35 + Math.random() * 50;
        }
        if (shoot) {
          shoot.age += dt;
          const k = shoot.age / 1.4;
          const x = shoot.x + k * 220;
          const y = shoot.y + k * 90;
          const a = Math.sin(Math.PI * Math.min(1, k)) * 0.8;
          const grad = ctx.createLinearGradient(x - 80, y - 33, x, y);
          grad.addColorStop(0, `rgba(${starRGB},0)`);
          grad.addColorStop(1, `rgba(${starRGB},${a})`);
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(x - 80, y - 33);
          ctx.lineTo(x, y);
          ctx.stroke();
          if (k >= 1) shoot = null;
        }
      }

      // the moon: crosses the sky over the session; its phase is your progress
      const f = state.session ? Math.min(1, state.session / SESSION_ARC) : 0.35;
      const mx = w * (0.12 + 0.76 * f);
      const my = h * (0.3 - 0.16 * Math.sin(Math.PI * f));
      const g = momentGlow(state);
      const haloR = 70 + 30 * g;
      const halo = ctx.createRadialGradient(mx, my, 20, mx, my, haloR);
      halo.addColorStop(0, `rgba(255,240,200,${0.18 + 0.2 * g})`);
      halo.addColorStop(1, "rgba(255,240,200,0)");
      ctx.fillStyle = halo;
      ctx.fillRect(mx - haloR, my - haloR, haloR * 2, haloR * 2);
      moon(mx, my, 26, Math.min(1, state.progress));

      // low hills on the horizon
      ctx.fillStyle = hillColor;
      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let i = 0; i < hills.length; i++) {
        const p = hills[i];
        const prev = hills[i - 1] ?? p;
        ctx.quadraticCurveTo(prev.x, prev.y, (prev.x + p.x) / 2, (prev.y + p.y) / 2);
      }
      ctx.lineTo(w, hills[hills.length - 1].y);
      ctx.lineTo(w, h);
      ctx.closePath();
      ctx.fill();
    },
  };
}
