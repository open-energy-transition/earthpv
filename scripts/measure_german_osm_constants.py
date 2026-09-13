#!/usr/bin/env python
"""Measure what a German OSM solar polygon is actually worth in kWp per m2.

Germany's Verified tier is hand-mapped OSM area times two assumed constants, and it fails a
register check that cannot be argued with: its ground-mount component alone is 43,965 MWp
against 37,138 MWp of ALL registered German ground-mount. 118% is impossible, so at least one
constant is wrong for German OSM geometry. The documented cause is mapper convention -- German
polygons outline roofs and whole sites rather than module arrays -- with implied kWp/m2
reported anywhere from 0.02 to 0.99 against an assumed 0.18.

MaStR can settle it because it geolocates the placement that matters: **81.2% of ground-mount
units carry coordinates** (14,357 of 17,674, 37.19 GWp), against 5.2% of rooftop units. So a
registered unit's coordinate falling inside an OSM polygon pairs a true capacity with a mapped
area, and the ratio is the constant that polygon deserves.

**Three things this is careful about.** OSM polygons are dissolved first, because a
`power=plant` perimeter with nested `power=generator` ways would otherwise split one
installation's capacity across two areas and halve the ratio. Capacity is summed per polygon,
because a plant is usually many registered units. And the constant is reported area-weighted
rather than as a median of ratios, since that is how it is applied: total capacity over total
area, so large sites carry the weight they actually have.

The rooftop constant is measured the same way but is a **lower bound on confidence**, not a
recommendation: 5.2% coordinate coverage, skewed to units at or above 30 kWp, is a biased
sample of a population dominated by sub-10 kWp systems.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-constants")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", default="data/labels/germany_national_osm_solar.parquet")
    ap.add_argument("--cutoff", default="2025-09-30")
    ap.add_argument("--out", default="results/germany_osm_conversion_constants.json")
    args = ap.parse_args()

    import sqlalchemy as sa

    from earthpv.labels import dissolve_overlapping, geodesic_area_m2
    from earthpv.mastr import GROUND_ART, ROOFTOP_ART
    from earthpv.mastr_validation import DEFAULT_MASTR_SQLITE

    eng = sa.create_engine(f"sqlite:///{DEFAULT_MASTR_SQLITE}")
    q = sa.text("""
        SELECT "Laengengrad" AS lon, "Breitengrad" AS lat, "Bruttoleistung" AS kwp,
               "ArtDerSolaranlage" AS art
        FROM solar_extended
        WHERE "Inbetriebnahmedatum" <= :c AND "Bruttoleistung" IS NOT NULL
          AND "Laengengrad" IS NOT NULL AND "Breitengrad" IS NOT NULL
          AND ("EinheitBetriebsstatus" = 'In Betrieb'
               OR ("DatumEndgueltigeStilllegung" IS NOT NULL
                   AND "DatumEndgueltigeStilllegung" > :c))
    """)
    units = pd.read_sql(q, eng, params={"c": args.cutoff})
    log.info("geolocated register units: %d (%.1f GWp)", len(units), units.kwp.sum() / 1e6)

    osm = gpd.read_parquet(args.osm)
    osm = osm[osm.geometry.notna() & osm.geometry.is_valid].to_crs("EPSG:4326")
    out: dict = {"cutoff": args.cutoff, "placements": {}}

    for placement, arts, assumed in (("ground", GROUND_ART, 0.05),
                                     ("rooftop", ROOFTOP_ART, 0.18)):
        sub_osm = osm[osm.placement == placement][["geometry"]].reset_index(drop=True)
        if sub_osm.empty:
            continue
        # Dissolve first: a plant perimeter with nested generator ways is ONE installation,
        # and splitting its capacity across both areas would halve the measured constant.
        dissolved = dissolve_overlapping(sub_osm)
        dissolved = dissolved.reset_index(drop=True)
        dissolved["area_m2"] = [geodesic_area_m2(g) for g in dissolved.geometry]
        dissolved = dissolved[dissolved.area_m2 > 0].reset_index(drop=True)

        u = units[units.art.isin(arts)]
        pts = gpd.GeoDataFrame({"kwp": u.kwp.to_numpy()},
                               geometry=gpd.points_from_xy(u.lon, u.lat), crs="EPSG:4326")
        j = gpd.sjoin(pts, dissolved[["geometry"]], how="inner", predicate="within")
        if j.empty:
            log.warning("%s: no register unit falls inside any OSM polygon", placement)
            continue
        # Sum capacity per polygon: a plant is usually many registered units.
        cap = j.groupby("index_right").kwp.sum()
        matched = dissolved.loc[cap.index].copy()
        matched["kwp"] = cap.to_numpy()
        matched["kwp_per_m2"] = matched.kwp / matched.area_m2

        area_weighted = float(matched.kwp.sum() / matched.area_m2.sum())
        qs = matched.kwp_per_m2.quantile([.1, .25, .5, .75, .9])
        out["placements"][placement] = {
            "assumed_constant": assumed,
            "measured_area_weighted_kwp_per_m2": round(area_weighted, 5),
            "ratio_measured_over_assumed": round(area_weighted / assumed, 3),
            "n_osm_polygons_total": int(len(dissolved)),
            "n_matched_polygons": int(len(matched)),
            "matched_area_km2": round(float(matched.area_m2.sum() / 1e6), 2),
            "matched_capacity_gwp": round(float(matched.kwp.sum() / 1e6), 3),
            "register_units_with_coords": int(len(u)),
            "coordinate_coverage_note": (
                "81.2% of ground units carry coordinates; only 5.2% of rooftop units do, "
                "skewed to >= 30 kWp, so the rooftop figure is a biased sample"),
            "per_polygon_quantiles": {f"p{int(k*100)}": round(float(v), 5)
                                      for k, v in qs.items()},
        }
        log.info("%s: %d matched polygons, %.2f km2, %.2f GWp -> %.5f kWp/m2 "
                 "(assumed %.2f, ratio %.2f)", placement, len(matched),
                 matched.area_m2.sum() / 1e6, matched.kwp.sum() / 1e6, area_weighted,
                 assumed, area_weighted / assumed)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\n{'placement':<10}{'assumed':>9}{'measured':>11}{'ratio':>8}{'matched':>10}"
          f"{'GWp':>8}")
    for k, v in out["placements"].items():
        print(f"{k:<10}{v['assumed_constant']:>9.3f}{v['measured_area_weighted_kwp_per_m2']:>11.5f}"
              f"{v['ratio_measured_over_assumed']:>8.2f}{v['n_matched_polygons']:>10,}"
              f"{v['matched_capacity_gwp']:>8.2f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
