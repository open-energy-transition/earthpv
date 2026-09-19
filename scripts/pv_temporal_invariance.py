"""Is a PV array's reflectance actually constant over time? The premise, measured directly.

Temporal unmixing assumes the PV endmember is time-invariant while the background moves,
so a mixed pixel's temporal spread is DAMPED in proportion to its PV fraction. That
assumption is worth testing on its own, because a tilted panel is specular, and this
project's whole glint subsystem exists because a panel's apparent brightness changes with
sun and view geometry. If PV pixels move MORE than diffuse roof pixels, the sign of the
estimator is backwards and the fraction interpretation is void.

Compares, per quadrat: per-pixel temporal MAD inside mapped PV polygons against roof pixels
with no mapped PV, using the same saved scene stacks the estimator reads.

    pixi run python scripts/pv_temporal_invariance.py --aoi pakistan
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import rasterio.features

from earthpv.preprocess import _robust_spread, load_scene_stack
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("pv_temporal_invariance")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--composites", type=Path, default=None)
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--iso3", default="PAK")
    ap.add_argument("--out", type=Path, default=Path("results/pv_temporal_invariance.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    composites = args.composites or Path("data/composites") / args.aoi

    from earthpv.buildings import fetch_vida_buildings
    from earthpv import overture
    con = overture.connect()

    rows = []
    for stem in sorted(discover_quadrats(args.labels_dir)):
        loaded = load_scene_stack(composites, stem)
        if loaded is None:
            continue
        stack, transform, crs = loaded
        boundary, pv = load_quadrat(stem, args.labels_dir)
        if pv.empty:
            continue
        shape = stack.shape[-2:]
        pv_m = rasterio.features.rasterize(
            ((g, 1) for g in pv.to_crs(crs).geometry), out_shape=shape,
            transform=transform, fill=0, dtype="uint8").astype(bool)
        bu = fetch_vida_buildings(boundary.bounds, args.iso3, con=con)
        if bu.empty:
            continue
        roof_m = rasterio.features.rasterize(
            ((g, 1) for g in bu.to_crs(crs).geometry), out_shape=shape,
            transform=transform, fill=0, dtype="uint8").astype(bool)
        # Roof pixels with no mapped PV are the control: same material class, same
        # neighbourhood, differing only in whether an array sits there.
        ctrl_m = roof_m & ~pv_m
        # The third class is the one that decides whether the estimator can work at all:
        # the NON-BUILT background, which is what a building's damping is divided by.
        open_m = ~roof_m & ~pv_m
        spread = _robust_spread(stack)                 # (band, y, x)
        vis = np.nanmean(spread[[0, 1, 2, 6]], axis=0)  # B02 B03 B04 B08
        swir = np.nanmean(spread[[8, 9]], axis=0)       # B11 B12
        if pv_m.sum() < 20 or ctrl_m.sum() < 20:
            continue
        r = {"quadrat": stem, "n_pv_px": int(pv_m.sum()), "n_ctrl_px": int(ctrl_m.sum())}
        for lab, f in (("vis", vis), ("swir", swir)):
            a, b, o = f[pv_m], f[ctrl_m], f[open_m]
            r[f"mad_pv_{lab}"] = round(float(np.nanmedian(a)), 1)
            r[f"mad_ctrl_{lab}"] = round(float(np.nanmedian(b)), 1)
            r[f"mad_open_{lab}"] = round(float(np.nanmedian(o)), 1)
            r[f"ratio_{lab}"] = round(float(np.nanmedian(a) / max(np.nanmedian(b), 1e-6)), 3)
            # How much more the open background moves than a roof does. If this is ~1 the
            # roofs are at the same floor as their surroundings and there is no dynamic
            # background to normalise against, whatever the quadrat-wide amplitude says.
            r[f"open_over_roof_{lab}"] = round(
                float(np.nanmedian(o) / max(np.nanmedian(b), 1e-6)), 3)
        rows.append(r)
        log.info("%-34s PV %4.0f  roof %4.0f  open %4.0f DN | PV/roof %.2f  open/roof %.2f",
                 stem, r["mad_pv_vis"], r["mad_ctrl_vis"], r["mad_open_vis"],
                 r["ratio_vis"], r["open_over_roof_vis"])

    if not rows:
        raise SystemExit("no quadrat had both a scene stack and mapped PV")
    rv = np.array([r["ratio_vis"] for r in rows])
    rs = np.array([r["ratio_swir"] for r in rows])
    oo = np.array([r["open_over_roof_vis"] for r in rows])
    summary = {
        "n_quadrats": len(rows),
        "ratio_vis_median": round(float(np.median(rv)), 3),
        "ratio_swir_median": round(float(np.median(rs)), 3),
        "quadrats_pv_more_variable_vis": int((rv > 1).sum()),
        "quadrats_pv_more_variable_swir": int((rs > 1).sum()),
        "open_over_roof_vis_median": round(float(np.median(oo)), 3),
        "per_quadrat": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_quadrat"}, indent=2))


if __name__ == "__main__":
    main()
