"""Save the per-scene stack each quadrat's composite is reduced from.

Temporal unmixing needs the scenes, not their median: it estimates a pixel's PV areal
fraction from how much its temporal spread is DAMPED relative to its local background
(`preprocess.temporal_unmix_fields`). The median composite and the temporal-statistics
sidecar both discard exactly that.

Writes `<composites>/stacks/<stem>.npz` per quadrat, on the parent composite's pixel grid,
with masked observations stored as 0 (the project's existing fill convention). Resumable.

    pixi run python scripts/compose_scene_stacks.py --aoi pakistan
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

log = logging.getLogger("compose_scene_stacks")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--composites", type=Path, default=None)
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--quadrat", action="append", default=None)
    ap.add_argument("--window", default="")
    ap.add_argument("--margin-m", type=float, default=200.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    composites = args.composites or Path("data/composites") / args.aoi
    window = tuple(args.window.split(":")) if args.window else None
    names = args.quadrat or discover_quadrats(args.labels_dir)
    out_dir = composites / "stacks"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not (out_dir / f"{n}.npz").exists()]
    log.info("%d quadrats, %d already done, %d to build -> %s",
             len(names), len(names) - len(todo), len(todo), out_dir)
    if args.limit:
        todo = todo[: args.limit]

    done = failed = 0
    for i, stem in enumerate(todo, start=1):
        t0 = time.time()
        try:
            boundary, _ = load_quadrat(stem, args.labels_dir)
            gb = quadrat_geobox(composites, boundary, args.margin_m)
            if gb is None:
                log.warning("quadrat %s: no composite tile covers it", stem)
                failed += 1
                continue
            gbox, bbox = gb
            kw = {"geobox": gbox}
            if window:
                kw["date_range"] = window
            res = scene_stack(bbox, **kw)
            if res is None:
                log.warning("quadrat %s: no scenes", stem)
                failed += 1
                continue
            arr, dates, transform, crs = res
            # NaN (cloud-masked or failed read) -> 0, matching COMPOSITE_FILL, so the file
            # is a plain uint16 array and the reader restores NaN from it.
            store = np.nan_to_num(arr, nan=0.0).clip(0, 65535).astype("uint16")
            np.savez_compressed(
                out_dir / f"{stem}.npz", stack=store, dates=np.array(dates),
                transform=np.array(transform).reshape(-1)[:6], crs=str(crs),
            )
            done += 1
            log.info("[%d/%d] %s: %d scenes x %d bands, %dx%d px, %.1f MB, %.0fs",
                     i, len(todo), stem, store.shape[0], store.shape[1],
                     store.shape[3], store.shape[2],
                     (out_dir / f"{stem}.npz").stat().st_size / 1e6, time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one bad quadrat must not kill the run
            log.warning("quadrat %s failed: %s", stem, e)
            failed += 1
    log.info("Wrote %d stacks, %d failed", done, failed)


if __name__ == "__main__":
    main()
