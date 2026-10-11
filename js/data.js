// Loads the static data files and answers "what's in this time window / area".

const BASE = 'data/';

async function fetchJSON(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// Array record -> object. Layout documented in scripts/build_data.py.
function toRecord(a, standing) {
  return {
    id: a[0], title: a[1], lat: a[2], lng: a[3], start: a[4], end: a[5],
    cat: a[6], kind: a[7], score: a[8], img: a[9], desc: a[10], date: a[11], place: a[12],
    standing,
  };
}

export class Store {
  constructor() {
    this.index = null;
    this.buckets = new Map(); // bucket index -> records[] | Promise
    this.long = [];
    this.tiles = new Map(); // tile key -> records[] | Promise
    this.search = null;
  }

  async init() {
    this.index = await fetchJSON('index.json');
    this.long = (await fetchJSON('h/long.json')).map(a => toRecord(a, false));
  }

  // Bucket ids that can hold happenings overlapping [a, b].
  bucketIds(a, b) {
    const lo = a - this.index.longSpan;
    const ids = [];
    this.index.buckets.forEach(([from, to], i) => { if (to >= lo && from <= b) ids.push(i); });
    return ids;
  }

  loadBucket(i) {
    if (!this.buckets.has(i)) {
      const p = fetchJSON(`h/${i}.json`).then(rows => {
        const recs = rows.map(a => toRecord(a, false));
        this.buckets.set(i, recs);
        return recs;
      }).catch(err => { this.buckets.delete(i); throw err; });
      this.buckets.set(i, p);
    }
    return Promise.resolve(this.buckets.get(i));
  }

  // True when everything needed for [a, b] is in memory.
  hasWindow(a, b) {
    return this.bucketIds(a, b).every(i => Array.isArray(this.buckets.get(i)));
  }

  async loadWindow(a, b) {
    await Promise.all(this.bucketIds(a, b).map(i => this.loadBucket(i)));
  }

  // Warm neighbouring buckets so scrubbing stays smooth.
  prefetchAround(a, b) {
    const ids = this.bucketIds(a, b);
    if (!ids.length) return;
    for (const i of [ids[0] - 1, ids[ids.length - 1] + 1]) {
      if (i >= 0 && i < this.index.buckets.length) this.loadBucket(i).catch(() => {});
    }
  }

  happenings(a, b) {
    const out = [];
    for (const i of this.bucketIds(a, b)) {
      const recs = this.buckets.get(i);
      if (!Array.isArray(recs)) continue;
      for (const r of recs) if (r.start <= b && r.end >= a) out.push(r);
    }
    for (const r of this.long) if (r.start <= b && r.end >= a) out.push(r);
    return out;
  }

  // --- Standing places (spatial quadtree leaves) ---

  tileKeys(bounds) {
    const [w, s, e, n] = bounds;
    return this.index.tiles
      .filter(([, x0, y0, x1, y1]) => x1 >= w && x0 <= e && y1 >= s && y0 <= n)
      .map(t => t[0]);
  }

  loadTile(key) {
    if (!this.tiles.has(key)) {
      const p = fetchJSON(`p/${key}.json`).then(rows => {
        const recs = rows.map(a => toRecord(a, true));
        this.tiles.set(key, recs);
        return recs;
      }).catch(err => { this.tiles.delete(key); throw err; });
      this.tiles.set(key, p);
    }
    return Promise.resolve(this.tiles.get(key));
  }

  standing(a, b, keys) {
    const out = [];
    for (const k of keys) {
      const recs = this.tiles.get(k);
      if (!Array.isArray(recs)) continue;
      for (const r of recs) if (r.start <= b && r.end >= a) out.push(r);
    }
    return out;
  }

  async loadSearch() {
    if (!this.search) {
      this.search = fetchJSON('search.json').then(rows => rows.map(a => ({
        id: a[0], title: a[1], lat: a[2], lng: a[3], start: a[4], end: a[5], cat: a[6], kind: a[7],
        norm: normalize(a[1]),
      })));
    }
    return this.search;
  }
}

export function normalize(s) {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}
