// Decodes the 1886+ borders off the main thread (see js/cshapes.js).
import { decode } from './cshapes.js';

self.onmessage = async e => {
  try {
    const { shapes, labels } = decode(await (await fetch(e.data)).json());
    self.postMessage({ shapes: new Blob([JSON.stringify(shapes)], { type: 'application/json' }), labels });
  } catch (err) {
    self.postMessage({ error: String(err) });
  }
};
