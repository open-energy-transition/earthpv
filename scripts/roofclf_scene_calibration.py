#!/usr/bin/env python
"""Is roofclf's flatness across municipalities scene drift, or genuine blindness?

Measured over 9,674 German municipalities: true adoption intensity spans 4.6x while roofclf's
mean probability spans 0.95x, Spearman -0.031. Three feature sets (with size, without size,
spectral only) gave byte-identical municipal errors, so it is not the features.

Two explanations remain and they imply opposite next steps:

* **Scene drift.** Each 0.1 degree cell is one composite with its own atmosphere, sun angle and
  epoch. If those shift p's level per scene, the nuisance variance swamps a real adoption
  signal, and removing the per-scene offset would recover it.
* **Genuine blindness at scale.** The classifier ranks roofs within a neighbourhood but carries
  no information about which neighbourhoods have more PV, in which case no re-weighting helps.

The discriminating measurement is WITHIN-scene: for cells containing several municipalities,
does mean p track adoption across those municipalities, where scene conditions are shared? A
positive within-cell correlation alongside the null across-cell one is scene drift. Both null
is blindness.

The scene-normalised estimator (each building's p divided by its own cell's mean) is then the
corresponding fix, scored the same way as everything else.
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
log = logging.getLogger("scene-cal")

EQ_AREA = "EPSG:3035"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prob-dir", default="data/roofclf_national_germany_prod/germany/prob")
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--gemeinden", default="data/calibration/vg250_gem.parquet")
    ap.add_argument("--mastr", default="data/calibration/mastr_gemeinden.parquet")
    ap.add_argument("--truth-col", default="kw_rooftop_le100")
    ap.add_argument("--min-coverage", type=float, default=0.98)
    ap.add_argument("--min-gem-per-cell", type=int, default=5)
    ap.add_argument("--out", default="results/germany_roofclf_scene_calibration.json")
    args = ap.parse_args()

    from scipy.stats import spearmanr

    files = sorted(glob.glob(f"{args.prob_dir}/*.parquet"))
    grid = gpd.read_parquet(args.grid)
    done = {Path(f).stem for f in files}
    covered = grid[grid.cell.isin(done)].geometry.union_all()

    gem = gpd.read_parquet(args.gemeinden)
    gem["ags"] = gem.ags.astype(str).str.zfill(8)
    gem = gem[gem.geometry.intersects(covered)].reset_index(drop=True)
    gm = gem.to_crs(EQ_AREA)
    cov_m = gpd.GeoSeries([covered], crs=gem.crs).to_crs(EQ_AREA).iloc[0]
    gem["covered_frac"] = gm.geometry.intersection(cov_m).area / gm.geometry.area.clip(lower=1)
    keep = gem[gem["covered_frac"] >= args.min_coverage][["ags", "geometry"]].reset_index(drop=True)
    log.info("fully covered Gemeinden: %d", len(keep))

    # Per (municipality, cell): credited area, roof area, and building count.
    acc: dict[tuple[str, str], list[float]] = {}
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
        cell = Path(f).stem
        pts = gpd.GeoDataFrame(
            {"p": g.p_roofclf.to_numpy(), "roof": g.roof_area_m2.to_numpy()},
            geometry=g.geometry.representative_point(), crs=g.crs)
        j = gpd.sjoin(pts, keep, how="inner", predicate="within")
        if len(j) == 0:
            continue
        for ags, sub in j.groupby("ags"):
            a = acc.setdefault((ags, cell), [0.0, 0.0, 0.0])
            a[0] += float((sub.p * sub.roof).sum())
            a[1] += float(sub.roof.sum())
            a[2] += len(sub)
        if i % 1000 == 0:
            log.info("  %d/%d cells", i, len(files))

    d = pd.DataFrame([{"ags": k[0], "cell": k[1], "credited": v[0], "roof": v[1], "n": v[2]}
                      for k, v in acc.items()])
    d = d[d.roof > 0]
    mastr = pd.read_parquet(args.mastr)
    mastr["ags"] = mastr.ags.astype(str).str.zfill(8)
    truth = mastr.set_index("ags")[args.truth_col]

    per_gem = d.groupby("ags").agg(credited=("credited", "sum"), roof=("roof", "sum")).reset_index()
    per_gem["truth"] = per_gem.ags.map(truth)
    per_gem = per_gem.dropna().query("credited>0 and roof>0 and truth>0")
    per_gem["mean_p"] = per_gem.credited / per_gem.roof
    per_gem["intensity"] = per_gem.truth / per_gem.roof

    # 1. within-scene: shared atmosphere, sun angle and epoch.
    rows = []
    for cell, sub in d.groupby("cell"):
        s = sub.merge(per_gem[["ags", "truth"]], on="ags", how="inner")
        s = s[(s.roof > 0) & (s.truth > 0)]
        if len(s) < args.min_gem_per_cell:
            continue
        r = spearmanr(s.credited / s.roof, s.truth / s.roof)[0]
        if not np.isnan(r):
            rows.append({"cell": cell, "n_gem": len(s), "rho": float(r)})
    w = pd.DataFrame(rows)

    # 2. the corresponding fix: divide each cell's contribution by that cell's mean p.
    d["cell_mean_p"] = d.cell.map(d.groupby("cell").apply(
        lambda s: s.credited.sum() / max(s.roof.sum(), 1e-9), include_groups=False))
    d["credited_norm"] = d.credited / d.cell_mean_p.clip(lower=1e-9)
    norm = d.groupby("ags").credited_norm.sum()
    per_gem["credited_norm"] = per_gem.ags.map(norm)

    def _score(x, name):
        m = (x > 0) & per_gem.truth.notna()
        pred = x[m] * (per_gem.truth[m].sum() / x[m].sum())
        return {name: {
            "median_municipal_abs_pct_err": round(
                float((np.abs(pred - per_gem.truth[m]) / per_gem.truth[m]).median() * 100), 1),
            "spearman": round(float(spearmanr(x[m], per_gem.truth[m])[0]), 4)}}

    out = {"n_gemeinden": int(len(per_gem)),
           "across_scene_spearman_meanp_vs_intensity": round(
               float(spearmanr(per_gem.mean_p, per_gem.intensity)[0]), 4),
           "within_scene": {
               "n_cells": int(len(w)),
               "median_rho": round(float(w.rho.median()), 4) if len(w) else None,
               "mean_rho": round(float(w.rho.mean()), 4) if len(w) else None,
               "frac_positive": round(float((w.rho > 0).mean()), 3) if len(w) else None},
           "estimators": {}}
    for x, name in ((per_gem.roof, "roof_area_baseline"),
                    (per_gem.credited, "roofclf_as_is"),
                    (per_gem.credited_norm.fillna(0), "roofclf_scene_normalised")):
        out["estimators"].update(_score(x, name))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\n{out['n_gemeinden']:,} municipalities")
    print(f"across-scene Spearman(mean p, adoption intensity): "
          f"{out['across_scene_spearman_meanp_vs_intensity']:+.4f}")
    ws = out["within_scene"]
    print(f"within-scene, {ws['n_cells']} cells with >= {args.min_gem_per_cell} municipalities: "
          f"median rho {ws['median_rho']:+.4f}, mean {ws['mean_rho']:+.4f}, "
          f"{100*ws['frac_positive']:.0f}% positive")
    print(f"\n{'estimator':<28}{'medAPE%':>9}{'rho':>8}")
    for k, v in out["estimators"].items():
        print(f"{k:<28}{v['median_municipal_abs_pct_err']:>9.1f}{v['spearman']:>8.3f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
