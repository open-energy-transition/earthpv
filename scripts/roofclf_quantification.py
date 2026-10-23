"""The capacity half of roofclf is a QUANTIFICATION problem; test the quantifiers.

`sub400_capacity` and `roofclf_ge400_capacity` price a cell as flagged roof area times the
calibration quadrats' (true PV area / flagged roof area), per stratum -- coverage ratio over
area recall, refit together. That is "classify and count" (CC) with a ratio calibration:
threshold the score, count what crosses it, rescale by how the count behaved where truth is
known. The machine-learning literature on estimating class prevalence in a new population
(Forman 2008; Bella et al. 2010; Saerens, Latinne & Decaestecker 2002; Gonzalez et al. 2017
for a review) found CC to be the weakest of the standard estimators, specifically under
PRIOR SHIFT -- a population whose base rate differs from training while the class-
conditional feature distributions do not -- which is this register's own diagnosis of
roofclf: "ranking transfers, absolute rates do not" (rate_ratio 0.28 to 4.41).

Every estimator here uses the SAME leave-one-quadrat-out scores (the shipped model's
out-of-fold `p_oof` by default, or a block from `roofclf_untapped_ablation.py`), and every
estimator is calibrated on the OTHER quadrats only, per roof-size band:

  null    roof area x (true PV area / roof area): no classifier at all
  cc      flagged roof area x (true PV area / flagged roof area), flags at the shipped
          precision-0.5 threshold -- the structure the capacity chain uses
  pcc     probability-weighted roof area in place of flagged roof area
  emq     pcc on posteriors re-estimated per quadrat by the EM prior adjustment of Saerens
          et al. (2002): iterate the quadrat's prevalence and Bayes-rescale every posterior to
          it until both agree. Under pure prior shift this recovers the new base rate.
  acc     the count adjusted by TPR and FPR measured on the other quadrats
          ((CC - FPR) / (TPR - FPR), per band), times the band's mean PV area per PV roof
  pacc    the same with mean posteriors in place of rates (probabilistic ACC)

Reported per estimator: median and IQR of |estimate - truth| / truth over the quadrats
with PV, pooled ratio, Spearman, and paired per-quadrat |log| error against `cc` (what
ships) and `pcc`. Truth is the parcel-label `pv_area_true_m2`.

    pixi run python scripts/roofclf_quantification.py
    pixi run python scripts/roofclf_quantification.py --block plus_d21m   # any ablation block
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from earthpv.sppi import _precision_threshold

log = logging.getLogger("quantification")
EDGES = (0.0, 50.0, 100.0, 200.0, 400.0, np.inf)
OOF = Path("/home/tobi/earthpv_data/roofclf_untapped/roofclf_untapped_oof.npz")


def emq(p: np.ndarray, prior_train: float, n_iter: int = 1000, tol: float = 1e-8) -> np.ndarray:
    """Saerens-Latinne-Decaestecker EM: posteriors re-estimated under a new class prior."""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    pi = prior_train
    for _ in range(n_iter):
        a, b = pi / prior_train, (1 - pi) / (1 - prior_train)
        pp = a * p / (a * p + b * (1 - p))
        new = float(pp.mean())
        if abs(new - pi) < tol:
            break
        pi = new
    return pp


def estimates(t: pd.DataFrame, s: np.ndarray) -> pd.DataFrame:
    roof, pv = t.roof_area_m2.to_numpy(), t.pv_area_true_m2.to_numpy()
    y = t.has_pv.to_numpy().astype(bool)
    q = t.quadrat.to_numpy()
    band = np.digitize(roof, EDGES[1:-1])
    thr = _precision_threshold(y, s, min_precision=0.5)
    flag = s >= thr
    # EM posteriors per quadrat, each against the prior of the quadrats its scores were
    # NOT fitted on (out-of-fold, so that is every other quadrat)
    em = np.empty_like(s)
    for name in np.unique(q):
        m = q == name
        em[m] = emq(s[m], float(y[~m].mean()))
    rows = []
    for name in np.unique(q):
        te = q == name
        r = {"quadrat": name, "truth": float(pv[te].sum()), "n": int(te.sum())}
        for k in ("null", "cc", "pcc", "emq", "acc", "pacc"):
            r[k] = 0.0
        for b in range(len(EDGES) - 1):
            o, tb = ~te & (band == b), te & (band == b)
            if not o.any() or not tb.any():
                continue
            pv_o = pv[o].sum()
            for k, w in (("null", np.ones_like(s)), ("cc", flag.astype(float)),
                         ("pcc", s), ("emq", em)):
                den = (w[o] * roof[o]).sum()
                if den > 0:
                    r[k] += (w[tb] * roof[tb]).sum() * pv_o / den
            yo = y[o]
            if yo.any() and (~yo).any():
                mean_pv_pos = pv[o][yo].mean()
                tpr, fpr = flag[o][yo].mean(), flag[o][~yo].mean()
                ptp, pfp = s[o][yo].mean(), s[o][~yo].mean()
                if tpr - fpr > 1e-3:
                    pi = np.clip((flag[tb].mean() - fpr) / (tpr - fpr), 0, 1)
                    r["acc"] += pi * tb.sum() * mean_pv_pos
                if ptp - pfp > 1e-3:
                    pi = np.clip((s[tb].mean() - pfp) / (ptp - pfp), 0, 1)
                    r["pacc"] += pi * tb.sum() * mean_pv_pos
        r["rate_true"] = float(y[te].mean())
        r["rate_pcc"] = float(s[te].mean())
        r["rate_emq"] = float(em[te].mean())
        rows.append(r)
    return pd.DataFrame(rows).set_index("quadrat")


def summary(e: pd.DataFrame) -> dict:
    ok = e.truth > 0
    out = {}
    for k in ("null", "cc", "pcc", "emq", "acc", "pacc"):
        err = (e.loc[ok, k] - e.loc[ok, "truth"]).abs() / e.loc[ok, "truth"]
        out[k] = {"median_abs_err": round(float(err.median()), 4),
                  "iqr": [round(float(err.quantile(.25)), 4), round(float(err.quantile(.75)), 4)],
                  "pooled_ratio": round(float(e.loc[ok, k].sum() / e.loc[ok, "truth"].sum()), 4),
                  "spearman": round(float(stats.spearmanr(e.loc[ok, k],
                                                          e.loc[ok, "truth"]).statistic), 4)}
    for ref in ("cc", "pcc"):
        a = np.abs(np.log(np.maximum(e.loc[ok, ref], 1.0) / e.loc[ok, "truth"]))
        for k in ("null", "cc", "pcc", "emq", "acc", "pacc"):
            if k == ref:
                continue
            b = np.abs(np.log(np.maximum(e.loc[ok, k], 1.0) / e.loc[ok, "truth"]))
            dl = (a - b).to_numpy()  # positive = k has the smaller error
            better = int((dl > 0).sum())
            out[k][f"vs_{ref}"] = {
                "better": f"{better}/{len(dl)}",
                "median_dlog": round(float(np.median(dl)), 4),
                "sign_p": round(float(stats.binomtest(better, int((dl != 0).sum())).pvalue), 4),
                "wilcoxon_p": round(float(stats.wilcoxon(dl).pvalue), 4)}
    rr = e[e.rate_true > 0]
    out["rate_error"] = {k: round(float((rr[f"rate_{k}"] - rr.rate_true).abs().median()), 4)
                         for k in ("pcc", "emq")}
    out["rate_spearman"] = {k: round(float(stats.spearmanr(rr[f"rate_{k}"],
                                                           rr.rate_true).statistic), 4)
                            for k in ("pcc", "emq")}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--block", default=None,
                    help="score from roofclf_untapped_ablation's OOF file instead of p_oof")
    ap.add_argument("--oof", type=Path, default=OOF)
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_quantification.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t = gpd.read_parquet(args.table).drop(columns="geometry").reset_index(drop=True)
    if args.block:
        z = np.load(args.oof, allow_pickle=True)
        if not (z["quadrat"] == t.quadrat.to_numpy()).all():
            raise SystemExit("OOF rows do not line up with the table")
        s = z[args.block]
    else:
        s = t.p_oof.to_numpy()
    e = estimates(t, s)
    out = {"score": args.block or "p_oof (shipped)", "summary": summary(e)}
    e.to_csv(args.out.with_name(args.out.stem + (f"_{args.block}" if args.block else "")
                                + "_by_quadrat.csv"))
    print(json.dumps(out, indent=2))
    if not args.block:
        args.out.write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
