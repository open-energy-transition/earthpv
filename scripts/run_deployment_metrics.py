"""Does the noise-reduction package move the numbers the ATLAS consumes, not just AUC?

`roofclf`'s AUC is not what capacity is built from. `run_roof_classifier` picks a threshold
targeting precision 0.5 on pooled out-of-fold scores, and everything downstream --
`sub400_capacity`'s coverage ratio and area recall -- is fitted on the population that
threshold flags. A ranking gain that leaves the flagged population unchanged changes no
capacity figure.

So this reports, for each variant, what the shipped deployment step would report: the
threshold, and the precision, recall and flagged count at it, from honest leave-one-quadrat-
out scores.

    pixi run python scripts/run_deployment_metrics.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, fit_logistic,
                             predict_proba)
from earthpv.sppi import _precision_threshold

log = logging.getLogger("deployment")
VARIANTS = {
    "baseline": None,
    "tmean_trim": "data/roofclf_preprocess/tmean_trim/buildings.geoparquet",
    "trimzonal": "data/roofclf_preprocess/trimzonal/buildings.geoparquet",
    "year_trim": "data/roofclf_preprocess/year_trim/buildings.geoparquet",
}


def _key(t):
    c = t.geometry.representative_point()
    return (t.quadrat.astype(str) + "|" + c.x.round(6).astype(str) + "|"
            + c.y.round(6).astype(str))


def oof(t: pd.DataFrame) -> np.ndarray:
    p = np.full(len(t), np.nan)
    for n in sorted(t.quadrat.unique()):
        te = (t.quadrat == n).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2:
            continue
        m = fit_logistic(_subset_matrix(t[tr], MODEL_FEATURES),
                         t.loc[tr, "has_pv"].to_numpy(float), L2)
        p[te] = predict_proba(m, _subset_matrix(t[te], MODEL_FEATURES))
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path,
                    default=Path("data/roofclf_temporal_unmix/buildings.geoparquet"))
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_deployment_metrics.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    base = gpd.read_parquet(args.baseline)
    base["_k"] = _key(base)
    out = {}
    for name, path in VARIANTS.items():
        t = base if path is None else gpd.read_parquet(path).pipe(
            lambda d: d.assign(_k=_key(d)))
        if path is not None:
            t = t[t._k.isin(set(base._k))]
        t = t.sort_values("_k").reset_index(drop=True)
        s = oof(t)
        ok = np.isfinite(s)
        y = t.loc[ok, "has_pv"].to_numpy(bool)
        sc = s[ok]
        thr = _precision_threshold(y, sc, min_precision=0.5)
        pred = sc >= thr
        tp, fp = int((pred & y).sum()), int((pred & ~y).sum())
        out[name] = {
            "n": int(ok.sum()), "auc": round(float(auc(y.astype(int), sc)), 4),
            "threshold": round(float(thr), 4),
            "n_flagged": int(pred.sum()),
            "precision": round(tp / max(tp + fp, 1), 4),
            "recall": round(tp / max(int(y.sum()), 1), 4),
        }
        log.info("%-12s auc %.4f  thr %.4f  flagged %6d  precision %.3f  recall %.3f",
                 name, out[name]["auc"], thr, out[name]["n_flagged"],
                 out[name]["precision"], out[name]["recall"])
    b = out["baseline"]
    for k, v in out.items():
        if k != "baseline":
            v["recall_gain_at_same_precision"] = round(v["recall"] - b["recall"], 4)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
