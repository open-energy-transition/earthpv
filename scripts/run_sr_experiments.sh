#!/usr/bin/env bash
# Waits for the running country-wide density recompute (earthpv-density-cal, CPU-heavy)
# to finish, then runs the three super-resolution feasibility tests in sequence:
#   1. sr_band_fusion_experiment.py   — guided 20m-band fusion (CPU, offline, local chips)
#   2. sr_multitemporal_experiment.py — multi-image SR feasibility (network, STAC pulls)
#   3. sr_hallucination_experiment.py — internal-learning SISR hallucination risk (GPU)
#
# Resumable via marker files under data/.sr_experiments/ (same idiom as
# run_after_train_pk16085.sh / run_preboom_pipeline.sh) — safe to relaunch after a kill.
#
# Run detached, its own systemd unit (isolates it from other running jobs' OOM/crash):
#   systemd-run --user --collect --unit=earthpv-sr-experiments -p Restart=on-failure \
#     -p RestartSec=60 -p WorkingDirectory=/run/media/tobi/aidisc/earthpv \
#     bash scripts/run_sr_experiments.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PY_DEFAULT=.pixi/envs/default/bin/python
PY_ML=.pixi/envs/ml/bin/python
LOG=data/sr_experiments.log
MARKERS=data/.sr_experiments
WAIT_UNIT=earthpv-density-cal

mkdir -p data "$MARKERS"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# ---- Step 0: wait for the density recompute to free up the CPU -----------------------
log "STEP0: waiting for $WAIT_UNIT to finish"
while systemctl --user is-active "$WAIT_UNIT" >/dev/null 2>&1; do
  sleep 120
done
log "STEP0: $WAIT_UNIT no longer running"

# ---- Step 1: band-fusion experiment (CPU, offline) ------------------------------------
if [ ! -f "$MARKERS/band_fusion" ]; then
  log "STEP1: sr_band_fusion_experiment.py"
  $PY_DEFAULT scripts/sr_band_fusion_experiment.py --aoi germany --n 80 >> "$LOG" 2>&1
  touch "$MARKERS/band_fusion"
else
  log "STEP1: already done, skipping"
fi

# ---- Step 2: multi-temporal experiment (network, STAC) --------------------------------
if [ ! -f "$MARKERS/multitemporal" ]; then
  log "STEP2: sr_multitemporal_experiment.py"
  $PY_DEFAULT scripts/sr_multitemporal_experiment.py --aoi germany --n-points 8 --n-scenes 12 >> "$LOG" 2>&1
  touch "$MARKERS/multitemporal"
else
  log "STEP2: already done, skipping"
fi

# ---- Step 3: hallucination experiment (GPU) -------------------------------------------
if [ ! -f "$MARKERS/hallucination" ]; then
  log "STEP3: sr_hallucination_experiment.py"
  $PY_ML scripts/sr_hallucination_experiment.py --aoi germany --n 15 >> "$LOG" 2>&1
  touch "$MARKERS/hallucination"
else
  log "STEP3: already done, skipping"
fi

log "SR EXPERIMENTS COMPLETE — see data/sr_band_fusion_experiment.csv, "
log "data/sr_multitemporal_experiment.csv, data/sr_hallucination_experiment.csv"
