"""Export PV candidates for OSM validation workflows.

Outputs:
- candidates.geoparquet / candidates.geojson — full attribute set
- maproulette.geojson — line-delimited FeatureCollections (one task per candidate)
  with imagery links, ready to upload as a MapRoulette challenge.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd

log = logging.getLogger(__name__)


def _imagery_links(lon: float, lat: float) -> dict[str, str]:
    return {
        "osm": f"https://www.openstreetmap.org/edit#map=19/{lat:.5f}/{lon:.5f}",
        "bing": f"https://www.bing.com/maps?cp={lat:.5f}~{lon:.5f}&lvl=19&style=a",
        "google": f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},200m/data=!3m1!1e3",
    }


def run_export(aoi: str, pred_dir: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pred_dir = Path(pred_dir) / aoi
    cands = gpd.read_parquet(pred_dir / "candidates.parquet")
    if cands.empty:
        log.warning("No candidates to export for %s", aoi)
        return
    # rank_score blends model confidence with the building prior (postprocess); it
    # puts on-/near-building detections at the top of the validation queue while
    # keeping every candidate. Fall back to raw confidence for older outputs.
    sort_col = "rank_score" if "rank_score" in cands.columns else "confidence"
    cands = cands.sort_values(sort_col, ascending=False).reset_index(drop=True)
    cands["candidate_id"] = [f"{aoi}-pv-{i:06d}" for i in range(len(cands))]

    gpq = pred_dir / f"{aoi}_pv_candidates.geoparquet"
    cands.to_parquet(gpq)
    gj = pred_dir / f"{aoi}_pv_candidates.geojson"
    cands.to_file(gj, driver="GeoJSON")

    # MapRoulette: newline-delimited FeatureCollections (RFC 7464-style, MR "lineByLine")
    mr = pred_dir / f"{aoi}_pv_maproulette.geojson"
    with mr.open("w") as f:
        for _, row in cands.iterrows():
            c = row.geometry.centroid
            props = {
                "candidate_id": row.candidate_id,
                "confidence": round(float(row.confidence), 3),
                "rank_score": round(float(row.rank_score), 3) if "rank_score" in cands else None,
                "building_dist_m": (
                    round(float(row.building_dist_m), 1) if "building_dist_m" in cands else None
                ),
                "area_m2": round(float(row.area_m2), 1),
                "placement": row.placement,
                "instruction": (
                    f"Possible solar PV array (~{row.area_m2:.0f} m2, "
                    f"confidence {row.confidence:.2f}, {row.placement}). "
                    "Check imagery; if confirmed, map power=generator + "
                    "generator:source=solar + generator:method=photovoltaic"
                    + (" + location=roof" if row.placement == "rooftop" else "")
                ),
                **_imagery_links(c.x, c.y),
            }
            fc = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": row.geometry.__geo_interface__,
                        "properties": props,
                    }
                ],
            }
            f.write(json.dumps(fc) + "\n")
    log.info("Exported %d candidates -> %s, %s, %s", len(cands), gpq.name, gj.name, mr.name)
