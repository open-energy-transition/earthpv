#!/usr/bin/env bash
# Nigeria: everything downstream of `compose`, behind marker files so a killed run
# resumes where it stopped rather than redoing hours of work. Modelled directly on
# scripts/run_zambia_pipeline.sh -- Nigeria is in the same starting condition (no local
# imagery cache, no calibration quadrat, no national register).
#
# `compose` itself is NOT here -- it runs as its own long-lived unit
# (earthpv-compose-nigeria, scripts/compose_loop.sh) and is bandwidth-bound on this
# machine, so it is the only stage measured in days. This script waits for that unit to
# go inactive, then runs the segmentation half of the main workflow end to end and
# writes the evidence atlas.
#
# Nigeria has NO calibration quadrats, so there is deliberately no roofclf half and no
# --sub400-*/--ge400-roof-cells flag: `earthpv atlas --osm-solar` alone is the
# segmentation-only evidence atlas, which is still this workflow's output for a country
# in that state (docs/reproduce.md step 15).
#
#   systemd-run --user --collect --unit=earthpv-nigeria-pipeline \
#     -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 \
#     bash scripts/run_nigeria_pipeline.sh <checkpoint>
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
AOI=nigeria
CKPT=${1:?usage: run_nigeria_pipeline.sh <checkpoint.ckpt>}
LABELS=data/labels/${AOI}_overpass_solar.parquet
OSM=data/labels/${AOI}_national_osm_solar.parquet
MARK=data/nigeria_pipeline_markers
LOG=data/nigeria_pipeline.log
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
while systemctl --user is-active --quiet earthpv-compose-nigeria; do
  say "waiting for compose ($(find data/composites/$AOI/composites -name composite_0.tif 2>/dev/null | wc -l) cells)"
  sleep 300
done
say "compose finished: $(find data/composites/$AOI/composites -name composite_0.tif 2>/dev/null | wc -l) cells"

# ---- segmentation half of the main workflow ------------------------------------------
step infer        $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$CKPT"
# NO --max-building-dist. The new-region runbook suggests 30 m, but that is the LEADS
# recipe: it drops every candidate farther than 30 m from a building. Nigeria's utility
# scale PV (Katsina, Kano, the northern mini-grid build-out) sits in farmland and scrub,
# and Pakistan's own published capacity run does not use it either. Filtering here would
# gut the ground half of the atlas to suppress a false-positive mode that
# `capacity_calibration` prices instead.
step postprocess  $PY -m earthpv.cli postprocess --aoi $AOI --threshold 0.3
step export       $PY -m earthpv.cli export --aoi $AOI --exclude-mapped --min-distance-m 100

# Rank the large OSM `power=plant` perimeters by how much of each the model actually
# lights up. Zambia's run found eight such perimeters (11.7 km2, 583 MWp at the land
# constant) that are announced-but-unbuilt project sites, and they feed the Verified tier
# directly. This step only WRITES THE TABLE AND THE RGB CROPS; it changes nothing. The
# exclusion list is hand-audited against the imagery, and a screen is only a ranking of
# what to look at. Read the CSV and the PNGs, then write
# configs/nigeria_osm_ground_exclusions.txt and re-run the last two steps.
#
# --min-area-m2 30000, NOT the 200,000 default. Nigeria's mapped population is a
# different shape from Zambia's: measured on the 2026-09-15 pull, its largest polygon is
# 0.220 km2 against Zambia's sixteen at 0.3-2.8 km2, so the default threshold screens
# exactly ONE feature and the step is effectively a no-op. 30,000 m2 catches 11 features
# holding 62.7% of all mapped area (47.1 MWp at the land constant), which is the
# concentration that makes the check worth running at all -- the 5 largest polygons alone
# are 46.1% of the country's mapped area.
step screen       $PY scripts/screen_osm_ground_perimeters.py --aoi $AOI \
                     --labels "$LABELS" \
                     --prob-dir data/predictions/$AOI/prob \
                     --min-area-m2 30000 \
                     --out results/nigeria_osm_ground_screen/screen_full.csv \
                     --png-dir results/nigeria_osm_ground_screen

# `--recall-reference none`: Nigeria has no Rule-1 quadrat and no register, and its OSM
# solar reference is thin and dominated by large `power=plant` perimeters that may be
# site or project boundaries rather than arrays. Measuring recall against that would turn
# "this polygon holds no panels" into "the model missed an installation" and inflate every
# capacity figure through 1/recall, up to the 20x DEFAULT_RECALL_FLOOR clamp. France and
# Zambia made the same call for the same reason; the result is a precision-honest floor,
# not a recall-corrected estimate.
step calibrate    $PY -m earthpv.cli calibrate-candidates --aoi $AOI --recall-reference none
step density      $PY -m earthpv.cli density --aoi $AOI --districts
step check_density $PY -m earthpv.cli check-density --aoi $AOI

# --labels pins this to Nigeria's own pull. Without it the script pools every
# data/labels/*_overpass_solar.parquet in the repo (Pakistan, Germany, France, Zambia).
step osm_solar    $PY scripts/prepare_national_osm_solar.py --aoi $AOI --labels "$LABELS"
step atlas        $PY -m earthpv.cli atlas --aoi $AOI --osm-solar "$OSM" \
                     --imagery-date-range "Nov 2025 - Mar 2026" \
                     --out results/nigeria_pv_evidence_atlas.html

# ---- checkpoint comparison (diagnostic, NOT the published product) -------------------
# Deliberately placed AFTER the atlas: the atlas is the deliverable and runs on v4, so a
# failure in this experiment cannot cost the run. v4 is the standing zero-shot checkpoint
# for a country with no local training data (Zambia and Germany both use it); v5 adds
# 17,059 French chips and is documented as FRANCE ONLY. The open question is whether v5's
# larger corpus transfers to a third country or whether its French tuning -- median
# candidate area 8,301 -> 1,400 m2, rooftop share 26.9% -> 50.3% -- is specific to a fleet
# whose median installation is 20 m2 against a 100 m2 pixel. Nigeria's mapped population
# is 89% ground-mount by area, so it is a genuinely different regime from either.
#
# The honest limit: 249 mapped features >= 400 m2, of which only those actually imaged
# count. That is enough to detect a large difference and nowhere near enough to certify a
# small one, which is why the script reports Wilson intervals and McNemar rather than two
# bare recall numbers.
V5_CKPT=data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt
V5_PRED=data/predictions_v5_nigeria
step infer_v5      $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$V5_CKPT" --out-dir "$V5_PRED"
step postprocess_v5 $PY -m earthpv.cli postprocess --aoi $AOI --pred-dir "$V5_PRED" --threshold 0.3
step compare       $PY scripts/compare_checkpoints_vs_mapped.py \
                      --labels "$LABELS" \
                      --model v4_combined_all:data/predictions/$AOI/candidates.parquet:data/predictions/$AOI/prob \
                      --model v5_combined_france:$V5_PRED/$AOI/candidates.parquet:$V5_PRED/$AOI/prob

say "ALL DONE"
