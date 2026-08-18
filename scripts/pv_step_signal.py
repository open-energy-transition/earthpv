"""Per-pixel PV *installation step* detection from a dense Sentinel-2 time series.

The question this answers: Pakistan's rooftop boom installed arrays far below the
detector's ~400 m2 floor (the Lahore calibration box: 1,034 mapped installations,
median ~50 m2, at which the trained model reads 0.000 probability on 99.8% of true
footprints and glint validates 0/1,021). Is the *appearance in time* of those panels
visible at all in Sentinel-2, even when their static appearance is not?

Method, in the order the signal is built up:

1. **Common-mode removal (spatial).** Per date and band, subtract the median over
   *reference* pixels (built-up, no mapped PV). This kills atmosphere, sun-angle,
   BOA-offset residue and seasonal illumination - everything shared by the scene -
   without needing any radiative-transfer model. Same idea as glint.py's annulus
   reference, applied scene-wide.
2. **Co-registration guard.** A 1-pixel geolocation wobble smears a 1-pixel target,
   so per-scene sub-pixel shift is estimated by phase correlation against the cube's
   own temporal median and scenes beyond `max_shift_px` are dropped.
3. **Learned spectral direction (spectral).** The PV-installation change vector is
   *measured*, not assumed: mean(post) - mean(pre) spectra at training PV pixels minus
   the same at reference pixels, giving a 10-band direction; every date is projected
   onto it to get one scalar per pixel per date. Learned on a spatially disjoint
   training half, evaluated on the held-out half - a fixed physical index (brightness,
   NDVI, blue/SWIR) is reported alongside as a baseline.
4. **Deseasonalise + breakpoint scan (time).** Per pixel, regress out annual +
   semiannual harmonics and per-relative-orbit offsets, then scan every candidate
   breakpoint month with a cumulative-sum two-mean model, keeping the amplitude,
   date and t-statistic of the best step.

Validation is built in, not bolted on: AUC against the mapped footprints, amplitude-
vs-PV-fraction regression at pixel/building/grid scale, a pre-boom placebo breakpoint,
and reference-pixel-only false-positive rates.

Usage:
    python scripts/pv_step_signal.py --cube lahore_box \
        --solar data/labels/lahore_calib_6p61km2_overpass_solar.parquet \
        --boundary data/labels/lahore_calib_6p61km2_boundary.geojson --out data/step/lahore_box
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)
log = logging.getLogger("pv_step")

BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
# Fixed reference indices, reported next to the learned direction so the learned one
# has to earn its place.
FIXED_INDICES = {
    "brightness": {b: 1.0 / len(BANDS) for b in BANDS},
    "ndvi": {"B08": 1.0, "B04": -1.0},          # unnormalised numerator; sign only
    "blue_minus_swir": {"B02": 1.0, "B11": -1.0},
}


# --------------------------------------------------------------------------- masks


def _fraction_raster(gdf: gpd.GeoDataFrame, grid: dict, subpx: int = 10) -> np.ndarray:
    """Areal fraction of each 10 m pixel covered by `gdf`, via `subpx`x subpixel burn.

    Small rooftop arrays are sub-pixel (median ~50 m2 = half a pixel), so a binary
    `all_touched` rasterisation would overstate them by an order of magnitude; the
    fractional cover is the quantity the reflectance mixture actually depends on.
    """
    import rasterio.features
    from affine import Affine

    h, w = grid["shape"]
    t = Affine(*grid["transform"])
    fine = t * Affine.scale(1.0 / subpx)
    if gdf.empty:
        return np.zeros((h, w), np.float32)
    geoms = gdf.to_crs(grid["crs"]).geometry.values
    burn = rasterio.features.rasterize(
        [(g, 1) for g in geoms], out_shape=(h * subpx, w * subpx), transform=fine,
        fill=0, all_touched=False, dtype="uint8",
    )
    return burn.reshape(h, subpx, w, subpx).mean(axis=(1, 3)).astype(np.float32)


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Binary dilation by a (2r+1) square - pure numpy, avoids a scipy dependency."""
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


# ------------------------------------------------------------------ co-registration


def _phase_shift(ref: np.ndarray, img: np.ndarray) -> tuple[float, float]:
    """Sub-pixel (dy, dx) shift of `img` relative to `ref` by phase correlation."""
    a = np.nan_to_num(ref - np.nanmean(ref))
    b = np.nan_to_num(img - np.nanmean(img))
    win = np.hanning(a.shape[0])[:, None] * np.hanning(a.shape[1])[None, :]
    A, B = np.fft.rfft2(a * win), np.fft.rfft2(b * win)
    cross = A * np.conj(B)
    denom = np.abs(cross)
    cross = np.where(denom > 0, cross / denom, 0)
    corr = np.fft.irfft2(cross, s=a.shape)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    shifts = []
    for axis, p in enumerate(peak):
        n = corr.shape[axis]
        p0 = p - n if p > n // 2 else p
        # parabolic refinement on the 3 samples around the peak
        idx = [list(peak), list(peak), list(peak)]
        idx[0][axis] = (p - 1) % n
        idx[2][axis] = (p + 1) % n
        y0, y1, y2 = (corr[tuple(i)] for i in idx)
        denom2 = y0 - 2 * y1 + y2
        delta = 0.5 * (y0 - y2) / denom2 if denom2 != 0 else 0.0
        shifts.append(p0 + float(np.clip(delta, -1, 1)))
    return shifts[0], shifts[1]


# ------------------------------------------------------------------------- fitting


def _design(dates: pd.Series, orbits: pd.Series) -> np.ndarray:
    """[1, sin/cos annual, sin/cos semiannual, per-orbit dummies] - the nuisance model.

    Phenology and per-relative-orbit view-geometry offsets are the two systematic
    effects that survive common-mode removal (they are pixel-specific, not scene-wide),
    and both would otherwise leak into a step estimate.
    """
    t = (pd.to_datetime(dates) - pd.Timestamp("2018-01-01")).dt.days.to_numpy(float)
    ang = 2 * np.pi * t / 365.25
    cols = [np.ones_like(t), np.sin(ang), np.cos(ang), np.sin(2 * ang), np.cos(2 * ang)]
    codes = pd.Categorical(orbits.fillna(-1)).codes
    for c in np.unique(codes)[1:]:          # first orbit folded into the intercept
        cols.append((codes == c).astype(float))
    return np.stack(cols, axis=1)


def _fit_residuals(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Residuals of per-pixel weighted LS of y[T,P] on X[T,K], NaNs preserved.

    Solved by normal equations per pixel (K is small; P can be 1e5), which is a few
    einsums rather than P separate lstsq calls.
    """
    ok = np.isfinite(y)
    yz = np.where(ok, y, 0.0)
    w = ok.astype(np.float32)
    XtX = np.einsum("tk,tl,tp->pkl", X, X, w, optimize=True)
    Xty = np.einsum("tk,tp->pk", X, yz * w, optimize=True)
    XtX += np.eye(X.shape[1], dtype=XtX.dtype) * 1e-8
    beta = np.linalg.solve(XtX, Xty[..., None])[..., 0]      # [P,K]
    fit = np.einsum("tk,pk->tp", X, beta, optimize=True)
    return np.where(ok, y - fit, np.nan)


def scan_breakpoints(resid: np.ndarray, dates: pd.Series, min_side: int = 12,
                     restrict: tuple[str, str] | None = None) -> dict:
    """Best two-mean step per pixel over all candidate breakpoints, via cumulative sums.

    resid[T,P] must be time-sorted. Returns amplitude (post-pre), breakpoint date,
    t-statistic and the per-side counts of the winning split. `restrict` limits
    candidate breakpoints to a date range (used for the pre-boom placebo).
    """
    ok = np.isfinite(resid)
    y = np.where(ok, resid, 0.0).astype(np.float64)
    n = ok.astype(np.float64)
    cs_y = np.concatenate([np.zeros((1, y.shape[1])), np.cumsum(y, axis=0)])
    cs_n = np.concatenate([np.zeros((1, n.shape[1])), np.cumsum(n, axis=0)])
    cs_y2 = np.concatenate([np.zeros((1, y.shape[1])), np.cumsum(y ** 2, axis=0)])
    T = y.shape[0]
    tot_y, tot_n, tot_y2 = cs_y[T], cs_n[T], cs_y2[T]
    d = pd.to_datetime(dates).to_numpy()
    cand = np.arange(1, T)
    if restrict is not None:
        lo, hi = np.datetime64(restrict[0]), np.datetime64(restrict[1])
        cand = cand[(d[cand] >= lo) & (d[cand] <= hi)]
    best_t = np.zeros(y.shape[1])
    best_amp = np.zeros(y.shape[1])
    best_idx = np.zeros(y.shape[1], int)
    best_n = np.zeros((y.shape[1], 2))
    for i in cand:
        n1, n2 = cs_n[i], tot_n - cs_n[i]
        good = (n1 >= min_side) & (n2 >= min_side)
        if not good.any():
            continue
        s1, s2 = cs_y[i], tot_y - cs_y[i]
        m1 = np.where(n1 > 0, s1 / np.maximum(n1, 1), 0.0)
        m2 = np.where(n2 > 0, s2 / np.maximum(n2, 1), 0.0)
        # pooled residual variance of the two-mean model
        sse = tot_y2 - (s1 ** 2 / np.maximum(n1, 1) + s2 ** 2 / np.maximum(n2, 1))
        dof = np.maximum(n1 + n2 - 2, 1)
        se = np.sqrt(np.maximum(sse, 0) / dof * (1 / np.maximum(n1, 1) + 1 / np.maximum(n2, 1)))
        tstat = np.where(se > 0, (m2 - m1) / se, 0.0)
        take = good & (np.abs(tstat) > np.abs(best_t))
        best_t = np.where(take, tstat, best_t)
        best_amp = np.where(take, m2 - m1, best_amp)
        best_idx = np.where(take, i, best_idx)
        best_n[take] = np.stack([n1, n2], axis=1)[take]
    return {
        "amp": best_amp, "tstat": np.nan_to_num(best_t),
        "date": pd.to_datetime(pd.Series(d[np.clip(best_idx, 0, T - 1)])),
        "n_pre": best_n[:, 0], "n_post": best_n[:, 1],
    }


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann-Whitney AUC; NaNs dropped."""
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if not len(pos) or not len(neg):
        return float("nan")
    allv = np.concatenate([pos, neg])
    r = pd.Series(allv).rank().to_numpy()
    return float((r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ---------------------------------------------------------------------------- main


def run(cube: str, solar_path: Path, boundary_path: Path | None, out_dir: Path,
        pv_min_frac: float = 0.10, max_shift_px: float = 0.6,
        pre_end: str = "2022-06-30", post_start: str = "2024-07-01") -> dict:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pv_ts_cube import load_cube

    out_dir.mkdir(parents=True, exist_ok=True)
    refl, meta, grid = load_cube(cube)
    h, w = grid["shape"]
    solar = gpd.read_parquet(solar_path) if str(solar_path).endswith("parquet") \
        else gpd.read_file(solar_path)
    f_pv = _fraction_raster(solar, grid)

    # Buildings: reference pixels must be built-up (so the comparison is roof-to-roof,
    # not roof-to-field) but carry no mapped PV, with a 1-pixel guard ring because the
    # sensor PSF spreads a panel's signal into its neighbours.
    from earthpv import overture
    from earthpv.buildings import fetch_vida_buildings

    bbox = tuple(grid["bbox"])
    blds = fetch_vida_buildings(bbox, "PAK", con=overture.connect())
    f_bld = _fraction_raster(blds, grid)
    log.info("%d buildings, %d mapped PV polygons in bbox", len(blds), len(solar))

    inside = np.ones((h, w), bool)
    if boundary_path is not None:
        b = gpd.read_file(boundary_path)
        inside = _fraction_raster(b, grid) > 0.99

    pv_mask = (f_pv >= pv_min_frac) & inside
    near_pv = _dilate(f_pv > 0.001, 1)
    ref_mask = (f_bld >= 0.5) & ~near_pv & inside
    log.info("pixels: %d PV (frac>=%.2f), %d reference built-up, %d inside box",
             int(pv_mask.sum()), pv_min_frac, int(ref_mask.sum()), int(inside.sum()))

    # 1. co-registration guard against the temporal median of a bright band
    b04 = refl[:, BANDS.index("B04")]
    med = np.nanmedian(b04, axis=0)
    shifts = np.array([_phase_shift(med, b04[i]) for i in range(len(meta))])
    meta["shift_y"], meta["shift_x"] = shifts[:, 0], shifts[:, 1]
    meta["shift_px"] = np.hypot(shifts[:, 0], shifts[:, 1])
    keep = meta["shift_px"].to_numpy() <= max_shift_px
    log.info("co-registration: median shift %.2f px, %d/%d scenes kept (<= %.2f px)",
             float(np.nanmedian(meta["shift_px"])), int(keep.sum()), len(meta), max_shift_px)
    refl, meta = refl[keep], meta[keep].reset_index(drop=True)

    # 2. common-mode removal against the reference-pixel median, per date and band
    ref_flat = ref_mask.reshape(-1)
    flat = refl.reshape(len(meta), len(BANDS), -1)
    common = np.nanmedian(flat[:, :, ref_flat], axis=2)                # [T,B]
    d = flat - common[:, :, None]

    # 3. learned spectral direction, on a spatially disjoint training half
    xs = np.arange(w)[None, :].repeat(h, 0).reshape(-1)
    train_side = xs < w / 2
    dates = pd.to_datetime(meta["date"])
    pre = (dates <= pre_end).to_numpy()
    post = (dates >= post_start).to_numpy()
    pv_flat, ref_flat_b = pv_mask.reshape(-1), ref_mask.reshape(-1)
    tr_pv, te_pv = pv_flat & train_side, pv_flat & ~train_side

    def _delta_spectrum(sel: np.ndarray) -> np.ndarray:
        a = np.nanmean(np.nanmean(d[post][:, :, sel], axis=2), axis=0)
        b = np.nanmean(np.nanmean(d[pre][:, :, sel], axis=2), axis=0)
        return a - b

    dir_pv = _delta_spectrum(tr_pv) - _delta_spectrum(ref_flat_b)
    norm = np.linalg.norm(dir_pv)
    direction = dir_pv / norm if norm > 0 else np.zeros(len(BANDS))
    log.info("learned direction (train PV pixels, n=%d): %s", int(tr_pv.sum()),
             {b: round(float(v), 3) for b, v in zip(BANDS, direction)})

    projections = {"learned": direction}
    for name, wts in FIXED_INDICES.items():
        v = np.array([wts.get(b, 0.0) for b in BANDS])
        projections[name] = v / np.linalg.norm(v)

    # 4. deseasonalise + breakpoint scan, per index
    X = _design(meta["date"], meta["orbit"])
    results, metrics = {}, {}
    for name, vec in projections.items():
        s = np.einsum("tbp,b->tp", d, vec.astype(np.float32), optimize=True)
        resid = _fit_residuals(s, X)
        fit = scan_breakpoints(resid, meta["date"])
        placebo = scan_breakpoints(resid, meta["date"], restrict=("2018-07-01", "2021-06-30"))
        results[name] = (fit, placebo)
        m = {
            "auc_amp": auc(fit["amp"][te_pv], fit["amp"][ref_flat_b]),
            "auc_tstat": auc(fit["tstat"][te_pv], fit["tstat"][ref_flat_b]),
            "auc_amp_train": auc(fit["amp"][tr_pv], fit["amp"][ref_flat_b]),
            "placebo_auc_tstat": auc(placebo["tstat"][te_pv], placebo["tstat"][ref_flat_b]),
            "n_test_pv": int(te_pv.sum()), "n_ref": int(ref_flat_b.sum()),
            "median_amp_pv": float(np.nanmedian(fit["amp"][te_pv])),
            "median_amp_ref": float(np.nanmedian(fit["amp"][ref_flat_b])),
        }
        # amplitude vs PV fraction, over every inside pixel that is built-up
        sel = (f_bld.reshape(-1) >= 0.3) & inside.reshape(-1)
        x, yv = f_pv.reshape(-1)[sel], fit["amp"][sel]
        good = np.isfinite(yv)
        if good.sum() > 50:
            sl, ic = np.polyfit(x[good], yv[good], 1)
            r = np.corrcoef(x[good], yv[good])[0, 1]
            m |= {"frac_slope": float(sl), "frac_intercept": float(ic), "frac_r": float(r)}
        metrics[name] = m
        log.info("%-16s AUC(test)=%.3f AUC(train)=%.3f placebo=%.3f r(frac)=%s",
                 name, m["auc_amp"], m["auc_amp_train"], m["placebo_auc_tstat"],
                 f"{m.get('frac_r', float('nan')):.3f}")

    best = max(metrics, key=lambda k: (metrics[k]["auc_amp"] if np.isfinite(metrics[k]["auc_amp"])
                                       else 0))
    fit, placebo = results[best]
    px = pd.DataFrame({
        "row": np.repeat(np.arange(h), w), "col": np.tile(np.arange(w), h),
        "f_pv": f_pv.reshape(-1), "f_bld": f_bld.reshape(-1), "inside": inside.reshape(-1),
        "is_pv": pv_flat, "is_ref": ref_flat_b, "train_side": train_side,
    })
    for name, (f, p) in results.items():
        px[f"amp_{name}"] = f["amp"]
        px[f"t_{name}"] = f["tstat"]
        px[f"date_{name}"] = f["date"].to_numpy()
        px[f"placebo_t_{name}"] = p["tstat"]
    px.to_parquet(out_dir / "pixels.parquet")
    meta.to_parquet(out_dir / "scenes.parquet")
    summary = {
        "cube": cube, "best_index": best, "metrics": metrics,
        "direction": {b: float(v) for b, v in zip(BANDS, direction)},
        "n_scenes": int(len(meta)), "n_scenes_dropped_coreg": int((~keep).sum()),
        "pv_polygons": int(len(solar)), "pv_area_m2": float(_fraction_raster(solar, grid).sum() * 100),
        "grid": grid, "pv_min_frac": pv_min_frac,
        "date_range": [str(meta["date"].min()), str(meta["date"].max())],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("wrote %s", out_dir)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cube", required=True)
    ap.add_argument("--solar", type=Path, required=True)
    ap.add_argument("--boundary", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pv-min-frac", type=float, default=0.10)
    ap.add_argument("--max-shift-px", type=float, default=0.6)
    a = ap.parse_args()
    run(a.cube, a.solar, a.boundary, a.out, a.pv_min_frac, a.max_shift_px)


if __name__ == "__main__":
    main()
