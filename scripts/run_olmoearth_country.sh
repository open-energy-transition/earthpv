#!/usr/bin/env bash
# OlmoEarth v1.3 against segmentation in a second country (2026-10-25): the comparison, then
# the blind review sheets. Behind markers, so a killed run resumes from its chunk cache.
#
#   systemd-run --user --collect --unit=earthpv-olmoearth-za -p WorkingDirectory="$PWD" \
#     -p MemoryMax=14G --setenv=OMP_NUM_THREADS=3 bash scripts/run_olmoearth_country.sh south_africa
set -uo pipefail
AOI=${1:?usage: run_olmoearth_country.sh <aoi>}
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MARK=data/olmoearth_${AOI}_markers
LOG=data/olmoearth_${AOI}.log
mkdir -p "$MARK"
export PYTHONUNBUFFERED=1
say() { echo "$(date '+%F %T') OLMO $AOI: $*" | tee -a "$LOG"; }
step() {
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1 || { local rc=$?; say "FAILED $(basename "$m") rc=$rc"; exit 1; }
  say "done $(basename "$m")"; touch "$m"
}
step compare $PY scripts/olmoearth_vs_segmentation_country.py --aoi "$AOI"
step review  $PY scripts/olmoearth_vs_segmentation_country.py --aoi "$AOI" --review
say "ALL DONE"
