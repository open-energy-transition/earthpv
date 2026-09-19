#!/usr/bin/env bash
# Measure whether keeping more than the median earns its place in roofclf.
#
#   1. scripts/compose_temporal_stats.py  writes a temporal_stats_0.tif sidecar for each
#      calibration-quadrat cell (p10/p50/p90/std per band + n_obs), off the same scene
#      stack the median composite already downloads.
#   2. this script refits roofclf with --temporal-features, which puts that block in the
#      TABLE and offers it to the ablation. It is NOT put in the fitted model: the shipped
#      feature set is unchanged, so `plus_temporal` vs `size_plus_spectral` in
#      ablation.csv is the whole verdict.
#
# Writes to its own --out-dir, so data/roofclf (production, 2026-08-20 Box 18 refit) is
# untouched and the comparison is against its recorded 0.8574 median fold AUC / 0.8206
# within size band.
#
# The quadrat set is the production one: every discoverable quadrat EXCEPT
# kalat_rural_calib_3km, which is Rule-1 but must stay out of any refit until
# building_table's roof term gets a placement/size guard (69 of its 89 has-PV buildings
# are labelled solely because a >= 400 m2 GROUND array clips them). See CLAUDE.md's
# "Calibration quadrats" and docs/issues/pakistan-calibration-boxes.md Box 17.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.pixi/envs/default/bin/python
OUT=${1:-data/roofclf_temporal_ablation}
EXCLUDE=kalat_rural_calib_3km

mapfile -t QUADRATS < <("$PY" - <<'PYEOF'
from pathlib import Path
from earthpv.roofclf import discover_quadrats
for q in sorted(discover_quadrats(Path("data/labels"))):
    if q != "kalat_rural_calib_3km":
        print(q)
PYEOF
)
echo "Refitting on ${#QUADRATS[@]} quadrats (excluding $EXCLUDE) -> $OUT"

ARGS=()
for q in "${QUADRATS[@]}"; do ARGS+=(--quadrat "$q"); done

"$PY" -m earthpv.cli roof-classifier \
  --aoi pakistan \
  --parcel-label \
  --temporal-features \
  --out-dir "$OUT" \
  "${ARGS[@]}"

echo
echo "=== Feature-block ablation (median across leave-one-quadrat-out folds) ==="
column -s, -t < "$OUT/ablation.csv"
