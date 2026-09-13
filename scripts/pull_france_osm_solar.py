#!/usr/bin/env python
"""National OSM solar pull for France, chunked, with placement classified against VIDA.

A single country-wide Overpass query for France times out (the same failure
`scripts/new_region.py check` hits, and the reason CLAUDE.md says country fetches need
per-province chunking). This walks a lon/lat grid instead, writes one parquet per tile so
a crashed run resumes, and concatenates at the end.

The output is what `earthpv atlas --osm-solar` consumes: `id`, `placement`, `area_m2`,
geometry. Placement comes from `build_overpass_labels(iso3="FRA")`, i.e. VIDA building
overlap on the local 4.1 GB parquet rather than Overture's remote S3, which times out
from this machine.

Overlapping features are dissolved by the caller (`atlas.build_evidence_atlas` runs
`labels.dissolve_overlapping`), so tile-boundary duplicates are removed there; this
script only de-duplicates on OSM id, which handles a feature returned by two tiles.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

log = logging.getLogger("fr-osm")
FRANCE = (-5.15, 41.33, 9.56, 51.09)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--nx", type=int, default=7)
    ap.add_argument("--ny", type=int, default=7)
    ap.add_argument("--tile-dir", default="data/labels/france_osm_tiles")
    ap.add_argument("--out", default="data/labels/france_national_osm_solar.parquet")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    from earthpv.overpass import build_overpass_labels

    tiles = Path(a.tile_dir)
    tiles.mkdir(parents=True, exist_ok=True)
    x = np.linspace(FRANCE[0], FRANCE[2], a.nx + 1)
    y = np.linspace(FRANCE[1], FRANCE[3], a.ny + 1)

    failed, empty = [], []
    for i in range(a.nx):
        for j in range(a.ny):
            name = f"fr_{i:02d}_{j:02d}"
            done = tiles / f"{name}_overpass_solar.parquet"
            if done.exists():
                continue
            bbox = (float(x[i]), float(y[j]), float(x[i + 1]), float(y[j + 1]))
            try:
                build_overpass_labels(out_dir=tiles, bbox=bbox, name=name,
                                      timeout=a.timeout, iso3="FRA")
                log.info("tile %s ok", name)
            except Exception as e:  # noqa: BLE001 - one bad tile must not kill the run
                # An all-sea tile legitimately returns nothing, and reporting that as a
                # failure sends the next operator chasing tiles that are the Bay of Biscay.
                # Only transport/parse errors are worth retrying.
                if "no solar features" in str(e):
                    log.info("tile %s: empty (no solar features in bbox)", name)
                    empty.append(name)
                else:
                    log.warning("tile %s failed: %s", name, e)
                    failed.append(name)

    parts = []
    for p in sorted(tiles.glob("*_overpass_solar.parquet")):
        try:
            parts.append(gpd.read_parquet(p))
        except Exception as e:  # noqa: BLE001
            log.warning("unreadable tile %s: %s", p, e)
    if not parts:
        log.error("no tiles were pulled")
        return 1
    g = pd.concat(parts, ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry="geometry", crs="EPSG:4326")
    before = len(g)
    if "id" in g.columns:
        g = g.drop_duplicates(subset="id")
    g.to_parquet(a.out)
    log.info("wrote %d features (%d before de-dup) -> %s", len(g), before, a.out)
    if empty:
        log.info("%d tiles legitimately empty (sea/abroad): %s", len(empty), empty)
    if failed:
        log.error("FAILED tiles (re-run to retry): %s", failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
