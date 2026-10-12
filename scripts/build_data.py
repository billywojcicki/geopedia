#!/usr/bin/env python3
"""Turn raw Wikidata CSVs (build/raw) into the static data files the site loads.

The data is a level-of-detail pyramid, so each view downloads only what it can
show. Every happening (event, founding, birth, death) gets a minzoom: the first
map zoom at which it is among the LOD_K most notable things in its 512px tile
and time slice. Records are then grouped by minzoom into tiers:

  a/  minzoom 0-3   whole world, split into time chunks       (always loaded)
  b/  minzoom 4-5   z2 map tiles, split into time chunks      (zoom >= 3)
  c/  minzoom 6-7   z4 map tiles, split into time chunks      (zoom >= 5)
  d/  minzoom 8+    spatial quadtree leaves, every era        (zoom >= 7)
  p/  places that existed (standing), quadtree, every era     (zoom >= 8.5)
  long.json         happenings spanning more than LONG_SPAN years
  index.json        file index and data version
  hist.json         happenings per year, for the timeline
  search.json       title index of the most notable items, with file locations

Record layout (arrays, to keep files small):
  [qid, title, lat, lon, start, end, cat, kind, score, img, desc, date, place, minzoom]
  start/end are astronomical years (0 = 1 BC). img is "a/ab/File.jpg" (Commons
  hash path) or "". date is a human-readable date string. place is the
  birth/death place label for people, else "". Standing records have no minzoom.

Usage: python3 scripts/build_data.py
"""
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import urllib.parse
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from categories import CATEGORIES, EVENT_ROLES, PLACE_ROLES, ROLE_PRIORITY, ROOTS  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(ROOT, "build", "raw")
OUT = os.path.join(ROOT, "data")

csv.field_size_limit(1 << 24)

CAT = {c: i for i, c in enumerate(CATEGORIES)}
# kind codes (js/config.js KIND_VERB must match)
EVENT, BUILT, FOUNDED, ESTABLISHED, BORN, DIED, PREMIERED, DISCOVERED, LAUNCHED = range(9)
HAPPENED = {EVENT, PREMIERED, DISCOVERED, LAUNCHED}  # things that happened, as opposed to places and lives

LONG_SPAN = 25  # years; longer happenings go to long.json
SEARCH_MAX = 40000  # happenings in the search index
SEARCH_FIRST = 10000  # entries in its first part (search.json; the rest is search-2.json)
SEARCH_MAX_PLACES = 6000  # plus this many places known only from the standing layer
SEARCH_MIN_PLACE_SCORE = 10
LOD_K = 8  # events per 512px tile per time slice before the rest wait for a deeper zoom
LOD_MAX_Z = 8  # minzoom 8 means "8 or deeper"
# Foundings, births and deaths get their own, smaller share of each tile and
# only start showing a couple of zoom levels later, so the map leads with what
# happened rather than who was born or what was built.
LOD_K_OTHER = 2
LOD_OTHER_OFFSET = 2
# (name, lowest minzoom, highest minzoom, grid zoom, records per time chunk)
TIERS = [
    ("a", 0, 3, 0, 1500),
    ("b", 4, 5, 2, 2000),
    ("c", 6, 7, 4, 1500),
]
DETAIL_MAX = 2000  # tier d records per quadtree leaf
TILE_MAX = 2500  # standing places per quadtree leaf
MIN_YEAR, MAX_YEAR = -10000, 2026

# Importance = sitelinks * weight. Sitelinks (how many language editions have
# an article) is a decent proxy for global significance.
WEIGHT = {
    "conflict": 1.0,
    "politics": 1.0,
    "disaster": 0.9,
    "culture": 0.9,
    "science": 0.9,
    "sports": 0.5,
    "event": 0.75,  # dated event with no recognised class
    "premiere": 0.8,
    "discovery": 0.9,
    "launch": 0.9,
    # Places and people collect sitelinks far more easily than events (every
    # language edition has an article on every city), and they're the backdrop
    # rather than the story, so they're scaled well down.
    "settlement": 0.25,
    "structure": 0.5,
    "institution": 0.25,
    None: 0.3,  # place of unrecognised class
    "low": 0.1,
    "born": 0.15,  # births mostly show people who became famous decades later
    "died": 0.2,
}
# Events with no usable "instance of" get a category from their title and
# description when the wording is unambiguous ("Battle of...", "... mine disaster").
GUESS_CAT = [
    ("conflict", re.compile(r"\b(battle|siege|action of|raid|massacre|war|rebellion|uprising|revolt|invasion|"
                            r"bombing|attack|skirmish|insurgency|mutiny|ambush|offensive|campaign against|"
                            r"naval engagement|sack of|capture of|liberation of|occupation of|pogrom|"
                            r"shooting|assassination|terrorist|clash|clashes|coup|riot|riots|fighting|incursion)\b", re.I)),
    ("disaster", re.compile(r"\b(disaster|earthquake|flood|fire|explosion|hurricane|typhoon|cyclone|tornado|"
                            r"eruption|tsunami|famine|epidemic|pandemic|outbreak|plague|crash|derailment|"
                            r"shipwreck|sinking|collapse|landslide|avalanche|blizzard|heat wave|drought|"
                            r"accident|stampede|wreck)\b", re.I)),
    # Editions of contests and shows: held to the sports bar (very notable only).
    ("sports", re.compile(r"\b(championships?|grand prix|draft|tournament|cup|bowl|regatta|marathon|derby|"
                          r"olympics|world series|playoffs?|rivalry|awards?|festival|pageant)\b", re.I)),
]


def guess_cat(title):
    """From the title only: descriptions mention wars and operations in passing."""
    for cat, rx in GUESS_CAT:
        if rx.search(title):
            return cat
    return None


def day_of_year(d):
    return (d[1] - 1) * 31 + d[2]


def year_of(t):
    """Year of an xsd:dateTime string, or None."""
    m = re.match(r"^(-?\d+)-", t or "")
    return int(m.group(1)) if m else None


# Continents, oceans, seas, regions: an event listing two of these is spread out.
REGION_CLASSES = {"Q5107", "Q9430", "Q165", "Q82794", "Q2221906"}
LOCAL_KM = 500  # an event's places further apart than this aren't one place
VAGUE_AREA = 2e10  # m² (20,000 km²): a location this big is a region, not a place
HUGE_AREA = 2e11  # m² (200,000 km²): too big even to stand in for an event's place
WORLDWIDE_MIN_SITELINKS = 25  # events spread over several regions must be this notable
WORLD_KM = 5000  # places further apart than this: a worldwide event, not pinned
NATIONWIDE_MIN_SITELINKS = 10  # events known only by country must be this notable
ELECTION_MIN_SITELINKS = 40  # national elections too (they'd crowd every capital)
WORK_MAX_SITELINKS = 60  # premieres and discoveries count at most this many
SPORTS_MIN_SITELINKS = 40
MIN_FOUNDING_HAPPENING = 1.5  # roughly 3+ sitelinks for a building, 5+ for a town
MIN_ESTABLISHED_HAPPENING = 3.0  # institutions, firms etc. need ~7+ sitelinks
# Standing places need this many sitelinks (one fewer with a photo).
MIN_STANDING_SITELINKS = {"low": 6, "institution": 2, None: 2}
IMAGE_BONUS = 1.15
DROPPED_MIN_SITELINKS = 20  # build/dropped.csv lists left-out items this notable

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def qid(uri):
    return int(uri.rsplit("/Q", 1)[1])


def read(name):
    with open(os.path.join(RAW, f"{name}.csv"), newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def parse_point(s):
    m = re.match(r"POINT\(([-\d.eE]+) ([-\d.eE]+)\)", s or "")
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return round(lat, 4), round(lon, 4)


def km(a, b):
    """Great-circle distance between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(h)))


def spread(pts):
    return max((km(a, b) for n, a in enumerate(pts) for b in pts[n + 1:]), default=0)


def centroid(pts):
    """Mean direction of points on the sphere, as (lat, lon)."""
    x = y = z = 0
    for lat, lon in pts:
        la, lo = math.radians(lat), math.radians(lon)
        x += math.cos(la) * math.cos(lo)
        y += math.cos(la) * math.sin(lo)
        z += math.sin(la)
    lat = math.degrees(math.atan2(z, math.hypot(x, y)))
    lon = math.degrees(math.atan2(y, x))
    return round(max(-60, min(70, lat)), 4), round(lon, 4)


JULIAN = "http://www.wikidata.org/entity/Q1985786"


def julian_from_gregorian(y, m, d):
    """The RDF export stores Julian-calendar dates converted to the proleptic
    Gregorian calendar; Wikipedia and Wikidata show them as entered (the
    Battle of Hastings: 14 October 1066, not 20 October)."""
    a = (14 - m) // 12
    yy, mm = y + 4800 - a, m + 12 * a - 3
    jdn = d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    c = jdn + 32082
    dd = (4 * c + 3) // 1461
    e = c - 1461 * dd // 4
    mo = (5 * e + 2) // 153
    return dd - 4800 + mo // 10, mo + 3 - 12 * (mo // 10), e - (153 * mo + 2) // 5 + 1


def parse_time(t, prec, cal=""):
    """-> (year, month, day, precision) or None. Day and year precision years
    are astronomical (0 = 1 BC); coarser BC values are not (the export writes
    the 3rd century BC as -300), which span() and date_label() account for."""
    m = re.match(r"^(-?)(\d+)-(\d\d)-(\d\d)", t or "")
    if not m:
        return None
    y = int(m.group(2)) * (-1 if m.group(1) else 1)
    mo, d = int(m.group(3)), int(m.group(4))
    try:
        p = int(prec)
    except ValueError:
        p = 9
    if p >= 11 and cal == JULIAN and mo and d:
        y, mo, d = julian_from_gregorian(y, mo, d)
    return y, mo, d, p


RANK = {"PreferredRank": 2, "NormalRank": 1}


def rank_of(iri):
    """2 preferred, 1 normal, 0 deprecated (dropped)."""
    return RANK.get((iri or "NormalRank").rsplit("#", 1)[-1], 0)


def unpack_date(packed):
    """"rank|time|precision|calendar" (one-row-per-item queries) -> date or None."""
    parts = (packed or "").split("|")
    if len(parts) != 4 or not rank_of(parts[0]):
        return None
    return parse_time(parts[1], parts[2], parts[3])


def span(d):
    """Year span covered by a date at its precision (astronomical years)."""
    y, _, _, p = d
    if p >= 9:
        return y, y
    if y < 0:  # BC, not astronomical at these precisions: -300 is 300 BC
        n = -y
        if p == 8:  # "700s BC": 709-700 BC
            return 1 - (n + 9), 1 - n
        if p == 7:  # "3rd century BC": 300-201 BC
            c = math.ceil(n / 100)
            return 1 - c * 100, -(c - 1) * 100
        if p == 6:
            k = math.ceil(n / 1000)
            return 1 - k * 1000, -(k - 1) * 1000
        unit = 10 ** (9 - p)
        return 1 - n - unit // 2, 1 - n + unit // 2
    if p == 8:
        s = (y // 10) * 10
        return s, s + 9
    if p == 7:  # century: 1800 -> 18th century (1701-1800)
        c = max(1, math.ceil(y / 100))
        return (c - 1) * 100 + 1, c * 100
    if p == 6:
        k = max(1, math.ceil(y / 1000))
        return (k - 1) * 1000 + 1, k * 1000
    unit = 10 ** (9 - p)
    return y - unit // 2, y + unit // 2


def year_label(y):
    """Astronomical year -> "490 BC", "AD 79", "1066"."""
    if y <= 0:
        return f"{1 - y} BC"
    return f"AD {y}" if y < 1000 else str(y)


def ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def date_label(d):
    y, mo, day, p = d
    if p >= 11 and mo and day:
        return f"{day} {MONTHS[mo - 1]} {year_label(y)}"
    if p == 10 and mo:
        return f"{MONTHS[mo - 1]} {year_label(y)}"
    if p == 9:
        return year_label(y)
    if y < 0:  # BC at a coarse precision: -300 means 300 BC
        n = -y
        if p == 8:
            return f"{n}s BC"
        if p == 7:
            return f"{ordinal(math.ceil(n / 100))} century BC"
        if p == 6:
            return f"{ordinal(math.ceil(n / 1000))} millennium BC"
        return f"c. {n} BC"
    if p == 8:
        return f"{(y // 10) * 10}s"
    if p == 7:
        return f"{ordinal(max(1, math.ceil(y / 100)))} century"
    if p == 6:
        return f"{ordinal(max(1, math.ceil(y / 1000)))} millennium"
    return f"c. {year_label(y)}"


def range_label(a, b):
    """Label for a span from date a to date b: "1939–1945", "490–479 BC",
    "44 BC – AD 14", "6 Apr – 29 May 1453", "6–9 Aug 1945"."""
    if b is None or a == b:
        return date_label(a)
    if a[3] < 9 or b[3] < 9:
        la, lb = date_label(a), date_label(b)
        return la if la == lb else f"{la} – {lb}"
    ya, yb = a[0], b[0]
    if ya == yb:
        if a[3] >= 11 and b[3] >= 11 and a[1] and b[1]:
            if a[1] == b[1]:
                return a[2] == b[2] and date_label(a) or f"{a[2]}–{b[2]} {MONTHS[a[1] - 1]} {year_label(ya)}"
            return f"{a[2]} {MONTHS[a[1] - 1]} – {b[2]} {MONTHS[b[1] - 1]} {year_label(ya)}"
        if a[3] >= 10 and b[3] >= 10 and a[1] and b[1] and a[1] != b[1]:
            return f"{MONTHS[a[1] - 1]}–{MONTHS[b[1] - 1]} {year_label(ya)}"
        return year_label(ya)
    if yb <= 0:
        return f"{1 - ya}–{1 - yb} BC"
    if ya <= 0:
        return f"{1 - ya} BC – AD {yb}"
    return f"{ya}–{yb}"


def best(values):
    """The date to use among several statements: preferred rank first, then
    the most precise. values: [(rank, date)]."""
    if not values:
        return None
    return max(values, key=lambda v: (v[0], v[1][3]))[1]


def top_rank(values):
    """Dates of the best rank present, earliest first."""
    if not values:
        return []
    r = max(v[0] for v in values)
    return sorted({v[1] for v in values if v[0] == r})


def commons_path(url):
    if not url:
        return ""
    name = urllib.parse.unquote(url.rsplit("/", 1)[1]).replace(" ", "_")
    ext = name.rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "gif", "svg", "webp"):
        return ""
    h = hashlib.md5(name.encode("utf-8")).hexdigest()
    return f"{h[0]}/{h[:2]}/{name}"


def clean_desc(s):
    s = (s or "").strip()
    return s if len(s) <= 110 else s[:107].rstrip() + "…"


def main():
    print("resolving classes…")
    parents = defaultdict(set)
    for r in read("subclass"):
        parents[r["a"].rsplit("/", 1)[1]].add(r["b"].rsplit("/", 1)[1])
    role_of_root = {}
    for role in ROLE_PRIORITY:
        for q in ROOTS[role]:
            role_of_root.setdefault(q, role)
    rank = {r: n for n, r in enumerate(ROLE_PRIORITY)}
    class_cache = {}

    def class_role(c):
        """Nearest (distance, priority, role) keep-match above class c, the
        distance to the nearest exclude root (or None), and to the nearest weak
        exclude root (or None)."""
        if c in class_cache:
            return class_cache[c]
        seen, frontier, dist = {c}, [c], 0
        keep, excl, weak = None, None, None
        while frontier and dist <= 12 and (keep is None or excl is None):
            hits = [role_of_root[x] for x in frontier if x in role_of_root]
            if excl is None and "exclude" in hits:
                excl = dist
            if weak is None and "exclude-weak" in hits:
                weak = dist
            hits = [h for h in hits if h not in ("exclude", "exclude-weak")]
            if keep is None and hits:
                role = min(hits, key=rank.get)
                keep = (dist, rank[role], role)
            nxt = []
            for x in frontier:
                for p in parents.get(x, ()):
                    if p not in seen:
                        seen.add(p)
                        nxt.append(p)
            frontier, dist = nxt, dist + 1
        class_cache[c] = (keep, excl, weak)
        return keep, excl, weak

    print("loading items…")
    items = {}
    for r in read("items"):
        if r["title"].startswith("List of"):
            continue
        i = qid(r["item"])
        items[i] = {"title": r["title"], "sl": int(r["sl"] or 0)}

    for r in read("meta"):
        it = items.get(qid(r["item"]))
        if it is not None:
            it["img"] = commons_path(r["image"])
            it["desc"] = clean_desc(r["desc"])

    best_keep, best_excl, weak_excl = {}, {}, set()
    for r in read("classes"):
        i = qid(r["item"])
        if i in items:
            keep, excl, weak = class_role(r["cls"].rsplit("/", 1)[1])
            if keep and (i not in best_keep or keep < best_keep[i]):
                best_keep[i] = keep
            if excl is not None and excl < best_excl.get(i, 99):
                best_excl[i] = excl
            if weak is not None:
                weak_excl.add(i)

    # National elections are known only by country and would crowd the
    # capitals of the recent past: they don't get the country fallback.
    def descends(c, target, depth=5):
        frontier = {c}
        for _ in range(depth):
            if target in frontier:
                return True
            frontier = {p for x in frontier for p in parents.get(x, ())}
        return target in frontier

    election_classes = {c for c in parents if descends(c, "Q40231")} | {"Q40231"}
    # Ships and aircraft are things, not events: the Titanic would show up in
    # 1909, the year it was built (its sinking has its own article).
    VEHICLES = {"Q11446", "Q1229765", "Q11436"}  # ship, watercraft, aircraft
    vehicle_classes = {c for c in parents if any(descends(c, v) for v in VEHICLES)} | VEHICLES
    elections, vehicles = {}, set()
    for r in read("classes"):
        c = r["cls"].rsplit("/", 1)[1]
        if c in election_classes:
            elections[qid(r["item"])] = True
        if c in vehicle_classes:
            vehicles.add(qid(r["item"]))

    def item_role(i):
        """Role of an item. Exclusion only wins when it's clearly the closer
        match (Stanford is both a university and an open-access publisher), or
        when the item is directly an excluded class and nothing kept is (an
        award ceremony is also, one step up, a ceremony)."""
        keep, excl = best_keep.get(i), best_excl.get(i)
        if i in vehicles:
            return "exclude"
        if keep is None and i in weak_excl:
            return "exclude"
        if excl is not None and (keep is None or excl < keep[0] - 1 or (excl == 0 and keep[0] > 0)):
            return "exclude"
        # Culture and sports (festivals, contests, yearly editions) are weak
        # matches: an exclusion as close wins (the 85th Academy Awards is an
        # edition, a ceremony of the arts, and an award ceremony).
        if excl is not None and excl <= keep[0] + {"culture": 0, "sports": 1}.get(keep[2], -99):
            return "exclude"
        return keep[2] if keep else None

    coords = {}
    for r in read("coords"):
        i = qid(r["item"])
        if i in items and i not in coords:
            pt = parse_point(r["c"])
            if pt:
                coords[i] = pt

    # Capitals with their years, so a country maps to its capital of the time.
    capitals = defaultdict(list)  # entity -> [(rank, point, from, to)]
    for r in read("capitals"):
        rk, pt = rank_of(r["rk"]), parse_point(r["c"])
        if rk and pt:
            capitals[r["country"]].append((rk, pt, year_of(r["s"]), year_of(r["e"])))

    def capital_at(entity, year):
        cs = capitals.get(entity)
        if not cs:
            return None
        valid = [c for c in cs if (c[2] is None or c[2] <= year) and (c[3] is None or year <= c[3])]
        if valid:
            # The one in office then (a dated term beats an open-ended one).
            return max(valid, key=lambda c: (c[2] is not None and c[3] is not None, c[0], c[2] or -99999))[1]
        return max(cs, key=lambda c: (c[0], c[3] is None))[1]

    # Locations from P276. Vague ones (countries, states, continents, oceans,
    # seas, regions, or anything over VAGUE_AREA) aren't pinned on directly.
    locs = defaultdict(dict)  # item -> location -> [point, vague, huge, has capital, label]
    for r in read("loccoords"):
        i = qid(r["item"])
        pt = parse_point(r["c"])
        if i not in items or not pt:
            continue
        big = r["big"].rsplit("/", 1)[-1]
        try:
            area = float(r["area"] or 0)
        except ValueError:
            area = 0
        cur = locs[i].setdefault(r["loc"], [pt, False, False, False, r["label"] or ""])
        cur[1] = cur[1] or bool(r["cap"] or big) or area > VAGUE_AREA
        cur[2] = cur[2] or big in REGION_CLASSES or area > HUGE_AREA
        cur[3] = cur[3] or bool(r["cap"])
    p131 = {}  # events placed only by city or district
    for r in read("p131coords"):
        i = qid(r["item"])
        try:
            area = float(r.get("area") or 0)
        except ValueError:
            area = 0
        # A district or city, not a state or province (by size, or by having a
        # capital when the size is unknown).
        if i in items and i not in p131 and not (area > VAGUE_AREA or not area and r["cap"]):
            pt = parse_point(r["c"])
            if pt:
                p131[i] = pt
    countries = defaultdict(dict)  # item -> country -> (centroid, label)
    for r in read("countrycoords"):
        i = qid(r["item"])
        if i in items and r["country"] not in countries[i]:
            countries[i][r["country"]] = (parse_point(r["cc"]), r["label"] or "")

    def locate(i, year):
        """-> (point, place label, how) for an event. how is None for a real
        place, "country" for a country's capital (notable events only), or
        (points, labels) for an event spread over places far apart (notable
        ones are pinned nowhere; point is then a specific place to fall back on)."""
        if i in coords:
            return coords[i], "", None
        ls = locs.get(i)
        if ls:
            vals = list(ls.items())
            specific = [v[0] for _, v in vals if not v[1]]
            regions = sum(v[2] for _, v in vals)
            if specific and spread(specific) <= LOCAL_KM and regions < 2:
                return specific[0], "", None
            # Countries count by their capital of the time, other places by their point.
            pts = [(capital_at(loc, year) if v[3] else None) or v[0] for loc, v in vals]
            labels = [v[4] for _, v in vals]
            if len(vals) > 1 and spread(pts) > LOCAL_KM:
                return (specific[0] if specific else None), "", (pts, labels)
            if specific:
                return specific[0], "", None
            if len(vals) == 1 and vals[0][1][3] and not vals[0][1][2]:
                # One country: its capital, labelled with the country.
                loc, v = vals[0]
                cap = capital_at(loc, year)
                if cap:
                    return cap, v[4], "country"
            # Only regions, close together (Sinai, Golan, West Bank): the most
            # central one, unless they are as big as a continent or a sea.
            near = [q for (loc, v), q in zip(vals, pts) if not v[2]]
            if near:
                mid = centroid(near)
                return min(near, key=lambda q: km(q, mid)), "", None
            return None, "", (pts, labels)
        if i in p131:
            return p131[i], "", None
        cs = countries.get(i)
        if cs:
            pts = [capital_at(c, year) or cc for c, (cc, _) in cs.items()]
            labels = [label for _, label in cs.values()]
            if any(pts) and (len(cs) == 1 or spread([q for q in pts if q]) <= LOCAL_KM):
                return next(q for q in pts if q), ", ".join(l for l in labels[:3] if l), "country"
            if len(cs) > 1 and all(pts):
                return None, "", (pts, labels)
        return None, "", None

    # Events with several far-apart places.
    def wide_label(pts, labels):
        if len(labels) <= 3 and all(labels):
            return ", ".join(labels)
        return "Worldwide" if spread(pts) > WORLD_KM else ""

    dates = defaultdict(lambda: defaultdict(list))  # item -> property -> [(rank, date)]
    for prop in ["P585", "P580", "P582", "P571", "P576", "P1619", "P1249"]:
        for r in read(f"date_{prop}"):
            i = qid(r["item"])
            rk = rank_of(r["rk"])
            if i in items and rk:
                d = parse_time(r["t"], r["prec"], r["cal"])
                if d:
                    dates[i][prop].append((rk, d))

    # Notable items left out, and why: build/dropped.csv answers "why isn't X on the map?".
    dropped = []

    def drop(i, it, role, reason):
        if it["sl"] >= DROPPED_MIN_SITELINKS:
            dropped.append((it["sl"], f"Q{i}", it["title"], role or "", reason))

    print("classifying…")
    happenings = []
    worldwide_recs = []  # no single place: listed and searchable, never pinned
    standing = []
    stats = Counter()

    for i, it in items.items():
        role = item_role(i)
        if role == "exclude":
            stats["excluded"] += 1
            drop(i, it, role, "excluded")
            continue
        ds = dates.get(i, {})
        cat = role if role in EVENT_ROLES else None
        p580, p582 = best(ds.get("P580")), best(ds.get("P582"))
        pits = top_rank(ds.get("P585"))
        pit_d = best(ds.get("P585"))
        # A decade- or century-level date says less than a precise one: when a
        # precise date says the same thing, the vague one doesn't stretch the span.
        precise = lambda d: d is not None and d[3] >= 9
        if precise(pit_d) or precise(p580) and precise(p582):
            p580 = p580 if precise(p580) else None
            p582 = p582 if precise(p582) else None
            pit_d = pit_d if precise(pit_d) else None
            pits = [d for d in pits if d[3] >= 9]
        elif pit_d and (precise(p580) or precise(p582)):
            pit_d, pits = None, []
        start_d = p580 or pit_d
        end_d = p582 or pit_d
        # Founding, opening, or failing those the earliest written record (Moscow, 1147).
        found_d = best(ds.get("P571")) or best(ds.get("P1619")) or best(ds.get("P1249"))
        is_place = role in PLACE_ROLES or (cat is None and found_d is not None)
        sl = it["sl"]
        img = it.get("img", "")
        bonus = IMAGE_BONUS if img else 1.0

        if not is_place:
            if cat is None and role is None:
                cat = guess_cat(it["title"])
                if cat:
                    stats[f"guessed:{cat}"] += 1
            if start_d is None:
                stats["no_date"] += 1
                drop(i, it, role, "no date")
                continue
            # Several dates a few days apart (Hiroshima, then Nagasaki): a range.
            # Further apart they are more likely rival datings: keep the best one.
            if not p580 and not p582 and len(pits) > 1 and all(d[3] >= 11 for d in pits) \
                    and pits[-1][0] == pits[0][0] and day_of_year(pits[-1]) - day_of_year(pits[0]) <= 10:
                start_d, end_d = pits[0], pits[-1]
            pt, place, how = locate(i, span(start_d)[0])
            notable = cat != "sports"  # unclassified events show as politics
            worldwide = False
            if how == "country":
                # Known only by country: the capital, for events notable enough
                # (elections would crowd every capital).
                if notable and sl >= NATIONWIDE_MIN_SITELINKS and (not elections.get(i) or sl >= ELECTION_MIN_SITELINKS):
                    stats["event:nationwide"] += 1
                else:
                    pt, place = None, ""
            elif how:
                if notable and sl >= WORLDWIDE_MIN_SITELINKS:
                    # Spread over places far apart: no pin, listed while in view.
                    place, pt, worldwide = wide_label(*how), centroid(how[0]), True
                    stats["event:wide"] += 1
                else:
                    place = ""  # a minor one keeps a specific place, if it has one
            if not pt:
                stats["event_nocoord"] += 1
                drop(i, it, role, "event: no usable place")
                continue
            if cat == "sports" and sl < SPORTS_MIN_SITELINKS:
                stats["sports_dropped"] += 1
                drop(i, it, role, "sports/edition under the bar")
                continue
            spans = [span(d) for d in (start_d, end_d) if d]
            start, end = min(x[0] for x in spans), max(x[1] for x in spans)
            if end - start > 2000 or start > MAX_YEAR:
                stats["bad_span"] += 1
                drop(i, it, role, "bad span")
                continue
            # A stated span reads as one ("1789–1799", "6 Apr – 29 May 1453");
            # otherwise the most precise single date.
            if end_d and start_d != end_d and (p580 and p582 or start_d[3] >= 11):
                label = range_label(*sorted((start_d, end_d)))
            else:
                label = date_label(pit_d or start_d)
            disp = "culture" if cat in ("culture", "sports") else (cat or "politics")
            score = sl * WEIGHT[cat or "event"] * bonus
            rec = [i, it["title"], pt[0], pt[1], start, end, CAT[disp], EVENT,
                   round(score, 1), img, it.get("desc", ""), label, place]
            if worldwide:
                rec.append([[round(q[0], 2), round(q[1], 2)] for q in dict.fromkeys(how[0])])
                worldwide_recs.append(rec)
            else:
                happenings.append(rec)
            stats[f"event:{cat}"] += 1
            continue

        found_d = found_d or start_d or pit_d
        if found_d is None:
            stats["no_date"] += 1
            drop(i, it, role, "no date")
            continue
        pt = coords.get(i)
        if not pt:
            stats["place_nocoord"] += 1
            drop(i, it, role, "place: no coordinates")
            continue
        s0, s1 = span(found_d)
        if s0 > MAX_YEAR:
            continue
        end_d = best(ds.get("P576")) or best(ds.get("P582"))
        end = span(end_d)[1] if end_d else 9999
        kind = BUILT if role == "structure" else FOUNDED if role == "settlement" else ESTABLISHED
        score = round(sl * WEIGHT[role] * bonus, 1)
        rec = [i, it["title"], pt[0], pt[1], s0, s1, CAT["built"], kind, score, img,
               it.get("desc", ""), date_label(found_d), ""]
        # Only notable foundings become happenings; minor ones still
        # show up (and are marked as new) through the standing layer when zoomed in.
        # Vague foundings ("18th century") would sit in every window of the
        # century, so they only appear through the standing layer.
        vague = s1 - s0 > LONG_SPAN
        if not vague and score >= (MIN_ESTABLISHED_HAPPENING if kind == ESTABLISHED else MIN_FOUNDING_HAPPENING):
            happenings.append(rec)
        min_sl = MIN_STANDING_SITELINKS.get(role, 1)
        if end >= s0 and (sl >= min_sl or (img and sl >= min_sl - 1)):
            standing.append(rec[:5] + [end] + rec[6:])
        stats[f"place:{role}"] += 1

    print("people, premieres, discoveries, launches…")
    found = set()
    for kind_name, kind, cat, weight in (
        ("births", BORN, "people", "born"),
        ("deaths", DIED, "people", "died"),
        ("premieres", PREMIERED, "culture", "premiere"),
        ("discoveries", DISCOVERED, "science", "discovery"),
        ("launches", LAUNCHED, "science", "launch"),
    ):
        for r in read(kind_name):
            pt = parse_point(r["c"])
            d = unpack_date(r["date"])
            if not pt or not d or r["title"].startswith("List of"):
                continue
            if r.get("cap"):
                continue  # found/premiered somewhere as vague as a country
            if kind in (PREMIERED, DISCOVERED):
                # Sitelinks here measure the thing (oxygen, a symphony), not
                # the moment it was found or first heard: cap them.
                r["sl"] = str(min(int(r["sl"] or 0), WORK_MAX_SITELINKS))
            s0, s1 = span(d)
            if s1 - s0 > 100 or s0 > MAX_YEAR:
                continue
            sl = int(r["sl"] or 0)
            img = commons_path(r["image"])
            score = round(sl * WEIGHT[weight] * (IMAGE_BONUS if img else 1), 1)
            i = qid(r["item"])
            if kind in (PREMIERED, DISCOVERED, LAUNCHED):
                found.add(i)
            happenings.append([i, r["title"], pt[0], pt[1], s0, s1, CAT[cat], kind,
                               score, img, clean_desc(r["desc"]), date_label(d), r["placeLabel"] or ""])
            stats[kind_name] += 1
    # A found object or premiered work is shown where it happened, not as a
    # "place" at the museum or theatre that holds it today.
    happenings = [h for h in happenings if not (h[0] in found and h[7] not in HAPPENED)]
    standing = [p for p in standing if p[0] not in found]

    with open(os.path.join(ROOT, "build", "dropped.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sitelinks", "item", "title", "role", "reason"])
        w.writerows(sorted(dropped, reverse=True))

    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"  happenings: {len(happenings)}  standing: {len(standing)}")

    write(happenings, standing, worldwide_recs)


_digest = hashlib.sha1()


def dump(path, obj):
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    _digest.update(path.encode() + data)
    return len(data)


def time_slice(year):
    """Slices for density limiting, finer where the record is denser."""
    if year >= 1500:
        return year
    if year >= 1000:
        return 100_000 + year // 5
    if year >= 0:
        return 200_000 + year // 10
    return 300_000 + year // 50


def tile_xy(lat, lng, z):
    """Web Mercator tile containing a point."""
    n = 1 << z
    x = int((lng + 180) / 360 * n)
    r = math.radians(max(-85.05, min(85.05, lat)))
    y = int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def assign_minzoom(recs, slice_key, k=LOD_K, offset=0):
    """Append minzoom to each record: the first zoom where it ranks in the top
    k of its tile within its time slice (plus `offset`). Ranks only improve as
    tiles get smaller, so the first zoom that admits a record admits it for good."""
    groups = defaultdict(list)
    for r in recs:
        groups[slice_key(r)].append(r)
    for group in groups.values():
        group.sort(key=lambda r: -r[8])
        mz = [LOD_MAX_Z] * len(group)
        for z in range(LOD_MAX_Z):
            seen = Counter()
            for i, r in enumerate(group):
                t = tile_xy(r[2], r[3], z)
                if seen[t] < k:
                    seen[t] += 1
                    if mz[i] > z:
                        mz[i] = z
        for r, z in zip(group, mz):
            r.append(min(LOD_MAX_Z, z + offset))


def chunk_by_start(recs, size):
    """Split records (sorted by start) into chunks of about `size`, never
    splitting one start year across chunks."""
    chunks, cur = [], []
    for r in recs:
        if len(cur) >= size and r[4] != cur[-1][4]:
            chunks.append(cur)
            cur = []
        cur.append(r)
    if cur:
        chunks.append(cur)
    return chunks


def quadtree(recs, max_n, write_leaf):
    """Split records into lng/lat quadtree leaves of at most max_n."""
    def split(recs, x0, y0, x1, y1, key):
        if len(recs) <= max_n or len(key) >= 14:
            if recs:
                write_leaf(key or "root", [x0, y0, x1, y1], recs)
            return
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        quads = [[], [], [], []]
        for r in recs:
            quads[(1 if r[3] >= mx else 0) + (2 if r[2] < my else 0)].append(r)
        split(quads[0], x0, my, mx, y1, key + "0")
        split(quads[1], mx, my, x1, y1, key + "1")
        split(quads[2], x0, y0, mx, my, key + "2")
        split(quads[3], mx, y0, x1, my, key + "3")
    split(recs, -180, -90, 180, 90, "")


def write(happenings, standing, worldwide):
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    total = 0
    loc = {}  # id(record) -> file it lives in, for the search index

    short = [r for r in happenings if r[5] - r[4] <= LONG_SPAN]
    long_ = [r for r in happenings if r[5] - r[4] > LONG_SPAN]
    happened = lambda r: r[7] in HAPPENED
    assign_minzoom([r for r in short if happened(r)], lambda r: time_slice(r[4]))
    assign_minzoom([r for r in short if not happened(r)], lambda r: time_slice(r[4]), LOD_K_OTHER, LOD_OTHER_OFFSET)
    assign_minzoom([r for r in long_ if happened(r)], lambda r: 0)
    assign_minzoom([r for r in long_ if not happened(r)], lambda r: 0, LOD_K_OTHER, LOD_OTHER_OFFSET)

    # Long happenings: the few that show zoomed out come with the first view;
    # the rest is an ordinary file, loaded from zoom 4.
    long_.sort(key=lambda r: -r[8])
    for name, recs in (("long", [r for r in long_ if r[13] <= TIERS[0][2]]),
                       ("long-2", [r for r in long_ if r[13] > TIERS[0][2]])):
        total += dump(os.path.join(OUT, f"{name}.json"), recs)
        for r in recs:
            loc[id(r)] = name

    tiers = {}
    for name, zmin, zmax, gz, size in TIERS:
        by_tile = defaultdict(list)
        for r in short:
            if zmin <= r[13] <= zmax:
                by_tile[tile_xy(r[2], r[3], gz)].append(r)
        tiles = {}
        for (x, y), recs in sorted(by_tile.items()):
            recs.sort(key=lambda r: (r[4], -r[8]))
            entries = []
            for i, chunk in enumerate(chunk_by_start(recs, size)):
                chunk.sort(key=lambda r: -r[8])
                path = f"{name}/{x}-{y}-{i}"
                total += dump(os.path.join(OUT, path + ".json"), chunk)
                # [first start, last start, count, last end]: lets the app skip
                # chunks that end before its window.
                entries.append([chunk_min(chunk), max(r[4] for r in chunk), len(chunk), max(r[5] for r in chunk)])
                for r in chunk:
                    loc[id(r)] = path
            tiles[f"{x}-{y}"] = entries
        tiers[name] = {"zoom": gz, "minz": zmin, "tiles": tiles}
        print(f"  tier {name}: {sum(len(v) for v in tiles.values())} files, "
              f"{sum(e[2] for v in tiles.values() for e in v)} records")

    detail = []

    def write_detail(key, bbox, recs):
        nonlocal total
        recs.sort(key=lambda r: -r[8])
        total += dump(os.path.join(OUT, "d", f"{key}.json"), recs)
        detail.append([key, *bbox, len(recs)])
        for r in recs:
            loc[id(r)] = f"d/{key}"  # search opens results zoomed in, where these load

    # Zoomed into a city the app reads only the world tier and these leaves, so
    # they also carry what the coarser b/c tiers hold (a b or c file covers far
    # more than a city: most of it would be wasted bytes).
    deep = [r for r in short if r[13] > TIERS[0][2]]
    quadtree(deep, DETAIL_MAX, write_detail)
    print(f"  tier d: {len(detail)} files, {len(deep)} records")

    places = []

    def write_places(key, bbox, recs):
        nonlocal total
        recs.sort(key=lambda r: -r[8])
        total += dump(os.path.join(OUT, "p", f"{key}.json"), recs)
        places.append([key, *bbox, len(recs)])
        for r in recs:
            loc[id(r)] = f"p/{key}"

    quadtree(standing, TILE_MAX, write_places)
    print(f"  standing: {len(places)} files, {len(standing)} records")

    # Events with no one place: a small file the app keeps whole. Layout as
    # other happenings (minzoom 0), plus the event's places at the end.
    worldwide.sort(key=lambda r: -r[8])
    for r in worldwide:
        r.insert(13, 0)
        loc[id(r)] = "world"
    total += dump(os.path.join(OUT, "world.json"), worldwide)
    print(f"  worldwide: {len(worldwide)} records")

    # Year histogram for the timeline (short + long happenings by start year).
    hist = Counter()
    for r in happenings + worldwide:
        hist[max(MIN_YEAR, min(MAX_YEAR, r[4]))] += 1
    total += dump(os.path.join(OUT, "hist.json"), {
        "min": MIN_YEAR, "max": MAX_YEAR, "counts": [hist.get(y, 0) for y in range(MIN_YEAR, MAX_YEAR + 1)]})

    # Search index: the most notable items, with the file holding each. Places
    # whose founding is only known roughly ("4th century BC") are in no
    # happening file, so the notable ones come from the standing layer.
    # Rows: [id, title, start, end, cat, kind, file, label]; the label is the
    # founding date of a place ("3rd century BC") or a worldwide event's places.
    def row(r, end):
        label = r[11] if r[7] in (BUILT, FOUNDED, ESTABLISHED) else r[12] if loc[id(r)] == "world" else ""
        return [r[0], r[1], r[4], end, r[6], r[7], loc[id(r)]] + ([label] if label else [])

    seen = set()
    search = []
    cutoff = 0
    for r in sorted(happenings + worldwide, key=lambda r: -r[8]):
        if r[0] in seen:
            continue
        seen.add(r[0])
        search.append(row(r, r[5]))
        if len(search) >= SEARCH_MAX:
            cutoff = r[8]
            break
    extra = [r for r in standing if r[0] not in seen and r[8] >= max(cutoff, SEARCH_MIN_PLACE_SCORE)]
    for r in sorted(extra, key=lambda r: -r[8])[:SEARCH_MAX_PLACES]:
        search.append(row(r, r[4]))
    # Most notable first: the app ranks ties by position.
    score = {r[0]: r[8] for r in happenings + worldwide + standing}
    search.sort(key=lambda e: -score[e[0]])
    # Two parts: the most notable answer most searches and arrive first.
    total += dump(os.path.join(OUT, "search.json"), search[:SEARCH_FIRST])
    total += dump(os.path.join(OUT, "search-2.json"), search[SEARCH_FIRST:])

    index = {
        "version": _digest.hexdigest()[:10],
        "categories": CATEGORIES,
        "longSpan": LONG_SPAN,
        "tiers": tiers,
        "detailMinz": TIERS[-1][2] + 1,
        "leavesHoldAll": True,  # detail leaves also carry the b/c tiers' records
        "longDetail": True,  # long happenings past zoom 3 are in long-2.json
        "searchParts": 2,  # search.json, then search-2.json
        "detail": detail,
        "standing": places,
        "counts": {"happenings": len(happenings), "standing": len(standing)},
    }
    total += dump(os.path.join(OUT, "index.json"), index)
    print(f"version {index['version']}  total: {total / 1e6:.1f} MB")


def chunk_min(chunk):
    return min(r[4] for r in chunk)


if __name__ == "__main__":
    main()
