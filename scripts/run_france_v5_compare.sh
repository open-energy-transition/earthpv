#!/usr/bin/env bash
# France with the RETRAINED v5 checkpoint, then the second register comparison.
#
# Everything writes to data/predictions_v5/ so the frozen zero-shot baseline
# (data/predictions/france + france_validation_BASELINE_zeroshot.json) stays intact and the
# two runs can be diffed rather than remembered.
#
# The honest comparison is `est_mwp_det` and `est_mwp_exp`: they use no calibration and no
# recall correction, so they isolate the detector. `est_mwp_cal`/`est_mwp_rc_roof` are
# re-derived per model and move for two reasons at once.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
CKPT="data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt"
PRED=data/predictions_v5
LOG=data/france_v5.log
OSM=data/labels/france_national_osm_solar.parquet
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "=== infer (v5, France-inclusive corpus) ==="
$MLPY -m earthpv.cli infer --aoi france --checkpoint "$CKPT" --out-dir "$PRED" >>"$LOG" 2>&1 \
  || { say "infer FAILED"; exit 1; }
say "infer done: $(find -L $PRED/france/prob -name '*.tif' 2>/dev/null | wc -l) rasters"

say "=== postprocess ==="
$PY -m earthpv.cli postprocess --aoi france --threshold 0.3 --pred-dir "$PRED" >>"$LOG" 2>&1 \
  || { say "postprocess FAILED"; exit 1; }
$PY - <<'PYQ' 2>&1 | tee -a "$LOG"
import geopandas as gpd
g=gpd.read_parquet('data/predictions_v5/france/candidates.parquet')
print("V5 candidates:", len(g), "| placement:", g.placement.value_counts().to_dict())
frac=g.placement.value_counts().get('no_building',0)/len(g)
print(f"no_building fraction: {frac:.3f}")
raise SystemExit(1 if frac > 0.90 else 0)
PYQ
[ $? -eq 0 ] || { say "STILL >90% no_building -- stale building cache again; stopping"; exit 1; }

say "=== calibrate-candidates (v5) ==="
$PY -m earthpv.cli calibrate-candidates --aoi france --pred-dir "$PRED" \
  --recall-reference none --by-placement >>"$LOG" 2>&1 || { say "calibrate FAILED"; exit 1; }

say "=== density (v5) ==="
$PY -m earthpv.cli density --aoi france --districts --pred-dir "$PRED" >>"$LOG" 2>&1 \
  || { say "density FAILED"; exit 1; }

say "=== register comparison #2 (v5) ==="
$PY -m earthpv.cli validate-france --opvm data/openpvmapper/enriched_national.parquet \
  --density-dir "$PRED/france/density" \
  --out-dir results/france_validation_v5 >>"$LOG" 2>&1 || { say "validate FAILED"; exit 1; }
say "=== V5 COMPARISON COMPLETE ==="
