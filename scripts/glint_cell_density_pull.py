"""Pull per-CELL (not per-installation) reflectance time series for the cell-aggregate
glint density calibration test. Same scene-search machinery as glint.py, but the
band-stats function here compares the whole cell against a WIDE external ring (150-400m
beyond the cell edge) rather than glint.py's 30m annulus -- a dense urban block's
immediate surroundings may contain other PV, so a tight annulus risks comparing panels
against panels instead of against a true non-PV background.

Usage:
  .pixi/envs/default/bin/python scripts/glint_cell_density_pull.py
"""

from __future__ import annotations

import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.warp
import rasterio.windows

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("cell_density_pull")

OUT_DIR = DATA_DIR / "glint_cell"
SERIES_DIR = OUT_DIR / "series"
CELLS_FILE = OUT_DIR / "cells.parquet"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BANDS = ("B03", "B08")
RING_INNER_M = 150.0
RING_OUTER_M = 450.0
TARGET_THREADS = 4
SCENE_THREADS = 6
_GDAL_ENV = dict(GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2", VSI_CACHE="TRUE")


def _cell_band_stats(item, band: str, geometry, lon: float, lat: float, provider: str) -> tuple[float, float, int]:
    """(p90 inside the cell, wide-ring median outside it, n inside px)."""
    href = item.assets[glint._band_asset_key(band, provider)].href
    with rasterio.Env(**_GDAL_ENV), rasterio.open(href) as src:
        xs, ys = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
        row, col = src.index(xs[0], ys[0])
        geom_native = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(src.crs).iloc[0]
        r_px = int(RING_OUTER_M / 10 + 15)
        win = rasterio.windows.Window(col - r_px, row - r_px, 2 * r_px, 2 * r_px)
        arr = src.read(1, window=win, boundless=True, fill_value=0).astype(float)
        wt = src.window_transform(win)
        inside = rasterio.features.geometry_mask([geom_native], arr.shape, wt, invert=True, all_touched=False)
        # Annulus = inside the outer buffer AND NOT inside the inner buffer. (A previous
        # version put the negation on the wrong buffer -- "farther than outer" AND "within
        # inner" is a logical impossibility, so the ring was always empty and every scene
        # silently failed the min-valid-pixel check below.)
        ring = rasterio.features.geometry_mask(
            [geom_native.buffer(RING_OUTER_M)], arr.shape, wt, invert=True
        ) & ~rasterio.features.geometry_mask(
            [geom_native.buffer(RING_INNER_M)], arr.shape, wt, invert=True
        )
    arr[arr == 0] = np.nan
    arr = arr + glint._boa_offset(item, provider)
    inside_v, ring_v = arr[inside], arr[ring]
    if np.isfinite(inside_v).sum() < 20 or np.isfinite(ring_v).sum() < 50:
        return np.nan, np.nan, 0
    return float(np.nanpercentile(inside_v, 90)), float(np.nanmedian(ring_v)), int(np.isfinite(inside_v).sum())


def _scene_row(item, geometry, lon: float, lat: float, provider: str) -> dict | None:
    try:
        ta = glint._cached_tile_angles(item, provider)
        ang = ta.at(lon, lat)
        if ang is None:
            return None
        row = dict(time=ta.sensing_time or item.datetime, cloud=item.properties.get("eo:cloud_cover"), **ang)
        for band in BANDS:
            p90, ring, npx = _cell_band_stats(item, band, geometry, lon, lat, provider)
            row[f"p90_{band}"], row[f"ring_{band}"] = p90, ring
            row["npx"] = npx
        return row
    except Exception as e:  # noqa: BLE001 — per-scene failures shouldn't kill the pull
        log.debug("scene %s failed: %s", item.id, e)
        return None


def _cell_series(geometry, start: datetime, end: datetime) -> pd.DataFrame:
    lon, lat = geometry.centroid.x, geometry.centroid.y
    rows = []
    for provider in ("planetary-computer", "earth-search"):
        items = glint._search_items(provider, lon, lat, start, end, MAX_CLOUD)
        if not items:
            continue
        with ThreadPoolExecutor(SCENE_THREADS) as ex:
            futs = [ex.submit(_scene_row, it, geometry, lon, lat, provider) for it in items]
            for f in as_completed(futs):
                r = f.result()
                if r:
                    rows.append(r)
        if rows:
            break
    return pd.DataFrame(rows).sort_values("time") if rows else pd.DataFrame()


def _pull_one(row) -> str:
    dst = SERIES_DIR / f"{row.cid}.parquet"
    if dst.exists():
        return "skip"
    df = _cell_series(row.geometry, DATE_RANGE[0], DATE_RANGE[1])
    df.to_parquet(dst)
    return f"{row.cid} ({row.stratum}, area={row.area_m2:.0f}m2): {len(df)} scenes"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    cells = gpd.read_parquet(CELLS_FILE)
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    todo = [r for r in cells.itertuples() if not (SERIES_DIR / f"{r.cid}.parquet").exists()]
    log.info("%d cells total, %d to pull", len(cells), len(todo))
    done = 0
    with ThreadPoolExecutor(TARGET_THREADS) as ex:
        futs = {ex.submit(_pull_one, r): r.cid for r in todo}
        for f in as_completed(futs):
            try:
                msg = f.result()
            except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
                msg = f"{futs[f]} FAILED: {e}"
            done += 1
            log.info("[%d/%d] %s", done, len(todo), msg)
    log.info("CELL_PULL_DONE")


if __name__ == "__main__":
    main()
