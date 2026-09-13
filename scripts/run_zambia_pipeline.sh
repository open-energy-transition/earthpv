#!/usr/bin/env bash
# Zambia: everything downstream of `compose`, behind marker files so a killed run
# resumes where it stopped rather than redoing hours of work.
#
# `compose` itself is NOT here -- it runs as its own long-lived unit
# (earthpv-compose-zambia, scripts/compose_loop.sh) and is bandwidth-bound at roughly
# 1 cell/min on this machine, so it is the only stage measured in days. This script
# waits for that unit to go inactive, then runs the segmentation half of the main
# workflow end to end and writes the evidence atlas.
#
# Zambia has NO calibration quadrats, so there is deliberately no roofclf half and no
# --sub400-*/--ge400-roof-cells flag: `earthpv atlas --osm-solar` alone is the
# segmentation-only evidence atlas, which is still this workflow's output for a country
# in that state (docs/reproduce.md step 15).
#
#   systemd-run --user --collect --unit=earthpv-zambia-pipeline \
#     -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 \
#     bash scripts/run_zambia_pipeline.sh <checkpoint>
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
AOI=zambia
CKPT=${1:?usage: run_zambia_pipeline.sh <checkpoint.ckpt>}
OSM=data/labels/${AOI}_national_osm_solar.parquet
MARK=data/zambia_pipeline_markers
LOG=data/zambia_pipeline.log
mkdir -p "$MARK"

say() { echo "$(date '+%F %T') PIPELINE: $*" | tee -a "$LOG"; }

step() {  # step <marker> <command...>
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  # check-density exits 1 when a region fails its plausibility check. That is a finding
  # to record and read, not a reason to abandon the run -- this project has a standing
  # precedent for publishing a checked-genuine failure (CLAUDE.md, "Plausibility gate").
  if [ $rc -ne 0 ] && [ "$(basename "$m")" != "check_density" ]; then
    say "FAILED $(basename "$m") rc=$rc"; exit $rc
  fi
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}

# ---- wait for compose ---------------------------------------------------------------
while systemctl --user is-active --quiet earthpv-compose-zambia; do
  say "waiting for compose ($(find data/composites/$AOI/composites -name composite_0.tif | wc -l) cells)"
  sleep 300
done
say "compose finished: $(find data/composites/$AOI/composites -name composite_0.tif | wc -l) cells"

# ---- segmentation half of the main workflow ------------------------------------------
step infer        $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$CKPT"
# NO --max-building-dist. The new-region runbook suggests 30 m, but that is the LEADS
# recipe: it drops every candidate farther than 30 m from a building, and Zambia's real PV
# is utility-scale ground-mount in farmland and bush (Chisamba, Itimpi, the Lusaka South
# MFEZ parks). Pakistan's own published capacity run does not use it either. Filtering here
# would gut the ground half of the atlas to suppress a false-positive mode that
# `capacity_calibration` prices instead.
step postprocess  $PY -m earthpv.cli postprocess --aoi $AOI --threshold 0.3
step export       $PY -m earthpv.cli export --aoi $AOI --exclude-mapped --min-distance-m 100

# Re-screen the large OSM `power=plant` perimeters now that every cell is composited and
# inferred. Three of them (7.07 km2, 353.6 MWp at the land constant) could not be judged on
# 2026-09-13 because their cells had not been composited yet -- this writes the full table
# so those verdicts can finally be taken. It does NOT change the exclusion list: that is
# hand-audited against the imagery (configs/zambia_osm_ground_exclusions.txt), and a screen
# is only a ranking of what to look at. Read the CSV and the PNGs, then extend the list and
# re-run `prepare_national_osm_solar.py --labels` + `atlas` if anything new is confirmed empty.
step screen       $PY scripts/screen_osm_ground_perimeters.py --aoi $AOI \
                     --labels data/labels/${AOI}_overpass_solar.parquet \
                     --prob-dir data/predictions/$AOI/prob \
                     --out results/zambia_osm_ground_screen/screen_full.csv \
                     --png-dir results/zambia_osm_ground_screen

# `--recall-reference none`: Zambia has no Rule-1 quadrat and no register, and its OSM
# reference is dominated by 1-3 km2 `power=plant` perimeters that may be site or project
# boundaries rather than arrays. Measuring recall against that would turn "this polygon
# holds no panels" into "the model missed an installation" and inflate every capacity
# figure through 1/recall, up to the 20x DEFAULT_RECALL_FLOOR clamp. France made the same
# call for the same reason; the result is a precision-honest floor, not an estimate.
step calibrate    $PY -m earthpv.cli calibrate-candidates --aoi $AOI --recall-reference none
step density      $PY -m earthpv.cli density --aoi $AOI --districts
step check_density $PY -m earthpv.cli check-density --aoi $AOI
step atlas        $PY -m earthpv.cli atlas --aoi $AOI --osm-solar "$OSM" \
                     --imagery-date-range "May - Oct 2025" \
                     --out results/zambia_pv_evidence_atlas.html

say "ALL DONE"
