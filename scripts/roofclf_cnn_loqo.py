"""LOQO-evaluate the roofclf-CNN pilot and compare directly against the existing
logistic-regression baseline (`data/roofclf/folds.csv`).

See /home/tobi/.claude/plans/soft-wondering-hopper.md for the staged pilot-then-full-LOQO
plan and the go/no-go rule. `--quadrats` restricts which quadrats get their own held-out
fold -- pass `mardan lahore` for the Stage 1 pilot, omit for the Stage 2 full run.

Usage:
    .pixi/envs/ml/bin/python scripts/roofclf_cnn_loqo.py --chip-px 64 --quadrats mardan lahore
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from earthpv.roofclf_cnn import CHIP_PX_DEFAULT, loqo_evaluate_cnn  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chip-px", type=int, default=CHIP_PX_DEFAULT)
    ap.add_argument("--chips-dir", type=Path, default=Path("data/roofclf_cnn"))
    ap.add_argument("--quadrats", nargs="*", default=None, help="e.g. mardan lahore for the pilot")
    ap.add_argument("--lr-folds", type=Path, default=Path("data/roofclf/folds.csv"),
                     help="Existing logistic-regression folds.csv to diff against")
    ap.add_argument("--fuse-scalars", action="store_true")
    ap.add_argument("--max-epochs", type=int, default=40)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    chips_path = args.chips_dir / f"chips_{args.chip_px}px.npy"
    index_path = args.chips_dir / f"chips_{args.chip_px}px_index.parquet"
    out_dir = args.out_dir or args.chips_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    folds, summary, _ = loqo_evaluate_cnn(
        chips_path, index_path, quadrats=args.quadrats, fuse_scalars=args.fuse_scalars,
        max_epochs=args.max_epochs, patience=args.patience, batch_size=args.batch_size,
    )

    lr = pd.read_csv(args.lr_folds)[["quadrat", "auc", "auc_within_size"]].rename(
        columns={"auc": "lr_auc", "auc_within_size": "lr_auc_within_size"}
    )
    merged = folds.merge(lr, on="quadrat", how="left")
    merged["delta_auc"] = merged.auc - merged.lr_auc
    merged["delta_auc_within_size"] = merged.auc_within_size - merged.lr_auc_within_size

    tag = f"{args.chip_px}px" + ("_fused" if args.fuse_scalars else "")
    merged.to_csv(out_dir / f"folds_{tag}.csv", index=False)
    (out_dir / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2))

    print(merged.to_string(index=False))
    print()
    print(json.dumps(summary, indent=2))
    print(f"-> {out_dir}/folds_{tag}.csv, {out_dir}/summary_{tag}.json")


if __name__ == "__main__":
    main()
