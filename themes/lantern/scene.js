// Lanterns — a lake below mountains. The picture follows your day:
//   • the sky takes its colours from the real clock (dawn, day, golden hour, dusk, night);
//   • the moon (the sun, in the light look) climbs across the sky as you read the open document;
//   • one lantern floats on the water for every card reviewed today, every question answered
//     and every five minutes of the reading session, on top of a few that are always there;
//   • now and then a lantern lifts off and drifts up. A question answered releases one too.
// Nothing blinks: lanterns breathe over several seconds, and everything else only drifts.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const BASE = 6; // lanterns that are always on the lake
const MAX = 36;
const RISERS = 6; // lanterns in the air at once, at most

// [hour, [top of the sky, middle, at the horizon]] — blended from one row to the next through the day
const SKY = {
  light: [
    [0, ["#59639f", "#a58cb6", "#e3b7a6"]],
    [5.5, ["#93acd8", "#f0c5c4", "#ffe0b5"]],
    [9, ["#8cc0e8", "#c6e2f3", "#f6ecd8"]],
    [15.5, ["#86b4e2", "#d9dceb", "#fbe3bd"]],
    [18, ["#7e9bd2", "#f1bd9a", "#ffd399"]],
    [20, ["#5f69a8", "#d48f9d", "#f5b78b"]],
    [22, ["#59639f", "#a58cb6", "#e3b7a6"]],
  ],
  dark: [
    [0, ["#0b0f2a", "#161b47", "#2c2a5a"]],
    [5, ["#161c44", "#43366a", "#9a5c70"]],
    [8, ["#121839", "#222a5c", "#3b3f78"]],
    [16.5, ["#151a40", "#2d2b62", "#57407a"]],
    [18.5, ["#1a1944", "#4d2f67", "#b2566a"]],
    [20.5, ["#0e1331", "#1b204f", "#353160"]],
    [23, ["#0b0f2a", "#161b47", "#2c2a5a"]],
  ],
};

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
function blend(a, b, k) {
  const A = rgb(a);
  const B = rgb(b);
  return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * k)).join(",")})`;
}
function skyAt(rows, hour) {
  let i = rows.length - 1;
  while (i > 0 && rows[i][0] > hour) i--;
  const from = rows[i];
  const to = rows[(i + 1) % rows.length];
  const end = i + 1 < rows.length ? to[0] : 24;
  const k = Math.min(1, Math.max(0, (hour - from[0]) / Math.max(0.01, end - from[0])));
  const s = k * k * (3 - 2 * k); // ease in and out, so each look holds for a while
  return from[1].map((c, j) => blend(c, to[1][j], s));
}

function glowSprite(size, inner, outer) {
  if (typeof OffscreenCanvas === "undefined") return null;
  const c = new OffscreenCanvas(size, size);
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, inner);
  grad.addColorStop(1, outer);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  return c;
}

export default function lanterns(env) {
  const { ctx, dark, state } = env;
  let w = env.w;
  let h = env.h;
  let hz = 0; // the horizon
  let sky = null;
  let water = null;
  let skyMinute = -1;
  let night = 0; // 0 by day … 1 at night: stars and fireflies follow it
  let far = [];
  let near = [];
  let stars = [];
  let ripples = [];
  let flies = [];
  let boats = [];
  let order = [];
  let risers = [];
  let nextRise = 6;
  let seenMoment = state.moment;
  let seen = 0;
  let born = new Map();
  let t = 0;

  const paper = dark ? ["#ffb35c", "#ff9a5e", "#ffd27a", "#ff8b72", "#f6b6cf"] : ["#f08a3c", "#e8743f", "#f2b13e", "#e7645a", "#e58bb0"];
  const glow = glowSprite(96, dark ? "rgba(255,188,110,0.55)" : "rgba(255,170,90,0.4)", "rgba(255,180,100,0)");
  const halo = glowSprite(160, dark ? "rgba(236,232,255,0.5)" : "rgba(255,244,210,0.75)", "rgba(255,255,255,0)");

  function ridge(R, base, amp, step) {
    const a = [R() * 6, R() * 6, R() * 6];
    const pts = [];
    for (let x = -step; x <= w + step; x += step) {
      const u = x / Math.max(320, w);
      const y = Math.sin(u * 5.1 + a[0]) * 0.5 + Math.sin(u * 11.3 + a[1]) * 0.3 + Math.sin(u * 23.7 + a[2]) * 0.2;
      pts.push([x, base - amp * (0.55 + 0.45 * y) - R() * amp * 0.06]);
    }
    return pts;
  }

  function layout() {
    const R = rng(31);
    hz = Math.round(h * 0.62);
    far = ridge(R, hz, h * 0.2, 46);
    near = ridge(R, hz, h * 0.11, 34);
    stars = Array.from({ length: Math.round((w * hz) / 9000) }, () => ({ x: R() * w, y: R() * hz * 0.9, r: 0.5 + R() * 1.1, ph: R() * 6.28, sp: 0.5 + R() * 0.7 }));
    ripples = Array.from({ length: 30 }, () => ({ x: R() * w, y: hz + 6 + R() * (h - hz - 10), len: 18 + R() * 50, ph: R() * 6.28 }));
    flies = Array.from({ length: 14 }, () => ({ x: R() * w, y: hz - 46 + R() * 60, a: R() * 6.28, b: R() * 6.28 }));
    boats = Array.from({ length: MAX }, (_, i) => {
      const z = 0.12 + R() * 0.88; // 0 far … 1 near
      return { i, z, x: R(), y: hz + 10 + z * z * Math.max(40, h - hz - 46), size: 5 + z * 10, drift: (R() < 0.5 ? -1 : 1) * (3 + R() * 6) * (0.4 + z), ph: R() * 6.28, color: paper[Math.floor(R() * paper.length)] };
    });
    order = [...boats].sort((p, q) => p.z - q.z);
    skyMinute = -1;
  }
  layout();

  function paintSky() {
    const now = new Date();
    const minute = now.getHours() * 60 + now.getMinutes();
    if (minute === skyMinute && sky) return;
    skyMinute = minute;
    const hour = minute / 60;
    const c = skyAt(dark ? SKY.dark : SKY.light, hour);
    sky = ctx.createLinearGradient(0, 0, 0, hz);
    sky.addColorStop(0, c[0]);
    sky.addColorStop(0.62, c[1]);
    sky.addColorStop(1, c[2]);
    water = ctx.createLinearGradient(0, hz, 0, h);
    water.addColorStop(0, c[2]);
    water.addColorStop(0.18, c[1]);
    water.addColorStop(1, c[0]);
    const dusk = hour < 6 ? 1 : hour < 7.5 ? (7.5 - hour) / 1.5 : hour < 18.5 ? 0 : hour < 20.5 ? (hour - 18.5) / 2 : 1;
    night = dark ? 0.55 + 0.45 * dusk : dusk * 0.7;
  }

  function path(pts, mirror) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], hz);
    for (const [x, y] of pts) ctx.lineTo(x, mirror ? hz + (hz - y) * 0.55 : y);
    ctx.lineTo(pts[pts.length - 1][0], hz);
    ctx.closePath();
    ctx.fill();
  }

  function sprite(img, x, y, size, alpha) {
    if (alpha <= 0.01) return;
    ctx.globalAlpha = alpha;
    if (img) ctx.drawImage(img, x - size / 2, y - size / 2, size, size);
    else {
      ctx.fillStyle = dark ? "#ffc27a" : "#ffb060";
      ctx.globalAlpha = alpha * 0.25;
      ctx.beginPath();
      ctx.arc(x, y, size * 0.3, 0, 6.2832);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // one paper lantern: a soft glow, the paper, a dark rim above and below, and the light inside
  function lantern(x, y, size, color, alpha, breathe) {
    sprite(glow, x, y, size * 6.5, alpha * breathe);
    const bw = size * 0.95;
    const bh = size * 1.2;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.ellipse(x, y, bw / 2, bh / 2, 0, 0, 6.2832);
    ctx.fill();
    ctx.fillStyle = dark ? "rgba(60,30,20,0.75)" : "rgba(90,45,25,0.7)";
    ctx.fillRect(x - bw * 0.3, y - bh / 2 - 1, bw * 0.6, Math.max(1.2, size * 0.16));
    ctx.fillRect(x - bw * 0.3, y + bh / 2 - Math.max(1.2, size * 0.16) + 1, bw * 0.6, Math.max(1.2, size * 0.16));
    ctx.fillStyle = `rgba(255,244,214,${0.5 + 0.35 * breathe})`;
    ctx.beginPath();
    ctx.ellipse(x, y + bh * 0.06, bw * 0.22, bh * 0.28, 0, 0, 6.2832);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function launch(x) {
    if (risers.length >= RISERS) return;
    risers.push({ x: x ?? w * (0.12 + Math.random() * 0.76), y: hz - 6, age: 0, ph: Math.random() * 6.28, color: paper[Math.floor(Math.random() * paper.length)] });
  }

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
      layout();
    },
    frame(dt) {
      t += dt;
      paintSky();
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, hz);

      // stars come out as the day ends
      if (night > 0.05) {
        ctx.fillStyle = "#ffffff";
        for (const s of stars) {
          ctx.globalAlpha = night * (0.35 + 0.3 * Math.sin(t * s.sp + s.ph)) * (1 - (s.y / hz) * 0.6);
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r, 0, 6.2832);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }

      // the moon (or the sun) climbs with your reading
      const p = 0.1 + 0.8 * Math.min(1, Math.max(0, state.progress));
      const mx = w * (0.14 + 0.72 * p);
      const my = hz - Math.sin(Math.PI * p) * hz * 0.66 - 14;
      const mr = Math.max(14, Math.min(w, h) * 0.035);
      sprite(halo, mx, my, mr * 7, 0.9);
      ctx.fillStyle = dark ? "#f2efff" : "#fff6dc";
      ctx.beginPath();
      ctx.arc(mx, my, mr, 0, 6.2832);
      ctx.fill();
      if (dark) {
        ctx.fillStyle = "rgba(180,176,214,0.45)"; // two soft seas on the moon
        ctx.beginPath();
        ctx.arc(mx - mr * 0.3, my - mr * 0.2, mr * 0.22, 0, 6.2832);
        ctx.arc(mx + mr * 0.28, my + mr * 0.3, mr * 0.15, 0, 6.2832);
        ctx.fill();
      }

      // mountains, and the lake that mirrors them
      ctx.fillStyle = dark ? "rgba(52,56,112,0.75)" : "rgba(126,132,184,0.6)";
      path(far, false);
      ctx.fillStyle = dark ? "#171b40" : "#5d6596";
      path(near, false);
      ctx.fillStyle = water;
      ctx.fillRect(0, hz, w, h - hz);
      ctx.fillStyle = dark ? "rgba(16,19,48,0.5)" : "rgba(84,92,142,0.3)";
      path(near, true);

      // the light of the moon lies on the water in broken lines
      ctx.fillStyle = dark ? "rgba(240,236,255,0.28)" : "rgba(255,246,220,0.55)";
      for (let k = 0; k < 11; k++) {
        const y = hz + 6 + k * k * 1.6 + k * 5;
        if (y > h) break;
        const half = mr * (0.6 + k * 0.22) * (0.75 + 0.25 * Math.sin(t * 0.6 + k * 1.3));
        ctx.fillRect(mx - half + Math.sin(t * 0.4 + k) * 5, y, half * 2, 1.6);
      }
      ctx.fillStyle = dark ? "rgba(255,255,255,0.07)" : "rgba(255,255,255,0.3)";
      for (const r of ripples) ctx.fillRect(r.x + Math.sin(t * 0.35 + r.ph) * 14, r.y, r.len, 1);

      // fireflies near the shore, at night
      if (night > 0.3) {
        ctx.fillStyle = dark ? "#ffe59a" : "#fff0b0";
        for (const f of flies) {
          ctx.globalAlpha = (night - 0.3) * (0.3 + 0.35 * (0.5 + 0.5 * Math.sin(t * 0.9 + f.a)));
          ctx.beginPath();
          ctx.arc(f.x + Math.sin(t * 0.3 + f.a) * 22, f.y + Math.cos(t * 0.23 + f.b) * 11, 1.6, 0, 6.2832);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }

      // lanterns on the water: a few are always there, the rest you lit today
      const n = Math.min(MAX, BASE + state.reviewed + state.answered + Math.floor(state.session / 300));
      if (n > seen) for (let i = seen; i < n; i++) born.set(i, seen === 0 ? -10 : t);
      if (n < seen) born = new Map([...born].filter(([i]) => i < n));
      seen = n;
      for (const b of order) {
        if (b.i >= n) continue;
        const alpha = state.still ? 1 : Math.min(1, (t - (born.get(b.i) ?? -10)) / 2.4);
        const span = w + 80;
        const x = ((((b.x * span + b.drift * t) % span) + span) % span) - 40;
        const y = b.y + Math.sin(t * 0.7 + b.ph) * 1.4 * b.z;
        const breathe = 0.82 + 0.18 * Math.sin(t * 1.2 + b.ph); // one breath in about five seconds
        ctx.fillStyle = b.color; // its light on the water, in three fading strokes
        for (let k = 1; k <= 3; k++) {
          ctx.globalAlpha = alpha * breathe * (dark ? 0.3 : 0.22) / k;
          ctx.fillRect(x - b.size * 0.3 + Math.sin(t * 0.9 + b.ph + k) * 1.5, y + b.size * (0.5 + k * 0.55), b.size * 0.6, b.size * 0.3);
        }
        ctx.globalAlpha = 1;
        lantern(x, y, b.size, b.color, alpha, breathe);
      }

      // lanterns in the air
      if (state.still) {
        const R = rng(7);
        for (let k = 0; k < 4; k++) lantern(w * (0.15 + R() * 0.7), hz * (0.2 + R() * 0.55), 7 + R() * 5, paper[k % paper.length], 0.9, 0.9);
        return;
      }
      if (state.moment !== seenMoment) {
        seenMoment = state.moment;
        launch(w * 0.5);
      }
      nextRise -= dt;
      if (nextRise <= 0) {
        launch();
        nextRise = 9 + Math.random() * 11;
      }
      risers = risers.filter((r) => r.y > -30);
      for (const r of risers) {
        r.age += dt;
        r.y -= 13 * dt;
        const up = 1 - Math.max(0, r.y) / hz; // 0 at the water … 1 at the top
        const size = 12 - up * 6.5;
        const alpha = Math.min(1, r.age / 2.5) * Math.min(1, Math.max(0, r.y + 30) / (hz * 0.2));
        lantern(r.x + Math.sin(r.age * 0.45 + r.ph) * 16, r.y, size, r.color, alpha, 0.85 + 0.15 * Math.sin(r.age * 1.1 + r.ph));
      }
    },
  };
}
