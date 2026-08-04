#!/usr/bin/env bash
set -euo pipefail
cd /run/media/tobi/aidisc/earthpv

CKPT="data/models/fraction_pakistan_hardneg/terramind-pv-epoch=32-step=27027.ckpt"
INFER_OUT="data/predictions_fraction_hardneg_national"
DENSITY_BASE="data/predictions_fraction_hardneg_national_base"

echo "=== Stage 1: national inference (current epoch, fraction_pakistan_hardneg) ==="
.pixi/envs/ml/bin/python -m earthpv.cli infer \
  --aoi pakistan --checkpoint "$CKPT" --out-dir "$INFER_OUT"

echo "STAGE1_INFER_DONE"

echo "=== Stage 2: density with new fraction-head instrument ==="
.pixi/envs/default/bin/python -m earthpv.cli density \
  --aoi pakistan --pred-dir "$DENSITY_BASE" \
  --fraction-prob-dir "$INFER_OUT/pakistan/prob" \
  --districts

echo "STAGE2_DENSITY_DONE"

echo "=== Stage 3: plausibility gate ==="
set +e
.pixi/envs/default/bin/python -m earthpv.cli check-density \
  --aoi pakistan --pred-dir "$DENSITY_BASE"
CHECK_RC=$?
set -e
echo "STAGE3_CHECK_DENSITY_EXIT=$CHECK_RC"

echo "FRACTION_HARDNEG_NATIONAL_PIPELINE_DONE"
