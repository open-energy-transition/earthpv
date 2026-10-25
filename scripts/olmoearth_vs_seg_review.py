"""Blind review of UNMAPPED OlmoEarth detections, mixed with fresh segmentation and AlphaEarth
ones, for the precision question `olmoearth_vs_segmentation.py` leaves open.

At its declared operating point (`olmo64_both@0.995`: the first threshold whose random-land
burden, 6.1 unmapped detections per 1,000 km2, is below segmentation's 8.5) OlmoEarth's mapped
lower bound in the PV-rich cells is 0.745 against segmentation's 0.755, at much higher recall.
Whether its unmapped detections are arrays nobody mapped or false positives is what this asks.

Drawn, seeded: 24 unmapped OlmoEarth detections from the rich cells and every one from the
random cells, plus 12 rich-cell segmentation and 12 rich-cell AlphaEarth (`aef23_both@0.99`,
the same 2023 baseline) detections not in `aef_vs_seg_review.py`'s set, as a check that the
reviewer reads the way that review did. Shuffled together and rendered by
`aef_render_review_tiles.render` under random codes; the key goes to a separate file.

    pixi run python scripts/olmoearth_vs_seg_review.py
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
from aef_vs_seg_review import OUT as AEF_REVIEW, _unmapped  # noqa: E402
from aef_vs_segmentation import CANDS, MIN_AREA, OSM, WORK as AEF_WORK  # noqa: E402
from olmoearth_vs_segmentation import WORK  # noqa: E402
from propose_calibration_candidates import esri_capture  # noqa: E402

OUT = Path("results/olmoearth_vs_seg_review")
SEED = 20261025
N = {("rich", "olmo64"): 24, ("random", "olmo64"): 99, ("rich", "seg"): 12, ("rich", "aef23"): 12}


def _detections(setname: str, inst: str, cands: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if inst == "olmo64":
        return gpd.read_parquet(WORK / f"det_{setname}_olmo64_both_0.995.parquet")
    if inst == "aef23":
        return gpd.read_parquet(AEF_WORK / f"det_natneg_base2023_{setname}_both_0.99.parquet")
    return cands


def main() -> None:
    sets = gpd.read_parquet(AEF_WORK / "eval_sets.parquet")
    osm = gpd.read_parquet(OSM).to_crs(4326)
    cands = gpd.read_parquet(CANDS).to_crs(4326)
    cands = cands[cands.area_m2 >= MIN_AREA]
    seen = gpd.read_file(AEF_REVIEW / "blind_key_DO_NOT_OPEN_BEFORE_VERDICTS.geojson").to_crs(4326)
    rng = np.random.default_rng(SEED)
    picks = []
    for (setname, inst), n in N.items():
        area = sets[sets.set == setname].union_all()
        d = _detections(setname, inst, cands).to_crs(4326)
        d = d[d.representative_point().within(area)].reset_index(drop=True)
        u = _unmapped(d, osm)
        if inst != "olmo64":  # not one the earlier review already judged
            u = u[~u.intersects(seen.union_all())]
        take = u.loc[rng.choice(u.index.to_numpy(), size=min(n, len(u)), replace=False)]
        picks.append(gpd.GeoDataFrame({"set": setname, "instrument": inst,
                                       "area_m2": take.area_m2.to_numpy()},
                                      geometry=take.geometry.to_numpy(), crs=4326))
        print(setname, inst, "unmapped", len(u), "drawn", len(take))
    p = gpd.GeoDataFrame(pd.concat(picks, ignore_index=True), crs=4326)
    p = p.sample(frac=1, random_state=SEED).reset_index(drop=True)
    p["code"] = [f"W{i:02d}" for i in range(len(p))]
    (OUT / "blind").mkdir(parents=True, exist_ok=True)
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
