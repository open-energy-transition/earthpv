#!/usr/bin/env python
"""Carry a country's review verdicts over, by overlap, to a staging run's review queues.

A verdict on the solar farm review (blobs above the cap) or the large installation review
(leads from 10,000 m2 up to the cap) names one candidate of one candidate file, so a new
model run starts both reviews empty (`oversize_review.py draw --stage NAME --pred DIR`). A
person judged the PLACE, so this fills the staging queues from the published reviews (owner,
2026-11-19, when Denmark, California and Texas moved to their localized ResNet runs):

- every outline judged on either published review (blob or large; solar or not solar, the
  bright-roof flag kept) is a judged area;
- a staging outline takes `pv` when at least `--min-share` of it lies inside outlines judged
  solar, `not_pv` when at least that share lies inside outlines judged not solar (with the
  `bright_roof` flag when that share lies inside outlines flagged so), and stays blank, to be
  judged on the staging page, otherwise (or when both hold);
- its `evidence` names the share and the published review it came from.

Only blank rows of the staging review.csv are touched, so a verdict given on the staging
page is never overwritten. The published reviews, tables and pages are only read. Then
`oversize_review.py [--kind large] apply --stage NAME --pred DIR --table <staging table>`
records the verdicts, and `package` drops the judged outlines from the staging pages.

    pixi run python scripts/carry_review_verdicts.py --aoi texas --stage resnet \\
        --pred data/predictions_resnet_20261119/texas
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

AREA_CRS = "EPSG:6933"
KINDS = ("oversize_review", "large_review")


def _geoms(cands: gpd.GeoDataFrame, rev: pd.DataFrame, what: str) -> gpd.GeoSeries:
    """The outlines `rev` names, after checking `cands` is the file it was drawn from."""
    miss = ~rev["candidate_index"].isin(cands.index)
    if miss.any():
        raise SystemExit(f"{what}: {int(miss.sum())} rows name candidates the file does not hold")
    area = cands.loc[rev["candidate_index"], "area_m2"].to_numpy(float)
    if not np.allclose(area, rev["area_m2"].to_numpy(float), rtol=1e-6, atol=1.0):
        raise SystemExit(f"{what}: the candidate file is not the one the review was drawn from")
    return cands.loc[rev["candidate_index"]].geometry.to_crs(AREA_CRS).buffer(0)


def _union(geoms: gpd.GeoSeries):
    return unary_union(geoms.values) if len(geoms) else None


def _share(geoms: gpd.GeoSeries, zone) -> np.ndarray:
    if zone is None or not len(geoms):
        return np.zeros(len(geoms))
    return (geoms.intersection(zone).area / geoms.area).to_numpy(float)


def main() -> int:
    from oversize_review import run_source

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--stage", required=True, help="the staging run's name (draw --stage)")
    ap.add_argument("--pred", required=True,
                    help="the staging run's prediction directory, holding candidates.parquet")
    ap.add_argument("--published-pred", default=None,
                    help="the published run's prediction directory (default: release_leads.SOURCES)")
    ap.add_argument("--min-share", type=float, default=0.5)
    ap.add_argument("--from-label", default="published run",
                    help="how the evidence names the run the verdicts came from")
    a = ap.parse_args()

    pub_pred = REPO / (a.published_pred or run_source(a.aoi)["pred"])
    pub = gpd.read_parquet(pub_pred / "candidates.parquet")
    judged = []
    for kind in KINDS:
        path = REPO / "results" / f"{a.aoi}_{kind}" / "review.csv"
        if not path.exists():
            continue
        rev = pd.read_csv(path, dtype={"verdict": str, "flag": str, "evidence": str})
        rev = rev[rev["verdict"].fillna("").isin(["pv", "not_pv"])]
        if rev.empty:
            continue
        g = _geoms(pub, rev, str(path))
        judged.append(pd.DataFrame({"verdict": rev["verdict"].to_numpy(),
                                    "flag": rev.get("flag", pd.Series("", index=rev.index))
                                               .fillna("").to_numpy(),
                                    "geometry": g.to_numpy()}))
    summary = {"aoi": a.aoi, "stage": a.stage, "min_share": a.min_share,
               "published_pred": str(pub_pred.relative_to(REPO)), "kinds": {}}
    if not judged:
        print(f"{a.aoi}: no published verdicts to carry over")
        summary["published_judged"] = 0
    else:
        j = gpd.GeoDataFrame(pd.concat(judged, ignore_index=True), crs=AREA_CRS)
        zones = {"pv": _union(j.geometry[j.verdict == "pv"]),
                 "not_pv": _union(j.geometry[j.verdict == "not_pv"]),
                 "bright_roof": _union(j.geometry[(j.verdict == "not_pv")
                                                  & (j.flag == "bright_roof")])}
        summary["published_judged"] = {v: int((j.verdict == v).sum()) for v in ("pv", "not_pv")}
        cands = gpd.read_parquet(REPO / a.pred / "candidates.parquet")
        for kind in KINDS:
            path = REPO / "results" / f"{a.aoi}_{a.stage}" / kind / "review.csv"
            if not path.exists():
                print(f"{kind}: no staging review at {path.relative_to(REPO)}")
                continue
            rev = pd.read_csv(path, dtype={"verdict": str, "flag": str, "evidence": str})
            for col in ("verdict", "flag", "evidence"):
                rev[col] = rev[col].fillna("") if col in rev else ""
            open_ = rev["verdict"].eq("")
            g = _geoms(cands, rev[open_], str(path))
            s_pv, s_no, s_br = (_share(g, zones[k]) for k in ("pv", "not_pv", "bright_roof"))
            pv = (s_pv >= a.min_share) & (s_no < a.min_share)
            no = (s_no >= a.min_share) & (s_pv < a.min_share)
            idx = rev.index[open_]
            rev.loc[idx[pv], "verdict"] = "pv"
            rev.loc[idx[no], "verdict"] = "not_pv"
            rev.loc[idx[no & (s_br >= a.min_share)], "flag"] = "bright_roof"
            for i, sp, sn, p, n in zip(idx, s_pv, s_no, pv, no):
                if p or n:
                    rev.at[i, "evidence"] = (
                        f"carried over by overlap from the {a.from_label}'s review: "
                        f"{(sp if p else sn):.0%} of this outline lies inside outlines judged "
                        f"{'solar' if p else 'not solar'}")
            rev.to_csv(path, index=False)
            both = int(((s_pv >= a.min_share) & (s_no >= a.min_share)).sum())
            k = {"rows": int(len(rev)), "open_before": int(open_.sum()),
                 "carried_pv": int(pv.sum()), "carried_not_pv": int(no.sum()),
                 "carried_bright_roof": int((no & (s_br >= a.min_share)).sum()),
                 "both_over_share_left_open": both,
                 "open_after": int(rev["verdict"].eq("").sum()),
                 "carried_pv_km2": round(float(rev.loc[idx[pv], "area_m2"].sum()) / 1e6, 3),
                 "open_after_km2": round(float(rev.loc[rev["verdict"].eq(""), "area_m2"].sum())
                                         / 1e6, 3)}
            summary["kinds"][kind] = k
            print(f"{a.aoi} {kind}: {k['carried_pv']} solar + {k['carried_not_pv']} not solar "
                  f"carried over of {k['open_before']} open; {k['open_after']} left to judge "
                  f"({k['open_after_km2']:.2f} km2) -> {path.relative_to(REPO)}")
    out = REPO / "results" / f"{a.aoi}_{a.stage}" / "carried_verdicts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
