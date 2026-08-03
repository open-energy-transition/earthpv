"""Score the confirmed hard-negative chip set with two fraction-head checkpoints and
compare predicted PV fraction at each candidate's exact center, before vs. after
retraining on those same negatives.

These 1,020 chips (data/chips_fraction_hardneg_eval/pakistan_hard_neg) are large,
OSM-unmapped buildings the OLD checkpoint already scored below 0.10 in both the current
and 2022 composites (that consistency is what "confirmed" means in
hard_negatives.py -- see docs comment there); most were also folded into the new
checkpoint's own training set at 1x (not oversampled). So this is NOT a test of whether
retraining "fixes" false positives at these exact points (the old model already got them
right) -- it is a sanity check that explicit reinforcement on this population didn't
destabilize it. Whether real installations were lost in the process is a separate
question, answered by `earthpv evaluate --aoi pakistan --checkpoint <ckpt> --task-type
regression` (pixel RMSE/IoU and per-installation recall by size) run for both checkpoints
against the standard held-out val split.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from earthpv.infer import load_model, predict_window

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("score_hardneg_before_after")

CENTER_RADIUS_PX = 3  # ~30x30 m window around the chip center, matching a small rooftop


def score_checkpoint(checkpoint: Path, chip_paths: list[Path]) -> np.ndarray:
    task, device, task_type = load_model(checkpoint, task_type="regression")
    out = np.full(len(chip_paths), np.nan)
    for i, p in enumerate(chip_paths):
        with rasterio.open(p) as src:
            arr = src.read().astype("float32")
        frac = predict_window(arr, task, device, task_type)
        h, w = frac.shape[-2:]
        cy, cx = h // 2, w // 2
        r = CENTER_RADIUS_PX
        patch = frac[max(0, cy - r):cy + r + 1, max(0, cx - r):cx + r + 1]
        out[i] = float(patch.mean())
    return out


def main(old_ckpt: Path, new_ckpt: Path, chips_dir: Path) -> None:
    index = pd.read_parquet(chips_dir / "index.parquet")
    chip_paths = [Path(p) for p in index["image"]]
    log.info("Scoring %d hard-negative chips with OLD checkpoint %s", len(chip_paths), old_ckpt)
    old_scores = score_checkpoint(old_ckpt, chip_paths)
    log.info("Scoring %d hard-negative chips with NEW checkpoint %s", len(chip_paths), new_ckpt)
    new_scores = score_checkpoint(new_ckpt, chip_paths)

    df = index[["chip_id", "split"]].copy()
    df["old_score"] = old_scores
    df["new_score"] = new_scores
    df["delta"] = df.new_score - df.old_score

    for label, sub in [("all", df), ("train (seen in retrain)", df[df.split == "train"]),
                        ("val (held out)", df[df.split == "val"])]:
        if sub.empty:
            continue
        log.info(
            "%s (n=%d): old mean=%.4f median=%.4f | new mean=%.4f median=%.4f | "
            "delta mean=%.4f | old>=0.10: %d | new>=0.10: %d",
            label, len(sub), sub.old_score.mean(), sub.old_score.median(),
            sub.new_score.mean(), sub.new_score.median(), sub.delta.mean(),
            int((sub.old_score >= 0.10).sum()), int((sub.new_score >= 0.10).sum()),
        )
    out_path = chips_dir / "before_after_scores.parquet"
    df.to_parquet(out_path)
    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-checkpoint", type=Path, required=True)
    ap.add_argument("--new-checkpoint", type=Path, required=True)
    ap.add_argument(
        "--chips-dir", type=Path,
        default=Path("data/chips_fraction_hardneg_eval/pakistan_hard_neg"),
    )
    args = ap.parse_args()
    main(args.old_checkpoint, args.new_checkpoint, args.chips_dir)
