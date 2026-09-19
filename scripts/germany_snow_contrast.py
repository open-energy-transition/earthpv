"""Does lying snow raise the PV-vs-roof contrast? The surviving half of the snow idea.

`docs/experiments.md` rejected snow-cover contrast for France on OPPORTUNITY -- 0.096 usable
scenes per commune-winter outside the Alps -- and recorded the one variant worth testing:
"If the snow hypothesis is ever tested properly it should be tested there, not in France",
meaning Germany, which has more reliable lowland snow and is already the largest region in
the training corpus.

The physics: panels are tilted, smooth and dark, so they shed and melt snow faster than the
roof around them. Under lying snow a dark array stops being a dark patch on a dark roof and
becomes a dark patch on a white one, which should raise the contrast the detector depends on.

This measures the contrast directly, with no classifier: for PV-dense German cells, per
scene, d-prime between pixels inside mapped OSM rooftop PV and PV-free roof pixels, split by
whether snow lay on the roofs that day.

Two things make it different from the shipped composite path:

  * SCL class 11 (snow) is KEPT. `imagery.scene_stack` masks to classes 4-7, which throws
    away precisely the observations under test.
  * Snow is measured OVER BUILDING FOOTPRINTS, not over the cell. Snow on farmland says
    nothing about whether roofs were white -- the same distinction `snow_opportunity.py`
    makes for France.

Germany's OSM rooftop layer is about 3.6% complete, so the PV-free control contains unmapped
PV. That biases d-prime toward zero, but it does so EQUALLY in snow and snow-free scenes, so
the comparison survives; the absolute values do not.

    pixi run python scripts/germany_snow_contrast.py --boxes 8 --winters 2022 2023 2024
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import odc.stac
import rasterio.features
from shapely.geometry import box as shp_box

from earthpv.imagery import _ES_BAND_FOR, _es_catalog

log = logging.getLogger("germany_snow_contrast")
SCL_SNOW = 11
SCL_CLOUD = (3, 8, 9, 10)
SCL_CLEAR = (4, 5, 6, 7)
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
VIS_NIR = [0, 1, 2, 6]
# OSM rooftop polygons above this are roof or site outlines rather than arrays -- measured
# in the German size-dependent conversion work (>2 km2 polygons imply 0.051 kWp/m2 against
# 0.200 for small ones). Using them as "PV pixels" would dilute the contrast with bare roof.
MAX_ARRAY_M2 = 2000.0
MIN_ARRAY_M2 = 100.0


def pick_boxes(solar: gpd.GeoDataFrame, n: int, half_km: float) -> list:
    """The n densest 0.1 deg cells by mapped rooftop array count, as small boxes."""
    pts = solar.geometry.representative_point()
    key = (np.floor(pts.x * 10).astype(int).astype(str) + "_"
           + np.floor(pts.y * 10).astype(int).astype(str))
    top = key.value_counts().head(n)
    out = []
    for k, cnt in top.items():
        m = key == k
        cx, cy = float(pts[m].x.median()), float(pts[m].y.median())
        dx = half_km / (111.32 * np.cos(np.radians(cy)))
        dy = half_km / 110.54
        out.append({"cell": k, "n_arrays": int(cnt),
                    "bbox": (cx - dx, cy - dy, cx + dx, cy + dy)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--solar", type=Path,
                    default=Path("data/labels/germany_national_osm_solar.parquet"))
    ap.add_argument("--boxes", type=int, default=8)
    ap.add_argument("--half-km", type=float, default=1.5)
    ap.add_argument("--winters", type=int, nargs="+", default=[2022, 2023, 2024])
    ap.add_argument("--max-items", type=int, default=40)
    ap.add_argument("--min-snow", type=float, default=0.20,
                    help="snow share of ROOF pixels for a scene to count as snow-covered")
    ap.add_argument("--max-cloud", type=float, default=0.20)
    ap.add_argument("--out", type=Path, default=Path("results/germany_snow_contrast.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    solar = gpd.read_parquet(args.solar)
    roof_pv = solar[(solar.placement == "rooftop")
                    & (solar.area_m2.between(MIN_ARRAY_M2, MAX_ARRAY_M2))]
    log.info("%d mapped rooftop arrays in %.0f-%.0f m2", len(roof_pv), MIN_ARRAY_M2, MAX_ARRAY_M2)
    boxes = pick_boxes(roof_pv, args.boxes, args.half_km)
    from earthpv.buildings import fetch_vida_buildings

    rows = []
    for bi, b in enumerate(boxes, 1):
        bbox = b["bbox"]
        pv_here = roof_pv[roof_pv.intersects(shp_box(*bbox))]
        bu = fetch_vida_buildings(bbox, "DEU")
        if pv_here.empty or bu.empty:
            log.warning("box %s: no PV or no buildings", b["cell"])
            continue
        for wy in args.winters:
            rng = (f"{wy}-12-01", f"{wy + 1}-02-28")
            with_lock = _es_catalog().search(
                collections=["sentinel-2-l2a"], bbox=bbox, datetime=f"{rng[0]}/{rng[1]}")
            items = list(with_lock.items())[: args.max_items]
            if not items:
                continue
            ds = odc.stac.load(
                items, bands=[_ES_BAND_FOR[x] for x in [*BANDS, "SCL"]],
                bbox=bbox, resolution=10, crs="EPSG:32632", groupby="solar_day",
                chunks={"x": 1024, "y": 1024}, fail_on_error=False,
            ).rename({_ES_BAND_FOR[x]: x for x in [*BANDS, "SCL"]}).compute()
            arr = np.stack([ds[x].values for x in BANDS], axis=1).astype("float32")
            scl = ds["SCL"].values
            tr = ds.odc.transform
            shape = arr.shape[-2:]
            pv_m = rasterio.features.rasterize(
                ((g, 1) for g in pv_here.to_crs(ds.odc.crs).geometry), out_shape=shape,
                transform=tr, fill=0, dtype="uint8").astype(bool)
            roof_m = rasterio.features.rasterize(
                ((g, 1) for g in bu.to_crs(ds.odc.crs).geometry), out_shape=shape,
                transform=tr, fill=0, dtype="uint8").astype(bool)
            ctrl_m = roof_m & ~pv_m
            if pv_m.sum() < 20 or ctrl_m.sum() < 50:
                continue
            for t in range(arr.shape[0]):
                s = scl[t]
                roof_scl = s[roof_m]
                snow = float(np.mean(roof_scl == SCL_SNOW))
                cloud = float(np.mean(np.isin(roof_scl, SCL_CLOUD)))
                usable = np.isin(s, SCL_CLEAR + (SCL_SNOW,))
                vis = np.nanmean(arr[t][VIS_NIR], axis=0)
                vis = np.where(usable, vis, np.nan)
                a, c = vis[pv_m], vis[ctrl_m]
                a, c = a[np.isfinite(a)], c[np.isfinite(c)]
                if len(a) < 20 or len(c) < 50:
                    continue
                sd = np.sqrt(0.5 * (np.var(a) + np.var(c)))
                rows.append({
                    "cell": b["cell"], "winter": wy,
                    "date": str(np.datetime64(ds["time"].values[t], "D")),
                    "snow_frac_roof": snow, "cloud_frac_roof": cloud,
                    "pv_mean": float(np.mean(a)), "roof_mean": float(np.mean(c)),
                    "dprime": float((np.mean(a) - np.mean(c)) / sd),
                    "n_pv_px": int(len(a)),
                })
            log.info("box %d/%d %s winter %d: %d scenes", bi, len(boxes), b["cell"], wy,
                     sum(r["cell"] == b["cell"] and r["winter"] == wy for r in rows))

    import pandas as pd
    from scipy import stats
    d = pd.DataFrame(rows)
    d.to_csv("results/germany_snow_contrast_scenes.csv", index=False)
    clear = d[d.cloud_frac_roof <= args.max_cloud]
    snowy = clear[clear.snow_frac_roof >= args.min_snow]
    bare = clear[clear.snow_frac_roof < 0.02]
    out = {
        "n_scenes": int(len(d)), "n_low_cloud": int(len(clear)),
        "n_snow_scenes": int(len(snowy)), "n_bare_scenes": int(len(bare)),
        "n_cells": int(d.cell.nunique()) if len(d) else 0,
        "snow_opportunity_rate": round(float(len(snowy) / max(len(clear), 1)), 4),
    }
    if len(snowy) >= 5 and len(bare) >= 5:
        out["dprime_snow"] = round(float(snowy.dprime.median()), 3)
        out["dprime_bare"] = round(float(bare.dprime.median()), 3)
        out["roof_brightness_snow"] = round(float(snowy.roof_mean.median()), 1)
        out["roof_brightness_bare"] = round(float(bare.roof_mean.median()), 1)
        u, p = stats.mannwhitneyu(snowy.dprime, bare.dprime)
        out["mannwhitney_p"] = round(float(p), 4)
        out["contrast_gain"] = round(float(abs(snowy.dprime.median())
                                           / max(abs(bare.dprime.median()), 1e-9)), 2)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
