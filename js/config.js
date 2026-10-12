// Static configuration: categories, timeline scale, journeys.

// Order must match CATEGORIES in scripts/categories.py.
export const CATEGORIES = [
  { id: 'conflict', name: 'War & conflict', short: 'War' },
  { id: 'politics', name: 'Politics & society', short: 'Politics' },
  { id: 'disaster', name: 'Disasters', short: 'Disasters' },
  { id: 'culture', name: 'Arts & culture', short: 'Culture' },
  { id: 'science', name: 'Science & discovery', short: 'Science' },
  { id: 'built', name: 'Built & founded', short: 'Built' },
  { id: 'people', name: 'Births & deaths', short: 'People', off: true }, // off by default
];

// Record kinds (index = kind code in the data files).
export const KIND_VERB = ['', 'Built', 'Founded', 'Established', 'Born', 'Died', 'Premiered', 'Discovered', 'Launched', 'Sank'];
export const KIND = { EVENT: 0, BUILT: 1, FOUNDED: 2, ESTABLISHED: 3, BORN: 4, DIED: 5, PREMIERED: 6, DISCOVERED: 7, LAUNCHED: 8, SANK: 9 };
// Things that happened, as opposed to places and lives (which rank lower).
export const HAPPENED = new Set([KIND.EVENT, KIND.PREMIERED, KIND.DISCOVERED, KIND.LAUNCHED, KIND.SANK]);

export const MIN_YEAR = -10000;
export const MAX_YEAR = 2026;

// Piecewise-linear slider scale: [year, position 0..1]. Recent centuries get
// more room because that's where most of the record is.
export const TIME_ANCHORS = [
  [-10000, 0], [-3000, 0.05], [-500, 0.15], [0, 0.21], [500, 0.28], [1000, 0.36],
  [1500, 0.48], [1700, 0.58], [1800, 0.67], [1900, 0.79], [1950, 0.88], [MAX_YEAR, 1],
];
export const TICKS = [-3000, -1000, 1, 500, 1000, 1500, 1700, 1800, 1900, 1950, 2000];

// Default half-width of the time window, by era: sparse eras get wider windows.
export function autoSpan(y) {
  if (y >= 1900) return 2;
  if (y >= 1700) return 5;
  if (y >= 1500) return 10;
  if (y >= 1000) return 20;
  if (y >= 0) return 40;
  if (y >= -1000) return 75;
  return 150;
}

// Zoom at which places that merely *existed* (not founded in the window) appear.
export const STANDING_ZOOM = 9;

const bc = n => 1 - n; // 450 BC -> astronomical -449

export const JOURNEYS = [
  { name: 'Ancient Egypt', year: bc(2560), span: 150, center: [31.2, 28.5], zoom: 5 },
  { name: 'Classical Greece', year: bc(450), span: 40, center: [23.5, 38.6], zoom: 5.6 },
  { name: 'Roman Empire', year: 100, span: 40, center: [14, 41.5], zoom: 4.2 },
  { name: 'Han & Rome', year: 100, span: 50, center: [70, 35], zoom: 2.2 },
  { name: 'Viking Age', year: 870, span: 40, center: [4, 56], zoom: 3.8 },
  { name: 'The Crusades', year: 1160, span: 60, center: [33, 35], zoom: 4.3 },
  { name: 'Mongol Empire', year: 1240, span: 30, center: [85, 45], zoom: 2.8 },
  { name: 'Italian Renaissance', year: 1490, span: 25, center: [11.5, 43.6], zoom: 6 },
  { name: 'Age of Discovery', year: 1510, span: 25, center: [-35, 15], zoom: 1.8 },
  { name: 'American Revolution', year: 1777, span: 6, center: [-73.2, 41.2], zoom: 5.6 },
  { name: 'French Revolution', year: 1791, span: 4, center: [2.35, 48.8], zoom: 5.5 },
  { name: 'Napoleonic Wars', year: 1807, span: 8, center: [12, 50], zoom: 3.9 },
  { name: 'Industrial Britain', year: 1840, span: 20, center: [-2.2, 53.2], zoom: 6 },
  { name: 'American Civil War', year: 1863, span: 2, center: [-79.5, 37.5], zoom: 5.4 },
  { name: 'World War I', year: 1916, span: 2, center: [4, 49.6], zoom: 5.6 },
  { name: 'World War II', year: 1942, span: 3, center: [18, 47], zoom: 3.4 },
  { name: 'Civil rights era', year: 1963, span: 4, center: [-86.5, 33.5], zoom: 5.2 },
  { name: 'Fall of the Wall', year: 1989, span: 1, center: [13.4, 52.5], zoom: 5 },
  { name: 'Today', year: MAX_YEAR, span: 1, center: null, zoom: null },
];

export const DEFAULT_VIEW = { year: 1776, span: 'auto', center: [-35, 30], zoom: 2.1 };
