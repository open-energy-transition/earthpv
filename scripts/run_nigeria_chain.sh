#!/usr/bin/env bash
# Nigeria, end to end: wait for its inputs and for the link to be free, compose, then run
# the segmentation half of the main workflow.
#
# YIELDING TO FRANCE. `earthpv-de-fr-nofilter` is rebuilding France with no density filter
# and its compose is the bandwidth-heavy stage; the ~6 MB/s link is the binding constraint
# for both runs (CLAUDE.md, "compose is bandwidth-bound"), so running them together would
# just split it and finish neither sooner. This waits on the `fr_compose` MARKER rather
# than on the whole DE/FR unit, because everything after it in that chain (infer,
# postprocess, density) is GPU/CPU-bound and can overlap with Nigeria's compose freely.
# The same courtesy that script extends to the Zambia run in its own header.
#
#   systemd-run --user --collect --unit=earthpv-nigeria-chain \
#     -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=20G \
#     bash scripts/run_nigeria_chain.sh
set -uo pipefail
cd "$(dirname "$0")/.."
AOI=nigeria
CKPT=data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt
FR_MARKER=data/de_fr_nofilter_markers/fr_compose
LOG=data/nigeria_chain.log
say(){ echo "$(date '+%F %T') CHAIN: $*" | tee -a "$LOG"; }

# ---- inputs -------------------------------------------------------------------------
while systemctl --user is-active --quiet earthpv-vida-nga; do
  say "waiting for VIDA NGA ($(stat -c%s /home/tobi/earthpv_data/NGA.parquet.part 2>/dev/null || echo 0) bytes)"
  sleep 300
done
[ -s data/vida/NGA.parquet ] || { say "FAILED: no data/vida/NGA.parquet"; exit 1; }
say "VIDA NGA ready"

# The labels pull (earthpv-nigeria-bootstrap) gates compose only loosely: `populated_cells`
# unions density-selected cells with cells holding an OSM solar polygon, and compose_loop
# re-runs that selection every pass, so a late labels file is picked up by the next pass
# rather than missed. Waiting anyway keeps the cell ORDER right -- label cells are
# composited first, so a partial run still has the whole mapped population imaged.
while systemctl --user is-active --quiet earthpv-nigeria-bootstrap; do
  say "waiting for the OSM labels pull"; sleep 300
done
if [ -s data/labels/${AOI}_overpass_solar.parquet ]; then
  say "labels ready: $(stat -c%s data/labels/${AOI}_overpass_solar.parquet) bytes"
else
  # Not fatal: a country with no mapped solar still composites and infers. It loses the
  # Verified tier and the label-first cell ordering, which the write-up must then state.
  say "WARNING: no labels parquet -- continuing without the mapped reference"
fi

# ---- yield to the France compose ----------------------------------------------------
while [ ! -f "$FR_MARKER" ] && systemctl --user is-active --quiet earthpv-de-fr-nofilter; do
  say "yielding to the France compose ($(find data/composites/france/composites -name composite_0.tif 2>/dev/null | wc -l) cells)"
  sleep 600
done
say "link free: France compose done (marker=$([ -f "$FR_MARKER" ] && echo yes || echo no), de_fr unit=$(systemctl --user is-active earthpv-de-fr-nofilter))"

# ---- compose ------------------------------------------------------------------------
# min_buildings 1000, as Zambia used. Workers 4, matching the concurrent France pass:
# the work is latency-bound, and each worker holds a cell's band stack in RSS.
# ITER_S 3600 caps each pass by WALL CLOCK -- a long-lived compose DEGRADES before it
# dies, and a degraded pass is indistinguishable from a healthy one from outside
# (CLAUDE.md). STALL_S 600 kills a pass that hangs instead.
# No --window: the AOI carries `compose_window`, which run_compose honours.
say "starting compose (min_buildings 1000)"
systemd-run --user --collect --unit=earthpv-compose-$AOI \
  -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=16G \
  bash scripts/compose_loop.sh $AOI 0 1000 4 3600 600
sleep 30
while systemctl --user is-active --quiet earthpv-compose-$AOI; do
  say "compose running ($(find data/composites/$AOI/composites -name composite_0.tif 2>/dev/null | wc -l) cells)"
  sleep 900
done
say "compose finished: $(find data/composites/$AOI/composites -name composite_0.tif 2>/dev/null | wc -l) cells"

# ---- the rest of the main workflow --------------------------------------------------
# Its own wait-for-compose loop is a no-op by now, which is correct.
exec bash scripts/run_nigeria_pipeline.sh "$CKPT"
