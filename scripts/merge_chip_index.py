"""Merge per-AOI chip indexes into the combined training index.

Usage: python scripts/merge_chip_index.py [aoi[:repeat] ...]  (default: germany punjab)
`repeat` duplicates that AOI's *train* rows N times to oversample an
underrepresented domain (val rows are never duplicated).
Writes data/chips/combined/index.parquet with an `aoi` column added.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main(aois: list[str]) -> None:
    frames = []
    for spec in aois:
        aoi, _, rep = spec.partition(":")
        rep = int(rep or 1)
        p = ROOT / "data" / "chips" / aoi / "index.parquet"
        df = pd.read_parquet(p)
        df["aoi"] = aoi
        if rep > 1:
            train = df[df.split == "train"]
            df = pd.concat([df] + [train] * (rep - 1), ignore_index=True)
        frames.append(df)
        print(f"{aoi} (x{rep} train): {len(df)} chips ({int((df.split == 'val').sum())} val, "
              f"{int((df.pv_pixels > 0).sum())} with PV)")
    out = pd.concat(frames, ignore_index=True)
    out_path = ROOT / "data" / "chips" / "combined" / "index.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path)
    print(f"combined: {len(out)} chips -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["germany", "punjab"])
