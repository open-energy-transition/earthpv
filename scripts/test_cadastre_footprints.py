#!/usr/bin/env python
"""Does roofclf's French result change if the footprints are authoritative?

`roofclf` reads VIDA Open Buildings, which is imagery-derived: in Toussieu it finds 672
footprints where the French cadastre finds 3,366, with a median of 146 m2 against 22 m2.
Bad footprints would degrade three things at once -- the roof-area feature (the single
strongest one), the zonal spectral means (computed over the wrong pixels), and the label
itself (mapped PV intersected with the footprint). So "the sensor cannot see 20 m2 arrays"
and "the footprints are wrong" are confounded until this is run.

The cadastre (DGFiP via Etalab) is published per commune keyed by INSEE, which is exactly
the unit the French quadrats already use, and is authoritative rather than modelled. Overture
carries essentially the same French footprints (3,826 in the Toussieu bbox) but needs a
global S3 scan at ~166 s per commune against the cadastre's ~2 s, and its release directory
is pruned to the last two releases, so a pinned release string dies silently.

Everything else is held fixed: same `building_table`, same features, same parcel label, same
leave-one-quadrat-out protocol, same hand-mapped labels. Only the footprint layer changes.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cadastre")

URL = ("https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes/"
       "{dep}/{insee}/cadastre-{insee}-batiments.json.gz")


def fetch_cadastre(insee: str, cache: Path) -> gpd.GeoDataFrame:
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"cadastre-{insee}-batiments.json"
    if not f.exists():
        dep = insee[:3] if insee.startswith("97") else insee[:2]
        req = urllib.request.Request(URL.format(dep=dep, insee=insee),
                                     headers={"User-Agent": "earthpv/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            f.write_bytes(gzip.decompress(r.read()))
    g = gpd.read_file(f).to_crs("EPSG:4326")
    return g[g.geometry.notna() & g.geometry.is_valid].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", default="data/labels/france")
    ap.add_argument("--composites", default="data/composites/france")
    ap.add_argument("--cache", default="data/cadastre_france")
    ap.add_argument("--out-table", default="data/roofclf_france_cadastre/buildings.geoparquet")
    ap.add_argument("--out", default="results/france_roofclf_cadastre_control.json")
    ap.add_argument("--exclude", default="saint_gely_du_fesc",
                    help="not Rule-1 complete; excluded from every fit")
    args = ap.parse_args()

    from earthpv.labels import geodesic_area_m2
    from earthpv.roofclf import (MODEL_FEATURES, auc, auc_within_size, building_table,
                                 design_matrix, fit_logistic, predict_proba)

    labels_dir = Path(args.labels_dir)
    stems = sorted(p.name[: -len("_boundary.geojson")]
                   for p in labels_dir.glob("*_boundary.geojson"))
    stems = [s for s in stems if args.exclude not in s]

    parts, cmp_rows = [], []
    for stem in stems:
        bnd = gpd.read_file(labels_dir / f"{stem}_boundary.geojson")
        insee = str(bnd["insee"].iloc[0]).zfill(5)
        cad = fetch_cadastre(insee, Path(args.cache))
        cad = cad[["geometry"]].copy()
        cad["area_m2"] = [geodesic_area_m2(g) for g in cad.geometry]
        cad["id"] = [f"cad-{i}" for i in range(len(cad))]
        t = building_table(stem, "FRA", Path(args.composites), None, None,
                           labels_dir=labels_dir, parcel_label=True, buildings=cad)
        if t.empty:
            log.warning("%s: empty table", stem)
            continue
        parts.append(t)
        cmp_rows.append({"quadrat": stem, "insee": insee, "cadastre_buildings": len(t),
                         "cadastre_pv": int(t.has_pv.sum()),
                         "cadastre_base_rate": round(float(t.has_pv.mean()), 4),
                         "cadastre_median_roof_m2": round(float(t.roof_area_m2.median()), 1)})
        log.info("%s: %d cadastre buildings, %d with PV (%.2f%%)",
                 stem, len(t), int(t.has_pv.sum()), 100 * t.has_pv.mean())

    tab = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True))
    Path(args.out_table).parent.mkdir(parents=True, exist_ok=True)
    tab.to_parquet(args.out_table)

    feats = list(MODEL_FEATURES)
    rows = []
    for q in sorted(tab.quadrat.unique()):
        te = tab[tab.quadrat == q]
        tr = tab[tab.quadrat != q]
        if te.has_pv.sum() == 0 or tr.has_pv.sum() == 0:
            continue
        m = fit_logistic(design_matrix(tr, feats), tr.has_pv.to_numpy(float))
        p = predict_proba(m, design_matrix(te, feats))
        y = te.has_pv.to_numpy(float)
        ws, _ = auc_within_size(y, p, te.roof_area_m2.to_numpy())
        rows.append({"quadrat": q, "n": len(te), "n_pv": int(y.sum()),
                     "auc": round(float(auc(y, p)), 4),
                     "auc_within_size": round(float(ws), 4)})
    per = pd.DataFrame(rows)

    vida = gpd.read_parquet("data/roofclf_france/buildings.geoparquet")
    BASE_AUC, BASE_WS = 0.7103, 0.6274
    out = {
        "footprint_source": "DGFiP cadastre via Etalab (per-commune, authoritative)",
        "cadastre": {"buildings": int(len(tab)), "positives": int(tab.has_pv.sum()),
                     "base_rate": round(float(tab.has_pv.mean()), 4),
                     "median_roof_m2": round(float(tab.roof_area_m2.median()), 1),
                     "median_fold_auc": round(float(per.auc.median()), 4),
                     "median_fold_auc_within_size": round(float(per.auc_within_size.median()), 4)},
        "vida_baseline": {"buildings": int(len(vida)), "positives": int(vida.has_pv.sum()),
                          "base_rate": round(float(vida.has_pv.mean()), 4),
                          "median_roof_m2": round(float(vida.roof_area_m2.median()), 1),
                          "median_fold_auc": BASE_AUC,
                          "median_fold_auc_within_size": BASE_WS},
        "delta": {"median_auc": round(float(per.auc.median()) - BASE_AUC, 4),
                  "median_auc_within_size": round(float(per.auc_within_size.median()) - BASE_WS, 4)},
        "per_quadrat": per.to_dict("records"),
        "per_quadrat_counts": cmp_rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))

    print("\nper commune (cadastre footprints, LOQO):")
    print(per.to_string(index=False))
    print(f"\n{'':<34}{'buildings':>11}{'pv':>7}{'base%':>8}{'medm2':>8}{'AUC':>9}{'within':>9}")
    c, v = out["cadastre"], out["vida_baseline"]
    print(f"{'VIDA (published baseline)':<34}{v['buildings']:>11,}{v['positives']:>7,}"
          f"{100*v['base_rate']:>8.2f}{v['median_roof_m2']:>8.0f}{v['median_fold_auc']:>9.4f}"
          f"{v['median_fold_auc_within_size']:>9.4f}")
    print(f"{'Cadastre (authoritative)':<34}{c['buildings']:>11,}{c['positives']:>7,}"
          f"{100*c['base_rate']:>8.2f}{c['median_roof_m2']:>8.0f}{c['median_fold_auc']:>9.4f}"
          f"{c['median_fold_auc_within_size']:>9.4f}")
    print(f"{'  delta':<34}{'':>11}{'':>7}{'':>8}{'':>8}"
          f"{out['delta']['median_auc']:>+9.4f}{out['delta']['median_auc_within_size']:>+9.4f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
