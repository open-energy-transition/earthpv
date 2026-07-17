"""Does gating a lowered detection threshold by building-roof-axis orientation
(a free, universal, zero-network proxy for "this roof plausibly supports a
south-facing panel") recover more true positives than blanket threshold lowering,
without blanket lowering's IoU cost?

Rationale (see conversation): `glint_iou_experiment.py` already showed unconditional
threshold lowering hurts IoU everywhere (false positives grow faster than true
positives). Gating by glint validation helped narrowly, but glint is expensive and
retrospective (you need a candidate to already exist). Gating by building orientation
is cheap and available for every rooftop a priori -- IF orientation actually predicts
where the model under-detects. This tests that premise directly, restricted to
`kind == "generator"` (rooftop) targets, since ground-mount plants have no building
to take an axis from.

Caveat baked into the design, not glossed over: Pakistan's dominant urban roof type is
flat concrete, where a tilt-frame's azimuth is NOT constrained by the roof's footprint
shape the way a pitched roof's ridge line would constrain it. So this proxy may simply
not predict real installed orientation here -- that's an open empirical question this
script answers, not an assumption.

Usage:
  .pixi/envs/default/bin/python scripts/roof_axis_iou_experiment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv.config import DATA_DIR  # noqa: E402
from glint_iou_experiment import T_BASE, load_targets, pred_plain, prob_raster_index, read_window  # noqa: E402

BUILDINGS_FILE = DATA_DIR / "predictions" / "pakistan" / "density" / "buildings.geoparquet"
MATCH_BUFFER_M = 60.0
SOUTH_GATE_DEG = 35.0  # "plausibly south-facing" cutoff on the roof axis's best facing option


def long_axis_bearing(geom) -> float:
    mrr = geom.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)
    edges = [
        (np.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1]), coords[i], coords[i + 1])
        for i in range(4)
    ]
    edges.sort(key=lambda e: -e[0])
    (x0, y0), (x1, y1) = edges[0][1], edges[0][2]
    return np.degrees(np.arctan2(x1 - x0, y1 - y0)) % 180


def south_gap_deg(ridge_bearing_mod180: float) -> float:
    """Angular distance from due south (180) of whichever of the roof's two possible
    PANEL-FACING directions is closer to south. A row of panels mounted along the
    roof's long axis (the ridge) faces PERPENDICULAR to that axis, not along it --
    so the two facing options are ridge+90 and ridge+270, not ridge and ridge+180.
    0 = a facing option points exactly south; 90 = the roof's long axis runs exactly
    north-south, so both facing options point due east/west (worst case)."""
    facing_a = (ridge_bearing_mod180 + 90) % 360
    facing_b = (ridge_bearing_mod180 + 270) % 360

    def circ_dist(x: float, target: float = 180.0) -> float:
        d = abs(x - target) % 360
        return min(d, 360 - d)

    return min(circ_dist(facing_a), circ_dist(facing_b))


def main() -> None:
    tgts = load_targets()
    gens = tgts[tgts.kind == "generator"].reset_index(drop=True)
    idx = prob_raster_index()
    reps = gpd.GeoDataFrame(gens[["pid"]], geometry=gens.geometry.representative_point(), crs="EPSG:4326")
    hits = gpd.sjoin(reps, idx, predicate="within", how="left").drop_duplicates("pid")
    gens = gens.merge(hits[["pid", "path"]], on="pid", how="left")
    gens = gens[gens.path.notna()].reset_index(drop=True)
    print(f"{len(gens)} generator-kind targets with a covering prob raster")

    buildings = gpd.read_parquet(BUILDINGS_FILE)
    b_sindex = buildings.sindex
    buf_deg = MATCH_BUFFER_M / 111_000

    south_gaps = []
    for r in tqdm(gens.itertuples(), total=len(gens), desc="roof axis match"):
        cand_idx = b_sindex.query(r.geometry.buffer(buf_deg), predicate="intersects")
        if len(cand_idx) == 0:
            south_gaps.append(np.nan)
            continue
        near = buildings.iloc[cand_idx]
        utm_crs = gpd.GeoSeries([r.geometry], crs="EPSG:4326").estimate_utm_crs()
        target_utm = gpd.GeoSeries([r.geometry], crs="EPSG:4326").to_crs(utm_crs).iloc[0]
        near_utm = near.geometry.to_crs(utm_crs)
        nearest = near_utm.distance(target_utm).idxmin()
        axis = long_axis_bearing(near_utm.loc[nearest])
        south_gaps.append(south_gap_deg(axis))
    gens["south_gap"] = south_gaps
    n_matched = gens.south_gap.notna().sum()
    print(f"{n_matched}/{len(gens)} matched to a building within {MATCH_BUFFER_M:.0f} m")

    gens["south_plausible"] = gens.south_gap <= SOUTH_GATE_DEG

    strategies = [("t=0.30 baseline", None, T_BASE)]
    for t in (0.20, 0.15, 0.10, 0.05):
        strategies.append((f"unconditional t={t:.2f}", None, t))
        strategies.append((f"south-plausible-gated t={t:.2f}", True, t))
        strategies.append((f"NOT-south-plausible-gated t={t:.2f}", False, t))

    acc = {name: np.zeros(3, dtype=np.int64) for name, _, _ in strategies}
    n_eval = 0
    for r in gens.itertuples():
        rw = read_window(r.path, r.geometry)
        if rw is None:
            continue
        prob, gt = rw
        n_eval += 1
        base = pred_plain(prob, T_BASE)
        for name, gate, t in strategies:
            if gate is None:
                pred = pred_plain(prob, t)
            elif gate is True:
                pred = pred_plain(prob, t) if r.south_plausible else base
            else:
                pred = pred_plain(prob, t) if not r.south_plausible else base
            tp = int((pred & gt).sum())
            fp = int((pred & ~gt).sum())
            fn = int((~pred & gt).sum())
            acc[name] += (tp, fp, fn)

    n_south = int(gens.south_plausible.sum())
    print(f"\n{n_eval} generator targets evaluated; {n_south} south-plausible "
          f"(south_gap <= {SOUTH_GATE_DEG} deg), {n_matched - n_south} not, "
          f"{len(gens) - n_matched} unmatched (left at baseline)")
    print(f"south_gap distribution: median={gens.south_gap.median():.1f}, "
          f"p25={gens.south_gap.quantile(.25):.1f}, p75={gens.south_gap.quantile(.75):.1f}")

    rows = []
    for name, _, _ in strategies:
        tp, fp, fn = acc[name]
        rows.append({"strategy": name, "IoU": tp / max(tp + fp + fn, 1), "tp": tp, "fp": fp, "fn": fn})
    table = pd.DataFrame(rows).round(4)
    print("\n=== window IoU (generator-kind only) ===")
    print(table.to_string(index=False))
    table.to_csv(DATA_DIR / "glint" / "roof_axis_iou_experiment.csv", index=False)


if __name__ == "__main__":
    main()
