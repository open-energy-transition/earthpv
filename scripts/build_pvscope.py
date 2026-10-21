"""PVscope: one calibration area's Sentinel-2 pixels and its mapped PV as an interactive 3D
cube, space on two axes and the ten bands on the third, and the same pixels again in
spectral space.

Why this page exists: most rooftop PV mapped in Pakistan's calibration areas is smaller
than one 10 m pixel, and six of the ten bands are native 20 m, four times the area. The
page shows what that does to the signal in two halves that a 2D figure keeps apart:

- **Spatial**: how much of one pixel a single array can cover at best (`best_fill`), from
  the mapped polygons rasterised at 1 m on the composite's own grid.
- **Spectral**: how far that cover moves the pixel away from the roofs around it, against
  how much PV-free roofs already differ from one another.

Measured per band on the area's own pixels:

- `delta`: contrast at full cover, a through-origin fit of (pixel - local roof background)
  on PV cover. Local background is the median of PV-free roof pixels (VIDA roof cover at
  least half, not touching mapped PV) within 50 m for 10 m bands and 60 m for 20 m bands.
- `sigma`: robust spread (1.4826 x MAD) of that contrast over PV-free roof pixels. It is
  roof-to-roof clutter, not sensor noise, and it is what any detector has to beat.
- `fstar = 2 sigma / |delta|`: the pixel cover PV needs before it moves the pixel 2 sigma.
  Times the pixel area, the smallest array that can do it when it sits inside one pixel.
- a matched filter combining the four native-10 m bands at 10 m and all ten bands on the
  20 m grid, with the same 2 sigma rule.

Every figure is in-sample for one area: it describes this area's roofs, not Pakistan's.
The composites hold the 20 m bands nearest-neighbour replicated into 2x2 blocks aligned to
even pixel indices (checked below, not assumed), which is why the window starts on one.

    .pixi/envs/default/bin/python scripts/build_pvscope.py
    .pixi/envs/default/bin/python scripts/build_pvscope.py \\
        --quadrat peshawar_west_calib_4p39km2 --composite <path/to/composite_0.tif>

Writes `results/pakistan_pvscope.html`, one self-contained page (three.js r128 from
cdnjs/jsDelivr, everything else inline). `pixi run docs-figures` copies it to
`docs/assets/interactive/pvscope.html`, which `docs/methods/pvscope.md` embeds.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from rasterio import features
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from scipy import ndimage
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from earthpv.buildings import fetch_vida_buildings  # noqa: E402

LABELS = ROOT / "data/labels"
COMPOSITES = ROOT / "data/composites/pakistan/composites"
OUT = ROOT / "results/pakistan_pvscope.html"
TEMPLATE_PATH = ROOT / "src/earthpv/templates/pvscope.html"
DEFAULT_QUADRAT = "peshawar_west_calib_4p39km2"

# Sentinel-2A central wavelengths (nm) of the ten bands the composites carry.
BAND_NM = {"B02": 492, "B03": 560, "B04": 665, "B05": 704, "B06": 740, "B07": 783,
           "B08": 833, "B8A": 865, "B11": 1614, "B12": 2202}
NATIVE_20M = {"B05", "B06", "B07", "B8A", "B11", "B12"}
BOA_OFFSET = 1000      # processing baseline 04.00 DN carry +1000
SUPERSAMPLE = 10       # polygons rasterised at 1 m, then averaged up to 10 m / 20 m
WIN = 64               # side of the 3D window, in 10 m pixels
SIZE_BINS = [10, 25, 50, 100, 200, 400, 800, 1600, 3200, 25600]
NODATA = -32768        # contrast sentinel in the embedded integer arrays


def find_composite(boundary: gpd.GeoDataFrame) -> Path:
    w, s, e, n = boundary.to_crs(4326).total_bounds
    for tif in sorted(glob.glob(str(COMPOSITES / "*/composite_0.tif"))):
        with rasterio.open(tif) as src:
            bw, bs, be, bn = transform_bounds(src.crs, 4326, *src.bounds)
        if bw <= w and be >= e and bs <= s and bn >= n:
            return Path(tif)
    raise SystemExit("no single composite cell covers the quadrat; pass --composite")


def block_mean(a: np.ndarray, k: int) -> np.ndarray:
    h, w = a.shape
    return a.reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def local_contrast(stack, cover, roof, inside, radius):
    """Pixel minus the median of nearby PV-free roof pixels, per band.

    Inside and next to a large array there may be no PV-free roof within `radius`; the
    neighbourhood then doubles, twice, before a pixel is left without a background."""
    bg_mask = (cover == 0) & (roof >= 0.5) & ~ndimage.binary_dilation(cover > 0, iterations=1)
    out = np.empty_like(stack)
    for i in range(stack.shape[0]):
        vals = np.where(bg_mask, stack[i], np.nan)
        bg = np.full(vals.shape, np.nan, dtype=np.float32)
        for r in (radius, 2 * radius, 4 * radius):
            todo = np.isnan(bg)
            if not todo.any():
                break
            wider = ndimage.generic_filter(vals, np.nanmedian, size=2 * r + 1,
                                           mode="constant", cval=np.nan)
            bg[todo] = wider[todo]
        out[i] = stack[i] - bg
    return out, bg_mask & (inside > 0.5)


def fit_delta(c, cover, inside):
    """Contrast at full cover: through-origin least squares of contrast on cover."""
    sel = (cover > 0) & (inside > 0.5) & np.isfinite(c)
    return float(np.sum(cover[sel] * c[sel]) / np.sum(cover[sel] ** 2)), int(sel.sum())


def robust_sigma(x):
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def matched_filter(c, cover, bg_sel, inside):
    """Combine bands into one score in units of roof clutter sigma.

    delta from the same through-origin fit, band by band; clutter covariance from PV-free
    roof pixels with the 2% most extreme dropped, so a few odd roofs do not set it."""
    ok = np.all(np.isfinite(c), axis=0)
    sel = (cover > 0) & (inside > 0.5) & ok
    delta = (c[:, sel] * cover[sel]).sum(1) / (cover[sel] ** 2).sum()
    bgv = c[:, bg_sel & ok]
    dist = np.linalg.norm(bgv - np.median(bgv, 1, keepdims=True), axis=0)
    cov = np.cov(bgv[:, dist < np.quantile(dist, 0.98)])
    w = np.linalg.solve(cov, delta)
    snr1 = float(np.sqrt(delta @ w))
    score = np.tensordot(w / snr1, np.nan_to_num(c), axes=1)
    score[~ok] = np.nan
    false_alarm = float(np.mean(score[bg_sel & ok] >= 2.0))
    return snr1, score, false_alarm


def per_array_cover(ids: np.ndarray, n_arrays: int, k: int):
    """Best single-pixel cover of each array on a k x k (1 m cells) grid, the pixel it is
    in, and per pixel the array covering most of it."""
    hb, wb = ids.shape[0] // k, ids.shape[1] // k
    rr, cc = np.nonzero(ids)
    key = ids[rr, cc].astype(np.int64) * (hb * wb) + (rr // k) * wb + (cc // k)
    uniq, cnt = np.unique(key, return_counts=True)
    aid, blk = uniq // (hb * wb), uniq % (hb * wb)
    best = np.zeros(n_arrays + 1)
    best_blk = np.full(n_arrays + 1, -1)
    owner = np.full(hb * wb, -1)
    owner_cnt = np.zeros(hb * wb)
    for a, b, n in zip(aid, blk, cnt):
        if n > best[a]:
            best[a], best_blk[a] = n, b
        if n > owner_cnt[b]:
            owner_cnt[b], owner[b] = n, a - 1
    return best[1:] / (k * k), best_blk[1:], owner.reshape(hb, wb)


def check_20m_blocks(stack, bands):
    """The 20 m bands must be 2x2-constant on even indices, or the block maths is wrong."""
    for b in NATIVE_20M:
        x = stack[bands.index(b)]
        same = np.mean(x[:, 0::2] == x[:, 1::2]) * np.mean(x[0::2] == x[1::2])
        if same < 0.95:
            raise SystemExit(f"{b} is not 2x2 block-constant on even indices ({same:.2f})")


def choose_window(pv_px: np.ndarray, areas: np.ndarray, inside10: np.ndarray, step=4):
    """The WIN x WIN window, fully inside the area, holding the widest spread of sizes."""
    h, w = inside10.shape
    edges = [0, 50, 100, 400, 1600, np.inf]
    best, best_rc = None, None
    for r in range(0, h - WIN, step):
        for c in range(0, w - WIN, step):
            if inside10[r:r + WIN, c:c + WIN].mean() < 0.999:
                continue
            m = (pv_px[:, 0] >= c + 2) & (pv_px[:, 0] < c + WIN - 2) & \
                (pv_px[:, 1] >= r + 2) & (pv_px[:, 1] < r + WIN - 2)
            counts = np.histogram(areas[m], bins=edges)[0]
            score = (counts > 0).sum() * 1000 + np.minimum(counts, 4).sum() * 10 + m.sum()
            if best is None or score > best:
                best, best_rc = score, (r, c)
    if best_rc is None:
        raise SystemExit("no window fits inside the area")
    return best_rc


def size_distribution():
    """Every mapped PV polygon across the calibration areas, deduplicated by OSM id."""
    frames = []
    for f in sorted(glob.glob(str(LABELS / "*_calib_*_overpass_solar.parquet"))):
        g = gpd.read_parquet(f)
        g = g[g.geometry.type.isin(["Polygon", "MultiPolygon"])]
        frames.append(g[["id", "area_m2"]].assign(q=Path(f).name))
    allpv = pd.concat(frames).drop_duplicates("id")
    a = allpv.area_m2.to_numpy()
    edges = np.round(np.arange(0.8, 4.61, 0.1), 2)
    counts = np.histogram(np.log10(np.clip(a, 10 ** edges[0], 10 ** edges[-1] - 1)), bins=edges)[0]
    return {
        "edges": edges.tolist(), "counts": counts.tolist(), "n": int(len(a)),
        "n_quadrats": int(allpv.q.nunique()), "median": round(float(np.median(a)), 1),
        "share100": round(float(np.mean(a < 100)), 4), "share400": round(float(np.mean(a < 400)), 4),
    }


def px_rings(geom, x0, y0, tol=0.3):
    geom = geom.simplify(tol, preserve_topology=True)
    polys = getattr(geom, "geoms", [geom])
    rings = []
    for p in polys:
        if p.is_empty or p.geom_type != "Polygon":
            continue
        rings.append([[round((x - x0) / 10, 2), round((y0 - y) / 10, 2)] for x, y in p.exterior.coords])
    return rings


def build(quadrat: str, composite: Path | None) -> dict:
    bnd = gpd.read_file(LABELS / f"{quadrat}_boundary.geojson")
    pv = gpd.read_parquet(LABELS / f"{quadrat}_overpass_solar.parquet")
    pv = pv[pv.geometry.type.isin(["Polygon", "MultiPolygon"])].reset_index(drop=True)
    composite = composite or find_composite(bnd)
    src = rasterio.open(composite)
    bands = list(src.descriptions)
    win = from_bounds(*bnd.to_crs(src.crs).total_bounds, src.transform)
    win = win.round_offsets().round_lengths()
    c0 = int(win.col_off) - int(win.col_off) % 2 - 2
    r0 = int(win.row_off) - int(win.row_off) % 2 - 2
    w, h = int(win.width) + 6, int(win.height) + 6
    w, h = w + w % 2, h + h % 2
    win = Window(c0, r0, w, h)
    tr = src.window_transform(win)
    dn = src.read(window=win)
    check_20m_blocks(dn, bands)
    refl = (dn.astype(np.float32) - BOA_OFFSET) / 10000.0
    print(f"{quadrat}: {composite.parent.name}, area grid {h} x {w} px, {len(pv)} PV polygons")

    tr1 = tr * Affine.scale(1 / SUPERSAMPLE)
    shape1 = (h * SUPERSAMPLE, w * SUPERSAMPLE)
    pv_u = pv.to_crs(src.crs)
    ids = features.rasterize([(g, i + 1) for i, g in enumerate(pv_u.geometry)], out_shape=shape1,
                             transform=tr1, fill=0, dtype="int32")
    bbox = tuple(bnd.to_crs(4326).total_bounds + np.array([-0.005, -0.005, 0.005, 0.005]))
    bld = fetch_vida_buildings(bbox, "PAK").to_crs(src.crs)
    roof1 = features.rasterize([(g, 1) for g in bld.geometry], out_shape=shape1, transform=tr1,
                               fill=0, dtype="uint8").astype(np.float32)
    in1 = features.rasterize([(g, 1) for g in bnd.to_crs(src.crs).geometry], out_shape=shape1,
                             transform=tr1, fill=0, dtype="uint8").astype(np.float32)
    pvm = (ids > 0).astype(np.float32)
    f10, f20 = block_mean(pvm, 10), block_mean(pvm, 20)
    roof10, roof20 = block_mean(roof1, 10), block_mean(roof1, 20)
    in10, in20 = block_mean(in1, 10), block_mean(in1, 20)
    del roof1, in1, pvm

    bf10, bb10, own10 = per_array_cover(ids, len(pv), 10)
    bf20, bb20, _ = per_array_cover(ids, len(pv), 20)

    # Per band, at its native resolution.
    con_full = np.full_like(refl, np.nan)
    band_rows = []
    for i, b in enumerate(bands):
        if b in NATIVE_20M:
            v, cov, rf, ins, rad = refl[i][::2, ::2], f20, roof20, in20, 3
        else:
            v, cov, rf, ins, rad = refl[i], f10, roof10, in10, 5
        c, bg_sel = local_contrast(v[None], cov, rf, ins, rad)
        c = c[0]
        delta, n_fit = fit_delta(c, cov, ins)
        sig = robust_sigma(c[bg_sel])
        fstar = 2 * sig / abs(delta)
        px_area = 400 if b in NATIVE_20M else 100
        band_rows.append({"name": b, "nm": BAND_NM[b], "res": 20 if b in NATIVE_20M else 10,
                          "delta": round(delta, 5), "sigma": round(sig, 5), "fstar": round(fstar, 3),
                          "amin": round(fstar * px_area, 1), "n": n_fit,
                          "roof": round(float(np.nanmedian(v[bg_sel])), 4)})
        con_full[i] = np.repeat(np.repeat(c, 2, 0), 2, 1) if b in NATIVE_20M else c
        print(f"  {b} ({band_rows[-1]['res']} m): delta {delta:+.4f}, sigma {sig:.4f}, "
              f"f* {fstar:.2f}, A_min {fstar * px_area:.0f} m2")

    i10 = [bands.index(b) for b in bands if b not in NATIVE_20M]
    c10, bg10 = local_contrast(refl[i10], f10, roof10, in10, 5)
    snr10, s10, fa10 = matched_filter(c10, f10, bg10, in10)
    st20 = np.stack([block_mean(refl[i], 2) for i in range(len(bands))])
    c20, bg20 = local_contrast(st20, f20, roof20, in20, 3)
    snr20, s20, fa20 = matched_filter(c20, f20, bg20, in20)
    mf = {"snr10": round(snr10, 3), "fstar10": round(2 / snr10, 3), "amin10": round(200 / snr10, 1),
          "snr20": round(snr20, 3), "fstar20": round(2 / snr20, 3), "amin20": round(800 / snr20, 1),
          "fa10": round(fa10, 4), "fa20": round(fa20, 4)}
    print(f"  matched filter: 10 m x 4 bands A_min {mf['amin10']} m2; 20 m x 10 bands "
          f"A_min {mf['amin20']} m2 (false alarms {fa10:.3f} / {fa20:.3f})")

    sa10 = np.array([s10.flat[k] if k >= 0 else np.nan for k in bb10])
    sa20 = np.array([s20.flat[k] if k >= 0 else np.nan for k in bb20])
    areas = pv.area_m2.to_numpy()

    # Share of arrays whose best pixel clears 2 sigma, by size: printed for the operator,
    # not embedded (the page shows the per-array scores in its list instead).
    print("  clears 2 sigma at its best pixel (10 m x 4 bands / 20 m x 10 bands):")
    for lo, hi in zip(SIZE_BINS[:-1], SIZE_BINS[1:]):
        m = (areas >= lo) & (areas < hi)
        m10, m20 = m & np.isfinite(sa10), m & np.isfinite(sa20)
        r10 = np.mean(sa10[m10] >= 2) if m10.any() else np.nan
        r20 = np.mean(sa20[m20] >= 2) if m20.any() else np.nan
        print(f"    {lo:>5}-{hi:<5} m2  n={int(m.sum()):>3}  {r10:6.1%} / {r20:6.1%}")

    # Window for the 3D view.
    rep = pv_u.geometry.representative_point()
    inv = ~tr
    pv_px = np.array([inv * (p.x, p.y) for p in rep])
    wr, wc = choose_window(pv_px, areas, in10)
    wr -= wr % 2
    wc -= wc % 2
    x0, y0 = tr * (wc, wr)
    sl = (slice(wr, wr + WIN), slice(wc, wc + WIN))
    sl20 = (slice(wr // 2, wr // 2 + WIN // 2), slice(wc // 2, wc // 2 + WIN // 2))
    # Best pixel of each array INSIDE the window, for arrays the window edge cuts.
    _, wbest, _ = per_array_cover(
        ids[wr * SUPERSAMPLE:(wr + WIN) * SUPERSAMPLE, wc * SUPERSAMPLE:(wc + WIN) * SUPERSAMPLE],
        len(pv), 10)
    del ids

    def ints(a, scale):
        a = np.asarray(a, dtype=np.float64) * scale
        return np.where(np.isfinite(a), np.round(a), NODATA).astype(int).ravel().tolist()

    in_win = (pv_px[:, 0] > wc) & (pv_px[:, 0] < wc + WIN) & (pv_px[:, 1] > wr) & (pv_px[:, 1] < wr + WIN)
    clip = box(x0, y0 - WIN * 10, x0 + WIN * 10, y0)
    polys = []
    for i, g in enumerate(pv_u.geometry):
        if not g.intersects(clip):
            continue
        b10 = wbest[i]
        if b10 < 0:      # a sliver under one 1 m cell
            continue
        polys.append({"i": i, "area": round(float(areas[i]), 1), "bf10": round(float(bf10[i]), 3),
                      "bf20": round(float(bf20[i]), 3),
                      "s10": None if not np.isfinite(sa10[i]) else round(float(sa10[i]), 2),
                      "s20": None if not np.isfinite(sa20[i]) else round(float(sa20[i]), 2),
                      "best": [int(b10 // WIN), int(b10 % WIN)],
                      "place": str(pv.placement.iloc[i]) if "placement" in pv else "",
                      "rings": px_rings(g.intersection(clip), x0, y0)})
    bld_w = bld[bld.intersects(clip)]
    bld_rings = [r for g in bld_w.geometry.intersection(clip) for r in px_rings(g, x0, y0, tol=0.5)]
    own_w = own10[sl]

    center = gpd.GeoSeries.from_xy([x0 + WIN * 5], [y0 - WIN * 5], crs=src.crs).to_crs(4326).iloc[0]
    meta = {
        "quadrat": quadrat, "cell": composite.parent.name, "crs": str(src.crs),
        "n_arrays": int(len(pv)), "n_window_arrays": int(in_win.sum()),
        "n_window_buildings": int(len(bld_w)), "lat": round(center.y, 4), "lon": round(center.x, 4),
        "area_km2": round(float(bnd.to_crs(src.crs).area.sum() / 1e6), 2),
        "median_area": round(float(np.median(areas)), 1),
    }
    print(f"  window rows {wr}-{wr + WIN}, cols {wc}-{wc + WIN}: {len(polys)} arrays, "
          f"{len(bld_w)} buildings, centre {meta['lat']}, {meta['lon']}")
    return {
        "meta": meta, "bands": band_rows, "mf": mf,
        "win": {
            "n": WIN,
            "refl": [ints(refl[i][sl], 10000) for i in range(len(bands))],
            "con": [ints(con_full[i][sl], 10000) for i in range(len(bands))],
            "f10": ints(f10[sl], 100), "f20": ints(f20[sl20], 100), "roof": ints(roof10[sl], 100),
            "s10": ints(s10[sl], 100), "s20": ints(s20[sl20], 100),
            "owner": own_w.ravel().astype(int).tolist(),
        },
        "polys": polys, "bld": bld_rings,
        "sizes": size_distribution(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quadrat", default=DEFAULT_QUADRAT)
    ap.add_argument("--composite", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    data = build(args.quadrat, args.composite)
    html = TEMPLATE_PATH.read_text().replace("__DATA_JSON__", json.dumps(data, separators=(",", ":")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html)
    print(f"-> {args.out} ({args.out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
