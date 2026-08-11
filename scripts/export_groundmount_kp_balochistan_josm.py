"""Export the largest ground-mount candidates in Khyber Pakhtunkhwa and Balochistan as
one JOSM validation layer.

These two provinces are `check-density`'s worst plausibility failures (KP ground:rooftop
ratio 3.35-8x measured across several density re-derivations this project's history,
Balochistan 3.9-18x) -- bare rock, dry riverbed and salt flat terrain reads bright in a
dry-season Sentinel-2 composite with nothing to constrain it to a real installation,
exactly the failure mode `postprocess.MAX_CANDIDATE_M2` exists to catch for the largest
blobs and cannot catch for smaller ones. No pipeline fix substitutes for a human actually
looking at the largest candidates in these two regions against high-resolution imagery --
this script generates that JOSM layer; it does not review it.

    python scripts/export_groundmount_kp_balochistan_josm.py --aoi pakistan --top-n 40
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
from shapely.geometry import mapping  # noqa: E402

DO_NOT_UPLOAD = (
    "earthpv model detection, NOT verified OSM data -- confirm against imagery before "
    "any OSM edit"
)
PROVINCES = ("Khyber Pakhtunkhwa", "Balochistan")

MAPCSS = """\
/* earthpv ground-mount candidate JOSM validation layer -- KP + Balochistan largest.
   JOSM: Preferences -> Map Paint Styles -> + -> point at this file. */
way[feature_type=groundmount_candidate] {
    color: #ff9500;
    width: 2;
    fill-color: #ff9500;
    fill-opacity: 0.30;
    z-index: 100;
}
way[feature_type=groundmount_candidate][oversize=yes] {
    color: #ff3b30;
    fill-color: #ff3b30;
    fill-opacity: 0.25;
    width: 3;
}
way[feature_type=groundmount_candidate][osm_matched=yes] {
    color: #34c759;
    fill-color: #34c759;
}
"""


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 6)
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--pred-dir", default="data/predictions")
    ap.add_argument("--top-n", type=int, default=40, help="Largest N candidates PER PROVINCE")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    pred_dir = Path(args.pred_dir) / args.aoi
    cands = gpd.read_parquet(pred_dir / "candidates.parquet")
    ground = cands[cands["placement"].isin(["no_building", "ground_adjacent"])].copy()

    regions = gpd.read_parquet(pred_dir / "density" / "regions.geoparquet")
    regions = regions[regions["level"] == "region"]
    regions = regions[regions["name"].isin(PROVINCES)]
    if regions.empty:
        raise SystemExit(f"No region polygons found for {PROVINCES} in {pred_dir}/density/regions.geoparquet")

    joined = gpd.sjoin(
        ground, regions[["name", "geometry"]], how="inner", predicate="intersects"
    )

    features = []
    summary = []
    for province in PROVINCES:
        sub = joined[joined["name"] == province].sort_values("area_m2", ascending=False)
        top = sub.head(args.top_n)
        summary.append((province, len(sub), len(top), float(top["area_m2"].sum()) / 1e6))
        for row in top.itertuples():
            props = {
                "feature_type": "groundmount_candidate",
                "province": province,
                "area_m2": _clean(getattr(row, "area_m2", None)),
                "confidence": _clean(getattr(row, "confidence", None)),
                "placement": getattr(row, "placement", None),
                "oversize": "yes" if getattr(row, "oversize", False) else "no",
                "geometry_source": getattr(row, "geometry_source", None),
                "osm_matched": "yes" if pd.notna(getattr(row, "osm_matched_id", None)) else "no",
                "do_not_upload": DO_NOT_UPLOAD,
            }
            features.append(_feature(row.geometry, props))

    out = Path(args.out) if args.out else Path("results") / f"{args.aoi}_groundmount_kp_balochistan_josm.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "type": "FeatureCollection",
        "name": out.stem,
        "earthpv": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "aoi": args.aoi, "provinces": list(PROVINCES), "top_n_per_province": args.top_n,
        },
        "features": features,
    }, indent=None))
    mapcss_path = out.with_suffix(".mapcss")
    mapcss_path.write_text(MAPCSS)

    print(f"wrote {out} ({len(features)} candidates) and {mapcss_path}")
    for province, n_total, n_top, top_km2 in summary:
        print(f"  {province}: {n_top}/{n_total} ground-mount candidates shown, "
              f"{top_km2:.2f} km2 of the largest")
    print("\nReminder: earthpv model detection, NOT verified OSM data -- confirm against "
          "imagery before any OSM edit. This layer has NOT been reviewed.")


def _feature(geom, props: dict) -> dict:
    return {"type": "Feature", "properties": {k: v for k, v in props.items() if v is not None},
            "geometry": mapping(geom)}


if __name__ == "__main__":
    main()
