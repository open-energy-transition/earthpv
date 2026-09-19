"""Does a high-sun window give more PV contrast than the dry-season one we composite in?

Measured 2026-09-19 over 239 winter scenes: the PV-vs-roof separation strengthens with solar
elevation, d' = -1.296 + 0.0145 x sun_zenith, because a higher sun brightens the roof while
the panel stays dark (Spearman(sun_zenith, roof brightness) = -0.520). The Nov-Mar compose
window only samples sun zenith 36.8-59.4 deg, so the fit's prediction for summer is an
EXTRAPOLATION -- roughly double the contrast at 20 deg. This measures it instead.

Pakistan's high-sun months are mostly monsoon, so the window used here is PRE-MONSOON May to
mid-June: dry, and the highest sun available without cloud.

Paired by quadrat against the winter scenes already scored in
`results/glint_geometry_snr_scenes.csv`, with identical PV and roof masks, so the only thing
that differs is when the sensor looked.

    pixi run python scripts/summer_window_contrast.py --quadrats 10
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio.features

from earthpv.compose import quadrat_geobox
from earthpv.imagery import scene_stack
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("summer_window")
VIS_NIR = [0, 1, 2, 6]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--iso3", default="PAK")
    ap.add_argument("--window", default="2026-05-01:2026-06-15")
    ap.add_argument("--quadrats", type=int, default=10)
    ap.add_argument("--winter", type=Path,
                    default=Path("results/glint_geometry_snr_scenes.csv"))
    ap.add_argument("--out", type=Path, default=Path("results/summer_window_contrast.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    window = tuple(args.window.split(":"))

    winter = pd.read_csv(args.winter)
    # Prefer the quadrats with the most PV pixels: the d' estimate is least noisy there.
    order = (winter.groupby("quadrat").n_pv_px.median().sort_values(ascending=False).index)
    names = [q for q in order if q in set(discover_quadrats(args.labels_dir))][: args.quadrats]
    log.info("%d quadrats: %s", len(names), ", ".join(n.split("_calib")[0] for n in names))

    out_dir = args.composites / "stacks_summer"
    out_dir.mkdir(parents=True, exist_ok=True)
    from earthpv import overture
    from earthpv.buildings import fetch_vida_buildings
    con = overture.connect()

    rows = []
    for i, stem in enumerate(names, 1):
        t0 = time.time()
        npz = out_dir / f"{stem}.npz"
        boundary, pv = load_quadrat(stem, args.labels_dir)
        gb = quadrat_geobox(args.composites, boundary, 200.0)
        if gb is None or pv.empty:
            continue
        gbox, bbox = gb
        if npz.exists():
            z = np.load(npz, allow_pickle=False)
            stack = z["stack"].astype("float32")
            stack[stack == 0] = np.nan
            dates = [str(d) for d in z["dates"]]
            transform, crs = rasterio.Affine(*z["transform"]), str(z["crs"])
        else:
            res = scene_stack(bbox, date_range=window, geobox=gbox)
            if res is None:
                log.warning("%s: no summer scenes", stem)
                continue
            stack, dates, transform, crs = res
            np.savez_compressed(npz, stack=np.nan_to_num(stack, nan=0.0).clip(0, 65535)
                                .astype("uint16"), dates=np.array(dates),
                                transform=np.array(transform).reshape(-1)[:6], crs=str(crs))
        shape = stack.shape[-2:]
        pv_m = rasterio.features.rasterize(
            ((g, 1) for g in pv.to_crs(crs).geometry), out_shape=shape,
            transform=transform, fill=0, dtype="uint8").astype(bool)
        bu = fetch_vida_buildings(boundary.bounds, args.iso3, con=con)
        roof_m = rasterio.features.rasterize(
            ((g, 1) for g in bu.to_crs(crs).geometry), out_shape=shape,
            transform=transform, fill=0, dtype="uint8").astype(bool)
        ctrl_m = roof_m & ~pv_m
        if pv_m.sum() < 20 or ctrl_m.sum() < 50:
            continue
        for t, d in enumerate(dates):
            vis = np.nanmean(stack[t][VIS_NIR], axis=0)
            a, c = vis[pv_m], vis[ctrl_m]
            a, c = a[np.isfinite(a)], c[np.isfinite(c)]
            if len(a) < 20 or len(c) < 50:
                continue
            s = np.sqrt(0.5 * (np.var(a) + np.var(c)))
            rows.append({"quadrat": stem, "date": d, "season": "summer",
                         "dprime": float((np.mean(a) - np.mean(c)) / s),
                         "pv_mean": float(np.mean(a)), "roof_mean": float(np.mean(c)),
                         "n_pv_px": int(len(a))})
        log.info("[%d/%d] %s: %d summer scenes, %.0fs", i, len(names), stem,
                 sum(r["quadrat"] == stem for r in rows), time.time() - t0)

    s = pd.DataFrame(rows)
    s.to_csv("results/summer_window_contrast_scenes.csv", index=False)
    from scipy import stats
    w = winter[winter.quadrat.isin(s.quadrat.unique())]
    per = (s.groupby("quadrat").dprime.median().rename("summer")
           .to_frame().join(w.groupby("quadrat").dprime.median().rename("winter")))
    per["gain"] = per.summer.abs() / per.winter.abs()
    out = {"window": args.window, "n_quadrats": int(len(per)),
           "n_summer_scenes": int(len(s)), "n_winter_scenes": int(len(w)),
           "median_dprime_summer": round(float(per.summer.median()), 3),
           "median_dprime_winter": round(float(per.winter.median()), 3),
           "median_contrast_gain": round(float(per.gain.median()), 2),
           "quadrats_summer_better": int((per.summer.abs() > per.winter.abs()).sum()),
           "roof_brightness_summer": round(float(s.roof_mean.median()), 1),
           "roof_brightness_winter": round(float(w.roof_mean.median()), 1)}
    if len(per) >= 5:
        out["wilcoxon_p"] = round(float(stats.wilcoxon(per.summer.abs(),
                                                       per.winter.abs()).pvalue), 4)
    per.round(3).to_csv("results/summer_window_contrast_by_quadrat.csv")
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
