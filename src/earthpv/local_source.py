"""Read imagery/labels/buildings artifacts produced by the sibling `rooftopsenti`
project (per-MGRS Sentinel-2 composite COGs + OSM/Overture parquets).

Reusing these avoids re-downloading terabytes over a shared connection; earthpv
falls back to its own Overture/Planetary-Computer fetchers when a region has no
local artifacts (see imagery.py / labels.py).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.merge
import rasterio.warp
from rasterio.crs import CRS
from shapely.geometry import box

log = logging.getLogger(__name__)

Bbox = tuple[float, float, float, float]


def _snap_bounds(bounds, transform):
    """Expand `bounds` outwards to the source raster's own pixel grid.

    Without this, `merge` builds its output grid starting at whatever bounds it is handed,
    and those come from a lat/lon round-trip, so they land at an arbitrary sub-pixel offset
    from the source. Measured 2026-09-20 across eight quadrats, the returned grid sat
    0.014-0.933 px off the source tile, meaning every read RESAMPLED the composite onto a
    displaced grid before anything downstream saw it. Snapping makes the read a copy.

    MEASURED BENEFIT IS SMALL AND NOT SIGNIFICANT: +0.0038 AUC and +0.0032 within size band
    for `roofclf` over the 30 calibration quadrats, 18 of 30 folds, p = 0.26. It was first
    attributed the whole +0.0098 gap between the stack and composite read paths; measuring
    it alone showed it accounts for about a third of that, and the remainder is still
    unexplained -- most likely the stack's 200 m margin changing which pixels edge footprints
    sample, or a different scene set.

    Kept on CORRECTNESS grounds rather than for the number: a read should not silently
    resample its source, and the composite's own pixels are the truth. Note it does change
    feature values, so anything calibrated on the old path shifts slightly.
    """
    px, py = abs(transform.a), abs(transform.e)
    x0, y0, x1, y1 = bounds
    ox, oy = transform.c, transform.f
    import math
    return (ox + math.floor((x0 - ox) / px) * px,
            oy - math.ceil((oy - y0) / py) * py,
            ox + math.ceil((x1 - ox) / px) * px,
            oy - math.floor((oy - y1) / py) * py)


class CompositeIndex:
    """Spatial index over `composites/<TILE>/composite_0.tif` COGs of one region.

    `layers=2` additionally reads each tile's `composite_1.tif` (a contrast-season
    composite on the same grid) and returns the windows channel-stacked
    [layer0 bands..., layer1 bands...]. Tiles missing composite_1 raise at read.
    """

    def __init__(self, region_dir: Path, layers: int = 1):
        self.region_dir = Path(region_dir)
        self.layers = layers
        rows = []
        for tif in sorted(self.region_dir.glob("composites/*/composite_0.tif")):
            try:
                with rasterio.open(tif) as src:
                    geom = box(*rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds))
                    rows.append({"path": str(tif), "crs": str(src.crs), "geometry": geom})
            except rasterio.errors.RasterioIOError as e:
                log.warning("skipping unreadable composite %s: %s", tif, e)
        if not rows:
            raise FileNotFoundError(f"No composites under {self.region_dir}/composites")
        self.index = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        log.info("Indexed %d composite tiles under %s", len(self.index), self.region_dir)

    @property
    def coverage(self):
        return self.index.union_all()

    def read_window(self, bbox: Bbox) -> tuple[np.ndarray, rasterio.Affine, CRS] | None:
        """Read a 4326-bbox window; mosaics across tiles. Returns None if uncovered.

        With layers=2 the result has both layers' bands stacked on axis 0.
        """
        hits = self.index[self.index.intersects(box(*bbox))]
        if hits.empty:
            return None
        # Prefer a single tile that fully covers the bbox (cheap path)
        full = hits[hits.covers(box(*bbox))]
        paths = [full.iloc[0].path] if not full.empty else list(hits.path)
        layer_arrays = []
        transform = dst_crs = None
        for layer in range(self.layers):
            lpaths = [str(Path(p).with_name(f"composite_{layer}.tif")) for p in paths]
            missing = [p for p in lpaths if not Path(p).exists()]
            if missing:
                raise FileNotFoundError(f"missing layer-{layer} composites: {missing[:3]}")
            srcs = [rasterio.open(p) for p in lpaths]
            try:
                dst_crs = srcs[0].crs
                wb = rasterio.warp.transform_bounds("EPSG:4326", dst_crs, *bbox)
                wb = _snap_bounds(wb, srcs[0].transform)
                arr, transform = rasterio.merge.merge(srcs, bounds=wb, nodata=0)
                layer_arrays.append(arr)
            finally:
                for s in srcs:
                    s.close()
        if len(layer_arrays) > 1:
            # Same grids by construction; guard off-by-one merge shapes.
            h = min(a.shape[1] for a in layer_arrays)
            w = min(a.shape[2] for a in layer_arrays)
            layer_arrays = [a[:, :h, :w] for a in layer_arrays]
        return np.concatenate(layer_arrays, axis=0), transform, dst_crs

    def read_sidecar_window(
        self, bbox: Bbox, name: str
    ) -> tuple[np.ndarray, rasterio.Affine, CRS] | None:
        """Read a per-tile sidecar raster (e.g. `temporal_stats_0.tif`) over a 4326 bbox.

        Same tile selection and mosaicking as `read_window`, against a differently-named
        file in the same cell directories. Returns None when the bbox is uncovered OR when
        any contributing tile has no such sidecar -- missing is a normal state (sidecars
        are written only by `compose --stats`), so this degrades to "no data" rather than
        raising the way a missing composite layer does.
        """
        hits = self.index[self.index.intersects(box(*bbox))]
        if hits.empty:
            return None
        full = hits[hits.covers(box(*bbox))]
        paths = [full.iloc[0].path] if not full.empty else list(hits.path)
        spaths = [Path(p).with_name(name) for p in paths]
        if any(not p.exists() for p in spaths):
            return None
        srcs = [rasterio.open(str(p)) for p in spaths]
        try:
            dst_crs = srcs[0].crs
            wb = rasterio.warp.transform_bounds("EPSG:4326", dst_crs, *bbox)
            arr, transform = rasterio.merge.merge(srcs, bounds=wb, nodata=0)
        finally:
            for s in srcs:
                s.close()
        return arr, transform, dst_crs


@lru_cache(maxsize=4)
def composite_index(region_dir: str, layers: int = 1) -> CompositeIndex:
    return CompositeIndex(Path(region_dir), layers=layers)


def load_solar_labels(region_dir: Path, min_area_m2: float = 400.0) -> gpd.GeoDataFrame:
    """Normalize rooftopsenti label artifacts to the earthpv label schema.

    labels.parquet = curated rooftop positives (>= region's min area, on-building
    or location=roof). solar.parquet = all OSM solar polygons; large off-building
    ones are added as ground-mount positives.
    """
    region_dir = Path(region_dir)
    rooftop = gpd.read_parquet(region_dir / "osm" / "labels.parquet")
    rooftop = rooftop.assign(placement="rooftop")

    out_cols = ["osm_id", "placement", "area_m2", "geometry"]
    solar_path = region_dir / "osm" / "solar.parquet"
    if solar_path.exists():
        allsolar = gpd.read_parquet(solar_path)
        allsolar = allsolar[allsolar.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        allsolar["area_m2"] = allsolar.geometry.to_crs("EPSG:6933").area
        ground = allsolar[
            (allsolar.area_m2 >= min_area_m2) & (~allsolar.osm_id.isin(set(rooftop.osm_id)))
        ].assign(placement="ground")
        labels = gpd.GeoDataFrame(
            gpd.pd.concat([rooftop[out_cols], ground[out_cols]], ignore_index=True),
            crs=rooftop.crs,
        )
        # Small arrays kept separately for ignore-masking during rasterization
        small = allsolar[allsolar.area_m2 < min_area_m2][out_cols[:1] + ["area_m2", "geometry"]]
        small = small.assign(placement="small")
        labels = gpd.GeoDataFrame(
            gpd.pd.concat([labels, small], ignore_index=True), crs=rooftop.crs
        )
    else:
        labels = rooftop[out_cols]
    return labels


def load_buildings(region_dir: Path) -> gpd.GeoDataFrame | None:
    """Large-building footprints (hard negatives / inference ROIs)."""
    region_dir = Path(region_dir)
    for rel in ("buildings/buildings_filtered.parquet", "osm/buildings.parquet"):
        p = region_dir / rel
        if p.exists():
            return gpd.read_parquet(p)
    return None
