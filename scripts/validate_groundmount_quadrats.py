"""Validate the PROMOTED PRODUCTION segmentation checkpoint (v3_combined_india, the model
behind `data/predictions/<aoi>/prob/` and `candidates.parquet`) against the two ground-mount
solar-farm calibration boxes -- the targeted evaluation `docs/issues/pakistan-calibration-
boxes.md`'s "Two ground-mount solar-farm calibration areas" section left open.

Every other quadrat evaluation in this project (`roofclf`, `validate_fraction_quadrats.py`)
is a rooftop *building* classifier question -- does this footprint carry PV. A solar farm has
no building to classify; the only question that makes sense is whether the model's own PIXEL
output and the pipeline's own CANDIDATE polygons recover the mapped footprint. This measures
both, independently:

- **Pixel-level** (same methodology as `validate_fraction_quadrats.py`, generalized to any
  raster, not just the fraction head): `auc` -- can the raw probability raster separate mapped-
  PV pixels from background inside the box; `scale` -- integral(prob)/255 over the box, divided
  by the true mapped area. This is upstream of thresholding/polygonization and cannot be
  confounded by the OSM-replacement or duplicate-match issues below.
- **Candidate-polygon level** (what `density.py`'s capacity numbers actually consume):
  every `candidates.parquet` row within `--match-distance-m` of the box, summed area vs. true
  mapped area, PLUS an explicit duplicate-OSM-match check (`osm_matched_id` collisions --
  the mechanism documented 2026-08-06 at Quaid-e-Azam Solar Park) so this reproduces that
  finding against whatever `candidates.parquet` is current rather than trusting the old number.

The two boxes are named `*_gmcalib_*`, not `*_calib_*`, specifically so `roofclf.
discover_quadrats()` never picks them up for rooftop training -- this script does NOT use
that glob; it takes the boxes explicitly.

    python scripts/validate_groundmount_quadrats.py \
        --prob-dir data/predictions/pakistan/prob \
        --candidates data/predictions/pakistan/candidates.parquet
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.mask import mask as rio_mask
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.labels import geodesic_area_m2  # noqa: E402

LABELS = Path("data/labels")


def discover_gmcalib(labels_dir: Path = LABELS) -> list[str]:
    """The ground-mount boxes' own stems -- deliberately NOT `roofclf.discover_quadrats`,
    which globs `*_calib_*` and would never match `*_gmcalib_*` by design (see module
    docstring)."""
    return sorted(
        Path(p).name.removesuffix("_boundary.geojson")
        for p in glob.glob(str(labels_dir / "*_gmcalib_*_boundary.geojson"))
    )


def raster_index(prob_dir: Path) -> gpd.GeoDataFrame:
    rows = []
    for p in sorted(prob_dir.glob("*.tif")):
        with rasterio.open(p) as s:
            g = gpd.GeoSeries([box(*s.bounds)], crs=s.crs).to_crs(4326).iloc[0]
        rows.append({"path": str(p), "geometry": g})
    if not rows:
        raise SystemExit(f"no rasters under {prob_dir}")
    return gpd.GeoDataFrame(rows, crs=4326)


def integral_m2(path: str, geoms: gpd.GeoSeries) -> float:
    """sum(prob/255 * pixel_area) inside `geoms` -- the same expected-area integral
    `density.py` takes, restricted to one shape."""
    with rasterio.open(path) as s:
        gs = geoms.to_crs(s.crs)
        try:
            arr, _ = rio_mask(s, list(gs.geometry), crop=True, filled=True, nodata=0)
        except ValueError:
            return 0.0
        px = abs(s.transform.a) * abs(s.transform.e)
    return float(arr[0].astype("float64").sum() / 255.0 * px)


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos, neg = int(labels.sum()), int(labels.size - labels.sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    s = scores[order]
    ranks = np.empty(s.size, dtype="float64")
    i = 0
    while i < s.size:
        j = i
        while j + 1 < s.size and s[j + 1] == s[i]:
            j += 1
        ranks[i : j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    r = np.empty_like(ranks)
    r[order] = ranks
    m = labels.astype(bool)
    return float((r[m].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def pixels(path: str, bnd: gpd.GeoDataFrame, sol: gpd.GeoDataFrame):
    with rasterio.open(path) as s:
        gs = bnd.to_crs(s.crs)
        try:
            arr, tr = rio_mask(s, list(gs.geometry), crop=True, filled=True, nodata=0)
        except ValueError:
            return None
        shape = arr.shape[1:]
        truth = rasterize(
            [(g, 1) for g in sol.to_crs(s.crs).geometry if not g.is_empty],
            out_shape=shape, transform=tr, fill=0, dtype="uint8", all_touched=True,
        )
        inside = rasterize(
            [(g, 1) for g in gs.geometry], out_shape=shape, transform=tr,
            fill=0, dtype="uint8",
        ).astype(bool)
    return arr[0][inside].astype("float64"), truth[inside].astype("uint8")


def candidate_area_check(
    cands: gpd.GeoDataFrame, bnd_geom, match_distance_m: float,
) -> dict:
    """Every candidate within `match_distance_m` of the box (not just intersecting it --
    a box-adjacent farm perimeter and its nearest candidate can be drawn slightly off from
    each other), summed area, and an explicit duplicate-`osm_matched_id` check -- the
    mechanism documented 2026-08-06 at Quaid-e-Azam Solar Park, reproduced here against
    whatever `candidates.parquet` is current."""
    m = cands.to_crs(3857)
    g3857 = gpd.GeoSeries([bnd_geom], crs=4326).to_crs(3857).iloc[0]
    near = m[m.distance(g3857) <= match_distance_m]
    n_dup_osm = 0
    if "osm_matched_id" in near.columns:
        matched = near[near.osm_matched_id.notna() & (near.osm_matched_id != "")]
        counts = matched.osm_matched_id.value_counts()
        n_dup_osm = int((counts > 1).sum())
        dup_ids = counts[counts > 1].index.tolist()
    else:
        dup_ids = []
    # Geometric overlap among the near candidates, independent of osm_matched_id: the
    # documented QASP mechanism is two candidates each matching a DIFFERENT OSM id (an
    # outer envelope and a member way nested inside it), which an id-equality check alone
    # cannot see -- only their geometries overlapping can.
    geoms = list(near.geometry)
    n_overlapping_pairs = sum(
        1 for i in range(len(geoms)) for j in range(i + 1, len(geoms))
        if geoms[i].intersects(geoms[j]) and not geoms[i].touches(geoms[j])
    )
    # `density.py` drops every candidate over `postprocess.MAX_CANDIDATE_M2` (100,000 m2)
    # from capacity entirely (flagged, not removed, from the leads product -- but absent
    # from every capacity sum). A candidate can match the true footprint almost exactly at
    # the pixel level and still contribute ~nothing to the published number if it lands on
    # the wrong side of that cutoff -- this is the metric that actually reaches the atlas,
    # distinct from `candidate_area_m2` (every near candidate, oversize or not).
    non_oversize = near[~near.oversize] if "oversize" in near.columns else near
    return {
        "n_candidates_near": int(len(near)),
        "candidate_area_m2": round(float(near.area_m2.sum()), 1) if len(near) else 0.0,
        "n_oversize_near": int(near.oversize.sum()) if "oversize" in near.columns and len(near) else 0,
        "candidate_area_capacity_m2": round(float(non_oversize.area_m2.sum()), 1) if len(non_oversize) else 0.0,
        "n_geometrically_overlapping_pairs": n_overlapping_pairs,
        "n_duplicate_osm_matches": n_dup_osm,
        "duplicate_osm_ids": dup_ids,
        "placements": near.placement.value_counts().to_dict() if "placement" in near.columns and len(near) else {},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prob-dir", default="data/predictions/pakistan/prob",
                     help="Production segmentation probability rasters (v3_combined_india)")
    ap.add_argument("--candidates", default="data/predictions/pakistan/candidates.parquet")
    ap.add_argument("--labels-dir", default=str(LABELS))
    ap.add_argument("--match-distance-m", type=float, default=200.0,
                     help="How far a candidate may sit from the box and still count as "
                          "'this site' -- wider than the usual 30 m new-lead radius because "
                          "a multi-km2 farm's own boundary and OSM's mapped perimeter can be "
                          "drawn with real slack between them")
    ap.add_argument("--out", default="results/groundmount_quadrat_validation.csv")
    args = ap.parse_args()

    labels_dir = Path(args.labels_dir)
    stems = discover_gmcalib(labels_dir)
    if not stems:
        raise SystemExit(f"no *_gmcalib_*_boundary.geojson under {labels_dir}")
    print(f"ground-mount boxes: {stems}")

    prob_idx = raster_index(Path(args.prob_dir))
    print(f"indexed {len(prob_idx)} probability rasters under {args.prob_dir}")

    cands = gpd.read_parquet(args.candidates)
    if cands.crs is None:
        cands = cands.set_crs(4326)
    print(f"loaded {len(cands):,} candidates from {args.candidates}")

    rows = []
    for stem in stems:
        bnd = gpd.read_file(labels_dir / f"{stem}_boundary.geojson").to_crs(4326)
        sol_path = labels_dir / f"{stem}_overpass_solar.parquet"
        sol = gpd.read_parquet(sol_path).to_crs(4326)
        sol = sol[sol.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]
        sol = gpd.clip(sol, bnd)
        true_m2 = float(sol.geometry.map(geodesic_area_m2).sum())
        poly = bnd.union_all()

        hits = prob_idx[prob_idx.intersects(poly)]
        pred_m2 = sum(integral_m2(p, bnd.geometry) for p in hits.path)
        scale = pred_m2 / true_m2 if true_m2 else float("nan")

        parts = [x for x in (pixels(p, bnd, sol) for p in hits.path) if x is not None]
        auc = mean_pv = mean_bg = float("nan")
        n_px = n_px_pv = 0
        if parts:
            sc = np.concatenate([a for a, _ in parts])
            lb = np.concatenate([b for _, b in parts])
            n_px, n_px_pv = int(lb.size), int(lb.sum())
            auc = _auc(sc, lb)
            if lb.any():
                mean_pv = float(sc[lb.astype(bool)].mean()) / 255.0
            if (~lb.astype(bool)).any():
                mean_bg = float(sc[~lb.astype(bool)].mean()) / 255.0

        cand_check = candidate_area_check(cands, poly, args.match_distance_m)
        cand_scale = (
            cand_check["candidate_area_m2"] / true_m2 if true_m2 else float("nan")
        )
        cand_scale_capacity = (
            cand_check["candidate_area_capacity_m2"] / true_m2 if true_m2 else float("nan")
        )

        row = {
            "quadrat": stem, "n_solar": len(sol), "true_m2": round(true_m2, 1),
            "n_cells": len(hits), "n_px": n_px, "n_px_pv": n_px_pv,
            "prob_pred_m2": round(pred_m2, 1), "prob_scale": round(scale, 4),
            "pixel_auc": round(auc, 4) if auc == auc else None,
            "mean_prob_on_pv": round(mean_pv, 5) if mean_pv == mean_pv else None,
            "mean_prob_on_bg": round(mean_bg, 5) if mean_bg == mean_bg else None,
            "candidate_scale": round(cand_scale, 4) if cand_scale == cand_scale else None,
            "candidate_scale_capacity": (
                round(cand_scale_capacity, 4) if cand_scale_capacity == cand_scale_capacity else None
            ),
            **cand_check,
        }
        rows.append(row)
        print(
            f"\n{stem}: true={true_m2:,.0f} m2 ({len(sol)} mapped features)\n"
            f"  pixel-level:     prob_scale={scale:.3f}  auc={auc:.4f}  "
            f"mean_pv={mean_pv:.4f}  mean_bg={mean_bg:.4f}\n"
            f"  candidate-level (ALL near, incl. oversize): "
            f"n_near={cand_check['n_candidates_near']}  "
            f"area={cand_check['candidate_area_m2']:,.0f} m2  scale={cand_scale:.3f}\n"
            f"  candidate-level (CAPACITY-relevant, oversize excluded, matches density.py): "
            f"area={cand_check['candidate_area_capacity_m2']:,.0f} m2  "
            f"scale={cand_scale_capacity:.4f}\n"
            f"  n_oversize_near={cand_check['n_oversize_near']}  "
            f"n_geometrically_overlapping_pairs={cand_check['n_geometrically_overlapping_pairs']}  "
            f"duplicate_osm_matches={cand_check['n_duplicate_osm_matches']} {cand_check['duplicate_osm_ids']}"
        )

    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
