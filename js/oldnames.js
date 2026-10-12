// Names of their time on the map: Leningrad in 1950, Constantinople in 1700,
// the Soviet Union rather than Russia, the Gold Coast rather than Ghana. The
// table (basemap/old-names.json) is shared with the data build, which renames
// the places in the article index the same way.

const TABLE_URL = new URL('basemap/old-names.json', document.baseURI).href;

// Which label layers take which kind of name.
const COUNTRY_LAYERS = /^(world-countries|label_country|borders-label)/;
const CITY_LAYERS = /^(world-cities$|label_city|label_town|label_village)/;

let table = null;
let loading = null;
const applied = new WeakMap(); // style layer -> { orig, sig }

export function loadOldNames() {
  loading ??= fetch(TABLE_URL).then(r => r.json()).then(t => { table = t; }).catch(() => { loading = null; });
  return loading;
}

// [[current name, name of the time], ...] for one kind of place in a year.
function renames(entries, year) {
  const out = new Map();
  for (const e of entries) {
    const era = e.eras.find(([from, to]) => (from === null || from <= year) && (to === null || year < to));
    if (!era) continue;
    for (const n of e.names) if (n !== era[2] && !out.has(n)) out.set(n, era[2]);
  }
  return [...out];
}

// Point the label layers at the names of `year`. Cheap when nothing changed
// (the usual case while scrubbing), so it runs on every year change.
export function applyOldNames(map, year) {
  if (!table || !map) return;
  const kinds = { country: renames(table.countries, year), city: renames(table.cities, year) };
  const sigs = { country: JSON.stringify(kinds.country), city: JSON.stringify(kinds.city) };
  for (const id of map.getLayersOrder()) {
    const kind = COUNTRY_LAYERS.test(id) ? 'country' : CITY_LAYERS.test(id) ? 'city' : null;
    const layer = kind && map.getLayer(id);
    if (!layer || layer.type !== 'symbol') continue;
    // Keyed by the layer object: a new style or a re-added layer starts over.
    let s = applied.get(layer);
    if (!s) applied.set(layer, s = { orig: map.getLayoutProperty(id, 'text-field'), sig: '[]' });
    if (s.sig === sigs[kind]) continue;
    s.sig = sigs[kind];
    const pairs = kinds[kind];
    map.setLayoutProperty(id, 'text-field', pairs.length
      ? ['match', ['to-string', s.orig], ...pairs.flat(), s.orig]
      : s.orig);
  }
}
