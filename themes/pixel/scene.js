// Pixel art — a small parallax landscape drawn at low resolution and scaled up with crisp pixels.
// The path lights up as you read; the flag marks the end of the text.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const DAY = { sky: ["#94c8f0", "#b6dcf5", "#d4ecf8"], far: "#8aa6c8", hill: "#5f9e6e", hill2: "#4b8a5c", ground: "#3e7a4c", path: "#c9a26c", walked: "#f3d9a4", pathEdge: "#b08650", cloud: "#ffffff", tree: "#2f6a45", trunk: "#6b4a2f", flag: "#b13e53" };
const NIGHT = { sky: ["#1a1c2c", "#29304a", "#333c57"], far: "#3b4466", hill: "#2a4a46", hill2: "#22403c", ground: "#1d3633", path: "#7a6246", walked: "#c9a36a", pathEdge: "#6a5238", cloud: "#4a5275", tree: "#173329", trunk: "#3d2c22", flag: "#ffcd75" };

export default function pixel(env) {
  const { ctx, dark, state } = env;
  const P = dark ? NIGHT : DAY;
  let w = env.w;
  let h = env.h;
  let W = 200;
  let H = 120;
  let buf;
  let bctx;
  let far = [];
  let hills = [];
  let trees = [];
  let clouds = [];
  let stars = [];
  let t = 0;

  function layout() {
    W = 200;
    H = Math.max(60, Math.round((200 * h) / Math.max(1, w)));
    buf = new OffscreenCanvas(W, H);
    bctx = buf.getContext("2d");
    const R = rng(7);
    far = Array.from({ length: W * 2 }, (_, x) => Math.round(H * 0.55 + Math.sin(x * 0.045) * 6 + Math.sin(x * 0.13) * 3));
    hills = Array.from({ length: W * 2 }, (_, x) => Math.round(H * 0.7 + Math.sin(x * 0.07 + 1) * 4 + Math.sin(x * 0.021) * 5));
    trees = Array.from({ length: 24 }, () => ({ x: Math.floor(R() * W * 2), s: 3 + Math.floor(R() * 4) }));
    clouds = Array.from({ length: 6 }, () => ({ x: R() * W * 2, y: 4 + Math.floor(R() * H * 0.3), len: 8 + Math.floor(R() * 14) }));
    stars = Array.from({ length: 40 }, () => ({ x: Math.floor(R() * W), y: Math.floor(R() * H * 0.5), ph: R() * 6 }));
  }
  layout();

  function px(x, y, wd, ht, color) {
    bctx.fillStyle = color;
    bctx.fillRect(Math.round(x), Math.round(y), wd, ht);
  }

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
      layout();
    },
    frame(dt) {
      t += dt;
      // sky bands
      const band = Math.ceil(H * 0.6 / 3);
      P.sky.forEach((c, i) => px(0, i * band, W, band, c));
      px(0, band * 3, W, H, P.sky[2]);
      if (dark) {
        for (const s of stars) {
          if (Math.sin(t * 0.6 + s.ph) > -0.2) px(s.x, s.y, 1, 1, "#f4f4f4"); // slow twinkle, several seconds
        }
        px(W - 30, 10, 5, 5, "#f4f4f4"); // moon
      } else {
        px(W - 31, 9, 8, 8, "#ffe9a8"); // sun
        px(W - 32, 11, 10, 4, "#ffe9a8");
        px(W - 29, 7, 4, 12, "#ffe9a8");
      }

      // parallax layers: far ridge, clouds, hills with trees
      const o1 = Math.floor(t * 0.6) % W;
      const o2 = Math.floor(t * 1.5) % W;
      for (const c of clouds) {
        const x = ((c.x - t * 2) % (W + 30) + W + 30) % (W + 30) - 30;
        px(x, c.y, c.len, 2, P.cloud);
        px(x + 2, c.y - 1, c.len - 4, 1, P.cloud);
      }
      for (let x = 0; x < W; x++) px(x, far[x + o1], 1, H, P.far);
      for (let x = 0; x < W; x++) px(x, hills[x + o2], 1, H, P.hill);
      for (const tr of trees) {
        const x = ((tr.x - o2) % (W * 2) + W * 2) % (W * 2);
        if (x >= W) continue;
        const y = hills[(x + o2) % (W * 2)];
        px(x, y - tr.s * 2, 1, tr.s * 2, P.trunk);
        px(x - tr.s + 1, y - tr.s * 2 - 1, tr.s * 2 - 1, tr.s, P.tree);
        px(x - tr.s + 2, y - tr.s * 3 + 1, tr.s * 2 - 3, tr.s - 1, P.tree);
      }

      // ground and the path
      const gy = H - 12;
      px(0, gy, W, 12, P.ground);
      px(0, gy + 4, W, 3, P.path);
      px(0, gy + 7, W, 1, P.pathEdge);

      // the flag at the end of the path
      const fx = W - 10;
      px(fx, gy - 9, 1, 13, P.pathEdge);
      px(fx + 1, gy - 9, 5, 3, P.flag);

      // progress: the stretch of path you've covered is lit, up to how far you've read
      const x = Math.round(Math.min(1, state.progress) * (W - 10));
      if (x > 0) px(0, gy + 4, x, 3, P.walked);

      // a quiet moment: a few slow sparkles rising from the lit end of the path
      if (state.moment && !state.still) {
        const k = (performance.now() - state.moment) / 2600;
        if (k > 0 && k < 1) {
          for (let i = 0; i < 4; i++) px(x + Math.round(Math.cos(i * 1.6 + k * 2) * 5), gy - Math.round(k * 8) - i, 1, 1, "#ffe9a8");
        }
      }

      ctx.clearRect(0, 0, w, h);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(buf, 0, 0, W, H, 0, 0, w, Math.round((H * w) / W));
    },
  };
}
