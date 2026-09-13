#!/usr/bin/env python
"""Build one pooled roofclf feature table over the OpenPVMapper pseudo-quadrats.

Same `building_table` the real fit uses, so the only thing that differs between this table
and `data/roofclf_france/buildings.geoparquet` is where the labels came from: a model output
with ~30x the supervision, instead of fourteen communes swept by hand.

France runs without `--seg-prob-dir` for the reason documented in
docs/methods/france-validation.md: `building_table` reads segmentation probability from a
SINGLE 0.1 degree cell, and a commune-sized quadrat straddles several, so the feature would
be correct in some quadrats and part-zero in others.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("opvm-table")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", default="data/labels/france_opvm")
    ap.add_argument("--composites", default="data/composites/france")
    ap.add_argument("--out", default="data/roofclf_france_opvm/buildings.geoparquet")
    ap.add_argument("--iso3", default="FRA")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--footprints", choices=["vida", "cadastre"], default="vida",
                    help="vida keeps the imagery-derived default; cadastre pulls the "
                         "authoritative DGFiP layer per INSEE, which finds ~2.3x more "
                         "buildings in France (see docs/experiments.md)")
    ap.add_argument("--checkpoint-every", type=int, default=10)
    args = ap.parse_args()

    from earthpv import overture
    from earthpv.roofclf import building_table

    labels_dir = Path(args.labels_dir)
    man = json.load(open(labels_dir / "manifest.json"))
    if args.limit:
        man = man[: args.limit]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    con = overture.connect()
    parts, t0 = [], time.time()
    for i, m in enumerate(man, 1):
        t1 = time.time()
        bu = None
        if args.footprints == "cadastre":
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from earthpv.labels import geodesic_area_m2
            from test_cadastre_footprints import fetch_cadastre
            insee = str(gpd.read_file(
                labels_dir / f"{m['stem']}_boundary.geojson")["insee"].iloc[0]).zfill(5)
            bu = fetch_cadastre(insee, Path("data/cadastre_france"))[["geometry"]].copy()
            bu["area_m2"] = [geodesic_area_m2(g) for g in bu.geometry]
            bu["id"] = [f"cad-{j}" for j in range(len(bu))]
        try:
            t = building_table(m["stem"], args.iso3, Path(args.composites), None, None,
                               labels_dir=labels_dir, con=con, parcel_label=True, buildings=bu)
        except Exception as e:  # noqa: BLE001
            log.warning("%s FAILED: %s", m["stem"], e)
            continue
        if t.empty:
            log.warning("%s: empty table (no VIDA buildings or no composite)", m["stem"])
            continue
        parts.append(t)
        n = sum(len(p) for p in parts)
        pv = sum(int(p.has_pv.sum()) for p in parts)
        log.info("[%d/%d] %s: %d rows (%d pv) | pooled %d rows, %d pv | %.0fs (%.0fs total)",
                 i, len(man), m["stem"], len(t), int(t.has_pv.sum()), n, pv,
                 time.time() - t1, time.time() - t0)
        if args.checkpoint_every and i % args.checkpoint_every == 0:
            gpd.GeoDataFrame(pd.concat(parts, ignore_index=True)).to_parquet(out)
            log.info("checkpointed %d quadrats -> %s", len(parts), out)

    if not parts:
        raise SystemExit("no tables built")
    tab = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True))
    tab.to_parquet(out)
    log.info("wrote %s: %d buildings, %d with PV (%.2f%%), %d quadrats",
             out, len(tab), int(tab.has_pv.sum()), 100 * tab.has_pv.mean(),
             tab.quadrat.nunique())


if __name__ == "__main__":
    main()
