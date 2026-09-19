"""Write temporal-statistics sidecars for the cells the calibration quadrats sit in.

`earthpv compose --stats` selects cells nationally by building density, which is the wrong
selection for a quadrat ablation: the 30 Pakistani quadrats occupy about 30 cells out of
4,473, and recomposing the country to measure a feature block would cost ~215 GB and days
of bandwidth. This walks the quadrat boundaries instead, finds the composite tiles they
actually fall in, and writes only those sidecars.

Two extents, and the default is the cheap one:

  --extent quadrat  (default)  one `<composites>/temporal_stats/<stem>.tif` per quadrat,
      covering the quadrat bbox plus a margin. A quadrat is 1-4 km2 inside a ~110 km2
      cell, and only the quadrat carries labels, so this reads roughly 30x less for
      exactly the same measurement. MEASURED on a machine sharing its link with a national
      compose: 21 minutes per full cell against about a minute per quadrat.
  --extent cell                one `temporal_stats_0.tif` per composite cell, i.e. the
      artifact a national scoring pass would need. ~48 MB and a full cell's bandwidth each.

Either way the output is snapped to the parent `composite_0.tif` pixel grid, so the
sidecar's p50 band is directly comparable to the composite's median -- verified
bit-identical on 100% of valid pixels for cell 0116_0102. The composite is never
rewritten.

    pixi run python scripts/compose_temporal_stats.py --aoi pakistan

Resumable: an existing output is skipped, so a killed run costs only its current unit.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import rasterio
import rasterio.warp

from earthpv.compose import quadrat_geobox, temporal_stats_path, write_temporal_stats
from earthpv.imagery import annual_composite
from earthpv.local_source import composite_index
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("compose_temporal_stats")


def quadrat_tiles(composites: Path, names: list[str], labels_dir: Path) -> list[Path]:
    """Composite tiles (composite_0.tif paths) that any quadrat boundary touches."""
    from shapely.geometry import box

    idx = composite_index(str(composites), layers=1)
    tiles: dict[str, None] = {}
    for n in names:
        boundary, _ = load_quadrat(n, labels_dir)
        hits = idx.index[idx.index.intersects(box(*boundary.bounds))]
        if hits.empty:
            log.warning("quadrat %s: no composite tile covers it", n)
            continue
        for p in hits.path:
            tiles.setdefault(p, None)
    return [Path(p) for p in tiles]


def run_quadrat_extent(
    composites: Path, names: list[str], labels_dir: Path,
    window: tuple[str, str] | None, margin_m: float, limit: int,
) -> None:
    """One clipped sidecar per quadrat under `<composites>/temporal_stats/<stem>.tif`."""
    out_dir = composites / "temporal_stats"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [n for n in names if not (out_dir / f"{n}.tif").exists()]
    log.info("%d quadrats, %d already done, %d to build -> %s",
             len(names), len(names) - len(todo), len(todo), out_dir)
    if limit:
        todo = todo[:limit]

    done = failed = 0
    for i, stem in enumerate(todo, start=1):
        t0 = time.time()
        try:
            boundary, _ = load_quadrat(stem, labels_dir)
            gb = quadrat_geobox(composites, boundary, margin_m)
            if gb is None:
                log.warning("quadrat %s: no composite tile covers it", stem)
                failed += 1
                continue
            gbox, bbox = gb
            kw = {"geobox": gbox, "with_stats": True}
            if window:
                kw["date_range"] = window
            res = annual_composite(bbox, **kw)
            if res is None:
                log.warning("quadrat %s: no scenes", stem)
                failed += 1
                continue
            _, transform, crs, stats = res
            write_temporal_stats(out_dir / f"{stem}.tif", stats, transform, crs, window)
            done += 1
            log.info("[%d/%d] %s: %d bands, %dx%d px, %.0fs", i, len(todo), stem,
                     stats.shape[0], stats.shape[2], stats.shape[1], time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one bad quadrat must not kill the run
            log.warning("quadrat %s failed: %s", stem, e)
            failed += 1
    log.info("Wrote %d quadrat sidecars, %d failed", done, failed)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--composites", type=Path, default=None,
                    help="default: data/composites/<aoi>")
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--quadrat", action="append", default=None,
                    help="repeatable; default every discoverable quadrat")
    ap.add_argument("--window", default="",
                    help="'YYYY-MM-DD:YYYY-MM-DD'; default = annual_composite's own")
    ap.add_argument("--limit", type=int, default=0, help="cap units (0 = all)")
    ap.add_argument("--extent", choices=("quadrat", "cell"), default="quadrat",
                    help="quadrat: one clipped sidecar per quadrat (default, ~30x cheaper). "
                         "cell: one full-cell sidecar per composite cell.")
    ap.add_argument("--margin-m", type=float, default=200.0,
                    help="margin around a quadrat boundary, --extent quadrat (default 200)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    composites = args.composites or Path("data/composites") / args.aoi
    window = tuple(args.window.split(":")) if args.window else None
    names = args.quadrat or discover_quadrats(args.labels_dir)
    if not names:
        raise SystemExit(f"No calibration quadrats found in {args.labels_dir}")
    log.info("%d quadrats -> scanning %s", len(names), composites)

    if args.extent == "quadrat":
        run_quadrat_extent(composites, names, args.labels_dir, window, args.margin_m,
                           args.limit)
        return

    tiles = quadrat_tiles(composites, names, args.labels_dir)
    todo = [t for t in tiles if not temporal_stats_path(t.parent).exists()]
    log.info("%d quadrat cells, %d already have a sidecar, %d to build",
             len(tiles), len(tiles) - len(todo), len(todo))
    if args.limit:
        todo = todo[: args.limit]

    from odc.geo.geobox import GeoBox

    done = failed = 0
    for i, tif in enumerate(todo, start=1):
        name = tif.parent.name
        t0 = time.time()
        try:
            with rasterio.open(tif) as b:
                gbox = GeoBox((b.height, b.width), b.transform, b.crs)
                bbox = rasterio.warp.transform_bounds(b.crs, "EPSG:4326", *b.bounds)
            kw = {"geobox": gbox, "with_stats": True}
            if window:
                kw["date_range"] = window
            res = annual_composite(bbox, **kw)
            if res is None:
                log.warning("cell %s: no scenes", name)
                failed += 1
                continue
            _, transform, crs, stats = res
            write_temporal_stats(temporal_stats_path(tif.parent), stats, transform, crs, window)
            done += 1
            log.info("[%d/%d] %s: %d bands, %.0fs", i, len(todo), name, stats.shape[0],
                     time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one bad cell must not kill the run
            log.warning("cell %s failed: %s", name, e)
            failed += 1
    log.info("Wrote %d sidecars, %d failed", done, failed)


if __name__ == "__main__":
    main()
