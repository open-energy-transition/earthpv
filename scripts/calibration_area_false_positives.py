#!/usr/bin/env python
"""False positives inside the calibration areas, for both detectors.

Two questions, measured on the areas a person declared completely mapped:

1. **roofclf**: of the roofs it flags, how many carry no mapped PV, and is that a lot? Read
   on the fit's out-of-fold scores (`p_oof`: every roof scored by a model that never saw
   its area), at the deployment threshold, recomputed the way `roofclf.py` picks it
   (`sppi._precision_threshold`, min precision 0.5: as many roofs as the ranking can flag
   while precision stays at 0.5). Precision only means something against the share of
   roofs that carry PV at all, so each area is set beside two references at the SAME number
   of flagged roofs: chance (its base rate) and a ranking by roof area alone, the null every
   roofclf pricing test is held to. Also written: the share of the score mass on roofs
   without PV, which is what probability-weighted pricing actually sums.
2. **segmentation**: model candidates (capacity-relevant, <= the merge cap) whose
   representative point lies in an area, with the distance to the nearest mapped OSM solar
   feature (the area's own pull plus the national one, in the area's UTM zone). The
   pipeline counts a candidate within 100 m (`min_distance_m`) as matched; distance 0
   means the outline touches a mapped array.

Both are upper bounds on false positives: an area is complete against its mapping imagery's
date, so PV built since then counts as false here.

    pixi run python scripts/calibration_area_false_positives.py --aoi pakistan

Writes results/<aoi>_roofclf_precision_by_area.csv (one row per area plus `ALL`),
results/<aoi>_calibration_area_seg_candidates.csv (one row per candidate) and
results/<aoi>_calibration_area_false_positives.json (the pooled numbers quoted in
docs/how-it-works.md).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MERGE_CAP_M2 = 100_000.0          # postprocess.MAX_CANDIDATE_M2
MATCH_M = 100.0                   # the calibration table's min_distance_m
TOP_SHARES = (0.01, 0.05, 0.10)


def roofclf_by_area(model_dir: Path) -> tuple[pd.DataFrame, dict]:
    import pyarrow.parquet as pq
    from earthpv.sppi import _precision_threshold

    t = pq.read_table(model_dir / "buildings.geoparquet",
                      columns=["quadrat", "has_pv", "p_oof", "roof_area_m2",
                               "pv_area_true_m2"]).to_pandas()
    t = t[t.p_oof.notna()].reset_index(drop=True)
    y = t.has_pv.astype(bool).to_numpy()
    s = t.p_oof.to_numpy(float)
    thr = _precision_threshold(y, s, min_precision=0.5)
    t["flag"] = s >= thr

    def at_k(score: np.ndarray, yy: np.ndarray, k: int) -> float:
        return float(yy[np.argsort(-score, kind="stable")[:k]].mean()) if k else np.nan

    rows = []
    for name, g in [*t.groupby("quadrat"), ("ALL", t)]:
        yy = g.has_pv.astype(bool).to_numpy()
        k = int(g.flag.sum())
        tp = int((g.flag & g.has_pv.astype(bool)).sum())
        mass = float(g.p_oof.sum())
        rows.append({
            "area": name, "n_roofs": len(g), "n_pv": int(yy.sum()),
            "base_rate": yy.mean(), "n_flagged": k, "true_pos": tp, "false_pos": k - tp,
            "precision": tp / k if k else np.nan,
            "precision_roof_area_only": at_k(g.roof_area_m2.to_numpy(float), yy, k),
            "recall": tp / yy.sum() if yy.sum() else np.nan,
            "score_mass": mass,
            "score_mass_pv_free_share": float(g.p_oof[~g.has_pv.astype(bool)].sum()) / mass,
        })
    out = pd.DataFrame(rows)
    pv = t.pv_area_true_m2.fillna(0).to_numpy(float)
    k_all = int(t.flag.sum())
    rng = np.random.default_rng(0)

    def area_recall(score):
        idx = np.argsort(-score, kind="stable")[:k_all]
        return float(pv[idx].sum() / pv.sum())

    w = t.p_oof * t.roof_area_m2
    pooled = {
        "threshold": thr, "n_roofs": len(t), "n_pv": int(y.sum()), "base_rate": float(y.mean()),
        "n_flagged": k_all, "false_pos": int((t.flag & ~t.has_pv.astype(bool)).sum()),
        "precision": float(y[t.flag].mean()), "recall": float(y[t.flag].sum() / y.sum()),
        "pv_area_recall": area_recall(s),
        "roof_area_only": {"precision": at_k(t.roof_area_m2.to_numpy(float), y, k_all),
                           "pv_area_recall": area_recall(t.roof_area_m2.to_numpy(float))},
        "random": {"precision": float(y.mean()),
                   "pv_area_recall": area_recall(rng.random(len(t)))},
        "precision_top_share": {f"{q:.0%}": at_k(s, y, int(q * len(t))) for q in TOP_SHARES},
        "score_mass_pv_free_share": float(t.p_oof[~t.has_pv.astype(bool)].sum() / t.p_oof.sum()),
        "roof_area_weighted_score_pv_free_share": float(w[~t.has_pv.astype(bool)].sum() / w.sum()),
    }
    per_area = out[out.area != "ALL"]
    usable = per_area[(per_area.n_flagged >= 20) & (per_area.n_pv >= 20)]
    pooled["areas_compared"] = len(usable)
    pooled["areas_beating_roof_area"] = int(
        (usable.precision > usable.precision_roof_area_only).sum())
    pooled["precision_range_compared"] = [float(usable.precision.min()),
                                          float(usable.precision.max())]
    return out, pooled


def seg_candidates(aoi: str, candidates: Path, labels_dir: Path, osm_solar: Path):
    import geopandas as gpd

    c = gpd.read_parquet(candidates)
    c = c[c.area_m2 <= MERGE_CAP_M2]
    nat = gpd.read_parquet(osm_solar)[["geometry"]].to_crs(4326)
    rows, n_areas = [], 0
    for b in sorted(glob.glob(str(labels_dir / "*_calib_*_boundary.geojson"))):
        n_areas += 1
        stem = Path(b).name.removesuffix("_boundary.geojson")
        bnd = gpd.read_file(b).to_crs(4326)
        poly = bnd.union_all()
        utm = bnd.estimate_utm_crs()
        inside = c[c.geometry.representative_point().within(poly)]
        if inside.empty:
            continue
        parts = [nat]
        own = labels_dir / f"{stem}_overpass_solar.parquet"
        if own.exists():
            parts.append(gpd.read_parquet(own)[["geometry"]].to_crs(4326))
        ref = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
        ref = ref[ref.intersects(poly.buffer(0.01))].to_crs(utm)
        for _, r in inside.to_crs(utm).iterrows():
            rows.append({
                "area": stem.split("_calib_")[0], "area_m2": r["area_m2"],
                "placement": r["placement"], "geometry_source": r["geometry_source"],
                "confidence": r["confidence"],
                "dist_to_mapped_m": float(ref.distance(r.geometry).min()) if len(ref) else np.inf,
            })
    d = pd.DataFrame(rows)
    roof = d.placement == "rooftop"
    summary = {
        "areas": n_areas, "areas_with_candidates": int(d.area.nunique()),
        "candidates": len(d),
        "beyond_match_distance": int((d.dist_to_mapped_m > MATCH_M).sum()),
        "touching_no_mapped_pv": int((d.dist_to_mapped_m > 0).sum()),
        "rooftop": {"n": int(roof.sum()),
                    "touching_no_mapped_pv": int((d[roof].dist_to_mapped_m > 0).sum())},
        "ground_or_other": {"n": int((~roof).sum()),
                            "touching_no_mapped_pv": int((d[~roof].dist_to_mapped_m > 0).sum())},
        "outline_replaced_by_osm": int((d.geometry_source == "osm").sum()),
        "match_distance_m": MATCH_M,
    }
    return d, summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--model-dir", type=Path, default=Path("data/roofclf"),
                    help="roofclf fit directory (buildings.geoparquet with p_oof)")
    ap.add_argument("--candidates", type=Path, default=None,
                    help="default data/predictions/<aoi>/candidates.parquet")
    ap.add_argument("--labels-dir", type=Path, default=None,
                    help="where the areas' boundaries live: data/labels for Pakistan, "
                         "data/labels/<aoi> elsewhere")
    ap.add_argument("--osm-solar", type=Path, default=None,
                    help="default data/labels/<aoi>_overpass_solar.parquet")
    ap.add_argument("--out-dir", type=Path, default=Path("results"))
    a = ap.parse_args()
    aoi = a.aoi
    labels_dir = a.labels_dir or Path("data/labels" if aoi == "pakistan" else f"data/labels/{aoi}")
    cands = a.candidates or Path(f"data/predictions/{aoi}/candidates.parquet")
    osm = a.osm_solar or Path(f"data/labels/{aoi}_overpass_solar.parquet")

    by_area, roof = roofclf_by_area(a.model_dir)
    seg, seg_sum = seg_candidates(aoi, cands, labels_dir, osm)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    by_area.round(4).to_csv(a.out_dir / f"{aoi}_roofclf_precision_by_area.csv", index=False)
    seg.round(2).to_csv(a.out_dir / f"{aoi}_calibration_area_seg_candidates.csv", index=False)
    summary = {"aoi": aoi, "roofclf_fit": str(a.model_dir), "roofclf": roof,
               "segmentation_candidates": str(cands), "osm_solar": str(osm),
               "segmentation": seg_sum}
    (a.out_dir / f"{aoi}_calibration_area_false_positives.json").write_text(
        json.dumps(summary, indent=1, default=float) + "\n")
    print(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
