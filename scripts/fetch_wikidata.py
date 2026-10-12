#!/usr/bin/env python3
"""Fetch geotagged, dated Wikidata items (with English Wikipedia articles).

Queries the QLever Wikidata SPARQL endpoint (fast, no 60s timeout) and caches
raw CSV results in build/raw/. Re-run with --force to refetch.

Usage: python3 scripts/fetch_wikidata.py [--force] [name ...]
"""
import csv
import os
import sys
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://qlever.dev/api/wikidata"
UA = "GeopediaBuild/0.1 (https://github.com/billywojcicki/geopedia)"
RAW = os.path.join(os.path.dirname(__file__), "..", "build", "raw")

PREFIX = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX psn: <http://www.wikidata.org/prop/statement/value-normalized/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX pqv: <http://www.wikidata.org/prop/qualifier/value/>
"""

# A date statement's value, precision, calendar (the RDF export converts
# Julian dates to Gregorian; the build converts them back for display) and
# rank (the build drops deprecated statements and prefers preferred ones; a
# FILTER on the rank here makes QLever silently drop most rows).
def dated(prop, var="st"):
    return f"""?item p:{prop} ?{var} . ?{var} wikibase:rank ?rk ;
    psv:{prop} [ wikibase:timeValue ?tv ; wikibase:timePrecision ?pr ; wikibase:timeCalendarModel ?cal ] ."""

# For one-row-per-item queries: one statement's date packed as
# "rank|time|precision|calendar" so the parts stay together. MAX picks the
# preferred statement first (rank IRIs sort Preferred > Normal > Deprecated).
# QLever wants the expression bound before it is aggregated.
PACKED_DATE = "(MAX(?packed) AS ?date)"
PACK = """BIND(CONCAT(STR(?rk), "|", STR(?tv), "|", STR(?pr), "|", STR(?cal)) AS ?packed)"""

ENWIKI = "?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ."

# Non-human items that carry a date and a location (their own, their
# location's, or their start point's: the Hijra set out from Mecca). Events may
# also be located only by the city or region (P131) or country (P17) they
# happened in: the build places those at that city, or at the country's capital.
CANDIDATE = """
  {
    { ?item wdt:P585 [] } UNION { ?item wdt:P580 [] } UNION { ?item wdt:P571 [] } UNION { ?item wdt:P1619 [] }
    { ?item wdt:P625 [] } UNION { ?item wdt:P276 ?_l . ?_l wdt:P625 [] } UNION { ?item wdt:P1427 ?_s . ?_s wdt:P625 [] }
  } UNION {
    { ?item wdt:P585 [] } UNION { ?item wdt:P580 [] }
    { ?item wdt:P131 ?_m . ?_m wdt:P625 [] } UNION { ?item wdt:P17 [] }
  }
"""
EVENT_DATE = "{ ?item wdt:P585 [] } UNION { ?item wdt:P580 [] }"

# Location classes too vague to pin an event on: countries, states, continents,
# oceans, seas, regions, peninsulas, rivers, mountain ranges... (big areas are
# also caught by their size in the build).
BIG_CLASSES = " ".join("wd:" + q for q in [
    "Q6256", "Q3624078", "Q5107", "Q9430", "Q165", "Q3024240", "Q35657", "Q107390", "Q10864048",
    "Q1620908", "Q82794", "Q2221906", "Q3502482", "Q34763", "Q4022", "Q46831", "Q1322134",
    "Q1973404", "Q166620", "Q399984", "Q1969448", "Q4588528", "Q137186904", "Q15642541", "Q209495",
])
# Things found, premiered or launched that matter less as moments.
THING_CLASSES = " ".join("wd:" + q for q in [
    "Q16521",  # taxon
    "Q11344",  # chemical element
    "Q6999",  # astronomical object
    "Q60186",  # meteorite
    "Q7946",  # mineral
    "Q154210",  # subatomic particle
    "Q2095",  # food
    "Q11424",  # film
    "Q134556",  # single
    "Q7366",  # song
    "Q482994",  # album
])
# Where someone was born or a work premiered: only countries, states,
# continents and oceans are too vague ("historical region" also covers
# Königsberg, the city).
COUNTRY_CLASSES = " ".join("wd:" + q for q in [
    "Q6256", "Q3624078", "Q5107", "Q9430", "Q165", "Q3024240", "Q35657", "Q107390", "Q10864048",
])

# Minimum sitelinks for people (births/deaths) to keep the set focused.
PEOPLE_MIN_SITELINKS = 25

QUERIES = {
    "items": f"""
SELECT DISTINCT ?item ?title ?sl WHERE {{
  {ENWIKI} ?article schema:name ?title .
  ?item wikibase:sitelinks ?sl .
  {CANDIDATE}
  FILTER NOT EXISTS {{ ?item wdt:P31 wd:Q5 }}
}}""",
    "meta": f"""
SELECT ?item (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) WHERE {{
  {ENWIKI}
  {CANDIDATE}
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item schema:description ?d FILTER(LANG(?d) = "en") }}
}} GROUP BY ?item""",
    "coords": f"""
SELECT DISTINCT ?item ?c WHERE {{
  {ENWIKI}
  ?item wdt:P625 ?c .
  {{ ?item wdt:P585 [] }} UNION {{ ?item wdt:P580 [] }} UNION {{ ?item wdt:P571 [] }} UNION {{ ?item wdt:P1619 [] }}
}}""",
    # Events located only through P276 (and documents dated by inception: the
    # Atlantic Charter), or failing that their start point (?start: a voyage's
    # port, a march's first town). ?cap/?big flag locations that are countries,
    # states, oceans etc. (their coordinate is a meaningless centroid).
    "loccoords": f"""
SELECT DISTINCT ?item ?loc ?label ?c ?cap ?capc ?big ?area ?start WHERE {{
  {ENWIKI}
  {{ ?item wdt:P585 [] }} UNION {{ ?item wdt:P580 [] }} UNION {{ ?item wdt:P571 [] }}
  {{ ?item wdt:P276 ?loc }} UNION {{
    ?item wdt:P1427 ?loc . BIND(1 AS ?start)
    FILTER NOT EXISTS {{ ?item wdt:P276 ?_l . ?_l wdt:P625 [] }}
  }}
  ?loc wdt:P625 ?c .
  FILTER NOT EXISTS {{ ?item wdt:P625 [] }}
  OPTIONAL {{ ?loc wdt:P36 ?cap OPTIONAL {{ ?cap wdt:P625 ?capc }} }}
  OPTIONAL {{ ?loc wdt:P31 ?big VALUES ?big {{ {BIG_CLASSES} }} }}
  OPTIONAL {{ ?loc p:P2046/psn:P2046/wikibase:quantityAmount ?area }}
  OPTIONAL {{ ?loc rdfs:label ?label FILTER(LANG(?label) = "en") }}
}}""",
    # Capitals with their validity, so a country maps to its capital of the
    # time (Ottoman Empire: Bursa, Edirne, then Constantinople).
    "capitals": """
SELECT DISTINCT ?country ?cap ?c ?s ?e ?rk WHERE {
  ?country p:P36 ?st . ?st ps:P36 ?cap ; wikibase:rank ?rk .
  ?cap wdt:P625 ?c .
  OPTIONAL { ?st pq:P580 ?s }
  OPTIONAL { ?st pq:P582 ?e }
}""",
    # Events located only through P131 (city, district...). ?cap flags regions
    # with a capital (states, provinces): too vague to pin.
    "p131coords": f"""
SELECT DISTINCT ?item ?loc ?c ?cap ?area WHERE {{
  {ENWIKI}
  {EVENT_DATE}
  ?item wdt:P131 ?loc . ?loc wdt:P625 ?c .
  FILTER NOT EXISTS {{ ?item wdt:P625 [] }}
  OPTIONAL {{ ?loc wdt:P36 ?cap }}
  OPTIONAL {{ ?loc p:P2046/psn:P2046/wikibase:quantityAmount ?area }}
}}""",
    # Country of each dated event without its own coordinates: the build pins
    # nationwide events (revolutions, famines, reforms) at the capital.
    "countrycoords": f"""
SELECT DISTINCT ?item ?country ?label ?capc ?cc WHERE {{
  {ENWIKI}
  {EVENT_DATE}
  ?item wdt:P17 ?country .
  FILTER NOT EXISTS {{ ?item wdt:P625 [] }}
  OPTIONAL {{ ?country wdt:P36 ?cap . ?cap wdt:P625 ?capc }}
  OPTIONAL {{ ?country wdt:P625 ?cc }}
  OPTIONAL {{ ?country rdfs:label ?label FILTER(LANG(?label) = "en") }}
}}""",
    # Events whose own coordinates are just their country's (the Dissolution
    # of the Soviet Union in central Siberia): the build treats them as known
    # only by country.
    "centroids": f"""
SELECT DISTINCT ?item ?country ?label WHERE {{
  {ENWIKI}
  {EVENT_DATE}
  ?item wdt:P625 ?c ; wdt:P17 ?country . ?country wdt:P625 ?c .
  OPTIONAL {{ ?country rdfs:label ?label FILTER(LANG(?label) = "en") }}
}}""",
    "classes": f"""
SELECT DISTINCT ?item ?cls WHERE {{
  {ENWIKI}
  {CANDIDATE}
  ?item wdt:P31 ?cls .
}}""",
}

# Subclass (P279) edges above every class our items use, so the build can
# find each class's *nearest* category root instead of any ancestor.
QUERIES["subclass"] = f"""
SELECT DISTINCT ?a ?b WHERE {{
  {{ SELECT DISTINCT ?cls WHERE {{ {ENWIKI} {CANDIDATE} ?item wdt:P31 ?cls . }} }}
  ?cls wdt:P279* ?a .
  ?a wdt:P279 ?b .
}}"""

for prop in ["P585", "P580", "P582", "P571", "P576", "P1619", "P1249"]:
    QUERIES[f"date_{prop}"] = f"""
SELECT ?item (?tv AS ?t) (?pr AS ?prec) ?cal ?rk WHERE {{
  {ENWIKI}
  {CANDIDATE}
  {dated(prop)}
}}"""

for kind, place_prop, date_prop in [("births", "P19", "P569"), ("deaths", "P20", "P570")]:
    QUERIES[kind] = f"""
SELECT ?item (SAMPLE(?ti) AS ?title) (SAMPLE(?s) AS ?sl) {PACKED_DATE}
       (SAMPLE(?pl) AS ?place) (SAMPLE(?pll) AS ?placeLabel) (SAMPLE(?co) AS ?c) (SAMPLE(?cp) AS ?cap)
       (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) WHERE {{
  ?item wdt:P31 wd:Q5 ; wikibase:sitelinks ?s .
  {ENWIKI} ?article schema:name ?ti .
  {dated(date_prop)}
  {PACK}
  ?item wdt:{place_prop} ?pl . ?pl wdt:P625 ?co .
  OPTIONAL {{ ?pl wdt:P31 ?cp VALUES ?cp {{ {COUNTRY_CLASSES} }} }}  # a country or state: too vague
  OPTIONAL {{ ?pl rdfs:label ?pll FILTER(LANG(?pll) = "en") }}
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item schema:description ?d FILTER(LANG(?d) = "en") }}
}} GROUP BY ?item HAVING (MAX(?s) >= {PEOPLE_MIN_SITELINKS})"""
# (A FILTER on the sitelinks here makes QLever return nothing, at random.)


# Sites found where they are (Lascaux, Tutankhamun's tomb) have no separate
# place of discovery: their own coordinates, flagged so the build keeps them
# as places too. (The place's OPTIONALs stay inside the other branch: with ?pl
# unbound here they would bind it to any country at all.)
OWN_SITE = """ UNION {
    ?item wdt:P625 ?co . BIND(1 AS ?site)
    FILTER NOT EXISTS { ?item wdt:P189 ?_p . ?_p wdt:P625 [] }
  }"""

# Works first performed at a known venue (operas, ballets, plays, symphonies),
# objects found at a known place (hoards, fossils, manuscripts) and
# spacecraft launched from a known site (Sputnik 1, Apollo 11).
for kind, date_prop, place_prop in [("premieres", "P1191", "P4647"), ("discoveries", "P575", "P189"),
                                    ("launches", "P619", "P1427")]:  # P1427: start point (launch pad)
    QUERIES[kind] = f"""
SELECT ?item (SAMPLE(?ti) AS ?title) (SAMPLE(?s) AS ?sl) {PACKED_DATE}
       (SAMPLE(?pl) AS ?place) (SAMPLE(?pll) AS ?placeLabel) (SAMPLE(?co) AS ?c) (SAMPLE(?cp) AS ?cap)
       (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) (SAMPLE(?anc) AS ?thing) (SAMPLE(?site) AS ?own) WHERE {{
  ?item wikibase:sitelinks ?s .
  {ENWIKI} ?article schema:name ?ti .
  # A thing rather than a moment (a fossil genus, an element, a moon, a film):
  # the build gives these less weight.
  OPTIONAL {{ ?item wdt:P31/wdt:P279* ?anc VALUES ?anc {{ {THING_CLASSES} }} }}
  {dated(date_prop)}
  {PACK}
  {{
    ?item wdt:{place_prop} ?pl . ?pl wdt:P625 ?co .
    # Not a country or state: too vague (Ebola was found at the Ebola River, and in Zaire).
    FILTER NOT EXISTS {{ ?pl wdt:P31 ?cp VALUES ?cp {{ {COUNTRY_CLASSES} }} }}
    OPTIONAL {{ ?pl rdfs:label ?pll FILTER(LANG(?pll) = "en") }}
  }}{OWN_SITE if kind == "discoveries" else ""}
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item schema:description ?d FILTER(LANG(?d) = "en") }}
}} GROUP BY ?item{" HAVING (MAX(?s) >= 10)" if kind == "launches" else ""}"""


# Ships that sank, dated by the "significant event" statement (Wikidata has
# no sinking date property) and pinned on the wreck: the Mary Rose, the Vasa,
# the Lusitania. Islands where ships were wrecked are not watercraft.
QUERIES["wrecks"] = f"""
SELECT ?item (SAMPLE(?ti) AS ?title) (SAMPLE(?s) AS ?sl) {PACKED_DATE} (SAMPLE(?co) AS ?c)
       (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) WHERE {{
  ?item wikibase:sitelinks ?s .
  {ENWIKI} ?article schema:name ?ti .
  ?item p:P793 ?st . ?st ps:P793 ?what ; wikibase:rank ?rk ;
    pqv:P585 [ wikibase:timeValue ?tv ; wikibase:timePrecision ?pr ; wikibase:timeCalendarModel ?cal ] .
  VALUES ?what {{ wd:Q906512 wd:Q30880545 wd:Q1522772 }}  # shipwrecking, sinking, capsizing
  {PACK}
  ?item wdt:P625 ?co .
  ?item wdt:P31/wdt:P279* wd:Q1229765 .
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item schema:description ?d FILTER(LANG(?d) = "en") }}
}} GROUP BY ?item HAVING (MAX(?s) >= 10)"""


# Iconic events Wikidata can't place or date (no location statement, a
# vandalised date): scripts/overrides.csv has the place and date, this the
# rest. Re-run with --force after editing it.
with open(os.path.join(os.path.dirname(__file__), "overrides.csv"), newline="", encoding="utf-8") as _f:
    _manual = " ".join(f"wd:{r['qid']}" for r in csv.DictReader(_f))
QUERIES["manual"] = f"""
SELECT ?item (SAMPLE(?ti) AS ?title) (SAMPLE(?s) AS ?sl) (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) WHERE {{
  VALUES ?item {{ {_manual} }}
  ?item wikibase:sitelinks ?s .
  {ENWIKI} ?article schema:name ?ti .
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item schema:description ?d FILTER(LANG(?d) = "en") }}
}} GROUP BY ?item"""


def run(name, query, force=False):
    path = os.path.join(RAW, f"{name}.csv")
    if os.path.exists(path) and not force:
        print(f"[skip] {name} (cached)")
        return
    body = urllib.parse.urlencode({"query": PREFIX + query}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "User-Agent": UA,
        "Accept": "text/csv",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    for attempt in range(4):
        try:
            t0 = time.time()
            tail = b""
            with urllib.request.urlopen(req, timeout=600) as resp, open(path + ".tmp", "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    tail = (tail + chunk)[-2048:]
            # A query that times out mid-export still ends with HTTP 200: QLever
            # appends its error to the truncated result.
            if b"An error has occurred while exporting" in tail:
                raise RuntimeError("export cut short: " + tail.decode(errors="replace").strip().splitlines()[-1])
            os.replace(path + ".tmp", path)
            size = os.path.getsize(path) / 1e6
            print(f"[ok]   {name}: {size:.1f} MB in {time.time() - t0:.0f}s")
            return
        except Exception as e:  # network hiccups, 5xx
            print(f"[err]  {name}: {e} (attempt {attempt + 1})")
            time.sleep(15 * 2 ** attempt)
    raise SystemExit(f"failed: {name}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    os.makedirs(RAW, exist_ok=True)
    ran = False
    for name, q in QUERIES.items():
        if args and name not in args:
            continue
        if ran:
            time.sleep(20)  # QLever rate-limits bursts
        run(name, q, force)
        ran = True


if __name__ == "__main__":
    main()
