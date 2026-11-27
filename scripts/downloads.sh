#!/usr/bin/env bash
# Pause and resume EarthPV's downloads without touching training or any other compute.
#
#   pixi run pause-downloads     # freeze every running download unit
#   pixi run resume-downloads    # thaw them
#   pixi run downloads-status    # each download unit, frozen or not, and compose progress
#
# A download is a systemd user unit whose name matches PATTERNS: Sentinel-2 compose, the
# country queues (they start label pulls and the next compose round), OSM label pulls, VIDA,
# Geofabrik and other fetches. Units are matched by name, so the next country's compose unit
# is covered without naming it. Pausing uses systemd's cgroup freezer (`systemctl --user
# freeze|thaw`): processes stop where they are and continue from there; nothing is killed.
#
# - A unit with a process on the GPU or running `earthpv.cli train|infer|evaluate` is never
#   frozen: a frozen trainer was killed by systemd-oomd on 2026-11-08 and its unit could
#   neither thaw nor restart. Training is stopped cleanly and resumed from last.ckpt instead.
# - A compose pass runs under `timeout 3600`, whose clock keeps running while frozen. After a
#   pause of more than an hour the pass exits on thaw (rc=124) and compose_loop.sh starts a
#   fresh one with a new Planetary Computer token; finished cells are kept.
# - systemd-oomd can still kill a frozen unit under memory pressure. A killed unit has to be
#   relaunched (compose resumes where it stopped).
set -euo pipefail
cd "$(dirname "$0")/.."

PATTERNS=(
  'earthpv-compose-*'      # Sentinel-2 composites (compose_loop.sh)
  'earthpv-*queue*'        # country queues: label pulls, thermal scans, compose rounds
  'earthpv-*-labels*'      # OSM solar label pulls (Overpass, Geofabrik extracts)
  'earthpv-*-vida'         # VIDA building footprints
  'earthpv-geofabrik-*'    # Geofabrik extracts
  'earthpv-*-fetch*'       # other fetches (time series, grid load, labels)
  'earthpv-*-dl' 'earthpv-*-dl[0-9]*'
)
STATE=data/.downloads_paused

units() {  # matching service units; extra args are list-units filters
  systemctl --user list-units --no-legend --plain --type=service "$@" "${PATTERNS[@]}" \
    | awk '{print $1}'
}

freezer() { systemctl --user show -p FreezerState --value "$1"; }

gpu_reason() {  # prints why a unit must not be frozen; fails if it may be
  local cg pids pid cmd gpu
  cg=$(systemctl --user show -p ControlGroup --value "$1")
  [ -n "$cg" ] && [ -d "/sys/fs/cgroup$cg" ] || return 1
  pids=$(find "/sys/fs/cgroup$cg" -name cgroup.procs -exec cat {} + 2>/dev/null || true)
  gpu=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -d ' ' || true)
  for pid in $pids; do
    if grep -qx "$pid" <<<"$gpu"; then echo "pid $pid is on the GPU"; return 0; fi
    cmd=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)
    if [[ $cmd =~ earthpv\.cli\ (train|infer|evaluate) ]]; then
      echo "pid $pid runs ${BASH_REMATCH[0]#earthpv.cli }"; return 0
    fi
  done
  return 1
}

pause() {
  local u reason n=0
  for u in $(units --state=active); do
    [ "$(freezer "$u")" = running ] || { echo "already paused  $u"; continue; }
    if reason=$(gpu_reason "$u"); then echo "skipped  $u ($reason)"; continue; fi
    systemctl --user freeze "$u"
    [ -f "$STATE" ] || date '+%F %T' >"$STATE"
    echo "$u" >>"$STATE"
    echo "paused   $u"; n=$((n + 1))
  done
  [ "$n" -gt 0 ] || echo "no running download unit to pause"
}

resume() {
  local u n=0
  for u in $(units --state=active); do
    [ "$(freezer "$u")" = running ] && continue
    systemctl --user thaw "$u"
    echo "resumed  $u"; n=$((n + 1))
  done
  rm -f "$STATE"
  [ "$n" -gt 0 ] || echo "no paused download unit"
}

status() {
  local u aoi log progress list
  [ -f "$STATE" ] && echo "paused with pause-downloads since $(head -1 "$STATE")"
  list=$(units --state=active)
  [ -n "$list" ] || { echo "no download unit is running"; return 0; }
  for u in $list; do
    progress=""
    if [[ $u == earthpv-compose-*.service ]]; then
      aoi=${u#earthpv-compose-}; aoi=${aoi%.service}; log=data/compose_$aoi.log
      [ -f "$log" ] && progress=$(tail -c 4000 "$log" | tr '\r' '\n' \
        | grep -oE '[0-9]+/[0-9]+ \[' | tail -1 | tr -d ' [' || true)
      [ -n "$progress" ] && progress="cells $progress"
    fi
    printf '%-42s %-8s %s\n' "$u" "$(freezer "$u")" "$progress"
  done
}

case "${1:-status}" in
  pause) pause ;;
  resume) resume ;;
  status) status ;;
  *) echo "usage: $0 pause|resume|status" >&2; exit 2 ;;
esac
