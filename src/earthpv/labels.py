"""Build PV label datasets from Overture (OSM-derived) solar features.

Placement logic:
- OSM `location=roof` / `generator:place=roof` -> rooftop
- power=plant perimeters -> ground-mount
- remaining polygons -> classified by overlap with Overture building footprints
- point features are kept for evaluation only (no polygon to burn into masks)
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely.geometry import box

from earthpv import overture
from earthpv.config import Settings

log = logging.getLogger(__name__)
_GEOD = Geod(ellps="WGS84")


def geodesic_area_m2(geom) -> float:
    """Unsigned geodesic area — CRS-free, works globally."""
    if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return 0.0
    area, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(area)


def resolve_aoi(aoi: str, settings: Settings) -> tuple[tuple[float, float, float, float], dict]:
    cfg = settings.aois.get(aoi)
    if cfg is None:
        raise KeyError(f"AOI '{aoi}' not in configs/aoi.yaml (have: {list(settings.aois)})")
    return tuple(cfg["bbox"]), cfg


def classify_placement(
    solar: gpd.GeoDataFrame, con, settings: Settings, overlap_frac: float
) -> gpd.GeoDataFrame:
    solar = solar.copy()
    solar["placement"] = "unknown"

    roofish = solar["osm_location"].isin(["roof", "rooftop"]) | solar["generator_place"].isin(
        ["roof", "rooftop"]
    )
    solar.loc[roofish, "placement"] = "rooftop"
    solar.loc[(solar["kind"] == "plant") & ~roofish, "placement"] = "ground"

    # Remaining polygons: check overlap with buildings, cluster by 0.25 deg cells
    # so each Overture query stays small.
    todo = solar[(solar["placement"] == "unknown") & (solar.geom_type != "Point")]
    if todo.empty:
        return solar
    cells = set()
    for geom in todo.geometry:
        b = geom.bounds
        cells.add((np.floor(b[0] / 0.25), np.floor(b[1] / 0.25)))
    log.info("Classifying %d unknown polygons via buildings in %d cells", len(todo), len(cells))
    for cx, cy in sorted(cells):
        cell_bbox = (cx * 0.25, cy * 0.25, (cx + 1) * 0.25, (cy + 1) * 0.25)
        in_cell = todo[todo.geometry.intersects(box(*cell_bbox))]
        if in_cell.empty:
            continue
        buildings = overture.fetch_buildings(cell_bbox, settings, con)
        if buildings.empty:
            solar.loc[in_cell.index, "placement"] = "ground"
            continue
        sindex = buildings.sindex
        for idx, geom in in_cell.geometry.items():
            cand = buildings.geometry.iloc[sindex.query(geom, predicate="intersects")]
            if len(cand) == 0:
                solar.loc[idx, "placement"] = "ground"
                continue
            inter = cand.intersection(geom)
            frac = sum(geodesic_area_m2(g) for g in inter) / max(geodesic_area_m2(geom), 1e-6)
            solar.loc[idx, "placement"] = "rooftop" if frac >= overlap_frac else "ground"
        todo = todo.drop(index=in_cell.index)
    return solar


def build_labels(aoi: str, out_dir: Path) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    bbox, cfg = resolve_aoi(aoi, settings)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = overture.connect()

    log.info("Fetching solar features for %s bbox=%s (release %s)", aoi, bbox, settings.overture_release)
    solar = overture.fetch_solar(bbox, settings, con)
    log.info("Fetched %d solar features (%d polygons)", len(solar), (solar.geom_type != "Point").sum())
    if solar.empty:
        raise RuntimeError(
            "No solar features returned — check that Overture source_tags carry "
            "generator:source (fallback: Overpass API)."
        )

    solar = classify_placement(solar, con, settings, settings.rooftop_overlap_frac)
    solar["area_m2"] = [geodesic_area_m2(g) for g in solar.geometry]
    solar["geom_type"] = solar.geom_type

    # Optional: clip to the actual division polygon, attach region for train/val split
    if "division" in cfg:
        d = cfg["division"]
        regions = overture.fetch_regions(d["country"], settings, con)
        if not regions.empty:
            regions.to_parquet(out_dir / f"{aoi}_regions.parquet")
            solar = gpd.sjoin(
                solar, regions[["name", "geometry"]], how="left", predicate="intersects"
            ).drop(columns=["index_right"]).rename(columns={"name": "region"})
            solar = solar[~solar.index.duplicated(keep="first")]

    out = out_dir / f"{aoi}_solar.parquet"
    solar.to_parquet(out)
    n_poly = ((solar.geom_type != "Point") & (solar.area_m2 >= 100)).sum()
    log.info(
        "Wrote %s: %d features | polygons>=100m2: %d | rooftop: %d | ground: %d",
        out, len(solar), n_poly,
        (solar.placement == "rooftop").sum(), (solar.placement == "ground").sum(),
    )
    return out
