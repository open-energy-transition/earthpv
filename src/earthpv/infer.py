"""Tiled inference over an AOI using the local Sentinel-2 composites.

For each composite cell, slides a 224 px window across its native UTM grid and
overlap-adds the predictions with a 2D Hann taper into a single seamless probability
raster (uint8, 0-255) per cell. The Hann blending and a patch-size-coprime stride
suppress the window-seam / patch-grid artefacts that a naive per-window write produces.
Building ROI screening happens at the `compose`/postprocess stages, not here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from tqdm import tqdm

from earthpv.config import CHIP_SIZE, MODEL_BANDS, Settings
from earthpv.labels import resolve_aoi
from earthpv.local_source import CompositeIndex

log = logging.getLogger(__name__)


def load_model(checkpoint: Path):
    import torch
    from terratorch.tasks import SemanticSegmentationTask

    task = SemanticSegmentationTask.load_from_checkpoint(checkpoint, map_location="cpu")
    task.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return task.to(device), device


def run_inference(
    aoi: str, checkpoint: Path, out_dir: Path, only_built: bool = True, limit: int = 0
) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import torch

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    # Prefer composites built by the `compose` stage for this AOI (e.g. Punjab, which
    # has no local composites); fall back to the rooftopsenti source_region.
    composed = Path("data/composites") / aoi
    if composed.exists() and any(composed.glob("composites/*/composite_0.tif")):
        comp_idx = CompositeIndex(composed)
    else:
        source_region = cfg.get("source_region")
        if not source_region:
            raise NotImplementedError(f"AOI '{aoi}' has no source_region for local inference.")
        comp_idx = CompositeIndex(Path(settings.raw["local_root"]) / source_region)
    # `only_built` is retained for CLI compatibility; composited cells are already
    # building-populated, and rooftop/ground attribution happens in postprocess.
    log.info("Inference on %s: %d composite cells", aoi, len(comp_idx.index))

    # Two-season stack: model input is [composite_0 bands, composite_1 bands]; every
    # cell must have the contrast layer (built by `compose --index 1`).
    stacked = bool(cfg.get("stack_window"))
    if stacked:
        missing = [p for p in comp_idx.index.path
                   if not (Path(p).parent / "composite_1.tif").exists()]
        if missing:
            raise FileNotFoundError(
                f"{len(missing)} cells missing composite_1.tif (e.g. {missing[:3]}); "
                "run compose --index 1 --window <contrast season> first"
            )
    out_dir = Path(out_dir) / aoi / "prob"
    out_dir.mkdir(parents=True, exist_ok=True)
    task, device = load_model(checkpoint)
    n_bands = len(MODEL_BANDS)
    # Stride deliberately NOT a multiple of the 16 px ViT patch size: this offsets the
    # patch grid between neighbouring windows so patch-edge artefacts decorrelate and
    # average out instead of recurring on a regular lattice.
    stride = 104
    # 2D Hann taper: each window's contribution fades to ~0 at its own edges, so window
    # seams blend smoothly (overlap-add) and border artefacts get near-zero weight.
    hann = np.outer(np.hanning(CHIP_SIZE), np.hanning(CHIP_SIZE)).astype("float32") + 1e-3

    tiles = list(comp_idx.index.path)
    if limit:
        tiles = tiles[:limit]
    windows_run = 0
    for tile_path in tqdm(tiles, desc="cells"):
        tile = Path(tile_path).parent.name
        src1 = rasterio.open(Path(tile_path).parent / "composite_1.tif") if stacked else None
        with rasterio.open(tile_path) as src:
            H, W = src.height, src.width
            transform, crs = src.transform, src.crs
            acc = np.zeros((H, W), dtype="float32")
            wacc = np.zeros((H, W), dtype="float32")
            valid_any = np.zeros((H, W), dtype=bool)
            # Window origins, clamped to the tile and always including the far edge so
            # coverage reaches the borders without reading out of bounds.
            rows = sorted(set(list(range(0, max(H - CHIP_SIZE, 0) + 1, stride)) + [max(H - CHIP_SIZE, 0)]))
            cols = sorted(set(list(range(0, max(W - CHIP_SIZE, 0) + 1, stride)) + [max(W - CHIP_SIZE, 0)]))
            for r in rows:
                for c in cols:
                    win = Window(c, r, CHIP_SIZE, CHIP_SIZE)
                    arr = src.read(window=win, boundless=True, fill_value=0)[:n_bands]
                    h, w = min(CHIP_SIZE, H - r), min(CHIP_SIZE, W - c)
                    if (arr[:, :h, :w] > 0).mean() < 0.2:  # skip mostly-nodata windows
                        continue
                    if src1 is not None:
                        arr = np.concatenate(
                            [arr, src1.read(window=win, boundless=True, fill_value=0)[:n_bands]],
                            axis=0,
                        )
                    x = torch.from_numpy(arr.astype("float32") / 10000.0)[None].to(device)
                    with torch.no_grad(), torch.autocast(device_type=device, enabled=device == "cuda"):
                        out = task(x)
                        logits = out.output if hasattr(out, "output") else out
                        prob = torch.softmax(logits, dim=1)[0, 1].float().cpu().numpy()
                    acc[r : r + h, c : c + w] += prob[:h, :w] * hann[:h, :w]
                    wacc[r : r + h, c : c + w] += hann[:h, :w]
                    valid_any[r : r + h, c : c + w] |= (arr[:, :h, :w] > 0).any(axis=0)
                    windows_run += 1
        # Weighted average; zero where no window contributed or the composite had no data.
        prob_full = np.where(wacc > 0, acc / np.maximum(wacc, 1e-6), 0.0)
        prob_full[~valid_any] = 0.0
        out_tif = out_dir / f"{tile}.tif"
        with rasterio.open(
            out_tif, "w", driver="GTiff", width=W, height=H, count=1, dtype="uint8",
            crs=crs, transform=transform, compress="deflate", predictor=2,
        ) as dst:
            dst.write((np.clip(prob_full, 0, 1) * 255).astype("uint8"), 1)
        if src1 is not None:
            src1.close()
    log.info("Inference wrote %d seamless cell rasters (%d windows) -> %s",
             len(tiles), windows_run, out_dir)
    return out_dir
