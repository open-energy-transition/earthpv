"""Does fitting SPPI's own inputs to our labels beat the physics formula, sub-400 m2 only?

SPPI (He et al. 2026) is a fixed, zero-parameter formula:

    SPPI = (B02/B03) * (B11 - B03 - |B08-B03| - |B12-B03|) / (B11 + B03)

`docs/issues/sppi-spectral-index-evaluation.md` already measured it against the (then) nine
quadrats: it beats our own detection rasters (0.823/0.828 within-size) but loses to the
17-feature roofclf fit (0.874/0.842), and adding it as a roofclf feature moves nothing
(already redundant with the reflectance features roofclf already has).

The question here is narrower: SPPI's own five raw bands, refit with weights chosen from
OUR labels instead of the paper's physics-derived unit coefficients -- and specifically,
does specializing that fit to sub-400 m2 training data (rather than all sizes) help on
sub-400 m2 buildings. This reuses `roofclf.fit_logistic`/`auc`/`auc_within_size` exactly
(no new statistics), leave-one-quadrat-out throughout, and runs on the 2026-08-05
17-quadrat table (83,748 buildings, 93.6% sub-400 m2) -- 5-9x the labels the original SPPI
evaluation had.

Four variants per fold, all evaluated ONLY on the held-out quadrat's sub-400 m2 buildings:
  raw_sppi     the physics formula, no fitting at all (the paper's number)
  refit_all    logistic regression on SPPI's 5 raw bands, trained on all OTHER quadrats'
               buildings of ANY size
  refit_sub400 same 5 bands, trained on all OTHER quadrats' buildings RESTRICTED to <400 m2
  roofclf      the shipped model's existing out-of-fold prediction (17 features), read
               from buildings.geoparquet's `p_oof` column -- not refit here, just the
               already-computed LOQO baseline this is being measured against

    python scripts/sppi_sub400_refit_test.py --buildings data/roofclf_20260805_newquadrats/buildings.geoparquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.roofclf import auc, auc_within_size, fit_logistic, predict_proba  # noqa: E402
from earthpv.sppi import compute_sppi  # noqa: E402

SPPI_BANDS = ["b02_mean", "b03_mean", "b08_mean", "b11_mean", "b12_mean"]
FLOOR = 400.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buildings", required=True)
    ap.add_argument("--out", default="results/sppi_sub400_refit_test.csv")
    args = ap.parse_args()

    import geopandas as gpd
    df = gpd.read_parquet(args.buildings)
    df["sppi"] = compute_sppi(df.b02_mean, df.b03_mean, df.b08_mean, df.b11_mean, df.b12_mean)
    X_all = df[SPPI_BANDS].to_numpy(dtype="float64")
    y_all = df["has_pv"].to_numpy(dtype="float64")
    roof_all = df["roof_area_m2"].to_numpy(dtype="float64")
    quadrats = sorted(df["quadrat"].unique())
    print(f"{len(df):,} buildings, {len(quadrats)} quadrats, "
          f"{(roof_all < FLOOR).mean() * 100:.1f}% sub-{FLOOR:g} m2\n")

    rows = []
    for q in quadrats:
        test = (df["quadrat"] == q).to_numpy()
        train = ~test
        test_small = test & (roof_all < FLOOR)
        if test_small.sum() < 10 or y_all[test_small].sum() < 2:
            print(f"  {q:16s} skipped: only {int(test_small.sum())} sub-400 buildings "
                  f"({int(y_all[test_small].sum())} PV)")
            continue

        y_te, roof_te = y_all[test_small], roof_all[test_small]
        r = {"quadrat": q, "n": int(test_small.sum()), "n_pv": int(y_te.sum())}

        # raw_sppi: no fitting, evaluate the physics formula directly.
        s = df.loc[test_small, "sppi"].to_numpy(dtype="float64")
        r["raw_sppi_auc"] = round(auc(y_te, s), 4)
        r["raw_sppi_auc_ws"], _ = auc_within_size(y_te, s, roof_te)

        # refit_all: same 5 bands, logistic-fit on every OTHER quadrat, any size.
        m = fit_logistic(X_all[train], y_all[train])
        p = predict_proba(m, X_all[test_small])
        r["refit_all_auc"] = round(auc(y_te, p), 4)
        r["refit_all_auc_ws"], _ = auc_within_size(y_te, p, roof_te)

        # refit_sub400: same 5 bands, logistic-fit on every OTHER quadrat's sub-400 ONLY.
        train_small = train & (roof_all < FLOOR)
        if y_all[train_small].sum() >= 5 and (1 - y_all[train_small]).sum() >= 5:
            m2 = fit_logistic(X_all[train_small], y_all[train_small])
            p2 = predict_proba(m2, X_all[test_small])
            r["refit_sub400_auc"] = round(auc(y_te, p2), 4)
            r["refit_sub400_auc_ws"], _ = auc_within_size(y_te, p2, roof_te)
        else:
            r["refit_sub400_auc"] = r["refit_sub400_auc_ws"] = np.nan

        # roofclf: the shipped model's own LOQO out-of-fold prediction, unchanged.
        if "p_oof" in df.columns:
            po = df.loc[test_small, "p_oof"].to_numpy(dtype="float64")
            r["roofclf_auc"] = round(auc(y_te, po), 4)
            r["roofclf_auc_ws"], _ = auc_within_size(y_te, po, roof_te)

        rows.append(r)
        print(f"  {q:16s} n={r['n']:5d} pv={r['n_pv']:4d}  "
              f"raw_sppi={r['raw_sppi_auc']:.3f}  refit_all={r['refit_all_auc']:.3f}  "
              f"refit_sub400={r.get('refit_sub400_auc', float('nan')):.3f}  "
              f"roofclf={r.get('roofclf_auc', float('nan')):.3f}", flush=True)

    out = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"\n{len(out)} quadrats -> {args.out}\n")
    cols = [c for c in out.columns if c.endswith(("_auc", "_auc_ws"))]
    print("median across folds (unconditional / within-size):")
    for base in ("raw_sppi", "refit_all", "refit_sub400", "roofclf"):
        a, aws = f"{base}_auc", f"{base}_auc_ws"
        if a in out.columns:
            print(f"  {base:14s} {out[a].median():.4f} / {out[aws].median():.4f}   "
                  f"min {out[a].min():.4f} / {out[aws].min():.4f}")


if __name__ == "__main__":
    main()
