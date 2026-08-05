#!/usr/bin/env bash
# Wait for every calibration quadrat to have a complete OSM pull, then run the sub-400 m2
# chain (fraction head + roofclf). GATED: if any quadrat is still missing its pull when the
# wait expires, do NOT start. `roofclf.discover_quadrats` silently uses whatever is present,
# so a partial set would produce a plausible-looking LOQO fit over the wrong population and
# a deployment threshold derived from it -- worse than no run, because nothing downstream
# would show which quadrats were missing.
set -uo pipefail
cd /run/media/tobi/aidisc/earthpv
MAX_WAIT_S=${MAX_WAIT_S:-5400}

pending() {
  ls data/labels/*_calib_*_boundary.geojson 2>/dev/null | sed 's|.*/||;s|_boundary.geojson||' \
  | while read -r s; do
      ls data/labels/"${s}"_overpass_solar*.parquet >/dev/null 2>&1 || echo "$s"
    done
}

waited=0
while [ -n "$(pending)" ] && [ "$waited" -lt "$MAX_WAIT_S" ]; do
  sleep 60; waited=$((waited + 60))
done

P="$(pending)"
if [ -n "$P" ]; then
  echo "$(date -Is) ABORT: not starting the sub-400 chain -- these quadrats still have no pull:"
  echo "$P" | sed 's/^/  /'
  echo "Re-run scripts/finish_quadrat_registrations.sh once Overpass recovers, then this."
  echo SUB400_NOT_STARTED
  exit 1
fi

echo "$(date -Is) all quadrats have pulls (waited ${waited}s); starting the sub-400 chain"
ls data/labels/*_calib_*_boundary.geojson | sed 's|.*/||;s|_boundary.geojson||' | sed 's/^/  /'
exec bash scripts/run_sub400_fraction_roofclf.sh
