#!/usr/bin/env python3
"""Build the self-hosted world basemap and vendor the map's third-party assets.

Zoomed out (below BASEMAP_MAX_ZOOM in js/basemap.js) the map draws only what
this script produces, all served from our own origin:

  basemap/world.json      Natural Earth 1:50m land, lakes, borders and labels,
                          simplified to what a world/continent view needs, with
                          coordinates delta-encoded (decoded by js/basemap.js)
  basemap/positron.json   OpenFreeMap's Positron style, used for zoomed-in detail
  basemap/fonts/...       Latin glyph ranges for the label fonts
  vendor/maplibre-gl@...  the MapLibre GL build

Zoomed in, the map switches to OpenFreeMap vector tiles, whose world-level
tiles are far too heavy (300-700 KB each) for a fast first view.

Usage: python3 scripts/build_basemap.py
"""
import json
import math
import os
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "build", "ne")
OUT = os.path.join(ROOT, "basemap")
UA = "GeopediaBuild/0.1 (https://github.com/billywojcicki/geopedia)"

NE = "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/{}.geojson"
STYLE = "https://tiles.openfreemap.org/styles/positron"
FONTS = "https://tiles.openfreemap.org/fonts/{}/{}.pbf"
FONT_STACKS = ["Noto Sans Regular", "Noto Sans Italic"]  # labels; italic is for historical borders
FONT_RANGES = ["0-255", "256-511", "8192-8447"]  # Latin-1, Latin Extended-A, punctuation
MAPLIBRE = "maplibre-gl@5.24.0"

DECIMALS = 2  # ~1 km: under a pixel at zoom 5
TOLERANCE = 0.02  # Douglas-Peucker tolerance in degrees, about a pixel at zoom 5
MIN_AREA = 0.004  # square degrees; smaller islands and lakes are dropped
MAX_ZOOM = 6  # must match BASEMAP_MAX_ZOOM in js/basemap.js


def get(url, path=None):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return data


def ne(name):
    return json.loads(get(NE.format(name), os.path.join(CACHE, f"{name}.geojson")))


def simplify(pts, tol):
    """Douglas-Peucker, iterative."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x0, y0), (x1, y1) = pts[a], pts[b]
        dx, dy = x1 - x0, y1 - y0
        norm = math.hypot(dx, dy) or 1e-12
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / norm if (dx or dy) else math.hypot(x - x0, y - y0)
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(ring):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:]))) / 2


def round_ring(ring, closed):
    if closed and ring_area(ring) < MIN_AREA:
        return None
    ring = simplify(ring, TOLERANCE)
    out = []
    for x, y in ring:
        p = [round(x, DECIMALS), round(y, DECIMALS)]
        if not out or p != out[-1]:
            out.append(p)
    if closed and len(out) < 4:
        return None
    if not closed and len(out) < 2:
        return None
    return out


def round_geom(g):
    t, c = g["type"], g["coordinates"]
    if t in ("Polygon", "MultiPolygon"):
        polys = []
        for poly in ([c] if t == "Polygon" else c):
            outer = round_ring(poly[0], True)
            if outer:
                polys.append([outer] + [r for r in (round_ring(r, True) for r in poly[1:]) if r])
        if not polys:
            return None
        return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}
    if t == "LineString":
        r = round_ring(c, False)
        return {"type": t, "coordinates": r} if r else None
    if t == "MultiLineString":
        lines = [r for r in (round_ring(l, False) for l in c) if r]
        return {"type": t, "coordinates": lines} if lines else None
    return g


def feature(geom, **props):
    return {"type": "Feature", "geometry": geom, "properties": props}


SCALE = 10 ** DECIMALS


def encode_line(pts):
    """[x0, y0, dx1, dy1, ...] in 1/SCALE degree units: small ints compress well."""
    out, px, py = [], 0, 0
    for x, y in pts:
        ix, iy = round(x * SCALE), round(y * SCALE)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def encode(f):
    """Feature -> [props, type, coords] with delta-encoded coordinates."""
    g, props = f["geometry"], f["properties"]
    t, c = g["type"], g["coordinates"]
    if t == "Point":
        return [props, "pt", [round(c[0] * 1000), round(c[1] * 1000)]]
    if t == "LineString":
        return [props, "l", [encode_line(c)]]
    if t == "MultiLineString":
        return [props, "l", [encode_line(l) for l in c]]
    polys = [c] if t == "Polygon" else c
    return [props, "p", [[encode_line(r) for r in poly] for poly in polys]]


def point(lng, lat):
    return {"type": "Point", "coordinates": [round(lng, 3), round(lat, 3)]}


def ring_area_centroid(ring):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if not a:
        return 0, ring[0]
    return abs(a / 2), (cx / (3 * a), cy / (3 * a))


def label_point(geom):
    """Centroid of the largest outer ring: good enough for seas and oceans."""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    best = max((ring_area_centroid(p[0]) for p in polys), key=lambda t: t[0])
    return best[1]


def build_world():
    feats = []
    for f in ne("ne_50m_land")["features"]:
        g = round_geom(f["geometry"])
        if g:
            feats.append(feature(g, k="land"))
    for f in ne("ne_50m_lakes")["features"]:
        p = f["properties"]
        if (p.get("scalerank") or 0) > 4:
            continue
        g = round_geom(f["geometry"])
        if g:
            feats.append(feature(g, k="lake", mz=p.get("min_zoom") or 0))
    for f in ne("ne_50m_admin_0_boundary_lines_land")["features"]:
        g = round_geom(f["geometry"])
        if g:
            disputed = "Disputed" in (f["properties"].get("FEATURECLA") or "")
            feats.append(feature(g, k="border", d=1 if disputed else 0))
    for f in ne("ne_50m_admin_1_states_provinces_lines")["features"]:
        g = round_geom(f["geometry"])
        if g:
            feats.append(feature(g, k="state", mz=f["properties"].get("MIN_ZOOM") or 3))
    for f in ne("ne_50m_admin_0_countries")["features"]:
        p = f["properties"]
        if p.get("LABEL_X") is None:
            continue
        feats.append(feature(point(p["LABEL_X"], p["LABEL_Y"]), k="country",
                             n=p.get("NAME_EN") or p["NAME"], mz=p.get("MIN_LABEL") or 2, r=p.get("LABELRANK") or 5))
    for f in ne("ne_50m_geography_marine_polys")["features"]:
        p = f["properties"]
        name = p.get("name_en") or p.get("name")
        if not name:
            continue
        x, y = label_point(f["geometry"])
        feats.append(feature(point(x, y), k="sea", n=name, mz=p.get("min_label") or 3,
                             o=1 if p.get("featurecla") == "ocean" else 0))
    for f in ne("ne_50m_populated_places")["features"]:
        p = f["properties"]
        if (p.get("MIN_ZOOM") or 5) > MAX_ZOOM:
            continue  # only shows once zoomed in, where OpenFreeMap takes over
        lng, lat = f["geometry"]["coordinates"]
        feats.append(feature(point(lng, lat), k="city", n=p.get("NAME_EN") or p["NAME"],
                             mz=p.get("MIN_ZOOM") or 5, cap=1 if p.get("ADM0CAP") else 0))
    return [encode(f) for f in feats]


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def main():
    n = dump(os.path.join(OUT, "world.json"), build_world())
    print(f"world.json: {n / 1e3:.0f} KB")

    style = json.loads(get(STYLE))
    n = dump(os.path.join(OUT, "positron.json"), style)
    print(f"positron.json: {n / 1e3:.0f} KB")

    for stack in FONT_STACKS:
        for rng in FONT_RANGES:
            path = os.path.join(OUT, "fonts", stack.lower().replace(" ", "-"), f"{rng}.pbf")
            data = get(FONTS.format(urllib.parse.quote(stack), rng))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
    print(f"fonts: {len(FONT_STACKS) * len(FONT_RANGES)} files")

    for name, src in [("maplibre-gl.js", "dist/"), ("maplibre-gl.css", "dist/"), ("LICENSE.txt", "")]:
        path = os.path.join(ROOT, "vendor", MAPLIBRE, name)
        data = get(f"https://unpkg.com/{MAPLIBRE}/{src}{name}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    print(f"vendored {MAPLIBRE}")


if __name__ == "__main__":
    main()
