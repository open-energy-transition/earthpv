"""Is there real sub-pixel information across Sentinel-2 revisits (SR option 2)?

Multi-image super-resolution only has something to reconstruct if repeat acquisitions
sample the scene at different sub-pixel phases. Sentinel-2 L2A tiles are orthorectified
onto a fixed UTM grid, so the achievable gain is an open empirical question, not a given
— this script measures it directly rather than assuming a number, network-bound like the
glint pulls (reuses their STAC-search machinery: `earthpv.glint._search_items` /
`_band_asset_key` / `_boa_offset`).

Per test point (~5 building-dense locations, reused from a chip index so they're real
scenes with structure), pull N clear single-date scenes over ~1 year of B08 at native
10 m, then:

1. **Sub-pixel phase diversity** — FFT phase-correlation shift of every scene against a
   reference, with a parabolic sub-pixel refinement. If the fractional part clusters at
   ~0 across pairs, revisits are already phase-locked (no MISR headroom); if it spreads
   across (0,1), there is real sub-pixel sampling diversity to exploit.
2. **Leave-one-out self-consistency** (the decisive, ground-truth-free test): fuse all
   scenes but one via drizzle (each scene splatted onto a 2x grid at its estimated
   sub-pixel offset, then averaged), degrade the fused estimate back to native
   resolution, and compare it against the held-out real scene — versus a plain
   temporal-mean-of-the-rest baseline that uses the same scenes with no sub-pixel
   placement. If drizzle doesn't beat the mean baseline at predicting an independent
   real observation, its extra sharpness is arranging noise, not resolving structure.
3. Laplacian-variance sharpness of the full-stack fusion vs a single-scene bicubic 2x,
   reported descriptively (sharpness alone can't distinguish real detail from noise —
   point 2 is what does that).

Synthetic validation (real Sentinel-2 chip texture as ground truth, known injected
shifts) caught two real sign bugs before any network calls were spent — see
`phase_shift`'s and the LOO alignment's docstrings/comments — and confirmed the fixed
pipeline discriminates correctly: it favors fusion (beats the mean baseline) when real
sub-pixel diversity is injected, and penalizes it (loses badly to the mean baseline) when
all synthetic scenes share the same phase — spline resampling has a real interpolation
cost that only pays for itself when there's real sub-pixel content to recover. That
asymmetry is a feature, not noise: it's exactly the discrimination this test needs on
real data, where whether that content exists is the open question.

Usage:
  .pixi/envs/default/bin/python scripts/sr_multitemporal_experiment.py --aoi germany --n-points 5
"""

from __future__ import annotations

import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
import typer
from scipy.ndimage import zoom

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402

log = logging.getLogger("sr_multitemporal")
app = typer.Typer(pretty_exceptions_show_locals=False)

BAND = "B08"
WIN_PX = 128       # 128x128 @ 10 m = 1.28 km window
MAX_CLOUD = 40
SCENE_THREADS = 4  # modest: shares this machine's PC bandwidth with other running pulls


def _read_window(item, band: str, lon: float, lat: float, provider: str, half: int = WIN_PX // 2):
    href = item.assets[glint._band_asset_key(band, provider)].href
    with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
        xs, ys = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
        row, col = src.index(xs[0], ys[0])
        win = rasterio.windows.Window(col - half, row - half, 2 * half, 2 * half)
        arr = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
    arr[arr == 0] = np.nan
    return arr + glint._boa_offset(item, provider)


def pull_series(lon: float, lat: float, start, end, n: int) -> list[np.ndarray]:
    items = glint._search_items("planetary-computer", lon, lat, start, end, MAX_CLOUD)
    seen, keep = set(), []
    for it in sorted(items, key=lambda i: i.properties.get("eo:cloud_cover", 100)):
        key = it.datetime.strftime("%Y%m%d")
        if key in seen:
            continue
        seen.add(key)
        keep.append(it)
        if len(keep) >= n:
            break
    arrays = []
    with ThreadPoolExecutor(SCENE_THREADS) as ex:
        futs = [ex.submit(_read_window, it, BAND, lon, lat, "planetary-computer") for it in keep]
        for f in as_completed(futs):
            try:
                a = f.result()
                if np.isfinite(a).mean() > 0.9:  # drop scenes with a lot of nodata/cloud mask
                    arrays.append(a)
            except Exception as e:  # noqa: BLE001 — one bad scene shouldn't kill the point
                log.debug("scene read failed: %s", e)
    return arrays


def phase_shift(ref: np.ndarray, img: np.ndarray) -> tuple[float, float]:
    """Sub-pixel (row, col) shift of `img` relative to `ref` via FFT phase correlation
    with a parabolic peak refinement. A 2D Hann window is applied before the FFT —
    real (non-periodic) image content otherwise produces strong edge artifacts in the
    correlation that swamp the true peak (verified against a synthetic known-shift
    test: unwindowed estimates were essentially uncorrelated with the true shift)."""
    r = np.nan_to_num(ref, nan=float(np.nanmean(ref)))
    im = np.nan_to_num(img, nan=float(np.nanmean(img)))
    wy = np.hanning(r.shape[0])
    wx = np.hanning(r.shape[1])
    win = np.outer(wy, wx)
    r, im = (r - r.mean()) * win, (im - im.mean()) * win
    F1, F2 = np.fft.fft2(r), np.fft.fft2(im)
    R = F1 * np.conj(F2)
    R /= np.abs(R) + 1e-9
    corr = np.fft.ifft2(R).real
    h, w = corr.shape
    iy, ix = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(line: np.ndarray, i: int, n: int) -> float:
        y0, y1, y2 = line[(i - 1) % n], line[i], line[(i + 1) % n]
        denom = y0 - 2 * y1 + y2
        return 0.0 if denom == 0 else 0.5 * (y0 - y2) / denom

    sub_y, sub_x = refine(corr[:, ix], iy, h), refine(corr[iy, :], ix, w)
    sy = (iy - h if iy > h // 2 else iy) + sub_y
    sx = (ix - w if ix > w // 2 else ix) + sub_x
    # Cross-power-spectrum convention (F_ref * conj(F_img)) places the correlation
    # peak at -d for img(n)=ref(n-d); verified against scipy.ndimage.shift with known
    # integer shifts (sign was exactly inverted, not an off-by-one or scale bug).
    return float(-sy), float(-sx)


def fuse_subpixel(scenes: list[np.ndarray], shifts: list[tuple[float, float]], factor: int = 2):
    """Resample every scene onto the same HR grid at its own estimated sub-pixel
    offset (spline interpolation), then average.

    An earlier version of this function did nearest-cell "drizzle" splatting, which
    leaves holes wherever no scene's rounded phase lands on a given HR cell (~25-50%
    coverage with only a handful of scenes even given true sub-pixel diversity — the
    4 finer sub-lattices of a 2x grid need scenes landing in all 4 phase quadrants) —
    verified against a synthetic known-shift test where it lost to plain bicubic
    despite correct shifts and real sub-pixel diversity by construction. Per-scene
    spline resampling has no holes and is the standard non-uniform-interpolation MISR
    reconstruction; the same synthetic test now shows it beating bicubic as expected.
    """
    from scipy.ndimage import map_coordinates

    h, w = scenes[0].shape
    H, W = h * factor, w * factor
    yy, xx = np.mgrid[0:H, 0:W].astype("float64")
    acc = np.zeros((H, W))
    for img, (sy, sx) in zip(scenes, shifts):
        ly, lx = yy / factor + sy, xx / factor + sx
        filled_img = np.nan_to_num(img, nan=float(np.nanmean(img)))
        acc += map_coordinates(filled_img, [ly, lx], order=3, mode="reflect")
    return acc / len(scenes)


def _laplacian_var(a: np.ndarray) -> float:
    lap = (
        -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    )
    return float(np.nanvar(lap))


def _degrade(a: np.ndarray, factor: int = 2) -> np.ndarray:
    h, w = a.shape
    h2, w2 = h - h % factor, w - w % factor
    return a[:h2, :w2].reshape(h2 // factor, factor, w2 // factor, factor).mean(axis=(1, 3))


def run_point(lon: float, lat: float, n_scenes: int) -> dict | None:
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    start = end - timedelta(days=365)
    scenes = pull_series(lon, lat, start, end, n_scenes)
    if len(scenes) < 4:
        return None
    ref = scenes[0]
    shifts = [(0.0, 0.0)] + [phase_shift(ref, s) for s in scenes[1:]]
    frac = np.array([abs(sy - round(sy)) for sy, _ in shifts[1:]]
                     + [abs(sx - round(sx)) for _, sx in shifts[1:]])

    # Leave-one-out self-consistency: hold out the last scene.
    held_out, held_shift = scenes[-1], shifts[-1]
    fuse_scenes, fuse_shifts = scenes[:-1], shifts[:-1]
    fused_hr = fuse_subpixel(fuse_scenes, fuse_shifts)
    fused_degraded = _degrade(fused_hr)[: held_out.shape[0], : held_out.shape[1]]
    # naive baseline: same scenes, no sub-pixel placement, just temporal mean.
    mean_baseline = np.nanmean(np.stack(fuse_scenes), axis=0)
    # Align the held-out scene INTO the reference frame for a fair comparison: since
    # held_out(n) = ref_content(n - held_shift) (phase_shift's convention, verified
    # against scipy.ndimage.shift with known synthetic shifts), recovering
    # ref_content requires shifting by -held_shift, not +held_shift — an earlier
    # version of this line had the wrong sign here too (doubles the offset instead
    # of removing it), caught by re-running the same synthetic check end-to-end.
    from scipy.ndimage import shift as ndi_shift

    held_aligned = ndi_shift(
        np.nan_to_num(held_out, nan=np.nanmean(held_out)),
        (-held_shift[0], -held_shift[1]), order=1, mode="reflect",
    )

    def rmse(a, b):
        return float(np.sqrt(np.nanmean((a - b) ** 2)))

    rmse_fused = rmse(fused_degraded, held_aligned)
    rmse_mean = rmse(mean_baseline, held_aligned)

    # Descriptive sharpness (all scenes, full fusion).
    fused_full = fuse_subpixel(scenes, shifts)
    bicubic_single = zoom(np.nan_to_num(ref, nan=np.nanmean(ref)), 2, order=3)

    return {
        "lon": lon, "lat": lat, "n_scenes": len(scenes),
        "frac_shift_mean": float(np.nanmean(frac)), "frac_shift_std": float(np.nanstd(frac)),
        "rmse_fused_loo": rmse_fused, "rmse_mean_baseline_loo": rmse_mean,
        "sharpness_fused": _laplacian_var(fused_full),
        "sharpness_bicubic_single": _laplacian_var(bicubic_single),
    }


@app.command()
def main(
    aoi: str = typer.Option("germany"),
    n_points: int = typer.Option(5),
    n_scenes: int = typer.Option(10),
    seed: int = typer.Option(42),
    out: Path = typer.Option(Path("data/sr_multitemporal_experiment.csv")),
):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    idx = pd.read_parquet(Path("data/chips") / aoi / "index.parquet")
    pos = idx[idx.kind == "positive"] if "kind" in idx.columns else idx
    pts = pos.sample(min(n_points, len(pos)), random_state=seed)

    rows = []
    for i, r in enumerate(pts.itertuples()):
        log.info("[%d/%d] pulling %d scenes near (%.4f, %.4f)", i + 1, len(pts), n_scenes, r.lon, r.lat)
        res = run_point(r.lon, r.lat, n_scenes)
        if res is None:
            log.warning("  too few usable scenes, skipping")
            continue
        rows.append(res)
        log.info("  frac_shift=%.3f rmse_fused=%.1f rmse_mean=%.1f",
                  res["frac_shift_mean"], res["rmse_fused_loo"], res["rmse_mean_baseline_loo"])

    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    print(f"\n=== SR option 2: multi-image super-resolution feasibility, n={len(df)} points ===")
    if df.empty:
        print("No usable points (network/cloud issues) — inconclusive.")
        raise typer.Exit()
    print(f"Sub-pixel phase diversity: mean fractional shift = {df.frac_shift_mean.mean():.3f} "
          f"(std {df.frac_shift_std.mean():.3f}); 0 = phase-locked, 0.25-0.5 = genuine diversity")
    print("Leave-one-out self-consistency RMSE vs a held-out real scene:")
    print(f"  sub-pixel fusion (fuse_subpixel) = {df.rmse_fused_loo.mean():.1f}")
    print(f"  temporal mean (no sub-pixel)     = {df.rmse_mean_baseline_loo.mean():.1f}")
    print(f"Descriptive sharpness (Laplacian variance): fused={df.sharpness_fused.mean():.1f} "
          f"vs bicubic-single={df.sharpness_bicubic_single.mean():.1f}")
    verdict = (
        "POSITIVE — sub-pixel fusion beats the naive mean at predicting a held-out real "
        "scene: there is real sub-pixel information to exploit."
        if df.rmse_fused_loo.mean() < df.rmse_mean_baseline_loo.mean()
        else "NEGATIVE — sub-pixel fusion does not beat plain temporal averaging on "
             "held-out data: the extra sharpness is not resolving real sub-pixel structure."
    )
    print(f"\nVerdict: {verdict}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    app()
