"""Price the preprocessing variants against the shipped composite, per quadrat.

Builds one roofclf table per variant (same 30 production quadrats, same parcel label, same
feature list) and compares each against the baseline table fold by fold, so the ONLY thing
that differs is how the same downloaded pixels became per-building reflectance.

    pixi run python scripts/run_preprocess_ablation.py --modes sharpen20,sharpen20_interp,unmix

Variants are described in `earthpv.preprocess`. The baseline defaults to the table from the
temporal ablation, whose MODEL_FEATURES columns reproduce production exactly (median fold
AUC 0.8574, within size band 0.8206).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

from earthpv import overture
from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             building_table, discover_quadrats, fit_logistic, predict_proba)

log = logging.getLogger("preprocess_ablation")
EXCLUDE = "kalat_rural_calib_3km"   # see CLAUDE.md's "Calibration quadrats"


def build(mode: str, out: Path, quadrats: list[str], composites: Path, labels_dir: Path,
          seg: Path | None, frac: Path | None, iso3: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "buildings.geoparquet"
    if dst.exists():
        log.info("%s: table exists, reusing %s", mode, dst)
        return dst
    con = overture.connect()
    t0 = time.time()
    parts = [building_table(n, iso3, composites, seg, frac, labels_dir, con,
                            parcel_label=True, preprocess=None if mode == "baseline" else mode)
             for n in quadrats]
    tab = gpd.GeoDataFrame(pd.concat([p for p in parts if not p.empty], ignore_index=True),
                           geometry="geometry", crs="EPSG:4326")
    tab.to_parquet(dst)
    log.info("%s: %d rows, %d quadrats, %.0fs -> %s", mode, len(tab), tab.quadrat.nunique(),
             time.time() - t0, dst)
    return dst


def _key(t: pd.DataFrame) -> pd.Series:
    """Row key that survives a rebuild: quadrat plus the footprint's rounded centroid."""
    c = t.geometry.representative_point()
    return (t.quadrat.astype(str) + "|" + c.x.round(6).astype(str) + "|"
            + c.y.round(6).astype(str))


def folds(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name in sorted(t.quadrat.unique()):
        te = (t.quadrat == name).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2:
            continue
        m = fit_logistic(_subset_matrix(t[tr], MODEL_FEATURES),
                         t.loc[tr, "has_pv"].to_numpy(float), L2)
        p = predict_proba(m, _subset_matrix(t[te], MODEL_FEATURES))
        y = t.loc[te, "has_pv"].to_numpy()
        roof = t.loc[te, "roof_area_m2"].to_numpy()
        rows.append({"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum()),
                     "auc": auc(y, p), "auc_ws": auc_within_size(y, p, roof)[0]})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--modes", default="sharpen20,sharpen20_interp,unmix")
    ap.add_argument("--baseline", type=Path,
                    default=Path("data/roofclf_temporal_ablation/buildings.geoparquet"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--seg-prob-dir", type=Path,
                    default=Path("data/predictions_pk16085/pakistan/prob"))
    ap.add_argument("--frac-prob-dir", type=Path,
                    default=Path("data/predictions_frac_pk_v2/pakistan/prob"))
    ap.add_argument("--out", type=Path, default=Path("data/roofclf_preprocess"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    _, cfg = resolve_aoi(args.aoi, Settings.load())
    iso3 = _iso3_for(cfg)
    quadrats = [q for q in sorted(discover_quadrats(args.labels_dir)) if q != EXCLUDE]
    log.info("%d quadrats (excluding %s)", len(quadrats), EXCLUDE)

    base = gpd.read_parquet(args.baseline)
    base["_k"] = _key(base)
    summary = {}
    for mode in args.modes.split(","):
        dst = build(mode, args.out / mode, quadrats, args.composites, args.labels_dir,
                    args.seg_prob_dir, args.frac_prob_dir, iso3)
        var = gpd.read_parquet(dst)
        var["_k"] = _key(var)
        # Compare on the rows both tables kept, so a differing NaN-drop cannot masquerade
        # as a skill difference.
        common = set(base._k) & set(var._k)
        b = base[base._k.isin(common)].sort_values("_k").reset_index(drop=True)
        v = var[var._k.isin(common)].sort_values("_k").reset_index(drop=True)
        log.info("%s: %d rows in common (baseline %d, variant %d)",
                 mode, len(common), len(base), len(var))
        fb, fv = folds(b), folds(v)
        d = fb.merge(fv, on="quadrat", suffixes=("_base", "_var"))
        res = {"mode": mode, "n_rows": len(common), "n_folds": len(d),
               "baseline_auc": round(float(d.auc_base.median()), 4),
               "variant_auc": round(float(d.auc_var.median()), 4),
               "baseline_auc_ws": round(float(d.auc_ws_base.median()), 4),
               "variant_auc_ws": round(float(d.auc_ws_var.median()), 4)}
        pairs = (("auc", "auc_var", "auc_base"), ("ws", "auc_ws_var", "auc_ws_base"))
        for lab, a, bcol in pairs:
            delta = d[a] - d[bcol]
            better = int((delta > 0).sum())
            worse = int((delta < 0).sum())
            from scipy import stats
            p = stats.binomtest(better, max(better + worse, 1), 0.5).pvalue
            res[f"delta_{lab}_median"] = round(float(delta.median()), 4)
            res[f"delta_{lab}_iqr"] = [round(float(delta.quantile(.25)), 4),
                                       round(float(delta.quantile(.75)), 4)]
            res[f"{lab}_folds_better"] = better
            res[f"{lab}_sign_p"] = round(float(p), 4)
        summary[mode] = res
        d.to_csv(Path("results") / f"roofclf_preprocess_{mode}_folds.csv", index=False)
        log.info("%s: %s", mode, json.dumps(res))

    # Merge rather than overwrite: a run naming one mode must not drop the others already
    # measured, which is how the first l1c run clobbered three committed results.
    out_json = Path("results/roofclf_preprocess_ablation.json")
    prior = json.loads(out_json.read_text()) if out_json.exists() else {}
    prior.update(summary)
    out_json.write_text(json.dumps(prior, indent=2))
    summary = prior
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
