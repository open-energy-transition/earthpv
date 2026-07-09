"""Per-building PV density and PyPSA-ready grid / admin-region aggregates.

The `infer -> postprocess -> export` chain produces *individual installation
candidates* for human OSM validation. This stage instead answers "how much PV sits
on the buildings of each area" — the input energy-system models (PyPSA / PyPSA-Earth)
actually consume. It runs entirely on the artifacts already on disk (per-cell
probability rasters + `candidates.parquet` + the VIDA building footprints); no GPU,
no retraining.

Two PV-area metrics are reported per building, because the model is deliberately
recall-first (many false positives) and neither number is unconditionally honest:

- **detected** (`*_det`): area of the thresholded, merged `candidates.parquet`
  polygons intersecting the footprint. Crisp, consistent with the human-facing
  product; the precision-honest floor.
- **expected** (`*_exp`): probability-weighted area, sum of per-pixel probability
  (above a small noise floor) times 100 m² over the footprint. Integrates
  sub-threshold signal; an upper-leaning expectation for sensitivity bands.

Three layers are written to `data/predictions/<aoi>/density/`:
  buildings.geoparquet  — one row per building carrying a PV signal
  grid.geoparquet/.csv  — one row per 0.1 deg cell (the pipeline's native grid)
  regions.*             — one row per Overture province (and optionally district)

Double counting is avoided at the source: adjacent per-cell rasters overlap by a
few pixels, so every building is assigned to exactly one cell by its representative
point, and each cell's building-independent raster sum is cropped to the canonical
0.1 deg box (see `cell_manifest`).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.transform
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform
from shapely.geometry import box as shapely_box
from shapely.geometry import shape as shapely_shape
from tqdm import tqdm

from earthpv import overture
from earthpv.buildings import _iso3_for, fetch_vida_buildings
from earthpv.compose import CELL_DEG, _aoi_boundary
from earthpv.config import Settings
from earthpv.labels import geodesic_area_m2, resolve_aoi

log = logging.getLogger(__name__)

PIXEL_M2 = 100.0  # 10 m x 10 m Sentinel-2 pixel
# kWp per m2 of detected panel area. ~5.5 m2 of c-Si module per kWp -> ~0.18 kWp/m2.
# The model detects the dark panel area itself, so this maps area -> capacity directly.
DEFAULT_KWP_PER_M2 = 0.18

# Additive per-cell columns summed up into region totals (never average ratios).
_SUM_COLS = [
    "n_buildings", "roof_area_m2", "n_pv_buildings",
    "pv_area_det_roof_m2", "pv_area_det_total_m2", "pv_area_det_roofcand_m2",
    "pv_area_exp_m2", "pv_area_exp_roof_m2",
]


# --------------------------------------------------------------------------------------
# Cell bookkeeping
# --------------------------------------------------------------------------------------
def _grid_origin(aoi: str, cfg: dict, settings: Settings) -> tuple[float, float]:
    """The (minx, miny) origin of the 0.1 deg cell grid, replicating compose exactly.

    compose snaps the AOI boundary's lower-left to `grid_origin` (mod CELL_DEG); the
    canonical cell names inference wrote derive from this origin, so we must match it
    bit-for-bit to decode raster centres back to canonical (ix, iy).
    """
    boundary = _aoi_boundary(aoi, cfg, settings)
    bbox = tuple(boundary.total_bounds) if boundary is not None else tuple(cfg["bbox"])
    minx, miny = bbox[0], bbox[1]
    if cfg.get("grid_origin"):
        gx, gy = cfg["grid_origin"]
        minx = gx + np.floor((minx - gx) / CELL_DEG) * CELL_DEG
        miny = gy + np.floor((miny - gy) / CELL_DEG) * CELL_DEG
    return float(minx), float(miny)


def cell_manifest(prob_dir: Path, origin: tuple[float, float]) -> gpd.GeoDataFrame:
    """Map every probability raster to its canonical 0.1 deg cell, deduping overlaps.

    A handful of rasters carry legacy off-grid names (a different AOI's grid origin)
    whose coverage duplicates a canonical cell. We key on the raster *centre* under
    this AOI's origin, and where several rasters land in one cell keep the one whose
    filename already equals the canonical name (else the first). This is the single
    source of truth for which raster serves which cell.
    """
    minx, miny = origin
    rows = []
    for tif in sorted(Path(prob_dir).glob("*.tif")):
        with rasterio.open(tif) as src:
            w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        cx, cy = (w + e) / 2, (s + n) / 2
        ix = int(np.floor((cx - minx) / CELL_DEG))
        iy = int(np.floor((cy - miny) / CELL_DEG))
        rows.append({"file": tif.stem, "path": str(tif), "ix": ix, "iy": iy})
    if not rows:
        raise FileNotFoundError(f"No probability rasters in {prob_dir}")

    df = pd.DataFrame(rows)
    df["cell"] = df.apply(lambda r: f"{r.ix:04d}_{r.iy:04d}", axis=1)
    kept, dropped = [], []
    for cell, grp in df.groupby("cell"):
        if len(grp) == 1:
            kept.append(grp.iloc[0])
            continue
        exact = grp[grp.file == cell]
        chosen = (exact.iloc[0] if len(exact) else grp.iloc[0])
        kept.append(chosen)
        dropped += [r.file for _, r in grp.iterrows() if r.path != chosen.path]
    if dropped:
        log.info("Deduped %d overlapping/off-grid rasters: %s", len(dropped), dropped)

    man = pd.DataFrame(kept).reset_index(drop=True)
    man["lon0"] = minx + man.ix * CELL_DEG
    man["lat0"] = miny + man.iy * CELL_DEG
    geom = [shapely_box(x, y, x + CELL_DEG, y + CELL_DEG) for x, y in zip(man.lon0, man.lat0)]
    return gpd.GeoDataFrame(man, geometry=geom, crs="EPSG:4326")


# --------------------------------------------------------------------------------------
# Per-cell zonal statistics
# --------------------------------------------------------------------------------------
def _canonical_window(src, lon0: float, lat0: float) -> Window:
    """Pixel window of the canonical 0.1 deg box within the raster (clipped to it).

    The raster is ~0.101 deg wide (overlaps its neighbours); cropping the
    building-independent expected-area sum to the exact box stops those overlap
    strips being counted in two cells.
    """
    w, s, e, n = transform_bounds(
        "EPSG:4326", src.crs, lon0, lat0, lon0 + CELL_DEG, lat0 + CELL_DEG
    )
    win = from_bounds(w, s, e, n, transform=src.transform).round_offsets().round_lengths()
    return win.intersection(Window(0, 0, src.width, src.height))


def per_building_raster_stats(
    bu_utm: gpd.GeoDataFrame, prob: np.ndarray, transform, min_prob: float
) -> pd.DataFrame:
    """Expected PV area, pixel count and peak probability per building.

    Buildings are rasterized to their footprint pixels at native 10 m
    (`all_touched=False`); ~half of Pakistani footprints are sub-pixel and get zero
    pixels this way, so those fall back to the probability of their centroid pixel
    times the footprint area. Expected area is capped at the roof area (a 100 m2
    pixel overhangs a small roof).
    """
    n = len(bu_utm)
    out = pd.DataFrame(
        {"pv_area_exp_m2": np.zeros(n), "n_px": np.zeros(n, int), "pv_prob_max": np.zeros(n)}
    )
    if n == 0:
        return out
    roof = bu_utm["area_m2"].to_numpy(float)
    idx = rasterio.features.rasterize(
        ((g, i) for i, g in enumerate(bu_utm.geometry, start=1)),
        out_shape=prob.shape, transform=transform, fill=0, all_touched=False, dtype="int32",
    )
    flat = idx.ravel()
    weighted = np.where(prob >= min_prob, prob, 0.0).ravel()
    exp_px = np.bincount(flat, weights=weighted, minlength=n + 1)[1:]
    n_px = np.bincount(flat, minlength=n + 1)[1:]
    max_p = np.zeros(n + 1)
    np.maximum.at(max_p, flat, prob.ravel())
    max_p = max_p[1:]

    pv_area = exp_px * PIXEL_M2
    zero = n_px == 0
    if zero.any():
        pts = bu_utm.geometry.representative_point()
        xs, ys = pts.x.to_numpy()[zero], pts.y.to_numpy()[zero]
        rr, cc = rasterio.transform.rowcol(transform, xs, ys)
        rr = np.clip(np.asarray(rr), 0, prob.shape[0] - 1)
        cc = np.clip(np.asarray(cc), 0, prob.shape[1] - 1)
        p_c = prob[rr, cc]
        p_c = np.where(p_c >= min_prob, p_c, 0.0)
        pv_area[zero] = p_c * roof[zero]
        max_p[zero] = prob[rr, cc]

    out["pv_area_exp_m2"] = np.minimum(pv_area, roof)
    out["n_px"] = n_px.astype(int)
    out["pv_prob_max"] = max_p
    return out


def per_building_detected(bu: gpd.GeoDataFrame, cands: gpd.GeoDataFrame) -> pd.DataFrame:
    """Thresholded PV area per building from the merged candidate polygons.

    For each candidate intersecting the cell, the footprint-candidate intersection
    area (geodesic) is added to every building it overlaps; the best-overlap
    candidate's confidence and placement are recorded. Area is capped at the roof.
    """
    n = len(bu)
    det = np.zeros(n)
    conf = np.full(n, np.nan)
    placement = np.array([""] * n, dtype=object)
    best_area = np.zeros(n)
    if n == 0 or cands.empty:
        return pd.DataFrame(
            {"pv_area_det_m2": det, "pv_conf_det": conf, "pv_placement": placement}
        )
    sindex = bu.sindex
    for cand in cands.itertuples():
        hits = sindex.query(cand.geometry, predicate="intersects")
        for bi in hits:
            inter = geodesic_area_m2(bu.geometry.iloc[bi].intersection(cand.geometry))
            if inter <= 0:
                continue
            det[bi] += inter
            if inter > best_area[bi]:
                best_area[bi] = inter
                conf[bi] = float(getattr(cand, "confidence", np.nan))
                placement[bi] = getattr(cand, "placement", "") or ""
    det = np.minimum(det, bu["area_m2"].to_numpy(float))
    return pd.DataFrame({"pv_area_det_m2": det, "pv_conf_det": conf, "pv_placement": placement})


def process_cell(
    row, cands: gpd.GeoDataFrame, con, iso3: str, min_prob: float,
    min_building_exp_m2: float, cells_dir: Path, force: bool,
) -> None:
    """Resumable per-cell unit: write buildings partial + one summary row."""
    part = cells_dir / f"{row.cell}.parquet"
    summ = cells_dir / f"{row.cell}.summary.parquet"
    if part.exists() and summ.exists() and not force:
        return

    lon0, lat0 = float(row.lon0), float(row.lat0)
    with rasterio.open(row.path) as src:
        win = _canonical_window(src, lon0, lat0)
        prob = src.read(1, window=win).astype("float32") / 255.0
        win_tf = window_transform(win, src.transform)
        crs = src.crs
        w4, s4, e4, n4 = transform_bounds(src.crs, "EPSG:4326", *src.bounds)

    # Buildings whose representative point falls in this cell's canonical box only
    # (half-open) so each building nationwide is processed by exactly one cell.
    bu = fetch_vida_buildings((w4, s4, e4, n4), iso3, con=con).reset_index(drop=True)
    if not bu.empty:
        rp = bu.geometry.representative_point()
        in_box = (
            (rp.x >= lon0) & (rp.x < lon0 + CELL_DEG)
            & (rp.y >= lat0) & (rp.y < lat0 + CELL_DEG)
        )
        bu = bu[in_box.to_numpy()].reset_index(drop=True)

    # Candidates intersecting the cell (for per-building detection) and those assigned
    # to it by representative point (for cell totals that reconcile with candidates.parquet).
    box_geom = shapely_box(lon0, lat0, lon0 + CELL_DEG, lat0 + CELL_DEG)
    cand_hits = (
        cands.iloc[cands.sindex.query(box_geom, predicate="intersects")]
        if not cands.empty else cands
    )
    if not cand_hits.empty:
        crp = cand_hits.geometry.representative_point()
        c_in = (
            (crp.x >= lon0) & (crp.x < lon0 + CELL_DEG)
            & (crp.y >= lat0) & (crp.y < lat0 + CELL_DEG)
        )
        cands_in = cand_hits[c_in.to_numpy()]
    else:
        cands_in = cand_hits

    n_buildings = len(bu)
    roof_area = float(bu["area_m2"].sum()) if n_buildings else 0.0
    # Building-independent expected area over the cropped box (no overlap double-count).
    exp_cell = float(np.where(prob >= min_prob, prob, 0.0).sum() * PIXEL_M2)

    if n_buildings:
        rstats = per_building_raster_stats(bu.to_crs(crs), prob, win_tf, min_prob)
        dstats = per_building_detected(bu, cand_hits)
        b = bu.copy()
        b["building_uid"] = [f"{row.cell}_{i:06d}" for i in range(n_buildings)]
        b["cell"] = row.cell
        rp = b.geometry.representative_point()
        b["lon"], b["lat"] = rp.x.to_numpy(), rp.y.to_numpy()
        b = b.rename(columns={"area_m2": "roof_area_m2"})
        b["pv_area_det_m2"] = dstats["pv_area_det_m2"].to_numpy()
        b["pv_area_exp_m2"] = rstats["pv_area_exp_m2"].to_numpy()
        b["pv_prob_max"] = rstats["pv_prob_max"].round(3).to_numpy()
        b["pv_conf_det"] = dstats["pv_conf_det"].to_numpy()
        b["pv_placement"] = dstats["pv_placement"].to_numpy()
        b["pv_ratio_det"] = (b.pv_area_det_m2 / b.roof_area_m2.clip(lower=1e-6)).clip(upper=1.0)
        b["pv_ratio_exp"] = (b.pv_area_exp_m2 / b.roof_area_m2.clip(lower=1e-6)).clip(upper=1.0)
        keep = (b.pv_area_det_m2 > 0) | (b.pv_area_exp_m2 >= min_building_exp_m2)
        cols = [
            "building_uid", "cell", "geometry", "lon", "lat", "roof_area_m2", "bf_confidence",
            "pv_area_det_m2", "pv_area_exp_m2", "pv_ratio_det", "pv_ratio_exp",
            "pv_conf_det", "pv_prob_max", "pv_placement",
        ]
        signal = gpd.GeoDataFrame(b[keep][cols], geometry="geometry", crs="EPSG:4326")
        summary = {
            "n_buildings": n_buildings,
            "roof_area_m2": roof_area,
            "n_pv_buildings": int((b.pv_area_det_m2 > 0).sum()),
            "pv_area_det_roof_m2": float(b.pv_area_det_m2.sum()),
            "pv_area_exp_roof_m2": float(b.pv_area_exp_m2.sum()),
        }
    else:
        signal = gpd.GeoDataFrame(
            {c: [] for c in [
                "building_uid", "cell", "lon", "lat", "roof_area_m2", "bf_confidence",
                "pv_area_det_m2", "pv_area_exp_m2", "pv_ratio_det", "pv_ratio_exp",
                "pv_conf_det", "pv_prob_max", "pv_placement"]},
            geometry=[], crs="EPSG:4326",
        )
        summary = {
            "n_buildings": 0, "roof_area_m2": 0.0, "n_pv_buildings": 0,
            "pv_area_det_roof_m2": 0.0, "pv_area_exp_roof_m2": 0.0,
        }

    summary.update({
        "cell": row.cell, "ix": int(row.ix), "iy": int(row.iy),
        "lon0": lon0, "lat0": lat0,
        "pv_area_exp_m2": exp_cell,
        "pv_area_det_total_m2": float(cands_in["area_m2"].sum()) if not cands_in.empty else 0.0,
        "pv_area_det_roofcand_m2": (
            float(cands_in[cands_in.placement == "rooftop"]["area_m2"].sum())
            if not cands_in.empty else 0.0
        ),
    })

    cells_dir.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".parquet.tmp")
    signal.to_parquet(tmp)
    tmp.rename(part)
    tmp = summ.with_suffix(".parquet.tmp")
    pd.DataFrame([summary]).to_parquet(tmp)
    tmp.rename(summ)


# --------------------------------------------------------------------------------------
# Admin regions
# --------------------------------------------------------------------------------------
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{level}/"


def fetch_geoboundaries(iso3: str, level: str) -> gpd.GeoDataFrame | None:
    """Admin polygons from geoBoundaries (open data, CC-BY): level 'ADM1' = provinces,
    'ADM2' = districts.

    This is the admin source in practice because Overture's S3 divisions endpoint
    times out from this machine even bbox-pruned; geoBoundaries is a light CDN fetch.
    """
    try:
        meta = json.load(urllib.request.urlopen(
            GEOBOUNDARIES_API.format(iso3=iso3, level=level), timeout=60))
        gj = json.load(urllib.request.urlopen(meta["gjDownloadURL"], timeout=120))
    except Exception as e:  # noqa: BLE001 — network failures degrade to no layer
        log.warning("geoBoundaries %s/%s fetch failed: %s", iso3, level, e)
        return None
    feats = gj.get("features", [])
    if not feats:
        return None
    rows = [{
        "id": f["properties"].get("shapeID"),
        "name": f["properties"].get("shapeName"),
        "country": f["properties"].get("shapeGroup", iso3),
        "geometry": shapely_shape(f["geometry"]),
    } for f in feats]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def load_admin(
    aoi: str, cfg: dict, settings: Settings, iso3: str, labels_dir: Path,
    districts: bool, regions_file: Path | None,
) -> tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None]:
    """Province (and optional district) polygons.

    Order per level: explicit `--regions-file` (regions only) -> cached parquet ->
    geoBoundaries -> Overture divisions. Any failure degrades to no layer for that
    level (with a rerun hint) rather than aborting the whole run.
    """
    country = (cfg.get("division") or {}).get("country")

    def _load(kind: str, subtype: str, adm: str) -> gpd.GeoDataFrame | None:
        if regions_file and kind == "region":
            return gpd.read_parquet(regions_file).to_crs("EPSG:4326")
        cache = Path(labels_dir) / f"{aoi}_{kind}s.parquet"
        if cache.exists():
            log.info("Using cached %s polygons %s", kind, cache)
            return gpd.read_parquet(cache).to_crs("EPSG:4326")
        gdf = fetch_geoboundaries(iso3, adm)
        if (gdf is None or gdf.empty) and country is not None:
            try:
                gdf = overture.fetch_regions(country, settings, subtype=subtype)
            except Exception as e:  # noqa: BLE001 — Overture S3 timeouts must not kill the run
                log.warning("Overture %s fetch failed (%s)", kind, e)
                gdf = None
        if gdf is None or gdf.empty:
            log.warning("No %s polygons available; layer skipped. Pass --regions-file to supply "
                        "them.", kind)
            return None
        Path(labels_dir).mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(cache)
        return gdf.to_crs("EPSG:4326")

    regions = _load("region", "region", "ADM1")
    dist = _load("district", "county", "ADM2") if districts else None
    return regions, dist


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------
def _ratios(df: pd.DataFrame, area_km2: pd.Series, kwp_per_m2: float) -> pd.DataFrame:
    df = df.copy()
    roof = df["roof_area_m2"].clip(lower=1e-6)
    df["pv_ratio_det"] = (df.pv_area_det_roof_m2 / roof).clip(upper=1.0).round(4)
    df["pv_ratio_exp"] = (df.pv_area_exp_roof_m2 / roof).clip(upper=1.0).round(4)
    df["pv_det_m2_per_km2"] = (df.pv_area_det_roof_m2 / area_km2.clip(lower=1e-9)).round(2)
    df["pv_exp_m2_per_km2"] = (df.pv_area_exp_roof_m2 / area_km2.clip(lower=1e-9)).round(2)
    df["est_mwp_det"] = (df.pv_area_det_roof_m2 * kwp_per_m2 / 1000.0).round(4)
    df["est_mwp_exp"] = (df.pv_area_exp_roof_m2 * kwp_per_m2 / 1000.0).round(4)
    return df


def aggregate(
    out_dir: Path, manifest: gpd.GeoDataFrame, regions: gpd.GeoDataFrame | None,
    districts: gpd.GeoDataFrame | None, kwp_per_m2: float,
) -> dict:
    cells_dir = out_dir / "cells"

    # Per-building layer -------------------------------------------------------------
    parts = [gpd.read_parquet(p) for p in sorted(cells_dir.glob("*.parquet"))
             if not p.name.endswith(".summary.parquet")]
    buildings = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    ) if parts else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    if not buildings.empty:
        buildings["est_kwp_det"] = (buildings.pv_area_det_m2 * kwp_per_m2).round(3)
        buildings["est_kwp_exp"] = (buildings.pv_area_exp_m2 * kwp_per_m2).round(3)
        pts = gpd.GeoDataFrame(
            geometry=gpd.points_from_xy(buildings.lon, buildings.lat), crs="EPSG:4326"
        )
        for gdf, col in ((regions, "region"), (districts, "district")):
            if gdf is not None and not gdf.empty:
                j = gpd.sjoin(pts, gdf[["name", "geometry"]], how="left", predicate="within")
                buildings[col] = j["name"].to_numpy()[: len(buildings)]
            else:
                buildings[col] = None
    buildings.to_parquet(out_dir / "buildings.geoparquet")

    # 0.1 deg grid layer -------------------------------------------------------------
    summ = pd.concat(
        [pd.read_parquet(p) for p in sorted(cells_dir.glob("*.summary.parquet"))],
        ignore_index=True,
    )
    grid = manifest[["cell", "ix", "iy", "lon0", "lat0", "geometry"]].merge(
        summ.drop(columns=["ix", "iy", "lon0", "lat0"]), on="cell", how="left"
    )
    grid = gpd.GeoDataFrame(grid, geometry="geometry", crs="EPSG:4326")
    grid[_SUM_COLS] = grid[_SUM_COLS].fillna(0.0)
    grid["lon_center"] = grid.lon0 + CELL_DEG / 2
    grid["lat_center"] = grid.lat0 + CELL_DEG / 2
    grid["cell_area_km2"] = [geodesic_area_m2(g) / 1e6 for g in grid.geometry]
    grid = _ratios(grid, grid["cell_area_km2"], kwp_per_m2)
    grid.to_parquet(out_dir / "grid.geoparquet")
    grid.drop(columns="geometry").to_csv(out_dir / "grid.csv", index=False)

    # Admin-region layer -------------------------------------------------------------
    n_regions = 0
    if regions is not None and not regions.empty:
        centroids = gpd.GeoDataFrame(
            grid[["cell"] + _SUM_COLS],
            geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs="EPSG:4326",
        )
        frames = []
        for gdf, level in ((regions, "region"), (districts, "county")):
            if gdf is None or gdf.empty:
                continue
            j = gpd.sjoin(centroids, gdf[["id", "name", "geometry"]], how="inner",
                          predicate="within")
            agg = j.groupby(["id", "name"], as_index=False).agg(
                {**{c: "sum" for c in _SUM_COLS}, "cell": "count"}
            ).rename(columns={"cell": "n_cells"})
            agg = agg.merge(gdf[["id", "name", "country", "geometry"]], on=["id", "name"])
            agg = gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")
            agg["level"] = level
            agg["area_km2"] = [geodesic_area_m2(g) / 1e6 for g in agg.geometry]
            agg = _ratios(agg, agg["area_km2"], kwp_per_m2)
            frames.append(agg.rename(columns={"id": "region_id"}))
        if frames:
            reg = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
            reg.to_parquet(out_dir / "regions.geoparquet")
            reg.drop(columns="geometry").to_csv(out_dir / "regions.csv", index=False)
            reg.to_file(out_dir / "regions.geojson", driver="GeoJSON")
            n_regions = int((reg.level == "region").sum())

    return {
        "n_cells": int(len(grid)),
        "n_signal_buildings": int(len(buildings)),
        "n_regions": n_regions,
        "total_pv_area_det_total_m2": float(grid.pv_area_det_total_m2.sum()),
        "total_pv_area_det_roofcand_m2": float(grid.pv_area_det_roofcand_m2.sum()),
        "total_pv_area_det_roof_m2": float(grid.pv_area_det_roof_m2.sum()),
        "total_pv_area_exp_roof_m2": float(grid.pv_area_exp_roof_m2.sum()),
        "total_est_mwp_det": float(grid.est_mwp_det.sum()),
        "total_est_mwp_exp": float(grid.est_mwp_exp.sum()),
    }


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def run_density(
    aoi: str,
    pred_dir: Path = Path("data/predictions"),
    threshold: float = 0.3,
    kwp_per_m2: float = DEFAULT_KWP_PER_M2,
    min_prob: float = 0.05,
    min_building_exp_m2: float = 10.0,
    limit: int = 0,
    districts: bool = False,
    regions_file: Path | None = None,
    labels_dir: Path = Path("data/labels"),
    force: bool = False,
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    iso3 = _iso3_for(cfg)
    if iso3 is None:
        raise ValueError(f"AOI '{aoi}' has no division.country -> cannot locate VIDA buildings")

    prob_dir = Path(pred_dir) / aoi / "prob"
    cand_path = Path(pred_dir) / aoi / "candidates.parquet"
    if not cand_path.exists():
        raise FileNotFoundError(f"{cand_path} missing — run `earthpv postprocess --aoi {aoi}` first")
    cands = gpd.read_parquet(cand_path)
    if not cands.empty:
        _ = cands.sindex  # build once, reused per cell

    out_dir = Path(pred_dir) / aoi / "density"
    out_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = out_dir / "cells"

    manifest = cell_manifest(prob_dir, _grid_origin(aoi, cfg, settings))
    if limit:
        manifest = manifest.head(limit)
    log.info("Processing %d cells for %s (iso3=%s)", len(manifest), aoi, iso3)

    con = overture.connect()
    for row in tqdm([r for _, r in manifest.iterrows()], desc="density"):
        try:
            process_cell(row, cands, con, iso3, min_prob, min_building_exp_m2, cells_dir, force)
        except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
            log.warning("cell %s failed: %s", row.cell, e)

    regions, dist = load_admin(aoi, cfg, settings, iso3, labels_dir, districts, regions_file)
    stats = aggregate(out_dir, manifest, regions, dist, kwp_per_m2)

    meta = {
        "aoi": aoi, "threshold": threshold, "kwp_per_m2": kwp_per_m2,
        "min_prob": min_prob, "min_building_exp_m2": min_building_exp_m2,
        "limit": limit, "districts": districts, **stats,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    log.info("Wrote density outputs -> %s", out_dir)
    log.info("Summary: %s", json.dumps(stats, indent=2))
    return out_dir
