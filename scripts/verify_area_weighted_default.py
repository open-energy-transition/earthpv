"""Acceptance test for shipping area-weighted zonal means as roofclf's default.

The experimental `areazonal` variant measured +0.0113 AUC within size band. The SHIPPED
version is not that code: it masks nodata with the same all-bands-equal-fill test
`zonal_mean_max` uses (the experiment tested `np.isfinite`, which is right for a NaN-masked
scene stack and wrong for a composite window, where fill is 0.0 and would enter the weighted
mean as genuine near-zero reflectance -- the cell-edge mechanism that once made 45.6% of
every nationally flagged building an artefact), and it falls back to the pixel-centre value
for a footprint with no subpixel of its own instead of returning NaN (the experiment silently
dropped 0.16-0.47% of buildings, which are the smallest ones, i.e. the population this module
exists for).

So the published figure cannot be carried over. This re-measures the shipped default against
the shipped pre-2026-09-20 behaviour, on the same rows, and reports BOTH the ranking metric
and the deployment metric the capacity chain actually consumes.

    pixi run python scripts/verify_area_weighted_default.py
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from earthpv import overture
from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             building_table, discover_quadrats, fit_logistic, predict_proba)
from earthpv.sppi import _precision_threshold

log = logging.getLogger("area_weighted")
EXCLUDE = "kalat_rural_calib_3km"
OUT = Path("data/roofclf_area_weighted")


def build(on: bool, quadrats, iso3, con) -> Path:
    dst = OUT / ("on" if on else "off") / "buildings.geoparquet"
    if dst.exists():
        log.info("reusing %s", dst)
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    parts = [building_table(n, iso3, Path("data/composites/pakistan"),
                            Path("data/predictions_pk16085/pakistan/prob"),
                            Path("data/predictions_frac_pk_v2/pakistan/prob"),
                            Path("data/labels"), con, parcel_label=True, area_weighted=on)
             for n in quadrats]
    tab = gpd.GeoDataFrame(pd.concat([p for p in parts if not p.empty], ignore_index=True),
                           geometry="geometry", crs="EPSG:4326")
    tab.to_parquet(dst)
    log.info("area_weighted=%s: %d rows, %.0fs -> %s", on, len(tab), time.time() - t0, dst)
    return dst


def _key(t):
    c = t.geometry.representative_point()
    return (t.quadrat.astype(str) + "|" + c.x.round(6).astype(str) + "|"
            + c.y.round(6).astype(str))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    _, cfg = resolve_aoi("pakistan", Settings.load())
    quadrats = [q for q in sorted(discover_quadrats(Path("data/labels"))) if q != EXCLUDE]
    con = overture.connect()
    tabs = {k: gpd.read_parquet(build(k == "on", quadrats, _iso3_for(cfg), con))
            for k in ("off", "on")}
    for k, t in tabs.items():
        t["_k"] = _key(t)
    common = set(tabs["on"]._k) & set(tabs["off"]._k)
    for k in tabs:
        t = tabs[k][tabs[k]._k.isin(common)].sort_values("_k").reset_index(drop=True)
        tabs[k] = t[np.isfinite(_subset_matrix(t, MODEL_FEATURES)).all(axis=1)
                    ].reset_index(drop=True)
    n = min(len(tabs["on"]), len(tabs["off"]))
    log.info("%d rows in common, %d after NaN drop", len(common), n)

    rows, oof = [], {}
    for k, t in tabs.items():
        s = np.full(len(t), np.nan)
        for q in sorted(t.quadrat.unique()):
            te = (t.quadrat == q).to_numpy()
            tr = ~te
            if t.loc[tr, "has_pv"].nunique() < 2:
                continue
            m = fit_logistic(_subset_matrix(t[tr], MODEL_FEATURES),
                             t.loc[tr, "has_pv"].to_numpy(float), L2)
            s[te] = predict_proba(m, _subset_matrix(t[te], MODEL_FEATURES))
            y = t.loc[te, "has_pv"].to_numpy()
            roof = t.loc[te, "roof_area_m2"].to_numpy()
            rows.append({"arm": k, "quadrat": q, "auc": auc(y, s[te]),
                         "ws": auc_within_size(y, s[te], roof)[0]})
        oof[k] = s

    d = pd.DataFrame(rows).pivot(index="quadrat", columns="arm", values=["auc", "ws"])
    res = {}
    print(f"\n{'metric':14} {'pixel-centre':>14} {'area-weighted':>15} {'delta':>9} "
          f"{'better':>9} {'sign p':>8} {'wilcoxon':>9}")
    for met in ("auc", "ws"):
        a, b = d[(met, "off")], d[(met, "on")]
        dl = (b - a).dropna()
        nb, nw = int((dl > 0).sum()), int((dl < 0).sum())
        ps = stats.binomtest(nb, max(nb + nw, 1), 0.5).pvalue
        pw = stats.wilcoxon(b.dropna(), a.dropna()).pvalue
        print(f"{met:14} {a.median():14.4f} {b.median():15.4f} {dl.median():+9.4f} "
              f"{nb:5d}/{nb + nw:<3d} {ps:8.3f} {pw:9.4f}")
        res[met] = {"off": round(float(a.median()), 4), "on": round(float(b.median()), 4),
                    "delta_median": round(float(dl.median()), 4), "folds_better": nb,
                    "folds_worse": nw, "sign_p": round(float(ps), 4),
                    "wilcoxon_p": round(float(pw), 4)}

    print(f"\n{'arm':16} {'AUC':>8} {'threshold':>10} {'flagged':>9} {'precision':>10} "
          f"{'recall':>8}")
    base = None
    for k in ("off", "on"):
        t, s = tabs[k], oof[k]
        ok = np.isfinite(s)
        y = t.has_pv.to_numpy(bool)
        thr = _precision_threshold(y[ok], s[ok], 0.5)
        flag = ok & (s >= thr)
        prec, rec = float(y[flag].mean()), float(y[flag].sum() / y[ok].sum())
        base = rec if base is None else base
        print(f"{k:16} {auc(y[ok], s[ok]):8.4f} {thr:10.4f} {int(flag.sum()):9d} "
              f"{prec:10.4f} {rec:8.4f}")
        res[f"deploy_{k}"] = {"auc": round(float(auc(y[ok], s[ok])), 4),
                              "threshold": round(thr, 4), "n_flagged": int(flag.sum()),
                              "precision": round(prec, 4), "recall": round(rec, 4),
                              "d_recall": round(rec - base, 4)}
    Path("results/roofclf_area_weighted_default.json").write_text(
        json.dumps(res, indent=2) + "\n")
    print("\nwrote results/roofclf_area_weighted_default.json")


if __name__ == "__main__":
    main()
