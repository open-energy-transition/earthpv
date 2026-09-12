#!/usr/bin/env bash
# v6: France capped to Germany's size -> train, infer, score. The ablation that separates
# "French data is present" from "the corpus is 3.8x larger" in v5's result.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
PRED=data/predictions_v6
LOG=data/france_v6.log
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "=== train (v6, France capped to 3,201 train chips) ==="
$MLPY -m earthpv.cli train --config configs/terramind_pv_v6_france_capped.yaml >>"$LOG" 2>&1 \
  || { say "train FAILED"; exit 1; }
CKPT=$(ls -t data/models/v6_france_capped/terramind-pv-epoch=*.ckpt 2>/dev/null | head -1)
[ -n "$CKPT" ] || { say "no checkpoint produced"; exit 1; }
say "best checkpoint: $CKPT"

say "=== infer (v6) ==="
$MLPY -m earthpv.cli infer --aoi france --checkpoint "$CKPT" --out-dir "$PRED" >>"$LOG" 2>&1 \
  || { say "infer FAILED"; exit 1; }

say "=== postprocess (v6) ==="
$PY -m earthpv.cli postprocess --aoi france --threshold 0.3 --pred-dir "$PRED" >>"$LOG" 2>&1 \
  || { say "postprocess FAILED"; exit 1; }
$PY - <<'PYQ' 2>&1 | tee -a "$LOG"
import geopandas as gpd
g=gpd.read_parquet('data/predictions_v6/france/candidates.parquet')
print("V6 candidates:", len(g), "| placement:", g.placement.value_counts().to_dict())
frac=g.placement.value_counts().get('no_building',0)/len(g)
print(f"no_building fraction: {frac:.3f}")
raise SystemExit(1 if frac > 0.90 else 0)
PYQ
[ $? -eq 0 ] || { say "STILL >90% no_building -- stopping"; exit 1; }

say "=== calibrate + density (v6) ==="
$PY -m earthpv.cli calibrate-candidates --aoi france --pred-dir "$PRED" \
  --recall-reference none --by-placement >>"$LOG" 2>&1 || { say "calibrate FAILED"; exit 1; }
$PY -m earthpv.cli density --aoi france --districts --pred-dir "$PRED" >>"$LOG" 2>&1 \
  || { say "density FAILED"; exit 1; }

say "=== register comparison #3 (v6 capped) ==="
$PY -m earthpv.cli validate-france --opvm data/openpvmapper/enriched_national.parquet \
  --density-dir "$PRED/france/density" --out-dir results/france_validation_v6 >>"$LOG" 2>&1 \
  || { say "validate FAILED"; exit 1; }
say "=== V6 COMPLETE ==="
