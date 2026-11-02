#!/usr/bin/env bash
# Yemen's segmentation re-localized on the 2026-11-01 OpenStreetMap pull (v25, owner request
# 2026-11-01: "run a new segmentation for Yemen with a localized model using the new
# training data"). configs/terramind_pv_v25_yemen.yaml is v13's recipe and base corpus;
# only the Yemen chips are new.
#
#   systemd-run --user --collect --unit=earthpv-v25-yemen -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=14G bash scripts/run_yemen_v25.sh
#
# chips -> val buffer -> merge -> train (retried, resumes from last.ckpt) -> v25's two saved
# epochs against v13 and v5 on the 'Amran holdout (compare_backbones.py, matched precision)
# -> national inference with v25's best -> postprocess, leads, precision table, density.
# Everything is written beside the published run, never over it: chips in
# /home/tobi/earthpv_data/chips_v25/yemen (data/chips/yemen_v25), predictions, leads, table
# and density in /home/tobi/earthpv_data/predictions_v25/yemen. The atlas is built by hand
# afterwards, for review before anything is published. Resumable: markers in
# data/yemen_v25_markers/.
set -u
cd "$(dirname "$0")/.."

PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
MARK=data/yemen_v25_markers
LOG=/home/tobi/earthpv_data/models/v25_yemen.log
GPU_LOCK=data/.gpu.lock
CHIPS=/home/tobi/earthpv_data/chips_v25
COMBINED=/home/tobi/earthpv_data/chips/combined_yemen_v25
RUN=/home/tobi/earthpv_data/models/v25_combined_yemen
PRED=/home/tobi/earthpv_data/predictions_v25
CONFIG=configs/terramind_pv_v25_yemen.yaml
V13=data/models/v13_combined_yemen/terramind-pv-epoch=28-step=45733.ckpt
V5=data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt
mkdir -p "$MARK" "$CHIPS" "$COMBINED" "$RUN" "$PRED"
export PYTHONUNBUFFERED=1
export GDAL_CACHEMAX=128

say() { echo "$(date '+%F %T') V25: $*" | tee -a "$LOG"; }
step() {  # step <marker> <command...>
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  # check-density exits 1 when a region fails its plausibility check: a finding to read.
  if [ $rc -ne 0 ] && [ "$(basename "$m")" != "check_density" ]; then
    say "FAILED $(basename "$m") rc=$rc"; exit $rc
  fi
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}
gpu() { flock "$GPU_LOCK" "$@"; }

[ -L data/chips/yemen_v25 ] || ln -s "$CHIPS/yemen" data/chips/yemen_v25
[ -L data/chips/combined_yemen_v25 ] || ln -s "$COMBINED" data/chips/combined_yemen_v25
[ -L data/models/v25_combined_yemen ] || ln -s "$RUN" data/models/v25_combined_yemen

step chips $PY -m earthpv.cli chips --aoi yemen --out-dir "$CHIPS"
step val_buffer $PY scripts/mark_val_buffer.py --aoi yemen --chips yemen_v25
read -r NTRAIN NVAL NPOS < <($PY -c "
import pandas as pd
d = pd.read_parquet('data/chips/yemen_v25/index.parquet')
print(int((d.split=='train').sum()), int((d.split=='val').sum()), int((d.pv_pixels>0).sum()))")
say "chips: $NTRAIN train, $NVAL val, $NPOS with PV"
if [ "${NVAL:-0}" -lt 8 ] || [ "${NTRAIN:-0}" -lt 50 ]; then
  say "FAILED chips_checked: too few chips (train $NTRAIN, val $NVAL)"; exit 1
fi
REPEAT=$($PY -c "print(max(1, min(8, round(7000 / max(1, $NTRAIN)))))")
step merge $PY scripts/merge_chip_index.py --out data/chips/combined_yemen_v25/index.parquet \
  germany punjab pakistan gujarat france yemen_v25:$REPEAT

if [ ! -f "$MARK/train" ]; then
  # Let Pakistan's v24 scoring chain finish its last GPU steps first: once this training
  # takes the lock it holds it for ~10 h, and v24's comparison needs only ~30 min.
  while systemctl --user is-active --quiet earthpv-v24-eval; do
    say "waiting for earthpv-v24-eval before training"; sleep 300
  done
  for attempt in 1 2 3 4 5; do
    say "train attempt $attempt"
    gpu $MLPY -m earthpv.cli train --config "$CONFIG" >> "$LOG" 2>&1 && { echo 0 > "$MARK/train"; break; }
    say "train attempt $attempt failed rc=$?"
    sleep 60
  done
  [ -f "$MARK/train" ] || { say "FAILED train: 5 attempts"; exit 1; }
  say "V25 TRAIN DONE"
fi

BEST=$($MLPY scripts/pick_best_checkpoint.py "$RUN" 2>/dev/null | tail -1)
[ -f "$BEST" ] || { say "FAILED pick: $BEST"; exit 1; }
OTHER=$(ls -t "$RUN"/*-epoch=*.ckpt | grep -vF "$(basename "$BEST")" | head -1)
say "v25 best $BEST, second $OTHER"

step compare gpu $MLPY scripts/compare_backbones.py --name v25_yemen_vs_v13 \
  --ckpt "v13=$V13" --ckpt "v25=$BEST" --ckpt "v25b=$OTHER" --ckpt "v5=$V5" \
  --aois yemen_v25@yemen --match-aois yemen_v25
step infer gpu $MLPY -m earthpv.cli infer --aoi yemen --checkpoint "$BEST" --out-dir "$PRED"
step postprocess $PY -m earthpv.cli postprocess --aoi yemen --pred-dir "$PRED" --threshold 0.3 \
  --building-buffer-m 500 --stream-buildings
step export $PY -m earthpv.cli export --aoi yemen --pred-dir "$PRED" --exclude-mapped \
  --min-distance-m 100
step calibrate $PY -m earthpv.cli calibrate-candidates --aoi yemen --pred-dir "$PRED" \
  --recall-reference none --out "$PRED/yemen/yemen_candidate_precision.yaml"
step density $PY -m earthpv.cli density --aoi yemen --pred-dir "$PRED" --districts \
  --calibration "$PRED/yemen/yemen_candidate_precision.yaml"
step check_density $PY -m earthpv.cli check-density --aoi yemen --pred-dir "$PRED"
say "V25 CHAIN DONE: $PRED/yemen, results/backbone_compare/v25_yemen_vs_v13/"
