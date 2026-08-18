#!/usr/bin/env bash
# Wait for the parcel-label national scoring to finish, then run the capacity chain.
#
# Written 2026-08-16 for the parcel-label rollout. Everything it writes goes under
# data/roofclf_national_parcel/, so the published roof-only outputs are untouched and the
# two can be compared side by side before anything is promoted.
set -uo pipefail
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
NAT=data/roofclf_national_parcel/pakistan/prob
DENS=data/roofclf_national_parcel/pakistan/density
OSM=data/labels/pakistan_overpass_solar.parquet
LOG=data/roofclf_parcel_national.log

# The scoring unit writes "INFO Done:" once, at the end of a completed pass.
while systemctl --user is-active --quiet earthpv-roofclf-parcel-national; do sleep 60; done
if ! grep -q "INFO Done: " "$LOG"; then
  echo "FAILED: scoring unit exited without a completion marker; not running downstream"
  tail -5 "$LOG"
  exit 1
fi
echo "scoring complete, $(ls "$NAT"/*.parquet | wc -l) cells"

set -e
$PY -m earthpv.cli sub400-capacity --aoi pakistan \
  --roofclf-dir "$NAT" --calib-dir data/roofclf_parcel --out-dir "$DENS" --osm-solar "$OSM"

$PY -m earthpv.cli ge400-roof-capacity --aoi pakistan \
  --roofclf-dir "$NAT" --calib-dir data/roofclf_parcel --out-dir "$DENS" --osm-solar "$OSM"

# NOTE: --sub400-outdomain-cells is deliberately not passed (2026-08-15 decision).
$PY -m earthpv.cli atlas --aoi pakistan \
  --sub400-central-cells "$DENS/sub400_central_incremental_buildings.parquet" \
  --sub400-low-cells     "$DENS/sub400_low_incremental_buildings.parquet" \
  --ge400-roof-cells     "$DENS/ge400_roof_incremental_buildings.parquet" \
  --osm-solar "$OSM" \
  --out "$DENS/pakistan_pv_evidence_atlas_parcel.html"

echo "PARCEL DOWNSTREAM COMPLETE"
