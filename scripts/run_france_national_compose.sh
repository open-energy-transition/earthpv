#!/usr/bin/env bash
# National France compose, in a time-bounded restart loop.
#
# `compose` leaks file descriptors and memory at country scale. Two distinct symptoms,
# measured on France 2026-09-04/06:
#
#   * it eventually dies with `OSError(24, 'Too many open files')` (passes 1 and 2, after
#     305 and 157 cells), and
#   * BEFORE that it degrades badly rather than failing fast. Pass 3 decayed from 58 s/it
#     to 172 and then 256 s/it, RSS climbing past 8 GB, delivering 0.17 cells/min against a
#     healthy 0.74 -- and because it never actually crashed, a crash-triggered loop never
#     restarted it. Four hours were spent at a quarter speed.
#
# So each pass is capped by wall clock instead of waiting for a crash. `timeout` returns
# 124, which is the EXPECTED path here, not an error: the pass is cut while still healthy
# and the next one starts with a fresh FD table, fresh memory and a freshly signed
# Planetary Computer SAS token (which expires ~24 h after signing).
#
# compose is resumable and writes each cell via a .tmp rename, so cutting a pass mid-cell
# loses at most the cells in flight, which the next pass simply redoes.
set -u
cd /run/media/tobi/aidisc/earthpv
LOG=data/france_national_compose.log
TARGET=5471
PASS_SECONDS=7200      # 2 h: ~90 cells at the healthy rate, well inside the decay window
MAX_PASSES=200         # the "added nothing" guard below is the real stop condition
say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }
# -L: data/composites/france is a SYMLINK to /home/tobi/earthpv_composites/france (the
# aidisc drive is too small for a country). Plain `find` does not descend into a
# symlinked directory, so without -L this returns 0, the "added nothing" guard fires
# on the first pass and the loop kills itself while compose is working perfectly.
count(){ find -L data/composites/france -name 'composite_0.tif' | wc -l; }

export GDAL_HTTP_MAX_RETRY=3 GDAL_HTTP_RETRY_DELAY=2
export CPL_VSIL_CURL_CACHE_SIZE=67108864
export GDAL_NUM_DATASET_CACHE=64

for pass in $(seq 1 "$MAX_PASSES"); do
  before=$(count)
  if [ "$before" -ge "$TARGET" ]; then say "all $TARGET cells present; done"; break; fi
  say "pass $pass: starting with $before/$TARGET cells"
  timeout --signal=TERM --kill-after=120 "$PASS_SECONDS" \
    .pixi/envs/default/bin/python -m earthpv.cli compose --aoi france \
      --min-buildings 1000 --workers 4 >>"$LOG" 2>&1
  rc=$?
  # A cut-off pass can leave a half-written .tmp; the rename is atomic so no committed
  # cell is ever partial, but the stragglers would otherwise accumulate.
  find -L data/composites/france -name '*.tif.tmp' -delete 2>/dev/null
  after=$(count)
  case "$rc" in
    124) note="(time-capped, expected)" ;;
      0) note="(clean exit)" ;;
      *) note="(crashed rc=$rc)" ;;
  esac
  say "pass $pass: $before -> $after cells (+$((after-before))) $note"
  if [ "$after" -le "$before" ]; then
    say "pass $pass added nothing; stopping so this does not spin. Investigate $LOG."
    exit 1
  fi
  sleep 15
done
say "national compose loop finished at $(count)/$TARGET cells"
