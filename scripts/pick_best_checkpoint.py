"""Print the argmax-val/mIoU checkpoint for a run directory.

`save_top_k=2` keeps the two best checkpoints, so `ls -t` returns whichever was written
LAST -- the SECOND-best whenever the final improvement is not the argmax. Lightning records
the argmax in each checkpoint's own ModelCheckpoint callback state, which is authoritative.

**A directory can hold more than one run.** When a training run is killed and restarted
(Poland, 2026-10-22: systemd-oomd), the dead run's checkpoints and its `last.ckpt` survive
and Lightning writes the new run's state to `last-v1.ckpt`. Reading only `last.ckpt` then
returns the DEAD run's best (Poland shipped epoch 7 at 0.776 against the live run's epoch
27 at 0.804 until this was caught). So every `last*.ckpt` is read and the best score among
runs whose best file still exists wins.
"""

import glob
import os
import sys

import torch

run_dir = sys.argv[1]
cands = sorted(glob.glob(f"{run_dir}/*-epoch=*.ckpt"))  # any `checkpoint_prefix`
if not cands:
    sys.exit("no checkpoints")
probes = sorted(glob.glob(f"{run_dir}/last*.ckpt")) or cands[-1:]
best = None
for probe in probes:
    ckpt = torch.load(probe, map_location="cpu", weights_only=False)
    for key, state in (ckpt.get("callbacks") or {}).items():
        path = state.get("best_model_path") if "ModelCheckpoint" in str(key) else None
        if path and glob.glob(path):
            score = state.get("best_model_score")
            score = float(score) if score is not None else float("-inf")
            if best is None or score > best[0]:
                best = (score, path, probe)
if best:
    print(best[1])
    print(f"picked {os.path.basename(best[1])} (val {best[0]:.4f}) from "
          f"{os.path.basename(best[2])} among {len(probes)} run state(s)", file=sys.stderr)
    sys.exit(0)
# Fall back to mtime only if the callback state is unreadable, and say so loudly.
print(max(cands, key=os.path.getmtime))
print("WARNING: fell back to mtime selection", file=sys.stderr)
