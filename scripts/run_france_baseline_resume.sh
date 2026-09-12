#!/usr/bin/env bash
# Resume the France baseline from postprocess, after the stale-VIDA-cache fix.
#
# The first attempt reused a 153,759-building cache built for a 31-cell pilot, so 13,330 of
# 13,419 national candidates came back `no_building`. That is not a detection result, it is
# a stale file, and it would have converted essentially all capacity at the ground constant.
# `buildings.load_dense_buildings` now compares extents and refetches; this re-runs the
# stages that consumed the bad placements.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
LOG=data/france_baseline.log
OSM=data/labels/france_national_osm_solar.parquet
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "=== postprocess (refetching VIDA for 5,380 cells; expect 1-3 h) ==="
$PY -m earthpv.cli postprocess --aoi france --threshold 0.3 >>"$LOG" 2>&1 \
  || { say "postprocess FAILED"; exit 1; }
$PY - <<'PYQ' 2>&1 | tee -a "$LOG"
import geopandas as gpd
g=gpd.read_parquet('data/predictions/france/candidates.parquet')
vc=g.placement.value_counts()
print("PLACEMENT AFTER REFETCH:", vc.to_dict())
frac=vc.get('no_building',0)/len(g)
print(f"no_building fraction: {frac:.3f}")
raise SystemExit(1 if frac > 0.90 else 0)
PYQ
[ $? -eq 0 ] || { say "STILL >90% no_building -- stopping, the join is still wrong"; exit 1; }

$PY -m earthpv.cli export --aoi france >>"$LOG" 2>&1 || say "export failed (non-fatal)"

say "=== calibrate-candidates (national, interim mapped-only) ==="
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
cp -f results/france_validation/france_validation.json \
      results/france_validation/france_validation_BASELINE_zeroshot.json

say "=== atlases ==="
$PY -m earthpv.cli atlas --aoi france --osm-solar "$OSM" \
  --out results/france_pv_evidence_atlas.html >>"$LOG" 2>&1 || say "evidence atlas FAILED"
$PY scripts/build_france_comparison_atlas.py >>"$LOG" 2>&1 || say "comparison atlas FAILED"
mkdir -p docs/assets/interactive
cp -f results/france_pv_evidence_atlas.html docs/assets/interactive/ 2>/dev/null
cp -f results/france_pv_comparison_atlas.html docs/assets/interactive/ 2>/dev/null
say "=== BASELINE COMPLETE ==="
