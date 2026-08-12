"""Mine roofclf hard negatives using glint ABSENCE, conditioned on opportunity.

The n=6 hard-negative retrain (2026-08-09) concluded that the fix for roofclf's bright-roof
false positives is mining more examples of the same pattern nationally, and that no
roofclf-side mining tool existed. This is that tool, with one constraint the earlier work
could not have known about.

**Glint absence is only usable evidence where sensitivity is high, and that is a narrow
population.** From `glint_opportunity`'s fitted per-opportunity rates (2026-08-12), the
probability that a REAL array validates by glint depends on both its size and how many
chances it got. Turning that into the contamination of a mined negative set, at roofclf's
own precision of 0.526 and glint's 0.01 false-validation rate on non-PV:

    bin        best-case sensitivity (E=25)   share of "negatives" that are really PV
    <100                   0.41                          39.8%   unusable
    100-500                0.63                          29.6%   unusable
    500-1k                 0.65                          28.3%   unusable
    1k-5k                  0.88                          11.9%   usable
    5k-50k                 0.92                           7.9%   usable
    >50k                   0.93                           7.5%   usable

So this mines **large roofs at high-opportunity locations only**. That is deliberately not
where roofclf's documented failure mode lives (small bright roofs): below 1,000 m2 a mined
set would be ~30-40% real PV, and training on it would teach the classifier that a third of
real arrays are not arrays, biased specifically toward panels whose pose cannot glint. The
honest scope of this tool is the >= 400 m2 rooftop population that
`roofclf_ge400_capacity` serves, not the sub-400 m2 half.

Every emitted row carries `predicted_sensitivity` and `p_pv_given_no_glint`, so a consumer
can weight or threshold rather than treat all mined negatives as equally certain.

Usage:
  .pixi/envs/default/bin/python scripts/glint_mine_hard_negatives.py --cells 0061_0011,0061_0012
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv import glint_opportunity as go  # noqa: E402

log = logging.getLogger("glint_mine")

START = datetime(2024, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 14, tzinfo=timezone.utc)
PROB_DIR = Path("data/roofclf_national_with_sppi/pakistan/prob")
RATE_TABLE = Path("results/glint_opportunity/glint_rate_by_size.csv")
OUT_DIR = Path("data/glint_hardneg")
ROOFCLF_PRECISION = 0.5264   # sub400_central_summary.json, at the deployment threshold
GLINT_FALSE_RATE = 0.01      # glint_direct_detect: validation rate on random buildings
MIN_ROOF_M2 = 1000.0         # below this the mined set is 28-40% real PV (see docstring)
MAX_CONTAMINATION = 0.25     # refuse to emit a negative less certain than this


def bucket_of(area: np.ndarray) -> np.ndarray:
    edges = [100, 500, 1000, 5000, 50000]
    labels = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
    return np.array([labels[int(np.searchsorted(edges, a, side="right"))] for a in area])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True, help="comma-separated cell ids to mine")
    ap.add_argument("--max-buildings", type=int, default=400)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--max-contamination", type=float, default=MAX_CONTAMINATION,
                    help="refuse to emit a negative whose P(actually PV) exceeds this")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    thr = args.threshold or json.loads(
        Path("data/roofclf/summary.json").read_text())["deployment_threshold"]
    rate = pd.read_csv(RATE_TABLE)
    cells = [c.strip() for c in args.cells.split(",") if c.strip()]

    parts = []
    for c in cells:
        p = PROB_DIR / f"{c}.parquet"
        if not p.exists():
            log.warning("no scoring output for cell %s", c)
            continue
        d = gpd.read_parquet(p)
        sel = d[(d.p_roofclf >= thr) & (d.roof_area_m2 >= MIN_ROOF_M2)].copy()
        sel["cell"] = c
        parts.append(sel)
    if not parts:
        raise SystemExit("no candidate buildings")
    cand = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    log.info("%d flagged buildings >= %.0f m2 across %d cells", len(cand), MIN_ROOF_M2, len(cells))

    # Anything OSM already maps, or the segmentation model already found, is likely real PV
    # and must not be mined as a negative.
    from earthpv.export import new_lead_mask

    osm = gpd.read_parquet("data/labels/pakistan_overpass_solar.parquet")
    cand = cand[new_lead_mask(cand, osm, min_distance_m=30.0)].reset_index(drop=True)
    seg = gpd.read_parquet("data/predictions/pakistan/candidates.parquet")
    cand = cand[new_lead_mask(cand, seg, min_distance_m=30.0)].reset_index(drop=True)
    log.info("%d remain after excluding anything OSM-mapped or already detected", len(cand))
    if cand.empty:
        raise SystemExit("nothing left to mine")

    cand = cand.sort_values("roof_area_m2", ascending=False).head(args.max_buildings)
    cand = cand.reset_index(drop=True)
    cand["pid"] = [f"hn_{i:05d}" for i in range(len(cand))]
    reps = cand.geometry.representative_point()
    cand["lon"], cand["lat"] = reps.x.to_numpy(), reps.y.to_numpy()
    cand["bucket"] = bucket_of(cand.roof_area_m2.to_numpy())

    # Opportunity is computed ONCE PER CELL, not per building. Every building in a 0.1 deg
    # cell is seen by the same scenes, and `TileAngles.at` interpolates a coarse per-granule
    # angle grid across which an 11 km cell moves the view angle by a fraction of a degree --
    # far below the 6 deg tolerance this feeds. Doing it per building meant 400 redundant
    # STAC searches for 2 distinct answers.
    centres = (cand.groupby("cell")[["lon", "lat"]].mean().reset_index()
               .rename(columns={"cell": "pid"}))
    log.info("computing glint opportunity for %d cells (%d buildings) ...",
             len(centres), len(cand))
    cell_opp = go.target_opportunities(centres, START, END, workers=4, n_threads=8)
    cand = cand.merge(cell_opp.rename(columns={"pid": "cell"}), on="cell", how="left")
    cand["predicted_sensitivity"] = go.predicted_sensitivity(
        cand.expected_opportunities.to_numpy(), cand.bucket.to_numpy(), rate)
    s = cand.predicted_sensitivity.to_numpy()
    cand["p_pv_given_no_glint"] = (
        ROOFCLF_PRECISION * (1 - s)
        / (ROOFCLF_PRECISION * (1 - s) + (1 - ROOFCLF_PRECISION) * (1 - GLINT_FALSE_RATE))
    )
    usable = cand[cand.p_pv_given_no_glint <= args.max_contamination].reset_index(drop=True)
    log.info("%d of %d buildings reach usable sensitivity (contamination <= %.0f%%)",
             len(usable), len(cand), 100 * args.max_contamination)
    if usable.empty:
        cand.to_parquet(OUT_DIR / "candidates_scored.parquet")
        raise SystemExit(
            "no building reaches usable glint sensitivity here -- mining would produce a "
            "negative set too contaminated to train on. Scored candidates written for "
            "inspection; pick higher-opportunity cells or accept that glint cannot mine here.")

    log.info("pulling glint series for %d buildings ...", len(usable))
    series = glint.tile_scene_series_batch(
        usable[["pid", "geometry", "lon", "lat"]], START, END, max_workers=5, use_scl=True)
    fits = []
    for r in usable.itertuples():
        df = series.get(r.pid)
        fit = glint.spike_fit(df) if df is not None and not df.empty else dict(
            n_scenes=0, n_clear=0, n_spikes=0, n_cloud_vetoed=0, n_consistent=0)
        fits.append(dict(pid=r.pid, **{k: fit.get(k) for k in
                                       ("n_scenes", "n_clear", "n_spikes",
                                        "n_cloud_vetoed", "n_consistent")}))
    usable = usable.merge(pd.DataFrame(fits), on="pid", how="left")

    # A building with too few usable scenes was not actually tested, whatever its predicted
    # opportunity said -- silence there is missing data, not evidence.
    tested = usable[usable.n_clear.fillna(0) >= 30]
    negatives = tested[tested.n_consistent.fillna(0) == 0].reset_index(drop=True)
    glinted = tested[tested.n_consistent.fillna(0) >= 2]
    log.info("tested %d; %d never glinted (mined as negatives), %d validated as real PV",
             len(tested), len(negatives), len(glinted))

    usable.to_parquet(OUT_DIR / "candidates_scored.parquet")
    negatives.to_parquet(OUT_DIR / "mined_negatives.parquet")
    (OUT_DIR / "mining_summary.json").write_text(json.dumps(dict(
        cells=cells, threshold=thr, min_roof_m2=MIN_ROOF_M2,
        n_flagged=int(len(cand)), n_usable_sensitivity=int(len(usable)),
        n_tested=int(len(tested)), n_mined_negatives=int(len(negatives)),
        n_glint_validated=int(len(glinted)),
        mean_predicted_sensitivity=float(negatives.predicted_sensitivity.mean())
        if len(negatives) else None,
        mean_contamination=float(negatives.p_pv_given_no_glint.mean()) if len(negatives) else None,
    ), indent=2))
    print(f"\nmined {len(negatives)} hard negatives -> {OUT_DIR/'mined_negatives.parquet'}")
    if len(negatives):
        print(f"  mean predicted glint sensitivity {negatives.predicted_sensitivity.mean():.2f}")
        print(f"  mean expected contamination      {negatives.p_pv_given_no_glint.mean():.1%}")


if __name__ == "__main__":
    main()
