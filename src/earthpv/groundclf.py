"""Ground-PV detector for small arrays beside farmland: roofclf's footprint-free sibling.

## Why a second instrument in the roofclf family

`roofclf` asks "does this roof carry PV?", which needs a roof. A solar pump array beside
a field has none: in Yemen's 'Amran test ground (283 owner-mapped arrays, 2026-10-23) only
6.6% of mapped array area lies on a VIDA footprint and 73% of arrays touch none, so the
rooftop classifier cannot see this population at any threshold. Segmentation cannot
either: it burns everything below 400 m2 as `ignore`, and in that box it found 0 (v13) and
4 (v5) of 283 arrays of every size.

The pixels can. The same arrays read 8-21% darker than a 30 m ring around them in the
visible and near-infrared and unchanged in SWIR (the 20 m SWIR pixel mixes them with
bright soil), which is SPPI's signature: zero-training SPPI separates PV pixels at AUC
0.93 there, and a 20-feature pixel logistic (`FEATURES`: bands, NDVI/NDBI/SPPI, and each
pixel minus its 70 m median) at 0.987, leave-one-block-out. As objects that was precision
0.55 at 81% array recall once the two confusers below were vetoed.

So the unit here is the PIXEL, aggregated into blobs, not the building.

## Two label sources, because good ones are rare

- **Clean areas**: farm calibration quadrats (`new_calibration_quadrat.py --farm`, stems
  carrying `roofclf.FARM_QUADRAT_INFIX`, drawn by `propose_calibration_candidates.py
  --farmland`) and any boundary passed as `clean_regions`. Every visible installation
  mapped. Pixels >= `POSITIVE_COVER` covered by a traced array (`power=generator`) are
  positives, pixels more than `CLEAN_NEG_BUFFER_M` from any PV are negatives. Only these
  can give precision and the capacity calibration. A complete area may still hold coarse
  shapes: a `power=plant` outline or a node trains as a bag (below) and is priced by
  `panel_area_factor`, so Tihama's 1,534 UNGSC rectangles, every one checked by the owner
  but drawn around a site, calibrate at the land constant rather than as panels.
- **Weak areas** (`weak_regions`): ordinary OSM, oversized rectangles and nodes included.
  Each label is a multiple-instance "bag" known to hold PV somewhere; the `MIL_K` most
  PV-like pixels in it are its positives, re-chosen over `MIL_ITERS` refits starting from
  SPPI. Measured on Tihama (1,533 four-corner `power=plant` rectangles, median 632 m2, plus
  117 nodes): leave-one-strip-out bag AUC 0.94 against the same shapes shifted into nearby
  land, where training the same rectangles as masks (how v13 was trained) learned nothing.
  Weak areas train the model; they never calibrate capacity.

## What is vetoed, and why each veto exists

- **Paved roads** (`ROAD_VETO_FRAC` of a blob within `ROAD_HALF_WIDTH_M` of an OSM
  motorway..tertiary centreline): all 9 road false positives in 'Amran's top 60, none of
  its mapped arrays. A flat road buffer would have dropped real arrays 0-5 m from roads.
- **Water** (blob SWIR more than `SWIR_VETO` below its ring): water-harvesting ponds were
  the main residual confuser, dark in the visible like panels but also dark in SWIR. It
  removed 11 leads and 0 of 301 mapped arrays. MNDWI does not work here: in a dry-season
  median the ponds read dry.
- **Outside the ROI** (no pixel within `ROI_RADIUS_M` of a building, a WorldCover cropland
  pixel or a green pixel): 96% of 'Amran's arrays lie inside it, in 28% of the land. It
  bought only 3-6 points of precision there, and exists mainly for basalt and shadowed
  hillsides far from any field (Sa'dah's dark-rock blobs).

## Capacity, and the 400 m2 cap

`ground_capacity` prices what neither OSM nor segmentation already counts: kept blobs more
than `DEDUP_M` from any OSM solar feature and any candidate segmentation's figure uses,
times a ratio of true mapped PV area per detected blob area measured on the clean areas
(the same coverage-ratio idea `sub400_capacity` applies to flagged roofs), times the
module constant, since arrays are traced around the panels. Its uncertainty is a
bootstrap over the clean AREAS, never pixels or blobs.

`max_array_m2` (default `MAX_ARRAY_M2`, the project's 400 m2 floor) restricts the ratio's
numerator to arrays below it, which makes the estimand "PV in arrays below 400 m2". That
is roofclf's convention, and it is not the whole gap here: 88% of 'Amran's mapped array
AREA is in arrays of 400 m2 or more, which segmentation also misses. Pass
`max_array_m2=None` to price farm ground PV of every size.

## Honest limits

The model and every number above come from two Yemeni areas. Transfer to a new country
is measured by leave-one-region-out (`train_ground` reports it), and is the open question:
Tihama-only training found 'Amran's arrays at pixel AUC 0.935 but at lower precision than
plain SPPI. Precision in a clean area is a lower bound where its imagery predates the
composite (Rule 1 is epoch-relative, see `roofclf`): 'Amran's leads included arrays a
Sentinel-2 time series dates to after the Esri capture.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from rasterio.transform import Affine
from scipy import ndimage
from shapely.geometry import Point, shape
from shapely.geometry import box as shapely_box
from shapely.geometry.base import BaseGeometry

from earthpv import roofclf
from earthpv.roofclf import BAND_NAMES, REFL_SCALE

log = logging.getLogger(__name__)

DETECTOR = "groundclf"
# The module was `roofclf_ground` until 2026-10-25; models fitted under that name still load.
LEGACY_DETECTORS = ("roofclf_ground",)
_LC_BANDS = ("b03", "b04", "b08", "b11", "b12")
FEATURES = ([f"log_{b}" for b in BAND_NAMES] + ["ndvi", "ndbi", "sppi"]
            + [f"lc_{b}" for b in _LC_BANDS] + ["lc_sppi", "lc_ndvi"])
LOCAL_WINDOW_PX = 7            # "pixel minus its 70 m median": darker than what surrounds it
POSITIVE_COVER = 0.5           # clean areas: a pixel at least half covered by mapped panels
CLEAN_NEG_BUFFER_M = 20.0      # clean areas: negatives keep this far from any mapped PV
WEAK_NEG_BUFFER_M = 100.0      # weak areas: OSM is incomplete and offset, so further
NODE_BAG_RADIUS_M = 30.0       # a mapped node is a bag of this radius
OUTLINE_KINDS = ("plant",)     # OSM features that outline a site, not its panels
MIL_K = 2                      # pixels per weak bag taken as positives
MIL_ITERS = 3
NEG_SAMPLE = 200_000           # negatives drawn per area and fold
N_BLOCKS = 4                   # spatial strips per area for leave-one-block-out
L2 = roofclf.L2
ROAD_HALF_WIDTH_M = 8.0
ROAD_VETO_FRAC = 0.3
SWIR_VETO = -0.2
ROI_RADIUS_M = 50.0
GREEN_NDVI = 0.25
TARGET_PRECISION = 0.5         # same precision target roofclf's deployment threshold uses
MAX_ARRAY_M2 = roofclf.MIN_PV_AREA_FOR_PACKING
# No farm array is a sheet of square kilometres. Measured on Yemen's 2026-10-24 national run:
# 87% of the detected area was in blobs of 5,000 m2 and more, mostly desert cells under 1%
# cropland (lava fields, dark rock), the largest one 61 km2, while the largest installation
# mapped in the seven farm areas is 22,231 m2 (99% under 2,215) and the largest detection in
# those areas 16,000 m2. The cap removes the sheets and touches no calibration blob.
MAX_BLOB_M2: float | None = 25_000.0
DEDUP_M = 20.0
# The calibration's applicability domain: cells whose cropland share AND building density lie
# within this factor of the range the clean areas span. The same x/÷1.25 the farm candidate
# sampler uses to call a box representative of its cell. Outside it the ratio is an
# extrapolation (the first Yemeni smoke test put its largest cells on Al Hudaydah's coast and
# city, 0-4% cropland, priced with a ratio measured on highland farms).
DOMAIN_TOL = 1.25
# A region's ratio is bootstrapped over its own areas once it has this many; below that it
# carries a stated factor of two either way at 90% (what `atlas` labels a judgement).
BOOT_MIN_AREAS = 3
JUDGEMENT_CI90 = (0.5, 2.0)
DEM_COLLECTION = "cop-dem-glo-90"   # Copernicus DEM, 90 m, on Planetary Computer
DEM_STEP = 10                      # cells read at every 10th DEM pixel, about 900 m
READ_PAD_M = 150.0             # covers the 35 m median window, 40 m ring and 50 m ROI
ON_MAPPED_M = 20.0             # a blob this close to a mapped array counts as right
SHIFT_M = (300.0, 2000.0)      # null bags: a label moved this far into nearby land
BOOT_SEED = 20261023
WC_TOKEN_S = 1800              # re-sign WorldCover tile URLs this often in a long run


# --------------------------------------------------------------------------------------
# Pixels
# --------------------------------------------------------------------------------------
def pixel_features(refl: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """`(H, W, len(FEATURES))` float32 from a 10-band window (`BAND_NAMES` order,
    composite DN / `REFL_SCALE`, the scaling roofclf uses); NaN where `valid` is False.

    Nodata is filled with each band's valid median before the local medians are taken, so
    a cell edge does not read as a dark spot to the pixels beside it.
    """
    from earthpv.sppi import compute_sppi

    r = np.clip(refl.astype("float32"), 1e-4, None)
    if valid.any() and not valid.all():
        fill = np.array([np.median(b[valid]) for b in r], dtype="float32")
        r = np.where(valid[None], r, fill[:, None, None])
    B = dict(zip(BAND_NAMES, r))
    eps = np.float32(1e-6)
    ndvi = (B["b08"] - B["b04"]) / (B["b08"] + B["b04"] + eps)
    ndbi = (B["b11"] - B["b08"]) / (B["b11"] + B["b08"] + eps)
    sppi = compute_sppi(B["b02"], B["b03"], B["b08"], B["b11"], B["b12"]).astype("float32")
    logs = {b: np.log(B[b]) for b in BAND_NAMES}

    def lc(x):
        return x - ndimage.median_filter(x, size=LOCAL_WINDOW_PX)

    cols = ([logs[b] for b in BAND_NAMES] + [ndvi, ndbi, sppi]
            + [lc(logs[b]) for b in _LC_BANDS] + [lc(sppi), lc(ndvi)])
    X = np.stack(cols, axis=-1).astype("float32")
    X[~valid] = np.nan
    return X


def logit(model: dict, X: np.ndarray) -> np.ndarray:
    """The model's decision value. Thresholds and rankings use this, not the probability:
    a balanced fit puts every strong detection at a probability that rounds to 1.0 in
    float32, which ties exactly the blobs a reviewer should see first."""
    Z = np.hstack([(X - model["mu"]) / model["sd"], np.ones((len(X), 1))])
    return Z @ model["w"]


def score_pixels(model: dict, X: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Logit per pixel (NaN outside `mask` and where any feature is NaN)."""
    H, W = X.shape[:2]
    out = np.full((H, W), np.nan, dtype="float32")
    m = np.isfinite(X).all(-1) if mask is None else (mask & np.isfinite(X).all(-1))
    if m.any():
        out[m] = logit(model, X[m].astype("float64"))
    return out


def pv_cover(geoms, out_shape, transform, sub: int = 10, strip: int = 256) -> np.ndarray:
    """Share of each pixel covered by `geoms`, rasterised at 1/`sub` of a pixel in row
    strips so a large area does not need a full-resolution canvas."""
    H, W = out_shape
    out = np.zeros(out_shape, dtype="float32")
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return out
    fine = transform * Affine.scale(1.0 / sub)
    for r0 in range(0, H, strip):
        r1 = min(H, r0 + strip)
        t = fine * Affine.translation(0, r0 * sub)
        f = rasterio.features.rasterize(((g, 1) for g in geoms), out_shape=((r1 - r0) * sub, W * sub),
                                        transform=t, dtype="uint8")
        out[r0:r1] = f.reshape(r1 - r0, sub, W, sub).mean(axis=(1, 3))
    return out


def _mask(geoms, out_shape, transform, all_touched: bool = True) -> np.ndarray:
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(out_shape, dtype=bool)
    return rasterio.features.rasterize(((g, 1) for g in geoms), out_shape=out_shape, transform=transform,
                                       all_touched=all_touched, dtype="uint8").astype(bool)


def _dist_m(mask: np.ndarray, px_m: float) -> np.ndarray:
    """Metres from every pixel to the nearest True pixel (inf when there is none)."""
    if not mask.any():
        return np.full(mask.shape, np.inf, dtype="float32")
    return (ndimage.distance_transform_edt(~mask) * px_m).astype("float32")


# --------------------------------------------------------------------------------------
# Reading composites, and the context layers (roads, buildings, cropland)
# --------------------------------------------------------------------------------------
def read_window(comp_idx, bbox4326, pad_m: float = READ_PAD_M):
    """`(dn, transform, crs)` over `bbox4326` padded by `pad_m`, mosaicked from every
    composite tile that shares the CRS of the tile at the bbox centre. `CompositeIndex.
    read_window` merges whatever it finds, which across a UTM-zone boundary would merge
    two projections; a pixel detector also needs the pad, for its local medians."""
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds

    from earthpv.local_source import _snap_bounds

    w, s, e, n = bbox4326
    cx, cy = (w + e) / 2, (s + n) / 2
    idx = comp_idx.index
    home = idx[idx.contains(Point(cx, cy))]
    if home.empty:
        home = idx[idx.intersects(shapely_box(*bbox4326))]
        if home.empty:
            return None
    crs = home.iloc[0]["crs"]
    dlat = pad_m / 111_320.0
    dlon = pad_m / (111_320.0 * max(np.cos(np.radians(cy)), 0.1))
    padded = (w - dlon, s - dlat, e + dlon, n + dlat)
    hits = idx[idx.intersects(shapely_box(*padded)) & (idx["crs"] == crs)]
    srcs = [rasterio.open(p) for p in hits.path]
    try:
        wb = _snap_bounds(transform_bounds("EPSG:4326", crs, *padded), srcs[0].transform)
        arr, tr = merge(srcs, bounds=wb, nodata=0)
        out_crs = srcs[0].crs
    finally:
        for s_ in srcs:
            s_.close()
    return arr, tr, out_crs


def paved_roads_by_chunk(chunks, cache_dir: Path, retries: int = 3) -> tuple[gpd.GeoDataFrame, set]:
    """Paved roads over 1-degree `chunks`, one cached file per chunk, so a run that covers
    part of a country never leaves a cache that looks complete for the rest of it.
    Returns `(roads, failed chunks)`; blobs under a failed chunk keep the road veto off and
    say so (`road_checked`)."""
    cache_dir = Path(cache_dir)
    parts, failed = [], set()
    for ch in chunks:
        f = cache_dir / f"{ch[0]:+07.2f}_{ch[1]:+06.2f}.parquet"
        if not f.exists():
            got = fetch_paved_roads([ch], cache=f, retries=retries)
            if got is None:
                failed.add(tuple(ch))
                continue
        parts.append(gpd.read_parquet(f))
    parts = [p for p in parts if len(p)]
    roads = (gpd.GeoDataFrame(pd.concat(parts, ignore_index=True).drop_duplicates("id"), crs="EPSG:4326")
             if parts else gpd.GeoDataFrame(columns=["id", "highway", "surface"], geometry=[], crs="EPSG:4326"))
    return roads, failed


def fetch_paved_roads(bboxes, cache: Path | None = None, retries: int = 3) -> gpd.GeoDataFrame | None:
    """OSM motorway..tertiary and asphalt/paved ways over every bbox in `bboxes`, cached.
    None when Overpass cannot be reached: the road veto is then off, and says so."""
    from earthpv.roads import fetch_roads_overpass

    if cache is not None and Path(cache).exists():
        return gpd.read_parquet(cache)
    parts = []
    for bb in bboxes:
        for attempt in range(retries):
            try:
                parts.append(fetch_roads_overpass(tuple(bb), timeout=180))
                break
            except Exception as e:  # noqa: BLE001 -- every mirror failed; retried, then None
                log.warning("roads %s attempt %d failed: %s", bb, attempt + 1, e)
                time.sleep(20 * (attempt + 1))
        else:
            log.warning("road veto OFF: no Overpass response for %s", bb)
            return None
    roads = (pd.concat(parts, ignore_index=True).drop_duplicates("id") if parts
             else gpd.GeoDataFrame(columns=["id", "highway", "surface"], geometry=[], crs="EPSG:4326"))
    roads = gpd.GeoDataFrame(roads, geometry="geometry", crs="EPSG:4326")
    if cache is not None:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        roads.to_parquet(cache)
    return roads


class _WorldCover:
    """WorldCover tile index for one run, re-signed every `WC_TOKEN_S` so a national pass
    does not outlive its Planetary Computer tokens (the failure CLAUDE.md records for
    compose and glint). Disabled for the rest of the run after a failure."""

    def __init__(self, bbox4326, enabled: bool = True):
        self.bbox, self.enabled, self.tiles, self.t = bbox4326, enabled, None, 0.0

    def mask(self, bbox4326, out_shape, transform, crs) -> np.ndarray | None:
        from earthpv import worldcover

        if not self.enabled:
            return None
        if self.tiles is None or time.time() - self.t > WC_TOKEN_S:
            try:
                self.tiles, self.t = worldcover._tile_index(self.bbox), time.time()
            except Exception as e:  # noqa: BLE001
                log.warning("WorldCover off for this run: %s", e)
                self.enabled = False
                return None
        tiles = self.tiles[self.tiles.intersects(shapely_box(*bbox4326))]
        if tiles.empty:
            return None
        from rasterio.warp import Resampling, reproject

        out = np.zeros(out_shape, dtype="uint8")
        for path in tiles.path:
            try:
                with rasterio.open(path) as src:
                    tmp = np.zeros(out_shape, dtype="uint8")
                    reproject(rasterio.band(src, 1), tmp, dst_transform=transform, dst_crs=crs,
                              resampling=Resampling.nearest)
            except Exception as e:  # noqa: BLE001
                log.warning("WorldCover read failed (%s); cropland anchor skipped here", e)
                return None
            out = np.where(out == 0, tmp, out)
        return out == worldcover.CROPLAND


def context_masks(bbox4326, out_shape, transform, crs, ndvi, iso3: str | None, roads, wc: _WorldCover | None,
                  con=None) -> tuple[np.ndarray | None, np.ndarray, dict]:
    """`(road, roi, info)`: paved-road buffer (None if roads unavailable) and the ROI
    (within `ROI_RADIUS_M` of a building, cropland or green pixel)."""
    from earthpv.buildings import fetch_vida_buildings

    px = abs(transform.a)
    info = {}
    road = None
    if roads is not None:
        sub = roads[roads.intersects(shapely_box(*bbox4326))]
        road = _mask(sub.to_crs(crs).buffer(ROAD_HALF_WIDTH_M), out_shape, transform, all_touched=False)
    anchor = np.nan_to_num(ndvi, nan=0.0) >= GREEN_NDVI
    info["green"] = True
    if iso3:
        try:
            bu = fetch_vida_buildings(bbox4326, iso3, con=con)
            anchor |= _mask(bu.to_crs(crs).geometry, out_shape, transform)
            info["buildings"] = True
        except Exception as e:  # noqa: BLE001 -- no local VIDA for this country
            log.warning("buildings anchor skipped: %s", e)
    crop = wc.mask(bbox4326, out_shape, transform, crs) if wc is not None else None
    if crop is not None:
        anchor |= crop
        info["cropland"] = True
    info["crop_mask"] = crop
    return road, _dist_m(anchor, px) <= ROI_RADIUS_M, info


# --------------------------------------------------------------------------------------
# Blobs
# --------------------------------------------------------------------------------------
BLOB_COLUMNS = ["n_px", "area_m2", "s_max", "s_mean", "swir_contrast", "road_frac", "in_roi",
                "road_veto", "water_veto"]


def extract_blobs(prob, threshold: float, domain, transform, crs, b11, road=None, roi=None,
                  exclude_ring=None) -> tuple[gpd.GeoDataFrame, np.ndarray]:
    """8-connected blobs of `prob >= threshold` (a logit, `score_pixels`) inside `domain`,
    with the veto inputs.
    Returns `(blobs in EPSG:4326, label raster)`; the raster's ids are row index + 1."""
    m = (np.nan_to_num(prob, nan=0.0) >= threshold) & domain
    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    if n == 0:
        return gpd.GeoDataFrame(columns=BLOB_COLUMNS, geometry=[], crs="EPSG:4326"), lab
    ids = np.arange(1, n + 1)
    n_px = np.bincount(lab.ravel(), minlength=n + 1)[1:]
    px_area = abs(transform.a * transform.e)
    grown = ndimage.grey_dilation(lab, footprint=np.ones((9, 9)))
    near = ndimage.grey_dilation(lab, footprint=np.ones((3, 3)))
    ring = (grown > 0) & (near == 0) & ~m
    if exclude_ring is not None:
        ring &= ~exclude_ring
    ring_med = ndimage.median(b11, np.where(ring, grown, 0), ids)
    swir = ndimage.mean(b11, lab, ids) / np.where(np.asarray(ring_med) > 0, ring_med, np.nan) - 1
    road_frac = ndimage.mean(road, lab, ids) if road is not None else np.zeros(n)
    in_roi = (ndimage.maximum(roi, lab, ids) > 0) if roi is not None else np.ones(n, dtype=bool)
    geoms = {}
    for geom, val in rasterio.features.shapes(lab.astype("int32"), mask=lab > 0, transform=transform,
                                              connectivity=8):
        geoms.setdefault(int(val), []).append(shape(geom))
    from shapely.ops import unary_union

    polys = [unary_union(geoms[i]) if len(geoms[i]) > 1 else geoms[i][0] for i in ids]
    df = gpd.GeoDataFrame({
        "n_px": n_px, "area_m2": n_px * px_area,
        "s_max": ndimage.maximum(prob, lab, ids), "s_mean": ndimage.mean(prob, lab, ids),
        "swir_contrast": np.asarray(swir, dtype=float), "road_frac": np.asarray(road_frac, dtype=float),
        "in_roi": np.asarray(in_roi, dtype=bool),
    }, geometry=polys, crs=crs)
    df["road_veto"] = df["road_frac"] >= ROAD_VETO_FRAC
    df["water_veto"] = df["swir_contrast"] < SWIR_VETO
    return df.to_crs("EPSG:4326"), lab


def kept(blobs: pd.DataFrame, max_blob_m2: float | None = MAX_BLOB_M2) -> np.ndarray:
    """Blobs that survive the road and water vetoes, lie in the ROI and under the cap."""
    k = ~blobs["road_veto"].to_numpy(bool) & ~blobs["water_veto"].to_numpy(bool) & blobs["in_roi"].to_numpy(bool)
    if max_blob_m2 is not None:
        k &= blobs["area_m2"].to_numpy(float) <= max_blob_m2
    return k


# --------------------------------------------------------------------------------------
# Training areas
# --------------------------------------------------------------------------------------
@dataclass
class Area:
    name: str
    kind: str                       # "clean" | "weak"
    boundary: BaseGeometry          # EPSG:4326
    labels: gpd.GeoDataFrame        # EPSG:4326, polygons and points
    source: str
    group: str = ""                 # areas cut from one region; transfer leaves a group out


def panel_area_factor(labels: gpd.GeoDataFrame, aoi: str | None = None) -> np.ndarray:
    """Per polygon of `labels`, the share of its area that is panels, from what its OSM tag
    says it outlines. A `power=generator` polygon is the array (1.0), and so is any polygon
    a mapper the AOI names in `osm_panel_tracers` drew (`labels.panel_traced`), whatever
    its tag. A `power=plant` polygon is the site, priced at the land constant like every
    mapped ground outline in the atlas's Verified tier (owner decision 2026-10-24, for
    Tihama's UNGSC rectangles), so `DEFAULT_KWP_PER_M2_LAND / DEFAULT_KWP_PER_M2_MODULE` of
    it is panels -- or none of it when a generator inside it already carries its panels.
    Labels without a `kind` column are all arrays, which is what every clean area held
    before this rule.

    Measured on Tihama: where the detector finds a rectangle its blob covers 21% of it,
    against 49% of an owner-traced array (median per feature), which puts a rectangle's
    panels near 0.43 of it; the land constant says 0.28, its 90% interval 0.19-0.42."""
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_LAND, DEFAULT_KWP_PER_M2_MODULE
    from earthpv.labels import panel_traced

    poly = labels[labels.geom_type.isin(["Polygon", "MultiPolygon"])]
    if "kind" not in poly.columns:
        return np.ones(len(poly))
    outline = poly["kind"].isin(OUTLINE_KINDS).to_numpy() & ~panel_traced(poly, aoi)
    fac = np.where(outline, DEFAULT_KWP_PER_M2_LAND / DEFAULT_KWP_PER_M2_MODULE, 1.0)
    if outline.any() and (~outline).any():
        has_array = gpd.sjoin(poly[outline][["geometry"]], poly[~outline][["geometry"]].representative_point()
                              .to_frame("geometry"), predicate="contains").index.unique()
        fac[np.flatnonzero(outline)[np.isin(poly.index[outline], has_array)]] = 0.0
    return fac


def _area_labels(name: str, boundary: BaseGeometry, cache_dir: Path, osm: Path | None,
                 refresh: bool) -> tuple[gpd.GeoDataFrame, str]:
    """OSM solar inside `boundary`: from `osm` if given, else a live Overpass pull cached
    as `<cache_dir>/<name>_solar.parquet` (kept out of data/labels/, whose AOI-agnostic
    `*_overpass_solar.parquet` glob in `export.load_mapped_reference_attrs` would pick a
    region file up)."""
    from earthpv.overpass import fetch_solar_overpass

    if osm is not None:
        g, src = gpd.read_parquet(osm).to_crs("EPSG:4326"), str(osm)
    else:
        cache = Path(cache_dir) / f"{name}_solar.parquet"
        if cache.exists() and not refresh:
            g, src = gpd.read_parquet(cache), str(cache)
        else:
            g = None
            for attempt in range(4):
                try:
                    g = fetch_solar_overpass(bbox=boundary.bounds)
                    if len(g):
                        break
                except Exception as e:  # noqa: BLE001
                    log.warning("Overpass for %s attempt %d: %s", name, attempt + 1, e)
                time.sleep(20 * (attempt + 1))
            if g is None or g.empty:
                raise RuntimeError(f"{name}: no OSM solar returned; an empty pull is not an empty area")
            cache.parent.mkdir(parents=True, exist_ok=True)
            g.to_parquet(cache)
            src = f"Overpass {time.strftime('%Y-%m-%d')} -> {cache}"
    g = g[g.intersects(boundary)].reset_index(drop=True)
    return g, src


def load_areas(labels_dir: Path, cache_dir: Path, clean_regions=(), weak_regions=(),
               osm: Path | None = None, refresh: bool = False) -> list[Area]:
    """Farm quadrats under `labels_dir` (clean), plus boundary files passed as clean or
    weak regions, each with its OSM solar. A quadrat keeps its nodes (`roofclf.load_quadrat`
    drops them, and a node left out makes its PV a negative) and takes its group from the
    boundary's `region` property, so areas cut from one mapped region are left out together
    when transfer is measured."""
    out = []
    for stem in roofclf.discover_quadrats(Path(labels_dir), farm=True):
        bpath = Path(labels_dir) / f"{stem}_boundary.geojson"
        b = roofclf.load_boundary(bpath)
        solar = roofclf._newest_solar(stem, Path(labels_dir))
        if solar is None:
            raise FileNotFoundError(f"farm quadrat {stem} has no *_overpass_solar parquet")
        pv = gpd.read_parquet(solar).to_crs("EPSG:4326")
        pv = pv[pv.geom_type.isin(["Polygon", "MultiPolygon", "Point", "MultiPoint"])].reset_index(drop=True)
        region = gpd.read_file(bpath).iloc[0].get("region") or stem
        out.append(Area(roofclf.quadrat_label(stem), "clean", b, pv, f"farm quadrat {stem}", region))
    for kind, paths in (("clean", clean_regions), ("weak", weak_regions)):
        for p in paths:
            b = roofclf.load_boundary(Path(p))
            name = Path(p).name.replace("_boundary.geojson", "").replace(".geojson", "")
            labels, src = _area_labels(name, b, cache_dir, osm, refresh)
            props = gpd.read_file(p).iloc[0]
            out.append(Area(name, kind, b, labels, src, props.get("region") or name))
    if not out:
        raise ValueError(f"no training areas: no farm quadrats under {labels_dir} and no regions given")
    return out


def _strips(domain: np.ndarray, k: int) -> np.ndarray:
    """`k` strips across the longer side of `domain`'s extent, -1 outside it."""
    rows, cols = np.nonzero(domain)
    rr, cc = np.indices(domain.shape)
    if (cols.max() - cols.min()) >= (rows.max() - rows.min()):
        b = (cc - cols.min()) * k // (cols.max() - cols.min() + 1)
    else:
        b = (rr - rows.min()) * k // (rows.max() - rows.min() + 1)
    return np.where(domain, np.clip(b, 0, k - 1), -1)


def prepare_area(a: Area, comp_idx, iso3, roads, wc, rng, con=None, aoi: str | None = None) -> dict | None:
    """Features, label masks and context for one area, in its composite's grid."""
    res = read_window(comp_idx, a.boundary.bounds, pad_m=READ_PAD_M)
    if res is None:
        log.warning("%s: no composite coverage, skipped", a.name)
        return None
    dn, tr, crs = res
    valid = (dn > 0).all(0)
    shp = valid.shape
    domain = valid & _mask([gpd.GeoSeries([a.boundary], crs=4326).to_crs(crs).iloc[0]], shp, tr, all_touched=False)
    if not domain.any():
        log.warning("%s: no valid composite pixel inside the boundary, skipped", a.name)
        return None
    refl = dn.astype("float32") / REFL_SCALE
    X = pixel_features(refl, valid)
    px = abs(tr.a)
    lab = a.labels.to_crs(crs)
    polys = lab[lab.geom_type.isin(["Polygon", "MultiPolygon"])]
    pts = lab[lab.geom_type.isin(["Point", "MultiPoint"])]
    bbox = tuple(gpd.GeoSeries([shapely_box(*tr * (0, shp[0]), *tr * (shp[1], 0))], crs=crs).to_crs(4326).total_bounds)
    road, roi, ctx = context_masks(bbox, shp, tr, crs, X[..., FEATURES.index("ndvi")], iso3, roads, wc, con=con)
    crop = ctx.pop("crop_mask", None)
    d_crop = float(crop[domain].mean()) if crop is not None else float("nan")
    d_bldg = float("nan")
    if iso3:
        from earthpv.buildings import fetch_vida_buildings
        from earthpv.labels import geodesic_area_m2

        bu = fetch_vida_buildings(a.boundary.bounds, iso3, con=con)
        n_in = int(bu.geometry.representative_point().within(a.boundary).sum()) if len(bu) else 0
        d_bldg = n_in / (geodesic_area_m2(a.boundary) / 1e6)
    d = {"area": a, "X": X, "domain": domain, "transform": tr, "crs": crs, "b11": refl[8], "road": road,
         "crop_frac": d_crop, "bldg_density_km2": d_bldg, "elev_m": area_elevation(a.boundary),
         "roi": roi, "context": ctx, "block": _strips(domain, N_BLOCKS), "px": px}
    if a.kind == "clean":
        # Traced arrays are pixel positives; outlines and nodes are bags, like a weak area's
        # labels, but the area is complete, so negatives come as close as a clean area's.
        fac = panel_area_factor(polys, aoi)
        traced, outline = fac == 1.0, (fac > 0) & (fac < 1.0)
        cov = pv_cover(polys.geometry[traced], shp, tr)
        bag_geoms = list(polys.geometry[outline]) + list(pts.buffer(NODE_BAG_RADIUS_M))
        dist = _dist_m((cov > 0) | _mask(list(polys.geometry[~traced]) + bag_geoms, shp, tr), px)
        arrays = polys[fac > 0].reset_index(drop=True)
        d.update(pos=(cov >= POSITIVE_COVER) & domain, neg=(dist > CLEAN_NEG_BUFFER_M) & domain, dist=dist,
                 arrays=arrays, array_px=[np.flatnonzero(_mask([g], shp, tr).ravel()) for g in arrays.geometry],
                 array_area=np.array([abs(g.area) for g in arrays.geometry]) * fac[fac > 0],
                 array_outline=fac[fac > 0] < 1.0, n_nodes=len(pts))
        null_buffer = CLEAN_NEG_BUFFER_M
    else:
        bag_geoms = list(polys.geometry) + list(pts.buffer(NODE_BAG_RADIUS_M))
        dist = _dist_m(_mask(bag_geoms, shp, tr), px)
        d.update(neg=(dist > WEAK_NEG_BUFFER_M) & domain, dist=dist)
        null_buffer = WEAK_NEG_BUFFER_M
    bags = [np.flatnonzero((_mask([g], shp, tr) & domain).ravel()) for g in bag_geoms]
    keep = [i for i, b in enumerate(bags) if len(b)]
    bags = [bags[i] for i in keep]
    bag_geoms = [bag_geoms[i] for i in keep]
    nulls = []
    from shapely.affinity import translate

    for g in bag_geoms:
        for _ in range(50):
            r, ang = rng.uniform(*SHIFT_M), rng.uniform(0, 2 * np.pi)
            m = _mask([translate(g, r * np.cos(ang), r * np.sin(ang))], shp, tr)
            if m.any() and domain[m].all() and dist[m].min() >= null_buffer:
                nulls.append(np.flatnonzero(m.ravel()))
                break
        else:
            nulls.append(None)
    d.update(bags=bags, nulls=nulls)
    return d


# --------------------------------------------------------------------------------------
# Fitting (multiple-instance for weak areas)
# --------------------------------------------------------------------------------------
def _flat(d):
    return d["X"].reshape(-1, d["X"].shape[-1])


def mil_fit(data: list[dict], train_block, rng, l2: float = L2) -> dict:
    """One model from every area's training pixels. `train_block(d)` is a boolean pixel
    mask of what this fit may see. Clean positives are fixed; each weak bag contributes
    its `MIL_K` highest-scoring pixels, re-chosen after every refit (SPPI first), and so
    does every outline or node in a clean area."""
    clean_pos, negs, weak = [], [], []
    for d in data:
        tm = train_block(d)
        Xf = _flat(d)
        ni = np.flatnonzero((d["neg"] & tm).ravel())
        if len(ni):
            negs.append(Xf[rng.choice(ni, min(NEG_SAMPLE, len(ni)), replace=False)])
        if "pos" in d:
            pi = np.flatnonzero((d["pos"] & tm).ravel())
            if len(pi):
                clean_pos.append(Xf[pi])
        tmf = tm.ravel()
        weak += [(Xf, b) for b in d["bags"] if tmf[b].mean() > 0.5]
    if not negs or (not clean_pos and not weak):
        raise ValueError("a fold has no positives or no negatives")
    sppi = FEATURES.index("sppi")
    scores = [Xf[b, sppi] for Xf, b in weak]
    model = None
    for _ in range(MIL_ITERS if weak else 1):
        wp = [Xf[b[np.argsort(np.nan_to_num(s, nan=-np.inf))[-MIL_K:]]] for (Xf, b), s in zip(weak, scores)]
        P = np.vstack(clean_pos + wp)
        N = np.vstack(negs)
        P, N = P[np.isfinite(P).all(1)], N[np.isfinite(N).all(1)]
        y = np.r_[np.ones(len(P)), np.zeros(len(N))]
        # Balanced: the base rate is set by how many negatives were sampled, not by the
        # land, so it carries no information worth fitting.
        sw = np.where(y == 1, len(N) / max(len(P), 1), 1.0)
        model = roofclf.fit_logistic(np.vstack([P, N]).astype("float64"), y, l2=l2, sample_weight=sw)
        scores = [logit(model, np.nan_to_num(Xf[b]).astype("float64")) for Xf, b in weak]
    return model


def _objects(d, prob, thr, max_blob_m2):
    """Kept blobs of one area at `thr`: (blobs, label raster, kept mask)."""
    excl = (d["dist"] == 0) if "dist" in d else None
    blobs, lab = extract_blobs(prob, thr, d["domain"], d["transform"], d["crs"], d["b11"], d["road"], d["roi"],
                               exclude_ring=excl)
    return blobs, lab, kept(blobs, max_blob_m2) if len(blobs) else np.zeros(0, dtype=bool)


def _clean_object_stats(d, prob, thr, max_blob_m2):
    blobs, lab, k = _objects(d, prob, thr, max_blob_m2)
    n = int(k.sum())
    if n:
        ids = np.flatnonzero(k) + 1
        on = ndimage.minimum(d["dist"], lab, ids) <= ON_MAPPED_M
        kl = np.isin(lab, ids).ravel()
        found = np.array([kl[p].any() for p in d["array_px"]]) if len(d["array_px"]) else np.zeros(0, bool)
        det_area = float(blobs["area_m2"].to_numpy()[k].sum())
    else:
        on, found, det_area = np.zeros(0, bool), np.zeros(len(d["array_px"]), bool), 0.0
    return {"blobs": n, "on_mapped": int(on.sum()), "found": found, "det_area_m2": det_area,
            "blob_area": blobs["area_m2"].to_numpy()[k] if n else np.zeros(0),
            "lab": lab, "kept_ids": np.flatnonzero(k) + 1 if n else np.zeros(0, int)}


def _bag_auc(d, prob):
    p = prob.ravel()
    ok = [i for i, nb in enumerate(d["nulls"]) if nb is not None]
    if len(ok) < 10:
        return float("nan")
    s1 = [np.nanmax(p[d["bags"][i]]) for i in ok]
    s0 = [np.nanmax(p[d["nulls"][i]]) for i in ok]
    return roofclf.auc(np.r_[np.ones(len(s1)), np.zeros(len(s0))], np.nan_to_num(np.r_[s1, s0], nan=-1))


def train_ground(
    aoi: str, labels_dir: Path, composites: Path, out_dir: Path, clean_regions=(), weak_regions=(),
    osm: Path | None = None, refresh_osm: bool = False, l2: float = L2, use_worldcover: bool = True,
    max_array_m2: float | None = MAX_ARRAY_M2, max_blob_m2: float | None = MAX_BLOB_M2,
    target_precision: float = TARGET_PRECISION,
) -> dict:
    """Fit, evaluate and calibrate the ground detector; write `out_dir`:

    - `model_full.json`: one fit on every area (roofclf's model format plus the detector's
      deployment threshold, a logit, and settings), what `score_ground_national` deploys;
    - `eval_areas.csv`: per area, leave-one-block-out pixel AUC (clean) or bag AUC (weak),
      and the leave-one-AREA-out transfer figures when there is more than one area;
    - `eval_objects.csv`: pooled precision/recall of kept blobs over a threshold ladder,
      clean areas only, from held-out scores;
    - `calibration.csv`: per clean area and block, detected blob area and mapped PV area
      at the deployment threshold, which `ground_capacity` turns into its ratio;
    - `summary.json`.
    """
    from earthpv import overture
    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    from earthpv.local_source import composite_index

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(BOOT_SEED)
    _, cfg = resolve_aoi(aoi, Settings.load())
    iso3 = _iso3_for(cfg)
    areas = load_areas(labels_dir, out_dir / "areas", clean_regions, weak_regions, osm, refresh_osm)
    comp_idx = composite_index(str(composites))
    con = overture.connect()
    data = []
    for a in areas:
        roads = fetch_paved_roads([a.boundary.bounds], cache=out_dir / "areas" / f"{a.name}_roads.parquet")
        wc = _WorldCover(a.boundary.bounds, enabled=use_worldcover)
        d = prepare_area(a, comp_idx, iso3, roads, wc, rng, con=con, aoi=aoi)
        if d is not None:
            data.append(d)
            log.info("%s (%s): %d px, %s", a.name, a.kind, int(d["domain"].sum()),
                     (f"{int(d['pos'].sum())} positive px, {len(d['arrays'])} arrays "
                      f"({int(d['array_outline'].sum())} outlines), " if a.kind == "clean" else "")
                     + f"{len(d['bags'])} bags")
    clean = [d for d in data if d["area"].kind == "clean"]

    # Leave-one-block-out: fold f holds out strip f of EVERY area, so each area is scored
    # by a model that saw the rest of it and all the other areas.
    held = [np.full(d["domain"].shape, np.nan, dtype="float32") for d in data]
    for f in range(N_BLOCKS):
        model = mil_fit(data, lambda d, f=f: (d["block"] >= 0) & (d["block"] != f), rng, l2)
        for d, h in zip(data, held):
            te = d["block"] == f
            h[te] = score_pixels(model, d["X"], te)[te]

    rows = []
    for d, h in zip(data, held):
        r = {"area": d["area"].name, "kind": d["area"].kind, "group": d["area"].group,
             "source": d["area"].source,
             "context": "+".join(k for k in ("green", "buildings", "cropland") if d["context"].get(k)),
             "road_veto": d["road"] is not None}
        if d["area"].kind == "clean":
            pos, neg = d["pos"], d["neg"]
            r.update(n_arrays=len(d["arrays"]), n_outlines=int(d["array_outline"].sum()), n_nodes=d["n_nodes"],
                     pixel_auc_lobo=roofclf.auc(np.r_[np.ones(pos.sum()), np.zeros(neg.sum())],
                                                np.r_[h[pos], h[neg]]) if pos.any() else float("nan"))
        r.update(n_bags=len(d["bags"]), bag_auc_lobo=_bag_auc(d, h))
        rows.append(r)

    # Deployment threshold: the lowest probability at which the clean areas' pooled
    # held-out blobs reach `target_precision` -- the most recall the target allows.
    ladder = []
    thr = None
    if clean:
        pooled = np.concatenate([h[d["domain"]] for d, h in zip(data, held) if d["area"].kind == "clean"])
        for q in (0.95, 0.97, 0.98, 0.99, 0.993, 0.995, 0.996, 0.997, 0.9975, 0.998, 0.9985, 0.999,
                  0.9993, 0.9995, 0.9998):
            t = float(np.nanquantile(pooled, q))
            st = [_clean_object_stats(d, h, t, max_blob_m2) for d, h in zip(data, held) if d["area"].kind == "clean"]
            nb, on = sum(s["blobs"] for s in st), sum(s["on_mapped"] for s in st)
            found = np.concatenate([s["found"] for s in st])
            ladder.append({"quantile": q, "threshold": t, "blobs": nb, "on_mapped": on,
                           "precision": on / nb if nb else float("nan"),
                           "array_recall": float(found.mean()) if len(found) else float("nan")})
        lad = pd.DataFrame(ladder)
        ok = lad[lad.precision >= target_precision]
        thr = float(ok.threshold.min()) if len(ok) else float(lad.threshold.max())
        if not len(ok):
            log.warning("no threshold reaches precision %.2f on the clean areas; using the strictest", target_precision)
        lad.to_csv(out_dir / "eval_objects.csv", index=False)
    else:
        log.warning("no clean area: precision, the deployment threshold and the capacity "
                    "calibration cannot be measured; pass --threshold to score nationally")

    # Capacity calibration, per clean area and block, at the deployment threshold.
    calib = []
    if thr is not None:
        for d, h in zip(data, held):
            if d["area"].kind != "clean":
                continue
            st = _clean_object_stats(d, h, thr, max_blob_m2)
            small = np.ones(len(d["array_area"]), bool) if max_array_m2 is None else d["array_area"] < max_array_m2
            cen = d["arrays"].geometry.representative_point()
            rr, cc = rasterio.transform.rowcol(d["transform"], cen.x.to_numpy(), cen.y.to_numpy())
            rr, cc = np.clip(rr, 0, d["block"].shape[0] - 1), np.clip(cc, 0, d["block"].shape[1] - 1)
            ablock = d["block"][rr, cc]
            ids = st["kept_ids"]
            # A blob's block is the one most of its pixels sit in.
            blob_block = (np.round(np.asarray(ndimage.median(d["block"], st["lab"], ids))).astype(int)
                          if len(ids) else np.zeros(0, int))
            for b in [None, *range(N_BLOCKS)]:
                sel = (ablock >= 0) if b is None else (ablock == b)
                det = st["det_area_m2"] if b is None else float(st["blob_area"][blob_block == b].sum())
                calib.append({"area": d["area"].name, "group": d["area"].group,
                              "block": "all" if b is None else int(b),
                              "crop_frac": d["crop_frac"], "bldg_density_km2": d["bldg_density_km2"],
                              "elev_m": d["elev_m"], "det_area_m2": det, "true_area_m2": float(d["array_area"][sel & small].sum()),
                              "true_area_outline_m2": float(d["array_area"][sel & small & d["array_outline"]].sum()),
                              "true_area_all_m2": float(d["array_area"][sel].sum()),
                              "n_arrays": int((sel & small).sum()), "recall": float(st["found"][sel & small].mean())
                              if (sel & small).any() else float("nan")})
        pd.DataFrame(calib).to_csv(out_dir / "calibration.csv", index=False)

    # Transfer: leave one REGION out (areas cut from one mapped region share a group, and a
    # neighbouring piece of the same farmland is no test). What a new country should expect.
    groups = list(dict.fromkeys(d["area"].group for d in data))
    models = {}
    if len(groups) > 1:
        for g in groups:
            try:
                models[g] = mil_fit([o for o in data if o["area"].group != g], lambda o: o["block"] >= 0, rng, l2)
            except ValueError as e:
                log.warning("transfer to %s not measurable: %s", g, e)
    if models:
        for d, r in zip(data, rows):
            m = models.get(d["area"].group)
            if m is None:
                continue
            p = score_pixels(m, d["X"], d["domain"])
            if d["area"].kind == "clean":
                pos, neg = d["pos"], d["neg"]
                r["pixel_auc_transfer"] = roofclf.auc(np.r_[np.ones(pos.sum()), np.zeros(neg.sum())],
                                                      np.r_[p[pos], p[neg]]) if pos.any() else float("nan")
                if thr is not None:
                    st = _clean_object_stats(d, p, thr, max_blob_m2)
                    r["precision_transfer"] = st["on_mapped"] / st["blobs"] if st["blobs"] else float("nan")
                    r["recall_transfer"] = float(st["found"].mean()) if len(st["found"]) else float("nan")
            r["bag_auc_transfer"] = _bag_auc(d, p)
    pd.DataFrame(rows).to_csv(out_dir / "eval_areas.csv", index=False)

    full = mil_fit(data, lambda d: d["block"] >= 0, rng, l2)
    payload = {
        "w": full["w"].tolist(), "mu": full["mu"].tolist(), "sd": full["sd"].tolist(),
        "converged": full["converged"], "features": FEATURES, "detector": DETECTOR,
        "threshold": thr, "target_precision": target_precision, "max_array_m2": max_array_m2,
        "max_blob_m2": max_blob_m2, "road_veto_frac": ROAD_VETO_FRAC, "swir_veto": SWIR_VETO,
        "roi_radius_m": ROI_RADIUS_M, "areas": [{"name": d["area"].name, "kind": d["area"].kind,
                                                "group": d["area"].group, "source": d["area"].source}
                                               for d in data],
    }
    (out_dir / "model_full.json").write_text(json.dumps(payload, indent=2))
    summary = {"aoi": aoi, "fingerprint": roofclf.model_fingerprint(full, FEATURES), "threshold": thr,
               "areas": rows, "objects": ladder, "calibration": calib}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    return summary


def load_ground_model(path: Path) -> tuple[dict, list[str], dict]:
    model, feats = roofclf.load_model(path)
    meta = json.loads(Path(path).read_text())
    if meta.get("detector") not in (DETECTOR, *LEGACY_DETECTORS):
        raise ValueError(f"{path} is not a {DETECTOR} model")
    if list(feats) != FEATURES:
        raise ValueError(f"{path} was fitted on features this code no longer computes")
    return model, feats, meta


# --------------------------------------------------------------------------------------
# National scoring
# --------------------------------------------------------------------------------------
def score_ground_national(
    aoi: str, model_path: Path, composites: Path, out_dir: Path, threshold: float | None = None,
    use_worldcover: bool = True, limit: int = 0, cells: set[str] | None = None, force: bool = False,
) -> Path:
    """Blobs of every canonical cell, one parquet per cell, with every veto input kept so
    `ground_capacity` decides what counts. Resumable like `roofclf.score_buildings_national`
    (a written cell is skipped unless `force`); a blob belongs to the cell holding its
    representative point, so a blob straddling an edge is written once.

    The road veto is NOT applied here: it is a vector overlap `ground_capacity` computes on
    the blobs, so a national pass never waits on Overpass (measured 2026-10-23: one 1-degree
    road chunk in twenty minutes while the mirrors returned 502s)."""
    from earthpv import overture
    from earthpv.buildings import _iso3_for
    from earthpv.compose import CELL_DEG
    from earthpv.config import Settings
    from earthpv.density import _grid_origin
    from earthpv.labels import resolve_aoi
    from earthpv.local_source import composite_index

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    model, feats, meta = load_ground_model(model_path)
    thr = threshold if threshold is not None else meta.get("threshold")
    if thr is None:
        raise ValueError(f"{model_path} carries no deployment threshold (no clean area); pass --threshold")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    iso3 = _iso3_for(cfg)
    comp_idx = composite_index(str(composites))
    manifest = roofclf.canonical_composite_manifest(comp_idx, _grid_origin(aoi, cfg, settings), CELL_DEG)
    if cells is not None:
        manifest = manifest[manifest.cell.isin(cells)]
    if limit:
        manifest = manifest.head(limit)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    w0, s0 = manifest.lon0.min(), manifest.lat0.min()
    e0, n0 = manifest.lon0.max() + CELL_DEG, manifest.lat0.max() + CELL_DEG
    wc = _WorldCover((w0, s0, e0, n0), enabled=use_worldcover)
    (out_dir / "_model.json").write_text(json.dumps({
        "fingerprint": roofclf.model_fingerprint(model, feats), "features": list(feats), "aoi": aoi,
        "composites": str(composites), "threshold": thr, "detector": DETECTOR,
        "worldcover": use_worldcover,
    }, indent=2))
    con = overture.connect()
    n_done, n_blobs = 0, 0
    t0 = time.time()
    for m in manifest.itertuples():
        out_path = out_dir / f"{m.cell}.parquet"
        if out_path.exists() and not force:
            continue
        bbox = (m.lon0, m.lat0, m.lon0 + CELL_DEG, m.lat0 + CELL_DEG)
        res = read_window(comp_idx, bbox)
        if res is None:
            continue
        dn, tr, crs = res
        valid = (dn > 0).all(0)
        refl = dn.astype("float32") / REFL_SCALE
        X = pixel_features(refl, valid)
        prob = score_pixels(model, X, valid)
        pb = tuple(gpd.GeoSeries([shapely_box(*tr * (0, valid.shape[0]), *tr * (valid.shape[1], 0))], crs=crs)
                   .to_crs(4326).total_bounds)
        _, roi, ctx = context_masks(pb, valid.shape, tr, crs, X[..., FEATURES.index("ndvi")], iso3, None,
                                    wc, con=con)
        blobs, _ = extract_blobs(prob, thr, valid, tr, crs, refl[8], None, roi)
        if len(blobs):
            rp = blobs.geometry.representative_point()
            blobs = blobs[rp.within(shapely_box(*bbox)).to_numpy()].reset_index(drop=True)
        blobs.insert(0, "cell", m.cell)
        blobs["context"] = "+".join(k for k in ("green", "buildings", "cropland") if ctx.get(k))
        blobs["road_checked"] = False
        blobs.to_parquet(out_path)
        n_done += 1
        n_blobs += len(blobs)
        if n_done % 25 == 0:
            log.info("%d cells, %d blobs, %.1f s/cell", n_done, n_blobs, (time.time() - t0) / n_done)
    log.info("done: %d cells scored this run, %d blobs -> %s", n_done, n_blobs, out_dir)
    return out_dir


# --------------------------------------------------------------------------------------
# Capacity
# --------------------------------------------------------------------------------------
def region_ratio_draws(calib: pd.DataFrame, n_boot: int, seed: int = BOOT_SEED) -> dict:
    """Per calibration region (`group`, areas cut from one mapped region; an area on its
    own otherwise): summed true and detected area, and `n_boot` replicates of both.

    A region with `BOOT_MIN_AREAS` areas or more is resampled over its own areas: one
    area's spread across its own strips is not the spread across places, which is what
    moved every roofclf number this project has published. Below that, its true area is
    multiplied by a lognormal draw of `JUDGEMENT_CI90`, so the region still carries an
    interval rather than none. Regions are resampled separately because they are priced
    separately (`domain_cells`)."""
    a = calib[calib.block == "all"].copy()
    if "group" not in a.columns:
        a["group"] = a["area"]
    rng = np.random.default_rng(seed)
    sigma = np.log(JUDGEMENT_CI90[1]) / 1.6448536
    out = {}
    for region, s in a.groupby("group", sort=False):
        t, d = s.true_area_m2.to_numpy(float), s.det_area_m2.to_numpy(float)
        if len(s) >= BOOT_MIN_AREAS:
            idx = rng.integers(0, len(s), (n_boot, len(s)))
            t_rep, d_rep = t[idx].sum(1), d[idx].sum(1)
        else:
            t_rep, d_rep = t.sum() * np.exp(rng.normal(0.0, sigma, n_boot)), np.full(n_boot, d.sum())
        out[region] = {"true": float(t.sum()), "det": float(d.sum()), "true_rep": t_rep, "det_rep": d_rep,
                       "n_areas": int(len(s)), "bootstrapped": len(s) >= BOOT_MIN_AREAS}
    return out


def _dem_items(bbox):
    import planetary_computer
    import pystac_client

    from earthpv.worldcover import STAC_URL

    cat = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    return list(cat.search(collections=[DEM_COLLECTION], bbox=bbox).items())


def cell_elevation(cells: pd.DataFrame, cell_deg: float = 0.1) -> pd.DataFrame:
    """`cell`, `elev_m`: median Copernicus DEM elevation of every cell (columns `cell`,
    `lon0`, `lat0`), read at every `DEM_STEP`-th pixel, one read per 1-degree tile."""
    lon0, lat0 = cells["lon0"].to_numpy(float), cells["lat0"].to_numpy(float)
    gx, gy = float(lon0.min()), float(lat0.min())
    key = {int(round((x - gx) / cell_deg)) * 100_000 + int(round((y - gy) / cell_deg)): c
           for c, x, y in zip(cells["cell"], lon0, lat0)}
    bbox = (lon0.min(), lat0.min(), lon0.max() + cell_deg, lat0.max() + cell_deg)
    parts = []
    for it in _dem_items(bbox):
        with rasterio.open(it.assets["data"].href) as src:
            h, w = max(1, src.height // DEM_STEP), max(1, src.width // DEM_STEP)
            arr = src.read(1, out_shape=(h, w)).astype("float64")
            t = src.transform * Affine.scale(src.width / w, src.height / h)
            nodata = src.nodata
        rows, cols = np.indices(arr.shape)
        lon, lat = t.c + (cols + 0.5) * t.a, t.f + (rows + 0.5) * t.e
        k = np.floor((lon - gx) / cell_deg).astype(np.int64) * 100_000 + np.floor((lat - gy) / cell_deg).astype(np.int64)
        ok = np.isin(k, list(key)) & (arr != nodata if nodata is not None else True)
        parts.append(pd.DataFrame({"k": k[ok], "elev_m": arr[ok]}))
    med = pd.concat(parts).groupby("k").elev_m.median() if parts else pd.Series(dtype=float)
    return pd.DataFrame({"cell": list(key.values()), "elev_m": [med.get(k, np.nan) for k in key]})


def area_elevation(boundary: BaseGeometry) -> float:
    """Median Copernicus DEM elevation inside `boundary` (EPSG:4326), at the DEM's 90 m."""
    from rasterio.errors import WindowError
    from rasterio.windows import Window, from_bounds

    vals = []
    for it in _dem_items(boundary.bounds):
        with rasterio.open(it.assets["data"].href) as src:
            win = from_bounds(*boundary.bounds, transform=src.transform).round_offsets().round_lengths()
            try:
                win = win.intersection(Window(0, 0, src.width, src.height))
            except WindowError:
                continue
            arr = src.read(1, window=win).astype("float64")
            inside = rasterio.features.geometry_mask([boundary], arr.shape, src.window_transform(win), invert=True)
            if src.nodata is not None:
                inside &= arr != src.nodata
            vals.append(arr[inside])
    vals = np.concatenate(vals) if vals else np.zeros(0)
    return float(np.median(vals)) if len(vals) else float("nan")


def road_fractions(blobs: gpd.GeoDataFrame, roads: gpd.GeoDataFrame) -> np.ndarray:
    """Share of each blob's area within `ROAD_HALF_WIDTH_M` of a road centreline: the
    vector form of the raster `road_frac` training measures."""
    out = np.zeros(len(blobs))
    if roads is None or roads.empty or blobs.empty:
        return out
    utm = blobs.estimate_utm_crs()
    bu = blobs.to_crs(utm).reset_index(drop=True)
    rb = gpd.GeoDataFrame(geometry=roads.to_crs(utm).buffer(ROAD_HALF_WIDTH_M).reset_index(drop=True), crs=utm)
    pairs = gpd.sjoin(bu[["geometry"]], rb, predicate="intersects")
    for i, grp in pairs.groupby(level=0):
        g = bu.geometry.iloc[i]
        out[i] = g.intersection(rb.geometry.iloc[grp["index_right"].to_numpy()].union_all()).area / g.area
    return out


DOMAIN_VARS = ("crop_frac", "bldg_density_km2", "elev_m")


def domain_cells(aoi: str, calib: pd.DataFrame, grid: Path | None) -> tuple[pd.DataFrame, dict]:
    """`cell`, the domain variables, `in_domain` and `region` for every density-grid cell,
    and the bounds used.

    A cell is in a region's domain when its cropland share, building density AND median
    elevation each lie within that region's areas' range, widened by `DOMAIN_TOL` each way,
    and it is priced with that region's ratio only (`region` names it; a cell two regions
    claim is priced with both pooled). One box around ALL areas was the rule while Yemen
    had one area. With 'Amran (highland, 1,900 m) and Tihama (lowland, 70 to 240 m) it
    reached 289 of 810 cells, mostly highland terraces in Ibb, Sana'a and Ta'izz that
    resemble Tihama in cropland and buildings only, and put Tihama's ratio (1.19 per
    detected m2, against 'Amran's 0.17) on their blobs: 3.5 GWp, above the 2.8 GWp of panels
    Yemen imported in total since 2017. Elevation is what separates the two landscapes."""
    from earthpv.worldcover import cell_cropland

    a = calib[calib.block == "all"].copy()
    if "group" not in a.columns:
        a["group"] = a["area"]
    g = pd.read_parquet(grid or Path("data/predictions") / aoi / "density" / "grid.geoparquet",
                        columns=["cell", "lon0", "lat0", "bldg_density_km2"])
    for name, fn in (("cropland", cell_cropland), ("elevation", cell_elevation)):
        cache = Path("data/cells_cache") / f"{aoi}_{name}.parquet"
        got = pd.read_parquet(cache) if cache.exists() else None
        if got is None or not set(g.cell) <= set(got.cell):
            got = fn(g[["cell", "lon0", "lat0"]])
            cache.parent.mkdir(parents=True, exist_ok=True)
            got.to_parquet(cache)
        g = g.merge(got[["cell", "crop_frac" if name == "cropland" else "elev_m"]], on="cell", how="left")
    cols = ["cell", *DOMAIN_VARS, "in_domain", "region"]
    if any(v not in a for v in DOMAIN_VARS) or a[list(DOMAIN_VARS)].isna().any().any():
        log.warning("calibration.csv lacks a domain variable (%s): no cell is in domain", ", ".join(DOMAIN_VARS))
        g["in_domain"], g["region"] = False, None
        return g[cols], {}
    bounds, hits = {}, []
    for region, s in a.groupby("group", sort=False):
        b = {v: [float(s[v].min()) / DOMAIN_TOL, float(s[v].max()) * DOMAIN_TOL] for v in DOMAIN_VARS}
        m = np.logical_and.reduce([g[v].between(*b[v]).to_numpy() for v in DOMAIN_VARS])
        bounds[str(region)] = b
        hits.append(np.where(m, str(region), ""))
    g["region"] = ["+".join(r for r in row if r) or None for row in zip(*hits)]
    g["in_domain"] = g["region"].notna()
    return g[cols], bounds


def ground_capacity(
    aoi: str, score_dir: Path, calib_dir: Path, out_dir: Path, osm_solar: Path | None = None,
    candidates: Path | None = None, n_boot: int = 200, kwp_per_m2: float | None = None,
    leads: int = 500, max_blob_m2: float | None = "model", roads: Path | None = None,
    grid: Path | None = None, roofclf_buildings: tuple = (), labels_dir: Path | None = None,
) -> dict:
    """Incremental ground-PV capacity per cell: kept blobs that neither OSM nor
    segmentation already counts, times the true/detected area ratio of the calibration
    region the cell resembles (`domain_cells`), times the module constant. Writes
    `ground_cells.parquet`, the incremental blobs, a ranked leads GeoJSON for JOSM review,
    and `summary.json`.

    The headline (`est_mwp_in_domain`) counts only cells inside a region's domain; the
    all-cells figure, at the ratio pooled over every area, is reported beside it as an
    extrapolation, never as the estimate. Blobs inside a registered farm area (`labels_dir`)
    count nothing: the area is completely mapped, so what is there is counted from the map,
    and a blob no mapped feature explains is a false positive or postdates the imagery."""
    from earthpv import capacity_calibration as cc
    from earthpv.density import capacity_relevant_candidates

    score_dir, calib_dir, out_dir = Path(score_dir), Path(calib_dir), Path(out_dir)
    man = json.loads((score_dir / "_model.json").read_text())
    model, feats, meta = load_ground_model(calib_dir / "model_full.json")
    if man.get("fingerprint") != roofclf.model_fingerprint(model, feats):
        raise ValueError(f"{score_dir} was scored by a different model than {calib_dir}/model_full.json; "
                         "the calibration ratio would describe another population")
    if max_blob_m2 == "model":
        max_blob_m2 = meta.get("max_blob_m2")
    calib = pd.read_csv(calib_dir / "calibration.csv", dtype={"block": str})
    regions = region_ratio_draws(calib, n_boot)
    a_all = calib[calib.block == "all"]
    if a_all.det_area_m2.sum() <= 0:
        raise ValueError("the clean areas hold no detected blob area at the deployment threshold")
    pooled = float(a_all.true_area_m2.sum() / a_all.det_area_m2.sum())
    kwp = cc.DEFAULT_KWP_PER_M2_MODULE if kwp_per_m2 is None else kwp_per_m2

    parts = [gpd.read_parquet(p) for p in sorted(score_dir.glob("*.parquet")) if not p.name.startswith("_")]
    parts = [p for p in parts if len(p)]
    if not parts:
        raise ValueError(f"no blobs under {score_dir}")
    blobs = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    n_all = len(blobs)
    blobs = blobs[kept(blobs, max_blob_m2)].reset_index(drop=True)

    # The road veto, as a vector overlap over the blobs that survived everything else.
    # Roads come from `roads` (a paved-roads parquet) or Overpass per whole 1-degree chunk,
    # cached, and only for chunks that hold a blob.
    if roads is not None:
        rd, failed = gpd.read_parquet(roads), set()
    else:
        keys = {(float(np.floor(x)), float(np.floor(y)))
                for x, y in zip(blobs.geometry.representative_point().x, blobs.geometry.representative_point().y)}
        rd, failed = paved_roads_by_chunk([(x, y, x + 1.0, y + 1.0) for x, y in sorted(keys)],
                                          Path("data/roads") / aoi)
    rp = blobs.geometry.representative_point()
    checked = np.array([(float(np.floor(x)), float(np.floor(y)), float(np.floor(x)) + 1.0,
                         float(np.floor(y)) + 1.0) not in failed for x, y in zip(rp.x, rp.y)])
    blobs["road_frac"] = road_fractions(blobs, rd)
    blobs["road_checked"] = checked
    blobs["road_veto"] = blobs["road_frac"] >= ROAD_VETO_FRAC
    n_road = int(blobs["road_veto"].sum())
    blobs = blobs[~blobs["road_veto"]].reset_index(drop=True)
    stats = {"blobs_scored": n_all, "blobs_kept_before_roads": len(blobs) + n_road, "road_vetoed": n_road,
             "blobs_kept": len(blobs), "blobs_kept_without_road_check": int((~blobs["road_checked"]).sum())}

    # Dedup, so the component is incremental: what OSM maps is counted from the map, and
    # what segmentation's figure uses is counted there.
    utm = blobs.estimate_utm_crs()
    bu = blobs.to_crs(utm)
    drop = np.zeros(len(blobs), dtype=bool)
    if osm_solar is not None:
        osm = gpd.read_parquet(osm_solar).to_crs(utm)
        near = gpd.sjoin(gpd.GeoDataFrame(geometry=bu.buffer(DEDUP_M), crs=utm), osm[["geometry"]],
                         predicate="intersects").index.unique()
        drop[near] = True
        stats["dedup_osm"] = int(len(near))
    if candidates is not None and Path(candidates).exists():
        cands, _ = capacity_relevant_candidates(gpd.read_parquet(candidates))
        cu = cands.to_crs(utm)
        near = gpd.sjoin(gpd.GeoDataFrame(geometry=bu.buffer(DEDUP_M), crs=utm), cu[["geometry"]],
                         predicate="intersects").index.unique()
        stats["dedup_segmentation"] = int((~drop[near]).sum())
        drop[near] = True
    # roofclf's own priced buildings, where a country has both instruments: under the
    # parcel label it already counts PV within `roofclf.YARD_RING_M` of a flagged roof, so a
    # blob that close to one is that building's yard array and is roofclf's to count.
    for path in roofclf_buildings:
        b = gpd.read_parquet(path)
        if b.empty:
            continue
        near = gpd.sjoin(gpd.GeoDataFrame(geometry=bu.buffer(roofclf.YARD_RING_M), crs=utm),
                         b.to_crs(utm)[["geometry"]], predicate="intersects").index.unique()
        stats[f"dedup_roofclf_{Path(path).stem}"] = int((~drop[near]).sum())
        drop[near] = True
    # Completely mapped farm areas: whatever is there is counted from the map.
    if labels_dir is not None:
        areas = [roofclf.load_boundary(Path(labels_dir) / f"{st}_boundary.geojson")
                 for st in roofclf.discover_quadrats(Path(labels_dir), farm=True)]
        if areas:
            rp = blobs.geometry.representative_point()
            inside = np.zeros(len(blobs), dtype=bool)
            for poly in areas:
                inside |= rp.within(poly).to_numpy()
            stats["inside_calibration_areas"] = int((inside & ~drop).sum())
            drop |= inside
    inc = blobs[~drop].reset_index(drop=True)
    stats["blobs_incremental"] = len(inc)

    cells = inc.groupby("cell").agg(n_blobs=("area_m2", "size"), det_area_m2=("area_m2", "sum")).reset_index()
    dom, bounds = domain_cells(aoi, calib, grid)
    cells = cells.merge(dom, on="cell", how="left")
    cells["in_domain"] = cells["in_domain"].fillna(False).astype(bool)
    # Each in-domain cell at the ratio of the region(s) it resembles, point and replicates.
    n_rep = len(next(iter(regions.values()))["true_rep"]) if regions else 0
    ratio_cell, reps_cell = np.zeros(len(cells)), np.zeros((len(cells), n_rep))
    for i, reg in enumerate(cells["region"]):
        if not isinstance(reg, str):
            continue
        rs = [regions[r] for r in reg.split("+")]
        ratio_cell[i] = sum(r["true"] for r in rs) / sum(r["det"] for r in rs)
        reps_cell[i] = sum(r["true_rep"] for r in rs) / sum(r["det_rep"] for r in rs)
    cells["ratio"] = ratio_cell
    cells["est_pv_area_m2"] = cells.det_area_m2 * ratio_cell
    cells["est_mwp"] = cells.est_pv_area_m2 * kwp / 1000.0
    total = float(cells.est_mwp.sum())
    det_total = float(cells.det_area_m2[cells.in_domain].sum())
    # The in-domain estimate per replicate, as an effective ratio over the in-domain blob
    # area, so the atlas can resample it the way it resamples roofclf's coverage ratio.
    det = cells.det_area_m2.to_numpy()
    boots = (det @ reps_cell) / det_total if det_total > 0 and n_rep else np.zeros(0)
    ratio = total * 1000.0 / kwp / det_total if det_total > 0 else pooled
    ci = ([float(np.percentile(boots, 5)) * det_total * kwp / 1000.0,
           float(np.percentile(boots, 95)) * det_total * kwp / 1000.0] if len(boots) else None)
    used = {r for reg in cells.loc[cells.in_domain, "region"] for r in reg.split("+")}
    boot_part = [f"{v['n_areas']} mapped farm areas in {r}" for r, v in regions.items()
                 if r in used and v["bootstrapped"]]
    judged = [f"{v['n_areas']} in {r}" for r, v in regions.items() if r in used and not v["bootstrapped"]]
    interval = (("bootstrap over " + " and ".join(boot_part) if boot_part else "stated judgement")
                + (f"; {', '.join(judged)} (fewer than {BOOT_MIN_AREAS}) a stated "
                   f"x/÷{JUDGEMENT_CI90[1]:g} judgement" if judged else ""))
    stats.update(cells_with_blobs=len(cells), cells_in_domain=int(cells.in_domain.sum()),
                 domain=bounds, regions={r: {"ratio": v["true"] / v["det"] if v["det"] else None,
                                             "n_areas": v["n_areas"],
                                             "cells": int((cells["region"].fillna("").str.split("+")
                                                           .apply(lambda x, r=r: r in x)).sum()),
                                             "est_mwp": float(cells.loc[cells["region"] == r, "est_mwp"].sum())}
                                         for r, v in regions.items()},
                 interval=interval,
                 est_mwp_all_cells_extrapolated=float(cells.det_area_m2.sum() * pooled * kwp / 1000.0))
    out_dir.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(out_dir / "ground_cells.parquet")
    inc.to_parquet(out_dir / "ground_blobs_incremental.parquet")
    lead = inc.sort_values("s_max", ascending=False).head(leads).reset_index(drop=True)
    lead.insert(0, "rank", np.arange(1, len(lead) + 1))
    if len(lead):
        lead.to_file(out_dir / "ground_leads.geojson", driver="GeoJSON")
    else:
        (out_dir / "ground_leads.geojson").write_text('{"type": "FeatureCollection", "features": []}\n')
    summary = {
        "aoi": aoi, "detector": DETECTOR, "fingerprint": man.get("fingerprint"),
        "estimand": (f"PV area in arrays below {meta.get('max_array_m2'):g} m2" if meta.get("max_array_m2")
                     else "PV area in ground arrays of every size"),
        "max_array_m2": meta.get("max_array_m2"),
        # Every replicate, so the atlas can carry this component's calibration error in
        # its interval the way it carries roofclf's coverage-ratio bootstrap.
        "ratio_bootstrap": [round(float(x), 6) for x in boots],
        "ratio_true_per_detected_m2": ratio, "ratio_pooled_all_areas": pooled, "ratio_boot_p05_p95": (
            [float(np.percentile(boots, 5)), float(np.percentile(boots, 95))] if len(boots) else None),
        "n_calibration_areas": int((calib.block == "all").sum()),
        "kwp_per_m2": kwp, "est_mwp_in_domain": total, "est_mwp_ci90": ci, **stats,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
