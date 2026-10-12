// Year-by-year borders from 1886 (CShapes 2.0, CC BY-NC-SA 4.0), shipped as
// a small topology by scripts/build_cshapes.py: shared borders are stored
// once and each outline lists the borders it is made of. Decoding it into
// GeoJSON happens in a worker (js/cshapes-worker.js) when one is available.

// The topology -> { shapes, labels } as GeoJSON. Every outline carries
// s and e (fractional years, e exclusive) for the map's year filter.
export function decode(t) {
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
  const shapes = [], labels = [];
  for (const [label, h, spans, lng, lat, area, polys] of t.shapes) {
    const coords = polys.map(p => p.map(ring));
    const geometry = coords.length === 1 ? { type: 'Polygon', coordinates: coords[0] } : { type: 'MultiPolygon', coordinates: coords };
    for (let i = 0; i < spans.length; i += 2) {
      const properties = { label, h, s: spans[i], e: spans[i + 1] };
      shapes.push({ type: 'Feature', geometry, properties });
      labels.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [lng, lat] }, properties: { ...properties, area } });
    }
  }
  // Bigger countries claim their label spot first.
  labels.sort((a, b) => b.properties.area - a.properties.area);
  return {
    shapes: { type: 'FeatureCollection', features: shapes },
    labels: { type: 'FeatureCollection', features: labels },
  };
}

let loading = null;

// { shapes: GeoJSON URL or object, labels: GeoJSON object }, decoded once.
// The worker hands back the outlines as a Blob, so the map's own worker
// fetches and parses them and the page never touches the big part.
export function loadCShapes() {
  const url = new URL('basemap/borders/cshapes.json', document.baseURI).href;
  loading ??= new Promise((resolve, reject) => {
    const w = new Worker(new URL('./cshapes-worker.js', import.meta.url), { type: 'module' });
    w.onmessage = e => {
      w.terminate();
      if (e.data.error) reject(new Error(e.data.error));
      else resolve({ shapes: URL.createObjectURL(e.data.shapes), labels: e.data.labels });
    };
    w.onerror = e => { w.terminate(); reject(e); };
    w.postMessage(url);
  }).catch(() => fetch(url).then(r => r.json()).then(decode)).catch(e => {
    loading = null; // try again next time
    throw e;
  });
  return loading;
}
