"""Small-array recall and precision of segmentation checkpoints in Pakistan, down to 100 m2.

`compare_backbones.py` and `evaluate` drop every label below `chips.MIN_PV_AREA` (400 m2), so
they cannot say whether a checkpoint trained on smaller arrays finds them. This scores two
test sets that neither checkpoint was trained on, at many thresholds from one inference pass:

    holdout chips  v16's Pakistani val and buffer chips (Multan and Punjab holdouts and their
                   8-cell rings), one forward pass per 224 px chip exactly as `evaluate` does.
                   Only installations clear of every Pakistani TRAIN chip count, each once (in
                   the chip whose centre is nearest), and pixel precision counts only pixels
                   outside every train chip. The map is incomplete here, so unmapped PV counts
                   as a false positive and pixel precision is a floor.
    calibration    every registered calibration area but the corroborated Jhang f2, scored on
      areas        production rasters (`earthpv infer --tiles`, Hann overlap-add), against each
                   area's newest pull. Mapped to Rule-1 (every visible panel), so precision is
                   honest up to imagery epoch. `lower_floor_corpus.py` keeps their small
                   arrays ignore, so no checkpoint has trained on them.

Precision is pixel precision (a predicted pixel is true where any mapped polygon of any size
touches it) and object precision (a connected blob of predicted pixels is true when it
touches a mapped polygon dilated by one pixel). Recall is per installation, by placement and
size bin, hit when any predicted pixel touches it (as `evaluate`). Every checkpoint is also
read at the lowest threshold matching the baseline's pixel precision at --threshold, per test
set, with an exact McNemar test on the installations one finds and the other misses.

    pixi run python scripts/small_array_eval.py cells          # cells for `infer --tiles`
    .pixi/envs/ml/bin/python scripts/small_array_eval.py chip-infer --ckpt v16=<path>
    pixi run python scripts/small_array_eval.py score --name v24_vs_v16 \\
        --ckpt v16=<path> --ckpt v24=<path> \\
        --rasters v16=/home/tobi/earthpv_data/seg_v16_pakistan/pakistan/prob \\
        --rasters v24=<infer out>/pakistan/prob

The first --ckpt is the baseline. Writes results/small_array_eval/<name>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from math import comb
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features as rio_features
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CORPUS = REPO / "data/chips/combined_pakistan_v16/index.parquet"
PK_AOIS = ["pakistan_fresh", "punjab"]
NATIONAL = REPO / "data/labels/pakistan_overpass_solar.parquet"
LABELS_DIR = REPO / "data/labels"
CACHE = Path("/home/tobi/earthpv_data/small_array_eval")
REF_RASTERS = Path("/home/tobi/earthpv_data/seg_v16_pakistan/pakistan/prob")
EXCLUDE_AREAS = {"jhang_f2_farm_calib_3km"}  # corroborated on poor imagery, not Rule-1
THRESHOLDS = [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9]
SIZE_BINS = [(0, 100), (100, 200), (200, 300), (300, 400), (400, 1000), (1000, float("inf"))]
SUBSETS = {
    "rooftop_100_400": lambda w: (w.placement == "rooftop") & (w.area_m2 >= 100) & (w.area_m2 < 400),
    "rooftop_lt100": lambda w: (w.placement == "rooftop") & (w.area_m2 < 100),
    "ground_100_400": lambda w: (w.placement == "ground") & (w.area_m2 >= 100) & (w.area_m2 < 400),
    "rooftop_ge400": lambda w: (w.placement == "rooftop") & (w.area_m2 >= 400),
    "ground_ge400": lambda w: (w.placement == "ground") & (w.area_m2 >= 400),
}


def _bin(a: float) -> str:
    for lo, hi in SIZE_BINS:
        if lo <= a < hi:
            return f"{int(lo)}-{'inf' if hi == float('inf') else int(hi)}"
    return "unknown"


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def _polys(lab: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    lab = lab[lab.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    lab["placement"] = lab["placement"].where(lab["placement"].isin(["rooftop", "ground"]), "ground")
    return lab[["placement", "area_m2", "geometry"]].reset_index(drop=True)


def _chip_sets() -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """(test chips, Pakistani train-chip footprints) from v16's corpus, which v24 shares."""
    ix = pd.read_parquet(CORPUS)
    pk = ix[ix.aoi.isin(PK_AOIS)].drop_duplicates(["aoi", "chip_id"]).reset_index(drop=True)
    cache = CACHE / "chip_boxes.parquet"
    if cache.exists():
        boxes = gpd.read_parquet(cache)
    else:
        geoms = []
        for p in pk["image"]:
            with rasterio.open(REPO / p) as s:
                geoms.append(box(*transform_bounds(s.crs, "EPSG:4326", *s.bounds)))
        boxes = gpd.GeoDataFrame(pk[["aoi", "chip_id", "split"]], geometry=geoms, crs=4326)
        CACHE.mkdir(parents=True, exist_ok=True)
        boxes.to_parquet(cache)
    test = pk[pk.split.isin(["val", "buffer"])].reset_index(drop=True)
    return test, boxes[boxes.split == "train"].reset_index(drop=True)


def areas() -> gpd.GeoDataFrame:
    from earthpv import roofclf

    rows = []
    for stem in roofclf.discover_quadrats(LABELS_DIR):
        if stem in EXCLUDE_AREAS:
            continue
        rows.append(dict(stem=stem, geometry=roofclf.load_boundary(
            LABELS_DIR / f"{stem}_boundary.geojson")))
    return gpd.GeoDataFrame(rows, crs=4326)


def _cell_boxes(raster_dir: Path) -> gpd.GeoDataFrame:
    cache = CACHE / "cell_boxes.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)
    rows = []
    for t in sorted(raster_dir.glob("*.tif")):
        with rasterio.open(t) as s:
            rows.append(dict(cell=t.stem, geometry=box(*transform_bounds(
                s.crs, "EPSG:4326", *s.bounds))))
    out = gpd.GeoDataFrame(rows, crs=4326)
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache)
    return out


def cmd_cells(a) -> int:
    cells = _cell_boxes(REF_RASTERS)
    j = gpd.sjoin(cells, areas(), predicate="intersects")
    names = sorted(j.cell.unique())
    (CACHE / "area_cells.txt").write_text("\n".join(names) + "\n")
    print(f"{len(names)} cells for {j.stem.nunique()} areas -> {CACHE / 'area_cells.txt'}")
    print(",".join(names))
    return 0


def cmd_chip_infer(a) -> int:
    import torch

    from earthpv.infer import load_model

    test, _ = _chip_sets()
    for spec in a.ckpt:
        name, path = spec.split("=", 1)
        out = CACHE / "chips" / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "checkpoint.txt").write_text(path + "\n")
        todo = [r for _, r in test.iterrows() if not (out / f"{r.aoi}_{r.chip_id}.npy").exists()]
        if not todo:
            print(f"{name}: all {len(test)} chips cached")
            continue
        task, device, task_type = load_model(Path(path))
        for r in todo:
            with rasterio.open(REPO / r["image"]) as src:
                arr = src.read().astype("float32")
            x = torch.from_numpy(arr / 10000.0)[None].to(device)
            with torch.no_grad(), torch.autocast(device_type=device, enabled=device == "cuda"):
                o = task(x)
                logits = o.output if hasattr(o, "output") else o
                prob = torch.softmax(logits, 1)[0, 1].float().cpu().numpy()
            np.save(out / f"{r.aoi}_{r.chip_id}.npy", prob.astype("float16"))
        print(f"{name}: {len(todo)} chips inferred into {out}")
    return 0


def _rasterize(geoms, shape, transform) -> np.ndarray:
    geoms = [(g, 1) for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(shape, bool)
    return rio_features.rasterize(geoms, out_shape=shape, transform=transform, fill=0,
                                  all_touched=True, dtype="uint8").astype(bool)


def _score_px(prob: dict, truth: np.ndarray, valid: np.ndarray, near: np.ndarray, acc: dict):
    """Accumulate pixel and object counts per checkpoint x threshold."""
    for name, p in prob.items():
        for t in THRESHOLDS:
            pred = (p >= t) & valid
            k = (name, t)
            c = acc.setdefault(k, dict(px_pred=0, px_tp=0, obj=0, obj_tp=0, obj_small=0,
                                       obj_small_tp=0))
            c["px_pred"] += int(pred.sum())
            c["px_tp"] += int((pred & truth).sum())
            lab, n = ndimage.label(pred, structure=np.ones((3, 3)))
            if n:
                idx = np.arange(1, n + 1)
                hit = ndimage.maximum(near, lab, idx).astype(bool)
                size = ndimage.sum(np.ones_like(lab), lab, idx)
                small = size <= 4  # at most 400 m2 of 10 m pixels
                c["obj"] += n
                c["obj_tp"] += int(hit.sum())
                c["obj_small"] += int(small.sum())
                c["obj_small_tp"] += int((hit & small).sum())


def _hits(prob: dict, inst_mask: np.ndarray) -> dict:
    return {(name, t): bool((p[inst_mask] >= t).any()) for name, p in prob.items()
            for t in THRESHOLDS}


def score_chips(names: list[str]) -> tuple[pd.DataFrame, dict]:
    test, train = _chip_sets()
    lab = _polys(gpd.read_parquet(NATIONAL))
    tr_idx = train.sindex
    in_train = set(gpd.sjoin(lab, train, predicate="intersects").index)
    # Each clean installation is scored once, in the test chip whose centre is nearest.
    centres = gpd.GeoDataFrame(test[["aoi", "chip_id"]],
                               geometry=gpd.points_from_xy(test.lon, test.lat), crs=4326)
    clean = lab[~lab.index.isin(in_train)]
    cent = clean.copy()
    cent["geometry"] = clean.geometry.representative_point()
    owner = gpd.sjoin_nearest(cent.to_crs(32642), centres.to_crs(32642))
    owner = owner[~owner.index.duplicated()]
    owner_of = {(r.aoi, r.chip_id): [] for r in test.itertuples()}
    for i, r in owner.iterrows():
        owner_of[(r["aoi"], r["chip_id"])].append(i)
    lab_idx = lab.sindex
    rows, acc = [], {}
    for r in test.itertuples():
        prob = {n: np.load(CACHE / "chips" / n / f"{r.aoi}_{r.chip_id}.npy").astype("float32")
                for n in names}
        with rasterio.open(REPO / r.image) as src:
            transform, crs, shape = src.transform, src.crs, (src.height, src.width)
            geo = box(*transform_bounds(crs, "EPSG:4326", *src.bounds))
        here = lab.iloc[lab_idx.query(geo, predicate="intersects")]
        here_utm = here.to_crs(crs)
        truth = _rasterize(here_utm.geometry, shape, transform)
        near = ndimage.binary_dilation(truth, np.ones((3, 3)))
        trb = train.iloc[tr_idx.query(geo, predicate="intersects")]
        valid = ~_rasterize(trb.to_crs(crs).geometry, shape, transform)
        _score_px(prob, truth, valid, near, acc)
        mine = [i for i in owner_of[(r.aoi, r.chip_id)] if i in here.index]
        for i in mine:
            m = _rasterize([here_utm.loc[i, "geometry"]], shape, transform)
            if not m.any():
                continue
            rec = dict(set="holdout", where=f"{r.aoi}/{r.chip_id}", label_idx=int(i),
                       placement=lab.loc[i, "placement"], area_m2=float(lab.loc[i, "area_m2"]))
            for (n, t), h in _hits(prob, m).items():
                rows.append(dict(rec, ckpt=n, thr=t, detected=h))
    return pd.DataFrame(rows), acc


def score_areas(rasters: dict[str, Path]) -> tuple[pd.DataFrame, dict]:
    from earthpv import roofclf

    ar = areas()
    cells = _cell_boxes(REF_RASTERS)
    rows, acc = [], {}
    for a in ar.itertuples():
        lab = _polys(gpd.read_parquet(roofclf._newest_solar(a.stem, LABELS_DIR)))
        lab = lab[lab.geometry.representative_point().within(a.geometry)].reset_index(drop=True)
        hit_any: dict = {}
        for c in cells[cells.intersects(a.geometry)].cell:
            srcs = {n: rasterio.open(d / f"{c}.tif") for n, d in rasters.items()}
            ref = next(iter(srcs.values()))
            bb = transform_bounds("EPSG:4326", ref.crs, *a.geometry.bounds)
            win = from_bounds(*bb, transform=ref.transform).round_offsets().round_lengths()
            try:  # a cell's 4326 box is a little larger than its UTM raster
                win = win.intersection(rasterio.windows.Window(0, 0, ref.width, ref.height))
            except rasterio.errors.WindowError:
                for s in srcs.values():
                    s.close()
                continue
            transform, shape = ref.window_transform(win), (int(win.height), int(win.width))
            # uint8 rasters, prob * 255 truncated; read back as postprocess does
            prob = {n: s.read(1, window=win).astype("float32") / 255.0 for n, s in srcs.items()}
            for s in srcs.values():
                s.close()
            inside = _rasterize(gpd.GeoSeries([a.geometry], crs=4326).to_crs(ref.crs),
                                shape, transform)
            lab_utm = lab.to_crs(ref.crs)
            truth = _rasterize(lab_utm.geometry, shape, transform)
            near = ndimage.binary_dilation(truth, np.ones((3, 3)))
            _score_px(prob, truth, inside, near, acc)
            for i, g in lab_utm.geometry.items():
                m = _rasterize([g], shape, transform)
                if not m.any():
                    continue
                for k, h in _hits(prob, m).items():
                    hit_any[(i, k)] = hit_any.get((i, k), False) or h
        for (i, (n, t)), h in hit_any.items():
            rows.append(dict(set="areas", where=a.stem, label_idx=int(i),
                             placement=lab.loc[i, "placement"], area_m2=float(lab.loc[i, "area_m2"]),
                             ckpt=n, thr=t, detected=h))
    return pd.DataFrame(rows), acc


def _px_table(acc: dict, set_name: str) -> pd.DataFrame:
    rows = []
    for (n, t), c in acc.items():
        rows.append(dict(set=set_name, ckpt=n, thr=t, **c,
                         px_precision=c["px_tp"] / max(c["px_pred"], 1),
                         obj_precision=c["obj_tp"] / max(c["obj"], 1),
                         obj_small_precision=c["obj_small_tp"] / max(c["obj_small"], 1)))
    return pd.DataFrame(rows)


def cmd_score(a) -> int:
    names = [c.split("=", 1)[0] for c in a.ckpt]
    base = names[0]
    rasters = {k: Path(v) for k, v in (r.split("=", 1) for r in a.rasters)}
    out = REPO / "results" / "small_array_eval" / a.name
    out.mkdir(parents=True, exist_ok=True)
    inst_h, acc_h = score_chips(names)
    inst_a, acc_a = score_areas({n: rasters[n] for n in names})
    inst = pd.concat([inst_h, inst_a], ignore_index=True)
    inst["size_bin"] = inst.area_m2.map(_bin)
    px = pd.concat([_px_table(acc_h, "holdout"), _px_table(acc_a, "areas")], ignore_index=True)
    inst.to_csv(out / "installations.csv", index=False)
    px.to_csv(out / "pixels.csv", index=False)

    summary = dict(name=a.name, baseline=base, threshold=a.threshold,
                   checkpoints=dict(c.split("=", 1) for c in a.ckpt),
                   rasters={k: str(v) for k, v in rasters.items()}, sets={})
    for s in ["holdout", "areas"]:
        p = px[px.set == s]
        target = float(p[(p.ckpt == base) & (p.thr == a.threshold)].px_precision.iloc[0])
        ops = {base: a.threshold}
        for n in names[1:]:
            ok = p[(p.ckpt == n) & (p.px_precision >= target)].sort_values("thr")
            ops[n] = float(ok.thr.iloc[0]) if len(ok) else float(p[p.ckpt == n].thr.max())
        si = inst[inst.set == s]
        block = dict(precision_target=round(target, 4), operating_points={})
        for n, t in ops.items():
            pr = p[(p.ckpt == n) & (p.thr == t)].iloc[0]
            d = si[(si.ckpt == n) & (si.thr == t)]
            block["operating_points"][n] = dict(
                thr=t, px_precision=round(pr.px_precision, 4),
                obj_precision=round(pr.obj_precision, 4),
                obj_small_precision=round(pr.obj_small_precision, 4), objects=int(pr.obj),
                recall={k: dict(n=int(sel(d).sum()), recall=round(float(d[sel(d)].detected.mean()), 4)
                                if sel(d).any() else None) for k, sel in SUBSETS.items()})
        key = ["where", "label_idx"]
        bsel = si[(si.ckpt == base) & (si.thr == ops[base])].set_index(key)
        for n in names[1:]:
            for label, t in (("at_threshold", a.threshold), ("at_matched_precision", ops[n])):
                w = si[(si.ckpt == n) & (si.thr == t)].set_index(key)[
                    ["placement", "area_m2", "detected"]].join(
                    bsel[["detected"]].rename(columns={"detected": "base"}))
                tests = {}
                for k, sel in SUBSETS.items():
                    x = w[sel(w)]
                    b_, c_ = int((x.detected & ~x.base).sum()), int((~x.detected & x.base).sum())
                    tests[k] = dict(n=len(x), recall_new=round(float(x.detected.mean()), 4)
                                    if len(x) else None,
                                    recall_base=round(float(x.base.mean()), 4) if len(x) else None,
                                    only_new=b_, only_base=c_, p_mcnemar=round(mcnemar_exact(b_, c_), 4))
                block[f"{n}_vs_{base}_{label}"] = dict(thr=t, tests=tests)
        summary["sets"][s] = block
    (out / "summary.json").write_text(json.dumps(summary, indent=1))

    for s, block in summary["sets"].items():
        print(f"\n== {s}: baseline pixel precision {block['precision_target']} at {a.threshold}")
        for n, op in block["operating_points"].items():
            rc = " ".join(f"{k}={v['recall']}(n={v['n']})" for k, v in op["recall"].items())
            print(f"  {n:>10} thr={op['thr']:.2f} px_prec={op['px_precision']:.3f} "
                  f"obj_prec={op['obj_precision']:.3f} small_obj_prec={op['obj_small_precision']:.3f} "
                  f"objects={op['objects']}  {rc}")
        for k, v in block.items():
            if k.endswith(("_at_threshold", "_at_matched_precision")):
                for sub, tst in v["tests"].items():
                    print(f"  {k} thr={v['thr']:.2f} {sub:>16} n={tst['n']} new={tst['recall_new']} "
                          f"base={tst['recall_base']} +{tst['only_new']}/-{tst['only_base']} "
                          f"p={tst['p_mcnemar']}")
    print(f"\n-> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cells")
    ci = sub.add_parser("chip-infer")
    ci.add_argument("--ckpt", action="append", required=True, help="label=path")
    sc = sub.add_parser("score")
    sc.add_argument("--name", required=True)
    sc.add_argument("--ckpt", action="append", required=True, help="label=path; first is baseline")
    sc.add_argument("--rasters", action="append", required=True, help="label=prob dir")
    sc.add_argument("--threshold", type=float, default=0.3)
    a = ap.parse_args()
    return {"cells": cmd_cells, "chip-infer": cmd_chip_infer, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
