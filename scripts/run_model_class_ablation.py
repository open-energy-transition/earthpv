"""Is the LINEAR MODEL the bottleneck, and does the shape block earn its place?

Every feature experiment in this project has been measured against `fit_logistic`, an
L2-regularised linear model. A linear score cannot express a conjunction, and "is this a PV
roof?" is one: dark AND spectrally flat across the visible AND the right SWIR drop AND
large AND in a dense-adoption area. So the six blocks measured within +/-0.005 of each
other may have been telling us about the functional form rather than the features.

Two questions on one set of leave-one-quadrat-out folds, from a table already built:

  1. Gradient boosting against the same features (`HistGradientBoostingClassifier`).
  2. `plus_shape`, which scored 0.8593 against the shipped 0.8574 in the ablation and has
     sat unadopted since 2026-08-09, given the paired test the rejected ideas all got.

Both GBM configurations are DECLARED HERE, not selected on the held-out folds: a
conservative one and a larger one, reported side by side, so nothing is tuned against the
thing it is measured on.

AUC is not the only column that matters. `rate_ratio` (predicted adoption rate over
observed) is reported per fold too, because the atlas consumes an aggregate: the register
already records that ranking transfers across quadrats while absolute rates do not, and a
model that ranks better but calibrates worse is not an improvement for this product.

    pixi run python scripts/run_model_class_ablation.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import (L2, MODEL_FEATURES, SHAPE_FEATURES, _subset_matrix, auc,
                             auc_within_size, fit_logistic, predict_proba)

log = logging.getLogger("model_class_ablation")

GBM_CONFIGS = {
    "gbm_small": dict(max_leaf_nodes=15, max_iter=200, learning_rate=0.08,
                      min_samples_leaf=100, l2_regularization=1.0),
    "gbm_large": dict(max_leaf_nodes=63, max_iter=600, learning_rate=0.05,
                      min_samples_leaf=20, l2_regularization=1.0),
}


def _fit_predict(model: str, Xtr, ytr, Xte) -> np.ndarray:
    if model == "logistic":
        return predict_proba(fit_logistic(Xtr, ytr, L2), Xte)
    from sklearn.ensemble import HistGradientBoostingClassifier

    clf = HistGradientBoostingClassifier(
        random_state=0, early_stopping=False, **GBM_CONFIGS[model])
    clf.fit(Xtr, ytr)
    return clf.predict_proba(Xte)[:, 1]


def run(table: pd.DataFrame, combos: dict[str, tuple[str, list[str]]]) -> pd.DataFrame:
    rows = []
    for name in sorted(table.quadrat.unique()):
        te = (table.quadrat == name).to_numpy()
        tr = ~te
        if table.loc[tr, "has_pv"].nunique() < 2:
            continue
        y = table.loc[te, "has_pv"].to_numpy()
        roof = table.loc[te, "roof_area_m2"].to_numpy()
        ytr = table.loc[tr, "has_pv"].to_numpy(float)
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum()),
             "base_rate": float(y.mean())}
        for label, (model, feats) in combos.items():
            Xtr, Xte = _subset_matrix(table[tr], feats), _subset_matrix(table[te], feats)
            p = _fit_predict(model, Xtr, ytr, Xte)
            r[f"auc__{label}"] = auc(y, p)
            r[f"ws__{label}"] = auc_within_size(y, p, roof)[0]
            r[f"rate__{label}"] = float(np.mean(p))
        rows.append(r)
        log.info("%-24s " + "  ".join(f"{k} %.4f" for k in combos),
                 name, *[rows[-1][f"auc__{k}"] for k in combos])
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=Path("data/roofclf_temporal_unmix/buildings.geoparquet"))
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_model_class.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    table = gpd.read_parquet(args.table)
    log.info("%d rows, %d quadrats from %s", len(table), table.quadrat.nunique(), args.table)
    base = list(MODEL_FEATURES)
    shape = list(MODEL_FEATURES) + list(SHAPE_FEATURES)
    combos = {
        "logistic": ("logistic", base),
        "logistic_shape": ("logistic", shape),
        "gbm_small": ("gbm_small", base),
        "gbm_large": ("gbm_large", base),
        "gbm_small_shape": ("gbm_small", shape),
        "gbm_large_shape": ("gbm_large", shape),
    }
    d = run(table, combos)

    from scipy import stats
    out = {"n_folds": int(len(d)), "n_rows": int(len(table)), "configs": GBM_CONFIGS,
           "medians": {}, "vs_logistic": {}}
    for k in combos:
        out["medians"][k] = {
            "auc": round(float(d[f"auc__{k}"].median()), 4),
            "within_size": round(float(d[f"ws__{k}"].median()), 4),
        }
        # Calibration: predicted over observed adoption rate, folds with a nonzero base
        # rate only (one quadrat is a confirmed zero, where the ratio is undefined).
        ok = d.base_rate > 0
        rr = d.loc[ok, f"rate__{k}"] / d.loc[ok, "base_rate"]
        out["medians"][k]["rate_ratio_median"] = round(float(rr.median()), 3)
        out["medians"][k]["rate_ratio_iqr"] = [round(float(rr.quantile(.25)), 3),
                                               round(float(rr.quantile(.75)), 3)]
    for k in combos:
        if k == "logistic":
            continue
        e = {}
        for lab, col in (("auc", "auc"), ("ws", "ws")):
            delta = d[f"{col}__{k}"] - d[f"{col}__logistic"]
            better = int((delta > 0).sum())
            worse = int((delta < 0).sum())
            e[f"delta_{lab}_median"] = round(float(delta.median()), 4)
            e[f"delta_{lab}_iqr"] = [round(float(delta.quantile(.25)), 4),
                                     round(float(delta.quantile(.75)), 4)]
            e[f"{lab}_folds_better"] = better
            e[f"{lab}_sign_p"] = round(
                float(stats.binomtest(better, max(better + worse, 1), 0.5).pvalue), 4)
        out["vs_logistic"][k] = e

    d.to_csv("results/roofclf_model_class_folds.csv", index=False)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps({"medians": out["medians"], "vs_logistic": out["vs_logistic"]}, indent=2))


if __name__ == "__main__":
    main()
