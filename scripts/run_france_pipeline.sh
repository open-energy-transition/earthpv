#!/usr/bin/env bash
# Post-compose France chain: infer -> postprocess -> export -> roofclf -> density.
#
# Waits for the quadrat-cell compose to finish first, so it can be launched immediately
# and left alone. Every stage is resumable, so a re-run after a failure picks up where it
# stopped rather than redoing GPU hours.
#
# Checkpoint: v4_combined_all epoch=41, the same one Germany used. The documented
# production checkpoint v3_combined_india is no longer on disk (see CLAUDE.md and
# docs/results/germany.md's owner-approved substitution, 2026-08-23).
set -u
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
MLPY=.pixi/envs/ml/bin/python
CKPT="data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt"
LOG=data/france_pipeline.log

say(){ echo "$(date -Is) $*" | tee -a "$LOG"; }

say "waiting for compose unit to finish"
while systemctl --user is-active --quiet earthpv-france-quadrat-compose; do sleep 30; done
N=$(find data/composites/france -name 'composite_0.tif' | wc -l)
say "compose done: $N cells"
if [ "$N" -lt 5 ]; then say "FATAL: too few composites ($N); stopping"; exit 1; fi

say "=== infer ==="
$MLPY -m earthpv.cli infer --aoi france --checkpoint "$CKPT" >>"$LOG" 2>&1 \
  || { say "infer FAILED"; exit 1; }
say "infer done: $(find data/predictions/france -name '*.tif' 2>/dev/null | wc -l) rasters"

say "=== postprocess ==="
$PY -m earthpv.cli postprocess --aoi france --threshold 0.3 >>"$LOG" 2>&1 \
  || { say "postprocess FAILED"; exit 1; }

say "=== export ==="
$PY -m earthpv.cli export --aoi france >>"$LOG" 2>&1 || say "export failed (non-fatal)"

say "=== roof-classifier (France quadrats, parcel label) ==="
# Saint-Gely-du-Fesc is excluded: the mapper marked it unfinished, so it is not Rule-1
# complete and would fit the coverage ratio on a partially-swept commune.
QUADS=$($PY - <<'PYQ'
from pathlib import Path
stems = sorted(p.name[:-len("_boundary.geojson")]
               for p in Path("data/labels/france").glob("*_calib_*_boundary.geojson"))
print(" ".join(f"--quadrat {s}" for s in stems if not s.startswith("saint_gely")))
PYQ
)
say "quadrats: $QUADS"
# --seg-prob-dir is deliberately NOT passed. roofclf reads the probability raster from a
# SINGLE 0.1 degree cell (the one containing the boundary's representative point) and
# zero-fills the rest, which is fine for a 1-4 km2 Pakistani box but not for French
# communes: seven of the fourteen straddle two to four cells. That would make seg_mean /
# seg_max correct in some quadrats and partly zero in others, which is worse than absent
# everywhere. Segmentation carries little signal at this scale anyway -- the modal mapped
# French array is 20 m2, a fifth of one Sentinel-2 pixel.
$PY -m earthpv.cli roof-classifier --aoi france \
  --labels-dir data/labels/france \
  --composites data/composites/france \
  --out-dir data/roofclf_france --parcel-label $QUADS >>"$LOG" 2>&1 \
  || { say "roof-classifier FAILED"; exit 1; }

say "=== density ==="
$PY -m earthpv.cli density --aoi france --districts >>"$LOG" 2>&1 \
  || say "density failed (non-fatal for the register blocks)"
$PY -m earthpv.cli check-density --aoi france >>"$LOG" 2>&1 || say "check-density reported failures"

say "=== PIPELINE COMPLETE ==="
