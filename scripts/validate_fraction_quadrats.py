"""Score one or more national fraction-head prob dirs against the mapped quadrats.

The fraction head's own val split answers "did pixel IoU improve on real installations".
It cannot answer "did the change cost recall in the dense small-rooftop regime the
sub-400 m2 program exists for", because that regime is only exhaustively mapped in the
calibration quadrats. This does, off already-written national rasters -- no re-scoring,
no GPU -- and reports two independent things per quadrat:

- `scale` = predicted / true PV area (a *calibration* question; a uniform miss is
  fixable after the fact with `density --exp-scale`).
- `auc` = pixel-level separation of mapped-PV pixels from the rest of the quadrat
  (an *information* question; a loss here is not fixable by rescaling).

Reading them together is the point. Scale alone is ambiguous: a quadrat where a
checkpoint over-predicts can lose true signal and still look like it improved, because
the two errors cancel in one ratio.

Usage:
    python scripts/validate_fraction_quadrats.py \
        v1=data/predictions_frac_pk_v2/pakistan/prob \
        hn=data/predictions_fraction_hardneg_national/pakistan/prob \
        --out results/fraction_quadrat_validation.csv
"""
from __future__ import annotations

import argparse
import glob
import os
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
VIDA = Path("data/predictions/pakistan/buildings/pakistan_vida.parquet")


def newest_solar(stem: str) -> Path | None:
    """Newest dated Overpass pull for a quadrat, else the bare file (same rule as
    `roofclf._newest_overpass_path` -- a re-pull must win over the original)."""
    cands = sorted(LABELS.glob(f"{stem}_overpass_solar*.parquet"))
    dated = [p for p in cands if p.name != f"{stem}_overpass_solar.parquet"]
    return (dated or cands)[-1] if cands else None


def raster_index(prob_dir: Path) -> gpd.GeoDataFrame:
    """Cell footprints in 4326, so a quadrat can find its covering raster(s). Each
    cell raster carries its own UTM CRS, so this cannot be a plain bounds compare."""
    rows = []
    for p in sorted(prob_dir.glob("*.tif")):
        with rasterio.open(p) as s:
            g = gpd.GeoSeries([box(*s.bounds)], crs=s.crs).to_crs(4326).iloc[0]
        rows.append({"path": str(p), "geometry": g})
    if not rows:
        raise SystemExit(f"no rasters under {prob_dir}")
    return gpd.GeoDataFrame(rows, crs=4326)


def integral_m2(path: str, geoms: gpd.GeoSeries) -> float:
    """sum(prob/255 * pixel_area) inside `geoms` -- the same integral `density.py`'s
    expected-area instrument takes, restricted to a shape."""
    with rasterio.open(path) as s:
        gs = geoms.to_crs(s.crs)
        try:
            arr, _ = rio_mask(s, list(gs.geometry), crop=True, filled=True, nodata=0)
        except ValueError:  # disjoint from this cell
            return 0.0
        px = abs(s.transform.a) * abs(s.transform.e)
    return float(arr[0].astype("float64").sum() / 255.0 * px)


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Mann-Whitney AUC with tie correction -- the raster is uint8, so ties dominate
    and a naive rank would inflate this."""
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
    """(raster values, mapped-PV mask) for every pixel inside the quadrat."""
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", metavar="LABEL=PROB_DIR",
                    help="one or more labelled prob dirs, e.g. hn=data/predictions_x/pakistan/prob")
    ap.add_argument("--out", default="results/fraction_quadrat_validation.csv")
    ap.add_argument("--buildings", default=str(VIDA),
                    help="VIDA parquet for the building-restricted integral (what "
                         "*_exp_roof uses); pass '' to skip it")
    args = ap.parse_args()

    runs = {}
    for spec in args.runs:
        if "=" not in spec:
            raise SystemExit(f"expected LABEL=PROB_DIR, got {spec!r}")
        label, d = spec.split("=", 1)
        runs[label] = Path(d)

    stems = sorted(
        os.path.basename(p).replace("_boundary.geojson", "")
        for p in glob.glob(str(LABELS / "*_calib_*_boundary.geojson"))
    )
    idx = {k: raster_index(d) for k, d in runs.items()}
    print("indexed: " + ", ".join(f"{k}={len(v)} cells" for k, v in idx.items()), flush=True)

    # The national VIDA parquet has no bbox covering column, so a bbox= pushdown
    # raises rather than filtering -- read the columns we need once and clip per quadrat.
    blds_all = None
    if args.buildings:
        try:
            blds_all = gpd.read_parquet(args.buildings, columns=["geometry"]).to_crs(4326)
            print(f"buildings: {len(blds_all):,} footprints", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"buildings unavailable, skipping roof-restricted integral: {e}")

    out = []
    for stem in stems:
        spath = newest_solar(stem)
        if spath is None:
            print(f"skip {stem}: no mapped-solar pull")
            continue
        bnd = gpd.read_file(LABELS / f"{stem}_boundary.geojson").to_crs(4326)
        sol = gpd.read_parquet(spath).to_crs(4326)
        sol = sol[sol.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]
        sol = gpd.clip(sol, bnd)
        if sol.empty:
            print(f"skip {stem}: no mapped solar inside boundary")
            continue
        true_m2 = float(sol.geometry.map(geodesic_area_m2).sum())
        poly = bnd.union_all()
        blds = (gpd.clip(blds_all[blds_all.intersects(poly)], bnd)
                if blds_all is not None else None)

        row = {"quadrat": stem, "n_solar": len(sol), "true_m2": round(true_m2, 1),
               "n_bldg": (len(blds) if blds is not None else None)}
        for key in runs:
            hits = idx[key][idx[key].intersects(poly)]
            pred = sum(integral_m2(p, bnd.geometry) for p in hits.path)
            row[f"{key}_pred_m2"] = round(pred, 1)
            row[f"{key}_scale"] = round(pred / true_m2, 3) if true_m2 else float("nan")
            if blds is not None and len(blds):
                roof = sum(integral_m2(p, blds.geometry) for p in hits.path)
                row[f"{key}_pred_roof_m2"] = round(roof, 1)
                row[f"{key}_scale_roof"] = round(roof / true_m2, 3) if true_m2 else float("nan")

            parts = [x for x in (pixels(p, bnd, sol) for p in hits.path) if x is not None]
            if parts:
                sc = np.concatenate([a for a, _ in parts])
                lb = np.concatenate([b for _, b in parts])
                row["n_px"], row["n_px_pv"] = int(lb.size), int(lb.sum())
                row[f"{key}_auc"] = round(_auc(sc, lb), 4)
                row[f"{key}_mean_pv"] = round(float(sc[lb.astype(bool)].mean()) / 255.0, 5)
                row[f"{key}_mean_bg"] = round(float(sc[~lb.astype(bool)].mean()) / 255.0, 5)
        out.append(row)
        desc = "  ".join(f"{k}: scale={row.get(f'{k}_scale')} auc={row.get(f'{k}_auc')}"
                         for k in runs)
        print(f"  {stem}: true={true_m2:,.0f} m2  {desc}", flush=True)

    df = pd.DataFrame(out)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    cols = ["quadrat", "n_solar", "true_m2", "n_px_pv"]
    for k in runs:
        cols += [c for c in (f"{k}_scale", f"{k}_scale_roof", f"{k}_auc",
                             f"{k}_mean_pv", f"{k}_mean_bg") if c in df]
    print("\n" + df[cols].to_string(index=False))
    print("\nmedians across %d quadrats:" % len(df))
    for k in runs:
        parts = [f"scale={df[f'{k}_scale'].median():.3f}", f"auc={df[f'{k}_auc'].median():.4f}"]
        if f"{k}_scale_roof" in df:
            parts.insert(1, f"scale_roof={df[f'{k}_scale_roof'].median():.3f}")
        print(f"  {k:<4} " + "  ".join(parts))
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
