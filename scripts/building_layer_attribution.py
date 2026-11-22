#!/usr/bin/env python
"""How often does a building layer put a mapped ROOFTOP array on a roof?

Placement is the building layer's most expensive job: a rooftop array whose roof is missing
from the layer reads `no_building`/`ground_adjacent` and converts at the land constant
(0.05 kWp/m2) instead of the module constant (0.18), about 3.6x less, and its precision and
recall come from the ground subtables. OpenStreetMap says independently where mappers saw a
roof: `location=roof` / `generator:place=roof` on the solar polygon. This scores any number
of candidate building layers against those tags, so a layer can be judged before an atlas is
rebuilt on it.

Per layer, over tagged rooftop polygons (and, as the false-roof control, tagged ground ones):
  on_roof      share whose area is at least --min-share covered by footprints
  touch        share touching any footprint
  area_on_roof the same as on_roof, weighted by array area
Footprint coverage is the sum of the array's intersections with each footprint, capped at
the array's area (the layers hold few overlapping outlines).

Caveat for OSM-derived layers: a rooftop array mapped in OSM is usually traced on an OSM
building, so a layer built from OSM buildings scores it nearly by construction. Read those
rows as "what the pipeline would do", not as independent evidence the roof exists.

    .pixi/envs/default/bin/python scripts/building_layer_attribution.py \\
        --labels data/labels/belgium_overpass_solar.parquet \\
        --layer vida=/home/tobi/earthpv_data/BEL.parquet \\
        --layer block=/home/tobi/earthpv_data/BEL_vida_osmfill.parquet --out results/x.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

log = logging.getLogger("attribution")
TILE = 0.1
PAD = 0.003
ROOF = {"roof", "rooftop"}
GROUND = {"ground", "surface"}


def tagged(labels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    loc = labels.get("osm_location", pd.Series(index=labels.index, dtype=object)).str.lower()
    place = labels.get("generator_place", pd.Series(index=labels.index, dtype=object)).str.lower()
    tag = np.where(loc.isin(ROOF) | place.isin(ROOF), "roof",
                   np.where(loc.isin(GROUND) | place.isin(GROUND), "ground", None))
    out = labels.assign(tag=tag)
    out = out[out.tag.notna() & out.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    return out.to_crs(4326).reset_index(drop=True)


def coverage(con, layer: str, lab: gpd.GeoDataFrame) -> np.ndarray:
    """Share of each array's area covered by the layer's footprints."""
    cx = lab.geometry.centroid
    tx = np.floor(cx.x / TILE).astype(int)
    ty = np.floor(cx.y / TILE).astype(int)
    cov = np.zeros(len(lab))
    geoms = shapely.make_valid(lab.geometry.to_numpy())
    area = shapely.area(geoms)
    for (x, y), idx in pd.Series(np.arange(len(lab))).groupby([tx, ty]):
        idx = idx.to_numpy()
        x0, y0 = x * TILE - PAD, y * TILE - PAD
        x1, y1 = (x + 1) * TILE + PAD, (y + 1) * TILE + PAD
        wkb = con.execute(f"""
            SELECT ST_AsWKB(geometry) FROM read_parquet('{layer}')
            WHERE bbox.xmin <= {x1} AND bbox.xmax >= {x0} AND bbox.ymin <= {y1} AND bbox.ymax >= {y0}
        """).fetchnumpy()
        col = next(iter(wkb.values()))
        if len(col) == 0:
            continue
        fp = shapely.make_valid(shapely.from_wkb([bytes(b) for b in col]))
        i, j = shapely.STRtree(fp).query(geoms[idx], predicate="intersects")
        if len(i) == 0:
            continue
        inter = shapely.area(shapely.intersection(geoms[idx][i], fp[j]))
        s = np.bincount(i, weights=inter, minlength=len(idx))
        cov[idx] = np.minimum(s / np.maximum(area[idx], 1e-30), 1.0)
        touch = np.zeros(len(idx), bool)
        touch[i] = True
        cov[idx[touch & (cov[idx] == 0)]] = 1e-9  # touches, no area
    return cov


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--layer", action="append", required=True, help="name=parquet (repeatable)")
    ap.add_argument("--min-share", type=float, default=0.5)
    ap.add_argument("--min-area-m2", type=float, default=10.0)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv import overture

    lab = tagged(gpd.read_parquet(a.labels))
    if "area_m2" in lab:
        lab = lab[lab.area_m2.fillna(0) >= a.min_area_m2].reset_index(drop=True)
    log.info("%s: %d roof-tagged, %d ground-tagged polygons", a.labels.name,
             (lab.tag == "roof").sum(), (lab.tag == "ground").sum())
    con = overture.connect()
    rows = []
    for spec in a.layer:
        name, path = spec.split("=", 1)
        cov = coverage(con, path, lab)
        for tag in ("roof", "ground"):
            m = (lab.tag == tag).to_numpy()
            if not m.any():
                continue
            w = lab.loc[m, "area_m2"].to_numpy() if "area_m2" in lab else np.ones(m.sum())
            on = cov[m] >= a.min_share
            rows.append({"labels": a.labels.name, "layer": name, "tag": tag, "n": int(m.sum()),
                         "on_roof": round(float(on.mean()), 4),
                         "touch": round(float((cov[m] > 0).mean()), 4),
                         "area_on_roof": round(float(w[on].sum() / w.sum()), 4),
                         "median_cover": round(float(np.median(cov[m])), 3)})
            log.info("%-10s %-6s n=%6d on_roof %.3f touch %.3f area_on_roof %.3f", name, tag,
                     rows[-1]["n"], rows[-1]["on_roof"], rows[-1]["touch"], rows[-1]["area_on_roof"])
    out = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.out, index=False)
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
