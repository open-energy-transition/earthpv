#!/usr/bin/env python
"""France's roofclf control rerun on EUBUCCO v0.2 footprints, with its building attributes.

`test_cadastre_footprints.py` (2026-09-12) measured that authoritative footprints (the DGFiP
cadastre) lift France's within-size-band AUC from 0.6274 (VIDA) to 0.6548. The pan-European
merges that would replace VIDA in an atlas -- JRC DBSM R2025 and EUBUCCO v0.2 -- both put a
government layer first (in France IGN BD TOPO), then OSM, then Microsoft, and add
attributes VIDA lacks: building type, height, floors, construction year. This asks two
things on the same 13 hand-mapped communes, protocol unchanged:

  1. footprints: are EUBUCCO's as good as the cadastre's for roofclf?
  2. attributes: do type / height / floors / year add anything on top of MODEL_FEATURES?

EUBUCCO v0.2 (ODbL; https://eubucco.com) is read from its anonymous S3 endpoint with
pyarrow, one GeoParquet per NUTS-2 region, row groups sorted by `city_id` = "FR" + INSEE,
so only a commune's few row groups are fetched. DBSM R2025 France (28.9 GB GeoPackage, its
government layer EUBUCCO v0.1) is not used: it cannot be read selectively at a usable speed
from the JRC server (1-3 s per range request), and v0.2 is the newer of the two merges.

    .pixi/envs/default/bin/python scripts/test_eubucco_footprints.py
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eubucco")

ENDPOINT = "https://s3.eubucco.com"
PREFIX = "eubucco/v0.2/buildings/parquet"
COLS = ["id", "city_id", "type", "subtype", "height", "floors", "construction_year",
        "geometry_source", "height_source", "type_source", "construction_year_source",
        "geometry"]
# Licence blockers inside EUBUCCO v0.2 (CC BY-NC / CC BY-SA sources); none is French, kept
# here so a reuse of this reader elsewhere drops them.
BLOCKED_SOURCES = ("gov-italy-abruzzo", "gov-czechia-prague")
# Departement -> NUTS-2 file for the quadrats' communes. Row groups are sorted by city_id only
# loosely (each file's tail row groups span most of France), so without this a commune reads
# 57-84 row groups from 13-16 files instead of ~8 from its own region.
DEP_NUTS2 = {"01": "FRK2", "03": "FRK1", "22": "FRH0", "31": "FRJ2", "34": "FRJ1",
             "38": "FRK2", "57": "FRF3", "64": "FRI1", "69": "FRK2", "71": "FRC1",
             "73": "FRK2", "67": "FRF1", "68": "FRF1"}


def nuts2_files(s3, country: str) -> list[str]:
    import pyarrow.fs as fs
    sel = fs.FileSelector(PREFIX, recursive=True)
    return sorted(i.path for i in s3.get_file_info(sel)
                  if i.path.endswith(".parquet") and f"nuts_id={country}" in i.path)


def rg_index(s3, files: list[str], cache: Path) -> list[tuple[str, int, str, str]]:
    """(file, row group, min city_id, max city_id) for every row group, cached as JSON.

    Reading the 22 French footers once (2 MB each) and then only the row groups a commune
    falls in is ~100x faster than a pyarrow dataset filter over the remote files, which
    took 11 minutes for one commune on this link."""
    import pyarrow.parquet as pq
    f = cache / "rg_index.json"
    if f.exists():
        return [tuple(r) for r in json.loads(f.read_text())]
    rows = []
    for path in files:
        md = pq.ParquetFile(path, filesystem=s3).metadata
        names = [md.row_group(0).column(i).path_in_schema for i in range(md.num_columns)]
        ci = names.index("city_id")
        for k in range(md.num_row_groups):
            st = md.row_group(k).column(ci).statistics
            rows.append((path, k, st.min, st.max))
        log.info("indexed %s: %d row groups", path.rsplit("/", 1)[-1], md.num_row_groups)
    cache.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows))
    return rows


def fetch_commune(s3, files: list[str], insee: str, cache: Path) -> gpd.GeoDataFrame:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    f = cache / f"eubucco-v0.2-FR{insee}.parquet"
    if not f.exists():
        city = f"FR{insee}"
        own = DEP_NUTS2.get(insee[:2])
        hits = [(p, k) for p, k, lo, hi in rg_index(s3, files, cache) if lo <= city <= hi
                and (own is None or f"nuts_id={own}/" in p)]
        parts = []
        for path in sorted({p for p, _ in hits}):
            rgs = [k for p, k in hits if p == path]
            t = pq.ParquetFile(path, filesystem=s3).read_row_groups(rgs, columns=COLS)
            parts.append(t.filter(pc.equal(t["city_id"], city)))
        tab = pa.concat_tables(parts) if parts else pa.table({c: [] for c in COLS})
        cache.mkdir(parents=True, exist_ok=True)
        pq.write_table(tab, f)
    df = pd.read_parquet(f).rename(columns={"type": "bldg_type"})
    g = gpd.GeoDataFrame(df.drop(columns="geometry"),
                         geometry=gpd.GeoSeries.from_wkb(df.geometry, crs="EPSG:3035"))
    g = g[~g.geometry_source.astype(str).isin(BLOCKED_SOURCES)]
    g = g[g.geometry.notna() & g.geometry.is_valid].to_crs("EPSG:4326")
    return g.reset_index(drop=True)


def add_attributes(t: gpd.GeoDataFrame, eub: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """EUBUCCO attributes onto building_table rows, by representative point."""
    pts = gpd.GeoDataFrame({"_r": np.arange(len(t))},
                           geometry=t.geometry.representative_point(), crs=t.crs)
    j = gpd.sjoin(pts, eub[["bldg_type", "height", "floors", "construction_year", "geometry"]],
                  how="left", predicate="within")
    j = j[~j._r.duplicated(keep="first")].sort_values("_r")
    t = t.copy()
    h = pd.to_numeric(j["height"], errors="coerce").to_numpy(float)
    fl = pd.to_numeric(j["floors"], errors="coerce").to_numpy(float)
    yr = pd.to_numeric(j["construction_year"], errors="coerce").to_numpy(float)
    typ = j["bldg_type"].astype(str).str.lower().to_numpy()
    t["eub_log_height"] = np.log1p(np.clip(np.nan_to_num(h, nan=np.nanmedian(h)), 0, None))
    t["eub_floors"] = np.nan_to_num(fl, nan=np.nanmedian(fl))
    t["eub_nonres"] = (typ == "non-residential").astype(float)
    t["eub_year_known"] = np.isfinite(yr).astype(float)
    t["eub_year"] = np.where(np.isfinite(yr), (yr - 1970) / 30.0, 0.0)
    t["eub_type"] = typ
    return t


def loqo(tab: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    from earthpv.roofclf import (auc, auc_within_size, design_matrix, fit_logistic,
                                 predict_proba)
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
                     "auc": float(auc(y, p)), "ws": float(ws)})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels-dir", default="data/labels/france")
    ap.add_argument("--composites", default="data/composites/france")
    ap.add_argument("--cache", default="data/eubucco_france")
    ap.add_argument("--out-table", default="data/roofclf_france_eubucco/buildings.geoparquet")
    ap.add_argument("--out", default="results/france_roofclf_eubucco_control.json")
    ap.add_argument("--exclude", default="saint_gely_du_fesc")
    args = ap.parse_args()

    import pyarrow.fs as fs
    from scipy import stats

    from earthpv.labels import geodesic_area_m2
    from earthpv.roofclf import MODEL_FEATURES, building_table

    s3 = fs.S3FileSystem(endpoint_override=ENDPOINT, anonymous=True, region="eu")
    files = nuts2_files(s3, "FR")
    log.info("%d French NUTS-2 files", len(files))
    labels_dir = Path(args.labels_dir)
    stems = sorted(p.name[: -len("_boundary.geojson")] for p in labels_dir.glob("*_boundary.geojson"))
    stems = [s for s in stems if args.exclude not in s]

    parts, counts = [], []
    for stem in stems:
        bnd = gpd.read_file(labels_dir / f"{stem}_boundary.geojson")
        insee = str(bnd["insee"].iloc[0]).zfill(5)
        eub = fetch_commune(s3, files, insee, Path(args.cache))
        if eub.empty:
            log.warning("%s (%s): no EUBUCCO buildings", stem, insee)
            continue
        fp = eub[["geometry"]].copy()
        fp["area_m2"] = [geodesic_area_m2(g) for g in fp.geometry]
        fp["id"] = [f"eub-{i}" for i in range(len(fp))]
        t = building_table(stem, "FRA", Path(args.composites), None, None,
                           labels_dir=labels_dir, parcel_label=True, buildings=fp)
        if t.empty:
            continue
        t = add_attributes(gpd.GeoDataFrame(t, crs="EPSG:4326"), eub)
        parts.append(t)
        src = eub.geometry_source.astype(str).value_counts(normalize=True).round(3).to_dict()
        counts.append({"quadrat": stem, "insee": insee, "buildings": len(t),
                       "pv": int(t.has_pv.sum()),
                       "median_roof_m2": round(float(t.roof_area_m2.median()), 1),
                       "geometry_sources": src,
                       "nonres_share": round(float(t.eub_nonres.mean()), 3),
                       "year_known": round(float(t.eub_year_known.mean()), 3)})
        log.info("%s: %d EUBUCCO buildings, %d with PV; sources %s", stem, len(t),
                 int(t.has_pv.sum()), src)

    tab = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    Path(args.out_table).parent.mkdir(parents=True, exist_ok=True)
    tab.drop(columns=["eub_type"]).to_parquet(args.out_table)

    base = list(MODEL_FEATURES)
    blocks = {
        "baseline": base,
        "plus_type": base + ["eub_nonres"],
        "plus_height": base + ["eub_log_height", "eub_floors"],
        "plus_year": base + ["eub_year", "eub_year_known"],
        "plus_all": base + ["eub_nonres", "eub_log_height", "eub_floors", "eub_year",
                            "eub_year_known"],
    }
    folds = {k: loqo(tab, f) for k, f in blocks.items()}
    b = folds["baseline"].set_index("quadrat")
    out = {"source": "EUBUCCO v0.2 (ODbL), per commune via city_id",
           "buildings": int(len(tab)), "positives": int(tab.has_pv.sum()),
           "median_roof_m2": round(float(tab.roof_area_m2.median()), 1),
           "reference": {"vida": {"buildings": 44314, "positives": 1231, "auc": 0.7103,
                                  "ws": 0.6274},
                         "cadastre": {"buildings": 103697, "positives": 1759, "auc": 0.7369,
                                      "ws": 0.6548}},
           "blocks": {}}
    for k, f in folds.items():
        f = f.set_index("quadrat")
        row = {"median_auc": round(float(f.auc.median()), 4),
               "median_ws": round(float(f.ws.median()), 4), "folds": int(len(f))}
        if k != "baseline":
            d = (f.ws - b.ws).dropna()
            better, worse = int((d > 0).sum()), int((d < 0).sum())
            row.update({"delta_ws_median": round(float(d.median()), 4),
                        "ws_better": f"{better}/{len(d)}",
                        "ws_sign_p": round(float(stats.binomtest(better, max(better + worse, 1)).pvalue), 4)})
        out["blocks"][k] = row
    out["per_quadrat_counts"] = counts
    out["per_quadrat_baseline"] = folds["baseline"].round(4).to_dict("records")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: v for k, v in out.items() if k not in ("per_quadrat_counts",
                                                                 "per_quadrat_baseline")}, indent=2))


if __name__ == "__main__":
    main()
