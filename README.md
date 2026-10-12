# Geopedia

A map of history. Scroll around the world, drag the timeline, and see the Wikipedia articles for what happened there and then.

- **Zoomed out** you get the most notable things in the time window, spread across the globe.
- **Zoomed in** on a city you get the local stuff: every battle, riot, treaty, building and birth that Wikipedia knows about there, plus the places that already existed at that point in time.
- **The timeline** picks a year and a window around it (auto-sized by era, or pick your own). The map tints toward parchment and fades modern roads as you go back.
- **Click anything** to read the Wikipedia summary in the side panel, or the full article inline.
- Extras: search (`/`), "Surprise me", curated Journeys (American Revolution, WWII...), historical borders (on by default before 1992), a night sky behind the globe (stars, the Milky Way, shooting stars; it swings the other way as the globe turns, like the view from a spacecraft), shareable links (Share button on every article), play button, light/dark mode.
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
basemap/                  self-hosted world basemap, map style, label fonts, historical borders (generated)
vendor/                   MapLibre GL, served from this site (fetched by the build)
scripts/                  data pipeline (Python 3, stdlib only)
```

| File | What it does |
| --- | --- |
| `js/app.js` | State, map layers, sidebar list, article panel, search, URL state |
| `js/search.js` | Search ranking |
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
python3 scripts/build_borders.py    # writes basemap/borders/ (rarely needs rerunning)
node scripts/social_card.mjs URL    # optional: re-shoot og.jpg and icons/ (needs Playwright)
```

`fetch_wikidata.py --force` refetches. Queries go to the [QLever](https://qlever.dev) Wikidata endpoint, which handles the big queries the official one times out on.

## Phones and in-app browsers

Built for the X / Twitter in-app browser as much as for Safari and Chrome:

- Bottom sheet instead of a sidebar in portrait; landscape phones get a compact side panel. Search opens the sheet fully; reading hides search, filters and the timeline.
- Uses dynamic viewport units and safe-area insets, so nothing sits under a notch, home bar or in-app toolbar. The search box is 16px so iOS doesn't zoom in on focus; pinching over the panels doesn't zoom the page.
- Touch targets: dot pins have a bigger invisible hit area and labels are tappable; no zoom buttons (pinch) and no hover cards on touch.
- The map renders at most at 2x pixel density (phones report 3x; it looks the same and draws much faster), and the background world prefetch is skipped on touch devices to save data.
- Link previews (iMessage, X, WhatsApp, Slack, Discord): Open Graph and Twitter card tags with `og.jpg`, a real screenshot at 2400x1260 (the wide ratio gets the large card). iMessage takes its small icon from the 180px `apple-touch-icon`. Previews are cached by image URL, so **bump `og.jpg?v=` in `index.html` whenever the image changes**. Regenerate the image and icons with `node scripts/social_card.mjs <site url>`.
- Also in place: PNG favicons next to the SVG one (Safari before 17, search results), a web app manifest with a maskable icon (Android home screens), a canonical URL, structured data for search engines, a `404.html` that sends stray links back to the map, a message for browsers without JavaScript, and no phone-number auto-linking of years on iOS.
- Everything points at `https://billywojcicki.github.io/geopedia/`; change `index.html` and `404.html` if the site moves to another domain.

## Performance

Still a plain static site. The speed comes from never downloading or drawing what the current view can't show.

**The night sky** (`js/space.js`) is two canvases behind the map: the stars and Milky Way are redrawn only when the camera moves (about 1 ms), shooting stars and twinkling repaint just their own few pixels at about 12 frames a second, and all of it stops once the globe fills the screen, in a background tab, or with reduced motion. To drop it, remove the `new Space(...)` line in `js/app.js`.

**Level-of-detail data.** The build gives every happening a `minzoom`: the first map zoom at which it's among the 8 most notable things in its 512px map tile and time slice (a year after 1500, longer slices before). Records are then grouped into tiers, like map tiles but with time:

| Tier | minzoom | Split by | Loaded when |
| --- | --- | --- | --- |
| `a/` | 0-3 | time chunks, whole world | always |
| `b/` | 4-5 | z2 map tiles x time chunks | zoom 3-6 |
| `c/` | 6-7 | z4 map tiles x time chunks | zoom 5-6 |
| `d/` | 4+ | small map areas, every era in one file | zoom >= 7 (instead of b/ and c/) |
| `p/` | places that existed | small map areas, every era | zoom >= 8.5 |

So the world view downloads only the world's top items for the window, and a city view downloads only that city (every era of it, so scrubbing the timeline there needs no network at all). Each chunk lists its last end year, so chunks that end before the window are skipped. Long happenings that only show zoomed in (`long-2.json`) load from zoom 4. Detail files are picked nearest the middle of the screen first.

**Shared links and search.** A shared link names the file holding its article (`&f=a/0-0-7`), so opening one is a single small fetch, often one the first view needs anyway. The search index comes in two parts: the 10k most notable entries (216 KB gzipped) answer the first keystroke, and the rest (700 KB) follows.

**Our own world basemap.** OpenFreeMap's world-level tiles are 300-700 KB each, so the default view used to pull ~5.5 MB of tiles (plus 1.2 MB of shaded-relief images) and showed a patchy map while they arrived. Below zoom 6 the map now draws only `basemap/world.json`: Natural Earth 1:50m land, lakes, borders and labels, simplified to what those zooms can show and delta-encoded, 170 KB gzipped. OpenFreeMap tiles load only from zoom 6, where they're smaller; our coarse land stays underneath until zoom 7.5 so the sea never flashes land-coloured while they arrive. The relief layer is gone (it was also why zooming in looked blurry).

**Historical borders, self-hosted.** The originals are 2-4 MB per era (600 KB gzipped from a CDN) and parsing one froze the page for most of a second. `scripts/build_borders.py` simplifies each era to about a pixel at zoom 5, 120 KB gzipped, and adds one label point per polity; the map's worker fetches and parses them, so changing era costs the page nothing. They load only once the map is idle, so they never slow the first view.

**Old maps vs. today's.** The basemap is always today's (OpenStreetMap streets and buildings, modern country borders and names); nobody has historical street data at world scale. Going back in time it shifts to a parchment tint and fades roads, railways and buildings (mostly gone by 1750). Before 1992 the historical borders overlay is on by default and hides modern borders and country names (in 1960 there's no Russia on the map, there's the Soviet Union); the Layers toggle overrides that.

**Names of their time.** Labels on the map and places in the articles' details use the name a place had in the year shown: Leningrad in 1950 (Petrograd in 1920), Stalingrad in 1942, Constantinople before 1930, Bombay before 1995, Edo before 1868, the Gold Coast before 1957, the Soviet Union for Russia from 1922 to 1991 (and its republics as SSRs), the German Empire, the Weimar Republic, Nazi Germany and Allied-occupied Germany, then East or West Germany by which side of the border a place lies (Berlin stays Berlin). One table, `basemap/old-names.json`, drives both the map (city, country and border labels, switched as the timeline crosses a renaming) and the data build. The border source's own labels are kept as they are and renamed through the same table ("USSR" shows as the Soviet Union).

**One origin for the first view.** MapLibre, the map style, the world basemap and the Latin glyphs of the label fonts (regular, and italic for historical borders, whose names are folded to those ranges at build time) are all served from this site, so the first view needs no third-party server at all (other glyph ranges still come from OpenFreeMap when needed).

**Startup.** `index.html` starts fetching the data index, map style and world basemap before any script runs, all JS modules are preloaded in parallel, and the app module runs before MapLibre (the biggest download) arrives, so the first view's data is already in flight. Pins and the sidebar list go up as soon as the data lands, without waiting for map tiles.

**Caching.** Data URLs carry a build hash (`?v=...`), so `sw.js` serves them cache-first forever and drops old versions. Map tiles, fonts, the basemap and MapLibre are cached too. The worker starts after the first visit has loaded, so on install it caches the boot files and the data files that visit already downloaded (from the HTTP cache): the second visit is as fast as later ones. The basemap is refreshed in the background at most once a day. Thumbnails that just failed (Wikimedia rate-limits) aren't asked for again for two minutes. Neighbouring time chunks are prefetched at low network priority, and on a fast connection all world-level chunks load in the background a few seconds after startup, so scrubbing the timeline zoomed out is instant.

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

1. **Events** with a date (`point in time`, or `start`/`end time`) and a place. The place is, in order: the event's own coordinates (unless they're just its country's centre point, like the Dissolution of the Soviet Union's in central Siberia); its `location` if that's a city or site; its `start point` (the Hijra from Mecca, a voyage's home port; not a plane crash's departure airport); its `located in` (P131) district or city. Countries, states, continents, oceans, seas, regions and anything over 20,000 km² are too vague to pin on. Notable events (10+ language editions) known only by one country, however big, like reforms, crises, revolutions and invasions, are pinned on that country's capital *of the time* (the Ottoman Empire's is Bursa, then Edirne, then Constantinople) and labelled with the country. National elections are left out of that fallback (they'd crowd every capital), and so are expeditions and meetings, which happened anywhere but there. Events located only in a few nearby regions (the Six-Day War: Sinai, Golan, West Bank) are pinned on the most central one.
   Notable events whose places are far apart (25+ language editions, 10+ for voyages and expeditions), or known only by one vague region (the "Arab world"), like the world wars, the Napoleonic Wars, the Hundred Years' War and the Crusades, have no pin at all: about 570 of them are listed as chips under the list's heading whenever one of their places is in view (sharp events before long eras; nothing over 400 years), are searchable, and opening one zooms out to show where they happened. About 40k events in all.
2. **Premieres, discoveries, launches and wrecks**: operas, plays and ballets at the theatre where they premiered, scientific discoveries where they were made (not chemical elements "discovered in Sweden"; sites like Lascaux and Tutankhamun's tomb where they are), spacecraft from their launch pad (Sputnik 1, Apollo 11), and ships where they sank (the Mary Rose, the Vasa, the Lusitania; dated by Wikidata's "significant event", 20+ language editions, and left out when the sinking has its own event pin, like the USS Arizona at Pearl Harbor). About 4.7k.
3. **Places** with a founding date (`inception` or `opening date`): buildings, towns, institutions, historical states. They appear as a "Built / Founded / Established" event in their year, and when zoomed in they also appear (in grey) for every year they existed, until `dissolved/demolished` if known. About 250k.
4. **People** with 25+ Wikipedia language editions: births and deaths at the birth/death place. About 80k. Off by default.

**Categories.** Each item's Wikidata class is walked up the subclass tree to its *nearest* known root. Nearest matters because Wikidata's tree is messy (a protest is, eventually, a "conflict"; Paris is, eventually, an "electoral unit"). On a tie, the more specific category wins over Politics, whose roots (meeting, ceremony) are broad.

| Category | What's in it |
| --- | --- |
| War & conflict | Battles, sieges, wars, raids, massacres, genocides, revolts, insurgencies, coups, military operations, mass shootings |
| Politics & society | Treaties, revolutions, reforms, protests, strikes, social movements, elections, summits, councils, coronations, scandals, trials, assassinations, economic crises and crashes |
| Disasters | Earthquakes, eruptions, floods, fires, famines, epidemics, shipwrecks, air and rail accidents |
| Arts & culture | Festivals, exhibitions, world's fairs, art movements, golden ages, premieres, the biggest sports events |
| Science & discovery | Expeditions, experiments, discoveries, space missions, launches, nuclear tests |
| Built & founded | Buildings, towns, institutions and states, in their founding year |
| Births & deaths | Off by default |

Events with no usable class get one from unambiguous title wording ("Battle of", "massacre", "mine disaster"); anything else unclassified shows under Politics & society, unless its class says it's a thing rather than something that happened (languages, offices and titles, car and weapon models, organisms, emergency numbers). A short hand-picked list (`KEEP_EVENTS` in `scripts/categories.py`) rescues famous moments that rule would catch: the Wow! signal, RDS-1, the Radium Girls.

**Dropped as noise.** Sports seasons and matches, and other yearly editions (pageants, film festivals, championships, drafts), unless 60+ language editions, so World Cups and Olympics stay. Award ceremonies and honours lists, holidays and national days, albums, opening ceremonies, single Olympic disciplines, concert tours, eclipses and saros series, Japanese era names, auto shows and fan conventions, Wikipedia meetups, local elections (municipal, mayoral, by-elections, party leaderships), radio/TV stations, films, TV shows, seasons and episodes, languages, paintings and other artworks, currencies, newspapers, ships and aircraft (the Titanic was built in 1909; its sinking has its own article), modern countries (centroid coordinates), constituencies, "List of" articles, a country's share of a pandemic ("COVID-19 pandemic in Italy").

**Bars by kind.** Some kinds of event only make the map when well known (language editions): one-off matches and fights (the Miracle on Ice, the Rumble in the Jungle) 20+, murders, ceremonies, conventions, national and papal elections 20+, meetings 12+, exhibitions 10+, individual deaths and crimes ("Killing of ...") 20+, launches 18+ (probes, landers and firsts like Pioneer 5, IM-1 and Ham the chimp's Mercury-Redstone 2), but crew rotations and numbered shuttle flights 25+ (STS-1 and Soyuz 11 stay, Soyuz TMA-9 goes). Assassinations always stay. `build/dropped.csv` lists every notable item left out and why.

**Dates.** As Wikidata shows them, not as its export stores them: dates before 1583 entered in the Julian calendar are converted back (the Battle of Hastings is 14 October 1066, not the 20th), centuries and millennia BC read as Wikidata means them (the 3rd century BC is 300-201 BC), deprecated statements are ignored and preferred ones win (the Battle of Marathon: 12 September 490 BC). A vague date (a decade, a century) doesn't stretch an event that also has a precise one. Stated spans read as spans: "16-19 Oct 1813", "6 Apr - 29 May 1453", "44 BC - AD 14". Rival dates of equal standing go to the one that isn't a 1 January (often a year typed as a day: the German Empire was proclaimed on 18 January 1871), then the earliest (Vesuvius, October 79). A treaty or law signed before it took effect shows its signing, not its years in force (the Lateran Treaty is 1929, not 1929-1985); a start after the end is treated as a typo. Events dated only by inception (the Rivonia Trial, the Atlantic Charter) use it.

**Hand fixes.** Some iconic events Wikidata can't place or date: no location at all (the East-West Schism, the Emancipation Proclamation, Hurricane Katrina), only a country (Magna Carta, the Edict of Nantes), or a vandalised date (the Battle of the Alamo said 11 September 2001). `scripts/overrides.csv` gives about 60 of them a place and date by hand (title, sitelinks, photo and description still come from Wikidata); after editing it, run `python3 scripts/fetch_wikidata.py --force manual` before the build. `build/dropped.csv` is the place to look for candidates.

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

**Search.** The index holds the 40k most notable happenings plus the 6k most notable places known only roughly ("founded 4th century BC": Paris, Rome, Babylon). Results rank by how well the title matches (exact, then prefix, then whole words, then anywhere), then by notability, with a nudge for events over places and people, so "waterloo" finds the battle before the station. "world war 2", "ww2" and "wwii" all find World War II.

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
- Historical borders: [aourednik/historical-basemaps](https://github.com/aourednik/historical-basemaps) (GPL-3.0), simplified and self-hosted in `basemap/borders/` (see `SOURCE.md` there)
- Map rendering: [MapLibre GL JS](https://maplibre.org) (BSD-3-Clause), vendored in `vendor/`
