"""Re-run the original 500-target Pakistan validation through the new tile-batched
fetch (and, for reference, the new self-referenced ring option) to confirm the
tile-major rewrite (`glint.tile_scene_series_batch`, see
docs/issues/glint-tile-batched-coverage.md) and the self-referenced spike criterion
(`glint.annotate_spikes`) still reproduce the original per-target `scene_series`
pull's results at full country scale — not just the small, single-tile clusters
(6 candidates, 8 spot-checked installations, one Lahore block) validated so far this
session.

This is also the first real stress test of tile-batching's *grouping*, not just its
per-target correctness: the original 500 targets are OSM-confirmed installations
spread across all of Pakistan, so 1-degree binning produces many small, scattered
groups (unlike the single-tile clusters tested so far) — a different regime the
grouping logic hasn't been exercised at before.

Compares against the original `data/glint/pakistan_summary.csv` (n_scenes/n_spikes/
n_consistent per target, produced by the old one-target-at-a-time
`scripts/glint_validate_pakistan.py`) target-by-target, and recomputes the per-size
-bucket rates for a direct side-by-side against `pakistan_stats_by_size.csv`'s
published numbers.

Usage:
  .pixi/envs/default/bin/python scripts/glint_revalidate_pakistan.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_revalidate")

# Same window `glint_validate_pakistan.py` used, so scene counts are directly comparable.
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
BUCKET_LABELS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
OUT_DIR = DATA_DIR / "glint"


def run() -> pd.DataFrame:
    targets = gpd.read_parquet(OUT_DIR / "pakistan_targets.parquet")
    old = pd.read_csv(OUT_DIR / "pakistan_summary.csv")

    tb = pd.DataFrame({
        "pid": targets.pid, "geometry": targets.geometry.to_numpy(),
        "lon": targets.lon.to_numpy(), "lat": targets.lat.to_numpy(),
    })
    log.info("tile-batched fetch: %d country-wide targets, %s to %s",
             len(tb), DATE_RANGE[0].date(), DATE_RANGE[1].date())
    series_by_pid = glint.tile_scene_series_batch(
        tb, DATE_RANGE[0], DATE_RANGE[1], tile_deg=1.0, max_workers=8,
    )
    log.info("fetch done: %d/%d targets returned at least one scene",
             sum(1 for s in series_by_pid.values() if not s.empty), len(tb))

    rows = []
    for r in targets.itertuples():
        series = series_by_pid.get(r.pid, pd.DataFrame())
        default = glint.spike_fit(series) if not series.empty else \
            dict(n_scenes=0, n_spikes=0, n_consistent=0)
        selfref = glint.spike_fit(series, self_referenced=True) if not series.empty else \
            dict(n_scenes=0, n_spikes=0, n_consistent=0)
        rows.append(dict(
            pid=r.pid, bucket=r.bucket, area_m2=r.area_m2,
            new_n_scenes=default["n_scenes"], new_n_spikes=default["n_spikes"],
            new_n_consistent=default["n_consistent"],
            selfref_n_spikes=selfref["n_spikes"], selfref_n_consistent=selfref["n_consistent"],
        ))
    new = pd.DataFrame(rows)
    new["new_detected"] = new.new_n_spikes >= 1
    new["new_validated"] = new.new_n_consistent >= 2
    new["selfref_detected"] = new.selfref_n_spikes >= 1
    new["selfref_validated"] = new.selfref_n_consistent >= 2

    out = old[["pid", "detected", "validated", "n_scenes", "n_spikes", "n_consistent"]].merge(
        new, on="pid", how="outer", suffixes=("_old", "")
    )
    out.to_csv(OUT_DIR / "pakistan_revalidate_tilebatch.csv", index=False)
    return out


def report(out: pd.DataFrame) -> None:
    both = out.dropna(subset=["detected", "new_detected"])
    print(f"\n=== Tile-batched re-fetch vs original per-target pull: {len(both)} targets "
          f"compared (of {len(out)} total) ===\n")

    agree_d = (both.detected == both.new_detected).mean()
    agree_v = (both.validated == both.new_validated).mean()
    print("Per-target agreement (old per-target fetch vs new tile-batched fetch, "
          "default spatial-ring criterion):")
    print(f"  detected flag matches: {agree_d:.3f}   validated flag matches: {agree_v:.3f}")
    scene_diff = (both.n_scenes - both.new_n_scenes).abs()
    print(f"  n_scenes abs diff: mean={scene_diff.mean():.2f} max={scene_diff.max():.0f} "
          "(small diffs expected -- tile-batch's bbox search can find a scene a point search "
          "missed, or vice versa near a tile seam; large diffs would flag a real regression)")

    disagree = both[both.detected != both.new_detected]
    if not disagree.empty:
        print(f"\n{len(disagree)} targets where the detected flag flipped:")
        print(disagree[["pid", "bucket", "area_m2", "n_scenes", "n_spikes", "new_n_scenes",
                        "new_n_spikes"]].to_string(index=False))

    print("\n=== Per-bucket rates: original study vs tile-batched re-fetch "
          "(default vs self-referenced) ===")
    def bucket_rates(df, det_col, val_col):
        g = df.groupby("bucket", observed=True).agg(
            n=("pid", "size"), pct_detected=(det_col, "mean"), pct_validated=(val_col, "mean")
        )
        g[["pct_detected", "pct_validated"]] *= 100
        return g.reindex(BUCKET_LABELS)

    orig = bucket_rates(both, "detected", "validated")
    new_default = bucket_rates(out, "new_detected", "new_validated")
    new_selfref = bucket_rates(out, "selfref_detected", "selfref_validated")
    comparison = orig[["n", "pct_detected", "pct_validated"]].join(
        new_default[["pct_detected", "pct_validated"]], rsuffix="_new_default"
    ).join(new_selfref[["pct_detected", "pct_validated"]], rsuffix="_new_selfref")
    print(comparison.round(1).to_string())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    report(run())
