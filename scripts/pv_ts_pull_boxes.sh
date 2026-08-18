#!/usr/bin/env bash
# Sequential dense-cube pulls for the calibration boxes + negative controls.
#
# Sequential on purpose: each box already runs 4 concurrent tile-year loads, and the
# bottleneck is Earth Search COG reads, so stacking boxes in parallel just spreads the
# same bandwidth thinner while multiplying the chance of a mid-pull failure.
# Resumable: every (tile, year) that already has an .npz is skipped.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
LOG=data/ts_pull_boxes.log
START=${START:-2018-07-01}
END=${END:-2026-07-24}

pull() {  # name  boundary-or-bbox-spec
  echo "=== $(date '+%F %T') pulling $1" >> "$LOG"
  # shellcheck disable=SC2086
  timeout 3600 $PY scripts/pv_ts_cube.py pull --name "$1" $2 \
      --start "$START" --end "$END" --workers 4 >> "$LOG" 2>&1
  echo "=== $(date '+%F %T') $1 rc=$? files=$(ls data/ts/$1/*.npz 2>/dev/null | wc -l)" >> "$LOG"
}

# Calibration boxes, largest median installation first: the method has to be shown to
# work where the signal is unambiguous (1,000+ m2 industrial arrays) before its
# behaviour at 50-100 m2 rooftop scale means anything.
pull sundar_box       "--boundary data/labels/sundar_calib_1km_boundary.geojson --buffer-m 250"
pull site_karachi_box "--boundary data/labels/site_karachi_calib_1km_boundary.geojson --buffer-m 250"
pull multan_box       "--boundary data/labels/multan_calib_1km_boundary.geojson --buffer-m 250"
pull faisalabad_box   "--boundary data/labels/faisalabad_calib_1km_boundary.geojson --buffer-m 250"

# Negative controls, same scene geometry as the Lahore box (same MGRS tile, ~5-15 km away):
# irrigated cropland and a canal/park strip. Any "installation step" found here is a
# false positive by construction - this is the stress test the epoch-jump issue doc asks for.
pull control_crop_lhr "--bbox 74.4600,31.3600,74.4760,31.3740"
pull control_crop2_lhr "--bbox 74.3200,31.5600,74.3360,31.5740"
echo "=== $(date '+%F %T') all box pulls done" >> "$LOG"
