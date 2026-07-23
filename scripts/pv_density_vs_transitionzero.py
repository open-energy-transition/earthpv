"""Build two comparison artifacts from the current density run against TransitionZero's
rooftop-solar hex dataset:

1. Our own PV density choropleth (est_mwp_det per 0.1-deg grid cell).
2. A vs-TransitionZero share-diff map: since TZ's `data/estimated_rooftop_solar_capacity.json`
   is not in comparable absolute units to our est_mwp_det (different methodology/scope --
   confirmed 2026-07-16, see docs), both datasets are normalized to percent-of-national-total
   per spatial unit before differencing (share_diff_pp = our %-share - TZ's %-share, per TZ
   H3 hexagon). This answers "do the two datasets agree on where PV concentrates", which is
   the meaningful comparison; raw magnitudes are not comparable.

Writes JSON data consumed by the two HTML templates (kept as plain data-prep, not committed
HTML -- the HTML is hand-built to match the dataviz skill's palette/marks conventions).

Usage:
  .pixi/envs/default/bin/python scripts/pv_density_vs_transitionzero.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

PRED_DIR = Path("data/predictions_pk16085/pakistan")
TZ_PATH = Path("data/estimated_rooftop_solar_capacity.json")
OUT_DIR = PRED_DIR / "density" / "maps"


def load_tz() -> gpd.GeoDataFrame:
    raw = json.loads(TZ_PATH.read_text())
    rows = []
    for r in raw:
        geom = shape(json.loads(r["geojson"]))
        val = float(r["value"][0]) if r["value"] else 0.0
        rows.append({"name": r["name"], "value": val, "geometry": geom})
    tz = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    total = tz.value.sum()
    tz["tz_share_pct"] = tz.value / total * 100.0
    return tz


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    grid = gpd.read_parquet(PRED_DIR / "density" / "grid.geoparquet")
    meta = json.loads((PRED_DIR / "density" / "meta.json").read_text())
    total_mwp = meta["total_est_mwp_det"]
    grid = grid[["cell", "lon_center", "lat_center", "est_mwp_det", "geometry"]].copy()
    grid["our_share_pct"] = grid.est_mwp_det / total_mwp * 100.0

    nonzero = grid[grid.est_mwp_det > 0]
    print(f"Grid: {len(nonzero)}/{len(grid)} nonzero cells, total {total_mwp:.1f} MWp")

    # -- Density map data: nonzero cells only, sqrt-transformed for the color scale --
    density_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(r.lon_center, 4), round(r.lat_center, 4)]},
            "properties": {"mwp": round(float(r.est_mwp_det), 3)},
        }
        for r in nonzero.itertuples()
    ]

    # -- vs-TransitionZero: assign each grid cell centroid to its containing TZ hexagon --
    tz = load_tz()
    reps = gpd.GeoDataFrame(
        {"our_share_pct": grid.our_share_pct}, geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center),
        crs="EPSG:4326",
    )
    hits = gpd.sjoin(reps, tz[["name", "geometry"]], predicate="within", how="left")
    our_share_by_hex = hits.dropna(subset=["name"]).groupby("name").our_share_pct.sum()

    tz = tz.set_index("name")
    tz["our_share_pct"] = our_share_by_hex.reindex(tz.index).fillna(0.0)
    tz["share_diff_pp"] = tz.our_share_pct - tz.tz_share_pct
    matched = int((our_share_by_hex.reindex(tz.index).fillna(0.0) > 0).sum())
    print(f"TZ hexagons: {len(tz)}, {matched} received >=1 of our grid cells")
    print(f"share_diff_pp range: {tz.share_diff_pp.min():.3f} to {tz.share_diff_pp.max():.3f}")

    tz_features = []
    for name, row in tz.iterrows():
        geom = row.geometry.simplify(0.002, preserve_topology=True)
        tz_features.append({
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": {
                "name": name,
                "tz_pct": round(float(row.tz_share_pct), 4),
                "our_pct": round(float(row.our_share_pct), 4),
                "diff_pp": round(float(row.share_diff_pp), 4),
            },
        })

    regions = gpd.read_parquet(PRED_DIR / "density" / "regions.geoparquet")
    provinces = regions[regions.level == "region"]
    outline_features = [
        {
            "type": "Feature",
            "geometry": row.geometry.simplify(0.01, preserve_topology=True).__geo_interface__,
            "properties": {"name": row["name"]},
        }
        for _, row in provinces.iterrows()
    ]
    bounds = grid.total_bounds.tolist()  # [minx, miny, maxx, maxy]

    (OUT_DIR / "density_data.json").write_text(json.dumps({
        "total_mwp": total_mwp,
        "n_cells": int(len(grid)),
        "n_nonzero": int(len(nonzero)),
        "bounds": bounds,
        "outline": outline_features,
        "features": density_features,
    }))
    (OUT_DIR / "tz_compare_data.json").write_text(json.dumps({
        "diff_min": float(tz.share_diff_pp.min()),
        "diff_max": float(tz.share_diff_pp.max()),
        "n_hex": int(len(tz)),
        "n_matched": matched,
        "bounds": bounds,
        "outline": outline_features,
        "features": tz_features,
    }))
    print(f"Wrote {OUT_DIR}/density_data.json and tz_compare_data.json")


if __name__ == "__main__":
    main()
