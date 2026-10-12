// Historical borders overlay from aourednik/historical-basemaps (GPL-3.0),
// simplified and self-hosted by scripts/build_borders.py. Snapshots are
// approximate and sparse; we show the latest snapshot at or before the year.
// The map's worker fetches and parses each file, so switching eras never
// stalls the page.

const BASE = new URL('basemap/borders/', document.baseURI).href;
// Must match SNAPSHOTS in scripts/build_borders.py.
const SNAPSHOTS = [
  -123000, -10000, -8000, -5000, -4000, -3000, -2000, -1500, -1000, -700, -500, -400, -323, -300, -200, -100, -1,
  100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1279, 1300, 1400, 1492, 1500, 1530, 1600, 1650,
  1700, 1715, 1783, 1800, 1815, 1880, 1900, 1914, 1920, 1930, 1938, 1945, 1960, 1994, 2000, 2010,
];
const MODERN_LAYERS = /^(boundary_|label_country|world-(borders|states|countries))/;

function keyFor(y) {
  return y < 0 ? `bc${-y}` : String(y);
}

function snapshotFor(year) {
  let s = SNAPSHOTS[0];
  for (const y of SNAPSHOTS) if (y <= year) s = y;
  return s;
}

export class Borders {
  constructor(map) {
    this.map = map;
    this.on = false;
    this.snapshot = null;
    this.timer = null;
  }

  toggle(on, year) {
    this.on = on;
    this.lastYear = year;
    this.setModernVisible(!on);
    if (on) this.setYear(year, false);
    else this.removeLayers();
  }

  setYear(year, dragging) {
    this.lastYear = year;
    if (!this.on) return;
    const s = snapshotFor(year);
    if (s === this.snapshot) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(s), dragging ? 250 : 0);
  }

  load(s) {
    this.snapshot = s;
    this.ensureLayers();
    this.map.getSource('borders').setData(`${BASE}${keyFor(s)}.geojson`);
    this.map.getSource('borders-labels').setData(`${BASE}${keyFor(s)}.labels.geojson`);
  }

  ensureLayers() {
    const map = this.map;
    if (map.getSource('borders')) return;
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    // maxzoom 6: the outlines are approximate anyway, so deeper zooms reuse
    // the z6 tiles instead of re-cutting the whole world on every zoom.
    const empty = { type: 'FeatureCollection', features: [] };
    map.addSource('borders', { type: 'geojson', data: empty, tolerance: 0.6, maxzoom: 6 });
    map.addSource('borders-labels', { type: 'geojson', data: empty });
    const firstSymbol = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    const fill = ['to-color', ['concat', 'hsl(', ['to-string', ['get', 'h']], dark ? ', 35%, 45%)' : ', 55%, 62%)']];
    map.addLayer({
      id: 'borders-fill', type: 'fill', source: 'borders',
      paint: { 'fill-color': fill, 'fill-opacity': dark ? 0.2 : 0.16 },
    }, firstSymbol);
    map.addLayer({
      id: 'borders-line', type: 'line', source: 'borders',
      paint: {
        'line-color': dark ? 'rgba(235,235,245,0.45)' : 'rgba(60,50,40,0.45)',
        'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 6, 1.2],
      },
    }, firstSymbol);
    map.addLayer({
      id: 'borders-label', type: 'symbol', source: 'borders-labels',
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
    });
  }

  removeLayers() {
    const map = this.map;
    for (const id of ['borders-label', 'borders-line', 'borders-fill']) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of ['borders', 'borders-labels']) if (map.getSource(id)) map.removeSource(id);
    this.snapshot = null;
  }

  setModernVisible(v) {
    for (const l of this.map.getStyle().layers) {
      if (MODERN_LAYERS.test(l.id)) this.map.setLayoutProperty(l.id, 'visibility', v ? 'visible' : 'none');
    }
  }

  // After a style reload (theme change).
  restore() {
    if (!this.on) return;
    this.snapshot = null;
    this.setModernVisible(false);
    const y = this.lastYear;
    this.load(snapshotFor(y ?? 1800));
  }
}
