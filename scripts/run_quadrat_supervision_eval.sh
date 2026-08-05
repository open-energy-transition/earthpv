#!/usr/bin/env bash
# Evaluate both runs of the quadrat-supervision experiment, one after the other.
#
# The pair is the whole point: `quad13` scores karachi_coast in-sample, `quadho` scores the
# same box out-of-sample, so the difference between them separates a generalising gain from
# memorisation of 13 specific places. Sequential, never concurrent -- a single GTX 1060
# (6 GB) cannot hold two inference passes and this project has already lost a multi-hour job
# to an OOM kill.
#
# Best checkpoints by the national val/RMSE the configs monitor (not `last.ckpt`).
set -euo pipefail
cd /run/media/tobi/aidisc/earthpv

scripts/eval_fraction_quadrat_model.sh quad13 \
  'data/models/fraction_pakistan_quadrats/terramind-pv-epoch=56-step=41838.ckpt'

scripts/eval_fraction_quadrat_model.sh quadho \
  'data/models/fraction_pakistan_quadrats_holdout_karachi/terramind-pv-epoch=32-step=24024.ckpt'

echo "ALL_EVAL_DONE"
