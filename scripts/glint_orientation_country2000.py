"""Country-scale glint tilt/orientation study, 2000 OSM-confirmed Pakistan
installations -- a 4x-larger, faster re-run of `scripts/glint_validate_pakistan.py`'s
500-target study (results/glint_validation_pakistan/), same methodology
(`glint_validation.analyze_point`, tol_deg=3, single default spike criterion) so the
two are directly comparable, but with two changes:

1. **Source**: `data/labels/pakistan_overpass_solar.parquet` (16,085 features, already
   classified rooftop/ground via `overpass.build_overpass_labels`) instead of the raw
   `osm_pk_solar_160726.geojson` -- same underlying OSM pull, already has `placement`,
   letting this study report a rooftop-vs-ground split the original never had.
2. **Fetch**: chunked `glint.tile_scene_series_batch` (CHUNK_SIZE targets per call,
   each call its own fresh STAC search+token) instead of the original's slow
   one-target-at-a-time `scene_series` loop -- the same mitigation
   `scripts/glint_validate_calibration_box.py` proved out today for the SAS-token-
   staleness bug (docs/issues/glint-tile-batched-coverage.md): restarting the whole
   batched call every ~150 targets keeps each call's wall-clock comfortably under a
   token's ~30-45 min lifetime, unlike one huge unchunked country-scale call (lost a
   median 63 scenes/target, 48% lost more than half -- see
   [[earthpv-glint-tile-batching]]). Per-target results are cached to
   data/glint/country2000/<pid>.parquet as each chunk completes, so a kill/restart
   resumes from the last finished chunk instead of losing everything.

Usage:
  .pixi/envs/default/bin/python scripts/glint_orientation_country2000.py sample
  .pixi/envs/default/bin/python scripts/glint_orientation_country2000.py pull
  .pixi/envs/default/bin/python scripts/glint_orientation_country2000.py analyze
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

log = logging.getLogger("glint_country2000")
app = typer.Typer(pretty_exceptions_show_locals=False)

SOURCE_FILE = Path("data/labels/pakistan_overpass_solar.parquet")
OUT_DIR = DATA_DIR / "glint" / "country2000"
TARGETS_FILE = DATA_DIR / "glint" / "country2000_targets.parquet"
SUMMARY_FILE = DATA_DIR / "glint" / "country2000_summary.csv"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BANDS = ("B03", "B08")
CHUNK_SIZE = 150  # see module docstring: matches the proven calibration-box fix
TILE_DEG = 1.0

BINS = [0, 100, 500, 1000, 5000, 50000, np.inf]
LABELS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
# Population-capped stratified quota for n≈2000 (vs. n=500's 80/80/80/85/82/93):
# >50k only has 93 features country-wide, so its shortfall vs an even 1/6 split is
# redistributed across the other five buckets rather than left unfilled.
QUOTA = {"<100": 382, "100-500": 382, "500-1k": 381, "1k-5k": 381, "5k-50k": 381, ">50k": 93}


@app.command()
def sample(seed: int = typer.Option(42)):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    g = gpd.read_parquet(SOURCE_FILE)
    g["bucket"] = pd.cut(g.area_m2, bins=BINS, labels=LABELS)
    picks = []
    for bucket, quota in QUOTA.items():
        pool = g[g.bucket == bucket]
        take = pool if len(pool) <= quota else pool.sample(quota, random_state=seed)
        picks.append(take)
        log.info("%-8s pool=%5d take=%3d", bucket, len(pool), len(take))
    sel = pd.concat(picks).reset_index(drop=True)
    reps = sel.geometry.representative_point()
    out = gpd.GeoDataFrame({
        "pid": [f"c2k_{i:04d}" for i in range(len(sel))],
        "osm_id": sel["id"].values,
        "kind": sel["kind"].values,
        "placement": sel["placement"].values,
        "area_m2": sel["area_m2"].round(1).values,
        "bucket": sel["bucket"].astype(str).values,
        "lon": reps.x.round(5).values,
        "lat": reps.y.round(5).values,
    }, geometry=sel.geometry.values, crs="EPSG:4326")
    DATA_DIR.joinpath("glint").mkdir(parents=True, exist_ok=True)
    out.to_parquet(TARGETS_FILE)
    log.info("wrote %s (%d targets)", TARGETS_FILE, len(out))


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

    n_chunks = -(-len(todo) // CHUNK_SIZE)  # ceil div
    for i in range(n_chunks):
        chunk = todo.iloc[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        log.info("chunk %d/%d: %d targets (fresh search + token)", i + 1, n_chunks, len(chunk))
        try:
            chunk_series = glint.tile_scene_series_batch(
                chunk, *DATE_RANGE, bands=BANDS, tile_deg=TILE_DEG, max_workers=max_workers,
            )
        except Exception as e:  # noqa: BLE001 — one bad chunk must not kill the whole pull
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
                          bucket=r.bucket, area_m2=r.area_m2, **res))
    s = pd.DataFrame(rows)
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    s.to_csv(SUMMARY_FILE, index=False)
    log.info("per-target summary -> %s (%d/%d targets analyzed)", SUMMARY_FILE, len(s), len(targets))

    def agg(g):
        return pd.Series({
            "n": len(g), "med_area_m2": g.area_m2.median(), "med_scenes": g.n_scenes.median(),
            "pct_detected": 100 * g.detected.mean(), "pct_validated": 100 * g.validated.mean(),
            "med_spikes_when_detected": g.loc[g.detected, "n_spikes"].median(),
        })

    by_bucket = s.groupby("bucket", sort=False).apply(agg, include_groups=False).reindex(LABELS)
    by_kind = s.groupby("kind").apply(agg, include_groups=False)
    by_place = s.groupby("placement").apply(agg, include_groups=False)
    out_dir = DATA_DIR / "glint"
    by_bucket.round(1).to_csv(out_dir / "country2000_stats_by_size.csv")
    by_kind.round(1).to_csv(out_dir / "country2000_stats_by_kind.csv")
    by_place.round(1).to_csv(out_dir / "country2000_stats_by_placement.csv")
    print("\n=== by size bucket (m^2) ===")
    print(by_bucket.round(1).to_string())
    print("\n=== by kind ===")
    print(by_kind.round(1).to_string())
    print("\n=== by placement ===")
    print(by_place.round(1).to_string())


if __name__ == "__main__":
    app()
