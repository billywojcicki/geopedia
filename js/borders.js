// Historical borders overlay. Before 1886: aourednik/historical-basemaps
// (GPL-3.0), simplified and self-hosted by scripts/build_borders.py; the
// snapshots are approximate and sparse, so we show the latest one at or before
// the year. From 1886: CShapes 2.0 (CC BY-NC-SA 4.0, scripts/build_cshapes.py),
// every state and colony as it stood on 1 July of the year. The map's worker
// fetches and parses the files, so switching eras never stalls the page, and
// the eras either side are downloaded ahead of time.

import { applyOldNames } from './oldnames.js';
import { cshapesYear, CSHAPES_URL } from './cshapes.js';

const BASE = new URL('basemap/borders/', document.baseURI).href;
// Must match SNAPSHOTS in scripts/build_borders.py.
const SNAPSHOTS = [
  -123000, -10000, -8000, -5000, -4000, -3000, -2000, -1500, -1000, -700, -500, -400, -323, -300, -200, -100, -1,
  100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1279, 1300, 1400, 1492, 1500, 1530, 1600, 1650,
  1700, 1715, 1783, 1800, 1815, 1880,
];
// Must match FIRST_YEAR in scripts/build_cshapes.py.
const CSHAPES_FROM = 1886;
const CSHAPES = 'cshapes';
// Each source has its own layers, so the 1886+ outlines stay loaded while
// the timeline goes back and forth across 1886. Label layer ids start with
// "borders-label" (js/oldnames.js renames them).
const SETS = {
  snapshot: { shapes: 'borders', labels: 'borders-labels', fill: 'borders-fill', line: 'borders-line', label: 'borders-label' },
  [CSHAPES]: { shapes: 'borders-cs', labels: 'borders-cs-labels', fill: 'borders-cs-fill', line: 'borders-cs-line', label: 'borders-label-cs' },
};
const MODERN_LAYERS = /^(boundary_|label_country|world-(borders|states|countries))/;
const ATTRIBUTION = 'Borders: <a href="https://github.com/aourednik/historical-basemaps" target="_blank">historical-basemaps</a>, '
  + '<a href="https://icr.ethz.ch/data/cshapes/" target="_blank">CShapes 2.0</a> (CC BY-NC-SA)';
// A name waits until its polity is about 12 px across (area is in square
// degrees, zoom is the tile's). 1492 has 1,300 names: laying them all out at
// globe zoom, where nearly all lose their collisions, was 40% of that era's
// load time.
const LABEL_FILTER = ['>=', ['get', 'area'], ['/', 72, ['^', 4, ['zoom']]]];
// Below this the globe is small and names spill past its edge into the sky.
const LABEL_MINZOOM = 1.5;

function keyFor(y) {
  return y < 0 ? `bc${-y}` : String(y);
}

function snapshotFor(year) {
  if (year >= CSHAPES_FROM) return CSHAPES;
  let s = SNAPSHOTS[0];
  for (const y of SNAPSHOTS) if (y <= year) s = y;
  return s;
}

const filesFor = s => [`${BASE}${keyFor(s)}.geojson`, `${BASE}${keyFor(s)}.labels.geojson`];

// Downloads a file into the HTTP cache, where the map's worker will find it.
const warmed = new Set();
function warm(url) {
  if (warmed.has(url)) return;
  warmed.add(url);
  fetch(url, { priority: 'low' }).then(r => r.arrayBuffer()).catch(() => warmed.delete(url));
}

// The borders for a year, fetched (or for 1886 on, decoded) before the map
// is up, so they arrive with the first view.
export function prefetchBorders(year) {
  const s = snapshotFor(year);
  if (s === CSHAPES) cshapesYear(year).catch(() => {});
  else filesFor(s).forEach(warm);
}

export class Borders {
  constructor(map) {
    this.map = map;
    this.on = false;
    this.snapshot = null; // shown: a snapshot year or CSHAPES
    this.timer = null;
    this.loadedSnapshot = null; // the snapshot year the snapshot source holds
    this.shownKey = null; // which 1886+ outlines the 1886+ source holds
  }

  toggle(on, year) {
    clearTimeout(this.timer);
    this.on = on;
    this.lastYear = year;
    this.setModernVisible(!on);
    if (on) this.setYear(year, false);
    else this.removeLayers();
  }

  setYear(year, dragging) {
    // A newer year always replaces a pending one (back to the shown era included).
    clearTimeout(this.timer);
    this.lastYear = year;
    if (!this.on) return;
    const s = snapshotFor(year);
    if (s === this.snapshot) {
      // Every year change also retries a 1886+ load that failed.
      if (s === CSHAPES) this.timer = setTimeout(() => this.showYear(year), dragging ? 120 : 0);
      return;
    }
    this.timer = setTimeout(() => this.load(s), dragging ? 250 : 0);
  }

  load(s) {
    if (!this.on) return;
    this.snapshot = s;
    applyOldNames(this.map, this.lastYear ?? s); // the labels' names of their time
    if (s !== CSHAPES) {
      this.ensureLayers(SETS.snapshot);
      this.show(SETS.snapshot);
      if (s !== this.loadedSnapshot) {
        this.loadedSnapshot = s;
        const [shapes, labels] = filesFor(s);
        this.map.getSource('borders').setData(shapes);
        this.map.getSource('borders-labels').setData(labels);
        this.prefetchAround(s);
      }
      return;
    }
    this.ensureLayers(SETS[CSHAPES]);
    this.show(SETS[CSHAPES]); // empty until decoded the first time: no stale 1880 world meanwhile
    this.showYear(this.lastYear);
  }

  // Show the 1886+ outlines that stood on 1 July of the year. Most years
  // change nothing, so the map only reloads when an outline does.
  showYear(year) {
    if (this.snapshot !== CSHAPES) return;
    cshapesYear(year).then(d => {
      const set = SETS[CSHAPES];
      if (!this.on || this.snapshot !== CSHAPES || this.lastYear !== year || !this.map.getSource(set.shapes)) return;
      if (d.key === this.shownKey) return;
      if (this.shownKey === null) this.prefetchAround(CSHAPES);
      this.shownKey = d.key;
      this.map.getSource(set.shapes).setData(d.shapes);
      this.map.getSource(set.labels).setData(d.labels);
    }).catch(() => {}); // tried again on the next year change
  }

  // Once the map is idle (the era is drawn), download the eras either side,
  // so stepping to them skips the network.
  prefetchAround(s) {
    if (navigator.connection?.saveData) return;
    this.map.once('idle', () => {
      if (this.snapshot !== s) return;
      const i = s === CSHAPES ? SNAPSHOTS.length : SNAPSHOTS.indexOf(s);
      for (const j of [i - 1, i + 1]) {
        if (j === SNAPSHOTS.length) warm(CSHAPES_URL);
        else if (j >= 0 && j < SNAPSHOTS.length) filesFor(SNAPSHOTS[j]).forEach(warm);
      }
    });
  }

  show(active) {
    for (const set of Object.values(SETS)) {
      for (const id of [set.fill, set.line, set.label]) {
        if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', set === active ? 'visible' : 'none');
      }
    }
  }

  ensureLayers(set) {
    const map = this.map;
    if (map.getSource(set.shapes)) return;
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    // maxzoom 6: the outlines are approximate anyway, so deeper zooms reuse
    // the z6 tiles instead of re-cutting the whole world on every zoom.
    // buffer 4 (px, default 128): there are no symbols here, and every tile
    // otherwise cuts, triangulates and curves twice its own area.
    const empty = { type: 'FeatureCollection', features: [] };
    map.addSource(set.shapes, { type: 'geojson', data: empty, tolerance: 0.6, maxzoom: 6, buffer: 4, attribution: ATTRIBUTION });
    map.addSource(set.labels, { type: 'geojson', data: empty });
    const firstSymbol = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    const fill = ['to-color', ['concat', 'hsl(', ['to-string', ['get', 'h']], dark ? ', 35%, 45%)' : ', 55%, 62%)']];
    map.addLayer({
      id: set.fill, type: 'fill', source: set.shapes,
      paint: { 'fill-color': fill, 'fill-opacity': dark ? 0.2 : 0.16 },
    }, firstSymbol);
    map.addLayer({
      id: set.line, type: 'line', source: set.shapes,
      paint: {
        'line-color': dark ? 'rgba(235,235,245,0.45)' : 'rgba(60,50,40,0.45)',
        'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 6, 1.2],
      },
    }, firstSymbol);
    // Below the pins' label blockers, so pin labels win collisions.
    const beforePins = map.getLayer('pin-blockers') ? 'pin-blockers' : undefined;
    map.addLayer({
      id: set.label, type: 'symbol', source: set.labels, minzoom: LABEL_MINZOOM, filter: LABEL_FILTER,
      layout: {
        'symbol-sort-key': ['-', ['get', 'area']],
        'text-field': ['get', 'label'],
        'text-font': ['Noto Sans Italic'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 1, 10, 5, 13, 8, 15],
        'text-transform': 'uppercase',
        'text-letter-spacing': 0.1,
        'text-max-width': 8,
        'text-padding': 6,
      },
      paint: {
        'text-color': dark ? 'rgba(235,235,245,0.75)' : 'rgba(70,55,40,0.8)',
        'text-halo-color': dark ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.8)',
        'text-halo-width': 1.2,
      },
    }, beforePins);
    applyOldNames(map, this.lastYear ?? CSHAPES_FROM); // a new label layer starts with plain names
  }

  removeLayers() {
    clearTimeout(this.timer);
    const map = this.map;
    for (const set of Object.values(SETS)) {
      for (const id of [set.label, set.line, set.fill]) if (map.getLayer(id)) map.removeLayer(id);
      for (const id of [set.shapes, set.labels]) if (map.getSource(id)) map.removeSource(id);
    }
    this.snapshot = null;
    this.loadedSnapshot = null;
    this.shownKey = null;
  }

  setModernVisible(v) {
    for (const l of this.map.getStyle().layers) {
      if (MODERN_LAYERS.test(l.id)) this.map.setLayoutProperty(l.id, 'visibility', v ? 'visible' : 'none');
    }
  }

  // After a style reload (theme change): the sources went with the old style.
  restore() {
    if (!this.on) return;
    this.snapshot = null;
    this.loadedSnapshot = null;
    this.shownKey = null;
    this.setModernVisible(false);
    const y = this.lastYear;
    this.load(snapshotFor(y ?? 1800));
  }
}
