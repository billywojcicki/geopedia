// Geopedia: wires the data store, map, pins, timeline and sidebar together.

import { CATEGORIES, KIND, KIND_VERB, HAPPENED, JOURNEYS, DEFAULT_VIEW, STANDING_ZOOM, MIN_YEAR, MAX_YEAR, autoSpan } from './config.js';
import {
  $, el, setChildren, clamp, fmtYear, fmtRange, parseYear, catColor, metaLine,
  thumbUrl, wikiImg, wikiUrl, debounce, throttle, distKm,
} from './util.js';
import { Store, normalize, displayZoom } from './data.js';
import { buildStyle, applyAge, ageFor, themeName, addGlyphProtocol } from './basemap.js';
import { Timeline } from './timeline.js';
import { Pins } from './pins.js';
import { fetchSummary, fetchArticle } from './wiki.js';
import { Borders, prefetchBorders } from './borders.js';
import { applyOldNames, loadOldNames, resetOldNames } from './oldnames.js';
import { Space } from './space.js';
import { Sheet } from './sheet.js';
import { rankSearch } from './search.js';

const store = new Store();
const state = {
  year: DEFAULT_VIEW.year,
  spanMode: DEFAULT_VIEW.span, // 'auto' | number
  cats: new Set(CATEGORIES.flatMap((c, i) => (c.off ? [] : [i]))),
  standing: true,
  globe: true,
  borders: null, // null: automatic (on before AUTO_BORDERS_BEFORE); true/false: the user's choice
  selected: null,
};
let map, pins, timeline, borders, sheet, space;
let startZoom; // the first view's zoom: from the link, or the whole globe (globeZoom)
let stopPlay = () => {}; // set once the timeline's controls are bound
let candidates = []; // current window, sorted by priority
let candById = new Map();
let theme = themeName();

const span = () => (state.spanMode === 'auto' ? autoSpan(state.year) : state.spanMode);
const range = () => [state.year - span(), state.year + span()];

// ---------------------------------------------------------------------------
// Boot
//
// Startup is a race to first pins. index.html starts fetching the data index
// and the map style before any module loads; this module runs before MapLibre
// has finished downloading, so the first view's data is already on its way by
// the time the map exists. Pins go up as soon as data and map are both there,
// without waiting for basemap tiles.

const libReady = new Promise(res => {
  if (window.maplibregl) return res();
  document.getElementById('maplibre-js').addEventListener('load', res, { once: true });
});

async function init() {
  readHash();
  sheet = new Sheet($('#sidebar'), { onChange: onSheetChange, onDismiss: closeArticle, onDragStart: showListIfStale });
  onSheetChange(sheet.state);
  startZoom = state.zoom ?? globeZoom();
  // Stop iOS zooming the whole page on a pinch over the panels.
  document.addEventListener('gesturestart', e => e.preventDefault());
  const boot = window.__geopediaBoot || {};
  const stylePromise = buildStyle(theme, { globe: state.globe }, boot);
  await store.init(boot.index);
  store.onLoad = scheduleUpdate;

  timeline = new Timeline({ onInput: (y, dragging) => setYear(y, { dragging }) });
  store.loadHist().then(h => timeline.setHist(h), () => {});
  buildFilters();
  buildJourneys();
  bindChrome();
  setYear(state.year);
  update(); // request the first view's data now, not after the map constructor's long task
  if (bordersOn()) prefetchBorders(state.year); // behind the data, while MapLibre downloads

  await libReady;
  addGlyphProtocol();
  map = new maplibregl.Map({
    container: 'map',
    style: await stylePromise,
    center: state.center || DEFAULT_VIEW.center,
    zoom: startZoom,
    attributionControl: { compact: true, customAttribution: 'Data: <a href="https://www.wikidata.org" target="_blank">Wikidata</a> &amp; <a href="https://en.wikipedia.org" target="_blank">Wikipedia</a> (CC BY-SA)' },
    maxPitch: 0,
    dragRotate: false,
    pitchWithRotate: false,
    renderWorldCopies: true,
    fadeDuration: 150,
    // The style is built by our own code (js/basemap.js): checking it against
    // the style spec on every load only costs main-thread time.
    validateStyle: false,
    // Phones report 3x; 2x looks the same on a map and is far cheaper to draw.
    pixelRatio: Math.min(devicePixelRatio || 1, 2),
  });
  map.touchZoomRotate.disableRotation();
  space = new Space(map, { home: DEFAULT_VIEW.center });
  // Start with attribution folded into its (i) button.
  map.once('idle', () => document.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show'));
  // A touch on a pin starts fetching its summary, a little before the tap's click.
  pins = new Pins(map, { onHover: showHover, onLeave: hideHover, onClick: toggle, onPress: r => fetchSummary(r.title) });
  borders = new Borders(map);
  window.geopedia = { map, store, state, setYear, space, get candidates() { return candidates; } }; // for devtools

  map.on('style.load', onStyleLoad);
  map.once('load', onStyleLoad);
  bindDotEvents();
  syncPadding(false);
  new ResizeObserver(() => syncPadding(false)).observe($('#timeline'));
  map.on('move', throttle(placePins, 120));
  map.on('moveend', onMoveEnd);
  // Clicking empty map deselects; on phones it also puts the sheet away.
  map.on('click', e => {
    hideHover();
    if (overPin(e)) return;
    const r = dotAt(e.point);
    if (r) { toggle(r); return; }
    if (state.selected) closeArticle();
    else if (sheet.active && sheet.state !== 'peek') sheet.snap('peek');
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', async e => {
    const next = e.matches ? 'dark' : 'light';
    let style;
    try { style = await buildStyle(next, { globe: state.globe }, window.__geopediaBoot || {}); } catch { return; } // offline: keep the old look
    theme = next;
    styleReady = false;
    resetOldNames();
    map.setStyle(style);
  });
  // Lost OpenFreeMap's tile index (a blip at load): ask again, or the detailed
  // map stays blank for the session.
  map.on('error', e => {
    if (e.sourceId !== 'openmaptiles' || e.tile) return;
    setTimeout(() => { const s = map.getSource('openmaptiles'); if (s?.url) s.setUrl(s.url); }, 5000);
  });

  refresh(); // data may already be in: place pins and dots on the new map
  if (state.pendingSelect) openEntry({ id: state.pendingSelect, loc: state.pendingFile }, { fly: false });
  addEventListener('hashchange', onHashChange);
  addEventListener('popstate', onPopState);
  // Offline: say so. Back online: retry what failed at once, not on its backoff.
  addEventListener('offline', () => toast('You’re offline. The map shows what’s already loaded.', 0));
  addEventListener('online', () => { hideToast(); store.failed.clear(); refresh(); });
  // A tab left open across a deploy would mix old code with new data.
  let checked = Date.now();
  addEventListener('visibilitychange', async () => {
    if (document.hidden || Date.now() - checked < 10 * 60 * 1000) return;
    checked = Date.now();
    const v = await fetch('data/index.json', { cache: 'no-cache' }).then(r => r.json()).then(j => j.version, () => null);
    if (v && store.version && v !== store.version) toast('Geopedia was updated. Reload for the latest.', 0);
  });
  map.once('idle', () => {
    store.prefetchWorld();
    registerServiceWorker();
  });
}

// Runs for the first style and again after a theme switch replaces it.
function onStyleLoad() {
  if (map.getLayer('dots')) return;
  styleReady = true;
  addLayers();
  pins.attach();
  updateDots();
  applyAge(map, theme, lastAge = ageFor(state.year));
  if (!bordersReady) {
    // After the first frame, which asks for the first view's tiles: the
    // borders queue up right behind them in the map's worker.
    map.once('render', () => { bordersReady = true; syncBorders(); });
  }
  borders.restore();
  loadOldNames().then(() => { if (styleReady) applyOldNames(map, state.year); });
}

// The phone sheet moved: body classes drive the CSS, then the map padding and
// pin placement follow the new free area.
function onSheetChange(s) {
  // Switched to the phone layout while reading: the article needs the sheet up.
  if (sheet?.active && state.selected && s === 'peek') { sheet.allow(['half', 'full']); return; }
  const b = document.body.classList;
  b.remove('sheet-peek', 'sheet-half', 'sheet-full');
  if (sheet?.active) b.add(`sheet-${s}`);
  if (sheet?.active && s !== 'peek') stopPlay(); // the timeline steps aside: don't play on unseen
  $('#grabber').setAttribute('aria-label', s === 'full' ? 'Collapse panel' : 'Expand panel');
  syncPadding();
  clearTimeout(onSheetChange.t);
  onSheetChange.t = setTimeout(() => { obstacleCache = null; placePins(); }, 450); // after the slide
  showListIfStale();
}

function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || location.protocol === 'file:') return;
  navigator.serviceWorker.register('sw.js').catch(() => {});
  // Hand the new worker the data files this visit loaded before it existed.
  navigator.serviceWorker.ready.then(reg => {
    const urls = performance.getEntriesByType('resource').map(e => e.name).filter(u => u.includes('/data/') && u.includes('?v='));
    reg.active?.postMessage({ type: 'cache', urls });
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Time

let lastAge = -1;
let styleReady = false;

// Historical borders are on by default before 1992, when today's borders and
// names mislead (no Russia in 1960: the Soviet Union); the Layers toggle
// overrides that for the session. They are part of the first view: their
// files download during startup and they go on the map with its first frame.
const AUTO_BORDERS_BEFORE = 1992;
let bordersReady = false;
const bordersOn = () => state.borders ?? state.year < AUTO_BORDERS_BEFORE;
function syncBorders(dragging = false) {
  const on = bordersOn();
  $('#opt-borders').checked = on;
  if (!bordersReady) return;
  if (on !== borders.on) borders.toggle(on, state.year);
  else if (on) borders.setYear(state.year, dragging);
}

function setYear(y, { dragging = false } = {}) {
  state.year = clamp(Math.round(y), MIN_YEAR, MAX_YEAR);
  const [a, b] = range();
  timeline.set(state.year, [a, b]);
  if (document.activeElement !== $('#year-input')) $('#year-input').value = fmtYear(state.year);
  sizeYearInput();
  $('#tl-range').innerHTML = span() === 0 ? 'Exact year' : `<b>${fmtRange(a, b)}</b>`;

  const age = Math.round(ageFor(state.year) * 50) / 50;
  if (age !== lastAge && styleReady) { lastAge = age; applyAge(map, theme, age); }
  syncBorders(dragging);
  if (styleReady) applyOldNames(map, state.year);
  // Prefetch only once the map is up, so it never competes with the first view.
  if (!dragging && map) store.prefetchAround(currentView());
  scheduleUpdate();
  writeHash();
}

function sizeYearInput() {
  const i = $('#year-input');
  i.style.width = `${Math.max(4, i.value.length) * 0.62 + 0.4}em`;
}

// ---------------------------------------------------------------------------
// Updates: at most one per animation frame, however fast the timeline is
// scrubbed or data arrives.

let updateQueued = false;
let lastSig = '';

function scheduleUpdate() {
  if (updateQueued) return;
  updateQueued = true;
  requestAnimationFrame(() => { updateQueued = false; update(); });
}

// Force a full recompute on the next frame (filters or options changed).
function refresh() {
  lastSig = '';
  scheduleUpdate();
}

function update() {
  const view = currentView();
  const files = store.filesFor(view);
  store.ensure(files); // each file that arrives schedules another update
  const loaded = files.filter(f => store.get(f));
  setLoading(loaded.length < files.length);
  const sig = [view.a, view.b, displayZoom(view.zoom), [...state.cats].join(''), store.long.length, store.world.length, loaded.join()].join('|');
  if (sig !== lastSig) {
    lastSig = sig;
    recompute(view, loaded);
  }
}

function currentView() {
  const [a, b] = range();
  return { bounds: viewBounds(), zoom: map ? map.getZoom() : startZoom, a, b, standing: state.standing };
}

// [w, s, e, n] of the visible map plus a margin, so panning finds data waiting.
function viewBounds() {
  const bb = map ? map.getBounds() : estimatedBounds();
  const [w, s, e, n] = [bb.getWest(), bb.getSouth(), bb.getEast(), bb.getNorth()];
  const px = (e - w) * 0.15, py = (n - s) * 0.15;
  return [w - px, Math.max(-90, s - py), e + px, Math.min(90, n + py)];
}

// Before the map exists: the view estimated from centre and zoom (Web
// Mercator), shaped like the LngLatBounds the map would return.
function estimatedBounds() {
  const [lng, lat] = state.center || DEFAULT_VIEW.center;
  const degPerPx = 360 / (512 * 2 ** startZoom);
  const dx = (innerWidth / 2) * degPerPx, dy = (innerHeight / 2) * degPerPx * Math.cos((lat * Math.PI) / 180);
  const b = [lng - dx, Math.max(-85, lat - dy), lng + dx, Math.min(85, lat + dy)];
  return { getWest: () => b[0], getSouth: () => b[1], getEast: () => b[2], getNorth: () => b[3] };
}

let loadingTimer = null;
function setLoading(on) {
  clearTimeout(loadingTimer);
  if (!on) { $('#timeline').classList.remove('loading'); return; }
  // Only show the spinner if loading takes long enough to notice.
  loadingTimer = setTimeout(() => $('#timeline').classList.add('loading'), 250);
}

// ---------------------------------------------------------------------------
// Candidates: everything visible in the current window, by priority.

function priority(r) {
  // Places that merely existed rank below things that happened.
  if (r.standing) return r.isNew ? r.score * 0.6 : r.score * 0.35;
  // Foundings, births and deaths give way to events of similar weight.
  if (!HAPPENED.has(r.kind)) return r.score * 0.6;
  // Long spans (wars, eras, civilisations) are less about this moment.
  const len = r.end - r.start;
  return len > 10 ? r.score / Math.sqrt(1 + len / 40) : r.score;
}

function recompute(view, files) {
  const out = [];
  const seen = new Set();
  // Happenings come before standing places, so they win duplicate ids.
  for (const r of store.records(files, view.a, view.b, view.zoom)) {
    if (!state.cats.has(r.cat) || seen.has(r.id)) continue;
    seen.add(r.id);
    r.prio = priority(r);
    out.push(r);
  }
  out.sort((x, y) => y.prio - x.prio);
  candidates = out;
  candById = new Map(out.map(r => [r.id, r]));
  if (hoverId != null && !candById.has(hoverId)) hideHover(); // its pin or dot is gone
  updateDots();
  placePins();
  updateList();
  fillNearby();
}

// A shared link opens its article before anything around it has loaded:
// add the Nearby list once there is something to show.
function fillNearby() {
  const slot = state.selected && $('#article .a-nearby');
  if (!slot || slot.childElementCount) return;
  const sec = nearbySection(state.selected);
  if (sec) slot.append(sec);
}

// ---------------------------------------------------------------------------
// Map layers

function addLayers() {
  if (!map.getSource('items')) {
    map.addSource('items', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  }
  const color = ['match', ['get', 'c'], ...CATEGORIES.flatMap((c, i) => [i, cssVar(`--c-${c.id}`)]), '#888'];
  const standingColor = cssVar('--c-standing');
  map.addLayer({
    id: 'dots', type: 'circle', source: 'items',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'],
        1, ['+', 1.3, ['*', 0.13, ['sqrt', ['get', 's']]]],
        6, ['+', 2.2, ['*', 0.2, ['sqrt', ['get', 's']]]],
        12, ['+', 3.5, ['*', 0.28, ['sqrt', ['get', 's']]]]],
      'circle-color': ['case', ['==', ['get', 'st'], 1], standingColor, color],
      'circle-opacity': ['case', ['==', ['get', 'st'], 1], 0.55, 0.8],
      'circle-stroke-color': theme === 'dark' ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.9)',
      'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 2, 0, 6, 0.8, 12, 1.2],
      'circle-pitch-alignment': 'map',
    },
  });
}

// Layer-scoped handlers survive style swaps, so bind them once.
// Pins sit inside the map's container, so their mouse events reach the map
// too: those belong to the pin, not to a dot underneath it.
const overPin = e => e.originalEvent?.target?.closest?.('.pin');

function bindDotEvents() {
  map.on('mousemove', 'dots', e => {
    if (overPin(e)) return;
    const r = candById.get(e.features[0].properties.id);
    if (!r) return;
    map.getCanvas().style.cursor = 'pointer';
    showHover(r, null, e.point);
  });
  map.on('mouseleave', 'dots', e => {
    map.getCanvas().style.cursor = '';
    if (!overPin(e)) hideHover();
  });
}

// The record whose dot is nearest a click, within a finger's width on touch
// screens: dots are a few pixels across and a tap rarely lands on one exactly.
const COARSE = matchMedia('(pointer: coarse)');
const HOVER = matchMedia('(hover: hover)');
function dotAt(point) {
  const pad = COARSE.matches ? 16 : 5;
  const box = [[point.x - pad, point.y - pad], [point.x + pad, point.y + pad]];
  let best = null, bestD = Infinity;
  for (const f of map.queryRenderedFeatures(box, { layers: ['dots'] })) {
    const p = map.project(f.geometry.coordinates);
    const d = Math.hypot(p.x - point.x, p.y - point.y);
    if (d < bestD) { bestD = d; best = f; }
  }
  return best ? candById.get(best.properties.id) : null;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function updateDots() {
  const src = map?.getSource('items');
  if (!src) return;
  src.setData({
    type: 'FeatureCollection',
    features: candidates.map(r => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [r.lng, r.lat] },
      properties: { id: r.id, c: r.cat, s: r.prio, st: r.standing && !r.isNew ? 1 : 0 },
    })),
  });
}

function placePins() {
  if (!map) return;
  pins.place(candidates, state.selected?.world ? null : state.selected, obstacles());
  if (hoverId != null && hoverFromPin && !pins.active.has(hoverId)) hideHover();
}

function onMoveEnd() {
  placePins();
  updateList();
  writeHash();
  scheduleUpdate(); // the view may need different files or a different level of detail
}

// ---------------------------------------------------------------------------
// Sidebar list

const updateList = debounce(renderList, 120);

// The list is often out of sight: under an open article, or on phones in a
// sheet at peek height or under search results. Rendering it then would be
// wasted work on every map move, so it waits until it shows.
let listStale = false;
function listHidden() {
  const b = document.body.classList;
  if (b.contains('reading')) return true;
  return !!sheet?.active && !sheet.drag?.live && (sheet.state === 'peek' || b.contains('searching'));
}
function showListIfStale() {
  if (listStale && !listHidden()) renderList();
}

// Rows of the last render by record, reused while their record stays
// listed: building rows and their images is most of a render's cost.
let listRows = new Map();

function inView(r, b, globe) {
  if (globe && map && map.getZoom() < 2.5) {
    return !(map.transform.isLocationOccluded && map.transform.isLocationOccluded({ lng: r.lng, lat: r.lat }));
  }
  if (r.lat < b.getSouth() || r.lat > b.getNorth()) return false;
  let lng = r.lng;
  const w = b.getWest(), e = b.getEast();
  if (e - w >= 360) return true;
  if (lng < w) lng += 360; else if (lng > e) lng -= 360;
  return lng >= w && lng <= e;
}

function renderList() {
  if (listHidden()) { listStale = true; return; }
  listStale = false;
  const [a, b] = range();
  // Before the map exists the list still fills in, from the estimated view.
  const bounds = map ? map.getBounds() : estimatedBounds();
  const globe = map ? map.getProjection()?.type === 'globe' : state.globe;
  const visible = candidates.filter(r => inView(r, bounds, globe));
  $('#list-title').textContent = span() === 0 ? fmtYear(state.year) : fmtRange(a, b);
  const zoom = map ? map.getZoom() : startZoom;
  const zoomHint = visible.length && zoom < STANDING_ZOOM - 0.5 && state.standing ? ' · zoom in for more' : '';
  $('#list-sub').textContent = `${visible.length.toLocaleString()} ${visible.length === 1 ? 'article' : 'articles'} in view${zoomHint}`;
  // Events of these years spread over many places (the world wars, the
  // Napoleonic Wars), which have no pin: listed while one of their places is in view.
  // Short, sharp events beat long eras (the Middle Ages) at a given notability.
  const world = store.world.filter(r => r.start <= b && r.end >= a && r.end - r.start <= WORLD_MAX_SPAN && state.cats.has(r.cat)
    && (r.pts.length ? r.pts.some(([lat, lng]) => inView({ lat, lng }, bounds, globe)) : true))
    .sort((x, y) => worldRank(y) - worldRank(x)).slice(0, 3);
  const strip = $('#list-world');
  strip.hidden = !world.length;
  setChildren(strip, world.map(r => {
    const icon = el('span', { class: 'globe', 'aria-hidden': 'true' });
    icon.innerHTML = GLOBE_SVG;
    const btn = el('button', { class: 'world-chip', style: `--c:${catColor(r.cat)}`, title: metaLine(r) ? `${r.title}, ${metaLine(r)}` : r.title },
      icon, el('span', {}, r.title));
    btn.addEventListener('click', () => select(r));
    return btn;
  }));
  const list = $('#list');
  if (!visible.length) {
    const none = !state.cats.size;
    listRows = new Map();
    list.replaceChildren(el('li', { class: 'list-empty' },
      el('strong', {}, none ? 'Every category is off' : 'Nothing recorded here yet'),
      none ? el('button', { class: 'btn', onclick: () => setCats(CATEGORIES.flatMap((c, i) => (c.off ? [] : [i]))) }, 'Show them again')
        : 'Try zooming out, moving the timeline, or widening the time window.'));
    return;
  }
  const shown = visible.slice(0, 120);
  const rows = new Map(shown.map(r => [r, listRows.get(r) || listItem(r)]));
  const more = visible.length > shown.length;
  // Same rows in the same order (a small pan, a step of the timeline): leave the DOM alone.
  const same = rows.size === listRows.size && [...rows.keys()].every((r, i) => list.children[i] === listRows.get(r))
    && !!list.querySelector(':scope > .list-more') === more;
  listRows = rows;
  if (same) return;
  list.replaceChildren(...rows.values());
  if (more) {
    list.append(el('li', { class: 'list-more' }, `Showing the ${shown.length} most notable. Zoom in to see more.`));
  }
}

const WORLD_MAX_SPAN = 400; // years; longer eras are periods, not events to point at
const worldRank = r => r.score / (1 + Math.max(0, r.end - r.start - 30) / 60);
const GLOBE_SVG = '<svg viewBox="0 0 24 24" width="13" height="13"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.8 5.2 3.8 8.5s-1.2 6.1-3.8 8.5c-2.6-2.4-3.8-5.2-3.8-8.5s1.2-6.1 3.8-8.5Z" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';

// List rows act as buttons: focusable, and Enter or Space opens them.
function pressable(node, fn) {
  node.tabIndex = 0;
  node.setAttribute('role', 'button');
  node.addEventListener('click', fn);
  node.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); }
  });
  return node;
}

function listItem(r) {
  const li = el('li', { style: `--c:${catColor(r.cat)}` },
    thumb(r, 96),
    el('div', { class: 'li-body' },
      el('div', { class: 'li-title' }, r.title),
      el('div', { class: 'li-meta' }, el('b', {}, metaLine(r))),
      r.desc ? el('div', { class: 'li-desc' }, r.desc) : null,
    ),
  );
  pressable(li, () => select(r, { fly: true }));
  // Hover only: on touch screens mouseenter fires on a tap and nothing ever leaves.
  if (HOVER.matches) {
    li.addEventListener('mouseenter', () => { pins?.setHighlight(r.id); pulse(r); fetchSummary(r.title); });
    li.addEventListener('mouseleave', () => { pins?.setHighlight(null); pulse(null); });
  }
  return li;
}

function thumb(r, w) {
  const t = el('div', { class: 'thumb', style: `--c:${catColor(r.cat)}` });
  if (r.img) {
    t.classList.add('has-img');
    const img = wikiImg(r.img, w);
    img.addEventListener('error', () => { if (!img.isConnected) t.classList.remove('has-img'); });
    if (r.kind === KIND.BORN || r.kind === KIND.DIED) img.style.objectPosition = 'center 20%';
    t.append(img);
  }
  return t;
}

let pulseMarker = null;
function pulse(r) {
  pulseMarker?.remove();
  pulseMarker = null;
  if (!r || !map || r.world) return;
  const node = el('div', { class: 'pin' }, el('div', { class: 'pulse', style: `--c:${catColor(r.cat)}` }));
  pulseMarker = new maplibregl.Marker({ element: node, anchor: 'center', opacityWhenCovered: '0' }).setLngLat([r.lng, r.lat]).addTo(map);
}

// ---------------------------------------------------------------------------
// Hover card

let hoverTimer = null;
let hoverId = null, hoverFromPin = false;

function showHover(r, node, point) {
  clearTimeout(hoverTimer);
  hoverId = r.id;
  hoverFromPin = !!node;
  hoverTimer = setTimeout(() => {
    const card = $('#hovercard');
    const people = r.kind === KIND.BORN || r.kind === KIND.DIED;
    card.className = `hovercard${people ? ' people' : ''}`;
    card.style.setProperty('--c', catColor(r.cat));
    setChildren(card,
      r.img ? hoverImage(r.img) : null,
      el('div', { class: 'hc-body' },
        el('div', { class: 'badge' }, el('span', { class: 'dot' }), categoryLabel(r)),
        el('div', { class: 'hc-title' }, r.title),
        el('div', { class: 'hc-date' }, metaLine(r)),
        r.desc ? el('div', { class: 'hc-desc' }, r.desc) : null,
        el('div', { class: 'hc-hint' }, 'Click to read'),
      ),
    );
    card.hidden = false;
    fetchSummary(r.title); // a hover usually comes before a click: have the text ready
    // Beside the pin and its label, never over them; on the right if it fits.
    let left, right, y;
    if (node) {
      const boxes = [...node.querySelectorAll('.pin-label, .pin-photo, .pin-dot')].map(e => e.getBoundingClientRect());
      left = Math.min(...boxes.map(b => b.left)) - 10;
      right = Math.max(...boxes.map(b => b.right)) + 10;
      y = Math.min(...boxes.map(b => b.top)) - 20;
    } else {
      const c = map.getCanvas().getBoundingClientRect();
      left = c.left + point.x - 14; right = c.left + point.x + 14; y = c.top + point.y - 20;
    }
    const w = 280, h = card.offsetHeight;
    const x = right + w <= innerWidth - 12 || left - w < 12 ? right : left - w;
    card.style.left = `${clamp(x, 12, innerWidth - w - 12)}px`;
    card.style.top = `${clamp(y, 12, innerHeight - h - 12)}px`;
  }, node ? 90 : 40);
}

// The 120px thumb (already cached by the pin) shows until the sharp one
// lands; if neither loads, the image area goes rather than sit there grey.
function hoverImage(path) {
  const box = el('div', { class: 'hc-img', style: `background-image:url("${thumbUrl(path, 330)}"),url("${thumbUrl(path, 120)}")` });
  const probe = new Image();
  probe.onerror = () => box.remove();
  probe.src = thumbUrl(path, 120);
  return box;
}

function hideHover() {
  clearTimeout(hoverTimer);
  hoverId = null;
  $('#hovercard').hidden = true;
}

function categoryLabel(r) {
  if (r.standing && !r.isNew) return 'Place';
  return CATEGORIES[r.cat].name;
}

// ---------------------------------------------------------------------------
// Article view

let articleSeq = 0;

// Clicking the open item again closes it.
function toggle(r) {
  if (state.selected?.id === r.id) closeArticle();
  else select(r);
}

function select(r, { fly = false, zoom = null } = {}) {
  openSeq++;
  hideHover();
  state.selected = r;
  showArticle(r);
  if (map && !history.state?.article) {
    history.replaceState({ ...history.state, base: true }, ''); // the entry Back returns to
    history.pushState({ article: true }, '', currentHash());
  }
  if (!map) {
    // Clicked in the list before the map is up: it opens on the item when ready.
    if (!r.world) { state.center = [r.lng, r.lat]; state.zoom = Math.max(state.zoom ?? DEFAULT_VIEW.zoom, 5); }
    return;
  }
  pins.setSelected(r.id);
  if (r.world) {
    // No one place to pin: show the part of the world it happened across.
    if (fly) {
      const pts = r.pts?.length ? r.pts : [[r.lat, r.lng]];
      const lats = pts.map(q => q[0]), lngs = pts.map(q => q[1]);
      const w = Math.min(...lngs), e = Math.max(...lngs);
      if (e - w > 150 || Math.max(...lats) - Math.min(...lats) > 80) {
        map.flyTo({ center: [r.lng, r.lat], zoom: Math.min(map.getZoom(), 1.6), duration: 1600 });
      } else {
        map.fitBounds([[w, Math.min(...lats)], [e, Math.max(...lats)]], { padding: 60, maxZoom: 5, duration: 1600 });
      }
    } else {
      placePins();
    }
    writeHash();
    return;
  }
  const z = zoom ?? Math.min(Math.max(map.getZoom(), r.kind === KIND.EVENT ? 7 : 9), 13);
  if (fly) {
    map.flyTo({ center: [r.lng, r.lat], zoom: z, duration: 1600 }); // not essential: reduced motion jumps
  } else if (sheet.active) {
    // The sheet now covers the bottom half: bring the pin into the free part.
    map.easeTo({ center: [r.lng, r.lat], duration: 500 });
  } else {
    placePins();
  }
  writeHash();
}

// Keep the map's visual centre in the part not covered by the panels.
// animate: glide along with the phone sheet (not on the first layout).
function syncPadding(animate = true) {
  obstacleCache = null;
  if (!map) return;
  const padding = { top: 0, right: 0, ...panelInsets() };
  if (sheet.active) {
    if (map.getPadding().bottom === padding.bottom) return;
    // Selecting flies right after this, with the new padding: set it now.
    if (state.selected || !animate) map.setPadding(padding);
    else map.easeTo({ padding, duration: 420 });
    return;
  }
  map.setPadding(padding);
}

// How much of the screen's left and bottom the panels cover.
function panelInsets() {
  if (sheet.active) {
    // Use where the sheet is going, not where it is mid-slide. A full sheet
    // keeps the half-sheet padding, so the selected pin stays on screen below
    // the controls instead of in the strip at the top.
    const tl = sheet.state === 'peek' ? $('#timeline').offsetHeight + 10 : 0;
    return { left: 0, bottom: Math.min(sheet.visible(), sheet.visible('half')) + tl };
  }
  const collapsed = document.body.classList.contains('collapsed');
  const sb = $('#sidebar').getBoundingClientRect();
  const tl = $('#timeline').getBoundingClientRect();
  const sideSheet = !collapsed && sb.top < innerHeight / 3; // desktop: panel on the left
  let bottomEdge = tl.top;
  if (!collapsed && !sideSheet) bottomEdge = Math.min(bottomEdge, sb.top);
  return { left: sideSheet ? Math.max(0, sb.right) : 0, bottom: Math.max(0, innerHeight - bottomEdge) };
}

// The first view shows the whole globe, so it's plainly a planet to spin, on
// any screen: the zoom at which it fills about 90% of the free area (up to
// zoom 3, for very big screens).
function globeZoom() {
  const { left, bottom } = panelInsets();
  const r = Math.max(80, Math.min(innerWidth - left, innerHeight - bottom) * 0.45);
  const c = 1.5 * innerHeight; // MapLibre's camera distance: a 36.87° field of view
  const R = (r * r + r * Math.hypot(r, c)) / c; // the radius that perspective shrinks to r
  const lat = (DEFAULT_VIEW.center[1] * Math.PI) / 180;
  return Math.min(3, Math.log2((R * 2 * Math.PI * Math.cos(lat)) / 512));
}

// Screen rects that pins must not sit under. Measuring forces layout, so the
// result is cached until the window or the panels change size.
let obstacleCache = null;
function obstacles() {
  if (obstacleCache) return obstacleCache;
  const out = [];
  for (const id of ['sidebar', 'timeline']) {
    if (id === 'sidebar' && !sheet.active && document.body.classList.contains('collapsed')) continue;
    if (id === 'timeline' && sheet.active && sheet.state !== 'peek') continue;
    const r = document.getElementById(id).getBoundingClientRect();
    if (r.width && r.height) out.push([r.left, r.top, r.right, r.bottom]);
  }
  const pill = $('.brand-pill').getBoundingClientRect();
  if (pill.width) out.push([pill.left, pill.top, pill.right, pill.bottom]);
  const c = $('.controls').getBoundingClientRect();
  out.push([c.left, c.top, c.right, c.top + 140]);
  return (obstacleCache = out);
}
addEventListener('resize', () => { obstacleCache = null; });

function closeArticle({ fromHistory = false } = {}) {
  openSeq++;
  state.selected = null;
  pins?.setSelected(null); // the list works before the map is up
  document.body.classList.remove('reading');
  sheet.allow(['peek', 'half', 'full']);
  if (sheet.active) sheet.snap('peek');
  $('#article-view').hidden = true;
  $('#list-view').hidden = false;
  showListIfStale();
  placePins();
  // Closed on screen: step back over the entry the article added.
  if (!fromHistory && history.state?.article) history.back();
  writeHash();
}

function showArticle(r) {
  const seq = ++articleSeq;
  document.body.classList.add('reading');
  if (sheet.active) {
    sheet.allow(['half', 'full']);
    sheet.snap('half');
  } else if (document.body.classList.contains('collapsed')) {
    setCollapsed(false);
  }
  $('#list-view').hidden = true;
  $('#article-view').hidden = false;
  $('#article-view').scrollTop = 0;
  const people = r.kind === KIND.BORN || r.kind === KIND.DIED;
  const hero = r.img
    ? el('div', { class: `hero${people ? ' portrait' : ''}`, style: `background-image:url("${thumbUrl(r.img, 120)}")` })
    : null;
  if (hero) {
    const img = wikiImg(r.img, 500, { loading: 'eager', sizes: '(max-width: 860px) 92vw, 360px', fetchpriority: 'high' });
    img.addEventListener('load', () => img.classList.add('loaded'));
    img.addEventListener('error', () => { if (!img.isConnected) hero.remove(); });
    hero.append(img);
  }
  const prose = el('div', { class: 'prose' }, el('div', { class: 'skeleton' }), el('div', { class: 'skeleton' }), el('div', { class: 'skeleton short' }));
  const readMore = el('button', { class: 'btn' }, 'Continue reading');
  const article = $('#article');
  article.style.setProperty('--c', catColor(r.cat));
  setChildren(article,
    hero,
    el('div', { class: 'badge' }, el('span', { class: 'dot' }), categoryLabel(r)),
    el('h2', { tabindex: '-1' }, r.title),
    el('div', { class: 'a-date' }, metaLine(r)),
    r.desc ? el('p', { class: 'a-desc' }, r.desc) : null,
    prose,
    el('div', { class: 'a-actions' },
      readMore,
      el('a', { class: 'btn primary', href: wikiUrl(r.title), target: '_blank', rel: 'noopener' }, 'Open in Wikipedia ↗'),
    ),
    el('div', { class: 'a-nearby' }, nearbySection(r)),
    // CC BY-SA wants the licence linked and changes noted; Commons images
    // credit their author and licence on the file page.
    el('p', { class: 'credit' }, 'Text adapted from ', el('a', { href: wikiUrl(r.title), target: '_blank', rel: 'noopener' }, 'Wikipedia'),
      ' under ', el('a', { href: 'https://creativecommons.org/licenses/by-sa/4.0/', target: '_blank', rel: 'license noopener' }, 'CC BY-SA 4.0'), '. ',
      r.img ? ['Image: ', el('a', { href: `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(r.img.slice(r.img.lastIndexOf('/') + 1))}`, target: '_blank', rel: 'noopener' }, 'Wikimedia Commons'), '. '] : null,
      el('a', { href: `https://www.wikidata.org/wiki/Q${r.id}`, target: '_blank', rel: 'noopener' }, `Wikidata Q${r.id}`), '.'),
  );

  let full = false; // the full article is in: a late summary mustn't replace it
  const loadSummary = () => fetchSummary(r.title).then(s => {
    if (seq !== articleSeq || full) return;
    if (s?.extract_html) {
      prose.innerHTML = s.extract_html;
    } else {
      // The description is already shown above; just offer another try.
      const retry = el('button', { class: 'link-btn' }, 'Try again');
      retry.addEventListener('click', () => {
        setChildren(prose, el('div', { class: 'skeleton' }), el('div', { class: 'skeleton short' }));
        loadSummary();
      });
      setChildren(prose, el('p', { class: 'a-desc' }, 'Couldn’t reach Wikipedia for the summary. ', retry));
    }
    // Only free images: a thumbnail hosted on Wikipedia itself is a fair-use
    // one, licensed for Wikipedia alone.
    if (!r.img && s?.thumbnail?.source?.includes('/wikipedia/commons/') && !article.querySelector('.hero')) {
      article.prepend(el('div', { class: 'hero' }, el('img', { src: s.thumbnail.source, alt: '', class: 'loaded' })));
    }
  });
  loadSummary();
  readMore.addEventListener('click', async () => {
    readMore.disabled = true;
    readMore.textContent = 'Loading…';
    const html = await fetchArticle(r.title);
    if (seq !== articleSeq) return;
    if (html) {
      full = true;
      prose.innerHTML = html;
      readMore.remove();
      for (const img of prose.querySelectorAll('img')) {
        img.addEventListener('error', () => (img.closest('figure, .thumb, .tsingle') || img).remove(), { once: true });
      }
      return;
    }
    readMore.disabled = false;
    readMore.textContent = 'Couldn’t load it. Try again';
  });
}

// Other things near this one in the current window.
function nearbySection(r) {
  if (r.world) return null;
  const near = candidates
    .filter(o => o.id !== r.id && Math.abs(o.lat - r.lat) < 1 && distKm(o, r) < 40)
    .slice(0, 8);
  if (!near.length) return null;
  const [a, b] = range();
  return el('div', {},
    el('div', { class: 'section-title' }, `Nearby, ${fmtRange(a, b)}`),
    el('ul', { class: 'nearby' }, near.map(o => {
      const li = el('li', { style: `--c:${catColor(o.cat)}` }, thumb(o, 96),
        el('div', { class: 'li-body' }, el('div', { class: 'li-title' }, o.title), el('div', { class: 'li-meta' }, el('b', {}, metaLine(o)))));
      pressable(li, () => select(o, { fly: true }));
      if (HOVER.matches) {
        li.addEventListener('mouseenter', () => { pins?.setHighlight(o.id); pulse(o); });
        li.addEventListener('mouseleave', () => { pins?.setHighlight(null); pulse(null); });
      }
      return li;
    })),
  );
}

// ---------------------------------------------------------------------------
// Search, random, journeys

async function search(q) {
  const input = $('#search');
  const results = $('#results');
  if (!q.trim() && document.activeElement === input) { showSuggestions(); return; }
  if (normalize(q.trim()).length < 2) { results.hidden = true; input.setAttribute('aria-expanded', 'false'); return; }
  // The first part of the index answers at once; the whole, once it's in.
  let entries, complete = false;
  try {
    const all = store.loadSearch();
    entries = await Promise.race([all, store.loadSearchFirst()]);
    complete = entries === await Promise.race([all, Promise.resolve(null)]);
    if (!complete) all.then(() => { if (input.value === q && document.activeElement === input) search(q); }, () => {});
  } catch {
    setChildren(results, el('li', { class: 'empty' }, 'Couldn’t load search. Check your connection and try again.'));
    results.hidden = false;
    return;
  }
  // The index may have taken a while: only show results for what's still typed.
  if (input.value !== q || document.activeElement !== input) return;
  const top = rankSearch(entries, q);
  results.replaceChildren(...(top.length ? top.map((e, i) => {
    const li = el('li', { id: `result-${i}`, role: 'option', 'aria-selected': i === 0 ? 'true' : 'false', style: `--c:${catColor(e.cat)}` },
      el('span', { class: 'dot' }), el('span', { class: 'r-title' }, e.title),
      el('span', { class: 'r-meta' }, resultMeta(e)));
    li.addEventListener('mousedown', ev => { ev.preventDefault(); chooseResult(e); });
    li._entry = e;
    return li;
  }) : [el('li', { class: 'empty' }, 'No matches among notable articles')]));
  results.hidden = false;
  input.setAttribute('aria-expanded', 'true');
  input.setAttribute('aria-activedescendant', top.length ? 'result-0' : '');
}

// An empty search box offers a way in: a few journeys across the eras, and
// a random article.
const SUGGESTED = ['Ancient Egypt', 'Roman Empire', 'Viking Age', 'Mongol Empire', 'Age of Discovery', 'French Revolution', 'World War II', 'Space Race']
  .map(n => JOURNEYS.find(j => j.name === n)).filter(Boolean);
function showSuggestions() {
  const input = $('#search'), results = $('#results');
  const row = (i, title, meta, pick) => {
    const li = el('li', { id: `result-${i}`, role: 'option', 'aria-selected': 'false', style: '--c:var(--accent)' },
      el('span', { class: 'dot' }), el('span', { class: 'r-title' }, title), el('span', { class: 'r-meta' }, meta));
    li.addEventListener('mousedown', ev => { ev.preventDefault(); input.blur(); pick(); });
    li._pick = () => { input.blur(); pick(); };
    return li;
  };
  results.replaceChildren(
    el('li', { class: 'empty r-head' }, 'Journeys through history'),
    ...SUGGESTED.map((j, i) => row(i, j.name, fmtYear(j.year), () => goJourney(j))),
    row(SUGGESTED.length, 'Surprise me', 'A random article', () => $('#random').click()),
  );
  results.hidden = false;
  input.setAttribute('aria-expanded', 'true');
}

function resultMeta(e) {
  if (e.kind >= KIND.BUILT && e.kind <= KIND.ESTABLISHED) return `${KIND_VERB[e.kind]} ${e.label || fmtYear(e.start)}`;
  const when = e.kind === KIND.EVENT ? fmtRange(e.start, e.end) : `${KIND_VERB[e.kind]} ${fmtYear(e.start)}`;
  return e.loc === 'world' && e.label ? `${when} · ${e.label}` : when;
}

let choosing = false;
function chooseResult(e) {
  choosing = true;
  $('#results').hidden = true;
  $('#search').value = '';
  $('#search').blur();
  openEntry(e, { fly: true }).finally(() => {
    choosing = false;
    $('#article h2')?.focus({ preventScroll: true }); // keyboard users land on what they chose
  });
}

// Open an item known by id (a search result, Surprise me, a shared link):
// from data already loaded, else the one file that holds it (the search index
// and shared links say which), else look it up in the search index.
// Opening can wait on a file or the search index: a newer selection (or a
// close) in the meantime wins, and the late one is dropped.
let openSeq = 0;
async function openEntry(e, { fly }) {
  const seq = ++openSeq;
  let rec = store.findLoaded(e.id);
  if (!rec && e.loc) rec = await store.findRecord(e);
  if (!rec && !e.loc) {
    // An older link with no file: usually in the first view's data, on its way.
    await store.ensure(store.filesFor(currentView()));
    rec = store.findLoaded(e.id);
  }
  if (!rec) {
    const all = await store.loadSearch().catch(() => null);
    const entry = all?.find(x => x.id === e.id);
    if (entry) rec = await store.findRecord(entry);
  }
  if (!rec || seq !== openSeq) return;
  // Only move the timeline if the item isn't part of the current window.
  const isPlace = rec.kind >= KIND.BUILT && rec.kind <= KIND.ESTABLISHED;
  const [a, b] = range();
  const inWindow = isPlace ? rec.start <= b : rec.start <= b && rec.end >= a;
  if (!inWindow) setYear(rec.start);
  if (rec.standing) rec.isNew = rec.start >= range()[0];
  // Select first, so on phones the sheet is up before the flight aims the pin above it.
  select(rec, { fly, zoom: isPlace ? 13 : rec.kind === KIND.EVENT ? 8 : 9 });
}

async function randomPick() {
  const all = await store.loadSearchFirst().catch(() => []);
  const pool = all.slice(0, 6000).filter(e => state.cats.has(e.cat));
  const e = pool[Math.floor(Math.random() * pool.length)];
  if (e) openEntry(e, { fly: true });
}

function buildJourneys() {
  const box = $('#journeys');
  box.replaceChildren(...JOURNEYS.map(j => {
    const b = el('button', {}, el('b', {}, j.name), el('small', {}, fmtYear(j.year)));
    b.addEventListener('click', () => { toggleJourneys(false); goJourney(j); });
    return b;
  }));
}

function goJourney(j) {
  state.spanMode = j.span;
  syncSpanSelect();
  setYear(j.year);
  if (!j.center) return;
  if (map) map.flyTo({ center: j.center, zoom: j.zoom, duration: 2200 });
  else { state.center = j.center; state.zoom = j.zoom; }
}

function toggleJourneys(open) {
  const box = $('#journeys');
  open = open ?? box.hidden;
  box.hidden = !open;
  $('#journeys-btn').setAttribute('aria-expanded', String(open));
}

function syncSpanSelect() {
  const sel = $('#span');
  const v = String(state.spanMode);
  if (![...sel.options].some(o => o.value === v)) sel.append(el('option', { value: v }, `±${v} yrs`));
  sel.value = v;
}

// ---------------------------------------------------------------------------
// Chrome: filters, controls, timeline buttons, keyboard

function buildFilters() {
  $('#filters').replaceChildren(...CATEGORIES.map((c, i) => {
    const b = el('button', { class: 'chip', 'aria-pressed': String(state.cats.has(i)), style: `--c:${catColor(i)}`, title: c.name },
      el('span', { class: 'dot' }), c.short);
    b.addEventListener('click', e => {
      // Alt/Option-click: show only this category.
      if (e.altKey) setCats([i]);
      else { const next = new Set(state.cats); if (next.has(i)) next.delete(i); else next.add(i); setCats(next); }
    });
    return b;
  }));
}

function setCats(cats) {
  state.cats = new Set(cats);
  [...$('#filters').children].forEach((x, j) => x.setAttribute('aria-pressed', String(state.cats.has(j))));
  refresh();
}

function setCollapsed(c) {
  document.body.classList.toggle('collapsed', c);
  $('#expand').hidden = !c;
  setTimeout(() => { syncPadding(); placePins(); }, 360);
}

function bindChrome() {
  $('#zoom-in').addEventListener('click', () => map?.zoomIn());
  $('#zoom-out').addEventListener('click', () => map?.zoomOut());
  $('#back').addEventListener('click', closeArticle);
  $('#close').addEventListener('click', closeArticle);
  $('#share').addEventListener('click', share);
  $('#collapse').addEventListener('click', () => setCollapsed(true));
  $('#expand').addEventListener('click', () => setCollapsed(false));
  $('#random').addEventListener('click', randomPick);

  const layersBtn = $('#layers-btn');
  layersBtn.addEventListener('click', e => {
    e.stopPropagation();
    const open = $('#layers').hidden;
    $('#layers').hidden = !open;
    layersBtn.setAttribute('aria-expanded', String(open));
  });
  $('#journeys-btn').addEventListener('click', e => { e.stopPropagation(); toggleJourneys(); });
  document.addEventListener('click', e => {
    if (!e.target.closest('#layers')) { $('#layers').hidden = true; layersBtn.setAttribute('aria-expanded', 'false'); }
    if (!e.target.closest('#journeys')) toggleJourneys(false);
  });

  $('#opt-standing').addEventListener('change', e => { state.standing = e.target.checked; refresh(); });
  $('#opt-globe').addEventListener('change', e => {
    state.globe = e.target.checked;
    map?.setProjection({ type: state.globe ? 'globe' : 'mercator' });
    space?.schedule();
  });
  $('#opt-borders').addEventListener('change', e => {
    state.borders = e.target.checked;
    syncBorders();
  });

  const sel = $('#span');
  sel.addEventListener('change', () => {
    state.spanMode = sel.value === 'auto' ? 'auto' : Number(sel.value);
    setYear(state.year);
  });

  const yi = $('#year-input');
  yi.addEventListener('focus', () => yi.select());
  yi.addEventListener('input', sizeYearInput);
  yi.addEventListener('keydown', e => {
    if (e.key === 'Enter') { yi.blur(); }
    if (e.key === 'Escape') { yi.value = fmtYear(state.year); yi.blur(); }
  });
  yi.addEventListener('blur', () => {
    const y = parseYear(yi.value);
    if (y != null) setYear(y); else yi.value = fmtYear(state.year);
    sizeYearInput();
  });

  // Play: move forward through time at a pace that suits the era.
  let playTimer = null;
  stopPlay = () => { if (playTimer) play(); };
  const play = () => {
    if (playTimer) { clearInterval(playTimer); playTimer = null; $('#timeline').classList.remove('playing'); return; }
    $('#timeline').classList.add('playing');
    if (state.year >= MAX_YEAR - 1) setYear(-2999); // from 3000 BC, where the record gets going
    playTimer = setInterval(() => {
      const step = Math.max(1, Math.round(span() / 2));
      if (state.year + step > MAX_YEAR) return play();
      setYear(state.year + step);
    }, 900);
  };
  $('#play').addEventListener('click', play);

  const input = $('#search');
  if (innerWidth < 420) input.placeholder = 'Search places, events…'; // the full one gets cut off
  const doSearch = debounce(() => search(input.value), 110);
  input.addEventListener('input', doSearch);
  let before = null; // sheet state to return to after searching (phones)
  input.addEventListener('focus', () => {
    store.loadSearch().catch(() => {});
    if (input.value) search(input.value); else showSuggestions();
    // Before the snap: the list under the results needn't render for it.
    document.body.classList.add('searching');
    if (sheet.active && sheet.state !== 'full') { before = sheet.state; sheet.snap('full'); }
  });
  input.addEventListener('blur', () => setTimeout(() => {
    $('#results').hidden = true;
    document.body.classList.remove('searching');
    if (before && !choosing && !state.selected && sheet.state === 'full') sheet.snap(before);
    before = null;
    showListIfStale();
  }, 120));
  input.addEventListener('keydown', e => {
    const items = [...$('#results').querySelectorAll('li[role=option]')];
    const cur = items.findIndex(li => li.getAttribute('aria-selected') === 'true');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = clamp(cur + (e.key === 'ArrowDown' ? 1 : -1), 0, items.length - 1);
      items.forEach((li, i) => li.setAttribute('aria-selected', String(i === n)));
      if (items[n]) input.setAttribute('aria-activedescendant', items[n].id);
    } else if (e.key === 'Enter' && items[cur]) {
      if (items[cur]._pick) items[cur]._pick(); else chooseResult(items[cur]._entry);
    } else if (e.key === 'Escape') {
      input.value = '';
      $('#results').hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.blur();
    }
  });

  document.addEventListener('keydown', e => {
    if (e.target.closest('input, select, textarea')) return;
    if (e.key === '/') { e.preventDefault(); input.focus(); }
    if (e.key === 'Escape') {
      // Popovers first, then the article.
      if (!$('#journeys').hidden || !$('#layers').hidden) {
        toggleJourneys(false);
        $('#layers').hidden = true;
        $('#layers-btn').setAttribute('aria-expanded', 'false');
      } else if (state.selected) closeArticle();
    }
    // e.code: with Shift held, e.key is "{" or "}" on many layouts.
    if (e.code === 'BracketLeft' || e.code === 'BracketRight') {
      setYear(state.year + (e.code === 'BracketRight' ? 1 : -1) * (e.shiftKey ? 10 : 1));
    }
  });
}

// ---------------------------------------------------------------------------
// URL state: #y=1776&w=auto&m=41.2,-73.2,5.6&a=123

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const y = parseInt(p.get('y'), 10);
  if (!Number.isNaN(y)) state.year = clamp(y, MIN_YEAR, MAX_YEAR);
  const w = p.get('w');
  if (w) {
    const n = parseInt(w, 10);
    state.spanMode = w === 'auto' || Number.isNaN(n) ? 'auto' : clamp(n, 0, 1000);
  }
  const m = (p.get('m') || '').split(',').map(Number);
  if (m.length === 3 && m.every(Number.isFinite)) {
    state.center = [((m[1] + 540) % 360) - 180, clamp(m[0], -85, 85)];
    state.zoom = clamp(m[2], 0, 20);
  } else if (map) state.center = null; // a pasted link without a position keeps the current view
  const a = parseInt(p.get('a'), 10);
  state.pendingSelect = a > 0 ? a : null;
  state.pendingFile = p.get('f') || null;
  if (state.spanMode !== 'auto') queueMicrotask(syncSpanSelect);
}

// A link pasted into an open tab: go there.
function onHashChange() {
  if (location.hash === traversed) { traversed = null; return; }
  if (location.hash === currentHash()) return;
  const was = state.selected?.id;
  readHash();
  syncSpanSelect();
  setYear(state.year);
  if (state.center) map.jumpTo({ center: state.center, zoom: state.zoom });
  if (state.pendingSelect && state.pendingSelect !== was) openEntry({ id: state.pendingSelect, loc: state.pendingFile }, { fly: false });
  else if (!state.pendingSelect && state.selected) closeArticle();
}

function currentHash() {
  const p = new URLSearchParams();
  p.set('y', state.year);
  p.set('w', state.spanMode);
  if (map) {
    const c = map.getCenter();
    p.set('m', `${c.lat.toFixed(4)},${c.lng.toFixed(4)},${map.getZoom().toFixed(2)}`);
  }
  if (state.selected) {
    p.set('a', state.selected.id);
    // The file holding it: opening the link then needs no search index.
    if (state.selected.file) p.set('f', state.selected.file);
  }
  return '#' + p.toString().replace(/%2C/g, ',').replace(/%2F/g, '/');
}

const writeHash = debounce(() => {
  if (map) history.replaceState(history.state, '', currentHash());
}, 300);

// Opening an article adds a history entry, so Back (or Android's back
// gesture) closes it instead of leaving the site.
// Any other step (a pasted link, Forward) is applied by onHashChange.
let traversed = null; // a hash whose history step was handled already
function onPopState() {
  if (!history.state?.base) return;
  traversed = location.hash;
  if (state.selected) closeArticle({ fromHistory: true });
  writeHash();
}

// Share the open article: the system share sheet where there is one (phones,
// most in-app browsers), else copy the link.
async function share() {
  const r = state.selected;
  if (!r) return;
  const url = location.href.split('#')[0] + currentHash();
  const data = { title: `${r.title} | Geopedia`, text: `${r.title}, ${metaLine(r)}`, url };
  if (navigator.share) {
    try { await navigator.share(data); } catch { /* dismissed */ }
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    toast('Link copied');
  } catch {
    prompt('Copy this link', url);
  }
}

// ---------------------------------------------------------------------------
// Toast

let toastTimer = null;
function toast(msg, ms = 4000) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  if (ms) toastTimer = setTimeout(hideToast, ms);
}
function hideToast() { $('#toast').hidden = true; }

// Boot last, so every module-level binding above is initialised.
init().catch(err => {
  console.error(err);
  toast('Geopedia couldn’t load. Check your connection and reload the page.', 0);
});
