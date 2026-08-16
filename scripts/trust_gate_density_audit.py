"""Is `select_calibrated_quadrats`'s precision-trust gate confounded with building density?

The gate keeps quadrats whose roofclf `rate_ratio` (predicted/true adoption rate) falls in
[0.5, 2.0]. It is described everywhere in this repo as a *precision* filter, independent of
the density domain (`density.CALIBRATED_BLDG_DENSITY_KM2`), and CLAUDE.md warns the two must
be checked separately. This script asks the question that framing leaves open: whether the
gate, while filtering on precision, also filters on density as a side effect -- and if so,
what that costs, since the surviving quadrats are what
`coverage_ratio_by_size_and_density` and `area_recall_by_size_and_density` are fit on, and
those two multipliers price 83% of the published Best estimate.

Three stages, all printed by one run:

  confound  rate_ratio against quadrat density: rank correlation, gate pass rate by density
            tercile, and how far the surviving quadrats' density range sits from the cells
            the fit is deployed onto.
  reach     how many in-domain buildings, and how many published MWp, are priced by a
            multiplier fit on quadrats strictly denser than their own cell.
  sweep     refit both multipliers under a range of `ratio_hi` values and recompute the two
            roofclf capacity components exactly, so the gate's effect on the headline is a
            measured number rather than an argument.

The sweep recomputes `roof_area_m2 * DEFAULT_KWP_PER_M2_MODULE * coverage_ratio /
area_recall` (the literal formula in `sub400_capacity.domain_restricted_capacity` and
`roofclf_ge400_capacity.domain_restricted_ge400_roof_capacity`) over the saved incremental
building tables, re-deriving both multipliers per building from the refit tables. It
reproduces the shipped totals under the shipped gate as its own correctness check.

Known approximation: the density-conditional size floor (`size_floor_by_density_band`) is
applied upstream of the saved tables and its band edges move with the gate, so the sweep
holds the shipped floor selection fixed. In the shipped run the floor removed 8,657
buildings carrying 306,896 m2, which is 0.17% of the sub-400 area, so this cannot move any
conclusion here.

Usage:
    .pixi/envs/default/bin/python scripts/trust_gate_density_audit.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE  # noqa: E402
from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2  # noqa: E402
from earthpv.sub400_capacity import (  # noqa: E402
    DEFAULT_EXCLUDE, DEFAULT_N_DENSITY_STRATA, DEFAULT_RATIO_HI, DEFAULT_RATIO_LO,
    apply_stratified_area_recall, apply_stratified_coverage_ratio,
    area_recall_by_size_and_density, coverage_ratio_by_size_and_density,
    quadrat_building_density_km2, select_calibrated_quadrats,
)

BUILDINGS = Path("data/roofclf/buildings.geoparquet")
FOLDS = Path("data/roofclf/folds.csv")
PROFILE = Path("results/calibration_quadrats.csv")
SUMMARY = Path("data/roofclf/summary.json")
CELL_DENSITY = Path("data/roofclf/national_cell_density.parquet")
DENSITY_DIR = Path("data/roofclf_national_with_sppi/pakistan/density")
COMPONENTS = (
    ("sub400_central_incremental_buildings.parquet", "est_kwp_sub400",
     "sub-400 rooftop (central)", 7890.1642),
    ("ge400_roof_incremental_buildings.parquet", "est_kwp_ge400_roof",
     ">=400 roofclf rooftop", 7189.4282),
)
PUBLISHED_BEST_MWP = 18218.4
SWEEP = [2.0, 2.5, 3.0, 3.5, 5.0, np.inf]


def _folds_with_density() -> pd.DataFrame:
    folds = pd.read_csv(FOLDS)
    prof = pd.read_csv(PROFILE)
    prof["density"] = prof.n_buildings / prof.area_km2
    d = folds.merge(prof[["label", "density", "n_buildings", "area_km2"]],
                    left_on="quadrat", right_on="label", how="left")
    d["passes_gate"] = (
        (d.rate_ratio >= DEFAULT_RATIO_LO) & (d.rate_ratio <= DEFAULT_RATIO_HI)
        & ~d.quadrat.isin(DEFAULT_EXCLUDE)
    )
    return d


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return float("nan")
    rx = pd.Series(x[ok]).rank().to_numpy()
    ry = pd.Series(y[ok]).rank().to_numpy()
    return float(np.corrcoef(rx, ry)[0, 1])


def stage_confound(d: pd.DataFrame) -> None:
    print("=" * 78)
    print("CONFOUND: is the precision gate also a density filter?")
    print("=" * 78)
    have = d[d.density.notna()]
    rho = _spearman(have.density.to_numpy(), have.rate_ratio.to_numpy())
    print(f"Spearman(quadrat density, rate_ratio) = {rho:+.3f} over {len(have)} quadrats "
          f"with a density on file")
    print("  a negative sign means roofclf over-predicts adoption in sparser settlements,")
    print("  so an upper bound on rate_ratio removes the sparse end by construction\n")

    have = have.assign(tercile=pd.qcut(have.density, 3, labels=["sparse", "middle", "dense"]))
    t = have.groupby("tercile", observed=True).agg(
        n=("quadrat", "size"), density_lo=("density", "min"), density_hi=("density", "max"),
        median_rate_ratio=("rate_ratio", "median"), passing=("passes_gate", "sum"))
    t["pass_rate"] = (t.passing / t.n).round(2)
    print(t.round(2).to_string())

    passed = d[d.passes_gate]
    print(f"\ngate keeps {len(passed)} of {len(d)} quadrats "
          f"(rate_ratio in [{DEFAULT_RATIO_LO}, {DEFAULT_RATIO_HI}], excluding "
          f"{list(DEFAULT_EXCLUDE)})")
    print(f"  surviving density range: {passed.density.min():.0f} - "
          f"{passed.density.max():.0f} bldg/km2")
    dropped_sparse = d[(~d.passes_gate) & (d.density < passed.density.min())]
    print(f"  quadrats dropped that are sparser than every survivor: {len(dropped_sparse)}")
    print(dropped_sparse[["quadrat", "density", "base_rate", "rate_ratio"]]
          .sort_values("density").round(3).to_string(index=False))

    missing = d[d.density.isna()]
    if not missing.empty:
        print(f"\na second, independent blocker: {len(missing)} quadrat(s) have no "
              f"n_buildings in {PROFILE} at all,")
        print("  so quadrat_building_density_km2 cannot place them and they can never enter")
        print("  the coverage-ratio fit regardless of the gate:")
        print(missing[["quadrat", "rate_ratio"]].round(3).to_string(index=False))
        print(f"  (note {CALIBRATED_BLDG_DENSITY_KM2[0]:.1f} bldg/km2, the density domain's "
              f"own floor, was set by one of these)")


def stage_reach(d: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 78)
    print("REACH: how much of the published number is priced out of calibration range?")
    print("=" * 78)
    sparsest = d[d.passes_gate].density.min()
    nat = pd.read_parquet(CELL_DENSITY)
    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    dom = nat[(nat.density > lo) & (nat.density < hi)]
    below = dom[dom.density < sparsest]
    print(f"sparsest quadrat in the fit: {sparsest:.0f} bldg/km2")
    print(f"density domain: ({lo}, {hi}) bldg/km2, {len(dom):,} cells, "
          f"{dom.n_buildings.sum():,} buildings")
    print(f"  in-domain buildings in cells sparser than that: {below.n_buildings.sum():,} "
          f"({100*below.n_buildings.sum()/dom.n_buildings.sum():.1f}%) in {len(below):,} cells")
    w = below.sort_values("density")
    cw = np.cumsum(w.n_buildings.to_numpy()) / w.n_buildings.sum()
    qs = {f"p{int(q*100)}": float(w.density.to_numpy()[np.searchsorted(cw, q)])
          for q in (0.25, 0.5, 0.75)}
    print(f"  their building-weighted density: {qs} bldg/km2")

    dens = nat.set_index("cell").density
    rows = []
    for fname, col, label, _ in COMPONENTS:
        t = pd.read_parquet(DENSITY_DIR / fname, columns=["cell", col])
        t["density"] = t.cell.map(dens)
        tot = t[col].sum() / 1000
        out = t.loc[t.density < sparsest, col].sum() / 1000
        rows.append({"component": label, "mwp": tot, "mwp_below_calibration": out,
                     "share": out / tot})
    r = pd.DataFrame(rows)
    print()
    for _, x in r.iterrows():
        print(f"  {x['component']:28s} {x.mwp:9,.1f} MWp   out of range "
              f"{x.mwp_below_calibration:9,.1f} MWp ({100*x.share:5.1f}%)")
    print(f"  {'roofclf half of the atlas':28s} {r.mwp.sum():9,.1f} MWp   out of range "
          f"{r.mwp_below_calibration.sum():9,.1f} MWp "
          f"({100*r.mwp_below_calibration.sum()/r.mwp.sum():.1f}%)")
    print(f"  = {100*r.mwp_below_calibration.sum()/PUBLISHED_BEST_MWP:.0f}% of the published "
          f"Best estimate of {PUBLISHED_BEST_MWP:,.1f} MWp")
    return r


def _recompute(quadrats: list[str], threshold: float) -> dict:
    """Both roofclf capacity components under one choice of calibration quadrats."""
    qd = quadrat_building_density_km2(PROFILE, quadrats)
    cov = coverage_ratio_by_size_and_density(
        BUILDINGS, quadrats, threshold, qd, n_density_bands=DEFAULT_N_DENSITY_STRATA)
    rec = area_recall_by_size_and_density(
        BUILDINGS, quadrats, threshold, qd, n_density_bands=DEFAULT_N_DENSITY_STRATA)
    dens = pd.read_parquet(CELL_DENSITY).set_index("cell").density
    out = {"band_edges": cov["band_edges"], "n_quadrats": len(quadrats),
           "sparsest": float(qd.min())}
    for fname, col, label, _ in COMPONENTS:
        t = pd.read_parquet(DENSITY_DIR / fname, columns=["cell", "roof_area_m2"])
        cd = t.cell.map(dens).to_numpy(float)
        a = t.roof_area_m2.to_numpy(float)
        kwp = (a * DEFAULT_KWP_PER_M2_MODULE
               * apply_stratified_coverage_ratio(a, cd, cov)
               / apply_stratified_area_recall(a, cd, rec))
        out[label] = float(kwp.sum()) / 1000.0
    return out


def stage_sweep(threshold: float) -> None:
    print("\n" + "=" * 78)
    print("SWEEP: what does relaxing the gate do to the headline?")
    print("=" * 78)
    prof = pd.read_csv(PROFILE).set_index("label")
    placeable = set(prof.index[prof.n_buildings.notna() & prof.area_km2.notna()])
    base = None
    rows = []
    for hi in SWEEP:
        quadrats, _ = select_calibrated_quadrats(FOLDS, DEFAULT_RATIO_LO, hi)
        # A quadrat with no n_buildings on file cannot be placed in a density band, so it
        # cannot enter the fit no matter how wide the gate is opened.
        quadrats = [q for q in quadrats if q in placeable]
        r = _recompute(quadrats, threshold)
        tot = sum(r[c[2]] for c in COMPONENTS)
        if base is None:
            base = tot
        rows.append({"ratio_hi": hi, "n_quadrats": r["n_quadrats"],
                     "sparsest_bldg_km2": r["sparsest"],
                     "band_split": r["band_edges"][1],
                     **{c[2]: r[c[2]] for c in COMPONENTS},
                     "roofclf_half_mwp": tot, "vs_shipped_%": 100 * (tot / base - 1)})
    df = pd.DataFrame(rows)
    print(df.round(2).to_string(index=False))

    print("\ncorrectness check against the shipped totals:")
    for fname, col, label, shipped in COMPONENTS:
        got = float(df.loc[df.ratio_hi == DEFAULT_RATIO_HI, label].iloc[0])
        flag = "OK" if abs(got - shipped) / shipped < 0.005 else "MISMATCH"
        print(f"  {label:28s} recomputed {got:9,.1f} vs shipped {shipped:9,.1f} MWp  [{flag}]")


def main() -> None:
    threshold = json.loads(SUMMARY.read_text())["deployment_threshold"]
    print(f"roofclf deployment threshold {threshold}\n")
    d = _folds_with_density()
    stage_confound(d)
    stage_reach(d)
    stage_sweep(threshold)


if __name__ == "__main__":
    main()
