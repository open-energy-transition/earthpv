#!/usr/bin/env bash
# Rebuild training chips for an AOI over its composite set, then remerge the combined
# (germany + <aoi>) training index. Run AFTER the AOI's compose finishes.
#
# Usage: scripts/rebuild_training.sh [aoi] [train_repeat]
#   aoi          (default pakistan)
#   train_repeat (default 2): oversample the AOI's *train* rows N times in the merge
#                to upweight the in-domain (target-domain) signal vs Germany, which
#                otherwise dominates by chip count (val rows are never duplicated).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.pixi/envs/default/bin/python
[ -x "$PY" ] || PY=python
AOI="${1:-pakistan}"
REPEAT="${2:-2}"
LOG="data/compose_${AOI}.log"

# Guard: only proceed once compose actually finished (its final log line), so we never
# chip a half-built composite set. FORCE=1 overrides (e.g. if you stopped it deliberately).
if [ "${FORCE:-0}" != "1" ] && ! grep -q "Composited .* new cells" "$LOG" 2>/dev/null; then
  echo "compose for '$AOI' not finished (no completion line in $LOG). Run after it completes, or FORCE=1."
  exit 1
fi
echo "Composed cells present: $(find "data/composites/$AOI/composites" -name composite_0.tif 2>/dev/null | wc -l)"

echo "== [1/3] rebuilding $AOI chips (fresh centers over full coverage) =="
$PY -m earthpv.cli chips --aoi "$AOI"

echo "== [2/3] merging combined index: germany + $AOI (train x${REPEAT}) =="
$PY scripts/merge_chip_index.py germany "${AOI}:${REPEAT}"

echo "== [3/3] summary =="
$PY - "$AOI" <<'PYEOF'
import sys, pandas as pd
aoi = sys.argv[1]
d = pd.read_parquet("data/chips/combined/index.parquet")
print(f"combined: {len(d)} chips, {int((d.pv_pixels>0).sum())} with PV, {int((d.split=='val').sum())} val")
print(d.groupby(["aoi", "split"]).size().to_string())
sub = d[d.aoi == aoi]
print(f"{aoi} val chips with PV: {int(((sub.split=='val') & (sub.pv_pixels>0)).sum())}")
PYEOF
echo "Ready to train: .pixi/envs/ml/bin/python -m earthpv.cli train --config configs/terramind_pv.yaml"
