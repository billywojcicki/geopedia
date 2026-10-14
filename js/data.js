// Loads the level-of-detail data pyramid (see scripts/build_data.py) and
// answers "what's in this view": which files it needs and which records they
// hold for the current time window and zoom.

import { STANDING_ZOOM } from './config.js';

const BASE = 'data/';
const MAX_DETAIL_FILES = 24;
const KEEP_LEAVES = 150; // detail and place files kept in memory, least recently used dropped first
const RETRY_MS = [2000, 8000, 30000]; // a file that failed waits this long before another try

// Array record -> object. Layout documented in scripts/build_data.py. `file`
// is where it came from, so a shared link can fetch just that file.
function toRecord(a, standing, file) {
  return {
    id: a[0], title: a[1], lat: a[2], lng: a[3], start: a[4], end: a[5],
    cat: a[6], kind: a[7], score: a[8], img: a[9], desc: a[10], date: a[11], place: a[12],
    minzoom: standing ? 0 : a[13], standing, file,
  };
}

const isLeaf = path => path.startsWith('d/') || path.startsWith('p/');

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

// Keys of the boxes [key, w, s, e, n] that touch [w, s, e, n], nearest to its
// centre first, at most `limit` of them (the middle of the screen matters most).
function boxHits(entries, [w, s, e, n], limit) {
  // Normalise to [-180, 180] and split boxes that cross the antimeridian.
  const boxes = e - w >= 360 ? [[-180, s, 180, n]]
    : [[w, s, e, n]].flatMap(([a, b, c, d]) => {
      const a2 = ((a + 540) % 360) - 180, c2 = a2 + (c - a);
      return c2 > 180 ? [[a2, b, 180, d], [-180, b, c2 - 360, d]] : [[a2, b, c2, d]];
    });
  const cx = ((((w + e) / 2) + 540) % 360) - 180, cy = (s + n) / 2;
  const hits = [];
  for (const [key, x0, y0, x1, y1] of entries) {
    if (!boxes.some(([bw, bs, be, bn]) => x1 >= bw && x0 <= be && y1 >= bs && y0 <= bn)) continue;
    let dx = Math.abs((x0 + x1) / 2 - cx);
    if (dx > 180) dx = 360 - dx;
    hits.push([dx * dx + ((y0 + y1) / 2 - cy) ** 2, key]);
  }
  hits.sort((p, q) => p[0] - q[0]);
  return hits.slice(0, limit).map(h => h[1]);
}

export class Store {
  constructor() {
    this.index = null;
    this.version = '';
    this.files = new Map(); // path -> records[] | Promise
    this.failed = new Map(); // path -> [failures, time of the last one]
    this.long = [];
    this.world = []; // events with no one place (world wars): listed, never pinned
    this.search = null;
    this.onLoad = () => {};
  }

  // indexPromise lets the page start fetching index.json before modules load.
  async init(indexPromise) {
    // One retry: a dropped request at boot shouldn't leave a dead page.
    this.index = await (indexPromise || this.fetchRaw('index', false)).catch(() => this.fetchRaw('index', false));
    this.version = this.index.version;
    this.longReady = this.fetchRaw('long').then(rows => { this.long = rows.map(a => toRecord(a, false, 'long')); this.onLoad(); })
      .catch(() => {});
    this.worldReady = this.fetchRaw('world', true, 'low')
      .then(rows => { this.world = rows.map(a => ({ ...toRecord(a, false, 'world'), world: true, pts: a[14] || [] })); this.onLoad(); })
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
    const detail = zmax >= this.index.detailMinz;
    for (const [name, t] of tiers) {
      if (t.minz > zmax) continue;
      // Zoomed into a city, the detail leaves hold everything below the world tier.
      if (detail && t.minz > 0 && this.index.leavesHoldAll) continue;
      for (const key of gridKeys(bounds, t.zoom)) {
        const chunks = t.tiles[key];
        if (!chunks) continue;
        // [first start, last start, count, last end]: a chunk is needed if a
        // record in it can reach into the window.
        chunks.forEach(([from, to, , end], i) => { if ((end ?? to) >= a && to >= lo && from <= b) out.push(`${name}/${key}-${i}`); });
      }
    }
    if (detail) {
      for (const key of boxHits(this.index.detail, bounds, MAX_DETAIL_FILES)) out.push(`d/${key}`);
    }
    // Long happenings that only show from zoom 4 (most are minor).
    if (zmax >= 4 && this.index.longDetail) out.push('long-2');
    if (standing && zoom >= STANDING_ZOOM - 0.5) {
      for (const key of boxHits(this.index.standing, bounds, MAX_DETAIL_FILES)) out.push(`p/${key}`);
    }
    return out;
  }

  get(path) {
    const v = this.files.get(path);
    if (!Array.isArray(v)) return null;
    if (isLeaf(path)) { this.files.delete(path); this.files.set(path, v); } // most recently used last
    return v;
  }

  // Panning around the world at city zoom would otherwise keep every file it
  // ever loaded.
  trimLeaves() {
    let n = 0;
    for (const k of this.files.keys()) if (isLeaf(k)) n++;
    for (const [k, v] of this.files) {
      if (n <= KEEP_LEAVES) break;
      if (isLeaf(k) && Array.isArray(v)) { this.files.delete(k); n--; }
    }
  }

  // low: a prefetch, which must never slow down what's on screen.
  load(path, low = false) {
    if (!this.files.has(path)) {
      // A file that just failed waits before the next try (it would otherwise
      // be asked for again on every update).
      const f = this.failed.get(path);
      if (f && Date.now() - f[1] < RETRY_MS[Math.min(f[0], RETRY_MS.length) - 1]) {
        return Promise.reject(new Error(`${path}: waiting to retry`));
      }
      const standing = path.startsWith('p/');
      const p = this.fetchRaw(path, true, low ? 'low' : 'auto').then(rows => {
        const recs = rows.map(a => toRecord(a, standing, path));
        this.files.set(path, recs);
        this.failed.delete(path);
        if (isLeaf(path)) this.trimLeaves();
        this.onLoad();
        return recs;
      }, err => {
        this.files.delete(path);
        this.failed.set(path, [(f?.[0] || 0) + 1, Date.now()]);
        // Try again once the wait is over, if the view still wants it.
        setTimeout(() => this.onLoad(), RETRY_MS[Math.min((f?.[0] || 0) + 1, RETRY_MS.length) - 1] + 50);
        throw err;
      });
      this.files.set(path, p);
    }
    return Promise.resolve(this.files.get(path));
  }

  // A record already loaded, in any file.
  findLoaded(id) {
    for (const r of this.long) if (r.id === id) return r;
    for (const r of this.world) if (r.id === id) return r;
    for (const v of this.files.values()) {
      if (!Array.isArray(v)) continue;
      for (const r of v) if (r.id === id) return r;
    }
    return null;
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

  // Search index rows: [id, title, start, end, cat, kind, file, date label],
  // most notable first, in two parts. loadSearch() resolves with the whole
  // index; loadSearchFirst() with the first part, which arrives much sooner.
  loadSearchFirst() {
    if (!this.searchFirst) {
      const rows = r => r.map(a => ({
        id: a[0], title: a[1], start: a[2], end: a[3], cat: a[4], kind: a[5], loc: a[6], label: a[7] || '',
        norm: normalize(a[1]),
      }));
      this.searchFirst = this.fetchRaw('search').then(rows);
      this.search = this.index.searchParts > 1
        ? Promise.all([this.searchFirst, this.fetchRaw('search-2', true, 'low').then(rows)]).then(([a, b]) => a.concat(b))
        : this.searchFirst;
      // A failure lets the next search try again.
      this.search.catch(() => { this.search = this.searchFirst = null; });
    }
    return this.searchFirst;
  }

  loadSearch() {
    this.loadSearchFirst();
    return this.search;
  }

  // Find a record by id in the file that holds it (from the search index or
  // a shared link).
  async findRecord(entry) {
    if (entry.loc === 'long') { await this.longReady; return this.long.find(r => r.id === entry.id) || null; }
    if (entry.loc === 'world') { await this.worldReady; return this.world.find(r => r.id === entry.id) || null; }
    if (!/^([abcdp]\/[\w-]+|long-2)$/.test(entry.loc || '')) return null;
    const recs = await this.load(entry.loc).catch(() => null);
    return recs?.find(r => r.id === entry.id) || null;
  }
}

// Records show from their minzoom onwards, one level early so views feel full.
export function displayZoom(zoom) {
  return Math.floor(zoom) + 1;
}

// Lowercase, accents off, and letters that aren't accented forms folded too
// ("Łódź" matches "lodz").
const FOLD = { ł: 'l', ø: 'o', æ: 'ae', œ: 'oe', ß: 'ss', đ: 'd', ð: 'd', þ: 'th', ı: 'i', ħ: 'h' };
export function normalize(s) {
  return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[łøæœßđðþıħ]/g, c => FOLD[c]);
}

function idle(fn) {
  (window.requestIdleCallback || (f => setTimeout(f, 200)))(fn, { timeout: 3000 });
}
