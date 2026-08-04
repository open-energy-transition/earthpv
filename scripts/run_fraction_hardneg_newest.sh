#!/usr/bin/env bash
set -euo pipefail
cd /run/media/tobi/aidisc/earthpv

CKPT="data/models/fraction_pakistan_hardneg/terramind-pv-epoch=32-step=27027.ckpt"
WINDOW="2026-05-01:2026-08-03"
INDEX=2
INFER_OUT="data/predictions_fraction_hardneg_newest"
DENSITY_BASE="data/predictions_fraction_hardneg_newest_base"

echo "=== Stage 0: compose newest-imagery layer (index $INDEX, window $WINDOW) ==="
.pixi/envs/default/bin/python -m earthpv.cli compose \
  --aoi pakistan --index "$INDEX" --window "$WINDOW" --use-vida --workers 6

echo "STAGE0_COMPOSE_DONE"

echo "=== Stage 1: national inference on the newest-imagery layer ==="
.pixi/envs/ml/bin/python -m earthpv.cli infer \
  --aoi pakistan --checkpoint "$CKPT" --index "$INDEX" --out-dir "$INFER_OUT"

echo "STAGE1_INFER_DONE"

mkdir -p "$DENSITY_BASE/pakistan/buildings"
ln -sf /run/media/tobi/aidisc/earthpv/data/predictions/pakistan/candidates.parquet \
  "$DENSITY_BASE/pakistan/candidates.parquet"
ln -sf /run/media/tobi/aidisc/earthpv/data/predictions/pakistan/buildings/pakistan_vida.parquet \
  "$DENSITY_BASE/pakistan/buildings/pakistan_vida.parquet"
ln -sf /run/media/tobi/aidisc/earthpv/data/predictions/pakistan/prob \
  "$DENSITY_BASE/pakistan/prob"

echo "=== Stage 2: density with newest-imagery fraction instrument ==="
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

echo "FRACTION_HARDNEG_NEWEST_PIPELINE_DONE"
