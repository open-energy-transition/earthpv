"""Targeted top-up of the country2000 glint/orientation study, concentrated in the
latitude bands and provinces `scripts/glint_pose_by_region.py` found too thin to trust
(26-28N, 28-30N, 34-37N; Khyber Pakhtunkhwa, Balochistan, Gilgit-Baltistan, Azad
Kashmir) -- see `docs/methods/glint.md`'s "Detection rate, validation rate, and fitted
pose all shift with latitude" section for why.

**Not a fresh random national sample** -- a random draw from the SAME underrepresented
strata, excluding every `osm_id` country2000 already pulled (2,000 of them), same
source (`data/labels/pakistan_overpass_solar.parquet`), same fetch mechanism
(`glint.tile_scene_series_batch`, 150-target chunks, each its own fresh STAC
search+token -- the proven mitigation for the SAS-token-expiry failure mode documented
in `docs/issues/glint-tile-batched-coverage.md`), same date range and bands as
country2000, so the two pulls are directly poolable afterwards.

**Quotas are capped by what actually exists, not by what would look balanced.** The
underrepresented population itself is uneven: Khyber Pakhtunkhwa and Balochistan have
real remaining pools (444 and 162 undrawn OSM-confirmed installations respectively) and
can be meaningfully topped up; Azad Kashmir has only 8 installations in the entire
country and Gilgit-Baltistan only 2 -- both are taken as a full census (every remaining
one), not a sample, because there is nothing left to sample from. 26-28N is nearly
exhausted too (58 nationally, 27 already drawn by country2000) -- whatever is left is
taken, and no amount of re-sampling fixes a population this small.

Usage:
  .pixi/envs/default/bin/python scripts/glint_orientation_region_topup.py sample
  .pixi/envs/default/bin/python scripts/glint_orientation_region_topup.py pull
  .pixi/envs/default/bin/python scripts/glint_orientation_region_topup.py analyze
  .pixi/envs/default/bin/python scripts/glint_orientation_region_topup.py merge
"""

from __future__ import annotations

import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402
from glint_validation import analyze_point  # noqa: E402 (shared spike/fit logic)

log = logging.getLogger("glint_region_topup")
app = typer.Typer(pretty_exceptions_show_locals=False)

SOURCE_FILE = Path("data/labels/pakistan_overpass_solar.parquet")
REGIONS_FILE = Path("data/labels/pakistan_regions.parquet")
COUNTRY2000_TARGETS = DATA_DIR / "glint" / "country2000_targets.parquet"
COUNTRY2000_SUMMARY = DATA_DIR / "glint" / "country2000_summary.csv"
OUT_DIR = DATA_DIR / "glint" / "region_topup"
TARGETS_FILE = DATA_DIR / "glint" / "region_topup_targets.parquet"
SUMMARY_FILE = DATA_DIR / "glint" / "region_topup_summary.csv"
MERGED_TARGETS = DATA_DIR / "glint" / "pakistan_combined_targets.parquet"
MERGED_SUMMARY = DATA_DIR / "glint" / "pakistan_combined_summary.csv"

# Same window country2000 used -- the two pulls must be poolable afterwards.
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BANDS = ("B03", "B08")
CHUNK_SIZE = 150
TILE_DEG = 1.0

LAT_EDGES = [24, 26, 28, 30, 32, 34, 37]
LAT_LABELS = [f"{lo}-{hi}N" for lo, hi in zip(LAT_EDGES[:-1], LAT_EDGES[1:])]
UNDER_BANDS = {"26-28N", "28-30N", "34-37N"}
UNDER_PROVINCES = {"Khyber Pakhtunkhwa", "Balochistan", "Gilgit-Baltistan", "Azad Kashmir"}

# Caps, not exact targets -- `sample()` takes min(cap, pool). Provinces take priority
# over the residual latitude-band quotas below (a KP installation in 28-30N counts
# against the KP cap, not the band cap) so nothing is double-quota'd.
PROVINCE_CAP = {"Khyber Pakhtunkhwa": 120, "Balochistan": 80,
                "Gilgit-Baltistan": 10_000, "Azad Kashmir": 10_000}  # effectively "take all"
BAND_CAP = {"28-30N": 80, "34-37N": 80, "26-28N": 10_000}  # residual, after province picks removed


@app.command()
def sample(seed: int = typer.Option(43, help="Different seed from country2000's 42, deliberately")):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    g = gpd.read_parquet(SOURCE_FILE).to_crs(4326)
    g["lat"] = g.geometry.centroid.y
    g["lon"] = g.geometry.centroid.x

    already = gpd.read_parquet(COUNTRY2000_TARGETS)
    already_ids = set(already["osm_id"])
    g = g[~g["id"].isin(already_ids)].reset_index(drop=True)
    log.info("source pool after excluding %d already-drawn country2000 targets: %d", len(already_ids), len(g))

    g["lat_band"] = pd.cut(g["lat"], bins=LAT_EDGES, labels=LAT_LABELS)
    regions = gpd.read_parquet(REGIONS_FILE).to_crs(4326)
    pts = g.copy()
    pts["geometry"] = gpd.points_from_xy(pts.lon, pts.lat)
    joined = gpd.sjoin(pts, regions[["name", "geometry"]], predicate="within", how="left")
    joined = joined.drop(columns=["index_right"])

    picks = []
    picked_idx = set()

    for prov, cap in PROVINCE_CAP.items():
        pool = joined[(joined["name"] == prov) & (~joined.index.isin(picked_idx))]
        take = pool if len(pool) <= cap else pool.sample(cap, random_state=seed)
        log.info("province %-20s pool=%5d take=%3d", prov, len(pool), len(take))
        picks.append(take)
        picked_idx |= set(take.index)

    for band, cap in BAND_CAP.items():
        pool = joined[(joined["lat_band"].astype(str) == band) & (~joined.index.isin(picked_idx))]
        take = pool if len(pool) <= cap else pool.sample(cap, random_state=seed)
        log.info("lat band %-10s pool=%5d take=%3d (province-quota targets already removed)", band, len(pool), len(take))
        picks.append(take)
        picked_idx |= set(take.index)

    sel = pd.concat(picks).drop_duplicates(subset=["id"]).reset_index(drop=True)
    reps = sel.geometry.representative_point()
    out = gpd.GeoDataFrame({
        "pid": [f"rtop_{i:04d}" for i in range(len(sel))],
        "osm_id": sel["id"].values,
        "kind": sel["kind"].values,
        "placement": sel["placement"].values,
        "area_m2": sel["area_m2"].round(1).values,
        "province": sel["name"].values,
        "lat_band": sel["lat_band"].astype(str).values,
        "lon": reps.x.round(5).values,
        "lat": reps.y.round(5).values,
    }, geometry=sel.geometry.values, crs="EPSG:4326")
    DATA_DIR.joinpath("glint").mkdir(parents=True, exist_ok=True)
    out.to_parquet(TARGETS_FILE)
    log.info("wrote %s (%d targets total)", TARGETS_FILE, len(out))
    log.info("by province:\n%s", out["province"].value_counts(dropna=False).to_string())
    log.info("by lat band:\n%s", out["lat_band"].value_counts(dropna=False).to_string())


@app.command()
def pull(max_workers: int = typer.Option(8)):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = gpd.read_parquet(TARGETS_FILE)
    todo = targets[~targets.pid.map(lambda p: (OUT_DIR / f"{p}.parquet").exists())].reset_index(drop=True)
    log.info("%d targets total, %d to pull", len(targets), len(todo))
    if todo.empty:
        log.info("PULL_DONE (nothing to do)")
        return

    n_chunks = -(-len(todo) // CHUNK_SIZE)
    for i in range(n_chunks):
        chunk = todo.iloc[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        log.info("chunk %d/%d: %d targets (fresh search + token)", i + 1, n_chunks, len(chunk))
        try:
            chunk_series = glint.tile_scene_series_batch(
                chunk, *DATE_RANGE, bands=BANDS, tile_deg=TILE_DEG, max_workers=max_workers,
            )
        except Exception as e:  # noqa: BLE001 -- one bad chunk must not kill the whole pull
            log.warning("chunk %d/%d FAILED: %s -- will retry on next run", i + 1, n_chunks, e)
            continue
        n_scenes = [len(d) for d in chunk_series.values() if not d.empty]
        log.info("chunk %d/%d done: scene-count median=%.0f min=%d max=%d (%d/%d had scenes)",
                  i + 1, n_chunks, pd.Series(n_scenes).median() if n_scenes else 0,
                  min(n_scenes, default=0), max(n_scenes, default=0), len(n_scenes), len(chunk))
        for pid, df in chunk_series.items():
            (df if not df.empty else pd.DataFrame()).to_parquet(OUT_DIR / f"{pid}.parquet")
    log.info("PULL_DONE")


@app.command()
def analyze(tol_deg: float = 3.0):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    targets = gpd.read_parquet(TARGETS_FILE)
    rows = []
    for r in targets.itertuples():
        p = OUT_DIR / f"{r.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            res = dict(n_scenes=0, n_clear=0, n_spikes=0, fit_tilt=np.nan, fit_az=np.nan,
                       n_consistent=0, n_predicted=0, med_spike_amp=np.nan, base_B08=np.nan)
        else:
            res, _ = analyze_point(d, tol_deg)
        rows.append(dict(pid=r.pid, kind=r.kind, placement=r.placement,
                          province=r.province, lat_band=r.lat_band, area_m2=r.area_m2, **res))
    s = pd.DataFrame(rows)
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    s.to_csv(SUMMARY_FILE, index=False)
    log.info("per-target summary -> %s (%d/%d targets analyzed)", SUMMARY_FILE, len(s), len(targets))
    print(s.groupby("province", dropna=False).agg(
        n=("pid", "size"), pct_detected=("detected", "mean"), pct_validated=("validated", "mean"),
    ).to_string())
    print(s.groupby("lat_band", dropna=False).agg(
        n=("pid", "size"), pct_detected=("detected", "mean"), pct_validated=("validated", "mean"),
    ).to_string())


@app.command()
def merge():
    """Concatenate this top-up with country2000 into one combined pool, for
    `glint_pose_by_region.py` (or any successor) to re-analyze at full sample size."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    t0 = gpd.read_parquet(COUNTRY2000_TARGETS)[["pid", "osm_id", "kind", "placement", "area_m2", "lon", "lat", "geometry"]]
    t1 = gpd.read_parquet(TARGETS_FILE)[["pid", "osm_id", "kind", "placement", "area_m2", "lon", "lat", "geometry"]]
    targets = pd.concat([t0, t1], ignore_index=True)
    gpd.GeoDataFrame(targets, geometry="geometry", crs=4326).to_parquet(MERGED_TARGETS)

    s0 = pd.read_csv(COUNTRY2000_SUMMARY)
    s1 = pd.read_csv(SUMMARY_FILE)
    common = [c for c in s0.columns if c in s1.columns]
    summary = pd.concat([s0[common], s1[common]], ignore_index=True)
    summary.to_csv(MERGED_SUMMARY, index=False)
    log.info("wrote %s (%d targets) and %s (%d rows)", MERGED_TARGETS, len(targets), MERGED_SUMMARY, len(summary))


if __name__ == "__main__":
    app()
