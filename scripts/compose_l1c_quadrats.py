"""Build top-of-atmosphere (L1C) composites over the calibration quadrats.

The control for "is Sen2Cor's surface-reflectance retrieval hurting us?" -- see
`imagery.l1c_composite` for why a specular dark target is the worst case for an
atmospheric correction that assumes a Lambertian one.

Writes `<composites>/l1c/<stem>.tif`, one per quadrat, on the parent composite's pixel
grid so the L1C and L2A feature tables describe identical footprint pixels and the only
difference is the processing level. Resumable.

    pixi run python scripts/compose_l1c_quadrats.py --aoi pakistan
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import rasterio

from earthpv.compose import COMPOSITE_BANDS, quadrat_geobox
from earthpv.imagery import l1c_composite
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("compose_l1c_quadrats")


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
    out_dir = composites / "l1c"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not (out_dir / f"{n}.tif").exists()]
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
            res = l1c_composite(bbox, **kw)
            if res is None:
                log.warning("quadrat %s: no usable L1C scenes", stem)
                failed += 1
                continue
            arr, transform, crs = res
            tmp = (out_dir / f"{stem}.tif").with_suffix(".tif.tmp")
            with rasterio.open(
                tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1],
                count=arr.shape[0], dtype="uint16", crs=crs, transform=transform,
                compress="deflate", predictor=2,
            ) as dst:
                dst.write(arr)
                dst.descriptions = tuple(COMPOSITE_BANDS)
                dst.update_tags(earthpv_level="L1C-TOA",
                                earthpv_window=":".join(window) if window else "default")
            tmp.rename(out_dir / f"{stem}.tif")
            done += 1
            log.info("[%d/%d] %s: %dx%d px, %.0fs", i, len(todo), stem,
                     arr.shape[2], arr.shape[1], time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one bad quadrat must not kill the run
            log.warning("quadrat %s failed: %s", stem, e)
            failed += 1
    log.info("Wrote %d L1C quadrat composites, %d failed", done, failed)


if __name__ == "__main__":
    main()
