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
    labels: gpd.GeoDataFrame, coverage, rng: np.random.Generator, limit: int
) -> pd.DataFrame:
    """Positives from PV polygons + matched near-negatives + random background,
    all constrained to the composite coverage polygon. Only arrays >= MIN_PV_AREA
    seed positive chips so training centres on the target large installations."""
    pos_polys = labels[
        labels.placement.isin(["rooftop", "ground"]) & (labels.area_m2 >= MIN_PV_AREA)
    ]
    # Jitter each positive chip so the installation lands at a RANDOM position in the
    # frame, not the centre. Without this the model learns a centre bias and, at
    # sliding-window inference, fires once per window -> a regular grid of false
    # positives at the stride spacing. Jitter up to ~±half a chip (chip = 2.24 km).
    jit_deg = 900.0 / 111320.0  # ~±900 m
    rows = []
    for _, r in pos_polys.iterrows():
        c = r.geometry.centroid
        jx = rng.uniform(-jit_deg, jit_deg) / np.cos(np.radians(c.y))
        jy = rng.uniform(-jit_deg, jit_deg)
        rows.append((c.x + jx, c.y + jy, "positive", r.placement))
    pos = pd.DataFrame(rows, columns=["lon", "lat", "kind", "placement"])
    # Dedupe positives sharing a ~2 km cell to avoid near-identical chips
    cell = (pos.lon / 0.02).round().astype(int).astype(str) + "_" + (
        pos.lat / 0.02
    ).round().astype(int).astype(str)
    pos = pos.loc[~cell.duplicated()].reset_index(drop=True)
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


def _write_tif(path: Path, arr: np.ndarray, transform, crs, dtype: str) -> None:
    arr = arr if arr.ndim == 3 else arr[None]
    with rasterio.open(
        path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
        dtype=dtype, crs=crs, transform=transform, compress="deflate", predictor=2,
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


def build_chips(
    aoi: str, labels_dir: Path, out_dir: Path, limit: int = 0, seasonal: bool = False
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    out_dir = Path(out_dir) / aoi
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "masks").mkdir(parents=True, exist_ok=True)

    source_region = cfg.get("source_region")
    if not source_region:
        raise NotImplementedError(
            f"AOI '{aoi}' has no source_region; the STAC chip backend is not wired for "
            "training. Add local composites under local_root or use the STAC path."
        )
    region_dir = Path(settings.raw["local_root"]) / source_region
    # Two-season stack: chips get [base 10 bands, contrast-window 10 bands]. When the
    # AOI's composed cells already carry composite_1 the stack is read locally;
    # otherwise (germany: single-layer rooftopsenti COGs) the contrast season is
    # fetched per chip from STAC on the base window's exact grid.
    stack_window = tuple(cfg["stack_window"]) if cfg.get("stack_window") else None
    # Imagery: prefer composites built by the `compose` stage for this AOI (mirrors
    # infer.py) — e.g. punjab trains on its composed cells with pakistan_500 labels.
    composed = Path("data/composites") / aoi
    fetch_contrast = False
    if composed.exists() and any(composed.glob("composites/*/composite_0.tif")):
        comp_idx = CompositeIndex(composed, layers=2 if stack_window else 1)
    else:
        comp_idx = CompositeIndex(region_dir)
        fetch_contrast = stack_window is not None
    coverage = comp_idx.coverage
    labels = load_solar_labels(region_dir)
    labels = labels[labels.geometry.centroid.within(coverage)].reset_index(drop=True)
    log.info(
        "AOI %s: %d composite tiles, %d labels in coverage (%s)",
        aoi, len(comp_idx.index), len(labels),
        labels.placement.value_counts().to_dict(),
    )

    rng = np.random.default_rng(42)
    centers = sample_chip_centers(labels, coverage, rng, limit)
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
                mask = _burn_mask(win_labels, transform, crs, arr.shape[-2:])
                _write_tif(img_path, arr, transform, crs, "uint16")
                _write_tif(mask_path, mask.astype("int16"), transform, crs, "int16")
        except Exception as e:  # noqa: BLE001 — one bad chip must not kill the run
            log.warning("chip %s failed: %s", cid, e)
            return None
        with rasterio.open(mask_path) as m:
            band = m.read(1)
        split = "val" if tile in val_tiles else "train"
        return dict(chip_id=cid, lon=row.lon, lat=row.lat, kind=row.kind, tile=tile,
                    split=split, pv_pixels=int((band == 1).sum()),
                    image=str(img_path), mask=str(mask_path))

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
