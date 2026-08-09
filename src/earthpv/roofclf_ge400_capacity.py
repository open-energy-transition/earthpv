"""roofclf-based capacity for >= 400 m2 ROOFTOP buildings -- the rooftop-only swap
scoped 2026-08-06 and implemented 2026-08-07.

Measured basis (13 calibration quadrats, LOQO out-of-fold, on the exact same >= 400 m2
buildings): roofclf AUC 0.896 vs segmentation's own raster probability AUC 0.726-0.775
(both `seg_mean` from the undocumented `pk16085` checkpoint and `seg_mean_main` from
`v3_combined_india`, the actual production checkpoint -- see CLAUDE.md's Density stage
section, 2026-08-06/07 entries). At matched ~54% precision, per-building recall is
94.2% (roofclf) vs 19-25% (segmentation). Segmentation's known weak spot is specifically
SMALL PV, including small PV *on large buildings* (a big roof with a modest array) --
so this instrument, like every roofclf capacity number in this project, should only ever
be validated against installation-size ground truth (`pv_area_true_m2`), never
building-size alone; a >= 400 m2 building can carry an installation far smaller than its
own roof.

This REPLACES segmentation's own `est_mwp_rc_roof` for rooftop-placed capacity, it does
not add to it -- unlike `roofclf_capacity.incremental_capacity`'s dedup-and-add design.
Ground-mount is untouched: roofclf has no footprint to score there, segmentation remains
the only >= 400 m2 ground-mount instrument. The replacement is DOMAIN-RESTRICTED, same
reasoning as `sub400_capacity.py`: roofclf's precision/coverage-ratio is measured on 13
hand-picked quadrats, not a national sample, so it only replaces segmentation's rooftop
total inside the density-matched cells (`sub400_capacity.national_cell_domain`) --
outside that domain, segmentation's own `est_mwp_rc_roof` stays authoritative per cell,
since that is the only evidence-backed number available there. `atlas.py` blends the two
per cell rather than choosing one nationally.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def density_regime_coverage_ratio_ge400(
    buildings_path: Path, quadrats: list[str], threshold: float, min_area_m2: float = 400.0,
) -> dict:
    """Measured (true mapped PV area / roof area) on the >= `min_area_m2` buildings
    roofclf flags in `quadrats` -- the >= 400 m2 mirror of
    `sub400_capacity.density_regime_coverage_ratio`. Same reasoning: a flat precision
    weight assumes full-footprint coverage on every true positive, which measurably
    overstates capacity (see that function's docstring); this ratio nets out precision
    and partial coverage in one measured number.
    """
    df = gpd.read_parquet(buildings_path)
    sub = df[df.quadrat.isin(quadrats) & (df.roof_area_m2 >= min_area_m2)]
    if sub.empty:
        raise ValueError(f"None of {quadrats} found >= {min_area_m2} m2 in {buildings_path}")
    flagged = sub[sub.p_oof >= threshold]
    roof_sum = float(flagged.roof_area_m2.sum())
    true_sum = float(flagged.pv_area_true_m2.sum())
    ratio = true_sum / roof_sum if roof_sum else float("nan")
    result = {
        "quadrats": quadrats,
        "threshold": threshold,
        "min_area_m2": min_area_m2,
        "n_ge400": int(len(sub)),
        "n_flagged": int(len(flagged)),
        "flagged_roof_area_m2": round(roof_sum, 1),
        "flagged_true_pv_area_m2": round(true_sum, 1),
        "coverage_ratio": round(ratio, 4),
    }
    log.info("Density-regime >= %.0f m2 coverage ratio: %s", min_area_m2, result)
    return result


def domain_restricted_ge400_roof_capacity(
    roofclf_dir: Path,
    folds_path: Path,
    buildings_path: Path,
    cell_density_path: Path,
    threshold: float,
    osm_solar_path: Path | None = None,
    max_distance_m: float = 30.0,
    min_area_m2: float = 400.0,
    ratio_lo: float | None = None,
    ratio_hi: float | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """roofclf-scored, coverage-ratio-weighted capacity for >= 400 m2 rooftop buildings,
    restricted to the density-matched domain (same ~92 cells `sub400_capacity` uses).

    Returns `(flagged_buildings, summary)`. `flagged_buildings` carries `est_kwp_ge400_
    roof` per building (for `atlas.py`'s per-cell aggregation via
    `_join_buildings_to_grid_cells`, the same path `small_low`/`small_central` already
    use) -- NOT deduped against segmentation candidates, because this is a REPLACEMENT
    of segmentation's own rooftop estimate in-domain, not an incremental addition on top
    of it (contrast `roofclf_capacity.incremental_capacity`). It IS deduped against
    hand-mapped OSM (when `osm_solar_path` given), for the same double-counting reason
    `sub400_capacity`'s own OSM dedup exists: a building OSM already mapped should not
    also count here.
    """
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE
    from earthpv.export import new_lead_mask
    from earthpv.sub400_capacity import (
        DEFAULT_RATIO_HI, DEFAULT_RATIO_LO, national_cell_domain, select_calibrated_quadrats,
    )

    ratio_lo = DEFAULT_RATIO_LO if ratio_lo is None else ratio_lo
    ratio_hi = DEFAULT_RATIO_HI if ratio_hi is None else ratio_hi

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)
    coverage_info = density_regime_coverage_ratio_ge400(
        buildings_path, quadrats, threshold, min_area_m2
    )
    coverage_ratio = coverage_info["coverage_ratio"]

    parts = []
    for cell in sorted(in_domain_cells):
        p = Path(roofclf_dir) / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns:
            continue
        f = d[(d.p_roofclf >= threshold) & (d.roof_area_m2 >= min_area_m2)]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        if parts else gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf"], crs="EPSG:4326"
        )
    )
    log.info(
        "Domain-restricted >= %.0f m2 rooftop: %d/%d cells, %d flagged buildings in-domain",
        min_area_m2, len(in_domain_cells), len(all_cells), len(flagged),
    )

    n_near_osm = 0
    if osm_solar_path is not None and not flagged.empty:
        osm = gpd.read_parquet(osm_solar_path)
        is_new_osm = new_lead_mask(flagged, osm, min_distance_m=max_distance_m)
        n_near_osm = int((~is_new_osm).sum())
        flagged = flagged[is_new_osm].reset_index(drop=True)

    flagged = flagged.copy()
    total_area_m2 = float(flagged["roof_area_m2"].sum()) if not flagged.empty else 0.0
    flagged["est_kwp_ge400_roof"] = (
        flagged["roof_area_m2"].to_numpy(float) * DEFAULT_KWP_PER_M2_MODULE * coverage_ratio
        if not flagged.empty else np.array([])
    )
    total_mwp = float(flagged["est_kwp_ge400_roof"].sum()) / 1000.0 if not flagged.empty else 0.0

    summary = {
        "method": "domain_restricted_ge400_roof_capacity",
        "calibration_quadrats": quadrats,
        "calibration_coverage_ratio": coverage_ratio,
        "calibration_coverage_ratio_n_flagged": coverage_info["n_flagged"],
        "threshold": threshold,
        "min_area_m2": min_area_m2,
        "n_domain_cells": len(in_domain_cells),
        "n_national_cells": int(len(all_cells)),
        "n_flagged_in_domain": int(len(flagged)) + n_near_osm,
        "osm_dedup_applied": osm_solar_path is not None,
        "n_excluded_near_osm": n_near_osm,
        "n_final": int(len(flagged)),
        "total_roof_area_m2": round(total_area_m2, 1),
        "total_est_mwp_ge400_roof_domain": round(total_mwp, 4),
        "scope": (
            f"{len(in_domain_cells)} of {len(all_cells)} national cells "
            f"({100 * len(in_domain_cells) / len(all_cells):.1f}% of cells) whose "
            "building density falls in the calibration quadrats' range. REPLACES "
            "segmentation's est_mwp_rc_roof only inside these cells; outside them "
            "segmentation's own per-cell est_mwp_rc_roof stays authoritative -- see "
            "atlas.py's per-cell blend. NOT a national figure on its own."
        ),
    }
    log.info("Domain-restricted >= %.0f m2 rooftop capacity: %s", min_area_m2, summary)
    return flagged, summary
