"""Evaluate a trained model on held-out chips.

Reports pixel IoU/F1 and, more importantly for the >= 500 m2 goal, per-installation
recall bucketed by array size: an installation counts as detected if any predicted
positive pixel overlaps its polygon (recall-first, matching the OSM-validation use).
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
from rasterio import features as rio_features
from shapely.geometry import box

from earthpv.config import Settings
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.local_source import load_solar_labels

log = logging.getLogger(__name__)

SIZE_BUCKETS = [(1000, np.inf), (500, 1000), (250, 500), (0, 250)]


def _bucket(area: float) -> str:
    for lo, hi in SIZE_BUCKETS:
        if lo <= area < hi:
            return f"{lo}-{'inf' if hi == np.inf else int(hi)}"
    return "0-250"


def evaluate(
    aoi: str, checkpoint: Path, chips_dir: Path, threshold: float = 0.3,
    task_type: str = "auto", chips_name: str | None = None,
) -> pd.DataFrame:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import torch

    from earthpv.infer import _sniff_task_type, load_model

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    region_dir = Path(settings.raw["local_root"]) / cfg["source_region"]
    labels = load_solar_labels(region_dir)
    if task_type == "auto":
        task_type = _sniff_task_type(checkpoint)
    placements = ["rooftop", "ground", "small"] if task_type == "regression" else \
        ["rooftop", "ground"]
    labels = labels[labels.placement.isin(placements)].reset_index(drop=True)

    index = pd.read_parquet(Path(chips_dir) / (chips_name or aoi) / "index.parquet")
    val = index[index.split == "val"]
    if val.empty:
        val = index.sample(frac=0.2, random_state=42)
    log.info("Evaluating on %d val chips", len(val))

    task, device, task_type = load_model(checkpoint, task_type=task_type)
    # Chips carry the model's full input (10 bands, or 20 for a two-season stack);
    # feed all of them rather than truncating to the single-season band count.

    tp = fp = fn = 0
    detected, missed = [], []  # areas of GT installations
    pred_sums, gt_sums = [], []  # chip-level Σ predicted / true PV area (m2), regression only
    sq_err_sum = abs_err_sum = n_valid_px = 0.0
    for _, row in val.iterrows():
        with rasterio.open(row["image"]) as src:
            arr = src.read().astype("float32")
            transform, crs, shape = src.transform, src.crs, (src.height, src.width)
            chip_geo = box(*rasterio.warp.transform_bounds(crs, "EPSG:4326", *src.bounds))
        x = torch.from_numpy(arr / 10000.0)[None].to(device)
        with torch.no_grad(), torch.autocast(device_type=device, enabled=device == "cuda"):
            out = task(x)
            logits = out.output if hasattr(out, "output") else out
            if task_type == "regression":
                frac = logits[0] if logits.ndim == 3 else logits[0, 0]
                frac = frac.clamp(0, 1).cpu().numpy()
            else:
                frac = torch.softmax(logits, 1)[0, 1].cpu().numpy()
        pred = frac >= threshold

        with rasterio.open(row["mask"]) as src:
            gt_raw = src.read(1).astype("float32")
        valid = gt_raw != -1
        if task_type == "regression":
            err = frac[valid] - gt_raw[valid]
            sq_err_sum += float((err**2).sum())
            abs_err_sum += float(np.abs(err).sum())
            n_valid_px += int(valid.sum())
            pred_sums.append(float(frac[valid].sum()) * 100.0)
            gt_sums.append(float(gt_raw[valid].sum()) * 100.0)
            gt_binary = gt_raw > 0
        else:
            gt_binary = gt_raw == 1
        tp += int((pred & gt_binary & valid).sum())
        fp += int((pred & ~gt_binary & valid).sum())
        fn += int((~pred & gt_binary & valid).sum())

        # Per-installation recall
        gt_here = labels[labels.geometry.intersects(chip_geo)]
        if gt_here.empty:
            continue
        for _, inst in gt_here.iterrows():
            area = inst.area_m2 if inst.area_m2 > 0 else geodesic_area_m2(inst.geometry)
            poly = gpd.GeoSeries([inst.geometry], crs="EPSG:4326").to_crs(crs).iloc[0]
            inst_mask = rio_features.rasterize(
                [(poly, 1)], out_shape=shape, transform=transform, all_touched=True, dtype="uint8"
            ).astype(bool)
            if not inst_mask.any():
                continue
            (detected if (pred & inst_mask).any() else missed).append(area)

    iou = tp / max(tp + fp + fn, 1)
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    log.info("Pixel IoU=%.3f F1=%.3f (tp=%d fp=%d fn=%d)", iou, f1, tp, fp, fn)

    rows = []
    det = pd.Series(detected, dtype=float)
    mis = pd.Series(missed, dtype=float)
    for lo, hi in SIZE_BUCKETS:
        name = f"{lo}-{'inf' if hi == np.inf else int(hi)}"
        nd = int(((det >= lo) & (det < hi)).sum())
        nm = int(((mis >= lo) & (mis < hi)).sum())
        tot = nd + nm
        rows.append(dict(bucket=name, installations=tot, detected=nd,
                         recall=round(nd / tot, 3) if tot else float("nan")))
    report = pd.DataFrame(rows)
    report.attrs["pixel_iou"] = iou
    report.attrs["pixel_f1"] = f1

    if task_type == "regression":
        rmse = (sq_err_sum / max(n_valid_px, 1)) ** 0.5
        mae = abs_err_sum / max(n_valid_px, 1)
        pred_s, gt_s = np.array(pred_sums), np.array(gt_sums)
        bias = float((pred_s - gt_s).mean()) if len(pred_s) else float("nan")
        if len(pred_s) > 1 and gt_s.std() > 0 and pred_s.std() > 0:
            r2 = float(np.corrcoef(pred_s, gt_s)[0, 1] ** 2)
            slope = float(np.sum(pred_s * gt_s) / max(float(np.sum(gt_s**2)), 1e-9))
        else:
            r2 = slope = float("nan")
        report.attrs.update(pixel_rmse=rmse, pixel_mae=mae, chip_sum_r2=r2,
                            chip_sum_slope=slope, chip_sum_bias_m2=bias)
        log.info(
            "Pixel RMSE=%.4f MAE=%.4f | chip-sum R2=%.3f slope=%.3f bias=%.1f m2 (n=%d chips)",
            rmse, mae, r2, slope, bias, len(pred_s),
        )
    log.info("Per-installation recall by size (m2):\n%s", report.to_string(index=False))
    return report


if __name__ == "__main__":
    import sys

    import rasterio.warp  # noqa: F401

    ckpt = sys.argv[1] if len(sys.argv) > 1 else sorted(Path("data/models").glob("*.ckpt"))[-1]
    evaluate("germany", Path(ckpt), Path("data/chips"))
