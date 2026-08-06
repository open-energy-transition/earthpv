"""Sample N roofclf-flagged (< 400 m2) buildings as one JOSM spot-check layer.

`export_roofclf_detections_geojson.py` answers "show me the density-calibrated
domain's leads, capped for review." This answers a different question: "give me a
sample of N successful detections, either from one specific place or from anywhere
roofclf has been scored" -- no domain restriction by default, since the point here is
to spot-check the classifier's raw behaviour, not to restate the capacity instrument's
own calibrated population.

"Successful detection" means `p_roofclf >= threshold` -- the classifier's own positive
call at its deployment operating point -- not a ground-truth-confirmed true positive.
roofclf has no ground truth outside the 18 hand-mapped calibration quadrats, so
"successful" cannot mean "confirmed correct" anywhere else on the map; read every
feature here as "the model says yes," to be checked against imagery, not as "verified
PV."

Three mutually exclusive ways to pick the sample, in priority order:

1. `--cell <cell_id>` -- every flagged building in one named 0.1-degree grid cell
   (looked up from `--grid-csv`), e.g. `--cell 0135_0078`. Reads exactly one file.
2. `--bbox minx,miny,maxx,maxy` -- every flagged building whose representative point
   falls inside an arbitrary box, spanning as many cell files as it touches.
3. **Neither given: random sample nationally.** Reading and filtering all ~4,463
   national cell files just to draw N rows is real I/O for no benefit, so this instead
   randomly picks `--sample-cells` cell files (default 60, seeded by `--seed`), pools
   their flagged buildings, and samples N from that pool. This is a random sample of
   cells then a random sample of rows within them, not a mathematically uniform
   national sample -- good enough for a spot-check, not a basis for a national
   estimate (`export_roofclf_detections_geojson.py`'s domain-restricted population is
   the closest this project has to that).

Every mode is capped at `--n` (default 2000): bbox/cell modes take the top-N by
`p_roofclf` if the match count exceeds it, random mode draws an actual random N-subset
of its pooled candidates.

**This is unverified model output, not existing OSM data.** Never create or edit an
OSM feature directly from this layer without confirming it against imagery first.

    pixi run roofclf-sample -- --cell 0135_0078
    python scripts/sample_roofclf_detections_geojson.py --bbox 74.35,31.55,74.40,31.58
    python scripts/sample_roofclf_detections_geojson.py --n 500 --seed 1
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box as shapely_box
from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DO_NOT_UPLOAD = (
    "earthpv model detection, NOT verified OSM data -- confirm against imagery before "
    "any OSM edit"
)

MAPCSS = """\
/* earthpv roofclf sample JOSM validation layer.
   JOSM: Preferences -> Map Paint Styles -> + -> point at this file. */
way[feature_type=roofclf_detection] {
    color: #b06fe0;
    width: 2;
    fill-color: #b06fe0;
    fill-opacity: 0.35;
    z-index: 100;
}
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


def _read_flagged(path: Path, threshold: float) -> gpd.GeoDataFrame:
    d = gpd.read_parquet(path)
    if d.empty or "p_roofclf" not in d.columns:
        return d.iloc[0:0]
    return d[d.p_roofclf >= threshold]


def sample_by_cell(roofclf_dir: Path, cell: str, threshold: float) -> gpd.GeoDataFrame:
    p = roofclf_dir / f"{cell}.parquet"
    if not p.exists():
        raise SystemExit(f"{p} not found -- is {cell!r} a cell roofclf actually scored?")
    return _read_flagged(p, threshold)


def sample_by_bbox(
    roofclf_dir: Path, bbox: tuple[float, float, float, float], threshold: float,
    grid_csv: Path,
) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = bbox
    grid = pd.read_csv(grid_csv)
    # 0.1deg cells: a cell (lon0, lat0) covers [lon0, lon0+0.1] x [lat0, lat0+0.1].
    touching = grid[
        (grid.lon0 < maxx) & (grid.lon0 + 0.1 > minx)
        & (grid.lat0 < maxy) & (grid.lat0 + 0.1 > miny)
    ]
    if touching.empty:
        raise SystemExit(f"no grid cells touch bbox {bbox} -- check --grid-csv covers this AOI")
    box = shapely_box(minx, miny, maxx, maxy)
    parts = []
    for cell in touching["cell"]:
        p = roofclf_dir / f"{cell}.parquet"
        if not p.exists():
            continue
        f = _read_flagged(p, threshold)
        if f.empty:
            continue
        f = f[f.geometry.representative_point().within(box)]
        if not f.empty:
            parts.append(f)
    if not parts:
        return gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    print(f"  read {len(touching)} cell file(s) touching the bbox")
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")


def sample_random(
    roofclf_dir: Path, threshold: float, n_sample_cells: int, seed: int,
) -> gpd.GeoDataFrame:
    all_files = sorted(roofclf_dir.glob("*.parquet"))
    if not all_files:
        raise SystemExit(f"no per-cell parquets found under {roofclf_dir}")
    rng = random.Random(seed)
    picked = rng.sample(all_files, k=min(n_sample_cells, len(all_files)))
    print(f"  randomly picked {len(picked)} of {len(all_files)} cell files (seed={seed})")
    parts = []
    for p in picked:
        f = _read_flagged(p, threshold)
        if not f.empty:
            parts.append(f)
    if not parts:
        return gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")


def flag_osm_matched(df: gpd.GeoDataFrame, osm_solar_path: Path, max_distance_m: float = 30.0):
    from earthpv.export import new_lead_mask

    osm = gpd.read_parquet(osm_solar_path)
    return ~new_lead_mask(df, osm, min_distance_m=max_distance_m)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--roofclf-dir", default="data/roofclf_national_20260805")
    ap.add_argument("--model-summary", default="data/roofclf_20260805_newquadrats/summary.json")
    ap.add_argument("--threshold", type=float, default=None,
                     help="p_roofclf cutoff (default: deployment_threshold from --model-summary)")
    ap.add_argument("--cell", default=None, help="one named 0.1deg grid cell, e.g. 0135_0078")
    ap.add_argument("--bbox", default=None, help="minx,miny,maxx,maxy in lon/lat degrees")
    ap.add_argument("--grid-csv", default=None,
                     help="default <pred-dir>/<aoi>/density/grid.csv (needed for --bbox)")
    ap.add_argument("--pred-dir", default="data/predictions")
    ap.add_argument("--n", type=int, default=2000, help="target sample size")
    ap.add_argument("--sample-cells", type=int, default=60,
                     help="random mode only: how many cell files to pool before sampling --n rows")
    ap.add_argument("--seed", type=int, default=0, help="random mode only")
    ap.add_argument("--osm-solar", default=None,
                     help="default data/labels/<aoi>_overpass_solar.parquet, skipped if missing")
    ap.add_argument("--out", default=None,
                     help="default results/<aoi>_roofclf_sample_josm.geojson")
    ap.add_argument("--no-mapcss", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cell and args.bbox:
        raise SystemExit("pass EITHER --cell OR --bbox, not both")

    roofclf_dir = Path(args.roofclf_dir)
    if not roofclf_dir.exists():
        raise SystemExit(f"{roofclf_dir} not found -- pass --roofclf-dir")

    threshold = args.threshold
    if threshold is None:
        summary_path = Path(args.model_summary)
        if not summary_path.exists():
            raise SystemExit(f"{summary_path} not found and --threshold not given")
        threshold = json.loads(summary_path.read_text())["deployment_threshold"]
    print(f"threshold: p_roofclf >= {threshold}")

    if args.cell:
        print(f"mode: single cell {args.cell!r}")
        pool = sample_by_cell(roofclf_dir, args.cell, threshold)
        mode = f"cell:{args.cell}"
    elif args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))
        if len(bbox) != 4:
            raise SystemExit("--bbox needs exactly 4 comma-separated values: minx,miny,maxx,maxy")
        grid_csv = Path(args.grid_csv) if args.grid_csv else (
            Path(args.pred_dir) / args.aoi / "density" / "grid.csv"
        )
        if not grid_csv.exists():
            raise SystemExit(f"{grid_csv} not found -- pass --grid-csv")
        print(f"mode: bbox {bbox}")
        pool = sample_by_bbox(roofclf_dir, bbox, threshold, grid_csv)
        mode = f"bbox:{args.bbox}"
    else:
        print("mode: random sample nationally (no --cell/--bbox given)")
        pool = sample_random(roofclf_dir, threshold, args.sample_cells, args.seed)
        mode = f"random(sample_cells={args.sample_cells},seed={args.seed})"

    print(f"{len(pool):,} flagged buildings available")
    if pool.empty:
        raise SystemExit("nothing flagged in this selection")

    if len(pool) <= args.n:
        sample = pool.reset_index(drop=True)
        if len(pool) < args.n:
            print(f"WARNING: only {len(pool):,} available, fewer than --n={args.n}")
    elif args.cell or args.bbox:
        # Deterministic top-N by confidence for a targeted region, not a random subset --
        # a fixed bbox/cell run should be reproducible without needing --seed.
        sample = pool.sort_values("p_roofclf", ascending=False).head(args.n).reset_index(drop=True)
    else:
        sample = pool.sample(n=args.n, random_state=args.seed).reset_index(drop=True)
    print(f"{len(sample):,} after sampling to --n={args.n}")

    osm_solar_path = Path(args.osm_solar) if args.osm_solar else (
        Path("data/labels") / f"{args.aoi}_overpass_solar.parquet"
    )
    matched = None
    if osm_solar_path.exists():
        matched = flag_osm_matched(sample, osm_solar_path)
        print(f"{int(matched.sum()):,} of {len(sample):,} already have a nearby OSM feature")
    else:
        print(f"(no OSM solar pull at {osm_solar_path} -- osm_matched left unset)")

    feats = []
    for i, r in enumerate(sample.itertuples()):
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

    out = Path(args.out) if args.out else Path("results") / f"{args.aoi}_roofclf_sample_josm.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "type": "FeatureCollection",
        "name": out.stem,
        "earthpv": {
            "purpose": "sample of N roofclf-flagged (< 400 m2) buildings for a JOSM spot-check",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aoi": args.aoi,
            "roofclf_dir": str(roofclf_dir),
            "threshold": threshold,
            "mode": mode,
            "n_available": len(pool),
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
