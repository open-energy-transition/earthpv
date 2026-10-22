"""AlphaEarth as a second >= 400 m2 detector: better than segmentation, or an alternative?

Every AEF result so far scored objects someone else had already found (segmentation
candidates, mapped arrays, their controls). A detector has to find arrays itself, wall to
wall, and pay for its false positives. This runs one, and segmentation, over the same
cells against the same truth.

The AEF detector is a per-pixel logistic over the frozen embedding: positives are pixels at
least 75% covered by a mapped OSM array >= 400 m2 (2026-07-18 snapshot), negatives are
random pixels more than 30 m from any mapped PV, both drawn from the 2,215 chunks
`aef_large_array_change.py` already cached, never from an evaluation cell or quadrat (2 km
buffer). Three declared feature sets: `change` (e2025 - e2017, the one the reviews
favoured), `level` (e2025 alone, a single epoch like segmentation's input), `both`.
Detections are connected components of p >= tau, kept at >= 400 m2.

Evaluation, all seeded and declared here:

  * `random`: 20 cells drawn uniformly from the national density grid (segmentation's own
    footprint): the false-positive burden an instrument carries where PV is rare.
  * `rich`: 20 cells drawn from the 239 holding two or more mapped arrays >= 400 m2: recall.
  * `quadrats`: the Rule-1 quadrats, the only exhaustively mapped truth, where an unmatched
    detection is a false positive (up to Rule-1's epoch caveat) rather than maybe unmapped.

Truth is the July snapshot, dissolved, arrays >= 400 m2; a detection is "mapped" if any OSM
solar feature is within 100 m (the precision table's `min_distance_m`), which makes
precision a lower bound for both instruments alike. Segmentation is the production candidate
set at area >= 400 m2, swept stricter by candidate `confidence`; AEF is swept by `tau`.

Known asymmetry, stated rather than corrected: AEF's newest year is calendar 2025, while
segmentation reads late-2025 to mid-2026 composites, so an array built in 2026 is visible
to one instrument only.

    pixi run python scripts/aef_vs_segmentation.py --plan
    pixi run python scripts/aef_vs_segmentation.py
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
from shapely.geometry import box, shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aef_mosaic as am  # noqa: E402
from aef_large_array_change import prefetch  # noqa: E402

from earthpv.labels import dissolve_overlapping  # noqa: E402
from earthpv.roofclf import (L2, discover_quadrats, fit_logistic,  # noqa: E402
                             load_boundary, predict_proba)

log = logging.getLogger("aef_vs_seg")

GRID = Path("data/predictions/pakistan/density/grid.geoparquet")
CANDS = Path("data/predictions/pakistan/candidates.parquet")
OSM = Path("data/labels/pakistan_overpass_solar.parquet")
OUT = Path("results/aef_vs_segmentation.json")
WORK = Path("/home/tobi/earthpv_data/aef/aef_vs_seg")
UTM = "EPSG:32642"
SEED = 20261024
POP = Path("results/aef_large_array_change_population.parquet")
N_RANDOM, N_RICH = 20, 20
BUFFER_DEG = 0.02
MIN_AREA = 400.0
MATCH_M = 100.0
POS_COVER = 0.75
NEG_DIST_PX = 3
NEG_PER_CHUNK = 150
MAX_POS = 150_000
TAUS = (0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995)
SEG_CONF = (0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
VARIANTS = ("change", "level", "both")
# --national-negatives: the first run drew every negative from chunks around known PV, so
# the detector never saw mountain, river or open desert, and its false-positive burden in the
# random cells may be the training set's fault rather than the embedding's. These add
# negatives from random density cells, a few chunks each, disjoint from every evaluation area.
NAT_CELLS, NAT_CHUNKS_PER_CELL, NAT_NEG_PER_CHUNK = 60, 6, 400


def _pixel_area_m2(lat: float) -> float:
    return (am.GSD * 111320.0) ** 2 * np.cos(np.radians(lat))


def _features(e17, e25, variant):
    """(n_px, d) design matrix from (64, n_px) dequantised embeddings."""
    if variant == "change":
        return (e25 - e17).T
    if variant == "level":
        return e25.T
    return np.vstack([e25 - e17, e25]).T


def eval_sets(rng):
    g = gpd.read_parquet(GRID)
    o = gpd.read_parquet(OSM).to_crs(4326)
    o = o[o.area_m2 >= MIN_AREA]
    j = gpd.sjoin(gpd.GeoDataFrame(geometry=o.representative_point(), crs=4326),
                  g[["geometry"]], predicate="within")
    g["n_osm400"] = g.index.map(j.groupby("index_right").size()).fillna(0).astype(int)
    rand = g.loc[rng.choice(g.index.to_numpy(), N_RANDOM, replace=False)]
    rich_pool = g[(g.n_osm400 >= 2) & ~g.index.isin(rand.index)]
    rich = rich_pool.loc[rng.choice(rich_pool.index.to_numpy(), N_RICH, replace=False)]
    qs = [(s, load_boundary(Path("data/labels") / f"{s}_boundary.geojson"))
          for s in discover_quadrats()]
    rows = ([{"set": "random", "name": c, "geometry": geom} for c, geom in zip(rand.cell, rand.geometry)]
            + [{"set": "rich", "name": c, "geometry": geom} for c, geom in zip(rich.cell, rich.geometry)]
            + [{"set": "quadrats", "name": s, "geometry": geom} for s, geom in qs])
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)


# --------------------------------------------------------------------------------------
# Training on the cached chunks
# --------------------------------------------------------------------------------------
def _footprint_keys() -> list[tuple[int, int]]:
    pop = gpd.read_parquet(POP)
    return sorted(set().union(*[set(am.chunks_for_bounds(*g.bounds)) for g in pop.geometry]))


FOOTPRINT_KEYS: list = []


def national_negative_keys(exclude, rng) -> list[tuple[int, int]]:
    g = gpd.read_parquet(GRID)
    ex = exclude.buffer(BUFFER_DEG).union_all()
    g = g[~g.geometry.intersects(ex)]
    cells = g.loc[rng.choice(g.index.to_numpy(), NAT_CELLS, replace=False)]
    keys = []
    for geom in cells.geometry:
        ks = am.chunks_for_bounds(*geom.bounds)
        keys += [ks[i] for i in rng.choice(len(ks), min(NAT_CHUNKS_PER_CELL, len(ks)), replace=False)]
    return sorted(set(keys))


def training_sample(osm_d, exclude, rng, extra_keys=()):
    keys = sorted({tuple(map(int, p.stem.split("_"))) for p in (am.CACHE / "2017").glob("*.zst")}
                  & {tuple(map(int, p.stem.split("_"))) for p in (am.CACHE / "2025").glob("*.zst")}
                  & set(FOOTPRINT_KEYS))
    extra = set(extra_keys)
    keys = sorted(set(keys) | extra)
    ex = exclude.buffer(BUFFER_DEG).union_all()
    osm_sidx = osm_d.sindex
    X17, X25, Y = [], [], []
    for k, (cy, cx) in enumerate(keys):
        x0, y0 = am.X0 + cx * am.INNER * am.GSD, am.Y0 - cy * am.INNER * am.GSD
        cb = box(x0, y0 - am.INNER * am.GSD, x0 + am.INNER * am.GSD, y0)
        if cb.intersects(ex):
            continue
        a17, a25 = am.chunk(2017, cy, cx), am.chunk(2025, cy, cx)
        if a17 is None or a25 is None:
            continue
        tr = rasterio.Affine(am.GSD, 0, x0, 0, -am.GSD, y0)
        hit = osm_d.iloc[osm_sidx.query(cb, predicate="intersects")]
        if len(hit):
            fine = rasterio.Affine(am.GSD / 4, 0, x0, 0, -am.GSD / 4, y0)
            r = rasterio.features.rasterize(((gm, 1) for gm in hit.geometry),
                                            out_shape=(am.INNER * 4, am.INNER * 4),
                                            transform=fine, fill=0, dtype="uint8")
            cov = r.reshape(am.INNER, 4, am.INNER, 4).mean(axis=(1, 3))
        else:
            cov = np.zeros((am.INNER, am.INNER))
        valid = (a17[0] != am.NODATA) & (a25[0] != am.NODATA)
        pos = valid & (cov >= POS_COVER)
        far = ndimage.distance_transform_edt(cov == 0) > NEG_DIST_PX
        negc = np.flatnonzero((valid & far).ravel())
        nn = NAT_NEG_PER_CHUNK if (cy, cx) in extra else NEG_PER_CHUNK
        neg = rng.choice(negc, size=min(nn, negc.size), replace=False) if negc.size else []
        for idx, yv in ((np.flatnonzero(pos.ravel()), 1), (np.asarray(neg, dtype=int), 0)):
            if len(idx) == 0:
                continue
            X17.append(a17.reshape(64, -1)[:, idx])
            X25.append(a25.reshape(64, -1)[:, idx])
            Y.append(np.full(len(idx), yv, dtype=np.int8))
        if (k + 1) % 500 == 0:
            log.info("  training chunks %d/%d", k + 1, len(keys))
    X17, X25, Y = np.hstack(X17), np.hstack(X25), np.concatenate(Y)
    p = np.flatnonzero(Y == 1)
    if p.size > MAX_POS:
        drop = rng.choice(p, size=p.size - MAX_POS, replace=False)
        keep = np.setdiff1d(np.arange(Y.size), drop)
        X17, X25, Y = X17[:, keep], X25[:, keep], Y[keep]
    log.info("training pixels: %d positive, %d negative", int(Y.sum()), int((Y == 0).sum()))
    return am.dequantize(X17), am.dequantize(X25), Y


# --------------------------------------------------------------------------------------
# Detection over an evaluation area
# --------------------------------------------------------------------------------------
def detect(models, geom) -> dict[str, gpd.GeoDataFrame]:
    minx, miny, maxx, maxy = geom.bounds
    r17, tr = am.window(2017, minx, miny, maxx, maxy)
    r25, _ = am.window(2025, minx, miny, maxx, maxy)
    h, w = r17.shape[1:]
    valid = ((r17[0] != am.NODATA) & (r25[0] != am.NODATA)).ravel()
    inside = rasterio.features.geometry_mask([geom], (h, w), tr, invert=True).ravel()
    ok = valid & inside
    e17 = am.dequantize(r17.reshape(64, -1)[:, ok])
    e25 = am.dequantize(r25.reshape(64, -1)[:, ok])
    px_area = _pixel_area_m2((miny + maxy) / 2)
    out = {}
    for v, m in models.items():
        p = np.zeros(h * w, dtype="float32")
        X = _features(e17, e25, v)
        for s in range(0, X.shape[0], 200_000):
            p[np.flatnonzero(ok)[s:s + 200_000]] = predict_proba(m, X[s:s + 200_000])
        p = p.reshape(h, w)
        for tau in TAUS:
            lab, n = ndimage.label(p >= tau, structure=np.ones((3, 3)))
            if n == 0:
                continue
            sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1)) * px_area
            keep = np.flatnonzero(sizes >= MIN_AREA) + 1
            if keep.size == 0:
                continue
            lab = np.where(np.isin(lab, keep), lab, 0).astype("int32")
            pmean = ndimage.mean(p, lab, index=keep)
            polys = {}
            for gj, val in rasterio.features.shapes(lab, mask=lab > 0, transform=tr):
                polys.setdefault(int(val), []).append(shape(gj))
            rows = [{"label": k_, "area_m2": float(sizes[k_ - 1]), "p_mean": float(pm),
                     "geometry": gpd.GeoSeries(polys[k_]).union_all()}
                    for k_, pm in zip(keep, pmean)]
            out[f"{v}@{tau}"] = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    return out


def _near(a: gpd.GeoDataFrame, b: gpd.GeoDataFrame) -> np.ndarray:
    """For each row of a: is any geometry of b within MATCH_M?"""
    if a.empty or b.empty:
        return np.zeros(len(a), bool)
    au, bu = a.to_crs(UTM), b.to_crs(UTM)
    hit = gpd.sjoin(gpd.GeoDataFrame(geometry=au.buffer(MATCH_M).to_numpy(), crs=UTM),
                    bu[["geometry"]], predicate="intersects").index.unique()
    return np.isin(np.arange(len(a)), hit)


def score(sets, dets, cands, osm_all, truth) -> pd.DataFrame:
    rows = []
    for setname in ("random", "rich", "quadrats"):
        S = sets[sets.set == setname]
        area_km2 = float(S.to_crs("EPSG:6933").area.sum() / 1e6)
        inside = lambda g: g[g.representative_point().within(S.union_all())]  # noqa: E731
        T = inside(truth)
        segs = inside(cands[cands.area_m2 >= MIN_AREA])
        instruments = {f"seg@conf{c}": segs[segs.confidence >= c] for c in SEG_CONF}
        for key in dets[setname]:
            instruments[f"aef_{key}"] = dets[setname][key]
        for name, D in instruments.items():
            mapped = _near(D, osm_all)
            found = _near(T, D) if len(T) else np.array([], bool)
            r = {"set": setname, "instrument": name, "n_det": len(D), "area_km2": area_km2,
                 "precision_lb": round(float(mapped.mean()), 3) if len(D) else None,
                 "unmapped_per_1000km2": round(float((~mapped).sum() / area_km2 * 1000), 1),
                 "n_truth": len(T), "recall": round(float(found.mean()), 3) if len(T) else None}
            for pl in ("ground", "rooftop"):
                m = (T.placement == pl).to_numpy()
                r[f"recall_{pl}"] = round(float(found[m].mean()), 3) if m.sum() else None
                r[f"n_truth_{pl}"] = int(m.sum())
            if name.startswith("aef_"):
                both = _near(T, segs) | found
                r["recall_union_seg"] = round(float(both.mean()), 3) if len(T) else None
                conf = _near(segs, D)
                r["seg_confirmed_n"] = int(conf.sum())
                r["seg_confirmed_precision_lb"] = (round(float(_near(segs[conf], osm_all).mean()), 3)
                                                   if conf.any() else None)
                r["seg_unconfirmed_precision_lb"] = (round(float(_near(segs[~conf], osm_all).mean()), 3)
                                                     if (~conf).any() else None)
            rows.append(r)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--national-negatives", action="store_true")
    args = ap.parse_args()
    global OUT
    if args.national_negatives:
        OUT = OUT.with_name(OUT.stem + "_natneg.json")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = np.random.default_rng(SEED)
    WORK.mkdir(parents=True, exist_ok=True)

    sets = eval_sets(rng)
    sets.to_parquet(WORK / "eval_sets.parquet")
    keys = sorted(set().union(*[set(am.chunks_for_bounds(*g.bounds)) for g in sets.geometry]))
    cached = sum((am.CACHE / "2017" / f"{a}_{b}.zst").exists() for a, b in keys)
    log.info("eval: %s; %d chunks per year, %d already cached (~%.1f GB to fetch)",
             sets.set.value_counts().to_dict(), len(keys), cached,
             2 * (len(keys) - cached) * 2.5 / 1000)
    if args.plan:
        return
    for y in (2025, 2017):
        log.info("fetching %d", y)
        prefetch([(y, *k) for k in keys], workers=args.workers)

    osm = gpd.read_parquet(OSM).to_crs(4326)
    osm = osm[osm.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    osm_d = dissolve_overlapping(osm).to_crs(4326)
    truth = osm_d[osm_d.area_m2 >= MIN_AREA].reset_index(drop=True)
    cands = gpd.read_parquet(CANDS).to_crs(4326)

    extra = []
    if args.national_negatives:
        extra = national_negative_keys(sets, np.random.default_rng(SEED + 7))
        log.info("national negatives: %d chunks from %d random cells", len(extra), NAT_CELLS)
        for y in (2025, 2017):
            prefetch([(y, *k) for k in extra], workers=args.workers)
    FOOTPRINT_KEYS[:] = _footprint_keys()
    X17, X25, Y = training_sample(truth, sets, rng, extra)
    models = {}
    for v in VARIANTS:
        models[v] = fit_logistic(_features(X17, X25, v).astype("float64"), Y.astype(float), L2)
        log.info("fitted %s (converged %s)", v, models[v]["converged"])

    dets = {}
    for setname, S in sets.groupby("set"):
        acc = {}
        for _, row in S.iterrows():
            for key, g in detect(models, row.geometry).items():
                acc.setdefault(key, []).append(g.assign(area_name=row["name"]))
            log.info("  detected %s %s", setname, row["name"])
        dets[setname] = {k: gpd.GeoDataFrame(pd.concat(v, ignore_index=True), crs=4326)
                         for k, v in acc.items()}
        tag = "_natneg" if args.national_negatives else ""
        for k, g in dets[setname].items():
            g.to_parquet(WORK / f"det{tag}_{setname}_{k.replace('@', '_')}.parquet")
    res = score(sets, dets, cands, osm, truth)
    res.to_csv(OUT.with_name(OUT.stem + ".csv"), index=False)
    OUT.write_text(json.dumps({"n_train_pos": int(Y.sum()), "n_train_neg": int((Y == 0).sum()),
                               "rows": res.to_dict(orient="records")}, indent=2, default=str))
    with pd.option_context("display.width", 250, "display.max_rows", 200):
        print(res.to_string(index=False))


if __name__ == "__main__":
    main()
