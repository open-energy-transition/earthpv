#!/usr/bin/env bash
# Run 2 of the quadrat-supervision experiment: same recipe, karachi_coast_calib_700m held
# out. Waits for the all-13 run to release the GPU first -- a single GTX 1060 (6 GB) cannot
# hold two of these, and the project has already lost a multi-hour job to an OOM kill.
set -euo pipefail
cd /run/media/tobi/aidisc/earthpv

while systemctl --user is-active --quiet earthpv-fraction-quadrats-train; do sleep 60; done
echo "$(date -Is) all-13 run finished; starting holdout run"

exec .pixi/envs/ml/bin/python -m earthpv.cli train \
  --config configs/terramind_pv_fraction_pakistan_quadrats_holdout_karachi.yaml
