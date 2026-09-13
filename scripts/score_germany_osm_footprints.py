#!/usr/bin/env python
"""National roofclf scoring over Germany with OSM footprints instead of VIDA.

The paired half of the register validation. Measured over 27 German cells, VIDA returns
300,222 footprints where OSM returns 465,707, and half of all German OSM rooftop arrays sit
more than 20 m from any VIDA polygon. Since the sub-400 m2 estimator prices flagged ROOF
AREA, that difference goes straight into the number, so the register check is run twice and
the two passes differ in exactly one input.

Uses `score_buildings_national`'s `buildings_fn` hook, so the model, threshold, composites,
cell grid and scoring code are identical between passes.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-osm-score")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells-csv", required=True)
    ap.add_argument("--model-path", default="data/roofclf_germany/model_full.json")
    ap.add_argument("--composites", default="data/composites/germany")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--footprints", choices=["vida", "osm"], default="osm")
    ap.add_argument("--geofabrik", default="/home/tobi/earthpv_data/geofabrik")
    ap.add_argument("--min-roof-area-m2", type=float, default=0.0)
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_roofclf_border_germany import osm_buildings

    from earthpv.roofclf import load_model, score_buildings_national

    out_dir = Path(args.out_dir or
                   f"data/roofclf_national_germany_{args.footprints}/germany/prob")
    if args.footprints == "vida":
        # None falls through to score_buildings_national's own fetch_vida_buildings, which
        # is what the deployed Pakistani chain uses.
        buildings_fn = None
        zips = []
    else:
        zips = sorted(Path(args.geofabrik).glob("*.zip"))
        if not zips:
            raise SystemExit(f"no OSM extracts under {args.geofabrik}")
        log.info("OSM extracts: %s", [z.name for z in zips])

    def _osm(bbox):
        g = osm_buildings(bbox, zips)
        if g.empty:
            return gpd.GeoDataFrame({"geometry": [], "area_m2": [], "id": []},
                                    geometry="geometry", crs="EPSG:4326")
        if args.min_roof_area_m2:
            g = g[g.area_m2 >= args.min_roof_area_m2].reset_index(drop=True)
        return g

    if args.footprints == "osm":
        buildings_fn = _osm

    model, feats = load_model(Path(args.model_path))
    cells = set(pd.read_csv(args.cells_csv).cell.astype(str))
    log.info("scoring %d cells with %s footprints", len(cells), args.footprints)
    out = score_buildings_national(
        "germany", model, feats, Path(args.composites), out_dir,
        min_roof_area_m2=args.min_roof_area_m2, buildings_fn=buildings_fn, cells=cells)
    log.info("wrote %s", out)


if __name__ == "__main__":
    main()
