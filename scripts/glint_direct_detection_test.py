"""Does glint work as a *direct* detector, not just a corroborator?

Everywhere else in this pipeline, glint only re-scores candidates the segmentation
model already proposed (`postprocess.add_glint_prior`) or samples a stratified subset
of buildings to estimate an adoption *rate* (`glint_spike_rate_estimator.py`). Neither
of those tests whether scanning glint over *every* target in an area — with no model
in the loop at all — recovers real installations at a usable precision/recall, which is
the actual question for "can glint alone find PV". This script runs that test
exhaustively over a small, real, actively-being-mapped neighbourhood, using the
tile-batched fetch (`glint.tile_scene_series_batch`) built for exactly this kind of
locally-clustered, many-target scan.

Two target-geometry modes, `--geometry {buildings,pv-polygons}`:

- `buildings` (VIDA footprints): tests recall AND lets unmapped buildings surface as
  candidate new leads, but dilutes the signal — a small PV array on a much larger
  roof gets averaged in with a lot of non-PV roof material, especially damaging at
  Sentinel-2 resolution where a small building is only 1-4 pixels to begin with.
- `pv-polygons` (the actual mapped installation footprints, from the same fresh
  Overpass pull): the geometry the original 500-target country-wide validation study
  used, so this is the fair, dilution-free apples-to-apples recall comparison against
  that study's numbers — at the cost of not being able to test unmapped locations
  (there's no ground-truth polygon for something nobody has mapped yet).

Ground truth is a *fresh* Overpass pull (bypasses Overture's snapshot lag — this area
is mid-mapping, so a stale snapshot would undercount). In `buildings` mode, a building
counts as mapped PV if it intersects (or sits within `MATCH_DIST_M` of) a live
`generator:source=solar` / `plant:source=solar` feature; because the area is only
mostly (not completely) mapped, "false positive" there has two readings — a real false
alarm, or a genuine installation the mapping team hasn't reached yet — so the script
reports both the strict metric and the list of glint-flagged-but-unmapped buildings as
candidate new leads. In `pv-polygons` mode every target is mapped PV by construction,
so the report reduces to a clean recall number.

Usage:
  .pixi/envs/default/bin/python scripts/glint_direct_detection_test.py \\
      --geometry pv-polygons --overpass data/labels/lahore_glinttest_overpass_solar.parquet \\
      --bbox 74.396054,31.459866,74.400740,31.463866 \\
      --out-prefix data/glint/lahore_direct_detect_pvpoly

  .pixi/envs/default/bin/python scripts/glint_direct_detection_test.py \\
      --geometry buildings --buildings data/glint/lahore_glinttest_buildings_tight.parquet \\
      --overpass data/labels/lahore_glinttest_overpass_solar.parquet \\
      --out-prefix data/glint/lahore_direct_detect
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402

log = logging.getLogger("glint_direct_detect")

MATCH_DIST_M = 15.0  # a building "is" a mapped PV feature if within this distance
BUCKET_EDGES = [0, 100, 500, 1000, 5000, 50000, np.inf]
BUCKET_LABELS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]


def match_ground_truth(buildings: gpd.GeoDataFrame, mapped: gpd.GeoDataFrame) -> np.ndarray:
    if mapped.empty:
        return np.zeros(len(buildings), dtype=bool)
    sindex = mapped.sindex
    hits = np.zeros(len(buildings), dtype=bool)
    buf = buildings.geometry.buffer(MATCH_DIST_M / 111_000)  # ~degrees, fine at this scale
    for i, g in enumerate(buf):
        hits[i] = len(sindex.query(g, predicate="intersects")) > 0
    return hits


def _filter_bbox(gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float] | None) -> gpd.GeoDataFrame:
    if bbox is None:
        return gdf
    minx, miny, maxx, maxy = bbox
    rep = gdf.geometry.representative_point()
    return gdf[(rep.x >= minx) & (rep.x <= maxx) & (rep.y >= miny) & (rep.y <= maxy)]


def load_targets(
    geometry: str, overpass_path: Path, buildings_path: Path | None,
    bbox: tuple[float, float, float, float] | None,
) -> gpd.GeoDataFrame:
    """Returns a GeoDataFrame with (at least) `geometry`, `area_m2`, `mapped_pv`."""
    if geometry == "pv-polygons":
        gt = gpd.read_parquet(overpass_path)
        gt = gt[gt.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(drop=True)
        gt = _filter_bbox(gt, bbox).reset_index(drop=True)
        gt["mapped_pv"] = True  # by construction: these ARE the mapped installations
        log.info("%d mapped PV polygons in scope (geometry=pv-polygons)", len(gt))
        return gt[["geometry", "area_m2", "mapped_pv"]]

    buildings = gpd.read_parquet(buildings_path).reset_index(drop=True)
    buildings = _filter_bbox(buildings, bbox).reset_index(drop=True)
    mapped = gpd.read_parquet(overpass_path)
    mapped = mapped[mapped.geom_type.isin(["Polygon", "MultiPolygon", "Point"])]
    buildings["mapped_pv"] = match_ground_truth(buildings, mapped)
    log.info("%d buildings, %d already mapped as PV (%.1f%%)",
              len(buildings), buildings.mapped_pv.sum(), 100 * buildings.mapped_pv.mean())
    return buildings[["geometry", "area_m2", "mapped_pv"]]


def run(targets_in: gpd.GeoDataFrame, lookback_days: int, tile_deg: float,
        max_workers: int, out_prefix: Path, self_referenced: bool = False) -> pd.DataFrame:
    targets_in = targets_in.reset_index(drop=True)
    targets = pd.DataFrame({
        "pid": [f"t{i:05d}" for i in range(len(targets_in))],
        "geometry": targets_in.geometry.to_numpy(),
        "lon": targets_in.geometry.centroid.x.to_numpy(),
        "lat": targets_in.geometry.centroid.y.to_numpy(),
    })
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    log.info("tile-batched glint fetch: %d targets, %d-day lookback", len(targets), lookback_days)
    series_by_pid = glint.tile_scene_series_batch(
        targets, start, end, tile_deg=tile_deg, max_workers=max_workers,
    )

    rows = []
    for pid, series in series_by_pid.items():
        if series.empty:
            rows.append(dict(pid=pid, n_scenes=0, n_spikes=0, n_consistent=0))
            continue
        fit = glint.spike_fit(series, self_referenced=self_referenced)
        rows.append(dict(pid=pid, **{k: fit[k] for k in ("n_scenes", "n_spikes", "n_consistent")}))
    fits = pd.DataFrame(rows)

    out = targets_in.copy()
    out["pid"] = targets["pid"]
    out = out.merge(fits, on="pid")
    out["detected"] = out.n_spikes >= 1
    out["validated"] = out.n_consistent >= 2
    out["bucket"] = pd.cut(out.area_m2, bins=BUCKET_EDGES, labels=BUCKET_LABELS)

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    out.drop(columns="geometry").to_csv(out_prefix.with_suffix(".csv"), index=False)
    gpd.GeoDataFrame(out, geometry="geometry", crs=targets_in.crs).to_parquet(
        out_prefix.with_suffix(".parquet")
    )
    return out


def report(out: pd.DataFrame, geometry: str) -> None:
    mapped = out[out.mapped_pv]
    unmapped = out[~out.mapped_pv]
    kind = "PV polygons" if geometry == "pv-polygons" else "buildings"
    print(f"\n=== Glint as a direct detector: {len(out)} {kind} scanned "
          f"({mapped.mapped_pv.sum() if not mapped.empty else 0} already mapped as PV) ===\n")

    print(f"Recall on already-mapped PV {kind}, by size bucket:")
    if not mapped.empty:
        agg = mapped.groupby("bucket", observed=True).agg(
            n=("pid", "size"), detected=("detected", "mean"), validated=("validated", "mean")
        )
        print(agg.round(3).to_string())
        print(f"  overall: detected={mapped.detected.mean():.3f} "
              f"validated={mapped.validated.mean():.3f}  (n={len(mapped)})")
    else:
        print(f"  (no mapped PV {kind} in this area)")

    if unmapped.empty:
        print(f"\n(geometry={geometry}: every target is mapped PV by construction — "
              "no unmapped/false-positive/new-leads comparison to report)")
        return

    print(f"\n'False'-positive rate on {kind} NOT mapped as PV (some of these may be "
          "real, unmapped installations — see the leads list below):")
    agg = unmapped.groupby("bucket", observed=True).agg(
        n=("pid", "size"), detected=("detected", "mean"), validated=("validated", "mean")
    )
    print(agg.round(3).to_string())
    print(f"  overall: detected={unmapped.detected.mean():.3f} "
          f"validated={unmapped.validated.mean():.3f}  (n={len(unmapped)})")

    leads = unmapped[unmapped.validated].sort_values("n_consistent", ascending=False)
    print(f"\n{len(leads)} unmapped {kind} validated glint (n_consistent >= 2) — "
          "candidate new leads for the mapping team:")
    if not leads.empty:
        cols = ["pid", "area_m2", "n_scenes", "n_spikes", "n_consistent"]
        print(leads[cols].head(30).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--geometry", choices=["buildings", "pv-polygons"], default="buildings",
                     help="Scan VIDA building footprints (tests recall + finds new leads, but "
                     "dilutes the signal) or the mapped PV polygons directly (dilution-free "
                     "recall test, matching the country-wide study's own methodology)")
    ap.add_argument("--buildings", type=Path, help="Required when --geometry buildings")
    ap.add_argument("--overpass", type=Path, required=True)
    ap.add_argument("--bbox", type=str, default=None,
                     help="minlon,minlat,maxlon,maxlat — restrict targets to this box "
                     "(applies to both geometry modes; omit to use the whole --overpass/"
                     "--buildings file's extent)")
    ap.add_argument("--lookback-days", type=int, default=365)
    ap.add_argument("--tile-deg", type=float, default=1.0)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--out-prefix", type=Path, default=Path("data/glint/direct_detect"))
    ap.add_argument("--self-referenced", action="store_true",
                     help="Compare each target's annulus to its own history instead of "
                     "requiring it to be dim right now — for dense urban blocks (see "
                     "earthpv.glint.annotate_spikes)")
    args = ap.parse_args()
    if args.geometry == "buildings" and args.buildings is None:
        ap.error("--buildings is required when --geometry buildings")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else None
    targets_in = load_targets(args.geometry, args.overpass, args.buildings, bbox)
    result = run(targets_in, args.lookback_days, args.tile_deg,
                 args.max_workers, args.out_prefix, self_referenced=args.self_referenced)
    report(result, args.geometry)
