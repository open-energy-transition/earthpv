"""Fold `roofclf.score_buildings_national`'s per-building output into capacity.

Deliberately a standalone, small module rather than a deep `density.py` rewrite: the
question this answers ("how much incremental capacity does roofclf's national scoring
add, on top of what segmentation already contributes") is well-posed without touching
density's core per-cell aggregation, and keeping it separate means a wrong assumption
here can't silently corrupt the published density pipeline. Promote into `density.py`
properly once this number has been sat with for a while, the same path glint/vegetation
took before deeper integration.

Two things this explicitly does NOT do, both on purpose:
- Does not double count. `est_mwp_rc` is already recall-corrected (1/recall inflation),
  so a second detector's contribution belongs in the recall measurement
  (`capacity_calibration.derive_table`'s `recall_cands` hook, added this session but not
  wired in here), not stacked as extra area on top. This module instead answers a
  narrower, safely-additive question: for buildings roofclf flags that segmentation's
  own candidate polygons do not cover AT ALL, what is that incremental area worth. It is
  a lower bound on what a full recall re-measurement would show, not the same number.
- Does not weight by roofclf's raw p_roofclf. The LOQO-measured precision at the
  deployment threshold (`roofclf.py`'s `evaluate()` summary) is the honest per-building
  P(real) at that operating point; used as one flat weight, not the per-row probability,
  since the latter is not independently calibrated the way `capacity_calibration`'s
  `p_real(bin)` is.

Run 2026-07-30 against the real national scoring output: 18,063 MWp incremental --
3.5-8x the country's entire existing recall-corrected total (5,078 MWp all-placement).
**Not promoted, not folded into density.** The flat LOQO precision (0.50, measured on
22,044 buildings across 9 quadrats at ~10.8% PV prevalence) does not survive being
applied to 81.76M buildings nationally at a much lower true base rate -- PPV falls as
prevalence falls even at constant sensitivity/specificity, which is exactly the
"absolute rates don't transfer across strata" problem CLAUDE.md already documents for
`rate_ratio`. A handful of cells (3 of 4,473) also show textbook logistic-saturation
behaviour (`p_roofclf` pinned at ~0.999999, a covariate far outside training range) but
they are a minor, secondary artifact -- only 4% of the flagged area -- not the reason
the headline number is unusable. See
`docs/issues/roofclf-national-deployment-and-temporal-features.md` for the full
diagnosis. This module is kept because the mechanics (dedup, area/kWp conversion) are
correct and reusable once a per-stratum precision correction exists -- only the
"flat national precision" assumption is what failed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE

log = logging.getLogger(__name__)


def load_flagged_buildings(roofclf_dir: Path, threshold: float) -> gpd.GeoDataFrame:
    """Concatenate every per-cell parquet from `score_buildings_national`, keeping only
    buildings at or above the deployment threshold. Empty-cell files (no VIDA buildings
    in that cell) are skipped rather than erroring."""
    parts = []
    for p in sorted(Path(roofclf_dir).glob("*.parquet")):
        try:
            d = gpd.read_parquet(p)
        except Exception:  # noqa: BLE001 -- an empty pd.DataFrame().to_parquet() has no geo metadata
            continue
        if d.empty or "p_roofclf" not in d.columns:
            continue
        flagged = d[d.p_roofclf >= threshold]
        if not flagged.empty:
            parts.append(flagged)
    if not parts:
        return gpd.GeoDataFrame(columns=["cell", "geometry", "roof_area_m2", "p_roofclf"], crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")


def incremental_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    threshold: float,
    precision: float,
    max_distance_m: float = 30.0,
    kwp_per_m2_module: float = DEFAULT_KWP_PER_M2_MODULE,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Buildings roofclf flags that have no existing segmentation candidate within
    `max_distance_m` -- the incremental, non-double-counted population -- with a flat
    precision weight (not roofclf's own per-row probability; see module docstring).

    `max_distance_m` matches `postprocess.NEAR_BUILDING_M`'s convention: a segmentation
    candidate genuinely covering this building should sit within a few tens of metres
    of it, not the ~100 m "same installation, roughly" threshold used for national
    recall/precision calibration elsewhere.

    Returns `(incremental_buildings, summary_dict)`.
    """
    from earthpv.export import new_lead_mask

    flagged = load_flagged_buildings(roofclf_dir, threshold)
    log.info("roofclf: %d buildings flagged at threshold %.4f", len(flagged), threshold)
    if flagged.empty:
        return flagged, {"n_flagged": 0, "n_incremental": 0, "total_est_mwp_roofclf_incremental": 0.0}

    cands = gpd.read_parquet(candidates_path)
    log.info("segmentation candidates: %d", len(cands))

    # True where a flagged building has NO existing candidate within max_distance_m --
    # i.e. segmentation missed it entirely. Reuses new_lead_mask exactly as written for
    # export.py's own leads-vs-mapped check, just with the roles swapped (candidates
    # play the "already mapped" reference here, not OSM).
    is_new = new_lead_mask(flagged, cands, min_distance_m=max_distance_m)
    incremental = flagged[is_new].reset_index(drop=True)
    log.info(
        "%d/%d flagged buildings (%.1f%%) have no segmentation candidate within %.0f m "
        "-- these are the incremental, non-double-counted population",
        len(incremental), len(flagged), 100 * len(incremental) / max(len(flagged), 1),
        max_distance_m,
    )

    incremental = incremental.copy()
    incremental["est_kwp_roofclf"] = (
        incremental["roof_area_m2"].to_numpy(float) * kwp_per_m2_module * precision
    )
    total_mwp = float(incremental["est_kwp_roofclf"].sum()) / 1000.0
    total_area = float(incremental["roof_area_m2"].sum())

    summary = {
        "threshold": threshold,
        "precision_weight": precision,
        "max_distance_m": max_distance_m,
        "kwp_per_m2_module": kwp_per_m2_module,
        "n_flagged": int(len(flagged)),
        "n_incremental": int(len(incremental)),
        "incremental_frac": round(len(incremental) / max(len(flagged), 1), 4),
        "total_incremental_roof_area_m2": round(total_area, 1),
        "total_est_mwp_roofclf_incremental": round(total_mwp, 4),
    }
    log.info("Summary: %s", summary)
    return incremental, summary
