"""Gallery for the glint-date experiment: do PV roofs actually light up on the predicted date?

Step 2 measured that a glint-date feature adds nothing to `roofclf`. A number like "+0.0003
AUC" is easy to distrust, so this renders the underlying imagery: for the Lahore buildings
where the hypothesis had its BEST chance -- confirmed PV, and the largest measured brightening
between the dry-season composite and the predicted glint window -- it crops both epochs at
the same place, on the same colour scale, with the mapped PV outlined.

If the idea worked, the bottom row would show panels flaring. Picking the best cases rather
than random ones is deliberate: a random sample would be a weaker test, because it could
always be answered with "you just did not pick the ones that glint".

Usage:
  .pixi/envs/default/bin/python scripts/glint_date_gallery.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import rasterio  # noqa: E402
import rasterio.warp  # noqa: E402
import rasterio.windows  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint, roofclf  # noqa: E402

log = logging.getLogger("glint_gallery")

QUADRAT = "lahore"
FEATURES = Path("results/glint_date_feature/lahore_glint_features.parquet")
DATES = Path("results/glint_date_feature/dates_used.json")
OUT_DIR = Path("docs/glint_examples_S2_glintdate")
RGB = ("B04", "B03", "B02")
PAD_M = 90.0
N_SHOW = 5


def read_rgb(item, provider: str, bounds_utm: tuple, crs) -> np.ndarray | None:
    """(H, W, 3) reflectance crop from one STAC item, in the given projected bounds."""
    chans = []
    for band in RGB:
        href = item.assets[glint._band_asset_key(band, provider)].href
        with rasterio.Env(**glint._GDAL_ENV), rasterio.open(href) as src:
            if src.crs != crs:
                return None
            win = rasterio.windows.from_bounds(*bounds_utm, transform=src.transform)
            arr = src.read(1, window=win, boundless=True, fill_value=0).astype("float32")
        chans.append((arr + glint._boa_offset(item, provider)) / roofclf.REFL_SCALE)
    if not chans or chans[0].size == 0:
        return None
    return np.stack(chans, axis=-1)


def stretch(img: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip((img - lo) / max(hi - lo, 1e-6), 0, 1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = json.loads(DATES.read_text())
    used = meta["dates"]
    if not used:
        raise SystemExit("no glint-window scene was usable; nothing to render")

    import pandas as pd

    f = pd.read_parquet(FEATURES)
    bu = gpd.read_parquet("data/roofclf/buildings.geoparquet")
    lah = bu[bu.quadrat == QUADRAT].reset_index(drop=True)
    lah = lah.join(f[["glint_max", "glint_excess", "glint_ratio"]], rsuffix="_f")

    # Best case for the hypothesis: confirmed PV, biggest measured brightening, and enough
    # roof to be more than one pixel so a reader can actually see the footprint.
    cand = lah[(lah.has_pv == 1) & (lah.roof_area_m2 > 150)].copy()
    cand = cand.sort_values("glint_excess", ascending=False).head(N_SHOW)
    log.info("showing %d buildings, glint_excess %.4f to %.4f", len(cand),
             cand.glint_excess.min(), cand.glint_excess.max())

    utm = cand.estimate_utm_crs()
    cand_utm = cand.to_crs(utm)

    items = glint._search_items_bbox(
        "planetary-computer", tuple(cand.total_bounds),
        __import__("datetime").datetime.fromisoformat("2024-07-01T00:00:00+00:00"),
        __import__("datetime").datetime.fromisoformat("2026-07-01T00:00:00+00:00"), 100)
    by_id = {it.id: it for it in items}
    glint_item = by_id.get(used[0]["item"])
    if glint_item is None:
        raise SystemExit(f"could not re-find the scene used in step 2: {used[0]['item']}")
    # Baseline: a clear scene well OUTSIDE the glint window, same season, for a like-for-like
    # visual. The composite roofclf actually reads is a median of many such scenes.
    glint_key = used[0]["key"][:8]
    # Nearest clear scene IN TIME to the glint date, same tile. A baseline a year away
    # would let ordinary change (new construction, a panel installed in between, a different
    # crop stage) masquerade as, or mask, the effect being tested.
    others = [it for it in items
              if it.properties.get("eo:cloud_cover", 100) < 5
              and it.id.split("_")[4] == glint_item.id.split("_")[4]
              and it.datetime.strftime("%Y%m%d") != glint_key]
    base_item = min(others, key=lambda it: abs(it.datetime - glint_item.datetime)) if others else None
    if base_item is None:
        raise SystemExit("no clear non-glint-window scene to compare against")
    log.info("glint-window scene %s vs baseline scene %s", glint_item.id, base_item.id)

    fig, axes = plt.subplots(2, len(cand_utm), figsize=(2.5 * len(cand_utm), 5.6))
    fig.patch.set_facecolor("#100d09")
    if len(cand_utm) == 1:
        axes = axes[:, None]
    for j, row in enumerate(cand_utm.itertuples()):
        c = row.geometry.centroid
        half = max(row.geometry.bounds[2] - row.geometry.bounds[0],
                   row.geometry.bounds[3] - row.geometry.bounds[1]) / 2 + PAD_M
        bounds = (c.x - half, c.y - half, c.x + half, c.y + half)
        imgs = [read_rgb(base_item, "planetary-computer", bounds, utm),
                read_rgb(glint_item, "planetary-computer", bounds, utm)]
        if any(im is None for im in imgs):
            log.warning("skipping building %d: unreadable", j)
            continue
        # ONE stretch across both epochs: the whole question is whether the second frame is
        # brighter, and per-frame normalisation would erase exactly that.
        lo = float(min(np.percentile(im, 2) for im in imgs))
        hi = float(max(np.percentile(im, 98) for im in imgs))
        for i, im in enumerate(imgs):
            ax = axes[i, j]
            ax.imshow(stretch(im, lo, hi), interpolation="nearest",
                      extent=(bounds[0], bounds[2], bounds[1], bounds[3]))
            gpd.GeoSeries([row.geometry], crs=utm).boundary.plot(
                ax=ax, color="#f5a623", linewidth=1.4)
            ax.set_xticks([])
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color("#3a2d16")
        axes[0, j].set_title(f"{row.roof_area_m2:.0f} m$^2$ roof\n"
                             f"{row.pv_area_true_m2:.0f} m$^2$ mapped PV",
                             color="#c9bda4", fontsize=8.5, pad=6)
    axes[0, 0].set_ylabel("ordinary clear date", color="#f7f1e6", fontsize=10)
    axes[1, 0].set_ylabel("predicted glint date", color="#f5a623", fontsize=10)
    fig.suptitle("Buildings with confirmed PV, on the date the geometry says they should glint",
                 color="#f7f1e6", fontsize=12.5, fontweight="bold", y=0.99)
    fig.text(0.5, 0.935, f"Same colour stretch in both rows. Baseline {base_item.datetime.date()}, "
                         f"glint window {glint_item.datetime.date()}. Mapped PV outlined.",
             ha="center", color="#c9bda4", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = OUT_DIR / "glint_date_vs_ordinary.png"
    fig.savefig(out, dpi=150, facecolor="#100d09")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
