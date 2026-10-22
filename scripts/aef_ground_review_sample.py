"""A stratified review sample of unmapped ground-mount candidates, by AlphaEarth change score.

`aef_large_array_change.py` estimates the share of unmapped ground detections that are real
from a score mixture. That estimate leans on an assumption it cannot check itself: that a
false positive changes like the land around it. Human review of a sample with KNOWN
inclusion probabilities checks it, and turns the score into a calibrated precision. It is
the same move the glint validation made for `p_unmapped`.

Strata are terciles of the `learned` (change-only) score over the unmapped ground candidates
scored there, `--per-stratum` drawn at random from each (seeded), so a stratum's verdicts
weight back to the population by its size. `learned`, not `learned_level`, because a blind
review of 48 of these (`aef_render_review_tiles.py`) found the level-including score passes
static look-alikes, forest, rock and motorways, that the change-only score rejects. Each feature carries the Esri World Imagery capture date at its
centre, the layer a JOSM or iD reviewer sees: a capture before `--recent` cannot confirm an
installation the composite shows, and its verdict should be "imagery too old", not "no PV".

    pixi run python scripts/aef_ground_review_sample.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from propose_calibration_candidates import esri_capture  # noqa: E402

SCORES = Path("results/aef_large_array_change_scores.csv")
POP = Path("results/aef_large_array_change_population.parquet")
OUT = Path("results/aef_ground_review")
SEED = 20261022


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-stratum", type=int, default=25)
    ap.add_argument("--score", default="learned")
    ap.add_argument("--recent", default="2025-01-01")
    args = ap.parse_args()

    s = pd.read_csv(SCORES)
    pop = gpd.read_parquet(POP)[["obj_id", "geometry"]]
    u = s[(s.role == "unmapped") & (s.placement2 == "ground")].dropna(subset=[args.score]).copy()
    u["stratum"] = pd.qcut(u[args.score], 3, labels=["low", "mid", "high"]).astype(str)
    rng = np.random.default_rng(SEED)
    picks = []
    for st, g in u.groupby("stratum"):
        k = min(args.per_stratum, len(g))
        picks.append(g.loc[rng.choice(g.index.to_numpy(), size=k, replace=False)])
    r = pd.concat(picks)
    r = gpd.GeoDataFrame(r.merge(pop, on="obj_id"), geometry="geometry", crs=4326)
    dates = []
    for g in r.geometry:
        p = g.representative_point()
        cap = esri_capture(p.x, p.y)
        dates.append(cap["date"].isoformat() if cap else None)
    r["imagery_date"] = dates
    r["imagery_recent"] = [d is not None and d >= args.recent for d in dates]
    r["verdict"] = ""  # pv | no_pv | imagery_too_old | unsure
    r["note"] = ""
    OUT.mkdir(parents=True, exist_ok=True)
    keep = ["obj_id", "stratum", args.score, "change", "bin", "area_m2", "imagery_date",
            "imagery_recent", "verdict", "note", "geometry"]
    r[keep].to_file(OUT / "review.geojson", driver="GeoJSON")
    r[keep[:-1]].to_csv(OUT / "review_log.csv", index=False)
    sizes = u.stratum.value_counts().to_dict()
    meta = {"score": args.score, "seed": SEED, "per_stratum": args.per_stratum,
            "stratum_population": sizes,
            "stratum_bounds": {st: [round(float(g[args.score].min()), 4),
                                    round(float(g[args.score].max()), 4)]
                               for st, g in u.groupby("stratum")},
            "n_imagery_recent": int(r.imagery_recent.sum()), "n": int(len(r)),
            "recent_cutoff": args.recent}
    (OUT / "review_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
