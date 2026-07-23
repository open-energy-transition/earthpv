"""Per-pixel anomaly-count pilot for cell-aggregate glint density.

The original cell-aggregate test (glint_cell_density_{targets,pull,analyze}.py,
README #7) blended each cell into ONE p90-of-whole-cell statistic per scene and found
no signal: zero-PV control cells averaged 1.0 spike, PV-bearing cells 1.45 (medians
tied at 1.0). Diagnosed cause: p90 only moves if ~10% of the cell's pixels brighten
simultaneously, but each installation glints on its own narrow, orientation-specific
date window -- even the busiest 120-installation hotspot never got enough panels
glinting on the SAME date to clear that bar.

This tests the identified-but-untried fix: instead of one blended statistic, count
per-PIXEL anomalies (each pixel judged against its OWN clear-scene baseline, exactly
the self-referenced idea already validated at the per-installation level -- see
[[earthpv-glint-direct-detection]]) and SUM those counts over the whole time series.
This sidesteps "needs simultaneous brightening" entirely: it just accumulates
independent narrow-window hits pixel by pixel, scene by scene.

Reuses the exact same 44 cells (data/glint_cell/cells.parquet: 15 dense + 10 mid +
15 zero + 4 hotspot, same Lahore ground truth) for an apples-to-apples comparison
against the original negative result.

v2: pixel reads happen in the SAME pass as the STAC item search/asset-open (one
tile-major sweep over every scene, capturing every cell's window immediately via
`glint._read_targets_from_item(..., return_array=True)`), not a later per-cell loop
over cached item refs -- v1 cached `tile_scene_series_batch(keep_items=True)`'s items
and re-opened their hrefs sequentially per cell afterward; by the time it reached
cell #12 the SAS tokens minted during the original search had expired, and every
cell after that silently returned "0 readable scenes" (the per-target try/except
caught the expired-token error as ordinary missing data). "Clear" scene
classification here uses the item's own `eo:cloud_cover` metadata instead of a
ring-stability check -- cheap (no extra window read) and avoids needing the
wide-external-ring machinery the original cell pull used for a different purpose.

Usage:
  .pixi/envs/default/bin/python scripts/glint_cell_pixel_anomaly_pilot.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
CELLS_FILE = DATA_DIR / "glint_cell" / "cells.parquet"
OUT_DIR = DATA_DIR / "glint_cell" / "pixel_anomaly"
BANDS = glint.GLINT_BANDS  # ("B03", "B08")
MAX_CLOUD = 80
CLEAR_CLOUD_PCT = 20.0  # scene-level eo:cloud_cover cutoff for baseline-eligible scenes
K_SIGMA = 5.0  # matches annotate_spikes's per-installation threshold
SIGMA_FLOOR = 0.015  # matches annotate_spikes
TILE_DEG = 1.0
MAX_WORKERS = 20


def pull_pixel_cubes(targets: pd.DataFrame) -> dict[str, dict]:
    """Tile-major sweep: one STAC search + one set of asset opens per tile group,
    every cell's window read immediately per scene (no cached hrefs re-opened later).
    Returns {pid: {"time": [...], "cloud": [...], band: [2D array, ...]}}."""
    keys = [glint._tile_key(lon, lat, TILE_DEG) for lon, lat in zip(targets.lon, targets.lat)]
    groups: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    print(f"{len(targets)} cells -> {len(groups)} tile group(s)")

    raw = {
        pid: {"time": [], "cloud": [], "transform": None, "crs": None, **{b: [] for b in BANDS}}
        for pid in targets.pid
    }
    for gi, ((gx, gy), idx) in enumerate(groups.items()):
        grp = targets.iloc[idx]
        bbox = (gx * TILE_DEG, gy * TILE_DEG, (gx + 1) * TILE_DEG, (gy + 1) * TILE_DEG)
        provider = "planetary-computer"
        try:
            items = glint._search_items_bbox(provider, bbox, *DATE_RANGE, MAX_CLOUD)
        except Exception as e:  # noqa: BLE001 -- one bad group search must not kill the run
            print(f"group {gi}: PC search failed ({e.__class__.__name__}), trying Earth Search")
            items = []
        if not items:
            provider = "earth-search"
            try:
                items = glint._search_items_bbox(provider, bbox, *DATE_RANGE, MAX_CLOUD)
            except Exception as e:  # noqa: BLE001
                print(f"group {gi}: Earth Search also failed ({e.__class__.__name__})")
                items = []
        if not items:
            print(f"group {gi}: no scenes for bbox {bbox}")
            continue
        items = sorted(items, key=lambda i: i.id)
        member = [(r.pid, r.geometry, r.lon, r.lat) for r in grp.itertuples()]
        print(f"group {gi}: {len(items)} scenes x {len(member)} cells")

        def _process_item(item):
            try:
                ta = glint._cached_tile_angles(item, provider)
            except Exception:  # noqa: BLE001 -- one bad scene shouldn't kill the group
                return []
            band_arrays = {
                band: glint._read_targets_from_item(item, band, member, provider, return_array=True)
                for band in BANDS
            }
            cloud = item.properties.get("eo:cloud_cover")
            time = ta.sensing_time or item.datetime
            out = []
            for pid, _geometry, lon, lat in member:
                if ta.at(lon, lat) is None:
                    continue
                reads = {b: band_arrays[b][pid] for b in BANDS}
                if any(r is None for r in reads.values()):
                    continue
                arrs = {b: reads[b][0] for b in BANDS}
                shape0 = arrs[BANDS[0]].shape
                if any(a.shape != shape0 for a in arrs.values()):
                    continue
                wt, crs = reads[BANDS[0]][1], reads[BANDS[0]][2]
                out.append((pid, time, cloud, arrs, wt, crs))
            return out

        with ThreadPoolExecutor(MAX_WORKERS) as ex:
            futs = {ex.submit(_process_item, it): it for it in items}
            done = 0
            for f in as_completed(futs):
                try:
                    rows = f.result()
                except Exception as e:  # noqa: BLE001 -- one bad item must not kill the group
                    print(f"item {futs[f].id} failed: {e}")
                    rows = []
                for pid, time, cloud, arrs, wt, crs in rows:
                    raw[pid]["time"].append(time)
                    raw[pid]["cloud"].append(cloud)
                    if raw[pid]["transform"] is None:
                        raw[pid]["transform"] = wt  # same UTM grid every scene in a group; first is fine
                        raw[pid]["crs"] = crs
                    for b in BANDS:
                        raw[pid][b].append(glint._refl(arrs[b]))
                done += 1
                if done % 50 == 0:
                    print(f"group {gi}: {done}/{len(items)} scenes processed")
    return raw


def analyze_cell(pid: str, row, cube_data: dict) -> dict | None:
    n_read = len(cube_data["time"])
    if n_read < 20:
        print(f"{pid}: only {n_read} readable scenes, skipping")
        return None
    cloud = np.array([c if c is not None else 100.0 for c in cube_data["cloud"]], dtype=float)
    clear_flags = cloud <= CLEAR_CLOUD_PCT
    if clear_flags.sum() < 10:
        print(f"{pid}: only {int(clear_flags.sum())} clear scenes (cloud<={CLEAR_CLOUD_PCT}), skipping")
        return None

    cube = {b: np.stack(cube_data[b]) for b in BANDS}  # (n_scenes, H, W)
    anomaly = np.ones(cube[BANDS[0]].shape, dtype=bool)
    for b in BANDS:
        clear_cube = cube[b][clear_flags]
        base = np.nanmedian(clear_cube, axis=0)
        sigma = np.maximum(1.4826 * np.nanmedian(np.abs(clear_cube - base), axis=0), SIGMA_FLOOR)
        anomaly &= cube[b] > (base + K_SIGMA * sigma)
    anomaly &= clear_flags[:, None, None]

    per_scene_count = anomaly.reshape(anomaly.shape[0], -1).sum(axis=1)
    total_events = int(per_scene_count.sum())
    n_anomalous_scenes = int((per_scene_count > 0).sum())
    max_scene_count = int(per_scene_count.max()) if len(per_scene_count) else 0
    n_pixels = anomaly.shape[1] * anomaly.shape[2]
    n_clear = int(clear_flags.sum())

    # Per-pixel anomaly count map, saved alongside the affine transform + CRS so
    # locations can be reconstructed later for validation (see build_anomaly_geojson).
    count_map = anomaly.sum(axis=0).astype(np.int32)  # (H, W)
    wt = cube_data["transform"]
    np.savez(
        OUT_DIR / f"{pid}_pixels.npz",
        count_map=count_map,
        transform=np.array(wt)[:6],
        crs=str(cube_data["crs"]),
    )

    result = dict(
        cid=pid, stratum=row.stratum, area_m2=float(row.area_m2), n_install=int(row.n_install),
        n_scenes_read=n_read, n_clear=n_clear, n_pixels=n_pixels,
        total_anomaly_events=total_events, n_anomalous_scenes=n_anomalous_scenes,
        max_scene_anomaly_count=max_scene_count,
        anomaly_rate=total_events / (n_pixels * n_clear) if n_clear else np.nan,
    )
    print(f"{pid} ({row.stratum}, area={row.area_m2:.0f}m2, n_install={row.n_install}): "
          f"{n_clear}/{n_read} clear scenes, {total_events} total anomaly events, "
          f"{n_anomalous_scenes} anomalous scenes, max/scene={max_scene_count}")
    return result


def build_anomaly_geojson(cells: gpd.GeoDataFrame) -> None:
    """One point per distinct anomalous pixel, across every cell that produced a
    result -- for visual validation against high-res imagery (JOSM etc.)."""
    rows = []
    for row in cells.itertuples():
        npz_path = OUT_DIR / f"{row.cid}_pixels.npz"
        if not npz_path.exists():
            continue
        data = np.load(npz_path, allow_pickle=True)
        count_map = data["count_map"]
        wt = rasterio.Affine(*data["transform"])
        crs = str(data["crs"])
        ys, xs = np.nonzero(count_map)
        if len(xs) == 0:
            continue
        # pixel center -> native CRS -> EPSG:4326
        native_x, native_y = wt * (xs + 0.5, ys + 0.5)
        lon, lat = rasterio.warp.transform(crs, "EPSG:4326", native_x, native_y)
        for x, y, count in zip(lon, lat, count_map[ys, xs]):
            rows.append(dict(
                cid=row.cid, stratum=row.stratum, area_m2=float(row.area_m2),
                n_install=int(row.n_install), anomaly_count=int(count),
                geometry=Point(x, y),
            ))
    if not rows:
        print("No anomaly pixels to export.")
        return
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    out = OUT_DIR / "anomaly_locations.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"Wrote {len(gdf)} anomaly-pixel locations -> {out}")
    print(gdf.groupby("stratum").agg(n_points=("cid", "size"), n_cells=("cid", "nunique")).to_string())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cells = gpd.read_parquet(CELLS_FILE)
    print(f"{len(cells)} cells ({cells.stratum.value_counts().to_dict()})")

    targets = pd.DataFrame({
        "pid": cells["cid"].to_numpy(),
        "geometry": cells.geometry.to_numpy(),
        "lon": cells.geometry.centroid.x.to_numpy(),
        "lat": cells.geometry.centroid.y.to_numpy(),
    })
    print("Pulling pixel cubes (single pass, tile-major)...")
    raw = pull_pixel_cubes(targets)

    results = []
    for row in cells.itertuples():
        marker = OUT_DIR / f"{row.cid}.csv"
        npz = OUT_DIR / f"{row.cid}_pixels.npz"
        if marker.exists() and npz.exists():
            results.append(pd.read_csv(marker).iloc[0].to_dict())
            continue
        try:
            r = analyze_cell(row.cid, row, raw.get(row.cid, {"time": [], "cloud": []}))
        except Exception as e:  # noqa: BLE001 -- one bad cell must not kill the run
            print(f"{row.cid}: FAILED ({e.__class__.__name__}: {e})")
            continue
        if r:
            pd.DataFrame([r]).to_csv(marker, index=False)
            results.append(r)

    if not results:
        print("No cells produced a usable result.")
        return
    df = pd.DataFrame(results)
    df.to_csv(OUT_DIR / "combined.csv", index=False)
    print(f"\n=== Per-stratum summary ({len(df)} cells) ===")
    summary = df.groupby("stratum").agg(
        n=("cid", "size"),
        mean_total_events=("total_anomaly_events", "mean"),
        median_total_events=("total_anomaly_events", "median"),
        mean_anomalous_scenes=("n_anomalous_scenes", "mean"),
        mean_anomaly_rate=("anomaly_rate", "mean"),
    )
    print(summary.reindex(["zero", "mid", "dense", "hotspot"]).to_string())

    pv_cells = df[df.stratum != "zero"]
    if len(pv_cells) >= 3:
        corr = pv_cells[["area_m2", "total_anomaly_events"]].corr().iloc[0, 1]
        print(f"\nPearson corr(area_m2, total_anomaly_events) among PV-bearing cells: {corr:.3f}")

    build_anomaly_geojson(cells)


if __name__ == "__main__":
    main()
