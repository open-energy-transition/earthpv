"""Print the argmax-val/mIoU checkpoint for a run directory.

`save_top_k=2` keeps the two best checkpoints, so `ls -t` returns whichever was written
LAST -- the SECOND-best whenever the final improvement is not the argmax. Lightning records
the argmax in each checkpoint's own ModelCheckpoint callback state, which is authoritative.
"""
import glob
import sys

import torch

run_dir = sys.argv[1]
cands = sorted(glob.glob(f"{run_dir}/terramind-pv-epoch=*.ckpt"))
if not cands:
    sys.exit("no checkpoints")

probe = f"{run_dir}/last.ckpt"
probe = probe if glob.glob(probe) else cands[-1]
ckpt = torch.load(probe, map_location="cpu", weights_only=False)
for key, state in (ckpt.get("callbacks") or {}).items():
    if "ModelCheckpoint" in str(key) and state.get("best_model_path"):
        best = state["best_model_path"]
        if glob.glob(best):
            print(best)
            sys.exit(0)
# Fall back to mtime only if the callback state is unreadable, and say so loudly.
print(max(cands, key=lambda p: __import__("os").path.getmtime(p)))
print("WARNING: fell back to mtime selection", file=sys.stderr)
