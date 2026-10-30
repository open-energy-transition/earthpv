#!/usr/bin/env bash
# v21: v14's recipe and corpus with TerraMind's own input standardisation, then scored against
# v14 on the 11 holdouts the THOR comparison used. See configs/terramind_pv_v21_tmnorm_south_africa.yaml.
#
#   systemd-run --user --collect --unit=earthpv-v21-tmnorm -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=14G bash scripts/run_tmnorm_compare.sh
#
# Resumable: every step leaves a marker in data/tmnorm_v21_markers/, and train continues from
# its own last.ckpt (`resume: true`). GPU steps take the same lock as run_country_compute.sh.
#
# Four checkpoints are scored, so the normalisation effect can be read against epoch noise:
# v14 epoch 41 (shipped; the baseline and the precision target), v14 epoch 49 (its other saved
# epoch), and BOTH of v21's saved epochs (Lightning's top 2 by val/mIoU).
set -u
cd "$(dirname "$0")/.."

MLPY=.pixi/envs/ml/bin/python
MARK=data/tmnorm_v21_markers
LOG=data/tmnorm_v21.log
GPU_LOCK=data/.gpu.lock
CONFIG=configs/terramind_pv_v21_tmnorm_south_africa.yaml
RUN_DIR=data/models/v21_tmnorm_south_africa
HOME_DIR=/home/tobi/earthpv_data/models/v21_tmnorm_south_africa
V14=data/models/v14_combined_south_africa/terramind-pv-epoch=41-step=79968.ckpt
V14E49=data/models/v14_combined_south_africa/terramind-pv-epoch=49-step=95200.ckpt
mkdir -p "$MARK"
export PYTHONUNBUFFERED=1
export GDAL_CACHEMAX=128  # see run_backbone_compare.sh: the per-process default got a unit oomd-killed

say() { echo "$(date '+%F %T') V21: $*" | tee -a "$LOG"; }
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

# Checkpoints live on /home: the aidisc drive is the binding constraint.
mkdir -p "$HOME_DIR"
[ -e "$RUN_DIR" ] || ln -s "$HOME_DIR" "$RUN_DIR"

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

# Both saved epochs, best first, from Lightning's own record in every last*.ckpt (never mtime).
mapfile -t TOP < <($MLPY - "$RUN_DIR" 2>>"$LOG" <<'EOF'
import glob, os, sys, torch
scores = {}
for last in glob.glob(os.path.join(sys.argv[1], "last*.ckpt")):
    ck = torch.load(last, map_location="cpu", weights_only=False)
    for key, state in ck.get("callbacks", {}).items():
        if key.startswith("ModelCheckpoint"):
            for path, score in state.get("best_k_models", {}).items():
                if os.path.exists(path):
                    scores[path] = float(score)
for path, score in sorted(scores.items(), key=lambda kv: -kv[1])[:2]:
    print(path)
    print(f"{os.path.basename(path)} val/mIoU {score:.4f}", file=sys.stderr)
EOF
)
[ "${#TOP[@]}" -ge 1 ] || { say "FAILED pick: no checkpoint"; exit 1; }
say "v21 saved epochs: ${TOP[*]}"
CKPTS=(--ckpt v14=$V14 --ckpt v14e49=$V14E49 --ckpt "v21=${TOP[0]}")
[ "${#TOP[@]}" -ge 2 ] && CKPTS+=(--ckpt "v21b=${TOP[1]}")

# Thresholds reach far below 0.3 because a more precise model matches v14's pixel precision
# only there (v18 needed 0.0003), and above it for a less precise one.
step compare gpu $MLPY scripts/compare_backbones.py --name v21_tmnorm_vs_v14 "${CKPTS[@]}" \
  --aois south_africa france germany pakistan punjab gujarat poland vietnam india morocco egypt \
  --match-aois south_africa france germany pakistan punjab gujarat \
  --thresholds 0.0003 0.001 0.003 0.01 0.03 0.05 0.1 0.15 0.2 0.25 0.3 0.4 0.5 0.6 0.7 0.8

say "V21 DONE: results/backbone_compare/v21_tmnorm_vs_v14/"
