"""Does guided fusion beat naive resampling for the native-20 m bands (SR option 1)?

The 10-band stack (config.LOCAL_BANDS) mixes native-10 m bands (B02,B03,B04,B08) with
native-20 m bands (B05,B06,B07,B8A,B11,B12) that arrive at the 10 m grid pre-resampled
(naive bilinear/nearest at the compose stage). SWIR (B11/B12) is among the strongest
PV/soil/roof discriminators, so a guided pansharpening-style fusion — using the real
10 m bands as a spatial-detail donor — could sharpen it for free (no new imagery, no
retraining input format change, just a preprocessing step compose already has all the
bands for).

Two measurements, both offline on existing chip tifs (data/chips/<aoi>/{images,masks}):

1. **Wald-protocol fidelity**: B08 is a *native* 10 m band, so it doubles as ground
   truth for a controlled test. Simulate "B08 as if it were 20 m" (block-mean downsample
   + bilinear upsample back to the 10 m grid — the same degradation a real 20 m band
   would show), then reconstruct it with SFIM fusion (Liu 2000: fused = naive_upsampled
   * guide / lowpass(guide), using B04 as the detail donor) and compare RMSE/SSIM against
   the naive upsample, against the REAL B08. This validates the fusion algorithm itself
   without touching a real 20 m band.
2. **Practical separability**: apply the identical fusion to the real B11 (already
   arrives naive-resampled in the chip tif) and check whether it increases the
   PV-vs-background pixel separation (Cohen's d) using each chip's own label mask —
   the thing that would actually matter for detection.

No new imagery, no retraining: this is a fast, offline, resumable-free single pass over
existing chip tifs. A negative result here means the compose stage's naive resampling
is already adequate and a fusion step isn't worth adding; a positive result is the case
for landing it as a compose/config option.

Usage:
  .pixi/envs/default/bin/python scripts/sr_band_fusion_experiment.py --aoi germany --n 60
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import uniform_filter, zoom

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.config import LOCAL_BANDS  # noqa: E402

log = logging.getLogger("sr_band_fusion")

GT_BAND = "B08"          # native 10 m, held out as ground truth for the Wald test
GUIDE_BAND = "B04"       # native 10 m, the fusion detail donor
TARGET_20M_BAND = "B11"  # real native 20 m band, tested for practical separability gain
EPS = 1e-3


def _downup(a: np.ndarray, factor: int = 2) -> tuple[np.ndarray, tuple[int, int]]:
    """Block-mean downsample by `factor` then bilinear upsample back — simulates the
    resolution loss (not just the resampling) a native-20 m band actually has."""
    h, w = a.shape
    h2, w2 = h - h % factor, w - w % factor
    a = a[:h2, :w2].astype("float32")
    down = a.reshape(h2 // factor, factor, w2 // factor, factor).mean(axis=(1, 3))
    up = zoom(down, factor, order=1)[:h2, :w2]
    if up.shape != (h2, w2):
        up = np.pad(up, [(0, h2 - up.shape[0]), (0, w2 - up.shape[1])], mode="edge")
    return up, (h2, w2)


def sfim_fuse(naive_upsampled: np.ndarray, guide: np.ndarray, factor: int = 2) -> np.ndarray:
    """SFIM (Liu 2000): inject the guide's high-frequency detail, normalized by its own
    matching-footprint lowpass, into the coarser band. `guide` must already be cropped
    to `naive_upsampled`'s shape."""
    guide_low, _ = _downup(guide, factor)
    guide_low = guide_low[: naive_upsampled.shape[0], : naive_upsampled.shape[1]]
    return naive_upsampled * (guide[: naive_upsampled.shape[0], : naive_upsampled.shape[1]]
                               / np.clip(guide_low, EPS, None))


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a.astype("float64") - b.astype("float64")) ** 2)))


def _ssim(a: np.ndarray, b: np.ndarray, win: int = 7) -> float:
    """Single-scale SSIM (Wang et al. 2004); dynamic range taken from the pair itself,
    which is fine for a *relative* naive-vs-fused comparison on the same chip."""
    a, b = a.astype("float64"), b.astype("float64")
    dyn = max(a.max(), b.max(), 1.0)
    c1, c2 = (0.01 * dyn) ** 2, (0.03 * dyn) ** 2
    mu_a, mu_b = uniform_filter(a, win), uniform_filter(b, win)
    var_a = uniform_filter(a * a, win) - mu_a**2
    var_b = uniform_filter(b * b, win) - mu_b**2
    cov = uniform_filter(a * b, win) - mu_a * mu_b
    ssim_map = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / (
        (mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)
    )
    return float(np.clip(ssim_map, -1, 1).mean())


def _cohens_d(x: np.ndarray, y: np.ndarray) -> float:
    nx, ny = len(x), len(y)
    pooled = np.sqrt(((nx - 1) * x.var(ddof=1) + (ny - 1) * y.var(ddof=1)) / (nx + ny - 2))
    return float((x.mean() - y.mean()) / pooled) if pooled > 0 else 0.0


def run(index_path: Path, n: int, seed: int) -> pd.DataFrame:
    idx = pd.read_parquet(index_path)
    sample = idx.sample(min(n, len(idx)), random_state=seed)
    band_ix = {b: i for i, b in enumerate(LOCAL_BANDS)}
    rows = []
    for r in sample.itertuples():
        try:
            with rasterio.open(r.image) as src:
                arr = src.read().astype("float32")
            with rasterio.open(r.mask) as src:
                mask = src.read(1)
        except rasterio.errors.RasterioIOError as e:
            log.warning("skip %s: %s", r.chip_id, e)
            continue

        gt = arr[band_ix[GT_BAND]]
        guide = arr[band_ix[GUIDE_BAND]]
        target20 = arr[band_ix[TARGET_20M_BAND]]

        # 1. Wald-protocol fidelity on the held-out 10 m band.
        naive_up, shp = _downup(gt, 2)
        gt_c = gt[: shp[0], : shp[1]]
        fused = sfim_fuse(naive_up, guide, 2)
        rmse_naive, rmse_fused = _rmse(naive_up, gt_c), _rmse(fused, gt_c)
        ssim_naive, ssim_fused = _ssim(naive_up, gt_c), _ssim(fused, gt_c)

        # 2. Practical separability on the real 20 m band (no ground truth available).
        mask_c = mask[: shp[0], : shp[1]]
        pv, bg = mask_c == 1, mask_c == 0
        target_c = target20[: shp[0], : shp[1]]
        fused20 = sfim_fuse(target_c, guide, 2)
        sep_naive = sep_fused = np.nan
        if pv.sum() >= 5 and bg.sum() >= 20:
            sep_naive = _cohens_d(target_c[pv], target_c[bg])
            sep_fused = _cohens_d(fused20[pv], fused20[bg])

        rows.append({
            "chip_id": r.chip_id, "kind": getattr(r, "kind", None),
            "rmse_naive": rmse_naive, "rmse_fused": rmse_fused,
            "ssim_naive": ssim_naive, "ssim_fused": ssim_fused,
            "sep_naive_d": sep_naive, "sep_fused_d": sep_fused,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="germany")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data/sr_band_fusion_experiment.csv"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    index_path = Path("data/chips") / args.aoi / "index.parquet"
    df = run(index_path, args.n, args.seed)
    df.to_csv(args.out, index=False)

    print(f"\n=== SR option 1: guided 20m-band fusion (SFIM), n={len(df)} chips ===")
    print(f"Wald-protocol fidelity on held-out {GT_BAND} (naive vs SFIM-fused):")
    print(f"  RMSE   naive={df.rmse_naive.mean():.1f}  fused={df.rmse_fused.mean():.1f}  "
          f"({100*(1 - df.rmse_fused.mean()/df.rmse_naive.mean()):+.1f}%)")
    print(f"  SSIM   naive={df.ssim_naive.mean():.3f}  fused={df.ssim_fused.mean():.3f}")
    sep = df.dropna(subset=["sep_naive_d", "sep_fused_d"])
    print(f"\nPV-vs-background separability on real {TARGET_20M_BAND} "
          f"(Cohen's d, {len(sep)}/{len(df)} chips had both classes):")
    print(f"  naive={sep.sep_naive_d.mean():.3f}  fused={sep.sep_fused_d.mean():.3f}")
    verdict = (
        "POSITIVE — fusion improves both fidelity and separability; worth landing as a "
        "compose option."
        if df.rmse_fused.mean() < df.rmse_naive.mean() and sep.sep_fused_d.mean() > sep.sep_naive_d.mean()
        else "NEGATIVE/MIXED — naive resampling is already adequate; not worth the added "
             "compose complexity."
    )
    print(f"\nVerdict: {verdict}")
    print(f"Wrote {args.out}")
