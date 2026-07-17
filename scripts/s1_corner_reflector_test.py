"""Empirical test: does Sentinel-1 show a PV corner-reflector signature, and is it
denser/more persistent than Sentinel-2's optical glint spikes?

Physical hypothesis (see conversation): a PV row (tilted panel + flat ground beneath)
forms a dihedral corner reflector. Unlike optical glint -- which needs the panel's
specular reflection of the SUN to hit the sensor, a narrow date-dependent alignment --
SAR is active (illuminates itself), so the relevant alignment is between the row's own
geometry and the SAR's *fixed* orbit/look geometry (ascending vs descending pass,
~2 discrete headings, not a season-varying continuum). If real, that predicts:
  (a) enhancement should be far less sparse than optical spikes (which fire on ~1-4%
      of dates) -- geometry that's favorable stays favorable on every pass;
  (b) enhancement should differ between ascending and descending orbits (the two
      passes look from very different headings), a clean, checkable asymmetry;
  (c) enhancement strength should correlate with how the panel's *row axis* (derived
      from the optical fit's panel azimuth +/- 90 deg -- standard racking has rows
      running perpendicular to the panel's tilt-facing direction) sits relative to
      the satellite's track heading -- though which alignment (parallel vs
      perpendicular to track) is favorable is exactly what this test should reveal
      empirically rather than assume.

Uses the same targets as the glint validation study (already-fitted tilt/az, so we
know each target's implied row axis) and Planetary Computer's `sentinel-1-rtc`
collection (analysis-ready gamma0 backscatter, no extra calibration needed).

Usage:
  .pixi/envs/default/bin/python scripts/s1_corner_reflector_test.py pull
  .pixi/envs/default/bin/python scripts/s1_corner_reflector_test.py analyze
"""

from __future__ import annotations

import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.warp
import rasterio.windows
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("s1_test")
app = typer.Typer(pretty_exceptions_show_locals=False)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
OUT_DIR = DATA_DIR / "s1_test"
SERIES_DIR = OUT_DIR / "series"
TARGETS_FILE = OUT_DIR / "targets.parquet"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
N_TARGETS = 24
TARGET_THREADS = 3
SCENE_THREADS = 5
_GDAL_ENV = dict(GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2", VSI_CACHE="TRUE")


@lru_cache(maxsize=1)
def _catalog():
    import planetary_computer
    import pystac_client

    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


@app.command()
def sample(n: int = N_TARGETS, seed: int = 0):
    """Pick a diverse sample of already-validated targets: spread across fitted
    azimuth (so the implied row axis varies) and skewed toward larger/higher-
    n_consistent installations (more pixels -> less speckle noise per read)."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = pd.read_csv(DATA_DIR / "glint" / "pakistan_summary.csv")
    tgts = gpd.read_parquet(DATA_DIR / "glint" / "pakistan_targets.parquet")
    v = s[s.n_consistent >= 2].merge(tgts[["pid", "geometry"]], on="pid")
    v = gpd.GeoDataFrame(v, geometry="geometry", crs="EPSG:4326")
    v["az_bin"] = pd.cut(v.fit_az, bins=np.arange(75, 190, 15))
    rng = np.random.default_rng(seed)
    picks = []
    for _, grp in v.groupby("az_bin", observed=True):
        if grp.empty:
            continue
        take = grp.sort_values("n_consistent", ascending=False).head(3)
        picks.append(take)
    out = pd.concat(picks).head(n).reset_index(drop=True)
    n_bins = out.az_bin.nunique()
    out = out.drop(columns=["az_bin"])
    out = gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")
    out["row_axis"] = (out.fit_az + 90) % 180  # standard racking: row long-axis ~ perp to tilt-facing
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(TARGETS_FILE)
    log.info("sampled %d targets across %d azimuth bins -> %s", len(out), n_bins, TARGETS_FILE)
    log.info("fit_az range in sample: %.1f - %.1f", out.fit_az.min(), out.fit_az.max())


def _polygon_vs_annulus(href: str, geometry, lon: float, lat: float) -> tuple[float, float, int]:
    with rasterio.Env(**_GDAL_ENV), rasterio.open(href) as src:
        xs, ys = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
        row, col = src.index(xs[0], ys[0])
        geom_native = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(src.crs).iloc[0]
        half_extent = max(
            geom_native.bounds[2] - geom_native.bounds[0],
            geom_native.bounds[3] - geom_native.bounds[1],
        ) / 2
        r_px = int(np.clip(half_extent / 10 + 10, 16, 80))
        win = rasterio.windows.Window(col - r_px, row - r_px, 2 * r_px, 2 * r_px)
        arr = src.read(1, window=win, boundless=True, fill_value=src.nodata).astype("float32")
        wt = src.window_transform(win)
        inside = rasterio.features.geometry_mask(
            [geom_native], arr.shape, wt, invert=True, all_touched=False
        )
        if not inside.any():
            inside = rasterio.features.geometry_mask(
                [geom_native], arr.shape, wt, invert=True, all_touched=True
            )
        ring = ~rasterio.features.geometry_mask(
            [geom_native.buffer(50)], arr.shape, wt, invert=True
        )
    nodata = src.nodata
    arr[arr == nodata] = np.nan
    inside_v, ring_v = arr[inside], arr[ring & ~inside]
    if np.isfinite(inside_v).sum() < 3 or np.isfinite(ring_v).sum() < 20:
        return np.nan, np.nan, 0
    return (
        float(np.nanpercentile(inside_v, 90)),
        float(np.nanmedian(ring_v)),
        int(np.isfinite(inside_v).sum()),
    )


def _scene_row(item, geometry, lon: float, lat: float) -> dict | None:
    try:
        row = dict(
            time=item.datetime, orbit_state=item.properties.get("sat:orbit_state"),
            rel_orbit=item.properties.get("sat:relative_orbit"),
        )
        for pol in ("vv", "vh"):
            if pol not in item.assets:
                return None
            inside, ring, npx = _polygon_vs_annulus(item.assets[pol].href, geometry, lon, lat)
            row[f"{pol}_inside"], row[f"{pol}_ring"], row[f"{pol}_npx"] = inside, ring, npx
        return row
    except Exception as e:  # noqa: BLE001 — per-scene failures shouldn't kill the pull
        log.debug("scene %s failed: %s", item.id, e)
        return None


def _s1_series(geometry, start: datetime, end: datetime, n_threads: int) -> pd.DataFrame:
    lon, lat = geometry.centroid.x, geometry.centroid.y
    search = _catalog().search(
        collections=["sentinel-1-rtc"],
        intersects={"type": "Point", "coordinates": [lon, lat]},
        datetime=f"{start.date()}/{end.date()}",
    )
    items = list(search.items())
    rows = []
    with ThreadPoolExecutor(n_threads) as ex:
        futs = [ex.submit(_scene_row, it, geometry, lon, lat) for it in items]
        for f in as_completed(futs):
            r = f.result()
            if r:
                rows.append(r)
    return pd.DataFrame(rows).sort_values("time") if rows else pd.DataFrame()


def _pull_one(row) -> str:
    dst = SERIES_DIR / f"{row.pid}.parquet"
    if dst.exists():
        return "skip"
    df = _s1_series(row.geometry, DATE_RANGE[0], DATE_RANGE[1], SCENE_THREADS)
    df.to_parquet(dst)
    return f"{row.pid}: {len(df)} S1 scenes"


@app.command()
def pull():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    if not TARGETS_FILE.exists():
        sample()
    tgts = gpd.read_parquet(TARGETS_FILE)
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    todo = [r for r in tgts.itertuples() if not (SERIES_DIR / f"{r.pid}.parquet").exists()]
    log.info("%d targets total, %d to pull", len(tgts), len(todo))
    done = 0
    with ThreadPoolExecutor(TARGET_THREADS) as ex:
        futs = {ex.submit(_pull_one, r): r.pid for r in todo}
        for f in as_completed(futs):
            try:
                msg = f.result()
            except Exception as e:  # noqa: BLE001 — one bad target must not kill the run
                msg = f"{futs[f]} FAILED: {e}"
            done += 1
            log.info("[%d/%d] %s", done, len(todo), msg)
    log.info("S1_PULL_DONE")


def _enhancement_rate(d: pd.DataFrame, pol: str, k: float = 3.0) -> dict:
    """Fraction of scenes where in-polygon backscatter is a robust outlier above its
    own clear-baseline (median + k*MAD of the ring-normalized ratio), mirroring the
    optical spike criterion's structure but for linear-power SAR backscatter."""
    d = d.dropna(subset=[f"{pol}_inside", f"{pol}_ring"])
    if len(d) < 5:
        return dict(n=len(d), rate=np.nan)
    ratio = d[f"{pol}_inside"] / d[f"{pol}_ring"].clip(lower=1e-6)
    med = ratio.median()
    mad = max(1.4826 * (ratio - med).abs().median(), 0.05)
    enhanced = ratio > med + k * mad
    return dict(n=len(d), rate=float(enhanced.mean()), median_ratio=float(med))


@app.command()
def analyze():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tgts = gpd.read_parquet(TARGETS_FILE)
    rows = []
    for r in tgts.itertuples():
        p = SERIES_DIR / f"{r.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            continue
        rec = dict(pid=r.pid, fit_az=r.fit_az, row_axis=r.row_axis, n_scenes=len(d))
        for pol in ("vv", "vh"):
            overall = _enhancement_rate(d, pol)
            rec[f"{pol}_rate_all"] = overall["rate"]
            for state in ("ascending", "descending"):
                sub = d[d.orbit_state == state]
                res = _enhancement_rate(sub, pol)
                rec[f"{pol}_rate_{state}"] = res["rate"]
                rec[f"{pol}_n_{state}"] = res["n"]
        rows.append(rec)
    s = pd.DataFrame(rows)
    s.to_csv(OUT_DIR / "s1_summary.csv", index=False)
    log.info("wrote %s (%d targets)", OUT_DIR / "s1_summary.csv", len(s))

    print("\n=== per-target enhancement rate (fraction of scenes flagged elevated) ===")
    cols = ["pid", "fit_az", "row_axis", "n_scenes", "vv_rate_all", "vv_rate_ascending",
            "vv_rate_descending", "vh_rate_all"]
    print(s[cols].round(3).to_string(index=False))

    print(f"\nmedian VV enhancement rate across all scenes: {s.vv_rate_all.median()*100:.1f}%")
    print(f"median VH enhancement rate across all scenes: {s.vh_rate_all.median()*100:.1f}%")
    asc = s.vv_rate_ascending.dropna()
    desc = s.vv_rate_descending.dropna()
    print(f"ascending vs descending VV rate (paired targets): "
          f"asc median={asc.median()*100:.1f}%  desc median={desc.median()*100:.1f}%")
    diff = (s.vv_rate_ascending - s.vv_rate_descending).dropna()
    print(f"per-target |ascending - descending| gap: median={diff.abs().median()*100:.1f} pts, "
          f"max={diff.abs().max()*100:.1f} pts")


if __name__ == "__main__":
    app()
