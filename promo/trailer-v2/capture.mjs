// Trailer renderer: drives the real site frame by frame on a virtual clock and
// saves PNGs. The edit (camera, years, callouts, copy) is cut.json; the
// effects drawn over the map are overlay.js and overlay.css.
//
//   node capture.mjs frames [from] [to]
//   FPS=15 SCALE=0.5 node capture.mjs draft      (a quick draft: 960x540)
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stateAt, histBins } from './cut.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const cfg = JSON.parse(fs.readFileSync(path.join(here, 'cut.json'), 'utf8'));
const FPS = Number(process.env.FPS || 30), SCALE = Number(process.env.SCALE || 1);
const DRAFT = SCALE < 1 || FPS < 30;
const [,, outDir, fromArg, toArg] = process.argv;
const total = Math.round(cfg.duration * FPS);
const from = Number(fromArg ?? 0), to = Math.min(total, Number(toArg ?? total));
fs.mkdirSync(outDir, { recursive: true });
const DEBUG = !!process.env.DEBUG;

// Callout photos come from cache/ (fetch-images.sh fills it).
const cacheDir = process.env.CACHE || path.join(here, 'cache');
const images = cfg.callouts.map(c => {
  const f = path.join(cacheDir, c.img.replaceAll('/', '_'));
  return fs.existsSync(f) ? `data:image/jpeg;base64,${fs.readFileSync(f).toString('base64')}` : '';
});
const hist = histBins(JSON.parse(fs.readFileSync(path.join(here, '../../data/hist.json'), 'utf8')), cfg);

const browser = await chromium.launch({
  executablePath: process.env.CHROME || undefined,
  // Software GL renders the same on any machine (SOFTWARE_GL=0 uses the GPU).
  args: [...(process.env.SOFTWARE_GL === '0' ? [] : ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']), '--hide-scrollbars'],
  proxy: process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } : undefined,
});
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: SCALE, colorScheme: 'dark' });
const page = await ctx.newPage();
page.on('pageerror', e => console.log('pageerror', e.message));
if (DEBUG) page.on('console', m => console.log('console', m.text()));

const s0 = stateAt(cfg, from / FPS);
await page.goto(`${process.env.TRAILER_URL ?? cfg.url}#y=${s0.year}&w=${s0.span}&m=${s0.cam.center[0]},${s0.cam.center[1]},${Math.max(0, s0.cam.zoom)}`);
await page.waitForFunction(() => window.geopedia?.map?.loaded(), null, { timeout: 60000 });
await page.waitForTimeout(5000);
await page.addStyleTag({ content: fs.readFileSync(path.join(here, 'overlay.css'), 'utf8') });
await page.addScriptTag({ content: fs.readFileSync(path.join(here, 'overlay.js'), 'utf8') });
await page.evaluate(({ cfg, images, hist }) => {
  const m = window.geopedia.map;
  m.setMinZoom(-2);
  m.setMaxPitch(85);
  // The app pads the map for its (hidden) panels: the trailer frames the whole screen.
  m.setPadding = () => m;
  window.TR.init(cfg, images, hist);
}, { cfg, images, hist });

const cdp = await ctx.newCDPSession(page);
// Real time, not a virtual clock (screenshots deadlock on one now and then):
// every frame sets the whole state itself, so only the site's own CSS
// animations need taming, done below.
const raf = () => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));

async function apply(f) {
  const t = f / FPS, s = stateAt(cfg, t);
  await page.evaluate(({ t, s }) => {
    const g = window.geopedia, m = g.map;
    if (s.pins !== window.__pins) {
      window.__pins = s.pins;
      document.body.classList.toggle('tr-nopins', !s.pins);
      if (m.getLayer('dots')) m.setLayoutProperty('dots', 'visibility', s.pins ? 'visible' : 'none');
    }
    let again = false;
    if (s.borders !== g.state.borders) { g.state.borders = s.borders; again = true; }
    if (s.span !== g.state.spanMode) { g.state.spanMode = s.span; again = true; }
    if (again || s.year !== g.state.year) g.setYear(s.year);
    m.jumpTo({ ...s.cam, padding: { top: 0, left: 0, bottom: 0, right: 0, ...s.cam.padding } });
    const c = m.getCanvas();
    c.style.filter = s.filter;
    c.style.opacity = s.mapOpacity;
    window.TR.frame(t, s);
  }, { t, s });
  return s;
}

const ready = () => page.evaluate(() => {
  const g = window.geopedia, m = g.map;
  return m.loaded() && m.areTilesLoaded() && ![...g.store.files.values()].some(v => v instanceof Promise);
});

// Pins pop in over a few frames of video time (twice as fast as on the site),
// whatever the real time spent.
const settlePins = t => page.evaluate(now => {
  for (const el of document.querySelectorAll('.pin-in')) {
    el.dataset.born ??= now;
    for (const a of el.getAnimations()) { a.pause(); a.currentTime = Math.min((now - Number(el.dataset.born)) * 2, 400); }
  }
}, t * 1000);

await page.evaluate(() => { window.geopedia.map._fadeDuration = 0; }); // labels appear at once

// A few frames before the first one let pins settle in as they would mid-run.
for (let f = Math.max(0, from - 4); f < from; f++) { await apply(f); await raf(); await settlePins(f / FPS); }

const only = process.env.FRAMES ? new Set(process.env.FRAMES.split(',').map(Number)) : null;
for (let f = from; f < to; f++) {
  if (only && !only.has(f)) continue;
  const s = await apply(f);
  await raf();
  // Wait for tiles and data (capped: a stuck tile must not stop the run).
  const tries = f === from || only ? 300 : DRAFT ? 80 : 200;
  for (let k = 0; k < tries; k++) {
    if (await ready()) break;
    await page.waitForTimeout(40);
  }
  await raf();
  await settlePins(f / FPS);
  await raf();
  const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, `f${String(f).padStart(4, '0')}.png`), Buffer.from(shot.data, 'base64'));
  if (DEBUG || f % 15 === 0) console.log('frame', f, 't', (f / FPS).toFixed(2), 'year', s.year);
}
await browser.close();
