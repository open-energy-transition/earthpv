"""Per-building rooftop-PV classifier, trained on the fully-mapped calibration quadrats.

## Why the unit of prediction changes

At 10 m GSD a 100 m² array is one mixed pixel. You cannot outline it, and the segmentation
model is not even asked to try: `chips.MIN_PV_AREA` burns everything below 400 m² as
`ignore = -1`, so it receives no gradient there and has no reason to put probability mass
on a small array. The measured consequence is that the whole sub-500 m² class contributes
~8 MWp to the Pakistan national estimate, while a single fully-mapped square kilometre of
residential Lahore holds 3.3x more sub-100 m² PV area than the model finds nationwide.

Recall-corrected estimation cannot repair that: `1/recall x ~0 ~ 0`. A class you never
detect is not recoverable by reweighting the class you do detect. It needs a different
estimator, and this module is it.

The question asked here is **"does this building carry PV?"**, not "where are its panel
edges". That is a far easier problem at one mixed pixel: it needs the footprint's spectral
signature to differ from a PV-free roof of the same kind, not a resolvable outline. The
output is a calibrated per-building probability, which aggregates directly into an
adoption rate per cell/region and, with a kWp-per-roof-area factor measured on the same
quadrats, into capacity.

## Why the quadrats are the only usable label source

Ordinary OSM is incomplete at small sizes, so a building with no mapped PV is not a
negative. In an exhaustively mapped quadrat it is: every building carries a verified
has-PV / has-no-PV label. That is exactly the supervision missing in the failure regime,
and it is why these quadrats should not be spent only on post-hoc correction.

The sample is also the honest limit of this module. Of the six available quadrats, four are
industrial estates and two residential, and PV area below 500 m² is 96-98% of the
residential boxes against 4-10% of the industrial ones. So the pooled set under-represents
exactly the stratum the module exists to serve, and reported skill must be read per quadrat,
never pooled. `evaluate` therefore reports leave-one-quadrat-out folds and refuses to
headline a pooled number.

**Rule-1 complete** (every visible panel inside the boundary mapped, verified against
high-res imagery) is a *mapper's declaration*, never something this code infers and never
something a script can produce. As of **2026-08-05 the repository owner declared it for all
seventeen quadrats**, so every quadrat's has-no-PV buildings now count as trustworthy
negatives and a low score anywhere can no longer be attributed to missing labels.

**Rule-1 is epoch-relative, and this is the single most important thing to know about it.**
Mapping is done against OpenStreetMap's background imagery (Esri/Bing/Maxar), whose capture
date does not match the Sentinel-2 composite the model reads and is generally *older*. So the
declaration certifies "every panel visible in THAT imagery is mapped" -- it cannot certify
panels built after it. In a country where rooftop PV is growing as fast as Pakistan's, the
gap between the two epochs is exactly where new installations live: they are present in the
model's input and absent from the labels. Rule-1 therefore holds *as of the mapping imagery*,
and only becomes a statement about the model's own epoch once imagery contemporaneous with
the composite is acquired and swept.

Concretely, the bias directions are known even though the magnitude per quadrat is not:

- **Precision is a lower bound.** A correct detection of an unmapped-but-real installation
  scores as a false positive.
- **`base_rate` is a lower bound** and therefore **`rate_ratio` an upper bound**, since a
  building carrying unmapped PV is counted as a negative.
- **Recall over mapped installations is unaffected** by this mechanism -- it only ever
  divides by labels that exist.

The size of the effect is measurable without new mapping, by running one checkpoint over two
imagery epochs (`scripts/fraction_stale_label_audit.py`): a pixel predicted PV now and not
pre-boom, and unlabelled, is a candidate post-mapping installation rather than an error.
Measured 2026-08-05 across 13 quadrats it moves pooled precision 0.435 -> 0.450, only 5.8% of
apparent false positives -- but that pooled number is dominated by industrial quadrats with
large false-positive pixel counts, and **per quadrat it is the dominant error term exactly
where the sub-400 m² work lives**: 68.4% in karachi_coast (precision 0.570 -> 0.807), 23.7%
in quetta, 11.7% in lahore.

Two further caveats nothing in the data expresses: five of the seventeen were first pulled
from OSM the same day they were declared complete, and no independent second-mapper sweep is
recorded for any quadrat in this repo (true since the first one). `imagery_layer` and
`imagery_date` in `results/calibration_quadrats.csv` are where the epoch belongs and are
**still empty for every quadrat** -- see docs/issues/calibration-imagery-dating.md.

## Size is a confounder, so skill is reported conditional on it

Adoption rises with house size -- mappers report large houses packed with PV and small ones
much less -- so footprint area alone reaches AUC ~0.73 without the imagery contributing
anything. `auc_within_size` scores inside roof-area bands (`_SIZE_BANDS`) and n-weights the
result, which removes size as a discriminator entirely and measures what the pixels add at
fixed size. Median across folds: 0.845 conditional against 0.879 unconditional, so the size
prior is worth about 3 points and the imagery carries the rest. The same statistic for the
segmentation raster is 0.707, and 0.500 on the Rule-1 quadrat.

## Model

Regularised logistic regression on standardised features, fitted with scipy L-BFGS. Chosen
over gradient boosting deliberately: the output must be a *calibrated probability*, because
it is summed into an adoption rate rather than thresholded, and with five spatial folds and
a few thousand rows a linear model in good features is the appropriate capacity. No
scikit-learn dependency, so this runs in the base (no-torch) environment like every other
data stage. `--model` is where a boosted variant would go once there are more quadrats.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.transform
import shapely
from rasterio.warp import transform_bounds
from shapely.geometry import box as shapely_box
from shapely.geometry.base import BaseGeometry

log = logging.getLogger(__name__)

# Composite reflectance is uint16 scaled by this (Sentinel-2 L2A convention).
REFL_SCALE = 10000.0
# config.LOCAL_BANDS order; NIR_BROAD / RED / SWIR_1 indices used for the ratio features.
BAND_NAMES = ("b02", "b03", "b04", "b05", "b06", "b07", "b08", "b8a", "b11", "b12")
_I_RED, _I_NIR, _I_SWIR1, _I_BLUE, _I_GREEN = 2, 6, 8, 0, 1

# A building counts as PV-carrying when a mapped array covers at least this share of it, so
# a panel array that merely clips a neighbouring roof's edge does not label that roof.
MIN_PV_OVERLAP_FRAC = 0.05
# Reflectance value `CompositeIndex.read_window` leaves where the requested window falls
# outside the composite tile (`rasterio.merge.merge(..., nodata=0)`). Real composite
# pixels are never exactly zero in all ten bands, so this doubles as the "no data here"
# test -- see `zonal_mean_max`, which must be passed it for any reflectance window.
COMPOSITE_FILL = 0.0
# Ridge strength on standardised features. Deliberately firm: five spatial folds cannot
# support tuning, so this is set once and left.
L2 = 1.0
# Same floor as chips.MIN_PV_AREA -- "sub-400 m2" is this project's standard name for
# the population below the segmentation model's detection floor.
MIN_PV_AREA_FOR_PACKING = 400.0

# --------------------------------------------------------------------------------------
# Parcel label (2026-08-16): the yard, not just the roof
# --------------------------------------------------------------------------------------
# Depth of the yard ring around each footprint. 20 m because that is where the population
# is: 93.9% of strict sub-400 m2 ground-mount installations in the quadrats, and 91.0% of
# every OSM ground-tagged generator under 400 m2 nationally, sit within 10 m of a VIDA
# footprint, 98.5% within 30 m (`scripts/small_ground_mount_assessment.py census|national`,
# written up in docs/issues/small-ground-mount-instrument.md). 20 m keeps ~96% of them
# while staying inside the 30 m radius `sub400_capacity`'s OSM/candidate dedup already
# uses, so nothing this ring picks up can be double-counted against a feature those
# masks exclude.
YARD_RING_M = 20.0
# Off-roof PV belonging to an installation at or above this area is NOT attributed to a
# building. Above the segmentation floor, ground-mount is segmentation's job and the atlas
# already counts it (`density.py`'s ground-mount half); attributing it here as well would
# double-count one installation across two instruments. Same value as
# MIN_PV_AREA_FOR_PACKING / chips.MIN_PV_AREA, deliberately.
YARD_MAX_INSTALLATION_M2 = 400.0


# --------------------------------------------------------------------------------------
# Quadrat discovery and labels
# --------------------------------------------------------------------------------------
_BOUNDARY_SUFFIX = "_boundary.geojson"


def discover_quadrats(labels_dir: Path = Path("data/labels")) -> list[str]:
    """Quadrat stems that have both a boundary and a mapped-solar file.

    A stem is the full prefix before `_boundary.geojson`, e.g. `site_karachi_calib_1km` or
    `karachi_coast_calib_700m`. Matching on `_calib_*_` rather than a hard-coded `_calib_1km_`
    keeps the quadrat size out of the code: the protocol calls for 1-4 km2 boxes and the
    first Rule-1-complete one is 0.49 km2.
    """
    out = []
    for b in sorted(Path(labels_dir).glob(f"*_calib_*{_BOUNDARY_SUFFIX}")):
        stem = b.name[: -len(_BOUNDARY_SUFFIX)]
        if _newest_solar(stem, labels_dir) is not None:
            out.append(stem)
    return out


def quadrat_label(stem: str) -> str:
    """Short display name for a quadrat stem (`lahore_calib_6p61km2` -> `lahore`).

    Deliberately drops the size tag, so a quadrat keeps its fold label when its boundary is
    redrawn. That continuity is also a trap on the reporting side: a label-keyed join cannot
    tell new ground truth from old model scores (see the Lahore replacement note in
    docs/methods/calibration-quadrats.md).
    """
    return re.sub(r"_calib_.*$", "", stem)


def _newest_solar(stem: str, labels_dir: Path) -> Path | None:
    """Newest mapped-solar pull for a quadrat.

    Mapping is iterative and a quadrat gets re-pulled after a completeness pass, so the
    dated file supersedes the undated one. Picking the stale pull silently encodes
    whatever was cached at pull time as ground truth -- the exact failure recorded in
    docs/issues/pakistan-calibration-boxes.md. Lexicographic order does this correctly
    because '.' sorts before '_', so `..._overpass_solar.parquet` precedes any
    `..._overpass_solar_<date>.parquet`.
    """
    cands = sorted(Path(labels_dir).glob(f"{stem}_overpass_solar*.parquet"))
    return cands[-1] if cands else None


def load_boundary(path: Path) -> BaseGeometry:
    """One EPSG:4326 (Multi)Polygon for a quadrat boundary file, however it was authored.

    Quadrats no longer have to be script-generated geodesic squares -- a mapper can draw
    the boundary in JOSM and hand over the GeoJSON (see
    `docs/calibration-mapping-protocol.md`). That makes three normalisations load-bearing
    rather than cosmetic, and all of them have to happen in ONE place, because the
    evaluation scripts read every feature in the file (`rio_mask(s, list(gs.geometry))`,
    `bnd.union_all()`) while this loader and `chips.quadrat_chips` used to read only
    `geometry.iloc[0]` -- a multi-part hand-drawn boundary would then have trained on one
    piece and been scored on all of them, silently:

    1. **Every feature is unioned**, not just the first.
    2. **A closed LineString becomes a Polygon.** JOSM exports a closed way as a Polygon
       only when it carries area tags; an untagged one comes out as a LineString, whose
       `rasterize` is a one-pixel-wide outline and whose `.within()` is empty -- so the
       quadrat would score zero buildings and zero supervised pixels with no error.
    3. **Invalid rings are repaired** (`make_valid`) and Z is dropped. A ring drawn by
       hand can self-intersect where it closes, and shapely predicates on an invalid
       polygon are undefined rather than wrong-but-usable.
    """
    from shapely import force_2d, make_valid
    from shapely.geometry import MultiPolygon, Polygon

    gdf = gpd.read_file(path).to_crs("EPSG:4326")
    geoms = []
    for g in gdf.geometry:
        if g is None or g.is_empty:
            continue
        g = force_2d(g)
        if g.geom_type in ("LineString", "LinearRing"):
            if len(g.coords) < 4 or g.coords[0] != g.coords[-1]:
                raise ValueError(
                    f"{path}: contains an open LineString ({len(g.coords)} nodes). A quadrat "
                    "boundary must be a closed area -- in JOSM, close the way (and ideally tag "
                    "it, e.g. `landuse=residential`, so it exports as a polygon)."
                )
            g = Polygon(g.coords)
        if not g.is_valid:
            g = make_valid(g)
        geoms.append(g)
    if not geoms:
        raise ValueError(f"{path}: no usable geometry")

    merged = gpd.GeoSeries(geoms, crs="EPSG:4326").union_all()
    # make_valid on a self-touching ring can yield a GeometryCollection; keep the areal parts.
    if merged.geom_type == "GeometryCollection":
        parts = [g for g in merged.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not parts:
            raise ValueError(f"{path}: no areal geometry after repair")
        merged = parts[0] if len(parts) == 1 else MultiPolygon(
            [p for g in parts for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])]
        )
    if merged.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"{path}: boundary is {merged.geom_type}, expected a closed area")
    if len(geoms) > 1:
        log.info("boundary %s: unioned %d features", Path(path).name, len(geoms))
    return merged


def load_quadrat(stem: str, labels_dir: Path = Path("data/labels")) -> tuple:
    """`(boundary geometry, mapped PV polygons)` for one quadrat, in EPSG:4326."""
    boundary = load_boundary(Path(labels_dir) / f"{stem}{_BOUNDARY_SUFFIX}")
    solar_path = _newest_solar(stem, labels_dir)
    pv = gpd.read_parquet(solar_path).to_crs("EPSG:4326")
    pv = pv[pv.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    log.info("quadrat %s: %d mapped PV polygons from %s", stem, len(pv), solar_path.name)
    return boundary, pv


def packing_density(pv: gpd.GeoDataFrame, max_area_m2: float = MIN_PV_AREA_FOR_PACKING) -> float:
    """Median distance (m) from each sub-`max_area_m2` installation to its nearest
    neighbour of ANY size -- what actually sits next to a small array on the ground
    (which is what drives 10 m-pixel mixing), not just the spacing among other small
    arrays. A quadrat that is one small array surrounded by a dense field of large
    ones is "packed" by this measure even though `packing_density` restricted to
    small-only pairs would call it sparse.

    Measured 2026-07-29 across all 9 quadrats with this exact definition: this
    single, model-free, purely geometric number correlates strongly with
    `exp_scale_anchor`'s fraction-head scale (r=0.70), its segmentation scale
    (r=0.82), and `roofclf`'s own `auc_within_size` (r=0.78) -- i.e. most of why
    quadrats behave so differently is already visible from installation spacing
    alone, before any imagery is even read. Splits the 9 quadrats cleanly at
    ~20-40 m: five pack sub-400 m2 arrays tighter than one Sentinel-2 pixel
    (7-19 m, informal/residential), four sit at 44-52 m with sub-400 m2 as a small
    minority of their population (industrial) -- the same stratum split this
    project already tracks by hand, but continuous and measurable from the labels
    alone. NaN if fewer than 2 total installations (no pair to measure a distance
    between) or none below `max_area_m2` (nothing to measure FROM).
    """
    from scipy.spatial import cKDTree

    from earthpv.labels import geodesic_area_m2

    if len(pv) < 2:
        return float("nan")
    areas = np.array([geodesic_area_m2(g) for g in pv.geometry])
    is_small = areas < max_area_m2
    if not is_small.any():
        return float("nan")
    lon, lat = pv.geometry.centroid.x.mean(), pv.geometry.centroid.y.mean()
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
    cent_utm = pv.to_crs(epsg).geometry.centroid
    xy = np.column_stack([cent_utm.x.to_numpy(), cent_utm.y.to_numpy()])
    # k=2: nearest OTHER point (k=1 would be the point itself, distance 0).
    d, _ = cKDTree(xy).query(xy, k=2)
    return float(np.median(d[is_small, 1]))


# --------------------------------------------------------------------------------------
# Per-footprint zonal statistics
# --------------------------------------------------------------------------------------
def zonal_mean_max(
    bu_utm: gpd.GeoDataFrame, arr: np.ndarray, transform, nodata: float | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Per-building mean and max of a (bands, H, W) or (H, W) array over its footprint.

    Sub-pixel footprints rasterize to zero pixels -- about half of Pakistani VIDA
    buildings -- and those fall back to their representative point's pixel, which is the
    same convention `density.per_building_raster_stats` uses. Without the fallback the
    entire small-building population, i.e. the population this module exists for, would
    drop out of the table.

    **`nodata` is what keeps a fill value out of the statistics, and on the national run
    it is load-bearing rather than defensive.** Pass `nodata=0.0` for a reflectance
    window: a pixel where EVERY band equals it is treated as absent, so a footprint is
    averaged over its real pixels only, and a footprint with no real pixel at all comes
    back NaN instead of a plausible-looking number. Leave it `None` for a probability
    raster, where 0 is a legitimate value and the commonest one.

    The mechanism this exists for (measured 2026-08-06, and the cause of what looked like
    a band of rooftop-PV false positives along every cell boundary in JOSM): a composite
    tile's bounds round-trip through EPSG:4326 in `CompositeIndex.read_window` -- UTM
    bounds -> lat/lon envelope -> UTM envelope of that envelope -- which inflates the
    requested window by the grid convergence, 50-70 m in Punjab and up to 357 m across
    Pakistan's tiles. `rasterio.merge.merge` fills the excess with its `nodata=0`, so a
    per-cell read carries a frame of exact zeros (5-7 px, 2.2% of the window in cell
    0135_0078) exactly where the cell's edge buildings sit. It is unavoidable at the
    read: a lat/lon box is not a UTM box, so requesting one from a UTM raster always
    asks for corners the raster does not have. Zero reflectance is darker than any real
    roof, and PV is dark, so the classifier reads it as a near-certain array: the fitted
    national model returns p=0.73 for a 100 m2 all-zero footprint against 0.10 for a
    typical one, and 0.48 even at 30 m2 -- above the 0.2407 deployment threshold at
    every size. Nationally that was 2.86M all-fill buildings, 95.4% of them flagged,
    **45.6% of every flagged building in the country**. Within 25 m of a cell edge the
    flag rate was 65.3% against 5.9% in the interior.

    Masking is the fix; widening the read is not. Padding the request so the fill frame
    lands outside the cell was tried and measured worse: composite tiles overlap their
    neighbours by ~150 m strips, `merge`'s "first source wins" precedence is filename
    order rather than "the cell's own tile", and the requested bounds are not on the
    source pixel grid -- so a padded read silently re-sources the cell's whole border
    strip from a differently-composited neighbour and shifts every pixel by a fraction
    of one. Measured on the same two cells: masking alone puts the sub-50 m edge flag
    rate at or below the interior rate (Lahore 5.06% vs 5.95%, isolated cell 0.40% vs
    3.86%), while a 150 m pad leaves the edge at 10.10% vs 5.95% and moves the isolated
    cell's *interior* rate 3.86% -> 4.68%.

    A building whose representative point resolves OUTSIDE the array, or onto a fill
    pixel, likewise gets NaN, not a silently clipped edge-row/-column pixel. Callers must
    handle NaN: keep the building but leave its score NaN (`score_buildings_national`,
    so building counts and `potential.large_roof_buildings` stay complete), or drop the
    row before it reaches a fit (`building_table`).
    """
    if arr.ndim == 2:
        arr = arr[None]
    nb, h, w = arr.shape
    n = len(bu_utm)
    idx = rasterio.features.rasterize(
        ((g, i) for i, g in enumerate(bu_utm.geometry, start=1)),
        out_shape=(h, w), transform=transform, fill=0, all_touched=False, dtype="int32",
    )
    # A nodata pixel is relabelled to the background bin 0, so it contributes to neither
    # the sums nor the counts and a footprint covering only nodata falls through to the
    # representative-point branch below (which then also rejects it).
    valid_px = None
    if nodata is not None:
        valid_px = ~np.all(arr == nodata, axis=0)
        idx = np.where(valid_px, idx, 0)
    flat = idx.ravel()
    counts = np.bincount(flat, minlength=n + 1)[1:]
    means = np.zeros((nb, n), dtype="float64")
    maxes = np.zeros((nb, n), dtype="float64")
    for b in range(nb):
        v = arr[b].ravel().astype("float64")
        s = np.bincount(flat, weights=v, minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            means[b] = np.where(counts > 0, s / np.maximum(counts, 1), 0.0)
        m = np.zeros(n + 1)
        np.maximum.at(m, flat, v)
        maxes[b] = m[1:]

    zero = counts == 0
    if zero.any():
        pts = bu_utm.geometry.representative_point()
        rr, cc = rasterio.transform.rowcol(
            transform, pts.x.to_numpy()[zero], pts.y.to_numpy()[zero]
        )
        rr = np.asarray(rr)
        cc = np.asarray(cc)
        ok = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
        if valid_px is not None:
            # Same rejection for a point that lands inside the window but on fill.
            ok[ok] &= valid_px[rr[ok], cc[ok]]
        zero_idx = np.flatnonzero(zero)
        valid_idx, oob_idx = zero_idx[ok], zero_idx[~ok]
        rr_v, cc_v = rr[ok], cc[ok]
        for b in range(nb):
            v = arr[b][rr_v, cc_v].astype("float64")
            means[b, valid_idx] = v
            maxes[b, valid_idx] = v
            means[b, oob_idx] = np.nan
            maxes[b, oob_idx] = np.nan
    return means, maxes


def yard_features(
    bu_utm: gpd.GeoDataFrame, arr: np.ndarray, transform, nodata: float | None = COMPOSITE_FILL,
    ring_m: float = YARD_RING_M, extra_mask: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Zonal statistics over each building's YARD -- the land around it, out to `ring_m`.

    The counterpart to `zonal_mean_max`'s roof block, and the feature half of the parcel
    label (see `parcel_pv_area`). A sub-400 m2 ground-mounted array beside a house is
    invisible to every roof-scoped feature this module has, and segmentation is at chance
    on it (0.534 AUC against matched controls), while SPPI over the same yard pixels
    reaches 0.833 -- so this is where that signal enters.

    **The yard is partitioned, not buffered.** Each background pixel is assigned to the
    NEAREST footprint by a distance-transform Voronoi, so no pixel is credited to two
    buildings. Buffering each footprint by 20 m instead would double-count almost every
    pixel in a dense quadrat, where overlapping buffers are the rule rather than the
    exception, and would let one array raise the yard statistics of every neighbour it
    happens to fall near.

    **Buildings with no yard pixel get imputed features and `has_yard = 0`.** In a dense
    block a footprint can be entirely surrounded by other footprints; 62% of the quadrat
    building population has no yard pixel at all. Dropping those rows is not an option
    (they are most of the country's flagged population), and leaving NaN would take them
    out of the fit at training time and out of `score_buildings_national`'s `valid` mask at
    deployment. They are imputed at the LOCAL median -- this quadrat's or this cell's own
    yard-bearing buildings -- for the same reason `local_zscore` re-centres locally rather
    than nationally, and flagged with `has_yard` so the fit can condition on the fallback
    instead of reading it as a measurement. This is the imputation the measured 0.747 AUC
    in docs/issues/small-ground-mount-instrument.md was obtained under.

    `extra_mask` further restricts which pixels may enter a ring (a quadrat boundary, say).
    Returns one array per feature name in `YARD_FEATURES` plus the raw `yard_area_m2`.
    """
    from scipy import ndimage

    from earthpv.sppi import compute_sppi

    if arr.ndim == 2:
        arr = arr[None]
    h, w = arr.shape[-2:]
    px_m = abs(transform.a)
    n = len(bu_utm)
    names = ([f"yard_{b}_mean" for b in BAND_NAMES]
             + ["yard_ndvi", "yard_ndbi", "yard_brightness", "yard_swir_vis_ratio",
                "yard_blue_red_ratio", "yard_sppi_mean", "yard_sppi_max"])

    bid = rasterio.features.rasterize(
        ((g, i + 1) for i, g in enumerate(bu_utm.geometry)),
        out_shape=(h, w), transform=transform, fill=0, dtype="int32", all_touched=True,
    )
    if not (bid > 0).any():
        # No footprint rasterized at all (a window smaller than one pixel, or an empty
        # frame). Every building is yardless; say so rather than dividing by zero.
        out = {k: np.zeros(n) for k in names}
        out["yard_area_m2"] = np.zeros(n)
        out["has_yard"] = np.zeros(n)
        return out

    valid = np.ones((h, w), dtype=bool) if nodata is None else ~np.all(arr == nodata, axis=0)
    if extra_mask is not None:
        valid &= extra_mask
    dist, (iy, ix) = ndimage.distance_transform_edt(
        bid == 0, sampling=px_m, return_indices=True
    )
    ring = np.where((bid == 0) & (dist <= ring_m) & valid, bid[iy, ix], 0)
    flat = ring.ravel()
    counts = np.bincount(flat, minlength=n + 1)[1:]

    def zmean(a: np.ndarray) -> np.ndarray:
        s = np.bincount(flat, weights=a.ravel().astype("float64"), minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(counts > 0, s / np.maximum(counts, 1), np.nan)

    def zmax(a: np.ndarray) -> np.ndarray:
        m = np.full(n + 1, -np.inf)
        np.maximum.at(m, flat, a.ravel().astype("float64"))
        return np.where(counts > 0, m[1:], np.nan)

    band = {b: zmean(arr[i]) for i, b in enumerate(BAND_NAMES)}
    eps = 1e-6
    r, nir, sw = band[BAND_NAMES[_I_RED]], band[BAND_NAMES[_I_NIR]], band[BAND_NAMES[_I_SWIR1]]
    sppi_px = compute_sppi(arr[0], arr[1], arr[6], arr[8], arr[9])
    out = {f"yard_{b}_mean": band[b] for b in BAND_NAMES}
    out["yard_ndvi"] = (nir - r) / (nir + r + eps)
    out["yard_ndbi"] = (sw - nir) / (sw + nir + eps)
    # Plain mean, not nanmean: a yardless building is NaN in every band at once, so NaN
    # propagating here is the correct answer and nanmean would only add an empty-slice
    # warning on its way to the same value. The imputation below is what resolves it.
    out["yard_brightness"] = np.stack([band[b] for b in BAND_NAMES]).mean(axis=0)
    out["yard_swir_vis_ratio"] = sw / (
        np.stack([band[BAND_NAMES[i]] for i in (_I_BLUE, _I_GREEN, _I_RED)]).mean(axis=0) + eps
    )
    out["yard_blue_red_ratio"] = band[BAND_NAMES[_I_BLUE]] / (r + eps)
    out["yard_sppi_mean"] = zmean(sppi_px)
    out["yard_sppi_max"] = zmax(sppi_px)

    has_yard = (counts > 0).astype(float)
    for k in names:
        v = out[k]
        if not np.isfinite(v).any():
            out[k] = np.zeros(n)
            continue
        out[k] = np.where(np.isfinite(v), v, np.nanmedian(v))
    out["yard_area_m2"] = counts * px_m * px_m
    out["has_yard"] = has_yard
    return out


def parcel_pv_area(
    bu: gpd.GeoDataFrame, bu_utm: gpd.GeoDataFrame, pv: gpd.GeoDataFrame,
    ring_m: float = YARD_RING_M, max_installation_m2: float = YARD_MAX_INSTALLATION_M2,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Mapped PV area that sits OFF every footprint, attributed to its nearest building.

    The label half of the parcel widening. `building_table`'s roof term is the geometric
    intersection of mapped PV with each footprint, so an array two metres off the wall
    contributes exactly zero to `pv_area_true_m2` -- and therefore zero to the coverage
    ratio and zero to the area recall -- on a building this classifier very often flags
    anyway (29.4% of them, against a 9.9% background). That is an accounting gap, not a
    detection gap: 168 of 253 such buildings in the quadrats carry rooftop PV too and are
    already in the atlas.

    Three rules keep this from double-counting anything:

    1. **Off-roof only.** Each installation's geometry has every footprint it intersects
       subtracted from it first, so the roof term and this term partition one polygon and
       never both bill the same square metre.
    2. **One owner.** The remainder goes whole to the single nearest building, not to every
       building within the ring.
    3. **Below the segmentation floor only.** An installation of `max_installation_m2` or
       more is skipped entirely: above that floor ground-mount is segmentation's instrument
       and the atlas already counts it, so attributing it here too would count one plant in
       two components.

    Off-roof PV further than `ring_m` from any building is dropped and reported in the
    returned counters rather than silently absorbed -- it is the ~1.5% tail with no host
    building, and the honest thing is for it to remain missing.

    **Two different things land in this term, and they are returned separately.** An OSM
    installation tagged `placement=ground` beside a house is the small ground-mount array
    this widening exists for. But a `placement=rooftop` array whose polygon extends past
    its VIDA footprint is not ground-mount at all -- VIDA outlines are imagery-derived and
    routinely undersized or a metre or two off, so part of a genuinely roof-mounted array
    falls outside the polygon and the roof-only intersection simply loses it. Both belong
    in `pv_area_true_m2` (both are real PV on that parcel, and the denominator is the same
    VIDA roof area either way), but only the first is ground-mount, and the atlas's
    rooftop/ground-mount split is only honest if the two can be told apart. Measured on
    the quadrats, the overhang term is much the larger of the two -- see the summary
    `run_roof_classifier` writes.

    Returns `(ground_yard_m2, overhang_yard_m2, counters)`, both per building.
    """
    from earthpv.labels import geodesic_area_m2

    n = len(bu)
    ground, overhang = np.zeros(n), np.zeros(n)
    info = {"n_attributed": 0, "n_orphan": 0, "orphan_area_m2": 0.0, "n_oversize_skipped": 0}
    if pv.empty or n == 0:
        return ground, overhang, info

    areas = np.array([geodesic_area_m2(g) for g in pv.geometry])
    keep = areas < max_installation_m2
    info["n_oversize_skipped"] = int((~keep).sum())
    if not keep.any():
        return ground, overhang, info
    small = pv.geometry.to_numpy()[keep]
    is_ground = (
        pv["placement"].to_numpy()[keep] == "ground" if "placement" in pv.columns
        else np.zeros(int(keep.sum()), dtype=bool)
    )

    # Subtract the footprints in EPSG:4326, where both layers already live, then measure
    # geodesically -- `labels.geodesic_area_m2`, never `.area` on lat/lon (CLAUDE.md).
    sidx = bu.sindex
    offs, offs_ground = [], []
    for g, gnd in zip(small, is_ground):
        hits = sidx.query(g, predicate="intersects")
        off = (g if len(hits) == 0
               else g.difference(shapely.union_all(bu.geometry.to_numpy()[hits])))
        if not off.is_empty and off.area > 0:
            offs.append(off)
            offs_ground.append(bool(gnd))
    if not offs:
        return ground, overhang, info

    off_gs = gpd.GeoSeries(offs, crs="EPSG:4326")
    off_utm = off_gs.to_crs(bu_utm.crs)
    off_areas = np.array([geodesic_area_m2(g) for g in off_gs])
    nearest = bu_utm.sindex.nearest(off_utm, return_all=False)[1]
    for j, (g_utm, bi) in enumerate(zip(off_utm.to_numpy(), nearest)):
        if g_utm.distance(bu_utm.geometry.iloc[bi]) <= ring_m:
            (ground if offs_ground[j] else overhang)[bi] += off_areas[j]
            info["n_attributed"] += 1
        else:
            info["n_orphan"] += 1
            info["orphan_area_m2"] += float(off_areas[j])
    return ground, overhang, info


def shape_features(geoms_utm: gpd.GeoSeries) -> dict[str, np.ndarray]:
    """Compactness, rectangularity and aspect ratio from each building's OWN footprint
    geometry -- no new imagery, using shape the VIDA polygon already carries and roofclf
    never looked at (only `roof_area_m2`, a scalar, was used before). Motivation: a large
    PV installation tends to occupy a large, regular rectangular section of a roof;
    oddly-shaped footprints (courtyards, informal additions, L-shapes) are a priori less
    likely to carry a full array, and this is a genuinely different signal from anything
    reflectance-based -- weaker than a physical measurement like glint, but free (the
    geometry is already fetched) and worth an ablation.

    `geoms_utm` must be projected (a UTM-like CRS in metres), not EPSG:4326 -- area and
    perimeter in degrees are not physically meaningful. Fully vectorised (shapely 2's
    array ufuncs), not a per-row `.apply`, so this is cheap even at national scale.

    - `compactness`: Polsby-Popper (4*pi*area/perimeter^2), 1.0 for a circle, lower for an
      elongated or irregular outline.
    - `rectangularity`: area / area of the minimum-rotated-bounding-rectangle, 1.0 for a
      perfect rectangle.
    - `aspect_ratio`: long/short side of that same minimum rotated rectangle, recovered
      from its own area and perimeter (long+short = P/2, long*short = A, solved as the
      roots of a quadratic) rather than extracting corner coordinates -- avoids a
      per-polygon Python loop entirely.
    """
    area = geoms_utm.area.to_numpy(dtype="float64")
    perim = geoms_utm.length.to_numpy(dtype="float64")
    compactness = 4 * np.pi * area / np.maximum(perim**2, 1e-9)

    rects = shapely.minimum_rotated_rectangle(geoms_utm.to_numpy())
    rect_area = shapely.area(rects)
    rect_perim = shapely.length(rects)
    # Clipped to <=1.0: by definition a polygon can never exceed its own bounding
    # rectangle's area, but the rectangle-fitting algorithm's floating-point rounding
    # can put it a hair over (measured up to 1.0003) for an already-near-rectangular
    # footprint.
    rectangularity = np.clip(area / np.maximum(rect_area, 1e-9), 0.0, 1.0)

    half_sum = rect_perim / 2.0  # long + short
    disc = np.maximum(half_sum**2 - 4 * rect_area, 0.0)  # long*short = rect_area
    sq = np.sqrt(disc)
    long_side = (half_sum + sq) / 2.0
    short_side = np.maximum((half_sum - sq) / 2.0, 1e-6)
    aspect_ratio = long_side / short_side

    return {
        "compactness": compactness, "rectangularity": rectangularity,
        "aspect_ratio": aspect_ratio,
    }


def local_zscore(values: np.ndarray) -> np.ndarray:
    """`(value - local median) / local std`, "local" meaning whatever population the
    caller passes in -- one quadrat's worth of buildings in `building_table`, one
    national cell's worth in `score_buildings_national`. Both are already-existing,
    roughly-comparable spatial units (a quadrat is built to fit inside one composite
    cell; national scoring already iterates cell-by-cell), so no new grouping concept is
    introduced, just a per-unit re-centring instead of a nationally-pooled absolute value.

    Targets the specific bright-roof false-positive mode a single national model can't
    otherwise separate from a genuine bright array: a building unusually bright for ITS
    OWN neighbourhood is a different claim than "bright in absolute terms", which
    conflates a real anomaly with a merely regionally-common roofing material (e.g. a
    city where white-painted or bare-metal roofs are the norm). Population std (ddof=0),
    not sample std, so a single-building cell/quadrat gives 0 rather than NaN.
    """
    values = np.asarray(values, dtype="float64")
    med = np.median(values)
    std = values.std(ddof=0)
    return (values - med) / max(std, 1e-6)


def _raster_for(point, prob_dir: Path) -> Path | None:
    """The per-cell raster in `prob_dir` whose extent contains `point`."""
    for tif in sorted(Path(prob_dir).glob("*.tif")):
        with rasterio.open(tif) as src:
            if shapely_box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds)).contains(point):
                return tif
    return None


def _read_prob(path: Path, bounds4326: tuple, out_crs, out_transform, out_shape) -> np.ndarray:
    """A 0-1 probability raster resampled onto the composite's grid for this quadrat."""
    from rasterio.warp import Resampling, reproject

    with rasterio.open(path) as src:
        w, s, e, n = transform_bounds("EPSG:4326", src.crs, *bounds4326)
        win = rasterio.windows.from_bounds(w, s, e, n, transform=src.transform)
        win = win.round_offsets().round_lengths().intersection(
            rasterio.windows.Window(0, 0, src.width, src.height)
        )
        data = src.read(1, window=win).astype("float32") / 255.0
        src_tf = rasterio.windows.transform(win, src.transform)
        src_crs = src.crs
    out = np.zeros(out_shape, dtype="float32")
    reproject(
        source=data, destination=out, src_transform=src_tf, src_crs=src_crs,
        dst_transform=out_transform, dst_crs=out_crs, resampling=Resampling.bilinear,
    )
    return out


# --------------------------------------------------------------------------------------
# Feature table
# --------------------------------------------------------------------------------------
def building_table(
    stem: str, iso3: str, composites: Path, seg_prob_dir: Path | None,
    frac_prob_dir: Path | None, labels_dir: Path = Path("data/labels"), con=None,
    include_epoch_jump: bool = False, preboom_prob_dir: Path | None = None,
    parcel_label: bool = False,
) -> pd.DataFrame:
    """One row per VIDA building in the quadrat, labelled and featurised.

    `parcel_label` (2026-08-16) widens both the label and the feature set from the roof to
    the whole parcel: `pv_area_true_m2` gains the off-roof PV within `YARD_RING_M`
    (`parcel_pv_area`), and the table gains the yard block (`yard_features`). The roof-only
    term stays available as `pv_area_roof_m2`, and the yard term as `pv_area_yard_m2`, so a
    table built this way still reproduces every pre-widening figure exactly. Off by default:
    every published atlas number to date is a roof-only measurement. See
    docs/issues/small-ground-mount-instrument.md for what motivates it and what it cannot fix
    (the calibration for the sparse stratum this most affects rests on four quadrats).
    """
    from earthpv.buildings import fetch_vida_buildings
    from earthpv.labels import geodesic_area_m2
    from earthpv.local_source import composite_index

    boundary, pv = load_quadrat(stem, labels_dir)
    name = quadrat_label(stem)
    minx, miny, maxx, maxy = boundary.bounds
    bu = fetch_vida_buildings((minx, miny, maxx, maxy), iso3, con=con).reset_index(drop=True)
    if bu.empty:
        log.warning("quadrat %s: no VIDA buildings", name)
        return pd.DataFrame()
    inside = bu.geometry.representative_point().within(boundary)
    bu = bu[inside.to_numpy()].reset_index(drop=True)
    if bu.empty:
        return pd.DataFrame()

    # Labels: true PV area on each footprint, then a has-PV flag by overlap share.
    pv_area = np.zeros(len(bu))
    if not pv.empty:
        sindex = bu.sindex
        for g in pv.geometry:
            for bi in sindex.query(g, predicate="intersects"):
                inter = geodesic_area_m2(bu.geometry.iloc[bi].intersection(g))
                if inter > 0:
                    pv_area[bi] += inter
    roof = bu["area_m2"].to_numpy(float)
    frac_true = np.divide(pv_area, np.maximum(roof, 1e-6))
    nn_median_m = packing_density(pv)

    # Imagery on the composite's own grid; the probability rasters are resampled onto it.
    # `composite_index` is `lru_cache`d on (path, layers), so calling this once per
    # quadrat (9x) or once per national cell (4,000+x, see `score_buildings_national`)
    # only ever pays the ~4,500-tile directory scan once per run, not once per call.
    # `layers=2` additionally reads composite_1 (pre-boom, ~2021-10 to 2022-01) stacked
    # on the same grid -- zero extra inference, since composite_1 is already ~complete
    # nationally (docs/issues/epoch-jump-recall-signal.md's cheap variant).
    # `nodata=COMPOSITE_FILL` below matters here for the same reason it does nationally,
    # just at much smaller scale: measured 2026-08-06, sialkot's window is 1.0% fill and
    # sukkur's 0.45%, the other 16 quadrats none. Training was therefore near-clean while
    # deployment was not, which is the skew that let the fill go unnoticed for so long.
    n_layers = 2 if include_epoch_jump else 1
    res = composite_index(str(composites), layers=n_layers).read_window((minx, miny, maxx, maxy))
    if res is None:
        log.warning("quadrat %s: no composite coverage", name)
        return pd.DataFrame()
    arr, transform, crs = res
    arr = arr.astype("float32") / REFL_SCALE
    preboom_arr = arr[len(BAND_NAMES): 2 * len(BAND_NAMES)] if include_epoch_jump else None
    arr = arr[: len(BAND_NAMES)]
    bu_utm = bu.to_crs(crs)
    means, maxes = zonal_mean_max(bu_utm, arr, transform, nodata=COMPOSITE_FILL)

    # The parcel widening. Both terms are kept separately so this table alone can
    # reproduce the roof-only figures it supersedes.
    pv_area_roof = pv_area.copy()
    pv_area_yard_ground = np.zeros(len(bu))
    pv_area_yard_overhang = np.zeros(len(bu))
    if parcel_label:
        pv_area_yard_ground, pv_area_yard_overhang, yard_info = parcel_pv_area(bu, bu_utm, pv)
        pv_area = pv_area_roof + pv_area_yard_ground + pv_area_yard_overhang
        frac_true = np.divide(pv_area, np.maximum(roof, 1e-6))
        log.info(
            "quadrat %s: parcel label adds %.0f m2 of off-roof PV (%.0f ground-tagged, "
            "%.0f rooftop overhanging its VIDA footprint) on %d buildings "
            "(%d installations attributed, %d orphaned beyond %.0f m totalling %.0f m2, "
            "%d at/above the %.0f m2 segmentation floor left to segmentation)",
            name, pv_area_yard_ground.sum() + pv_area_yard_overhang.sum(),
            pv_area_yard_ground.sum(), pv_area_yard_overhang.sum(),
            int(((pv_area_yard_ground + pv_area_yard_overhang) > 0).sum()),
            yard_info["n_attributed"], yard_info["n_orphan"], YARD_RING_M,
            yard_info["orphan_area_m2"], yard_info["n_oversize_skipped"],
            YARD_MAX_INSTALLATION_M2,
        )

    out = gpd.GeoDataFrame({
        "quadrat": name,
        "geometry": bu.geometry.to_numpy(),
        "roof_area_m2": roof,
        "bf_confidence": bu.get("bf_confidence", pd.Series(np.nan, index=bu.index)).to_numpy(),
        "pv_area_true_m2": pv_area,
        "pv_area_roof_m2": pv_area_roof,
        "pv_area_yard_m2": pv_area_yard_ground + pv_area_yard_overhang,
        "pv_area_yard_ground_m2": pv_area_yard_ground,
        "pv_area_yard_overhang_m2": pv_area_yard_overhang,
        "pv_frac_true": frac_true,
        "has_pv": (frac_true >= MIN_PV_OVERLAP_FRAC).astype(int),
        # A per-quadrat constant (same value every row), not a per-building feature --
        # carried here so `_fold_report` can read it straight off the held-out fold's
        # rows without a second pass over the labels. See `packing_density`.
        "nn_median_m": nn_median_m,
    })
    for i, b in enumerate(BAND_NAMES):
        out[f"{b}_mean"] = means[i]
    eps = 1e-6
    r, nir, sw = means[_I_RED], means[_I_NIR], means[_I_SWIR1]
    out["ndvi"] = (nir - r) / (nir + r + eps)
    out["ndbi"] = (sw - nir) / (sw + nir + eps)
    out["brightness"] = means.mean(axis=0)
    # PV modules are dark and comparatively flat across the visible, with a
    # characteristic SWIR drop; these two ratios carry most of that shape.
    out["swir_vis_ratio"] = sw / (means[[_I_BLUE, _I_GREEN, _I_RED]].mean(axis=0) + eps)
    out["blue_red_ratio"] = means[_I_BLUE] / (r + eps)

    # Shape features from the VIDA footprint geometry itself (no new imagery) and a
    # per-quadrat local-contrast re-centring of brightness (see `shape_features`/
    # `local_zscore`'s docstrings for what each targets and why).
    for k, v in shape_features(bu_utm.geometry).items():
        out[k] = v
    out["brightness_zscore"] = local_zscore(out["brightness"].to_numpy())

    if parcel_label:
        # Restricted to the quadrat's own boundary: a ring pixel outside it is not
        # Rule-1 mapped, so PV there would read as a feature with no matching label.
        inbnd = rasterio.features.rasterize(
            [(gpd.GeoSeries([boundary], crs="EPSG:4326").to_crs(crs).iloc[0], 1)],
            out_shape=arr.shape[-2:], transform=transform, fill=0, dtype="uint8",
        ).astype(bool)
        for k, v in yard_features(bu_utm, arr, transform, extra_mask=inbnd).items():
            out[k] = v
        log.info("quadrat %s: %.0f%% of buildings have at least one yard pixel",
                 name, 100 * out["has_yard"].mean())

    if include_epoch_jump:
        # Raw pre-boom reflectance delta per band -- the free variant from
        # docs/issues/epoch-jump-recall-signal.md (that doc's proposed version uses a
        # *probability* jump instead, which needs a targeted preboom inference pass;
        # this one needs none). A real installation should be dim pre-boom and bright
        # now; jump ~0 in either direction is uninformative or a persistent bright
        # roof/soil, not evidence of PV.
        pb_means, _ = zonal_mean_max(bu_utm, preboom_arr, transform, nodata=COMPOSITE_FILL)
        for i, b in enumerate(BAND_NAMES):
            out[f"{b}_jump"] = means[i] - pb_means[i]

    bounds = (minx, miny, maxx, maxy)
    for label, d in (("seg", seg_prob_dir), ("frac", frac_prob_dir), ("preboom", preboom_prob_dir)):
        out[f"{label}_mean"] = 0.0
        out[f"{label}_max"] = 0.0
        if d is None:
            continue
        # A representative point, not the centroid: a concave drawn boundary can have its
        # centroid outside itself, which would look up a raster cell the quadrat is not in.
        path = _raster_for(boundary.representative_point(), Path(d))
        if path is None:
            log.warning("quadrat %s: no %s raster covers it", name, label)
            continue
        # One cell only. Fine for a boundary inside a single 0.1 deg cell (every quadrat so
        # far); a larger drawn boundary straddling cells gets zero-filled outside this one,
        # so say so rather than silently featurising part of it as no-signal.
        with rasterio.open(path) as _s:
            if not shapely_box(*transform_bounds(_s.crs, "EPSG:4326", *_s.bounds)).covers(boundary):
                log.warning("quadrat %s: %s raster %s does not cover the whole boundary; "
                            "the uncovered part is featurised as zero probability",
                            name, label, path.name)
        p = _read_prob(path, bounds, crs, transform, arr.shape[-2:])
        pm, px = zonal_mean_max(bu_utm, p, transform)
        out[f"{label}_mean"], out[f"{label}_max"] = pm[0], px[0]
    if preboom_prob_dir is not None:
        # Probability-jump variant (docs/issues/epoch-jump-recall-signal.md): current
        # minus pre-boom segmentation probability. A building the model never lights up
        # for at all (seg_max=0 both epochs, the common case below the detection floor)
        # gets jump=0, correctly uninformative -- only a genuine rise is signal.
        out["epoch_jump"] = out["seg_max"] - out["preboom_max"]

    # `zonal_mean_max` returns NaN (2026-08-06 fix) for a building with no valid
    # composite pixel. Unlike `score_buildings_national`, which keeps the row with a NaN
    # score, drop it here: an unfeaturisable building cannot contribute to a fit, and a
    # silent NaN would poison the standardisation in `fit_logistic`.
    band_cols = [f"{b}_mean" for b in BAND_NAMES]
    valid = out[band_cols].notna().all(axis=1)
    if not valid.all():
        log.warning("quadrat %s: dropping %d/%d buildings with no valid composite pixel "
                    "(likely at the quadrat's own boundary)", name, int((~valid).sum()), len(out))
        out = out[valid.to_numpy()].reset_index(drop=True)

    out = out.set_geometry("geometry").set_crs("EPSG:4326")
    log.info(
        "quadrat %s: %d buildings, %d with PV (%.1f%%), true PV area %.0f m2",
        name, len(out), int(out.has_pv.sum()), 100 * out.has_pv.mean(), pv_area.sum(),
    )
    return out


SPECTRAL_FEATURES = [f"{b}_mean" for b in BAND_NAMES] + [
    "ndvi", "ndbi", "brightness", "swir_vis_ratio", "blue_red_ratio"
]
# The existing model outputs as features. Measured to add nothing (median fold AUC 0.8819
# -> 0.8834) and to *cost* accuracy on the sub-500 m2 buildings this module is for
# (0.8815 -> 0.8698), which is unsurprising: the segmentation model is trained with those
# arrays burned as ignore, so its probability there is noise the fit can only chase. Kept
# available behind `include_prob_features`, and always computed so `_fold_report` can keep
# scoring them as baselines.
PROB_FEATURES = ["seg_mean", "frac_mean"]
# Footprint geometry (`shape_features`) -- free (no new imagery, the polygon is already
# fetched), tested for whether a large/regular roof section reads differently than an
# irregular one. See `_ABLATIONS`'s `plus_shape` for whether this earns a place in
# MODEL_FEATURES.
SHAPE_FEATURES = ["compactness", "rectangularity", "aspect_ratio"]
# Brightness re-centred against the building's own quadrat/cell (`local_zscore`) instead
# of a nationally-pooled absolute value -- targets the bright-roof false-positive mode
# specifically. See `_ABLATIONS`'s `plus_local_contrast`.
LOCAL_CONTRAST_FEATURES = ["brightness_zscore"]
# The yard block (`yard_features`), present only under `parcel_label`. Same shape as the
# roof block plus SPPI, which is the strongest single spectral discriminator for a yard
# array (0.833 AUC per pixel against matched controls) and needs no training. Measured to
# be a clean negative for the ROOF task (0.8711 -> 0.8709), so this list must never be
# folded into MODEL_FEATURES unconditionally -- it earns its place only against a label
# that includes the yard.
YARD_FEATURES = (
    [f"yard_{b}_mean" for b in BAND_NAMES]
    + ["yard_ndvi", "yard_ndbi", "yard_brightness", "yard_swir_vis_ratio",
       "yard_blue_red_ratio", "yard_sppi_mean", "yard_sppi_max", "log_yard_area", "has_yard"]
)
# Default model input: footprint size plus footprint reflectance. Set by the ablation, not
# by preference.
MODEL_FEATURES = ["log_roof_area", "bf_confidence"] + SPECTRAL_FEATURES
PARCEL_MODEL_FEATURES = MODEL_FEATURES + YARD_FEATURES
FEATURES = (
    MODEL_FEATURES + PROB_FEATURES + SHAPE_FEATURES + LOCAL_CONTRAST_FEATURES
)  # every column the table carries


def _with_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Columns the feature lists name but the table stores in raw form. Shared by
    `design_matrix` and `_subset_matrix` so a fit and an ablation cannot derive them
    differently."""
    d = df.copy()
    d["log_roof_area"] = np.log10(d.roof_area_m2.clip(lower=1.0))
    d["bf_confidence"] = d.bf_confidence.fillna(d.bf_confidence.median() if
                                                d.bf_confidence.notna().any() else 0.0)
    if "yard_area_m2" in d.columns:
        # 0 m2 of yard is a real measurement (a fully enclosed footprint), not missing
        # data, and log10(max(0,1)) = 0 puts it at the bottom of the scale where it
        # belongs. `has_yard` carries the "this is the floor, not a small yard" flag.
        d["log_yard_area"] = np.log10(d.yard_area_m2.clip(lower=1.0))
    return d


def design_matrix(df: pd.DataFrame, feats: list[str] | None = None) -> np.ndarray:
    return _with_derived(df)[feats or MODEL_FEATURES].to_numpy(dtype="float64")


# --------------------------------------------------------------------------------------
# Logistic regression (scipy), AUC
# --------------------------------------------------------------------------------------
def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = L2) -> dict:
    """L2-regularised logistic regression on standardised features, via L-BFGS.

    The intercept is unpenalised so the fitted base rate is not shrunk toward 0.5 -- this
    model's output is aggregated into an adoption rate, where the base rate is the point.
    """
    from scipy.optimize import minimize

    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.hstack([(X - mu) / sd, np.ones((len(X), 1))])

    def nll(w):
        z = Z @ w
        # log(1+exp(z)) computed stably
        ll = np.sum(y * z - np.logaddexp(0.0, z))
        pen = l2 * np.sum(w[:-1] ** 2) / 2.0
        g = Z.T @ (1.0 / (1.0 + np.exp(-z)) - y)
        g[:-1] += l2 * w[:-1]
        return -ll + pen, g

    w0 = np.zeros(Z.shape[1])
    res = minimize(nll, w0, jac=True, method="L-BFGS-B")
    return {"w": res.x, "mu": mu, "sd": sd, "converged": bool(res.success)}


def predict_proba(model: dict, X: np.ndarray) -> np.ndarray:
    Z = np.hstack([(X - model["mu"]) / model["sd"], np.ones((len(X), 1))])
    return 1.0 / (1.0 + np.exp(-(Z @ model["w"])))


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """ROC AUC via the rank (Mann-Whitney) identity; ties handled by average ranks."""
    y = np.asarray(y).astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = pd.Series(s).rank().to_numpy()
    return float((r[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------
# Roof-area bands for the size-conditional AUC. Adoption genuinely rises with house size
# (mappers report large houses packed with PV and small ones much less), so a classifier
# given footprint area scores well above chance from that propensity alone -- roof area by
# itself reaches ~0.73 here. Scoring *within* a band removes size as a discriminator, so
# what is left is the imagery actually separating a PV roof from a PV-free roof of the same
# size. This is the honest headline for what the pixels contribute.
_SIZE_BANDS = ((0, 50), (50, 100), (100, 200), (200, 400), (400, np.inf))


def auc_within_size(
    y: np.ndarray, s: np.ndarray, roof: np.ndarray
) -> tuple[float, list[dict]]:
    """Size-conditional AUC: AUC inside each roof-area band, then an n-weighted mean.

    Bands with no positive or no negative case are skipped (AUC undefined), and their
    counts are excluded from the weighting rather than scored as 0.5.
    """
    rows, num, den = [], 0.0, 0
    for lo, hi in _SIZE_BANDS:
        m = (roof >= lo) & (roof < hi)
        if m.sum() < 2:
            continue
        a = auc(y[m], s[m])
        rows.append({
            "band": f"{lo:g}-{'inf' if hi == np.inf else f'{hi:g}'}",
            "n": int(m.sum()), "n_pv": int(y[m].sum()),
            "auc": None if np.isnan(a) else round(a, 4),
        })
        if not np.isnan(a):
            num += a * m.sum()
            den += int(m.sum())
    return (num / den if den else float("nan")), rows


def _fold_report(name: str, y: np.ndarray, p: np.ndarray, df: pd.DataFrame) -> dict:
    small = (df.roof_area_m2.to_numpy() < 500.0)
    roof = df.roof_area_m2.to_numpy()
    within, _ = auc_within_size(y, p, roof)
    within_seg, _ = auc_within_size(y, df.seg_mean.to_numpy(), roof)
    return {
        "quadrat": name,
        "n": int(len(y)),
        "n_pv": int(y.sum()),
        "base_rate": round(float(y.mean()), 4),
        "auc": round(auc(y, p), 4),
        "auc_small": round(auc(y[small], p[small]), 4) if small.sum() > 1 else float("nan"),
        "auc_seg_baseline": round(auc(y, df.seg_mean.to_numpy()), 4),
        "auc_frac_baseline": round(auc(y, df.frac_mean.to_numpy()), 4),
        "auc_within_size": round(within, 4),
        "auc_within_size_seg": round(within_seg, 4),
        "pred_rate": round(float(p.mean()), 4),
        "rate_ratio": round(float(p.mean() / max(y.mean(), 1e-9)), 3),
        # Median nearest-neighbour spacing (m) of this quadrat's own sub-400 m2
        # installations -- measured 2026-07-29 to correlate strongly with exp_scale
        # (r=0.70-0.82) and auc_within_size (r=0.78) across all 9 quadrats; reported
        # per fold so a reader can see at a glance whether a fold's skill/scale sits
        # in the dense-packed (~7-19 m, informal/residential) or sparse (~44-52 m,
        # industrial) regime, without cross-referencing a separate table.
        "nn_median_m": (
            round(float(df.nn_median_m.iloc[0]), 1)
            if "nn_median_m" in df.columns and len(df) else float("nan")
        ),
    }


def evaluate(
    table: pd.DataFrame, l2: float = L2, feats: list[str] | None = None
) -> tuple[pd.DataFrame, dict, np.ndarray]:
    """Leave-one-quadrat-out evaluation.

    Returns `(fold table, summary, out-of-fold probability per row)`. The third is the only
    honest per-building prediction available for these rows -- every building scored by a
    model that never saw its quadrat -- so it is what gets written to the table.

    A random split would put buildings from the same street in train and test and report
    fantasy skill; the quadrats are the only meaningful spatial unit here. Folds are
    reported individually because the five quadrats are not one population -- four
    industrial estates and one residential neighbourhood.
    """
    rows, oof = [], np.full(len(table), np.nan)
    for name in table.quadrat.unique():
        te = table.quadrat == name
        tr = ~te
        if table.loc[tr, "has_pv"].nunique() < 2 or te.sum() == 0:
            continue
        m = fit_logistic(
            design_matrix(table[tr], feats), table.loc[tr, "has_pv"].to_numpy(float), l2
        )
        p = predict_proba(m, design_matrix(table[te], feats))
        oof[te.to_numpy()] = p
        rows.append(_fold_report(name, table.loc[te, "has_pv"].to_numpy(), p, table[te]))
    folds = pd.DataFrame(rows)
    full = fit_logistic(design_matrix(table, feats), table.has_pv.to_numpy(float), l2)
    summary = {
        "n_buildings": int(len(table)),
        "n_pv": int(table.has_pv.sum()),
        "n_quadrats": int(table.quadrat.nunique()),
        "median_fold_auc": round(float(folds.auc.median()), 4) if len(folds) else None,
        "min_fold_auc": round(float(folds.auc.min()), 4) if len(folds) else None,
        "median_fold_auc_small": (
            round(float(folds.auc_small.median()), 4) if len(folds) else None
        ),
        # The size-confound-free headline: what the imagery adds at fixed roof size.
        "median_fold_auc_within_size": (
            round(float(folds.auc_within_size.median()), 4) if len(folds) else None
        ),
        "median_fold_auc_within_size_seg": (
            round(float(folds.auc_within_size_seg.median()), 4) if len(folds) else None
        ),
        "median_seg_baseline_auc": (
            round(float(folds.auc_seg_baseline.median()), 4) if len(folds) else None
        ),
        "median_frac_baseline_auc": (
            round(float(folds.auc_frac_baseline.median()), 4) if len(folds) else None
        ),
        "features": list(feats or MODEL_FEATURES),
        "coef": {
            f: round(float(c), 4)
            for f, c in zip(feats or MODEL_FEATURES, full["w"][:-1])
        },
        "intercept": round(float(full["w"][-1]), 4),
    }
    return folds, summary, oof


_ABLATIONS = {
    # Bigger roofs carry PV more often, so a model given only footprint size already
    # scores well above chance. Unless the spectral block beats this it is decoration:
    # "large buildings have PV" is a prior, not a measurement of *this* building.
    "area_only": ["log_roof_area", "bf_confidence"],
    # The converse: does the imagery alone separate PV roofs, with no size hint?
    "spectral_only": list(SPECTRAL_FEATURES),
    # The shipped default.
    "size_plus_spectral": list(MODEL_FEATURES),
    "plus_prob_rasters": list(MODEL_FEATURES) + list(PROB_FEATURES),
    # 2026-08-09: footprint shape (compactness/rectangularity/aspect ratio), free --
    # no new imagery, the polygon is already fetched.
    "plus_shape": list(MODEL_FEATURES) + list(SHAPE_FEATURES),
    # 2026-08-09: brightness re-centred against the building's own quadrat/cell instead
    # of a nationally-pooled absolute value -- targets the bright-roof false-positive mode.
    "plus_local_contrast": list(MODEL_FEATURES) + list(LOCAL_CONTRAST_FEATURES),
    "plus_shape_and_local_contrast": (
        list(MODEL_FEATURES) + list(SHAPE_FEATURES) + list(LOCAL_CONTRAST_FEATURES)
    ),
}


# Glint (`roofclf_glint.glint_score_features`) is NOT computed by default -- network-bound,
# minutes to hours per that module's own docstring -- so it is never in `table` unless a
# caller has explicitly run that expensive pull and joined the two columns in by hand.
# Kept as a name list here, not folded into `_ABLATIONS` unconditionally, so an ordinary
# `ablate()` call on a table without glint data never KeyErrors on a missing column.
GLINT_FEATURES = ["glint_n_consistent", "glint_spike_rate"]


def ablate(table: pd.DataFrame, l2: float = L2) -> pd.DataFrame:
    """Leave-one-quadrat-out AUC per feature block, so the size prior is separated out.

    Adds `plus_glint`/`plus_everything` blocks only when `table` already carries
    `GLINT_FEATURES` -- see that constant's comment.
    """
    ablations = dict(_ABLATIONS)
    if "has_yard" in table.columns:
        # Under `parcel_label` the label itself has changed, so `size_plus_spectral` here
        # is no longer the shipped model -- it is the roof-only model measured against a
        # parcel label, i.e. exactly the "does the yard block earn its place" contrast.
        ablations["plus_yard"] = list(PARCEL_MODEL_FEATURES)
        ablations["yard_only"] = ["log_roof_area", "bf_confidence"] + list(YARD_FEATURES)
    if all(c in table.columns for c in GLINT_FEATURES):
        ablations["plus_glint"] = list(MODEL_FEATURES) + list(GLINT_FEATURES)
        ablations["plus_everything"] = (
            list(MODEL_FEATURES) + list(SHAPE_FEATURES) + list(LOCAL_CONTRAST_FEATURES)
            + list(GLINT_FEATURES)
        )
    rows = []
    for label, feats in ablations.items():
        for name in table.quadrat.unique():
            te = (table.quadrat == name).to_numpy()
            tr = ~te
            if table.loc[tr, "has_pv"].nunique() < 2:
                continue
            Xtr, Xte = _subset_matrix(table[tr], feats), _subset_matrix(table[te], feats)
            m = fit_logistic(Xtr, table.loc[tr, "has_pv"].to_numpy(float), l2)
            p = predict_proba(m, Xte)
            y = table.loc[te, "has_pv"].to_numpy()
            small = table.loc[te, "roof_area_m2"].to_numpy() < 500.0
            rows.append({
                "block": label, "quadrat": name, "auc": round(auc(y, p), 4),
                "auc_small": round(auc(y[small], p[small]), 4) if small.sum() > 1 else np.nan,
            })
    df = pd.DataFrame(rows)
    return df.pivot_table(index="block", values=["auc", "auc_small"], aggfunc="median").round(4)


def _subset_matrix(df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    return _with_derived(df)[feats].to_numpy(dtype="float64")


def exp_scale_anchor(table: pd.DataFrame) -> pd.DataFrame:
    """Absolute-scale anchor for the density stage's expected-area instruments.

    For each quadrat: the PV area each raster-integral estimator predicts over the
    quadrat's buildings, against the exhaustively mapped truth. `scale` is the factor
    `density --exp-scale` should divide by, i.e. predicted / true. This is what the German
    MaStR bench cannot settle -- there its two slope estimators disagree by 2.6x and its
    well-mapped subset by 13x -- because here the denominator is complete by construction.
    """
    rows = []
    for name, g in table.groupby("quadrat"):
        roof = g.roof_area_m2.to_numpy()
        true = float(g.pv_area_true_m2.sum())
        for label in ("seg", "frac"):
            pred = float(np.minimum(g[f"{label}_mean"].to_numpy() * roof, roof).sum())
            rows.append({
                "quadrat": name, "instrument": label,
                "pred_pv_area_m2": round(pred, 1), "true_pv_area_m2": round(true, 1),
                "scale": round(pred / true, 3) if true > 0 else float("nan"),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# National deployment
# --------------------------------------------------------------------------------------
def save_model(model: dict, feats: list[str], path: Path) -> None:
    """Persist a `fit_logistic` result + the feature list it was fit on, so scoring new
    buildings later doesn't need to refit (LOQO already measures honest skill; a
    national deployment uses ONE fit on all labelled quadrats pooled, the same "full"
    fit `evaluate()` already computes for its `coef`/`intercept` summary fields)."""
    payload = {
        "w": model["w"].tolist(), "mu": model["mu"].tolist(), "sd": model["sd"].tolist(),
        "converged": model["converged"], "features": feats,
    }
    Path(path).write_text(json.dumps(payload, indent=2))


def model_fingerprint(model: dict, feats: list[str]) -> str:
    """Short stable hash of a fitted model's feature list and coefficients.

    Written next to a national scoring run (`score_buildings_national`) and checked by the
    capacity functions, so a scoring output can be matched to the calibration table it was
    produced from. Two national scorings now coexist on disk (the roof-only one every
    published figure uses, and a parcel-label one), and pairing the wrong two is a silent
    error: both directories hold the same columns, the numbers just quietly describe
    different populations. That is the same failure mode as the silently-regressed
    calibration YAML in CLAUDE.md's Density stage section, so it gets a guard rather than a
    convention.
    """
    import hashlib

    payload = json.dumps(
        {"features": list(feats),
         "w": [round(float(x), 10) for x in np.asarray(model["w"]).ravel()],
         "mu": [round(float(x), 10) for x in np.asarray(model["mu"]).ravel()],
         "sd": [round(float(x), 10) for x in np.asarray(model["sd"]).ravel()]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def check_scoring_matches_calibration(roofclf_dir: Path, calib_dir: Path) -> None:
    """Raise if a national scoring directory was produced by a different model than the
    calibration directory's `model_full.json`. Silent (a debug log) when the scoring run
    predates `_model.json`, since it cannot be checked and refusing would break every
    existing output."""
    manifest = Path(roofclf_dir) / "_model.json"
    model_path = Path(calib_dir) / "model_full.json"
    if not manifest.exists() or not model_path.exists():
        log.debug("No model fingerprint to check for %s against %s", roofclf_dir, calib_dir)
        return
    scored = json.loads(manifest.read_text()).get("fingerprint")
    model, feats = load_model(model_path)
    expected = model_fingerprint(model, feats)
    if scored != expected:
        raise ValueError(
            f"{roofclf_dir} was scored with model fingerprint {scored}, but {model_path} "
            f"fingerprints {expected}. These are different models -- the coverage ratio and "
            f"area recall from this calibration table do not describe that scored "
            f"population. Rescore nationally with this model, or point --calib-dir at the "
            f"calibration the scoring actually came from."
        )


def load_model(path: Path) -> tuple[dict, list[str]]:
    d = json.loads(Path(path).read_text())
    model = {
        "w": np.array(d["w"]), "mu": np.array(d["mu"]), "sd": np.array(d["sd"]),
        "converged": d["converged"],
    }
    return model, d["features"]


def canonical_composite_manifest(comp_idx, origin: tuple[float, float], cell_deg: float) -> pd.DataFrame:
    """Every composite tile mapped onto its canonical `(ix, iy)` cell under `origin`,
    deduping any tile that lands on a cell another tile already claims.

    **Why this exists (found 2026-08-06 while fixing the cell-edge fill bug above).**
    Pakistan's `data/composites/pakistan/composites/` carries tiles from two different
    grid origins describing overlapping ground: this AOI's own snapped grid (e.g.
    `0135_0078`, covering Lahore) and Punjab's un-snapped one, left over from an earlier
    on-demand `compose --aoi punjab` run (e.g. `0219_0117`, the same ground, 31.9%
    overlap, sharing 137,556 buildings -- 32.4% of `0135_0078`'s VIDA population). Punjab
    is a subregion of Pakistan, so its own boundary bbox's lower-left corner is not
    Pakistan's; `configs/aoi.yaml`'s `pakistan.grid_origin` snaps the *phase* of the two
    grids to agree (mod `cell_deg`) but that does not make their absolute indices agree
    -- Pakistan's snapped origin is `punjab_origin - 85 * cell_deg` in longitude, so the
    same ground gets two different, both "valid-looking", canonical names. Iterating raw
    `comp_idx.index` (as `score_buildings_national` used to) scores a building lying in
    the overlap once under each name -- the exact class of bug `density.cell_manifest`
    already exists to dedupe for probability rasters; this is the composite-tile
    counterpart, same convention: recompute each tile's cell from its own centre under
    THIS AOI's `origin` (ignoring what its directory happens to be named), and where two
    tiles land on the same recomputed cell, keep whichever one's directory name already
    equals that canonical name (i.e. prefer the tile this AOI's own `compose` produced),
    else the first.
    """
    minx, miny = origin
    rows = []
    for row in comp_idx.index.itertuples():
        cx, cy = row.geometry.centroid.x, row.geometry.centroid.y
        ix = int(np.floor((cx - minx) / cell_deg))
        iy = int(np.floor((cy - miny) / cell_deg))
        rows.append({"name": Path(row.path).parent.name, "path": row.path, "ix": ix, "iy": iy})
    df = pd.DataFrame(rows)
    df["cell"] = df.apply(lambda r: f"{int(r.ix):04d}_{int(r.iy):04d}", axis=1)
    kept, dropped = [], []
    for cell, grp in df.groupby("cell"):
        if len(grp) == 1:
            kept.append(grp.iloc[0])
            continue
        exact = grp[grp.name == cell]
        chosen = exact.iloc[0] if len(exact) else grp.iloc[0]
        kept.append(chosen)
        dropped += [r["name"] for _, r in grp.iterrows() if r.path != chosen.path]
    if dropped:
        log.info(
            "canonical composite manifest: deduped %d off-grid/overlapping tile(s) onto "
            "an existing canonical cell: %s", len(dropped), dropped,
        )
    man = pd.DataFrame(kept).reset_index(drop=True)
    man["lon0"] = minx + man.ix * cell_deg
    man["lat0"] = miny + man.iy * cell_deg
    return man


def score_buildings_national(
    aoi: str, model: dict, feats: list[str], composites: Path, out_dir: Path,
    min_roof_area_m2: float = 0.0, force: bool = False, limit: int = 0,
    layer_index: int = 0,
) -> Path:
    """Apply an already-fit model to every VIDA building under `composites`, one cell
    (one composite tile) at a time -- the per-cell/per-building pattern
    `density.process_cell` already proves tractable at Pakistan's ~4,463-cell national
    scale, adapted here to skip anything label-dependent (no ground truth exists
    outside the 9 calibration quadrats; this writes a predicted probability, not a
    fold-evaluated one).

    Resumable like `density.py`: a cell already written to `out_dir/{cell}.parquet` is
    skipped unless `force`. `min_roof_area_m2` is a pass-through to
    `fetch_vida_buildings`'s own filter (0 = keep everything, matching `density.py`'s
    convention -- about half of Pakistani VIDA footprints are sub-pixel and
    `zonal_mean_max`'s representative-point fallback already handles them).
    `limit` caps the number of cells actually processed this call (0 = all), for a
    smoke test before a multi-hour national run.

    **Cell-edge false positives (2026-08-06 fix).** `read_window`'s bounds round-trip
    inflates the requested window past the tile and `rasterio.merge` fills the excess
    with zeros, which this classifier reads as near-certain PV -- before the fix that was
    45.6% of every flagged building in Pakistan, concentrated in a band along every cell
    boundary. `zonal_mean_max(..., nodata=COMPOSITE_FILL)` excludes those pixels from the
    statistics; a building left with no valid pixel keeps its row (building counts and
    `potential.large_roof_buildings` stay complete) but gets `p_roofclf`/`sppi` NaN,
    counted in `n_unscored_nodata` and logged. See `zonal_mean_max` for the mechanism,
    the measured numbers, and why widening the read instead makes it worse.

    **Double-scored buildings in composite-tile overlaps (2026-08-06 fix).** Iterating
    `comp_idx.index` directly used to let two differently-named tiles both claim the same
    building whenever their (possibly off-grid) bboxes overlapped -- measured at >=5% of
    tile area for 901 of Pakistan's 4,473 tiles, at least 2.2M duplicated building
    instances overall. Cells are now taken from `canonical_composite_manifest`, which
    recomputes each tile's cell under this AOI's own grid and dedupes overlaps onto one
    canonical `(ix, iy)` per cell -- see its docstring for the mechanism. Both the VIDA
    fetch/ownership test and the composite read now use that cell's exact canonical
    0.1 deg box instead of a tile's own (possibly duplicated, possibly non-rectangular)
    bounds.
    """
    from earthpv.buildings import _iso3_for, fetch_vida_buildings
    from earthpv.compose import CELL_DEG
    from earthpv.config import Settings
    from earthpv.density import _grid_origin
    from earthpv.labels import resolve_aoi
    from earthpv.local_source import composite_index
    from earthpv import overture

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    iso3 = _iso3_for(cfg)
    if iso3 is None:
        raise ValueError(f"AOI '{aoi}' has no division.iso3 -> cannot locate VIDA buildings")

    # layer_index > 0 scores an alternate epoch (e.g. composite_1, the pre-boom
    # 2021-10..2022-01 layer built by `compose --index 1`) with the SAME model and
    # features -- the growth pipeline's roofclf half. The model and every downstream
    # coverage-ratio/area-recall table stay calibrated against current-epoch mapping;
    # applying them to another epoch is an explicit same-instrument extrapolation that
    # only ever feeds epoch DIFFS, never a standalone historical level.
    comp_idx = composite_index(str(composites), layers=layer_index + 1)
    origin = _grid_origin(aoi, cfg, settings)
    manifest = canonical_composite_manifest(comp_idx, origin, CELL_DEG)
    log.info("Canonical grid: %d cells from %d composite tiles", len(manifest), len(comp_idx.index))
    con = overture.connect()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The saved model's own feature list decides this: a parcel-label model
    # (`PARCEL_MODEL_FEATURES`) needs the yard block computed per cell, a roof-only one
    # must not pay for it. No flag to keep in sync, so a model can never be deployed
    # against features it was not fit on.
    # Fingerprint first, so the manifest exists even if the run is interrupted partway --
    # a resumed run appends cells to the same directory and must not be checkable only
    # once it has finished.
    (out_dir / "_model.json").write_text(json.dumps({
        "fingerprint": model_fingerprint(model, feats), "features": list(feats),
        "aoi": aoi, "composites": str(composites), "layer_index": layer_index,
    }, indent=2))
    need_yard = any(f in set(YARD_FEATURES) for f in feats)
    if need_yard:
        log.info("Model asks for the yard block -- computing the %.0f m parcel ring per cell",
                 YARD_RING_M)

    n_cells, n_buildings, n_flagged_05, n_unscored_nodata = 0, 0, 0, 0
    for m in manifest.itertuples():
        if limit and n_cells >= limit:
            break
        cell = m.cell
        out_path = out_dir / f"{cell}.parquet"
        if out_path.exists() and not force:
            continue
        bbox = (m.lon0, m.lat0, m.lon0 + CELL_DEG, m.lat0 + CELL_DEG)
        bu = fetch_vida_buildings(bbox, iso3, min_area_m2=min_roof_area_m2, con=con)
        if bu.empty:
            pd.DataFrame().to_parquet(out_path)
            continue
        # Half-open claim on the cell's own canonical box (not the fetch bbox, which is
        # padded by sjoin/row-group slop) so every building nationwide is scored by
        # exactly one cell -- same convention `density.cell_manifest` uses.
        inside = bu.geometry.representative_point().within(shapely_box(*bbox))
        bu = bu[inside.to_numpy()].reset_index(drop=True)
        if bu.empty:
            pd.DataFrame().to_parquet(out_path)
            continue

        try:
            res = comp_idx.read_window(bbox)
        except FileNotFoundError as e:
            # A handful of national cells never got their composite_<layer_index>.tif
            # (see compose_loop_preboom.sh's log). Skip without writing so a later
            # resumed run retries them once the layer exists.
            log.warning("cell %s: missing layer-%d composite (%s), skipping %d buildings",
                        cell, layer_index, e, len(bu))
            continue
        if res is None:
            log.warning("cell %s: no composite coverage, skipping %d buildings", cell, len(bu))
            continue
        arr, transform, crs = res
        arr = arr[layer_index * len(BAND_NAMES): (layer_index + 1) * len(BAND_NAMES)]
        arr = arr.astype("float32") / REFL_SCALE
        bu_utm = bu.to_crs(crs)
        means, _ = zonal_mean_max(bu_utm, arr, transform, nodata=COMPOSITE_FILL)

        eps = 1e-6
        r, nir, sw = means[_I_RED], means[_I_NIR], means[_I_SWIR1]
        feat_df = pd.DataFrame({
            "roof_area_m2": bu["area_m2"].to_numpy(float),
            "bf_confidence": bu.get(
                "bf_confidence", pd.Series(np.nan, index=bu.index)
            ).to_numpy(),
        })
        for i, b in enumerate(BAND_NAMES):
            feat_df[f"{b}_mean"] = means[i]
        feat_df["ndvi"] = (nir - r) / (nir + r + eps)
        feat_df["ndbi"] = (sw - nir) / (sw + nir + eps)
        feat_df["brightness"] = means.mean(axis=0)
        feat_df["swir_vis_ratio"] = sw / (means[[_I_BLUE, _I_GREEN, _I_RED]].mean(axis=0) + eps)
        feat_df["blue_red_ratio"] = means[_I_BLUE] / (r + eps)
        # Same shape/local-contrast features as `building_table` -- "local" here is this
        # cell's own building population, the national-scale analogue of one quadrat.
        for k, v in shape_features(bu_utm.geometry).items():
            feat_df[k] = v
        feat_df["brightness_zscore"] = local_zscore(feat_df["brightness"].to_numpy())
        if need_yard:
            # Cell-edge yards are truncated at the read window, exactly as roof statistics
            # already are: `read_window` returns this cell's own box, so a building on the
            # boundary sees only the part of its ring inside it. It shrinks `yard_area_m2`
            # for a thin border strip rather than fabricating pixels, and `has_yard`
            # remains true, which is the conservative failure.
            for k, v in yard_features(bu_utm, arr, transform).items():
                feat_df[k] = v

        # A building with no valid composite pixel keeps its row -- building counts and
        # `potential.large_roof_buildings` read this table for footprints alone, so
        # dropping it would quietly shrink the national building population -- but its
        # scores stay NaN. NaN never satisfies `p_roofclf >= threshold`, so it cannot
        # reach a capacity figure or a JOSM lead. This is the fix, not a defensive
        # check: before it, those rows scored ~0.73 and were 45.6% of all national flags
        # (see `zonal_mean_max`).
        valid = feat_df[[c for c in feat_df.columns if c != "bf_confidence"]].notna().all(axis=1)
        valid = valid.to_numpy()
        n_unscored_nodata += int((~valid).sum())

        p = np.full(len(feat_df), np.nan)
        if valid.any():
            p[valid] = predict_proba(
                model, design_matrix(feat_df[valid].reset_index(drop=True), feats)
            )
        # SPPI costs nothing extra here -- the five bands it needs are already read for
        # the model features above. Saving it alongside p_roofclf is what lets a future
        # national AND-gate (see docs/methods/density.md's "SPPI cross-validation")
        # happen without a second national composite-read pass.
        from earthpv.sppi import compute_sppi

        sppi_val = compute_sppi(
            feat_df["b02_mean"], feat_df["b03_mean"], feat_df["b08_mean"],
            feat_df["b11_mean"], feat_df["b12_mean"],
        )
        result = gpd.GeoDataFrame({
            "cell": cell, "geometry": bu.geometry.to_numpy(),
            "roof_area_m2": feat_df["roof_area_m2"], "p_roofclf": p, "sppi": sppi_val,
        }, crs="EPSG:4326")
        result.to_parquet(out_path)

        n_cells += 1
        n_buildings += len(bu)
        n_flagged_05 += int((p >= 0.5).sum())
        if n_cells % 200 == 0:
            log.info("Scored %d cells, %d buildings so far (%d >= 0.5 raw)",
                      n_cells, n_buildings, n_flagged_05)

    log.info("Done: %d cells scored this run, %d buildings, %d >= 0.5 raw probability "
              "(deployment threshold is chosen separately, see the LOQO precision "
              "calibration, not this raw count), %d left unscored (p_roofclf NaN) for "
              "having no valid composite pixel -> %s",
              n_cells, n_buildings, n_flagged_05, n_unscored_nodata, out_dir)
    return out_dir


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def run_roof_classifier(
    aoi: str = "pakistan",
    quadrats: list[str] | None = None,
    composites: Path = Path("data/composites/pakistan"),
    seg_prob_dir: Path | None = Path("data/predictions_pk16085/pakistan/prob"),
    frac_prob_dir: Path | None = Path("data/predictions_frac_pk_v2/pakistan/prob"),
    labels_dir: Path = Path("data/labels"),
    out_dir: Path = Path("data/roofclf"),
    l2: float = L2,
    parcel_label: bool = False,
    include_yard_features: bool = False,
    table_path: Path | None = None,
) -> Path:
    """Fit, evaluate and persist the classifier. See the CLI command for the options.

    `include_yard_features` puts `YARD_FEATURES` in the model. Measured 2026-08-16 and left
    OFF: against the PARCEL label itself -- the label the yard block exists to serve -- it
    scores median fold AUC 0.8712 against 0.8734 for the roof-only feature set, and yard
    features alone reach only 0.7538 against a 0.7382 size-only baseline. The reason is
    visible in `summary["parcel_pv_area_m2"]`: 80% of what the parcel label adds is mapped
    ROOFTOP PV overhanging an undersized VIDA footprint, which roof features already see,
    and the genuinely ground-mounted term is 1.7% of quadrat PV area -- too little to move
    a 118,755-row fit even when a yard block describes it well in isolation
    (docs/issues/small-ground-mount-instrument.md measures 0.747 AUC for it against a
    ground-mount-only label of 253 positives).

    `table_path` refits from an existing `buildings.geoparquet` instead of rebuilding every
    quadrat table, for exactly this kind of feature-set comparison: the tables cost about
    ten minutes and do not depend on the feature list or on `l2`. It is an error to pass it
    with a `parcel_label` the stored table was not built under, and this checks.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv import overture
    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    iso3 = _iso3_for(cfg)
    if iso3 is None:
        raise ValueError(f"AOI '{aoi}' has no division.iso3 -> cannot locate VIDA buildings")
    names = quadrats or discover_quadrats(labels_dir)
    if not names:
        raise FileNotFoundError(f"No calibration quadrats found in {labels_dir}")
    log.info("Quadrats: %s", ", ".join(names))

    feats = list(PARCEL_MODEL_FEATURES if include_yard_features else MODEL_FEATURES)
    if table_path is not None:
        table = gpd.read_parquet(table_path)
        stored_parcel = "pv_area_yard_m2" in table.columns
        if stored_parcel != parcel_label:
            raise ValueError(
                f"{table_path} was built with parcel_label={stored_parcel}, but this call "
                f"asks for parcel_label={parcel_label}. The label is baked into the stored "
                f"pv_area_true_m2/has_pv columns and cannot be changed by a refit."
            )
        log.info("Refitting from %s (%d rows, %d quadrats) -- tables not rebuilt",
                 table_path, len(table), table.quadrat.nunique())
    else:
        con = overture.connect()
        parts = [
            building_table(n, iso3, composites, seg_prob_dir, frac_prob_dir, labels_dir, con,
                           parcel_label=parcel_label)
            for n in names
        ]
        # Keep geometry so the per-building predictions are mappable (QGIS, the docs figure).
        table = gpd.GeoDataFrame(
            pd.concat([p for p in parts if not p.empty], ignore_index=True),
            geometry="geometry", crs="EPSG:4326",
        )
    if include_yard_features and "has_yard" not in table.columns:
        raise ValueError("include_yard_features needs a table built with parcel_label=True")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    folds, summary, oof = evaluate(table, l2=l2, feats=feats)
    table["p_oof"] = oof  # scored by a model that never saw this building's quadrat
    table.to_parquet(out_dir / "buildings.geoparquet")
    # Downstream (`sub400_capacity`, `roofclf_ge400_capacity`) reads this table's
    # `pv_area_true_m2` for both the coverage ratio and the area recall, so which label it
    # was built under decides what those corrections mean. Record it where a reader of the
    # summary cannot miss it rather than leaving it to be inferred from the feature list.
    summary["parcel_label"] = bool(parcel_label)
    summary["yard_features_in_model"] = bool(include_yard_features)
    if parcel_label:
        summary["parcel_pv_area_m2"] = {
            "roof": round(float(table.pv_area_roof_m2.sum()), 1),
            "yard_ground_tagged": round(float(table.pv_area_yard_ground_m2.sum()), 1),
            "yard_rooftop_overhang": round(float(table.pv_area_yard_overhang_m2.sum()), 1),
        }
        summary["n_pv_roof_only_label"] = int(
            (table.pv_area_roof_m2 / table.roof_area_m2.clip(lower=1e-6)
             >= MIN_PV_OVERLAP_FRAC).sum()
        )

    # Deployment artifact: ONE fit on every labelled building pooled (not per-fold --
    # LOQO above is for honest skill measurement; a national scorer needs a single
    # model), persisted so `score_buildings_national` never needs to refit.
    full_model = fit_logistic(design_matrix(table, feats), table.has_pv.to_numpy(float), l2)
    save_model(full_model, feats, out_dir / "model_full.json")
    # Deployment threshold: precision-targeted (not Youden's J -- this session's SPPI
    # validation measured that a balanced-sensitivity criterion trades away far too much
    # precision for a capacity-contributing detector), on the pooled out-of-fold scores,
    # i.e. still an honest LOQO number, just one threshold instead of nine per-fold ones.
    from earthpv.sppi import _precision_threshold

    valid = ~np.isnan(oof)
    y_valid, s_valid = table.loc[valid, "has_pv"].to_numpy(bool), oof[valid]
    thresh = _precision_threshold(y_valid, s_valid, min_precision=0.5)
    pred = s_valid >= thresh
    tp, fp = int((pred & y_valid).sum()), int((pred & ~y_valid).sum())
    thresh_stats = {
        "n_flagged": int(pred.sum()), "precision": round(tp / max(tp + fp, 1), 4),
        "recall": round(tp / max(int(y_valid.sum()), 1), 4),
    }
    summary["deployment_threshold"] = round(float(thresh), 4)
    summary["deployment_threshold_stats"] = thresh_stats
    log.info("Deployment threshold (precision>=0.5 target, pooled LOQO scores): %.4f -> %s",
              thresh, thresh_stats)

    anchor = exp_scale_anchor(table)
    abl = ablate(table, l2=l2)
    summary["ablation_median_auc"] = {k: float(v) for k, v in abl["auc"].items()}
    summary["ablation_median_auc_small"] = {k: float(v) for k, v in abl["auc_small"].items()}
    folds.to_csv(out_dir / "folds.csv", index=False)
    anchor.to_csv(out_dir / "exp_scale_anchor.csv", index=False)
    abl.to_csv(out_dir / "ablation.csv")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    log.info("Leave-one-quadrat-out folds:\n%s", folds.to_string(index=False))
    log.info("Feature-block ablation (median across folds):\n%s", abl.to_string())
    log.info("Expected-area absolute-scale anchor:\n%s", anchor.to_string(index=False))
    log.info("Summary: %s", json.dumps(summary, indent=2))
    return out_dir
