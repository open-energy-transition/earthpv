#!/usr/bin/env python
"""Normalised contrast to PV-free neighbours, against the all-neighbour version.

The experiment behind docs/experiments.md's "PV-free neighbours only (2026-10-23)",
run on the production roofclf building table (`data/roofclf/buildings.geoparquet`).
Usage: `.pixi/envs/default/bin/python scripts/roofclf_pvfree_neighbour_contrast.py [k]`.

For each building, the k nearest buildings in its own quadrat that pass a reference
filter give a background median and robust sd per band. Contrast = x - median,
normalised contrast = (x - median) / robust_sd.

Reference filters:
  all       every neighbour (the register's 2026-09-19 measurement, d' 1.226 -> 0.904)
  oracle    neighbours with has_pv == 0 -- uses neighbour LABELS, an upper bound only
  score     neighbours below the deployment threshold on p_oof (deployable)
  score_lo  neighbours in the lowest half of their quadrat's p_oof (deployable, stricter)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from earthpv import roofclf as rc

K = int(sys.argv[1]) if len(sys.argv) > 1 else 50
POOL = 400                       # candidates searched to find K that pass a filter
THRESH = 0.2446                  # deployment threshold (summary.json)
BANDS = [f"{b}_mean" for b in rc.BAND_NAMES]

t = gpd.read_parquet(ROOT / "data" / "roofclf" / "buildings.geoparquet")
t = t.dropna(subset=BANDS + ["p_oof"]).reset_index(drop=True)
y = t.has_pv.to_numpy().astype(bool)
X = t[BANDS].to_numpy("float64")
print(f"{len(t)} buildings, {y.sum()} PV, k={K}")

filters = {"all": None, "oracle": None, "score": None, "score_lo": None}
med = {f: np.full_like(X, np.nan) for f in filters}
rsd = {f: np.full_like(X, np.nan) for f in filters}
nref = {f: np.zeros(len(t)) for f in filters}
radius = {f: np.full(len(t), np.nan) for f in filters}

for q, idx in t.groupby("quadrat").indices.items():
    sub = t.iloc[idx]
    pts = sub.geometry.representative_point()
    lat0 = float(pts.y.mean())
    xy = np.column_stack([pts.x.to_numpy() * 111320.0 * np.cos(np.radians(lat0)),
                          pts.y.to_numpy() * 110540.0])
    kk = min(POOL + 1, len(sub))
    d, j = cKDTree(xy).query(xy, k=kk)
    d, j = d[:, 1:], j[:, 1:]
    vals = X[idx]
    p = sub.p_oof.to_numpy()
    lo_cut = np.median(p)
    ok = {
        "all": np.ones(len(sub), bool),
        "oracle": ~sub.has_pv.to_numpy().astype(bool),
        "score": p < THRESH,
        "score_lo": p < lo_cut,
    }
    for f, keep in ok.items():
        passed = keep[j]                                  # (n, kk-1)
        rank = np.cumsum(passed, axis=1)
        sel = passed & (rank <= K)
        for i in range(len(sub)):
            nb = j[i, sel[i]]
            if len(nb) < 10:
                continue
            v = vals[nb]
            m = np.median(v, axis=0)
            med[f][idx[i]] = m
            rsd[f][idx[i]] = 1.4826 * np.median(np.abs(v - m), axis=0)
            nref[f][idx[i]] = len(nb)
            radius[f][idx[i]] = d[i, sel[i]][-1]


def dprime(F, yy):
    """Mahalanobis separation, PV-free covariance (and pooled for comparison)."""
    ok = np.isfinite(F).all(1)
    F, yy = F[ok], yy[ok]
    dm = F[yy].mean(0) - F[~yy].mean(0)
    S0 = np.cov(F[~yy], rowvar=False)
    Sp = (np.cov(F[~yy], rowvar=False) * (~yy).sum() + np.cov(F[yy], rowvar=False) * yy.sum()) / len(yy)
    return float(np.sqrt(dm @ np.linalg.solve(S0, dm))), float(np.sqrt(dm @ np.linalg.solve(Sp, dm))), int(ok.sum())


def band_dprime(F, yy):
    ok = np.isfinite(F).all(1)
    F, yy = F[ok], yy[ok]
    sd0 = F[~yy].std(0)
    return (F[yy].mean(0) - F[~yy].mean(0)) / sd0, sd0


raw_d, raw_dp, n = dprime(X, y)
raw_bd, raw_sd = band_dprime(X, y)
print(f"\nraw bands: d' {raw_d:.3f} (PV-free cov)  {raw_dp:.3f} (pooled)  n={n}")
rows = [{"reference": "none (raw)", "form": "-", "dprime": raw_d, "dprime_pooled": raw_dp,
         "pvfree_sd_ratio_med": 1.0, "band_dprime_ratio_med": 1.0, "n": n,
         "median_ref_n": np.nan, "median_radius_m": np.nan}]
for f in filters:
    for form in ("delta", "z"):
        F = X - med[f] if form == "delta" else (X - med[f]) / np.where(rsd[f] > 0, rsd[f], np.nan)
        d0, dp, n = dprime(F, y)
        bd, sd = band_dprime(F, y)
        rows.append({
            "reference": f, "form": form, "dprime": d0, "dprime_pooled": dp,
            "pvfree_sd_ratio_med": float(np.median(sd / raw_sd)) if form == "delta" else np.nan,
            "band_dprime_ratio_med": float(np.median(bd / raw_bd)),
            "n": n, "median_ref_n": float(np.nanmedian(nref[f])),
            "median_radius_m": float(np.nanmedian(radius[f])),
        })
sep = pd.DataFrame(rows)
print(sep.round(3).to_string(index=False))

# Per-band detail for the oracle, delta form, to see where the separation lives.
bd_o, sd_o = band_dprime(X - med["oracle"], y)
bd_a, sd_a = band_dprime(X - med["all"], y)
print("\nper band d' (raw / all-nb delta / oracle delta), and PV-free sd ratio (all / oracle):")
for b, r0, r1, r2, s1, s2 in zip(BANDS, raw_bd, bd_a, bd_o, sd_a / raw_sd, sd_o / raw_sd):
    print(f"  {b:9s} {r0:+.3f} {r1:+.3f} {r2:+.3f}   sd {s1:.2f} {s2:.2f}")

# LOQO: add each contrast block to the shipped feature set.
for f in filters:
    for form in ("delta", "z"):
        F = X - med[f] if form == "delta" else (X - med[f]) / np.where(rsd[f] > 0, rsd[f], np.nan)
        for i, b in enumerate(rc.BAND_NAMES):
            t[f"{b}_{f}_{form}"] = F[:, i]
# A building with too few reference neighbours gets the quadrat-median fill (rare).
feat_cols = [c for c in t.columns if any(c.endswith(f"_{f}_{fm}") for f in filters for fm in ("delta", "z"))]
for c in feat_cols:
    t[c] = t[c].fillna(t.groupby("quadrat")[c].transform("median")).fillna(0.0)

blocks = {"shipped": list(rc.MODEL_FEATURES)}
for f in filters:
    for form in ("delta", "z"):
        blocks[f"+{f}_{form}"] = list(rc.MODEL_FEATURES) + [f"{b}_{f}_{form}" for b in rc.BAND_NAMES]
blocks["size+oracle_z_only"] = ["log_roof_area", "bf_confidence"] + [f"{b}_oracle_z" for b in rc.BAND_NAMES]
blocks["size+score_z_only"] = ["log_roof_area", "bf_confidence"] + [f"{b}_score_z" for b in rc.BAND_NAMES]

res = []
for label, feats in blocks.items():
    for q in t.quadrat.unique():
        te = (t.quadrat == q).to_numpy()
        tr = ~te
        Xtr = rc._subset_matrix(t[tr], feats)
        Xte = rc._subset_matrix(t[te], feats)
        m = rc.fit_logistic(Xtr, t.loc[tr, "has_pv"].to_numpy(float), rc.L2)
        p = rc.predict_proba(m, Xte)
        yy = t.loc[te, "has_pv"].to_numpy()
        w, _ = rc.auc_within_size(yy, p, t.loc[te, "roof_area_m2"].to_numpy())
        res.append({"block": label, "quadrat": q, "auc": rc.auc(yy, p), "auc_within_size": w})
res = pd.DataFrame(res)
base = res[res.block == "shipped"].set_index("quadrat")
out = []
for label, g in res.groupby("block", sort=False):
    g = g.set_index("quadrat")
    dw = (g.auc_within_size - base.auc_within_size).dropna()
    wins = int((dw > 0).sum())
    out.append({"block": label, "auc": g.auc.median(), "auc_within_size": g.auc_within_size.median(),
                "d_within_median": dw.median(), "folds_better": f"{wins}/{len(dw)}",
                "sign_p": binomtest(wins, len(dw)).pvalue if label != "shipped" else np.nan})
out = pd.DataFrame(out)
print(f"\nLOQO, {t.quadrat.nunique()} folds:")
print(out.round(4).to_string(index=False))
sep.to_csv(ROOT / f"results/roofclf_pvfree_neighbour_contrast_sep_k{K}.csv", index=False)
res.to_csv(ROOT / f"results/roofclf_pvfree_neighbour_contrast_folds_k{K}.csv", index=False)
