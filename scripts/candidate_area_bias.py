#!/usr/bin/env python
"""How large is a segmentation candidate's outline against the array it found?

`density` converts a candidate's whole polygon area to capacity, scaled by `p_real` and
divided by recall, and both of those count installations, not area. So if a real
candidate's 10 m outline is systematically larger or smaller than its array, that factor
passes straight into every `est_mwp_*` figure (the attribution gap in
`docs/methods/density.md` is the same polygon seen from the building side). Measured on
candidates that found a mapped installation, before `postprocess.replace_with_osm_geometry`
swaps in the mapped outline, so pass the pre-replacement candidates:

- `area_ratio`: summed candidate area over the summed (dissolved) OSM area it found. Each
  OSM installation is credited to the one candidate that overlaps it most, so a merged
  neighbour counts once and a fragment of a split installation counts as no match.
- `overdraw`: the share of candidate area outside every mapped installation. False area
  inside a Rule-1 quadrat; false area OR unmapped PV elsewhere, so nationally an upper bound.
- `coverage`: the share of the found installations' area the candidate covers.

Reported nationally and inside the AOI's Rule-1 calibration areas (complete as of their
mapping imagery), per placement and candidate size bin (the calibration table's own bins).

    python scripts/candidate_area_bias.py --aoi pakistan \\
        --candidates data/predictions/pakistan/candidates_pre_osm_replace_20260729.parquet \\
        --osm-solar data/labels/pakistan_overpass_solar.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EQUAL_AREA = "EPSG:6933"
N_BOOT = 1000


def bin_labels(edges: list[float]) -> list[str]:
    def f(v: float) -> str:
        return f"{v / 1000:g}k" if v >= 1000 else f"{v:g}"
    out = [f"<{f(edges[0])}"] if edges[0] > 0 else []
    out += [f"{f(lo)}-{f(hi)}" for lo, hi in zip(edges[:-1], edges[1:])]
    return out + [f">{f(edges[-1])}"]


def rule1_areas(aoi: str, labels_dir: Path):
    """Union of the AOI's Rule-1 calibration areas (`configs/atlas/<aoi>.yaml`)."""
    from shapely.ops import unary_union

    from earthpv.roofclf import load_boundary

    boxes = yaml.safe_load((ROOT / "configs/atlas" / f"{aoi}.yaml").read_text())["calibration_boxes"]
    stems = [b["stem"] for b in boxes if b.get("status") == "rule1"
             and (labels_dir / f"{b['stem']}_boundary.geojson").exists()]
    return stems, unary_union([load_boundary(labels_dir / f"{s}_boundary.geojson") for s in stems])


def summarise(df: pd.DataFrame, rng: np.random.Generator) -> dict:
    m = df[df["true_m2"] > 0]
    if m.empty:
        return {"n_matched": 0}
    ratio = m["cand_m2"].sum() / m["true_m2"].sum()
    idx = rng.integers(0, len(m), (N_BOOT, len(m)))
    boot = m["cand_m2"].to_numpy()[idx].sum(1) / m["true_m2"].to_numpy()[idx].sum(1)
    return {
        "n_matched": int(len(m)), "n_fragments": int(((df["true_m2"] == 0) & (df["inside_m2"] > 0)).sum()),
        "cand_m2": round(float(m["cand_m2"].sum())), "true_m2": round(float(m["true_m2"].sum())),
        "area_ratio": round(float(ratio), 3),
        "area_ratio_ci90": [round(float(x), 3) for x in np.percentile(boot, [5, 95])],
        "median_ratio": round(float((m["cand_m2"] / m["true_m2"]).median()), 3),
        "overdraw": round(float(1 - m["inside_m2"].sum() / m["cand_m2"].sum()), 3),
        "coverage": round(float(m["covered_m2"].sum() / m["true_m2"].sum()), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--candidates", type=Path, required=True,
                    help="candidates BEFORE replace_with_osm_geometry (model outlines)")
    ap.add_argument("--osm-solar", type=Path, required=True)
    ap.add_argument("--labels-dir", type=Path, default=None,
                    help="calibration area boundaries (default data/labels, or data/labels/<aoi>)")
    ap.add_argument("--calibration", type=Path, default=None,
                    help="table whose bin_edges_m2 to use (default configs/calibration/<aoi>_candidate_precision.yaml)")
    ap.add_argument("--out", type=Path, default=None,
                    help="default results/<aoi>_candidate_area_bias.json")
    args = ap.parse_args()
    from earthpv.labels import dissolve_overlapping

    labels_dir = args.labels_dir or (Path("data/labels") if args.aoi == "pakistan"
                                     else Path("data/labels") / args.aoi)
    table = args.calibration or Path(f"configs/calibration/{args.aoi}_candidate_precision.yaml")
    edges = [float(e) for e in yaml.safe_load(table.read_text())["bin_edges_m2"]]
    labels = bin_labels(edges)

    cands = gpd.read_parquet(args.candidates)[["geometry", "area_m2", "placement"]]
    osm = gpd.read_parquet(args.osm_solar)
    osm = osm[osm.geom_type.isin(("Polygon", "MultiPolygon"))]
    osm = dissolve_overlapping(osm, group_col=None)
    c = cands.to_crs(EQUAL_AREA).reset_index(drop=True)
    o = osm.to_crs(EQUAL_AREA).reset_index(drop=True)
    c["geometry"] = shapely.make_valid(c.geometry.to_numpy())
    o["geometry"] = shapely.make_valid(o.geometry.to_numpy())

    pairs = gpd.sjoin(c[["geometry"]], o[["geometry"]], predicate="intersects")
    li, ri = pairs.index.to_numpy(), pairs["index_right"].to_numpy()
    inter = shapely.area(shapely.intersection(c.geometry.to_numpy()[li], o.geometry.to_numpy()[ri]))
    p = pd.DataFrame({"cand": li, "osm": ri, "inter": inter})
    p = p[p["inter"] > 0]
    best = p.sort_values("inter").groupby("osm").tail(1)   # each installation -> one candidate
    o_area = shapely.area(o.geometry.to_numpy())
    c["cand_m2"] = shapely.area(c.geometry.to_numpy())
    c["true_m2"] = best.assign(a=o_area[best["osm"]]).groupby("cand")["a"].sum().reindex(c.index, fill_value=0)
    c["covered_m2"] = best.groupby("cand")["inter"].sum().reindex(c.index, fill_value=0)
    c["inside_m2"] = p.groupby("cand")["inter"].sum().reindex(c.index, fill_value=0)
    c["bin"] = pd.Categorical(np.array(labels)[np.searchsorted(edges, c["area_m2"], side="right")],
                              categories=labels, ordered=True)

    stems, quadrats = rule1_areas(args.aoi, labels_dir)
    in_q = c.to_crs(4326).geometry.representative_point().within(quadrats).to_numpy()
    rng = np.random.default_rng(20261028)
    rows = []
    for scope, part in (("national", c), ("rule1_quadrats", c[in_q])):
        for placement in ("rooftop", "ground", "all"):
            sub = part if placement == "all" else part[part["placement"].eq(placement)
                                                       if placement == "rooftop"
                                                       else ~part["placement"].eq("rooftop")]
            for label, grp in [("all", sub), (">=400 m2", sub[sub["area_m2"] >= 400])] + [
                    (lab, sub[sub["bin"] == lab]) for lab in labels]:
                rows.append({"scope": scope, "placement": placement, "bin": label,
                             "n_candidates": int(len(grp)), **summarise(grp, rng)})
    out = args.out or Path("results") / f"{args.aoi}_candidate_area_bias.json"
    res = pd.DataFrame(rows)
    summary = {"aoi": args.aoi, "candidates": str(args.candidates), "osm_solar": str(args.osm_solar),
               "n_osm_dissolved": int(len(o)), "rule1_quadrats": stems,
               "placement_note": "ground = every candidate not classed rooftop "
                                 "(ground_adjacent and no_building included)",
               "rows": res.to_dict("records")}
    out.write_text(json.dumps(summary, indent=1) + "\n")
    show = res[res["n_matched"].fillna(0) > 0][["scope", "placement", "bin", "n_candidates", "n_matched",
                                                "area_ratio", "area_ratio_ci90", "median_ratio",
                                                "overdraw", "coverage"]]
    pd.set_option("display.width", 220)
    print(show.to_string(index=False))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
