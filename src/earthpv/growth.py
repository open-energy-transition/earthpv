"""Two-epoch PV growth from the evidence atlas's own instruments.

The first growth map (scripts/pv_growth_map.py, 2026-08-06) diffed two `density` runs
made with DIFFERENT segmentation checkpoints (current: v3_combined_india, pre-boom: an
undocumented pk16085 variant -- both since deleted from disk), with the pre-2026-08-11
pooled calibration and the old 0.07 land constant on the pre-boom side, and with no
roofclf half at all -- so it measured the >= 400 m2 segmentation floor only, through an
instrument that changed between the two epochs. This module supersedes that product.

Here both epochs go through ONE identical instrument pair -- the same segmentation
checkpoint for both epochs' inference, the same placement-split calibration YAML for
both `density` runs, and the same fitted roofclf model + coverage-ratio/area-recall
tables scoring both epochs' composites -- and the combination per cell mirrors
`atlas.build_evidence_atlas`'s Best-estimate composition, minus its hand-mapped OSM
component (OSM install dates don't exist, so mapped features cannot be assigned to an
epoch; both epochs' model components are deduplicated against the SAME present-day OSM
pull instead, which cancels in the diff):

- ground-mount: segmentation `est_mwp_rc_ground`, both epochs;
- rooftop, inside the density-calibrated domain (`density.CALIBRATED_BLDG_DENSITY_KM2`
  over the shared national cell-density table): roofclf's >= 400 m2 rooftop replacement,
  both epochs;
- rooftop, outside that domain: segmentation `est_mwp_rc_roof`, both epochs;
- sub-400 m2: roofclf's central estimate, both epochs.

**What a pre-boom roofclf/segmentation level means here.** Every calibration in this
project (candidate precision, coverage ratio, area recall, the roofclf fit itself) is
measured against current-epoch mapping and imagery. Applying it to the pre-boom epoch
assumes those calibrations transfer across epochs; that is untestable without pre-boom
ground truth and is exactly why this module publishes epoch DIFFS of a fixed instrument,
never a standalone historical capacity level. The systematic part of any calibration
error is shared by both epochs and largely cancels in the difference; what does not
cancel is documented in the summary's `caveats`.

**Negative per-cell deltas are kept, not clamped.** A cell where the instrument reads
lower in the current epoch than pre-boom is instrument noise (or, rarely, a real
decommissioning); clamping at zero would bias the national total up. The summary reports
the negative mass separately so its size is visible.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger("growth")

# Column pulled from each epoch's segmentation density grid, per placement.
SEG_COLS = ["est_mwp_rc", "est_mwp_rc_roof", "est_mwp_rc_ground"]


def _roofclf_cell_mwp(path: Path, kwp_col: str) -> pd.Series:
    """Per-cell MWp sums from a sub400/ge400 incremental-buildings parquet."""
    df = pd.read_parquet(path, columns=["cell", kwp_col])
    return df.groupby("cell")[kwp_col].sum() / 1000.0


def _domain_cells(cell_density_path: Path) -> set[str]:
    """The density-calibrated domain, derived exactly as the capacity functions do:
    `density.CALIBRATED_BLDG_DENSITY_KM2` over the shared national cell-density table
    (NOT from which cells happen to have flagged buildings -- a domain cell where
    roofclf flags nothing in either epoch is a genuine roofclf zero, not a
    fall-back-to-segmentation cell)."""
    from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2

    cd = pd.read_parquet(cell_density_path)
    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    dens_col = "density" if "density" in cd.columns else "bldg_density_km2"
    return set(cd.loc[(cd[dens_col] >= lo) & (cd[dens_col] <= hi), "cell"])


def build_growth(
    aoi: str,
    current_pred_dir: Path,
    preboom_pred_dir: Path,
    current_roofclf_density: Path,
    preboom_roofclf_density: Path,
    out_dir: Path,
    cell_density_path: Path = Path("data/roofclf/national_cell_density.parquet"),
    sppi_growth_grid: Path | None = None,
    current_label: str = "current",
    preboom_label: str = "pre-boom (2021-10..2022-01)",
) -> Path:
    """Combine both epochs' segmentation density grids and roofclf capacity outputs
    into a per-cell growth grid, region aggregates, and a summary JSON. See the module
    docstring for the composition and its assumptions."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cur = gpd.read_parquet(Path(current_pred_dir) / aoi / "density" / "grid.geoparquet")
    pre_path = Path(preboom_pred_dir) / aoi / "density" / "grid.geoparquet"
    if pre_path.exists():
        pre = gpd.read_parquet(pre_path)
    else:  # older density runs on a secondary pred dir only kept the CSV
        pre = pd.read_csv(Path(preboom_pred_dir) / aoi / "density" / "grid.csv")
    pre = pd.DataFrame(pre.drop(columns="geometry", errors="ignore"))

    grid = cur.merge(
        pre[["cell", *SEG_COLS]], on="cell", how="left", suffixes=("", "_preboom"),
    )
    # A cell with no pre-boom row never got a composite_1 / pre-boom inference: its
    # delta is NOT MEASURABLE there, which is different from zero pre-boom capacity.
    grid["preboom_covered"] = grid["est_mwp_rc_preboom"].notna()
    n_uncovered = int((~grid.preboom_covered).sum())
    if n_uncovered:
        log.warning(
            "%d/%d cells have no pre-boom epoch coverage -- excluded from every delta "
            "(their current-epoch capacity is reported but not differenced)",
            n_uncovered, len(grid),
        )

    # roofclf halves, per cell, both epochs. Missing cell = flagged nothing there = 0.
    sub_cur = _roofclf_cell_mwp(
        Path(current_roofclf_density) / "sub400_central_incremental_buildings.parquet",
        "est_kwp_sub400")
    sub_pre = _roofclf_cell_mwp(
        Path(preboom_roofclf_density) / "sub400_central_incremental_buildings.parquet",
        "est_kwp_sub400")
    ge4_cur = _roofclf_cell_mwp(
        Path(current_roofclf_density) / "ge400_roof_incremental_buildings.parquet",
        "est_kwp_ge400_roof")
    ge4_pre = _roofclf_cell_mwp(
        Path(preboom_roofclf_density) / "ge400_roof_incremental_buildings.parquet",
        "est_kwp_ge400_roof")
    for name, s in [("mwp_sub400_cur", sub_cur), ("mwp_sub400_pre", sub_pre),
                    ("mwp_ge400_roofclf_cur", ge4_cur), ("mwp_ge400_roofclf_pre", ge4_pre)]:
        grid[name] = grid["cell"].map(s).fillna(0.0)

    domain = _domain_cells(Path(cell_density_path))
    grid["in_domain"] = grid["cell"].isin(domain)
    grid["roof_source"] = np.where(grid.in_domain, "roofclf", "segmentation")

    covered = grid.preboom_covered
    fill = lambda c: grid[c].fillna(0.0)  # noqa: E731

    # Component levels per epoch, composed exactly as the evidence atlas does (minus OSM).
    grid["mwp_ground_cur"] = fill("est_mwp_rc_ground")
    grid["mwp_ground_pre"] = fill("est_mwp_rc_ground_preboom")
    grid["mwp_roof_cur"] = np.where(
        grid.in_domain, grid.mwp_ge400_roofclf_cur, fill("est_mwp_rc_roof"))
    grid["mwp_roof_pre"] = np.where(
        grid.in_domain, grid.mwp_ge400_roofclf_pre, fill("est_mwp_rc_roof_preboom"))
    grid["mwp_total_cur"] = grid.mwp_ground_cur + grid.mwp_roof_cur + grid.mwp_sub400_cur
    grid["mwp_total_pre"] = grid.mwp_ground_pre + grid.mwp_roof_pre + grid.mwp_sub400_pre

    for comp in ["ground", "roof", "sub400", "total"]:
        cur_c, pre_c = f"mwp_{comp}_cur", f"mwp_{comp}_pre"
        grid[f"delta_mwp_{comp}"] = np.where(covered, grid[cur_c] - grid[pre_c], np.nan)
    # Raw segmentation-only delta, for continuity with the superseded growth map.
    grid["delta_est_mwp_rc"] = np.where(
        covered, fill("est_mwp_rc") - fill("est_mwp_rc_preboom"), np.nan)

    if sppi_growth_grid and Path(sppi_growth_grid).exists():
        sppi = gpd.read_parquet(sppi_growth_grid).drop(columns="geometry")
        keep = [c for c in ["n_onset_buildings", "onset_roof_area_m2", "onset_mwp"]
                if c in sppi.columns]
        grid = grid.merge(sppi[["cell", *keep]], on="cell", how="left")
        grid[keep] = grid[keep].fillna(0.0)

    grid.to_parquet(out_dir / "growth_grid.geoparquet")
    grid.drop(columns="geometry").to_csv(out_dir / "growth_grid.csv", index=False)

    # Region aggregates: assign each cell by centroid to every region level present.
    regions_path = Path(current_pred_dir) / aoi / "density" / "regions.geoparquet"
    region_frames = []
    if regions_path.exists():
        regions = gpd.read_parquet(regions_path)
        cent = grid[["cell", "geometry"]].copy()
        cent["geometry"] = cent.geometry.representative_point()
        num_cols = [c for c in grid.columns if c.startswith(("mwp_", "delta_"))
                    or c in ("n_onset_buildings", "onset_roof_area_m2", "onset_mwp")]
        for level, rl in regions.groupby(regions.get("level", pd.Series("region", index=regions.index))):
            joined = gpd.sjoin(
                cent.set_geometry("geometry"), rl[["region_id", "name", "geometry"]],
                how="left", predicate="within",
            )[["cell", "region_id", "name"]]
            agg = (grid.drop(columns="geometry").merge(joined, on="cell")
                   .groupby(["region_id", "name"], as_index=False)[num_cols].sum(min_count=1))
            agg["level"] = level
            agg = rl[["region_id", "geometry"]].merge(agg, on="region_id")
            region_frames.append(agg)
    if region_frames:
        greg = pd.concat(region_frames, ignore_index=True)
        greg = gpd.GeoDataFrame(greg, geometry="geometry", crs=regions.crs)
        greg.to_parquet(out_dir / "growth_regions.geoparquet")
        greg.drop(columns="geometry").to_csv(out_dir / "growth_regions.csv", index=False)
        greg.to_file(out_dir / "growth_regions.geojson", driver="GeoJSON")

    def _tot(col: str) -> float:
        return round(float(grid.loc[covered, col].sum()), 1)

    deltas = {c: _tot(f"delta_mwp_{c}") for c in ["ground", "roof", "sub400", "total"]}
    summary = {
        "aoi": aoi,
        "method": "growth.build_growth",
        "epochs": {"current": current_label, "preboom": preboom_label},
        "inputs": {
            "current_pred_dir": str(current_pred_dir),
            "preboom_pred_dir": str(preboom_pred_dir),
            "current_roofclf_density": str(current_roofclf_density),
            "preboom_roofclf_density": str(preboom_roofclf_density),
            "cell_density_path": str(cell_density_path),
        },
        "n_cells": int(len(grid)),
        "n_cells_preboom_covered": int(covered.sum()),
        "n_domain_cells": int(grid.in_domain.sum()),
        "mwp_current": {c: _tot(f"mwp_{c}_cur") for c in ["ground", "roof", "sub400", "total"]},
        "mwp_preboom": {c: _tot(f"mwp_{c}_pre") for c in ["ground", "roof", "sub400", "total"]},
        "delta_mwp": deltas,
        "delta_mwp_negative_cell_mass": round(float(
            grid.loc[covered, "delta_mwp_total"].clip(upper=0).sum()), 1),
        "delta_est_mwp_rc_segmentation_only": _tot("delta_est_mwp_rc"),
        "caveats": [
            "Every calibration (candidate precision, coverage ratio, area recall, the "
            "roofclf fit) is measured on current-epoch mapping/imagery and assumed to "
            "transfer to the pre-boom epoch; only the DIFF of the fixed instrument is "
            "meaningful, never the standalone pre-boom level.",
            "Hand-mapped OSM capacity is excluded from both epochs (no install dates); "
            "both epochs' components are deduplicated against the same present-day OSM "
            "pull, so the dedup cancels in the diff.",
            "OSM geometry replacement in postprocess uses present-day footprints in both "
            "epochs: a plant that physically EXPANDED since the pre-boom epoch gets its "
            "full present footprint in both, biasing its delta toward zero "
            "(conservative).",
            "Both epochs' composites were built before the 2026-07-26 imagery fallback "
            "baseline-offset fix; per-cell fallback-scene usage differs between epochs, "
            "an unquantified radiometric confound shared with the published atlas's own "
            "composites.",
            "VIDA building footprints are a single present-day snapshot; a building "
            "constructed after the pre-boom epoch still exists in that epoch's building "
            "table with (correctly) no PV signal on bare ground.",
            "No composed credible interval yet: coverage-ratio/kWp draws are shared "
            "between epochs and mostly cancel in the diff, but the residual is not "
            "priced. Point deltas only.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    log.info("Growth: current %.1f / pre-boom %.1f -> delta %.1f MWp "
             "(ground %.1f, roof %.1f, sub400 %.1f) over %d/%d covered cells -> %s",
             summary["mwp_current"]["total"], summary["mwp_preboom"]["total"],
             deltas["total"], deltas["ground"], deltas["roof"], deltas["sub400"],
             summary["n_cells_preboom_covered"], summary["n_cells"], out_dir)
    return out_dir
