"""Does the roof serve as its own control? A pre-boom epoch against the current one.

This register's SNR budget says the noise that limits `roofclf` is not the sensor: it is
ROOF-TO-ROOF HETEROGENEITY, 0.0431 reflectance, 20-40x the radiometric noise, and the
linear spectral limit on the zonal mean is already essentially reached (Mahalanobis
separation implies 0.807 within size band against 0.8333 achieved). Every intervention
that improved the MEASUREMENT -- L1C, sharpening, unmixing, super-resolution, multi-frame
fusion -- failed or reduced to noise averaging, which is exactly what that budget predicts.

There is one term that cancels roof-to-roof heterogeneity outright, and it is not spectral:
the same roof, earlier. Pakistan's rooftop PV boom is post-2022, so a 2019/20 dry-season
composite is a pre-installation look at most of today's arrays. `current - 2019` differences
away everything about the roof that did not change, leaving the installation.

Registered before measuring. The obvious failure mode is that the difference fires on
anything that changed -- a new building, a replaced roof, a repainted one -- and the
label is correlated with new construction. Two controls separate that:

  SPLIT-HALF PLACEBO   the same difference taken between the first and second half of the
                       CURRENT dry-season stack. Same band count, same features, same
                       imagery, same reduction -- but no installation can sit between the
                       two halves. If the placebo helps as much as the epoch difference,
                       what helps is having two estimates of the same roof, not the epoch.
  OLD LEVELS           the 2019 reflectance as a level rather than a difference. For an
                       UNPENALISED linear model this spans the same space as the
                       difference and must tie it; under L2 it does not, because the
                       difference parameterisation is the one that encodes "the roof
                       cancels". A gap between them measures how much of the gain is the
                       prior rather than the data.

Both epochs are reduced the SAME way (trimmed mean of the saved scene stack), so a
difference cannot pick up a reducer or a read-path change -- the mistake that cost this
register a headline once already.

    pixi run python scripts/compose_scene_stacks.py --aoi pakistan \
        --window 2019-11-01:2020-03-15 --subdir stacks_2019
    pixi run python scripts/run_epoch_difference_ablation.py
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

from earthpv.preprocess import load_scene_stack, trimmed_mean_stack
from earthpv.roofclf import (BAND_NAMES, COMPOSITE_FILL, L2, MODEL_FEATURES, REFL_SCALE,
                             _I_BLUE, _I_GREEN, _I_NIR, _I_RED, _I_SWIR1, _subset_matrix,
                             auc, auc_within_size, discover_quadrats, fit_logistic,
                             load_quadrat, predict_proba, zonal_mean_max)

log = logging.getLogger("epoch_diff")
EXCLUDE = "kalat_rural_calib_3km"
EPS = 1e-6

_DERIVED = ("brightness", "ndvi", "ndbi", "swir_vis_ratio", "blue_red_ratio")
DELTA_OLD = [f"d19_{b}" for b in BAND_NAMES] + [f"d19_{k}" for k in _DERIVED]
DELTA_SPLIT = [f"dsp_{b}" for b in BAND_NAMES] + [f"dsp_{k}" for k in _DERIVED]
OLD_LEVELS = [f"old_{b}" for b in BAND_NAMES] + [f"old_{k}" for k in _DERIVED]

BLOCKS = {
    "baseline": list(MODEL_FEATURES),
    "plus_delta_2019": list(MODEL_FEATURES) + DELTA_OLD,
    "plus_delta_split": list(MODEL_FEATURES) + DELTA_SPLIT,        # the placebo
    "plus_old_levels": list(MODEL_FEATURES) + OLD_LEVELS,
    "plus_both": list(MODEL_FEATURES) + DELTA_OLD + DELTA_SPLIT,
}


def trimmed_mean(st: np.ndarray) -> np.ndarray:
    """The reducer this register settled on: drop the extreme 20% per pixel, mean the rest."""
    return trimmed_mean_stack(st) / REFL_SCALE


def spectral_summary(means: np.ndarray) -> dict[str, np.ndarray]:
    """The same fifteen quantities `building_table` derives, from a (band, building) mean."""
    out = {b: means[i] for i, b in enumerate(BAND_NAMES)}
    r, nir, sw = means[_I_RED], means[_I_NIR], means[_I_SWIR1]
    vis = means[[_I_BLUE, _I_GREEN, _I_RED]].mean(axis=0)
    out["brightness"] = means.mean(axis=0)
    out["ndvi"] = (nir - r) / (nir + r + EPS)
    out["ndbi"] = (sw - nir) / (sw + nir + EPS)
    out["swir_vis_ratio"] = sw / (vis + EPS)
    out["blue_red_ratio"] = means[_I_BLUE] / (r + EPS)
    return out


def quadrat_deltas(stem: str, bu: gpd.GeoDataFrame, composites: Path,
                   labels_dir: Path) -> pd.DataFrame | None:
    cur = load_scene_stack(composites, stem)
    old = load_scene_stack(composites, stem, subdir="stacks_2019")
    if cur is None or old is None:
        log.warning("quadrat %s: missing %s stack", stem,
                    "current" if cur is None else "2019")
        return None
    st_c, tr_c, crs_c = cur
    st_o, tr_o, crs_o = old
    if st_c.shape[1:] != st_o.shape[1:] or str(crs_c) != str(crs_o):
        log.warning("quadrat %s: grids differ (%s %s vs %s %s)", stem, st_c.shape, crs_c,
                    st_o.shape, crs_o)
        return None
    # Split the CURRENT stack by acquisition order, which is date order as saved.
    h = st_c.shape[0] // 2
    if h < 2:
        log.warning("quadrat %s: only %d current frames, no split-half control",
                    stem, st_c.shape[0])
        return None
    arrs = {"cur": trimmed_mean(st_c), "old": trimmed_mean(st_o),
            "a": trimmed_mean(st_c[:h]), "b": trimmed_mean(st_c[h:])}
    bu_utm = bu.to_crs(crs_c)
    sums = {}
    for k, a in arrs.items():
        m, _ = zonal_mean_max(bu_utm, np.nan_to_num(a, nan=COMPOSITE_FILL), tr_c,
                              nodata=COMPOSITE_FILL)
        sums[k] = spectral_summary(m)
    cols = {}
    for k in sums["cur"]:
        cols[f"d19_{k}"] = sums["cur"][k] - sums["old"][k]
        cols[f"dsp_{k}"] = sums["a"][k] - sums["b"][k]
        cols[f"old_{k}"] = sums["old"][k]
    return pd.DataFrame(cols)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=Path("data/roofclf_temporal_ablation/buildings.geoparquet"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    base = gpd.read_parquet(args.table)
    log.info("baseline table %d rows, %d quadrats", len(base), base.quadrat.nunique())
    parts = []
    for stem in sorted(discover_quadrats(args.labels_dir)):
        if stem == EXCLUDE:
            continue
        name = stem.split("_calib_")[0]
        sub = base[base.quadrat == stem]
        if sub.empty:
            sub = base[base.quadrat == name]
        if sub.empty:
            log.warning("quadrat %s: not in the baseline table", stem)
            continue
        # Rebuild the SAME footprint set the table carries, in the same row order, so the
        # delta columns can be attached positionally rather than re-joined spatially.
        d = quadrat_deltas(stem, sub, args.composites, args.labels_dir)
        if d is None:
            continue
        d.index = sub.index
        parts.append(pd.concat([sub, d], axis=1))
        log.info("%-28s %d buildings, d19_brightness mean %+.4f, split %+.4f",
                 name, len(sub), float(d.d19_brightness.mean()),
                 float(d.dsp_brightness.mean()))
    t = pd.concat(parts, ignore_index=True)
    feats = sorted({c for f in BLOCKS.values() for c in f})
    before = len(t)
    t = t[np.isfinite(_subset_matrix(t, feats)).all(axis=1)].reset_index(drop=True)
    log.info("%d rows kept of %d after one shared NaN drop, %d quadrats",
             len(t), before, t.quadrat.nunique())

    rows = []
    for name in sorted(t.quadrat.unique()):
        te = (t.quadrat == name).to_numpy()
        tr = ~te
        if t.loc[tr, "has_pv"].nunique() < 2 or t.loc[te, "has_pv"].nunique() < 2:
            continue
        y = t.loc[te, "has_pv"].to_numpy()
        roof = t.loc[te, "roof_area_m2"].to_numpy()
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum())}
        for lab, fs in BLOCKS.items():
            m = fit_logistic(_subset_matrix(t[tr], fs),
                             t.loc[tr, "has_pv"].to_numpy(float), L2)
            p = predict_proba(m, _subset_matrix(t[te], fs))
            r[f"auc__{lab}"] = auc(y, p)
            r[f"ws__{lab}"] = auc_within_size(y, p, roof)[0]
        rows.append(r)
        log.info("%-28s ws %.4f -> d19 %.4f (placebo %.4f)", name.split("_calib")[0],
                 r["ws__baseline"], r["ws__plus_delta_2019"], r["ws__plus_delta_split"])
    d = pd.DataFrame(rows)

    print(f"\n{len(t)} rows, {len(d)} folds")
    print(f"{'block':22} {'AUC':>9} {'within-size':>12}")
    for lab in BLOCKS:
        print(f"{lab:22} {d[f'auc__{lab}'].median():9.4f} {d[f'ws__{lab}'].median():12.4f}")
    print(f"\n{'vs baseline':22} {'d within-size':>14} {'folds better':>13} {'sign p':>8} "
          f"{'wilcoxon p':>11}")
    summary = {"n_rows": int(len(t)), "n_folds": int(len(d)),
               "baseline_ws": round(float(d.ws__baseline.median()), 4)}
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
                        "ws_median": round(float(d[f"ws__{lab}"].median()), 4),
                        "folds_better": b, "folds_worse": w,
                        "sign_p": round(float(ps), 4), "wilcoxon_p": round(float(pw), 4)}
    Path("results/roofclf_epoch_difference.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    d.to_csv("results/roofclf_epoch_difference_folds.csv", index=False)
    print("\nwrote results/roofclf_epoch_difference.json and _folds.csv")


if __name__ == "__main__":
    main()
