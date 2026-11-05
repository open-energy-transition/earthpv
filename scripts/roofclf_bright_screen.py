#!/usr/bin/env python
"""Where are Pakistan's roofs brighter in NIR/SWIR than any calibration area's?

roofclf over-credits roofs that are bright in NIR and SWIR (mean of B08, B8A, B11, B12):
leave-one-quadrat-out, the brightest 5% of calibration roofs are priced at 2.6x their
mapped PV area below 400 m2 and 5.1x above, and 83% of national roofs beyond the
calibration roofs' 99th percentile sit in neighbourhoods brighter than nearly any
calibration neighbourhood (2026-11-05). This screen finds those landscapes so calibration
areas can be drawn in them (`propose_calibration_candidates.py --bright`).

Per in-domain cell (the density-calibrated domain, `density.CALIBRATED_BLDG_DENSITY_KM2`),
every building the national scoring scored gets its NIR+SWIR from the same composite and
the same feature code the scoring used (`roofclf.epoch_feature_frame`), so the numbers are
on the calibration table's scale. They are aggregated into 0.005 deg sub-squares (count,
score mass p x roof area, score mass on roofs beyond the calibration p99, a 64-bin NIR+SWIR
histogram), from which `windows.parquet` builds 0.01 deg windows on a 0.005 deg stride.

  pixi run python scripts/roofclf_bright_screen.py [--workers 3]   # resumable per cell

Outputs under data/roofclf_bright_screen/pakistan/: cells/<cell>.parquet (sub-squares),
windows.parquet, reference.json (calibration quantiles the screen is measured against).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv import roofclf  # noqa: E402
from earthpv.compose import CELL_DEG  # noqa: E402
from earthpv.config import Settings  # noqa: E402
from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2, _grid_origin  # noqa: E402
from earthpv.labels import resolve_aoi  # noqa: E402
from earthpv.local_source import composite_index  # noqa: E402

AOI = "pakistan"
OUT = Path("data/roofclf_bright_screen") / AOI
PROB = Path("data/roofclf_national_with_sppi") / AOI / "prob"
CAL_TABLE = Path("data/roofclf/buildings.geoparquet")
NS_BANDS = ["b08_mean", "b8a_mean", "b11_mean", "b12_mean"]
SUB_DEG = 0.005
HIST_EDGES = np.linspace(0.05, 0.65, 65)   # NIR+SWIR reflectance; outside clips to the end bins
log = logging.getLogger("bright_screen")


def reference() -> dict:
    t = pd.read_parquet(CAL_TABLE, columns=["quadrat"] + NS_BANDS)
    ns = t[NS_BANDS].mean(axis=1)
    qmed = ns.groupby(t.quadrat).median()
    return {"cal_p95": float(ns.quantile(0.95)), "cal_p99": float(ns.quantile(0.99)),
            "quadrat_median_max": float(qmed.max()), "quadrat_median_argmax": str(qmed.idxmax()),
            "quadrat_medians": {k: round(float(v), 4) for k, v in qmed.items()}}


_CTX: dict = {}


def _init(cfg_items):
    logging.disable(logging.WARNING)
    _CTX["comp"] = composite_index("data/composites/pakistan", layers=1)
    _CTX.update(cfg_items)


def one_cell(row: dict) -> str:
    import geopandas as gpd
    out = OUT / "cells" / f"{row['cell']}.parquet"
    if out.exists():
        return f"{row['cell']}: cached"
    t0 = time.time()
    bu = gpd.read_parquet(PROB / f"{row['cell']}.parquet")
    if bu.empty:
        pd.DataFrame().to_parquet(out)
        return f"{row['cell']}: empty"
    bu["area_m2"] = bu["roof_area_m2"]             # the name epoch_feature_frame reads
    bbox = (row["lon0"], row["lat0"], row["lon0"] + CELL_DEG, row["lat0"] + CELL_DEG)
    arr, transform, crs = _CTX["comp"].read_window(bbox)
    fd, _ = roofclf.epoch_feature_frame(bu, arr, transform, crs, 0, None, False)
    ns = fd[NS_BANDS].mean(axis=1).to_numpy(float)
    p = bu.p_roofclf.to_numpy(float)
    r = bu.roof_area_m2.to_numpy(float)
    pt = bu.geometry.representative_point()
    ix = np.floor(pt.x.to_numpy() / SUB_DEG).astype(np.int64)
    iy = np.floor(pt.y.to_numpy() / SUB_DEG).astype(np.int64)
    ok = np.isfinite(ns) & np.isfinite(p)
    bright = ns > _CTX["cal_p99"]
    mass = np.where(ok, p * r, 0.0)
    h = np.clip(np.digitize(ns, HIST_EDGES) - 1, 0, len(HIST_EDGES) - 2)
    df = pd.DataFrame({"ix": ix, "iy": iy, "n": ok.astype(np.int32), "n_bright": (ok & bright).astype(np.int32),
                       "mass": mass, "mass_bright": np.where(bright, mass, 0.0),
                       "mass_ge400": np.where(r >= 400, mass, 0.0),
                       "mass_bright_ge400": np.where(bright & (r >= 400), mass, 0.0), "h": h})
    agg = df.groupby(["ix", "iy"]).agg(n=("n", "sum"), n_bright=("n_bright", "sum"), mass=("mass", "sum"),
                                       mass_bright=("mass_bright", "sum"), mass_ge400=("mass_ge400", "sum"),
                                       mass_bright_ge400=("mass_bright_ge400", "sum"))
    hist = pd.crosstab([df.ix, df.iy], df.h).reindex(columns=range(len(HIST_EDGES) - 1), fill_value=0)
    agg = agg.join(hist.rename(columns=lambda c: f"h{c}")).reset_index()
    agg["cell"] = row["cell"]
    agg.to_parquet(out)
    return f"{row['cell']}: {len(bu):,} bldgs, {int(bright[ok].sum()):,} beyond cal p99, {time.time() - t0:.0f}s"


def windows(ref: dict) -> pd.DataFrame:
    S = pd.concat([pd.read_parquet(p) for p in sorted((OUT / "cells").glob("*.parquet"))
                   if p.stat().st_size > 0], ignore_index=True)
    S = S.drop(columns="cell").groupby(["ix", "iy"]).sum().reset_index()   # cell-edge sub-squares
    num = [c for c in S.columns if c not in ("ix", "iy")]
    key = S.set_index(["ix", "iy"])[num]
    parts = []
    for dx in (0, 1):
        for dy in (0, 1):
            k = key.copy()
            k.index = pd.MultiIndex.from_arrays([k.index.get_level_values(0) - dx, k.index.get_level_values(1) - dy])
            parts.append(k)
    W = pd.concat(parts).groupby(level=[0, 1]).sum()
    W.index.names = ["ix", "iy"]
    W = W.reset_index()
    H = W[[f"h{i}" for i in range(len(HIST_EDGES) - 1)]].to_numpy()
    cum = np.cumsum(H, axis=1)
    mid = (HIST_EDGES[:-1] + HIST_EDGES[1:]) / 2
    W["ns_median"] = mid[np.argmax(cum >= (cum[:, -1:] / 2), axis=1)]
    W["lon0"], W["lat0"] = W.ix * SUB_DEG, W.iy * SUB_DEG
    clat = W.lat0 + SUB_DEG
    W["area_km2"] = (2 * SUB_DEG * 111.32 * np.cos(np.radians(clat))) * (2 * SUB_DEG * 110.54)
    W["density_km2"] = W.n / W.area_km2
    W["share_bright"] = W.n_bright / W.n.clip(lower=1)
    W["brighter_than_every_area"] = W.ns_median > ref["quadrat_median_max"]
    return W.drop(columns=[f"h{i}" for i in range(len(HIST_EDGES) - 1)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    (OUT / "cells").mkdir(parents=True, exist_ok=True)
    ref = reference()
    (OUT / "reference.json").write_text(json.dumps(ref, indent=1))
    print(f"calibration NIR+SWIR p95 {ref['cal_p95']:.4f}, p99 {ref['cal_p99']:.4f}; brightest area's "
          f"median roof {ref['quadrat_median_max']:.4f} ({ref['quadrat_median_argmax']})", flush=True)
    settings = Settings.load()
    _, cfg = resolve_aoi(AOI, settings)
    dens = pd.read_parquet("data/roofclf/national_cell_density.parquet")
    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    dom = set(dens[(dens.density > lo) & (dens.density < hi)].cell)
    man = roofclf.canonical_composite_manifest(composite_index("data/composites/pakistan", layers=1),
                                               _grid_origin(AOI, cfg, settings), CELL_DEG)
    man = man[man.cell.isin(dom) & man.cell.map(lambda c: (PROB / f"{c}.parquet").exists())]
    rows = man[["cell", "lon0", "lat0"]].to_dict("records")
    print(f"{len(rows)} in-domain cells with a national scoring", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=({"cal_p99": ref["cal_p99"]},)) as ex:
        for k, msg in enumerate(ex.map(one_cell, rows, chunksize=4), 1):
            if k % 50 == 0 or k == len(rows):
                print(f"[{k}/{len(rows)} {time.time() - t0:.0f}s] {msg}", flush=True)
    W = windows(ref)
    W.to_parquet(OUT / "windows.parquet")
    print(f"{len(W):,} windows; {int(W.brighter_than_every_area.sum()):,} with a median roof brighter than every "
          f"calibration area's; national score mass beyond cal p99 {W.mass_bright.sum() / 4 / (W.mass.sum() / 4):.3f}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
