#!/usr/bin/env bash
# France national BASELINE: everything downstream of a finished national compose, using the
# ZERO-SHOT checkpoint (v4_combined_all epoch=41, trained on Germany/Pakistan/Punjab/Gujarat
# and NO French chips).
#
# This exists to produce the number a French retrain has to beat. The register comparison it
# ends with is the first real measurement of how well segmentation transfers to France: the
# earlier attempt covered 1.9% of registered capacity and correctly refused to report itself
# as national.
#
# Order matters in one non-obvious place: `calibrate-candidates` is re-derived here BEFORE
# `density`, because the existing table was fitted on 119 candidates from 31 cells. At
# national scale there will be thousands, so mapped_frac is far better determined. Recall
# stays skipped (--recall-reference none): the hand-mapped communes are a sub-400 m2 ground
# truth and segmentation's population is above the floor, so pooling them would manufacture
# a large, badly-determined correction.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
CKPT="data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt"
LOG=data/france_baseline.log
OSM=data/labels/france_national_osm_solar.parquet
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "waiting for the national compose loop to finish"
while systemctl --user is-active --quiet earthpv-france-national-compose; do sleep 120; done
N=$(find -L data/composites/france -name 'composite_0.tif' | wc -l)
say "compose finished with $N/5471 cells"
if [ "$N" -lt 5000 ]; then
  say "FATAL: only $N cells; the loop stopped early. Fix compose before baselining."; exit 1
fi

say "=== infer (zero-shot v4_combined_all epoch=41) ==="
$MLPY -m earthpv.cli infer --aoi france --checkpoint "$CKPT" >>"$LOG" 2>&1 \
  || { say "infer FAILED"; exit 1; }
say "infer done: $(find -L data/predictions/france/prob -name '*.tif' 2>/dev/null | wc -l) rasters"

say "=== postprocess ==="
$PY -m earthpv.cli postprocess --aoi france --threshold 0.3 >>"$LOG" 2>&1 \
  || { say "postprocess FAILED"; exit 1; }
$PY -m earthpv.cli export --aoi france >>"$LOG" 2>&1 || say "export failed (non-fatal)"

say "=== calibrate-candidates (national, interim mapped-only) ==="
cp -f configs/calibration/france_candidate_precision.yaml \
      configs/calibration/france_candidate_precision_PRE_national.yaml 2>/dev/null || true
$PY -m earthpv.cli calibrate-candidates --aoi france \
  --recall-reference none --by-placement >>"$LOG" 2>&1 \
  || { say "calibrate-candidates FAILED"; exit 1; }

say "=== density ==="
$PY -m earthpv.cli density --aoi france --districts >>"$LOG" 2>&1 \
  || { say "density FAILED"; exit 1; }
$PY -m earthpv.cli check-density --aoi france >>"$LOG" 2>&1 || say "check-density reported failures"

say "=== register comparison (THE BASELINE) ==="
$PY -m earthpv.cli validate-france --opvm data/openpvmapper/enriched_national.parquet \
  >>"$LOG" 2>&1 || { say "validate-france FAILED"; exit 1; }
# Freeze it, so the post-retrain run has something to be compared against.
cp -f results/france_validation/france_validation.json \
      results/france_validation/france_validation_BASELINE_zeroshot.json
$PY - <<'PYQ' 2>&1 | tee -a "$LOG"
import json
r=json.load(open('results/france_validation/france_validation_BASELINE_zeroshot.json'))
e=r.get('earthpv_vs_register') or {}
print("BASELINE coverage_by_capacity:", e.get('coverage_by_capacity'),
      "national:", e.get('national'), "n_communes:", e.get('n_communes_scored'))
for blk in ('results','results_above_floor','results_above_floor_bt'):
    for est,st in (e.get(blk) or {}).items():
        print(f"  {blk:24s} {est:16s} slope={st.get('slope_through_origin')} "
              f"median_ratio={st.get('median_ratio')} spearman={st.get('spearman')} "
              f"total_ratio={st.get('total_ratio')}")
PYQ

say "=== atlases ==="
$PY -m earthpv.cli atlas --aoi france --osm-solar "$OSM" \
  --out results/france_pv_evidence_atlas.html >>"$LOG" 2>&1 || say "evidence atlas FAILED"
$PY scripts/build_france_comparison_atlas.py >>"$LOG" 2>&1 || say "comparison atlas FAILED"
mkdir -p docs/assets/interactive
cp -f results/france_pv_evidence_atlas.html docs/assets/interactive/ 2>/dev/null
cp -f results/france_pv_comparison_atlas.html docs/assets/interactive/ 2>/dev/null

say "=== BASELINE COMPLETE ==="
