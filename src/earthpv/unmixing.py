"""Per-footprint linear spectral unmixing: a minimal two-endmember model, tested here as
a candidate FOURTH sub-400 m² instrument alongside the segmentation raster, the fraction
head, and roofclf (see CLAUDE.md's "Sub-400 m² instruments" and
`docs/methods/density.md`'s "How could we lower the detection floor" bracket section,
2026-07-31).

The idea this promotes: instead of a nationally-fitted classifier or a fixed spectral
formula, estimate each building's PV coverage fraction by projecting its zonal-mean
reflectance onto the line connecting a "pure PV" endmember and a "pure background"
endmember -- and fit those two endmembers FROM THE SAME LOCAL POPULATION being scored
(a cell's own confirmed >= 400 m² detections and known negatives), not from a national
covariate. That is structurally different from the three approaches this project has
already tried and failed to find a national stratification proxy for (existing candidate
density, roofclf's own raw rate, SPPI agreement rate): those all predict which REGIME a
cell is in from a proxy measured elsewhere; this instead asks whether a cell can
calibrate itself, with no proxy and no transfer at all.

**Status: LOQO-evaluated on the 8 mapped quadrats only (`evaluate_loqo`), not yet run at
national/per-cell scale.** The per-cell self-check (`cell_selfcheck_ratio`) that would
make this deployable nationally -- recover known area on a cell's own large detections,
trust the small-array output only where that recovery holds -- is implemented but has
never been exercised against real per-cell data; that is the natural next step once this
quadrat-level result is judged worth pursuing further.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from earthpv.roofclf import BAND_NAMES, auc, auc_within_size


def fit_endmembers(
    t: pd.DataFrame, pv_weight_col: str = "pv_frac_true", truth_col: str = "has_pv",
    bands: tuple[str, ...] = BAND_NAMES,
) -> tuple[np.ndarray, np.ndarray]:
    """Two endmember reflectance vectors from a labelled building table.

    The PV endmember is the `pv_weight_col`-weighted mean band vector -- weighting
    toward more fully covered roofs sharpens the pure-PV signature rather than diluting
    it with partially covered ones. The background endmember is the plain mean over
    `truth_col == False` buildings. Both are fit on whatever pool is passed in; the
    caller decides whether that is "the other N-1 quadrats" (LOQO, below) or, in a real
    per-cell deployment, that cell's own confirmed detections and low-score buildings.
    """
    cols = [f"{b}_mean" for b in bands]
    x = t[cols].to_numpy(float)
    w = t[pv_weight_col].to_numpy(float)
    if w.sum() <= 0:
        raise ValueError("no positive PV weight in training pool")
    pv_vec = (x * w[:, None]).sum(axis=0) / w.sum()
    bg = ~t[truth_col].astype(bool).to_numpy()
    if not bg.any():
        raise ValueError("no negative (has_pv == False) buildings in training pool")
    bg_vec = x[bg].mean(axis=0)
    return pv_vec, bg_vec


def unmix_fraction(
    t: pd.DataFrame, pv_vec: np.ndarray, bg_vec: np.ndarray, bands: tuple[str, ...] = BAND_NAMES,
) -> np.ndarray:
    """Per-building PV coverage fraction via 1-D projection onto the PV<->background
    line in band space -- the minimal two-endmember linear mixture model, clipped to
    [0, 1]. A full simplex-constrained multi-endmember unmix would need far more
    training examples per fit than an 8-quadrat table (or a single cell) can supply;
    this is the model with the fewest free parameters that still has a physical
    reading (a roof is a mix of PV panel and whatever the roof is made of).
    """
    cols = [f"{b}_mean" for b in bands]
    x = t[cols].to_numpy(float)
    d = pv_vec - bg_vec
    denom = float(np.dot(d, d))
    if denom <= 0:
        return np.zeros(len(t))
    f = (x - bg_vec[None, :]) @ d / denom
    return np.clip(f, 0.0, 1.0)


def evaluate_loqo(
    t: pd.DataFrame, quadrat_col: str = "quadrat", truth_col: str = "has_pv",
    pv_weight_col: str = "pv_frac_true", roof_col: str = "roof_area_m2",
) -> pd.DataFrame:
    """Leave-one-quadrat-out evaluation, same protocol as `roofclf.evaluate` /
    `sppi.calibrate_threshold_loqo`: endmembers fit on the other quadrats (pooled),
    scored on the held-out one, so every reported number is out-of-fold.

    Reports AUC, size-conditional AUC (`roofclf.auc_within_size`, the same honest
    metric this project uses everywhere -- see CLAUDE.md), Pearson r against the true
    per-footprint PV areal fraction (the area-estimation analogue of AUC), and the
    aggregate predicted/true PV area ratio (`scale`, matching `roofclf.exp_scale_anchor`
    and the SPPI evaluation's own `scale` column) -- directly comparable to the existing
    segmentation/fraction-head/SPPI table in
    `docs/issues/sppi-spectral-index-evaluation.md`.
    """
    rows = []
    for q in t[quadrat_col].unique():
        train = t[t[quadrat_col] != q]
        test = t[t[quadrat_col] == q]
        pv_vec, bg_vec = fit_endmembers(train, pv_weight_col=pv_weight_col, truth_col=truth_col)
        f = unmix_fraction(test, pv_vec, bg_vec)
        y = test[truth_col].astype(bool).to_numpy()
        roof = test[roof_col].to_numpy(float)
        true_frac = test[pv_weight_col].to_numpy(float)

        a = auc(y, f)
        a_ws, _ = auc_within_size(y, f, roof)
        r = float(np.corrcoef(f, true_frac)[0, 1]) if len(test) > 1 else float("nan")
        pred_area = float((f * roof).sum())
        true_area = float((true_frac * roof).sum())
        scale = pred_area / true_area if true_area > 0 else float("nan")

        rows.append({
            "quadrat": q, "n": len(test), "n_pv": int(y.sum()),
            "auc": round(a, 4) if a == a else np.nan,
            "auc_within_size": round(a_ws, 4) if a_ws == a_ws else np.nan,
            "pearson_r": round(r, 4) if r == r else np.nan,
            "pred_area_m2": round(pred_area, 1),
            "true_area_m2": round(true_area, 1),
            "scale": round(scale, 4) if scale == scale else np.nan,
        })
    return pd.DataFrame(rows)


def cell_selfcheck_ratio(confirmed_pred_area_m2: float, confirmed_true_area_m2: float) -> float:
    """Recovered/true area ratio on a cell's own >= 400 m² confirmed detections -- the
    per-cell self-calibration signal this module's docstring proposes as a fourth
    candidate national stratification proxy, needing no ground truth (unlike
    `evaluate_loqo`, which needs quadrat labels and can therefore never run nationally).

    **Not yet tested nationally.** This function exists so a future per-cell run
    (fit endmembers per cell from its own >= 400 m² detections and low-score buildings,
    apply to that cell's sub-400 m² buildings, then check this ratio) can be assembled;
    `evaluate_loqo` above is the only evaluation actually run so far, and it answers a
    different question (does the mechanism work at all on labelled quadrats), not
    whether the self-check ratio would correctly flag good vs. bad cells nationally.
    """
    if confirmed_true_area_m2 <= 0:
        return float("nan")
    return confirmed_pred_area_m2 / confirmed_true_area_m2
