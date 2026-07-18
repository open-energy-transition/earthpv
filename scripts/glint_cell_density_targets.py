"""Select a stratified sample of Lahore grid cells for the cell-aggregate glint
density calibration test (see conversation): does the COUNT of elevated-brightness
dates for a whole neighbourhood cell -- not any single installation -- correlate with
that cell's known true PV area? If real installations in a dense block have varied
(quasi-independent) orientations, the union of their narrow individual glint windows
should make the CELL glint far more often than any one sub-pixel installation would
alone, even though none of them are individually resolvable.

Grid: 300m cells over the Lahore OSM bbox (big enough to hold several adjacent small
roofs, small enough to stay a single "neighbourhood"). True density = summed OSM solar
polygon area within the cell. Stratified sample: densest cells, a mid-density band, and
zero-density controls (same urban bbox, so any signal difference isn't just "urban vs
rural").

Usage:
  .pixi/envs/default/bin/python scripts/glint_cell_density_targets.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box as shapely_box

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("cell_density_targets")

OUT_DIR = DATA_DIR / "glint_cell"
LAHORE_BBOX = (74.05, 31.30, 74.55, 31.65)
CELL_M = 300.0
N_DENSE = 15
N_MID = 10
N_ZERO = 15
SEED = 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    osm = gpd.read_file(DATA_DIR / "osm_pk_solar_160726.geojson")
    osm = osm[osm.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    lahore = osm.cx[LAHORE_BBOX[0]:LAHORE_BBOX[2], LAHORE_BBOX[1]:LAHORE_BBOX[3]].copy()
    utm_crs = lahore.estimate_utm_crs()
    lahore_utm = lahore.to_crs(utm_crs)
    lahore_utm["area_m2"] = lahore_utm.geometry.area

    minx, miny, maxx, maxy = lahore_utm.total_bounds
    cx = lahore_utm.geometry.centroid.x
    cy = lahore_utm.geometry.centroid.y
    ix = ((cx - minx) // CELL_M).astype(int)
    iy = ((cy - miny) // CELL_M).astype(int)
    lahore_utm["ix"], lahore_utm["iy"] = ix, iy

    dens = lahore_utm.groupby(["ix", "iy"]).agg(area_m2=("area_m2", "sum"), n_install=("area_m2", "size"))
    dens = dens.reset_index()
    log.info("%d cells with any OSM PV (of a full grid over the bbox)", len(dens))

    rng = np.random.default_rng(SEED)
    dense = dens.sort_values("area_m2", ascending=False).head(N_DENSE)
    remaining = dens.drop(dense.index)
    mid = remaining[remaining.area_m2.between(500, 3000)].sample(
        min(N_MID, len(remaining[remaining.area_m2.between(500, 3000)])), random_state=SEED
    )

    # Zero-density controls: empty cells within the same bbox, away from any mapped PV
    # (buffer by 1 cell so a control isn't just an artifact of grid-cell edge slicing).
    occupied = set(zip(dens.ix, dens.iy))
    n_ix = int((maxx - minx) // CELL_M) + 1
    n_iy = int((maxy - miny) // CELL_M) + 1
    zero_candidates = []
    for _ in range(N_ZERO * 20):
        i, j = rng.integers(0, n_ix), rng.integers(0, n_iy)
        neighborhood_clear = all(
            (i + di, j + dj) not in occupied for di in (-1, 0, 1) for dj in (-1, 0, 1)
        )
        if neighborhood_clear:
            zero_candidates.append((i, j))
        if len(zero_candidates) >= N_ZERO:
            break
    zero = pd.DataFrame(zero_candidates, columns=["ix", "iy"])
    zero["area_m2"] = 0.0
    zero["n_install"] = 0

    picks = pd.concat([
        dense.assign(stratum="dense"), mid.assign(stratum="mid"), zero.assign(stratum="zero"),
    ], ignore_index=True)
    picks["lon0"] = minx + picks.ix * CELL_M
    picks["lat0"] = miny + picks.iy * CELL_M
    geoms_utm = [
        shapely_box(x, y, x + CELL_M, y + CELL_M) for x, y in zip(picks.lon0, picks.lat0)
    ]
    picks_gdf = gpd.GeoDataFrame(picks, geometry=geoms_utm, crs=utm_crs).to_crs("EPSG:4326")
    picks_gdf["cid"] = [f"cell_{i:04d}" for i in range(len(picks_gdf))]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    picks_gdf.to_parquet(OUT_DIR / "cells.parquet")
    log.info("wrote %d cells (%s) -> %s", len(picks_gdf),
             picks_gdf.stratum.value_counts().to_dict(), OUT_DIR / "cells.parquet")
    log.info("dense cell area range: %.0f - %.0f m2", dense.area_m2.min(), dense.area_m2.max())


if __name__ == "__main__":
    main()
