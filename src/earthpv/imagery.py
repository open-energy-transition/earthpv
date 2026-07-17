"""Sentinel-2 L2A seasonal median composites from Microsoft Planetary Computer.

Produces, for any bbox, per-season cloud-masked median composites of the 12
TerraMind S2L2A bands at 10 m, plus an annual median (median over seasons).

`annual_composite` (the compose-stage entry point) falls back to Element84's
Earth Search catalog (AWS Open Data, same L2A scenes as COGs) when Planetary
Computer errors out — PC is ~4x faster from here (West Europe region) when
healthy, but has multi-hour 503 storms and SAS-token expiries under sustained
load; Earth Search needs no auth/tokens and lives in a different failure domain.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from functools import lru_cache

import numpy as np
import odc.stac
import planetary_computer
import pystac_client
import xarray as xr

from earthpv.config import S2_BANDS, SEASONS

log = logging.getLogger(__name__)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
ES_STAC_URL = "https://earth-search.aws.element84.com/v1"
# A healthy cell composites via PC in well under a minute; past this, treat PC as
# "struggling" (SAS-token/503 storms degrade individual band reads without raising,
# so a cell can silently take minutes instead of erroring outright) and hand the
# cell to Earth Search rather than keep waiting. The abandoned PC attempt is left to
# finish on its own in the background (vsicurl reads have no side effects to clean
# up); the pool is sized well above compose's typical worker count so a run of
# stragglers can't starve fresh cells of a PC attempt slot.
PC_TIMEOUT_S = 60
_PC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=24, thread_name_prefix="pc-attempt")
# SCL classes to keep: 4 vegetation, 5 bare, 6 water, 7 unclassified, 11 snow(excl)
_SCL_VALID = (4, 5, 6, 7)
MAX_CLOUD = 60  # scene-level filter; per-pixel SCL masking below

# Earth Search serves the same COG assets keyed by common band name; the rest of
# the pipeline (and the trained model's radiometry) speaks PC's B-names.
_ES_BAND_FOR = {
    "B02": "blue", "B03": "green", "B04": "red", "B05": "rededge1",
    "B06": "rededge2", "B07": "rededge3", "B08": "nir", "B8A": "nir08",
    "B11": "swir16", "B12": "swir22", "SCL": "scl",
}


@lru_cache(maxsize=1)
def _catalog() -> pystac_client.Client:
    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


@lru_cache(maxsize=1)
def _es_catalog() -> pystac_client.Client:
    return pystac_client.Client.open(ES_STAC_URL)


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


_SEARCH_LOCK = threading.Lock()


def _annual_composite_via(
    provider: str,
    bbox: tuple[float, float, float, float],
    date_range: tuple[str, str],
    max_cloud: int,
    max_items: int,
    geobox=None,
) -> tuple[np.ndarray, object, object] | None:
    """One provider attempt of annual_composite; `provider` is
    "planetary-computer" or "earth-search"."""
    from rasterio.crs import CRS

    bands = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
    es = provider == "earth-search"
    catalog = _es_catalog() if es else _catalog()
    with _SEARCH_LOCK:
        search = catalog.search(
            collections=["sentinel-2-l2a"], bbox=bbox,
            datetime=f"{date_range[0]}/{date_range[1]}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
        )
        items = sorted(search.items(), key=lambda it: it.properties.get("eo:cloud_cover", 100))
    if not items:
        return None
    items = items[:max_items]
    load_bands = [_ES_BAND_FOR[b] for b in [*bands, "SCL"]] if es else [*bands, "SCL"]
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
    grid = dict(geobox=geobox) if geobox is not None else dict(
        bbox=bbox, resolution=10, crs=CRS.from_epsg(epsg)
    )
    ds = odc.stac.load(
        items, bands=load_bands, groupby="solar_day",
        chunks={"x": 2048, "y": 2048}, fail_on_error=False, **grid,
    )
    if es:
        ds = ds.rename({_ES_BAND_FOR[b]: b for b in [*bands, "SCL"]})
    valid = ds["SCL"].isin(_SCL_VALID)
    masked = ds[bands].where(valid)
    if es:
        # Earth Search bakes the baseline->=04.00 BOA offset into its COGs
        # (earthsearch:boa_offset_applied); PC serves raw DNs, which is what the
        # model is calibrated to. Add the offset back per solar day so fallback
        # cells are radiometrically identical to PC ones (verified pixel-exact
        # +1000 on a matched scene). Pre-2022 baselines carry no offset.
        per_day = {
            it.datetime.date(): 1000 if it.properties.get("earthsearch:boa_offset_applied") else 0
            for it in items
        }
        offs = [per_day.get(d, 1000) for d in ds["time"].dt.date.values]
        masked = masked + xr.DataArray(offs, coords={"time": ds["time"]}, dims="time")
    med = masked.median(dim="time", skipna=True).fillna(0).astype("uint16").compute()
    arr = np.stack([med[b].values for b in bands], axis=0)
    if (arr != 0).mean() < 0.01:
        # fail_on_error=False degrades read failures to NaN -> 0, so a total 503
        # storm can yield a "successful" all-zero composite that resume-skipping
        # then never repairs. Cells are building-populated land: (near-)all-zero
        # means the reads failed wholesale, not that the ground is dark.
        raise RuntimeError(
            f"{provider}: composite {100 * (arr == 0).mean():.0f}% empty for bbox={bbox}"
        )
    transform = med.odc.transform if hasattr(med, "odc") else med.rio.transform()
    crs = geobox.crs if geobox is not None else CRS.from_epsg(epsg)
    return arr, transform, crs


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

    Tries Planetary Computer first (fastest from here when healthy), and hands the
    cell to Earth Search (AWS) if PC errors out, comes back empty, or is simply
    struggling — `PC_TIMEOUT_S` bounds how long we wait, since a SAS-token/503 storm
    degrades individual band reads (retried and swallowed by `fail_on_error=False`)
    without ever raising, so a struggling cell would otherwise silently take minutes
    instead of erroring outright. Different hosting from PC, so its recurring
    outages don't take the cell down.
    """
    fut = _PC_EXECUTOR.submit(
        _annual_composite_via, "planetary-computer", bbox, date_range, max_cloud, max_items, geobox
    )
    try:
        result = fut.result(timeout=PC_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        log.warning(
            "Planetary Computer exceeded %ds for bbox=%s (struggling); handing off to "
            "Earth Search without waiting further (the PC attempt is abandoned, not "
            "killed, and will finish in the background)",
            PC_TIMEOUT_S, bbox,
        )
        return _annual_composite_via(
            "earth-search", bbox, date_range, max_cloud, max_items, geobox
        )
    except Exception as e:  # noqa: BLE001 — any PC failure is grounds for fallback
        log.warning(
            "Planetary Computer failed for bbox=%s (%s); falling back to Earth Search",
            bbox, e,
        )
        return _annual_composite_via(
            "earth-search", bbox, date_range, max_cloud, max_items, geobox
        )
    if result is None:
        # PC has no scenes for this window; ES mirrors the same ESA archive but
        # ingestion lags differ — cheap second opinion before declaring no-data.
        log.info("Planetary Computer returned no scenes for bbox=%s; trying Earth Search", bbox)
        return _annual_composite_via(
            "earth-search", bbox, date_range, max_cloud, max_items, geobox
        )
    return result


def to_chip_array(ds: xr.Dataset, seasons: list[str]) -> np.ndarray:
    """(bands*len(seasons), y, x) uint16 array in S2_BANDS order per season."""
    arrs = [
        np.stack([ds[b].sel(season=s).values for b in S2_BANDS], axis=0) for s in seasons
    ]
    return np.concatenate(arrs, axis=0)
