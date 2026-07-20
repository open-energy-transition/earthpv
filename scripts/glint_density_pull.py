"""Resumable glint scene-series pull for the density-improvement targets
(`glint_density_targets.py`'s missed/control samples, or `glint_spike_rate_estimator.py
sample`'s stratified building sample). Parameterized by region so it works for `lahore`,
`germany`, or a spike-rate-estimator region against
`data/glint/<region>_density_targets.parquet`.

Fetched tile-major by default (`glint.tile_scene_series_batch`): one STAC search + one
set of asset opens per `--tile-deg`-degree spatial bin, shared by every target in it,
instead of one of each per target — the actual cost driver once a region has more than a
few dozen targets (see docs/issues/glint-tile-batched-coverage.md). `--no-batch` restores
the original one-target-at-a-time path (kept for comparison/debugging, not because the
batched path drops coverage — validated byte-identical per-scene stats on a real cluster,
see glint.py's `tile_scene_series_batch` docstring).

Usage:
  .pixi/envs/default/bin/python scripts/glint_density_pull.py lahore
  .pixi/envs/default/bin/python scripts/glint_density_pull.py germany
  .pixi/envs/default/bin/python scripts/glint_density_pull.py lahore_rate --tile-deg 0.5
"""

from __future__ import annotations

import logging
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_density_pull")
app = typer.Typer(pretty_exceptions_show_locals=False)

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BANDS = ("B03", "B08")
TARGET_THREADS = 4
SCENE_THREADS = 6


def _pull_one(row, series_dir: Path) -> str:
    dst = series_dir / f"{row.pid}.parquet"
    if dst.exists():
        return "skip"
    df = glint.scene_series(
        row.geometry, DATE_RANGE[0], DATE_RANGE[1],
        bands=BANDS, max_cloud=MAX_CLOUD, n_threads=SCENE_THREADS,
    )
    if df.empty:
        df = pd.DataFrame()
    df.to_parquet(dst)
    return f"{row.pid} ({row.kind}): {len(df)} scenes"


def _pull_batch(todo: gpd.GeoDataFrame, series_dir: Path, tile_deg: float, max_workers: int) -> None:
    targets = pd.DataFrame({
        "pid": todo.pid.to_numpy(),
        "geometry": todo.geometry.to_numpy(),
        "lon": todo.geometry.centroid.x.to_numpy(),
        "lat": todo.geometry.centroid.y.to_numpy(),
    })
    series_by_pid = glint.tile_scene_series_batch(
        targets, DATE_RANGE[0], DATE_RANGE[1], bands=BANDS, max_cloud=MAX_CLOUD,
        tile_deg=tile_deg, max_workers=max_workers,
    )
    for row in todo.itertuples():
        df = series_by_pid.get(row.pid, pd.DataFrame())
        (series_dir / f"{row.pid}.parquet").parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(series_dir / f"{row.pid}.parquet")
        log.info("%s (%s): %d scenes", row.pid, getattr(row, "kind", "?"), len(df))


@app.command()
def main(
    region: str = typer.Argument(..., help="lahore | germany | <region>"),
    batch: bool = typer.Option(True, help="Tile-major batched fetch (--no-batch for the "
                                "original per-target path)"),
    tile_deg: float = typer.Option(1.0, help="Spatial bin size (degrees) for the batched fetch"),
    max_workers: int = typer.Option(6, help="Threads per tile group (batched) or scenes "
                                     "per target (per-target)"),
):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    targets_file = DATA_DIR / "glint" / f"{region}_density_targets.parquet"
    tgts = gpd.read_parquet(targets_file)
    series_dir = DATA_DIR / "glint" / f"{region}_density"
    series_dir.mkdir(parents=True, exist_ok=True)
    todo = tgts[~tgts.pid.map(lambda p: (series_dir / f"{p}.parquet").exists())]
    log.info("%s: %d targets total, %d to pull (batch=%s)", region, len(tgts), len(todo), batch)
    if todo.empty:
        log.info("DENSITY_PULL_DONE region=%s (nothing to do)", region)
        return

    if batch:
        _pull_batch(todo, series_dir, tile_deg, max_workers)
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
    log.info("DENSITY_PULL_DONE region=%s", region)


if __name__ == "__main__":
    app()
