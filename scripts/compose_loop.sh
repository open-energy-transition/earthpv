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
# done), or progress stalls (remaining cells have no scenes).
#
# Usage:  bash scripts/compose_loop.sh [AOI] [TARGET_CELLS] [MIN_BUILDINGS]
#   AOI            default pakistan
#   TARGET_CELLS   stop once this many cells have a composite; 0 (default for a new AOI)
#                  means "run until compose exits cleanly or stalls", which is what you
#                  want when you do not yet know the cell count
#   MIN_BUILDINGS  cell-selection threshold passed through to compose, default 100
#                  (100 is what the country-wide Pakistan run used; the docs
#                  suggest 1000 as a cheaper starting point for a new region)
#
# Run detached, as its own unit so another job's OOM kill cannot take it with it:
#   systemd-run --user --collect --unit=earthpv-compose-<aoi> \
#     -p WorkingDirectory="$PWD" bash scripts/compose_loop.sh <aoi> 0 1000
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
[ -x "$PY" ] || PY=python

AOI=${1:-pakistan}
TARGET=${2:-0}
MIN_BUILDINGS=${3:-100}
LOG="data/compose_${AOI}.log"
ITER=1800          # 30 min per fresh process, comfortably under the token lifetime
COMPDIR="data/composites/$AOI/composites"

mkdir -p data
echo "$(date '+%F %T') LOOP: start aoi=${AOI} target=${TARGET:-none} min_buildings=${MIN_BUILDINGS}" >> "$LOG"

prev=-1; stall=0
while true; do
  done=$(find "$COMPDIR" -name composite_0.tif 2>/dev/null | wc -l)
  echo "$(date '+%F %T') LOOP: ${done}/${TARGET} done (stall=${stall})" >> "$LOG"
  if [ "$TARGET" -gt 0 ] && [ "$done" -ge "$TARGET" ]; then
    echo "$(date '+%F %T') LOOP: target reached, exiting" >> "$LOG"; break
  fi
  if [ "$done" -le "$prev" ]; then stall=$((stall+1)); else stall=0; fi
  [ "$stall" -ge 3 ] && { echo "$(date '+%F %T') LOOP: no progress 3x at ${done}, exiting" >> "$LOG"; break; }
  prev=$done
  timeout -k 60 "$ITER" $PY -m earthpv.cli compose --aoi "$AOI" \
    --min-buildings "$MIN_BUILDINGS" --workers 6 >> "$LOG" 2>&1
  rc=$?
  echo "$(date '+%F %T') LOOP: iteration exit rc=${rc}" >> "$LOG"
  # rc 124 = timed out (expected: token-refresh restart). rc 0 = compose processed the whole
  # cell list (all compositable cells done) -> finished.
  [ "$rc" -eq 0 ] && { echo "$(date '+%F %T') LOOP: compose exited cleanly, done" >> "$LOG"; break; }
  sleep 15   # guard against a tight loop if compose fails instantly
done
echo "$(date '+%F %T') LOOP: wrapper exiting" >> "$LOG"
