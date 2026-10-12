#!/usr/bin/env python3
"""Build the self-hosted historical borders for the borders overlay.

Source: aourednik/historical-basemaps (GPL-3.0), one world GeoJSON per
snapshot year. The originals are 2-4 MB each; drawn at world and continent
scale they need far less, so each snapshot is simplified to about a pixel at
zoom 5 and written as two files the map's worker fetches and parses itself:

  basemap/borders/<key>.geojson         polities: {label, h (hue)}
  basemap/borders/<key>.labels.geojson  one label point per polity

Usage: python3 scripts/build_borders.py
"""
import json
import os

from build_basemap import ROOT, dump, get, label_point, ring_area, simplify

SOURCE = "https://cdn.jsdelivr.net/gh/aourednik/historical-basemaps@master/geojson/{}"
CACHE = os.path.join(ROOT, "build", "borders")
OUT = os.path.join(ROOT, "basemap", "borders")

# Must match SNAPSHOTS in js/borders.js.
SNAPSHOTS = [
    -123000, -10000, -8000, -5000, -4000, -3000, -2000, -1500, -1000, -700, -500, -400, -323, -300, -200, -100, -1,
    100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1279, 1300, 1400, 1492, 1500, 1530, 1600, 1650,
    1700, 1715, 1783, 1800, 1815, 1880, 1900, 1914, 1920, 1930, 1938, 1945, 1960, 1994, 2000, 2010,
]

DECIMALS = 2  # ~1 km
TOLERANCE = 0.02  # degrees, about a pixel at zoom 5 (the outlines are approximate anyway)
MIN_AREA = 0.002  # square degrees; smaller islands are dropped


def key(y):
    return f"bc{-y}" if y < 0 else str(y)


def hue(name):
    """Stable pastel hue per polity name."""
    h = 0
    units = name.encode("utf-16-le")
    for i in range(0, len(units), 2):
        h = (h * 31 + int.from_bytes(units[i:i + 2], "little")) & 0xFFFFFFFF
    return h % 360


def ring(r):
    if ring_area(r) < MIN_AREA:
        return None
    out = []
    for x, y in simplify(r, TOLERANCE):
        p = [round(x, DECIMALS), round(y, DECIMALS)]
        if not out or p != out[-1]:
            out.append(p)
    return out if len(out) >= 4 else None


def geometry(g):
    if not g or g["type"] not in ("Polygon", "MultiPolygon"):
        return None
    polys = []
    for poly in [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]:
        outer = ring(poly[0])
        if outer:
            polys.append([outer] + [r for r in map(ring, poly[1:]) if r])
    if not polys:
        return None
    return {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else {"type": "MultiPolygon", "coordinates": polys}


def build(y):
    name = f"world_{key(y)}.geojson"
    src = json.loads(get(SOURCE.format(name), os.path.join(CACHE, name)))
    shapes, labels = [], []
    for f in src["features"]:
        p = f.get("properties") or {}
        label = p.get("NAME") or p.get("SUBJECTO") or ""
        g = geometry(f.get("geometry"))
        if not label or not g:
            continue
        shapes.append({"type": "Feature", "geometry": g, "properties": {"label": label, "h": hue(p.get("SUBJECTO") or label)}})
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        area = max(ring_area(poly[0]) for poly in polys)
        x, yy = label_point(g)
        labels.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(x, 3), round(yy, 3)]},
                       "properties": {"label": label, "area": round(area, 2)}})
    # Bigger polities claim their label spot first.
    labels.sort(key=lambda f: -f["properties"]["area"])
    n = dump(os.path.join(OUT, f"{key(y)}.geojson"), {"type": "FeatureCollection", "features": shapes})
    n += dump(os.path.join(OUT, f"{key(y)}.labels.geojson"), {"type": "FeatureCollection", "features": labels})
    return n


def main():
    total = 0
    for y in SNAPSHOTS:
        n = build(y)
        total += n
        print(f"  {key(y)}: {n / 1e3:.0f} KB")
    print(f"borders: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
