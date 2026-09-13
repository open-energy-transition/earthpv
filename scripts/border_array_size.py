#!/usr/bin/env python
"""Installation size either side of the France-Germany border.

The France work found that French rooftop arrays are far smaller than Pakistani ones
relative to their roof, which is what stops `roofclf` working there. The obvious question is
whether that is a national policy artefact or something about the landscape, and the
France-Germany border is the natural experiment: same climate, same building stock, different
feed-in tariff history.

**The measurement trap this script is built around.** The two geolocated sources are not
equally complete. OpenPVMapper covers France at ~1.13M rooftop polygons from sub-metre
imagery; German OSM covers ~3.6% of registered rooftop units and is biased toward larger
installations, because a mapper is likelier to trace a big array. Comparing them directly
would show a jump roughly twice the real one. So this writes TWO series:

* the geolocated profile, honest about being biased on the German side, and
* a register anchor from ODRE and MaStR, which are both complete and therefore unbiased,
  but which France publishes only as per-commune aggregates, so it is a mean per unit in
  kWp rather than a distribution in m2.

Reading them together is the point: the profile shows WHERE the change happens, the register
anchor shows HOW BIG it really is.
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
log = logging.getLogger("border")

EQ_AREA = "EPSG:3035"          # ETRS89-LAEA, metres, correct for Europe
FR_BORDER_DEPS = ["67", "68", "57", "54", "88", "55", "90", "70", "25", "52"]
DE_BORDER_LAND = ["08", "07", "10"]   # AGS prefixes: Baden-Wuerttemberg, RP, Saarland
MAX_KM = 60.0
BIN_KM = 10.0


def shared_border(cache: Path) -> gpd.GeoSeries:
    """The FR-DE land border as one line, in EQ_AREA metres."""
    import urllib.request
    geoms = {}
    for iso in ("FRA", "DEU"):
        f = cache / f"gb_{iso}_adm0.geojson"
        if not f.exists():
            meta = json.loads(urllib.request.urlopen(
                urllib.request.Request(
                    f"https://www.geoboundaries.org/api/current/gbOpen/{iso}/ADM0/",
                    headers={"User-Agent": "earthpv/1.0"}), timeout=180).read())
            url = meta.get("simplifiedGeometryGeoJSON") or meta["gjDownloadURL"]
            f.write_bytes(urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "earthpv/1.0"}),
                timeout=300).read())
        g = gpd.read_file(f).to_crs(EQ_AREA)
        # Mainland only: the overseas departements would drag the union across the globe.
        g = g.explode(index_parts=False)
        g = g[g.geometry.area > 1e9]
        geoms[iso] = g.union_all()
    # The shared border is where the two national outlines touch. Buffer one side by a
    # kilometre so simplified outlines that do not coincide exactly still intersect.
    return gpd.GeoSeries([geoms["FRA"].boundary.intersection(geoms["DEU"].buffer(1000))],
                         crs=EQ_AREA)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/geoboundaries")
    ap.add_argument("--out", default="results/border_array_size.csv")
    ap.add_argument("--out-anchor", default="results/border_register_anchor.csv")
    args = ap.parse_args()

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    border = shared_border(cache)
    log.info("FR-DE border length: %.0f km", border.length.iloc[0] / 1000)
    bline = border.iloc[0]

    # ---- geolocated profile -------------------------------------------------------
    fr = gpd.read_parquet("data/openpvmapper/enriched_national.parquet",
                          columns=["dpt", "surface", "false_positive", "geometry"],
                          filters=[("dpt", "in", FR_BORDER_DEPS)])
    fr = fr[(fr.false_positive != True) & fr.surface.notna()]  # noqa: E712
    fr = fr.to_crs(EQ_AREA)
    fr["dist_km"] = -fr.geometry.representative_point().distance(bline) / 1000
    fr["area_m2"] = fr.surface
    fr["side"] = "France"
    log.info("France arrays within %.0f km: %d", MAX_KM, int((fr.dist_km > -MAX_KM).sum()))

    de = gpd.read_parquet("data/labels/germany_national_osm_solar.parquet",
                          columns=["placement", "area_m2", "geometry"])
    de = de[(de.placement == "rooftop") & (de.area_m2 >= 5)].to_crs(EQ_AREA)
    de["dist_km"] = de.geometry.representative_point().distance(bline) / 1000
    de["side"] = "Germany"
    log.info("Germany arrays within %.0f km: %d", MAX_KM, int((de.dist_km < MAX_KM).sum()))

    cols = ["dist_km", "area_m2", "side"]
    both = pd.concat([pd.DataFrame(fr[cols]), pd.DataFrame(de[cols])], ignore_index=True)
    both = both[both.dist_km.abs() <= MAX_KM]
    edges = np.arange(-MAX_KM, MAX_KM + BIN_KM, BIN_KM)
    both["bin"] = pd.cut(both.dist_km, edges, right=False)
    rows = []
    for (b, side), g in both.groupby(["bin", "side"], observed=True):
        if len(g) < 30:
            continue
        rows.append({"bin_lo_km": b.left, "bin_hi_km": b.right, "side": side, "n": len(g),
                     "median_m2": round(float(g.area_m2.median()), 1),
                     "p25_m2": round(float(g.area_m2.quantile(.25)), 1),
                     "p75_m2": round(float(g.area_m2.quantile(.75)), 1)})
    prof = pd.DataFrame(rows).sort_values(["side", "bin_lo_km"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    prof.to_csv(args.out, index=False)
    log.info("wrote %s (%d bins)", args.out, len(prof))

    # ---- register anchor ----------------------------------------------------------
    # Both registers are complete, so this is the unbiased version of the same question.
    # France publishes sub-36 kW only as per-commune aggregates, hence a mean per unit.
    # Matched bands: France's register censors below 36 kW into aggregates, so the only
    # statistic it can offer is a mean per sub-36 kW unit. Germany is cut to the SAME band
    # rather than to all rooftop units, or the comparison would be Germany's whole fleet
    # against France's small half.
    fr_cc = pd.read_parquet("results/france_validation_v6/commune_capacity.parquet")
    fr_cc["dep"] = fr_cc.insee.astype(str).str.zfill(5).str[:2]
    fb = fr_cc[fr_cc.dep.isin(["67", "68", "57"])]
    fr_n = float(fb.n_small_units.sum())
    fr_mean = float(fb.kw_small_agg.sum() / max(fr_n, 1))

    # `mastr_gemeinden.parquet`'s `n_units` counts EVERY solar row including ground-mount,
    # so it cannot give a rooftop mean; query the register directly instead.
    import sqlalchemy as sa

    from earthpv.mastr import ROOFTOP_ART
    from earthpv.mastr_validation import DEFAULT_MASTR_SQLITE
    eng = sa.create_engine(f"sqlite:///{DEFAULT_MASTR_SQLITE}")
    q = sa.text("""
        SELECT COUNT(*) AS n, SUM("Bruttoleistung") AS kw
        FROM solar_extended
        WHERE "ArtDerSolaranlage" = :art
          AND "Inbetriebnahmedatum" <= :cutoff
          AND "Bruttoleistung" IS NOT NULL AND "Bruttoleistung" < 36
          AND substr("Gemeindeschluessel", 1, 2) IN ('08','07','10')
          AND ("EinheitBetriebsstatus" = 'In Betrieb'
               OR ("DatumEndgueltigeStilllegung" IS NOT NULL
                   AND "DatumEndgueltigeStilllegung" > :cutoff))
    """)
    de_row = pd.read_sql(q, eng, params={"art": ROOFTOP_ART[0], "cutoff": "2025-09-30"}).iloc[0]
    de_n, de_mean = float(de_row.n), float(de_row.kw) / max(float(de_row.n), 1)

    anchor = pd.DataFrame([
        {"side": "France", "source": "ODRE register, sub-36 kW, dep 67/68/57",
         "n_units": int(fr_n), "mean_kwp_per_unit": round(fr_mean, 3),
         "implied_m2_at_0p15": round(fr_mean / 0.15, 1)},
        {"side": "Germany", "source": "MaStR register, rooftop sub-36 kW, BW/RP/Saarland",
         "n_units": int(de_n), "mean_kwp_per_unit": round(de_mean, 3),
         "implied_m2_at_0p15": round(de_mean / 0.15, 1)},
    ])
    anchor.to_csv(args.out_anchor, index=False)
    log.info("wrote %s", args.out_anchor)
    print(prof.to_string(index=False))
    print()
    print(anchor.to_string(index=False))
    print(f"\nregister ratio Germany/France: {de_mean / fr_mean:.2f}x")


if __name__ == "__main__":
    main()
