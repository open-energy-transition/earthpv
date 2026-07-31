"""Small-PV (< 400 m2) validation leads for manual checking in JOSM.

Answers a narrower question than the density pipeline's own numbers: not "how much
capacity," but "does the Best-estimate instrument (roofclf, domain-restricted to the
93 density-calibrated cells) actually point at real, previously-unmapped installations
when a human looks at the imagery?" That is exactly what `sub400_central_incremental_
buildings.parquet` is FOR as a population (it is the same buildings whose summed area
becomes the `small_central` figure on the evidence atlas's Best tier), but it has never
itself been spot-checked as individual leads the way the >= 400 m2 candidate pipeline's
`_pv_new_leads.geojson` already is.

Two filters on top of what `sub400_capacity.domain_restricted_capacity` already applied:
- **Not already mapped**: dropped if within 30 m of an existing OSM solar feature
  (`export.filter_new_leads`, the same distance convention used throughout this project's
  "is this a new lead" checks) -- otherwise this file would mostly confirm installations
  already in OSM, not test whether the model finds anything NEW.
- **Top-N by predicted size**: the filtered population is still ~10^5 buildings, far more
  than one person reviews in a JOSM session. Sorted by `roof_area_m2` descending (larger
  roofs are both the model's most confident predictions here, roofclf's own AUC rising
  with size, and the easiest for a human to actually confirm or refute by eye in
  satellite imagery) and capped at `--limit` (default 300).

Usage:
    pixi run python scripts/build_small_pv_josm_leads.py
    pixi run python scripts/build_small_pv_josm_leads.py --limit 500
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd

from earthpv.export import filter_new_leads

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CENTRAL_BUILDINGS = (
    ROOT / "data" / "roofclf_national_with_sppi" / "pakistan" / "density"
    / "sub400_central_incremental_buildings.parquet"
)
OSM_SOLAR = ROOT / "data" / "labels" / "pakistan_overpass_solar.parquet"
OUT = ROOT / "results" / "pakistan_small_pv_josm_leads.geojson"

MIN_DISTANCE_M = 30.0


def _imagery_note(lon: float, lat: float) -> str:
    return (
        f"osm={lon:.5f},{lat:.5f} | "
        f"bing=https://www.bing.com/maps?cp={lat:.5f}~{lon:.5f}&lvl=19&style=a | "
        f"google=https://www.google.com/maps/@{lat:.5f},{lon:.5f},200m/data=!3m1!1e3"
    )


def build(limit: int) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    candidates = gpd.read_parquet(CENTRAL_BUILDINGS)
    log.info("Loaded %d domain-restricted, incremental sub-400 m2 buildings", len(candidates))

    mapped = gpd.read_parquet(OSM_SOLAR)
    new_leads = filter_new_leads(candidates, mapped, min_distance_m=MIN_DISTANCE_M)
    log.info(
        "%d/%d (%.1f%%) are not within %.0f m of an existing OSM solar feature -- these "
        "are the genuinely untested leads",
        len(new_leads), len(candidates), 100 * len(new_leads) / max(len(candidates), 1),
        MIN_DISTANCE_M,
    )

    new_leads = new_leads.sort_values("roof_area_m2", ascending=False).reset_index(drop=True)
    top = new_leads.head(limit).copy()

    centroids = top.geometry.representative_point()
    top["lead_id"] = [f"pakistan-small-pv-{i:04d}" for i in range(len(top))]
    top["est_kwp"] = (top["est_kwp_sub400"]).round(2)
    top["fixme"] = [
        f"Possible small rooftop PV ({row.roof_area_m2:.0f} m2 roof, roofclf-flagged, "
        "not near any existing OSM solar feature) -- check imagery; if real, map as "
        "generator:source=solar or power=generator + generator:source=solar"
        for row in top.itertuples()
    ]
    top["imagery_note"] = [
        _imagery_note(p.x, p.y) for p in centroids
    ]

    out_cols = ["lead_id", "cell", "roof_area_m2", "est_kwp", "fixme", "imagery_note", "geometry"]
    top = top[out_cols]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    top.to_file(OUT, driver="GeoJSON")
    log.info(
        "Wrote %d small-PV JOSM leads (of %d filtered, %d before OSM filter) -> %s",
        len(top), len(new_leads), len(candidates), OUT,
    )
    return OUT


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=300, help="Max leads to write (default 300)")
    args = ap.parse_args()
    build(args.limit)


if __name__ == "__main__":
    main()
