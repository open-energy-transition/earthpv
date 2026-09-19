"""Does handing roofclf the CELL-LEVEL brightness improve the level it predicts?

`absolute = cell_mean + deviation`, and the model sees only `absolute`, which confounds
"this building is bright" with "this cell is bright". Adding the cell mean is one extra
degree of freedom per feature.

Registered before measuring: a cell-constant feature adds the SAME number to every
building's logit inside a held-out quadrat, so it cannot reorder them. Any AUC movement can
only come from refitting the other coefficients. What it can move is the LEVEL, which is
where this model is weakest -- per-quadrat adoption-rate error 0.0308, the one place
gradient boosting beat it -- and the motivation is the measured split: within-cell z-scores
alone tie the shipped ranking while doubling the rate error, so ranking is relative and
calibration is absolute.

    pixi run python scripts/run_cell_level_ablation.py
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from earthpv.roofclf import (CELL_LEVEL_FEATURES, L2, MODEL_FEATURES, _subset_matrix,
                             add_cell_level_features, auc, auc_within_size, fit_logistic,
                             predict_proba)

log = logging.getLogger("cell_level")
TABLE = "data/roofclf_temporal_unmix/buildings.geoparquet"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t = add_cell_level_features(gpd.read_parquet(TABLE))
    log.info("%d rows, %d quadrats", len(t), t.quadrat.nunique())
    blocks = {
        "baseline": list(MODEL_FEATURES),
        "plus_brightness_cellmean": list(MODEL_FEATURES) + ["brightness_cellmean"],
        "plus_all_cellmeans": list(MODEL_FEATURES) + list(CELL_LEVEL_FEATURES),
    }
    rows = []
    for i, name in enumerate(sorted(t.quadrat.unique()), 1):
        te = (t.quadrat == name).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2:
            continue
        y = t.loc[te, "has_pv"].to_numpy()
        roof = t.loc[te, "roof_area_m2"].to_numpy()
        r = {"quadrat": name, "base_rate": float(y.mean()), "n_pv": int(y.sum())}
        for lab, feats in blocks.items():
            m = fit_logistic(_subset_matrix(t[tr], feats),
                             t.loc[tr, "has_pv"].to_numpy(float), L2)
            p = predict_proba(m, _subset_matrix(t[te], feats))
            r[f"auc__{lab}"] = auc(y, p)
            r[f"ws__{lab}"] = auc_within_size(y, p, roof)[0]
            r[f"rate__{lab}"] = float(np.mean(p))
        rows.append(r)
        log.info("[%d] %-26s auc %.4f -> %.4f", i, name.split("_calib")[0],
                 r["auc__baseline"], r["auc__plus_all_cellmeans"])
    d = pd.DataFrame(rows)
    ok = d.base_rate > 0
    print(f"\n{'block':28} {'AUC':>8} {'w-size':>8} {'|rate err|':>11} {'rate ratio':>11}")
    for lab in blocks:
        err = (d.loc[ok, f"rate__{lab}"] - d.loc[ok, "base_rate"]).abs()
        rr = d.loc[ok, f"rate__{lab}"] / d.loc[ok, "base_rate"]
        print(f"{lab:28} {d[f'auc__{lab}'].median():8.4f} {d[f'ws__{lab}'].median():8.4f} "
              f"{err.median():11.4f} {rr.median():11.3f}")
    e_base = (d.loc[ok, "rate__baseline"] - d.loc[ok, "base_rate"]).abs()
    print(f"\n{'vs baseline':28} {'dAUC':>9} {'AUC better':>11} {'rate closer':>12} "
          f"{'sign p':>8} {'wilcox':>8}")
    for lab in blocks:
        if lab == "baseline":
            continue
        e = (d.loc[ok, f"rate__{lab}"] - d.loc[ok, "base_rate"]).abs()
        dl = d[f"auc__{lab}"] - d["auc__baseline"]
        b = int((e_base - e > 0).sum())
        w = int((e_base - e < 0).sum())
        ps = stats.binomtest(b, max(b + w, 1), 0.5).pvalue
        pw = stats.wilcoxon(e_base, e).pvalue if (e_base - e).abs().sum() > 0 else float("nan")
        print(f"{lab:28} {dl.median():+9.4f} {int((dl > 0).sum()):8d}/{len(d)} "
              f"{b:10d}/{int(ok.sum())} {ps:8.3f} {pw:8.4f}")
    d.to_csv("results/roofclf_cell_level_folds.csv", index=False)
    print("\nwrote results/roofclf_cell_level_folds.csv")


if __name__ == "__main__":
    main()
