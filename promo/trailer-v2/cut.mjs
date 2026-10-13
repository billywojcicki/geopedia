// The edit as a function of time: camera, year, time window and map look at
// any moment, from cut.json. Shared by capture.mjs and check tools.

const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
const smooth = (a, b, t) => { const k = clamp((t - a) / (b - a)); return k * k * (3 - 2 * k); };
const easeIn = k => k * k * k;

// Monotone cubic interpolation (Fritsch-Carlson): smooth, and never
// overshoots the keyframes, so the camera can't swing back.
function monotone(xs, ys) {
  const n = xs.length, d = [], m = new Array(n);
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]));
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i], s = a * a + b * b;
    if (s > 9) { const k = 3 / Math.sqrt(s); m[i] = k * a * d[i]; m[i + 1] = k * b * d[i]; }
  }
  return x => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let i = 0;
    while (x > xs[i + 1]) i++;
    const h = xs[i + 1] - xs[i], u = (x - xs[i]) / h;
    const h00 = 2 * u ** 3 - 3 * u ** 2 + 1, h10 = u ** 3 - 2 * u ** 2 + u, h01 = -2 * u ** 3 + 3 * u ** 2, h11 = u ** 3 - u ** 2;
    return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1];
  };
}

const memo = new WeakMap();
function curves(cfg) {
  if (!memo.has(cfg)) {
    const K = cfg.rush.keys, ts = K.map(k => k[0]);
    memo.set(cfg, { lon: monotone(ts, K.map(k => k[1])), lat: monotone(ts, K.map(k => k[2])), zoom: monotone(ts, K.map(k => k[3])) });
  }
  return memo.get(cfg);
}

// Years fly by when history is sparse and slow down as it gets dense: the
// time left until today shrinks exponentially (plus an offset, so the end
// doesn't crawl).
export function yearAt(cfg, t) {
  const r = cfg.rush, span = r.to - r.from + r.offset;
  const u = clamp((t - r.t0) / (r.t1 - r.t0));
  return r.to - (span * Math.exp(-Math.log(span / r.offset) * u) - r.offset);
}
export function yearsPerSecond(cfg, t) {
  const r = cfg.rush, span = r.to - r.from + r.offset, k = Math.log(span / r.offset) / (r.t1 - r.t0);
  return k * (r.to - yearAt(cfg, t) + r.offset);
}

export function stateAt(cfg, t) {
  const { race, dawn, impact, rush, payoff, end } = cfg;
  const c = curves(cfg);
  if (t < dawn.t0) {
    const k = clamp((t - race.t0) / (race.t1 - race.t0));
    return {
      phase: 'race', cam: { center: race.center, zoom: lerp(race.zoom[0], race.zoom[1], k), pitch: 0, bearing: 0, padding: {} },
      year: rush.from, label: rush.from, span: 200, pins: false, borders: false,
      filter: 'brightness(0.3) saturate(0.5)', mapOpacity: 1,
    };
  }
  if (t < impact.t) {
    const k = clamp((t - dawn.t0) / (dawn.t1 - dawn.t0));
    const push = easeIn(clamp((t - dawn.push[0]) / (dawn.push[1] - dawn.push[0])));
    const light = smooth(dawn.light[0], dawn.light[1], t);
    return {
      phase: 'dawn',
      cam: { center: dawn.center, zoom: lerp(dawn.zoom[0], dawn.zoom[1], k) + 0.55 * push, pitch: dawn.pitch - 10 * push, bearing: 0, padding: {} },
      year: rush.from, label: rush.from, span: 200, pins: false, borders: false,
      filter: `brightness(${(0.05 + 0.8 * light).toFixed(3)}) saturate(${(0.45 + 0.55 * light).toFixed(3)})`, mapOpacity: 1,
    };
  }
  const slide = smooth(payoff.slide[0], payoff.slide[1], t) - smooth(payoff.back[0], payoff.back[1], t);
  const padding = { right: Math.round(payoff.padRight * Math.max(0, slide)) };
  if (t < payoff.implode[0]) {
    const cam = { center: [((c.lon(t) + 540) % 360) - 180, c.lat(t)], zoom: c.zoom(t), pitch: 0, bearing: 0, padding };
    if (t < rush.t1) {
      const year = Math.round(yearAt(cfg, t));
      // Each pin stays up for about a third of a second, however fast the years go.
      const span = Math.round(clamp(0.18 * yearsPerSecond(cfg, t), 2, 400));
      return { phase: 'rush', cam, year, label: year, span, pins: true, borders: true, filter: 'saturate(1.08) contrast(1.04)', mapOpacity: 1 };
    }
    // Every era at once.
    return { phase: 'payoff', cam, year: rush.to, label: rush.to, span: rush.to - rush.from, pins: true, borders: false, filter: 'saturate(1.08) contrast(1.04)', mapOpacity: 1 };
  }
  // The world collapses into a point.
  const [a, b] = payoff.implode;
  const k = clamp((t - a) / (b - a));
  const t1 = Math.min(t, end.t);
  const base = c.zoom(a);
  const cam = {
    center: [((c.lon(a) + 6 * k + 540) % 360) - 180, c.lat(a)], zoom: Math.max(-2, base - 4.4 * easeIn(k)),
    pitch: 0, bearing: 0, padding,
  };
  return {
    phase: t1 < end.t ? 'implode' : 'end', cam, year: rush.to, label: rush.to, span: rush.to - rush.from, pins: false, borders: false,
    filter: `brightness(${(1 + 0.9 * k).toFixed(3)}) saturate(1.1)`, mapOpacity: t < end.t ? 1 : 0,
  };
}

// The timeline strip: how much history each stretch of the sweep covers
// (events per year, log scale, 0..1), in 240 steps.
export function histBins(h, cfg, n = 240) {
  const at = y => h.counts[Math.round(y) - h.min] || 0;
  const out = [];
  for (let i = 0; i < n; i++) {
    const ya = yearAt(cfg, cfg.rush.t0 + (cfg.rush.t1 - cfg.rush.t0) * i / n);
    const yb = yearAt(cfg, cfg.rush.t0 + (cfg.rush.t1 - cfg.rush.t0) * (i + 1) / n);
    let sum = 0;
    for (let y = Math.ceil(ya); y <= Math.floor(yb); y++) sum += at(y);
    out.push(Math.log10(1 + sum / Math.max(1, yb - ya)));
  }
  const max = Math.max(...out);
  return out.map(v => Math.round(v / max * 1000) / 1000);
}
