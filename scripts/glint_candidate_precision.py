"""Glint sample of UNMAPPED model candidates -> capacity-atlas precision calibration.

The 500-target study (glint_validate_pakistan.py) measured the glint instrument's
sensitivity S_b on OSM-confirmed (true) installations. This script points the same
instrument at a stratified sample of *unmapped model candidates* — the population
whose real-PV fraction is unknown — so `earthpv calibrate-candidates` can invert the
observed validated rate v_b through S_b and the control false floor f into a
candidate precision per size bin: p_u(b) = clip((v_b - f) / (S_b - f), 0, 1).
See src/earthpv/capacity_calibration.py for the estimator this feeds.

Only bins where the instrument discriminates (>= 500 m2) are sampled. Mapped
candidates are excluded (their realness is already known — they enter the table via
the mapped fraction instead).

Resumable: each candidate's scene series lands in data/glint/<aoi>_cand/<pid>.parquet;
existing files are skipped on relaunch. Same threading etiquette as the study script
(compose may share this machine's Planetary Computer bandwidth; stay modest).

Usage:
  .pixi/envs/default/bin/python scripts/glint_candidate_precision.py sample --aoi pakistan \
      --pred-dir data/predictions_pk16085
  .pixi/envs/default/bin/python scripts/glint_candidate_precision.py pull --aoi pakistan
  .pixi/envs/default/bin/python scripts/glint_candidate_precision.py analyze --aoi pakistan
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
from earthpv.capacity_calibration import BIN_LABELS, bin_index  # noqa: E402
from earthpv.config import DATA_DIR, Settings  # noqa: E402
from earthpv.labels import resolve_aoi  # noqa: E402
from glint_validation import analyze_point  # noqa: E402  (shared spike/fit logic)

log = logging.getLogger("glint_cand")
app = typer.Typer(pretty_exceptions_show_locals=False)

OUT_DIR = DATA_DIR / "glint"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BANDS = ("B03", "B08")
TARGET_THREADS = 4
SCENE_THREADS = 6

# Only the bins the instrument can discriminate (S_b - f >= 0.05): >= 500 m2.
QUOTA = {"500-1k": 90, "1k-5k": 90, "5k-50k": 90, ">50k": 90}


def _targets_file(aoi: str) -> Path:
    return OUT_DIR / f"{aoi}_cand_targets.parquet"


def _series_dir(aoi: str) -> Path:
    return OUT_DIR / f"{aoi}_cand"


@app.command()
def sample(
    aoi: str = typer.Option("pakistan"),
    pred_dir: Path = typer.Option(Path("data/predictions_pk16085")),
    min_distance_m: float = typer.Option(100.0, help="Mapped-exclusion distance (match export)"),
    seed: int = typer.Option(42),
):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from earthpv.export import _load_mapped_reference, new_lead_mask

    cands = gpd.read_parquet(Path(pred_dir) / aoi / "candidates.parquet")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    mapped = _load_mapped_reference(aoi, cfg, settings)
    if mapped is None or mapped.empty:
        raise typer.Exit("no mapped OSM reference — cannot restrict to unmapped candidates")
    unmapped = cands[new_lead_mask(cands, mapped, min_distance_m=min_distance_m)]
    unmapped = unmapped.reset_index(drop=True)
    unmapped["bucket"] = pd.Categorical.from_codes(
        bin_index(unmapped["area_m2"].to_numpy()), categories=list(BIN_LABELS)
    ).astype(str)

    picks = []
    for bucket, quota in QUOTA.items():
        pool = unmapped[unmapped.bucket == bucket]
        take = pool if len(pool) <= quota else pool.sample(quota, random_state=seed)
        picks.append(take)
        log.info("%-8s pool=%5d take=%3d", bucket, len(pool), len(take))
    sel = pd.concat(picks).reset_index(drop=True)
    reproj = sel.geometry.to_crs("EPSG:6933").centroid.to_crs("EPSG:4326")
    out = gpd.GeoDataFrame({
        "pid": [f"{aoi}_c{i:04d}" for i in range(len(sel))],
        "area_m2": sel["area_m2"].round(1).values,
        "bucket": sel["bucket"].values,
        "lon": reproj.x.round(5).values,
        "lat": reproj.y.round(5).values,
    }, geometry=sel.geometry.values, crs="EPSG:4326")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(_targets_file(aoi))
    log.info("wrote %s (%d targets)", _targets_file(aoi), len(out))


def _pull_one(row, series_dir: Path) -> str:
    dst = series_dir / f"{row.pid}.parquet"
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
def pull(
    aoi: str = typer.Option("pakistan"),
    batch: bool = typer.Option(True, help="Tile-major batched fetch (--no-batch for the "
                                "original per-target path)"),
    tile_deg: float = typer.Option(1.0, help="Spatial bin size (degrees) for the batched fetch"),
    max_workers: int = typer.Option(6, help="Threads per tile group (batched) or scenes "
                                     "per target (per-target)"),
):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    tgts = gpd.read_parquet(_targets_file(aoi))
    series_dir = _series_dir(aoi)
    series_dir.mkdir(parents=True, exist_ok=True)
    todo = tgts[~tgts.pid.map(lambda p: (series_dir / f"{p}.parquet").exists())]
    log.info("%d targets total, %d to pull (batch=%s)", len(tgts), len(todo), batch)
    if todo.empty:
        log.info("PULL_DONE (nothing to do)")
        return

    if batch:
        targets = todo[["pid", "geometry", "lon", "lat"]]
        series_by_pid = glint.tile_scene_series_batch(
            targets, DATE_RANGE[0], DATE_RANGE[1], bands=BANDS, max_cloud=MAX_CLOUD,
            tile_deg=tile_deg, max_workers=max_workers,
        )
        for r in todo.itertuples():
            df = series_by_pid.get(r.pid, pd.DataFrame())
            df.to_parquet(series_dir / f"{r.pid}.parquet")
            log.info("%s: %d scenes", r.pid, len(df))
    else:
        done = 0
        with ThreadPoolExecutor(TARGET_THREADS) as ex:
            futs = {ex.submit(_pull_one, r, series_dir): r.pid for r in todo.itertuples()}
            for f in as_completed(futs):
                try:
                    msg = f.result()
                except Exception as e:  # noqa: BLE001 — one bad target must not kill the run
                    msg = f"{futs[f]} FAILED: {e}"
                done += 1
                log.info("[%d/%d] %s", done, len(todo), msg)
    log.info("PULL_DONE")


@app.command()
def analyze(aoi: str = typer.Option("pakistan"), tol_deg: float = 3.0):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tgts = gpd.read_parquet(_targets_file(aoi))
    series_dir = _series_dir(aoi)
    rows = []
    for r in tgts.itertuples():
        p = series_dir / f"{r.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            res = dict(n_scenes=0, n_clear=0, n_spikes=0, fit_tilt=np.nan, fit_az=np.nan,
                       n_consistent=0, n_predicted=0, med_spike_amp=np.nan, base_B08=np.nan)
        else:
            res, _ = analyze_point(d, tol_deg)
        rows.append(dict(pid=r.pid, bucket=r.bucket, area_m2=r.area_m2, **res))
    s = pd.DataFrame(rows)
    s["validated"] = s.n_consistent >= 2
    s.to_csv(OUT_DIR / f"{aoi}_cand_summary.csv", index=False)

    per_bin = s.groupby("bucket", sort=False).agg(
        n=("validated", "size"), n_validated=("validated", "sum")
    ).reindex(list(QUOTA)).dropna().astype(int).reset_index(names="bin_label")
    out = OUT_DIR / f"{aoi}_candidate_glint_sample.csv"
    per_bin.to_csv(out, index=False)
    print(per_bin.to_string(index=False))
    print(f"\nwrote {out} — feed it to:\n"
          f"  earthpv calibrate-candidates --aoi {aoi} --glint-sample {out}")


if __name__ == "__main__":
    app()
