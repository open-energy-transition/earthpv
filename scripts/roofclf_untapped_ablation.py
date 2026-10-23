"""The 2026-10-22 "untapped opportunities" sweep for roofclf, on Pakistan's quadrats.

Same design as every roofclf ablation in docs/experiments.md: the production 30-quadrat
table (`data/roofclf/buildings.geoparquet`, parcel label, area-weighted zonal means),
leave-one-quadrat-out, each block paired per fold against the shipped model. Everything
below is DECLARED HERE, before any of it was measured. Extra columns come from
`scripts/roofclf_untapped_extract.py`, which reproduces the shipped band means exactly.

Three things are reported per block, because the register has found more than once that
they disagree:

  ranking       median fold AUC and AUC within roof-size band (the size-free headline),
                paired per fold: median delta, folds better, sign and Wilcoxon p
  deployment    pooled recall at the precision-0.5 threshold `run_roof_classifier` picks,
                with a quadrat-bootstrap 95% interval on the difference
  capacity      the per-quadrat true PV AREA predicted leave-one-quadrat-out the way the
                capacity chain prices it: flagged roof area per roof-size band times the
                other quadrats' (true PV area / flagged roof area) in that band. This is
                coverage ratio and area recall in one step, and it is the quantity the
                atlas is built from. Paired per quadrat on |log(estimate / truth)|.

Blocks:

  pixel read    psf<s>  footprint weights convolved with a Gaussian PSF (sigma px)
                dil<d>  footprint buffered by d metres before area weighting
  epoch         plus_d21 / plus_d21m  difference against composite_1 (2021/22, pre-boom),
                        with the documented +1000 DN offset or a per-window median match
                plus_c1m_levels  the same epoch as levels, the L2-prior control
  context       plus_ctx   VIDA-only micro-context (counts within 25/50/100 m, nearest
                           neighbour, size relative to neighbours, built-up share)
                plus_nb10  the 10 nearest buildings' mean spectral features and size,
                           i.e. a spatial lag of the linear predictor: PV adoption is
                           clustered, which is why subtracting a neighbourhood FAILED
  model form    plus_inter_size  spectral x log roof area
                plus_nd45        every pairwise normalised band difference
                l2_*             regularisation strength
                gbm, blend       gradient boosting and the mean of its logit with the
                                 linear model's (ranking from one, calibration from the other)
  training set  drop_sliver_pos  train without positives carrying under 10 m2 of PV
                drop_adjacent_neg  train without negatives within 5 m of a positive
                (both are evaluated on the full, unchanged labels)
  re-measure    plus_yard, plus_prob  rejected on older fits; the current summary.json shows
                                      the largest within-size medians of any block

    pixi run python scripts/roofclf_untapped_ablation.py
"""

from __future__ import annotations

import os

# one thread per worker: the folds run in parallel processes instead
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

from earthpv.roofclf import (BAND_NAMES, L2, MODEL_FEATURES, PARCEL_MODEL_FEATURES,
                             PROB_FEATURES, SPECTRAL_FEATURES, _I_BLUE, _I_GREEN, _I_NIR,
                             _I_RED, _I_SWIR1, _subset_matrix, auc, auc_within_size,
                             fit_logistic, predict_proba)

log = logging.getLogger("untapped")
EPS = 1e-6
FEATS_PATH = Path("/home/tobi/earthpv_data/roofclf_untapped/features.parquet")
GBM_SMALL = dict(max_leaf_nodes=15, max_iter=200, learning_rate=0.08,
                 min_samples_leaf=100, l2_regularization=1.0)
CAP_BANDS = (0.0, 50.0, 100.0, 200.0, 400.0, np.inf)
N_BOOT = 200
SIZE = ["log_roof_area", "bf_confidence"]
_DERIVED = ("ndvi", "ndbi", "brightness", "swir_vis_ratio", "blue_red_ratio")


def spectral(df: pd.DataFrame, prefix: str) -> list[str]:
    """Derive the shipped fifteen spectral quantities from `<prefix>_<band>` columns, in
    place, exactly as `building_table` does; return their names."""
    m = np.stack([df[f"{prefix}_{b}"].to_numpy(float) for b in BAND_NAMES])
    r, nir, sw = m[_I_RED], m[_I_NIR], m[_I_SWIR1]
    df[f"{prefix}_ndvi"] = (nir - r) / (nir + r + EPS)
    df[f"{prefix}_ndbi"] = (sw - nir) / (sw + nir + EPS)
    df[f"{prefix}_brightness"] = m.mean(axis=0)
    df[f"{prefix}_swir_vis_ratio"] = sw / (m[[_I_BLUE, _I_GREEN, _I_RED]].mean(axis=0) + EPS)
    df[f"{prefix}_blue_red_ratio"] = m[_I_BLUE] / (r + EPS)
    return [f"{prefix}_{b}" for b in BAND_NAMES] + [f"{prefix}_{k}" for k in _DERIVED]


def neighbour_means(d: pd.DataFrame, xy: np.ndarray, cols: list[str], k: int) -> pd.DataFrame:
    out = np.full((len(d), len(cols)), np.nan)
    vals = d[cols].to_numpy(float)
    for _, idx in d.groupby("quadrat").indices.items():
        kk = min(k + 1, len(idx))
        _, j = cKDTree(xy[idx]).query(xy[idx], k=kk)
        out[idx] = np.nanmean(vals[idx][j[:, 1:]], axis=1)
    return pd.DataFrame(out, columns=[f"nb{k}_{c}" for c in cols], index=d.index)


def build(t: gpd.GeoDataFrame, f: pd.DataFrame) -> tuple[pd.DataFrame, dict, np.ndarray]:
    d = pd.concat([t.drop(columns="geometry"), f], axis=1)
    spec = list(SPECTRAL_FEATURES)
    blocks: dict[str, tuple] = {"baseline": ("lr", list(MODEL_FEATURES), {})}

    blocks["aw_repro"] = ("lr", SIZE + spectral(d, "aw"), {})
    for p in ("psf0.4", "psf0.65", "psf1", "dil1", "dil2", "dil4"):
        blocks[p] = ("lr", SIZE + spectral(d, p), {})
    # footprint AND dilated mean together: the model may use the ring contrast between them
    blocks["plus_dil2"] = ("lr", list(MODEL_FEATURES) + spectral(d, "dil2"), {})

    c1 = spectral(d, "c1")
    # `c1` carries the documented +1000 DN offset. `c1m` is the same layer shifted per band
    # so its window median matches the current composite's: the extractor recorded that
    # shift AFTER the offset was applied, so adding it replaces the offset outright.
    for b in BAND_NAMES:
        d[f"c1m_{b}"] = d[f"c1_{b}"] + d[f"c1_medshift_{b}"]
    c1m = spectral(d, "c1m")
    d21, d21m = [], []
    for s, a, bm in zip(spec, c1, c1m):
        k = s.removesuffix("_mean")
        d[f"d21_{k}"] = d[s] - d[a]
        d[f"d21m_{k}"] = d[s] - d[bm]
        d21.append(f"d21_{k}")
        d21m.append(f"d21m_{k}")
    blocks["plus_d21"] = ("lr", list(MODEL_FEATURES) + d21, {})
    blocks["plus_d21m"] = ("lr", list(MODEL_FEATURES) + d21m, {})
    blocks["plus_c1m_levels"] = ("lr", list(MODEL_FEATURES) + c1m, {})
    blocks["c1m_only"] = ("lr", SIZE + c1m, {})

    ctx = [c for c in f.columns if c.startswith("ctx_")]
    blocks["plus_ctx"] = ("lr", list(MODEL_FEATURES) + ctx, {})
    pts = t.geometry.representative_point()
    lat0 = float(pts.y.mean())
    xy = np.column_stack([pts.x.to_numpy() * 111320.0 * np.cos(np.radians(lat0)),
                          pts.y.to_numpy() * 110540.0])
    d["log_roof_area_raw"] = np.log10(d.roof_area_m2.clip(lower=1.0))
    nb = neighbour_means(d, xy, spec + ["log_roof_area_raw"], 10)
    d = pd.concat([d, nb], axis=1)
    blocks["plus_nb10"] = ("lr", list(MODEL_FEATURES) + list(nb.columns), {})

    la = d["log_roof_area_raw"].to_numpy()
    inter = []
    for s in spec:
        d[f"x_{s}"] = d[s] * la
        inter.append(f"x_{s}")
    blocks["plus_inter_size"] = ("lr", list(MODEL_FEATURES) + inter, {})
    nd = []
    for i, a in enumerate(BAND_NAMES):
        for b in BAND_NAMES[i + 1:]:
            x, y_ = d[f"{a}_mean"], d[f"{b}_mean"]
            d[f"nd_{a}_{b}"] = (x - y_) / (x + y_ + EPS)
            nd.append(f"nd_{a}_{b}")
    blocks["plus_nd45"] = ("lr", list(MODEL_FEATURES) + nd, {})
    for l2 in (0.01, 100.0, 1000.0, 10000.0):
        blocks[f"l2_{l2:g}"] = ("lr", list(MODEL_FEATURES), {"l2": l2})
    blocks["gbm"] = ("gbm", list(MODEL_FEATURES), {})

    sliver = ((d.has_pv == 1) & (d.pv_area_true_m2 < 10.0)).to_numpy()
    blocks["drop_sliver_pos"] = ("lr", list(MODEL_FEATURES), {"drop": sliver})
    adj = adjacent_negatives(t, 5.0)
    blocks["drop_adjacent_neg"] = ("lr", list(MODEL_FEATURES), {"drop": adj})
    log.info("training-set variants drop %d sliver positives, %d adjacent negatives",
             int(sliver.sum()), int(adj.sum()))

    # Lahore and Sanghar carry ~13,500 rows each and Tank Rural 225, so an unweighted fit is
    # mostly two quadrats. Deployment is to unseen places, and every fold here is one.
    nq = d.groupby("quadrat").quadrat.transform("size").to_numpy(float)
    blocks["quadrat_balanced"] = ("lr", list(MODEL_FEATURES), {"weight": 1.0 / nq})
    blocks["quadrat_sqrt_balanced"] = ("lr", list(MODEL_FEATURES), {"weight": 1.0 / np.sqrt(nq)})

    blocks["plus_yard"] = ("lr", list(PARCEL_MODEL_FEATURES), {})
    # pass 2 (declared after pass 1 read the two faintly-positive capacity blocks)
    blocks["plus_d21m_yard"] = ("lr", list(PARCEL_MODEL_FEATURES) + d21m, {})
    blocks["plus_prob"] = ("lr", list(MODEL_FEATURES) + list(PROB_FEATURES), {})

    allf = sorted({c for _, fs, _ in blocks.values() for c in fs})
    ok = np.isfinite(_subset_matrix(d, allf)).all(axis=1)
    log.info("one shared NaN drop: %d of %d rows lack some block's features", int((~ok).sum()),
             len(d))
    return d, blocks, ok


def adjacent_negatives(t: gpd.GeoDataFrame, dist_m: float) -> np.ndarray:
    """Negatives whose footprint lies within `dist_m` of a positive's: at 10 m they share a
    pixel with it, so from the sensor's side they are partly PV whatever the label says."""
    out = np.zeros(len(t), dtype=bool)
    for _, idx in t.groupby("quadrat").indices.items():
        utm = t.iloc[idx].to_crs(t.iloc[idx].estimate_utm_crs())
        pos = (utm.has_pv == 1).to_numpy()
        if not pos.any() or pos.all():
            continue
        buf = gpd.GeoDataFrame(geometry=utm.geometry[pos].buffer(dist_m).to_numpy(), crs=utm.crs)
        neg = gpd.GeoDataFrame({"i": np.flatnonzero(~pos)},
                               geometry=utm.geometry[~pos].to_numpy(), crs=utm.crs)
        hit = gpd.sjoin(neg, buf, predicate="intersects")["i"].unique()
        out[idx[hit]] = True
    return out


_D: pd.DataFrame | None = None


def _job(args):
    name, kind, feats, opts, q = args
    d = _D
    te = (d.quadrat == q).to_numpy()
    tr = ~te
    if "drop" in opts:
        tr &= ~opts["drop"]
    ytr = d.loc[tr, "has_pv"].to_numpy(float)
    Xtr, Xte = _subset_matrix(d[tr], feats), _subset_matrix(d[te], feats)
    if kind == "lr":
        sw = opts["weight"][tr] if "weight" in opts else None
        p = predict_proba(fit_logistic(Xtr, ytr, opts.get("l2", L2), sample_weight=sw), Xte)
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier

        clf = HistGradientBoostingClassifier(random_state=0, early_stopping=False, **GBM_SMALL)
        clf.fit(Xtr, ytr)
        p = clf.predict_proba(Xte)[:, 1]
    return name, q, p


def loqo(d: pd.DataFrame, blocks: dict, workers: int) -> dict[str, np.ndarray]:
    global _D
    _D = d
    quads = sorted(d.quadrat.unique())
    jobs = [(n, k, fs, o, q) for n, (k, fs, o) in blocks.items() for q in quads]
    oof = {n: np.full(len(d), np.nan) for n in blocks}
    with ProcessPoolExecutor(workers) as ex:
        for i, (n, q, p) in enumerate(ex.map(_job, jobs, chunksize=1)):
            oof[n][(d.quadrat == q).to_numpy()] = p
            if (i + 1) % 60 == 0:
                log.info("%d / %d fits", i + 1, len(jobs))
    return oof


def precision_threshold(y: np.ndarray, s: np.ndarray, target: float = 0.5) -> float:
    from earthpv.sppi import _precision_threshold

    return float(_precision_threshold(y, s, min_precision=target))


def recall_at(y: np.ndarray, s: np.ndarray, thr: float) -> float:
    return float(((s >= thr) & y).sum() / max(int(y.sum()), 1))


def capacity_by_quadrat(d: pd.DataFrame, s: np.ndarray, thr: float) -> pd.DataFrame:
    """Leave-one-quadrat-out true-PV-area estimate per quadrat, priced per size band as
    flagged roof area x (other quadrats' true PV area / flagged roof area)."""
    band = np.digitize(d.roof_area_m2.to_numpy(), CAP_BANDS[1:-1])
    roof = d.roof_area_m2.to_numpy()
    pv = d.pv_area_true_m2.to_numpy()
    flag = s >= thr
    q = d.quadrat.to_numpy()
    rows = []
    for name in np.unique(q):
        te = q == name
        est = soft = 0.0
        for k in range(len(CAP_BANDS) - 1):
            o = ~te & (band == k)
            den = roof[o & flag].sum()
            if den > 0:
                est += roof[te & (band == k) & flag].sum() * pv[o].sum() / den
            # the same pricing with no threshold: probability-weighted roof area
            sden = (s[o] * roof[o]).sum()
            if sden > 0:
                soft += (s[te & (band == k)] * roof[te & (band == k)]).sum() * pv[o].sum() / sden
        rows.append({"quadrat": name, "truth": pv[te].sum(), "est": est, "soft": soft})
    return pd.DataFrame(rows)


def paired(a: np.ndarray, b: np.ndarray) -> dict:
    dl = (a - b)[np.isfinite(a - b)]
    better, worse = int((dl > 0).sum()), int((dl < 0).sum())
    rng = np.random.default_rng(0)
    boot = [np.median(rng.choice(dl, len(dl))) for _ in range(500)]
    return {"delta_median": round(float(np.median(dl)), 4),
            "delta_mean": round(float(np.mean(dl)), 4),
            "ci95": [round(float(np.percentile(boot, 2.5)), 4),
                     round(float(np.percentile(boot, 97.5)), 4)],
            "better": f"{better}/{len(dl)}",
            "sign_p": round(float(stats.binomtest(better, max(better + worse, 1)).pvalue), 4),
            "wilcoxon_p": round(float(stats.wilcoxon(dl).pvalue), 4) if len(dl) > 5 else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--features", type=Path, default=FEATS_PATH)
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_untapped.json"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", nargs="*", default=None, help="restrict to these blocks")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(args.table).reset_index(drop=True)
    f = pd.read_parquet(args.features).reset_index(drop=True)
    d, blocks, ok = build(t, f)
    d = d[ok].reset_index(drop=True)
    if args.only:
        blocks = {k: v for k, v in blocks.items() if k in args.only or k == "baseline"}
    # training-set masks were built on the full table; re-index them to the kept rows
    for n, (k, fs, o) in blocks.items():
        for key in ("drop", "weight"):
            if key in o:
                o[key] = o[key][ok]
    oof = loqo(d, blocks, args.workers)
    if "gbm" in oof:
        lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))  # noqa: E731
        oof["blend"] = 1.0 / (1.0 + np.exp(-(lg(oof["baseline"]) + lg(oof["gbm"])) / 2.0))

    y = d.has_pv.to_numpy(bool)
    roof = d.roof_area_m2.to_numpy()
    quads = d.quadrat.to_numpy()
    uq = np.unique(quads)
    members = {q: np.flatnonzero(quads == q) for q in uq}
    rng = np.random.default_rng(1)
    boot_ix = [np.concatenate([members[q] for q in rng.choice(uq, len(uq))])
               for _ in range(N_BOOT)]

    per_fold, cap, summ = {}, {}, {}
    for n, s in oof.items():
        rows = []
        for q in uq:
            te = quads == q
            rows.append({"quadrat": q, "auc": auc(y[te], s[te]),
                         "ws": auc_within_size(y[te], s[te], roof[te])[0],
                         "rate_err": abs(float(s[te].mean()) - float(y[te].mean()))})
        per_fold[n] = pd.DataFrame(rows).set_index("quadrat")
        thr = precision_threshold(y, s)
        c = capacity_by_quadrat(d, s, thr).set_index("quadrat")
        c = c[c.truth > 0]
        c["abslog"] = np.abs(np.log(np.maximum(c.est, 1.0) / c.truth))
        c["abslog_soft"] = np.abs(np.log(np.maximum(c.soft, 1.0) / c.truth))
        cap[n] = c
        summ[n] = {
            "auc": round(float(per_fold[n].auc.median()), 4),
            "within_size": round(float(per_fold[n].ws.median()), 4),
            "rate_err": round(float(per_fold[n].rate_err.median()), 4),
            "threshold": round(thr, 4),
            "recall_at_p50": round(recall_at(y, s, thr), 4),
            "cap_median_abs_err": round(float((np.abs(c.est - c.truth) / c.truth).median()), 4),
            "cap_pooled_ratio": round(float(c.est.sum() / c.truth.sum()), 4),
            "cap_spearman": round(float(stats.spearmanr(c.est, c.truth).statistic), 4),
            "soft_median_abs_err": round(float((np.abs(c.soft - c.truth) / c.truth).median()), 4),
            "soft_pooled_ratio": round(float(c.soft.sum() / c.truth.sum()), 4),
        }

    out = {"n_buildings": int(len(d)), "n_pv": int(y.sum()), "n_folds": int(len(uq)),
           "medians": summ, "paired_vs_baseline": {}}
    b = "baseline"
    for n in oof:
        if n == b:
            continue
        pf, pb = per_fold[n], per_fold[b]
        dr = []
        for ix in boot_ix:
            ta = precision_threshold(y[ix], oof[n][ix])
            tb = precision_threshold(y[ix], oof[b][ix])
            dr.append(recall_at(y[ix], oof[n][ix], ta) - recall_at(y[ix], oof[b][ix], tb))
        out["paired_vs_baseline"][n] = {
            "auc": paired(pf.auc.to_numpy(), pb.auc.to_numpy()),
            "within_size": paired(pf.ws.to_numpy(), pb.ws.to_numpy()),
            "rate_err_reduction": paired(-pf.rate_err.to_numpy(), -pb.rate_err.to_numpy()),
            "recall_at_p50_delta": round(summ[n]["recall_at_p50"] - summ[b]["recall_at_p50"], 4),
            "recall_at_p50_ci95": [round(float(np.percentile(dr, 2.5)), 4),
                                   round(float(np.percentile(dr, 97.5)), 4)],
            "capacity_abslog_reduction": paired(-cap[n].abslog.to_numpy(),
                                                -cap[b].abslog.to_numpy()),
            "soft_capacity_abslog_reduction": paired(-cap[n].abslog_soft.to_numpy(),
                                                     -cap[b].abslog_soft.to_numpy()),
        }
    # the aggregation change on its own: soft against thresholded pricing, same scores
    out["soft_vs_threshold_baseline"] = paired(-cap[b].abslog_soft.to_numpy(),
                                               -cap[b].abslog.to_numpy())
    folds = pd.concat({n: v for n, v in per_fold.items()}, axis=1)
    folds.columns = [f"{c}__{n}" for n, c in folds.columns]
    folds.to_csv(args.out.with_name(args.out.stem + "_folds.csv"))
    caps = pd.concat({n: v for n, v in cap.items()}, axis=1)
    caps.columns = [f"{c}__{n}" for n, c in caps.columns]
    caps.to_csv(args.out.with_name(args.out.stem + "_capacity.csv"))
    np.savez_compressed(FEATS_PATH.parent / (args.out.stem + "_oof.npz"),
                        quadrat=quads, has_pv=y, **oof)
    args.out.write_text(json.dumps(out, indent=2) + "\n")

    print(f"\n{len(d)} rows, {y.sum()} PV, {len(uq)} folds")
    print(f"{'block':20} {'AUC':>7} {'ws':>7} {'d_ws':>8} {'better':>7} {'p':>6} "
          f"{'recall':>7} {'d_rec':>7} {'cap_err':>8} {'cap_better':>10} {'cap_p':>6}")
    for n, m in summ.items():
        pv_ = out["paired_vs_baseline"].get(n)
        if pv_ is None:
            print(f"{n:20} {m['auc']:7.4f} {m['within_size']:7.4f} {'':>8} {'':>7} {'':>6} "
                  f"{m['recall_at_p50']:7.4f} {'':>7} {m['cap_median_abs_err']:8.3f}")
            continue
        ws, cp = pv_["within_size"], pv_["capacity_abslog_reduction"]
        print(f"{n:20} {m['auc']:7.4f} {m['within_size']:7.4f} {ws['delta_median']:+8.4f} "
              f"{ws['better']:>7} {ws['sign_p']:6.3f} {m['recall_at_p50']:7.4f} "
              f"{pv_['recall_at_p50_delta']:+7.4f} {m['cap_median_abs_err']:8.3f} "
              f"{cp['better']:>10} {cp['sign_p']:6.3f}")


if __name__ == "__main__":
    main()
