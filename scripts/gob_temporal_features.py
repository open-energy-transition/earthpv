#!/usr/bin/env python
"""Per-building features from Google Open Buildings 2.5D Temporal for roofclf's quadrats.

Open question 22's last open source ("Google Open Buildings 2.5D Temporal"): annual building
presence, fractional count and height, 2016-2023, 4 m effective resolution on a 0.5 m grid,
CC BY 4.0 + ODbL, Global South only. VIDA is an undated snapshot; this gives every footprint
an age (the first year Google's model sees a building there) and a height, which is the one
openly licensed height source after GlobalBuildingAtlas (CC BY-NC, and redundant with roof
area on its 5-quadrat subsample, docs/experiments.md 2026-09-20).

Source: the public bucket gs://open-buildings-temporal-data/v1 over HTTPS, no Earth Engine.
`v1/manifests/<s2token>_EPSG_<utm>_<year>_06_30.json` are Earth Engine ingestion manifests
that list each 12.5 km tile (25,000 px at 0.5 m, 3 float bands, nodata -99) with its affine
transform; the tiles are tiled, deflated GeoTIFFs with internal overviews, so only the
quadrat's window is read at the full 0.5 m. The files' internal overviews are unusable:
  on the Faisalabad quadrat presence reads 0.72 inside footprints and 0.16 outside at 0.5 m,
  and the same 0.20 / 0.12 inside and out at the 2 m / 1 m overviews.

Per building and year: mean presence, mean and max height and summed fractional count over
the footprint's 0.5 m pixels (pixel centres inside; footprints with none take the pixel under
their representative point). Written per row of the calibration table, so the ablation joins
by position.

    .pixi/envs/default/bin/python scripts/gob_temporal_features.py \\
        --table data/roofclf/buildings.geoparquet \\
        --out data/gob_temporal/pakistan_quadrats_features.parquet
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import box

log = logging.getLogger("gob_temporal")

BUCKET = "open-buildings-temporal-data"
HTTP = f"https://storage.googleapis.com/{BUCKET}"
LIST = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
YEARS = list(range(2016, 2024))
TILE_PX = 25000
TILE_RES = 0.5
RES = TILE_RES  # full resolution: the internal overviews carry no building signal
PAD_M = 60.0
NODATA = -99.0
UA = {"User-Agent": "earthpv-research"}

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def manifest_names(cache: Path) -> list[str]:
    path = cache / "manifest_names.json"
    if path.exists():
        return json.loads(path.read_text())
    names, tok = [], None
    while True:
        url = f"{LIST}?prefix=v1/manifests/&maxResults=1000&fields=items(name),nextPageToken"
        d = json.loads(_get(url + (f"&pageToken={tok}" if tok else "")))
        names += [i["name"] for i in d.get("items", [])]
        tok = d.get("nextPageToken")
        if not tok:
            break
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(names))
    return names


def tile_index(epsg: int, year: int, cache: Path) -> list[tuple[tuple, str]]:
    """(bounds, https url) of every tile in the manifests for one UTM zone and year."""
    pat = re.compile(rf"v1/manifests/([0-9a-f]+)_EPSG_{epsg}_{year}_06_30\.json$")
    out = []
    for name in manifest_names(cache):
        if not pat.search(name):
            continue
        local = cache / Path(name).name
        if not local.exists():
            local.write_bytes(_get(f"{HTTP}/{name}"))
        m = json.loads(local.read_text())
        prefix = m["uriPrefix"].replace(f"gs://{BUCKET}", HTTP)
        for s in m["tilesets"][0]["sources"]:
            t = s["affineTransform"]
            w = s["dimensions"]["width"] * t["scaleX"]
            h = s["dimensions"]["height"] * -t["scaleY"]
            x0, y1 = t["translateX"], t["translateY"]
            out.append(((x0, y1 - h, x0 + w, y1), prefix + s["uris"][0]))
    return out


def read_window(urls: list[str], bounds: tuple) -> tuple[np.ndarray, object]:
    """(3, H, W) float32 mosaic over `bounds` (count, height, presence), NaN without data.

    A direct boundless window read of bands 2 and 3 per tile (16 s for a 1 km2 quadrat), not
    `rasterio.merge` of all three (minutes on a shared link); fractional count is not read
    and comes back NaN. Tile origins are whole metres and `bounds` sit on the 0.5 m grid, so
    windows are pixel-aligned and tiles paste without resampling."""
    from rasterio.windows import from_bounds
    x0, y0, x1, y1 = bounds
    w, h = int(round((x1 - x0) / RES)), int(round((y1 - y0) / RES))
    tr = from_origin(x0, y1, RES, RES)
    out = np.full((3, h, w), np.nan, dtype="float32")
    for u in urls:
        with rasterio.open("/vsicurl/" + u) as s:
            win = from_bounds(x0, y0, x1, y1, s.transform).round_offsets().round_lengths()
            a = s.read((2, 3), window=win, boundless=True, fill_value=NODATA,
                       out_shape=(2, h, w)).astype("float32")
        a[a == NODATA] = np.nan
        for k in (0, 1):
            m = np.isfinite(a[k])
            out[k + 1][m] = a[k][m]
    return out, tr


def zonal(bu: gpd.GeoDataFrame, arr: np.ndarray, tr) -> pd.DataFrame:
    """Per building: presence mean, height mean/max, fractional count sum."""
    h, w = arr.shape[1:]
    ids = np.arange(1, len(bu) + 1, dtype=np.int32)
    lab = rasterize(zip(bu.geometry, ids), out_shape=(h, w), transform=tr, fill=0,
                    dtype="int32", all_touched=False)
    count, height, presence = arr
    n = len(bu) + 1
    flat = lab.ravel()
    ok = flat > 0
    def agg(v: np.ndarray, how: str) -> np.ndarray:
        v = v.ravel()
        good = ok & np.isfinite(v)
        if how == "sum":
            return np.bincount(flat[good], weights=v[good], minlength=n)[1:]
        if how == "mean":
            s = np.bincount(flat[good], weights=v[good], minlength=n)[1:]
            c = np.bincount(flat[good], minlength=n)[1:]
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(c > 0, s / c, np.nan)
        mx = np.full(n, -np.inf)
        np.maximum.at(mx, flat[good], v[good])
        mx = mx[1:]
        return np.where(np.isfinite(mx), mx, np.nan)
    px = np.bincount(flat[ok], minlength=n)[1:]
    out = pd.DataFrame({
        "px": px,
        "presence": agg(presence, "mean"),
        "height": agg(height, "mean"),
        "height_max": agg(height, "max"),
        "count": agg(count, "sum"),
    })
    # Footprints that own no pixel centre: the pixel under the representative point.
    miss = np.flatnonzero(px == 0)
    if len(miss):
        pts = bu.geometry.iloc[miss].representative_point()
        inv = ~tr
        cols, rows = inv * (pts.x.to_numpy(), pts.y.to_numpy())
        r = np.clip(np.floor(rows).astype(int), 0, h - 1)
        c = np.clip(np.floor(cols).astype(int), 0, w - 1)
        out.loc[miss, "presence"] = presence[r, c]
        out.loc[miss, "height"] = height[r, c]
        out.loc[miss, "height_max"] = height[r, c]
        out.loc[miss, "count"] = count[r, c]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--table", type=Path, default=Path("data/roofclf/buildings.geoparquet"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/gob_temporal/pakistan_quadrats_features.parquet"))
    ap.add_argument("--cache", type=Path, default=Path("data/gob_temporal/manifests"))
    ap.add_argument("--quadrat", action="append", help="only these quadrats (repeatable)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t = gpd.read_parquet(a.table)
    t = t.reset_index(drop=True)
    t["row"] = np.arange(len(t))
    quads = a.quadrat or sorted(t.quadrat.unique())
    parts = []
    for q in quads:
        sub = t[t.quadrat == q]
        lon = float(sub.to_crs(4326).geometry.union_all().centroid.x)
        epsg = 32600 + int((lon + 180) // 6) + 1
        bu = sub.to_crs(epsg)
        minx, miny, maxx, maxy = bu.total_bounds
        bounds = (np.floor((minx - PAD_M) / RES) * RES, np.floor((miny - PAD_M) / RES) * RES,
                  np.ceil((maxx + PAD_M) / RES) * RES, np.ceil((maxy + PAD_M) / RES) * RES)
        qbox = box(*bounds)
        part = a.out.parent / "parts" / f"{q}.parquet"
        if part.exists():
            parts.append(pd.read_parquet(part))
            log.info("%s: cached", q)
            continue
        res = {"row": sub.row.to_numpy()}

        def one_year(y: int):
            urls = [u for b, u in tile_index(epsg, y, a.cache) if box(*b).intersects(qbox)]
            if not urls:
                return y, None, 0
            for attempt in range(5):  # a DNS blip once killed a run (2026-11-22)
                try:
                    arr, tr = read_window(urls, bounds)
                    break
                except rasterio.errors.RasterioIOError as e:
                    if attempt == 4:
                        raise
                    log.warning("%s %d: %s; retrying", q, y, e)
                    import time
                    time.sleep(30 * (attempt + 1))
            return y, zonal(bu, arr, tr), len(urls)

        from concurrent.futures import ThreadPoolExecutor
        for y in YEARS:  # manifests first, serially, so threads never race on the cache
            tile_index(epsg, y, a.cache)
        # About 8 float32 arrays per year in flight; Lahore (43M px) at 8 years in parallel
        # was OOM-killed at 10 GB, so the thread count follows the window size.
        npx = (bounds[2] - bounds[0]) / RES * (bounds[3] - bounds[1]) / RES
        workers = int(max(1, min(len(YEARS), 4e9 // (npx * 4 * 8))))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for y, z, n in ex.map(one_year, YEARS):
                if z is None:
                    log.warning("%s %d: no tile", q, y)
                    continue
                for c in ("presence", "height", "height_max", "count"):
                    res[f"{c}_{y}"] = z[c].to_numpy()
                if y == YEARS[-1]:
                    res["px"] = z["px"].to_numpy()
                log.info("%s %d: %d tile(s), presence %.2f, height %.1f m (medians)", q, y, n,
                         np.nanmedian(z.presence), np.nanmedian(z.height))
        part.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(res).to_parquet(part)
        parts.append(pd.DataFrame(res))
    out = pd.concat(parts, ignore_index=True).sort_values("row")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out)
    log.info("wrote %d buildings x %d columns -> %s", len(out), out.shape[1], a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
