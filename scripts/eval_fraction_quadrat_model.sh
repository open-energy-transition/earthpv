#!/usr/bin/env bash
# Evaluate one fraction checkpoint over the calibration quadrats.
#
#   scripts/eval_fraction_quadrat_model.sh <name> <checkpoint>
#
# Runs inference over only the 15 composite cells that cover a quadrat (seconds-to-minutes,
# not the 3h19m a national pass takes) in BOTH epochs:
#   --index 0  the current dry-season composite (2025-11-01..2026-03-15)
#   --index 1  the pre-boom composite (2021-10-01..2022-01-24)
# Same checkpoint both times, which is what lets `fraction_stale_label_audit.py` attribute an
# unlabelled prediction to "installation built after the mapping imagery" rather than to a
# model difference.
#
# Then two evaluations:
#   1. validate_fraction_quadrats.py -- predicted/true area (`scale`) and pixel AUC per
#      quadrat, alongside fraction v1 and the hard-negative checkpoint for context.
#   2. fraction_stale_label_audit.py -- brackets precision between "every unlabelled
#      prediction is an error" and "candidate new installations are not errors".
set -euo pipefail
cd /run/media/tobi/aidisc/earthpv

NAME="${1:?usage: $0 <name> <checkpoint>}"
CKPT="${2:?usage: $0 <name> <checkpoint>}"
CELLS="$(cat data/quadrat_cells.txt)"
CUR="data/predictions_${NAME}_quadcells"
PRE="data/predictions_${NAME}_quadcells_preboom"

echo "=== $(date -Is) inference, current epoch (index 0) ==="
.pixi/envs/ml/bin/python -m earthpv.cli infer --aoi pakistan --checkpoint "$CKPT" \
  --out-dir "$CUR" --tiles "$CELLS" --index 0 --no-only-built

echo "=== $(date -Is) inference, pre-boom epoch (index 1) ==="
.pixi/envs/ml/bin/python -m earthpv.cli infer --aoi pakistan --checkpoint "$CKPT" \
  --out-dir "$PRE" --tiles "$CELLS" --index 1 --no-only-built

echo "=== $(date -Is) per-quadrat scale + pixel AUC vs v1 and hard-neg ==="
.pixi/envs/default/bin/python scripts/validate_fraction_quadrats.py \
  v1=data/predictions_frac_pk_v2/pakistan/prob \
  hn=data/predictions_fraction_hardneg_national/pakistan/prob \
  "${NAME}=$CUR/pakistan/prob" \
  --out "results/fraction_quadrat_validation_${NAME}.csv"

echo "=== $(date -Is) stale-label audit (two epochs, same checkpoint) ==="
.pixi/envs/default/bin/python scripts/fraction_stale_label_audit.py \
  --current "$CUR/pakistan/prob" --preboom "$PRE/pakistan/prob" \
  --out "results/fraction_stale_label_audit_${NAME}.csv"

echo "EVAL_DONE_${NAME}"
