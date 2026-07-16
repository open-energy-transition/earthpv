"""Diff two `density` runs (current vs. pre-boom epoch) into a PV-growth time series.

Pakistan's rooftop PV stock is dominated by the post-2022 import boom (README.md,
"Planned: two-epoch change detection"). Once `density` has been run once per epoch
(current: data/predictions/<aoi>/density, pre-boom: data/predictions_preboom/<aoi>/
density — see scripts/run_preboom_pipeline.sh), this script joins the two grid/region
aggregates on cell/region id and writes the delta as the spatially-resolved growth map.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pv_growth_map")

DELTA_COLS = ["est_mwp_det", "est_mwp_exp"]


def _diff(current: pd.DataFrame, preboom: pd.DataFrame, on: str) -> pd.DataFrame:
    merged = current.merge(
        preboom[[on, *DELTA_COLS]], on=on, how="left", suffixes=("", "_preboom")
    )
    for col in DELTA_COLS:
        merged[col + "_preboom"] = merged[col + "_preboom"].fillna(0.0)
        merged[f"delta_{col}"] = (merged[col] - merged[col + "_preboom"]).round(4)
    return merged


def run(current_dir: Path, preboom_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    cur_grid = gpd.read_parquet(current_dir / "grid.geoparquet")
    pre_grid = pd.read_csv(preboom_dir / "grid.csv")
    grid = _diff(cur_grid, pre_grid, on="cell")
    grid.to_parquet(out_dir / "growth_grid.geoparquet")
    grid.drop(columns="geometry").to_csv(out_dir / "growth_grid.csv", index=False)
    log.info(
        "Grid growth: current %.1f MWp (det) vs pre-boom %.1f MWp -> delta %.1f MWp",
        cur_grid.est_mwp_det.sum(),
        pre_grid.est_mwp_det.sum(),
        grid.delta_est_mwp_det.sum(),
    )

    cur_reg_path = current_dir / "regions.geoparquet"
    pre_reg_path = preboom_dir / "regions.csv"
    if cur_reg_path.exists() and pre_reg_path.exists():
        cur_reg = gpd.read_parquet(cur_reg_path)
        pre_reg = pd.read_csv(pre_reg_path)
        regions = _diff(cur_reg, pre_reg, on="region_id")
        regions.to_parquet(out_dir / "growth_regions.geoparquet")
        regions.drop(columns="geometry").to_csv(out_dir / "growth_regions.csv", index=False)
        regions.to_file(out_dir / "growth_regions.geojson", driver="GeoJSON")
        top = regions.sort_values("delta_est_mwp_det", ascending=False)[
            ["name", "est_mwp_det", "delta_est_mwp_det"]
        ].head(10)
        log.info("Top districts/regions by MWp growth:\n%s", top.to_string(index=False))
    else:
        log.warning("No regions.geoparquet/regions.csv found; skipping region-level growth")

    log.info("Wrote growth map -> %s", out_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aoi", default="pakistan")
    parser.add_argument("--current-dir", type=Path, default=Path("data/predictions"))
    parser.add_argument("--preboom-dir", type=Path, default=Path("data/predictions_preboom"))
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    current_density = args.current_dir / args.aoi / "density"
    preboom_density = args.preboom_dir / args.aoi / "density"
    out = args.out_dir or (current_density / "growth")
    run(current_density, preboom_density, out)
