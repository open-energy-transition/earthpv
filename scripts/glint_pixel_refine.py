"""Per-pixel spike-date refinement: can glint sharpen masks, not just rank them?

`glint_iou_experiment.py` showed threshold games (gated lowering/raising) cannot beat
the 0.3 baseline — but 26% of FP pixels sit in the 99 glint-validated windows and 56%
in the 184 detected ones. This tests a stronger use of the same physics: on a spike
date the *panel pixels themselves* brighten 2-3x over their own clear-day baseline,
so a per-pixel amplitude map localizes the panels inside the window. Strategies:

  trim   pred = model & (amp >= t)        — cut model FP halo that never glints
  union  pred = model | (amp >= t_hi)     — add glint-bright pixels the model missed
  both   trim + union

Pull stage (network): for each glint-detected target, read the B08 window for its
spike scenes (strongest 6) and 8 clear non-spike baseline scenes, reprojected onto the
prob-raster window grid; cache per target as npz under data/glint/pixel_refine/.
Analyze stage (offline): sweep strategies over gates (detected / validated), report
overall window IoU against the same 494-target baseline as the threshold experiment.

Usage:
  .pixi/envs/default/bin/python scripts/glint_pixel_refine.py pull
  .pixi/envs/default/bin/python scripts/glint_pixel_refine.py analyze
"""

from __future__ import annotations

import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402
from glint_iou_experiment import (  # noqa: E402
    T_BASE, load_targets, pred_plain, prob_raster_index, read_window,
)

log = logging.getLogger("glint_px")
app = typer.Typer(pretty_exceptions_show_locals=False)

CACHE_DIR = DATA_DIR / "glint" / "pixel_refine"
OUT_DIR = DATA_DIR / "glint"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BAND = "B08"
MAX_SPIKES = 6
MAX_BASELINE = 8
TARGET_THREADS = 4


def _window_grid(tif: str, geom_wgs84):
    """(transform, shape, crs) of the same padded window read_window() uses."""
    from rasterio.windows import Window, from_bounds

    with rasterio.open(tif) as src:
        g = gpd.GeoSeries([geom_wgs84], crs="EPSG:4326").to_crs(src.crs).iloc[0]
        minx, miny, maxx, maxy = g.bounds
        win = from_bounds(minx - 200, miny - 200, maxx + 200, maxy + 200, src.transform)
        win = win.intersection(Window(0, 0, src.width, src.height))
        win = win.round_offsets().round_lengths()
        return src.window_transform(win), (int(win.height), int(win.width)), src.crs


def _read_scene_window(item, provider: str, dst_transform, dst_shape, dst_crs) -> np.ndarray:
    """Scene BAND reflectance reprojected onto the analysis window grid (NaN = nodata)."""
    href = item.assets[glint._band_asset_key(BAND, provider)].href
    dst = np.full(dst_shape, np.nan, dtype="float32")
    with rasterio.Env(GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2"), \
            rasterio.open(href) as src:
        bounds = rasterio.warp.transform_bounds(
            dst_crs, src.crs,
            dst_transform.c, dst_transform.f + dst_transform.e * dst_shape[0],
            dst_transform.c + dst_transform.a * dst_shape[1], dst_transform.f,
        )
        win = rasterio.windows.from_bounds(*bounds, src.transform)
        win = win.round_offsets().round_lengths()
        arr = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
        arr[arr == 0] = np.nan
        arr = arr + glint._boa_offset(item, provider)
        rasterio.warp.reproject(
            arr, dst,
            src_transform=src.window_transform(win), src_crs=src.crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=rasterio.warp.Resampling.nearest,
            src_nodata=np.nan, dst_nodata=np.nan,
        )
    return np.clip((dst - 1000.0) / 10000.0, 0, None)  # DN -> BOA reflectance


def _searched_items(lon: float, lat: float) -> tuple[list, str]:
    for provider in ("planetary-computer", "earth-search"):
        items = glint._search_items(provider, lon, lat, DATE_RANGE[0], DATE_RANGE[1], 80)
        if items:
            return items, provider
    return [], "planetary-computer"


def _items_near(items: list, t, tol_s: float = 1800.0) -> list:
    """Items whose acquisition is within tol_s of t — the stored series `time` is the
    MTD mid-swath sensing time, which drifts up to ~7 min from the STAC item datetime
    (granule start), so exact key matching would silently drop scenes. Neighbouring
    acquisitions are days apart, so 30 min is unambiguous."""
    ts = pd.Timestamp(t)
    out = [it for it in items if abs((pd.Timestamp(it.datetime) - ts).total_seconds()) <= tol_s]
    return sorted(out, key=lambda it: abs((pd.Timestamp(it.datetime) - ts).total_seconds()))


def _pull_one(row) -> str:
    dst_file = CACHE_DIR / f"{row.pid}.npz"
    if dst_file.exists():
        return "skip"
    series = pd.read_parquet(DATA_DIR / "glint" / "pakistan" / f"{row.pid}.parquet")
    ann = glint.annotate_spikes(series)
    if ann.empty or not ann.spike.any():
        np.savez_compressed(dst_file, empty=True)
        return f"{row.pid}: no spikes"
    ann = ann.reset_index(drop=True)
    base_med = ann.loc[ann.clear, f"a_{BAND}"].median()
    spikes = ann[ann.spike].copy()
    spikes["strength"] = spikes[f"a_{BAND}"] / max(base_med, 1e-6)
    spikes = spikes.sort_values("strength", ascending=False).head(MAX_SPIKES)
    mid_spike = spikes.time.astype("int64").median()
    clear = ann[ann.clear & ~ann.spike].copy()
    clear["dt"] = (clear.time.astype("int64") - mid_spike).abs()
    baseline = clear.sort_values("dt").head(MAX_BASELINE)

    grid_t, grid_shape, grid_crs = _window_grid(row.path, row.geometry)
    lon, lat = row.geometry.centroid.x, row.geometry.centroid.y
    items, provider = _searched_items(lon, lat)

    def _read_rows(rows_df) -> list[np.ndarray]:
        out = []
        for t in rows_df.time:
            for it in _items_near(items, t):
                try:
                    arr = _read_scene_window(it, provider, grid_t, grid_shape, grid_crs)
                except Exception as e:  # noqa: BLE001 — a failed scene read just gets skipped
                    log.debug("%s %s read failed: %s", row.pid, t, e)
                    continue
                if np.isfinite(arr).mean() > 0.5:
                    out.append(arr)
                    break
        return out

    spike_arrs = _read_rows(spikes)
    base_arrs = _read_rows(baseline)
    if len(spike_arrs) < 1 or len(base_arrs) < 3:
        np.savez_compressed(dst_file, empty=True)
        return f"{row.pid}: insufficient scenes ({len(spike_arrs)} spike, {len(base_arrs)} base)"
    base_px = np.nanmedian(np.stack(base_arrs), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        amp = np.nanmax(np.stack(spike_arrs), axis=0) / np.clip(base_px, 0.01, None)
    np.savez_compressed(dst_file, amp=amp.astype("float32"),
                        n_spike=len(spike_arrs), n_base=len(base_arrs))
    return f"{row.pid}: amp map from {len(spike_arrs)} spike / {len(base_arrs)} base scenes"


def _gated_targets() -> gpd.GeoDataFrame:
    tgts = load_targets()
    idx = prob_raster_index()
    reps = gpd.GeoDataFrame(
        tgts[["pid"]], geometry=tgts.geometry.representative_point(), crs="EPSG:4326"
    )
    hits = gpd.sjoin(reps, idx, predicate="within", how="left").drop_duplicates("pid")
    tgts = tgts.merge(hits[["pid", "path"]], on="pid", how="left")
    return tgts[tgts.path.notna()].reset_index(drop=True)


@app.command()
def pull():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tgts = _gated_targets()
    todo = tgts[tgts.detected].reset_index(drop=True)
    log.info("%d detected targets, %d cached", len(todo),
             sum((CACHE_DIR / f"{p}.npz").exists() for p in todo.pid))
    done = 0
    with ThreadPoolExecutor(TARGET_THREADS) as ex:
        futs = {ex.submit(_pull_one, r): r.pid for r in todo.itertuples()}
        for f in as_completed(futs):
            try:
                msg = f.result()
            except Exception as e:  # noqa: BLE001 — one bad target must not kill the run
                msg = f"{futs[f]} FAILED: {e}"
            done += 1
            log.info("[%d/%d] %s", done, len(futs), msg)
    log.info("PIXEL_PULL_DONE")


@app.command()
def analyze():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tgts = _gated_targets()
    trims = [1.1, 1.15, 1.2, 1.3, 1.5]
    unions = [1.5, 2.0, 3.0]
    strats = [("baseline", None, None)]
    strats += [(f"trim amp>={t:.2f}", t, None) for t in trims]
    strats += [(f"union amp>={u:.2f}", None, u) for u in unions]
    strats += [(f"trim>=1.20 + union>=2.0", 1.2, 2.0)]

    for gate in ("detected", "validated"):
        acc = {s[0]: np.zeros(3, dtype=np.int64) for s in strats}
        n_gated = n_refined = 0
        for row in tgts.itertuples():
            rw = read_window(row.path, row.geometry)
            if rw is None:
                continue
            prob, gt = rw
            base = pred_plain(prob, T_BASE)
            amp = None
            if getattr(row, gate):
                n_gated += 1
                f = CACHE_DIR / f"{row.pid}.npz"
                if f.exists():
                    z = np.load(f)
                    if "amp" in z and z["amp"].shape == base.shape:
                        amp = z["amp"]
                        n_refined += 1
            for name, t_trim, t_union in strats:
                pred = base
                if amp is not None and name != "baseline":
                    keep = np.isnan(amp) | (amp >= t_trim) if t_trim else np.ones_like(base)
                    pred = base & keep
                    if t_union:
                        pred = pred | (np.nan_to_num(amp) >= t_union)
                tp = int((pred & gt).sum())
                fp = int((pred & ~gt).sum())
                fn = int((~pred & gt).sum())
                acc[name] += (tp, fp, fn)
        rows = [{"strategy": n, "IoU": a[0] / max(a.sum(), 1),
                 "tp": a[0], "fp": a[1], "fn": a[2]} for n, a in acc.items()]
        table = pd.DataFrame(rows).round(4)
        table.to_csv(OUT_DIR / f"pixel_refine_{gate}.csv", index=False)
        print(f"\n=== gate: {gate} ({n_gated} gated, {n_refined} with amp maps; "
              f"windows of all 494 targets included) ===")
        print(table.to_string(index=False))


if __name__ == "__main__":
    app()
