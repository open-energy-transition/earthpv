#!/usr/bin/env python
"""Germany with OSM footprints instead of VIDA, and a French border calibration set.

Two changes to `test_roofclf_transfer_germany.py`, both prompted by what that run exposed:
50.5% of German OSM rooftop arrays sat more than 20 m from any VIDA footprint, so only 13.9%
of them ever reached a labelled building.

1. **Footprints.** German OSM buildings (Geofabrik extracts for the France-facing
   Bundeslaender) replace VIDA. Both tables are built over the SAME cells, so the comparison
   is a footprint swap and not a change of evaluation set.
2. **A calibration set France can actually supply.** Germany has no exhaustively mapped
   quadrats and its OSM is ~3.6% complete, so it cannot fit a coverage ratio. The French side
   of the same border can: authoritative cadastre footprints, near-complete OpenPVMapper
   labels, and a complete register. 40 communes in Alsace and Moselle stand in for the German
   side.

**The regime does not fully transfer, and the run reports it rather than assuming it.** French
border communes have a median mapped array of 21 m2 against 59 m2 on the German cells. Part of
that is measurement (German OSM is 3.6% complete and biased large, OpenPVMapper is not), but
register against register still puts German units above French ones, so a French-fitted model
is being asked to rank larger arrays than it was trained on.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-border")

LAYER = "gis_osm_buildings_a_free_1.shp"


def osm_buildings(bbox, zips: list[Path]) -> gpd.GeoDataFrame:
    """German OSM building polygons intersecting bbox, read straight out of the zips."""
    from earthpv.labels import geodesic_area_m2

    parts = []
    for z in zips:
        try:
            g = gpd.read_file(f"/vsizip/{z}/{LAYER}", bbox=bbox)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", z.name, str(e)[:120])
            continue
        if len(g):
            parts.append(g[["geometry"]])
    if not parts:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs).to_crs(4326)
    g = g[g.geometry.notna() & g.geometry.is_valid].reset_index(drop=True)
    g["area_m2"] = [geodesic_area_m2(x) for x in g.geometry]
    g["id"] = [f"osm-{i}" for i in range(len(g))]
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells-csv", required=True)
    ap.add_argument("--labels-dir", default="data/labels/germany_border")
    ap.add_argument("--geofabrik", default="/home/tobi/earthpv_data/geofabrik")
    ap.add_argument("--out", default="results/germany_border_transfer.json")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_roofclf_transfer_germany import build_quadrats

    from earthpv import overture
    from earthpv.roofclf import (MODEL_FEATURES, auc, auc_within_size, building_table,
                                 design_matrix, fit_logistic, predict_proba)

    zips = sorted(Path(args.geofabrik).glob("*.zip"))
    log.info("OSM building extracts: %s", [z.name for z in zips])
    cells = pd.read_csv(args.cells_csv).cell.astype(str).tolist()
    labels_dir = Path(args.labels_dir)
    man = build_quadrats(cells, labels_dir)
    log.info("built %d German border pseudo-quadrats", len(man))

    con = overture.connect()
    tabs: dict[str, list] = {"vida": [], "osm": []}
    for i, m in enumerate(man, 1):
        bnd = gpd.read_file(labels_dir / f"{m['stem']}_boundary.geojson")
        bb = tuple(bnd.total_bounds)
        bu_osm = osm_buildings(bb, zips)
        if bu_osm.empty:
            log.warning("%s: no OSM buildings, skipped from BOTH tables to keep them paired",
                        m["stem"])
            continue
        for tag, bu in (("vida", None), ("osm", bu_osm)):
            try:
                t = building_table(m["stem"], "DEU", Path("data/composites/germany"), None,
                                   None, labels_dir=labels_dir, con=con, parcel_label=True,
                                   buildings=bu)
            except Exception as e:  # noqa: BLE001
                log.warning("%s/%s failed: %s", m["stem"], tag, str(e)[:120])
                t = pd.DataFrame()
            if not t.empty:
                tabs[tag].append(t)
        log.info("[%d/%d] %s: vida=%d osm=%d rows", i, len(man), m["stem"],
                 len(tabs["vida"][-1]) if tabs["vida"] else 0,
                 len(tabs["osm"][-1]) if tabs["osm"] else 0)

    feats = list(MODEL_FEATURES)
    out: dict = {"footprint_comparison": {}, "models_on_osm_footprints": {}}

    def _fit(df):
        return fit_logistic(design_matrix(df, feats), df.has_pv.to_numpy(float))

    trains = {
        "france_border_cadastre_opvm": "data/roofclf_france_border/buildings.geoparquet",
        "france_national_opvm": "data/roofclf_france_opvm/buildings.geoparquet",
        "pakistan_production": "data/roofclf/buildings.geoparquet",
    }
    eval_tabs = {}
    for tag in ("vida", "osm"):
        if not tabs[tag]:
            continue
        tab = gpd.GeoDataFrame(pd.concat(tabs[tag], ignore_index=True))
        eval_tabs[tag] = tab
        Path(f"data/roofclf_germany_border_{tag}").mkdir(parents=True, exist_ok=True)
        tab.to_parquet(f"data/roofclf_germany_border_{tag}/buildings.geoparquet")
        y = tab.has_pv.to_numpy(float)
        pv = tab[tab.has_pv.astype(bool)]
        rows = []
        for q in sorted(tab.quadrat.unique()):
            te, tr = tab[tab.quadrat == q], tab[tab.quadrat != q]
            if te.has_pv.sum() == 0 or tr.has_pv.sum() == 0:
                continue
            p = predict_proba(_fit(tr), design_matrix(te, feats))
            yy = te.has_pv.to_numpy(float)
            w, _ = auc_within_size(yy, p, te.roof_area_m2.to_numpy())
            rows.append({"auc": float(auc(yy, p)), "auc_within_size": float(w)})
        per = pd.DataFrame(rows)
        out["footprint_comparison"][tag] = {
            "buildings": int(len(tab)), "pv_buildings": int(y.sum()),
            "base_rate": round(float(y.mean()), 4),
            "median_roof_m2": round(float(tab.roof_area_m2.median()), 1),
            "median_pv_area_m2": round(float(pv.pv_area_true_m2.median()), 1),
            "median_pv_share_of_roof": round(
                float((pv.pv_area_true_m2 / pv.roof_area_m2.clip(lower=1)).median()), 3),
            "in_domain_loco_auc": round(float(per.auc.median()), 4),
            "in_domain_loco_auc_within_size": round(float(per.auc_within_size.median()), 4),
        }

    if "osm" in eval_tabs:
        tab = eval_tabs["osm"]
        y, roof = tab.has_pv.to_numpy(float), tab.roof_area_m2.to_numpy()
        X = design_matrix(tab, feats)
        for name, path in trains.items():
            if not Path(path).exists():
                out["models_on_osm_footprints"][name] = {"error": f"missing {path}"}
                continue
            tr = gpd.read_parquet(path)
            p = predict_proba(_fit(tr), X)
            ws, _ = auc_within_size(y, p, roof)
            out["models_on_osm_footprints"][name] = {
                "train_buildings": int(len(tr)), "train_positives": int(tr.has_pv.sum()),
                "auc": round(float(auc(y, p)), 4), "auc_within_size": round(float(ws), 4)}
        out["models_on_osm_footprints"]["germany_in_domain_loco"] = {
            "auc": out["footprint_comparison"]["osm"]["in_domain_loco_auc"],
            "auc_within_size": out["footprint_comparison"]["osm"]["in_domain_loco_auc_within_size"]}

    out["truth_caveat"] = (
        "German OSM covers ~3.6% of registered rooftop units, so most true positives sit in "
        "the negative class and every AUC here is attenuated, equally for every model. Not "
        "comparable to figures measured on exhaustively mapped quadrats."
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))

    print("\n=== footprint swap, same cells ===")
    print(f"{'':<8}{'buildings':>11}{'pv':>8}{'base%':>8}{'medroof':>9}{'PVshare':>9}"
          f"{'in-domain AUC':>15}{'within':>9}")
    for tag, v in out["footprint_comparison"].items():
        print(f"{tag:<8}{v['buildings']:>11,}{v['pv_buildings']:>8,}{100*v['base_rate']:>8.2f}"
              f"{v['median_roof_m2']:>9.0f}{v['median_pv_share_of_roof']:>9.3f}"
              f"{v['in_domain_loco_auc']:>15.4f}{v['in_domain_loco_auc_within_size']:>9.4f}")
    print("\n=== models scored on German border cells (OSM footprints) ===")
    print(f"{'model':<34}{'train pos':>11}{'AUC':>9}{'within':>9}")
    for k, v in out["models_on_osm_footprints"].items():
        if "error" in v:
            print(f"{k:<34} {v['error']}")
            continue
        print(f"{k:<34}{v.get('train_positives', 0):>11,}{v['auc']:>9.4f}{v['auc_within_size']:>9.4f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
