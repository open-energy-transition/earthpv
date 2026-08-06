"""Export every detected rooftop-PV candidate for one AOI as a single JOSM validation layer.

Existing JOSM-facing exports are all narrower than this: `export_calibration_quadrats_
geojson.py` shows already-*mapped* OSM solar inside the 18 hand-checked quadrats, and
`build_small_pv_josm_leads.py` shows the sub-400 m2 roofclf/SPPI leads, capped per cell.
Neither answers "show me every place the segmentation model itself found a rooftop array,
everywhere in the country" -- this does, straight from `postprocess`'s own candidate
population (`data/predictions/<aoi>/candidates.parquet`), no ranking or per-cell cap.

By default this is **all >= 400 m2 rooftop-placed candidates**, matched-to-OSM or not: the
model's rooftop detections at their most direct, meant for a broad visual sanity pass in
JOSM against high-resolution imagery, not a prioritised mapping queue (for that, see
`export.py`'s new-leads/MapRoulette outputs, or `pixi run small-pv-leads` below the floor).
`--placement` widens the population to ground-mount/no-building candidates, `--unmatched-
only` narrows it to candidates with no nearby OSM feature, and `--min-confidence` drops
low-confidence rows -- all repeatable knobs, not one-off edits to this file.

**This is unverified model output, not existing OSM data.** Unlike the calibration
export (a copy of real, already-mapped features), every polygon here is a detection this
project's own segmentation model produced and has NOT been checked by a person -- some
of it will be false positives, and the known worst offenders (`oversize`, see
`postprocess.MAX_CANDIDATE_M2`) are flagged, not hidden. Never create or edit an OSM
feature directly from this layer without confirming it against imagery first.

    pixi run rooftop-detections-export
    python scripts/export_rooftop_detections_geojson.py --aoi pakistan --placement all
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402

DO_NOT_UPLOAD = (
    "earthpv model detection, NOT verified OSM data -- confirm against imagery before "
    "any OSM edit"
)

MAPCSS = """\
/* earthpv rooftop-detection JOSM validation layer.
   JOSM: Preferences -> Map Paint Styles -> + -> point at this file.
   Colours by whether OSM already has a matching feature nearby, and flags oversize
   candidates separately -- postprocess.MAX_CANDIDATE_M2 documents these as the model's
   worst-known false-positive mode (touching thresholded pixels merged with no upper
   bound, so a sheet of false positives becomes one multi-km2 "installation"). */

way[feature_type=rooftop_detection] {
    color: #2ec7ff;
    width: 2;
    fill-color: #2ec7ff;
    fill-opacity: 0.35;
    z-index: 100;
}

/* Already has a nearby OSM feature -- lower priority to check, it is at least known. */
way[feature_type=rooftop_detection][osm_matched=yes] {
    color: #ffb000;
    fill-color: #ffb000;
}

/* postprocess.MAX_CANDIDATE_M2: touching pixels merged with no upper bound -- the
   project's worst-known false-positive mode. Check these first. */
way[feature_type=rooftop_detection][oversize=yes] {
    color: #ff3b30;
    fill-color: #ff3b30;
    fill-opacity: 0.25;
    width: 3;
}
"""


def _clean(v):
    """JSON-safe scalar; NaN becomes None rather than the invalid-JSON literal NaN."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 6)
    return v


def _feature(geom, props: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {k: v for k, v in props.items() if v is not None},
        "geometry": mapping(geom),
    }


def _province_summary(cands: gpd.GeoDataFrame, density_dir: Path) -> pd.DataFrame | None:
    """Per-province candidate count/area, purely for the printed sanity check -- skipped
    (not an error) if this AOI has no `density` run to join against."""
    regions_path = density_dir / "regions.geoparquet"
    if not regions_path.exists():
        return None
    reg = gpd.read_parquet(regions_path)
    reg = reg[reg.level == "region"]
    pts = gpd.GeoDataFrame(
        cands[["area_m2"]], geometry=cands.geometry.representative_point(), crs=cands.crs,
    )
    joined = gpd.sjoin(pts, reg[["name", "geometry"]], predicate="within", how="left")
    out = (
        joined.groupby("name", dropna=False)["area_m2"]
        .agg(n="count", total_area_m2="sum")
        .sort_values("n", ascending=False)
        .reset_index()
        .rename(columns={"name": "province"})
    )
    out["province"] = out["province"].fillna("(outside any province polygon)")
    return out


def build(
    cands: gpd.GeoDataFrame, placement: str, min_confidence: float | None,
    unmatched_only: bool,
) -> tuple[gpd.GeoDataFrame, list[dict]]:
    if placement != "all":
        cands = cands[cands["placement"] == placement]
    if min_confidence is not None:
        cands = cands[cands["confidence"] >= min_confidence]
    if unmatched_only:
        cands = cands[cands["osm_matched_id"].isna()]
    cands = cands.reset_index(drop=True)

    feats = []
    for i, r in enumerate(cands.itertuples()):
        matched = pd.notna(getattr(r, "osm_matched_id", None))
        feats.append(_feature(r.geometry, {
            "feature_type": "rooftop_detection",
            "candidate_id": i,
            "placement": _clean(getattr(r, "placement", None)),
            "area_m2": round(float(getattr(r, "area_m2", 0.0) or 0.0), 1),
            "confidence": _clean(getattr(r, "confidence", None)),
            "rank_score": _clean(getattr(r, "rank_score", None)),
            "oversize": "yes" if bool(getattr(r, "oversize", False)) else "no",
            "osm_matched": "yes" if matched else "no",
            "osm_match_dist_m": (
                round(float(r.osm_match_dist_m), 1)
                if matched and pd.notna(getattr(r, "osm_match_dist_m", None)) else None
            ),
            "building_overlap_frac": _clean(getattr(r, "building_overlap_frac", None)),
            "do_not_upload": DO_NOT_UPLOAD,
        }))
    return cands, feats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--pred-dir", default="data/predictions")
    ap.add_argument(
        "--placement", default="rooftop",
        choices=["rooftop", "ground_adjacent", "no_building", "all"],
        help="candidate placement to include (default: rooftop only)",
    )
    ap.add_argument(
        "--min-confidence", type=float, default=None,
        help="drop candidates below this confidence (default: no filter, everything "
             "postprocess kept)",
    )
    ap.add_argument(
        "--unmatched-only", action="store_true",
        help="only candidates with no nearby OSM feature (osm_matched_id is null) -- "
             "a prioritised leads view rather than the full detected population",
    )
    ap.add_argument("--out", default=None, help="default results/<aoi>_rooftop_detections_josm.geojson")
    ap.add_argument("--no-mapcss", action="store_true", help="skip the sibling JOSM style")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    pred_dir = Path(args.pred_dir) / args.aoi
    candidates_path = pred_dir / "candidates.parquet"
    if not candidates_path.exists():
        raise SystemExit(f"{candidates_path} not found -- run `earthpv postprocess` first")
    cands = gpd.read_parquet(candidates_path)

    cands, feats = build(cands, args.placement, args.min_confidence, args.unmatched_only)
    if not feats:
        raise SystemExit(
            f"no candidates matched --placement={args.placement!r} "
            f"--min-confidence={args.min_confidence} --unmatched-only={args.unmatched_only}"
        )

    out = Path(args.out) if args.out else Path("results") / f"{args.aoi}_rooftop_detections_josm.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "type": "FeatureCollection",
        "name": out.stem,
        "earthpv": {
            "purpose": "visual JOSM sanity pass over every detected rooftop-PV candidate",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aoi": args.aoi,
            "placement_filter": args.placement,
            "min_confidence": args.min_confidence,
            "unmatched_only": args.unmatched_only,
            "n_candidates": len(feats),
            "max_candidate_m2": MAX_CANDIDATE_M2,
            "warning": DO_NOT_UPLOAD,
        },
        "features": feats,
    }
    out.write_text(json.dumps(doc, indent=1) + "\n")

    n_oversize = int((cands["oversize"]).sum()) if "oversize" in cands.columns else 0
    n_matched = int(cands["osm_matched_id"].notna().sum())
    total_area = float(cands["area_m2"].sum())
    print(
        f"{len(cands):,} candidates ({args.placement}), {total_area:,.0f} m2 total, "
        f"{n_matched:,} already OSM-matched, {n_oversize:,} oversize (>= "
        f"{MAX_CANDIDATE_M2:,.0f} m2, check these first) -> {out}"
    )

    prov = _province_summary(cands, pred_dir / "density")
    if prov is not None:
        print()
        print(prov.to_string(index=False))
    else:
        print(f"\n(no density/regions.geoparquet for {args.aoi} -- skipping province breakdown)")

    if not args.no_mapcss:
        style = out.with_suffix(".mapcss")
        style.write_text(MAPCSS)
        print(f"\nJOSM style -> {style}  (Preferences -> Map Paint Styles -> + -> this file)")
    print(f"\nReminder: {DO_NOT_UPLOAD}.")


if __name__ == "__main__":
    main()
