#!/usr/bin/env bash
# Rescore Germany with the register-labelled model, then re-run the register validation.
# Only the training labels differ from the previous national run: same features, same
# footprints (VIDA), same cells, same calibration harness.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
LOG=data/de_mastr_rescore.log
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "=== national scoring, register-labelled model ==="
$PY scripts/score_germany_osm_footprints.py --cells-csv "$1" --footprints vida \
  --model-path data/roofclf_germany_mastr/model_full.json \
  --out-dir data/roofclf_national_germany_mastr/germany/prob >>"$LOG" 2>&1 \
  || { say "scoring FAILED"; exit 1; }

say "=== capacity calibration against MaStR ==="
$PY scripts/calibrate_germany_capacity.py \
  --prob-dir data/roofclf_national_germany_mastr/germany/prob \
  --out results/germany_roofclf_capacity_mastr.json \
  --out-cells results/germany_roofclf_capacity_mastr_by_cell.csv >>"$LOG" 2>&1 \
  || { say "calibration FAILED"; exit 1; }
say "=== MASTR RESCORE COMPLETE ==="
