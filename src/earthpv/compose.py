"""Build Sentinel-2 composites for an AOI's building-populated cells via STAC.

For regions with no local composites (e.g. Punjab), rooftop PV can only exist where
there are roofs, so we composite only 0.1 deg cells that contain buildings - the
meaningful search space - prioritised by building density (cities first). Output
COGs mirror the rooftopsenti layout (`<cell>/composite_0.tif`) so CompositeIndex
and infer consume them unchanged. Resumable: existing cells are skipped.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from tqdm import tqdm

from earthpv.config import Settings
from earthpv.imagery import (
    DEFAULT_RESAMPLING,
    TEMPORAL_STAT_BLOCKS,
    annual_composite,
    temporal_stat_band_names,
)
from earthpv.labels import resolve_aoi
from earthpv.local_source import composite_index, load_buildings, load_solar_labels

log = logging.getLogger(__name__)

CELL_DEG = 0.1


def _fold_name(s: str) -> str:
    """Casefold + strip diacritics, so config names like 'Gujarat' match gazetteer
    transliterations like 'Gujarāt' (geoBoundaries' Indian ADM1 names carry macrons)."""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _aoi_boundary(aoi: str, cfg: dict, settings: Settings) -> gpd.GeoDataFrame | None:
    """Boundary polygon for the AOI. Prefer the AOI-named region (e.g. punjab_500)
    over source_region - source_region supplies imagery/buildings and may cover a
    different, larger area (e.g. pakistan_500 = Balochistan+Sindh).

    AOIs with no local rooftopsenti dataset at all (e.g. a fresh country/state with no
    source_region) fall back to geoBoundaries ADM1: filtered to `division.name` for a
    region, unioned for a whole country. That is what keeps e.g. a "gujarat" AOI's cells
    from spilling into neighbouring states when only a loose bbox is configured.

    **`subtype: country` used to return None here, and a bbox is not a border.** The
    filter read `subtype != "country"`, so every country AOI with no `source_region`
    composited its raw bbox with no clip on either the building pass or the label pass.
    Germany and Pakistan were never exposed (both have a local `boundary.parquet`);
    France, Zambia and Nigeria all were. Measured on France 2026-09-16: 795 of 6,774
    composited cells, 11.7%, sit more than 0.1 deg outside the country - the whole
    lon -5.10 column is Atlantic and Spain, and the 50.0-50.4N band is the Channel and
    England. The label pass leaks harder than the building pass, because VIDA is already
    partitioned per country while `<aoi>_overpass_solar.parquet` is a raw bbox pull:
    only 21.8% of France's is inside France (CLAUDE.md, "A national OSM pull is not
    national until it is clipped to the border"), and `_solar_label_cells` composites a
    cell for each of those features. This is the same class of error as that OSM one,
    one stage earlier.

    The union is **clipped to the configured bbox** before being returned. `populated_cells`
    derives its grid origin from `boundary.total_bounds`, so a country whose ADM1 set
    includes overseas territories (Portugal's Azores, Spain's Canaries, France's Guyane)
    would otherwise move `minx`/`miny` and silently RENAME every cell, orphaning the
    composites already on disk. Verified not to move any current cell name: FRA/NGA/ZMB
    ADM1 bounds all snap back to their configured `grid_origin`.
    """
    cands = [f"{aoi}_500", aoi]
    if cfg.get("source_region"):
        cands.append(cfg["source_region"])
    for cand in cands:
        p = Path(settings.raw["local_root"]) / cand / "aoi" / "boundary.parquet"
        if p.exists():
            return gpd.read_parquet(p).to_crs("EPSG:4326")
    division = cfg.get("division") or {}
    name, iso2, subtype = division.get("name"), division.get("country"), division.get("subtype")
    if name and iso2 and subtype:
        import shapely

        from earthpv.buildings import _iso3_for
        from earthpv.density import fetch_geoboundaries  # deferred: density.py imports this module

        iso3 = _iso3_for(cfg)
        if iso3:
            adm1 = fetch_geoboundaries(iso3, "ADM1")
            if adm1 is not None:
                adm1 = adm1.to_crs("EPSG:4326")
                if subtype == "country":
                    geom = adm1.geometry.union_all()
                else:
                    hit = adm1[adm1.name.map(_fold_name) == _fold_name(name)]
                    if hit.empty:
                        log.warning(
                            "geoBoundaries ADM1 for %s has no region named %r; using raw bbox",
                            iso3, name,
                        )
                        return None
                    geom = hit.geometry.union_all()
                if cfg.get("bbox"):
                    geom = geom.intersection(shapely.box(*cfg["bbox"]))
                if geom.is_empty:
                    log.warning(
                        "geoBoundaries %s for %s does not intersect the configured bbox; "
                        "using raw bbox", subtype, iso3,
                    )
                    return None
                return gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
    return None


def _solar_label_cells(
    aoi: str,
    cfg: dict,
    settings: Settings,
    minx: float,
    miny: float,
    bbox: tuple[float, float, float, float],
    boundary: gpd.GeoDataFrame | None,
    labels_dir: Path = Path("data/labels"),
) -> set[tuple[int, int]]:
    """Cells (same grid/origin as populated_cells) that contain an OSM solar positive.

    Building density finds *unknown* arrays for inference; these guarantee imagery
    over *already-mapped* arrays so each becomes a trainable in-domain positive,
    independent of local building density. Uses the same bbox + boundary clip as the
    building pass so nothing outside the AOI leaks in.

    Two label sources, in order of preference:

    1. The AOI's rooftopsenti `source_region` OSM solar dataset, where one exists.
    2. A local Overpass pull, `<labels_dir>/<aoi>_overpass_solar*.parquet` - the same
       file `chips` trains from (`chips._newest_overpass_path`). This is what makes a
       new country's in-domain retrain possible at all: without it, a mapped ground-
       mount plant sitting in farmland is never composited (no buildings -> no cell),
       so it can never become a training chip no matter how completely OSM has it.
       Measured on Zambia 2026-09-13: 1,568 mapped solar features, most of the large
       ones in cells far below any sane `--min-buildings` threshold.

    With neither, this degrades to no label cells rather than attempting a direct
    Overture S3 query, which times out from this machine (see CLAUDE.md). Inference
    coverage (via building density) is unaffected either way.
    """
    labels = None
    if cfg.get("source_region"):
        region_dir = Path(settings.raw["local_root"]) / cfg["source_region"]
        labels = load_solar_labels(region_dir)
    if labels is None or labels.empty:
        from earthpv.chips import _newest_overpass_path

        overpass_path = _newest_overpass_path(aoi, Path(labels_dir))
        if not overpass_path.exists():
            return set()
        log.info("Solar label cells from Overpass pull %s", overpass_path)
        labels = gpd.read_parquet(overpass_path)
    if labels is None or labels.empty:
        return set()
    pts = labels.geometry.representative_point()
    xmin, ymin, xmax, ymax = bbox
    inb = (pts.x >= xmin) & (pts.x <= xmax) & (pts.y >= ymin) & (pts.y <= ymax)
    pts = gpd.GeoDataFrame(geometry=pts[inb].values, crs="EPSG:4326")
    if boundary is not None and not pts.empty:
        pts = gpd.sjoin(pts, boundary[["geometry"]], predicate="within", how="inner")
    if pts.empty:
        return set()
    ix = np.floor((pts.geometry.x.values - minx) / CELL_DEG).astype(int)
    iy = np.floor((pts.geometry.y.values - miny) / CELL_DEG).astype(int)
    return set(zip(ix.tolist(), iy.tolist()))


def populated_cells(
    aoi: str, cfg: dict, settings: Settings, min_buildings: int, include_labels: bool = True,
    use_vida: bool = False,
) -> pd.DataFrame:
    """0.1 deg cells within the AOI to composite, sorted by building density.

    A cell is selected if it has >= min_buildings buildings OR (when include_labels)
    it contains an OSM solar polygon - so density coverage for finding new arrays is
    unioned with full imagery coverage over every already-mapped one. Buildings are
    clipped to the AOI polygon (not just its bbox) so neighbouring provinces' cities
    in the shared building set don't leak in.

    `use_vida=True` forces VIDA Open Buildings for cell selection even when the AOI has
    a `source_region` - the local rooftopsenti building set is Overture-only, filtered
    to >= 500 m2, so it silently undercounts by 2-3 orders of magnitude wherever small
    (mostly residential) structures dominate and aren't individually mapped in OSM.
    VIDA is imagery-derived and doesn't have that gap.
    """
    boundary = _aoi_boundary(aoi, cfg, settings)
    bbox = tuple(boundary.total_bounds) if boundary is not None else tuple(cfg["bbox"])
    minx, miny = bbox[0], bbox[1]
    # Optional grid anchor: snap the cell grid so it is congruent (mod CELL_DEG) with
    # another AOI's grid, letting already-composited cells be reused by renaming
    # (e.g. pakistan anchors to punjab's origin to reuse its 64 cells).
    if cfg.get("grid_origin"):
        gx, gy = cfg["grid_origin"]
        minx = gx + np.floor((minx - gx) / CELL_DEG) * CELL_DEG
        miny = gy + np.floor((miny - gy) / CELL_DEG) * CELL_DEG
    bbox = (minx, miny, bbox[2], bbox[3])
    minx, miny, maxx, maxy = bbox
    if cfg.get("source_region") and not use_vida:
        buildings = load_buildings(Path(settings.raw["local_root"]) / cfg["source_region"])
        rep = buildings.geometry.representative_point()
        bx_all, by_all = rep.x.values, rep.y.values
    else:
        # No local rooftopsenti dataset for this AOI (e.g. a new country/state), or VIDA
        # was explicitly requested - fetch VIDA Open Buildings directly, bbox-pruned, the
        # same source density.py already uses per-cell. Uses the local cached parquet
        # (data/vida/<iso3>.parquet) if present, else a bbox-pruned remote scan.
        #
        # Country-scale VIDA scans (Pakistan: 76M+ buildings) OOM if decoded into full
        # shapely polygons (fetch_vida_buildings): use the lightweight point-only path,
        # which reads the parquet's `bbox` struct and never touches WKB/GEOS.
        from earthpv import overture
        from earthpv.buildings import _iso3_for, fetch_vida_building_points

        iso3 = _iso3_for(cfg)
        if not iso3:
            raise ValueError(
                f"AOI '{aoi}' has no source_region and no resolvable division.country "
                "-> cannot locate buildings for cell selection."
            )
        log.info(
            "%s buildings for '%s' (%s)", "Forcing VIDA" if use_vida else "No local source_region;"
            " fetching VIDA", aoi, iso3,
        )
        pts_df = fetch_vida_building_points(bbox, iso3, con=overture.connect())
        bx_all, by_all = pts_df["lon"].values, pts_df["lat"].values
    inb = (bx_all >= minx) & (bx_all <= maxx) & (by_all >= miny) & (by_all <= maxy)
    bx, by = bx_all[inb], by_all[inb]
    if boundary is not None:
        # shapely's vectorized point-in-polygon test operates on plain float arrays, so
        # tens of millions of buildings never need a Point object or GeoDataFrame built.
        import shapely

        within = shapely.contains_xy(boundary.geometry.union_all(), bx, by)
        bx, by = bx[within], by[within]
    ix = np.floor((bx - minx) / CELL_DEG).astype(int)
    iy = np.floor((by - miny) / CELL_DEG).astype(int)
    cells = pd.DataFrame({"ix": ix, "iy": iy}).value_counts().reset_index(name="n")

    label_cells = (
        _solar_label_cells(aoi, cfg, settings, minx, miny, bbox, boundary)
        if include_labels
        else set()
    )
    has_label = (
        np.array([(a, b) in label_cells for a, b in zip(cells.ix, cells.iy)], dtype=bool)
        if label_cells
        else np.zeros(len(cells), dtype=bool)
    )
    n_by_density = int((cells.n >= min_buildings).sum())
    cells = cells[(cells.n >= min_buildings) | has_label].reset_index(drop=True)
    # Label cells with no mapped buildings at all are absent from the histogram; add them.
    extra = sorted(label_cells - set(zip(cells.ix, cells.iy)))
    if extra:
        cells = pd.concat(
            [cells, pd.DataFrame({"ix": [a for a, _ in extra], "iy": [b for _, b in extra], "n": 0})],
            ignore_index=True,
        )
    cells["lon0"] = minx + cells.ix * CELL_DEG
    cells["lat0"] = miny + cells.iy * CELL_DEG
    if include_labels:
        log.info(
            "Selected %d cells: %d by density (>=%d buildings), %d contain OSM solar labels",
            len(cells), n_by_density, min_buildings, len(label_cells),
        )
    if label_cells:
        # Composite label cells (which hold the OSM solar positives = the training data)
        # BEFORE density-only cells (which only add inference coverage), each ordered by
        # density. On a slow/partial run this makes the full training set available without
        # waiting for the whole country to composite.
        cells["_lbl"] = [(a, b) not in label_cells for a, b in zip(cells.ix, cells.iy)]
        cells = cells.sort_values(["_lbl", "n"], ascending=[True, False])
        cells = cells.drop(columns="_lbl").reset_index(drop=True)
    else:
        cells = cells.sort_values("n", ascending=False).reset_index(drop=True)
    return cells


COMPOSITE_BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]


def temporal_stats_path(cell_dir: Path, index: int = 0) -> Path:
    """Sidecar path for a cell's temporal statistics.

    A SIDECAR, not extra bands on `composite_<i>.tif`: that file's 10-band layout is the
    contract `CompositeIndex`, `infer`, `postprocess`, `density` and `roofclf` all read,
    and it is shared with the sibling rooftopsenti project. Widening it would break every
    one of them; a separate file is purely additive, and a cell that has no sidecar simply
    has no temporal features.
    """
    return cell_dir / f"temporal_stats_{index}.tif"


def write_temporal_stats(
    path: Path, stats: np.ndarray, transform, crs, window: tuple[str, str] | None
) -> None:
    """Write a temporal-stats sidecar, via a .tmp rename like the composites themselves.

    The window is recorded in TIFF tags. Which dates a composite was built from is
    otherwise unrecoverable from the file, and these statistics are only comparable
    against a median built from the same scenes.
    """
    tmp = path.with_suffix(".tif.tmp")
    with rasterio.open(
        tmp, "w", driver="GTiff", width=stats.shape[2], height=stats.shape[1],
        count=stats.shape[0], dtype="uint16", crs=crs, transform=transform,
        compress="deflate", predictor=2,
    ) as dst:
        dst.write(stats)
        dst.descriptions = tuple(temporal_stat_band_names(COMPOSITE_BANDS))
        dst.update_tags(
            earthpv_window=":".join(window) if window else "default",
            earthpv_stat_blocks=",".join(TEMPORAL_STAT_BLOCKS) + ",n_obs",
        )
    tmp.rename(path)


def existing_resampling(out_dir: Path) -> str | None:
    """The resampling an AOI's existing composites were built with, or None if there are none.

    A composite written before 2026-09-19 carries no `earthpv_resampling` tag, and every
    one of those is "nearest". This exists so a resumable run cannot quietly append
    bilinear cells to a nearest corpus: the difference is small, systematic, and exactly
    the kind of domain shift that shows up later as an unexplained calibration drift.
    """
    for tif in sorted(out_dir.glob("*/composite_0.tif"))[:1]:
        try:
            with rasterio.open(tif) as src:
                return src.tags().get("earthpv_resampling", "nearest")
        except rasterio.errors.RasterioIOError:
            return None
    return None


def quadrat_geobox(composites: Path, boundary, margin_m: float = 200.0):
    """GeoBox over a quadrat's bbox, snapped to its parent composite's pixel grid.

    Snapping matters: it is what keeps the sidecar's p50 band comparable, pixel for pixel,
    with `composite_0.tif`'s median, which is the check that rules out the two being built
    from different scene sets. Returns `(geobox, bbox4326)` or None if uncovered.
    """
    import numpy as np
    import rasterio.warp
    from odc.geo.geobox import GeoBox
    from shapely.geometry import box

    idx = composite_index(str(composites), layers=1)
    hits = idx.index[idx.index.intersects(box(*boundary.bounds))]
    if hits.empty:
        return None
    with rasterio.open(hits.iloc[0].path) as src:
        crs, tr = src.crs, src.transform
        xs, ys = rasterio.warp.transform(
            "EPSG:4326", crs,
            [boundary.bounds[0], boundary.bounds[2]], [boundary.bounds[1], boundary.bounds[3]],
        )
    minx, maxx = min(xs) - margin_m, max(xs) + margin_m
    miny, maxy = min(ys) - margin_m, max(ys) + margin_m
    px = abs(tr.a)
    # Snap outwards onto the parent grid (tr.c/tr.f are its origin).
    minx = tr.c + np.floor((minx - tr.c) / px) * px
    maxy = tr.f - np.floor((tr.f - maxy) / px) * px
    w = int(np.ceil((maxx - minx) / px))
    h = int(np.ceil((maxy - miny) / px))
    gbox = GeoBox((h, w), rasterio.Affine(px, 0, minx, 0, -px, maxy), crs)
    bbox = rasterio.warp.transform_bounds(crs, "EPSG:4326", minx, maxy - h * px, minx + w * px, maxy)
    return gbox, bbox


def run_compose(
    aoi: str,
    out_dir: Path,
    min_buildings: int = 1000,
    limit: int = 0,
    window: tuple[str, str] | None = None,
    index: int = 0,
    workers: int = 1,
    include_labels: bool = True,
    use_vida: bool = False,
    stats: bool = False,
    resampling: str | None = None,
) -> Path:
    """`window`/`index` build an extra seasonal layer (`composite_<index>.tif`, e.g.
    a post-monsoon contrast season) into the same cell dirs as the base run.

    `workers` > 1 composites cells concurrently. The work is I/O-bound (remote STAC
    scene reads), so threads overlap the network waits for a near-linear speedup;
    the STAC search is serialized internally (annual_composite) for thread safety.

    `resampling` picks how the native-20 m bands reach the 10 m grid (see
    `imagery.BAND_RESAMPLING`) and is stamped into every composite this writes. Leave it
    None and the AOI decides: a directory that already holds composites keeps whatever
    they were built with, and only a fresh AOI gets the current default. That is what
    stops a resumable run from appending bilinear cells to a nearest corpus, which no
    docstring warning would have prevented -- `compose` is re-invoked in a restart loop
    for a country-scale run, so the FIRST pass after a default changes is where it would
    have happened. An explicit value overrides the inheritance and warns if it conflicts.

    `stats` also writes `temporal_stats_<index>.tif` per cell (see `write_temporal_stats`).
    Two consequences worth knowing before running it at scale. It roughly quadruples
    per-cell disk, and it makes the stage compute- and memory-hungry as well as
    bandwidth-bound (~2.2 GB peak RSS per concurrent cell, measured), so keep `workers`
    low. And a cell whose composite already exists is NOT skipped when its sidecar is
    missing: the scenes are re-read to build it, and the existing composite is left
    exactly as it was rather than rewritten, because the on-disk one may have been built
    from a different scene availability and downstream products already rest on it.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if index > 0 and window is None:
        raise ValueError("compose --index > 0 requires --window (the layer's date range)")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    # An AOI may pin its own base-layer window (`compose_window`). France does, because its
    # calibration labels were drawn on 2023-2024 imagery and a national run on a different
    # epoch than the quadrat cells would silently mix two epochs into one product -- the
    # resumable skip means the already-built cells keep whatever window they were made
    # with. An explicit --window still wins, and index > 0 layers are unaffected.
    if window is None and index == 0 and cfg.get("compose_window"):
        window = tuple(cfg["compose_window"])
        log.info("Using AOI compose_window %s for %s", window, aoi)
    # Mirror the rooftopsenti layout (<region>/composites/<cell>/composite_0.tif) so
    # CompositeIndex reads it unchanged.
    region_dir = Path(out_dir) / aoi
    out_dir = region_dir / "composites"
    out_dir.mkdir(parents=True, exist_ok=True)

    found = existing_resampling(out_dir)
    if resampling is None:
        resampling = found or DEFAULT_RESAMPLING
        if found:
            log.info("Inheriting resampling=%s from the %d composites already in %s",
                     resampling, len(list(out_dir.glob("*/composite_0.tif"))), out_dir)
        else:
            log.info("Fresh AOI: using resampling=%s", resampling)
    elif found and found != resampling:
        log.warning(
            "MIXING RESAMPLING: %s already holds composites built with %r and this run was "
            "told %r. The two are not interchangeable -- recompose the AOI wholesale or "
            "pass --resampling %s.", out_dir, found, resampling, found,
        )

    cells = populated_cells(aoi, cfg, settings, min_buildings, include_labels, use_vida)
    if limit:
        cells = cells.head(limit)
    log.info("Compositing %d cells (>= %d buildings) for %s (%d workers)",
             len(cells), min_buildings, aoi, workers)

    def _one(cell) -> bool:
        name = f"{int(cell.ix):04d}_{int(cell.iy):04d}"
        cell_dir = out_dir / name
        tif = cell_dir / f"composite_{index}.tif"
        sidecar = temporal_stats_path(cell_dir, index)
        have_composite = tif.exists()
        if have_composite and (not stats or sidecar.exists()):
            return False
        bbox = (cell.lon0, cell.lat0, cell.lon0 + CELL_DEG, cell.lat0 + CELL_DEG)
        try:
            if have_composite:
                # Sidecar-only pass: pin the stats to the existing composite's exact grid
                # so the two are pixel-aligned, and never touch the composite itself.
                from odc.geo.geobox import GeoBox

                with rasterio.open(tif) as b:
                    gbox = GeoBox((b.height, b.width), b.transform, b.crs)
                kw = dict(geobox=gbox, with_stats=True, resampling=resampling)
                if window:
                    kw["date_range"] = window
                if index > 0:
                    kw["max_cloud"] = 60
                res = annual_composite(bbox, **kw)
                if res is None:
                    log.warning("cell %s: no scenes for stats sidecar", name)
                    return False
                _, transform, crs, stats_arr = res
                write_temporal_stats(sidecar, stats_arr, transform, crs, window)
                return True
            if index > 0:
                # Pin the extra layer to the base layer's exact grid.
                base = cell_dir / "composite_0.tif"
                if not base.exists():
                    log.warning("cell %s: no base composite for layer %d", name, index)
                    return False
                from odc.geo.geobox import GeoBox

                with rasterio.open(base) as b:
                    gbox = GeoBox((b.height, b.width), b.transform, b.crs)
                res = annual_composite(bbox, date_range=window, geobox=gbox, max_cloud=60,
                                       with_stats=stats, resampling=resampling)
            else:
                kw = dict(with_stats=stats, resampling=resampling)
                if window:
                    kw["date_range"] = window
                res = annual_composite(bbox, **kw)
        except Exception as e:  # noqa: BLE001 - one bad cell must not kill the run
            log.warning("cell %s failed: %s", name, e)
            return False
        if res is None:
            log.warning("cell %s: no scenes", name)
            return False
        stats_arr = None
        if stats:
            arr, transform, crs, stats_arr = res
        else:
            arr, transform, crs = res
        cell_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temp then rename so a killed run never leaves a half-written COG
        # that the resumable skip would treat as done.
        tmp = tif.with_suffix(".tif.tmp")
        with rasterio.open(
            tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
            dtype="uint16", crs=crs, transform=transform, compress="deflate", predictor=2,
        ) as dst:
            dst.write(arr)
            dst.descriptions = tuple(
                ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
            )
            # Which resampling built this cell. A composite with no such tag predates
            # 2026-09-19 and is "nearest".
            dst.update_tags(earthpv_resampling=resampling,
                            earthpv_window=":".join(window) if window else "default")
        tmp.rename(tif)
        if stats_arr is not None:
            write_temporal_stats(sidecar, stats_arr, transform, crs, window)
        return True

    rows = [cell for _, cell in cells.iterrows()]
    done = 0
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ok in tqdm(ex.map(_one, rows), total=len(rows), desc="compose"):
                done += int(ok)
    else:
        for cell in tqdm(rows, desc="compose"):
            done += int(_one(cell))
    log.info("Composited %d new cells -> %s", done, out_dir)
    return region_dir
