#!/usr/bin/env bash
# Run all 5 folds of the fraction-head quadrat-supervision k-fold retrain sequentially.
# A single GTX 1060 (6 GB) cannot hold two training runs at once, and this project has
# already lost a multi-hour job to an OOM kill from trying -- so this is one process,
# one fold at a time, not 5 concurrent systemd units.
set -euo pipefail
cd /run/media/tobi/aidisc/earthpv

for fold in 0 1 2 3 4; do
  echo "$(date -Is) starting fold $fold"
  .pixi/envs/ml/bin/python -m earthpv.cli train \
    --config "configs/terramind_pv_fraction_kfold${fold}.yaml"
  echo "$(date -Is) fold $fold done"
done

echo "$(date -Is) all 5 folds done"
