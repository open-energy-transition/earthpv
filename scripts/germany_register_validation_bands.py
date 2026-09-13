#!/usr/bin/env python
"""Band-level tables behind Germany's register validation, as tracked figure sources.

Two measurements, both against MaStR, both by polygon size, because size is what turned out
to matter:

* **Rooftop** -- what a hand-mapped OSM polygon is actually worth in kWp/m2, measured on the
  polygons containing EXACTLY ONE registered unit so a polygon in a dense street cannot
  collect its neighbours' address points.
* **Ground** -- what share of polygons in each band contains any registered unit at all.
  Registration is mandatory and 81.2% of ground units carry coordinates, so a band with no
  corroboration is a band that is not ground-mount PV.

Writes `results/germany_osm_validation_bands.csv`, read by
`build_docs_figures.fig_germany_register_validation`.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-bands")

ROOF_BINS = [0, 200, 500, 2000, np.inf]
ROOF_LAB = ["<200", "200-500", "500-2k", ">2k"]
GROUND_BINS = [0, 1e6, 5e6, 10e6, np.inf]
GROUND_LAB = ["<1 km2", "1-5 km2", "5-10 km2", ">10 km2"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", default="data/labels/germany_national_osm_solar_PRE_ground_cap.parquet",
                    help="the PRE-cap file, so the ground panel shows what the cap removed")
    ap.add_argument("--cutoff", default="2025-09-30")
    ap.add_argument("--out", default="results/germany_osm_validation_bands.csv")
    args = ap.parse_args()

    import sqlalchemy as sa

    from earthpv.labels import dissolve_overlapping
    from earthpv.mastr import GROUND_ART, ROOFTOP_ART
    from earthpv.mastr_validation import DEFAULT_MASTR_SQLITE

    eng = sa.create_engine(f"sqlite:///{DEFAULT_MASTR_SQLITE}")
    units = pd.read_sql(sa.text("""
        SELECT "Laengengrad" lon, "Breitengrad" lat, "Bruttoleistung" kwp,
               "ArtDerSolaranlage" art
        FROM solar_extended
        WHERE "Inbetriebnahmedatum" <= :c AND "Bruttoleistung" IS NOT NULL
          AND "Laengengrad" IS NOT NULL
          AND ("EinheitBetriebsstatus" = 'In Betrieb'
               OR ("DatumEndgueltigeStilllegung" IS NOT NULL
                   AND "DatumEndgueltigeStilllegung" > :c))
    """), eng, params={"c": args.cutoff})

    osm = gpd.read_parquet(args.osm)
    d = dissolve_overlapping(osm, group_col="placement")
    rows = []

    for placement, arts, bins, labs, assumed in (
            ("rooftop", ROOFTOP_ART, ROOF_BINS, ROOF_LAB, 0.18),
            ("ground", GROUND_ART, GROUND_BINS, GROUND_LAB, 0.05)):
        poly = d[d.placement == placement].reset_index(drop=True)
        u = units[units.art.isin(arts)]
        pts = gpd.GeoDataFrame({"kwp": u.kwp.to_numpy()},
                               geometry=gpd.points_from_xy(u.lon, u.lat), crs="EPSG:4326")
        j = gpd.sjoin(pts, poly[["geometry"]], how="inner", predicate="within")
        n_units = j.groupby("index_right").size()
        cap = j.groupby("index_right").kwp.sum()
        poly["n_units"] = poly.index.map(n_units).fillna(0).astype(int)
        poly["reg_kwp"] = poly.index.map(cap).fillna(0.0)
        poly["band"] = pd.cut(poly.area_m2, bins, labels=labs, right=False)

        for lab in labs:
            s = poly[poly.band == lab]
            if s.empty:
                continue
            # One unit only: removes address-point crowding, which otherwise makes small
            # polygons look like they carry three times full module coverage.
            one = s[s.n_units == 1]
            measured = (float(one.reg_kwp.sum() / one.area_m2.sum())
                        if len(one) >= 20 and one.area_m2.sum() > 0 else np.nan)
            if measured == measured:
                measured = min(measured, 0.20)  # physical ceiling: full module coverage
            rows.append({
                "placement": placement, "band": lab,
                "n_polygons": int(len(s)),
                "area_km2": round(float(s.area_m2.sum() / 1e6), 2),
                "n_matched_one_unit": int(len(one)),
                "pct_with_registered_unit": round(float((s.n_units > 0).mean() * 100), 1),
                "assumed_kwp_per_m2": assumed,
                "measured_kwp_per_m2": (round(measured, 4) if measured == measured else ""),
                "gwp_at_assumed": round(float(s.area_m2.sum() * assumed / 1e6), 3),
                "gwp_at_measured": (round(float(s.area_m2.sum() * measured / 1e6), 3)
                                    if measured == measured else ""),
            })

    out = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(out.to_string(index=False))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
