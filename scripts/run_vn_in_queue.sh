#!/usr/bin/env bash
# Vietnam, then India: the long-running, unattended queue behind the 2026-09-23 run.
#
# The link is the binding constraint (compose is bandwidth-bound, CLAUDE.md), so this
# script owns the NETWORK LANE -- label pulls and compose -- and hands each country's
# GPU/CPU work to its own unit (scripts/run_country_compute.sh), which can overlap the
# other country's compose freely.
#
# Priority: Vietnam first, as the owner asked. India's compose only fills time Vietnam
# cannot use yet (its VIDA file and labels were still downloading at launch), and is
# PREEMPTED the moment Vietnam is ready: compose writes each cell to .tif.tmp and renames
# it atomically, so stopping a pass loses at most the cells in flight.
#
# Everything here is a tick loop over files and units, so it is safe to kill and relaunch
# at any time; it re-derives its state from disk.
#
#   systemd-run --user --collect --unit=earthpv-vn-in-queue -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_vn_in_queue.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
QMARK=data/vn_in_queue_markers
LOG=data/vn_in_queue.log
mkdir -p "$QMARK"
say() { echo "$(date '+%F %T') QUEUE: $*" | tee -a "$LOG"; }

# Compose settings, all from the Nigeria livelock post-mortem (CLAUDE.md): Planetary
# Computer patience several times the contended per-cell wall time, a stall watchdog well
# above a pass's startup cost, 4 workers, 1-hour wall-clock passes.
PC_TIMEOUT_S=600
STALL_S=2400
WORKERS=4
MIN_BUILDINGS=1000
COVERAGE_MIN=97          # percent of selected cells that counts as "compose finished"
MAX_UNPRODUCTIVE=8       # consecutive rounds adding < ROUND_PROGRESS_MIN before accepting
ROUND_PROGRESS_MIN=20    #   a shortfall (the remaining cells then have no usable scenes)
ROUND_WAIT=3600          # pause after an unproductive round, so a provider outage can clear
INDIA_TRAIN_DENSITY_CELLS=3000   # density cells beyond the label cells before India trains
DISK_MIN_HOME_GB=120
DISK_MIN_AIDISC_GB=8
COMPUTE_MAX_FAILS=3      # relaunches of a failed compute unit before waiting for a human

unit_active() { systemctl --user is-active --quiet "$1"; }
built() { find -L "data/composites/$1/composites" -name composite_0.tif 2>/dev/null | wc -l; }
selected() { grep -aoE "Selected [0-9]+ cells" "data/compose_$1.log" 2>/dev/null | tail -1 | grep -oE "[0-9]+"; }
label_cells() { grep -aoE "[0-9]+ contain OSM solar labels" "data/compose_$1.log" 2>/dev/null | tail -1 | grep -oE "^[0-9]+"; }
free_gb() { df -BG --output=avail "$1" | tail -1 | tr -dc 0-9; }
vn_vida() { [ -s data/vida/VNM.parquet ] && [ ! -e /home/tobi/earthpv_data/VNM.parquet.part ]; }
labels_ok() { [ -s "data/labels/$1_overpass_solar.parquet" ]; }
vn_tiles_fetched() { grep -aqE -- "--fetch-only: all|never landed" data/vietnam_labels.log 2>/dev/null; }
foreign_compose() {
  systemctl --user list-units --type=service --state=active --no-legend 'earthpv-compose-*' 2>/dev/null \
    | awk '{print $1}' | grep -vE '^earthpv-compose-(vietnam|india)\.service$'
}

launch_labels() {  # launch_labels <aoi> <bbox> <iso3> <tiles>
  local aoi=$1
  unit_active "earthpv-$aoi-labels" && return 0
  local n; n=$(cat "$QMARK/${aoi}_labels_launches" 2>/dev/null || echo 0)
  local last; last=$(stat -c %Y "$QMARK/${aoi}_labels_launches" 2>/dev/null || echo 0)
  [ $(( $(date +%s) - last )) -lt 1800 ] && return 0   # at most one launch per 30 min
  echo $((n + 1)) > "$QMARK/${aoi}_labels_launches"
  say "launching $aoi labels pull (attempt $((n + 1)); cached tiles are reused)"
  systemd-run --user --collect --unit="earthpv-$aoi-labels" -p WorkingDirectory="$PWD" \
    -p MemoryMax=12G bash -c "$PY scripts/overpass_labels_chunked.py --bbox $2 --iso3 $3 \
      --name $aoi --tiles $4 --timeout 300 --retries 8 >> data/${aoi}_labels.log 2>&1" >/dev/null
}

start_compose() {  # start_compose <aoi>
  local aoi=$1
  say "compose round for $aoi starting at $(built "$aoi") cells"
  echo "$(built "$aoi")" > "$QMARK/${aoi}_round_start"
  find -L "data/composites/$aoi/composites" -name '*.tif.tmp' -delete 2>/dev/null
  systemd-run --user --collect --unit="earthpv-compose-$aoi" -p WorkingDirectory="$PWD" \
    -p LimitNOFILE=65536:65536 -p MemoryMax=12G \
    --setenv=EARTHPV_PC_TIMEOUT_S=$PC_TIMEOUT_S --setenv=EARTHPV_REQUIRE_BOUNDARY=1 \
    bash scripts/compose_loop.sh "$aoi" 0 $MIN_BUILDINGS $WORKERS 3600 $STALL_S \
      "--resampling nearest" >/dev/null
}

finish_round() {  # finish_round <aoi>: book-keeping after a compose unit exits
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
    # A persistent shortfall after this many rounds means the remaining cells have no
    # usable scenes (northern Vietnamese cloud), not an outage. Proceed and RECORD it:
    # the results page states coverage, it does not present a partial country as whole.
    echo "$got/$sel (${pct}%) SHORTFALL after $unprod unproductive rounds" > "$QMARK/${aoi}_compose_done"
    say "$aoi COMPOSE ACCEPTED WITH SHORTFALL: $got/$sel (${pct}%)"
  elif [ "$gained" -lt "$ROUND_PROGRESS_MIN" ]; then
    touch "$QMARK/${aoi}_cooldown"; say "$aoi round unproductive ($unprod/$MAX_UNPRODUCTIVE); cooling down ${ROUND_WAIT}s"
  fi
}

maybe_compute() {  # maybe_compute <aoi> <start marker>
  local aoi=$1 fails
  [ -f "$2" ] || return 0
  [ -f "$QMARK/${aoi}_compute_finished" ] && return 0
  unit_active "earthpv-$aoi-compute" && return 0
  if grep -q "ALL DONE" "data/${aoi}_pipeline.log" 2>/dev/null; then
    touch "$QMARK/${aoi}_compute_finished"; say "$aoi compute chain finished"; return 0
  fi
  fails=$(cat "$QMARK/${aoi}_compute_launches" 2>/dev/null || echo 0)
  if [ "$fails" -ge "$COMPUTE_MAX_FAILS" ]; then
    [ -f "$QMARK/${aoi}_needs_attention" ] || { touch "$QMARK/${aoi}_needs_attention"; \
      say "NEEDS ATTENTION: $aoi compute unit launched $fails times without finishing; see data/${aoi}_pipeline.log"; }
    return 0
  fi
  echo $((fails + 1)) > "$QMARK/${aoi}_compute_launches"
  say "launching $aoi compute chain (launch $((fails + 1))/$COMPUTE_MAX_FAILS)"
  systemd-run --user --collect --unit="earthpv-$aoi-compute" -p WorkingDirectory="$PWD" \
    -p LimitNOFILE=65536:65536 -p MemoryMax=14G \
    bash scripts/run_country_compute.sh "$aoi" >/dev/null
}

say "queue start (pid $$)"
while true; do
  # ---- labels (light on the link; run alongside compose) --------------------------------
  # Vietnam's tiles were fetched ahead of its VIDA file (--fetch-only); the placement half
  # can run as soon as both exist, without waiting for India's pull to finish.
  if ! labels_ok vietnam && vn_vida && { vn_tiles_fetched || ! unit_active earthpv-vn-in-labels; }; then
    launch_labels vietnam 102.1,8.4,109.5,23.4 VNM 3x8
  fi
  if ! labels_ok india && ! unit_active earthpv-vn-in-labels; then
    launch_labels india 68.0,6.7,97.5,37.1 IND 14x14
  fi
  VN_READY=0; vn_vida && labels_ok vietnam && VN_READY=1
  # India's VIDA file is already local, so its compose can use the link while Vietnam's
  # inputs download. Labels are NOT required to start: `populated_cells` recomputes the
  # label cells on every pass and composites them first, so a late labels file is picked
  # up by the next pass (the same argument scripts/run_nigeria_chain.sh makes).
  IN_READY=1

  # ---- milestones -------------------------------------------------------------------------
  if [ ! -f "$QMARK/india_train_ready" ]; then
    lc=$(label_cells india); got=$(built india)
    if [ -f "$QMARK/india_compose_done" ] || { [ -n "$lc" ] && [ "$got" -ge $((lc + INDIA_TRAIN_DENSITY_CELLS)) ]; }; then
      echo "$got cells (label cells ${lc:-?})" > "$QMARK/india_train_ready"
      say "India training milestone reached: $got cells composited (label cells ${lc:-?})"
    fi
  fi

  # ---- disk guard ---------------------------------------------------------------------------
  hf=$(free_gb /); af=$(free_gb /run/media/tobi/aidisc)
  if [ "$hf" -lt "$DISK_MIN_HOME_GB" ] || [ "$af" -lt "$DISK_MIN_AIDISC_GB" ]; then
    say "DISK GUARD: / ${hf}G free, aidisc ${af}G free -- stopping compose until space returns"
    for a in vietnam india; do unit_active "earthpv-compose-$a" && systemctl --user stop "earthpv-compose-$a"; done
    sleep 1800; continue
  fi

  # ---- network lane -------------------------------------------------------------------------
  for a in vietnam india; do
    unit_active "earthpv-compose-$a" || finish_round "$a"
  done
  VN_DONE=0; [ -f "$QMARK/vietnam_compose_done" ] && VN_DONE=1
  IN_DONE=0; [ -f "$QMARK/india_compose_done" ] && IN_DONE=1
  # Preempt India the moment Vietnam can run.
  if [ "$VN_READY" = 1 ] && [ "$VN_DONE" = 0 ] && unit_active earthpv-compose-india; then
    say "Vietnam is ready: preempting India compose at $(built india) cells"
    # Not a round outcome: drop the bookkeeping rather than let a short preempted round
    # count toward the unproductive-round limit.
    systemctl --user stop earthpv-compose-india; sleep 30; rm -f "$QMARK/india_round_start"
  fi
  if ! unit_active earthpv-compose-vietnam && ! unit_active earthpv-compose-india; then
    fc=$(foreign_compose)
    if [ -n "$fc" ]; then
      say "yielding the link to a foreign compose: $fc"
    else
      next=""
      if [ "$VN_READY" = 1 ] && [ "$VN_DONE" = 0 ]; then next=vietnam
      elif [ "$IN_READY" = 1 ] && [ "$IN_DONE" = 0 ]; then next=india
      fi
      if [ -n "$next" ]; then
        cd_file="$QMARK/${next}_cooldown"
        if [ -f "$cd_file" ] && [ $(( $(date +%s) - $(stat -c %Y "$cd_file") )) -lt $ROUND_WAIT ]; then
          :   # cooling down after an unproductive round
        else
          rm -f "$cd_file"; start_compose "$next"
        fi
      fi
    fi
  fi

  # ---- compute lanes ------------------------------------------------------------------------
  maybe_compute vietnam "$QMARK/vietnam_compose_done"
  maybe_compute india "$QMARK/india_train_ready"

  if [ -f "$QMARK/vietnam_compute_finished" ] && [ -f "$QMARK/india_compute_finished" ]; then
    say "both countries finished; queue exiting"; break
  fi
  sleep 300
done
