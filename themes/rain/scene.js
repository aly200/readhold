// Rain — pixel art: rain over an empty city that was left a long time ago. Dark windows, broken glass, a
// rusted car, a leaning streetlight, cracks in the road with grass coming through, puddles that ripple.
// As you read, ivy climbs down the walls, small trees take root on the roofs, and glowing mushrooms and buds
// light up the ruins; spores (fireflies at night) drift up, and a gap of light opens in the clouds.
// Nature taking the city back, gently. Drawn at low resolution and scaled up with crisp pixels. Nothing flashes:
// every glow swells and fades over several seconds.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

const DAY = {
  sky: ["#76838f", "#83909b", "#909ca6", "#9da8b1"], cloud: "#6a7782", cloud2: "#8c98a2",
  far: "#717e89", far2: "#6a7782", mid: "#56626d", midEdge: "#616d78", near: "#434d57", nearEdge: "#4f5a64",
  win: "#2e353c", winBroken: "#20262b", winGlass: "#7d8b97", boarded: "#5d5249",
  sign: "#7f6a5a", signFade: "#968273", rust: "#7a4c37", rust2: "#5e3a2b", car: "#5f6a6f", tire: "#22272b",
  walk: "#4d555c", walkEdge: "#5a636a", road: "#3b4249", lane: "#77705d", crack: "#2c3238",
  puddle: "#8796a2", puddleEdge: "#6e7c87", ripple: "#b9c6d0",
  vine: "#4f6c46", vine2: "#5f8051", leaf: "#6f9358", grass: "#5c7c4b", trunk: "#4a3d32",
  pole: "#2f363c", lampOff: "#596169", rain: "#c3d0da", splash: "#d3dee6",
  glow: ["#3fd6c0", "#9b7bea", "#f2b54e", "#62c7ef"], glowA: 0.28, mote: "#f4f1d0", beam: "#fff4d6", moon: "#e9edf2",
};
const NIGHT = {
  sky: ["#10151e", "#131a25", "#17202c", "#1b2533"], cloud: "#0f141c", cloud2: "#1f2938",
  far: "#1a222e", far2: "#171e29", mid: "#141b24", midEdge: "#19212b", near: "#10161d", nearEdge: "#151c24",
  win: "#0b0f14", winBroken: "#07090c", winGlass: "#2a3647", boarded: "#221e1c",
  sign: "#2e2722", signFade: "#3a322b", rust: "#3c2a22", rust2: "#2c1f19", car: "#262d33", tire: "#0b0d10",
  walk: "#1a2028", walkEdge: "#202731", road: "#141920", lane: "#3a382f", crack: "#0e1217",
  puddle: "#2c3a4c", puddleEdge: "#1e2836", ripple: "#5a6d85",
  vine: "#18281e", vine2: "#1d3225", leaf: "#243b2b", grass: "#223728", trunk: "#221c18",
  pole: "#0e1216", lampOff: "#2b3138", rain: "#5f7189", splash: "#71839b",
  glow: ["#6ff7de", "#c39bff", "#ffd27a", "#8fe3ff"], glowA: 0.55, mote: "#d8ff9a", beam: "#9fb6d6", moon: "#dfe6f0",
};

export default function rain(env) {
  const { ctx, dark, state } = env;
  const P = dark ? NIGHT : DAY;
  let w = env.w;
  let h = env.h;
  const W = 320;
  let H = 180;
  let buf, b; // the low-resolution frame
  let city, cctx; // everything that never moves, drawn once per layout
  let gy = 0; // where the buildings stand
  let clouds = [], drops = [], ripples = [], splashes = [], vines = [], roofTrees = [], puddles = [];
  let shrooms = [], motes = [], spots = []; // glowing mushrooms, drifting spores, and places they can grow
  let lamp = null;
  let t = 0;
  let rippleClock = 0;

  const px = (c, x, y, wd, ht, color) => {
    c.fillStyle = color;
    c.fillRect(Math.round(x), Math.round(y), wd, ht);
  };

  function building(c, R, x0, bw, top, body, edge, layer) {
    // the block, column by column: a jagged broken roofline, sometimes a collapsed corner, and a lit edge
    const tops = [];
    const fallen = R() < 0.35 ? 3 + Math.floor(R() * 6) : 0;
    const left = R() < 0.5;
    for (let i = 0; i < bw; i++) {
      let tt = top + (R() < 0.18 ? 1 + Math.floor(R() * 3) : 0);
      if (fallen) {
        const d = left ? fallen - i : i - (bw - 1 - fallen);
        if (d > 0) tt = Math.max(tt, top + d);
      }
      tops.push(tt);
      px(c, x0 + i, tt, 1, gy - tt, i === bw - 1 ? edge : body);
    }
    const topAt = (x) => tops[Math.min(bw - 1, Math.max(0, x - x0))];
    if (layer === "far") {
      if (R() < 0.4) px(c, x0 + Math.floor(bw / 2), top - 4 - Math.floor(R() * 5), 1, 6, body); // an antenna
      return;
    }
    // windows: most dark, some broken, a few still catching the grey light, some boarded up
    const cols = Math.floor((bw - 3) / 4);
    for (let wy = top + 4; wy < gy - 5; wy += 5) {
      for (let i = 0; i < cols; i++) {
        const wx = x0 + 2 + i * 4;
        const r = R();
        if (wy <= Math.max(topAt(wx), topAt(wx + 1)) + 1) continue; // no windows where the wall has fallen
        if (r < 0.12) {
          px(c, wx, wy, 2, 3, P.boarded);
          px(c, wx, wy + 1, 2, 1, P.win);
        } else if (r < 0.32) {
          px(c, wx, wy, 2, 3, P.winBroken);
          px(c, wx + (R() < 0.5 ? 0 : 1), wy + 2, 1, 1, P.winGlass); // a shard left in the frame
        } else if (r < 0.42) {
          px(c, wx, wy, 2, 3, P.winGlass);
          px(c, wx + 1, wy, 1, 1, P.win);
        } else px(c, wx, wy, 2, 3, P.win);
      }
    }
    // a doorway at street level
    if (bw > 14) px(c, x0 + 3 + Math.floor(R() * (bw - 10)), gy - 6, 4, 6, P.winBroken);
    // ivy that was already there when the city emptied, and more that grows as you read
    const strands = 1 + Math.floor(bw / 7);
    for (let i = 0; i < strands; i++) {
      const vx = x0 + 1 + Math.floor(R() * (bw - 2));
      const max = Math.min(gy - top - 2, 6 + Math.floor(R() * (gy - top) * 0.8));
      vines.push({ x: vx, y: topAt(vx), max, base: 0.12 + R() * 0.25, seed: Math.floor(R() * 1e6), layer });
    }
    const rx = x0 + 2 + Math.floor(R() * (bw - 6));
    if (bw > 10) roofTrees.push({ x: rx, y: topAt(rx), at: 0.2 + R() * 0.75, s: 2 + Math.floor(R() * 3) });
    if (layer === "near") {
      for (let i = 0; i < 2; i++) {
        const sx = x0 + 1 + Math.floor(R() * (bw - 2));
        spots.push({ x: sx, y: topAt(sx) });
      }
      for (let i = 0; i < 3; i++) spots.push({ x: x0 + Math.floor(R() * bw), y: gy });
    }
  }

  function layout() {
    H = Math.max(110, Math.round((W * h) / Math.max(1, w)));
    gy = H - 26;
    buf = new OffscreenCanvas(W, H);
    b = buf.getContext("2d");
    city = new OffscreenCanvas(W, H);
    cctx = city.getContext("2d");
    vines = [];
    roofTrees = [];
    spots = [];
    const R = rng(23);

    // far towers: tall, hazy, with a crane that was never taken down
    for (let x = -4; x < W; ) {
      const bw = 10 + Math.floor(R() * 18);
      building(cctx, R, x, bw, Math.round(H * 0.18 + R() * H * 0.3), R() < 0.5 ? P.far : P.far2, P.far2, "far");
      x += bw + Math.floor(R() * 4);
    }
    const cx = Math.round(W * 0.68);
    const ctop = Math.round(H * 0.1);
    px(cctx, cx, ctop, 2, gy - ctop, P.far2);
    px(cctx, cx - 22, ctop, 46, 2, P.far2);
    px(cctx, cx + 20, ctop + 2, 1, 10, P.far2); // the hook's cable, still hanging
    for (let i = 0; i < 46; i += 4) px(cctx, cx - 22 + i, ctop - 1, 1, 1, P.far2);

    // middle row
    for (let x = -6; x < W; ) {
      const bw = 16 + Math.floor(R() * 22);
      building(cctx, R, x, bw, Math.round(H * 0.38 + R() * H * 0.18), P.mid, P.midEdge, "mid");
      x += bw + 1 + Math.floor(R() * 3);
    }
    // a faded billboard, peeling
    const bx = Math.round(W * 0.2);
    const by = Math.round(H * 0.42);
    px(cctx, bx, by + 3, 26, 7, P.sign);
    px(cctx, bx, by, 18, 3, P.sign); // its top right corner has torn away
    for (let i = 0; i < 40; i++) {
      const fx = Math.floor(R() * 26);
      const fy = Math.floor(R() * 10);
      if (fy >= 3 || fx < 18) px(cctx, bx + fx, by + fy, 1, 1, P.signFade);
    }
    px(cctx, bx + 3, by + 10, 1, 6, P.pole);
    px(cctx, bx + 22, by + 10, 1, 6, P.pole);

    // near row, lower and darker, with gaps
    for (let x = -3; x < W; ) {
      const bw = 20 + Math.floor(R() * 26);
      if (R() < 0.8) building(cctx, R, x, bw, Math.round(H * 0.56 + R() * H * 0.12), P.near, P.nearEdge, "near");
      x += bw + 6 + Math.floor(R() * 14);
    }

    // the street: sidewalk, road with faded lane marks, cracks with grass, puddles
    px(cctx, 0, gy, W, 3, P.walk);
    px(cctx, 0, gy, W, 1, P.walkEdge);
    px(cctx, 0, gy + 3, W, H - gy - 3, P.road);
    for (let x = 4; x < W; x += 14) if (R() < 0.75) px(cctx, x, gy + 13, 6, 1, P.lane);
    for (let i = 0; i < 9; i++) {
      let x = Math.floor(R() * W);
      let y = gy + 4 + Math.floor(R() * (H - gy - 6));
      for (let k = 0; k < 8 + Math.floor(R() * 10); k++) {
        if (k === 3) spots.push({ x, y });
        px(cctx, x, y, 1, 1, P.crack);
        if (R() < 0.35) px(cctx, x, y - 1, 1, 1, P.grass);
        x += 1;
        y += R() < 0.5 ? 0 : R() < 0.5 ? 1 : -1;
      }
    }
    for (let x = 0; x < W; x++) if (R() < 0.22) px(cctx, x, gy - 1, 1, 1 + Math.floor(R() * 2), P.grass); // grass along the walls
    puddles = [];
    for (let i = 0; i < 5; i++) {
      const pw = 10 + Math.floor(R() * 18);
      const p = { x: Math.floor(R() * (W - pw)), y: gy + 6 + Math.floor(R() * (H - gy - 10)), w: pw };
      puddles.push(p);
      px(cctx, p.x + 2, p.y, p.w - 4, 1, P.puddleEdge);
      px(cctx, p.x, p.y + 1, p.w, 2, P.puddle);
      px(cctx, p.x + 2, p.y + 3, p.w - 4, 1, P.puddleEdge);
    }

    // a rusted car with flat tyres, left where it stopped
    const carX = Math.round(W * 0.58);
    const carY = gy + 7;
    px(cctx, carX, carY, 26, 5, P.car);
    px(cctx, carX + 6, carY - 3, 13, 3, P.car);
    px(cctx, carX + 7, carY - 2, 5, 2, P.winBroken);
    px(cctx, carX + 13, carY - 2, 5, 2, P.win);
    for (let i = 0; i < 12; i++) px(cctx, carX + Math.floor(R() * 26), carY + Math.floor(R() * 5), 1 + Math.floor(R() * 2), 1, R() < 0.5 ? P.rust : P.rust2);
    px(cctx, carX + 3, carY + 5, 5, 1, P.tire);
    px(cctx, carX + 18, carY + 5, 5, 1, P.tire);
    px(cctx, carX + 24, carY - 1, 2, 1, P.grass);
    spots.push({ x: carX + 9, y: carY - 3 }, { x: carX + 15, y: carY - 3 }, { x: carX + 2, y: carY }); // on the old car

    // a leaning streetlight (its lamp long dead) and a bare tree in a cracked planter
    const lx = Math.round(W * 0.34);
    for (let i = 0; i < 22; i++) px(cctx, lx + Math.floor(i / 6), gy - i, 1, 1, P.pole);
    px(cctx, lx + 3, gy - 22, 6, 1, P.pole);
    px(cctx, lx + 7, gy - 21, 3, 2, P.lampOff);
    lamp = { x: lx + 8, y: gy - 19 };
    const tx = Math.round(W * 0.84);
    px(cctx, tx - 3, gy - 1, 7, 2, P.walkEdge);
    px(cctx, tx, gy - 14, 1, 14, P.trunk);
    for (const [dx, dy, len] of [[-1, -10, 4], [1, -8, 5], [-1, -5, 3], [1, -13, 3]]) {
      for (let i = 0; i < len; i++) px(cctx, tx + dx * (i + 1), gy + dy - Math.floor(i / 2), 1, 1, P.trunk);
    }

    clouds = Array.from({ length: 7 }, () => ({ x: R() * (W + 80) - 40, y: Math.floor(R() * H * 0.22), len: 26 + Math.floor(R() * 40), v: 1.2 + R() * 1.6 }));
    drops = Array.from({ length: Math.round((W * H) / 130) }, () => ({ x: R() * (W + 40), y: R() * H, v: 120 + R() * 70, len: 2 + Math.floor(R() * 3) }));
    ripples = [];
    splashes = [];
    // glowing mushrooms: a few already lit when you start (hope was always there), more as you read
    const G = rng(57);
    shrooms = spots
      .filter(() => G() < 0.7)
      .map((sp, i) => ({ ...sp, at: i % 5 === 0 ? 0 : 0.05 + G() * 0.9, c: P.glow[Math.floor(G() * P.glow.length)], big: G() < 0.3, ph: G() * 6.28, sp: 0.35 + G() * 0.35 }));
    motes = Array.from({ length: 34 }, () => ({ x: G() * W, y: gy - G() * (gy * 0.7), vx: (G() - 0.5) * 3, vy: -(1.5 + G() * 3), ph: G() * 6.28, k: G() }));
  }
  layout();
  const R = rng(99);

  let buds = [];
  // a round pixel halo: rows that widen then narrow
  function blob(x, y, rad, color, alpha) {
    b.globalAlpha = alpha;
    b.fillStyle = color;
    for (let dy = -rad; dy <= rad; dy++) {
      const half = Math.round(Math.sqrt(rad * rad - dy * dy));
      b.fillRect(Math.round(x) - half, Math.round(y) + dy, half * 2 + 1, 1);
    }
  }
  function drawVines(p) {
    buds = [];
    for (const v of vines) {
      const len = Math.round(v.max * clamp01(v.base + p * 0.95));
      if (len < 1) continue;
      const r = rng(v.seed);
      let x = v.x;
      for (let i = 0; i < len; i++) {
        px(b, x, v.y + i, 1, 1, i % 4 === 0 ? P.vine2 : P.vine);
        if (r() < 0.3) px(b, x + (r() < 0.5 ? -1 : 1), v.y + i, 1, 1, P.leaf);
        if (r() < 0.035 && p > 0.15) buds.push({ x: x + (r() < 0.5 ? -1 : 1), y: v.y + i, c: P.glow[Math.floor(r() * P.glow.length)], ph: r() * 6.28 });
        if (r() < 0.08) x += r() < 0.5 ? -1 : 1;
      }
    }
    for (const tr of roofTrees) {
      if (p < tr.at) continue;
      const g = clamp01((p - tr.at) / 0.15);
      const s = Math.max(1, Math.round(tr.s * g));
      px(b, tr.x, tr.y - s, 1, s, P.trunk);
      px(b, tr.x - s, tr.y - s - s, s * 2 + 1, s, P.leaf);
      px(b, tr.x - s + 1, tr.y - s * 3 + 1, Math.max(1, s * 2 - 1), s - 1 || 1, P.vine2);
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

      // a low, heavy sky in bands, and slow clouds
      const band = Math.ceil(gy / P.sky.length);
      P.sky.forEach((c, i) => px(b, 0, i * band, W, band + 1, c));
      for (const c of clouds) {
        c.x += c.v * dt;
        if (c.x > W + 10) c.x = -c.len - 10;
        px(b, c.x, c.y, c.len, 3, P.cloud);
        px(b, c.x + 4, c.y - 2, c.len - 10, 2, P.cloud);
        px(b, c.x + 2, c.y + 3, c.len - 4, 1, P.cloud2);
      }

      // the moment glow: the clouds thin for a few seconds, slowly
      if (state.moment && !state.still) {
        const k = (performance.now() - state.moment) / 2600;
        if (k > 0 && k < 1) {
          b.globalAlpha = 0.18 * Math.sin(Math.PI * k);
          px(b, 0, 0, W, gy, dark ? "#6f86a8" : "#f2efe2");
          b.globalAlpha = 1;
        }
      }

      // hope: as you read, a gap opens in the clouds; sunbeams by day, the moon by night
      const gap = clamp01((p - 0.15) / 0.85);
      if (gap > 0) {
        const gx = Math.round(W * 0.78);
        if (dark) {
          b.globalAlpha = 0.9 * gap;
          px(b, gx - 2, 9, 5, 7, P.moon);
          px(b, gx - 3, 10, 7, 5, P.moon);
          b.globalAlpha = 0.12 * gap;
          px(b, gx - 7, 6, 15, 13, P.moon);
        }
        b.globalAlpha = (dark ? 0.06 : 0.14) * gap;
        for (let i = 0; i < 4; i++) {
          for (let y = 0; y < gy; y += 2) px(b, gx - 8 - i * 14 - y * 0.55, y, 6 + i * 2, 2, P.beam);
        }
        b.globalAlpha = 1;
      }

      b.drawImage(city, 0, 0);
      drawVines(p);

      // glowing mushrooms and buds, each swelling and fading slowly on its own rhythm
      b.globalCompositeOperation = dark ? "lighter" : "source-over";
      for (const m of shrooms) {
        const k = clamp01((p - m.at) / 0.08);
        if (k <= 0) continue;
        const pulse = 0.65 + 0.35 * Math.sin(t * m.sp + m.ph);
        blob(m.x, m.y - 3, m.big ? 6 : 5, m.c, P.glowA * 0.3 * k * pulse);
        blob(m.x, m.y - 3, 2, m.c, P.glowA * 0.55 * k * pulse);
        b.globalAlpha = 1;
      }
      b.globalCompositeOperation = "source-over";
      for (const m of shrooms) {
        const k = clamp01((p - m.at) / 0.08);
        if (k <= 0) continue;
        b.globalAlpha = 0.6 + 0.4 * k;
        px(b, m.x, m.y - 2, 1, 2, dark ? "#4b5a55" : "#d7d2c4"); // stem
        if (m.big) {
          px(b, m.x - 2, m.y - 3, 5, 1, m.c);
          px(b, m.x - 1, m.y - 4, 3, 1, m.c);
          px(b, m.x + 2, m.y - 1, 1, 1, m.c); // a little one beside it
        } else {
          px(b, m.x - 1, m.y - 3, 3, 1, m.c);
          px(b, m.x, m.y - 4, 1, 1, m.c);
        }
        b.globalAlpha = 1;
      }
      b.globalCompositeOperation = dark ? "lighter" : "source-over";
      for (const bd of buds) {
        blob(bd.x, bd.y, 2, bd.c, P.glowA * (0.4 + 0.25 * Math.sin(t * 0.5 + bd.ph)));
        b.globalAlpha = 1;
        px(b, bd.x, bd.y, 1, 1, bd.c);
      }
      b.globalCompositeOperation = "source-over";

      // spores drifting up from the glow (fireflies at night): more of them the further you read
      const showMotes = Math.round(motes.length * (0.25 + 0.75 * p));
      for (let i = 0; i < showMotes; i++) {
        const m = motes[i];
        m.x += (m.vx + Math.sin(t * 0.7 + m.ph) * 2) * dt;
        m.y += m.vy * dt;
        if (m.y < gy * 0.25) {
          m.y = gy - 2 - R() * 10;
          m.x = R() * W;
        }
        if (m.x < 0) m.x += W;
        if (m.x > W) m.x -= W;
        b.globalAlpha = (dark ? 0.75 : 0.5) * (0.4 + 0.6 * Math.max(0, Math.sin(t * 0.8 + m.ph)));
        px(b, m.x, m.y, 1, 1, P.mote);
        b.globalAlpha = 1;
      }

      // at night the old streetlight hums back to a faint glow now and then (a slow swell, never a flicker)
      if (dark && lamp) {
        const glow = Math.max(0, Math.sin(t * 0.25)) * 0.5;
        if (glow > 0.02) {
          b.globalAlpha = glow;
          px(b, lamp.x - 1, lamp.y, 3, 1, "#d9c08a");
          b.globalAlpha = glow * 0.25;
          px(b, lamp.x - 4, lamp.y + 1, 9, 6, "#d9c08a");
          px(b, lamp.x - 6, lamp.y + 7, 13, gy - lamp.y - 7, "#d9c08a");
          b.globalAlpha = 1;
        }
      }

      // ripples in the puddles
      rippleClock += dt;
      while (rippleClock > 0.18) {
        rippleClock -= 0.18;
        const pd = puddles[Math.floor(R() * puddles.length)];
        if (pd) ripples.push({ x: pd.x + 2 + Math.floor(R() * (pd.w - 4)), y: pd.y + 1, age: 0 });
      }
      ripples = ripples.filter((r) => (r.age += dt) < 0.9);
      for (const r of ripples) {
        const rad = 1 + Math.floor(r.age * 4);
        b.globalAlpha = 0.8 * (1 - r.age / 0.9);
        px(b, r.x - rad, r.y + 1, 1, 1, P.ripple);
        px(b, r.x + rad, r.y + 1, 1, 1, P.ripple);
        px(b, r.x - rad + 1, r.y, Math.max(1, rad * 2 - 1), 1, P.ripple);
        b.globalAlpha = 1;
      }

      // rain, slanting a little in the wind, with tiny splashes on the street
      b.fillStyle = P.rain;
      b.globalAlpha = dark ? 0.5 : 0.38;
      for (const d of drops) {
        d.y += d.v * dt;
        d.x -= d.v * dt * 0.18;
        if (d.y > H) {
          if (d.x > 0 && d.x < W && R() < 0.25) splashes.push({ x: Math.round(d.x), y: gy + 3 + Math.floor(R() * (H - gy - 4)), age: 0 });
          d.y = -d.len - R() * 20;
          d.x = R() * (W + 40);
        }
        if (d.x < -2) d.x += W + 40;
        for (let i = 0; i < d.len; i++) b.fillRect(Math.round(d.x + i * 0.18), Math.round(d.y - i), 1, 1);
      }
      b.globalAlpha = 1;
      splashes = splashes.filter((s) => (s.age += dt) < 0.2);
      for (const s of splashes) {
        px(b, s.x - 1, s.y - 1, 1, 1, P.splash);
        px(b, s.x + 1, s.y - 1, 1, 1, P.splash);
      }

      ctx.clearRect(0, 0, w, h);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(buf, 0, 0, W, H, 0, 0, w, Math.round((H * w) / W));
    },
  };
}
