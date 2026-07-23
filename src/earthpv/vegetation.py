"""Seasonal-vegetation veto for the leads product.

Countryside green-field false positives (measured 2026-07-23 on the pk16085
Pakistan leads): in the dry-season composite the model actually read, those
leads are NOT green — median NDVI 0.10, spectrally indistinguishable from real
PV, because the fields were dark fallow/harvested/flooded-paddy soil when the
median was built. The "green field" a validator sees in high-res imagery is a
season mismatch, so no single-composite spectral test can remove them. What
does discriminate is the vegetation CYCLE: every crop field greens up at some
point in the year, PV panels never do.

Two instruments, by cost:

- `composite_max_ndvi` — max mean-NDVI across the composite epochs already on
  disk (current + pre-boom). Free and local, but two dry-season medians
  undersample the crop cycle: catches ~17% of countryside FP suspects at ~2%
  cost to OSM-confirmed PV (thresold 0.35). The interim filter.
- `scripts/veg_annual_ndvi.py` — samples a year of Sentinel-2 scenes per lead
  (the glint pipeline's fetcher, B04/B08) and reports p95 NDVI over the year;
  crossing ~0.4 means a crop cycle. Network-bound, resumable; the proper
  instrument. Cloud contamination biases NDVI *down*, so the veto is
  conservative with respect to residual cloud.

Both feed `export`: vetoed leads are dropped from the cleaned leads file and
written to `hard_negatives_veg.parquet` — ready for
`earthpv hard-negative-chips --centers` so the confusion class (dark fallow /
paddy soil, absent from German training negatives) enters the next retrain.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features as rfeat
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

from earthpv.config import LOCAL_BANDS

log = logging.getLogger(__name__)

RED_BAND = LOCAL_BANDS.index("B04") + 1  # 1-based raster band numbers
NIR_BAND = LOCAL_BANDS.index("B08") + 1
DEFAULT_COMPOSITE_NDVI_MAX = 0.35  # measured: 17% of countryside FP suspects, 2% of real PV
DEFAULT_ANNUAL_NDVI_MAX = 0.4


def _composites_region_dir(aoi: str, cfg: dict, settings) -> Path:
    """The composites root for this AOI: locally composed first, else the
    rooftopsenti source_region (same `composites/<cell>/composite_<n>.tif` layout)."""
    composed = Path("data/composites") / aoi
    if (composed / "composites").exists():
        return composed
    source_region = cfg.get("source_region")
    if source_region:
        return Path(settings.raw["local_root"]) / source_region
    raise FileNotFoundError(f"No composites for AOI '{aoi}' (no local dir, no source_region)")


def _mean_ndvi_for_group(tif: Path, geoms: gpd.GeoSeries) -> np.ndarray:
    """Mean NDVI over each geometry's footprint pixels in one composite COG."""
    out = np.full(len(geoms), np.nan)
    with rasterio.open(tif) as src:
        gg = geoms.to_crs(src.crs)
        for k, geom in enumerate(gg):
            w = from_bounds(*geom.bounds, transform=src.transform)
            try:
                # raises WindowError when the geometry pokes fully outside this
                # tile (rep point in the overlap strip, bounds beyond the edge)
                w = w.round_offsets().round_lengths().intersection(
                    Window(0, 0, src.width, src.height)
                )
            except rasterio.errors.WindowError:
                continue
            if w.width < 1 or w.height < 1:
                continue
            red = src.read(RED_BAND, window=w).astype("float32")
            nir = src.read(NIR_BAND, window=w).astype("float32")
            m = rfeat.geometry_mask(
                [geom], out_shape=red.shape,
                transform=window_transform(w, src.transform),
                invert=True, all_touched=True,
            )
            if not m.any():
                continue
            out[k] = float(np.mean((nir[m] - red[m]) / np.maximum(nir[m] + red[m], 1e-6)))
    return out


def composite_max_ndvi(
    geoms: gpd.GeoSeries, aoi: str, cfg: dict, settings,
) -> np.ndarray:
    """Max mean-NDVI per geometry across every composite epoch on disk.

    NaN where no composite covers the geometry — the caller must treat NaN as
    "unchecked", never as a veto. Groups geometries per tile so each COG is
    opened once per epoch.
    """
    from earthpv.local_source import CompositeIndex

    region_dir = _composites_region_dir(aoi, cfg, settings)
    idx = CompositeIndex(region_dir).index
    geoms = geoms.reset_index(drop=True)
    reps = gpd.GeoDataFrame(geometry=geoms.representative_point(), crs=geoms.crs)
    hits = gpd.sjoin(reps, idx[["path", "geometry"]], predicate="within", how="left")
    # a rep point in a tile-overlap strip joins to several tiles; any one will do
    hits = hits[~hits.index.duplicated(keep="first")]

    result = np.full(len(geoms), np.nan)
    grouped = hits.dropna(subset=["path"]).groupby("path").groups
    log.info("Composite NDVI: %d/%d leads covered, %d tiles",
             sum(len(v) for v in grouped.values()), len(geoms), len(grouped))
    for tif_path, rows in grouped.items():
        rows = list(rows)
        for epoch_tif in _epoch_paths(Path(tif_path)):
            nd = _mean_ndvi_for_group(epoch_tif, geoms.iloc[rows])
            result[rows] = np.fmax(result[rows], nd)  # fmax: NaN-tolerant max
    return result


def _epoch_paths(composite_0: Path) -> list[Path]:
    """Every composite_<n>.tif sibling of a tile's composite_0 (epochs on disk)."""
    return sorted(composite_0.parent.glob("composite_*.tif"))
