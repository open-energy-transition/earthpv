"""Build a contrast-season composite_1.tif on each base tile's exact grid.

Per-chip STAC fetch of the contrast season is ~5 min/chip (thousands of tiny remote
windowed reads); compositing once per base tile and reading windows locally is far
cheaper and reusable. For each base composite_0.tif this loads the contrast-season
scenes onto that tile's geobox, medians them, and writes composite_1.tif beside a
hardlink of the base — into data/composites/<aoi>, which chips/infer already prefer.

Usage: build_contrast_composites.py <aoi> <base_glob> <win_start> <win_end>
  e.g. ... germany '/…/germany_500/composites/*/composite_0.tif' 2025-11-01 2026-03-15
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import rasterio
import rasterio.warp
from odc.geo.geobox import GeoBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.imagery import annual_composite  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("contrast")


def main(aoi: str, base_glob: str, win_start: str, win_end: str) -> None:
    bases = sorted(Path().glob(base_glob) if not base_glob.startswith("/")
                   else map(Path, __import__("glob").glob(base_glob)))
    out_root = Path("data/composites") / aoi / "composites"
    log.info("Building contrast composites for %d base tiles -> %s", len(bases), out_root)
    for base in bases:
        tile = base.parent.name
        cell_dir = out_root / tile
        cell_dir.mkdir(parents=True, exist_ok=True)
        base_link = cell_dir / "composite_0.tif"
        if not base_link.exists():
            os.link(base, base_link)  # reuse base pixels without copying
        out = cell_dir / "composite_1.tif"
        if out.exists():
            log.info("%s: composite_1 exists, skip", tile)
            continue
        with rasterio.open(base) as b:
            gbox = GeoBox((b.height, b.width), b.transform, b.crs)
            bbox = rasterio.warp.transform_bounds(b.crs, "EPSG:4326", *b.bounds)
        try:
            res = annual_composite(bbox, date_range=(win_start, win_end),
                                   geobox=gbox, max_cloud=60, max_items=15)
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", tile, e)
            continue
        if res is None:
            log.warning("%s: no contrast scenes", tile)
            continue
        arr, transform, crs = res
        with rasterio.open(
            out, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1],
            count=arr.shape[0], dtype="uint16", crs=crs, transform=transform,
            compress="deflate", predictor=2,
        ) as dst:
            dst.write(arr)
        log.info("%s: wrote composite_1 %dx%d nonzero=%.2f", tile, arr.shape[2],
                 arr.shape[1], float((arr > 0).mean()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
