"""Merge per-AOI chip indexes into the combined training index.

Usage: python scripts/merge_chip_index.py [--out PATH] [aoi[:repeat] ...]
       (default aois: germany punjab)
`repeat` duplicates that AOI's *train* rows N times to oversample an
underrepresented domain (val rows are never duplicated).
Writes data/chips/combined/index.parquet with an `aoi` column added, or PATH with
`--out`. Pass `--out` for every new corpus: the default path holds v3india's corpus and
has been silently clobbered by a merge more than once (CLAUDE.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main(aois: list[str], out_path: Path | None = None) -> None:
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
    out_path = out_path or ROOT / "data" / "chips" / "combined" / "index.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path)
    print(f"combined: {len(out)} chips -> {out_path}")


if __name__ == "__main__":
    args, out = sys.argv[1:], None
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i:i + 2]
    main(args or ["germany", "punjab"], out)
