#!/usr/bin/env bash
# Wait for every shard of the verified-negative scene-series pull, then fetch pixel stamps
# for the negatives (itself sharded). Two stages, one unit: the stamp fetch needs the
# cached series to decide which scenes to read, so it cannot start early, and leaving the
# hand-off to an operator is how a multi-hour chain ends up idle overnight.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PY=.pixi/envs/default/bin/python
NSHARD=4

wait_for() {  # wait_for <unit-prefix>
  local prefix=$1 active=1
  while [ "$active" -gt 0 ]; do
    active=0
    for i in $(seq 0 $((NSHARD - 1))); do
      if systemctl --user is-active --quiet "${prefix}-${i}"; then active=$((active + 1)); fi
    done
    [ "$active" -gt 0 ] && sleep 60
  done
}

# Two conditions, not one. "No shard is active" alone fires during the few seconds between
# stopping and relaunching the fleet (which happened once while tuning worker counts), and
# would start the stamp fetch against a half-built series cache.
EXPECTED=$(( $(.pixi/envs/default/bin/python -c "
import geopandas as gpd
print(len(gpd.read_parquet('data/glint/psfneg_density_targets.parquet')))" 2>/dev/null || echo 600) * 95 / 100 ))
while true; do
  wait_for earthpv-psfneg-pull
  have=$(ls data/glint/psfneg_density/ 2>/dev/null | wc -l)
  if [ "$have" -ge "$EXPECTED" ]; then break; fi
  echo "$(date -Is) shards idle but only $have/$EXPECTED series present; waiting for a relaunch"
  sleep 120
done
echo "$(date -Is) series pull finished; files: $(ls data/glint/psfneg_density/ 2>/dev/null | wc -l)"

for i in $(seq 0 $((NSHARD - 1))); do
  "$PY" scripts/glint_psf_photometry.py stamps --set negatives --max-workers 6 \
      --shard "$i" --of "$NSHARD" &
done
wait
echo "$(date -Is) PSF_NEG_CHAIN_DONE stamps: $(ls data/glint/psf/stamps/negatives/ 2>/dev/null | wc -l)"
