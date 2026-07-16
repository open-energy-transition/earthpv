"""Turn probability chips into PV candidate polygons joined with buildings."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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


def _join_buildings_chunked(
    cands: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, chunk_deg: float = 1.0
) -> gpd.GeoDataFrame:
    """`_join_buildings_metric` per coarse spatial chunk of candidates.

    `_join_buildings_metric`'s own bbox buffer only prunes the buildings table when
    the CANDIDATES passed to it are already spatially tight — for a country-scale
    candidate set (spanning the whole VIDA extent in one call) it degenerates to
    reprojecting the ENTIRE buildings table (millions of rows) at once, which is what
    killed a whole-Pakistan postprocess run. Chunking candidates first keeps each
    call's candidate bbox small, so its internal `.cx[]` slice actually does its job.
    """
    if cands.empty:
        return cands
    reps = cands.geometry.representative_point()
    keys = list(zip(
        np.floor(reps.x.to_numpy() / chunk_deg).astype(int).tolist(),
        np.floor(reps.y.to_numpy() / chunk_deg).astype(int).tolist(),
    ))
    cands = cands.reset_index(drop=True)
    parts = []
    for key in sorted(set(keys)):
        mask = [k == key for k in keys]
        parts.append(_join_buildings_metric(cands[mask].reset_index(drop=True), buildings))
    log.info("Building join: %d candidates in %d spatial chunks", len(cands), len(parts))
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=cands.crs)


def _prob_raster_index(prob_dir: Path) -> gpd.GeoDataFrame:
    rows = []
    for tif in sorted(Path(prob_dir).glob("*.tif")):
        with rasterio.open(tif) as src:
            geom = shapely_box(*rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds))
            rows.append({"path": str(tif), "geometry": geom})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def add_epoch_prior(cands: gpd.GeoDataFrame, preboom_prob_dir: Path) -> gpd.GeoDataFrame:
    """Down-weight candidates that were already bright in the pre-boom (2021/22) epoch.

    Pakistan's rooftop PV stock is dominated by the post-2022 import boom, so a feature
    with high probability in BOTH epochs — a bright riverbed, rock outcrop, industrial
    roof, greenhouse — is likely a persistent false positive rather than new PV; one
    bright only in the current epoch is plausibly genuine. Cells with no pre-boom raster
    (no scenes in that window) are left neutral (`preboom_prob=0`) rather than penalised,
    since we can't check them. Nothing is dropped — same recall-first ranking-only
    contract as `building_prior`.
    """
    cands = cands.reset_index(drop=True).copy()
    cands["preboom_prob"] = 0.0
    if cands.empty:
        cands["epoch_prior"] = 1.0
        return cands
    tiles = _prob_raster_index(Path(preboom_prob_dir))
    if tiles.empty:
        log.warning("No pre-boom rasters under %s; epoch prior left neutral", preboom_prob_dir)
        cands["epoch_prior"] = 1.0
        return cands
    reps = gpd.GeoDataFrame(geometry=cands.geometry.representative_point(), crs=cands.crs)
    hits = gpd.sjoin(reps, tiles, predicate="within", how="left")
    for tif_path, idx in hits.dropna(subset=["path"]).groupby("path").groups.items():
        idx = list(idx)
        with rasterio.open(tif_path) as src:
            prob = src.read(1).astype("float32") / 255.0
            sub = cands.loc[idx].to_crs(src.crs)
            for i, geom in zip(idx, sub.geometry):
                mask = rio_features.geometry_mask(
                    [geom], out_shape=prob.shape, transform=src.transform, invert=True
                )
                if mask.any():
                    cands.loc[i, "preboom_prob"] = float(prob[mask].mean())
    cands["epoch_prior"] = (1.0 - cands["preboom_prob"]).clip(0.0, 1.0).round(3)
    return cands


def add_glint_prior(
    cands: gpd.GeoDataFrame, top_n: int = 300, lookback_days: int = 730,
    tol_deg: float = 3.0, min_consistent: int = 2, bonus: float = 0.2,
    max_workers: int = 4,
) -> gpd.GeoDataFrame:
    """Physics-based corroborator: does the candidate glint on dates geometrically
    consistent with one fixed panel orientation? A glass PV panel is partly a
    specular reflector; Sentinel-2 views near-nadir, so a fixed panel only glints
    when its tilt/azimuth happens to bisect the sun and sensor at the ~10:30 overpass
    (see `earthpv.glint`). Validated against known German and Punjab installations:
    self-consistent multi-date glint recovers the true panel orientation cleanly, but
    **absence of glint is common even for real arrays** (wrong orientation for this
    geometry — ~30% of confirmed installations showed zero spikes over 2 years), so
    this is reward-only: candidates with no or inconsistent glint are left unchanged,
    never down-weighted. Confirmed candidates get a small rank_score bonus (up to
    `1 + bonus`, saturating at 4 mutually-consistent spike dates).

    This is a network-bound per-candidate Sentinel-2 time-series pull (dozens to
    hundreds of scene reads each), impractical at country scale for every polygon —
    bounded to the current top `top_n` by rank_score.
    """
    cands = cands.reset_index(drop=True).copy()
    cands["glint_spikes"] = 0
    cands["glint_consistent"] = 0
    cands["glint_fit_tilt"] = np.nan
    cands["glint_fit_az"] = np.nan
    cands["glint_prior"] = 0.0
    if cands.empty or "rank_score" not in cands.columns:
        return cands

    from earthpv import glint

    idx = cands["rank_score"].to_numpy().argsort()[::-1][:top_n]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    def _check(i: int):
        series = glint.scene_series(cands.geometry.iloc[i], start, end, n_threads=6)
        if series.empty:
            return i, None
        return i, glint.spike_fit(series, tol_deg=tol_deg)

    log.info("Glint check: pulling Sentinel-2 time series for top %d candidates", len(idx))
    with ThreadPoolExecutor(max_workers) as ex:
        futs = [ex.submit(_check, int(i)) for i in idx]
        for f in tqdm(as_completed(futs), total=len(futs), desc="glint"):
            i, res = f.result()
            if not res:
                continue
            cands.loc[i, "glint_spikes"] = res["n_spikes"]
            cands.loc[i, "glint_consistent"] = res["n_consistent"]
            cands.loc[i, "glint_fit_tilt"] = res["fit_tilt"]
            cands.loc[i, "glint_fit_az"] = res["fit_az"]

    consistent = cands["glint_consistent"].to_numpy(float)
    confidence = np.clip(consistent / 4.0, 0.0, 1.0)
    confidence[consistent < min_consistent] = 0.0
    cands["glint_prior"] = confidence.round(3)
    cands["rank_score"] = (cands["rank_score"] * (1.0 + bonus * confidence)).round(4)
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


def run_postprocess(
    aoi: str, pred_dir: Path, threshold: float = 0.3, max_building_dist_m: float = 0.0,
    preboom_prob_dir: Path | None = None,
    check_glint: bool = False, glint_top_n: int = 300,
) -> Path:
    """`max_building_dist_m` (0 = disabled) drops candidates whose nearest building is
    farther than this — isolated detections (cropland glare, bare soil, water glint)
    are the dominant false-positive mode away from any structure. Only applies where
    a real distance was resolved (`_join_buildings_metric`, i.e. VIDA/local buildings
    available); candidates with no distance signal at all (`-1`, e.g. the Overture
    fallback join or no buildings anywhere in the AOI) are left alone rather than
    dropped on missing information."""
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
            cands = _join_buildings_chunked(cands, buildings)
        else:
            # Last resort: remote Overture join (no metric signals for ranking).
            cands = attach_buildings(cands, settings)
        cands = _add_ranking(cands)
        if preboom_prob_dir:
            cands = add_epoch_prior(cands, preboom_prob_dir)
            cands["rank_score"] = (
                cands["rank_score"] * (0.5 + 0.5 * cands["epoch_prior"])
            ).round(4)
            log.info("Epoch-diff rescoring applied from %s", preboom_prob_dir)
        if check_glint:
            cands = add_glint_prior(cands, top_n=glint_top_n)
            log.info("Glint-consistency check applied to top %d candidates", glint_top_n)
        cands = cands.sort_values("rank_score", ascending=False).reset_index(drop=True)
        if max_building_dist_m and "building_dist_m" in cands.columns:
            n_before = len(cands)
            dist = cands["building_dist_m"].to_numpy(float)
            keep = (dist < 0) | (dist <= max_building_dist_m)
            cands = cands[keep].reset_index(drop=True)
            log.info(
                "Dropped %d/%d candidates > %.0f m from the nearest building",
                n_before - len(cands), n_before, max_building_dist_m,
            )
    out = Path(pred_dir) / aoi / "candidates.parquet"
    cands.to_parquet(out)
    log.info("Wrote %s (%s)", out,
             cands.placement.value_counts().to_dict() if not cands.empty else "empty")
    return out
