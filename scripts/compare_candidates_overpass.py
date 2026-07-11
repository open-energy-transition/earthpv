"""Compare detected PV candidates against live OSM solar mappings (via Overpass).

Cross-references `pakistan_pv_candidates.geojson` against a fresh Overpass query for
`generator:source=solar` / `plant:source=solar` features across Pakistan's bbox. A
candidate that sits right on top of an already-mapped OSM solar feature is confirmed
real (mapped rooftop/plant); one with no nearby OSM feature at all is either a genuine
new lead or a false positive — this script doesn't decide which, it just gives you the
distance-to-nearest-real-feature so you can triage: candidates far from ANY OSM solar
feature AND far from other supporting evidence are the ones most worth checking first
in an editor.

Usage:
    pixi run python scripts/compare_candidates_overpass.py
    pixi run python scripts/compare_candidates_overpass.py --match-dist 100
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd

log = logging.getLogger(__name__)

CANDIDATES_PATH = Path("data/predictions/pakistan/pakistan_pv_candidates.geojson")
PAKISTAN_BBOX = (60.87, 23.80, 77.13, 37.09)  # matches configs/aoi.yaml pakistan.bbox
OUT_PATH = Path("data/predictions/pakistan/pakistan_pv_candidates_overpass_compared.geojson")
UNMATCHED_OUT_PATH = Path("data/predictions/pakistan/pakistan_pv_candidates_unmatched.geojson")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", type=Path, default=CANDIDATES_PATH)
    ap.add_argument("--match-dist", type=float, default=200.0,
                     help="Metres within which a candidate counts as OSM-confirmed")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--refresh", action="store_true",
                     help="Re-query Overpass even if --out already has a cached comparison")
    ap.add_argument("--top", type=int, default=25, help="How many top-suspicion rows to print")
    ap.add_argument("--unmatched-out", type=Path, default=UNMATCHED_OUT_PATH,
                     help="Where to write the filtered file with osm_match=True rows removed")
    args = ap.parse_args()

    if args.out.exists() and not args.refresh:
        log.info("Loading cached comparison from %s (pass --refresh to re-query Overpass)", args.out)
        cands = gpd.read_file(args.out)
    else:
        from earthpv.overpass import fetch_solar_overpass

        log.info("Loading candidates from %s", args.candidates)
        cands = gpd.read_file(args.candidates)
        log.info("Loaded %d candidates", len(cands))

        log.info("Querying Overpass for live OSM solar features across Pakistan (bbox=%s)...",
                  PAKISTAN_BBOX)
        osm = fetch_solar_overpass(bbox=PAKISTAN_BBOX, timeout=args.timeout)
        log.info("Overpass returned %d live OSM solar features", len(osm))
        if osm.empty:
            raise RuntimeError("Overpass returned zero features — check connectivity/query before trusting a 'no matches' result.")

        # Pakistan spans multiple UTM zones (41N-43N), so a single flat projection
        # introduces real (if modest — up to ~2km at 100km+ range) distance error.
        # Use a metric CRS only to find the nearest candidate cheaply via the spatial
        # index, then report the actual distance via geodesic calculation (matches
        # this codebase's established convention — see labels.py::geodesic_area_m2 —
        # of never trusting a flat projection for real-world distances/areas).
        utm = "EPSG:32643"
        cands_m = cands.to_crs(utm)
        osm_m = osm.to_crs(utm)

        (_, tree_idx) = osm_m.sindex.nearest(cands_m.geometry.values, return_all=False)

        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        nearest_dist = [
            geod.inv(
                cands.geometry.iloc[i].centroid.x, cands.geometry.iloc[i].centroid.y,
                osm.geometry.iloc[j].centroid.x, osm.geometry.iloc[j].centroid.y,
            )[2]
            for i, j in enumerate(tree_idx)
        ]

        cands["osm_nearest_dist_m"] = nearest_dist
        cands["osm_match"] = cands["osm_nearest_dist_m"] <= args.match_dist
        cands["osm_nearest_id"] = [osm.iloc[i]["id"] for i in tree_idx]

        n_matched = int(cands["osm_match"].sum())
        n_total = len(cands)
        log.info(
            "%d / %d candidates (%.1f%%) are within %.0fm of a live-mapped OSM solar feature",
            n_matched, n_total, 100 * n_matched / n_total if n_total else 0, args.match_dist,
        )
        log.info(
            "Distance-to-nearest-OSM-feature distribution (m): min=%.0f p25=%.0f median=%.0f "
            "p75=%.0f p90=%.0f max=%.0f",
            cands["osm_nearest_dist_m"].min(), cands["osm_nearest_dist_m"].quantile(.25),
            cands["osm_nearest_dist_m"].median(), cands["osm_nearest_dist_m"].quantile(.75),
            cands["osm_nearest_dist_m"].quantile(.90), cands["osm_nearest_dist_m"].max(),
        )

        args.out.parent.mkdir(parents=True, exist_ok=True)
        cands.to_file(args.out, driver="GeoJSON")
        log.info("Wrote %s (adds osm_match / osm_nearest_dist_m / osm_nearest_id columns)", args.out)

    # Filtered file: drop already-mapped candidates entirely, leaving only the ones
    # with no live OSM solar feature nearby — new leads or false positives, for
    # further triage without already-confirmed detections cluttering the view.
    unmatched_only = cands[~cands["osm_match"]].reset_index(drop=True)
    args.unmatched_out.parent.mkdir(parents=True, exist_ok=True)
    unmatched_only.to_file(args.unmatched_out, driver="GeoJSON")
    log.info(
        "Wrote %s: %d candidates with osm_match=True removed, %d remain",
        args.unmatched_out, int(cands["osm_match"].sum()), len(unmatched_only),
    )

    # Rank-based combined score rather than raw units (distance spans 0-149,000m while
    # confidence spans 0-1, so a naive product/sum would be dominated by distance alone).
    # Lowest combined rank = lowest confidence AND farthest from any real OSM feature —
    # the candidates with the least model conviction and the least corroborating evidence,
    # i.e. the likeliest actual false positives to check first.
    conf_rank = cands["confidence"].rank(ascending=True)
    dist_rank = cands["osm_nearest_dist_m"].rank(ascending=False)
    cands["fp_suspicion_rank"] = conf_rank + dist_rank
    suspects = cands.sort_values("fp_suspicion_rank", ascending=True)

    log.info(
        "Top %d candidates by combined suspicion (lowest confidence + farthest from any "
        "live-mapped OSM solar feature):",
        args.top,
    )
    for _, row in suspects.head(args.top).iterrows():
        c = row.geometry.centroid
        print(
            f"  {row.get('candidate_id', '?')}: conf={row.get('confidence', float('nan')):.2f} "
            f"dist_to_nearest_osm={row.osm_nearest_dist_m:.0f}m "
            f"area={row.get('area_m2', float('nan')):.0f}m2 "
            f"-> https://www.openstreetmap.org/edit#map=19/{c.y:.5f}/{c.x:.5f}"
        )


if __name__ == "__main__":
    main()
