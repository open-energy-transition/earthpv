"""Prototype: does a lower size floor for roofclf's sub-400 m2 instrument need to be
joint with local base-rate/density, or is a flat size cutoff good enough?

Background: `sub400_capacity.py`'s production capacity functions apply NO lower size
floor at all -- only an upper 400 m2 "contamination" cutoff. An earlier, untracked
diagnostic (`results/roofclf_precision_by_size.html`, no surviving source script)
recommended a flat 100-200 m2 floor from a precision/recall-by-size curve pooled across
quadrats. That is suspect for two reasons: (a) precision here is a documented lower
bound whenever validation imagery predates the current epoch -- real recent installs
score as false positives, while recall over labelled installations is not similarly
biased -- so a precision-chasing floor optimizes against a biased signal; and (b) it
ignores that local base_rate/density spans 3-30% across quadrats while roofclf's own
predicted rate is nearly flat (`rate_ratio`, no per-stratum intercept), so a flat size
cutoff cannot distinguish a small roof in a high-prevalence quadrat from the same size
in a low-prevalence one.

This script builds the INCLUSION-question analogue of `coverage_ratio_by_size_and_density`
(which already does a joint size x density fit, but for re-weighting a flagged roof's
*covered fraction*, not for deciding whether a building should be flagged at all): a
precision/recall table stratified by BOTH roof size and quadrat building-density band,
plus a fixed-breakpoint floor-cost curve run pooled and per density band, plus a
sensitivity check on `select_calibrated_quadrats`'s own 13-of-18 selection.

This is diagnostic only -- it imports read-only helpers from `sub400_capacity.py` and
does not modify it or any production capacity path.

    pixi run python scripts/roofclf_size_density_signal.py
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.sub400_capacity import (
    DEFAULT_COVERAGE_MIN_BIN_N,
    DEFAULT_EXCLUDE,
    DEFAULT_N_DENSITY_STRATA,
    DEFAULT_RATIO_LO,
    DEFAULT_RATIO_HI,
    quadrat_building_density_km2,
    select_calibrated_quadrats,
)

log = logging.getLogger(__name__)

DEFAULT_BUILDINGS = Path("data/roofclf/buildings.geoparquet")
DEFAULT_FOLDS = Path("data/roofclf/folds.csv")
DEFAULT_QUADRAT_PROFILE = Path("results/calibration_quadrats.csv")
DEFAULT_SUMMARY_JSON = Path("data/roofclf/summary.json")
DEFAULT_N_SIZE_BINS = 5
DEFAULT_FLOOR_BREAKPOINTS_M2 = tuple(range(0, 450, 50))


def load_threshold(summary_json_path: Path) -> float:
    """The deployed roofclf score threshold, read from `roof-classifier`'s own output
    rather than hardcoded -- so this script never silently drifts from whatever
    threshold production is actually using."""
    summary = json.loads(Path(summary_json_path).read_text())
    return float(summary["deployment_threshold"])


def size_bin_edges(roof_area_m2: np.ndarray, n_bins: int) -> np.ndarray:
    """Quantile edges over the FULL population (not just flagged buildings) -- both
    recall's denominator and a floor's actual target population need the unflagged rows
    too, unlike `coverage_ratio_by_size`'s bins, which are fit on flagged buildings only
    because that function only ever re-weights already-flagged area."""
    edges = np.unique(np.quantile(roof_area_m2, np.linspace(0.0, 1.0, n_bins + 1)))
    if len(edges) < 3:
        edges = np.array([roof_area_m2.min(), roof_area_m2.max()])
    edges[0], edges[-1] = -np.inf, np.inf
    return edges


def _confusion(pred: np.ndarray, has_pv: np.ndarray) -> dict:
    tp = int((pred & (has_pv == 1)).sum())
    fp = int((pred & (has_pv == 0)).sum())
    fn = int((~pred & (has_pv == 1)).sum())
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else float("nan"),
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else float("nan"),
    }


def _cell_row(d: pd.DataFrame, threshold: float, min_bin_n: int, total_flagged_area: float) -> dict:
    pred = d.p_oof.to_numpy(float) >= threshold
    has_pv = d.has_pv.to_numpy(int)
    conf = _confusion(pred, has_pv)
    n_flagged = int(pred.sum())
    n_pv = int((has_pv == 1).sum())
    flagged_area = float(d.loc[pred, "roof_area_m2"].sum())
    true_pv_area_flagged = float(d.loc[pred, "pv_area_true_m2"].sum())
    return {
        "n": int(len(d)), "n_flagged": n_flagged, "n_pv": n_pv,
        **conf,
        "roof_area_m2_flagged": round(flagged_area, 1),
        "true_pv_area_m2_flagged": round(true_pv_area_flagged, 1),
        "frac_of_calibration_flagged_area": (
            round(flagged_area / total_flagged_area, 4) if total_flagged_area else float("nan")
        ),
        "thin": bool(n_flagged < min_bin_n or n_pv < min_bin_n),
    }


def joint_precision_recall_table(
    buildings: pd.DataFrame,
    quadrat_density: pd.Series,
    threshold: float,
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_size_bins: int = DEFAULT_N_SIZE_BINS,
    min_bin_n: int = DEFAULT_COVERAGE_MIN_BIN_N,
) -> pd.DataFrame:
    """One row per (density_band, size_bin), plus margin rows (`pooled` on either axis) --
    a small contingency table with margins, all computed from one merged frame so it is
    self-consistent. Thin cells (`n_flagged` or `n_pv` below `min_bin_n`) are reported
    as-is, NEVER silently replaced by a pooled fallback the way `coverage_ratio_by_size`
    does -- showing where signal breaks down is this table's entire purpose.
    """
    d = buildings.copy()
    d["density"] = d["quadrat"].map(quadrat_density)

    density_edges = np.unique(
        np.quantile(quadrat_density.to_numpy(float), np.linspace(0, 1, n_density_bands + 1))
    )
    if len(density_edges) < 3:
        density_edges = np.array([quadrat_density.min(), quadrat_density.max()])
    density_edges[0], density_edges[-1] = -np.inf, np.inf
    d["density_band_idx"] = np.clip(
        np.searchsorted(density_edges, d["density"].to_numpy(float), side="right") - 1,
        0, len(density_edges) - 2,
    )

    size_edges = size_bin_edges(d["roof_area_m2"].to_numpy(float), n_size_bins)
    d["size_bin_idx"] = np.clip(
        np.searchsorted(size_edges, d["roof_area_m2"].to_numpy(float), side="right") - 1,
        0, len(size_edges) - 2,
    )

    total_flagged_area = float(d.loc[d.p_oof >= threshold, "roof_area_m2"].sum())

    rows = []
    n_bands = len(density_edges) - 1
    n_bins = len(size_edges) - 1
    for bi in range(n_bands):
        for si in range(n_bins):
            cell = d[(d.density_band_idx == bi) & (d.size_bin_idx == si)]
            if cell.empty:
                continue
            row = {
                "density_band": f"{density_edges[bi]:.0f}-{density_edges[bi + 1]:.0f}/km2",
                "size_bin": f"[{size_edges[si]:.0f}, {size_edges[si + 1]:.0f})",
                **_cell_row(cell, threshold, min_bin_n, total_flagged_area),
            }
            rows.append(row)
        # margin: pooled-size for this density band
        band_cell = d[d.density_band_idx == bi]
        rows.append({
            "density_band": f"{density_edges[bi]:.0f}-{density_edges[bi + 1]:.0f}/km2",
            "size_bin": "pooled",
            **_cell_row(band_cell, threshold, min_bin_n, total_flagged_area),
        })
    for si in range(n_bins):
        # margin: pooled-density for this size bin
        size_cell = d[d.size_bin_idx == si]
        rows.append({
            "density_band": "pooled",
            "size_bin": f"[{size_edges[si]:.0f}, {size_edges[si + 1]:.0f})",
            **_cell_row(size_cell, threshold, min_bin_n, total_flagged_area),
        })
    rows.append({
        "density_band": "pooled", "size_bin": "pooled",
        **_cell_row(d, threshold, min_bin_n, total_flagged_area),
    })
    return pd.DataFrame(rows)


def recall_precision_by_floor(
    buildings: pd.DataFrame,
    threshold: float,
    floors_m2: tuple[float, ...] = DEFAULT_FLOOR_BREAKPOINTS_M2,
    density_band: str | None = None,
) -> pd.DataFrame:
    """Precision/recall/n/area of `(p_oof >= threshold) AND (roof_area_m2 >= floor)` vs
    `has_pv`, for each fixed floor in `floors_m2` -- legible m2 breakpoints, not
    quantiles, because a floor decision is stated in m2. Run once pooled (sanity-checks
    against the untracked HTML's own reported numbers) and once per density band so the
    recall COST of a given floor can be compared directly across bands -- the concrete
    test of whether the floor should be joint with density.
    """
    rows = []
    for floor in floors_m2:
        pred = (buildings.p_oof.to_numpy(float) >= threshold) & (
            buildings.roof_area_m2.to_numpy(float) >= floor
        )
        has_pv = buildings.has_pv.to_numpy(int)
        conf = _confusion(pred, has_pv)
        rows.append({
            "density_band": density_band or "pooled",
            "floor_m2": floor,
            "n": int(len(buildings)),
            "n_flagged": int(pred.sum()),
            "n_pv": int((has_pv == 1).sum()),
            **conf,
            "roof_area_m2_flagged": round(float(buildings.loc[pred, "roof_area_m2"].sum()), 1),
        })
    return pd.DataFrame(rows)


def compare_quadrat_selections(
    buildings: pd.DataFrame,
    folds_path: Path,
    quadrat_profile_path: Path,
    threshold: float,
    n_density_bands: int,
    n_size_bins: int,
    min_bin_n: int,
) -> pd.DataFrame:
    """Runs the joint table for several named quadrat selections, isolating the
    mardan-specific exclusion (documented separately, worst AUC fold) from the
    ratio-band exclusion's own effect, and showing ratio-threshold sensitivity."""
    named = {
        "current_13": dict(ratio_lo=DEFAULT_RATIO_LO, ratio_hi=DEFAULT_RATIO_HI, exclude=DEFAULT_EXCLUDE),
        "drop_mardan_only": dict(ratio_lo=0.0, ratio_hi=float("inf"), exclude=DEFAULT_EXCLUDE),
        "all_18": dict(ratio_lo=0.0, ratio_hi=float("inf"), exclude=()),
        "widened_ratio_0.3_3.0": dict(ratio_lo=0.3, ratio_hi=3.0, exclude=DEFAULT_EXCLUDE),
    }
    rows = []
    for name, kw in named.items():
        quadrats, _ = select_calibrated_quadrats(folds_path, **kw)
        quadrat_density = quadrat_building_density_km2(quadrat_profile_path, quadrats)
        sub = buildings[buildings.quadrat.isin(quadrats)]
        joint = joint_precision_recall_table(
            sub, quadrat_density, threshold, n_density_bands, n_size_bins, min_bin_n,
        )
        joint.insert(0, "selection", name)
        joint.insert(1, "n_quadrats", len(quadrats))
        rows.append(joint)
    return pd.concat(rows, ignore_index=True)


def marginal_quadrat_contribution(
    buildings: pd.DataFrame,
    folds_path: Path,
    quadrat_profile_path: Path,
    threshold: float,
    n_density_bands: int,
    min_bin_n: int,
) -> pd.DataFrame:
    """For each currently-excluded quadrat: its own context (base_rate/rate_ratio/auc),
    which density band it would join, and the before/after n_flagged/n_pv/precision/
    recall for that band -- precision's and recall's deltas reported SEPARATELY, since
    `rate_ratio` (why these were excluded) is a precision-relevant bias measure, not
    necessarily informative about size-conditional recall."""
    base_quadrats, _ = select_calibrated_quadrats(
        folds_path, ratio_lo=DEFAULT_RATIO_LO, ratio_hi=DEFAULT_RATIO_HI, exclude=DEFAULT_EXCLUDE,
    )
    all_folds = pd.read_csv(folds_path).set_index("quadrat")
    excluded = sorted(set(all_folds.index) - set(base_quadrats))

    base_density = quadrat_building_density_km2(quadrat_profile_path, base_quadrats)
    density_edges = np.unique(
        np.quantile(base_density.to_numpy(float), np.linspace(0, 1, n_density_bands + 1))
    )
    density_edges[0], density_edges[-1] = -np.inf, np.inf

    all_density = quadrat_building_density_km2(
        quadrat_profile_path, base_quadrats + excluded
    )

    rows = []
    for q in excluded:
        q_density = float(all_density.loc[q])
        band_idx = int(np.clip(
            np.searchsorted(density_edges, q_density, side="right") - 1, 0, len(density_edges) - 2
        ))
        band_quadrats = [
            bq for bq in base_quadrats
            if int(np.clip(
                np.searchsorted(density_edges, float(base_density.loc[bq]), side="right") - 1,
                0, len(density_edges) - 2,
            )) == band_idx
        ]
        before = buildings[buildings.quadrat.isin(band_quadrats)]
        after = buildings[buildings.quadrat.isin(band_quadrats + [q])]
        before_conf = _confusion(before.p_oof.to_numpy(float) >= threshold, before.has_pv.to_numpy(int))
        after_conf = _confusion(after.p_oof.to_numpy(float) >= threshold, after.has_pv.to_numpy(int))
        rows.append({
            "excluded_quadrat": q,
            "base_rate": round(float(all_folds.loc[q, "base_rate"]), 4),
            "rate_ratio": round(float(all_folds.loc[q, "rate_ratio"]), 3),
            "auc": round(float(all_folds.loc[q, "auc"]), 4),
            "density_km2": round(q_density, 1),
            "joins_band": f"{density_edges[band_idx]:.0f}-{density_edges[band_idx + 1]:.0f}/km2",
            "band_n_before": before_conf["tp"] + before_conf["fp"] + before_conf["fn"] + (
                len(before) - before_conf["tp"] - before_conf["fp"] - before_conf["fn"]
            ),
            "band_precision_before": before_conf["precision"],
            "band_precision_after": after_conf["precision"],
            "band_recall_before": before_conf["recall"],
            "band_recall_after": after_conf["recall"],
            "band_n_pv_before": int((before.has_pv == 1).sum()),
            "band_n_pv_after": int((after.has_pv == 1).sum()),
        })
    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--buildings", type=Path, default=DEFAULT_BUILDINGS)
    ap.add_argument("--folds", type=Path, default=DEFAULT_FOLDS)
    ap.add_argument("--quadrat-profile", type=Path, default=DEFAULT_QUADRAT_PROFILE)
    ap.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    ap.add_argument("--threshold", type=float, default=None, help="Override deployment_threshold")
    ap.add_argument("--n-density-bands", type=int, default=DEFAULT_N_DENSITY_STRATA)
    ap.add_argument("--n-size-bins", type=int, default=DEFAULT_N_SIZE_BINS)
    ap.add_argument("--min-bin-n", type=int, default=DEFAULT_COVERAGE_MIN_BIN_N)
    ap.add_argument("--out-prefix", default="results/roofclf_size_density_signal")
    args = ap.parse_args()

    threshold = args.threshold if args.threshold is not None else load_threshold(args.summary_json)
    print(f"threshold = {threshold}\n")

    all_buildings = gpd.read_parquet(args.buildings)

    quadrats, folds_subset = select_calibrated_quadrats(args.folds)
    print(f"current_13 quadrats ({len(quadrats)}): {quadrats}")
    print(f"base_rate range: {folds_subset.base_rate.min():.3f}-{folds_subset.base_rate.max():.3f}\n")

    quadrat_density = quadrat_building_density_km2(args.quadrat_profile, quadrats)
    buildings = all_buildings[all_buildings.quadrat.isin(quadrats)]

    print("=== 1. Joint (density band x size bin) precision/recall table, current_13 ===")
    print(
        "NOTE: precision here is a documented LOWER BOUND (pre-epoch validation imagery "
        "scores real recent installs as false positives); recall over labelled "
        "installations is not similarly biased. Weight recall more when reading this.\n"
    )
    joint = joint_precision_recall_table(
        buildings, quadrat_density, threshold, args.n_density_bands, args.n_size_bins, args.min_bin_n,
    )
    print(joint.to_string(index=False))
    joint_path = f"{args.out_prefix}_joint.csv"
    Path(joint_path).parent.mkdir(parents=True, exist_ok=True)
    joint.to_csv(joint_path, index=False)
    print(f"-> {joint_path}\n")

    print("=== 2. Recall/precision cost by fixed size floor: pooled vs per density band ===")
    floor_rows = [recall_precision_by_floor(buildings, threshold)]
    density_edges = np.unique(
        np.quantile(quadrat_density.to_numpy(float), np.linspace(0, 1, args.n_density_bands + 1))
    )
    density_edges[0], density_edges[-1] = -np.inf, np.inf
    band_idx_by_quadrat = np.clip(
        np.searchsorted(density_edges, quadrat_density.to_numpy(float), side="right") - 1,
        0, len(density_edges) - 2,
    )
    for bi in range(len(density_edges) - 1):
        band_quadrats = quadrat_density.index[band_idx_by_quadrat == bi].tolist()
        if not band_quadrats:
            continue
        band_buildings = buildings[buildings.quadrat.isin(band_quadrats)]
        label = f"{density_edges[bi]:.0f}-{density_edges[bi + 1]:.0f}/km2"
        floor_rows.append(recall_precision_by_floor(band_buildings, threshold, density_band=label))
    floor_curve = pd.concat(floor_rows, ignore_index=True)
    print(floor_curve.to_string(index=False))
    floor_path = f"{args.out_prefix}_floor_curve.csv"
    floor_curve.to_csv(floor_path, index=False)
    print(f"-> {floor_path}\n")

    pooled_row = floor_curve[floor_curve.density_band == "pooled"]
    no_floor = pooled_row[pooled_row.floor_m2 == 0].iloc[0]
    print(
        f"Sanity check vs. the untracked HTML diagnostic: no-floor precision "
        f"{no_floor.precision:.3f} / recall {no_floor.recall:.3f} (HTML reported "
        f"~0.535 / ~0.740 -- compare before trusting anything new below).\n"
    )

    print("=== 3. Sensitivity of the joint table to which/how many quadrats are trusted ===")
    by_selection = compare_quadrat_selections(
        all_buildings, args.folds, args.quadrat_profile, threshold,
        args.n_density_bands, args.n_size_bins, args.min_bin_n,
    )
    pooled_only = by_selection[(by_selection.density_band == "pooled") & (by_selection.size_bin == "pooled")]
    print(pooled_only.to_string(index=False))
    selection_path = f"{args.out_prefix}_by_selection.csv"
    by_selection.to_csv(selection_path, index=False)
    print(f"-> {selection_path}\n")

    print("=== 4. Marginal contribution of each currently-excluded quadrat ===")
    marginal = marginal_quadrat_contribution(
        all_buildings, args.folds, args.quadrat_profile, threshold, args.n_density_bands, args.min_bin_n,
    )
    print(marginal.to_string(index=False))
    marginal_path = f"{args.out_prefix}_marginal_quadrats.csv"
    marginal.to_csv(marginal_path, index=False)
    print(f"-> {marginal_path}\n")

    n_total_quadrats = len(pd.read_csv(args.folds))
    print(
        f"=== Note: {n_total_quadrats} Rule-1-complete quadrats exist today "
        f"(results/calibration_quadrats.csv, all rule1_complete=True); "
        "there is no automated path to add more -- each one requires the owner to "
        "personally hand-map and declare completeness. select_calibrated_quadrats's "
        "13-of-18 selection is a data-driven ratio-band filter, not a fixed target "
        "count, and would change automatically if the underlying 18 changed.\n"
    )

    high_band = floor_curve[
        (floor_curve.density_band != "pooled") & (floor_curve.floor_m2 == floor_curve.floor_m2.max())
    ]
    print(
        "=== Headline read ===\n"
        "Compare the recall COST (delta from floor_m2=0 to a candidate floor) between "
        "density bands in table 2 above. If the cost is similar across bands, a flat "
        "floor is defensible. If it differs materially, a joint size-x-density rule "
        "would do meaningfully better than a flat one -- read off the per-band rows "
        "directly rather than trusting this summary alone."
    )


if __name__ == "__main__":
    main()
