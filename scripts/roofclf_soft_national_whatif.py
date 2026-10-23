"""National what-if: thresholded vs probability-weighted sub-400 m2 pricing over the roofclf
domain, production calibration tables, NO dedup or size floor (scale of the change only).

    pixi run python scripts/roofclf_soft_national_whatif.py /home/tobi/earthpv_data/roofclf_untapped/national_soft_whatif.csv
"""
import sys
sys.path.insert(0, "scripts")
import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq
from roofclf_soft_capacity_check import stratified, _bin
from earthpv.sub400_capacity import (DEFAULT_EXCLUDE, quadrat_building_density_km2)
from earthpv.density import calibrated_density_range
d = gpd.read_parquet("data/roofclf/buildings.geoparquet").drop(columns="geometry")
folds = pd.read_csv("data/roofclf/folds.csv").set_index("quadrat")
folds = folds[~folds.index.isin(DEFAULT_EXCLUDE)]
trusted = folds[(folds.rate_ratio >= 0.5) & (folds.rate_ratio <= 2.0)].index.tolist()
qd = quadrat_building_density_km2("results/calibration_quadrats.csv", sorted(d.quadrat.unique()))
thr = 0.2446
p = d.p_oof.to_numpy()
flag = p >= thr
m_thr = stratified(d, trusted, qd, flag, flag.astype(float))
m_soft = stratified(d, trusted, qd, flag, p)
lo, hi = calibrated_density_range("pakistan")
cells = pd.read_parquet("data/roofclf/national_cell_density.parquet").set_index("cell")
dom = cells[(cells.density >= lo) & (cells.density <= hi)]
KWP = 0.18
rows = []
for cell, row in dom.iterrows():
    f = f"data/roofclf_national_with_sppi/pakistan/prob/{cell}.parquet"
    try:
        t = pq.read_table(f, columns=["roof_area_m2", "p_roofclf"]).to_pandas()
    except FileNotFoundError:
        continue
    t = t[(t.roof_area_m2 < 400) & np.isfinite(t.p_roofclf)]
    roof, pr = t.roof_area_m2.to_numpy(), t.p_roofclf.to_numpy()
    out = {"cell": cell, "density": row.density, "n": len(t)}
    for lab, w, model in (("thr", (pr >= thr).astype(float), m_thr), ("soft", pr, m_soft)):
        edges, bands = model
        b = int(np.clip(np.searchsorted(edges, row.density, side="right") - 1, 0, len(bands) - 1))
        ce, cov, re, rec = bands[b]
        out[lab] = float((w * roof * cov[_bin(ce, roof)] / rec[_bin(re, roof)]).sum()) * KWP / 1000
    rows.append(out)
r = pd.DataFrame(rows)
r.to_csv(sys.argv[1], index=False)
print(f"{len(r)} in-domain cells, {r.n.sum():,} sub-400 buildings")
print(f"thresholded {r.thr.sum():,.0f} MWp   soft {r.soft.sum():,.0f} MWp   ratio {r.soft.sum()/r.thr.sum():.3f}")
r["dband"] = pd.qcut(r.density, 5)
g = r.groupby("dband", observed=True).agg(cells=("cell", "size"), bldgs=("n", "sum"), thr=("thr", "sum"), soft=("soft", "sum"))
g["ratio"] = g.soft / g.thr
print(g.round(1).to_string())
