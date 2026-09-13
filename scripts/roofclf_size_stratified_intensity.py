#!/usr/bin/env python
"""Give the German estimator the term it is missing: adoption intensity by roof size.

Measured across 9,674 municipalities, adoption intensity is almost a deterministic function of
roof scale: Spearman **-0.920**. German rooftop PV is a small-roof phenomenon, so houses and
farm buildings carry far more kWp per m2 than large industrial and urban roofs. The deployed
estimator, `sum(p * roof_area) * constant`, has no term for that. Worse, roofclf's own
probability leans slightly TOWARD big roofs (+0.147 against roof scale), so within a scene it
is negatively correlated with adoption intensity (median rho -0.300 across 2,580 cells).

That is why four label strategies, three feature sets, better footprints and per-scene
normalisation all landed on or behind a plain roof-area baseline.

**The fix needs no model, no labels and no imagery.** Split each municipality's roof area into
size bins and let the register say what a square metre in each bin is worth:

    truth_m = sum over bins b of ( A_mb * intensity_b )

with `A_mb` the roof area of municipality m in bin b. The register gives one equation per
municipality and there are only a handful of bins, so `intensity_b` is recovered by
non-negative least squares from thousands of equations -- overdetermined by three orders of
magnitude. This is `coverage_ratio_by_size_and_density`'s idea pointed at a complete register
instead of at mapped quadrats.

Every variant is cross-validated by municipality: intensities are fitted on the training folds
only, so a held-out municipality's capacity is never used to predict itself.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("size-intensity")

EQ_AREA = "EPSG:3035"
BINS = [0, 50, 100, 200, 400, 1000, 5000, np.inf]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prob-dir", default="data/roofclf_national_germany_prod/germany/prob")
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--gemeinden", default="data/calibration/vg250_gem.parquet")
    ap.add_argument("--mastr", default="data/calibration/mastr_gemeinden.parquet")
    ap.add_argument("--truth-col", default="kw_rooftop_le100")
    ap.add_argument("--min-coverage", type=float, default=0.98)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--cache", default="results/germany_roof_area_by_size_bin.csv")
    ap.add_argument("--out", default="results/germany_size_stratified_intensity.json")
    args = ap.parse_args()

    from scipy.optimize import nnls
    from scipy.stats import spearmanr

    cache = Path(args.cache)
    if cache.exists():
        d = pd.read_csv(cache, dtype={"ags": str})
        log.info("reusing %s", cache)
    else:
        files = sorted(glob.glob(f"{args.prob_dir}/*.parquet"))
        grid = gpd.read_parquet(args.grid)
        covered = grid[grid.cell.isin({Path(f).stem for f in files})].geometry.union_all()
        gem = gpd.read_parquet(args.gemeinden)
        gem["ags"] = gem.ags.astype(str).str.zfill(8)
        gem = gem[gem.geometry.intersects(covered)].reset_index(drop=True)
        gm = gem.to_crs(EQ_AREA)
        cov_m = gpd.GeoSeries([covered], crs=gem.crs).to_crs(EQ_AREA).iloc[0]
        gem["covered_frac"] = gm.geometry.intersection(cov_m).area / gm.geometry.area.clip(lower=1)
        keep = gem[gem["covered_frac"] >= args.min_coverage][["ags", "geometry"]].reset_index(drop=True)
        log.info("fully covered Gemeinden: %d", len(keep))

        acc: dict[str, np.ndarray] = {}
        nb = len(BINS) - 1
        for i, f in enumerate(files, 1):
            try:
                g = gpd.read_parquet(f)
            except Exception:
                continue
            if len(g) == 0 or "p_roofclf" not in g.columns:
                continue
            g = g[g.p_roofclf.notna()]
            if g.empty:
                continue
            pts = gpd.GeoDataFrame(
                {"roof": g.roof_area_m2.to_numpy(), "p": g.p_roofclf.to_numpy(),
                 "b": np.digitize(g.roof_area_m2.to_numpy(), BINS[1:-1])},
                geometry=g.geometry.representative_point(), crs=g.crs)
            j = gpd.sjoin(pts, keep, how="inner", predicate="within")
            if len(j) == 0:
                continue
            for ags, sub in j.groupby("ags"):
                a = acc.setdefault(ags, np.zeros(2 * nb))
                a[:nb] += np.bincount(sub.b, weights=sub.roof, minlength=nb)
                a[nb:] += np.bincount(sub.b, weights=sub.roof * sub.p, minlength=nb)
            if i % 1000 == 0:
                log.info("  %d/%d cells", i, len(files))
        cols = ([f"roof_b{i}" for i in range(nb)] + [f"credited_b{i}" for i in range(nb)])
        d = pd.DataFrame([{"ags": k, **dict(zip(cols, v))} for k, v in acc.items()])
        cache.parent.mkdir(parents=True, exist_ok=True)
        d.to_csv(cache, index=False)
        log.info("wrote %s", cache)

    nb = len(BINS) - 1
    mastr = pd.read_parquet(args.mastr)
    mastr["ags"] = mastr.ags.astype(str).str.zfill(8)
    d["ags"] = d.ags.astype(str).str.zfill(8)
    d = d.merge(mastr[["ags", args.truth_col]], on="ags", how="inner")
    d = d.rename(columns={args.truth_col: "truth"})
    roof_cols = [f"roof_b{i}" for i in range(nb)]
    cred_cols = [f"credited_b{i}" for i in range(nb)]
    d["roof_total"] = d[roof_cols].sum(axis=1)
    d = d[(d.truth > 0) & (d.roof_total > 0)].reset_index(drop=True)
    log.info("municipalities in the fit: %d, %.2f GWp", len(d), d.truth.sum() / 1e6)

    rng = np.random.default_rng(args.seed)
    fold = rng.integers(0, args.folds, len(d))
    out = {"n_gemeinden": int(len(d)), "bins_m2": [float(b) for b in BINS],
           "estimators": {}}

    def _cv(cols, name, single=False):
        pred = np.zeros(len(d))
        coefs = []
        for f in range(args.folds):
            tr, te = fold != f, fold == f
            if single:
                x = d.loc[tr, cols].sum(axis=1).to_numpy()
                r = d.loc[tr, "truth"].sum() / max(x.sum(), 1e-9)
                pred[te] = d.loc[te, cols].sum(axis=1).to_numpy() * r
                coefs.append([float(r)])
            else:
                A = d.loc[tr, cols].to_numpy()
                w, _ = nnls(A, d.loc[tr, "truth"].to_numpy())
                pred[te] = d.loc[te, cols].to_numpy() @ w
                coefs.append([float(v) for v in w])
        ok = pred > 0
        out["estimators"][name] = {
            "median_municipal_abs_pct_err": round(
                float((np.abs(pred[ok] - d.truth[ok]) / d.truth[ok]).median() * 100), 1),
            "spearman": round(float(spearmanr(pred, d.truth)[0]), 4),
            "total_ratio": round(float(pred.sum() / d.truth.sum()), 4),
            "mean_coefficients": [round(float(v), 5) for v in np.mean(coefs, axis=0)],
        }
        return out["estimators"][name]

    _cv(roof_cols, "roof_area_single_constant", single=True)
    _cv(cred_cols, "roofclf_single_constant", single=True)
    _cv(roof_cols, "roof_area_size_stratified")
    _cv(cred_cols, "roofclf_size_stratified")

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\n{len(d):,} municipalities, {d.truth.sum()/1e6:.1f} GWp registered")
    print(f"\n{'estimator':<32}{'medAPE%':>9}{'rho':>8}{'total':>8}")
    for k, v in out["estimators"].items():
        print(f"{k:<32}{v['median_municipal_abs_pct_err']:>9.1f}{v['spearman']:>8.3f}"
              f"{v['total_ratio']:>8.3f}")
    lab = [f"{int(BINS[i])}-{'inf' if np.isinf(BINS[i+1]) else int(BINS[i+1])}" for i in range(nb)]
    print("\nfitted kWp per m2 of roof, by roof-size bin (roof-area variant):")
    for name, c in zip(lab, out["estimators"]["roof_area_size_stratified"]["mean_coefficients"]):
        print(f"   {name:>12} m2 : {c:.5f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
