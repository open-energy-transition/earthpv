"""Copy a training corpus with Pakistan's sub-400 m2 arrays re-burned as positives.

`chips.MIN_PV_AREA` burns every array below 400 m2 as ignore. This asks whether training on
the mapped arrays between `--floor` (default 100 m2) and 400 m2 as PV teaches segmentation to
find more small rooftop arrays, so it changes nothing else: same chips, same images, same
split, same recipe; only the masks of the given AOIs' TRAIN rows are rewritten, and only by
turning pixels a `--floor`-to-400 m2 polygon touches (all_touched, as `chips._burn_mask` burns
the big ones) into 1. Arrays below the floor stay ignore. Val and buffer rows keep their masks,
so checkpoint selection on val/mIoU means the same thing as for the baseline.

Every registered calibration area (`data/labels/*_calib_*_boundary.geojson`) is held out: a
small array touching one stays ignore, so those Rule-1-complete areas are a clean small-array
test for both checkpoints (`scripts/small_array_eval.py`).

    pixi run python scripts/lower_floor_corpus.py \\
        --index data/chips/combined_pakistan_v16/index.parquet \\
        --aois pakistan_fresh punjab --labels data/labels/pakistan_overpass_solar.parquet \\
        --out /home/tobi/earthpv_data/chips/combined_pakistan_v24_floor100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from rasterio.warp import transform_bounds
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.chips import MIN_PV_AREA  # noqa: E402


def calibration_areas(labels_dir: Path) -> gpd.GeoDataFrame:
    parts = []
    for f in sorted(labels_dir.glob("*_calib_*_boundary.geojson")):
        g = gpd.read_file(f).to_crs(4326)
        g["quadrat"] = f.name.removesuffix("_boundary.geojson")
        parts.append(g[["quadrat", "geometry"]])
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)


def small_labels(path: Path, floor: float, held_out: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    lab = gpd.read_parquet(path)
    lab = lab[lab.geom_type.isin(["Polygon", "MultiPolygon"])]
    lab = lab[(lab.area_m2 >= floor) & (lab.area_m2 < MIN_PV_AREA)].reset_index(drop=True)
    touch = gpd.sjoin(lab, held_out, predicate="intersects").index.unique()
    print(f"{len(lab)} arrays {floor:.0f}-{MIN_PV_AREA:.0f} m2, {len(touch)} touch a calibration "
          f"area and stay ignore")
    return lab.drop(index=touch).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--aois", nargs="+", required=True, help="index `aoi` values to re-burn")
    ap.add_argument("--labels", type=Path, required=True, help="Overpass solar parquet")
    ap.add_argument("--floor", type=float, default=100.0)
    ap.add_argument("--labels-dir", type=Path, default=REPO / "data" / "labels")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    index = pd.read_parquet(a.index)
    held_out = calibration_areas(a.labels_dir)
    lab = small_labels(a.labels, a.floor, held_out)
    sidx = lab.sindex
    (a.out / "masks").mkdir(parents=True, exist_ok=True)

    rows = index[index.aoi.isin(a.aois) & (index.split == "train")]
    todo = rows.drop_duplicates("mask")
    stats = dict(chips=0, chips_changed=0, px_added=0, px_ignore_to_pv=0, px_bg_to_pv=0)
    new_mask: dict[str, str] = {}
    for _, r in todo.iterrows():
        src_path = REPO / r["mask"] if not Path(r["mask"]).is_absolute() else Path(r["mask"])
        with rasterio.open(src_path) as src:
            old = src.read(1)
            prof = src.profile
            bounds4326 = box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds))
            transform, crs, shape = src.transform, src.crs, (src.height, src.width)
        hits = lab.iloc[sidx.query(bounds4326, predicate="intersects")]
        out = old.copy()
        if len(hits):
            geoms = [(g, 1) for g in hits.to_crs(crs).geometry if not g.is_empty]
            burn = rio_features.rasterize(geoms, out_shape=shape, transform=transform, fill=0,
                                          all_touched=True, dtype="uint8").astype(bool)
            add = burn & (old != 1)
            stats["px_ignore_to_pv"] += int((add & (old == -1)).sum())
            stats["px_bg_to_pv"] += int((add & (old == 0)).sum())
            stats["px_added"] += int(add.sum())
            out[add] = 1
            stats["chips_changed"] += int(add.any())
        stats["chips"] += 1
        dst = a.out / "masks" / f"{r['aoi']}_{Path(r['mask']).name}"
        with rasterio.open(dst, "w", **prof) as d:
            d.write(out, 1)
        new_mask[r["mask"]] = str(dst)

    out_index = index.copy()
    sel = out_index.aoi.isin(a.aois) & (out_index.split == "train")
    out_index.loc[sel, "mask"] = out_index.loc[sel, "mask"].map(new_mask)
    for m, dst in new_mask.items():
        with rasterio.open(dst) as d:
            n = int((d.read(1) == 1).sum())
        out_index.loc[sel & (out_index["mask"] == dst), "pv_pixels"] = n
    out_index.to_parquet(a.out / "index.parquet")
    meta = dict(source_index=str(a.index), aois=a.aois, labels=str(a.labels), floor=a.floor,
                held_out_areas=len(held_out), arrays_burned=len(lab), **stats)
    (a.out / "corpus.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
