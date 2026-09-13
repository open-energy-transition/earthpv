#!/usr/bin/env bash
# The sub-400 m2 estimator against a complete register, twice: VIDA footprints as deployed,
# then OSM footprints, over the SAME cells so the only difference is the building layer.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
CELLS="$1"
LOG=data/de_register_validation.log
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

for FP in vida osm; do
  say "=== national scoring, $FP footprints ==="
  $PY scripts/score_germany_osm_footprints.py --cells-csv "$CELLS" --footprints "$FP" \
    >>"$LOG" 2>&1 || { say "$FP scoring FAILED"; exit 1; }
  say "=== register validation, $FP ==="
  $PY scripts/validate_sub400_against_mastr.py \
    --prob-dir "data/roofclf_national_germany_$FP/germany/prob" --label "$FP" \
    >>"$LOG" 2>&1 || { say "$FP validation FAILED"; exit 1; }
  say "--- $FP done ---"
done
say "=== REGISTER VALIDATION COMPLETE ==="
