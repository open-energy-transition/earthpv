"""Build the `punjab_boom` AOI's composite tree (see configs/aoi.yaml).

Reuses punjab's 65 existing composite_0.tif via symlink (current epoch, unaffected by
the Collection-1 radiometric-offset bug fixed 2026-07-26), fetches composite_0 fresh for
the 9 val_tiles cells punjab's own composed set never covered, then builds composite_1
for all resulting cells at the real pre-boom window (2021-10-01..2022-01-24) with the
now-fixed imagery.py -- unlike data/composites/punjab/composites/*/composite_1.tif,
which is the seasonal experiment's stale post-monsoon-2025 contrast, built before that
fix, under the same filename.

Deliberately bounded to punjab's original 65-cell footprint + the 9 missing val cells
(74 total), not the full ~133-cell Punjab OSM-label-cell population -- this keeps the
comparison to the seasonal experiment apples-to-apples (same training footprint, only
the contrast window changes) and bounds this to a same-session, network-bound job
instead of an hours-longer one that would also change what's being tested.
"""

from __future__ import annotations

import logging
from pathlib import Path

import rasterio
import rasterio.warp
from odc.geo.geobox import GeoBox

from earthpv.compose import populated_cells
from earthpv.config import Settings
from earthpv.imagery import annual_composite
from earthpv.labels import resolve_aoi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_punjab_boom_composites")

BOOM_WINDOW = ("2021-10-01", "2022-01-24")
BAND_DESCRIPTIONS = ("B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12")


def _write(tif: Path, arr, transform, crs) -> None:
    cell_dir = tif.parent
    cell_dir.mkdir(parents=True, exist_ok=True)
    tmp = tif.with_suffix(".tif.tmp")
    with rasterio.open(
        tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
        dtype="uint16", crs=crs, transform=transform, compress="deflate", predictor=2,
    ) as dst:
        dst.write(arr)
        dst.descriptions = BAND_DESCRIPTIONS
    tmp.rename(tif)


def main() -> None:
    settings = Settings.load()
    _, cfg = resolve_aoi("punjab", settings)
    src_root = Path("data/composites/punjab/composites")
    dst_root = Path("data/composites/punjab_boom/composites")
    dst_root.mkdir(parents=True, exist_ok=True)

    existing = sorted(p.name for p in src_root.iterdir() if p.is_dir())
    log.info("Symlinking %d existing punjab cells' composite_0 into punjab_boom", len(existing))
    for name in existing:
        src = src_root / name / "composite_0.tif"
        if not src.exists():
            log.warning("cell %s: no composite_0.tif in punjab, skipping", name)
            continue
        dst_dir = dst_root / name
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "composite_0.tif"
        if not dst.exists():
            dst.symlink_to(src.resolve())

    val_tiles = set(cfg["val_tiles"])
    missing_val = sorted(val_tiles - set(existing))
    log.info("val_tiles missing composite_0: %s", missing_val)
    if missing_val:
        # label-only selection (huge min_buildings) gives exactly the OSM-solar-label
        # cells' lon0/lat0 without pulling in punjab's full building-density population.
        cells = populated_cells("punjab", cfg, settings, min_buildings=10**9, include_labels=True)
        cells["name"] = [f"{int(r.ix):04d}_{int(r.iy):04d}" for _, r in cells.iterrows()]
        lookup = cells.set_index("name")
        for name in missing_val:
            if name not in lookup.index:
                log.warning("val cell %s not found in label-cell set, skipping", name)
                continue
            row = lookup.loc[name]
            bbox = (row.lon0, row.lat0, row.lon0 + 0.1, row.lat0 + 0.1)
            tif = dst_root / name / "composite_0.tif"
            if tif.exists():
                continue
            res = annual_composite(bbox)
            if res is None:
                log.warning("cell %s: no scenes for base composite_0, skipping entirely", name)
                continue
            arr, transform, crs = res
            _write(tif, arr, transform, crs)
            log.info("cell %s: built fresh composite_0", name)

    all_cells = sorted(p.name for p in dst_root.iterdir() if p.is_dir())
    log.info("%d total cells in punjab_boom; building composite_1 (boom window %s)",
             len(all_cells), BOOM_WINDOW)
    n_built, n_skipped, n_failed = 0, 0, 0
    for name in all_cells:
        cell_dir = dst_root / name
        base = cell_dir / "composite_0.tif"
        tif = cell_dir / "composite_1.tif"
        if tif.exists():
            n_skipped += 1
            continue
        if not base.exists():
            log.warning("cell %s: no base composite_0, cannot pin composite_1", name)
            n_failed += 1
            continue
        with rasterio.open(base) as b:
            gbox = GeoBox((b.height, b.width), b.transform, b.crs)
            bounds4326 = rasterio.warp.transform_bounds(b.crs, "EPSG:4326", *b.bounds)
        try:
            res = annual_composite(bounds4326, date_range=BOOM_WINDOW, geobox=gbox, max_cloud=60)
        except Exception as e:  # noqa: BLE001 - one bad cell must not kill the run
            log.warning("cell %s: composite_1 failed: %s", name, e)
            n_failed += 1
            continue
        if res is None:
            log.warning("cell %s: no scenes in boom window", name)
            n_failed += 1
            continue
        arr, transform, crs = res
        _write(tif, arr, transform, crs)
        n_built += 1
        if n_built % 10 == 0:
            log.info("Built %d/%d composite_1 so far (%d skipped, %d failed)",
                      n_built, len(all_cells), n_skipped, n_failed)

    log.info("Done: %d composite_1 built, %d already present, %d failed -> %s",
              n_built, n_skipped, n_failed, dst_root)


if __name__ == "__main__":
    main()
