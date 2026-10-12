// Basemap, in two layers of detail:
//
// - Zoomed out (below BASEMAP_MAX_ZOOM): our own Natural Earth world
//   (basemap/world.json, ~170 KB), served from this site. OpenFreeMap's
//   world-level vector tiles are 300-700 KB each, so a first view drawn from
//   them meant megabytes of downloads and a patchy map while they arrived.
// - Zoomed in: OpenFreeMap vector tiles (OpenMapTiles schema), restyled from
//   their Positron style with a softer, Apple-ish palette.
//
// Both "age" (parchment tones, fading roads) as the timeline goes back in time.

export const BASEMAP_MAX_ZOOM = 6; // must match MAX_ZOOM in scripts/build_basemap.py
// Our coarse land stays under the detailed tiles a little longer, so the sea
// never flashes land-coloured while those tiles load.
const COARSE_LAND_UNTIL = 7.5;
const OFM_FONTS = 'https://tiles.openfreemap.org/fonts/';
// Glyph ranges shipped in basemap/fonts (everything else comes from OpenFreeMap).
const LOCAL_GLYPHS = { 'Noto Sans Regular': ['0-255', '256-511', '8192-8447'] };
const FONT = ['Noto Sans Regular'];

const PALETTES = {
  light: {
    background: '#f2f0eb', water: '#b4d6f1', waterLabel: '#4f7aa6', park: '#d6eacb', wood: '#dbe9d2',
    residential: '#ebe8e2', building: '#e5e2dc', buildingLine: '#d9d5ce', ice: '#fbfbfb',
    road: '#ffffff', roadCasing: '#e1ddd5', motorway: '#fde8b4', motorwayCasing: '#ecd29a',
    minor: '#ffffff', rail: '#d9d6d0', boundary: '#b7afa4', state: '#cfc8bd',
    label: '#3a3a3c', labelSoft: '#6e6e73', country: '#55555a', halo: 'rgba(255,255,255,0.92)',
  },
  dark: {
    background: '#232325', water: '#1b2a3b', waterLabel: '#7a9cc0', park: '#22322a', wood: '#213027',
    residential: '#29292b', building: '#323235', buildingLine: '#3b3b3e', ice: '#3a3a3c',
    road: '#3e3e42', roadCasing: '#2c2c2f', motorway: '#6a5a36', motorwayCasing: '#4a3f27',
    minor: '#38383b', rail: '#3a3a3d', boundary: '#5f5f64', state: '#47474b',
    label: '#d1d1d6', labelSoft: '#98989d', country: '#aeaeb2', halo: 'rgba(28,28,30,0.9)',
  },
};

// What the map drifts toward as we go back in time.
const AGED = {
  light: { background: '#efe5cf', water: '#c3d5d2', park: '#dfe2c3', wood: '#dde2c4', residential: '#ebe2cf', building: '#e6dcc8' },
  dark: { background: '#29251f', water: '#1f2a30', park: '#2a2e24', wood: '#282c23', residential: '#2c2822', building: '#35302a' },
};

function hex(c) {
  const n = parseInt(c.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mix(a, b, t) {
  const A = hex(a), B = hex(b);
  return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, '0')).join('');
}

const EN_NAME = ['coalesce', ['get', 'name:en'], ['get', 'name_en'], ['get', 'name']];

export function themeName() {
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// Glyphs come through a custom protocol: Latin ranges of our label font are
// served from this site, anything else (other scripts, other weights) from
// OpenFreeMap.
let protocolAdded = false;
export function addGlyphProtocol() {
  if (protocolAdded) return;
  protocolAdded = true;
  maplibregl.addProtocol('glyphs', async (params, abort) => {
    const [, stack, range] = params.url.match(/^glyphs:\/\/(.+)\/(\d+-\d+)$/);
    const name = decodeURIComponent(stack);
    const local = LOCAL_GLYPHS[name]?.includes(range);
    const url = local
      ? new URL(`basemap/fonts/${name.toLowerCase().replace(/ /g, '-')}/${range}.pbf`, location.href).href
      : `${OFM_FONTS}${stack}/${range}.pbf`;
    const res = await fetch(url, { signal: abort.signal });
    if (!res.ok) throw new Error(`glyphs ${res.status}`);
    return { data: await res.arrayBuffer() };
  });
}

// basemap/world.json -> GeoJSON. Coordinates are delta-encoded integers
// (hundredths of a degree; points in thousandths).
export function decodeWorld(rows) {
  const line = enc => {
    const out = [];
    let x = 0, y = 0;
    for (let i = 0; i < enc.length; i += 2) {
      x += enc[i];
      y += enc[i + 1];
      out.push([x / 100, y / 100]);
    }
    return out;
  };
  return {
    type: 'FeatureCollection',
    features: rows.map(([properties, t, c]) => ({
      type: 'Feature',
      properties,
      geometry: t === 'pt' ? { type: 'Point', coordinates: [c[0] / 1000, c[1] / 1000] }
        : t === 'l' ? { type: 'MultiLineString', coordinates: c.map(line) }
          : { type: 'MultiPolygon', coordinates: c.map(poly => poly.map(line)) },
    })),
  };
}

// boot: { positron, world } promises started early by index.html (optional).
// Runs before MapLibre has loaded; call addGlyphProtocol() once it has.
export async function buildStyle(theme, { globe = true } = {}, boot = {}) {
  const [positron, world] = await Promise.all([
    boot.positron || fetch('basemap/positron.json').then(r => r.json()),
    boot.world || fetch('basemap/world.json').then(r => r.json()),
  ]);
  const style = structuredClone(positron);
  const P = PALETTES[theme];
  const byId = id => style.layers.find(x => x.id === id);
  const paint = (id, props) => { const l = byId(id); if (l) l.paint = { ...l.paint, ...props }; };
  const layout = (id, props) => { const l = byId(id); if (l) l.layout = { ...l.layout, ...props }; };

  // No sprite: drop road shields and icons, keep the labels.
  delete style.sprite;
  style.layers = style.layers.filter(l => !/shield|^airport$/.test(l.id));
  for (const l of style.layers) if (l.layout) delete l.layout['icon-image'];
  delete style.sources.ne2_shaded;
  style.glyphs = 'glyphs://{fontstack}/{range}';

  // Detailed tiles only once zoomed in: MapLibre won't fetch a tile source
  // while none of its layers is visible.
  for (const l of style.layers) {
    if (l.source === 'openmaptiles') l.minzoom = Math.max(l.minzoom || 0, BASEMAP_MAX_ZOOM);
  }

  paint('background', { 'background-color': ['step', ['zoom'], P.water, COARSE_LAND_UNTIL, P.background] });
  paint('water', { 'fill-color': P.water });
  paint('park', { 'fill-color': P.park, 'fill-opacity': 0.9 });
  paint('landcover_wood', { 'fill-color': P.wood });
  paint('landcover_ice_shelf', { 'fill-color': P.ice });
  paint('landcover_glacier', { 'fill-color': P.ice });
  paint('landuse_residential', { 'fill-color': P.residential });
  paint('building', { 'fill-color': P.building, 'fill-outline-color': P.buildingLine });
  paint('waterway', { 'line-color': P.water });
  paint('road_area_pier', { 'fill-color': P.background });
  paint('road_pier', { 'line-color': P.background });
  for (const id of ['highway_path', 'highway_minor']) paint(id, { 'line-color': P.minor });
  paint('highway_major_casing', { 'line-color': P.roadCasing });
  paint('highway_major_inner', { 'line-color': P.road });
  paint('highway_major_subtle', { 'line-color': P.roadCasing });
  for (const id of ['highway_motorway_casing', 'highway_motorway_bridge_casing', 'tunnel_motorway_casing']) {
    paint(id, { 'line-color': P.motorwayCasing });
  }
  for (const id of ['highway_motorway_inner', 'highway_motorway_bridge_inner', 'tunnel_motorway_inner']) {
    paint(id, { 'line-color': P.motorway });
  }
  paint('highway_motorway_subtle', { 'line-color': P.roadCasing });
  for (const id of ['railway', 'railway_transit', 'railway_service']) paint(id, { 'line-color': P.rail });
  for (const id of ['railway_dashline', 'railway_transit_dashline', 'railway_service_dashline']) paint(id, { 'line-color': P.background });
  for (const id of ['boundary_2', 'boundary_3', 'boundary_disputed']) paint(id, { 'line-color': P.boundary });
  paint('aeroway-area', { 'fill-color': P.road });
  paint('aeroway-runway', { 'line-color': P.road });

  for (const l of style.layers) {
    if (l.type !== 'symbol') continue;
    const isWater = l.id.startsWith('water');
    const isCountry = l.id.startsWith('label_country');
    l.paint = {
      ...l.paint,
      'text-color': isWater ? P.waterLabel : isCountry ? P.country : /label_(other|state)|highway|waterway/.test(l.id) ? P.labelSoft : P.label,
      'text-halo-color': P.halo,
      'text-halo-width': 1.4,
      'text-halo-blur': 0.4,
    };
    if (l.id.startsWith('label_') || l.id.startsWith('water_name')) layout(l.id, { 'text-field': EN_NAME });
    if (isCountry) layout(l.id, { 'text-transform': 'uppercase', 'text-letter-spacing': 0.12 });
  }

  // Our world: coarse land and lakes under everything, borders under the
  // detailed labels, our labels on top.
  style.sources.world = {
    type: 'geojson', data: decodeWorld(world), maxzoom: BASEMAP_MAX_ZOOM, tolerance: 0.5,
    attribution: '<a href="https://www.naturalearthdata.com" target="_blank">Natural Earth</a>',
  };
  const kind = k => ['==', ['get', 'k'], k];
  const shown = ['<=', ['get', 'mz'], ['zoom']];
  const fills = [
    { id: 'world-land', type: 'fill', source: 'world', maxzoom: COARSE_LAND_UNTIL, filter: kind('land'), paint: { 'fill-color': P.background } },
    { id: 'world-lakes', type: 'fill', source: 'world', maxzoom: COARSE_LAND_UNTIL, filter: ['all', kind('lake'), shown], paint: { 'fill-color': P.water } },
  ];
  const lines = [
    {
      id: 'world-states', type: 'line', source: 'world', minzoom: 3, maxzoom: BASEMAP_MAX_ZOOM,
      filter: ['all', kind('state'), shown],
      paint: { 'line-color': P.state, 'line-width': 0.6, 'line-dasharray': [3, 2] },
    },
    {
      id: 'world-borders', type: 'line', source: 'world', maxzoom: BASEMAP_MAX_ZOOM, filter: kind('border'),
      paint: { 'line-color': P.boundary, 'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 5, 1.1] },
    },
  ];
  const halo = { 'text-halo-color': P.halo, 'text-halo-width': 1.4, 'text-halo-blur': 0.4 };
  const labels = [
    {
      id: 'world-seas', type: 'symbol', source: 'world', maxzoom: BASEMAP_MAX_ZOOM, filter: ['all', kind('sea'), shown],
      layout: {
        'text-field': ['get', 'n'], 'text-font': FONT, 'text-max-width': 6, 'text-letter-spacing': 0.15,
        'text-size': ['interpolate', ['linear'], ['zoom'], 1, ['case', ['==', ['get', 'o'], 1], 11, 9], 5, ['case', ['==', ['get', 'o'], 1], 14, 12]],
      },
      paint: { 'text-color': P.waterLabel, ...halo },
    },
    {
      id: 'world-cities-dot', type: 'circle', source: 'world', maxzoom: BASEMAP_MAX_ZOOM,
      filter: ['all', kind('city'), ['<=', ['get', 'mz'], ['+', ['zoom'], 0.5]]],
      paint: { 'circle-radius': ['case', ['==', ['get', 'cap'], 1], 2.6, 2], 'circle-color': P.labelSoft, 'circle-stroke-color': P.halo, 'circle-stroke-width': 1 },
    },
    {
      id: 'world-cities', type: 'symbol', source: 'world', maxzoom: BASEMAP_MAX_ZOOM,
      filter: ['all', kind('city'), ['<=', ['get', 'mz'], ['+', ['zoom'], 0.5]]],
      layout: {
        'text-field': ['get', 'n'], 'text-font': FONT, 'text-size': ['case', ['==', ['get', 'cap'], 1], 12, 11],
        'text-anchor': 'left', 'text-offset': [0.5, 0], 'symbol-sort-key': ['get', 'mz'],
      },
      paint: { 'text-color': P.label, ...halo },
    },
    {
      id: 'world-countries', type: 'symbol', source: 'world', maxzoom: BASEMAP_MAX_ZOOM, filter: ['all', kind('country'), shown],
      layout: {
        'text-field': ['get', 'n'], 'text-font': FONT, 'text-transform': 'uppercase', 'text-letter-spacing': 0.12,
        'text-max-width': 7, 'symbol-sort-key': ['get', 'r'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 1, 9, 3, 11, 5, 13],
      },
      paint: { 'text-color': P.country, ...halo },
    },
  ];
  const bg = style.layers.findIndex(l => l.id === 'background');
  style.layers.splice(bg + 1, 0, ...fills);
  const firstSymbol = style.layers.findIndex(l => l.type === 'symbol');
  style.layers.splice(firstSymbol, 0, ...lines);
  style.layers.push(...labels);

  if (globe) style.projection = { type: 'globe' };
  style.sky = { 'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 0.8, 4, 0.6, 7, 0] };
  return style;
}

// t = 0 (today) .. 1 (distant past)
export function ageFor(year) {
  if (year >= 1990) return 0;
  if (year <= 1750) return 1;
  return (1990 - year) / 240;
}

export function applyAge(map, theme, t) {
  const P = PALETTES[theme], A = AGED[theme];
  const set = (id, prop, val) => { if (map.getLayer(id)) map.setPaintProperty(id, prop, val); };
  const land = mix(P.background, A.background, t);
  const water = mix(P.water, A.water, t * 0.8);
  set('background', 'background-color', ['step', ['zoom'], water, COARSE_LAND_UNTIL, land]);
  set('world-land', 'fill-color', land);
  set('world-lakes', 'fill-color', water);
  set('water', 'fill-color', water);
  set('waterway', 'line-color', water);
  set('park', 'fill-color', mix(P.park, A.park, t));
  set('landcover_wood', 'fill-color', mix(P.wood, A.wood, t));
  set('landuse_residential', 'fill-color', mix(P.residential, A.residential, t));
  set('building', 'fill-color', mix(P.building, A.building, t));
  set('building', 'fill-opacity', 1 - 0.5 * t);
  const roadOpacity = 1 - 0.8 * t;
  for (const l of map.getStyle().layers) {
    if (!/^(highway|tunnel|railway|road_|aeroway)/.test(l.id)) continue;
    if (l.type === 'symbol') set(l.id, 'text-opacity', 1 - t);
    else set(l.id, l.type === 'fill' ? 'fill-opacity' : 'line-opacity', roadOpacity);
  }
}
