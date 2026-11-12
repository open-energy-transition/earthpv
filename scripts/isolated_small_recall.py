"""Recall of ISOLATED mapped arrays by size, from production probability rasters, down to 100 m2.

A small array next to a large one is "found" whenever the large one's outline reaches it, so
recall over every mapped array credits small arrays with their neighbours' detections (in South
Africa thousands of panel rows are mapped as small polygons). This counts an array as isolated
when no other mapped array of any size lies within 50 m, and as found when the largest
probability inside its outline (all-touched) reaches the threshold.

    areas  Pakistan's registered calibration areas (Rule-1, every visible panel mapped; the
           corroborated Jhang f2 is left out, as in small_array_eval.py), read from one prob
           raster directory per model. Also counts unmapped objects: connected blobs of at least
           two pixels at the threshold, mostly inside the area, touching no mapped array
           (dilated by one pixel), per km2.
    cells  a `sheet_scan.py curve` run's saved per-installation maxima (whole cells), with the
           geometry re-joined from the AOI's newest Overpass pull.

    pixi run python scripts/isolated_small_recall.py areas --name isolated_v16_v28 \\
        --rasters v16=/home/tobi/earthpv_data/seg_v16_pakistan/pakistan/prob \\
        --rasters v28=/home/tobi/earthpv_data/predictions_v28/pakistan/prob
    pixi run python scripts/isolated_small_recall.py cells --name isolated_sa_v14_v28_v41 \\
        --aoi south_africa --curve v14_v28_v41

`--threshold label=t` reads one model at its own threshold (e.g. small_array_eval.py's matched
one); the rest use `--default-threshold` (0.3). Writes results/small_array_eval/<name>/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
from rasterio import features
from rasterio.windows import Window, from_bounds
from scipy import ndimage

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
LABELS_DIR = REPO / "data/labels"
EXCLUDE_AREAS = {"jhang_f2_farm_calib_3km"}  # corroborated on poor imagery, not Rule-1
ISOLATION_M = 50.0
BINS = [0, 100, 200, 400, 700, 1000, 5000]


def _isolated(gdf: gpd.GeoDataFrame, among: gpd.GeoDataFrame | None = None) -> np.ndarray:
    """True where no OTHER mapped array (any size) lies within ISOLATION_M."""
    if not len(gdf):
        return np.zeros(0, bool)
    utm = gdf.estimate_utm_crs()
    g = gdf.to_crs(utm)
    pool = g if among is None else among.to_crs(utm)
    j = gpd.sjoin(gpd.GeoDataFrame(geometry=g.buffer(ISOLATION_M), crs=utm),
                  gpd.GeoDataFrame(geometry=pool.geometry, crs=utm), predicate="intersects")
    j = j[j.index != j.index_right]
    return ~gdf.index.isin(j.index)


def _table(arr: pd.DataFrame, thr: dict[str, float]) -> pd.DataFrame:
    arr = arr.copy()
    arr["bin"] = pd.cut(arr.area_m2, BINS, right=False,
                        labels=[f"{a}-{b}" for a, b in zip(BINS[:-1], BINS[1:])])
    out = []
    for iso in (True, False):
        sub = arr[arr.isolated] if iso else arr
        for (pl, b), d in sub.dropna(subset=["bin"]).groupby(["placement", "bin"], observed=True):
            r = dict(arrays="isolated" if iso else "all", placement=pl, bin=str(b), n=len(d))
            for m, t in thr.items():
                r[m] = round(float((d[f"p_{m}"] >= t).mean()), 3)
            out.append(r)
    return pd.DataFrame(out)


def cmd_areas(a) -> int:
    from earthpv import roofclf
    from earthpv.labels import geodesic_area_m2

    dirs = {k: Path(v) for k, v in (r.split("=", 1) for r in a.rasters)}
    thr = {m: a.default_threshold for m in dirs} | {
        k: float(v) for k, v in (t.split("=", 1) for t in a.threshold)}
    first = next(iter(dirs.values()))
    cells = []
    for p in sorted(first.glob("*.tif")):
        if all((d / p.name).exists() for d in dirs.values()):
            with rasterio.open(p) as r:
                cells.append((p.name, *rasterio.warp.transform_bounds(r.crs, 4326, *r.bounds)))
    cells = pd.DataFrame(cells, columns=["name", "w", "s", "e", "n"])
    rows, objs = [], []
    for stem in roofclf.discover_quadrats(LABELS_DIR):
        if stem in EXCLUDE_AREAS:
            continue
        area = roofclf.load_boundary(LABELS_DIR / f"{stem}_boundary.geojson")
        lab = gpd.read_parquet(roofclf._newest_solar(stem, LABELS_DIR)).to_crs(4326)
        lab = lab[lab.geom_type.isin(["Polygon", "MultiPolygon"])]
        lab = lab[lab.representative_point().within(area)].reset_index(drop=True)
        lab["placement"] = lab["placement"].where(lab["placement"].isin(["rooftop", "ground"]),
                                                  "ground")
        lab["area_m2"] = [geodesic_area_m2(g) for g in lab.geometry]
        lab["isolated"] = _isolated(lab)
        w, s, e, n = area.bounds
        hit = cells[(cells.w < e) & (cells.e > w) & (cells.s < n) & (cells.n > s)]
        if hit.empty:
            print(f"{stem}: no raster cell, skipped")
            continue
        maxp = {m: np.full(len(lab), -1.0) for m in dirs}
        for cname in hit.name:
            for m, d in dirs.items():
                with rasterio.open(d / cname) as r:
                    bb = rasterio.warp.transform_bounds(4326, r.crs, w - 0.001, s - 0.001,
                                                        e + 0.001, n + 0.001)
                    win = from_bounds(*bb, r.transform).round_offsets().round_lengths()
                    try:
                        win = win.intersection(Window(0, 0, r.width, r.height))
                    except rasterio.errors.WindowError:
                        continue
                    prob = r.read(1, window=win).astype(np.float32)
                    if r.dtypes[0] == "uint8":
                        prob /= 255.0
                    tr, shape, crs = r.window_transform(win), prob.shape, r.crs
                gl = lab.to_crs(crs)
                for i, g in enumerate(gl.geometry):
                    o = features.rasterize([(g, 1)], out_shape=shape, transform=tr,
                                           all_touched=True).astype(bool)
                    if o.any():
                        maxp[m][i] = max(maxp[m][i], float(prob[o].max()))
                inside = features.rasterize(
                    [(gpd.GeoSeries([area], crs=4326).to_crs(crs).iloc[0], 1)],
                    out_shape=shape, transform=tr).astype(bool)
                known = (features.rasterize([(g, 1) for g in gl.geometry], out_shape=shape,
                                            transform=tr, all_touched=True).astype(bool)
                         if len(gl) else np.zeros(shape, bool))
                known = ndimage.binary_dilation(known, iterations=1)
                lab_o, nobj = ndimage.label(prob >= thr[m])
                for k in range(1, nobj + 1):
                    mk = lab_o == k
                    if mk.sum() < 2 or (mk & inside).sum() * 2 < mk.sum():
                        continue
                    objs.append(dict(area=stem, model=m, cell=cname, px=int(mk.sum()),
                                     touches_mapped=bool((mk & known).any())))
        ga = gpd.GeoSeries([area], crs=4326)
        km2 = float(ga.to_crs(ga.estimate_utm_crs()).area.sum() / 1e6)
        objs.append(dict(area=stem, model="_area", km2=km2))
        for i in range(len(lab)):
            rows.append(dict(area=stem, placement=lab.placement[i], area_m2=lab.area_m2[i],
                             isolated=bool(lab.isolated[i]), **{f"p_{m}": maxp[m][i] for m in dirs}))
        print(f"{stem}: {len(lab)} arrays, {km2:.1f} km2", flush=True)
    arr, ob = pd.DataFrame(rows), pd.DataFrame(objs)
    out = REPO / "results/small_array_eval" / a.name
    out.mkdir(parents=True, exist_ok=True)
    arr.to_csv(out / "arrays.csv", index=False)
    ob.to_csv(out / "objects.csv", index=False)
    tab = _table(arr, thr)
    km2 = ob.loc[ob.model == "_area", "km2"].sum()
    fa = {m: int(((ob.model == m) & ~ob.touches_mapped.fillna(True).astype(bool)).sum())
          for m in dirs}
    lines = [f"{arr.area.nunique()} areas with arrays of {int((ob.model == '_area').sum())}, "
             f"{km2:.1f} km2; thresholds {thr}",
             "unmapped objects per km2: " + ", ".join(f"{m} {fa[m] / km2:.3f} ({fa[m]})"
                                                       for m in dirs), "",
             tab.to_string(index=False)]
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def cmd_cells(a) -> int:
    from earthpv.chips import _newest_overpass_path, _overpass_labels
    from earthpv.labels import geodesic_area_m2

    inst = pd.read_parquet(REPO / f"data/sheet_scan/{a.aoi}/curve_{a.curve}_installations.parquet")
    osm = _overpass_labels(_newest_overpass_path(a.aoi, LABELS_DIR)).reset_index(drop=True)
    g = osm.loc[inst.index]
    ok = np.isclose([geodesic_area_m2(x) for x in g.geometry], inst.area_m2.values, rtol=1e-6)
    if ok.mean() < 0.999:
        print(f"labels do not line up with the curve run ({ok.mean():.4f}); a newer pull?")
        return 1
    inst["isolated"] = _isolated(gpd.GeoDataFrame(geometry=g.geometry, crs=osm.crs),
                                 among=gpd.GeoDataFrame(geometry=osm.geometry, crs=osm.crs))
    inst["placement"] = inst.placement.replace({"small": "rooftop"})
    models = [c[2:] for c in inst.columns if c.startswith("p_")]
    thr = {m: a.default_threshold for m in models} | {
        k: float(v) for k, v in (t.split("=", 1) for t in a.threshold)}
    out = REPO / "results/small_array_eval" / a.name
    out.mkdir(parents=True, exist_ok=True)
    tab = _table(inst, thr)
    lines = [f"{a.aoi} whole cells (sheet_scan curve {a.curve}), {len(inst)} mapped arrays; "
             f"thresholds {thr}", "", tab.to_string(index=False)]
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("areas", "cells"):
        p = sub.add_parser(name)
        p.add_argument("--name", required=True)
        p.add_argument("--threshold", action="append", default=[], help="label=threshold")
        p.add_argument("--default-threshold", type=float, default=0.3)
        if name == "areas":
            p.add_argument("--rasters", action="append", required=True, help="label=prob dir")
        else:
            p.add_argument("--aoi", required=True)
            p.add_argument("--curve", required=True, help="tag of curve_<tag>_installations")
    a = ap.parse_args()
    return cmd_areas(a) if a.cmd == "areas" else cmd_cells(a)


if __name__ == "__main__":
    sys.exit(main())
