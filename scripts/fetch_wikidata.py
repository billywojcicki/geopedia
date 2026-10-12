#!/usr/bin/env python3
"""Fetch geotagged, dated Wikidata items (with English Wikipedia articles).

Queries the QLever Wikidata SPARQL endpoint (fast, no 60s timeout) and caches
raw CSV results in build/raw/. Re-run with --force to refetch.

Usage: python3 scripts/fetch_wikidata.py [--force] [name ...]
"""
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

# Non-human items that carry a date and a location. Events may also be
# located only by the city or region (P131) or country (P17) they happened
# in: the build places those at that city, or at the country's capital.
CANDIDATE = """
  {
    { ?item wdt:P585 [] } UNION { ?item wdt:P580 [] } UNION { ?item wdt:P571 [] } UNION { ?item wdt:P1619 [] }
    { ?item wdt:P625 [] } UNION { ?item wdt:P276 ?_l . ?_l wdt:P625 [] }
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
    # Events located only through P276. ?cap/?big flag locations that are
    # countries, states, oceans etc. (their coordinate is a meaningless centroid).
    "loccoords": f"""
SELECT DISTINCT ?item ?loc ?label ?c ?cap ?capc ?big ?area WHERE {{
  {ENWIKI}
  {{ ?item wdt:P585 [] }} UNION {{ ?item wdt:P580 [] }}
  ?item wdt:P276 ?loc . ?loc wdt:P625 ?c .
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

for prop in ["P585", "P580", "P582", "P571", "P576", "P1619"]:
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


# Works first performed at a known venue (operas, ballets, plays, symphonies),
# objects found at a known place (hoards, fossils, manuscripts) and
# spacecraft launched from a known site (Sputnik 1, Apollo 11).
for kind, date_prop, place_prop in [("premieres", "P1191", "P4647"), ("discoveries", "P575", "P189"),
                                    ("launches", "P619", "P1427")]:  # P1427: start point (launch pad)
    QUERIES[kind] = f"""
SELECT ?item (SAMPLE(?ti) AS ?title) (SAMPLE(?s) AS ?sl) {PACKED_DATE}
       (SAMPLE(?pl) AS ?place) (SAMPLE(?pll) AS ?placeLabel) (SAMPLE(?co) AS ?c) (SAMPLE(?cp) AS ?cap)
       (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) WHERE {{
  ?item wikibase:sitelinks ?s .
  {ENWIKI} ?article schema:name ?ti .
  {dated(date_prop)}
  {PACK}
  ?item wdt:{place_prop} ?pl . ?pl wdt:P625 ?co .
  OPTIONAL {{ ?pl wdt:P31 ?cp VALUES ?cp {{ {COUNTRY_CLASSES} }} }}  # a country or state: too vague
  OPTIONAL {{ ?pl rdfs:label ?pll FILTER(LANG(?pll) = "en") }}
  OPTIONAL {{ ?item wdt:P18 ?img }}
  OPTIONAL {{ ?item schema:description ?d FILTER(LANG(?d) = "en") }}
}} GROUP BY ?item{" HAVING (MAX(?s) >= 10)" if kind == "launches" else ""}"""


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
            with urllib.request.urlopen(req, timeout=600) as resp, open(path + ".tmp", "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
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
