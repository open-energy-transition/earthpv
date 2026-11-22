#!/usr/bin/env python
"""Estimate how a building layer moves Verified through untagged OSM solar polygons.

`labels.classify_placement` calls an OSM solar polygon rooftop from its tags when it has
them; an untagged generator polygon is rooftop when footprints cover >= 0.5 of it, ground
otherwise, and the atlas converts rooftop at 0.18 kWp/m2 (module) and ground at 0.05 (site).
The staging chains reuse the labels' stored placement, so their Verified cannot move. This
re-classifies the overlap-decided polygons under each layer and prices the flips.

Run from the earthpv repo root with its pixi python:
  python scripts/building_layer_verified_effect.py <labels.parquet> name=layer.parquet ...
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")
from building_layer_attribution import coverage  # noqa: E402
from earthpv import overture  # noqa: E402

MODULE, LAND, FRAC, ROOF_MAX = 0.18, 0.05, 0.5, 100_000.0
lab = gpd.read_parquet(sys.argv[1]).to_crs(4326)
roofish = (lab.osm_location.isin(["roof", "rooftop"]) | lab.generator_place.isin(["roof", "rooftop"]))
by_overlap = (~roofish & (lab["kind"] != "plant")
              & lab.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
              & (lab.area_m2 <= ROOF_MAX))
sub = lab[by_overlap].reset_index(drop=True)
print(f"{Path(sys.argv[1]).name}: {len(sub)} polygons placed by footprint overlap "
      f"({sub.area_m2.sum() / 1e6:.3f} km2) of {len(lab)} features")
con = overture.connect()
ref = None
for spec in sys.argv[2:]:
    name, path = spec.split("=", 1)
    roof = coverage(con, path, sub) >= FRAC
    mwp = float((sub.area_m2 * np.where(roof, MODULE, LAND)).sum() / 1000.0)
    if ref is None:
        ref = (roof, mwp)
        print(f"  {name:10s} rooftop {roof.mean():.3f} of them, {mwp:8.1f} MWp")
        continue
    up = roof & ~ref[0]
    down = ~roof & ref[0]
    print(f"  {name:10s} rooftop {roof.mean():.3f}, {mwp:8.1f} MWp, {mwp - ref[1]:+7.1f} MWp vs "
          f"first layer ({int(up.sum())} ground->roof, {int(down.sum())} roof->ground)")
