#!/usr/bin/env python
"""Pseudo-quadrats for Germany labelled from the register, not from OpenStreetMap.

Germany's roofclf trains on OSM labels that mark ~3.6% of registered rooftop units, so ~96%
of true positives sit in the negative class. A model fed that can only learn which roofs are
large and bright, which is why it correlates with roof area and then loses to a roof-area
baseline outright.

MaStR publishes coordinates at and above 30 kWp: **108,443 geolocated rooftop units in the
30-72 kWp band**, which is inside roofclf's own sub-400 m2 domain and is register-certain
rather than enthusiast-mapped. That is 20x the OSM-labelled buildings in the same cells.

**What this does and does not fix.** Positives in the band become near-certain. Negatives do
not: 4.13M sub-30 kWp units carry no coordinates at all (0.0%, a privacy policy rather than
missing data) and 30.7% of the 30-72 kWp band is also uncoordinated, so "no register point"
still does not mean "no PV". The band is 6.9 of the 49.0 GWp below the segmentation floor, so
this sharpens the top of the domain and leaves the bulk to a later prior-based approach.

Points are address points, not array centroids, so each is buffered to the module area its
registered capacity implies (kWp / DEFAULT_KWP_PER_M2_MODULE) to give `building_table`'s
intersection labelling something to bite on.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mastr-quadrats")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells-csv", required=True)
    ap.add_argument("--points", default="data/labels/mastr_rooftop_30_72kwp_points.parquet")
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--out-dir", default="data/labels/germany_mastr")
    ap.add_argument("--min-units", type=int, default=20)
    args = ap.parse_args()

    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cells = pd.read_csv(args.cells_csv).cell.astype(str).tolist()
    grid = gpd.read_parquet(args.grid)
    grid = grid[grid.cell.isin(cells)]
    pts = gpd.read_parquet(args.points).to_crs(grid.crs)

    man = []
    for _, c in grid.iterrows():
        sub = pts[pts.geometry.within(c.geometry)].copy()
        if len(sub) < args.min_units:
            continue
        # Buffer in a local metric CRS so the radius is metres, not degrees.
        utm = sub.estimate_utm_crs()
        s_m = sub.to_crs(utm)
        area = (sub.kwp / DEFAULT_KWP_PER_M2_MODULE).to_numpy()
        s_m["geometry"] = [g.buffer(math.sqrt(a / math.pi))
                           for g, a in zip(s_m.geometry, area)]
        poly = s_m.to_crs(grid.crs)
        stem = f"de_{c.cell}_calib_mastr"
        gpd.GeoDataFrame({
            "id": [f"mastr-{i}" for i in range(len(poly))],
            "kind": "generator", "placement": "rooftop",
            "area_m2": area, "label_tag": "mastr_register",
            "geometry": poly.geometry.to_numpy(),
        }, geometry="geometry", crs=grid.crs).to_parquet(
            out / f"{stem}_overpass_solar.parquet")
        gpd.GeoDataFrame([{
            "quadrat_id": stem, "location": c.cell, "insee": "", "size_km2": None,
            "shape": "grid_cell", "stratum": "germany_mastr_register",
            "mapping_date": None, "source_geojson": None,
            "label_source": "mastr_30_72kwp_geolocated",
        }], geometry=[c.geometry], crs=grid.crs).to_file(
            out / f"{stem}_boundary.geojson", driver="GeoJSON")
        man.append({"stem": stem, "cell": c.cell, "n_units": int(len(sub)),
                    "median_kwp": round(float(sub.kwp.median()), 1)})

    (out / "manifest.json").write_text(json.dumps(man, indent=2))
    log.info("wrote %d quadrats, %d register-certain positives -> %s",
             len(man), sum(m["n_units"] for m in man), out)


if __name__ == "__main__":
    main()
