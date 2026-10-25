"""OlmoEarth v1.3 as a second >= 400 m2 detector, against AlphaEarth and segmentation.

`aef_vs_segmentation.py --national-negatives` ran AlphaEarth (AEF, 64-d) wall to wall
against the production candidate set: not better overall, but complementary, lifting
quadrat rooftop recall from 0.35 to 0.60 in union. Ai2's OlmoEarth v1.3 embeddings
(released 2026-10-22, 128-d with a nested 64-d prefix, one per 10 m pixel per calendar
year) report beating AEF on most of their benchmarks. This asks whether they do here: same
evaluation areas, truth, detector, thresholds and scoring as the AEF run, only the
embedding differs.

Declared before measuring:

  * Same 20 random cells, 20 PV-rich cells and Rule-1 quadrats (`aef_vs_segmentation.
    eval_sets`, same seed), same truth (July 2026 OSM snapshot, dissolved, arrays >= 400 m2,
    a detection "mapped" if OSM solar lies within 100 m), same candidate set.
  * Same detector: a per-pixel L2 logistic, positives >= 75% covered by a mapped array
    >= 400 m2, negatives > 30 m from one, 150 per training tile around the AEF study's
    10,373 objects plus 400 per tile from 60 random national cells (6 tiles each), nothing
    within 0.02 deg of an evaluation area, at most 150,000 positives. Components of
    p >= tau (8-connected), kept at >= 400 m2.
  * **Change baseline 2023, not 2017.** v1.3 is global for 2023-2025 only; over Pakistan
    the 2017-2022 backfill is partial (checked 2026-10-24: zone 43 from 2017, Multan from
    2022, Quetta from 2023). So AEF is re-run with the same 2023 baseline
    (`aef_vs_segmentation.py --national-negatives --base-year 2023`) and the comparison of
    embeddings is made there; AEF's published 2017-baseline run is reported beside it.
  * Variants `change` (e2025 - e2023), `level` (e2025), `both`, at 128-d and at the 64-d
    prefix, AEF's dimension.
  * Operating point, per embedding: `both` at the first tau whose false-positive burden in
    the random cells is below segmentation's (8.5 unmapped detections per 1,000 km2), the
    rule that picked AEF's tau 0.99.

Licence: the embeddings are under the OlmoEarth Artifact License, which bans military and
extractive uses and requires those bans on any distributed derivative. Nothing derived
from them is published by this script.

    pixi run python scripts/olmoearth_vs_segmentation.py --plan
    pixi run python scripts/olmoearth_vs_segmentation.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from scipy import ndimage
from shapely import make_valid
from shapely.geometry import box, shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aef_vs_segmentation as avs  # noqa: E402
import olmoearth_mosaic as om  # noqa: E402

from earthpv.labels import dissolve_overlapping  # noqa: E402
from earthpv.roofclf import L2, fit_logistic, predict_proba  # noqa: E402

log = logging.getLogger("olmo_vs_seg")

OUT = Path("results/olmoearth_vs_segmentation")
WORK = Path("/home/tobi/earthpv_data/olmoearth/vs_seg")
AEF_WORK = avs.WORK
BASE_YEAR, YEAR = 2023, 2025
DIMS = (128, 64)
PX_M2 = om.GSD**2
BATCH = 200_000


def _zones_of(geom) -> list[int]:
    minx, _, maxx, _ = geom.bounds
    return list(range(om.zone_of(minx), om.zone_of(maxx) + 1))


def _band(z: int):
    lon0 = -180 + 6 * (z - 1)
    return box(lon0, -80, lon0 + 6, 84)


def _keys_for(gdf: gpd.GeoDataFrame) -> set[tuple[int, int, int]]:
    """OlmoEarth tiles (zone, row, col) covering each geometry, in the zone(s) it touches."""
    out = set()
    for geom in gdf.geometry:
        for z in _zones_of(geom):
            part = box(*geom.bounds).intersection(_band(z))  # only bounds matter here
            if part.is_empty:
                continue
            b = gpd.GeoSeries([part], crs=4326).to_crs(om.epsg(z)).total_bounds
            out |= {(z, *k) for k in om.chunks_for_bounds(z, *b)}
    return out


def _tile_box(z: int, cy: int, cx: int):
    t = om.chunk_transform(z, cy, cx)
    return box(t.c, t.f - om.INNER * om.GSD, t.c + om.INNER * om.GSD, t.f)


def national_negative_keys(exclude, rng, grid=avs.GRID) -> list[tuple[int, int, int]]:
    """`aef_vs_segmentation.national_negative_keys` on OlmoEarth's tiles: the same 60 random
    density cells, up to 6 tiles of each."""
    g = gpd.read_parquet(grid)
    ex = exclude.buffer(avs.BUFFER_DEG).union_all()
    g = g[~g.geometry.intersects(ex)]
    cells = g.loc[rng.choice(g.index.to_numpy(), avs.NAT_CELLS, replace=False)]
    keys = []
    for geom in cells.geometry:
        ks = sorted(_keys_for(gpd.GeoDataFrame(geometry=[geom], crs=4326)))
        keys += [ks[i] for i in rng.choice(len(ks), min(avs.NAT_CHUNKS_PER_CELL, len(ks)),
                                           replace=False)]
    return sorted(set(keys))


def _features(eb, e25, variant, dims):
    """(n_px, d) design matrix from (128, n_px) dequantised embeddings."""
    eb, e25 = eb[:dims], e25[:dims]
    if variant == "change":
        return (e25 - eb).T
    if variant == "level":
        return e25.T
    return np.vstack([e25 - eb, e25]).T


def training_sample(truth, exclude, rng, foot_keys, extra_keys, dims=128):
    """`dims` is how many bands are read: 64 fetches only the Matryoshka prefix."""
    extra = set(extra_keys)
    keys = sorted(set(foot_keys) | extra)
    ex4326 = exclude.buffer(avs.BUFFER_DEG).union_all()
    ex = {z: gpd.GeoSeries([ex4326.intersection(_band(z).buffer(1))], crs=4326)
          .to_crs(om.epsg(z)).iloc[0] for z in {k[0] for k in keys}}
    tz = {z: truth.to_crs(om.epsg(z)) for z in ex}
    tidx = {z: t.sindex for z, t in tz.items()}
    XB, X25, Y = [], [], []
    for k, (z, cy, cx) in enumerate(keys):
        cb = _tile_box(z, cy, cx)
        if cb.intersects(ex[z]):
            continue
        ab, a25 = om.chunk(z, BASE_YEAR, cy, cx, dims), om.chunk(z, YEAR, cy, cx, dims)
        if ab is None or a25 is None:
            continue
        t = om.chunk_transform(z, cy, cx)
        hit = tz[z].iloc[tidx[z].query(cb, predicate="intersects")]
        if len(hit):
            fine = rasterio.Affine(om.GSD / 4, 0, t.c, 0, -om.GSD / 4, t.f)
            r = rasterio.features.rasterize(((gm, 1) for gm in hit.geometry),
                                            out_shape=(om.INNER * 4, om.INNER * 4),
                                            transform=fine, fill=0, dtype="uint8")
            cov = r.reshape(om.INNER, 4, om.INNER, 4).mean(axis=(1, 3))
        else:
            cov = np.zeros((om.INNER, om.INNER))
        valid = (ab[0] != om.NODATA) & (a25[0] != om.NODATA)
        pos = valid & (cov >= avs.POS_COVER)
        far = ndimage.distance_transform_edt(cov == 0) > avs.NEG_DIST_PX
        negc = np.flatnonzero((valid & far).ravel())
        nn = avs.NAT_NEG_PER_CHUNK if (z, cy, cx) in extra else avs.NEG_PER_CHUNK
        neg = rng.choice(negc, size=min(nn, negc.size), replace=False) if negc.size else []
        for idx, yv in ((np.flatnonzero(pos.ravel()), 1), (np.asarray(neg, dtype=int), 0)):
            if len(idx) == 0:
                continue
            XB.append(ab.reshape(dims, -1)[:, idx])
            X25.append(a25.reshape(dims, -1)[:, idx])
            Y.append(np.full(len(idx), yv, dtype=np.int8))
        if (k + 1) % 500 == 0:
            log.info("  training tiles %d/%d", k + 1, len(keys))
    XB, X25, Y = np.hstack(XB), np.hstack(X25), np.concatenate(Y)
    p = np.flatnonzero(Y == 1)
    if p.size > avs.MAX_POS:
        drop = rng.choice(p, size=p.size - avs.MAX_POS, replace=False)
        keep = np.setdiff1d(np.arange(Y.size), drop)
        XB, X25, Y = XB[:, keep], X25[:, keep], Y[keep]
    log.info("training pixels: %d positive, %d negative", int(Y.sum()), int((Y == 0).sum()))
    return om.dequantize(XB), om.dequantize(X25), Y


def detect(models, geom, dims=128, taus=avs.TAUS) -> dict[str, gpd.GeoDataFrame]:
    """Detections per model and tau over one evaluation area, one read per UTM zone."""
    acc: dict[str, list] = {}
    geom = make_valid(geom)
    for z in _zones_of(geom):
        part = geom.intersection(_band(z))
        if part.is_empty:
            continue
        pu = gpd.GeoSeries([part], crs=4326).to_crs(om.epsg(z)).iloc[0]
        rb, tr = om.window(z, BASE_YEAR, *pu.bounds, dims=dims)
        r25, _ = om.window(z, YEAR, *pu.bounds, dims=dims)
        h, w = rb.shape[1:]
        valid = ((rb[0] != om.NODATA) & (r25[0] != om.NODATA)).ravel()
        inside = rasterio.features.geometry_mask([pu], (h, w), tr, invert=True).ravel()
        ok = np.flatnonzero(valid & inside)
        rb, r25 = rb.reshape(dims, -1), r25.reshape(dims, -1)
        probs = {key: np.zeros(h * w, dtype="float32") for key in models}
        for s in range(0, ok.size, BATCH):
            sl = ok[s:s + BATCH]
            eb, e25 = om.dequantize(rb[:, sl]), om.dequantize(r25[:, sl])
            for (dims, v), m in models.items():
                probs[(dims, v)][sl] = predict_proba(m, _features(eb, e25, v, dims))
        for (dims, v), p in probs.items():
            p = p.reshape(h, w)
            for tau in taus:
                lab, n = ndimage.label(p >= tau, structure=np.ones((3, 3)))
                if n == 0:
                    continue
                sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1)) * PX_M2
                keep = np.flatnonzero(sizes >= avs.MIN_AREA) + 1
                if keep.size == 0:
                    continue
                lab = np.where(np.isin(lab, keep), lab, 0).astype("int32")
                pmean = ndimage.mean(p, lab, index=keep)
                polys = {}
                for gj, val in rasterio.features.shapes(lab, mask=lab > 0, transform=tr):
                    polys.setdefault(int(val), []).append(shape(gj))
                g = gpd.GeoDataFrame(
                    [{"label": k_, "area_m2": float(sizes[k_ - 1]), "p_mean": float(pm),
                      "zone": z, "geometry": gpd.GeoSeries(polys[k_]).union_all()}
                     for k_, pm in zip(keep, pmean)], geometry="geometry", crs=om.epsg(z))
                acc.setdefault(f"olmo{dims}_{v}@{tau}", []).append(g.to_crs(4326))
    return {k: gpd.GeoDataFrame(pd.concat(v, ignore_index=True), crs=4326) for k, v in acc.items()}


def _aef_dets(setname: str, tag: str, prefix: str) -> dict[str, gpd.GeoDataFrame]:
    out = {}
    for v in avs.VARIANTS:
        for tau in avs.TAUS:
            f = AEF_WORK / f"det{tag}_{setname}_{v}_{tau}.parquet"
            if f.exists():
                out[f"{prefix}_{v}@{tau}"] = gpd.read_parquet(f).to_crs(4326)
    return out


def operating_points(res: pd.DataFrame, taus=avs.TAUS) -> dict[str, str]:
    """The declared rule: per embedding, `both` at the first tau whose random-cell burden
    is below segmentation's at confidence 0."""
    r = res[res.set == "random"].set_index("instrument")
    seg = r.loc["seg@conf0.0", "unmapped_per_1000km2"]
    ops = {}
    for emb in sorted({i.split("_")[0] for i in r.index if not i.startswith("seg@")}):
        for tau in taus:
            key = f"{emb}_both@{tau}"
            if key in r.index and r.loc[key, "unmapped_per_1000km2"] < seg:
                ops[emb] = key
                break
    return ops


def unions(sets, dets, cands, truth, ops) -> pd.DataFrame:
    """Recall of segmentation in union with each operating point, and with both embeddings,
    and how many arrays only one embedding adds."""
    rows = []
    for setname in ("rich", "quadrats"):
        S = sets[sets.set == setname]
        if S.empty:  # a country without Rule-1 quadrats
            continue
        inside = lambda g: g[g.representative_point().within(S.union_all())]  # noqa: E731
        T = inside(truth)
        seg = avs._near(T, inside(cands[cands.area_m2 >= avs.MIN_AREA]))
        found = {emb: avs._near(T, dets[setname][key]) for emb, key in ops.items()}
        for pl in ("all", "rooftop", "ground"):
            m = np.ones(len(T), bool) if pl == "all" else (T.placement == pl).to_numpy()
            r = {"set": setname, "placement": pl, "n_truth": int(m.sum()),
                 "seg": round(float(seg[m].mean()), 3)}
            for emb, f in found.items():
                r[f"seg+{emb}"] = round(float((seg | f)[m].mean()), 3)
            embs = list(found)
            for a in embs:
                for b in embs:
                    if a < b:
                        r[f"seg+{a}+{b}"] = round(float((seg | found[a] | found[b])[m].mean()), 3)
                        r[f"only_{a}_not_seg_{b}"] = int((found[a] & ~seg & ~found[b])[m].sum())
                        r[f"only_{b}_not_seg_{a}"] = int((found[b] & ~seg & ~found[a])[m].sum())
            rows.append(r)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = np.random.default_rng(avs.SEED)
    WORK.mkdir(parents=True, exist_ok=True)

    sets = avs.eval_sets(rng)
    saved = gpd.read_parquet(AEF_WORK / "eval_sets.parquet")
    assert list(saved["name"]) == list(sets["name"]), "evaluation areas differ from the AEF run"
    eval_keys = _keys_for(sets)
    pop = gpd.read_parquet(avs.POP).to_crs(4326)
    foot_keys = _keys_for(pop)
    extra = national_negative_keys(sets, np.random.default_rng(avs.SEED + 7))
    allk = sorted(eval_keys | foot_keys | set(extra))
    todo = [(z, y, b, cy, cx) for (z, cy, cx) in allk for y in (BASE_YEAR, YEAR)
            for b in range(om.BLOCKS)]
    cached = sum(om._chunk_path(*k).exists() for k in todo)
    log.info("tiles: %d eval, %d training, %d national negatives; %d chunks, %d cached "
             "(~%.0f GB to fetch at ~3.6 MB a chunk)", len(eval_keys), len(foot_keys),
             len(extra), len(todo), cached, (len(todo) - cached) * 3.6 / 1000)
    if args.plan:
        return
    om.prefetch(todo, workers=args.workers)

    osm = gpd.read_parquet(avs.OSM).to_crs(4326)
    osm = osm[osm.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    osm_d = dissolve_overlapping(osm).to_crs(4326)
    truth = osm_d[osm_d.area_m2 >= avs.MIN_AREA].reset_index(drop=True)
    cands = gpd.read_parquet(avs.CANDS).to_crs(4326)

    XB, X25, Y = training_sample(truth, sets, rng, foot_keys, extra)
    models = {}
    for dims in DIMS:
        for v in avs.VARIANTS:
            models[(dims, v)] = fit_logistic(_features(XB, X25, v, dims).astype("float64"),
                                             Y.astype(float), L2)
            log.info("fitted %d-d %s (converged %s)", dims, v, models[(dims, v)]["converged"])
    del XB, X25

    dets = {}
    for setname, S in sets.groupby("set"):
        acc = {}
        for _, row in S.iterrows():
            for key, g in detect(models, row.geometry).items():
                acc.setdefault(key, []).append(g.assign(area_name=row["name"]))
            log.info("  detected %s %s", setname, row["name"])
        dets[setname] = {k: gpd.GeoDataFrame(pd.concat(v, ignore_index=True), crs=4326)
                         for k, v in acc.items()}
        for k, g in dets[setname].items():
            g.to_parquet(WORK / f"det_{setname}_{k.replace('@', '_')}.parquet")
        dets[setname].update(_aef_dets(setname, "_natneg", "aef17"))
        dets[setname].update(_aef_dets(setname, "_natneg_base2023", "aef23"))

    res = avs.score(sets, dets, cands, osm, truth)
    ops = operating_points(res)
    un = unions(sets, dets, cands, truth, ops)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT.with_suffix(".csv"), index=False)
    un.to_csv(OUT.with_name(OUT.name + "_unions.csv"), index=False)
    OUT.with_suffix(".json").write_text(json.dumps({
        "base_year": BASE_YEAR, "year": YEAR, "n_train_pos": int(Y.sum()),
        "n_train_neg": int((Y == 0).sum()), "converged": {f"{d}_{v}": bool(m["converged"])
                                                          for (d, v), m in models.items()},
        "operating_points": ops, "rows": res.to_dict(orient="records"),
        "unions": un.to_dict(orient="records")}, indent=2, default=str))
    cols = ["set", "instrument", "n_det", "precision_lb", "unmapped_per_1000km2", "recall",
            "recall_ground", "recall_rooftop", "recall_union_seg"]
    with pd.option_context("display.width", 250, "display.max_rows", 400):
        print("operating points:", ops)
        print(res[res.instrument.isin(["seg@conf0.0", *ops.values()])][cols].to_string(index=False))
        print(un.to_string(index=False))


if __name__ == "__main__":
    main()
