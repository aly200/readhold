// Beach — a sunny shore (light) or a warm sunset (dark). Soft waves wash in and out, the sea glints, a palm
// sways, gulls glide and a small sailboat drifts along the horizon. A sandcastle rises on the sand with your
// reading progress, and a little flag goes up at the end. Everything moves slowly; nothing flashes.
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
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const TAU = Math.PI * 2;

export default function beach(env) {
  const { ctx, dark, state } = env;
  let w = env.w;
  let h = env.h;
  let t = 0;
  let horizon, shore, sky, sea, sand, glints, shells, gulls, stars;

  const P = dark
    ? {
        skyTop: "#1c2442", skyMid: "#4a3a6a", skyLow: "#f08c6c", skyHorizon: "#ffc58c",
        sun: "255,170,110", sunCore: "#ffcf8f", seaFar: "#4a4f80", seaNear: "#2d6f86",
        glint: "255,205,150", foam: "255,236,220", wet: "#7c6a58", sandTop: "#b08f68", sandBottom: "#6f5a45",
        palm: "#1c1a26", frond: "#232634", gull: "rgba(40,36,58,0.75)", boat: "#2a2738", sail: "rgba(255,226,200,0.9)",
        castle: "#c7a37a", castleShade: "#9c7d5a", flag: "#ff8f7a", shell: ["#e8c9b0", "#f2b8a8", "#d8c7e8"],
      }
    : {
        skyTop: "#7cc8f0", skyMid: "#b5e2f7", skyLow: "#fbe9cf", skyHorizon: "#fff3dc",
        sun: "255,228,140", sunCore: "#fff3b8", seaFar: "#5bbfd6", seaNear: "#3fd0c9",
        glint: "255,255,255", foam: "255,255,255", wet: "#e3c48f", sandTop: "#f7dfae", sandBottom: "#efc98a",
        palm: "#8a6a4a", frond: "#4f9b5c", gull: "rgba(70,80,96,0.7)", boat: "#c25b4f", sail: "rgba(255,255,255,0.95)",
        castle: "#f2cf8e", castleShade: "#d9ad66", flag: "#ff6f6f", shell: ["#ffffff", "#ffc9c2", "#e2d6ff"],
      };

  function layout() {
    horizon = Math.round(h * 0.56);
    shore = Math.round(h * 0.8);
    sky = ctx.createLinearGradient(0, 0, 0, horizon);
    sky.addColorStop(0, P.skyTop);
    sky.addColorStop(0.55, P.skyMid);
    sky.addColorStop(0.88, P.skyLow);
    sky.addColorStop(1, P.skyHorizon);
    sea = ctx.createLinearGradient(0, horizon, 0, shore);
    sea.addColorStop(0, P.seaFar);
    sea.addColorStop(1, P.seaNear);
    sand = ctx.createLinearGradient(0, shore - 30, 0, h);
    sand.addColorStop(0, P.sandTop);
    sand.addColorStop(1, P.sandBottom);
    const R = rng(11);
    glints = Array.from({ length: Math.round(w / 26) }, () => ({ x: R() * w, y: horizon + 6 + Math.pow(R(), 1.6) * (shore - horizon - 40), len: 6 + R() * 16, ph: R() * TAU, sp: 0.35 + R() * 0.5 }));
    shells = Array.from({ length: Math.round(w / 140) }, () => ({ x: R() * w, y: shore + 30 + R() * (h - shore - 40), r: 2.5 + R() * 3, c: P.shell[Math.floor(R() * P.shell.length)], star: R() < 0.3 }));
    gulls = Array.from({ length: 3 }, (_, i) => ({ x: R() * w, y: h * (0.12 + i * 0.09 + R() * 0.05), v: 14 + R() * 10, s: 0.8 + R() * 0.5, ph: R() * TAU }));
    stars = dark ? Array.from({ length: 60 }, () => ({ x: R() * w, y: R() * horizon * 0.5, r: 0.5 + R() * 1.1, ph: R() * TAU })) : [];
  }
  layout();

  // where the water reaches on the sand: a slow in-and-out, with a gentle ripple along the edge
  const waterline = (x, k) => shore + 18 + Math.sin(t * 0.42 + k) * 14 + Math.sin(x * 0.012 + t * 0.6 + k) * 5;

  function drawSun() {
    const sx = dark ? w * 0.7 : w * 0.8;
    const sy = dark ? horizon - 8 : h * 0.15;
    const r = dark ? 58 : 38;
    const halo = ctx.createRadialGradient(sx, sy, 0, sx, sy, r * 5);
    halo.addColorStop(0, `rgba(${P.sun},0.55)`);
    halo.addColorStop(1, `rgba(${P.sun},0)`);
    ctx.fillStyle = halo;
    ctx.fillRect(sx - r * 5, sy - r * 5, r * 10, r * 10);
    ctx.fillStyle = P.sunCore;
    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, TAU);
    ctx.fill();
    return sx;
  }

  function drawBoat() {
    const span = w + 200;
    const x = ((t * 6 + w * 0.2) % span) - 100;
    const y = horizon + 4 + Math.sin(t * 0.8) * 1.2;
    ctx.fillStyle = P.boat;
    ctx.beginPath();
    ctx.moveTo(x - 16, y);
    ctx.lineTo(x + 16, y);
    ctx.lineTo(x + 11, y + 6);
    ctx.lineTo(x - 11, y + 6);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = P.sail;
    ctx.beginPath();
    ctx.moveTo(x - 1, y - 2);
    ctx.lineTo(x - 1, y - 28);
    ctx.lineTo(x + 13, y - 2);
    ctx.closePath();
    ctx.fill();
  }

  function drawPalm() {
    const bx = Math.max(60, w * 0.07);
    const by = shore + 70;
    const sway = Math.sin(t * 0.5) * 0.05;
    const topX = bx + 70 + sway * 120;
    const topY = by - Math.min(330, h * 0.42);
    ctx.strokeStyle = P.palm;
    ctx.lineCap = "round";
    for (let i = 0; i < 14; i++) {
      const k0 = i / 14;
      const k1 = (i + 1) / 14;
      const x0 = bx + (topX - bx) * Math.sin(k0 * Math.PI * 0.5);
      const y0 = by + (topY - by) * k0;
      const x1 = bx + (topX - bx) * Math.sin(k1 * Math.PI * 0.5);
      const y1 = by + (topY - by) * k1;
      ctx.lineWidth = 16 - k0 * 8;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }
    ctx.fillStyle = P.frond;
    const fronds = [-2.6, -2.1, -1.5, -0.9, -0.35, 0.2, 0.7];
    for (let i = 0; i < fronds.length; i++) {
      const a = fronds[i] + sway * (1 + i * 0.2) + Math.sin(t * 0.9 + i) * 0.03;
      const len = 120 + (i % 3) * 18;
      const ex = topX + Math.cos(a) * len;
      const ey = topY + Math.sin(a) * len + 40;
      const mx = topX + Math.cos(a) * len * 0.5;
      const my = topY + Math.sin(a) * len * 0.5 - 18;
      ctx.beginPath();
      ctx.moveTo(topX, topY);
      ctx.quadraticCurveTo(mx, my - 14, ex, ey);
      ctx.quadraticCurveTo(mx, my + 12, topX, topY);
      ctx.fill();
    }
    ctx.fillStyle = dark ? "#2e2a2a" : "#7a5a3a";
    for (let i = 0; i < 3; i++) {
      ctx.beginPath();
      ctx.arc(topX - 8 + i * 9, topY + 8 + (i % 2) * 5, 7, 0, TAU);
      ctx.fill();
    }
  }

  function drawGull(g, dt) {
    g.x += g.v * dt;
    if (g.x > w + 40) g.x = -40;
    const flap = Math.sin(t * 2.2 + g.ph) * 5 * g.s; // a slow wingbeat (about 0.35 per second)
    const y = g.y + Math.sin(t * 0.4 + g.ph) * 6;
    ctx.strokeStyle = P.gull;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(g.x - 12 * g.s, y - flap);
    ctx.quadraticCurveTo(g.x - 5 * g.s, y - 7 * g.s, g.x, y);
    ctx.quadraticCurveTo(g.x + 5 * g.s, y - 7 * g.s, g.x + 12 * g.s, y - flap);
    ctx.stroke();
  }

  function drawCastle(p) {
    if (p < 0.05) return;
    const cx = w * 0.86;
    const base = Math.min(h - 26, shore + 110);
    const grow = (from) => clamp01((p - from) / 0.12);
    ctx.fillStyle = P.castleShade;
    ctx.beginPath();
    ctx.ellipse(cx, base + 4, 80, 10, 0, 0, TAU);
    ctx.fill();
    const block = (x, y, bw, bh, k) => {
      if (k <= 0) return;
      const hh = bh * k;
      ctx.fillStyle = P.castle;
      ctx.fillRect(x - bw / 2, y - hh, bw, hh);
      ctx.fillStyle = P.castleShade;
      ctx.fillRect(x + bw / 2 - 6, y - hh, 6, hh);
      if (k >= 1) {
        ctx.fillStyle = P.castle;
        for (let i = -1; i <= 1; i++) ctx.fillRect(x + i * (bw / 3) - bw / 10, y - hh - 6, bw / 5, 6);
      }
    };
    block(cx, base, 120, 30, grow(0.05)); // the wall
    block(cx - 46, base - 30, 30, 44, grow(0.25)); // left tower
    block(cx + 46, base - 30, 30, 44, grow(0.45)); // right tower
    block(cx, base - 30, 44, 62, grow(0.65)); // the keep
    if (p >= 0.65) {
      ctx.fillStyle = P.castleShade;
      ctx.beginPath();
      ctx.arc(cx, base - 4, 9, Math.PI, 0);
      ctx.fill();
    }
    const flag = grow(0.88);
    if (flag > 0) {
      const top = base - 30 - 62 - 6;
      const pole = 30 * flag;
      ctx.strokeStyle = P.castleShade;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, top);
      ctx.lineTo(cx, top - pole);
      ctx.stroke();
      const wave = Math.sin(t * 1.6) * 3;
      ctx.fillStyle = P.flag;
      ctx.beginPath();
      ctx.moveTo(cx, top - pole);
      ctx.quadraticCurveTo(cx + 10, top - pole + wave, cx + 20, top - pole + 5);
      ctx.lineTo(cx, top - pole + 11);
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
      const p = clamp01(state.progress);
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, horizon);
      for (const s of stars) {
        ctx.fillStyle = `rgba(255,240,220,${0.35 + 0.25 * Math.sin(t * 0.5 + s.ph)})`;
        ctx.fillRect(s.x, s.y, s.r, s.r);
      }
      const sunX = drawSun();
      ctx.fillStyle = sea;
      ctx.fillRect(0, horizon, w, shore - horizon + 40);

      // the sun's reflection: soft shimmering strokes under the sun that widen toward the shore, and slow glints
      const rows = 16;
      for (let i = 0; i < rows; i++) {
        const k = i / (rows - 1);
        const y = horizon + 5 + k * (shore - horizon - 30);
        const half = 10 + k * 70 + Math.sin(t * 0.7 + i * 1.7) * (6 + k * 10);
        ctx.fillStyle = `rgba(${P.sun},${(dark ? 0.55 : 0.4) * (1 - k * 0.75)})`;
        ctx.fillRect(sunX - half + Math.sin(t * 0.5 + i) * 6, y, half * 2, 2 + k * 2);
      }
      for (const g of glints) {
        const a = Math.max(0, Math.sin(t * g.sp + g.ph)) * 0.6;
        if (a < 0.05) continue;
        ctx.strokeStyle = `rgba(${P.glint},${a})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(g.x, g.y);
        ctx.lineTo(g.x + g.len, g.y);
        ctx.stroke();
      }
      drawBoat();

      // sand, then the wet band and the foam of the wave as it washes in and out
      ctx.fillStyle = sand;
      ctx.fillRect(0, shore - 10, w, h - shore + 10);
      ctx.fillStyle = P.wet;
      ctx.beginPath();
      ctx.moveTo(0, shore - 10);
      for (let x = 0; x <= w + 20; x += 20) ctx.lineTo(x, waterline(x, 0) + 22);
      ctx.lineTo(w, shore - 10);
      ctx.closePath();
      ctx.fill();
      for (const [k, a] of [[0, 1], [2.1, 0.55]]) {
        ctx.fillStyle = sea;
        ctx.beginPath();
        ctx.moveTo(0, shore - 12);
        for (let x = 0; x <= w + 20; x += 20) ctx.lineTo(x, waterline(x, k));
        ctx.lineTo(w, shore - 12);
        ctx.closePath();
        ctx.globalAlpha = a;
        ctx.fill();
        ctx.strokeStyle = `rgba(${P.foam},0.85)`;
        ctx.lineWidth = 3;
        ctx.beginPath();
        for (let x = 0; x <= w + 20; x += 20) (x === 0 ? ctx.moveTo : ctx.lineTo).call(ctx, x, waterline(x, k));
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      for (const s of shells) {
        ctx.fillStyle = s.c;
        if (s.star) {
          ctx.beginPath();
          for (let i = 0; i < 10; i++) {
            const r = i % 2 ? s.r * 0.8 : s.r * 2;
            const a = (i / 10) * TAU - Math.PI / 2;
            ctx.lineTo(s.x + Math.cos(a) * r, s.y + Math.sin(a) * r);
          }
          ctx.closePath();
          ctx.fill();
        } else {
          ctx.beginPath();
          ctx.ellipse(s.x, s.y, s.r * 1.3, s.r, 0, 0, TAU);
          ctx.fill();
        }
      }
      drawPalm();
      drawCastle(p);
      for (const g of gulls) drawGull(g, dt);

      const glow = momentGlow(state);
      if (glow > 0) {
        const grad = ctx.createRadialGradient(sunX, horizon, 0, sunX, horizon, Math.max(w, h) * 0.6);
        grad.addColorStop(0, `rgba(${P.sun},${0.22 * glow})`);
        grad.addColorStop(1, `rgba(${P.sun},0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
