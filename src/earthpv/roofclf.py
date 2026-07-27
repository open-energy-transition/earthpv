"""Per-building rooftop-PV classifier, trained on the fully-mapped calibration quadrats.

## Why the unit of prediction changes

At 10 m GSD a 100 m² array is one mixed pixel. You cannot outline it, and the segmentation
model is not even asked to try: `chips.MIN_PV_AREA` burns everything below 400 m² as
`ignore = -1`, so it receives no gradient there and has no reason to put probability mass
on a small array. The measured consequence is that the whole sub-500 m² class contributes
~8 MWp to the Pakistan national estimate, while a single fully-mapped square kilometre of
residential Lahore holds 3.3x more sub-100 m² PV area than the model finds nationwide.

Recall-corrected estimation cannot repair that: `1/recall x ~0 ~ 0`. A class you never
detect is not recoverable by reweighting the class you do detect. It needs a different
estimator, and this module is it.

The question asked here is **"does this building carry PV?"**, not "where are its panel
edges". That is a far easier problem at one mixed pixel: it needs the footprint's spectral
signature to differ from a PV-free roof of the same kind, not a resolvable outline. The
output is a calibrated per-building probability, which aggregates directly into an
adoption rate per cell/region and, with a kWp-per-roof-area factor measured on the same
quadrats, into capacity.

## Why the quadrats are the only usable label source

Ordinary OSM is incomplete at small sizes, so a building with no mapped PV is not a
negative. In an exhaustively mapped quadrat it is: every building carries a verified
has-PV / has-no-PV label. That is exactly the supervision missing in the failure regime,
and it is why these quadrats should not be spent only on post-hoc correction.

The sample is also the honest limit of this module. Of the six available quadrats, four are
industrial estates and two residential, and PV area below 500 m² is 96-98% of the
residential boxes against 4-10% of the industrial ones. So the pooled set under-represents
exactly the stratum the module exists to serve, and reported skill must be read per quadrat,
never pooled. `evaluate` therefore reports leave-one-quadrat-out folds and refuses to
headline a pooled number.

Only `karachi_coast_calib_700m` is asserted **Rule-1 complete** (every visible panel mapped,
verified against imagery by the repository owner). It is therefore the only quadrat whose
has-no-PV buildings are trustworthy negatives, and the only one where a low score cannot be
blamed on missing labels. It is also the hardest: median installation 86 m², 98.8% of
installations below the 400 m² detection floor, and the segmentation raster predicts
*exactly zero* PV area over its buildings (AUC 0.500, chance).

## Size is a confounder, so skill is reported conditional on it

Adoption rises with house size -- mappers report large houses packed with PV and small ones
much less -- so footprint area alone reaches AUC ~0.73 without the imagery contributing
anything. `auc_within_size` scores inside roof-area bands (`_SIZE_BANDS`) and n-weights the
result, which removes size as a discriminator entirely and measures what the pixels add at
fixed size. Median across folds: 0.845 conditional against 0.879 unconditional, so the size
prior is worth about 3 points and the imagery carries the rest. The same statistic for the
segmentation raster is 0.707, and 0.500 on the Rule-1 quadrat.

## Model

Regularised logistic regression on standardised features, fitted with scipy L-BFGS. Chosen
over gradient boosting deliberately: the output must be a *calibrated probability*, because
it is summed into an adoption rate rather than thresholded, and with five spatial folds and
a few thousand rows a linear model in good features is the appropriate capacity. No
scikit-learn dependency, so this runs in the base (no-torch) environment like every other
data stage. `--model` is where a boosted variant would go once there are more quadrats.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.transform
from rasterio.warp import transform_bounds
from shapely.geometry import box as shapely_box

log = logging.getLogger(__name__)

# Composite reflectance is uint16 scaled by this (Sentinel-2 L2A convention).
REFL_SCALE = 10000.0
# config.LOCAL_BANDS order; NIR_BROAD / RED / SWIR_1 indices used for the ratio features.
BAND_NAMES = ("b02", "b03", "b04", "b05", "b06", "b07", "b08", "b8a", "b11", "b12")
_I_RED, _I_NIR, _I_SWIR1, _I_BLUE, _I_GREEN = 2, 6, 8, 0, 1

# A building counts as PV-carrying when a mapped array covers at least this share of it, so
# a panel array that merely clips a neighbouring roof's edge does not label that roof.
MIN_PV_OVERLAP_FRAC = 0.05
# Ridge strength on standardised features. Deliberately firm: five spatial folds cannot
# support tuning, so this is set once and left.
L2 = 1.0


# --------------------------------------------------------------------------------------
# Quadrat discovery and labels
# --------------------------------------------------------------------------------------
_BOUNDARY_SUFFIX = "_boundary.geojson"


def discover_quadrats(labels_dir: Path = Path("data/labels")) -> list[str]:
    """Quadrat stems that have both a boundary and a mapped-solar file.

    A stem is the full prefix before `_boundary.geojson`, e.g. `site_karachi_calib_1km` or
    `karachi_coast_calib_700m`. Matching on `_calib_*_` rather than a hard-coded `_calib_1km_`
    keeps the quadrat size out of the code: the protocol calls for 1-4 km2 boxes and the
    first Rule-1-complete one is 0.49 km2.
    """
    out = []
    for b in sorted(Path(labels_dir).glob(f"*_calib_*{_BOUNDARY_SUFFIX}")):
        stem = b.name[: -len(_BOUNDARY_SUFFIX)]
        if _newest_solar(stem, labels_dir) is not None:
            out.append(stem)
    return out


def quadrat_label(stem: str) -> str:
    """Short display name for a quadrat stem (`lahore_calib_1km` -> `lahore`)."""
    return re.sub(r"_calib_.*$", "", stem)


def _newest_solar(stem: str, labels_dir: Path) -> Path | None:
    """Newest mapped-solar pull for a quadrat.

    Mapping is iterative and a quadrat gets re-pulled after a completeness pass, so the
    dated file supersedes the undated one. Picking the stale pull silently encodes
    whatever was cached at pull time as ground truth -- the exact failure recorded in
    docs/issues/pakistan-calibration-boxes.md. Lexicographic order does this correctly
    because '.' sorts before '_', so `..._overpass_solar.parquet` precedes any
    `..._overpass_solar_<date>.parquet`.
    """
    cands = sorted(Path(labels_dir).glob(f"{stem}_overpass_solar*.parquet"))
    return cands[-1] if cands else None


def load_quadrat(stem: str, labels_dir: Path = Path("data/labels")) -> tuple:
    """`(boundary geometry, mapped PV polygons)` for one quadrat, in EPSG:4326."""
    boundary = gpd.read_file(
        Path(labels_dir) / f"{stem}{_BOUNDARY_SUFFIX}"
    ).to_crs("EPSG:4326").geometry.iloc[0]
    solar_path = _newest_solar(stem, labels_dir)
    pv = gpd.read_parquet(solar_path).to_crs("EPSG:4326")
    pv = pv[pv.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    log.info("quadrat %s: %d mapped PV polygons from %s", stem, len(pv), solar_path.name)
    return boundary, pv


# --------------------------------------------------------------------------------------
# Per-footprint zonal statistics
# --------------------------------------------------------------------------------------
def zonal_mean_max(
    bu_utm: gpd.GeoDataFrame, arr: np.ndarray, transform
) -> tuple[np.ndarray, np.ndarray]:
    """Per-building mean and max of a (bands, H, W) or (H, W) array over its footprint.

    Sub-pixel footprints rasterize to zero pixels -- about half of Pakistani VIDA
    buildings -- and those fall back to their representative point's pixel, which is the
    same convention `density.per_building_raster_stats` uses. Without the fallback the
    entire small-building population, i.e. the population this module exists for, would
    drop out of the table.
    """
    if arr.ndim == 2:
        arr = arr[None]
    nb, h, w = arr.shape
    n = len(bu_utm)
    idx = rasterio.features.rasterize(
        ((g, i) for i, g in enumerate(bu_utm.geometry, start=1)),
        out_shape=(h, w), transform=transform, fill=0, all_touched=False, dtype="int32",
    )
    flat = idx.ravel()
    counts = np.bincount(flat, minlength=n + 1)[1:]
    means = np.zeros((nb, n), dtype="float64")
    maxes = np.zeros((nb, n), dtype="float64")
    for b in range(nb):
        v = arr[b].ravel().astype("float64")
        s = np.bincount(flat, weights=v, minlength=n + 1)[1:]
        with np.errstate(invalid="ignore", divide="ignore"):
            means[b] = np.where(counts > 0, s / np.maximum(counts, 1), 0.0)
        m = np.zeros(n + 1)
        np.maximum.at(m, flat, v)
        maxes[b] = m[1:]

    zero = counts == 0
    if zero.any():
        pts = bu_utm.geometry.representative_point()
        rr, cc = rasterio.transform.rowcol(
            transform, pts.x.to_numpy()[zero], pts.y.to_numpy()[zero]
        )
        rr = np.clip(np.asarray(rr), 0, h - 1)
        cc = np.clip(np.asarray(cc), 0, w - 1)
        for b in range(nb):
            v = arr[b][rr, cc].astype("float64")
            means[b, zero] = v
            maxes[b, zero] = v
    return means, maxes


def _raster_for(point, prob_dir: Path) -> Path | None:
    """The per-cell raster in `prob_dir` whose extent contains `point`."""
    for tif in sorted(Path(prob_dir).glob("*.tif")):
        with rasterio.open(tif) as src:
            if shapely_box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds)).contains(point):
                return tif
    return None


def _read_prob(path: Path, bounds4326: tuple, out_crs, out_transform, out_shape) -> np.ndarray:
    """A 0-1 probability raster resampled onto the composite's grid for this quadrat."""
    from rasterio.warp import Resampling, reproject

    with rasterio.open(path) as src:
        w, s, e, n = transform_bounds("EPSG:4326", src.crs, *bounds4326)
        win = rasterio.windows.from_bounds(w, s, e, n, transform=src.transform)
        win = win.round_offsets().round_lengths().intersection(
            rasterio.windows.Window(0, 0, src.width, src.height)
        )
        data = src.read(1, window=win).astype("float32") / 255.0
        src_tf = rasterio.windows.transform(win, src.transform)
        src_crs = src.crs
    out = np.zeros(out_shape, dtype="float32")
    reproject(
        source=data, destination=out, src_transform=src_tf, src_crs=src_crs,
        dst_transform=out_transform, dst_crs=out_crs, resampling=Resampling.bilinear,
    )
    return out


# --------------------------------------------------------------------------------------
# Feature table
# --------------------------------------------------------------------------------------
def building_table(
    stem: str, iso3: str, composites: Path, seg_prob_dir: Path | None,
    frac_prob_dir: Path | None, labels_dir: Path = Path("data/labels"), con=None,
) -> pd.DataFrame:
    """One row per VIDA building in the quadrat, labelled and featurised."""
    from earthpv.buildings import fetch_vida_buildings
    from earthpv.labels import geodesic_area_m2
    from earthpv.local_source import CompositeIndex

    boundary, pv = load_quadrat(stem, labels_dir)
    name = quadrat_label(stem)
    minx, miny, maxx, maxy = boundary.bounds
    bu = fetch_vida_buildings((minx, miny, maxx, maxy), iso3, con=con).reset_index(drop=True)
    if bu.empty:
        log.warning("quadrat %s: no VIDA buildings", name)
        return pd.DataFrame()
    inside = bu.geometry.representative_point().within(boundary)
    bu = bu[inside.to_numpy()].reset_index(drop=True)
    if bu.empty:
        return pd.DataFrame()

    # Labels: true PV area on each footprint, then a has-PV flag by overlap share.
    pv_area = np.zeros(len(bu))
    if not pv.empty:
        sindex = bu.sindex
        for g in pv.geometry:
            for bi in sindex.query(g, predicate="intersects"):
                inter = geodesic_area_m2(bu.geometry.iloc[bi].intersection(g))
                if inter > 0:
                    pv_area[bi] += inter
    roof = bu["area_m2"].to_numpy(float)
    frac_true = np.divide(pv_area, np.maximum(roof, 1e-6))

    # Imagery on the composite's own grid; the probability rasters are resampled onto it.
    res = CompositeIndex(Path(composites)).read_window((minx, miny, maxx, maxy))
    if res is None:
        log.warning("quadrat %s: no composite coverage", name)
        return pd.DataFrame()
    arr, transform, crs = res
    arr = arr[: len(BAND_NAMES)].astype("float32") / REFL_SCALE
    bu_utm = bu.to_crs(crs)
    means, maxes = zonal_mean_max(bu_utm, arr, transform)

    out = gpd.GeoDataFrame({
        "quadrat": name,
        "geometry": bu.geometry.to_numpy(),
        "roof_area_m2": roof,
        "bf_confidence": bu.get("bf_confidence", pd.Series(np.nan, index=bu.index)).to_numpy(),
        "pv_area_true_m2": pv_area,
        "pv_frac_true": frac_true,
        "has_pv": (frac_true >= MIN_PV_OVERLAP_FRAC).astype(int),
    })
    for i, b in enumerate(BAND_NAMES):
        out[f"{b}_mean"] = means[i]
    eps = 1e-6
    r, nir, sw = means[_I_RED], means[_I_NIR], means[_I_SWIR1]
    out["ndvi"] = (nir - r) / (nir + r + eps)
    out["ndbi"] = (sw - nir) / (sw + nir + eps)
    out["brightness"] = means.mean(axis=0)
    # PV modules are dark and comparatively flat across the visible, with a
    # characteristic SWIR drop; these two ratios carry most of that shape.
    out["swir_vis_ratio"] = sw / (means[[_I_BLUE, _I_GREEN, _I_RED]].mean(axis=0) + eps)
    out["blue_red_ratio"] = means[_I_BLUE] / (r + eps)

    bounds = (minx, miny, maxx, maxy)
    for label, d in (("seg", seg_prob_dir), ("frac", frac_prob_dir)):
        out[f"{label}_mean"] = 0.0
        out[f"{label}_max"] = 0.0
        if d is None:
            continue
        path = _raster_for(boundary.centroid, Path(d))
        if path is None:
            log.warning("quadrat %s: no %s raster covers it", name, label)
            continue
        p = _read_prob(path, bounds, crs, transform, arr.shape[-2:])
        pm, px = zonal_mean_max(bu_utm, p, transform)
        out[f"{label}_mean"], out[f"{label}_max"] = pm[0], px[0]
    out = out.set_geometry("geometry").set_crs("EPSG:4326")
    log.info(
        "quadrat %s: %d buildings, %d with PV (%.1f%%), true PV area %.0f m2",
        name, len(out), int(out.has_pv.sum()), 100 * out.has_pv.mean(), pv_area.sum(),
    )
    return out


SPECTRAL_FEATURES = [f"{b}_mean" for b in BAND_NAMES] + [
    "ndvi", "ndbi", "brightness", "swir_vis_ratio", "blue_red_ratio"
]
# The existing model outputs as features. Measured to add nothing (median fold AUC 0.8819
# -> 0.8834) and to *cost* accuracy on the sub-500 m2 buildings this module is for
# (0.8815 -> 0.8698), which is unsurprising: the segmentation model is trained with those
# arrays burned as ignore, so its probability there is noise the fit can only chase. Kept
# available behind `include_prob_features`, and always computed so `_fold_report` can keep
# scoring them as baselines.
PROB_FEATURES = ["seg_mean", "frac_mean"]
# Default model input: footprint size plus footprint reflectance. Set by the ablation, not
# by preference.
MODEL_FEATURES = ["log_roof_area", "bf_confidence"] + SPECTRAL_FEATURES
FEATURES = MODEL_FEATURES + PROB_FEATURES  # every column the table carries


def design_matrix(df: pd.DataFrame, feats: list[str] | None = None) -> np.ndarray:
    d = df.copy()
    d["log_roof_area"] = np.log10(d.roof_area_m2.clip(lower=1.0))
    d["bf_confidence"] = d.bf_confidence.fillna(d.bf_confidence.median() if
                                                d.bf_confidence.notna().any() else 0.0)
    return d[feats or MODEL_FEATURES].to_numpy(dtype="float64")


# --------------------------------------------------------------------------------------
# Logistic regression (scipy), AUC
# --------------------------------------------------------------------------------------
def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = L2) -> dict:
    """L2-regularised logistic regression on standardised features, via L-BFGS.

    The intercept is unpenalised so the fitted base rate is not shrunk toward 0.5 -- this
    model's output is aggregated into an adoption rate, where the base rate is the point.
    """
    from scipy.optimize import minimize

    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.hstack([(X - mu) / sd, np.ones((len(X), 1))])

    def nll(w):
        z = Z @ w
        # log(1+exp(z)) computed stably
        ll = np.sum(y * z - np.logaddexp(0.0, z))
        pen = l2 * np.sum(w[:-1] ** 2) / 2.0
        g = Z.T @ (1.0 / (1.0 + np.exp(-z)) - y)
        g[:-1] += l2 * w[:-1]
        return -ll + pen, g

    w0 = np.zeros(Z.shape[1])
    res = minimize(nll, w0, jac=True, method="L-BFGS-B")
    return {"w": res.x, "mu": mu, "sd": sd, "converged": bool(res.success)}


def predict_proba(model: dict, X: np.ndarray) -> np.ndarray:
    Z = np.hstack([(X - model["mu"]) / model["sd"], np.ones((len(X), 1))])
    return 1.0 / (1.0 + np.exp(-(Z @ model["w"])))


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """ROC AUC via the rank (Mann-Whitney) identity; ties handled by average ranks."""
    y = np.asarray(y).astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = pd.Series(s).rank().to_numpy()
    return float((r[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------
# Roof-area bands for the size-conditional AUC. Adoption genuinely rises with house size
# (mappers report large houses packed with PV and small ones much less), so a classifier
# given footprint area scores well above chance from that propensity alone -- roof area by
# itself reaches ~0.73 here. Scoring *within* a band removes size as a discriminator, so
# what is left is the imagery actually separating a PV roof from a PV-free roof of the same
# size. This is the honest headline for what the pixels contribute.
_SIZE_BANDS = ((0, 50), (50, 100), (100, 200), (200, 400), (400, np.inf))


def auc_within_size(
    y: np.ndarray, s: np.ndarray, roof: np.ndarray
) -> tuple[float, list[dict]]:
    """Size-conditional AUC: AUC inside each roof-area band, then an n-weighted mean.

    Bands with no positive or no negative case are skipped (AUC undefined), and their
    counts are excluded from the weighting rather than scored as 0.5.
    """
    rows, num, den = [], 0.0, 0
    for lo, hi in _SIZE_BANDS:
        m = (roof >= lo) & (roof < hi)
        if m.sum() < 2:
            continue
        a = auc(y[m], s[m])
        rows.append({
            "band": f"{lo:g}-{'inf' if hi == np.inf else f'{hi:g}'}",
            "n": int(m.sum()), "n_pv": int(y[m].sum()),
            "auc": None if np.isnan(a) else round(a, 4),
        })
        if not np.isnan(a):
            num += a * m.sum()
            den += int(m.sum())
    return (num / den if den else float("nan")), rows


def _fold_report(name: str, y: np.ndarray, p: np.ndarray, df: pd.DataFrame) -> dict:
    small = (df.roof_area_m2.to_numpy() < 500.0)
    roof = df.roof_area_m2.to_numpy()
    within, _ = auc_within_size(y, p, roof)
    within_seg, _ = auc_within_size(y, df.seg_mean.to_numpy(), roof)
    return {
        "quadrat": name,
        "n": int(len(y)),
        "n_pv": int(y.sum()),
        "base_rate": round(float(y.mean()), 4),
        "auc": round(auc(y, p), 4),
        "auc_small": round(auc(y[small], p[small]), 4) if small.sum() > 1 else float("nan"),
        "auc_seg_baseline": round(auc(y, df.seg_mean.to_numpy()), 4),
        "auc_frac_baseline": round(auc(y, df.frac_mean.to_numpy()), 4),
        "auc_within_size": round(within, 4),
        "auc_within_size_seg": round(within_seg, 4),
        "pred_rate": round(float(p.mean()), 4),
        "rate_ratio": round(float(p.mean() / max(y.mean(), 1e-9)), 3),
    }


def evaluate(
    table: pd.DataFrame, l2: float = L2, feats: list[str] | None = None
) -> tuple[pd.DataFrame, dict, np.ndarray]:
    """Leave-one-quadrat-out evaluation.

    Returns `(fold table, summary, out-of-fold probability per row)`. The third is the only
    honest per-building prediction available for these rows -- every building scored by a
    model that never saw its quadrat -- so it is what gets written to the table.

    A random split would put buildings from the same street in train and test and report
    fantasy skill; the quadrats are the only meaningful spatial unit here. Folds are
    reported individually because the five quadrats are not one population -- four
    industrial estates and one residential neighbourhood.
    """
    rows, oof = [], np.full(len(table), np.nan)
    for name in table.quadrat.unique():
        te = table.quadrat == name
        tr = ~te
        if table.loc[tr, "has_pv"].nunique() < 2 or te.sum() == 0:
            continue
        m = fit_logistic(
            design_matrix(table[tr], feats), table.loc[tr, "has_pv"].to_numpy(float), l2
        )
        p = predict_proba(m, design_matrix(table[te], feats))
        oof[te.to_numpy()] = p
        rows.append(_fold_report(name, table.loc[te, "has_pv"].to_numpy(), p, table[te]))
    folds = pd.DataFrame(rows)
    full = fit_logistic(design_matrix(table, feats), table.has_pv.to_numpy(float), l2)
    summary = {
        "n_buildings": int(len(table)),
        "n_pv": int(table.has_pv.sum()),
        "n_quadrats": int(table.quadrat.nunique()),
        "median_fold_auc": round(float(folds.auc.median()), 4) if len(folds) else None,
        "min_fold_auc": round(float(folds.auc.min()), 4) if len(folds) else None,
        "median_fold_auc_small": (
            round(float(folds.auc_small.median()), 4) if len(folds) else None
        ),
        # The size-confound-free headline: what the imagery adds at fixed roof size.
        "median_fold_auc_within_size": (
            round(float(folds.auc_within_size.median()), 4) if len(folds) else None
        ),
        "median_fold_auc_within_size_seg": (
            round(float(folds.auc_within_size_seg.median()), 4) if len(folds) else None
        ),
        "median_seg_baseline_auc": (
            round(float(folds.auc_seg_baseline.median()), 4) if len(folds) else None
        ),
        "median_frac_baseline_auc": (
            round(float(folds.auc_frac_baseline.median()), 4) if len(folds) else None
        ),
        "features": list(feats or MODEL_FEATURES),
        "coef": {
            f: round(float(c), 4)
            for f, c in zip(feats or MODEL_FEATURES, full["w"][:-1])
        },
        "intercept": round(float(full["w"][-1]), 4),
    }
    return folds, summary, oof


_ABLATIONS = {
    # Bigger roofs carry PV more often, so a model given only footprint size already
    # scores well above chance. Unless the spectral block beats this it is decoration:
    # "large buildings have PV" is a prior, not a measurement of *this* building.
    "area_only": ["log_roof_area", "bf_confidence"],
    # The converse: does the imagery alone separate PV roofs, with no size hint?
    "spectral_only": list(SPECTRAL_FEATURES),
    # The shipped default.
    "size_plus_spectral": list(MODEL_FEATURES),
    "plus_prob_rasters": list(FEATURES),
}


def ablate(table: pd.DataFrame, l2: float = L2) -> pd.DataFrame:
    """Leave-one-quadrat-out AUC per feature block, so the size prior is separated out."""
    rows = []
    for label, feats in _ABLATIONS.items():
        for name in table.quadrat.unique():
            te = (table.quadrat == name).to_numpy()
            tr = ~te
            if table.loc[tr, "has_pv"].nunique() < 2:
                continue
            Xtr, Xte = _subset_matrix(table[tr], feats), _subset_matrix(table[te], feats)
            m = fit_logistic(Xtr, table.loc[tr, "has_pv"].to_numpy(float), l2)
            p = predict_proba(m, Xte)
            y = table.loc[te, "has_pv"].to_numpy()
            small = table.loc[te, "roof_area_m2"].to_numpy() < 500.0
            rows.append({
                "block": label, "quadrat": name, "auc": round(auc(y, p), 4),
                "auc_small": round(auc(y[small], p[small]), 4) if small.sum() > 1 else np.nan,
            })
    df = pd.DataFrame(rows)
    return df.pivot_table(index="block", values=["auc", "auc_small"], aggfunc="median").round(4)


def _subset_matrix(df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    d = df.copy()
    d["log_roof_area"] = np.log10(d.roof_area_m2.clip(lower=1.0))
    d["bf_confidence"] = d.bf_confidence.fillna(
        d.bf_confidence.median() if d.bf_confidence.notna().any() else 0.0
    )
    return d[feats].to_numpy(dtype="float64")


def exp_scale_anchor(table: pd.DataFrame) -> pd.DataFrame:
    """Absolute-scale anchor for the density stage's expected-area instruments.

    For each quadrat: the PV area each raster-integral estimator predicts over the
    quadrat's buildings, against the exhaustively mapped truth. `scale` is the factor
    `density --exp-scale` should divide by, i.e. predicted / true. This is what the German
    MaStR bench cannot settle -- there its two slope estimators disagree by 2.6x and its
    well-mapped subset by 13x -- because here the denominator is complete by construction.
    """
    rows = []
    for name, g in table.groupby("quadrat"):
        roof = g.roof_area_m2.to_numpy()
        true = float(g.pv_area_true_m2.sum())
        for label in ("seg", "frac"):
            pred = float(np.minimum(g[f"{label}_mean"].to_numpy() * roof, roof).sum())
            rows.append({
                "quadrat": name, "instrument": label,
                "pred_pv_area_m2": round(pred, 1), "true_pv_area_m2": round(true, 1),
                "scale": round(pred / true, 3) if true > 0 else float("nan"),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def run_roof_classifier(
    aoi: str = "pakistan",
    quadrats: list[str] | None = None,
    composites: Path = Path("data/composites/pakistan"),
    seg_prob_dir: Path | None = Path("data/predictions_pk16085/pakistan/prob"),
    frac_prob_dir: Path | None = Path("data/predictions_frac_pk_v2/pakistan/prob"),
    labels_dir: Path = Path("data/labels"),
    out_dir: Path = Path("data/roofclf"),
    l2: float = L2,
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv import overture
    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    iso3 = _iso3_for(cfg)
    if iso3 is None:
        raise ValueError(f"AOI '{aoi}' has no division.iso3 -> cannot locate VIDA buildings")
    names = quadrats or discover_quadrats(labels_dir)
    if not names:
        raise FileNotFoundError(f"No calibration quadrats found in {labels_dir}")
    log.info("Quadrats: %s", ", ".join(names))

    con = overture.connect()
    parts = [
        building_table(n, iso3, composites, seg_prob_dir, frac_prob_dir, labels_dir, con)
        for n in names
    ]
    # Keep geometry so the per-building predictions are mappable (QGIS, the docs figure).
    table = gpd.GeoDataFrame(
        pd.concat([p for p in parts if not p.empty], ignore_index=True),
        geometry="geometry", crs="EPSG:4326",
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    folds, summary, oof = evaluate(table, l2=l2)
    table["p_oof"] = oof  # scored by a model that never saw this building's quadrat
    table.to_parquet(out_dir / "buildings.geoparquet")
    anchor = exp_scale_anchor(table)
    abl = ablate(table, l2=l2)
    summary["ablation_median_auc"] = {k: float(v) for k, v in abl["auc"].items()}
    summary["ablation_median_auc_small"] = {k: float(v) for k, v in abl["auc_small"].items()}
    folds.to_csv(out_dir / "folds.csv", index=False)
    anchor.to_csv(out_dir / "exp_scale_anchor.csv", index=False)
    abl.to_csv(out_dir / "ablation.csv")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    log.info("Leave-one-quadrat-out folds:\n%s", folds.to_string(index=False))
    log.info("Feature-block ablation (median across folds):\n%s", abl.to_string())
    log.info("Expected-area absolute-scale anchor:\n%s", anchor.to_string(index=False))
    log.info("Summary: %s", json.dumps(summary, indent=2))
    return out_dir
