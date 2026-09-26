#!/usr/bin/env bash
# Everything downstream of compose for one new country, with a LOCALIZED segmentation
# checkpoint: chips -> merge -> train -> pick -> compare against v5 -> infer with the
# winner -> the segmentation-only evidence-atlas chain. Behind marker files, so a killed
# run resumes at the step it stopped on.
#
# Generalises scripts/run_nigeria_pipeline.sh, adding the retrain the owner asked for on
# 2026-09-23 ("always localize the segmentation by training with local data labels").
# Compose is NOT here: scripts/run_vn_in_queue.sh owns the network lane and writes the
# markers this script waits on.
#
#   systemd-run --user --collect --unit=earthpv-<aoi>-compute -p WorkingDirectory="$PWD" \
#     -p LimitNOFILE=65536:65536 -p MemoryMax=14G bash scripts/run_country_compute.sh <aoi>
#
# Per-country settings live in the `case` below. Two modes:
#   vietnam  chips/train once Vietnam's compose is finished, then the whole chain.
#   india    chips/train at a TRAINING MILESTONE (every label cell plus >= 3,000 density
#            cells composited, written by the queue), then inference runs INCREMENTALLY
#            every 6 h behind the still-running compose, and the downstream chain runs
#            once compose is finished. National India is weeks of compose on this link;
#            training does not need to wait for all of it, only for real background chips
#            (Zambia's v7 was built too early and had zero).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
AOI=${1:?usage: run_country_compute.sh <vietnam|india>}
V5=data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt
QMARK=data/vn_in_queue_markers
MARK=data/${AOI}_pipeline_markers
LOG=data/${AOI}_pipeline.log
GPU_LOCK=data/.gpu.lock
LABELS=data/labels/${AOI}_overpass_solar.parquet
OSM=data/labels/${AOI}_national_osm_solar.parquet
mkdir -p "$MARK" "$QMARK" results

case "$AOI" in
  vietnam)
    MODEL_TAG=v9_combined_vietnam; CONFIG=configs/terramind_pv_v9_vietnam.yaml
    BASE_CORPUS="germany punjab pakistan gujarat france"
    DATE_RANGE="Sep 2025 - Aug 2026"
    START_MARKER=$QMARK/vietnam_compose_done
    INCREMENTAL=0 ;;
  india)
    MODEL_TAG=v10_combined_india; CONFIG=configs/terramind_pv_v10_india.yaml
    # gujarat DROPPED: national India chips cover it (see configs/terramind_pv_v10_india.yaml)
    BASE_CORPUS="germany punjab pakistan france"
    DATE_RANGE="Nov 2025 - Mar 2026"
    START_MARKER=$QMARK/india_train_ready
    INCREMENTAL=1 ;;
  *) echo "unknown AOI $AOI"; exit 2 ;;
esac
COMPOSE_DONE=$QMARK/${AOI}_compose_done
ALT=data/predictions_alt   # the losing checkpoint's diagnostic run

say() { echo "$(date '+%F %T') COMPUTE[$AOI]: $*" | tee -a "$LOG"; }
# One GPU job at a time across both countries (flock), and none while a FOREIGN job holds
# the card: a 6 GB GTX 1060 cannot fit two trainings. "Foreign" = a compute process using
# over 1 GB, because the desktop (nautilus, ptyxis, loupe) keeps small GPU contexts open
# permanently and a plain "any compute app" test would wait forever.
#
# A concurrent session's Nigeria retrain (earthpv-nigeria-localize, launched 2026-09-23)
# trains and infers WITHOUT this lock, so while that unit is alive this also yields to it,
# for at most GPU_YIELD_MAX_S, so a stuck foreign unit cannot park this run forever.
GPU_YIELD_UNITS="earthpv-nigeria-localize"
GPU_YIELD_MAX_S=172800
gpu() {
  local waited=0 u busy
  while :; do
    busy=""
    for u in $GPU_YIELD_UNITS; do systemctl --user is-active --quiet "$u" && busy=$u; done
    [ -z "$busy" ] || [ "$waited" -ge "$GPU_YIELD_MAX_S" ] && break
    say "GPU step waiting for $busy (${waited}s so far)"; sleep 1800; waited=$((waited + 1800))
  done
  flock "$GPU_LOCK" bash -c '
    while nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null \
          | awk "\$1 > 1024 {f=1} END {exit !f}"; do
      echo "$(date "+%F %T") GPU busy with a foreign job; waiting" >&2; sleep 300
    done
    exec "$@"' _ "$@"
}

step() {  # step <marker> <command...>
  local m="$MARK/$1"; shift
  if [ -f "$m" ]; then say "skip $(basename "$m") (done)"; return 0; fi
  say "start $(basename "$m"): $*"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  # check-density exits 1 when a region fails its plausibility check: a finding to read,
  # not a reason to abandon the run (CLAUDE.md, "Plausibility gate").
  if [ $rc -ne 0 ] && [ "$(basename "$m")" != "check_density" ]; then
    say "FAILED $(basename "$m") rc=$rc"; exit $rc
  fi
  say "done $(basename "$m") rc=$rc"; echo "$rc" > "$m"
}

# ---- wait for imagery ------------------------------------------------------------------
while [ ! -f "$START_MARKER" ]; do
  say "waiting for $(basename "$START_MARKER") ($(find -L data/composites/$AOI/composites -name composite_0.tif 2>/dev/null | wc -l) cells composited)"
  sleep 1800
done
say "imagery ready: $(find -L data/composites/$AOI/composites -name composite_0.tif | wc -l) cells"

# ---- localized training -----------------------------------------------------------------
step chips $PY -m earthpv.cli chips --aoi $AOI
# Train chips in the one-cell ring around the holdout could see val installations through
# their window; relabel them `buffer` so neither side of the comparison is in-sample.
step val_buffer $PY scripts/mark_val_buffer.py --aoi $AOI

# The val split is geographic (`val_tiles`). Refuse to train on a corpus whose holdout
# came out too small to score -- datamodule.py would silently fall back to a random 20%
# split, and compare_local_vs_v5.py would then score v5 on chips the local model trained on.
if [ ! -f "$MARK/chips_checked" ]; then
  read -r NTRAIN NVAL NPOS < <($PY -c "
import pandas as pd
d = pd.read_parquet('data/chips/$AOI/index.parquet')
print(int((d.split=='train').sum()), int((d.split=='val').sum()), int((d.pv_pixels>0).sum()))")
  say "chips: $NTRAIN train, $NVAL val, $NPOS with PV"
  if [ "${NVAL:-0}" -lt 8 ] || [ "${NTRAIN:-0}" -lt 50 ]; then
    say "FAILED chips_checked: too few chips to train/score (train $NTRAIN, val $NVAL) -- fix val_tiles in configs/aoi.yaml, delete $MARK/chips and re-run"
    exit 1
  fi
  echo "$NTRAIN $NVAL $NPOS" > "$MARK/chips_checked"
fi
read -r NTRAIN NVAL NPOS < "$MARK/chips_checked"
# Local train rows repeated so they are roughly a quarter of the corpus (v5's other
# corpora are ~23,000 train rows), capped at x8 like Zambia's v7.
REPEAT=$($PY -c "print(max(1, min(8, round(7000 / max(1, $NTRAIN)))))")
step merge $PY scripts/merge_chip_index.py --out data/chips/combined_$AOI/index.parquet \
  $BASE_CORPUS $AOI:$REPEAT
step train gpu $MLPY -m earthpv.cli train --config $CONFIG

if [ ! -s "$MARK/pick" ]; then
  LOCAL=$($MLPY scripts/pick_best_checkpoint.py data/models/$MODEL_TAG 2>>"$LOG" | head -1)
  [ -f "$LOCAL" ] || { say "FAILED pick: no checkpoint in data/models/$MODEL_TAG"; exit 1; }
  echo "$LOCAL" > "$MARK/pick"; say "best checkpoint: $LOCAL"
fi
LOCAL=$(cat "$MARK/pick")

# ---- the owner's ship rule: whichever scores better on the held-out region ------------
if [ ! -s "$MARK/decide" ]; then
  say "start decide: $LOCAL vs $V5 on the $AOI val chips"
  CHOSEN=$(gpu $MLPY scripts/compare_local_vs_v5.py --aoi $AOI --local "$LOCAL" --v5 "$V5" 2>>"$LOG" | tee -a "$LOG" | tail -1)
  [ -f "$CHOSEN" ] || { say "FAILED decide: no checkpoint returned"; exit 1; }
  echo "$CHOSEN" > "$MARK/decide"; say "done decide: shipping $CHOSEN (results/${AOI}_checkpoint_decision.json)"
fi
CHOSEN=$(cat "$MARK/decide")
if [ "$CHOSEN" = "$LOCAL" ]; then OTHER=$V5; else OTHER=$LOCAL; fi

# ---- inference ----------------------------------------------------------------------------
if [ "$INCREMENTAL" = 1 ]; then
  # Compose is still running. Keep inference caught up every 6 h (infer resumes per cell),
  # so when compose finishes only the last cells remain.
  while [ ! -f "$COMPOSE_DONE" ]; do
    say "incremental infer ($(find -L data/composites/$AOI/composites -name composite_0.tif | wc -l) cells composited, $(ls data/predictions/$AOI/prob 2>/dev/null | wc -l) inferred)"
    gpu $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$CHOSEN" >> "$LOG" 2>&1 \
      || say "incremental infer rc=$? (retried next round)"
    sleep 21600
  done
  say "compose finished: $(find -L data/composites/$AOI/composites -name composite_0.tif | wc -l) cells"
fi
step infer gpu $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$CHOSEN"

# ---- segmentation half of the main workflow (as scripts/run_nigeria_pipeline.sh) --------
# NO --max-building-dist: that is the leads recipe and would drop ground-mount in farmland.
# --building-buffer-m 500 (not the 2 km default): Vietnam's candidates reach 1,897 of its
# 3,127 cells, and every footprint within 2 km of one of them was OOM-killed three times at
# 14 GB (2026-09-26). Placement and rank_score only use buildings within ~40 m.
# --stream-buildings: fetch/join/discard per 0.25-deg chunk instead of holding a national
# building table. Verified on Vietnam: identical placement and overlap for all 6,536
# candidates and identical distance for all 6,321 within 500 m, at 1.9 GB against 14-18.5 GB.
step postprocess  $PY -m earthpv.cli postprocess --aoi $AOI --threshold 0.3 --building-buffer-m 500 --stream-buildings
step export       $PY -m earthpv.cli export --aoi $AOI --exclude-mapped --min-distance-m 100
# Ranking of large OSM power=plant perimeters by how much of each the model lights up.
# Review artefacts ONLY; an exclusion list is hand-audited and never auto-applied.
step screen       $PY scripts/screen_osm_ground_perimeters.py --aoi $AOI --labels "$LABELS" \
                     --prob-dir data/predictions/$AOI/prob --min-area-m2 50000 \
                     --out results/${AOI}_osm_ground_screen/screen_full.csv \
                     --png-dir results/${AOI}_osm_ground_screen
# No quadrat, no register: precision-honest floor, recall deliberately not corrected.
step calibrate    $PY -m earthpv.cli calibrate-candidates --aoi $AOI --recall-reference none
step density      $PY -m earthpv.cli density --aoi $AOI --districts
step check_density $PY -m earthpv.cli check-density --aoi $AOI
# --labels pins this to the country's own pull (the default pools every country's file).
# --keep-detected-screen: the 5 km2 ground cap is a German measurement; Vietnam's five
# largest mapped parks (5.6-8.3 km2, ~1.9 GWp) are 92-99% detected by the model, and India's
# biggest parks are tens of km2. Above the cap a feature is kept only on that evidence.
step osm_solar    $PY scripts/prepare_national_osm_solar.py --aoi $AOI --labels "$LABELS" \
                     --keep-detected-screen results/${AOI}_osm_ground_screen/screen_full.csv
# --include-offgrid-osm: every label cell is in the compose selection, so this is a no-op
# unless a label cell never composited (cloud); then it keeps that hand-mapped capacity
# rather than dropping it, as France and Germany do.
step atlas        $PY -m earthpv.cli atlas --aoi $AOI --osm-solar "$OSM" --include-offgrid-osm \
                     --imagery-date-range "$DATE_RANGE" \
                     --out results/${AOI}_pv_evidence_atlas.html
touch "$QMARK/${AOI}_atlas_done"

# ---- diagnostic: the losing checkpoint over the whole country --------------------------
# AFTER the atlas, so a failure here cannot cost the deliverable. The decision itself was
# made on the held-out region only; this is the whole-country population-shape comparison
# (candidate count, median area, blobs) that France and Nigeria reported.
step infer_other  gpu $MLPY -m earthpv.cli infer --aoi $AOI --checkpoint "$OTHER" --out-dir $ALT
step postprocess_other $PY -m earthpv.cli postprocess --aoi $AOI --pred-dir $ALT --threshold 0.3 --building-buffer-m 500 --stream-buildings
step compare      $PY scripts/compare_checkpoints_vs_mapped.py --labels "$LABELS" \
                     --model chosen:data/predictions/$AOI/candidates.parquet:data/predictions/$AOI/prob \
                     --model other:$ALT/$AOI/candidates.parquet:$ALT/$AOI/prob
say "ALL DONE (chosen $CHOSEN)"
