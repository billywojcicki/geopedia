// Outer space behind the globe: stars, the Milky Way, a few nebulae and the
// odd shooting star. The sky is a sphere at infinity around a camera that
// orbits the Earth, so turning the globe swings the stars the other way, as
// they would from a spacecraft.
//
// Cheap by design: two canvases behind the map. The sky is redrawn only when
// the camera moves; shooting stars and a little twinkling run on their own
// small canvas. Everything stops while the globe fills the screen, in the
// background tab, and (shooting stars, twinkling) with reduced motion.

const TAU = Math.PI * 2;
const RAD = Math.PI / 180;

// Seeded, so the sky is the same on every visit.
function rng(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const dir = (lng, lat) => [Math.cos(lat) * Math.cos(lng), Math.cos(lat) * Math.sin(lng), Math.sin(lat)];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = a => { const l = Math.hypot(...a); return [a[0] / l, a[1] / l, a[2] / l]; };
const add = (a, b, k = 1) => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];

// Star colours, blue-white to warm.
const TINTS = [[200, 215, 255], [235, 240, 255], [255, 250, 240], [255, 232, 200], [255, 210, 170]];
const ALPHAS = 8;

// A soft round glow, drawn once and stamped wherever needed.
function sprite(rgb, size = 64, core = 0) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  const [r, gg, b] = rgb;
  if (core) grad.addColorStop(0, `rgba(255,255,255,${core})`);
  grad.addColorStop(core ? 0.08 : 0, `rgba(${r},${gg},${b},1)`);
  grad.addColorStop(0.35, `rgba(${r},${gg},${b},0.35)`);
  grad.addColorStop(1, `rgba(${r},${gg},${b},0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  return c;
}

export class Space {
  constructor(map, { home = [-35, 30] } = {}) {
    this.map = map;
    const container = map.getContainer();
    this.sky = this.canvas('space-sky');
    this.fx = this.canvas('space-fx');
    container.prepend(this.sky, this.fx);
    container.classList.add('space');
    document.documentElement.classList.add('space');
    this.small = matchMedia('(max-width: 860px)').matches;
    this.still = matchMedia('(prefers-reduced-motion: reduce)');
    this.meteors = [];
    this.dirty = [];
    this.queued = false;
    this.active = false;
    this.ready = false;

    const redraw = () => this.schedule();
    map.on('move', redraw);
    map.on('resize', () => { if (this.ready) { this.resize(); this.schedule(); } });
    map.on('projectiontransition', redraw);
    document.addEventListener('visibilitychange', () => this.animate());
    this.still.addEventListener?.('change', () => this.animate());
    // Building the sky takes tens of ms on a phone: it waits until the first
    // view is up, so it never holds up the first pins. The background is
    // already dark meanwhile (the classes above).
    const start = () => {
      this.build(home);
      this.ready = true;
      this.resize();
      this.schedule();
    };
    if (window.requestIdleCallback) requestIdleCallback(start, { timeout: 1000 });
    else setTimeout(start, 300);
  }

  canvas(cls) {
    const c = document.createElement('canvas');
    c.className = cls;
    c.setAttribute('aria-hidden', 'true');
    return c;
  }

  // The sky: stars scattered over the sphere, more of them crowded into the
  // band of the Milky Way, its glowing clouds, and a few nebulae.
  build(home) {
    const rand = rng(1776);
    const gauss = () => { let s = 0; for (let i = 0; i < 4; i++) s += rand(); return (s - 2) * 1.2; };
    const randomDir = () => { const z = rand() * 2 - 1, a = rand() * TAU, r = Math.sqrt(1 - z * z); return [r * Math.cos(a), r * Math.sin(a), z]; };

    // The galactic plane, placed against the globe as first seen: its bright
    // core just right of the Earth, the band sweeping up and down past it.
    const f0 = dir((home[0] + 180) * RAD, -home[1] * RAD);
    const r0 = norm(cross(f0, [0, 0, 1]));
    const u0 = cross(r0, f0);
    const C = norm(add(add(f0, r0, Math.tan(30 * RAD)), u0, Math.tan(8 * RAD)));
    const T = norm(cross(cross(C, add(u0, r0, -0.6)), C)); // the band's heading at the core
    const n = cross(C, T);
    const band = (t, spread) => norm(add(add(C.map(v => v * Math.cos(t)), T, Math.sin(t)), n, spread));
    const fromCore = t => ((t + Math.PI) % TAU + TAU) % TAU - Math.PI; // the core is at t = 0

    const scale = this.small ? 0.55 : 1;
    const stars = [];
    const push = (d, size, bright, tint) => stars.push({ d, size, a: Math.min(ALPHAS - 1, Math.floor(bright * ALPHAS)), tint });
    for (let i = 0; i < 2600 * scale; i++) {
      const b = rand() ** 2.5;
      push(randomDir(), b > 0.55 ? 2 : b > 0.2 ? 1.5 : 1, 0.35 + b * 0.65, Math.floor(rand() * TINTS.length));
    }
    for (let i = 0; i < 7000 * scale; i++) {
      const t = rand() * TAU;
      const near = Math.exp(-1.5 * fromCore(t) ** 2); // denser toward the core
      push(band(t, gauss() * (0.045 + 0.06 * near)), rand() < 0.05 ? 1.5 : 1, 0.2 + rand() * 0.45 + near * 0.25, rand() < 0.5 ? 1 : 2 + Math.floor(rand() * 2));
    }
    // Draw in buckets of one colour and brightness: far fewer state changes.
    stars.sort((p, q) => p.tint - q.tint || p.a - q.a);
    // Packed into flat arrays for the loop that runs on every camera move.
    this.starDir = new Float64Array(stars.length * 3);
    this.starSize = new Float64Array(stars.length);
    this.starStyle = new Uint8Array(stars.length); // index into this.styles
    stars.forEach((s, i) => {
      this.starDir.set(s.d, i * 3);
      this.starSize[i] = s.size;
      this.starStyle[i] = s.tint * ALPHAS + s.a;
    });
    this.styles = TINTS.flatMap(([r, g, b]) => Array.from({ length: ALPHAS }, (_, a) => `rgba(${r},${g},${b},${((a + 1) / ALPHAS).toFixed(2)})`));

    // The Milky Way's glow: overlapping soft clouds along the band.
    const glows = [];
    const milk = sprite([175, 185, 235]), dust = sprite([245, 215, 190]), warm = sprite([255, 225, 190]);
    for (let i = 0; i < 340; i++) {
      const t = rand() * TAU;
      const near = Math.exp(-2 * fromCore(t) ** 2);
      glows.push({ d: band(t, gauss() * 0.03), r: 0.05 + rand() * 0.07 + near * 0.06, a: 0.06 + near * 0.08, img: rand() < near * 0.8 ? dust : milk });
    }
    for (let i = 0; i < 24; i++) glows.push({ d: band(gauss() * 0.22, gauss() * 0.015), r: 0.03 + rand() * 0.05, a: 0.09, img: warm });
    // The dark rift of dust down the middle of the band, cut out of the glow.
    this.rifts = [];
    for (let i = 0; i < 160; i++) {
      const t = gauss() * 1.1;
      this.rifts.push({ d: band(t, 0.004 + gauss() * 0.006), r: 0.012 + rand() * 0.022, a: 0.18 + rand() * 0.22 });
    }
    this.shade = sprite([0, 0, 0], 64);
    // Nebulae: violet, rose and teal clouds scattered over the sky.
    const hues = [[150, 90, 255], [255, 90, 170], [70, 200, 220], [110, 120, 255]];
    for (let i = 0; i < 12; i++) {
      const d = randomDir();
      const img = sprite(hues[i % hues.length]);
      for (let k = 0; k < 4; k++) glows.push({ d: norm(add(d, randomDir(), 0.07)), r: 0.08 + rand() * 0.14, a: 0.09 + rand() * 0.08, img });
    }
    this.halo = sprite([90, 160, 255], 256);
    this.glows = glows;

    // Stars that twinkle (drawn again, gently pulsing, on the effects canvas).
    this.spark = sprite([255, 255, 255], 32, 1);
    const bright = stars.filter(s => s.size >= 2);
    const every = Math.max(1, Math.floor(bright.length / (this.small ? 18 : 40)));
    this.twinklers = bright.filter((_, i) => i % every === 0)
      .map(s => ({ d: s.d, phase: rand() * TAU, speed: 0.6 + rand() * 1.4 }));
  }

  resize() {
    const ratio = Math.min(devicePixelRatio || 1, 2);
    const { clientWidth: w, clientHeight: h } = this.map.getContainer();
    for (const c of [this.sky, this.fx]) {
      c.width = Math.round(w * ratio);
      c.height = Math.round(h * ratio);
    }
    this.w = w;
    this.h = h;
    this.ratio = ratio;
    this.dirty = []; // resizing cleared the canvases
  }

  schedule() {
    if (this.queued || !this.ready) return;
    this.queued = true;
    requestAnimationFrame(() => { this.queued = false; this.draw(); });
  }

  // Whether any sky shows: a globe that doesn't yet fill the screen.
  visible() {
    if (this.map.getProjection()?.type !== 'globe') return false;
    const radius = 512 * 2 ** this.map.getZoom() / TAU;
    return radius < Math.hypot(this.w, this.h) / 2;
  }

  // Camera looking at the Earth's centre from above the map's centre.
  camera() {
    const c = this.map.getCenter();
    const f = dir((c.lng + 180) * RAD, -Math.max(-89, Math.min(89, c.lat)) * RAD);
    const r = norm(cross(f, [0, 0, 1]));
    const u = cross(r, f);
    // The sky turns at a fraction of a real lens's rate: a wide view, so it
    // drifts rather than whips past.
    const focal = Math.max(this.w, this.h) * 0.42;
    const p = this.map.project(c); // the globe's centre on screen (the map is padded)
    // The globe's radius on screen, from how far a degree of latitude reaches.
    const q = this.map.project([c.lng, c.lat + (c.lat > 0 ? -1 : 1)]);
    const radius = Math.hypot(q.x - p.x, q.y - p.y) / RAD;
    return { f, r, u, focal, ox: p.x, oy: p.y, radius };
  }

  project(d, cam) {
    const z = dot(d, cam.f);
    if (z < 0.05) return null;
    return [cam.ox + (dot(d, cam.r) / z) * cam.focal, cam.oy - (dot(d, cam.u) / z) * cam.focal];
  }

  draw() {
    const on = this.visible();
    if (on !== this.active) {
      this.active = on;
      this.sky.hidden = this.fx.hidden = !on;
      this.animate();
    }
    if (!on) return;
    const g = this.sky.getContext('2d');
    g.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
    g.clearRect(0, 0, this.w, this.h);
    const cam = this.cam = this.camera();
    const { w, h } = this;

    g.globalCompositeOperation = 'lighter';
    for (const s of this.glows) {
      const p = this.project(s.d, cam);
      if (!p) continue;
      const size = s.r * cam.focal * 2;
      if (p[0] < -size || p[1] < -size || p[0] > w + size || p[1] > h + size) continue;
      g.globalAlpha = s.a;
      g.drawImage(s.img, p[0] - size / 2, p[1] - size / 2, size, size);
    }
    g.globalCompositeOperation = 'destination-out';
    for (const s of this.rifts) {
      const p = this.project(s.d, cam);
      if (!p) continue;
      const size = s.r * cam.focal * 2;
      g.globalAlpha = s.a;
      g.drawImage(this.shade, p[0] - size / 2, p[1] - size / 2, size, size);
    }
    g.globalCompositeOperation = 'lighter';
    // The atmosphere's glow around the limb.
    const R = cam.radius * 1.45;
    g.globalAlpha = 0.55;
    g.drawImage(this.halo, cam.ox - R, cam.oy - R, R * 2, R * 2);
    g.globalAlpha = 1;
    g.globalCompositeOperation = 'source-over';

    // project() inlined: thousands of stars, no garbage per frame.
    const { f, r, u, focal, ox, oy } = cam;
    const D = this.starDir, S = this.starSize, K = this.starStyle;
    let style = -1;
    for (let i = 0, j = 0; i < S.length; i++, j += 3) {
      const x = D[j], y = D[j + 1], z = D[j + 2];
      const depth = x * f[0] + y * f[1] + z * f[2];
      if (depth < 0.05) continue;
      const px = ox + ((x * r[0] + y * r[1] + z * r[2]) / depth) * focal;
      const py = oy - ((x * u[0] + y * u[1] + z * u[2]) / depth) * focal;
      if (px < 0 || py < 0 || px > w || py > h) continue;
      if (K[i] !== style) g.fillStyle = this.styles[style = K[i]];
      g.fillRect(px, py, S[i], S[i]);
    }
    this.twinkleAt = [];
    for (const t of this.twinklers) {
      const p = this.project(t.d, cam);
      if (p && p[0] > 0 && p[1] > 0 && p[0] < w && p[1] < h) this.twinkleAt.push([p[0], p[1], t.phase, t.speed]);
    }
    this.drawFx(performance.now());
  }

  // ---- Shooting stars and twinkling -------------------------------------

  animate() {
    const run = this.active && !document.hidden && !this.still.matches;
    if (run && !this.running) {
      this.running = true;
      this.nextMeteor = performance.now() + 1500 + Math.random() * 2500;
      const tick = now => {
        if (!this.running) return;
        // Twinkling needs little: about 12 frames a second, unless a meteor flies.
        if (this.meteors.length || now - (this.lastFx || 0) > 80) this.drawFx(now);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    } else if (!run && this.running) {
      this.running = false;
      this.meteors = [];
      this.dirty = [];
      this.fx.getContext('2d').clearRect(0, 0, this.fx.width, this.fx.height);
    }
  }

  spawn(now) {
    const { w, h } = this;
    const angle = (0.15 + Math.random() * 0.5) * Math.PI * (Math.random() < 0.5 ? 1 : -1) + Math.PI / 2;
    const speed = (0.5 + Math.random() * 0.6) * Math.max(w, h) / 1000; // px per ms
    this.meteors.push({
      x: Math.random() * w, y: Math.random() * h * 0.7,
      vx: Math.cos(angle) * speed * (Math.random() < 0.5 ? 1 : -1), vy: Math.sin(angle) * speed,
      born: now, life: 600 + Math.random() * 700, len: 90 + Math.random() * 170,
    });
    this.nextMeteor = now + 2500 + Math.random() * 6000;
  }

  drawFx(now) {
    this.lastFx = now;
    const g = this.fx.getContext('2d');
    g.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
    // Only what was drawn last time is cleared: a few small squares, not the screen.
    for (const [x, y, w, h] of this.dirty) g.clearRect(x, y, w, h);
    this.dirty = [];
    if (!this.running || !this.twinkleAt) return;

    for (const [x, y, phase, speed] of this.twinkleAt) {
      const k = 0.5 + 0.5 * Math.sin(now / 1000 * speed * TAU / 3 + phase);
      g.globalAlpha = 0.25 + 0.75 * k * k;
      const size = 7 + 5 * k;
      g.drawImage(this.spark, x - size / 2 + 0.5, y - size / 2 + 0.5, size, size);
      this.dirty.push([x - 8, y - 8, 17, 17]);
    }
    g.globalAlpha = 1;

    if (now > this.nextMeteor) this.spawn(now);
    this.meteors = this.meteors.filter(m => now - m.born < m.life);
    for (const m of this.meteors) {
      const age = (now - m.born) / m.life;
      const x = m.x + m.vx * (now - m.born), y = m.y + m.vy * (now - m.born);
      const v = Math.hypot(m.vx, m.vy);
      const tx = x - (m.vx / v) * m.len, ty = y - (m.vy / v) * m.len;
      const fade = Math.sin(age * Math.PI); // in, then out
      const grad = g.createLinearGradient(x, y, tx, ty);
      grad.addColorStop(0, `rgba(255,255,255,${0.9 * fade})`);
      grad.addColorStop(0.3, `rgba(190,215,255,${0.35 * fade})`);
      grad.addColorStop(1, 'rgba(160,190,255,0)');
      g.strokeStyle = grad;
      g.lineWidth = 2;
      g.lineCap = 'round';
      g.beginPath();
      g.moveTo(x, y);
      g.lineTo(tx, ty);
      g.stroke();
      g.globalAlpha = fade;
      g.drawImage(this.spark, x - 6, y - 6, 12, 12);
      g.globalAlpha = 1;
      this.dirty.push([Math.min(x, tx) - 8, Math.min(y, ty) - 8, Math.abs(x - tx) + 16, Math.abs(y - ty) + 16]);
    }
  }

}
