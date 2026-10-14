#!/usr/bin/env python3
"""Build year-by-year borders for 1886 onwards from CShapes 2.0.

CShapes (Schvitz, Girardin, Rüegger, Weidmann, Cederman, Gleditsch 2022,
CC BY-NC-SA 4.0) maps every state and colony from 1886 to 2019 with the
dates each outline held. It ships as TopoJSON inside the CRAN package; this
reads it from the source tarball (data only, nothing in it is run).

Shared borders are simplified once, on the topology's arcs, so neighbours
still meet exactly. Outlines nobody would see (those that never span a
1 July, the moment a year on the map stands for) are dropped, and an outline
that comes back unchanged after simplifying is merged with its neighbour in
time. The output is one small topology the site decodes once in a worker
(js/cshapes.js), which then hands the map one year's outlines at a time:

  basemap/borders/cshapes.json  {q, arcs, shapes}
    arcs:   [x0, y0, dx, dy, ...] in 1/q degrees
    shapes: [label, hue, [s, e, s, e, ...], label lng, label lat, area,
             [[outer ring's arc ids, hole's ids, ...], ...]]

s and e are fractional years (e exclusive); the last outlines run on (e 9999).
An arc id ~i is arc i reversed.
Labels are current names; the map shows them as names of their time
(basemap/old-names.json), plus a few set here by date (the two Germanys).

Usage: python3 scripts/build_cshapes.py
"""
import datetime
import io
import json
import lzma
import os
import tarfile

from build_basemap import ROOT, dump, get, label_point, simplify
from build_borders import MIN_AREA, TOLERANCE, hue

SOURCES = [
    "https://cran.r-project.org/src/contrib/cshapes_2.0.tar.gz",
    "https://cran.r-project.org/src/contrib/Archive/cshapes/cshapes_2.0.tar.gz",
]
Q = 100  # coordinates are stored in 1/Q degrees (~1 km)
MEMBER = "cshapes/inst/extdata/cshapes_2_cow.topojson.xz"  # COW: has the microstates
CACHE = os.path.join(ROOT, "build", "cshapes", "cshapes_2.0.tar.gz")
OUT = os.path.join(ROOT, "basemap", "borders")
LAST = "2019-12-31"  # the data's end: outlines still standing run on
FIRST_YEAR = 1886  # must match CSHAPES_FROM in js/borders.js

# CShapes names -> the names old-names.json and the map know.
NAMES = {
    "Antigua & Barbuda": "Antigua and Barbuda",
    "Belarus (Byelorussia)": "Belarus",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "British Somaliland (Somaliland Republic)": "British Somaliland",
    "Burkina Faso (Upper Volta)": "Burkina Faso",
    "Cambodia (Kampuchea)": "Cambodia",
    "Congo, Democratic Republic of (Zaire)": "Democratic Republic of the Congo",
    "Cote D'Ivoire": "Ivory Coast",
    "Danzig": "Free City of Danzig",
    "French Guyana": "French Guiana",
    "Gaza": "Gaza Strip",
    "Germany (Prussia)": "Germany",
    "Iran (Persia)": "Iran",
    "Italy/Sardinia": "Italy",
    "Korea, People's Republic of": "North Korea",
    "Korea, Republic of": "South Korea",
    "Kashmir (North, Azad)": "Azad Kashmir",
    "Kyrgyz Republic": "Kyrgyzstan",
    "Lagos": "Lagos Colony",
    "Macedonia (FYROM/North Macedonia)": "North Macedonia",
    "Madagascar (Malagasy)": "Madagascar",
    "Micronesia (Federated states of)": "Micronesia",
    "Myanmar (Burma)": "Myanmar",
    "New Caledonia and Dependencies": "New Caledonia",
    "Palestine": "Mandatory Palestine",
    "Reunion": "Réunion",
    "Rumania": "Romania",
    "Russia (Soviet Union)": "Russia",
    "Sabah (North Borneo)": "North Borneo",
    "Sao Tome and Principe": "São Tomé and Príncipe",
    "Selangore": "Selangor",
    "Southern Sakhalin Island": "Karafuto",
    "Sri Lanka (Ceylon)": "Sri Lanka",
    "St. Kitts and Nevis": "Saint Kitts and Nevis",
    "St. Lucia": "Saint Lucia",
    "St. Vincent and the Grenadines": "Saint Vincent and the Grenadines",
    "Surinam": "Suriname",
    "Swaziland (Eswatini)": "Eswatini",
    "Tanzania (Tanganyika)": "Tanzania",
    "Turkey (Ottoman Empire)": "Turkey",
    "United States of America": "United States",
    "Vietnam, Democratic Republic of": "North Vietnam",
    "Vietnam, Republic of": "South Vietnam",
    "West Irian (Dutch New Guinea)": "Dutch New Guinea",
    "Yemen, People's Republic of": "South Yemen",
    "Yugoslavia/Serbia": "Serbia",  # old-names.json: Yugoslavia, FR Yugoslavia, ...
    "Zimbabwe (Rhodesia)": "Zimbabwe",
}

# Names that depend on the date: (CShapes name, last day) -> name, first match wins.
BY_DATE = {
    "German Federal Republic": [("1949-09-20", "Allied-occupied Germany"), ("1990-10-02", "West Germany"), (LAST, "Germany")],
    "German Democratic Republic": [("1949-10-04", "Soviet occupation zone"), (LAST, "East Germany")],
    "New Guinea (German New Guinea) (Kaiser Wilhelmsland)": [("1914-11-10", "German New Guinea"), (LAST, "New Guinea")],
    "Vietnam (Annam/Cochin China/Tonkin)": [("1954-07-20", "French Indochina"), (LAST, "Vietnam")],
    "Yemen (Arab Republic of Yemen)": [("1990-05-21", "North Yemen"), (LAST, "Yemen")],
}

# Colonies take their ruler's colour, so empires read as one; occupied lands keep their own.
RULED = {"colony", "protectorate", "mandate"}


def fyear(d, after=False):
    """'1945-05-08' -> 1945.35 (the start of that day, or its end with after)."""
    d = datetime.date.fromisoformat(d) + datetime.timedelta(days=after)
    start = datetime.date(d.year, 1, 1)
    days = (datetime.date(d.year + 1, 1, 1) - start).days
    return d.year + (d - start).days / days


def name(p):
    raw = p["country_name"]
    for last, n in BY_DATE.get(raw, ()):
        if p["start"] <= last:
            return n
    return NAMES.get(raw, raw)


def load():
    for url in SOURCES:
        try:
            data = get(url, CACHE)
            break
        except Exception as e:  # moved to the archive once a newer version ships
            print(f"  {url}: {e}")
    else:
        raise SystemExit("cshapes: no source reachable")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        raw = tar.extractfile(MEMBER).read()
    topo = json.loads(lzma.decompress(raw))
    assert "transform" not in topo, "quantized topology: decode deltas first"
    return topo


def quantized_arcs(arcs):
    """Each arc simplified once (neighbours keep meeting exactly), in 1/Q degrees."""
    out = []
    for arc in arcs:
        pts = []
        for x, y in simplify([tuple(p) for p in arc], TOLERANCE):
            p = (round(x * Q), round(y * Q))
            if not pts or p != pts[-1]:
                pts.append(p)
        out.append(pts)
    return out


def ring_points(arcs, ids):
    pts = []
    for i in ids:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        pts.extend(a[1:] if pts else a)
    return pts


def signed_area(pts):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:])) / 2 / Q / Q


def polygons(arcs, g):
    """[[(arc ids, points, area) per ring: outer first, then holes], ...] without
    the specks. Outer rings run anticlockwise and holes clockwise, as GeoJSON wants."""
    out = []
    for poly in [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]:
        rings = []
        for k, ids in enumerate(poly):
            pts = ring_points(arcs, ids)
            a = signed_area(pts) if len(pts) >= 4 and pts[0] == pts[-1] else 0
            if abs(a) < MIN_AREA:
                if k == 0:
                    break  # no outer ring, no polygon
                continue
            if (a < 0) == (k == 0):
                ids, pts = [~i for i in reversed(ids)], pts[::-1]
            rings.append((ids, pts, abs(a)))
        if rings:
            out.append(rings)
    return out


def shown(s, e):
    """Does [s, e) hold a 1 July from FIRST_YEAR on?"""
    return any(s <= y + 0.5 < e for y in range(max(FIRST_YEAR, int(s)), int(min(e, 2020)) + 1))


def main():
    topo = load()
    arcs = quantized_arcs(topo["arcs"])
    geoms = next(iter(topo["objects"].values()))["geometries"]
    # A colour per country code, from its latest name.
    latest = {}
    for g in sorted(geoms, key=lambda g: g["properties"]["start"]):
        latest[str(g["properties"]["cowcode"])] = name(g["properties"])

    runs = {}  # (label, hue, rings) -> {"spans": [[s, e], ...], "polys": ...}
    for g in geoms:
        p = g["properties"]
        s = fyear(p["start"])
        e = 9999 if p["end"] >= LAST else fyear(p["end"], after=True)
        if not shown(s, e):
            continue
        polys = polygons(arcs, g)
        if not polys:
            continue
        ruler = p["owner"] if p["status"] in RULED else str(p["cowcode"])
        ids = [[r[0] for r in poly] for poly in polys]
        key = (name(p), hue(latest.get(ruler, name(p))), json.dumps(ids))
        runs.setdefault(key, {"spans": [], "polys": polys})["spans"].append([s, e])

    used = {}  # old arc index -> new
    shapes = []
    for (label, h, _), run in sorted(runs.items(), key=lambda kv: (min(kv[1]["spans"])[0], kv[0][0])):
        # Spans that touch merge: the same outline under one name, unchanged at this scale.
        spans = sorted(run["spans"])
        merged = [spans[0]]
        for s, e in spans[1:]:
            if s <= merged[-1][1] + 0.003:  # a day
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        polys = run["polys"]
        # The label sits at the centroid of the largest piece.
        _, pts, area = max((poly[0] for poly in polys), key=lambda r: r[2])
        x, y = label_point({"type": "Polygon", "coordinates": [[(px / Q, py / Q) for px, py in pts]]})
        rings = []
        for poly in polys:
            rings.append([[used.setdefault(i, len(used)) if i >= 0 else ~used.setdefault(~i, len(used)) for i in r[0]]
                          for r in poly])
        shapes.append([label, h, [round(v, 3) for span in merged for v in span], round(x, 2), round(y, 2),
                       round(area, 2), rings])

    out_arcs = [None] * len(used)
    for old, new in used.items():
        pts = arcs[old]
        flat = [pts[0][0], pts[0][1]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            flat += [x1 - x0, y1 - y0]
        out_arcs[new] = flat
    n = dump(os.path.join(OUT, "cshapes.json"), {"q": Q, "arcs": out_arcs, "shapes": shapes})
    print(f"cshapes: {len(shapes)} outlines, {sum(len(s[2]) // 2 for s in shapes)} spans, "
          f"{len(out_arcs)} arcs, {n / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
