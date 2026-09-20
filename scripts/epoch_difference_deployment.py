"""What the 2019 epoch difference is worth in the units the atlas consumes.

Same question `run_deployment_metrics.py` asks of the noise-reduction package: AUC is not
what capacity is built from. `run_roof_classifier` picks a threshold targeting precision 0.5
on pooled out-of-fold scores and `sub400_capacity` fits its coverage ratio and area recall on
whatever that flags, so a ranking gain that leaves the flagged population alone changes no
capacity figure.

Both arms are scored on the SAME rows (the epoch table, one shared NaN drop) so the
comparison is the feature block and nothing else.

    pixi run python scripts/epoch_difference_deployment.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, discover_quadrats,
                             fit_logistic, predict_proba)
from earthpv.sppi import _precision_threshold


def main() -> None:
    from scripts.run_epoch_difference_ablation import DELTA_OLD, EXCLUDE, quadrat_deltas

    base = gpd.read_parquet("data/roofclf_temporal_ablation/buildings.geoparquet")
    parts = []
    for stem in sorted(discover_quadrats(Path("data/labels"))):
        if stem == EXCLUDE:
            continue
        sub = base[base.quadrat == stem.split("_calib_")[0]]
        if sub.empty:
            continue
        d = quadrat_deltas(stem, sub, Path("data/composites/pakistan"), Path("data/labels"))
        if d is None:
            continue
        d.index = sub.index
        parts.append(pd.concat([sub, d], axis=1))
    t = pd.concat(parts, ignore_index=True)
    arms = {"baseline": list(MODEL_FEATURES),
            "plus_delta_2019": list(MODEL_FEATURES) + list(DELTA_OLD)}
    allf = sorted({c for f in arms.values() for c in f})
    t = t[np.isfinite(_subset_matrix(t, allf)).all(axis=1)].reset_index(drop=True)
    y = t.has_pv.to_numpy(bool)

    out = {"n_rows": int(len(t))}
    print(f"\n{len(t)} rows, {t.quadrat.nunique()} quadrats")
    print(f"{'arm':18} {'AUC':>8} {'threshold':>10} {'flagged':>9} {'precision':>10} "
          f"{'recall':>8}")
    base_recall = None
    for lab, feats in arms.items():
        s = np.full(len(t), np.nan)
        for q in sorted(t.quadrat.unique()):
            te = (t.quadrat == q).to_numpy()
            tr = ~te
            if t.loc[tr, "has_pv"].nunique() < 2:
                continue
            m = fit_logistic(_subset_matrix(t[tr], feats),
                             t.loc[tr, "has_pv"].to_numpy(float), L2)
            s[te] = predict_proba(m, _subset_matrix(t[te], feats))
        ok = np.isfinite(s)
        thr = _precision_threshold(y[ok], s[ok], 0.5)
        flag = ok & (s >= thr)
        prec = float(y[flag].mean())
        rec = float(y[flag].sum() / y[ok].sum())
        base_recall = rec if base_recall is None else base_recall
        print(f"{lab:18} {auc(y[ok], s[ok]):8.4f} {thr:10.4f} {int(flag.sum()):9d} "
              f"{prec:10.4f} {rec:8.4f}")
        out[lab] = {"auc": round(float(auc(y[ok], s[ok])), 4), "threshold": round(thr, 4),
                    "n_flagged": int(flag.sum()), "precision": round(prec, 4),
                    "recall": round(rec, 4), "d_recall": round(rec - base_recall, 4)}
    Path("results/roofclf_epoch_deployment.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nwrote results/roofclf_epoch_deployment.json")


if __name__ == "__main__":
    main()
