"""Step 2: does imagery from a predicted glint date give `roofclf` a stronger PV signal?

The hypothesis: `roofclf` reads a dry-season MEDIAN composite, and a median over ~12 scenes
is designed to suppress exactly the transient specular events that mark a panel. Reading the
few dates when panels here are geometrically able to glint should therefore raise the
signal-to-noise ratio, most of all in dense urban blocks where many installations would
brighten at once.

Tested on the Lahore quadrat: 6.61 km2, 13,500 buildings, 3,432 of them carrying mapped PV
(the densest ground truth in the project, and exactly the dense-urban case the idea targets).

Measures, per building:
  glint_max   -- max reflectance over the glint-window scenes (the specular event, if any)
  glint_ratio -- glint_max / the same building's median-composite brightness

then reports (a) standalone AUC of each against `has_pv`, (b) AUC within roof-size band, and
(c) the INCREMENTAL AUC on top of `roofclf.MODEL_FEATURES` under a spatial train/test split.
(c) is the number that decides it: a feature can separate PV on its own and still add
nothing to a model that already has size and reflectance.

Spatial, not random, splitting: buildings 20 m apart share pixels and roof material, so a
random fold reports the optimism of memorising neighbourhoods. West/east halves of the
boundary are used instead.

Usage:
  .pixi/envs/default/bin/python scripts/glint_date_roofclf_feature.py [--n-dates 6]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import rasterio  # noqa: E402

from earthpv import glint, roofclf  # noqa: E402

log = logging.getLogger("glint_feature")

QUADRAT = "lahore"
STEM = "lahore_calib_6p61km2"
START = datetime(2024, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)
TOL_DEG = 6.0     # the wider lobe: this is a feature, not a detection threshold, so admit
                  # marginal geometry and let the classifier decide what it is worth
BANDS = ("B03", "B08")
MAX_RING_CLOUD = 0.20
OUT_DIR = Path("results/glint_date_feature")


def glint_window_dates(lon: float, lat: float, n_dates: int, prior: dict) -> pd.DataFrame:
    """The `n_dates` scenes that would light up the largest share of an assumed installed
    pose population, with their per-scene lit fraction. Reuses Step 1's machinery so the two
    steps cannot disagree about which dates are optimal."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import glint_observability_ceiling as ceil

    geom = ceil.fetch_geometry(lon, lat)
    if geom.empty:
        raise RuntimeError("no granule geometry for the Lahore quadrat")
    tilt, az = ceil.sample_poses(prior)
    lit = ceil.per_scene_lit_fraction(geom, tilt, az, TOL_DEG)
    g = geom.assign(lit_frac=lit).sort_values("lit_frac", ascending=False)
    return g.head(n_dates).reset_index(drop=True)


def read_scene_for_buildings(item, provider: str, bu_utm: gpd.GeoDataFrame,
                             bounds4326: tuple) -> dict | None:
    """Per-building mean/max of each band on one scene, plus its SCL cloud fraction.

    Reads a single window covering the whole quadrat once per band, then does zonal stats
    with `roofclf.zonal_mean_max` -- the same reader `building_table` uses for the composite,
    so the glint-date feature and the baseline features are measured the same way.
    """
    out: dict[str, np.ndarray] = {}
    try:
        for band in BANDS:
            href = item.assets[glint._band_asset_key(band, provider)].href
            with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
                win = rasterio.windows.from_bounds(
                    *rasterio.warp.transform_bounds("EPSG:4326", src.crs, *bounds4326),
                    transform=src.transform,
                )
                arr = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
                wt = src.window_transform(win)
                if src.crs != bu_utm.crs:
                    return None
                # zonal_mean_max is band-major: a 2D window comes back as (1, n_buildings),
                # so take band 0 rather than assigning a length-1 array to 13,500 rows.
                mean, mx = roofclf.zonal_mean_max(bu_utm, arr, wt, nodata=0.0)
            offset = glint._boa_offset(item, provider)
            out[f"{band}_mean"] = np.asarray(mean)[0] + offset
            out[f"{band}_max"] = np.asarray(mx)[0] + offset
        # Cloud: one fraction for the whole quadrat window is enough to accept/reject the
        # date, and it is the same SCL evidence `annotate_spikes` gates spikes on.
        href = item.assets[glint._band_asset_key("SCL", provider)].href
        with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
            win = rasterio.windows.from_bounds(
                *rasterio.warp.transform_bounds("EPSG:4326", src.crs, *bounds4326),
                transform=src.transform,
            )
            scl = src.read(1, window=win, boundless=True, fill_value=0)
        valid = scl != 0
        out["cloud_frac"] = float(np.isin(scl, glint.SCL_CLOUD_CLASSES)[valid].mean()) if valid.any() else np.nan
    except Exception as e:  # noqa: BLE001 -- a bad scene is skipped, not fatal
        log.warning("scene %s failed: %s", item.id, e)
        return None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-dates", type=int, default=6,
                    help="how many top glint-window scenes to combine into the max")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bu = gpd.read_parquet("data/roofclf/buildings.geoparquet")
    lah = bu[bu.quadrat == QUADRAT].reset_index(drop=True)
    log.info("%s: %d buildings, %d with PV (%.1f%%)",
             QUADRAT, len(lah), int(lah.has_pv.sum()), 100 * lah.has_pv.mean())
    b = roofclf.load_boundary(Path("data/labels") / f"{STEM}_boundary.geojson")
    lon, lat = b.representative_point().x, b.representative_point().y
    bounds4326 = tuple(gpd.GeoSeries([b], crs="EPSG:4326").buffer(0.003).total_bounds)

    utm = gpd.GeoSeries([b], crs="EPSG:4326").estimate_utm_crs()
    bu_utm = lah.set_geometry(lah.geometry).to_crs(utm)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import glint_observability_ceiling as ceil

    dates = glint_window_dates(lon, lat, args.n_dates, ceil.POSE_PRIORS["textbook_south"])
    log.info("top %d glint-window dates (lit fraction at tol %.0f deg):\n%s", args.n_dates,
             TOL_DEG, dates[["time", "lit_frac"]].to_string(index=False))

    items = glint._search_items_bbox("planetary-computer", bounds4326, START, END, 100)
    by_key = {}
    for it in items:
        by_key.setdefault(pd.to_datetime(it.datetime).strftime("%Y%m%d%H%M"), []).append(it)

    per_scene, used = [], []
    for r in dates.itertuples():
        key = pd.to_datetime(r.time).strftime("%Y%m%d%H%M")
        cands = by_key.get(key) or by_key.get(pd.to_datetime(r.time).strftime("%Y%m%d")[:8], [])
        if not cands:
            cands = [it for k, v in by_key.items() if k[:8] == key[:8] for it in v]
        got = None
        for it in cands:
            res = read_scene_for_buildings(it, "planetary-computer", bu_utm, bounds4326)
            if res and np.isfinite(res["B03_mean"]).sum() > 0.5 * len(bu_utm):
                got = (it, res)
                break
        if got is None:
            log.warning("no readable scene for %s", key)
            continue
        it, res = got
        if res["cloud_frac"] is not None and res["cloud_frac"] > MAX_RING_CLOUD:
            log.info("skipping %s: %.0f%% cloud over the quadrat", key, 100 * res["cloud_frac"])
            continue
        per_scene.append(res)
        used.append(dict(key=key, item=it.id, lit_frac=float(r.lit_frac),
                         cloud_frac=res["cloud_frac"]))
        log.info("used %s (%s) lit %.1f%% cloud %.1f%%", key, it.id,
                 100 * r.lit_frac, 100 * (res["cloud_frac"] or 0))

    if not per_scene:
        raise SystemExit("no usable glint-window scene: nothing to test")

    # The feature: brightest response across the glint window, and its ratio to the
    # building's own median-composite brightness (which is what roofclf already sees).
    gmax = np.nanmax(np.stack([s["B03_max"] for s in per_scene]), axis=0)
    gmax8 = np.nanmax(np.stack([s["B08_max"] for s in per_scene]), axis=0)
    lah["glint_max"] = gmax / roofclf.REFL_SCALE
    lah["glint_max_b08"] = gmax8 / roofclf.REFL_SCALE
    base = (lah.b03_mean + lah.b08_mean).clip(lower=1e-6)
    lah["glint_ratio"] = (lah.glint_max + lah.glint_max_b08) / base
    lah["glint_excess"] = (lah.glint_max - lah.b03_mean) + (lah.glint_max_b08 - lah.b08_mean)

    y = lah.has_pv.to_numpy().astype(int)
    rows = []
    for feat in ("glint_max", "glint_max_b08", "glint_ratio", "glint_excess",
                 "brightness", "b03_mean"):
        s = lah[feat].to_numpy(dtype=float)
        ok = np.isfinite(s)
        rows.append(dict(feature=feat, n=int(ok.sum()),
                         auc=round(roofclf.auc(y[ok], s[ok]), 4),
                         auc_within_size=round(roofclf.auc_within_size(
                             y[ok], s[ok], lah.roof_area_m2.to_numpy()[ok])[0], 4)))
    standalone = pd.DataFrame(rows)
    print("\n=== standalone separation (has_pv), Lahore ===")
    print(standalone.to_string(index=False))

    # Incremental value, spatial west/east split.
    cx = lah.geometry.representative_point().x
    west = cx < cx.median()
    results = []
    for name, feats in (("baseline (size+reflectance)", roofclf.MODEL_FEATURES),
                        ("+ glint_ratio", roofclf.MODEL_FEATURES + ["glint_ratio"]),
                        ("+ glint_excess", roofclf.MODEL_FEATURES + ["glint_excess"]),
                        ("+ glint_max both bands",
                         roofclf.MODEL_FEATURES + ["glint_max", "glint_max_b08"])):
        for train_mask, label in ((west, "train W / test E"), (~west, "train E / test W")):
            d = lah.copy()
            X = roofclf.design_matrix(d, feats)
            good = np.isfinite(X).all(axis=1)
            tr, te = train_mask.to_numpy() & good, (~train_mask.to_numpy()) & good
            model = roofclf.fit_logistic(X[tr], y[tr])
            p = roofclf.predict_proba(model, X[te])
            results.append(dict(features=name, split=label, n_train=int(tr.sum()),
                                n_test=int(te.sum()),
                                auc=round(roofclf.auc(y[te], p), 4),
                                auc_within_size=round(roofclf.auc_within_size(
                                    y[te], p, lah.roof_area_m2.to_numpy()[te])[0], 4)))
    inc = pd.DataFrame(results)
    print("\n=== incremental value on top of roofclf's own features (spatial holdout) ===")
    print(inc.to_string(index=False))
    piv = inc.groupby("features")[["auc", "auc_within_size"]].mean().round(4)
    print("\nmean over both splits:")
    print(piv.to_string())

    standalone.to_csv(OUT_DIR / "standalone_auc.csv", index=False)
    inc.to_csv(OUT_DIR / "incremental_auc.csv", index=False)
    lah[["roof_area_m2", "has_pv", "pv_area_true_m2", "glint_max", "glint_max_b08",
         "glint_ratio", "glint_excess", "brightness", "b03_mean", "b08_mean"]].to_parquet(
        OUT_DIR / "lahore_glint_features.parquet")
    (OUT_DIR / "dates_used.json").write_text(json.dumps(
        dict(quadrat=QUADRAT, tol_deg=TOL_DEG, n_dates_requested=args.n_dates,
             dates=used, n_buildings=int(len(lah)), n_pv=int(y.sum())), indent=2, default=str))
    print(f"\n-> {OUT_DIR}")


if __name__ == "__main__":
    main()
