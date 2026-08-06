"""Create a calibration quadrat: geodesic square OR a hand-drawn boundary, + OSM solar
pull + a status report.

Boxes 9-11 were each built by hand, which is how the Peshawar pair ended up sharing a
corner before anyone checked. This does the protocol's steps in the protocol's order:

1. Get the boundary. Either a **geodesic square** (`pyproj.Geod.fwd`, never drawn by eye)
   from `--lat/--lon/--side-m`, or an arbitrary polygon **drawn in JOSM** and handed over
   as `--geojson`. Nothing downstream requires a square: every consumer masks and
   rasterises the real geometry (`chips.quadrat_chips`, `roofclf.building_table`, the
   quadrat evaluation scripts). A drawn boundary can follow a suburb, an industrial
   estate or a canal, which is often a better sampling unit than a square that clips
   arbitrary halves of both.
2. **Check overlap against every existing quadrat before writing anything**, and refuse
   to continue on a hit unless `--allow-overlap` is passed. An overlap is not merely
   redundant coverage -- pooling two overlapping quadrats into `roofclf` double-counts
   the shared installations and breaks leave-one-quadrat-out fold independence.
3. Write `<stem>_boundary.geojson` (+ `.parquet`), the file `roofclf.discover_quadrats`
   globs for. Geometry is normalised through `roofclf.load_boundary`, so a closed JOSM
   way that exported as a LineString, a multi-part selection, or a ring that
   self-intersects where it closes all land as one valid (Multi)Polygon here rather than
   failing silently four stages later.
4. Pull live OSM solar for the box into `<stem>_overpass_solar.parquet`.
5. Report the ground-truth profile a new box gets judged on: size distribution against
   the 400 m² detection floor, placement split, and `roofclf.packing_density`.

A fresh box is NEVER Rule-1 complete: that needs a human completeness declaration, which
no script can produce. See `docs/calibration-mapping-protocol.md`.

    python scripts/new_calibration_quadrat.py \
        --name peshawar_west --lat 33.9905887 --lon 71.4261494 --side-m 1500

    python scripts/new_calibration_quadrat.py \
        --name gujranwala_east --geojson ~/drawn/gujranwala_east.geojson
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
from earthpv.config import CHIP_SIZE  # noqa: E402
from earthpv.labels import geodesic_area_m2  # noqa: E402
from earthpv.roofclf import load_boundary  # noqa: E402

LABELS = Path("data/labels")
GEOD = Geod(ellps="WGS84")
FLOOR_M2 = 400.0  # the segmentation model's per-object detection floor
CHIP_M = CHIP_SIZE * 10.0  # 2,240 m -- one training chip's edge
# `chips.quadrat_chip_centers` insets by this much so a chip window can still jitter.
CHIP_MARGIN_M = 120.0
# The protocol's intended quadrat size. Outside this is a warning, never a refusal: the
# first Rule-1-complete box is 0.49 km2 and the largest is 2.25 km2.
PROTOCOL_KM2 = (0.4, 4.0)


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


def is_rectangular(geom, tol_m: float = 1.0) -> bool:
    """True if `geom` is (to within `tol_m`) its own bounding box -- i.e. a script-made
    axis-aligned square, for which quoting a side length means something."""
    if geom.geom_type != "Polygon" or list(geom.interiors):
        return False
    from shapely.geometry import box as shapely_box

    env = shapely_box(*geom.bounds)
    if env.area == 0:
        return False
    # Symmetric difference as a fraction of the envelope, converted to a rough metre band.
    diff_frac = geom.symmetric_difference(env).area / env.area
    side_m = (abs(GEOD.geometry_area_perimeter(env)[0])) ** 0.5
    return diff_frac * side_m < tol_m


def describe_geometry(geom, area_m2: float) -> dict:
    """Shape facts a mapper needs to see before a drawn boundary is accepted.

    `chip_fit` is the load-bearing one. A quadrat only supervises pixels inside its
    boundary, and `chips.quadrat_chip_centers` frames it in 2.24 km chip windows -- one
    centred window when the boundary fits, a covering tile grid when it does not. Both
    work, but a boundary whose bounding box runs to several km buys many more chips for
    the same mapped area and dilutes the quadrat's weight in the corpus, so it is worth
    knowing before mapping rather than after.
    """
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    minx, miny, maxx, maxy = geom.bounds
    cy = (miny + maxy) / 2.0
    span_x = (maxx - minx) * 111_320.0 * np.cos(np.radians(cy))
    span_y = (maxy - miny) * 110_540.0
    # Same threshold `chips.quadrat_chip_centers` tiles on: the chip edge itself, not the
    # jitterable width. A boundary between the two fits one window with no jitter left.
    fits = span_x <= CHIP_M and span_y <= CHIP_M
    tight = fits and min(CHIP_M - span_x, CHIP_M - span_y) / 2.0 <= CHIP_MARGIN_M
    return {
        "type": geom.geom_type,
        "n_parts": len(parts),
        "n_vertices": sum(len(p.exterior.coords) - 1 for p in parts),
        "n_holes": sum(len(p.interiors) for p in parts),
        "bbox_span_m": (round(float(span_x), 1), round(float(span_y), 1)),
        "area_km2": round(area_m2 / 1e6, 4),
        # How much of the bbox the shape actually fills: 1.00 is a rectangle, a long
        # diagonal or L-shape is much lower, and a low value is what makes a boundary
        # need several chip windows for little mapped area.
        "bbox_fill": round(area_m2 / max(span_x * span_y, 1e-9), 3),
        "rectangular": is_rectangular(geom),
        "chip_fit": (
            f"needs tiling (bbox exceeds the {CHIP_M:,.0f} m chip)" if not fits
            else "one window, no jitter room" if tight
            else "one window with jitter"
        ),
        "fits_one_chip": fits,
    }


def confirm_element_count(
    bbox: tuple[float, float, float, float], attempts: int = 2, timeout: int = 90,
) -> int:
    """Largest element count seen over `attempts` independent Overpass queries of the same
    bbox, for cross-checking a pull that may have come back partial.

    The **max**, not one query and not the mean, because the failure being checked for is
    truncation and truncation only ever loses elements: the largest answer any endpoint
    gives is the best available lower bound on the truth. Measured on the Lahore DHA-5 box
    on 2026-08-05, consecutive identical queries returned 5,983 / 5,983 / 5,983 and then
    72 -- so a single confirming query is itself untrustworthy, in either direction.

    Counts only elements that yield a geometry, via the same `_element_geometry` the fetcher
    uses, so this is comparable with the ROW count of what was written. Counting raw elements
    instead would make any element the fetcher legitimately drops (no geometry, an open way
    with <2 nodes) look like truncation, and the retry loop would then spin and abort on a
    perfectly good pull.

    Returns 0 if no attempt succeeded; an unavailable checker must not read as "fine".

    `timeout` is deliberately shorter than the fetch's: `_run_query` walks three mirrors at
    `timeout + 30` each, so a generous value here turns a cheap cross-check into tens of
    minutes of hanging on a slow endpoint (measured on the Sundar box). A confirming query
    that times out reports 0 for that attempt, which is safe -- 0 cannot fail the check.
    """
    from earthpv.overpass import _element_geometry, _query_bbox, _run_query

    q, best = _query_bbox(bbox, timeout), 0
    for i in range(attempts):
        try:
            els = _run_query(q, timeout).get("elements", [])
            usable = sum(1 for el in els
                         if (g := _element_geometry(el)) is not None and not g.is_empty)
            best = max(best, usable)
        except Exception as e:  # noqa: BLE001
            print(f"  (confirming query {i + 1}/{attempts} unavailable: {e})")
    return best


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
    ap.add_argument("--lat", type=float, help="square mode: centre latitude")
    ap.add_argument("--lon", type=float, help="square mode: centre longitude")
    ap.add_argument("--side-m", type=float, default=1000.0,
                    help="square mode: side length in metres (default 1000)")
    ap.add_argument("--geojson",
                    help="drawn mode: a GeoJSON of the boundary, e.g. exported from JOSM. "
                         "Any closed shape; multiple features are unioned. Mutually "
                         "exclusive with --lat/--lon")
    ap.add_argument("--size-tag",
                    help="drawn mode: override the '_calib_<tag>' name suffix (default is "
                         "the geodesic area, e.g. 1p24km2)")
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
    drawn = args.geojson is not None
    if drawn == (args.lat is not None or args.lon is not None):
        raise SystemExit("pass EITHER --geojson (drawn boundary) OR --lat and --lon (square)")
    if not drawn and (args.lat is None or args.lon is None):
        raise SystemExit("square mode needs both --lat and --lon")

    side = args.side_m
    if drawn:
        src = Path(args.geojson).expanduser()
        # Normalised by the same loader every downstream stage uses, so what is validated
        # here is exactly what training and evaluation will read -- not a second opinion.
        poly = load_boundary(src)
        area = abs(GEOD.geometry_area_perimeter(poly)[0])
        # Area, not a side: a drawn shape has no side. '1.24' -> '1p24km2' keeps the tag
        # filename-safe and visibly different from the square tags ('1km', '700m').
        size_tag = args.size_tag or f"{area / 1e6:.2f}".replace(".", "p") + "km2"
    else:
        src = None
        # Matches the existing size-agnostic naming: 1000 -> "1km", 700 -> "700m",
        # 1500 -> "1500m". `roofclf.discover_quadrats` globs `*_calib_*_boundary.geojson`,
        # so the tag is free-form -- but do not re-hardcode `_calib_1km_` anywhere.
        size_tag = args.size_tag or (
            f"{int(side // 1000)}km" if side % 1000 == 0 else f"{side:g}m")
        poly = geodesic_square(args.lat, args.lon, side)
        area = abs(GEOD.geometry_area_perimeter(poly)[0])
    stem = f"{args.name}_calib_{size_tag}"

    w, s, e, n = poly.bounds
    rep = poly.representative_point()
    print(f"quadrat {stem}")
    if drawn:
        print(f"  source  {src}")
        print(f"  centre  {rep.y:.7f}, {rep.x:.7f} (representative point)")
    else:
        print(f"  center  {args.lat}, {args.lon}   side {side:g} m")
    print(f"  bbox    {w:.6f},{s:.6f},{e:.6f},{n:.6f}")
    print(f"  area    {area:,.3f} m2 geodesic"
          + ("" if drawn else f" (nominal {side * side:,.0f})"))

    geom_info = describe_geometry(poly, area)
    print("\ngeometry:")
    for k, v in geom_info.items():
        if k != "fits_one_chip":
            print(f"  {k:<14} {v}")
    if not geom_info["fits_one_chip"]:
        print(
            f"\n  NOTE: the bounding box exceeds one {CHIP_M:,.0f} m training chip, so "
            "`earthpv quadrat-chips` will\n  tile it into several covering windows rather "
            "than one centred one. That is supported and\n  loses no mapped ground, but it "
            "buys more chips for the same supervision -- if the shape is\n  long and thin, "
            "consider splitting it into separate quadrats instead."
        )
    if not PROTOCOL_KM2[0] <= area / 1e6 <= PROTOCOL_KM2[1]:
        print(f"\n  NOTE: {area / 1e6:.2f} km2 is outside the protocol's "
              f"{PROTOCOL_KM2[0]}-{PROTOCOL_KM2[1]} km2 guidance. Not a blocker (the first "
              "Rule-1-complete\n  box is 0.49 km2), but a small box gives a noisy base_rate "
              "and a large one is a long mapping job.")

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

    # A representative point, not the centroid: for a concave drawn boundary the centroid
    # can fall outside the polygon, which would look up the wrong district.
    district, province = admin_lookup(rep.y, rep.x)
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
        # The measured geodesic area in both modes, never a nominal side*side -- for a
        # drawn shape the latter does not exist, and for a lon/lat square it is not
        # exactly the area anyway.
        "size_km2": round(area / 1e6, 4),
        "center": f"[{rep.x} {rep.y}]",
        "shape": "square (geodesic)" if not drawn else "drawn",
    }
    if not drawn:
        props["side_m"] = float(side)
    else:
        # Provenance: which file a mapper handed over, so a boundary that later looks wrong
        # can be traced to its source rather than re-derived by guesswork.
        props["source_geojson"] = str(src)
        props["n_vertices"] = geom_info["n_vertices"]
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
            # An empty response is retryable (below) and a `remark`ed one now fails over
            # inside `_run_query`. Neither catches the third case, measured on this very
            # box: a mirror returning a *partial* element list, HTTP 200, no remark. So
            # confirm the count against an independent query of the same bbox before
            # accepting the pull as ground truth. A quadrat that silently holds a fraction
            # of its installations poisons every negative in it.
            n_written = len(gpd.read_parquet(out))
            n_confirm = confirm_element_count((w, s, e, n))
            print(f"  wrote {n_written} features; confirming query sees {n_confirm}")
            if not n_confirm:
                # Says so loudly and records it, because a pull that could not be
                # cross-checked is indistinguishable on disk from one that was -- and for a
                # brand-new quadrat with no predecessor, the cross-check is the ONLY guard
                # against the silent partial response. Re-verify when the endpoints recover.
                print("  WARNING: no confirming query succeeded, so this pull is UNVERIFIED "
                      "against the\n           partial-response failure mode. For a new "
                      "quadrat (no predecessor to check\n           containment against) "
                      "that is the only guard -- re-run once Overpass recovers.")
                props["pull_unverified"] = True
                gpd.GeoDataFrame([props], geometry=[poly], crs="EPSG:4326").to_parquet(
                    LABELS / f"{stem}_boundary.parquet")
            if n_confirm and n_written < 0.98 * n_confirm:
                raise RuntimeError(
                    f"pull looks truncated: {n_written} features written vs {n_confirm} "
                    "elements in a confirming query of the same bbox"
                )
            break
        except RuntimeError as exc:
            # NOT `as e` -- `w, s, e, n = poly.bounds` above already bound `e` to the east
            # bound, and `except ... as e` implicitly deletes `e` when the block exits
            # (PEP 3110), which left `e` unbound on the next loop iteration's
            # `bbox=(w, s, e, n)` reference (measured 2026-08-06, `islamabad_northeast`:
            # UnboundLocalError on retry attempt 2, once all three mirrors had failed once).
            print(f"  attempt {attempt}/{args.retries} failed: {exc}")
            if attempt == args.retries:
                raise SystemExit(
                    "\nABORT: no usable Overpass response after "
                    f"{args.retries} attempts. The boundary files are written; re-run this "
                    "same command to retry the pull only (the overlap check skips this "
                    "box's own boundary). Do NOT record this as 'no PV in the box' -- an "
                    "endpoint returning zero elements is indistinguishable from an empty "
                    "box in a single attempt."
                ) from exc
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
