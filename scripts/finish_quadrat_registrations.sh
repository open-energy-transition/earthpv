#!/usr/bin/env bash
# Keep retrying the pending quadrat registrations until none are left, then report.
#
# Overpass was heavily degraded on 2026-08-05 (429s, then 504/502/connect-timeout across all
# three mirrors), and a registration is worthless unless its pull is whole -- so the answer is
# patience, not pressure. Long gaps between passes on purpose: retrying hard is what produced
# the 429s in the first place, and the partial-response failure mode lives precisely in the
# slow mirrors that rate-limiting pushes you onto.
set -uo pipefail
cd /run/media/tobi/aidisc/earthpv
PASSES=${PASSES:-6}
PASS_GAP_S=${PASS_GAP_S:-300}

pending() {
  ls data/labels/*_calib_*_boundary.geojson 2>/dev/null | sed 's|.*/||;s|_boundary.geojson||' \
  | while read -r s; do
      ls data/labels/"${s}"_overpass_solar*.parquet >/dev/null 2>&1 || echo "$s"
    done
}

for i in $(seq 1 "$PASSES"); do
  P="$(pending)"
  if [ -z "$P" ]; then
    echo "$(date -Is) nothing pending after $((i-1)) pass(es)"
    break
  fi
  echo "=== $(date -Is) pass $i/$PASSES; still pending: $(echo "$P" | tr '\n' ' ')"
  GAP_S=90 bash scripts/register_pending_quadrats_20260805.sh 2>&1 \
    | grep -aE "====|installations inside|already registered|confirming query sees|UNVERIFIED|FAILED|NEEDS RETRY|all registrations"
  P="$(pending)"
  [ -z "$P" ] && { echo "$(date -Is) all registered on pass $i"; break; }
  [ "$i" -lt "$PASSES" ] && { echo "$(date -Is) sleeping ${PASS_GAP_S}s before pass $((i+1))"; sleep "$PASS_GAP_S"; }
done

echo "=== $(date -Is) FINAL REGISTRATION STATE ==="
P="$(pending)"
if [ -z "$P" ]; then echo "ALL_REGISTERED"; else echo "STILL_PENDING: $(echo "$P" | tr '\n' ' ')"; fi
ls data/labels/*_calib_*_boundary.geojson | sed 's|.*/||;s|_boundary.geojson||' | while read -r s; do
  n=$(ls data/labels/"${s}"_overpass_solar*.parquet 2>/dev/null | tail -1)
  [ -n "$n" ] && echo "  OK   $s" || echo "  PEND $s"
done
echo REGISTRATION_LOOP_DONE
