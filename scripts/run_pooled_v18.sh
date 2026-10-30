#!/usr/bin/env bash
# v18: v16's corpus pooled with every country's own chips plus national German chips, then
# scored against v14 (released) and v16 (Pakistan's) on every region's held-out chips.
# See configs/terramind_pv_v18_pooled.yaml for what the corpus holds and why.
#
#   systemd-run --user --collect --unit=earthpv-v18-pooled -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=14G bash scripts/run_pooled_v18.sh
#
# Resumable: every step leaves a marker in data/pooled_v18_markers/, and train continues from
# its own last.ckpt (`resume: true`). GPU steps take the same lock as run_country_compute.sh,
# so a country's training queued behind this one waits instead of sharing the 6 GB card.
set -u
cd "$(dirname "$0")/.."

PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
MARK=data/pooled_v18_markers
LOG=data/pooled_v18.log
GPU_LOCK=data/.gpu.lock
WORK=/home/tobi/earthpv_data/pooled_v18
CONFIG=configs/terramind_pv_v18_pooled.yaml
V14=data/models/release/earthpv_segmentation_v14.ckpt
V16=data/models/v16_combined_pakistan/terramind-pv-epoch=30-step=65348.ckpt
mkdir -p "$MARK"

say() { echo "$(date '+%F %T') V18: $*" | tee -a "$LOG"; }
gpu() {  # same lock and foreign-job test as run_country_compute.sh
  flock "$GPU_LOCK" bash -c '
    while nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null \
          | awk "\$1 > 1024 {f=1} END {exit !f}"; do
      echo "$(date "+%F %T") GPU busy with a foreign job; waiting" >&2; sleep 300
    done
    exec "$@"' _ "$@"
}
step() {  # step <marker> <command...>
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then say "FAILED $(basename "$m") rc=$rc"; exit $rc; fi
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}

step chips_germany_national $PY -m earthpv.cli chips --aoi germany \
  --labels-dir $WORK/labels_germany --out-dir data/chips/germany_national \
  --region-filter $WORK/germany_region_filter.parquet --max-positives 3500

step merge $PY scripts/build_pooled_corpus.py --out data/chips/combined_pooled_v18/index.parquet

# An oomd kill or a crash resumes from last.ckpt; a run that fails five times stops here.
if [ ! -f "$MARK/train" ]; then
  for attempt in 1 2 3 4 5; do
    say "start train (attempt $attempt)"
    gpu $MLPY -m earthpv.cli train --config $CONFIG >> "$LOG" 2>&1 && { echo 0 > "$MARK/train"; break; }
    say "train attempt $attempt failed rc=$?"; sleep 120
  done
  [ -f "$MARK/train" ] || { say "FAILED train after 5 attempts"; exit 1; }
  say "done train"
fi

V18=$($MLPY scripts/pick_best_checkpoint.py data/models/v18_pooled 2>>"$LOG" | head -1)
[ -n "$V18" ] || { say "FAILED pick: no checkpoint"; exit 1; }
say "best v18 checkpoint: $V18"

step compare gpu $MLPY scripts/compare_backbones.py --name v18_pooled_vs_v14_v16 \
  --ckpt v14=$V14 --ckpt v16=$V16 --ckpt v18=$V18 \
  --aois south_africa france germany pakistan pakistan_fresh@pakistan punjab gujarat india poland \
         vietnam morocco egypt yemen zambia \
  --match-aois south_africa france germany pakistan punjab gujarat

say "V18 DONE: results/backbone_compare/v18_pooled_vs_v14_v16/"
