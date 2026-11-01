#!/usr/bin/env python
"""Give each country's candidate-precision table the confidence split, keeping its evidence.

`calibrate-candidates` derives the split by default (2026-11-01), but re-deriving a
published table from scratch needs every input it was built from as it stood: Pakistan's
30 calibration boxes, Germany's register sample, India's oversize review. This applies
`capacity_calibration.split_ground_by_confidence` to the table as checked in instead: only
the ground bins are split, into confident ground and `LOWCONF_GROUP` (open ground, peak
probability below 0.9: the class `export.low_confidence_rule` drops from lead files),
recounted on the capacity-relevant candidates `density` prices, against the same mapped
reference `calibrate-candidates` uses. Rooftop bins, recall rows, provenance and the
oversize review are untouched.

Prints, per country, the recount against the stored totals and the model's priced
capacity before and after (area x p_real / recall x land or module constant, the
per-candidate pricing; the atlas combines it with OSM, so Best moves by less or more).

    pixi run python scripts/split_calibration_tables.py --out-dir /tmp/split   # dry run
    pixi run python scripts/split_calibration_tables.py --aoi namibia          # writes
    pixi run python scripts/split_calibration_tables.py --aoi germany \\
        --mastr-p-unmapped <scripts/mastr_p_unmapped.py --split output>

A table carrying a measured p_unmapped in its ground bins (Germany's register) is refused
without per-group measurements. Writing goes through `write_table`, whose evidence guard
then refuses any later re-derivation that drops the split.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earthpv import capacity_calibration as cc  # noqa: E402
from earthpv.config import Settings  # noqa: E402
from earthpv.density import (DEFAULT_KWP_PER_M2_LAND, DEFAULT_KWP_PER_M2_MODULE,  # noqa: E402
                             capacity_relevant_candidates, load_osm_screen)
from earthpv.export import load_mapped_reference_attrs  # noqa: E402
from earthpv.labels import resolve_aoi  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402

# The run behind each published atlas, where it is not data/predictions/<aoi>.
PRED = {"nigeria": "data/predictions_v5_nigeria", "france": "data/predictions_v5"}
AOIS = ["pakistan", "india", "germany", "france", "vietnam", "egypt", "yemen", "south_africa",
        "morocco", "poland", "zambia", "nigeria", "namibia"]


def priced_mwp(cands: gpd.GeoDataFrame, table: dict) -> tuple[float, float]:
    """(model MWp, of which low-confidence open ground) under `table`."""
    a = cands["area_m2"].to_numpy(float)
    pl = cands["placement"].astype(str).to_numpy()
    conf = cands["confidence"].to_numpy(float)
    fixed = cands["p_real_fixed"].to_numpy(float) if "p_real_fixed" in cands else None
    p = cc.candidate_p_real(a, table, placement=pl, confidence=conf, fixed=fixed)
    r = cc.candidate_recall(a, table, placement=pl, confidence=conf, fixed=fixed)
    k = np.where(pl == "rooftop", DEFAULT_KWP_PER_M2_MODULE, DEFAULT_KWP_PER_M2_LAND) / 1000.0
    mwp = a * p / r * k
    low = cc._placement_group(pl, conf, cc.default_confidence_split()) == cc.LOWCONF_GROUP
    return float(mwp.sum()), float(mwp[low].sum())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", action="append", help="only these (default: every published one)")
    ap.add_argument("--out-dir", type=Path, help="write here instead of configs/calibration/")
    ap.add_argument("--mastr-p-unmapped", type=Path,
                    help="scripts/mastr_p_unmapped.py --split output (Germany)")
    a = ap.parse_args()

    settings = Settings.load()
    pu = None
    if a.mastr_p_unmapped:
        df = pd.read_csv(a.mastr_p_unmapped)
        pu = {}
        for row in df.itertuples():
            pu.setdefault(str(row.placement), {})[str(row.bin_label)] = (int(row.n), int(row.n_real))
    rows = []
    for aoi in a.aoi or AOIS:
        path = cc.default_table_path(aoi)
        table = cc.load_table(path)
        if table.get("confidence_split"):
            print(f"{aoi}: already split, skipped")
            continue
        _, cfg = resolve_aoi(aoi, settings)
        raw = gpd.read_parquet(ROOT / PRED.get(aoi, "data/predictions") / aoi / "candidates.parquet")
        cands, _ = capacity_relevant_candidates(raw, MAX_CANDIDATE_M2, osm_screen=load_osm_screen(aoi))
        mapped = load_mapped_reference_attrs(aoi, cfg, settings)
        new = cc.split_ground_by_confidence(table, cands, mapped,
                                            p_unmapped_by_group=pu if aoi == "germany" else None)
        before, low_before = priced_mwp(cands, table)
        after, low_after = priced_mwp(cands, new)
        drift = [c for c in new["split_counts"]
                 if (c["recount_n"], c["recount_mapped"]) != (c["stored_n"], c["stored_mapped"])]
        rows.append({"aoi": aoi, "model_mwp_before": round(before, 1),
                     "model_mwp_after": round(after, 1), "change": round(after - before, 1),
                     "lowconf_mwp_before": round(low_before, 1),
                     "lowconf_mwp_after": round(low_after, 1),
                     "bins_recount_drift": len(drift)})
        for c in drift:
            print(f"  {aoi} ground {c['label']}: stored {c['stored_n']}/{c['stored_mapped']} "
                  f"recounted {c['recount_n']}/{c['recount_mapped']}")
        dest = (a.out_dir / path.name) if a.out_dir else path
        if a.out_dir:
            a.out_dir.mkdir(parents=True, exist_ok=True)
        cc.write_table(new, dest)
    pd.set_option("display.width", 200)
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
