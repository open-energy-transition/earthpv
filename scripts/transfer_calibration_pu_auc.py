"""Does a borrowed roofclf still rank PV roofs? PU AUC on OSM-mapped positives.

OSM-PV buildings against every other sub-400 m2 building in the same cells, scored by a
national `roofclf-score-national` pass. Unlabelled roofs include unmapped PV, so this is a
lower bound on the true AUC, and only comparable between countries measured the same way:

    python scripts/transfer_calibration_pu_auc.py pakistan \
        data/labels/pakistan_overpass_solar.parquet \
        data/roofclf_national_with_sppi/pakistan/prob exclude_quadrats
    python scripts/transfer_calibration_pu_auc.py nigeria \
        data/labels/nigeria_overpass_solar_FROZEN_20260915_eval.parquet \
        data/roofclf_transfer/nigeria/prob none
    python scripts/transfer_calibration_pu_auc.py india \
        data/labels/india_overpass_solar.parquet data/roofclf_transfer/india/prob none

Positives come only from mapped arrays under 400 m2, and every building touching a
>= 400 m2 PV polygon is dropped from BOTH classes (2026-10-22). Before that, any non-ground
polygon labelled every footprint it touched, and VIDA traces a park's panel rows as
buildings: India's 3,229 polygons labelled 47,911 positives and read 0.673, Nigeria's
read 0.902 on 357. Pakistan, whose mapped rooftop PV is mostly small, barely moved
(0.934 -> 0.930).
"""
import sys, numpy as np, pandas as pd, geopandas as gpd
from pathlib import Path
from shapely.geometry import box
from earthpv import transfer_calibration as tc
from earthpv.compose import CELL_DEG
from earthpv.config import Settings
from earthpv.density import _grid_origin
from earthpv.labels import dissolve_overlapping, resolve_aoi
from earthpv.roofclf import auc
aoi, osm_path, prob_dir, excl = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4] == "exclude_quadrats"
osm = gpd.read_parquet(osm_path); osm = osm[osm.geometry.geom_type.isin(["Polygon","MultiPolygon"])].to_crs("EPSG:4326")
osm = dissolve_overlapping(osm)
if excl:
    from earthpv.roofclf import load_boundary
    qu = gpd.GeoSeries([load_boundary(p) for p in sorted(Path("data/labels").glob("*_calib_*_boundary.geojson"))], crs="EPSG:4326").union_all()
    osm = osm[~osm.intersects(qu.buffer(0.002))]
big = osm[osm.area_m2 >= 400].reset_index(drop=True)
small = osm[osm.area_m2 < 400].reset_index(drop=True)
st = Settings.load(); _, cfg = resolve_aoi(aoi, st); ox, oy = _grid_origin(aoi, cfg, st)
cells = sorted({f"{int(np.floor((p.x-ox)/CELL_DEG)):04d}_{int(np.floor((p.y-oy)/CELL_DEG)):04d}" for p in small.geometry.representative_point()})
rows = []; n_dropped = 0
for c in cells:
    f = prob_dir / f"{c}.parquet"
    if not f.exists(): continue
    try: bu = gpd.read_parquet(f)
    except ValueError: continue
    if bu.empty: continue
    bu = bu.rename(columns={"roof_area_m2": "area_m2"}).reset_index(drop=True)
    bb = box(*bu.total_bounds)
    bg = big[big.intersects(bb)]
    if not bg.empty:
        touch = gpd.sjoin(bu[["geometry"]], bg[["geometry"]], predicate="intersects").index.unique()
        n_dropped += len(touch)
        bu = bu.drop(index=touch).reset_index(drop=True)
    pv = small[small.intersects(bb)]
    if pv.empty or bu.empty: continue
    lab = tc.label_pv(bu, pv)
    b = tc.size_bin(bu.area_m2)
    keep = (b >= 0) & bu.p_roofclf.notna().to_numpy()
    rows.append(pd.DataFrame({"cell": c, "bin": b[keep], "p": bu.p_roofclf.to_numpy()[keep],
                              "y": lab.has_pv.to_numpy()[keep], "a": lab.pv_area_m2.to_numpy()[keep]}))
d = pd.concat(rows, ignore_index=True)
print(f"{aoi}: {d.cell.nunique()} cells, {len(d):,} sub-400 buildings, {int(d.y.sum())} OSM-PV positives; {n_dropped:,} buildings touching >=400 m2 PV dropped")
print(f"  PU AUC overall {auc(d.y, d.p):.3f}; within size bins: " + ", ".join(f"{k}:{auc(g.y, g.p):.3f}(n+={int(g.y.sum())})" for k, g in d.groupby("bin")))
print("  mean PV area per positive by bin: " + ", ".join(f"{k}:{g.a[g.y].mean():.0f}" for k, g in d.groupby("bin")))
print(f"  flag rate @0.2446 positives {(d.p[d.y] >= 0.2446).mean():.3f} vs unlabelled {(d.p[~d.y] >= 0.2446).mean():.3f}")
d.to_parquet(f"results/transfer_calibration/pu_table_{aoi}.parquet")
