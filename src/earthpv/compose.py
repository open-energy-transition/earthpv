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
from earthpv.local_source import load_buildings, load_solar_labels

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


def _solar_label_cells(
    cfg: dict,
    settings: Settings,
    minx: float,
    miny: float,
    bbox: tuple[float, float, float, float],
    boundary: gpd.GeoDataFrame | None,
) -> set[tuple[int, int]]:
    """Cells (same grid/origin as populated_cells) that contain an OSM solar positive.

    Building density finds *unknown* arrays for inference; these guarantee imagery
    over *already-mapped* arrays so each becomes a trainable in-domain positive,
    independent of local building density. Uses the same bbox + boundary clip as the
    building pass so nothing outside the AOI leaks in.
    """
    region_dir = Path(settings.raw["local_root"]) / cfg["source_region"]
    labels = load_solar_labels(region_dir)
    if labels is None or labels.empty:
        return set()
    pts = labels.geometry.representative_point()
    xmin, ymin, xmax, ymax = bbox
    inb = (pts.x >= xmin) & (pts.x <= xmax) & (pts.y >= ymin) & (pts.y <= ymax)
    pts = gpd.GeoDataFrame(geometry=pts[inb].values, crs="EPSG:4326")
    if boundary is not None and not pts.empty:
        pts = gpd.sjoin(pts, boundary[["geometry"]], predicate="within", how="inner")
    if pts.empty:
        return set()
    ix = np.floor((pts.geometry.x.values - minx) / CELL_DEG).astype(int)
    iy = np.floor((pts.geometry.y.values - miny) / CELL_DEG).astype(int)
    return set(zip(ix.tolist(), iy.tolist()))


def populated_cells(
    aoi: str, cfg: dict, settings: Settings, min_buildings: int, include_labels: bool = True
) -> pd.DataFrame:
    """0.1 deg cells within the AOI to composite, sorted by building density.

    A cell is selected if it has >= min_buildings buildings OR (when include_labels)
    it contains an OSM solar polygon — so density coverage for finding new arrays is
    unioned with full imagery coverage over every already-mapped one. Buildings are
    clipped to the AOI polygon (not just its bbox) so neighbouring provinces' cities
    in the shared building set don't leak in.
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

    label_cells = (
        _solar_label_cells(cfg, settings, minx, miny, bbox, boundary) if include_labels else set()
    )
    has_label = (
        np.array([(a, b) in label_cells for a, b in zip(cells.ix, cells.iy)], dtype=bool)
        if label_cells
        else np.zeros(len(cells), dtype=bool)
    )
    n_by_density = int((cells.n >= min_buildings).sum())
    cells = cells[(cells.n >= min_buildings) | has_label].reset_index(drop=True)
    # Label cells with no mapped buildings at all are absent from the histogram; add them.
    extra = sorted(label_cells - set(zip(cells.ix, cells.iy)))
    if extra:
        cells = pd.concat(
            [cells, pd.DataFrame({"ix": [a for a, _ in extra], "iy": [b for _, b in extra], "n": 0})],
            ignore_index=True,
        )
    cells["lon0"] = minx + cells.ix * CELL_DEG
    cells["lat0"] = miny + cells.iy * CELL_DEG
    if include_labels:
        log.info(
            "Selected %d cells: %d by density (>=%d buildings), %d contain OSM solar labels",
            len(cells), n_by_density, min_buildings, len(label_cells),
        )
    return cells.sort_values("n", ascending=False).reset_index(drop=True)


def run_compose(
    aoi: str,
    out_dir: Path,
    min_buildings: int = 1000,
    limit: int = 0,
    window: tuple[str, str] | None = None,
    index: int = 0,
    workers: int = 1,
    include_labels: bool = True,
) -> Path:
    """`window`/`index` build an extra seasonal layer (`composite_<index>.tif`, e.g.
    a post-monsoon contrast season) into the same cell dirs as the base run.

    `workers` > 1 composites cells concurrently. The work is I/O-bound (remote STAC
    scene reads), so threads overlap the network waits for a near-linear speedup;
    the STAC search is serialized internally (annual_composite) for thread safety.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if index > 0 and window is None:
        raise ValueError("compose --index > 0 requires --window (the layer's date range)")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    # Mirror the rooftopsenti layout (<region>/composites/<cell>/composite_0.tif) so
    # CompositeIndex reads it unchanged.
    region_dir = Path(out_dir) / aoi
    out_dir = region_dir / "composites"
    out_dir.mkdir(parents=True, exist_ok=True)

    cells = populated_cells(aoi, cfg, settings, min_buildings, include_labels)
    if limit:
        cells = cells.head(limit)
    log.info("Compositing %d cells (>= %d buildings) for %s (%d workers)",
             len(cells), min_buildings, aoi, workers)

    def _one(cell) -> bool:
        name = f"{int(cell.ix):04d}_{int(cell.iy):04d}"
        cell_dir = out_dir / name
        tif = cell_dir / f"composite_{index}.tif"
        if tif.exists():
            return False
        bbox = (cell.lon0, cell.lat0, cell.lon0 + CELL_DEG, cell.lat0 + CELL_DEG)
        try:
            if index > 0:
                # Pin the extra layer to the base layer's exact grid.
                base = cell_dir / "composite_0.tif"
                if not base.exists():
                    log.warning("cell %s: no base composite for layer %d", name, index)
                    return False
                from odc.geo.geobox import GeoBox

                with rasterio.open(base) as b:
                    gbox = GeoBox((b.height, b.width), b.transform, b.crs)
                res = annual_composite(bbox, date_range=window, geobox=gbox, max_cloud=60)
            else:
                res = annual_composite(bbox, date_range=window) if window else annual_composite(bbox)
        except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
            log.warning("cell %s failed: %s", name, e)
            return False
        if res is None:
            log.warning("cell %s: no scenes", name)
            return False
        arr, transform, crs = res
        cell_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temp then rename so a killed run never leaves a half-written COG
        # that the resumable skip would treat as done.
        tmp = tif.with_suffix(".tif.tmp")
        with rasterio.open(
            tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
            dtype="uint16", crs=crs, transform=transform, compress="deflate", predictor=2,
        ) as dst:
            dst.write(arr)
            dst.descriptions = tuple(
                ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
            )
        tmp.rename(tif)
        return True

    rows = [cell for _, cell in cells.iterrows()]
    done = 0
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ok in tqdm(ex.map(_one, rows), total=len(rows), desc="compose"):
                done += int(ok)
    else:
        for cell in tqdm(rows, desc="compose"):
            done += int(_one(cell))
    log.info("Composited %d new cells -> %s", done, out_dir)
    return region_dir
