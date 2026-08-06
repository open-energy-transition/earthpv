"""Export buildings `roofclf` flags as PV-carrying as one JOSM validation layer.

Companion to `export_rooftop_detections_geojson.py`, which shows the segmentation
model's >= 400 m2 candidates. This shows the OTHER instrument: `roofclf`, a per-building
classifier trained on the hand-mapped calibration quadrats to catch PV *below* the
segmentation floor (see CLAUDE.md's "Sub-400 m2 instruments"). Reads a national
`roofclf.score_buildings_national` scoring directory directly (cell/geometry/
roof_area_m2/p_roofclf/sppi per building), not a pre-built capacity artifact -- so
this always shows exactly what the classifier flagged, not a derived MWp number.

**Why this is capped, unlike the segmentation export.** roofclf's raw national output
is enormous and, unrestricted, not something this project treats as plausible: at the
current deployment threshold it flags ~5.95 million buildings nationally (see
`roofclf_capacity.py` / CLAUDE.md's rejected flat-precision fold-in, 79 GWp implausible
against a 5 GWp segmentation total). A GeoJSON that large cannot be opened in JOSM
usefully and would mostly restate that known problem, not help anyone review images. So
by default this:

1. **Restricts to the density-calibrated domain** (`sub400_capacity.national_cell_domain`
   -- cells whose building density falls in the calibration quadrats' range, ~92 of
   4,463 nationally): the only population this project has any calibration evidence
   for, one way or the other.
2. **Caps per cell, then overall** (`--per-cell` / `--limit`, defaults 6 / 500, the same
   two-stage cap `build_small_pv_josm_leads.py` uses), ranked by `p_roofclf` descending,
   so the sample spans the checked area instead of clustering into whichever cell scores
   highest.

Neither restriction drops a candidate silently: `--no-domain-restriction` shows the
unrestricted national population instead (loudly warned, since that is the rejected
population above), and `--limit 0` disables the overall cap (per-cell still applies
unless `--per-cell 0` too).

Every feature carries `p_roofclf`, `sppi`, and (if `--osm-solar` resolves) whether a
mapped OSM installation already sits within 30 m -- flagged, not dropped, matching
`export_rooftop_detections_geojson.py`'s philosophy of showing status rather than
curating a leads queue. For an already-curated, dedup'd-against-existing-mapping leads
queue instead, see `pixi run small-pv-leads`.

**This is unverified model output, not existing OSM data** -- same warning as the
segmentation export. Never create or edit an OSM feature directly from this layer
without confirming it against imagery first.

    pixi run roofclf-detections-export
    python scripts/export_roofclf_detections_geojson.py --aoi pakistan --limit 2000
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
from earthpv.sub400_capacity import national_cell_domain  # noqa: E402

DO_NOT_UPLOAD = (
    "earthpv model detection, NOT verified OSM data -- confirm against imagery before "
    "any OSM edit"
)

MAPCSS = """\
/* earthpv roofclf-detection JOSM validation layer.
   JOSM: Preferences -> Map Paint Styles -> + -> point at this file.
   Colour intensity is not encoded (JOSM MapCSS can't easily gradient on a numeric tag
   without an eval expression per install); osm_matched is, since it is the more useful
   review-priority signal. */

way[feature_type=roofclf_detection] {
    color: #b06fe0;
    width: 2;
    fill-color: #b06fe0;
    fill-opacity: 0.35;
    z-index: 100;
}

/* Already has a nearby OSM feature -- lower priority to check, it is at least known. */
way[feature_type=roofclf_detection][osm_matched=yes] {
    color: #ffb000;
    fill-color: #ffb000;
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


def _feature(geom, props: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {k: v for k, v in props.items() if v is not None},
        "geometry": mapping(geom),
    }


def load_flagged(roofclf_dir: Path, threshold: float, cells: set[str] | None) -> gpd.GeoDataFrame:
    """Every building >= `threshold` from `roofclf_dir`'s per-cell parquets. `cells`,
    when given, restricts to those cell filenames only -- reads ~92 files instead of
    ~4,463, the same filename-filter optimisation `sub400_capacity.domain_restricted_
    capacity` uses, since a full national read is exactly the scale this script exists
    to avoid by default.
    """
    paths = (
        sorted(roofclf_dir / f"{c}.parquet" for c in cells) if cells is not None
        else sorted(roofclf_dir.glob("*.parquet"))
    )
    parts = []
    for p in paths:
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns:
            continue
        f = d[d.p_roofclf >= threshold]
        if not f.empty:
            parts.append(f)
    if not parts:
        return gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")


def cap_per_cell_then_overall(df: pd.DataFrame, per_cell: int, limit: int) -> pd.DataFrame:
    df = df.sort_values("p_roofclf", ascending=False)
    if per_cell > 0:
        df = df.groupby("cell", group_keys=False).head(per_cell)
    if limit > 0:
        df = df.sort_values("p_roofclf", ascending=False).head(limit)
    return df.reset_index(drop=True)


def flag_osm_matched(df: gpd.GeoDataFrame, osm_solar_path: Path, max_distance_m: float = 30.0):
    from earthpv.export import new_lead_mask

    osm = gpd.read_parquet(osm_solar_path)
    is_new = new_lead_mask(df, osm, min_distance_m=max_distance_m)
    return ~is_new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument(
        "--roofclf-dir", default="data/roofclf_national_20260805",
        help="`roofclf.score_buildings_national` output dir. Update this together with "
             "--model-summary whenever a newer national scoring run supersedes it.",
    )
    ap.add_argument(
        "--model-summary", default="data/roofclf_20260805_newquadrats/summary.json",
        help="LOQO fit summary.json to read deployment_threshold from, unless "
             "--threshold overrides it",
    )
    ap.add_argument("--threshold", type=float, default=None,
                    help="p_roofclf cutoff (default: deployment_threshold from --model-summary)")
    ap.add_argument("--grid-csv", default=None,
                    help="density/grid.csv to derive the calibrated-density domain from "
                         "(default <pred-dir>/<aoi>/density/grid.csv)")
    ap.add_argument("--pred-dir", default="data/predictions")
    ap.add_argument(
        "--no-domain-restriction", action="store_true",
        help="score the WHOLE country, not just the density-calibrated domain -- this is "
             "the population CLAUDE.md documents as rejected/implausible (~5.95M "
             "buildings at the current threshold); reads all national cell files "
             "(minutes, ~7GB) and still gets capped by --per-cell/--limit before writing",
    )
    ap.add_argument("--per-cell", type=int, default=6,
                    help="max leads per 0.1deg cell, ranked by p_roofclf (0 = no per-cell cap)")
    ap.add_argument("--limit", type=int, default=500,
                    help="max leads overall, ranked by p_roofclf, applied after --per-cell (0 = no cap)")
    ap.add_argument("--osm-solar", default=None,
                    help="national OSM solar pull to flag osm_matched against "
                         "(default data/labels/<aoi>_overpass_solar.parquet, skipped if missing)")
    ap.add_argument("--out", default=None,
                    help="default results/<aoi>_roofclf_detections_josm.geojson")
    ap.add_argument("--no-mapcss", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    roofclf_dir = Path(args.roofclf_dir)
    if not roofclf_dir.exists():
        raise SystemExit(f"{roofclf_dir} not found -- pass --roofclf-dir")

    threshold = args.threshold
    if threshold is None:
        summary_path = Path(args.model_summary)
        if not summary_path.exists():
            raise SystemExit(
                f"{summary_path} not found and --threshold not given -- pass one or the other"
            )
        threshold = json.loads(summary_path.read_text())["deployment_threshold"]
    print(f"threshold: p_roofclf >= {threshold}")

    cells = None
    if not args.no_domain_restriction:
        grid_csv = Path(args.grid_csv) if args.grid_csv else (
            Path(args.pred_dir) / args.aoi / "density" / "grid.csv"
        )
        if not grid_csv.exists():
            raise SystemExit(
                f"{grid_csv} not found -- pass --grid-csv, or --no-domain-restriction to "
                "skip the domain restriction entirely (see its help for the tradeoff)"
            )
        grid = pd.read_csv(grid_csv)
        cell_density = grid[["cell"]].copy()
        cell_density["density"] = grid["n_buildings"] / grid["cell_area_km2"].clip(lower=1e-9)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        cell_density.to_parquet(tmp_path)
        try:
            cells = national_cell_domain(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        print(f"domain restriction: {len(cells)} of {len(grid)} cells match the calibrated "
              "building-density range")
    else:
        print(
            "WARNING: --no-domain-restriction -- this is the population CLAUDE.md "
            "documents as rejected/implausible at national scale. Reading every national "
            "cell file; this takes a few minutes."
        )

    flagged = load_flagged(roofclf_dir, threshold, cells)
    print(f"{len(flagged):,} buildings flagged before capping")
    if flagged.empty:
        raise SystemExit("nothing flagged -- check --roofclf-dir/--threshold")

    capped = cap_per_cell_then_overall(flagged, args.per_cell, args.limit)
    print(f"{len(capped):,} buildings after --per-cell={args.per_cell} --limit={args.limit}")

    osm_solar_path = Path(args.osm_solar) if args.osm_solar else (
        Path("data/labels") / f"{args.aoi}_overpass_solar.parquet"
    )
    matched = None
    if osm_solar_path.exists():
        matched = flag_osm_matched(capped, osm_solar_path)
        print(f"{int(matched.sum()):,} of {len(capped):,} already have a nearby OSM feature")
    else:
        print(f"(no OSM solar pull at {osm_solar_path} -- osm_matched left unset)")

    feats = []
    for i, r in enumerate(capped.itertuples()):
        feats.append(_feature(r.geometry, {
            "feature_type": "roofclf_detection",
            "candidate_id": i,
            "cell": _clean(getattr(r, "cell", None)),
            "roof_area_m2": round(float(getattr(r, "roof_area_m2", 0.0) or 0.0), 1),
            "p_roofclf": _clean(getattr(r, "p_roofclf", None)),
            "sppi": _clean(getattr(r, "sppi", None)),
            "osm_matched": (
                ("yes" if bool(matched[i]) else "no") if matched is not None else None
            ),
            "do_not_upload": DO_NOT_UPLOAD,
        }))

    out = Path(args.out) if args.out else Path("results") / f"{args.aoi}_roofclf_detections_josm.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "type": "FeatureCollection",
        "name": out.stem,
        "earthpv": {
            "purpose": "visual JOSM sanity pass over roofclf-flagged buildings",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aoi": args.aoi,
            "roofclf_dir": str(roofclf_dir),
            "threshold": threshold,
            "domain_restricted": not args.no_domain_restriction,
            "per_cell_cap": args.per_cell,
            "overall_limit": args.limit,
            "n_flagged_before_cap": len(flagged),
            "n_features": len(feats),
            "warning": DO_NOT_UPLOAD,
        },
        "features": feats,
    }
    out.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"\nwrote {len(feats):,} features -> {out}")

    if not args.no_mapcss:
        style = out.with_suffix(".mapcss")
        style.write_text(MAPCSS)
        print(f"JOSM style -> {style}  (Preferences -> Map Paint Styles -> + -> this file)")
    print(f"\nReminder: {DO_NOT_UPLOAD}.")


if __name__ == "__main__":
    main()
