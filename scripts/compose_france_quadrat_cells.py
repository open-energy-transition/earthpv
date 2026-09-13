#!/usr/bin/env python
"""Composite the 0.1 degree cells covering France's calibration communes, first.

The national `earthpv compose --aoi france` run selects cells by building count and
works down from the densest, so a 494-building commune like Notre-Dame-de-Londres would
be composited late or (below `--min-buildings`) never. The calibration quadrats are
exactly the cells the roofclf fit cannot start without, so they are built up front here,
on the same grid and with the same window as the national run -- `compose`'s resumable
skip then leaves them alone.

Writes `data/composites/france/composites/<ix>_<iy>/composite_0.tif`, the layout
`CompositeIndex` and `infer` already read.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.compose import CELL_DEG  # noqa: E402
from earthpv.config import Settings  # noqa: E402
from earthpv.imagery import annual_composite  # noqa: E402
from earthpv.labels import resolve_aoi  # noqa: E402

log = logging.getLogger("compose-quadrats")
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]


def quadrat_cells(labels_dir: Path, origin: tuple[float, float]) -> pd.DataFrame:
    """Every cell index touched by a quadrat boundary, on the AOI's pinned grid."""
    gx, gy = origin
    rows = []
    for b in sorted(Path(labels_dir).glob("*_calib_*_boundary.geojson")):
        g = gpd.read_file(b)
        minx, miny, maxx, maxy = g.total_bounds
        ix0, ix1 = int(np.floor((minx - gx) / CELL_DEG)), int(np.floor((maxx - gx) / CELL_DEG))
        iy0, iy1 = int(np.floor((miny - gy) / CELL_DEG)), int(np.floor((maxy - gy) / CELL_DEG))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                rows.append(dict(quadrat=b.name.split("_calib_")[0], ix=ix, iy=iy,
                                 lon0=gx + ix * CELL_DEG, lat0=gy + iy * CELL_DEG))
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["ix", "iy"]).reset_index(drop=True), df


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default="france")
    ap.add_argument("--labels-dir", default="data/labels/france")
    ap.add_argument("--out-dir", default="data/composites")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    settings = Settings.load()
    _, cfg = resolve_aoi(a.aoi, settings)
    origin = tuple(cfg["grid_origin"])
    window = tuple(cfg["compose_window"])
    cells, per_quadrat = quadrat_cells(Path(a.labels_dir), origin)
    log.info("%d unique cells cover %d quadrats; window %s",
             len(cells), per_quadrat.quadrat.nunique(), window)

    out = Path(a.out_dir) / a.aoi / "composites"
    out.mkdir(parents=True, exist_ok=True)

    def one(cell) -> str:
        name = f"{int(cell.ix):04d}_{int(cell.iy):04d}"
        tif = out / name / "composite_0.tif"
        if tif.exists():
            return f"{name} skip"
        bbox = (cell.lon0, cell.lat0, cell.lon0 + CELL_DEG, cell.lat0 + CELL_DEG)
        try:
            res = annual_composite(bbox, date_range=window)
        except Exception as e:  # noqa: BLE001
            return f"{name} FAIL {e}"
        if res is None:
            return f"{name} no-scenes"
        arr, transform, crs = res
        tif.parent.mkdir(parents=True, exist_ok=True)
        tmp = tif.with_suffix(".tif.tmp")
        with rasterio.open(
            tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1],
            count=arr.shape[0], dtype="uint16", crs=crs, transform=transform,
            compress="deflate", predictor=2,
        ) as dst:
            dst.write(arr)
            dst.descriptions = tuple(BANDS)
        tmp.rename(tif)
        return f"{name} ok"

    from concurrent.futures import ThreadPoolExecutor

    rows = [c for _, c in cells.iterrows()]
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(one, rows):
            log.info(r)
    per_quadrat.to_csv(REPO / "results" / "france_quadrat_cells.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
