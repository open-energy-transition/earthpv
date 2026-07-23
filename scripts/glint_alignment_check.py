"""Check label-vs-Sentinel-2 alignment: for a handful of OSM-confirmed PV installations
with strong, self-consistent glint signals, accumulate every detected glint scene into
one max-composite image (per-pixel max reflectance across all spike dates) and overlay
the OSM polygon boundary. A real, well-aligned panel should light up a hotspot that sits
INSIDE the polygon; a systematic offset across many targets would point at a genuine
label/imagery misalignment rather than normal within-roof variation.

Fetches via `glint.tile_scene_series_batch` (one STAC search + shared asset opens per
1-degree tile group, scenes within a group read concurrently) rather than one
independent per-target point search each -- the same tile-major approach validated in
docs/issues/glint-tile-batched-coverage.md, with `keep_items=True` so this script can
go back and re-read pixel windows for the specific scenes `annotate_spikes` flagged,
without a second search. Reuses glint.py's exact per-target window/read logic
(`_read_target_array`, `_target_window`) so the pixel grid is identical to what
`spike_fit`/`annotate_spikes` already scored -- this is a pixel-level view of the same
evidence, not a new pipeline.

Usage:
  .pixi/envs/default/bin/python scripts/glint_alignment_check.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless machine, no $DISPLAY -- must be set before pyplot import

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.patches import Polygon as MplPolygon
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BAND = "B03"  # 10m native, no resampling -- matches GLINT_BANDS[0]
OUT_DIR = DATA_DIR / "glint" / "alignment_check"
# Hand-picked: high spike count + high mutual-consistency (n_consistent close to
# n_spikes), spread across the country and across size buckets -- see
# data/glint/pakistan_revalidate_tilebatch.csv. pk_0429/pk_0491 sit ~2m apart (same
# tile group) -- a real test of the batch's search/asset-open sharing, not just its
# per-target correctness.
TARGET_PIDS = ["pk_0071", "pk_0222", "pk_0257", "pk_0429", "pk_0491", "pk_0447"]


def read_reflectance(item, provider: str, geometry, lon: float, lat: float):
    href = item.assets[glint._band_asset_key(BAND, provider)].href
    with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
        arr, wt, geom_native = glint._read_target_array(src, geometry, lon, lat)
    offset = glint._boa_offset(item, provider)
    return glint._refl(arr + offset), wt, geom_native


def poly_to_pixel_xy(geom_native, transform):
    """Exterior ring of geom_native (possibly Multi-) in (col, row) pixel space."""
    rings = []
    geoms = geom_native.geoms if geom_native.geom_type.startswith("Multi") else [geom_native]
    for g in geoms:
        xs, ys = g.exterior.coords.xy
        cols, rows = ~transform * (np.array(xs), np.array(ys))
        rings.append(np.column_stack([cols, rows]))
    return rings


def build_composite(pid: str, row, df: pd.DataFrame) -> dict | None:
    """Given one target's tile-batched scene series (with `_item`/`_provider` columns
    from `keep_items=True`), flag spikes and build the max-composite glint image."""
    if df.empty:
        print(f"{pid}: no scenes found")
        return None
    d = glint.annotate_spikes(df)
    spikes = d[d.spike]
    if spikes.empty:
        print(f"{pid}: {len(d)} scenes, 0 spikes -- skipping")
        return None

    geometry, lon, lat = row.geometry, row.lon, row.lat
    arrays, transform, geom_native = [], None, None
    for t, item, provider in zip(spikes.time, spikes["_item"], spikes["_provider"]):
        try:
            refl, wt, gn = read_reflectance(item, provider, geometry, lon, lat)
        except Exception as e:  # noqa: BLE001 -- one bad read shouldn't kill the target
            print(f"{pid}: read failed for {t}: {e}")
            continue
        if transform is None:
            transform, geom_native = wt, gn
        if not arrays or refl.shape == arrays[0].shape:
            arrays.append(refl)
    if not arrays:
        print(f"{pid}: no readable spike scenes")
        return None

    stack = np.stack(arrays)
    composite = np.nanmax(stack, axis=0)
    n_used = len(arrays)

    # brightest pixel in the composite vs. polygon centroid, both in pixel space
    peak_row, peak_col = np.unravel_index(np.nanargmax(composite), composite.shape)
    cen_col, cen_row = ~transform * (geom_native.centroid.x, geom_native.centroid.y)
    offset_px = float(np.hypot(peak_col - cen_col, peak_row - cen_row))
    peak_xy = transform * (peak_col + 0.5, peak_row + 0.5)
    peak_inside = geom_native.buffer(10).contains(Point(peak_xy))  # 10m slack = ~1px

    result = dict(
        pid=pid, bucket=row.bucket, area_m2=float(row.area_m2), n_scenes=len(d),
        n_spikes=len(spikes), n_composited=n_used, offset_px=offset_px,
        offset_m=offset_px * 10, peak_inside_polygon=bool(peak_inside),
        composite=composite, transform=transform, geom_native=geom_native,
    )
    print(f"{pid} ({row.bucket}, {row.area_m2:.0f} m2): {len(d)} scenes, {len(spikes)} spikes, "
          f"{n_used} composited, peak offset {offset_px:.1f}px ({offset_px*10:.0f}m), "
          f"peak inside polygon: {peak_inside}")
    return result


def plot_results(results: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = len(results)
    fig, axes = plt.subplots(1, n, figsize=(4.2 * n, 4.6))
    if n == 1:
        axes = [axes]
    for ax, r in zip(axes, results):
        comp = r["composite"]
        vmax = np.nanpercentile(comp, 99.5)
        ax.imshow(comp, cmap="inferno", vmin=0, vmax=max(vmax, 0.05))
        for ring in poly_to_pixel_xy(r["geom_native"], r["transform"]):
            ax.add_patch(MplPolygon(ring, closed=True, fill=False, edgecolor="cyan",
                                     linewidth=1.6))
        peak_row, peak_col = np.unravel_index(np.nanargmax(comp), comp.shape)
        ax.plot(peak_col, peak_row, marker="+", color="lime", markersize=14, markeredgewidth=2)
        ax.set_title(
            f"{r['pid']} ({r['bucket']})\n{r['area_m2']:.0f} m2, {r['n_spikes']} spikes, "
            f"offset {r['offset_m']:.0f}m\ninside={r['peak_inside_polygon']}",
            fontsize=9,
        )
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle("Glint max-composite (B03 reflectance) vs. OSM polygon (cyan) -- "
                  "+ marks the brightest accumulated pixel", fontsize=11)
    fig.tight_layout()
    out = OUT_DIR / "glint_alignment_check.png"
    fig.savefig(out, dpi=150)
    print(f"\nWrote {out}")


def main() -> None:
    all_targets = gpd.read_parquet(DATA_DIR / "glint" / "pakistan_targets.parquet")
    targets = all_targets[all_targets.pid.isin(TARGET_PIDS)].reset_index(drop=True)
    print(f"Fetching {len(targets)} targets via tile_scene_series_batch...")
    series_by_pid = glint.tile_scene_series_batch(
        targets[["pid", "geometry", "lon", "lat"]], *DATE_RANGE,
        tile_deg=1.0, max_workers=8, keep_items=True,
    )

    results = []
    for pid in TARGET_PIDS:
        matches = targets.loc[targets.pid == pid]
        if matches.empty:
            print(f"{pid}: not found in targets parquet")
            continue
        row = matches.iloc[0]
        df = series_by_pid.get(pid, pd.DataFrame())
        try:
            r = build_composite(pid, row, df)
        except Exception as e:  # noqa: BLE001 -- one bad target must not kill the run
            print(f"{pid}: failed ({e.__class__.__name__}: {e})")
            continue
        if r:
            results.append(r)

    if not results:
        print("No targets produced a usable composite.")
        return
    offsets = [r["offset_m"] for r in results]
    inside = [r["peak_inside_polygon"] for r in results]
    print(f"\n=== Summary: {len(results)} targets ===")
    print(f"peak-offset (m): mean={np.mean(offsets):.1f} median={np.median(offsets):.1f} "
          f"max={np.max(offsets):.1f}")
    print(f"peak inside polygon: {sum(inside)}/{len(inside)}")
    plot_results(results)


if __name__ == "__main__":
    main()
