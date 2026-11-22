#!/usr/bin/env bash
# building_layer_stage_chain.sh <variant> : the production chain from postprocess to atlas
# (scripts/run_country_compute.sh, minus review draws, the ground screen and leads/polygons
# releases, whose outputs are reused) for Belgium and the Netherlands in tree_<variant>.
set -uo pipefail
V=$1
S=/home/tobi/earthpv_data/stage_buildings_20261122
T=$S/tree_$V
cd "$T"
export PYTHONPATH="$T/src"
PY=.pixi/envs/default/bin/python
declare -A THR=([belgium]=0.3 [netherlands]=0.98)
G=/home/tobi/earthpv_data/geofabrik
declare -A PBF=([belgium]=$G/belgium_20261107/belgium-latest.osm.pbf
                [netherlands]=$G/netherlands_20261107/netherlands-latest.osm.pbf)
run() { echo "$(date '+%F %T') [$V/$AOI] $*"; "$@"; rc=$?; echo "$(date '+%F %T') [$V/$AOI] rc=$rc"; return 0; }
for AOI in belgium netherlands; do
  LABELS=data/labels/${AOI}_overpass_solar.parquet
  OSM=data/labels/${AOI}_national_osm_solar.parquet
  run $PY -m earthpv.cli postprocess --aoi $AOI --threshold ${THR[$AOI]} --building-buffer-m 500 --stream-buildings
  run $PY scripts/drop_solar_thermal.py --aoi $AOI --candidates
  run $PY -m earthpv.cli export --aoi $AOI --exclude-mapped --min-distance-m 100
  run $PY -W ignore scripts/building_layer_remap_reviews.py "$T" $AOI
  run $PY -m earthpv.cli calibrate-candidates --aoi $AOI --recall-reference none
  run $PY -m earthpv.cli density --aoi $AOI --districts --threshold ${THR[$AOI]}
  run $PY -m earthpv.cli check-density --aoi $AOI
  run $PY scripts/prepare_national_osm_solar.py --aoi $AOI --labels "$LABELS" \
        --keep-detected-screen results/${AOI}_osm_ground_screen/screen_full.csv
  run $PY scripts/solar_thermal_plants.py --aoi $AOI --osm-solar $OSM --pbf ${PBF[$AOI]}
  run $PY -m earthpv.cli atlas --aoi $AOI --osm-solar "$OSM" --include-offgrid-osm \
        --imagery-date-range "May - Sep 2026" --out results/${AOI}_pv_evidence_atlas.html
done
echo "CHAIN_DONE $V"
