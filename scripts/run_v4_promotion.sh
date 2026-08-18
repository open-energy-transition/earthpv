#!/usr/bin/env bash
# Promote v4_combined_all (Germany+Punjab+Pakistan+Gujarat combined segmentation
# retrain, 2026-08-14) to production: re-run inference/postprocess/export/density for
# Pakistan and Gujarat with the new checkpoint, into FRESH output dirs (data/
# predictions_v4, data/roofclf_national_with_sppi_v4) so the current published
# artifacts are never touched until the new ones are verified by hand.
#
# roofclf's own scores (p_roofclf/sppi) do NOT depend on the segmentation checkpoint,
# so `roofclf-score-national` is NOT re-run -- sub400-capacity/ge400-roof-capacity read
# the EXISTING data/roofclf_national_with_sppi/pakistan/prob/ scores via --roofclf-dir.
# They DO need re-running regardless, because both dedupe their incremental buildings
# against segmentation's own candidates.parquet (see sub400_capacity.py's module
# docstring, "dedup-vs-segmentation mechanics") -- a new checkpoint can flag a
# different building, changing which sub-400 m2 roofs are "already counted".
#
# Writes verification copies to results/, NOT docs/assets/interactive/ -- promotion
# only touches the published site after these are checked by hand against the current
# numbers (16,608.7 MWp Best, etc.) for a sane before/after, not a silent replacement.
#
# Chains into the fraction-head k-fold retrain afterward (same GPU, sequential, see
# scripts/run_fraction_kfold.sh's own header for why).
set -uo pipefail
cd /run/media/tobi/aidisc/earthpv

CKPT="data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt"
PRED="data/predictions_v4"
ROOFCLF_OUT_PK="data/roofclf_national_with_sppi_v4/pakistan/density"
LOG="data/run_v4_promotion.log"
MLPY=".pixi/envs/ml/bin/python"
PY=".pixi/envs/default/bin/python"

run_stage() {  # name  interpreter  cli-args...
  local name=$1; shift; local py=$1; shift
  echo "$(date -Is) ${name}: starting (${py} -m earthpv.cli $*)" >> "$LOG"
  "$py" -m earthpv.cli "$@" >> "$LOG" 2>&1
  local rc=$?
  echo "$(date -Is) ${name}: exit rc=${rc}" >> "$LOG"
  if [ "$rc" -ne 0 ]; then
    echo "$(date -Is) ${name} FAILED (rc=${rc}) -- aborting promotion, k-fold NOT started" >> "$LOG"
    exit "$rc"
  fi
}

# check-density's exit code is a plausibility SIGNAL, not a pass/fail gate on whether to
# keep going -- the currently-published atlas itself carries 3 checked-genuine failures
# (KP/Balochistan/ICT, see docs/open-questions.md), published anyway per this project's
# own precedent. Report it; never let it abort the pipeline.
run_nonfatal() {
  local name=$1; shift; local py=$1; shift
  echo "$(date -Is) ${name}: starting (${py} -m earthpv.cli $*)" >> "$LOG"
  "$py" -m earthpv.cli "$@" >> "$LOG" 2>&1
  echo "$(date -Is) ${name}: exit rc=$? (non-fatal, see log for which regions/why)" >> "$LOG"
}

echo "$(date -Is) === v4 promotion: Pakistan ===" >> "$LOG"
run_stage PK_INFER         "$MLPY" infer   --aoi pakistan --checkpoint "$CKPT" --out-dir "$PRED"
run_stage PK_POSTPROCESS   "$PY"   postprocess --aoi pakistan --pred-dir "$PRED" --threshold 0.3
run_stage PK_EXPORT        "$PY"   export      --aoi pakistan --pred-dir "$PRED"
run_stage PK_SUB400        "$PY"   sub400-capacity --aoi pakistan --pred-dir "$PRED" \
  --roofclf-dir data/roofclf_national_with_sppi/pakistan/prob --out-dir "$ROOFCLF_OUT_PK" \
  --osm-solar data/labels/pakistan_overpass_solar.parquet
run_stage PK_GE400         "$PY"   ge400-roof-capacity --aoi pakistan --pred-dir "$PRED" \
  --roofclf-dir data/roofclf_national_with_sppi/pakistan/prob --out-dir "$ROOFCLF_OUT_PK" \
  --osm-solar data/labels/pakistan_overpass_solar.parquet
run_stage PK_CALIBRATE     "$PY"   calibrate-candidates --aoi pakistan --pred-dir "$PRED"
run_stage PK_DENSITY       "$PY"   density --aoi pakistan --pred-dir "$PRED" --districts
run_nonfatal PK_CHECK_DENSITY "$PY" check-density --aoi pakistan --pred-dir "$PRED"

echo "$(date -Is) === v4 promotion: Gujarat ===" >> "$LOG"
run_stage GJ_INFER         "$MLPY" infer   --aoi gujarat --checkpoint "$CKPT" --out-dir "$PRED"
run_stage GJ_POSTPROCESS   "$PY"   postprocess --aoi gujarat --pred-dir "$PRED" --threshold 0.3
run_stage GJ_EXPORT        "$PY"   export      --aoi gujarat --pred-dir "$PRED"
run_stage GJ_CALIBRATE     "$PY"   calibrate-candidates --aoi gujarat --pred-dir "$PRED" --recall-reference none
run_stage GJ_DENSITY       "$PY"   density --aoi gujarat --pred-dir "$PRED" --districts
run_nonfatal GJ_CHECK_DENSITY "$PY" check-density --aoi gujarat --pred-dir "$PRED"

echo "$(date -Is) === v4 promotion: atlases (verification copies, results/) ===" >> "$LOG"
run_stage PK_ATLAS "$PY" atlas --aoi pakistan --pred-dir "$PRED" \
  --sub400-central-cells   "$ROOFCLF_OUT_PK/sub400_central_incremental_buildings.parquet" \
  --sub400-low-cells       "$ROOFCLF_OUT_PK/sub400_low_incremental_buildings.parquet" \
  --sub400-outdomain-cells "$ROOFCLF_OUT_PK/sub400_outdomain_and_gate_incremental_buildings.parquet" \
  --ge400-roof-cells       "$ROOFCLF_OUT_PK/ge400_roof_incremental_buildings.parquet" \
  --osm-solar data/labels/pakistan_overpass_solar.parquet \
  --pose-summary-csv data/glint/country2000_summary.csv \
  --pose-history-note "(a 4x-larger, chunked-tile-batch re-run of the original 500-target study)" \
  --pose-data-note "(2000-target stratified country study, chunked tile-batch pull)" \
  --out results/pakistan_evidence_atlas_v4_check.html

run_stage GJ_ATLAS "$PY" atlas --aoi gujarat --pred-dir "$PRED" \
  --out results/gujarat_pv_atlas_v4_check.html

echo "$(date -Is) V4_PROMOTION_DONE" >> "$LOG"

echo "$(date -Is) === starting fraction-head k-fold retrain ===" >> "$LOG"
exec bash scripts/run_fraction_kfold.sh
