"""Does internal-learning deep single-image SR invent structure (SR option 3)?

Deep single-image SR (SISR) has no second observation to fall back on — it upsamples
from a learned or self-taught prior, which for a detector whose remaining errors are
precision-side (not recall-side) is exactly the wrong failure mode: it can synthesize
panel-row-like regularity that was never there. This script measures that risk directly
rather than asserting it, using ZSSR (Shocher et al. 2018) — a genuine self-supervised
deep SISR method that needs no external pretrained weights or downloads: it trains a
tiny CNN per-image on (downsampled, original) pairs built purely from augmentations of
that one image, then applies the trained net to upsample the image itself. Being purely
internal-prior-driven (no cross-image training set), ZSSR is the sharpest available test
of "what does a deep upsampler invent when it only has this one image's own statistics
to go on" — precisely the mechanism SISR papers point to for hallucination risk.

Runs on `data/chips/<aoi>` positive (real PV) and negative (confirmed no PV) chips —
same source the model itself trains on. For each chip: train ZSSR-lite (a handful of
seconds on GPU), apply it to the chip's own B08 band, and compare against a bicubic 2x
baseline via two metrics measuring "structure invented beyond plain sharpening":
  - extra high-frequency energy: Laplacian-variance of (deep_output - bicubic_baseline)
  - new edge count: thresholded-gradient pixels present in deep_output, absent in
    bicubic_baseline, at the same location

If invented structure is similar in magnitude on negative controls (no real PV to
recover — any invented detail there IS hallucination by definition) and on positive
chips, that supports treating SISR's "sharpening" as prior-driven pattern completion
rather than real recovery, regardless of ground truth; if it is much higher specifically
on positive chips, that would argue the extra detail tracks real content instead.

Usage:
  .pixi/envs/ml/bin/python scripts/sr_hallucination_experiment.py --aoi germany --n 8
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.config import LOCAL_BANDS  # noqa: E402

log = logging.getLogger("sr_hallucination")
BAND = "B08"
N_STEPS = 400
LR = 1e-3
EDGE_THRESH_SIGMA = 2.0  # "new edge" = gradient magnitude beyond this many stds of the bicubic map


class ZSSRNet(nn.Module):
    """~40k-param residual CNN, matching ZSSR's own scale (deliberately tiny — a
    per-image internal-learning method has only one image's own statistics to fit,
    so a bigger net would just memorize noise)."""

    def __init__(self, ch: int = 32):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(1, ch, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(ch, ch, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(ch, ch, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(ch, 1, 3, padding=1),
        )

    def forward(self, x):
        # Bicubic upsample first (ZSSR's own recipe), network learns the residual detail.
        up = F.interpolate(x, scale_factor=2, mode="bicubic", align_corners=False)
        return up + self.body(up)


def _augment(img: np.ndarray, k: int) -> np.ndarray:
    """8 dihedral augmentations (4 rotations x optional flip) — ZSSR's own augmentation
    set, needed because a single image alone has too few pixels to fit even a tiny CNN
    without it."""
    a = np.rot90(img, k % 4)
    return np.fliplr(a) if k >= 4 else a


def train_zssr(img: np.ndarray, device: str, steps: int = N_STEPS, seed: int = 0) -> ZSSRNet:
    rng = np.random.default_rng(seed)
    net = ZSSRNet().to(device)
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    img = img.astype("float32")
    mean, std = img.mean(), img.std() + 1e-6
    norm = (img - mean) / std
    for _ in range(steps):
        k = int(rng.integers(0, 8))
        hr = _augment(norm, k).copy()
        h, w = hr.shape
        h2, w2 = h - h % 2, w - w % 2
        hr = hr[:h2, :w2]
        lr = hr.reshape(h2 // 2, 2, w2 // 2, 2).mean(axis=(1, 3))  # self-degrade, factor 2
        lr_t = torch.from_numpy(lr[None, None]).to(device)
        hr_t = torch.from_numpy(hr[None, None]).to(device)
        pred = net(lr_t)
        loss = F.mse_loss(pred, hr_t)
        opt.zero_grad()
        loss.backward()
        opt.step()
    net.eval()
    return net, mean, std


def apply_zssr(net: ZSSRNet, mean: float, std: float, img: np.ndarray, device: str) -> np.ndarray:
    norm = (img.astype("float32") - mean) / std
    with torch.no_grad():
        out = net(torch.from_numpy(norm[None, None]).to(device)).cpu().numpy()[0, 0]
    return out * std + mean


def _laplacian(a: np.ndarray) -> np.ndarray:
    return -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]


def _gradient_mag(a: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(a)
    return np.sqrt(gy**2 + gx**2)


def hallucination_metrics(deep_out: np.ndarray, bicubic: np.ndarray) -> dict:
    diff = deep_out - bicubic
    extra_hf_energy = float(np.var(_laplacian(diff)))
    grad_bicubic = _gradient_mag(bicubic)
    grad_deep = _gradient_mag(deep_out)
    thresh = grad_bicubic.mean() + EDGE_THRESH_SIGMA * grad_bicubic.std()
    new_edges = int(((grad_deep > thresh) & (grad_bicubic <= thresh)).sum())
    return {"extra_hf_energy": extra_hf_energy, "new_edge_count": new_edges}


def run(index_path: Path, n: int, seed: int, device: str) -> pd.DataFrame:
    idx = pd.read_parquet(index_path)
    band_ix = LOCAL_BANDS.index(BAND)
    # chips.py kinds are positive / near_negative / background (no plain "negative") —
    # "background" (far from any mapped PV) is the true negative control; near_negative
    # (close to a positive, still labeled PV-free) is deliberately excluded here since a
    # model-invented panel there could coincidentally overlap real nearby PV context.
    groups = []
    if "kind" in idx.columns:
        for kind, label in (("positive", "positive"), ("background", "negative")):
            pool = idx[idx.kind == kind]
            if "pv_pixels" in pool.columns:
                pool = pool[pool.pv_pixels > 0] if kind == "positive" else pool[pool.pv_pixels == 0]
            sample = pool.sample(min(n, len(pool)), random_state=seed).copy()
            sample["kind"] = label
            groups.append(sample)
    else:
        groups = [idx.sample(min(2 * n, len(idx)), random_state=seed)]

    rows = []
    for grp in groups:
        for r in grp.itertuples():
            try:
                with rasterio.open(r.image) as src:
                    img = src.read(band_ix + 1).astype("float32")
            except rasterio.errors.RasterioIOError as e:
                log.warning("skip %s: %s", r.chip_id, e)
                continue
            net, mean, std = train_zssr(img, device, seed=seed)
            deep_out = apply_zssr(net, mean, std, img, device)
            bicubic = F.interpolate(
                torch.from_numpy(img[None, None]), scale_factor=2, mode="bicubic", align_corners=False
            ).numpy()[0, 0]
            m = hallucination_metrics(deep_out, bicubic)
            m.update({"chip_id": r.chip_id, "kind": getattr(r, "kind", None)})
            rows.append(m)
            log.info("%s (%s): extra_hf=%.2f new_edges=%d",
                      r.chip_id, m["kind"], m["extra_hf_energy"], m["new_edge_count"])
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="germany")
    ap.add_argument("--n", type=int, default=8, help="chips per group (positive/negative)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("data/sr_hallucination_experiment.csv"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("device=%s", device)
    index_path = Path("data/chips") / args.aoi / "index.parquet"
    df = run(index_path, args.n, args.seed, device)
    df.to_csv(args.out, index=False)

    print(f"\n=== SR option 3: internal-learning deep SISR hallucination risk (ZSSR), "
          f"n={len(df)} chips ===")
    if "kind" in df.columns and df.kind.notna().any():
        summary = df.groupby("kind")[["extra_hf_energy", "new_edge_count"]].mean()
        print(summary.to_string())
        pos = df[df.kind == "positive"]
        neg = df[df.kind == "negative"]
        if len(pos) and len(neg):
            ratio = pos.extra_hf_energy.mean() / max(neg.extra_hf_energy.mean(), 1e-9)
            print(f"\npositive/negative extra-HF-energy ratio: {ratio:.2f} "
                  "(near 1 = invented detail is similar regardless of real PV -> "
                  "hallucination, not recovery; >>1 = extra detail tracks real content)")
            verdict = (
                "CONFIRMED RISK — invented structure on no-PV negative controls is "
                "comparable to positive chips: SISR is pattern-completing, not "
                "recovering real detail. Do not feed this into detection."
                if ratio < 2.0
                else "WEAKER RISK than assumed — invented detail is markedly higher on "
                     "real-PV chips, suggesting some of it tracks genuine content. Still "
                     "would need per-candidate discrimination before trusting it."
            )
            print(f"\nVerdict: {verdict}")
    else:
        print(df[["extra_hf_energy", "new_edge_count"]].mean().to_string())
    print(f"\nWrote {args.out}")
