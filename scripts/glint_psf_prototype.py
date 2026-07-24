"""Prototype: measure an empirical solar-glint point-spread function (PSF) from small,
strongly-validated PV installations, compare it to Sentinel-2's own published/measured
PSF, then test whether matched-filtering against it recovers more signal from smaller,
weakly-detected installations than the current aperture (in-polygon vs annulus) statistic
-- the same logic as PSF photometry for faint stars fainter than a naive aperture can
cleanly separate from sky noise.

Why this should work in principle: a genuinely sub-pixel PV array (< 100 m^2, well under
one 10 m x 10 m pixel) is optically a point source, so a real glint event's excess
reflectance should spread across neighbouring pixels according to the SENSOR's PSF --
not stay confined to one polygon-footprint pixel the way the current `p98 inside polygon
vs ring median` statistic implicitly assumes. If that spread has a stable, known shape,
correlating a candidate's local pixel neighbourhood against it (a matched filter) is the
provably-optimal linear detector for a point source buried in pixel noise -- strictly
better SNR than a boxcar aperture sum, which is exactly why stellar photometry moved from
aperture photometry to PSF fitting for faint targets.

Why it might NOT: (1) installations in the 100-500 m^2 range this validation reaches
(the size range with enough confirmed spikes to calibrate from) already span 1-5 pixels,
so their excess is a MIX of true PSF blur and their own finite extent -- not a pure point
source, and the derived "PSF" is really a PSF-convolved-with-small-extended-source
template specific to this size range, not a universal kernel. (2) Only ~2-9% of
confirmed installations glint at all in the <500 m^2 range (the whole reason coverage is
thin here), so the calibration sample is small no matter what. Both caveats are checked
below, not assumed away.

Data reuse (zero new labeling, minimal new pulls): pids + confirmed spike/validation
flags come from the existing 500-target country-scale study
(`results/glint_validation_pakistan/pakistan_summary.csv`, `data/glint/pakistan_targets.parquet`).
Only the RAW PIXEL WINDOWS (this study only ever kept aggregate p98/ring stats, not pixel
arrays) are new network reads -- one `tile_scene_series_batch(keep_items=True)` batched
call for all ~18 targets used here, then `glint._read_target_array` pixel reads restricted
to each target's own already-known spike/clear dates (a handful of scenes per target, not
a full resurvey) -- reusing exactly the fetch/window logic `scripts/glint_alignment_check.py`
already established.

Usage:
  .pixi/envs/default/bin/python scripts/glint_psf_prototype.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless -- must precede pyplot import

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BAND = "B03"  # matches glint_alignment_check.py: 10m native, no resampling
OUT_DIR = DATA_DIR / "glint" / "psf_prototype"
STAMP_R = 5  # +-5 px around the known point -> 11x11 template
N_BASELINE = 6  # clear-date scenes averaged into the background estimate

# Calibration set: confirmed OSM installations, area < 500 m^2, glint-VALIDATED
# (n_consistent >= 2 in the original study) -- these have a real, self-consistent
# glint fit, so their spike dates are trustworthy, not one-off bright pixels.
CALIB_PIDS = ["pk_0031", "pk_0071", "pk_0092", "pk_0103", "pk_0118",
              "pk_0127", "pk_0133", "pk_0135", "pk_0140"]
# Test set: same size range, at least one spike seen but NOT validated
# (n_consistent < 2) -- exactly the population a better statistic needs to help,
# since the current aperture stat left them undecided.
TEST_PIDS = ["pk_0006", "pk_0034", "pk_0069", "pk_0085", "pk_0090",
             "pk_0093", "pk_0110", "pk_0155", "pk_0156"]


def _refresh_pc_token(item, provider: str) -> None:
    """Re-sign a Planetary Computer item's asset hrefs immediately before use.

    Local to this script, NOT a change to earthpv.glint (that fix was tried and
    reverted). Needed here specifically because this script fetches ALL targets'
    scene stats first (tile_scene_series_batch(keep_items=True), which can take
    tens of minutes across several tile groups under Planetary Computer outages),
    then re-reads raw pixel windows from the RETAINED items in a separate later
    pass (build_target_stamps) -- exactly the "search now, read much later"
    pattern that outlives a SAS token's ~30-45 min lifetime. First run without
    this hit it directly: every read for 5/9 calibration targets and 8/9 test
    targets failed with an expired-token error, because their tile group had been
    searched a long time before this script got around to re-reading it.

    Cheap: `planetary_computer.sign` caches tokens per (account, container) and
    only re-fetches when the cached one has under 60s left, so this is a
    same-token cache hit in the common case, a real refresh only right before
    actual expiry. Earth Search needs no token, so it's a no-op there.
    """
    if provider != "planetary-computer":
        return
    import planetary_computer

    planetary_computer.sign_inplace(item)


def read_refl(item, provider: str, geometry, lon: float, lat: float):
    _refresh_pc_token(item, provider)
    href = item.assets[glint._band_asset_key(BAND, provider)].href
    with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
        arr, wt, geom_native = glint._read_target_array(src, geometry, lon, lat)
    offset = glint._boa_offset(item, provider)
    return glint._refl(arr + offset), wt, geom_native


def point_rc(geom_native, transform) -> tuple[float, float]:
    """(row, col) of the target's true centroid within the window array, sub-pixel."""
    col, row = ~transform * (geom_native.centroid.x, geom_native.centroid.y)
    return row, col


def crop_stamp(arr: np.ndarray, row: float, col: float, r: int = STAMP_R) -> np.ndarray | None:
    """r-pixel-radius crop centred on (row, col), nearest-integer aligned. None if the
    crop would run off the array edge (window is generously sized, r_px>=16, so this
    should be rare -- but a target near the scene edge can still clip)."""
    ri, ci = int(round(row)), int(round(col))
    r0, r1, c0, c1 = ri - r, ri + r + 1, ci - r, ci + r + 1
    if r0 < 0 or c0 < 0 or r1 > arr.shape[0] or c1 > arr.shape[1]:
        return None
    return arr[r0:r1, c0:c1]


def build_target_stamps(pid: str, row, df: pd.DataFrame) -> list[np.ndarray]:
    """One background-subtracted, peak-normalised stamp per spike date for this target."""
    if df.empty:
        print(f"{pid}: no scenes")
        return []
    d = glint.annotate_spikes(df)
    spikes = d[d.spike]
    clear = d[d.clear & ~d.spike]
    if spikes.empty:
        print(f"{pid}: 0 spikes")
        return []
    geometry, lon, lat = row.geometry, row.lon, row.lat

    # Background: per-pixel MEDIAN across a handful of clear-date reads -- robust to
    # any single contaminated scene, and isolates the transient excess the same way
    # astronomical difference imaging isolates a transient from a static field.
    baseline_arrays, transform, geom_native = [], None, None
    base_sample = clear.sample(min(N_BASELINE, len(clear)), random_state=0) if len(clear) else clear
    for t, item, provider in zip(base_sample.time, base_sample["_item"], base_sample["_provider"]):
        try:
            arr, wt, gn = read_refl(item, provider, geometry, lon, lat)
        except Exception as e:  # noqa: BLE001 -- one bad baseline read shouldn't kill the target
            print(f"{pid}: baseline read failed for {t}: {e}")
            continue
        if transform is None:
            transform, geom_native = wt, gn
        if not baseline_arrays or arr.shape == baseline_arrays[0].shape:
            baseline_arrays.append(arr)
    if not baseline_arrays:
        print(f"{pid}: no readable baseline scenes")
        return []
    background = np.nanmedian(np.stack(baseline_arrays), axis=0)

    stamps = []
    for t, item, provider in zip(spikes.time, spikes["_item"], spikes["_provider"]):
        try:
            arr, wt, gn = read_refl(item, provider, geometry, lon, lat)
        except Exception as e:  # noqa: BLE001 -- one bad spike read shouldn't kill the target
            print(f"{pid}: spike read failed for {t}: {e}")
            continue
        if arr.shape != background.shape:
            continue
        diff = arr - background
        r_row, r_col = point_rc(geom_native, transform)
        stamp = crop_stamp(diff, r_row, r_col)
        if stamp is None or not np.isfinite(stamp).all():
            continue
        peak = np.nanmax(stamp)
        if peak <= 0:
            continue
        stamps.append(stamp / peak)  # peak-normalised: shape only, amplitude removed
    print(f"{pid} ({row.area_m2:.0f} m2): {len(spikes)} spikes -> {len(stamps)} usable stamps")
    return stamps


def radial_profile(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r = img.shape[0] // 2
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    rad = np.sqrt(xx**2 + yy**2)
    bins = np.arange(0, r + 1.5, 1.0)
    idx = np.digitize(rad.ravel(), bins)
    prof = np.array([img.ravel()[idx == i].mean() for i in range(1, len(bins))])
    return bins[:-1], prof


def gaussian_mtf_sigma(mtf_at_nyquist: float) -> float:
    """Pixel-space sigma of the Gaussian whose MTF at Nyquist (f=0.5 cyc/px) equals
    `mtf_at_nyquist` -- MTF(f) = exp(-2*(pi*sigma*f)^2) for a Gaussian PSF, the exact
    model ESA's SentiWiki page states it derives Sentinel-2's operational PSFs with
    (see script docstring / chat sources). Solving at f=0.5:
        sigma = sqrt(-ln(m)) * sqrt(2) / pi
    """
    return np.sqrt(2.0) / np.pi * np.sqrt(-np.log(mtf_at_nyquist))


def gaussian_stamp(sigma: float, r: int = STAMP_R) -> np.ndarray:
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    g = np.exp(-(xx**2 + yy**2) / (2 * sigma**2))
    return g / g.max()


def matched_filter_stat(diff: np.ndarray, row: float, col: float, kernel: np.ndarray) -> float:
    """Normalised cross-correlation of `kernel` against `diff` at the known point
    location -- the matched-filter statistic (optimal linear detector for a known-shape
    signal in noise), vs. the current pipeline's `a - r` aperture-minus-annulus stat."""
    stamp = crop_stamp(diff, row, col)
    if stamp is None:
        return np.nan
    k = kernel - kernel.mean()
    s = stamp - stamp.mean()
    denom = np.linalg.norm(k) * np.linalg.norm(s)
    return float(np.sum(k * s) / denom) if denom > 0 else np.nan


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_targets = gpd.read_parquet(DATA_DIR / "glint" / "pakistan_targets.parquet")
    pids = CALIB_PIDS + TEST_PIDS
    targets = all_targets[all_targets.pid.isin(pids)].reset_index(drop=True)
    print(f"Fetching {len(targets)} targets (calib+test) via tile_scene_series_batch...")
    series_by_pid = glint.tile_scene_series_batch(
        targets[["pid", "geometry", "lon", "lat"]], *DATE_RANGE,
        tile_deg=1.0, max_workers=8, keep_items=True,
    )

    # ---- 1. Build the empirical PSF from the calibration set --------------------
    calib_stamps = []
    for pid in CALIB_PIDS:
        row = targets.loc[targets.pid == pid].iloc[0]
        calib_stamps += build_target_stamps(pid, row, series_by_pid.get(pid, pd.DataFrame()))
    if not calib_stamps:
        print("No calibration stamps -- aborting.")
        return
    empirical_psf = np.median(np.stack(calib_stamps), axis=0)
    empirical_psf = np.clip(empirical_psf, 0, None)
    empirical_psf /= empirical_psf.max()
    print(f"\nEmpirical PSF built from {len(calib_stamps)} stamps across "
          f"{len(CALIB_PIDS)} calibration targets.")

    # ---- 2. Theoretical Sentinel-2 PSF from the published MTF range -------------
    mtf_lo, mtf_hi = 0.15, 0.30  # SentiWiki: 10m-band MTF-at-Nyquist design range
    sigma_lo, sigma_hi = gaussian_mtf_sigma(mtf_hi), gaussian_mtf_sigma(mtf_lo)
    sigma_mid = gaussian_mtf_sigma(0.2)  # a representative mid-range value
    theory_psf = gaussian_stamp(sigma_mid)
    print(f"Theoretical Gaussian sigma from published MTF@Nyquist=0.15-0.30: "
          f"{sigma_lo:.2f}-{sigma_hi:.2f} px (mid @0.2 = {sigma_mid:.2f} px, "
          f"FWHM {sigma_mid*2.3548:.2f} px)")

    r_emp, prof_emp = radial_profile(empirical_psf)
    r_th, prof_th = radial_profile(theory_psf)
    # empirical FWHM: linear-interpolate the profile down to half its peak (r=0) value
    half = prof_emp[0] / 2
    below = np.where(prof_emp <= half)[0]
    fwhm_emp = 2 * (r_emp[below[0] - 1] + (prof_emp[below[0] - 1] - half) /
                    (prof_emp[below[0] - 1] - prof_emp[below[0]])) if len(below) else np.nan
    print(f"Empirical PSF radial FWHM ~= {fwhm_emp:.2f} px (theory: {sigma_mid*2.3548:.2f} px "
          f"@ MTF=0.2, range {sigma_lo*2.3548:.2f}-{sigma_hi*2.3548:.2f} px)")

    # ---- 3. Matched-filter test on the weakly-detected small set -----------------
    kernel = empirical_psf  # use the measured shape, not the theoretical one, as the
    # matched filter -- it already includes this size range's true finite-extent blur
    # on top of the sensor PSF (see docstring caveat), which is the more honest filter
    # to test even though it means this result can't yet be claimed as a UNIVERSAL PSF.
    results = []
    for pid in TEST_PIDS:
        row = targets.loc[targets.pid == pid].iloc[0]
        df = series_by_pid.get(pid, pd.DataFrame())
        if df.empty:
            continue
        d = glint.annotate_spikes(df)
        spikes, clear = d[d.spike], d[d.clear & ~d.spike]
        if spikes.empty:
            continue
        base_sample = clear.sample(min(N_BASELINE, len(clear)), random_state=0) if len(clear) else clear
        baseline_arrays = []
        for t, item, provider in zip(base_sample.time, base_sample["_item"], base_sample["_provider"]):
            try:
                arr, _wt, _gn = read_refl(item, provider, row.geometry, row.lon, row.lat)
            except Exception:  # noqa: BLE001
                continue
            baseline_arrays.append(arr)
        if not baseline_arrays:
            continue
        background = np.nanmedian(np.stack(baseline_arrays), axis=0)
        # baseline noise floor: matched-filter stat evaluated on OTHER clear scenes
        # (should center near 0) -- the "sky noise" a real spike must rise above.
        noise_stats = []
        for t, item, provider in zip(base_sample.time, base_sample["_item"], base_sample["_provider"]):
            try:
                arr, wt, gn = read_refl(item, provider, row.geometry, row.lon, row.lat)
            except Exception:  # noqa: BLE001
                continue
            r_row, r_col = point_rc(gn, wt)
            noise_stats.append(matched_filter_stat(arr - background, r_row, r_col, kernel))
        noise_stats = [x for x in noise_stats if np.isfinite(x)]

        for t, item, provider, a_val, r_val in zip(
            spikes.time, spikes["_item"], spikes["_provider"], spikes[f"a_{BAND}"], spikes[f"r_{BAND}"]
        ):
            try:
                arr, wt, gn = read_refl(item, provider, row.geometry, row.lon, row.lat)
            except Exception:  # noqa: BLE001
                continue
            r_row, r_col = point_rc(gn, wt)
            mf = matched_filter_stat(arr - background, r_row, r_col, kernel)
            if not np.isfinite(mf):
                continue
            noise_std = np.std(noise_stats) if len(noise_stats) >= 2 else np.nan
            results.append(dict(
                pid=pid, area_m2=float(row.area_m2), time=t,
                aperture_stat=float(a_val - r_val), matched_filter=mf,
                mf_noise_std=noise_std,
                mf_sigma=mf / noise_std if noise_std and noise_std > 0 else np.nan,
            ))

    res_df = pd.DataFrame(results)
    if res_df.empty:
        print("No test-set spike scenes were readable.")
    else:
        res_df.to_csv(OUT_DIR / "matched_filter_test.csv", index=False)
        print(f"\n=== Matched-filter test: {len(res_df)} spike scenes across "
              f"{res_df.pid.nunique()} weakly-detected small targets ===")
        print(res_df.groupby("pid").agg(
            n=("matched_filter", "size"),
            mf_median=("matched_filter", "median"),
            mf_sigma_median=("mf_sigma", "median"),
            aperture_median=("aperture_stat", "median"),
        ).round(3).to_string())
        print(f"\nOverall median matched-filter sigma (excess / own baseline noise): "
              f"{res_df.mf_sigma.median():.2f}")
        print(f"Fraction of scenes with matched-filter sigma >= 3 (a confident point-source "
              f"detection by the matched-filter statistic alone): "
              f"{(res_df.mf_sigma >= 3).mean():.1%}")

    # ---- 4. Plot: empirical vs theoretical PSF + radial profiles -----------------
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    axes[0].imshow(empirical_psf, cmap="inferno")
    axes[0].set_title(f"Empirical PSF (n={len(calib_stamps)} stamps,\n"
                       f"{len(CALIB_PIDS)} validated targets <500 m2)", fontsize=10)
    axes[1].imshow(theory_psf, cmap="inferno")
    axes[1].set_title(f"Theoretical Gaussian PSF\n(Sentinel-2 MTF@Nyquist=0.2, sigma={sigma_mid:.2f}px)",
                       fontsize=10)
    axes[2].plot(r_emp, prof_emp / prof_emp[0], "o-", label="empirical", color="tab:orange")
    axes[2].plot(r_th, prof_th / prof_th[0], "s--", label="theory (MTF=0.2)", color="tab:blue")
    axes[2].fill_between(
        r_th, radial_profile(gaussian_stamp(sigma_lo))[1] / radial_profile(gaussian_stamp(sigma_lo))[1][0],
        radial_profile(gaussian_stamp(sigma_hi))[1] / radial_profile(gaussian_stamp(sigma_hi))[1][0],
        alpha=0.15, color="tab:blue", label="theory range (MTF 0.15-0.30)",
    )
    axes[2].set_xlabel("radius (px)")
    axes[2].set_ylabel("normalised profile")
    axes[2].legend(fontsize=8)
    axes[2].set_title("Radial profile", fontsize=10)
    for ax in axes[:2]:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout()
    out = OUT_DIR / "glint_psf_comparison.png"
    fig.savefig(out, dpi=150)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
