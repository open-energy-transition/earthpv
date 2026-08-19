#!/usr/bin/env bash
# Two-epoch PV growth pipeline (see src/earthpv/growth.py's module docstring).
#
# Runs BOTH epochs through one identical instrument pair: the v4_combined_all
# epoch=41 segmentation checkpoint (the only national-capable checkpoint still on
# disk -- v3_combined_india and pk16085 were deleted, which is what made the first
# growth map a cross-checkpoint diff) and the production parcel-label roofclf model.
# The current-epoch segmentation pass already exists (data/predictions_v4, built
# 2026-08-14); its density is REBUILT here because that run used the regressed
# pooled calibration table (calibration_status=interim-mapped-only) that was
# restored to the placement-split version on 2026-08-15.
#
# Stages are stamped under $STAMPS; a finished stage is skipped on re-run, and the
# long stages (infer, density, roofclf scoring) additionally resume per cell on
# their own. Total cold runtime ~11-13 h (infer 3.3h + postprocess 0.7h +
# 2x density 2.3h + roofclf scoring ~2.5h + capacity stages ~0.5h).
#
# Run detached (Linger is enabled on this machine):
#   systemd-run --user --unit=earthpv-growth-pipeline \
#     --working-directory="$PWD" bash scripts/run_growth_pipeline.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PYD=.pixi/envs/default/bin/python
PYML=.pixi/envs/ml/bin/python
AOI=pakistan
CKPT="data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt"
PB=data/predictions_preboom_v4
CURP=data/predictions_v4
RCPROB_CUR=data/roofclf_national_with_sppi/$AOI/prob        # parcel scoring, current epoch (exists)
RCPRE=data/roofclf_national_with_sppi_preboom/$AOI
RCCUR=data/roofclf_national_with_sppi_growth_current/$AOI
OSM=data/labels/pakistan_overpass_solar.parquet
OUT=data/growth/$AOI
STAMPS=$OUT/.stages
LOG=data/growth_pipeline.log
mkdir -p "$STAMPS"

ts() { date '+%FT%T%z'; }
say() { echo "$(ts) $*" >> "$LOG"; }

run_stage() {  # run_stage NAME cmd...
  local name=$1; shift
  if [ -f "$STAMPS/$name.done" ]; then say "$name: already done, skipping"; return 0; fi
  say "$name: starting ($*)"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  say "$name: exit rc=$rc"
  if [ $rc -ne 0 ]; then say "PIPELINE ABORTED at $name"; exit $rc; fi
  touch "$STAMPS/$name.done"
}

say "=== growth pipeline start (checkpoint $CKPT) ==="

# 1. Pre-boom national inference, same checkpoint as data/predictions_v4.
run_stage PB_INFER "$PYML" -m earthpv.cli infer --aoi $AOI --checkpoint "$CKPT" \
  --index 1 --out-dir $PB

# 2. Pre-boom postprocess, mirroring the v4 promotion's flags exactly.
run_stage PB_POSTPROCESS "$PYD" -m earthpv.cli postprocess --aoi $AOI \
  --pred-dir $PB --threshold 0.3

# 3. Current-epoch density REBUILD against the restored placement-split calibration
#    YAML (the 2026-08-14 run used the regressed pooled table). Back up the old one.
if [ ! -f "$STAMPS/CUR_DENSITY_BACKUP.done" ]; then
  if [ -d "$CURP/$AOI/density" ]; then
    cp -a "$CURP/$AOI/density" "$CURP/$AOI/density_PRE_growth_recal_20260819_backup" \
      >> "$LOG" 2>&1 || { say "backup failed"; exit 1; }
    say "CUR_DENSITY_BACKUP: copied density -> density_PRE_growth_recal_20260819_backup"
  fi
  touch "$STAMPS/CUR_DENSITY_BACKUP.done"
fi
run_stage CUR_DENSITY "$PYD" -m earthpv.cli density --aoi $AOI --pred-dir $CURP \
  --districts --force

# 4. Pre-boom density, same (default) calibration YAML.
run_stage PB_DENSITY "$PYD" -m earthpv.cli density --aoi $AOI --pred-dir $PB --districts

# 5. Plausibility gate on the pre-boom epoch (informational: exit 1 = a region
#    failed; recorded, does not block the growth diff, matching project precedent
#    for checked failures -- but check the log before publishing).
if [ ! -f "$STAMPS/PB_CHECK_DENSITY.done" ]; then
  say "PB_CHECK_DENSITY: starting"
  "$PYD" -m earthpv.cli check-density --aoi $AOI --pred-dir $PB >> "$LOG" 2>&1
  say "PB_CHECK_DENSITY: exit rc=$? (non-fatal, review before publishing)"
  touch "$STAMPS/PB_CHECK_DENSITY.done"
fi

# 6. Pre-boom roofclf national scoring: same parcel model, composite_1 reflectance.
run_stage PB_ROOFCLF "$PYD" -m earthpv.cli roofclf-score-national --aoi $AOI \
  --out-dir $RCPRE/prob --layer-index 1

# 7. Pre-boom capacity halves (deduped against the pre-boom epoch's own candidates).
run_stage PB_SUB400 "$PYD" -m earthpv.cli sub400-capacity --aoi $AOI \
  --pred-dir $PB --roofclf-dir $RCPRE/prob --out-dir $RCPRE/density --osm-solar $OSM
run_stage PB_GE400 "$PYD" -m earthpv.cli ge400-roof-capacity --aoi $AOI \
  --pred-dir $PB --roofclf-dir $RCPRE/prob --out-dir $RCPRE/density --osm-solar $OSM

# 8. Current-epoch capacity halves, rebuilt against the v4 candidates (the canonical
#    ones under data/roofclf_national_with_sppi were deduped against the deleted v3
#    checkpoint's candidates; the growth pair must be v4-consistent on both sides).
run_stage CUR_SUB400 "$PYD" -m earthpv.cli sub400-capacity --aoi $AOI \
  --pred-dir $CURP --roofclf-dir $RCPROB_CUR --out-dir $RCCUR/density --osm-solar $OSM
run_stage CUR_GE400 "$PYD" -m earthpv.cli ge400-roof-capacity --aoi $AOI \
  --pred-dir $CURP --roofclf-dir $RCPROB_CUR --out-dir $RCCUR/density --osm-solar $OSM

# 9. Combine into the growth grid/regions/summary.
run_stage GROWTH "$PYD" -m earthpv.cli growth --aoi $AOI \
  --current-pred-dir $CURP --preboom-pred-dir $PB \
  --current-roofclf-density $RCCUR/density --preboom-roofclf-density $RCPRE/density \
  --out-dir $OUT \
  --sppi-growth-grid data/predictions/pakistan/density/growth/sppi_growth_grid.geoparquet \
  --current-label "current (2025/26 dry season, v4_combined_all epoch=41)" \
  --preboom-label "pre-boom (2021-10..2022-01, same checkpoint)"

say "=== growth pipeline DONE -> $OUT/summary.json ==="
