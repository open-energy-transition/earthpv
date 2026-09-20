"""Does the WITHIN-FOOTPRINT pixel distribution add anything over the zonal mean?

Every spectral feature roofclf ships is a mean over the footprint. That is the right
statistic only if a flagged roof is uniformly covered, and it is not: a panel array
usually occupies part of a roof, so the mean is a mixture of panel and roof in an unknown
proportion. This register has already established that the roof half is the dominant
noise term (roof-to-roof heterogeneity 0.0431 reflectance, 20-40x the sensor noise) and
that the LINEAR SPECTRAL LIMIT ON THE MEAN is essentially reached (Mahalanobis separation
implies AUC 0.807 within size band against 0.8333 achieved). Order statistics are not on
that axis: they are a different summary of the same pixels, not a cleaner estimate of the
same summary.

Registered before measuring, three hypotheses and one control:

  EXTREMES  the darkest pixel in a footprint approximates the panel endmember, so min/max
            are less diluted than the mean. Prediction: helps, and helps MORE on larger
            footprints (more pixels to take an extreme over).
  SPREAD    a partially covered roof is internally heterogeneous and a uniformly bright
            roof is not, so the within-footprint standard deviation is direct evidence of
            partial cover. Prediction: helps, and is the block that survives if only one
            does, because it does not need the extreme to be the panel.
  BOTH      the two together.
  px_count  THE CONTROL. Roughly half the Pakistani VIDA population is sub-pixel and falls
            back to a representative point, where min = max = mean and std = 0 exactly.
            Both blocks therefore carry a hidden "how many pixels did this footprint get"
            signal that `log_roof_area` does not fully supply. If the control alone moves
            the metric as much as the blocks do, the blocks measure footprint size, not
            roof composition, and nothing here is about PV.

    pixi run python scripts/run_dispersion_ablation.py
    pixi run python scripts/run_dispersion_ablation.py --preprocess trimzonal
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from earthpv import overture
from earthpv.roofclf import (DISPERSION_FEATURES, EXTREME_FEATURES, L2, MODEL_FEATURES,
                             SPREAD_FEATURES, _subset_matrix, auc, auc_within_size,
                             building_table, discover_quadrats, fit_logistic, predict_proba)

log = logging.getLogger("dispersion")
EXCLUDE = "kalat_rural_calib_3km"   # see CLAUDE.md's "Calibration quadrats"

BLOCKS = {
    "baseline": list(MODEL_FEATURES),
    "plus_px_count": list(MODEL_FEATURES) + ["px_log_count"],
    "plus_extremes": list(MODEL_FEATURES) + ["px_log_count"] + list(EXTREME_FEATURES),
    "plus_spread": list(MODEL_FEATURES) + ["px_log_count"] + list(SPREAD_FEATURES),
    "plus_dispersion": list(MODEL_FEATURES) + list(DISPERSION_FEATURES),
}


def build(out: Path, quadrats: list[str], composites: Path, labels_dir: Path,
          seg: Path | None, frac: Path | None, iso3: str, preprocess: str | None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "buildings.geoparquet"
    if dst.exists():
        log.info("table exists, reusing %s", dst)
        return dst
    con = overture.connect()
    t0 = time.time()
    parts = [building_table(n, iso3, composites, seg, frac, labels_dir, con,
                            parcel_label=True, preprocess=preprocess)
             for n in quadrats]
    tab = gpd.GeoDataFrame(pd.concat([p for p in parts if not p.empty], ignore_index=True),
                           geometry="geometry", crs="EPSG:4326")
    tab.to_parquet(dst)
    log.info("%d rows, %d quadrats, %.0fs -> %s", len(tab), tab.quadrat.nunique(),
             time.time() - t0, dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--preprocess", default=None,
                    help="composite variant to build the table on (default: the shipped read)")
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--seg-prob-dir", type=Path,
                    default=Path("data/predictions_pk16085/pakistan/prob"))
    ap.add_argument("--frac-prob-dir", type=Path,
                    default=Path("data/predictions_frac_pk_v2/pakistan/prob"))
    ap.add_argument("--out", type=Path, default=Path("data/roofclf_dispersion"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    _, cfg = resolve_aoi(args.aoi, Settings.load())
    iso3 = _iso3_for(cfg)
    quadrats = [q for q in sorted(discover_quadrats(args.labels_dir)) if q != EXCLUDE]
    tag = args.preprocess or "baseline"
    log.info("%d quadrats (excluding %s), composite variant %s", len(quadrats), EXCLUDE, tag)

    dst = build(args.out / tag, quadrats, args.composites, args.labels_dir,
                args.seg_prob_dir, args.frac_prob_dir, iso3, args.preprocess)
    t = gpd.read_parquet(dst)
    # One NaN drop for ALL blocks, so a block cannot win by being fitted on more rows --
    # the mistake that poisoned the temporal-unmix and brightness_zscore fits.
    cols = sorted({c for f in BLOCKS.values() for c in f} | {"has_pv", "roof_area_m2"})
    need = [c for c in cols if c in t.columns]
    before = len(t)
    t = t[np.isfinite(_subset_matrix(t, [c for c in need if c != "quadrat"])).all(axis=1)]
    log.info("%d rows kept of %d after one shared NaN drop", len(t), before)

    rows = []
    for i, name in enumerate(sorted(t.quadrat.unique()), 1):
        te = (t.quadrat == name).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2:
            continue
        y = t.loc[te, "has_pv"].to_numpy()
        roof = t.loc[te, "roof_area_m2"].to_numpy()
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum()),
             "base_rate": float(y.mean())}
        for lab, feats in BLOCKS.items():
            m = fit_logistic(_subset_matrix(t[tr], feats),
                             t.loc[tr, "has_pv"].to_numpy(float), L2)
            p = predict_proba(m, _subset_matrix(t[te], feats))
            r[f"auc__{lab}"] = auc(y, p)
            r[f"ws__{lab}"] = auc_within_size(y, p, roof)[0]
            # The EXTREMES prediction is size-conditional, so split the fold's own AUC by
            # whether the footprint got more than one pixel to take an extreme over.
            multi = t.loc[te, "px_log_count"].to_numpy() > 0.0
            if multi.sum() > 1 and len(np.unique(y[multi])) == 2:
                r[f"multipx__{lab}"] = auc(y[multi], p[multi])
            if (~multi).sum() > 1 and len(np.unique(y[~multi])) == 2:
                r[f"singlepx__{lab}"] = auc(y[~multi], p[~multi])
        rows.append(r)
        log.info("[%2d] %-26s base %.4f -> disp %.4f", i, name.split("_calib")[0],
                 r["ws__baseline"], r["ws__plus_dispersion"])
    d = pd.DataFrame(rows)

    print(f"\ncomposite variant: {tag}   {len(t)} rows, {len(d)} folds")
    print(f"{'block':22} {'AUC':>8} {'within-size':>12} {'multi-px':>10} {'single-px':>10}")
    for lab in BLOCKS:
        print(f"{lab:22} {d[f'auc__{lab}'].median():8.4f} {d[f'ws__{lab}'].median():12.4f} "
              f"{d.get(f'multipx__{lab}', pd.Series([np.nan])).median():10.4f} "
              f"{d.get(f'singlepx__{lab}', pd.Series([np.nan])).median():10.4f}")
    print(f"\n{'vs baseline':22} {'d within-size':>14} {'folds better':>13} {'sign p':>8} "
          f"{'wilcoxon p':>11}")
    summary = {"variant": tag, "n_rows": int(len(t)), "n_folds": int(len(d))}
    for lab in BLOCKS:
        if lab == "baseline":
            continue
        delta = d[f"ws__{lab}"] - d["ws__baseline"]
        b, w = int((delta > 0).sum()), int((delta < 0).sum())
        ps = stats.binomtest(b, max(b + w, 1), 0.5).pvalue
        pw = stats.wilcoxon(d[f"ws__{lab}"], d["ws__baseline"]).pvalue if b + w else np.nan
        print(f"{lab:22} {delta.median():+14.4f} {b:9d}/{b + w:<3d} {ps:8.3f} {pw:11.4f}")
        summary[lab] = {"d_ws_median": round(float(delta.median()), 4),
                        "d_auc_median": round(float((d[f"auc__{lab}"]
                                                     - d["auc__baseline"]).median()), 4),
                        "folds_better": b, "folds_worse": w,
                        "sign_p": round(float(ps), 4), "wilcoxon_p": round(float(pw), 4)}
    out_json = Path("results") / f"roofclf_dispersion_{tag}.json"
    prev = json.loads(out_json.read_text()) if out_json.exists() else {}
    prev[tag] = summary
    out_json.write_text(json.dumps(prev, indent=2) + "\n")
    d.to_csv(Path("results") / f"roofclf_dispersion_{tag}_folds.csv", index=False)
    print(f"\nwrote {out_json} and results/roofclf_dispersion_{tag}_folds.csv")


if __name__ == "__main__":
    main()
