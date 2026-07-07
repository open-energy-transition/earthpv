#!/usr/bin/env bash
# Wait for the pakistan compose loop (scripts/compose_loop.sh) to finish, then run the
# inference tail on the cells it composited: infer -> postprocess -> export.
#
# "Finish" = the compose_loop wrapper process is gone, which covers all its exit paths
# (target reached, clean rc=0, or stall-out). Whatever imagery exists at that point is
# what we infer on. Launch detached:
#   nohup setsid bash scripts/infer_after_compose.sh >/dev/null 2>&1 </dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."
AOI=pakistan
LOG=data/infer_after_compose_pakistan.log
CKPT=data/models/v2_combined/terramind-pv-epoch=39-step=8240.ckpt   # v2_combined best-val (10-band)
MLPY=.pixi/envs/ml/bin/python        # GPU stage
PY=.pixi/envs/default/bin/python     # data stages
[ -x "$MLPY" ] || MLPY=python
[ -x "$PY" ] || PY=python

echo "$(date '+%F %T') WATCH: waiting for scripts/compose_loop.sh to finish" >> "$LOG"
while pgrep -f "scripts/compose_loop.sh" >/dev/null 2>&1; do sleep 60; done
n=$(find "data/composites/$AOI/composites" -name composite_0.tif 2>/dev/null | wc -l)
echo "$(date '+%F %T') WATCH: compose_loop gone; ${n} composited cells" >> "$LOG"

run_stage() {  # name  interpreter  cli-args...
  local name=$1; shift; local py=$1; shift
  echo "$(date '+%F %T') ${name}: starting" >> "$LOG"
  "$py" -m earthpv.cli "$@" >> "$LOG" 2>&1
  local rc=$?
  echo "$(date '+%F %T') ${name}: exit rc=${rc}" >> "$LOG"
  if [ "$rc" -ne 0 ]; then
    echo "$(date '+%F %T') ${name} FAILED (rc=${rc}) -- aborting tail" >> "$LOG"
    exit "$rc"
  fi
}

run_stage INFER       "$MLPY" infer       --aoi "$AOI" --checkpoint "$CKPT"
run_stage POSTPROCESS "$PY"   postprocess --aoi "$AOI"
run_stage EXPORT      "$PY"   export      --aoi "$AOI"

echo "$(date '+%F %T') WATCH: tail complete -- infer/postprocess/export done" >> "$LOG"
