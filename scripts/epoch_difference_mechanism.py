"""If the 2019 difference helps, WHAT is it seeing? PV, or construction?

The split-half placebo in `run_epoch_difference_ablation.py` controls for measurement -- two
looks at the same roof, no epoch gap -- but not for change of the wrong kind. A building
that did not exist in 2019, or was re-roofed, also differences large, and VIDA footprints
are derived from recent imagery so new construction IS in the layer.

Three reads, none of which needs new data:

  SIGN      PV modules are dark. An installed array should make a roof DARKER in the
            visible, so the fitted coefficient on `d19_brightness` should be NEGATIVE and
            PV-bearing roofs should have darkened relative to PV-free ones. Bare ground
            turning into a roof goes the other way.
  MAGNITUDE if the signal were construction, it would live in the extreme tail of |delta|.
            Splitting the fold AUC by whether a building is in the top decile of
            |d19_brightness| says whether the gain needs that tail.
  DIRECTION  the same contrast measured directly: mean d19_brightness for PV-bearing
            against PV-free roofs, per quadrat, as a paired test.

    pixi run python scripts/epoch_difference_mechanism.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             fit_logistic, predict_proba)

def main() -> None:
    import geopandas as gpd

    from scripts.run_epoch_difference_ablation import (DELTA_OLD, EXCLUDE,  # noqa: F401
                                                       quadrat_deltas)
    from earthpv.roofclf import discover_quadrats
    base = gpd.read_parquet("data/roofclf_temporal_ablation/buildings.geoparquet")
    parts = []
    for stem in sorted(discover_quadrats(Path("data/labels"))):
        if stem == EXCLUDE:
            continue
        name = stem.split("_calib_")[0]
        sub = base[base.quadrat == name]
        if sub.empty:
            continue
        d = quadrat_deltas(stem, sub, Path("data/composites/pakistan"), Path("data/labels"))
        if d is None:
            continue
        d.index = sub.index
        parts.append(pd.concat([sub, d], axis=1))
    t = pd.concat(parts, ignore_index=True)
    feats = list(MODEL_FEATURES) + list(DELTA_OLD)
    t = t[np.isfinite(_subset_matrix(t, feats)).all(axis=1)].reset_index(drop=True)
    y = t.has_pv.to_numpy()

    # 1. SIGN, from one pooled fit (the per-fold coefficients are all the same story).
    m = fit_logistic(_subset_matrix(t, feats), y.astype(float), L2)
    # `w` is in standardised units, so coefficients are directly comparable.
    coef = dict(zip(feats, m["w"][: len(feats)]))
    print("coefficient on the epoch difference, largest ten by magnitude:")
    for k, v in sorted(((k, v) for k, v in coef.items() if k.startswith("d19_")),
                       key=lambda kv: -abs(kv[1]))[:10]:
        print(f"  {k:24} {v:+.3f}")

    # 2. DIRECTION, paired over quadrats.
    rows = []
    for q in sorted(t.quadrat.unique()):
        s = t[t.quadrat == q]
        if s.has_pv.nunique() < 2:
            continue
        rows.append({"quadrat": q,
                     "pv": float(s.loc[s.has_pv == 1, "d19_brightness"].mean()),
                     "nopv": float(s.loc[s.has_pv == 0, "d19_brightness"].mean())})
    d = pd.DataFrame(rows)
    dd = d.pv - d.nopv
    nb, nw = int((dd < 0).sum()), int((dd > 0).sum())
    print(f"\nd19_brightness, PV roofs minus PV-free roofs, per quadrat:")
    print(f"  median {dd.median():+.5f}   darker in {nb} of {nb + nw} quadrats   "
          f"sign p = {stats.binomtest(nb, max(nb + nw, 1), 0.5).pvalue:.4f}")

    # 3. MAGNITUDE: does the gain need the extreme tail?
    thr = np.nanquantile(np.abs(t.d19_brightness.to_numpy()), 0.90)
    tail = np.abs(t.d19_brightness.to_numpy()) >= thr
    print(f"\ntop-decile |d19_brightness| cut at {thr:.4f}; {int(tail.sum())} buildings, "
          f"base rate {y[tail].mean():.4f} against {y[~tail].mean():.4f} elsewhere")
    out = []
    for q in sorted(t.quadrat.unique()):
        te = (t.quadrat == q).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2 or t.loc[te, "has_pv"].nunique() < 2:
            continue
        r = {"quadrat": q}
        for lab, fs in (("baseline", list(MODEL_FEATURES)), ("d19", feats)):
            mm = fit_logistic(_subset_matrix(t[tr], fs), t.loc[tr, "has_pv"].to_numpy(float), L2)
            p = predict_proba(mm, _subset_matrix(t[te], fs))
            yy, roof = t.loc[te, "has_pv"].to_numpy(), t.loc[te, "roof_area_m2"].to_numpy()
            r[f"ws__{lab}"] = auc_within_size(yy, p, roof)[0]
            for sel, nm in ((tail[te], "tail"), (~tail[te], "bulk")):
                if sel.sum() > 1 and len(np.unique(yy[sel])) == 2:
                    r[f"{nm}__{lab}"] = auc(yy[sel], p[sel])
        out.append(r)
    o = pd.DataFrame(out)
    print(f"\n{'subset':12} {'baseline':>10} {'plus d19':>10} {'delta':>9} {'better':>9}")
    for nm in ("ws", "bulk", "tail"):
        a, b = f"{nm}__d19", f"{nm}__baseline"
        mm = o[[a, b]].dropna()
        dl = mm[a] - mm[b]
        print(f"{nm:12} {mm[b].median():10.4f} {mm[a].median():10.4f} {dl.median():+9.4f} "
              f"{int((dl > 0).sum()):5d}/{len(mm)}")
    o.to_csv("results/roofclf_epoch_mechanism_folds.csv", index=False)
    Path("results/roofclf_epoch_mechanism.json").write_text(json.dumps({
        "coef_d19": {k: round(float(v), 4) for k, v in coef.items() if k.startswith("d19_")},
        "pv_minus_nopv_d19_brightness_median": round(float(dd.median()), 6),
        "quadrats_darker": nb, "quadrats_total": nb + nw,
        "sign_p": round(float(stats.binomtest(nb, max(nb + nw, 1), 0.5).pvalue), 4),
        "tail_threshold": round(float(thr), 5),
    }, indent=2) + "\n")
    print("\nwrote results/roofclf_epoch_mechanism.json")


if __name__ == "__main__":
    main()
