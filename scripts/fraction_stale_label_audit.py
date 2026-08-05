"""Split a fraction head's apparent false positives into "stale label" and "real error".

The calibration quadrats were mapped against high-res basemap imagery that is generally
*older* than the Sentinel-2 composite the model reads. Installations built in between are
present in the image and absent from the labels, so a pixel the model correctly calls PV
scores as a false positive. Precision measured against these labels is therefore a lower
bound, and "the model over-predicts here" and "the mapper's imagery predates the panel"
are indistinguishable from one epoch alone.

Two epochs separate them. Running the *same* checkpoint on the pre-boom (2021/22)
composite as well as the current one:

- predicted PV now, **not** pre-boom, and unlabelled -> consistent with an installation
  built after the mapping imagery. A **candidate new installation**, i.e. a stale label,
  and also a mapping lead.
- predicted PV in **both** epochs and unlabelled -> the surface already looked PV-like
  before Pakistan's solar boom, so a stale label explains it much less well. Counted as a
  **persistent** apparent false positive.

Same checkpoint both times on purpose: comparing against a raster produced by a different
checkpoint would confound the epoch difference with a model difference.

This does not *prove* either class. A new array can sit on a roof that was already bright,
and a genuine false positive can appear only in the current epoch (a new bright roof, a
seasonal surface). It brackets precision instead of asserting one number:
`precision_raw` (every unlabelled prediction is an error) and `precision_upper` (candidate
new installations are not errors).

    python scripts/fraction_stale_label_audit.py \
        --current data/predictions_fraction_quadrats/pakistan/prob \
        --preboom data/predictions_fraction_quadrats_preboom/pakistan/prob
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.mask import mask as rio_mask
from shapely.geometry import box

LABELS = Path("data/labels")
FLOOR_M2 = 400.0


def raster_index(prob_dir: str) -> gpd.GeoDataFrame:
    rows = []
    for p in sorted(glob.glob(prob_dir + "/*.tif")):
        with rasterio.open(p) as s:
            rows.append({"path": p, "geometry": gpd.GeoSeries(
                [box(*s.bounds)], crs=s.crs).to_crs(4326).iloc[0]})
    if not rows:
        raise SystemExit(f"no rasters under {prob_dir}")
    return gpd.GeoDataFrame(rows, crs=4326)


def _read(path: str, bnd: gpd.GeoDataFrame, sol: gpd.GeoDataFrame):
    """(fraction, labelled-PV mask, pixel_m2) inside the quadrat, on the raster's grid."""
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
        ).astype(bool)
        inside = rasterize(
            [(g, 1) for g in gs.geometry], out_shape=shape, transform=tr, fill=0,
            dtype="uint8",
        ).astype(bool)
        px = abs(tr.a * tr.e)
    # infer writes uint8 0-255; density.py reads /255.
    return arr[0].astype("float32") / 255.0, truth, inside, px


def newest_solar(stem: str) -> Path | None:
    c = sorted(LABELS.glob(f"{stem}_overpass_solar*.parquet"))
    dated = [p for p in c if p.name != f"{stem}_overpass_solar.parquet"]
    return (dated or c)[-1] if c else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True, help="prob dir, current epoch")
    ap.add_argument("--preboom", required=True, help="prob dir, pre-boom epoch, SAME checkpoint")
    ap.add_argument("--threshold", type=float, default=0.2,
                    help="fraction at/above which a pixel counts as predicted PV")
    ap.add_argument("--preboom-max", type=float, default=0.1,
                    help="pre-boom fraction below which a pixel counts as 'was not PV then'")
    ap.add_argument("--out", default="results/fraction_stale_label_audit.csv")
    args = ap.parse_args()

    cur_idx, pre_idx = raster_index(args.current), raster_index(args.preboom)
    stems = sorted(os.path.basename(p).replace("_boundary.geojson", "")
                   for p in glob.glob(str(LABELS / "*_calib_*_boundary.geojson")))
    rows = []
    for stem in stems:
        sp = newest_solar(stem)
        if sp is None:
            continue
        bnd = gpd.read_file(LABELS / f"{stem}_boundary.geojson").to_crs(4326)
        sol = gpd.read_parquet(sp).to_crs(4326)
        sol = sol[sol.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]
        sol = gpd.clip(sol, bnd)
        if sol.empty:
            continue
        poly = bnd.union_all()
        cur_hits = cur_idx[cur_idx.intersects(poly)]
        pre_hits = pre_idx[pre_idx.intersects(poly)]
        if cur_hits.empty or pre_hits.empty:
            print(f"skip {stem}: missing raster coverage")
            continue

        tp = fp_new = fp_persist = fn = 0
        a_new = a_persist = 0.0
        for cp in cur_hits.path:
            c = _read(cp, bnd, sol)
            if c is None:
                continue
            cf, truth, inside, px = c
            # Pre-boom on the same footprint. Grids are pinned to the base composite by
            # `compose --index`, so the same cell aligns pixel-for-pixel across epochs;
            # a shape mismatch means a different cell and is skipped rather than resized.
            pf = None
            for pp in pre_hits.path:
                if os.path.basename(pp) == os.path.basename(cp):
                    r = _read(pp, bnd, sol)
                    if r is not None and r[0].shape == cf.shape:
                        pf = r[0]
                    break
            if pf is None:
                continue
            pred = (cf >= args.threshold) & inside
            lab = truth & inside
            tp += int((pred & lab).sum())
            fn += int((lab & ~pred).sum())
            apparent = pred & ~lab
            was_not = pf < args.preboom_max
            fp_new += int((apparent & was_not).sum())
            fp_persist += int((apparent & ~was_not).sum())
            a_new += float(cf[apparent & was_not].sum()) * px
            a_persist += float(cf[apparent & ~was_not].sum()) * px

        fp = fp_new + fp_persist
        rows.append({
            "quadrat": stem, "tp_px": tp, "fn_px": fn,
            "fp_px": fp, "fp_new_candidate_px": fp_new, "fp_persistent_px": fp_persist,
            "new_candidate_share_of_fp": round(fp_new / fp, 3) if fp else np.nan,
            "precision_raw": round(tp / (tp + fp), 3) if tp + fp else np.nan,
            "precision_upper": round(tp / (tp + fp_persist), 3) if tp + fp_persist else np.nan,
            "recall": round(tp / (tp + fn), 3) if tp + fn else np.nan,
            "new_candidate_area_m2": round(a_new, 1),
            "persistent_fp_area_m2": round(a_persist, 1),
        })
        r = rows[-1]
        print(f"  {stem:28s} P {r['precision_raw']}-{r['precision_upper']}  R {r['recall']}  "
              f"new-cand {r['new_candidate_share_of_fp']} of FP", flush=True)

    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print("\n" + df.to_string(index=False))
    tp, fp, fpn, fn = df.tp_px.sum(), df.fp_px.sum(), df.fp_new_candidate_px.sum(), df.fn_px.sum()
    print(f"\npooled over {len(df)} quadrats at threshold {args.threshold} "
          f"(pre-boom < {args.preboom_max} = 'was not PV then'):")
    print(f"  recall              {tp/(tp+fn):.3f}")
    print(f"  precision_raw       {tp/(tp+fp):.3f}   (every unlabelled prediction an error)")
    print(f"  precision_upper     {tp/(tp+fp-fpn):.3f}   (candidate new installations not errors)")
    print(f"  {fpn:,} of {fp:,} apparent-FP pixels ({fpn/fp*100:.1f}%) are new-installation "
          f"candidates, {df.new_candidate_area_m2.sum():,.0f} m2 of predicted coverage")
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
