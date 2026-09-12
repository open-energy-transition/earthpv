#!/usr/bin/env python
"""How often is there usable lying snow on the roofs of France's calibration communes?

Snow inverts the contrast that makes small rooftop PV hard at 10 m: a shed-clear panel is
dark against a bright roof instead of dark against dark slate. Before any of that can be
exploited, the question that killed the equivalent glint idea has to be answered --
**how many chances does a building actually get?** `glint_opportunity.py` exists because a
per-target detection rate is meaningless without the number of geometrically compatible
scenes behind it; this is the same measurement for snow, and it is pure metadata plus one
20 m band, so it costs no GPU and no modelling.

The measure is snow **over building footprints**, not over the commune. Snow on farmland
tells you nothing: what matters is whether the roofs were white on a day Sentinel-2 could
see them. So SCL is read on its native 20 m grid and reduced inside a rasterised mask of
the commune's VIDA footprints.

A scene counts as an opportunity when, over those footprints, snow (SCL 11) exceeds
`--min-snow` AND cloud (SCL 3/8/9/10) stays under `--max-cloud-frac`. Both conditions
matter and the cloud one is easy to forget: a snowfall in France usually arrives with the
weather system that hides it.

    pixi run python scripts/snow_opportunity.py --winters 2021 2022 2023 2024
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

log = logging.getLogger("snow-opportunity")
SCL_SNOW = 11
SCL_CLOUD = (3, 8, 9, 10)


def commune_boxes(labels_dir: Path) -> list[dict]:
    out = []
    for b in sorted(Path(labels_dir).glob("*_calib_*_boundary.geojson")):
        g = gpd.read_file(b)
        out.append({
            "name": b.name.split("_calib_")[0],
            "geometry": g.geometry.iloc[0],
            "bounds": tuple(g.total_bounds),
        })
    return out


def commune_buildings(bounds, iso3):
    """VIDA footprints for a commune, fetched ONCE (the parquet scan is the slow part)."""
    from earthpv.buildings import fetch_vida_buildings

    bu = fetch_vida_buildings(bounds, iso3)
    return None if bu.empty else bu


def roof_mask(bu, transform, shape, crs):
    """Rasterise the commune's footprints onto one SCL window's own grid.

    Rebuilt per scene rather than cached on shape alone: a commune near an MGRS seam is
    covered by scenes in different UTM zones, so two windows can share a shape and mean
    entirely different ground. `all_touched` because at 20 m a single house selects no
    pixel centre, and an empty mask would silently report 0.0 snow, i.e. "no opportunity",
    which is the most misleading possible default for this measurement.
    """
    import rasterio.features

    geoms = bu.to_crs(crs).geometry.values
    return rasterio.features.geometry_mask(
        geoms, shape, transform, invert=True, all_touched=True
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", default="data/labels/france")
    ap.add_argument("--iso3", default="FRA")
    ap.add_argument("--winters", nargs="+", type=int, default=[2021, 2022, 2023, 2024])
    ap.add_argument("--max-scene-cloud", type=int, default=70,
                    help="STAC eo:cloud_cover prefilter, scene level")
    ap.add_argument("--max-cloud-frac", type=float, default=0.20,
                    help="Max cloud fraction OVER THE ROOFS for a scene to count")
    ap.add_argument("--min-snow", type=float, default=0.05,
                    help="Min snow fraction over the roofs for a scene to count")
    ap.add_argument("--out", default="results/france_snow_opportunity.csv")
    a = ap.parse_args()

    import rasterio
    import rasterio.warp
    import rasterio.windows

    from earthpv.imagery import _catalog

    cat = _catalog()
    rows = []
    for c in commune_boxes(Path(a.labels_dir)):
        for wy in a.winters:
            # A "winter" is Nov of wy through Mar of wy+1.
            window = f"{wy}-11-01/{wy + 1}-03-31"
            try:
                items = list(cat.search(
                    collections=["sentinel-2-l2a"], bbox=c["bounds"], datetime=window,
                    query={"eo:cloud_cover": {"lt": a.max_scene_cloud}},
                ).items())
            except Exception as e:  # noqa: BLE001
                log.warning("%s %s: search failed: %s", c["name"], wy, e)
                continue

            bu = commune_buildings(c["bounds"], a.iso3)
            if bu is None:
                log.warning("%s: no VIDA buildings; skipped", c["name"])
                break
            for it in items:
                href = it.assets.get("SCL")
                if href is None:
                    continue
                try:
                    with rasterio.open(href.href) as src:
                        # The commune bounds are lon/lat; SCL is UTM. Reprojecting them
                        # first is not optional -- `from_bounds` on raw degrees against a
                        # metre transform returns a sub-pixel window and reads a 0x0 array,
                        # which then looks exactly like "this scene had no roof pixels".
                        ub = rasterio.warp.transform_bounds(
                            "EPSG:4326", src.crs, *c["bounds"]
                        )
                        win = rasterio.windows.from_bounds(*ub, transform=src.transform)
                        arr = src.read(1, window=win, boundless=True, fill_value=0)
                        wt = src.window_transform(win)
                        if arr.size == 0:
                            continue
                        mask = roof_mask(bu, wt, arr.shape, src.crs)
                        if not mask.any():
                            continue
                        roofs = arr[mask]
                        valid = roofs[roofs > 0]
                        if valid.size == 0:
                            continue
                        snow = float((valid == SCL_SNOW).mean())
                        cloud = float(np.isin(valid, SCL_CLOUD).mean())
                except Exception as e:  # noqa: BLE001
                    log.debug("%s %s: SCL read failed: %s", c["name"], it.id, e)
                    continue
                rows.append({
                    "commune": c["name"], "winter": wy, "scene": it.id,
                    "date": str(it.datetime.date()),
                    "scene_cloud_pct": it.properties.get("eo:cloud_cover"),
                    "roof_snow_frac": round(snow, 4),
                    "roof_cloud_frac": round(cloud, 4),
                    "n_roof_px": int(valid.size),
                    "opportunity": bool(snow >= a.min_snow and cloud <= a.max_cloud_frac),
                })
            log.info("%s winter %s: %d scenes examined", c["name"], wy, len(items))

    df = pd.DataFrame(rows)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    if df.empty:
        print("no scenes examined")
        return 1

    print(f"\nscenes examined: {len(df)} across {df.commune.nunique()} communes, "
          f"{df.winter.nunique()} winters")
    print(f"opportunities (roof snow >= {a.min_snow}, roof cloud <= {a.max_cloud_frac}): "
          f"{int(df.opportunity.sum())}")
    per = df.groupby("commune").agg(
        scenes=("scene", "size"), opps=("opportunity", "sum"),
        max_roof_snow=("roof_snow_frac", "max"),
    ).sort_values("opps", ascending=False)
    per["opps_per_winter"] = (per.opps / df.winter.nunique()).round(2)
    print("\n", per.to_string())
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
