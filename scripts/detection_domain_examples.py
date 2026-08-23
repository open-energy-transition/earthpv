#!/usr/bin/env python
"""Source data for the docs' "how detection works" illustrations, spatial and spectral.

Reads gitignored `data/` (the roofclf building table, the national probability rasters,
the OSM label pull) and writes three small tracked artifacts to `results/`, which
`scripts/build_docs_figures.py` then turns into the published figures. Same arrangement
as `plot_calib_quadrat.py` -> `coastal-Karachi.png`: the docs CI cannot regenerate a
data-dependent artifact, so the tracked file is the interface to the site.

Outputs
  results/detection_spectral_signatures.csv   median 10-band spectrum, PV vs size-matched
                                              PV-free roofs, sub-400 m2, from the Rule-1
                                              calibration quadrats
  results/detection_feature_auc.csv           how well each single spectral cue separates
                                              the same two populations, vs SPPI and the
                                              full classifier (all out-of-fold)
  results/segmentation_examples.png           composite -> probability -> polygon, four
                                              real installations from ~200,000 m2 down to
                                              a sub-400 m2 miss
  results/candidate_placement.png             the building join on real candidates: the
                                              same scene before and after VIDA footprints
                                              classify each candidate's placement
  results/quadrat_map.png                     every calibration quadrat on the province
                                              map, sized by its mapped installations
  results/capacity_metrics_example.csv        one real rooftop candidate (area, bin,
                                              placement) for the det -> cal -> rc
                                              waterfall figure; p_real and recall come
                                              from the tracked calibration YAML at
                                              figure-build time so the two never diverge
  results/density_domain_cells.csv            every national cell's building density and
                                              count, for the calibrated-domain histogram
  results/density_domain_quadrats.csv         each quadrat's own density plus the shipped
                                              domain band (density.CALIBRATED_BLDG_DENSITY_KM2)
  results/pv_size_vs_building_bins.csv        mapped PV area and coverage fraction per
                                              roof-size bin, PV-carrying quadrat buildings
  results/pv_size_vs_building_scatter.csv     a stratified per-building sample of
                                              (roof area, PV area) behind those bins

The building sample: every building under 400 m2 in the Rule-1 quadrat table except
Kalat Rural (its has-PV labels are dominated by a >= 400 m2 ground-mount array clipping
roofs, see docs/methods/calibration-quadrats.md), with the PV-free class resampled to the
PV class's roof-size decile distribution so nothing below is a roof-size effect in
disguise.

    .pixi/envs/default/bin/python scripts/detection_domain_examples.py
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.windows

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from rasterio.warp import transform_bounds, transform_geom  # noqa: E402
from shapely.geometry import box, shape  # noqa: E402

from earthpv.labels import geodesic_area_m2  # noqa: E402
from earthpv.local_source import CompositeIndex  # noqa: E402
from earthpv.sppi import compute_sppi  # noqa: E402

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

BUILDINGS = ROOT / "data/roofclf/buildings.geoparquet"
LABELS = ROOT / "data/labels/pakistan_overpass_solar.parquet"
PROB_DIR = ROOT / "data/predictions/pakistan/prob"
COMPOSITES = ROOT / "data/composites/pakistan"

SEED = 20260823
BANDS = ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b8a", "b11", "b12"]
# Band centre wavelengths in nm (Sentinel-2A values, the convention the mission handbook
# quotes); close enough to S2B/S2C for a labelled axis.
WAVELENGTH_NM = {
    "b02": 490, "b03": 560, "b04": 665, "b05": 705, "b06": 740,
    "b07": 783, "b08": 842, "b8a": 865, "b11": 1610, "b12": 2190,
}

# Same raster styling as plot_calib_quadrat.py, so the two example PNGs read as one set.
INK, DIM, RULE = "#1A1A1A", "#555555", "#CCCCCC"
PV_EDGE = "#00C2B8"    # mapped OSM ground truth
CAND_EDGE = "#E8890C"  # the threshold-0.3 contour, i.e. what postprocess polygonizes
CMAP = "magma"
THRESHOLD = 0.3        # postprocess default, docs/reproduce.md


# ------------------------------------------------------------------ spectral domain


def matched_sample() -> tuple[pd.DataFrame, pd.DataFrame]:
    """PV and size-matched PV-free buildings under 400 m2 from the quadrat table."""
    cols = ["quadrat", "roof_area_m2", "has_pv", "p_oof"] + [f"{b}_mean" for b in BANDS] + [
        "ndvi", "ndbi", "brightness", "swir_vis_ratio", "blue_red_ratio",
    ]
    df = pd.read_parquet(BUILDINGS, columns=cols)
    df = df[df.quadrat != "kalat_rural"].dropna(subset=["b02_mean"])
    sub = df[df.roof_area_m2 < 400.0].copy()
    sub["dec"] = pd.qcut(sub.roof_area_m2, 10, labels=False, duplicates="drop")
    pv = sub[sub.has_pv == 1]
    npv = sub[sub.has_pv == 0]
    # Resample the PV-free class to the PV class's roof-size decile distribution
    # (3x the PV count, so the medians stay stable), so the two spectra are compared
    # at the same roof sizes rather than confounded by size.
    parts = []
    for d, frac in pv.dec.value_counts(normalize=True).items():
        pool = npv[npv.dec == d]
        n = min(len(pool), int(round(frac * 3 * len(pv))))
        parts.append(pool.sample(n, random_state=SEED % (2**32)))
    return pv, pd.concat(parts)


def rank_auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann-Whitney AUC with tie handling, no sklearn dependency."""
    x = np.concatenate([pos, neg])
    ranks = pd.Series(x).rank().to_numpy()
    n_pos, n_neg = len(pos), len(neg)
    return float((ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def write_spectral_csvs() -> None:
    pv, npv = matched_sample()
    log.info("spectral sample: %d PV vs %d size-matched PV-free buildings", len(pv), len(npv))

    rows = []
    for b in BANDS:
        c = f"{b}_mean"
        rows.append({
            "band": b.upper().replace("B8A", "B8A"),
            "wavelength_nm": WAVELENGTH_NM[b],
            "pv_q25": pv[c].quantile(0.25), "pv_med": pv[c].median(),
            "pv_q75": pv[c].quantile(0.75),
            "nopv_q25": npv[c].quantile(0.25), "nopv_med": npv[c].median(),
            "nopv_q75": npv[c].quantile(0.75),
            "n_pv": len(pv), "n_nopv": len(npv),
        })
    out = RESULTS / "detection_spectral_signatures.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})
    log.info("wrote %s", out.relative_to(ROOT))

    # Single-cue separation on the identical sample, against the two combinations the
    # pipeline actually uses. `p_oof` is out-of-fold (leave-one-quadrat-out), so the
    # combined row carries no optimism the single-feature rows lack.
    pv_sppi = compute_sppi(pv.b02_mean, pv.b03_mean, pv.b08_mean, pv.b11_mean, pv.b12_mean)
    npv_sppi = compute_sppi(npv.b02_mean, npv.b03_mean, npv.b08_mean, npv.b11_mean, npv.b12_mean)
    cues = [
        # (csv key, chart label, direction of the PV class, positive scores)
        ("roofclf", "roofclf, all 17 features combined", "out-of-fold probability",
         pv.p_oof.to_numpy(float), npv.p_oof.to_numpy(float)),
        ("sppi", "SPPI, a fixed 5-band formula", "higher over panels",
         pv_sppi.to_numpy(float), npv_sppi.to_numpy(float)),
        ("blue_red_ratio", "blue / red ratio", "panels read bluer",
         pv.blue_red_ratio.to_numpy(float), npv.blue_red_ratio.to_numpy(float)),
        ("b08", "near-infrared B08", "panels read darker",
         pv.b08_mean.to_numpy(float), npv.b08_mean.to_numpy(float)),
        ("ndbi", "NDBI (SWIR vs NIR)", "relatively brighter in SWIR",
         pv.ndbi.to_numpy(float), npv.ndbi.to_numpy(float)),
        ("brightness", "overall brightness", "panels read darker",
         pv.brightness.to_numpy(float), npv.brightness.to_numpy(float)),
        ("ndvi", "NDVI (vegetation index)", "nearly uninformative here",
         pv.ndvi.to_numpy(float), npv.ndvi.to_numpy(float)),
    ]
    out = RESULTS / "detection_feature_auc.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "label", "direction", "auc_raw", "auc_folded", "n_pv", "n_nopv"])
        for key, label, direction, pos, neg in cues:
            a = rank_auc(pos, neg)
            w.writerow([key, label, direction, f"{a:.4f}", f"{max(a, 1 - a):.4f}",
                        len(pos), len(neg)])
            log.info("  %-34s AUC %.3f (folded %.3f)", label, a, max(a, 1 - a))
    log.info("wrote %s", out.relative_to(ROOT))


# ------------------------------------------------------------------- spatial domain


def _cell_index() -> gpd.GeoDataFrame:
    """Lon/lat bounds of every per-cell probability raster."""
    paths, geoms = [], []
    for p in sorted(PROB_DIR.glob("*.tif")):
        with rasterio.open(p) as src:
            paths.append(p)
            geoms.append(box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds)))
    return gpd.GeoDataFrame({"path": paths}, geometry=geoms, crs="EPSG:4326")


def _prob_stats(cells: gpd.GeoDataFrame, geom) -> tuple[float, float] | None:
    """(mean, max) model probability inside one lon/lat polygon, or None off-raster."""
    hit = cells[cells.contains(geom.centroid)]
    if hit.empty:
        return None
    with rasterio.open(hit["path"].iloc[0]) as src:
        g = transform_geom("EPSG:4326", src.crs.to_string(), geom.__geo_interface__)
        win = rasterio.windows.from_bounds(
            *shape(g).bounds, transform=src.transform
        ).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        if win.width < 1 or win.height < 1:
            return None
        arr = src.read(1, window=win).astype("float32") / 255.0
        mask = rasterio.features.geometry_mask(
            [g], out_shape=(int(win.height), int(win.width)),
            transform=rasterio.windows.transform(win, src.transform),
            invert=True, all_touched=True,
        )
        vals = arr[mask]
    return (float(vals.mean()), float(vals.max())) if vals.size else None


def _rgb(arr: np.ndarray) -> np.ndarray:
    """True-colour composite, percentile-stretched per band (plot_calib_quadrat._rgb)."""
    rgb = np.stack([arr[2], arr[1], arr[0]]).astype("float32")  # B04, B03, B02
    out = np.empty_like(rgb)
    for i in range(3):
        b = rgb[i]
        lo, hi = np.percentile(b[b > 0], (2, 98)) if (b > 0).any() else (0.0, 1.0)
        out[i] = np.clip((b - lo) / max(hi - lo, 1e-6), 0, 1)
    return np.transpose(out, (1, 2, 0))


def pick_examples(labels: gpd.GeoDataFrame, cells: gpd.GeoDataFrame) -> list[dict]:
    """One installation per size bracket, plus the median probability of its bracket.

    The first three rows are deliberately clear detections (the highest mean probability
    in a fixed random shortlist), because the figure illustrates the mechanism; the
    bracket median reported next to each keeps the recall picture honest. The last row is
    the opposite: the sampled sub-400 m2 installation whose peak probability sits at its
    bracket's median, i.e. a representative miss, not a cherry-picked one.
    """
    a = labels["area_m2"]
    brackets = [
        ("ground", "Utility plant, ground-mount",
         (labels.placement == "ground") & (a >= 1e5), "best", 2200.0),
        ("roof_large", "Industrial rooftop",
         (labels.placement == "rooftop") & a.between(2000, 10000), "best", 640.0),
        ("roof_floor", "Rooftop at the 400 m² floor",
         (labels.placement == "rooftop") & a.between(400, 1000), "best", 400.0),
        ("roof_sub400", "Below the floor",
         (labels.placement == "rooftop") & a.between(80, 300), "median", 400.0),
    ]
    rows = []
    for key, title, sel, mode, side_m in brackets:
        shortlist = labels[sel].sample(min(sel.sum(), 60), random_state=7)
        scored = []
        for _, r in shortlist.iterrows():
            st = _prob_stats(cells, r.geometry)
            if st is not None:
                scored.append((r, *st))
        med_max = float(np.median([s[2] for s in scored]))
        if mode == "best":
            r, p_mean, p_max = max(scored, key=lambda s: s[1])
        else:
            r, p_mean, p_max = min(scored, key=lambda s: abs(s[2] - med_max))
        rows.append({
            "key": key, "title": title, "row": r, "p_max": p_max,
            "bracket_median_pmax": med_max, "n_scored": len(scored), "side_m": side_m,
        })
        log.info("%s: %s %.0f m2, p_max %.2f (bracket median %.2f over %d sampled)",
                 key, r["id"], r["area_m2"], p_max, med_max, len(scored))
    return rows


def build_examples_png(out: Path) -> None:
    labels = gpd.read_parquet(LABELS)
    labels["area_m2"] = [geodesic_area_m2(g) for g in labels.geometry]
    cells = _cell_index()
    picks = pick_examples(labels, cells)
    comp = CompositeIndex(COMPOSITES)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig, axes = plt.subplots(len(picks), 3, figsize=(11.4, 3.85 * len(picks)))
    norm = Normalize(0.0, 1.0)
    im = None

    for i, pick in enumerate(picks):
        r = pick["row"]
        c = r.geometry.centroid
        # A square lon/lat crop of side_m metres around the installation.
        half_deg_y = pick["side_m"] / 2 / 111_320.0
        half_deg_x = half_deg_y / np.cos(np.radians(c.y))
        bounds = (c.x - half_deg_x, c.y - half_deg_y, c.x + half_deg_x, c.y + half_deg_y)
        res = comp.read_window(bounds)
        if res is None:
            raise SystemExit(f"no composite coverage at {c.y:.3f}N {c.x:.3f}E")
        arr, transform, crs = res
        arr = arr[:10].astype("float32") / 10000.0
        h, w = arr.shape[-2:]
        left, top = transform * (0, 0)
        right, bottom = transform * (w, h)
        extent = (left, right, bottom, top)

        hit = cells[cells.contains(c)]
        with rasterio.open(hit["path"].iloc[0]) as src:
            wb = transform_bounds(crs, src.crs, left, bottom, right, top)
            win = rasterio.windows.from_bounds(*wb, transform=src.transform)
            win = win.round_offsets().round_lengths().intersection(
                rasterio.windows.Window(0, 0, src.width, src.height))
            prob_native = src.read(1, window=win).astype("float32") / 255.0
            src_tf = rasterio.windows.transform(win, src.transform)
            src_crs = src.crs
        prob = np.zeros((h, w), "float32")
        from rasterio.warp import Resampling, reproject
        reproject(source=prob_native, destination=prob, src_transform=src_tf,
                  src_crs=src_crs, dst_transform=transform, dst_crs=crs,
                  resampling=Resampling.bilinear)

        osm = labels[labels.intersects(box(*bounds))].to_crs(crs)
        n_osm = len(osm)

        ax0, ax1, ax2 = axes[i]
        lw = 0.7 if pick["side_m"] > 1000 else 1.0
        ax0.imshow(_rgb(arr), extent=extent, interpolation="nearest")
        osm.boundary.plot(ax=ax0, color=PV_EDGE, linewidth=lw)

        im = ax1.imshow(prob, extent=extent, cmap=CMAP, norm=norm, interpolation="nearest")

        ax2.imshow(_rgb(arr), extent=extent, interpolation="nearest")
        osm.boundary.plot(ax=ax2, color=PV_EDGE, linewidth=lw)
        if prob.max() >= THRESHOLD:
            # The exact operation postprocess performs: everything above 0.3, outlined.
            ax2.contour(prob, levels=[THRESHOLD], colors=[CAND_EDGE], linewidths=1.4,
                        extent=(left, right, bottom, top), origin="upper")

        ax0.set_title(
            f"{pick['title']}\n{r['area_m2']:,.0f} m² mapped, {c.y:.2f}N {c.x:.2f}E",
            fontsize=10, color=INK, loc="left", pad=6)
        ax1.set_title(
            f"peak P(PV) {pick['p_max']:.2f}\n"
            f"bracket median {pick['bracket_median_pmax']:.2f}, "
            f"n = {pick['n_scored']} sampled",
            fontsize=9, color=DIM, loc="left", pad=6)
        ax2.set_title(
            "candidate polygon" if prob.max() >= THRESHOLD
            else "nothing above 0.3: no candidate",
            fontsize=9, color=DIM, loc="left", pad=6)

        # 100 m scale bar, bottom left of the first panel.
        bar = 500.0 if pick["side_m"] > 1000 else 100.0
        x0 = left + (right - left) * 0.05
        y0 = bottom + (top - bottom) * 0.06
        ax0.plot([x0, x0 + bar], [y0, y0], color="white", linewidth=2.5)
        ax0.plot([x0, x0 + bar], [y0, y0], color=INK, linewidth=1.2)
        ax0.text(x0 + bar / 2, y0 + (top - bottom) * 0.02, f"{bar:.0f} m",
                 ha="center", color="white", fontsize=7.5,
                 path_effects=None)

        for ax in (ax0, ax1, ax2):
            ax.set_xlim(left, right)
            ax.set_ylim(bottom, top)
            ax.set_xticks([])
            ax.set_yticks([])
            for sp in ax.spines.values():
                sp.set_color(RULE)
        if n_osm == 0:
            log.warning("row %d has no OSM outline in view", i)

    for j, head in enumerate(["1. Sentinel-2 composite, 10 m", "2. Model probability",
                              "3. Threshold 0.3 and polygonize"]):
        axes[0][j].text(0.0, 1.30, head, transform=axes[0][j].transAxes,
                        fontsize=11.5, color=INK, fontweight="bold")

    cax = fig.add_axes([0.62, 0.042, 0.27, 0.009])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_label("P(PV)", color=DIM, fontsize=8)
    cb.ax.tick_params(colors=DIM, labelsize=7.5)
    cb.outline.set_edgecolor(RULE)

    handles = [
        Line2D([], [], color=PV_EDGE, linewidth=1.6, label="mapped in OpenStreetMap"),
        Line2D([], [], color=CAND_EDGE, linewidth=1.6, label="candidate (P > 0.3 outline)"),
    ]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.015, 0.022),
               fontsize=8.5, frameon=False, ncol=2)
    fig.text(0.015, 0.008,
             "Production checkpoint (v3_combined_india), the national inference run behind "
             "the published atlas. Rows 1-3 are deliberately clear detections; the bracket "
             "median next to each shows how typical that is.",
             fontsize=7.5, color=DIM)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.94, bottom=0.075,
                        wspace=0.03, hspace=0.30)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, facecolor="white")
    log.info("wrote %s", out.relative_to(ROOT))


# --------------------------------------------------------------- the building join

PLACEMENT_COLORS = {
    "rooftop": "#E8890C",          # >= 30% of the candidate sits on a footprint
    "ground_adjacent": "#7550b0",  # within 30 m of one
    "no_building": "#1c6fa8",      # neither
}
# A ~3.2 km scene near Multan chosen because it holds all three placement classes in one
# view (27 rooftop, 3 ground_adjacent, 2 no_building at the time of writing); the counts
# in the panel titles are recomputed from the candidates file, never assumed.
PLACEMENT_CENTER = (71.387, 30.1308)
PLACEMENT_SIDE_M = 3200.0


def build_placement_png(out: Path) -> None:
    """The same scene twice: raw candidates on imagery, then classified by the join."""
    from earthpv.buildings import fetch_vida_buildings

    cx, cy = PLACEMENT_CENTER
    half_y = PLACEMENT_SIDE_M / 2 / 111_320.0
    half_x = half_y / np.cos(np.radians(cy))
    bounds = (cx - half_x, cy - half_y, cx + half_x, cy + half_y)

    comp = CompositeIndex(COMPOSITES)
    res = comp.read_window(bounds)
    if res is None:
        raise SystemExit(f"no composite coverage at {cy:.3f}N {cx:.3f}E")
    arr, transform, crs = res
    arr = arr[:10].astype("float32") / 10000.0
    h, w = arr.shape[-2:]
    left, top = transform * (0, 0)
    right, bottom = transform * (w, h)
    extent = (left, right, bottom, top)

    cands = gpd.read_parquet(ROOT / "data/predictions/pakistan/candidates.parquet")
    cands = cands[cands.intersects(box(*bounds))].to_crs(crs)
    buildings = fetch_vida_buildings(bounds, "PAK").to_crs(crs)
    counts = cands.placement.value_counts().to_dict()
    log.info("placement scene: %d candidates %s, %d VIDA buildings",
             len(cands), counts, len(buildings))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(11.4, 6.1))

    ax0.imshow(_rgb(arr), extent=extent, interpolation="nearest")
    cands.boundary.plot(ax=ax0, color=CAND_EDGE, linewidth=1.3)
    ax0.set_title(
        f"{len(cands)} candidate polygons from the probability raster\n"
        "(threshold 0.3, polygonized; no building information yet)",
        fontsize=10, color=INK, loc="left", pad=8)

    buildings.plot(ax=ax1, facecolor="#E4E0D6", edgecolor="#B9B3A5", linewidth=0.25)
    for pl, col in PLACEMENT_COLORS.items():
        sub = cands[cands.placement == pl]
        if not sub.empty:
            sub.plot(ax=ax1, facecolor=col, edgecolor=col, alpha=0.55, linewidth=1.2)
            sub.boundary.plot(ax=ax1, color=col, linewidth=1.2)
    ax1.set_title(
        f"the same candidates against {len(buildings):,} VIDA footprints\n"
        f"rooftop {counts.get('rooftop', 0)}, ground-adjacent "
        f"{counts.get('ground_adjacent', 0)}, no building {counts.get('no_building', 0)}",
        fontsize=10, color=INK, loc="left", pad=8)

    handles = [
        mpatches.Patch(facecolor="#E4E0D6", edgecolor="#B9B3A5",
                       label="VIDA building footprint"),
        mpatches.Patch(facecolor=PLACEMENT_COLORS["rooftop"], alpha=0.7,
                       label="rooftop (≥ 30% on a footprint)"),
        mpatches.Patch(facecolor=PLACEMENT_COLORS["ground_adjacent"], alpha=0.7,
                       label="ground-adjacent (within 30 m)"),
        mpatches.Patch(facecolor=PLACEMENT_COLORS["no_building"], alpha=0.7,
                       label="no building nearby"),
    ]
    ax1.legend(handles=handles, loc="lower right", fontsize=8, frameon=True,
               framealpha=0.92, edgecolor=RULE)

    bar = 500.0
    x0 = left + (right - left) * 0.05
    y0 = bottom + (top - bottom) * 0.05
    ax0.plot([x0, x0 + bar], [y0, y0], color="white", linewidth=2.6)
    ax0.plot([x0, x0 + bar], [y0, y0], color=INK, linewidth=1.3)
    ax0.text(x0 + bar / 2, y0 + (top - bottom) * 0.015, "500 m", ha="center",
             color="white", fontsize=7.5)
    for ax in (ax0, ax1):
        ax.set_xlim(left, right)
        ax.set_ylim(bottom, top)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_aspect("equal")
        for sp in ax.spines.values():
            sp.set_color(RULE)

    fig.text(0.008, 0.975, f"The building join, on one real scene "
             f"({cy:.2f}N {cx:.2f}E)", fontsize=14, color=INK, va="top")
    fig.text(0.008, 0.928,
             "Placement never removes a candidate; it decides how each one is ranked for "
             "mappers and which\narea-to-capacity constant prices it (module 0.18 kWp/m² "
             "on rooftops, land 0.05 kWp/m² for ground-mount).",
             fontsize=8.8, color=DIM, va="top")
    fig.subplots_adjust(left=0.008, right=0.992, top=0.78, bottom=0.02, wspace=0.03)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, facecolor="white")
    log.info("wrote %s", out.relative_to(ROOT))


# ------------------------------------------------------------------ quadrat map

# Excluded from every roofclf refit until building_table's roof term gets a
# placement/size guard: 69 of its 89 has-PV labels come from one >= 400 m2 ground array
# clipping roofs. See docs/methods/calibration-quadrats.md and CLAUDE.md's Box 17 entry.
EXCLUDED_QUADRATS = {"kalat_rural_calib_3km"}


def _quadrat_stats() -> list[dict]:
    """One row per registered quadrat: boundary centroid, area, mapped installations."""
    rows = []
    for boundary in sorted((ROOT / "data/labels").glob("*_calib_*_boundary.geojson")):
        stem = boundary.name.replace("_boundary.geojson", "")
        pulls = sorted((ROOT / "data/labels").glob(f"{stem}_overpass_solar*.parquet"))
        if not pulls:
            log.warning("%s has no solar pull, skipping", stem)
            continue
        b = gpd.read_file(boundary)
        solar = gpd.read_parquet(pulls[-1])  # dated re-pulls sort after the plain name
        geom = b.geometry.union_all()
        rows.append({
            "stem": stem,
            "lon": geom.centroid.x, "lat": geom.centroid.y,
            "km2": geodesic_area_m2(geom) / 1e6,
            "n_pv": len(solar),
            "excluded": stem in EXCLUDED_QUADRATS,
        })
    return rows


def build_quadrat_map_png(out: Path) -> None:
    regions = gpd.read_parquet(ROOT / "data/labels/pakistan_regions.parquet")
    rows = _quadrat_stats()
    log.info("quadrat map: %d quadrats, %d mapped installations total",
             len(rows), sum(r["n_pv"] for r in rows))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig, ax = plt.subplots(figsize=(8.6, 8.2))
    regions.plot(ax=ax, facecolor="#F2EFE8", edgecolor="#B9B3A5", linewidth=0.7)

    kept = [r for r in rows if not r["excluded"]]
    excl = [r for r in rows if r["excluded"]]
    size = lambda r: 14 + 5.5 * np.sqrt(r["n_pv"])  # noqa: E731
    ax.scatter([r["lon"] for r in kept], [r["lat"] for r in kept],
               s=[size(r) for r in kept], color=CAND_EDGE, alpha=0.75,
               edgecolor="white", linewidth=0.6, zorder=5)
    if excl:
        ax.scatter([r["lon"] for r in excl], [r["lat"] for r in excl],
                   s=[size(r) for r in excl], facecolor="none", edgecolor=DIM,
                   linewidth=1.4, zorder=5)

    # Name the extremes so the map reads without a gazetteer: the three largest mapped
    # populations, the confirmed-zero quadrat, and the excluded one.
    label = sorted(kept, key=lambda r: -r["n_pv"])[:3]
    label += [r for r in kept if r["n_pv"] == 0] + excl
    for r in label:
        name = r["stem"].split("_calib")[0].replace("_", " ")
        if r["excluded"]:
            note, xy, ha = " (excluded)", (-8, -14), "right"
        elif r["n_pv"] == 0:
            note, xy, ha = " (0 installations)", (-8, -26), "right"
        else:
            note, xy, ha = f" ({r['n_pv']:,})", (8, 6), "left"
        ax.annotate(name + note, (r["lon"], r["lat"]), textcoords="offset points",
                    xytext=xy, ha=ha, fontsize=8, color=INK)

    for n in (10, 100, 1000):
        ax.scatter([], [], s=14 + 5.5 * np.sqrt(n), color=CAND_EDGE, alpha=0.75,
                   label=f"{n:,} mapped installations")
    ax.scatter([], [], s=60, facecolor="none", edgecolor=DIM, linewidth=1.4,
               label="registered, excluded from the fit")
    ax.legend(loc="lower right", fontsize=8, frameon=False, labelspacing=1.1)

    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    total = sum(r["n_pv"] for r in rows)
    fig.text(0.02, 0.97, f"{len(rows)} calibration quadrats, "
             f"{total:,} exhaustively mapped installations", fontsize=14, color=INK,
             va="top")
    fig.text(0.02, 0.935,
             "Every quadrat is declared Rule-1 complete by its mapper: each visible panel "
             "inside the boundary is mapped,\nso a roof without PV is a real negative. "
             "Marker area scales with mapped installations.",
             fontsize=8.8, color=DIM, va="top")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.90, bottom=0.01)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, facecolor="white")
    log.info("wrote %s", out.relative_to(ROOT))


# --------------------------------------------- one candidate for the metrics waterfall


def write_capacity_metrics_example() -> None:
    """A representative rooftop candidate for the det -> cal -> rc worked example.

    Deliberately only the candidate's own facts are written: its bin's measured p_real
    and recall are read from the tracked calibration YAML by the figure itself, so a
    recalibration moves the figure without this script re-running. Selection is
    deterministic: the model-geometry rooftop candidate closest to the 1k-5k bin's
    median area (a bin where both corrections visibly matter: p_real ~0.6, recall ~0.46).
    """
    cands = gpd.read_parquet(ROOT / "data/predictions/pakistan/candidates.parquet")
    sub = cands[(cands.placement == "rooftop") & (cands.geometry_source == "model")
                & (cands.area_m2 >= 1000) & (cands.area_m2 < 5000) & (~cands.oversize)]
    row = sub.iloc[(sub.area_m2 - sub.area_m2.median()).abs().argsort().iloc[0]]
    c = row.geometry.centroid
    out = RESULTS / "capacity_metrics_example.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bin", "placement", "area_m2", "confidence", "lon", "lat",
                    "n_in_bin", "kwp_per_m2_module"])
        w.writerow(["1k-5k", "rooftop", f"{row.area_m2:.0f}", f"{row.confidence:.2f}",
                    f"{c.x:.3f}", f"{c.y:.3f}", len(sub), 0.18])
    log.info("metrics example: %.0f m2 rooftop candidate at %.2fN %.2fE "
             "(median of %d in bin); wrote %s",
             row.area_m2, c.y, c.x, len(sub), out.relative_to(ROOT))


# ------------------------------------------------- the density-calibration domain band


def write_density_domain_csvs() -> None:
    """National per-cell density plus each quadrat's own density and the shipped band."""
    from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2

    cells = pd.read_parquet(ROOT / "data/roofclf/national_cell_density.parquet")
    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    inside = (cells.density >= lo) & (cells.density <= hi)
    log.info("domain band (%.1f, %.1f): %d of %d cells (%.1f%%), %.1f%% of buildings",
             lo, hi, int(inside.sum()), len(cells), 100 * inside.mean(),
             100 * cells.n_buildings[inside].sum() / cells.n_buildings.sum())

    out = RESULTS / "density_domain_cells.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell", "n_buildings", "density"])
        for r in cells.itertuples():
            w.writerow([r.cell, int(r.n_buildings), f"{r.density:.2f}"])
    log.info("wrote %s", out.relative_to(ROOT))

    # Each quadrat's own density, the same quantity sub400_capacity's
    # quadrat_building_density_km2 computes from the regenerated quadrat profile CSV.
    profile = pd.read_csv(RESULTS / "calibration_quadrats.csv")
    out = RESULTS / "density_domain_quadrats.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "density", "excluded", "band_lo", "band_hi"])
        for r in profile.itertuples():
            w.writerow([r.label, f"{r.n_buildings / r.area_km2:.2f}",
                        int(r.quadrat in EXCLUDED_QUADRATS), lo, hi])
    log.info("wrote %s (%d quadrats)", out.relative_to(ROOT), len(profile))


# ------------------------------------------------ PV size against building size


def write_pv_vs_building_csvs() -> None:
    """Mapped PV area against the roof it sits on, from the Rule-1 quadrat buildings.

    Ground-truth relationship on PV-carrying buildings (parcel label, Kalat Rural
    excluded as everywhere else). Note this is a different population from the coverage
    ratio the capacity chain applies: that one is measured over roofclf-*flagged* roofs,
    false flags included, so it sits lower than the per-building medians here.
    """
    df = pd.read_parquet(BUILDINGS, columns=["quadrat", "roof_area_m2", "pv_area_true_m2",
                                             "has_pv"])
    pv = df[(df.quadrat != "kalat_rural") & (df.has_pv == 1) & (df.pv_area_true_m2 > 0)
            & (df.roof_area_m2 > 0)].copy()
    edges = np.logspace(np.log10(10), np.log10(30000), 14)
    pv["bin"] = pd.cut(pv.roof_area_m2, edges)
    pv["cov_frac"] = pv.pv_area_true_m2 / pv.roof_area_m2
    rng = np.random.default_rng(SEED)

    out = RESULTS / "pv_size_vs_building_bins.csv"
    kept = 0
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["roof_lo", "roof_hi", "n", "roof_med", "pv_q25", "pv_med", "pv_q75",
                    "cov_q25", "cov_med", "cov_q75"])
        for iv, g in pv.groupby("bin", observed=True):
            if len(g) < 20:  # the >8,753 m2 tail has 8 buildings, too few for quartiles
                continue
            kept += len(g)
            w.writerow([f"{iv.left:.0f}", f"{iv.right:.0f}", len(g),
                        f"{g.roof_area_m2.median():.1f}",
                        f"{g.pv_area_true_m2.quantile(0.25):.1f}",
                        f"{g.pv_area_true_m2.median():.1f}",
                        f"{g.pv_area_true_m2.quantile(0.75):.1f}",
                        f"{g['cov_frac'].quantile(0.25):.3f}",
                        f"{g['cov_frac'].median():.3f}",
                        f"{g['cov_frac'].quantile(0.75):.3f}"])
    log.info("pv-vs-building: %d PV buildings, %d in binned rows; wrote %s",
             len(pv), kept, out.relative_to(ROOT))

    # A stratified sample per bin so the sparse industrial tail stays visible in the
    # scatter instead of being swamped by the residential mode.
    out = RESULTS / "pv_size_vs_building_scatter.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["roof_area_m2", "pv_area_m2"])
        for _, g in pv.groupby("bin", observed=True):
            take = g.sample(min(len(g), 250), random_state=int(rng.integers(2**31)))
            for r in take.itertuples():
                w.writerow([f"{r.roof_area_m2:.1f}", f"{r.pv_area_true_m2:.1f}"])
    log.info("wrote %s", out.relative_to(ROOT))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    write_spectral_csvs()
    build_examples_png(RESULTS / "segmentation_examples.png")
    build_placement_png(RESULTS / "candidate_placement.png")
    build_quadrat_map_png(RESULTS / "quadrat_map.png")
    write_capacity_metrics_example()
    write_density_domain_csvs()
    write_pv_vs_building_csvs()


if __name__ == "__main__":
    main()
