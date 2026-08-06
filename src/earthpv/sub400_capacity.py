"""Sub-400 m2 capacity: fraction head + roofclf, density-stratified, kept OUT of `density.py`.

This is a deliberately separate, experimental product -- NOT the segmentation-based
atlas (`density.py`), and NOT merged into it. Two things forced that separation:

- Promoting the fraction head as `density.py`'s default expected-area instrument
  (2026-07-30) broke `earthpv check-density` when forced through the current candidate
  population (a disproportionate 46% collapse in roof-intersected candidate area vs.
  29% overall -- a `density.py`/`postprocess.py` aggregation issue, not something this
  module can fix). The segmentation-based atlas was restored and stays the default.
- roofclf's national capacity fold-in was separately rejected (see `roofclf_capacity.py`):
  a flat LOQO precision (0.50, measured at ~10.8% PV prevalence across 9 quadrats) gives
  18-37 GWp nationally, 3.5-8x the country's entire segmentation-based total, because PPV
  at a fixed threshold falls as true prevalence falls and the calibration quadrats are not
  representative of national prevalence.

The second failure is exactly what this module measures and partially corrects. Per-quadrat
precision at the deployment threshold is NOT flat -- it ranges 0.30-0.81 across the 8
quadrats (see `select_calibrated_quadrats`), and it is not simply "higher density is
better": quadrats where roofclf's raw predicted rate roughly matches the true rate
(rate_ratio within 2x either direction) sit in a *middle* density band (12-19% base rate),
with sparser quadrats (<10%) overestimating 2x+ and the one much-denser residential quadrat
(lahore, 30%) underestimating instead. Restricting to that middle band lifts pooled
precision from 0.499 (all 8) to 0.549 (the 3-quadrat band) at comparable recall -- a real,
measured improvement, not a guess -- but it is still an extrapolation from three quadrats to
81M national buildings, not a national measurement. Report it as such.

No reliable *national* proxy for "which cells resemble the calibrated density band" was
found to exist: tried and rejected here (see `docs/issues/` write-up) are (a) existing
segmentation-detected candidate density per cell -- anti-correlated with true small-PV base
rate, since large-PV (industrial) and small-PV (residential) adoption are different
populations, and (b) roofclf's own raw predicted rate per cell -- does not separate
calibrated from miscalibrated quadrats either (multan/sundar's predicted rate sits inside the
"good" band despite 2x+ true miscalibration).

**Measured 2026-07-30: the precision correction alone does not fix national deployment.**
Applying the density-regime precision (0.5495) to the SAME unrestricted 2,276,331
incrementally-flagged buildings used by the rejected flat-0.50 attempt gives 40,879 MWp --
*worse* than the original 37,197 MWp, because 0.5495 > 0.5. The precision fix and the
volume problem are separate failures; fixing one does not touch the other. The volume
problem needs restricting WHICH buildings count, which needs a national proxy -- and per
the paragraph above, none was found to exist. The only defensible move left is the
building-density domain restriction already used for roofclf's feature space (rejected on
its own in `docs/issues/roofclf-national-deployment-and-temporal-features.md` at flat 0.50
precision: 11,817 MWp, still implausible, plus a 13.4%-of-buildings/49%-of-area confound
where "incremental" buildings were already >=400 m2, i.e. not sub-400 at all). Combining
all three corrections -- domain restriction (93 cells matching the 8 quadrats'
737-4750 bldg/km2 range) + the >=400 m2 contamination filter + the density-regime precision
(0.5495 instead of 0.50) -- gives **6,628 MWp**, the same order of magnitude as the
country's entire existing segmentation-based total (5,078 MWp). That is `domain_restricted_
capacity` below. It is a real result, but it describes only those 93 cells (2.1% of
national cells, 19.1% of national buildings) -- extrapolating it to the other 97.9% of the
country (naive rate x 1/0.021 ~ 315 GWp) is exactly the failure mode this whole module
exists to avoid, and must not be done.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Symmetric log-scale band: a quadrat is "reasonably calibrated" if roofclf's raw
# predicted rate is within 2x of the true (labelled) rate in either direction. Chosen
# because it is a direct measure of calibration quality (not a proxy like base_rate
# itself), computed once from data, not tuned to hit a target number.
DEFAULT_RATIO_LO = 0.5
DEFAULT_RATIO_HI = 2.0
# mardan is excluded on its own documented grounds (worst fold, AUC 0.743, a distinct
# and already-diagnosed problem unrelated to density -- see CLAUDE.md); it also fails
# the ratio band on its own (0.312), so this is belt-and-suspenders, not load-bearing.
DEFAULT_EXCLUDE = ("mardan",)


def select_calibrated_quadrats(
    folds_path: Path,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
) -> tuple[list[str], pd.DataFrame]:
    """Quadrats whose roofclf rate_ratio (predicted/true adoption rate) falls in
    [ratio_lo, ratio_hi] -- i.e. where the classifier's raw predicted rate is not wildly
    off from ground truth. Returns `(quadrat_names, folds_subset_df)` for logging/audit.
    """
    folds = pd.read_csv(folds_path).set_index("quadrat")
    folds = folds[~folds.index.isin(exclude)]
    sel = folds[(folds.rate_ratio >= ratio_lo) & (folds.rate_ratio <= ratio_hi)]
    if sel.empty:
        raise ValueError(
            f"No quadrat has rate_ratio in [{ratio_lo}, {ratio_hi}] -- "
            f"loosen the band or check {folds_path}"
        )
    log.info(
        "Density-calibrated quadrats (rate_ratio in [%.2f, %.2f]): %s (base_rate %.3f-%.3f)",
        ratio_lo, ratio_hi, sel.index.tolist(), sel.base_rate.min(), sel.base_rate.max(),
    )
    excluded_lo = folds[folds.rate_ratio < ratio_lo]
    excluded_hi = folds[folds.rate_ratio > ratio_hi]
    if not excluded_lo.empty:
        log.info(
            "Excluded (underestimate, ratio<%.2f): %s -- roofclf UNDER-predicts here, so "
            "including them would only make the correction more conservative, but they "
            "are dropped for symmetry with the overestimate side, not for any other reason",
            ratio_lo, excluded_lo.index.tolist(),
        )
    if not excluded_hi.empty:
        log.info(
            "Excluded (overestimate, ratio>%.2f): %s -- these are the low-true-density "
            "quadrats (base_rate %.3f-%.3f) that drove the original flat-precision "
            "national number to 18-37 GWp; excluding them is the whole point of this module",
            ratio_hi, excluded_hi.index.tolist(),
            excluded_hi.base_rate.min(), excluded_hi.base_rate.max(),
        )
    return sel.index.tolist(), sel


def density_regime_precision(
    buildings_path: Path, quadrats: list[str], threshold: float
) -> dict:
    """Pooled precision/recall of roofclf's leave-one-quadrat-out OOF predictions
    (`p_oof`/`has_pv` in `roofclf.evaluate()`'s per-building table), restricted to
    `quadrats`, at `threshold`. This is a real held-out measurement (each quadrat's
    `p_oof` was produced by a model that never saw that quadrat), not a training-set
    fit -- the same LOQO discipline `roofclf.py` uses everywhere else.
    """
    df = gpd.read_parquet(buildings_path)
    sub = df[df.quadrat.isin(quadrats)]
    if sub.empty:
        raise ValueError(f"None of {quadrats} found in {buildings_path}")
    pred = sub.p_oof >= threshold
    tp = int((pred & (sub.has_pv == 1)).sum())
    fp = int((pred & (sub.has_pv == 0)).sum())
    fn = int((~pred & (sub.has_pv == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    result = {
        "quadrats": quadrats,
        "threshold": threshold,
        "n": int(len(sub)),
        "n_flagged": int(pred.sum()),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }
    log.info("Density-regime precision: %s", result)
    return result


def national_incremental_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    threshold: float,
    max_distance_m: float = 30.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The density-stratified version of `roofclf_capacity.incremental_capacity`: same
    dedup-vs-segmentation mechanics, but weighted by the density-regime-restricted
    precision instead of the flat all-quadrat LOQO number. Returns
    `(incremental_buildings, summary)`; `summary` carries both the calibration-selection
    diagnostics and the capacity result so a caller never has to re-derive the precision
    used to produce a given number.
    """
    from earthpv.roofclf_capacity import incremental_capacity

    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)
    precision_info = density_regime_precision(buildings_path, quadrats, threshold)

    incremental, cap_summary = incremental_capacity(
        roofclf_dir=roofclf_dir,
        candidates_path=candidates_path,
        threshold=threshold,
        precision=precision_info["precision"],
        max_distance_m=max_distance_m,
    )
    summary = {
        "method": "density_regime_restricted",
        "calibration_quadrats": quadrats,
        "calibration_base_rate_range": [
            round(float(folds_subset.base_rate.min()), 4),
            round(float(folds_subset.base_rate.max()), 4),
        ],
        "calibration_precision_n": precision_info["n"],
        "calibration_precision_n_flagged": precision_info["n_flagged"],
        "calibration_recall": precision_info["recall"],
        **cap_summary,
        "caveat": (
            "Extrapolated nationally from 3 calibration quadrats at a flat precision; "
            "no reliable per-cell national proxy for local PV density was found (tested: "
            "existing candidate density anti-correlates, roofclf's own predicted rate "
            "does not separate calibration regimes). Not validated at national scale, "
            "not merged into density.py's headline total_est_mwp_rc."
        ),
    }
    return incremental, summary


def national_cell_domain(cell_density_path: Path) -> set[str]:
    """Cells whose building density falls in the calibration quadrats' range
    (`density.CALIBRATED_BLDG_DENSITY_KM2`) -- the same range `density.py`'s
    segmentation-only completeness flag reads, reused here for the opposite purpose:
    restricting WHERE this module's national deployment is allowed to count buildings at
    all, not just flagging confidence after the fact.
    """
    from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2

    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    cells = pd.read_parquet(cell_density_path)
    in_range = cells[(cells.density >= lo) & (cells.density <= hi)]
    return set(in_range.cell)


def domain_restricted_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    cell_density_path: Path,
    threshold: float,
    max_distance_m: float = 30.0,
    contamination_max_m2: float = 400.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    osm_solar_path: Path | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The module's actually-recommended output (see module docstring's 2026-07-30 note):
    combines three corrections, each individually insufficient on its own when measured:

    1. **Domain restriction** -- only buildings in cells whose building density falls in
       the calibration quadrats' range count at all (`national_cell_domain`). This is the
       one necessary handle on WHICH buildings this module may speak about; no other
       tested proxy (existing candidate density, roofclf's own raw rate) restricts the
       population defensibly -- see module docstring.
    2. **Contamination filter** -- buildings whose own footprint is already
       >= `contamination_max_m2` are dropped from "incremental": they were never sub-400
       m2 to begin with, they are just outside `new_lead_mask`'s 30 m matching radius of
       an existing segmentation candidate (a geometry-matching gap, not sub-floor signal).
    3. **Density-regime precision** -- `density_regime_precision`'s measured value (from
       the quadrats whose rate_ratio is within `[ratio_lo, ratio_hi]`), not the flat LOQO
       number, which the module docstring shows does not help on its own.

    `osm_solar_path`, when given, adds a FOURTH exclusion: buildings within `max_distance_m`
    of an already hand-mapped OSM solar feature. Without it, "incremental" only means "no
    nearby *segmentation* candidate" -- a roofclf-flagged building that OSM already mapped
    but segmentation missed entirely (no candidate anywhere near it) passes straight
    through, and the evidence atlas counts it twice: once as `osm_mwp_unmatched`, once here.
    Measured 2026-08-06 against the then-current outputs: 2.8% of buildings / 3.3% of MWp
    in this population sat within 30 m of an OSM feature -- real, not hypothetical. Optional
    (not required) only because some callers may not have a national OSM pull handy; every
    call that feeds the evidence atlas should pass it.

    Returns `(incremental_buildings, summary)`. `summary["scope"]` states exactly what
    population this describes -- READ IT before quoting the MWp number. It is a LOCAL
    figure (the in-domain cells only, 93 of 4,473 nationally as measured 2026-07-30) and
    must NOT be divided by the domain's share of national cells/buildings to infer a
    country total -- doing so was the exact failure this module exists to avoid.
    """
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE
    from earthpv.export import new_lead_mask

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    n_buildings_in_domain = int(
        all_cells.loc[all_cells.cell.isin(in_domain_cells), "n_buildings"].sum()
    )
    n_buildings_national = int(all_cells.n_buildings.sum())
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)
    precision_info = density_regime_precision(buildings_path, quadrats, threshold)

    # Read only the ~93 in-domain per-cell parquets, not all 4,473 -- files are named
    # <cell>.parquet by `score_buildings_national`, so this is a filename filter, not a
    # post-hoc one. `load_flagged_buildings` (roofclf_capacity.py) reads everything and
    # would be ~50x slower here for no benefit, since the domain restriction throws away
    # all but ~2% of cells anyway.
    parts = []
    for cell in sorted(in_domain_cells):
        p = Path(roofclf_dir) / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns:
            continue
        f = d[d.p_roofclf >= threshold]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        if parts else gpd.GeoDataFrame(columns=["cell", "geometry", "roof_area_m2", "p_roofclf"], crs="EPSG:4326")
    )
    log.info(
        "Domain-restricted: %d/%d cells, %d flagged buildings in-domain",
        len(in_domain_cells), len(all_cells), len(flagged),
    )

    cands = gpd.read_parquet(candidates_path)
    is_new = new_lead_mask(flagged, cands, min_distance_m=max_distance_m)
    n_near_osm = 0
    if osm_solar_path is not None:
        osm = gpd.read_parquet(osm_solar_path)
        is_new_osm = new_lead_mask(flagged, osm, min_distance_m=max_distance_m)
        n_near_osm = int((is_new & ~is_new_osm).sum())
        is_new = is_new & is_new_osm
    incremental_raw = flagged[is_new].reset_index(drop=True)

    over = incremental_raw.roof_area_m2 >= contamination_max_m2
    n_contaminated = int(over.sum())
    contaminated_area_m2 = float(incremental_raw.loc[over, "roof_area_m2"].sum())
    incremental = incremental_raw[~over].reset_index(drop=True)

    precision = precision_info["precision"]
    total_area_m2 = float(incremental.roof_area_m2.sum())
    incremental = incremental.copy()
    incremental["est_kwp_sub400"] = (
        incremental.roof_area_m2.to_numpy(float) * DEFAULT_KWP_PER_M2_MODULE * precision
    )
    total_mwp = float(incremental.est_kwp_sub400.sum()) / 1000.0

    summary = {
        "method": "domain_restricted_sub400_capacity",
        "calibration_quadrats": quadrats,
        "calibration_precision": precision,
        "calibration_recall": precision_info["recall"],
        "n_domain_cells": len(in_domain_cells),
        "n_national_cells": int(len(all_cells)),
        "n_buildings_in_domain": n_buildings_in_domain,
        "n_buildings_national": n_buildings_national,
        "n_flagged_in_domain": int(len(flagged)),
        "osm_dedup_applied": osm_solar_path is not None,
        "n_excluded_near_osm": n_near_osm,
        "n_incremental_before_contamination_filter": int(len(incremental_raw)),
        "n_contaminated_excluded_ge_400m2": n_contaminated,
        "contaminated_area_m2_excluded": round(contaminated_area_m2, 1),
        "n_incremental_sub400": int(len(incremental)),
        "total_incremental_sub400_area_m2": round(total_area_m2, 1),
        "total_est_mwp_sub400_domain_restricted": round(total_mwp, 4),
        "scope": (
            f"{len(in_domain_cells)} of {len(all_cells)} national cells "
            f"({100 * len(in_domain_cells) / len(all_cells):.1f}% of cells, "
            f"{100 * n_buildings_in_domain / n_buildings_national:.1f}% of national "
            "buildings) whose building density falls in the calibration quadrats' range. "
            "NOT a national figure -- do not rescale by the domain's share of "
            "cells/buildings to estimate a country total; the other cells are mostly "
            "rural and not known to share this rate."
        ),
    }
    log.info("Domain-restricted sub-400 capacity: %s", summary)
    return incremental, summary


def domain_restricted_and_gate_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    cell_density_path: Path,
    threshold: float,
    sppi_min_precision: float = 0.5,
    max_distance_m: float = 30.0,
    contamination_max_m2: float = 400.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    osm_solar_path: Path | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The sub-400 bracket's LOW end: `domain_restricted_capacity`'s same 93-cell
    population, but requiring `p_roofclf >= threshold` AND SPPI above a pooled
    precision-targeted threshold, instead of roofclf alone.

    `docs/methods/density.md`'s "SPPI cross-validation" section measured this AND-gate
    on the domain-restricted population in prose on 2026-07-30 (496,122 -> 343,032
    flagged buildings, 6,628 -> 4,690 MWp, precision flat at ~0.55) but never saved it as
    reusable code or a pinned artifact -- this is that promotion, re-measured against
    whatever `roofclf_dir`/`candidates_path` are current rather than assumed to
    reproduce the exact prior figure. It was rejected there as *the* domain-restricted
    number (no precision gain, only lost recall) -- that verdict still holds. As a
    bracket LOW end it is being asked a different question: not "is this the best
    domain-restricted estimate" but "what does the more conservative of two measured
    detector agreements say", which is exactly what a stricter join criterion is for.

    The SPPI threshold is a single pooled fit on the SAME calibration quadrats
    `select_calibrated_quadrats` already selects (`sppi.pooled_precision_threshold`) --
    no LOQO here, since there is no national quadrat to hold out, matching how
    roofclf's own national `deployment_threshold` is one pooled constant.

    `osm_solar_path`: see `domain_restricted_capacity`'s docstring -- same fix, same
    reason (measured 2026-08-06: 3.0% of buildings / 3.8% of MWp in this population
    were within 30 m of an OSM feature before this parameter existed).
    """
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE
    from earthpv.export import new_lead_mask
    from earthpv.sppi import add_sppi, pooled_precision_threshold

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)

    bt = gpd.read_parquet(buildings_path)
    if "sppi" not in bt.columns:
        bt = add_sppi(bt)
    sppi_thresh = pooled_precision_threshold(bt, quadrats, min_precision=sppi_min_precision)

    cal = bt[bt.quadrat.isin(quadrats)]
    y = cal.has_pv.to_numpy(bool)
    roof_pred = cal.p_oof.to_numpy(float) >= threshold
    and_pred = roof_pred & (cal.sppi.to_numpy(float) >= sppi_thresh)
    tp = int((and_pred & y).sum())
    fp = int((and_pred & ~y).sum())
    and_precision = tp / (tp + fp) if (tp + fp) else float("nan")
    and_recall = tp / int(y.sum()) if y.sum() else float("nan")
    roof_tp = int((roof_pred & y).sum())
    roof_fp = int((roof_pred & ~y).sum())
    roof_only_precision = roof_tp / (roof_tp + roof_fp) if (roof_tp + roof_fp) else float("nan")
    roof_only_recall = roof_tp / int(y.sum()) if y.sum() else float("nan")

    parts = []
    for cell in sorted(in_domain_cells):
        p = Path(roofclf_dir) / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns or "sppi" not in d.columns:
            continue
        f = d[(d.p_roofclf >= threshold) & (d.sppi >= sppi_thresh)]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        if parts
        else gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    )
    log.info(
        "Domain-restricted AND-gate: %d/%d cells, %d flagged buildings in-domain "
        "(sppi_threshold=%.4f)", len(in_domain_cells), len(all_cells), len(flagged), sppi_thresh,
    )

    cands = gpd.read_parquet(candidates_path)
    is_new = new_lead_mask(flagged, cands, min_distance_m=max_distance_m)
    n_near_osm = 0
    if osm_solar_path is not None:
        osm = gpd.read_parquet(osm_solar_path)
        is_new_osm = new_lead_mask(flagged, osm, min_distance_m=max_distance_m)
        n_near_osm = int((is_new & ~is_new_osm).sum())
        is_new = is_new & is_new_osm
    incremental_raw = flagged[is_new].reset_index(drop=True)

    over = incremental_raw.roof_area_m2 >= contamination_max_m2
    n_contaminated = int(over.sum())
    contaminated_area_m2 = float(incremental_raw.loc[over, "roof_area_m2"].sum())
    incremental = incremental_raw[~over].reset_index(drop=True)

    total_area_m2 = float(incremental.roof_area_m2.sum())
    incremental = incremental.copy()
    incremental["est_kwp_sub400_and_gate"] = (
        incremental.roof_area_m2.to_numpy(float)
        * DEFAULT_KWP_PER_M2_MODULE
        * (and_precision if and_precision == and_precision else 0.0)
    )
    total_mwp = float(incremental.est_kwp_sub400_and_gate.sum()) / 1000.0

    summary = {
        "method": "domain_restricted_and_gate_sub400_capacity",
        "calibration_quadrats": quadrats,
        "roofclf_threshold": threshold,
        "sppi_threshold": round(float(sppi_thresh), 4),
        "roofclf_only_precision_same_quadrats": (
            round(roof_only_precision, 4) if roof_only_precision == roof_only_precision else None
        ),
        "roofclf_only_recall_same_quadrats": (
            round(roof_only_recall, 4) if roof_only_recall == roof_only_recall else None
        ),
        "and_gate_precision": round(and_precision, 4) if and_precision == and_precision else None,
        "and_gate_recall": round(and_recall, 4) if and_recall == and_recall else None,
        "n_domain_cells": len(in_domain_cells),
        "n_national_cells": int(len(all_cells)),
        "n_flagged_in_domain": int(len(flagged)),
        "osm_dedup_applied": osm_solar_path is not None,
        "n_excluded_near_osm": n_near_osm,
        "n_incremental_before_contamination_filter": int(len(incremental_raw)),
        "n_contaminated_excluded_ge_400m2": n_contaminated,
        "contaminated_area_m2_excluded": round(contaminated_area_m2, 1),
        "n_incremental_sub400": int(len(incremental)),
        "total_incremental_sub400_area_m2": round(total_area_m2, 1),
        "total_est_mwp_sub400_and_gate": round(total_mwp, 4),
        "scope": (
            f"{len(in_domain_cells)} of {len(all_cells)} national cells "
            f"({100 * len(in_domain_cells) / len(all_cells):.1f}% of cells) -- the SAME "
            "population `domain_restricted_capacity` uses, joined against SPPI instead "
            "of roofclf alone. NOT a national figure; see that function's docstring for "
            "why rescaling by cell/building share is invalid. This is the sub-400 "
            "bracket's LOW member -- read alongside `total_est_mwp_sub400_domain_"
            "restricted` (central, roofclf alone, same population) and the unrestricted "
            "flat-precision national fold-in (high, see roofclf_capacity.py / "
            "docs/methods/density.md)."
        ),
    }
    log.info("Domain-restricted AND-gate sub-400 capacity: %s", summary)
    return incremental, summary


def suggest_high_density_regions(
    cell_density_path: Path,
    calibration_quadrat_densities: dict[str, float],
    top_n: int = 20,
) -> pd.DataFrame:
    """Rank national 0.1-degree cells by building density (buildings/km2) as the best
    *available* proxy for "resembles a calibration quadrat" -- explicitly NOT a validated
    predictor of small-PV adoption (see module docstring: no such proxy was found). This
    only answers "where should new calibration quadrats be mapped to extend the density
    range this module depends on", which is a weaker and more honest question than "where
    is sub-400 m2 capacity concentrated".

    `calibration_quadrat_densities` should be the 8-quadrat building-density table (name
    -> buildings/km2) so the ranked cells can be read against the existing density range.
    """
    cells = pd.read_parquet(cell_density_path)
    ranked = cells.sort_values("density", ascending=False).head(top_n).reset_index(drop=True)
    lo = min(calibration_quadrat_densities.values())
    hi = max(calibration_quadrat_densities.values())
    ranked["vs_calibration_range"] = np.where(
        ranked.density < lo, "below", np.where(ranked.density > hi, "above", "within")
    )
    log.info(
        "Top %d national cells by building density (calibration range %.0f-%.0f/km2): "
        "see returned DataFrame",
        top_n, lo, hi,
    )
    return ranked
