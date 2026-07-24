"""Empirical glint-method validation on the Lahore calibration box's fully-mapped
ground truth — a genuinely different check from the country-scale 500-target study
(`scripts/glint_validate_pakistan.py`): every installation here is independently known
complete (docs/calibration-mapping-protocol.md Rule 1), so this isn't a fresh SAMPLE of
OSM-mapped installations, it's the ENTIRE population of a small area, letting us ask
"does glint's country-wide sensitivity curve replicate in one genuinely exhaustive
micro-area?" rather than "does glint work on a representative national sample?"

Efficient by construction: all 1,021 installations sit inside one 1km x 1km box, i.e.
one single 1-degree tile group for `glint.tile_scene_series_batch` — one STAC search,
shared per-scene band opens across every target, immediate read (no deferred re-read
of retained items), so this does NOT hit the SAS-token-staleness bug the tile-batched
country-scale revalidation did (docs/issues/glint-tile-batched-coverage.md) — that bug
needs either many groups (queued retries) or a keep_items=True + later separate read
pass; neither applies here.

Reuses `glint_validation.analyze_point` (spike detection + orientation-consistency fit)
unchanged on the batched output, which shares tile_scene_series_batch's exact column
schema with plain per-target `scene_series` — no new spike-detection logic.

Usage:
  .pixi/envs/default/bin/python scripts/glint_validate_calibration_box.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv import glint  # noqa: E402
from earthpv.capacity_calibration import BIN_LABELS, bin_index  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402
from glint_validation import analyze_point  # noqa: E402 (shared spike/fit logic)

log = logging.getLogger("glint_calib_box")

LABELS_FILE = Path("data/labels/lahore_calib_1km_overpass_solar.parquet")
OUT_DIR = DATA_DIR / "glint" / "calib_box"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BANDS = ("B03", "B08")
# All 1,021 targets share one 1-degree tile group, so a single tile_scene_series_batch
# call re-searches nothing between targets -- but the per-scene, per-target read loop
# (not parallelized across targets, only across scenes) took long enough for 1,021 at
# once that the group's SAS token (minted once at that one search) expired partway
# through: every target came back with an identical, truncated scene count (55 instead
# of the ~130-150 a 2-year Lahore lookback should have), confirmed by HTTP 403s in the
# log right before completion. Chunking re-searches (a fresh token) per chunk, trading
# a few redundant searches (cheap) for keeping each chunk's read volume -- and thus
# wall-time -- comfortably under the ~30-45 min token lifetime. Local mitigation only;
# does not touch earthpv.glint.
CHUNK_SIZE = 150

# Country-wide reference curve (results/glint_validation_pakistan/pakistan_stats_by_size.csv,
# the 500-target study) -- what we're checking this box's local rate against.
COUNTRY_PCT_VALIDATED = {
    "<100": 2.5, "100-500": 8.8, "500-1k": 16.2, "1k-5k": 30.6, "5k-50k": 29.3, ">50k": 26.1,
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    labels = gpd.read_parquet(LABELS_FILE).reset_index(drop=True)
    labels["pid"] = [f"box_{i:04d}" for i in range(len(labels))]
    labels["bucket"] = pd.Categorical.from_codes(
        bin_index(labels["area_m2"].to_numpy()), categories=list(BIN_LABELS)
    ).astype(str)
    reps = labels.geometry.representative_point()
    log.info("%d installations (all fully-mapped ground truth) -> one tile-batched pull", len(labels))
    log.info("bucket counts: %s", labels.bucket.value_counts().reindex(BIN_LABELS).to_dict())

    targets = pd.DataFrame({"pid": labels.pid, "geometry": labels.geometry,
                             "lon": reps.x, "lat": reps.y})
    n_chunks = -(-len(targets) // CHUNK_SIZE)  # ceil div
    series_by_pid: dict = {}
    for i in range(n_chunks):
        chunk = targets.iloc[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        log.info("chunk %d/%d: %d targets (fresh search + token)", i + 1, n_chunks, len(chunk))
        chunk_series = glint.tile_scene_series_batch(
            chunk, *DATE_RANGE, bands=BANDS, tile_deg=1.0, max_workers=8,
        )
        n_scenes = [len(d) for d in chunk_series.values() if not d.empty]
        log.info("chunk %d/%d done: scene-count median=%.0f min=%d max=%d",
                 i + 1, n_chunks, pd.Series(n_scenes).median() if n_scenes else 0,
                 min(n_scenes, default=0), max(n_scenes, default=0))
        series_by_pid.update(chunk_series)

    rows = []
    for r in labels.itertuples():
        d = series_by_pid.get(r.pid, pd.DataFrame())
        res, _ = analyze_point(d) if not d.empty else (
            dict(n_scenes=0, n_clear=0, n_spikes=0, fit_tilt=np.nan, fit_az=np.nan,
                 n_consistent=0, n_predicted=0, med_spike_amp=np.nan, base_B08=np.nan),
            d,
        )
        rows.append(dict(pid=r.pid, bucket=r.bucket, area_m2=r.area_m2, **res))
    s = pd.DataFrame(rows)
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    s.to_csv(OUT_DIR / "lahore_calib_box_glint_summary.csv", index=False)
    log.info("wrote %s (%d installations analyzed)", OUT_DIR / "lahore_calib_box_glint_summary.csv", len(s))

    def agg(g):
        return pd.Series({
            "n": len(g), "med_area_m2": g.area_m2.median(), "med_scenes": g.n_scenes.median(),
            "pct_detected": 100 * g.detected.mean(), "pct_validated": 100 * g.validated.mean(),
        })

    by_bucket = s.groupby("bucket", sort=False).apply(agg, include_groups=False).reindex(BIN_LABELS)
    by_bucket["country_pct_validated"] = [COUNTRY_PCT_VALIDATED.get(b, np.nan) for b in BIN_LABELS]
    by_bucket.round(2).to_csv(OUT_DIR / "lahore_calib_box_stats_by_size.csv")
    print("\n=== box-local glint validation vs. country-wide 500-target study ===")
    print(by_bucket.round(2).to_string())

    n_no_scenes = int((s.n_scenes == 0).sum())
    if n_no_scenes:
        log.warning("%d/%d installations had zero readable scenes (sub-pixel / read failures)",
                    n_no_scenes, len(s))


if __name__ == "__main__":
    main()
