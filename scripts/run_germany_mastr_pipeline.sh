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
UNIT=earthpv-compose-germany
MIN_CELLS=4200                          # ~90% of the 4,664 selected cells
POLL=${POLL:-300}                       # seconds between checks
DOWN_GRACE=${DOWN_GRACE:-21600}         # 6 h of compose being down AND making no progress

log() { echo "$(date '+%F %T') [chain] $*"; }

# --- wait for compose -------------------------------------------------------------------
# The unit going inactive is NOT proof that compose finished. It also goes inactive when it
# is stopped deliberately for maintenance (the fd-limit fix on 2026-08-29) or lands in
# `failed`. The original guard broke out of the wait loop on any inactive state and then
# aborted on the < MIN_CELLS check, which killed the chain and cost a manual relaunch.
#
# So: judge completion by composites on disk, and treat "unit down but still short" as a
# reason to KEEP WAITING rather than to abort. Give up only after DOWN_GRACE elapses with
# the unit down and no new composites appearing -- new composites reset the timer, so a
# restart (or a manual foreground run) is picked up automatically.
#
# Tradeoff, deliberate: if compose is stopped for maintenance once it is already past
# MIN_CELLS, the chain proceeds rather than waiting for the restart. MIN_CELLS is by
# definition "enough composites to run the chain on", so that is the intended reading --
# but stop the CHAIN before compose if you are doing maintenance late in the run.
log "waiting for $UNIT to finish (poll ${POLL}s, give up after $((DOWN_GRACE / 3600))h of stalled downtime)..."
down_since=0
last_n=-1
while :; do
  state=$(systemctl --user show "$UNIT" -p ActiveState --value 2>/dev/null || echo inactive)
  n=$(find "$COMPOSITES" -name composite_0.tif 2>/dev/null | wc -l)

  case "$state" in
    active|activating|reloading|deactivating)
      # running, or inside the Restart=on-failure window
      down_since=0
      ;;
    *)
      if [ "$n" -ge "$MIN_CELLS" ]; then
        log "compose done: unit $state, $n composites on disk (>= $MIN_CELLS)"
        break
      fi
      now=$(date +%s)
      if [ "$n" -gt "$last_n" ]; then
        down_since=0                    # still producing -- a restart is in flight
      elif [ "$down_since" -eq 0 ]; then
        down_since=$now
        log "compose is $state at $n/$MIN_CELLS composites -- waiting for it to resume"
      elif [ $((now - down_since)) -ge "$DOWN_GRACE" ]; then
        log "compose $state for $(((now - down_since) / 3600))h with no new composites ($n < $MIN_CELLS). Re-run (resumable):"
        log "  systemd-run --user --unit $UNIT --working-directory=$PWD \\"
        log "    --property=Restart=on-failure --property=LimitNOFILE=65536:65536 \\"
        log "    bash -c '.pixi/envs/default/bin/python -m earthpv.cli compose --aoi germany --use-vida --workers 5 --window 2025-04-01:2025-09-30 >> logs/compose_germany.log 2>&1'"
        log "  (LimitNOFILE must be the soft:hard PAIR -- a bare 65536 sets only the hard"
        log "   limit, leaves the soft limit at 1024, and compose dies on 'Too many open files')"
        log "then relaunch this chain. Aborting."
        exit 1
      fi
      ;;
  esac

  last_n=$n
  sleep "$POLL"
done

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
