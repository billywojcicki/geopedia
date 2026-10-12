// Service worker: makes repeat visits fast by serving things that never change
// from a local cache.
//
// - data/*.json?v=<version>: cache-first. The version is a hash of the build,
//   so a file at a given URL never changes; old versions are dropped.
// - vendor/<lib>@<version>/: cache-first (versioned path).
// - basemap/: stale-while-revalidate (instant, refreshed in the background).
// - OpenFreeMap tiles and fonts: cache-first (versioned URLs), with the tile
//   cache trimmed so it can't grow without bound; its tile index is
//   stale-while-revalidate.
// - Everything else (the app itself, data/index.json, Wikipedia): network, so
//   a new deploy is picked up on the next load.

const LIB = 'lib-v1';
const TILES = 'tiles-v1';
const MAX_TILES = 4000;
let dataVersion = null;
let puts = 0;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.origin === location.origin) {
    const v = url.searchParams.get('v');
    if (v && url.pathname.includes('/data/')) e.respondWith(dataFile(req, v));
    else if (url.pathname.includes('/vendor/')) e.respondWith(cacheFirst(LIB, req));
    else if (url.pathname.includes('/basemap/')) e.respondWith(staleWhileRevalidate(LIB, req));
    return;
  }
  if (url.hostname === 'tiles.openfreemap.org') {
    const versioned = /\.(pbf|png|jpg|webp|json)$/.test(url.pathname) && !url.pathname.startsWith('/styles/');
    e.respondWith(versioned ? cacheFirst(TILES, req, true) : staleWhileRevalidate(TILES, req));
  }
});

async function dataFile(req, v) {
  const name = `data-${v}`;
  if (dataVersion !== v) {
    dataVersion = v;
    // A new build is live: drop caches of older ones (in the background).
    caches.keys().then(keys => keys.filter(k => k.startsWith('data-') && k !== name).forEach(k => caches.delete(k)));
  }
  return cacheFirst(name, req);
}

async function cacheFirst(name, req, trim = false) {
  const cache = await caches.open(name);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) {
    cache.put(req, res.clone());
    if (trim && ++puts % 100 === 0) trimCache(cache);
  }
  return res;
}

async function staleWhileRevalidate(name, req) {
  const cache = await caches.open(name);
  const hit = await cache.match(req);
  const fresh = fetch(req).then(res => {
    if (res.ok) cache.put(req, res.clone());
    return res;
  });
  if (hit) {
    fresh.catch(() => {});
    return hit;
  }
  return fresh;
}

async function trimCache(cache) {
  const keys = await cache.keys();
  // Oldest entries come first.
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(k);
}
