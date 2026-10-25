"""ESA WorldCover land-cover false-positive check for the leads product.

Unlike `sar.py`/`sppi.py` (spectral proxies computed from scratch, then calibrated on
whatever ground truth happens to be on hand), this checks candidates against an
existing, independently-trained global land-cover classifier -- ESA WorldCover v200
(2021, 10 m, exactly the Sentinel-2 grid), served free of charge via Planetary
Computer STAC (no login; this project already talks to PC elsewhere, see `imagery.py`).
It directly targets the two false-positive classes actually seen in this project
(dry riverbed/salt flat/bare rock, and water) rather than hoping a spectral ratio
correlates with them.

Spot-checked 2026-08-02 against three of the false positives flagged by hand this
session: `pakistan-pv-004962` (the Balochistan salt-flat FP) reads 100% WorldCover
class 60 (bare/sparse vegetation); `pakistan-pv-003319` (the S1-bright
Gilgit-Baltistan/mountain FP) reads 85% class 60; the broken-composite river cluster
at (31.245, 72.379) reads 100% class 40 (cropland) -- WorldCover correctly does NOT
call that one bare or water, consistent with its false positives being caused by the
corrupted composite bands, not a land-cover confusion this check could ever have fixed.

**Caveat this module cannot avoid: some real PV is legitimately built on bare ground.**
Ground-mount arrays are frequently sited on bare/marginal land on purpose (that is
part of why it is cheap land to build on) -- this is the same "arid ground" failure
mode SPPI already documents, from the opposite direction (SPPI over-predicts there;
this filter, applied without discretion, would strip real ground-mount PV that
happens to also sit on bare land). Measured cost is in `DEFAULT_VETO_CLASSES`'s
docstring below, and in `ensemble.py`, which weighs this against SPPI and S1 rather
than trusting it alone.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features as rfeat
import rasterio.transform
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

log = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "esa-worldcover"

# ESA WorldCover v200 (2021) class codes.
TREE_COVER = 10
SHRUBLAND = 20
GRASSLAND = 30
CROPLAND = 40
BUILT_UP = 50
BARE = 60
SNOW_ICE = 70
WATER = 80
WETLAND = 90
MANGROVES = 95
MOSS_LICHEN = 100

# Measured 2026-08-02 on the same country-scale populations as sar.py/sppi.py (2,426
# OSM-confirmed real PV vs. 701 confirmed FP -- vegetation-cycle-refuted + epoch-
# persistent): flagging BARE (class 60; SNOW_ICE/WATER never actually fire in either
# population, both are rare here) costs 15.8% of real PV but catches only 4.0% of
# that FP population -- WorldCover is NOT a good filter for vegetation/epoch-type
# false positives, which correctly read as CROPLAND (490/701) or other non-bare
# classes, not bare ground. It is a genuinely strong filter for the OTHER failure
# class this project has: on the 21 false positives flagged by hand in Balochistan
# desert / Gilgit-Baltistan mountains, it catches 16/21 (76%) -- far ahead of SPPI
# (19% at its own low-cost default) and S1 (0%) on that exact set. Real PV's 15.8%
# cost is concentrated in ground-mount arrays legitimately sited on bare land (see
# the module docstring's caveat) -- this is a real, structural cost, not noise to
# tune away, which is why `ensemble.py` requires agreement with another instrument
# rather than trusting this alone.
DEFAULT_VETO_CLASSES = (BARE, SNOW_ICE, WATER)


def _tile_index(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """WorldCover tiles (3x3 deg) covering `bbox`, preferring the 2021 v200 release."""
    import planetary_computer
    import pystac_client
    from shapely.geometry import box

    cat = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=[COLLECTION], bbox=bbox).items())
    if not items:
        raise FileNotFoundError(f"No {COLLECTION} tiles found for bbox {bbox}")
    v200 = [it for it in items if "v200" in it.id]
    items = v200 or items
    rows = [{"path": it.assets["map"].href, "geometry": box(*it.bbox)} for it in items]
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def candidate_worldcover_class(geoms: gpd.GeoSeries) -> np.ndarray:
    """Majority WorldCover class per candidate footprint (mode over touched pixels).

    NaN where no tile covers the point -- the caller must treat NaN as "unchecked",
    never as a veto (same contract as `vegetation.composite_max_ndvi`/`sppi.candidate_sppi`).
    """
    geoms = geoms.reset_index(drop=True)
    idx = _tile_index(tuple(geoms.total_bounds))
    reps = gpd.GeoDataFrame(geometry=geoms.representative_point(), crs=geoms.crs)
    hits = gpd.sjoin(reps, idx[["path", "geometry"]], predicate="within", how="left")
    hits = hits[~hits.index.duplicated(keep="first")]

    out = np.full(len(geoms), np.nan)
    for tif_path, rows in hits.dropna(subset=["path"]).groupby("path").groups.items():
        rows = list(rows)
        with rasterio.open(tif_path) as src:
            gg = geoms.iloc[rows].to_crs(src.crs)
            for pos, geom in zip(rows, gg):
                if geom.geom_type == "Point" or geom.area == 0:
                    rr, cc = rasterio.transform.rowcol(src.transform, geom.x, geom.y)
                    if not (0 <= rr < src.height and 0 <= cc < src.width):
                        continue
                    out[pos] = float(src.read(1, window=Window(cc, rr, 1, 1))[0, 0])
                    continue
                try:
                    win = from_bounds(*geom.bounds, transform=src.transform)
                    win = win.round_offsets().round_lengths().intersection(
                        Window(0, 0, src.width, src.height)
                    )
                except rasterio.errors.WindowError:
                    continue
                if win.width < 1 or win.height < 1:
                    continue
                arr = src.read(1, window=win)
                transform = window_transform(win, src.transform)
                mask = rfeat.geometry_mask(
                    [geom], out_shape=arr.shape, transform=transform,
                    invert=True, all_touched=True,
                )
                if not mask.any():
                    continue
                vals, counts = np.unique(arr[mask], return_counts=True)
                out[pos] = float(vals[np.argmax(counts)])
    return out


def candidate_worldcover_veto(
    geoms: gpd.GeoSeries, veto_classes: tuple[int, ...] = DEFAULT_VETO_CLASSES,
) -> tuple[np.ndarray, np.ndarray]:
    """`(wc_class, is_veto)` -- `is_veto` is False (never True) where `wc_class` is NaN."""
    wc = candidate_worldcover_class(geoms)
    veto = np.isin(wc, veto_classes) & np.isfinite(wc)
    return wc, veto


# --------------------------------------------------------------------------------------
# Cropland: where farm ground PV lives (`groundclf`, farm calibration candidates)
# --------------------------------------------------------------------------------------
# Read resolution for the cell/window statistics. WorldCover's COGs carry overviews, so a
# 100 m read of a 3x3 deg tile is one 3,600 px square from the overview, not 36,000.
CROPLAND_READ_M = 100.0


def _decimated(src, bounds, res_m: float):
    """`(array, transform)` of `src` over 4326 `bounds`, read at roughly `res_m`; None when
    the bounds cover less than one source pixel (a tile edge meeting a bbox edge)."""
    dec = max(1, int(round(res_m / 10.0)))
    win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
    if win.width < 1 or win.height < 1:
        return None
    try:
        win = win.intersection(Window(0, 0, src.width, src.height))
    except rasterio.errors.WindowError:
        return None
    h, w = max(1, int(win.height) // dec), max(1, int(win.width) // dec)
    arr = src.read(1, window=win, out_shape=(h, w))
    t = window_transform(win, src.transform)
    return arr, t * t.scale(win.width / w, win.height / h)


def cell_cropland(cells, cell_deg: float = 0.1, res_m: float = CROPLAND_READ_M):
    """Cropland share of every 0.1 deg cell in `cells` (columns `cell`, `lon0`, `lat0`).

    Returns `cell`, `crop_frac` (class 40 over all classified pixels, so sea and nodata
    do not dilute it) and `crop_km2` (that share of the cell's area). One read per
    WorldCover tile, so a country costs a dozen tile reads, not one per cell.
    """
    import pandas as pd

    lon0, lat0 = cells["lon0"].to_numpy(float), cells["lat0"].to_numpy(float)
    gx, gy = float(lon0.min()), float(lat0.min())
    key = {(int(round((x - gx) / cell_deg)), int(round((y - gy) / cell_deg))): c
           for c, x, y in zip(cells["cell"], lon0, lat0)}
    crop, total = {}, {}
    bbox = (lon0.min(), lat0.min(), lon0.max() + cell_deg, lat0.max() + cell_deg)
    for path in _tile_index(bbox).path:
        with rasterio.open(path) as src:
            tb = src.bounds
            ib = (max(tb.left, bbox[0]), max(tb.bottom, bbox[1]), min(tb.right, bbox[2]), min(tb.top, bbox[3]))
            if ib[0] >= ib[2] or ib[1] >= ib[3]:
                continue
            got = _decimated(src, ib, res_m)
        if got is None:
            continue
        arr, t = got
        rows, cols = np.indices(arr.shape)
        lon = t.c + (cols + 0.5) * t.a
        lat = t.f + (rows + 0.5) * t.e
        ix = np.floor((lon - gx) / cell_deg).astype(int)
        iy = np.floor((lat - gy) / cell_deg).astype(int)
        k = ix.astype(np.int64) * 100_000 + iy
        valid = arr > 0
        for kk, n in zip(*np.unique(k[valid], return_counts=True)):
            total[kk] = total.get(kk, 0) + int(n)
        for kk, n in zip(*np.unique(k[arr == CROPLAND], return_counts=True)):
            crop[kk] = crop.get(kk, 0) + int(n)
    out = []
    for (ix, iy), c in key.items():
        kk = ix * 100_000 + iy
        frac = crop.get(kk, 0) / total[kk] if total.get(kk) else 0.0
        lat_c = gy + (iy + 0.5) * cell_deg
        area_km2 = (cell_deg * 111.32) ** 2 * np.cos(np.radians(lat_c))
        out.append({"cell": c, "crop_frac": frac, "crop_km2": frac * area_km2})
    return pd.DataFrame(out)


def landcover_points(bbox: tuple[float, float, float, float], res_m: float = CROPLAND_READ_M):
    """`(lon, lat, is_cropland)` for every classified pixel centre in `bbox`, read at
    `res_m`. Every classified pixel, not only cropland, so a window's cropland SHARE can
    be counted without sea or nodata diluting it."""
    lons, lats, crop = [], [], []
    for path in _tile_index(bbox).path:
        with rasterio.open(path) as src:
            tb = src.bounds
            ib = (max(tb.left, bbox[0]), max(tb.bottom, bbox[1]), min(tb.right, bbox[2]), min(tb.top, bbox[3]))
            if ib[0] >= ib[2] or ib[1] >= ib[3]:
                continue
            got = _decimated(src, ib, res_m)
        if got is None:
            continue
        arr, t = got
        rows, cols = np.nonzero(arr > 0)
        lons.append(t.c + (cols + 0.5) * t.a)
        lats.append(t.f + (rows + 0.5) * t.e)
        crop.append(arr[rows, cols] == CROPLAND)
    if not lons:
        return np.array([]), np.array([]), np.array([], dtype=bool)
    return np.concatenate(lons), np.concatenate(lats), np.concatenate(crop)


def cropland_mask(bbox4326, dst_shape, dst_transform, dst_crs) -> np.ndarray | None:
    """WorldCover cropland (class 40) resampled nearest onto a composite window's grid;
    None when no tile covers it or the service cannot be reached (callers degrade to
    their other ROI anchors rather than fail a national run on one network error)."""
    from rasterio.warp import Resampling, reproject

    try:
        tiles = _tile_index(bbox4326)
    except Exception as e:  # noqa: BLE001 -- network / STAC; reported, never fatal
        log.warning("WorldCover unavailable for %s: %s", bbox4326, e)
        return None
    out = np.zeros(dst_shape, dtype="uint8")
    for path in tiles.path:
        try:
            with rasterio.open(path) as src:
                tmp = np.zeros(dst_shape, dtype="uint8")
                reproject(rasterio.band(src, 1), tmp, dst_transform=dst_transform, dst_crs=dst_crs,
                          resampling=Resampling.nearest)
        except Exception as e:  # noqa: BLE001
            log.warning("WorldCover tile read failed (%s): %s", path, e)
            return None
        out = np.where(out == 0, tmp, out)
    return out == CROPLAND
