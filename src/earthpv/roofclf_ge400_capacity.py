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
    quadrat_profile_path: Path = Path("results/calibration_quadrats.csv"),
    n_density_bands: int | None = None,
    n_coverage_boot: int | None = None,
    recall_correct: bool = True,
) -> tuple[gpd.GeoDataFrame, dict]:
    """roofclf-scored, coverage-ratio-weighted capacity for >= 400 m2 rooftop buildings,
    restricted to the density-matched domain (same ~92 cells `sub400_capacity` uses).

    **Size-binned coverage ratio, not a flat one (2026-08-09).** The capacity multiplier
    is looked up per building from `sub400_capacity.coverage_ratio_by_size`/
    `apply_size_coverage_ratio` -- the SAME calibration `sub400_capacity.py`'s own
    sub-400 m2 functions use, since that function is fit once across the full size range
    the calibration quadrats cover and the ratio was measured continuous across the
    400 m2 boundary (no separate >= 400 m2 refit). Its predecessor
    (`density_regime_coverage_ratio_ge400`, one flat number for every >= 400 m2 building
    regardless of how much bigger than 400 m2 it actually was) is retired; see
    `coverage_ratio_by_size`'s docstring for the measured size trend.

    **Also density-stratified, same day.** As with `sub400_capacity.py`'s own two
    functions, the size-binned fit is now itself fit separately per building-density
    stratum (`sub400_capacity.coverage_ratio_by_size_and_density`/
    `apply_stratified_coverage_ratio`) and looked up by each building's OWN cell's
    density, not a single pooled fit applied uniformly across the whole domain.

    **Area-recall corrected (2026-08-15, `recall_correct`, default True).** The coverage
    ratio prices the PV on roofs roofclf FLAGGED; dividing by
    `sub400_capacity.area_recall_by_size_and_density` extends that to the roofs it missed,
    the same Horvitz-Thompson step `density.py` has always applied to segmentation
    candidates. The correction is small here and large below 400 m2, which is itself the
    expected shape: measured on the trusted quadrats' own >= 400 m2 buildings, roofclf's
    area recall is 0.982, against 0.808 for sub-400 m2 -- this instrument was chosen for
    this population precisely because it barely misses at this size. Reporting it anyway
    matters for the atlas's interval, since the same quadrat resample now moves this
    component and the sub-400 m2 one together.

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
        DEFAULT_COVERAGE_N_BOOT, DEFAULT_N_DENSITY_STRATA, DEFAULT_RATIO_HI, DEFAULT_RATIO_LO,
        apply_stratified_area_recall, apply_stratified_coverage_ratio,
        area_recall_by_size_and_density, coverage_ratio_by_size_and_density,
        coverage_ratio_bootstrap_factors,
        national_cell_domain, parcel_label_composition, quadrat_building_density_km2,
        select_calibrated_quadrats,
    )

    ratio_lo = DEFAULT_RATIO_LO if ratio_lo is None else ratio_lo
    ratio_hi = DEFAULT_RATIO_HI if ratio_hi is None else ratio_hi
    n_density_bands = DEFAULT_N_DENSITY_STRATA if n_density_bands is None else n_density_bands

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)
    quadrat_density = quadrat_building_density_km2(quadrat_profile_path, quadrats)
    stratified = coverage_ratio_by_size_and_density(
        buildings_path, quadrats, threshold, quadrat_density, n_density_bands=n_density_bands
    )
    recall_stratified = area_recall_by_size_and_density(
        buildings_path, quadrats, threshold, quadrat_density, n_density_bands=n_density_bands
    ) if recall_correct else None

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
    if not flagged.empty:
        cell_density_lookup = all_cells.set_index("cell")["density"]
        flagged_cell_density = flagged["cell"].map(cell_density_lookup).to_numpy(float)
        flagged["coverage_ratio"] = apply_stratified_coverage_ratio(
            flagged["roof_area_m2"].to_numpy(float), flagged_cell_density, stratified
        )
        flagged["area_recall"] = (
            apply_stratified_area_recall(
                flagged["roof_area_m2"].to_numpy(float), flagged_cell_density, recall_stratified
            ) if recall_correct else np.ones(len(flagged))
        )
        flagged["est_kwp_ge400_roof"] = (
            flagged["roof_area_m2"].to_numpy(float)
            * DEFAULT_KWP_PER_M2_MODULE
            * flagged["coverage_ratio"].to_numpy()
            / flagged["area_recall"].to_numpy()
        )
        mean_coverage_ratio = float(
            np.average(flagged["coverage_ratio"], weights=flagged["roof_area_m2"])
        )
        # Capacity-weighted: the factor this component's published total was divided by.
        weighted = flagged["roof_area_m2"] * flagged["coverage_ratio"]
        effective_area_recall = float(weighted.sum() / (weighted / flagged["area_recall"]).sum())
        cov_boot = coverage_ratio_bootstrap_factors(
            buildings_path, quadrats, threshold, quadrat_density, stratified,
            flagged["roof_area_m2"].to_numpy(float), flagged_cell_density,
            n_density_bands=n_density_bands,
            n_boot=DEFAULT_COVERAGE_N_BOOT if n_coverage_boot is None else n_coverage_boot,
            recall_stratified=recall_stratified,
        )
    else:
        flagged["coverage_ratio"] = np.array([])
        flagged["area_recall"] = np.array([])
        flagged["est_kwp_ge400_roof"] = np.array([])
        mean_coverage_ratio = float("nan")
        effective_area_recall = float("nan")
        cov_boot = {"n_boot": 0, "factors": [], "factor_ci90": None}
    total_mwp = float(flagged["est_kwp_ge400_roof"].sum()) / 1000.0 if not flagged.empty else 0.0

    summary = {
        "method": "domain_restricted_ge400_roof_capacity",
        "calibration_quadrats": quadrats,
        # See `sub400_capacity.parcel_label_composition`: None under the roof-only label,
        # and under the parcel label the share of this "rooftop" figure that is in fact
        # ground-tagged PV standing in the building's yard.
        "parcel_label_composition": parcel_label_composition(buildings_path, quadrats, threshold),
        "calibration_coverage_ratio_by_size_and_density": stratified,
        "calibration_coverage_ratio_area_weighted_mean": (
            round(mean_coverage_ratio, 4) if mean_coverage_ratio == mean_coverage_ratio else None
        ),
        "recall_correction_applied": bool(recall_correct),
        "calibration_area_recall_by_size_and_density": recall_stratified,
        "calibration_effective_area_recall": (
            round(effective_area_recall, 4)
            if effective_area_recall == effective_area_recall else None
        ),
        # Quadrat-resampling uncertainty on this component, as dimensionless multiplicative
        # factors (`sub400_capacity.coverage_ratio_bootstrap_factors`). Replicate b here is
        # the SAME resampled quadrat set as replicate b in the sub-400 m2 summaries, by
        # shared seed -- `atlas.build_evidence_atlas` relies on that to add correlated
        # components without understating the total's interval.
        "coverage_ratio_bootstrap": cov_boot,
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
