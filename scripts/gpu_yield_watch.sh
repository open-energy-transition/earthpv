#!/usr/bin/env bash
# Let a country's GPU step pre-empt India's v10 whole-country diagnostic (2026-10-11).
#
# The diagnostic (`run_country_compute.sh india`, step infer_other) holds data/.gpu.lock for
# ~19 h, and a country chain launched by run_country_queue.sh would wait behind it in
# `flock` silently for that long. Every 5 min this:
#   - stops earthpv-india-compute when its infer is running AND a country compute unit has
#     a `flock` on the GPU lock with no child yet (i.e. blocked waiting for it), and leaves
#     data/vn_in_queue_markers/india_diag_paused;
#   - relaunches it when that marker exists, the India unit is down, the diagnostic is not
#     finished, and every active country compute unit is past its GPU phase (its `infer`
#     marker exists) or none is active.
# Infer writes each cell to .tmp and renames, and skips finished cells, so a stop costs
# one partly read cell and a model load.
#
#   systemd-run --user --collect --unit=earthpv-gpu-yield -p WorkingDirectory="$PWD" \
#     -p MemoryMax=512M bash scripts/gpu_yield_watch.sh
set -u
cd "$(dirname "$0")/.."
LOG=data/country_queue.log
PAUSED=data/vn_in_queue_markers/india_diag_paused
INDIA=earthpv-india-compute
say() { echo "$(date '+%F %T') GPU-YIELD: $*" >> "$LOG"; }

procs_of() {  # pids in a user unit's cgroup
  local cg; cg=$(systemctl --user show "$1" -p ControlGroup --value 2>/dev/null)
  [ -n "$cg" ] && cat "/sys/fs/cgroup$cg/cgroup.procs" 2>/dev/null
  # also nested cgroups
  [ -n "$cg" ] && find "/sys/fs/cgroup$cg" -mindepth 2 -name cgroup.procs -exec cat {} + 2>/dev/null
}

country_units() {
  systemctl --user list-units 'earthpv-*-compute.service' --state=active --no-legend --plain \
    | awk '{print $1}' | sed 's/\.service$//' | grep -v "^$INDIA\$"
}

waiting_unit() {  # first country unit with a flock that has not started its command
  local u p
  for u in $(country_units); do
    for p in $(procs_of "$u"); do
      [ "$(cat /proc/$p/comm 2>/dev/null)" = flock ] || continue
      grep -q gpu.lock /proc/$p/cmdline 2>/dev/null || continue
      [ -z "$(pgrep -P "$p")" ] && { echo "$u"; return; }
    done
  done
}

india_inferring() {
  local p
  for p in $(procs_of "$INDIA"); do
    tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -q 'earthpv.cli infer' && return 0
  done
  return 1
}

countries_past_gpu() {
  local u aoi
  for u in $(country_units); do
    aoi=${u#earthpv-}; aoi=${aoi%-compute}
    [ -f "data/${aoi}_pipeline_markers/infer" ] || return 1
  done
  return 0
}

say "watch started"
while :; do
  if systemctl --user is-active --quiet "$INDIA"; then
    w=$(waiting_unit)
    if [ -n "$w" ] && india_inferring; then
      say "$w is waiting on the GPU lock; stopping $INDIA (v10 diagnostic, resumes per cell)"
      touch "$PAUSED"
      systemctl --user stop "$INDIA"
    fi
  elif [ -f "$PAUSED" ] && [ ! -f data/india_pipeline_markers/compare ] \
       && [ -z "$(waiting_unit)" ] && countries_past_gpu; then
    say "GPU free of country work; relaunching $INDIA"
    rm -f "$PAUSED"
    systemd-run --user --collect --unit="$INDIA" -p WorkingDirectory="$PWD" \
      -p LimitNOFILE=65536:65536 -p MemoryMax=20G bash scripts/run_country_compute.sh india \
      >> "$LOG" 2>&1 || say "relaunch failed"
  fi
  [ -f data/india_pipeline_markers/compare ] && [ ! -f "$PAUSED" ] && { say "India diagnostic finished; watch exits"; exit 0; }
  sleep 300
done
