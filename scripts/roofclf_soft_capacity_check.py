"""Probability-weighted against thresholded pricing, in the capacity chain's own structure.

`roofclf_quantification.py` found that pricing roof area weighted by `p_roofclf` instead of
by a 0/1 flag at the precision-0.5 threshold halves the per-quadrat error of the predicted
true PV area (median 0.457 to 0.242, better in 20 of 29 quadrats, Wilcoxon p = 0.0065),
and that the thresholded estimator is no better than pricing every roof with no
classifier at all (0.477). That test used five fixed size bands. This one rebuilds the
shipped calibration exactly and changes only the weight:

  * coverage ratio per decile of FLAGGED roof size, area recall per decile of PV-CARRYING
    roof size (`sub400_capacity.coverage_ratio_by_size` / `area_recall_by_size`),
  * each fitted within two building-density strata of the calibration quadrats, median
    split, pooled fallback below 25 rows (`_stratify_by_density`),
  * fitted only on the rate_ratio-trusted quadrats, Mardan excluded
    (`select_calibrated_quadrats`),
  * estimate = sum over a quadrat's buildings of weight x roof area x coverage / recall.

Thresholded: weight = 1[p >= threshold]. Soft: weight = p, with the SAME bin edges (the
thresholded population's deciles) so only the weighting differs. Held out one quadrat at
a time: its own labels never enter the threshold, the trusted set, or either table. All 29
quadrats with mapped PV are scored, trusted or not, because deployment prices every cell.
Before any of that, the indicator-weighted tables are checked against the shipped
functions on the full trusted set and must match them exactly.

    pixi run python scripts/roofclf_soft_capacity_check.py
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
from earthpv.sub400_capacity import (AREA_RECALL_FLOOR, DEFAULT_COVERAGE_MIN_BIN_N,
                                     DEFAULT_COVERAGE_N_SIZE_BINS, DEFAULT_EXCLUDE,
                                     DEFAULT_RATIO_HI, DEFAULT_RATIO_LO, _density_band_edges,
                                     area_recall_by_size_and_density,
                                     coverage_ratio_by_size_and_density,
                                     quadrat_building_density_km2)

log = logging.getLogger("soft_capacity")
NB, MIN_N = DEFAULT_COVERAGE_N_SIZE_BINS, DEFAULT_COVERAGE_MIN_BIN_N


def _edges(x: np.ndarray) -> np.ndarray:
    e = np.unique(np.quantile(x, np.linspace(0.0, 1.0, NB + 1)))
    if len(e) < 3:
        e = np.array([x.min(), x.max()])
    e[0], e[-1] = -np.inf, np.inf
    return e


def _bin(e: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.clip(np.searchsorted(e, x, side="right") - 1, 0, len(e) - 2)


def size_tables(roof, pv, flag, w):
    """(coverage edges, coverage per bin, recall edges, recall per bin) for one quadrat set,
    `flag` fixing the bin edges and `w` the weights, mirroring the shipped fallbacks."""
    has = pv > 0
    ce = _edges(roof[flag]) if flag.any() else np.array([-np.inf, np.inf])
    cb = _bin(ce, roof)
    overall_c = (w * pv).sum() / max((w * roof).sum(), 1e-12)
    cov = np.empty(len(ce) - 1)
    for i in range(len(cov)):
        m = cb == i
        # the shipped test counts flagged buildings; the soft analogue counts their weight
        n = flag[m].sum() if np.array_equal(w, flag.astype(float)) else w[m].sum()
        den = (w[m] * roof[m]).sum()
        cov[i] = (w[m] * pv[m]).sum() / den if den and n >= MIN_N else overall_c
    re = _edges(roof[has])
    rb = _bin(re, roof)
    overall_r = (w * pv).sum() / pv.sum()
    rec = np.empty(len(re) - 1)
    for i in range(len(rec)):
        m = rb == i
        tot = pv[m].sum()
        r = (w[m] * pv[m]).sum() / tot if tot > 0 and (m & has).sum() >= MIN_N else overall_r
        rec[i] = max(r, AREA_RECALL_FLOOR)
    return ce, cov, re, rec


def stratified(d: pd.DataFrame, quads: list[str], qdens: pd.Series, flag, w):
    """Per density band (median split of `quads`' own densities, pooled fallback) tables."""
    sel = d.quadrat.isin(quads).to_numpy()
    roof, pv = d.roof_area_m2.to_numpy(), d.pv_area_true_m2.to_numpy()
    pooled = size_tables(roof[sel], pv[sel], flag[sel], w[sel])
    qd = qdens.loc[quads]
    edges = _density_band_edges(qd, 2)
    bidx = np.clip(np.searchsorted(edges, qd.to_numpy(float), side="right") - 1, 0, len(edges) - 2)
    bands = []
    for i in range(len(edges) - 1):
        bq = qd.index[bidx == i].tolist()
        m = d.quadrat.isin(bq).to_numpy()
        if not bq:
            bands.append(pooled)
            continue
        ce, cov, re, rec = size_tables(roof[m], pv[m], flag[m], w[m])
        # each table falls back to the pooled one on its own row count, as shipped
        n_cov = flag[m].sum()
        n_rec = (pv[m] > 0).sum()
        bands.append((ce, cov, re, rec) if (n_cov >= MIN_N and n_rec >= MIN_N) else
                     (pooled[0] if n_cov < MIN_N else ce, pooled[1] if n_cov < MIN_N else cov,
                      pooled[2] if n_rec < MIN_N else re, pooled[3] if n_rec < MIN_N else rec))
    return edges, bands


def estimate(roof, w, dens, model) -> float:
    edges, bands = model
    b = int(np.clip(np.searchsorted(edges, dens, side="right") - 1, 0, len(bands) - 1))
    ce, cov, re, rec = bands[b]
    return float((w * roof * cov[_bin(ce, roof)] / rec[_bin(re, roof)]).sum())


def verify(d, quads, qdens, thr) -> float:
    """Indicator-weighted tables against the shipped functions on the full trusted set."""
    flag = d.p_oof.to_numpy() >= thr
    _, bands = stratified(d, quads, qdens, flag, flag.astype(float))
    cov_s = coverage_ratio_by_size_and_density(None, quads, thr, qdens, df=d)
    rec_s = area_recall_by_size_and_density(None, quads, thr, qdens, df=d)
    worst = 0.0
    for mine, c, r in zip(bands, cov_s["bands"], rec_s["bands"]):
        ct, rt = pd.DataFrame(c["coverage_table"]), pd.DataFrame(r["recall_table"])
        worst = max(worst, float(np.max(np.abs(mine[1] - ct.coverage_ratio.to_numpy()))),
                    float(np.max(np.abs(mine[3] - rt.area_recall.to_numpy()))))
    return worst  # the shipped tables round to 4 decimals


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--folds", type=Path, default=Path("data/roofclf/folds.csv"))
    ap.add_argument("--profile", type=Path, default=Path("results/calibration_quadrats.csv"))
    ap.add_argument("--score", default="p_oof", help="column of --table, or npz:<block>")
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_soft_capacity.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    d = gpd.read_parquet(args.table).drop(columns="geometry").reset_index(drop=True)
    if args.score.startswith("npz:"):
        z = np.load("/home/tobi/earthpv_data/roofclf_untapped/roofclf_untapped_oof.npz",
                    allow_pickle=True)
        assert (z["quadrat"] == d.quadrat.to_numpy()).all()
        d["p_oof"] = z[args.score[4:]]
    elif args.score != "p_oof":
        d["p_oof"] = d[args.score]
    folds = pd.read_csv(args.folds).set_index("quadrat")
    folds = folds[~folds.index.isin(DEFAULT_EXCLUDE)]
    trusted = folds[(folds.rate_ratio >= DEFAULT_RATIO_LO)
                    & (folds.rate_ratio <= DEFAULT_RATIO_HI)].index.tolist()
    allq = sorted(d.quadrat.unique())
    qdens = quadrat_building_density_km2(args.profile, allq)
    y = d.has_pv.to_numpy().astype(bool)
    p = d.p_oof.to_numpy()
    q = d.quadrat.to_numpy()
    roof, pv = d.roof_area_m2.to_numpy(), d.pv_area_true_m2.to_numpy()

    thr_all = _precision_threshold(y, p, min_precision=0.5)
    if args.score == "p_oof":
        worst = verify(d, trusted, qdens, thr_all)
        print(f"reproduction against the shipped tables: max |diff| {worst:.2e} "
              f"({len(trusted)} trusted quadrats, threshold {thr_all:.4f})")
        if worst > 6e-5:
            raise SystemExit("indicator-weighted tables do not reproduce the shipped ones")

    rows = []
    for name in allq:
        te = q == name
        if pv[te].sum() <= 0:
            continue
        thr = _precision_threshold(y[~te], p[~te], min_precision=0.5)
        flag = p >= thr
        cal = [c for c in trusted if c != name]
        r = {"quadrat": name, "trusted": name in trusted, "truth": pv[te].sum(),
             "truth_sub400": pv[te & (roof < 400)].sum(), "density": float(qdens[name])}
        for lab, w in (("thresholded", flag.astype(float)), ("soft", p),
                       ("null", np.ones_like(p))):
            fl = flag if lab != "null" else np.ones_like(flag)
            model = stratified(d, cal, qdens, fl, w)
            r[lab] = estimate(roof[te], w[te], qdens[name], model)
            s4 = te & (roof < 400)
            r[f"{lab}_sub400"] = estimate(roof[s4], w[s4], qdens[name], model)
        rows.append(r)
    e = pd.DataFrame(rows).set_index("quadrat")
    e.to_csv(args.out.with_name(args.out.stem + f"_{args.score.replace(':', '_')}_by_quadrat.csv"))

    out = {"score": args.score, "n_quadrats": int(len(e)), "trusted": trusted, "results": {}}
    for scope, tcol in (("all", "truth"), ("sub400", "truth_sub400")):
        ok = e[tcol] > 0
        res = {}
        for lab in ("null", "thresholded", "soft"):
            col = lab if scope == "all" else f"{lab}_sub400"
            err = (e.loc[ok, col] - e.loc[ok, tcol]).abs() / e.loc[ok, tcol]
            res[lab] = {"median_abs_err": round(float(err.median()), 4),
                        "iqr": [round(float(err.quantile(.25)), 4),
                                round(float(err.quantile(.75)), 4)],
                        "pooled_ratio": round(float(e.loc[ok, col].sum() / e.loc[ok, tcol].sum()), 4),
                        "spearman": round(float(stats.spearmanr(e.loc[ok, col],
                                                                e.loc[ok, tcol]).statistic), 4)}
        for a, b in (("soft", "thresholded"), ("thresholded", "null"), ("soft", "null")):
            ca, cb = (a, b) if scope == "all" else (f"{a}_sub400", f"{b}_sub400")
            la = np.abs(np.log(np.maximum(e.loc[ok, ca], 1.0) / e.loc[ok, tcol]))
            lb = np.abs(np.log(np.maximum(e.loc[ok, cb], 1.0) / e.loc[ok, tcol]))
            dl = (lb - la).to_numpy()  # positive: `a` is closer to truth
            nb = int((dl > 0).sum())
            res[f"{a}_vs_{b}"] = {"a_better": f"{nb}/{len(dl)}",
                                  "median_dlog": round(float(np.median(dl)), 4),
                                  "sign_p": round(float(stats.binomtest(nb, len(dl)).pvalue), 4),
                                  "wilcoxon_p": round(float(stats.wilcoxon(dl).pvalue), 4)}
        out["results"][scope] = res
    print(json.dumps(out["results"], indent=2))
    if args.score == "p_oof":
        args.out.write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
