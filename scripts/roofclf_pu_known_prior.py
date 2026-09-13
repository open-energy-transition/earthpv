#!/usr/bin/env python
"""Train roofclf against the register's per-municipality COUNTS, not its coordinates.

Step 1 showed that MaStR's geolocated units make a better classifier and a worse capacity
estimate, because coordinates exist only at and above 30 kWp: 6.9 of the 49.0 GWp below the
floor. The labels and the estimand disagree.

Counts do not have that problem. MaStR publishes exact rooftop unit counts for all 11,024
Gemeinden, 4,411,015 units covering every band including the 4.13M sub-30 kWp units that carry
no coordinates at all. That is a **known class prior per municipality**: we do not know WHICH
buildings carry PV, but we know exactly HOW MANY do.

That turns this into positive-unlabelled learning with a known prior. Each building gets a soft
target:

* a labelled positive (a register coordinate matched it) keeps y = 1,
* every unlabelled building in municipality m gets y = w_m, the residual positive rate among
  the unlabelled there: (N_true_m - n_labelled_m) / (N_buildings_m - n_labelled_m).

Fitting cross-entropy against soft targets is then the standard treatment, and it supervises
the sub-30 kWp population that no coordinate can reach.

**The prior is used in training only.** Evaluation is grouped by municipality: a held-out
Gemeinde's count is used as truth, never as an input, so the fitted model must generalise to
municipalities whose counts it has not seen. Without that split the exercise would be circular,
since forcing predicted counts to match known counts makes the municipal total exact by
construction.

**A municipality only counts if the scored cells cover it.** N_true_m is the whole
municipality's unit count, so a partly covered one pairs a whole-municipality numerator with a
partial denominator and inflates w_m.
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
log = logging.getLogger("pu-prior")

EQ_AREA = "EPSG:3035"


def fit_logistic_soft(X: np.ndarray, y_soft: np.ndarray, l2: float = 1.0) -> dict:
    """L2-regularised logistic regression against soft targets in [0, 1].

    Same shape as `roofclf.fit_logistic` (standardised features, unpenalised intercept) so the
    result is a drop-in for `roofclf.predict_proba`; it differs only in accepting a fractional
    target, which is what a known class prior produces for an unlabelled row.
    """
    from scipy.optimize import minimize

    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.hstack([(X - mu) / sd, np.ones((len(X), 1))])

    def nll(w):
        z = Z @ w
        ll = np.sum(y_soft * z - np.logaddexp(0.0, z))
        pen = l2 * np.sum(w[:-1] ** 2)
        g = Z.T @ (1.0 / (1.0 + np.exp(-z)) - y_soft)
        g[:-1] += 2 * l2 * w[:-1]
        return -ll + pen, g

    res = minimize(nll, np.zeros(Z.shape[1]), jac=True, method="L-BFGS-B",
                   options={"maxiter": 500})
    return {"w": res.x, "mu": mu, "sd": sd, "converged": bool(res.success)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="data/roofclf_germany_mastr/buildings.geoparquet")
    ap.add_argument("--gemeinden", default="data/calibration/vg250_gem.parquet")
    ap.add_argument("--units", default="data/calibration/mastr_rooftop_units_by_ags.parquet")
    ap.add_argument("--mastr", default="data/calibration/mastr_gemeinden.parquet")
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--labels-dir", default="data/labels/germany_mastr")
    ap.add_argument("--truth-col", default="kw_rooftop_le100")
    ap.add_argument("--min-coverage", type=float, default=0.98)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--out", default="results/germany_roofclf_pu_prior.json")
    args = ap.parse_args()

    from earthpv.roofclf import MODEL_FEATURES, design_matrix, fit_logistic, predict_proba

    feats = list(MODEL_FEATURES)
    t = gpd.read_parquet(args.table)
    log.info("table: %d buildings, %d labelled positives", len(t), int(t.has_pv.sum()))

    cells = {p.name.split("_calib_")[0][3:] for p in Path(args.labels_dir).glob("*_boundary.geojson")}
    grid = gpd.read_parquet(args.grid).to_crs(EQ_AREA)
    covered = grid[grid.cell.isin(cells)].geometry.union_all()

    gem = gpd.read_parquet(args.gemeinden).to_crs(EQ_AREA)
    gem["ags"] = gem.ags.astype(str).str.zfill(8)
    gem = gem[gem.geometry.intersects(covered)].reset_index(drop=True)
    gem["covered_frac"] = gem.geometry.intersection(covered).area / gem.geometry.area.clip(lower=1)
    keep = gem[gem["covered_frac"] >= args.min_coverage][["ags", "geometry"]].reset_index(drop=True)
    log.info("Gemeinden fully covered by the labelled cells: %d", len(keep))

    tm = t.to_crs(EQ_AREA)
    pts = gpd.GeoDataFrame(t.drop(columns="geometry").assign(_i=np.arange(len(t))),
                           geometry=tm.geometry.representative_point(), crs=EQ_AREA)
    j = gpd.sjoin(pts[["_i", "geometry"]], keep, how="inner", predicate="within")
    t = t.iloc[j["_i"].to_numpy()].copy()
    t["ags"] = j["ags"].to_numpy()
    log.info("buildings inside fully covered Gemeinden: %d", len(t))

    units = pd.read_parquet(args.units).set_index("ags").n_rooftop_units
    g = t.groupby("ags").agg(n_bldg=("roof_area_m2", "size"), n_lab=("has_pv", "sum"))
    g["n_true"] = g.index.map(units).fillna(0.0)
    # Residual positive rate among the unlabelled: the whole point of the prior.
    g["w"] = ((g.n_true - g.n_lab) / (g.n_bldg - g.n_lab).clip(lower=1)).clip(0.0, 1.0)
    log.info("prior w: median %.4f, p90 %.4f; register units %d vs labelled %d",
             g.w.median(), g.w.quantile(0.9), int(g.n_true.sum()), int(g.n_lab.sum()))

    t["w_m"] = t.ags.map(g.w).fillna(0.0).to_numpy()
    y_lab = t.has_pv.to_numpy(float)
    y_soft = np.where(y_lab > 0, 1.0, t.w_m.to_numpy())
    X = design_matrix(t, feats)

    ags_arr = np.array(sorted(t.ags.unique()))
    rng = np.random.default_rng(args.seed)
    rng.shuffle(ags_arr)
    fold_of = {a: i % args.folds for i, a in enumerate(ags_arr)}
    fold = t.ags.map(fold_of).to_numpy()

    preds = {}
    for name, target in (("pu_known_prior", y_soft), ("labels_only", y_lab)):
        oof = np.zeros(len(t))
        for f in range(args.folds):
            tr, te = fold != f, fold == f
            m = (fit_logistic_soft(X[tr], target[tr]) if name == "pu_known_prior"
                 else fit_logistic(X[tr], target[tr]))
            oof[te] = predict_proba(m, X[te])
        preds[name] = oof
        log.info("%s: out-of-fold predictions done", name)

    mastr = pd.read_parquet(args.mastr)
    mastr["ags"] = mastr.ags.astype(str).str.zfill(8)
    truth = mastr.set_index("ags")[args.truth_col]
    from scipy.stats import spearmanr
    out = {"n_buildings": int(len(t)), "n_gemeinden": int(t.ags.nunique()),
           "n_labelled_positives": int(y_lab.sum()),
           "register_units_in_scope": int(g.n_true.sum()),
           "median_prior_w": round(float(g.w.median()), 5),
           "estimators": {}}

    def _score(name, credited):
        d = pd.DataFrame({"ags": t.ags.to_numpy(), "x": credited}).groupby("ags").x.sum()
        d = pd.DataFrame({"x": d, "truth": d.index.map(truth)}).dropna()
        d = d[(d.x > 0) & (d.truth > 0)]
        pred = d.x * (d.truth.sum() / d.x.sum())
        out["estimators"][name] = {
            "n": int(len(d)),
            "median_municipal_abs_pct_err": round(
                float((np.abs(pred - d.truth) / d.truth).median() * 100), 1),
            "spearman": round(float(spearmanr(d.x, d.truth)[0]), 4),
            "kwp_per_m2": round(float(d.truth.sum() / d.x.sum()), 5),
        }

    roof = t.roof_area_m2.to_numpy()
    _score("pu_known_prior", roof * preds["pu_known_prior"])
    _score("labels_only", roof * preds["labels_only"])
    _score("roof_area_baseline", roof)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\n{out['n_buildings']:,} buildings, {out['n_gemeinden']:,} Gemeinden, "
          f"{out['register_units_in_scope']:,} register units vs "
          f"{out['n_labelled_positives']:,} labelled")
    print(f"\n{'estimator':<24}{'medAPE%':>9}{'rho':>8}{'kWp/m2':>10}{'n':>7}")
    for k, v in out["estimators"].items():
        print(f"{k:<24}{v['median_municipal_abs_pct_err']:>9.1f}{v['spearman']:>8.3f}"
              f"{v['kwp_per_m2']:>10.4f}{v['n']:>7}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
