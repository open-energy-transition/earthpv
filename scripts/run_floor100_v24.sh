#!/usr/bin/env bash
# Scores v24 (configs/terramind_pv_v24_pakistan_floor100.yaml: v16 with Pakistan's 100-400 m2
# arrays trained as PV) against v16 once unit earthpv-v24-floor100 has finished training.
#
#   systemd-run --user --collect --unit=earthpv-v24-eval -p WorkingDirectory="$PWD" \
#     -p MemoryMax=14G bash scripts/run_floor100_v24.sh
#
# Both of each run's saved checkpoints are scored (v16 epochs 30 and 38; v24's best and
# second-best val/mIoU), so the comparison shows how far epoch choice alone moves the numbers.
# Small arrays: scripts/small_array_eval.py (holdout chips + calibration areas, down to 100 m2).
# Arrays of 400 m2 and up: scripts/compare_backbones.py on Pakistan's holdouts, as v16 was shipped.
# Resumable: every step leaves a marker in data/v24_floor100_markers/.
set -u
cd "$(dirname "$0")/.."

MLPY=.pixi/envs/ml/bin/python
PY=.pixi/envs/default/bin/python
MARK=data/v24_floor100_markers
LOG=/home/tobi/earthpv_data/models/v24_eval.log
GPU_LOCK=data/.gpu.lock
E=/home/tobi/earthpv_data/small_array_eval
RUN=/home/tobi/earthpv_data/models/v24_pakistan_floor100
V16=/home/tobi/earthpv_data/models/v16_combined_pakistan/terramind-pv-epoch=30-step=65348.ckpt
V16E38=/home/tobi/earthpv_data/models/v16_combined_pakistan/terramind-pv-epoch=38-step=82212.ckpt
V16_RASTERS=/home/tobi/earthpv_data/seg_v16_pakistan/pakistan/prob
mkdir -p "$MARK"
export PYTHONUNBUFFERED=1
export GDAL_CACHEMAX=128

say() { echo "$(date '+%F %T') V24EVAL: $*" | tee -a "$LOG"; }
step() {  # step <marker> <command...>
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then say "FAILED $(basename "$m") rc=$rc"; exit $rc; fi
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}
gpu() { flock "$GPU_LOCK" "$@"; }

while systemctl --user is-active --quiet earthpv-v24-floor100; do sleep 300; done
grep -q "V24 TRAIN DONE" /home/tobi/earthpv_data/models/v24_train.log \
  || { say "training did not finish (no V24 TRAIN DONE in v24_train.log)"; exit 1; }

BEST=$($MLPY scripts/pick_best_checkpoint.py "$RUN" 2>/dev/null | tail -1)
[ -f "$BEST" ] || { say "pick_best_checkpoint gave no file: $BEST"; exit 1; }
OTHER=$(ls -t "$RUN"/*-epoch=*.ckpt | grep -vF "$(basename "$BEST")" | head -1)
say "v24 best $BEST, second $OTHER"

CELLS=$(paste -sd, "$E/area_cells.txt")
step chip_infer gpu $MLPY scripts/small_array_eval.py chip-infer --ckpt "v24=$BEST" --ckpt "v24b=$OTHER"
step infer_v24 gpu $MLPY -m earthpv.cli infer --aoi pakistan --checkpoint "$BEST" \
  --out-dir "$E/rasters/v24" --tiles "$CELLS"
step infer_v24b gpu $MLPY -m earthpv.cli infer --aoi pakistan --checkpoint "$OTHER" \
  --out-dir "$E/rasters/v24b" --tiles "$CELLS"
step score $PY scripts/small_array_eval.py score --name v24_floor100_vs_v16 \
  --ckpt "v16=$V16" --ckpt "v16e38=$V16E38" --ckpt "v24=$BEST" --ckpt "v24b=$OTHER" \
  --rasters "v16=$V16_RASTERS" --rasters "v16e38=$E/rasters/v16e38/pakistan/prob" \
  --rasters "v24=$E/rasters/v24/pakistan/prob" --rasters "v24b=$E/rasters/v24b/pakistan/prob"
step compare gpu $MLPY scripts/compare_backbones.py --name v24_floor100_vs_v16 \
  --ckpt "v16=$V16" --ckpt "v16e38=$V16E38" --ckpt "v24=$BEST" --ckpt "v24b=$OTHER" \
  --aois pakistan_fresh@pakistan pakistan punjab --match-aois pakistan_fresh pakistan punjab
say "V24 EVAL DONE: results/small_array_eval/v24_floor100_vs_v16/ results/backbone_compare/v24_floor100_vs_v16/"
