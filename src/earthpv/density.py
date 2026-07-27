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

With a calibration table (capacity_calibration) two more estimators join at the
cell/region level: **calibrated** (`*_cal`, candidates weighted by a measured
P(real | size, glint)) and **recall-corrected** (`*_rc`, the calibrated area further
divided by the model's measured per-size-bin recall — a Horvitz-Thompson estimate of
the whole >= detection-floor population, with 90% credible intervals from posterior
draws over every calibration count; see `_candidate_uncertainty`).

Area becomes capacity through **two** constants, not one, because detected area means
two different things (capacity_calibration.DEFAULT_KWP_PER_M2_{MODULE,LAND}): a rooftop
detection is ~module area, a ground-mount detection is *site* area, of which only the
ground-cover ratio is module. Every all-PV estimator is therefore split by `placement`
before conversion (`_ratios`), and both constants carry lognormal priors that propagate
into the credible intervals (`_composed_mwp_draws`).

Candidates above `postprocess.MAX_CANDIDATE_M2` are excluded here (not from the leads
product): a single multi-km2 polygon is a merged false-positive sheet or a whole plant
site, and converting it as one installation's panel area is what let a handful of blobs
dominate a country total.

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
from earthpv.capacity_calibration import (
    DEFAULT_KWP_PER_M2_LAND,
    DEFAULT_KWP_PER_M2_MODULE,
)
from earthpv.compose import CELL_DEG, _aoi_boundary
from earthpv.config import Settings
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.postprocess import MAX_CANDIDATE_M2

log = logging.getLogger(__name__)

PIXEL_M2 = 100.0  # 10 m x 10 m Sentinel-2 pixel
# Retained name for the rooftop/module constant (pv_capacity imports it); the ground-mount
# constant is DEFAULT_KWP_PER_M2_LAND. See capacity_calibration for both derivations.
DEFAULT_KWP_PER_M2 = DEFAULT_KWP_PER_M2_MODULE

# Additive per-cell columns summed up into region totals (never average ratios).
_SUM_COLS = [
    "n_buildings", "roof_area_m2", "n_pv_buildings",
    "pv_area_det_roof_m2", "pv_area_det_total_m2", "pv_area_det_roofcand_m2",
    "pv_area_cal_roof_m2", "pv_area_cal_total_m2", "pv_area_cal_roofcand_m2",
    "pv_area_exp_m2", "pv_area_exp_roof_m2",
    # A count, not an area: how many of a region's cells the expected-area instrument
    # actually covered. Summed like the areas so region rows carry their own coverage.
    "exp_covered",
]
# The subset of _SUM_COLS that describes the *candidate* population rather than the
# building/raster layers. These are recomputed from the (oversize-filtered) candidate
# frame by `candidate_cell_totals` on every run, so the filter takes effect without
# rebuilding the expensive per-cell partials; any copies in cached partials are dropped.
_CAND_COLS = [
    "pv_area_det_total_m2", "pv_area_det_roofcand_m2",
    "pv_area_cal_total_m2", "pv_area_cal_roofcand_m2",
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
    bu_utm: gpd.GeoDataFrame, prob: np.ndarray, transform, min_prob: float,
    scale: float = 1.0,
) -> pd.DataFrame:
    """Expected PV area, pixel count and peak probability per building.

    Buildings are rasterized to their footprint pixels at native 10 m
    (`all_touched=False`); ~half of Pakistani footprints are sub-pixel and get zero
    pixels this way, so those fall back to the probability of their centroid pixel
    times the footprint area. Expected area is capped at the roof area (a 100 m2
    pixel overhangs a small roof).

    `prob` is whichever raster the caller chose as the expected-area instrument (see
    `process_cell`): segmentation class probability, or a fraction head's per-pixel PV
    coverage fraction. `scale` divides the summed area by a measured aggregate
    over-prediction factor and is applied *before* the roof-area cap.
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
    if scale != 1.0:
        pv_area = pv_area / scale

    out["pv_area_exp_m2"] = np.minimum(pv_area, roof)
    out["n_px"] = n_px.astype(int)
    out["pv_prob_max"] = max_p
    return out


def per_building_detected(bu: gpd.GeoDataFrame, cands: gpd.GeoDataFrame) -> pd.DataFrame:
    """Thresholded PV area per building from the merged candidate polygons.

    For each candidate intersecting the cell, the footprint-candidate intersection
    area (geodesic) is added to every building it overlaps; the best-overlap
    candidate's confidence and placement are recorded. Area is capped at the roof.
    `pv_area_cal_m2` is the same sum with each candidate weighted by its `p_real`
    (capacity_calibration; 1.0 when uncalibrated, making cal == det).
    """
    n = len(bu)
    det = np.zeros(n)
    cal = np.zeros(n)
    conf = np.full(n, np.nan)
    placement = np.array([""] * n, dtype=object)
    best_area = np.zeros(n)
    if n == 0 or cands.empty:
        return pd.DataFrame(
            {"pv_area_det_m2": det, "pv_area_cal_m2": cal,
             "pv_conf_det": conf, "pv_placement": placement}
        )
    sindex = bu.sindex
    for cand in cands.itertuples():
        hits = sindex.query(cand.geometry, predicate="intersects")
        p_real = float(getattr(cand, "p_real", 1.0))
        for bi in hits:
            inter = geodesic_area_m2(bu.geometry.iloc[bi].intersection(cand.geometry))
            if inter <= 0:
                continue
            det[bi] += inter
            cal[bi] += inter * p_real
            if inter > best_area[bi]:
                best_area[bi] = inter
                conf[bi] = float(getattr(cand, "confidence", np.nan))
                placement[bi] = getattr(cand, "placement", "") or ""
    roof = bu["area_m2"].to_numpy(float)
    det = np.minimum(det, roof)
    cal = np.minimum(cal, roof)
    return pd.DataFrame({"pv_area_det_m2": det, "pv_area_cal_m2": cal,
                         "pv_conf_det": conf, "pv_placement": placement})


def candidate_cell_totals(
    cands: gpd.GeoDataFrame, origin: tuple[float, float], manifest_cells: set[str]
) -> pd.DataFrame:
    """Per-cell candidate-population areas, split into rooftop-placed and everything else.

    One row per cell that has candidates, with the four `_CAND_COLS`. Candidates are
    assigned to exactly one cell by representative point, matching how
    `_candidate_uncertainty` assigns them, so the point columns and the draw matrices
    describe the same population.

    The rooftop/other split is what makes the two-constant capacity conversion possible:
    `*_roofcand` converts at the module constant, the remainder (total minus roofcand,
    i.e. `ground_adjacent` + `no_building`) at the land constant. Deriving these here
    rather than in `process_cell` keeps them a pure function of the candidate frame handed
    in, so an oversize filter or a re-calibration takes effect on a plain re-run.
    """
    cols = ["cell", *_CAND_COLS]
    if cands.empty:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols}).astype({"cell": object})
    minx, miny = origin
    reps = cands.geometry.representative_point()
    ix = np.floor((reps.x.to_numpy() - minx) / CELL_DEG).astype(int)
    iy = np.floor((reps.y.to_numpy() - miny) / CELL_DEG).astype(int)
    cell = np.array([f"{i:04d}_{j:04d}" for i, j in zip(ix, iy)])

    area = cands["area_m2"].to_numpy(float)
    p_real = (
        cands["p_real"].to_numpy(float) if "p_real" in cands.columns else np.ones(len(cands))
    )
    roof = (
        cands["placement"].astype(str).to_numpy() == "rooftop"
        if "placement" in cands.columns else np.zeros(len(cands), bool)
    )
    df = pd.DataFrame({
        "cell": cell,
        "pv_area_det_total_m2": area,
        "pv_area_det_roofcand_m2": np.where(roof, area, 0.0),
        "pv_area_cal_total_m2": area * p_real,
        "pv_area_cal_roofcand_m2": np.where(roof, area * p_real, 0.0),
    })
    keep = df["cell"].isin(manifest_cells)
    if not keep.all():
        log.info("Cell totals: %d candidates outside manifest cells ignored", int((~keep).sum()))
    return df[keep].groupby("cell", as_index=False)[_CAND_COLS].sum()


def process_cell(
    row, cands: gpd.GeoDataFrame, con, iso3: str, min_prob: float,
    min_building_exp_m2: float, cells_dir: Path, force: bool,
    exp_source: str = "segmentation", exp_path: str | None = None, exp_scale: float = 1.0,
) -> None:
    """Resumable per-cell unit: write buildings partial + one summary row.

    Every raster read here serves the *expected-area* metric (`pv_area_exp_*`,
    `pv_prob_max`); the detected and calibrated columns come from candidate polygons.
    So `exp_path` swaps the instrument wholesale: pass a fraction head's per-pixel PV
    coverage raster for this cell and `pv_area_exp` becomes an integral of predicted
    coverage rather than of segmentation class probability. That is the estimator that
    can see sub-400 m2 arrays at all, because the segmentation model is trained with
    everything below `chips.MIN_PV_AREA` burned as ignore and therefore has no reason to
    put probability mass there. `exp_scale` divides by a measured aggregate
    over-prediction factor. When `exp_path` is None the segmentation raster is used, as
    before.
    """
    part = cells_dir / f"{row.cell}.parquet"
    summ = cells_dir / f"{row.cell}.summary.parquet"
    if part.exists() and summ.exists() and not force:
        return

    lon0, lat0 = float(row.lon0), float(row.lat0)
    # The cell's geographic footprint and CRS always come from the canonical (segmentation)
    # raster, so cell geometry and building assignment stay identical whichever instrument
    # supplies the expected-area values.
    with rasterio.open(row.path) as src:
        win = _canonical_window(src, lon0, lat0)
        prob = src.read(1, window=win).astype("float32") / 255.0
        win_tf = window_transform(win, src.transform)
        crs = src.crs
        grid_shape = (src.height, src.width)
        w4, s4, e4, n4 = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    # exp_covered: 1 when the chosen instrument actually supplied values for this cell.
    # In segmentation mode that is always true. In fraction mode the fraction run may
    # cover fewer cells than the segmentation run, and those cells' expected area is
    # *absent*, not zero -- aggregates must report the coverage, not average in the gap.
    exp_covered = 1
    if exp_source == "fraction":
        if exp_path is None:
            exp_covered = 0
            prob = np.zeros_like(prob)
        else:
            with rasterio.open(exp_path) as esrc:
                if esrc.crs != crs or (esrc.height, esrc.width) != grid_shape:
                    raise ValueError(
                        f"cell {row.cell}: expected-area raster {exp_path} is not on the "
                        f"same grid as {row.path} ({esrc.crs}/{(esrc.height, esrc.width)} "
                        f"vs {crs}/{grid_shape})"
                    )
                prob = esrc.read(1, window=win).astype("float32") / 255.0

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

    # Candidates intersecting the cell, for the per-building detected area. Cell-level
    # candidate-population totals are NOT computed here — `candidate_cell_totals` derives
    # them from the whole candidate frame at aggregate time, so they always reflect the
    # current oversize filter rather than whatever was in force when a partial was written.
    box_geom = shapely_box(lon0, lat0, lon0 + CELL_DEG, lat0 + CELL_DEG)
    cand_hits = (
        cands.iloc[cands.sindex.query(box_geom, predicate="intersects")]
        if not cands.empty else cands
    )

    n_buildings = len(bu)
    roof_area = float(bu["area_m2"].sum()) if n_buildings else 0.0
    # Building-independent expected area over the cropped box (no overlap double-count).
    exp_cell = float(np.where(prob >= min_prob, prob, 0.0).sum() * PIXEL_M2) / exp_scale

    if n_buildings:
        rstats = per_building_raster_stats(
            bu.to_crs(crs), prob, win_tf, min_prob, scale=exp_scale
        )
        dstats = per_building_detected(bu, cand_hits)
        b = bu.copy()
        b["building_uid"] = [f"{row.cell}_{i:06d}" for i in range(n_buildings)]
        b["cell"] = row.cell
        rp = b.geometry.representative_point()
        b["lon"], b["lat"] = rp.x.to_numpy(), rp.y.to_numpy()
        b = b.rename(columns={"area_m2": "roof_area_m2"})
        b["pv_area_det_m2"] = dstats["pv_area_det_m2"].to_numpy()
        b["pv_area_cal_m2"] = dstats["pv_area_cal_m2"].to_numpy()
        b["pv_area_exp_m2"] = rstats["pv_area_exp_m2"].to_numpy()
        b["pv_prob_max"] = rstats["pv_prob_max"].round(3).to_numpy()
        b["pv_conf_det"] = dstats["pv_conf_det"].to_numpy()
        b["pv_placement"] = dstats["pv_placement"].to_numpy()
        b["pv_ratio_det"] = (b.pv_area_det_m2 / b.roof_area_m2.clip(lower=1e-6)).clip(upper=1.0)
        b["pv_ratio_exp"] = (b.pv_area_exp_m2 / b.roof_area_m2.clip(lower=1e-6)).clip(upper=1.0)
        keep = (b.pv_area_det_m2 > 0) | (b.pv_area_exp_m2 >= min_building_exp_m2)
        cols = [
            "building_uid", "cell", "geometry", "lon", "lat", "roof_area_m2", "bf_confidence",
            "pv_area_det_m2", "pv_area_cal_m2", "pv_area_exp_m2", "pv_ratio_det", "pv_ratio_exp",
            "pv_conf_det", "pv_prob_max", "pv_placement",
        ]
        signal = gpd.GeoDataFrame(b[keep][cols], geometry="geometry", crs="EPSG:4326")
        summary = {
            "n_buildings": n_buildings,
            "roof_area_m2": roof_area,
            "n_pv_buildings": int((b.pv_area_det_m2 > 0).sum()),
            "pv_area_det_roof_m2": float(b.pv_area_det_m2.sum()),
            "pv_area_cal_roof_m2": float(b.pv_area_cal_m2.sum()),
            "pv_area_exp_roof_m2": float(b.pv_area_exp_m2.sum()),
        }
    else:
        signal = gpd.GeoDataFrame(
            {c: [] for c in [
                "building_uid", "cell", "lon", "lat", "roof_area_m2", "bf_confidence",
                "pv_area_det_m2", "pv_area_cal_m2", "pv_area_exp_m2", "pv_ratio_det",
                "pv_ratio_exp", "pv_conf_det", "pv_prob_max", "pv_placement"]},
            geometry=[], crs="EPSG:4326",
        )
        summary = {
            "n_buildings": 0, "roof_area_m2": 0.0, "n_pv_buildings": 0,
            "pv_area_det_roof_m2": 0.0, "pv_area_cal_roof_m2": 0.0,
            "pv_area_exp_roof_m2": 0.0,
        }

    summary.update({
        "cell": row.cell, "ix": int(row.ix), "iy": int(row.iy),
        "lon0": lon0, "lat0": lat0,
        "pv_area_exp_m2": exp_cell,
        "exp_covered": exp_covered,
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
# Recall-corrected candidate estimator + posterior uncertainty
# --------------------------------------------------------------------------------------
def _candidate_uncertainty(
    cands: gpd.GeoDataFrame,
    table: dict,
    origin: tuple[float, float],
    manifest_cells: set[str],
    recall_floor: float,
    kwp_module: float = DEFAULT_KWP_PER_M2_MODULE,
    kwp_land: float = DEFAULT_KWP_PER_M2_LAND,
    n_draws: int = 1000,
) -> dict | None:
    """Per-cell recall-corrected (Horvitz-Thompson) candidate area with posterior draws.

    Each surviving candidate of size bin b stands in for 1/recall(b) real
    installations of that class (recall measured against a pipeline-independent
    mapped OSM reference, see capacity_calibration), so

        pv_area_rc = sum(area * p_real / max(recall, recall_floor))

    estimates the *whole* >= detection-floor population, not just the detected part.
    It lives on the candidate population — comparable to the `*_total` cell columns
    (`*_roofcand` for the rooftop-placed subset), NOT to the footprint-intersected
    `*_roof` columns; per-building recall inflation would be meaningless (the missed
    installations sit on other, unknown buildings).

    Uncertainty: bin-level posterior draws over every calibration count
    (capacity_calibration.posterior_draws) are pushed through the same weights.
    Draws are shared across cells within a bin (fully correlated), so summing a
    cell's draw rows gives the correct interval at any aggregation level. Returns
    per-cell draw matrices (m^2) for the calibrated and recall-corrected sums, for
    the full and rooftop-placed candidate populations.

    Also returns matching draws for the two area->capacity constants (`kwp`), drawn at the
    same `n_draws` so `_composed_mwp_draws` can turn any (all, rooftop) pair of area
    matrices into MWp draws that carry the conversion uncertainty as well.
    """
    from earthpv import capacity_calibration as cc

    if cands.empty:
        return None
    area = cands["area_m2"].to_numpy(float)
    bins = cc.bin_index(area)
    reps = cands.geometry.representative_point()
    minx, miny = origin
    ix = np.floor((reps.x.to_numpy() - minx) / CELL_DEG).astype(int)
    iy = np.floor((reps.y.to_numpy() - miny) / CELL_DEG).astype(int)
    cell = np.array([f"{i:04d}_{j:04d}" for i, j in zip(ix, iy)])

    glint = (
        cands["glint_consistent"].to_numpy() if "glint_consistent" in cands.columns else None
    )
    validated = np.zeros(len(cands), bool) if glint is None else np.asarray(glint) >= 2
    rooftop = (
        cands["placement"].astype(str).to_numpy() == "rooftop"
        if "placement" in cands.columns
        else np.zeros(len(cands), bool)
    )
    p_pt = cc.candidate_p_real(area, table, glint_consistent=glint)
    r_pt = cc.candidate_recall(area, table, floor=recall_floor)

    # Same population process_cell counts into the cell totals: assigned by
    # representative point to a manifest cell.
    keep = np.isin(cell, list(manifest_cells))
    if not keep.all():
        log.info("Uncertainty: %d candidates outside manifest cells ignored", (~keep).sum())
    df = pd.DataFrame({
        "cell": cell[keep], "b": bins[keep], "v": validated[keep],
        "roof": rooftop[keep], "area": area[keep],
        "rc_pt": (area * p_pt / r_pt)[keep],
    })
    if df.empty:
        return None

    draws = cc.posterior_draws(table, n_draws=n_draws)
    prior = np.clip(draws["p_real"], 1e-6, 1 - 1e-6)
    odds = prior / (1.0 - prior) * draws["lr"]
    w = np.stack([draws["p_real"], odds / (1.0 + odds)])  # (validated?, bin, draw)
    r_dr = np.maximum(draws["recall"], recall_floor)

    cells = np.unique(df["cell"].to_numpy())
    pos = {c: i for i, c in enumerate(cells)}
    mats = {k: np.zeros((len(cells), n_draws)) for k in ("cal_all", "rc_all", "cal_roof", "rc_roof")}
    for roof_only, cal_key, rc_key in ((False, "cal_all", "rc_all"), (True, "cal_roof", "rc_roof")):
        sub = df[df.roof] if roof_only else df
        for (c, b, v), a in sub.groupby(["cell", "b", "v"])["area"].sum().items():
            wa = a * w[int(v), b]
            mats[cal_key][pos[c]] += wa
            mats[rc_key][pos[c]] += wa / r_dr[b]

    points = (
        df.assign(rc_roof_pt=np.where(df.roof, df.rc_pt, 0.0))
        .groupby("cell", as_index=False)[["rc_pt", "rc_roof_pt"]].sum()
        .rename(columns={"rc_pt": "pv_area_rc_total_m2", "rc_roof_pt": "pv_area_rc_roofcand_m2"})
    )
    return {
        "cells": cells, "pos": pos, "mats": mats, "points": points,
        "n_draws": n_draws, "recall_floor": recall_floor,
        "kwp": cc.kwp_draws(n_draws=n_draws, module=kwp_module, land=kwp_land),
    }


def _composed_mwp_draws(
    unc: dict, all_key: str, roof_key: str, rows: list[int] | None = None
) -> np.ndarray:
    """Per-draw MWp for an area draw matrix, split by placement before conversion.

    `all_key` is the whole candidate population, `roof_key` its rooftop-placed subset;
    the remainder is ground-mount and converts at the land constant. Pass `rows` to sum a
    cell subset first (region/country totals), or None to keep the per-cell axis (the
    grid layer's own intervals). Shapes: (n_draws,) with rows, (n_cells, n_draws) without.
    """
    tot_m2 = unc["mats"][all_key]
    roof_m2 = unc["mats"][roof_key]
    if rows is not None:
        n = unc["n_draws"]
        tot_m2 = tot_m2[rows].sum(axis=0) if rows else np.zeros(n)
        roof_m2 = roof_m2[rows].sum(axis=0) if rows else np.zeros(n)
    ground_m2 = np.clip(tot_m2 - roof_m2, 0.0, None)
    kwp = unc["kwp"]
    return (roof_m2 * kwp["module"] + ground_m2 * kwp["land"]) / 1000.0


def _unc_mwp_ci(unc: dict, cell_list: list[str]) -> dict:
    """Credible intervals (MWp) over the summed draws of a set of cells.

    Each estimator is composed from its rooftop-placed and ground-mount parts at the two
    per-draw kWp/m2 constants, so the interval carries the area->capacity uncertainty as
    well as the calibration counts. `est_mwp_rc_roof` is rooftop-only, hence the same key
    on both sides (zero ground-mount area).
    """
    from earthpv.capacity_calibration import CI_PCT

    rows = [unc["pos"][c] for c in cell_list if c in unc["pos"]]
    out = {}
    for all_key, roof_key, name in (
        ("rc_all", "rc_roof", "est_mwp_rc"),
        ("rc_roof", "rc_roof", "est_mwp_rc_roof"),
        ("cal_all", "cal_roof", "est_mwp_cal_total"),
    ):
        tot = _composed_mwp_draws(unc, all_key, roof_key, rows)
        lo, hi = np.percentile(tot, CI_PCT)
        out[f"{name}_lo"], out[f"{name}_hi"] = round(float(lo), 4), round(float(hi), 4)
    return out


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------
def _ratios(
    df: pd.DataFrame, area_km2: pd.Series, kwp_module: float, kwp_land: float
) -> pd.DataFrame:
    """Ratios and MWp estimates for a cell/region frame.

    Conversion is split by what the area physically is. The roof-scope estimators
    (`est_mwp_det`/`_cal`/`_exp`) come from candidate-footprint *intersections*, so they
    are module area whatever the candidate's placement, and convert at `kwp_module`. The
    candidate-population estimators (`est_mwp_cal_total`, `est_mwp_rc`) mix rooftop-placed
    candidates with ground-mount ones whose polygon is site area, so each is summed as
    rooftop-placed at `kwp_module` plus the remainder at `kwp_land`. `*_ground` is exported
    alongside because the ground/roof balance is the plausibility signal that catches
    false-positive sheets (see plausibility.py).
    """
    df = df.copy()
    roof = df["roof_area_m2"].clip(lower=1e-6)
    df["pv_ratio_det"] = (df.pv_area_det_roof_m2 / roof).clip(upper=1.0).round(4)
    df["pv_ratio_exp"] = (df.pv_area_exp_roof_m2 / roof).clip(upper=1.0).round(4)
    df["pv_det_m2_per_km2"] = (df.pv_area_det_roof_m2 / area_km2.clip(lower=1e-9)).round(2)
    df["pv_exp_m2_per_km2"] = (df.pv_area_exp_roof_m2 / area_km2.clip(lower=1e-9)).round(2)
    df["est_mwp_det"] = (df.pv_area_det_roof_m2 * kwp_module / 1000.0).round(4)
    df["est_mwp_cal"] = (df.pv_area_cal_roof_m2 * kwp_module / 1000.0).round(4)
    df["est_mwp_exp"] = (df.pv_area_exp_roof_m2 * kwp_module / 1000.0).round(4)

    def _split(total_col: str, roof_col: str, prefix: str) -> None:
        roof_mwp = df[roof_col] * kwp_module / 1000.0
        ground_mwp = (df[total_col] - df[roof_col]).clip(lower=0.0) * kwp_land / 1000.0
        df[f"{prefix}_roofcand"] = roof_mwp.round(4)
        df[f"{prefix}_ground"] = ground_mwp.round(4)
        df[prefix] = (roof_mwp + ground_mwp).round(4)

    _split("pv_area_cal_total_m2", "pv_area_cal_roofcand_m2", "est_mwp_cal_total")
    if {"pv_area_rc_total_m2", "pv_area_rc_roofcand_m2"} <= set(df.columns):
        _split("pv_area_rc_total_m2", "pv_area_rc_roofcand_m2", "est_mwp_rc")
        # est_mwp_rc_roof is the established name for the rooftop-placed recall-corrected
        # estimator (atlas metric 3); est_mwp_rc_roofcand is its _split alias.
        df["est_mwp_rc_roof"] = df["est_mwp_rc_roofcand"]
    return df


def _backfill_cal(df: pd.DataFrame) -> pd.DataFrame:
    """Cell partials written before the calibrated estimator lack the cal columns;
    treat them as uncalibrated (cal == det) so mixed-vintage runs stay additive.

    Only the building/footprint columns need this. The candidate-population columns
    (`_CAND_COLS`) are recomputed from the candidate frame every run by
    `candidate_cell_totals`, so a stale copy in a partial is dropped rather than patched.
    """
    for cal_col, det_col in (
        ("pv_area_cal_m2", "pv_area_det_m2"),
        ("pv_area_cal_roof_m2", "pv_area_det_roof_m2"),
    ):
        if det_col in df.columns:
            if cal_col not in df.columns:
                df[cal_col] = df[det_col]
            else:
                df[cal_col] = df[cal_col].fillna(df[det_col])
    return df


def aggregate(
    out_dir: Path, manifest: gpd.GeoDataFrame, regions: gpd.GeoDataFrame | None,
    districts: gpd.GeoDataFrame | None, kwp_module: float, kwp_land: float,
    cand_totals: pd.DataFrame, unc: dict | None = None,
) -> dict:
    cells_dir = out_dir / "cells"
    rc_cols = ["pv_area_rc_total_m2", "pv_area_rc_roofcand_m2"] if unc is not None else []
    sum_cols = _SUM_COLS + rc_cols

    # Per-building layer -------------------------------------------------------------
    parts = [gpd.read_parquet(p) for p in sorted(cells_dir.glob("*.parquet"))
             if not p.name.endswith(".summary.parquet")]
    buildings = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    ) if parts else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    if not buildings.empty:
        buildings = _backfill_cal(buildings)
        # Per-building areas are all candidate-footprint intersections, i.e. module area
        # on a roof, so they convert at the module constant regardless of placement.
        buildings["est_kwp_det"] = (buildings.pv_area_det_m2 * kwp_module).round(3)
        buildings["est_kwp_cal"] = (buildings.pv_area_cal_m2 * kwp_module).round(3)
        buildings["est_kwp_exp"] = (buildings.pv_area_exp_m2 * kwp_module).round(3)
        pts = gpd.GeoDataFrame(
            geometry=gpd.points_from_xy(buildings.lon, buildings.lat), crs="EPSG:4326"
        )
        for gdf, col in ((regions, "region"), (districts, "district")):
            if gdf is not None and not gdf.empty:
                # Reduce per input row before assigning: a point landing in two polygons
                # (overlapping admin claims) makes sjoin return more rows than it got, and
                # positional assignment would then shift every later building's label.
                j = gpd.sjoin(pts, gdf[["name", "geometry"]], how="left", predicate="within")
                buildings[col] = (
                    j["name"].groupby(level=0).first().reindex(pts.index).to_numpy()
                )
            else:
                buildings[col] = None
    buildings.to_parquet(out_dir / "buildings.geoparquet")

    # 0.1 deg grid layer -------------------------------------------------------------
    summ = pd.concat(
        [pd.read_parquet(p) for p in sorted(cells_dir.glob("*.summary.parquet"))],
        ignore_index=True,
    )
    # Drop any candidate-population columns cached in the partials and take them from
    # `cand_totals`, which was derived from the candidate frame this run actually used.
    summ = _backfill_cal(summ.drop(columns=_CAND_COLS, errors="ignore"))
    grid = manifest[["cell", "ix", "iy", "lon0", "lat0", "geometry"]].merge(
        summ.drop(columns=["ix", "iy", "lon0", "lat0"]), on="cell", how="left"
    )
    grid = gpd.GeoDataFrame(grid, geometry="geometry", crs="EPSG:4326")
    grid = grid.merge(cand_totals, on="cell", how="left")
    if unc is not None:
        grid = grid.merge(unc["points"], on="cell", how="left")
    grid[sum_cols] = grid[sum_cols].fillna(0.0)
    grid["lon_center"] = grid.lon0 + CELL_DEG / 2
    grid["lat_center"] = grid.lat0 + CELL_DEG / 2
    grid["cell_area_km2"] = [geodesic_area_m2(g) / 1e6 for g in grid.geometry]
    grid = _ratios(grid, grid["cell_area_km2"], kwp_module, kwp_land)
    if unc is not None:
        from earthpv.capacity_calibration import CI_PCT

        lohi = np.percentile(_composed_mwp_draws(unc, "rc_all", "rc_roof"), CI_PCT, axis=1)
        ci = pd.DataFrame({
            "cell": unc["cells"],
            "est_mwp_rc_lo": lohi[0].round(4), "est_mwp_rc_hi": lohi[1].round(4),
        })
        grid = grid.merge(ci, on="cell", how="left")
        grid[["est_mwp_rc_lo", "est_mwp_rc_hi"]] = (
            grid[["est_mwp_rc_lo", "est_mwp_rc_hi"]].fillna(0.0)
        )
    grid.to_parquet(out_dir / "grid.geoparquet")
    grid.drop(columns="geometry").to_csv(out_dir / "grid.csv", index=False)

    # Admin-region layer -------------------------------------------------------------
    n_regions = 0
    if regions is not None and not regions.empty:
        centroids = gpd.GeoDataFrame(
            grid[["cell"] + sum_cols],
            geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs="EPSG:4326",
        )
        frames = []
        for gdf, level in ((regions, "region"), (districts, "county")):
            if gdf is None or gdf.empty:
                continue
            j = gpd.sjoin(centroids, gdf[["id", "name", "geometry"]], how="inner",
                          predicate="within")
            agg = j.groupby(["id", "name"], as_index=False).agg(
                {**{c: "sum" for c in sum_cols}, "cell": "count"}
            ).rename(columns={"cell": "n_cells"})
            agg = agg.merge(gdf[["id", "name", "country", "geometry"]], on=["id", "name"])
            agg = gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")
            agg["level"] = level
            agg["area_km2"] = [geodesic_area_m2(g) / 1e6 for g in agg.geometry]
            agg = _ratios(agg, agg["area_km2"], kwp_module, kwp_land)
            if unc is not None:
                ci_rows = [
                    {"id": rid, "name": name, **_unc_mwp_ci(unc, cell_list)}
                    for (rid, name), cell_list in j.groupby(["id", "name"])["cell"].agg(list).items()
                ]
                agg = agg.merge(pd.DataFrame(ci_rows), on=["id", "name"], how="left")
            frames.append(agg.rename(columns={"id": "region_id"}))
        if frames:
            reg = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
            reg.to_parquet(out_dir / "regions.geoparquet")
            reg.drop(columns="geometry").to_csv(out_dir / "regions.csv", index=False)
            reg.to_file(out_dir / "regions.geojson", driver="GeoJSON")
            n_regions = int((reg.level == "region").sum())

    stats = {
        "n_cells": int(len(grid)),
        "n_signal_buildings": int(len(buildings)),
        "n_regions": n_regions,
        "kwp_per_m2_module": float(kwp_module),
        "kwp_per_m2_land": float(kwp_land),
        "total_pv_area_det_total_m2": float(grid.pv_area_det_total_m2.sum()),
        "total_pv_area_det_roofcand_m2": float(grid.pv_area_det_roofcand_m2.sum()),
        "total_pv_area_det_roof_m2": float(grid.pv_area_det_roof_m2.sum()),
        "total_pv_area_cal_roof_m2": float(grid.pv_area_cal_roof_m2.sum()),
        "total_pv_area_cal_roofcand_m2": float(grid.pv_area_cal_roofcand_m2.sum()),
        "total_pv_area_exp_roof_m2": float(grid.pv_area_exp_roof_m2.sum()),
        # Expected-area coverage. Below 1.0 the exp totals describe only part of the AOI
        # (a fraction-head run covering fewer cells than the segmentation run), so they
        # are NOT comparable to the det/cal/rc totals, which cover every manifest cell.
        "n_cells_exp_covered": int(grid.exp_covered.sum()),
        "exp_coverage_frac": round(float(grid.exp_covered.sum()) / max(len(grid), 1), 4),
        "total_est_mwp_det": float(grid.est_mwp_det.sum()),
        "total_est_mwp_cal": float(grid.est_mwp_cal.sum()),
        "total_est_mwp_cal_total": float(grid.est_mwp_cal_total.sum()),
        "total_est_mwp_cal_total_roofcand": float(grid.est_mwp_cal_total_roofcand.sum()),
        "total_est_mwp_cal_total_ground": float(grid.est_mwp_cal_total_ground.sum()),
        "total_est_mwp_exp": float(grid.est_mwp_exp.sum()),
    }
    if unc is not None:
        stats.update({
            "recall_floor": unc["recall_floor"],
            "n_draws": unc["n_draws"],
            "total_pv_area_rc_total_m2": float(grid.pv_area_rc_total_m2.sum()),
            "total_pv_area_rc_roofcand_m2": float(grid.pv_area_rc_roofcand_m2.sum()),
            "total_est_mwp_rc": float(grid.est_mwp_rc.sum()),
            "total_est_mwp_rc_roof": float(grid.est_mwp_rc_roof.sum()),
            "total_est_mwp_rc_ground": float(grid.est_mwp_rc_ground.sum()),
            **{f"total_{k}": v for k, v in _unc_mwp_ci(unc, list(unc["cells"])).items()},
        })
    return stats


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def run_density(
    aoi: str,
    pred_dir: Path = Path("data/predictions"),
    threshold: float = 0.3,
    kwp_per_m2_module: float = DEFAULT_KWP_PER_M2_MODULE,
    kwp_per_m2_land: float = DEFAULT_KWP_PER_M2_LAND,
    min_prob: float = 0.05,
    min_building_exp_m2: float = 10.0,
    limit: int = 0,
    districts: bool = False,
    regions_file: Path | None = None,
    labels_dir: Path = Path("data/labels"),
    force: bool = False,
    calibration: Path | None = None,
    recall_floor: float | None = None,
    max_candidate_m2: float = MAX_CANDIDATE_M2,
    fraction_prob_dir: Path | None = None,
    exp_scale: float = 1.0,
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

    # Drop blobs before anything consumes them. A multi-km2 contiguous polygon is a merged
    # false-positive sheet or a whole plant site, not one installation's panel area, and
    # unfiltered they dominated the Pakistan country total (see postprocess.MAX_CANDIDATE_M2).
    # Kept in candidates.parquet for the human-validated leads product; excluded here only.
    n_oversize, oversize_area_m2 = 0, 0.0
    if max_candidate_m2 and not cands.empty:
        over = cands["area_m2"].to_numpy(float) > max_candidate_m2
        n_oversize = int(over.sum())
        oversize_area_m2 = float(cands.loc[over, "area_m2"].sum())
        if n_oversize:
            log.warning(
                "Excluding %d/%d oversize candidates (> %.0f m2) from capacity: %.1f%% of "
                "candidate area, largest %.2f km2",
                n_oversize, len(cands), max_candidate_m2,
                100.0 * oversize_area_m2 / max(float(cands["area_m2"].sum()), 1e-9),
                float(cands["area_m2"].max()) / 1e6,
            )
            cands = cands[~over].reset_index(drop=True)
    # Cached partials carry the per-building/footprint columns from whatever candidate set
    # was in force when they were written; only the candidate-population columns are
    # rederived each run. Say so rather than letting the two disagree silently.
    cached_cells = Path(pred_dir) / aoi / "density" / "cells"
    stale_partials = (
        bool(n_oversize) and not force
        and cached_cells.exists() and any(cached_cells.glob("*.summary.parquet"))
    )
    if stale_partials:
        log.warning(
            "Cached cell partials exist: the per-building and *_roof columns still include "
            "the excluded oversize candidates. Re-run with --force to rebuild them "
            "(re-fetches VIDA footprints per cell)."
        )

    if not cands.empty:
        _ = cands.sindex  # build once, reused per cell

    # Capacity-atlas calibration: weight each candidate by P(real | size, glint).
    # This is the split from the leads product — rank_score is never consumed here,
    # and the leads path never consumes p_real. Without a table, p_real = 1 and
    # est_mwp_cal degenerates to est_mwp_det.
    from earthpv import capacity_calibration as cc

    cal_path = Path(calibration) if calibration else cc.default_table_path(aoi)
    cal_status = "uncalibrated"
    table = None
    if cal_path.exists():
        table = cc.load_table(cal_path)
        cal_status = table["status"]
        glint_cons = cands.get("glint_consistent") if not cands.empty else None
        if not cands.empty:
            cands["p_real"] = cc.candidate_p_real(
                cands["area_m2"].to_numpy(), table,
                glint_consistent=None if glint_cons is None else glint_cons.to_numpy(),
            )
        log.info("Calibration table %s (%s): est_mwp_cal is precision-weighted", cal_path, cal_status)
    else:
        log.warning(
            "No calibration table at %s — est_mwp_cal will equal est_mwp_det; "
            "run `earthpv calibrate-candidates --aoi %s` first for a calibrated atlas",
            cal_path, aoi,
        )
    if recall_floor is None:
        recall_floor = cc.DEFAULT_RECALL_FLOOR

    out_dir = Path(pred_dir) / aoi / "density"
    out_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = out_dir / "cells"

    origin = _grid_origin(aoi, cfg, settings)
    manifest = cell_manifest(prob_dir, origin)
    if limit:
        manifest = manifest.head(limit)
    log.info("Processing %d cells for %s (iso3=%s)", len(manifest), aoi, iso3)

    con = overture.connect()
    # Expected-area instrument. Default is the segmentation raster (`prob_dir`), which by
    # construction cannot see below chips.MIN_PV_AREA -- those arrays are burned as ignore
    # in training. A fraction-head run supplies per-pixel PV *coverage* instead, which is
    # the only instrument here with sub-400 m2 sensitivity. Its cells are keyed by the same
    # canonical grid, so a fraction run covering fewer cells simply leaves those uncovered.
    exp_source = "segmentation"
    exp_paths: dict[str, str] = {}
    if fraction_prob_dir is not None:
        exp_source = "fraction"
        frac_man = cell_manifest(Path(fraction_prob_dir), origin)
        exp_paths = dict(zip(frac_man.cell, frac_man.path))
        n_cov = sum(1 for c in manifest.cell if c in exp_paths)
        log.info(
            "Expected-area instrument: fraction head %s — %d/%d manifest cells covered "
            "(%.1f%%), exp_scale=%.3f",
            fraction_prob_dir, n_cov, len(manifest), 100.0 * n_cov / max(len(manifest), 1),
            exp_scale,
        )
        if n_cov < len(manifest):
            log.warning(
                "%d cells have no fraction raster: their pv_area_exp_* is ABSENT, not zero "
                "(exp_covered=0). Country exp totals from this run cover only the %.1f%% of "
                "cells listed above — do not read them as national.",
                len(manifest) - n_cov, 100.0 * n_cov / max(len(manifest), 1),
            )
        if exp_scale == 1.0:
            log.warning(
                "exp_scale=1.0: the fraction head's absolute scale is NOT established. The "
                "German MaStR bench puts it 2.5x high on all Gemeinden (slope 0.394) and "
                "8-13x high on the well-mapped subset (0.077-0.129). Treat these areas as a "
                "ranking layer until anchored — see `earthpv roof-classifier` for a "
                "quadrat-based absolute anchor."
            )
    for row in tqdm([r for _, r in manifest.iterrows()], desc="density"):
        try:
            process_cell(
                row, cands, con, iso3, min_prob, min_building_exp_m2, cells_dir, force,
                exp_source=exp_source, exp_path=exp_paths.get(row.cell), exp_scale=exp_scale,
            )
        except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
            log.warning("cell %s failed: %s", row.cell, e)

    regions, dist = load_admin(aoi, cfg, settings, iso3, labels_dir, districts, regions_file)
    manifest_cells = set(manifest.cell)
    cand_totals = candidate_cell_totals(cands, origin, manifest_cells)
    unc = None
    if table is not None and not cands.empty:
        unc = _candidate_uncertainty(
            cands, table, origin, manifest_cells, recall_floor=recall_floor,
            kwp_module=kwp_per_m2_module, kwp_land=kwp_per_m2_land,
        )
    stats = aggregate(
        out_dir, manifest, regions, dist, kwp_per_m2_module, kwp_per_m2_land,
        cand_totals, unc=unc,
    )

    meta = {
        "aoi": aoi, "threshold": threshold,
        "kwp_per_m2_module": kwp_per_m2_module, "kwp_per_m2_land": kwp_per_m2_land,
        "min_prob": min_prob, "min_building_exp_m2": min_building_exp_m2,
        "limit": limit, "districts": districts,
        "max_candidate_m2": max_candidate_m2,
        "n_oversize_excluded": n_oversize,
        "oversize_area_m2": oversize_area_m2,
        "oversize_stale_partials": stale_partials,
        "exp_source": exp_source,
        "fraction_prob_dir": str(fraction_prob_dir) if fraction_prob_dir else None,
        "exp_scale": exp_scale,
        "calibration": str(cal_path) if cal_path.exists() else None,
        "calibration_status": cal_status, **stats,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Self-contained HTML capacity atlas (results/pakistan_7_7-style); never fatal.
    try:
        from earthpv.atlas import build_atlas

        build_atlas(aoi, out_dir)
    except Exception as e:  # noqa: BLE001 — a map rendering issue must not fail the run
        log.warning("atlas generation failed: %s", e)

    log.info("Wrote density outputs -> %s", out_dir)
    log.info("Summary: %s", json.dumps(stats, indent=2))
    return out_dir
