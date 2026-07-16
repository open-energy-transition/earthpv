#!/usr/bin/env bash
# Pre-boom epoch differencing -> rescored candidates, PV growth map, pvlib capacity check.
#
# Sequences (resumable via marker files under data/.*_done, guarded like compose_loop.sh):
#   1. wait for the running index-0 (current-epoch) compose to finish
#   2. in parallel: pre-boom compose (index 1, network-bound) || eval-gate + current-epoch
#      inference (GPU-bound) -- no resource contention, so these overlap
#   3. pre-boom epoch inference (GPU; needs step 2's pre-boom compose done)
#   4. postprocess current epoch, epoch-diff rescored against the pre-boom prob rasters
#   5. postprocess pre-boom epoch (reuses the VIDA buildings cache from step 4 -- same
#      physical buildings, avoids a duplicate country-scale fetch)
#   6. density both epochs
#   7. PV growth map (current - pre-boom, scripts/pv_growth_map.py)
#   8. pvlib capacity double-check (module database + PVGIS yield cross-check)
#   9. export final rescored candidates + MapRoulette challenge
#
# Run detached: nohup setsid bash scripts/run_preboom_pipeline.sh > data/preboom_pipeline.log 2>&1 < /dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."

PY_DEFAULT=.pixi/envs/default/bin/python
PY_ML=.pixi/envs/ml/bin/python
AOI=pakistan
CHECKPOINT="data/models/v3_combined_india/terramind-pv-epoch=22-step=9062.ckpt"
CURRENT_DIR=data/predictions
PREBOOM_DIR=data/predictions_preboom
LOG=data/preboom_pipeline.log
TOTAL_CELLS=4464
MARKERS=data/.preboom_pipeline

mkdir -p data "$MARKERS"

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# ---- Step 1: wait for the running index-0 compose ----------------------------------
log "STEP1: waiting for index-0 compose ($TOTAL_CELLS cells)"
while true; do
  done=$(find data/composites/$AOI/composites -name composite_0.tif 2>/dev/null | wc -l)
  running=$(pgrep -f "earthpv.cli compose --aoi $AOI" >/dev/null && echo yes || echo no)
  if [ "$done" -ge "$TOTAL_CELLS" ] || [ "$running" = no ]; then
    log "STEP1: done ($done/$TOTAL_CELLS cells, compose process running=$running)"
    break
  fi
  sleep 300
done

# ---- Step 2: parallel tracks --------------------------------------------------------
TRACK_A=""
if [ ! -f "$MARKERS/compose_preboom" ]; then
  log "STEP2A: launching pre-boom compose (index 1, 2021-10-01:2022-01-24, 6 workers)"
  (
    $PY_DEFAULT -m earthpv.cli compose --aoi $AOI --min-buildings 1000 --use-vida \
      --workers 6 --index 1 --window 2021-10-01:2022-01-24 >> "$LOG" 2>&1
    touch "$MARKERS/compose_preboom"
  ) &
  TRACK_A=$!
else
  log "STEP2A: already done, skipping"
fi

TRACK_B=""
if [ ! -f "$MARKERS/infer_current" ]; then
  (
    log "STEP2B: evaluating $CHECKPOINT on the Multan val split (safety gate -- this " \
        "checkpoint has no prior evaluation; compare its F1 by eye against v3 epoch=07's " \
        "documented 0.929 per-installation recall before trusting the run)"
    $PY_ML -m earthpv.cli evaluate --aoi $AOI --checkpoint "$CHECKPOINT" >> "$LOG" 2>&1
    f1=$(grep -oE "F1=[0-9.]+" "$LOG" | tail -1 | cut -d= -f2)
    log "STEP2B: eval F1=${f1:-unknown}"
    # Catches a totally broken checkpoint (bad load, wrong task_type, near-zero output) --
    # NOT a quality bar. 0.05 is a "something is badly wrong" floor, not a target.
    if [ -n "${f1:-}" ] && awk "BEGIN{exit !($f1 < 0.05)}"; then
      log "STEP2B: ABORT -- F1 $f1 looks catastrophically broken; not running country-wide inference"
      touch "$MARKERS/aborted"
      exit 1
    fi
    log "STEP2B: launching current-epoch full-Pakistan inference"
    $PY_ML -m earthpv.cli infer --aoi $AOI --checkpoint "$CHECKPOINT" --out-dir $CURRENT_DIR >> "$LOG" 2>&1
    touch "$MARKERS/infer_current"
  ) &
  TRACK_B=$!
else
  log "STEP2B: already done, skipping"
fi

[ -n "$TRACK_A" ] && wait "$TRACK_A"
[ -n "$TRACK_B" ] && wait "$TRACK_B"

if [ -f "$MARKERS/aborted" ]; then
  log "PIPELINE ABORTED at step 2B -- see eval log above. Exiting wrapper."
  exit 1
fi
log "STEP2: both tracks done"

# ---- Step 3: pre-boom epoch inference ------------------------------------------------
if [ ! -f "$MARKERS/infer_preboom" ]; then
  log "STEP3: pre-boom epoch inference"
  $PY_ML -m earthpv.cli infer --aoi $AOI --checkpoint "$CHECKPOINT" \
    --out-dir $PREBOOM_DIR --index 1 >> "$LOG" 2>&1
  touch "$MARKERS/infer_preboom"
else
  log "STEP3: already done, skipping"
fi

# ---- Step 4: postprocess current epoch, epoch-diff rescored -------------------------
if [ ! -f "$MARKERS/postprocess_current" ]; then
  log "STEP4: postprocess current epoch (epoch-diff rescored)"
  $PY_DEFAULT -m earthpv.cli postprocess --aoi $AOI --pred-dir $CURRENT_DIR \
    --preboom-prob-dir "$PREBOOM_DIR/$AOI/prob" >> "$LOG" 2>&1
  touch "$MARKERS/postprocess_current"
else
  log "STEP4: already done, skipping"
fi

# ---- Step 5: postprocess pre-boom epoch (reuse VIDA buildings cache) ----------------
if [ ! -f "$MARKERS/postprocess_preboom" ]; then
  log "STEP5: postprocess pre-boom epoch"
  mkdir -p "$PREBOOM_DIR/$AOI"
  if [ -d "$CURRENT_DIR/$AOI/buildings" ] && [ ! -d "$PREBOOM_DIR/$AOI/buildings" ]; then
    cp -r "$CURRENT_DIR/$AOI/buildings" "$PREBOOM_DIR/$AOI/buildings"
    log "STEP5: reused VIDA buildings cache from $CURRENT_DIR (same physical buildings)"
  fi
  $PY_DEFAULT -m earthpv.cli postprocess --aoi $AOI --pred-dir $PREBOOM_DIR >> "$LOG" 2>&1
  touch "$MARKERS/postprocess_preboom"
else
  log "STEP5: already done, skipping"
fi

# ---- Step 6: density both epochs -----------------------------------------------------
if [ ! -f "$MARKERS/density_current" ]; then
  log "STEP6A: density (current epoch)"
  $PY_DEFAULT -m earthpv.cli density --aoi $AOI --pred-dir $CURRENT_DIR >> "$LOG" 2>&1
  touch "$MARKERS/density_current"
else
  log "STEP6A: already done, skipping"
fi

if [ ! -f "$MARKERS/density_preboom" ]; then
  log "STEP6B: density (pre-boom epoch, reusing cached region polygons)"
  $PY_DEFAULT -m earthpv.cli density --aoi $AOI --pred-dir $PREBOOM_DIR \
    --regions-file data/labels/pakistan_regions.parquet >> "$LOG" 2>&1
  touch "$MARKERS/density_preboom"
else
  log "STEP6B: already done, skipping"
fi

# ---- Step 7: PV growth map ------------------------------------------------------------
if [ ! -f "$MARKERS/growth_map" ]; then
  log "STEP7: PV growth map (current vs pre-boom)"
  $PY_DEFAULT scripts/pv_growth_map.py --aoi $AOI \
    --current-dir $CURRENT_DIR --preboom-dir $PREBOOM_DIR >> "$LOG" 2>&1
  touch "$MARKERS/growth_map"
else
  log "STEP7: already done, skipping"
fi

# ---- Step 8: pvlib capacity double-check ----------------------------------------------
if [ ! -f "$MARKERS/pv_yield" ]; then
  log "STEP8: pvlib capacity double-check"
  $PY_DEFAULT -m earthpv.cli pv-yield --aoi $AOI --pred-dir $CURRENT_DIR >> "$LOG" 2>&1
  touch "$MARKERS/pv_yield"
else
  log "STEP8: already done, skipping"
fi

# ---- Step 9: export final candidates ---------------------------------------------------
if [ ! -f "$MARKERS/export" ]; then
  log "STEP9: export final rescored candidates + MapRoulette challenge"
  $PY_DEFAULT -m earthpv.cli export --aoi $AOI --pred-dir $CURRENT_DIR --exclude-mapped >> "$LOG" 2>&1
  touch "$MARKERS/export"
else
  log "STEP9: already done, skipping"
fi

log "PIPELINE COMPLETE"
