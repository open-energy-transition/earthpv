"""Drop training chips that could see the geographic val holdout.

`chips` assigns a chip to the 0.1 deg cell holding its (jittered) centre and splits on
`val_tiles`, so a TRAIN chip centred in a cell next to a val cell can reach ~1.1 km into it
(half the 2.24 km window) and show the model an installation it is then scored on. A
province-shaped holdout has a long border, so this is not a corner case. Every train chip
in a cell 8-adjacent to a val cell is relabelled `split = "buffer"`, which the datamodule,
`evaluate` and `merge_chip_index`'s repeat all ignore (they select `train`/`val` only). A
chip two cells away is at least one full cell (~11 km) from the holdout, far beyond a
window's reach.

Rewrites `data/chips/<aoi>/index.parquet` in place, keeping the original as
`index_prebuffer.parquet` the first time. Idempotent.

    python scripts/mark_val_buffer.py --aoi vietnam
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    a = ap.parse_args()

    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi

    _, cfg = resolve_aoi(a.aoi, Settings.load())
    val = set(cfg.get("val_tiles") or [])
    if not val:
        print(f"{a.aoi}: no val_tiles configured; nothing to buffer")
        return 0
    path = REPO / "data" / "chips" / a.aoi / "index.parquet"
    backup = path.with_name("index_prebuffer.parquet")
    if not backup.exists():
        pd.read_parquet(path).to_parquet(backup)
    idx = pd.read_parquet(backup)

    def ixy(name: str) -> tuple[int, int]:
        x, y = name.split("_")
        return int(x), int(y)

    vxy = {ixy(t) for t in val}
    ring = {(x + dx, y + dy) for x, y in vxy for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - vxy
    tile_xy = idx.tile.map(lambda t: ixy(t) if isinstance(t, str) and "_" in t else None)
    hit = (idx.split == "train") & tile_xy.isin(ring)
    idx.loc[hit, "split"] = "buffer"
    idx.to_parquet(path)
    print(f"{a.aoi}: {int(hit.sum())} train chips in the {len(ring)}-cell ring around "
          f"{len(vxy)} val cells marked 'buffer'; now "
          f"{int((idx.split == 'train').sum())} train / {int((idx.split == 'val').sum())} val "
          f"/ {int((idx.split == 'buffer').sum())} buffer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
