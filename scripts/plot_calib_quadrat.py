"""Three-panel figure for one calibration quadrat: what is there, what the detector sees,
what the per-building classifier sees.

Written for the Rule-1-complete coastal Karachi box, which is the clearest illustration of
the sub-floor blindness the density docs describe: 165 mapped installations, median 86 m2,
98.8% below the 400 m2 detection floor, and a segmentation raster that predicts *zero* PV
area over the box's buildings.

Panels, left to right:
  1. Sentinel-2 dry-season composite, true colour, at native 10 m -- deliberately not
     upsampled, because the point is how little a 86 m2 array is at this resolution.
     Mapped PV outlined in cyan, building footprints in thin grey.
  2. The segmentation model's PV probability on the same extent and colour scale as panel 3.
  3. The per-building classifier's out-of-fold probability, one colour per footprint.
     Out-of-fold means every building was scored by a model that never saw this quadrat.

Reads gitignored `data/` and writes a tracked PNG to `results/`, the same arrangement as
plot_pv_density_maps.py -> build_docs_figures.crop_hero_map: CI cannot regenerate a
data-dependent raster, so the tracked PNG is the interface to the docs.

    pixi run python scripts/plot_calib_quadrat.py [--quadrat <stem>] [--out <path>]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402

from earthpv.local_source import CompositeIndex  # noqa: E402
from earthpv.roofclf import _raster_for, _read_prob, load_quadrat  # noqa: E402

log = logging.getLogger(__name__)

SERIF = ["Iowan Old Style", "Palatino Linotype", "Palatino", "Georgia", "serif"]
SANS = ["DejaVu Sans", "system-ui", "sans-serif"]
INK, DIM, RULE = "#1A1A1A", "#555555", "#CCCCCC"
PV_EDGE = "#00C2B8"       # mapped ground truth
BLD_EDGE = "#8A8A8A"
CMAP = "magma"


def _rgb(arr: np.ndarray) -> np.ndarray:
    """True-colour composite from the 10-band stack, percentile-stretched per band."""
    rgb = np.stack([arr[2], arr[1], arr[0]]).astype("float32")  # B04, B03, B02
    out = np.empty_like(rgb)
    for i in range(3):
        b = rgb[i]
        lo, hi = np.percentile(b[b > 0], (2, 98)) if (b > 0).any() else (0.0, 1.0)
        out[i] = np.clip((b - lo) / max(hi - lo, 1e-6), 0, 1)
    return np.transpose(out, (1, 2, 0))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--quadrat", default="karachi_coast_calib_2p16km2")
    ap.add_argument("--label", default="karachi_coast", help="row value in the roofclf table")
    ap.add_argument("--title", default="Coastal Karachi (DHA Phase 5 / Zamzama)")
    ap.add_argument("--composites", default="data/composites/pakistan")
    ap.add_argument("--seg-prob", default="data/predictions_pk16085/pakistan/prob")
    ap.add_argument("--roofclf", default="data/roofclf/buildings.geoparquet")
    ap.add_argument("--folds", default="data/roofclf/folds.csv")
    ap.add_argument("--out", default="results/coastal-Karachi.png")
    a = ap.parse_args()

    # Every number in the titles is read from the artifacts, never typed in: the repo's
    # rule is that a figure cannot drift from its source (CLAUDE.md, docs site section).
    import pandas as pd
    from earthpv.labels import geodesic_area_m2

    folds = pd.read_csv(a.folds).set_index("quadrat")
    if a.label not in folds.index:
        raise SystemExit(f"{a.label} not in {a.folds}; run `earthpv roof-classifier` first")
    f = folds.loc[a.label]

    boundary, pv = load_quadrat(a.quadrat)
    pv_area = np.array([geodesic_area_m2(g) for g in pv.geometry])
    med = float(np.median(pv_area))
    below = 100.0 * (pv_area < 400.0).mean()
    minx, miny, maxx, maxy = boundary.bounds
    res = CompositeIndex(Path(a.composites)).read_window((minx, miny, maxx, maxy))
    if res is None:
        raise SystemExit(f"no composite coverage for {a.quadrat}")
    arr, transform, crs = res
    arr = arr[:10].astype("float32") / 10000.0
    h, w = arr.shape[-2:]

    seg_path = _raster_for(boundary.centroid, Path(a.seg_prob))
    seg = (
        _read_prob(seg_path, (minx, miny, maxx, maxy), crs, transform, (h, w))
        if seg_path else np.zeros((h, w), "float32")
    )

    bu = gpd.read_parquet(a.roofclf)
    bu = bu[bu.quadrat == a.label].to_crs(crs)
    seg_mean_per_building = bu.seg_mean.to_numpy()
    pv_utm = pv.to_crs(crs)
    # Shared pixel extent so all three panels register exactly.
    left, top = transform * (0, 0)
    right, bottom = transform * (w, h)
    extent = (left, right, bottom, top)

    plt.rcParams.update({"font.family": SANS, "font.size": 9})
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 5.0))

    axes[0].imshow(_rgb(arr), extent=extent, interpolation="nearest")
    bu.boundary.plot(ax=axes[0], color=BLD_EDGE, linewidth=0.35, alpha=0.85)
    pv_utm.boundary.plot(ax=axes[0], color=PV_EDGE, linewidth=1.0)
    axes[0].set_title(
        f"Sentinel-2, 10 m - {len(pv_utm)} mapped installations\n"
        f"median {med:.0f} m²; {below:.1f}% below the 400 m² floor",
        fontsize=10, color=INK, loc="left", pad=8,
    )
    axes[0].legend(
        handles=[
            mpatches.Patch(facecolor="none", edgecolor=PV_EDGE, label="mapped PV (Rule-1 complete)"),
            mpatches.Patch(facecolor="none", edgecolor=BLD_EDGE, label="building footprint"),
        ],
        loc="lower left", fontsize=7.5, frameon=True, framealpha=0.85,
    )

    norm = Normalize(0.0, 1.0)
    im = axes[1].imshow(seg, extent=extent, cmap=CMAP, norm=norm, interpolation="nearest")
    pv_utm.boundary.plot(ax=axes[1], color=PV_EDGE, linewidth=0.8, alpha=0.9)
    seg_pred_m2 = float(np.minimum(
        seg_mean_per_building * bu.roof_area_m2.to_numpy(), bu.roof_area_m2.to_numpy()
    ).sum())
    axes[1].set_title(
        f"Segmentation model P(PV) - max {seg.max():.2f}\n"
        f"predicts {seg_pred_m2:,.0f} m² vs {pv_area.sum():,.0f} m² mapped; "
        f"AUC {f.auc_seg_baseline:.3f}",
        fontsize=10, color=INK, loc="left", pad=8,
    )

    bu.plot(ax=axes[2], column="p_oof", cmap=CMAP, norm=norm, linewidth=0.15,
            edgecolor="#00000033")
    pv_utm.boundary.plot(ax=axes[2], color=PV_EDGE, linewidth=0.8, alpha=0.9)
    axes[2].set_title(
        "Per-building classifier, out-of-fold\n"
        f"AUC {f.auc:.3f} ({f.auc_within_size:.3f} at fixed roof size)",
        fontsize=10, color=INK, loc="left", pad=8,
    )

    for ax in axes:
        ax.set_xlim(left, right)
        ax.set_ylim(bottom, top)
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color(RULE)

    cax = fig.add_axes([0.355, 0.075, 0.60, 0.022])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_label("P(PV)  -  same scale in both right-hand panels", color=DIM, fontsize=8)
    cb.ax.tick_params(colors=DIM, labelsize=7.5)
    cb.outline.set_edgecolor(RULE)

    fig.text(0.008, 0.965, a.title, fontsize=15, family=SERIF, color=INK, va="top")
    fig.text(
        0.008, 0.915,
        "The benchmark that shows where the detector ends and the per-building model begins. "
        f"Every visible panel in this {geodesic_area_m2(boundary) / 1e6:.2f} km² box is mapped "
        "and owner-verified, so a building with no PV here is a real negative.",
        fontsize=8.8, color=DIM, va="top",
    )
    fig.subplots_adjust(left=0.008, right=0.992, top=0.80, bottom=0.13, wspace=0.03)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, facecolor="white")
    log.info("wrote %s (%d buildings, %d mapped PV, seg max %.3f)",
             out, len(bu), len(pv_utm), float(seg.max()))


if __name__ == "__main__":
    main()
