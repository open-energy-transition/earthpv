#!/usr/bin/env bash
# Rebuild both France atlases on the retrained v5 checkpoint.
# v5 is applied to FRANCE ONLY; Pakistan and Germany keep v4 and their published figures.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
LOG=data/france_atlas_v5.log
OSM=data/labels/france_national_osm_solar.parquet
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

# Keep the zero-shot pages so the before/after is inspectable, not just remembered.
for f in results/france_pv_evidence_atlas.html results/france_pv_comparison_atlas.html; do
  [ -f "$f" ] && cp -f "$f" "${f%.html}_BASELINE_zeroshot.html"
done

say "=== evidence atlas (v5) ==="
# --include-offgrid-osm: France's density grid holds only the 5,473 cells `compose` built
# above --min-buildings, and 281,269 of 353,011 hand-mapped installations (79.7%) fall
# outside it -- more mapped capacity than the atlas showed. The flag adds an OSM-only cell
# per such installation (no imagery, no inference, every model column zero) instead of
# dropping it. Owner's call, 2026-09-13: no regional filter on the French atlas.
$PY -m earthpv.cli atlas --aoi france --pred-dir data/predictions_v5 --osm-solar "$OSM" \
  --include-offgrid-osm \
  --out results/france_pv_evidence_atlas.html >>"$LOG" 2>&1 || { say "evidence atlas FAILED"; exit 1; }

say "=== comparison atlas (v5) ==="
$PY scripts/build_france_comparison_atlas.py \
  --validation results/france_validation_v5/france_validation.json \
  --out results/france_pv_comparison_atlas.html >>"$LOG" 2>&1 || { say "comparison atlas FAILED"; exit 1; }

mkdir -p docs/assets/interactive
cp -f results/france_pv_evidence_atlas.html docs/assets/interactive/
cp -f results/france_pv_comparison_atlas.html docs/assets/interactive/
say "=== ATLASES REBUILT ON v5 ==="
