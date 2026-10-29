"""Hard negatives from OpenStreetMap classes the segmentation model mistakes for PV.

Egypt's mapping leads carry many outlines on swimming pools and on wastewater treatment
plants, above all their rectangular basins and sludge drying beds: still water in a regular
rectangle reads dark in the near infrared against bright desert, much as a block of panels
does at 10 m. Like a road (roads.py), a mapped pool or treatment basin needs no bi-temporal
check: anything OpenStreetMap maps as one, away from mapped solar, is safely a negative.

Each class is a list of Overpass selectors. Every feature is checked against the AOI's
model candidates (`lead_hit`: a candidate polygon touches it), so the output says how many
leads each class explains as well as where to cut chips. Centers are ordered hits first,
then by area, and decluttered onto a grid, so the confirmed confusions are never the ones
dropped. Writes `<out_dir>/<aoi>/hard_negatives_osm.parquet` (lon, lat, kind, ...), ready
for `earthpv hard-negative-chips --centers`, and a `_summary.json` beside it.

Features come from Overpass by default, one query per class per chunk. `pbf=` reads a
Geofabrik extract instead (`PBF_FILTERS`, GDAL's OSM driver): a dated snapshot, and the way
through when the Overpass mirrors are overloaded, as they were on 2026-10-29.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, box
from tqdm import tqdm

from earthpv.export import _load_mapped_reference
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.local_source import CompositeIndex
from earthpv.overpass import _relation_geometry, _run_query, _way_geometry
from earthpv.roads import _grid_chunks

log = logging.getLogger(__name__)

# Overpass selectors per class; `{bbox}` is filled per chunk.
CLASSES: dict[str, list[str]] = {
    "swimming_pool": [
        'way["leisure"="swimming_pool"]{bbox}',
        'relation["leisure"="swimming_pool"]{bbox}',
    ],
    # The plant's site outline (its chip covers the basins inside), plus basins mapped on
    # their own: `water=wastewater` is the documented tag, `man_made=clarifier` the round
    # settling tanks.
    "wastewater": [
        'nwr["man_made"="wastewater_plant"]{bbox}',
        'way["water"="wastewater"]{bbox}',
        'relation["water"="wastewater"]{bbox}',
        'way["man_made"="clarifier"]{bbox}',
    ],
}
# The same classes as GDAL OSM-driver layers and OGR SQL filters. The default osmconf.ini
# makes a closed way a polygon only for some keys (leisure and natural, not man_made or
# water), so a closed `man_made=wastewater_plant` way arrives in `lines`.
_WASTEWATER_TAG = "other_tags LIKE '%\"water\"=>\"wastewater\"%'"
PBF_FILTERS: dict[str, list[tuple[str, str]]] = {
    "swimming_pool": [("multipolygons", "leisure = 'swimming_pool'")],
    "wastewater": [
        ("multipolygons", f"man_made IN ('wastewater_plant', 'clarifier') OR {_WASTEWATER_TAG}"),
        ("lines", f"man_made IN ('wastewater_plant', 'clarifier') OR {_WASTEWATER_TAG}"),
        ("points", "man_made = 'wastewater_plant'"),
    ],
}
MIN_AREA_M2 = {"swimming_pool": 150.0, "wastewater": 0.0}  # a villa pool is under a pixel
NODE_HIT_M = 150.0      # a plant mapped as a node: a candidate this close is on it
DECLUTTER_M = 500.0     # one chip per 500 m grid cell; a chip is 2.24 km across
MAPPED_BUFFER_M = 75.0  # same halo as roads.py and hard_negatives.py
CHUNK_DEG = 1.0
DEG_M = 111320.0


def _query(selectors: list[str], bbox: tuple[float, float, float, float], timeout: int) -> str:
    xmin, ymin, xmax, ymax = bbox
    bbox_str = f"({ymin},{xmin},{ymax},{xmax})"  # Overpass order: south,west,north,east
    body = "\n".join(f"  {s.format(bbox=bbox_str)};" for s in selectors)
    return f"[out:json][timeout:{timeout}];\n(\n{body}\n);\nout tags geom;"


def fetch_class_overpass(
    osm_class: str, bbox: tuple[float, float, float, float], timeout: int = 180
) -> gpd.GeoDataFrame:
    """One class's features in `bbox`, as polygons (ways, relations) or points (nodes)."""
    data = _run_query(_query(CLASSES[osm_class], bbox, timeout), timeout)
    rows = []
    for el in data.get("elements", []):
        if el["type"] == "node":
            geom = Point(el["lon"], el["lat"])
        elif el["type"] == "way":
            geom = _way_geometry(el)
        else:
            geom = _relation_geometry(el)
        if geom is None or geom.is_empty:
            continue
        tags = el.get("tags", {})
        rows.append({
            "osm_id": f"osm-{el['type']}/{el['id']}",
            "osm_class": osm_class,
            "name": tags.get("name") or tags.get("name:en"),
            "tag": next((f"{k}={tags[k]}" for k in ("leisure", "man_made", "water")
                         if k in tags), None),
            "geometry": geom,
        })
    if not rows:
        return gpd.GeoDataFrame(columns=["osm_id", "osm_class", "name", "tag"], geometry=[],
                                crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def read_class_pbf(osm_class: str, pbf: Path) -> gpd.GeoDataFrame:
    """One class's features from an OSM extract, in `fetch_class_overpass`'s schema."""
    import pyogrio

    # The driver spills its node index to a temp file; keep it beside the extract (on
    # /home), not in the working directory on the nearly full aidisc.
    pyogrio.set_gdal_config_options({"CPL_TMPDIR": str(Path(pbf).resolve().parent)})
    frames = []
    for layer, where in PBF_FILTERS[osm_class]:
        df = pyogrio.read_dataframe(pbf, layer=layer, where=where)
        if df.empty:
            continue
        if layer == "lines":  # a closed way is an area; an open one says nothing of size
            closed = df.geometry.is_closed & (df.geometry.count_coordinates() >= 4)
            df = df[closed].copy()
            df["geometry"] = df.geometry.apply(lambda g: Polygon(g.coords))
        if layer == "multipolygons":
            way = df["osm_way_id"].notna()
            df["osm_id"] = np.where(way, "osm-way/" + df["osm_way_id"].astype(str),
                                    "osm-relation/" + df["osm_id"].astype(str))
        else:
            kind = "way" if layer == "lines" else "node"
            df["osm_id"] = f"osm-{kind}/" + df["osm_id"].astype(str)
        if osm_class == "swimming_pool":
            tag = pd.Series("leisure=swimming_pool", index=df.index)
        else:
            tag = ("man_made=" + df["man_made"]).fillna("water=wastewater")
        frames.append(gpd.GeoDataFrame({
            "osm_id": df["osm_id"], "osm_class": osm_class, "name": df["name"], "tag": tag,
        }, geometry=df.geometry, crs="EPSG:4326"))
    if not frames:
        return gpd.GeoDataFrame(columns=["osm_id", "osm_class", "name", "tag"], geometry=[],
                                crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")


def _lead_hits(features: gpd.GeoDataFrame, candidates: gpd.GeoDataFrame) -> np.ndarray:
    """Candidates touching each feature (a node counts within NODE_HIT_M)."""
    if candidates is None or candidates.empty:
        return np.zeros(len(features), dtype=int)
    probe = features.geometry.where(
        features.geom_type.isin(["Polygon", "MultiPolygon"]),
        features.geometry.buffer(NODE_HIT_M / DEG_M),
    )
    sindex = candidates.sindex
    return np.array([len(sindex.query(g, predicate="intersects")) for g in probe])


def run_osm_hard_negatives(
    aoi: str,
    classes: tuple[str, ...] = ("swimming_pool", "wastewater"),
    pred_dir: Path = Path("data/predictions"),
    out_dir: Path = Path("data/predictions"),
    declutter_m: float = DECLUTTER_M,
    mapped_buffer_m: float = MAPPED_BUFFER_M,
    limit_per_class: int = 0,
    chunk_deg: float = CHUNK_DEG,
    timeout: int = 180,
    pbf: Path | None = None,
) -> Path:
    """Hard-negative chip centers on OSM features of `classes` inside the AOI's composited
    coverage, away from mapped solar, hits on the model's candidates first. `pbf` reads
    the features from an OSM extract instead of Overpass."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv.config import Settings

    unknown = set(classes) - set(CLASSES)
    if unknown:
        raise ValueError(f"unknown classes {sorted(unknown)}; known: {sorted(CLASSES)}")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)

    composed = Path("data/composites") / aoi
    if composed.exists() and any(composed.glob("composites/*/composite_0.tif")):
        comp_idx = CompositeIndex(composed)
    else:
        comp_idx = CompositeIndex(Path(settings.raw["local_root"]) / cfg["source_region"])
    coverage = comp_idx.coverage
    bounds = tuple(gpd.GeoSeries([coverage], crs="EPSG:4326").total_bounds)
    chunks = [c for c in _grid_chunks(bounds, chunk_deg) if coverage.intersects(box(*c))]

    fetched, failed = [], []
    for osm_class in classes:
        if pbf is not None:
            fetched.append(read_class_pbf(osm_class, pbf))
            log.info("%s: %d features in %s", osm_class, len(fetched[-1]), pbf)
            continue
        for bbox in tqdm(chunks, desc=f"{osm_class} chunks"):
            try:
                gdf = fetch_class_overpass(osm_class, bbox, timeout=timeout)
            except Exception as e:  # noqa: BLE001 -- one bad chunk must not kill the run
                log.warning("%s chunk %s failed: %s", osm_class, bbox, e)
                failed.append({"osm_class": osm_class, "bbox": list(bbox)})
                continue
            if not gdf.empty:
                fetched.append(gdf)

    out_path = Path(out_dir) / aoi
    out_path.mkdir(parents=True, exist_ok=True)
    out_path = out_path / "hard_negatives_osm.parquet"
    if not fetched:
        log.warning("No OSM features of %s found for %s", classes, aoi)
        return out_path

    feats = pd.concat(fetched, ignore_index=True).drop_duplicates(subset="osm_id")
    feats = gpd.GeoDataFrame(feats, geometry="geometry", crs="EPSG:4326")
    # A matched way comes back whole, so clip by its point rather than its outline: a
    # chip needs imagery at its center.
    pts = feats.geometry.representative_point()
    feats = feats[pts.within(coverage)].reset_index(drop=True)
    feats["area_m2"] = feats.geometry.apply(geodesic_area_m2)
    n_fetched = feats.osm_class.value_counts().to_dict()

    candidates_path = Path(pred_dir) / aoi / "candidates.parquet"
    candidates = gpd.read_parquet(candidates_path) if candidates_path.exists() else None
    leads_path = Path(pred_dir) / aoi / f"{aoi}_pv_new_leads.geojson"
    leads = gpd.read_file(leads_path) if leads_path.exists() else None
    feats["candidate_hits"] = _lead_hits(feats, candidates)
    feats["lead_hits"] = _lead_hits(feats, leads)

    summary: dict = {"aoi": aoi, "classes": list(classes),
                     "source": str(pbf) if pbf is not None else "overpass",
                     "chunks": None if pbf is not None else len(chunks),
                     "chunks_failed": failed, "fetched": n_fetched,
                     "candidates": None if candidates is None else len(candidates),
                     "leads": None if leads is None else len(leads), "per_class": {}}
    if leads is not None and len(leads):
        # Leads explained by each class, and their outline area: what a mapper meets.
        lead_geoms = leads.geometry
        for osm_class in classes:
            sub = feats[feats.osm_class == osm_class]
            probe = sub.geometry.where(sub.geom_type.isin(["Polygon", "MultiPolygon"]),
                                       sub.geometry.buffer(NODE_HIT_M / DEG_M))
            on = lead_geoms.intersects(probe.union_all()) if len(sub) else \
                pd.Series(False, index=leads.index)
            summary["per_class"][osm_class] = {
                "features": int(len(sub)),
                "features_hit_by_a_lead": int((sub.lead_hits > 0).sum()),
                "leads_on_class": int(on.sum()),
                "leads_on_class_area_m2": float(leads.loc[on, "area_m2"].sum()),
            }

    mapped = _load_mapped_reference(aoi, cfg, settings)
    if mapped is not None and not mapped.empty:
        halo = feats.geometry.buffer(mapped_buffer_m / DEG_M)
        near = np.array([len(mapped.sindex.query(g, predicate="intersects")) > 0
                         for g in halo])
        summary["dropped_near_mapped_solar"] = int(near.sum())
        feats = feats[~near].reset_index(drop=True)

    keep = np.zeros(len(feats), dtype=bool)
    for osm_class in classes:
        keep |= (feats.osm_class == osm_class) & (feats.area_m2 >= MIN_AREA_M2[osm_class])
        keep |= (feats.osm_class == osm_class) & feats.geom_type.eq("Point")
    feats = feats[keep]
    feats = feats.assign(hit=feats.candidate_hits > 0).sort_values(
        ["hit", "area_m2"], ascending=[False, False]).reset_index(drop=True)

    pts = feats.geometry.representative_point()
    feats["lon"], feats["lat"] = pts.x, pts.y
    deg = declutter_m / DEG_M
    cell = ((feats.lon / deg).round().astype(int).astype(str) + "_"
            + (feats.lat / deg).round().astype(int).astype(str))
    feats = feats.loc[~cell.duplicated()].reset_index(drop=True)
    if limit_per_class:
        feats = feats.groupby("osm_class", group_keys=False).head(limit_per_class)

    out = pd.DataFrame({
        "lon": feats.lon, "lat": feats.lat, "kind": "hard_negative", "placement": None,
        "osm_class": feats.osm_class, "osm_id": feats.osm_id, "tag": feats["tag"],
        "name": feats["name"], "area_m2": feats.area_m2,
        "candidate_hits": feats.candidate_hits, "lead_hits": feats.lead_hits,
    }).reset_index(drop=True)
    out.to_parquet(out_path)
    summary["centers"] = out.osm_class.value_counts().to_dict()
    summary["centers_hit"] = out[out.candidate_hits > 0].osm_class.value_counts().to_dict()
    out_path.with_name("hard_negatives_osm_summary.json").write_text(
        json.dumps(summary, indent=2, default=str))
    log.info("Wrote %d OSM hard-negative centers (%s) -> %s", len(out),
             summary["centers"], out_path)
    return out_path
