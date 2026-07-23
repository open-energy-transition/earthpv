"""Annual NDVI check for new leads -> green-field false-positive veto.

The countryside FP diagnosis (src/earthpv/vegetation.py docstring): green-field
leads are NOT green in the dry-season composite the model read — they were dark
fallow/harvested/flooded soil. The discriminating physics is the vegetation
cycle, which two dry-season medians undersample badly. This script samples a
full year of Sentinel-2 scenes per lead (the glint pipeline's per-target
fetcher, B04/B08) and reports each lead's year-long NDVI distribution: a p95
above ~0.4 means the footprint greened up at some point — a crop, never PV.
Residual cloud biases NDVI down, so the veto is conservative under cloud.

Resumable: each lead's scene series lands in data/veg/<aoi>/<candidate_id>.parquet;
existing files are skipped on relaunch. Same threading etiquette as the glint
scripts (modest, this machine shares Planetary Computer bandwidth).

Usage:
  .pixi/envs/default/bin/python scripts/veg_annual_ndvi.py pull --aoi pakistan \
      --pred-dir data/predictions_pk16085 [--limit 30]
  .pixi/envs/default/bin/python scripts/veg_annual_ndvi.py analyze --aoi pakistan \
      --pred-dir data/predictions_pk16085
  # then:
  #   earthpv export --aoi pakistan --pred-dir data/predictions_pk16085 \
  #       --exclude-mapped --min-distance-m 100 --epoch-clean --veg-max-ndvi 0.35 \
  #       --annual-ndvi data/predictions_pk16085/pakistan/annual_ndvi.parquet
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("veg_ndvi")
app = typer.Typer(pretty_exceptions_show_locals=False)

BANDS = ("B04", "B08")
MAX_CLOUD = 70
TARGET_THREADS = 4
SCENE_THREADS = 6
MONSOON_MONTHS = (6, 7, 8, 9)  # kharif greening window — must be inside the date range


def _series_dir(aoi: str) -> Path:
    return DATA_DIR / "veg" / aoi


def _leads(aoi: str, pred_dir: Path, leads_file: Path | None) -> gpd.GeoDataFrame:
    path = leads_file or Path(pred_dir) / aoi / f"{aoi}_pv_new_leads.geojson"
    leads = gpd.read_file(path)
    if "candidate_id" not in leads.columns:
        raise SystemExit(f"{path} has no candidate_id — rerun `earthpv export` first")
    return leads


@app.command()
def pull(
    aoi: str = typer.Option("pakistan"),
    pred_dir: Path = typer.Option(Path("data/predictions_pk16085")),
    leads_file: Path = typer.Option(
        None, help="Leads to sample (default <pred_dir>/<aoi>/<aoi>_pv_new_leads.geojson). "
        "Point at the _clean file to skip already-vetoed leads."
    ),
    days: int = typer.Option(365, help="Lookback window (must span a monsoon)"),
    limit: int = typer.Option(0, help="Cap leads for a smoke run (0 = all)"),
):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    leads = _leads(aoi, pred_dir, leads_file)
    if limit:
        leads = leads.head(limit)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    series_dir = _series_dir(aoi)
    series_dir.mkdir(parents=True, exist_ok=True)
    todo = [r for r in leads.itertuples()
            if not (series_dir / f"{r.candidate_id}.parquet").exists()]
    log.info("%d/%d leads still to pull (%s .. %s)", len(todo), len(leads),
             start.date(), end.date())

    def _one(row) -> str:
        dst = series_dir / f"{row.candidate_id}.parquet"
        df = glint.scene_series(
            row.geometry, start, end,
            bands=BANDS, max_cloud=MAX_CLOUD, n_threads=SCENE_THREADS,
        )
        # Persist even when empty so resume doesn't retry a no-scene lead forever.
        df.to_parquet(dst)
        return f"{row.candidate_id}: {len(df)} scenes"

    done = 0
    with ThreadPoolExecutor(TARGET_THREADS) as ex:
        futs = [ex.submit(_one, r) for r in todo]
        for f in as_completed(futs):
            try:
                msg = f.result()
                done += 1
                if done % 25 == 0 or done == len(todo):
                    log.info("[%d/%d] %s", done, len(todo), msg)
            except Exception as e:  # noqa: BLE001 — one lead must not kill the pull
                log.warning("lead failed: %s", e)
    log.info("pull complete: %d series under %s", done, series_dir)


@app.command()
def analyze(
    aoi: str = typer.Option("pakistan"),
    pred_dir: Path = typer.Option(Path("data/predictions_pk16085")),
    leads_file: Path = typer.Option(None),
):
    """Per-lead year-long NDVI stats -> <pred_dir>/<aoi>/annual_ndvi.parquet."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    leads = _leads(aoi, pred_dir, leads_file)
    series_dir = _series_dir(aoi)
    rows = []
    for r in leads.itertuples():
        p = series_dir / f"{r.candidate_id}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty or not {"p98_B04", "p98_B08"} <= set(d.columns):
            rows.append({"candidate_id": r.candidate_id, "n_clear": 0})
            continue
        red = d["p98_B04"].to_numpy(float)
        nir = d["p98_B08"].to_numpy(float)
        ok = np.isfinite(red) & np.isfinite(nir) & (red + nir > 0)
        if not ok.any():
            rows.append({"candidate_id": r.candidate_id, "n_clear": 0})
            continue
        ndvi = (nir[ok] - red[ok]) / (nir[ok] + red[ok])
        months = pd.to_datetime(d["time"]).dt.month.to_numpy()[ok]
        monsoon = np.isin(months, MONSOON_MONTHS)
        rows.append({
            "candidate_id": r.candidate_id,
            "n_clear": int(ok.sum()),
            "n_monsoon": int(monsoon.sum()),
            "ndvi_p95": round(float(np.percentile(ndvi, 95)), 3),
            "ndvi_max": round(float(ndvi.max()), 3),
            "ndvi_med": round(float(np.median(ndvi)), 3),
            "ndvi_monsoon_p95": (
                round(float(np.percentile(ndvi[monsoon], 95)), 3) if monsoon.any() else None
            ),
        })
    out = pd.DataFrame(rows)
    dst = Path(pred_dir) / aoi / "annual_ndvi.parquet"
    out.to_parquet(dst)
    sampled = out[out.n_clear > 0]
    log.info("wrote %s: %d leads analyzed (%d with scenes)", dst, len(out), len(sampled))
    if len(sampled):
        for thr in (0.3, 0.4, 0.5):
            log.info("  p95 NDVI > %.1f: %d leads (%.1f%%)", thr,
                     int((sampled.ndvi_p95 > thr).sum()),
                     100 * (sampled.ndvi_p95 > thr).mean())
        log.info("feed it to: earthpv export --aoi %s --annual-ndvi %s ...", aoi, dst)


if __name__ == "__main__":
    app()
