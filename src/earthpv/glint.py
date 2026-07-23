"""Solar-glint geometry for PV panels in Sentinel-2 imagery.

A glass-fronted PV panel is partly a specular reflector: the sensor sees a
glint when the panel normal bisects the sun and view vectors (both pointing
up from the ground), n ~ (s + v)/|s + v|. Sentinel-2 views near-nadir
(view zenith 0..~12 deg), so a fixed panel glints only when its tilt is close
to half the solar zenith and its azimuth close to the solar azimuth at the
~10:30 local overpass — narrow, predictable date windows.

This module provides
- the specular geometry (required orientation / misalignment angle),
- skyfield-based sun positions and S2 overpass prediction from TLEs
  (the "when could a glint be measured" calendar), and
- parsing of per-scene MTD_TL.xml granule metadata for the *actual*
  per-point viewing angles of historical scenes (TLE back-propagation is
  not reliable years into the past; the metadata is ground truth).

All azimuths are degrees clockwise from north; zeniths from vertical.
Vectors are ENU (east, north, up) unit vectors.
"""

from __future__ import annotations

import logging
import math
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.config import DATA_DIR

log = logging.getLogger(__name__)

SKYFIELD_DIR = DATA_DIR / "skyfield"
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
GLINT_BANDS = ("B03", "B08")
_GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MAX_RETRY="3",
    GDAL_HTTP_RETRY_DELAY="2",
    VSI_CACHE="TRUE",
)

# NORAD catalog numbers of the Sentinel-2 constellation.
S2_NORAD = {"S2A": 40697, "S2B": 42063, "S2C": 60989}
# Satellite elevation (deg) at the ground point below which the point is
# outside the ~290 km swath (view zenith <= ~12 deg <=> elevation >= ~78).
_SWATH_MIN_ELEVATION = 78.0


# ---------------------------------------------------------------- geometry

def unit_enu(zenith_deg: float | np.ndarray, azimuth_deg: float | np.ndarray) -> np.ndarray:
    """ENU unit vector(s) pointing up from the ground at (zenith, azimuth)."""
    z = np.radians(zenith_deg)
    a = np.radians(azimuth_deg)
    return np.stack([np.sin(a) * np.sin(z), np.cos(a) * np.sin(z), np.cos(z)], axis=-1)


def zen_az(vec: np.ndarray) -> tuple[float, float]:
    e, n, u = vec[..., 0], vec[..., 1], vec[..., 2]
    zen = np.degrees(np.arccos(np.clip(u, -1, 1)))
    az = np.degrees(np.arctan2(e, n)) % 360.0
    return zen, az


def required_orientation(
    sun_zen: float, sun_az: float, view_zen: float, view_az: float
) -> tuple[float, float]:
    """Panel (tilt, azimuth) whose specular reflection of the sun hits the sensor."""
    s = unit_enu(sun_zen, sun_az)
    v = unit_enu(view_zen, view_az)
    n = s + v
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return zen_az(n)


def misalignment_deg(
    sun_zen: float, sun_az: float, view_zen: float, view_az: float,
    tilt: float, panel_az: float,
) -> float:
    """Angle between the panel's specular reflection of the sun and the view ray.

    ~0 deg means the glint hits the sensor; the effective tolerance is set by
    the solar disk (~0.5 deg) plus panel texturing/roughness (a few deg).
    """
    s = unit_enu(sun_zen, sun_az)
    v = unit_enu(view_zen, view_az)
    n = unit_enu(tilt, panel_az)
    r = 2.0 * np.sum(n * s, axis=-1, keepdims=True) * n - s
    cosang = np.clip(np.sum(r * v, axis=-1), -1.0, 1.0)
    return np.degrees(np.arccos(cosang))


# ---------------------------------------------------------------- skyfield

@lru_cache(maxsize=1)
def _sky():
    """(timescale, earth, sun) — ephemeris cached under data/skyfield/."""
    from skyfield.api import Loader

    SKYFIELD_DIR.mkdir(parents=True, exist_ok=True)
    load = Loader(str(SKYFIELD_DIR), verbose=False)
    ts = load.timescale()
    eph = load("de421.bsp")
    return ts, eph["earth"], eph["sun"]


def sun_position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Apparent sun (zenith, azimuth) at a WGS84 point. `when` must be tz-aware."""
    from skyfield.api import wgs84

    ts, earth, sun = _sky()
    t = ts.from_datetime(when.astimezone(timezone.utc))
    alt, az, _ = (earth + wgs84.latlon(lat, lon)).at(t).observe(sun).apparent().altaz()
    return 90.0 - alt.degrees, az.degrees


@lru_cache(maxsize=1)
def _s2_satellites():
    """Current TLEs for S2A/B/C from Celestrak (valid ~weeks around now)."""
    import requests
    from skyfield.api import EarthSatellite

    ts, _, _ = _sky()
    sats = {}
    for name, catnr in S2_NORAD.items():
        url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE"
        lines = requests.get(url, timeout=30).text.strip().splitlines()
        if len(lines) >= 3:
            sats[name] = EarthSatellite(lines[1], lines[2], lines[0].strip(), ts)
        else:
            log.warning("no TLE for %s (%s)", name, catnr)
    return sats


@dataclass
class Overpass:
    satellite: str
    time: datetime
    view_zen: float   # deg, at the ground point
    view_az: float    # deg, ground -> satellite
    sun_zen: float
    sun_az: float
    glint_tilt: float     # panel tilt that would glint into the sensor
    glint_az: float       # panel azimuth that would glint into the sensor

    def misalignment(self, tilt: float, panel_az: float) -> float:
        return float(misalignment_deg(
            self.sun_zen, self.sun_az, self.view_zen, self.view_az, tilt, panel_az
        ))


def predict_overpasses(
    lat: float, lon: float, start: datetime, end: datetime,
    min_sun_alt: float = 5.0,
) -> list[Overpass]:
    """Daytime S2 overpasses of a point, with per-pass glint orientation.

    Propagates current TLEs, so accuracy degrades away from today: timing
    drifts by minutes over months, but the *sun-driven* glint orientation
    (tilt ~ sun_zen/2 at ~10:30 local) is robust because the view stays
    near-nadir. Use scene metadata (below) for historical scenes instead.
    """
    from skyfield.api import wgs84

    ts, earth, sun = _sky()
    topos = wgs84.latlon(lat, lon)
    t0 = ts.from_datetime(start.astimezone(timezone.utc))
    t1 = ts.from_datetime(end.astimezone(timezone.utc))
    passes = []
    for name, sat in _s2_satellites().items():
        times, events = sat.find_events(topos, t0, t1, altitude_degrees=_SWATH_MIN_ELEVATION)
        for t, ev in zip(times, events):
            if ev != 1:  # culmination
                continue
            alt, az, _ = (sat - topos).at(t).altaz()
            when = t.utc_datetime()
            sz, sa = sun_position(lat, lon, when)
            if 90.0 - sz < min_sun_alt:  # night (ascending-node) pass
                continue
            vz, va = 90.0 - alt.degrees, az.degrees
            gt, ga = required_orientation(sz, sa, vz, va)
            passes.append(Overpass(name, when, vz, va, sz, sa, float(gt), float(ga)))
    return sorted(passes, key=lambda p: p.time)


def glint_windows(
    lat: float, lon: float, tilt: float, panel_az: float,
    start: datetime, end: datetime, tol_deg: float = 3.0,
) -> list[Overpass]:
    """Overpasses where a panel of the given orientation glints within tol."""
    return [
        p for p in predict_overpasses(lat, lon, start, end)
        if p.misalignment(tilt, panel_az) <= tol_deg
    ]


# ------------------------------------------------- granule metadata (MTD_TL)

def _angle_grid(node) -> np.ndarray:
    rows = [
        [float(v) for v in row.text.split()]
        for row in node.find("Values_List").findall("VALUES")
    ]
    return np.array(rows, dtype=float)


@dataclass
class TileAngles:
    """Angle grids of one granule (5 km grid over the 110 km tile)."""

    epsg: int
    ulx: float
    uly: float
    step: float
    sun_zen: np.ndarray
    sun_az: np.ndarray
    view_vec: np.ndarray        # (H, W, 3) detector-merged mean view unit vector
    mean_sun: tuple[float, float]
    # True tile sensing time. The STAC item datetime is the *datatake start*
    # (northern end of the orbit strip), minutes earlier for southern tiles.
    sensing_time: datetime | None = None

    def _idx(self, x: float, y: float) -> tuple[int, int]:
        """Nearest grid node for a point in tile CRS (grid anchored at UL)."""
        col = int(round((x - self.ulx) / self.step))
        row = int(round((self.uly - y) / self.step))
        h, w = self.sun_zen.shape
        return min(max(row, 0), h - 1), min(max(col, 0), w - 1)

    def at(self, lon: float, lat: float) -> dict | None:
        """Sun/view (zenith, azimuth) at a WGS84 point, or None if no detector."""
        import rasterio.warp

        xs, ys = rasterio.warp.transform("EPSG:4326", f"EPSG:{self.epsg}", [lon], [lat])
        r, c = self._idx(xs[0], ys[0])
        v = self.view_vec[r, c]
        if not np.isfinite(v).all():
            # fall back to the nearest finite node (detector-footprint edges)
            finite = np.argwhere(np.isfinite(self.view_vec[..., 0]))
            if len(finite) == 0:
                return None
            r, c = finite[np.argmin(((finite - [r, c]) ** 2).sum(axis=1))]
            v = self.view_vec[r, c]
        vz, va = zen_az(v / np.linalg.norm(v))
        return {
            "sun_zen": float(self.sun_zen[r, c]),
            "sun_az": float(self.sun_az[r, c]),
            "view_zen": float(vz),
            "view_az": float(va),
        }


def parse_tile_angles(xml_text: str, band_id: int = 3) -> TileAngles:
    """Parse MTD_TL.xml sun + viewing-angle grids (default band B04).

    Per-detector viewing grids are merged by averaging the ENU view vectors of
    all detectors covering a node (adjacent detectors alternate slightly
    fore/aft; the mean is the right summary for a 10 m pixel).
    """
    root = ET.fromstring(xml_text)
    ns = {"n1": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

    def find(path):
        node = root.find(path, ns) if ns else root.find(path)
        if node is None:
            raise ValueError(f"MTD_TL.xml: missing {path}")
        return node

    sensing = root.find(".//SENSING_TIME", ns) if ns else root.find(".//SENSING_TIME")
    sensing_time = None
    if sensing is not None:
        sensing_time = datetime.fromisoformat(sensing.text.replace("Z", "+00:00"))

    geocoding = find(".//Tile_Geocoding")
    epsg = int(geocoding.find("HORIZONTAL_CS_CODE").text.split(":")[1])
    geopos = geocoding.find("Geoposition[@resolution='10']")
    ulx, uly = float(geopos.find("ULX").text), float(geopos.find("ULY").text)

    angles = find(".//Tile_Angles")
    sun_grid = angles.find("Sun_Angles_Grid")
    step = float(sun_grid.find("Zenith/COL_STEP").text)
    sun_zen = _angle_grid(sun_grid.find("Zenith"))
    sun_az = _angle_grid(sun_grid.find("Azimuth"))
    mean = angles.find("Mean_Sun_Angle")
    mean_sun = (float(mean.find("ZENITH_ANGLE").text), float(mean.find("AZIMUTH_ANGLE").text))

    vec_sum = np.zeros((*sun_zen.shape, 3))
    vec_cnt = np.zeros(sun_zen.shape)
    for grids in angles.findall("Viewing_Incidence_Angles_Grids"):
        if int(grids.get("bandId")) != band_id:
            continue
        vz = _angle_grid(grids.find("Zenith"))
        va = _angle_grid(grids.find("Azimuth"))
        ok = np.isfinite(vz) & np.isfinite(va)
        vec = unit_enu(vz, va)
        vec_sum[ok] += vec[ok]
        vec_cnt[ok] += 1
    with np.errstate(invalid="ignore"):
        view_vec = vec_sum / vec_cnt[..., None]

    return TileAngles(epsg, ulx, uly, step, sun_zen, sun_az, view_vec, mean_sun, sensing_time)


# --------------------------------------------------------- historical scene series
#
# Two STAC providers over the same underlying ESA archive, same fallback rationale as
# imagery.py: Planetary Computer is fastest from here when healthy but has recurring
# 503 storms and SAS-token expiries under sustained load; Earth Search (AWS Open Data)
# needs no auth/tokens and lives in a different failure domain. Unlike imagery.py's
# per-cell composite (which needs every scene, so it falls back for the whole cell),
# scene_series tolerates losing individual scenes — spike detection just needs "enough"
# dates — so the fallback triggers only when a provider yields nothing at all.

ES_STAC_URL = "https://earth-search.aws.element84.com/v1"
# Earth Search keys assets by common band name, not B-number; also exposes the same
# granule metadata (MTD_TL.xml) under a differently-punctuated asset key.
_ES_BAND_ASSET = {
    "B01": "coastal", "B02": "blue", "B03": "green", "B04": "red",
    "B05": "rededge1", "B06": "rededge2", "B07": "rededge3", "B08": "nir",
    "B8A": "nir08", "B09": "nir09", "B11": "swir16", "B12": "swir22", "SCL": "scl",
}

_tile_angles_cache: dict[str, TileAngles] = {}
_tile_angles_lock = threading.Lock()
_SEARCH_LOCK = threading.Lock()  # pystac-client search is not thread-safe


@lru_cache(maxsize=1)
def _pc_catalog():
    import planetary_computer
    import pystac_client

    return pystac_client.Client.open(PC_STAC_URL, modifier=planetary_computer.sign_inplace)


@lru_cache(maxsize=1)
def _es_catalog():
    import pystac_client

    return pystac_client.Client.open(ES_STAC_URL)


def _search_items(provider: str, lon: float, lat: float, start: datetime, end: datetime,
                   max_cloud: int):
    catalog = _es_catalog() if provider == "earth-search" else _pc_catalog()
    with _SEARCH_LOCK:
        search = catalog.search(
            collections=["sentinel-2-l2a"],
            intersects={"type": "Point", "coordinates": [lon, lat]},
            datetime=f"{start.date()}/{end.date()}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
        )
        return list(search.items())


def _metadata_asset_key(provider: str) -> str:
    return "granule_metadata" if provider == "earth-search" else "granule-metadata"


def _band_asset_key(band: str, provider: str) -> str:
    return _ES_BAND_ASSET[band] if provider == "earth-search" else band


def _boa_offset(item, provider: str) -> float:
    """Earth Search bakes the baseline>=04.00 BOA offset into its COGs; Planetary
    Computer serves raw DNs, which `spike_fit`'s reflectance conversion assumes. Add
    the offset back so ES-sourced rows are radiometrically identical to PC ones
    (same fix as imagery.py's Earth Search fallback)."""
    if provider == "earth-search" and item.properties.get("earthsearch:boa_offset_applied"):
        return 1000.0
    return 0.0


def _cached_tile_angles(item, provider: str) -> TileAngles:
    cache_key = f"{provider}:{item.id}"
    with _tile_angles_lock:
        cached = _tile_angles_cache.get(cache_key)
    if cached is not None:
        return cached
    import requests

    href = item.assets[_metadata_asset_key(provider)].href
    xml_text = requests.get(href, timeout=60).text
    ta = parse_tile_angles(xml_text)
    with _tile_angles_lock:
        _tile_angles_cache[cache_key] = ta
    return ta


def _target_window(src, geometry, lon: float, lat: float):
    """Window position/size + the target geometry in the dataset's native CRS —
    shared by `_read_target_stats` (aggregate percentile/median) and
    `_read_target_array` (raw pixel array, for glint-composite/alignment-check
    imagery). Depends only on the target's own footprint, not on scene content."""
    import rasterio.warp
    import rasterio.windows

    xs, ys = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
    row, col = src.index(xs[0], ys[0])
    geom_native = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(src.crs).iloc[0]
    half_extent = max(
        geom_native.bounds[2] - geom_native.bounds[0],
        geom_native.bounds[3] - geom_native.bounds[1],
    ) / 2
    r_px = int(np.clip(half_extent / 10 + 10, 16, 60))
    win = rasterio.windows.Window(col - r_px, row - r_px, 2 * r_px, 2 * r_px)
    return win, geom_native


def _read_target_array(src, geometry, lon: float, lat: float):
    """Raw windowed DN array (NaN for nodata) + its affine transform + the target
    geometry in the array's CRS — the pixel-level analogue of `_read_target_stats`,
    which collapses to aggregate stats. For building a glint-composite image to
    visually/quantitatively check label-vs-imagery alignment (see
    docs/issues/glint-alignment-check.md)."""
    win, geom_native = _target_window(src, geometry, lon, lat)
    arr = src.read(1, window=win, boundless=True, fill_value=0).astype(float)
    arr[arr == 0] = np.nan
    return arr, src.window_transform(win), geom_native


def _read_target_stats(src, geometry, lon: float, lat: float) -> tuple[float, float, int]:
    """(p98 inside geometry, annulus median, n inside pixels), raw DN (no BOA offset —
    that's a per-item constant, applied by the caller, not per-read), from an ALREADY
    -OPEN band dataset.

    Extracted from `_polygon_band_stats` so the tile-batched reader (opens the dataset
    once, calls this per target) and the original per-target path share one
    implementation of the per-pixel math — the window read/mask/percentile logic is
    unavoidably per-target (each target has its own location), only the dataset open
    (and its HTTP session) is shared in the batched path.
    """
    import rasterio.features

    win, geom_native = _target_window(src, geometry, lon, lat)
    arr = src.read(1, window=win, boundless=True, fill_value=0).astype(float)
    wt = src.window_transform(win)
    inside = rasterio.features.geometry_mask(
        [geom_native], arr.shape, wt, invert=True, all_touched=False
    )
    if not inside.any():
        # Sub-pixel installation (common for small rooftop generators): the
        # strict mask selects no pixel centres. Fall back to every pixel the
        # polygon touches — p98 then reads the brightest touched pixel, which
        # is exactly where a glint from a small array shows up.
        inside = rasterio.features.geometry_mask(
            [geom_native], arr.shape, wt, invert=True, all_touched=True
        )
    ring = ~rasterio.features.geometry_mask(
        [geom_native.buffer(30)], arr.shape, wt, invert=True
    )
    arr[arr == 0] = np.nan
    inside_v, ring_v = arr[inside], arr[ring]
    if np.isfinite(inside_v).sum() < 1 or np.isfinite(ring_v).sum() < 20:
        return np.nan, np.nan, 0
    return (
        float(np.nanpercentile(inside_v, 98)),
        float(np.nanmedian(ring_v)),
        int(np.isfinite(inside_v).sum()),
    )


def _polygon_band_stats(
    item, band: str, geometry, lon: float, lat: float, provider: str,
) -> tuple[float, float, int]:
    """(p98 inside geometry, annulus median, n inside pixels), raw DN, in one band."""
    import rasterio

    href = item.assets[_band_asset_key(band, provider)].href
    with rasterio.Env(**_GDAL_ENV), rasterio.open(href) as src:
        p98, ring, npx = _read_target_stats(src, geometry, lon, lat)
    offset = _boa_offset(item, provider)  # NaN-preserving: nan + offset stays nan
    return p98 + offset, ring + offset, npx


def _scene_row(
    item, geometry, lon: float, lat: float, bands: tuple[str, ...], provider: str,
) -> dict | None:
    try:
        ta = _cached_tile_angles(item, provider)
        ang = ta.at(lon, lat)
        if ang is None:
            return None
        row = dict(time=ta.sensing_time or item.datetime,
                   cloud=item.properties.get("eo:cloud_cover"), **ang)
        for band in bands:
            p98, ring, npx = _polygon_band_stats(item, band, geometry, lon, lat, provider)
            row[f"p98_{band}"], row[f"ring_{band}"] = p98, ring
            row["npx"] = npx
        return row
    except Exception as e:  # noqa: BLE001 — per-scene failures shouldn't kill the pull
        log.debug("scene %s (%s) failed: %s", item.id, provider, e)
        return None


def _scene_series_via(
    provider: str, geometry, lon: float, lat: float, start: datetime, end: datetime,
    bands: tuple[str, ...], max_cloud: int, n_threads: int,
) -> pd.DataFrame:
    items = _search_items(provider, lon, lat, start, end, max_cloud)
    if not items:
        return pd.DataFrame()
    seen, keep = set(), []
    for it in sorted(items, key=lambda i: i.id):
        key = it.datetime.strftime("%Y%m%d%H%M")
        if key in seen:
            continue
        seen.add(key)
        keep.append(it)
    rows = []
    with ThreadPoolExecutor(n_threads) as ex:
        futs = [ex.submit(_scene_row, it, geometry, lon, lat, bands, provider) for it in keep]
        for f in as_completed(futs):
            r = f.result()
            if r:
                rows.append(r)
    return pd.DataFrame(rows).sort_values("time") if rows else pd.DataFrame()


def scene_series(
    geometry, start: datetime, end: datetime,
    bands: tuple[str, ...] = GLINT_BANDS, max_cloud: int = 80, n_threads: int = 8,
) -> pd.DataFrame:
    """Per-scene reflectance + sun/view-angle time series for one polygon.

    One row per Sentinel-2 L1C-dated scene: p98 in-polygon and annulus-median DN for
    each band, plus the point's true sun/view angles from that scene's MTD_TL.xml.
    Tries Planetary Computer first (fastest from here when healthy) and falls back to
    Earth Search (AWS Open Data, no auth/tokens, different failure domain) only if PC
    returns no scenes at all — individual PC scene-read failures (503 storms) are
    already tolerated per-scene by `_scene_row`, so they don't trigger this. Empty
    DataFrame if neither archive has usable scenes in range.
    """
    lon, lat = geometry.centroid.x, geometry.centroid.y
    df = _scene_series_via("planetary-computer", geometry, lon, lat, start, end,
                            bands, max_cloud, n_threads)
    if df.empty:
        log.info("Planetary Computer: no scenes near (%.4f, %.4f); trying Earth Search",
                  lon, lat)
        df = _scene_series_via("earth-search", geometry, lon, lat, start, end,
                                bands, max_cloud, n_threads)
    return df


# --------------------------------------------------------------------------------------
# Tile-batched fetch: the same per-target output as `scene_series`, for many targets at
# once. One STAC search + one set of asset opens per spatial group, shared by every
# target that falls in it, instead of one of each per target — the actual bottleneck at
# scale is re-discovering the same scene list and re-opening the same COGs for every
# candidate in a cluster, not the per-pixel math (see
# docs/issues/glint-tile-batched-coverage.md). Feeds both `postprocess.add_glint_prior`
# (detection) and `scripts/glint_spike_rate_estimator.py` (density) — same fetch, same
# output schema, so neither's scoring/inversion logic needs to change.
# --------------------------------------------------------------------------------------
def _tile_key(lon: float, lat: float, tile_deg: float) -> tuple[int, int]:
    return int(np.floor(lon / tile_deg)), int(np.floor(lat / tile_deg))


def _search_items_bbox(provider: str, bbox: tuple[float, float, float, float],
                        start: datetime, end: datetime, max_cloud: int):
    catalog = _es_catalog() if provider == "earth-search" else _pc_catalog()
    with _SEARCH_LOCK:
        search = catalog.search(
            collections=["sentinel-2-l2a"], bbox=list(bbox),
            datetime=f"{start.date()}/{end.date()}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
        )
        return list(search.items())


def _read_targets_from_item(
    item, band: str, targets: list[tuple[str, object, float, float]], provider: str,
    return_array: bool = False, apply_offset: bool = True,
) -> dict[str, tuple[float, float, int]] | dict[str, np.ndarray]:
    """Open one band asset once, read every target's window from it — the batched
    analogue of `_polygon_band_stats`, sharing one dataset handle (and its HTTP
    session/connection) across all targets instead of reopening per target.

    The asset open itself must be guarded, not just the per-target read: a long
    tile-batch run (many groups, each with its own STAC search) can outlive a
    Planetary Computer SAS token's ~30-45 min lifetime (the same failure documented
    for `compose_loop.sh`), and re-reading an EXPIRED token's URL fails at
    `rasterio.open()` — before any per-target try/except runs. Missed in the
    original implementation: it crashed a 500-target country-wide revalidation run
    45 minutes in (`RasterioIOError: HTTP response code: 403`), losing the whole
    run's progress since `tile_scene_series_batch` has no cross-group checkpointing.
    A later group's fresh STAC search mints a fresh token, so this only ever needs
    to fail the ONE item/band it hit, not the whole run.

    `return_array=True` returns `(reflectance-offset-applied raw window array, its
    affine window transform, the dataset's native CRS)` per target instead of
    collapsed stats — for a caller that needs pixel-level data (e.g. a per-pixel
    anomaly count) and a way to place each pixel back on the map. `apply_offset=False`
    skips the BOA reflectance offset entirely — required for a classification band
    like SCL, where the Earth Search radiometric-offset correction (`_boa_offset`)
    would corrupt the integer class codes rather than correct a reflectance DN.
    Must still be called from the SAME pass that
    opens the item/asset, not cached and re-read later: the href's SAS token is
    only fresh right after the search that produced it (see
    `scripts/glint_cell_pixel_anomaly_pilot.py`'s first version, which cached
    `tile_scene_series_batch(keep_items=True)`'s item refs and re-opened them in a
    later sequential per-cell loop — the first ~12 cells' reads landed inside the
    token's lifetime, every cell after that got 0 readable scenes, silently, because
    the per-target try/except caught the now-expired-token error as ordinary
    missing data rather than the true cause)."""
    import rasterio

    href = item.assets[_band_asset_key(band, provider)].href
    offset = _boa_offset(item, provider) if apply_offset else 0.0
    out = {}
    try:
        with rasterio.Env(**_GDAL_ENV), rasterio.open(href) as src:
            for pid, geometry, lon, lat in targets:
                try:
                    if return_array:
                        arr, wt, _gn = _read_target_array(src, geometry, lon, lat)
                        out[pid] = (arr + offset, wt, src.crs)
                    else:
                        p98, ring, npx = _read_target_stats(src, geometry, lon, lat)
                        out[pid] = (p98 + offset, ring + offset, npx)
                except Exception as e:  # noqa: BLE001 — one bad target must not kill the batch
                    log.debug("target %s failed on %s: %s", pid, href, e)
                    out[pid] = None if return_array else (np.nan, np.nan, 0)
    except Exception as e:  # noqa: BLE001 — an unopenable asset (expired token, 503
        log.debug("failed to open %s: %s", href, e)  # storm) must not kill the batch
        for pid, _geometry, _lon, _lat in targets:
            out[pid] = None if return_array else (np.nan, np.nan, 0)
    return out


def tile_scene_series_batch(
    targets: pd.DataFrame, start: datetime, end: datetime,
    bands: tuple[str, ...] = GLINT_BANDS, max_cloud: int = 80,
    tile_deg: float = 1.0, max_workers: int = 6, keep_items: bool = False,
) -> dict[str, pd.DataFrame]:
    """Tile-major batched analogue of `scene_series`, for many targets at once.

    `targets` needs columns `pid`, `geometry` (WGS84 point or small polygon), `lon`,
    `lat`. Groups targets into `tile_deg`-degree bins (a plain lon/lat grid, not a
    literal MGRS tile lookup — cheaper to compute and just as effective an
    amortization proxy: correctness of each target's read comes from its own
    coordinate transform into whichever scene's native CRS covers it, not from the
    grouping, so an imperfect group/tile alignment only costs a few wasted item-opens
    for out-of-bounds targets, never a wrong answer). One STAC search per group (by
    bbox, not per-target point, so a PC miss falls back to Earth Search once per group
    rather than once per target), then for every returned scene, each band asset is
    opened once and every group member's window is read from it.

    Returns `{pid: DataFrame}`, one row per scene, with the SAME columns
    `scene_series`/`_scene_row` produce (`time`, `cloud`, sun/view angles,
    `p98_<band>`/`ring_<band>` per band, `npx`) — every downstream consumer
    (`spike_fit`, `annotate_spikes`, `add_glint_prior`) is unchanged. Missing pids (no
    scenes found in range) come back as empty DataFrames, matching `scene_series`.

    `keep_items=True` adds `_item`/`_provider` columns (the STAC item object + which
    catalog it came from) alongside the stats — for a consumer that needs to go back
    and re-read pixel-level data for specific scenes afterward (e.g. building a glint
    composite image, see `scripts/glint_alignment_check.py`), without a second search.
    Off by default: item objects aren't parquet/CSV-serializable, and no production
    consumer (`add_glint_prior`, the density/precision scripts) needs them.
    """
    keys = [_tile_key(lon, lat, tile_deg) for lon, lat in zip(targets.lon, targets.lat)]
    groups: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    log.info("tile-batch: %d targets -> %d groups (%.2f deg)", len(targets), len(groups), tile_deg)

    all_rows: dict[str, list[dict]] = {pid: [] for pid in targets.pid}
    for gi, ((gx, gy), rows_idx) in enumerate(groups.items()):
        grp = targets.iloc[rows_idx]
        bbox = (gx * tile_deg, gy * tile_deg, (gx + 1) * tile_deg, (gy + 1) * tile_deg)
        provider = "planetary-computer"
        try:
            items = _search_items_bbox(provider, bbox, start, end, max_cloud)
        except Exception as e:  # noqa: BLE001 — one bad group search must not kill the run
            log.warning("tile-batch group %d: PC search failed (%s), trying Earth Search", gi, e)
            items = []
        if not items:
            provider = "earth-search"
            try:
                items = _search_items_bbox(provider, bbox, start, end, max_cloud)
            except Exception as e:  # noqa: BLE001 — same: skip the group, not the whole run
                log.warning("tile-batch group %d: Earth Search also failed (%s), skipping", gi, e)
                items = []
        if not items:
            log.debug("tile-batch group %d: no scenes for bbox %s", gi, bbox)
            continue
        # Do NOT dedupe items by date here: near a real tile-overlap seam, two items
        # sharing a date-minute key can cover DIFFERENT (only partially-overlapping)
        # footprints — a group-wide "keep the alphabetically-first id" tie-break can
        # silently keep the item that does NOT cover a given target while dropping the
        # one that does, since `TileAngles.at()` always returns an angle via its
        # nearest-finite-node fallback even for a point outside real coverage (masking
        # the miss until the pixel read fails). Caught by comparing against the
        # original per-target `scene_series` on a real seam-zone candidate: the group
        # search picked an adjacent tile that didn't actually cover that point, and
        # every one of its ~20 scenes silently read 0 finite pixels. Fix: process every
        # item, and resolve the per-date choice AFTER reading, per target, by whichever
        # item actually has data there (see the npx-based pick below).
        items = sorted(items, key=lambda i: i.id)
        member_targets = [(r.pid, r.geometry, r.lon, r.lat) for r in grp.itertuples()]

        def _process_item(item):
            try:
                ta = _cached_tile_angles(item, provider)
            except Exception as e:  # noqa: BLE001 — one bad scene shouldn't kill the group
                log.debug("tile-angles failed for %s: %s", item.id, e)
                return []
            band_results = {
                band: _read_targets_from_item(item, band, member_targets, provider)
                for band in bands
            }
            out = []
            for pid, geometry, lon, lat in member_targets:
                try:
                    ang = ta.at(lon, lat)
                    if ang is None:
                        continue
                    row = dict(pid=pid, time=ta.sensing_time or item.datetime,
                               cloud=item.properties.get("eo:cloud_cover"), **ang)
                    for band in bands:
                        p98, ring, npx = band_results[band][pid]
                        row[f"p98_{band}"], row[f"ring_{band}"] = p98, ring
                        row["npx"] = npx  # last band wins, matching `_scene_row`
                    if keep_items:
                        row["_item"], row["_provider"] = item, provider
                    out.append(row)
                except Exception as e:  # noqa: BLE001 — per-target failures shouldn't
                    log.debug("target %s on %s failed: %s", pid, item.id, e)  # kill the scene
            return out

        with ThreadPoolExecutor(max_workers) as ex:
            futs = {ex.submit(_process_item, it): it for it in items}
            for f in as_completed(futs):
                try:
                    rows = f.result()
                except Exception as e:  # noqa: BLE001 — one bad item must not kill the group
                    log.debug("item %s failed: %s", futs[f].id, e)
                    continue
                for row in rows:
                    all_rows[row["pid"]].append(row)

    # Per-target, per-date dedup: keep whichever item actually had data (max npx) —
    # the correctness fix described above. Applied here (once, in pandas) rather than
    # per-target during the fetch, since "best of several items for this date" can only
    # be decided once every item's read is in.
    def _dedupe(rows: list[dict]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["_date_key"] = pd.to_datetime(df["time"]).dt.strftime("%Y%m%d%H%M")
        df = df.sort_values("npx", ascending=False).drop_duplicates("_date_key", keep="first")
        return df.drop(columns="_date_key").sort_values("time").reset_index(drop=True)

    return {
        pid: (_dedupe(rows) if rows else pd.DataFrame())
        for pid, rows in all_rows.items()
    }


def _refl(dn):
    return np.clip((np.asarray(dn, dtype=float) - 1000.0) / 10000.0, 0, None)


def annotate_spikes(
    df: pd.DataFrame, bands: tuple[str, ...] = GLINT_BANDS,
    self_referenced: bool = False, ring_k_sigma: float = 3.0,
) -> pd.DataFrame:
    """Per-scene reflectance + clear/spike flags + required glint orientation.

    A spike is a scene where in-polygon reflectance in every band jumps far above its
    own clear-scene baseline. Two ways to rule out clouds/haze (which brighten the
    neighbourhood too, not just the target):

    - **Spatial** (default, `self_referenced=False`): the surrounding annulus must
      stay dim *right now* — `a > 1.5 * r` on this date. Requires the ring to be
      darker than the target in absolute terms, which holds for the rural/mixed
      imagery this was validated on but breaks down in dense urban blocks: with
      ~2,500 buildings/km² of similar-brightness rooftops, the ring is *never*
      meaningfully darker than the roof it surrounds, so the ratio never clears 1.5x
      even for a real, substantially-panelled installation (verified directly: best
      ratio over a full year on a confirmed 503 m² Lahore rooftop, ~480 m² of it
      mapped PV, was 1.09).
    - **Self-referenced** (`self_referenced=True`): instead of comparing the target to
      its neighbours *now*, compare the ring to *its own* history — the ring must
      stay within `ring_k_sigma` of its own clear-day baseline. This never depends on
      the ring's absolute brightness, only on whether it moved, so it targets exactly
      the dense-urban failure mode above (no need for the target to outshine
      permanently-bright neighbours) while keeping the same protection against
      neighbourhood-wide brightening (a hazy day moves the ring away from its own
      baseline either way — clouds/haze don't care whether the roof next door is
      bright or dark).

    Adds `a_*`/`r_*` (in-polygon / annulus reflectance), `clear`, `spike`, and
    `glint_tilt`/`glint_az` (the orientation that scene's geometry would require)
    columns. Rows missing reflectance stats are dropped; empty input (or
    all-missing) returns empty.
    """
    need = [f"p98_{b}" for b in bands] + [f"ring_{b}" for b in bands]
    d = df.dropna(subset=need).copy()
    if d.empty:
        return d
    for b in bands:
        d[f"a_{b}"] = _refl(d[f"p98_{b}"])
        d[f"r_{b}"] = _refl(d[f"ring_{b}"])

    stable = np.ones(len(d), bool)
    for b in bands:
        med = d[f"r_{b}"].median()
        stable &= d[f"r_{b}"].between(0.5 * med, 1.6 * med + 0.03)
    d["clear"] = stable

    base = {b: d.loc[d.clear, f"a_{b}"].median() for b in bands}
    sig = {
        b: max(1.4826 * (d.loc[d.clear, f"a_{b}"] - base[b]).abs().median(), 0.015)
        for b in bands
    }
    spike = d.clear.copy()
    if self_referenced:
        ring_base = {b: d.loc[d.clear, f"r_{b}"].median() for b in bands}
        ring_sig = {
            b: max(1.4826 * (d.loc[d.clear, f"r_{b}"] - ring_base[b]).abs().median(), 0.015)
            for b in bands
        }
    for b in bands:
        spike &= d[f"a_{b}"] > base[b] + 5 * sig[b]
        if self_referenced:
            spike &= d[f"r_{b}"] <= ring_base[b] + ring_k_sigma * ring_sig[b]
        else:
            spike &= d[f"a_{b}"] > 1.5 * (d[f"r_{b}"] + 0.02)
    d["spike"] = spike

    gt, ga = required_orientation(
        d.sun_zen.to_numpy(), d.sun_az.to_numpy(), d.view_zen.to_numpy(), d.view_az.to_numpy()
    )
    d["glint_tilt"], d["glint_az"] = gt, ga
    return d


def fit_best_orientation(
    annotated: pd.DataFrame, tol_deg: float = 3.0,
) -> tuple[float, float, int] | None:
    """Among an `annotate_spikes` frame's spike dates, the (tilt, az, n_consistent)
    that the largest number of them agree on via the specular condition — the
    geometric signature a coincidental bright pixel wouldn't have. None with fewer
    than 2 spikes (a single spike can't be checked for self-consistency)."""
    sp = annotated[annotated.spike]
    if len(sp) < 2:
        return None
    best, best_n = None, -1
    for _, s in sp.iterrows():
        mis = misalignment_deg(
            sp.sun_zen.to_numpy(), sp.sun_az.to_numpy(),
            sp.view_zen.to_numpy(), sp.view_az.to_numpy(),
            s.glint_tilt, s.glint_az,
        )
        n = int((mis <= tol_deg).sum())
        if n > best_n:
            best, best_n = (float(s.glint_tilt), float(s.glint_az)), n
    return best[0], best[1], best_n


def spike_fit(
    df: pd.DataFrame, bands: tuple[str, ...] = GLINT_BANDS, tol_deg: float = 3.0,
    self_referenced: bool = False, ring_k_sigma: float = 3.0,
) -> dict:
    """Detect glint spikes in a `scene_series` time series and fit one panel orientation.

    `self_referenced` swaps the spatial "ring must be dim now" check for a temporal
    one ("ring must be near its own baseline now") — see `annotate_spikes`. Use it in
    dense urban contexts where a spatial ring is never meaningfully darker than the
    roof it surrounds.

    Returns a dict with n_scenes/n_clear/n_spikes/fit_tilt/fit_az/n_consistent — the
    last two are NaN/0 with fewer than 2 spikes (a single spike can't be checked for
    self-consistency and is not distinguishable from a one-off bright pixel).
    """
    d = annotate_spikes(df, bands, self_referenced=self_referenced, ring_k_sigma=ring_k_sigma)
    if d.empty:
        return dict(n_scenes=0, n_clear=0, n_spikes=0, fit_tilt=np.nan, fit_az=np.nan,
                     n_consistent=0)
    res = dict(n_scenes=len(d), n_clear=int(d.clear.sum()), n_spikes=int(d.spike.sum()),
                fit_tilt=np.nan, fit_az=np.nan, n_consistent=0)
    fit = fit_best_orientation(d, tol_deg)
    if fit is not None:
        res["fit_tilt"], res["fit_az"] = round(fit[0], 1), round(fit[1], 1)
        res["n_consistent"] = fit[2]
    return res
