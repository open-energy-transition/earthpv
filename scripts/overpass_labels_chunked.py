"""Country-scale OSM solar pull, split into a bbox grid.

`earthpv overpass-labels --bbox <country>` issues one `out meta geom` query over the
whole bbox, and every public Overpass mirror 504s on that for a country-sized area
(measured on Zambia 2026-09-13: all three endpoints in `overpass.OVERPASS_ENDPOINTS`
timed out, at 180 s and again at 300 s, for a region holding only ~1,570 features --
the cost is the area scanned, not the answer returned). `docs/reproduce.md` already
says to chunk such a pull by province; this does it by a regular grid instead, so it
needs no admin boundaries and no per-country tuning.

Each tile is fetched with `overpass.fetch_solar_overpass`, which raises rather than
returning a partial answer when a mirror truncates (`OverpassTruncated`), so a tile
either lands whole or is retried. Features are then deduplicated on OSM `id` -- a way
straddling a tile edge is returned by both neighbours -- and pushed through the same
`classify_placement` + `geodesic_area_m2` step `build_overpass_labels` uses, so the
output is byte-for-byte the same schema the single-shot path writes.

**Tiles are cached and a rerun resumes.** Each landed tile is written to
`<out-dir>/.overpass_tiles/<name>_<COLSxROWS>/<i>_<j>.parquet` (an empty tile as a
zero-row file), and a rerun with the same `--bbox`/`--tiles` skips every cached tile. A
national India pull is ~190 tiles against mirrors that 504 for minutes at a time
(measured 2026-09-23); without this one persistent failure meant refetching the whole
country. `--fresh` ignores the cache. The refuse-to-write-a-partial-pull rule is
unchanged: the national file is only written once every tile has landed.

    pixi run python scripts/overpass_labels_chunked.py \
        --bbox 21.999,-18.08,33.706,-8.224 --iso3 ZMB --name zambia --tiles 4x4
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

log = logging.getLogger("overpass_chunked")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bbox", required=True, help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--iso3", required=True,
                    help="ISO3; routes placement lookups to data/vida/<ISO3>.parquet")
    ap.add_argument("--name", required=True,
                    help="output stem: data/labels/<name>_overpass_solar.parquet")
    ap.add_argument("--tiles", default="4x4", help="grid as COLSxROWS (default 4x4)")
    ap.add_argument("--timeout", type=int, default=180, help="per-tile Overpass timeout (s)")
    ap.add_argument("--retries", type=int, default=4, help="attempts per tile before giving up")
    ap.add_argument("--out-dir", type=Path, default=REPO / "data" / "labels")
    ap.add_argument("--fetch-only", action="store_true",
                    help="stop once every tile is cached, before the national clip and the "
                    "VIDA placement step (lets the Overpass half run while VIDA downloads)")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore cached tiles from an earlier run and refetch everything")
    ap.add_argument(
        "--no-clip", action="store_true",
        help="Keep features outside the country. Off by default: a country bbox is not "
        "the country, and a grid tile in a corner can return a neighbour's capital "
        "(measured on Zambia 2026-09-13: the SE tile returned 987 features, nearly all "
        "Zimbabwean).",
    )
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv import overture
    from earthpv.config import Settings
    from earthpv.labels import classify_placement, geodesic_area_m2
    from earthpv.overpass import fetch_solar_overpass

    minx, miny, maxx, maxy = (float(v) for v in a.bbox.split(","))
    ncol, nrow = (int(v) for v in a.tiles.lower().split("x"))
    dx, dy = (maxx - minx) / ncol, (maxy - miny) / nrow

    # The cache key carries the bbox, so a different grid can never read stale tiles.
    key = f"{a.name}_{ncol}x{nrow}_" + "_".join(f"{v:.4f}" for v in (minx, miny, maxx, maxy))
    tile_dir = a.out_dir / ".overpass_tiles" / key
    tile_dir.mkdir(parents=True, exist_ok=True)

    frames, failed = [], []
    for j in range(nrow):
        for i in range(ncol):
            tile = (minx + i * dx, miny + j * dy, minx + (i + 1) * dx, miny + (j + 1) * dy)
            label = f"{i},{j}"
            cached = tile_dir / f"{i}_{j}.parquet"
            if cached.exists() and not a.fresh:
                gdf = gpd.read_parquet(cached)
                log.info("tile %s: %d features (cached)", label, len(gdf))
                if not gdf.empty:
                    frames.append(gdf)
                continue
            for attempt in range(1, a.retries + 1):
                try:
                    gdf = fetch_solar_overpass(bbox=tile, timeout=a.timeout)
                    log.info("tile %s %s: %d features", label,
                             tuple(round(v, 3) for v in tile), len(gdf))
                    tmp = cached.with_suffix(".tmp")
                    (gdf if not gdf.empty else gpd.GeoDataFrame(
                        geometry=[], crs="EPSG:4326")).to_parquet(tmp)
                    tmp.replace(cached)
                    if not gdf.empty:
                        frames.append(gdf)
                    break
                except Exception as e:  # noqa: BLE001 - a tile that will not land is information
                    log.warning("tile %s attempt %d/%d failed: %s", label, attempt, a.retries, e)
                    time.sleep(10 * attempt)
            else:
                failed.append(label)

    if failed:
        # Never write a partial national pull silently: an incomplete reference reads
        # downstream as "the model found things OSM does not have", i.e. as precision
        # loss, and nothing in the pipeline can tell the difference.
        log.error("tiles that never landed: %s -- refusing to write a partial pull", failed)
        return 1
    if not frames:
        log.error("no solar features anywhere in %s", a.bbox)
        return 1
    if a.fetch_only:
        log.info("--fetch-only: all %d tiles cached in %s; rerun without it to finish",
                 ncol * nrow, tile_dir)
        return 0

    solar = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    before = len(solar)
    solar = solar.drop_duplicates(subset="id").reset_index(drop=True)
    log.info("%d features, %d after de-duplicating tile overlaps", before, len(solar))

    if not a.no_clip:
        # A bbox big enough to hold the country also holds slabs of its neighbours.
        # Clip on geoBoundaries ADM1 (unioned), the same source `density` aggregates to,
        # so the national pull describes the country the atlas will publish.
        from earthpv.density import fetch_geoboundaries

        adm1 = fetch_geoboundaries(a.iso3, "ADM1")
        if adm1 is None:
            log.warning("no geoBoundaries ADM1 for %s -- keeping the raw bbox pull", a.iso3)
        else:
            import shapely

            country = adm1.to_crs("EPSG:4326").geometry.union_all()
            rep = solar.geometry.representative_point()
            inside = shapely.contains_xy(country, rep.x.values, rep.y.values)
            log.info(
                "clipped to %s: %d of %d features inside the national boundary",
                a.iso3, int(inside.sum()), len(solar),
            )
            solar = solar[inside].reset_index(drop=True)
            if solar.empty:
                log.error("nothing left after the national clip")
                return 1

    settings = Settings.load()
    con = overture.connect()
    solar = classify_placement(solar, con, settings, settings.rooftop_overlap_frac, iso3=a.iso3)
    solar["area_m2"] = [geodesic_area_m2(g) for g in solar.geometry]
    solar["geom_type"] = solar.geom_type

    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / f"{a.name}_overpass_solar.parquet"
    solar.to_parquet(out)
    n_poly = int(((solar.geom_type != "Point") & (solar.area_m2 >= 10)).sum())
    log.info(
        "Wrote %s: %d features | polygons>=10m2: %d | rooftop: %d | ground: %d | unknown: %d",
        out, len(solar), n_poly,
        int((solar.placement == "rooftop").sum()),
        int((solar.placement == "ground").sum()),
        int((solar.placement == "unknown").sum()),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
