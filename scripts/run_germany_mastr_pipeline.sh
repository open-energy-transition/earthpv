#!/usr/bin/env bash
# Germany MaStR validation chain: waits for the earthpv-compose-germany unit, then runs
# infer -> postprocess -> calibrate-candidates -> density -> check-density -> validate-mastr.
#
# Launched 2026-08-23 as systemd unit earthpv-germany-mastr (see logs/germany_mastr_chain.log).
# Checkpoint: v4_combined_all epoch=41 -- the documented v3_combined_india production
# checkpoint is no longer on disk (owner-approved substitution, 2026-08-23); the result must
# be documented as v4-based. Composites: data/composites/germany -> /home/tobi (symlink),
# window 2025-04-01:2025-09-30 (matches germany_500 training imagery AND the MaStR cutoff).
set -euo pipefail
cd "$(dirname "$0")/.."

CKPT="data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt"
SOLAR="/run/media/tobi/aidisc/rooftopsenti/data/germany_500/osm/solar.parquet"
COMPOSITES="data/composites/germany/composites"
MIN_CELLS=4200   # ~90% of the 4,664 selected cells; below this, compose needs a re-run first

log() { echo "$(date '+%F %T') [chain] $*"; }

log "waiting for earthpv-compose-germany to finish..."
# The compose unit runs with Restart=on-failure (it died once on fd exhaustion,
# 2026-08-23), so "activating" (the auto-restart window) still counts as running.
while :; do
  state=$(systemctl --user show earthpv-compose-germany -p ActiveState --value 2>/dev/null || echo inactive)
  case "$state" in active|activating|reloading|deactivating) sleep 300 ;; *) break ;; esac
done

n=$(find "$COMPOSITES" -name composite_0.tif 2>/dev/null | wc -l)
log "compose unit inactive; $n composites on disk"
if [ "$n" -lt "$MIN_CELLS" ]; then
  log "FEWER THAN $MIN_CELLS composites -- compose likely died early. Re-run (resumable):"
  log "  systemd-run --user --unit earthpv-compose-germany --working-directory=$PWD \\"
  log "    bash -c '.pixi/envs/default/bin/python -m earthpv.cli compose --aoi germany --use-vida --workers 5 --window 2025-04-01:2025-09-30 >> logs/compose_germany.log 2>&1'"
  log "then relaunch this chain. Aborting."
  exit 1
fi

log "stage: infer (GPU, ~3.4 s/cell, resumable)"
.pixi/envs/ml/bin/python -m earthpv.cli infer --aoi germany --checkpoint "$CKPT"

log "stage: postprocess"
.pixi/envs/default/bin/python -m earthpv.cli postprocess --aoi germany --threshold 0.3

log "stage: calibrate-candidates (by-placement default; germany table is interim mapped-only)"
.pixi/envs/default/bin/python -m earthpv.cli calibrate-candidates --aoi germany

log "stage: density (--force: fingerprint changed vs the PRE_mgrs snapshot era)"
.pixi/envs/default/bin/python -m earthpv.cli density --aoi germany --districts --force

log "stage: check-density (plausibility gate; non-fatal here, verdict recorded for review)"
if .pixi/envs/default/bin/python -m earthpv.cli check-density --aoi germany; then
  log "check-density: PASS"
else
  log "check-density: FAILED (exit $?) -- review before publishing; validate-mastr still runs"
fi

log "stage: validate-mastr"
.pixi/envs/default/bin/python -m earthpv.cli validate-mastr --aoi germany --solar-path "$SOLAR"

log "chain complete -- results/germany_mastr_validation.json"
