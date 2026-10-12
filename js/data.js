// Loads the level-of-detail data pyramid (see scripts/build_data.py) and
// answers "what's in this view": which files it needs and which records they
// hold for the current time window and zoom.

import { STANDING_ZOOM } from './config.js';

const BASE = 'data/';
const MAX_DETAIL_FILES = 24;

// Array record -> object. Layout documented in scripts/build_data.py.
function toRecord(a, standing) {
  return {
    id: a[0], title: a[1], lat: a[2], lng: a[3], start: a[4], end: a[5],
    cat: a[6], kind: a[7], score: a[8], img: a[9], desc: a[10], date: a[11], place: a[12],
    minzoom: standing ? 0 : a[13], standing,
  };
}

// Web Mercator tile coordinate (fractional) for a lng/lat at zoom z.
function tileX(lng, z) { return ((lng + 180) / 360) * 2 ** z; }
function tileY(lat, z) {
  const r = (Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z;
}

// Keys "x-y" of the grid tiles at zoom z that a [w, s, e, n] box touches.
function gridKeys([w, s, e, n], z) {
  const size = 2 ** z;
  if (z === 0) return ['0-0'];
  const keys = [];
  const x0 = Math.floor(tileX(w, z)), x1 = Math.floor(tileX(Math.min(e, w + 360), z));
  const y0 = Math.max(0, Math.floor(tileY(n, z))), y1 = Math.min(size - 1, Math.floor(tileY(s, z)));
  for (let x = x0; x <= x1 && x - x0 < size; x++) {
    for (let y = y0; y <= y1; y++) keys.push(`${((x % size) + size) % size}-${y}`);
  }
  return keys;
}

function boxHits(entries, [w, s, e, n], limit) {
  // Normalise to [-180, 180] and split boxes that cross the antimeridian.
  const boxes = e - w >= 360 ? [[-180, s, 180, n]]
    : [[w, s, e, n]].flatMap(([a, b, c, d]) => {
      const a2 = ((a + 540) % 360) - 180, c2 = a2 + (c - a);
      return c2 > 180 ? [[a2, b, 180, d], [-180, b, c2 - 360, d]] : [[a2, b, c2, d]];
    });
  const out = [];
  for (const [key, x0, y0, x1, y1] of entries) {
    if (boxes.some(([bw, bs, be, bn]) => x1 >= bw && x0 <= be && y1 >= bs && y0 <= bn)) out.push(key);
    if (out.length >= limit) break;
  }
  return out;
}

export class Store {
  constructor() {
    this.index = null;
    this.version = '';
    this.files = new Map(); // path -> records[] | Promise
    this.long = [];
    this.world = []; // events with no one place (world wars): listed, never pinned
    this.search = null;
    this.onLoad = () => {};
  }

  // indexPromise lets the page start fetching index.json before modules load.
  async init(indexPromise) {
    this.index = await (indexPromise || this.fetchRaw('index', false));
    this.version = this.index.version;
    this.longReady = this.fetchRaw('long').then(rows => { this.long = rows.map(a => toRecord(a, false)); this.onLoad(); });
    this.worldReady = this.fetchRaw('world', true, 'low')
      .then(rows => { this.world = rows.map(a => ({ ...toRecord(a, false), world: true })); this.onLoad(); })
      .catch(() => {});
  }

  url(path, versioned = true) {
    return `${BASE}${path}.json${versioned ? `?v=${this.version}` : ''}`;
  }

  async fetchRaw(path, versioned = true, priority = 'auto') {
    const res = await fetch(this.url(path, versioned), { priority });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  // Every file a view needs. view = { bounds: [w, s, e, n], zoom, a, b, standing }
  filesFor({ bounds, zoom, a, b, standing }) {
    const out = [];
    const lo = a - this.index.longSpan;
    const zmax = displayZoom(zoom);
    const tiers = Object.entries(this.index.tiers);
    for (const [name, t] of tiers) {
      if (t.minz > zmax) continue;
      for (const key of gridKeys(bounds, t.zoom)) {
        const chunks = t.tiles[key];
        if (!chunks) continue;
        chunks.forEach(([from, to], i) => { if (to >= lo && from <= b) out.push(`${name}/${key}-${i}`); });
      }
    }
    if (zmax >= this.index.detailMinz) {
      for (const key of boxHits(this.index.detail, bounds, MAX_DETAIL_FILES)) out.push(`d/${key}`);
    }
    if (standing && zoom >= STANDING_ZOOM - 0.5) {
      for (const key of boxHits(this.index.standing, bounds, MAX_DETAIL_FILES)) out.push(`p/${key}`);
    }
    return out;
  }

  get(path) {
    const v = this.files.get(path);
    return Array.isArray(v) ? v : null;
  }

  // low: a prefetch, which must never slow down what's on screen.
  load(path, low = false) {
    if (!this.files.has(path)) {
      const standing = path.startsWith('p/');
      const p = this.fetchRaw(path, true, low ? 'low' : 'auto').then(rows => {
        const recs = rows.map(a => toRecord(a, standing));
        this.files.set(path, recs);
        return recs;
      }).catch(err => { this.files.delete(path); throw err; })
        .finally(() => this.onLoad());
      this.files.set(path, p);
    }
    return Promise.resolve(this.files.get(path));
  }

  ensure(paths) {
    return Promise.all(paths.map(p => this.load(p).catch(() => null)));
  }

  isLoaded(paths) {
    return paths.every(p => this.get(p));
  }

  // Records of the given files that fall in [a, b] and show at this zoom.
  // Standing places that existed come back with isNew set.
  *records(paths, a, b, zoom) {
    const zmax = displayZoom(zoom);
    for (const r of this.long) if (r.start <= b && r.end >= a && r.minzoom <= zmax) yield r;
    for (const path of paths) {
      const recs = this.get(path);
      if (!recs) continue;
      for (const r of recs) {
        if (r.start > b || r.end < a || r.minzoom > zmax) continue;
        if (r.standing) r.isNew = r.start >= a;
        yield r;
      }
    }
  }

  // Warm the time chunks just before and after the window, for every tile in
  // view, so scrubbing the timeline rarely waits on the network.
  prefetchAround(view) {
    const lo = view.a - this.index.longSpan;
    const zmax = displayZoom(view.zoom);
    for (const [name, t] of Object.entries(this.index.tiers)) {
      if (t.minz > zmax) continue;
      for (const key of gridKeys(view.bounds, t.zoom)) {
        const chunks = t.tiles[key];
        if (!chunks) continue;
        const hit = chunks.map(([from, to], i) => (to >= lo && from <= view.b ? i : -1)).filter(i => i >= 0);
        if (!hit.length) continue;
        for (const i of [hit[0] - 1, hit[hit.length - 1] + 1]) {
          if (i >= 0 && i < chunks.length) this.load(`${name}/${key}-${i}`, true).catch(() => {});
        }
      }
    }
  }

  // On a fast connection, quietly fetch every world-level chunk, so scrubbing
  // the timeline zoomed out never waits. Skipped on slow or metered links.
  prefetchWorld() {
    const c = navigator.connection;
    if (c && (c.saveData || c.effectiveType !== '4g' || c.downlink < 5)) return;
    if (matchMedia('(pointer: coarse)').matches) return; // phones: save data and battery
    const chunks = this.index.tiers.a.tiles['0-0'] || [];
    let i = 0;
    const next = () => {
      while (i < chunks.length && this.files.has(`a/0-0-${i}`)) i++;
      if (i >= chunks.length) return;
      this.load(`a/0-0-${i++}`, true).catch(() => {}).then(() => idle(next));
    };
    setTimeout(() => idle(next), 5000); // after images and the first interactions
  }

  loadHist() {
    return this.fetchRaw('hist');
  }

  loadSearch() {
    if (!this.search) {
      this.search = this.fetchRaw('search').then(rows => rows.map(a => ({
        id: a[0], title: a[1], lat: a[2], lng: a[3], start: a[4], end: a[5], cat: a[6], kind: a[7], loc: a[8],
        norm: normalize(a[1]),
      })));
    }
    return this.search;
  }

  // Find a record by id in the file the search index says holds it.
  async findRecord(entry) {
    if (entry.loc === 'long') { await this.longReady; return this.long.find(r => r.id === entry.id) || null; }
    if (entry.loc === 'world') { await this.worldReady; return this.world.find(r => r.id === entry.id) || null; }
    const recs = await this.load(entry.loc).catch(() => null);
    return recs?.find(r => r.id === entry.id) || null;
  }

  // Standing record for a place, from the leaves around a point.
  async findStanding(id, lng, lat) {
    const keys = boxHits(this.index.standing, [lng, lat, lng, lat], 4);
    const recs = (await Promise.all(keys.map(k => this.load(`p/${k}`).catch(() => [])))).flat();
    return recs.find(r => r.id === id) || null;
  }
}

// Records show from their minzoom onwards, one level early so views feel full.
export function displayZoom(zoom) {
  return Math.floor(zoom) + 1;
}

export function normalize(s) {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

function idle(fn) {
  (window.requestIdleCallback || (f => setTimeout(f, 200)))(fn, { timeout: 3000 });
}
