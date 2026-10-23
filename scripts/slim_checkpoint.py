"""Turn a training checkpoint into a release checkpoint, and prove the two predict alike.

A Lightning checkpoint carries optimizer moments, loop state and callbacks, two thirds of
its 98.6 MB, none of it needed to predict. It also records `backbone_pretrained: true`, so
loading one first downloads TerraMind's base weights from Hugging Face only for the
state_dict to overwrite every one of them. The release copy keeps the weights and
hyperparameters, sets `backbone_pretrained: false`, and so loads offline at 33 MB.

    .pixi/envs/ml/bin/python scripts/slim_checkpoint.py \\
        data/models/v14_combined_south_africa/terramind-pv-epoch=41-step=79968.ckpt \\
        dist/model/earthpv_segmentation_v14.ckpt --verify-aoi south_africa

Verification runs both files on held-out chips of `--verify-aoi` and fails unless the PV
probabilities agree to 1e-4 (they came out identical for v14). Then upload the file with a
SHA256SUMS and update scripts/fetch_model.py's RELEASE.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

KEEP = ["epoch", "global_step", "pytorch-lightning_version", "state_dict", "hparams_name",
        "hyper_parameters"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--verify-aoi", default="france", help="AOI whose val chips to compare on")
    ap.add_argument("--chips", type=int, default=6)
    args = ap.parse_args()

    import numpy as np
    import pandas as pd
    import rasterio
    import torch

    from earthpv import infer

    infer._allow_custom_losses()
    ck = torch.load(args.src, map_location="cpu", weights_only=False)
    slim = {k: ck[k] for k in KEEP if k in ck}
    slim["hyper_parameters"]["model_args"]["backbone_pretrained"] = False
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    torch.save(slim, args.dst)
    print(f"{args.src.stat().st_size / 1e6:.1f} MB -> {args.dst.stat().st_size / 1e6:.1f} MB")

    idx = pd.read_parquet(f"data/chips/{args.verify_aoi}/index.parquet")
    rows = idx[idx["split"] == "val"].head(args.chips)
    a, device, task_type = infer.load_model(args.src)
    b, _, _ = infer.load_model(args.dst)
    worst = 0.0
    for _, r in rows.iterrows():
        with rasterio.open(r["image"]) as f:
            arr = f.read()
        pa = infer.predict_window(arr, a, device, task_type)
        pb = infer.predict_window(arr, b, device, task_type)
        worst = max(worst, float(np.abs(pa - pb).max()))
    print(f"{len(rows)} {args.verify_aoi} val chips, max |dp| = {worst:.3g}")
    if worst > 1e-4:
        print("Release copy does not reproduce the original", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
