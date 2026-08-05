#!/usr/bin/env bash
# One-off driver for the 2026-08-05 batch of quadrat registrations: the Peshawar West
# replacement plus four new Islamabad quadrats. Serial on purpose -- concurrent Overpass
# pulls invite the rate-limited partial response that nearly poisoned the Lahore box, and
# every pull here is cross-checked against a confirming query that also hits the same
# endpoints. Keep going past a failure so one bad endpoint does not cost the whole batch;
# the summary at the end is what says which ones need a retry.
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
CB=data/labels/calibration_boundaries
FAILED=()

# Pause between registrations. Each one now costs the endpoint up to three queries (the
# pull plus two confirming ones), and overpass-api.de answered 429 Too Many Requests part
# way through this very batch -- back-to-back registrations rate-limit themselves into the
# slow mirrors, which is exactly where the partial-response failure mode lives.
GAP_S=${GAP_S:-45}

# Idempotent: a quadrat is done when it has BOTH a boundary and a solar pull, which is
# exactly what `roofclf.discover_quadrats` requires. Re-running after a partial batch then
# costs nothing for the ones that succeeded and does not re-hit Overpass for them. FORCE=1
# re-pulls everything.
reg() {  # reg <name> <size-tag> <geojson-stem>
  local stem="$1_calib_$2"
  if [ "${FORCE:-0}" != "1" ] \
     && [ -f "data/labels/${stem}_boundary.geojson" ] \
     && compgen -G "data/labels/${stem}_overpass_solar*.parquet" > /dev/null; then
    echo "=== $(date -Is)  $stem: already registered, skipping"
    return
  fi
  echo "=================== $(date -Is)  $stem  ==================="
  if ! "$PY" scripts/new_calibration_quadrat.py --name "$1" --size-tag "$2" \
        --geojson "$CB/$3.geojson" --retries 3 --retry-wait-s 90; then
    echo "!!! FAILED: $stem"
    FAILED+=("$stem")
  fi
  sleep "$GAP_S"
}

# Replacement: fully contains peshawar_west_calib_1500m, which is already retired.
reg peshawar_west 4p39km2 peshawar

# Four new, mutually non-overlapping diamonds around Islamabad (~2.79 km2 each).
# Note the source filename for north is "4-quad-noth" (sic) as supplied.
reg islamabad_north 2p79km2 4-quad-noth
reg islamabad_east  2p79km2 4-quad-east
reg islamabad_south 2p79km2 4-quad-south
reg islamabad_west  2p79km2 4-quad-west

# Sukkur, Sindh. Note the supplied filename is "sakkur" (sic); the quadrat is named for the
# city's usual spelling. Unlike the four above, its bbox fits inside one 2,240 m chip.
reg sukkur 2p63km2 sakkur

# Karachi coastal: replaces karachi_coast_calib_700m (already retired). NOT a strict
# superset -- 8.6% of the old box falls outside this boundary -- but that sliver holds zero
# mapped installations, so no ground truth is lost. Rule-1 status was withdrawn by the owner
# for the extended area; set rule1_complete=False wherever it is recorded.
reg karachi_coast 2p16km2 karachi_coast

# SITE Karachi industrial: replaces site_karachi_calib_1km (already retired), fully contains
# it, 0 installations lost.
reg site_karachi 4p14km2 karachi_industrial

# Rahim Yar Khan: replaces rahim_yar_khan_calib_1km (already retired), fully contains it,
# 0 installations lost. Source filename happens to match the OLD stem -- it is the new
# boundary, not the retired one.
reg rahim_yar_khan 2p06km2 rahim_yar_khan_calib_1km

echo "=================== $(date -Is) summary ==================="
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "all registrations succeeded"
else
  printf 'NEEDS RETRY: %s\n' "${FAILED[@]}"
fi
echo BATCH_DONE
