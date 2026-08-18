"""Build PV label datasets from Overture (OSM-derived) solar features.

Placement logic:
- OSM `location=roof` / `generator:place=roof` -> rooftop
- power=plant perimeters -> ground-mount
- remaining polygons -> classified by overlap with Overture building footprints
- point features are kept for evaluation only (no polygon to burn into masks)
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely.geometry import box

from earthpv import overture
from earthpv.config import Settings

log = logging.getLogger(__name__)
_GEOD = Geod(ellps="WGS84")


def geodesic_area_m2(geom) -> float:
    """Unsigned geodesic area - CRS-free, works globally."""
    if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return 0.0
    area, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(area)


def dissolve_overlapping(
    gdf: gpd.GeoDataFrame, group_col: str | None = "placement"
) -> gpd.GeoDataFrame:
    """Merge polygons that geometrically intersect into one feature per connected
    cluster, recomputing area geodesically on the union.

    Two OSM tags can describe the same real installation - a `power=plant` perimeter
    and a nested `power=generator` way, or two overlapping ways from independent
    mapping passes - as separate FEATURES. Summing their individual `area_m2`s
    double-counts the physical PV they share. Measured 2026-08-10 at Quaid-e-Azam
    Solar Park: 77% of the dissolved `generator` footprint sits inside the `plant`
    perimeter already covering it; nationally, ground-mount OSM area shrinks 24.4%
    once dissolved (55.95 -> 42.32 km²). It also fixes a second, unrelated failure
    mode: `postprocess.replace_with_osm_geometry`'s nearest-match picks whichever
    fragment happens to be closest, which can be a small nested member way instead of
    the real installation's outer footprint (Sukkur solar farm matched a 44,948 m²
    fragment - 1.7% of its true 2.6 km² footprint - because the national OSM pull had
    21 overlapping, un-dissolved elements at that site). Dissolving first removes the
    fragments before matching ever runs.

    `group_col`, if given and present, keeps clusters within the same value only -
    rooftop and ground-mount should never merge into each other even if their
    footprints happen to touch (a rooftop array directly above a ground-mount plant's
    substation, say). Non-polygon rows (points - an OSM `generator:source=solar` node
    with no mapped footprint) pass through unchanged; there is nothing to dissolve and
    their area stays whatever it already was (typically 0).

    Every other column keeps the value of the LARGEST (by pre-dissolve `area_m2`, or
    planar `.area` if that column is absent) contributing row per cluster - an
    `osm_matched_id`-style identifier from a dissolved pair should point at something
    real, not an arbitrary concatenation. A new `n_dissolved` column records cluster
    size (1 for anything that didn't merge) so the effect is auditable rather than
    silent.
    """
    import shapely
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    gdf = gdf.reset_index(drop=True)
    n_total = len(gdf)
    if n_total == 0:
        return gdf.assign(n_dissolved=pd.array([], dtype="int64"))

    is_poly = gdf.geometry.geom_type.isin(("Polygon", "MultiPolygon")).to_numpy()
    poly_idx = np.flatnonzero(is_poly)
    n_dissolved = np.ones(n_total, dtype=int)
    keep_mask = np.ones(n_total, dtype=bool)
    if poly_idx.size == 0:
        return gdf.assign(n_dissolved=n_dissolved)

    geoms = shapely.make_valid(gdf.geometry.to_numpy()[poly_idx])
    if group_col and group_col in gdf.columns:
        groups = gdf[group_col].to_numpy()[poly_idx]
        groups = np.where(pd.isna(groups), "__none__", groups.astype(str))
    else:
        groups = np.zeros(poly_idx.size, dtype=object)

    area_basis = (
        gdf["area_m2"].to_numpy(float)[poly_idx] if "area_m2" in gdf.columns
        else shapely.area(geoms)
    )
    out_geom = list(gdf.geometry.to_numpy())
    out_area = gdf["area_m2"].to_numpy(float).copy() if "area_m2" in gdf.columns else None

    for g in np.unique(groups):
        members = np.flatnonzero(groups == g)
        sub_geoms = geoms[members]
        n = members.size
        if n == 1:
            continue
        tree = shapely.STRtree(sub_geoms)
        li, ri = tree.query(sub_geoms, predicate="intersects")
        pair_mask = li != ri
        li, ri = li[pair_mask], ri[pair_mask]
        rows = np.concatenate([li, np.arange(n)])
        cols = np.concatenate([ri, np.arange(n)])
        graph = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
        _, labels = connected_components(graph, directed=False)
        for cl in np.unique(labels):
            cl_members = members[labels == cl]
            if cl_members.size == 1:
                continue
            global_members = poly_idx[cl_members]
            rep = global_members[np.argmax(area_basis[cl_members])]
            union = shapely.union_all(geoms[cl_members])
            out_geom[rep] = union
            if out_area is not None:
                out_area[rep] = geodesic_area_m2(union)
            n_dissolved[rep] = cl_members.size
            keep_mask[global_members[global_members != rep]] = False

    result = gdf.copy()
    result["geometry"] = out_geom
    if out_area is not None:
        result["area_m2"] = out_area
    result["n_dissolved"] = n_dissolved
    return result[keep_mask].reset_index(drop=True)


def resolve_aoi(aoi: str, settings: Settings) -> tuple[tuple[float, float, float, float], dict]:
    cfg = settings.aois.get(aoi)
    if cfg is None:
        raise KeyError(f"AOI '{aoi}' not in configs/aoi.yaml (have: {list(settings.aois)})")
    return tuple(cfg["bbox"]), cfg


def classify_placement(
    solar: gpd.GeoDataFrame, con, settings: Settings, overlap_frac: float,
    iso3: str | None = None,
) -> gpd.GeoDataFrame:
    """`iso3` switches the building source to a local VIDA country parquet
    (data/vida/<iso3>.parquet) - required where Overture's remote S3 is unusable
    (direct queries time out from this machine, see CLAUDE.md) and no rooftopsenti
    building cache exists, e.g. India."""
    solar = solar.copy()
    solar["placement"] = "unknown"

    roofish = solar["osm_location"].isin(["roof", "rooftop"]) | solar["generator_place"].isin(
        ["roof", "rooftop"]
    )
    solar.loc[roofish, "placement"] = "rooftop"
    solar.loc[(solar["kind"] == "plant") & ~roofish, "placement"] = "ground"

    # Remaining polygons: check overlap with buildings, cluster by 0.25 deg cells
    # so each Overture query stays small.
    todo = solar[(solar["placement"] == "unknown") & (solar.geom_type != "Point")]
    if todo.empty:
        return solar
    cells = set()
    for geom in todo.geometry:
        b = geom.bounds
        cells.add((np.floor(b[0] / 0.25), np.floor(b[1] / 0.25)))
    log.info("Classifying %d unknown polygons via buildings in %d cells", len(todo), len(cells))
    for cx, cy in sorted(cells):
        cell_bbox = (cx * 0.25, cy * 0.25, (cx + 1) * 0.25, (cy + 1) * 0.25)
        in_cell = todo[todo.geometry.intersects(box(*cell_bbox))]
        if in_cell.empty:
            continue
        if iso3:
            from earthpv.buildings import fetch_vida_buildings

            buildings = fetch_vida_buildings(cell_bbox, iso3, con=con)
        else:
            buildings = overture.fetch_buildings(cell_bbox, settings, con)
        if buildings.empty:
            solar.loc[in_cell.index, "placement"] = "ground"
            continue
        sindex = buildings.sindex
        for idx, geom in in_cell.geometry.items():
            cand = buildings.geometry.iloc[sindex.query(geom, predicate="intersects")]
            if len(cand) == 0:
                solar.loc[idx, "placement"] = "ground"
                continue
            inter = cand.intersection(geom)
            frac = sum(geodesic_area_m2(g) for g in inter) / max(geodesic_area_m2(geom), 1e-6)
            solar.loc[idx, "placement"] = "rooftop" if frac >= overlap_frac else "ground"
        todo = todo.drop(index=in_cell.index)
    return solar


def build_labels(aoi: str, out_dir: Path) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    bbox, cfg = resolve_aoi(aoi, settings)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = overture.connect()

    log.info("Fetching solar features for %s bbox=%s (release %s)", aoi, bbox, settings.overture_release)
    solar = overture.fetch_solar(bbox, settings, con)
    log.info("Fetched %d solar features (%d polygons)", len(solar), (solar.geom_type != "Point").sum())
    if solar.empty:
        raise RuntimeError(
            "No solar features returned - check that Overture source_tags carry "
            "generator:source (fallback: Overpass API)."
        )

    solar = classify_placement(solar, con, settings, settings.rooftop_overlap_frac)
    solar["area_m2"] = [geodesic_area_m2(g) for g in solar.geometry]
    solar["geom_type"] = solar.geom_type

    # Optional: clip to the actual division polygon, attach region for train/val split
    if "division" in cfg:
        d = cfg["division"]
        regions = overture.fetch_regions(d["country"], settings, con)
        if not regions.empty:
            regions.to_parquet(out_dir / f"{aoi}_regions.parquet")
            solar = gpd.sjoin(
                solar, regions[["name", "geometry"]], how="left", predicate="intersects"
            ).drop(columns=["index_right"]).rename(columns={"name": "region"})
            solar = solar[~solar.index.duplicated(keep="first")]

    out = out_dir / f"{aoi}_solar.parquet"
    solar.to_parquet(out)
    n_poly = ((solar.geom_type != "Point") & (solar.area_m2 >= 100)).sum()
    log.info(
        "Wrote %s: %d features | polygons>=100m2: %d | rooftop: %d | ground: %d",
        out, len(solar), n_poly,
        (solar.placement == "rooftop").sum(), (solar.placement == "ground").sum(),
    )
    return out
