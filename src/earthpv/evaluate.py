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


def evaluate(aoi: str, checkpoint: Path, chips_dir: Path, threshold: float = 0.3) -> pd.DataFrame:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import torch
    from terratorch.tasks import SemanticSegmentationTask

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    region_dir = Path(settings.raw["local_root"]) / cfg["source_region"]
    labels = load_solar_labels(region_dir)
    labels = labels[labels.placement.isin(["rooftop", "ground"])].reset_index(drop=True)

    index = pd.read_parquet(Path(chips_dir) / aoi / "index.parquet")
    val = index[index.split == "val"]
    if val.empty:
        val = index.sample(frac=0.2, random_state=42)
    log.info("Evaluating on %d val chips", len(val))

    task = SemanticSegmentationTask.load_from_checkpoint(checkpoint, map_location="cpu").eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    task = task.to(device)
    # Chips carry the model's full input (10 bands, or 20 for a two-season stack);
    # feed all of them rather than truncating to the single-season band count.

    tp = fp = fn = 0
    detected, missed = [], []  # areas of GT installations
    for _, row in val.iterrows():
        with rasterio.open(row["image"]) as src:
            arr = src.read().astype("float32")
            transform, crs, shape = src.transform, src.crs, (src.height, src.width)
            chip_geo = box(*rasterio.warp.transform_bounds(crs, "EPSG:4326", *src.bounds))
        x = torch.from_numpy(arr / 10000.0)[None].to(device)
        with torch.no_grad(), torch.autocast(device_type=device, enabled=device == "cuda"):
            out = task(x)
            logits = out.output if hasattr(out, "output") else out
            pred = (torch.softmax(logits, 1)[0, 1] >= threshold).cpu().numpy()

        with rasterio.open(row["mask"]) as src:
            gt = src.read(1)
        valid = gt != -1
        tp += int((pred & (gt == 1) & valid).sum())
        fp += int((pred & (gt == 0) & valid).sum())
        fn += int((~pred & (gt == 1) & valid).sum())

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
    log.info("Per-installation recall by size (m2):\n%s", report.to_string(index=False))
    return report


if __name__ == "__main__":
    import sys

    import rasterio.warp  # noqa: F401

    ckpt = sys.argv[1] if len(sys.argv) > 1 else sorted(Path("data/models").glob("*.ckpt"))[-1]
    evaluate("germany", Path(ckpt), Path("data/chips"))
