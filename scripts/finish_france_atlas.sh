#!/usr/bin/env bash
# Rebuild the France validation and comparison atlas once the national commune polygons
# and (if present) an earthpv density run are available, then place the atlas where the
# docs build expects it.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
LOG=data/france_atlas.log
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "waiting for commune polygons"
while systemctl --user is-active --quiet earthpv-france-communes; do sleep 30; done
if [ ! -s data/labels/france_communes.parquet ]; then
  say "FATAL: data/labels/france_communes.parquet missing"; exit 1
fi
say "communes ready"

say "re-running validation (picks up density if it exists)"
$PY -m earthpv.cli validate-france \
  --opvm data/openpvmapper/enriched_national.parquet >>"$LOG" 2>&1 \
  || { say "validate-france FAILED"; exit 1; }

say "building comparison atlas"
$PY scripts/build_france_comparison_atlas.py >>"$LOG" 2>&1 \
  || { say "atlas build FAILED"; exit 1; }

mkdir -p docs/assets/interactive
cp results/france_pv_comparison_atlas.html docs/assets/interactive/france_pv_comparison_atlas.html
say "ATLAS READY: $(du -h results/france_pv_comparison_atlas.html | cut -f1)"
