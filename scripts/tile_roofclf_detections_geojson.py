"""Export EVERY roofclf-flagged (< 400 m2) building in one or more regions as JOSM
layers -- complete, never sampled. If a region's full set is too big for one usable
file, it is split (quadtree: halve both dimensions, recurse) into as many tiles as it
takes to get every tile under `--max-per-file`; each tile is still complete for its own
ground, so the full set of files together covers the requested region with zero
omissions.

Replaces `sample_roofclf_detections_geojson.py`'s top-N-by-confidence and random-sample
modes -- neither actually answered "does the model miss anything," only "how bad are its
most/least confident calls." A capped or randomly-sampled file cannot show that, and a
JOSM reviewer working through tiles one at a time does not need the whole country pooled
into one random draw; they need one region, completely, at a time.

Exactly one of `--cell` / `--bbox` / `--all-quadrats` selects which region(s):

- `--cell` -- one or more named 0.1deg grid cells, comma-separated.
- `--bbox` -- one arbitrary box, minx,miny,maxx,maxy.
- `--all-quadrats` -- every registered calibration quadrat (`roofclf.discover_quadrats`,
  e.g. `lahore_calib_6p61km2`) -- the project's small, hand-mapped ground-truth
  validation regions. Filters to each quadrat's actual boundary polygon, not just its
  bounding box, since several are hand-drawn and not rectangular. One output file set
  per quadrat, so you get a JOSM layer for every validation region in one run.

All output for a run lands in one folder, `results/<aoi>_roofclf_validation/` by default
(override with `--out-dir`) -- every region's tiles side by side rather than scattered
loose into `results/`. The sibling `.mapcss` JOSM style is off by default (`--mapcss` to
write it): one is enough to load in JOSM, and a run with many regions/tiles would
otherwise write the identical style file dozens of times over.

    pixi run roofclf-tiles -- --cell 0135_0078
    pixi run roofclf-tiles -- --cell 0135_0078,0061_0012
    python scripts/tile_roofclf_detections_geojson.py --all-quadrats --mapcss
    python scripts/tile_roofclf_detections_geojson.py --bbox 74.35,31.55,74.40,31.58 --max-per-file 1500
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
from shapely.geometry import box as shapely_box
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DO_NOT_UPLOAD = (
    "earthpv model detection, NOT verified OSM data -- confirm against imagery before "
    "any OSM edit"
)

# Recursive quadtree split stops here even if a tile is still over --max-per-file --
# guards against infinite recursion when detections cluster tightly enough that
# halving the box forever cannot separate them (a real, if rare, possibility at dense
# urban block scale). A leaf this deep is at most 1/4^12 of the starting box.
MAX_SPLIT_DEPTH = 12

MAPCSS = """\
/* earthpv roofclf tile JOSM validation layer.
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


def load_by_cell(roofclf_dir: Path, cell: str, threshold: float) -> gpd.GeoDataFrame:
    p = roofclf_dir / f"{cell}.parquet"
    if not p.exists():
        raise SystemExit(f"{p} not found -- is {cell!r} a cell roofclf actually scored?")
    return _read_flagged(p, threshold)


def calibration_quadrats_union(labels_dir: Path) -> BaseGeometry | None:
    """One (Multi)Polygon covering every registered calibration quadrat's real boundary
    -- used to exclude ground already reviewed via `--all-quadrats` from a `--cell`/
    `--bbox` run, so the two never show a mapper the same buildings twice. `None` if no
    quadrats are registered (nothing to exclude, not an error)."""
    from earthpv.roofclf import discover_quadrats, load_boundary
    from shapely.ops import unary_union

    stems = discover_quadrats(labels_dir)
    if not stems:
        return None
    return unary_union([load_boundary(labels_dir / f"{stem}_boundary.geojson") for stem in stems])


def exclude_calibration_overlap(
    gdf: gpd.GeoDataFrame, quadrats_union: BaseGeometry | None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Drop buildings whose representative point falls inside any calibration quadrat.
    Returns `(filtered_gdf, n_excluded)`."""
    if quadrats_union is None or gdf.empty:
        return gdf, 0
    inside = gdf.geometry.representative_point().within(quadrats_union)
    n_excluded = int(inside.sum())
    return gdf[~inside.to_numpy()], n_excluded


def load_by_polygon(
    roofclf_dir: Path, polygon: BaseGeometry, threshold: float, grid_csv: Path,
) -> gpd.GeoDataFrame:
    """Every flagged building whose representative point falls inside `polygon` --
    the polygon itself, not just its bounding box, so a non-rectangular region (a
    hand-drawn quadrat) does not pull in buildings from its bbox's corners."""
    minx, miny, maxx, maxy = polygon.bounds
    grid = pd.read_csv(grid_csv)
    touching = grid[
        (grid.lon0 < maxx) & (grid.lon0 + 0.1 > minx)
        & (grid.lat0 < maxy) & (grid.lat0 + 0.1 > miny)
    ]
    if touching.empty:
        raise SystemExit(f"no grid cells touch bounds {polygon.bounds} -- check --grid-csv covers this AOI")
    parts = []
    for cell in touching["cell"]:
        p = roofclf_dir / f"{cell}.parquet"
        if not p.exists():
            continue
        f = _read_flagged(p, threshold)
        if f.empty:
            continue
        f = f[f.geometry.representative_point().within(polygon)]
        if not f.empty:
            parts.append(f)
    print(f"  read {len(touching)} cell file(s) touching this region")
    if not parts:
        return gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")


def quadtree_split(
    gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float], max_per_file: int, depth: int = 0,
) -> list[tuple[tuple, gpd.GeoDataFrame]]:
    """Every building in `gdf` is inside `bbox`. Returns `[(tile_bbox, tile_gdf), ...]`
    covering `bbox` with no overlap and no omission: leaves are either under
    `max_per_file`, or at `MAX_SPLIT_DEPTH` regardless (logged, not silently truncated).
    """
    if len(gdf) <= max_per_file or depth >= MAX_SPLIT_DEPTH:
        if len(gdf) > max_per_file:
            print(f"  WARNING: tile at depth {depth} still has {len(gdf):,} buildings "
                  f"(> --max-per-file={max_per_file}) -- hit MAX_SPLIT_DEPTH, writing as-is")
        return [(bbox, gdf)]
    minx, miny, maxx, maxy = bbox
    midx, midy = (minx + maxx) / 2, (miny + maxy) / 2
    quadrants = [
        (minx, miny, midx, midy), (midx, miny, maxx, midy),
        (minx, midy, midx, maxy), (midx, midy, maxx, maxy),
    ]
    reps = gdf.geometry.representative_point()
    x, y = reps.x.to_numpy(), reps.y.to_numpy()
    out = []
    for qbbox in quadrants:
        qminx, qminy, qmaxx, qmaxy = qbbox
        in_q = (x >= qminx) & (x < qmaxx if qmaxx < maxx else x <= qmaxx) \
            & (y >= qminy) & (y < qmaxy if qmaxy < maxy else y <= qmaxy)
        sub = gdf[in_q]
        if sub.empty:
            continue
        out.extend(quadtree_split(sub, qbbox, max_per_file, depth + 1))
    return out


def flag_osm_matched(df: gpd.GeoDataFrame, osm_solar_path: Path, max_distance_m: float = 30.0):
    from earthpv.export import new_lead_mask

    osm = gpd.read_parquet(osm_solar_path)
    return ~new_lead_mask(df, osm, min_distance_m=max_distance_m)


def write_tile(
    tile_gdf: gpd.GeoDataFrame, tile_bbox: tuple, out_path: Path, meta_extra: dict,
    osm_solar_path: Path | None, make_mapcss: bool,
) -> None:
    matched = None
    if osm_solar_path is not None and osm_solar_path.exists() and not tile_gdf.empty:
        matched = flag_osm_matched(tile_gdf, osm_solar_path)

    feats = []
    for i, r in enumerate(tile_gdf.itertuples()):
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

    doc = {
        "type": "FeatureCollection",
        "name": out_path.stem,
        "earthpv": {
            "purpose": "every roofclf-flagged (< 400 m2) building in this tile -- complete, not sampled",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tile_bbox": [round(v, 6) for v in tile_bbox],
            "n_features": len(feats),
            "warning": DO_NOT_UPLOAD,
            **meta_extra,
        },
        "features": feats,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1) + "\n")

    if make_mapcss:
        out_path.with_suffix(".mapcss").write_text(MAPCSS)


def process_region(
    label: str, gdf: gpd.GeoDataFrame, bbox: tuple, out_prefix: Path, threshold: float,
    roofclf_dir: Path, max_per_file: int, osm_solar_path: Path | None, make_mapcss: bool,
) -> dict:
    """One region (cell / bbox / quadrat): tile it, write every tile, return a summary
    row. Never raises on an empty region -- that is a real, reportable outcome across a
    multi-region run (`--all-quadrats`), not a fatal error the way it is for a single
    explicit `--cell`/`--bbox`."""
    print(f"\n=== {label} ===")
    if gdf.empty:
        print("  0 flagged buildings -- skipping")
        return {"region": label, "n_buildings": 0, "n_tiles": 0, "files": []}

    print(f"  {len(gdf):,} flagged buildings (complete population, no cap)")
    tiles = quadtree_split(gdf.reset_index(drop=True), bbox, max_per_file)
    total = sum(len(t) for _, t in tiles)
    assert total == len(gdf), f"tiling lost buildings: {total} written vs {len(gdf)} available"
    print(f"  split into {len(tiles)} tile(s) (max-per-file={max_per_file})")

    width = max(2, len(str(len(tiles))))
    files = []
    for i, (tile_bbox, tile_gdf) in enumerate(tiles, start=1):
        out_path = out_prefix.parent / f"{out_prefix.name}_part{i:0{width}d}_of_{len(tiles):0{width}d}.geojson"
        write_tile(
            tile_gdf, tile_bbox, out_path,
            {"region": label, "threshold": threshold, "roofclf_dir": str(roofclf_dir),
             "part": i, "n_parts": len(tiles)},
            osm_solar_path, make_mapcss,
        )
        files.append(str(out_path))
        print(f"    wrote {len(tile_gdf):,} features -> {out_path}")

    return {"region": label, "n_buildings": total, "n_tiles": len(tiles), "files": files}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--roofclf-dir", default="data/roofclf_national_20260805")
    ap.add_argument("--model-summary", default="data/roofclf_20260805_newquadrats/summary.json")
    ap.add_argument("--threshold", type=float, default=None,
                     help="p_roofclf cutoff (default: deployment_threshold from --model-summary)")
    ap.add_argument("--cell", default=None,
                     help="one or more named 0.1deg grid cells, comma-separated, e.g. "
                          "0135_0078 or 0135_0078,0061_0012")
    ap.add_argument("--bbox", default=None, help="minx,miny,maxx,maxy in lon/lat degrees")
    ap.add_argument(
        "--all-quadrats", action="store_true",
        help="every registered calibration quadrat (roofclf.discover_quadrats) -- the "
             "project's small hand-mapped validation regions -- one output file set "
             "per quadrat, filtered to its real boundary polygon",
    )
    ap.add_argument("--labels-dir", default="data/labels",
                     help="for --all-quadrats, and for the calibration-overlap exclusion "
                          "below")
    ap.add_argument(
        "--include-calibration-overlap", action="store_true",
        help="for --cell/--bbox only: by default, any building inside a registered "
             "calibration quadrat is excluded, so a --cell/--bbox run never re-covers "
             "ground already reviewed via --all-quadrats. Pass this to disable that and "
             "include everything (--all-quadrats is unaffected either way -- excluding "
             "quadrat overlap FROM the quadrats themselves would be self-defeating)",
    )
    ap.add_argument("--grid-csv", default=None,
                     help="default <pred-dir>/<aoi>/density/grid.csv (needed for --bbox/--all-quadrats)")
    ap.add_argument("--pred-dir", default="data/predictions")
    ap.add_argument("--max-per-file", type=int, default=2000,
                     help="split into tiles until every tile has at most this many features")
    ap.add_argument("--osm-solar", default=None,
                     help="default data/labels/<aoi>_overpass_solar.parquet, skipped if missing")
    ap.add_argument("--out-dir", default=None,
                     help="directory for output files (default results/<aoi>_roofclf_validation/)")
    ap.add_argument("--mapcss", action="store_true",
                     help="also write a sibling .mapcss JOSM style file per tile (off by "
                          "default -- one is enough to load in JOSM, and duplicating the "
                          "same style file once per tile clutters the output folder)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    modes_given = sum(bool(x) for x in (args.cell, args.bbox, args.all_quadrats))
    if modes_given != 1:
        raise SystemExit("pass EXACTLY ONE of --cell, --bbox, or --all-quadrats")

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

    grid_csv = Path(args.grid_csv) if args.grid_csv else (
        Path(args.pred_dir) / args.aoi / "density" / "grid.csv"
    )
    osm_solar_path = Path(args.osm_solar) if args.osm_solar else (
        Path("data/labels") / f"{args.aoi}_overpass_solar.parquet"
    )
    if not osm_solar_path.exists():
        print(f"(no OSM solar pull at {osm_solar_path} -- osm_matched left unset)")
    out_dir = Path(args.out_dir) if args.out_dir else Path("results") / f"{args.aoi}_roofclf_validation"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Loaded once, reused for every --cell/--bbox region below -- cheap (18 small
    # polygons unioned once), and must be the SAME union all regions are checked
    # against so two regions in one run cannot each keep the half of an excluded
    # building the other one dropped.
    quadrats_union = None
    if (args.cell or args.bbox) and not args.include_calibration_overlap:
        quadrats_union = calibration_quadrats_union(Path(args.labels_dir))
        if quadrats_union is None:
            print(f"(no calibration quadrats found under {args.labels_dir} -- nothing to exclude)")

    # Build the region list up front so --all-quadrats can report "N regions to process"
    # before spending any time reading composites.
    regions = []  # (label, gdf, bbox)
    if args.cell:
        cells = [c.strip() for c in args.cell.split(",") if c.strip()]
        for cell in cells:
            gdf = load_by_cell(roofclf_dir, cell, threshold)
            gdf, n_excluded = exclude_calibration_overlap(gdf, quadrats_union)
            if n_excluded:
                print(f"{cell}: excluded {n_excluded:,} buildings inside a calibration quadrat")
            bbox = tuple(gdf.total_bounds) if not gdf.empty else (0.0, 0.0, 0.0, 0.0)
            regions.append((cell, gdf, bbox))
    elif args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))
        if len(bbox) != 4:
            raise SystemExit("--bbox needs exactly 4 comma-separated values: minx,miny,maxx,maxy")
        if not grid_csv.exists():
            raise SystemExit(f"{grid_csv} not found -- pass --grid-csv")
        gdf = load_by_polygon(roofclf_dir, shapely_box(*bbox), threshold, grid_csv)
        gdf, n_excluded = exclude_calibration_overlap(gdf, quadrats_union)
        if n_excluded:
            print(f"excluded {n_excluded:,} buildings inside a calibration quadrat")
        label = args.bbox.replace(",", "_").replace(".", "p")
        regions.append((label, gdf, bbox))
    else:
        from earthpv.roofclf import discover_quadrats, load_boundary

        if not grid_csv.exists():
            raise SystemExit(f"{grid_csv} not found -- pass --grid-csv")
        labels_dir = Path(args.labels_dir)
        stems = discover_quadrats(labels_dir)
        if not stems:
            raise SystemExit(f"no quadrats found under {labels_dir}")
        print(f"{len(stems)} registered calibration quadrats found under {labels_dir}")
        for stem in stems:
            boundary = load_boundary(labels_dir / f"{stem}_boundary.geojson")
            gdf = load_by_polygon(roofclf_dir, boundary, threshold, grid_csv)
            regions.append((stem, gdf, boundary.bounds))

    summaries = []
    for label, gdf, bbox in regions:
        out_prefix = out_dir / f"{args.aoi}_roofclf_tiles_{label}"
        summaries.append(process_region(
            label, gdf, bbox, out_prefix, threshold, roofclf_dir, args.max_per_file,
            osm_solar_path, args.mapcss,
        ))

    n_regions = len(summaries)
    n_with_data = sum(1 for s in summaries if s["n_buildings"] > 0)
    total_buildings = sum(s["n_buildings"] for s in summaries)
    total_files = sum(s["n_tiles"] for s in summaries)
    print(f"\n{'=' * 60}")
    print(f"{n_regions} region(s) processed, {n_with_data} with detections, "
          f"{total_files} file(s) written, {total_buildings:,} buildings total, "
          f"nothing sampled or truncated.")
    if n_regions > 1:
        print(pd.DataFrame(
            [{"region": s["region"], "buildings": s["n_buildings"], "tiles": s["n_tiles"]}
             for s in summaries]
        ).to_string(index=False))
    print(f"\nReminder: {DO_NOT_UPLOAD}.")


if __name__ == "__main__":
    main()
