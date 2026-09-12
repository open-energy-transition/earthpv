#!/usr/bin/env python
"""Was the French roofclf limited by its training data, or by the sensor?

Fits roofclf on OpenPVMapper labels (~30x the supervision of the fourteen hand-mapped
communes) and scores it on the hand-mapped truth, which is the only human-verified ground
truth France has. Training communes and evaluation communes are disjoint by INSEE, so the
evaluation is always out-of-commune, matching the leave-one-quadrat-out protocol the
1,231-positive baseline was measured under.

Three numbers come out, and they answer different questions:

* **AUC on hand-mapped truth** -- the headline. If ~30x more labels lifts this well above
  the 0.710 / 0.627-within-size baseline, the training data was the binding constraint.
  If it does not move, the constraint is physical.
* **AUC on held-out OpenPVMapper labels** -- the control that separates "learned nothing"
  from "learned OpenPVMapper's own biases". A model that scores well here and badly on
  hand-mapped truth has fitted the reference model rather than the world.
* **Base rates** -- OpenPVMapper is ~67% complete against hand-mapped truth, so some of its
  negatives are real positives. That mislabelling attenuates measured AUC, which is why the
  result is read as a lower bound on what these labels can deliver.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opvm-table", default="data/roofclf_france_opvm/buildings.geoparquet")
    ap.add_argument("--truth-table", default="data/roofclf_france/buildings.geoparquet")
    ap.add_argument("--out", default="results/france_roofclf_opvm_control.json")
    ap.add_argument("--seed", type=int, default=20260912)
    args = ap.parse_args()

    from earthpv.roofclf import (MODEL_FEATURES, auc, auc_within_size, design_matrix,
                                 fit_logistic, predict_proba)

    tr = gpd.read_parquet(args.opvm_table)
    te = gpd.read_parquet(args.truth_table)
    feats = list(MODEL_FEATURES)

    print(f"train (OpenPVMapper labels): {len(tr):,} buildings, {int(tr.has_pv.sum()):,} with PV "
          f"({100*tr.has_pv.mean():.2f}%), {tr.quadrat.nunique()} communes")
    print(f"test  (hand-mapped truth)  : {len(te):,} buildings, {int(te.has_pv.sum()):,} with PV "
          f"({100*te.has_pv.mean():.2f}%), {te.quadrat.nunique()} communes")

    # Control: hold out 20% of TRAINING communes to score the model on its own label source.
    rng = np.random.default_rng(args.seed)
    quads = np.array(sorted(tr.quadrat.unique()))
    rng.shuffle(quads)
    n_hold = max(1, len(quads) // 5)
    hold, keep = set(quads[:n_hold]), set(quads[n_hold:])
    tr_fit = tr[tr.quadrat.isin(keep)]
    tr_hold = tr[tr.quadrat.isin(hold)]

    def _fit(df):
        X = design_matrix(df, feats)
        return fit_logistic(X, df.has_pv.to_numpy(float))

    model_ctrl = _fit(tr_fit)
    p_ctrl = predict_proba(model_ctrl, design_matrix(tr_hold, feats))
    ctrl_auc = auc(tr_hold.has_pv.to_numpy(float), p_ctrl)
    ctrl_ws, _ = auc_within_size(tr_hold.has_pv.to_numpy(float), p_ctrl,
                                 tr_hold.roof_area_m2.to_numpy())

    # Headline: fit on ALL OpenPVMapper communes, score each hand-mapped commune.
    model = _fit(tr)
    p = predict_proba(model, design_matrix(te, feats))
    rows = []
    for q, g in te.groupby("quadrat"):
        m = te.quadrat == q
        y = g.has_pv.to_numpy(float)
        if y.sum() == 0 or y.sum() == len(y):
            continue
        a = auc(y, p[m.to_numpy()])
        ws, _ = auc_within_size(y, p[m.to_numpy()], g.roof_area_m2.to_numpy())
        rows.append({"quadrat": q, "n": len(g), "n_pv": int(y.sum()),
                     "auc": round(float(a), 4), "auc_within_size": round(float(ws), 4)})
    per = pd.DataFrame(rows).sort_values("auc", ascending=False)
    pooled = auc(te.has_pv.to_numpy(float), p)
    pooled_ws, _ = auc_within_size(te.has_pv.to_numpy(float), p, te.roof_area_m2.to_numpy())

    BASE_AUC, BASE_WS = 0.7103, 0.6274
    print("\nper hand-mapped commune (OpenPVMapper-trained model):")
    print(per.to_string(index=False))
    out = {
        "train_buildings": int(len(tr)), "train_positives": int(tr.has_pv.sum()),
        "train_communes": int(tr.quadrat.nunique()),
        "test_buildings": int(len(te)), "test_positives": int(te.has_pv.sum()),
        "opvm_trained_on_handmapped": {
            "median_commune_auc": round(float(per.auc.median()), 4),
            "median_commune_auc_within_size": round(float(per.auc_within_size.median()), 4),
            "pooled_auc": round(float(pooled), 4),
            "pooled_auc_within_size": round(float(pooled_ws), 4),
            "per_commune": per.to_dict("records"),
        },
        "control_opvm_trained_on_opvm_heldout": {
            "n_held_out_communes": int(len(hold)),
            "auc": round(float(ctrl_auc), 4),
            "auc_within_size": round(float(ctrl_ws), 4),
        },
        "handmapped_trained_baseline": {
            "median_fold_auc": BASE_AUC, "median_fold_auc_within_size": BASE_WS,
            "train_positives": 1231,
        },
        "delta_vs_baseline": {
            "median_auc": round(float(per.auc.median()) - BASE_AUC, 4),
            "median_auc_within_size": round(float(per.auc_within_size.median()) - BASE_WS, 4),
            "supervision_ratio": round(float(tr.has_pv.sum()) / 1231, 1),
        },
        "caveat": (
            "OpenPVMapper recalls 0.67 of hand-mapped truth, so some of its negatives are "
            "real positives; that mislabelling attenuates AUC, making this a lower bound on "
            "what these labels can deliver"
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))

    print(f"\n{'':<38}{'AUC':>9}{'within-size':>13}")
    print(f"{'hand-mapped baseline (1,231 pv, LOQO)':<38}{BASE_AUC:>9.4f}{BASE_WS:>13.4f}")
    print(f"{'OpenPVMapper-trained, on hand-mapped':<38}"
          f"{per.auc.median():>9.4f}{per.auc_within_size.median():>13.4f}")
    print(f"{'  (delta)':<38}{per.auc.median()-BASE_AUC:>+9.4f}"
          f"{per.auc_within_size.median()-BASE_WS:>+13.4f}")
    print(f"{'CONTROL: on held-out OpenPVMapper':<38}{ctrl_auc:>9.4f}{ctrl_ws:>13.4f}")
    print(f"\nsupervision ratio: {out['delta_vs_baseline']['supervision_ratio']}x the positives")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
