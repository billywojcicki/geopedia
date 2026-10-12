// Ranking for the search box. The index (data/search.json) holds the ~40k
// most notable items, most notable first. A result's rank is how well its
// title matches, then how notable it is, with a nudge for things that
// happened over places and people: "waterloo" means the battle.

import { HAPPENED } from './config.js';
import { normalize } from './data.js';

const ROMAN = ['', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',
  'xi', 'xii', 'xiii', 'xiv', 'xv', 'xvi', 'xvii', 'xviii', 'xix', 'xx'];

// Whole-query shorthands.
const ALIASES = {
  ww1: 'world war i', wwi: 'world war i', ww2: 'world war ii', wwii: 'world war ii',
  '9/11': 'september 11 attacks', ussr: 'soviet union', usa: 'united states', uk: 'united kingdom',
};

const EXACT = 130, PREFIX = 60, WORDS = 50, ANYWHERE = 10;
const HAPPENED_BONUS = 12;
const RANK_WEIGHT = 4.5; // points lost per halving of notability

// Ways to read the query: as typed, numbers as Roman numerals ("world war 2"),
// and a known shorthand ("ww2").
function variants(q) {
  const out = [q];
  const roman = q.replace(/\b(\d{1,2})\b/g, (m, n) => ROMAN[+n] || m);
  if (roman !== q) out.push(roman);
  if (ALIASES[q]) out.push(ALIASES[q]);
  return out.map(v => ({ v, words: v.split(/\s+/) }));
}

// Title without a trailing disambiguation: "Treaty of Paris (1898)".
function core(norm) {
  return norm.replace(/\s*\([^)]*\)$/, '');
}

function matchScore(norm, { v, words }) {
  if (!words.every(w => norm.includes(w))) return -1;
  const c = core(norm);
  if (c === v || norm === v) return EXACT;
  if (c.startsWith(v)) return PREFIX;
  const padded = ' ' + norm;
  if (words.every(w => padded.includes(' ' + w))) return WORDS;
  return ANYWHERE;
}

// entries: search index rows with a `norm` title, in notability order.
export function rankSearch(entries, query, limit = 8) {
  const q = normalize(query.trim()).replace(/\s+/g, ' ');
  if (q.length < 2) return [];
  const vs = variants(q);
  const scored = [];
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    let m = -1;
    for (const v of vs) m = Math.max(m, matchScore(e.norm, v));
    if (m < 0) continue;
    const s = m - RANK_WEIGHT * Math.log2(i + 1) + (HAPPENED.has(e.kind) ? HAPPENED_BONUS : 0);
    scored.push([s, e]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, limit).map(x => x[1]);
}
