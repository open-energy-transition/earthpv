#!/usr/bin/env bash
# France evidence atlas, in the segmentation-only form.
#
# Waits for the density stage, then builds the atlas. Deliberately omits
# --sub400-central-cells / --sub400-low-cells: those need `roofclf-score-national` over the
# whole country plus `sub400-capacity`, and France's composites currently cover the 31
# calibration-commune cells only. CLAUDE.md's rule for a country in that state is the
# segmentation-only evidence atlas, and supplying one sub400 flag without the other is
# rejected as a half-configured run anyway.
#
# The result is therefore a COMMUNE-DOMAIN product, not a national one. It is labelled as
# such and must not be quoted as a French national total.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
LOG=data/france_evidence_atlas.log
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "waiting for the France pipeline (density) to finish"
while systemctl --user is-active --quiet earthpv-france-pipeline; do sleep 30; done

if [ ! -d data/predictions/france/density ]; then
  say "FATAL: no density output at data/predictions/france/density; atlas skipped"; exit 1
fi

OSM=data/labels/france_national_osm_solar.parquet
if [ ! -s "$OSM" ]; then
  say "waiting for the OSM solar pull"
  while systemctl --user is-active --quiet earthpv-france-osm; do sleep 30; done
fi
if [ ! -s "$OSM" ]; then
  say "FATAL: --osm-solar is required and $OSM is missing"; exit 1
fi
say "osm solar: $($PY -c "import geopandas as g;print(len(g.read_parquet('$OSM')))") features"

say "building evidence atlas"
$PY -m earthpv.cli atlas --aoi france --osm-solar "$OSM" \
  --out results/france_pv_evidence_atlas.html >>"$LOG" 2>&1 \
  || { say "atlas FAILED"; exit 1; }

mkdir -p docs/assets/interactive
cp results/france_pv_evidence_atlas.html docs/assets/interactive/france_pv_evidence_atlas.html
say "EVIDENCE ATLAS READY: $(du -h results/france_pv_evidence_atlas.html | cut -f1)"
