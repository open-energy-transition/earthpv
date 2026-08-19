#!/usr/bin/env bash
# Auto-restarting compose loop for the intermediate-year epochs (indices 2..4,
# pakistan) -- the annual growth series (docs/open-questions.md item 14).
#
# Epoch layout after this completes (all on composite_0's base grid):
#   composite_0  2025-11-01..2026-03-15  current (already built)
#   composite_1  2021-10-01..2022-01-24  pre-boom (already built)
#   composite_2  2022-11-01..2023-03-15
#   composite_3  2023-11-01..2024-03-15
#   composite_4  2024-11-01..2025-03-15
# Indices 2..4 use composite_0's Nov..Mar dry-season window so 4 of the 5 epochs
# share one season definition; composite_1's shorter Oct..Jan window predates that
# convention and is kept as-is (rebuilding it would orphan every published number).
#
# Same token-expiry problem as compose_loop.sh / compose_loop_preboom.sh: PC SAS
# tokens outlive under a slow-network read backlog after ~30-45 min, so each epoch
# runs in fresh 30-min processes until its target count is reached or progress
# stalls. Epochs run SEQUENTIALLY (network-bound: parallel epochs would split the
# same bandwidth, and 3x4 workers is the RSS regime that OOMed 2026-07-19).
#
# Expect ~6 days per epoch (~2 min/cell x ~4,470 cells), ~18 days total. Composites
# land on the big root disk via the data/composites/pakistan symlink
# (-> /home/tobi/earthpv_composites/pakistan since 2026-08-19; the aidisc/aidata
# drives were both full).
#
# Run detached:
#   systemd-run --user --unit=earthpv-compose-years \
#     --working-directory="$PWD" bash scripts/compose_loop_years.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
[ -x "$PY" ] || PY=python
AOI=pakistan
LOG=data/compose_years.log
TARGET=4473        # composite_0 cell count; composite_1 topped out at 4467, so a
                   # few-cell shortfall ends via the stall exit, not a hang
ITER=1800          # 30 min per fresh process, comfortably under the token lifetime
COMPDIR="data/composites/$AOI/composites"

declare -A WINDOWS=(
  [2]="2022-11-01:2023-03-15"
  [3]="2023-11-01:2024-03-15"
  [4]="2024-11-01:2025-03-15"
)

echo "$(date '+%F %T') === LOOP START: intermediate-year compose (indices 2..4) ===" >> "$LOG"
for idx in 2 3 4; do
  win=${WINDOWS[$idx]}
  prev=-1; stall=0
  echo "$(date '+%F %T') EPOCH $idx ($win): starting" >> "$LOG"
  while true; do
    done_n=$(find "$COMPDIR" -name "composite_${idx}.tif" 2>/dev/null | wc -l)
    echo "$(date '+%F %T') EPOCH $idx: ${done_n}/${TARGET} done (stall=${stall})" >> "$LOG"
    [ "$done_n" -ge "$TARGET" ] && { echo "$(date '+%F %T') EPOCH $idx: target reached" >> "$LOG"; break; }
    if [ "$done_n" -le "$prev" ]; then stall=$((stall+1)); else stall=0; fi
    # Stall threshold 6 (vs the preboom loop's 3): a 30-min iteration that spends
    # its whole budget on one slow-network cell shows zero progress without being
    # dead, and at 6 days per epoch a premature exit costs more than three extra
    # idle iterations.
    [ "$stall" -ge 6 ] && { echo "$(date '+%F %T') EPOCH $idx: no progress 6x at ${done_n}, moving on" >> "$LOG"; break; }
    prev=$done_n
    timeout -k 60 "$ITER" $PY -m earthpv.cli compose --aoi "$AOI" --min-buildings 1000 --use-vida \
      --workers 4 --index "$idx" --window "$win" >> "$LOG" 2>&1
    rc=$?
    echo "$(date '+%F %T') EPOCH $idx: iteration exit rc=${rc}" >> "$LOG"
    [ "$rc" -eq 0 ] && { echo "$(date '+%F %T') EPOCH $idx: compose exited cleanly" >> "$LOG"; break; }
    sleep 15
  done
done
echo "$(date '+%F %T') === LOOP DONE: all intermediate-year epochs attempted ===" >> "$LOG"
