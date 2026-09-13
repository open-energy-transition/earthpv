#!/usr/bin/env python
"""Fit Germany's roofclf on the best measured training mix and score every cell.

**Preliminary by construction, and labelled as such.** Germany has no exhaustively mapped
calibration quadrats, so the classifier is trained on OSM labels that mark ~3.6% of registered
rooftop units. That is enough to RANK roofs (median fold AUC 0.824) but not to fit a coverage
ratio, because the true PV area on a flagged roof cannot be measured from a 3.6% sample.

**The way round it is that Germany does not need quadrats for the capacity half.** MaStR is
complete, so kWp per unit of credited roof area is fitted directly against the register per
municipality, which is a stronger calibration than a transferred quadrat ratio rather than a
weaker one. That is `validate_sub400_against_mastr.py`, run after this.

**Two measured caveats travel with any number this produces**, both from that validation:
total roof area times a constant beats this estimator in Germany (23.0% against 58.4% median
municipal error, the reverse of Pakistan where roofclf wins 3.4x), and the cross-validated
national total came out at 1.003 while the median municipality was off by 53%, so a national
total agreeing with the register is not evidence that the geography is right.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-prod")

SETS = {
    "germany": ["data/roofclf_germany/buildings.geoparquet"],
    "germany+fr_national": ["data/roofclf_germany/buildings.geoparquet",
                            "data/roofclf_france_opvm/buildings.geoparquet"],
    "germany+fr_border": ["data/roofclf_germany/buildings.geoparquet",
                          "data/roofclf_france_border/buildings.geoparquet"],
    "germany+both": ["data/roofclf_germany/buildings.geoparquet",
                     "data/roofclf_france_opvm/buildings.geoparquet",
                     "data/roofclf_france_border/buildings.geoparquet"],
    "fr_border": ["data/roofclf_france_border/buildings.geoparquet"],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mix", choices=sorted(SETS), required=True)
    ap.add_argument("--out-dir", default="data/roofclf_germany_prod")
    ap.add_argument("--prob-dir", default="data/roofclf_national_germany_prod/germany/prob")
    ap.add_argument("--composites", default="data/composites/germany")
    ap.add_argument("--cells-csv", default=None, help="omit to score every cell")
    ap.add_argument("--fit-only", action="store_true")
    args = ap.parse_args()

    from earthpv.roofclf import (MODEL_FEATURES, design_matrix, fit_logistic, save_model,
                                 score_buildings_national)

    feats = list(MODEL_FEATURES)
    parts = [gpd.read_parquet(p) for p in SETS[args.mix]]
    tr = pd.concat(parts, ignore_index=True)
    log.info("mix %s: %d buildings, %d with PV (%.2f%%) from %d source(s)",
             args.mix, len(tr), int(tr.has_pv.sum()), 100 * tr.has_pv.mean(), len(parts))

    model = fit_logistic(design_matrix(tr, feats), tr.has_pv.to_numpy(float))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_model(model, feats, out / "model_full.json")
    # No deployment_threshold is written on purpose. Germany's LOQO threshold search returns
    # a value above 1.0 with zero buildings flagged, because a 0.5 precision target is
    # unreachable when ~96% of true positives are unlabelled. Downstream weights roofs by
    # probability instead, so an unreachable threshold cannot silently zero every cell.
    (out / "summary.json").write_text(json.dumps({
        "mix": args.mix,
        "sources": SETS[args.mix],
        "n_buildings": int(len(tr)),
        "n_pv": int(tr.has_pv.sum()),
        "base_rate": round(float(tr.has_pv.mean()), 5),
        "features": feats,
        "deployment_threshold": None,
        "threshold_note": (
            "omitted deliberately: unreachable on 3.6%-complete OSM labels; use "
            "probability weighting (validate_sub400_against_mastr.py --weight prob)"),
        "status": "PRELIMINARY - no exhaustively mapped German quadrats exist",
    }, indent=2))
    log.info("wrote %s", out / "model_full.json")
    if args.fit_only:
        return

    cells = (set(pd.read_csv(args.cells_csv).cell.astype(str))
             if args.cells_csv else None)
    log.info("scoring %s cells", len(cells) if cells else "ALL")
    score_buildings_national("germany", model, feats, Path(args.composites),
                             Path(args.prob_dir), cells=cells)
    log.info("done -> %s", args.prob_dir)


if __name__ == "__main__":
    main()
