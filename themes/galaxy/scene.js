// Galaxy — a spiral galaxy seen at a tilt, turning very slowly: a glowing core, star-filled arms with pink
// star-forming clouds and dark dust lanes, colourful nebulae drifting at the edges, distant galaxies, and
// bright stars with soft spikes. The galaxy brightens as you read, and each card you review today adds a
// star to your constellation. Everything twinkles over several seconds; nothing flashes.
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
const TAU = Math.PI * 2;
const MAX_STARS = 60;
const gauss = (R) => (R() + R() + R() - 1.5) / 1.5;

const DARK = {
  top: "#060414", bottom: "#120c2a", star: "235,230,255",
  core: ["255,240,215", "255,205,160", "190,150,255"], armIn: [215, 200, 255], armOut: [130, 175, 255],
  pink: "255,110,190", dust: "8,5,20", nebulae: ["150,70,230", "230,70,160", "40,150,220", "60,200,180"],
  far: "200,190,255", spike: "220,225,255",
};
const LIGHT = {
  top: "#cdbff0", bottom: "#ece6fb", star: "70,50,140",
  core: ["255,252,240", "255,228,190", "160,120,235"], armIn: [96, 64, 180], armOut: [70, 96, 200],
  pink: "210,70,160", dust: "236,230,251", nebulae: ["170,130,240", "240,140,200", "120,170,245", "120,210,200"],
  far: "100,80,180", spike: "90,70,170",
};

export default function galaxy(env) {
  const { ctx, dark, state } = env;
  const P = dark ? DARK : LIGHT;
  let w = env.w;
  let h = env.h;
  let sky, gal, S;
  let stars = [], bright = [], distant = [], constellation = [];
  let t = 0;
  let seen = -1;
  const bornAt = new Map();

  /** Draw the galaxy face-on into its own canvas once; each frame it is turned and tilted. */
  function makeGalaxy() {
    S = Math.round(Math.min(1900, Math.max(w, h) * 1.1));
    gal = new OffscreenCanvas(S, S);
    const g = gal.getContext("2d");
    const R0 = S / 2;
    const R = rng(5);
    g.globalCompositeOperation = dark ? "lighter" : "source-over";

    const dot = (x, y, s, rgb, a) => {
      g.fillStyle = `rgba(${rgb},${a})`;
      g.fillRect(x, y, s, s);
    };
    const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k)).join(",");
    const ARMS = 2;
    // a soft glow along each arm, so the spiral reads as light and not only as dots
    for (let i = 0; i < 900; i++) {
      const arm = Math.floor(R() * ARMS);
      const rn = 0.08 + 0.86 * Math.pow(R(), 0.9);
      const th = arm * Math.PI + rn * 7.2 + gauss(R) * (0.35 * (1 - rn) + 0.24);
      const rr = rn * R0;
      const x = R0 + Math.cos(th) * rr;
      const y = R0 + Math.sin(th) * rr;
      const pr = (14 + R() * 26) * (1.2 - rn * 0.5);
      const col = mix(P.armIn, P.armOut, Math.min(1, rn / 0.8));
      const pg = g.createRadialGradient(x, y, 0, x, y, pr);
      pg.addColorStop(0, `rgba(${col},${dark ? 0.07 : 0.08})`);
      pg.addColorStop(1, `rgba(${col},0)`);
      g.fillStyle = pg;
      g.fillRect(x - pr, y - pr, pr * 2, pr * 2);
    }
    const n = Math.round(S * 9);
    for (let i = 0; i < n; i++) {
      const inArm = R() < 0.72;
      const rn = inArm ? 0.06 + 0.94 * Math.pow(R(), 0.85) : Math.pow(R(), 1.6);
      let th;
      if (inArm) {
        const arm = Math.floor(R() * ARMS);
        th = arm * Math.PI + rn * 7.2 + gauss(R) * (0.55 * (1 - rn) + 0.3);
      } else th = R() * TAU;
      const rr = rn * R0 * (0.92 + R() * 0.08);
      const x = R0 + Math.cos(th) * rr;
      const y = R0 + Math.sin(th) * rr;
      const size = R() < 0.06 ? 1.8 : R() < 0.4 ? 1.2 : 0.8;
      const a = (inArm ? 0.8 : 0.35) * (1 - rn * 0.5) * (dark ? 1 : 0.85);
      const col = rn < 0.18 ? P.core[1] : mix(P.armIn, P.armOut, Math.min(1, (rn - 0.18) / 0.7));
      dot(x, y, size, col, a);
      // pink star-forming clouds strung along the arms
      if (inArm && rn > 0.25 && R() < 0.01) {
        const cr = 3 + R() * 6;
        const cg = g.createRadialGradient(x, y, 0, x, y, cr);
        cg.addColorStop(0, `rgba(${P.pink},${dark ? 0.32 : 0.28})`);
        cg.addColorStop(1, `rgba(${P.pink},0)`);
        g.fillStyle = cg;
        g.fillRect(x - cr, y - cr, cr * 2, cr * 2);
      }
    }
    // dark dust lanes just inside each arm (dark mode), soft light lanes (light mode)
    g.globalCompositeOperation = "source-over";
    for (let i = 0; i < S * 2.2; i++) {
      const arm = Math.floor(R() * ARMS);
      const rn = 0.12 + 0.8 * Math.pow(R(), 0.9);
      const th = arm * Math.PI + rn * 7.2 - 0.32 + gauss(R) * 0.08;
      const rr = rn * R0;
      const s = 2 + R() * 4;
      dot(R0 + Math.cos(th) * rr, R0 + Math.sin(th) * rr, s, P.dust, dark ? 0.16 : 0.22);
    }
    // the core
    g.globalCompositeOperation = dark ? "lighter" : "source-over";
    const core = g.createRadialGradient(R0, R0, 0, R0, R0, R0 * 0.42);
    core.addColorStop(0, `rgba(${P.core[0]},0.95)`);
    core.addColorStop(0.12, `rgba(${P.core[1]},0.6)`);
    core.addColorStop(0.45, `rgba(${P.core[2]},${dark ? 0.16 : 0.2})`);
    core.addColorStop(1, `rgba(${P.core[2]},0)`);
    g.fillStyle = core;
    g.fillRect(0, 0, S, S);
  }

  function layout() {
    const R = rng(17);
    sky = ctx.createLinearGradient(0, 0, w * 0.3, h);
    sky.addColorStop(0, P.top);
    sky.addColorStop(1, P.bottom);
    stars = Array.from({ length: Math.round((w * h) / 4200) }, () => ({
      x: R() * w, y: R() * h, r: 0.4 + R() * 1.1, base: 0.25 + R() * 0.45,
      speed: 0.5 + R() * 0.9, // radians per second: one twinkle takes 4–12 seconds
      phase: R() * TAU,
    }));
    bright = Array.from({ length: 7 }, () => ({ x: R() * w, y: R() * h, len: 5 + R() * 8, phase: R() * TAU }));
    distant = Array.from({ length: 5 }, () => ({ x: R() * w, y: R() * h, r: 5 + R() * 9, tilt: R() * Math.PI, flat: 0.3 + R() * 0.5 }));
    const C = rng(29);
    let x = w * 0.12;
    let y = h * 0.22;
    constellation = Array.from({ length: MAX_STARS }, () => {
      x += 30 + C() * 60;
      y += (C() - 0.5) * 70;
      if (x > w * 0.9) {
        x = w * (0.1 + C() * 0.2);
        y += 90;
      }
      y = Math.max(h * 0.08, Math.min(h * 0.8, y));
      return { x, y };
    });
    makeGalaxy();
  }
  layout();

  return {
    resize(nw, nh) {
      w = nw;
      h = nh;
      layout();
    },
    frame(dt) {
      t += dt;
      const p = Math.min(1, state.progress);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      // nebulae drifting at the edges
      ctx.globalCompositeOperation = dark ? "lighter" : "source-over";
      const spots = [[0.08, 0.2], [0.92, 0.78], [0.85, 0.12], [0.12, 0.85]];
      spots.forEach(([sx, sy], i) => {
        const cx = w * sx + Math.sin(t * 0.03 + i * 2) * w * 0.04;
        const cy = h * sy + Math.cos(t * 0.025 + i) * h * 0.04;
        const r = Math.max(w, h) * (0.22 + 0.06 * (i % 2));
        const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        grad.addColorStop(0, `rgba(${P.nebulae[i]},${dark ? 0.14 : 0.2})`);
        grad.addColorStop(0.5, `rgba(${P.nebulae[i]},${dark ? 0.05 : 0.08})`);
        grad.addColorStop(1, `rgba(${P.nebulae[i]},0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      });

      // faint background stars and distant galaxies
      for (const s of stars) {
        const a = s.base + 0.2 * Math.sin(t * s.speed + s.phase);
        ctx.fillStyle = `rgba(${P.star},${Math.max(0.05, a)})`;
        ctx.fillRect(s.x, s.y, s.r * 1.6, s.r * 1.6);
      }
      for (const d of distant) {
        ctx.save();
        ctx.translate(d.x, d.y);
        ctx.rotate(d.tilt);
        ctx.scale(1, d.flat);
        const dg = ctx.createRadialGradient(0, 0, 0, 0, 0, d.r);
        dg.addColorStop(0, `rgba(${P.far},0.5)`);
        dg.addColorStop(1, `rgba(${P.far},0)`);
        ctx.fillStyle = dg;
        ctx.fillRect(-d.r, -d.r, d.r * 2, d.r * 2);
        ctx.restore();
      }

      // the galaxy: tilted, turning about once every half hour, brighter the further you read
      ctx.save();
      ctx.translate(w * 0.5, h * 0.5);
      ctx.rotate(-0.42);
      ctx.scale(1, 0.4);
      ctx.rotate(t * 0.0035);
      ctx.globalAlpha = 0.72 + 0.28 * p;
      ctx.drawImage(gal, -S / 2, -S / 2);
      ctx.restore();
      ctx.globalAlpha = 1;

      // bright stars with soft four-point spikes
      for (const b of bright) {
        const a = 0.55 + 0.3 * Math.sin(t * 0.45 + b.phase);
        ctx.strokeStyle = `rgba(${P.spike},${a * 0.6})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(b.x - b.len, b.y);
        ctx.lineTo(b.x + b.len, b.y);
        ctx.moveTo(b.x, b.y - b.len);
        ctx.lineTo(b.x, b.y + b.len);
        ctx.stroke();
        const bg = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, 5);
        bg.addColorStop(0, `rgba(${P.spike},${a})`);
        bg.addColorStop(1, `rgba(${P.spike},0)`);
        ctx.fillStyle = bg;
        ctx.fillRect(b.x - 5, b.y - 5, 10, 10);
      }
      ctx.globalCompositeOperation = "source-over";

      // your constellation: one star per card reviewed today
      const n = Math.min(MAX_STARS, state.reviewed);
      if (seen < 0) seen = n; // stars you already had appear without animation
      if (n > seen) for (let i = seen; i < n; i++) bornAt.set(i, t);
      seen = n;
      if (n > 1) {
        ctx.strokeStyle = `rgba(${P.star},0.3)`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(constellation[0].x, constellation[0].y);
        for (let i = 1; i < n; i++) ctx.lineTo(constellation[i].x, constellation[i].y);
        ctx.stroke();
      }
      for (let i = 0; i < n; i++) {
        const c = constellation[i];
        const k = state.still || !bornAt.has(i) ? 1 : Math.min(1, (t - bornAt.get(i)) / 1.5);
        const halo = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, 12);
        halo.addColorStop(0, `rgba(${P.star},${0.5 * k})`);
        halo.addColorStop(1, `rgba(${P.star},0)`);
        ctx.fillStyle = halo;
        ctx.fillRect(c.x - 12, c.y - 12, 24, 24);
        ctx.fillStyle = `rgba(${P.star},${0.95 * k})`;
        ctx.beginPath();
        ctx.arc(c.x, c.y, 2.2, 0, TAU);
        ctx.fill();
      }

      const g = momentGlow(state);
      if (g > 0) {
        const grad = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.6);
        grad.addColorStop(0, `rgba(${P.nebulae[0]},${0.18 * g})`);
        grad.addColorStop(1, `rgba(${P.nebulae[0]},0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }
    },
  };
}
