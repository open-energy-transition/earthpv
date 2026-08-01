"""Rooftop-potential validation leads for manual site-visit / JOSM review.

Ranks buildings from `potential.large_roof_buildings` (>= 200 m2, pure footprint
geometry -- see that module for why this carries none of the sub-400 m2 calibration
caveats documented elsewhere in this project) by `roof_area_m2 * kwh_per_kwp_yr` at the
building's own cell -- raw size times modelled annual irradiance, the same combination
`atlas.py::build_potential_atlas` uses to color its Potential tab, just evaluated per
building rather than summed per cell.

A per-building "already covered" ratio (like density.py's `pv_ratio_exp`) isn't
available for buildings outside density's signal-building table -- most large-but-
uncovered buildings, by construction, never appear there -- so this script instead
drops any building already close to a known PV source: an existing detected candidate
polygon (`candidates.parquet`) or a hand-mapped OSM solar feature. Both reuse
`export.filter_new_leads`, the same distance convention used throughout this project's
"is this a new lead" checks.

Capped at N per 0.1 deg cell (default 6, matching `build_small_pv_josm_leads.py`) before
an overall --limit, so the sample spans the checked country instead of clustering into
whichever cell has the single largest roof.

Usage:
    pixi run potential-leads
    pixi run python scripts/build_potential_leads.py --limit 300
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd

from earthpv.export import filter_new_leads
from earthpv.pv_capacity import grid_specific_yield, interpolate_yield

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
LARGE_ROOF_BUILDINGS = (
    ROOT / "data" / "predictions" / "pakistan" / "potential" / "large_roof_buildings.parquet"
)
CANDIDATES_PATH = ROOT / "data" / "predictions" / "pakistan" / "candidates.parquet"
OSM_SOLAR = ROOT / "data" / "labels" / "pakistan_overpass_solar.parquet"
IRRADIANCE_CACHE = ROOT / "data" / "predictions" / "pakistan" / "density" / "irradiance_probes.csv"
RESULTS_DIR = ROOT / "results"
OUT_PATH = RESULTS_DIR / "pakistan_potential_leads.geojson"

MIN_DISTANCE_M = 30.0
KWP_PER_M2_MODULE = 0.18


def _imagery_note(lon: float, lat: float) -> str:
    return (
        f"osm={lon:.5f},{lat:.5f} | "
        f"bing=https://www.bing.com/maps?cp={lat:.5f}~{lon:.5f}&lvl=19&style=a | "
        f"google=https://www.google.com/maps/@{lat:.5f},{lon:.5f},200m/data=!3m1!1e3"
    )


def build(limit: int, per_cell: int) -> Path:
    buildings = gpd.read_parquet(LARGE_ROOF_BUILDINGS)
    log.info("Loaded %d large-roof buildings", len(buildings))

    candidates = gpd.read_parquet(CANDIDATES_PATH)
    not_detected = filter_new_leads(buildings, candidates, min_distance_m=MIN_DISTANCE_M)
    log.info(
        "%d/%d (%.1f%%) are not within %.0f m of an existing detected candidate -- "
        "these are the genuinely uncovered leads",
        len(not_detected), len(buildings), 100 * len(not_detected) / max(len(buildings), 1),
        MIN_DISTANCE_M,
    )

    if OSM_SOLAR.exists():
        mapped = gpd.read_parquet(OSM_SOLAR)
        new_leads = filter_new_leads(not_detected, mapped, min_distance_m=MIN_DISTANCE_M)
        log.info(
            "%d/%d (%.1f%%) are also not within %.0f m of a hand-mapped OSM solar feature",
            len(new_leads), len(not_detected),
            100 * len(new_leads) / max(len(not_detected), 1), MIN_DISTANCE_M,
        )
    else:
        log.warning("%s not found -- skipping the OSM-mapped filter", OSM_SOLAR)
        new_leads = not_detected

    bounds = tuple(new_leads.total_bounds)
    probes = grid_specific_yield(bounds, IRRADIANCE_CACHE)
    centroids = new_leads.geometry.representative_point()
    new_leads = new_leads.copy()
    new_leads["kwh_per_kwp_yr"] = interpolate_yield(
        probes, centroids.x.to_numpy(), centroids.y.to_numpy()
    )
    new_leads["score"] = new_leads["roof_area_m2"] * new_leads["kwh_per_kwp_yr"]

    new_leads = new_leads.sort_values("score", ascending=False).reset_index(drop=True)
    spread = new_leads.groupby("cell", group_keys=False).head(per_cell)
    spread = spread.sort_values("score", ascending=False).reset_index(drop=True)
    log.info(
        "%d leads remain after capping at %d per cell (%d distinct cells); taking top %d",
        len(spread), per_cell, spread["cell"].nunique(), limit,
    )
    top = spread.head(limit).copy()

    centroids = top.geometry.representative_point()
    top["lead_id"] = [f"pakistan-potential-{i:04d}" for i in range(len(top))]
    top["est_kwp"] = (top["roof_area_m2"] * KWP_PER_M2_MODULE).round(2)
    top["est_gwh_yr"] = (top["est_kwp"] * top["kwh_per_kwp_yr"] / 1e6).round(4)
    top["fixme"] = [
        f"Large roof ({r.roof_area_m2:.0f} m2), no detected PV nearby, modelled "
        f"{r.kwh_per_kwp_yr:.0f} kWh/kWp/yr -- a rooftop SITING OPPORTUNITY, not a "
        "detection of existing PV; check imagery to confirm the roof is real, "
        "accessible and unshaded before treating it as a genuine lead"
        for r in top.itertuples()
    ]
    top["imagery_note"] = [_imagery_note(p.x, p.y) for p in centroids]

    out_cols = [
        "lead_id", "cell", "roof_area_m2", "kwh_per_kwp_yr", "est_kwp", "est_gwh_yr",
        "fixme", "imagery_note", "geometry",
    ]
    top = top[out_cols]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    top.to_file(OUT_PATH, driver="GeoJSON")
    log.info(
        "Wrote %d potential leads (of %d filtered, %d before filters) -> %s",
        len(top), len(new_leads), len(buildings), OUT_PATH,
    )
    return OUT_PATH


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=300, help="Max leads to write (default 300)")
    ap.add_argument("--per-cell", type=int, default=6, help="Max leads per 0.1 deg cell (default 6)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build(args.limit, args.per_cell)


if __name__ == "__main__":
    main()
