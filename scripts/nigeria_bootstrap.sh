#!/usr/bin/env bash
# Nigeria: wait for the VIDA NGA download, then pull the national OSM solar labels.
#
# The two are chained rather than run in parallel because the chunked Overpass script
# finishes with `classify_placement`, which needs data/vida/NGA.parquet -- without it
# the placement lookup falls back to a remote row-group scan of an 8.6 GB parquet over
# a 745 KB/s link.
#
# A country-scale Overpass pull MUST be chunked: a single national query times out on
# every public mirror (CLAUDE.md / docs/results/zambia.md), and the national boundary
# clip matters, since a bbox around Nigeria also holds slabs of Niger, Chad, Cameroon
# and Benin.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
LOG=data/nigeria_bootstrap.log
say() { echo "$(date '+%F %T') BOOTSTRAP: $*" | tee -a "$LOG"; }

while systemctl --user is-active --quiet earthpv-vida-nga; do
  say "waiting for VIDA NGA ($(stat -c%s /home/tobi/earthpv_data/NGA.parquet.part 2>/dev/null || echo 0) bytes)"
  sleep 120
done
if [ ! -s data/vida/NGA.parquet ]; then
  say "FAILED: VIDA NGA download did not produce data/vida/NGA.parquet"; exit 1
fi
say "VIDA NGA ready: $(stat -Lc%s data/vida/NGA.parquet) bytes"

# 5x5 rather than Zambia's 4x4: Nigeria's bbox is a similar size but holds far more
# OSM, and the cost of an Overpass tile is the area scanned.
say "starting chunked Overpass pull"
$PY scripts/overpass_labels_chunked.py \
  --bbox 2.668,4.24,14.68,13.893 --iso3 NGA --name nigeria --tiles 5x5 >> "$LOG" 2>&1
rc=$?
say "overpass pull rc=$rc"
exit $rc
