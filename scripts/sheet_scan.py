"""Country-scale scan for large false sheets a candidate model draws and the reference does not.

On a bare Karoo ridge v14's epochs 41 and 49 both score every pixel 0.000 and their weight
average marks a 1.6 km2 sheet (2026-11-06). One event in 4,900 holdout chips gives no rate. A
candidate baseline runs over whole countries with no holdout to catch such a sheet, so this
measures how often it happens over a random sample of a country's cells, against a reference
whose probability rasters are already published (South Africa's are v14 epoch 41's own).

    sample   a seeded random sample of cells that have both a composite and a reference raster,
             written to data/sheet_scan/<aoi>/cells.txt (and a comma list for `infer --tiles`).
    compare  thresholds both rasters as postprocess does (uint8 / 255 >= threshold, 4-connected
             objects like rasterio.features.shapes) and counts, per size class, the candidate's
             objects that touch no reference object ("new") and the reference's that touch no
             candidate object ("lost"), and which of them touch mapped OSM solar. The classes are
             400-10,000 m2, 10,000-100,000 m2 and >= 100,000 m2 (above the merge cap: a sheet
             that would go to the solar farm review). Writes summary.json, new_objects.parquet
             (>= 10,000 m2, with centroids) and, with --quicklooks N, a PNG per largest unmapped
             new object: composite, reference, candidate, Esri World Imagery. --out-name keeps
             a second threshold's results apart from the first's.
    curve    per model and threshold, over the sampled cells: unmapped objects (>= 4 px,
             touching no OSM solar) per 1,000 km2, flagged area, the flagged share on mapped
             solar, and recall of mapped installations (rooftop 400-5,000 m2, ground >= 400 m2:
             any pixel >= threshold on the outline). --paired name@thr ... compares each
             with the first, per installation (McNemar). Matching thresholds on holdout chips
             can mislead at country scale (2026-11-06: v14's epoch average matched v14's chip
             precision at 0.97, where over whole South African cells it finds fewer arrays
             than v14 at 0.3; at 0.3 it finds more with fewer unmapped objects).
    blobs    the country's solar farm review as labels: for each outline above the merge cap
             a person judged (results/<aoi>_oversize_review/review.csv), whether each model
             still draws it at each threshold, and as an outline still above the cap. Needs
             the models' rasters over the cells holding the outlines, written to
             data/sheet_scan/<aoi>/blobs/cells.csv; it prints the infer command when missing.

Run the candidate over the sample first:

    pixi run python scripts/sheet_scan.py sample --aoi south_africa --n 1000
    .pixi/envs/ml/bin/python -m earthpv.cli infer --aoi south_africa --checkpoint <ckpt> \\
        --out-dir data/sheet_scan/south_africa/<name> --tiles "$(cat data/sheet_scan/south_africa/cells.csv)"
    pixi run python scripts/sheet_scan.py compare --aoi south_africa --name <name> \\
        --cand-threshold <its matched threshold>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SCAN = REPO / "data" / "sheet_scan"  # -> /home/tobi/earthpv_data/sheet_scan
CLASSES = [(400, 10_000, "400-10k m2"), (10_000, 100_000, "10k-100k m2"),
           (100_000, float("inf"), ">=100k m2")]
MIN_PX = 4  # 400 m2 at 10 m, the training floor


def _composite_cells(aoi: str) -> dict[str, Path]:
    return {p.parent.name: p for p in (REPO / "data" / "composites" / aoi / "composites")
            .glob("*/composite_0.tif")}


def cmd_sample(a) -> None:
    ref_dir = a.ref_dir or REPO / "data" / "predictions" / a.aoi / "prob"
    comp = _composite_cells(a.aoi)
    cells = sorted(set(comp) & {p.stem for p in Path(ref_dir).glob("*.tif")})
    rng = np.random.default_rng(a.seed)
    pick = sorted(rng.choice(cells, size=min(a.n, len(cells)), replace=False).tolist())
    d = SCAN / a.aoi
    d.mkdir(parents=True, exist_ok=True)
    (d / "cells.txt").write_text("\n".join(pick) + "\n")
    (d / "cells.csv").write_text(",".join(pick))
    (d / "sample.json").write_text(json.dumps(dict(
        aoi=a.aoi, n=len(pick), of=len(cells), seed=a.seed, ref_dir=str(ref_dir),
        drawn=time.strftime("%F %T")), indent=2))
    print(f"{len(pick)} of {len(cells)} cells -> {d / 'cells.txt'}")


def _objects(mask: np.ndarray):
    from scipy import ndimage

    lab, n = ndimage.label(mask)  # 4-connected, as rasterio.features.shapes
    size = np.bincount(lab.ravel(), minlength=n + 1)
    return lab, n, size


def _touching(lab: np.ndarray, n: int, other: np.ndarray) -> np.ndarray:
    return np.bincount(lab.ravel(), weights=other.ravel(), minlength=n + 1) > 0


def cmd_compare(a) -> None:
    import geopandas as gpd
    import rasterio
    import rasterio.warp
    from rasterio import features as rio_features
    from rasterio.warp import transform as warp_transform

    from earthpv.chips import _newest_overpass_path, _overpass_labels

    d = SCAN / a.aoi
    cells = (a.cells_file or d / "cells.txt").read_text().split()
    ref_dir = Path(a.ref_dir or REPO / "data" / "predictions" / a.aoi / "prob")
    cand_dir = d / a.name / a.aoi / "prob"
    labels_path = a.labels or _newest_overpass_path(a.aoi, REPO / "data" / "labels")
    osm = _overpass_labels(labels_path)
    osm = osm[osm.placement.isin(["rooftop", "ground"])]
    sindex = osm.sindex
    rows, new_rows, missing = [], [], []
    area_km2 = 0.0
    for cell in cells:
        rp, cp = ref_dir / f"{cell}.tif", cand_dir / f"{cell}.tif"
        if not cp.exists():
            missing.append(cell)
            continue
        with rasterio.open(rp) as r, rasterio.open(cp) as c:
            ref_p, cand_p = r.read(1), c.read(1)
            if ref_p.shape != cand_p.shape or r.transform != c.transform:
                raise SystemExit(f"{cell}: candidate raster is not on the reference grid")
            transform, crs, px_m2 = r.transform, r.crs, abs(r.transform.a * r.transform.e)
            bounds = rasterio.warp.transform_bounds(crs, "EPSG:4326", *r.bounds)
        area_km2 += ref_p.size * px_m2 / 1e6
        ref = ref_p.astype("float32") / 255.0 >= a.ref_threshold
        cand = cand_p.astype("float32") / 255.0 >= a.cand_threshold
        hits = osm.iloc[list(sindex.intersection(bounds))]
        mapped = np.zeros(ref.shape, bool)
        if len(hits):
            mapped = rio_features.rasterize(
                [(g, 1) for g in gpd.GeoSeries(hits.geometry, crs=osm.crs).to_crs(crs)],
                out_shape=ref.shape, transform=transform, all_touched=True).astype(bool)
        for who, own, other, prob in (("new", cand, ref, cand_p), ("lost", ref, cand, ref_p)):
            lab, n, size = _objects(own)
            if not n:
                continue
            k = np.arange(1, n + 1)
            alone = ~_touching(lab, n, other)[k]
            on_osm = _touching(lab, n, mapped)[k]
            big = size[k] >= MIN_PX
            for lo, hi, name in CLASSES:
                m = big & (size[k] * px_m2 >= lo) & (size[k] * px_m2 < hi)
                rows.append(dict(cell=cell, side=who, size_class=name, objects=int(m.sum()),
                                 alone=int((m & alone).sum()),
                                 alone_unmapped=int((m & alone & ~on_osm).sum())))
            if who == "new":
                for j in k[alone & big & (size[k] * px_m2 >= 10_000)]:
                    rr, cc = np.nonzero(lab == j)
                    x, y = transform * (cc.mean() + 0.5, rr.mean() + 0.5)
                    lon, lat = warp_transform(crs, "EPSG:4326", [x], [y])
                    new_rows.append(dict(
                        cell=cell, area_m2=float(size[j] * px_m2), lon=lon[0], lat=lat[0],
                        max_prob=float(prob[lab == j].max()) / 255.0,
                        ref_max_prob=float(ref_p[lab == j].max()) / 255.0,
                        on_osm=bool(on_osm[j - 1]), row0=int(rr.min()), row1=int(rr.max()),
                        col0=int(cc.min()), col1=int(cc.max())))
    df = pd.DataFrame(rows)
    out = d / (a.out_name or a.name)
    out.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(new_rows).sort_values("area_m2", ascending=False) if new_rows else \
        pd.DataFrame(columns=["cell", "area_m2", "lon", "lat", "max_prob", "on_osm"])
    new.to_parquet(out / "new_objects.parquet")
    per = 1000.0 / max(area_km2, 1e-9)
    summ = {"aoi": a.aoi, "name": a.name, "cells": len(cells) - len(missing),
            "missing_cells": missing, "area_km2": round(area_km2, 1),
            "ref_dir": str(ref_dir), "ref_threshold": a.ref_threshold,
            "cand_threshold": a.cand_threshold, "labels": str(labels_path),
            "classes": {}}
    lines = [f"{a.name} vs reference over {summ['cells']} {a.aoi} cells ({area_km2:,.0f} km2), "
             f"candidate >= {a.cand_threshold}, reference >= {a.ref_threshold}",
             f"{'class':12s} {'side':5s} {'objects':>8s} {'alone':>7s} {'unmapped':>9s}"
             f"  per 1,000 km2 (alone, unmapped)"]
    for _, _, name in CLASSES:
        summ["classes"][name] = {}
        for side in ("new", "lost"):
            g = df[(df.size_class == name) & (df.side == side)] if len(df) else df
            o, al, un = (int(g[c].sum()) if len(g) else 0
                         for c in ("objects", "alone", "alone_unmapped"))
            summ["classes"][name][side] = dict(objects=o, alone=al, alone_unmapped=un,
                                               alone_unmapped_per_1000km2=round(un * per, 3))
            lines.append(f"{name:12s} {side:5s} {o:8d} {al:7d} {un:9d}  {un * per:.2f}")
    (out / "summary.json").write_text(json.dumps(summ, indent=2))
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if missing:
        print(f"WARNING: {len(missing)} sampled cells have no candidate raster")
    if a.quicklooks:
        _quicklooks(a, new[~new.on_osm].head(a.quicklooks), ref_dir, cand_dir, out / "quicklooks")


def _quicklooks(a, objs: pd.DataFrame, ref_dir: Path, cand_dir: Path, qdir: Path) -> None:
    import urllib.request

    import io

    import matplotlib
    import rasterio
    import rasterio.warp
    import rasterio.windows
    from rasterio.windows import Window

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    comp = _composite_cells(a.aoi)
    qdir.mkdir(parents=True, exist_ok=True)
    for i, o in enumerate(objs.itertuples(index=False)):
        pad = 30
        r0, c0 = max(o.row0 - pad, 0), max(o.col0 - pad, 0)
        win = Window(c0, r0, o.col1 - o.col0 + 2 * pad, o.row1 - o.row0 + 2 * pad)
        with rasterio.open(comp[o.cell]) as s:
            rgb = s.read([3, 2, 1], window=win, boundless=True).astype("float32")
            bounds = rasterio.warp.transform_bounds(s.crs, "EPSG:4326",
                                                    *rasterio.windows.bounds(win, s.transform))
        with rasterio.open(ref_dir / f"{o.cell}.tif") as s:
            rp = s.read(1, window=win, boundless=True) / 255.0
        with rasterio.open(cand_dir / f"{o.cell}.tif") as s:
            cp = s.read(1, window=win, boundless=True) / 255.0
        panels = [("Sentinel-2 composite", np.clip(np.moveaxis(rgb, 0, -1) / 3000.0, 0, 1)),
                  (f"reference (>= {a.ref_threshold})", rp), (f"{a.name} (>= {a.cand_threshold})", cp)]
        try:
            url = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/"
                   f"MapServer/export?bbox={bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
                   "&bboxSR=4326&imageSR=4326&size=600,600&format=jpg&f=image")
            req = urllib.request.Request(url, headers={"User-Agent": "earthpv-sheet-scan"})
            panels.append(("Esri World Imagery",
                           plt.imread(io.BytesIO(urllib.request.urlopen(req, timeout=60).read()),
                                      format="jpg")))
        except Exception as e:  # imagery is a convenience, never a reason to fail the scan
            print(f"quicklook {i}: no Esri image ({e})")
        fig, ax = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 4.4))
        for axi, (t, img) in zip(ax, panels):
            axi.imshow(img, vmin=0, vmax=1)
            axi.set_title(t, fontsize=9)
            axi.axis("off")
        fig.suptitle(f"{o.cell}  {o.area_m2 / 1e6:.3f} km2  lon {o.lon:.4f} lat {o.lat:.4f}  "
                     f"max p {o.max_prob:.2f} (reference {o.ref_max_prob:.2f})", fontsize=9)
        plt.tight_layout()
        plt.savefig(qdir / f"{i:02d}_{o.cell}_{o.lon:.4f}_{o.lat:.4f}.png", dpi=80)
        plt.close(fig)
    print(f"{len(objs)} quicklooks -> {qdir}")


CURVE_GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.96, 0.97, 0.98,
              0.99]
ROOF_BAND = (400.0, 5_000.0)


def _model_dirs(aoi: str, specs: list[str]) -> dict[str, Path]:
    """`name` -> data/sheet_scan/<aoi>/<name>/<aoi>/prob (where `infer --out-dir` writes);
    `name=<dir>` -> that directory (e.g. a published data/predictions/<aoi>/prob)."""
    out = {}
    for s in specs:
        name, _, path = s.partition("=")
        out[name] = Path(path) if path else SCAN / aoi / name / aoi / "prob"
    return out


def cmd_curve(a) -> None:
    import rasterio
    import rasterio.warp
    from rasterio import features as rio_features

    from compare_backbones import mcnemar_exact
    from earthpv.chips import _newest_overpass_path, _overpass_labels
    from earthpv.labels import geodesic_area_m2

    d = SCAN / a.aoi
    cells = (a.cells_file or d / "cells.txt").read_text().split()
    models = _model_dirs(a.aoi, a.model)
    for name, p in models.items():
        lack = [c for c in cells if not (p / f"{c}.tif").exists()]
        if lack:
            raise SystemExit(f"{name}: {len(lack)} of {len(cells)} cells have no raster in {p}")
    labels_path = a.labels or _newest_overpass_path(a.aoi, REPO / "data" / "labels")
    osm = _overpass_labels(labels_path).reset_index(drop=True)
    osm["area_m2"] = [geodesic_area_m2(g) for g in osm.geometry]
    sindex = osm.sindex
    first = next(iter(models))
    maxp = {m: np.full(len(osm), -1, np.int16) for m in models}  # uint8 max; -1 = not imaged
    nt = len(CURVE_GRID)
    fa = {m: np.zeros(nt, np.int64) for m in models}
    flagged = {m: np.zeros(nt, np.int64) for m in models}
    on_known = {m: np.zeros(nt, np.int64) for m in models}
    thr8 = np.array(CURVE_GRID, np.float32)
    area_km2 = 0.0
    for i, cell in enumerate(cells):
        with rasterio.open(models[first] / f"{cell}.tif") as r:
            tr, crs, shape, px_m2 = r.transform, r.crs, r.shape, abs(r.transform.a * r.transform.e)
            bounds = rasterio.warp.transform_bounds(crs, "EPSG:4326", *r.bounds)
        area_km2 += shape[0] * shape[1] * px_m2 / 1e6
        hits = osm.iloc[list(sindex.intersection(bounds))]
        known = np.zeros(shape, bool)
        outlines = []
        if len(hits):
            geoms = hits.geometry.to_crs(crs)
            known = rio_features.rasterize([(g, 1) for g in geoms], out_shape=shape, transform=tr,
                                           all_touched=True).astype(bool)
            for idx, g in zip(hits.index, geoms):
                o = rio_features.rasterize([(g, 1)], out_shape=shape, transform=tr,
                                           all_touched=True).astype(bool)
                if o.any():
                    outlines.append((idx, o))
        for m, p in models.items():
            with rasterio.open(p / f"{cell}.tif") as r:
                prob = r.read(1)
            if prob.shape != shape:
                raise SystemExit(f"{m} {cell}: not on {first}'s grid")
            for idx, o in outlines:
                maxp[m][idx] = max(maxp[m][idx], int(prob[o].max()))
            pf = prob.astype(np.float32) / 255.0
            for j, t in enumerate(thr8):
                on = pf >= t
                flagged[m][j] += int(on.sum())
                on_known[m][j] += int((on & known).sum())
                lab, n, size = _objects(on)
                if n:
                    touch = _touching(lab, n, known)
                    fa[m][j] += int(((size >= MIN_PX) & ~touch)[1:].sum())
        if i % 100 == 0:
            print(f"{i}/{len(cells)} {cell}", flush=True)
    inst = osm[["placement", "area_m2"]].copy()
    for m in models:
        inst[f"p_{m}"] = np.where(maxp[m] >= 0, maxp[m] / 255.0, np.nan)
    inst = inst.dropna(subset=[f"p_{m}" for m in models])
    groups = {"rooftop_400_5000": (inst.placement == "rooftop") & inst.area_m2.between(*ROOF_BAND),
              "ground_ge400": (inst.placement == "ground") & (inst.area_m2 >= 400)}
    rows = []
    for m in models:
        for j, t in enumerate(CURVE_GRID):
            r = dict(model=m, thr=t, unmapped_objects_per_1000km2=round(fa[m][j] / area_km2 * 1e3, 2),
                     flagged_km2=round(flagged[m][j] * px_m2 / 1e6, 2),
                     flagged_on_mapped=round(on_known[m][j] / max(flagged[m][j], 1), 4))
            for g, msk in groups.items():
                r[g] = round(float((inst.loc[msk, f"p_{m}"] >= t).mean()), 4)
            rows.append(r)
    cur = pd.DataFrame(rows)
    tag = "_".join(models)
    cur.to_csv(d / f"curve_{tag}.csv", index=False)
    inst.to_parquet(d / f"curve_{tag}_installations.parquet")
    lines = [f"{len(cells)} {a.aoi} cells ({area_km2:,.0f} km2); mapped installations "
             + ", ".join(f"{g} n={int(msk.sum())}" for g, msk in groups.items()),
             cur.to_string(index=False)]
    if len(a.paired) > 1:
        def hit(spec):
            m, _, t = spec.partition("@")
            return inst[f"p_{m}"] >= float(t)
        base = hit(a.paired[0])
        for spec in a.paired[1:]:
            h = hit(spec)
            for g, msk in groups.items():
                gain, loss = int((h & ~base)[msk].sum()), int((~h & base)[msk].sum())
                lines.append(f"{spec} vs {a.paired[0]} {g}: {h[msk].mean():.3f} vs "
                             f"{base[msk].mean():.3f} (+{gain}/-{loss}, p={mcnemar_exact(gain, loss):.2g})")
    (d / f"curve_{tag}.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def cmd_blobs(a) -> None:
    import geopandas as gpd
    import rasterio
    import rasterio.warp
    from rasterio import features as rio_features
    from shapely.geometry import box

    from earthpv.postprocess import MAX_CANDIDATE_M2

    d = SCAN / a.aoi / "blobs"
    d.mkdir(parents=True, exist_ok=True)
    review = pd.read_csv(a.review or REPO / "results" / f"{a.aoi}_oversize_review" / "review.csv")
    review = review[review.verdict.isin(["pv", "not_pv"])]
    cand = gpd.read_parquet(a.candidates or REPO / "data" / "predictions" / a.aoi / "candidates.parquet")
    out = gpd.GeoDataFrame(
        review[["candidate_index", "code", "verdict", "area_m2"]].reset_index(drop=True),
        geometry=cand.loc[review.candidate_index].geometry.to_numpy(), crs=cand.crs).to_crs(4326)
    ref_dir = Path(a.ref_dir or REPO / "data" / "predictions" / a.aoi / "prob")
    grid = []
    for p in sorted(ref_dir.glob("*.tif")):
        with rasterio.open(p) as r:
            grid.append(dict(cell=p.stem, geometry=box(*rasterio.warp.transform_bounds(
                r.crs, "EPSG:4326", *r.bounds))))
    pairs = gpd.sjoin(out, gpd.GeoDataFrame(grid, crs=4326), predicate="intersects")
    cells = sorted(pairs.cell.unique())
    (d / "cells.csv").write_text(",".join(cells))
    print(f"{len(out)} judged outlines ({out.verdict.value_counts().to_dict()}) in {len(cells)} "
          f"cells -> {d / 'cells.csv'}")
    rows, summary = [], []
    for name, p in _model_dirs(a.aoi, a.model).items():
        lack = [c for c in cells if not (p / f"{c}.tif").exists()]
        if lack:
            print(f"{name}: {len(lack)} cells missing; run\n  .pixi/envs/ml/bin/python -m earthpv.cli "
                  f"infer --aoi {a.aoi} --checkpoint <ckpt> --out-dir {SCAN / a.aoi / name} "
                  f"--tiles \"$(cat {d / 'cells.csv'})\"")
            continue
        acc = {(i, t): [0, 0, 0.0] for i in out.index for t in a.threshold}  # px, hit, largest
        for cell, g in pairs.groupby("cell"):
            with rasterio.open(p / f"{cell}.tif") as r:
                prob = r.read(1).astype(np.float32) / 255.0
                tr, crs, px_m2 = r.transform, r.crs, abs(r.transform.a * r.transform.e)
            masks = {i: rio_features.rasterize([(geom, 1)], out_shape=prob.shape, transform=tr)
                     .astype(bool) for i, geom in zip(g.index, g.to_crs(crs).geometry)}
            for t in a.threshold:
                lab, n, size = _objects(prob >= t)
                for i, o in masks.items():
                    k = acc[(i, t)]
                    k[0] += int(o.sum())
                    ids = lab[o & (lab > 0)]
                    k[1] += int(ids.size)
                    if ids.size:
                        k[2] = max(k[2], float(size[np.unique(ids)].max() * px_m2))
        for (i, t), (npx, hit, largest) in acc.items():
            rows.append(dict(model=name, thr=t, code=out.code[i], verdict=out.verdict[i],
                             area_m2=out.area_m2[i], covered=hit / max(npx, 1),
                             drawn=hit > 0, above_cap=largest >= MAX_CANDIDATE_M2,
                             largest_object_m2=largest))
    if not rows:
        return
    res = pd.DataFrame(rows)
    res.to_csv(d / ("verdicts_" + "_".join(res.model.unique()) + ".csv"), index=False)
    s = res.groupby(["model", "thr", "verdict"]).agg(
        outlines=("drawn", "size"), drawn=("drawn", "sum"), above_cap=("above_cap", "sum"),
        mean_covered=("covered", "mean")).round(3)
    print(s.to_string())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--aoi", default="south_africa")
    s.add_argument("--n", type=int, default=1000)
    s.add_argument("--seed", type=int, default=20261106)
    s.add_argument("--ref-dir", type=Path)
    c = sub.add_parser("compare")
    c.add_argument("--aoi", default="south_africa")
    c.add_argument("--name", required=True, help="the candidate's run name under data/sheet_scan/<aoi>/")
    c.add_argument("--cand-threshold", type=float, required=True)
    c.add_argument("--ref-dir", type=Path)
    c.add_argument("--ref-threshold", type=float, default=0.3)
    c.add_argument("--labels", type=Path)
    c.add_argument("--quicklooks", type=int, default=20)
    c.add_argument("--cells-file", type=Path, help="default data/sheet_scan/<aoi>/cells.txt")
    c.add_argument("--out-name", help="output directory name (default --name)")
    m = "a run name under data/sheet_scan/<aoi>/ or name=<probability raster dir>"
    k = sub.add_parser("curve")
    k.add_argument("--aoi", default="south_africa")
    k.add_argument("--model", action="append", required=True, help=m + "; repeat")
    k.add_argument("--paired", nargs="+", default=[], help="name@thr ...; the first is the base")
    k.add_argument("--labels", type=Path)
    k.add_argument("--cells-file", type=Path, help="default data/sheet_scan/<aoi>/cells.txt")
    b = sub.add_parser("blobs")
    b.add_argument("--aoi", default="south_africa")
    b.add_argument("--model", action="append", default=[], help=m + "; repeat")
    b.add_argument("--threshold", type=float, nargs="+", default=[0.3])
    b.add_argument("--review", type=Path, help="default results/<aoi>_oversize_review/review.csv")
    b.add_argument("--candidates", type=Path,
                   help="the run the review judged (default data/predictions/<aoi>/candidates.parquet)")
    b.add_argument("--ref-dir", type=Path, help="that run's rasters, for the cell grid")
    a = ap.parse_args()
    {"sample": cmd_sample, "compare": cmd_compare, "curve": cmd_curve,
     "blobs": cmd_blobs}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
