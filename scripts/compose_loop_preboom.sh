#!/usr/bin/env bash
# Auto-restarting compose loop for the pre-boom epoch layer (index 1, pakistan).
#
# Same token-expiry problem as compose_loop.sh (PC SAS tokens outlive under a slow-network
# read backlog after ~30-45 min, throughput collapses with response_code=403/206 errors).
# This was previously being relaunched by hand every ~30 min (see the repeated
# "Selected 4464 cells" / "Compositing 4464 cells" restarts in data/preboom_pipeline.log);
# this wrapper automates that instead of requiring a human/agent to notice and relaunch.
#
# Exits when the target cell count is reached, compose exits cleanly, or progress stalls.
# Run detached:
#   nohup setsid bash scripts/compose_loop_preboom.sh >/dev/null 2>&1 </dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
[ -x "$PY" ] || PY=python
AOI=pakistan
LOG=data/preboom_pipeline.log
TARGET=4464
ITER=1800          # 30 min per fresh process, comfortably under the token lifetime
COMPDIR="data/composites/$AOI/composites"

prev=-1; stall=0
echo "$(date '+%F %T') === LOOP START: pre-boom compose auto-restart wrapper ===" >> "$LOG"
while true; do
  done=$(find "$COMPDIR" -name composite_1.tif 2>/dev/null | wc -l)
  echo "$(date '+%F %T') LOOP: ${done}/${TARGET} done (stall=${stall})" >> "$LOG"
  [ "$done" -ge "$TARGET" ] && { echo "$(date '+%F %T') LOOP: target reached, exiting" >> "$LOG"; break; }
  if [ "$done" -le "$prev" ]; then stall=$((stall+1)); else stall=0; fi
  [ "$stall" -ge 3 ] && { echo "$(date '+%F %T') LOOP: no progress 3x at ${done}, exiting" >> "$LOG"; break; }
  prev=$done
  # 4 workers, not 6: 6 peaked at 11.4G RSS and got the unit oom-killed while GPU
  # inference was also running (2026-07-19); network-bound anyway, so cost is small.
  timeout -k 60 "$ITER" $PY -m earthpv.cli compose --aoi "$AOI" --min-buildings 1000 --use-vida \
    --workers 4 --index 1 --window 2021-10-01:2022-01-24 >> "$LOG" 2>&1
  rc=$?
  echo "$(date '+%F %T') LOOP: iteration exit rc=${rc}" >> "$LOG"
  [ "$rc" -eq 0 ] && { echo "$(date '+%F %T') LOOP: compose exited cleanly, done" >> "$LOG"; break; }
  sleep 15   # guard against a tight loop if compose fails instantly
done
echo "$(date '+%F %T') LOOP: wrapper exiting" >> "$LOG"
