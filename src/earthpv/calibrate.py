"""Calibrate/validate PV density model output against German MaStR ground truth.

Works on *any* per-cell probability raster (segmentation prob or fraction-regression
output — both are uint8/255-encoded, see infer.py) zonal-summed per municipality
(Gemeinde, keyed by AGS) and compared against MaStR-reported rooftop PV capacity.
This is deliberately separate from density.py: that stage's `cell_manifest` assumes
~0.1deg cells, while Germany's local composites are 110 km MGRS tiles — a zonal join
straight from raster to municipality polygon is simpler and correct for both.

Also derives an OSM/MaStR completeness ratio per Gemeinde, used to build a
"well-mapped" region filter for training chips (see chips.py's `region_filter`): a
background chip centred where OSM PV mapping is sparse would carry a false 0 target,
which is the main label-noise channel for the fraction-regression task.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from rasterio.warp import transform_bounds
from shapely.geometry import box as shapely_box

from earthpv.config import Settings
from earthpv.labels import resolve_aoi
from earthpv.local_source import load_solar_labels

log = logging.getLogger(__name__)

PIXEL_M2 = 100.0  # 10 m x 10 m Sentinel-2 pixel
VG250_URL = (
    "https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/"
    "vg250_01-01.utm32s.gpkg.ebenen.zip"
)
KREISE_FALLBACK_URL = (
    "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_kreise/"
    "4_kreise.geojson"
)


# --------------------------------------------------------------------------------------
# Municipality boundaries
# --------------------------------------------------------------------------------------
def fetch_gemeinden(cache_dir: Path = Path("data/calibration")) -> gpd.GeoDataFrame:
    """BKG VG250 Gemeinde polygons (8-digit AGS). geoBoundaries has no DEU municipality
    level, so this is a direct fetch of the official open dataset (dl-de/by-2-0)."""
    cache_dir = Path(cache_dir)
    cache = cache_dir / "vg250_gem.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)

    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "vg250_ebenen.zip"
    if not zip_path.exists():
        log.info("Downloading VG250 from %s", VG250_URL)
        tmp = zip_path.with_suffix(".zip.tmp")
        urllib.request.urlretrieve(VG250_URL, tmp)  # noqa: S310 — fixed, trusted BKG URL
        tmp.rename(zip_path)

    extract_dir = cache_dir / "vg250_extracted"
    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    gpkgs = list(extract_dir.rglob("*.gpkg"))
    if not gpkgs:
        raise FileNotFoundError(f"No .gpkg found in extracted VG250 archive at {extract_dir}")
    gdf = gpd.read_file(gpkgs[0], layer="vg250_gem")

    # GF (Geofaktor) == 4: land area including structures — excludes water-only geometry
    # duplicates for coastal/lake municipalities. Degrade gracefully if the column/value
    # differs in a future VG250 release rather than dropping all rows.
    if "GF" in gdf.columns and (gdf["GF"] == 4).any():
        gdf = gdf[gdf["GF"] == 4]
    gdf = gdf.dissolve(by="AGS", as_index=False)
    gdf = gdf.rename(columns={"AGS": "ags", "GEN": "name"})[["ags", "name", "geometry"]]
    gdf = gdf.to_crs("EPSG:4326")
    gdf.to_parquet(cache)
    log.info("Wrote %d Gemeinde polygons -> %s", len(gdf), cache)
    return gdf


def fetch_kreise_fallback(cache_dir: Path = Path("data/calibration")) -> gpd.GeoDataFrame:
    """5-digit-AGS Kreis polygons, used only if BKG VG250 is unreachable. MaStR's
    Gemeindeschluessel[:5] is the matching Kreis key at this coarser level."""
    cache_dir = Path(cache_dir)
    cache = cache_dir / "kreise_fallback.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)
    cache_dir.mkdir(parents=True, exist_ok=True)
    gdf = gpd.read_file(KREISE_FALLBACK_URL)
    id_col = next(c for c in gdf.columns if c.upper() in ("AGS", "RS", "ID_2"))
    name_col = next((c for c in gdf.columns if c.upper() in ("GEN", "NAME_2", "NAME")), id_col)
    gdf = gdf.rename(columns={id_col: "ags", name_col: "name"})[["ags", "name", "geometry"]]
    gdf["ags"] = gdf["ags"].astype(str).str.zfill(5)
    gdf = gdf.to_crs("EPSG:4326")
    gdf.to_parquet(cache)
    log.info("Wrote %d Kreis fallback polygons -> %s", len(gdf), cache)
    return gdf


# --------------------------------------------------------------------------------------
# Zonal stats: probability raster -> PV area per Gemeinde
# --------------------------------------------------------------------------------------
def zonal_model_area(
    gemeinden: gpd.GeoDataFrame, prob_dir: Path, min_prob: float = 0.05,
) -> pd.DataFrame:
    """Expected PV area (m2) per Gemeinde: sum of per-pixel value (>= min_prob) x 100 m2.

    Only Gemeinden fully covered by a SINGLE raster are processed — Germany's MGRS
    composites overlap by ~10 km, so a straddling Gemeinde would otherwise be double- or
    partially-counted. Dropped counts are logged, not silently absorbed.
    """
    tifs = sorted(Path(prob_dir).glob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"No probability rasters in {prob_dir}")

    raster_rows = []
    for tif in tifs:
        with rasterio.open(tif) as src:
            bounds4326 = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        raster_rows.append({"path": str(tif), "geometry": shapely_box(*bounds4326)})
    raster_idx = gpd.GeoDataFrame(raster_rows, geometry="geometry", crs="EPSG:4326")
    sindex = raster_idx.sindex

    covering: dict[str, list] = {}
    n_uncovered = n_straddling = 0
    for gi, row in gemeinden.iterrows():
        hits = raster_idx.iloc[sindex.query(row.geometry, predicate="intersects")]
        covers = hits[hits.geometry.covers(row.geometry)]
        if covers.empty:
            n_uncovered += 1
            continue
        if len(covers) > 1:
            n_straddling += 1
        covering.setdefault(covers.iloc[0].path, []).append(gi)
    log.info(
        "Gemeinden: %d single-raster-covered, %d uncovered (no raster), "
        "%d covered by >1 raster (kept first, logged)",
        sum(len(v) for v in covering.values()), n_uncovered, n_straddling,
    )

    results = []
    for path, gis in covering.items():
        sub = gemeinden.loc[gis]
        with rasterio.open(path) as src:
            prob = src.read(1).astype("float32") / 255.0
            transform, crs = src.transform, src.crs
        sub_utm = sub.to_crs(crs)
        idx = rio_features.rasterize(
            ((g, i) for i, g in enumerate(sub_utm.geometry, start=1)),
            out_shape=prob.shape, transform=transform, fill=0, all_touched=False, dtype="int32",
        )
        weighted = np.where(prob >= min_prob, prob, 0.0)
        exp_px = np.bincount(idx.ravel(), weights=weighted.ravel(), minlength=len(sub) + 1)[1:]
        n_px = np.bincount(idx.ravel(), minlength=len(sub) + 1)[1:]
        for k, gi in enumerate(gis):
            results.append({
                "ags": gemeinden.loc[gi, "ags"], "pv_m2_model": float(exp_px[k] * PIXEL_M2),
                "n_px": int(n_px[k]), "raster": Path(path).stem,
            })
    return pd.DataFrame(results)


# --------------------------------------------------------------------------------------
# OSM/MaStR completeness (feeds the well-mapped chip filter)
# --------------------------------------------------------------------------------------
def osm_completeness(
    gemeinden: gpd.GeoDataFrame, labels: gpd.GeoDataFrame, mastr_df: pd.DataFrame,
    kwp_per_m2: float = 0.18,
) -> pd.DataFrame:
    rooftop = labels[labels.placement == "rooftop"]
    pts = gpd.GeoDataFrame(
        {"area_m2": rooftop.area_m2.to_numpy()},
        geometry=rooftop.geometry.centroid, crs="EPSG:4326",
    )
    joined = gpd.sjoin(pts, gemeinden[["ags", "geometry"]], how="inner", predicate="within")
    osm_agg = joined.groupby("ags", as_index=False)["area_m2"].sum().rename(
        columns={"area_m2": "osm_rooftop_area_m2"}
    )
    df = gemeinden[["ags", "name"]].merge(osm_agg, on="ags", how="left")
    df = df.merge(mastr_df[["ags", "kw_rooftop"]], on="ags", how="left")
    df["osm_rooftop_area_m2"] = df.osm_rooftop_area_m2.fillna(0.0)
    df["kw_rooftop"] = df.kw_rooftop.fillna(0.0)
    df["completeness"] = (
        df.osm_rooftop_area_m2 * kwp_per_m2 / df.kw_rooftop.clip(lower=1e-6)
    ).round(4)
    return df


# --------------------------------------------------------------------------------------
# Calibration fit
# --------------------------------------------------------------------------------------
def _fit_xy(x: np.ndarray, y: np.ndarray) -> dict:
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 2:
        return {"n": int(len(x))}
    slope_ols_origin = float(np.sum(x * y) / np.clip(np.sum(x**2), 1e-9, None))
    pos = x > 0
    slope_robust_median = float(np.median(y[pos] / x[pos])) if pos.any() else float("nan")
    r2 = float(np.corrcoef(x, y)[0, 1] ** 2) if x.std() > 0 and y.std() > 0 else float("nan")
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    spearman = float(np.corrcoef(rx, ry)[0, 1]) if rx.std() > 0 and ry.std() > 0 else float("nan")
    both_pos = (x > 0) & (y > 0)
    if both_pos.sum() > 2:
        lx, ly = np.log(x[both_pos]), np.log(y[both_pos])
        loglog_r = float(np.corrcoef(lx, ly)[0, 1]) if lx.std() > 0 and ly.std() > 0 else float("nan")
    else:
        loglog_r = float("nan")
    return {
        "n": int(len(x)), "slope_ols_origin": slope_ols_origin,
        "slope_robust_median": slope_robust_median, "r2": r2,
        "spearman_rho": spearman, "loglog_pearson_r": loglog_r,
    }


def fit_calibration(df: pd.DataFrame, kwp_per_m2: float) -> dict:
    x = (df.pv_m2_model.fillna(0.0) * kwp_per_m2 / 1000.0).to_numpy()  # model MWp
    y = (df.kw_rooftop.fillna(0.0) / 1000.0).to_numpy()  # MaStR MWp
    out = {"all": _fit_xy(x, y)}
    if "well_mapped" in df.columns and df.well_mapped.any():
        wm = df.well_mapped.to_numpy()
        out["well_mapped"] = _fit_xy(x[wm], y[wm])
    return out


def _scatter_plot(df: pd.DataFrame, kwp_per_m2: float, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = df.pv_m2_model.fillna(0.0) * kwp_per_m2 / 1000.0
    y = df.kw_rooftop.fillna(0.0) / 1000.0
    wm = df.get("well_mapped", pd.Series(False, index=df.index))
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(x[~wm], y[~wm], s=8, alpha=0.4, label="all gemeinden", color="gray")
    ax.scatter(x[wm], y[wm], s=10, alpha=0.7, label="well-mapped", color="C0")
    lim = max(x.max(), y.max(), 1e-3)
    ax.plot([0, lim], [0, lim], "k--", linewidth=1, label="1:1")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Model-derived rooftop PV (MWp)")
    ax.set_ylabel("MaStR rooftop PV (MWp)")
    ax.set_title("Model vs MaStR rooftop PV per Gemeinde")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def run_calibrate(
    aoi: str = "germany",
    pred_dir: Path = Path("data/predictions"),
    mastr_path: Path = Path("data/calibration/mastr_gemeinden.parquet"),
    min_prob: float = 0.05,
    kwp_per_m2: float = 0.18,
    completeness_threshold: float = 0.6,
    min_mastr_kw: float = 50.0,
    limit: int = 0,
    out_dir: Path = Path("data/calibration"),
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    resolve_aoi(aoi, settings)  # validates the AOI exists; germany is DE-only for now
    cfg = settings.aois[aoi]
    if (cfg.get("division") or {}).get("country") != "DE":
        raise ValueError(f"calibrate currently supports German AOIs only (got '{aoi}')")

    out_dir = Path(out_dir)
    try:
        gemeinden = fetch_gemeinden(out_dir)
    except Exception as e:  # noqa: BLE001 — degrade to the coarser fallback, don't abort
        log.warning("VG250 fetch failed (%s); falling back to Kreis-level boundaries", e)
        gemeinden = fetch_kreise_fallback(out_dir)
    if limit:
        gemeinden = gemeinden.head(limit)

    mastr_df = pd.read_parquet(mastr_path)

    prob_dir = Path(pred_dir) / aoi / "prob"
    zonal = zonal_model_area(gemeinden, prob_dir, min_prob=min_prob)

    labels_dir = Path(settings.raw["local_root"]) / cfg["source_region"]
    labels = load_solar_labels(labels_dir)
    # Completeness (OSM rooftop area vs MaStR kW) and the well-mapped flag are properties
    # of the LABELS, independent of which raster tiles happen to be inferred yet — compute
    # them over the FULL national Gemeinde set so `well_mapped.parquet` is usable as a
    # chips.py region_filter for training anywhere, not just wherever prob rasters exist.
    completeness = osm_completeness(gemeinden, labels, mastr_df, kwp_per_m2=kwp_per_m2)
    completeness["well_mapped"] = (
        (completeness.completeness >= completeness_threshold)
        & (completeness.kw_rooftop >= min_mastr_kw)
    )

    # `joined` (raster-covered subset only) is for the correlation FIT, which does need
    # actual model output; it inherits well_mapped via the merge.
    joined = zonal.merge(completeness, on="ags", how="left")
    joined = joined.merge(gemeinden[["ags", "geometry"]], on="ags", how="left")

    calibration = fit_calibration(joined, kwp_per_m2)

    out_dir.mkdir(parents=True, exist_ok=True)
    completeness.to_parquet(out_dir / "completeness.parquet")
    well_mapped_gdf = gpd.GeoDataFrame(
        completeness[completeness.well_mapped].merge(gemeinden[["ags", "geometry"]], on="ags")
        [["ags", "name", "completeness", "kw_rooftop", "geometry"]],
        geometry="geometry", crs="EPSG:4326",
    )
    well_mapped_gdf.to_parquet(out_dir / "well_mapped.parquet")
    joined.drop(columns=["geometry"]).to_csv(out_dir / "gemeinden_joined.csv", index=False)
    (out_dir / "calibration.json").write_text(json.dumps({
        "aoi": aoi, "pred_dir": str(pred_dir), "min_prob": min_prob, "kwp_per_m2": kwp_per_m2,
        "completeness_threshold": completeness_threshold, "min_mastr_kw": min_mastr_kw,
        "n_gemeinden_joined": int(len(joined)), "n_well_mapped": int(joined.well_mapped.sum()),
        **calibration,
    }, indent=2))
    try:
        _scatter_plot(joined, kwp_per_m2, out_dir / "calibration_scatter.png")
    except Exception as e:  # noqa: BLE001 — plotting must not fail the run
        log.warning("Scatter plot failed: %s", e)

    log.info("Calibration: %s", json.dumps(calibration, indent=2))
    log.info("Wrote calibration outputs -> %s", out_dir)
    return out_dir
