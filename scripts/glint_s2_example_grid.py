"""Build a 2x3 example grid of real Sentinel-2 glint spikes, one per size bucket.

Companion to `docs/glint_examples_HR/` (high-resolution ESRI World Imagery screenshots
showing the same physical phenomenon — the blown-out white/rainbow sheen off a PV
panel's glass when the sun reflects straight into the sensor). This script renders the
Sentinel-2-resolution analogue: for each of the 6 size buckets in the 500-target
Pakistan validation study, picks the most strongly-validated real installation
(highest `n_consistent`), finds its brightest spike date from the already-cached
per-scene series (`data/glint/pakistan/<pid>.parquet`, no new network calls for date
selection), then fetches a true-color (B04/B03/B02) crop for that exact date — the
frame where the glint actually happened.

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
RGB_BANDS = ("B04", "B03", "B02")
PAD_M = 120.0  # context padding around the installation footprint
OUT_DIR = Path("docs/glint_examples_S2")


def pick_examples() -> pd.DataFrame:
    """Strongest validated installation (highest n_consistent) per size bucket."""
    summary = pd.read_csv(DATA_DIR / "glint" / "pakistan_summary.csv")
    targets = gpd.read_parquet(DATA_DIR / "glint" / "pakistan_targets.parquet")
    merged = summary.merge(targets[["pid", "geometry"]], on="pid")
    validated = merged[merged.validated].copy()
    validated["bucket"] = validated["bucket"].astype(str)
    best = (
        validated.sort_values(["n_consistent", "n_spikes"], ascending=False)
        .groupby("bucket", as_index=False)
        .first()
    )
    best["bucket"] = pd.Categorical(best["bucket"], categories=BUCKETS, ordered=True)
    return best.sort_values("bucket").reset_index(drop=True)


def spike_date(pid: str):
    series = pd.read_parquet(DATA_DIR / "glint" / "pakistan" / f"{pid}.parquet")
    amp = series["p98_B08"] - series["ring_B08"]
    return series.loc[amp.idxmax(), "time"]


def fetch_rgb_crop(geometry, when) -> np.ndarray | None:
    """True-color crop covering `geometry` + PAD_M, from the scene closest to `when`."""
    lon, lat = geometry.centroid.x, geometry.centroid.y
    start, end = when - pd.Timedelta(hours=12), when + pd.Timedelta(hours=12)
    items = glint._search_items("planetary-computer", lon, lat, start, end, max_cloud=100)
    provider = "planetary-computer"
    if not items:
        items = glint._search_items("earth-search", lon, lat, start, end, max_cloud=100)
        provider = "earth-search"
    if not items:
        log.warning("no scene found near %s", when)
        return None
    item = min(items, key=lambda it: abs((it.datetime - when.to_pydatetime()).total_seconds()))

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

    # Simple percentile stretch per channel for display (raw DN, ~0-10000+ range).
    out = np.zeros_like(rgb)
    for c in range(3):
        lo, hi = np.percentile(rgb[..., c], [2, 98])
        out[..., c] = np.clip((rgb[..., c] - lo) / max(hi - lo, 1.0), 0, 1)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    examples = pick_examples()
    log.info("examples:\n%s", examples[["pid", "bucket", "area_m2", "n_consistent"]])

    fig, axes = plt.subplots(2, 3, figsize=(13.5, 9))
    for ax, row in zip(axes.flat, examples.itertuples()):
        when = spike_date(row.pid)
        log.info("%s (%s, %.0f m2): spike on %s", row.pid, row.bucket, row.area_m2, when)
        rgb = fetch_rgb_crop(row.geometry, when)
        if rgb is None:
            ax.set_visible(False)
            continue
        ax.imshow(rgb)
        ax.set_title(f"{row.bucket} m² bucket — actual {row.area_m2:.0f} m²\n"
                     f"{when:%Y-%m-%d}  n_consistent={row.n_consistent}", fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle(
        "Solar glint at Sentinel-2 resolution — real OSM-confirmed Pakistan installations,\n"
        "true colour (B04/B03/B02), each cropped to its own brightest spike date",
        fontsize=12,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "sentinel2_glint_grid.png"
    fig.savefig(out_path, dpi=150)
    log.info("wrote %s", out_path)


if __name__ == "__main__":
    main()
