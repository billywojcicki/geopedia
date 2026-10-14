// Decodes the 1886+ borders off the main thread once, then answers with each
// year's outlines as GeoJSON blobs (see js/cshapes.js).
import { prepare, standing, collections } from './cshapes.js';

let outlines = null;
let spans = null;

self.onmessage = async e => {
  const { id, url, year, have } = e.data;
  try {
    // Low: at startup this must not slow down MapLibre's own download.
    outlines ??= fetch(url, { priority: 'low' }).then(r => {
      if (!r.ok) throw new Error(`cshapes ${r.status}`);
      return r.json();
    }).then(prepare);
    const all = await outlines;
    spans ??= all.map(o => o.spans);
    const key = standing(spans, year);
    const out = { id, key };
    if (e.data.spans) out.spans = spans;
    if (!have.includes(key)) Object.assign(out, collections(all, key));
    self.postMessage(out);
  } catch (err) {
    outlines = null; // try again next time
    self.postMessage({ id, error: String(err) });
  }
};
