"""Do Google's precomputed AlphaEarth embeddings add anything roofclf does not already have?

The Satellite Embedding dataset (AlphaEarth Foundations v2.1, Google / Google DeepMind,
CC-BY-4.0) gives every 10 m pixel a 64-number, unit-length summary of one calendar year of
Sentinel-2, Landsat, Sentinel-1 and other inputs, 2017 onwards. It costs nothing to try:
no training and no GPU, and it is read here from the Source Cooperative COG mirror
(`tge-labs/aef`, anonymous S3), so no Earth Engine account is needed either.

The question is the one every roofclf feature block has had to answer: on the production
30-quadrat table (`data/roofclf/buildings.geoparquet`, parcel label, area-weighted
Sentinel-2 means), leave-one-quadrat-out, paired per fold against the shipped model, does
adding the embedding improve ranking (AUC, and AUC within roof-size band, the
size-confound-free headline), the pooled recall at the precision-0.5 deployment threshold,
and the per-quadrat adoption-rate error the atlas actually consumes?

Each building gets the AREA-WEIGHTED mean of the 64 de-quantised channels over its
footprint, with the same `preprocess.coverage_matrix` weights the shipped Sentinel-2
features use, so the two blocks see one footprint the same way. A footprint smaller than a
subpixel keeps the pixel under its representative point.

Everything below is DECLARED HERE, not chosen on the held-out folds:

  * primary: `plus_aef2025` against `baseline` (MODEL_FEATURES), logistic, same L2. 2025 is
    the latest AEF year and the closest to the Sentinel-2 composites roofclf reads (late
    2025 to mid 2026).
  * `plus_aef2024`: one year earlier, for epoch sensitivity (Pakistan's boom ran through
    2024-2025, and an annual embedding averages over the whole year).
  * `plus_aef2021`: the PRE-BOOM control. Most mapped PV did not exist in 2021, so whatever
    a 2021 embedding adds is roof and neighbourhood PROPENSITY, not panels. The register
    already records that roofclf's own 2021 score predicts today's PV at AUC 0.83 against
    0.87 (experiments, 2026-10-20); the gap between this row and `plus_aef2025` is the part
    of the embedding that can plausibly be panels.
  * `plus_aef_change`: 2025 plus (2025 - 2021), i.e. letting the model use the change since
    before the boom, which is what an installation is.
  * `aef_only`: size + AEF 2025 with NO Sentinel-2 block -- can the embedding replace it?
  * `gbm_baseline` / `gbm_plus_aef2025`: the conservative `gbm_small` configuration from
    `run_model_class_ablation.py`, because 64 entangled dimensions may need a non-linear
    head. The register already found GBM ranks worse and calibrates better on the shipped
    features, so these are read against each other, not against the logistic baseline.

    pixi run python scripts/run_aef_embedding_ablation.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats
from shapely.geometry import box

from earthpv.roofclf import (L2, MODEL_FEATURES, _subset_matrix, auc, auc_within_size,
                             fit_logistic, predict_proba)

log = logging.getLogger("aef_ablation")

AEF_INDEX = Path("/home/tobi/earthpv_data/aef/index/aef_index.parquet")
AEF_CACHE = Path("/home/tobi/earthpv_data/aef/roofclf_quadrats")
AEF_DIMS = [f"aef_{i:02d}" for i in range(64)]
AEF_NODATA = -128
PAD_M = 80.0
CONTEXT_PX = 7  # 70 m box
SUBPIX = 4
YEARS = (2025, 2024, 2021)
N_BOOT = 500

# anonymous read of the Source Cooperative bucket; the bucket name has dots, so path-style
_GDAL_ENV = dict(AWS_NO_SIGN_REQUEST="YES", AWS_REGION="us-west-2", AWS_VIRTUAL_HOSTING="FALSE",
                 GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                 CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tiff,.vrt")

GBM_SMALL = dict(max_leaf_nodes=15, max_iter=200, learning_rate=0.08,
                 min_samples_leaf=100, l2_regularization=1.0)


def dequantize(v: np.ndarray) -> np.ndarray:
    """int8 -> [-1, 1] as the dataset README specifies; -128 is nodata in every channel."""
    f = v.astype("float32")
    out = np.sign(f) * (f / 127.5) ** 2
    out[v == AEF_NODATA] = np.nan
    return out


def _vrt_path(s3_path: str) -> str:
    # The COGs are stored bottom-up; the companion .vrt flips them to north-up.
    return "/vsis3/" + s3_path.removeprefix("s3://").removesuffix(".tiff") + ".vrt"


def table_fingerprint(t: pd.DataFrame) -> str:
    key = t.quadrat.astype(str) + ":" + t.roof_area_m2.round(3).astype(str)
    return hashlib.sha1("|".join(key).encode()).hexdigest()[:16]


def read_window(q: str, year: int, tile: pd.Series, bu_utm: gpd.GeoDataFrame):
    """Raw int8 window over the quadrat (+`PAD_M`), cached so follow-ups need no network."""
    import rasterio
    from rasterio.windows import from_bounds

    cache = AEF_CACHE / "windows" / str(year) / f"{q}.npz"
    if cache.exists():
        z = np.load(cache)
        return z["arr"], rasterio.Affine(*z["transform"]), str(z["crs"])
    minx, miny, maxx, maxy = bu_utm.total_bounds
    with rasterio.Env(**_GDAL_ENV), rasterio.open(_vrt_path(tile.path)) as src:
        win = from_bounds(minx - PAD_M, miny - PAD_M, maxx + PAD_M, maxy + PAD_M,
                          src.transform).round_offsets().round_lengths()
        arr = src.read(window=win)
        transform = src.window_transform(win)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, arr=arr, transform=np.array(transform[:6]), crs=str(tile.crs))
    return arr, transform, str(tile.crs)


def quadrat_aef(q: str, year: int, bu: gpd.GeoDataFrame,
                tile: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """(n_buildings, 64) area-weighted mean embedding over each footprint, and the same
    embedding averaged over a `CONTEXT_PX`-pixel box around the building (its
    neighbourhood, of which a typical footprint is a few percent)."""
    import rasterio
    from scipy.ndimage import uniform_filter

    from earthpv.preprocess import coverage_matrix

    bu_utm = bu.to_crs(tile.crs)
    raw, transform, _ = read_window(q, year, tile, bu_utm)
    arr = dequantize(raw)
    nb, h, w = arr.shape
    flat = arr.reshape(nb, -1)
    valid = np.isfinite(flat).all(axis=0)
    A = coverage_matrix(bu_utm, (h, w), transform, subpix=SUBPIX)
    Aok = A.multiply(valid[:, None]).tocsr()
    wsum = np.asarray(Aok.sum(axis=0)).ravel()
    out = np.full((len(bu), nb), np.nan, dtype="float32")
    num = Aok.T.dot(np.nan_to_num(flat, nan=0.0).T)  # (buildings, 64)
    ok = wsum > 1e-6
    out[ok] = num[ok] / wsum[ok, None]
    pts = bu_utm.geometry.representative_point()
    rows, cols = rasterio.transform.rowcol(transform, pts.x.to_numpy(), pts.y.to_numpy())
    rows = np.clip(np.asarray(rows), 0, h - 1)
    cols = np.clip(np.asarray(cols), 0, w - 1)
    # Footprints with no subpixel of their own: the pixel under the representative point.
    out[~ok] = arr[:, rows[~ok], cols[~ok]].T
    vmask = valid.reshape(h, w).astype("float32")
    den = uniform_filter(vmask, CONTEXT_PX, mode="constant")
    ctx = np.stack([uniform_filter(np.nan_to_num(b, nan=0.0), CONTEXT_PX, mode="constant")
                    for b in arr]) / np.maximum(den, 1e-6)
    return out, ctx[:, rows, cols].T.astype("float32")


def extract(table: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    fp = table_fingerprint(table)
    cache = AEF_CACHE / f"aef_{year}_{fp}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    idx = gpd.read_parquet(AEF_INDEX)
    idx = idx[idx.year == year]
    out = np.full((len(table), 64), np.nan, dtype="float32")
    ctx = np.full((len(table), 64), np.nan, dtype="float32")
    for q in sorted(table.quadrat.unique()):
        sel = (table.quadrat == q).to_numpy()
        bu = table.loc[sel, ["geometry"]]
        hull = box(*bu.total_bounds)
        tiles = idx[idx.intersects(hull)]
        # contain the whole quadrat, not just touch it, or the window would be clipped
        tiles = tiles[tiles.contains(hull)] if tiles.contains(hull).any() else tiles
        if len(tiles) != 1:
            raise RuntimeError(f"{q} {year}: {len(tiles)} AEF tiles cover the quadrat")
        out[sel], ctx[sel] = quadrat_aef(q, year, bu, tiles.iloc[0])
        log.info("  %d %-24s %5d buildings, %d without a valid embedding", year, q,
                 sel.sum(), int(np.isnan(out[sel]).any(axis=1).sum()))
    df = pd.concat([pd.DataFrame(out, columns=AEF_DIMS),
                    pd.DataFrame(ctx, columns=[f"{c}_ctx" for c in AEF_DIMS])], axis=1)
    AEF_CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def _fit_predict(model: str, Xtr, ytr, Xte) -> np.ndarray:
    if model == "logistic":
        return predict_proba(fit_logistic(Xtr, ytr, L2), Xte)
    from sklearn.ensemble import HistGradientBoostingClassifier

    clf = HistGradientBoostingClassifier(random_state=0, early_stopping=False, **GBM_SMALL)
    clf.fit(Xtr, ytr)
    return clf.predict_proba(Xte)[:, 1]


def run(d: pd.DataFrame, combos: dict) -> tuple[pd.DataFrame, dict]:
    rows, oof = [], {k: np.full(len(d), np.nan) for k in combos}
    for name in sorted(d.quadrat.unique()):
        te = (d.quadrat == name).to_numpy()
        tr = ~te
        y = d.loc[te, "has_pv"].to_numpy()
        roof = d.loc[te, "roof_area_m2"].to_numpy()
        ytr = d.loc[tr, "has_pv"].to_numpy(float)
        r = {"quadrat": name, "n": int(te.sum()), "n_pv": int(y.sum()),
             "base_rate": float(y.mean())}
        for lab, (model, feats) in combos.items():
            p = _fit_predict(model, _subset_matrix(d[tr], feats), ytr,
                             _subset_matrix(d[te], feats))
            oof[lab][te] = p
            r[f"auc__{lab}"] = auc(y, p)
            r[f"ws__{lab}"] = auc_within_size(y, p, roof)[0]
            r[f"rate__{lab}"] = float(np.mean(p))
        rows.append(r)
        log.info("%-24s n=%5d pv=%4d  " + "  ".join(f"{k} %.4f" for k in combos),
                 name, r["n"], r["n_pv"], *[r[f"auc__{k}"] for k in combos])
    return pd.DataFrame(rows), oof


def recall_at_precision(y: np.ndarray, s: np.ndarray, min_precision: float = 0.5) -> float:
    from earthpv.sppi import _precision_threshold

    t = _precision_threshold(y, s, min_precision=min_precision)
    pred = s >= t
    return float((pred & y).sum() / max(int(y.sum()), 1))


def paired(f: pd.DataFrame, a: str, b: str, col: str) -> dict:
    """Fold-paired comparison of `a` against `b`: median delta, folds better, sign and
    Wilcoxon p, and a quadrat-bootstrap 95% interval on the median delta."""
    dl = (f[f"{col}__{a}"] - f[f"{col}__{b}"]).dropna().to_numpy()
    better, worse = int((dl > 0).sum()), int((dl < 0).sum())
    rng = np.random.default_rng(0)
    boot = [np.median(rng.choice(dl, len(dl))) for _ in range(N_BOOT)]
    return {
        "delta_median": round(float(np.median(dl)), 4),
        "delta_mean": round(float(np.mean(dl)), 4),
        "delta_ci95": [round(float(np.percentile(boot, 2.5)), 4),
                       round(float(np.percentile(boot, 97.5)), 4)],
        "folds_better": f"{better}/{len(dl)}",
        "sign_p": round(float(stats.binomtest(better, max(better + worse, 1), 0.5).pvalue), 4),
        "wilcoxon_p": round(float(stats.wilcoxon(dl).pvalue), 4) if len(dl) > 5 else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--out", type=Path, default=Path("results/roofclf_aef_embedding.json"))
    ap.add_argument("--no-gbm", action="store_true", help="skip the two GBM rows")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(args.table).reset_index(drop=True)
    log.info("%d buildings, %d with PV, %d quadrats", len(t), int(t.has_pv.sum()),
             t.quadrat.nunique())
    emb = {y: extract(t, y) for y in YEARS}
    d = t.drop(columns="geometry").copy()
    for y, e in emb.items():
        for c in AEF_DIMS:
            d[f"{c}_{y}"] = e[c].to_numpy()
            d[f"{c}_ctx_{y}"] = e[f"{c}_ctx"].to_numpy()
        # Each pixel vector is unit length; a footprint mean's norm says how uniform the
        # footprint's pixels are, reported for the record, not used as a feature.
        log.info("AEF %d: footprint-mean norm median %.3f, %d rows missing", y,
                 float(np.median(np.linalg.norm(e[AEF_DIMS].to_numpy(), axis=1))),
                 int(e[AEF_DIMS].isna().any(axis=1).sum()))
    for c in AEF_DIMS:
        d[f"{c}_chg"] = d[f"{c}_2025"] - d[f"{c}_2021"]
    missing = d[[f"{c}_{y}" for y in YEARS for c in AEF_DIMS]].isna().any(axis=1)
    if missing.any():
        log.warning("dropping %d buildings with no valid embedding in some year", missing.sum())
        d = d[~missing].reset_index(drop=True)

    base = list(MODEL_FEATURES)
    a = {y: [f"{c}_{y}" for c in AEF_DIMS] for y in YEARS}
    chg = [f"{c}_chg" for c in AEF_DIMS]
    combos = {
        "baseline": ("logistic", base),
        "plus_aef2025": ("logistic", base + a[2025]),
        "plus_aef2024": ("logistic", base + a[2024]),
        "plus_aef2021": ("logistic", base + a[2021]),
        "plus_aef_change": ("logistic", base + a[2025] + chg),
        "aef_only": ("logistic", ["log_roof_area", "bf_confidence"] + a[2025]),
        # the 70 m neighbourhood instead of the footprint: if this matches plus_aef2025,
        # what the embedding adds is where the building is, not what is on its roof
        "plus_context2025": ("logistic", base + [f"{c}_ctx_2025" for c in AEF_DIMS]),
    }
    if not args.no_gbm:
        combos["gbm_baseline"] = ("gbm", base)
        combos["gbm_plus_aef2025"] = ("gbm", base + a[2025])
    f, oof = run(d, combos)

    y_all = d.has_pv.to_numpy(bool)
    out = {"n_buildings": int(len(d)), "n_pv": int(y_all.sum()), "n_folds": int(len(f)),
           "years": list(YEARS), "medians": {}, "paired": {}}
    ok = f.base_rate > 0
    for k in combos:
        err = (f.loc[ok, f"rate__{k}"] - f.loc[ok, "base_rate"]).abs()
        out["medians"][k] = {
            "auc": round(float(f[f"auc__{k}"].median()), 4),
            "within_size": round(float(f[f"ws__{k}"].median()), 4),
            "rate_err_median": round(float(err.median()), 4),
            "recall_at_p50": round(recall_at_precision(y_all, oof[k]), 4),
        }
        f[f"rerr__{k}"] = (f[f"rate__{k}"] - f["base_rate"]).abs()

    # Pooled recall at the precision-0.5 threshold, with a quadrat bootstrap on the
    # difference: the deployment threshold is one pooled number, so its uncertainty is
    # which quadrats happen to be in the pool.
    quads = d.quadrat.to_numpy()
    uq = np.unique(quads)
    members = {q: np.flatnonzero(quads == q) for q in uq}
    rng = np.random.default_rng(1)
    boot_ix = [np.concatenate([members[q] for q in rng.choice(uq, len(uq))])
               for _ in range(200)]

    comparisons = [(k, "baseline") for k in combos
                   if k not in ("baseline", "gbm_baseline", "gbm_plus_aef2025")]
    comparisons += [("plus_aef2025", "plus_aef2021"), ("plus_aef_change", "plus_aef2025"),
                    ("plus_aef2025", "plus_context2025")]
    if not args.no_gbm:
        comparisons += [("gbm_plus_aef2025", "gbm_baseline")]
    for a_, b_ in comparisons:
        e = {"auc": paired(f, a_, b_, "auc"), "within_size": paired(f, a_, b_, "ws")}
        # rate error: lower is better, so flip the sign to keep "better" meaning better
        rr = f.loc[ok].copy()
        rr[f"nrerr__{a_}"], rr[f"nrerr__{b_}"] = -rr[f"rerr__{a_}"], -rr[f"rerr__{b_}"]
        e["rate_err_reduction"] = paired(rr, a_, b_, "nrerr")
        dr = [recall_at_precision(y_all[ix], oof[a_][ix])
              - recall_at_precision(y_all[ix], oof[b_][ix]) for ix in boot_ix]
        e["recall_at_p50_delta"] = round(out["medians"][a_]["recall_at_p50"]
                                         - out["medians"][b_]["recall_at_p50"], 4)
        e["recall_at_p50_delta_ci95"] = [round(float(np.percentile(dr, 2.5)), 4),
                                         round(float(np.percentile(dr, 97.5)), 4)]
        out["paired"][f"{a_}__vs__{b_}"] = e

    f.to_csv(args.out.with_name(args.out.stem + "_folds.csv"), index=False)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
