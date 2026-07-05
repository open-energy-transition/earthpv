"""Build Sentinel-2 composites for an AOI's building-populated cells via STAC.

For regions with no local composites (e.g. Punjab), rooftop PV can only exist where
there are roofs, so we composite only 0.1 deg cells that contain buildings — the
meaningful search space — prioritised by building density (cities first). Output
COGs mirror the rooftopsenti layout (`<cell>/composite_0.tif`) so CompositeIndex
and infer consume them unchanged. Resumable: existing cells are skipped.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from tqdm import tqdm

from earthpv.config import Settings
from earthpv.imagery import annual_composite
from earthpv.labels import resolve_aoi
from earthpv.local_source import load_buildings

log = logging.getLogger(__name__)

CELL_DEG = 0.1


def _aoi_boundary(aoi: str, cfg: dict, settings: Settings) -> gpd.GeoDataFrame | None:
    """Boundary polygon for the AOI. Prefer the AOI-named region (e.g. punjab_500)
    over source_region — source_region supplies imagery/buildings and may cover a
    different, larger area (e.g. pakistan_500 = Balochistan+Sindh)."""
    cands = [f"{aoi}_500", aoi]
    if cfg.get("source_region"):
        cands.append(cfg["source_region"])
    for cand in cands:
        p = Path(settings.raw["local_root"]) / cand / "aoi" / "boundary.parquet"
        if p.exists():
            return gpd.read_parquet(p).to_crs("EPSG:4326")
    return None


def populated_cells(aoi: str, cfg: dict, settings: Settings, min_buildings: int) -> pd.DataFrame:
    """0.1 deg cells within the AOI that contain >= min_buildings, sorted by density.

    Buildings are clipped to the AOI polygon (not just its bbox) so neighbouring
    provinces' cities in the shared building set don't leak in.
    """
    boundary = _aoi_boundary(aoi, cfg, settings)
    bbox = tuple(boundary.total_bounds) if boundary is not None else tuple(cfg["bbox"])
    minx, miny = bbox[0], bbox[1]
    # Optional grid anchor: snap the cell grid so it is congruent (mod CELL_DEG) with
    # another AOI's grid, letting already-composited cells be reused by renaming
    # (e.g. pakistan anchors to punjab's origin to reuse its 64 cells).
    if cfg.get("grid_origin"):
        gx, gy = cfg["grid_origin"]
        minx = gx + np.floor((minx - gx) / CELL_DEG) * CELL_DEG
        miny = gy + np.floor((miny - gy) / CELL_DEG) * CELL_DEG
    bbox = (minx, miny, bbox[2], bbox[3])
    buildings = load_buildings(Path(settings.raw["local_root"]) / cfg["source_region"])
    pts = buildings.geometry.representative_point()
    minx, miny, maxx, maxy = bbox
    inb = (pts.x >= minx) & (pts.x <= maxx) & (pts.y >= miny) & (pts.y <= maxy)
    pts = gpd.GeoDataFrame(geometry=pts[inb].values, crs="EPSG:4326")
    if boundary is not None:
        pts = gpd.sjoin(pts, boundary[["geometry"]], predicate="within", how="inner")
    bx, by = pts.geometry.x.values, pts.geometry.y.values
    ix = np.floor((bx - minx) / CELL_DEG).astype(int)
    iy = np.floor((by - miny) / CELL_DEG).astype(int)
    cells = pd.DataFrame({"ix": ix, "iy": iy}).value_counts().reset_index(name="n")
    cells = cells[cells.n >= min_buildings].reset_index(drop=True)
    cells["lon0"] = minx + cells.ix * CELL_DEG
    cells["lat0"] = miny + cells.iy * CELL_DEG
    return cells.sort_values("n", ascending=False).reset_index(drop=True)


def run_compose(aoi: str, out_dir: Path, min_buildings: int = 1000, limit: int = 0) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    # Mirror the rooftopsenti layout (<region>/composites/<cell>/composite_0.tif) so
    # CompositeIndex reads it unchanged.
    region_dir = Path(out_dir) / aoi
    out_dir = region_dir / "composites"
    out_dir.mkdir(parents=True, exist_ok=True)

    cells = populated_cells(aoi, cfg, settings, min_buildings)
    if limit:
        cells = cells.head(limit)
    log.info("Compositing %d cells (>= %d buildings) for %s", len(cells), min_buildings, aoi)

    done = 0
    for _, cell in tqdm(cells.iterrows(), total=len(cells), desc="compose"):
        name = f"{int(cell.ix):04d}_{int(cell.iy):04d}"
        cell_dir = out_dir / name
        tif = cell_dir / "composite_0.tif"
        if tif.exists():
            continue
        bbox = (cell.lon0, cell.lat0, cell.lon0 + CELL_DEG, cell.lat0 + CELL_DEG)
        try:
            res = annual_composite(bbox)
        except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
            log.warning("cell %s failed: %s", name, e)
            continue
        if res is None:
            log.warning("cell %s: no scenes", name)
            continue
        arr, transform, crs = res
        cell_dir.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            tif, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
            dtype="uint16", crs=crs, transform=transform, compress="deflate", predictor=2,
        ) as dst:
            dst.write(arr)
            dst.descriptions = tuple(
                ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
            )
        done += 1
    log.info("Composited %d new cells -> %s", done, out_dir)
    return region_dir
