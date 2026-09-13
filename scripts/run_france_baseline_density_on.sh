set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
LOG=data/france_baseline.log
OSM=data/labels/france_national_osm_solar.parquet
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }
say "=== density (national, fresh: 31-cell partials archived) ==="
$PY -m earthpv.cli density --aoi france --districts >>"$LOG" 2>&1 || { say "density FAILED"; exit 1; }
$PY -m earthpv.cli check-density --aoi france >>"$LOG" 2>&1 || say "check-density reported failures"
say "=== register comparison (THE BASELINE) ==="
$PY -m earthpv.cli validate-france --opvm data/openpvmapper/enriched_national.parquet >>"$LOG" 2>&1 \
  || { say "validate-france FAILED"; exit 1; }
cp -f results/france_validation/france_validation.json results/france_validation/france_validation_BASELINE_zeroshot.json
say "=== atlases ==="
$PY -m earthpv.cli atlas --aoi france --osm-solar "$OSM" --out results/france_pv_evidence_atlas.html >>"$LOG" 2>&1 || say "evidence atlas FAILED"
$PY scripts/build_france_comparison_atlas.py >>"$LOG" 2>&1 || say "comparison atlas FAILED"
mkdir -p docs/assets/interactive
cp -f results/france_pv_evidence_atlas.html docs/assets/interactive/ 2>/dev/null
cp -f results/france_pv_comparison_atlas.html docs/assets/interactive/ 2>/dev/null
say "=== BASELINE COMPLETE ==="
