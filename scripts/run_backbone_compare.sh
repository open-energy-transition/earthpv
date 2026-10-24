#!/usr/bin/env bash
# Train the THOR backbone-comparison pair on v14's corpus, sequentially: the ps16 control
# first (~10 h, catches a broken run early), then ps8 (~40 h). v14 itself is the baseline and
# is not retrained. Scoring is a separate step (scripts/compare_backbones.py), run after both.
# Each run's stdout/stderr goes to data/backbone_compare_<run>.log; a marker
# data/backbone_compare_markers/<run>_done is written on success and the run is skipped if
# present, so relaunching the unit resumes where it stopped; within a run, the configs set
# `resume: true`, so a killed run continues from its last.ckpt.
#
#   systemd-run --user --unit earthpv-thor-compare --property=MemoryMax=16G \
#       --working-directory="$PWD" bash scripts/run_backbone_compare.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/ml/bin/python
mkdir -p data/backbone_compare_markers
export PYTHONUNBUFFERED=1
# GDAL's block cache defaults to 5% of RAM PER PROCESS (main + 4 loader workers, ~1.5 GB
# each here); whole-chip reads gain nothing from it. The first launch grew to 9.5 GB and
# was the unit systemd-oomd picked under memory pressure.
export GDAL_CACHEMAX=128
for run in ps16 ps8; do
  marker=data/backbone_compare_markers/${run}_done
  if [[ -f $marker ]]; then echo "$(date '+%F %T') skip $run (done)"; continue; fi
  echo "$(date '+%F %T') start $run"
  $PY -m earthpv.cli train --config configs/thor_pv_${run}_south_africa.yaml \
      > data/backbone_compare_${run}.log 2>&1
  rc=$?
  echo "$(date '+%F %T') done $run rc=$rc"
  if [[ $rc -ne 0 ]]; then exit $rc; fi
  touch "$marker"
done
echo "$(date '+%F %T') ALL TRAINED"
