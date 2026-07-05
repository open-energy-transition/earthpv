"""Turn probability chips into PV candidate polygons joined with buildings."""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from shapely.geometry import box as shapely_box
from shapely.geometry import shape
from shapely.ops import unary_union
from tqdm import tqdm

from earthpv import overture
from earthpv.buildings import load_dense_buildings
from earthpv.config import Settings
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.local_source import load_buildings

log = logging.getLogger(__name__)

# A candidate whose nearest footprint is within this gap counts as building-adjacent.
NEAR_BUILDING_M = 30.0


def polygonize_chips(prob_dir: Path, threshold: float) -> gpd.GeoDataFrame:
    parts = []
    tifs = sorted(prob_dir.glob("*.tif"))
    for tif in tqdm(tifs, desc="polygonize"):
        geoms, confs = [], []
        with rasterio.open(tif) as src:
            prob = src.read(1).astype("float32") / 255.0
            hot = (prob >= threshold).astype("uint8")
            if hot.sum() == 0:
                continue
            for geom, _ in rio_features.shapes(hot, mask=hot.astype(bool), transform=src.transform):
                sel = rio_features.geometry_mask(
                    [geom], out_shape=prob.shape, transform=src.transform, invert=True
                )
                geoms.append(shape(geom))
                confs.append(float(prob[sel].max()))
            crs = src.crs
        if geoms:
            # Windows are in per-tile UTM; reproject each tile's polygons to WGS84.
            parts.append(
                gpd.GeoDataFrame({"confidence": confs}, geometry=geoms, crs=crs).to_crs("EPSG:4326")
            )
    if not parts:
        return gpd.GeoDataFrame({"confidence": []}, geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    if gdf.empty:
        return gdf
    # Merge fragments across overlapping chips
    merged = gpd.GeoDataFrame(
        geometry=list(unary_union(gdf.geometry.values).geoms)
        if gdf.union_all().geom_type == "MultiPolygon"
        else [gdf.union_all()],
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(merged, gdf, how="left", predicate="intersects")
    conf = joined.groupby(joined.index)["confidence"].max()
    merged["confidence"] = conf
    return merged


def _join_buildings_metric(
    cands: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, near_m: float = NEAR_BUILDING_M
) -> gpd.GeoDataFrame:
    """Classify candidates against a footprint set and record the metric signals used
    for re-ranking: overlap fraction with the nearest roof and gap to the nearest one.

    Work is done in the candidates' local UTM zone so intersection areas and the
    nearest-building distance come out in metres. Buildings are pre-clipped to the
    candidates' extent so a country-scale (VIDA) set reprojects cheaply.
    """
    cands = cands.reset_index(drop=True).copy()
    minx, miny, maxx, maxy = cands.total_bounds
    buf = 0.02  # ~2 km pad so nearest-building gaps just outside the extent still resolve
    near = buildings.cx[minx - buf : maxx + buf, miny - buf : maxy + buf]
    n = len(cands)
    cands["placement"] = "no_building"
    cands["building_id"] = None
    cands["building_overlap_frac"] = 0.0
    cands["building_dist_m"] = -1.0
    if near.empty:
        log.info("No buildings within the candidate extent; all -> no_building")
        return cands

    lon = (minx + maxx) / 2
    lat = (miny + maxy) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
    cu = cands.to_crs(epsg)
    bu = near.to_crs(epsg).reset_index(drop=True)
    id_col = "id" if "id" in bu.columns else bu.columns[0]
    sindex = bu.sindex

    frac = np.zeros(n)
    dist = np.full(n, np.inf)
    bid: list[str | None] = [None] * n
    # One nearest-neighbour query for every candidate (metres in this UTM zone).
    idx, d = sindex.nearest(cu.geometry.values, return_all=False, return_distance=True)
    for k in range(idx.shape[1]):
        ci, ti = int(idx[0, k]), int(idx[1, k])
        dist[ci] = float(d[k])
        bid[ci] = str(bu.iloc[ti][id_col])
    # Total overlap fraction only matters for candidates that actually sit on roofs.
    for ci in np.where(dist < 1e-6)[0]:
        g = cu.geometry.iloc[ci]
        hits = sindex.query(g, predicate="intersects")
        if len(hits) == 0:
            continue
        inter = sum(g.intersection(bu.geometry.iloc[int(h)]).area for h in hits)
        frac[ci] = inter / max(g.area, 1e-6)

    placement = np.where(
        frac >= 0.3, "rooftop", np.where(dist <= near_m, "ground_adjacent", "no_building")
    )
    cands["placement"] = placement
    cands["building_overlap_frac"] = frac.round(3)
    cands["building_dist_m"] = np.where(np.isfinite(dist), dist, -1.0).round(1)
    cands["building_id"] = bid
    cands.loc[cands.placement == "no_building", "building_id"] = None
    return cands


def _add_ranking(cands: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Blend model confidence with a building prior into a `rank_score` for triage.

    The prior rewards sitting on (overlap) or beside (small gap) a footprint, but
    never drops to zero — a high-confidence detection with no nearby building (an
    unmapped roof or a ground-mount farm, both valid targets) still surfaces. So this
    only re-orders the human-validation queue; it never removes a candidate.
    """
    cands = cands.copy()
    frac = cands.get("building_overlap_frac", pd.Series(0.0, index=cands.index)).to_numpy(float)
    dist = cands.get("building_dist_m", pd.Series(-1.0, index=cands.index)).to_numpy(float).copy()
    dist[dist < 0] = 1e6  # no building found -> treat as very far
    on_roof = np.clip(frac / 0.5, 0.0, 1.0)          # 1.0 once >= 50% sits on a roof
    beside = 0.5 * np.exp(-dist / NEAR_BUILDING_M)    # up to 0.5 just off a roof, decaying
    prior = np.clip(np.maximum(np.maximum(on_roof, beside), 0.15), 0.0, 1.0)
    conf = cands["confidence"].fillna(0.0).to_numpy(float)
    cands["building_prior"] = prior.round(3)
    cands["rank_score"] = (conf * (0.5 + 0.5 * prior)).round(4)
    return cands


def attach_buildings(cands: gpd.GeoDataFrame, settings: Settings) -> gpd.GeoDataFrame:
    """Spatial join with Overture buildings per 0.25 deg cell -> placement column."""
    cands = cands.copy()
    cands["placement"] = "no_building"
    cands["building_id"] = None
    cells = sorted(
        {(np.floor(b[0] / 0.25), np.floor(b[1] / 0.25)) for b in (g.bounds for g in cands.geometry)}
    )
    log.info("Joining %d candidates with Overture buildings in %d cells", len(cands), len(cells))
    con = overture.connect()
    for cx, cy in tqdm(cells, desc="buildings"):
        cell_bbox = (cx * 0.25, cy * 0.25, (cx + 1) * 0.25, (cy + 1) * 0.25)
        sub = cands[cands.geometry.intersects(shapely_box(*cell_bbox))]
        if sub.empty:
            continue
        buildings = overture.fetch_buildings(cell_bbox, settings, con,
                                             min_bbox_area_m2=settings.min_roof_area_m2 / 2)
        if buildings.empty:
            continue
        sindex = buildings.sindex
        for idx, geom in sub.geometry.items():
            hits = sindex.query(geom, predicate="intersects")
            if len(hits) == 0:
                continue
            cand_b = buildings.iloc[hits]
            inter_areas = [geodesic_area_m2(geom.intersection(b)) for b in cand_b.geometry]
            best = int(np.argmax(inter_areas))
            frac = inter_areas[best] / max(geodesic_area_m2(geom), 1e-6)
            cands.loc[idx, "placement"] = "rooftop" if frac >= 0.3 else "ground_adjacent"
            cands.loc[idx, "building_id"] = cand_b.iloc[best]["id"]
    return cands


def _resolve_buildings(
    aoi: str, cands: gpd.GeoDataFrame, cfg: dict, settings: Settings, pred_dir: Path
) -> gpd.GeoDataFrame | None:
    """Best available footprint set for the candidate extent.

    VIDA (imagery-derived, includes small/unmapped buildings — the strongest prior)
    is tried first and cached; the rooftopsenti local set (Overture, >= 500 m2) is
    the fallback. Both feed the same metric join.
    """
    dense = load_dense_buildings(aoi, cands, cfg, settings, Path(pred_dir) / aoi / "buildings")
    if dense is not None and not dense.empty:
        return dense
    source_region = cfg.get("source_region")
    if source_region:
        local = load_buildings(Path(settings.raw["local_root"]) / source_region)
        if local is not None and not local.empty:
            log.info("Falling back to %d local (Overture >=500 m2) buildings", len(local))
            return local
    return None


def run_postprocess(aoi: str, pred_dir: Path, threshold: float = 0.3) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    prob_dir = Path(pred_dir) / aoi / "prob"
    cands = polygonize_chips(prob_dir, threshold)
    log.info("Polygonized %d candidates at threshold %.2f", len(cands), threshold)
    if not cands.empty:
        cands["area_m2"] = [geodesic_area_m2(g) for g in cands.geometry]
        cands = cands[cands.area_m2 >= 50].reset_index(drop=True)
        _, cfg = resolve_aoi(aoi, settings)
        buildings = _resolve_buildings(aoi, cands, cfg, settings, pred_dir)
        if buildings is not None and not buildings.empty:
            log.info("Joining %d candidates with %d buildings", len(cands), len(buildings))
            cands = _join_buildings_metric(cands, buildings)
        else:
            # Last resort: remote Overture join (no metric signals for ranking).
            cands = attach_buildings(cands, settings)
        cands = _add_ranking(cands)
        cands = cands.sort_values("rank_score", ascending=False).reset_index(drop=True)
    out = Path(pred_dir) / aoi / "candidates.parquet"
    cands.to_parquet(out)
    log.info("Wrote %s (%s)", out,
             cands.placement.value_counts().to_dict() if not cands.empty else "empty")
    return out
