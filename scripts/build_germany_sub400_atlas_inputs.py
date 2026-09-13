#!/usr/bin/env python
"""Turn Germany's scored buildings into the two parquets `earthpv atlas` expects.

The evidence atlas wants a roofclf half as building-level rows carrying `est_kwp_sub400`
(Best) and `est_kwp_sub400_and_gate` (the stricter floor). Two adaptations are needed for
Germany, and both are recorded in the output rather than hidden:

**Pre-aggregated to one row per cell.** `atlas._join_buildings_to_grid_cells` sjoins every
row to the density grid and sums per cell. Handing it 25M building geometries peaks over
20 GB and is OOM-killed; handing it one row per cell, positioned on a real building inside
that cell, produces the identical per-cell sum. `score_buildings_national` claims each
building for exactly one cell on that cell's own half-open box, so a point taken from the
cell's own buildings cannot land anywhere else.

**The floor tier is quantile-based, not precision-calibrated.** Pakistan's AND-gate requires
roofclf and SPPI to agree at a threshold fitted for 0.5 precision. Germany cannot fit that:
its labels mark ~3.6% of registered units, which is why its LOQO threshold search returns a
value above 1.0 flagging nothing. The floor here is therefore "both signals in their top
decile", an explicitly weaker claim, and the atlas tier built from it should be read as
"where two independent signals agree" rather than "calibrated to a measured precision".

The kWp per credited m2 comes from `calibrate_germany_capacity.py`, fitted against MaStR per
municipality, not from a transferred quadrat coverage ratio.
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
log = logging.getLogger("de-atlas-inputs")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prob-dir", default="data/roofclf_national_germany_prod/germany/prob")
    ap.add_argument("--capacity", default="results/germany_roofclf_capacity.json")
    ap.add_argument("--quantile", type=float, default=0.90)
    ap.add_argument("--out-dir", default="data/roofclf_national_germany_prod/germany/density")
    ap.add_argument("--sample-cells", type=int, default=400)
    ap.add_argument("--max-roof-m2", type=float, default=400.0)
    ap.add_argument("--min-roof-m2", type=float, default=0.0)
    ap.add_argument("--method", choices=["roofclf", "size_band"], default="roofclf",
                    help="roofclf weights each roof by p; size_band prices band roof area "
                         "directly with a register-fitted constant and uses no classifier")
    ap.add_argument("--kwp-per-m2", type=float, default=None,
                    help="size_band only: kWp per m2 of band roof, fitted against the register")
    ap.add_argument("--osm-solar", default="data/labels/germany_national_osm_solar.parquet")
    ap.add_argument("--candidates", default="data/predictions/germany/candidates.parquet")
    args = ap.parse_args()

    if args.method == "size_band":
        if args.kwp_per_m2 is None:
            raise SystemExit("--kwp-per-m2 is required for --method size_band")
        ratio = args.kwp_per_m2
        log.info("size_band: %.0f-%.0f m2 roofs at %.5f kWp/m2, no classifier",
                 args.min_roof_m2, args.max_roof_m2, ratio)
    else:
        ratio = json.loads(Path(args.capacity).read_text())["estimators"][
            "roofclf_probability_weighted"]["kwp_per_m2"]
        log.info("roofclf: register-fitted %.5f kWp per credited m2", ratio)

    files = sorted(glob.glob(f"{args.prob_dir}/*.parquet"))
    if not files:
        raise SystemExit(f"no scored cells under {args.prob_dir}")

    rng = np.random.default_rng(20260913)
    sample = rng.choice(files, size=min(args.sample_cells, len(files)), replace=False)
    ps, ss = [], []
    for f in sample:
        try:
            # pandas, not geopandas: reading a column subset without the geometry column
            # raises in gpd.read_parquet, and the quantiles do not need geometry.
            g = pd.read_parquet(f, columns=["p_roofclf", "sppi"])
        except Exception:
            continue
        g = g[g.p_roofclf.notna()]
        if len(g):
            ps.append(g.p_roofclf.to_numpy())
            ss.append(g.sppi.to_numpy())
    p_thr = float(np.nanquantile(np.concatenate(ps), args.quantile))
    s_thr = float(np.nanquantile(np.concatenate(ss), args.quantile))
    log.info("top-decile thresholds from %d sampled cells: p_roofclf >= %.5f, sppi >= %.5f",
             len(sample), p_thr, s_thr)

    # INCREMENTAL, or the atlas double-counts. The Best tier already carries segmentation's
    # own >= 400 m2 detections and the hand-mapped OSM population, so a roofclf component that
    # credits every building would add capacity the atlas has counted once already. Pakistan's
    # `domain_restricted_capacity` dedupes for exactly this reason; this is its equivalent.
    osm = gpd.read_parquet(args.osm_solar)[["geometry"]].to_crs("EPSG:4326")
    osm = osm[osm.geometry.notna() & osm.geometry.is_valid]
    cand = gpd.read_parquet(args.candidates)[["geometry"]].to_crs("EPSG:4326")
    cand = cand[cand.geometry.notna() & cand.geometry.is_valid]
    log.info("dedup layers: %d OSM installations, %d segmentation candidates", len(osm), len(cand))
    osm_ix, cand_ix = osm.sindex, cand.sindex

    n_all = n_kept = 0
    rows = []
    for f in files:
        try:
            g = gpd.read_parquet(f)
        except Exception:
            continue
        if len(g) == 0 or "p_roofclf" not in g.columns:
            continue
        g = g[g.p_roofclf.notna()]
        if g.empty:
            continue
        n_all += len(g)
        # Sub-400 m2 roofs only: this is the atlas's small-PV component, and >= 400 m2 is
        # segmentation's own population.
        g = g[(g.roof_area_m2 < args.max_roof_m2) & (g.roof_area_m2 >= args.min_roof_m2)]
        if g.empty:
            continue
        pt = g.geometry.representative_point()
        drop = np.zeros(len(g), dtype=bool)
        for layer_ix in (osm_ix, cand_ix):
            hit = layer_ix.query(pt.to_numpy(), predicate="within")
            if len(hit):
                drop[np.unique(hit[0])] = True
        g = g[~drop]
        if g.empty:
            continue
        n_kept += len(g)
        if args.method == "size_band":
            # No classifier: the band's roof area priced directly. Measured at 35.4% median
            # municipal error against roofclf's 48.4% and 37.8% for all roof area.
            kwp = g.roof_area_m2.to_numpy() * ratio
            # A regression has no second detector to agree with, so there is no floor
            # population. Verified therefore keeps only hand-mapped OSM, and this component
            # is written as zeros rather than omitted, because the atlas requires the pair.
            agree = np.zeros(len(g), dtype=bool)
        else:
            kwp = g.roof_area_m2.to_numpy() * g.p_roofclf.to_numpy() * ratio
            agree = (g.p_roofclf.to_numpy() >= p_thr) & (g.sppi.to_numpy() >= s_thr)
        rows.append({
            "cell": Path(f).stem,
            "est_kwp_sub400": float(kwp.sum()),
            "est_kwp_sub400_and_gate": float(kwp[agree].sum()),
            "n_buildings": int(len(g)), "n_agree": int(agree.sum()),
            # A point on a real building in this cell: the join must not depend on the
            # cell id string, which the atlas deliberately distrusts.
            "geometry": g.geometry.iloc[0].representative_point(),
        })

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    d = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs="EPSG:4326")
    d[["cell", "est_kwp_sub400", "geometry"]].to_parquet(
        out / "sub400_central_incremental_buildings.parquet")
    d[["cell", "est_kwp_sub400_and_gate", "geometry"]].to_parquet(
        out / "sub400_low_incremental_buildings.parquet")
    log.info("buildings: %d assessable, %d kept after sub-%.0f m2 + OSM/candidate dedup (%.1f%%)",
             n_all, n_kept, args.max_roof_m2, 100 * n_kept / max(n_all, 1))
    log.info("cells=%d  central=%.1f MWp  and-gate floor=%.1f MWp (%.1f%% of central)",
             len(d), d.est_kwp_sub400.sum() / 1000, d.est_kwp_sub400_and_gate.sum() / 1000,
             100 * d.est_kwp_sub400_and_gate.sum() / max(d.est_kwp_sub400.sum(), 1e-9))
    log.info("wrote %s", out)


if __name__ == "__main__":
    main()
