#!/usr/bin/env python
"""Do Google Open Buildings 2.5D Temporal's AGE and HEIGHT add anything to roofclf?

Open question 22's first measurement for this source: the features on Pakistan's quadrat
set, size-controlled AUC on the spatial holdout, dropped below one point. Same protocol as
`run_gba_height_ablation.py` (2026-09-20: GlobalBuildingAtlas height +0.0006 within size
band, 6 of 9 folds, on the 5 quadrats GBA covered), but on all 41 quadrats of the production
table, because 2.5D Temporal covers all of Pakistan, and with two features GBA never had:

  age     the first year (2016-2023) Google's model sees a building at the footprint, its
          presence in 2016, whether it appeared from 2021 on (the boom), and the height
          gained 2016 -> 2023 (a storey added)
  height  mean and max building_height in 2023 (CC BY 4.0 / ODbL, so deployable, unlike GBA)

Leave-one-quadrat-out with roofclf's own fit (`fit_logistic`, L2), reporting the median fold
AUC, the median within-size-band AUC (`auc_within_size`), and per block the change in
within-size AUC over the baseline with a sign test across folds.

    .pixi/envs/default/bin/python scripts/run_gob_temporal_ablation.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             fit_logistic, predict_proba)

log = logging.getLogger("gob_ablation")
YEARS = list(range(2016, 2024))
PRESENT = 0.5


def derive(f: pd.DataFrame) -> pd.DataFrame:
    pres = np.column_stack([f[f"presence_{y}"].to_numpy(float) for y in YEARS])
    ok = np.isfinite(pres)
    seen = np.where(ok, pres >= PRESENT, False)
    first_idx = np.where(seen.any(1), seen.argmax(1), len(YEARS))  # len = never by 2023
    h23 = f["height_2023"].to_numpy(float)
    h16 = f["height_2016"].to_numpy(float)
    out = pd.DataFrame({
        "gob_log_h": np.log1p(np.clip(np.nan_to_num(h23), 0, None)),
        "gob_log_hmax": np.log1p(np.clip(np.nan_to_num(f["height_max_2023"].to_numpy(float)), 0, None)),
        "gob_pres23": np.nan_to_num(f["presence_2023"].to_numpy(float)),
        "gob_pres16": np.nan_to_num(f["presence_2016"].to_numpy(float)),
        "gob_first": first_idx / (len(YEARS) - 1),
        "gob_new": (first_idx >= YEARS.index(2021)).astype(float),
        "gob_dh": np.clip(np.nan_to_num(h23 - h16), -10, 10),
        "first_year": np.where(first_idx < len(YEARS), np.array(YEARS + [0])[first_idx], np.nan),
    })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--features", type=Path,
                    default=Path("data/gob_temporal/pakistan_quadrats_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_gob_temporal.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(args.table).reset_index(drop=True)
    f = pd.read_parquet(args.features).set_index("row").reindex(np.arange(len(t)))
    covered = f["presence_2023"].notna().to_numpy()
    d = pd.concat([t, derive(f)], axis=1)[covered].reset_index(drop=True)
    log.info("%d of %d buildings carry 2.5D Temporal values, %d quadrats",
             len(d), len(t), d.quadrat.nunique())

    # Descriptives: does the source separate PV roofs at all, before any model?
    desc = {}
    for c in ("gob_log_h", "gob_pres23", "gob_pres16", "gob_first", "gob_new", "gob_dh"):
        a, b = d.loc[d.has_pv == 1, c], d.loc[d.has_pv == 0, c]
        sd = np.sqrt((a.var() + b.var()) / 2) or np.nan
        desc[c] = {"pv_mean": round(float(a.mean()), 3), "nopv_mean": round(float(b.mean()), 3),
                   "d_prime": round(float((a.mean() - b.mean()) / sd), 3)}
    fy = d.groupby(d.first_year.fillna(0).astype(int)).has_pv.agg(["size", "mean"]).round(4)
    log.info("PV rate by first year seen (0 = never by 2023):\n%s", fy)

    base = list(MODEL_FEATURES)
    age = ["gob_pres16", "gob_first", "gob_new", "gob_dh"]
    height = ["gob_log_h", "gob_log_hmax"]
    blocks = {
        "baseline": base,
        "plus_height": base + height,
        "plus_age": base + age,
        "plus_presence": base + ["gob_pres23"],
        "plus_all": base + height + age + ["gob_pres23"],
        "size_age_height_only": ["log_roof_area"] + height + age,
        "size_only": ["log_roof_area"],
    }
    rows = []
    for name in sorted(d.quadrat.unique()):
        te = (d.quadrat == name).to_numpy()
        tr = ~te
        if d.loc[tr, "has_pv"].nunique() < 2 or d.loc[te, "has_pv"].nunique() < 2:
            continue
        y = d.loc[te, "has_pv"].to_numpy()
        roof = d.loc[te, "roof_area_m2"].to_numpy()
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum())}
        for lab, feats in blocks.items():
            mod = fit_logistic(_subset_matrix(d[tr], feats), d.loc[tr, "has_pv"].to_numpy(float), L2)
            p = predict_proba(mod, _subset_matrix(d[te], feats))
            r[f"auc__{lab}"] = auc(y, p)
            r[f"ws__{lab}"] = auc_within_size(y, p, roof)[0]
        rows.append(r)
        log.info("  %-26s n=%5d pv=%4d  ws %.4f -> all %.4f", name, r["n"], r["n_pv"],
                 r["ws__baseline"], r["ws__plus_all"])
    fdf = pd.DataFrame(rows)
    out = {"n_buildings": int(len(d)), "n_folds": int(len(fdf)),
           "coverage": round(float(covered.mean()), 4), "descriptives": desc,
           "pv_rate_by_first_year": {int(k): {"n": int(v["size"]), "pv_rate": float(v["mean"])}
                                     for k, v in fy.iterrows()}}
    for lab in blocks:
        out[f"auc_{lab}"] = round(float(fdf[f"auc__{lab}"].median()), 4)
        out[f"ws_{lab}"] = round(float(fdf[f"ws__{lab}"].median()), 4)
    for lab in blocks:
        if lab == "baseline":
            continue
        for tag in ("auc", "ws"):
            dl = (fdf[f"{tag}__{lab}"] - fdf[f"{tag}__baseline"]).dropna()
            b, w = int((dl > 0).sum()), int((dl < 0).sum())
            out[f"delta_{tag}_{lab}"] = round(float(dl.median()), 4)
            out[f"{tag}_better_{lab}"] = f"{b}/{len(dl)}"
            out[f"{tag}_p_{lab}"] = round(float(stats.binomtest(b, max(b + w, 1), 0.5).pvalue), 4)
    fdf.to_csv(args.out.with_name(args.out.stem + "_folds.csv"), index=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
