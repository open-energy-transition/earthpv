"""Can AlphaEarth's year-on-year change see Pakistan's large arrays and ground-mount?

Follow-up to `run_aef_embedding_ablation.py`, which closed the embedding as a roofclf feature
(propensity, not panels) but found that pixels fully covered by a large mapped array DO move
between 2021 and 2025 at the industrial quadrats. This asks where that could be worth having.

The target is the ground-mount precision table. `pakistan_candidate_precision.yaml` sets
`p_unmapped = 0.0` in every ground bin ("interim-mapped-only-by-placement"): every
segmentation detection off a roof with no OSM feature within 100 m is booked as false, about
4,300 of 5,200, because nothing independent has ever looked at them. Rooftop bins inherit
0.0 below 5,000 m2 and 0.129 above, from the pooled glint sample. A change signal measured
where truth exists can say how close that floor is.

Populations, all declared here and seeded:

  * real: candidates with an OSM solar feature within 100 m (the table's `min_distance_m`),
    all of them, plus `missed`: OSM installations >= 400 m2 (dissolved) with no candidate
    within 100 m, a random 500 per placement. `missed` is also its own question: does AEF
    find what segmentation does not?
  * unmapped: candidates with no OSM feature within 100 m. All rooftop ones, and a random
    1,000 ground ones, proportional to size bin.
  * controls. Ground: each object's own polygon displaced 300-1,200 m on a random bearing,
    with no OSM solar or candidate within 50 m, so the control is the same shape on the
    land around it. Rooftop: the two VIDA buildings >= 400 m2 within 2 km closest to the
    object in log-area, with no OSM solar or candidate within 30 m. Pakistani large roofs
    carry unmapped PV, so rooftop AUCs are lower bounds.
  * quadrat: candidates inside a Rule-1 quadrat (Kalat Rural included, which was sited on
    ground-mount). Unmapped ones there are the only clean false positives available, up to
    Rule-1's epoch caveat.

Scores per object, from the area-weighted mean embedding of 2017, 2021 and 2025:

  * `change`: 1 - cos(e2017, e2025). Direction-agnostic; the primary score.
  * `change_p75`: 75th percentile of per-pixel 1 - cos over the polygon, which a loose
    model outline dilutes less than a mean (mapped candidates carry OSM's tight geometry,
    unmapped ones the model's).
  * `learned`: logistic on e2025 - e2017, real against its own controls, fitted per
    placement and scored only out of group (1-degree cells), so construction or crop change
    can be told apart from an installation by direction, not just magnitude.
  * `learned_level`: the same plus the 2025 levels, which can also see an array built
    before 2017 (one that has nothing left to change).

Unmapped real share, per placement and size bin, by a threshold mixture on each score at
its control's 95th percentile: pi = (P_unmapped - P_their_controls) / (P_real -
P_their_controls_real), with a bootstrap over objects. Read against the table's
`p_unmapped`.

    pixi run python scripts/aef_large_array_change.py --plan   # populations + download size
    pixi run python scripts/aef_large_array_change.py
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.affinity import translate

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aef_mosaic as am  # noqa: E402

from earthpv.labels import dissolve_overlapping  # noqa: E402
from earthpv.roofclf import (L2, auc, discover_quadrats, fit_logistic,  # noqa: E402
                             load_boundary, predict_proba)

log = logging.getLogger("aef_large_array")

CANDS = Path("data/predictions/pakistan/candidates.parquet")
OSM = Path("data/labels/pakistan_overpass_solar.parquet")
TABLE = Path("configs/calibration/pakistan_candidate_precision.yaml")
OUT = Path("results/aef_large_array_change.json")
YEARS = (2025, 2017, 2021)  # fetch order: the two endpoints first; 2021 is optional
UTM = "EPSG:32642"  # metric buffers only; Pakistan spans 41N-43N, 42N is central
MATCH_M = 100.0
N_UNMAPPED_GROUND = 1000
N_MISSED = 500
SHIFT_M = (300.0, 1200.0)
ROOF_CTRL_RADIUS_M = 2000.0
N_ROOF_CTRL = 2
WORKERS = 4
N_BOOT = 500
SEED = 20261022
BINS = [0, 500, 1000, 5000, 50000, np.inf]
BIN_LABELS = ["<500", "500-1k", "1k-5k", "5k-50k", ">50k"]
# the table's own bin labels, so its p_unmapped can be read per bin
TABLE_BINS = {"<500": "100-500", "500-1k": "500-1k", "1k-5k": "1k-5k", "5k-50k": "5k-50k",
              ">50k": ">50k"}


# --------------------------------------------------------------------------------------
# Populations
# --------------------------------------------------------------------------------------
def _sizebin(a) -> pd.Series:
    return pd.cut(pd.Series(a), BINS, labels=BIN_LABELS, right=False).astype(str)


def build_objects(rng: np.random.Generator) -> gpd.GeoDataFrame:
    c = gpd.read_parquet(CANDS).to_crs(4326).reset_index(drop=True)
    c["placement2"] = np.where(c.placement == "rooftop", "rooftop", "ground")
    osm = gpd.read_parquet(OSM).to_crs(4326)
    osm = osm[osm.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    osm_d = dissolve_overlapping(osm).to_crs(4326)
    osm_u = osm_d.to_crs(UTM)
    cu = c.to_crs(UTM)
    near = gpd.sjoin(cu[["geometry"]], gpd.GeoDataFrame(geometry=osm_u.buffer(MATCH_M)),
                     predicate="intersects").index.unique()
    c["mapped"] = c.index.isin(near)

    # Rule-1 quadrat interiors (every discoverable quadrat, Kalat Rural included)
    qs = [load_boundary(Path("data/labels") / f"{s}_boundary.geojson") for s in discover_quadrats()]
    qd = gpd.GeoDataFrame(geometry=qs, crs=4326)
    inq = gpd.sjoin(gpd.GeoDataFrame(geometry=c.geometry.representative_point(), crs=4326),
                    qd, predicate="within").index.unique()
    c["in_quadrat"] = c.index.isin(inq)

    c["bin"] = _sizebin(c.area_m2.to_numpy())
    keep = c.mapped | (c.placement2 == "rooftop") | c.in_quadrat
    gu = c[~keep & (c.placement2 == "ground")]
    take = []
    for b, g in gu.groupby("bin"):
        k = int(round(N_UNMAPPED_GROUND * len(g) / len(gu)))
        take.extend(rng.choice(g.index.to_numpy(), size=min(k, len(g)), replace=False))
    c = c[keep | c.index.isin(take)].copy()
    c["role"] = np.where(c.mapped, "real", "unmapped")
    c["source"] = "candidate"
    c["obj_id"] = "cand_" + c.index.astype(str)

    # Segmentation misses: dissolved OSM >= 400 m2 with no candidate within 100 m
    allc = gpd.read_parquet(CANDS).to_crs(UTM)
    hit = gpd.sjoin(osm_u[["geometry"]], gpd.GeoDataFrame(geometry=allc.buffer(MATCH_M)),
                    predicate="intersects").index.unique()
    miss = osm_d[(osm_d.area_m2 >= 400) & ~osm_d.index.isin(hit)].copy()
    picks = []
    for pl, g in miss.groupby("placement"):
        picks.extend(rng.choice(g.index.to_numpy(), size=min(N_MISSED, len(g)), replace=False))
    miss = miss.loc[picks]
    m = gpd.GeoDataFrame({
        "obj_id": "miss_" + miss.index.astype(str), "placement2": miss.placement.to_numpy(),
        "area_m2": miss.area_m2.to_numpy(), "mapped": True, "in_quadrat": False,
        "role": "real", "source": "missed"}, geometry=miss.geometry.to_numpy(), crs=4326)
    m["bin"] = _sizebin(m.area_m2.to_numpy())
    cols = ["obj_id", "placement2", "area_m2", "mapped", "in_quadrat", "role", "source", "bin",
            "geometry"]
    objs = pd.concat([c[cols], m[cols]], ignore_index=True)
    return gpd.GeoDataFrame(objs, geometry="geometry", crs=4326), osm_d, gpd.read_parquet(CANDS).to_crs(4326)


def _chunks(geom) -> set:
    return set(am.chunks_for_bounds(*geom.bounds))


def build_controls(objs, osm, cands, rng) -> gpd.GeoDataFrame:
    """Displaced polygons for ground objects, nearby PV-free large roofs for rooftop ones."""
    from earthpv.buildings import fetch_vida_buildings

    avoid50 = pd.concat([osm.to_crs(UTM).geometry, cands.to_crs(UTM).geometry]).buffer(50.0)
    av = gpd.GeoDataFrame(geometry=avoid50.to_numpy(), crs=UTM)
    need = set().union(*[_chunks(g) for g in objs.geometry])
    rows = []
    ground = objs[objs.placement2 == "ground"]
    gu = ground.to_crs(UTM)
    for (i, o), gm in zip(ground.iterrows(), gu.geometry):
        best = None
        for _ in range(20):
            d = rng.uniform(*SHIFT_M)
            th = rng.uniform(0, 2 * math.pi)
            cand = translate(gm, d * math.cos(th), d * math.sin(th))
            if len(av.sindex.query(cand, predicate="intersects")):
                continue
            g4 = gpd.GeoSeries([cand], crs=UTM).to_crs(4326).iloc[0]
            if best is None:
                best = g4
            if _chunks(g4) <= need:
                best = g4
                break
        if best is not None:
            rows.append({"obj_id": "ctrl_" + o.obj_id, "of": o.obj_id, "geometry": best,
                         "placement2": "ground", "area_m2": o.area_m2})
    roof = objs[objs.placement2 == "rooftop"]
    if len(roof):
        # one VIDA query per 0.1-degree cell holding a rooftop object, never a national bbox
        rp = roof.geometry.representative_point()
        cells = sorted(set(zip(np.floor(rp.x * 10).astype(int), np.floor(rp.y * 10).astype(int))))
        parts = []
        for cx, cy in cells:
            v = fetch_vida_buildings((cx / 10 - 0.02, cy / 10 - 0.02, cx / 10 + 0.12, cy / 10 + 0.12),
                                     "PAK", min_area_m2=400.0)
            if len(v):
                parts.append(v[["area_m2", "geometry"]])
        vida = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
        vida = vida[~vida.geometry.representative_point().apply(lambda g: (round(g.x, 6), round(g.y, 6))).duplicated()]
        log.info("VIDA >= 400 m2 for rooftop controls: %d buildings in %d cells", len(vida), len(cells))
        vu = vida.to_crs(UTM)
        av30 = gpd.GeoDataFrame(geometry=pd.concat([osm.to_crs(UTM).geometry,
                                                    cands.to_crs(UTM).geometry]).buffer(30.0).to_numpy(),
                                crs=UTM)
        bad = gpd.sjoin(vu[["geometry"]], av30, predicate="intersects").index.unique()
        vu = vu[~vu.index.isin(bad)]
        used = set()
        ru = roof.to_crs(UTM)
        for (i, o), gm in zip(roof.iterrows(), ru.geometry):
            near = vu.iloc[vu.sindex.query(gm.centroid.buffer(ROOF_CTRL_RADIUS_M))]
            near = near[~near.index.isin(used)]
            if near.empty:
                continue
            dl = (np.log10(near.area_m2.clip(lower=1)) - np.log10(max(o.area_m2, 1))).abs()
            for j in dl.sort_values().index[:N_ROOF_CTRL]:
                used.add(j)
                rows.append({"obj_id": f"ctrl_{o.obj_id}_{j}", "of": o.obj_id,
                             "geometry": vida.loc[j, "geometry"], "placement2": "rooftop",
                             "area_m2": float(vida.loc[j, "area_m2"])})
    ctl = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    meta = objs.set_index("obj_id")
    ctl["role"] = "control"
    ctl["source"] = "control"
    ctl["of_role"] = ctl["of"].map(meta.role)
    ctl["of_source"] = ctl["of"].map(meta.source)
    ctl["mapped"] = False
    ctl["in_quadrat"] = False
    ctl["bin"] = ctl["of"].map(meta.bin)  # a control is binned with the object it controls
    return ctl


# --------------------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------------------
def prefetch(keys: list[tuple], workers: int = WORKERS) -> None:
    t0, got, done = time.time(), 0, 0
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(am.fetch, *k) for k in keys]
        for f in as_completed(futs):
            got += f.result()
            done += 1
            if done % 100 == 0 or done == len(keys):
                dt = time.time() - t0
                log.info("  fetched %d/%d chunks, %.2f GB, %.2f MB/s", done, len(keys),
                         got / 1e9, got / 1e6 / max(dt, 1e-6))


@lru_cache(maxsize=256)
def _decoded(year: int, cy: int, cx: int):
    return am.chunk(year, cy, cx)


def object_features(geom, years=YEARS) -> dict:
    from earthpv.preprocess import coverage_matrix

    pad = 3 * am.GSD
    minx, miny, maxx, maxy = geom.bounds
    out = {}
    pix = {}
    for y in years:
        raw, tr = am.window(y, minx - pad, miny - pad, maxx + pad, maxy + pad, chunk_fn=_decoded)
        arr = am.dequantize(raw)
        nb, h, w = arr.shape
        A = coverage_matrix(gpd.GeoSeries([geom]), (h, w), tr, subpix=4)
        wts = np.asarray(A.todense()).ravel()
        flat = arr.reshape(nb, -1)
        ok = np.isfinite(flat).all(0) & (wts > 0)
        if wts[ok].sum() <= 0:
            # smaller than a subpixel: the pixel under the representative point
            p = geom.representative_point()
            r, c = int((tr.f - p.y) / am.GSD), int((p.x - tr.c) / am.GSD)
            r, c = min(max(r, 0), h - 1), min(max(c, 0), w - 1)
            out[y] = arr[:, r, c]
            pix[y] = arr[:, r, c][:, None]
            continue
        out[y] = (flat[:, ok] * wts[ok]).sum(1) / wts[ok].sum()
        sel = ok & (wts >= 0.25) if (ok & (wts >= 0.25)).any() else ok
        pix[y] = flat[:, sel]
    return out, pix


def _cos(a, b, axis=0):
    return np.sum(a * b, axis=axis) / (np.linalg.norm(a, axis=axis) * np.linalg.norm(b, axis=axis))


def featurise(df: gpd.GeoDataFrame, years=YEARS) -> pd.DataFrame:
    rows = []
    # walk objects in chunk order so the decoded-chunk cache is reused
    order = np.lexsort((df.geometry.bounds.minx.to_numpy(), df.geometry.bounds.maxy.to_numpy()))
    for k, i in enumerate(order):
        o = df.iloc[i]
        e, pix = object_features(o.geometry, years)
        if any(np.isnan(e[y]).any() for y in years):
            continue
        r = {"obj_id": o.obj_id}
        for y in years:
            for d in range(64):
                r[f"e{y}_{d:02d}"] = float(e[y][d])
        r["change"] = 1 - _cos(e[2017], e[2025])
        if 2021 in years:
            r["change_17_21"] = 1 - _cos(e[2017], e[2021])
            r["change_21_25"] = 1 - _cos(e[2021], e[2025])
        r["change_p75"] = float(np.percentile(1 - _cos(pix[2017], pix[2025]), 75))
        rows.append(r)
        if (k + 1) % 1000 == 0:
            log.info("  featurised %d/%d", k + 1, len(df))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------
def learned_scores(d: pd.DataFrame, level: bool) -> np.ndarray:
    dims = [f"{d_:02d}" for d_ in range(64)]
    X = np.stack([d[f"e2025_{k}"] - d[f"e2017_{k}"] for k in dims], 1)
    if level:
        X = np.hstack([X, d[[f"e2025_{k}" for k in dims]].to_numpy()])
    out = np.full(len(d), np.nan)
    for pl in ("ground", "rooftop"):
        P = (d.placement2 == pl).to_numpy()
        train = P & ((d.role == "real") | (d.of_role == "real")).to_numpy()
        y = (d.role == "real").to_numpy(float)
        for g in np.unique(d.group[P]):
            te = P & (d.group == g).to_numpy()
            tr = train & ~(d.group == g).to_numpy()
            if y[tr].min() == y[tr].max():
                continue
            out[te] = predict_proba(fit_logistic(X[tr], y[tr], L2), X[te])
    return out


def _mixture(d, score, rng) -> dict:
    """pi = (P_u - P_cu) / (P_r - P_cr) at the controls' 95th percentile."""
    ctrl = d[d.role == "control"]
    t = np.nanpercentile(ctrl[score], 95)
    # the real reference is real CANDIDATES (same detector as the unmapped ones), each
    # side against its own controls
    grp = {("real", None): d[(d.role == "real") & (d.source == "candidate")],
           ("unmapped", None): d[d.role == "unmapped"],
           ("control", "control_of_real"): d[(d.of_role == "real") & (d.of_source == "candidate")],
           ("control", "control_of_unmapped"): d[d.of_role == "unmapped"]}

    def est(g):
        pr, pu = (g[("real", None)][score] > t).mean(), (g[("unmapped", None)][score] > t).mean()
        cr = (g[("control", "control_of_real")][score] > t).mean()
        cu = (g[("control", "control_of_unmapped")][score] > t).mean()
        den = pr - cr
        return (pu - cu) / den if den > 0.02 else np.nan, pr, pu, cr, cu

    pi, pr, pu, cr, cu = est(grp)
    boots = []
    for _ in range(N_BOOT):
        gb = {k: v.sample(len(v), replace=True, random_state=int(rng.integers(2**31)))
              for k, v in grp.items() if len(v)}
        if len(gb) < 4:
            break
        boots.append(est(gb)[0])
    boots = np.array([b for b in boots if np.isfinite(b)])
    return {"pi": None if not np.isfinite(pi) else round(float(pi), 3),
            "pi_ci90": ([round(float(np.percentile(boots, 5)), 3),
                         round(float(np.percentile(boots, 95)), 3)] if boots.size > 50 else None),
            "exceed_real": round(float(pr), 3), "exceed_unmapped": round(float(pu), 3),
            "exceed_ctrl_real": round(float(cr), 3), "exceed_ctrl_unmapped": round(float(cu), 3),
            "n_real": int(len(grp[("real", None)])), "n_unmapped": int(len(grp[("unmapped", None)]))}


def analyse(d: pd.DataFrame) -> dict:
    import yaml

    rng = np.random.default_rng(SEED + 1)
    tab = yaml.safe_load(TABLE.read_text())["placement_bins"]
    scores = ["change", "change_p75", "learned", "learned_level"]
    out = {"n_objects": d.role.value_counts().to_dict(), "auc": {}, "missed": {},
           "unmapped_share": {}, "quadrat": {}, "timing": {}}
    for pl in ("ground", "rooftop"):
        P = d[d.placement2 == pl]
        for b in BIN_LABELS + ["all"]:
            B = P if b == "all" else P[P.bin == b]
            real = B[(B.role == "real") & (B.source == "candidate")]
            miss = B[(B.role == "real") & (B.source == "missed")]
            cr = B[(B.of_role == "real") & (B.of_source == "candidate")]
            cm = B[B.of_source == "missed"]
            key = f"{pl}|{b}"
            out["auc"][key] = {"n_real_cand": len(real), "n_ctrl": len(cr)}
            for s in scores:
                if len(real) >= 10 and len(cr) >= 10:
                    out["auc"][key][s] = round(auc(np.r_[np.ones(len(real)), np.zeros(len(cr))],
                                                   np.r_[real[s], cr[s]]), 4)
            # missed: recall at the controls' 5% false-positive rate
            if len(miss) >= 10 and len(cm) >= 10:
                out["missed"][key] = {"n": len(miss)}
                for s in scores:
                    t = np.nanpercentile(cm[s], 95)
                    out["missed"][key][f"recall_fpr05_{s}"] = round(float((miss[s] > t).mean()), 3)
                    out["missed"][key][f"auc_{s}"] = round(auc(
                        np.r_[np.ones(len(miss)), np.zeros(len(cm))], np.r_[miss[s], cm[s]]), 4)
            if b != "all" and (B.role == "unmapped").sum() >= 15:
                row = {s: _mixture(B, s, rng) for s in ("change", "learned", "learned_level")}
                tb = [x for x in tab[pl] if x["label"] == TABLE_BINS[b]]
                if tb:
                    row["table_p_unmapped"] = tb[0]["p_unmapped"]
                    row["table_mapped_frac"] = tb[0]["mapped_frac"]
                out["unmapped_share"][key] = row
        q = P[P.in_quadrat]
        if len(q):
            out["quadrat"][pl] = {
                "n_mapped": int((q.role == "real").sum()), "n_unmapped": int((q.role == "unmapped").sum()),
                **{f"median_{s}_{r}": round(float(q[q.role == r][s].median()), 4)
                   for s in scores for r in ("real", "unmapped") if (q.role == r).any()}}
        real = P[P.role == "real"]
        if "change_21_25" not in P:
            continue
        out["timing"][pl] = {
            "median_change_17_21": round(float(real.change_17_21.median()), 4),
            "median_change_21_25": round(float(real.change_21_25.median()), 4),
            "share_mostly_after_2021": round(float((real.change_21_25 > real.change_17_21).mean()), 3),
            "controls_share_mostly_after_2021": round(float(
                (P[P.role == "control"].change_21_25 > P[P.role == "control"].change_17_21).mean()), 3),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="build populations, report size, stop")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--years", type=int, nargs="+", default=list(YEARS),
                    help="2017 and 2025 are required; 2021 adds the timing split")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = np.random.default_rng(SEED)

    pop_path = OUT.with_name(OUT.stem + "_population.parquet")
    if pop_path.exists():
        df = gpd.read_parquet(pop_path)
    else:
        objs, osm, cands = build_objects(rng)
        ctl = build_controls(objs, osm, cands, rng)
        df = gpd.GeoDataFrame(pd.concat([objs, ctl], ignore_index=True), crs=4326)
        df["group"] = (np.floor(df.geometry.representative_point().x).astype(int).astype(str) + "_"
                       + np.floor(df.geometry.representative_point().y).astype(int).astype(str))
        # a control lives in its object's group, so a fold never splits a pair
        gmap = df.set_index("obj_id").group
        m = df["of"].notna()
        df.loc[m, "group"] = df.loc[m, "of"].map(gmap)
        df.to_parquet(pop_path)
    log.info("population:\n%s", df.groupby(["placement2", "role", "source"]).size().to_string())
    keys = sorted(set().union(*[_chunks(g) for g in df.geometry]))
    log.info("%d inner chunks per year, ~%.1f GB per year at 2.5 MB/chunk", len(keys),
             len(keys) * 2.5 / 1000)
    if args.plan:
        return
    years = tuple(args.years)
    assert {2017, 2025} <= set(years), "2017 and 2025 are the change endpoints"
    for y in years:
        log.info("fetching %d", y)
        prefetch([(y, *k) for k in keys], workers=args.workers)

    feat_path = OUT.with_name(OUT.stem + "_features_" + "_".join(map(str, sorted(years))) + ".parquet")
    if feat_path.exists():
        f = pd.read_parquet(feat_path)
    else:
        f = featurise(df, years)
        f.to_parquet(feat_path)
    d = df.drop(columns="geometry").merge(f, on="obj_id")
    for col in ("of_role", "of_source"):
        d[col] = d[col].fillna("")
    d["learned"] = learned_scores(d, level=False)
    d["learned_level"] = learned_scores(d, level=True)
    keep = [c for c in ("obj_id", "placement2", "role", "source", "of", "of_role", "of_source",
                        "bin", "area_m2", "in_quadrat", "group", "change", "change_p75",
                        "change_17_21", "change_21_25", "learned", "learned_level") if c in d]
    d[keep].to_csv(OUT.with_name(OUT.stem + "_scores.csv"), index=False)
    res = analyse(d)
    OUT.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
