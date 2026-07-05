"""Dense building footprints for candidate re-ranking.

The rooftopsenti local building set is Overture-only, filtered to >= 500 m2, so it
only knows *large, already-mapped* buildings. For an unmapped-sprawl target like
Punjab that makes "no building nearby" ambiguous (real FP vs. real-but-unmapped
roof). VIDA's Google+Microsoft Open Buildings layer is imagery-derived and covers
small/unmapped structures, which turns building proximity into a usable prior.

Fetched once per AOI (bbox-filtered) via DuckDB httpfs and cached to a local
GeoParquet; the S3/Overture path stays the fallback for AOIs with no VIDA cache.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
from tqdm import tqdm

from earthpv import overture
from earthpv.config import Settings

log = logging.getLogger(__name__)

# Single HTTPS GeoParquet per country (no S3 auth / no per-cell round trips), so a
# bbox-filtered pull is a single scan. iso3 is substituted per AOI division country.
VIDA_URL = (
    "https://data.source.coop/vida/google-microsoft-open-buildings/"
    "geoparquet/by_country/country_iso={iso3}/{iso3}.parquet"
)
# Full-country download of the file above. For country-scale candidate sets the
# hundreds of remote row-group scans dominate (~1 min each on this connection);
# one bulk download + local scans is ~10x faster overall.
VIDA_LOCAL = "data/vida/{iso3}.parquet"

_ISO2_TO_ISO3 = {"PK": "PAK", "DE": "DEU"}

Bbox = tuple[float, float, float, float]


def _iso3_for(cfg: dict) -> str | None:
    div = cfg.get("division") or {}
    iso2 = div.get("country")
    return _ISO2_TO_ISO3.get(iso2) if iso2 else None


def fetch_vida_buildings(
    bbox: Bbox, iso3: str, min_area_m2: float = 0.0, con=None
) -> gpd.GeoDataFrame:
    """VIDA Open Buildings within `bbox`, as an EPSG:4326 GeoDataFrame.

    Filters on the parquet `bbox` struct (row-group prunable) so only the AOI's
    row groups are scanned. `min_area_m2` uses the dataset's own `area_in_meters`.
    """
    con = con or overture.connect()
    local = Path(VIDA_LOCAL.format(iso3=iso3))
    url = str(local) if local.exists() else VIDA_URL.format(iso3=iso3)
    xmin, ymin, xmax, ymax = bbox
    area_filter = f"AND area_in_meters >= {min_area_m2}" if min_area_m2 else ""
    sql = f"""
        SELECT area_in_meters AS area_m2, confidence AS bf_confidence,
               ST_AsWKB(geometry) AS geometry
        FROM read_parquet('{url}')
        WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin}
          AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin} {area_filter}
    """
    df = con.execute(sql).df()
    gdf = overture._to_gdf(df)
    if not gdf.empty:
        gdf["id"] = [f"vida-{i}" for i in range(len(gdf))]
    return gdf


CELL_DEG = 0.1  # VIDA is spatially clustered ~this well; one cell scans in seconds


def _candidate_cells(geoms: gpd.GeoSeries, buffer_deg: float) -> list[tuple[float, float]]:
    """Lower-left corners of the 0.1 deg cells covering the candidates + buffer.

    The country VIDA file has tens of millions of rows, so a province-wide bbox pull
    is impractical; candidates are sparse, so we only scan the handful of cells they
    actually fall in.
    """
    b = geoms.bounds
    cells: set[tuple[int, int]] = set()
    for minx, miny, maxx, maxy in zip(b.minx, b.miny, b.maxx, b.maxy):
        ix0 = int(np.floor((minx - buffer_deg) / CELL_DEG))
        ix1 = int(np.floor((maxx + buffer_deg) / CELL_DEG))
        iy0 = int(np.floor((miny - buffer_deg) / CELL_DEG))
        iy1 = int(np.floor((maxy + buffer_deg) / CELL_DEG))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                cells.add((ix, iy))
    return [(ix * CELL_DEG, iy * CELL_DEG) for ix, iy in sorted(cells)]


def fetch_vida_near(
    geoms: gpd.GeoSeries, iso3: str, buffer_m: float = 2000.0
) -> gpd.GeoDataFrame:
    """VIDA footprints within `buffer_m` of any candidate geometry.

    Scans only the candidate-containing 0.1 deg cells and clips each to a buffered
    union of the candidates, so the cached set stays small even though the source
    file is nationwide.
    """
    buffer_deg = buffer_m / 111320.0
    cells = _candidate_cells(geoms, buffer_deg)
    clip = geoms.buffer(buffer_deg).union_all()  # geographic buffer; fine as a keep-mask
    log.info("Scanning %d VIDA cells (%s) around %d candidates", len(cells), iso3, len(geoms))
    con = overture.connect()
    parts = []
    for lon0, lat0 in tqdm(cells, desc="vida cells"):
        bbox = (lon0, lat0, lon0 + CELL_DEG, lat0 + CELL_DEG)
        g = fetch_vida_buildings(bbox, iso3, con=con)
        if g.empty:
            continue
        keep = g.sindex.query(clip, predicate="intersects")
        if len(keep):
            parts.append(g.iloc[keep])
    if not parts:
        return gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326")
    out = gpd.GeoDataFrame(gpd.pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    out["id"] = [f"vida-{i}" for i in range(len(out))]
    return out


def load_dense_buildings(
    aoi: str, cands: gpd.GeoDataFrame, cfg: dict, settings: Settings, cache_dir: Path
) -> gpd.GeoDataFrame | None:
    """Dense footprints around an AOI's candidates, preferring a cached VIDA pull.

    Order: cached VIDA parquet -> fresh windowed VIDA download (if the AOI's country
    is known) -> None (caller falls back to the local/Overture building set).
    """
    cache_dir = Path(cache_dir)
    cache = cache_dir / f"{aoi}_vida.parquet"
    if cache.exists():
        log.info("Loading cached VIDA buildings %s", cache)
        return gpd.read_parquet(cache)

    iso3 = _iso3_for(cfg)
    if iso3 is None:
        log.info("No division country for AOI %s; skipping VIDA (using fallback buildings)", aoi)
        return None
    gdf = fetch_vida_near(cands.geometry, iso3)
    if gdf.empty:
        log.warning("VIDA returned no buildings for %s; using fallback", aoi)
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(cache)
    log.info("Cached %d VIDA buildings -> %s", len(gdf), cache)
    return gdf
