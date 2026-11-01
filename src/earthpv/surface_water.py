"""Surface-water history of candidate outlines, from JRC Global Surface Water.

JRC Global Surface Water v1.3 (Pekel et al. 2016; Landsat 1984-2020, 30 m, 10-degree COG
tiles, Planetary Computer collection `jrc-gsw`, free, no login): `extent` is 1 where a
pixel was ever classified water, `occurrence` the percentage of valid observations that
were, 255 no data (sea). `water_history` returns, per outline, the share of its pixels
(all-touched) that were ever wet and their mean occurrence.

Used as an OPTIONAL lead screen (`export.water_lead_screen`, AOI key `lead_water_screen`):
seasonal pans, salt pans, fish and wastewater ponds read as ground-mounted panels in a
dry-season median. Measured 2026-11-01 on the 13 published countries
(results/fp_filter_survey/): a non-rooftop lead with at least a quarter of its outline ever
wet is a false positive in arid countries (Namibia: 197 leads, 21 of the 67 MWp its leads
carry, none of 57 matched real candidates; Egypt: 93 leads, 9 of 9 sampled on Esri not PV;
Pakistan: 477 leads at 0.2% of matched real candidates). It must stay off where real PV
stands on water or wet ground: India (7.6% of mapped ground-mount area flagged: Khavda's
salt marsh and the Omkareshwar and Ramagundam floating plants) and Vietnam (17%; pond and
floating PV, 3 of 9 flagged leads real). Rooftop flags are noise: a dark city roof is
sometimes classified water.

Reads are batched by the COGs' 512-pixel blocks, fetched in threads and cached compressed
under `CACHE_DIR` (one outline per request would cost ~0.4 s each). `planetary_computer.sign`
started returning 404 for this dataset's storage account on 2026-11-01; the collection
token endpoint works but hands out a shared token valid for about 15 minutes, so reads are
signed with it and re-signed against its own expiry.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/jrc-gsw"
# data/jrc_gsw is a symlink to /home (bulk data off the aidisc drive); ~400 MB covers the
# thirteen published countries.
CACHE_DIR = Path(os.environ.get("EARTHPV_GSW_CACHE", "data/jrc_gsw"))
BLOCK = 512
NODATA = 255
_GDAL_ENV = dict(GDAL_CACHEMAX="2048", VSI_CACHE="TRUE", VSI_CACHE_SIZE="200000000",
                 GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5",
                 GDAL_HTTP_RETRY_DELAY="2", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")

_TOKEN: dict = {}
_TOKEN_LOCK = threading.Lock()
_LOCAL = threading.local()


def _token_expiry(tok: str) -> float:
    se = parse_qs(tok)["se"][0]
    return datetime.strptime(se, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _token(force: bool = False) -> str:
    """The collection SAS token, refreshed five minutes before its own `se`."""
    import requests

    with _TOKEN_LOCK:
        if not force and _TOKEN.get("t") and time.time() < _TOKEN["exp"] - 300:
            return _TOKEN["t"]
        for k in range(10):
            try:
                r = requests.get(TOKEN_URL, timeout=30)
                r.raise_for_status()
                tok = r.json()["token"]
                exp = _token_expiry(tok)
                if exp - time.time() < 120:  # a shared token about to lapse: wait it out
                    raise RuntimeError(f"token expires in {exp - time.time():.0f} s")
                _TOKEN.update(t=tok, exp=exp)
                return tok
            except Exception as e:  # noqa: BLE001
                log.warning("JRC token fetch failed (%s), retry %d", e, k)
                time.sleep(15 * (k + 1))
        raise RuntimeError("no SAS token for jrc-gsw")


def _tile_key(lon: float, lat: float) -> tuple[int, int]:
    """JRC tiles are 10 x 10 degrees, named by their north-west corner."""
    return int(math.floor(lon / 10) * 10), int(math.ceil(lat / 10) * 10)


def _fetch_block(hrefs: dict, tag: str, r: int, c: int, shape: tuple[int, int]) -> np.ndarray:
    """(2, h, w) uint8 extent and occurrence of internal block (r, c), disk-cached."""
    import rasterio
    from rasterio.windows import Window

    p = CACHE_DIR / tag / f"{r}_{c}.npz"
    if p.exists():
        return np.load(p)["a"]
    w = Window(c * BLOCK, r * BLOCK, BLOCK, BLOCK).intersection(Window(0, 0, shape[1], shape[0]))
    for k in range(5):
        ds = getattr(_LOCAL, "ds", None)
        if (ds is None or _LOCAL.tag != tag or _LOCAL.tok != _TOKEN.get("t")
                or time.time() > _TOKEN.get("exp", 0) - 300):
            for d in ds or []:
                d.close()
            tok = _token(force=k > 0)
            _LOCAL.ds = ds = [rasterio.open(f"{hrefs[a]}?{tok}") for a in ("extent", "occurrence")]
            _LOCAL.tag, _LOCAL.tok = tag, tok
        try:
            a = np.stack([ds[0].read(1, window=w), ds[1].read(1, window=w)])
            break
        except rasterio.errors.RasterioIOError as e:
            log.warning("JRC block %s %d,%d unreadable (%s), re-signing", tag, r, c, str(e)[:80])
            for d in ds:
                d.close()
            _LOCAL.ds = None
            time.sleep(5 * (k + 1))
    else:
        raise RuntimeError(f"JRC block {tag} {r},{c} unreadable")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, a=a)
    tmp.rename(p)
    return a


def water_history(geoms: gpd.GeoSeries, workers: int = 24) -> pd.DataFrame:
    """Per outline: `ever_wet_frac` (share of valid pixels ever water, 1984-2020),
    `occurrence_mean` (their mean % of observations wet) and `n_px`. NaN where no valid
    pixel touches the outline (sea, or no JRC tile)."""
    import pystac_client
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import Window, from_bounds
    from rasterio.windows import transform as wtransform

    geoms = gpd.GeoSeries(geoms).to_crs(4326)
    os.environ.update(_GDAL_ENV)  # global, so the worker threads' opens see it
    res = {k: np.full(len(geoms), np.nan) for k in ("ever_wet_frac", "occurrence_mean", "n_px")}
    if geoms.empty:
        return pd.DataFrame(res, index=geoms.index)
    rp = geoms.representative_point()
    keys = pd.Series([_tile_key(x, y) for x, y in zip(rp.x, rp.y)], index=range(len(geoms)))
    cat = pystac_client.Client.open(STAC)
    for (lon0, lat1), idx in keys.groupby(keys).groups.items():
        tag = f"{lon0}_{lat1}"
        items = list(cat.search(collections=["jrc-gsw"],
                                bbox=[lon0 + 4.9, lat1 - 5.1, lon0 + 5.1, lat1 - 4.9]).items())
        if not items:
            log.warning("no JRC surface-water tile for %s", tag)
            continue
        hrefs = {a: items[0].assets[a].href.split("?")[0] for a in ("extent", "occurrence")}
        with rasterio.open(f"{hrefs['extent']}?{_token()}") as src:
            T, H, W = src.transform, src.height, src.width
        full = Window(0, 0, W, H)
        wins = {}
        for i in idx:
            w = from_bounds(*geoms.iloc[i].bounds, transform=T)
            w = Window(math.floor(w.col_off) - 1, math.floor(w.row_off) - 1,
                       math.ceil(w.width) + 3, math.ceil(w.height) + 3)
            try:
                wins[i] = w.intersection(full)
            except rasterio.errors.WindowError:
                pass
        need = set()
        for w in wins.values():
            r0, r1 = int(w.row_off) // BLOCK, (int(w.row_off + w.height) - 1) // BLOCK
            c0, c1 = int(w.col_off) // BLOCK, (int(w.col_off + w.width) - 1) // BLOCK
            need.update((r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1))
        log.info("JRC tile %s: %d outlines, %d blocks", tag, len(wins), len(need))
        with ThreadPoolExecutor(workers) as ex:
            blocks = dict(zip(need, ex.map(
                lambda rc: _fetch_block(hrefs, tag, rc[0], rc[1], (H, W)), need)))
        for i, w in wins.items():
            ro, co, h, wd = int(w.row_off), int(w.col_off), int(w.height), int(w.width)
            arr = np.full((2, h, wd), NODATA, dtype=np.uint8)
            for r in range(ro // BLOCK, (ro + h - 1) // BLOCK + 1):
                for c in range(co // BLOCK, (co + wd - 1) // BLOCK + 1):
                    blk = blocks[(r, c)]
                    br, bc = r * BLOCK, c * BLOCK
                    y0, y1 = max(ro, br), min(ro + h, br + blk.shape[1])
                    x0, x1 = max(co, bc), min(co + wd, bc + blk.shape[2])
                    arr[:, y0 - ro:y1 - ro, x0 - co:x1 - co] = \
                        blk[:, y0 - br:y1 - br, x0 - bc:x1 - bc]
            ext, occ = arr
            m = geometry_mask([geoms.iloc[i]], out_shape=ext.shape, transform=wtransform(w, T),
                              invert=True, all_touched=True) & (ext != NODATA)
            k = int(m.sum())
            if k:
                res["n_px"][i] = k
                res["ever_wet_frac"][i] = float((ext[m] == 1).mean())
                res["occurrence_mean"][i] = float(occ[m].mean())
        del blocks
    return pd.DataFrame(res, index=geoms.index)
