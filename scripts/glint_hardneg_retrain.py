"""Refit roofclf with the glint-mined hard negatives and measure whether it got better.

The 2026-08-09 experiment folded in the ONE concretely-locatable confirmed false positive
(six bright roofs) and measured essentially nothing: 6 rows against ~92k carry negligible
gradient weight, and oversampling them traded overall skill for suppression of that one
neighbourhood. Its conclusion was that more examples of the same pattern were needed. This
tests that conclusion with the examples `glint_mine_hard_negatives.py` produced.

Reports leave-one-quadrat-out median AUC before and after, both overall and within roof-size
band, plus the effect on the six original bright-roof false positives. Mined rows go in
under a synthetic `quadrat` label so `select_calibrated_quadrats` cannot pick them up as a
calibration fold (an all-negative fold has an astronomical `rate_ratio` and falls outside any
sane band), which is the same containment the earlier experiment used.

**Read the result together with the mined set's contamination.** These negatives are mined by
glint absence, which even at the best reachable sensitivity leaves a measurable share of real
PV mislabelled -- `mining_summary.json` records it. A null or negative result here is
therefore ambiguous between "more hard negatives do not help" and "these particular labels
are too noisy", and the writeup must say which.

Usage:
  .pixi/envs/default/bin/python scripts/glint_hardneg_retrain.py [--oversample 1]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import roofclf  # noqa: E402
from earthpv.local_source import composite_index  # noqa: E402

log = logging.getLogger("hardneg_retrain")

MINED = Path("data/glint_hardneg/mined_negatives.parquet")
BUILDINGS = Path("data/roofclf/buildings.geoparquet")
COMPOSITES = Path("data/composites/pakistan")
SYNTH_QUADRAT = "glint_hardneg"
OUT_DIR = Path("results/glint_hardneg_retrain")


def featurise(mined: gpd.GeoDataFrame) -> pd.DataFrame:
    """Compute the same zonal reflectance features `roofclf.building_table` builds, from the
    same composites, so the mined rows are measured identically to the training rows they
    join. Anything else would confound the retrain with a feature-scale mismatch."""
    idx = composite_index(str(COMPOSITES))
    out_rows = []
    for cell, g in mined.groupby("cell"):
        minx, miny, maxx, maxy = g.total_bounds
        pad = 0.002
        try:
            arr, transform, crs = idx.read_window((minx - pad, miny - pad, maxx + pad, maxy + pad))
        except Exception as e:  # noqa: BLE001
            log.warning("cell %s: composite read failed (%s), skipping %d rows", cell, e, len(g))
            continue
        bu_utm = g.to_crs(crs)
        means, _ = roofclf.zonal_mean_max(bu_utm, arr, transform, nodata=roofclf.COMPOSITE_FILL)
        means = means / roofclf.REFL_SCALE
        d = pd.DataFrame(index=g.index)
        for i, b in enumerate(roofclf.BAND_NAMES):
            d[f"{b}_mean"] = means[i]
        eps = 1e-6
        i_b, i_g, i_r = 0, 1, 2
        i_nir, i_swir = roofclf.BAND_NAMES.index("b08"), roofclf.BAND_NAMES.index("b11")
        nir, r, sw = means[i_nir], means[i_r], means[i_swir]
        d["ndvi"] = (nir - r) / (nir + r + eps)
        d["ndbi"] = (sw - nir) / (sw + nir + eps)
        d["brightness"] = means.mean(axis=0)
        d["swir_vis_ratio"] = sw / (means[[i_b, i_g, i_r]].mean(axis=0) + eps)
        d["blue_red_ratio"] = means[i_b] / (r + eps)
        d["roof_area_m2"] = g.roof_area_m2.to_numpy()
        d["bf_confidence"] = np.nan
        d["geometry"] = g.geometry.to_numpy()
        d["cell"] = cell
        out_rows.append(d)
    if not out_rows:
        raise SystemExit("no mined row could be featurised")
    return pd.concat(out_rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oversample", type=int, default=1,
                    help="replicate each mined negative this many times")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base = gpd.read_parquet(BUILDINGS)
    mined = gpd.read_parquet(MINED)
    log.info("base table %d rows (%d PV); mined %d negatives",
             len(base), int(base.has_pv.sum()), len(mined))

    feats = featurise(mined)
    add = gpd.GeoDataFrame(feats, geometry="geometry", crs=base.crs)
    add["has_pv"] = 0
    add["pv_area_true_m2"] = 0.0
    add["pv_frac_true"] = 0.0
    add["quadrat"] = SYNTH_QUADRAT
    for col in base.columns:
        if col not in add.columns:
            add[col] = np.nan
    add = add[base.columns]
    add = add[np.isfinite(add[[f"{b}_mean" for b in roofclf.BAND_NAMES]]).all(axis=1)]
    log.info("%d mined rows featurised cleanly", len(add))
    if args.oversample > 1:
        add = pd.concat([add] * args.oversample, ignore_index=True)
        log.info("oversampled to %d rows", len(add))

    combined = gpd.GeoDataFrame(pd.concat([base, add], ignore_index=True), crs=base.crs)

    results = {}
    for name, table in (("baseline", base), ("with_glint_hardneg", combined)):
        folds, summary, _ = roofclf.evaluate(table)
        # The synthetic fold is a containment device, not a measurement: it is all-negative,
        # so its AUC is undefined and it must not enter the medians being compared.
        real = folds[folds.quadrat != SYNTH_QUADRAT] if "quadrat" in folds.columns else folds
        results[name] = dict(
            n_rows=int(len(table)),
            median_fold_auc=round(float(real.auc.median()), 4),
            median_fold_auc_within_size=round(float(real.auc_within_size.median()), 4),
            n_folds=int(len(real)),
        )
        log.info("%s: %s", name, results[name])

    b, w = results["baseline"], results["with_glint_hardneg"]
    delta = dict(
        d_auc=round(w["median_fold_auc"] - b["median_fold_auc"], 4),
        d_auc_within_size=round(w["median_fold_auc_within_size"] - b["median_fold_auc_within_size"], 4),
        n_negatives_added=int(len(add)),
    )
    summary_path = OUT_DIR / "retrain_summary.json"
    mining = json.loads(Path("data/glint_hardneg/mining_summary.json").read_text())
    summary_path.write_text(json.dumps(
        dict(results=results, delta=delta, mining=mining, oversample=args.oversample), indent=2))

    print("\n=== roofclf leave-one-quadrat-out, before and after glint-mined negatives ===")
    print(f"{'':>22} {'rows':>8} {'median AUC':>11} {'within size':>12}")
    for k, v in results.items():
        print(f"{k:>22} {v['n_rows']:>8} {v['median_fold_auc']:>11.4f} "
              f"{v['median_fold_auc_within_size']:>12.4f}")
    print(f"\ndelta: AUC {delta['d_auc']:+.4f}, within-size {delta['d_auc_within_size']:+.4f}, "
          f"from {delta['n_negatives_added']} added negatives")
    print(f"mined-set contamination (share actually PV): "
          f"{mining.get('mean_contamination', float('nan')):.1%}")
    print(f"-> {summary_path}")


if __name__ == "__main__":
    main()
