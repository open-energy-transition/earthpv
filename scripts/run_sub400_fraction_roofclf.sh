#!/usr/bin/env bash
# Sub-400 m2 PV density from the two instruments that can see below the segmentation
# model's detection floor: the FRACTION head (per-pixel PV coverage) and ROOFCLF
# (per-building "does this roof carry PV?"). The segmentation raster is deliberately not
# used as an estimator anywhere in this chain -- measured, it scores AUC ~0.50 in the
# sub-400 regime and predicts 0.0 m2 of PV in the quadrats that are almost entirely
# sub-floor, so including it would add noise dressed as evidence. It appears only as a
# reported baseline inside step 1's fold table, which is where a chance-level number is
# informative rather than load-bearing.
#
# Ordering matters and is not arbitrary:
#   1. roofclf LOQO on the CURRENT quadrat set -> model_full.json, the precision-targeted
#      deployment threshold, AND exp_scale_anchor.csv. That anchor is where the fraction
#      head's `--exp-scale` comes from, so step 3 cannot be calibrated before step 1 runs.
#   2. Score every VIDA building nationally with that model (the long pole, ~4,470 cells,
#      resumable per cell).
#   3. Fraction-head expected area nationally, via `density --fraction-prob-dir`.
#   4. Domain-restricted sub-400 capacity, which is the only figure here that is defensible
#      as a number rather than a ranking (see docs/methods/density.md).
set -uo pipefail
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
STAMP=20260805
FRAC_PROB=data/predictions_frac_pk_v2/pakistan/prob   # fraction_pakistan_v1, the checkpoint
                                                      # of record for sub-400 m2 (the
                                                      # hard-negative retrain is a large-array
                                                      # win and a small-rooftop loss).
OUT=data/roofclf_${STAMP}_newquadrats
NAT=data/roofclf_national_${STAMP}

echo "########## $(date -Is) step 1: roofclf LOQO on the current quadrat set"
"$PY" -m earthpv.cli roof-classifier --aoi pakistan \
  --frac-prob-dir "$FRAC_PROB" \
  --out-dir "$OUT" || { echo "STEP1_FAILED"; exit 1; }

echo "########## $(date -Is) step 1 outputs"
"$PY" - <<'EOF'
import json, pandas as pd
from pathlib import Path
o = Path("data/roofclf_20260805_newquadrats")
s = json.load(open(o / "summary.json"))
for k in ("n_quadrats","n_buildings","n_pv","median_fold_auc","median_fold_auc_within_size",
          "median_fold_auc_within_size_seg","median_frac_baseline_auc","median_seg_baseline_auc",
          "intercept","deployment_threshold"):
    if k in s:
        print(f"  {k:34s} {s[k]}")
a = pd.read_csv(o / "exp_scale_anchor.csv")
fr = a[a.instrument == "frac"]
print(f"\n  fraction-head scale across {len(fr)} quadrats: "
      f"median {fr.scale.median():.3f}  min {fr.scale.min():.3f}  max {fr.scale.max():.3f}")
print(f"  -> suggested --exp-scale for the fraction head: {1.0 / fr.scale.median():.4f}")
EOF

echo "########## $(date -Is) step 2: score every VIDA building nationally (long)"
"$PY" - <<EOF || { echo "STEP2_FAILED"; exit 1; }
import json, logging, sys
sys.path.insert(0, "src")
from pathlib import Path
from earthpv import roofclf
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
o = Path("$OUT")
m = json.load(open(o / "model_full.json"))
roofclf.score_buildings_national(
    "pakistan", m, m["features"], Path("data/composites/pakistan"), Path("$NAT"))
EOF

echo "########## $(date -Is) BOTH_STEPS_DONE  ($OUT, $NAT)"
