"""Aggregate the national per-building SPPI epoch-diff into the same grid/region units
as scripts/pv_growth_map.py's segmentation-based growth map.

`earthpv.sppi.score_buildings_national_growth` scores every VIDA building nationally
against both epochs (composite_0 current, composite_1 pre-boom) with the SPPI spectral
formula -- no model, no GPU. This script sums that per-building signal up to the 0.1-deg
grid cell and admin-region level so it lines up next to (not instead of) the segmentation
growth map's delta_est_mwp columns: a second, independent line of evidence for where PV
appeared, from a completely different mechanism (a fixed formula on reflectance, not a
trained detector's probability).

**Read `mean_delta_sppi`/`n_onset_buildings` as corroborating evidence, not a capacity
number.** SPPI's *level* carries a documented adopter-propensity confound (a static
spectral index alone scores ~0.82 AUC before any panel exists -- see
docs/issues/small-pv-step-signal.md); differencing removes the *level* confound the same
way `postprocess.add_epoch_prior` already leans on for the segmentation probability, but
the pre-boom composites both this and the segmentation growth map depend on were built
2026-07-25, one day BEFORE the imagery.py Collection-1 baseline-offset fix (see CLAUDE.md
"Invariants" / the pv_growth_map.py docstring) -- so a cell-by-cell radiometric
inconsistency is a live, unquantified confound of its own until composite_1 is rebuilt.
`ONSET_THRESHOLD` reuses the building-classification operating point already calibrated
in `sppi.py` (`pooled_precision_threshold`, ~50% precision on the 9 mapped quadrats) rather
than inventing a second, uncalibrated cut -- that calibration was fit on current-epoch
SPPI only, so applying it to the pre-boom side is untested, not a validated choice.

**`onset_mwp` is an explicit, UNCALIBRATED ceiling, not a validated capacity number.**
It is `onset_roof_area_m2 * DEFAULT_KWP_PER_M2_MODULE`, i.e. it treats every square metre
of onset roof area as real PV with no precision weighting at all -- unlike the
segmentation growth map's `est_mwp_rc`, which IS recall/precision-corrected. No LOQO
calibration exists for "SPPI crossed the has-PV threshold between two epochs" as its own
population (only for a single-epoch SPPI level, and only against the 9 urban/industrial
calibration quadrats, not this population's national, arid-terrain-inclusive spread) --
so `onset_mwp` should be read the same way this project's other explicit ceilings are
read (e.g. `sub400_capacity`'s "High" tier): an outer bound on plausibility, not an
estimate, and one that should shrink substantially once corrected for SPPI's documented
arid/bare-terrain false-positive mode and the general "ranking transfers, absolute rates
do not" pattern this project has hit for every other national-scale SPPI/roofclf
extrapolation attempted so far.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sppi_growth_map")

ONSET_THRESHOLD = -0.0183


def _load_buildings(sppi_dir: Path) -> pd.DataFrame:
    files = sorted(Path(sppi_dir).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files under {sppi_dir}")
    parts = [
        pd.read_parquet(f, columns=["cell", "roof_area_m2", "sppi_current", "sppi_preboom", "delta_sppi"])
        for f in files
    ]
    parts = [p for p in parts if not p.empty]
    df = pd.concat(parts, ignore_index=True)
    log.info("Loaded %d buildings across %d cells with SPPI growth data", len(df), df.cell.nunique())
    return df


def _cell_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    onset = (df.sppi_preboom < ONSET_THRESHOLD) & (df.sppi_current >= ONSET_THRESHOLD)
    df = df.assign(onset=onset, onset_roof_area_m2=np.where(onset, df.roof_area_m2, 0.0))
    return df.groupby("cell").agg(
        n_buildings_sppi=("delta_sppi", "size"),
        mean_delta_sppi=("delta_sppi", "mean"),
        median_delta_sppi=("delta_sppi", "median"),
        n_onset_buildings=("onset", "sum"),
        onset_roof_area_m2=("onset_roof_area_m2", "sum"),
    ).reset_index()


def run(sppi_dir: Path, grid_path: Path, regions_path: Path | None, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cell_agg = _cell_aggregate(_load_buildings(sppi_dir))

    grid = gpd.read_parquet(grid_path)
    merged = grid[["cell", "geometry", "lon_center", "lat_center", "cell_area_km2"]].merge(
        cell_agg, on="cell", how="left"
    )
    count_cols = ["n_buildings_sppi", "n_onset_buildings", "onset_roof_area_m2"]
    merged[count_cols] = merged[count_cols].fillna(0.0)
    merged["onset_mwp"] = merged.onset_roof_area_m2 * DEFAULT_KWP_PER_M2_MODULE / 1000.0
    sum_cols = [*count_cols, "onset_mwp"]
    merged.to_parquet(out_dir / "sppi_growth_grid.geoparquet")
    merged.drop(columns="geometry").to_csv(out_dir / "sppi_growth_grid.csv", index=False)
    log.info(
        "Wrote sppi_growth_grid -> %s (%d cells, %d onset buildings, %.0f m2 onset roof area, "
        "%.1f MWp uncalibrated ceiling)",
        out_dir, len(merged), merged.n_onset_buildings.sum(), merged.onset_roof_area_m2.sum(),
        merged.onset_mwp.sum(),
    )

    if regions_path and Path(regions_path).exists():
        regions = gpd.read_parquet(regions_path)
        centroids = gpd.GeoDataFrame(
            merged[["cell", *sum_cols]],
            geometry=gpd.points_from_xy(merged.lon_center, merged.lat_center), crs="EPSG:4326",
        )
        j = gpd.sjoin(centroids, regions[["id", "name", "geometry"]], how="inner", predicate="within")
        reg_agg = j.groupby(["id", "name"], as_index=False)[sum_cols].sum()
        reg_agg = reg_agg.merge(regions[["id", "name", "geometry"]], on=["id", "name"])
        reg_agg = gpd.GeoDataFrame(reg_agg, geometry="geometry", crs="EPSG:4326")
        reg_agg.to_parquet(out_dir / "sppi_growth_regions.geoparquet")
        reg_agg.drop(columns="geometry").to_csv(out_dir / "sppi_growth_regions.csv", index=False)
        top = reg_agg.sort_values("onset_mwp", ascending=False)[
            ["name", "n_onset_buildings", "onset_roof_area_m2", "onset_mwp"]
        ].head(10)
        log.info("Top regions by SPPI-onset uncalibrated MWp:\n%s", top.to_string(index=False))
    else:
        log.warning("No regions file at %s; skipping region-level aggregate", regions_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sppi-dir", type=Path, default=Path("data/sppi_growth/pakistan"))
    parser.add_argument(
        "--grid", type=Path, default=Path("data/predictions/pakistan/density/grid.geoparquet")
    )
    parser.add_argument("--regions", type=Path, default=Path("data/labels/pakistan_regions.parquet"))
    parser.add_argument(
        "--out-dir", type=Path, default=Path("data/predictions/pakistan/density/growth")
    )
    args = parser.parse_args()
    run(args.sppi_dir, args.grid, args.regions, args.out_dir)
