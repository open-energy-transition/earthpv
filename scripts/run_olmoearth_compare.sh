#!/usr/bin/env bash
# OlmoEarth v1.3 against AlphaEarth and segmentation (2026-10-24): AlphaEarth re-run on the
# 2023 change baseline OlmoEarth covers, then the OlmoEarth run, which scores both.
# Behind markers, so a killed run resumes; both scripts cache every chunk they download.
#
#   systemd-run --user --collect --unit=earthpv-olmoearth-vs-seg -p WorkingDirectory="$PWD" \
#     -p MemoryMax=14G --setenv=OMP_NUM_THREADS=3 bash scripts/run_olmoearth_compare.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MARK=data/olmoearth_compare_markers
LOG=data/olmoearth_compare.log
mkdir -p "$MARK"
export PYTHONUNBUFFERED=1
say() { echo "$(date '+%F %T') OLMO: $*" | tee -a "$LOG"; }
step() {
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1 || { local rc=$?; say "FAILED $(basename "$m") rc=$rc"; exit 1; }
  say "done $(basename "$m")"; touch "$m"
}
step aef_base2023 $PY scripts/aef_vs_segmentation.py --national-negatives --base-year 2023
step olmoearth    $PY scripts/olmoearth_vs_segmentation.py
say "ALL DONE"
