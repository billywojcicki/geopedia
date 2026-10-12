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
EVENT, BUILT, FOUNDED, ESTABLISHED, BORN, DIED, PREMIERED, DISCOVERED = range(8)
HAPPENED = {EVENT, PREMIERED, DISCOVERED}  # things that happened, as opposed to places and lives

LONG_SPAN = 25  # years; longer happenings go to long.json
SEARCH_MAX = 40000  # happenings in the search index
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
                            r"bombing|attack|skirmish|insurgency|mutiny|ambush|offensive|operation|campaign against|"
                            r"naval engagement|sack of|capture of|fall of|liberation of|occupation of|pogrom|"
                            r"shooting|assassination|terrorist|clash|clashes|coup|riot|riots|fighting|incursion)\b", re.I)),
    ("disaster", re.compile(r"\b(disaster|earthquake|flood|fire|explosion|hurricane|typhoon|cyclone|tornado|"
                            r"eruption|tsunami|famine|epidemic|pandemic|outbreak|plague|crash|derailment|"
                            r"shipwreck|sinking|collapse|landslide|avalanche|blizzard|heat wave|drought|"
                            r"accident|stampede|wreck)\b", re.I)),
    # Editions of contests and shows: held to the sports bar (very notable only).
    ("sports", re.compile(r"\b(championships?|grand prix|draft|tournament|cup|bowl|regatta|marathon|derby|"
                          r"olympics|world series|playoffs?|rivalry|awards?|festival|pageant)\b", re.I)),
]


def guess_cat(title, desc):
    text = f"{title} {desc}"
    for cat, rx in GUESS_CAT:
        if rx.search(text):
            return cat
    return None


# Continents, oceans, seas, regions: an event listing two of these is spread out.
REGION_CLASSES = {"Q5107", "Q9430", "Q165", "Q82794", "Q2221906"}
LOCAL_KM = 500  # an event's places further apart than this aren't one place
WORLDWIDE_MIN_SITELINKS = 40  # events spread over several regions must be this notable
WORLD_KM = 5000  # places further apart than this: a worldwide event, not pinned
NATIONWIDE_MIN_SITELINKS = 10  # events known only by country must be this notable
WORK_MAX_SITELINKS = 60  # premieres and discoveries count at most this many
SPORTS_MIN_SITELINKS = 40
MIN_FOUNDING_HAPPENING = 1.5  # roughly 3+ sitelinks for a building, 5+ for a town
MIN_ESTABLISHED_HAPPENING = 3.0  # institutions, firms etc. need ~7+ sitelinks
# Standing places need this many sitelinks (one fewer with a photo).
MIN_STANDING_SITELINKS = {"low": 6, "institution": 2, None: 2}
IMAGE_BONUS = 1.15

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


def parse_time(t, prec):
    """-> (year, month, day, precision) or None. Years are astronomical."""
    m = re.match(r"^(-?)(\d+)-(\d\d)-(\d\d)", t or "")
    if not m:
        return None
    y = int(m.group(2)) * (-1 if m.group(1) else 1)
    try:
        p = int(prec)
    except ValueError:
        p = 9
    return y, int(m.group(3)), int(m.group(4)), p


def span(d):
    """Year span covered by a date at its precision."""
    y, _, _, p = d
    if p >= 9:
        return y, y
    if p == 8:
        s = (y // 10) * 10
        return s, s + 9
    if p == 7:  # century: 1800 -> 18th century (1701-1800)
        c = math.ceil(y / 100) if y > 0 else math.floor((y - 1) / 100)
        return (c - 1) * 100 + 1, c * 100
    if p == 6:
        k = math.ceil(y / 1000) if y > 0 else math.floor((y - 1) / 1000)
        return (k - 1) * 1000 + 1, k * 1000
    unit = 10 ** (9 - p)
    return y - unit // 2, y + unit // 2


def year_label(y):
    return f"{1 - y} BC" if y <= 0 else str(y)


def ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def date_label(d, end=None):
    y, mo, day, p = d
    if p >= 11 and mo and day:
        s = f"{day} {MONTHS[mo - 1]} {year_label(y)}"
    elif p == 10 and mo:
        s = f"{MONTHS[mo - 1]} {year_label(y)}"
    elif p == 9:
        s = year_label(y)
    elif p == 8:
        s = f"{year_label((y // 10) * 10)}s" if y > 0 else f"c. {year_label(y)}"
    elif p == 7:
        c = math.ceil(y / 100) if y > 0 else math.floor((y - 1) / 100)
        s = f"{ordinal(c)} century" if c > 0 else f"{ordinal(-c)} century BC"
    elif p == 6:
        k = math.ceil(y / 1000) if y > 0 else math.floor((y - 1) / 1000)
        s = f"{ordinal(k)} millennium" if k > 0 else f"{ordinal(-k)} millennium BC"
    else:
        s = f"c. {year_label(y)}"
    if end and end[0] != y:
        e = year_label(end[0])
        if p >= 9 and end[3] >= 9:
            s = f"{year_label(y)}–{e}"
    return s


def best(values):
    """Pick the most precise date among several statements."""
    return max(values, key=lambda d: d[3]) if values else None


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
        """Nearest (distance, priority, role) keep-match above class c, and the
        distance to the nearest exclude root (or None)."""
        if c in class_cache:
            return class_cache[c]
        seen, frontier, dist = {c}, [c], 0
        keep, excl = None, None
        while frontier and dist <= 12 and (keep is None or excl is None):
            hits = [role_of_root[x] for x in frontier if x in role_of_root]
            if excl is None and "exclude" in hits:
                excl = dist
            hits = [h for h in hits if h != "exclude"]
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
        class_cache[c] = (keep, excl)
        return keep, excl

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

    best_keep, best_excl = {}, {}
    for r in read("classes"):
        i = qid(r["item"])
        if i in items:
            keep, excl = class_role(r["cls"].rsplit("/", 1)[1])
            if keep and (i not in best_keep or keep < best_keep[i]):
                best_keep[i] = keep
            if excl is not None and excl < best_excl.get(i, 99):
                best_excl[i] = excl

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
    elections = {}
    for r in read("classes"):
        if r["cls"].rsplit("/", 1)[1] in election_classes:
            elections[qid(r["item"])] = True

    def item_role(i):
        """Role of an item. Exclusion only wins when it's clearly the closer
        match (Stanford is both a university and an open-access publisher), or
        when the item is directly an excluded class and nothing kept is (an
        award ceremony is also, one step up, a ceremony)."""
        keep, excl = best_keep.get(i), best_excl.get(i)
        if excl is not None and (keep is None or excl < keep[0] - 1 or (excl == 0 and keep[0] > 0)):
            return "exclude"
        return keep[2] if keep else None

    coords = {}
    for r in read("coords"):
        i = qid(r["item"])
        if i in items and i not in coords:
            pt = parse_point(r["c"])
            if pt:
                coords[i] = pt
    # Events located through P276. A specific place (city, site) wins over
    # vague ones (country, continent, ocean: centroids mean nothing). Events
    # whose places are far apart are regional (pinned on their most central
    # place) or, past WORLD_KM, worldwide (the world wars, the Cold War: listed
    # and searchable, never pinned).
    locs = defaultdict(dict)  # item -> location -> (point, vague, continent/ocean/region, capital)
    for r in read("loccoords"):
        i = qid(r["item"])
        pt = parse_point(r["c"])
        if i in items and pt:
            _, vague, region, cap = locs[i].get(r["loc"], (0, False, False, None))
            big = r["big"].rsplit("/", 1)[-1]
            locs[i][r["loc"]] = (pt, vague or bool(r["cap"] or big), region or big in REGION_CLASSES,
                                 cap or parse_point(r["capc"]))
    loccoords = {}
    spread_out = {}  # item -> (points, place label, fallback point, places to pin a regional event on)
    for i, ls in locs.items():
        specific = [pt for pt, vague, _, _ in ls.values() if not vague]
        everywhere = [pt for pt, _, _, _ in ls.values()]
        regions = sum(region for _, _, region, _ in ls.values())
        if specific and spread(specific) <= LOCAL_KM and regions < 2:
            loccoords[i] = specific[0]
        elif len(everywhere) > 1 and spread(everywhere) > LOCAL_KM:
            loccoords[i] = None
            # Countries count by their capital; continents and oceans not at all.
            pins = specific + [cap for _, vague, _, cap in ls.values() if vague and cap]
            spread_out[i] = (everywhere, "", specific[0] if specific else None, pins)
        else:
            loccoords[i] = specific[0] if specific else None
    del locs
    # Events placed only by city/district.
    for r in read("p131coords"):
        i = qid(r["item"])
        if i not in items or i in loccoords:
            continue
        pt = None if r["cap"] else parse_point(r["c"])
        if pt:
            loccoords[i] = pt
    # Events placed only by country: pinned at the capital, labelled with the
    # country. Events spanning several countries (world wars...) are skipped.
    countries = defaultdict(dict)  # item -> country -> (point, label)
    for r in read("countrycoords"):
        i = qid(r["item"])
        if i not in items or r["country"] in countries[i]:
            continue
        pt = parse_point(r["capc"]) or parse_point(r["cc"])
        countries[i][r["country"]] = (pt, r["label"] or "")
    nationwide = {}
    for i, cs in countries.items():
        pts = [pt for pt, _ in cs.values() if pt]
        if len(cs) == 1 and pts:
            nationwide[i] = (pts[0], next(iter(cs.values()))[1])
        elif len(pts) > 1 and i not in spread_out and spread(pts) > LOCAL_KM:
            labels = [label for _, label in cs.values()]
            spread_out[i] = (pts, ", ".join(labels) if len(labels) <= 3 and all(labels) else "", None, pts)
    del countries

    dates = defaultdict(lambda: defaultdict(list))
    for prop in ["P585", "P580", "P582", "P571", "P576", "P1619"]:
        for r in read(f"date_{prop}"):
            i = qid(r["item"])
            if i in items:
                d = parse_time(r["t"], r["prec"])
                if d:
                    dates[i][prop].append(d)

    print("classifying…")
    happenings = []
    worldwide_recs = []  # no single place: searchable, listed, never pinned
    standing = []
    stats = Counter()

    for i, it in items.items():
        role = item_role(i)
        if role == "exclude":
            stats["excluded"] += 1
            continue
        ds = dates.get(i, {})
        cat = role if role in EVENT_ROLES else None
        pit_d = best(ds.get("P585"))
        start_d = best(ds.get("P580")) or pit_d
        end_d = best(ds.get("P582")) or pit_d
        found_d = best(ds.get("P571")) or best(ds.get("P1619"))
        is_place = role in PLACE_ROLES or (cat is None and found_d is not None)
        sl = it["sl"]
        img = it.get("img", "")
        bonus = IMAGE_BONUS if img else 1.0

        if not is_place:
            if cat is None and role is None:
                cat = guess_cat(it["title"], it.get("desc", ""))
                if cat:
                    stats[f"guessed:{cat}"] += 1
            if start_d is None:
                stats["no_date"] += 1
                continue
            pt = coords.get(i) or loccoords.get(i)
            place = ""
            worldwide = False
            if not pt and i in spread_out:
                pts, place, pt, pins = spread_out[i]  # pt: a specific place to fall back on
                if not (cat and cat != "sports" and sl >= WORLDWIDE_MIN_SITELINKS):
                    place = ""
                elif spread(pts) > WORLD_KM:
                    pt = centroid(pts)
                    place = place or "Worldwide"
                    worldwide = True
                    stats["event:worldwide"] += 1
                elif pins:
                    # A regional event: pinned on whichever of its places is most central.
                    mid = centroid(pts)
                    pt = min(pins, key=lambda q: km(q, mid))
                    stats["event:regional"] += 1
                else:
                    pt = None
            elif not pt and i in nationwide and cat and cat != "sports" and sl >= NATIONWIDE_MIN_SITELINKS \
                    and not elections.get(i):
                (pt, place) = nationwide[i]
                stats["event:nationwide"] += 1
            if not pt:
                stats["event_nocoord"] += 1
                continue
            if cat == "sports" and sl < SPORTS_MIN_SITELINKS:
                stats["sports_dropped"] += 1
                continue
            spans = [span(d) for d in (start_d, end_d, pit_d) if d]
            start, end = min(x[0] for x in spans), max(x[1] for x in spans)
            if end - start > 2000 or start > MAX_YEAR:
                stats["bad_span"] += 1
                continue
            # Multi-year events read as their span ("1789-1799"); otherwise the
            # most precise single date.
            ranged = start_d and end_d and best(ds.get("P580")) and best(ds.get("P582")) and end_d[0] != start_d[0]
            if pit_d and pit_d[3] >= 10 and not ranged:
                label = date_label(pit_d)
            else:
                first = min((d for d in (start_d, end_d) if d), key=lambda d: d[0])
                last = max((d for d in (start_d, end_d) if d), key=lambda d: d[0])
                label = date_label(first, last)
            disp = "culture" if cat in ("culture", "sports") else (cat or "politics")
            score = sl * WEIGHT[cat or "event"] * bonus
            rec = [i, it["title"], pt[0], pt[1], start, end, CAT[disp], EVENT,
                   round(score, 1), img, it.get("desc", ""), label, place]
            (worldwide_recs if worldwide else happenings).append(rec)
            stats[f"event:{cat}"] += 1
            continue

        found_d = found_d or start_d or pit_d
        if found_d is None:
            stats["no_date"] += 1
            continue
        pt = coords.get(i)
        if not pt:
            stats["place_nocoord"] += 1
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

    print("people, premieres, discoveries…")
    found = set()
    for kind_name, kind, cat, weight in (
        ("births", BORN, "people", "born"),
        ("deaths", DIED, "people", "died"),
        ("premieres", PREMIERED, "culture", "premiere"),
        ("discoveries", DISCOVERED, "science", "discovery"),
    ):
        for r in read(kind_name):
            pt = parse_point(r["c"])
            d = parse_time(r["t"], r["prec"])
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
            if kind in (PREMIERED, DISCOVERED):
                found.add(i)
            happenings.append([i, r["title"], pt[0], pt[1], s0, s1, CAT[cat], kind,
                               score, img, clean_desc(r["desc"]), date_label(d), r["placeLabel"] or ""])
            stats[kind_name] += 1
    # A found object or premiered work is shown where it happened, not as a
    # "place" at the museum or theatre that holds it today.
    happenings = [h for h in happenings if not (h[0] in found and h[7] not in HAPPENED)]
    standing = [p for p in standing if p[0] not in found]

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

    long_.sort(key=lambda r: -r[8])
    total += dump(os.path.join(OUT, "long.json"), long_)
    for r in long_:
        loc[id(r)] = "long"

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
                entries.append([chunk_min(chunk), max(r[4] for r in chunk), len(chunk)])
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
            loc[id(r)] = f"d/{key}"

    deep = [r for r in short if r[13] > TIERS[-1][2]]
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

    # Events with no one place: a small file the app keeps whole.
    worldwide.sort(key=lambda r: -r[8])
    for r in worldwide:
        r.append(0)
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
    seen = set()
    search = []
    cutoff = 0
    for r in sorted(happenings + worldwide, key=lambda r: -r[8]):
        if r[0] in seen:
            continue
        seen.add(r[0])
        search.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], loc[id(r)]])
        if len(search) >= SEARCH_MAX:
            cutoff = r[8]
            break
    extra = [r for r in standing if r[0] not in seen and r[8] >= max(cutoff, SEARCH_MIN_PLACE_SCORE)]
    for r in sorted(extra, key=lambda r: -r[8])[:SEARCH_MAX_PLACES]:
        search.append([r[0], r[1], r[2], r[3], r[4], r[4], r[6], r[7], loc[id(r)]])
    # Most notable first: the app ranks ties by position.
    score = {r[0]: r[8] for r in happenings + worldwide + standing}
    search.sort(key=lambda e: -score[e[0]])
    total += dump(os.path.join(OUT, "search.json"), search)

    index = {
        "version": _digest.hexdigest()[:10],
        "categories": CATEGORIES,
        "longSpan": LONG_SPAN,
        "tiers": tiers,
        "detailMinz": TIERS[-1][2] + 1,
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
