"""Where each model's unmapped objects lie, by land cover, over a whole-cell sample.

Companion to `scripts/sheet_scan.py curve` for Indonesia (2026-11-26): the curve counts
unmapped objects (>= 4 px, touching no mapped solar) per model and threshold; this says what
they sit on, using the land-cover layers `landcover_hard_negatives.py` reads: oil palm extent
(Descals et al. 2024), mining footprints (Tang & Werner 2023), forest lost since 2021 (Hansen
GFC 2025) and OSM aquaculture. An object is assigned by its centroid pixel, mine first, then
aquaculture, oil palm, clearing, else "other". It also writes every unmapped object >= 1 ha
with its centroid, for looking at on Sentinel-2.

    pixi run python scripts/indonesia_false_objects.py --cells data/sheet_scan/indonesia/cells_random.txt \\
        --model v28=data/predictions/indonesia/prob@0.98 \\
        --model v48r=data/sheet_scan/indonesia/v48r_e07/indonesia/prob@0.3 \\
        --labels data/labels/indonesia_changesets_20261126/indonesia_overpass_solar.parquet \\
        --out results/indonesia_model_comparison/random_landcover.csv
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
LC = Path("/home/tobi/earthpv_data/landcover")


def _lhn():
    spec = importlib.util.spec_from_file_location(
        "lhn", REPO / "scripts" / "landcover_hard_negatives.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sample_tiles(tiles, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Class hit at each point (nearest pixel of the tile holding it)."""
    out = np.zeros(len(lon), bool)
    for k, (x, y) in enumerate(zip(lon, lat)):
        for p in tiles.covering((x, y, x, y)):
            r = tiles._src(p)
            row, col = r.index(x, y)
            if 0 <= row < r.height and 0 <= col < r.width:
                v = r.read(1, window=((row, row + 1), (col, col + 1)))
                out[k] = bool(tiles.hit(v).any())
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cells", type=Path, required=True)
    ap.add_argument("--model", action="append", required=True, help="name=prob_dir@threshold")
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--osm-landuse", type=Path,
                    default=Path("/home/tobi/earthpv_data/indonesia_hardneg/landuse_polygons.parquet"))
    ap.add_argument("--clearing-since", type=int, default=2021)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    import rasterio
    import rasterio.warp
    from rasterio import features
    from scipy import ndimage

    lhn = _lhn()
    cells = a.cells.read_text().split()
    bounds = (95.0, -11.1, 141.1, 6.0)
    palm = lhn.RasterTiles(LC / "oilpalm_descals2024" / "extent", bounds)
    since = a.clearing_since - 2000
    loss = lhn.RasterTiles(LC / "hansen_gfc2025", bounds, hit=lambda v: v >= since)
    mines = gpd.read_parquet(LC / "mining_tang2023" / "indonesia_mines.parquet")
    osm = lhn.osm_classes(a.osm_landuse)
    mines = pd.concat([mines[["geometry"]], osm[osm.lc_class == "mine"][["geometry"]]])
    aqua = osm[osm.lc_class == "aquaculture"][["geometry"]]
    mapped = gpd.read_parquet(a.labels)
    mapped = mapped[mapped.geometry.notna()]

    specs = []
    for s in a.model:
        name, _, rest = s.partition("=")
        d, _, t = rest.rpartition("@")
        specs.append((name, Path(d), float(t)))

    rows, area_km2 = [], 0.0
    for i, cell in enumerate(cells):
        with rasterio.open(specs[0][1] / f"{cell}.tif") as r:
            tr, crs, shape = r.transform, r.crs, r.shape
            px_m2 = abs(tr.a * tr.e)
            b4326 = rasterio.warp.transform_bounds(crs, "EPSG:4326", *r.bounds)
        area_km2 += shape[0] * shape[1] * px_m2 / 1e6
        hits = mapped.iloc[list(mapped.sindex.intersection(b4326))]
        known = np.zeros(shape, bool)
        if len(hits):
            known = features.rasterize([(g, 1) for g in hits.geometry.to_crs(crs)],
                                       out_shape=shape, transform=tr, all_touched=True).astype(bool)
        for name, d, thr in specs:
            with rasterio.open(d / f"{cell}.tif") as r:
                on = r.read(1).astype(np.float32) / 255.0 >= thr
            lab, n = ndimage.label(on)
            if not n:
                continue
            size = np.bincount(lab.ravel(), minlength=n + 1)
            touch = np.bincount(lab.ravel(), weights=known.ravel(), minlength=n + 1) > 0
            keep = [j for j in range(1, n + 1) if size[j] >= 4 and not touch[j]]
            if not keep:
                continue
            cy, cx = zip(*ndimage.center_of_mass(on, lab, keep))
            xs, ys = rasterio.transform.xy(tr, cy, cx)
            lon, lat = rasterio.warp.transform(crs, "EPSG:4326", xs, ys)
            for j, x, y in zip(keep, lon, lat):
                rows.append(dict(model=name, threshold=thr, cell=cell, lon=x, lat=y,
                                 area_m2=float(size[j] * px_m2)))
        if i % 100 == 0:
            print(f"{i}/{len(cells)} {cell}", flush=True)
    obj = pd.DataFrame(rows)
    if obj.empty:
        print("no unmapped objects")
        return 0
    pts = gpd.GeoDataFrame(obj, geometry=gpd.points_from_xy(obj.lon, obj.lat), crs="EPSG:4326")
    on_mine = pts.intersects(mines.union_all()).to_numpy()
    on_aqua = pts.intersects(aqua.union_all()).to_numpy() if len(aqua) else np.zeros(len(pts), bool)
    on_palm = sample_tiles(palm, obj.lon.to_numpy(), obj.lat.to_numpy())
    on_loss = sample_tiles(loss, obj.lon.to_numpy(), obj.lat.to_numpy())
    obj["land_cover"] = np.select([on_mine, on_aqua, on_palm, on_loss],
                                  ["mine", "aquaculture", "oil_palm", "clearing"], "other")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    obj.to_parquet(a.out.with_suffix(".parquet"))
    per = 1000.0 / area_km2
    summ = (obj.groupby(["model", "threshold", "land_cover"])
            .agg(objects=("area_m2", "size"), km2=("area_m2", lambda s: s.sum() / 1e6))
            .reset_index())
    tot = obj.groupby(["model", "threshold"]).agg(objects=("area_m2", "size"),
                                                  km2=("area_m2", lambda s: s.sum() / 1e6))
    summ["objects_per_1000km2"] = (summ.objects * per).round(2)
    summ.to_csv(a.out, index=False)
    print(f"{len(cells)} cells, {area_km2:,.0f} km2")
    print((tot.assign(per_1000km2=(tot.objects * per).round(2))).to_string())
    print(summ.pivot_table(index=["model", "threshold"], columns="land_cover",
                           values="objects", fill_value=0).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
