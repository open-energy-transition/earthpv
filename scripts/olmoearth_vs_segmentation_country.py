"""OlmoEarth v1.3 against segmentation in a second country (South Africa by default).

In Pakistan (`olmoearth_vs_segmentation.py`, 2026-10-25) a per-pixel logistic over the 64-d
OlmoEarth embedding, held to segmentation's false-alarm rate on random land, matched its
precision and nearly doubled its rooftop recall. One country and a precision resting on one
reviewer are the caveats. This repeats the test where segmentation is strongest (v14, a
decisive localisation win), OpenStreetMap is richest, and the evaluation can be drawn where
neither instrument trained.

Declared before measuring (2026-10-25):

  * Segmentation: the production candidates >= 400 m2 (`data/predictions/<aoi>/
    candidates.parquet`, v14 for South Africa), swept by `confidence` as in Pakistan.
  * Held out from both: the AOI's segmentation val holdout (`val_tiles`; South Africa's 250
    Western Cape cells), which v14 never trained on. The probe drops every training tile and
    national negative within 0.02 deg of a holdout cell or an evaluation area.
  * `random`: 20 cells drawn uniformly from the national density grid, for the false-alarm
    burden. `rich`: 20 holdout cells holding two or more mapped arrays >= 400 m2, for recall
    and precision, clean for both instruments. No quadrats: the country has no Rule-1 area,
    so there is no exhaustively mapped truth set.
  * Truth: the AOI's OSM pull (South Africa's of 2026-10-10, solar thermal dropped), polygons
    dissolved, arrays >= 400 m2. A detection is mapped when any OSM solar feature, nodes
    included, lies within 100 m, so precision is a lower bound for both.
  * Probe: Pakistan's recipe (positives >= 75% covered, negatives > 30 m from mapped PV, 150
    per tile plus 400 per tile from 60 random cells x 6 tiles, at most 150,000 positives, L2
    logistic, 8-connected components >= 400 m2), on the training tiles touching a candidate
    or mapped array >= 400 m2 outside the exclusion, a seeded sample of 2,500 if there are
    more (Pakistan used 2,487 around its AEF study population). Variants `change`, `level`
    and `both` of e2025 against e2023, 64-d only: 128-d never got under segmentation's burden
    in Pakistan, and 64-d halves the download.
  * Operating point by Pakistan's rule: `both` at the first tau whose random-cell burden is
    below segmentation's at confidence 0, over Pakistan's taus plus 0.998 and 0.999 in case
    0.995 is not strict enough here. Pakistan's own 0.995 is reported beside it.

Stated asymmetries, both favouring segmentation: it reads 2026-04 to 2026-09 composites while
OlmoEarth's newest year is 2025, so an array built in 2026 is visible to one instrument only;
and outside the holdout its training chips may overlap the random cells.

`--review` then draws a blind sample of unmapped detections for a human verdict: up to 24
OlmoEarth and 24 segmentation detections from each of the rich and random cells, shuffled and
rendered on Esri imagery under random codes, the key in a separate file. `--join` reads the
verdicts (`pv`, `no_pv`, `unsure`) back and turns them into reviewed precision and false
alarms per 1,000 km2.

    pixi run python scripts/olmoearth_vs_segmentation_country.py --plan
    pixi run python scripts/olmoearth_vs_segmentation_country.py
    pixi run python scripts/olmoearth_vs_segmentation_country.py --review
    pixi run python scripts/olmoearth_vs_segmentation_country.py --join [--verdicts <csv>]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aef_vs_segmentation as avs  # noqa: E402
import olmoearth_mosaic as om  # noqa: E402
import olmoearth_vs_segmentation as ovs  # noqa: E402
from aef_render_review_tiles import PANEL, render  # noqa: E402
from propose_calibration_candidates import esri_capture  # noqa: E402

from earthpv.config import Settings  # noqa: E402
from earthpv.labels import dissolve_overlapping  # noqa: E402
from earthpv.roofclf import L2, fit_logistic  # noqa: E402

log = logging.getLogger("olmo_country")

SEED = 20261026
N_RANDOM, N_RICH = 20, 20
MAX_TRAIN_TILES = 2500
DIMS = 64
TAUS = (*avs.TAUS, 0.998, 0.999)
PAKISTAN_TAU = 0.995
N_REVIEW = 24
KEY = "blind_key_DO_NOT_OPEN_BEFORE_VERDICTS.geojson"


def paths(aoi: str) -> dict[str, Path]:
    return {"grid": Path(f"data/predictions/{aoi}/density/grid.geoparquet"),
            "cands": Path(f"data/predictions/{aoi}/candidates.parquet"),
            "osm": Path(f"data/labels/{aoi}_overpass_solar.parquet"),
            "work": Path(f"/home/tobi/earthpv_data/olmoearth/vs_seg_{aoi}"),
            "out": Path(f"results/olmoearth_vs_segmentation_{aoi}"),
            "review": Path(f"results/olmoearth_vs_seg_review_{aoi}")}


def metric_crs(bbox) -> str:
    """The UTM zone at the AOI's centre: only 100 m buffers are drawn in it."""
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return f"EPSG:{(32700 if lat < 0 else 32600) + om.zone_of(lon)}"


def load_osm(path: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Every OSM solar feature (for "mapped"), and the dissolved arrays >= 400 m2 (truth)."""
    osm = gpd.read_parquet(path).to_crs(4326)
    poly = osm[osm.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    d = dissolve_overlapping(poly).to_crs(4326)
    return osm, d[d.area_m2 >= avs.MIN_AREA].reset_index(drop=True)


def eval_sets(grid, truth, holdout, rng) -> gpd.GeoDataFrame:
    j = gpd.sjoin(gpd.GeoDataFrame(geometry=truth.representative_point(), crs=4326),
                  grid[["geometry"]], predicate="within")
    grid = grid.assign(n_osm400=grid.index.map(j.groupby("index_right").size())
                       .fillna(0).astype(int))
    rand = grid.loc[rng.choice(grid.index.to_numpy(), N_RANDOM, replace=False)]
    pool = grid[grid.cell.isin(holdout) & (grid.n_osm400 >= 2) & ~grid.index.isin(rand.index)]
    log.info("rich pool: %d holdout cells with >= 2 mapped arrays >= 400 m2", len(pool))
    rich = pool.loc[rng.choice(pool.index.to_numpy(), N_RICH, replace=False)]
    rows = ([{"set": "random", "name": c, "geometry": g} for c, g in zip(rand.cell, rand.geometry)]
            + [{"set": "rich", "name": c, "geometry": g} for c, g in zip(rich.cell, rich.geometry)])
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)


def training_keys(objs, exclude, rng) -> list[tuple[int, int, int]]:
    """Tiles touching any object, minus those `training_sample` would skip anyway, so they
    are never downloaded; a seeded sample if there are more than MAX_TRAIN_TILES."""
    ex4326 = exclude.buffer(avs.BUFFER_DEG).union_all()
    exz, keep = {}, []
    for k in sorted(ovs._keys_for(objs)):
        z = k[0]
        if z not in exz:
            exz[z] = gpd.GeoSeries([ex4326.intersection(ovs._band(z).buffer(1))],
                                   crs=4326).to_crs(om.epsg(z)).iloc[0]
        if not ovs._tile_box(*k).intersects(exz[z]):
            keep.append(k)
    log.info("training tiles: %d outside the exclusion", len(keep))
    if len(keep) > MAX_TRAIN_TILES:
        keep = [keep[i] for i in sorted(rng.choice(len(keep), MAX_TRAIN_TILES, replace=False))]
    return keep


def run(aoi: str, p: dict, plan: bool, workers: int) -> None:
    cfg = Settings.load().aois[aoi]
    holdout = set(cfg.get("val_tiles", []))
    if not holdout:
        raise SystemExit(f"{aoi}: no val_tiles, so nothing is held out from segmentation")
    rng = np.random.default_rng(SEED)
    p["work"].mkdir(parents=True, exist_ok=True)

    osm, truth = load_osm(p["osm"])
    cands = gpd.read_parquet(p["cands"]).to_crs(4326)
    grid = gpd.read_parquet(p["grid"]).to_crs(4326)
    sets = eval_sets(grid, truth, holdout, rng)
    sets.to_parquet(p["work"] / "eval_sets.parquet")
    exclude = gpd.GeoDataFrame(geometry=pd.concat(
        [sets.geometry, grid[grid.cell.isin(holdout)].geometry], ignore_index=True), crs=4326)

    big = cands[cands.area_m2 >= avs.MIN_AREA]
    objs = gpd.GeoDataFrame(geometry=pd.concat([big.geometry, truth.geometry],
                                               ignore_index=True), crs=4326)
    eval_keys = ovs._keys_for(sets)
    foot_keys = training_keys(objs, exclude, rng)
    extra = ovs.national_negative_keys(exclude, np.random.default_rng(SEED + 7), grid=p["grid"])
    allk = sorted(eval_keys | set(foot_keys) | set(extra))
    todo = [(z, y, 0, cy, cx) for (z, cy, cx) in allk for y in (ovs.BASE_YEAR, ovs.YEAR)]
    cached = sum(om._chunk_path(*k).exists() for k in todo)
    log.info("truth: %d arrays >= 400 m2 (%s); %d candidates >= 400 m2; %d holdout cells",
             len(truth), truth.placement.value_counts().to_dict(), len(big), len(holdout))
    log.info("tiles: %d eval, %d training, %d national negatives; %d chunks at %d-d, %d cached "
             "(~%.0f GB to fetch at ~3.6 MB a chunk)", len(eval_keys), len(foot_keys),
             len(extra), len(todo), DIMS, cached, (len(todo) - cached) * 3.6 / 1000)
    if plan:
        return
    om.prefetch(todo, workers=workers)

    XB, X25, Y = ovs.training_sample(truth, exclude, rng, foot_keys, extra, dims=DIMS)
    models = {}
    for v in avs.VARIANTS:
        models[(DIMS, v)] = fit_logistic(ovs._features(XB, X25, v, DIMS).astype("float64"),
                                         Y.astype(float), L2)
        log.info("fitted %d-d %s (converged %s)", DIMS, v, models[(DIMS, v)]["converged"])
    del XB, X25

    dets = {}
    for setname, S in sets.groupby("set"):
        acc = {}
        for _, row in S.iterrows():
            for key, g in ovs.detect(models, row.geometry, dims=DIMS, taus=TAUS).items():
                acc.setdefault(key, []).append(g.assign(area_name=row["name"]))
            log.info("  detected %s %s", setname, row["name"])
        dets[setname] = {k: gpd.GeoDataFrame(pd.concat(v, ignore_index=True), crs=4326)
                         for k, v in acc.items()}
        for k, g in dets[setname].items():
            g.to_parquet(p["work"] / f"det_{setname}_{k.replace('@', '_')}.parquet")

    res = avs.score(sets, dets, cands, osm, truth)
    ops = ovs.operating_points(res, TAUS)
    un = ovs.unions(sets, dets, cands, truth, ops)
    p["out"].parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(p["out"].with_suffix(".csv"), index=False)
    un.to_csv(p["out"].with_name(p["out"].name + "_unions.csv"), index=False)
    p["out"].with_suffix(".json").write_text(json.dumps({
        "aoi": aoi, "base_year": ovs.BASE_YEAR, "year": ovs.YEAR, "dims": DIMS,
        "n_holdout_cells": len(holdout), "n_truth": len(truth),
        "n_train_tiles": len(foot_keys), "n_negative_tiles": len(extra),
        "n_train_pos": int(Y.sum()), "n_train_neg": int((Y == 0).sum()),
        "converged": {v: bool(m["converged"]) for (_, v), m in models.items()},
        "operating_points": ops, "pakistan_tau": f"olmo{DIMS}_both@{PAKISTAN_TAU}",
        "rows": res.to_dict(orient="records"), "unions": un.to_dict(orient="records")},
        indent=2, default=str))
    cols = ["set", "instrument", "n_det", "precision_lb", "unmapped_per_1000km2", "recall",
            "recall_ground", "recall_rooftop", "recall_union_seg"]
    show = ["seg@conf0.0", *ops.values(), f"olmo{DIMS}_both@{PAKISTAN_TAU}"]
    with pd.option_context("display.width", 250, "display.max_rows", 400):
        print("operating points:", ops)
        print(res[res.instrument.isin(show)][cols].to_string(index=False))
        print(un.to_string(index=False))


def _operating_point(p: dict) -> str:
    ops = json.loads(p["out"].with_suffix(".json").read_text())["operating_points"]
    if f"olmo{DIMS}" in ops:
        return ops[f"olmo{DIMS}"]
    log.warning("no tau met segmentation's burden; reviewing the strictest, %s", TAUS[-1])
    return f"olmo{DIMS}_both@{TAUS[-1]}"


def review(p: dict) -> None:
    sets = gpd.read_parquet(p["work"] / "eval_sets.parquet")
    osm = gpd.read_parquet(p["osm"]).to_crs(4326)
    cands = gpd.read_parquet(p["cands"]).to_crs(4326)
    cands = cands[cands.area_m2 >= avs.MIN_AREA]
    op = _operating_point(p)
    rng = np.random.default_rng(SEED)
    picks = []
    for setname in ("rich", "random"):
        area = sets[sets.set == setname].union_all()
        for inst in ("olmo", "seg"):
            d = (gpd.read_parquet(p["work"] / f"det_{setname}_{op.replace('@', '_')}.parquet")
                 if inst == "olmo" else cands)
            d = d[d.representative_point().within(area)].reset_index(drop=True)
            u = d[~avs._near(d, osm)]
            take = u.loc[rng.choice(u.index.to_numpy(), size=min(N_REVIEW, len(u)), replace=False)]
            picks.append(gpd.GeoDataFrame(
                {"set": setname, "instrument": op if inst == "olmo" else "seg@conf0.0",
                 "area_m2": take.area_m2.to_numpy()}, geometry=take.geometry.to_numpy(), crs=4326))
            log.info("%s %s: %d unmapped, %d drawn", setname, inst, len(u), len(take))
    k = gpd.GeoDataFrame(pd.concat(picks, ignore_index=True), crs=4326)
    k = k.sample(frac=1, random_state=SEED).reset_index(drop=True)
    k["code"] = [f"S{i:02d}" for i in range(len(k))]
    (p["review"] / "blind").mkdir(parents=True, exist_ok=True)
    imgs, dates = [], []
    for _, r in k.iterrows():
        pt = r.geometry.representative_point()
        cap = esri_capture(pt.x, pt.y)
        dates.append(cap["date"].isoformat() if cap else "unknown")
        imgs.append(render(r.geometry, r.code, dates[-1]))
    k["imagery_date"] = dates
    k.to_file(p["review"] / KEY, driver="GeoJSON")
    pd.DataFrame({"code": k.code, "imagery_date": dates, "verdict": "", "note": ""}).to_csv(
        p["review"] / "blind" / "verdicts.csv", index=False)
    for i in range(0, len(imgs), 6):
        sheet = Image.new("RGB", (PANEL * 3, PANEL * 2), (0, 0, 0))
        for j, im in enumerate(imgs[i:i + 6]):
            sheet.paste(im, ((j % 3) * PANEL, (j // 3) * PANEL))
        sheet.save(p["review"] / "blind" / f"sheet_{i // 6:02d}.png")
    log.info("%d panels in %d sheets", len(imgs), math.ceil(len(imgs) / 6))


def join(p: dict, verdicts: Path) -> None:
    """Reviewed share of the unmapped detections, carried to precision and false alarms."""
    key = gpd.read_file(p["review"] / KEY).drop(columns="geometry")
    v = pd.read_csv(verdicts, dtype=str).fillna("")
    j = key.merge(v[["code", "verdict", "note"]], on="code", how="left")
    bad = sorted(set(j.verdict.fillna("")) - {"pv", "no_pv", "unsure"})
    if bad:
        raise SystemExit(f"{verdicts}: verdicts must be pv, no_pv or unsure; found {bad}")
    j.to_csv(p["review"] / f"blind_review_joined_{verdicts.stem}.csv", index=False)
    res = pd.read_csv(p["out"].with_suffix(".csv")).set_index(["set", "instrument"])
    rows = []
    for (setname, inst), g in j.groupby(["set", "instrument"]):
        r = res.loc[(setname, inst)]
        n, pv, uns = len(g), int((g.verdict == "pv").sum()), int((g.verdict == "unsure").sum())
        lo, hi = pv / n, (pv + uns) / n
        mapped = float(r.precision_lb)
        rows.append({"set": setname, "instrument": inst, "n_reviewed": n, "pv": pv,
                     "unsure": uns, "no_pv": n - pv - uns, "precision_lb": mapped,
                     "precision_reviewed": [round(mapped + (1 - mapped) * lo, 3),
                                            round(mapped + (1 - mapped) * hi, 3)],
                     "unmapped_per_1000km2": float(r.unmapped_per_1000km2),
                     "false_alarms_per_1000km2": [round(r.unmapped_per_1000km2 * (1 - hi), 1),
                                                  round(r.unmapped_per_1000km2 * (1 - lo), 1)]})
    out = p["review"] / f"summary_{verdicts.stem}.json"
    out.write_text(json.dumps(rows, indent=2))
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="south_africa")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--join", action="store_true")
    ap.add_argument("--verdicts", type=Path)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = paths(args.aoi)
    avs.UTM = metric_crs(Settings.load().aois[args.aoi]["bbox"])  # read by avs._near
    if args.review:
        review(p)
    elif args.join:
        join(p, args.verdicts or p["review"] / "blind" / "verdicts.csv")
    else:
        run(args.aoi, p, args.plan, args.workers)


if __name__ == "__main__":
    main()
