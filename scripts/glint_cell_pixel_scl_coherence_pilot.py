"""Two fixes on top of the orientation-consistency pilot, both motivated by real
validation against high-res imagery (a lot of false positives across villages/small
housing, larger installations worked well, clouds still looked like a big issue):

1. **Per-pixel cloud masking via SCL**, replacing the crude whole-scene
   `eo:cloud_cover` metadata threshold used by both prior pixel pilots. A scene
   reported as "15% cloudy" can still have a cloud sitting exactly over one 300m
   cell while the metadata filter waves it through; Sentinel-2's Scene
   Classification Layer (SCL) flags cloud/cloud-shadow/cirrus PER PIXEL, which is
   what `imagery.py` already uses for the segmentation model's composites
   (`_SCL_VALID = (4, 5, 6, 7)`, reused verbatim here). SCL is native 20m
   resolution (B03/B08 are 10m) -- read it nearest-neighbor-resampled onto the
   exact same 10m grid as the reflectance bands (see `read_scl_for_members`), or
   cloud/shadow pixels would silently misalign against the pixels they're meant
   to mask.

2. **Spatial-coherence filter**: the per-pixel method has zero shape awareness --
   a single glinting corrugated-metal/tin roof (extremely common in South Asian
   rural housing, a real non-PV specular reflector) looks identical to a real
   panel to a lone-pixel test. A real PV array should show multiple ADJACENT
   validated pixels forming a panel-shaped footprint; require a minimum connected
   cluster size (`scipy.ndimage.label`, 8-connectivity) before counting a
   detection, filtering out isolated single-pixel hits.

Same 44 cells (data/glint_cell/cells.parquet) as all three prior pilots.

Usage:
  .pixi/envs/default/bin/python scripts/glint_cell_pixel_scl_coherence_pilot.py
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
import rasterio.enums
import rasterio.warp
import rasterio.windows
import scipy.ndimage
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
CELLS_FILE = DATA_DIR / "glint_cell" / "cells.parquet"
OUT_DIR = DATA_DIR / "glint_cell" / "pixel_scl_coherence"
BANDS = glint.GLINT_BANDS  # ("B03", "B08")
MAX_CLOUD = 80
SCL_VALID = (4, 5, 6, 7)  # vegetation, bare, water, unclassified -- matches imagery.py
MIN_VALID_SCENES = 10  # per-pixel minimum SCL-clear scenes to trust its baseline
K_SIGMA = 5.0
SIGMA_FLOOR = 0.015
TOL_DEG = 3.0
MIN_CLUSTER_SIZE = 2  # 8-connected validated pixels required to count as coherent
TILE_DEG = 1.0
MAX_WORKERS = 20


def read_scl_for_members(item, provider: str, member_windows: list[tuple[str, object, tuple]]):
    """Open the SCL asset once, read every member's window resampled (nearest --
    it's categorical) onto its OWN already-read B03/B08 pixel grid (`wt`, `shape`),
    so cloud/shadow flags line up exactly with the reflectance pixels they mask.
    SCL is native 20m vs B03/B08's 10m; naive same-r_px reads would silently cover
    2x the ground extent and misalign entirely."""
    href = item.assets[glint._band_asset_key("SCL", provider)].href
    out = {}
    try:
        with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
            for pid, wt, shape in member_windows:
                try:
                    H, W = shape
                    minx, maxy = wt * (0, 0)
                    maxx, miny = wt * (W, H)
                    row0, col0 = src.index(minx, maxy)
                    row1, col1 = src.index(maxx, miny)
                    win = rasterio.windows.Window(col0, row0, col1 - col0, row1 - row0)
                    arr = src.read(
                        1, window=win, boundless=True, fill_value=0,
                        out_shape=(H, W), resampling=rasterio.enums.Resampling.nearest,
                    )
                    out[pid] = arr.astype(np.int16)
                except Exception:  # noqa: BLE001 -- one bad target must not kill the batch
                    out[pid] = None
    except Exception:  # noqa: BLE001 -- an unopenable asset must not kill the batch
        for pid, _wt, _shape in member_windows:
            out[pid] = None
    return out


def pull_pixel_cubes(targets: pd.DataFrame) -> dict[str, dict]:
    keys = [glint._tile_key(lon, lat, TILE_DEG) for lon, lat in zip(targets.lon, targets.lat)]
    groups: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    print(f"{len(targets)} cells -> {len(groups)} tile group(s)")

    ANGLE_KEYS = ("sun_zen", "sun_az", "view_zen", "view_az")
    raw = {
        pid: {"time": [], "transform": None, "crs": None, "scl": [],
              **{k: [] for k in ANGLE_KEYS}, **{b: [] for b in BANDS}}
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
            time = ta.sensing_time or item.datetime
            valid, member_windows = [], []
            for pid, _geometry, lon, lat in member:
                ang = ta.at(lon, lat)
                if ang is None:
                    continue
                reads = {b: band_arrays[b][pid] for b in BANDS}
                if any(r is None for r in reads.values()):
                    continue
                arrs = {b: reads[b][0] for b in BANDS}
                shape0 = arrs[BANDS[0]].shape
                if any(a.shape != shape0 for a in arrs.values()):
                    continue
                wt, crs = reads[BANDS[0]][1], reads[BANDS[0]][2]
                valid.append((pid, ang, arrs, wt, crs))
                member_windows.append((pid, wt, shape0))
            if not valid:
                return []
            scl_by_pid = read_scl_for_members(item, provider, member_windows)
            out = []
            for pid, ang, arrs, wt, crs in valid:
                scl = scl_by_pid.get(pid)
                if scl is None:
                    continue
                out.append((pid, time, ang, arrs, scl, wt, crs))
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
                for pid, time, ang, arrs, scl, wt, crs in rows:
                    raw[pid]["time"].append(time)
                    for k in ANGLE_KEYS:
                        raw[pid][k].append(ang[k])
                    raw[pid]["scl"].append(scl)
                    if raw[pid]["transform"] is None:
                        raw[pid]["transform"] = wt
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

    cube = {b: np.stack(cube_data[b]) for b in BANDS}
    scl_cube = np.stack(cube_data["scl"])  # (n_scenes, H, W)
    pixel_clear = np.isin(scl_cube, SCL_VALID)  # per-pixel, per-scene cloud/shadow screen
    n_valid_per_pixel = pixel_clear.sum(axis=0)
    trustworthy = n_valid_per_pixel >= MIN_VALID_SCENES
    if not trustworthy.any():
        print(f"{pid}: no pixel has >= {MIN_VALID_SCENES} SCL-clear scenes, skipping")
        return None

    anomaly = np.ones(cube[BANDS[0]].shape, dtype=bool)
    for b in BANDS:
        band_masked = np.where(pixel_clear, cube[b], np.nan)
        base = np.nanmedian(band_masked, axis=0)
        sigma = np.maximum(1.4826 * np.nanmedian(np.abs(band_masked - base), axis=0), SIGMA_FLOOR)
        anomaly &= cube[b] > (base + K_SIGMA * sigma)
    anomaly &= pixel_clear
    anomaly &= trustworthy[None, :, :]

    sun_zen = np.array(cube_data["sun_zen"])
    sun_az = np.array(cube_data["sun_az"])
    view_zen = np.array(cube_data["view_zen"])
    view_az = np.array(cube_data["view_az"])
    glint_tilt, glint_az = glint.required_orientation(sun_zen, sun_az, view_zen, view_az)

    H, W = anomaly.shape[1], anomaly.shape[2]
    raw_events = int(anomaly.sum())
    validated_map = np.zeros((H, W), dtype=np.int32)
    per_pixel_counts = anomaly.reshape(anomaly.shape[0], -1).sum(axis=0).reshape(H, W)
    candidates = np.argwhere(per_pixel_counts >= 2)
    for i, j in candidates:
        spike_idx = np.nonzero(anomaly[:, i, j])[0]
        best_n = 0
        for h in spike_idx:
            mis = glint.misalignment_deg(
                sun_zen[spike_idx], sun_az[spike_idx], view_zen[spike_idx], view_az[spike_idx],
                glint_tilt[h], glint_az[h],
            )
            n = int((mis <= TOL_DEG).sum())
            if n > best_n:
                best_n = n
        if best_n >= 2:
            validated_map[i, j] = best_n

    n_validated_pixels = int((validated_map > 0).sum())

    # Spatial-coherence filter: keep only 8-connected clusters of >= MIN_CLUSTER_SIZE
    # validated pixels -- an isolated single-pixel hit (e.g. one glinting tin roof
    # corner) doesn't look like a panel array; a real array should be multiple
    # adjacent pixels.
    structure = np.ones((3, 3), dtype=int)
    labels, n_labels = scipy.ndimage.label(validated_map > 0, structure=structure)
    coherent_map = np.zeros_like(validated_map)
    n_coherent_clusters = 0
    if n_labels > 0:
        sizes = scipy.ndimage.sum(np.ones_like(labels), labels, index=np.arange(1, n_labels + 1))
        keep_labels = np.nonzero(sizes >= MIN_CLUSTER_SIZE)[0] + 1
        n_coherent_clusters = len(keep_labels)
        keep_mask = np.isin(labels, keep_labels)
        coherent_map = np.where(keep_mask, validated_map, 0)
    n_coherent_pixels = int((coherent_map > 0).sum())

    wt = cube_data["transform"]
    np.savez(
        OUT_DIR / f"{pid}_pixels.npz",
        validated_map=validated_map, coherent_map=coherent_map,
        transform=np.array(wt)[:6], crs=str(cube_data["crs"]),
    )

    result = dict(
        cid=pid, stratum=row.stratum, area_m2=float(row.area_m2), n_install=int(row.n_install),
        n_scenes_read=n_read, n_pixels=H * W, raw_anomaly_events=raw_events,
        n_candidate_pixels=int(len(candidates)), n_validated_pixels=n_validated_pixels,
        n_coherent_clusters=n_coherent_clusters, n_coherent_pixels=n_coherent_pixels,
    )
    print(f"{pid} ({row.stratum}, area={row.area_m2:.0f}m2, n_install={row.n_install}): "
          f"{raw_events} raw events, {n_validated_pixels} orientation-validated, "
          f"{n_coherent_clusters} coherent clusters ({n_coherent_pixels} px)")
    return result


def build_geojson(cells: gpd.GeoDataFrame) -> None:
    rows = []
    for row in cells.itertuples():
        npz_path = OUT_DIR / f"{row.cid}_pixels.npz"
        if not npz_path.exists():
            continue
        data = np.load(npz_path, allow_pickle=True)
        cmap = data["coherent_map"]
        wt = rasterio.Affine(*data["transform"])
        crs = str(data["crs"])
        ys, xs = np.nonzero(cmap)
        if len(xs) == 0:
            continue
        native_x, native_y = wt * (xs + 0.5, ys + 0.5)
        lon, lat = rasterio.warp.transform(crs, "EPSG:4326", native_x, native_y)
        for x, y, n_consistent in zip(lon, lat, cmap[ys, xs]):
            rows.append(dict(
                cid=row.cid, stratum=row.stratum, area_m2=float(row.area_m2),
                n_install=int(row.n_install), n_consistent=int(n_consistent),
                geometry=Point(x, y),
            ))
    if not rows:
        print("No coherent-cluster pixels to export.")
        return
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    out = OUT_DIR / "coherent_locations.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"Wrote {len(gdf)} coherent-cluster pixel locations -> {out}")
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
    print("Pulling pixel cubes + SCL + angles (single pass, tile-major)...")
    raw = pull_pixel_cubes(targets)

    results = []
    for row in cells.itertuples():
        marker = OUT_DIR / f"{row.cid}.csv"
        npz = OUT_DIR / f"{row.cid}_pixels.npz"
        if marker.exists() and npz.exists():
            results.append(pd.read_csv(marker).iloc[0].to_dict())
            continue
        try:
            r = analyze_cell(row.cid, row, raw.get(row.cid, {"time": [], "scl": []}))
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
        mean_raw_events=("raw_anomaly_events", "mean"),
        mean_validated_pixels=("n_validated_pixels", "mean"),
        median_validated_pixels=("n_validated_pixels", "median"),
        mean_coherent_clusters=("n_coherent_clusters", "mean"),
        median_coherent_clusters=("n_coherent_clusters", "median"),
        mean_coherent_pixels=("n_coherent_pixels", "mean"),
    )
    print(summary.reindex(["zero", "mid", "dense", "hotspot"]).to_string())

    pv_cells = df[df.stratum != "zero"]
    if len(pv_cells) >= 3:
        corr = pv_cells[["area_m2", "n_coherent_clusters"]].corr().iloc[0, 1]
        print(f"\nPearson corr(area_m2, n_coherent_clusters) among PV-bearing cells: {corr:.3f}")

    build_geojson(cells)


if __name__ == "__main__":
    main()
