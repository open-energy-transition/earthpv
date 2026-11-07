"""Solar thermal power plants (CSP) as an atlas component.

Solar THERMAL is dropped from every country's PV labels (`scripts/drop_solar_thermal.py`):
a mirror field is not photovoltaic, and counted as one at the ground-mount land constant it
would add PV that does not exist (Khi Solar One's 5.97 km2 site would read 298 MWp against
its 50 MW). Since 2026-11-07 the atlas counts concentrated solar power plants instead, in
Verified and Best, at their electric rating (owner decision, CSP power plants only: solar
water heaters and solar district heating produce heat and stay out).

A plant enters the table when OpenStreetMap maps it as a `power=plant` whose
`plant:method` names thermal (never photovoltaic) and which carries a
`plant:output:electricity` tag (a plant with only a hot-water or heat output is a heating
plant), or when `drop_solar_thermal.KNOWN_THERMAL` lists it. A plant lying mostly inside
another one's outline is a part of it (Solaben 2 inside the Solaben complex) and is dropped.

**Capacity.** The electricity tag where it gives a number. Where it does not ("yes"), or
where the number is implausibly high for the site (more than `CSP_TAG_MAX_FACTOR` times the
measured density on a site of at least `CSP_TAG_CHECK_MIN_KM2`, which is what a tag naming a
whole complex looks like: Noor 3's outline is tagged 582 MW, Noor 1-4 together), capacity is
site area x `CSP_MW_PER_KM2`. Only implausibly HIGH tags are overruled: tower plants are
legitimately sparse (Khi Solar One 8.4 MW/km2, Gemasolar 10.4).

`CSP_MW_PER_KM2` is the median over the 46 plants of at least 0.2 km2 that carried an MW
tag in the thermal records of South Africa, Morocco, Spain and Turkey on 2026-11-07
(27.2 MW/km2, 10-90% 18.9-42.8, log-SD 0.41). `CSP_LOG_SD` drives the uncertainty of
area-based plants in the atlas interval; a tagged plant is its nameplate and has none.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CSP_MW_PER_KM2 = 27.2
CSP_LOG_SD = 0.41
CSP_TAG_MAX_FACTOR = 3.0
CSP_TAG_CHECK_MIN_KM2 = 0.5
CSP_MIN_AREA_M2 = 10_000.0
# A plant more than this share inside a larger CSP plant is part of it.
CSP_CONTAINED_FRAC = 0.5

TABLE_NAME = "{aoi}_csp_plants.parquet"
COLUMNS = ["id", "name", "mw", "mw_source", "mw_tag", "area_m2", "geometry"]


def table_path(aoi: str, labels_dir: Path = Path("data/labels")) -> Path:
    return Path(labels_dir) / TABLE_NAME.format(aoi=aoi)


def parse_mw(tag) -> float | None:
    """MW from a `plant:output:electricity` value ("50 MW", "49.9 MW", "1.2 GW", "800 kW");
    None for "yes", an empty tag or anything else."""
    if tag is None or (isinstance(tag, float) and np.isnan(tag)):
        return None
    m = re.match(r"^\s*([\d]+(?:[.,]\d+)?)\s*(GW|MW|kW|W)?\s*$", str(tag), re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "MW").upper()
    return {"GW": v * 1000.0, "MW": v, "KW": v / 1000.0, "W": v / 1e6}[unit]


def is_csp_plant(tags: dict) -> bool:
    """A thermal power plant with an electric output (see the module docstring)."""
    if str(tags.get("power", "")) != "plant":
        return False
    method = (str(tags.get("plant:method", "")) + ";" + str(tags.get("generator:method", ""))).lower()
    if "photovoltaic" in method or "thermal" not in method:
        return False
    out = str(tags.get("plant:output:electricity", "")).strip().lower()
    # "no" (Senftenberg's solar district heating, 2026-11-07), "0" or "none" is a plant that
    # says it makes no electricity.
    return out not in ("", "no", "none", "0", "0 mw")


def plant_capacity(mw_tag: float | None, area_m2: float) -> tuple[float, str]:
    """(MW, source) for one plant: the tag, or site area x CSP_MW_PER_KM2."""
    km2 = area_m2 / 1e6
    by_area = km2 * CSP_MW_PER_KM2
    if mw_tag is None or mw_tag <= 0:
        return by_area, "area"
    if km2 >= CSP_TAG_CHECK_MIN_KM2 and mw_tag / km2 > CSP_TAG_MAX_FACTOR * CSP_MW_PER_KM2:
        return by_area, "area (tag implausible)"
    return float(mw_tag), "tag"


def build_table(candidates: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """CSP plant table from `candidates` (columns id, name, mw_tag_raw, area_m2, geometry in
    EPSG:4326, one row per OSM thermal power plant with an electric output). Returns the
    table and the rows left out with the reason (too small, part of a larger plant)."""
    from earthpv.labels import geodesic_area_m2

    c = candidates.copy()
    if c.empty:
        return gpd.GeoDataFrame(columns=COLUMNS, geometry="geometry", crs="EPSG:4326"), pd.DataFrame()
    c = c[c.geometry.notna() & c.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    c["area_m2"] = [geodesic_area_m2(g) for g in c.geometry]
    out_rows = []
    small = c["area_m2"] < CSP_MIN_AREA_M2
    for _, r in c[small].iterrows():
        out_rows.append({"id": r["id"], "name": r.get("name"), "area_m2": r["area_m2"],
                         "reason": f"site under {CSP_MIN_AREA_M2:,.0f} m2"})
    c = c[~small].sort_values("area_m2", ascending=False).reset_index(drop=True)
    if not c.empty:
        utm = c.estimate_utm_crs()
        g = c.to_crs(utm).geometry.buffer(0)
        keep = np.ones(len(c), bool)
        for i in range(len(c)):
            for j in range(i):  # j is larger (sorted)
                if not keep[j]:
                    continue
                inter = g.iloc[i].intersection(g.iloc[j]).area
                if inter > CSP_CONTAINED_FRAC * g.iloc[i].area:
                    keep[i] = False
                    out_rows.append({"id": c.at[i, "id"], "name": c.at[i, "name"],
                                     "area_m2": c.at[i, "area_m2"],
                                     "reason": f"inside {c.at[j, 'id']} ({c.at[j, 'name']})"})
                    break
        c = c[keep].reset_index(drop=True)
    mw, src, tag = [], [], []
    for _, r in c.iterrows():
        t = parse_mw(r.get("mw_tag_raw"))
        v, s = plant_capacity(t, float(r["area_m2"]))
        mw.append(v)
        src.append(s)
        tag.append(t)
    c["mw"], c["mw_source"], c["mw_tag"] = mw, src, tag
    table = gpd.GeoDataFrame(c[COLUMNS], geometry="geometry", crs="EPSG:4326")
    return table, pd.DataFrame(out_rows)


def load_plants(aoi: str, labels_dir: Path = Path("data/labels")) -> gpd.GeoDataFrame | None:
    """The country's CSP table; None when it was never built (the page then says solar
    thermal was not checked), an empty frame when it was and holds no plant."""
    p = table_path(aoi, labels_dir)
    if not p.exists():
        return None
    t = gpd.read_parquet(p)
    return t.to_crs("EPSG:4326") if t.crs is not None else t.set_crs("EPSG:4326")
