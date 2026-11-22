#!/usr/bin/env python
"""Re-point a staging tree's review verdicts at its own candidate rows.

Review CSVs name candidates by row (`candidate_index`) of the candidates file they were drawn
from. A different building layer changes `rank_score`, which reorders that file, so the same
outline sits at another row and density refuses the verdicts (area check). The outline itself
is unchanged (same rasters, same threshold): match each review row to the candidate with the
same representative point (5 decimals, as the review rounds it) and area, and rewrite the
index. Staging trees only; the repo's review files are never touched.

    python scripts/building_layer_remap_reviews.py <tree> <aoi>
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

tree, aoi = Path(sys.argv[1]), sys.argv[2]
cands = gpd.read_parquet(tree / "data/predictions" / aoi / "candidates.parquet")
rp = cands.geometry.representative_point()
key = pd.DataFrame({"idx": cands.index, "lon": rp.x.round(5).to_numpy(),
                    "lat": rp.y.round(5).to_numpy(), "area": cands["area_m2"].to_numpy(float)})
for kind in ("large_review", "oversize_review"):
    path = tree / "results" / f"{aoi}_{kind}" / "review.csv"
    if not path.exists():
        continue
    orig = path.with_suffix(".csv.orig")
    if not orig.exists():
        path.rename(orig)
    rev = pd.read_csv(orig)
    if "candidate_index" not in rev or rev.empty:
        rev.to_csv(path, index=False)
        continue
    m = rev.merge(key, on=["lon", "lat"], how="left")
    m = m[(m["area"] - m["area_m2"]).abs() <= 1.0]
    m = m[~m.duplicated(subset=["candidate_index"], keep=False)]
    new = rev["candidate_index"].map(dict(zip(m["candidate_index"], m["idx"])))
    judged = rev["verdict"].fillna("").isin(("pv", "not_pv"))
    lost = judged & new.isna()
    moved = int((new.notna() & (new != rev["candidate_index"])).sum())
    rev.loc[lost, "verdict"] = np.nan  # an outline this run no longer holds: unjudged
    rev["candidate_index"] = new.fillna(-1).astype(int)
    rev = rev[rev["candidate_index"] >= 0]
    rev.to_csv(path, index=False)
    print(f"{aoi} {kind}: {len(rev)} rows kept, {moved} re-pointed, "
          f"{int(lost.sum())} judged rows without a matching outline")
