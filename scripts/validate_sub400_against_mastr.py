#!/usr/bin/env python
"""Does the sub-400 m2 capacity estimator recover a known truth?

This is the check the project has never been able to run. `coverage_ratio` and `area_recall`
price about 83% of Pakistan's published Best estimate and are fit on 30 purposive quadrats,
against no independent truth, because Pakistan has none. Germany does: MaStR is complete by
law, and `vg250_gem.parquet` carries the municipality polygons it is keyed to.

**Why the 30 kWp coordinate cliff does not block this.** MaStR publishes no coordinates below
30 kWp, which is why Germany's `p_unmapped` precision instrument cannot reach the sub-400 m2
population. But this estimator does not make per-building claims; it emits a per-area MWp
aggregate, and an aggregate is exactly what an uncoordinated register publishes completely.
The cliff blocks precision, not calibration.

**What is measured.** Flagged roof area per Gemeinde against registered sub-floor rooftop
capacity, cross-validated across municipalities: fit the ratio on a training split, predict
the held-out split, and report slope, Spearman and bias. Then ask whether stratifying by
building size and density -- the machinery Pakistan's atlas depends on -- beats a single
pooled ratio out of sample. That is the part nobody has been able to test.

**A Gemeinde is only usable if the scored cells cover it completely.** Its register capacity
is whole, so a partially scored municipality has truncated flagged area against complete
truth, which would drag the fitted ratio down. Coverage is measured geometrically and
anything below `--min-coverage` is dropped rather than counted.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sub400-mastr")

EQ_AREA = "EPSG:3035"


def load_scored(prob_dir: Path, threshold: float | None,
                min_roof_m2: float | None = None, max_roof_m2: float | None = None,
                want_sppi: bool = False) -> gpd.GeoDataFrame:
    """Scored buildings, optionally restricted to a roof-area band.

    The band filter is applied PER FILE, before concatenating. Loading every German
    building at once is the documented 22.7 GB OOM (CLAUDE.md, "Anything that loads every
    scored building at once will OOM"); restricting to 200-400 m2 on the way in keeps a
    band run well inside memory and changes nothing about the result.
    """
    parts = []
    cols = ["geometry", "roof_area_m2", "p_roofclf"] + (["sppi"] if want_sppi else [])
    for f in sorted(prob_dir.glob("*.parquet")):
        try:
            g = gpd.read_parquet(f)
        except Exception:
            continue
        if len(g) == 0 or "p_roofclf" not in g.columns:
            continue
        if want_sppi and "sppi" not in g.columns:
            raise SystemExit(f"{f} has no `sppi` column; this scoring pass cannot be "
                             "used for an SPPI weighting")
        if min_roof_m2 is not None:
            g = g[g.roof_area_m2 >= min_roof_m2]
        if max_roof_m2 is not None:
            g = g[g.roof_area_m2 < max_roof_m2]
        if len(g) == 0:
            continue
        parts.append(g[cols])
    if not parts:
        raise SystemExit(f"no scored cells under {prob_dir}")
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    if threshold is not None:
        g["flagged"] = g.p_roofclf >= threshold
        log.info("scored buildings: %d, flagged %d (%.2f%%)",
                 len(g), int(g.flagged.sum()), 100 * g.flagged.mean())
    else:
        g["flagged"] = True
    log.info("p_roofclf: median %.4f, p90 %.4f, max %.4f",
             g.p_roofclf.median(), g.p_roofclf.quantile(0.9), g.p_roofclf.max())
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prob-dir", required=True)
    ap.add_argument("--calib-dir", default="data/roofclf_germany")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--grid", default="data/predictions/germany/density/grid.geoparquet")
    ap.add_argument("--gemeinden", default="data/calibration/vg250_gem.parquet")
    ap.add_argument("--mastr", default="data/calibration/mastr_gemeinden.parquet")
    ap.add_argument("--truth-col", default="kw_rooftop_le100",
                    help="registered rooftop capacity in the band the instrument targets")
    ap.add_argument("--min-coverage", type=float, default=0.98)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--label", default="vida")
    ap.add_argument("--weight",
                    choices=["prob", "threshold", "area", "sppi_rank", "sppi_threshold"],
                    default="prob",
                    help="prob weights each roof by p_roofclf (no threshold needed, the "
                         "analogue of density.py's est_mwp_exp); threshold counts roofs "
                         "above --threshold, the analogue of est_mwp_det; area credits "
                         "every roof's full area with NO classifier at all (the baseline "
                         "the published German half uses); sppi_rank weights each roof by "
                         "the percentile rank of its SPPI within the scored population "
                         "(SPPI is a spectral index in roughly [-0.55, 0.07], not a "
                         "probability, so it cannot be multiplied in raw); sppi_threshold "
                         "counts roofs in SPPI's top --sppi-decile fraction")
    ap.add_argument("--min-roof-m2", type=float, default=None,
                    help="restrict to roofs at or above this area, applied per file on load")
    ap.add_argument("--max-roof-m2", type=float, default=None,
                    help="restrict to roofs below this area; 200/400 reproduces the band "
                         "the published German sub-400 estimator prices")
    ap.add_argument("--sppi-decile", type=float, default=0.9,
                    help="sppi_threshold only: quantile of SPPI above which a roof counts")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    thr = args.threshold
    if thr is None and args.weight == "threshold":
        thr = json.loads(
            (Path(args.calib_dir) / "summary.json").read_text())["deployment_threshold"]
    # A calibration fitted on incomplete labels can return a threshold no probability can
    # reach. Germany's OSM-fitted run produced 1.9994 with n_flagged=0, because the 0.5
    # precision target is unreachable when ~96% of true positives are unlabelled. Flagging
    # nothing would silently make every municipality read zero rather than error, so this
    # refuses instead.
    if thr is not None and not (0.0 < thr < 1.0):
        raise SystemExit(
            f"deployment threshold {thr:.4f} is outside (0, 1): the calibration could not "
            "reach its precision target on incomplete labels. Pass --weight prob to skip "
            "thresholding, or --threshold with a value chosen deliberately.")
    if args.weight == "prob":
        log.info("weighting roofs by p_roofclf; no threshold applied")
    else:
        log.info("deployment threshold: %.4f", thr)

    want_sppi = args.weight.startswith("sppi")
    scored = load_scored(Path(args.prob_dir),
                         thr if args.weight == "threshold" else None,
                         args.min_roof_m2, args.max_roof_m2, want_sppi).to_crs(EQ_AREA)
    if want_sppi:
        # Rank within the scored population: SPPI is an index, not a probability, and its
        # absolute value carries no calibration. The fitted ratio absorbs the scale either
        # way, so what is being tested is whether SPPI ORDERS roofs usefully.
        s = scored.sppi.to_numpy()
        # NaN-safe throughout. Measured on the German band: 34 NaN SPPI values in 313,264
        # buildings, 0.011% -- enough for np.quantile to return NaN, and `x >= NaN` is
        # False for EVERY row, so the first threshold run flagged nothing at all and
        # reported n_gemeinden=0 rather than failing. A NaN roof is not evidence of PV,
        # so it ranks and flags as absent rather than being dropped.
        n_nan = int(np.isnan(s).sum())
        if n_nan:
            log.info("SPPI: %d of %d buildings have no value (%.3f%%); treated as absent",
                     n_nan, len(s), 100 * n_nan / len(s))
        scored["sppi_rank"] = pd.Series(s).rank(pct=True).fillna(0.0).to_numpy()
        s_thr = float(np.nanquantile(s, args.sppi_decile))
        scored["flagged"] = (scored.sppi >= s_thr).fillna(False)
        log.info("SPPI: median %.4f, p90 %.4f, threshold(q=%.2f) %.4f, flagged %d (%.1f%%)",
                 float(np.nanmedian(s)), float(np.nanquantile(s, 0.9)), args.sppi_decile, s_thr,
                 int(scored.flagged.sum()), 100 * float(scored.flagged.mean()))
    elif args.weight == "area":
        scored["flagged"] = True
    grid = gpd.read_parquet(args.grid).to_crs(EQ_AREA)
    done = {p.stem for p in Path(args.prob_dir).glob("*.parquet")}
    grid = grid[grid.cell.isin(done)]
    scored_area = grid.geometry.union_all()
    log.info("scored cells: %d", len(grid))

    gem = gpd.read_parquet(args.gemeinden).to_crs(EQ_AREA)
    gem["ags"] = gem.ags.astype(str).str.zfill(8)
    gem = gem[gem.geometry.intersects(scored_area)].reset_index(drop=True)
    # Bracket access, and never `.cov`: a column called `cov` is shadowed by
    # DataFrame.cov, the covariance method, exactly like the `row.mask` trap in CLAUDE.md.
    gem["covered_frac"] = (gem.geometry.intersection(scored_area).area
                           / gem.geometry.area.clip(lower=1))
    keep = gem[gem["covered_frac"] >= args.min_coverage].reset_index(drop=True)
    log.info("Gemeinden touching scored cells: %d, fully covered (>=%.0f%%): %d",
             len(gem), 100 * args.min_coverage, len(keep))
    if len(keep) < 50:
        raise SystemExit("too few fully covered Gemeinden for a cross-validated fit")

    keep_cols = ["geometry", "roof_area_m2", "p_roofclf", "flagged"]
    if want_sppi:
        keep_cols += ["sppi", "sppi_rank"]
    scored = scored[[c for c in keep_cols if c in scored.columns]]
    j = gpd.sjoin(scored, keep[["ags", "geometry"]], how="inner", predicate="within")
    # The estimator's input: roof area credited to PV, either probability-weighted or
    # thresholded. Everything downstream is identical between the two.
    if args.weight == "prob":
        j["credited_m2"] = j.roof_area_m2 * j.p_roofclf
    elif args.weight == "area":
        j["credited_m2"] = j.roof_area_m2
    elif args.weight == "sppi_rank":
        j["credited_m2"] = j.roof_area_m2 * j.sppi_rank
    else:  # threshold, sppi_threshold
        j["credited_m2"] = j.roof_area_m2 * j.flagged.astype(float)
    agg = j.groupby("ags").agg(
        flagged_roof_m2=("credited_m2", "sum"),
        all_roof_m2=("roof_area_m2", "sum"),
        n_buildings=("roof_area_m2", "size"),
        n_flagged=("flagged", "sum"),
        median_roof_m2=("roof_area_m2", "median"),
    ).reset_index()

    mastr = pd.read_parquet(args.mastr)
    mastr["ags"] = mastr.ags.astype(str).str.zfill(8)
    d = agg.merge(mastr[["ags", args.truth_col, "kw_rooftop"]], on="ags", how="inner")
    d = d[(d.flagged_roof_m2 > 0) & (d[args.truth_col] > 0)].reset_index(drop=True)
    d["truth_kw"] = d[args.truth_col]
    area_km2 = keep.set_index("ags").geometry.area / 1e6
    d["density"] = d.n_buildings / d.ags.map(area_km2).clip(lower=1e-9)
    log.info("Gemeinden in the fit: %d, %.2f GWp registered in band",
             len(d), d.truth_kw.sum() / 1e6)

    rng = np.random.default_rng(args.seed)
    fold = rng.integers(0, args.folds, len(d))
    res: dict = {}

    def _cv(name: str, strata: pd.Series | None):
        pred = np.zeros(len(d))
        for f in range(args.folds):
            tr, te = fold != f, fold == f
            if strata is None:
                r = d.loc[tr, "truth_kw"].sum() / max(d.loc[tr, "flagged_roof_m2"].sum(), 1e-9)
                pred[te] = d.loc[te, "flagged_roof_m2"] * r
            else:
                for s in strata.unique():
                    mtr, mte = tr & (strata == s).to_numpy(), te & (strata == s).to_numpy()
                    if mtr.sum() < 10:
                        mtr = tr
                    r = d.loc[mtr, "truth_kw"].sum() / max(d.loc[mtr, "flagged_roof_m2"].sum(), 1e-9)
                    pred[mte] = d.loc[mte, "flagged_roof_m2"] * r
        from scipy.stats import spearmanr
        ok = pred > 0
        slope = float((pred * d.truth_kw).sum() / max((pred ** 2).sum(), 1e-9))
        res[name] = {
            "n": int(len(d)),
            "slope_truth_on_pred": round(slope, 4),
            "spearman": round(float(spearmanr(pred, d.truth_kw)[0]), 4),
            "total_ratio_pred_over_truth": round(float(pred.sum() / d.truth_kw.sum()), 4),
            "median_abs_pct_err": round(float(
                (np.abs(pred[ok] - d.truth_kw[ok]) / d.truth_kw[ok]).median() * 100), 1),
            "loglog_r": round(float(np.corrcoef(np.log10(pred[ok]),
                                                np.log10(d.truth_kw[ok]))[0, 1]), 4),
        }

    _cv("pooled_single_ratio", None)
    size_q = pd.qcut(d.median_roof_m2, 4, labels=False, duplicates="drop")
    dens_q = pd.qcut(d.density, 4, labels=False, duplicates="drop")
    _cv("stratified_by_size", size_q.astype(str))
    _cv("stratified_by_density", dens_q.astype(str))
    _cv("stratified_by_size_and_density", (size_q.astype(str) + "_" + dens_q.astype(str)))

    out = {
        "footprints": args.label,
        "prob_dir": str(args.prob_dir),
        "weight": args.weight,
        "threshold": (round(float(thr), 4) if thr is not None else None),
        "truth_column": args.truth_col,
        "n_scored_cells": int(len(grid)),
        "n_gemeinden": int(len(d)),
        "registered_gwp_in_band": round(float(d.truth_kw.sum() / 1e6), 3),
        "implied_kwp_per_flagged_m2": round(
            float(d.truth_kw.sum() / max(d.flagged_roof_m2.sum(), 1e-9)), 4),
        "cross_validated": res,
        "caveat": (
            "the fitted ratio absorbs everything between flagged roof area and registered "
            "capacity, including footprint completeness, so it is a calibration not a "
            "physical constant; what the cross-validation tests is whether it is stable "
            "enough to predict municipalities it was not fit on"
        ),
    }
    outp = Path(args.out
                or f"results/germany_sub400_register_{args.label}_{args.weight}.json")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2))
    d.to_csv(str(outp).replace(".json", "_per_gemeinde.csv"), index=False)

    print(f"\nfootprints={args.label}  cells={len(grid)}  Gemeinden={len(d)}  "
          f"registered {out['registered_gwp_in_band']} GWp in band")
    print(f"implied {out['implied_kwp_per_flagged_m2']} kWp per flagged m2 "
          f"(project module constant: 0.18, France-measured: 0.150)")
    print(f"\n{'estimator':<34}{'slope':>8}{'rho':>8}{'tot':>8}{'medAPE%':>9}{'loglog r':>10}")
    for k, v in res.items():
        print(f"{k:<34}{v['slope_truth_on_pred']:>8.3f}{v['spearman']:>8.3f}"
              f"{v['total_ratio_pred_over_truth']:>8.3f}{v['median_abs_pct_err']:>9.1f}"
              f"{v['loglog_r']:>10.3f}")
    print(f"\nwrote {outp}")


if __name__ == "__main__":
    main()
