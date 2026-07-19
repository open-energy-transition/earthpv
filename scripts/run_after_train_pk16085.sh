#!/usr/bin/env bash
# Post-training pipeline for the pk16085 model (trained on chips rebuilt from the user's
# Overpass-downloaded PV data, see data/labels/pakistan_overpass_solar.parquet).
#
# Sequence (resumable via marker files under data/.pk16085_pipeline, guarded like
# run_preboom_pipeline.sh):
#   1. wait for the running `earthpv.cli train` process to exit
#   2. pick the best of the 2 top-k checkpoints by eval F1 on the Pakistan val split
#   3. full-Pakistan inference with that checkpoint -> data/predictions_pk16085
#      (a FRESH out-dir -- data/predictions is the v3_combined_india / preboom-pipeline
#      output and must not be clobbered by this run)
#   4. postprocess (threshold, polygonize, join buildings, rank_score)
#   5. density (per-building + grid + region PV density/capacity aggregates)
#   6. export new leads (candidates not near any already-mapped OSM solar feature)
#
# Run detached: nohup setsid bash scripts/run_after_train_pk16085.sh > /dev/null 2>&1 < /dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."

PY_DEFAULT=.pixi/envs/default/bin/python
PY_ML=.pixi/envs/ml/bin/python
AOI=pakistan
PRED_DIR=data/predictions_pk16085
LOG=data/pk16085_pipeline.log
MARKERS=data/.pk16085_pipeline

mkdir -p data "$MARKERS"

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# ---- Step 1: wait for training to finish -------------------------------------------
log "STEP1: waiting for earthpv.cli train to exit"
while pgrep -f "earthpv.cli train" >/dev/null; do
  sleep 300
done
log "STEP1: training process no longer running"

# ---- Step 2: pick best checkpoint by eval F1 ----------------------------------------
if [ ! -f "$MARKERS/checkpoint_chosen" ]; then
  log "STEP2: evaluating top-k checkpoints on $AOI val split"
  best_ckpt=""
  best_f1="-1"
  for ckpt in data/models/terramind-pv-epoch=*.ckpt; do
    [ -e "$ckpt" ] || continue
    log "STEP2: evaluating $ckpt"
    $PY_ML -m earthpv.cli evaluate --aoi $AOI --checkpoint "$ckpt" >> "$LOG" 2>&1
    f1=$(grep -oE "F1=[0-9.]+" "$LOG" | tail -1 | cut -d= -f2)
    log "STEP2: $ckpt -> F1=${f1:-unknown}"
    if [ -n "${f1:-}" ] && awk "BEGIN{exit !($f1 > $best_f1)}"; then
      best_f1=$f1
      best_ckpt=$ckpt
    fi
  done
  if [ -z "$best_ckpt" ]; then
    log "STEP2: ABORT -- no checkpoint could be evaluated"
    touch "$MARKERS/aborted"
    exit 1
  fi
  log "STEP2: chosen checkpoint = $best_ckpt (F1=$best_f1)"
  echo "$best_ckpt" > "$MARKERS/checkpoint_chosen"
else
  log "STEP2: already done, skipping"
fi
CHECKPOINT=$(cat "$MARKERS/checkpoint_chosen")

# ---- Step 3: full-Pakistan inference -------------------------------------------------
if [ ! -f "$MARKERS/infer" ]; then
  log "STEP3: full-Pakistan inference with $CHECKPOINT -> $PRED_DIR"
  $PY_ML -m earthpv.cli infer --aoi $AOI --checkpoint "$CHECKPOINT" --out-dir $PRED_DIR >> "$LOG" 2>&1
  touch "$MARKERS/infer"
else
  log "STEP3: already done, skipping"
fi

# ---- Step 4: postprocess --------------------------------------------------------------
if [ ! -f "$MARKERS/postprocess" ]; then
  log "STEP4: postprocess"
  $PY_DEFAULT -m earthpv.cli postprocess --aoi $AOI --pred-dir $PRED_DIR >> "$LOG" 2>&1
  touch "$MARKERS/postprocess"
else
  log "STEP4: already done, skipping"
fi

# ---- Step 5: density (PV density + capacity aggregates, all candidates) --------------
if [ ! -f "$MARKERS/density" ]; then
  log "STEP5: density"
  $PY_DEFAULT -m earthpv.cli density --aoi $AOI --pred-dir $PRED_DIR \
    --regions-file data/labels/pakistan_regions.parquet --districts >> "$LOG" 2>&1
  touch "$MARKERS/density"
else
  log "STEP5: already done, skipping"
fi

# ---- Step 6: export new leads ---------------------------------------------------------
if [ ! -f "$MARKERS/export" ]; then
  log "STEP6: export (+ new leads, 100m distance filter)"
  $PY_DEFAULT -m earthpv.cli export --aoi $AOI --pred-dir $PRED_DIR \
    --exclude-mapped --min-distance-m 100 >> "$LOG" 2>&1
  touch "$MARKERS/export"
else
  log "STEP6: already done, skipping"
fi

log "PIPELINE COMPLETE"
