"""Build full-year scene stacks, to give multi-frame fusion more sub-pixel phases.

Multi-frame fusion measured +0.0273 AUC within size band over the dry-season stack
(2026-09-20). Its raw material is sub-pixel diversity between acquisitions, and the
dry-season window supplies only ~12 frames of which about 3 are usefully displaced. Google's
Open Buildings 2.5D Temporal fuses up to 32. More frames means more chances to catch diverse
phases, which is the first of the three levers on that result.

The cost is that a full year reintroduces exactly what the dry-season window exists to
exclude: monsoon cloud, phenology and a wider illumination range. Frames are still
SCL-masked, so cloud removes samples rather than corrupting them, but the fused product is
no longer one epoch -- which matters for anything except this measurement.

Writes `<composites>/stacks_year/<stem>.npz`, same format as `compose_scene_stacks.py`.

    pixi run python scripts/compose_year_stacks.py --aoi pakistan
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np

from earthpv.compose import quadrat_geobox
from earthpv.imagery import scene_stack
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("year_stacks")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--composites", type=Path, default=None)
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--window", default="2025-04-01:2026-03-31")
    ap.add_argument("--max-items", type=int, default=36)
    ap.add_argument("--max-cloud", type=int, default=40)
    ap.add_argument("--margin-m", type=float, default=200.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    composites = args.composites or Path("data/composites") / args.aoi
    window = tuple(args.window.split(":"))
    out_dir = composites / "stacks_year"
    out_dir.mkdir(parents=True, exist_ok=True)
    names = discover_quadrats(args.labels_dir)
    todo = [n for n in names if not (out_dir / f"{n}.npz").exists()]
    if args.limit:
        todo = todo[: args.limit]
    log.info("%d quadrats, %d to build, window %s, up to %d scenes each",
             len(names), len(todo), window, args.max_items)

    done = failed = 0
    for i, stem in enumerate(todo, start=1):
        t0 = time.time()
        try:
            boundary, _ = load_quadrat(stem, args.labels_dir)
            gb = quadrat_geobox(composites, boundary, args.margin_m)
            if gb is None:
                failed += 1
                continue
            gbox, bbox = gb
            res = scene_stack(bbox, date_range=window, max_cloud=args.max_cloud,
                              max_items=args.max_items, geobox=gbox)
            if res is None:
                log.warning("%s: no scenes", stem)
                failed += 1
                continue
            arr, dates, transform, crs = res
            np.savez_compressed(
                out_dir / f"{stem}.npz",
                stack=np.nan_to_num(arr, nan=0.0).clip(0, 65535).astype("uint16"),
                dates=np.array(dates), transform=np.array(transform).reshape(-1)[:6],
                crs=str(crs))
            done += 1
            log.info("[%d/%d] %s: %d scenes (dry-season stack had ~12), %dx%d px, %.0fs",
                     i, len(todo), stem, arr.shape[0], arr.shape[3], arr.shape[2],
                     time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one bad quadrat must not kill the run
            log.warning("%s failed: %s", stem, e)
            failed += 1
    log.info("Wrote %d year stacks, %d failed", done, failed)


if __name__ == "__main__":
    main()
