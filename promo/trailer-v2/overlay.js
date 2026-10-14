// Page-side effects for the trailer: comets, the sunrise, the impact, the year
// counter and timeline strip, callouts, copy, the implosion and the end card.
// capture.mjs injects this into the real site, calls TR.init once, then
// TR.frame(t, state) for every frame after it has moved the camera.
// Everything is a pure function of t (seeded randomness), so any frame can be
// rendered on its own and chunks rendered by different browsers match.
window.TR = (() => {
  const W = 1920, H = 1080;
  let cfg, map, dpr, front, fx, back, bx, flash, scrim, counter, callouts = [], texts = new Map();

  // ---- helpers -------------------------------------------------------------
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, k) => a + (b - a) * k;
  const smooth = (a, b, t) => { const k = clamp((t - a) / (b - a)); return k * k * (3 - 2 * k); };
  const easeOut = k => 1 - (1 - k) ** 3;
  const easeIn = k => k * k * k;
  const easeOutBack = k => { const c = 1.9; return 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2; };
  function rng(seed) {
    return () => {
      seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const proj = ll => { const p = map.project(ll); return [p.x, p.y]; };
  const hidden = ll => { const tr = map.transform; return !!(tr.isLocationOccluded && tr.isLocationOccluded({ lng: ll[0], lat: ll[1] })); };
  const hexA = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  };
  function canvas(id) {
    const c = document.createElement('canvas');
    c.id = id;
    c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
    c.style.cssText = `position:absolute;left:0;top:0;width:${W}px;height:${H}px;pointer-events:none`;
    return c;
  }
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  const fmtYear = y => (y <= 0 ? `${1 - y}<small>BC</small>` : y < 1000 ? `<small>AD</small>${y}` : String(y));

  // ---- the year curve (same as capture.mjs) ------------------------------
  function rushU(year) {
    const r = cfg.rush, span = r.to - r.from + r.offset;
    return Math.log(span / (r.to - year + r.offset)) / Math.log(span / r.offset);
  }

  // ---- init ----------------------------------------------------------------
  function init(c, images, hist) {
    cfg = c;
    map = window.geopedia.map;
    dpr = window.devicePixelRatio || 1;
    cfg.hist = hist;

    const tr = el('div'); tr.id = 'tr';
    document.body.append(tr);
    front = canvas('tr-front'); fx = front.getContext('2d');
    tr.append(front, el('div', 'vignette'));
    flash = el('div', 'flash'); tr.append(flash);
    scrim = el('div', 'scrim'); tr.append(scrim);
    counter = el('div', 'counter'); tr.append(counter);
    const tick = el('div'); tick.id = 'tr-tick'; tick.style.cssText = 'position:absolute;left:0;top:0;width:2px;height:2px;opacity:.01;background:#000'; tr.append(tick);

    // The sun lives behind the globe: between the sky and the map's canvas.
    back = canvas('tr-back'); bx = back.getContext('2d');
    const sky = document.querySelector('#map .space-fx') || document.querySelector('#map .space-sky');
    if (sky) sky.after(back); else map.getContainer().prepend(back);

    for (const [i, co] of cfg.callouts.entries()) {
      const color = css(`--c-${co.cat}`) || '#fff';
      const node = el('div', `co ${co.side}`);
      node.style.setProperty('--c', color);
      node.innerHTML = `<div class="co-ring"></div><div class="co-dot"></div><div class="co-line"></div>
        <div class="co-card"><div class="co-img" style="background-image:url('${images[i]}')"></div>
        <div class="co-text"><div class="co-d">${co.date}</div><div class="co-t">${co.title}</div></div></div>`;
      tr.append(node);
      callouts.push({ ...co, node, color, ring: node.querySelector('.co-ring'), dot: node.querySelector('.co-dot'),
        line: node.querySelector('.co-line'), card: node.querySelector('.co-card') });
    }
    for (const x of cfg.texts) {
      const n = el('div', `t ${x.cls}`, x.html);
      n.id = `tr-${x.id}`;
      tr.append(n);
      texts.set(x.id, { ...x, n });
    }
    makeComets();
  }

  // ---- 1. The race: comets streak toward the Earth ------------------------
  let comets, streaks;
  const COLORS = [[255, 214, 150], [96, 224, 255], [255, 96, 196], [176, 128, 255], [255, 160, 80], [120, 255, 214]];
  function makeComets() {
    const r = rng(7);
    comets = [];
    // The lead: rises from below the frame and is still racing at the cut.
    comets.push({ th: Math.PI / 2 + 0.08, rho: 0.95, z0: 0.42, v: 2.25, wob: 0.004, w: 1, ph: 0, curve: -0.05, col: [255, 236, 190], die: 99, size: 1.35 });
    for (let i = 1; i < 17; i++) {
      comets.push({
        th: r() * Math.PI * 2, rho: 0.8 + r() * 1.8, z0: 0.3 - r() * 1.6, v: 1.0 + r() * 1.5,
        wob: 0.004 + r() * 0.01, w: 0.6 + r(), ph: r() * 6.28, curve: (r() - 0.5) * 0.24, col: COLORS[1 + (i % 5)],
        die: i % 3 === 0 ? 99 : 1.6 + r() * 2.2, size: 0.8 + r() * 0.6,
      });
    }
    streaks = [];
    for (let i = 0; i < 260; i++) streaks.push({ a: r() * 6.283, d: 0.35 + r() * 3.2, z: r() * 14, w: 0.6 + r() * 1.4 });
  }
  const F = 1100;
  function cometAt(c, t, vp) {
    const z = c.z0 + c.v * t;
    if (z <= 0.08) return null;
    const th = c.th + c.curve * t + c.wob * Math.sin(c.w * t + c.ph);
    const rho = c.rho * (1 - 0.18 * t / 4);
    return { x: vp[0] + Math.cos(th) * rho * F / z, y: vp[1] + Math.sin(th) * rho * F / z, z };
  }
  function drawRace(t) {
    t += 0.6; // a cold open: the comets are already in flight on frame one
    const vp = proj(cfg.race.center);
    // Warp streaks: dust rushing past the camera.
    fx.globalCompositeOperation = 'lighter';
    fx.lineCap = 'round';
    for (const s of streaks) {
      const z = ((s.z - t * 7) % 14 + 14) % 14 + 0.25;
      const k = F / z, k2 = F / (z + 0.9);
      const x1 = vp[0] + Math.cos(s.a) * s.d * k, y1 = vp[1] + Math.sin(s.a) * s.d * k;
      const x2 = vp[0] + Math.cos(s.a) * s.d * k2, y2 = vp[1] + Math.sin(s.a) * s.d * k2;
      const a = clamp((14 - z) / 14) * 0.38 * smooth(0, 0.25, t);
      fx.strokeStyle = `rgba(200,220,255,${a})`;
      fx.lineWidth = s.w * clamp(3 / z, 0.4, 2.2);
      fx.beginPath(); fx.moveTo(x1, y1); fx.lineTo(x2, y2); fx.stroke();
    }
    // Comets: far ones first.
    const live = comets.map(c => ({ c, p: cometAt(c, t, vp) })).filter(o => o.p).sort((a, b) => b.p.z - a.p.z);
    for (const { c, p } of live) {
      const fade = c.die < 99 ? 1 - smooth(c.die, c.die + 0.35, t) : 1;
      if (fade <= 0) { burst(c, t, vp); continue; }
      drawComet(c, t, vp, fade);
      if (c.die < 99 && t > c.die) burst(c, t, vp);
    }
    fx.globalCompositeOperation = 'source-over';
  }
  function drawComet(c, t, vp, fade) {
    const N = 26, pts = [];
    for (let k = 0; k <= N; k++) {
      const p = cometAt(c, t - k * 0.03, vp);
      if (!p) break;
      pts.push(p);
    }
    if (pts.length < 2) return;
    const head = pts[0];
    const hr = clamp(70 * c.size / head.z, 1.5, 70);
    if (head.x < -400 || head.x > W + 400 || head.y < -400 || head.y > H + 400) return;
    const [r, g, b] = c.col;
    // Tail: a tapering ribbon, widest just behind the head.
    const left = [], right = [];
    for (let k = 0; k < pts.length; k++) {
      const a = pts[Math.max(0, k - 1)], bb = pts[Math.min(pts.length - 1, k + 1)];
      let dx = bb.x - a.x, dy = bb.y - a.y; const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
      const w = clamp(70 * c.size / pts[k].z, 1, 80) * 0.85 * (1 - k / pts.length) ** 0.8;
      left.push([pts[k].x - dy * w, pts[k].y + dx * w]); right.push([pts[k].x + dy * w, pts[k].y - dx * w]);
    }
    const tail = pts.at(-1);
    const grad = fx.createLinearGradient(head.x, head.y, tail.x, tail.y);
    grad.addColorStop(0, `rgba(${r},${g},${b},${0.75 * fade})`);
    grad.addColorStop(0.35, `rgba(${r},${g},${b},${0.32 * fade})`);
    grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
    fx.fillStyle = grad;
    fx.beginPath();
    fx.moveTo(left[0][0], left[0][1]);
    for (const q of left) fx.lineTo(q[0], q[1]);
    for (let k = right.length - 1; k >= 0; k--) fx.lineTo(right[k][0], right[k][1]);
    fx.closePath(); fx.fill();
    // Hot core line.
    const g2 = fx.createLinearGradient(head.x, head.y, tail.x, tail.y);
    g2.addColorStop(0, `rgba(255,255,255,${0.9 * fade})`);
    g2.addColorStop(0.5, `rgba(255,255,255,0)`);
    fx.strokeStyle = g2; fx.lineWidth = Math.max(1, hr * 0.35);
    fx.beginPath(); fx.moveTo(head.x, head.y);
    for (const q of pts) fx.lineTo(q.x, q.y);
    fx.stroke();
    // Head glow and sparks shed along the tail.
    glow(fx, head.x, head.y, hr * 5, [r, g, b], 0.55 * fade);
    glow(fx, head.x, head.y, hr * 1.6, [255, 255, 255], 0.95 * fade);
    const rr = rng(Math.floor(t * 30) * 131 + c.th * 1000);
    for (let i = 0; i < 6; i++) {
      const k = Math.floor(rr() * (pts.length - 1)), q = pts[k];
      glow(fx, q.x + (rr() - 0.5) * hr * 2, q.y + (rr() - 0.5) * hr * 2, 2 + rr() * 4, [255, 255, 255], 0.5 * fade * (1 - k / pts.length));
    }
  }
  function burst(c, t, vp) {
    const age = t - c.die;
    if (age < 0 || age > 0.6) return;
    const p = cometAt(c, c.die, vp);
    if (!p) return;
    const rr = rng(Math.round(c.th * 1e4));
    for (let i = 0; i < 18; i++) {
      const a = rr() * 6.283, v = 60 + rr() * 260;
      const d = v * (1 - Math.exp(-age * 4)) / 4;
      glow(fx, p.x + Math.cos(a) * d, p.y + Math.sin(a) * d, 3 + rr() * 5, c.col, 0.8 * (1 - age / 0.6));
    }
  }
  function glow(g, x, y, r, [cr, cg, cb], a) {
    if (a <= 0.002 || r <= 0.2) return;
    const gr = g.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, `rgba(${cr},${cg},${cb},${a})`);
    gr.addColorStop(0.35, `rgba(${cr},${cg},${cb},${a * 0.35})`);
    gr.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
    g.fillStyle = gr;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  }

  // ---- 2. Dawn: the sun crests the horizon --------------------------------
  function horizonY() {
    const [lng, lat0] = cfg.dawn.center;
    let lo = lat0, hi = 89.9;
    if (hidden([lng, lo])) return proj([lng, lo])[1];
    if (!hidden([lng, hi])) return proj([lng, hi])[1];
    for (let i = 0; i < 22; i++) { const m = (lo + hi) / 2; if (hidden([lng, m])) hi = m; else lo = m; }
    return proj([lng, lo])[1];
  }
  function drawDawn(t) {
    const d = cfg.dawn;
    const yH = horizonY(), x = W / 2;
    const rise = smooth(d.sunrise[0], d.sunrise[1], t);
    const pre = smooth(d.glow, d.sunrise[0] + 0.4, t);
    const R = 30;
    const sy = yH + R * (1.15 - 2.6 * rise);
    const up = clamp((yH - (sy - R)) / (2 * R)); // how much of the disc clears the horizon
    // Behind the globe: horizon glow, corona, rays, the disc.
    bx.globalCompositeOperation = 'lighter';
    ellipse(bx, x, yH, 1300, 120, [110, 160, 255], 0.10 + 0.25 * pre + 0.2 * rise);
    ellipse(bx, x, yH, 900, 170, [255, 170, 90], 0.10 * pre + 0.55 * rise);
    glow(bx, x, sy, 420 * (0.5 + 0.5 * rise), [255, 226, 180], 0.25 * pre + 0.7 * rise);
    bx.save(); bx.translate(x, sy);
    for (let i = 0; i < 20; i++) {
      const a = i / 20 * Math.PI * 2 + t * 0.06, L = 600 + 500 * ((i * 7) % 5) / 5;
      const g = bx.createLinearGradient(0, 0, Math.cos(a) * L, Math.sin(a) * L);
      g.addColorStop(0, `rgba(255,236,200,${0.16 * rise})`); g.addColorStop(1, 'rgba(255,236,200,0)');
      bx.fillStyle = g;
      bx.beginPath(); bx.moveTo(0, 0);
      bx.lineTo(Math.cos(a - 0.012) * L, Math.sin(a - 0.012) * L); bx.lineTo(Math.cos(a + 0.012) * L, Math.sin(a + 0.012) * L);
      bx.closePath(); bx.fill();
    }
    bx.restore();
    bx.globalCompositeOperation = 'source-over';
    bx.fillStyle = `rgba(255,252,240,${smooth(d.sunrise[0], d.sunrise[0] + 0.5, t)})`;
    bx.beginPath(); bx.arc(x, sy, R, 0, Math.PI * 2); bx.fill();
    // In front: glare over the limb, an anamorphic streak, a few lens ghosts.
    fx.globalCompositeOperation = 'lighter';
    if (up > 0) {
      glow(fx, x, Math.min(sy, yH), 160, [255, 240, 210], 0.55 * up);
      const g = fx.createLinearGradient(0, 0, W, 0);
      g.addColorStop(0, 'rgba(90,170,255,0)'); g.addColorStop(0.3, `rgba(110,190,255,${0.35 * up})`);
      g.addColorStop(0.5, `rgba(235,248,255,${0.95 * up})`); g.addColorStop(0.7, `rgba(110,190,255,${0.35 * up})`);
      g.addColorStop(1, 'rgba(90,170,255,0)');
      fx.fillStyle = g;
      const yy = Math.min(sy, yH - 2);
      fx.fillRect(0, yy - 2, W, 4);
      fx.globalAlpha = 0.35; fx.fillRect(0, yy - 9, W, 18); fx.globalAlpha = 1;
      const cx = W / 2, cy = H / 2;
      for (const [k, r, col] of [[1.5, 46, [120, 255, 200]], [1.9, 90, [255, 120, 220]], [2.5, 24, [140, 180, 255]]]) {
        glow(fx, lerp(x, cx, k), lerp(yy, cy, k), r, col, 0.16 * up);
      }
    }
    // The lead comet arcs in and strikes Mesopotamia.
    const k = clamp((t - d.comet[0]) / (d.comet[1] - d.comet[0]));
    if (k > 0 && k < 1) {
      const P = proj(cfg.impact.at), S = [180, -80], C = [560, 120];
      const bez = q => [(1 - q) ** 2 * S[0] + 2 * (1 - q) * q * C[0] + q * q * P[0], (1 - q) ** 2 * S[1] + 2 * (1 - q) * q * C[1] + q * q * P[1]];
      const q = easeIn(k) * 0.85 + k * 0.15;
      const head = bez(q);
      const N = 22;
      for (let i = N; i >= 0; i--) {
        const qq = Math.max(0, q - i * 0.012), p = bez(qq);
        const f = 1 - i / N;
        glow(fx, p[0], p[1], 4 + 16 * f * (0.5 + q), [255, 214, 150], 0.22 * f);
      }
      glow(fx, head[0], head[1], 70 * (0.6 + q), [255, 214, 150], 0.6);
      glow(fx, head[0], head[1], 16 * (0.6 + q), [255, 255, 255], 1);
    }
    fx.globalCompositeOperation = 'source-over';
  }
  function ellipse(g, x, y, rx, ry, col, a) {
    g.save(); g.translate(x, y); g.scale(rx / ry, 1);
    glow(g, 0, 0, ry, col, a);
    g.restore();
  }

  // ---- 3. Impact ----------------------------------------------------------
  function drawImpact(t) {
    const t0 = cfg.impact.t, age = t - t0;
    if (age < 0 || age > 1.2) return;
    const [x, y] = proj(cfg.impact.at);
    fx.globalCompositeOperation = 'lighter';
    for (const [delay, col, size] of [[0, [255, 222, 170], 1700], [0.1, [120, 210, 255], 1100]]) {
      const p = clamp((age - delay) / 0.95);
      if (p <= 0 || p >= 1) continue;
      const r = 20 + size * easeOut(p);
      fx.strokeStyle = `rgba(${col[0]},${col[1]},${col[2]},${0.9 * (1 - p) ** 1.4})`;
      fx.lineWidth = 3 + 30 * (1 - p);
      fx.beginPath(); fx.arc(x, y, r, 0, Math.PI * 2); fx.stroke();
    }
    glow(fx, x, y, 500, [255, 220, 170], 0.8 * Math.exp(-age * 4));
    const rr = rng(99);
    for (let i = 0; i < 70; i++) {
      const a = rr() * 6.283, v = 300 + rr() * 900;
      const d = v * (1 - Math.exp(-age * 3)) / 3;
      glow(fx, x + Math.cos(a) * d, y + Math.sin(a) * d, 3 + rr() * 6, [255, 230, 190], 0.9 * clamp(1 - age / (0.5 + rr() * 0.6)));
    }
    fx.globalCompositeOperation = 'source-over';
  }

  // ---- 4. The rush: counter, timeline strip, callouts ----------------------
  function drawCounter(t, s) {
    const r = cfg.rush;
    const a = smooth(r.t0 + 0.1, r.t0 + 0.4, t) * (1 - smooth(r.t1 + 0.35, r.t1 + 0.7, t));
    counter.style.opacity = a;
    scrim.style.opacity = a;
    if (a <= 0) return;
    counter.innerHTML = fmtYear(s.label);
    const pulse = t >= r.t1 ? 1 + 0.07 * Math.exp(-(t - r.t1) * 7) : 1;
    counter.style.transform = `scale(${pulse})`;
    // Timeline strip: history piling up, revealed as the playhead passes.
    const u = clamp((t - r.t0) / (r.t1 - r.t0));
    const x0 = 96, x1 = W - 96, base = H - 70, hh = 54, hist = cfg.hist;
    fx.save();
    fx.globalAlpha = a;
    fx.strokeStyle = 'rgba(255,255,255,0.22)'; fx.lineWidth = 1;
    fx.beginPath(); fx.moveTo(x0, base + 0.5); fx.lineTo(x1, base + 0.5); fx.stroke();
    const n = hist.length, upto = Math.max(1, Math.round(u * (n - 1)));
    const grad = fx.createLinearGradient(0, base - hh, 0, base);
    grad.addColorStop(0, 'rgba(255,255,255,0.75)'); grad.addColorStop(1, 'rgba(120,190,255,0.12)');
    fx.fillStyle = grad;
    fx.beginPath(); fx.moveTo(x0, base);
    for (let i = 0; i <= upto; i++) fx.lineTo(x0 + (x1 - x0) * i / (n - 1), base - hh * hist[i]);
    fx.lineTo(x0 + (x1 - x0) * upto / (n - 1), base); fx.closePath(); fx.fill();
    const px = x0 + (x1 - x0) * u, py = base - hh * hist[upto];
    fx.globalCompositeOperation = 'lighter';
    fx.fillStyle = 'rgba(255,255,255,0.9)'; fx.fillRect(px - 1, base - hh - 8, 2, hh + 8);
    glow(fx, px, py, 26, [150, 210, 255], 0.9);
    fx.globalCompositeOperation = 'source-over';
    fx.font = '500 15px "Inter", sans-serif'; fx.fillStyle = 'rgba(255,255,255,0.55)'; fx.textAlign = 'center';
    for (const [y, label] of [[-2999, '3000 BC'], [-999, '1000 BC'], [1, 'AD 1'], [1000, '1000'], [1500, '1500'], [1800, '1800'], [1900, '1900'], [2000, '2000']]) {
      const xx = x0 + (x1 - x0) * rushU(y);
      fx.fillRect(xx - 0.5, base + 4, 1, 6);
      fx.fillText(label, xx, base + 28);
    }
    fx.restore();
  }

  function drawCallouts(t) {
    for (const c of callouts) {
      const age = t - c.t;
      if (age < 0 || age > 0.95 || hidden(c.at)) { c.node.style.opacity = 0; continue; }
      const [x, y] = proj(c.at);
      c.node.style.opacity = 1;
      // Ring and dot on the spot.
      const rp = clamp(age / 0.7);
      c.ring.style.transform = `translate(${x}px,${y}px) scale(${0.2 + 2.3 * easeOut(rp)})`;
      c.ring.style.opacity = (1 - rp) * 0.9;
      const out = smooth(0.72, 0.92, age);
      c.dot.style.transform = `translate(${x}px,${y}px) scale(${easeOutBack(clamp(age / 0.18)) * (1 - out)})`;
      // Card above the spot (below if no room), on its side.
      const right = c.side === 'right', below = y - 360 < 24;
      const cx = right ? x + 54 : x - 54, cy = below ? y + 54 : y - 54;
      const lp = clamp(age / 0.12);
      const len = Math.hypot(cx - x, cy - y) * lp, ang = Math.atan2(cy - y, cx - x);
      c.line.style.transform = `translate(${x}px,${y}px) rotate(${ang}rad)`;
      c.line.style.width = `${len}px`;
      c.line.style.opacity = 1 - out;
      const k = clamp((age - 0.04) / 0.22);
      const sc = k <= 0 ? 0.6 : 0.6 + 0.4 * easeOutBack(k);
      const ox = right ? 0 : -100, oy = below ? 0 : -100;
      c.card.style.transform = `translate(${cx}px,${cy - 12 * out}px) translate(${ox}%,${oy}%) scale(${sc})`;
      c.card.style.transformOrigin = `${right ? 'left' : 'right'} ${below ? 'top' : 'bottom'}`;
      c.card.style.opacity = clamp(k * 3) * (1 - out);
    }
  }

  // ---- 5. Payoff and implosion --------------------------------------------
  function drawImplode(t) {
    const [a, b] = cfg.payoff.implode;
    if (t < a || t > b + 0.2) return;
    const g = proj(map.getCenter().toArray());
    const rr = rng(4242);
    const pal = ['--c-conflict', '--c-politics', '--c-disaster', '--c-culture', '--c-science', '--c-exploration', '--c-built'].map(css);
    fx.globalCompositeOperation = 'lighter';
    fx.lineCap = 'round';
    for (let i = 0; i < 520; i++) {
      const ang = rr() * 6.283, dist = 260 + rr() ** 0.7 * 1300, ts = a + rr() * (b - a - 0.3), dur = 0.28 + rr() * 0.22;
      const col = pal[i % pal.length];
      const k = (t - ts) / dur;
      if (k < 0 || k > 1) continue;
      const d1 = dist * (1 - easeIn(k)), d0 = dist * (1 - easeIn(Math.max(0, k - 0.12)));
      fx.strokeStyle = hexA(col, 0.85 * Math.sin(k * Math.PI) ** 0.5);
      fx.lineWidth = 1.5 + 2 * rr();
      fx.beginPath();
      fx.moveTo(g[0] + Math.cos(ang) * d0, g[1] + Math.sin(ang) * d0);
      fx.lineTo(g[0] + Math.cos(ang) * d1, g[1] + Math.sin(ang) * d1);
      fx.stroke();
    }
    const q = smooth(a + 0.25, b, t);
    glow(fx, g[0], g[1], 60 + 380 * q, [255, 236, 200], 0.9 * q);
    glow(fx, g[0], g[1], 12 + 30 * q, [255, 255, 255], q);
    fx.globalCompositeOperation = 'source-over';
  }

  function drawEnd(t) {
    const t0 = cfg.end.t, age = t - t0;
    if (age < -0.05) return;
    const cx = W / 2, cy = H * 0.47;
    fx.globalCompositeOperation = 'lighter';
    // The point the world collapsed into, now a star behind the logo.
    glow(fx, cx, cy, 700, [120, 160, 255], 0.22 + 0.5 * Math.exp(-age * 3));
    glow(fx, cx, cy, 260, [255, 230, 200], 0.12 + 0.7 * Math.exp(-age * 4));
    const sk = 0.28 + 0.7 * Math.exp(-age * 2.5);
    const g = fx.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, 'rgba(90,170,255,0)'); g.addColorStop(0.5, `rgba(220,240,255,${sk})`); g.addColorStop(1, 'rgba(90,170,255,0)');
    fx.fillStyle = g; fx.fillRect(0, cy - 1.5, W, 3);
    fx.globalAlpha = 0.3; fx.fillRect(0, cy - 10, W, 20); fx.globalAlpha = 1;
    const p = clamp(age / 0.8);
    if (p < 1) {
      fx.strokeStyle = `rgba(255,236,210,${0.8 * (1 - p) ** 1.5})`;
      fx.lineWidth = 2 + 20 * (1 - p);
      fx.beginPath(); fx.arc(cx, cy, 30 + 1400 * easeOut(p), 0, Math.PI * 2); fx.stroke();
    }
    fx.globalCompositeOperation = 'source-over';
  }

  function drawTexts(t) {
    for (const x of texts.values()) {
      const f = x.fade ?? 0.4;
      const op = t < x.t0 || t > x.t1 ? 0 : Math.min(1, (t - x.t0) / f, (x.t1 - t) / f);
      x.n.style.opacity = op;
      const age = t - x.t0;
      if (x.cls.includes('logo')) {
        const k = easeOut(clamp(age / 0.7));
        x.n.style.setProperty('--k', k); // tracks in to the size's own spacing (overlay.css)
        x.n.style.filter = `blur(${(1 - k) * 14}px)`;
      } else {
        x.n.style.transform = `translateY(${(1 - easeOut(clamp(age / 0.5))) * 24}px)`;
      }
    }
  }

  // ---- frame ---------------------------------------------------------------
  function frame(t, s) {
    fx.setTransform(dpr, 0, 0, dpr, 0, 0); fx.clearRect(0, 0, W, H);
    bx.setTransform(dpr, 0, 0, dpr, 0, 0); bx.clearRect(0, 0, W, H);
    if (t < cfg.dawn.t0) drawRace(t);
    else if (t < cfg.impact.t) drawDawn(t);
    drawImpact(t);
    drawCounter(t, s);
    drawCallouts(t);
    drawImplode(t);
    drawEnd(t);
    drawTexts(t);
    // Flash: the strike, and the world collapsing into the logo.
    const it = cfg.impact.t, et = cfg.end.t;
    const f1 = t < it ? smooth(it - 0.09, it, t) : Math.exp(-(t - it) * 8);
    const f2 = t < et ? smooth(et - 0.12, et, t) * 0.95 : 0.95 * Math.exp(-(t - et) * 6);
    flash.style.opacity = Math.max(f1, f2);
  }

  return { init, frame };
})();
