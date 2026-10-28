#!/usr/bin/env bash
# India's `ring_cells: 3` widening (2026-10-22): everything downstream of compose, re-run so
# the 3,573 added cells reach the evidence atlas. The segmentation half of
# run_country_compute.sh with the same flags, and five differences:
#   - inference stays caught up behind the still-running compose unit, then runs once more;
#   - the published run's outputs are copied to $PRE before anything overwrites them;
#   - postprocess keeps the published building join for every 0.25-deg chunk whose
#     candidates did not change (--reuse-join); the full join was 23 h of it;
#   - density runs --force: candidates.parquet changed, so its cached partials are stale;
#   - the atlas goes to results/india_pv_evidence_atlas_ring.html, not over the published
#     page, so the two can be compared before anything is republished.
# Same checkpoint (v5), labels and window as the published atlas, so the ring is the only
# change. Behind markers in $MARK; a killed run resumes at the step it stopped on.
#
#   systemd-run --user --collect --unit=earthpv-india-ring-chain -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=14G bash scripts/run_india_ring_chain.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
AOI=india
CKPT=data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt
COMPOSE_UNIT=earthpv-compose-$AOI
MARK=data/${AOI}_ring_markers
LOG=data/${AOI}_ring_pipeline.log
PRE=/home/tobi/earthpv_data/${AOI}_PRE_ring_20261024
PRED=data/predictions/$AOI
LABELS=data/labels/${AOI}_overpass_solar.parquet
OSM=data/labels/${AOI}_national_osm_solar.parquet
SCREEN=results/${AOI}_osm_ground_screen
GPU_LOCK=data/.gpu.lock
INFER_EVERY_S=10800
mkdir -p "$MARK"

say() { echo "$(date '+%F %T') RING[$AOI]: $*" | tee -a "$LOG"; }
ncomp() { find -L data/composites/$AOI/composites -name composite_0.tif | wc -l; }
ninf() { find -L $PRED/prob -name '*.tif' | wc -l; }
gpu() { flock "$GPU_LOCK" "$@"; }

step() {  # step <marker> <command...>, as run_country_compute.sh
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  if [ $rc -ne 0 ] && [ "$(basename "$m")" != "check_density" ]; then
    say "FAILED $(basename "$m") rc=$rc"; exit $rc
  fi
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}

# ---- inference behind the compose -------------------------------------------------------
# compose_loop.sh exits on "no progress 3x" as well as on a clean finish, and a stall is
# usually the network, not the end of the work: 2026-10-23 00:39 it stopped at 26,594 of
# 29,171 cells and sat idle for 15.5 h. So a stall exit relaunches the same unit (same
# arguments and environment as the 2026-10-23 16:17 launch) after an hour, at most
# COMPOSE_RELAUNCH_MAX times; only a clean exit, or a stall that survives them, ends the wait.
COMPOSE_RELAUNCH_MAX=3
relaunch_compose() {
  systemd-run --user --collect --unit="$COMPOSE_UNIT" -p WorkingDirectory="$PWD" \
    -p MemoryMax=12G -p LimitNOFILE=65536:65536 \
    --setenv=EARTHPV_PC_TIMEOUT_S=1800 --setenv=EARTHPV_REQUIRE_BOUNDARY=1 \
    --setenv=GDAL_HTTP_TCP_KEEPALIVE=YES --setenv=GDAL_HTTP_TCP_KEEPIDLE=60 \
    --setenv=GDAL_HTTP_TCP_KEEPINTVL=30 --setenv=GDAL_HTTP_LOW_SPEED_TIME=60 \
    --setenv=GDAL_HTTP_LOW_SPEED_LIMIT=1 --setenv=GDAL_HTTP_CONNECTTIMEOUT=30 \
    --setenv=GDAL_HTTP_MAX_RETRY=5 --setenv=GDAL_HTTP_RETRY_DELAY=5 \
    --setenv=EARTHPV_NET_TIMEOUT_S=120 --setenv=EARTHPV_FORCE_IPV4=1 \
    bash scripts/compose_loop.sh $AOI 0 1000 4 3600 900 "--resampling nearest"
}
relaunches=0
while :; do
  while systemctl --user is-active --quiet "$COMPOSE_UNIT"; do
    say "incremental infer ($(ncomp) cells composited, $(ninf) inferred)"
    gpu $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$CKPT" >> "$LOG" 2>&1 \
      || say "incremental infer rc=$? (retried next round)"
    # Sleep in slices, so the end of the compose is noticed within minutes, not hours.
    for _ in $(seq $((INFER_EVERY_S / 300))); do
      systemctl --user is-active --quiet "$COMPOSE_UNIT" || break
      sleep 300
    done
  done
  last=$(grep "LOOP:" data/compose_${AOI}.log | grep -v "wrapper exiting" | tail -1)
  if [[ "$last" == *"no progress"* ]] && [ "$relaunches" -lt "$COMPOSE_RELAUNCH_MAX" ]; then
    relaunches=$((relaunches + 1))
    say "compose stopped on a stall ($last); relaunching in 1 h ($relaunches/$COMPOSE_RELAUNCH_MAX)"
    sleep 3600
    relaunch_compose >> "$LOG" 2>&1 || { say "FAILED compose relaunch"; exit 1; }
    sleep 60
    continue
  fi
  # Neither a clean finish nor a stall (stopped by hand, killed): wait for the unit to come
  # back, or for `touch $MARK/compose_accept` to go on with the cells already composited.
  if [[ "$last" != *"exited cleanly"* && "$last" != *"no progress"* && ! -f "$MARK/compose_accept" ]]; then
    say "compose unit inactive without finishing ($last); waiting for it or for $MARK/compose_accept"
    until systemctl --user is-active --quiet "$COMPOSE_UNIT" || [ -f "$MARK/compose_accept" ]; do
      sleep 600
    done
    continue
  fi
  break
done
say "compose unit finished: $(ncomp) cells composited ($(grep LOOP data/compose_${AOI}.log | tail -2 | head -1))"
step infer gpu $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$CKPT"
say "$(ninf) cells inferred"

# ---- keep the published run -------------------------------------------------------------
if [ ! -f "$MARK/backup" ]; then
  mkdir -p "$PRE/results" "$PRE/configs" "$PRE/labels"
  cp -a $PRED/candidates.parquet $PRED/density "$PRE/" &&
  cp -a $SCREEN/screen_full.csv "$PRE/results/" &&
  cp -a results/${AOI}_pv_evidence_atlas.html results/${AOI}_pv_evidence_atlas_capacity_by_cell.parquet "$PRE/results/" &&
  cp -a configs/calibration/${AOI}_candidate_precision.yaml "$PRE/configs/" &&
  cp -a $OSM "$PRE/labels/" || { say "FAILED backup"; exit 1; }
  say "published run copied to $PRE"; touch "$MARK/backup"
fi

# ---- the segmentation half, as run_country_compute.sh -----------------------------------
step postprocess  $PY -m earthpv.cli postprocess --aoi $AOI --threshold 0.3 --building-buffer-m 500 \
                     --stream-buildings --reuse-join "$PRE/candidates.parquet"
step thermal      $PY scripts/drop_solar_thermal.py --aoi $AOI --candidates
step export       $PY -m earthpv.cli export --aoi $AOI --exclude-mapped --min-distance-m 100
step screen       $PY scripts/screen_osm_ground_perimeters.py --aoi $AOI --labels "$LABELS" \
                     --prob-dir $PRED/prob --min-area-m2 50000 \
                     --out $SCREEN/screen_full.csv --png-dir $SCREEN
step calibrate    $PY -m earthpv.cli calibrate-candidates --aoi $AOI --recall-reference none
step density      $PY -m earthpv.cli density --aoi $AOI --districts --force
step check_density $PY -m earthpv.cli check-density --aoi $AOI
step osm_solar    $PY scripts/prepare_national_osm_solar.py --aoi $AOI --labels "$LABELS" \
                     --keep-detected-screen $SCREEN/screen_full.csv
step atlas        $PY -m earthpv.cli atlas --aoi $AOI --osm-solar "$OSM" --include-offgrid-osm \
                     --imagery-date-range "Nov 2025 - Mar 2026" \
                     --out results/${AOI}_pv_evidence_atlas_ring.html
say "RING ATLAS DONE: results/${AOI}_pv_evidence_atlas_ring.html (published run in $PRE)"
