"""Bi-temporal hard-negative mining.

Large building footprints with no known OSM solar match are the natural hard-negative
source for this task: roofs plausible enough to host PV, currently unlabeled. But
"unlabeled" doesn't mean "empty" -- OSM mapping lags real installations (that lag is the
whole premise of this project), so a candidate building could already carry an unmapped
array. Blindly training on it as a negative would punish a true positive.

This module screens that out with a bi-temporal check: run the current best checkpoint
over BOTH the present-day composite and an independently-built composite from an older
year (e.g. 2022) at each candidate building. A candidate only becomes a confirmed hard
negative if the model sees no PV signal at EITHER date -- a stable, persistent non-PV
building the model should learn to leave alone. A candidate with signal now but not in
the older year looks like a recent, still-unmapped installation instead -- a genuine
lead, not something to suppress -- and is written to a separate file rather than
discarded.

The older-year composite is a throwaway filtering artifact (composite_<year>.tif,
cached per-cell so reruns are cheap); the actual training chip is always cut from the
CURRENT composite via chips.py, matching every other chip in the dataset.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
import shapely
from tqdm import tqdm

from earthpv.buildings import _iso3_for, fetch_vida_buildings
from earthpv.config import CHIP_SIZE, MODEL_BANDS, Settings
from earthpv.export import _load_mapped_reference
from earthpv.imagery import annual_composite
from earthpv.infer import load_model, predict_window
from earthpv.labels import resolve_aoi
from earthpv.local_source import CompositeIndex

log = logging.getLogger(__name__)

MIN_BUILDING_AREA_M2 = 400.0  # matches chips.MIN_PV_AREA: the practical scale floor
DECLUTTER_M = 300.0  # keep at most one candidate per this-size cell (diversity, not one complex)
MAPPED_BUFFER_M = 75.0  # halo around a building that counts as "already has a match"; a
# 20 m halo (tried first) let ~10% of "confirmed" negatives through with a real OSM match
# a bit further from the building outline than that (VIDA/OSM footprint misalignment,
# or the array sitting just off the building polygon) -- widened after inspecting
# build_hard_negative_chips's safety-net burn on an initial Pakistan run.


def find_candidate_buildings(
    aoi: str, cfg: dict, settings: Settings, comp_idx: CompositeIndex,
    min_area_m2: float = MIN_BUILDING_AREA_M2, limit: int = 0,
) -> gpd.GeoDataFrame:
    """Large VIDA buildings inside the AOI's already-composited coverage, with no
    nearby OSM solar match, largest first, decluttered to ~one per DECLUTTER_M cell."""
    iso3 = _iso3_for(cfg)
    if not iso3:
        raise ValueError(f"AOI '{aoi}' has no resolvable ISO3 country for VIDA buildings.")
    coverage = comp_idx.coverage
    bbox = tuple(gpd.GeoSeries([coverage], crs="EPSG:4326").total_bounds)
    log.info("Querying VIDA %s buildings >= %.0f m2 in composited coverage bbox=%s", iso3, min_area_m2, bbox)
    buildings = fetch_vida_buildings(bbox, iso3, min_area_m2=min_area_m2)
    if buildings.empty:
        return buildings
    cx = buildings.geometry.centroid
    within = shapely.contains_xy(coverage, cx.x.to_numpy(), cx.y.to_numpy())
    buildings = buildings[within].reset_index(drop=True)
    log.info("%d large buildings inside composited cells", len(buildings))
    if buildings.empty:
        return buildings

    mapped = _load_mapped_reference(aoi, cfg, settings)
    if mapped is not None and not mapped.empty:
        sindex = mapped.sindex
        halo = buildings.geometry.buffer(MAPPED_BUFFER_M / 111320.0)
        has_match = np.array([len(sindex.query(g, predicate="intersects")) > 0 for g in halo])
        buildings = buildings[~has_match].reset_index(drop=True)
        log.info("%d remain after dropping buildings near a known OSM solar polygon", len(buildings))

    buildings = buildings.sort_values("area_m2", ascending=False).reset_index(drop=True)
    cx = buildings.geometry.centroid
    deg = DECLUTTER_M / 111320.0
    cell = (cx.x / deg).round().astype(int).astype(str) + "_" + (cx.y / deg).round().astype(int).astype(str)
    buildings = buildings.loc[~cell.duplicated()].reset_index(drop=True)
    log.info("%d remain after %.0f m spatial declutter", len(buildings), DECLUTTER_M)
    if limit and len(buildings) > limit:
        buildings = buildings.head(limit).reset_index(drop=True)
    return buildings


def _read_chip(path: Path, lon: float, lat: float, n_bands: int) -> tuple[np.ndarray, rasterio.Affine, object] | None:
    with rasterio.open(path) as src:
        (x,), (y,) = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
        col, row = ~src.transform * (x, y)
        col, row = int(col) - CHIP_SIZE // 2, int(row) - CHIP_SIZE // 2
        win = rasterio.windows.Window(col, row, CHIP_SIZE, CHIP_SIZE)
        arr = src.read(window=win, boundless=True, fill_value=0)[:n_bands]
        if (arr > 0).mean() < 0.2:
            return None
        return arr, src.window_transform(win), src.crs


def _building_max_prob(prob: np.ndarray, geom, win_transform, crs) -> float:
    geom_utm = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(crs).iloc[0]
    from rasterio import features as rio_features

    mask = rio_features.rasterize(
        [(geom_utm, 1)], out_shape=prob.shape, transform=win_transform, fill=0, dtype="uint8"
    ).astype(bool)
    if not mask.any():
        h, w = prob.shape
        return float(prob[h // 2, w // 2])
    return float(prob[mask].max())


def _build_old_composite(now_path: Path, tile_bounds: tuple, date_range: tuple[str, str], year_tag: str) -> Path | None:
    old_path = now_path.with_name(f"composite_{year_tag}.tif")
    if old_path.exists():
        return old_path
    from odc.geo.geobox import GeoBox

    with rasterio.open(now_path) as base:
        gbox = GeoBox((base.height, base.width), base.transform, base.crs)
    try:
        res = annual_composite(tile_bounds, date_range=date_range, geobox=gbox)
    except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
        log.warning("cell %s: %s composite failed: %s", now_path.parent.name, year_tag, e)
        return None
    if res is None:
        log.warning("cell %s: no scenes for %s", now_path.parent.name, year_tag)
        return None
    arr, transform, crs = res
    tmp = old_path.with_suffix(".tif.tmp")
    with rasterio.open(
        tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
        dtype="uint16", crs=crs, transform=transform, compress="deflate", predictor=2,
    ) as dst:
        dst.write(arr)
        dst.descriptions = tuple(["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"])
    tmp.rename(old_path)
    return old_path


def run_hard_negatives(
    aoi: str,
    checkpoint: Path,
    compare_year: str = "2022",
    window: tuple[str, str] | None = None,
    composites_dir: Path = Path("data/composites"),
    out_dir: Path = Path("data/predictions"),
    min_area_m2: float = MIN_BUILDING_AREA_M2,
    limit: int = 300,
    neg_prob_threshold: float = 0.1,
    jitter_m: float = 300.0,
    workers: int = 4,
) -> Path:
    """Mine confirmed hard negatives for `aoi`, writing:

    - <out_dir>/<aoi>/hard_negatives_confirmed.parquet: lon, lat, kind="hard_negative",
      ready to feed into chips.build_hard_negative_chips.
    - <out_dir>/<aoi>/hard_negatives_flagged_leads.parquet: candidates with signal now
      but not in `compare_year` -- likely real, still-unmapped installs; not negatives.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    date_range = window or (f"{compare_year}-01-01", f"{compare_year}-12-31")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    comp_idx = CompositeIndex(Path(composites_dir) / aoi)

    buildings = find_candidate_buildings(aoi, cfg, settings, comp_idx, min_area_m2, limit)
    if buildings.empty:
        log.warning("No candidate buildings found for %s", aoi)
        return Path(out_dir) / aoi / "hard_negatives_confirmed.parquet"

    now_idx = comp_idx.index.reset_index(drop=True)
    joined = gpd.sjoin(buildings, now_idx[["geometry", "path"]], predicate="within", how="inner")
    joined = joined[~joined.index.duplicated()]
    log.info(
        "%d candidate buildings across %d composite cells", len(joined), joined["path"].nunique()
    )

    rng = np.random.default_rng(42)
    jit_deg = jitter_m / 111320.0
    n_bands = len(MODEL_BANDS)

    # Phase 1: build every distinct cell's older-year composite concurrently -- this
    # is the dominant cost (network-bound STAC fetch, one per cell, same as compose.py's
    # own workers pattern) and is embarrassingly parallel across cells.
    groups = list(joined.groupby("path"))
    log.info("Building %s composites for %d cells (%d workers)", compare_year, len(groups), workers)

    def _old_for(item) -> tuple[str, Path | None]:
        path, group = item
        tile_idx = group["index_right"].iloc[0]
        tile_bounds = now_idx.loc[tile_idx, "geometry"].bounds
        return path, _build_old_composite(Path(path), tile_bounds, date_range, compare_year)

    old_paths: dict[str, Path | None] = {}
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for path, old_path in tqdm(ex.map(_old_for, groups), total=len(groups), desc=f"{compare_year} composites"):
                old_paths[path] = old_path
    else:
        for item in tqdm(groups, desc=f"{compare_year} composites"):
            path, old_path = _old_for(item)
            old_paths[path] = old_path

    # Phase 2: per-building inference -- fast, GPU-bound, sequential (one model instance).
    task, device, task_type = load_model(checkpoint, task_type="auto")
    log.info("Loaded %s checkpoint %s", task_type, checkpoint)

    confirmed, flagged, ambiguous_ct, no_old_data_ct = [], [], 0, 0
    for path, group in tqdm(groups, desc="buildings"):
        now_path = Path(path)
        old_path = old_paths.get(path)
        if old_path is None:
            no_old_data_ct += len(group)
            continue
        for _, row in group.iterrows():
            cx, cy = row.geometry.centroid.x, row.geometry.centroid.y
            jx = rng.uniform(-jit_deg, jit_deg) / np.cos(np.radians(cy))
            jy = rng.uniform(-jit_deg, jit_deg)
            lon, lat = cx + jx, cy + jy
            now_chip = _read_chip(now_path, lon, lat, n_bands)
            old_chip = _read_chip(old_path, lon, lat, n_bands)
            if now_chip is None or old_chip is None:
                continue
            arr_now, tf_now, crs_now = now_chip
            arr_old, tf_old, crs_old = old_chip
            prob_now = _building_max_prob(
                predict_window(arr_now, task, device, task_type), row.geometry, tf_now, crs_now
            )
            prob_old = _building_max_prob(
                predict_window(arr_old, task, device, task_type), row.geometry, tf_old, crs_old
            )
            rec = dict(
                lon=lon, lat=lat, kind="hard_negative", placement=None,
                area_m2=float(row.area_m2), prob_now=prob_now, prob_old=prob_old,
            )
            if prob_now < neg_prob_threshold and prob_old < neg_prob_threshold:
                confirmed.append(rec)
            elif prob_now >= neg_prob_threshold and prob_old < neg_prob_threshold:
                flagged.append(rec)
            else:
                ambiguous_ct += 1

    out_dir = Path(out_dir) / aoi
    out_dir.mkdir(parents=True, exist_ok=True)
    confirmed_df = pd.DataFrame(confirmed)
    flagged_df = pd.DataFrame(flagged)
    confirmed_path = out_dir / "hard_negatives_confirmed.parquet"
    flagged_path = out_dir / "hard_negatives_flagged_leads.parquet"
    confirmed_df.to_parquet(confirmed_path)
    flagged_df.to_parquet(flagged_path)
    log.info(
        "Hard negatives for %s: %d confirmed, %d flagged as possible unmapped installs "
        "(now>=%.2f, %s<%.2f), %d ambiguous (signal at both dates, excluded), "
        "%d skipped (no %s data) -> %s",
        aoi, len(confirmed_df), len(flagged_df), neg_prob_threshold, compare_year,
        neg_prob_threshold, ambiguous_ct, no_old_data_ct, compare_year, confirmed_path,
    )
    return confirmed_path
