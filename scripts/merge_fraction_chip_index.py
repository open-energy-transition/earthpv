"""Merge per-source fraction-regression chip indexes into a combined training index.

Mirrors `scripts/merge_chip_index.py`'s train-row-oversampling logic exactly (val
rows are never duplicated), but as a SEPARATE script rather than an edit to that
one: the shared merger hardcodes both its input path pattern
(`data/chips/<aoi>/index.parquet`) and its output path
(`data/chips/combined/index.parquet`) - the index the *production segmentation*
configs (`terramind_pv.yaml`, `terramind_pv_v3india.yaml`) depend on. Fraction
chips don't all live under that same input pattern either (Germany's usable set
is `data/chips_unfiltered/germany_fraction`, not `data/chips/germany_fraction`,
which is the too-small well-mapped-filtered variant - see
`configs/terramind_pv_fraction.yaml`'s comment), so reusing the shared script
as-is would need path overrides anyway.

Usage: python scripts/merge_fraction_chip_index.py [--out PATH] [name:path[:repeat] ...]
  (default sources: germany:data/chips_unfiltered/germany_fraction:1 pakistan:data/chips/pakistan_fraction:2)
  (default --out: data/chips/combined_fraction/index.parquet)

`--out` exists because the default path is shared, mutable state: both
`configs/terramind_pv_fraction_pakistan.yaml` (v1) and `..._v2.yaml` point
`index_path` at it identically, so re-running this script with a different source
list silently overwrites whichever mix a config previously assumed it built from.
Any new experiment should pass an explicitly-named `--out` and point a fresh config
at that exact path, not reuse the shared default in place.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = [
    "germany:data/chips_unfiltered/germany_fraction:1",
    "pakistan:data/chips/pakistan_fraction:2",
]
DEFAULT_OUT = ROOT / "data" / "chips" / "combined_fraction" / "index.parquet"


def main(sources: list[str], out_path: Path) -> None:
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
        # Hard-negative sources (build_hard_negative_chips) burn masks the segmentation
        # way (pv_pixels, no pv_frac_sum column) since they're all-zero targets either way.
        pv_col = df.pv_frac_sum if "pv_frac_sum" in df.columns else df.pv_pixels
        print(f"{name} (x{rep} train, {path}): {len(df)} chips "
              f"({int((df.split == 'val').sum())} val, {int((pv_col > 0).sum())} with PV)")
    out = pd.concat(frames, ignore_index=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path)
    print(f"{out_path.parent.name}: {len(out)} chips -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output index.parquet path")
    ap.add_argument("sources", nargs="*", default=DEFAULT_SOURCES, help="name:path[:repeat] specs")
    args = ap.parse_args()
    main(args.sources, args.out)
