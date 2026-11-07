#!/usr/bin/env bash
# `density` after model candidates were only REMOVED (e.g. scripts/solar_thermal_plants.py,
# which keeps the previous file as candidates.with_thermal.parquet): recompute the cells whose
# box a removed candidate intersects and keep every other cell's partial. A partial depends
# only on its cell's buildings, its probability raster and the candidates intersecting its box,
# and stores no candidate index, so the result is the same as `density --force` (checked on
# Namibia 2026-11-07: grid, regions and buildings identical to the last digit) at a fraction of
# the cost (India's full rebuild is ~28 h, this ~1 h).
#
#   bash scripts/density_partial_update.sh <aoi> [pred_dir] [previous candidates file name]
#
# Backs up the density directory's top-level files and the dropped partials to
# /home/tobi/earthpv_data/density_PRE_partial_<date>/<aoi>/ first.
set -eu
AOI=$1; PRED=${2:-data/predictions}; OLD=${3:-candidates.with_thermal.parquet}
cd "$(dirname "$0")/.."
PY=${PY:-.pixi/envs/default/bin/python}
[ -x "$PY" ] || PY=/run/media/tobi/aidisc/earthpv/.pixi/envs/default/bin/python
export PYTHONPATH=$PWD/src
BK=/home/tobi/earthpv_data/density_PRE_partial_$(date +%Y%m%d)/$AOI
DD=$PRED/$AOI/density
mkdir -p "$BK/cells"
find -L "$DD" -maxdepth 1 -type f -exec cp -p {} "$BK/" \;
$PY - "$AOI" "$PRED" "$BK" "$OLD" <<'PY'
import json, shutil, sys
from pathlib import Path
import geopandas as gpd
from shapely.geometry import box
from earthpv.density import CELL_DEG, _candidates_fingerprint
aoi, pred, bk, old_name = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
d = pred / aoi
old = gpd.read_parquet(d / old_name)
new = gpd.read_parquet(d / "candidates.parquet")
if not new.index.isin(old.index).all():
    sys.exit("candidates.parquet holds rows the previous file does not: not a pure removal")
gone = old.loc[~old.index.isin(new.index)]
grid = gpd.read_parquet(d / "density/grid.geoparquet")
cells = sorted({r.cell for r in grid.itertuples() for g in gone.geometry
                if box(r.lon0, r.lat0, r.lon0 + CELL_DEG, r.lat0 + CELL_DEG).intersects(g)})
print(f"{aoi}: {len(gone)} removed candidates touch cells {cells}")
for c in cells:
    for suf in (".parquet", ".summary.parquet"):
        p = d / "density/cells" / f"{c}{suf}"
        if p.exists():
            shutil.move(p, bk / "cells" / p.name)
fp = _candidates_fingerprint(pred / aoi / "candidates.parquet", len(new))  # density's own path form
(d / "density/candidates_fingerprint.json").write_text(json.dumps(fp, indent=2))
PY
$PY -m earthpv.cli density --aoi "$AOI" --districts --pred-dir "$PRED"
$PY -m earthpv.cli check-density --aoi "$AOI" --pred-dir "$PRED" || echo "check-density rc=$?"
echo "PARTIAL UPDATE DONE $AOI"
