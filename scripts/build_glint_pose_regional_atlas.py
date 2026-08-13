"""Build a standalone, night-lights-style atlas page for the regional glint/pose
re-cut (`docs/methods/glint.md`'s "Detection rate, validation rate, and fitted pose all
shift with latitude" section) -- province choropleth by validation rate, individual
target points, and a latitude-band bar chart, matching this project's other interactive
result pages (`src/earthpv/templates/pv_evidence_atlas.html` is the style reference).

Scratch-style analysis script, like `build_pv_external_comparison.py` -- not wired into
the `earthpv` CLI or the main pipeline, reads results already on disk
(`results/glint_pose_by_region_combined.csv`, `data/glint/pakistan_combined_points_
enriched.parquet`, both written by `glint_orientation_region_topup.py` +
`glint_pose_by_region.py`).

Usage:
    .pixi/envs/default/bin/python scripts/build_glint_pose_regional_atlas.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.atlas import _rings  # noqa: E402 -- same ring simplification the other atlases use

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_CSV = ROOT / "results/glint_pose_by_region_combined.csv"
POINTS_PARQUET = ROOT / "data/glint/pakistan_combined_points_enriched.parquet"
REGIONS_PARQUET = ROOT / "data/labels/pakistan_regions.parquet"
TEMPLATE = ROOT / "src/earthpv/templates/glint_pose_regional_atlas.html"
OUT = ROOT / "results/pakistan_glint_pose_regional.html"

MIN_N_FOR_POSE_STATS = 20


def main() -> None:
    summary = pd.read_csv(SUMMARY_CSV)
    points = gpd.read_parquet(POINTS_PARQUET)
    regions = gpd.read_parquet(REGIONS_PARQUET).to_crs(4326)

    prov_rows = summary[summary["group"].str.startswith("province ")].copy()
    prov_rows["province"] = prov_rows["group"].str.replace("province ", "", regex=False)
    lat_rows = summary[summary["group"].str.startswith("lat ")].copy()
    lat_rows["lat_band"] = lat_rows["group"].str.replace("lat ", "", regex=False)

    provinces = []
    for r in regions.itertuples():
        match = prov_rows[prov_rows["province"] == r.name]
        stats = match.iloc[0].to_dict() if len(match) else {}
        provinces.append({
            "name": r.name,
            "rings": _rings(r.geometry),
            "n_targets": int(stats.get("n_targets", 0) or 0),
            "pct_detected": float(stats.get("pct_detected", 0) or 0),
            "pct_validated": float(stats.get("pct_validated", 0) or 0),
            "reliable": bool(stats.get("pose_stats_reliable", False)),
        })

    lat_bands = [
        {
            "label": r.lat_band,
            "n_targets": int(r.n_targets),
            "pct_detected": float(r.pct_detected),
            "pct_validated": float(r.pct_validated),
            "median_tilt": None if pd.isna(r.median_tilt_deg) else float(r.median_tilt_deg),
            "az_min": None if pd.isna(r.az_min_deg) else float(r.az_min_deg),
            "az_max": None if pd.isna(r.az_max_deg) else float(r.az_max_deg),
            "reliable": bool(r.pose_stats_reliable),
        }
        for r in lat_rows.itertuples()
    ]

    pts_out = [
        {
            "lon": round(float(p.lon), 4), "lat": round(float(p.lat), 4),
            "detected": bool(p.detected), "validated": bool(p.validated),
            "placement": p.placement if isinstance(p.placement, str) else "unknown",
        }
        for p in points.itertuples()
    ]

    minx, miny, maxx, maxy = regions.total_bounds
    total = {
        "n_targets": int(len(points)),
        "n_country2000": 2000,
        "n_topup": int(len(points) - 2000),
        "pct_detected": round(100 * points["detected"].mean(), 1),
        "pct_validated": round(100 * points["validated"].mean(), 1),
        "n_reliable_groups": int(sum(g["reliable"] for g in lat_bands) + sum(p["reliable"] for p in provinces)),
        "n_groups": len(lat_bands) + len(provinces),
    }

    data = {
        "bounds": [round(minx, 3), round(miny, 3), round(maxx, 3), round(maxy, 3)],
        "provinces": provinces,
        "lat_bands": lat_bands,
        "points": pts_out,
        "totals": total,
    }

    html = TEMPLATE.read_text()
    html = html.replace("__PV_DATA_JSON__", json.dumps(data, separators=(",", ":")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"{total['n_targets']} targets ({total['n_country2000']} country2000 + {total['n_topup']} targeted top-up), "
          f"{total['pct_detected']}% detected, {total['pct_validated']}% validated -> {OUT}")


if __name__ == "__main__":
    main()
