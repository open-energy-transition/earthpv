"""DuckDB queries against Overture Maps GeoParquet on S3.

Overture preserves raw OSM tags in `source_tags` for base-theme features, which is
how we recover `generator:source=solar` / `plant:source=solar` labels.
"""

from __future__ import annotations

import duckdb
import geopandas as gpd
import pandas as pd
import shapely

from earthpv.config import Settings

S3_ROOT = "s3://overturemaps-us-west-2/release"

Bbox = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    # Anonymous access to the public Overture bucket
    con.execute("CREATE OR REPLACE SECRET overture (TYPE s3, PROVIDER config, REGION 'us-west-2');")
    return con


def _theme_path(release: str, theme: str, type_: str) -> str:
    return f"{S3_ROOT}/{release}/theme={theme}/type={type_}/*"


def _bbox_where(bbox: Bbox, prefix: str = "") -> str:
    xmin, ymin, xmax, ymax = bbox
    p = f"{prefix}." if prefix else ""
    return (
        f"{p}bbox.xmin <= {xmax} AND {p}bbox.xmax >= {xmin} "
        f"AND {p}bbox.ymin <= {ymax} AND {p}bbox.ymax >= {ymin}"
    )


def _to_gdf(df: pd.DataFrame, geom_col: str = "geometry") -> gpd.GeoDataFrame:
    if df.empty:
        return gpd.GeoDataFrame(df, geometry=[], crs="EPSG:4326")
    geom = shapely.from_wkb(df[geom_col].apply(bytes))
    return gpd.GeoDataFrame(df.drop(columns=[geom_col]), geometry=geom, crs="EPSG:4326")


def fetch_solar(
    bbox: Bbox, settings: Settings | None = None, con: duckdb.DuckDBPyConnection | None = None
) -> gpd.GeoDataFrame:
    """Solar generators/plants (OSM-derived) from the Overture base/infrastructure layer.

    Returns polygons and points with a `kind` column: generator (single install,
    usually rooftop) or plant (solar farm perimeter, usually ground-mount).
    """
    settings = settings or Settings.load()
    con = con or connect()
    path = _theme_path(settings.overture_release, "base", "infrastructure")
    sql = f"""
        SELECT
            id,
            class,
            map_extract(source_tags, 'generator:source')[1] AS generator_source,
            map_extract(source_tags, 'plant:source')[1] AS plant_source,
            map_extract(source_tags, 'generator:place')[1] AS generator_place,
            map_extract(source_tags, 'location')[1] AS osm_location,
            ST_AsWKB(geometry) AS geometry
        FROM read_parquet('{path}', hive_partitioning=1)
        WHERE subtype = 'power'
          AND class IN ('generator', 'plant', 'power_plant')
          AND {_bbox_where(bbox)}
          AND (
            map_extract(source_tags, 'generator:source')[1] = 'solar'
            OR map_extract(source_tags, 'plant:source')[1] = 'solar'
          )
    """
    gdf = _to_gdf(con.execute(sql).df())
    if not gdf.empty:
        gdf["kind"] = gdf["class"].map(lambda c: "generator" if c == "generator" else "plant")
    return gdf


def fetch_buildings(
    bbox: Bbox,
    settings: Settings | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    min_bbox_area_m2: float | None = None,
) -> gpd.GeoDataFrame:
    """Building footprints in bbox. `min_bbox_area_m2` pre-filters on the parquet
    bbox column (approximate, in metres) to avoid transferring millions of sheds."""
    settings = settings or Settings.load()
    con = con or connect()
    path = _theme_path(settings.overture_release, "buildings", "building")
    area_filter = ""
    if min_bbox_area_m2:
        # deg -> m at this latitude; bbox area overestimates footprint area, which is
        # fine for a recall-oriented pre-filter.
        lat = (bbox[1] + bbox[3]) / 2
        area_filter = (
            f"AND (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) "
            f"* 111320.0 * 111320.0 * cos(radians({lat})) >= {min_bbox_area_m2}"
        )
    sql = f"""
        SELECT id, subtype, class, ST_AsWKB(geometry) AS geometry
        FROM read_parquet('{path}', hive_partitioning=1)
        WHERE {_bbox_where(bbox)} {area_filter}
    """
    return _to_gdf(con.execute(sql).df())


def building_grid_stats(
    bbox: Bbox,
    cell_deg_x: float,
    cell_deg_y: float,
    settings: Settings | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    min_bbox_area_m2: float = 0.0,
) -> pd.DataFrame:
    """Aggregate building counts onto a chip grid without transferring geometries.

    Returns columns: ix, iy, n_buildings, max_area_m2 (approx). Used to skip
    empty chips during large-AOI inference.
    """
    settings = settings or Settings.load()
    con = con or connect()
    path = _theme_path(settings.overture_release, "buildings", "building")
    lat = (bbox[1] + bbox[3]) / 2
    area_expr = (
        "(bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) "
        f"* 111320.0 * 111320.0 * cos(radians({lat}))"
    )
    sql = f"""
        SELECT
            CAST(floor((bbox.xmin - {bbox[0]}) / {cell_deg_x}) AS INT) AS ix,
            CAST(floor((bbox.ymin - {bbox[1]}) / {cell_deg_y}) AS INT) AS iy,
            count(*) AS n_buildings,
            max({area_expr}) AS max_area_m2
        FROM read_parquet('{path}', hive_partitioning=1)
        WHERE {_bbox_where(bbox)} AND {area_expr} >= {min_bbox_area_m2}
        GROUP BY 1, 2
    """
    return con.execute(sql).df()


def fetch_division(
    name: str,
    country: str,
    subtype: str = "region",
    settings: Settings | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> gpd.GeoDataFrame:
    """Division area polygon (e.g. Punjab province, German states) from Overture divisions."""
    settings = settings or Settings.load()
    con = con or connect()
    path = _theme_path(settings.overture_release, "divisions", "division_area")
    sql = f"""
        SELECT id, names.primary AS name, country, subtype, ST_AsWKB(geometry) AS geometry
        FROM read_parquet('{path}', hive_partitioning=1)
        WHERE country = '{country}' AND subtype = '{subtype}'
          AND (names.primary = '{name}'
               OR list_contains(map_values(names.common), '{name}'))
    """
    return _to_gdf(con.execute(sql).df())


def fetch_regions(
    country: str,
    settings: Settings | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> gpd.GeoDataFrame:
    """All first-level regions (states/provinces) of a country."""
    settings = settings or Settings.load()
    con = con or connect()
    path = _theme_path(settings.overture_release, "divisions", "division_area")
    sql = f"""
        SELECT id, names.primary AS name, country, subtype, ST_AsWKB(geometry) AS geometry
        FROM read_parquet('{path}', hive_partitioning=1)
        WHERE country = '{country}' AND subtype = 'region'
    """
    return _to_gdf(con.execute(sql).df())
