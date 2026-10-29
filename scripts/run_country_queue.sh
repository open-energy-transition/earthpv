#!/usr/bin/env bash
# Morocco, Egypt, Yemen, South Africa: the unattended queue behind the 2026-10-10 run
# (Poland added 2026-10-19, Namibia 2026-10-28).
#
# Generalises scripts/run_vn_in_queue.sh from two hard-wired countries to an ordered list.
# This script owns the NETWORK LANE -- label pulls and compose, one country at a time in
# priority order -- and hands each composed country to its own compute unit
# (scripts/run_country_compute.sh, SKIP_DIAGNOSTIC=1), which overlaps the next country's
# compose. GPU steps inside those units serialize on data/.gpu.lock.
#
# Everything here is a tick loop over files and units, so it is safe to kill and relaunch
# at any time; it re-derives its state from disk. Status: bash scripts/country_queue_status.sh
#
#   systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
QMARK=data/country_queue_markers
LOG=data/country_queue.log
mkdir -p "$QMARK"
say() { echo "$(date '+%F %T') QUEUE: $*" | tee -a "$LOG"; }

# aoi | bbox for the Overpass pull | ISO3 | Overpass tile grid. Order = priority.
COUNTRIES="
morocco|-13.2,27.6,-1.0,35.95|MAR|4x3
egypt|24.7,22.0,36.9,31.7|EGY|4x4
yemen|41.8,12.1,54.6,19.0|YEM|4x3
south_africa|16.4,-34.9,32.9,-22.1|ZAF|8x6
poland|14.0,49.0,24.2,54.9|POL|5x4
namibia|11.7,-29.0,25.3,-16.9|NAM|4x4
"
AOIS=$(echo "$COUNTRIES" | awk -F'|' 'NF {print $1}')

# Compose settings exactly as scripts/run_vn_in_queue.sh, which carries the measurements
# behind each one (Nigeria livelock post-mortem, the 2026-09-24 dead-connection fix, the
# 2026-09-25 Python-side timeout).
PC_TIMEOUT_S=1800
STALL_S=900
WORKERS=4
MIN_BUILDINGS=1000
GDAL_NET_ENV="--setenv=GDAL_HTTP_TCP_KEEPALIVE=YES --setenv=GDAL_HTTP_TCP_KEEPIDLE=60 \
  --setenv=GDAL_HTTP_TCP_KEEPINTVL=30 --setenv=GDAL_HTTP_LOW_SPEED_TIME=60 \
  --setenv=GDAL_HTTP_LOW_SPEED_LIMIT=1 --setenv=GDAL_HTTP_CONNECTTIMEOUT=30 \
  --setenv=GDAL_HTTP_MAX_RETRY=5 --setenv=GDAL_HTTP_RETRY_DELAY=5 \
  --setenv=EARTHPV_NET_TIMEOUT_S=120 --setenv=EARTHPV_FORCE_IPV4=1"
COVERAGE_MIN=97
MAX_UNPRODUCTIVE=6
ROUND_PROGRESS_MIN=10
ROUND_WAIT=3600
DISK_MIN_HOME_GB=120
DISK_MIN_AIDISC_GB=6
COMPUTE_MAX_FAILS=3
MAX_COMPUTE_UNITS=2      # two chains may overlap (one training, one on CPU); RAM is 30 GB

unit_active() { systemctl --user is-active --quiet "$1"; }
built() { find -L "data/composites/$1/composites" -name composite_0.tif 2>/dev/null | wc -l; }
selected() { grep -aoE "Selected [0-9]+ cells" "data/compose_$1.log" 2>/dev/null | tail -1 | grep -oE "[0-9]+"; }
free_gb() { df -BG --output=avail "$1" | tail -1 | tr -dc 0-9; }
field() { echo "$COUNTRIES" | awk -F'|' -v a="$1" -v k="$2" '$1 == a {print $k}'; }
vida_ok() { local f="data/vida/$(field "$1" 3).parquet"; [ -s "$f" ] && [ ! -e "$(readlink -f "$f").part" ]; }
labels_ok() { [ -s "data/labels/$1_overpass_solar.parquet" ]; }
compose_active() {
  systemctl --user list-units --type=service --state=active --no-legend 'earthpv-compose-*' 2>/dev/null | grep -q .
}
n_compute_active() {
  systemctl --user list-units --type=service --state=active --no-legend 'earthpv-*-compute.service' 2>/dev/null | wc -l
}
val_empty() {
  $PY -c "
from earthpv.config import Settings
import sys; sys.exit(0 if not Settings.load().aois['$1'].get('val_tiles') else 1)"
}

launch_labels() {  # full pull (placement needs the VIDA file); cached tiles are reused
  local aoi=$1 n last
  unit_active "earthpv-$aoi-labels" && return 0
  # The fetch-only pass for all four runs as its own unit (scripts/pull_labels_mena_za.sh);
  # never race it on THIS country's tile cache. Once it has logged this country's return
  # code every tile is cached, and the full pull makes no Overpass requests at all.
  if unit_active earthpv-labels-mena-za && \
     ! grep -q "LABELS\[$aoi\] rc=0" data/labels_mena_za.log 2>/dev/null; then return 0; fi
  n=$(cat "$QMARK/${aoi}_labels_launches" 2>/dev/null || echo 0)
  last=$(stat -c %Y "$QMARK/${aoi}_labels_launches" 2>/dev/null || echo 0)
  [ $(( $(date +%s) - last )) -lt 1800 ] && return 0
  [ "$n" -ge 4 ] && return 0
  echo $((n + 1)) > "$QMARK/${aoi}_labels_launches"
  say "launching $aoi labels pull (attempt $((n + 1)))"
  systemd-run --user --collect --unit="earthpv-$aoi-labels" -p WorkingDirectory="$PWD" \
    -p MemoryMax=10G bash -c "$PY scripts/overpass_labels_chunked.py --bbox=$(field "$aoi" 2) \
      --iso3 $(field "$aoi" 3) --name $aoi --tiles $(field "$aoi" 4) --timeout 300 --retries 8 \
      >> data/${aoi}_labels.log 2>&1" >/dev/null
}

start_compose() {
  local aoi=$1
  say "compose round for $aoi starting at $(built "$aoi") cells"
  echo "$(built "$aoi")" > "$QMARK/${aoi}_round_start"
  find -L "data/composites/$aoi/composites" -name '*.tif.tmp' -delete 2>/dev/null
  systemd-run --user --collect --unit="earthpv-compose-$aoi" -p WorkingDirectory="$PWD" \
    -p LimitNOFILE=65536:65536 -p MemoryMax=12G \
    --setenv=EARTHPV_PC_TIMEOUT_S=$PC_TIMEOUT_S --setenv=EARTHPV_REQUIRE_BOUNDARY=1 \
    $GDAL_NET_ENV \
    bash scripts/compose_loop.sh "$aoi" 0 $MIN_BUILDINGS $WORKERS 3600 $STALL_S \
      "--resampling nearest" >/dev/null
}

finish_round() {  # book-keeping after a compose unit exits (as run_vn_in_queue.sh)
  local aoi=$1 sel got pct start gained unprod
  [ -f "$QMARK/${aoi}_round_start" ] || return 0
  sel=$(selected "$aoi"); got=$(built "$aoi")
  start=$(cat "$QMARK/${aoi}_round_start"); rm -f "$QMARK/${aoi}_round_start"
  gained=$((got - start))
  if [ -z "$sel" ] || [ "$sel" -eq 0 ]; then
    say "WARNING: $aoi compose never logged a cell selection (see data/compose_$aoi.log)"; return 0
  fi
  pct=$((100 * got / sel))
  say "$aoi compose round done: $got/$sel cells (${pct}%), +$gained"
  if [ "$pct" -ge "$COVERAGE_MIN" ]; then
    echo "$got/$sel (${pct}%)" > "$QMARK/${aoi}_compose_done"
    say "$aoi COMPOSE DONE: $got/$sel (${pct}%)"; return 0
  fi
  unprod=$(cat "$QMARK/${aoi}_unproductive" 2>/dev/null || echo 0)
  if [ "$gained" -lt "$ROUND_PROGRESS_MIN" ]; then unprod=$((unprod + 1)); else unprod=0; fi
  echo "$unprod" > "$QMARK/${aoi}_unproductive"
  if [ "$unprod" -ge "$MAX_UNPRODUCTIVE" ]; then
    echo "$got/$sel (${pct}%) SHORTFALL after $unprod unproductive rounds" > "$QMARK/${aoi}_compose_done"
    say "$aoi COMPOSE ACCEPTED WITH SHORTFALL: $got/$sel (${pct}%)"
  elif [ "$gained" -lt "$ROUND_PROGRESS_MIN" ]; then
    touch "$QMARK/${aoi}_cooldown"; say "$aoi round unproductive ($unprod/$MAX_UNPRODUCTIVE); cooling down ${ROUND_WAIT}s"
  fi
}

maybe_compute() {
  local aoi=$1 fails
  [ -f "$QMARK/${aoi}_compose_done" ] || return 0
  [ -f "$QMARK/${aoi}_atlas_done" ] && return 0
  [ -f "$QMARK/${aoi}_thermal_checked" ] || return 0
  unit_active "earthpv-$aoi-compute" && return 0
  if grep -q "ATLAS DONE" "data/${aoi}_pipeline.log" 2>/dev/null; then
    touch "$QMARK/${aoi}_atlas_done"; say "$aoi atlas finished"; return 0
  fi
  [ "$(n_compute_active)" -ge "$MAX_COMPUTE_UNITS" ] && return 0
  fails=$(cat "$QMARK/${aoi}_compute_launches" 2>/dev/null || echo 0)
  if [ "$fails" -ge "$COMPUTE_MAX_FAILS" ]; then
    [ -f "$QMARK/${aoi}_needs_attention" ] || { touch "$QMARK/${aoi}_needs_attention"; \
      say "NEEDS ATTENTION: $aoi compute unit launched $fails times without an atlas; see data/${aoi}_pipeline.log"; }
    return 0
  fi
  if val_empty "$aoi"; then
    say "$aoi has no val_tiles: choosing the holdout from the label map (scripts/pick_val_region.py)"
    if ! $PY scripts/pick_val_region.py --aoi "$aoi" --write >> "$LOG" 2>&1; then
      say "NEEDS ATTENTION: $aoi holdout could not be chosen automatically"
      touch "$QMARK/${aoi}_needs_attention"; return 0
    fi
  fi
  echo $((fails + 1)) > "$QMARK/${aoi}_compute_launches"
  say "launching $aoi compute chain (launch $((fails + 1))/$COMPUTE_MAX_FAILS)"
  systemd-run --user --collect --unit="earthpv-$aoi-compute" -p WorkingDirectory="$PWD" \
    -p LimitNOFILE=65536:65536 -p MemoryMax=14G \
    --setenv=QMARK=$QMARK --setenv=SKIP_DIAGNOSTIC=1 \
    bash scripts/run_country_compute.sh "$aoi" >/dev/null
}

say "queue start (pid $$): $(echo $AOIS)"
while true; do
  # ---- labels: full pull per country once its VIDA file has landed ------------------------
  for a in $AOIS; do
    labels_ok "$a" || { vida_ok "$a" && launch_labels "$a"; }
  done
  # ...then drop solar-thermal (CSP, water heaters) once, before anything trains on them.
  # Morocco 2026-10-10: 1,697 of 3,440 features, 20.2 km2, were Noor Ouarzazate 1-3 CSP.
  for a in $AOIS; do
    if labels_ok "$a" && [ ! -f "$QMARK/${a}_thermal_checked" ] && ! unit_active "earthpv-$a-labels"; then
      if $PY scripts/drop_solar_thermal.py --aoi "$a" >> "$LOG" 2>&1; then
        touch "$QMARK/${a}_thermal_checked"; say "$a solar-thermal check done"
      else say "$a solar-thermal check failed (Overpass?); retried next tick"; fi
    fi
  done

  # ---- disk guard -----------------------------------------------------------------------
  hf=$(free_gb /); af=$(free_gb /run/media/tobi/aidisc)
  if [ "$hf" -lt "$DISK_MIN_HOME_GB" ] || [ "$af" -lt "$DISK_MIN_AIDISC_GB" ]; then
    say "DISK GUARD: / ${hf}G free, aidisc ${af}G free -- stopping compose until space returns"
    for a in $AOIS; do unit_active "earthpv-compose-$a" && systemctl --user stop "earthpv-compose-$a"; done
    sleep 1800; continue
  fi

  # ---- network lane: one compose at a time, first ready country in priority order -------
  for a in $AOIS; do unit_active "earthpv-compose-$a" || finish_round "$a"; done
  if ! compose_active; then
    for a in $AOIS; do
      [ -f "$QMARK/${a}_compose_done" ] && continue
      vida_ok "$a" && labels_ok "$a" || continue
      cd_file="$QMARK/${a}_cooldown"
      if [ -f "$cd_file" ] && [ $(( $(date +%s) - $(stat -c %Y "$cd_file") )) -lt $ROUND_WAIT ]; then
        continue   # cooling down after an unproductive round; let the next country use the link
      fi
      rm -f "$cd_file"; start_compose "$a"; break
    done
  fi

  # ---- compute lanes ----------------------------------------------------------------------
  for a in $AOIS; do maybe_compute "$a"; done

  all=1; for a in $AOIS; do [ -f "$QMARK/${a}_atlas_done" ] || all=0; done
  if [ "$all" = 1 ]; then say "every country has its atlas; queue exiting"; break; fi
  sleep 300
done
