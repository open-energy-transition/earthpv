"""Build the per-building chip cache for the roofclf-CNN pilot experiment.

See /home/tobi/.claude/plans/soft-wondering-hopper.md for the full design. Reads the
CANONICAL labelled population (`data/roofclf/buildings.geoparquet`, 91,840 buildings /
18 quadrats -- the exact population behind the 0.8824 logistic-regression baseline and
the 0.8748 gradient-boosted-tree result already measured this session), never a
diagnostic variant (e.g. `data/roofclf_hardneg/`), so the CNN's eventual AUC is directly
comparable to both.

Usage:
    .pixi/envs/ml/bin/python scripts/roofclf_cnn_build_chips.py --chip-px 64
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.roofclf_cnn import CHIP_M_DEFAULT, CHIP_PX_DEFAULT, build_building_chips  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buildings", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--chip-px", type=int, default=CHIP_PX_DEFAULT)
    ap.add_argument("--chip-m", type=float, default=CHIP_M_DEFAULT)
    ap.add_argument("--out-dir", type=Path, default=Path("data/roofclf_cnn"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = build_building_chips(
        args.buildings, args.composites, chip_px=args.chip_px, chip_m=args.chip_m,
        out_dir=args.out_dir,
    )
    print(f"-> {out_dir}")


if __name__ == "__main__":
    main()
