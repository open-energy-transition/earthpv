"""Per-band mean/std of a chip corpus's TRAIN split, in the units the model receives.

Chips store DN; `datamodule.PVChipDataset` divides by `DN_SCALE` before the model sees them,
so the statistics are computed on DN / DN_SCALE. A backbone that standardises its own input
(`earthpv.thor_backbone`) takes these as `band_mean` / `band_std`. Pixels where every band
is 0 (composite fill) are excluded. Train split only, so no holdout chip informs the fit.

    python scripts/chip_band_stats.py --index data/chips/combined_south_africa/index.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.datamodule import DN_SCALE  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--n", type=int, default=3000, help="chips sampled from the train split")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    ix = pd.read_parquet(a.index)
    train = ix[ix.split == "train"]
    sample = train.sample(n=min(a.n, len(train)), random_state=a.seed)
    s = s2 = None
    count = 0
    for path in sample["image"]:
        with rasterio.open(path) as src:
            arr = src.read().astype("float64") / DN_SCALE
        valid = (arr != 0).any(axis=0)
        px = arr[:, valid]
        if s is None:
            s = np.zeros(arr.shape[0])
            s2 = np.zeros(arr.shape[0])
        s += px.sum(axis=1)
        s2 += (px**2).sum(axis=1)
        count += px.shape[1]
    mean = s / count
    std = np.sqrt(s2 / count - mean**2)
    out = {"index": str(a.index), "chips": len(sample), "pixels": int(count),
           "band_mean": [round(float(v), 6) for v in mean],
           "band_std": [round(float(v), 6) for v in std]}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
