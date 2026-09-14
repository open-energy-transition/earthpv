#!/usr/bin/env bash
# Rebuild Germany and France with NO building-density filter on the imagery.
#
# WHY. Both countries were composed at `--min-buildings 1000`, so `density` only ever saw
# cells above that threshold and the register comparisons are scoped to the municipalities
# that grid reaches -- Germany 99.75% of registered rooftop capacity (96.2% of Gemeinden),
# France 93.0% (77.1% of communes). The atlases' OSM side was un-filtered on 2026-09-13
# (`--include-offgrid-osm`), but the MODEL side still stopped at the threshold. This
# removes that too, by composing every building-populated cell and re-running the chain.
#
# SCALE (measured 2026-09-13 from the VIDA building histogram, cells of 0.1 deg):
#   Germany  4,844 populated cells total; 4,656 already built ->   188 new  (~3 h)
#   France   6,461 populated cells total; 5,473 already built ->   988 new  (~16 h)
# The threshold only ever excluded very sparse cells, which is exactly why capacity
# coverage was already 99.75%/93.0%. Expect the German numbers to barely move and the
# French ones to move more -- France's uncovered communes are the small rural ones, where
# below-floor residential PV concentrates.
#
# ORDER. Waits for the Zambia compose to finish first: that is the owner's primary run and
# the ~6 MB/s link is the binding constraint for all three (see the compose-bandwidth
# note in CLAUDE.md). Germany goes first because it is 5x smaller.
#
#   systemd-run --user --collect --unit=earthpv-de-fr-nofilter \
#     -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=26G \
#     bash scripts/run_de_fr_nofilter.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
LOG=data/de_fr_nofilter.log
MARK=data/de_fr_nofilter_markers
mkdir -p "$MARK"
say(){ echo "$(date '+%F %T') NOFILTER: $*" | tee -a "$LOG"; }

step(){ # step <marker> <command...>
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m")"; return 0; fi
  say "start $(basename "$m")"
  "$@" >> "$LOG" 2>&1; local rc=$?
  # check-density exits non-zero on a plausibility failure, which is a finding to read,
  # not a reason to abandon a multi-hour chain (CLAUDE.md, "Plausibility gate").
  case "$(basename "$m")" in check_*) ;; *) [ $rc -ne 0 ] && { say "FAILED $(basename "$m") rc=$rc"; exit $rc; };; esac
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}

compose_all(){ # compose_all <aoi> <extra args>
  local aoi=$1; shift
  bash scripts/compose_loop.sh "$aoi" 0 1 4 3600 600 "$*"
}

# ---------------------------------------------------------------- wait for Zambia
while systemctl --user is-active --quiet earthpv-compose-zambia; do
  say "waiting for the Zambia compose ($(find data/composites/zambia/composites -name composite_0.tif 2>/dev/null | wc -l) cells)"
  sleep 600
done
say "Zambia compose finished; starting Germany"

# ---------------------------------------------------------------- Germany (v4, no window in aoi.yaml)
# The window MUST be stated: Germany has no `compose_window`, and the compose default is a
# Punjab dry season (German winter). 2025-04-01:2025-09-30 is the epoch the existing 4,656
# cells were built on and matches the MaStR 2025-09-30 register cutoff.
DE_CKPT="data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt"
step de_compose   compose_all germany --use-vida --window 2025-04-01:2025-09-30
step de_infer     $MLPY -m earthpv.cli infer --aoi germany --checkpoint "$DE_CKPT"
step de_post      $PY -m earthpv.cli postprocess --aoi germany --threshold 0.3
step de_calib     $PY -m earthpv.cli calibrate-candidates --aoi germany \
                     --mastr-p-unmapped results/germany_mastr_p_unmapped.csv
step de_density   $PY -m earthpv.cli density --aoi germany --districts --force
step check_de     $PY -m earthpv.cli check-density --aoi germany
# The filter-free measurement itself: coverage_frac/coverage_capacity_frac in this output
# are what the "measured over N% of registered capacity" caveat quotes.
step de_validate  $PY -m earthpv.cli validate-mastr --aoi germany \
                     --solar-path data/labels/germany_national_osm_solar.parquet
step de_atlas     $PY -m earthpv.cli atlas --aoi germany \
                     --osm-solar data/labels/germany_national_osm_solar.parquet \
                     --sub400-central-cells data/roofclf_national_germany_prod/germany/density/sub400_central_incremental_buildings.parquet \
                     --sub400-low-cells data/roofclf_national_germany_prod/germany/density/sub400_low_incremental_buildings.parquet \
                     --include-offgrid-osm \
                     --out docs/assets/interactive/germany_pv_evidence_atlas.html

# ---------------------------------------------------------------- France (v5, own pred-dir)
FR_CKPT="data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt"
FR_PRED=data/predictions_v5
step fr_compose   compose_all france
step fr_infer     $MLPY -m earthpv.cli infer --aoi france --checkpoint "$FR_CKPT" --out-dir "$FR_PRED"
step fr_post      $PY -m earthpv.cli postprocess --aoi france --pred-dir "$FR_PRED" --threshold 0.3
# `--recall-reference none` is France's documented setting: its only exhaustive ground truth
# is sub-400 m2 (the 14 hand-mapped communes) against a >= 400 m2 candidate population, so
# measuring recall there manufactures a large, badly-determined correction and trips the 20x
# DEFAULT_RECALL_FLOOR clamp. Keeps France a precision-honest floor, as published.
step fr_calib     $PY -m earthpv.cli calibrate-candidates --aoi france --pred-dir "$FR_PRED" \
                     --recall-reference none
step fr_density   $PY -m earthpv.cli density --aoi france --pred-dir "$FR_PRED" --districts --force
step check_fr     $PY -m earthpv.cli check-density --aoi france --pred-dir "$FR_PRED"
step fr_validate  $PY -m earthpv.cli validate-france --pred-dir "$FR_PRED"
step fr_atlas     $PY -m earthpv.cli atlas --aoi france --pred-dir "$FR_PRED" \
                     --osm-solar data/labels/france_national_osm_solar.parquet \
                     --include-offgrid-osm \
                     --out results/france_pv_evidence_atlas.html

say "ALL DONE -- re-read coverage_frac / coverage_capacity_frac in"
say "  results/germany_mastr_validation.json and results/france_validation*/france_validation.json"
say "  and update the coverage-basis sentence to the new values."
