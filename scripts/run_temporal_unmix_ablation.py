"""Price the temporal-unmixing block, and test the condition it was predicted to need.

Two questions, and the second is the point:

1. Does adding the damping block to roofclf help? Leave-one-quadrat-out, paired per fold
   against the shipped feature set, on one table so nothing but the feature list changes.

2. Does it help WHERE IT SHOULD? The estimator divides a pixel's temporal spread by its
   local background's, so it can only work where the background actually moves relative to
   a roof. `scripts/pv_temporal_invariance.py` measures that per quadrat as
   `open_over_roof_vis`. The prediction, registered before the run: the per-fold gain rises
   with it. A flat relationship means the block carries nothing even where it is
   identifiable, which is a stronger negative than a pooled null.

    pixi run python scripts/run_temporal_unmix_ablation.py --aoi pakistan
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
from earthpv.preprocess import TEMPORAL_UNMIX_COMPACT, TEMPORAL_UNMIX_FEATURES
from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             building_table, discover_quadrats, fit_logistic, predict_proba)

log = logging.getLogger("temporal_unmix_ablation")
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
        rows.append({"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum()),
                     "auc": auc(y, p), "auc_ws": auc_within_size(y, p, roof)[0]})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--seg-prob-dir", type=Path,
                    default=Path("data/predictions_pk16085/pakistan/prob"))
    ap.add_argument("--frac-prob-dir", type=Path,
                    default=Path("data/predictions_frac_pk_v2/pakistan/prob"))
    ap.add_argument("--out", type=Path, default=Path("data/roofclf_temporal_unmix"))
    ap.add_argument("--invariance", type=Path,
                    default=Path("results/pv_temporal_invariance.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    _, cfg = resolve_aoi(args.aoi, Settings.load())
    iso3 = _iso3_for(cfg)
    quadrats = [q for q in sorted(discover_quadrats(args.labels_dir)) if q != EXCLUDE]

    args.out.mkdir(parents=True, exist_ok=True)
    dst = args.out / "buildings.geoparquet"
    if dst.exists():
        table = gpd.read_parquet(dst)
        log.info("reusing %s (%d rows)", dst, len(table))
    else:
        con = overture.connect()
        t0 = time.time()
        parts = [building_table(n, iso3, args.composites, args.seg_prob_dir,
                                args.frac_prob_dir, args.labels_dir, con,
                                parcel_label=True, temporal_unmix=True) for n in quadrats]
        table = gpd.GeoDataFrame(pd.concat([p for p in parts if not p.empty], ignore_index=True),
                                 geometry="geometry", crs="EPSG:4326")
        table.to_parquet(dst)
        log.info("built %d rows, %d quadrats, %.0fs", len(table), table.quadrat.nunique(),
                 time.time() - t0)

    have = [c for c in TEMPORAL_UNMIX_COMPACT if c in table.columns]
    if len(have) < len(TEMPORAL_UNMIX_COMPACT):
        raise SystemExit(f"table is missing damping columns: {have}")
    full = [c for c in TEMPORAL_UNMIX_FEATURES if c in table.columns]

    # Damping is NaN where the ratio was not computable (a still background, or too few
    # cloud-free looks). That is only 0.2% of rows nationally but 41% of one quadrat, and
    # a single NaN poisons a logistic fit -- every fold training on that quadrat returned
    # NaN coefficients. Drop those rows ONCE, for every feature set alike, so the four
    # comparisons stay paired on identical rows rather than each seeing a different table.
    finite = np.isfinite(table[full].to_numpy(dtype="float64")).all(axis=1)
    dropped = int((~finite).sum())
    log.info("dropping %d rows (%.2f%%) with an incomputable damping ratio; worst quadrat "
             "%s at %.0f%%", dropped, 100 * dropped / len(table),
             table.loc[~finite, "quadrat"].value_counts().idxmax() if dropped else "-",
             100 * table.assign(b=~finite).groupby("quadrat").b.mean().max())
    table = table[finite].reset_index(drop=True)

    base = folds(table, list(MODEL_FEATURES))
    comp = folds(table, list(MODEL_FEATURES) + have)
    fl = folds(table, list(MODEL_FEATURES) + full)
    only = folds(table, ["log_roof_area", "bf_confidence"] + have)
    d = base.merge(comp, on="quadrat", suffixes=("_base", "_tu"))
    d = d.merge(fl[["quadrat", "auc", "auc_ws"]].rename(
        columns={"auc": "auc_tufull", "auc_ws": "auc_ws_tufull"}), on="quadrat")
    d = d.merge(only[["quadrat", "auc", "auc_ws"]].rename(
        columns={"auc": "auc_tuonly", "auc_ws": "auc_ws_tuonly"}), on="quadrat")
    d["delta"] = d.auc_tu - d.auc_base
    d["delta_ws"] = d.auc_ws_tu - d.auc_ws_base

    from scipy import stats
    summary = {
        "n_folds": int(len(d)),
        "n_rows": int(len(table)),
        "n_rows_dropped_nan": dropped,
        "median_auc_base": round(float(d.auc_base.median()), 4),
        "median_auc_plus_unmix": round(float(d.auc_tu.median()), 4),
        "median_auc_plus_unmix_full": round(float(d.auc_tufull.median()), 4),
        "median_auc_unmix_only": round(float(d.auc_tuonly.median()), 4),
        "median_ws_base": round(float(d.auc_ws_base.median()), 4),
        "median_ws_plus_unmix": round(float(d.auc_ws_tu.median()), 4),
        "median_ws_unmix_only": round(float(d.auc_ws_tuonly.median()), 4),
    }
    for lab, col in (("auc", "delta"), ("ws", "delta_ws")):
        better = int((d[col] > 0).sum())
        worse = int((d[col] < 0).sum())
        summary[f"delta_{lab}_median"] = round(float(d[col].median()), 4)
        summary[f"delta_{lab}_iqr"] = [round(float(d[col].quantile(.25)), 4),
                                       round(float(d[col].quantile(.75)), 4)]
        summary[f"{lab}_folds_better"] = better
        summary[f"{lab}_sign_p"] = round(
            float(stats.binomtest(better, max(better + worse, 1), 0.5).pvalue), 4)

    # The pre-registered conditional test.
    if args.invariance.exists():
        inv = {r["quadrat"]: r for r in json.loads(args.invariance.read_text())["per_quadrat"]}
        d["open_over_roof"] = [inv.get(q, {}).get("open_over_roof_vis", np.nan)
                               for q in d.quadrat]
        ok = d.open_over_roof.notna()
        if ok.sum() >= 6:
            for lab, col in (("auc", "delta"), ("ws", "delta_ws")):
                rho, p = stats.spearmanr(d.loc[ok, "open_over_roof"], d.loc[ok, col])
                summary[f"cond_{lab}_spearman"] = round(float(rho), 3)
                summary[f"cond_{lab}_p"] = round(float(p), 4)
            hi = d.loc[ok & (d.open_over_roof >= d.loc[ok, "open_over_roof"].median())]
            lo = d.loc[ok & (d.open_over_roof < d.loc[ok, "open_over_roof"].median())]
            summary["delta_ws_dynamic_half"] = round(float(hi.delta_ws.median()), 4)
            summary["delta_ws_still_half"] = round(float(lo.delta_ws.median()), 4)
            summary["n_conditioned"] = int(ok.sum())

    d.to_csv("results/roofclf_temporal_unmix_folds.csv", index=False)
    Path("results/roofclf_temporal_unmix.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
