// Trailer renderer: drives the real site frame by frame on a virtual clock
// and saves 1920x1080 PNGs. Shots and copy come from shots.json, so changing
// the copy or the cut is an edit and a re-render.
//
//   node capture.mjs shots.json out/frames [from] [to]
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const [,, shotsPath, outDir, fromArg, toArg] = process.argv;
const cfg = JSON.parse(fs.readFileSync(shotsPath, 'utf8'));
const FPS = cfg.fps ?? 30;
const total = Math.round(cfg.duration * FPS);
const from = Number(fromArg ?? 0), to = Number(toArg ?? total);
fs.mkdirSync(outDir, { recursive: true });
const fontDir = path.join(path.dirname(new URL(import.meta.url).pathname), 'fonts');
const font = f => fs.readFileSync(path.join(fontDir, f)).toString('base64');

const ease = {
  linear: t => t,
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
  out: t => 1 - (1 - t) ** 3,
  in: t => t * t * t,
};
const lerp = (a, b, t) => a + (b - a) * t;
// Shortest way round for longitudes.
const lerpLng = (a, b, t) => { let d = b - a; if (d > 180) d -= 360; if (d < -180) d += 360; return a + d * t; };

// Camera, year and overlay state at time t (seconds).
function stateAt(t) {
  const shot = cfg.shots.find(s => t >= s.t0 && t < s.t1) ?? cfg.shots.at(-1);
  const u = Math.min(1, Math.max(0, (t - shot.t0) / (shot.t1 - shot.t0)));
  const e = ease[shot.ease ?? 'inOut'](u);
  const a = shot.from, b = shot.to ?? shot.from;
  const cam = {
    center: [lerpLng(a.center[0], b.center[0], e), lerp(a.center[1], b.center[1], e)],
    zoom: lerp(a.zoom, b.zoom, e),
    bearing: lerp(a.bearing ?? 0, b.bearing ?? 0, e),
    pitch: lerp(a.pitch ?? 0, b.pitch ?? 0, e),
  };
  const ye = ease[shot.yearEase ?? 'linear'](u);
  const year = Math.round(lerp(a.year, b.year ?? a.year, ye));
  // Overlays: each {id, text, t0, t1, fade} visible between t0 and t1.
  const texts = (cfg.texts ?? []).map(x => {
    const f = x.fade ?? 0.5;
    const op = t < x.t0 || t > x.t1 ? 0 : Math.min(1, (t - x.t0) / f, (x.t1 - t) / f);
    return { ...x, op: Math.max(0, op), rise: (1 - Math.min(1, (t - x.t0) / (f * 1.6))) * 14 };
  });
  return { shot, cam, year, texts, span: shot.span ?? 'auto', chrome: shot.chrome ?? 'clean', bigYear: shot.bigYear ?? false, padding: shot.padding ?? {} };
}

const browser = await chromium.launch({
  // CHROME: a Chromium binary, if not Playwright's own. Software GL renders
  // the same on any machine (SOFTWARE_GL=0 uses the GPU instead).
  executablePath: process.env.CHROME || undefined,
  args: [...(process.env.SOFTWARE_GL === '0' ? [] : ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']), '--hide-scrollbars'],
  // Map tiles and Wikimedia thumbnails come from outside: through the sandbox's proxy.
  proxy: process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } : undefined,
});
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, colorScheme: cfg.theme ?? 'dark' });
const page = await ctx.newPage();
page.on('pageerror', e => console.log('pageerror', e.message));
const s0 = stateAt(from / FPS);
if (process.env.DEBUG) console.error('goto');
await page.goto(`${process.env.TRAILER_URL ?? cfg.url}#y=${s0.year}&w=${s0.span}&m=${s0.cam.center[0]},${s0.cam.center[1]},${s0.cam.zoom}`);
await page.waitForFunction(() => window.geopedia?.map?.loaded(), null, { timeout: 60000 });
if (process.env.DEBUG) console.error('loaded');
await page.waitForTimeout(6000);
if (process.env.DEBUG) console.error('settled');

// Overlay layer and chrome switches.
await page.evaluate(({ cinzel, garamond, css }) => {
  const st = document.createElement('style');
  st.textContent = `
    @font-face { font-family: Cinzel; src: url(data:font/ttf;base64,${cinzel}); font-weight: 400 900; }
    @font-face { font-family: Garamond; src: url(data:font/ttf;base64,${garamond}); font-weight: 400 800; }
    body.tr-clean #sidebar, body.tr-clean .controls, body.tr-clean #timeline, body.tr-clean .brand-pill,
    body.tr-timeline #sidebar, body.tr-timeline .controls, body.tr-timeline .brand-pill,
    .maplibregl-ctrl-attrib, .maplibregl-ctrl-bottom-right, .maplibregl-ctrl-bottom-left, .toast { display: none !important; }
    #tr { position: fixed; inset: 0; pointer-events: none; z-index: 1000; }
    #tr .t { position: absolute; left: 0; right: 0; text-align: center; color: #fff; will-change: opacity, transform;
             text-shadow: 0 2px 24px rgba(0,0,0,.65), 0 0 2px rgba(0,0,0,.6); }
    #tr .vignette { position: absolute; inset: 0; background: radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,.45) 100%); }
    #tr .year { position: absolute; left: 88px; bottom: 70px; color: #fff; font: 600 132px/1 Cinzel, serif; letter-spacing: .04em;
                text-shadow: 0 4px 30px rgba(0,0,0,.6); }
    ${css}`;
  document.head.append(st);
  const tr = document.createElement('div');
  tr.id = 'tr';
  tr.innerHTML = '<div class="vignette"></div><div class="year"></div>';
  document.body.append(tr);
}, { cinzel: font('Cinzel[wght].ttf'), garamond: font('EBGaramond[wght].ttf'), css: cfg.css ?? '' });

if (process.env.DEBUG) console.error('overlay in');
const cdp = await ctx.newCDPSession(page);
await cdp.send('Emulation.setVirtualTimePolicy', { policy: 'pause' });
// Plain "advance": a hanging tile or thumbnail must not stall the clock (the
// frame loop below waits for loading in real time instead).
const DEBUG = !!process.env.DEBUG;
const advance = ms => new Promise((res, rej) => {
  const t = Date.now();
  // A budget can fail to expire while the page is busy: don't wait forever.
  const timer = setTimeout(() => { if (DEBUG) console.log('advance timeout', ms); res(); }, 20000);
  cdp.once('Emulation.virtualTimeBudgetExpired', () => { clearTimeout(timer); if (DEBUG && Date.now() - t > 2000) console.log('slow advance', Date.now() - t); res(); });
  cdp.send('Emulation.setVirtualTimePolicy', { policy: 'advance', budget: ms }).catch(rej);
});

let lastYear = null, lastSpan = null, lastChrome = null;
const only = process.env.FRAMES ? new Set(process.env.FRAMES.split(',').map(Number)) : null;
for (let f = from; f < to; f++) {
  if (only && !only.has(f)) continue;
  const s = stateAt(f / FPS);
  if (DEBUG) console.log('frame', f, 'set');
  await page.evaluate(({ s, newYear, newSpan, newChrome }) => {
    const g = window.geopedia;
    if (newChrome) {
      document.body.classList.toggle('tr-clean', s.chrome === 'clean');
      document.body.classList.toggle('tr-timeline', s.chrome === 'timeline');
      // The app pads the map for its sidebar and timeline; hidden, they'd
      // still push the camera around, so clean shots keep their own framing.
      const m = g.map;
      m._origSetPadding ??= m.setPadding.bind(m);
      m.setPadding = s.chrome === 'clean' ? () => m : m._origSetPadding;
      if (s.chrome !== 'clean') window.dispatchEvent(new Event('resize'));
    }
    if (newSpan) g.state.spanMode = s.span;
    if (newYear || newSpan) g.setYear(s.year);
    // Clean shots frame the whole screen (the app pads for its sidebar and timeline).
    g.map.jumpTo(s.chrome === 'clean' ? { ...s.cam, padding: { top: 0, left: 0, right: 0, bottom: 0, ...s.padding } } : s.cam);
    const tr = document.getElementById('tr');
    for (const x of s.texts) {
      let el = document.getElementById(`tr-${x.id}`);
      if (!el) {
        el = document.createElement('div');
        el.id = `tr-${x.id}`;
        el.className = `t ${x.cls ?? ''}`;
        el.innerHTML = x.html;
        el.setAttribute('style', x.style ?? '');
        tr.append(el);
      }
      el.style.opacity = x.op * (x.maxOpacity ?? 1);
      el.style.transform = `translateY(${x.rise}px)`;
    }
    const y = tr.querySelector('.year');
    y.textContent = s.bigYear ? (s.year <= 0 ? `${1 - s.year} BC` : String(s.year)) : '';
  }, { s, newYear: s.year !== lastYear, newSpan: s.span !== lastSpan, newChrome: s.chrome !== lastChrome });
  lastYear = s.year; lastSpan = s.span; lastChrome = s.chrome;
  // Render with the new camera and year (tiles and data get requested), wait
  // while anything is loading, then paint once more: the clock is frozen
  // between steps, so nothing reaches the screen without a step.
  const check = () => page.evaluate(() => {
    const g = window.geopedia, m = g.map;
    if (!m.loaded() || !m.areTilesLoaded()) return null;
    if ([...g.store.files.values()].some(v => v instanceof Promise)) return null;
    for (const [layer, src] of [['borders-cs-fill', 'borders-cs'], ['borders-fill', 'borders']]) {
      if (m.getLayer(layer) && m.getLayoutProperty(layer, 'visibility') !== 'none' && !m.querySourceFeatures(src).length) return null;
    }
    return { pins: document.querySelectorAll('.pin:not(.leaving)').length, photos: document.querySelectorAll('.pin-photo.loading').length };
  });
  if (DEBUG) console.log('frame', f, 'advance');
  await advance(17);
  if (DEBUG) console.log('frame', f, 'check');
  // A cut (or the first frame) waits for everything; inside a shot the camera
  // moves a little each frame, so a short wait is enough (the map draws
  // parent tiles while children load, which motion hides).
  const cut = only || f === from || stateAt(f / FPS).shot !== stateAt((f - 1) / FPS).shot;
  let st = cut ? await check() : { pins: 0, photos: 0 };
  if (!cut) {
    for (let k = 0; k < 15; k++) {
      const ok = await page.evaluate(() => window.geopedia.map.loaded() && ![...window.geopedia.store.files.values()].some(v => v instanceof Promise));
      if (ok) break;
      await page.waitForTimeout(100);
      await advance(16);
    }
  } else if (!st || st.photos) {
    // Workers and the network run in real time: give them real time too.
    // Settled: loaded, the same pins twice, photos in (or 6 s spent on them:
    // Wikimedia can stall).
    let prev = null;
    for (let k = 0; k < 300; k++) {
      if (st && prev && st.pins === prev.pins && (!st.photos || k > 60)) break;
      prev = st;
      if (DEBUG && k % 10 === 0) console.log('wait', k, JSON.stringify(st));
      await page.waitForTimeout(100);
      await advance(20);
      st = await check();
    }
  }
  // The capture waits for the next compositor frame, and frames only come
  // while the clock runs: ask first, then step until it arrives.
  if (DEBUG) console.log('frame', f, 'shoot');
  let shotP = cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
  let shot = null;
  for (let k = 0; !shot; k++) {
    if (k && k % 10 === 0) shotP = cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true });  // ask again
    if (k > 60) throw new Error(`no screenshot for frame ${f}`);  // the supervisor restarts us
    await advance(16);
    shot = await Promise.race([shotP, new Promise(r => setTimeout(() => r(null), 1500))]);
  }
  fs.writeFileSync(path.join(outDir, `f${String(f).padStart(4, '0')}.png`), Buffer.from(shot.data, 'base64'));
  if (f % 30 === 0) console.log('frame', f, 'year', s.year);
}
await browser.close();
