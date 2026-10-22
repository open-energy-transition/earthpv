"""Validate the transfer calibration against Pakistan's calibration quadrats.

THE QUESTION. If Pakistan had no quadrats, how well would OSM-mapped positives and a
pre-boom Sentinel-2 epoch measure the sub-400 m2 level (`earthpv.transfer_calibration`)?
Each quadrat is estimated with no quadrat information at all -- positives come from OSM
mapping OUTSIDE every quadrat, negatives from the same buildings in composite_1
(2021-10 to 2022-01), the classifier from the other quadrats -- and scored against its own
Rule-1 labels. The quadrat-calibrated estimators are scored leave-one-quadrat-out on the
same buildings beside it, so the comparison prices exactly what losing the quadrats costs.

WHAT EACH ORACLE ISOLATES. "oracle TPR" replaces the OSM positives with the other
quadrats' complete labels (is the mapped population representative?); "oracle FPR" replaces
the pre-boom flag rate with the quadrat's own current flag rate on PV-free roofs (how biased
is the past as a negative set?). Both read quadrat labels and are diagnostics only.

Population: buildings under 400 m2 with a score in both epochs, the sub-400 component's own.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from shapely.geometry import box

from earthpv import transfer_calibration as tc
from earthpv.compose import CELL_DEG
from earthpv.config import Settings
from earthpv.density import _grid_origin
from earthpv.labels import dissolve_overlapping, resolve_aoi
from earthpv.local_source import composite_index
from earthpv.roofclf import (
    L2, design_matrix, epoch_feature_frame, fit_logistic, load_model, predict_proba,
)

PAD_DEG = 0.001
OSM_QUADRAT_BUFFER_DEG = 0.002


def score_epochs(table: gpd.GeoDataFrame, feats: list[str], composites: Path,
                 pre_layer: int, pre_dn_offset: float) -> tuple[np.ndarray, np.ndarray]:
    """Leave-one-quadrat-out scores of every quadrat building in layer 0 (a check against
    the table's own `p_oof`) and in `pre_layer`, each by the model fitted without it."""
    comp = composite_index(str(composites), layers=pre_layer + 1)
    p_cur, p_pre = np.full(len(table), np.nan), np.full(len(table), np.nan)
    y = table["has_pv"].to_numpy(float)
    for q in sorted(table["quadrat"].unique()):
        te = (table["quadrat"] == q).to_numpy()
        m = fit_logistic(design_matrix(table[~te], feats), y[~te], L2)
        bu = gpd.GeoDataFrame({
            "area_m2": table.loc[te, "roof_area_m2"].to_numpy(),
            "bf_confidence": table.loc[te, "bf_confidence"].to_numpy(),
        }, geometry=table.loc[te].geometry.to_numpy(), crs=table.crs).to_crs("EPSG:4326")
        x0, y0, x1, y1 = bu.total_bounds
        res = comp.read_window((x0 - PAD_DEG, y0 - PAD_DEG, x1 + PAD_DEG, y1 + PAD_DEG))
        if res is None:
            print(f"  {q}: no composite coverage, skipped")
            continue
        arr, transform, crs = res
        for layer, dest, off in ((0, p_cur, 0.0), (pre_layer, p_pre, pre_dn_offset)):
            fdf, _ = epoch_feature_frame(bu, arr, transform, crs, layer, dn_offset=off)
            valid = fdf.drop(columns="bf_confidence").notna().all(axis=1).to_numpy()
            p = np.full(len(fdf), np.nan)
            if valid.any():
                p[valid] = predict_proba(
                    m, design_matrix(fdf[valid].reset_index(drop=True), feats))
            dest[te] = p
        print(f"  {q}: {int(te.sum()):,} buildings scored in both epochs")
    return p_cur, p_pre


def osm_positives(osm_path: Path, quadrat_union, prob_dir: Path, aoi: str,
                  threshold: float) -> pd.DataFrame:
    """Every sub-400 m2 building carrying OSM-mapped PV outside the quadrats, with its
    national current-epoch score and its mapped PV area."""
    osm = gpd.read_parquet(osm_path)
    osm = osm[osm.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].to_crs("EPSG:4326")
    osm = dissolve_overlapping(osm)
    osm = osm[~osm.intersects(quadrat_union.buffer(OSM_QUADRAT_BUFFER_DEG))]
    # A large ground perimeter clips the small buildings inside it (inverter houses,
    # offices) without putting PV on them; parcel_pv_area already skips it for the yard.
    osm = osm[(osm["placement"] != "ground") | (osm["area_m2"] < 400)].reset_index(drop=True)
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    ox, oy = _grid_origin(aoi, cfg, settings)
    rp = osm.geometry.representative_point()
    cells = sorted({f"{int(np.floor((p.x - ox) / CELL_DEG)):04d}_"
                    f"{int(np.floor((p.y - oy) / CELL_DEG)):04d}" for p in rp})
    rows = []
    for cell in cells:
        path = prob_dir / f"{cell}.parquet"
        if not path.exists():
            continue
        bu = gpd.read_parquet(path)
        if bu.empty:
            continue
        bu = bu.rename(columns={"roof_area_m2": "area_m2"}).reset_index(drop=True)
        x0, y0, x1, y1 = bu.total_bounds
        pv = osm[osm.intersects(box(x0, y0, x1, y1))]
        if pv.empty:
            continue
        lab = tc.label_pv(bu, pv)
        keep = lab["has_pv"].to_numpy() & (tc.size_bin(bu["area_m2"]) >= 0)
        rows.append(pd.DataFrame({
            "cell": cell, "roof_area_m2": bu.loc[keep, "area_m2"].to_numpy(),
            "p": bu.loc[keep, "p_roofclf"].to_numpy(),
            "pv_area_m2": lab.loc[keep, "pv_area_m2"].to_numpy(),
        }))
    pos = pd.concat(rows, ignore_index=True)
    print(f"OSM positives outside the quadrats: {len(pos):,} sub-400 m2 buildings in "
          f"{pos['cell'].nunique()} cells ({int(pos['p'].isna().sum())} unscored)")
    return pos


def quadrat_estimates(sub: pd.DataFrame, pos_osm: pd.DataFrame, thr: float) -> pd.DataFrame:
    rows = []
    pos = tc.positive_rates(tc.size_bin(pos_osm["roof_area_m2"]), pos_osm["p"],
                            pos_osm["pv_area_m2"], thr)
    for q, d in sub.groupby("quadrat"):
        o = sub[(sub["quadrat"] != q)]
        ob = tc.size_bin(o["roof_area_m2"])
        b = tc.size_bin(d["roof_area_m2"])
        cur = tc.bin_rates(b, d["p_oof"], thr)
        pre = tc.bin_rates(b, d["p_pre"], thr)
        neg = d["has_pv"].to_numpy() == 0
        fpr_oracle = tc.bin_rates(b[neg], d["p_oof"].to_numpy()[neg], thr)
        op = o["has_pv"].to_numpy() == 1
        pos_oracle = tc.positive_rates(ob[op], o["p_oof"].to_numpy()[op],
                                       o["pv_area_true_m2"].to_numpy()[op], thr)
        r = {"quadrat": q, "n_buildings": len(d), "true_n_pv": int(d["has_pv"].sum()),
             "true_pv_area_m2": float(d["pv_area_true_m2"].sum()),
             "base_rate": float(d["has_pv"].mean())}
        variants = {
            "transfer": (cur, pre, pos, False),
            "transfer_prob": (cur, pre, pos, True),
            "oracle_tpr": (cur, pre, pos_oracle, False),
            "oracle_fpr": (cur, fpr_oracle, pos, False),
            "oracle_both": (cur, fpr_oracle, pos_oracle, False),
        }
        for name, (c, p_, ps, prob) in variants.items():
            e = tc.estimate(c, p_, ps, probabilistic=prob)
            r[f"{name}_n_pv"] = float(e["n_pv"].sum(skipna=True))
            r[f"{name}_pv_area_m2"] = float(e["pv_area_m2"].sum(skipna=True))
            r[f"{name}_unidentified_bins"] = int(e["pi"].isna().sum())
        # Quadrat-calibrated benchmarks, leave-one-quadrat-out on the same buildings.
        roof, pvt = d["roof_area_m2"].to_numpy(), o["pv_area_true_m2"].to_numpy()
        r["null_pv_area_m2"] = roof.sum() * pvt.sum() / o["roof_area_m2"].sum()
        r["pweighted_pv_area_m2"] = (
            (d["p_oof"] * d["roof_area_m2"]).sum()
            * pvt.sum() / (o["p_oof"] * o["roof_area_m2"]).sum())
        flagged_ratio = 0.0
        for k in range(tc.N_SIZE_BINS):
            fo = (ob == k) & (o["p_oof"].to_numpy() >= thr)
            fd = (b == k) & (d["p_oof"].to_numpy() >= thr)
            den = o["roof_area_m2"].to_numpy()[fo].sum()
            if den > 0:
                flagged_ratio += (d["roof_area_m2"].to_numpy()[fd].sum()
                                  * pvt[ob == k].sum() / den)
        r["flagged_ratio_pv_area_m2"] = flagged_ratio
        # Diagnostics, pooled over the quadrat's sub-400 buildings.
        r["f_cur"] = float((d["p_oof"] >= thr).mean())
        r["f_pre"] = float((d["p_pre"] >= thr).mean())
        r["fpr_now_true"] = float((d["p_oof"].to_numpy()[neg] >= thr).mean())
        r["tpr_now_true"] = float((d["p_oof"].to_numpy()[~neg] >= thr).mean()) if (~neg).any() else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def summarise(est: pd.DataFrame) -> dict:
    out = {}
    methods = ["transfer", "transfer_prob", "oracle_tpr", "oracle_fpr", "oracle_both",
               "null", "pweighted", "flagged_ratio"]
    truth = est["true_pv_area_m2"]
    for m in methods:
        e = est[f"{m}_pv_area_m2"]
        ok = truth > 0
        err = (e[ok] - truth[ok]).abs() / truth[ok]
        out[m] = {
            "median_abs_error": round(float(err.median()), 4),
            "pooled_ratio": round(float(e.sum() / truth.sum()), 4),
            "spearman": round(float(spearmanr(e, truth).statistic), 4),
            "median_ratio": round(float((e[ok] / truth[ok]).median()), 4),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calib-dir", type=Path, default=Path("data/roofclf"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--prob-dir", type=Path,
                    default=Path("data/roofclf_national_with_sppi/pakistan/prob"))
    ap.add_argument("--osm", type=Path, default=Path("data/labels/pakistan_overpass_solar.parquet"))
    ap.add_argument("--pre-layer", type=int, default=1)
    ap.add_argument("--pre-dn-offset", type=float, default=tc.PRE_BASELINE_DN_OFFSET,
                    help="DN added to the pre-boom layer (0 reproduces the unharmonized read)")
    ap.add_argument("--out", type=Path, default=Path("results/transfer_calibration/pakistan_check"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    table = gpd.read_parquet(a.calib_dir / "buildings.geoparquet")
    _, feats = load_model(a.calib_dir / "model_full.json")
    thr = json.loads((a.calib_dir / "summary.json").read_text())["deployment_threshold"]
    print(f"{len(table):,} quadrat buildings, {table['quadrat'].nunique()} quadrats, "
          f"threshold {thr}")

    scores = a.out / f"quadrat_epoch_scores_off{a.pre_dn_offset:.0f}.parquet"
    if scores.exists():
        s = pd.read_parquet(scores)
        p_cur, p_pre = s["p_cur_check"].to_numpy(), s["p_pre"].to_numpy()
    else:
        p_cur, p_pre = score_epochs(table, feats, a.composites, a.pre_layer, a.pre_dn_offset)
        pd.DataFrame({"p_cur_check": p_cur, "p_pre": p_pre}).to_parquet(scores)
    ok = np.isfinite(p_cur) & table["p_oof"].notna().to_numpy()
    print(f"layer-0 rescoring vs p_oof: max |diff| {np.nanmax(np.abs(p_cur[ok] - table['p_oof'].to_numpy()[ok])):.2e}, "
          f"r = {np.corrcoef(p_cur[ok], table['p_oof'].to_numpy()[ok])[0, 1]:.5f}")
    table["p_pre"] = p_pre

    pos_path = a.out / "osm_positives.parquet"
    if pos_path.exists():
        pos_osm = pd.read_parquet(pos_path)
    else:
        from earthpv.roofclf import load_boundary
        bounds = sorted(Path("data/labels").glob("*_calib_*_boundary.geojson"))
        qunion = gpd.GeoSeries([load_boundary(p) for p in bounds], crs="EPSG:4326").union_all()
        pos_osm = osm_positives(a.osm, qunion, a.prob_dir, "pakistan", thr)
        pos_osm.to_parquet(pos_path)
    pos_osm = pos_osm[pos_osm["p"].notna()]

    sub = table[(table["roof_area_m2"] < 400) & table["p_oof"].notna() & table["p_pre"].notna()]
    sub = pd.DataFrame(sub.drop(columns="geometry"))
    print(f"population: {len(sub):,} sub-400 m2 buildings scored in both epochs "
          f"({len(table[table['roof_area_m2'] < 400]) - len(sub):,} dropped as unscored)")

    est = quadrat_estimates(sub, pos_osm, thr)
    est.to_csv(a.out / "per_quadrat.csv", index=False)
    pos_rates = tc.positive_rates(tc.size_bin(pos_osm["roof_area_m2"]), pos_osm["p"],
                                  pos_osm["pv_area_m2"], thr)
    sb = tc.size_bin(sub["roof_area_m2"])
    has = sub["has_pv"].to_numpy() == 1
    pooled = pd.DataFrame({
        "n": tc.bin_rates(sb, sub["p_oof"], thr)["n"],
        "f_cur": tc.bin_rates(sb, sub["p_oof"], thr)["flag_rate"],
        "f_pre": tc.bin_rates(sb, sub["p_pre"], thr)["flag_rate"],
        "fpr_now_true": tc.bin_rates(sb[~has], sub["p_oof"].to_numpy()[~has], thr)["flag_rate"],
        "tpr_quadrats": tc.positive_rates(sb[has], sub["p_oof"].to_numpy()[has],
                                          sub["pv_area_true_m2"].to_numpy()[has], thr)["tpr"],
        "tpr_osm": pos_rates["tpr"], "n_pos_osm": pos_rates["n_pos"],
        "mean_pv_area_quadrats": tc.positive_rates(
            sb[has], sub["p_oof"].to_numpy()[has],
            sub["pv_area_true_m2"].to_numpy()[has], thr)["mean_pv_area_m2"],
        "mean_pv_area_osm": pos_rates["mean_pv_area_m2"],
        "base_rate": pd.Series(has).groupby(sb).mean().reindex(range(tc.N_SIZE_BINS)).to_numpy(),
    })
    pooled.index = [f"{lo:.0f}-{hi:.0f}" for lo, hi in zip(tc.SIZE_EDGES_M2[:-1], tc.SIZE_EDGES_M2[1:])]
    pooled.to_csv(a.out / "pooled_rates_by_size.csv")
    summary = {"threshold": thr, "pre_layer": a.pre_layer, "pre_dn_offset": a.pre_dn_offset,
               "n_quadrats": int(len(est)),
               "n_osm_positives": int(len(pos_osm)), "by_method": summarise(est)}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    with pd.option_context("display.width", 200, "display.precision", 4):
        print("\nPooled rates by roof size:\n", pooled)
        print("\nPV area per quadrat, error against Rule-1 labels:")
        print(pd.DataFrame(summary["by_method"]).T)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
