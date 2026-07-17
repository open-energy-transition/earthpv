"""Can glint evidence improve pixel IoU, not just ranking?

The pipeline polygonizes at a recall-oriented threshold (0.3) and uses glint only as
a rank_score bonus (`postprocess.add_glint_prior`), which cannot move IoU. Hypothesis:
where the glint physics *confirms* PV, the model's probability field is systematically
under-thresholded (partial roofs, mixed pixels), so lowering the threshold locally —
only inside glint-confirmed windows — recovers true-positive pixels at little false-
positive cost, while lowering it everywhere would drown IoU in false positives.

Measured entirely offline on the 500-target OSM validation sample: per-target windows
from the existing country-wide prob rasters (data/predictions/pakistan/prob), ground
truth = the OSM polygon, glint gates from data/glint/pakistan_summary.csv.

Strategies compared over identical windows:
  - unconditional threshold sweep (0.30 baseline down to 0.05)
  - glint-gated plain lowering (validated / detected targets only)
  - glint-gated hysteresis (grow >= t_low pixels connected to a >= 0.3 seed component)

Usage:
  .pixi/envs/default/bin/python scripts/glint_iou_experiment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
from rasterio import features as rio_features
from rasterio.windows import Window, from_bounds
from scipy import ndimage
from shapely.geometry import box
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.config import DATA_DIR  # noqa: E402

PROB_DIR = DATA_DIR / "predictions" / "pakistan" / "prob"
TARGETS_FILE = DATA_DIR / "glint" / "pakistan_targets.parquet"
SUMMARY_FILE = DATA_DIR / "glint" / "pakistan_summary.csv"
INDEX_CACHE = DATA_DIR / "glint" / "prob_raster_index.parquet"
OUT_DIR = DATA_DIR / "glint"
PAD_M = 200          # window padding around the target polygon
T_BASE = 0.3         # the pipeline's operational polygonize threshold


def prob_raster_index() -> gpd.GeoDataFrame:
    if INDEX_CACHE.exists():
        return gpd.read_parquet(INDEX_CACHE)
    rows = []
    for tif in tqdm(sorted(PROB_DIR.glob("*.tif")), desc="index rasters"):
        with rasterio.open(tif) as src:
            b = rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            rows.append({"path": str(tif), "geometry": box(*b)})
    idx = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    idx.to_parquet(INDEX_CACHE)
    return idx


def load_targets() -> gpd.GeoDataFrame:
    tgts = gpd.read_parquet(TARGETS_FILE)
    summ = pd.read_csv(SUMMARY_FILE)[["pid", "n_spikes", "n_consistent"]]
    g = tgts.merge(summ, on="pid", how="inner")
    g["validated"] = g.n_consistent >= 2
    g["detected"] = g.n_spikes >= 1
    return g


def read_window(tif: str, geom_wgs84) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (prob, gt_mask) for a padded window around the target, or None if the
    polygon falls outside this raster's footprint."""
    with rasterio.open(tif) as src:
        g = gpd.GeoSeries([geom_wgs84], crs="EPSG:4326").to_crs(src.crs).iloc[0]
        minx, miny, maxx, maxy = g.bounds
        win = from_bounds(minx - PAD_M, miny - PAD_M, maxx + PAD_M, maxy + PAD_M, src.transform)
        try:
            win = win.intersection(Window(0, 0, src.width, src.height))
        except rasterio.errors.WindowError:
            # Representative-point sjoin matched this raster's WGS84 bbox, but the
            # target polygon itself (its own bounds, padded) falls just outside the
            # raster's actual pixel grid — a rounding/edge case, not a real target.
            return None
        win = win.round_offsets().round_lengths()
        if win.width <= 0 or win.height <= 0:
            return None
        prob = src.read(1, window=win).astype("float32") / 255.0
        wt = src.window_transform(win)
        gt = rio_features.rasterize(
            [(g, 1)], out_shape=prob.shape, transform=wt, all_touched=True, dtype="uint8"
        ).astype(bool)
        if not gt.any():
            return None
        return prob, gt


def pred_plain(prob: np.ndarray, t: float) -> np.ndarray:
    return prob >= t


def pred_hyst(prob: np.ndarray, t_low: float, t_seed: float = T_BASE) -> np.ndarray:
    """Pixels >= t_low, but only in connected components that contain a >= t_seed pixel
    — grows existing detections outward without conjuring detached blobs."""
    lab, n = ndimage.label(prob >= t_low)
    if n == 0:
        return prob >= t_seed
    seeds = np.unique(lab[prob >= t_seed])
    seeds = seeds[seeds > 0]
    if seeds.size == 0:
        return prob >= t_seed
    return np.isin(lab, seeds)


def strategies() -> list[tuple[str, str | None, str, float]]:
    """(name, gate column or None, kind, t). Kinds:
    plain — threshold t on gated targets, T_BASE on the rest (lowering direction);
    hyst  — like plain but grown only from >= T_BASE seed components;
    raise — threshold t on UNgated targets, T_BASE stays on gated ones (glint
            protects confirmed installations from a global precision raise)."""
    out: list[tuple[str, str | None, str, float]] = [("t=0.30 baseline", None, "plain", T_BASE)]
    for t in (0.20, 0.15, 0.10, 0.05):
        out.append((f"t={t:.2f} unconditional", None, "plain", t))
    for t in (0.40, 0.50, 0.60, 0.70):
        out.append((f"t={t:.2f} unconditional", None, "plain", t))
    for t in (0.20, 0.15, 0.10, 0.05):
        out.append((f"glint-validated plain t={t:.2f}", "validated", "plain", t))
    for t in (0.15, 0.10, 0.05):
        out.append((f"glint-validated hyst  t={t:.2f}", "validated", "hyst", t))
    for t in (0.15, 0.10):
        out.append((f"glint-detected  plain t={t:.2f}", "detected", "plain", t))
    for t in (0.40, 0.50, 0.60, 0.70):
        out.append((f"raise t={t:.2f}, validated keep 0.30", "validated", "raise", t))
    for t in (0.40, 0.50, 0.60):
        out.append((f"raise t={t:.2f}, detected  keep 0.30", "detected", "raise", t))
    return out


def main() -> None:
    tgts = load_targets()
    idx = prob_raster_index()
    reps = gpd.GeoDataFrame(
        tgts[["pid"]], geometry=tgts.geometry.representative_point(), crs="EPSG:4326"
    )
    hits = gpd.sjoin(reps, idx, predicate="within", how="left").drop_duplicates("pid")
    tgts = tgts.merge(hits[["pid", "path"]], on="pid", how="left")
    no_raster = tgts.path.isna().sum()

    strats = strategies()
    acc = {s[0]: np.zeros(3, dtype=np.int64) for s in strats}       # tp, fp, fn (all)
    acc_1k = {s[0]: np.zeros(3, dtype=np.int64) for s in strats}    # >= 1000 m2 subset
    rescued = {s[0]: 0 for s in strats}  # invisible at T_BASE -> gains a GT-overlapping pixel
    hit = {s[0]: 0 for s in strats}      # targets with >= 1 predicted pixel on GT (recall proxy)
    per_target = []
    n_eval = 0

    for row in tqdm(list(tgts.itertuples()), desc="targets"):
        if not isinstance(row.path, str):
            continue
        rw = read_window(row.path, row.geometry)
        if rw is None:
            continue
        prob, gt = rw
        n_eval += 1
        base_pred = pred_plain(prob, T_BASE)
        base_hits_gt = bool((base_pred & gt).any())
        rec = {"pid": row.pid, "area_m2": row.area_m2, "bucket": row.bucket,
               "validated": row.validated, "detected": row.detected,
               "max_prob": float(prob.max()), "base_hits_gt": base_hits_gt}
        for name, gate, kind, t in strats:
            gated = gate is not None and getattr(row, gate)
            if kind == "raise":
                pred = base_pred if gated else pred_plain(prob, t)
            elif gate is not None and not gated:
                pred = base_pred
            elif kind == "hyst":
                pred = pred_hyst(prob, t)
            else:
                pred = pred_plain(prob, t)
            tp = int((pred & gt).sum())
            fp = int((pred & ~gt).sum())
            fn = int((~pred & gt).sum())
            acc[name] += (tp, fp, fn)
            hit[name] += int(tp > 0)
            if row.area_m2 >= 1000:
                acc_1k[name] += (tp, fp, fn)
            if not base_hits_gt and tp > 0:
                rescued[name] += 1
            rec[f"iou::{name}"] = tp / max(tp + fp + fn, 1)
        per_target.append(rec)

    print(f"\n{n_eval} targets evaluated ({no_raster} had no covering prob raster, "
          f"{len(tgts) - n_eval - no_raster} fell outside raster footprints / empty GT)")

    rows = []
    for name, _, _, _ in strats:
        tp, fp, fn = acc[name]
        t1, f1p, f1n = acc_1k[name]
        rows.append({
            "strategy": name,
            "IoU": tp / max(tp + fp + fn, 1),
            "IoU_ge1k": t1 / max(t1 + f1p + f1n, 1),
            "tp": tp, "fp": fp, "fn": fn,
            "inst_recall": hit[name] / max(n_eval, 1),
            "rescued": rescued[name],
        })
    table = pd.DataFrame(rows)
    table[["IoU", "IoU_ge1k"]] = table[["IoU", "IoU_ge1k"]].round(4)
    pd.DataFrame(per_target).to_csv(OUT_DIR / "iou_experiment_per_target.csv", index=False)
    table.to_csv(OUT_DIR / "iou_experiment.csv", index=False)
    print("\n=== window IoU by strategy (identical windows, gated strategies fall back "
          "to baseline where ungated) ===")
    print(table.to_string(index=False))

    pt = pd.DataFrame(per_target)
    inv = pt[~pt.base_hits_gt]
    print(f"\n{len(inv)} targets invisible at t={T_BASE:.2f}; of those, "
          f"{int(inv.validated.sum())} are glint-validated (rescue potential); "
          f"median max window prob of the validated-invisible: "
          f"{inv[inv.validated].max_prob.median():.3f}")


if __name__ == "__main__":
    main()
