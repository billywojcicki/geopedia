// Small shared helpers.

import { TIME_ANCHORS, CATEGORIES, KIND_VERB, KIND } from './config.js';

export const $ = (sel, root = document) => root.querySelector(sel);

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'style') e.style.cssText = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}

export function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

// --- Years ------------------------------------------------------------------
// Years are astronomical internally (0 = 1 BC, -1 = 2 BC).

export function fmtYear(y) {
  y = Math.round(y);
  return y <= 0 ? `${1 - y} BC` : String(y);
}

export function fmtRange(a, b) {
  if (a === b) return fmtYear(a);
  if (a <= 0 && b <= 0) return `${1 - a}–${1 - b} BC`;
  return `${fmtYear(a)} – ${fmtYear(b)}`;
}

// "1066", "-490", "490 BC", "490bce", "44 b.c." -> astronomical year
export function parseYear(s) {
  s = String(s).trim().toLowerCase().replace(/[.,\s]/g, '');
  const m = s.match(/^(-?\d{1,5})(bce?|ad|ce)?$/);
  if (!m) return null;
  let y = parseInt(m[1], 10);
  if (m[2] && m[2].startsWith('b')) y = 1 - Math.abs(y);
  return y;
}

export function yearToPos(y) {
  const A = TIME_ANCHORS;
  if (y <= A[0][0]) return 0;
  for (let i = 1; i < A.length; i++) {
    if (y <= A[i][0]) {
      const [y0, p0] = A[i - 1], [y1, p1] = A[i];
      return p0 + (p1 - p0) * (y - y0) / (y1 - y0);
    }
  }
  return 1;
}

export function posToYear(p) {
  const A = TIME_ANCHORS;
  if (p <= 0) return A[0][0];
  for (let i = 1; i < A.length; i++) {
    if (p <= A[i][1]) {
      const [y0, p0] = A[i - 1], [y1, p1] = A[i];
      return y0 + (y1 - y0) * (p - p0) / (p1 - p0);
    }
  }
  return A[A.length - 1][0];
}

// --- Records -----------------------------------------------------------------

export function catColor(cat) {
  return `var(--c-${CATEGORIES[cat].id})`;
}

// Display title for map labels: drop disambiguation like "(1919–1920)".
export function shortTitle(t) {
  return t.replace(/\s*\([^)]*\)$/, '');
}

// Secondary line under a title: "17 Jun 1775", "Born 1706", "Built 1723".
export function subline(r) {
  return r.kind === KIND.EVENT ? r.date : `${KIND_VERB[r.kind]} ${r.date}`;
}

// Longer form for cards: adds the place for births and deaths.
export function metaLine(r) {
  const s = subline(r);
  return (r.kind === KIND.BORN || r.kind === KIND.DIED) && r.place ? `${s} in ${r.place}` : s;
}

// --- Wikimedia -----------------------------------------------------------------

// Wikimedia only serves a fixed set of thumbnail widths.
const THUMB_WIDTHS = [60, 120, 250, 330, 500, 960, 1280];

export function thumbUrl(path, width) {
  if (!path) return '';
  const w = THUMB_WIDTHS.find(x => x >= width) || 1280;
  const name = path.slice(path.lastIndexOf('/') + 1);
  const dir = path.slice(0, path.lastIndexOf('/') + 1);
  const enc = encodeURIComponent(name);
  const suffix = /\.svg$/i.test(name) ? '.png' : '';
  return `https://upload.wikimedia.org/wikipedia/commons/thumb/${dir}${enc}/${w}px-${enc}${suffix}`;
}

function originalUrl(path) {
  const name = path.slice(path.lastIndexOf('/') + 1);
  const dir = path.slice(0, path.lastIndexOf('/') + 1);
  return `https://upload.wikimedia.org/wikipedia/commons/${dir}${encodeURIComponent(name)}`;
}

export function wikiUrl(title) {
  return `https://en.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, '_'))}`;
}

// <img> for a Commons file. Large sizes fall back to the original file when the
// thumbnail fails (Wikimedia refuses thumbnails wider than the original); small
// ones just disappear rather than risk pulling a huge original.
export function wikiImg(path, width, attrs = {}) {
  const img = el('img', { src: thumbUrl(path, width), alt: '', loading: 'lazy', decoding: 'async', ...attrs });
  img.addEventListener('error', () => {
    if (width >= 330 && !img.dataset.fallback && !/\.svg$/i.test(path)) {
      img.dataset.fallback = '1';
      img.src = originalUrl(path);
    } else {
      img.remove();
    }
  });
  return img;
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function throttle(fn, ms) {
  let last = 0, t = null;
  return (...a) => {
    const now = performance.now();
    if (now - last >= ms) { last = now; fn(...a); }
    else if (!t) t = setTimeout(() => { t = null; last = performance.now(); fn(...a); }, ms - (now - last));
  };
}

// Great-circle distance in km.
export function distKm(a, b) {
  const R = 6371, rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
