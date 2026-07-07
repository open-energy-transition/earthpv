#!/usr/bin/env bash
# Auto-restarting compose loop for long runs.
#
# A single long compose process 403-storms ~30-45 min in: its Planetary Computer SAS token
# expires, blob reads start returning response_code=403, GDAL retries with backoff, and
# throughput collapses. The signer (planetary_computer.sign_inplace) already auto-refreshes,
# but under a slow-network read backlog the reads outlive the token. Fix: time-box each
# compose to under the token lifetime and relaunch a FRESH process (fresh token, drained
# backlog). compose is resumable (temp-then-rename writes), so each pass skips done cells.
#
# Exits when the target cell count is reached, compose exits cleanly (all compositable cells
# done), or progress stalls (remaining cells have no scenes). Run detached:
#   nohup setsid bash scripts/compose_loop.sh >/dev/null 2>&1 </dev/null &
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
[ -x "$PY" ] || PY=python
AOI=pakistan
LOG=data/compose_pakistan.log
TARGET=1393
ITER=1800          # 30 min per fresh process, comfortably under the token lifetime
COMPDIR="data/composites/$AOI/composites"

prev=-1; stall=0
while true; do
  done=$(find "$COMPDIR" -name composite_0.tif 2>/dev/null | wc -l)
  echo "$(date '+%F %T') LOOP: ${done}/${TARGET} done (stall=${stall})" >> "$LOG"
  [ "$done" -ge "$TARGET" ] && { echo "$(date '+%F %T') LOOP: target reached, exiting" >> "$LOG"; break; }
  if [ "$done" -le "$prev" ]; then stall=$((stall+1)); else stall=0; fi
  [ "$stall" -ge 3 ] && { echo "$(date '+%F %T') LOOP: no progress 3x at ${done}, exiting" >> "$LOG"; break; }
  prev=$done
  timeout -k 60 "$ITER" $PY -m earthpv.cli compose --aoi "$AOI" --min-buildings 100 --workers 6 >> "$LOG" 2>&1
  rc=$?
  echo "$(date '+%F %T') LOOP: iteration exit rc=${rc}" >> "$LOG"
  # rc 124 = timed out (expected: token-refresh restart). rc 0 = compose processed the whole
  # cell list (all compositable cells done) -> finished.
  [ "$rc" -eq 0 ] && { echo "$(date '+%F %T') LOOP: compose exited cleanly, done" >> "$LOG"; break; }
  sleep 15   # guard against a tight loop if compose fails instantly
done
echo "$(date '+%F %T') LOOP: wrapper exiting" >> "$LOG"
