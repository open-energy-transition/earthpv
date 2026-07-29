"""SPPI (He et al. 2026) as a building-scoped, precision-calibrated PV detector.

Promotes the formula and evaluation validated in `scripts/sppi_index_test.py` /
`docs/issues/sppi-spectral-index-evaluation.md` into reusable code. That evaluation found
SPPI is a real, substantially independent per-building signal (median AUC 0.828 within
size band, only 30.6% overlap with what the segmentation model catches) but NOT a
standalone capacity instrument (18x scale spread across quadrats, worst case 4.7x
over-prediction on bare arid ground -- exactly this project's dominant false-positive
mode).

The design here is scoped to close that specific gap: SPPI-driven candidates are
restricted to BUILDING FOOTPRINTS. Bare rock, glacier, and desert have no building to
attach a candidate to, so they cannot enter this path at all -- the arid failure mode is
structurally excluded rather than statistically corrected. This module only prepares and
validates the mechanism (leave-one-quadrat-out threshold calibration and precision
measurement on the 9 mapped quadrats, via `scripts/sppi_capacity_validation.py`); it does
not run at national scale, which is an explicit follow-up decision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-6


def compute_sppi(b02, b03, b08, b11, b12):
    """SPPI = (B02/B03) * ((B11 - B03 - |B08-B03| - |B12-B03|) / (B11 + B03)).

    B02 (blue) substitutes for the paper's B01 (coastal aerosol, 60 m), which earthpv's
    10-band composites exclude (`config.LOCAL_BANDS`) -- the paper's own recommended
    substitution, costed by the authors at +/-2% accuracy. Every term is a ratio or
    normalized difference of same-scaled reflectance, so it is invariant to whatever
    fixed scale factor the input bands carry (composite DN or true reflectance) --
    accepts numpy arrays, pandas Series, or scalars.
    """
    return (b02 / (b03 + EPS)) * (
        (b11 - b03 - np.abs(b08 - b03) - np.abs(b12 - b03)) / (b11 + b03 + EPS)
    )


def add_sppi(df: pd.DataFrame) -> pd.DataFrame:
    """Add an `sppi` column from a DataFrame carrying `b02_mean`...`b12_mean` (the
    `roofclf.building_table` column convention)."""
    df = df.copy()
    df["sppi"] = compute_sppi(df.b02_mean, df.b03_mean, df.b08_mean, df.b11_mean, df.b12_mean)
    return df


def _youden_threshold(y: np.ndarray, s: np.ndarray) -> tuple[float, dict]:
    """Threshold maximizing Youden's J (sensitivity + specificity - 1).

    Prevalence-independent, unlike F1 -- appropriate here since quadrat base rates span
    3% to 30% (`roofclf`'s own fold table) and a prevalence-sensitive criterion would
    chase specificity in the low-base-rate quadrats rather than a genuinely better cut.
    Candidate thresholds are every distinct score value (a full ROC sweep, not a grid).
    """
    y = np.asarray(y).astype(bool)
    order = np.argsort(s)
    s_sorted = s[order]
    thresholds = np.unique(s_sorted)
    best_j, best_t, best_stats = -np.inf, float(thresholds[0]), {}
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float(np.median(s)), {"sensitivity": float("nan"), "specificity": float("nan")}
    for t in thresholds:
        pred = s >= t
        tp = int((pred & y).sum())
        fp = int((pred & ~y).sum())
        fn = int((~pred & y).sum())
        tn = int((~pred & ~y).sum())
        sens = tp / n_pos
        spec = tn / n_neg
        j = sens + spec - 1
        if j > best_j:
            precision = tp / (tp + fp) if (tp + fp) else float("nan")
            f1 = 2 * precision * sens / (precision + sens) if (precision + sens) else float("nan")
            best_j, best_t = j, float(t)
            best_stats = {
                "sensitivity": sens, "specificity": spec, "precision": precision, "f1": f1,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            }
    return best_t, best_stats


def _precision_threshold(y: np.ndarray, s: np.ndarray, min_precision: float = 0.5) -> float:
    """Highest (most conservative) threshold whose cumulative precision, sweeping
    scores from the top down, first reaches `min_precision`. If nothing clears it,
    returns a threshold above the max score (flags nothing) rather than silently
    falling back to a low-precision cut -- a candidate class with no reliable
    precision floor should contribute zero capacity, not a guess.
    """
    y = np.asarray(y).astype(bool)
    order = np.argsort(-s)
    s_sorted, y_sorted = s[order], y[order]
    cum_tp = np.cumsum(y_sorted)
    cum_n = np.arange(1, len(y_sorted) + 1)
    precision = cum_tp / cum_n
    ok = np.where(precision >= min_precision)[0]
    return float(s_sorted[ok[-1]]) if len(ok) else float(s_sorted[0]) + 1.0


def calibrate_threshold_loqo(
    t: pd.DataFrame, score_col: str = "sppi", truth_col: str = "has_pv",
    quadrat_col: str = "quadrat", criterion: str = "precision", min_precision: float = 0.5,
) -> pd.DataFrame:
    """Leave-one-quadrat-out SPPI threshold calibration, same protocol as
    `roofclf.evaluate`: fit on the other N-1 quadrats (pooled), apply to the held-out
    one, so every reported number is out-of-fold. Returns one row per quadrat with the
    threshold and its performance *on the held-out quadrat* (the deployment-honest
    number), not on the quadrats that set it.

    `criterion="precision"` (the default, and the right one for a capacity-contributing
    detector, where a false positive directly inflates the published number) picks the
    most conservative threshold clearing `min_precision` on the training pool.
    `criterion="youden"` instead maximizes sensitivity+specificity-1 -- a general
    classifier-evaluation criterion (matches `roofclf`'s own AUC-oriented framing) that
    this session measured trades away far too much precision for this specific use:
    median held-out precision 0.272 (youden) vs 0.524 (precision, min_precision=0.5),
    and youden left the arid quadrat (Quetta) at 4.9% precision -- unusably low.
    """
    rows = []
    for q in t[quadrat_col].unique():
        train = t[t[quadrat_col] != q]
        test = t[t[quadrat_col] == q]
        y_train, s_train = train[truth_col].to_numpy(bool), train[score_col].to_numpy(float)
        if criterion == "precision":
            thresh = _precision_threshold(y_train, s_train, min_precision=min_precision)
            train_stats: dict = {}
        elif criterion == "youden":
            thresh, train_stats = _youden_threshold(y_train, s_train)
        else:
            raise ValueError(f"unknown criterion {criterion!r}")
        y_test = test[truth_col].to_numpy(bool)
        s_test = test[score_col].to_numpy(float)
        pred = s_test >= thresh
        tp = int((pred & y_test).sum())
        fp = int((pred & ~y_test).sum())
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / y_test.sum() if y_test.sum() else float("nan")
        rows.append({
            "quadrat": q, "criterion": criterion, "threshold": round(thresh, 4),
            "n": len(test), "n_pv": int(y_test.sum()),
            "n_flagged": int(pred.sum()),
            "precision_held_out": round(precision, 4) if precision == precision else np.nan,
            "recall_held_out": round(recall, 4) if recall == recall else np.nan,
            "train_sensitivity": round(train_stats.get("sensitivity", np.nan), 4),
            "train_specificity": round(train_stats.get("specificity", np.nan), 4),
        })
    return pd.DataFrame(rows)


def sppi_only_incremental(
    t: pd.DataFrame, thresholds: pd.DataFrame, seg_threshold: float = 0.3,
    kwp_per_m2_module: float = 0.18,
) -> pd.DataFrame:
    """Per quadrat: buildings SPPI flags (at its LOQO-calibrated threshold) that the
    segmentation model's own raster does NOT already flag at its operating point
    (`seg_max < seg_threshold`) -- the incremental, SPPI-only, building-scoped
    candidates this module could add.

    Measures, per quadrat: how many buildings are flagged, the measured precision among
    them (`has_pv` ground truth -- this doubles as this candidate class's own `p_real`,
    the thing a raw SPPI raster has no way to supply), their total roof area, and the
    capacity impact of that area at `kwp_per_m2_module`, precision-weighted -- directly
    comparable to that quadrat's existing segmentation-only capacity
    (`data/roofclf/exp_scale_anchor.csv`'s `true_pv_area_m2` denominator).
    """
    thresh_by_quadrat = thresholds.set_index("quadrat")["threshold"].to_dict()
    rows = []
    for q, g in t.groupby("quadrat"):
        thresh = thresh_by_quadrat.get(q)
        if thresh is None:
            continue
        incremental = g[(g["sppi"] >= thresh) & (g["seg_max"] < seg_threshold)]
        n_flagged = len(incremental)
        n_true = int(incremental["has_pv"].sum())
        precision = n_true / n_flagged if n_flagged else float("nan")
        roof_area = float(incremental["roof_area_m2"].sum())
        true_pv_area_of_flagged = float(incremental["pv_area_true_m2"].sum())
        capacity_kwp = roof_area * kwp_per_m2_module * (precision if precision == precision else 0.0)
        rows.append({
            "quadrat": q,
            "n_buildings": len(g),
            "n_seg_missed_sppi_flagged": n_flagged,
            "n_true_positive": n_true,
            "precision": round(precision, 4) if precision == precision else np.nan,
            "incremental_roof_area_m2": round(roof_area, 1),
            "true_pv_area_in_flagged_m2": round(true_pv_area_of_flagged, 1),
            "incremental_capacity_kwp": round(capacity_kwp, 1),
        })
    return pd.DataFrame(rows)


def recall_effect(
    t: pd.DataFrame, thresholds: pd.DataFrame, seg_threshold: float = 0.3,
) -> pd.DataFrame:
    """Per quadrat: does treating an SPPI-flagged building as "detected" raise the
    matched fraction of true installations, the same question `capacity_calibration
    .derive_table`'s recall block asks nationally -- computed directly here since
    quadrat ground truth links `has_pv` to each building 1:1 (no distance-matching
    needed at this scale, unlike the national `new_lead_mask`-based check).
    """
    thresh_by_quadrat = thresholds.set_index("quadrat")["threshold"].to_dict()
    rows = []
    for q, g in t.groupby("quadrat"):
        thresh = thresh_by_quadrat.get(q)
        if thresh is None:
            continue
        true = g[g["has_pv"].astype(bool)]
        if true.empty:
            continue
        seg_recall = float((true["seg_max"] >= seg_threshold).mean())
        combined_recall = float(((true["seg_max"] >= seg_threshold) | (true["sppi"] >= thresh)).mean())
        rows.append({
            "quadrat": q, "n_true_installations": len(true),
            "seg_only_recall": round(seg_recall, 4),
            "combined_recall": round(combined_recall, 4),
            "recall_delta": round(combined_recall - seg_recall, 4),
        })
    return pd.DataFrame(rows)
