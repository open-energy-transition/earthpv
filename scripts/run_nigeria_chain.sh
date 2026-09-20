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
# outside); STALL_S kills a pass that HANGS instead -- see PC PATIENCE below for why both
# it and the Planetary Computer patience are set here rather than left at their defaults.
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
# PC PATIENCE AND THE STALL WATCHDOG, both raised 2026-09-20 after this run LIVELOCKED.
# It ran at ~35 cells/h to 2,340 of 6,341 cells and then produced exactly zero for 17
# hours, across ten rounds, while the link stayed saturated at 6.3 MB/s. Neither the
# provider nor the imagery was at fault: a direct test of three missing cells the same
# morning composited two of them (47.8 s via PC in the north, 297.8 s via Earth Search
# mid-country) and refused the third for real (99% empty, southern cloud).
#
# The cause is the death spiral imagery.py's `_PROVIDER_OVERRIDE` comment already
# describes, entered from the other side. `PC_TIMEOUT_S` defaults to 60 s, which is a
# SINGLE-CELL number; a cell is bandwidth-bound at ~290 MB against a ~380 MB/min link,
# so under 4 workers a perfectly healthy cell takes ~4x its uncontended 48-53 s and
# EVERY cell trips the patience. Each hand-off then downloads the cell TWICE, because
# the abandoned PC attempt keeps reading in the background, and the halved throughput
# pushes the next cells over the timeout too. Raising the patience to several times the
# expected per-cell wall time is exactly what that comment prescribes; it still catches
# a genuinely stuck cell.
#
# STALL_S compounded it rather than causing it. At 600 s the watchdog killed every pass
# before a single contended cell could land -- a pass needs 4-5 minutes just to fetch
# VIDA, select cells and skip the 2,340 already on disk, leaving under five minutes of
# real work -- so the loop hit "no progress 3x", exited, and the round loop paid its
# 1,800 s provider cooldown for a provider that was never down. 2,400 s leaves room for
# a slow cell without letting a true hang cost the whole hour.
PC_TIMEOUT_S=600
STALL_S=2400
COVERAGE_MIN=97          # percent of selected cells that must be composited
# MAX_ROUNDS was 8, which was sized for a transient outage and WRONG for the job: eight
# rounds of an hour plus 30-minute waits is about eight hours of patience, while a
# country-scale compose at ~0.6 cells/min needs days. Nigeria hit it at 2,340 of 6,341
# cells (36%) on 2026-09-19 and would have exited with a correct refusal that simply
# stopped a run needing to continue. The gate's job is to stop a PARTIAL COUNTRY reaching
# the pipeline, not to double as a wall clock, so the budget is now roughly a week.
# scripts/run_france_national_compose.sh had this right: budget generously and let "a pass
# added nothing" be the stop condition.
MAX_ROUNDS=200
ROUND_WAIT=1800          # seconds to wait AFTER AN UNPRODUCTIVE ROUND, so an outage can clear
ROUND_PROGRESS_MIN=20    # cells; below this a round counts as unproductive and earns the wait

selected_cells(){ grep -oE "Selected [0-9]+ cells" "data/compose_$AOI.log" 2>/dev/null | tail -1 | grep -oE "[0-9]+"; }
built_cells(){ find "data/composites/$AOI/composites" -name composite_0.tif 2>/dev/null | wc -l; }

for round in $(seq 1 $MAX_ROUNDS); do
  before=$(built_cells)
  say "compose round $round/$MAX_ROUNDS (min_buildings 1000, provider ${EARTHPV_STAC_PROVIDER:-default PC-first}), at $before cells"
  systemd-run --user --collect --unit=earthpv-compose-$AOI \
    -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=16G \
    --setenv=EARTHPV_PC_TIMEOUT_S=$PC_TIMEOUT_S \
    bash scripts/compose_loop.sh $AOI 0 1000 4 3600 $STALL_S
  sleep 30
  while systemctl --user is-active --quiet earthpv-compose-$AOI; do
    say "compose running ($(built_cells) cells)"; sleep 900
  done
  sel=$(selected_cells); got=$(built_cells)
  if [ -z "$sel" ] || [ "$sel" -eq 0 ]; then
    say "FAILED: compose never logged a cell selection"; exit 1
  fi
  pct=$(( 100 * got / sel ))
  gained=$(( got - before ))
  say "compose round $round finished: $got/$sel cells (${pct}%), +$gained this round"
  [ "$pct" -ge "$COVERAGE_MIN" ] && break
  if [ "$round" -lt "$MAX_ROUNDS" ]; then
    # Only pay the cooldown when the round achieved nothing, which is the signature of a
    # provider outage. A round that is simply not finished yet should restart at once:
    # at 200 rounds an unconditional 30-minute wait would burn four days doing nothing.
    if [ "$gained" -lt "$ROUND_PROGRESS_MIN" ]; then
      say "round added only $gained cells -- waiting ${ROUND_WAIT}s for the provider"
      sleep "$ROUND_WAIT"
    fi
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
