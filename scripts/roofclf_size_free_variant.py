#!/usr/bin/env python
"""Does taking roof area OUT of roofclf let it explain what roof area cannot?

Measured on 9,674 German municipalities: roof area alone explains 61% of municipal capacity
variance in log space, adoption intensity varies 8.5x from the 5th to the 95th percentile, and
the correlation between roofclf's credited area and the residual of a roof-area-only fit is
**+0.007**. roofclf adds nothing at municipality level that roof area did not already carry.

The suspected cause is that `log_roof_area` is roofclf's strongest single feature, so
`sum(p * roof_area)` is close to a monotone function of `sum(roof_area)` and the estimator
collapses onto its own baseline. Germany's ablation says spectral-only still reaches 0.789 AUC,
so the panel signal exists; the question is whether it is being swamped.

This fits the same model on three feature sets -- with size, without size, spectral only --
and scores each the same way. The decisive column is not AUC but `corr_with_residual`: whether
the estimator carries information the roof-area baseline lacks.

Training uses the register-count prior (the best supervision found for Germany), grouped by
municipality so a held-out Gemeinde's count is never an input.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("size-free")

EQ_AREA = "EPSG:3035"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="/home/tobi/earthpv_data/roofclf_confirm/buildings.geoparquet")
    ap.add_argument("--labels-dir", default="data/labels/germany_confirm")
    ap.add_argument("--gemeinden", default="data/calibration/vg250_gem.parquet")
    ap.add_argument("--units", default="data/calibration/mastr_rooftop_units_by_ags.parquet")
    ap.add_argument("--mastr", default="data/calibration/mastr_gemeinden.parquet")
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--truth-col", default="kw_rooftop_le100")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--out", default="results/germany_roofclf_size_free.json")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from roofclf_pu_known_prior import fit_logistic_soft

    from earthpv.roofclf import (MODEL_FEATURES, SPECTRAL_FEATURES, design_matrix,
                                 predict_proba)
    from scipy.stats import spearmanr

    t = gpd.read_parquet(args.table)
    cells = {p.name.split("_calib_")[0][3:]
             for p in Path(args.labels_dir).glob("*_boundary.geojson")}
    grid = gpd.read_parquet(args.grid).to_crs(EQ_AREA)
    covered = grid[grid.cell.isin(cells)].geometry.union_all()
    gem = gpd.read_parquet(args.gemeinden).to_crs(EQ_AREA)
    gem["ags"] = gem.ags.astype(str).str.zfill(8)
    gem = gem[gem.geometry.intersects(covered)].reset_index(drop=True)
    gem["covered_frac"] = gem.geometry.intersection(covered).area / gem.geometry.area.clip(lower=1)
    keep = gem[gem["covered_frac"] >= 0.98][["ags", "geometry"]].reset_index(drop=True)

    tm = t.to_crs(EQ_AREA)
    pts = gpd.GeoDataFrame({"_i": np.arange(len(t))},
                           geometry=tm.geometry.representative_point(), crs=EQ_AREA)
    j = gpd.sjoin(pts, keep, how="inner", predicate="within")
    t = t.iloc[j["_i"].to_numpy()].copy()
    t["ags"] = j["ags"].to_numpy()
    log.info("%d buildings across %d fully covered Gemeinden", len(t), t.ags.nunique())

    units = pd.read_parquet(args.units).set_index("ags").n_rooftop_units
    g = t.groupby("ags").agg(n_bldg=("roof_area_m2", "size"), n_lab=("has_pv", "sum"))
    g["n_true"] = g.index.map(units).fillna(0.0)
    g["w"] = ((g.n_true - g.n_lab) / (g.n_bldg - g.n_lab).clip(lower=1)).clip(0.0, 1.0)
    y_lab = t.has_pv.to_numpy(float)
    y_soft = np.where(y_lab > 0, 1.0, t.ags.map(g.w).fillna(0.0).to_numpy())

    ags_arr = np.array(sorted(t.ags.unique()))
    rng = np.random.default_rng(args.seed)
    rng.shuffle(ags_arr)
    fold = t.ags.map({a: i % args.folds for i, a in enumerate(ags_arr)}).to_numpy()

    mastr = pd.read_parquet(args.mastr)
    mastr["ags"] = mastr.ags.astype(str).str.zfill(8)
    truth_by_ags = mastr.set_index("ags")[args.truth_col]
    roof = t.roof_area_m2.to_numpy()

    # The roof-area-only baseline, and the residual every variant is trying to explain.
    base = pd.DataFrame({"ags": t.ags.to_numpy(), "roof": roof}).groupby("ags").roof.sum()
    base = pd.DataFrame({"roof": base, "truth": base.index.map(truth_by_ags)}).dropna()
    base = base[(base.roof > 0) & (base.truth > 0)]
    lr, lt = np.log10(base.roof), np.log10(base.truth)
    resid = lt - np.polyval(np.polyfit(lr, lt, 1), lr)
    base_pred = base.roof * (base.truth.sum() / base.roof.sum())
    base_ape = float((np.abs(base_pred - base.truth) / base.truth).median() * 100)
    log.info("roof-area baseline: %d Gemeinden, median error %.1f%%, log-log r %.3f",
             len(base), base_ape, float(np.corrcoef(lr, lt)[0, 1]))

    variants = {
        "with_size (current)": list(MODEL_FEATURES),
        "no_size": [f for f in MODEL_FEATURES if f != "log_roof_area"],
        "spectral_only": list(SPECTRAL_FEATURES),
    }
    out = {"n_buildings": int(len(t)), "n_gemeinden": int(len(base)),
           "roof_area_baseline": {"median_municipal_abs_pct_err": round(base_ape, 1),
                                  "spearman": round(float(spearmanr(base.roof, base.truth)[0]), 4)},
           "variants": {}}

    for name, feats in variants.items():
        X = design_matrix(t, feats)
        oof = np.zeros(len(t))
        for f in range(args.folds):
            tr, te = fold != f, fold == f
            oof[te] = predict_proba(fit_logistic_soft(X[tr], y_soft[tr]), X[te])
        cred = pd.DataFrame({"ags": t.ags.to_numpy(), "x": roof * oof}).groupby("ags").x.sum()
        d = pd.DataFrame({"x": cred, "truth": cred.index.map(truth_by_ags)}).dropna()
        d = d[(d.x > 0) & (d.truth > 0)]
        pred = d.x * (d.truth.sum() / d.x.sum())
        common = d.index.intersection(base.index)
        r_resid = float(np.corrcoef(np.log10(d.loc[common, "x"]), resid.loc[common])[0, 1])
        out["variants"][name] = {
            "n": int(len(d)),
            "median_municipal_abs_pct_err": round(
                float((np.abs(pred - d.truth) / d.truth).median() * 100), 1),
            "spearman": round(float(spearmanr(d.x, d.truth)[0]), 4),
            "corr_with_roof_area_residual": round(r_resid, 4),
        }
        log.info("%s: medAPE %.1f%%, rho %.3f, corr with residual %+.4f", name,
                 out["variants"][name]["median_municipal_abs_pct_err"],
                 out["variants"][name]["spearman"], r_resid)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\n{out['n_buildings']:,} buildings, {out['n_gemeinden']:,} municipalities")
    print(f"\n{'variant':<22}{'medAPE%':>9}{'rho':>8}{'corr w/ residual':>19}")
    print(f"{'roof area (baseline)':<22}{base_ape:>9.1f}"
          f"{out['roof_area_baseline']['spearman']:>8.3f}{'--':>19}")
    for k, v in out["variants"].items():
        print(f"{k:<22}{v['median_municipal_abs_pct_err']:>9.1f}{v['spearman']:>8.3f}"
              f"{v['corr_with_roof_area_residual']:>+19.4f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
