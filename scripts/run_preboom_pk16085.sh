#!/usr/bin/env bash
# Rescore pk16085 candidates using pre-boom epoch-diff change detection (README's
# "two-epoch change detection"): a candidate that was already bright before the
# 2021-2022 solar-import boom is very unlikely to be real PV -- it's a persistent
# bright roof/soil/water false positive, not a genuine post-boom installation.
# postprocess.add_epoch_prior downweights rank_score accordingly; it never drops a
# candidate (recall-first — the epoch-diff is evidence for re-ranking, not a filter).
#
# Sequence (resumable via marker files under data/.preboom_pk16085, same idiom as
# run_after_train_pk16085.sh):
#   0. wait for the running earthpv-preboom-compose unit to finish -- so pre-boom
#      inference runs exactly ONCE on the complete cell set, not partially now plus a
#      wasted full GPU re-run later (infer.py is not itself resumable per-cell).
#   1. pre-boom inference (composite_1, the pre-boom window) with the pk16085
#      checkpoint -> a FRESH out-dir (data/predictions_preboom_pk16085 -- must not
#      clobber data/predictions_preboom, which holds the older v3_combined_india
#      pre-boom pass).
#   2. re-run postprocess on the pk16085 candidates with --preboom-prob-dir pointing
#      at it, adding epoch_prior/preboom_prob columns and rescaling rank_score.
#   3. re-export (rank_score changed, so leads ordering and the MapRoulette task order
#      need refreshing). density/atlas are NOT rerun: epoch rescoring never changes
#      area_m2/geometry/glint columns, so est_mwp_{det,cal,exp} are unaffected.
#
# Run detached:
#   systemd-run --user --collect --unit=earthpv-preboom-pk16085 -p Restart=on-failure \
#     -p RestartSec=60 -p WorkingDirectory=/run/media/tobi/aidisc/earthpv \
#     bash scripts/run_preboom_pk16085.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PY_ML=.pixi/envs/ml/bin/python
PY_DEFAULT=.pixi/envs/default/bin/python
AOI=pakistan
CHECKPOINT=data/models/terramind-pv-epoch=11-step=5880.ckpt
PRED_DIR=data/predictions_pk16085
PREBOOM_DIR=data/predictions_preboom_pk16085
LOG=data/preboom_pk16085.log
MARKERS=data/.preboom_pk16085

mkdir -p data "$MARKERS"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

log "STEP0: waiting for earthpv-preboom-compose to finish"
while systemctl --user is-active earthpv-preboom-compose >/dev/null 2>&1; do
  sleep 300
done
log "STEP0: pre-boom compose no longer running"

if [ ! -f "$MARKERS/infer" ]; then
  log "STEP1: pre-boom inference (index=1) with pk16085 checkpoint -> $PREBOOM_DIR"
  $PY_ML -m earthpv.cli infer --aoi $AOI --checkpoint "$CHECKPOINT" --index 1 --out-dir $PREBOOM_DIR >> "$LOG" 2>&1
  touch "$MARKERS/infer"
else
  log "STEP1: already done, skipping"
fi

if [ ! -f "$MARKERS/postprocess" ]; then
  log "STEP2: postprocess with epoch-diff rescoring"
  $PY_DEFAULT -m earthpv.cli postprocess --aoi $AOI --pred-dir $PRED_DIR \
    --preboom-prob-dir "$PREBOOM_DIR/$AOI/prob" >> "$LOG" 2>&1
  touch "$MARKERS/postprocess"
else
  log "STEP2: already done, skipping"
fi

if [ ! -f "$MARKERS/export" ]; then
  log "STEP3: re-export (rank_score changed)"
  $PY_DEFAULT -m earthpv.cli export --aoi $AOI --pred-dir $PRED_DIR \
    --exclude-mapped --min-distance-m 100 >> "$LOG" 2>&1
  touch "$MARKERS/export"
else
  log "STEP3: already done, skipping"
fi

log "PREBOOM_PK16085_RESCORE_COMPLETE"
