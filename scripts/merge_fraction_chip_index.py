"""Merge per-source fraction-regression chip indexes into a combined training index.

Mirrors `scripts/merge_chip_index.py`'s train-row-oversampling logic exactly (val
rows are never duplicated), but as a SEPARATE script rather than an edit to that
one: the shared merger hardcodes both its input path pattern
(`data/chips/<aoi>/index.parquet`) and its output path
(`data/chips/combined/index.parquet`) — the index the *production segmentation*
configs (`terramind_pv.yaml`, `terramind_pv_v3india.yaml`) depend on. Fraction
chips don't all live under that same input pattern either (Germany's usable set
is `data/chips_unfiltered/germany_fraction`, not `data/chips/germany_fraction`,
which is the too-small well-mapped-filtered variant — see
`configs/terramind_pv_fraction.yaml`'s comment), so reusing the shared script
as-is would need path overrides anyway.

Usage: python scripts/merge_fraction_chip_index.py [name:path[:repeat] ...]
  (default: germany:data/chips_unfiltered/germany_fraction:1 pakistan:data/chips/pakistan_fraction:2)
Writes data/chips/combined_fraction/index.parquet with a `source` column added.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [
    "germany:data/chips_unfiltered/germany_fraction:1",
    "pakistan:data/chips/pakistan_fraction:2",
]


def main(sources: list[str]) -> None:
    frames = []
    for spec in sources:
        parts = spec.split(":")
        name, path = parts[0], parts[1]
        rep = int(parts[2]) if len(parts) > 2 else 1
        p = ROOT / path / "index.parquet"
        df = pd.read_parquet(p)
        df["source"] = name
        if rep > 1:
            train = df[df.split == "train"]
            df = pd.concat([df] + [train] * (rep - 1), ignore_index=True)
        frames.append(df)
        print(f"{name} (x{rep} train, {path}): {len(df)} chips "
              f"({int((df.split == 'val').sum())} val, {int((df.pv_frac_sum > 0).sum())} with PV)")
    out = pd.concat(frames, ignore_index=True)
    out_path = ROOT / "data" / "chips" / "combined_fraction" / "index.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path)
    print(f"combined_fraction: {len(out)} chips -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_SOURCES)
