#!/bin/bash
# VIDA building footprints for the 2026-10-10 Morocco/Egypt/Yemen/South Africa run.
cd "$(dirname "$0")/.."
for i in MAR YEM EGY ZAF; do
  dest=/home/tobi/earthpv_data/$i.parquet
  [ -s "$dest" ] && [ ! -e "$dest.part" ] && { echo "$(date '+%F %T') $i already present"; continue; }
  echo "$(date '+%F %T') $i start"
  .pixi/envs/default/bin/python scripts/ranged_download.py \
    "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country/country_iso=$i/$i.parquet" \
    "$dest" --workers 16 --chunk-mb 32 || echo "$(date '+%F %T') $i FAILED rc=$?"
  echo "$(date '+%F %T') $i done $(stat -c %s "$dest" 2>/dev/null)"
done
