"""Sentinel-1 backscatter false-positive check for the leads product.

Measured 2026-08-02 on the pk16085 Pakistan leads: OSM-confirmed real PV detections
sit brighter in both S1 polarizations than confirmed non-PV false positives (NDVI-
refuted vegetation from `vegetation.py` + epoch-persistent bright candidates), even
controlling for candidate size (fixed 120 m window around each candidate's centroid,
scored within log-area bands rather than over the candidates' own wildly different
polygon sizes): overall AUC(VH) 0.73, size-conditional AUC 0.61-0.84 depending on
band, weakest at the largest (>16,000 m2, where plant-scale ambiguity is already a
known problem for other reasons) and strongest in the 1,600-16,000 m2 range that
covers most of this project's target class. Real sits several dB brighter in both
VV and VH - consistent with built/PV surfaces backscattering more than the dominant
false-positive class this project actually has (bare terrain: dry riverbed, salt
flat, bare rock, snow), not the corner-reflector-vs-bare-soil contrast a rigid
metal structure like a substation would show (see subdetect's `s1_separability.py`
for that case; cross-pol ratio was uninformative in both projects' tests, plain
VV/VH level is what carries the signal).

The threshold below is deliberately conservative - the two distributions overlap
substantially (this is a coarser signal than the vegetation-cycle veto, whose
default catches ~17% of FP suspects at ~2% cost to real PV): VH < -18 dB catches
13.9% of the measured false positives at 6.8% cost to confirmed real PV (~2.1x
enrichment). Tune `s1_vh_max_db` if a different cost/catch trade-off is wanted.

**Optional by design.** Sentinel-1 composites are not fetched by earthpv's own
`compose` stage - running this check needs a directory of already-built
`composites/<cell>/composite_s1.tif` RTC composites (VV, VH; same uint16 DN
convention as `imagery.py`'s S2 composites) on the SAME 0.1 deg grid as
`configs/aoi.yaml`'s `grid_origin`. For Pakistan this already exists in the
sibling `subdetect` project (built for a different detector, same grid by
construction - see that project's README). An AOI with no such directory simply
skips this veto entirely, same "a lead no instrument could check is always kept"
contract as every other veto in `export.py` - nobody is required to download
Sentinel-1 data to run the standard pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.warp
from rasterio.windows import Window, from_bounds

log = logging.getLogger(__name__)

# Same convention as subdetect/src/subdetect/config.py (same RTC product, same
# storage scheme) -- reused verbatim rather than recalibrated, since we are reading
# their composites directly, not refitting a new scale.
S1_SCALE = 500.0
S1_OFFSET_DB = 50.0

# Fixed sampling window (metres, half-size) around each candidate's centroid --
# matches subdetect's own s1_separability.py exactly, chosen there (and reused here)
# specifically so a huge polygonized blob and a small rooftop array are compared on
# the same footing rather than each averaged over its own, very different-sized
# footprint.
DEFAULT_WINDOW_M = 60.0

# VH-only veto: see module docstring for the measured cost/catch numbers. VV adds
# nothing beyond VH (the two are highly correlated at this resolution; an AND-gate
# on both was tested and performed no better), so the veto checks VH alone.
DEFAULT_S1_VH_MAX_DB = -18.0


def _s1_cell_index(s1_dir: Path) -> gpd.GeoDataFrame:
    """Spatial index over `<s1_dir>/composites/<cell>/composite_s1.tif` rasters.

    Mirrors `local_source.CompositeIndex`'s pattern (glob + real raster bounds, not
    recomputed grid arithmetic) but anchored on `composite_s1.tif` since the S1
    directory is typically a different root than the AOI's own S2 composites.
    """
    rows = []
    for tif in sorted(Path(s1_dir).glob("composites/*/composite_s1.tif")):
        with rasterio.open(tif) as src:
            bounds = rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        rows.append({"path": str(tif), "geometry": _box(*bounds)})
    if not rows:
        raise FileNotFoundError(f"No composite_s1.tif found under {s1_dir}/composites/*/")
    idx = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    log.info("Indexed %d Sentinel-1 composite cells under %s", len(idx), s1_dir)
    return idx


def _box(minx, miny, maxx, maxy):
    from shapely.geometry import box

    return box(minx, miny, maxx, maxy)


def s1_backscatter(
    geoms: gpd.GeoSeries, s1_dir: Path, window_m: float = DEFAULT_WINDOW_M,
) -> tuple[np.ndarray, np.ndarray]:
    """Mean VV/VH backscatter (dB) in a fixed window around each geometry's centroid.

    NaN where no S1 composite covers the point -- the caller must treat NaN as
    "unchecked", never as a veto (same contract as `vegetation.composite_max_ndvi`).
    """
    idx = _s1_cell_index(s1_dir)
    n = len(geoms)
    vv = np.full(n, np.nan)
    vh = np.full(n, np.nan)
    cent = geoms.reset_index(drop=True).centroid
    hits = gpd.sjoin(
        gpd.GeoDataFrame(geometry=cent, crs=geoms.crs).to_crs("EPSG:4326"),
        idx[["path", "geometry"]], predicate="within", how="left",
    )
    hits = hits[~hits.index.duplicated(keep="first")]

    open_rasters: dict[str, rasterio.DatasetReader] = {}
    try:
        for path, rows in hits.dropna(subset=["path"]).groupby("path").groups.items():
            src = open_rasters.setdefault(path, rasterio.open(path))
            for i in rows:
                lon, lat = cent.iloc[i].x, cent.iloc[i].y
                x, y = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
                x, y = x[0], y[0]
                try:
                    # raises WindowError when the point's cell-membership (from the
                    # sjoin against the cell's bbox) doesn't survive rounding to whole
                    # pixels right at a raster edge -- rare, skip rather than crash.
                    win = from_bounds(
                        x - window_m, y - window_m, x + window_m, y + window_m,
                        transform=src.transform,
                    ).round_offsets().round_lengths().intersection(
                        Window(0, 0, src.width, src.height)
                    )
                except rasterio.errors.WindowError:
                    continue
                if win.width <= 0 or win.height <= 0:
                    continue
                arr = src.read(window=win).astype("float32")
                valid = arr[0] > 0
                if valid.sum() < 4:
                    continue
                vv[i] = arr[0][valid].mean() / S1_SCALE - S1_OFFSET_DB
                vh[i] = arr[1][valid].mean() / S1_SCALE - S1_OFFSET_DB
    finally:
        for src in open_rasters.values():
            src.close()

    log.info(
        "S1 backscatter: %d/%d candidates covered by a composite cell under %s",
        int(np.isfinite(vv).sum()), n, s1_dir,
    )
    return vv, vh
