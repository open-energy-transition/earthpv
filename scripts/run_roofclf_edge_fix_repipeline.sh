#!/usr/bin/env bash
# Re-runs everything downstream of the 2026-08-06 cell-edge-fill and composite-tile
# overlap fixes (see docs/issues/roofclf-cell-edge-false-positives.md), in the order
# that doc's "What has to be re-run" section specifies:
#   1. roofclf LOQO refit (fast) -> model_full.json, deployment threshold, folds.csv,
#      buildings.geoparquet. Refitting first (not reusing the stale 2026-08-05 model)
#      matters because building_table's own fill-fix changes sialkot/sukkur's features.
#   2. score_buildings_national with that model, over the canonical (deduped) cell grid
#      -- the long pole, ~2-3h.
#   3. sub400_capacity's two domain-restricted capacity functions, writing the exact
#      artifact layout scripts/build_small_pv_josm_leads.py already expects.
#   4. Evidence atlas rebuild.
#   5. JOSM leads + roofclf-tiles export (left for the caller -- see the log's tail).
#
# Run as its own systemd-run --user unit (not just nohup) per docs/notes memory of long
# jobs dying to session-scope OOM/logout; Linger is already enabled on this account.
set -uo pipefail
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
STAMP=20260806

REFIT_DIR=data/roofclf                                       # canonical "current" dir
NAT_DIR=data/roofclf_national_with_sppi/pakistan             # canonical national dir
SUB400_DIR=data/sub400_${STAMP}_fixed                          # dated audit copy
CAND=data/predictions/pakistan/candidates.parquet
OSM_SOLAR=data/labels/pakistan_overpass_solar.parquet
OLD_CELL_DENSITY=data/sub400_20260806/national_cell_density.parquet  # unaffected by
                                                                       # either fix (built
                                                                       # from inference
                                                                       # rasters, not raw
                                                                       # composite tiles)

mkdir -p "$SUB400_DIR" "$NAT_DIR/prob" "$NAT_DIR/density"

echo "########## $(date -Is) STEP 1: roofclf LOQO refit (fixed building_table)"
"$PY" -m earthpv.cli roof-classifier --aoi pakistan --out-dir "$REFIT_DIR" \
  || { echo "STEP1_FAILED"; exit 1; }
cp "$OLD_CELL_DENSITY" "$REFIT_DIR/national_cell_density.parquet"

echo "########## $(date -Is) STEP 1 outputs"
"$PY" - <<EOF
import json
s = json.load(open("$REFIT_DIR/summary.json"))
for k in ("n_quadrats", "n_buildings", "n_pv", "median_fold_auc", "median_fold_auc_within_size",
          "deployment_threshold", "deployment_threshold_stats"):
    if k in s:
        print(f"  {k:34s} {s[k]}")
EOF

echo "########## $(date -Is) STEP 2: score every VIDA building nationally (long pole)"
"$PY" - <<EOF || { echo "STEP2_FAILED"; exit 1; }
import json, logging
from pathlib import Path
from earthpv import roofclf
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
model, feats = roofclf.load_model(Path("$REFIT_DIR/model_full.json"))
roofclf.score_buildings_national(
    "pakistan", model, feats, Path("data/composites/pakistan"), Path("$NAT_DIR/prob"),
)
EOF

echo "########## $(date -Is) STEP 3: domain-restricted sub-400 capacity (roofclf-only + AND-gate)"
"$PY" - <<EOF || { echo "STEP3_FAILED"; exit 1; }
import json
from pathlib import Path
from earthpv import sub400_capacity as sc

REFIT_DIR = Path("$REFIT_DIR")
NAT_DIR = Path("$NAT_DIR")
SUB400_DIR = Path("$SUB400_DIR")
summary = json.load(open(REFIT_DIR / "summary.json"))
threshold = summary["deployment_threshold"]
print("Using deployment_threshold =", threshold)

kwargs = dict(
    roofclf_dir=NAT_DIR / "prob",
    candidates_path=Path("$CAND"),
    folds_path=REFIT_DIR / "folds.csv",
    buildings_path=REFIT_DIR / "buildings.geoparquet",
    cell_density_path=REFIT_DIR / "national_cell_density.parquet",
    threshold=threshold,
    osm_solar_path=Path("$OSM_SOLAR"),
)

central, central_summary = sc.domain_restricted_capacity(**kwargs)
central.to_parquet(NAT_DIR / "density" / "sub400_central_incremental_buildings.parquet")
central.to_parquet(SUB400_DIR / "sub400_central.parquet")
json.dump(central_summary, open(SUB400_DIR / "sub400_central_summary.json", "w"), indent=2)
print("CENTRAL:", json.dumps(central_summary, indent=2))

low, low_summary = sc.domain_restricted_and_gate_capacity(**kwargs)
low.to_parquet(NAT_DIR / "density" / "sub400_low_incremental_buildings.parquet")
low.to_parquet(SUB400_DIR / "sub400_low.parquet")
json.dump(low_summary, open(SUB400_DIR / "sub400_low_summary.json", "w"), indent=2)
print("LOW (AND-gate):", json.dumps(low_summary, indent=2))
EOF

echo "########## $(date -Is) STEP 4: rebuild the evidence atlas"
ATLAS_OUT=results/pakistan_pv_evidence_atlas.html
if [ -f "$ATLAS_OUT" ]; then
  cp "$ATLAS_OUT" "results/pakistan_pv_evidence_atlas_PRE_edge_overlap_fix_${STAMP}_backup.html"
fi
"$PY" -m earthpv.cli atlas --aoi pakistan \
  --sub400-low-cells "$SUB400_DIR/sub400_low.parquet" \
  --sub400-central-cells "$SUB400_DIR/sub400_central.parquet" \
  --osm-solar "$OSM_SOLAR" \
  --out "$ATLAS_OUT" \
  || { echo "STEP4_FAILED"; exit 1; }

echo "########## $(date -Is) ALL_STEPS_DONE ($REFIT_DIR, $NAT_DIR, $SUB400_DIR, $ATLAS_OUT)"
echo "Next (not run automatically here): pixi run small-pv-leads ; pixi run roofclf-tiles -- --cell <cell>"
