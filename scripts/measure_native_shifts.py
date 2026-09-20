"""Re-measure inter-acquisition sub-pixel shifts from NATIVE granules, no resampling.

`scripts/measure_subpixel_shifts.py` put the median inter-acquisition shift at 0.122 px
(1.22 m) and concluded multi-frame fusion has thin raw material here. That number is a LOWER
BOUND for a reason worth removing: it was measured on stacks loaded onto a geobox derived
from a bbox, which is not guaranteed aligned to the source MGRS grid, with the 10 m bands
loaded by NEAREST resampling. Either can quantise a true sub-pixel offset away before it is
ever measured.

Sentinel-2 L2A is delivered on a fixed MGRS tile grid, so every acquisition of the same tile
shares identical pixel geometry. Reading the same pixel window straight out of each scene's
own COG therefore involves no reprojection, no resampling and no grid choice by us -- the
only thing that can make the frames differ sub-pixel is residual geolocation error in ESA's
own geometric model, which is exactly the quantity multi-frame fusion consumes.

Also records the relative orbit per scene, because view geometry differs between orbits and
cross-orbit pairs are where diversity should concentrate. If it does, the actionable
conclusion is to choose a window spanning both orbits rather than simply a longer one.

    pixi run python scripts/measure_native_shifts.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
from rasterio.windows import from_bounds

from earthpv.imagery import _ES_BAND_FOR, _es_catalog
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("native_shifts")
MIN_VALID = 0.80


def _phase_shift():
    spec = importlib.util.spec_from_file_location(
        "pv_step_signal", Path("scripts/pv_step_signal.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._phase_shift


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--window", default="2025-11-01:2026-03-15")
    ap.add_argument("--max-items", type=int, default=14)
    ap.add_argument("--quadrats", type=int, default=12)
    ap.add_argument("--out", type=Path, default=Path("results/native_shifts.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ps = _phase_shift()
    d0, d1 = args.window.split(":")

    rows = []
    names = sorted(discover_quadrats(args.labels_dir))[: args.quadrats]
    for qi, stem in enumerate(names, 1):
        boundary, _ = load_quadrat(stem, args.labels_dir)
        items = sorted(
            _es_catalog().search(collections=["sentinel-2-l2a"], bbox=boundary.bounds,
                                 datetime=f"{d0}/{d1}",
                                 query={"eo:cloud_cover": {"lt": 30}}).items(),
            key=lambda it: it.properties.get("eo:cloud_cover", 100))[: args.max_items]
        if len(items) < 4:
            continue
        # One MGRS tile only: different tiles have different grids, and comparing across
        # them would measure the tiling, not the geolocation.
        tiles = [f"{i.properties['mgrs:utm_zone']}{i.properties['mgrs:latitude_band']}"
                 f"{i.properties['mgrs:grid_square']}" for i in items]
        main_tile = max(set(tiles), key=tiles.count)
        items = [i for i, t in zip(items, tiles) if t == main_tile]
        arrs, orbits, dates = [], [], []
        for it in items:
            href = it.assets[_ES_BAND_FOR["B08"]].href
            try:
                with rasterio.open(href) as src:
                    wb = rasterio.warp.transform_bounds("EPSG:4326", src.crs,
                                                        *boundary.bounds)
                    win = from_bounds(*wb, src.transform).round_offsets().round_lengths()
                    a = src.read(1, window=win).astype("float32")
            except Exception as e:  # noqa: BLE001
                log.warning("%s %s: %s", stem, it.id, str(e)[:60])
                continue
            if a.size == 0 or np.mean(a > 0) < MIN_VALID:
                continue
            a[a == 0] = np.nan
            arrs.append(a)
            orbits.append(int(it.properties.get("sat:relative_orbit", -1)))
            dates.append(str(it.datetime.date()))
        if len(arrs) < 4:
            continue
        shp = min(a.shape for a in arrs)
        arrs = [a[:shp[0], :shp[1]] for a in arrs]
        ref = int(np.argmax([np.isfinite(a).mean() for a in arrs]))
        for k, a in enumerate(arrs):
            if k == ref:
                continue
            dy, dx = ps(arrs[ref], a)
            if abs(dy) > 3 or abs(dx) > 3:
                continue
            rows.append({"quadrat": stem, "tile": main_tile, "date": dates[k],
                         "orbit": orbits[k], "ref_orbit": orbits[ref],
                         "same_orbit": orbits[k] == orbits[ref],
                         "dy": dy, "dx": dx, "mag": float(np.hypot(dy, dx))})
        log.info("[%d/%d] %-34s tile %s, %d frames, %d orbits", qi, len(names), stem,
                 main_tile, len(arrs), len(set(orbits)))

    d = pd.DataFrame(rows)
    d.to_csv("results/native_shifts_frames.csv", index=False)
    frac = np.minimum(np.mod(d.mag, 1.0), 1 - np.mod(d.mag, 1.0))
    out = {
        "n_pairs": int(len(d)), "n_quadrats": int(d.quadrat.nunique()),
        "median_shift_px": round(float(d.mag.median()), 3),
        "median_shift_m": round(float(d.mag.median() * 10), 2),
        "p90_shift_px": round(float(d.mag.quantile(0.9)), 3),
        "share_above_0p2px": round(float((d.mag > 0.2).mean()), 3),
        "share_above_0p5px": round(float((d.mag > 0.5).mean()), 3),
        "median_subpixel_offset": round(float(frac.median()), 3),
        "composite_grid_median_px": 0.122,
    }
    if d.same_orbit.nunique() > 1:
        out["median_shift_same_orbit_px"] = round(float(d[d.same_orbit].mag.median()), 3)
        out["median_shift_cross_orbit_px"] = round(float(d[~d.same_orbit].mag.median()), 3)
        out["n_same_orbit"] = int(d.same_orbit.sum())
        out["n_cross_orbit"] = int((~d.same_orbit).sum())
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
