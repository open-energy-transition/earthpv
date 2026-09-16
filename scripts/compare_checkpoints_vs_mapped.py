"""Two checkpoints, one country, scored against its mapped OpenStreetMap installations.

WHAT THIS MEASURES, AND WHAT IT DOES NOT. Recall over mapped features only: of the OSM
installations the pipeline actually imaged, how many did each checkpoint's candidate set
find? Precision is deliberately NOT reported, for the same reason
`france_validation.mapped_vs_earthpv` declines to report it -- an unmatched candidate in a
country with 1,144 mapped features is overwhelmingly likely to be a genuinely unmapped
installation rather than a false positive, so a "precision" number here would mostly
measure how incomplete OpenStreetMap is. Recall over mapped installations is the half that
survives: a polygon somebody drew on the ground is a fair thing to require a detector to
find.

THREE THINGS THAT WOULD OTHERWISE MAKE THIS LIE.

  1. A feature in a cell that was never inferred must not read as a miss. That is the one
     way this measurement silently produces a wrong answer, and it is why every reference
     is pushed through `capacity_calibration.coverage_filter` against each checkpoint's
     OWN probability rasters before anything is counted.
  2. The two checkpoints must be scored over the SAME features, or the comparison is
     between two different questions. The reference is therefore intersected down to the
     features both checkpoints imaged, and the script says how many that dropped.
  3. OSM reference polygons are dissolved first (`labels.dissolve_overlapping`): a
     `power=plant` perimeter with a nested `power=generator` way is one installation, and
     counting it twice weights the recall estimate toward whatever got mapped twice.

The population shape block is reported alongside because that is where the France v4->v5
difference actually showed up: median candidate area moved 8,301 -> 1,400 m2 and the
rooftop share 26.9% -> 50.3% while TOTAL candidate area went DOWN, which a pooled recall
number alone would have hidden entirely.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.capacity_calibration import BIN_LABELS, bin_index, coverage_filter  # noqa: E402
from earthpv.export import new_lead_mask  # noqa: E402
from earthpv.labels import dissolve_overlapping, geodesic_area_m2  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval. Normal approximation is useless at the counts involved here."""
    if n == 0:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", type=Path, required=True,
                    help="placement-classified OSM pull, e.g. data/labels/<aoi>_overpass_solar.parquet")
    ap.add_argument("--model", action="append", required=True, metavar="NAME:CANDIDATES:PROBDIR",
                    help="repeatable: a label, its candidates.parquet, and its prob raster dir")
    ap.add_argument("--min-area-m2", type=float, default=400.0,
                    help="reference floor; 400 = the segmentation floor this product targets")
    ap.add_argument("--min-distance-m", type=float, default=100.0,
                    help="a candidate within this distance of a mapped feature counts as "
                         "having found it (the `export --min-distance-m` convention: an OSM "
                         "node or an offset footprint never literally intersects)")
    a = ap.parse_args()

    models = []
    for spec in a.model:
        name, cand, prob = spec.split(":", 2)
        models.append((name, Path(cand), Path(prob)))

    ref = gpd.read_parquet(a.labels)
    ref = ref[ref.geometry.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    ref = dissolve_overlapping(ref)
    ref["area_m2"] = [geodesic_area_m2(g) for g in ref.geometry]
    ref = ref[ref.area_m2 >= a.min_area_m2].reset_index(drop=True)
    print(f"reference: {len(ref)} dissolved OSM polygons >= {a.min_area_m2:,.0f} m2\n")

    # Restrict to what BOTH checkpoints imaged, so the two are answering one question.
    covered = None
    for name, _, prob in models:
        c = coverage_filter(ref, prob)
        print(f"  {name}: imaged {len(c)} of {len(ref)}")
        ids = set(c["id"]) if "id" in c.columns else set(c.index)
        covered = ids if covered is None else (covered & ids)
    key = ref["id"] if "id" in ref.columns else ref.index.to_series()
    ref = ref[key.isin(covered)].reset_index(drop=True)
    print(f"  scored over the {len(ref)} imaged by all {len(models)} checkpoint(s)\n")
    if ref.empty:
        print("nothing imaged in common -- cannot compare")
        return 1

    ridx = bin_index(ref.area_m2.values)

    print("RECALL OVER MAPPED INSTALLATIONS (95% Wilson)")
    header = f"{'size bin':>10} {'n':>5}"
    for name, _, _ in models:
        header += f" | {name:>22}"
    print(header)
    results = {}
    for name, cand_path, _ in models:
        cand = gpd.read_parquet(cand_path)
        # Same exclusion `density` applies: polygonize_chips merges touching thresholded
        # pixels with no upper bound, so a connected sheet of false positives can become
        # one multi-km2 "installation" that would match everything near it.
        if "area_m2" in cand.columns:
            cand = cand[cand.area_m2 <= MAX_CANDIDATE_M2].reset_index(drop=True)
        results[name] = (~new_lead_mask(ref, cand, min_distance_m=a.min_distance_m), cand)

    for b, label in enumerate(BIN_LABELS):
        in_bin = ridx == b
        n = int(in_bin.sum())
        if n == 0:
            continue
        row = f"{label:>10} {n:>5}"
        for name, _, _ in models:
            k = int(results[name][0][in_bin].sum())
            lo, hi = wilson(k, n)
            row += f" | {k:>3}/{n:<3} {k/n:>5.3f} {lo:.2f}-{hi:.2f}"
        print(row)
    row = f"{'POOLED':>10} {len(ref):>5}"
    for name, _, _ in models:
        k = int(results[name][0].sum())
        lo, hi = wilson(k, len(ref))
        row += f" | {k:>3}/{len(ref):<3} {k/len(ref):>5.3f} {lo:.2f}-{hi:.2f}"
    print(row)

    # McNemar's discordant pairs: the only honest read of "is one better", since the two
    # checkpoints are scored on the SAME installations and the counts are small.
    if len(models) == 2:
        (n1, _, _), (n2, _, _) = models
        m1, m2 = results[n1][0], results[n2][0]
        b_only, a_only = int((m1 & ~m2).sum()), int((m2 & ~m1).sum())
        print(f"\ndiscordant: {n1} only {b_only}, {n2} only {a_only}, "
              f"both {int((m1 & m2).sum())}, neither {int((~m1 & ~m2).sum())}")
        if b_only + a_only:
            print("  (McNemar exact two-sided p = "
                  f"{min(1.0, 2 * sum(math.comb(b_only + a_only, i) for i in range(min(b_only, a_only) + 1)) / 2 ** (b_only + a_only)):.3f})")

    print("\nCANDIDATE POPULATION SHAPE (where v4->v5 actually moved in France)")
    print(f"{'model':>22} {'candidates':>11} {'median m2':>10} {'total km2':>10} "
          f"{'rooftop':>8} {'>=10k m2':>9}")
    for name, _, _ in models:
        c = results[name][1]
        ar = c.area_m2.values if "area_m2" in c.columns else np.array([])
        roof = (c.placement == "rooftop").mean() if "placement" in c.columns else float("nan")
        print(f"{name:>22} {len(c):>11,} {np.median(ar):>10,.0f} {ar.sum()/1e6:>10.1f} "
              f"{100*roof:>7.1f}% {int((ar >= 10_000).sum()):>9,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
