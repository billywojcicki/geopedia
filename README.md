# Geopedia

A map of history. Scroll around the world, drag the timeline, and see the Wikipedia articles for what happened there and then.

- **Zoomed out** you get the most notable things in the time window, spread across the globe.
- **Zoomed in** on a city you get the local stuff: every battle, riot, treaty, building and birth that Wikipedia knows about there, plus the places that already existed at that point in time.
- **The timeline** picks a year and a window around it (auto-sized by era, or pick your own). The map tints toward parchment and fades modern roads as you go back.
- **Click anything** to read the Wikipedia summary in the side panel, or the full article inline.
- Extras: search (`/`), "Surprise me", curated Journeys (American Revolution, WWII...), historical borders overlay, shareable URLs, play button, light/dark mode, phone layout.

## Run it

It's a static site, no build step.

```sh
python3 -m http.server 8000
# open http://localhost:8000
```

To host it, turn on GitHub Pages for the branch (Settings > Pages > Deploy from a branch, root folder). Any static host works.

## Layout

```
index.html, css/, js/     the site (vanilla JS modules, MapLibre GL from unpkg)
data/                     generated data the site loads (committed)
scripts/                  data pipeline (Python 3, stdlib only)
```

| File | What it does |
| --- | --- |
| `js/app.js` | State, map layers, sidebar list, article panel, search, URL state |
| `js/data.js` | Loads time buckets and spatial tiles on demand |
| `js/pins.js` | Greedy screen-space placement of labelled photo pins |
| `js/timeline.js` | Non-linear year scrubber with a density histogram |
| `js/basemap.js` | Restyles OpenFreeMap vector tiles, ages the map by year |
| `js/borders.js` | Historical borders overlay |
| `js/wiki.js` | Live Wikipedia summaries and full articles |

## Rebuilding the data

```sh
python3 scripts/fetch_wikidata.py   # ~2 min, caches CSVs in build/raw/
python3 scripts/build_data.py       # ~40 s, writes data/
```

`fetch_wikidata.py --force` refetches. Queries go to the [QLever](https://qlever.dev) Wikidata endpoint, which handles the big queries the official one times out on.

## How the content is chosen

Full Wikipedia text is tens of GB, so the static part is an index (title, place, date, short description, photo) and article text is fetched live from Wikipedia when you open something.

**Source.** Wikidata, because it has what Wikipedia articles lack: structured coordinates and dates. Every item must have an English Wikipedia article.

**What's on the map.** Three kinds of things:

1. **Events** with a date (`point in time`, or `start`/`end time`) and a place (own coordinates, or the coordinates of their `location` if that's a city or site; events located only in a whole country or ocean are dropped because a centroid is meaningless). About 40k.
2. **Places** with a founding date (`inception` or `opening date`): buildings, towns, institutions, historical states. They appear as a "Built / Founded / Established" event in their year, and when zoomed in they also appear (in grey) for every year they existed, until `dissolved/demolished` if known. About 250k.
3. **People** with 25+ Wikipedia language editions: births and deaths at the birth/death place. About 80k.

**Categories.** Each item's Wikidata class is walked up the subclass tree to its *nearest* known root: battles, sieges, wars, massacres go to War & conflict; treaties, protests, revolutions, assassinations, elections to Politics & society; earthquakes, fires, accidents, epidemics to Disasters; festivals, exhibitions, expeditions, major sports to Culture & science. Nearest matters because Wikidata's tree is messy (a protest is, eventually, a "conflict"; Paris is, eventually, an "electoral unit").

**Dropped as noise.** Sports seasons and matches (unless 40+ language editions, so World Cups and Olympics stay), award ceremonies, concert tours, eclipses, radio/TV stations, films, TV shows, languages, paintings and other artworks, modern countries (centroid coordinates), constituencies.

**Ranking.** Importance = number of Wikipedia language editions with an article (sitelinks), times a weight per kind, times 1.15 if there's a photo:

| Kind | Weight | Why |
| --- | --- | --- |
| War, politics | 1.0 | What the map is for |
| Disasters, culture | 0.9 | |
| Generic dated events | 0.75 | |
| Notable buildings | 0.65 | |
| Towns and cities | 0.3 | Every Wikipedia has an article on every city, so they'd swamp events |
| Institutions | 0.3 | Same problem |
| Deaths / births | 0.3 / 0.25 | Births mostly surface people famous decades later |
| Schools, stations, firms, counties | 0.15 | Kept for local colour when zoomed in |
| Big sports events | 0.5 | |

On the map, places that merely existed rank at a third of their score, and long events (wars, eras) are discounted by their length so the specific beats the general.

**Zoom.** Pins are placed greedily in priority order and skipped if they'd overlap one already placed, so the most notable things win at world scale and local ones appear as you zoom in. Small dots show everything else in the window.

**Time window.** Default half-width by era: ±2 years after 1900, ±5 after 1700, ±10 after 1500, ±20 after 1000, ±40 after AD 1, wider before that.

**Known gaps.** Things Wikidata lacks a date or coordinates for are missing (about 14k events are only located to a country). Sitelinks favour globally famous things over locally important ones, and Western topics over others. Births use the birthplace's city coordinates, so people stack on city centres. Pre-1500 coverage is thin.

## Credits

- Data: [Wikidata](https://www.wikidata.org) (CC0) and [Wikipedia](https://en.wikipedia.org) (CC BY-SA 4.0), images from Wikimedia Commons (various licenses)
- Basemap: [OpenFreeMap](https://openfreemap.org), [OpenMapTiles](https://openmaptiles.org), [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, [Natural Earth](https://www.naturalearthdata.com)
- Historical borders: [aourednik/historical-basemaps](https://github.com/aourednik/historical-basemaps) (GPL-3.0), loaded on demand
- Map rendering: [MapLibre GL JS](https://maplibre.org)
