// Year-by-year borders from 1886 (CShapes 2.0, CC BY-NC-SA 4.0), shipped as
// a small topology by scripts/build_cshapes.py: shared borders are stored
// once and each outline lists the borders it is made of. A worker
// (js/cshapes-worker.js) decodes it once, then writes each year's outlines
// as GeoJSON for the map's own worker to fetch, so the map only ever indexes
// the year it shows (all of 1886-2019 at once is 4 MB of GeoJSON).

// Relative to this module, which the worker imports too (it has no document).
export const CSHAPES_URL = new URL('../basemap/borders/cshapes.json', import.meta.url).href;

// The topology -> one entry per outline: its spans (fractional years, e
// exclusive), its label's area and its features as GeoJSON text.
export function prepare(t) {
  const arcs = t.arcs.map(a => {
    const pts = [];
    let x = 0, y = 0;
    for (let i = 0; i < a.length; i += 2) {
      x += a[i];
      y += a[i + 1];
      pts.push([x / t.q, y / t.q]);
    }
    return pts;
  });
  const ring = ids => {
    const out = [];
    for (const i of ids) {
      const a = i >= 0 ? arcs[i] : arcs[~i].slice().reverse();
      for (let k = out.length ? 1 : 0; k < a.length; k++) out.push(a[k]);
    }
    return out;
  };
  return t.shapes.map(([label, h, spans, lng, lat, area, polys]) => {
    const coords = polys.map(p => p.map(ring));
    const geometry = coords.length === 1 ? { type: 'Polygon', coordinates: coords[0] } : { type: 'MultiPolygon', coordinates: coords };
    return {
      spans,
      area,
      shape: JSON.stringify({ type: 'Feature', geometry, properties: { label, h } }),
      label: JSON.stringify({ type: 'Feature', geometry: { type: 'Point', coordinates: [lng, lat] }, properties: { label, h, area } }),
    };
  });
}

// Which outlines stood on 1 July of the year, as a key: "3,17,42,".
export function standing(spans, year) {
  const t = year + 0.5;
  let key = '';
  for (let i = 0; i < spans.length; i++) {
    const s = spans[i];
    for (let k = 0; k < s.length; k += 2) {
      if (s[k] <= t && t < s[k + 1]) { key += `${i},`; break; }
    }
  }
  return key;
}

// The outlines in a key -> { shapes, labels } as GeoJSON blobs.
export function collections(outlines, key) {
  const on = key.split(',').filter(Boolean).map(Number);
  const blob = parts => new Blob([`{"type":"FeatureCollection","features":[${parts.join(',')}]}`], { type: 'application/json' });
  // Bigger countries claim their label spot first.
  const byArea = on.slice().sort((a, b) => outlines[b].area - outlines[a].area);
  return { shapes: blob(on.map(i => outlines[i].shape)), labels: blob(byArea.map(i => outlines[i].label)) };
}

let worker = null; // false: decode on the page (no module workers)
let spans = null; // every outline's spans, once decoded
let seq = 0;
const waiting = new Map();
// Recent years as blob URLs by key, most recently used last: going back to a
// year (or to one with the same outlines) needs no decoding at all.
const cache = new Map();
const CACHE_SIZE = 8;
let here = null;

function remember(key, d) {
  const urls = { shapes: URL.createObjectURL(d.shapes), labels: URL.createObjectURL(d.labels) };
  cache.set(key, urls);
  for (const [k, u] of cache) {
    if (cache.size <= CACHE_SIZE) break;
    cache.delete(k);
    URL.revokeObjectURL(u.shapes);
    URL.revokeObjectURL(u.labels);
  }
  return urls;
}

function cached(key) {
  const urls = cache.get(key);
  if (!urls) return null;
  cache.delete(key);
  cache.set(key, urls);
  return urls;
}

async function onPage(year, have) {
  here ??= fetch(CSHAPES_URL).then(r => r.json()).then(prepare).catch(e => { here = null; throw e; });
  const outlines = await here;
  spans ??= outlines.map(o => o.spans);
  const key = standing(spans, year);
  return have.includes(key) ? { key } : { key, ...collections(outlines, key) };
}

function request(year, have) {
  if (worker === null) {
    try {
      worker = new Worker(new URL('./cshapes-worker.js', import.meta.url), { type: 'module' });
    } catch {
      worker = false;
    }
    if (worker) {
      worker.onmessage = e => {
        const d = e.data;
        const w = waiting.get(d.id);
        waiting.delete(d.id);
        if (d.spans) spans = d.spans;
        if (d.error) w?.reject(new Error(d.error));
        else w?.resolve(d);
      };
      // The worker couldn't start (no module workers): decode on the page.
      worker.onerror = () => {
        worker.terminate();
        worker = false;
        for (const [id, w] of waiting) {
          waiting.delete(id);
          onPage(w.year, w.have).then(w.resolve, w.reject);
        }
      };
    }
  }
  if (!worker) return onPage(year, have);
  return new Promise((resolve, reject) => {
    const id = ++seq;
    waiting.set(id, { resolve, reject, year, have });
    worker.postMessage({ id, url: CSHAPES_URL, year, spans: !spans, have });
  });
}

// { key, shapes, labels } for a year: key names its set of outlines, shapes
// and labels are GeoJSON URLs for the map. Decodes on first use.
export async function cshapesYear(year) {
  const key = spans && standing(spans, year);
  const hit = key && cached(key);
  if (hit) return { key, ...hit };
  let d = await request(year, [...cache.keys()]);
  if (!d.shapes && !cache.has(d.key)) d = await request(year, []); // dropped from the cache meanwhile
  return { key: d.key, ...(d.shapes ? remember(d.key, d) : cached(d.key)) };
}
