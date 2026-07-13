"""Sample training chips: Sentinel-2 composites + rasterized PV masks.

Primary backend reads the Sentinel-2 composite COGs already produced by the
sibling `rooftopsenti` project (config `local_root` + AOI `source_region`); the
Planetary-Computer STAC compositor is the fallback for regions without local
artifacts.

Chip mix: PV-centered positives, near-positive negatives (same urban context,
no PV), and random background. Masks: 1 = PV (rooftop or ground, >= min area),
0 = background, -1 = ignore (small sub-threshold arrays, so the loss neither
rewards nor penalises them).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from tqdm import tqdm

from earthpv.config import CHIP_SIZE, MODEL_BANDS, Settings
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.local_source import CompositeIndex, load_solar_labels

log = logging.getLogger(__name__)

CHIP_M = CHIP_SIZE * 10.0  # chip edge in metres
# Arrays >= this are trained as positives; smaller ones are burned as ignore (no
# positive or negative gradient). 400 m2 is ~4 Sentinel-2 pixels — the practical
# floor for per-pixel supervision at 10 m GSD; it also matches the rooftop/ground
# vs "small" split in local_source.load_solar_labels.
MIN_PV_AREA = 400.0


def _chip_id(lon: float, lat: float) -> str:
    return hashlib.sha1(f"{lon:.5f}_{lat:.5f}".encode()).hexdigest()[:12]


def _chip_bbox(lon: float, lat: float) -> tuple[float, float, float, float]:
    dy = CHIP_M / 2 / 111320.0
    dx = CHIP_M / 2 / (111320.0 * np.cos(np.radians(lat)))
    return (lon - dx, lat - dy, lon + dx, lat + dy)


def sample_chip_centers(
    labels: gpd.GeoDataFrame, coverage, rng: np.random.Generator, limit: int,
    min_seed_area: float = MIN_PV_AREA, max_positives: int = 0,
    region_filter: gpd.GeoDataFrame | None = None,
) -> pd.DataFrame:
    """Positives from PV polygons + matched near-negatives + random background,
    all constrained to the composite coverage polygon. Only arrays >= min_seed_area
    seed positive chips; the binary task keeps this at MIN_PV_AREA so training centres
    on the target large installations, while the fraction-regression task passes 0 to
    also seed from small (sub-pixel) arrays.

    `region_filter`, if given, restricts ALL centres (positive, near-negative,
    background) to its union polygon. This matters most for fraction regression: a
    background/near-negative chip centred where OSM PV mapping is incomplete would
    carry a false 0 target on any unmapped roof, which corrupts the aggregate signal
    the regression task depends on."""
    if region_filter is not None and not region_filter.empty:
        union = region_filter.union_all()
        labels = labels[labels.geometry.centroid.within(union)]
        coverage = coverage.intersection(union)

    # min_seed_area <= 0 means the fraction-regression task (called with 0.0 from
    # build_chips), which also wants "small" (sub-MIN_PV_AREA) arrays as positive seeds —
    # they're exactly the sub-pixel signal the regression task is meant to pick up.
    seed_placements = ["rooftop", "ground", "small"] if min_seed_area <= 0 else \
        ["rooftop", "ground"]
    pos_polys = labels[
        labels.placement.isin(seed_placements) & (labels.area_m2 >= min_seed_area)
    ]
    # Jitter each positive chip so the installation lands at a RANDOM position in the
    # frame, not the centre. Without this the model learns a centre bias and, at
    # sliding-window inference, fires once per window -> a regular grid of false
    # positives at the stride spacing. Jitter up to ~±half a chip (chip = 2.24 km).
    jit_deg = 900.0 / 111320.0  # ~±900 m
    centroids = pos_polys.geometry.centroid
    cx, cy = centroids.x.to_numpy(), centroids.y.to_numpy()
    jx = rng.uniform(-jit_deg, jit_deg, len(cx)) / np.cos(np.radians(cy))
    jy = rng.uniform(-jit_deg, jit_deg, len(cy))
    pos = pd.DataFrame(
        {"lon": cx + jx, "lat": cy + jy, "kind": "positive",
         "placement": pos_polys.placement.to_numpy()}
    )
    # Shuffle before the dedupe below so which chip survives a shared cell is
    # unbiased, then dedupe positives sharing a ~2 km cell to avoid near-identical chips.
    pos = pos.iloc[rng.permutation(len(pos))].reset_index(drop=True)
    cell = (pos.lon / 0.02).round().astype(int).astype(str) + "_" + (
        pos.lat / 0.02
    ).round().astype(int).astype(str)
    pos = pos.loc[~cell.duplicated()].reset_index(drop=True)
    if max_positives and len(pos) > max_positives:
        pos = pos.sample(n=max_positives, random_state=42).reset_index(drop=True)
    n_pos = len(pos)

    near = pos.sample(n=max(n_pos // 2, 1), random_state=1, replace=n_pos < 2).copy()
    near["lon"] = near.lon + rng.uniform(0.03, 0.06, len(near)) * rng.choice([-1, 1], len(near))
    near["lat"] = near.lat + rng.uniform(0.02, 0.04, len(near)) * rng.choice([-1, 1], len(near))
    near["kind"] = "near_negative"

    minx, miny, maxx, maxy = coverage.bounds
    m = max(n_pos, 1)
    rand = pd.DataFrame(
        {
            "lon": rng.uniform(minx, maxx, m),
            "lat": rng.uniform(miny, maxy, m),
            "kind": "background",
            "placement": None,
        }
    )
    out = pd.concat([pos, near, rand], ignore_index=True)
    # `coverage` is already intersected with region_filter's union above, so this single
    # check enforces both the composite-coverage and (if given) region-filter constraints.
    inside = gpd.GeoSeries(gpd.points_from_xy(out.lon, out.lat), crs="EPSG:4326").within(coverage)
    out = out[inside.values].reset_index(drop=True)
    if limit and len(out) > limit:
        # Preserve the mix: half positives, quarter each of near/background
        keep = pd.concat(
            [
                out[out.kind == "positive"].head(max(limit // 2, 1)),
                out[out.kind == "near_negative"].head(max(limit // 4, 1)),
                out[out.kind == "background"].head(max(limit // 4, 1)),
            ]
        )
        out = keep.head(limit).reset_index(drop=True)
    return out


def _burn_mask(labels: gpd.GeoDataFrame, transform, crs, shape) -> np.ndarray:
    """Rasterize PV polygons onto a window grid. Big arrays -> 1, small -> -1 (ignore)."""
    mask = np.zeros(shape, dtype="int16")
    lab_utm = labels.to_crs(crs)
    big = [
        (g, 1) for g, a in zip(lab_utm.geometry, labels.area_m2)
        if not g.is_empty and a >= MIN_PV_AREA and g.geom_type in ("Polygon", "MultiPolygon")
    ]
    small = [
        (g, 1) for g, a, p in zip(lab_utm.geometry, labels.area_m2, labels.placement)
        if not g.is_empty and a < MIN_PV_AREA and p in ("rooftop", "ground", "small")
        and g.geom_type in ("Polygon", "MultiPolygon")
    ]
    if small:
        ign = rio_features.rasterize(
            small, out_shape=shape, transform=transform, fill=0, all_touched=True, dtype="uint8"
        )
        mask[ign == 1] = -1
    if big:
        pv = rio_features.rasterize(
            big, out_shape=shape, transform=transform, fill=0, all_touched=True, dtype="uint8"
        )
        mask[pv == 1] = 1
    return mask


def _burn_fraction(labels: gpd.GeoDataFrame, transform, crs, shape, factor: int = 10) -> np.ndarray:
    """Sub-pixel PV coverage fraction per 10 m pixel: rasterize ALL placements (including
    sub-MIN_PV_AREA "small" arrays — the whole point of the regression task) at `factor`x
    resolution (~1 m with the default), then block-mean back down to the native grid.
    `all_touched=False` at the hi-res grid keeps the area estimate honest — `all_touched=True`
    would inflate every polygon by a partial-pixel halo at 1 m too."""
    lab_utm = labels.to_crs(crs)
    polys = [
        (g, 1) for g, p in zip(lab_utm.geometry, labels.placement)
        if not g.is_empty and p in ("rooftop", "ground", "small")
        and g.geom_type in ("Polygon", "MultiPolygon")
    ]
    hi_shape = (shape[0] * factor, shape[1] * factor)
    hi_transform = transform * rasterio.Affine.scale(1.0 / factor)
    if not polys:
        return np.zeros(shape, dtype="float32")
    hi = rio_features.rasterize(
        polys, out_shape=hi_shape, transform=hi_transform, fill=0, all_touched=False,
        dtype="uint8",
    )
    frac = hi.reshape(shape[0], factor, shape[1], factor).mean(axis=(1, 3))
    return frac.astype("float32")


def _write_tif(path: Path, arr: np.ndarray, transform, crs, dtype: str) -> None:
    arr = arr if arr.ndim == 3 else arr[None]
    predictor = 3 if dtype.startswith("float") else 2
    with rasterio.open(
        path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
        dtype=dtype, crs=crs, transform=transform, compress="deflate", predictor=predictor,
    ) as dst:
        dst.write(arr)


def _crop(arr: np.ndarray, size: int) -> tuple[np.ndarray, int, int]:
    """Center crop/pad trailing (y, x) dims to exactly (size, size).

    Returns (cropped, ox, oy): the column/row offset removed from the top-left,
    needed to keep the geotransform aligned with the cropped grid.
    """
    y, x = arr.shape[-2], arr.shape[-1]
    oy, ox = max((y - size) // 2, 0), max((x - size) // 2, 0)
    arr = arr[..., oy : oy + size, ox : ox + size]
    if arr.shape[-2] < size or arr.shape[-1] < size:
        pad = [(0, 0)] * (arr.ndim - 2) + [
            (0, size - arr.shape[-2]), (0, size - arr.shape[-1])
        ]
        arr = np.pad(arr, pad)
    return arr, ox, oy


def _tile_of(lon: float, lat: float, comp_idx: CompositeIndex) -> str | None:
    from shapely.geometry import Point

    hit = comp_idx.index[comp_idx.index.contains(Point(lon, lat))]
    if hit.empty:
        return None
    return Path(hit.iloc[0].path).parent.name


def _overpass_labels(path: Path, min_area_m2: float = 400.0) -> gpd.GeoDataFrame:
    """Normalize an Overpass-fetched solar parquet (overpass.build_overpass_labels)
    to the schema load_solar_labels returns, so AOIs without a rooftopsenti dataset
    (e.g. India) can train from live OSM: polygons >= min_area keep their classified
    rooftop/ground placement (unknown -> ground, mirroring rooftopsenti's "large
    off-building = ground-mount" rule); smaller ones become the "small" ignore class."""
    labels = gpd.read_parquet(path)
    labels = labels[labels.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    labels = labels.rename(columns={"id": "osm_id"})
    big = labels.area_m2 >= min_area_m2
    labels.loc[big & (labels.placement == "unknown"), "placement"] = "ground"
    labels.loc[~big, "placement"] = "small"
    return labels[["osm_id", "placement", "area_m2", "geometry"]].reset_index(drop=True)


def build_chips(
    aoi: str, labels_dir: Path, out_dir: Path, limit: int = 0, seasonal: bool = False,
    fraction: bool = False, max_positives: int = 0, region_filter: Path | None = None,
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    # Fraction chips live in a parallel tree so the binary-segmentation chips are untouched.
    out_dir = Path(out_dir) / (f"{aoi}_fraction" if fraction else aoi)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "masks").mkdir(parents=True, exist_ok=True)
    region_gdf = gpd.read_parquet(region_filter) if region_filter else None

    source_region = cfg.get("source_region")
    composed = Path("data/composites") / aoi
    overpass_path = Path(labels_dir) / f"{aoi}_overpass_solar.parquet"
    if not source_region and not (
        composed.exists() and any(composed.glob("composites/*/composite_0.tif"))
        and overpass_path.exists()
    ):
        raise NotImplementedError(
            f"AOI '{aoi}' has no source_region; training needs composed imagery under "
            f"{composed} (run `compose`) plus Overpass labels at {overpass_path} "
            "(run `overpass-labels`)."
        )
    # Two-season stack: chips get [base 10 bands, contrast-window 10 bands]. When the
    # AOI's composed cells already carry composite_1 the stack is read locally;
    # otherwise (germany: single-layer rooftopsenti COGs) the contrast season is
    # fetched per chip from STAC on the base window's exact grid.
    stack_window = tuple(cfg["stack_window"]) if cfg.get("stack_window") else None
    # Imagery: prefer composites built by the `compose` stage for this AOI (mirrors
    # infer.py) — e.g. punjab trains on its composed cells with pakistan_500 labels.
    fetch_contrast = False
    if composed.exists() and any(composed.glob("composites/*/composite_0.tif")):
        comp_idx = CompositeIndex(composed, layers=2 if stack_window else 1)
    else:
        comp_idx = CompositeIndex(Path(settings.raw["local_root"]) / source_region)
        fetch_contrast = stack_window is not None
    coverage = comp_idx.coverage
    # Labels: rooftopsenti's curated set when the AOI has one; fresh Overpass OSM
    # otherwise (also used when a source_region exists but the AOI-named Overpass
    # file was fetched deliberately — the fresher source wins).
    if overpass_path.exists():
        labels = _overpass_labels(overpass_path)
        log.info("Using Overpass labels from %s", overpass_path)
    else:
        labels = load_solar_labels(Path(settings.raw["local_root"]) / source_region)
    labels = labels[labels.geometry.centroid.within(coverage)].reset_index(drop=True)
    log.info(
        "AOI %s: %d composite tiles, %d labels in coverage (%s)",
        aoi, len(comp_idx.index), len(labels),
        labels.placement.value_counts().to_dict(),
    )

    rng = np.random.default_rng(42)
    centers = sample_chip_centers(
        labels, coverage, rng, limit,
        min_seed_area=0.0 if fraction else MIN_PV_AREA,
        max_positives=max_positives, region_filter=region_gdf,
    )
    val_tiles = set(cfg.get("val_tiles", []))
    log.info(
        "Sampling %d chips (%s)%s", len(centers), centers.kind.value_counts().to_dict(),
        f", contrast window {stack_window} via {'STAC' if fetch_contrast else 'local layers'}"
        if stack_window else "",
    )

    n_bands = len(MODEL_BANDS) * (2 if stack_window else 1)

    def _build_one(row) -> dict | None:
        cid = _chip_id(row.lon, row.lat)
        img_path = out_dir / "images" / f"{cid}.tif"
        mask_path = out_dir / "masks" / f"{cid}.tif"
        tile = _tile_of(row.lon, row.lat, comp_idx)
        try:
            if not (img_path.exists() and mask_path.exists()):
                res = comp_idx.read_window(_chip_bbox(row.lon, row.lat))
                if res is None:
                    return None
                arr, transform, crs = res
                arr = arr[:n_bands if not fetch_contrast else len(MODEL_BANDS)]
                arr, ox, oy = _crop(arr, CHIP_SIZE)
                # Shift the geotransform to the cropped top-left so the mask aligns
                transform = transform * rasterio.Affine.translation(ox, oy)
                if fetch_contrast:
                    from odc.geo.geobox import GeoBox

                    from earthpv.imagery import annual_composite

                    gbox = GeoBox((CHIP_SIZE, CHIP_SIZE), transform, crs)
                    cres = annual_composite(
                        _chip_bbox(row.lon, row.lat), date_range=stack_window,
                        geobox=gbox, max_cloud=60,
                    )
                    contrast = (
                        cres[0] if cres is not None
                        else np.zeros_like(arr[: len(MODEL_BANDS)])
                    )
                    if cres is None:
                        log.warning("chip %s: no contrast-season scenes, zero-filled", cid)
                    arr = np.concatenate([arr, contrast.astype(arr.dtype)], axis=0)
                win_labels = labels[labels.geometry.intersects(_bbox_poly(row.lon, row.lat))]
                _write_tif(img_path, arr, transform, crs, "uint16")
                if fraction:
                    mask = _burn_fraction(win_labels, transform, crs, arr.shape[-2:])
                    _write_tif(mask_path, mask, transform, crs, "float32")
                else:
                    mask = _burn_mask(win_labels, transform, crs, arr.shape[-2:])
                    _write_tif(mask_path, mask.astype("int16"), transform, crs, "int16")
        except Exception as e:  # noqa: BLE001 — one bad chip must not kill the run
            log.warning("chip %s failed: %s", cid, e)
            return None
        with rasterio.open(mask_path) as m:
            band = m.read(1)
        split = "val" if tile in val_tiles else "train"
        pv_pixels = int((band > 0).sum()) if fraction else int((band == 1).sum())
        record = dict(chip_id=cid, lon=row.lon, lat=row.lat, kind=row.kind, tile=tile,
                      split=split, pv_pixels=pv_pixels, image=str(img_path), mask=str(mask_path))
        if fraction:
            record["pv_frac_sum"] = float(band.sum())
        return record

    rows = [row for _, row in centers.iterrows()]
    records = []
    if fetch_contrast:
        # STAC-bound: overlap the network waits. Searches are serialized inside
        # annual_composite; the COG reads parallelize.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=4) as ex:
            for rec in tqdm(ex.map(_build_one, rows), total=len(rows), desc="chips"):
                if rec:
                    records.append(rec)
    else:
        for row in tqdm(rows, desc="chips"):
            rec = _build_one(row)
            if rec:
                records.append(rec)

    index = pd.DataFrame(records)
    index_path = out_dir / "index.parquet"
    index.to_parquet(index_path)
    log.info(
        "Wrote %d chips (%d with PV, %d val) -> %s",
        len(index), int((index.pv_pixels > 0).sum()) if len(index) else 0,
        int((index.split == "val").sum()) if len(index) else 0, index_path,
    )
    return index_path


def _bbox_poly(lon: float, lat: float):
    from shapely.geometry import box

    return box(*_chip_bbox(lon, lat))


def build_hard_negative_chips(
    aoi: str, centers_path: Path, labels_dir: Path, out_dir: Path
) -> Path:
    """Cut real chips at hard_negatives.py's confirmed centers, into a chip set
    parallel to the AOI's normal one (e.g. `<aoi>_hard_neg/`) so it can be added to
    `scripts/merge_chip_index.py`'s AOI list independently.

    Images always come from the AOI's current composites (matching every other chip);
    the older-year comparison used to confirm these as negatives is a filtering-only
    artifact and never enters the training image itself. The mask is still burned from
    the real label set as a safety net against staleness between when hard_negatives.py
    ran its OSM-exclusion query and when this cuts chips (should be all-zero throughout)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    out_dir = Path(out_dir) / f"{aoi}_hard_neg"
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "masks").mkdir(parents=True, exist_ok=True)

    source_region = cfg.get("source_region")
    composed = Path("data/composites") / aoi
    overpass_path = Path(labels_dir) / f"{aoi}_overpass_solar.parquet"
    if composed.exists() and any(composed.glob("composites/*/composite_0.tif")):
        comp_idx = CompositeIndex(composed)
    else:
        comp_idx = CompositeIndex(Path(settings.raw["local_root"]) / source_region)
    if overpass_path.exists():
        labels = _overpass_labels(overpass_path)
    else:
        labels = load_solar_labels(Path(settings.raw["local_root"]) / source_region)

    centers = pd.read_parquet(centers_path)
    val_tiles = set(cfg.get("val_tiles", []))
    log.info("Cutting %d hard-negative chips for %s", len(centers), aoi)

    def _build_one(row) -> dict | None:
        cid = _chip_id(row.lon, row.lat)
        img_path = out_dir / "images" / f"{cid}.tif"
        mask_path = out_dir / "masks" / f"{cid}.tif"
        tile = _tile_of(row.lon, row.lat, comp_idx)
        try:
            if not (img_path.exists() and mask_path.exists()):
                res = comp_idx.read_window(_chip_bbox(row.lon, row.lat))
                if res is None:
                    return None
                arr, transform, crs = res
                arr = arr[: len(MODEL_BANDS)]
                arr, ox, oy = _crop(arr, CHIP_SIZE)
                transform = transform * rasterio.Affine.translation(ox, oy)
                win_labels = labels[labels.geometry.intersects(_bbox_poly(row.lon, row.lat))]
                _write_tif(img_path, arr, transform, crs, "uint16")
                mask = _burn_mask(win_labels, transform, crs, arr.shape[-2:])
                _write_tif(mask_path, mask.astype("int16"), transform, crs, "int16")
        except Exception as e:  # noqa: BLE001 — one bad chip must not kill the run
            log.warning("chip %s failed: %s", cid, e)
            return None
        with rasterio.open(mask_path) as m:
            band = m.read(1)
        split = "val" if tile in val_tiles else "train"
        return dict(
            chip_id=cid, lon=row.lon, lat=row.lat, kind="hard_negative", tile=tile,
            split=split, pv_pixels=int((band == 1).sum()), image=str(img_path), mask=str(mask_path),
        )

    records = []
    for _, row in tqdm(list(centers.iterrows()), desc="hard_neg_chips"):
        rec = _build_one(row)
        if rec:
            records.append(rec)

    index = pd.DataFrame(records)
    index_path = out_dir / "index.parquet"
    index.to_parquet(index_path)
    n_leaked = int((index.pv_pixels > 0).sum()) if len(index) else 0
    if n_leaked:
        log.warning(
            "%d/%d hard-negative chips actually rasterized PV pixels from the label set "
            "(stale exclusion vs. current labels) -- inspect before training on this set",
            n_leaked, len(index),
        )
    log.info("Wrote %d hard-negative chips (%d val) -> %s",
              len(index), int((index.split == "val").sum()) if len(index) else 0, index_path)
    return index_path
