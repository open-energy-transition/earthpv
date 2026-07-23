"""Per-pixel orientation-CONSISTENCY version of the cell-aggregate glint density test.

`glint_cell_pixel_anomaly_pilot.py` counted a per-pixel anomaly as "brighter than its
own baseline by 5 sigma" and found the result didn't discriminate PV density at all --
zero-PV control cells had the HIGHEST mean anomaly count, hotspot cells (up to 120
installations) the LOWEST (Pearson corr(area, events) = -0.037). Diagnosed cause: that
pilot only replicated half of what makes the per-INSTALLATION self-referenced method
(glint.spike_fit) reliable. The other half -- and the part missing here -- is the
geometric-consistency check: a real glint's spike dates must agree on ONE fixed panel
orientation via the specular-reflection condition (glint.fit_best_orientation /
misalignment_deg), which is exactly what separates real glint from generic transient
brightening (registration jitter, localized cloud/shadow, other reflective surfaces).
A "5-sigma brighter" pixel with no such date-to-date consistency is almost certainly
noise; this pilot tests whether requiring it recovers the discrimination the raw count
couldn't get.

Per pixel: same 5-sigma anomaly flagging as before, then -- for pixels with >=2
anomalous (clear) scenes -- try each anomalous scene's own required orientation as a
hypothesis (glint.required_orientation) and count how many of the pixel's OTHER
anomalous scenes are within `TOL_DEG` misalignment of it (glint.misalignment_deg,
the same specular-condition check `fit_best_orientation` uses at the per-installation
level). Best hypothesis's count is `n_consistent`; a pixel needs `n_consistent >= 2`
to count as orientation-validated -- a coincidental bright pixel would need to
independently land within a few degrees of the same fixed geometry on 2+ unrelated
dates, which pure noise essentially never does by chance.

Same 44 cells (data/glint_cell/cells.parquet) as both prior pilots, for a clean
three-way comparison: whole-cell p90 (README #7, negative) -> raw per-pixel anomaly
count (negative, inverted) -> per-pixel orientation-consistent count (this script).

Usage:
  .pixi/envs/default/bin/python scripts/glint_cell_pixel_orientation_pilot.py
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
OUT_DIR = DATA_DIR / "glint_cell" / "pixel_orientation"
BANDS = glint.GLINT_BANDS  # ("B03", "B08")
MAX_CLOUD = 80
CLEAR_CLOUD_PCT = 20.0
K_SIGMA = 5.0
SIGMA_FLOOR = 0.015
TOL_DEG = 3.0  # matches spike_fit's default
TILE_DEG = 1.0
MAX_WORKERS = 20


def pull_pixel_cubes(targets: pd.DataFrame) -> dict[str, dict]:
    """Same tile-major single-pass sweep as glint_cell_pixel_anomaly_pilot.py, plus
    per-scene sun/view angles (needed for required_orientation/misalignment_deg)."""
    keys = [glint._tile_key(lon, lat, TILE_DEG) for lon, lat in zip(targets.lon, targets.lat)]
    groups: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    print(f"{len(targets)} cells -> {len(groups)} tile group(s)")

    ANGLE_KEYS = ("sun_zen", "sun_az", "view_zen", "view_az")
    raw = {
        pid: {"time": [], "cloud": [], "transform": None, "crs": None,
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
            cloud = item.properties.get("eo:cloud_cover")
            time = ta.sensing_time or item.datetime
            out = []
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
                out.append((pid, time, cloud, ang, arrs, wt, crs))
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
                for pid, time, cloud, ang, arrs, wt, crs in rows:
                    raw[pid]["time"].append(time)
                    raw[pid]["cloud"].append(cloud)
                    for k in ANGLE_KEYS:
                        raw[pid][k].append(ang[k])
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
    cloud = np.array([c if c is not None else 100.0 for c in cube_data["cloud"]], dtype=float)
    clear_flags = cloud <= CLEAR_CLOUD_PCT
    if clear_flags.sum() < 10:
        print(f"{pid}: only {int(clear_flags.sum())} clear scenes, skipping")
        return None

    cube = {b: np.stack(cube_data[b]) for b in BANDS}
    anomaly = np.ones(cube[BANDS[0]].shape, dtype=bool)  # (n_scenes, H, W)
    for b in BANDS:
        clear_cube = cube[b][clear_flags]
        base = np.nanmedian(clear_cube, axis=0)
        sigma = np.maximum(1.4826 * np.nanmedian(np.abs(clear_cube - base), axis=0), SIGMA_FLOOR)
        anomaly &= cube[b] > (base + K_SIGMA * sigma)
    anomaly &= clear_flags[:, None, None]

    sun_zen = np.array(cube_data["sun_zen"])
    sun_az = np.array(cube_data["sun_az"])
    view_zen = np.array(cube_data["view_zen"])
    view_az = np.array(cube_data["view_az"])
    glint_tilt, glint_az = glint.required_orientation(sun_zen, sun_az, view_zen, view_az)

    H, W = anomaly.shape[1], anomaly.shape[2]
    raw_events = int(anomaly.sum())
    validated_map = np.zeros((H, W), dtype=np.int32)  # n_consistent per validated pixel
    n_validated_pixels = 0
    consistent_events = 0

    # Only bother fitting pixels with >=2 anomalous scenes -- a single spike can't
    # be checked for self-consistency (same rule as fit_best_orientation).
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
            n_validated_pixels += 1
            consistent_events += best_n

    wt = cube_data["transform"]
    np.savez(
        OUT_DIR / f"{pid}_pixels.npz",
        validated_map=validated_map,
        transform=np.array(wt)[:6],
        crs=str(cube_data["crs"]),
    )

    result = dict(
        cid=pid, stratum=row.stratum, area_m2=float(row.area_m2), n_install=int(row.n_install),
        n_scenes_read=n_read, n_clear=int(clear_flags.sum()), n_pixels=H * W,
        raw_anomaly_events=raw_events, n_candidate_pixels=int(len(candidates)),
        n_validated_pixels=n_validated_pixels, consistent_events=consistent_events,
    )
    print(f"{pid} ({row.stratum}, area={row.area_m2:.0f}m2, n_install={row.n_install}): "
          f"{raw_events} raw events, {len(candidates)} candidate pixels, "
          f"{n_validated_pixels} orientation-validated, {consistent_events} consistent events")
    return result


def build_geojson(cells: gpd.GeoDataFrame) -> None:
    rows = []
    for row in cells.itertuples():
        npz_path = OUT_DIR / f"{row.cid}_pixels.npz"
        if not npz_path.exists():
            continue
        data = np.load(npz_path, allow_pickle=True)
        vmap = data["validated_map"]
        wt = rasterio.Affine(*data["transform"])
        crs = str(data["crs"])
        ys, xs = np.nonzero(vmap)
        if len(xs) == 0:
            continue
        native_x, native_y = wt * (xs + 0.5, ys + 0.5)
        lon, lat = rasterio.warp.transform(crs, "EPSG:4326", native_x, native_y)
        for x, y, n_consistent in zip(lon, lat, vmap[ys, xs]):
            rows.append(dict(
                cid=row.cid, stratum=row.stratum, area_m2=float(row.area_m2),
                n_install=int(row.n_install), n_consistent=int(n_consistent),
                geometry=Point(x, y),
            ))
    if not rows:
        print("No orientation-validated pixels to export.")
        return
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    out = OUT_DIR / "orientation_validated_locations.geojson"
    gdf.to_file(out, driver="GeoJSON")
    print(f"Wrote {len(gdf)} orientation-validated pixel locations -> {out}")
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
    print("Pulling pixel cubes + angles (single pass, tile-major)...")
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
        mean_raw_events=("raw_anomaly_events", "mean"),
        mean_candidate_pixels=("n_candidate_pixels", "mean"),
        mean_validated_pixels=("n_validated_pixels", "mean"),
        median_validated_pixels=("n_validated_pixels", "median"),
        mean_consistent_events=("consistent_events", "mean"),
    )
    print(summary.reindex(["zero", "mid", "dense", "hotspot"]).to_string())

    pv_cells = df[df.stratum != "zero"]
    if len(pv_cells) >= 3:
        corr = pv_cells[["area_m2", "n_validated_pixels"]].corr().iloc[0, 1]
        print(f"\nPearson corr(area_m2, n_validated_pixels) among PV-bearing cells: {corr:.3f}")

    build_geojson(cells)


if __name__ == "__main__":
    main()
