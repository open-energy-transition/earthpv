"""Create a calibration quadrat: exact geodesic square + OSM solar pull + a status report.

Boxes 9-11 were each built by hand, which is how the Peshawar pair ended up sharing a
corner before anyone checked. This does the protocol's steps in the protocol's order:

1. Build the square **geodesically** (`pyproj.Geod.fwd`), never drawn by eye.
2. **Check overlap against every existing quadrat before writing anything**, and refuse
   to continue on a hit unless `--allow-overlap` is passed. An overlap is not merely
   redundant coverage -- pooling two overlapping quadrats into `roofclf` double-counts
   the shared installations and breaks leave-one-quadrat-out fold independence.
3. Write `<stem>_boundary.geojson` (+ `.parquet`), the file `roofclf.discover_quadrats`
   globs for.
4. Pull live OSM solar for the box into `<stem>_overpass_solar.parquet`.
5. Report the ground-truth profile a new box gets judged on: size distribution against
   the 400 m² detection floor, placement split, and `roofclf.packing_density`.

A fresh box is NEVER Rule-1 complete: that needs a human completeness declaration, which
no script can produce. See `docs/calibration-mapping-protocol.md`.

    python scripts/new_calibration_quadrat.py \
        --name peshawar_west --lat 33.9905887 --lon 71.4261494 --side-m 1500
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Geod
from shapely.geometry import Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.labels import geodesic_area_m2  # noqa: E402

LABELS = Path("data/labels")
GEOD = Geod(ellps="WGS84")
FLOOR_M2 = 400.0  # the segmentation model's per-object detection floor


def geodesic_square(lat: float, lon: float, side_m: float) -> Polygon:
    """Axis-aligned lon/lat rectangle whose sides measure `side_m` geodesically at the
    center. Not exactly `side_m**2` in area (a lon/lat rectangle is not a geodesic
    square), but exact to within a few mm² at these sizes -- the point is that the side
    lengths are computed, not eyeballed."""
    half = side_m / 2.0
    _, north, _ = GEOD.fwd(lon, lat, 0, half)
    _, south, _ = GEOD.fwd(lon, lat, 180, half)
    east, _, _ = GEOD.fwd(lon, lat, 90, half)
    west, _, _ = GEOD.fwd(lon, lat, 270, half)
    return Polygon([(east, south), (east, north), (west, north), (west, south), (east, south)])


def check_overlap(poly: Polygon, area_m2: float, skip: str = "") -> list[tuple[str, float, float]]:
    """(stem, % of the new box shared, centre separation km) for every existing quadrat,
    overlapping ones first. `skip` excludes one stem -- its own -- so re-running after a
    failed Overpass pull is not blocked by the boundary the previous attempt wrote."""
    rows = []
    for p in sorted(glob.glob(str(LABELS / "*_calib_*_boundary.geojson"))):
        stem = os.path.basename(p).replace("_boundary.geojson", "")
        if stem == skip:
            continue
        u = gpd.read_file(p).to_crs(4326).union_all()
        d_km = GEOD.inv(poly.centroid.x, poly.centroid.y, u.centroid.x, u.centroid.y)[2] / 1000.0
        share = 0.0
        if u.intersects(poly):
            share = abs(GEOD.geometry_area_perimeter(u.intersection(poly))[0]) / area_m2 * 100.0
        rows.append((stem, share, d_km))
    return sorted(rows, key=lambda r: (-r[1], r[2]))


def admin_lookup(lat: float, lon: float) -> tuple[str | None, str | None]:
    """District/province from the density stage's own cached admin polygons, so a new
    box's stated location comes from the same source the capacity tables use rather
    than from reading the coordinates by hand."""
    out = []
    for f in ("data/labels/pakistan_districts.parquet", "data/labels/pakistan_regions.parquet"):
        try:
            adm = gpd.read_parquet(f).to_crs(4326)
            hit = adm[adm.contains(Point(lon, lat))]
            col = next((c for c in ("name", "shapeName") if c in adm.columns), None)
            out.append(str(hit.iloc[0][col]) if len(hit) and col else None)
        except Exception:  # noqa: BLE001 -- absent cache is not fatal, just unlabelled
            out.append(None)
    return out[0], out[1]


def profile(sol: gpd.GeoDataFrame) -> dict:
    a = sol["area_m2"].to_numpy(dtype="float64")
    d = {
        "n": int(len(sol)),
        "total_m2": round(float(a.sum()), 1),
        "median_m2": round(float(np.median(a)), 1),
        "mean_m2": round(float(a.mean()), 1),
        "max_m2": round(float(a.max()), 1),
        "n_below_floor": int((a < FLOOR_M2).sum()),
        "pct_below_floor": round(float((a < FLOOR_M2).mean() * 100), 1),
        "n_below_100": int((a < 100).sum()),
        "pct_below_100": round(float((a < 100).mean() * 100), 1),
    }
    if "placement" in sol.columns:
        d["placement"] = sol["placement"].value_counts().to_dict()
    try:
        from earthpv.roofclf import packing_density

        d["nn_median_m"] = round(float(packing_density(sol)), 1)
    except Exception as e:  # noqa: BLE001
        d["nn_median_m"] = f"unavailable ({e})"
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True,
                    help="place slug, e.g. peshawar_west (the '_calib_<size>' suffix is added)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--side-m", type=float, default=1000.0)
    ap.add_argument("--iso3", default="PAK")
    ap.add_argument("--allow-overlap", action="store_true",
                    help="proceed even though the box overlaps an existing quadrat "
                         "(record the share and the dedup consequence in the box registry)")
    ap.add_argument("--retries", type=int, default=4,
                    help="Overpass attempts before giving up; an empty response counts "
                         "as a failure, not as an empty box")
    ap.add_argument("--retry-wait-s", type=float, default=60.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="run the geometry + overlap checks and stop before writing or fetching")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    side = args.side_m
    # Matches the existing size-agnostic naming: 1000 -> "1km", 700 -> "700m",
    # 1500 -> "1500m". `roofclf.discover_quadrats` globs `*_calib_*_boundary.geojson`,
    # so the tag is free-form -- but do not re-hardcode `_calib_1km_` anywhere.
    size_tag = f"{int(side // 1000)}km" if side % 1000 == 0 else f"{side:g}m"
    stem = f"{args.name}_calib_{size_tag}"

    poly = geodesic_square(args.lat, args.lon, side)
    area = abs(GEOD.geometry_area_perimeter(poly)[0])
    w, s, e, n = poly.bounds
    print(f"quadrat {stem}")
    print(f"  center  {args.lat}, {args.lon}   side {side:g} m")
    print(f"  bbox    {w:.6f},{s:.6f},{e:.6f},{n:.6f}")
    print(f"  area    {area:,.3f} m2 geodesic (nominal {side * side:,.0f})")

    print("\noverlap check against existing quadrats:")
    rows = check_overlap(poly, area, skip=stem)
    overlaps = [r for r in rows if r[1] > 0]
    for st, share, d_km in rows[:5]:
        flag = f"OVERLAP {share:.2f}% of new box" if share else "clear"
        print(f"  {st:<28} {d_km:8.2f} km   {flag}")
    if len(rows) > 5:
        print(f"  ... {len(rows) - 5} more, all clear" if not overlaps else "")
    if overlaps and not args.allow_overlap:
        raise SystemExit(
            f"\nABORT: overlaps {len(overlaps)} existing quadrat(s). Pooling overlapping "
            "quadrats into roofclf double-counts the shared installations and breaks LOQO "
            "fold independence -- move the center, or pass --allow-overlap and record the "
            "share in docs/issues/pakistan-calibration-boxes.md."
        )
    print(f"  -> {len(overlaps)} overlapping quadrat(s)")

    district, province = admin_lookup(args.lat, args.lon)
    print(f"\nadmin lookup: district={district!r} province={province!r}")
    if args.dry_run:
        print("\n--dry-run: nothing written, nothing fetched")
        return

    LABELS.mkdir(parents=True, exist_ok=True)
    props = {
        "quadrat_id": stem,
        # Never guessed here: a stratum is a mapper's judgement about the landscape,
        # and every non-owner-mapped box carries this placeholder at creation.
        "stratum": "unclassified pending mapper review",
        "location": ", ".join(x for x in (district and f"{district} District",
                                          province, "Pakistan") if x),
        "province": province,
        "size_km2": round(side * side / 1e6, 4),
        "side_m": float(side),
        "center": f"[{args.lon} {args.lat}]",
    }
    gdf = gpd.GeoDataFrame([props], geometry=[poly], crs="EPSG:4326")
    gj = LABELS / f"{stem}_boundary.geojson"
    gdf.to_file(gj, driver="GeoJSON")
    # GeoJSON written by fiona/pyogrio drops the FeatureCollection "name"; the existing
    # boxes carry it, so patch it back for consistency with them.
    doc = json.loads(gj.read_text())
    doc["name"] = f"{stem}_boundary"
    gj.write_text(json.dumps(doc, indent=2) + "\n")
    gdf.to_parquet(LABELS / f"{stem}_boundary.parquet")
    print(f"\nwrote {gj}")
    print(f"wrote {LABELS / f'{stem}_boundary.parquet'}")

    from earthpv.overpass import build_overpass_labels

    # A 0-result pull is treated as retryable, not as truth. Measured 2026-08-04 on this
    # very box: when overpass-api.de 504s and `_run_query` fails over, a mirror can return
    # an empty element list instead of an error -- two consecutive pulls of the same bbox
    # gave 0 then 167. `build_overpass_labels` does raise on empty (so it fails loudly
    # rather than writing an empty quadrat), but "this box has no PV" and "the endpoint
    # lied" are indistinguishable from one attempt, so never register a 0 without retries.
    print("\nfetching OSM solar for the box ...")
    out = None
    for attempt in range(1, args.retries + 1):
        try:
            out = build_overpass_labels(LABELS, bbox=(w, s, e, n), name=stem, iso3=args.iso3)
            break
        except RuntimeError as e:
            print(f"  attempt {attempt}/{args.retries} failed: {e}")
            if attempt == args.retries:
                raise SystemExit(
                    "\nABORT: no usable Overpass response after "
                    f"{args.retries} attempts. The boundary files are written; re-run this "
                    "same command to retry the pull only (the overlap check skips this "
                    "box's own boundary). Do NOT record this as 'no PV in the box' -- an "
                    "endpoint returning zero elements is indistinguishable from an empty "
                    "box in a single attempt."
                ) from e
            time.sleep(args.retry_wait_s)
    sol = gpd.read_parquet(out)
    # Overpass returns anything intersecting the bbox; the quadrat is the polygon.
    sol = sol[sol.geometry.representative_point().within(poly)].reset_index(drop=True)
    if "area_m2" not in sol.columns:
        sol["area_m2"] = [geodesic_area_m2(g) for g in sol.geometry]
    sol.to_parquet(out)
    print(f"wrote {out}  ({len(sol)} installations inside the boundary)")

    print("\nground-truth profile:")
    for k, v in profile(sol).items():
        print(f"  {k:<16} {v}")
    print(
        "\nStatus: NOT Rule-1 complete. This is a live Overpass pull at a supplied center, "
        "not a human completeness pass -- absence of a mapped installation inside the box "
        "does NOT mean absence of PV. Usable as a roofclf training quadrat, not as a "
        "source of trustworthy negatives. Register it in "
        "docs/issues/pakistan-calibration-boxes.md and "
        "docs/methods/calibration-quadrats.md."
    )


if __name__ == "__main__":
    main()
