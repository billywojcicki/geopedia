// Pins: the labelled, photo-bearing markers. Every placement pass walks the
// candidates in priority order and greedily keeps those that don't collide
// on screen, so zooming out shows only the most notable things and zooming in
// reveals the local ones.

import { el, shortTitle, subline, thumbUrl, catColor } from './util.js';
import { KIND, HAPPENED } from './config.js';

const CELL = 48;
const failed = new Map(); // image -> when it failed to load; retried after a while (429s pass)
const RETRY_PHOTO_MS = 120000;
const failedRecently = img => Date.now() - (failed.get(img) || 0) < RETRY_PHOTO_MS;
const measureCtx = document.createElement('canvas').getContext('2d');
const widthCache = new Map();

function textWidth(s, font) {
  const k = font + s;
  let w = widthCache.get(k);
  if (w === undefined) {
    measureCtx.font = font;
    w = measureCtx.measureText(s).width;
    if (widthCache.size > 20000) widthCache.clear();
    widthCache.set(k, w);
  }
  return w;
}

const UI_FONT = getComputedStyle(document.documentElement).getPropertyValue('--font');
const TITLE_FONT = `600 12.5px ${UI_FONT}`, SUB_FONT = `500 11px ${UI_FONT}`;

export class Pins {
  constructor(map, { onHover, onLeave, onClick, onPress }) {
    this.map = map;
    this.onHover = onHover;
    this.onLeave = onLeave;
    this.onClick = onClick;
    this.onPress = onPress; // a finger touched the pin: a tap's click follows soon
    this.active = new Map(); // id -> { marker, el, rec }
    this.selectedId = null;
    this.highlightId = null;
  }

  // candidates: sorted by priority (desc). forced: record to always place.
  place(candidates, forced, obstacles = []) {
    const map = this.map;
    const canvas = map.getCanvas();
    const W = canvas.clientWidth, H = canvas.clientHeight;
    const zoom = map.getZoom();
    const maxPins = Math.round(clamp(W * H / 28000, 10, 50));
    const globe = map.getProjection()?.type === 'globe';
    const tr = map.transform;
    const b = map.getBounds();
    const [west, east, south, north] = [b.getWest(), b.getEast(), b.getSouth(), b.getNorth()];
    const wrap = east - west >= 360 || (globe && zoom < 2.5);
    const grid = new Map();
    const boxes = [];
    const placed = [];
    const small = zoom < 3.5;
    const photoR = small ? 16 : 21;

    const collides = box => {
      const cx0 = Math.floor(box[0] / CELL), cx1 = Math.floor(box[2] / CELL);
      const cy0 = Math.floor(box[1] / CELL), cy1 = Math.floor(box[3] / CELL);
      for (let cx = cx0; cx <= cx1; cx++) for (let cy = cy0; cy <= cy1; cy++) {
        const list = grid.get(cx * 4096 + cy);
        if (!list) continue;
        for (const o of list) if (box[0] < o[2] && box[2] > o[0] && box[1] < o[3] && box[3] > o[1]) return true;
      }
      return false;
    };
    const add = box => {
      boxes.push(box);
      const cx0 = Math.floor(box[0] / CELL), cx1 = Math.floor(box[2] / CELL);
      const cy0 = Math.floor(box[1] / CELL), cy1 = Math.floor(box[3] / CELL);
      for (let cx = cx0; cx <= cx1; cx++) for (let cy = cy0; cy <= cy1; cy++) {
        const k = cx * 4096 + cy;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(box);
      }
    };

    const tryPlace = (r, force) => {
      let lng = r.lng;
      if (!wrap) {
        if (r.lat < south || r.lat > north) return;
        // Bounds can extend past ±180; test the nearest world copy.
        if (lng < west) lng += 360; else if (lng > east) lng -= 360;
        if (lng < west || lng > east) return;
      }
      const ll = { lng, lat: r.lat };
      if (globe && tr.isLocationOccluded && tr.isLocationOccluded(ll)) return;
      const p = map.project(ll);
      if (p.x < -10 || p.y < -10 || p.x > W + 10 || p.y > H + 10) return;
      const photo = !!r.img && !failedRecently(r.img);
      const rad = photo ? photoR : 7;
      // A record's label never changes: measure it once.
      const tw = r.labelW ??= Math.min(170, Math.max(textWidth(shortTitle(r.title), TITLE_FONT), textWidth(subline(r), SUB_FONT)));
      const m = 3; // breathing room between pins
      const hh = Math.max(rad, 16) + m;
      // Label on the right if it fits, else on the left.
      const right = [p.x - rad - m, p.y - hh, p.x + rad + 6 + tw + m, p.y + hh];
      const left = [p.x - rad - 6 - tw - m, p.y - hh, p.x + rad + m, p.y + hh];
      // A label must fit on screen and not overlap anything placed already.
      const free = b => b[0] >= 0 && b[2] <= W && b[1] >= 0 && b[3] <= H && !collides(b);
      let box = right, side = 'right';
      if (!force && !free(right)) {
        if (!free(left)) return;
        box = left; side = 'left';
      }
      add(box);
      // The label's box relative to the pin, for the basemap's label collisions.
      placed.push({ r, photo, small: photo && small, side, w: box[2] - box[0], h: box[3] - box[1], off: rad + m });
    };

    // Panels floating over the map act as already-placed boxes.
    const origin = canvas.getBoundingClientRect();
    for (const [l, t, r, b] of obstacles) add([l - origin.left, t - origin.top, r - origin.left, b - origin.top]);

    if (forced) tryPlace(forced, true);
    // Things that happened lead; buildings, foundings and standing places get
    // at most a third of the labels, even where events are scarce.
    const maxMinor = Math.max(4, Math.round(maxPins / 3));
    let scanned = 0, minor = 0;
    for (const r of candidates) {
      if (placed.length >= maxPins || ++scanned > 12000) break;
      if (forced && r.id === forced.id) continue;
      const isMinor = !HAPPENED.has(r.kind);
      if (isMinor && minor >= maxMinor) continue;
      const n = placed.length;
      tryPlace(r, false);
      if (isMinor && placed.length > n) minor++;
    }
    this.render(placed);
    this.block(placed);
    return placed.length;
  }

  // Basemap and border labels give way to pin labels: each placed pin gets an
  // invisible box in a symbol layer on top, which MapLibre's label collision
  // then keeps clear. Call after every style load.
  attach() {
    const map = this.map;
    if (!map.getSource('pin-blockers')) map.addSource('pin-blockers', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    if (!map.getLayer('pin-blockers')) {
      map.addLayer({
        id: 'pin-blockers', type: 'symbol', source: 'pin-blockers',
        layout: {
          'icon-image': ['get', 'img'], 'icon-anchor': ['get', 'anchor'], 'icon-offset': ['get', 'off'],
          'icon-allow-overlap': true, 'icon-ignore-placement': false, 'icon-padding': 0,
          'icon-rotation-alignment': 'viewport', 'icon-pitch-alignment': 'viewport',
        },
        paint: { 'icon-opacity': 0 },
      });
    }
    this.block(this.lastPlaced || []);
  }

  block(placed) {
    this.lastPlaced = placed;
    const map = this.map, src = map.getSource('pin-blockers');
    if (!src) return;
    src.setData({
      type: 'FeatureCollection',
      features: placed.map(({ r, side, w, h, off }) => {
        const W = Math.ceil(w / 10) * 10, H = Math.ceil(h / 2) * 2;
        const img = `pin-blocker-${W}x${H}`;
        if (!map.hasImage(img)) map.addImage(img, { width: W, height: H, data: new Uint8Array(W * H * 4) });
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [r.lng, r.lat] },
          properties: { img, anchor: side === 'left' ? 'right' : 'left', off: [side === 'left' ? off : -off, 0] },
        };
      }),
    });
  }

  render(placed) {
    const keep = new Set();
    for (const { r, photo, small, side } of placed) {
      keep.add(r.id);
      const cur = this.active.get(r.id);
      if (cur && cur.photo === photo && cur.small === small && cur.standing === (r.standing && !r.isNew)) {
        cur.el.classList.remove('leaving');
        cur.el.classList.toggle('left', side === 'left');
        continue;
      }
      if (cur) this.remove(r.id, true);
      this.add(r, photo, small, side);
    }
    for (const id of [...this.active.keys()]) if (!keep.has(id)) this.remove(id);
  }

  add(r, photo, small, side) {
    const standing = r.standing && !r.isNew;
    const inner = el('div', { class: 'pin-in' },
      photo
        ? el('div', { class: 'pin-photo loading', style: `--c:${catColor(r.cat)}` })
        : el('div', { class: 'pin-dot', style: `--c:${catColor(r.cat)}` }),
      el('div', { class: 'pin-label' }, el('b', {}, shortTitle(r.title)), el('small', {}, subline(r))),
    );
    const node = el('div', {
      class: ['pin', photo && 'photo', small && 'small', standing && 'standing', side === 'left' && 'left',
        (r.kind === KIND.BORN || r.kind === KIND.DIED) && 'people', r.id === this.selectedId && 'selected',
        r.id === this.highlightId && 'hl'].filter(Boolean).join(' '),
      style: `--c:${catColor(r.cat)}`,
    }, inner);
    if (photo) this.loadPhoto(r, node);
    node.addEventListener('mouseenter', () => this.onHover(r, node));
    node.addEventListener('mouseleave', () => this.onLeave(r));
    node.addEventListener('pointerdown', e => { if (e.pointerType === 'touch') this.onPress?.(r); });
    node.addEventListener('click', e => { e.stopPropagation(); this.onClick(r); });
    node.tabIndex = 0;
    node.setAttribute('role', 'button');
    node.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.onClick(r); }
    });
    const marker = new maplibregl.Marker({ element: node, anchor: 'center', opacityWhenCovered: '0' })
      .setLngLat([r.lng, r.lat])
      .addTo(this.map);
    node.setAttribute('aria-label', `${r.title}, ${subline(r)}`);
    this.active.set(r.id, { marker, el: node, rec: r, photo, small, standing });
  }

  // Show the photo once it has loaded; if it can't load, become a plain dot.
  loadPhoto(r, node) {
    const face = node.querySelector('.pin-photo');
    const toDot = () => {
      failed.set(r.img, Date.now());
      face.className = 'pin-dot';
      node.classList.remove('photo', 'small');
    };
    if (failedRecently(r.img)) return toDot();
    const img = new Image();
    img.onload = () => {
      face.style.backgroundImage = `url("${img.src}")`;
      face.classList.remove('loading');
    };
    img.onerror = toDot;
    img.src = thumbUrl(r.img, 120);
  }

  remove(id, now = false) {
    const cur = this.active.get(id);
    if (!cur) return;
    this.active.delete(id);
    if (now) { cur.marker.remove(); return; }
    cur.el.classList.add('leaving');
    setTimeout(() => cur.marker.remove(), 180);
  }

  setSelected(id) {
    this.selectedId = id;
    for (const [k, v] of this.active) v.el.classList.toggle('selected', k === id);
  }

  setHighlight(id) {
    this.highlightId = id;
    for (const [k, v] of this.active) v.el.classList.toggle('hl', k === id);
  }

  clear() {
    for (const id of [...this.active.keys()]) this.remove(id, true);
  }
}

function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
