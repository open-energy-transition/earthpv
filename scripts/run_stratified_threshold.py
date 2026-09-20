"""Is ONE national threshold leaving recall on the table?

`run_roof_classifier` picks a single cut on pooled out-of-fold scores targeting precision
0.5, and `sub400_capacity` fits its coverage ratio and area recall on whatever that cut
flags. One threshold is recall-optimal at a given precision only if the score is
CALIBRATED -- if `p = 0.3` means the same thing on a 60 m2 roof in a sparse village and on
a 900 m2 roof in an industrial estate. This register has repeatedly found it does not:
`rate_ratio` spans 0.2-5x across quadrats, gradient boosting beat the linear model on
per-quadrat rate error while ranking worse, and no monotone recalibration recovered that
gain. Miscalibration ACROSS STRATA is exactly the condition under which per-stratum
thresholds beat a global one at the same pooled precision, and it costs nothing to run:
the scores already exist.

The strata are the ones the capacity chain already uses, so a gain here is directly
consumable: building-size band, and the quadrat's building-density stratum.

Registered before measuring:

  * A per-stratum threshold CANNOT change any ranking, so AUC is untouched by
    construction. The only thing that can move is which buildings are flagged, which is
    the whole point -- this is a product experiment, not a model experiment.
  * The thresholds must be fitted OUT OF FOLD or the exercise is circular: a threshold
    chosen on a quadrat's own labels will always look good on that quadrat. Each held-out
    quadrat's cuts come from the OTHER quadrats' out-of-fold scores, the same nesting the
    model itself uses.
  * PREDICTION: a gain, but a small one, and concentrated in the small-size bands where
    the base rate is lowest and the pooled cut is therefore most conservative. If the
    gain is large, suspect the fold nesting before believing it.

TWO RULES ARE TESTED, AND THEY ARE NOT THE SAME THING. Targeting the same PRECISION in
every stratum ("by_size" and friends) is the intuitive version and the wrong objective: at
a fixed pooled precision the recall-maximising allocation equalises the MARGINAL precision,
the precision of the last building admitted, not the stratum's average. A stratum with a
3.6% base rate has to be cut very deep before its average precision reaches 0.5, which
throws away exactly the recall this is meant to buy. The right version recalibrates the
score to a per-stratum posterior and then applies ONE global cut to the recalibrated score
("recal_global"), which equalises the margin by construction. The register's existing
finding that no monotone map recovers gradient boosting's calibration gain does not settle
this: that map was global, and a per-stratum map is not.

    pixi run python scripts/run_stratified_threshold.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, fit_logistic,
                             predict_proba)
from earthpv.sppi import _precision_threshold

log = logging.getLogger("stratified_threshold")

# The capacity chain's own size deciles are fitted per run; these fixed edges are the
# coarse version, chosen so every bin holds enough positives to fit a threshold on 29
# quadrats. The top bin is the segmentation floor.
SIZE_EDGES = [0.0, 50.0, 100.0, 200.0, 400.0, np.inf]


def oof_scores(t: pd.DataFrame) -> np.ndarray:
    p = np.full(len(t), np.nan)
    for n in sorted(t.quadrat.unique()):
        te = (t.quadrat == n).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2:
            continue
        m = fit_logistic(_subset_matrix(t[tr], MODEL_FEATURES),
                         t.loc[tr, "has_pv"].to_numpy(float), L2)
        p[te] = predict_proba(m, _subset_matrix(t[te], MODEL_FEATURES))
    return p


def _pr(y: np.ndarray, flag: np.ndarray) -> tuple[float, float, int]:
    n = int(flag.sum())
    prec = float(y[flag].mean()) if n else float("nan")
    rec = float(y[flag].sum() / max(y.sum(), 1))
    return prec, rec, n


def _global_flags(y_fit, s_fit, s_app, target):
    return s_app >= _precision_threshold(y_fit, s_fit, target)


def _recal(y_fit, s_fit, g_fit, s_app, g_app, min_pos=20):
    """Per-stratum isotonic recalibration of the score, fitted on the training folds.

    A stratum too thin to fit honestly keeps the pooled map, so the transform is never
    less determined than the global one it is being compared against.
    """
    from sklearn.isotonic import IsotonicRegression

    def _fit(yy, ss):
        return IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(ss, yy)

    pooled = _fit(y_fit.astype(float), s_fit)
    out = pooled.predict(s_app)
    for g in np.unique(g_app):
        mf, ma = g_fit == g, g_app == g
        if mf.sum() > 0 and y_fit[mf].sum() >= min_pos and len(np.unique(s_fit[mf])) > 2:
            out[ma] = _fit(y_fit[mf].astype(float), s_fit[mf]).predict(s_app[ma])
    return out, pooled


def _stratum_flags(y_fit, s_fit, g_fit, s_app, g_app, target, min_pos=20):
    """One threshold per stratum, each targeting the same precision, with a fall-back to
    the pooled cut wherever the stratum is too thin to fit one honestly."""
    pooled = _precision_threshold(y_fit, s_fit, target)
    out = np.zeros(len(s_app), dtype=bool)
    for g in np.unique(g_app):
        m_fit = g_fit == g
        thr = pooled
        if m_fit.sum() > 0 and y_fit[m_fit].sum() >= min_pos:
            thr = _precision_threshold(y_fit[m_fit], s_fit[m_fit], target)
        out[g_app == g] = s_app[g_app == g] >= thr
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=Path("data/roofclf_temporal_unmix/buildings.geoparquet"))
    ap.add_argument("--target", type=float, default=0.5)
    ap.add_argument("--out", type=Path,
                    default=Path("results/roofclf_stratified_threshold.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(args.table).reset_index(drop=True)
    t = t[np.isfinite(_subset_matrix(t, MODEL_FEATURES)).all(axis=1)].reset_index(drop=True)
    s = oof_scores(t)
    ok = np.isfinite(s)
    t, s = t[ok].reset_index(drop=True), s[ok]
    y = t.has_pv.to_numpy(bool)
    log.info("%d rows, %d quadrats, pooled AUC %.4f", len(t), t.quadrat.nunique(), auc(y, s))

    size_g = np.digitize(t.roof_area_m2.to_numpy(), SIZE_EDGES[1:-1])
    # Quadrat building density, the capacity chain's other stratifier, as terciles of the
    # per-quadrat building count per unit area proxy the table already carries.
    per_q = t.groupby("quadrat").size()
    dens_g = pd.qcut(t.quadrat.map(per_q), 3, labels=False, duplicates="drop").to_numpy()
    combo_g = size_g * 10 + dens_g
    strata = {"global": None, "by_size": size_g, "by_density": dens_g,
              "by_size_and_density": combo_g}

    # Nested: each quadrat's cuts come from the OTHER quadrats' out-of-fold scores.
    quads = sorted(t.quadrat.unique())
    recal_arms = {f"recal_{k}": g for k, g in strata.items() if g is not None}
    flags = {k: np.zeros(len(t), bool) for k in list(strata) + list(recal_arms)}
    for q in quads:
        app = (t.quadrat == q).to_numpy()
        fit = ~app
        for k, g in strata.items():
            if g is None:
                flags[k][app] = _global_flags(y[fit], s[fit], s[app], args.target)
            else:
                flags[k][app] = _stratum_flags(y[fit], s[fit], g[fit], s[app], g[app],
                                               args.target)
        for k, g in recal_arms.items():
            # The recalibrated score is what gets ONE global cut. The cut itself is fitted
            # on the training folds' own recalibrated scores (in-sample to the isotonic
            # map, which is why the map is fitted on the training folds and never on q).
            r_fit, _ = _recal(y[fit], s[fit], g[fit], s[fit], g[fit])
            r_app, _ = _recal(y[fit], s[fit], g[fit], s[app], g[app])
            flags[k][app] = _global_flags(y[fit], r_fit, r_app, args.target)

    print(f"\n{'rule':24} {'flagged':>9} {'precision':>10} {'recall':>8} {'d recall':>9}")
    base_p, base_r, base_n = _pr(y, flags["global"])
    summary = {"n_rows": int(len(t)), "auc": round(float(auc(y, s)), 4),
               "target_precision": args.target}
    for k in flags:
        p, r, n = _pr(y, flags[k])
        print(f"{k:24} {n:9d} {p:10.4f} {r:8.4f} {r - base_r:+9.4f}")
        summary[k] = {"n_flagged": n, "precision": round(p, 4), "recall": round(r, 4),
                      "d_recall": round(r - base_r, 4)}

    # A recall gain bought by dropping precision is not a gain. Report the honest
    # comparison too: the global threshold RE-TUNED to whatever precision the stratified
    # rule actually achieved, so both rules sit at the same operating precision.
    print(f"\n{'matched-precision check':24} {'flagged':>9} {'precision':>10} {'recall':>8}")
    for k in flags:
        if k == "global":
            continue
        p_k = summary[k]["precision"]
        m = np.zeros(len(t), bool)
        for q in quads:
            app = (t.quadrat == q).to_numpy()
            fit = ~app
            m[app] = _global_flags(y[fit], s[fit], s[app], p_k)
        p, r, n = _pr(y, m)
        print(f"{'global @ ' + f'{p_k:.4f}':24} {n:9d} {p:10.4f} {r:8.4f}")
        summary[k]["matched_global_recall"] = round(r, 4)
        summary[k]["net_d_recall"] = round(summary[k]["recall"] - r, 4)
        # Pooled recall hides which quadrats moved. The paired per-quadrat test is what
        # every other claim in this register is held to, so hold this one to it too.
        dq = []
        for q in quads:
            a = (t.quadrat == q).to_numpy() & y
            if a.sum() == 0:
                continue
            dq.append(float(flags[k][a].mean()) - float(m[a].mean()))
        dq = np.array(dq)
        b, w = int((dq > 0).sum()), int((dq < 0).sum())
        from scipy import stats as _st
        summary[k]["paired"] = {
            "d_recall_median": round(float(np.median(dq)), 4),
            "quadrats_better": b, "quadrats_worse": w,
            "sign_p": round(float(_st.binomtest(b, max(b + w, 1), 0.5).pvalue), 4)}
        print(f"{'  paired over quadrats':24} {'':9} {'':10} "
              f"median {np.median(dq):+.4f}  {b}/{b + w} better  "
              f"p={summary[k]['paired']['sign_p']:.3f}")

    print(f"\n{'per size bin':24} {'n':>8} {'base rate':>10} {'global thr recall':>18} "
          f"{'stratified recall':>18}")
    for i, lo in enumerate(SIZE_EDGES[:-1]):
        m = size_g == i
        if m.sum() == 0:
            continue
        lab = f"{lo:.0f}-{SIZE_EDGES[i + 1]:.0f} m2"
        rg = float(y[m & flags['global']].sum() / max(y[m].sum(), 1))
        rs = float(y[m & flags['recal_by_size']].sum() / max(y[m].sum(), 1))
        print(f"{lab:24} {int(m.sum()):8d} {float(y[m].mean()):10.4f} {rg:18.4f} "
              f"{rs:18.4f}")
        summary.setdefault("size_bins", {})[lab] = {
            "n": int(m.sum()), "base_rate": round(float(y[m].mean()), 4),
            "recall_global": round(rg, 4), "recall_stratified": round(rs, 4)}
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
