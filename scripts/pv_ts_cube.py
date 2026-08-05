"""Dense per-scene Sentinel-2 L2A cubes for small AOIs (calibration boxes).

Why this exists: the production pipeline sees each cell as *two* dry-season median
composites (`composite_0` = 2025/26, `composite_1` = 2021/22). Differencing two medians
throws away almost all of the temporal information — and silently mixes the Sentinel-2
processing-baseline conventions (see "Radiometry" below). A rooftop array of 100 m2
covers ~1 Sentinel-2 pixel (often a fraction of one), so the per-date signal is small;
but with ~500 dates over 8 years the *step* in a pixel's reflectance when panels are
installed is estimable at far better precision than a 2-composite difference (SE shrinks
with sqrt(N), and the seasonal/atmospheric common mode can be regressed out against
neighbouring roofs).

This module only *fetches and caches* the cube. Analysis lives in `pv_step_signal.py`.

Radiometry (the landmine): ESA's processing baseline 04.00 (2022-01-25) added a +1000 DN
BOA offset. Planetary Computer serves raw DNs, so pre-2022 scenes sit on a different
convention than post-2022 ones — a naive multi-year difference sees a spurious +1000 step
at exactly the boom's start. Worse, the catalog carries BOTH the original (03.00) and the
Collection-1-reprocessed (04.00/05.xx) version of the *same* acquisition, so
`groupby="solar_day"` can median across conventions. Handled by: dedupe per acquisition
keeping the highest baseline, then normalise every scene to *offset-removed* DN, i.e.
reflectance = DN / 10000 for every date in the cube.

Provider: Earth Search (AWS) is the default — Planetary Computer's STAC search was timing
out wholesale while this was written, and ES already serves offset-corrected COGs
(`earthsearch:boa_offset_applied`), needs no token, and is fast for small windows.

Usage:
    python scripts/pv_ts_cube.py pull --name lahore_box \
        --boundary data/labels/lahore_calib_6p61km2_boundary.geojson --buffer-m 250
    python scripts/pv_ts_cube.py pull --name control_crop --bbox 74.55,31.30,74.57,31.32
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import warnings
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np

warnings.filterwarnings("ignore", category=RuntimeWarning)
log = logging.getLogger("pv_ts_cube")

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
ES_STAC = "https://earth-search.aws.element84.com/v1"
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
ES_ASSET = {
    "B02": "blue", "B03": "green", "B04": "red", "B05": "rededge1", "B06": "rededge2",
    "B07": "rededge3", "B08": "nir", "B8A": "nir08", "B11": "swir16", "B12": "swir22",
    "SCL": "scl",
}
CUBE_ROOT = Path("data/ts")
# SCL classes kept: 4 vegetation, 5 bare/built, 6 water, 7 unclassified — the same set
# the composite pipeline uses, so cube-derived stats stay comparable to composite ones.
SCL_VALID = (4, 5, 6, 7)


def _catalog(provider: str):
    import pystac_client

    if provider == "earth-search":
        return pystac_client.Client.open(ES_STAC)
    import planetary_computer

    return pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)


def _baseline(item) -> float:
    try:
        return float(item.properties.get("s2:processing_baseline", "0"))
    except (TypeError, ValueError):
        return 0.0


def _tile(item) -> str:
    code = item.properties.get("grid:code") or item.properties.get("s2:mgrs_tile")
    if code:
        return str(code).replace("MGRS-", "")
    m = re.search(r"_T(\d{2}[A-Z]{3})_", item.properties.get("s2:granule_id", "") or "")
    return m.group(1) if m else "unk"


def _orbit(item) -> int | None:
    o = item.properties.get("sat:relative_orbit")
    if o is not None:
        return int(o)
    m = re.search(r"_R(\d{3})_", item.properties.get("s2:product_uri", "") or "")
    return int(m.group(1)) if m else None


def _offset_removal(item, provider: str) -> float:
    """DN to subtract so the scene lands on offset-removed DN (reflectance*10000).

    ES serves COGs with the baseline>=04.00 BOA offset already taken out
    (`earthsearch:boa_offset_applied`); PC serves raw DNs, so post-baseline scenes
    still carry the +1000.
    """
    if provider == "earth-search":
        return 0.0 if item.properties.get("earthsearch:boa_offset_applied") else (
            1000.0 if _baseline(item) >= 4.0 else 0.0
        )
    return 1000.0 if _baseline(item) >= 4.0 else 0.0


def dedupe_items(items: list) -> list:
    """One item per (acquisition datetime, MGRS tile), keeping the highest processing
    baseline. The catalog holds reprocessed duplicates of the same acquisition; keeping
    both would median two different DN conventions into one date."""
    best: dict[tuple, object] = {}
    for it in items:
        key = (it.properties.get("datetime"), _tile(it))
        cur = best.get(key)
        if cur is None or _baseline(it) > _baseline(cur):
            best[key] = it
    return sorted(best.values(), key=lambda it: it.properties["datetime"])


def geobox_for(bbox: tuple[float, float, float, float], res: float = 10.0):
    """Fixed 10 m UTM grid for the AOI, so every year/tile pull lands on identical pixels."""
    from odc.geo.geobox import GeoBox
    from odc.geo.geom import box

    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
    return GeoBox.from_geopolygon(box(*bbox, crs="EPSG:4326"), resolution=res, crs=f"EPSG:{epsg}")


def _load_tile_year(items: list, gbox, tile: str, provider: str):
    """(arr[T, B+1, H, W] int16 offset-removed DN with SCL last, dates, per-date meta)."""
    import odc.stac

    bands = [*BANDS, "SCL"]
    load_bands = [ES_ASSET[b] for b in bands] if provider == "earth-search" else bands
    ds = odc.stac.load(
        items, bands=load_bands, geobox=gbox, groupby="solar_day",
        chunks={"x": 2048, "y": 2048}, fail_on_error=False, resampling="bilinear",
    )
    if provider == "earth-search":
        ds = ds.rename({ES_ASSET[b]: b for b in bands})
    ds = ds.compute()
    dates = ds["time"].dt.strftime("%Y-%m-%d").values.tolist()
    by_day: dict[str, list] = defaultdict(list)
    for it in items:
        by_day[it.properties["datetime"][:10]].append(it)
    arr = np.stack([ds[b].values.astype(np.int32) for b in BANDS], axis=1)  # [T,B,H,W]
    scl = ds["SCL"].values.astype(np.int32)[:, None]
    meta = []
    for i, d in enumerate(dates):
        day = by_day.get(d) or []
        it = day[0] if day else None
        base = max((_baseline(x) for x in day), default=0.0)
        off = max((_offset_removal(x, provider) for x in day), default=0.0)
        if off:
            arr[i] -= int(off)
        meta.append({
            "date": d, "tile": tile, "baseline": base, "offset_removed": off,
            "orbit": _orbit(it) if it else None,
            "platform": (it.properties.get("platform") if it else None),
            "cloud": float(it.properties.get("eo:cloud_cover", np.nan)) if it else np.nan,
            "sun_elev": float(it.properties.get("view:sun_elevation", np.nan)) if it else np.nan,
            "sun_az": float(it.properties.get("view:sun_azimuth", np.nan)) if it else np.nan,
        })
    out = np.concatenate([arr, scl], axis=1)
    np.clip(out, -1000, 20000, out=out)
    return out.astype(np.int16), np.array(dates), meta


def pull(name: str, bbox: tuple[float, float, float, float], start: str, end: str,
         max_cloud: int = 80, workers: int = 4, provider: str = "earth-search") -> Path:
    out_dir = CUBE_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    gbox = geobox_for(bbox)
    (out_dir / "grid.json").write_text(json.dumps({
        "name": name, "bbox": list(bbox), "start": start, "end": end, "provider": provider,
        "crs": str(gbox.crs), "transform": list(gbox.transform)[:6],
        "shape": [gbox.shape[0], gbox.shape[1]], "bands": BANDS + ["SCL"],
        "convention": "offset-removed DN; reflectance = DN/10000",
    }, indent=2))
    cat = _catalog(provider)
    years = list(range(int(start[:4]), int(end[:4]) + 1))
    from concurrent.futures import ThreadPoolExecutor

    def _one(job):
        year, tile, items = job
        f = out_dir / f"{tile}_{year}.npz"
        if f.exists():
            return f, 0
        try:
            arr, dates, meta = _load_tile_year(items, gbox, tile, provider)
        except Exception as e:  # noqa: BLE001 — one bad tile-year must not kill the pull
            log.warning("%s %s %s failed: %s", name, tile, year, e)
            return f, -1
        # np.savez_compressed appends .npz unless the name already ends in it, so the
        # temp name must keep the suffix last or the rename target won't exist.
        tmp = f.with_name(f.name.replace(".npz", ".tmp.npz"))
        np.savez_compressed(tmp, arr=arr, dates=dates, meta=json.dumps(meta))
        tmp.rename(f)
        return f, len(dates)

    jobs = []
    for year in years:
        y0, y1 = max(f"{year}-01-01", start), min(f"{year}-12-31", end)
        if y0 > y1:
            continue
        search = cat.search(collections=["sentinel-2-l2a"], bbox=bbox,
                            datetime=f"{y0}/{y1}", query={"eo:cloud_cover": {"lt": max_cloud}})
        items = dedupe_items(list(search.items()))
        by_tile: dict[str, list] = defaultdict(list)
        for it in items:
            by_tile[_tile(it)].append(it)
        for tile, tile_items in by_tile.items():
            if not (out_dir / f"{tile}_{year}.npz").exists():
                jobs.append((year, tile, tile_items))
        log.info("%s %d: %d items over tiles %s", name, year, len(items),
                 {k: len(v) for k, v in by_tile.items()})
    total = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f, n in ex.map(_one, jobs):
            if n > 0:
                total += n
                log.info("wrote %s (%d dates)", f.name, n)
    log.info("%s: %d new dates cached in %s", name, total, out_dir)
    return out_dir


def load_cube(name: str, min_valid_frac: float = 0.5):
    """Concatenate every cached tile-year into one time-sorted cube.

    Returns (arr[T,B,H,W] float32 reflectance with invalid pixels NaN, meta DataFrame,
    grid dict). Dates are kept per (tile, orbit) observation — the same solar day seen
    from two MGRS tiles stays two rows, since they carry different view geometry.
    """
    import pandas as pd

    out_dir = CUBE_ROOT / name
    grid = json.loads((out_dir / "grid.json").read_text())
    arrs, metas = [], []
    for f in sorted(out_dir.glob("*.npz")):
        z = np.load(f, allow_pickle=False)
        a = z["arr"]
        m = pd.DataFrame(json.loads(str(z["meta"])))
        arrs.append(a)
        metas.append(m)
    if not arrs:
        raise FileNotFoundError(f"no cached cube for {name}")
    arr = np.concatenate(arrs, axis=0)
    meta = pd.concat(metas, ignore_index=True)
    order = np.argsort(meta["date"].values, kind="stable")
    arr, meta = arr[order], meta.iloc[order].reset_index(drop=True)
    scl = arr[:, -1]
    refl = arr[:, :-1].astype(np.float32) / 10000.0
    valid = np.isin(scl, SCL_VALID) & (arr[:, :-1] != 0).all(axis=1)
    refl[~np.broadcast_to(valid[:, None], refl.shape)] = np.nan
    frac = valid.reshape(len(meta), -1).mean(axis=1)
    meta["valid_frac"] = frac
    keep = frac >= min_valid_frac
    log.info("%s: %d obs, %d kept (valid_frac >= %.2f), grid %s",
             name, len(meta), int(keep.sum()), min_valid_frac, grid["shape"])
    return refl[keep], meta[keep].reset_index(drop=True), grid


def boundary_bbox(path: Path, buffer_m: float) -> tuple[float, float, float, float]:
    g = gpd.read_file(path).to_crs("EPSG:4326")
    if buffer_m:
        utm = g.estimate_utm_crs()
        g = g.to_crs(utm).buffer(buffer_m).to_crs("EPSG:4326")
    b = g.total_bounds
    return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--name", required=True)
    p.add_argument("--boundary", type=Path)
    p.add_argument("--bbox", help="minx,miny,maxx,maxy (overrides --boundary)")
    p.add_argument("--buffer-m", type=float, default=250.0)
    p.add_argument("--start", default="2018-07-01")
    p.add_argument("--end", default="2026-07-20")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-cloud", type=int, default=80)
    p.add_argument("--provider", default="earth-search",
                   choices=["earth-search", "planetary-computer"])
    a = ap.parse_args()
    if a.cmd == "pull":
        if a.bbox:
            bbox = tuple(float(x) for x in a.bbox.split(","))
        elif a.boundary:
            bbox = boundary_bbox(a.boundary, a.buffer_m)
        else:
            ap.error("need --bbox or --boundary")
        log.info("bbox=%s", bbox)
        pull(a.name, bbox, a.start, a.end, a.max_cloud, a.workers, a.provider)


if __name__ == "__main__":
    main()
