"""Pool every country's segmentation chips into one corpus (v18).

Every localized checkpoint so far is the v5 base plus ONE country, so no model has seen more
than one of Poland, India, Vietnam, Egypt, Morocco, Yemen, Nigeria and Zambia, and Germany's
chips come from 14 MGRS tiles out of a national label set eight times larger. This builds
v16's corpus (data/chips/combined_pakistan_v16, kept row for row with its own repeats and
buffers) plus each of those countries' own chip index, each country's train rows repeated
clamp(round(7000 / n_train), 1, 8) times as `run_country_compute.sh` does when it localizes,
plus `germany_national` (national-compose chips outside the 14 tiles) once.

Every source keeps its own val split, so every holdout the release benchmark scores survives.
Sources overlap on the ground (India covers Gujarat's held-out box, the national German chips
border Germany's held-out tiles, the Pakistan and Punjab sets interleave), and each source's own
buffer only knows its own val cells. So any TRAIN chip within `--guard-km` of a VAL chip from a
DIFFERENT source is relabelled `buffer`: the cross-source version of `mark_val_buffer.py`'s
8-cell ring (one 0.1 deg cell is ~11 km; a 2.24 km window reaches 1.1 km from its centre).

    python scripts/build_pooled_corpus.py --out data/chips/combined_pooled_v18/index.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
BASE = "data/chips/combined_pakistan_v16/index.parquet"
ADD = ["poland", "india", "vietnam", "yemen", "nigeria", "egypt", "morocco", "zambia"]
ADD_FIXED = {"germany_national": ("data/chips/germany_national/germany/index.parquet", 1)}


def _xy_km(df: pd.DataFrame) -> np.ndarray:
    lat = np.radians(df.lat.to_numpy())
    return np.column_stack([df.lon.to_numpy() * 111.32 * np.cos(lat), df.lat.to_numpy() * 110.57])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--guard-km", type=float, default=12.0)
    a = ap.parse_args()

    frames, plan = [pd.read_parquet(ROOT / BASE)], {"base": BASE}
    frames[0]["source"] = frames[0]["aoi"]
    sources = [(aoi, f"data/chips/{aoi}/index.parquet", None) for aoi in ADD]
    sources += [(name, path, rep) for name, (path, rep) in ADD_FIXED.items()]
    for name, path, rep in sources:
        df = pd.read_parquet(ROOT / path)
        n_train = int((df.split == "train").sum())
        rep = rep or max(1, min(8, round(7000 / max(1, n_train))))
        df["aoi"] = name
        df["source"] = name
        train = df[df.split == "train"]
        frames.append(pd.concat([df] + [train] * (rep - 1), ignore_index=True))
        plan[name] = {"path": path, "repeat": rep, "chips": len(df), "train": n_train,
                      "val": int((df.split == "val").sum())}
    out = pd.concat(frames, ignore_index=True)

    missing = [p for p in pd.unique(pd.concat([out["image"], out["mask"]]))
               if not (ROOT / p).exists()]
    if missing:
        raise SystemExit(f"{len(missing)} chip files missing, e.g. {missing[:3]}")

    # Cross-source leak guard.
    val = out[out.split == "val"]
    guarded = {}
    for src in out.source.unique():
        other = val[val.source != src]
        mine = (out.source == src) & (out.split == "train")
        if other.empty or not mine.any():
            continue
        d, _ = cKDTree(_xy_km(other)).query(_xy_km(out[mine]), k=1)
        hit = out.index[mine][d < a.guard_km]
        out.loc[hit, "split"] = "buffer"
        if len(hit):
            guarded[src] = int(len(hit))

    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out)
    summary = {
        "plan": plan, "guard_km": a.guard_km, "guarded_train_rows": guarded,
        "rows": len(out), "by_source_split": {
            s: g.split.value_counts().to_dict() for s, g in out.groupby("source")},
    }
    a.out.with_name("corpus.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
