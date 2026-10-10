#!/bin/bash
# OSM solar label pulls for the 2026-10-10 Morocco/Egypt/Yemen/South Africa run.
# Usage: pull_labels_mena_za.sh [--fetch-only]. Cached tiles are reused on a rerun.
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
pull() {  # pull <aoi> <bbox> <iso3> <tiles>
  echo "$(date '+%F %T') LABELS[$1] start ${EXTRA:-}"
  $PY scripts/overpass_labels_chunked.py --bbox="$2" --iso3 "$3" --name "$1" --tiles "$4" \
    --timeout 300 --retries 8 ${EXTRA:-} >> "data/$1_labels.log" 2>&1
  echo "$(date '+%F %T') LABELS[$1] rc=$?"
}
EXTRA=${1:-}
pull morocco      -13.2,27.6,-1.0,35.95  MAR 4x3
pull egypt        24.7,22.0,36.9,31.7    EGY 4x4
pull yemen        41.8,12.1,54.6,19.0    YEM 4x3
pull south_africa 16.4,-34.9,32.9,-22.1  ZAF 8x6
