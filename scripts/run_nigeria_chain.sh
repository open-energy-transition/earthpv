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
# min_buildings 1000, as Zambia used. Workers 4. ITER_S 3600 caps each pass by WALL CLOCK
# (a long-lived compose DEGRADES before it dies, and a degraded pass looks healthy from
# outside); STALL_S 600 kills a pass that HANGS instead.
#
# STAC PROVIDER: left at the default (Planetary Computer first, Earth Search as
# fallback). Pinning EARTHPV_STAC_PROVIDER=earth-search was tried on 2026-09-17 when PC
# went degraded and MADE IT WORSE -- zero cells in 30 minutes against 428 from the
# default earlier the same morning. Measured cause: Earth Search's data bucket
# (sentinel-cogs, AWS us-west-2) was serving this machine at 11-23 kB/s across repeated
# samples, while a Cloudflare control pulled 1.56 MB/s and PC's STAC API answered in
# 0.3 s -- so the route to that one bucket was the problem, not the link and not PC.
# A single band COG is tens of MB, so at that rate a cell cannot finish at all.
# Set EARTHPV_STAC_PROVIDER in the environment to override; do not hardcode it here
# without measuring both providers first.
#
# COVERAGE GATE. compose_loop.sh exits on "no progress 3x", which cannot distinguish
# "every remaining cell has no scenes" from "the STAC provider is down". On 2026-09-17 it
# exited at 428 of 6,341 cells during a PC outage and this chain went straight on to
# infer, postprocess, export, screen and calibrate over 6.7% of Nigeria. A partial run
# that LOOKS complete is the worst outcome available here, so compose is now retried and,
# if it still cannot reach the bar, the chain FAILS rather than publishing a country from
# a fourteenth of its cells.
COVERAGE_MIN=97          # percent of selected cells that must be composited
MAX_ROUNDS=8             # retries; a real outage can outlast a few of these
ROUND_WAIT=1800          # seconds between rounds, so a transient outage can clear

selected_cells(){ grep -oE "Selected [0-9]+ cells" "data/compose_$AOI.log" 2>/dev/null | tail -1 | grep -oE "[0-9]+"; }
built_cells(){ find "data/composites/$AOI/composites" -name composite_0.tif 2>/dev/null | wc -l; }

for round in $(seq 1 $MAX_ROUNDS); do
  say "compose round $round/$MAX_ROUNDS (min_buildings 1000, provider ${EARTHPV_STAC_PROVIDER:-default PC-first})"
  systemd-run --user --collect --unit=earthpv-compose-$AOI \
    -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=16G \
    bash scripts/compose_loop.sh $AOI 0 1000 4 3600 600
  sleep 30
  while systemctl --user is-active --quiet earthpv-compose-$AOI; do
    say "compose running ($(built_cells) cells)"; sleep 900
  done
  sel=$(selected_cells); got=$(built_cells)
  if [ -z "$sel" ] || [ "$sel" -eq 0 ]; then
    say "FAILED: compose never logged a cell selection"; exit 1
  fi
  pct=$(( 100 * got / sel ))
  say "compose round $round finished: $got/$sel cells (${pct}%)"
  [ "$pct" -ge "$COVERAGE_MIN" ] && break
  if [ "$round" -lt "$MAX_ROUNDS" ]; then
    say "coverage below ${COVERAGE_MIN}% -- waiting ${ROUND_WAIT}s and retrying"
    sleep "$ROUND_WAIT"
  fi
done
sel=$(selected_cells); got=$(built_cells); pct=$(( 100 * got / sel ))
if [ "$pct" -lt "$COVERAGE_MIN" ]; then
  say "FAILED: compose reached only $got/$sel cells (${pct}%) after $MAX_ROUNDS rounds."
  say "Refusing to run the pipeline: a national atlas built from this would be a partial"
  say "country presented as a whole one. Fix the imagery source, then re-run this script."
  exit 1
fi
say "compose complete: $got/$sel cells (${pct}%)"

# ---- the rest of the main workflow --------------------------------------------------
# Its own wait-for-compose loop is a no-op by now, which is correct.
exec bash scripts/run_nigeria_pipeline.sh "$CKPT"
