"""Rooftop solar potential from three simple inputs: building size, lack of PV, irradiance.

    potential GWh/yr = free roof m2 x roof share x kWp/m2 x kWh/kWp

`roof_potential_cells` is the model's first half, one row per (0.1 deg cell, roof-size
band). It streams `roofclf.score_buildings_national`'s per-cell output, because a national
table does not fit in memory, and needs no new scoring pass:

- **Building size**: `roof_area_m2`, every VIDA footprint at or above `DEFAULT_MIN_ROOF_M2`.
- **Lack of PV**: a roof counts as free by `1 - p_roofclf`, and as 0 when it touches a mapped
  OSM solar outline or a model outline that earns capacity (`known_pv_features`). A whole roof
  counts as taken once it carries PV, however little of it the panels cover.
- **Roof share**: `measure_roof_share`, how much of the footprint mapped rooftop PV covers on
  the roofs that carry it. It is what owners install, not an engineering maximum.

`run_roof_potential` adds the irradiance (`pv_capacity.grid_specific_yield`). `earthpv atlas`
then picks the table up by itself: every evidence atlas whose AOI has one offers it as a map
layer (`load_potential`, `potential_totals`), and `atlas --potential-cells` draws the standalone
page (`atlas.build_potential_atlas`). This is a siting signal, not a capacity measurement or a forecast: cost, grid
limits, demand, roof structure, orientation and shade are all outside it.

`large_roof_buildings` is the older geometry-only pull behind
`scripts/build_potential_leads.py`, and never reads a PV score.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely.geometry import box

log = logging.getLogger(__name__)

# `large_roof_buildings`' floor, reaching below the segmentation model's detection floor.
DEFAULT_LARGE_ROOF_M2 = 200.0
# The segmentation model's own detection floor (chips.MIN_PV_AREA) -- used only to
# split the logged summary into "already-known population" vs. "new below-floor slice",
# not as a filter.
DETECTION_FLOOR_M2 = 400.0

# Lower edges of the roof-size bands, m2. The first is the model's floor: at Pakistan's measured
# roof share a 25 m2 roof carries about 1.5 kWp, three panels; below that it is not a system.
SIZE_BAND_EDGES = (25.0, 100.0, 200.0, 400.0)
DEFAULT_MIN_ROOF_M2 = SIZE_BAND_EDGES[0]
DEFAULT_N_PROBE = 400
# Where `earthpv roof-potential` writes, under <pred_dir>/<aoi>/. `earthpv atlas` looks here, so a
# country's atlas gains the layer by this command having run, with no flag to remember.
POTENTIAL_CELLS_RELPATH = Path("potential") / "roof_potential_cells.parquet"
# The columns the evidence atlas appends to `atlas.CELL_COLS_EVIDENCE` when it has this table.
POTENTIAL_CELL_COLS = ["potential_gwh", "potential_mwp"]
# How far (deg) past the grid's cell a file's middle building may sit and still be that cell.
_CELL_ID_TOLERANCE_DEG = 0.01


def large_roof_buildings(
    roofclf_dir: Path, min_roof_m2: float = DEFAULT_LARGE_ROOF_M2
) -> gpd.GeoDataFrame:
    """Every VIDA building nationally whose footprint is >= `min_roof_m2`, columns
    `cell, geometry, roof_area_m2` only -- `p_roofclf`/`sppi` are dropped even though
    the source files carry them, since this function's whole point is to answer a
    question those scores were never trained to answer.

    Reads every per-cell parquet in `roofclf_dir` (no domain restriction -- there is no
    precision estimate here to protect from an unrepresentative sample, unlike
    `sub400_capacity.domain_restricted_capacity`).
    """
    roofclf_dir = Path(roofclf_dir)
    parts = []
    for p in sorted(roofclf_dir.glob("*.parquet")):
        d = gpd.read_parquet(p, columns=["cell", "geometry", "roof_area_m2"])
        if d.empty:
            continue
        f = d[d.roof_area_m2 >= min_roof_m2]
        if not f.empty:
            parts.append(f)
    if not parts:
        raise ValueError(
            f"No buildings >= {min_roof_m2} m2 found under {roofclf_dir} -- check the "
            "directory holds `score_buildings_national`'s per-cell output"
        )
    buildings = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")

    n_total = len(buildings)
    area_total = float(buildings.roof_area_m2.sum())
    above = buildings.roof_area_m2 >= DETECTION_FLOOR_M2
    n_above, area_above = int(above.sum()), float(buildings.loc[above, "roof_area_m2"].sum())
    n_below, area_below = n_total - n_above, area_total - area_above
    log.info(
        "large_roof_buildings: %d buildings >= %.0f m2 (%.1f km2 total) -- %d/%d "
        "(%.1f/%.1f km2) already >= the %.0f m2 detection floor, %d/%d (%.1f/%.1f km2) "
        "are the new %.0f-%.0f m2 slice below it",
        n_total, min_roof_m2, area_total / 1e6,
        n_above, n_total, area_above / 1e6, area_total / 1e6, DETECTION_FLOOR_M2,
        n_below, n_total, area_below / 1e6, area_total / 1e6,
        min_roof_m2, DETECTION_FLOOR_M2,
    )
    return buildings


def measure_roof_share(buildings_table: Path, min_roof_m2: float = DEFAULT_MIN_ROOF_M2) -> dict:
    """How much of its footprint mapped rooftop PV covers, on the roofs that carry any, from a
    calibration table (`roofclf.building_table`'s `buildings.geoparquet`).

    `central` is area-weighted (total panels over total roof), so it prices a national roof
    total correctly; `low` and `high` are the median and 90th percentile PV roof.
    """
    t = pd.read_parquet(buildings_table, columns=["roof_area_m2", "pv_area_roof_m2"])
    t = t[(t["pv_area_roof_m2"] > 0) & (t["roof_area_m2"] >= min_roof_m2)]
    if t.empty:
        raise ValueError(f"No roof >= {min_roof_m2} m2 carries mapped PV in {buildings_table}")
    share = t["pv_area_roof_m2"] / t["roof_area_m2"]
    return {
        "central": float(t["pv_area_roof_m2"].sum() / t["roof_area_m2"].sum()),
        "low": float(share.median()),
        "high": float(share.quantile(0.9)),
        "n_pv_roofs": int(len(t)),
        "table": str(buildings_table),
    }


def known_pv_features(candidates_path: Path, osm_solar_path: Path, aoi: str) -> gpd.GeoDataFrame:
    """Every outline that already says "PV here", with a `source` of `osm` or `model`.

    Model outlines go through `density.capacity_relevant_candidates`, as they do for capacity:
    an unjudged merged sheet of false positives must not mark the town under it as taken.
    """
    from earthpv.density import (
        capacity_relevant_candidates,
        load_osm_screen,
        load_oversize_admission,
    )

    cands = gpd.read_parquet(candidates_path)
    relevant, _ = capacity_relevant_candidates(
        cands, osm_screen=load_osm_screen(aoi),
        oversize_admission=load_oversize_admission(aoi, cands))
    osm = gpd.read_parquet(osm_solar_path, columns=["geometry"]).to_crs(4326)
    model = relevant[["geometry"]].to_crs(4326)
    log.info("Known PV: %d OSM outlines, %d of %d model outlines",
             len(osm), len(model), len(cands))
    features = pd.concat(
        [osm.assign(source="osm"), model.assign(source="model")], ignore_index=True)
    return gpd.GeoDataFrame(features, geometry="geometry", crs=4326)


def _touched(buildings: gpd.GeoSeries, features: gpd.GeoSeries) -> np.ndarray:
    """Mask of `buildings` intersecting any of `features`."""
    mask = np.zeros(len(buildings), dtype=bool)
    if len(features):
        mask[np.unique(buildings.sindex.query(features.values, predicate="intersects")[1])] = True
    return mask


def roof_potential_cells(
    roofclf_dir: Path, known_pv: gpd.GeoDataFrame, grid: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """One row per (cell, size band): `n_roofs, roof_m2, free_m2, n_known, known_m2_osm,
    known_m2_model, sum_p, n_unscored`. See the module docstring for the definition.

    A building with no valid pixel (`p_roofclf` NaN) has no evidence of PV and counts as free;
    `n_unscored` says how many. Geometry is read only for the cells known PV reaches, where it
    also confirms the file's cell id still means the grid's cell, the failure
    `atlas._join_buildings_to_grid_cells` documents.
    """
    cells = grid.set_index("cell").geometry
    tree = known_pv.sindex
    is_osm = (known_pv["source"] == "osm").to_numpy()
    edges = np.asarray(SIZE_BAND_EDGES)
    paths = sorted(Path(roofclf_dir).glob("*.parquet"))
    if not paths:
        raise ValueError(f"No per-cell scoring under {roofclf_dir}")

    rows = []
    for i, path in enumerate(paths):
        cell = path.stem
        if cell not in cells.index:
            raise ValueError(f"{path} names a cell the density grid does not have")
        d = pq.read_table(path, columns=["roof_area_m2", "p_roofclf"]).to_pandas()
        if d.empty:
            continue
        area = d["roof_area_m2"].to_numpy(float)
        raw_p = d["p_roofclf"].to_numpy(float)
        unscored = np.isnan(raw_p)
        p = np.where(unscored, 0.0, raw_p)

        known_osm = known_model = np.zeros(len(d), dtype=bool)
        minx, miny, maxx, maxy = cells.loc[cell].bounds
        hits = tree.query(box(minx, miny, maxx, maxy), predicate="intersects")
        if len(hits):
            b = gpd.read_parquet(path, columns=["geometry"]).geometry
            mid = b.iloc[len(b) // 2].representative_point()
            tol = _CELL_ID_TOLERANCE_DEG
            if not (minx - tol <= mid.x <= maxx + tol and miny - tol <= mid.y <= maxy + tol):
                raise ValueError(f"{path}: buildings lie outside the grid's cell {cell}")
            hit_geoms = known_pv.geometry.iloc[hits]
            hit_osm = is_osm[hits]
            known_osm = _touched(b, hit_geoms[hit_osm])
            known_model = _touched(b, hit_geoms[~hit_osm]) & ~known_osm
        known = known_osm | known_model

        keep = area >= edges[0]
        frame = pd.DataFrame({
            "band": np.searchsorted(edges, area[keep], side="right") - 1,
            "n_roofs": 1,
            "roof_m2": area[keep],
            "free_m2": (area * (1.0 - p) * ~known)[keep],
            "n_known": known[keep].astype(int),
            "known_m2_osm": (area * known_osm)[keep],
            "known_m2_model": (area * known_model)[keep],
            "sum_p": np.where(known, 1.0, p)[keep],
            "n_unscored": unscored[keep].astype(int),
        })
        rows.append(frame.groupby("band", as_index=False).sum().assign(cell=cell))
        if (i + 1) % 500 == 0:
            log.info("roof_potential_cells: %d of %d cells", i + 1, len(paths))

    table = pd.concat(rows, ignore_index=True)
    table["band_lo_m2"] = edges[table.pop("band").to_numpy()]
    return table


def run_roof_potential(
    aoi: str, roofclf_dir: Path, roof_table: Path, osm_solar: Path,
    pred_dir: Path = Path("data/predictions"), out: Path | None = None,
    n_probe: int = DEFAULT_N_PROBE,
) -> Path:
    """Write `roof_potential_cells`' table, with each cell's PVGIS yield, and beside it under the
    same stem the JSON `load_potential` reads the roof share and the inputs from. The yield is
    fixed here so that building an atlas never needs PVGIS. `n_probe` is 400 (a few minutes on a
    first run, then cached beside the density outputs) because a 6 x 6 grid is too coarse to
    show where one province's yield ends and the next's begins.
    """
    from earthpv.pv_capacity import grid_specific_yield, interpolate_yield

    aoi_dir = Path(pred_dir) / aoi
    density_dir = aoi_dir / "density"
    out = Path(out) if out else aoi_dir / POTENTIAL_CELLS_RELPATH
    candidates = aoi_dir / "candidates.parquet"
    grid = gpd.read_parquet(density_dir / "grid.geoparquet",
                            columns=["cell", "geometry", "lon_center", "lat_center"])

    roof_share = measure_roof_share(roof_table)
    log.info("Roof share: %s", roof_share)
    known_pv = known_pv_features(candidates, osm_solar, aoi)
    table = roof_potential_cells(roofclf_dir, known_pv, grid)

    probes = grid_specific_yield(
        tuple(grid.total_bounds), density_dir / "irradiance_probes.csv", n_probe=n_probe)
    kwh = interpolate_yield(probes, grid["lon_center"].to_numpy(), grid["lat_center"].to_numpy())
    table["kwh_per_kwp_yr"] = table["cell"].map(pd.Series(kwh, index=grid["cell"]))

    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out)
    out.with_suffix(".json").write_text(json.dumps({
        "aoi": aoi,
        "roof_share": roof_share,
        "size_band_edges_m2": list(SIZE_BAND_EDGES),
        "n_probes": int(len(probes)),
        "inputs": {"roofclf_dir": str(roofclf_dir), "candidates": str(candidates),
                   "osm_solar": str(osm_solar)},
    }, indent=2))
    sums = table[
        ["n_roofs", "roof_m2", "free_m2", "known_m2_osm", "known_m2_model", "n_unscored"]
    ].sum()
    log.info("Wrote %s: %d cells, %s", out, table["cell"].nunique(), sums.round(0).to_dict())
    return out


def load_potential(path: Path, cells, aoi: str, kwp_per_m2: float) -> dict:
    """`run_roof_potential`'s table as arrays in the order of `cells`, with the model finished:
    `mwp` and `gwh` per cell and size band (`roof_km2`, `free_km2`, `known_km2`, `n_roofs`,
    `n_known` and `sum_p` have the same shape, `kwh` is per cell). Shared by the potential map
    and the evidence atlas's layer, so the two cannot disagree.
    """
    path = Path(path)
    run = json.loads(path.with_suffix(".json").read_text())
    if run["aoi"] != aoi:
        raise ValueError(f"{path} was built for {run['aoi']}, not {aoi}")
    table = pd.read_parquet(path)
    if "kwh_per_kwp_yr" not in table.columns:
        raise ValueError(f"{path} predates the yield column: re-run `earthpv roof-potential`")
    index = pd.Index(cells)
    unknown = set(table["cell"]) - set(index)
    if unknown:
        raise ValueError(f"{len(unknown)} cells in {path} are not in this atlas's grid")
    edges = list(SIZE_BAND_EDGES)

    def by_band(col: str) -> np.ndarray:
        return (table.pivot(index="cell", columns="band_lo_m2", values=col)
                .reindex(index=index, columns=edges).fillna(0.0).to_numpy())

    share = run["roof_share"]
    kwh = table.groupby("cell")["kwh_per_kwp_yr"].first().reindex(index).fillna(0.0).to_numpy()
    free_km2 = by_band("free_m2") / 1e6
    mwp_per_km2 = share["central"] * kwp_per_m2 * 1000.0
    mwp = free_km2 * mwp_per_km2
    return {
        "edges": edges, "share": share, "kwp_per_m2": kwp_per_m2, "mwp_per_km2": mwp_per_km2,
        "n_probes": run["n_probes"], "kwh": kwh, "mwp": mwp, "gwh": mwp * kwh[:, None] / 1000.0,
        "free_km2": free_km2, "roof_km2": by_band("roof_m2") / 1e6,
        "known_km2": (by_band("known_m2_osm") + by_band("known_m2_model")) / 1e6,
        "n_roofs": by_band("n_roofs"), "n_known": by_band("n_known"), "sum_p": by_band("sum_p"),
    }


def potential_totals(pot: dict) -> dict:
    """The national figures an evidence atlas carries as `totals.potential`."""
    gwh, share = float(pot["gwh"].sum()), pot["share"]
    kwh = pot["kwh"][pot["kwh"] > 0]
    return {
        "gwh": round(gwh, 1),
        "mwp": round(float(pot["mwp"].sum()), 1),
        "gwh_low": round(gwh * share["low"] / share["central"], 1),
        "gwh_high": round(gwh * share["high"] / share["central"], 1),
        "roof_share": round(share["central"], 3),
        "min_roof_m2": pot["edges"][0],
        "kwp_per_m2": pot["kwp_per_m2"],
        "free_km2": round(float(pot["free_km2"].sum()), 1),
        "roof_km2": round(float(pot["roof_km2"].sum()), 1),
        "kwh_range": [round(float(kwh.min())), round(float(kwh.max()))],
    }
