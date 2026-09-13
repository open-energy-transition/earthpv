#!/usr/bin/env python
"""Check Germany's roof-size/adoption relationship against exhaustive RID labels.

The best German estimator found so far predicts municipal capacity from roof area in the
200-400 m2 band alone (35.4% median municipal error against 37.8% for all roof area), on the
strength of a measured relationship: adoption intensity anti-correlates with roof scale at
Spearman -0.920, and the share of roof area in the 200-400 m2 band is the only positively
correlated one (+0.375).

That relationship was measured from German OSM, which covers ~3.6% of registered rooftop units
and is biased toward large, conspicuous installations -- precisely the bias that would
manufacture a spurious size preference. RID is the control: 1,902 roofs in Wartenberg annotated
exhaustively from aerial imagery, with `pvmodule` as one superstructure class among shadow,
chimney, dormer and tree. Every roof is labelled, so an absent module is a real negative rather
than an unmapped one.

**RID coordinates are stored latitude-first**, so the WKT is flipped before any area is taken;
read as-is, every polygon lands off the coast of Somalia and the areas are silently wrong.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rid")

BINS = [0, 50, 100, 200, 400, 1000, np.inf]
LAB = ["0-50", "50-100", "100-200", "200-400", "400-1k", "1k+"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rid-dir", default="data/rid")
    ap.add_argument("--out", default="results/germany_rid_size_check.json")
    args = ap.parse_args()

    from shapely import wkt
    from shapely.ops import transform

    from earthpv.labels import geodesic_area_m2

    d = Path(args.rid_dir)
    roofs = pd.read_csv(d / "pv_areas_reviewed.csv")
    obst = pd.read_csv(d / "obstacles_reviewed.csv")

    def flip(g):
        # RID stores "lat lon"; shapely reads the first ordinate as x.
        return transform(lambda x, y: (y, x), g)

    # Bracket access: `area` is exactly the kind of column name that resolves to a method
    # on a GeoDataFrame, the CLAUDE.md `row.mask` trap. A handful of rows carry no geometry.
    roofs = roofs[roofs["area"].notna()].reset_index(drop=True)
    roofs["geom"] = [flip(wkt.loads(g)) for g in roofs["area"]]
    roofs["roof_m2"] = [geodesic_area_m2(g) for g in roofs.geom]
    pv = obst[obst.type == "pvmodule"].copy()
    pv = pv[pv["obstacle"].notna()].reset_index(drop=True)
    pv["geom"] = [flip(wkt.loads(g)) for g in pv["obstacle"]]
    pv["pv_m2"] = [geodesic_area_m2(g) for g in pv.geom]
    by_roof = pv.groupby("pv_area_id").pv_m2.sum()

    r = roofs[["id", "roof_m2", "roof_type", "building_type"]].copy()
    r["pv_m2"] = r.id.map(by_roof).fillna(0.0)
    r["has_pv"] = r.pv_m2 > 0
    r = r[r.roof_m2 > 0].reset_index(drop=True)
    log.info("RID roofs: %d, with PV: %d (%.1f%%), median roof %.0f m2",
             len(r), int(r.has_pv.sum()), 100 * r.has_pv.mean(), r.roof_m2.median())

    r["bin"] = pd.cut(r.roof_m2, BINS, labels=LAB, right=False)
    g = r.groupby("bin", observed=True).agg(
        n_roofs=("roof_m2", "size"), n_pv=("has_pv", "sum"),
        roof_m2=("roof_m2", "sum"), pv_m2=("pv_m2", "sum")).reset_index()
    g["adoption_rate"] = (g.n_pv / g.n_roofs).round(4)
    g["pv_per_roof_m2"] = (g.pv_m2 / g.roof_m2).round(5)
    g["share_of_all_pv"] = (g.pv_m2 / g.pv_m2.sum()).round(4)
    g["share_of_all_roof"] = (g.roof_m2 / g.roof_m2.sum()).round(4)
    # >1 means the band carries more PV than its share of roof area: a real preference.
    g["concentration"] = (g.share_of_all_pv / g.share_of_all_roof.clip(lower=1e-9)).round(3)

    from scipy.stats import spearmanr
    pvb = r[r.has_pv]
    rho_area = float(spearmanr(pvb.roof_m2, pvb.pv_m2)[0])

    out = {
        "source": "RID (TU Munich), Wartenberg, exhaustively annotated",
        "n_roofs": int(len(r)), "n_with_pv": int(r.has_pv.sum()),
        "base_rate": round(float(r.has_pv.mean()), 4),
        "median_roof_m2": round(float(r.roof_m2.median()), 1),
        "median_pv_m2_on_pv_roofs": round(float(pvb.pv_m2.median()), 1),
        "spearman_roof_area_vs_pv_area_on_pv_roofs": round(rho_area, 4),
        "osm_comparison_spearman": 0.729,
        "by_roof_size": g.to_dict("records"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))

    print(f"\nRID: {len(r):,} exhaustively annotated roofs, {int(r.has_pv.sum())} with PV "
          f"({100*r.has_pv.mean():.1f}%)")
    print(f"median roof {r.roof_m2.median():.0f} m2, median PV on PV-roofs "
          f"{pvb.pv_m2.median():.0f} m2")
    print(f"Spearman(roof area, PV area) on PV roofs: {rho_area:+.3f}  "
          f"(OSM-derived estimate was +0.729)")
    print(f"\n{'roof size':>10}{'roofs':>8}{'with PV':>9}{'adoption':>10}"
          f"{'PV/roof m2':>12}{'% of all PV':>13}{'concentration':>14}")
    for _, x in g.iterrows():
        print(f"{x['bin']:>10}{x.n_roofs:>8}{x.n_pv:>9}{x.adoption_rate:>10.3f}"
              f"{x.pv_per_roof_m2:>12.5f}{100*x.share_of_all_pv:>12.1f}%{x.concentration:>14.2f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
