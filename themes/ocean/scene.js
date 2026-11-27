// Ocean — sunlit shallows (light) or the glowing deep sea (dark). Caustic ripples and soft light rays near the
// surface, rising bubbles, swaying kelp, small schools of fish, and in the dark a few slowly pulsing jellyfish.
// A coral reef grows along the seabed with reading progress. Everything moves slowly; nothing flashes.
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

const BUBBLES = 38;
const BURST = 26; // extra bubbles for a quiet moment (they never respawn)
const SPECKS = 30;

export default function ocean(env) {
  const { ctx, tokens, dark, state } = env;
  let w = env.w;
  let h = env.h;
  let water, rayGrad, surfaceGrad, bedGrad, glow, bedPath;
  let bubbles = [];
  let burst = [];
  let specks = [];
  let kelp = [];
  let corals = [];
  let schools = [];
  let jellies = [];
  let t = 0;
  let lastMoment = state.moment;

  const P = dark
    ? {
        top: tokens.bg2,
        mid: "#071a26",
        bottom: "#020a10",
        ray: "120,220,225",
        rayA: 0.05,
        caustic: "130,225,230",
        causticA: 0.06,
        bubble: "150,225,235",
        speck: "110,240,215",
        fish: "120,200,210",
        fishA: 0.2,
        kelp: ["#0f3a33", "#12443a", "#0c302c"],
        bedTop: "#0f242a",
        bedBottom: "#06121a",
        corals: ["#a8506a", "#b8743f", "#7e58a6", "#2f9c95", "#b64f7e", "#4b8fb0"],
        tip: "127,245,224",
        turtle: "110,190,190",
        turtleA: 0.22,
        bloom: "120,230,220",
      }
    : {
        top: "#d9f4f6",
        mid: tokens.bg,
        bottom: "#6fb4cc",
        ray: "255,255,236",
        rayA: 0.16,
        caustic: "255,255,255",
        causticA: 0.16,
        bubble: "255,255,255",
        speck: "255,255,255",
        fish: "22,72,96",
        fishA: 0.3,
        kelp: ["#3f8a5a", "#4f9a52", "#5f9d4a"],
        bedTop: "#ead9aa",
        bedBottom: "#cdb57e",
        corals: ["#ec8f7e", "#f4a95f", "#c98bc4", "#e9c86a", "#f07f9b", "#83cdb0"],
        tip: "255,250,235",
        turtle: "30,82,92",
        turtleA: 0.32,
        bloom: "255,250,220",
      };

  const bedY = (x) => h - (30 + 9 * Math.sin(x * 0.0041 + 1.3) + 6 * Math.sin(x * 0.0113 + 2.1));

  function layout() {
    const R = rng(57);
    water = ctx.createLinearGradient(0, 0, 0, h);
    water.addColorStop(0, P.top);
    water.addColorStop(0.45, P.mid);
    water.addColorStop(1, P.bottom);
    surfaceGrad = ctx.createLinearGradient(0, 0, 0, h * 0.14);
    surfaceGrad.addColorStop(0, `rgba(${P.ray},${dark ? 0.08 : 0.35})`);
    surfaceGrad.addColorStop(1, `rgba(${P.ray},0)`);
    rayGrad = ctx.createLinearGradient(0, 0, 0, h * 0.85);
    rayGrad.addColorStop(0, `rgba(${P.ray},1)`);
    rayGrad.addColorStop(1, `rgba(${P.ray},0)`);
    bedGrad = ctx.createLinearGradient(0, h - 50, 0, h);
    bedGrad.addColorStop(0, P.bedTop);
    bedGrad.addColorStop(1, P.bedBottom);
    // a soft glow of radius 1 at the origin; drawn with translate + scale (jellyfish)
    glow = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
    glow.addColorStop(0, "rgba(130,230,255,0.55)");
    glow.addColorStop(0.4, "rgba(110,200,255,0.18)");
    glow.addColorStop(1, "rgba(110,200,255,0)");

    bedPath = new Path2D();
    bedPath.moveTo(0, h);
    for (let x = 0; x <= w + 20; x += 20) bedPath.lineTo(x, bedY(x));
    bedPath.lineTo(w, h);
    bedPath.closePath();

    bubbles = Array.from({ length: BUBBLES }, () => newBubble(R, true));
    burst = [];
    specks = Array.from({ length: dark ? SPECKS : Math.round(SPECKS * 0.7) }, () => ({
      x: R() * w,
      y: R() * h * 0.9,
      r: 0.6 + R() * 1.2,
      drift: 2 + R() * 4,
      period: 4 + R() * 5, // seconds per slow glow cycle
      phase: R() * TAU,
    }));

    const nk = Math.min(16, Math.round(w / 120) + 4);
    kelp = Array.from({ length: nk }, (_, i) => {
      const x = ((i + 0.5) / nk) * w + (R() - 0.5) * (w / nk) * 0.8;
      return {
        x,
        base: bedY(x) + 8,
        segH: (h * (0.16 + R() * 0.2)) / 8,
        width: 3 + R() * 2.5,
        phase: R() * TAU,
        color: P.kelp[Math.floor(R() * P.kelp.length)],
      };
    });

    // the reef: fixed spots along the seabed, grown in a shuffled order so it fills in everywhere at once
    const nc = Math.max(14, Math.min(34, Math.round(w / 52)));
    const order = Array.from({ length: nc }, (_, i) => i);
    for (let i = nc - 1; i > 0; i--) {
      const j = Math.floor(R() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    corals = order.map((slot, rank) => {
      const x = ((slot + 0.5) / nc) * w + (R() - 0.5) * (w / nc) * 0.7;
      const type = ["branch", "fan", "brain", "anemone"][Math.floor(R() * 4)];
      const c = {
        x,
        base: bedY(x) + 4,
        rank,
        type,
        size: (type === "brain" ? 30 : type === "anemone" ? 46 : 60) + R() * 50,
        color: P.corals[Math.floor(R() * P.corals.length)],
        phase: R() * TAU,
        parts: [],
      };
      if (type === "branch") {
        const byDepth = [[], [], [], []];
        const grow = (x0, y0, a, len, d) => {
          const x1 = x0 + Math.sin(a) * len;
          const y1 = y0 - Math.cos(a) * len;
          byDepth[d].push([x0, y0, x1, y1]);
          if (d < 3) {
            grow(x1, y1, a - 0.3 - R() * 0.35, len * (0.62 + R() * 0.15), d + 1);
            grow(x1, y1, a + 0.3 + R() * 0.35, len * (0.62 + R() * 0.15), d + 1);
          }
        };
        grow(0, 0, (R() - 0.5) * 0.3, 0.36, 0);
        c.parts = byDepth;
      } else if (type === "fan") {
        const n = 9 + Math.floor(R() * 5);
        c.parts = Array.from({ length: n }, (_, k) => -1.15 + (2.3 * k) / (n - 1) + (R() - 0.5) * 0.08);
      } else if (type === "anemone") {
        const n = 7 + Math.floor(R() * 4);
        c.parts = Array.from({ length: n }, (_, k) => -1.1 + (2.2 * k) / (n - 1));
      }
      return c;
    });

    schools = Array.from({ length: 3 }, (_, i) => newSchool(R, i, true));
    jellies = dark
      ? Array.from({ length: 3 }, (_, i) => ({
          x: w * (0.18 + 0.32 * i) + (R() - 0.5) * w * 0.1,
          y: h * (0.25 + R() * 0.4),
          r: 10 + R() * 8,
          period: 4.5 + R() * 2.5, // seconds per pulse (never faster than ~3 s even at the liveliest pace)
          phase: R() * TAU,
          vx: (R() - 0.5) * 3,
        }))
      : [];
  }

  function newBubble(R, anywhere) {
    const r = 1.2 + R() * R() * 4.5;
    const x = R() * w;
    return {
      x,
      y: anywhere ? R() * h : bedY(x) + R() * 30,
      r,
      vy: 14 + r * 5 + R() * 8,
      wob: 1.2 + R() * 1.4,
      amp: 2 + R() * 4,
      phase: R() * TAU,
    };
  }

  function newSchool(R, i, initial) {
    const dir = R() < 0.5 ? 1 : -1;
    const n = 5 + Math.floor(R() * 5);
    const scale = 0.7 + R() * 0.6;
    return {
      active: i < 2, // the third school joins once you're halfway through
      dir,
      x: initial ? w * (0.15 + R() * 0.7) : dir > 0 ? -60 : w + 60,
      y: h * (0.18 + R() * 0.45),
      speed: (w + 360) / (30 + R() * 30), // crosses the screen in 30–60 s
      wait: 0,
      bob: R() * TAU,
      fish: Array.from({ length: n }, () => ({
        dx: R() * 110 * scale,
        dy: (R() - 0.5) * 50 * scale,
        len: (9 + R() * 6) * scale,
        phase: R() * TAU,
      })),
    };
  }

  layout();
  const RT = rng(91); // runtime randomness (respawns)

  function drawRays() {
    ctx.fillStyle = rayGrad;
    for (let i = 0; i < 5; i++) {
      const sway = Math.sin(t * 0.07 + i * 1.9) * w * 0.04;
      const x = w * (0.06 + i * 0.21) + sway;
      const a = P.rayA * (0.65 + 0.35 * Math.sin(t * 0.11 + i * 2.3));
      ctx.globalAlpha = a;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + w * 0.05, 0);
      ctx.lineTo(x + w * 0.2, h * 0.85);
      ctx.lineTo(x + w * 0.08, h * 0.85);
      ctx.closePath();
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function drawCaustics() {
    ctx.fillStyle = surfaceGrad;
    ctx.fillRect(0, 0, w, h * 0.14);
    ctx.lineCap = "round";
    const step = 18;
    for (let i = 0; i < 7; i++) {
      const y0 = h * (0.015 + i * 0.032);
      const depth = 1 - i / 7;
      const k1 = 0.011 + i * 0.0017;
      const k2 = 0.027 - i * 0.0019;
      ctx.strokeStyle = `rgba(${P.caustic},${P.causticA * depth})`;
      ctx.lineWidth = 1 + 2.2 * depth;
      ctx.beginPath();
      for (let x = -step; x <= w + step; x += step) {
        const y = y0 + 6 * Math.sin(x * k1 + t * 0.32 + i * 1.3) + 3.5 * Math.sin(x * k2 - t * 0.21 + i * 0.7);
        if (x === -step) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
  }

  function drawSpecks(dt) {
    for (const s of specks) {
      s.y -= s.drift * 0.3 * dt;
      s.x += Math.sin(t * 0.1 + s.phase) * 0.6 * dt;
      if (s.y < -4) s.y = h * 0.9;
      const a = dark ? 0.28 + 0.22 * Math.sin((t * TAU) / s.period + s.phase) : 0.2 + 0.1 * Math.sin((t * TAU) / s.period + s.phase);
      ctx.fillStyle = `rgba(${P.speck},${a})`;
      ctx.fillRect(s.x, s.y, s.r, s.r);
    }
  }

  function drawSchools(dt) {
    schools[2].active = schools[2].active || state.progress >= 0.5;
    for (let i = 0; i < schools.length; i++) {
      const s = schools[i];
      if (!s.active) continue;
      if (s.wait > 0) {
        s.wait -= dt;
        continue;
      }
      s.x += s.dir * s.speed * dt;
      const tail = 140;
      if ((s.dir > 0 && s.x - tail > w + 40) || (s.dir < 0 && s.x + tail < -40)) {
        schools[i] = newSchool(RT, i, false);
        schools[i].active = true;
        schools[i].wait = 6 + RT() * 14;
        continue;
      }
      const sy = s.y + Math.sin(t * 0.18 + s.bob) * 14;
      ctx.fillStyle = `rgba(${P.fish},${P.fishA})`;
      ctx.beginPath();
      for (const f of s.fish) {
        const cx = s.x - s.dir * f.dx;
        const cy = sy + f.dy + Math.sin(t * 0.9 + f.phase) * 3;
        const L = f.len;
        const wig = Math.sin(t * 6 + f.phase) * 0.22;
        ctx.moveTo(cx + L * 0.5, cy);
        ctx.ellipse(cx, cy, L * 0.5, L * 0.19, 0, 0, TAU);
        const bx = cx - s.dir * L * 0.42;
        ctx.moveTo(bx, cy);
        ctx.lineTo(cx - s.dir * L * 0.85, cy - L * (0.26 - wig));
        ctx.lineTo(cx - s.dir * L * 0.85, cy + L * (0.26 + wig));
        ctx.closePath();
      }
      ctx.fill();
    }
  }

  function drawJellies(dt) {
    for (const j of jellies) {
      const pulse = 0.5 + 0.5 * Math.sin((t * TAU) / j.period + j.phase); // 1 = fully contracted
      j.y -= (3 + 9 * pulse) * dt;
      j.x += j.vx * dt;
      if (j.y < -j.r * 5) {
        j.y = h + j.r * 4;
        j.x = w * (0.1 + RT() * 0.8);
      }
      ctx.save();
      ctx.translate(j.x, j.y);
      ctx.save();
      ctx.scale(j.r * 4, j.r * 4);
      ctx.globalAlpha = 0.45 + 0.2 * pulse;
      ctx.fillStyle = glow;
      ctx.fillRect(-1, -1, 2, 2);
      ctx.restore();
      const bw = j.r * (1 - 0.16 * pulse);
      const bh = j.r * (0.75 + 0.15 * pulse);
      ctx.strokeStyle = "rgba(160,230,255,0.28)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let k = 0; k < 5; k++) {
        const tx = -bw * 0.7 + (bw * 1.4 * k) / 4;
        const len = j.r * (2.2 + 0.5 * Math.sin(k * 1.7));
        ctx.moveTo(tx, 0);
        ctx.quadraticCurveTo(tx + Math.sin(t * 0.9 + k + j.phase) * 5, len * 0.5, tx + Math.sin(t * 0.7 + k) * 3, len);
      }
      ctx.stroke();
      ctx.fillStyle = "rgba(140,220,255,0.3)";
      ctx.strokeStyle = "rgba(175,238,255,0.5)";
      ctx.beginPath();
      ctx.moveTo(-bw, 0);
      ctx.bezierCurveTo(-bw, -bh * 1.35, bw, -bh * 1.35, bw, 0);
      ctx.quadraticCurveTo(0, bh * 0.3, -bw, 0);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    }
  }

  function drawTurtle() {
    const a = clamp01((state.progress - 0.7) / 0.15);
    if (a <= 0) return;
    const span = w + 320;
    const x = ((t * (span / 75) + w * 0.72 + 160) % span) - 160;
    const y = h * 0.36 + Math.sin(t * 0.09) * 22;
    const flap = Math.sin(t * 0.8) * 0.45;
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = `rgba(${P.turtle},${P.turtleA * a})`;
    ctx.beginPath();
    ctx.ellipse(0, 0, 26, 17, 0, 0, TAU);
    ctx.moveTo(38, -1);
    ctx.ellipse(31, -1, 7, 5.5, 0, 0, TAU);
    ctx.fill();
    for (const [fx, fy, len, side, base] of [[10, -12, 30, -1, -0.6], [10, 12, 30, 1, 0.6], [-18, -9, 13, -1, -2.3], [-18, 9, 13, 1, 2.3]]) {
      ctx.save();
      ctx.translate(fx, fy);
      ctx.rotate(base + side * flap * (len > 20 ? 1 : 0.4));
      ctx.beginPath();
      ctx.ellipse(len * 0.5, 0, len * 0.5, len * 0.17, 0, 0, TAU);
      ctx.fill();
      ctx.restore();
    }
    ctx.restore();
  }

  function drawKelp() {
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const k of kelp) {
      const pts = [];
      for (let s = 0; s <= 8; s++) {
        const sway = Math.sin(t * 0.33 + k.phase + s * 0.35) * s * s * 0.45 + Math.sin(t * 0.13 + k.phase) * s * 1.2;
        pts.push([k.x + sway, k.base - s * k.segH]);
      }
      ctx.strokeStyle = k.color;
      ctx.fillStyle = k.color;
      ctx.globalAlpha = dark ? 0.9 : 0.55;
      ctx.lineWidth = k.width;
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let s = 1; s < pts.length - 1; s++) {
        const mx = (pts[s][0] + pts[s + 1][0]) / 2;
        const my = (pts[s][1] + pts[s + 1][1]) / 2;
        ctx.quadraticCurveTo(pts[s][0], pts[s][1], mx, my);
      }
      ctx.lineTo(pts[8][0], pts[8][1]);
      ctx.stroke();
      ctx.beginPath();
      for (let s = 2; s <= 8; s++) {
        const side = s % 2 ? 1 : -1;
        const [px, py] = pts[s];
        const lx = px + side * 7;
        const rot = side * -0.5;
        ctx.moveTo(lx + 8 * Math.cos(rot), py + 8 * Math.sin(rot));
        ctx.ellipse(lx, py, 8, 2.8, rot, 0, TAU);
      }
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function drawCoral(c, s) {
    ctx.save();
    ctx.translate(c.x, c.base);
    ctx.rotate(Math.sin(t * 0.25 + c.phase) * 0.025);
    ctx.scale(s, s);
    ctx.fillStyle = c.color;
    ctx.strokeStyle = c.color;
    ctx.lineCap = "round";
    if (c.type === "branch") {
      for (let d = 0; d < 4; d++) {
        ctx.lineWidth = (5 - d * 1.1) / s;
        ctx.beginPath();
        for (const [x0, y0, x1, y1] of c.parts[d]) {
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
        }
        ctx.stroke();
      }
      if (dark) {
        ctx.fillStyle = `rgba(${P.tip},0.55)`;
        ctx.beginPath();
        for (const [, , x1, y1] of c.parts[3]) {
          ctx.moveTo(x1 + 1.6 / s, y1);
          ctx.arc(x1, y1, 1.6 / s, 0, TAU);
        }
        ctx.fill();
      }
    } else if (c.type === "fan") {
      ctx.globalAlpha = 0.32;
      ctx.beginPath();
      ctx.ellipse(0, -0.48, 0.5, 0.44, 0, 0, TAU);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1.4 / s;
      ctx.beginPath();
      for (const a of c.parts) {
        ctx.moveTo(0, 0);
        ctx.quadraticCurveTo(Math.sin(a) * 0.25, -0.35, Math.sin(a) * 0.48, -0.48 - Math.cos(a) * 0.42);
      }
      ctx.stroke();
      ctx.lineWidth = 3 / s;
      ctx.beginPath();
      ctx.moveTo(0, 0.04);
      ctx.lineTo(0, -0.12);
      ctx.stroke();
    } else if (c.type === "brain") {
      ctx.beginPath();
      ctx.ellipse(0, 0, 0.55, 0.42, 0, Math.PI, TAU);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = dark ? "rgba(0,0,0,0.3)" : "rgba(90,40,30,0.22)";
      ctx.lineWidth = 1.2 / s;
      ctx.beginPath();
      for (let k = 1; k <= 3; k++) {
        ctx.moveTo(-(0.55 - k * 0.12), 0);
        ctx.ellipse(0, 0, 0.55 - k * 0.12, 0.42 - k * 0.1, 0, Math.PI, TAU);
      }
      ctx.stroke();
    } else {
      // anemone: a short column and swaying tentacles
      ctx.fillRect(-0.09, -0.32, 0.18, 0.34);
      ctx.lineWidth = 2.6 / s;
      ctx.beginPath();
      const tips = [];
      for (let k = 0; k < c.parts.length; k++) {
        const a = c.parts[k] + Math.sin(t * 0.7 + c.phase + k * 0.6) * 0.12;
        const ex = Math.sin(a) * 0.42;
        const ey = -0.32 - Math.cos(a) * 0.42;
        ctx.moveTo(0, -0.3);
        ctx.quadraticCurveTo(Math.sin(a) * 0.12, -0.55, ex, ey);
        tips.push([ex, ey]);
      }
      ctx.stroke();
      ctx.fillStyle = `rgba(${P.tip},${dark ? 0.6 : 0.7})`;
      ctx.beginPath();
      for (const [ex, ey] of tips) {
        ctx.moveTo(ex + 2 / s, ey);
        ctx.arc(ex, ey, 2 / s, 0, TAU);
      }
      ctx.fill();
    }
    ctx.restore();
  }

  function drawReef() {
    const p = clamp01(state.progress) * corals.length;
    for (const c of corals) {
      const grow = clamp01(p - c.rank);
      if (grow <= 0) {
        // a polyp waiting its turn
        ctx.fillStyle = c.color;
        ctx.globalAlpha = 0.6;
        ctx.beginPath();
        ctx.arc(c.x, c.base - 1, 2.2, Math.PI, TAU);
        ctx.fill();
        ctx.globalAlpha = 1;
        continue;
      }
      // later corals grow a little taller: the reef thickens as you near the end
      drawCoral(c, c.size * (0.25 + 0.75 * grow) * (0.8 + 0.3 * clamp01(state.progress)));
    }
  }

  function bubble(b, alpha) {
    ctx.fillStyle = `rgba(${P.bubble},${0.1 * alpha})`;
    ctx.strokeStyle = `rgba(${P.bubble},${0.55 * alpha})`;
    ctx.beginPath();
    ctx.arc(b.dx, b.y, b.r, 0, TAU);
    ctx.fill();
    ctx.stroke();
    if (b.r > 2.5) {
      ctx.fillStyle = `rgba(255,255,255,${0.5 * alpha})`;
      ctx.fillRect(b.dx - b.r * 0.45, b.y - b.r * 0.5, b.r * 0.35, b.r * 0.35);
    }
  }

  function drawBubbles(dt) {
    ctx.lineWidth = 1;
    const fadeTop = h * 0.04;
    const fadeLen = h * 0.24;
    for (let i = 0; i < bubbles.length; i++) {
      const b = bubbles[i];
      b.y -= b.vy * dt;
      b.dx = b.x + Math.sin(t * b.wob + b.phase) * b.amp;
      if (b.y < fadeTop) {
        bubbles[i] = newBubble(RT, false);
        continue;
      }
      bubble(b, clamp01((b.y - fadeTop) / fadeLen) * (dark ? 0.7 : 1));
    }
    for (let i = burst.length - 1; i >= 0; i--) {
      const b = burst[i];
      b.y -= b.vy * dt;
      b.dx = b.x + Math.sin(t * b.wob + b.phase) * b.amp;
      if (b.y < fadeTop) {
        burst.splice(i, 1);
        continue;
      }
      bubble(b, clamp01((b.y - fadeTop) / fadeLen) * clamp01((h - b.y) / 40));
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
      // a quiet moment: a slow stream of extra bubbles rising from the reef
      if (state.moment !== lastMoment) {
        lastMoment = state.moment;
        if (state.moment && !state.still && burst.length === 0) {
          for (let i = 0; i < BURST; i++) {
            const b = newBubble(RT, false);
            b.x = w * (0.3 + RT() * 0.4);
            b.y = h + RT() * 140; // staggered start, so they arrive over a couple of seconds
            b.vy *= 1.3;
            burst.push(b);
          }
        }
      }

      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = water;
      ctx.fillRect(0, 0, w, h);

      drawRays();
      drawCaustics();
      drawSpecks(dt);
      drawSchools(dt);
      drawJellies(dt);
      drawTurtle();
      drawKelp();
      ctx.fillStyle = bedGrad;
      ctx.fill(bedPath);
      drawReef();
      drawBubbles(dt);

      const g = momentGlow(state);
      if (g > 0) {
        const bloom = ctx.createRadialGradient(w * 0.5, 0, 0, w * 0.5, 0, h * 0.85);
        bloom.addColorStop(0, `rgba(${P.bloom},${(dark ? 0.16 : 0.24) * g})`);
        bloom.addColorStop(1, `rgba(${P.bloom},0)`);
        ctx.fillStyle = bloom;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
