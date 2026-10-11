// Basemap: OpenFreeMap vector tiles (OpenMapTiles schema), restyled.
// We start from their Positron style and repaint it with a softer, Apple-ish
// palette, add Natural Earth shaded relief at low zoom, and "age" the map
// (parchment tones, fading roads) as the timeline goes back in time.

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';

const PALETTES = {
  light: {
    background: '#f2f0eb', water: '#b4d6f1', waterLabel: '#4f7aa6', park: '#d6eacb', wood: '#dbe9d2',
    residential: '#ebe8e2', building: '#e5e2dc', buildingLine: '#d9d5ce', ice: '#fbfbfb',
    road: '#ffffff', roadCasing: '#e1ddd5', motorway: '#fde8b4', motorwayCasing: '#ecd29a',
    minor: '#ffffff', rail: '#d9d6d0', boundary: '#b7afa4',
    label: '#3a3a3c', labelSoft: '#6e6e73', country: '#55555a', halo: 'rgba(255,255,255,0.92)',
    relief: { opacity: 0.8, saturation: -0.25, contrast: -0.05, brightnessMin: 0.12, brightnessMax: 1 },
  },
  dark: {
    background: '#232325', water: '#1b2a3b', waterLabel: '#7a9cc0', park: '#22322a', wood: '#213027',
    residential: '#29292b', building: '#323235', buildingLine: '#3b3b3e', ice: '#3a3a3c',
    road: '#3e3e42', roadCasing: '#2c2c2f', motorway: '#6a5a36', motorwayCasing: '#4a3f27',
    minor: '#38383b', rail: '#3a3a3d', boundary: '#5f5f64',
    label: '#d1d1d6', labelSoft: '#98989d', country: '#aeaeb2', halo: 'rgba(28,28,30,0.9)',
    relief: { opacity: 0.45, saturation: -0.35, contrast: 0, brightnessMin: 0, brightnessMax: 0.5 },
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

export async function buildStyle(theme, { globe = true } = {}) {
  const style = await (await fetch(STYLE_URL)).json();
  const P = PALETTES[theme];
  const paint = (id, props) => {
    const l = style.layers.find(x => x.id === id);
    if (l) l.paint = { ...l.paint, ...props };
  };
  const layout = (id, props) => {
    const l = style.layers.find(x => x.id === id);
    if (l) l.layout = { ...l.layout, ...props };
  };

  paint('background', { 'background-color': P.background });
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
  for (const id of ['highway_major_casing']) paint(id, { 'line-color': P.roadCasing });
  for (const id of ['highway_major_inner']) paint(id, { 'line-color': P.road });
  paint('highway_major_subtle', { 'line-color': P.roadCasing });
  for (const id of ['highway_motorway_casing', 'highway_motorway_bridge_casing', 'tunnel_motorway_casing']) {
    paint(id, { 'line-color': P.motorwayCasing });
  }
  for (const id of ['highway_motorway_inner', 'highway_motorway_bridge_inner', 'tunnel_motorway_inner']) {
    paint(id, { 'line-color': ['interpolate', ['linear'], ['zoom'], 5.8, P.roadCasing, 6, P.motorway] });
  }
  paint('highway_motorway_subtle', { 'line-color': P.roadCasing });
  for (const id of ['railway', 'railway_transit', 'railway_service']) paint(id, { 'line-color': P.rail });
  for (const id of ['railway_dashline', 'railway_transit_dashline', 'railway_service_dashline']) paint(id, { 'line-color': P.background });
  for (const id of ['boundary_2', 'boundary_3', 'boundary_disputed']) paint(id, { 'line-color': P.boundary });
  for (const id of ['aeroway-area', 'aeroway-runway']) paint(id, { [id === 'aeroway-area' ? 'fill-color' : 'line-color']: P.road });

  for (const l of style.layers) {
    if (l.type !== 'symbol') continue;
    const isWater = l.id.startsWith('water');
    const isCountry = l.id.startsWith('label_country');
    l.paint = {
      ...l.paint,
      'text-color': isWater ? P.waterLabel : isCountry ? P.country : /label_(other|state)|highway|waterway|airport/.test(l.id) ? P.labelSoft : P.label,
      'text-halo-color': P.halo,
      'text-halo-width': 1.4,
      'text-halo-blur': 0.4,
    };
    if (l.id.startsWith('label_') || l.id.startsWith('water_name')) layout(l.id, { 'text-field': EN_NAME });
    if (isCountry) layout(l.id, { 'text-transform': 'uppercase', 'text-letter-spacing': 0.12 });
  }

  // Natural Earth shaded relief under everything, fading out as you zoom in.
  const bgIndex = style.layers.findIndex(l => l.id === 'background');
  style.layers.splice(bgIndex + 1, 0, {
    id: 'relief', type: 'raster', source: 'ne2_shaded', maxzoom: 8,
    paint: {
      'raster-opacity': ['interpolate', ['linear'], ['zoom'], 0, P.relief.opacity, 5, P.relief.opacity * 0.8, 7.5, 0],
      'raster-saturation': P.relief.saturation,
      'raster-contrast': P.relief.contrast,
      'raster-brightness-min': P.relief.brightnessMin,
      'raster-brightness-max': P.relief.brightnessMax,
      'raster-fade-duration': 0,
    },
  });

  if (globe) style.projection = { type: 'globe' };
  style.sky = {
    'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 0.8, 4, 0.6, 7, 0],
  };
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
  set('background', 'background-color', mix(P.background, A.background, t));
  set('water', 'fill-color', mix(P.water, A.water, t * 0.8));
  set('waterway', 'line-color', mix(P.water, A.water, t * 0.8));
  set('park', 'fill-color', mix(P.park, A.park, t));
  set('landcover_wood', 'fill-color', mix(P.wood, A.wood, t));
  set('landuse_residential', 'fill-color', mix(P.residential, A.residential, t));
  set('building', 'fill-color', mix(P.building, A.building, t));
  set('building', 'fill-opacity', 1 - 0.5 * t);
  set('relief', 'raster-saturation', P.relief.saturation - 0.55 * t);
  const roadOpacity = 1 - 0.8 * t;
  for (const l of map.getStyle().layers) {
    if (!/^(highway|tunnel|railway|road_|aeroway)/.test(l.id)) continue;
    if (l.type === 'symbol') {
      set(l.id, 'text-opacity', 1 - t);
      set(l.id, 'icon-opacity', 1 - t);
    } else {
      set(l.id, l.type === 'fill' ? 'fill-opacity' : 'line-opacity', roadOpacity);
    }
  }
}
