"""Per-building feature blocks for the 2026-10-22 "untapped opportunities" roofclf sweep.

Re-reads every production quadrat's composite window and derives, for the SAME rows the
production table (`data/roofclf/buildings.geoparquet`) carries and in the same order:

  aw_<band>     the shipped area-weighted zonal mean, recomputed here. Must reproduce the
                table's `<band>_mean` to float precision, or nothing else in this file is
                comparable to the shipped model.
  psf<s>_<band> the same mean with each footprint's pixel weights convolved by a Gaussian
                of sigma `s` pixels. A pixel records the scene through the sensor's point
                spread function, so a building's signal leaks into pixels it does not
                cover; the effective PSF (registration included) was measured at sigma
                0.65 px in docs/issues/glint-psf-matched-filter.md. The area weights the
                model ships are the box-PSF special case (sigma 0).
  dil<d>_<band> the area-weighted mean over the footprint buffered by `d` metres. VIDA
                outlines are imagery-derived and systematically undersized (117,141 m2 of
                mapped rooftop PV overhangs them across these quadrats).
  c1_<band>     the same area-weighted mean read from composite_1 (2021-10 to 2022-01,
                Pakistan's PRE-BOOM epoch), with the +1000 DN BOA offset it lacks added
                back (`transfer_calibration.PRE_BASELINE_DN_OFFSET`). composite_1 already
                exists for 4,467 of 4,473 Pakistani cells, so if a difference against it
                helps, the second epoch the register prices at ~2 TB of download is
                already on disk for this country.
  ctx_*         VIDA-only micro-context: building counts within 25/50/100 m, the distance
                to the nearest other building, the building's log area relative to its 20
                nearest neighbours, and the built-up share within 50 m. Computed against
                the full VIDA layer around the quadrat (100 m margin), so a building on
                the quadrat edge is not mistaken for an isolated one.

    pixi run python scripts/roofclf_untapped_extract.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.spatial import cKDTree

from earthpv.local_source import composite_index
from earthpv.preprocess import coverage_matrix
from earthpv.roofclf import (BAND_NAMES, COMPOSITE_FILL, REFL_SCALE, area_weighted_zonal_mean,
                             discover_quadrats, load_quadrat, quadrat_label, zonal_mean_max)
from earthpv.transfer_calibration import PRE_BASELINE_DN_OFFSET

log = logging.getLogger("untapped_extract")

EXCLUDE = "kalat_rural_calib_3km"
OUT = Path("/home/tobi/earthpv_data/roofclf_untapped")
PSF_SIGMAS = (0.4, 0.65, 1.0)
DILATIONS_M = (1.0, 2.0, 4.0)
CTX_MARGIN_M = 100.0


def gaussian_conv_matrix(h: int, w: int, sigma: float) -> sparse.csr_matrix:
    """(h*w, h*w) sparse matrix that applies a normalised, truncated Gaussian blur."""
    r = int(np.ceil(3 * sigma))
    ax = np.arange(-r, r + 1)
    k1 = np.exp(-0.5 * (ax / sigma) ** 2)
    k1 /= k1.sum()
    rows, cols, vals = [], [], []
    yy, xx = np.mgrid[0:h, 0:w]
    src = (yy * w + xx).ravel()
    for dy, ky in zip(ax, k1):
        for dx, kx in zip(ax, k1):
            ty, tx = yy + dy, xx + dx
            ok = ((ty >= 0) & (ty < h) & (tx >= 0) & (tx < w)).ravel()
            rows.append(src[ok])
            cols.append((ty * w + tx).ravel()[ok])
            vals.append(np.full(ok.sum(), ky * kx, dtype="float32"))
    return sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows),
                                                      np.concatenate(cols))), shape=(h * w,) * 2)


def weighted_means(A: sparse.spmatrix, arr: np.ndarray, fallback: np.ndarray,
                   valid: np.ndarray, total_ref: np.ndarray | None = None) -> np.ndarray:
    """Weighted mean per building with `area_weighted_zonal_mean`'s exact fallback rules:
    only buildings the pixel-centre pass already scored, and only when at least half their
    weight sits on valid imagery."""
    nb = arr.shape[0]
    flat = arr.reshape(nb, -1)
    Aok = A.multiply(valid[:, None]).tocsr()
    w = np.asarray(Aok.sum(axis=0)).ravel()
    total = np.asarray(A.sum(axis=0)).ravel() if total_ref is None else total_ref
    already = np.isfinite(fallback).all(axis=0)
    covered = (w > 1e-6) & (w >= 0.5 * np.maximum(total, 1e-9)) & already
    out = np.array(fallback, dtype="float64", copy=True)
    num = Aok.T.dot(np.nan_to_num(flat, nan=0.0).T)  # (buildings, bands)
    out[:, covered] = (num[covered] / w[covered, None]).T
    return out


def valid_mask(arr: np.ndarray) -> np.ndarray:
    flat = arr.reshape(arr.shape[0], -1)
    return np.isfinite(flat).all(axis=0) & ~np.all(flat == COMPOSITE_FILL, axis=0)


def context_features(bu: gpd.GeoDataFrame, vida: gpd.GeoDataFrame, crs) -> pd.DataFrame:
    """VIDA-only neighbourhood descriptors for each table building, against the full layer."""
    b = bu.to_crs(crs)
    v = vida.to_crs(crs)
    pb = np.column_stack([b.geometry.representative_point().x, b.geometry.representative_point().y])
    pv = np.column_stack([v.geometry.representative_point().x, v.geometry.representative_point().y])
    va = v["area_m2"].to_numpy(float)
    tree = cKDTree(pv)
    out = {}
    for r in (25, 50, 100):
        # minus one: the building itself is in the VIDA layer too
        out[f"ctx_n{r}"] = np.log1p(np.maximum(
            np.array([len(x) for x in tree.query_ball_point(pb, r)]) - 1, 0))
    d, j = tree.query(pb, k=21)
    # the nearest hit is the building itself (the table is a VIDA subset), so drop it
    if np.median(d[:, 0]) > 0.5:
        raise RuntimeError("table buildings are not in the VIDA layer they came from")
    out["ctx_nn_m"] = np.log1p(d[:, 1])
    nb_log = np.log10(np.clip(va[j[:, 1:]], 1.0, None))
    own = np.log10(np.clip(b["area_m2"].to_numpy(float), 1.0, None))
    out["ctx_rel_area"] = own - np.median(nb_log, axis=1)
    out["ctx_size_rank"] = (nb_log < own[:, None]).mean(axis=1)
    # built-up share of a 50 m disc: summed neighbour roof area (by centroid) / disc area
    built = np.array([va[x].sum() for x in tree.query_ball_point(pb, 50)])
    out["ctx_built50"] = built / (np.pi * 50 ** 2)
    return pd.DataFrame(out, index=bu.index)


def quadrat_block(stem: str, sub: gpd.GeoDataFrame, comp: Path, labels_dir: Path,
                  con) -> pd.DataFrame:
    from earthpv.buildings import fetch_vida_buildings

    boundary, _ = load_quadrat(stem, labels_dir)
    minx, miny, maxx, maxy = boundary.bounds
    res = composite_index(str(comp), layers=2).read_window((minx, miny, maxx, maxy))
    if res is None:
        raise RuntimeError(f"{stem}: no composite")
    raw, transform, crs = res
    cur = raw[:10].astype("float32") / REFL_SCALE
    old_raw = raw[10:20].astype("float32")
    fill_old = (old_raw == COMPOSITE_FILL).all(axis=0)
    old = np.where(fill_old[None], old_raw, old_raw + np.float32(PRE_BASELINE_DN_OFFSET))
    old = old / REFL_SCALE

    bu = sub[["geometry"]].copy()
    bu["area_m2"] = sub["roof_area_m2"].to_numpy()
    bu_utm = bu.to_crs(crs)
    h, w = cur.shape[-2:]
    cols: dict[str, np.ndarray] = {}

    fb0, _ = zonal_mean_max(bu_utm, cur, transform, nodata=COMPOSITE_FILL)
    aw0, _ = area_weighted_zonal_mean(bu_utm, cur, transform, fb0)
    for i, b in enumerate(BAND_NAMES):
        cols[f"aw_{b}"] = aw0[i]

    A = coverage_matrix(bu_utm, (h, w), transform)
    v0 = valid_mask(cur)
    for s in PSF_SIGMAS:
        W = (gaussian_conv_matrix(h, w, s) @ A).tocsr()
        m = weighted_means(W, cur, fb0, v0)
        for i, b in enumerate(BAND_NAMES):
            cols[f"psf{s:g}_{b}"] = m[i]
    for dm in DILATIONS_M:
        bd = bu_utm.copy()
        bd["geometry"] = bu_utm.buffer(dm, join_style=2)
        Ad = coverage_matrix(bd, (h, w), transform)
        m = weighted_means(Ad, cur, fb0, v0)
        for i, b in enumerate(BAND_NAMES):
            cols[f"dil{dm:g}_{b}"] = m[i]

    fb1, _ = zonal_mean_max(bu_utm, old, transform, nodata=COMPOSITE_FILL)
    aw1, _ = area_weighted_zonal_mean(bu_utm, old, transform, fb1)
    for i, b in enumerate(BAND_NAMES):
        cols[f"c1_{b}"] = aw1[i]
    cols["c1_fill_frac"] = np.full(len(sub), float(fill_old.mean()))
    # The documented +1000 DN offset is a median over 60 cells, and whether a cell's
    # composite_1 needs it depends on which collection its scenes came from. Record each
    # band's window-median shift (current minus old, over pixels valid in both) so the
    # harness can harmonise per window instead -- the per-cell version of the same fix,
    # and one a national scorer can apply cell by cell.
    both = v0 & valid_mask(old)
    for i, b in enumerate(BAND_NAMES):
        cols[f"c1_medshift_{b}"] = np.full(
            len(sub), float(np.median(cur[i].ravel()[both]) - np.median(old[i].ravel()[both])))

    out = pd.DataFrame(cols, index=sub.index)
    pad = CTX_MARGIN_M / 111_000.0
    vida = fetch_vida_buildings((minx - pad, miny - pad, maxx + pad, maxy + pad), "PAK", con=con)
    out = pd.concat([out, context_features(bu, vida, crs)], axis=1)

    tab = sub[[f"{b}_mean" for b in BAND_NAMES]].to_numpy()
    dif = np.nanmax(np.abs(tab - aw0.T))
    log.info("%-30s %5d bldgs  reproduce max|diff| %.2e  c1 fill %.3f  c1 NaN %d",
             stem, len(sub), dif, fill_old.mean(), int(np.isnan(aw1).any(axis=0).sum()))
    out.attrs["repro"] = float(dif)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--out", type=Path, default=OUT / "features.parquet")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv import overture

    con = overture.connect()
    t = gpd.read_parquet(args.table)
    parts, repro = [], {}
    for stem in sorted(discover_quadrats(args.labels_dir)):
        if stem == EXCLUDE:
            continue
        name = quadrat_label(stem)
        sub = t[t.quadrat == name]
        if sub.empty:
            log.warning("%s not in table", name)
            continue
        cache = args.out.parent / "per_quadrat" / f"{name}.parquet"
        if cache.exists():
            parts.append(pd.read_parquet(cache))
            continue
        blk = quadrat_block(stem, sub, args.composites, args.labels_dir, con)
        repro[name] = blk.attrs["repro"]
        cache.parent.mkdir(parents=True, exist_ok=True)
        blk.to_parquet(cache)
        parts.append(blk)
    f = pd.concat(parts).sort_index()
    if len(f) != len(t) or not (f.index == t.index).all():
        raise RuntimeError(f"row mismatch: {len(f)} feature rows against {len(t)} table rows")
    f.to_parquet(args.out)
    log.info("wrote %s (%d rows, %d cols); worst reproduction %.2e", args.out, len(f),
             f.shape[1], max(repro.values()) if repro else float("nan"))


if __name__ == "__main__":
    main()
