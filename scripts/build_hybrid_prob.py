#!/usr/bin/env python
"""Combine two runs' probability rasters by outline size: one model everywhere, the other
inside its own large outlines.

California's localized ResNet (v38r) finds more small arrays than its TerraMind (v38) but
misses much of the state's largest parks (docs/results/california.md). This writes a third
run whose `prob/<cell>.tif` is the BASE run's probability everywhere, and the higher of the
two runs' inside every outline of the LARGE run's `candidates.parquet` of at least
`--min-area-m2`. Thresholded at the shared threshold, that is the base run's mask plus the
large run's large outlines. Everything downstream (postprocess, calibrate-candidates, the
reviews, density, the atlas) runs on the result as on any run.

    pixi run python scripts/build_hybrid_prob.py --aoi california \\
        --base-pred data/predictions_resnet_20261119 --large-pred data/predictions \\
        --min-area-m2 300000 --out-dir data/predictions_hybrid_20261120

Both runs must share the cell grid (the same composites). Writes `<out>/<aoi>/prob/` and
`<out>/<aoi>/hybrid.json` (the inputs and what changed).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--base-pred", type=Path, required=True,
                    help="prediction directory of the model used everywhere")
    ap.add_argument("--large-pred", type=Path, required=True,
                    help="prediction directory of the model used inside its large outlines")
    ap.add_argument("--min-area-m2", type=float, required=True)
    ap.add_argument("--threshold", type=float, default=None,
                    help="only to report how many pixels cross it (no effect on the rasters)")
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()

    base = REPO / a.base_pred / a.aoi / "prob"
    large = REPO / a.large_pred / a.aoi / "prob"
    out = REPO / a.out_dir / a.aoi / "prob"
    out.mkdir(parents=True, exist_ok=True)
    cands = gpd.read_parquet(REPO / a.large_pred / a.aoi / "candidates.parquet")
    gate = cands[cands["area_m2"] >= a.min_area_m2]
    by_crs: dict = {}
    files = sorted(base.glob("*.tif"))
    missing = [f.name for f in files if not (large / f.name).exists()]
    if missing:
        raise SystemExit(f"{len(missing)} cells of the base run have no raster in the large run, "
                         f"e.g. {missing[:3]}")
    thr = None if a.threshold is None else round(a.threshold * 255)
    n_touched = gate_px = raised_px = crossed_px = 0
    for f in files:
        with rasterio.open(f) as rb, rasterio.open(large / f.name) as rl:
            if (rb.crs, rb.transform, rb.shape) != (rl.crs, rl.transform, rl.shape):
                raise SystemExit(f"{f.name}: the two runs' rasters are not on the same grid")
            pb, pl, prof = rb.read(1), rl.read(1), rb.profile
            if rb.crs not in by_crs:
                by_crs[rb.crs] = gate.to_crs(rb.crs)
            g = by_crs[rb.crs]
            g = g[g.intersects(box(*rb.bounds))]
            res = pb
            if len(g):
                m = rasterize(((geom, 1) for geom in g.geometry), out_shape=rb.shape,
                              transform=rb.transform, fill=0, dtype="uint8").astype(bool)
                if m.any():
                    res = pb.copy()
                    res[m] = np.maximum(pb[m], pl[m])
                    n_touched += 1
                    gate_px += int(m.sum())
                    raised_px += int((res != pb).sum())
                    if thr is not None:
                        crossed_px += int(((res >= thr) & (pb < thr)).sum())
        tmp = out / (f.name + ".tmp")
        with rasterio.open(tmp, "w", **prof) as w:
            w.write(res, 1)
        tmp.replace(out / f.name)
    rec = {"aoi": a.aoi, "base_pred": str(a.base_pred), "large_pred": str(a.large_pred),
           "min_area_m2": a.min_area_m2, "n_gate_outlines": int(len(gate)),
           "gate_km2": round(float(gate["area_m2"].sum()) / 1e6, 3), "n_cells": len(files),
           "n_cells_touched": n_touched, "gate_px": gate_px, "raised_px": raised_px,
           "threshold": a.threshold, "crossed_threshold_px": crossed_px if thr is not None else None}
    (out.parent / "hybrid.json").write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
