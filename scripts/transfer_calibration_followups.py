"""Why the past epoch fails as a negative set, and what would work instead (Pakistan).

Runs after `transfer_calibration_pakistan_check.py`, from its cached outputs, and adds the
four measurements the 2026-10-20 register entry quotes:

1. Normalising the pre-boom epoch against today on the same buildings (median shift,
   median + IQR, quantile match per band), in case the raw failure was radiometric.
2. Propensity: how well each epoch's score predicts TODAY's PV. If the 2021 score does
   nearly as well as today's, the classifier recognises adopter-type roofs rather than
   panels, and the same roofs in the past are not negatives.
3. A strict threshold with no false-positive correction at all (pi = f / TPR_osm).
4. A simulated yes/no review of random flagged roofs as the level's calibration, with TPR
   and mean array area from OSM, at 100-800 reviews.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from earthpv import transfer_calibration as tc
from earthpv.local_source import composite_index
from earthpv.roofclf import (
    BAND_NAMES, L2, auc, design_matrix, epoch_feature_frame, fit_logistic, load_model,
    predict_proba,
)

COLS = [f"{b}_mean" for b in BAND_NAMES]


def band_means(t: gpd.GeoDataFrame, composites: Path, pre_layer: int, off: float) -> pd.DataFrame:
    comp = composite_index(str(composites), layers=pre_layer + 1)
    out = []
    for q in sorted(t["quadrat"].unique()):
        te = (t["quadrat"] == q).to_numpy()
        bu = gpd.GeoDataFrame({"area_m2": t.loc[te, "roof_area_m2"].to_numpy(),
                               "bf_confidence": t.loc[te, "bf_confidence"].to_numpy()},
                              geometry=t.loc[te].geometry.to_numpy(), crs=t.crs).to_crs("EPSG:4326")
        x0, y0, x1, y1 = bu.total_bounds
        arr, tr, crs = comp.read_window((x0 - 0.001, y0 - 0.001, x1 + 0.001, y1 + 0.001))
        f0, _ = epoch_feature_frame(bu, arr, tr, crs, 0)
        f1, _ = epoch_feature_frame(bu, arr, tr, crs, pre_layer, dn_offset=off)
        d = pd.DataFrame({"row": np.flatnonzero(te)})
        for c in COLS:
            d[f"cur_{c}"], d[f"pre_{c}"] = f0[c].to_numpy(), f1[c].to_numpy()
        out.append(d)
    return pd.concat(out).set_index("row").sort_index()


def derived(df: pd.DataFrame) -> pd.DataFrame:
    eps = 1e-6
    r, nir, sw = df["b04_mean"], df["b08_mean"], df["b11_mean"]
    df["ndvi"] = (nir - r) / (nir + r + eps)
    df["ndbi"] = (sw - nir) / (sw + nir + eps)
    df["brightness"] = df[COLS].mean(axis=1)
    df["swir_vis_ratio"] = sw / (df[["b02_mean", "b03_mean", "b04_mean"]].mean(axis=1) + eps)
    df["blue_red_ratio"] = df["b02_mean"] / (r + eps)
    return df


def normalise(cur: pd.DataFrame, pre: pd.DataFrame, how: str) -> pd.DataFrame:
    out = pre.copy()
    for c in COLS:
        x, y = pre[c], cur[c]
        ok = x.notna() & y.notna()
        if how == "median":
            out[c] = x + (y[ok].median() - x[ok].median())
        elif how == "median_iqr":
            a = ((y[ok].quantile(.75) - y[ok].quantile(.25))
                 / max(x[ok].quantile(.75) - x[ok].quantile(.25), 1e-6))
            out[c] = y[ok].median() + a * (x - x[ok].median())
        elif how == "quantile":
            qs = np.linspace(0.01, 0.99, 99)
            out[c] = np.interp(x, x[ok].quantile(qs), y[ok].quantile(qs))
    return out


def area_errors(est: pd.Series, truth: pd.Series) -> dict:
    ok = truth > 0
    return {"median_abs_error": round(float(((est - truth).abs() / truth)[ok].median()), 3),
            "pooled_ratio": round(float(est.sum() / truth.sum()), 3),
            "spearman": round(float(spearmanr(est, truth).statistic), 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calib-dir", type=Path, default=Path("data/roofclf"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--check-dir", type=Path, default=Path("results/transfer_calibration/pakistan_check"))
    ap.add_argument("--pre-layer", type=int, default=1)
    ap.add_argument("--pre-dn-offset", type=float, default=tc.PRE_BASELINE_DN_OFFSET)
    a = ap.parse_args()

    tg = gpd.read_parquet(a.calib_dir / "buildings.geoparquet")
    t = pd.DataFrame(tg.drop(columns="geometry"))
    _, feats = load_model(a.calib_dir / "model_full.json")
    thr = json.loads((a.calib_dir / "summary.json").read_text())["deployment_threshold"]
    pos = pd.read_parquet(a.check_dir / "osm_positives.parquet")
    pos = pos[pos["p"].notna()]
    pr = tc.positive_rates(tc.size_bin(pos["roof_area_m2"]), pos["p"], pos["pv_area_m2"], thr)
    out: dict = {"threshold": thr}

    bm_path = a.check_dir / f"quadrat_band_means_off{a.pre_dn_offset:.0f}.parquet"
    if not bm_path.exists():
        band_means(tg, a.composites, a.pre_layer, a.pre_dn_offset).to_parquet(bm_path)
    bm = pd.read_parquet(bm_path)
    if "row" in bm.columns:
        bm = bm.set_index("row").sort_index()
    y = t["has_pv"].to_numpy(float)
    models = {q: fit_logistic(design_matrix(t[t["quadrat"] != q], feats),
                              y[(t["quadrat"] != q).to_numpy()], L2)
              for q in sorted(t["quadrat"].unique())}

    # 1 + 2. Normalised pre-boom epochs, and how well each epoch predicts today's PV.
    out["normalisation"] = {}
    for how in ["none", "median", "median_iqr", "quantile"]:
        p_pre = np.full(len(t), np.nan)
        for q, m in models.items():
            te = (t["quadrat"] == q).to_numpy()
            rows = np.flatnonzero(te)
            cur = pd.DataFrame({c: bm.loc[rows, f"cur_{c}"].to_numpy() for c in COLS})
            pre = pd.DataFrame({c: bm.loc[rows, f"pre_{c}"].to_numpy() for c in COLS})
            pre = derived(normalise(cur, pre, how))
            pre["roof_area_m2"] = t.loc[te, "roof_area_m2"].to_numpy()
            pre["bf_confidence"] = t.loc[te, "bf_confidence"].to_numpy()
            ok = pre[COLS].notna().all(axis=1).to_numpy()
            p = np.full(len(pre), np.nan)
            p[ok] = predict_proba(m, design_matrix(pre[ok].reset_index(drop=True), feats))
            p_pre[te] = p
        d = t.assign(p_pre=p_pre)
        d = d[d["p_oof"].notna() & d["p_pre"].notna()]
        sub = d[d["roof_area_m2"] < 400]
        est, truth = {}, {}
        for q, g in sub.groupby("quadrat"):
            b = tc.size_bin(g["roof_area_m2"])
            e = tc.estimate(tc.bin_rates(b, g["p_oof"], thr), tc.bin_rates(b, g["p_pre"], thr), pr)
            est[q], truth[q] = e["pv_area_m2"].sum(skipna=True), g["pv_area_true_m2"].sum()
        neg = sub["has_pv"] == 0
        out["normalisation"][how] = {
            **area_errors(pd.Series(est), pd.Series(truth)),
            "flag_rate_current": round(float((sub["p_oof"] >= thr).mean()), 4),
            "flag_rate_pre": round(float((sub["p_pre"] >= thr).mean()), 4),
            "fpr_now_true": round(float((sub.loc[neg, "p_oof"] >= thr).mean()), 4),
            "auc_today_pv_current_score": round(auc(d["has_pv"], d["p_oof"]), 4),
            "auc_today_pv_pre_score": round(auc(d["has_pv"], d["p_pre"]), 4),
        }
        print(how, out["normalisation"][how], flush=True)

    sub = t[(t["roof_area_m2"] < 400) & t["p_oof"].notna()].copy()
    sub["bin"] = tc.size_bin(sub["roof_area_m2"])
    truth = sub.groupby("quadrat")["pv_area_true_m2"].sum()

    # 3. Strict thresholds, no false-positive correction.
    out["strict_threshold"] = {}
    for t_ in [0.2446, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85]:
        p_ = tc.positive_rates(tc.size_bin(pos["roof_area_m2"]), pos["p"], pos["pv_area_m2"], t_)
        est = sub.groupby("quadrat").apply(lambda g: (lambda c: (
            c["flag_rate"] * c["n"] / p_["tpr"] * p_["mean_pv_area_m2"]).sum())(
            tc.bin_rates(g["bin"], g["p_oof"], t_)))
        out["strict_threshold"][f"{t_:.2f}"] = area_errors(est, truth)
    print("strict threshold", out["strict_threshold"], flush=True)

    # 4. A yes/no review of random flagged roofs.
    sub["flag"] = sub["p_oof"] >= thr
    fl = sub[sub["flag"]]
    nflag = (sub.groupby(["quadrat", "bin"])["flag"].sum().unstack(fill_value=0)
             .reindex(columns=range(tc.N_SIZE_BINS), fill_value=0))

    def est_from(prec):
        return (nflag * (np.asarray(prec) / pr["tpr"].to_numpy()
                         * pr["mean_pv_area_m2"].to_numpy())).sum(axis=1)

    exact = fl.groupby("bin")["has_pv"].mean().reindex(range(tc.N_SIZE_BINS)).to_numpy()
    out["review"] = {"exact_precision": area_errors(est_from(exact), truth)}
    rng = np.random.default_rng(0)
    for n in [100, 200, 400, 800]:
        pooled, med = [], []
        for _ in range(300):
            prec = [fl.loc[fl["bin"] == b, "has_pv"].sample(
                n // tc.N_SIZE_BINS, replace=True, random_state=int(rng.integers(1e9))).mean()
                for b in range(tc.N_SIZE_BINS)]
            e = area_errors(est_from(prec), truth)
            pooled.append(e["pooled_ratio"])
            med.append(e["median_abs_error"])
        out["review"][f"n{n}"] = {
            "pooled_ratio_median": round(float(np.median(pooled)), 3),
            "pooled_ratio_90": [round(float(np.percentile(pooled, 5)), 3),
                                round(float(np.percentile(pooled, 95)), 3)],
            "median_abs_error": round(float(np.median(med)), 3)}
    print("review", out["review"], flush=True)
    (a.check_dir / "followups.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
