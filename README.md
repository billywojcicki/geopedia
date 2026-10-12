# Geopedia

A map of history. Scroll around the world, drag the timeline, and see the Wikipedia articles for what happened there and then.

- **Zoomed out** you get the most notable things in the time window, spread across the globe.
- **Zoomed in** on a city you get the local stuff: every battle, riot, treaty, building and birth that Wikipedia knows about there, plus the places that already existed at that point in time.
- **The timeline** picks a year and a window around it (auto-sized by era, or pick your own). The map tints toward parchment and fades modern roads as you go back.
- **Click anything** to read the Wikipedia summary in the side panel, or the full article inline.
- Extras: search (`/`), "Surprise me", curated Journeys (American Revolution, WWII...), historical borders overlay, shareable links (Share button on every article), play button, light/dark mode.
- **On phones** the panel is a bottom sheet (peek, half, full) you drag by its top. Tapping a pin opens the article at half height with the pin centred in the map above it; tapping the map or swiping down puts it away.

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
| `js/sheet.js` | Phone bottom sheet: snap points, drag with momentum |
| `js/timeline.js` | Non-linear year scrubber with a density histogram |
| `js/basemap.js` | Our world basemap when zoomed out, restyled OpenFreeMap tiles when zoomed in, aged by year |
| `js/borders.js` | Historical borders overlay |
| `js/wiki.js` | Live Wikipedia summaries and full articles |

## Rebuilding the data

```sh
python3 scripts/fetch_wikidata.py   # ~2 min, caches CSVs in build/raw/
python3 scripts/build_data.py       # ~40 s, writes data/
python3 scripts/build_basemap.py    # writes basemap/ and vendor/ (rarely needs rerunning)
node scripts/social_card.mjs URL    # optional: re-shoot og.jpg and icons/ (needs Playwright)
```

`fetch_wikidata.py --force` refetches. Queries go to the [QLever](https://qlever.dev) Wikidata endpoint, which handles the big queries the official one times out on.

## Phones and in-app browsers

Built for the X / Twitter in-app browser as much as for Safari and Chrome:

- Bottom sheet instead of a sidebar in portrait; landscape phones get a compact side panel. Search opens the sheet fully; reading hides search, filters and the timeline.
- Uses dynamic viewport units and safe-area insets, so nothing sits under a notch, home bar or in-app toolbar. The search box is 16px so iOS doesn't zoom in on focus; pinching over the panels doesn't zoom the page.
- Touch targets: dot pins have a bigger invisible hit area and labels are tappable; no zoom buttons (pinch) and no hover cards on touch.
- The map renders at most at 2x pixel density (phones report 3x; it looks the same and draws much faster), and the background world prefetch is skipped on touch devices to save data.
- Link previews: Open Graph and Twitter card tags with `og.jpg` (a real screenshot) and app icons. The tags point at `https://billywojcicki.github.io/geopedia/`; change them in `index.html` if the site moves to another domain.

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

**What's on the map.** Events are the point; places and people are the backdrop.

1. **Events** with a date (`point in time`, or `start`/`end time`) and a place. The place is, in order: the event's own coordinates; its `location` if that's a city or site; its `located in` (P131) district or city. Notable events (10+ language editions) known only by country, like reforms, crises and revolutions, are pinned on that country's capital and labelled with the country. National elections are left out of that fallback (they'd crowd every capital). About 38k.
2. **Premieres and discoveries**: operas, plays and ballets at the theatre where they premiered, and scientific discoveries where they were made (not chemical elements "discovered in Sweden"). About 3.4k.
3. **Places** with a founding date (`inception` or `opening date`): buildings, towns, institutions, historical states. They appear as a "Built / Founded / Established" event in their year, and when zoomed in they also appear (in grey) for every year they existed, until `dissolved/demolished` if known. About 250k.
4. **People** with 25+ Wikipedia language editions: births and deaths at the birth/death place. About 80k. Off by default.

**Categories.** Each item's Wikidata class is walked up the subclass tree to its *nearest* known root. Nearest matters because Wikidata's tree is messy (a protest is, eventually, a "conflict"; Paris is, eventually, an "electoral unit"). On a tie, the more specific category wins over Politics, whose roots (meeting, ceremony) are broad.

| Category | What's in it |
| --- | --- |
| War & conflict | Battles, sieges, wars, raids, massacres, genocides, revolts, insurgencies, coups, military operations |
| Politics & society | Treaties, revolutions, reforms, protests, strikes, social movements, elections, summits, councils, coronations, scandals, assassinations, economic crises and crashes |
| Disasters | Earthquakes, eruptions, floods, fires, famines, epidemics, shipwrecks, air and rail accidents |
| Arts & culture | Festivals, exhibitions, world's fairs, art movements, golden ages, premieres, the biggest sports events |
| Science & discovery | Expeditions, experiments, discoveries, space missions, launches, nuclear tests |
| Built & founded | Buildings, towns, institutions and states, in their founding year |
| Births & deaths | Off by default |

Events with no usable class get one from unambiguous title wording ("Battle of", "massacre", "mine disaster"); anything else unclassified shows under Politics & society.

**Dropped as noise.** Sports seasons and matches, and other yearly editions (pageants, film festivals, championships, drafts), unless 40+ language editions, so World Cups and Olympics stay. Award ceremonies and honours lists, concert tours, eclipses, radio/TV stations, films, TV shows, languages, paintings and other artworks, currencies, newspapers, modern countries (centroid coordinates), constituencies, "List of" articles.

**Ranking.** Importance = number of Wikipedia language editions with an article (sitelinks), times a weight per kind, times 1.15 if there's a photo:

| Kind | Weight | Why |
| --- | --- | --- |
| War, politics | 1.0 | What the map is for |
| Disasters, culture, science, discoveries | 0.9 | |
| Premieres | 0.8 | |
| Generic dated events | 0.75 | |
| Big sports events | 0.5 | |
| Notable buildings | 0.5 | |
| Towns and cities | 0.25 | Every Wikipedia has an article on every city, so they'd swamp events |
| Institutions | 0.25 | Same problem |
| Deaths / births | 0.2 / 0.15 | Births mostly surface people famous decades later |
| Schools, stations, firms, counties | 0.1 | Kept for local colour when zoomed in |

Premieres and discoveries count at most 60 language editions, so a famous opera or element doesn't outrank a war. On the map, buildings, foundings and people rank at 0.6 of their score and places that merely existed at 0.35; long events (wars, eras) are discounted by their length so the specific beats the general.

**Zoom.** Pins are placed greedily in priority order and skipped if they'd overlap one already placed, so the most notable things win at world scale and local ones appear as you zoom in. Buildings, foundings, people and standing places get at most a third of the labels on screen, so events lead even in a city. Small dots show the rest of what is loaded for that zoom and window.

The data tiles have their own budget per zoom: each 512px tile keeps its 8 most notable events per time slice, but only its 2 most notable places and people, and those only from 2 zoom levels deeper. At world zoom (z0-3) that's about 22k events, 2.7k places and 1.8k people (it used to be 8.6k, 25k and 19.5k).

**Time window.** Default half-width by era: ±2 years after 1900, ±5 after 1700, ±10 after 1500, ±20 after 1000, ±40 after AD 1, wider before that.

**Known gaps.** Things Wikidata lacks a date or coordinates for are missing (about 180k dated events have no usable place; the notable country-only ones are on capitals). Sitelinks favour globally famous things over locally important ones, and Western topics over others. Births use the birthplace's city coordinates, so people stack on city centres. Pre-1500 coverage is thin.

## Open questions

Parked for later, to decide once we've used it more:

1. Should older eras get more attention, e.g. a different time window, more Journeys, or a lower bar for inclusion before 1500?
2. More categories? Candidates: religion (councils, schisms, crusades, pilgrimages, currently split between Politics and War), economy and trade (crashes, trade routes, companies, now in Politics), exploration (voyages, now in Science), sport as its own filter (now folded into Culture).

Decided: People is off by default; founding pins stay but are backdrop (capped share of labels, lower weight, a deeper zoom before they show).

## Credits

- Data: [Wikidata](https://www.wikidata.org) (CC0) and [Wikipedia](https://en.wikipedia.org) (CC BY-SA 4.0), images from Wikimedia Commons (various licenses)
- Basemap: [Natural Earth](https://www.naturalearthdata.com) (public domain) when zoomed out; [OpenFreeMap](https://openfreemap.org), [OpenMapTiles](https://openmaptiles.org), [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors when zoomed in. Label font: Noto Sans (SIL Open Font License)
- Historical borders: [aourednik/historical-basemaps](https://github.com/aourednik/historical-basemaps) (GPL-3.0), loaded on demand
- Map rendering: [MapLibre GL JS](https://maplibre.org) (BSD-3-Clause), vendored in `vendor/`
