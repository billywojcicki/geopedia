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
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
"""

ENWIKI = "?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ."

# Non-human items that carry a date and a location (own or via P276).
CANDIDATE = """
  { ?item wdt:P585 [] } UNION { ?item wdt:P580 [] } UNION { ?item wdt:P571 [] } UNION { ?item wdt:P1619 [] }
  { ?item wdt:P625 [] } UNION { ?item wdt:P276 ?_l . ?_l wdt:P625 [] }
"""

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
SELECT DISTINCT ?item ?loc ?c ?cap ?big WHERE {{
  {ENWIKI}
  {{ ?item wdt:P585 [] }} UNION {{ ?item wdt:P580 [] }}
  ?item wdt:P276 ?loc . ?loc wdt:P625 ?c .
  FILTER NOT EXISTS {{ ?item wdt:P625 [] }}
  OPTIONAL {{ ?loc wdt:P36 ?cap }}
  OPTIONAL {{ ?loc wdt:P31 ?big VALUES ?big {{ wd:Q6256 wd:Q3624078 wd:Q5107 wd:Q9430 wd:Q165 wd:Q3024240 wd:Q35657 wd:Q107390 wd:Q10864048 wd:Q1620908 wd:Q82794 wd:Q2221906 }} }}
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
SELECT ?item ?t ?prec WHERE {{
  {ENWIKI}
  {CANDIDATE}
  ?item p:{prop}/psv:{prop} [ wikibase:timeValue ?t ; wikibase:timePrecision ?prec ] .
}}"""

for kind, place_prop, date_prop in [("births", "P19", "P569"), ("deaths", "P20", "P570")]:
    QUERIES[kind] = f"""
SELECT ?item (SAMPLE(?ti) AS ?title) (SAMPLE(?s) AS ?sl) (SAMPLE(?tv) AS ?t) (SAMPLE(?pr) AS ?prec)
       (SAMPLE(?pl) AS ?place) (SAMPLE(?pll) AS ?placeLabel) (SAMPLE(?co) AS ?c)
       (SAMPLE(?img) AS ?image) (SAMPLE(?d) AS ?desc) WHERE {{
  ?item wdt:P31 wd:Q5 ; wikibase:sitelinks ?s .
  FILTER(?s >= {PEOPLE_MIN_SITELINKS})
  {ENWIKI} ?article schema:name ?ti .
  ?item p:{date_prop}/psv:{date_prop} [ wikibase:timeValue ?tv ; wikibase:timePrecision ?pr ] .
  ?item wdt:{place_prop} ?pl . ?pl wdt:P625 ?co .
  OPTIONAL {{ ?pl rdfs:label ?pll FILTER(LANG(?pll) = "en") }}
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
            time.sleep(2 ** (attempt + 1))
    raise SystemExit(f"failed: {name}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    os.makedirs(RAW, exist_ok=True)
    for name, q in QUERIES.items():
        if args and name not in args:
            continue
        run(name, q, force)


if __name__ == "__main__":
    main()
