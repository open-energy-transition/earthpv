"""Two ways to aim roofclf at the quantity the atlas actually consumes.

The classifier is scored on AUC, but the product is a per-cell CAPACITY, which is an
area-weighted aggregate. Two cheap interventions target that mismatch directly, and neither
touches the feature set:

  1. AREA-WEIGHTED LOSS. An unweighted fit treats a 30 m2 shed and a 390 m2 warehouse as
     equally important rows, while capacity does not. `fit_logistic(sample_weight=...)`.

  2. POST-HOC CALIBRATION. The 2026-09-19 model-class test found gradient boosting ranks
     worse but predicts per-quadrat adoption rates better. A MONOTONE recalibration of the
     linear model's scores cannot change its ranking at all, so if the calibration gain is
     recoverable this way it comes for free. Isotonic globally, isotonic within roof-area
     terciles, and Platt.

Calibrators are fitted NESTED: inside each leave-one-quadrat-out fold the 29 training
quadrats are split into 5 blocks BY QUADRAT, inner out-of-fold scores are produced, and the
calibrator is fitted on those. Fitting it on in-sample scores would be optimistic in exactly
the direction being measured.

Metrics are reported for both objectives, because the whole point is that they differ:
ranking (AUC, AUC within size band) and aggregate (count rate ratio, and AREA ratio, the
predicted flagged roof area over the true, which is what capacity scales with).

    pixi run python scripts/run_weighting_calibration_ablation.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             fit_logistic, predict_proba)

log = logging.getLogger("weighting_calibration")
N_INNER = 5


def _inner_oof(tr: pd.DataFrame, feats: list[str], weighted: bool, seed: int = 0):
    """Out-of-fold scores within the training quadrats, grouped by quadrat."""
    quads = sorted(tr.quadrat.unique())
    rng = np.random.default_rng(seed)
    # Round-robin over a shuffled quadrat list: balanced blocks, and deterministic given
    # the seed. Random assignment can leave a block empty at this size.
    order = rng.permutation(len(quads))
    block = {quads[q]: int(i % N_INNER) for i, q in enumerate(order)}
    oof = np.full(len(tr), np.nan)
    for b in range(N_INNER):
        te = tr.quadrat.map(block).to_numpy() == b
        if te.all() or not te.any() or tr.loc[~te, "has_pv"].nunique() < 2:
            continue
        w = tr.loc[~te, "roof_area_m2"].to_numpy() if weighted else None
        m = fit_logistic(_subset_matrix(tr[~te], feats),
                         tr.loc[~te, "has_pv"].to_numpy(float), L2, sample_weight=w)
        oof[te] = predict_proba(m, _subset_matrix(tr[te], feats))
    return oof


def _calibrate(kind, s_tr, y_tr, roof_tr, s_te, roof_te):
    """Fit a monotone recalibration on inner-OOF scores and apply it to the held-out fold."""
    from sklearn.isotonic import IsotonicRegression
    ok = np.isfinite(s_tr)
    if kind == "iso_global":
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(s_tr[ok], y_tr[ok])
        return iso.predict(s_te)
    if kind == "iso_by_size":
        # Terciles of roof area, cut on the TRAINING rows only.
        cuts = np.quantile(roof_tr[ok], [1 / 3, 2 / 3])
        out = np.empty_like(s_te)
        gtr, gte = np.digitize(roof_tr, cuts), np.digitize(roof_te, cuts)
        for g in range(3):
            m_tr, m_te = ok & (gtr == g), gte == g
            if m_tr.sum() < 50 or not m_te.any():
                out[m_te] = s_te[m_te]
                continue
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(s_tr[m_tr], y_tr[m_tr])
            out[m_te] = iso.predict(s_te[m_te])
        return out
    if kind == "platt":
        eps = 1e-6
        z = np.log(np.clip(s_tr[ok], eps, 1 - eps) / (1 - np.clip(s_tr[ok], eps, 1 - eps)))
        m = fit_logistic(z[:, None], y_tr[ok], l2=1e-6)
        zt = np.log(np.clip(s_te, eps, 1 - eps) / (1 - np.clip(s_te, eps, 1 - eps)))
        return predict_proba(m, zt[:, None])
    raise ValueError(kind)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=Path("data/roofclf_temporal_unmix/buildings.geoparquet"))
    ap.add_argument("--out", type=Path,
                    default=Path("results/roofclf_weighting_calibration.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t = gpd.read_parquet(args.table)
    feats = list(MODEL_FEATURES)
    log.info("%d rows, %d quadrats", len(t), t.quadrat.nunique())

    variants = ["baseline", "area_weighted", "iso_global", "iso_by_size", "platt",
                "area_weighted_iso"]
    rows = []
    for name in sorted(t.quadrat.unique()):
        te = (t.quadrat == name).to_numpy()
        tr_df = t[~te]
        if tr_df.has_pv.nunique() < 2:
            continue
        y = t.loc[te, "has_pv"].to_numpy()
        roof = t.loc[te, "roof_area_m2"].to_numpy()
        roof_tr = tr_df.roof_area_m2.to_numpy()
        y_tr = tr_df.has_pv.to_numpy(float)
        Xtr, Xte = _subset_matrix(tr_df, feats), _subset_matrix(t[te], feats)
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum()),
             "base_rate": float(y.mean()),
             "true_area": float((y * roof).sum())}
        scores = {}
        m_plain = fit_logistic(Xtr, y_tr, L2)
        scores["baseline"] = predict_proba(m_plain, Xte)
        m_w = fit_logistic(Xtr, y_tr, L2, sample_weight=roof_tr)
        scores["area_weighted"] = predict_proba(m_w, Xte)
        oof_plain = _inner_oof(tr_df, feats, weighted=False)
        oof_w = _inner_oof(tr_df, feats, weighted=True)
        for kind in ("iso_global", "iso_by_size", "platt"):
            scores[kind] = _calibrate(kind, oof_plain, y_tr, roof_tr,
                                      scores["baseline"], roof)
        scores["area_weighted_iso"] = _calibrate("iso_global", oof_w, y_tr, roof_tr,
                                                 scores["area_weighted"], roof)
        for k, p in scores.items():
            r[f"auc__{k}"] = auc(y, p)
            r[f"ws__{k}"] = auc_within_size(y, p, roof)[0]
            r[f"rate__{k}"] = float(np.mean(p))
            r[f"area__{k}"] = float((p * roof).sum())
        rows.append(r)
        log.info("%-24s " + " ".join(f"{k[:9]} %.4f" for k in variants), name,
                 *[r[f"auc__{k}"] for k in variants])
    d = pd.DataFrame(rows)

    from scipy import stats
    out = {"n_folds": int(len(d)), "medians": {}, "vs_baseline": {}}
    ok = d.base_rate > 0
    for k in variants:
        rr = d.loc[ok, f"rate__{k}"] / d.loc[ok, "base_rate"]
        ar = d.loc[ok, f"area__{k}"] / d.loc[ok, "true_area"]
        out["medians"][k] = {
            "auc": round(float(d[f"auc__{k}"].median()), 4),
            "within_size": round(float(d[f"ws__{k}"].median()), 4),
            "rate_ratio_median": round(float(rr.median()), 3),
            "rate_ratio_iqr_width": round(float(rr.quantile(.75) - rr.quantile(.25)), 3),
            "area_ratio_median": round(float(ar.median()), 3),
            "area_ratio_iqr_width": round(float(ar.quantile(.75) - ar.quantile(.25)), 3),
            "median_abs_rate_err": round(float((d.loc[ok, f"rate__{k}"]
                                                - d.loc[ok, "base_rate"]).abs().median()), 4),
        }
    e_base = (d.loc[ok, "rate__baseline"] - d.loc[ok, "base_rate"]).abs()
    for k in variants:
        if k == "baseline":
            continue
        e = (d.loc[ok, f"rate__{k}"] - d.loc[ok, "base_rate"]).abs()
        delta_auc = d[f"auc__{k}"] - d["auc__baseline"]
        better = int((e_base - e > 0).sum())
        worse = int((e_base - e < 0).sum())
        out["vs_baseline"][k] = {
            "delta_auc_median": round(float(delta_auc.median()), 4),
            "auc_folds_better": int((delta_auc > 0).sum()),
            "rate_err_closer_in": f"{better}/{int(ok.sum())}",
            "rate_err_sign_p": round(
                float(stats.binomtest(better, max(better + worse, 1), 0.5).pvalue), 4),
            "rate_err_wilcoxon_p": round(float(stats.wilcoxon(e_base, e).pvalue), 4)
            if (e_base - e).abs().sum() > 0 else None,
        }
    d.to_csv("results/roofclf_weighting_calibration_folds.csv", index=False)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
