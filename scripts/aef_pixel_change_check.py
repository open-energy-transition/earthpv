"""Does an AlphaEarth pixel see a panel being installed, or only its neighbourhood changing?

Companion to `run_aef_embedding_ablation.py`, read from the windows it caches (no network).
A building-level LOQO gain cannot by itself say whether the embedding resolves the roof:
`roofclf` already knows that adoption clusters, and a 10 m embedding built from a model with
a wide spatial context could carry that clustering into every pixel near an array.

So, per calibration quadrat, three populations of 10 m pixels on the AEF grid:

  * PV       -- at least 75% covered by a mapped PV polygon (large arrays only; most
                Pakistani quadrat PV is smaller than one pixel, so this is the favourable case)
  * near     -- roof pixels (>= 75% footprint) with no mapped PV, within 20 m of some PV
  * far      -- roof pixels with no mapped PV, more than 50 m from any PV

and one number per pixel: how far its embedding moved between 2021 (before Pakistan's boom)
and 2025, as 1 - cos. If AEF resolves installations, PV moves much more than far, and near
sits with far. If near sits with PV, the embedding is smearing the change across the
neighbourhood, which is the propensity signal again under a new name.

    pixi run python scripts/aef_pixel_change_check.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from scipy.ndimage import distance_transform_edt

from earthpv.roofclf import auc, discover_quadrats, load_quadrat, quadrat_label

log = logging.getLogger("aef_pixel_change")

WINDOWS = Path("/home/tobi/earthpv_data/aef/roofclf_quadrats/windows")
SUB = 4
PV_FRAC = 0.75
ROOF_FRAC = 0.75
NEAR_M, FAR_M = 20.0, 50.0


def _dequant(v: np.ndarray) -> np.ndarray:
    f = v.astype("float32")
    out = np.sign(f) * (f / 127.5) ** 2
    out[v == -128] = np.nan
    return out


def _load(year: int, q: str):
    z = np.load(WINDOWS / str(year) / f"{q}.npz")
    return _dequant(z["arr"]), rasterio.Affine(*z["transform"]), str(z["crs"])


def _frac(geoms, shape, transform) -> np.ndarray:
    h, w = shape
    if len(geoms) == 0:
        return np.zeros(shape, dtype="float32")
    fine = rasterio.Affine(transform.a / SUB, 0, transform.c, 0, transform.e / SUB, transform.f)
    r = rasterio.features.rasterize(((g, 1) for g in geoms), out_shape=(h * SUB, w * SUB),
                                    transform=fine, fill=0, dtype="uint8")
    return r.reshape(h, SUB, w, SUB).mean(axis=(1, 3))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--early", type=int, default=2021)
    ap.add_argument("--late", type=int, default=2025)
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_aef_pixel_change.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(args.table, columns=["quadrat", "geometry"])
    stems = {}
    for s in discover_quadrats():
        stems.setdefault(quadrat_label(s), []).append(s)
    rows, pooled = [], {"pv": [], "near": [], "far": []}
    for q in sorted(t.quadrat.unique()):
        if not ((WINDOWS / str(args.early) / f"{q}.npz").exists()
                and (WINDOWS / str(args.late) / f"{q}.npz").exists()):
            log.warning("%s: windows not cached, skipped", q)
            continue
        e0, tr0, crs = _load(args.early, q)
        e1, tr1, _ = _load(args.late, q)
        if tuple(tr0) != tuple(tr1) or e0.shape != e1.shape:
            log.warning("%s: windows differ between years, skipped", q)
            continue
        bu = t[t.quadrat == q].to_crs(crs)
        # the stem whose boundary holds this table's buildings (a redrawn quadrat keeps its
        # label, so more than one stem can map to it)
        cands = stems.get(q, [])
        best, best_n = None, -1
        for s in cands:
            bnd, pv = load_quadrat(s)
            n = int(bu.to_crs("EPSG:4326").representative_point().within(bnd).sum())
            if n > best_n:
                best, best_n, best_bnd, best_pv = s, n, bnd, pv
        if best is None:
            log.warning("%s: no quadrat stem found, skipped", q)
            continue
        pv = best_pv.to_crs(crs)
        shape = e0.shape[1:]
        pvf = _frac(list(pv.geometry), shape, tr0)
        bf = _frac(list(bu.geometry), shape, tr0)
        inside = _frac([gpd.GeoSeries([best_bnd], crs="EPSG:4326").to_crs(crs).iloc[0]],
                       shape, tr0) >= 0.5
        cos = np.sum(e0 * e1, axis=0) / (np.linalg.norm(e0, axis=0) * np.linalg.norm(e1, axis=0))
        move = 1.0 - cos
        dist_m = distance_transform_edt(pvf == 0) * abs(tr0.a)
        ok = inside & np.isfinite(move)
        sets = {
            "pv": ok & (pvf >= PV_FRAC),
            "near": ok & (bf >= ROOF_FRAC) & (pvf == 0) & (dist_m <= NEAR_M),
            "far": ok & (bf >= ROOF_FRAC) & (pvf == 0) & (dist_m > FAR_M),
        }
        r = {"quadrat": q, **{f"n_{k}": int(v.sum()) for k, v in sets.items()}}
        for k, v in sets.items():
            r[f"move_{k}"] = float(np.median(move[v])) if v.any() else np.nan
        if sets["pv"].sum() >= 5 and sets["far"].sum() >= 5:
            for k in ("pv", "near"):
                if sets[k].sum() < 5:
                    continue
                a, b = move[sets[k]], move[sets["far"]]
                r[f"auc_{k}_vs_far"] = auc(np.r_[np.ones(a.size), np.zeros(b.size)], np.r_[a, b])
        for k, v in sets.items():
            pooled[k].append(move[v])
        rows.append(r)
        log.info("%-24s pv=%4d near=%5d far=%5d  move pv %.4f near %.4f far %.4f  "
                 "auc pv/far %s near/far %s", q, r["n_pv"], r["n_near"], r["n_far"],
                 r["move_pv"], r["move_near"], r["move_far"],
                 r.get("auc_pv_vs_far"), r.get("auc_near_vs_far"))
    f = pd.DataFrame(rows)
    P = {k: np.concatenate(v) if v else np.array([]) for k, v in pooled.items()}

    def _pooled_auc(k):
        a, b = P[k], P["far"]
        return round(auc(np.r_[np.ones(a.size), np.zeros(b.size)], np.r_[a, b]), 4)

    out = {
        "years": [args.early, args.late],
        "n_quadrats": int(len(f)),
        "n_pixels": {k: int(v.size) for k, v in P.items()},
        "median_move": {k: round(float(np.median(v)), 4) for k, v in P.items() if v.size},
        "pooled_auc_pv_vs_far": _pooled_auc("pv"),
        "pooled_auc_near_vs_far": _pooled_auc("near"),
        "median_quadrat_auc_pv_vs_far": round(float(f.auc_pv_vs_far.median()), 4),
        "median_quadrat_auc_near_vs_far": round(float(f.auc_near_vs_far.median()), 4),
        "n_quadrats_scored": int(f.auc_pv_vs_far.notna().sum()),
    }
    f.to_csv(args.out.with_name(args.out.stem + "_quadrats.csv"), index=False)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
