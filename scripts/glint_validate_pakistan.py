"""Country-scale empirical validation of the glint method on OSM-confirmed Pakistan PV.

Samples N installations from the user-supplied fresh OSM export
(data/osm_pk_solar_160726.geojson), stratified across area buckets so small rooftop
generators and utility-scale plants are all represented, then pulls ~2 years of
per-scene statistics per target (same machinery as scripts/glint_validation.py) and
reports how often the glint method "validates" an installation per size bucket.

Validation criterion per target (matching glint_validation.analyze_point):
  - detected: >= 1 spike (bright in B03+B08 inside the polygon, annulus stable)
  - validated: a single panel orientation (tilt, az) explains >= 2 spike dates
    via the specular condition (fit_best_orientation), i.e. the spikes are
    geometrically consistent with a fixed glass plane, not random brightening.

Resumable: each target's scene series lands in data/glint/pakistan/<pid>.parquet;
existing files are skipped on relaunch.

Usage:
  python scripts/glint_validate_pakistan.py sample --n 500
  python scripts/glint_validate_pakistan.py pull
  python scripts/glint_validate_pakistan.py analyze
"""

from __future__ import annotations

import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from earthpv.labels import geodesic_area_m2  # noqa: E402
from glint_validation import analyze_point  # noqa: E402  (shared spike/fit logic)

log = logging.getLogger("glint_pk")
app = typer.Typer(pretty_exceptions_show_locals=False)

OSM_FILE = DATA_DIR / "osm_pk_solar_160726.geojson"
OUT_DIR = DATA_DIR / "glint"
SERIES_DIR = OUT_DIR / "pakistan"
TARGETS_FILE = OUT_DIR / "pakistan_targets.parquet"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BANDS = ("B03", "B08")
# Compose (6 workers) shares this machine's PC bandwidth; stay modest.
TARGET_THREADS = 4
SCENE_THREADS = 6

BINS = [0, 100, 500, 1000, 5000, 50000, np.inf]
LABELS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
# >50k has only ~93 features country-wide -> take them all; spread the rest evenly.
QUOTA = {"<100": 80, "100-500": 80, "500-1k": 80, "1k-5k": 85, "5k-50k": 82, ">50k": 93}


@app.command()
def sample(n: int = typer.Option(500), seed: int = typer.Option(42)):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    g = gpd.read_file(OSM_FILE)
    g["kind"] = np.where(g["generator:source"].notna(), "generator", "plant")
    g["area_m2"] = [geodesic_area_m2(geom) for geom in g.geometry]
    g["bucket"] = pd.cut(g.area_m2, bins=BINS, labels=LABELS)
    picks = []
    for bucket, quota in QUOTA.items():
        pool = g[g.bucket == bucket]
        take = pool if len(pool) <= quota else pool.sample(quota, random_state=seed)
        picks.append(take)
        log.info("%-8s pool=%5d take=%3d", bucket, len(pool), len(take))
    sel = pd.concat(picks)
    reproj = sel.geometry.to_crs("EPSG:6933").centroid.to_crs("EPSG:4326")
    out = gpd.GeoDataFrame({
        "pid": [f"pk_{i:04d}" for i in range(len(sel))],
        "osm_id": sel["id"].values,
        "kind": sel["kind"].values,
        "area_m2": sel["area_m2"].round(1).values,
        "bucket": sel["bucket"].astype(str).values,
        "lon": reproj.x.round(5).values,
        "lat": reproj.y.round(5).values,
    }, geometry=sel.geometry.values, crs="EPSG:4326")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(TARGETS_FILE)
    log.info("wrote %s (%d targets)", TARGETS_FILE, len(out))


def _pull_one(row) -> str:
    dst = SERIES_DIR / f"{row.pid}.parquet"
    if dst.exists():
        return "skip"
    df = glint.scene_series(
        row.geometry, DATE_RANGE[0], DATE_RANGE[1],
        bands=BANDS, max_cloud=MAX_CLOUD, n_threads=SCENE_THREADS,
    )
    if df.empty:
        # Persist an empty marker so resume doesn't retry a no-scene target forever.
        df = pd.DataFrame()
    df.to_parquet(dst)
    return f"{row.pid}: {len(df)} scenes"


@app.command()
def pull():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
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
    log.info("PULL_DONE")


@app.command()
def analyze(tol_deg: float = 3.0):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tgts = gpd.read_parquet(TARGETS_FILE)
    rows = []
    for r in tgts.itertuples():
        p = SERIES_DIR / f"{r.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            res = dict(n_scenes=0, n_clear=0, n_spikes=0, fit_tilt=np.nan, fit_az=np.nan,
                       n_consistent=0, n_predicted=0, med_spike_amp=np.nan, base_B08=np.nan)
        else:
            res, _ = analyze_point(d, tol_deg)
        rows.append(dict(pid=r.pid, kind=r.kind, bucket=r.bucket, area_m2=r.area_m2, **res))
    s = pd.DataFrame(rows)
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    s.to_csv(OUT_DIR / "pakistan_summary.csv", index=False)
    log.info("per-target summary -> %s (%d targets analyzed)", OUT_DIR / "pakistan_summary.csv", len(s))

    def agg(g):
        return pd.Series({
            "n": len(g),
            "med_area_m2": g.area_m2.median(),
            "med_scenes": g.n_scenes.median(),
            "med_clear": g.n_clear.median(),
            "pct_detected": 100 * g.detected.mean(),
            "pct_validated": 100 * g.validated.mean(),
            "med_spikes_when_detected": g.loc[g.detected, "n_spikes"].median(),
            "med_amp_when_detected": g.loc[g.detected, "med_spike_amp"].median(),
        })

    by_bucket = s.groupby("bucket", sort=False).apply(agg, include_groups=False).reindex(LABELS)
    by_kind = s.groupby("kind").apply(agg, include_groups=False)
    by_bucket.round(1).to_csv(OUT_DIR / "pakistan_stats_by_size.csv")
    by_kind.round(1).to_csv(OUT_DIR / "pakistan_stats_by_kind.csv")
    print("\n=== by size bucket (m^2) ===")
    print(by_bucket.round(1).to_string())
    print("\n=== by kind ===")
    print(by_kind.round(1).to_string())


if __name__ == "__main__":
    app()
