"""Does a building's HEIGHT add anything roofclf does not already get from its footprint?

GlobalBuildingAtlas (zhu-xlab) publishes an LoD1 height per building. Height is a dimension
nothing in the feature set has: a warehouse and a shed with identical footprints are
different PV propensities. On the quadrat subset where GBA covers our buildings, height
alone separates PV from non-PV roofs at d' = +0.651 (median 6.74 m against 4.03 m), which is
comparable to the best single spectral band. The question this answers is whether that
survives controlling for size, since tall buildings are also large and `log_roof_area` is
already the model's strongest non-spectral feature.

Restricted to buildings GBA actually covers, and to quadrats with enough of them. That is a
biased subsample -- GBA coverage is not random -- so read it as "is height worth pursuing",
not as a deployment number.

**LICENCE: GBA heights are CC BY-NC 4.0.** This project publishes open data and has already
declined a dataset on that ground. Measuring is research; shipping a capacity figure derived
from it is not. Google Open Buildings 2.5D is the openly-licensed alternative to chase if
this comes out positive.

    pixi run python scripts/run_gba_height_ablation.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             fit_logistic, predict_proba)

log = logging.getLogger("gba_height")
MIN_MATCHED = 300


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=Path("data/roofclf_temporal_unmix/buildings.geoparquet"))
    ap.add_argument("--gba", type=Path,
                    default=Path("data/gba/e070_n35_e075_n30_quadrats.parquet"))
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_gba_height.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(args.table)
    g = gpd.read_parquet(args.gba)[["gba_height", "geometry"]]
    g = g[g.gba_height.notna()].to_crs("EPSG:4326")
    pts = t.copy()
    pts["geometry"] = t.geometry.representative_point()
    j = gpd.sjoin(gpd.GeoDataFrame(pts, geometry="geometry", crs="EPSG:4326"),
                  g, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    t = t.assign(gba_height=j.gba_height.to_numpy())
    t["log_gba_height"] = np.log1p(t.gba_height.clip(lower=0))

    m = t.gba_height.notna()
    keep = [q for q, n in t[m].quadrat.value_counts().items() if n >= MIN_MATCHED]
    d = t[m & t.quadrat.isin(keep)].reset_index(drop=True)
    log.info("%d buildings with a GBA height across %d quadrats (of %d)",
             len(d), d.quadrat.nunique(), t.quadrat.nunique())

    blocks = {
        "baseline": list(MODEL_FEATURES),
        "plus_height": list(MODEL_FEATURES) + ["log_gba_height"],
        "height_only": ["log_roof_area", "bf_confidence", "log_gba_height"],
    }
    rows = []
    for name in sorted(d.quadrat.unique()):
        te = (d.quadrat == name).to_numpy()
        tr = ~te
        if d.loc[tr, "has_pv"].nunique() < 2 or d.loc[te, "has_pv"].nunique() < 2:
            continue
        y = d.loc[te, "has_pv"].to_numpy()
        roof = d.loc[te, "roof_area_m2"].to_numpy()
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum())}
        for lab, feats in blocks.items():
            mod = fit_logistic(_subset_matrix(d[tr], feats),
                               d.loc[tr, "has_pv"].to_numpy(float), L2)
            p = predict_proba(mod, _subset_matrix(d[te], feats))
            r[f"auc__{lab}"] = auc(y, p)
            r[f"ws__{lab}"] = auc_within_size(y, p, roof)[0]
        rows.append(r)
        log.info("  %-24s n=%5d pv=%4d  auc %.4f -> %.4f", name.split("_calib")[0],
                 r["n"], r["n_pv"], r["auc__baseline"], r["auc__plus_height"])
    f = pd.DataFrame(rows)
    out = {"n_buildings": int(len(d)), "n_folds": int(len(f)),
           "join_rate_overall": round(float(m.mean()), 3)}
    for lab in blocks:
        out[f"auc_{lab}"] = round(float(f[f"auc__{lab}"].median()), 4)
        out[f"ws_{lab}"] = round(float(f[f"ws__{lab}"].median()), 4)
    for lab in ("plus_height", "height_only"):
        for tag, col in (("auc", "auc"), ("ws", "ws")):
            dl = f[f"{col}__{lab}"] - f[f"{col}__baseline"]
            b = int((dl > 0).sum())
            w = int((dl < 0).sum())
            out[f"delta_{tag}_{lab}"] = round(float(dl.median()), 4)
            out[f"{tag}_better_{lab}"] = f"{b}/{len(f)}"
            out[f"{tag}_p_{lab}"] = round(
                float(stats.binomtest(b, max(b + w, 1), 0.5).pvalue), 4)
    f.to_csv("results/roofclf_gba_height_folds.csv", index=False)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
