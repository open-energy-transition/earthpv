"""Direct OpenStreetMap solar-PV fetch via the Overpass API.

Overture Maps' periodic snapshot (`overture_release` in aoi.yaml) lags live OSM edits
by weeks to months — a mapper who just finished surveying a city's rooftop PV won't
show up there yet. Overpass queries live OSM state directly, at the cost of being a
single public API (rate-limited, no bbox row-group pruning). Output matches
`overture.fetch_solar`'s schema (id, class, generator_source, plant_source,
generator_place, osm_location, kind, geometry) so it's a drop-in alternative source
for `labels.classify_placement` / `labels.build_labels`.

Supports a region either as an explicit bbox or as a place name resolved by Overpass
itself (`area["name"=...]`), so no separate geocoder dependency is needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point, Polygon
from shapely.ops import polygonize, unary_union

log = logging.getLogger(__name__)

Bbox = tuple[float, float, float, float]

# Public mirrors, tried in order; the main instance is rate-limited and occasionally
# down, so fall back rather than fail outright on a single-mapper-region request.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

# `generator:source=solar` covers single installations (rooftop or ground-mount);
# `plant:source=solar` covers solar-farm perimeters. Mirrors overture.fetch_solar's
# two source tags exactly so downstream classification is identical either way.
_SELECTORS = ['["generator:source"="solar"]', '["plant:source"="solar"]']


def _build_query(region_filter: str, timeout: int) -> str:
    clauses = "\n".join(f'  nwr{sel}{region_filter};' for sel in _SELECTORS)
    return f"[out:json][timeout:{timeout}];\n(\n{clauses}\n);\nout body geom;"


def _query_bbox(bbox: Bbox, timeout: int) -> str:
    xmin, ymin, xmax, ymax = bbox
    # Overpass bbox order is south,west,north,east (lat/lon, not lon/lat).
    return _build_query(f"({ymin},{xmin},{ymax},{xmax})", timeout)


def _query_place(place: str, timeout: int) -> str:
    escaped = place.replace('"', '\\"')
    prelude = f'area["name"="{escaped}"]->.searchArea;\n'
    clauses = "\n".join(f'  nwr{sel}(area.searchArea);' for sel in _SELECTORS)
    return f"[out:json][timeout:{timeout}];\n{prelude}(\n{clauses}\n);\nout body geom;"


# overpass-api.de's reverse proxy 406s the default python-requests User-Agent
# (treated as a generic bot); a descriptive UA is enough to pass.
_HEADERS = {"User-Agent": "earthpv-solar-labels/1.0 (research tool; contact via repo issues)"}


def _run_query(query: str, timeout: int) -> dict:
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                url, data={"data": query}, headers=_HEADERS, timeout=timeout + 30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 — try the next mirror
            log.warning("Overpass endpoint %s failed: %s", url, e)
            last_err = e
    raise RuntimeError(f"All Overpass endpoints failed: {last_err}")


def _way_geometry(el: dict) -> Point | Polygon | None:
    coords = [(pt["lon"], pt["lat"]) for pt in el.get("geometry", []) if pt]
    if len(coords) < 2:
        return None
    if len(coords) >= 4 and coords[0] == coords[-1]:
        return Polygon(coords)
    # Open way: not the closed-ring shape a mapped panel array should have; keep the
    # centroid as a point rather than drop it silently, so the mapper's edit is still
    # visible in the output (flagged via geom_type downstream).
    return Point(coords[len(coords) // 2])


def _relation_geometry(el: dict) -> Polygon | None:
    outer = [
        [(pt["lon"], pt["lat"]) for pt in m.get("geometry", [])]
        for m in el.get("members", [])
        if m.get("role") == "outer" and m.get("geometry")
    ]
    lines = [c for c in outer if len(c) >= 2]
    if not lines:
        return None
    from shapely.geometry import LineString

    polys = list(polygonize([LineString(c) for c in lines]))
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else unary_union(polys)


def _element_geometry(el: dict):
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if el["type"] == "way":
        return _way_geometry(el)
    if el["type"] == "relation":
        return _relation_geometry(el)
    return None


def fetch_solar_overpass(
    bbox: Bbox | None = None, place: str | None = None, timeout: int = 180,
) -> gpd.GeoDataFrame:
    """Solar generators/plants directly from live OSM via Overpass.

    Exactly one of `bbox` or `place` must be given; `place` is resolved by Overpass's
    own `area["name"=...]` matching (works for most well-known cities/regions without
    a separate geocoding step — ambiguous or unmapped names return zero results rather
    than raising, so check the row count).
    """
    if bool(bbox) == bool(place):
        raise ValueError("Pass exactly one of bbox or place")
    query = _query_bbox(bbox, timeout) if bbox else _query_place(place, timeout)
    data = _run_query(query, timeout)
    elements = data.get("elements", [])

    rows = []
    for el in elements:
        geom = _element_geometry(el)
        if geom is None or geom.is_empty:
            continue
        tags = el.get("tags", {})
        is_plant = tags.get("plant:source") == "solar"
        rows.append({
            "id": f"osm-{el['type']}/{el['id']}",
            "class": "plant" if is_plant else "generator",
            "generator_source": tags.get("generator:source"),
            "plant_source": tags.get("plant:source"),
            "generator_place": tags.get("generator:place"),
            "osm_location": tags.get("location"),
            "geometry": geom,
        })
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326") if rows else \
        gpd.GeoDataFrame(columns=["id", "class", "generator_source", "plant_source",
                                   "generator_place", "osm_location"], geometry=[], crs="EPSG:4326")
    if not gdf.empty:
        gdf["kind"] = gdf["class"].map(lambda c: "generator" if c == "generator" else "plant")
    log.info(
        "Overpass returned %d solar elements (%s)", len(gdf),
        f"place={place!r}" if place else f"bbox={bbox}",
    )
    return gdf


def build_overpass_labels(
    out_dir: Path,
    bbox: Bbox | None = None,
    place: str | None = None,
    name: str | None = None,
    timeout: int = 180,
) -> Path:
    """Fetch + classify + write an Overpass-sourced labels parquet, mirroring
    `labels.build_labels`'s output shape (`<name>_solar.parquet`) but from live OSM."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv import overture
    from earthpv.config import Settings
    from earthpv.labels import classify_placement, geodesic_area_m2

    settings = Settings.load()
    solar = fetch_solar_overpass(bbox=bbox, place=place, timeout=timeout)
    if solar.empty:
        raise RuntimeError(
            f"Overpass returned no solar features for {'place=' + repr(place) if place else 'bbox=' + repr(bbox)} "
            "— check the name/bbox, or the region genuinely has no generator:source=solar / "
            "plant:source=solar tags yet."
        )

    con = overture.connect()
    solar = classify_placement(solar, con, settings, settings.rooftop_overlap_frac)
    solar["area_m2"] = [geodesic_area_m2(g) for g in solar.geometry]
    solar["geom_type"] = solar.geom_type

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or (place.lower().replace(" ", "_").replace(",", "") if place else "overpass_region")
    out = out_dir / f"{stem}_overpass_solar.parquet"
    solar.to_parquet(out)
    n_poly = ((solar.geom_type != "Point") & (solar.area_m2 >= 10)).sum()
    log.info(
        "Wrote %s: %d features | polygons>=10m2: %d | rooftop: %d | ground: %d | unknown: %d",
        out, len(solar), n_poly,
        (solar.placement == "rooftop").sum(), (solar.placement == "ground").sum(),
        (solar.placement == "unknown").sum(),
    )
    return out
