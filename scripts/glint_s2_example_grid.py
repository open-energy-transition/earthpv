"""Build a 3x6 example grid of real Sentinel-2 glint spikes, three per size bucket.

Companion to `docs/glint_examples_HR/` (high-resolution ESRI World Imagery screenshots
showing the same physical phenomenon - the blown-out white/rainbow sheen off a PV
panel's glass when the sun reflects straight into the sensor). This script renders the
Sentinel-2-resolution analogue: for each of the 6 size buckets in the 500-target
Pakistan validation study, picks up to 3 of the most strongly-validated real
installations (highest `n_consistent`), finds each one's brightest CLOUD-FREE spike
date, then fetches a true-color (B04/B03/B02) crop for that exact date - the frame
where the glint actually happened.

**Cloud screening, added because a prior version of this grid showed one cloud, not a
glint.** The actual bug was in this script, not in the shared glint module: the previous
version picked its example date as the single brightest `p98_B08 - ring_B08` reading over
a target's *entire* raw scene series, bypassing `annotate_spikes`'s own `spike` gate
(bright relative to that target's own clear-scene baseline **and** a stable, non-bright
annulus) entirely -- so an ungated bright/uneven cloud edge could win outright even though
the same series's properly-gated `spike` rows (the ones `n_consistent`/`validated` are
actually computed from) would have excluded it. This version sources candidate dates only
from `annotate_spikes`'s own `spike` column, the same gated set the rest of this project's
glint validation trusts, which turned out to already be enough: every one of the 18 dates
picked when this was rebuilt passed on the first try. On top of that, as defense in depth
(the cached series still predates the per-pixel SCL cloud veto added to `annotate_spikes`
2026-08-11, so its own `cloud_free` column is not available and the `spike` gate is running
geometry/reflectance heuristics alone): for each candidate date this script resolves the
actual Sentinel-2 scene and reads the SCL band live (`glint._scl_cloud_row`), same
mechanism and threshold (`glint.MAX_RING_CLOUD_FRAC`) production glint scoring now uses,
before accepting it. A candidate whose every spike date fails that live check is dropped
entirely and the next-ranked installation in that bucket takes its place.

With only 2 and 7 validated installations in the `<100` and `100-500` m² buckets
respectively (out of the 500-target sample), 3 *distinct* installations are not always
available -- where they aren't, a second clean spike date from an already-used
installation fills the remaining slot rather than leaving it blank, and the caption says
so explicitly (`repeat`) rather than implying a third distinct example exists.

Output: `docs/glint_examples_S2/sentinel2_glint_grid.png`.

Usage:
  .pixi/envs/default/bin/python scripts/glint_s2_example_grid.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no $DISPLAY on this machine

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
import rasterio.features  # noqa: E402
import rasterio.warp  # noqa: E402
import rasterio.windows  # noqa: E402
from matplotlib import pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_s2_example_grid")

BUCKETS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
N_PER_BUCKET = 3
RGB_BANDS = ("B04", "B03", "B02")
SERIES_BANDS = ("B03", "B08")  # matches the cached columns glint_validate_pakistan.py wrote
PAD_M = 120.0  # context padding around the installation footprint
MAX_SPIKE_DATES_TRIED = 6  # per target, brightest-first, before giving up on it
OUT_DIR = Path("docs/glint_examples_S2")

# `pk_0429` and `pk_0491` are the same real-world installation at Hub, Balochistan
# (centroids ~5 m apart) scored as two separate targets in the 500-target study -- a
# duplicate-geometry bug in `data/glint/pakistan_targets.parquet` upstream of this
# script, not something to fix here. Both previously filled the `>50k` column's top two
# slots with what is visually the same crop. Worse, that crop's brightest clean-by-SCL
# spike (2025-11-26) sits right next to the Hub Power Station, whose smoke plume drifts
# over part of the target on that date -- a confound the SCL cloud gate doesn't catch
# (industrial smoke isn't classified as cloud) and that makes a poor example of PV
# glint regardless of duplication. Excluded by pid, not by geometry, so this doesn't
# mask a genuinely distinct future duplicate -- see the spatial-proximity check in
# `select_bucket` for that.
EXCLUDED_PIDS = {"pk_0429", "pk_0491"}
# Two candidates within this distance of each other are treated as the same physical
# installation for gallery-selection purposes, even under different pids (see
# EXCLUDED_PIDS above for why a pid-only distinctness check missed exactly this case).
DEDUP_DISTANCE_DEG = 0.005  # ~500 m at Pakistan's latitudes


def candidate_pool() -> pd.DataFrame:
    """Every validated installation, ranked strongest-first within each bucket."""
    summary = pd.read_csv(DATA_DIR / "glint" / "pakistan_summary.csv")
    targets = gpd.read_parquet(DATA_DIR / "glint" / "pakistan_targets.parquet")
    merged = summary.merge(targets[["pid", "geometry"]], on="pid")
    validated = merged[merged.validated & ~merged.pid.isin(EXCLUDED_PIDS)].copy()
    validated["bucket"] = pd.Categorical(validated["bucket"].astype(str), categories=BUCKETS, ordered=True)
    return validated.sort_values(["bucket", "n_consistent", "n_spikes"], ascending=[True, False, False])


def ranked_spike_dates(pid: str) -> list:
    """This target's own flagged spike dates, brightest first -- reruns the shared,
    tested `annotate_spikes` on its cached series rather than re-deriving "bright" by
    hand, so ranking here means exactly what it means everywhere else in this project.
    """
    series = pd.read_parquet(DATA_DIR / "glint" / "pakistan" / f"{pid}.parquet")
    d = glint.annotate_spikes(series, bands=SERIES_BANDS)
    if d.empty or not d.spike.any():
        return []
    sp = d[d.spike].copy()
    sp["amp"] = sp["a_B08"] - sp["r_B08"]
    return sp.sort_values("amp", ascending=False)["time"].tolist()


def resolve_item(geometry, when):
    """The Sentinel-2 scene closest to `when` covering `geometry`, or `(None, None)`."""
    lon, lat = geometry.centroid.x, geometry.centroid.y
    start, end = when - pd.Timedelta(hours=12), when + pd.Timedelta(hours=12)
    items = glint._search_items("planetary-computer", lon, lat, start, end, max_cloud=100)
    provider = "planetary-computer"
    if not items:
        items = glint._search_items("earth-search", lon, lat, start, end, max_cloud=100)
        provider = "earth-search"
    if not items:
        return None, None
    item = min(items, key=lambda it: abs((it.datetime - when.to_pydatetime()).total_seconds()))
    return item, provider


def is_clean(item, geometry, provider: str) -> bool:
    """True if this scene's annulus around `geometry` reads clear of cloud in the SCL
    band -- the same live check `annotate_spikes` runs in production, applied here
    because the cached series this script's candidates come from predates it."""
    lon, lat = geometry.centroid.x, geometry.centroid.y
    row = glint._scl_cloud_row(item, geometry, lon, lat, provider)
    ring = row["scl_ring_cloud_frac"]
    if np.isnan(ring):
        log.warning("SCL unreadable for %s, treating as unknown-not-clean for this grid", item.id)
        return False
    return ring <= glint.MAX_RING_CLOUD_FRAC


def read_rgb(item, geometry, provider: str) -> np.ndarray:
    """True-color crop covering `geometry` + PAD_M from an already-resolved scene."""
    bands = []
    for band in RGB_BANDS:
        href = item.assets[glint._band_asset_key(band, provider)].href
        with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
            geom_native = gpd.GeoSeries([geometry], crs="EPSG:4326").to_crs(src.crs).iloc[0]
            minx, miny, maxx, maxy = geom_native.buffer(PAD_M).bounds
            win = rasterio.windows.from_bounds(minx, miny, maxx, maxy, src.transform)
            win = win.round_offsets().round_lengths()
            arr = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
            arr += glint._boa_offset(item, provider)
        bands.append(arr)
    rgb = np.stack(bands, axis=-1)
    out = np.zeros_like(rgb)
    for c in range(3):
        lo, hi = np.percentile(rgb[..., c], [2, 98])
        out[..., c] = np.clip((rgb[..., c] - lo) / max(hi - lo, 1.0), 0, 1)
    return out


def pick_clean_example(row, already_used: dict) -> tuple | None:
    """The brightest cloud-free (date, item, provider) for one candidate installation,
    skipping dates this target has already contributed to the grid."""
    used = already_used.get(row.pid, set())
    for when in ranked_spike_dates(row.pid)[:MAX_SPIKE_DATES_TRIED]:
        if when in used:
            continue
        item, provider = resolve_item(row.geometry, when)
        if item is None:
            continue
        if is_clean(item, row.geometry, provider):
            return when, item, provider
        log.info("  %s: spike on %s is cloud-contaminated, trying next date", row.pid, when)
    return None


def _near_any_chosen(pid: str, geometry, chosen: list[dict], threshold_deg: float) -> bool:
    """True if `geometry`'s centroid sits within `threshold_deg` of an already-chosen
    example's centroid FROM A DIFFERENT pid -- the same real-world installation can be
    stored as two distinct pids (see `EXCLUDED_PIDS`'s comment for the case this
    generalizes), so a pid-only distinctness check alone can still seat the same site
    twice. Excludes `chosen` entries with this candidate's OWN pid, or the intentional
    same-pid "repeat" fallback (a second clean date on an already-chosen installation,
    when the bucket has too few distinct ones) would always measure zero distance to
    itself and never be allowed to run."""
    cx, cy = geometry.centroid.x, geometry.centroid.y
    return any(
        ((cx - c["geometry"].centroid.x) ** 2 + (cy - c["geometry"].centroid.y) ** 2) ** 0.5 < threshold_deg
        for c in chosen if c["pid"] != pid
    )


def select_bucket(pool: pd.DataFrame, bucket: str, want: int = N_PER_BUCKET) -> list[dict]:
    """Up to `want` clean examples for one bucket: distinct installations first,
    falling back to a second clean date on an already-chosen one only if the bucket's
    own validated pool is too thin to fill every slot distinctly."""
    candidates = list(pool[pool.bucket == bucket].itertuples())
    chosen: list[dict] = []
    used_dates: dict[str, set] = {}

    def try_fill(allow_repeat: bool):
        for row in candidates:
            if len(chosen) >= want:
                return
            if not allow_repeat and row.pid in used_dates:
                continue
            if _near_any_chosen(row.pid, row.geometry, chosen, DEDUP_DISTANCE_DEG):
                log.info("  %s: within %.0f m of an already-chosen example, skipping",
                          row.pid, DEDUP_DISTANCE_DEG * 111_000)
                continue
            found = pick_clean_example(row, used_dates)
            if found is None:
                log.info("  %s: no cloud-free spike found in its own series, skipping", row.pid)
                continue
            when, item, provider = found
            used_dates.setdefault(row.pid, set()).add(when)
            chosen.append({
                "pid": row.pid, "bucket": bucket, "area_m2": row.area_m2,
                "n_consistent": row.n_consistent, "geometry": row.geometry,
                "when": when, "item": item, "provider": provider,
                "repeat": allow_repeat,
            })

    try_fill(allow_repeat=False)
    if len(chosen) < want:
        try_fill(allow_repeat=True)
    return chosen


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    pool = candidate_pool()
    log.info("validated pool sizes:\n%s", pool.groupby("bucket").size())

    examples: list[dict] = []
    for bucket in BUCKETS:
        log.info("bucket %s:", bucket)
        picked = select_bucket(pool, bucket)
        if len(picked) < N_PER_BUCKET:
            log.warning("  only %d/%d clean examples available for %s",
                        len(picked), N_PER_BUCKET, bucket)
        for p in picked:
            log.info("  %s (%.0f m2): clean spike on %s, n_consistent=%d%s",
                      p["pid"], p["area_m2"], p["when"], p["n_consistent"],
                      " [repeat installation]" if p["repeat"] else "")
        examples.extend(picked)

    fig, axes = plt.subplots(N_PER_BUCKET, len(BUCKETS), figsize=(24, 11.5))
    for bucket_i, bucket in enumerate(BUCKETS):
        rows = [e for e in examples if e["bucket"] == bucket]
        for rank_i in range(N_PER_BUCKET):
            ax = axes[rank_i, bucket_i]
            if rank_i >= len(rows):
                ax.set_visible(False)
                continue
            ex = rows[rank_i]
            rgb = read_rgb(ex["item"], ex["geometry"], ex["provider"])
            ax.imshow(rgb)
            tag = " (repeat)" if ex["repeat"] else ""
            lon, lat = ex["geometry"].centroid.x, ex["geometry"].centroid.y
            title = (
                f"{bucket} m² - actual {ex['area_m2']:.0f} m²\n"
                f"{ex['when']:%Y-%m-%d}  n_consistent={ex['n_consistent']}{tag}\n"
                f"{lat:.4f}°N {lon:.4f}°E"
            )
            ax.set_title(title, fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])

    fig.suptitle(
        "Solar glint at Sentinel-2 resolution - real OSM-confirmed Pakistan installations,\n"
        "true colour (B04/B03/B02), each cropped to its own brightest cloud-screened spike date "
        "(one column per size bucket, strongest example on top)",
        fontsize=12,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "sentinel2_glint_grid.png"
    fig.savefig(out_path, dpi=150)
    log.info("wrote %s", out_path)


if __name__ == "__main__":
    main()
