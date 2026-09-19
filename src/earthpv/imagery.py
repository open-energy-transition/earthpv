"""Sentinel-2 L2A seasonal median composites from Microsoft Planetary Computer.

Produces, for any bbox, per-season cloud-masked median composites of the 12
TerraMind S2L2A bands at 10 m, plus an annual median (median over seasons).

`annual_composite` (the compose-stage entry point) falls back to Element84's
Earth Search catalog (AWS Open Data, same L2A scenes as COGs) when Planetary
Computer errors out - PC is ~4x faster from here (West Europe region) when
healthy, but has multi-hour 503 storms and SAS-token expiries under sustained
load; Earth Search needs no auth/tokens and lives in a different failure domain.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
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
# Overridable, because 60 s is a single-cell number and compose runs several cells at
# once. A cell is BANDWIDTH-bound, not latency-bound (measured on Zambia 2026-09-13: one
# uncontended cell is 53 s via PC and 83 s via Earth Search, and ~290 MB of COG reads
# against a link that tops out near 320 MB/min -- i.e. one cell already saturates it).
# So under N workers a perfectly healthy cell takes roughly N x 53 s, every cell trips a
# 60 s patience, and the hand-off downloads each cell TWICE on a link that had no room
# for the first copy. Raise this to a few times the expected per-cell wall time when
# running several workers; the timeout is then still doing its job (catching a cell that
# is genuinely stuck) without firing on every cell.
PC_TIMEOUT_S = int(os.environ.get("EARTHPV_PC_TIMEOUT_S", "60"))
_PC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=24, thread_name_prefix="pc-attempt")
# Escape hatch for a PC outage that lasts longer than a compose run.
#
# The hand-off above abandons a struggling PC attempt but cannot kill it: the thread
# keeps reading the whole cell in the background, on the same link the Earth Search
# retry now needs. That is cheap when PC is healthy and a handful of cells straggle. It
# is a death spiral when EVERY cell exceeds the timeout, because the abandoned attempts
# accumulate until they fill the 24-slot pool and permanently hold the bandwidth --
# measured on Zambia 2026-09-13: with 6 compose workers 4 cells landed in 14 minutes,
# and raising it to 16 workers produced ZERO cells in the next 20 (each pass then dying
# on compose_loop.sh's 30-minute wall clock before writing anything, so the run looks
# alive and never advances). Setting EARTHPV_STAC_PROVIDER=earth-search skips the PC
# attempt entirely, which removes both the wasted bandwidth and the 60 s per-cell
# penalty. Unset (the default) keeps the PC-first behaviour every earlier run used.
_PROVIDER_OVERRIDE = os.environ.get("EARTHPV_STAC_PROVIDER", "").strip().lower() or None
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

# --- Resampling of the native-20 m bands ------------------------------------------------
#
# B05-B07, B8A, B11 and B12 are 20 m at the sensor; the composite is written at 10 m. With
# `odc.stac`'s default the 20 m value is REPLICATED nearest-neighbour into each 2x2 block,
# which was measured on cell 0122_0077 as 100.0% of 2x2 blocks constant for B11 and B12
# against 0.0% for B02 and B08. That is not merely coarse, it is MISREGISTERED: the value
# a footprint sees can come from a 20 m cell whose centre is up to 10 m away, and the
# classifier leans hardest on exactly these bands (`b11_mean` +4.33, `swir_vis_ratio`
# -3.92, `ndbi` +3.65, `b12_mean` -3.23, against +2.78 for the largest 10 m band).
#
# Measured 2026-09-19 over the 30 Pakistani calibration quadrats, leave-one-quadrat-out:
# bilinear moves roofclf's AUC within size band by a paired median +0.0041, better in 20 of
# 30 folds, sign test p=0.061. Suggestive rather than established, and free.
#
# SCL stays NEAREST because it is a class label: interpolating cloud class 8 and vegetation
# class 4 into "6" would invent water. The 10 m bands stay nearest too, since they are
# already on the target grid and interpolation could only blur them.
BAND_RESAMPLING = {
    "B05": "bilinear", "B06": "bilinear", "B07": "bilinear",
    "B8A": "bilinear", "B11": "bilinear", "B12": "bilinear",
}
DEFAULT_RESAMPLING = "20m-bilinear"


def _resampling_spec(mode: str, es: bool) -> str | dict:
    """odc.stac `resampling=` for a mode: "nearest" (the pre-2026-09-19 behaviour) or
    "20m-bilinear" (bilinear for the native-20 m bands only)."""
    if mode == "nearest":
        return "nearest"
    if mode != "20m-bilinear":
        raise ValueError(f"unknown resampling mode {mode!r}")
    spec = {"*": "nearest"}
    for b, how in BAND_RESAMPLING.items():
        spec[_ES_BAND_FOR[b] if es else b] = how
    return spec


# --- Temporal statistics ("keep more than the median") ---------------------------------
#
# The composite reduces ~12 cloud-masked scenes to their per-pixel median, which is the
# maximum-robustness central estimator and therefore deletes exactly the tail that a PV
# module puts there: a specular surface at a fixed tilt is anisotropic, so its brightest
# observations are the informative ones. These statistics come off the SAME stack the
# median is computed from, so they cost no extra download -- only compute, memory and
# disk. What they are for, per block:
#
#   p10  the dark tail. A shadow is dark and MOVES; PV is dark and does not.
#   p50  the median itself, stored here too so a sidecar is self-consistent: a cell whose
#        composite_0.tif was built in an earlier run under a possibly different scene
#        availability can still be differenced against its own epoch's median rather than
#        against a stale one.
#   p90  the bright tail, i.e. a free national glint proxy. Glint otherwise needs bespoke
#        per-target scene pulls (`glint.py`), which is why it is a corroborating signal
#        rather than a layer. Expect it to be WEAK here: 12 dry-season scenes give little
#        specular opportunity, which is the ceiling documented in docs/methods/glint.md.
#   std  temporal stability, the cheap separator between PV and cropland/water.
#   n    valid observations per pixel, which makes the other four readable: std = 0 means
#        "stable" at n = 12 and "one look" at n = 1, and the median composite alone cannot
#        tell those apart. Also surfaces nodata holes as a value rather than as forensics
#        (Zambia cell 0069_0068, 22.8% filled, cost a perimeter its verdict).
#
# NOT a claim that any of this helps. It is the cheapest measurable form of the question,
# and the ablation is what answers it.
TEMPORAL_STAT_BLOCKS = ("p10", "p50", "p90", "std")


def temporal_stat_band_names(bands: list[str] | tuple[str, ...]) -> list[str]:
    """Band descriptions of a temporal-stats sidecar, in written order.

    Block-major (every band's p10, then every band's p50, ...) so a reader can slice one
    statistic across all bands with a stride, and `n_obs` last as a single band.
    """
    return [f"{b}_{stat}" for stat in TEMPORAL_STAT_BLOCKS for b in bands] + ["n_obs"]


def _temporal_stats(stack, med_ds, bands: list[str]) -> np.ndarray:
    """Per-pixel temporal statistics as uint16 [len(TEMPORAL_STAT_BLOCKS)*nb + 1, H, W].

    `stack` is the cloud-masked (bands, time, y, x) Dataset, already in memory; `med_ds`
    its median over time, passed in so it is not computed twice.

    Reflectance statistics keep the composite's own DN scale, so p50 here is bit-identical
    to `composite_0.tif`'s band when both are built from the same scenes. Negative DNs
    (possible after the L2A baseline offset) are clipped at 0 rather than allowed to wrap
    through uint16, which is a real hazard the median path avoids only by accident.
    """
    q = stack.quantile([0.10, 0.90], dim="time", skipna=True)
    sd = stack.std(dim="time", skipna=True)
    per_block = {
        "p10": q.sel(quantile=0.10),
        "p50": med_ds,
        "p90": q.sel(quantile=0.90),
        "std": sd,
    }
    planes = [
        np.clip(np.nan_to_num(per_block[stat][b].values, nan=0.0), 0, 65535)
        for stat in TEMPORAL_STAT_BLOCKS
        for b in bands
    ]
    # Valid-observation count. Taken from one band rather than the SCL mask so it also
    # counts a scene whose read failed (fail_on_error=False degrades those to NaN, which
    # the SCL mask cannot see).
    n_obs = stack[bands[0]].notnull().sum(dim="time").values
    planes.append(np.clip(n_obs, 0, 65535))
    return np.stack(planes, axis=0).astype("uint16")


def _annual_composite_via(
    provider: str,
    bbox: tuple[float, float, float, float],
    date_range: tuple[str, str],
    max_cloud: int,
    max_items: int,
    geobox=None,
    with_stats: bool = False,
    resampling: str = DEFAULT_RESAMPLING,
) -> tuple[np.ndarray, object, object] | tuple[np.ndarray, object, object, np.ndarray] | None:
    """One provider attempt of annual_composite; `provider` is
    "planetary-computer" or "earth-search".

    `with_stats` additionally returns the per-pixel temporal statistics array (see
    `annual_composite`), computed from the same scene stack at no extra download."""
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
        chunks={"x": 2048, "y": 2048}, fail_on_error=False,
        resampling=_resampling_spec(resampling, es), **grid,
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
    stats_arr = None
    if with_stats:
        # Materialize the masked stack ONCE. Every reducer below is then numpy over an
        # in-memory array; issuing them against the lazy dask graph instead would re-read
        # -- and on a remote COG, re-DOWNLOAD -- every scene once per statistic, which is
        # the whole point of taking these from the stack that the median already pays for.
        # The stack itself is bands x dates x cell pixels x 4 bytes, 0.53 GB for a typical
        # Pakistani cell (989x1120 px, 12 scenes); MEASURED peak RSS is about 2.2 GB,
        # because `quantile` sorts a copy and GDAL holds its own block cache on top. So a
        # stats run is memory-bound as well as bandwidth-bound: keep `workers` low.
        stack = masked.astype("float32").compute()
        med_ds = stack.median(dim="time", skipna=True)
        stats_arr = _temporal_stats(stack, med_ds, bands)
    else:
        med_ds = masked.median(dim="time", skipna=True)
    med = med_ds.fillna(0).astype("uint16").compute()
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
    if with_stats:
        return arr, transform, crs, stats_arr
    return arr, transform, crs


def annual_composite(
    bbox: tuple[float, float, float, float],
    date_range: tuple[str, str] = ("2025-11-01", "2026-03-15"),
    max_cloud: int = 30,
    max_items: int = 12,
    geobox=None,
    with_stats: bool = False,
    resampling: str = DEFAULT_RESAMPLING,
) -> tuple[np.ndarray, object, object] | tuple[np.ndarray, object, object, np.ndarray] | None:
    """Cloud-masked median over the 10 local bands (B02..B12), 10 m.

    `resampling` is "20m-bilinear" (the default since 2026-09-19: bilinear for the bands
    that are natively 20 m, nearest for everything else) or "nearest" (what every composite
    built before that date used). **Do not mix the two within one AOI.** The change is
    small but systematic, and a model calibrated on nearest composites and scored on
    bilinear ones is a domain shift, not an improvement; recompose a country wholesale or
    leave it alone. See `BAND_RESAMPLING` for what was measured.

    `with_stats=True` returns a 4-tuple, `(arr, transform, crs, stats)`, where `stats` is
    the per-pixel temporal-statistics array described in `_temporal_stats`. It is computed
    from the same downloaded scenes, so it adds compute and memory but no network traffic
    -- the binding constraint on this stage is bandwidth (about 290 MB of COG reads per
    cell against a link that tops out near 320 MB/min). Off by default: every composite
    shipped to date is the median alone, and the extra bands roughly quadruple per-cell
    disk (about 48 MB against 12 MB), which is ~215 GB if it were ever run over all 4,473
    Pakistani cells.

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
    struggling - `PC_TIMEOUT_S` bounds how long we wait, since a SAS-token/503 storm
    degrades individual band reads (retried and swallowed by `fail_on_error=False`)
    without ever raising, so a struggling cell would otherwise silently take minutes
    instead of erroring outright. Different hosting from PC, so its recurring
    outages don't take the cell down.
    """
    if _PROVIDER_OVERRIDE is not None:
        # Single-provider mode (EARTHPV_STAC_PROVIDER). No fallback: the point is to
        # stop paying for a provider that is known to be down for this whole run.
        return _annual_composite_via(
            _PROVIDER_OVERRIDE, bbox, date_range, max_cloud, max_items, geobox, with_stats,
            resampling,
        )
    fut = _PC_EXECUTOR.submit(
        _annual_composite_via, "planetary-computer", bbox, date_range, max_cloud, max_items,
        geobox, with_stats, resampling,
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
            "earth-search", bbox, date_range, max_cloud, max_items, geobox, with_stats,
            resampling,
        )
    except Exception as e:  # noqa: BLE001 - any PC failure is grounds for fallback
        log.warning(
            "Planetary Computer failed for bbox=%s (%s); falling back to Earth Search",
            bbox, e,
        )
        return _annual_composite_via(
            "earth-search", bbox, date_range, max_cloud, max_items, geobox, with_stats,
            resampling,
        )
    if result is None:
        # PC has no scenes for this window; ES mirrors the same ESA archive but
        # ingestion lags differ - cheap second opinion before declaring no-data.
        log.info("Planetary Computer returned no scenes for bbox=%s; trying Earth Search", bbox)
        return _annual_composite_via(
            "earth-search", bbox, date_range, max_cloud, max_items, geobox, with_stats,
            resampling,
        )
    return result


GCS_S2 = "https://storage.googleapis.com/gcp-public-data-sentinel-2"
# Concurrent (scene, band) JP2 reads. I/O-bound, so this is not CPU parallelism.
L1C_WORKERS = int(os.environ.get("EARTHPV_L1C_WORKERS", "10"))
_GRANULE_CACHE: dict[str, str] = {}


def _gcs_granule_dir(product_uri: str, zone: str, band_lat: str, square: str) -> str | None:
    """The single GRANULE/<...>/ folder inside a SAFE, which only a listing reveals."""
    import json
    import urllib.request

    if product_uri in _GRANULE_CACHE:
        return _GRANULE_CACHE[product_uri]
    prefix = f"tiles/{zone}/{band_lat}/{square}/{product_uri}/GRANULE/"
    url = ("https://storage.googleapis.com/storage/v1/b/gcp-public-data-sentinel-2/o"
           f"?prefix={urllib.parse.quote(prefix)}&delimiter=%2F")
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            pre = json.load(r).get("prefixes", [])
    except Exception as e:  # noqa: BLE001
        log.warning("GCS granule listing failed for %s: %s", product_uri, e)
        return None
    if not pre:
        return None
    _GRANULE_CACHE[product_uri] = pre[0]
    return pre[0]


def l1c_composite(
    bbox: tuple[float, float, float, float],
    date_range: tuple[str, str] = ("2025-11-01", "2026-03-15"),
    max_cloud: int = 30,
    max_items: int = 12,
    geobox=None,
) -> tuple[np.ndarray, object, object] | None:
    """Cloud-masked median of TOP-OF-ATMOSPHERE (L1C) reflectance, same bands and grid.

    Why bother: Sen2Cor's surface-reflectance retrieval assumes a LAMBERTIAN surface and
    constrains aerosol from dark targets. A PV module is specular AND dark, so L2A models
    exactly the wrong thing over exactly the target of interest, in a geometry-dependent
    way, and it clips the saturation a real glint produces. Whether that costs anything is
    an empirical question, and this is how it gets asked.

    Where the pixels come from, and why it is not the obvious place: Planetary Computer
    publishes L2A only, and Earth Search's `sentinel-2-l1c` assets point at ESA's
    **requester-pays** `s3://sentinel-s2-l1c` bucket, which needs AWS credentials. Google's
    `gcp-public-data-sentinel-2` mirrors the same SAFE archives and is anonymously
    readable, so discovery runs on STAC (metadata, free) and the pixels are read as JP2
    over HTTPS from GCS. The band files are at their NATIVE resolution there -- 10980 px
    for B02, 5490 for B11 -- and are resampled onto `geobox` here.

    L1C carries no usable cloud mask (QA60 is empty from baseline 04.00), so the mask comes
    from the L2A scenes of the same solar days, loaded on the same grid. A day with no
    matching L2A scene is dropped rather than left unmasked.

    No radiometric offset is applied: every scene in a post-2022 window shares one
    baseline, so it is a constant a refitted classifier absorbs in its intercept. TOA is
    NOT comparable to the BOA composites; this is for refitting on, not differencing.
    """
    import rasterio
    import rasterio.warp
    from rasterio.crs import CRS
    from rasterio.windows import from_bounds

    bands = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
    catalog = _es_catalog()
    with _SEARCH_LOCK:
        def _search(collection):
            hits = catalog.search(
                collections=[collection], bbox=bbox,
                datetime=f"{date_range[0]}/{date_range[1]}",
                query={"eo:cloud_cover": {"lt": max_cloud}},
            )
            return sorted(hits.items(), key=lambda it: it.properties.get("eo:cloud_cover", 100))
        l1c_items = _search("sentinel-2-l1c")[:max_items]
        if not l1c_items:
            return None
        days = {it.datetime.date() for it in l1c_items}
        l2a_items = [it for it in _search("sentinel-2-l2a") if it.datetime.date() in days]
    if not l2a_items:
        log.warning("L1C: no matching L2A scenes for a cloud mask at bbox=%s", bbox)
        return None

    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
    grid = dict(geobox=geobox) if geobox is not None else dict(
        bbox=bbox, resolution=10, crs=CRS.from_epsg(epsg)
    )
    scl_ds = odc.stac.load(
        l2a_items, bands=[_ES_BAND_FOR["SCL"]], groupby="solar_day",
        chunks={"x": 2048, "y": 2048}, fail_on_error=False, **grid,
    ).rename({_ES_BAND_FOR["SCL"]: "SCL"}).compute()
    scl_by_day = {
        np.datetime64(t, "D").astype(object): scl_ds["SCL"].isel(time=i).values
        for i, t in enumerate(scl_ds["time"].values)
    }
    if geobox is not None:
        dst_crs, dst_transform = geobox.crs, geobox.transform
        dst_h, dst_w = geobox.shape
    else:
        dst_crs = CRS.from_epsg(epsg)
        dst_transform = scl_ds.odc.transform
        dst_h, dst_w = scl_ds["SCL"].shape[-2:]

    def _read_one(url: str) -> np.ndarray:
        """One band of one scene, resampled onto the target grid."""
        with rasterio.open(url) as src:
            wb = rasterio.warp.transform_bounds(
                dst_crs, src.crs,
                *rasterio.transform.array_bounds(dst_h, dst_w, dst_transform))
            win = from_bounds(*wb, src.transform).round_offsets().round_lengths()
            src_arr = src.read(1, window=win, boundless=True, fill_value=0)
            out = np.zeros((dst_h, dst_w), dtype="uint16")
            rasterio.warp.reproject(
                src_arr, out, src_transform=src.window_transform(win), src_crs=src.crs,
                dst_transform=dst_transform, dst_crs=dst_crs,
                resampling=rasterio.warp.Resampling.nearest)
            return out

    # Build the full (scene, band) work list, then read it concurrently. Serially this is
    # about 12 minutes per quadrat: each JP2 open costs 3-5 s of HTTP range requests to
    # parse a 10980 px header, times 10 bands times 12 scenes. The work is pure I/O, so a
    # pool collapses it to a couple of minutes. GDAL options below stop vsicurl probing for
    # sidecar files it will never find, which is a large part of that open cost.
    jobs = {}
    for it in l1c_items:
        if scl_by_day.get(it.datetime.date()) is None:
            continue
        pu = it.properties.get("s2:product_uri", "").rstrip("/")
        z = str(it.properties.get("mgrs:utm_zone"))
        gd = _gcs_granule_dir(pu, z, it.properties.get("mgrs:latitude_band"),
                              it.properties.get("mgrs:grid_square"))
        if not pu or not gd:
            continue
        sensing = pu.split("_")[2]          # e.g. 20260315T054639
        tile = (f"T{int(z):02d}{it.properties['mgrs:latitude_band']}"
                f"{it.properties['mgrs:grid_square']}")
        jobs[it] = [f"/vsicurl/{GCS_S2}/{gd}IMG_DATA/{tile}_{sensing}_{b}.jp2" for b in bands]

    stack, used = [], 0
    env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                       CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".jp2",
                       GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")
    with env, concurrent.futures.ThreadPoolExecutor(max_workers=L1C_WORKERS) as ex:
        futs = {it: [ex.submit(_read_one, u) for u in urls] for it, urls in jobs.items()}
        for it, fs in futs.items():
            try:
                planes = [f.result() for f in fs]
            except Exception as e:  # noqa: BLE001 - a bad band drops its scene, not the cell
                log.warning("L1C scene %s dropped: %s", it.id, e)
                continue
            a = np.stack(planes).astype("float32")
            a[:, ~np.isin(scl_by_day[it.datetime.date()], _SCL_VALID)] = np.nan
            stack.append(a)
            used += 1
    if not stack:
        log.warning("L1C: no scene could be read at bbox=%s", bbox)
        return None
    with np.errstate(invalid="ignore"):
        med = np.nanmedian(np.stack(stack), axis=0)
    arr = np.nan_to_num(med, nan=0.0).clip(0, 65535).astype("uint16")
    if (arr != 0).mean() < 0.01:
        raise RuntimeError(f"L1C composite {100 * (arr == 0).mean():.0f}% empty for bbox={bbox}")
    log.info("L1C: %d scenes read of %d, %d with a cloud mask", used, len(l1c_items), len(scl_by_day))
    return arr, dst_transform, dst_crs


def to_chip_array(ds: xr.Dataset, seasons: list[str]) -> np.ndarray:
    """(bands*len(seasons), y, x) uint16 array in S2_BANDS order per season."""
    arrs = [
        np.stack([ds[b].sel(season=s).values for b in S2_BANDS], axis=0) for s in seasons
    ]
    return np.concatenate(arrs, axis=0)
