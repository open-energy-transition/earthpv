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
import pandas as pd
import rasterio
import rasterio.merge
import rasterio.warp
from rasterio.crs import CRS
from shapely.geometry import box

log = logging.getLogger(__name__)

Bbox = tuple[float, float, float, float]


class CompositeIndex:
    """Spatial index over `composites/<TILE>/composite_0.tif` COGs of one region."""

    def __init__(self, region_dir: Path):
        self.region_dir = Path(region_dir)
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
        """Read a 4326-bbox window; mosaics across tiles. Returns None if uncovered."""
        hits = self.index[self.index.intersects(box(*bbox))]
        if hits.empty:
            return None
        # Prefer a single tile that fully covers the bbox (cheap path)
        full = hits[hits.covers(box(*bbox))]
        paths = [full.iloc[0].path] if not full.empty else list(hits.path)
        srcs = [rasterio.open(p) for p in paths]
        try:
            dst_crs = srcs[0].crs
            wb = rasterio.warp.transform_bounds("EPSG:4326", dst_crs, *bbox)
            arr, transform = rasterio.merge.merge(srcs, bounds=wb, nodata=0)
            return arr, transform, dst_crs
        finally:
            for s in srcs:
                s.close()


@lru_cache(maxsize=4)
def composite_index(region_dir: str) -> CompositeIndex:
    return CompositeIndex(Path(region_dir))


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
