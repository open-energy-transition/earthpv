#!/usr/bin/env bash
# Make Germany's SUB-400 m2 half filter-free too, then rebuild its atlas.
#
# `run_de_fr_nofilter.sh` composes and re-runs density over every building-populated cell,
# which removes the --min-buildings filter from the >= 400 m2 SEGMENTATION half. It does not
# touch the sub-400 half: that comes from `roofclf-score-national`, whose output covers only
# the cells that existed when it was last run (4,657). Leaving it there would ship an atlas
# whose two halves cover different countries -- and the sub-400 estimate is Germany's LARGEST
# Best component (52.2 GWp), so the mismatch would matter.
#
# Scoring is per-cell and skips what already exists, so only the new cells compute. The model
# is refitted from the same `germany+fr_border` mix first, which is deterministic given the
# same training parquets, so the existing 4,657 cells stay valid alongside the new ones.
#
#   bash scripts/germany_sub400_topup.sh          # waits for the chain's de_atlas marker
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
LOG=data/germany_sub400_topup.log
say(){ echo "$(date '+%F %T') TOPUP: $*" | tee -a "$LOG"; }

# Wait for COMPOSE, not for the atlas. roofclf scoring needs only composites and building
# footprints, so it can run while the chain is busy with infer/postprocess/density -- and
# finishing the inputs BEFORE the chain's own `de_atlas` step means that step picks up the
# complete sub-400 half directly, instead of publishing a half-covered atlas that then has
# to be rebuilt. The rebuild at the end stays as a belt-and-braces step: it is seconds, and
# it guarantees the published atlas matches these inputs whichever order things finish in.
for _ in $(seq 1 720); do
  [ -f data/de_fr_nofilter_markers/de_compose ] && break
  sleep 60
done
[ -f data/de_fr_nofilter_markers/de_compose ] || { say "de_compose never landed; aborting"; exit 1; }
say "Germany compose finished; topping up the sub-400 half while the chain continues"

# Recompute the gap AFTER compose finished, so a late cell is not missed.
$PY - <<'EOF' >> "$LOG" 2>&1
import os, pandas as pd
comp={d for d in os.listdir('data/composites/germany/composites')
      if os.path.exists(f'data/composites/germany/composites/{d}/composite_0.tif')}
prob={f.rsplit('.',1)[0] for f in os.listdir('data/roofclf_national_germany_prod/germany/prob')}
new=sorted(comp-prob)
print(f"composites {len(comp)}, already scored {len(prob)}, to score {len(new)}")
pd.DataFrame({'cell':new}).to_csv('data/germany_new_cells.csv', index=False)
EOF
n=$(( $(wc -l < data/germany_new_cells.csv) - 1 ))
say "scoring $n new cells with the production mix (germany+fr_border)"
$PY scripts/run_germany_roofclf_production.py --mix germany+fr_border \
    --cells-csv data/germany_new_cells.csv >> "$LOG" 2>&1 \
  || { say "roofclf scoring FAILED"; exit 1; }
say "scored; prob dir now $(ls data/roofclf_national_germany_prod/germany/prob | wc -l) cells"

# The published half is `--method size_band`, NOT the builder's default. Defaulting would
# silently swap Germany's sub-400 estimator back to the probability-weighted roofclf one that
# was REPLACED on 2026-09-13 for scoring worst of the three options (48.4% median municipal
# error against 37.8% for plain roof area and 35.4% for this band). The parameters are
# refitted on the no-filter grid 2026-09-15 (0.03509 -> 0.03493); the recipe is a pooled
# ratio of sums, sum(kw_rooftop_le100)/sum(band roof area) over fully covered Gemeinden,
# which reproduced 0.03509 exactly on the old grid. Central sums to 52,128.9 MWp and the floor
# tier is all zeros, which only the size_band branch produces (a regression has no second
# detector, so `agree` is zeroed rather than the component omitted).
say "regenerating the sub-400 atlas inputs (size_band, 200-400 m2 at 0.03493 kWp/m2)"
$PY scripts/build_germany_sub400_atlas_inputs.py \
    --method size_band --kwp-per-m2 0.03493 --min-roof-m2 200 --max-roof-m2 400 \
    >> "$LOG" 2>&1 || { say "sub400 inputs FAILED"; exit 1; }

# If the chain has not reached its own atlas step yet, that step will now use these inputs
# and this rebuild is redundant but harmless. If it already ran, this corrects it.
for _ in $(seq 1 360); do
  [ -f data/de_fr_nofilter_markers/de_atlas ] && break
  sleep 60
done
say "rebuilding the Germany atlas on the complete grid"
$PY -m earthpv.cli atlas --aoi germany \
  --osm-solar data/labels/germany_national_osm_solar.parquet \
  --sub400-central-cells data/roofclf_national_germany_prod/germany/density/sub400_central_incremental_buildings.parquet \
  --sub400-low-cells data/roofclf_national_germany_prod/germany/density/sub400_low_incremental_buildings.parquet \
  --include-offgrid-osm \
  --out docs/assets/interactive/germany_pv_evidence_atlas.html >> "$LOG" 2>&1 \
  || { say "atlas FAILED"; exit 1; }
say "TOPUP DONE"
