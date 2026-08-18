"""Static, print-quality PV density maps from the pk16085 density run --
matplotlib/geopandas, not the interactive HTML atlas (src/earthpv/atlas.py).

Two outputs:

- `scientific`: a full-resolution figure -- every one of the ~124k individual
  buildings carrying PV signal (data/predictions_pk16085/pakistan/density/
  buildings.geoparquet), not the 0.1 deg grid aggregate. Clean white background,
  province outlines, scale bar, north arrow, colorbar -- meant to sit in a paper
  or report figure.
- `poster`: same underlying per-building data, rendered at large-format print
  size (ISO A0 landscape, 300 DPI) in the project's established dark
  night-lights palette (src/earthpv/templates/pv_estimator_atlas.html's amber-
  on-near-black scheme), with a hero capacity number, per-province ranking and a
  soft glow layer under the bright clusters -- designed to be looked at from
  across a room, not read line by line.

Usage:
  .pixi/envs/default/bin/python scripts/plot_pv_density_maps.py scientific
  .pixi/envs/default/bin/python scripts/plot_pv_density_maps.py poster
  .pixi/envs/default/bin/python scripts/plot_pv_density_maps.py both
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402

DENSITY_DIR = Path("data/predictions_pk16085/pakistan/density")
OUT_DIR = Path("results")

SERIF = "Noto Serif Display"
SANS = "Noto Sans"
MONO = "Noto Sans Mono"

CITIES = [
    ["Karachi", 67.01, 24.86], ["Lahore", 74.34, 31.55], ["Islamabad", 73.05, 33.68],
    ["Faisalabad", 73.08, 31.42], ["Multan", 71.52, 30.2], ["Peshawar", 71.58, 34.01],
    ["Quetta", 66.98, 30.18], ["Hyderabad", 68.37, 25.4], ["Rawalpindi", 73.07, 33.6],
    ["Gujranwala", 74.19, 32.16], ["Sukkur", 68.85, 27.7], ["Bahawalpur", 71.68, 29.4],
]


def _load():
    b = gpd.read_parquet(DENSITY_DIR / "buildings.geoparquet")
    b = b[b.est_kwp_cal > 0].copy()
    reg = gpd.read_parquet(DENSITY_DIR / "regions.geoparquet")
    reg = reg[reg.level == "region"].copy()
    meta = json.loads((DENSITY_DIR / "meta.json").read_text())
    cx = b.geometry.to_crs("EPSG:6933").centroid.to_crs("EPSG:4326")
    b["bx"], b["by"] = cx.x.to_numpy(), cx.y.to_numpy()
    return b, reg, meta


def _scale_bar(ax, lon0, lat0, km, color, fontsize, mono=MONO):
    """A geodesic-correct scale bar: km converted to degrees of longitude at
    this map's latitude (1 deg lon = 111.32*cos(lat) km), so the bar's on-map
    length is accurate even though the axes themselves are plain lon/lat."""
    deg = km / (111.32 * np.cos(np.radians(lat0)))
    ax.plot([lon0, lon0 + deg], [lat0, lat0], color=color, lw=2.4, solid_capstyle="butt")
    for x in (lon0, lon0 + deg):
        ax.plot([x, x], [lat0 - 0.06, lat0 + 0.06], color=color, lw=2.4)
    ax.text(lon0 + deg / 2, lat0 + 0.18, f"{km} km", color=color, fontsize=fontsize,
             ha="center", va="bottom", family=mono)


def _north_arrow(ax, lon0, lat0, size, color):
    ax.annotate("", xy=(lon0, lat0 + size), xytext=(lon0, lat0),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=2.2, mutation_scale=22))
    ax.text(lon0, lat0 + size * 1.18, "N", color=color, fontsize=size * 34,
             ha="center", va="bottom", family=SANS, weight="bold")


def build_scientific() -> Path:
    b, reg, meta = _load()
    bounds = reg.total_bounds
    lat0 = (bounds[1] + bounds[3]) / 2
    aspect = 1 / np.cos(np.radians(lat0))

    fig_w = 20
    fig_h = fig_w * (bounds[3] - bounds[1]) * aspect / (bounds[2] - bounds[0])
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=300)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    reg.boundary.plot(ax=ax, color="#3a3a3a", linewidth=0.7, zorder=2)

    vmin, vmax = 0.3, np.percentile(b.est_kwp_cal, 99.5)
    norm = LogNorm(vmin=vmin, vmax=max(vmax, vmin * 10))
    cmap = plt.get_cmap("inferno")
    order = np.argsort(b.est_kwp_cal.to_numpy())  # brightest drawn last, on top
    sizes = 0.6 + 4.0 * (np.log10(b.est_kwp_cal.to_numpy() + 1) / np.log10(b.est_kwp_cal.max() + 1))
    sc = ax.scatter(
        b.bx.to_numpy()[order], b.by.to_numpy()[order], c=b.est_kwp_cal.to_numpy()[order],
        s=sizes[order], cmap=cmap, norm=norm, linewidths=0, alpha=0.85, zorder=3,
        rasterized=True,
    )

    for name, lon, lat in CITIES:
        ax.plot(lon, lat, marker="s", ms=3.5, color="#1f6fb2", zorder=4, mew=0)
        ax.annotate(name, (lon, lat), xytext=(4, 3), textcoords="offset points",
                    fontsize=11, family=SANS, color="#1a1a1a", zorder=5)

    ax.set_aspect(aspect)
    pad_x = (bounds[2] - bounds[0]) * 0.03
    pad_y = (bounds[3] - bounds[1]) * 0.03
    ax.set_xlim(bounds[0] - pad_x, bounds[2] + pad_x)
    ax.set_ylim(bounds[1] - pad_y, bounds[3] + pad_y)
    ax.set_xlabel("Longitude", fontsize=12, family=SANS)
    ax.set_ylabel("Latitude", fontsize=12, family=SANS)
    ax.tick_params(labelsize=10)
    for spine in ax.spines.values():
        spine.set_color("#888888")

    cbar = fig.colorbar(sc, ax=ax, shrink=0.5, pad=0.015, aspect=28)
    cbar.set_label("Estimated capacity per building (kWp, calibrated)", fontsize=11, family=SANS)
    cbar.ax.tick_params(labelsize=9)

    _scale_bar(ax, bounds[0] + pad_x + 0.3, bounds[1] + pad_y + 0.6, 200, "#1a1a1a", 10, mono=SANS)
    _north_arrow(ax, bounds[2] - pad_x - 0.7, bounds[1] + pad_y + 0.4, 0.6, "#1a1a1a")

    # fig-level text, not ax.set_title + ax.text(1.0x) -- the latter two don't share a
    # coordinate space (points-based title pad vs axes-fraction text) and collide.
    fig.text(0.09, 0.985, "Rooftop and ground-mount solar PV capacity - Pakistan",
             fontsize=22, family=SERIF, weight="medium", ha="left", va="top")
    fig.text(
        0.09, 0.965,
        f"{len(b):,} individual buildings carrying detected PV signal, calibrated capacity "
        # Per-building capacity is footprint-intersected, i.e. rooftop module area, so the
        # module constant is the one that applies. `kwp_per_m2` is the pre-split meta key.
        f"(P(real | size, glint)) at "
        f"{meta.get('kwp_per_m2_module', meta.get('kwp_per_m2', 0.18))} kWp/m² of panel area · "
        "TerraMind-tiny on Sentinel-2 L2A · earthpv density stage",
        fontsize=11.5, family=SANS, color="#444444", ha="left", va="top",
    )

    out_png = OUT_DIR / "pakistan_pv_density_scientific.png"
    out_pdf = OUT_DIR / "pakistan_pv_density_scientific.pdf"
    fig.savefig(out_png, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out_pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


# ---------------------------------------------------------------------------------------
# Poster
# ---------------------------------------------------------------------------------------
AMBER_STOPS = ["#191408", "#3d2c0c", "#6B4E12", "#C08019", "#F5B63E", "#FFF6DC"]
AMBER_CMAP = LinearSegmentedColormap.from_list("amber_glow", AMBER_STOPS)


def build_poster() -> Path:
    b, reg, meta = _load()
    bounds = reg.total_bounds
    lat0 = (bounds[1] + bounds[3]) / 2
    aspect = 1 / np.cos(np.radians(lat0))

    # ISO A0 landscape at 300 DPI.
    fig_w, fig_h = 46.8, 33.1
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=300)
    bg = "#0B0D13"
    fig.patch.set_facecolor(bg)

    # Map occupies the right ~72% of the canvas; left margin holds the title/stats panel.
    ax = fig.add_axes([0.30, 0.05, 0.68, 0.90])
    ax.set_facecolor("#07080D")

    reg.boundary.plot(ax=ax, color="#3a4258", linewidth=1.1, zorder=2, alpha=0.55)

    val = b.est_kwp_cal.to_numpy()
    order = np.argsort(val)
    norm = LogNorm(vmin=0.3, vmax=max(np.percentile(val, 99.7), 3))

    # Soft glow: large, very transparent markers under the sharp points, echoing the
    # HTML atlas's radial-gradient "bloom" for cells above a brightness threshold.
    bright = val > np.percentile(val, 92)
    ax.scatter(b.bx.to_numpy()[bright], b.by.to_numpy()[bright], c="#F5B63E",
               s=180, alpha=0.05, linewidths=0, zorder=2.5, rasterized=True)
    ax.scatter(b.bx.to_numpy()[bright], b.by.to_numpy()[bright], c="#F5B63E",
               s=70, alpha=0.07, linewidths=0, zorder=2.6, rasterized=True)

    sizes = 1.2 + 7.0 * (np.log10(val + 1) / np.log10(val.max() + 1))
    ax.scatter(
        b.bx.to_numpy()[order], b.by.to_numpy()[order], c=val[order],
        s=sizes[order], cmap=AMBER_CMAP, norm=norm, linewidths=0, alpha=0.92, zorder=3,
        rasterized=True,
    )

    for name, lon, lat in CITIES:
        ax.plot(lon, lat, marker="o", ms=4, color="#E9E5DC", alpha=0.7, zorder=4, mew=0)
        ax.annotate(name, (lon, lat), xytext=(5, 4), textcoords="offset points",
                    fontsize=15, family=SANS, color="#E9E5DCb0", zorder=5)

    ax.set_aspect(aspect)
    pad_x = (bounds[2] - bounds[0]) * 0.02
    pad_y = (bounds[3] - bounds[1]) * 0.02
    ax.set_xlim(bounds[0] - pad_x, bounds[2] + pad_x)
    ax.set_ylim(bounds[1] - pad_y, bounds[3] + pad_y)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    _scale_bar(ax, bounds[0] + pad_x + 0.3, bounds[1] + pad_y + 0.6, 200, "#9B958A", 15, mono=MONO)
    _north_arrow(ax, bounds[2] - pad_x - 0.8, bounds[1] + pad_y + 0.5, 0.7, "#9B958A")

    # ---- Left panel: title, hero number, province ranking ------------------------
    lp = fig.add_axes([0.03, 0.05, 0.24, 0.90])
    lp.set_axis_off()
    lp.set_facecolor(bg)

    lp.text(0.0, 0.97, "EARTHPV · SENTINEL-2 × TERRAMIND", fontsize=15, family=MONO,
            color="#6B665D", ha="left", va="top", transform=lp.transAxes, weight="bold")
    lp.text(0.0, 0.935, "Pakistan's solar\nboom, mapped\nbuilding by\nbuilding",
            fontsize=44, family=SERIF, color="#E9E5DC", ha="left", va="top",
            transform=lp.transAxes, linespacing=1.15)

    hero = meta.get("total_est_mwp_rc", meta.get("total_est_mwp_cal_total", 0))
    lo = meta.get("total_est_mwp_rc_lo")
    hi = meta.get("total_est_mwp_rc_hi")
    lp.text(0.0, 0.60, f"{hero:,.0f}", fontsize=90, family=MONO, weight="bold",
            color="#F5B63E", ha="left", va="top", transform=lp.transAxes)
    lp.text(0.0, 0.505, "MWp - recall-corrected, all PV", fontsize=17, family=SANS,
            color="#9B958A", ha="left", va="top", transform=lp.transAxes)
    if lo and hi:
        lp.text(0.0, 0.475, f"90% credible band  {lo:,.0f} – {hi:,.0f} MWp", fontsize=14,
                family=MONO, color="#6B665D", ha="left", va="top", transform=lp.transAxes)

    lp.text(0.0, 0.43, f"{len(b):,}", fontsize=32, family=MONO, weight="bold",
            color="#2FD9C4", ha="left", va="top", transform=lp.transAxes)
    lp.text(0.0, 0.398, "individual buildings carrying detected PV, plotted at full resolution",
            fontsize=13.5, family=SANS, color="#9B958A", ha="left", va="top",
            transform=lp.transAxes, wrap=True)

    # Province ranking bars.
    reg_sorted = reg.sort_values("est_mwp_rc", ascending=False) if "est_mwp_rc" in reg.columns \
        else reg.sort_values("est_mwp_cal_total", ascending=False)
    col = "est_mwp_rc" if "est_mwp_rc" in reg.columns else "est_mwp_cal_total"
    y0, dy = 0.335, 0.033
    maxv = reg_sorted[col].max()
    lp.text(0.0, y0 + dy * 0.9, "PROVINCES, RANKED", fontsize=12.5, family=MONO,
            color="#6B665D", ha="left", va="bottom", transform=lp.transAxes, weight="bold")
    for i, r in enumerate(reg_sorted.itertuples()):
        y = y0 - i * dy
        w = 0.62 * (getattr(r, col) / maxv)
        # Name + value sit just above their own bar (va="bottom" anchors text to y),
        # not below it -- a label placed below a bar reads as belonging to the NEXT
        # (lower) bar once there's more than one row, which is what happened before.
        lp.text(0.0, y + 0.004, r.name, fontsize=12.5, family=SANS,
                color="#E9E5DC", ha="left", va="bottom", transform=lp.transAxes)
        lp.text(0.98, y + 0.004, f"{getattr(r, col):,.0f} MWp", fontsize=12.5, family=MONO,
                color="#9B958A", ha="right", va="bottom", transform=lp.transAxes)
        lp.add_patch(plt.Rectangle((0.0, y - 0.013), w, 0.015, transform=lp.transAxes,
                                    color="#C08019", lw=0))

    lp.text(0.0, 0.045,
            "Model reads a year of Sentinel-2 L2A imagery and marks pixels that look like\n"
            "photovoltaic panels; area is calibrated by measured P(real | size, glint) against\n"
            "OSM mapping and a country-wide glint-corroboration study, then divided by\n"
            "measured per-size recall for the whole detectable population.",
            fontsize=12, family=SANS, color="#565E70", ha="left", va="top",
            transform=lp.transAxes, linespacing=1.5)
    lp.text(0.0, -0.005, "earthpv density stage · indicative estimate for energy-system modelling, not metered capacity",
            fontsize=10.5, family=MONO, color="#3a4258", ha="left", va="top", transform=lp.transAxes)

    out_png = OUT_DIR / "posters" / "pakistan_pv_density_poster.png"
    out_pdf = OUT_DIR / "posters" / "pakistan_pv_density_poster.pdf"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=300, facecolor=bg)
    fig.savefig(out_pdf, facecolor=bg)
    plt.close(fig)
    return out_png


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("scientific", "both"):
        print("scientific ->", build_scientific())
    if which in ("poster", "both"):
        print("poster ->", build_poster())
