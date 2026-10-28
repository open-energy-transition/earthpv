#!/usr/bin/env python
"""Does Pakistan's roofclf help in Yemen? Per-Yemeni-area AUC under six training regimes.

Reads the two existing quadrat tables (same 17 features, parcel label, area-weighted zonal
means), so nothing is re-extracted. Measured 2026-10-28 (docs/experiments.md):

- pk_zero   Pakistan's production model (data/roofclf/model_full.json), unchanged
- pk_restd  its coefficients, features re-standardised on the Yemeni training rows
- ye_loqo   Yemen alone, leave-one-area-out
- pooled    Pakistan + Yemen, every row weight 1 (Pakistan dominates 124k : 65k)
- pooled_eqw each country half the likelihood (= roof-classifier --extra-table)
- pooled_bldg_only Pakistan + Yemen's building boxes only (farm-area parcel labels out)

    python scripts/roofclf_transfer_yemen.py results/yemen_roofclf_transfer/transfer_by_area.csv
"""
import json
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from earthpv import roofclf as rc  # noqa: E402

FE = rc.MODEL_FEATURES
pk = gpd.read_parquet("data/roofclf/buildings.geoparquet").drop(columns="geometry")
ye = gpd.read_parquet("data/roofclf_yemen_with_farm/buildings.geoparquet").drop(columns="geometry")
pk["country"], ye["country"] = "PK", "YE"
ye["roof_pv"] = ye.pv_area_roof_m2.fillna(0) > 0

m = json.load(open("data/roofclf/model_full.json"))
pk_model = {k: np.asarray(m[k]) for k in ("w", "mu", "sd")}
assert m["features"] == FE

Xpk, ypk = rc.design_matrix(pk, FE), pk.has_pv.to_numpy(float)
Xye = rc.design_matrix(ye, FE)

BUILDING = ["al_wehdah_priority", "sayun_priority", "bani_al_harith_s8", "huth_s1"]
# Yemeni areas with any PV, else AUC is undefined
areas = [q for q in ye.quadrat.unique() if ye.loc[ye.quadrat == q, "has_pv"].any()]

preds = {k: np.full(len(ye), np.nan) for k in
         ("ye_loqo", "pk_zero", "pk_restd", "pooled", "pooled_eqw", "pooled_bldg_only")}
preds["pk_zero"] = rc.predict_proba(pk_model, Xye)

for q in areas:
    te = (ye.quadrat == q).to_numpy()
    tr = ~te
    Xtr, ytr = Xye[tr], ye.has_pv.to_numpy(float)[tr]
    # 1. Yemen only, leave this area out
    mdl = rc.fit_logistic(Xtr, ytr)
    preds["ye_loqo"][te] = rc.predict_proba(mdl, Xye[te])
    # 2. Pakistan's weights, re-standardised on the Yemeni training rows: a covariate-shift
    # fix that keeps every coefficient Pakistan learned
    restd = dict(pk_model, mu=Xtr.mean(0), sd=np.where(Xtr.std(0) > 0, Xtr.std(0), 1))
    preds["pk_restd"][te] = rc.predict_proba(restd, Xye[te])
    # 3. Pakistan + Yemen pooled, every row weight 1 (Pakistan dominates 124k : 65k)
    Xp = np.vstack([Xpk, Xtr])
    yp = np.concatenate([ypk, ytr])
    preds["pooled"][te] = rc.predict_proba(rc.fit_logistic(Xp, yp), Xye[te])
    # 4. pooled, each country carrying half the likelihood
    w = np.concatenate([np.full(len(ypk), 0.5 / len(ypk)), np.full(len(ytr), 0.5 / len(ytr))])
    preds["pooled_eqw"][te] = rc.predict_proba(rc.fit_logistic(Xp, yp, sample_weight=w), Xye[te])
    # 5. pooled with Yemen's BUILDING boxes only (the farm areas' positives are mostly
    # yard ground PV credited to the nearest building by the parcel label)
    keep = tr & ~ye.quadrat.str.endswith("_farm").to_numpy()
    Xb = np.vstack([Xpk, Xye[keep]])
    yb = np.concatenate([ypk, ye.has_pv.to_numpy(float)[keep]])
    preds["pooled_bldg_only"][te] = rc.predict_proba(rc.fit_logistic(Xb, yb), Xye[te])

rows = []
for q in areas:
    te = (ye.quadrat == q).to_numpy()
    d = ye[te]
    y, yroof, roof = d.has_pv.to_numpy(), d.roof_pv.to_numpy(), d.roof_area_m2.to_numpy()
    for k, p in preds.items():
        pq = p[te]
        rows.append({
            "area": q, "kind": "building" if q in BUILDING else "farm", "model": k,
            "n": int(te.sum()), "n_pv": int(y.sum()), "n_roof_pv": int(yroof.sum()),
            "auc": rc.auc(y, pq), "auc_roof_label": rc.auc(yroof, pq),
            "auc_within_size": rc.auc_within_size(y, pq, roof)[0],
            "rate_ratio": pq.mean() / max(y.mean(), 1e-9),
        })
res = pd.DataFrame(rows)
res.to_csv(sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout", index=False)

pd.set_option("display.width", 200)
for metric in ("auc", "auc_roof_label", "auc_within_size", "rate_ratio"):
    t = res.pivot(index="area", columns="model", values=metric)
    t = t.loc[BUILDING + [a for a in t.index if a not in BUILDING]]
    print(f"\n== {metric} ==")
    print(t.round(3).to_string())
    print("median building:", t.loc[BUILDING].median().round(3).to_dict())
    print("median all     :", t.median().round(3).to_dict())

