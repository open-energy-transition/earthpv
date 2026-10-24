#!/usr/bin/env bash
# Train the matched-grid THOR control (configs/thor_pv_ps16m_south_africa.yaml) AFTER the
# ps8 run of scripts/run_backbone_compare.sh, so the two never share the GPU: waits for the
# ps8 marker (or gives up if the main unit dies first), then trains and writes its own marker.
#
#   systemd-run --user --unit earthpv-thor-compare-matched --property=MemoryMax=16G \
#       --property=Restart=on-abnormal --property=RestartSec=120 \
#       --working-directory="$PWD" bash scripts/run_backbone_compare_matched.sh
set -uo pipefail
cd "$(dirname "$0")/.."
M=data/backbone_compare_markers
mkdir -p $M
export PYTHONUNBUFFERED=1 GDAL_CACHEMAX=128
if [[ -f $M/ps16m_done ]]; then echo "$(date '+%F %T') skip ps16m (done)"; exit 0; fi
until [[ -f $M/ps8_done ]]; do
  if ! systemctl --user is-active --quiet earthpv-thor-compare; then
    sleep 300  # the main unit may be in its RestartSec window
    if [[ ! -f $M/ps8_done ]] && ! systemctl --user is-active --quiet earthpv-thor-compare; then
      echo "$(date '+%F %T') main unit inactive without ps8_done; not starting ps16m"; exit 3
    fi
  fi
  sleep 120
done
echo "$(date '+%F %T') start ps16m"
.pixi/envs/ml/bin/python -m earthpv.cli train --config configs/thor_pv_ps16m_south_africa.yaml \
    > data/backbone_compare_ps16m.log 2>&1
rc=$?
echo "$(date '+%F %T') done ps16m rc=$rc"
[[ $rc -eq 0 ]] && touch $M/ps16m_done
exit $rc
