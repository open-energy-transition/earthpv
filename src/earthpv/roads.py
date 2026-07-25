"""Road hard-negative mining via OSM Overpass.

Large paved roads/highways are a real false-positive source (observed directly in the
fraction-model's exported new-leads): bright, linear asphalt reads similarly enough to
panel rows to fool the model. Unlike buildings (hard_negatives.py), a road has no
"maybe an unmapped installation" ambiguity, so no bi-temporal check is needed -- any
point sampled along a real OSM highway way, away from a mapped solar feature, is
safely a hard negative.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, box
from tqdm import tqdm

from earthpv.export import _load_mapped_reference
from earthpv.labels import resolve_aoi
from earthpv.local_source import CompositeIndex
from earthpv.overpass import _run_query

log = logging.getLogger(__name__)

# Sealed by construction convention even without an explicit surface tag; surface=
# asphalt/paved widens the net to minor roads that happen to be paved too.
_HIGHWAY_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary")
SAMPLE_SPACING_M = 150.0  # point spacing along a road; matches hard_negatives.py's DECLUTTER_M scale
MAPPED_BUFFER_M = 75.0  # halo around mapped solar to exclude; same value hard_negatives.py uses
CHUNK_DEG = 0.5  # coarse Overpass query tiling -- keeps each call well inside timeout
# instead of one whole-AOI query (this project has hit truncation/timeout failures on
# big single-shot Overpass/STAC pulls before; chunking is the established fix)


def _query_roads(bbox: tuple[float, float, float, float], timeout: int) -> str:
    xmin, ymin, xmax, ymax = bbox
    bbox_str = f"({ymin},{xmin},{ymax},{xmax})"  # Overpass bbox order: south,west,north,east
    classes = "|".join(_HIGHWAY_CLASSES)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f"(\n"
        f'  way["highway"~"^({classes})$"]{bbox_str};\n'
        f'  way["surface"~"^(asphalt|paved)$"]["highway"]{bbox_str};\n'
        f");\n"
        f"out body geom;"
    )


def fetch_roads_overpass(
    bbox: tuple[float, float, float, float], timeout: int = 120
) -> gpd.GeoDataFrame:
    """Major/paved OSM highway ways in `bbox`. Overpass returns a matching way's FULL
    geometry (not clipped to bbox), so ways spanning several query chunks recur --
    callers should clip to their actual area of interest and drop_duplicates on `id`."""
    data = _run_query(_query_roads(bbox, timeout), timeout)
    rows = []
    for el in data.get("elements", []):
        if el["type"] != "way" or not el.get("geometry"):
            continue
        coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"] if pt]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        rows.append({
            "id": f"osm-way/{el['id']}",
            "highway": tags.get("highway"),
            "surface": tags.get("surface"),
            "geometry": LineString(coords),
        })
    if not rows:
        return gpd.GeoDataFrame(columns=["id", "highway", "surface"], geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _grid_chunks(bounds: tuple[float, float, float, float], chunk_deg: float):
    xmin, ymin, xmax, ymax = bounds
    for x0 in np.arange(xmin, xmax, chunk_deg):
        for y0 in np.arange(ymin, ymax, chunk_deg):
            yield (float(x0), float(y0), float(min(x0 + chunk_deg, xmax)), float(min(y0 + chunk_deg, ymax)))


def run_road_hard_negatives(
    aoi: str,
    composites_dir: Path = Path("data/composites"),
    out_dir: Path = Path("data/predictions"),
    sample_spacing_m: float = SAMPLE_SPACING_M,
    mapped_buffer_m: float = MAPPED_BUFFER_M,
    chunk_deg: float = CHUNK_DEG,
    limit: int = 0,
    timeout: int = 120,
) -> Path:
    """Mine road hard negatives: sample points along major/paved OSM highways inside
    the AOI's composited coverage, away from any mapped solar feature.

    Writes <out_dir>/<aoi>/hard_negatives_roads.parquet: lon, lat, kind="hard_negative",
    ready for `earthpv hard-negative-chips --centers` exactly like the bi-temporal
    building negatives (hard_negatives.py) and the vegetation veto's centers (export.py).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv.config import Settings

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)

    composed = Path(composites_dir) / aoi
    if composed.exists() and any(composed.glob("*/composite_0.tif")):
        comp_idx = CompositeIndex(composed)
    else:
        comp_idx = CompositeIndex(Path(settings.raw["local_root"]) / cfg["source_region"])
    coverage = comp_idx.coverage
    bounds = tuple(gpd.GeoSeries([coverage], crs="EPSG:4326").total_bounds)

    chunks = [c for c in _grid_chunks(bounds, chunk_deg) if coverage.intersects(box(*c))]
    log.info("Querying OSM roads over %s composited coverage in %d chunks (%.2f deg each)",
             aoi, len(chunks), chunk_deg)

    fetched = []
    for bbox in tqdm(chunks, desc="road chunks"):
        try:
            roads = fetch_roads_overpass(bbox, timeout=timeout)
        except Exception as e:  # noqa: BLE001 -- one bad chunk must not kill the run
            log.warning("chunk %s failed: %s", bbox, e)
            continue
        if not roads.empty:
            fetched.append(roads)

    out_path = Path(out_dir) / aoi
    out_path.mkdir(parents=True, exist_ok=True)
    out_path = out_path / "hard_negatives_roads.parquet"
    if not fetched:
        log.warning("No OSM roads found for %s", aoi)
        return out_path

    roads = pd.concat(fetched, ignore_index=True).drop_duplicates(subset="id").reset_index(drop=True)
    log.info("%d distinct road ways across all chunks", len(roads))

    # Clip to actual composited coverage: a matched way's geometry is returned in full
    # (see fetch_roads_overpass docstring), and a hard-negative chip is only useful
    # where composited imagery actually exists to cut it from.
    roads["geometry"] = roads.geometry.intersection(coverage)
    roads = roads[roads.geom_type.isin(["LineString", "MultiLineString"])].reset_index(drop=True)
    if roads.empty:
        log.warning("No road geometry left for %s after clipping to composited coverage", aoi)
        return out_path

    mapped = _load_mapped_reference(aoi, cfg, settings)
    if mapped is not None and not mapped.empty:
        sindex = mapped.sindex
        halo = roads.geometry.buffer(mapped_buffer_m / 111320.0)
        has_match = np.array([len(sindex.query(g, predicate="intersects")) > 0 for g in halo])
        roads = roads[~has_match].reset_index(drop=True)
        log.info("%d road ways remain after dropping any near a known OSM solar polygon", len(roads))

    # Sample points along each way, then declutter onto a grid (hard_negatives.py's
    # DECLUTTER_M pattern) -- a single long highway would otherwise flood the negative
    # set with near-duplicate chips.
    spacing_deg = sample_spacing_m / 111320.0
    records = []
    for _, row in roads.iterrows():
        geom = row.geometry
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            if line.length == 0:
                continue
            n = max(1, int(line.length / spacing_deg))
            for i in range(n + 1):
                pt = line.interpolate(i / n, normalized=True)
                records.append(dict(
                    lon=pt.x, lat=pt.y, kind="hard_negative", placement=None,
                    highway=row["highway"], surface=row["surface"], road_id=row["id"],
                ))

    if not records:
        log.warning("No sampleable road geometry for %s", aoi)
        return out_path

    pts = pd.DataFrame(records)
    deg = sample_spacing_m / 111320.0
    cell = (pts.lon / deg).round().astype(int).astype(str) + "_" + (pts.lat / deg).round().astype(int).astype(str)
    pts = pts.loc[~cell.duplicated()].reset_index(drop=True)
    log.info("%d road hard-negative centers after %.0fm spatial declutter", len(pts), sample_spacing_m)

    if limit and len(pts) > limit:
        rng = np.random.default_rng(42)
        pts = pts.iloc[rng.choice(len(pts), limit, replace=False)].reset_index(drop=True)

    pts.to_parquet(out_path)
    log.info("Wrote %d road hard-negative centers -> %s", len(pts), out_path)
    return out_path


if __name__ == "__main__":
    import sys

    run_road_hard_negatives(sys.argv[1] if len(sys.argv) > 1 else "pakistan")
