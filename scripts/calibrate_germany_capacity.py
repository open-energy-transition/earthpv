#!/usr/bin/env python
"""Calibrate German rooftop capacity against MaStR, and report what it is worth.

Germany has no exhaustively mapped quadrats, so the usual `coverage_ratio` route is shut.
It does not need one: MaStR is complete, so kWp per unit of credited roof area is fitted
directly against the register per municipality. That is a stronger calibration than a
transferred quadrat ratio, not a weaker one.

Three numbers come out, and they are reported together on purpose:

* **the calibrated estimate** -- credited roof area times the register-fitted constant,
* **a roof-area baseline** -- total roof area times its own register-fitted constant, which
  in Germany is the more accurate of the two (23.0% against 58.4% median municipal error;
  in Pakistan the ordering reverses and roofclf wins 3.4x),
* **the register's own national total**, which is the truth the other two are trying to hit.

**The national comparison is a real out-of-sample test.** The constant is fitted only on
municipalities the scored cells fully cover, then applied to every scored building in the
country. If the covered subset is representative, the national totals agree; if not, the gap
is the extrapolation error, and it is reported rather than absorbed.

**A national total that matches is not evidence the geography is right.** Measured on the
709-cell run: total ratio 1.003 while the median municipality was off by 53%, because
over-prediction of the largest decile cancelled under-prediction of the rest.
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
log = logging.getLogger("de-capacity")

EQ_AREA = "EPSG:3035"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prob-dir", default="data/roofclf_national_germany_prod/germany/prob")
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--gemeinden", default="data/calibration/vg250_gem.parquet")
    ap.add_argument("--mastr", default="data/calibration/mastr_gemeinden.parquet")
    ap.add_argument("--truth-col", default="kw_rooftop_le100")
    ap.add_argument("--min-coverage", type=float, default=0.98)
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--out", default="results/germany_roofclf_capacity.json")
    ap.add_argument("--out-cells", default="results/germany_roofclf_capacity_by_cell.csv")
    args = ap.parse_args()

    files = sorted(glob.glob(f"{args.prob_dir}/*.parquet"))
    if not files:
        raise SystemExit(f"no scored cells under {args.prob_dir}")

    # Streamed, one cell at a time. Loading all 25M scored buildings and reprojecting them
    # in one go peaks at 22.7 GB and is OOM-killed; a cell holds a few thousand rows.
    grid = gpd.read_parquet(args.grid)
    done = {Path(f).stem for f in files}
    scored_cells = grid[grid.cell.isin(done)]
    scored_area = scored_cells.geometry.union_all()
    log.info("scored cells on the grid: %d of %d", len(scored_cells), len(grid))

    gem = gpd.read_parquet(args.gemeinden)
    gem["ags"] = gem.ags.astype(str).str.zfill(8)
    gem = gem[gem.geometry.intersects(scored_area)].reset_index(drop=True)
    gem_m = gem.to_crs(EQ_AREA)
    gem["covered_frac"] = (gem_m.geometry.intersection(
        gpd.GeoSeries([scored_area], crs=gem.crs).to_crs(EQ_AREA).iloc[0]).area
        / gem_m.geometry.area.clip(lower=1))
    keep = gem[gem["covered_frac"] >= args.min_coverage][["ags", "geometry"]].reset_index(drop=True)
    log.info("Gemeinden fully covered: %d of %d touched", len(keep), len(gem))

    per_ags: dict[str, list[float]] = {}
    cell_rows = []
    n_all = n_kept = 0
    nat_credited = nat_roof = 0.0
    for i, f in enumerate(files, 1):
        try:
            g = gpd.read_parquet(f)
        except Exception:
            continue
        if len(g) == 0 or "p_roofclf" not in g.columns:
            continue
        n_all += len(g)
        # Buildings with no valid composite pixel score NaN. Filling them with 0 would credit
        # their roof area to the baseline while crediting nothing to roofclf, biasing the very
        # comparison this script exists to make, so they leave BOTH populations.
        g = g[g.p_roofclf.notna()]
        if g.empty:
            continue
        n_kept += len(g)
        g = g.assign(credited_m2=g.roof_area_m2 * g.p_roofclf)
        nat_credited += float(g.credited_m2.sum())
        nat_roof += float(g.roof_area_m2.sum())
        cell_rows.append({"cell": Path(f).stem,
                          "credited_m2": float(g.credited_m2.sum()),
                          "all_roof_m2": float(g.roof_area_m2.sum()),
                          "n_buildings": int(len(g))})
        pts = gpd.GeoDataFrame(
            {"credited_m2": g.credited_m2.to_numpy(), "roof_area_m2": g.roof_area_m2.to_numpy()},
            geometry=g.geometry.representative_point(), crs=g.crs)
        j = gpd.sjoin(pts, keep, how="inner", predicate="within")
        if len(j):
            for ags, sub in j.groupby("ags"):
                acc = per_ags.setdefault(ags, [0.0, 0.0])
                acc[0] += float(sub.credited_m2.sum())
                acc[1] += float(sub.roof_area_m2.sum())
        if i % 500 == 0:
            log.info("  %d/%d cells, %d buildings kept", i, len(files), n_kept)

    log.info("dropped %d of %d buildings with no valid composite pixel (%.1f%%)",
             n_all - n_kept, n_all, 100 * (n_all - n_kept) / max(n_all, 1))
    log.info("national: %.1f km2 roof, %.1f km2 credited", nat_roof / 1e6, nat_credited / 1e6)

    agg = pd.DataFrame([{"ags": k, "credited_m2": v[0], "all_roof_m2": v[1]}
                        for k, v in per_ags.items()])
    mastr = pd.read_parquet(args.mastr)
    mastr["ags"] = mastr.ags.astype(str).str.zfill(8)
    d = agg.merge(mastr[["ags", args.truth_col]], on="ags", how="inner")
    d = d[(d.credited_m2 > 0) & (d[args.truth_col] > 0)].reset_index(drop=True)
    d["truth_kw"] = d[args.truth_col]
    log.info("calibration set: %d Gemeinden, %.2f GWp registered", len(d), d.truth_kw.sum() / 1e6)
    national = {"credited_m2": nat_credited, "all_roof_m2": nat_roof}

    rng = np.random.default_rng(args.seed)
    out: dict = {"status": "PRELIMINARY", "prob_dir": args.prob_dir,
                 "truth_column": args.truth_col,
                 "n_calibration_gemeinden": int(len(d)),
                 "registered_gwp_in_calibration_set": round(float(d.truth_kw.sum() / 1e6), 3),
                 "estimators": {}}

    for col, name in (("credited_m2", "roofclf_probability_weighted"),
                      ("all_roof_m2", "roof_area_baseline")):
        ratio = float(d.truth_kw.sum() / d[col].sum())
        boots = [float(d.truth_kw.iloc[i].sum() / d[col].iloc[i].sum())
                 for i in (rng.integers(0, len(d), len(d)) for _ in range(args.boot))]
        pred = d[col] * ratio
        ape = float((np.abs(pred - d.truth_kw) / d.truth_kw).median() * 100)
        from scipy.stats import spearmanr
        national_m2 = national[col]
        out["estimators"][name] = {
            "kwp_per_m2": round(ratio, 5),
            "kwp_per_m2_90ci": [round(float(np.percentile(boots, 5)), 5),
                                round(float(np.percentile(boots, 95)), 5)],
            "median_municipal_abs_pct_err": round(ape, 1),
            "spearman_vs_register": round(float(spearmanr(d[col], d.truth_kw)[0]), 4),
            "national_input_km2": round(national_m2 / 1e6, 1),
            "national_estimate_gwp": round(national_m2 * ratio / 1e6, 3),
        }

    reg_nat = float(mastr[args.truth_col].sum() / 1e6)
    out["register_national_gwp"] = round(reg_nat, 3)
    for name, v in out["estimators"].items():
        v["national_vs_register"] = round(v["national_estimate_gwp"] / reg_nat, 3)

    out["caveats"] = [
        "PRELIMINARY: Germany has no exhaustively mapped calibration quadrats, so the "
        "classifier is trained on OSM labels covering ~3.6% of registered rooftop units",
        "the roof-area baseline is MORE accurate than roofclf in Germany (measured), and "
        "LESS accurate in Pakistan by 3.4x -- this is regime-specific, not a defect",
        "a national total matching the register is not evidence the per-cell geography is "
        "right: the 709-cell run scored 1.003 nationally with 53% median municipal error",
        "the fitted kWp/m2 is a calibration, not a physical constant; it absorbs footprint "
        "completeness and classifier miscalibration alike",
        "buildings with no valid composite pixel (~10% nationally) are excluded from both "
        "estimators, so the national figures cover the assessable population, not every roof",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))

    # The calibration itself, one row per municipality: what the fit is actually made of,
    # and the source for the calibration panel in docs/assets/figures/germany_calibration.svg.
    d_out = d[["ags", "credited_m2", "all_roof_m2", "truth_kw"]].copy()
    for name, col in (("roofclf_probability_weighted", "credited_m2"),
                      ("roof_area_baseline", "all_roof_m2")):
        d_out[f"pred_kw_{col}"] = d[col] * out["estimators"][name]["kwp_per_m2"]
    gem_csv = str(args.out).replace(".json", "_per_gemeinde.csv")
    d_out.to_csv(gem_csv, index=False)
    log.info("wrote %s (%d municipalities)", gem_csv, len(d_out))

    cells = pd.DataFrame(cell_rows)
    r = out["estimators"]["roofclf_probability_weighted"]["kwp_per_m2"]
    cells["est_mwp_roofclf"] = cells.credited_m2 * r / 1000.0
    cells.to_csv(args.out_cells, index=False)

    print(f"\nscored {len(cell_rows)} cells, {n_kept:,} buildings")
    print(f"calibration: {len(d):,} fully covered Gemeinden, "
          f"{out['registered_gwp_in_calibration_set']} GWp registered")
    print(f"\n{'estimator':<32}{'kWp/m2':>9}{'medAPE%':>9}{'rho':>7}{'national GWp':>14}{'vs reg':>8}")
    for name, v in out["estimators"].items():
        print(f"{name:<32}{v['kwp_per_m2']:>9.4f}{v['median_municipal_abs_pct_err']:>9.1f}"
              f"{v['spearman_vs_register']:>7.3f}{v['national_estimate_gwp']:>14.2f}"
              f"{v['national_vs_register']:>8.2f}")
    print(f"{'REGISTER (truth)':<32}{'':>9}{'':>9}{'':>7}{reg_nat:>14.2f}{1.0:>8.2f}")
    print(f"\nwrote {args.out} and {args.out_cells}")


if __name__ == "__main__":
    main()
