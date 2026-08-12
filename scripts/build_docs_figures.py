#!/usr/bin/env python
"""Regenerate every figure the documentation site and the README embed.

Run with the pixi `default` environment (matplotlib + pillow only, no GPU):

    pixi run docs-figures
    # or
    .pixi/envs/default/bin/python scripts/build_docs_figures.py

Outputs land in `docs/assets/figures/`. Each chart is written twice, as
`<name>.svg` (light) and `<name>.dark.svg` (dark), so MkDocs Material can swap
them with the `#only-light` / `#only-dark` image suffixes and the site reads
correctly in both themes.

Numbers come from files on disk wherever a file exists, so a re-run after a new
pipeline pass picks up the new values:

  * glint sensitivity      results/glint_validation_pakistan/pakistan_stats_by_size.csv
  * capacity estimators    results/pakistan_pv_estimator_atlas.html (embedded JSON)
  * calibration table      configs/calibration/pakistan_candidate_precision.yaml
  * hero capacity map      results/pakistan_pv_density_scientific.png (auto-cropped)

The one exception is the per-installation recall table, which `earthpv evaluate`
prints to stdout rather than writing to disk; it is transcribed into RECALL
below with the checkpoint it came from.

Palette: the three series slots of the interactive result pages' "night lights"
design system (amber / blue / aqua = the atlas's accent / large / domain), on the
same surfaces the docs site paints -- see docs/assets/stylesheets/extra.css, which
carries the same values as MkDocs Material variables. Slot order is fixed, so slot 1
is the primary series on every chart.
"""

from __future__ import annotations

import csv
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "figures"

_MISSING_REPORTED: set[str] = set()


def source(rel: str) -> Path | None:
    """One generated figure's input file, or None when this machine does not have it.

    `results/` is gitignored in its entirety, so a fresh checkout -- the docs CI above
    all -- carries none of the pipeline outputs these charts read, and an unguarded
    `open()` there fails the whole run before any figure is written. A missing source
    now skips just the figures that need it, says so, and leaves the committed SVG under
    `docs/assets/figures/` in place: the same degrade-and-announce behaviour
    `sync_interactive()` and `crop_hero_map()` have always had.

    Deliberately NOT used for inputs under `configs/`, which are tracked -- a missing
    file there is a real error and should still stop the run.
    """
    p = ROOT / rel
    if p.exists():
        return p
    if rel not in _MISSING_REPORTED:
        _MISSING_REPORTED.add(rel)
        print(f"  {rel} missing, skipping the figures that read it")
    return None


# --------------------------------------------------------------------------- theme


@dataclass(frozen=True)
class Theme:
    """One rendering mode. Series hues are the three atlas slots, per mode."""

    name: str
    surface: str
    ink: str
    ink_dim: str
    ink_faint: str
    rule: str
    card: str
    s1: str
    s2: str
    s3: str


# `surface` is the page background these charts sit directly on, and `card` the panel
# fill the diagram boxes use, so both are the `--pv-page` / `--pv-panel` values from
# docs/assets/stylesheets/extra.css. `rule` is that stylesheet's hairline flattened
# against the surface and pushed a little harder, since a gridline has to read on its
# own where a table border has cell text next to it.
LIGHT = Theme("light", "#f1ebdd", "#2a2216", "#5f5540", "#857a61", "#cfc0a5", "#faf6ec",
              "#c25e12", "#1c6fa8", "#1f9b8a")
DARK = Theme("dark", "#100d09", "#f7f1e6", "#c9bda4", "#93866c", "#3a2d16", "#1a160f",
             "#f5a623", "#4fb2e8", "#2fd9c4")
THEMES = (LIGHT, DARK)


def new_fig(t: Theme, w: float, h: float):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(t.surface)
    ax.set_facecolor(t.surface)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=t.ink_dim, labelsize=9, length=0)
    return fig, ax


def style_axes(ax, t: Theme, *, xgrid=False, ygrid=False):
    ax.grid(axis="y" if ygrid else "x", visible=xgrid or ygrid,
            color=t.rule, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(t.ink_dim)


def save(fig, t: Theme, stem: str):
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = ".svg" if t.name == "light" else ".dark.svg"
    path = OUT / f"{stem}{suffix}"
    fig.savefig(path, format="svg", facecolor=t.surface, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")


def titled(fig, t: Theme, title: str, subtitle: str = "", width: int = 96):
    """Left-aligned title block above the axes, wrapped so it never collides."""
    h = fig.get_size_inches()[1]
    line = 0.19 / h  # one 9.5pt line, in figure-height units
    lines = textwrap.wrap(subtitle, width) if subtitle else []
    top = 1.0 + (len(lines) + 1.4) * line
    fig.text(0.0, top, title, ha="left", va="baseline", color=t.ink,
             fontsize=12.5, fontweight="bold")
    for i, ln in enumerate(lines):
        fig.text(0.0, top - (i + 1.15) * line, ln, ha="left", va="baseline",
                 color=t.ink_dim, fontsize=9.5)


plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "none",
    "figure.dpi": 110,
})


# ------------------------------------------------------------------- source data

# Per-installation recall at threshold 0.3, checkpoint v2_combined/terramind-pv-epoch=39.
# Printed by `earthpv evaluate`; transcribed because that stage has no file output.
RECALL = {
    "buckets": ["250 - 500", "500 - 1000", ">= 1000"],
    "germany": [0.95, 0.84, 0.83],
    "punjab": [0.14, 0.16, 0.55],
    "punjab_germany_only": [None, None, 0.18],
}


def read_glint_by_size():
    path = source("results/glint_validation_pakistan/pakistan_stats_by_size.csv")
    if path is None:
        return None
    rows = list(csv.DictReader(path.open()))
    return {
        "buckets": [r["bucket"] for r in rows],
        "n": [int(float(r["n"])) for r in rows],
        "detected": [float(r["pct_detected"]) for r in rows],
        "validated": [float(r["pct_validated"]) for r in rows],
    }


def read_glint_observability():
    """Per-quadrat glint observability ceiling (scripts/glint_observability_ceiling.py)."""
    path = source("results/glint_observability_by_quadrat.csv")
    if path is None:
        return None
    rows = [r for r in csv.DictReader(path.open()) if int(r["n_scenes"]) > 0]
    rows.sort(key=lambda r: -float(r["ever_textbook_south"]))
    return rows


def read_glint_date_auc():
    """Standalone and incremental AUC for the glint-date feature (Step 2)."""
    base = source("results/glint_date_feature")
    if base is None:
        return None
    standalone = list(csv.DictReader((base / "standalone_auc.csv").open()))
    inc = list(csv.DictReader((base / "incremental_auc.csv").open()))
    means: dict[str, list[float]] = {}
    for r in inc:
        means.setdefault(r["features"], []).append(float(r["auc_within_size"]))
    return standalone, {k: sum(v) / len(v) for k, v in means.items()}


def fig_glint_observability(t: Theme):
    """Why a predicted glint date cannot rescue small-PV detection: almost no installed
    pose can ever glint into Sentinel-2's near-nadir view."""
    rows = read_glint_observability()
    if rows is None:
        return
    fig, ax = new_fig(t, 6.9, 4.2)
    y = range(len(rows))
    ever = [100 * float(r["ever_textbook_south"]) for r in rows]
    best = [100 * float(r["best_date_lit_frac"]) for r in rows]
    ax.barh(list(y), ever, 0.62, color=t.s2, label="could ever glint, any date", zorder=3)
    ax.barh(list(y), best, 0.62, color=t.s1, label="glint on the single best date", zorder=4)
    for i, (e, b) in enumerate(zip(ever, best)):
        ax.text(e + 0.4, i, f"{e:.0f}%", va="center", color=t.ink, fontsize=8.5)
    ax.set_yticks(list(y))
    ax.set_yticklabels([r["quadrat"].replace("_", " ") for r in rows], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, max(ever) * 1.18)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    style_axes(ax, t, xgrid=True)
    leg = ax.legend(frameon=False, loc="lower right", fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "Almost no rooftop can ever glint into Sentinel-2",
           "Share of an assumed south-facing installed population (tilt 25+-8 deg) whose pose "
           "satisfies the specular condition on any scene in two years, per calibration "
           "quadrat, from real granule sun and view angles")
    save(fig, t, "glint_observability")


def fig_glint_pose_window(t: Theme):
    """The observable pose band itself: required tilt/azimuth per scene against where
    panels are actually installed."""
    import json as _json

    path = source("results/glint_observability_summary.json")
    if path is None:
        return
    data = _json.loads(path.read_text())
    scenes = data["per_quadrat_scenes"].get("lahore") or next(
        iter(data["per_quadrat_scenes"].values()))
    fig, ax = new_fig(t, 6.4, 3.9)
    ax.scatter(scenes["req_az"], scenes["req_tilt"], s=16, color=t.s1, alpha=0.85,
               zorder=4, label="pose that glints on some real Sentinel-2 scene")
    # The installed population this would have to overlap to be useful.
    rng = np.random.default_rng(0)
    ax.scatter(rng.normal(180, 25, 900), rng.normal(25, 8, 900).clip(0, 60), s=7,
               color=t.s2, alpha=0.30, zorder=3, label="assumed installed poses (south, tilt~25)")
    ax.set_xlabel("panel azimuth (deg from north)", color=t.ink_dim, fontsize=9)
    ax.set_ylabel("panel tilt (deg)", color=t.ink_dim, fontsize=9)
    ax.set_xlim(60, 300)
    ax.set_ylim(0, 55)
    style_axes(ax, t, xgrid=True, ygrid=True)
    leg = ax.legend(frameon=False, loc="upper right", fontsize=8.5)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "The glint window barely overlaps how panels are actually mounted",
           "Each amber point is the one panel pose that would reflect the sun into the sensor "
           "on one real Lahore scene. A panel only glints if its installed pose lands on that "
           "narrow locus.")
    save(fig, t, "glint_pose_window")


def fig_glint_date_auc(t: Theme):
    """The measured outcome: a glint-date feature adds nothing to roofclf."""
    read = read_glint_date_auc()
    if read is None:
        return
    standalone, inc_means = read
    fig, ax = new_fig(t, 6.6, 3.2)
    order = ["baseline (size+reflectance)", "+ glint_ratio", "+ glint_excess",
             "+ glint_max both bands"]
    labels = ["roofclf as it is\n(size + reflectance)", "+ glint / composite\nratio",
              "+ glint excess\nover composite", "+ glint max,\nboth bands"]
    vals = [inc_means[k] for k in order if k in inc_means]
    x = range(len(vals))
    colors = [t.s3] + [t.s1] * (len(vals) - 1)
    ax.bar(list(x), vals, 0.5, color=colors, zorder=3)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.004, f"{v:.4f}", ha="center", color=t.ink, fontsize=9.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels[:len(vals)], fontsize=8.5)
    lo = min(vals)
    ax.set_ylim(lo - 0.03, max(vals) + 0.03)
    ax.set_ylabel("size-controlled AUC, spatial holdout", color=t.ink_dim, fontsize=9)
    style_axes(ax, t, ygrid=True)
    titled(fig, t, "Glint-date imagery adds nothing to the roof classifier",
           "Lahore quadrat, 13,500 buildings, trained on one half and tested on the other. "
           "Every glint-date feature moves size-controlled AUC by less than 0.0005.")
    save(fig, t, "glint_date_auc")


def read_estimator_totals():
    """Pull the six capacity estimates out of the atlas page's embedded JSON."""
    path = source("results/pakistan_pv_estimator_atlas.html")
    if path is None:
        return None
    html = path.read_text()
    m = re.search(r'id="pvdata"[^>]*>(.*?)</script>', html, flags=re.S)
    if not m:
        raise SystemExit("could not locate the atlas data block")
    return json.loads(m.group(1))["totals"]


def read_calibration_recall():
    """Measured per-size-bin model recall + credible band from the calibration table."""
    text = (ROOT / "configs/calibration/pakistan_candidate_precision.yaml").read_text()
    bins, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- label:"):
            cur = {"label": s.split(":", 1)[1].strip()}
            bins.append(cur)
        elif cur is not None and ":" in s and s.startswith(("recall", "n_candidates")):
            k, v = s.split(":", 1)
            try:
                cur[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return [b for b in bins if "recall" in b]


# ----------------------------------------------------------------------- figures


def fig_recall_by_size(t: Theme):
    fig, ax = new_fig(t, 6.6, 3.1)
    b = RECALL["buckets"]
    x = range(len(b))
    w = 0.34
    gap = 0.012  # 2px surface gap between adjacent fills at this figure scale
    ax.bar([i - w / 2 - gap for i in x], RECALL["germany"], w, color=t.s1,
           label="Germany validation states", zorder=3)
    ax.bar([i + w / 2 + gap for i in x], RECALL["punjab"], w, color=t.s2,
           label="Punjab validation cells", zorder=3)
    for i, (g, p) in enumerate(zip(RECALL["germany"], RECALL["punjab"])):
        ax.text(i - w / 2 - gap, g + 0.03, f"{g:.2f}", ha="center", color=t.ink, fontsize=9)
        ax.text(i + w / 2 + gap, p + 0.03, f"{p:.2f}", ha="center", color=t.ink, fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{s} m$^2$" for s in b])
    ax.set_ylim(0, 1.30)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    style_axes(ax, t, ygrid=True)
    leg = ax.legend(frameon=False, loc="upper right", fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "Detection recall holds in Germany, drops on Pakistani rooftops",
           "Share of real installations recovered by at least one candidate, threshold 0.3, "
           "checkpoint v2_combined")
    save(fig, t, "recall_by_size")


def fig_glint_by_size(t: Theme):
    d = read_glint_by_size()
    if d is None:
        return
    fig, ax = new_fig(t, 6.8, 3.3)
    x = range(len(d["buckets"]))
    w = 0.34
    gap = 0.012
    ax.bar([i - w / 2 - gap for i in x], d["detected"], w, color=t.s1,
           label="at least one glint spike", zorder=3)
    ax.bar([i + w / 2 + gap for i in x], d["validated"], w, color=t.s2,
           label="spikes fit one fixed panel pose", zorder=3)
    ax.axhline(8.7, color=t.s3, linewidth=2, zorder=4)
    ax.text(1.42, 62, "8.7% false-validation floor (green line),\n"
            "measured on 69 control roofs with no PV",
            fontsize=8.5, color=t.s3, ha="left", va="bottom")
    for i, (det, val) in enumerate(zip(d["detected"], d["validated"])):
        ax.text(i - w / 2 - gap, det + 1.4, f"{det:.0f}", ha="center", color=t.ink, fontsize=9)
        ax.text(i + w / 2 + gap, val + 1.4, f"{val:.0f}", ha="center", color=t.ink, fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{b}\nn={n}" for b, n in zip(d["buckets"], d["n"])], fontsize=8.5)
    ax.set_ylim(0, 96)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    style_axes(ax, t, ygrid=True)
    leg = ax.legend(frameon=False, loc="upper left", fontsize=9,
                    bbox_to_anchor=(-0.02, 1.02))
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "Solar glint confirms PV, and does so more often on bigger arrays",
           "500 OSM-confirmed Pakistani installations, two years of Sentinel-2, "
           "grouped by installation area (m$^2$)")
    save(fig, t, "glint_by_size")


ESTIMATORS = [
    # (label, index into the atlas totals array, CI key or None, scope)
    ("Detected, rooftop", 0, None, "roof"),
    ("Calibrated, rooftop (headline)", 1, None, "roof"),
    ("Expected, rooftop", 2, None, "roof"),
    ("Recall-corrected, rooftop", 3, "rcr_ci", "roof"),
    ("Calibrated, all PV", 4, "ct_ci", "all"),
    ("Recall-corrected, all PV", 5, "rc_ci", "all"),
]


def fig_capacity_estimators(t: Theme):
    tot = read_estimator_totals()
    if tot is None:
        return
    fig, ax = new_fig(t, 7.6, 3.6)
    labels = [e[0] for e in ESTIMATORS]
    ends = [max(tot["m"][e[1]], tot[e[2]][1] if e[2] else 0) / 1000.0 for e in ESTIMATORS]
    ys = list(range(len(ESTIMATORS)))[::-1]
    for y, (label, idx, ci, scope) in zip(ys, ESTIMATORS):
        v = tot["m"][idx] / 1000.0
        col = t.s1 if scope == "roof" else t.s2
        ax.barh(y, v, height=0.46, color=col, zorder=3)
        end = v
        if ci:
            lo, hi = tot[ci][0] / 1000.0, tot[ci][1] / 1000.0
            ax.plot([lo, hi], [y, y], color=t.ink_dim, linewidth=1.5, zorder=4)
            for b in (lo, hi):
                ax.plot([b, b], [y - 0.12, y + 0.12], color=t.ink_dim, linewidth=1.5, zorder=4)
            end = hi
        ax.text(end + 0.45, y, f"{v:.1f} GWp", va="center", color=t.ink, fontsize=9.5)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=9.5)
    ax.set_ylim(-1.15, len(ESTIMATORS) - 0.4)
    ax.set_xlim(0, max(ends) * 1.22)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_xlabel("GWp", color=t.ink_dim, fontsize=9)
    style_axes(ax, t, xgrid=True)
    ax.grid(axis="x", color=t.rule, linewidth=0.8, zorder=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=t.s1),
               plt.Rectangle((0, 0), 1, 1, color=t.s2)]
    leg = ax.legend(handles, ["rooftop scope", "all PV, ground-mount farms included"],
                    frameon=False, loc="lower left", fontsize=9, ncol=2,
                    bbox_to_anchor=(0.0, -0.05), handlelength=1.1)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    # Two conversion constants since the placement split; older atlas payloads carry one.
    conv = (
        f"{tot['kwp']} kWp/m$^2$ rooftop module area, {tot['kwpLand']} kWp/m$^2$ "
        "ground-mount site area"
        if tot.get("kwpLand") else f"{tot['kwp']} kWp/m$^2$"
    )
    titled(fig, t, "One model, six defensible answers to “how much PV?”",
           f"Pakistan, {tot['n_cells']:,} grid cells, {conv}, run {tot['run_date']}. "
           "Whiskers are 90% credible intervals.")
    save(fig, t, "capacity_estimators")


def fig_model_recall_bins(t: Theme):
    bins = read_calibration_recall()
    fig, ax = new_fig(t, 6.6, 3.0)
    labels = [b["label"].strip("'\"") for b in bins]
    vals = [b["recall"] * 100 for b in bins]
    los = [b.get("recall_lo", b["recall"]) * 100 for b in bins]
    his = [b.get("recall_hi", b["recall"]) * 100 for b in bins]
    x = list(range(len(bins)))
    ax.bar(x, vals, 0.52, color=t.s1, zorder=3)
    for i, (v, lo, hi) in enumerate(zip(vals, los, his)):
        ax.plot([i, i], [lo, hi], color=t.ink_dim, linewidth=1.5, zorder=4)
        ax.text(i, hi + 3, f"{v:.0f}%", ha="center", color=t.ink, fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s} m$^2$" for s in labels], fontsize=9)
    ax.set_ylim(0, 112)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    style_axes(ax, t, ygrid=True)
    titled(fig, t, "Measured model recall by installation size",
           "Share of a pre-pipeline OpenStreetMap reference matched by a candidate. "
           "This curve is what the recall correction divides by.")
    save(fig, t, "model_recall_bins")


INSTRUMENTS = [
    # row label, lo m2, hi m2, colour slot, note under the bar
    ("Aggregate density\nestimate", 20, 3_000_000, "s3",
     "capacity per building, cell and district; no per-object geometry"),
    ("Individual detection\nas polygons", 400, 3_000_000, "s1",
     "exported as leads, verified by mappers in OpenStreetMap"),
    ("Glint existence\nand pose check", 1_000, 3_000_000, "s2",
     "confirms one fixed panel plane; no discrimination below 500 m$^2$"),
]


def fig_size_spectrum(t: Theme):
    fig, ax = new_fig(t, 7.8, 3.2)
    ax.set_xscale("log")
    n = len(INSTRUMENTS)
    for i, (label, lo, hi, slot, note) in enumerate(INSTRUMENTS):
        y = n - 1 - i
        ax.barh(y, hi - lo, left=lo, height=0.30, color=getattr(t, slot), zorder=3)
        ax.text(lo * 1.18, y - 0.27, note, color=t.ink_dim, fontsize=8.5, va="top",
                zorder=6, bbox=dict(facecolor=t.surface, edgecolor="none", pad=1.5))
    ax.axvline(400, color=t.ink, linewidth=1.1, linestyle=(0, (4, 3)), zorder=5)
    ax.annotate("400 m$^2$, roughly four Sentinel-2 pixels:\n"
                "the floor for outlining an array at all",
                xy=(400, n - 0.62), xytext=(560, n - 0.30), fontsize=8.5, color=t.ink,
                ha="left", va="top",
                arrowprops=dict(arrowstyle="-", color=t.ink, linewidth=0.9))
    ax.set_xlim(20, 3_000_000)
    ax.set_ylim(-0.72, n - 0.20)
    ax.set_yticks(list(range(n))[::-1])
    ax.set_yticklabels([r[0] for r in INSTRUMENTS], fontsize=9.5)
    for lbl in ax.get_yticklabels():
        lbl.set_color(t.ink)
    ax.set_xticks([100, 1_000, 10_000, 100_000, 1_000_000])
    ax.set_xticklabels(["100 m$^2$\nsmall rooftop", "1,000 m$^2$\nlarge rooftop",
                        "1 ha\ncommercial", "10 ha", "100 ha\nutility plant"], fontsize=8.5)
    ax.grid(axis="x", color=t.rule, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    titled(fig, t, "Which instrument covers which installation size",
           "Sentinel-2 samples the ground at 10 m. Below 400 m$^2$ an array is a handful of "
           "mixed pixels, so it is counted rather than outlined.")
    save(fig, t, "size_spectrum")


def read_pose_points():
    """Fitted (tilt, azimuth) pairs, read out of the pose survey page."""
    path = source("results/glint_validation_pakistan/pv_pose_country2000.html")
    if path is None:
        return None
    html = path.read_text()
    m = re.search(r'id="pvdata"[^>]*>(.*?)</script>', html, flags=re.S)
    if not m:
        raise SystemExit("could not locate the pose data block")
    return json.loads(m.group(1))


def fig_pv_pose(t: Theme):
    """Polar view of the fitted panel poses: tilt as radius, azimuth as angle."""
    import math

    d = read_pose_points()
    if d is None:
        return
    fig = plt.figure(figsize=(6.4, 5.6))
    fig.patch.set_facecolor(t.surface)
    ax = fig.add_subplot(projection="polar")
    ax.set_facecolor(t.surface)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    lo, hi = d["wedge"]
    mid = math.radians((lo + hi) / 2 % 360)
    ax.bar(x=math.radians((lo + hi) / 2), height=32, width=math.radians(hi - lo),
           bottom=0, color=t.rule, alpha=0.55, zorder=0, linewidth=0)
    ax.text(mid, 25, "never reachable\nfrom this orbit", ha="center",
            va="center", fontsize=8, color=t.ink_dim, zorder=6)

    groups = [("rooftop", "rooftop generator", t.s1), ("ground", "ground plant", t.s2)]
    for placement, label, col in groups:
        pts = [p for p in d["points"] if p["pl"] == placement]
        if not pts:
            continue
        ax.scatter([math.radians(p["az"]) for p in pts], [p["t"] for p in pts],
                   s=[max(9, min(90, p["a"] * 1.1)) for p in pts],
                   color=col, linewidths=0, label=label, alpha=0.85, zorder=3)

    ax.set_rlim(0, 32)
    ax.set_rticks([10, 20, 30])
    ax.set_rlabel_position(8)
    ax.set_yticklabels(["10", "20", "30 deg tilt"], fontsize=8, color=t.ink_dim)
    ax.set_xticks([math.radians(a) for a in range(0, 360, 45)])
    ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                       fontsize=9, color=t.ink_dim)
    ax.grid(color=t.rule, linewidth=0.8)
    ax.spines["polar"].set_color(t.rule)
    leg = ax.legend(frameon=False, fontsize=8.5, loc="lower center",
                    bbox_to_anchor=(0.5, -0.20), ncol=2)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "How Pakistani solar panels are actually mounted",
           "Fitted tilt and azimuth for 290 installations whose Sentinel-2 glints agree on "
           "one fixed panel plane, out of 2,000 checked. The shaded wedge is unreachable by "
           "this sensor's fixed overpass time, not known to be empty.", width=76)
    save(fig, t, "pv_pose_polar")


# ----------------------------------------------------- hand-authored SVG diagrams

FLYWHEEL = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="480"
     viewBox="0 0 900 480" font-family="DejaVu Sans, system-ui, sans-serif">
  <defs>
    <marker id="a{sfx}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
            orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="{s1}"/>
    </marker>
    <marker id="b{sfx}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
            orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="{s2}"/>
    </marker>
  </defs>
  <rect width="900" height="480" rx="10" fill="{surface}"/>
  <text x="50" y="42" font-size="17" font-weight="600" fill="{ink}">The mapping flywheel</text>
  <text x="50" y="64" font-size="12" fill="{dim}">Every turn leaves the training data larger, cleaner and more local.</text>

  <g stroke="{s1}" stroke-width="2" fill="none" marker-end="url(#a{sfx})">
    <path d="M432,148 H466"/>
    <path d="M660,196 V266"/>
  </g>
  <g stroke="{s2}" stroke-width="2" fill="none" marker-end="url(#b{sfx})">
    <path d="M468,330 H434"/>
    <path d="M240,266 V200"/>
  </g>

  <rect x="50" y="102" width="382" height="94" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="72" y="132" font-size="13" font-weight="600" fill="{ink}">1. OpenStreetMap labels</text>
  <text x="72" y="154" font-size="11" fill="{dim}">Solar polygons drawn by mappers, pulled live</text>
  <text x="72" y="172" font-size="11" fill="{dim}">through Overpass or Overture Maps.</text>

  <rect x="468" y="102" width="382" height="94" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="490" y="132" font-size="13" font-weight="600" fill="{ink}">2. Fine-tune TerraMind on Sentinel-2</text>
  <text x="490" y="154" font-size="11" fill="{dim}">Free 10 m imagery, worldwide, every five days.</text>
  <text x="490" y="172" font-size="11" fill="{dim}">No commercial tile licence in the way.</text>

  <rect x="468" y="266" width="382" height="128" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="490" y="296" font-size="13" font-weight="600" fill="{ink}">3. Rank candidates, publish leads</text>
  <text x="490" y="318" font-size="11" fill="{dim}">Recall-first. A building prior, glint corroboration,</text>
  <text x="490" y="336" font-size="11" fill="{dim}">a pre-boom epoch check and a vegetation veto</text>
  <text x="490" y="354" font-size="11" fill="{dim}">reorder the queue; a MapRoulette challenge</text>
  <text x="490" y="372" font-size="11" fill="{dim}">carries it to mappers.</text>

  <rect x="50" y="266" width="382" height="128" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="72" y="296" font-size="13" font-weight="600" fill="{ink}">4. People verify what the model found</text>
  <text x="72" y="318" font-size="11" fill="{dim}">Local mappers open each lead in the OpenStreetMap</text>
  <text x="72" y="336" font-size="11" fill="{dim}">editor, check it against Esri, Bing and Mapbox</text>
  <text x="72" y="354" font-size="11" fill="{dim}">imagery, then map it properly with local context.</text>
  <text x="72" y="376" font-size="11" fill="{s2}">Verified installations become the next training labels.</text>

  <text x="676" y="236" font-size="11" fill="{s1}">detections out</text>
  <text x="256" y="236" font-size="11" fill="{s2}">verified labels back in</text>
  <text x="50" y="440" font-size="11" fill="{dim}">Only free and openly licensed imagery reaches the model. The high-resolution</text>
  <text x="50" y="458" font-size="11" fill="{dim}">layers are used by people, inside the editor, where their licences allow it.</text>
</svg>
"""

PIPELINE_STRIP = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="214"
     viewBox="0 0 900 214" font-family="DejaVu Sans, system-ui, sans-serif">
  <rect width="900" height="214" rx="10" fill="{surface}"/>
  <text x="30" y="34" font-size="14" font-weight="600" fill="{ink}">Two products from one model</text>

  <rect x="30" y="56" width="180" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="48" y="82" font-size="12" font-weight="600" fill="{ink}">Sentinel-2 L2A</text>
  <text x="48" y="100" font-size="10.5" fill="{dim}">dry-season composites</text>

  <rect x="238" y="56" width="180" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="256" y="82" font-size="12" font-weight="600" fill="{ink}">TerraMind-tiny</text>
  <text x="256" y="100" font-size="10.5" fill="{dim}">probability raster</text>

  <rect x="446" y="26" width="204" height="60" rx="7" fill="{card}" stroke="{s1}"/>
  <text x="464" y="52" font-size="12" font-weight="600" fill="{s1}">Leads product</text>
  <text x="464" y="70" font-size="10.5" fill="{dim}">polygons for human review</text>

  <rect x="446" y="116" width="204" height="60" rx="7" fill="{card}" stroke="{s3}"/>
  <text x="464" y="142" font-size="12" font-weight="600" fill="{s3}">Capacity product</text>
  <text x="464" y="160" font-size="10.5" fill="{dim}">MWp per building and cell</text>

  <rect x="678" y="26" width="192" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="696" y="52" font-size="12" font-weight="600" fill="{ink}">OpenStreetMap</text>
  <text x="696" y="70" font-size="10.5" fill="{dim}">MapRoulette challenge</text>

  <rect x="678" y="116" width="192" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="696" y="142" font-size="12" font-weight="600" fill="{ink}">PyPSA-Earth</text>
  <text x="696" y="160" font-size="10.5" fill="{dim}">0.1 degree grid CSV</text>

  <g stroke="{dim}" stroke-width="1.6" fill="none">
    <path d="M210,86 H236"/>
    <path d="M418,86 H432 V56 H444"/>
    <path d="M418,86 H432 V146 H444"/>
  </g>
  <g stroke="{s1}" stroke-width="1.6" fill="none"><path d="M650,56 H676"/></g>
  <g stroke="{s3}" stroke-width="1.6" fill="none"><path d="M650,146 H676"/></g>

  <text x="30" y="200" font-size="10.5" fill="{dim}">False positives are useful on the top path and forbidden on the bottom one, so only the bottom path is precision-calibrated.</text>
</svg>
"""


# ---------------------------------------------------- generated architecture diagram
#
# Unlike FLYWHEEL/PIPELINE_STRIP above, this one is built programmatically: too many
# boxes (18) and cross-lane arrows to hand-place reliably as a static template.

ARCH_W = 1200
ARCH_MARGIN = 40


def _row_x(n, gap=20, x0=ARCH_MARGIN, width=ARCH_W - 2 * ARCH_MARGIN):
    bw = (width - gap * (n - 1)) / n
    return [x0 + i * (bw + gap) for i in range(n)], bw


def _elbow(sx, sy, tx, ty):
    mid = (sy + ty) / 2
    return f"M{sx:.0f},{sy:.0f} V{mid:.0f} H{tx:.0f} V{ty:.0f}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _svg_box(parts, boxes, t: Theme, key, x, y, w, h, title, lines, stroke=None):
    """Draw one labelled card and remember its rectangle under `key`.

    Shared by both generated diagrams (architecture, roofclf) so a palette or padding
    change lands on both at once; the arrow routing is what actually differs between
    them, and that stays local to each builder.
    """
    boxes[key] = (x, y, w, h)
    s = stroke or t.rule
    sw = 1.8 if stroke else 1.1
    parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="8" '
                 f'fill="{t.card}" stroke="{s}" stroke-width="{sw}"/>')
    parts.append(f'<text x="{x + 16:.0f}" y="{y + 23:.0f}" font-size="12.2" '
                 f'font-weight="600" fill="{t.ink}">{_esc(title)}</text>')
    for i, ln in enumerate(lines):
        parts.append(f'<text x="{x + 16:.0f}" y="{y + 23 + 17 * (i + 1):.0f}" '
                     f'font-size="10.1" fill="{t.ink_dim}">{_esc(ln)}</text>')


def _svg_anchor(boxes, k, side):
    x, y, w, h = boxes[k]
    return {
        "top": (x + w / 2, y),
        "bottom": (x + w / 2, y + h),
        "left": (x, y + h / 2),
        "right": (x + w, y + h / 2),
    }[side]


def _svg_markers(t: Theme) -> list[str]:
    """Arrowhead markers, one per series colour. Ids carry the theme name because both
    SVGs of a pair can end up in one DOM (the light/dark image pair) and a duplicated
    marker id would make one of them pick the other's colour."""
    return [
        f'<marker id="ah-{color.lstrip("#")}-{t.name}" viewBox="0 0 10 10" refX="9" '
        f'refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
        for color in (t.ink_dim, t.s1, t.s2, t.s3)
    ]


def build_architecture_svg(t: Theme) -> str:
    boxes: dict[str, tuple[float, float, float, float]] = {}
    parts: list[str] = []

    def box(key, x, y, w, h, title, lines, stroke=None):
        _svg_box(parts, boxes, t, key, x, y, w, h, title, lines, stroke)

    def anchor(k, side):
        return _svg_anchor(boxes, k, side)

    def arrow(k1, k2, color, *, dashed=False, from_side="bottom", to_side="top",
              route=None, label=None):
        sx, sy = anchor(k1, from_side)
        tx, ty = anchor(k2, to_side)
        label_xy = None
        if route == "under":
            drop = max(sy, ty) + 22
            path = f"M{sx:.0f},{sy:.0f} V{drop:.0f} H{tx:.0f} V{ty:.0f}"
            label_xy = ((sx + tx) / 2, drop + 13)
        elif route == "loop-left":
            gx, turn_y = 18, 204
            path = f"M{sx:.0f},{sy:.0f} H{gx} V{turn_y} H{tx:.0f} V{ty:.0f}"
            label_xy = ((gx + tx) / 2, turn_y - 7)
        elif from_side == "right" and to_side == "left" and abs(sy - ty) < 1:
            path = f"M{sx:.0f},{sy:.0f} H{tx:.0f}"
        else:
            path = _elbow(sx, sy, tx, ty)
        dash = ' stroke-dasharray="6,4"' if dashed else ""
        marker_id = f"ah-{color.lstrip('#')}-{t.name}"
        parts.append(f'<path d="{path}" stroke="{color}" stroke-width="1.7" fill="none" '
                     f'marker-end="url(#{marker_id})"{dash}/>')
        if label:
            mx, my = label_xy if label_xy else ((sx + tx) / 2, (sy + ty) / 2 - 6)
            parts.append(f'<text x="{mx:.0f}" y="{my:.0f}" font-size="9.2" fill="{color}" '
                         f'text-anchor="middle">{_esc(label)}</text>')

    def lane_label(text, y):
        parts.append(f'<text x="{ARCH_MARGIN}" y="{y:.0f}" font-size="11.3" '
                     f'font-weight="600" fill="{t.ink_dim}">{_esc(text)}</text>')

    def note(text, y, x=ARCH_MARGIN):
        parts.append(f'<text x="{x}" y="{y:.0f}" font-size="9.6" font-style="italic" '
                     f'fill="{t.ink_dim}">{_esc(text)}</text>')

    # ---- layout: 6 lanes, top to bottom -------------------------------------------

    title = "How raw data becomes a mapping lead and a capacity number"
    subtitle = ("Five instruments read the same Sentinel-2 composites and combine into two "
                "products: OpenStreetMap mapping leads and a calibrated capacity atlas.")
    parts.append(f'<text x="{ARCH_MARGIN}" y="38" font-size="17.5" font-weight="600" '
                 f'fill="{t.ink}">{_esc(title)}</text>')
    parts.append(f'<text x="{ARCH_MARGIN}" y="60" font-size="12" fill="{t.ink_dim}">'
                 f'{_esc(subtitle)}</text>')

    # Lane A - raw data
    lane_label("Raw data", 84)
    xa, wa = _row_x(3, gap=50)
    box("a1", xa[0], 90, wa, 84, "Sentinel-2 L2A",
        ["10-band dry-season composites,", "reused per tile or built on demand", "by compose"])
    box("a2", xa[1], 90, wa, 84, "OSM / Overture solar labels",
        ["mapped installations, plus live", "Overpass pulls for new areas"])
    box("a3", xa[2], 90, wa, 84, "VIDA / Overture buildings",
        ["imagery-derived footprints,", "includes small unmapped roofs"])

    # Lane B - train
    lane_label("Train", 228)
    xb, wb = _row_x(2, gap=80)
    box("b1", xb[0], 234, wb, 84, "chips",
        ["jittered positive windows,", "labels burned to per-pixel masks"])
    box("b2", xb[1], 234, wb, 84, "TerraMind-tiny fine-tune",
        ["TerraTorch + Lightning,", "checkpoint monitors val mIoU"])

    # Lane C - inference signals
    lane_label("Inference — five instruments, same Sentinel-2 imagery", 372)
    xc, wc = _row_x(5, gap=20)
    box("c1", xc[0], 378, wc, 106, "Segmentation raster", ["infer: per-pixel PV", "probability, primary", "≥ 400 m² instrument"], stroke=t.s1)
    box("c2", xc[1], 378, wc, 106, "Fraction head", ["alt checkpoint: per-pixel", "PV coverage fraction,", "drops the polygon"], stroke=t.s3)
    box("c3", xc[2], 378, wc, 106, "Glint matched filter", ["specular flash geometry,", "corroborates only", "(never demotes)"], stroke=t.s2)
    box("c4", xc[3], 378, wc, 106, "SPPI", ["zero-training spectral", "index, cross-validated,", "no model fit"], stroke=t.s3)
    box("c5", xc[4], 378, wc, 106, "roofclf", ["per-building classifier:", "size + reflectance,", "calibration quadrats"], stroke=t.s1)
    note("Glint and SPPI read the composites directly, no model fit; segmentation and the fraction head share one TerraMind checkpoint; roofclf trains separately on calibration-quadrat labels.", 502)

    # Lane D - combine and rank
    lane_label("Combine & rank", 538)
    xd, wd = _row_x(3, gap=50)
    box("d1", xd[0], 544, wd, 100, "postprocess",
        ["polygonize, join to building", "footprint, rank_score for", "the leads queue"])
    box("d2", xd[1], 544, wd, 100, "density",
        ["per-building / cell / region", "MWp: _det / _exp / _cal,", "≥ 400 m² only"])
    box("d3", xd[2], 544, wd, 100, "sub-400 m² bracket",
        ["domain-restricted roofclf +", "SPPI AND-gate, building-", "density-matched cells"])

    # Lane E - plausibility gate
    lane_label("Plausibility gate", 664)
    ew, ex = 460.0, (ARCH_W - 460.0) / 2
    box("e1", ex, 670, ew, 62, "check-density",
        ["ground:rooftop capacity ratio + single-cell concentration checks"], stroke=t.s2)

    # Lane F - outputs
    lane_label("Outputs", 780)
    xf, wf = _row_x(4, gap=20)
    box("f1", xf[0], 786, wf, 94, "MapRoulette leads",
        ["→ OpenStreetMap,", "a human verifies every", "candidate"], stroke=t.s1)
    box("f2", xf[1], 786, wf, 94, "Capacity atlas / dashboard",
        ["MWp per building, cell", "and region, ≥ 400 m²"], stroke=t.s3)
    box("f3", xf[2], 786, wf, 94, "PyPSA-Earth grid CSV",
        ["0.1° cell capacity for", "power-system modelling"], stroke=t.s3)
    box("f4", xf[3], 786, wf, 94, "Evidence atlas",
        ["Verified / Best estimate /", "Ceiling tiers, sub-400 m²", "plus ≥ 400 m²"], stroke=t.s2)

    note("Building footprints also feed roofclf and the sub-400 m² bracket directly (arrows omitted for clarity).", 936)
    note("Solid grey = the main trunk. Blue = load-bearing instruments. Orange = glint, corroborates only. Aqua = auxiliary instruments not (yet) in the headline number.", 954)

    # ---- arrows -------------------------------------------------------------------

    arrow("a1", "b1", t.ink_dim)
    arrow("a2", "b1", t.ink_dim)
    arrow("b1", "b2", t.ink_dim, from_side="right", to_side="left")
    arrow("b2", "c1", t.ink_dim)
    arrow("c1", "d1", t.s1)
    arrow("c1", "d2", t.s1)
    arrow("c2", "d2", t.s3, dashed=True)
    arrow("c3", "d1", t.s2)
    arrow("c4", "d3", t.s3)
    arrow("c5", "d3", t.s1)
    arrow("d1", "f1", t.ink_dim)
    arrow("d2", "e1", t.ink_dim)
    arrow("e1", "f2", t.ink_dim)
    arrow("f2", "f3", t.ink_dim, from_side="right", to_side="left")
    arrow("f2", "f4", t.ink_dim, from_side="bottom", to_side="bottom", route="under",
          label="+ existing ≥ 400 m² total")
    arrow("d3", "f4", t.s2)
    arrow("f1", "a2", t.s2, dashed=True, from_side="left", to_side="bottom", route="loop-left",
          label="verified leads become new training labels")

    markers = _svg_markers(t)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ARCH_W}" height="988" '
        f'viewBox="0 0 {ARCH_W} 988" font-family="DejaVu Sans, system-ui, sans-serif">'
        f'<defs>{"".join(markers)}</defs>'
        f'<rect width="{ARCH_W}" height="988" rx="10" fill="{t.surface}"/>'
        f'{"".join(parts)}</svg>'
    )


def write_architecture_diagram():
    OUT.mkdir(parents=True, exist_ok=True)
    for t in THEMES:
        svg = build_architecture_svg(t)
        suffix = ".svg" if t.name == "light" else ".dark.svg"
        path = OUT / f"architecture{suffix}"
        path.write_text(svg)
        print(f"  wrote {path.relative_to(ROOT)}")


# ---------------------------------------------------- generated roofclf flow chart
#
# The architecture diagram shows roofclf as one box among five instruments, which is the
# right altitude there and useless for someone trying to follow what roofclf actually
# does. This one zooms into that single box: quadrat labels in at the top, two atlas
# numbers out at the bottom, one lane per stage of docs/methods/roofclf.md.
#
# Figures on this site read their numbers from files wherever a file exists, but data/ is
# gitignored and the docs CI has none of it, so the counts below are transcribed from the
# run that produced the published atlas and named here with their source file. Refresh
# them together with the prose on the roofclf page after a refit.
ROOFCLF_W = 1200
ROOFCLF_H = 1064
# data/roofclf/summary.json
ROOFCLF_STATS = {
    "n_quadrats": 23,
    "auc": 0.857,
    "auc_within_size": 0.830,
    "threshold": 0.2443,
    "precision": 0.50,
    "recall": 0.66,
}
# data/roofclf_national_with_sppi/pakistan/density/*_summary.json
ROOFCLF_CAPACITY = {
    "n_domain_cells": 1680,
    "n_national_cells": 4463,
    "verified_sub400": 2929,
    "best_sub400": 6531,
    "best_ge400_roof": 6427,
    "best_outdomain": 278,
}


def build_roofclf_svg(t: Theme) -> str:
    boxes: dict[str, tuple[float, float, float, float]] = {}
    parts: list[str] = []
    s = ROOFCLF_STATS
    cap = ROOFCLF_CAPACITY

    def box(key, x, y, w, h, title, lines, stroke=None):
        _svg_box(parts, boxes, t, key, x, y, w, h, title, lines, stroke)

    def arrow(k1, k2, color, *, from_side="bottom", to_side="top"):
        """Lane-to-lane connector. A vertical hop turns 12 px below the source box rather
        than halfway down the gap, because halfway is exactly where the next lane's label
        and the previous lane's footnote sit -- routing high keeps the gap's text band
        clear."""
        sx, sy = _svg_anchor(boxes, k1, from_side)
        tx, ty = _svg_anchor(boxes, k2, to_side)
        if from_side in ("left", "right") and abs(sy - ty) < 1:
            path = f"M{sx:.0f},{sy:.0f} H{tx:.0f}"
        else:
            turn = sy + 12
            path = f"M{sx:.0f},{sy:.0f} V{turn:.0f} H{tx:.0f} V{ty:.0f}"
        parts.append(f'<path d="{path}" stroke="{color}" stroke-width="1.7" fill="none" '
                     f'marker-end="url(#ah-{color.lstrip("#")}-{t.name})"/>')

    # Lane labels and footnotes are collected separately and emitted last, each on its own
    # surface-coloured plate. This flow has six lanes stacked in one column, so a connector
    # dropping from lane N to lane N+1 necessarily crosses the text in the gap between them;
    # painting that text over the lines is what keeps it readable.
    overlay: list[str] = []

    def _plate(text, x, y, size, above, below):
        w = len(text) * size * 0.54
        overlay.append(f'<rect x="{x - 4:.0f}" y="{y - above:.0f}" width="{w:.0f}" '
                       f'height="{above + below:.0f}" fill="{t.surface}"/>')

    def lane_label(text, y):
        _plate(text, ARCH_MARGIN, y, 11.3, 11, 4)
        overlay.append(f'<text x="{ARCH_MARGIN}" y="{y:.0f}" font-size="11.3" '
                       f'font-weight="600" fill="{t.ink_dim}">{_esc(text)}</text>')

    def note(text, y):
        _plate(text, ARCH_MARGIN, y, 9.6, 9, 4)
        overlay.append(f'<text x="{ARCH_MARGIN}" y="{y:.0f}" font-size="9.6" font-style="italic" '
                       f'fill="{t.ink_dim}">{_esc(text)}</text>')

    title = "roofclf: from a hand-mapped square kilometre to a national capacity number"
    subtitle = ("One question per building: does this roof carry PV. Asked exactly where the "
                "segmentation model cannot outline anything.")
    parts.append(f'<text x="{ARCH_MARGIN}" y="38" font-size="17.5" font-weight="600" '
                 f'fill="{t.ink}">{_esc(title)}</text>')
    parts.append(f'<text x="{ARCH_MARGIN}" y="60" font-size="12" fill="{t.ink_dim}">'
                 f'{_esc(subtitle)}</text>')

    # Lane A - inputs
    lane_label("1. Inputs, per calibration quadrat", 92)
    xa, wa = _row_x(3, gap=50)
    box("a1", xa[0], 100, wa, 86, "Calibration quadrat",
        ["a boundary a mapper declared", "Rule-1 complete: every visible", "panel inside it is mapped"])
    box("a2", xa[1], 100, wa, 86, "VIDA building footprints",
        ["every roof inside the boundary,", "including the sub-pixel ones", "OSM has never mapped"])
    box("a3", xa[2], 100, wa, 86, "Sentinel-2 composite",
        ["the same 10-band dry-season", "median the segmentation model", "reads. No new imagery"])

    # Lane B - the table
    lane_label("2. One row per building (roofclf.building_table)", 232)
    xb, wb = _row_x(2, gap=80)
    box("b1", xb[0], 240, wb, 92, "Label: has_pv",
        ["mapped PV covering 5% or more of", "the footprint is a positive; every", "other roof is a TRUE negative"])
    box("b2", xb[1], 240, wb, 92, "Features",
        ["log roof area, plus the 10 band", "means over the polygon and NDVI,", "NDBI, brightness and two ratios"])
    note("A no-PV building only counts as a negative because the quadrat is exhaustively "
         "mapped. Ordinary OpenStreetMap cannot supply that below 400 m2.", 362)

    # Lane C - fit and measure
    lane_label("3. Fit and measure honestly (earthpv roof-classifier)", 394)
    xc, wc = _row_x(3, gap=30)
    box("c1", xc[0], 402, wc, 104, "L2 logistic regression",
        ["scipy L-BFGS on standardised", "features. Linear on purpose: the", "output is summed, not thresholded"], stroke=t.s1)
    box("c2", xc[1], 402, wc, 104, "Leave one quadrat out",
        [f"{s['n_quadrats']} folds, each scored by a model", f"that never saw it: {s['auc']:.3f} AUC,",
         f"{s['auc_within_size']:.3f} within roof-size band"], stroke=t.s1)
    box("c3", xc[2], 402, wc, 104, "Deployment threshold",
        [f"p >= {s['threshold']:.4f}, chosen on pooled", f"held-out scores for precision {s['precision']:.2f}",
         f"at recall {s['recall']:.2f}"], stroke=t.s1)
    note("Folds are spatial by construction. A random split would put neighbouring roofs in "
         "train and test and report skill the model does not have.", 540)

    # Lane D - national scoring
    lane_label("4. Score the country (earthpv roofclf-score-national)", 572)
    dw, dx = ROOFCLF_W - 2 * ARCH_MARGIN, ARCH_MARGIN
    box("d1", dx, 580, dw, 88, "Every VIDA building, one 0.1 degree cell at a time",
        ["75.7M buildings get a p_roofclf, and SPPI from the same five bands at no extra read cost.",
         "Composite fill pixels are masked out, and overlapping tiles are deduped onto one canonical cell,",
         "because both once turned into millions of false positives along cell edges."], stroke=t.s1)

    # Lane E - probability to capacity
    lane_label("5. Probability to capacity (earthpv sub400-capacity, ge400-roof-capacity)", 706)
    xe, we = _row_x(3, gap=30)
    box("e1", xe[0], 714, we, 108, "Restrict to a known domain",
        ["keep only cells whose building", "density falls in the quadrats'",
         f"own range: {cap['n_domain_cells']:,} of {cap['n_national_cells']:,} cells"], stroke=t.s3)
    box("e2", xe[1], 714, we, 108, "Remove what is already counted",
        ["drop any flagged building within", "30 m of an existing detection or", "a mapped OSM installation"], stroke=t.s3)
    box("e3", xe[2], 714, we, 108, "Roof area to MWp",
        ["a coverage ratio measured per", "roof-size bin and density band,", "then the module kWp constant"], stroke=t.s3)
    note("Panels cover only part of a flagged roof. Assuming otherwise overstated this "
         "estimate by 2.4 to 2.7x until the coverage ratio replaced precision as the multiplier.", 856)

    # Lane F - atlas tiers
    lane_label("6. Into the evidence atlas", 886)
    xf, wf = _row_x(2, gap=60)
    box("f1", xf[0], 894, wf, 94, "Verified tier",
        [f"roofclf AND SPPI agreeing: {cap['verified_sub400']:,} MWp",
         "below 400 m2. Two instruments that", "share no training data must agree"], stroke=t.s2)
    box("f2", xf[1], 894, wf, 94, "Best estimate tier",
        [f"roofclf alone in domain {cap['best_sub400']:,} MWp, plus",
         f"{cap['best_ge400_roof']:,} MWp of >= 400 m2 roofs, plus",
         f"{cap['best_outdomain']} MWp extrapolated outside it"], stroke=t.s1)

    note("roofclf also REPLACES the segmentation model's own rooftop estimate for buildings "
         "at or above 400 m2 inside the same domain, where it measures better.", 1020)
    # Colour names have to hold in both themes, so the legend says warm / teal / blue
    # rather than orange / aqua: the same three slots render amber, aqua and light blue
    # against the dark surface.
    note("Warm outline = the roofclf trunk. Teal = the calibration steps that decide where "
         "roofclf is allowed to speak at all. Blue = the tier where a second, independent "
         "instrument has to agree.", 1038)

    for a, b in (("a1", "b1"), ("a2", "b1"), ("a2", "b2"), ("a3", "b2")):
        arrow(a, b, t.ink_dim)
    arrow("b1", "c1", t.ink_dim)
    arrow("b2", "c1", t.ink_dim)
    arrow("c1", "c2", t.s1, from_side="right", to_side="left")
    arrow("c2", "c3", t.s1, from_side="right", to_side="left")
    arrow("c3", "d1", t.s1)
    arrow("d1", "e1", t.s3)
    arrow("e1", "e2", t.s3, from_side="right", to_side="left")
    arrow("e2", "e3", t.s3, from_side="right", to_side="left")
    arrow("e3", "f2", t.s1)
    arrow("e3", "f1", t.s2)

    markers = _svg_markers(t)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ROOFCLF_W}" height="{ROOFCLF_H}" '
        f'viewBox="0 0 {ROOFCLF_W} {ROOFCLF_H}" font-family="DejaVu Sans, system-ui, sans-serif">'
        f'<defs>{"".join(markers)}</defs>'
        f'<rect width="{ROOFCLF_W}" height="{ROOFCLF_H}" rx="10" fill="{t.surface}"/>'
        f'{"".join(parts)}{"".join(overlay)}</svg>'
    )


def write_roofclf_diagram():
    OUT.mkdir(parents=True, exist_ok=True)
    for t in THEMES:
        svg = build_roofclf_svg(t)
        suffix = ".svg" if t.name == "light" else ".dark.svg"
        path = OUT / f"roofclf_flow{suffix}"
        path.write_text(svg)
        print(f"  wrote {path.relative_to(ROOT)}")


def write_svg_pair(template: str, stem: str):
    for t in THEMES:
        svg = template.format(surface=t.surface, ink=t.ink, dim=t.ink_dim, rule=t.rule,
                              card=t.card, s1=t.s1, s2=t.s2, s3=t.s3, sfx=t.name)
        suffix = ".svg" if t.name == "light" else ".dark.svg"
        path = OUT / f"{stem}{suffix}"
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_text(svg)
        print(f"  wrote {path.relative_to(ROOT)}")


# ------------------------------------------------------------------- raster crop


def crop_hero_map():
    """Trim the whitespace margins off the scientific capacity map for embedding."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        print("  pillow not installed, skipping hero crop")
        return
    Image.MAX_IMAGE_PIXELS = None
    src = ROOT / "results/pakistan_pv_density_scientific.png"
    if not src.exists():
        print(f"  {src.relative_to(ROOT)} missing, skipping hero crop")
        return
    im = Image.open(src).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    bbox = ImageChops.difference(im, bg).getbbox()
    if bbox:
        pad = 24
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad))
        im = im.crop(bbox)
    im.thumbnail((2200, 2200), Image.LANCZOS)
    dst = OUT / "pakistan_capacity_map.png"
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(dst, optimize=True)
    print(f"  wrote {dst.relative_to(ROOT)} ({im.width}x{im.height})")


# Data-dependent rasters generated outside this script (they read gitignored `data/`, so CI
# cannot rebuild them) and tracked in `results/`. Copied in verbatim; regenerate with
# `python scripts/plot_calib_quadrat.py`.
STATIC_RASTERS = [
    ("results/coastal-Karachi.png", "coastal-Karachi.png"),
]


def copy_static_rasters():
    import shutil

    OUT.mkdir(parents=True, exist_ok=True)
    for src_rel, name in STATIC_RASTERS:
        src = ROOT / src_rel
        if not src.exists():
            print(f"  {src_rel} missing, skipping")
            continue
        shutil.copyfile(src, OUT / name)
        print(f"  wrote {(OUT / name).relative_to(ROOT)}")


# Interactive pages the site embeds in an iframe. MkDocs only serves what lives
# under `docs/`, so the tracked originals in `results/` are copied in here.
#
# The evidence atlas is the exception (2026-08-06): it is this project's primary
# output, so its canonical copy lives directly at
# `docs/assets/interactive/pakistan_evidence_atlas.html` -- write there directly
# (`earthpv atlas --aoi <aoi> --out docs/assets/interactive/pakistan_evidence_atlas.html`)
# rather than through `results/` and this sync step. The other pages below still
# follow the `results/` + sync pattern; the same move is a reasonable follow-up for
# each but has not been done.
INTERACTIVE = [
    ("results/pakistan_pv_estimator_atlas.html", "pakistan_capacity_atlas.html"),
    ("results/glint_validation_pakistan/pv_pose_country2000.html", "pakistan_pv_pose.html"),
    ("results/pakistan_pv_density/pakistan_pv_density_map.html", "pakistan_density_map.html"),
    ("results/pakistan_pv_growth_atlas.html", "pakistan_growth_atlas.html"),
]


def sync_interactive():
    dst_dir = ROOT / "docs" / "assets" / "interactive"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src_rel, name in INTERACTIVE:
        src = ROOT / src_rel
        if not src.exists():
            print(f"  {src_rel} missing, skipping")
            continue
        (dst_dir / name).write_bytes(src.read_bytes())
        print(f"  wrote docs/assets/interactive/{name}")


# National-dashboard bundles (earthpv.dashboard.build_national_dashboard): each is a
# directory of a few files (the tab shell plus one copy per panel), not a single file,
# so this is a directory copy rather than a row in INTERACTIVE above.
INTERACTIVE_DIRS = [
    ("results/pakistan_pv_dashboard", "pakistan_dashboard"),
]


def sync_interactive_dirs():
    import shutil

    dst_root = ROOT / "docs" / "assets" / "interactive"
    for src_rel, name in INTERACTIVE_DIRS:
        src = ROOT / src_rel
        if not src.exists():
            print(f"  {src_rel} missing, skipping")
            continue
        shutil.copytree(src, dst_root / name, dirs_exist_ok=True)
        print(f"  wrote docs/assets/interactive/{name}/")


LOGO_SRC = ROOT / "docs" / "assets" / "earthpv-logo.png"
# The site's header bar, `--pv-bar` in the light scheme: the favicon plate matches the
# bar the logo sits on rather than being its own colour.
BRAND_BAR = (42, 34, 22)


def derive_logo():
    """Trim and recolour the source logo into the variants the site and README need.

    The source is a black mark on transparency, off-centre with wide margins. Black is
    invisible on the dark header bar and on a dark README, so a white variant is
    generated from the same alpha channel; nothing is redrawn.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  pillow not installed, skipping logo derivation")
        return
    if not LOGO_SRC.exists():
        print(f"  {LOGO_SRC.relative_to(ROOT)} missing, skipping logo derivation")
        return
    OUT.mkdir(parents=True, exist_ok=True)

    src = Image.open(LOGO_SRC).convert("RGBA")
    alpha = src.split()[-1]
    box = alpha.getbbox()
    mark = src.crop(box)

    # Square canvas with a small even margin, so the mark scales predictably wherever
    # it is placed and never sits off-centre.
    side = int(max(mark.size) * 1.08)
    for name, rgb in (("earthpv-logo-mark", (0, 0, 0)), ("earthpv-logo-mark-white", (255, 255, 255))):
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        tinted = Image.new("RGBA", mark.size, rgb + (0,))
        tinted.putalpha(mark.split()[-1])
        canvas.paste(tinted, ((side - mark.width) // 2, (side - mark.height) // 2), tinted)
        out = canvas.resize((512, 512), Image.LANCZOS)
        out.save(OUT / f"{name}.png", optimize=True)
        print(f"  wrote docs/assets/figures/{name}.png")

    # Favicon: the white mark on the brand bar colour, rounded, at browser-tab scale.
    size = 256
    fav = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plate = Image.new("RGBA", (size, size), BRAND_BAR + (255,))
    rounded = Image.new("L", (size, size), 0)
    ImageDraw.Draw(rounded).rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=255)
    fav.paste(plate, (0, 0), rounded)
    white = Image.open(OUT / "earthpv-logo-mark-white.png").resize(
        (int(size * 0.74), int(size * 0.74)), Image.LANCZOS)
    fav.paste(white, ((size - white.width) // 2, (size - white.height) // 2), white)
    fav.save(OUT / "favicon.png", optimize=True)
    print("  wrote docs/assets/figures/favicon.png")


def main():
    print("charts")
    for t in THEMES:
        fig_recall_by_size(t)
        fig_glint_by_size(t)
        fig_capacity_estimators(t)
        fig_model_recall_bins(t)
        fig_size_spectrum(t)
        fig_pv_pose(t)
        fig_glint_observability(t)
        fig_glint_pose_window(t)
        fig_glint_date_auc(t)
    print("diagrams")
    write_svg_pair(FLYWHEEL, "osm_ai_flywheel")
    write_svg_pair(PIPELINE_STRIP, "two_products")
    write_architecture_diagram()
    write_roofclf_diagram()
    print("logo")
    derive_logo()
    print("rasters")
    crop_hero_map()
    print("static rasters")
    copy_static_rasters()
    print("interactive pages")
    sync_interactive()
    sync_interactive_dirs()


if __name__ == "__main__":
    main()
