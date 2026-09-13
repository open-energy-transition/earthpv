#!/usr/bin/env python
"""Download every French commune boundary from geo.api.gouv.fr, one departement at a time.

The national density-versus-register comparison apportions each 0.1 degree cell to the
communes it intersects, so it needs the whole commune layer, not the 14 mapped ones.
Fetched per departement because the national endpoint times out, and cached to parquet
because the round trip is minutes.

Departement codes include the two Corsican ones ('2A', '2B'), which are not integers --
zero-padding an int range silently drops Corsica and leaves a hole in the map.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

REPO = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "earthpv-france/1.0 (research tool; contact via repo issues)"}
URL = ("https://geo.api.gouv.fr/departements/{dep}/communes"
       "?fields=code,nom,surface,population,contour&format=geojson&geometry=contour")

DEPS = [f"{i:02d}" for i in range(1, 20)] + ["2A", "2B"] + \
       [f"{i:02d}" for i in range(21, 96)]

log = logging.getLogger("communes")


def fetch(dep: str, tries: int = 4):
    for t in range(tries):
        try:
            req = urllib.request.Request(URL.format(dep=dep), headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            log.warning("dep %s attempt %d: %s", dep, t + 1, e)
            time.sleep(10 * (t + 1))
    return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    out = REPO / "data" / "labels" / "france_communes.parquet"
    rows = []
    failed = []
    for dep in DEPS:
        d = fetch(dep)
        if not d or not d.get("features"):
            failed.append(dep)
            continue
        for f in d["features"]:
            p = f["properties"]
            if not f.get("geometry"):
                continue
            rows.append({
                "insee": str(p["code"]).zfill(5), "nom": p.get("nom"),
                "dep": dep, "surface_ha": p.get("surface"),
                "population": p.get("population"),
                "geometry": shape(f["geometry"]),
            })
        log.info("dep %s: %d communes (running total %d)", dep, len(d["features"]), len(rows))
    g = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs="EPSG:4326")
    g.to_parquet(out)
    log.info("wrote %d communes -> %s", len(g), out)
    if failed:
        log.error("FAILED departements (rerun): %s", failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
