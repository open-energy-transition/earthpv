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
