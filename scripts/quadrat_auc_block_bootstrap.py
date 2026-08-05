"""Paired spatial block bootstrap of per-quadrat pixel AUC between fraction checkpoints.

`validate_fraction_quadrats.py` reports one AUC per quadrat per run. On the held-out box of
the quadrat-supervision experiment the whole question is a difference of ~0.03 AUC over
~800 labelled pixels, and those pixels are not independent -- a 10 m raster over a rooftop
array gives many pixels of one installation, so a naive per-pixel resample would report a
confidence interval several times too narrow and turn any small difference "significant".

Blocks of `--block` pixels a side are resampled with replacement instead, which keeps
whole neighbourhoods together and lets the interval feel the real spatial redundancy. All
runs are scored on the SAME resampled pixel set each draw, so the difference is paired and
the interval is of the difference, not of two independent AUCs.

    python scripts/quadrat_auc_block_bootstrap.py \
        --quadrat karachi_coast_calib_700m --baseline v1 \
        v1=data/predictions_frac_pk_v2/pakistan/prob \
        quadho=data/predictions_quadho_quadcells/pakistan/prob \
        quad13=data/predictions_quad13_quadcells/pakistan/prob
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.mask import mask as rio_mask
from shapely.geometry import box

LABELS = Path("data/labels")


def newest_solar(stem: str) -> Path | None:
    c = sorted(LABELS.glob(f"{stem}_overpass_solar*.parquet"))
    dated = [p for p in c if p.name != f"{stem}_overpass_solar.parquet"]
    return (dated or c)[-1] if c else None


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Tie-corrected Mann-Whitney AUC. Identical to `validate_fraction_quadrats._auc`, so
    the point estimates here reproduce that script's numbers exactly."""
    pos, neg = int(labels.sum()), int(labels.size - labels.sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    s = scores[order]
    ranks = np.empty(s.size, dtype="float64")
    i = 0
    while i < s.size:
        j = i
        while j + 1 < s.size and s[j + 1] == s[i]:
            j += 1
        ranks[i : j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    r = np.empty_like(ranks)
    r[order] = ranks
    m = labels.astype(bool)
    return float((r[m].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def cell_paths(prob_dir: Path, poly) -> list[str]:
    hits = []
    for p in sorted(prob_dir.glob("*.tif")):
        with rasterio.open(p) as s:
            g = gpd.GeoSeries([box(*s.bounds)], crs=s.crs).to_crs(4326).iloc[0]
        if g.intersects(poly):
            hits.append(str(p))
    return hits


def read_pixels(path: str, bnd: gpd.GeoDataFrame, sol: gpd.GeoDataFrame, block: int):
    """(values, mapped-PV labels, block ids) for pixels inside the quadrat on one cell.

    Block ids come from the pixel's row/col in the masked window, so they are the same
    grid for every run reading the same cell -- which is what makes the resample paired.
    """
    with rasterio.open(path) as s:
        gs = bnd.to_crs(s.crs)
        try:
            arr, tr = rio_mask(s, list(gs.geometry), crop=True, filled=True, nodata=0)
        except ValueError:
            return None
        shape = arr.shape[1:]
        truth = rasterize(
            [(g, 1) for g in sol.to_crs(s.crs).geometry if not g.is_empty],
            out_shape=shape, transform=tr, fill=0, dtype="uint8", all_touched=True,
        )
        inside = rasterize(
            [(g, 1) for g in gs.geometry], out_shape=shape, transform=tr,
            fill=0, dtype="uint8",
        ).astype(bool)
    rr, cc = np.nonzero(inside)
    nblk_c = int(np.ceil(shape[1] / block))
    blk = (rr // block) * nblk_c + (cc // block)
    return arr[0][inside].astype("float64"), truth[inside].astype("uint8"), blk


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", metavar="LABEL=PROB_DIR")
    ap.add_argument("--quadrat", required=True)
    ap.add_argument("--baseline", required=True, help="label to difference against")
    ap.add_argument("--block", type=int, default=5, help="block side in pixels (5 = 50 m)")
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    runs = dict(spec.split("=", 1) for spec in args.runs)
    if args.baseline not in runs:
        raise SystemExit(f"--baseline {args.baseline} not among {list(runs)}")

    bnd = gpd.read_file(LABELS / f"{args.quadrat}_boundary.geojson").to_crs(4326)
    sp = newest_solar(args.quadrat)
    if sp is None:
        raise SystemExit(f"no mapped-solar pull for {args.quadrat}")
    sol = gpd.read_parquet(sp).to_crs(4326)
    sol = sol[sol.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]
    sol = gpd.clip(sol, bnd)
    poly = bnd.union_all()
    print(f"{args.quadrat}: {len(sol)} mapped installations, labels {sp.name}")

    # Cell rasters are keyed by basename so every run contributes the same cells in the
    # same order; a run missing a cell, or disagreeing on its pixel count, is fatal rather
    # than silently misaligned -- an unpaired difference is the one thing this cannot do.
    per_run: dict[str, list] = {}
    for label, d in runs.items():
        parts = {}
        for p in cell_paths(Path(d), poly):
            r = read_pixels(p, bnd, sol, args.block)
            if r is not None:
                parts[Path(p).name] = r
        per_run[label] = parts
        print(f"  {label}: {len(parts)} cells, {sum(v[0].size for v in parts.values()):,} px")

    names = sorted(set.intersection(*(set(v) for v in per_run.values())))
    if not names:
        raise SystemExit("no cell shared by all runs")
    dropped = {k: sorted(set(v) - set(names)) for k, v in per_run.items()}
    for k, v in dropped.items():
        if v:
            print(f"  NOTE {k} contributes cells no other run has, dropped: {v}")

    scores, labels, blocks = {k: [] for k in runs}, [], []
    off = 0
    for n in names:
        sizes = {k: per_run[k][n][0].size for k in runs}
        if len(set(sizes.values())) != 1:
            raise SystemExit(f"cell {n} pixel-count mismatch across runs: {sizes}")
        base_lab = per_run[args.baseline][n][1]
        base_blk = per_run[args.baseline][n][2]
        for k in runs:
            if not np.array_equal(per_run[k][n][1], base_lab):
                raise SystemExit(f"cell {n}: label mask differs for {k}")
            scores[k].append(per_run[k][n][0])
        labels.append(base_lab)
        blocks.append(base_blk + off)
        off += int(base_blk.max()) + 1

    sc = {k: np.concatenate(v) for k, v in scores.items()}
    lb = np.concatenate(labels)
    bk = np.concatenate(blocks)
    uniq = np.unique(bk)
    # Group pixel indices by block once; the draw loop then only concatenates.
    order = np.argsort(bk, kind="mergesort")
    bounds = np.searchsorted(bk[order], uniq)
    groups = np.split(order, bounds[1:])
    print(f"  pooled: {lb.size:,} px, {int(lb.sum()):,} labelled PV, {uniq.size} blocks "
          f"of {args.block}x{args.block}")

    point = {k: auc(sc[k], lb) for k in runs}
    rng = np.random.default_rng(args.seed)
    draws = {k: [] for k in runs}
    kept = 0
    for _ in range(args.draws):
        pick = rng.integers(0, len(groups), size=len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        y = lb[idx]
        if y.sum() == 0 or y.sum() == y.size:
            continue
        kept += 1
        for k in runs:
            draws[k].append(auc(sc[k][idx], y))

    rows = []
    b = np.asarray(draws[args.baseline])
    for k in runs:
        a = np.asarray(draws[k])
        d = a - b
        rows.append({
            "run": k, "auc": round(point[k], 4),
            "auc_lo95": round(float(np.percentile(a, 2.5)), 4),
            "auc_hi95": round(float(np.percentile(a, 97.5)), 4),
            "d_vs_base": round(point[k] - point[args.baseline], 4),
            "d_lo95": round(float(np.percentile(d, 2.5)), 4),
            "d_hi95": round(float(np.percentile(d, 97.5)), 4),
            # One-sided bootstrap p for "no better than baseline". The baseline row is
            # degenerate by construction (d == 0 every draw); read it as n/a.
            "p_one_sided": round(float((d <= 0).mean()), 4) if k != args.baseline else None,
        })
    df = pd.DataFrame(rows)
    print(f"\nblock bootstrap, {kept}/{args.draws} usable draws, baseline={args.baseline}")
    print(df.to_string(index=False))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.insert(0, "quadrat", args.quadrat)
        df.insert(1, "block_px", args.block)
        df.to_csv(args.out, index=False)
        print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
