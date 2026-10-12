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
index.html, css/, js/     the site (vanilla JS modules)
sw.js                     service worker (caching, see Performance)
data/                     generated history data the site loads (committed)
basemap/                  self-hosted world basemap, map style, label fonts (generated)
vendor/                   MapLibre GL, served from this site (fetched by the build)
scripts/                  data pipeline (Python 3, stdlib only)
```

| File | What it does |
| --- | --- |
| `js/app.js` | State, map layers, sidebar list, article panel, search, URL state |
| `js/data.js` | Works out which data files a view needs and loads them |
| `js/pins.js` | Greedy screen-space placement of labelled photo pins |
| `js/timeline.js` | Non-linear year scrubber with a density histogram |
| `js/basemap.js` | Our world basemap when zoomed out, restyled OpenFreeMap tiles when zoomed in, aged by year |
| `js/borders.js` | Historical borders overlay |
| `js/wiki.js` | Live Wikipedia summaries and full articles |

## Rebuilding the data

```sh
python3 scripts/fetch_wikidata.py   # ~2 min, caches CSVs in build/raw/
python3 scripts/build_data.py       # ~40 s, writes data/
python3 scripts/build_basemap.py    # writes basemap/ and vendor/ (rarely needs rerunning)
```

`fetch_wikidata.py --force` refetches. Queries go to the [QLever](https://qlever.dev) Wikidata endpoint, which handles the big queries the official one times out on.

## Performance

Still a plain static site. The speed comes from never downloading or drawing what the current view can't show.

**Level-of-detail data.** The build gives every happening a `minzoom`: the first map zoom at which it's among the 8 most notable things in its 512px map tile and time slice (a year after 1500, longer slices before). Records are then grouped into tiers, like map tiles but with time:

| Tier | minzoom | Split by | Loaded when |
| --- | --- | --- | --- |
| `a/` | 0-3 | time chunks, whole world | always |
| `b/` | 4-5 | z2 map tiles x time chunks | zoom >= 3 |
| `c/` | 6-7 | z4 map tiles x time chunks | zoom >= 5 |
| `d/` | 8+ | small map areas, every era in one file | zoom >= 7 |
| `p/` | places that existed | small map areas, every era | zoom >= 8.5 |

So the world view downloads only the world's top items for the window, and a city view downloads only that city (every era of it, so scrubbing the timeline there needs no network at all). The search index records which file holds each item, so opening a search result is one small fetch.

**Our own world basemap.** OpenFreeMap's world-level tiles are 300-700 KB each, so the default view used to pull ~5.5 MB of tiles (plus 1.2 MB of shaded-relief images) and showed a patchy map while they arrived. Below zoom 6 the map now draws only `basemap/world.json`: Natural Earth 1:50m land, lakes, borders and labels, simplified to what those zooms can show and delta-encoded, 170 KB gzipped. OpenFreeMap tiles load only from zoom 6, where they're smaller; our coarse land stays underneath until zoom 7.5 so the sea never flashes land-coloured while they arrive. The relief layer is gone (it was also why zooming in looked blurry).

**One origin for the first view.** MapLibre, the map style, the world basemap and the Latin glyphs of the label font are all served from this site, so the first view needs no third-party server at all (other glyph ranges still come from OpenFreeMap when needed).

**Startup.** `index.html` starts fetching the data index, map style and world basemap before any script runs, all JS modules are preloaded in parallel, and the app module runs before MapLibre (the biggest download) arrives, so the first view's data is already in flight. Pins and the sidebar list go up as soon as the data lands, without waiting for map tiles.

**Caching.** Data URLs carry a build hash (`?v=...`), so `sw.js` serves them cache-first forever and drops old versions. Map tiles, fonts, the basemap and MapLibre are cached too. Neighbouring time chunks are prefetched at low network priority, and on a fast connection all world-level chunks load in the background a few seconds after startup, so scrubbing the timeline zoomed out is instant.

**Main thread.** Timeline scrubbing and data arrivals are coalesced into at most one update per animation frame, and an update with nothing new skips the work. Pin placement measures text once and caches panel geometry.

**Images and reading.** Pins, list thumbnails and card placeholders share one 120px thumbnail URL, so it's downloaded once and shown instantly (blurry) while the sharper card or hero image loads. Hovering a pin or list row prefetches its Wikipedia summary, so clicking usually opens instantly.

Measured with a headless browser and a local server that gzips like GitHub Pages (software rendering, so absolute times are pessimistic):

| | First version | Now |
| --- | --- | --- |
| Time to first pins | 7.1 s | ~1.3-1.7 s, nearly all of it WebGL setup in the software renderer |
| Everything downloaded for the first view | ~8.5 MB from 3 servers | ~0.8 MB, all from this site (plus photo thumbnails) |
| History data for the first view | 1.3 MB | 0.25 MB |
| Data for scrubbing 1700 to 2000, zoomed out | 10.6 MB | ~2 MB (0 once prefetched) |
| Main-thread JS per timeline step | up to 120 ms | ~1-3 ms |
| Repeat visit, first pins | same as first | ~1.0 s, served by the service worker |

Ideas not done yet: precomputed Wikipedia extracts for the most-opened articles; a lighter tile source for zoom 6-8, where OpenFreeMap tiles are still 150-300 KB each (VersaTiles tiles are 2-4x smaller but its servers are slower); a binary record format (JSON parsing isn't a bottleneck yet).

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

**Zoom.** Pins are placed greedily in priority order and skipped if they'd overlap one already placed, so the most notable things win at world scale and local ones appear as you zoom in. Small dots show the rest of what is loaded for that zoom and window.

**Time window.** Default half-width by era: ±2 years after 1900, ±5 after 1700, ±10 after 1500, ±20 after 1000, ±40 after AD 1, wider before that.

**Known gaps.** Things Wikidata lacks a date or coordinates for are missing (about 14k events are only located to a country). Sitelinks favour globally famous things over locally important ones, and Western topics over others. Births use the birthplace's city coordinates, so people stack on city centres. Pre-1500 coverage is thin.

## Open questions

Parked for later, to decide once we've used it more:

1. Should People be off by default? It's the noisiest category (births mostly surface people famous decades later).
2. More or fewer founding pins (towns, buildings) relative to events?
3. Should older eras get more attention, e.g. a different time window, more Journeys, or a lower bar for inclusion before 1500?

## Credits

- Data: [Wikidata](https://www.wikidata.org) (CC0) and [Wikipedia](https://en.wikipedia.org) (CC BY-SA 4.0), images from Wikimedia Commons (various licenses)
- Basemap: [Natural Earth](https://www.naturalearthdata.com) (public domain) when zoomed out; [OpenFreeMap](https://openfreemap.org), [OpenMapTiles](https://openmaptiles.org), [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors when zoomed in. Label font: Noto Sans (SIL Open Font License)
- Historical borders: [aourednik/historical-basemaps](https://github.com/aourednik/historical-basemaps) (GPL-3.0), loaded on demand
- Map rendering: [MapLibre GL JS](https://maplibre.org) (BSD-3-Clause), vendored in `vendor/`
