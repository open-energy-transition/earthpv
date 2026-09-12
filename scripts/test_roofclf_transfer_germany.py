#!/usr/bin/env python
"""Does a roofclf fitted elsewhere work in Germany?

Germany sits between the two regimes this project has measured. French rooftop PV is a
~20 m2 patch covering an eighth of its roof and roofclf fails there; Pakistani rooftop PV is
~54 m2 covering a third and roofclf works. Germany's registered fleet is dominated by units
around 8-10 kWp, roughly 45-55 m2 of module, so the prediction is that roofclf should work
better in Germany than in France. This measures it.

Three models are scored on ONE German evaluation set so the comparison is like-for-like:

* the France model trained on OpenPVMapper labels (386,565 buildings, 16,435 positives),
* Pakistan's production model (123,867 buildings, 17,150 positives),
* a Germany in-domain fit, leave-one-cell-out, as the ceiling for this evaluation set.

**The German truth is OSM, and OSM is not complete.** Germany's OSM covers roughly 3.6% of
registered rooftop units, so a building with no OSM array is not reliably a negative: most
German rooftop PV is unmapped. That attenuates every AUC reported here, in the same direction
for every model. The absolute numbers are therefore lower bounds and should not be compared to
Pakistan's 0.857 or France's 0.710, which were measured against exhaustively mapped quadrats.
The comparison BETWEEN models on this shared set is what the run is for.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-transfer")

MIN_OSM_AREA_M2 = 5.0  # sub-5 m2 OSM polygons are node artefacts, not arrays


def build_quadrats(cells: list[str], out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    grid = gpd.read_parquet("data/predictions/germany/density/grid.geoparquet")
    grid = grid[grid.cell.isin(cells)]
    o = gpd.read_parquet("data/labels/germany_national_osm_solar.parquet")
    o = o[(o.placement == "rooftop") & (o.area_m2 >= MIN_OSM_AREA_M2)].to_crs(grid.crs)
    man = []
    for _, c in grid.iterrows():
        pv = o[o.geometry.intersects(c.geometry)].copy()
        if len(pv) < 20:
            continue
        stem = f"de_{c.cell}_osm"
        gpd.GeoDataFrame({
            "id": pv.get("id", pd.Series(range(len(pv)))).astype(str).to_numpy(),
            "kind": "generator", "placement": "rooftop",
            "area_m2": pv.area_m2.to_numpy(), "label_tag": "osm",
            "geometry": pv.geometry.to_numpy(),
        }, geometry="geometry", crs=pv.crs).to_parquet(out / f"{stem}_overpass_solar.parquet")
        gpd.GeoDataFrame([{
            "quadrat_id": stem, "location": c.cell, "insee": "", "size_km2": None,
            "shape": "grid_cell", "stratum": "germany_osm_pseudo", "mapping_date": None,
            "source_geojson": None, "label_source": "osm_germany",
        }], geometry=[c.geometry], crs=grid.crs).to_file(
            out / f"{stem}_boundary.geojson", driver="GeoJSON")
        man.append({"stem": stem, "cell": c.cell, "n_pv": int(len(pv)),
                    "n_buildings_grid": int(c.n_buildings)})
    (out / "manifest.json").write_text(json.dumps(man, indent=2))
    return man


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells-csv", required=True)
    ap.add_argument("--labels-dir", default="data/labels/germany_osm")
    ap.add_argument("--out-table", default="data/roofclf_germany_osm/buildings.geoparquet")
    ap.add_argument("--out", default="results/germany_roofclf_transfer.json")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    from earthpv import overture
    from earthpv.roofclf import (MODEL_FEATURES, auc, auc_within_size, building_table,
                                 design_matrix, fit_logistic, load_model, predict_proba)

    labels_dir = Path(args.labels_dir)
    cells = pd.read_csv(args.cells_csv).cell.astype(str).tolist()
    table_path = Path(args.out_table)

    if args.rebuild or not table_path.exists():
        man = build_quadrats(cells, labels_dir)
        log.info("built %d German pseudo-quadrats", len(man))
        con = overture.connect()
        parts = []
        for i, m in enumerate(man, 1):
            try:
                t = building_table(m["stem"], "DEU", Path("data/composites/germany"), None,
                                   None, labels_dir=labels_dir, con=con, parcel_label=True)
            except Exception as e:  # noqa: BLE001
                log.warning("%s failed: %s", m["stem"], e)
                continue
            if t.empty:
                continue
            parts.append(t)
            log.info("[%d/%d] %s: %d rows, %d pv | pooled %d", i, len(man), m["stem"],
                     len(t), int(t.has_pv.sum()), sum(len(p) for p in parts))
        tab = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True))
        table_path.parent.mkdir(parents=True, exist_ok=True)
        tab.to_parquet(table_path)
    else:
        tab = gpd.read_parquet(table_path)

    feats = list(MODEL_FEATURES)
    y = tab.has_pv.to_numpy(float)
    roof = tab.roof_area_m2.to_numpy()
    X = design_matrix(tab, feats)
    log.info("German eval set: %d buildings, %d with OSM PV (%.2f%%), %d cells",
             len(tab), int(y.sum()), 100 * y.mean(), tab.quadrat.nunique())

    res = {}
    for name, path in [("france_openpvmapper", None),
                       ("pakistan_production", "data/roofclf/model_full.json")]:
        if path is None:
            tr = gpd.read_parquet("data/roofclf_france_opvm/buildings.geoparquet")
            m = fit_logistic(design_matrix(tr, feats), tr.has_pv.to_numpy(float))
        else:
            m, mf = load_model(Path(path))
            if list(mf) != feats:
                log.warning("%s feature order differs; using its own", name)
                m2 = design_matrix(tab, list(mf))
                p = predict_proba(m, m2)
                ws, _ = auc_within_size(y, p, roof)
                res[name] = {"auc": round(float(auc(y, p)), 4),
                             "auc_within_size": round(float(ws), 4)}
                continue
        p = predict_proba(m, X)
        ws, _ = auc_within_size(y, p, roof)
        res[name] = {"auc": round(float(auc(y, p)), 4), "auc_within_size": round(float(ws), 4)}

    rows = []
    for q in sorted(tab.quadrat.unique()):
        te, tr = tab[tab.quadrat == q], tab[tab.quadrat != q]
        if te.has_pv.sum() == 0 or tr.has_pv.sum() == 0:
            continue
        m = fit_logistic(design_matrix(tr, feats), tr.has_pv.to_numpy(float))
        pp = predict_proba(m, design_matrix(te, feats))
        yy = te.has_pv.to_numpy(float)
        w, _ = auc_within_size(yy, pp, te.roof_area_m2.to_numpy())
        rows.append({"cell": q, "n": len(te), "n_pv": int(yy.sum()),
                     "auc": round(float(auc(yy, pp)), 4), "auc_within_size": round(float(w), 4)})
    per = pd.DataFrame(rows)
    res["germany_in_domain_loco"] = {
        "auc": round(float(per.auc.median()), 4),
        "auc_within_size": round(float(per.auc_within_size.median()), 4),
        "n_cells": int(len(per)),
    }

    pv = tab[tab.has_pv.astype(bool)]
    out = {
        "eval_set": {"buildings": int(len(tab)), "osm_pv_buildings": int(y.sum()),
                     "base_rate": round(float(y.mean()), 4),
                     "cells": int(tab.quadrat.nunique()),
                     "median_roof_m2": round(float(tab.roof_area_m2.median()), 1),
                     "median_pv_roof_m2": round(float(pv.roof_area_m2.median()), 1),
                     "median_pv_area_m2": round(float(pv.pv_area_true_m2.median()), 1),
                     "median_pv_share_of_roof": round(
                         float((pv.pv_area_true_m2 / pv.roof_area_m2.clip(lower=1)).median()), 3)},
        "models": res,
        "per_cell_in_domain": per.to_dict("records"),
        "truth_caveat": (
            "German OSM covers ~3.6% of registered rooftop units, so most true positives sit "
            "in the negative class. Every AUC here is attenuated by that, equally for every "
            "model, and none is comparable to a figure measured on exhaustively mapped "
            "quadrats. The between-model comparison is the point."
        ),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    e = out["eval_set"]
    print(f"\nGerman eval set: {e['buildings']:,} buildings, {e['osm_pv_buildings']:,} OSM-PV "
          f"({100*e['base_rate']:.2f}%), {e['cells']} cells")
    print(f"  median PV roof {e['median_pv_roof_m2']:.0f} m2 | array {e['median_pv_area_m2']:.0f} m2 "
          f"| share of roof {e['median_pv_share_of_roof']:.3f}")
    print(f"\n{'model':<28}{'AUC':>9}{'within-size':>13}")
    for k, v in res.items():
        print(f"{k:<28}{v['auc']:>9.4f}{v['auc_within_size']:>13.4f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
