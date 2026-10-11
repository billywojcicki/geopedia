#!/usr/bin/env python3
"""Turn raw Wikidata CSVs (build/raw) into the static data files the site loads.

Output (data/):
  index.json        bucket + tile index, year histogram, metadata
  h/<n>.json        "happenings" (events, foundings, births, deaths) bucketed by year
  h/long.json       happenings spanning more than LONG_SPAN years (wars, eras)
  p/<key>.json      "standing" places (buildings, towns...) in a spatial quadtree
  search.json       compact title index of the most notable items

Record layout (arrays, to keep files small):
  [qid, title, lat, lon, start, end, cat, kind, score, img, desc, date, place]
  start/end are astronomical years (0 = 1 BC). img is "a/ab/File.jpg" (Commons
  hash path) or "". date is a human-readable date string. place is the
  birth/death place label for people, else "".

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
# kind codes
EVENT, BUILT, FOUNDED, ESTABLISHED, BORN, DIED = range(6)

LONG_SPAN = 25  # years; longer happenings go to h/long.json
BUCKET_TARGET = 4000  # happenings per bucket file
TILE_MAX = 2500  # standing places per quadtree leaf
MIN_YEAR, MAX_YEAR = -10000, 2026

# Importance = sitelinks * weight. Sitelinks (how many language editions have
# an article) is a decent proxy for global significance.
WEIGHT = {
    "conflict": 1.0,
    "politics": 1.0,
    "disaster": 0.9,
    "culture": 0.9,
    "sports": 0.5,
    "event": 0.75,  # dated event with no recognised class
    # Places and people collect sitelinks far more easily than events (every
    # language edition has an article on every city), so they're scaled down
    # to sit alongside events of similar historical weight.
    "settlement": 0.3,
    "structure": 0.65,
    "institution": 0.3,
    None: 0.4,  # place of unrecognised class
    "low": 0.15,
    "born": 0.25,  # births mostly show people who became famous decades later
    "died": 0.3,
}
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

    def item_role(i):
        """Role of an item. Exclusion only wins when it's clearly the closer
        match (Stanford is both a university and an open-access publisher)."""
        keep, excl = best_keep.get(i), best_excl.get(i)
        if excl is not None and (keep is None or excl < keep[0] - 1):
            return "exclude"
        return keep[2] if keep else None

    coords = {}
    for r in read("coords"):
        i = qid(r["item"])
        if i in items and i not in coords:
            pt = parse_point(r["c"])
            if pt:
                coords[i] = pt
    loccoords = {}
    for r in read("loccoords"):
        i = qid(r["item"])
        if i not in items or i in loccoords:
            continue
        if r["cap"] or r["big"]:
            loccoords[i] = None  # located in a country/state/ocean: too vague
            continue
        pt = parse_point(r["c"])
        if pt:
            loccoords[i] = pt

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
            if start_d is None:
                stats["no_date"] += 1
                continue
            pt = coords.get(i) or loccoords.get(i)
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
            if pit_d and pit_d[3] >= 10:
                label = date_label(pit_d)
            else:
                first = min((d for d in (start_d, end_d) if d), key=lambda d: d[0])
                last = max((d for d in (start_d, end_d) if d), key=lambda d: d[0])
                label = date_label(first, last)
            disp = "culture" if cat in ("culture", "sports") else (cat or "politics")
            score = sl * WEIGHT[cat or "event"] * bonus
            happenings.append([i, it["title"], pt[0], pt[1], start, end, CAT[disp], EVENT,
                               round(score, 1), img, it.get("desc", ""), label, ""])
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
        # Only notable foundings go in the global time buckets; minor ones still
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

    print("people…")
    for kind_name, kind in (("births", BORN), ("deaths", DIED)):
        for r in read(kind_name):
            pt = parse_point(r["c"])
            d = parse_time(r["t"], r["prec"])
            if not pt or not d:
                continue
            s0, s1 = span(d)
            if s1 - s0 > 100:
                continue
            sl = int(r["sl"] or 0)
            img = commons_path(r["image"])
            score = round(sl * WEIGHT["born" if kind == BORN else "died"] * (IMAGE_BONUS if img else 1), 1)
            happenings.append([qid(r["item"]), r["title"], pt[0], pt[1], s0, s1, CAT["people"], kind,
                               score, img, clean_desc(r["desc"]), date_label(d), r["placeLabel"] or ""])
            stats[kind_name] += 1

    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"  happenings: {len(happenings)}  standing: {len(standing)}")

    write(happenings, standing)


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def write(happenings, standing):
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "h"))
    os.makedirs(os.path.join(OUT, "p"))

    # Happenings: short ones bucketed by start year, long ones in one file.
    happenings.sort(key=lambda r: (r[4], -r[8]))
    short = [r for r in happenings if r[5] - r[4] <= LONG_SPAN]
    long_ = [r for r in happenings if r[5] - r[4] > LONG_SPAN]
    long_.sort(key=lambda r: -r[8])
    total = dump(os.path.join(OUT, "h", "long.json"), long_)

    buckets = []
    cur = []
    for r in short:
        if len(cur) >= BUCKET_TARGET and r[4] != cur[-1][4]:
            buckets.append(cur)
            cur = []
        cur.append(r)
    if cur:
        buckets.append(cur)
    bucket_index = []
    for n, b in enumerate(buckets):
        b.sort(key=lambda r: -r[8])
        total += dump(os.path.join(OUT, "h", f"{n}.json"), b)
        bucket_index.append([b and min(r[4] for r in b), max(r[4] for r in b), len(b)])

    # Standing places: quadtree split until leaves are small enough.
    standing.sort(key=lambda r: -r[8])
    tiles = []

    def split(recs, x0, y0, x1, y1, key):
        nonlocal total
        if len(recs) <= TILE_MAX or len(key) >= 14:
            if recs:
                total += dump(os.path.join(OUT, "p", f"{key or 'root'}.json"), recs)
                tiles.append([key or "root", x0, y0, x1, y1, len(recs)])
            return
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        quads = [[], [], [], []]
        for r in recs:
            q = (1 if r[3] >= mx else 0) + (2 if r[2] < my else 0)
            quads[q].append(r)
        split(quads[0], x0, my, mx, y1, key + "0")
        split(quads[1], mx, my, x1, y1, key + "1")
        split(quads[2], x0, y0, mx, my, key + "2")
        split(quads[3], mx, y0, x1, my, key + "3")

    split(standing, -180, -90, 180, 90, "")

    # Year histogram for the timeline (short + long happenings by start year).
    hist = Counter()
    for r in happenings:
        hist[max(MIN_YEAR, min(MAX_YEAR, r[4]))] += 1

    # Search index: the most notable items of all kinds.
    seen = set()
    search = []
    for r in sorted(happenings, key=lambda r: -r[8]):
        if r[0] in seen:
            continue
        seen.add(r[0])
        search.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]])
        if len(search) >= 40000:
            break
    total += dump(os.path.join(OUT, "search.json"), search)

    index = {
        "version": 1,
        "categories": CATEGORIES,
        "longSpan": LONG_SPAN,
        "buckets": bucket_index,
        "tiles": tiles,
        "hist": {"min": MIN_YEAR, "max": MAX_YEAR,
                 "counts": [hist.get(y, 0) for y in range(MIN_YEAR, MAX_YEAR + 1)]},
        "counts": {"happenings": len(happenings), "standing": len(standing)},
    }
    total += dump(os.path.join(OUT, "index.json"), index)
    print(f"buckets: {len(buckets)}  long: {len(long_)}  tiles: {len(tiles)}  total: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
