"""After Pakistan contrast compose: give Punjab its contrast layer and fill any gaps.

1. Reverse-hardlink each Pakistan cell's composite_1 into the matching Punjab cell
   (Punjab ix,iy -> Pakistan ix+85, iy+40; same grid, so the link is pixel-valid).
2. Reconcile: any cell (pakistan or punjab) that has composite_0 but no composite_1
   gets its contrast built directly, so the two-layer infer guard never trips.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import rasterio
from odc.geo.geobox import GeoBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.imagery import annual_composite  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reconcile")

WINDOW = ("2025-09-20", "2025-11-15")
DX, DY = 85, 40  # punjab -> pakistan cell-name offset
COMP = Path("data/composites")


def link_punjab() -> None:
    pj = COMP / "punjab/composites"
    pk = COMP / "pakistan/composites"
    n = 0
    for cell in sorted(pj.iterdir()):
        if not (cell / "composite_0.tif").exists():
            continue
        ix, iy = int(cell.name[:4]) + DX, int(cell.name[5:]) + DY
        src = pk / f"{ix:04d}_{iy:04d}" / "composite_1.tif"
        dst = cell / "composite_1.tif"
        if src.exists() and not dst.exists():
            os.link(src, dst)
            n += 1
    log.info("Linked %d punjab contrast layers from pakistan", n)


def reconcile(region: str) -> None:
    root = COMP / region / "composites"
    missing = [c for c in sorted(root.iterdir())
               if (c / "composite_0.tif").exists() and not (c / "composite_1.tif").exists()]
    log.info("%s: %d cells need contrast built directly", region, len(missing))
    for cell in missing:
        ix, iy = int(cell.name[:4]), int(cell.name[5:])
        # cell lon0/lat0: pakistan grid is anchored to punjab origin; punjab grid too.
        # Recover bbox from the base raster's own georeferencing instead of guessing.
        with rasterio.open(cell / "composite_0.tif") as b:
            gbox = GeoBox((b.height, b.width), b.transform, b.crs)
            import rasterio.warp
            bbox = rasterio.warp.transform_bounds(b.crs, "EPSG:4326", *b.bounds)
        try:
            res = annual_composite(bbox, date_range=WINDOW, geobox=gbox, max_cloud=60)
        except Exception as e:  # noqa: BLE001
            log.warning("%s/%s failed: %s; dropping cell", region, cell.name, e)
            res = None
        if res is None:
            # No contrast data -> drop the cell so the stack stays consistent.
            (cell / "composite_0.tif").unlink()
            for extra in cell.glob("*"):
                extra.unlink()
            cell.rmdir()
            continue
        arr, tr, crs = res
        with rasterio.open(
            cell / "composite_1.tif", "w", driver="GTiff", width=arr.shape[2],
            height=arr.shape[1], count=arr.shape[0], dtype="uint16", crs=crs,
            transform=tr, compress="deflate", predictor=2,
        ) as dst:
            dst.write(arr)
        log.info("%s/%s: built contrast", region, cell.name)


if __name__ == "__main__":
    link_punjab()
    reconcile("punjab")
    reconcile("pakistan")
