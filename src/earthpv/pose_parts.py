"""Panel pose per part of a large installation: more than one orientation per solar farm.

The pose survey (`scripts/glint_pose_survey.py`, `pose.py`) reads one statistic per
installation per date, the 98th-percentile reflectance inside the whole outline, and fits
one panel plane to the dates it spikes on. A plant built in blocks facing different ways
glints on different dates in each block, so that fit can describe one block at best. Fauji
Cement Solar Power Plant (Pakistan, 344,189 m2, seven mapped generator blocks) spiked on
five dates of which two agreed.

Here an installation of `PARTS_MIN_M2` or more is cut into square cells of `CELL_M` metres
(`split_into_parts`), each cell is read against the whole installation's surroundings
(`glint._read_parts_stats`, one image window per scene for the whole farm), each cell gets
its own fit by the same rule as a whole installation (two or more spike dates agreeing on
one plane within 3 degrees), and cells whose panel normals agree within `GROUP_DEG` form
one orientation (`group_orientations`). An orientation needs `MIN_GROUP_PARTS` cells: a
lone cell's fit is not reported, since a farm of a hundred cells gives a hundred chances of
a chance agreement. Each orientation carries the area of its cells, so a farm reads as
"62% at 20 deg facing 178 deg, 25% at 12 deg facing 150 deg, 13% not measured".
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box

PARTS_MIN_M2 = 50_000   # installations at or above this are read in parts
CELL_M = 100.0          # cell side; 100 pixels at 10 m
MIN_PIECE_M2 = 2_000    # a cell clipped to under 20 pixels is not read
GROUP_DEG = 5.0         # cells whose panel normals agree within this are one orientation
MIN_GROUP_PARTS = 2     # an orientation needs this many cells to be reported


def split_into_parts(geom, cell_m: float = CELL_M,
                     min_piece_m2: float = MIN_PIECE_M2) -> gpd.GeoDataFrame:
    """The installation outline cut by a square grid anchored at its own bounding box, in
    its local UTM zone: one row per piece of at least `min_piece_m2`, with `part` (0..n-1),
    geodesic `area_m2`, representative `lon`/`lat` and the WGS84 geometry."""
    from earthpv.labels import geodesic_area_m2

    src = gpd.GeoSeries([geom], crs="EPSG:4326")
    utm = src.estimate_utm_crs()
    g = src.to_crs(utm).iloc[0]
    minx, miny, maxx, maxy = g.bounds
    cells = [box(x, y, x + cell_m, y + cell_m)
             for y in np.arange(miny, maxy, cell_m) for x in np.arange(minx, maxx, cell_m)]
    pieces = shapely.intersection(np.array(cells, dtype=object), g)
    pieces = gpd.GeoSeries(pieces, crs=utm)
    pieces = pieces[~pieces.is_empty & pieces.geom_type.isin(("Polygon", "MultiPolygon"))]
    wgs = pieces.to_crs("EPSG:4326").reset_index(drop=True)
    area = np.array([geodesic_area_m2(p) for p in wgs])
    keep = area >= min_piece_m2
    wgs, area = wgs[keep].reset_index(drop=True), area[keep]
    rep = wgs.representative_point()
    return gpd.GeoDataFrame({"part": np.arange(len(wgs)), "area_m2": area.round(1),
                             "lon": rep.x.round(6), "lat": rep.y.round(6)},
                            geometry=wgs.values, crs="EPSG:4326")


def part_id(pid: str, part: int) -> str:
    return f"{pid}#{part:03d}"


def fit_part(series: pd.DataFrame, tol_deg: float = 3.0) -> dict:
    """One cell's fit, by the same rule as a whole installation (`glint.spike_fit`)."""
    from earthpv import glint

    return glint.spike_fit(series, tol_deg=tol_deg)


def _normals(tilt, az) -> np.ndarray:
    from earthpv.glint import unit_enu

    return unit_enu(np.asarray(tilt, float), np.asarray(az, float))


def group_orientations(fits: pd.DataFrame, total_area_m2: float,
                       group_deg: float = GROUP_DEG,
                       min_parts: int = MIN_GROUP_PARTS) -> pd.DataFrame:
    """Orientations of one installation from its cells' fits.

    `fits` has one row per cell with `area_m2`, `lon`, `lat`, `fit_tilt`, `fit_az`,
    `n_consistent`. Cells with a fit (`n_consistent >= 2`) are taken strongest first
    (most agreeing dates, then largest), and each joins the first orientation whose
    founding cell's panel normal lies within `group_deg`, else founds a new one. An
    orientation's pose is its cells' median tilt and azimuth; its place is the
    area-weighted mean of their representative points. Orientations with fewer than
    `min_parts` cells are dropped. Returns one row per orientation, largest first, with
    `share` of `total_area_m2`."""
    f = fits[fits.n_consistent >= 2].sort_values(["n_consistent", "area_m2"],
                                                 ascending=False)
    if f.empty:
        return pd.DataFrame(columns=["orientation", "tilt", "az", "area_m2", "share",
                                     "n_parts", "max_consistent", "lon", "lat"])
    normals = _normals(f.fit_tilt, f.fit_az)
    seeds: list[np.ndarray] = []
    label = np.empty(len(f), int)
    for i, n in enumerate(normals):
        for k, s in enumerate(seeds):
            if np.degrees(np.arccos(np.clip(np.dot(n, s), -1, 1))) <= group_deg:
                label[i] = k
                break
        else:
            seeds.append(n)
            label[i] = len(seeds) - 1
    f = f.assign(_g=label)
    rows = []
    for _, g in f.groupby("_g"):
        if len(g) < min_parts:
            continue
        w = g.area_m2.to_numpy()
        rows.append({
            "tilt": round(float(g.fit_tilt.median()), 1),
            "az": round(float(g.fit_az.median()), 1),
            "area_m2": round(float(w.sum()), 1),
            "share": round(float(w.sum() / total_area_m2), 3),
            "n_parts": len(g),
            "max_consistent": int(g.n_consistent.max()),
            "lon": round(float(np.average(g.lon, weights=w)), 6),
            "lat": round(float(np.average(g.lat, weights=w)), 6),
        })
    out = pd.DataFrame(rows, columns=["tilt", "az", "area_m2", "share", "n_parts",
                                      "max_consistent", "lon", "lat"])
    out = out.sort_values("area_m2", ascending=False).reset_index(drop=True)
    out.insert(0, "orientation", np.arange(1, len(out) + 1))
    return out
