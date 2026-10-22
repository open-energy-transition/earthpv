"""Blind review of UNMAPPED detections from both instruments, mixed, for the precision gap.

`aef_vs_segmentation.py --national-negatives` leaves precision a lower bound everywhere but
the quadrats: a detection with no OSM solar within 100 m may be a false positive or an
array nobody mapped. In the PV-rich cells that bound is 0.61 for AlphaEarth (`both`, tau 0.99,
the declared operating point: its false-positive burden in the random cells, 5.7 per
1,000 km2, is the first below segmentation's 8.5) against 0.76 for segmentation, and OSM
there was partly mapped from segmentation's own leads, so the bound may favour it.

Drawn, seeded: 24 unmapped detections per instrument from the rich cells, and from the random
cells all 12 AlphaEarth ones and 12 of segmentation's 18. Shuffled together and rendered by
`aef_render_review_tiles.render` under random codes; the key goes to a separate file.

    pixi run python scripts/aef_vs_seg_review.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aef_render_review_tiles import PANEL, render  # noqa: E402
from aef_vs_segmentation import CANDS, MATCH_M, MIN_AREA, OSM, UTM, WORK  # noqa: E402
from propose_calibration_candidates import esri_capture  # noqa: E402

OUT = Path("results/aef_vs_seg_review")
SEED = 20261025
AEF_KEY = "both_0.99"
N = {("rich", "aef"): 24, ("rich", "seg"): 24, ("random", "aef"): 12, ("random", "seg"): 12}


def _unmapped(d: gpd.GeoDataFrame, osm: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    du, ou = d.to_crs(UTM), osm.to_crs(UTM)
    hit = gpd.sjoin(gpd.GeoDataFrame(geometry=du.buffer(MATCH_M).to_numpy(), crs=UTM),
                    ou[["geometry"]], predicate="intersects").index.unique()
    return d[~np.isin(np.arange(len(d)), hit)]


def main() -> None:
    sets = gpd.read_parquet(WORK / "eval_sets.parquet")
    osm = gpd.read_parquet(OSM).to_crs(4326)
    cands = gpd.read_parquet(CANDS).to_crs(4326)
    cands = cands[cands.area_m2 >= MIN_AREA]
    rng = np.random.default_rng(SEED)
    picks = []
    for (setname, inst), n in N.items():
        area = sets[sets.set == setname].union_all()
        if inst == "aef":
            d = gpd.read_parquet(WORK / f"det_natneg_{setname}_{AEF_KEY}.parquet")
        else:
            d = cands
        d = d[d.representative_point().within(area)].reset_index(drop=True)
        u = _unmapped(d, osm)
        take = u.loc[rng.choice(u.index.to_numpy(), size=min(n, len(u)), replace=False)]
        picks.append(gpd.GeoDataFrame({"set": setname, "instrument": inst,
                                       "area_m2": take.area_m2.to_numpy()},
                                      geometry=take.geometry.to_numpy(), crs=4326))
        print(setname, inst, "unmapped", len(u), "drawn", len(take))
    p = gpd.GeoDataFrame(pd.concat(picks, ignore_index=True), crs=4326)
    p = p.sample(frac=1, random_state=SEED).reset_index(drop=True)
    p["code"] = [f"V{i:02d}" for i in range(len(p))]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "blind").mkdir(exist_ok=True)
    imgs, dates = [], []
    for _, r in p.iterrows():
        pt = r.geometry.representative_point()
        cap = esri_capture(pt.x, pt.y)
        dates.append(cap["date"].isoformat() if cap else "unknown")
        imgs.append(render(r.geometry, r.code, dates[-1]))
    p["imagery_date"] = dates
    p.to_file(OUT / "blind_key_DO_NOT_OPEN_BEFORE_VERDICTS.geojson", driver="GeoJSON")
    pd.DataFrame({"code": p.code, "imagery_date": dates, "verdict": "", "note": ""}).to_csv(
        OUT / "blind" / "verdicts.csv", index=False)
    for k in range(0, len(imgs), 6):
        sheet = Image.new("RGB", (PANEL * 3, PANEL * 2), (0, 0, 0))
        for j, im in enumerate(imgs[k:k + 6]):
            sheet.paste(im, ((j % 3) * PANEL, (j // 3) * PANEL))
        sheet.save(OUT / "blind" / f"sheet_{k // 6:02d}.png")
    print(f"{len(imgs)} panels in {math.ceil(len(imgs) / 6)} sheets")


if __name__ == "__main__":
    main()
