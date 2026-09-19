"""Two more ways to aim at the features the classifier actually leans on.

  1. MEDOID compositing instead of a band-wise median. `annual_composite` medians each band
     independently, so a pixel's spectrum can be assembled from different dates and is one
     no scene ever observed. That is harmless per band and not harmless for a RATIO, and
     the model's largest coefficients are ratios. The medoid takes one real date's whole
     spectrum per pixel. Needs a table rebuilt from the saved scene stacks.

  2. CONTEXT-RELATIVE spectral features. `local_zscore` re-centres a building against its
     own quadrat or cell, and ships applied to `brightness` alone -- one feature of fifteen.
     Extending it to all of them targets transfer rather than in-sample skill. Computed
     from the existing table, so no rebuild.

Both are priced paired per leave-one-quadrat-out fold against the shipped feature set, with
the ranking and aggregate metrics side by side for the reason the last run established:
they can disagree.

    pixi run python scripts/run_medoid_context_ablation.py
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv import overture
from earthpv.roofclf import (CONTEXT_FEATURES, L2, MODEL_FEATURES, _subset_matrix,
                             add_context_features, auc, auc_within_size, building_table,
                             discover_quadrats, fit_logistic, predict_proba)

log = logging.getLogger("medoid_context")
EXCLUDE = "kalat_rural_calib_3km"


def folds(t: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    rows = []
    for name in sorted(t.quadrat.unique()):
        te = (t.quadrat == name).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2:
            continue
        m = fit_logistic(_subset_matrix(t[tr], feats), t.loc[tr, "has_pv"].to_numpy(float), L2)
        p = predict_proba(m, _subset_matrix(t[te], feats))
        y = t.loc[te, "has_pv"].to_numpy()
        roof = t.loc[te, "roof_area_m2"].to_numpy()
        rows.append({"quadrat": name, "auc": auc(y, p),
                     "ws": auc_within_size(y, p, roof)[0],
                     "rate": float(np.mean(p)), "base_rate": float(y.mean())})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--baseline", type=Path,
                    default=Path("data/roofclf_temporal_unmix/buildings.geoparquet"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--seg-prob-dir", type=Path,
                    default=Path("data/predictions_pk16085/pakistan/prob"))
    ap.add_argument("--frac-prob-dir", type=Path,
                    default=Path("data/predictions_frac_pk_v2/pakistan/prob"))
    ap.add_argument("--medoid-out", type=Path, default=Path("data/roofclf_medoid"))
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_medoid_context.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    _, cfg = resolve_aoi(args.aoi, Settings.load())
    iso3 = _iso3_for(cfg)
    quadrats = [q for q in sorted(discover_quadrats(args.labels_dir)) if q != EXCLUDE]

    base = gpd.read_parquet(args.baseline)
    base = add_context_features(base)
    log.info("baseline table %d rows, %d quadrats", len(base), base.quadrat.nunique())

    args.medoid_out.mkdir(parents=True, exist_ok=True)
    dst = args.medoid_out / "buildings.geoparquet"
    if dst.exists():
        med = gpd.read_parquet(dst)
        log.info("reusing medoid table %s (%d rows)", dst, len(med))
    else:
        con = overture.connect()
        t0 = time.time()
        parts = [building_table(n, iso3, args.composites, args.seg_prob_dir,
                                args.frac_prob_dir, args.labels_dir, con,
                                parcel_label=True, preprocess="medoid") for n in quadrats]
        med = gpd.GeoDataFrame(pd.concat([p for p in parts if not p.empty], ignore_index=True),
                               geometry="geometry", crs="EPSG:4326")
        med.to_parquet(dst)
        log.info("medoid table %d rows, %.0fs", len(med), time.time() - t0)
    med = add_context_features(med)

    ctx = [c for c in CONTEXT_FEATURES if c in base.columns]
    size_only = ["log_roof_area", "bf_confidence"]
    runs = {
        "baseline": (base, list(MODEL_FEATURES)),
        "medoid": (med, list(MODEL_FEATURES)),
        "plus_context": (base, list(MODEL_FEATURES) + ctx),
        "context_only": (base, size_only + ctx),
        "medoid_plus_context": (med, list(MODEL_FEATURES) + ctx),
    }
    res = {k: folds(t, f) for k, (t, f) in runs.items()}
    for k, d in res.items():
        log.info("%-20s auc %.4f  within-size %.4f", k, d.auc.median(), d.ws.median())

    from scipy import stats
    b = res["baseline"]
    out = {"n_folds": int(len(b)), "medians": {}, "vs_baseline": {}}
    for k, d in res.items():
        ok = d.base_rate > 0
        err = (d.loc[ok, "rate"] - d.loc[ok, "base_rate"]).abs()
        out["medians"][k] = {"auc": round(float(d.auc.median()), 4),
                             "within_size": round(float(d.ws.median()), 4),
                             "median_abs_rate_err": round(float(err.median()), 4)}
    for k, d in res.items():
        if k == "baseline":
            continue
        m = b.merge(d, on="quadrat", suffixes=("_b", "_v"))
        e = {}
        for lab, col in (("auc", "auc"), ("ws", "ws")):
            delta = m[f"{col}_v"] - m[f"{col}_b"]
            better = int((delta > 0).sum())
            worse = int((delta < 0).sum())
            e[f"delta_{lab}_median"] = round(float(delta.median()), 4)
            e[f"delta_{lab}_iqr"] = [round(float(delta.quantile(.25)), 4),
                                     round(float(delta.quantile(.75)), 4)]
            e[f"{lab}_folds_better"] = better
            e[f"{lab}_sign_p"] = round(
                float(stats.binomtest(better, max(better + worse, 1), 0.5).pvalue), 4)
        out["vs_baseline"][k] = e
        m.to_csv(f"results/roofclf_medoid_context_{k}_folds.csv", index=False)

    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
