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
#   WORKERS        concurrent cells, default 6. The work is network-bound with long
#                  waits (Planetary Computer routinely exceeds imagery.py's 60 s
#                  patience and every cell hands off to Earth Search), so the useful
#                  number is set by latency, not bandwidth: measured on Zambia
#                  2026-09-13, 6 workers ran at 0.29 cells/min while the link was
#                  carrying ~30 MB/min against the ~320 MB/min the same machine
#                  sustains on a parallel download. Raise it when throughput is
#                  latency-bound; watch RSS, since each worker holds a cell's stack.
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
WORKERS=${4:-6}
# Seconds per pass. The France run (2026-09-04/05) needed 2 h passes because a long-lived
# process DEGRADES -- fd leak, RSS past 8 GB, s/it decaying 58 -> 256 -- and a
# crash-triggered loop left it there for four hours. A wall-clock cap is the fix; the
# exact value trades that safety against restart overhead, which is real: each fresh pass
# spends 3-4 minutes before its first cell lands, so 30-minute passes cost ~12% of the run.
ITER_S=${5:-1800}
# Kill a pass early if it writes no cell for this long. The wall-clock cap above bounds a
# pass that DEGRADES; this bounds one that HANGS, which looks completely different from
# outside: measured on Zambia 2026-09-13, compose sat with 118 threads, 210 open sockets
# and 0 MB/min for ten minutes -- alive, no error, no traceback, no progress -- because
# Planetary Computer had started accepting connections and never answering. Without this,
# a hang costs the whole remaining pass.
STALL_S=${6:-600}
# Extra args passed straight through to `compose`, e.g. "--use-vida --window A:B".
# An AOI with no `compose_window` in aoi.yaml (Germany) MUST be given one here, or a
# top-up run lands on the compose default (a Punjab dry season = German winter) and
# silently mixes two epochs into one grid.
EXTRA=${7:-}
LOG="data/compose_${AOI}.log"
ITER=$ITER_S       # per-pass wall clock, see ITER_S above
COMPDIR="data/composites/$AOI/composites"

mkdir -p data
echo "$(date '+%F %T') LOOP: start aoi=${AOI} target=${TARGET:-none} min_buildings=${MIN_BUILDINGS} workers=${WORKERS} iter_s=${ITER_S} extra='${EXTRA}'" >> "$LOG"

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
    --min-buildings "$MIN_BUILDINGS" --workers "$WORKERS" $EXTRA >> "$LOG" 2>&1 &
  pass_pid=$!
  # Stall watchdog for the pass above.
  (
    last=$(find "$COMPDIR" -name composite_0.tif 2>/dev/null | wc -l); quiet=0
    while kill -0 "$pass_pid" 2>/dev/null; do
      sleep 60
      now=$(find "$COMPDIR" -name composite_0.tif 2>/dev/null | wc -l)
      if [ "$now" -gt "$last" ]; then last=$now; quiet=0; else quiet=$((quiet+60)); fi
      if [ "$quiet" -ge "$STALL_S" ]; then
        echo "$(date '+%F %T') LOOP: STALLED ${quiet}s at ${now} cells, killing pass" >> "$LOG"
        pkill -TERM -P "$pass_pid" 2>/dev/null; kill -TERM "$pass_pid" 2>/dev/null
        sleep 20; pkill -KILL -P "$pass_pid" 2>/dev/null; kill -KILL "$pass_pid" 2>/dev/null
        break
      fi
    done
  ) &
  watchdog=$!
  wait "$pass_pid"; rc=$?
  kill "$watchdog" 2>/dev/null; wait "$watchdog" 2>/dev/null
  echo "$(date '+%F %T') LOOP: iteration exit rc=${rc}" >> "$LOG"
  # rc 124 = timed out (expected: token-refresh restart). rc 0 = compose processed the whole
  # cell list (all compositable cells done) -> finished.
  # rc 0 means compose walked the whole cell list. A pass the watchdog killed exits
  # non-zero, so it is retried like any other interrupted pass.
  [ "$rc" -eq 0 ] && { echo "$(date '+%F %T') LOOP: compose exited cleanly, done" >> "$LOG"; break; }
  sleep 15   # guard against a tight loop if compose fails instantly
done
echo "$(date '+%F %T') LOOP: wrapper exiting" >> "$LOG"
