"""Resumable glint scene-series pull for the density-improvement targets
(`glint_density_targets.py`'s missed/control samples). Same per-target machinery as
`glint_validate_pakistan.py`, parameterized by region so it works for `lahore` and
`germany` (or any future region) against `data/glint/<region>_density_targets.parquet`.

Usage:
  .pixi/envs/default/bin/python scripts/glint_density_pull.py lahore
  .pixi/envs/default/bin/python scripts/glint_density_pull.py germany
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


@app.command()
def main(region: str = typer.Argument(..., help="lahore | germany | <region>")):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    targets_file = DATA_DIR / "glint" / f"{region}_density_targets.parquet"
    tgts = gpd.read_parquet(targets_file)
    series_dir = DATA_DIR / "glint" / f"{region}_density"
    series_dir.mkdir(parents=True, exist_ok=True)
    todo = [r for r in tgts.itertuples() if not (series_dir / f"{r.pid}.parquet").exists()]
    log.info("%s: %d targets total, %d to pull", region, len(tgts), len(todo))
    done = 0
    with ThreadPoolExecutor(TARGET_THREADS) as ex:
        futs = {ex.submit(_pull_one, r, series_dir): r.pid for r in todo}
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
