"""Sentinel-2 L2A seasonal median composites from Microsoft Planetary Computer.

Produces, for any bbox, per-season cloud-masked median composites of the 12
TerraMind S2L2A bands at 10 m, plus an annual median (median over seasons).
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import odc.stac
import planetary_computer
import pystac_client
import xarray as xr

from earthpv.config import S2_BANDS, SEASONS

log = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
# SCL classes to keep: 4 vegetation, 5 bare, 6 water, 7 unclassified, 11 snow(excl)
_SCL_VALID = (4, 5, 6, 7)
MAX_CLOUD = 60  # scene-level filter; per-pixel SCL masking below


@lru_cache(maxsize=1)
def _catalog() -> pystac_client.Client:
    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


def _season_median(
    bbox: tuple[float, float, float, float], date_range: tuple[str, str]
) -> xr.Dataset | None:
    search = _catalog().search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{date_range[0]}/{date_range[1]}",
        query={"eo:cloud_cover": {"lt": MAX_CLOUD}},
    )
    items = list(search.items())
    if not items:
        return None
    ds = odc.stac.load(
        items,
        bands=[*S2_BANDS, "SCL"],
        bbox=bbox,
        resolution=10,
        groupby="solar_day",
        chunks={"x": 512, "y": 512},
        fail_on_error=False,
    )
    valid = ds["SCL"].isin(_SCL_VALID)
    masked = ds[S2_BANDS].where(valid)
    return masked.median(dim="time", skipna=True)


def seasonal_composites(
    bbox: tuple[float, float, float, float],
    seasons: dict[str, tuple[str, str]] | None = None,
) -> xr.Dataset:
    """Return Dataset with dims (season, y, x) and one variable per band, uint16 DN.

    Seasons with no cloud-free data are filled from the annual median.
    """
    seasons = seasons or SEASONS
    per_season = {}
    for name, dates in seasons.items():
        comp = _season_median(bbox, tuple(dates))
        if comp is not None:
            per_season[name] = comp.compute()
        log.debug("season %s: %s", name, "ok" if comp is not None else "no data")
    if not per_season:
        raise RuntimeError(f"No Sentinel-2 data for bbox={bbox}")

    stack = xr.concat(list(per_season.values()), dim="season")
    stack = stack.assign_coords(season=list(per_season))
    annual = stack.median(dim="season", skipna=True)

    # Fill gaps (clouds all season / missing season) with annual values
    full = []
    for name in seasons:
        s = stack.sel(season=name) if name in per_season else annual
        full.append(s.fillna(annual))
    out = xr.concat(full, dim="season").assign_coords(season=list(seasons))
    out = xr.concat([out, annual.expand_dims(season=["annual"])], dim="season")
    # Residual NaNs (no data at all for a pixel) -> 0
    return out.fillna(0).astype("uint16")


_SEARCH_LOCK = __import__("threading").Lock()


def annual_composite(
    bbox: tuple[float, float, float, float],
    date_range: tuple[str, str] = ("2025-11-01", "2026-03-15"),
    max_cloud: int = 30,
    max_items: int = 12,
    geobox=None,
) -> tuple[np.ndarray, object, object] | None:
    """Cloud-masked median over the 10 local bands (B02..B12), 10 m.

    Uses the ~`max_items` least-cloudy scenes in `date_range` (default: Punjab dry
    season) to bound the download while keeping a clean median. Returns
    (array[10,H,W] uint16, transform, crs) in the bbox's UTM zone, or None if no
    usable scenes. Mirrors the rooftopsenti composite layout for downstream reuse.

    `geobox` (odc.geo GeoBox) pins the output to an exact existing grid so a
    contrast-season composite aligns pixel-perfectly with a base window; the STAC
    search still uses `bbox`. The catalog search is serialized (pystac-client is
    not thread-safe); the COG reads run concurrently fine.
    """
    from rasterio.crs import CRS

    bands = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
    with _SEARCH_LOCK:
        search = _catalog().search(
            collections=["sentinel-2-l2a"], bbox=bbox,
            datetime=f"{date_range[0]}/{date_range[1]}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
        )
        items = sorted(search.items(), key=lambda it: it.properties.get("eo:cloud_cover", 100))
    if not items:
        return None
    items = items[:max_items]
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
    grid = dict(geobox=geobox) if geobox is not None else dict(
        bbox=bbox, resolution=10, crs=CRS.from_epsg(epsg)
    )
    ds = odc.stac.load(
        items, bands=[*bands, "SCL"], groupby="solar_day",
        chunks={"x": 2048, "y": 2048}, fail_on_error=False, **grid,
    )
    valid = ds["SCL"].isin(_SCL_VALID)
    masked = ds[bands].where(valid)
    med = masked.median(dim="time", skipna=True).fillna(0).astype("uint16").compute()
    arr = np.stack([med[b].values for b in bands], axis=0)
    transform = med.odc.transform if hasattr(med, "odc") else med.rio.transform()
    crs = geobox.crs if geobox is not None else CRS.from_epsg(epsg)
    return arr, transform, crs


def to_chip_array(ds: xr.Dataset, seasons: list[str]) -> np.ndarray:
    """(bands*len(seasons), y, x) uint16 array in S2_BANDS order per season."""
    arrs = [
        np.stack([ds[b].sel(season=s).values for b in S2_BANDS], axis=0) for s in seasons
    ]
    return np.concatenate(arrs, axis=0)
